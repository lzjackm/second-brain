#!/bin/zsh
# Daily housekeeping (launchd, 1:45 PM ET). Keeps reports, scripts and small derived data; prunes what grows without limit.
#  - Agent runs: raw downloads (raw*/ folders, files over 10 MB) once those files are 3+ days old, judged by the files
#    themselves (an agent touching its folder no longer keeps 40 MB of downloads alive).
#  - Run traces (logs/*.trace.jsonl, about 16 MB a day): gzip after 3 days, delete after 14. Run results and errors
#    (.json, .err, .log): 30 days; empty .err files at once.
#  - State: rendered prompts after 7 days; briefs and signals after 14; one-off backups (*.tgz, *.before-*) after 7.
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"
cd "$ROOT"
before=$(du -sk agents logs state 2>/dev/null | awk '{s+=$1} END {print s+0}')
for run in agents/*/*(N/); do
  [[ -d "state/agent-${run:h:t}.lock" ]] && continue          # never touch a running agent
  find "$run" -type d -name 'raw*' -prune -mtime +3 -exec rm -rf {} +
  find "$run" -type f -size +10M -mtime +3 ! -name 'REPORT.md' -delete
  find "$run" -type d -name '__pycache__' -prune -exec rm -rf {} +
done
find logs -type f -name '*.trace.jsonl' -mtime +3 -exec gzip -q {} \;
find logs -type f -name '*.trace.jsonl.gz' -mtime +14 -delete
find logs -type f \( -name '*.log' -o -name '*.log.json' -o -name '*.log.err' -o -name '*.out' \) -mtime +30 -delete
find logs -type f -name '*.err' -size 0 -mmin +60 -delete
find state -maxdepth 1 -type f -name 'prompt-*.md' -mtime +7 -delete
find state/briefs state/signals -type f -mtime +14 -delete 2>/dev/null || true
find state -maxdepth 1 -type f \( -name '*.tgz' -o -name '*.before-*' \) -mtime +7 -delete
after=$(du -sk agents logs state 2>/dev/null | awk '{s+=$1} END {print s+0}')
echo "$(TZ=America/New_York date '+%Y-%m-%d %H:%M ET') cleanup freed $(( (before - after) / 1024 )) MB"
