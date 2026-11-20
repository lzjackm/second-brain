#!/usr/bin/env python3
"""Solutions Architect: build prompts and merge the answer with its skeptical review.

Usage: architect.py prompt <id> <out.md>            the answer prompt for the latest turn
       architect.py verify-prompt <id> <log> <out.md> the reviewer's prompt, from the answer run's log
       architect.py apply <id> <answer-log> <verify-log>
A question lives in architect/<id>.json; each follow-up is a new turn with its own answer and review.
"""
import collections
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402
from identity import CFG  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "architect"
ET = ZoneInfo("America/New_York")


def now():
    return datetime.now(ET).isoformat(timespec="seconds")


def load(i):
    return json.loads((DIR / f"{i}.json").read_text())


def save(q):
    q["updated"] = now()
    (DIR / f"{q['id']}.json").write_text(json.dumps(q, indent=2, ensure_ascii=False))


def last_json(text):
    for b in reversed(re.findall(r"```json\s*(\{.*?\})\s*```", text or "", flags=re.S)):
        try:
            return json.loads(b)
        except json.JSONDecodeError:
            continue
    return None


def client_q(q, turn):
    """The client's message a turn answers: a revision answers the same message as the turn it revises."""
    return q["turns"][turn["revises"]]["question"] if turn.get("kind") == "revise" else turn["question"]



def sa_fill(tpl):
    """The Solutions Architect's sources come from modules.architect in config/brain.json."""
    m = (CFG.get("modules") or {}).get("architect") or {}
    auth = m.get("authority") or [f"`{s['dest']}/`" for s in m.get("sources") or []]
    n = len(auth)
    gh = m.get("github") or []
    cf = m.get("conflicts_file")
    return (tpl.replace("{{SA_SOURCES}}", "\n".join(f"{i}. {a}" for i, a in enumerate(auth, 1)))
            .replace("{{SA_NEXT}}", str(n + 1)).replace("{{SA_NEXT1}}", str(n + 2)).replace("{{SA_NEXT2}}", str(n + 3))
            .replace("{{SA_GITHUB}}", (" (" + ", ".join(f"`gh pr list -R {r} --search \"<terms>\" --state all`" for r in gh) + ", `gh issue list`)") if gh else "")
            .replace("{{SA_NOTES}}", "\n".join(f"- {x}" for x in m.get("notes") or []))
            .replace("{{SA_CONFLICTS}}", f"   - Is the topic listed in `{cf}` as a conflict?\n" if cf else ""))


def confidence(final):
    """Confidence from the checker's results, not the model's self-rating (Nov 18: 10 of 14 answers said "medium" with no
    rule behind it). Returns (level, reasons): what keeps it from high, in a few words each.
    high: every claim the answer rests on confirmed against its source and backed by an ADR, spec or code; nothing
          refuted; sources agree; every client question answered.
    low:  a claim it rests on refuted or unsupported, or a client question unanswered.
    medium: the rest (a claim only in docs or Slack, a partial answer, a claim left unchecked). A claim the checker corrected
            counts as confirmed (the answer now carries the corrected text), and logged source disagreements stay in the
            checks section: the answer already follows the higher-authority source."""
    claims = [c for c in final.get("claims") or [] if c.get("shareable") is not False]
    oc = collections.Counter(c.get("outcome") for c in claims)
    qs = final.get("questions") or []
    low, mid = [], []
    if oc["refuted"] or oc["unsupported"]:
        low.append(f"{oc['refuted'] + oc['unsupported']} claim{'s' if oc['refuted'] + oc['unsupported'] > 1 else ''} not backed by a source")
    unans = sum(1 for q in qs if q.get("answered") == "no")
    if unans:
        low.append(f"{unans} question{'s' if unans > 1 else ''} unanswered")
    if not final.get("verified"):
        mid.append("not checked by the reviewer")
    if oc[None] and final.get("verified"):
        mid.append(f"{oc[None]} claim{'s' if oc[None] > 1 else ''} unchecked")
    if final.get("unconfirmed"):
        n = len(final["unconfirmed"])
        mid.append(f"{n} claim{'s' if n > 1 else ''} only in docs or Slack")
    part = sum(1 for q in qs if q.get("answered") == "partly")
    if part:
        mid.append(f"{part} question{'s' if part > 1 else ''} partly answered")
    if not claims:
        mid.append("no sourced claims")
    return ("low", low + mid) if low else ("medium", mid) if mid else ("high", [])


