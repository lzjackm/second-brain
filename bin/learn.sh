#!/bin/zsh
# One tutor turn for a Learn topic. The app starts it when the owner sends a message or presses Teach me / Quiz / Ask.
# Usage: bin/learn.sh <slug> <start|continue|quiz|ask|final>
# No work sources: the tutor sees only the topic's own state and the public web.
set -euo pipefail
ROOT="${0:A:h:h}"
SLUG="$1"; MODE="${2:-continue}"
[[ "$SLUG" =~ ^[a-z0-9-]+$ && -f "$ROOT/learn/topics/$SLUG.json" ]] || { echo "no topic $SLUG"; exit 1; }
PY=/opt/homebrew/bin/python3
TMP="$ROOT/state/prompt-learn-$SLUG.md"
$PY -I "$ROOT/bin/learn.py" build "$SLUG" "$MODE" "$TMP"
START=$(date +%s)
"$ROOT/bin/_claude.sh" "learn-$SLUG" "$TMP" --allowedTools "WebSearch" "WebFetch" --include-partial-messages || true
LOG=$(ls -t "$ROOT"/logs/learn-$SLUG-*.log 2>/dev/null | head -1 || true)
# Only apply a log this run wrote; if another turn held the lock, that turn applies its own.
if [[ -n "$LOG" ]] && (( $(stat -f %m "$LOG") >= START )); then
  $PY -I "$ROOT/bin/learn.py" apply "$SLUG" "$LOG"
fi
