#!/usr/bin/env python3
"""Item checks: invariants every queue item must meet, enforced in code rather than trusted to a prompt.

Each check comes from a miss the owner flagged (docs/incidents.md names the incident). The app runs them on every
read (`/api/items` carries `checks`) and refuses to act on a step with a blocking failure unless the owner overrides.
`python3 bin/checks.py` lists failures across the queue; tests/test_checks.py pins each one to its incident.

Checks
- K1 proposal_as_fact (block): a ledger step records a decision as Locked without `grounds` quoting a real source,
  or its grounds are the brain's own unsent draft.
- K2 unread_reply (block): one of the owner's steps follows his work done elsewhere that nobody has read yet.
  (The app also holds the item in In progress; see compute_status.)
- K3 reconciled_blind (block): work done elsewhere marked reconciled with no link to what the owner actually did,
  and a later step builds on it as Locked.
- K4 no_why_owner (warn): an open the owner step on an item that does not say why it is his.
- K5 no_source (warn): no evidence at all.
- K6 assumed (warn): the owner's current step was drafted on assumptions (basis.assumed).
- K7 placeholder (warn): a send-ready draft still has a blank or placeholder ([names], <link>).
- K8 locked_on_target (warn): a Locked ledger row whose own text is a target, proposal or hedge.
- K9 channel_ask (warn): why_owner rests on a channel ask or on owning the area, with no direct ask to the owner.
- K10 docs_only_claim (warn, architect): a shareable claim about the product sourced only from public docs or Slack,
  with no ADR, spec or code (`architect_claims`).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import is_owner  # noqa: E402
import identity  # noqa: E402
import reply_gate  # noqa: E402  (config/brain.json)
PENDING = {"todo", "queued", "failed"}
SLANG = re.compile(r"\b(gm|gmgm|gn|pls|plz|lmk|ty|tysm|np|imo|ngl|btw|tbh|lol|ser|wagmi|fyi)\b|!{2,}|\b\d{1,2}(st|nd|rd|th)\b", re.I)


def external_copy(step):
    """Text in a draft that reaches people outside the company: the whole draft when `execute.audience` is external,
    else any quoted block of 60+ characters (copy written for someone to forward)."""
    draft = step.get("draft") or ""
    if (step.get("execute") or {}).get("audience") == "external":
        return [draft]
    return [m for m in re.findall(r'["\u201c]([^"\u201d]{60,})["\u201d]', draft)]


def register_problems(text):
    """S18: sentences that start lowercase, and chat shorthand."""
    out = []
    starts = [m.group(1) for m in re.finditer(r"(?:^|[.!?]\s+|\n\s*)([A-Za-z])", text)]
    if any(c.islower() for c in starts):
        out.append("starts a sentence in lowercase")
    m = SLANG.search(text)
    if m:
        out.append(f"uses \"{m.group(0)}\"")
    return out


ASK_SINCE = "2026-11-16T17:00"  # reply steps record their ask from here on (K12)
WHY_OWNER_SINCE = "2026-11-11"  # items created before the why_owner rule existed are not flagged
LOCKED = re.compile(r"\|\s*(Locked|Decided|Final)\s*\|", re.I)
SEND_KINDS = {"slack_send", "slack_draft", "email_draft", "pr_comment", "pr_approve", "pr_request_changes"}
# [text] that is not a markdown link, or <word> that is not a Slack token (<@U..>, <#C..>, <!here>, <https://..|x>)
PLACEHOLDER = re.compile(r"\[[^\]\n]{2,80}\](?!\()|<(?![@#!/]|https?:|mailto:)[A-Za-z][A-Za-z .'\-]{1,40}>")
HEDGE = re.compile(r"\b(target(s|ed)?|aim(s|ing)? to|goal|propos(ed|al|es)|tentative(ly)?|not (a )?confirmed|unconfirmed|expected to|plan(s|ning)? to|TBD|likely|should get)\b", re.I)
CHANNEL_ASK = re.compile(r"\b(asked the (channel|team|group)|in #[\w-]+|channel|product owner|owner of|you own|ledger lists you)\b", re.I)
DIRECT_ASK = re.compile(r"\b(asked you|tagged you|DM(ed)? you|your DM|to you|you said|you told|you agreed|you offered|handed (this|it) to you|named you|mentioned you)\b", re.I)
_SA = (identity.CFG.get("modules") or {}).get("architect") or {}
# Primary sources: decision records, specs, code, and any Solution Architect snapshot marked primary; weak: public
# docs (and snapshots marked derived), chat. modules.architect.primary / derived list snapshot folder names.
_P = "|".join(re.escape(d) + "/(?!docs)" for d in _SA.get("primary") or [])
_D = "|".join(re.escape(d) for d in _SA.get("derived") or [])
PRIMARY = re.compile(r"(adrs?/|\bADR\b|spec|\.(rs|ts|tsx|js|go|py|java|kt|swift|c|cpp|sol|move)\b|/src/" + (f"|{_P}" if _P else "") + ")", re.I)
WEAK = re.compile(r"(docs\.|slack|#[\w-]+|\bthread\b" + (f"|{_D}" if _D else "") + ")", re.I)




def words(s):
    return set(re.findall(r"[a-z0-9]{3,}", (s or "").lower()))


def overlap(a, b):
    wa, wb = words(a), words(b)
    return len(wa & wb) / max(1, min(len(wa), len(wb))) if wa and wb else 0.0


def sent_by_app(step):
    """True only when the executor sent this step's draft, so the draft is exactly what was said.
    Steps the owner did themselves (done_by the owner, or done elsewhere) may differ from the draft."""
    return step.get("status") == "done" and step.get("done_by") == "executor"


def unsent_drafts(steps, upto):
    """Drafts of earlier steps that were never sent as written: done elsewhere, skipped, or still pending."""
    return [s.get("draft") or "" for s in steps[:upto]
            if s.get("draft") and not sent_by_app(s)]


def run(item):
    out = []
    steps = item.get("steps") or []
    pend = [s for s in steps if s.get("status", "todo") in PENDING]
    cur = pend[0] if pend else None

    def fail(code, level, msg, step=None):
        out.append({"code": code, "level": level, "msg": msg, **({"step_id": step["id"]} if step else {})})

    for n, s in enumerate(steps):
        if s.get("status", "todo") not in PENDING:
            continue
        before = steps[:n]
        unread = [b for b in before if b.get("status") == "done_elsewhere" and not b.get("reconciled_at")]
        if is_owner(s.get("owner")) and unread:
            fail("K2", "block", f"Waits on reading what you actually did for \"{unread[0].get('text', '')[:60]}\"", s)
        kind = (s.get("execute") or {}).get("kind")
        if kind in ("ledger_pr", "queue_update") and s.get("conflicts_pending"):
            fail("K11", "block", "Still has facts where your notes and the meeting notes disagree; settle them first", s)
        if kind == "ledger_pr" and LOCKED.search(s.get("draft") or ""):
            grounds = [g for g in s.get("grounds") or [] if g.get("url") and g.get("said")]
            if not grounds:
                fail("K1", "block", "Logs a decision as Locked without quoting the message that settled it", s)
            elif any(overlap(g["said"], d) >= 0.8 for g in grounds for d in unsent_drafts(steps, n)):
                fail("K1", "block", "Its source is the brain's own draft, not what was actually said", s)
            blind = [b for b in before if b.get("status") == "done_elsewhere" and b.get("reconciled_at")
                     and not any(e.get("url") for e in b.get("evidence") or [])]
            if blind:
                fail("K3", "block", "Builds on work done elsewhere that was never found in the sources", s)
    if cur and is_owner(cur.get("owner")):
        if not item.get("why_owner") and (item.get("created") or "") >= WHY_OWNER_SINCE:
            fail("K4", "warn", "Doesn't say why this is yours", cur)
        basis = cur.get("basis")
        assumed = (basis.get("assumed") or []) if isinstance(basis, dict) else []
        if assumed:
            fail("K6", "warn", "Drafted on assumptions: " + "; ".join(map(str, assumed))[:160], cur)
    for s in pend:
        if not is_owner(s.get("owner")):
            continue
        kind = (s.get("execute") or {}).get("kind")
        m = PLACEHOLDER.search(s.get("draft") or "") if kind in SEND_KINDS else None
        if m:
            fail("K7", "warn", f"Draft still has a blank to fill: {m.group(0)[:60]}", s)
        if kind == "ledger_pr":
            hedged = [ln for ln in (s.get("draft") or "").splitlines() if LOCKED.search(ln) and HEDGE.search(ln)]
            if hedged:
                fail("K8", "warn", "Logs as Locked something the row itself calls a target or proposal: \"" + HEDGE.search(hedged[0]).group(0) + "\"", s)
    if cur and is_owner(cur.get("owner")):
        why = item.get("why_owner") or ""
        if CHANNEL_ASK.search(why) and not DIRECT_ASK.search(why):
            fail("K9", "warn", "Nobody asked you directly: it rests on a channel ask or on owning the area", cur)
    if cur and is_owner(cur.get("owner")) and (cur.get("execute") or {}).get("kind") in ("slack_send", "slack_draft") \
            and (item.get("created") or "") >= ASK_SINCE:
        ask = cur.get("ask")
        if not isinstance(ask, dict):
            fail("K12", "warn", "Doesn't record the ask it answers (who, when, whether you were named, who answered since)", cur)
        elif reply_gate.verdict(ask):
            fail("K12", "block", "Not yours to answer: " + reply_gate.verdict(ask), cur)
    for s in pend:
        if is_owner(s.get("owner")) and (s.get("execute") or {}).get("kind") in SEND_KINDS:
            probs = [p for t in external_copy(s) for p in register_problems(t)]
            if probs:
                fail("K13", "block", "External copy reads like a chat: " + ", ".join(dict.fromkeys(probs)) + " (S18)", s)
    ev = [e for e in (item.get("evidence") or []) + [e for s in steps for e in s.get("evidence") or []] if e]
    if not ev and item.get("status") in ("open", "waiting"):
        fail("K5", "warn", "No source recorded")
    return out


def architect_claims(claims):
    """K10: shareable claims whose every source is public docs or Slack, with no ADR, spec or code."""
    out = []
    for c in claims or []:
        if not c.get("shareable"):
            continue
        refs = [f"{x.get('label', '')} {x.get('ref', '')}" for x in c.get("sources") or []]
        if refs and not any(PRIMARY.search(r) for r in refs) and all(WEAK.search(r) for r in refs):
            out.append({"code": "K10", "level": "warn", "claim": c.get("id"),
                        "msg": f"{c.get('id')}: sourced only from docs or Slack; confirm against an ADR, spec or code before sharing"})
    return out


def blocking(item, step_id):
    return [c for c in run(item) if c["level"] == "block" and c.get("step_id") == step_id]


if __name__ == "__main__":
    bad = 0
    for f in sorted((ROOT / "queue" / "items").glob("*.json")):
        item = json.loads(f.read_text())
        if item.get("status") in ("done", "dismissed", "stale", "delegated"):
            continue
        for c in run(item):
            bad += c["level"] == "block"
            print(f"{c['level']:5} {c['code']} {item['id']} {c.get('step_id', '')}: {c['msg']}")
    sys.exit(1 if bad and "--strict" in sys.argv else 0)
