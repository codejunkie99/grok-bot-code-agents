#!/usr/bin/env bash
# install-codex-app-server.sh: run a resident `codex app-server` on a local WebSocket,
# kept alive by tmux + a watchdog, with a small control script. Idempotent: rerun any time.
#
#   bash scripts/install-codex-app-server.sh            # install (or refresh) and start
#   bash scripts/install-codex-app-server.sh --no-start # install only
#
# Settings (env vars, all optional; saved to $CODEX_DELEGATE_DIR/env.sh on install):
#   CODEX_APP_SERVER_URL   listen URL, loopback only   (default ws://127.0.0.1:4500)
#   CODEX_DELEGATE_DIR     state dir                    (default ~/.codex-delegate)
#   CODEX_DELEGATE_BIN     where scripts go             (default ~/.local/bin)
#   CODEX_DELEGATE_LOG     log file                     (default ~/logs/codex-app-server.log)
#   CODEX_DELEGATE_TMUX    tmux session name            (default codex-app-server)
#   CODEX_BIN              codex binary                 (default: `command -v codex`)
#   CODEX_DELEGATE_MODEL   default model for new threads (default: unset = codex config.toml)
#   CODEX_DELEGATE_FULL_ACCESS=1   OPT-IN ONLY. Server default becomes sandbox danger-full-access
#                          + approval_policy never. Codex can then read and change any file the
#                          user can (SSH keys, tokens, other repos). Leave unset unless you mean it.
# CODEX_HOME is left alone, so the server shares the CLI's login, config and session history.
set -euo pipefail

URL="${CODEX_APP_SERVER_URL:-ws://127.0.0.1:4500}"
DIR="${CODEX_DELEGATE_DIR:-$HOME/.codex-delegate}"
BIN="${CODEX_DELEGATE_BIN:-$HOME/.local/bin}"
LOG="${CODEX_DELEGATE_LOG:-$HOME/logs/codex-app-server.log}"
SESSION="${CODEX_DELEGATE_TMUX:-codex-app-server}"
CODEX="${CODEX_BIN:-$(command -v codex || true)}"
MODEL="${CODEX_DELEGATE_MODEL:-}"
FULL="${CODEX_DELEGATE_FULL_ACCESS:-0}"
START=1
[ "${1:-}" = "--no-start" ] && START=0

die() { echo "install: $*" >&2; exit 1; }
[ -n "$CODEX" ] && [ -x "$CODEX" ] || die "codex not found; install the Codex CLI and log in first (or set CODEX_BIN)"
command -v tmux >/dev/null || die "tmux is required"
command -v flock >/dev/null || die "flock (util-linux) is required"
command -v curl >/dev/null || die "curl is required (health checks)"
case "$URL" in
  ws://127.0.0.1:*|ws://localhost:*|ws://\[::1\]:*) ;;
  *) die "CODEX_APP_SERVER_URL must be a loopback ws:// URL (the server has no auth); got $URL" ;;
esac
PORT="${URL##*:}"; PORT="${PORT%%/*}"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "cannot parse port from $URL"

mkdir -p "$DIR" "$BIN" "$(dirname "$LOG")"

# ---- settings ---------------------------------------------------------------------------
cat > "$DIR/.env.sh.new" <<ENV
# Settings for the resident codex app-server (written by install-codex-app-server.sh).
CDA_DIR="$DIR"
CDA_URL="$URL"
CDA_PORT="$PORT"
CDA_HTTP="http://127.0.0.1:$PORT"
CDA_SESSION="$SESSION"
CDA_CODEX="$CODEX"
CDA_LOG="$LOG"
CDA_LOG_MAX_BYTES=\$((10 * 1024 * 1024))
CDA_MODEL="$MODEL"
CDA_FULL_ACCESS="$FULL"
CDA_BIN="$BIN"
ENV
cat >> "$DIR/.env.sh.new" <<'ENV'