def words(t):
    return len(re.findall(r"\S+", t or ""))


def numbers(text):
    """The question numbers a message uses: "1." or "1)" at the start of a line, and in an answer also "1 and 2.",
    "1/2." or "1-2." (one block answering several)."""
    out = set()
    for m in re.finditer(r"(?m)^\s*(\d{1,2})(?:\s*(?:and|/|-|,|&)\s*(\d{1,2}))*\s*[.)]", text or ""):
        out |= {int(x) for x in re.findall(r"\d{1,2}", m.group(0))}
    return out


def limit(q, turn):
    """Longest the shareable answer may be (V10): about the client's own length, at least 50 words, at most 160 or
    55 words per numbered question, whichever is more. Nov 19: a five-question message got 160 words and lost the
    sources it had found."""
    cq = client_q(q, turn)
    return max(50, min(max(160, 55 * len(numbers(cq))), round(1.2 * words(cq))))


NEG = re.compile(r"\b(no date|has no date|with no date|no timeline|not (?:yet )?(?:published|announced|decided|set|confirmed)|"
                 r"(?:aren't|isn't|is not|are not) (?:yet )?(?:published|announced|decided|set|confirmed)|unconfirmed|not yet on)\b", re.I)


def slack_searched(q, turn):
    """Whether this answer's run (or the run it revises) searched Slack."""
    base = q["turns"][turn["revises"]] if turn.get("kind") == "revise" else turn
    logs = ((base.get("final") or base.get("answer") or {}).get("searched") or []) + ((turn.get("answer") or {}).get("searched") or [])
    return any("slack" in str(x).lower() and "not searched" not in str(x).lower() for x in logs)


def problems(q, turn, final):
    """What code checks before the owner reads an answer, as instructions for the one automatic pass."""
    ans, out = final.get("shareable_answer") or "", []
    want, got = numbers(client_q(q, turn)), numbers(ans)
    if want and (want - got or got - want):
        out.append(f"Number the answer with the client's own question numbers ({', '.join(map(str, sorted(want)))}), one block "
                   "per question, or \"1/2.\" when one block answers both; never renumber by topic.")
    neg = sorted({m.group(0) for m in NEG.finditer(ans)})
    if neg and not slack_searched(q, turn):
        out.append(f"The answer says {', '.join(repr(x) for x in neg)} but Slack was not searched. Search Slack (several "
                   "phrasings, the last 30 days) and the ledger for each before keeping it: dates and plans usually live there. "
                   "Add what you find, with its source, and log the searches in `searched`.")
    return out


def with_limit(tpl, q, turn):
    return tpl.replace("{{SA_LIMIT}}", str(limit(q, turn))) + images_block(q, turn)


def images_block(q, turn):
    """Images pasted with the client's message (and with a change request): part of the question, opened with Read."""
    base = q["turns"][turn["revises"]] if turn.get("kind") == "revise" else turn
    imgs = list(dict.fromkeys((base.get("images") or []) + (turn.get("images") or [])))
    imgs = [n for n in imgs if (ROOT / "architect" / "images" / n).is_file()]
    if not imgs:
        return ""
    return ("\n\n## Images sent with the question\n\nOpen each with Read before answering; they are part of what was asked "
            "(screenshots of errors, UI, docs or data). Quote what they show when an answer depends on it.\n"
            + "\n".join(f"- `architect/images/{n}`" for n in imgs) + "\n")


