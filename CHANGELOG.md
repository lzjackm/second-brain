# Changelog

Releases of the second-brain template. Run `/update-brain` to pull one in.

## v0.5.1 (2026-11-17)

Fresh-install fixes, from the first outside setup.
- **Runs find Claude Code wherever it's installed.** Scheduled runs use a bare PATH that missed `~/.local/bin`, where the native installer puts `claude`, so every run said "Runs are paused" while you were signed in. One shared environment file (`bin/_env.zsh`) now sets PATH for every script.
- **The right alert.** A missing `claude` now says "Claude Code not found", not "signed out".
- **Connector discovery keeps prefixed tools.** Tools named like `slack_read_channel` were all dropped, and a shortened name could be stored. Discovery now takes the real tool names from the connector itself, classifies them in code by their verbs (writes are still refused), and never stores a name the connector doesn't have.
- **`bin/doctor.sh`** checks setup the way the schedules see it (Python, where Claude Code is, sign-in, GitHub CLI, required connectors). `/onboard` runs it in step 1.
- New tests: `tests/test_setup.py`.

## v0.5.0 (2026-11-17)

Fixes found in daily use. Update if you press actions in the app.
- **Quick presses no longer collide.** Pressing several actions within seconds could start two executors whose edits blocked each other; one executor now runs at a time, held by an operating-system lock.
- **PR actions work when the app runs in the background.** Comment, approve, request changes and merge crashed under the background job's minimal PATH and stayed Running. The executor now sets its own PATH, marks a step failed with the reason on any unexpected error, and logs to `logs/execute-<date>.log`.
- **Brain edits report correctly.** A trimmed `git status` line made a successful rule edit read as "not added"; an edit is now judged only by what its own run changed, and one that touches another file is undone.
- **Reply gate.** Every reply step records the ask it answers (who, when, whether you were named, whether it came after your last message, who answered since). `bin/reply_gate.py` retires a reply that stopped being yours, and sync closes instead of redrafting when someone else answered. The reply specialist follows the same rule.
- New tests: `tests/test_executor.py` (brain edits end to end in a scratch repo) and `tests/test_reply_gate.py`.

## v0.4.0 (2026-11-14)

- **Claude is yours.** The brain runs on your own Claude Code sign-in; no key or account detail is ever stored here. The Connectors page shows the account in use, `/onboard` walks through signing in (plan, Console, API key, Bedrock or Vertex in your Claude Code user settings), and runs stop with an alert when you are signed out.
- **Connector settings.** Each connector has a role (Watch: lead runs read it for new work; Lookup: only when an item needs it; Off), what to watch, how often (every lead run or once a day), areas, and whether runs wait for it. Defaults come from its category.
- **Per-connector read windows.** Each watch connector remembers when it was last read in each area; a new one reads back 48 hours on its first run. A window moves on only after the lead run succeeds.
- **Test read.** A dry run over the last 48 hours lists what a connector would bring in, without queuing anything.
- **Is it earning its place?** Items sourced and reads per day over 7 days per connector, and a nudge to switch a quiet watch connector to Lookup.
- Plugins to keep off in runs move to `config/brain.json` (`runs.disabled_plugins`). The privacy gate also blocks credential patterns.

## v0.3.0 (2026-11-14)

Security release. Update before connecting real accounts.
- **Only your press acts.** Each press is recorded outside the repo with a fingerprint of the step's target and draft. The executor is now plain code and runs a step only when a matching press exists; anything else marked queued is refused and comes back to you.
- **Exact sends.** Connector actions (Slack, Docs, Sheets, Calendar) go through one guarded call that receives the pressed arguments directly; the model never sees the draft. The Send button shows the real target, and a first send to a new recipient asks again.
- **Every run is guarded** (`bin/tool_guard.py`): reads and writes by allowlist, no secrets, no network shell commands, short web fetches only, registered connector reads only.
- **Sandboxed Python** (`bin/sandbox.sh`): no network, no home folder outside `~/Projects`, no Keychain. Git runs read-only through `bin/gitread.sh`.
- **App hardening:** a per-launch token, exact origin and JSON on every call; capped bodies; id checks; safe links; generic errors.
- **Private files:** runs, logs and state are written owner-only. `/update-brain` updates only to release tags and shows the code diff for approval before anything runs.
- Security tests in `tests/test_security.py`.

## v0.2.0 (2026-11-13)

- **Connectors page** (Setup, Connectors): every Claude connector by popularity, with search and the selected ones marked. Add finds a connector's read tools (never write tools) and every run gets them; Retry and Remove. Runs read the list from `config/connectors.json`, which starts empty.
- **Meetings module**: week calendar from Google Calendar, agenda prep from attendees' open items, and a debrief that reconciles your notes with the meeting notes.
- **Solution Architect module**: answers a client's question from your specs and docs, searched in the authority order you set (`modules.architect.sources` and `authority`), with a second agent checking every claim. Starter voice and rules in `brain.example/architect*.md`.
- **Decision ledger module**, now complete: the ledger area's lead gets a fresh snapshot each run, open digest PRs and stale rows become review items, and PRs others open on the ledger get a review and an approval to-do.
- **Pipeline module**: a scout plus specialist runs per area as a cheaper alternative to the lead; `"pipeline": true` adds its schedule.
- **Shadow router** and **handover check-ins**, both off until configured.
- `docs/modules.md` covers every module; `/onboard` walks through connectors and modules.

## v0.1.0 (2026-11-13)

First release.
- Queue app: Needs me, In progress, Waiting, Done; one current step per item with its draft, source and Send button; Ask and Agent side panels; ⌘K palette; light and dark themes.
- Runs: lead and sync per area, agents you can talk to, executor (sends only on your press), reviser, daily distill (proposes brain rules), cleanup, ops report, stale alerts, weekly UX review, Learn tutor, daily synopsis.
- Checks in code: drafts recorded as decisions, blanks in send-ready drafts, wordy items and stale titles, Slack table format, connectors missing at run time.
- Onboarding (`/onboard`): name the brain, connect sources, link codebases and channels, create the first area, install schedules.
- Updates (`/update-brain`): pulls a release without touching your brain, config or data.
- Optional decision-ledger module; Meetings, Solution Architect, Pipeline and PR review modules to follow.
