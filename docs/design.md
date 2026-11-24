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

## Nov 22 refresh: measured, not guessed

Design systems extracted from the live sites of Linear, Superhuman, Things, Raycast, Arc and Vercel's Geist (`designlang`,
Chrome DevTools, in the sandboxed ux-lab tools), and the same measurements run on this app.

- **Type: seven sizes.** 11, 12, 13, 14, 15 (reading text), 16, 20. The app had drifted to 18 (9 to 28, including 12.5,
  15.5 and 21). Geist uses 7; Linear's app chrome lives at 12 to 14 with medium weight, never bold.
- **Contrast: every visible text passes WCAG AA.** Secondary grey raised: dark `--ink-3` #8f8c97 (5.3:1 on the reading
  pane, was 4.2), light #6f6d79 (5.1:1, was 3.3); light `--ink-2` #56545e keeps the two greys apart; light `--bad`
  #bf2a2f (5.1:1 on its chip). Measured per element in both themes, not per token.
- **Motion: one curve, three durations.** `--out` cubic-bezier(.25,.46,.45,.94) (Linear's ease-out); `--t1` 120ms for
  hover and colour, `--t2` 160ms for overlays, `--t3` 220ms for drawers. Linear answers hover in 100 to 160ms, Geist in
  150 to 200ms; this app animated only backgrounds and snapped every menu and dialog. Now every control eases colour,
  border and shadow; buttons press to 97%; dialogs, the palette and menus rise 4px and fade in. Reduced motion is honoured.
- **List rows: one unit.** Category is a 6px dot before the title (Things, Linear), not a line of text on every row; due
  and status sit on the title line as plain coloured text, right-aligned; the second line is one muted line under the
  title. Colour means something: red only for overdue or your own stale work, amber only for due within 2 days.
  "No reply in Nd" on someone else's step is grey.
- **Still open:** colour sprawl (16 near-duplicate pairs, mostly layered translucent whites) and the spacing scale
  (67/100: stray 9, 11 and 18px paddings) are next.
