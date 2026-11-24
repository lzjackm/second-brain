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
# Build the new copy beside the old one and swap it in only when it is whole (Nov 23: runs found DECISIONS.md empty when
# the fetch failed after the old copy was deleted, or a second run deleted it mid-read).
NEW="$OUT.new.$$"; rm -rf "$NEW"; mkdir -p "$NEW/digests" "$NEW/pr-diffs"
trap 'rm -rf "$NEW"' EXIT
if ! git -C "$REPO" fetch -q origin; then
  echo "ledger fetch failed; keeping the last good copy in $OUT" >&2
  exit 0
fi
for f in DECISIONS.md OPEN-ITEMS.md ACTIONS.md README.md; do
  git -C "$REPO" show "origin/main:$f" > "$NEW/$f" 2>/dev/null || true
done
if [[ ! -s "$NEW/DECISIONS.md" ]]; then
  echo "ledger copy came out empty; keeping the last good copy in $OUT" >&2
  exit 0
fi
latest=$(git -C "$REPO" ls-tree --name-only origin/main digests/ 2>/dev/null | sort | tail -1)
[[ -n "$latest" ]] && git -C "$REPO" show "origin/main:$latest" > "$NEW/digests/${latest:t}"
git -C "$REPO" log origin/main --since="3 days ago" --pretty='%h %ad %s' --date=short > "$NEW/recent-commits.txt"
gh pr list -R "$SLUG" --state open \
  --json number,title,author,createdAt,updatedAt,url,isDraft,reviewDecision,mergeStateStatus,body,headRefOid,headRefName > "$NEW/open-prs.json"
# Each open PR's changes to the ledger files, so runs see what is pending without gh (Nov 23: "gh blocked" in runs).
for n in $($PY -I -c 'import json,sys; [print(p["number"]) for p in json.load(open(sys.argv[1]))]' "$NEW/open-prs.json"); do
  gh pr diff "$n" -R "$SLUG" 2>/dev/null | $PY -I -c '
import re, sys
keep, out = False, []
for line in sys.stdin:
    if line.startswith("diff --git"):
        keep = bool(re.search(r" b/(DECISIONS|OPEN-ITEMS|ACTIONS)\.md$|/decisions/", line.strip()))
    if keep:
        out.append(line)
sys.stdout.write("".join(out)[:200000])' > "$NEW/pr-diffs/$n.diff" || true
  [[ -s "$NEW/pr-diffs/$n.diff" ]] || rm -f "$NEW/pr-diffs/$n.diff"
done
rm -rf "$OUT.old"; [[ -d "$OUT" ]] && mv "$OUT" "$OUT.old"; mv "$NEW" "$OUT"; rm -rf "$OUT.old"
trap - EXIT
$PY -I "$ROOT/bin/pr_watch.py" || echo "pr_watch failed" >&2
$PY -I "$ROOT/bin/ledger_freshness.py" || echo "ledger_freshness failed" >&2