cda_log() { echo "$(date -Is) [$1] ${*:2}" >> "$CDA_LOG"; }
# Server flags (bash array). Safe default: workspace-write sandbox with network, approvals on request.
cda_server_args() {
  if [ "$CDA_FULL_ACCESS" = 1 ]; then
    CDA_ARGS=(-c 'sandbox_mode="danger-full-access"' -c 'approval_policy="never"')
  else
    CDA_ARGS=(-c 'sandbox_mode="workspace-write"' -c 'sandbox_workspace_write.network_access=true' -c 'approval_policy="on-request"')
  fi
  [ -n "$CDA_MODEL" ] && CDA_ARGS+=(-c "model=\"$CDA_MODEL\"")
  return 0
}
# PIDs of our server (exact --listen URL match).
cda_server_pids() {
  local p args
  for p in $(pgrep -f -- "app-server .*--listen ${CDA_URL}" 2>/dev/null); do
    args=$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null) || continue
    case "$args" in *codex*app-server*"--listen ${CDA_URL}"*) echo "$p" ;; esac
  done
}
cda_ready() { curl -fsS -m 3 "${CDA_HTTP}/readyz" >/dev/null 2>&1; }
cda_rotate_log() {
  local sz; sz=$(stat -c %s "$CDA_LOG" 2>/dev/null || echo 0)
  [ "$sz" -gt "$CDA_LOG_MAX_BYTES" ] || return 0
  [ -f "$CDA_LOG.1" ] && mv -f "$CDA_LOG.1" "$CDA_LOG.2"
  cp "$CDA_LOG" "$CDA_LOG.1" && : > "$CDA_LOG"
  cda_log rotate "rotated log (was ${sz} bytes)"
}
ENV

# ---- keep loop (runs inside tmux) -------------------------------------------------------
cat > "$BIN/.codex-app-server-keep.new" <<KEEP
#!/usr/bin/env bash
# Keeps \`codex app-server\` running with backoff. Started by codex-app-server-ctl inside tmux.
set -u
. "$DIR/env.sh"
KEEP
cat >> "$BIN/.codex-app-server-keep.new" <<'KEEP'
exec 9> "$CDA_DIR/keep.lock"
flock -n 9 || { cda_log keep "another keep loop is running; exiting"; exit 0; }
trap 'cda_log keep "stopping (signal)"; kill $(cda_server_pids) 2>/dev/null; exit 0' HUP INT TERM
cd "$CDA_DIR" || exit 1        # neutral cwd; each thread passes its own cwd
backoff=5
while true; do
  [ -f "$CDA_DIR/stopped" ] && { cda_log keep "stopped flag set; exiting"; exit 0; }
  cda_rotate_log
  if [ -z "$(cda_server_pids)" ] && ss -Hltn "sport = :${CDA_PORT}" 2>/dev/null | grep -q .; then
    cda_log keep "port ${CDA_PORT} is used by another process; retry in 30s"; sleep 30; continue
  fi
  cda_server_args
  cda_log keep "starting: codex app-server ${CDA_ARGS[*]} --listen ${CDA_URL}"
  t0=$(date +%s)
  # Subscription login is the default: never inherit API-key environment overrides.
  env -u OPENAI_API_KEY -u CODEX_API_KEY "$CDA_CODEX" app-server "${CDA_ARGS[@]}" --listen "$CDA_URL" >> "$CDA_LOG" 2>&1 &
  wait $!; rc=$?
  ran=$(( $(date +%s) - t0 )); [ "$ran" -ge 120 ] && backoff=5
  cda_log keep "app-server exited rc=$rc after ${ran}s; restart in ${backoff}s"
  sleep "$backoff"; backoff=$(( backoff * 2 )); [ "$backoff" -gt 60 ] && backoff=60
done
KEEP

# ---- watchdog (detached, single instance) -----------------------------------------------
cat > "$BIN/.codex-app-server-watchdog.new" <<WD
#!/usr/bin/env bash
# Every 60s: recreate the tmux session if missing; kill a server that stopped answering /readyz.
set -u
. "$DIR/env.sh"
WD
cat >> "$BIN/.codex-app-server-watchdog.new" <<'WD'
exec 9> "$CDA_DIR/watchdog.lock"
flock -n 9 || exit 0
echo $$ > "$CDA_DIR/watchdog.pid"
bad=0
cda_log watchdog "starting (pid $$)"
while true; do
  if [ ! -f "$CDA_DIR/stopped" ]; then
    if ! tmux has-session -t "$CDA_SESSION" 2>/dev/null; then
      cda_log watchdog "tmux session $CDA_SESSION missing; recreating"
      tmux new-session -d -s "$CDA_SESSION" -c "$CDA_DIR" "$CDA_BIN/codex-app-server-keep"; bad=0
    elif [ -n "$(cda_server_pids)" ] && ! cda_ready; then
      bad=$((bad + 1)); cda_log watchdog "server not ready ($bad/3)"
      if [ "$bad" -ge 3 ]; then
        cda_log watchdog "killing unresponsive server"; kill $(cda_server_pids) 2>/dev/null
        sleep 5; kill -9 $(cda_server_pids) 2>/dev/null; bad=0
      fi
    else bad=0; fi
    cda_rotate_log
  fi
  sleep 60
done
WD

