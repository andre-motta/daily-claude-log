#!/usr/bin/env bash
set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
SKILLS_DIR="$CLAUDE_DIR/skills"
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

# Remove hook from settings.json
if [ -f "$SETTINGS_FILE" ]; then
    python3 -c "
import json

with open('$SETTINGS_FILE') as f:
    settings = json.load(f)

hooks = settings.get('hooks', {})
session_end = hooks.get('SessionEnd', [])
hooks['SessionEnd'] = [
    g for g in session_end
    if not any('daily-claude-log' in h.get('command', '') for h in g.get('hooks', []))
]
if not hooks['SessionEnd']:
    del hooks['SessionEnd']

with open('$SETTINGS_FILE', 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
" 2>/dev/null && info "Removed SessionEnd hook" || warn "Could not remove hook"
fi

# Remove skill symlinks
for skill in daily-summary collect-session; do
    target="$SKILLS_DIR/$skill"
    if [ -L "$target" ]; then
        rm "$target"
        info "Removed skill: $skill"
    fi
done

echo ""
info "Uninstalled. Data in \$DCL_DATA_DIR was NOT deleted."
echo "  Remove DCL_DATA_DIR and DCL_CLAUDE_DIR from your shell profile manually."
echo ""
