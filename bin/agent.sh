#!/bin/zsh
# Run a research agent on one step. The app starts it when the owner starts the agent from the Agent panel (Agent button or h).
# Usage: bin/agent.sh <item_id> <step_id>
set -euo pipefail
ROOT="${0:A:h:h}"
ITEM="$1"; STEP="$2"
[[ "$ITEM" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] || { echo "bad item id" >&2; exit 2; }
[[ "$STEP" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] || { echo "bad step id" >&2; exit 2; }
[[ -f "$ROOT/queue/items/$ITEM.json" ]] || { echo "no item $ITEM"; exit 1; }
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')
WORK="$ROOT/agents/$ITEM/$STEP"
mkdir -p "$WORK"
TMP="$ROOT/state/prompt-agent-$ITEM.md"
sed -e "s|{{ITEM}}|$ITEM|g" -e "s|{{STEP}}|$STEP|g" -e "s|{{NOW}}|$NOW|g" "$ROOT/prompts/agent.md" > "$TMP"

source "$ROOT/bin/_agent_tools.zsh"
/opt/homebrew/bin/python3 -I "$ROOT/bin/knowledge.py" "$ROOT/queue/items/$ITEM.json" >> "$TMP"  # The owner's positions on this item's topics
/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" sources >> "$TMP"   # every connector in config/connectors.json, with what to read
# The session is kept so the owner can talk to this agent afterwards (Talk panel): bin/agent-talk.sh resumes it.
JB_KEEP_SESSION=1 "$ROOT/bin/_claude.sh" "agent-$ITEM" "$TMP" \
  --add-dir ~/Projects "$HOME/.claude/projects/${HOME//[\/.]/-}/memory" \
  --allowedTools "${ALLOWED[@]}" || true
/opt/homebrew/bin/python3 -I "$ROOT/bin/agent_session.py" record "$ITEM" "$STEP"
# The owner may have replied while it worked: answer those now.
exec "$ROOT/bin/agent-talk.sh" "$ITEM" "$STEP"