# ---- control script ---------------------------------------------------------------------
cat > "$BIN/.codex-app-server-ctl.new" <<CTL
#!/usr/bin/env bash
# codex-app-server-ctl status|start|stop|restart|schema [DIR]
set -u
. "$DIR/env.sh"
CTL
cat >> "$BIN/.codex-app-server-ctl.new" <<'CTL'
wd_up() { local p; p=$(cat "$CDA_DIR/watchdog.pid" 2>/dev/null) && [ -n "$p" ] && kill -0 "$p" 2>/dev/null \
  && grep -q codex-app-server-watchdog "/proc/$p/cmdline" 2>/dev/null; }
wd_start() { wd_up || setsid nohup "$CDA_BIN/codex-app-server-watchdog" >/dev/null 2>&1 < /dev/null & }
case "${1:-status}" in
  start)
    rm -f "$CDA_DIR/stopped"; wd_start
    tmux has-session -t "$CDA_SESSION" 2>/dev/null \
      || tmux new-session -d -s "$CDA_SESSION" -c "$CDA_DIR" "$CDA_BIN/codex-app-server-keep"
    for _ in $(seq 1 30); do cda_ready && { echo "ready on $CDA_URL"; exit 0; }; sleep 1; done
    echo "started, not ready yet; see $CDA_LOG" ;;
  stop)
    touch "$CDA_DIR/stopped"
    wd_up && kill "$(cat "$CDA_DIR/watchdog.pid")"
    tmux kill-session -t "$CDA_SESSION" 2>/dev/null
    sleep 1; p=$(cda_server_pids); [ -n "$p" ] && kill $p
    cda_log ctl "stopped"; echo stopped ;;
  restart)   # restart the server process only; the keep loop relaunches it
    p=$(cda_server_pids)
    if [ -n "$p" ]; then cda_log ctl "restart: killing $p"; kill $p; echo "restarting (keep loop relaunches in ~5s)"
    else "$0" start; fi ;;
  schema)    # regenerate JSON schemas for the installed codex version
    v=$("$CDA_CODEX" --version 2>/dev/null | awk '{print $NF}')
    out="${2:-${CODEX_SCHEMA_DIR:-$CDA_DIR/schema-$v}}"
    "$CDA_CODEX" app-server generate-json-schema --out "$out" \
      && "$CDA_CODEX" app-server generate-json-schema --experimental --out "$out-experimental" \
      && echo "schemas: $out (+ -experimental)" ;;
  status)
    echo "url:      $CDA_URL"
    echo "ready:    $(cda_ready && echo yes || echo no)"
    echo "tmux:     $(tmux has-session -t "$CDA_SESSION" 2>/dev/null && echo up || echo missing)"
    echo "watchdog: $(wd_up && echo up || echo down)"
    echo "server:   $(p=$(cda_server_pids); [ -n "$p" ] && echo "pid $p" || echo none)"
    echo "sandbox:  $([ "$CDA_FULL_ACCESS" = 1 ] && echo 'danger-full-access, approvals never (OPT-IN)' || echo 'workspace-write + network, approvals on-request')"
    [ -f "$CDA_DIR/stopped" ] && echo "note:     stopped flag set (run start)"
    echo "log:      $CDA_LOG" ;;
  *) echo "usage: $0 status|start|stop|restart|schema [DIR]"; exit 2 ;;
esac
CTL

# Swap files in atomically (new inode), so a running keep loop/watchdog is never edited in place.
mv -f "$DIR/.env.sh.new" "$DIR/env.sh"
for n in keep watchdog ctl; do chmod +x "$BIN/.codex-app-server-$n.new"; mv -f "$BIN/.codex-app-server-$n.new" "$BIN/codex-app-server-$n"; done
here="$(cd "$(dirname "$0")" && pwd)"
extra=""
if [ -f "$here/codex-sessions" ]; then install -m 755 "$here/codex-sessions" "$BIN/codex-sessions"; extra=", codex-sessions"; fi

echo "installed: $BIN/codex-app-server-{ctl,keep,watchdog}$extra; settings in $DIR/env.sh"
[ "$FULL" = 1 ] && echo "WARNING: CODEX_DELEGATE_FULL_ACCESS=1: no sandbox, no approvals. Codex can read any file you can."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: add $BIN to PATH" ;; esac
if [ "$START" = 1 ]; then
  # If our server is already up, restart it so new settings apply; otherwise start it.
  if [ -n "$(. "$DIR/env.sh"; cda_server_pids)" ]; then "$BIN/codex-app-server-ctl" restart; else "$BIN/codex-app-server-ctl" start; fi
fi
