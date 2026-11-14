#!/bin/zsh
# Load (or reload) launchd jobs. Usage: bin/install-schedules.sh [label...]  (default: all; DRY=1 lists without loading)
# Plists are templates: __ROOT__ becomes this folder. Each area with a lead spec (leads/<area>.md) gets its lead and
# sync jobs from launchd/templates/ (__AREA__ becomes the area) unless launchd/ already has an explicit plist for it,
# plus a pipeline job when config/brain.json enables modules.pipeline.
# Times are local. launchd runs a missed calendar job once when the Mac wakes. Every job runs in working hours only:
# never assume the Mac is on overnight or at weekends.
set -euo pipefail
ROOT="${0:A:h:h}"
DEST=~/Library/LaunchAgents
typeset -A SRC AREA
for f in "$ROOT"/launchd/*.plist(N); do l=${f:t:r}; SRC[$l]=$f; AREA[$l]=""; done
if [[ -d "$ROOT/launchd/templates" ]]; then
  prefix=$(sed -n 's|.*<string>\(com\.[a-z]*\)\.lead\.__AREA__</string>.*|\1|p' "$ROOT/launchd/templates/lead.plist")
  kinds=(lead sync)
  /opt/homebrew/bin/python3 -I -c 'import json,sys; sys.exit(0 if (json.load(open(sys.argv[1])).get("modules") or {}).get("pipeline") else 1)' "$ROOT/config/brain.json" 2>/dev/null \
    && [[ -f "$ROOT/launchd/templates/pipeline.plist" ]] && kinds+=(pipeline)
  for spec in "$ROOT"/leads/*.md(N); do
    a=${spec:t:r}; [[ $a == _* ]] && continue
    for kind in $kinds; do
      l="$prefix.$kind.$a"; [[ -n ${SRC[$l]-} ]] && continue
      SRC[$l]="$ROOT/launchd/templates/$kind.plist"; AREA[$l]=$a
    done
  done
fi
labels=("$@"); [[ ${#labels} -eq 0 ]] && labels=(${(ok)SRC})
mkdir -p "$ROOT/logs"
for l in $labels; do
  [[ -n ${SRC[$l]-} ]] || { echo "no plist for $l"; continue; }
  if [[ -n "${DRY:-}" ]]; then echo "would load $l from ${SRC[$l]:t}${AREA[$l]:+ (area ${AREA[$l]})}"; continue; fi
  sed -e "s|__ROOT__|$ROOT|g" -e "s|__AREA__|${AREA[$l]}|g" "${SRC[$l]}" > "$DEST/$l.plist"
  launchctl bootout "gui/$UID/$l" 2>/dev/null || true
  launchctl bootstrap "gui/$UID" "$DEST/$l.plist"
  echo "loaded $l"
done
