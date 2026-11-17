# Second Brain

A personal chief of staff that runs on Claude Code on your Mac. It reads your Slack, meeting notes, issue tracker and repos on a schedule, turns what needs you into a short queue of next steps with drafts ready to send, and learns from every edit you make.

Nothing is sent, merged or posted until you press the button on that exact step.

## What you get

- **A queue app** at http://127.0.0.1:7878: Needs me, In progress, Waiting and Done, each item a short path to done with one current step, a draft and the source it came from.
- **Leads** that scan your sources a few times a working day and create or update items; a **sync** pass every 30 minutes that closes or advances them as threads move.
- **Agents** you start on any step and talk to in a side panel; they research, write a report and draft your next step.
- **A learning loop**: every press, edit, note and vote is logged; the daily distill proposes rules for your brain, and you approve them.
- **Learn** (a tutor that tracks what you know) and a **Synopsis** of each day.
- **Checks in code** for the mistakes that matter (recording a draft as if it were said, blanks in a send-ready draft, wordy items), so rules don't depend on a prompt being followed.

## Start

1. Clone this repo, open it in Claude Code, and run `/onboard`. It names your brain, connects Slack and your other sources, links your codebases and channels, creates your first area, and starts the app.
2. Install the schedules yourself when onboarding shows them: `bin/install-schedules.sh`.

Requirements: macOS, Homebrew Python (`/opt/homebrew/bin/python3`), Claude Code with a Claude plan that covers scheduled runs, and the Slack connector. Recommended: Google Drive and Calendar, Linear or Jira, GitHub (`gh` logged in), `terminal-notifier`.

## How it fits together

| Folder | What it is | Whose |
|---|---|---|
| `app/` | The queue app (one Python server, one HTML page) | Template |
| `bin/` | Runs, checks and housekeeping scripts | Template |
| `prompts/` | What each run is told to do; `{{OWNER}}`-style placeholders are filled from your config | Template |
| `launchd/` | Schedules; per-area lead and sync jobs come from `launchd/templates/` | Template |
| `brain.example/` | Starter rules, copied to `brain/` by onboarding | Template |
| `brain/`, `leads/`, `config/brain.json` | Your rules, your areas' lead specs, your identity and sources | **Yours** |
| `queue/items/`, `logs/`, `state/`, `agents/`, `learn/` | What the brain produces | **Yours** |

Your files are gitignored, so they never leave your machine and updates never touch them.

## Updating

Template releases come out roughly weekly and are listed in `CHANGELOG.md`. Run `/update-brain` in Claude Code to pull one in; it shows what changed, merges it and runs the tests.

## Modules

Optional features live behind `modules` in `config/brain.json`. See `docs/modules.md`.

## Cost

Every scheduled run is a Claude Code session. A typical setup with one area costs a few dollars a working day; the Performance page shows cost per job, and `log/usage.jsonl` has every run. Trim the sync interval or the number of lead runs in your area's lead spec if you need to.

## License

MIT. See `LICENSE`.

## Try it in a sandbox

To walk through setup without touching a brain you already run:

```
git clone https://github.com/<owner>/second-brain ~/second-brain-sandbox
cd ~/second-brain-sandbox && claude
```

Then type `/onboard`. The sandbox keeps its own config, data, presses and port (the app takes the next free one), so nothing it does reaches your other brain. Skip step 7 (schedules) unless you want it running in the background. Delete the folder and `~/Library/Application Support/second-brain` to remove it. It uses your real Claude sign-in and connectors, read only; nothing is sent unless you press Send.
