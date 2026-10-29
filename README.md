# Grok Bot Code Agents

Give Grok Bot two ways to delegate coding work: a **Codex worker** on its cloud computer and **Claude Code cloud sessions** on Anthropic's infrastructure.

## One prompt to set it up

Paste this into a Grok Bot conversation:

```text
Set up both coding delegation skills from https://github.com/codejunkie99/grok-bot-code-agents for my Grok Bot.

Read the README and both SKILL.md files. Clone the repository to ~/grok-bot-code-agents (reuse an existing checkout without overwriting my changes), and save both skills by name in my Grok Bot private skill library. Keep the clone so the skills can use its scripts. If skill creation is unavailable, tell me exactly what to do instead of claiming it worked.

For Codex, check whether the CLI is installed and logged in, whether tmux, flock, curl and the other Linux prerequisites are available, and whether a server is already running. Follow the repository's safe-default setup. If something is missing, help me install it or sign in using the supported secure flow. Do not enable full access or change my existing server without asking. Check and report whether the server is ready.

For Claude, guide me through creating an API-triggered Claude Code scheduled task, connecting the right repository, and securely providing its fire URL and token for use by the helper. Never ask me to paste a token into chat or print it. Check the Claude CLI login if follow-ups are wanted. Report anything that still needs my action.

Do not launch a coding task, push changes, create a pull request, or spend usage on a live test until I give you a task. Finish by listing what is installed, what is ready, and any remaining setup steps.
```

One prompt starts the setup; provider login, repository access, and creating a Claude API trigger may require you to complete steps in the relevant account. Grok Bot can save skills across its bots using its [private skill library](https://docs.x.ai/grok-bot/skills-routines-and-automations#save-a-skill). Installation and live cloud execution have not yet been verified in Grok Bot.

## Choose a worker

| | Codex | Claude Code cloud |
|---|---|---|
| Where work runs | Codex app-server on the Grok Bot computer | Claude Code cloud session |
| Dispatch | Local app-server and Python driver | Scheduled-task API trigger |
| Follow-up | Steer or interrupt; resume named sessions | Queue a message with the logged-in Claude CLI |
| Completion | A waiter observes the Codex turn and reports back | Open the session link; the documented trigger API does not report completion |
| Needs | Codex CLI login; Linux environment with `tmux`, `flock`, `curl`, `ss` and Python 3 | Eligible Claude account, configured cloud scheduled task and per-trigger token; Claude CLI login for follow-ups |

The Codex waiter keeps the Bot computer active while the locally running worker operates. A Claude cloud session runs independently of that computer. A Claude trigger response means the session was created, not that the work succeeded. The trigger is experimental, and each successful request creates a new session; do not automatically retry an ambiguous request. See [Claude's API documentation](https://platform.claude.com/docs/en/api/claude-code/routines-fire) and [cloud session docs](https://code.claude.com/docs/en/claude-code-on-the-web).

## Manual setup and usage

Read [the Codex skill](skills/bot-codex-delegate/SKILL.md) and [the Claude cloud skill](skills/bot-claude-cloud-delegate/SKILL.md). The Codex installer is intended for the Linux environment described above and listens on loopback only. It defaults to workspace-write and on-request approvals; full access is opt-in. The Codex driver declines approval requests unless configured otherwise. The Claude scheduled task's repository, permissions, connectors, and environment govern what a session can do. Never put credentials into prompts or the repository.

For Claude, set `CLAUDE_ROUTINE_FIRE_URL` and `CLAUDE_ROUTINE_TOKEN` in the helper's execution environment using your platform's secure credential flow. The variables must be available in the same process that runs the helper. A typical dispatch looks like this:

```bash
python3 ~/grok-bot-code-agents/skills/bot-claude-cloud-delegate/scripts/fire.py <<'TASK'
Inspect the repository and implement the requested change. Run relevant tests.
TASK
```

The helper prints a session ID and URL when creation succeeds. Open the URL to follow progress and review results. For a follow-up, use the Claude CLI signed in to the same Claude account:

```bash
printf '%s' 'Please also check the regression tests.' | claude -p --cloud SESSION_ID --output-format json
```

This queues the message and does not wait for an answer. Consult the two skills for detailed instructions, failure handling, and limits. The original Codex project documentation is retained at [docs/UPSTREAM-CODEX.md](docs/UPSTREAM-CODEX.md).

## Credits and license

The Codex workflow and scripts originate from [realTaki/bot-codex-delegate](https://github.com/realTaki/bot-codex-delegate), by Taki W. Its original MIT copyright and license are retained in [LICENSE](LICENSE); the Codex setup instructions here are adjusted for this repository. The Claude cloud skill and helper were developed separately for this combined repository.
