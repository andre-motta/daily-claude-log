#!/usr/bin/env python3
"""daily-claude-log: Extract and summarize Claude Code sessions.

Single-file, stdlib-only. No pip dependencies.

Commands:
    collect <session_id>          Process one session from its JSONL transcript
    collect-all [--date DATE]     Process all sessions for a date (default: today)
    backfill [--days N]           Process all sessions from last N days (default: 30)
    prompt [--date DATE]          Generate summary prompt for LLM consumption
    store-summary <date> <file>   Store a generated summary from file
    status [--date DATE]          Show stats for a date
    export [--date DATE]          Export raw session data as JSON
    list-dates                    List all dates with sessions

Environment variables:
    DCL_DATA_DIR     Where DB + summaries go (default: ~/.daily-claude-log)
    DCL_CLAUDE_DIR   Where Claude Code stores transcripts (default: ~/.claude)
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLAUDE_DIR = Path(os.path.expanduser(os.environ.get("DCL_CLAUDE_DIR", "~/.claude")))
DATA_DIR = Path(os.path.expanduser(os.environ.get("DCL_DATA_DIR", "~/.daily-claude-log")))
DB_PATH = DATA_DIR / "recap.db"
REPORTS_DIR = DATA_DIR / "reports"

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT NOT NULL,
    date TEXT NOT NULL,
    project TEXT NOT NULL,
    project_short TEXT NOT NULL,
    title TEXT,
    started_at TEXT,
    ended_at TEXT,
    duration_minutes REAL,
    user_messages INTEGER DEFAULT 0,
    assistant_messages INTEGER DEFAULT 0,
    files_touched TEXT DEFAULT '[]',
    tools_used TEXT DEFAULT '{}',
    commits TEXT DEFAULT '[]',
    mr_prs TEXT DEFAULT '[]',
    jira_tickets TEXT DEFAULT '[]',
    key_topics TEXT DEFAULT '[]',
    user_snippets TEXT DEFAULT '[]',
    assistant_snippets TEXT DEFAULT '[]',
    jsonl_path TEXT,
    processed_at TEXT,
    PRIMARY KEY (session_id, date)
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    date TEXT PRIMARY KEY,
    summary_md TEXT,
    digest TEXT,
    generated_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_short);
"""


def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    _migrate(db)
    db.executescript(SCHEMA)
    return db


def _migrate(db):
    """Migrate from old schema if needed."""
    try:
        info = db.execute("PRAGMA table_info(sessions)").fetchall()
    except Exception:
        return
    if not info:
        return
    pk_cols = [col for col in info if col[5] > 0]
    if len(pk_cols) == 1 and pk_cols[0][1] == "session_id":
        print(
            "Migrating DB: session_id -> (session_id, date) composite key...",
            file=sys.stderr,
        )
        print(
            "Run 'backfill' to re-collect sessions with correct per-day splitting.",
            file=sys.stderr,
        )
        db.execute("DROP TABLE IF EXISTS sessions")
        db.commit()


def project_short_name(project_dir):
    """Convert '-home-user-git-org-repo' to 'org/repo' style."""
    parts = project_dir.split("-")
    try:
        git_idx = parts.index("git")
        remainder = parts[git_idx + 1 :]
        if not remainder:
            return "~"
        return "/".join(remainder)
    except ValueError:
        return project_dir


def _extract_commit_message(cmd):
    """Extract commit message from a git commit command string."""
    simple = re.search(r'git commit\s.*?-m\s+"([^"]+)"', cmd)
    if simple:
        return simple.group(1)
    simple_sq = re.search(r"git commit\s.*?-m\s+'([^']+)'", cmd)
    if simple_sq:
        return simple_sq.group(1)

    if "EOF" in cmd:
        lines = cmd.split("\n")
        in_heredoc = False
        for line in lines:
            stripped = line.strip()
            if in_heredoc:
                if stripped in ("EOF", "EOF)", "'EOF'"):
                    break
                if stripped and not stripped.startswith(
                    "Co-Authored"
                ) and not stripped.startswith("Signed-off"):
                    return stripped
            if "<<" in line and "EOF" in line:
                in_heredoc = True

    return None


