---
name: bot-claude-cloud-delegate
description: Delegate coding tasks from Grok Bot to Claude Code cloud sessions using a Claude subscription login and the official CLI.
---

# Delegate to Claude Code cloud sessions

Use Claude Code's own cloud sessions, which run independently of Grok Bot's computer. This workflow uses the official Claude CLI signed in to a Claude account; it requires no API key or scheduled-task trigger token. See [Anthropic's cloud session documentation](https://code.claude.com/docs/en/claude-code-on-the-web).

## Setup

The user needs an eligible Claude subscription with cloud sessions enabled and access to the target repository. Install the Claude Code CLI following Anthropic's official instructions if needed, and check `claude auth status` without printing credentials. If not signed in to the intended Claude account, guide the user through `claude auth login` using the supported secure sign-in flow. Never request passwords or tokens in chat. Do not silently log out or replace an existing login.

Check account and organization policy, provider configuration, and repo access before calling setup complete. Third-party providers and API-only login do not provide the same cloud-session path. If API environment variables or config override the subscription login, report the conflict; do not silently change the user's global config. Cloud tasks consume subscription usage; extra usage may be billed if enabled.

## Start

1. Identify the checkout and branch, task scope, tests, and whether commits, pushes or a PR are authorized. Review the repository content that would be shared with the cloud before dispatch. With a GitHub remote and app access the cloud session normally clones the remote branch, which may not contain local changes. In other cases Claude can upload a repository bundle, potentially including committed history and tracked changes. Confirm the actual behavior from CLI output and the [cloud docs](https://code.claude.com/docs/en/claude-code-on-the-web) rather than assuming which files are sent.
2. From the intended repository run:

   ```bash
   claude --cloud "Describe the task and acceptance checks"
   ```

   This may open an interactive interface and require a TTY or user action. If the host cannot support it, report the limitation or start the session in the Claude Code web UI; do not substitute undocumented endpoints or token scraping. Record a session ID and link only if actually reported or visible. Do not start it again after an ambiguous error until checking whether a session was created.
3. Report the session link and that work is in progress or status is unknown. Launching does not prove task completion. Open the session in Claude Code on the web to observe, answer questions, review changes, or use available controls.

## Follow up and review

A CLI signed in to the same Claude account can queue a message to an existing cloud session:

```bash
printf '%s' 'Please also check the regression tests.' | claude -p --cloud SESSION_ID --output-format json
```

Check the CLI result. Queued means sent, not completed. Continue and review in the web session. The official documented CLI follow-up does not wait for the reply, so do not promise automatic completion notifications without an independently verified integration. `claude --teleport SESSION_ID` pulls the session and branch into a local checkout and changes its working state; local and cloud conversations do not stay synchronized.

For parallel work, use separate cloud sessions and coordinate branches and integration. An interrupted or stopped session may already have caused changes; review the actual state before continuing. Never copy login tokens or account cookies into scripts, prompts, logs, or a repository.
