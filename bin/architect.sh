#!/bin/zsh
# Solutions Architect: answer the latest turn of architect/<id>.json, then a skeptic reviews every claim.
# Read only everywhere: snapshots, local repos, Slack, Drive, Linear, GitHub. Nothing is sent or edited.
# Usage: bin/architect.sh <id>
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"; ID="$1"; PY=/opt/homebrew/bin/python3
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
[[ "$ID" =~ ^[a-z0-9-]+$ && -f "$ROOT/architect/$ID.json" ]] || { echo "no question $ID"; exit 1; }
# One lock for the whole run (answer, verify, apply, tightening pass), so the app never sees the gap between the
# answer and verify runs as a dead run and fails the turn (Nov 19: a finished tightening pass was marked failed).
# The tightening pass re-execs with the same pid, which keeps this lock.
RLOCK="$ROOT/state/architect-run-$ID.lock"
if ! mkdir "$RLOCK" 2>/dev/null; then
  P=$(cat "$RLOCK/pid" 2>/dev/null || echo "")
  [[ -n "$P" && "$P" != "$$" ]] && kill -0 "$P" 2>/dev/null && { echo "architect $ID already running"; exit 0; }
fi
echo $$ > "$RLOCK/pid"
trap 'rm -rf "$RLOCK"' EXIT
"$ROOT/bin/prefetch-sa.sh" || true
READ=(
  "Read" "Glob" "Grep" "WebSearch" "WebFetch"
  "Bash(gh pr list:*)" "Bash(gh pr view:*)" "Bash(gh issue list:*)" "Bash(gh issue view:*)" "Bash(gh search:*)"
  "Bash(ls:*)" "Bash(jq:*)"
  ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"}
)
DENY=("Edit" "Write" "NotebookEdit" "Bash(gh pr create:*)" "Bash(gh pr comment:*)" "Bash(gh pr merge:*)" "Bash(gh issue create:*)" "Bash(gh issue comment:*)" "Agent")
DIRS=(${(f)"$($PY -I -c 'import json,os,sys; m=(json.load(open(sys.argv[1])).get("modules") or {}).get("architect") or {}; print("\n".join(os.path.expanduser(d) for d in m.get("search_dirs") or ["~/Projects"]))' "$ROOT/config/brain.json")"})
A="$ROOT/state/prompt-architect-$ID.md"; V="$ROOT/state/prompt-architect-verify-$ID.md"
if [[ -n "${ARCH_ALOG:-}" && -f "$ARCH_ALOG" ]]; then
  ALOG="$ARCH_ALOG"   # resume: check and apply an answer that already ran (ARCH_ALOG=<its log>)
else
  $PY -I "$ROOT/bin/architect.py" prompt "$ID" "$A"
  S=$(date +%s)
  "$ROOT/bin/_claude.sh" "architect-$ID" "$A" --add-dir "${DIRS[@]}" "$HOME/.claude/projects/${HOME//[\/.]/-}/memory" --allowedTools "${READ[@]}" --disallowedTools "${DENY[@]}" || true
  ALOG=$(ls -t "$ROOT"/logs/architect-$ID-*.log 2>/dev/null | grep -v "/architect-verify-" | head -1 || true)
  (( $(stat -f %m "$ALOG" 2>/dev/null || echo 0) >= S )) || ALOG=""
fi
VLOG=""
if [[ -n "$ALOG" ]]; then
  $PY -I "$ROOT/bin/architect.py" verify-prompt "$ID" "$ALOG" "$V"
  if [[ -s "$V" ]]; then
    S2=$(date +%s)
    "$ROOT/bin/_claude.sh" "architect-verify-$ID" "$V" --add-dir "${DIRS[@]}" --allowedTools "${READ[@]}" --disallowedTools "${DENY[@]}" || true
    VLOG=$(ls -t "$ROOT"/logs/architect-verify-$ID-*.log 2>/dev/null | head -1 || true)
    (( $(stat -f %m "$VLOG" 2>/dev/null || echo 0) >= S2 )) || VLOG=""
  fi
fi
OUT=$($PY -I "$ROOT/bin/architect.py" apply "$ID" "$ALOG" "$VLOG")
# Over the length limit (V10): one automatic tightening pass, then the owner sees the result.
[[ "$OUT" == *TIGHTEN* && -z "${ARCH_TIGHTENED:-}" ]] && ARCH_TIGHTENED=1 exec "$0" "$ID"   # exec drops the trap; the next run sets it again
true
