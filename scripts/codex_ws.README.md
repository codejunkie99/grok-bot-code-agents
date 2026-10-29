# codex_ws.py

A small driver that lets a bot or orchestrator use [Codex](https://github.com/openai/codex) as its coding agent.
It talks to a running `codex app-server` over its WebSocket JSON-RPC 2.0 transport, so you can start threads,
run turns, steer or interrupt them, and list or read threads from a script or from another program.

It's one Python file using only the standard library (Python 3.8+, no `pip install`). You can use it as a CLI
or import it as a library.

## Prerequisites

- Codex CLI is installed and logged in (`codex login`).
- A `codex app-server` is running with a WebSocket listener the driver can reach, for example:

  ```sh
  codex app-server --listen ws://127.0.0.1:4500
  ```

  Bind to `127.0.0.1` only. The app-server runs commands on your machine, so don't expose it to a network.

## Endpoint and configuration

| Setting | CLI flag | Env var | Default |
|---|---|---|---|
| Host | `--host` | `CODEX_WS_HOST` | `127.0.0.1` |
| Port | `--port` | `CODEX_WS_PORT` | `4500` |
| Turn idle timeout (seconds) | `--turn-timeout` | `CODEX_WS_TURN_TIMEOUT` | `900` |
| Model | `start --model` | `CODEX_WS_MODEL` | server default (not sent) |
| Thread registry file | `--state` | `CODEX_WS_STATE` | off |

Global flags (`--host`, `--port`, `--turn-timeout`, `--state`, `-v`, `--approve`) go **before** the subcommand.
Events stream to stderr; JSON results go to stdout.

## Subcommands

### `start`: create a thread, optionally run a first turn

```sh
python3 codex_ws.py start --cwd ./my-repo
python3 codex_ws.py start --cwd ./my-repo --model gpt-5 --effort low "add a unit test for parse()"
```

Prints `{"threadId", "model", "cwd", "approvalPolicy", "sandbox"}`. If you pass a prompt, it then streams that
turn the same way `turn` does.
Options: `--sandbox read-only|workspace-write`, `--no-network`, `--danger-full-access` (see Security),
`--approval untrusted|on-request|never`, `--effort`, `--label`.

### `turn`: run a turn on an existing thread and wait for it to finish

```sh
python3 codex_ws.py turn <threadId> "now run the tests and fix failures" --effort medium
python3 codex_ws.py turn <threadId> "refactor X" --steer "keep the public API unchanged"
python3 codex_ws.py turn <threadId> "long task" --interrupt-after 120
```

Calls `thread/resume` first, then `turn/start`, and streams until `turn/completed`. It prints the
`turnId` right away and ends with `{"turnId", "status", "error", "durationMs", "finalMessage"}`. The exit code
is 0 when the status is `completed` or `interrupted`. `--steer` sends its text once the first command starts.

The wait uses an **idle** timeout, not a total wall-clock cap: `--turn-timeout SEC` (env `CODEX_WS_TURN_TIMEOUT`,
default 900) gives up only after SEC seconds with no new events from the server. Long turns are never killed
while Codex is still streaming. It is a global option, so put it before the subcommand:
`python3 codex_ws.py --turn-timeout 1800 turn <threadId> "..."`.

### `steer`: add input to an active turn (from another process)

```sh
python3 codex_ws.py steer <threadId> <turnId> "also update the changelog"
```

### `interrupt`: stop an active turn

```sh
python3 codex_ws.py interrupt <threadId> <turnId>
```

Note: commands that are already queued can still run after `turn/completed` reports `interrupted`. If side
effects matter, check the workspace yourself.

### `list` and `read`

```sh
python3 codex_ws.py list --cwd ./my-repo --limit 10     # thread/list
python3 codex_ws.py read <threadId> --turns              # thread/read (with turns and items)
```

### `saved`: show the optional local registry

```sh
python3 codex_ws.py --state ./threads.json start --cwd ./my-repo --label mybot-myproject-bugfix
python3 codex_ws.py --state ./threads.json saved
```

The registry is off unless you set `--state` or `CODEX_WS_STATE`. When it's on, it's a plain JSON list:

```json
[{"id": "<threadId>", "label": "mybot-myproject-bugfix", "cwd": "/path/to/my-repo",
  "model": "<model>", "created": "2026-01-01T12:00:00+0000"}]
```

The label is free text. One naming scheme you could use is `<bot>-<project>-<task-type>`.

## Library use

```python
from codex_ws import Codex
c = Codex(host="127.0.0.1", port=4500, on_event=print)
c.connect()                                        # initialize + initialized
tid  = c.thread_start("/abs/path/to/repo")["thread"]["id"]
turn = c.turn_start(tid, "do X", effort="low")["turn"]
c.turn_steer(tid, turn["id"], "also Y")
done = c.wait_turn(tid, turn["id"])                # params of turn/completed
c.call("thread/loaded/list", {})                   # any raw JSON-RPC method
```

The client is single-threaded. Notifications that arrive while it waits for a response are buffered,
server pings get an automatic pong, and approval requests get the `approve=` answer (default `decline`).

Methods used: `initialize`, `initialized`, `thread/start`, `thread/resume`, `thread/list`, `thread/read`,
`turn/start`, `turn/steer`, `turn/interrupt`. To see the exact protocol your Codex version speaks, generate its schema:
`codex app-server generate-json-schema --out ./schema`.

## Security

**Default: `workspace-write` sandbox, network on, `approvalPolicy: on-request`, approval requests declined.**
Codex can read files and write inside the thread's `cwd` (plus the temp dirs the sandbox allows), and it can
reach the network. Any request to step outside the sandbox gets declined unless you pass `--approve accept`
or `--approve acceptForSession`. Use `--no-network` to turn network off, or `--sandbox read-only` to block writes.

**`--danger-full-access` is opt-in. Read this before you use it.** It turns the sandbox off. Codex can then
read, change, or delete **any file the app-server's user can access**, not just the project. That includes
unrelated private data such as SSH and GPG private keys (`~/.ssh`), cloud credentials (`~/.aws`, `~/.config/gcloud`),
API tokens, browser profiles, password-manager exports, and other repos. Codex can also send that data over the
network. A prompt injection in a file, issue, web page, or dependency that Codex reads could make it do any of
these things. Combined with `--approval never`, nobody reviews any of this before it happens. Only use
it inside a disposable VM or container that holds no secrets you care about.

Other notes:
- Keep the app-server on loopback. The WebSocket has no authentication of its own, so anyone who can reach
  the port can run commands as that user.
- Point threads at the repo you intend to change, not at your home directory.

## License

MIT
