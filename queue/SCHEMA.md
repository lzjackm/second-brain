# Queue item schema

One file per item: `queue/items/<id>.json`. An item is a path to done: a short list of steps, each owned by someone. Leads create and update items and steps. The app records the owner's actions on steps and items and computes `status` from the steps. The executor carries out steps the owner told it to do.

```json
{
  "id": "work-20261107-0930-pricing",
  "key": "work:D12:decide",
  "area": "work",
  "type": "decide | approve_send | review | action | idea | brain_rule | meeting",
  "category": "optional: action | decision | reply | review | followup | learning | check | idea | meeting",
  "title": "The ask, under 12 words",
  "context": "One sentence, at most 20 words (S16): what this is and what the owner is deciding",
  "recommendation_short": "the owner's next move, at most 15 words (S16); shown only when the step has no draft",
  "summary": "Why it is here, at most 4 lines (Details view)",
  "recommendation": "What the lead recommends and why, 1 to 3 lines",
  "priority": 86,
  "priority_why": "decide 50 + due in 3 days 15 + blocks release 15 + Sam waiting 6",
  "due": "2026-11-09",
  "evidence": [ { "label": "#product 11-07", "url": "https://..." } ],
  "steps": [
    {
      "id": "s1",
      "text": "Reply to Sam: V1 OK with the two conditions",
      "owner": "me",
      "status": "todo",
      "draft": "Ready-to-send text",
      "execute": { "kind": "slack_send", "target": "<channel id> thread_ts <message ts>" }
    },
    { "id": "s2", "text": "Sam sets a target date for V2", "owner": "Sam Lee", "status": "todo" },
    { "id": "s3", "text": "Log D12 as Locked with the conditions", "owner": "me", "status": "todo",
      "draft": "| D12 | ... |", "execute": { "kind": "ledger_pr", "target": "~/Projects/<ledger repo> DECISIONS.md" } }
  ],
  "status": "open | waiting | working | reconciling | done | snoozed | delegated | dismissed | stale",
  "notes": [ { "ts": "...", "text": "the owner's input", "redraft": false, "action": "note | step_done_elsewhere | ...", "step_id": "s1" } ],
  "redraft_requested": null,
  "redrafted_at": null,
  "reconcile_requested": null,
  "snooze_until": null,
  "delegated_to": null,
  "created": "2026-11-07T09:30:00-05:00",
  "updated": "2026-11-07T09:30:00-05:00",
  "chat": [ { "ts": "...", "role": "<owner_token> | agent", "text": "...", "step_id": "s1", "proposed_draft": "optional", "applied_at": "optional" } ],
  "chat_pending": null,
  "synced_at": "last time the sync pass re-read this item's threads",
  "history": [ { "ts": "...", "by": "lead:work", "event": "created" } ]
}
```

## Why it's the owner's (required on every item with a the owner step)
`why_owner`: one line saying why this is the owner's to do, with the evidence: "Sam asked you in #product", "Jordan tagged you on the contract redline", "You own pricing (D30)". Only these count: the owner is asked or tagged; a reply or action is owed by the owner; or the decision is his by an existing ledger row or brain/knowledge file and nobody else has made it. A decision others already made is not the owner's to-do: log it (a review item with a `ledger_pr` step, when it passes the capture scope) or put it in the synopsis. If you cannot write `why_owner`, do not create the item. Every item also cites its source in `evidence`, with the Slack message link first when there is one.

## Steps

| Field | Meaning |
|---|---|
| `owner` | `me` for the owner's steps; a person's name for steps someone else must do; `lead` for steps a lead completes itself (it marks them done when the source shows it) |
| `status` | `todo`, `queued` (executor will run it), `failed`, `done`, `done_elsewhere` (the owner did it outside the app), `skipped` |
| `draft` | For the owner's steps with an action: ready-to-use text. the owner's edits are logged |
| `execute.kind` | `none` (the owner does it himself; optional `url` and `target_label` show an Open button), `queue_update` (a meeting debrief's JSON list of queue changes, applied by the app in code: `note`, `step_done` on someone else's step, `add_step`, `due`, `create`; all-or-nothing), `slack_send`, `slack_draft`, `gdoc_create`, `gsheet_write`, `calendar_event`, `email_draft`, `pr_merge`, `pr_comment`, `ledger_pr`, `brain_edit`; fields per `brain/mediums.md` |
| `ask` | Owner reply steps only: the message this reply answers, read from the thread to its latest message: `{"from", "at", "link", "names_owner": bool, "after_owner_last": bool, "answered_by": [names]}`. bin/reply_gate.py retires the item when the ask did not name the owner, the owner already replied after it, or someone answered it (P26). |
| `execute.medium_why` | Why this medium, quoting the ask ("Sam: 'one summary memo using the deal memo template'") |
| `elsewhere_note` | the owner's note on where and how he did it. Set with `done_elsewhere` |
| item `evidence` | Only the message(s) that make this an action item now, usually one: the ask, with its link. It is the only source line the owner sees on the item. Research goes in step `evidence` and the report (S16) |
| `reconciled_at`, `evidence` | Set by the lead after it finds what happened (for `done_elsewhere`) or confirms a step done |
| `grounds` | Required on a `ledger_pr` step that records a decision as Locked: `[{"who": "Sam Lee", "said": "exact words that settled it", "url": "message link", "ts": "..."}]`. Quote the real message, never a draft from this item. Without it, or when it matches an unsent draft, the app blocks the step (check K1, `bin/checks.py`) |
| `basis` | Not shown in the app; Ask and the agent chat use it. Object, not a string: `{"read": [...], "not_read": [...], "assumed": [...]}`: sources actually opened, relevant but not opened, and claims with no source. Names, not sentences, under 8 words each; at most 6 read, 3 not read, 3 assumed (S16). Shown in Details; Ask uses it |
| `done_at`, `done_by`, `result`, `error` | Set by the app, executor or lead |
| `revise_requested`, `revisions`, `revised_at` | the owner's Revise: each entry has `ts`, `note` (what is wrong), `draft_before`, and `change` (filled by the reviser). The step stays `todo`; its action is blocked until `revised_at` is newer than `revise_requested` |

