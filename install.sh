#!/usr/bin/env bash
set -euo pipefail

# daily-claude-log installer
# Sets up hooks, skills, and symlink for Claude Code session tracking.

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
SKILLS_DIR="$CLAUDE_DIR/skills"
BIN_DIR="$HOME/.local/bin"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[daily-claude-log]${NC} $1"; }
warn() { echo -e "${YELLOW}[daily-claude-log]${NC} $1"; }

# --- Environment ---

check_env() {
    local data_dir="${DCL_DATA_DIR:-}"

    if [ -z "$data_dir" ]; then
        echo ""
        echo "Where should daily-claude-log store data (SQLite DB + markdown reports)?"
        echo "This can be a private git repo you push to a remote."
        echo ""
        read -rp "Data directory [~/.daily-claude-log]: " data_dir
        data_dir="${data_dir:-$HOME/.daily-claude-log}"
        data_dir="${data_dir/#\~/$HOME}"

        echo ""
        echo "Add these to your shell profile (~/.bashrc, ~/.zshrc, or ~/.env_local):"
        echo ""
        echo "  export DCL_DATA_DIR=\"$data_dir\""
        echo "  export DCL_CLAUDE_DIR=\"$HOME/.claude\"  # optional, this is the default"
        echo ""

        export DCL_DATA_DIR="$data_dir"
    fi

    mkdir -p "${data_dir/#\~/$HOME}/reports"
    info "Data directory: ${data_dir/#\~/$HOME}"
}

# --- Install binary ---

install_binary() {
    mkdir -p "$BIN_DIR"

    if [ -L "$BIN_DIR/daily-claude-log" ] || [ -f "$BIN_DIR/daily-claude-log" ]; then
        rm "$BIN_DIR/daily-claude-log"
    fi

    ln -s "$REPO_DIR/recap.py" "$BIN_DIR/daily-claude-log"
    chmod +x "$REPO_DIR/recap.py"
    info "Linked daily-claude-log -> $REPO_DIR/recap.py"

    if ! echo "$PATH" | grep -q "$BIN_DIR"; then
        warn "$BIN_DIR not in PATH. Add to shell profile:"
        warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
}

# --- Install hook ---

install_hook() {
    if [ ! -f "$SETTINGS_FILE" ]; then
        warn "Claude Code settings not found at $SETTINGS_FILE"
        warn "Skipping hook. Run Claude Code once first, then re-run install."
        return
    fi

    local hook_cmd="$BIN_DIR/daily-claude-log collect \$CLAUDE_CODE_SESSION_ID"

    python3 -c "
import json, sys

with open('$SETTINGS_FILE') as f:
    settings = json.load(f)

hooks = settings.setdefault('hooks', {})
session_end = hooks.setdefault('SessionEnd', [])

for group in session_end:
    for h in group.get('hooks', []):
        if 'daily-claude-log' in h.get('command', ''):
            print('exists')
            sys.exit(0)

session_end.append({
    'hooks': [{
        'type': 'command',
        'command': '$hook_cmd',
        'timeout': 10
    }]
})

with open('$SETTINGS_FILE', 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')

print('installed')
" 2>/dev/null

    if python3 -c "
import json
with open('$SETTINGS_FILE') as f:
    s = json.load(f)
for g in s.get('hooks',{}).get('SessionEnd',[]):
    for h in g.get('hooks',[]):
        if 'daily-claude-log' in h.get('command',''):
            exit(0)
exit(1)
" 2>/dev/null; then
        info "SessionEnd hook installed"
    else
        warn "Could not install hook. Add manually to $SETTINGS_FILE"
    fi
}

# --- Install skills ---

install_skills() {
    mkdir -p "$SKILLS_DIR"

    for skill_dir in "$REPO_DIR"/skills/*/; do
        [ -d "$skill_dir" ] || continue
        local skill_name
        skill_name="$(basename "$skill_dir")"
        local target="$SKILLS_DIR/$skill_name"

        if [ -L "$target" ]; then
            rm "$target"
        fi

        if [ -d "$target" ]; then
            warn "Skill $skill_name already exists (not a symlink). Skipping."
            continue
        fi

        ln -s "$skill_dir" "$target"
        info "Skill installed: $skill_name"
    done
}

# --- Init database ---

init_db() {
    python3 "$REPO_DIR/recap.py" list-dates > /dev/null 2>&1
    info "Database initialized"
}

# --- Main ---

echo ""
echo "=== daily-claude-log installer ==="
echo ""

check_env
install_binary
install_hook
install_skills
init_db

echo ""
info "Installation complete!"
echo ""
echo "  Commands:"
echo "    daily-claude-log status              # today's sessions"
echo "    daily-claude-log backfill --days 30   # populate historical data"
echo "    daily-claude-log list-dates           # all dates with data"
echo ""
echo "  Claude Code skills:"
echo "    /daily-summary                        # generate AI summary of your day"
echo "    /collect-session                      # manually log current session"
echo ""
echo "  Sessions auto-collected on Claude Code exit."
echo ""
