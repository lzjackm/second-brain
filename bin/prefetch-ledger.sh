#!/bin/zsh
# Snapshot the decision-ledger repo (config/brain.json modules.ledger) for its area's lead, read only: the ledger
# files on origin/main, the newest digest, recent commits and open PRs. Then PRs others opened get a review
# (bin/pr_watch.py), and open-PR rows, the stale-row sweep and digest merge items are refreshed (bin/ledger_freshness.py).
# Usage: bin/prefetch-ledger.sh   (run-lead.sh and pipeline.sh call it for the ledger's area)
set -euo pipefail
source "${0:A:h}/_env.zsh"
ROOT="${0:A:h:h}"
PY=/opt/homebrew/bin/python3
{ IFS= read -r -d $'\0' REPO; IFS= read -r -d $'\0' SLUG; IFS= read -r -d $'\0' AREA; } < <($PY -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import identity as i; sys.stdout.write("\0".join([i.LEDGER_PATH, i.LEDGER_REPO, i.LEDGER_AREA]) + "\0")' "$ROOT/bin")
[[ -n "$REPO" ]] || { echo "no ledger configured"; exit 0; }
REPO=${~REPO}
OUT="$ROOT/state/snapshots/$AREA"
rm -rf "$OUT"; mkdir -p "$OUT/digests"
git -C "$REPO" fetch -q origin
for f in DECISIONS.md OPEN-ITEMS.md ACTIONS.md README.md; do
  git -C "$REPO" show "origin/main:$f" > "$OUT/$f" 2>/dev/null || true
done
latest=$(git -C "$REPO" ls-tree --name-only origin/main digests/ 2>/dev/null | sort | tail -1)
[[ -n "$latest" ]] && git -C "$REPO" show "origin/main:$latest" > "$OUT/digests/${latest:t}"
git -C "$REPO" log origin/main --since="3 days ago" --pretty='%h %ad %s' --date=short > "$OUT/recent-commits.txt"
gh pr list -R "$SLUG" --state open \
  --json number,title,author,createdAt,updatedAt,url,isDraft,reviewDecision,mergeStateStatus,body,headRefOid,headRefName > "$OUT/open-prs.json"
$PY -I "$ROOT/bin/pr_watch.py" || echo "pr_watch failed" >&2
$PY -I "$ROOT/bin/ledger_freshness.py" || echo "ledger_freshness failed" >&2