def _local_date(ts_str):
    """Convert ISO timestamp string to local date (YYYY-MM-DD).

    Treats all timestamps as UTC, converts to system local timezone.
    """
    if not ts_str:
        return None
    ts_clean = ts_str.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            utc_dt = datetime.strptime(ts_clean[:26], fmt).replace(
                tzinfo=timezone.utc
            )
            return utc_dt.astimezone().strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def extract_session(jsonl_path):
    """Parse JSONL transcript and extract per-date session data.

    Returns (session_id, title, dates_dict) where dates_dict maps
    local date strings to stat dicts. Sessions spanning midnight are
    split into separate date entries.
    """
    session_id = None
    title = None
    dates = {}

    def _acc(date_str):
        if date_str not in dates:
            dates[date_str] = {
                "started_at": None,
                "ended_at": None,
                "timestamps": [],
                "user_messages": 0,
                "assistant_messages": 0,
                "files_touched": set(),
                "tools_used": {},
                "commits": [],
                "mr_prs": [],
                "jira_tickets": set(),
                "user_snippets": [],
                "assistant_snippets": [],
            }
        return dates[date_str]

    jira_re = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
    commit_re = re.compile(r"git commit\b")

    with open(jsonl_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            timestamp = entry.get("timestamp")

            ts_str = None
            date_str = None
            if timestamp:
                ts_str = (
                    timestamp
                    if isinstance(timestamp, str)
                    else datetime.fromtimestamp(
                        timestamp / 1000, tz=timezone.utc
                    ).isoformat()
                )
                date_str = _local_date(ts_str)

            if entry_type == "ai-title":
                title = entry.get("aiTitle")
                session_id = entry.get("sessionId")
            elif entry_type in ("mode", "permission-mode", "last-prompt"):
                if not session_id:
                    session_id = entry.get("sessionId")

            if date_str is None:
                continue

            acc = _acc(date_str)
            acc["timestamps"].append(ts_str)
            if acc["started_at"] is None:
                acc["started_at"] = ts_str
            acc["ended_at"] = ts_str

            if entry_type == "user":
                acc["user_messages"] += 1
                msg = entry.get("message", {})
                content = msg.get("content", "") if isinstance(msg, dict) else ""
                if isinstance(content, str) and content.strip():
                    snippet = content.strip().split("\n")[0][:200]
                    if len(acc["user_snippets"]) < 10:
                        acc["user_snippets"].append(snippet)
                    tickets = jira_re.findall(content)
                    acc["jira_tickets"].update(tickets)

            elif entry_type == "assistant":
                acc["assistant_messages"] += 1
                msg = entry.get("message", {})
                content = msg.get("content", []) if isinstance(msg, dict) else []
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue

                        if block.get("type") == "text":
                            txt = block.get("text", "").strip()
                            if txt and len(acc["assistant_snippets"]) < 5:
                                snippet = txt.split("\n")[0][:200]
                                if len(snippet) > 20:
                                    acc["assistant_snippets"].append(snippet)

                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            acc["tools_used"][tool_name] = (
                                acc["tools_used"].get(tool_name, 0) + 1
                            )
                            inp = block.get("input", {})

                            if tool_name in ("Edit", "Write"):
                                fp = inp.get("file_path", "")
                                if fp:
                                    acc["files_touched"].add(fp)

                            elif tool_name == "Read":
                                fp = inp.get("file_path", "")
                                if fp:
                                    acc["files_touched"].add(fp)

                            elif tool_name == "Bash":
                                cmd = inp.get("command", "")
                                if commit_re.search(cmd):
                                    commit_msg = _extract_commit_message(cmd)
                                    if commit_msg:
                                        acc["commits"].append(commit_msg[:120])
                                tickets = jira_re.findall(cmd)
                                acc["jira_tickets"].update(tickets)

                            elif tool_name == "NotebookEdit":
                                fp = inp.get("file_path", "")
                                if fp:
                                    acc["files_touched"].add(fp)

            elif entry_type == "pr-link":
                pr_url = entry.get("prUrl", "")
                pr_num = entry.get("prNumber", "")
                pr_repo = entry.get("prRepository", "")
                if pr_url:
                    acc["mr_prs"].append(
                        {
                            "url": pr_url,
                            "number": pr_num,
                            "repo": pr_repo,
                        }
                    )

    for acc in dates.values():
        acc["files_touched"] = sorted(acc["files_touched"])
        acc["jira_tickets"] = sorted(acc["jira_tickets"])

    return session_id, title, dates


def parse_timestamp(ts):
    """Parse ISO timestamp string to datetime."""
    if not ts:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ):
        try:
            return datetime.strptime(ts[:26], fmt)
        except ValueError:
            continue
    return None


