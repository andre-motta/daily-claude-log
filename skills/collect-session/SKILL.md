---
name: collect-session
description: Manually collect the current Claude Code or Codex session into daily-claude-log. Use when you want to ensure a session is logged before it ends, or to verify collection is working.
arguments: []
argument-hint: (no arguments)
allowed-tools: Bash(daily-claude-log *) Bash(python3 *) Bash(echo *) Bash(date *)
---

# Collect Current Session

Manually trigger collection of the current Claude Code session.

## Step 1: Collect

Use the session ID exposed by the current agent host.

```bash
session_id="${CODEX_SESSION_ID:-${CODEX_THREAD_ID:-$CLAUDE_CODE_SESSION_ID}}"
daily-claude-log collect "$session_id"
```

## Step 2: Show status

```bash
daily-claude-log status --date "$(date +%Y-%m-%d)"
```

Report back what was collected.
