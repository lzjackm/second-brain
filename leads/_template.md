# Lead: <Area>

Area rulings: `brain/areas/<area>.md`.

## Cadence

Full lead run at 9:05, 11:05, 1:05, 3:05 and 5:05 PM (owner's timezone). Sync pass (`bin/run-lead.sh <area> sync`) every 30 minutes, 9:20 AM to 6:50 PM: re-reads the threads behind open items and closes, advances or redrafts them. Nothing runs outside working hours.

## Sources (read only)

1. Slack since the last run: DMs and group DMs to the owner, mentions of the owner, and these channels: (#channel-a, #channel-b).
2. Google Drive: "Notes by Gemini" meeting notes modified since the last run.
3. Issue tracker notifications for the owner (read only, G03).
4. Repos in `config/brain.json` `source_dirs` that belong to this area: (paths).
5. Optional: a decision-ledger repo (`modules.ledger`): its open decisions, gaps and actions.

## What becomes an item

| Signal | Type | Typical steps |
|---|---|---|
| A question to the owner that needs a decision | decide | The owner replies with the decision; the asker acts on it |
| A message to the owner that needs a reply | approve_send | The owner replies (`slack_send` with channel and thread_ts) |
| A PR or doc awaiting the owner's review | review | The owner reviews (link, `none`); then merges or comments |
| Work the owner committed to, due within 7 days or overdue | action | The concrete pieces of the work |
| A gap, risk or opportunity nobody has raised | idea | The owner raises it (draft to the right person) |

Everything else that moved goes in the synopsis, not the queue.
