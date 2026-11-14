# Modules

Optional features, switched on in `config/brain.json` under `modules`. `config/brain.example.json` has a filled example of each as `<name>_example`: rename the key to switch it on. /onboard asks about each one.

| Module | What it does | Switch on |
|---|---|---|
| Meetings | Week calendar from Google Calendar; agenda prep from attendees' open items; a debrief that reconciles your notes with the meeting notes | `"meetings": true` (needs the Google Calendar connector) |
| Decision ledger | Reads a repo of decision, gap and action tables. Its area's lead gets a fresh snapshot each run; meeting prep pulls each attendee's at-risk rows; PRs others open on it get a review and an approval to-do | `"ledger": {"path", "url", "name", "area"}` |
| Solution Architect | Answers a client's question from your specs, docs and repos, by authority, with a second agent checking every claim | `"architect": {"sources", "authority", "github", "notes", ...}` |
| Pipeline | A scout plus small specialist runs per area, as a cheaper alternative to the full lead. Compare both in Performance before relying on it | `"pipeline": true`, then rerun `bin/install-schedules.sh` |
| Shadow router | Routes each pipeline signal with a second model too and logs both, without acting on it | `config/router.json`: `"shadow": true`, `"decisions_model"`; the AI Gateway key in Keychain under `<slug>-ai-gateway` |
| Handover check-ins | Every few days, a status table of the items someone handed over to you | `config/handover.json`: add `{"from", "key_prefix", "since"}` to `handovers` |

## Solution Architect sources
`bin/prefetch-sa.sh` snapshots each source with `git archive` (read only; nothing is checked out) into `state/snapshots/sa/<dest>/` and writes `MANIFEST.md` with each source's commit and the authority order.

- `sources`: `{"dest": folder, "repo": local clone, "ref": "origin/main", "paths": [...], "dirs_matching": optional regex of extra directories}`.
- `authority`: one line per folder, highest first. The prompt and the claim checker use this order.
- `github`: repos whose PRs and issues count as recent discussion.
- `conflicts_file`: optional file listing known conflicts between sources (path inside the snapshot).
- `notes`: extra rules for the answer: synonyms, wording rules, other repos worth searching.
- `search_dirs`: folders the agent may read beyond the snapshot (default `~/Projects`).

The answer's voice lives in `brain/architect-voice.md`; rules learned from your feedback go in `brain/architect.md`.
