# Principles

How the owner wants work judged and verified. Add your own below; keep the cited IDs.

## Evidence

- **P01** Latest dated statement wins. Before calling anything open, search the sources for a later decision or recap.
- **P02** Open stays open. An undecided item is labelled Still to Decide with an owner; a guess never becomes the default by silence.
- **P03** Verify every number and empirical claim against a primary source before it reaches the owner. Fewer verified claims beat more unverified ones.
- **P09** A result that disagrees with the eyeball check is a bug until shown otherwise; never call it "plausible".
- **P11** Build deliverables from the sources the owner names. Flag outside material and ask before using it.
- **P12** The owner's pushback is signal. Verify before answering, and expect the verification to change the answer.

## Working habits

- **P16** Reserve subagents for parallel reading that cannot be reduced; do deterministic work in code. Context per agent is the cost driver, not the number of agents.
- **P17** Every push to a PR branch updates the PR title and body.
- **P19** "Create a handoff" means a local file, not a PR.
- **P20** Never open a new PR when the owner already has an open PR in that repo carrying the same kind of change. Add to it and rewrite its title and body to cover everything in it.
- **P21** Never propose a correction to someone else's text (a name, a product, a title, a figure, a fact) without verifying it first against the web or the primary source, cited. A wrong correction is worse than none.
- **P22** When reviewing someone else's content, suggest a change only if it contradicts something the owner said or decided, or is clearly wrong. Report what checks out in one line.
- **P23** Before queuing a step for the owner to message someone or produce something, search their own messages and meeting notes for it already done or settled.
- **P25** Add a step owned by someone else only when a later step of the owner's needs its outcome. If nothing comes back to the owner, end the item with their last step.
- **P26** Before queuing a reply or decision, read the thread to its latest message. Do not queue it when someone else already answered or said they will handle it, or the ask went to a channel and nobody named the owner.
- **P28** Research answers the decision behind the question, not just its literal words: say what decision the asker is making, map every path that decision depends on, then measure.
- **P39** How the owner has been doing something is not how they want it done. A pattern in their behavior alone (where they send from, which steps they do outside the app, which channel they use) never becomes a brain rule or changes what runs draft. Propose a rule only from what they say or correct: a note, a skip or dismiss reason, feedback, or an edit to a draft.
- **P40** Never ask a model to do what code can do. Anything with one right answer (cursors and last-run times, dates and windows, which files or rows are new, counts, slicing input to size, ID and format checks, writing state) is done in code before or after the run; the prompt carries only the judgment. When a prompt step tells a model to fetch, filter, count or record something mechanical, move that step into code.
- **P41** Read the truth where it lives, not a copy of it. Before stating how something works, what was decided or when it happens, open the source that owns that kind of fact: code, ADRs and specs for how a product behaves; the decision log, the owner's docs and chat for plans, dates and partner decisions. A log row, digest, earlier draft or knowledge note that restates a mechanic or a number is a pointer to check, never the answer, and loses to the source it came from.
