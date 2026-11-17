#!/bin/zsh
# Run one lead. Usage: bin/run-lead.sh <area> [lead|revise]
# "revise" is the fast path the app starts when the owner asks for a revision or a redraft:
# it only reworks the items he touched and skips the full source sweep.
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"
AREA="$1"
MODE="${2:-lead}"
# The sync pass yields to a full lead run on the same area.
if [[ "$MODE" == "sync" && -d "$ROOT/state/lead-$AREA.lock" ]] && kill -0 "$(cat "$ROOT/state/lead-$AREA.lock/pid" 2>/dev/null || echo 0)" 2>/dev/null; then echo "lead running; sync skipped"; exit 0; fi
[[ -f "$ROOT/leads/$AREA.md" ]] || { echo "no lead spec leads/$AREA.md"; exit 1; }
# One run per area at a time: the lead and the pipeline take the same lock (mkdir is atomic, so two runs that start in
# the same second, as macOS does with missed schedules on wake, cannot both get it). A dead holder's lock is taken over.
take_run_lock() {
  local L="$ROOT/state/run-$AREA.lock"
  if ! mkdir "$L" 2>/dev/null; then
    local P=$(cat "$L/pid" 2>/dev/null || echo 0)
    if kill -0 "$P" 2>/dev/null; then echo "another $AREA run is active (pid $P); skipped"; exit 0; fi
    rm -rf "$L"; mkdir "$L" 2>/dev/null || { echo "lost the $AREA run lock race; skipped"; exit 0; }
  fi
  echo $$ > "$L/pid"
}
# The full lead takes it (the exec below keeps this pid, so the lock lives exactly as long as the run). Revise and
# sync are quick passes on items the owner touched and stay out of it.
[[ "$MODE" == "lead" ]] && take_run_lock
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')
DATE=$(TZ=America/New_York date +%Y-%m-%d)
TITLE="${(C)AREA}"
TMP="$ROOT/state/prompt-$MODE-$AREA.md"
# Deterministic prefetch (git, gh) so the lead needs no shell access to other repos.
"$ROOT/bin/prefetch.sh" "$AREA" || echo "prefetch for $AREA failed; lead runs on sources it can reach" >&2
sed -e "s|{{AREA}}|$AREA|g" -e "s|{{AREA_TITLE}}|$TITLE|g" -e "s|{{NOW}}|$NOW|g" -e "s|{{DATE}}|$DATE|g" \
  "$ROOT/prompts/$MODE.md" > "$TMP"

source "$ROOT/bin/_lead_tools.zsh"
# The owner's positions (brain/knowledge) on any topic the area's live items touch.
LIVE=($(/opt/homebrew/bin/python3 -I -c 'import json,sys,glob; [print(f) for f in glob.glob(sys.argv[1]+"/queue/items/*.json") if json.load(open(f)).get("area")==sys.argv[2] and json.load(open(f)).get("status") in ("open","waiting","working","reconciling","snoozed")]' "$ROOT" "$AREA"))
(( ${#LIVE} )) && /opt/homebrew/bin/python3 -I "$ROOT/bin/knowledge.py" "${LIVE[@]}" >> "$TMP" || true
/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" sources "$AREA" "$MODE" >> "$TMP"   # watch list with per-connector windows, plus lookups (config/connectors.json)
# Local sources of truth the lead may read (config/brain.json source_dirs, set during onboarding).
SOURCE_DIRS=$(/opt/homebrew/bin/python3 -I -c 'import json,os,sys; c=json.load(open(sys.argv[1])); print(" ".join(os.path.expanduser(d) for d in c.get("source_dirs") or []) or sys.argv[2])' "$ROOT/config/brain.json" "$ROOT")
exec "$ROOT/bin/_claude.sh" "$MODE-$AREA" "$TMP" \
  --add-dir ${(z)SOURCE_DIRS} \
  --allowedTools "${ALLOWED[@]}"