def compute_active_duration(timestamps):
    """Compute active working time from a list of timestamps.

    Sums gaps between consecutive messages that are under 30 minutes.
    Gaps over 30 minutes are treated as breaks (--resume, lunch, etc).
    """
    if len(timestamps) < 2:
        return 0.0

    parsed = []
    for ts in timestamps:
        dt = parse_timestamp(ts)
        if dt:
            parsed.append(dt)

    if len(parsed) < 2:
        return 0.0

    parsed.sort()
    active_seconds = 0.0
    gap_threshold = 30 * 60

    for i in range(1, len(parsed)):
        gap = (parsed[i] - parsed[i - 1]).total_seconds()
        if gap < gap_threshold:
            active_seconds += gap

    return active_seconds / 60


def find_session_jsonl(session_id):
    """Find JSONL file for a session ID."""
    for jsonl in CLAUDE_DIR.glob("projects/*/*.jsonl"):
        if jsonl.stem == session_id:
            return str(jsonl)
    return None


def find_all_sessions(days=None, target_date=None):
    """Find all session JSONL files, optionally filtered by recency.

    Uses file mtime as a rough filter for discovery. Actual date
    assignment happens during collection based on message timestamps.
    """
    sessions = []
    for jsonl in sorted(CLAUDE_DIR.glob("projects/*/*.jsonl")):
        if "/subagents/" in str(jsonl):
            continue
        stat = jsonl.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime)

        if days is not None:
            cutoff = datetime.now() - timedelta(days=days + 1)
            if mtime < cutoff:
                continue

        if target_date:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            if mtime < target_dt - timedelta(days=1):
                continue
            if mtime > target_dt + timedelta(days=2):
                continue

        project_dir = jsonl.parent.name
        sessions.append(
            {
                "session_id": jsonl.stem,
                "jsonl_path": str(jsonl),
                "project_dir": project_dir,
                "mtime": mtime,
            }
        )
    return sessions


