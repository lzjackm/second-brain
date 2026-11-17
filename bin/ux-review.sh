#!/bin/zsh
# Weekly UX review: summarize real usage in code, then one agent proposes at most 5 changes as a queue item.
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"; PY=/opt/homebrew/bin/python3
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/'); DATE=$(TZ=America/New_York date +%Y-%m-%d)
TMP="$ROOT/state/prompt-ux-review.md"
sed -e "s|{{NOW}}|$NOW|g" -e "s|{{DATE}}|$DATE|g" "$ROOT/prompts/ux-review.md" > "$TMP"
$PY -I "$ROOT/bin/ux_summary.py" 7 >> "$TMP"
exec "$ROOT/bin/_claude.sh" "ux-review" "$TMP" --allowedTools "Read" "Glob" "Grep" "Edit($R/queue/items/**)"
