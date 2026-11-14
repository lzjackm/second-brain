#!/bin/zsh
# Merge one approved PR the way GitHub requires for merge queues and stacked PRs: the asynchronous merge API
# (PUT /pulls/{n}/merge-async). It adds the PR to the merge queue when the branch uses one, and for a stacked PR it
# merges the open PRs below it too. Branch rules and checks still apply; nothing is bypassed. The executor runs this
# for a pr_merge step after the owner presses Merge; it can do nothing else.
# Usage: bin/gh_enqueue.sh <pr-url>
set -euo pipefail
URL="$1"
[[ "$URL" =~ ^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([0-9]+)$ ]] || { echo "not a PR url: $URL"; exit 1; }
O="${match[1]}"; R="${match[2]}"; N="${match[3]}"
# The repo's preferred method: squash when allowed (linear-history repos need it), else merge.
M=$(gh api "repos/$O/$R" --jq 'if .allow_squash_merge then "squash" elif .allow_merge_commit then "merge" else "rebase" end')
gh api -X PUT "repos/$O/$R/pulls/$N/merge-async" -f merge_method="$M" --jq '"\(.status): \(.details.message // "")"'
for i in {1..18}; do
  sleep 10
  S=$(gh pr view "$URL" --json state,mergedAt --jq '"\(.state) \(.mergedAt // "")"')
  [[ "$S" == MERGED* ]] && { echo "merged ($M) at ${S#MERGED }"; exit 0; }
done
echo "accepted; not merged after 3 minutes (in a merge queue or waiting on checks): $S"