## Status (computed by the app, never set by leads except `stale`)

The first step whose status is `todo`, `queued` or `failed` is the current step.

- No current step: `done`, or `reconciling` while any `done_elsewhere` step lacks `reconciled_at`.
- A current step with status `failed` (a blocked agent or a failed send) makes the item `open`, whoever owns it: the owner decides what next.
- `working` (shown as In progress): a redraft is pending (`redraft_requested` newer than `redrafted_at`), the current step has a pending revision, is `queued` for the executor, or is owned by an agent the owner started.
- Current step owned by the owner: `open` (shows in Needs me).
- Current step owned by someone else: `waiting`.
- `snoozed`, `delegated`, `dismissed`, `stale` stick until the owner reopens.

## Rules

- Every item shows a category tag (Action item, Decision, Reply, Review, Follow-up, Learning, Code check, Idea, Meeting). The app derives it: `brain_rule` is Learning, an `idea` titled "Add check" is Code check, an item whose current step is someone else's is Follow-up, otherwise from `type`. Set `category` only to override. The labels live in `CATS` in app/index.html and get refined as the owner asks.

- Never queue something the owner only has to read or acknowledge (a report, a status, a cost summary): it goes on a page (Performance, Synopsis). Queue it only when he must act or decide.
- 2 to 5 steps. Concrete actions, not phases. Include other people's steps the item depends on, so it can wait on them.
- Steps read like quest progression: each one is the next thing that can actually happen, in order. Work the owner does himself (look through a site, review a doc, test, decide) is its own step, `execute` `{"kind": "none", "url": "<the thing to open>", "target_label": "test site"}`, done with one press. A message is its own later step, only when sending it moves the item, and never folded into the work it reports on ("Look through the site" then "Send Jordan the issues", not "Look through the site and flag issues to Jordan"). Don't default to a Slack draft. A step the owner does live (on a call, in a meeting) is a `none` step with no message draft: put the question in the step `text`; at most a one-line talking point in `draft`, which the app shows as a note, not a message.
- A step someone else owns must be something the owner actually needs from them. Never end on a passive step ("Taylor reads the reply and follows up if needed", "Morgan says if he wants feedback"): when nothing more is owed, the item is done. Waiting steps go stale after 3 days, or on `due`, and notify the owner (`bin/stale.py`).
- `due` is the target date for a response when there is one (asked for "by Thursday", a launch date). Stale notifications use it.
- `key` is stable per underlying thing. Update an existing item with the same key instead of creating a new one; append to `history`.
- Never change a step the owner resolved (`done`, `done_elsewhere`, `skipped`). Add new steps after it instead.
- Times are ISO 8601 with the ET offset.
- Meeting items (`type` `meeting`, `area` `meetings`, created from the Meetings page and worked only there: the queue lists and stale alerts skip them) carry `meeting` (event id, title, start, end, attendees). Their agent steps have `meeting_phase` `prep` or `debrief` and run `bin/meeting.sh`; marking the owner's "Run the meeting" step done starts the debrief. The debrief compares the owner's typed notes with Gemini's: facts only in Gemini's are added; conflicts go in a first the owner step with `meeting_phase` `reconcile` and `conflicts` (`n`, `topic`, `yours`, `notes_say`, `notes_url`, `affects`), and the update steps they touch carry `conflicts_pending` (K11 blocks them). the owner's answer on that step ("How do these settle?") starts the reconcile pass, which redrafts the update steps and clears `conflicts_pending`. Revise is not wired for them: edit the draft or use Ask.

