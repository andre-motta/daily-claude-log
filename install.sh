#!/usr/bin/env bash
set -euo pipefail

# daily-claude-log installer
# Sets up hooks and skills for Claude Code and Codex session tracking.

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
CLAUDE_SETTINGS_FILE="$CLAUDE_DIR/settings.json"
CODEX_HOOKS_FILE="$CODEX_DIR/hooks.json"
CLAUDE_SKILLS_DIR="$CLAUDE_DIR/skills"
CODEX_SKILLS_DIR="$HOME/.agents/skills"
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
        echo "  export DCL_CODEX_DIR=\"$CODEX_DIR\"  # optional, this is the default"
        echo ""

        export DCL_DATA_DIR="$data_dir"
    fi

    mkdir -p "${data_dir/#\~/$HOME}/reports"
    info "Data directory: ${data_dir/#\~/$HOME}"
}

# --- Install binary ---

install_binary() {
    # Remove old symlink if present (from pre-pip versions)
    if [ -L "$BIN_DIR/daily-claude-log" ]; then
        rm "$BIN_DIR/daily-claude-log"
        info "Removed old symlink"
    fi

    pip install -e "$REPO_DIR" --quiet 2>/dev/null || pip install -e "$REPO_DIR"
    info "Installed daily-claude-log via pip (editable mode)"

    if ! command -v daily-claude-log &> /dev/null; then
        warn "daily-claude-log not found in PATH after pip install"
        warn "You may need to add your Python scripts directory to PATH"
    fi
}

# --- Install hook ---

install_hook_file() {
    local settings_file="$1"
    local host_name="$2"
    local hook_cmd="$BIN_DIR/daily-claude-log collect-hook"

    mkdir -p "$(dirname "$settings_file")"
    if [ ! -f "$settings_file" ]; then
        echo '{}' > "$settings_file"
    fi

    python3 - "$settings_file" "$hook_cmd" <<'PY'
import json
import sys

settings_path, hook_command = sys.argv[1:]
with open(settings_path) as settings_file:
    settings = json.load(settings_file)

session_end = settings.setdefault("hooks", {}).setdefault("SessionEnd", [])
found = False
for group in session_end:
    for hook in group.get("hooks", []):
        if "daily-claude-log" in hook.get("command", ""):
            hook["command"] = hook_command
            hook["timeout"] = 10
            found = True

if not found:
    session_end.append({
        "hooks": [{
            "type": "command",
            "command": hook_command,
            "timeout": 10,
        }]
    })

with open(settings_path, "w") as settings_file:
    json.dump(settings, settings_file, indent=2)
    settings_file.write("\n")
PY
    info "$host_name SessionEnd hook installed"
}

install_hooks() {
    install_hook_file "$CLAUDE_SETTINGS_FILE" "Claude Code"
    install_hook_file "$CODEX_HOOKS_FILE" "Codex"
}

# --- Install skills ---

install_skills_in() {
    local skills_dir="$1"
    local host_name="$2"
    mkdir -p "$skills_dir"

    for skill_dir in "$REPO_DIR"/skills/*/; do
        [ -d "$skill_dir" ] || continue
        local skill_name
        skill_name="$(basename "$skill_dir")"
        local target="$skills_dir/$skill_name"

        if [ -L "$target" ]; then
            rm "$target"
        fi

        if [ -d "$target" ]; then
            warn "Skill $skill_name already exists (not a symlink). Skipping."
            continue
        fi

        ln -s "$skill_dir" "$target"
        info "$host_name skill installed: $skill_name"
    done
}

install_skills() {
    install_skills_in "$CLAUDE_SKILLS_DIR" "Claude Code"
    install_skills_in "$CODEX_SKILLS_DIR" "Codex"
}

# --- Init database ---

init_db() {
    daily-claude-log list-dates > /dev/null 2>&1
    info "Database initialized"
}

# --- Main ---

echo ""
echo "=== daily-claude-log installer ==="
echo ""

check_env
install_binary
install_hooks
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
echo "  Claude Code and Codex skills:"
echo "    /daily-summary                        # generate AI summary of your day"
echo "    /collect-session                      # manually log current session"
echo ""
echo "  Sessions auto-collected when Claude Code or Codex ends a session."
echo ""
