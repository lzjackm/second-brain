
## This run: editor of the pipeline (overrides steps 2, 6, 7 and 10 above)

The scout already read every source since the last run, and specialists researched and drafted proposals in parallel.
You decide what reaches {{OWNER_FIRST}}'s queue. You are the only run that writes new items; specialists never do.

Inputs, all in this run's folder:
- `state/proposals/{{RUN}}/*.json`: one proposal per file from the reply, decision and review specialists. Each has
  `kind` (`new_item` or `update_item`), the drafted `item` (or `item_id` and `changes`), the `ask` it answers, `why_owner`
  and `sources`. Proposals are drafts from runs that saw one message each: they are often wrong about ownership.
- `state/signals/{{RUN}}.jsonl.routed`: every signal the scout found, with its route (`reply`, `decision`, `review`,
  `update`, `synopsis`, `none`).

Instead of steps 6 and 7:
1. **Judge each proposal against the whole picture**: the thread to its latest message (open the link), the queue, the
   brain. Keep it only when the ask is {{OWNER_FIRST}}'s now (P26: asked or tagged, or the decider by a ledger row; nobody
   else answered; they haven't already replied). Otherwise drop it.
2. **Kept proposals become queue items or edits to existing ones**, per `queue/SCHEMA.md` and step 7's rules. Merge
   proposals and existing items that are about the same thing; never create a duplicate. Record `ask` on every reply step.
   History `by` is `editor:{{AREA}}`.
3. **Signals routed `update`**: apply them to the existing item they concern, as step 3 describes.
4. **Coverage check**: read {{OWNER_FIRST}}'s DMs, group DMs and @mentions since {{PREV_RUN}} (the previous run). Anything that asks something of them and that no signal covers gets handled here, as step 6 and 7
   would, with `"coverage_gap": true` in its history event. (This check runs while the pipeline is measured.)
5. **Log every decision** as one line per proposal in `state/proposals/{{RUN}}/decisions.jsonl`:
   `{"proposal": "<file>", "decision": "kept | merged | dropped", "item": "<item id or null>", "why": "one line"}`.

Do not write `state/{{AREA}}.last_run`: the scout owns it. Steps 1, 3 to 5, 8 and 9 above apply as written; write the
synopsis from the routed signals and the queue.

End with one line: `kept N, merged M, dropped K, updated U, coverage gaps G`.
