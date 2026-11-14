Route each signal to exactly one handler. Output only JSON: {"routes": [{"id": "sig-NN", "to": "<handler>", "confidence": 0.0-1.0}]}

Handlers:
- reply: someone asked {{OWNER_FIRST}} something or needs his response in a thread or DM
- decision: a decision was made or is needed (by {{OWNER_FIRST}} or others) that belongs in the ledger
- review: a PR, doc, deck or sheet waits on {{OWNER_FIRST}}'s review or approval
- update: it is about an existing queue item (signal has `related`), or {{OWNER_FIRST}} already answered something
- synopsis: worth knowing, no action for {{OWNER_FIRST}}

Signals:
{{SIGNALS}}
