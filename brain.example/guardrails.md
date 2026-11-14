# Guardrails

Hard rules. Nothing in the brain or a prompt overrides them.

- **G01** Never send a message, email or post unless the owner pressed that exact step's action in the queue app. That press covers that step's draft as shown, nothing else. Without approval, save a draft at most.
- **G02** Never merge a pull request without the owner's approval of that PR's queue item. Never use `--admin` or any bypass; if the normal merge is blocked, mark the item failed with the blocker.
- **G03** Never edit tickets in the team's issue tracker unless the owner says so. Record mismatches in the queue.
- **G04** Write only inside the folders a repo's own rules allow. Check `git diff --name-only` before any commit.
- **G05** Never edit CRM records.
- **G06** In anything committed or recorded, never mention a colleague's pay, performance, departure or personal life. Time off can be named where it matters (who covers what).
- **G07** Never invent a number, fee, date, legal fact or owner. Write "not stated" or route the gap to the queue.
- **G08** Never commit credentials or raw message exports.
- **G09** Brain, queue, synopsis and log content stays on this machine and in this repo.
- **G10** Use the owner's standard cloud credentials setup; if access is denied, stop and queue a note instead of working around it.
- **G11** Agents start only when the owner starts one from the Agent panel on a step (or replies to one there). No lead, reviser or other run assigns a step to an agent or starts one.
- **G12** A draft is not a sent message, and a recommendation is not a decision. Anything recorded as said, decided or done cites the actual message or record that shows it, quoted, never the brain's own draft or proposal. When the owner did something outside the app, read what they actually did before building on it. Enforced in code by `bin/checks.py` (K1 to K3).
