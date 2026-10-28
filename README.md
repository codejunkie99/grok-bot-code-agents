# bot-codex-delegate

**Let your [Grok Bot](https://x.ai/bot) run Codex the way a Cursor Project runs cloud agents: hand off the work, get woken when it's done.**

The bot is the coordinator. A resident `codex app-server` on the bot's cloud computer is its worker. Codex spends the quota, not the bot.

[中文说明](#中文说明)

---

## The problem

As [@0xmomonifty](https://x.com/0xmomonifty/status/2115269648698716426) put it: when Grok Bot drives Codex, it babysits it.

- **Babysitting burns bot quota.** The bot checks progress round after round. Its own quota goes to keeping Codex company.
- **Letting go stalls Codex.** If the bot ends its conversation, the cloud computer goes to sleep when no bot turn is active, and Codex freezes with it.
- **Routines don't help.** A progress-check routine is a fresh bot every time, re-reading the context, and it doesn't fire on time.

## The fix

Treat Codex like a cloud agent inside a project.

1. **A resident server.** `codex app-server` on `ws://127.0.0.1:4500` (WebSocket JSON-RPC, localhost only), kept up by tmux and a watchdog, with `/readyz` and `/healthz`. Same login and session history as the Codex CLI.
2. **Dispatch, then get woken.** The bot sends a turn in one background Shell call that returns on `turn/completed`. Completion wakes the bot. No polling turns in between.
3. **Steer and interrupt.** `turn/steer` adds instructions to a running turn; `turn/interrupt` stops it and the thread stays usable. Interrupt isn't a hard stop: commands already scheduled can still land, so check the working tree after.
4. **Reuse sessions.** One named session per project × task type (`<bot>-<project>-<task type>`), found with `thread/list`, picked up with `thread/resume`, compacted when it gets long, archived when done. Never two writers in one working tree.
5. **Long runs.** Pair it with [bot-keepalive](https://github.com/realTaki/bot-keepalive) so the computer stays awake until Codex finishes.

| | Babysitting | Progress routine | bot-codex-delegate |
|---|---|---|---|
| Who spends quota while Codex works | The bot, every check | A new bot each run | Codex |
| Bot context | Grows with every check | Re-read from scratch | Kept, one wake-up per turn |
| Knows when Codex is done | Only when it checks | Only when the routine fires | Right away, the call returns |
| Steer or stop mid-turn | Awkward | No | `turn/steer`, `turn/interrupt` |
| Codex context across tasks | Depends | Depends | One named session per task type |

## Safe defaults

The installer starts the server with sandbox `workspace-write` **with network access** and approval policy `on-request`. Codex writes inside the project folder and asks before stepping outside it. The model comes from your own Codex config.

Full access is **opt-in only**: `CODEX_DELEGATE_FULL_ACCESS=1` switches the server to `danger-full-access` with approvals `never`. Then Codex can read and change any file your user can, including SSH keys, API tokens and other projects on the machine. Only turn it on for a throwaway computer and work you trust.

The driver has the same defaults per thread, and it **declines** approval requests unless you pass `--approve accept` (or `acceptForSession`). `--no-network` and `--sandbox read-only` tighten it; `start --danger-full-access` is the opt-in escape hatch with the same risk as above.

The endpoint, state dir, log path, tmux session name and model are all env vars; see the top of [`install-codex-app-server.sh`](scripts/install-codex-app-server.sh). The server only listens on loopback because it has no auth.

## Install

Send your Grok Bot this link and ask it to save it as a skill:

```
https://github.com/realTaki/bot-codex-delegate/blob/main/skills/bot-codex-delegate/SKILL.md
```

The skill tells the bot to set up the server on its computer (Codex CLI must be installed and logged in):

```bash
git clone https://github.com/realTaki/bot-codex-delegate
bash bot-codex-delegate/scripts/install-codex-app-server.sh   # idempotent
codex-app-server-ctl status
codex-sessions                                                # named Codex sessions
```

What's in here:

- [`skills/bot-codex-delegate/SKILL.md`](skills/bot-codex-delegate/SKILL.md): the workflow and rules for the bot.
- [`scripts/install-codex-app-server.sh`](scripts/install-codex-app-server.sh): app-server in tmux + watchdog + `codex-app-server-ctl status|start|stop|restart|schema`, logs in `~/logs/`.
- [`scripts/codex-sessions`](scripts/codex-sessions): list, find, name, compact and archive sessions (Python stdlib only).
- [`scripts/codex_ws.py`](scripts/codex_ws.py): stdlib-only driver for start / turn / steer / interrupt / list / read ([docs](scripts/codex_ws.README.md)).

```bash
python3 scripts/codex_ws.py start --cwd ./my-repo "first task"      # prints threadId
python3 scripts/codex_ws.py turn <threadId> "next task" --effort medium
python3 scripts/codex_ws.py steer <threadId> <turnId> "also update the changelog"
python3 scripts/codex_ws.py interrupt <threadId> <turnId>
python3 scripts/codex_ws.py list --cwd ./my-repo
```

Driver settings: `--host`/`--port` (`CODEX_WS_HOST`/`CODEX_WS_PORT`, default `127.0.0.1:4500`), `start --model` (`CODEX_WS_MODEL`, default: the server's), `--state FILE` (`CODEX_WS_STATE`, off by default). Global flags go before the subcommand.

---

## 中文说明

**让 Grok Bot 像 Cursor Project 用云端 agent 一样用 Codex：派活出去，干完了叫醒它。** Bot 当协调者，云电脑上常驻的 `codex app-server` 当干活的 agent。额度花在 Codex 干活上，不花在 bot 盯着上。

**问题。** 正如 [@0xmomonifty](https://x.com/0xmomonifty/status/2115269648698716426) 说的：Grok Bot 驱动 Codex 时一直在“陪着”它。一轮一轮查进度，bot 自己的额度全花在陪 Codex 上；可要是 bot 撒手结束对话，没有 bot turn 在跑，云电脑就休眠，Codex 也跟着卡住。设个查进度的 Routine 也不行：每次都是新 bot，从头读上下文，而且触发不准时。

**解法。**
1. **常驻服务。** `codex app-server` 跑在 `ws://127.0.0.1:4500`（WebSocket JSON-RPC，只监听本机），tmux + watchdog 保活，健康检查 `/readyz`、`/healthz`。和 Codex CLI 共用登录和会话记录。
2. **派活，等叫醒。** Bot 用一条后台 Shell 命令（`block_until_ms: 0`）发出一个 turn，等到 `turn/completed` 才返回，完成即叫醒 bot。中间不轮询，不开查进度的 turn。
3. **中途转向、打断。** `turn/steer` 给正在跑的 turn 补指令；`turn/interrupt` 打断，会话还能接着用。注意打断不是硬停止：已经排上的命令可能还会执行，打断后先看一下工作区。
4. **复用会话。** 每个项目 × 任务类型一个命名会话（`<bot>-<项目>-<任务类型>`），用 `thread/list` 找、`thread/resume` 接上、太长就压缩、做完就归档。同一个工作区永远只能有一个写入者。
5. **长任务。** 配合 [bot-keepalive](https://github.com/realTaki/bot-keepalive)，Codex 跑完之前云电脑不休眠。

**安全默认值。** 默认沙箱 `workspace-write` 且允许联网，审批策略 `on-request`：Codex 在项目目录里写文件，越界之前先问。模型用你自己 Codex 配置里的。完全权限只能显式开启：`CODEX_DELEGATE_FULL_ACCESS=1` 会改成 `danger-full-access` + 审批 `never`，这时 Codex 能读写你这个用户能碰到的任何文件，包括别处的 SSH 密钥、API token 和其他项目。只在一次性的机器、可信的任务上用。地址、目录、日志、tmux 会话名、模型都能用环境变量改，服务只监听本机（它没有鉴权）。

**安装。** 把上面那个 `SKILL.md` 链接发给你的 Grok Bot，让它存成技能。技能会让 bot 在自己电脑上运行 `scripts/install-codex-app-server.sh`（可重复运行），需要先装好并登录 Codex CLI。驱动脚本 `scripts/codex_ws.py`（只用标准库）负责 start / turn / steer / interrupt / list / read，地址用 `--host`/`--port` 或 `CODEX_WS_HOST`/`CODEX_WS_PORT`，模型用 `start --model` 或 `CODEX_WS_MODEL`（默认用服务端的）。驱动默认拒绝审批请求，`--approve accept` 才放行；`--danger-full-access` 同样只能显式开启。

## License

MIT
