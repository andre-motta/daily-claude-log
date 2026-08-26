---
name: daily-summary
description: Generate AI summary of your Claude Code and Codex sessions for a given day. Collects session data, builds a token-efficient prompt, and uses a fast model to synthesize a daily report + digest. Use when asked for a daily summary, end-of-day recap, or "what did I do today".
arguments: [date]
argument-hint: [YYYY-MM-DD] (default: today)
allowed-tools: Bash(python3 *) Bash(daily-claude-log *) Bash(git *) Bash(cat *) Bash(ls *) Bash(date *) Read Write Agent
---

# Daily Summary

Generate an AI-powered summary of today's Claude Code and Codex sessions.

**Input:** `$ARGUMENTS`

## Step 1: Parse date

If `$ARGUMENTS` contains a date (YYYY-MM-DD format), use it. Otherwise use today's date.

```bash
date_arg=$(echo "$ARGUMENTS" | grep -oP '\d{4}-\d{2}-\d{2}' || date +%Y-%m-%d)
echo "Generating summary for: $date_arg"
```

## Step 2: Collect sessions

Run the collector to ensure all sessions for the target date are ingested:

```bash
daily-claude-log collect-all --date "$date_arg"
```

Then check what we have:

```bash
daily-claude-log status --date "$date_arg"
```

If no sessions found, tell the user and stop.

## Step 3: Generate summary prompt

```bash
daily-claude-log prompt --date "$date_arg" > /tmp/dcl-prompt-$date_arg.txt
```

Read the prompt file to see what data is available.

## Step 4: Generate summary

Spawn a subagent with model `gpt-5.6-luna` and low reasoning effort to generate
the summary. Pass it the prompt content. This is Codex's efficient model for a
focused synthesis task.

The agent should produce TWO sections separated by `---DIGEST---`:
1. A full markdown daily report
2. A short digest paragraph (under 80 words)

## Step 5: Store results

Write the agent's output to a temp file, then store it:

```bash
daily-claude-log store-summary "$date_arg" /tmp/dcl-summary-$date_arg.md
```

## Step 6: Show results

Read and display the generated summary to the user.

Check if `$DCL_DATA_DIR` is a git repo. If so, offer to commit and push:

```bash
cd "$DCL_DATA_DIR"
git add reports/ recap.db
git commit -m "daily-summary: $date_arg"
git push
```

Only commit/push if the user agrees.
