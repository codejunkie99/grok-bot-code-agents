---
name: bot-codex-delegate
description: Use this when a Grok Bot hands coding or other long work to a local Codex CLI on its cloud computer. The bot acts as the coordinator and a resident `codex app-server` is its worker: dispatch a turn in one background Shell call, get woken when it completes, steer or interrupt mid-turn, and reuse one named Codex session per project and task type.
---

# Delegate work to a resident Codex app-server

## Why
Driving Codex turn by turn and checking on it every round spends the bot's own quota just
watching. Ending the conversation instead lets the cloud computer sleep, and Codex stalls with
it. A progress-check routine starts a fresh bot each time, which re-reads the context and fires
at imprecise times.

What works: treat Codex like a cloud agent in a project. The bot dispatches a turn with **one
background Shell call** that returns only when the turn completes. Completion wakes the bot. No
turns are spent in between, so the quota goes to Codex doing the work.

## 1. Setup (once per computer)
Codex CLI must be installed and logged in. Then:

```bash
git clone https://github.com/realTaki/bot-codex-delegate
bash bot-codex-delegate/scripts/install-codex-app-server.sh
codex-app-server-ctl status
```

The installer is idempotent. It runs `codex app-server --listen ws://127.0.0.1:4500` in a tmux
session, adds a watchdog that recreates the session or kills a hung server, a control script
(`codex-app-server-ctl status|start|stop|restart|schema`), logs under `~/logs/`, and the
`codex-sessions` helper. Settings come from env vars (see the script header) and are saved to
`~/.codex-delegate/env.sh`; `CODEX_APP_SERVER_URL` changes the listen endpoint (loopback only, since
the server has no auth). It leaves `CODEX_HOME` alone, so the server shares the CLI's login,
config and session history.

Defaults: sandbox `workspace-write` with network access, approval policy `on-request`, model
from Codex's own config. Full access (`danger-full-access` + approvals `never`) is opt-in only
via `CODEX_DELEGATE_FULL_ACCESS=1`. Never turn it on by yourself: with it, Codex can read and
change any file the user can, including keys and tokens outside the project. Ask the user first.

After a Codex upgrade, run `codex-app-server-ctl schema [DIR]` to regenerate the JSON schemas
and check method names there, then `codex-app-server-ctl restart`.

Run **one** server per computer. All bots on the computer share it. Check
`codex-app-server-ctl status` before installing or starting anything.

## 2. Protocol in short
WebSocket, JSON-RPC 2.0, one JSON message per text frame. Health: `/readyz`, `/healthz`.

- `initialize {clientInfo}` → notification `initialized`. Pass
  `capabilities.experimentalApi: true` only if you need experimental methods.
- `thread/start {cwd, sandbox: "workspace-write"}`. Always pass the project's `cwd`; never rely
  on the server's own directory. Save `thread.id`.
- `turn/start {threadId, input: [{type: "text", text}], effort?}` → stream events → wait for
  `turn/completed`. Effort and model can be set per turn.
- A new connection must `thread/resume {threadId}` before any `turn/*` on an existing thread.
- With approval policy `on-request`, the server may send approval requests (commands, file
  changes) to the client. The driver must answer them (accept or decline) or the turn waits.

### Driver: `scripts/codex_ws.py`
One stdlib-only Python file ([docs](../../scripts/codex_ws.README.md)). Global flags go **before**
the subcommand; events stream to stderr, JSON results to stdout.

```bash
D=bot-codex-delegate/scripts/codex_ws.py
python3 $D start --cwd <repo> [--model <model>] [--effort medium] ["<first task>"]   # prints threadId
python3 $D turn <threadId> "<task>" [--effort medium] [--steer "<extra>"] [--interrupt-after SEC]
python3 $D steer <threadId> <turnId> "<extra>"      # from another process, mid-turn
python3 $D interrupt <threadId> <turnId>
python3 $D list [--cwd <repo>] [--limit 20]         # read-only
python3 $D read <threadId> [--turns]                # read-only
python3 $D --state threads.json saved               # optional local registry (start --label ...)
```

