# App design system (Nov 13, 2026 refresh)

The owner asked for an app that looks like a quality web app, not a company brand kit. Sources: Radix Colors, Linear's UI redesign posts, Inter's docs, Primer, Refactoring UI, Emil Kowalski on motion. Tokens live at the top of `app/index.html`; component rules in the "Nov 13 refresh" block.

- **Colour.** Radix Mauve neutrals (slightly warm grey), one Iris accent (#5b5bd6). Raised surfaces are lighter, not shadowed: base #121113 (sidebar, list), reading pane #1a191b, cards #232225, dialogs #2b292d. Borders are white or black at 7/11/17% alpha.
- **Accent only for:** the one primary button per screen, focus rings, unread dots, the selected row's bar, counts that need you, links.
- **Status.** A dot plus grey text. Colour only when it needs attention: amber for due within 2 days, filled amber for due today, filled red for overdue or urgent.
- **Type.** Inter (variable, optical sizing on), cv11 + ss01, tabular numbers on dates and counts. 13/20 base; list titles 13/500; body and chat 14/22; item title 21/28 600; meta 12. Two weights only: 500 and 600.
- **Space.** 4px grid. Sidebar 224, list 372, reading width 720. Rows 9px/16px padding; controls 28 to 32px.
- **Boxes.** Only the current step is a card. Steps, details, meetings and stats are separated by space and hairlines. Done steps fold into one "N done" line.
- **Chat.** Your messages in a bubble; the agent's as plain text; a report is a bordered card; live activity is single grey lines under a left rule.
- **Motion.** Hover 100ms ease-out; drawer 220ms cubic-bezier(.16,1,.3,1); nothing over 300ms; honours reduced motion.
- **Words.** brain/style.md S16 limits apply to every string the app shows.
