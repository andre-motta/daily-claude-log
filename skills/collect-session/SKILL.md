---
name: collect-session
description: Manually collect the current Claude Code session into daily-claude-log. Use when you want to ensure a session is logged before it ends, or to verify collection is working.
arguments: []
argument-hint: (no arguments)
allowed-tools: Bash(daily-claude-log *) Bash(python3 *) Bash(echo *) Bash(date *)
---

# Collect Current Session

Manually trigger collection of the current Claude Code session.

## Step 1: Collect

The current session ID is available via `$CLAUDE_CODE_SESSION_ID` environment variable.

```bash
daily-claude-log collect "$CLAUDE_CODE_SESSION_ID"
```

## Step 2: Show status

```bash
daily-claude-log status --date "$(date +%Y-%m-%d)"
```

Report back what was collected.
