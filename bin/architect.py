#!/usr/bin/env python3
"""Solutions Architect: build prompts and merge the answer with its skeptical review.

Usage: architect.py prompt <id> <out.md>            the answer prompt for the latest turn
       architect.py verify-prompt <id> <log> <out.md> the reviewer's prompt, from the answer run's log
       architect.py apply <id> <answer-log> <verify-log>
A question lives in architect/<id>.json; each follow-up is a new turn with its own answer and review.
"""
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


def words(t):
    return len(re.findall(r"\S+", t or ""))


def limit(q, turn):
    """Longest the shareable answer may be (V10): about the client's own length, between 50 and 160 words."""
    return max(50, min(160, round(1.2 * words(client_q(q, turn)))))


def with_limit(tpl, q, turn):
    return tpl.replace("{{SA_LIMIT}}", str(limit(q, turn)))


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
    turn["final"] = final
    q["status"] = "done"
    over = words(final.get("shareable_answer")) - limit(q, turn)
    import prose_lint  # noqa: E402  (declauding's linter)
    tics = prose_lint.summary(final.get("shareable_answer") or "", 6)
    if (over > 0 or tics) and not turn.get("auto_tighten"):
        # V10 in code: an answer over the limit gets one automatic tightening pass before the owner reads it.
        n = limit(q, turn)
        q["turns"].append({"question": f"Cut the shareable answer to at most {n} words (it is {words(final.get('shareable_answer'))}). "
                           "Keep every verdict, number and needed ask; drop greetings, closing questions, explanations the client "
                           "didn't ask for, second options and follow-up promises (brain/architect-voice.md V02 to V10)."
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