def collect_session(session_id, jsonl_path=None, db=None):
    """Extract and store one session, split across dates it spans."""
    if jsonl_path is None:
        jsonl_path = find_session_jsonl(session_id)
    if not jsonl_path or not os.path.exists(jsonl_path):
        return None

    close_db = False
    if db is None:
        db = get_db()
        close_db = True

    existing = db.execute(
        "SELECT processed_at FROM sessions WHERE session_id = ? LIMIT 1",
        (session_id,),
    ).fetchone()

    was_update = False
    if existing:
        file_mtime = datetime.fromtimestamp(os.path.getmtime(jsonl_path))
        processed_at = parse_timestamp(existing[0])
        if processed_at and file_mtime <= processed_at:
            if close_db:
                db.close()
            return "exists"
        db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        was_update = True

    project_dir = Path(jsonl_path).parent.name
    sid, title, dates = extract_session(jsonl_path)

    if not sid:
        sid = session_id

    if not dates:
        if close_db:
            db.close()
        return None

    now = datetime.now().isoformat()
    for date_str, data in sorted(dates.items()):
        duration = compute_active_duration(data["timestamps"])
        db.execute(
            """INSERT OR REPLACE INTO sessions
            (session_id, date, project, project_short, title,
             started_at, ended_at, duration_minutes,
             user_messages, assistant_messages,
             files_touched, tools_used, commits, mr_prs, jira_tickets,
             key_topics, user_snippets, assistant_snippets,
             jsonl_path, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                date_str,
                project_dir,
                project_short_name(project_dir),
                title,
                data["started_at"],
                data["ended_at"],
                round(duration, 1),
                data["user_messages"],
                data["assistant_messages"],
                json.dumps(data["files_touched"]),
                json.dumps(data["tools_used"]),
                json.dumps(data["commits"]),
                json.dumps(data["mr_prs"]),
                json.dumps(data["jira_tickets"]),
                json.dumps([]),
                json.dumps(data["user_snippets"]),
                json.dumps(data["assistant_snippets"]),
                jsonl_path,
                now,
            ),
        )

    db.commit()
    if close_db:
        db.close()
    return "updated" if was_update else "collected"


def cmd_collect(args):
    """Collect a single session."""
    if len(args) < 1:
        print("Usage: daily-claude-log collect <session_id> [jsonl_path]")
        sys.exit(1)
    session_id = args[0]
    jsonl_path = args[1] if len(args) > 1 else None
    result = collect_session(session_id, jsonl_path)
    if result == "exists":
        print(f"Session {session_id} already collected (unchanged)")
    elif result == "collected":
        print(f"Collected session {session_id}")
    elif result == "updated":
        print(f"Updated session {session_id} (file changed since last collection)")
    else:
        print(f"Could not find session {session_id}")


def cmd_collect_all(args):
    """Collect all sessions for a date."""
    target_date = None
    if "--date" in args:
        idx = args.index("--date")
        target_date = args[idx + 1]
    else:
        target_date = datetime.now().strftime("%Y-%m-%d")

    sessions = find_all_sessions(target_date=target_date)
    db = get_db()
    collected = 0
    updated = 0
    skipped = 0
    for s in sessions:
        result = collect_session(s["session_id"], s["jsonl_path"], db)
        if result == "collected":
            collected += 1
        elif result == "updated":
            updated += 1
        else:
            skipped += 1

    db.close()
    parts = [f"collected {collected}"]
    if updated:
        parts.append(f"updated {updated}")
    parts.append(f"skipped {skipped} (already processed)")
    print(f"Date {target_date}: {', '.join(parts)}")


def cmd_backfill(args):
    """Backfill sessions from last N days."""
    days = 30
    if "--days" in args:
        idx = args.index("--days")
        days = int(args[idx + 1])

    sessions = find_all_sessions(days=days)
    db = get_db()
    collected = 0
    updated = 0
    skipped = 0
    errors = 0
    for s in sessions:
        try:
            result = collect_session(s["session_id"], s["jsonl_path"], db)
            if result == "collected":
                collected += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            print(
                f"  Error processing {s['session_id']}: {e}",
                file=sys.stderr,
            )

    db.close()
    total = collected + updated + skipped + errors
    print(f"Backfill ({days} days): {total} sessions found")
    print(f"  Collected: {collected}")
    if updated:
        print(f"  Updated: {updated}")
    print(f"  Already processed: {skipped}")
    if errors:
        print(f"  Errors: {errors}")


def cmd_prompt(args):
    """Generate a summary prompt for LLM consumption."""
    target_date = None
    if "--date" in args:
        idx = args.index("--date")
        target_date = args[idx + 1]
    else:
        target_date = datetime.now().strftime("%Y-%m-%d")

    db = get_db()
    rows = db.execute(
        """SELECT session_id, project_short, title, started_at, ended_at,
                  duration_minutes, user_messages, assistant_messages,
                  files_touched, tools_used, commits, mr_prs, jira_tickets,
                  user_snippets, assistant_snippets
           FROM sessions WHERE date = ? ORDER BY started_at""",
        (target_date,),
    ).fetchall()
    db.close()

    if not rows:
        print(
            f"No sessions found for {target_date}. "
            f"Run 'collect-all --date {target_date}' first."
        )
        sys.exit(1)

    prompt = build_summary_prompt(target_date, rows)
    print(prompt)


def build_summary_prompt(date, rows):
    """Build a token-efficient prompt for LLM summarization."""
    lines = [
        f"Summarize this developer's work on {date}.",
        f"Total sessions: {len(rows)}",
        "",
        "Generate TWO outputs:",
        "1. FULL REPORT in markdown with: Summary (3-5 sentences), "
        "Sessions grouped by project, Key Accomplishments, "
        "Open Threads (anything that seems unfinished), Stats",
        "2. DIGEST: single paragraph, under 80 words, what mattered most",
        "",
        "Separate with '---DIGEST---' marker.",
        "",
        "Sessions:",
        "",
    ]

    projects = {}
    total_duration = 0
    total_files = set()
    total_commits = []
    total_mrs = []
    all_tickets = set()

    for row in rows:
        (
            _,
            project,
            title,
            _,
            _,
            duration,
            _,
            _,
            files_j,
            tools_j,
            commits_j,
            mrs_j,
            tickets_j,
            user_snip_j,
            asst_snip_j,
        ) = row

        files = json.loads(files_j)
        tools = json.loads(tools_j)
        commits = json.loads(commits_j)
        mrs = json.loads(mrs_j)
        tickets = json.loads(tickets_j)
        user_snips = json.loads(user_snip_j)
        asst_snips = json.loads(asst_snip_j)

        total_duration += duration or 0
        total_files.update(files)
        total_commits.extend(commits)
        total_mrs.extend(mrs)
        all_tickets.update(tickets)

        if project not in projects:
            projects[project] = []

        session_lines = [f"### {title or 'Untitled'} ({int(duration or 0)}m)"]

        if user_snips:
            session_lines.append(f"  User asked: {user_snips[0][:100]}")

        top_tools = sorted(tools.items(), key=lambda x: -x[1])[:5]
        if top_tools:
            tool_str = ", ".join(f"{t}:{c}" for t, c in top_tools)
            session_lines.append(f"  Tools: {tool_str}")

        edit_files = [f for f in files if not f.startswith("/")]
        if edit_files:
            short_files = [os.path.basename(f) for f in edit_files[:8]]
            session_lines.append(f"  Files: {', '.join(short_files)}")

        if commits:
            session_lines.append(
                f"  Commits: {'; '.join(c[:60] for c in commits[:3])}"
            )

        if mrs:
            mr_strs = [m.get("url", "") for m in mrs[:3]]
            session_lines.append(f"  MRs/PRs: {', '.join(mr_strs)}")

        if tickets:
            session_lines.append(f"  Jira: {', '.join(tickets)}")

        if asst_snips:
            session_lines.append(f"  Key output: {asst_snips[0][:100]}")

        projects[project].append("\n".join(session_lines))

    lines.append(
        f"Active time: ~{int(total_duration)}m across {len(projects)} projects"
    )
    lines.append(f"Files touched: {len(total_files)}")
    lines.append(f"Commits: {len(total_commits)}")
    if total_mrs:
        lines.append(f"MRs/PRs: {len(total_mrs)}")
    if all_tickets:
        lines.append(f"Jira tickets: {', '.join(sorted(all_tickets))}")
    lines.append("")

    for project, session_blocks in sorted(projects.items()):
        lines.append(f"## {project}")
        for block in session_blocks:
            lines.append(block)
        lines.append("")

    return "\n".join(lines)


def cmd_store_summary(args):
    """Store a generated summary."""
    if len(args) < 2:
        print("Usage: daily-claude-log store-summary <date> <summary_file>")
        sys.exit(1)

    date = args[0]
    summary_file = args[1]

    with open(summary_file) as f:
        content = f.read()

    summary_md = content
    digest = ""
    if "---DIGEST---" in content:
        parts = content.split("---DIGEST---", 1)
        summary_md = parts[0].strip()
        digest = parts[1].strip()

    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO daily_summaries
           (date, summary_md, digest, generated_at)
           VALUES (?, ?, ?, ?)""",
        (date, summary_md, digest, datetime.now().isoformat()),
    )
    db.commit()
    db.close()

    report_dir = REPORTS_DIR / date
    report_dir.mkdir(parents=True, exist_ok=True)

    full_path = report_dir / "full.md"
    with open(full_path, "w") as f:
        f.write(summary_md)

    digest_path = report_dir / "digest.md"
    if digest:
        with open(digest_path, "w") as f:
            f.write(digest)

    print(f"Full report: {full_path}")
    if digest:
        print(f"Digest: {digest_path}")


