# Grok Bot Code Agents

Delegate coding tasks from Grok Bot to Codex, Claude Code cloud sessions, and OpenCode. Codex and Claude use your subscription account login by default; no API key or scheduled-task trigger token is needed for either.

## One prompt to set it up

Paste this into a Grok Bot conversation:

```text
Set up the coding delegation skills from https://github.com/codejunkie99/grok-bot-code-agents for my Grok Bot.

Read the README and all three SKILL.md files. Clone the repository to ~/grok-bot-code-agents, or reuse the existing checkout without overwriting my changes. Save the three skills by name in my Grok Bot private skill library. Keep the clone for the Codex scripts. If skill creation is unavailable, tell me what to do rather than claiming it worked.

For Codex, use my ChatGPT subscription login, not an API key. Check the CLI and its login status, Linux prerequisites, and any existing server. Help me sign in securely if needed. Use the safe-default installer only if a suitable server is not already running, and check whether it becomes ready. Do not enable full access or change an existing server without asking.

For Claude Code, use my Claude subscription login and the official CLI cloud-session workflow. Check the CLI and account login; help me sign in securely if needed. Help me connect the right repository and check that cloud sessions are enabled. Do not require an API key or a scheduled-task trigger token. Report any step that needs me or cannot be verified.

For OpenCode, check the CLI and whether OpenCode Go is already configured without exposing credentials. OpenCode Go's documented provider setup requires an OpenCode API key: do not create, request, or paste one on my behalf. If Go isn't configured, explain that limitation and leave it pending. Do not silently switch to another provider or billing method.

Never ask me to paste passwords or tokens into chat. Do not launch a coding task, push changes, create a pull request, or spend usage on a live test until I give you a task. Finish by listing the skills installed, each worker's verified readiness, and any remaining setup steps.
```

One prompt starts setup; provider sign-in, repository access, or private skill creation may require your action. Grok Bot can save skills in its [private skill library](https://docs.x.ai/grok-bot/skills-routines-and-automations#save-a-skill). This setup has not been tested end to end inside Grok Bot.

## Choose a worker

| | Codex | Claude Code cloud | OpenCode / Go |
|---|---|---|---|
| Where work runs | Codex app-server on the Grok Bot computer | Claude Code cloud session | OpenCode CLI on the Grok Bot computer |
| Authentication | ChatGPT account subscription login | Claude account subscription login | Provider-dependent; Go requires its own OpenCode API key |
| Start | Local app-server and driver | `claude --cloud "task"` from a repository | `opencode run --model provider/model "task"` |
| Completion | A waiter can observe the local turn | Review the cloud session; documented CLI follow-up queues a message and exits | A waiter can observe the local process |
| Needs | Codex CLI, an eligible account, Linux, `tmux`, `flock`, `curl`, `ss`, Python 3 | Claude CLI, an eligible account with cloud sessions enabled, repository access | OpenCode CLI and a configured provider and model |

A Claude cloud session runs independently of the Bot computer. Codex and OpenCode run locally on that computer and may need a foreground waiter to keep it active. A task being launched is not evidence of completion. Account limits and optional extra-usage charges can apply.

OpenCode Go is subscription-based, but its [documented connection](https://opencode.ai/docs/providers/#opencode-go) uses an OpenCode API key. This is a provider credential, not necessarily pay-as-you-go billing. If you require OAuth without a key, Go cannot currently be set up that way using the documented flow. An already configured Go connection can be used without putting the key in your prompt; other OpenCode providers may offer OAuth but are not Go.

## Use the skills

- [Codex delegation](skills/bot-codex-delegate/SKILL.md): sign in with ChatGPT, run the local app-server, resume sessions, and steer or interrupt turns.
- [Claude Code cloud delegation](skills/bot-claude-cloud-delegate/SKILL.md): sign in with Claude, start a cloud session with `claude --cloud`, and queue a follow-up to an existing session.
- [OpenCode delegation](skills/bot-opencode-delegate/SKILL.md): use a configured OpenCode provider, run a task, and continue an existing session.

The Codex installer is for a Linux environment and listens on loopback only. It defaults to workspace-write and on-request approvals; full access is opt-in. It clears common API-key environment overrides from the app-server process; a user's configured provider and login still need checking. The CLI driver declines approval requests unless configured otherwise. The Claude CLI can upload a local repository bundle in some cases, so check which data will be sent before starting a session. Never put credentials into prompts or the repository.

## Credits and license

The Codex workflow and scripts originate from [realTaki/bot-codex-delegate](https://github.com/realTaki/bot-codex-delegate), by Taki W. Its original MIT copyright and license are retained in [LICENSE](LICENSE); the Codex setup instructions and installer here are adjusted for this repository. The Claude and OpenCode skills were developed separately for this combined repository. The original Codex project README is retained at [docs/UPSTREAM-CODEX.md](docs/UPSTREAM-CODEX.md).
