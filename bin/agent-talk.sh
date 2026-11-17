#!/bin/zsh
# Answer the owner's replies to the research agent on one step (the app's Talk panel), resuming the agent's own session so
# it keeps everything it already read. Loops while the owner has written something the agent hasn't answered.
# Usage: bin/agent-talk.sh <item_id> <step_id>
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"
ITEM="$1"; STEP="$2"
[[ "$ITEM" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] || { echo "bad item id" >&2; exit 2; }
[[ "$STEP" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] || { echo "bad step id" >&2; exit 2; }
PY=/opt/homebrew/bin/python3
[[ -f "$ROOT/queue/items/$ITEM.json" ]] || { echo "no item $ITEM"; exit 1; }
# One run per item at a time: a running agent answers pending replies itself when it finishes (agent.sh ends here).
if [[ -d "$ROOT/state/agent-$ITEM.lock" ]] && kill -0 "$(cat "$ROOT/state/agent-$ITEM.lock/pid" 2>/dev/null || echo 0)" 2>/dev/null; then
  echo "agent running; it answers when done"; exit 0
fi
source "$ROOT/bin/_agent_tools.zsh"
for round in {1..5}; do
  MSG=$($PY -I "$ROOT/bin/agent_session.py" pending "$ITEM" "$STEP") || exit 0
  # No saved session (the agent ran before Talk existed): start a new one that reads the earlier work first.
  RESUME=(); CONTEXT="Your earlier work on this step is in this session; continue from it."
  if SID=$($PY -I "$ROOT/bin/agent_session.py" session "$ITEM" "$STEP"); then RESUME=(--resume "$SID")
  else CONTEXT="This session has no memory of your earlier work. Before answering, read the item file, your report at agents/$ITEM/$STEP/REPORT.md, and the conversation so far in agents/$ITEM/$STEP/talk.jsonl. Your original instructions are prompts/agent.md (step $STEP of $ITEM)."; fi
  NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')
  TMP="$ROOT/state/prompt-agent-talk-$ITEM.md"
  $PY -I - "$ROOT/prompts/agent-talk.md" "$TMP" "$ITEM" "$STEP" "$NOW" "$MSG" "$CONTEXT" <<'PY'
import sys
src, out, item, step, now, msg, ctx = sys.argv[1:8]
open(out, "w").write(open(src).read().replace("{{ITEM}}", item).replace("{{STEP}}", step).replace("{{NOW}}", now)
                     .replace("{{CONTEXT}}", ctx).replace("{{MESSAGE}}", msg))
PY
  JB_KEEP_SESSION=1 "$ROOT/bin/_claude.sh" "agent-$ITEM" "$TMP" "${RESUME[@]}" \
    --add-dir ~/Projects "$HOME/.claude/projects/${HOME//[\/.]/-}/memory" \
    --allowedTools "${ALLOWED[@]}" || true
  $PY -I "$ROOT/bin/agent_session.py" record "$ITEM" "$STEP"
done
