#!/bin/zsh
# Meeting agent for one meeting item: prep (collect attendees' open items, check status, write the agenda) or
# debrief (read the notes, propose updates), or reconcile (redraft the updates from how the owner settled differences between
# his notes and the meeting notes). The app starts it when the owner chooses a meeting, marks it run, and settles differences.
# Usage: bin/meeting.sh <item_id> <step_id>   (the step's meeting_phase says prep or debrief)
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
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
# Prep: the meeting, its agenda source, the rules and the ledger's recent changes go in the prompt, not file by file.
[[ "$PHASE" == prep ]] && /opt/homebrew/bin/python3 -I "$ROOT/bin/meeting_context.py" "$ITEM" "$STEP" >> "$TMP"

# Reads everywhere it needs; writes only to this meeting's folder and its own item file. No sends, merges or edits elsewhere.
ALLOWED=(
  "Read" "Glob" "Grep"
  "Write($R/agents/$ITEM/**)" "Edit($R/agents/$ITEM/**)"
  "Edit($R/queue/items/$ITEM.json)"
  "Bash(bin/sandbox.sh python3:*)" "Bash($ROOT/bin/sandbox.sh python3:*)" "Bash(python3 bin/figma_read.py:*)" "Bash(jq:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Bash(tail:*)" "Bash(wc:*)" "Bash(date:*)"
  "Bash(bin/gitread.sh:*)" "Bash($ROOT/bin/gitread.sh:*)" "Bash(gh pr view:*)" "Bash(gh pr list:*)" "Bash(gh search prs:*)"
  ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"}
)
# Prep with more than 4 at-risk rows: check their status in up to 3 lanes at once (whole owners per lane), then one run
# writes the agenda from the results. While the lanes run, this script holds the meeting's run lock so the app shows it
# running; it lets go just before the final run takes it.
if [[ "$PHASE" == prep ]]; then
  LANES=$(/opt/homebrew/bin/python3 -I - "$ROOT/agents/$ITEM/$STEP" <<'PY'
import json, math, sys
from pathlib import Path
d = Path(sys.argv[1])
groups = json.loads((d / "items.json").read_text()).get("at_risk") or {}
n = sum(len(v) for v in groups.values())
k = 0 if n <= 4 else min(3, math.ceil(n / 5))
lanes = [dict() for _ in range(k)]
size = math.ceil(n / k) if k else 0
for owner, rows in sorted(groups.items(), key=lambda x: -len(x[1])):      # biggest owners first, onto the lightest lane;
    for c in range(0, len(rows), size or 1):                               # an owner bigger than a lane's share is split
        if k:
            lane = min(lanes, key=lambda l: sum(len(v) for v in l.values()))
            lane.setdefault(owner, []).extend(rows[c:c + size])
for i, lane in enumerate(lanes, 1):
    (d / f"lane-{i}.json").write_text(json.dumps(lane, ensure_ascii=False, indent=1))
    (d / f"check-{i}.json").unlink(missing_ok=True)
print(k)
PY
)
  if (( LANES > 0 )); then
    mkdir -p "$ROOT/state/agent-$ITEM.lock"; echo $$ > "$ROOT/state/agent-$ITEM.lock/pid"
    CHECK_ALLOWED=("Read" "Glob" "Grep" "Write($R/agents/$ITEM/$STEP/check-*.json)" "Edit($R/agents/$ITEM/$STEP/check-*.json)" "Bash(gh pr view:*)" ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"})
    for i in $(seq 1 $LANES); do
      P="$ROOT/state/prompt-meeting-$ITEM-check$i.md"
      /opt/homebrew/bin/python3 -I - "$ROOT/prompts/meeting-check.md" "$ROOT/agents/$ITEM/$STEP/lane-$i.json" "$ITEM" "$STEP" "$i" "$NOW" > "$P" <<'PY'
import sys
tpl, rows, item, step, lane, now = sys.argv[1:7]
t = open(tpl).read()
for k, v in {"{{ROWS}}": open(rows).read(), "{{ITEM}}": item, "{{STEP}}": step, "{{LANE}}": lane, "{{NOW}}": now}.items():
    t = t.replace(k, v)
print(t)
PY
      "$ROOT/bin/_claude.sh" "agent-$ITEM-check$i" "$P" --allowedTools "${CHECK_ALLOWED[@]}" &
    done
    wait
    /opt/homebrew/bin/python3 -I - "$ROOT/agents/$ITEM/$STEP" "$LANES" >> "$TMP" <<'PY'
import json, sys
from pathlib import Path
d, k = Path(sys.argv[1]), int(sys.argv[2])
res, missing = [], []
for i in range(1, k + 1):
    f = d / f"check-{i}.json"
    try:
        res += json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        missing.append(i)
print("\n## Status checks already done\n\nParallel checkers looked up every at-risk row's latest status; their results are below. "
      "Step 3 is done for these rows: use the results, and look something up yourself only for rows marked `not_checked`"
      + (f" or rows from lanes {missing}, which returned nothing" if missing else "") + ".\n\n```json\n" + json.dumps(res, ensure_ascii=False, indent=1) + "\n```")
PY
    rm -rf "$ROOT/state/agent-$ITEM.lock"
  fi
fi
exec "$ROOT/bin/_claude.sh" "agent-$ITEM" "$TMP" \
  --add-dir ~/Projects "$HOME/.claude/projects/${HOME//[\/.]/-}/memory" \
  --allowedTools "${ALLOWED[@]}"
