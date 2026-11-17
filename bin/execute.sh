#!/bin/zsh
# Runs queued steps the owner pressed. Plain code (bin/execute.py): each step needs a matching press (bin/press.py).
# Output goes to logs/execute-<date>.log, so a failure is never silent.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
ROOT="${0:A:h:h}"
exec /opt/homebrew/bin/python3 -I "$ROOT/bin/execute.py" "$@" >> "$ROOT/logs/execute-$(date +%Y%m%d).log" 2>&1
