#!/bin/zsh
# Answer the owner's questions on one item. The app starts it on Ask.
# Usage: bin/chat.sh <item_id>
set -euo pipefail
ROOT="${0:A:h:h}"
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
ITEM="$1"
[[ "$ITEM" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] || { echo "bad item id" >&2; exit 2; }
[[ -f "$ROOT/queue/items/$ITEM.json" ]] || { echo "no item $ITEM"; exit 1; }
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')
TMP="$ROOT/state/prompt-chat-$ITEM.md"
sed -e "s|{{ITEM}}|$ITEM|g" -e "s|{{NOW}}|$NOW|g" "$ROOT/prompts/chat.md" > "$TMP"
ALLOWED=(
  "Read" "Glob" "Grep" "WebSearch"
  "Edit($R/queue/items/**)"
  "Bash(python3 bin/figma_read.py:*)" "Bash(jq:*)" "Bash(ls:*)"
  ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"}
)
/opt/homebrew/bin/python3 -I "$ROOT/bin/knowledge.py" "$ROOT/queue/items/$ITEM.json" >> "$TMP"  # The owner's positions on this item's topics
exec "$ROOT/bin/_claude.sh" "chat-$ITEM" "$TMP" \
  --add-dir ~/Projects "$HOME/.claude/projects/${HOME//[\/.]/-}/memory" \
  --allowedTools "${ALLOWED[@]}"
