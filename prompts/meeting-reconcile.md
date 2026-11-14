{{OWNER}} ran a meeting, and the debrief found places where his notes and the meeting notes (Gemini) disagree. He has now said how each one settles. Running unattended. Redraft the proposed updates from his answer. You propose; {{OWNER_FIRST}} applies. Now is {{NOW}}.

## Inputs

- The item: `queue/items/{{ITEM}}.json`. Step `{{STEP}}` holds `conflicts` (each `n`, `topic`, `yours`, `notes_say`, `notes_url`, `affects`) and `result`: {{OWNER_FIRST}}'s answer. His answer is authoritative.
- The later steps with `revise_requested` newer than `revised_at`: the queue update (`queue_update`, a JSON list of operations) and the {{LEDGER_NAME}} repo update (`ledger_pr`), drafted by the debrief before he answered. Each conflicting fact in them is listed in that step's `conflicts_pending`.
- The debrief report: `agents/{{ITEM}}/<debrief step>/REPORT.md`.
- Read `brain/style.md`, `brain/guardrails.md` (G12) and `{{LEDGER_PATH}}/AGENTS.md` (when a ledger is configured) (row formats, how rows change).

## Do the work

1. For each conflict, apply what {{OWNER_FIRST}} said: his version, the notes' version, or a new fact he gave. If he left one open ("not sure", "check with Sam"), the fact is not recorded as settled: the row stays open or gets an action for that person, never Locked.
2. Rewrite only the parts of each pending step's `draft` that the conflicts touch; keep everything else as it is. Source a fact {{OWNER_FIRST}} settled as "{{OWNER}}, meeting debrief {{NOW}}" plus the notes link. A row recorded as Locked still needs `grounds` with the person's own words from the notes or {{OWNER_FIRST}}'s answer.
3. On each step you redrafted: clear `conflicts_pending`, set `revised_at` to now, and write one line in its latest `revisions` entry's `change` field saying what changed.
4. Add a short "Settled" section to the debrief REPORT.md: each conflict and how it settled.
5. Append history `agent reconciled notes` to the item. Never set item `status`; never change a step {{OWNER_FIRST}} resolved.

Never send, post, comment, merge, push or edit anything outside `agents/{{ITEM}}/` and this item's file.

End with one line: `settled N, redrafted steps S`.
