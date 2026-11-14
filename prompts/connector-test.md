You are previewing what {{OWNER_FIRST}}'s brain would pick up from one connector, **{{NAME}}**, before it goes live. Now is {{NOW}}. Nothing you do is saved to the queue: this is a dry run.

1. Read `leads/{{AREA}}.md` (what this area cares about), `brain/priorities.md` and the rules in `queue/SCHEMA.md` on what makes something {{OWNER_FIRST}}'s to do (`why_owner`).
2. Using only the {{NAME}} tools (load them with ToolSearch), read the last 48 hours of what the owner asked to watch there: {{USE}}
3. Decide what would become an action item for {{OWNER_FIRST}} under those rules. Be strict: only real asks, decisions or reviews that are {{OWNER_FIRST}}'s, not FYIs.

End your reply with one fenced block of valid JSON, exactly this shape:
```json
{"read": "one line: what you read (how many messages, docs or issues, from where)",
 "items": [{"title": "the action, under 10 words", "why": "why it is the owner's, one line", "source": "link or plain name"}],
 "noise": "one line: what you saw that would not become an item",
 "suggestion": "one line: keep as watch, switch to lookup, or narrow what to watch (and how)"}
```
At most 5 items. If the connector returns nothing or fails, say so in `read` and leave `items` empty.
