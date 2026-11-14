---
description: Pull the latest template release into this brain without touching the owner's brain, config or data.
---

Update this repo from the upstream template. Read `AGENTS.md` first. Nothing from upstream runs until the owner has seen the code changes and said yes: the brain's scripts read Slack, Drive and your repos, so new code gets the same access.

1. Make sure `git status` is clean for template files (anything outside `brain/`, `leads/`, `config/brain.json` and the data folders). If template files were edited locally, list them and ask before continuing: an update replaces them.
2. If there is no `upstream` remote, ask the user for the template repo URL and add it: `git remote add upstream <url>`.
3. `git fetch upstream --tags`. Update only to a release tag (`v*`), never to an untagged commit: pick the newest tag and say which.
4. Show what the release changes, before merging:
   - the `CHANGELOG.md` entries since the current version, in plain words;
   - `git diff --stat HEAD <tag>`, then the full diff of anything under `bin/`, `app/`, `prompts/`, `launchd/`, `.claude/` and `config/` (these run with your access). Point out anything that sends, fetches from the network, reads outside this folder, adds a hook or `.claude/settings*.json`, or changes `bin/tool_guard.py`, `bin/press.py`, `bin/execute.py` or `bin/sandbox.sh`.
   - Ask the owner to approve. Stop if they don't.
5. `git merge --no-edit <tag>`. The owner's files are gitignored, so they are never part of the merge. Resolve conflicts in favour of upstream for template files; if a conflict is in a file the user changed on purpose, show both versions and ask.
6. Run `bin/test.sh`. If it fails, stop and show the failure.
7. If anything under `launchd/` changed, tell the user to re-run `bin/install-schedules.sh` themselves. Restart the app: `launchctl kickstart -k gui/$UID/com.secondbrain.app`.
8. If the changelog mentions new brain rules or config keys, offer to add them to `brain/` or `config/brain.json` (the template ships them in `brain.example/` and the default config).

End with one line: the version now running and the headline changes.
