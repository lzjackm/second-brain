# Changelog

Releases of the second-brain template. Run `/update-brain` to pull one in.

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