def cmd_status(args):
    """Show stats for a date."""
    target_date = None
    if "--date" in args:
        idx = args.index("--date")
        target_date = args[idx + 1]
    else:
        target_date = datetime.now().strftime("%Y-%m-%d")

    db = get_db()
    rows = db.execute(
        """SELECT project_short, title, duration_minutes, user_messages,
                  files_touched, commits, mr_prs, jira_tickets
           FROM sessions WHERE date = ? ORDER BY started_at""",
        (target_date,),
    ).fetchall()

    summary = db.execute(
        "SELECT digest FROM daily_summaries WHERE date = ?", (target_date,)
    ).fetchone()
    db.close()

    if not rows:
        print(f"No sessions for {target_date}")
        return

    total_duration = 0
    total_files = set()
    total_commits = 0
    projects = set()

    print(f"=== {target_date} ===")
    print()

    for project, title, duration, msgs, files_j, commits_j, _, _ in rows:
        projects.add(project)
        total_duration += duration or 0
        files = json.loads(files_j)
        total_files.update(files)
        commits = json.loads(commits_j)
        total_commits += len(commits)
        dur_str = f"{int(duration or 0)}m"
        print(f"  [{project}] {title or 'Untitled'} ({dur_str}, {msgs} msgs)")

    print()
    print(f"Sessions: {len(rows)}")
    print(f"Projects: {len(projects)}")
    print(f"Active time: ~{int(total_duration)}m")
    print(f"Files touched: {len(total_files)}")
    print(f"Commits: {total_commits}")

    if summary:
        print()
        print(f"Digest: {summary[0]}")


