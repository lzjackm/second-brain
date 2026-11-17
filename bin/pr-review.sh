#!/bin/zsh
# Review one decision-ledger PR (modules.ledger) opened by someone other than the owner, then queue the owner's approval to-do.
# Safety: the PR's files are read as data only. Nothing from the PR branch is executed: the ledger check is the
# brain's own copy (bin/ledger_check.py) pointed at the PR's files. The PR is exported with `git archive`
# into a scratch folder, so no worktree or checkout of the owner's repo changes. Nothing is posted to GitHub here.
# Usage: bin/pr-review.sh <number> [head-sha]
set -euo pipefail
source "${0:A:h}/_env.zsh"
ROOT="${0:A:h:h}"; N="$1"; HEAD="${2:-}"; PY=/opt/homebrew/bin/python3
{ IFS= read -r -d $'\0' REPO; IFS= read -r -d $'\0' SLUG; IFS= read -r -d $'\0' AREA; } < <($PY -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import identity as i; sys.stdout.write("\0".join([i.LEDGER_PATH, i.LEDGER_REPO, i.LEDGER_AREA]) + "\0")' "$ROOT/bin")
REPO=${~REPO}
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
[[ "$N" =~ ^[0-9]+$ ]] || exit 1
PRDIR="$ROOT/state/pr/$N"; OUT="$ROOT/state/pr/$N-review"
rm -rf "$PRDIR" "$OUT"; mkdir -p "$PRDIR" "$OUT"
git -C "$REPO" fetch -q origin "pull/${N}/head:refs/remotes/pr/${N}" main
git -C "$REPO" archive "refs/remotes/pr/$N" | tar -x -C "$PRDIR"
gh pr view "$N" -R "$SLUG" \
  --json number,title,author,url,body,files,commits,headRefOid,baseRefName,mergeStateStatus,reviewDecision > "$OUT/pr.json"
gh pr diff "$N" -R "$SLUG" > "$OUT/diff.patch" || true
# The check needs git history for "changed since main": a throwaway repo holding main and the PR head, no hooks.
CHK="$OUT/check-repo"; git -c core.hooksPath=/dev/null clone -q --no-checkout --shared "$REPO" "$CHK"
git -C "$CHK" fetch -q "$REPO" "refs/remotes/pr/${N}:refs/heads/pr" "refs/remotes/origin/main:refs/remotes/origin/main"
git -C "$CHK" -c core.hooksPath=/dev/null checkout -q pr
$PY -I "$ROOT/bin/ledger_check.py" --root "$CHK" --base origin/main > "$OUT/check.txt" 2>&1 || true
rm -rf "$CHK"
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')
TMP="$ROOT/state/prompt-pr-review-$N.md"
sed -e "s|{{NOW}}|$NOW|g" -e "s|{{N}}|$N|g" -e "s|{{AREA}}|$AREA|g" -e "s|{{PRDIR}}|$PRDIR|g" -e "s|{{OUT}}|$OUT|g" "$ROOT/prompts/pr-review.md" > "$TMP"
"$ROOT/bin/_claude.sh" "pr-review-$N" "$TMP" \
  --allowedTools "Read" "Glob" "Grep" "Edit($R/queue/items/**)" \
    ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"} \
  --disallowedTools "Bash" "Agent" || true
# Mark this head reviewed only once the to-do exists, so a failed run is retried on the next pass.
if [[ -f "$ROOT/queue/items/$AREA-pr-$N.json" ]]; then
  $PY -I -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1]); d=json.loads(p.read_text()) if p.exists() else {}; d[sys.argv[2]]=sys.argv[3]; p.write_text(json.dumps(d, indent=1))' \
    "$ROOT/state/pr-reviews.json" "$N" "$HEAD"
fi
