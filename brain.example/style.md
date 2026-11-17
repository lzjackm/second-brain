# Style

How everything the owner reads is written. Prompts cite S10 to S13, S16 and S17.

- **S01** Plain words. No jargon the reader would have to look up.
- **S10** Queue items lead with the ask. The title is the decision or action in under 12 words, and names only the work still open: when a step finishes, retitle the item and update its context and recommendation.
- **S11** Drafts going to people use plain words, never shorthand from working files: no internal IDs, step ids or tags.
- **S12** Shortest clear wording, everywhere. Say it once, in the fewest plain words that keep the meaning. Chat answers: one or two sentences unless the owner asks for detail; lead with yes, no or the answer.
- **S13** Every step says exactly what happens when the owner presses it and what does not ("Creates the doc. Nothing is sent."), and what comes next.
- **S14** A draft the owner can send never contains blanks or placeholders. If a fact cannot be found, leave that point out and say so.
- **S15** A draft answers what was asked and commits the owner to nothing they have not offered.
- **S16** Hard length limits for everything shown in the app. Say each thing once; the app already shows the title, sources, steps and draft.
  - `context`: one sentence, at most 20 words.
  - `recommendation_short` and `recommendation`: the owner's next move, at most 15 words; never the content of the answer.
  - Item `evidence`: only the message(s) that make this an action item now, usually one. Research goes in the step's evidence and the report.
  - `why_owner`: at most 12 words. Step `text`: under 10 words, verb first.
  - A message draft: the shortest message that answers the ask. At most 5 lines; a number range is one line.
  - Numbers across scenarios: one line saying what they are, the table, and the supporting data in a file.
  - `basis`: names, not sentences, each under 8 words; at most 6 read, 3 not read, 3 assumed.
  - Reports: first line is the answer; then at most 10 lines before the detail sections.
  - Chat and agent answers: the answer in one or two sentences first; bullets only for real lists.
- **S17** Tables in Slack: sent by the app, a markdown pipe table alone in its own message; copied for the owner to paste, tab-separated values pasted as their own message. Never a code block or spaces for alignment.
- **S18** Register follows the audience. Internal DMs and team chats can match the owner's own casual voice. Anything that reaches people outside the company (partners, clients, investors, and copy written for a colleague to forward to them) is written like a company announcement: sentence case, full punctuation, no "gm", slang or chat shorthand (pls, lmk, ty, np), dates as "Nov 23", not "23rd". Set `execute.audience` to `external` on such steps; a quoted block inside an internal message counts as external copy. Enforced by bin/checks.py (K13). *Source: the template's starting rules.*