def prompt(i, out):
    q = load(i)
    turn = q["turns"][-1]
    if turn.get("kind") == "revise":
        base = q["turns"][turn["revises"]].get("final") or {}
        tpl = (ROOT / "prompts" / "architect-revise.md").read_text()
        sys.path.insert(0, str(ROOT / "bin"))
        import knowledge  # noqa: E402
        know = "".join(f"\n\n## The owner's positions: {f.relative_to(ROOT)}\n" + re.sub(r"^---.*?---\n", "", f.read_text(), flags=re.S).strip()
                       for f, _ in knowledge.match(client_q(q, turn) + " " + turn["question"]))
        Path(out).write_text(with_limit(tpl, q, turn).replace("{{NOW}}", now()).replace("{{DATE}}", now()[:10]).replace("{{QUESTION}}", client_q(q, turn))
                             .replace("{{ANSWER}}", json.dumps({k: base.get(k) for k in ("shareable_answer", "internal_notes", "claims", "questions", "conflicts", "gaps")}, indent=1, ensure_ascii=False))
                             .replace("{{FEEDBACK}}", turn["question"]) + know)
        return
    earlier = [f"Q: {t['question']}\nA: {(t.get('final') or {}).get('shareable_answer', '')}" for t in q["turns"][:-1]]
    ctx = (f"Client or context: {q['context']}\n" if q.get("context") else "")
    if earlier:
        ctx += "\nEarlier in this thread (this is a follow-up):\n" + "\n\n".join(earlier) + "\n"
    sys.path.insert(0, str(ROOT / "bin"))
    import knowledge  # noqa: E402
    know = "".join(f"\n\n## The owner's positions: {f.relative_to(ROOT)}\n" + re.sub(r"^---.*?---\n", "", f.read_text(), flags=re.S).strip()
                   for f, _ in knowledge.match(turn["question"] + " " + q.get("context", "")))
    if know:
        ctx += "\nThe owner's positions on this topic (internal; never quote them to the client, but never contradict them):" + know + "\n"
    tpl = sa_fill((ROOT / "prompts" / "architect.md").read_text())
    Path(out).write_text(with_limit(tpl, q, turn).replace("{{NOW}}", now()).replace("{{DEPTH}}", turn["depth"])
                         .replace("{{QUESTION}}", turn["question"]).replace("{{CONTEXT}}", ctx))


def verify_prompt(i, log, out):
    q = load(i)
    ans = last_json(Path(log).read_text() if Path(log).exists() else "")
    if not ans:
        Path(out).write_text("")
        return
    tpl = sa_fill((ROOT / "prompts" / "architect-verify.md").read_text())
    turn = q["turns"][-1]
    if turn.get("kind") == "revise":
        tpl = tpl.replace("## Do this", "## The owner's instructions for this rewrite (authoritative)\n" + turn["question"] +
                          "\n\nHonor them in your final answer and never undo them, including length and format limits. If one conflicts with answering every client question, fit the answers inside his limit (combine points) rather than breaking it.\n\n## Do this", 1)
    import prose_lint  # noqa: E402  (declauding's linter)
    tics = prose_lint.summary(ans.get("shareable_answer") or "", 6)
    if tics:   # fixed here, in the verify run, instead of in an extra pass afterwards (Nov 20: that pass added 4 minutes)
        tpl = tpl.replace("## Do this", f"## Also fix\nRewrite these AI-prose tics in the shareable answer as plain statements (S19): {tics}.\n\n## Do this", 1)
    Path(out).write_text(with_limit(tpl, q, q["turns"][-1]).replace("{{NOW}}", now()).replace("{{QUESTION}}", client_q(q, q["turns"][-1]))
                         .replace("{{ANSWER}}", json.dumps(ans, indent=1, ensure_ascii=False)))


def run_of(log):
    m = re.search(r"/([^/]+)\.log$", log or "")
    return m.group(1) if m else None


