# daily-claude-log

Automatically extract and summarize your [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions into daily reports. Zero dependencies beyond Python 3.9+ stdlib.

## What it does

1. **Collects** structured data from Claude Code session transcripts (JSONL files) -- files touched, tools used, commits, MRs/PRs, Jira tickets, user questions, assistant responses
2. **Stores** everything in a local SQLite database, split by local date (sessions spanning midnight are correctly attributed to each day)
3. **Generates** daily summaries using Claude (Haiku) via a Claude Code skill
4. **Outputs** reports as `reports/<date>/full.md` and `reports/<date>/digest.md`

The collection is pure Python (no LLM calls). Only the summary generation uses an LLM, and the prompt is pre-compressed to ~2-8KB so Haiku handles it cheaply (~15-20k tokens per day).

## Install

### From PyPI

```bash
pip install daily-claude-log
```

### From source (development)

```bash
git clone https://github.com/andre-motta/daily-claude-log.git
cd daily-claude-log
pip install -e .
```

### Claude Code hooks and skills

After installing the package, run the installer to set up the SessionEnd hook and Claude Code skills:

```bash
git clone https://github.com/andre-motta/daily-claude-log.git
cd daily-claude-log
bash install.sh
```

The installer will:
- Install the package via pip (editable mode)
- Add a `SessionEnd` hook to Claude Code (auto-collects when sessions end)
- Install `/daily-summary` and `/collect-session` skills

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DCL_DATA_DIR` | Where the SQLite DB and reports are stored. Can be a private git repo. | `~/.daily-claude-log` |
| `DCL_CLAUDE_DIR` | Where Claude Code stores its data (transcripts, etc). | `~/.claude` |

Add these to your shell profile (`~/.bashrc`, `~/.zshrc`, or equivalent):

```bash
export DCL_DATA_DIR=~/path/to/your/private/log/repo
```

## Usage

### CLI

```bash
# Show today's sessions
daily-claude-log status

# Backfill last 30 days of sessions
daily-claude-log backfill --days 30

# List all dates with data
daily-claude-log list-dates

# Generate summary prompt (for manual LLM use)
daily-claude-log prompt --date 2026-08-04

# Store a generated summary
daily-claude-log store-summary 2026-08-04 /tmp/summary.md

# Export session data as JSON
daily-claude-log export --date 2026-08-04

# Print version
daily-claude-log version
```

### Claude Code skills

Inside Claude Code:

- **`/daily-summary`** -- Collect today's sessions, generate an AI summary (uses Haiku), and store the report. Optionally commits to your data repo.
- **`/daily-summary 2026-08-01`** -- Generate summary for a specific date.
- **`/collect-session`** -- Manually trigger collection of the current session.

### Automatic collection

After installation, a `SessionEnd` hook runs automatically when you exit Claude Code, collecting the session into the database. No action needed.

## Data model

Sessions are stored in SQLite with a composite primary key `(session_id, date)`. A single Claude Code session that spans multiple days (via `claude -r` / resume) is split into separate rows per date, each containing only the activity from that day.

Each row tracks:
- Session ID, project, title, timestamps
- Active duration (computed from message gaps, handles `--resume` correctly)
- Files touched, tools used (with counts)
- Commits, MR/PR links, Jira tickets
- User message snippets, assistant response snippets

Reports are stored as:
```
$DCL_DATA_DIR/
  recap.db                    # SQLite database
  reports/
    2026-08-04/
      full.md                 # Full daily report
      digest.md               # One-paragraph digest
    2026-08-03/
      ...
```

## Committing to git

If `$DCL_DATA_DIR` is a git repo, the `/daily-summary` skill will offer to commit and push after generating a report. The SQLite DB is small (typically <1MB) and works fine in git.

## Uninstalling

```bash
# Remove hooks and skills
cd daily-claude-log
bash uninstall.sh

# Remove the package
pip uninstall daily-claude-log
```

Your data in `$DCL_DATA_DIR` is preserved.

## License

Apache-2.0
