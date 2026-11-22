#!/bin/zsh
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
# Code prepares the slice (new actions, changed feedback memories, unread sources) and moves the cursor;
# the model only judges it (P40). Nothing new: no run.
set +e; /opt/homebrew/bin/python3 -I "$ROOT/bin/distill_prep.py" prepare; RC=$?; set -e
(( RC == 3 )) && exit 0
(( RC != 0 )) && exit $RC
"$ROOT/bin/_claude.sh" distill "$ROOT/prompts/distill.md" \
  --allowedTools "Read" "Glob" "Grep" "Bash(date:*)" "Bash(jq:*)" \
  "Edit($R/queue/**)" "Write($R/queue/**)" "Bash(cat:*)" "Bash(wc:*)" || true
/opt/homebrew/bin/python3 -I "$ROOT/bin/distill_prep.py" commit "$(cat "$ROOT/state/distill.current")"
