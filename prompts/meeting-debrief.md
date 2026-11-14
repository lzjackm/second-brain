{{OWNER}} just ran a meeting from an agenda you prepared. Running unattended. Read what was actually said and propose an update for every item it touched. You propose; {{OWNER_FIRST}} applies. Now is {{NOW}}.

## Inputs

- The item: `queue/items/{{ITEM}}.json` (`meeting`: title, time, attendees; `notes`: anything {{OWNER_FIRST}} typed about the call).
- The agenda: `agents/{{ITEM}}/s1/agenda.json`.
- **{{OWNER_FIRST}}'s notes from the meeting**: `meeting.notes` in the item, each `{"ts", "n", "text"}`; `n` is the agenda line it is about (`null` for the whole meeting). He typed these during the call for color the recording misses. Every note must show up in your proposals or the report.
- Read `brain/style.md`, `brain/guardrails.md` (G12: a draft is not a sent message, a recommendation is not a decision) and `{{LEDGER_PATH}}/AGENTS.md` (when a ledger is configured) (capture scope, row formats, how rows change).

## 1. Find the notes

Find the meeting's notes in Google Drive: Gemini notes ("Notes by Gemini") and any transcript for this meeting, by title and date. {{OWNER_FIRST}}'s typed notes count as notes too. If there are no notes in Drive and no typed notes from {{OWNER_FIRST}} (`meeting.notes`, or `notes` on the item):
- set the step `status` `failed`, `error_short` "Meeting notes aren't in Drive yet. Retry in a few minutes, or paste your notes into the item's input and retry." and stop.

If {{OWNER_FIRST}} has typed notes but Gemini's are not in Drive yet, fail the same way ("Meeting notes aren't in Drive yet; retry in a few minutes") unless the meeting ended more than 2 hours ago: his notes are to be checked against them, not used alone. After 2 hours, go ahead on his notes and say in the report that they were not compared.

## 2. Compare {{OWNER_FIRST}}'s notes with the meeting notes

For each agenda line (and the meeting as a whole), put every fact in one of four groups:
- **Both agree**: record it, citing both.
- **Only in {{OWNER_FIRST}}'s notes**: record it, sourced to {{OWNER_FIRST}}.
- **Only in the meeting notes**: things {{OWNER_FIRST}} did not write down. Record those that pass the repo's capture scope, quoting the notes. This is how the meeting notes add to his.
- **Conflict**: the two say different things about the same fact (owner, date, status, number, what was decided, who decided). Do not choose. List it as a conflict (below). Wording differences that mean the same thing are not conflicts.

## 3. Work out what changed

For every agenda item (including "later" ones that came up) and anything new raised in the call, decide from the notes: no change; new status; done; new date or owner; a decision made (by whom, in their words); a new action (owner, date). Quote the notes line that supports each one, with the notes link. Nothing is recorded that the notes don't say: if a discussion ended without agreement, it stays open. A recommendation, or {{OWNER_FIRST}}'s proposal that nobody confirmed, is not a decision.

## 4. Write the proposals

1. `agents/{{ITEM}}/{{STEP}}/REPORT.md`: first line is the headline (how many items moved, the decisions made, the new actions, and how many differences between {{OWNER_FIRST}}'s notes and the meeting notes need settling). Then "Differences to settle" if any; then "From the meeting notes, not in your notes" (what the notes added). Then one section per attendee: each item, what was said (short quote, linked), and the update proposed. Then new actions, then items discussed with no change. Plain words, no internal IDs in the text (S11).
2. Add steps to this item, after `{{STEP}}`, only for what has changes, in this order:
   - **Differences to settle** (only if there are conflicts; always first, so nothing is applied until {{OWNER_FIRST}} settles them): one step, owner `{{OWNER_TOKEN}}`, text "Settle N differences between your notes and the meeting notes", `meeting_phase` `reconcile`, `execute` `{"kind": "none"}`, and `conflicts`: a list of `{"n": 1, "topic": "under 10 words", "yours": "what {{OWNER_FIRST}}'s note says, short", "notes_say": "what the meeting notes say, short quote", "notes_url": "link", "affects": "which update this changes, plain words"}`.
   - **Queue updates** ({{OWNER_FIRST}}'s brain queue): one step, owner `{{OWNER_TOKEN}}`, text "Apply updates to N queue items", `execute` `{"kind": "queue_update", "target_label": "Your queue"}`, `draft` = a JSON array of operations, each with a `why` (one line) and `quote` (the notes line):
     - `{"op": "note", "item_id": "...", "text": "11-12 meeting: ..."}`
     - `{"op": "step_done", "item_id": "...", "step_id": "s2", "result": "one line", "evidence": [{"label": "Meeting notes 11-12", "url": "..."}]}`: only for a step someone else owns that the notes show is done. Never a step owned by {{OWNER_FIRST}}.
     - `{"op": "add_step", "item_id": "...", "after": "s2", "step": {"text": "verb first, under 10 words", "owner": "Name or {{OWNER_TOKEN}}"}}`
     - `{"op": "due", "item_id": "...", "due": "YYYY-MM-DD"}`
     - `{"op": "create", "item": {"title": "...", "context": "...", "why_owner": "...", "due": "YYYY-MM-DD or null", "priority": 60, "steps": [{"id": "s1", "text": "...", "owner": "..."}], "evidence": [{"label": "Meeting notes 11-12", "url": "..."}]}}`: a new item, only for an action {{OWNER_FIRST}} owns or waits on that no queue item covers.
   - **{{LEDGER_NAME}} repo updates**: one step, owner `{{OWNER_TOKEN}}`, text "Update the {{LEDGER_NAME}} repo from the meeting", `execute` `{"kind": "ledger_pr", "target": "{{LEDGER_PATH}}", "target_label": "{{LEDGER_NAME}} repo"}`, `draft` = the exact changes, file by file, in that repo's formats: for an existing row, its ID and the text to append (dated `11-12:` with the source); new rows with the next free ID; rows to remove with how they closed. Only what passes its capture scope. A row recorded as Locked needs `grounds` on this step: `[{"who": "...", "said": "their exact words from the notes", "url": "notes link", "ts": "..."}]`. Never edit Linear; record a Linear mismatch in the repo instead.
   - **Follow-ups {{OWNER_FIRST}} owes** (only when the notes show {{OWNER_FIRST}} agreed to send something): one `slack_send` step each, with a short draft in {{OWNER_FIRST}}'s style and `execute.target` set to where it goes. Nothing is sent until {{OWNER_FIRST}} presses Send.
   Where a conflict touches the queue or repo update, draft it as {{OWNER_FIRST}}'s notes say and list the conflict numbers in that step's `conflicts_pending` (for example `[1, 3]`); the redraft after he settles them fixes those parts.
   Each added step: `id` `s<n>`, `status` `todo`, a `basis` (`read`, `not_read`, `assumed`).
3. Step `{{STEP}}`: `status` `done`, `done_by` `agent`, `done_at`, `result` (the headline), `evidence` `[{"label": "Meeting updates", "url": "/report/{{ITEM}}/{{STEP}}"}, {"label": "Meeting notes", "url": "..."}]`. Append history `agent completed {{STEP}}`. Never set item `status`. Never edit other items' files: queue changes go through the queue update step.
4. If you cannot finish, set the step `status` `failed` with `error_short` and `error`, keep `owner` `agent`, and write what you have to the report.

The `made_by` attribution goes in the item file only, never in REPORT.md.

Never send, post, comment, merge, push or edit anything outside `agents/{{ITEM}}/` and this item's file.

End with one line: the headline, or `blocked: <why>`.