def cmd_export(args):
    """Export session data as JSON."""
    target_date = None
    if "--date" in args:
        idx = args.index("--date")
        target_date = args[idx + 1]
    else:
        target_date = datetime.now().strftime("%Y-%m-%d")

    db = get_db()
    rows = db.execute(
        "SELECT * FROM sessions WHERE date = ? ORDER BY started_at",
        (target_date,),
    ).fetchall()
    cols = [
        d[0] for d in db.execute("SELECT * FROM sessions LIMIT 0").description
    ]
    db.close()

    sessions = []
    for row in rows:
        entry = dict(zip(cols, row))
        for key in (
            "files_touched",
            "tools_used",
            "commits",
            "mr_prs",
            "jira_tickets",
            "key_topics",
            "user_snippets",
            "assistant_snippets",
        ):
            if key in entry and isinstance(entry[key], str):
                entry[key] = json.loads(entry[key])
        sessions.append(entry)

    print(json.dumps({"date": target_date, "sessions": sessions}, indent=2))


def cmd_list_dates(_args):
    """List all dates with sessions."""
    db = get_db()
    rows = db.execute(
        """SELECT date, COUNT(*) as cnt, SUM(duration_minutes) as total_min,
                  COUNT(DISTINCT project_short) as projects
           FROM sessions GROUP BY date ORDER BY date DESC"""
    ).fetchall()
    db.close()

    if not rows:
        print("No sessions collected yet. Run 'backfill' first.")
        return

    for date, count, total_min, projects in rows:
        has_summary = (REPORTS_DIR / date / "full.md").exists()
        marker = " [summarized]" if has_summary else ""
        print(
            f"  {date}: {count} sessions, "
            f"{int(total_min or 0)}m, {projects} projects{marker}"
        )


def cmd_version(_args):
    """Print version."""
    from daily_claude_log import __version__

    print(f"daily-claude-log {__version__}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "collect": cmd_collect,
        "collect-all": cmd_collect_all,
        "backfill": cmd_backfill,
        "prompt": cmd_prompt,
        "store-summary": cmd_store_summary,
        "status": cmd_status,
        "export": cmd_export,
        "list-dates": cmd_list_dates,
        "version": cmd_version,
        "--version": cmd_version,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
