# Agent instructions

Applies to every run in this repo: leads, sync, agents, distill, the executor, and interactive Claude Code sessions.

## Load order

1. `brain/guardrails.md` (hard rules, never overridden)
2. `brain/principles.md`, `brain/style.md`, `brain/priorities.md`, `brain/mediums.md`
3. `brain/areas/<area>.md` for the area in play
4. `leads/<area>.md` when running as a lead

The brain wins over default behavior. A more specific file wins over a more general one, except that guardrails always win.

## Who the owner is

`config/brain.json` names the owner, the brain, the timezone and working hours. Prompts say `{{OWNER}}`, `{{OWNER_FIRST}}` and `{{OWNER_TOKEN}}`; `bin/_claude.sh` fills them in. In queue items, the owner's steps, chat messages and history entries carry `owner_token` (default `me`).

## Boundaries

- This repo is separate from every work repo. Never write brain, queue, synopsis or log content into another repo.
- Leads read sources; they write only under `queue/items/`, `synopsis/` and `state/` here.
- Changes in another repo happen only through the executor, after the owner approves a specific queue item, and follow that repo's own rules.
- The brain changes only through an approved `brain_rule` queue item or an interactive session where the owner asks for the change. Never silently.

## Knowledge and codex

- `brain/knowledge/*.md`: the owner's settled positions by topic, each with `triggers:`. `bin/knowledge.py` adds matching files to every drafting run.
- `learn/codex/<topic>.md`: what the owner has learned in Learn, with their level per subskill. Match their level when a draft touches the topic.

## When the owner flags a miss (incident loop)

Fix it at the level that stops the whole class:
1. **Rule** in `brain/` (a guardrail if it is about truth or safety).
2. **Check** in `bin/checks.py` or an enforcer like `bin/brevity.py` if code can detect it. Prompts drift; checks do not.
3. **Test** in `tests/` that fails if the check stops catching it. Run `bin/test.sh` before every commit.
4. **Log** one row in `docs/incidents.md`.

## Queue item contract

See `queue/SCHEMA.md`. One file per item. Reuse an open item with the same `key` instead of creating a duplicate.

## Your files vs template files

`brain/`, `leads/`, `config/brain.json`, `queue/items/`, `learn/`, `logs/`, `state/` and `agents/` are yours; template updates never touch them. Everything else comes from the template and is replaced by `/update-brain`. Change behavior through your brain and config, not by editing template files, so updates merge cleanly.

## Security model
- **Presses are the only trigger.** The app records each press (bin/press.py, outside the repo); the executor (bin/execute.py, plain code) runs a queued step only when the press matches its target and draft exactly.
- **Every run passes bin/tool_guard.py**: no secret files, no network shell commands, no git config tricks, no web fetches that could carry data out, no connector writes. The executor's single connector call gets the pressed arguments from the guard, never from a model.
- **Python runs in bin/sandbox.sh** (no home folder outside ~/Projects, no Keychain); git runs through bin/gitread.sh (read only).
- **The app** requires a per-launch token, its own origin and JSON on every API call; ids are checked before they become paths.

## Writing
Prose people will read follows `brain/style.md` S19 (no AI-prose tics). Interactive sessions run the `declauding` skill on drafts before handing them over; runs are checked in code by `bin/prose_lint.py` (its linter, vendored in `bin/vendor/`).
