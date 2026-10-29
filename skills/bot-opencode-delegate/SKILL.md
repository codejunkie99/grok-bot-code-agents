---
name: bot-opencode-delegate
description: Delegate coding tasks from Grok Bot to an OpenCode CLI session using an already configured provider, including OpenCode Go when configured.
---

# Delegate to OpenCode

OpenCode runs on Grok Bot's computer. Its model provider may support a subscription OAuth login or require a provider-specific key. OpenCode Go is a separate subscription whose [documented setup](https://opencode.ai/docs/providers/#opencode-go) requires an OpenCode API key; it is not a browser-OAuth inference login. Do not claim that OpenCode Go was connected through OAuth. Respect the user's credential preferences and never ask them to paste credentials in chat.

## Setup

Install the official OpenCode CLI if needed using [OpenCode's instructions](https://opencode.ai/docs/). Check `opencode --version`, the connected provider list with `opencode auth list`, and available model IDs with `opencode models opencode-go` if Go is intended. A listed credential or model does not verify that the subscription works. Never read or print the credentials file.

For a user who requires OAuth-only setup, stop at this point if Go is not already configured and report that its documented setup needs an OpenCode API key. Do not create a key or silently switch providers or billing. An already configured Go connection may be reused only if the user permits its use; do not claim it is OAuth. Other supported providers may offer OAuth, but are different providers and must be selected explicitly.

## Run and follow up

Agree on a repository, model ID, task, permissions, tests, and any authorized commit, push, or PR. The model ID should come from the installed CLI's provider list. In the repository:

```bash
opencode run --model 'opencode-go/MODEL_ID' --format json 'Describe the task and acceptance checks'
```

Check the result and capture the session ID from the actual event output. To continue an existing session, use:

```bash
opencode run --session SESSION_ID --model 'opencode-go/MODEL_ID' --format json 'Follow-up instructions'
```

Use the CLI's `run --help` because flags and output can vary by version. Do not use `--auto` or relax permissions without user authorization. Review the actual changes and test results before reporting success. A zero exit or an event alone does not establish that the task was completed.

Since the worker runs on the bot's cloud computer, the computer may sleep when the bot is idle. If the host supports a low-effort subagent and foreground waiting, have one waiter own the single `opencode run` process and wait continuously for its exit, then report the actual status and session ID. Never launch a second process just because a wait timed out. If the host cannot keep it awake or observe completion, say so. For parallel work, use separate working trees and sessions. Handle output and logs as potentially sensitive; do not publish or share sessions without authorization.
