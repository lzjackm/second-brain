#!/bin/zsh
# Pipeline for one area: scout -> director (route) -> specialists (proposals) -> editor (the lead: decides, writes the
# queue and synopsis). Replaces the lead's own source sweep when modules.pipeline is on (bin/run-lead.sh).
# Usage: bin/pipeline.sh <area>
set -euo pipefail
ROOT="${0:A:h:h}"
AREA="$1"
cd "$ROOT"
source "${0:A:h}/_env.zsh"
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
take_run_lock
mkdir "state/pipeline-$AREA.lock" 2>/dev/null || { echo "pipeline already running"; exit 0; }
trap 'rmdir "state/pipeline-$AREA.lock"; rm -rf "state/run-$AREA.lock"' EXIT
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')
DATE=$(TZ=America/New_York date +%Y-%m-%d)
RUN="pipe-$AREA-$(TZ=America/New_York date +%Y%m%d-%H%M)"
TITLE="${(C)AREA}"
source "$ROOT/bin/_lead_tools.zsh"
SOURCE_DIRS=$(/opt/homebrew/bin/python3 -I -c 'import json,os,sys; c=json.load(open(sys.argv[1])); print(" ".join(os.path.expanduser(d) for d in c.get("source_dirs") or []) or sys.argv[2])' "$ROOT/config/brain.json" "$ROOT")
render() { sed -e "s|{{AREA}}|$AREA|g" -e "s|{{AREA_TITLE}}|$TITLE|g" -e "s|{{NOW}}|$NOW|g" -e "s|{{DATE}}|$DATE|g" -e "s|{{RUN}}|$RUN|g" "$@"; }

# 1. Scout
bin/prefetch.sh "$AREA" || echo "prefetch failed" >&2
PREV=$(cat "state/$AREA.last_run" 2>/dev/null || echo "24 hours ago")
render prompts/scout.md > "state/prompt-scout-$AREA.md"
/opt/homebrew/bin/python3 -I bin/connectors.py sources "$AREA" lead "$NOW" >> "state/prompt-scout-$AREA.md"   # each connector's window
bin/_claude.sh "scout-$AREA" "state/prompt-scout-$AREA.md" --add-dir ${(z)SOURCE_DIRS} --allowedTools "${ALLOWED[@]}"
SIG="state/signals/$RUN.jsonl"
[[ -s "$SIG" ]] || { echo "no signals"; exit 0; }

# 2. Director: route each signal (slim input: summaries only), then group by handler
python3 -I bin/director.py "$SIG" "$AREA" "$RUN"

# 3. Specialists, one run per handler that has signals, each given only its signals
for SPEC in reply decision review; do
  F="state/signals/$RUN.$SPEC.jsonl"
  [[ -s "$F" ]] || continue
  python3 -I bin/brief.py "$SPEC" "$F" "$AREA" "state/briefs/$RUN-$SPEC.md"
  python3 -I - "$SPEC" "state/briefs/$RUN-$SPEC.md" "$AREA" "$NOW" "$DATE" "$TITLE" "$RUN" > "state/prompt-specialist-$SPEC-$AREA.md" <<'PY'
import json, sys
spec, brief, area, now, date, title, run = sys.argv[1:8]
jobs = json.load(open("config/specialists.json"))
tpl = open("prompts/specialist.md").read()
for k, v in {"{{SPEC}}": spec, "{{JOB}}": jobs[spec], "{{BRIEF}}": open(brief).read(), "{{AREA}}": area, "{{NOW}}": now, "{{DATE}}": date, "{{AREA_TITLE}}": title, "{{RUN}}": run}.items():
    tpl = tpl.replace(k, v)
print(tpl)
PY
  # Specialists research and propose; only the editor writes the queue. They may write only this run's proposal folder.
  SPEC_ALLOWED=(${ALLOWED:#Edit*} "Write($R/state/proposals/$RUN/**)" "Edit($R/state/proposals/$RUN/**)")
  JB_UNITS=$(wc -l < "$F" | tr -d ' ') bin/_claude.sh "specialist-$SPEC-$AREA" "state/prompt-specialist-$SPEC-$AREA.md" --add-dir ${(z)SOURCE_DIRS} --allowedTools "${SPEC_ALLOWED[@]}"
done

# 4. The editor: the area's lead, with every proposal, the routed signals and the whole queue, decides what reaches the
# owner, applies updates, checks coverage of DMs and mentions, and writes the synopsis (prompts/editor-mode.md).
mkdir -p "state/proposals/$RUN"
PIPE_RUN="$RUN" PIPE_PREV="$PREV" bin/run-lead.sh "$AREA" edit
echo "pipeline $RUN done"
/opt/homebrew/bin/python3 -I bin/dedupe.py "$AREA" || true
