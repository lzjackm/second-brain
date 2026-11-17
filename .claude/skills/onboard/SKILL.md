---
name: onboard
description: Set up this second brain for its new owner: name it, connect sources, create the first area, start the app. Use when the user wants to set up this brain, start onboarding, or says it's a new install.
---

You are setting up a fresh copy of this repo as the user's second brain. Work through the steps in order, one at a time. Ask short questions, propose sensible defaults, and write files yourself. Never send a message, merge, or edit anything outside this repo. Read `AGENTS.md` and `README.md` first.

## 1. Check the machine and connect Claude
- macOS with Homebrew Python at `/opt/homebrew/bin/python3` (the scripts and schedules use it). If it is missing, tell the user to run `brew install python`.
- **Claude is the brain's engine, and it is the user's own.** Every run calls their Claude Code (`claude -p`), so it uses whatever they are signed in with; this repo never holds a key, token or account detail. Run `claude auth status --text`:
  - Signed in with a paid Claude plan (individual, Team or Enterprise): nothing else to do. Runs count against that plan's usage.
  - Not signed in: tell them to run `claude auth login` in Terminal (it opens a browser) and pick their Claude account, or an Anthropic Console account to pay per use. Check again until it shows signed in.
  - Using an API key, Amazon Bedrock or Google Vertex: that belongs in their Claude Code user settings (`~/.claude/settings.json`, for example `apiKeyHelper` reading the key from Keychain) or their shell environment, never in this repo. Runs read user settings only (`--setting-sources user`).
  - Never write a key into any file here, and never paste one into the chat.
- Tell them what a day costs: the Performance page shows each job's cost; on a plan it counts toward their usage limits.
- Optional: `gh` (GitHub CLI, logged in) for PR features, `terminal-notifier` for notifications.
- Run `bin/doctor.sh`. It checks everything the way scheduled runs see it (launchd's bare PATH, not this Terminal's): Python, where Claude Code is installed, the sign-in, GitHub CLI and required connectors. Fix every FIX line before going on; run it again after connecting connectors in step 4.
- Run `bin/test.sh`. It must pass before going on.

## 2. Name the brain and its owner
Ask for: the brain's name (default "Second Brain"), the owner's full name, the first name the brain should use, their work email(s), GitHub login(s), timezone (IANA, for example `America/New_York`) and working hours (default 9 to 19; every scheduled job stays inside them). Copy `config/brain.example.json` to `config/brain.json` and fill it in (keep the `_doc` line; set `slug` to a lowercase-hyphen version of the brain name; `owner_initials` from the name; keep `owner_token` as `me`; add the full and first name, lowercased, to `owner_aliases`).

## 3. Seed the brain
Copy `brain.example/` to `brain/`. Then interview the user briefly and edit the copies:
- `brain/priorities.md`: their top two or three outcomes this quarter, and what to ignore.
- `brain/guardrails.md`: keep G01 to G12; ask what else must never happen (systems not to touch, people not to contact) and add rules after G12.
- `brain/style.md` and `brain/principles.md`: keep the cited IDs; ask about tone and length preferences and adjust wording, not IDs.
If the user has Claude Code feedback memories (`~/.claude/projects/<home path with dashes>/memory/`), offer to turn the feedback ones into rules, each with its source.

## 4. Connect sources
Start the app (`/opt/homebrew/bin/python3 app/server.py`, or load its schedule in step 7) and open the address it prints (http://127.0.0.1:7878, or the next free port if another brain already uses it; `state/app.port` has it), then the **Connectors** page (Setup, Connectors). The Claude card at the top must say Signed in. Below it, every Claude connector is listed by popularity, with search.
- The brain needs **Slack**, and works best with **Google Drive** (meeting notes), **Google Calendar**, the team's **issue tracker** (Linear or Jira) and **GitHub**. Ask which others they use.
- For each one: if it shows "Not connected", tell the user to connect it at claude.ai (Settings, Connectors) or with `/mcp`, then press Check status. Press **Add**: the brain finds its read tools (never write tools), and its settings open:
  - **Role.** Watch: lead runs read it for new work. Lookup: only when an item or link needs it. Off. Defaults come from its category (messaging, email and trackers watch; design, CRM and docs look up).
  - **What to watch**, in plain words. Channels, folders or teams per area go in that area's lead spec (step 6).
  - **How often** (watch only): every lead run, or once a day. Each read covers everything since that connector was last read; the first goes back 48 hours.
  - **Wait for it** (watch only): runs pause until it connects. Slack at least.
  - **Areas**: which areas' runs read it.
- Press **Run a test read** on each watch connector: it reads the last 48 hours and lists what would become an item, without queuing anything. Adjust what to watch until the list looks right.
- After a week, the page shows each connector's items and reads per day, and suggests Lookup for a watch connector that brought in nothing.

## 5. Link the sources of truth
Ask, and record the answers:
- **Codebases and docs repos** the brain should read: local clone paths go in `config/brain.json` `source_dirs` (clone any that are missing, read only).
- **Slack channels** that matter, per area.
- **Drive folders, trackers and sheets** that hold status (links).
- **Optional modules** (`docs/modules.md`): ask about each and switch on the ones they want, using the `_example` keys in `config/brain.example.json`:
  - **Meetings**, if Google Calendar is connected.
  - **Decision ledger**: a repo where decisions, gaps and actions are tracked as tables.
  - **Solution Architect**, if they answer client or partner questions: which repos hold the specs and docs, in what order of authority, and a few real replies they have sent so `brain/architect-voice.md` can match their voice (copy `brain.example/architect*.md` first; real replies go in `brain/private/`, never committed).
  - **Pipeline**, only after a week of lead runs to compare against.

## 6. Create the first area
An area is one part of their work with its own sources (for example `work`, or one per project). For each area (start with one):
- Copy `brain/areas/_template.md` to `brain/areas/<area>.md` and fill in scope and rules.
- Copy `leads/_template.md` to `leads/<area>.md` and fill in the sources from step 5 and what should become a queue item.
- Set `default_area` in `config/brain.json` to the first area.

## 7. Schedules and the app
- **Sandbox or test copy:** skip this step. Schedules would run leads in the background and spend usage; start the app by hand instead.
- Show the jobs with `DRY=1 bin/install-schedules.sh`: the app, the lead and sync for each area, the daily distill, cleanup, ops report, stale alerts and the weekly UX review.
- The user installs them themselves: tell them to run `bin/install-schedules.sh` (or `! bin/install-schedules.sh` in Claude Code). Do not run it for them.
- Open the app's address once the app job is loaded (`state/app.port` has the port).

## 8. First run
Offer to run one lead pass now: `bin/run-lead.sh <area>`. When it finishes, walk the user through the queue: the Needs me list, a step's draft and its Send button (nothing is sent until they press it), Ask, the Agent panel, and the ⌘K palette. Explain the learning loop: every press, edit and note is logged, and the daily distill proposes brain rules from it for them to approve.

## 9. Updates
Tell the user how to get template updates: `/update-brain`. Their brain, leads, config and data are never touched by an update.

End with a one-line summary of what was set up and what to do next.
