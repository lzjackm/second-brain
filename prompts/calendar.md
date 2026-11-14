List {{OWNER}}'s meetings for the week of Monday {{MONDAY}} through Sunday {{SUNDAY}} (America/New_York) from his Google Calendar, and save them. Running unattended. Read only: never create, change, accept, decline or delete an event.

1. Use the Google Calendar connector (`list_events`) to list events on his primary calendar from {{MONDAY}} 00:00 to {{SUNDAY}} 23:59 ET, in one call if it fits. Include events he was invited to. Skip events he declined.
2. Write one file per day, all seven, even days with no events: `state/calendar/<YYYY-MM-DD>.json` (overwrite each), the date being the event's start date in ET, with exactly this shape:

```json
{"date": "YYYY-MM-DD", "fetched_at": "{{NOW}}",
 "events": [{"id": "calendar event id", "title": "...", "start": "ISO 8601 with offset", "end": "...", "all_day": false,
   "url": "the event's calendar link (htmlLink)", "conference": "Meet or Zoom link or null", "organizer": "email",
   "description": "the description as written, at most about 2500 characters, or empty",
   "location": "the event's location or room, or null",
   "attachments": [{"title": "file name", "url": "link"}],
   "last_notes": {"title": "...", "url": "...", "date": "YYYY-MM-DD"} or null,
   "attendees": [{"name": "display name or null", "email": "...", "response": "accepted | declined | tentative | needsAction", "self": false, "resource": false}]}]}
```

`last_notes`: for a meeting that has happened before under the same title (a recurring series), the most recent "Notes by Gemini" doc for it in Google Drive (`search_files`, title contains the meeting title and 'Notes by Gemini', newest first), dated before this event; null if none or Drive is not available. `attachments` are the files attached to the event (agenda docs, decks), from the event's attachments field; an empty list when there are none. Mark {{OWNER_FIRST}}'s own attendee entry `"self": true` and meeting rooms `"resource": true`. Keep events in start order. Write valid JSON (escape quotes and newlines in descriptions).

If the calendar connector is not available, write each day's file with `"events": []` and `"error": "Google Calendar is not connected: run /mcp in Claude Code and connect claude.ai Google Calendar"`.

End with one line: how many events you saved across the week, or `blocked: <why>`.