def apply(i, alog, vlog):
    q = load(i)
    turn = q["turns"][-1]
    ans = last_json(Path(alog).read_text() if alog and Path(alog).exists() else "")
    ver = last_json(Path(vlog).read_text() if vlog and Path(vlog).exists() else "")
    turn.pop("pending", None)
    if not ans:
        turn["error"] = (Path(alog).read_text()[-600:] if alog and Path(alog).exists() else "") or "The answer run returned nothing."
        save(q)
        return
    turn["answer"] = ans
    turn["made_by"] = {"run": run_of(alog), "job": "architect"}
    final = {"shareable_answer": ans.get("shareable_answer", ""), "confidence": ans.get("confidence"),
             "internal_notes": ans.get("internal_notes", ""), "conflicts": ans.get("conflicts") or [],
             "gaps": ans.get("gaps") or [], "client_questions": ans.get("client_questions") or [],
             "searched": ans.get("searched") or [], "claims": ans.get("claims") or [], "questions": ans.get("questions") or [], "verified": False,
             "changes": ans.get("changes") or [], "lesson": ans.get("lesson")}
    if ver:
        turn["verify"] = ver
        turn["verified_by"] = {"run": run_of(vlog), "job": "architect-verify"}
        by = {v.get("id"): v for v in ver.get("verdicts") or []}
        for c in final["claims"]:
            v = by.get(c.get("id"))
            if v:
                c["outcome"], c["review"] = v.get("outcome"), v.get("reason")
                if v.get("outcome") == "revised" and v.get("revised_text"):
                    c["original_text"], c["text"] = c["text"], v["revised_text"]
        final["shareable_answer"] = ver.get("shareable_answer") or final["shareable_answer"]
        final["confidence"] = ver.get("confidence") or final["confidence"]
        final["conflicts"] += ver.get("new_conflicts") or []
        final["leaks"] = ver.get("leaks") or []
        final["missing_questions"] = ver.get("missing_questions") or []
        final["voice_fixes"] = ver.get("voice_fixes") or []
        final["verified"] = True
    final["unconfirmed"] = checks.architect_claims(final["claims"])  # K10
    final["model_confidence"] = final.get("confidence")
    final["confidence"], final["confidence_why"] = confidence(final)
    turn["final"] = final
    q["status"] = "done"
    over = words(final.get("shareable_answer")) - limit(q, turn)
    import prose_lint  # noqa: E402  (declauding's linter)
    tics = prose_lint.summary(final.get("shareable_answer") or "", 6) if not ver else ""   # verify already fixed them
    fixes = problems(q, turn, final)
    final["code_flags"] = fixes
    # A few words over is not worth a second answer and verify run (about 4 minutes): 10% slack.
    if (over > limit(q, turn) // 10 or tics or fixes) and not turn.get("auto_tighten"):
        # V10 and the checks above in code: one automatic pass before the owner reads it.
        n = limit(q, turn)
        q["turns"].append({"question": " ".join(fixes)
                           + (f" Cut the shareable answer to at most {n} words (it is {words(final.get('shareable_answer'))}). "
                              "Keep every verdict, number, source-backed detail and needed ask; drop greetings, closing questions, "
                              "explanations the client didn't ask for and follow-up promises (brain/architect-voice.md V02 to V10)."
                              if over > 0 else "")
                           + (f" Also rewrite these AI-prose tics as plain statements (S19): {tics}." if tics else ""),
                           "kind": "revise", "revises": len(q["turns"]) - 1, "depth": turn.get("depth", "quick"), "ts": now(),
                           "pending": now(), "auto_tighten": True})
        q["status"] = "working"
        save(q)
        print("TIGHTEN")
        return
    save(q)


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"prompt": lambda: prompt(*sys.argv[2:4]), "verify-prompt": lambda: verify_prompt(*sys.argv[2:5]),
     "apply": lambda: apply(*sys.argv[2:5])}[cmd]()
