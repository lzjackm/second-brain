# Context budget

How much each agent run is given, and why. Goal: every run gets enough to do its job well and nothing it doesn't use. Measured, not guessed.

## What a run costs

Every turn re-sends the whole context, so a run's cost is roughly (startup context + material read) x turns. Measured (tokens per turn, Haiku, trivial prompt):

| Startup setup | Tokens |
|---|---|
| Default (skills list, all built-in tool definitions, connectors) | 24,711 |
| Skills off (`--disable-slash-commands`) | 21,355 |
| Built-in tools restricted (`--tools ...`) AND connectors off (`--strict-mcp-config`) | about 7,000 |

**Trap:** the claude.ai connectors connect a few seconds after a run starts. Normally ToolSearch defers their tool definitions. Restricting `--tools` removes ToolSearch, so every connector's tools then load in full on every turn: about 20k extra per turn on Haiku, about 185k on Opus. A one-turn test ends before the connectors arrive and hides this. Rule: restricted tools always go with `--strict-mcp-config`; `_claude.sh` enforces it. Measured on the synopsis: $3.54 restricted alone, $0.05 with both.

Material on disk (tokens): ledger DECISIONS 20k, OPEN-ITEMS 9k, ACTIONS 4k, README 2.5k; all queue items 28k; brain files 0.2k to 1.3k each.

First pipeline run: scout $0.72, director $0.003, decision specialist $0.63, sync $1.01, synopsis $0.67. Total $3.03.

## Principles

1. **Memory lives in files, not in prompts.** Items carry their own state (steps, sources, history, notes, Ask threads); the ledger repo is the record of decisions; the brain holds rules. A run reads the slice its job needs.
2. **Prepare in code what code can prepare.** Ledger rows, related items and the rule pack are picked by a script before the agent starts, so the agent spends no turns finding them.
3. **Pay the startup cost once per job, at its smallest.** Skills off for every run. Jobs that need no connectors run with built-in tools restricted (6.5k instead of 25k per turn).
4. **Fewer turns.** A complete brief means fewer reads, and fewer reads means fewer turns, each of which re-sends everything.
5. **Measure per unit of work.** Compare cost per signal or per item handled and quality per job, not cost per run, since runs see different volumes.

## Design

### 1. Run setup per job (`config/context.json`)
For each job: which brain files it reads, which core rules are pinned into its brief, and whether it needs connectors.
- No connectors (built-in tools restricted): director, synopsis, distill.
- Connectors needed: lead, scout, sync, specialists, revise, chat, agent, execute.
- Skills off for all.

### 2. Briefs for specialists (`bin/brief.py`)
Built before each specialist run into `state/briefs/<run>-<specialist>.md`:
- **The signals** routed to it, in full.
- **Related items, in full**: items named in a signal's `related`, plus items whose key or title shares a ledger ID or two or more distinctive words with the signal.
- **Index of all open items**, one line each (key, title, current step), so it can spot duplicates without reading 28k of JSON.
- **Ledger slice**: every row whose ID is mentioned in a signal or related item, plus the top keyword-matching rows (up to 15), with a pointer to the full snapshot for anything else.
- **Rule pack**: the brain files listed for that job, plus pinned core rules (P01 latest dated wins, P03 verify numbers, P21 verify corrections, G01 to G09).

The prompt tells it the brief is normally enough, to use `Grep` on the full snapshot (returns only matching lines) when unsure, and to record what it opened in `basis.read` and what it could not open in `basis.not_read`.

### 3. Measurement
- `_claude.sh` logs per run: tokens across turns, turns, cost, model, and `units` (signals or items handled) when the caller provides them.
- The Jobs table adds cost per unit and turns per run next to quality.
- `basis.not_read` entries that repeat across items show where sources are out of reach; distill turns them into Fix items.

### 4. Experiment scope
- **Universal levers (skills off, restricted tools for no-connector jobs) apply to every job, lead included**, so they don't confound lead vs pipeline.
- **Briefs apply only to pipeline specialists.** Lead vs pipeline then compares the architecture, with briefs counted as part of it.
- **Model changes happen one job at a time, only where quality is measurable.** The synopsis has no quality signal, so its model does not change until it has one.

## Adversarial review

| Attack | Risk | Answer in the design |
|---|---|---|
| The ledger slice misses the row that matters (different wording, no shared ID) | Decision logged twice, or contradicting a Locked row | Decision specialist must `Grep` the full snapshot for the decision's subject before logging; Grep returns lines, not the 20k file. Brief carries all IDs mentioned anywhere in the signal chain |
| The scout's `related` is wrong or empty | Duplicate items | Index of all open items in every brief; key-based dedupe rule unchanged; the director's rule route to update only fires when `related` is set |
| Dropping principles.md from reply drafts loses "latest dated statement wins" | Stale or wrong drafts | Core rules (P01, P03, P21, guardrails) are pinned into every brief by ID, regardless of job pack |
| Restricted tools silently remove something a job needs, or quietly make it more expensive | Job fails, degrades, or costs more | Only applied to jobs that read files alone, always paired with `--strict-mcp-config`; every run's trace records tool calls and per-turn context; Jobs table shows cost and quality; first run per job checked by hand. (This attack happened: restricted tools without strict cost 70x more on the synopsis until caught by the trace.) |
| Specialist ignores the brief and reads everything anyway | No savings | Tokens and turns logged per run; a regression shows in cost per unit |
| Lead vs pipeline compared on runs that see different volumes | False conclusion | Compare cost per unit and quality, over several days, not single runs |
| Optimizing only the pipeline confounds the comparison | Can't tell architecture from context tricks | Universal levers apply to both; only briefs are pipeline-specific, and are part of what is being tested |
| A cheaper model on a job without a quality signal | Silent quality loss | No model change without a measurable quality signal for that job |
| Brief content from Slack carries injected instructions | Agent misled | Same exposure as today (agents already read Slack); briefs label signal text as data; guardrails unchanged; no new write paths |
| Brief too big for big runs (many signals) | Context bloat returns | Brief capped (signals in full, related items capped at 8 full, ledger slice capped at 15 rows); anything else by pointer |
| Turning skills off removes a skill a job relies on | Breakage | No job prompt uses skills; Figma and others are connector tools, not skills; verified by the first runs |
