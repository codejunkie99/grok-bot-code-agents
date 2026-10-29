---
name: bot-claude-cloud-delegate
description: Delegate coding tasks from Grok Bot to Claude Code cloud sessions, retain session links, and queue follow-ups using documented Anthropic interfaces.
---

# Delegate to Claude Code cloud sessions

Use this for Claude Code sessions running on Anthropic-managed infrastructure, not a local Claude CLI process or Remote Control. The cloud session continues independently if the bot's computer sleeps. The API creates a new session; it does not report completion. Do not promise a wake-up, successful task, or automated status monitoring without a separately verified integration.

## Setup

The user needs a Claude account with Claude Code cloud sessions enabled, a configured GitHub repository, and a cloud scheduled task (formerly routine) with an API trigger. Its saved prompt, repositories, connector access, environment, and permission mode govern the run. Confirm they match the requested task. Task runs consume Claude Code subscription usage; extra usage may be billed if enabled. See [Anthropic's scheduled task docs](https://code.claude.com/docs/en/routines) and [API reference](https://platform.claude.com/docs/en/api/claude-code/routines-fire).

The user generates a per-task API token in Claude Code and provides it privately as `CLAUDE_ROUTINE_TOKEN`, with the exact fire URL as `CLAUDE_ROUTINE_FIRE_URL`, using the host's secure credential flow. Both must be present in the helper process's environment. If the host cannot make a secure credential available there, report the remaining setup rather than claiming readiness. Do not ask the user to paste tokens into chat, print them, include them in prompts, or write them into the repo. The token can trigger that scheduled task and is distinct from an Anthropic API key. Rotate it if exposed.

## Start

1. Prepare a task describing the goal, repository, scope, acceptance checks, and whether committing, pushing, PR creation, or other external actions are authorized. A scheduled task's saved prompt still applies. Each fire creates a **new** session.
2. Run the bundled helper once, sending the task on stdin. Do not put secrets into the task:

   ```bash
   python3 ~/grok-bot-code-agents/skills/bot-claude-cloud-delegate/scripts/fire.py <<'TASK'
   Inspect the repository and implement the requested change. Run relevant tests.
   Do not push or open a pull request unless the task explicitly authorizes it.
   TASK
   ```

3. Save the returned session ID and URL with the task record. `status: created` confirms creation only. Report the link and say completion is unknown. Follow the link to review output and changes. If the request times out or returns an unrecognized response, check for an existing run before retrying: the API has no idempotency key. Never automatically retry a fire.

Alternatively, a logged-in Claude CLI can create a cloud session from a checkout with `claude --cloud "task"`; this is interactive and branch/upload behavior depends on repository setup. Check CLI output and the [cloud documentation](https://code.claude.com/docs/en/claude-code-on-the-web) before assuming which files were sent. Do not claim that a local checkout's unpushed changes are always present.

## Continue and review

For an existing session, Claude Code CLI authenticated to the same Claude account can queue a follow-up, without waiting for its answer:

```bash
printf '%s' 'Please also check the regression tests.' | claude -p --cloud SESSION_ID --output-format json
```

Check the CLI's result; queued means delivered, not completed. Follow-ups can steer ongoing work or continue an eligible session; a routine fire always creates a fresh one. Use the web session for progress, questions, cancellation controls, review, and PR creation as available. `claude --teleport SESSION_ID` copies a cloud session into a local checkout and changes its working state; it does not keep the local and cloud conversations synchronized.

The documented routine token has no read access. Do not infer completion from the fire response, a process exit, or elapsed time. Do not use undocumented private endpoints, account cookies, or a waiter that pretends to observe the session. An interrupted or stopped session may already have caused changes; review the actual state before continuing.

For parallel work, use separate cloud sessions and coordinate branches and integration to avoid conflicting changes. Avoid launching duplicate work after ambiguous errors. Cloud environments and scheduled task permissions may allow actions independently of the bot; configure and review them before dispatch.