- Endpoint: `--host`/`--port` or `CODEX_WS_HOST`/`CODEX_WS_PORT` (default `127.0.0.1:4500`).
- Model: `start --model` or `CODEX_WS_MODEL`; unset means the server's default.
- Registry: `--state FILE` or `CODEX_WS_STATE`; off unless set.
- Safe defaults: `workspace-write` with network, `approvalPolicy: on-request`, and approval
  requests are **declined**. `--approve accept|acceptForSession` answers them yes; `--no-network`
  or `--sandbox read-only` tighten it.
- `start --danger-full-access` (and `--approval never`) are opt-in only and need the user's
  explicit OK: Codex could then read, change or send any file the server's user can reach.
- `turn` resumes the thread first, prints the `turnId` right away, and exits 0 on `completed` or
  `interrupted`.

## 3. Dispatch and get woken
1. Find or create the session (section 5).
2. Start the turn with **one** Shell call, `block_until_ms: 0`, that waits for
   `turn/completed`, for example:
   `python3 codex_ws.py turn <threadId> "<task>" --effort medium 2> /tmp/<name>.events.log`
   It prints the `turnId` first and the final message and status at the end.
3. **Verify the launch**: check once that the turn started (a `turn/started` event or the log
   growing). Then end your turn. Do not poll, and do not open a turn just to check progress.
4. When the Shell call finishes, you are woken. Review the diff yourself, then report or send the
   next turn.

Keep your own queue for follow-ups and send the next `turn/start` after `turn/completed`.

## 4. Steer and interrupt
- **Steer** (add instructions to a running turn): `turn/steer {threadId, expectedTurnId, input}`,
  or `codex_ws.py steer <threadId> <turnId> "<text>"`. `expectedTurnId` must be the active turn.
- **Interrupt**: `turn/interrupt {threadId, turnId}` (`codex_ws.py interrupt <threadId> <turnId>`)
  → `turn/completed` with `status: "interrupted"`. The thread stays usable.
- **Interrupt is not a hard stop.** Commands already scheduled in the interrupted turn can keep
  running and land later. After an interrupt, check the working tree (`git status`, `git diff`)
  before sending more, and filter events by `turnId`. If side effects must stop for sure, abandon
  that thread and start a fresh one.

## 5. Reuse sessions
A session keeps the project context; a new one re-reads the whole project. Keep **one named
session per project × task type**, and send every new prompt of that type into it.

- **Name**: `<bot>-<project>-<task type>`, for example `mybot-website-frontend`. Bot name as it
  appears in the app, project = repo or folder name, task type = a short stable label. The name
  is the thread's Codex title, so other bots and the user see it.
- **Find**: `thread/list {searchTerm: "<bot>-<project>", sourceKinds: ["cli","vscode","exec","appServer"]}`
  (the default list leaves out `codex exec` sessions). Filter by folder with `cwd`.
  `codex-sessions find <term>` does the same.
- **Found**: `thread/resume {threadId}`, then `turn/start`.
- **None fits**: `thread/start` with the right `cwd`, run the first turn, then
  `thread/name/set {threadId, name}` (`codex-sessions name <id> "<name>"`). A new thread is not
  listed until after its first turn.
- **Long context** (slow turns, `contextWindowExceeded`): `thread/compact/start {threadId}`
  (`codex-sessions compact <id>`). The session and its name stay.
- **Task type done**: `thread/archive {threadId}` (`codex-sessions archive <id>`). `--archived`
  lists it, `unarchive` brings it back.
- `codex exec` sessions live in the same store; name them the same way and resume them with
  `codex exec resume <id>`.

## 6. Rules
- One server per computer. Don't start a second one; use `codex-app-server-ctl`.
- **Never two writers in one working tree.** Parallel work needs a separate clone and its own
  session.
- Tell Codex explicitly whether to commit or push, and to which branch.
- Dispatch with `block_until_ms: 0` and let completion wake you. No progress-check turns, no
  detached `nohup` runs that finish silently.
- Verify the launch before telling anyone it is running.
- Keep safe defaults. Full access only when the user asks for it.
- Never paste secrets into prompts or print auth files.
- **Long runs**: the cloud computer sleeps when no bot turn is active, and a sleeping computer
  freezes Codex too. For runs that must not pause, pair this with
  [bot-keepalive](https://github.com/realTaki/bot-keepalive).
