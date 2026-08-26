#!/usr/bin/env bash
set -euo pipefail

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

echo ""
echo "=== daily-claude-log uninstaller ==="
echo ""

# Remove binary symlink
if [ -L "$BIN_DIR/daily-claude-log" ]; then
    rm "$BIN_DIR/daily-claude-log"
    info "Removed symlink $BIN_DIR/daily-claude-log"
fi

# Remove hooks from Claude Code and Codex settings.
remove_hook() {
    local settings_file="$1"
    local host_name="$2"
    if [ ! -f "$settings_file" ]; then
        return
    fi
    python3 - "$settings_file" <<'PY'
import json
import sys

settings_path = sys.argv[1]
with open(settings_path) as f:
    settings = json.load(f)

hooks = settings.get('hooks', {})
session_end = hooks.get('SessionEnd', [])
hooks['SessionEnd'] = [
    g for g in session_end
    if not any('daily-claude-log' in h.get('command', '') for h in g.get('hooks', []))
]
if not hooks['SessionEnd']:
    del hooks['SessionEnd']

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
PY
    info "Removed $host_name SessionEnd hook"
}

remove_hook "$CLAUDE_SETTINGS_FILE" "Claude Code"
remove_hook "$CODEX_HOOKS_FILE" "Codex"

# Remove skill symlinks
for skills_dir in "$CLAUDE_SKILLS_DIR" "$CODEX_SKILLS_DIR"; do
    for skill in daily-summary collect-session; do
        target="$skills_dir/$skill"
        if [ -L "$target" ]; then
            rm "$target"
            info "Removed skill: $target"
        fi
    done
done

echo ""
info "Uninstalled. Data in \$DCL_DATA_DIR was NOT deleted."
echo "  Remove DCL_DATA_DIR and DCL_CLAUDE_DIR from your shell profile manually."
echo ""
