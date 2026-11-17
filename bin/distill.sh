#!/bin/zsh
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
exec "$ROOT/bin/_claude.sh" distill "$ROOT/prompts/distill.md" \
  --allowedTools "Read" "Glob" "Grep" "Bash(date:*)" "Bash(jq:*)" \
  "Edit($R/queue/**)" "Write($R/queue/**)" \
  "Write($R/state/distill.last_run)" "Bash(cat:*)" "Bash(wc:*)" \
  
