#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""codex_ws.py - tiny stdlib-only driver for a running `codex app-server`
(WebSocket transport, JSON-RPC 2.0). Lets a bot / orchestrator use Codex as its
coding agent: start threads, run turns, steer or interrupt them, list and read threads.

Endpoint defaults to ws://127.0.0.1:4500; override with --host/--port or
CODEX_WS_HOST / CODEX_WS_PORT. Model defaults to the server's default; override
with --model or CODEX_WS_MODEL.

SECURITY: new threads default to sandbox "workspace-write" (network on) with
approvalPolicy "on-request"; approval requests are declined unless --approve says
otherwise. "danger-full-access" is opt-in only (--danger-full-access) and lets
Codex read and write ANY file the server user can reach. See README.md.

Library:
    from codex_ws import Codex
    c = Codex(); c.connect()                       # initialize + initialized
    tid = c.thread_start(cwd="/abs/dir")["thread"]["id"]
    turn = c.turn_start(tid, "do X", effort="low")["turn"]
    c.turn_steer(tid, turn["id"], "also do Y")
    c.turn_interrupt(tid, turn["id"])
    done = c.wait_turn(tid, turn["id"])            # -> turn/completed params
CLI: python3 codex_ws.py -h
"""
import argparse, base64, collections, json, os, socket, struct, sys, time

DEFAULT_HOST = os.environ.get("CODEX_WS_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("CODEX_WS_PORT", "4500"))
DEFAULT_MODEL = os.environ.get("CODEX_WS_MODEL") or None     # None -> server default
DEFAULT_SANDBOX = "workspace-write"
DEFAULT_APPROVAL = "on-request"
# Optional local registry of threads created by this script. Disabled unless set.
DEFAULT_STATE = os.environ.get("CODEX_WS_STATE") or None


class WSClosed(Exception):
    pass


class WS:
    """Minimal RFC6455 client (text frames, client masking, auto-pong)."""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=30):
        self.s = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = self.s.recv(4096)
            if not d:
                raise WSClosed("closed during handshake")
            buf += d
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise WSClosed("handshake failed: " + head.split(b"\r\n")[0].decode())

    def _read(self, n):
        while len(self.buf) < n:
            d = self.s.recv(65536)
            if not d:
                raise WSClosed("socket closed")
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, op, data):
        n, mask = len(data), os.urandom(4)
        if n < 126:
            hdr = struct.pack("!BB", 0x80 | op, 0x80 | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x80 | op, 0x80 | 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x80 | op, 0x80 | 127, n)
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def send(self, obj):
        self._frame(0x1, json.dumps(obj).encode())

    def recv(self, timeout=None):
        """Return one JSON message, or None on timeout (only checked between frames)."""
        self.s.settimeout(timeout)
        msg = b""
        while True:
            try:
                b1, b2 = self._read(2)
            except socket.timeout:
                if msg:
                    continue
                return None
            self.s.settimeout(None)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            payload, op = self._read(n), b1 & 0x0F
            if op == 0x9:
                self._frame(0xA, payload); continue
            if op == 0xA:
                continue
            if op == 0x8:
                raise WSClosed("server closed")
            msg += payload
            if b1 & 0x80:
                return json.loads(msg)

    def close(self):
        try:
            self._frame(0x8, b""); self.s.close()
        except OSError:
            pass


class RPCError(Exception):
    def __init__(self, method, err):
        super().__init__(f"{method}: {err.get('code')} {err.get('message')}")
        self.error = err


class Codex:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, on_event=None, approve="decline",
                 state_file=None):
        self.host, self.port, self.ws, self.next_id = host, port, None, 1
        self.events = collections.deque()          # buffered server notifications
        self.on_event = on_event                   # callback(msg) for every notification
        self.approve = approve                     # answer for server approval requests
        self.state_file = state_file               # optional local thread registry (JSON)

    # --- transport -------------------------------------------------------
    def connect(self, name="codex_ws", version="0.1", experimental=False):
        self.ws = WS(self.host, self.port)
        p = {"clientInfo": {"name": name, "title": "codex_ws driver", "version": version}}
        if experimental:
            p["capabilities"] = {"experimentalApi": True}
        res = self.call("initialize", p)
        self.ws.send({"jsonrpc": "2.0", "method": "initialized"})
        return res

    def close(self):
        if self.ws:
            self.ws.close()

    def _handle(self, m):
        if "method" in m and "id" in m:            # server -> client request
            self._answer_server_request(m)
        elif "method" in m:                         # notification
            self.events.append(m)
            if self.on_event:
                self.on_event(m)

    def _answer_server_request(self, m):
        meth = m["method"]
        if meth in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            result = {"decision": self.approve}     # accept|acceptForSession|decline|cancel
        elif meth in ("execCommandApproval", "applyPatchApproval"):   # legacy v1
            result = {"decision": "approved" if self.approve.startswith("accept") else "denied"}
        else:
            self.ws.send({"jsonrpc": "2.0", "id": m["id"],
                          "error": {"code": -32601, "message": f"codex_ws: unsupported {meth}"}})
            return
        print(f"[codex_ws] server request {meth} -> {result}", file=sys.stderr)
        self.ws.send({"jsonrpc": "2.0", "id": m["id"], "result": result})

    def call(self, method, params=None, timeout=120):
        rid, self.next_id = self.next_id, self.next_id + 1
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.ws.send(msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = self.ws.recv(timeout=max(0.1, deadline - time.time()))
            if m is None:
                break
            if m.get("id") == rid and "method" not in m:
                if "error" in m:
                    raise RPCError(method, m["error"])
                return m.get("result")
            self._handle(m)
        raise TimeoutError(method)

    def next_event(self, timeout=None):
        """Pop a buffered notification or read the next one (None on timeout)."""
        deadline = None if timeout is None else time.time() + timeout
        while not self.events:
            left = None if deadline is None else deadline - time.time()
            if left is not None and left <= 0:
                return None
            m = self.ws.recv(timeout=left)
            if m is None:
                return None
            self._handle(m)
        return self.events.popleft()

    # --- API: method names / params per the app-server protocol schema ---------
    # (regenerate locally with: codex app-server generate-json-schema --out DIR)
    def thread_start(self, cwd, model=None, sandbox=DEFAULT_SANDBOX, approval=DEFAULT_APPROVAL,
                     effort=None, network=True, **extra):
        p = {"cwd": os.path.abspath(cwd), "sandbox": sandbox, "approvalPolicy": approval, **extra}
        model = model or DEFAULT_MODEL
        if model:
            p["model"] = model
        if effort:                                  # no top-level effort in ThreadStartParams
            p.setdefault("config", {})["model_reasoning_effort"] = effort
        if sandbox == "workspace-write":            # config.toml: sandbox_workspace_write.network_access
            p.setdefault("config", {})["sandbox_workspace_write"] = {"network_access": bool(network)}
        r = self.call("thread/start", p)
        if self.state_file:
            save_thread(self.state_file, r["thread"]["id"], p["cwd"], r.get("model"))
        return r

    def thread_resume(self, thread_id, **extra):
        return self.call("thread/resume", {"threadId": thread_id, **extra})

    def thread_list(self, limit=20, cwd=None, **extra):
        p = {"limit": limit, **extra}
        if cwd:
            p["cwd"] = os.path.abspath(cwd)
        return self.call("thread/list", p)

    def thread_read(self, thread_id, include_turns=False):
        return self.call("thread/read", {"threadId": thread_id, "includeTurns": include_turns})

    @staticmethod
    def text(t):
        return [{"type": "text", "text": t}]

    def turn_start(self, thread_id, text, effort=None, **extra):
        p = {"threadId": thread_id, "input": self.text(text), **extra}
        if effort:
            p["effort"] = effort
        return self.call("turn/start", p)

    def turn_steer(self, thread_id, expected_turn_id, text):
        return self.call("turn/steer", {"threadId": thread_id, "expectedTurnId": expected_turn_id,
                                        "input": self.text(text)})

    def turn_interrupt(self, thread_id, turn_id):
        return self.call("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})

    def wait_turn(self, thread_id, turn_id=None, timeout=900, until=None):
        """Consume events until turn/completed for this thread (and turn id, if given).
        `until(msg)` returning True stops early and returns that msg instead."""
        deadline = time.time() + timeout
        while True:
            m = self.next_event(timeout=max(0.1, deadline - time.time()))
            if m is None:
                raise TimeoutError("turn did not complete")
            if until and until(m):
                return m
            p = m.get("params") or {}
            if m["method"] == "turn/completed" and p.get("threadId") == thread_id and \
                    (turn_id is None or p["turn"]["id"] == turn_id):
                return p


# --- optional thread registry ----------------------------------------------
def load_threads(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_thread(path, tid, cwd, model, label=None):
    data = [t for t in load_threads(path) if t["id"] != tid]
    data.append({"id": tid, "label": label, "cwd": cwd, "model": model,
                 "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


# --- CLI ---------------------------------------------------------------------
def printer(verbose):
    def on_event(m):
        meth, p = m["method"], m.get("params") or {}
        if meth == "item/agentMessage/delta":
            if verbose:
                sys.stderr.write(p.get("delta", "")); sys.stderr.flush()
        elif meth in ("item/started", "item/completed"):
            it = p.get("item", {})
            extra = it.get("command") or it.get("status") or ""
            if it.get("type") == "agentMessage" and meth == "item/completed":
                extra = (it.get("text") or "")[:400]
            print(f"[{meth}] {it.get('type')} {extra}", file=sys.stderr)
        elif meth in ("turn/started", "turn/completed"):
            t = p.get("turn", {})
            print(f"[{meth}] turn={t.get('id')} status={t.get('status')} error={t.get('error')}", file=sys.stderr)
        elif meth == "error" or verbose:
            print(f"[{meth}] {json.dumps(p)[:300]}", file=sys.stderr)
    return on_event


def main(argv=None):
    ap = argparse.ArgumentParser(description="Drive a running codex app-server over WebSocket JSON-RPC")
    ap.add_argument("--host", default=DEFAULT_HOST, help="app-server host (env CODEX_WS_HOST, default %(default)s)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="app-server port (env CODEX_WS_PORT, default %(default)s)")
    ap.add_argument("--state", default=DEFAULT_STATE, metavar="FILE",
                    help="optional JSON registry of threads created by `start` (env CODEX_WS_STATE; off if unset)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--approve", default="decline", choices=["accept", "acceptForSession", "decline", "cancel"],
                    help="answer for command/fileChange approval requests (default decline)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", help="thread/start (+ optional first turn)")
    s.add_argument("--cwd", required=True, help="workspace directory for the thread")
    s.add_argument("--model", default=DEFAULT_MODEL, help="model id (env CODEX_WS_MODEL; default: server default)")
    s.add_argument("--sandbox", default=DEFAULT_SANDBOX, choices=["read-only", "workspace-write"],
                   help="sandbox mode (default %(default)s); use --danger-full-access to disable the sandbox")
    s.add_argument("--no-network", action="store_true", help="disable network access inside workspace-write")
    s.add_argument("--danger-full-access", action="store_true",
                   help="OPT-IN: no sandbox, Codex can read/write ANY file the server user can (see README)")
    s.add_argument("--approval", default=DEFAULT_APPROVAL, choices=["untrusted", "on-request", "never"],
                   help="approvalPolicy (default %(default)s)")
    s.add_argument("--label", help="free-form label stored in the --state registry, e.g. mybot-myproject-bugfix")
    s.add_argument("--effort"); s.add_argument("text", nargs="?")
    t = sub.add_parser("turn", help="thread/resume + turn/start, stream until turn/completed")
    t.add_argument("thread"); t.add_argument("text"); t.add_argument("--effort")
    t.add_argument("--steer", help="text sent via turn/steer once the first command item starts")
    t.add_argument("--interrupt-after", type=float, metavar="SEC", help="turn/interrupt after SEC seconds")
    for name, hlp in (("steer", "turn/steer an active turn"), ("interrupt", "turn/interrupt an active turn")):
        x = sub.add_parser(name, help=hlp); x.add_argument("thread"); x.add_argument("turn")
        if name == "steer":
            x.add_argument("text")
    l = sub.add_parser("list", help="thread/list"); l.add_argument("--cwd"); l.add_argument("--limit", type=int, default=20)
    r = sub.add_parser("read", help="thread/read"); r.add_argument("thread"); r.add_argument("--turns", action="store_true")
    sub.add_parser("saved", help="print the --state registry")
    a = ap.parse_args(argv)

    if a.cmd == "saved":
        if not a.state:
            print("no registry configured (use --state FILE or CODEX_WS_STATE)", file=sys.stderr); return 2
        print(json.dumps(load_threads(a.state), indent=1)); return 0
    c = Codex(a.host, a.port, on_event=printer(a.verbose), approve=a.approve)
    c.connect()
    try:
        if a.cmd == "list":
            out = c.thread_list(a.limit, a.cwd)
            for th in out["data"]:
                print(th["id"], th.get("status", {}).get("type"), th["cwd"], (th.get("preview") or "")[:60].replace("\n", " "))
            return 0
        if a.cmd == "read":
            print(json.dumps(c.thread_read(a.thread, a.turns), indent=1)[:20000]); return 0
        if a.cmd == "start":
            sandbox = "danger-full-access" if a.danger_full_access else a.sandbox
            if a.danger_full_access:
                print("[codex_ws] WARNING: danger-full-access - no sandbox, Codex can read/write any file "
                      "this user can (including unrelated private keys and credentials)", file=sys.stderr)
            r0 = c.thread_start(a.cwd, a.model, sandbox, a.approval, a.effort, network=not a.no_network)
            tid = r0["thread"]["id"]
            if a.state:
                save_thread(a.state, tid, r0.get("cwd") or os.path.abspath(a.cwd), r0.get("model"), a.label)
            print(json.dumps({"threadId": tid, "model": r0.get("model"), "cwd": r0.get("cwd"),
                              "approvalPolicy": r0.get("approvalPolicy"), "sandbox": r0.get("sandbox")}))
            if not a.text:
                return 0
            a.thread, a.steer, a.interrupt_after = tid, None, None
        else:
            c.thread_resume(a.thread, excludeTurns=True)   # (re)join the thread on this connection
        if a.cmd == "steer":
            print(json.dumps(c.turn_steer(a.thread, a.turn, a.text))); return 0
        if a.cmd == "interrupt":
            print(json.dumps(c.turn_interrupt(a.thread, a.turn))); return 0
        # turn (or start with text)
        turn = c.turn_start(a.thread, a.text, effort=a.effort)["turn"]
        print(json.dumps({"threadId": a.thread, "turnId": turn["id"]}), flush=True)
        t0, steered, interrupted = time.time(), False, False

        def until(m):
            nonlocal steered, interrupted
            if a.steer and not steered and m["method"] == "item/started" and \
                    m["params"]["item"].get("type") == "commandExecution":
                steered = True
                print(json.dumps({"steer": c.turn_steer(a.thread, turn["id"], a.steer)}), flush=True)
            if a.interrupt_after and not interrupted and time.time() - t0 >= a.interrupt_after:
                interrupted = True
                print(json.dumps({"interrupt": c.turn_interrupt(a.thread, turn["id"])}), flush=True)
            return False

        while True:
            try:
                done = c.wait_turn(a.thread, turn["id"], timeout=1 if a.interrupt_after and not interrupted else 900,
                                   until=until)
                break
            except TimeoutError:
                if not (a.interrupt_after and not interrupted):
                    raise
                until({"method": "_tick"})
        tt = done["turn"]
        msgs = [i.get("text") for i in tt.get("items", []) if i.get("type") == "agentMessage"]
        if not msgs:   # completed notification may carry no items; fetch them
            th = c.thread_read(a.thread, True)["thread"]
            for t_ in th.get("turns", []):
                if t_["id"] == turn["id"]:
                    msgs = [i.get("text") for i in t_.get("items", []) if i.get("type") == "agentMessage"]
        print(json.dumps({"turnId": tt["id"], "status": tt["status"], "error": tt.get("error"),
                          "durationMs": tt.get("durationMs"), "finalMessage": msgs[-1] if msgs else None},
                         ensure_ascii=False))
        return 0 if tt["status"] in ("completed", "interrupted") else 1
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
