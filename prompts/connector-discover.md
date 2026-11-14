List the tools of one connector so the brain can read from it safely. Running unattended.

The connector's tools are named `mcp__{{SERVER}}__<tool>`. Use ToolSearch with the query `+{{SERVER}}` (max_results 50), and again with other words if it may have more, until you have them all. Do not call any of the connector's tools.

Sort each tool:
- **read**: only reads, searches, lists or gets; no side effect anywhere.
- **write**: creates, updates, sends, posts, deletes, uploads, comments, schedules, authenticates, or anything with a side effect. When unsure, it is write.

Reply with only this JSON, tool names without the `mcp__{{SERVER}}__` prefix:
{"read": ["..."], "write": ["..."]}
If no tools of that connector are available (it is not connected), reply {"read": [], "write": [], "error": "not connected"}.
