#!/bin/zsh
# Meeting agent for one meeting item: prep (collect attendees' open items, check status, write the agenda) or
# debrief (read the notes, propose updates), or reconcile (redraft the updates from how the owner settled differences between
# his notes and the meeting notes). The app starts it when the owner chooses a meeting, marks it run, and settles differences.
# Usage: bin/meeting.sh <item_id> <step_id>   (the step's meeting_phase says prep or debrief)
set -euo pipefail
ROOT="${0:A:h:h}"
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
ITEM="$1"; STEP="$2"
[[ "$ITEM" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] || { echo "bad item id" >&2; exit 2; }
[[ "$STEP" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] || { echo "bad step id" >&2; exit 2; }
F="$ROOT/queue/items/$ITEM.json"
[[ -f "$F" ]] || { echo "no item $ITEM"; exit 1; }
PHASE=$(python3 -I -c 'import json,sys; i=json.load(open(sys.argv[1])); print(next(s.get("meeting_phase","") for s in i["steps"] if s["id"]==sys.argv[2]))' "$F" "$STEP")
[[ "$PHASE" == prep || "$PHASE" == debrief || "$PHASE" == reconcile ]] || { echo "step $STEP is not a meeting agent step"; exit 1; }
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')
mkdir -p "$ROOT/agents/$ITEM/$STEP"
[[ "$PHASE" == prep ]] && python3 -I "$ROOT/bin/meetings.py" collect "$ITEM" > /dev/null
TMP="$ROOT/state/prompt-meeting-$ITEM.md"
sed -e "s|{{ITEM}}|$ITEM|g" -e "s|{{STEP}}|$STEP|g" -e "s|{{NOW}}|$NOW|g" "$ROOT/prompts/meeting-$PHASE.md" > "$TMP"

# Reads everywhere it needs; writes only to this meeting's folder and its own item file. No sends, merges or edits elsewhere.
ALLOWED=(
  "Read" "Glob" "Grep"
  "Write($R/agents/$ITEM/**)" "Edit($R/agents/$ITEM/**)"
  "Edit($R/queue/items/$ITEM.json)"
  "Bash(bin/sandbox.sh python3:*)" "Bash($ROOT/bin/sandbox.sh python3:*)" "Bash(python3 bin/figma_read.py:*)" "Bash(jq:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Bash(tail:*)" "Bash(wc:*)" "Bash(date:*)"
  "Bash(bin/gitread.sh:*)" "Bash($ROOT/bin/gitread.sh:*)" "Bash(gh pr view:*)" "Bash(gh pr list:*)" "Bash(gh search prs:*)"
  ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"}
)
exec "$ROOT/bin/_claude.sh" "agent-$ITEM" "$TMP" \
  --add-dir ~/Projects "$HOME/.claude/projects/${HOME//[\/.]/-}/memory" \
  --allowedTools "${ALLOWED[@]}"
