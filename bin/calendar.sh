#!/bin/zsh
# Fetch the owner's meetings for one week (Monday to Sunday, containing the given date) into state/calendar/<date>.json,
# one file per day (read only). launchd runs it every Monday at 9 AM ET (com.secondbrain.calendar); the Meetings page
# starts it on Refresh.
# Usage: bin/calendar.sh [YYYY-MM-DD]
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
DATE="${1:-$(TZ=America/New_York date +%Y-%m-%d)}"
[[ "$DATE" =~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' ]] || { echo "bad date $DATE"; exit 1; }
read MONDAY SUNDAY <<< "$(python3 -I -c 'import datetime as d,sys; t=d.date.fromisoformat(sys.argv[1]); m=t-d.timedelta(days=t.weekday()); print(m, m+d.timedelta(days=6))' "$DATE")"
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')
mkdir -p "$ROOT/state/calendar"
TMP="$ROOT/state/prompt-calendar-$MONDAY.md"
sed -e "s|{{MONDAY}}|$MONDAY|g" -e "s|{{SUNDAY}}|$SUNDAY|g" -e "s|{{NOW}}|$NOW|g" "$ROOT/prompts/calendar.md" > "$TMP"
# Read tools of the Calendar connector only: never create_event, update_event, delete_event or respond_to_event.
exec "$ROOT/bin/_claude.sh" "calendar-$MONDAY" "$TMP" \
  --allowedTools "Read" "Write($R/state/calendar/**)" "Edit($R/state/calendar/**)" \
  ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"} \
