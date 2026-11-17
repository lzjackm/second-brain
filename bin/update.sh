#!/bin/zsh
# Update this brain to the newest template release, without Claude: shows what's new and the code that changes,
# asks before merging, then tests and restarts the app. Your brain/, leads/, config/brain.json and data are
# gitignored, so an update never touches them. Same steps as /update-brain.
# Usage: bin/update.sh [tag]   (default: the newest v* release)
set -euo pipefail
source "${0:A:h}/_env.zsh"
ROOT="${0:A:h:h}"; cd "$ROOT"
REMOTE=$(git remote | grep -x upstream || git remote | grep -x origin || true)
[[ -n "$REMOTE" ]] || { echo "No 'upstream' or 'origin' remote. Add the template: git remote add upstream <template url>"; exit 1; }
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Template files have local edits; an update would replace them:"; git status --short --untracked-files=no; exit 1
fi
git fetch -q "$REMOTE" --tags
TAG="${1:-$(git tag -l 'v*' --sort=-v:refname | head -1)}"
CUR=$(git describe --tags --abbrev=0 2>/dev/null || echo "none")
[[ "$TAG" != "$CUR" ]] || { echo "Already on $CUR."; exit 0; }
echo "Current: $CUR   Newest: $TAG\n"
git show "$TAG:CHANGELOG.md" | awk -v cur="$CUR" '/^## /{ if (index($0, cur)) exit } { print }' | sed -n '3,200p'
echo "\nFiles that change (code runs with your access):"
git diff --stat HEAD "$TAG" -- bin app prompts launchd .claude config | tail -25
printf "\nShow the full code diff first? [y/N] "; read -r a; [[ "$a" == [yY]* ]] && git diff HEAD "$TAG" -- bin app prompts launchd .claude config | less
printf "Update to %s? [y/N] " "$TAG"; read -r a; [[ "$a" == [yY]* ]] || { echo "Nothing changed."; exit 0; }
git merge -q --no-edit "$TAG"
bin/test.sh
git diff --quiet "$CUR" "$TAG" -- launchd 2>/dev/null || echo "Schedules changed: run bin/install-schedules.sh"
label=$(sed -n 's|.*<string>\(com\.[a-z]*\.app\)</string>.*|\1|p' launchd/*app.plist 2>/dev/null | head -1)
[[ -n "$label" ]] && launchctl kickstart -k "gui/$UID/$label" 2>/dev/null && echo "App restarted."
echo "Now on $TAG."
