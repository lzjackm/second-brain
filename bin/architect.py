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


STOP = set("the a an and or of to in on for with from at by is are be been was were it its this that these those as not no "
           "yes we you your our their they them can will would should could may might has have had do does did than then "
           "there here when what which who how all any each per via into over under about".split())


def _words(t):
    ws = (w.strip(".,;:'") for w in re.findall(r"[a-z0-9][a-z0-9.$%,'-]*", (t or "").lower()))
    return {w for w in ws if w and w not in STOP and (len(w) > 3 or re.search(r"\d", w))}


UNSURE = re.compile(r"\b(isn't|is not|aren't|not) (?:yet )?(?:decided|set|published|confirmed|known|in the (?:docs|specs?))|"
                    r"\bno (?:set|fixed|published|confirmed)\b|\bundecided\b|\bnot yet\b|\bunknown\b|\bunclear\b|\bTBD\b", re.I)


SECONDARY = re.compile(r"slack\.com|docs\.google\.com|drive\.google|#[\w-]+|\bslack\b|\bthread\b|\bDM\b|ledger|"
                       r"DECISIONS\.md|OPEN-ITEMS|ACTIONS\.md|\bD\d{2,4}\b|\bG\d{2,3}\b|meeting notes|gemini", re.I)


def secondary_only(c):
    """Every source is Slack, Drive or a ledger: secondary under the owner's source order (code, ADRs, specs and the
    published docs are primary)."""
    srcs = c.get("sources") or []
    return bool(srcs) and all(SECONDARY.search(f"{x.get('label', '')} {x.get('ref', '')}") for x in srcs)


def claim_level(c):
    """high: confirmed against code, an ADR, a spec or the published docs. medium: confirmed, but only in Slack, Drive
    or a ledger. low: refuted, unsupported, or never checked."""
    o = c.get("outcome")
    if o in ("refuted", "unsupported") or o is None:
        return "low"
    return "medium" if secondary_only(c) else "high"


def segments(final):
    """The shareable answer split into sentences, each with the confidence of the claims it rests on (Nov 24: the owner
    couldn't tell which parts of an answer were solid and which to check). Uses the writer's `spans` when given (exact
    sentence -> claim ids); otherwise matches each claim to the sentence sharing the most numbers and distinctive words.
    A sentence no claim backs stays unmarked unless it states a number or date, which then needs a check."""
    ans = final.get("shareable_answer") or ""
    claims = [c for c in final.get("claims") or [] if c.get("shareable") is not False]
    cuts = sorted({0, len(ans), *(m.end() for m in re.finditer(r"[.!?](?=\s)|\n", ans))})
    parts = []
    for piece in (ans[a:b] for a, b in zip(cuts, cuts[1:]) if ans[a:b]):
        if parts and re.fullmatch(r"\s*(?:[A-Za-z]?\d+(?:\s*(?:/|-|and)\s*[A-Za-z]?\d+)*[.)]|[•*-])", parts[-1]):
            parts[-1] += piece             # "1.", "A4." or "3/4." starts the sentence after it, not a sentence of its own
        else:
            parts.append(piece)
    if "".join(parts) != ans:            # never let the split change the text the owner copies
        return [{"text": ans}]
    rank = {"low": 0, "medium": 1, "high": 2}
    hits = {i: [] for i in range(len(parts))}
    for sp in final.get("spans") or []:
        t = (sp.get("text") or "").strip()
        for i, p in enumerate(parts):
            if t and t in p or (p.strip() and p.strip() in t):
                hits[i] += [c for c in claims if c.get("id") in (sp.get("claims") or [])]
    if not any(hits.values()):
        for c in claims:
            cw = _words(c.get("text"))
            nums = set(re.findall(r"\d[\d.,]*", c.get("text") or ""))
            best, score = None, 0.0
            for i, p in enumerate(parts):
                pw = _words(p)
                if not pw or not cw:
                    continue
                sc = len(cw & pw) / len(cw) + 0.5 * len(nums & set(re.findall(r"\d[\d.,]*", p)))
                if sc > score:
                    best, score = i, sc
            if best is not None and score >= 0.34:
                hits[best].append(c)
    partly = partly_marks(final, parts)
    out = []
    for i, p in enumerate(parts):
        if i in partly:
            out.append({"text": p, "level": "low", "q": partly[i]["where"], "why": partly[i]["why"]})
            continue
        cs = hits[i]
        if not p.strip():
            out.append({"text": p}); continue
        if cs:
            worst = min(cs, key=lambda c: rank[claim_level(c)])
            lv = claim_level(worst)
            src = (worst.get("sources") or [{}])[0]
            why = {"low": worst.get("review") or ("Not checked against a source" if worst.get("outcome") is None else "No source backs this"),
                   "medium": "Only in " + (src.get("label") or "Slack or Drive"),
                   "high": "Confirmed in " + (src.get("label") or "a primary source")}[lv]
            out.append({"text": p, "level": lv, "why": why[:220], "ref": src.get("ref"), "claims": [c.get("id") for c in cs]})
        elif final.get("spans") and re.search(r"\d|\b(will|is|are|has|planned|live|supports?)\b", p, re.I):
            out.append({"text": p, "level": "low", "why": "The writer cited no source for this"})
        else:
            out.append({"text": p})
    return out


LABEL = re.compile(r"^\s*([A-Za-z]?\d+(?:\s*(?:/|-|and)\s*[A-Za-z]?\d+)*)\s*[.:)]")


def partly_marks(final, parts):
    """For each client question answered only partly (or not at all): the sentence of its block that addresses it,
    with what is missing (Nov 24: "where's the piece it's unsure about? I want that highlighted in the text"). Uses
    the writer's `span` and `missing` when given; otherwise finds the question's block by its label (A1, B2, 3) and the
    sentence there that shares the most words with the matching gap and the question."""
    gaps = final.get("gaps") or []
    labels = {}
    for i, p in enumerate(parts):
        m = LABEL.match(p)
        if m:
            for lab in re.split(r"\s*(?:/|-|and)\s*", m.group(1)):
                labels.setdefault(lab.lower(), i)
    starts = sorted(set(labels.values()))
    marks = {}
    for q in final.get("questions") or []:
        if q.get("answered") not in ("partly", "no"):
            continue
        where = str(q.get("where") or "").strip().rstrip(".:)")
        qw = _words(q.get("q"))
        gap = q.get("missing") or max(gaps, key=lambda g: len(_words(g) & qw), default="")
        if gap and not q.get("missing") and len(_words(gap) & qw) < 2:
            gap = ""
        i0 = labels.get(where.lower())
        block = range(i0, next((s for s in starts if s > i0), len(parts))) if i0 is not None else range(len(parts))
        target = None
        if q.get("span"):
            target = next((i for i in block if q["span"].strip() and q["span"].strip() in parts[i]), None)
        if target is None:
            gw = _words(gap)   # the gap's words count double; a sentence that states the uncertainty is the likely one
            scored = [(2 * len(_words(parts[i]) & gw) + len(_words(parts[i]) & qw) + (3 if UNSURE.search(parts[i]) else 0), i)
                      for i in block if parts[i].strip()]
            unsure = [(sc, i) for sc, i in scored if UNSURE.search(parts[i]) and _words(parts[i]) & (gw | qw)]
            pick = max(unsure or scored, default=(0, None))   # a sentence saying what isn't settled beats word overlap
            target = pick[1] if pick[0] else (i0 if i0 is not None else None)
        if target is None or target in marks:
            continue
        what = gap or "the sources don't settle all of this question"
        marks[target] = {"where": where, "why": f"{where + ': ' if where else ''}{'not answered' if q.get('answered') == 'no' else 'partly answered'}. "
                                                  f"Missing: {what[0].lower() + what[1:] if what else what}"[:240]}
    return marks


def counts(final):
    """What the header shows, from the same rules as the badge: claims to check (low), claims resting only on Slack,
    Drive or the ledger (medium), and client questions only partly answered. Counted from claims, not just marked
    sentences, so a weak claim no sentence matched is never hidden."""
    claims = [c for c in final.get("claims") or [] if c.get("shareable") is not False]
    lv = collections.Counter(claim_level(c) for c in claims)
    partly = [{"where": str(q.get("where") or "").strip()[:12], "q": q.get("q", ""), "answered": q.get("answered")}
              for q in final.get("questions") or [] if q.get("answered") in ("partly", "no")]
    return {"low": lv["low"], "medium": lv["medium"], "partly": len(partly), "partly_list": partly[:8]}


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
        mid.append(f"{n} claim{'s' if n > 1 else ''} only in Slack, Drive or the ledger")
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


NEG = re.compile(r"\b(no date|has no date|with no date|no timeline|not (?:yet )?(?:published|announced|decided|set|confirmed)|"
                 r"(?:aren't|isn't|is not|are not) (?:yet )?(?:published|announced|decided|set|confirmed)|unconfirmed|not yet on)\b", re.I)


def slack_searched(q, turn):
    """Whether this answer's run (or the run it revises) searched Slack."""
    base = q["turns"][turn["revises"]] if turn.get("kind") == "revise" else turn
    logs = ((base.get("final") or base.get("answer") or {}).get("searched") or []) + ((turn.get("answer") or {}).get("searched") or [])
    return any("slack" in str(x).lower() and "not searched" not in str(x).lower() for x in logs)


ROUTE_SKIP = set("the a an to of via from into and or with on for at by testnet mainnet planned live route flow".split())


def missing_routes(q, ans):
    """Live or planned routes the research lanes found that the answer never names (Nov 20: the lanes found two solver
    routes and an API route; the answer said "no direct route")."""
    low, out = (ans or "").lower(), []
    turn = next((t for t in reversed(q.get("turns") or []) if t.get("kind") != "revise"), {})
    asked = (turn.get("question") or "").lower()   # words the client already used say nothing about which route
    for f in lane_files(q["id"]):
        try:
            routes = json.loads(f.read_text()).get("routes") or [] if f.exists() else []
        except (OSError, json.JSONDecodeError):
            continue
        for r in routes:
            if str(r.get("status", "")).startswith("not") or r.get("q") in (None, "", "0", 0):
                continue
            if not re.search(r"(?i)bridg|solver|\bapi\b|transfer|route|flow|token|withdraw|deposit|testnet|network", r.get("route", "")):
                continue   # a tip or how-to the lane listed as a route; only ways to move funds or connect are required
            names = [w for w in re.findall(r"\b(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,})\b", r.get("route", ""))
                     if w.lower() not in ROUTE_SKIP and not re.search(rf"\b{re.escape(w.lower())}\b", asked)]
            if names and not any(re.search(rf"\b{re.escape(n.lower())}\b", low) for n in names):
                out.append(f"question {r.get('q')}: {r.get('route')} ({r.get('status')})")
    return out[:6]


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


def with_images(tpl, q, turn):
    return tpl + images_block(q, turn)


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
        Path(out).write_text(with_images(tpl, q, turn).replace("{{NOW}}", now()).replace("{{DATE}}", now()[:10]).replace("{{QUESTION}}", client_q(q, turn))
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
    ctx += sent_examples(i)
    since = datetime.fromisoformat(turn["ts"]).timestamp() if turn.get("ts") else 0
    Path(out).write_text(with_images(tpl, q, turn).replace("{{NOW}}", now()).replace("{{DEPTH}}", turn["depth"])
                         .replace("{{QUESTION}}", turn["question"]).replace("{{CONTEXT}}", ctx) + lanes_block(i, since))


LANE_RE = r"docs\d?|live\d?"
PREFIX = {"docs": "d", "docs1": "d", "docs2": "e", "live": "s", "live1": "s", "live2": "t"}


def lane_file(i, lane):
    return ROOT / "state" / f"sa-lane-{lane}-{i}.json"


def lane_files(i):
    return sorted(f for f in (ROOT / "state").glob(f"sa-lane-*-{i}.json") if re.fullmatch(rf"sa-lane-({LANE_RE})-{re.escape(i)}\.json", f.name))


def lanes_for(i):
    """The research lanes for a question. With three or more numbered questions, docs and Slack are each split in two by
    question, four lanes at once (Nov 20: one lane per source took 3.5 minutes; the slowest lane sets the time)."""
    q = load(i)
    nums = sorted(numbers(next(t for t in reversed(q["turns"]) if t.get("kind") != "revise")["question"]))
    if len(nums) < 3:
        return [("docs", ""), ("live", "")]
    half = (len(nums) + 1) // 2
    a, b = ",".join(map(str, nums[:half])), ",".join(map(str, nums[half:]))
    return [("docs1", a), ("docs2", b), ("live1", a), ("live2", b)]


def lane_prompt(i, lane, out, digest=None, qs=""):
    """A research lane's brief (Nov 20): only the question, its own sources and the findings format. No voice, length or
    answer rules: the writer gets those. The docs lane starts from code's search digest; the live lane reads the docs
    lane's findings near the end, so what one learns reaches the other."""
    q = load(i)
    turn = q["turns"][-1]
    m = (CFG.get("modules") or {}).get("architect") or {}
    gh = m.get("github") or []
    if lane.startswith("docs"):
        auth = m.get("authority") or [f"`{x['dest']}/`" for x in m.get("sources") or []]
        src = ("Snapshots under `state/snapshots/sa/` (read `state/snapshots/sa/MANIFEST.md` first), by authority:\n"
               + "\n".join(f"{n}. {a}" for n, a in enumerate(auth, 1))
               + "\n- Other local repos in the search folders you were given."
               + ("\n- GitHub PRs and issues: " + ", ".join(f"`gh pr list -R {r} --search \"<terms>\" --state all`, `gh issue list -R {r} --search \"<terms>\"`" for r in gh) if gh else ""))
        dig = Path(digest).read_text() if digest and Path(digest).exists() else ""
        extra = ((f"- Your questions: {qs}. Another run searches the docs for the others; cover yours thoroughly and skip theirs.\n" if qs else "")
                 + "- Do not search Slack, Drive or other connected apps: the other run covers them.\n"
                 "- Code already searched every snapshot for the question's terms. Start from its digest below: open what it points "
                 "to, then search only for what it misses (other phrasings, related terms).\n\n## Code's search digest\n" + (dig or "(no hits)"))
    else:
        src = ("The connected apps: Slack (several phrasings per question, the last 60 days, the relevant channels, threads read in full), "
               "Drive meeting notes, and the issue tracker. Search Slack on every client question, even when you expect the docs to cover it.")
        focus = (f"- Your questions: {qs}. Another run searches Slack for the others; cover yours thoroughly and skip theirs.\n" if qs else "")
        extra = (focus + f"- Do not search the local snapshots or repos: the other run covers them.\n"
                 f"- After your first round, read whichever of `state/sa-lane-docs-{i}.json`, `state/sa-lane-docs1-{i}.json` and "
                 f"`state/sa-lane-docs2-{i}.json` exist (the docs runs' findings so far). "
                 "Search Slack for the newest status of anything it marks undecided, undated or missing, and for any route it doesn't list.")
    ctx = f"Client or context: {q['context']}\n" if q.get("context") else ""
    earlier = [f"Q: {t['question']}\nA: {(t.get('final') or {}).get('shareable_answer', '')}" for t in q["turns"][:-1] if not t.get("auto_tighten")]
    if earlier:   # a follow-up only makes sense with the thread it follows (Nov 20: lanes saw just the one-line follow-up)
        ctx += ("\nThis is a follow-up. The question above is the newest message; research it in light of the thread so far:\n\n"
                + "\n\n".join(earlier) + "\n")
    tpl = sa_fill((ROOT / "prompts" / "architect-lane.md").read_text())
    Path(out).write_text(tpl.replace("{{LANE_SOURCES}}", src).replace("{{LANE_EXTRA}}", extra).replace("{{NOW}}", now())
                         .replace("{{QUESTION}}", turn["question"]).replace("{{CONTEXT}}", ctx))


def draft(i, log):
    """The writer's answer, shown while verify checks it (Nov 20: you can read at about 5 minutes instead of 9)."""
    q = load(i)
    ans = last_json(Path(log).read_text() if log and Path(log).exists() else "")
    if ans and ans.get("shareable_answer"):
        q["turns"][-1]["draft"] = ans["shareable_answer"]
        save(q)


def norm(t):
    return re.sub(r"[\s`*_\\|]+", " ", (t or "").lower()).strip()


def source_text(ref):
    """The local file a citation points to (snapshot or repo path), or None for links and missing files."""
    path = re.split(r"[#:]", (ref or "").strip(), maxsplit=1)[0].strip()
    if not path or re.match(r"https?:|www\.", path):
        return None
    for base in (ROOT / "state" / "snapshots" / "sa", ROOT, Path.home()):
        f = (base / path.lstrip("~/")) if not path.startswith("/") else Path(path)
        if f.is_file():
            try:
                return f.read_text(errors="ignore")
            except OSError:
                return None
    return None


def quoted(quote, text):
    """Every piece of the quote (split at "..." where words were skipped) appears in the text."""
    parts = [norm(x)[:120] for x in re.split(r"\.\.\.|…", quote) if len(norm(x)) >= 12]
    return bool(parts) and all(x in text for x in parts)


def code_confirmed(claims):
    """Claims whose every source is a local file that contains its quote word for word: verify skips them."""
    out = []
    for c in claims or []:
        srcs = c.get("sources") or []
        if srcs and all(s.get("quote") and (t := source_text(s.get("ref"))) and quoted(s["quote"], norm(t)) for s in srcs):
            out.append(c.get("id"))
    return [x for x in out if x]


def lane_save(i, lane, log):
    """Keep a lane's findings for the other lane and the writer."""
    ans = last_json(Path(log).read_text() if log and Path(log).exists() else "")
    ans = ans or {"findings": [], "not_found": [f"the {lane} run returned nothing"]}
    for n, f in enumerate(ans.get("findings") or [], 1):   # the writer cites findings by id; code fills in the sources
        if isinstance(f, dict):
            f["id"] = f"{PREFIX.get(lane, 'x')}{n}"
    lane_file(i, lane).write_text(json.dumps(ans, indent=1, ensure_ascii=False))


def findings_by_id(i):
    out = {}
    for f in lane_files(i):
        try:
            for x in json.loads(f.read_text()).get("findings") or []:
                if isinstance(x, dict) and x.get("id"):
                    out[x["id"]] = x
        except (OSError, json.JSONDecodeError):
            pass
    return out


def expand(i, ans):
    """Claims the writer cited by finding id get those findings' sources and quotes, copied in code (Nov 20: the writer
    spent most of its 2.5 minutes copying quotes)."""
    if not ans:
        return ans
    by = findings_by_id(i)
    for c in ans.get("claims") or []:
        ids = c.get("findings") or []
        if ids and not c.get("sources"):
            c["sources"] = [by[x]["source"] for x in ids if x in by and isinstance(by[x].get("source"), dict)]
    if not ans.get("searched"):
        ans["searched"] = [s for f in lane_files(i) for s in (json.loads(f.read_text()).get("searched") or [])]
    return ans


def lanes_block(i, since):
    """Both lanes' findings, for the writer: what was found, not the raw search results."""
    out = []
    for f in lane_files(i):
        if f.stat().st_mtime >= since:
            lane = re.match(rf"sa-lane-({LANE_RE})-", f.name).group(1)
            out.append(f"### {lane} run\n```json\n{f.read_text()}\n```")
    if not out:
        return ""
    return ("\n\n## Research already done\nTwo runs searched the sources in parallel: docs (snapshots, repos, GitHub) and live "
            "(Slack, Drive, the issue tracker). Write the answer from their findings. You have no search tools: if a client question "
            "can't be answered from the findings, say what is missing in `gaps`. Code, ADRs, specs and published docs are the source of "
            "truth: when a primary finding and a secondary one (Slack, Drive, ledgers) disagree, answer with the primary one and put the "
            "other in `internal_notes` as a possible docs gap. Use secondary findings for plans, dates and what the docs don't cover.\n\n**Cite findings by id, don't copy them.** Each "
            "claim is `{\"id\": \"C1\", \"text\": \"...\", \"shareable\": true, \"findings\": [\"d3\", \"s2\"]}` with no `sources`: code copies "
            "each finding's source and quote in. Leave `searched` empty; code fills it.\n\n" + "\n\n".join(out))


def sent_examples(i, n=3):
    """The owner's most recent real replies (pasted with "What I sent"), next to the question they answered: the closest
    guide to how answers should read, used the next time before any rule is approved (Nov 20)."""
    got = []
    for f in sorted((ROOT / "architect").glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        if f.stem == i:
            continue
        try:
            q = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for t in reversed(q.get("turns") or []):
            if t.get("sent") and t.get("kind") != "revise":
                got.append((client_q(q, t)[:1500], t["sent"]["text"][:2500]))
                break
        if len(got) >= n:
            break
    if not got:
        return ""
    return ("\nAnswers the owner actually sent recently, after editing drafts like yours: match their length, structure and "
            "voice (never their facts, which may be out of date):\n\n" + "\n\n".join(f"Client asked:\n{a}\n\nOwner sent:\n{b}" for a, b in got) + "\n")


def verify_prompt(i, log, out):
    q = load(i)
    ans = expand(i, last_json(Path(log).read_text() if Path(log).exists() else ""))
    if not ans:
        Path(out).write_text("")
        return
    tpl = sa_fill((ROOT / "prompts" / "architect-verify.md").read_text())
    turn = q["turns"][-1]
    if turn.get("kind") == "revise":
        tpl = tpl.replace("## Do this", "## The owner's instructions for this rewrite (authoritative)\n" + turn["question"] +
                          "\n\nHonor them in your final answer and never undo them, including length and format limits. If one conflicts with answering every client question, fit the answers inside his limit (combine points) rather than breaking it.\n\n## Do this", 1)
    done = code_confirmed(ans.get("claims"))
    if done:   # code checked these quotes against their files; the verify run only needs the rest
        tpl = tpl.replace("## Do this", "## Already confirmed by code\nThese claims' quotes were found word for word in the cited "
                          f"local files: {', '.join(done)}. Don't re-check their sources; check every other claim.\n\n## Do this", 1)
    import prose_lint  # noqa: E402  (declauding's linter)
    tics = prose_lint.summary(ans.get("shareable_answer") or "", 6)
    if tics:   # fixed here, in the verify run, instead of in an extra pass afterwards (Nov 20: that pass added 4 minutes)
        tpl = tpl.replace("## Do this", f"## Also fix\nRewrite these AI-prose tics in the shareable answer as plain statements (S19): {tics}.\n\n## Do this", 1)
    Path(out).write_text(with_images(tpl, q, q["turns"][-1]).replace("{{NOW}}", now()).replace("{{QUESTION}}", client_q(q, q["turns"][-1]))
                         .replace("{{ANSWER}}", json.dumps(ans, indent=1, ensure_ascii=False)))


def run_of(log):
    m = re.search(r"/([^/]+)\.log$", log or "")
    return m.group(1) if m else None


def apply(i, alog, vlog):
    q = load(i)
    turn = q["turns"][-1]
    ans = expand(i, last_json(Path(alog).read_text() if alog and Path(alog).exists() else ""))
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
             "changes": ans.get("changes") or [], "lesson": ans.get("lesson"), "spans": ans.get("spans") or []}
    if ver:
        turn["verify"] = ver
        turn["verified_by"] = {"run": run_of(vlog), "job": "architect-verify"}
        by = {v.get("id"): v for v in ver.get("verdicts") or []}
        coded = set(code_confirmed(final["claims"]))
        for c in final["claims"]:
            if c.get("id") in coded and c.get("id") not in by:
                c["outcome"], c["review"] = "confirmed", "quote found word for word in the cited file (checked in code)"
            v = by.get(c.get("id"))
            if v:
                c["outcome"], c["review"] = v.get("outcome"), v.get("reason")
                if v.get("outcome") == "revised" and v.get("revised_text"):
                    c["original_text"], c["text"] = c["text"], v["revised_text"]
        if ver.get("shareable_answer") and ver["shareable_answer"] != final["shareable_answer"]:
            final["spans"] = ver.get("spans") or []   # the reviewer rewrote it: the writer's spans no longer line up
        final["shareable_answer"] = ver.get("shareable_answer") or final["shareable_answer"]
        final["confidence"] = ver.get("confidence") or final["confidence"]
        final["conflicts"] += ver.get("new_conflicts") or []
        final["leaks"] = ver.get("leaks") or []
        final["missing_questions"] = ver.get("missing_questions") or []
        if ver.get("questions"):
            final["questions"] = ver["questions"]   # the reviewer's view of coverage, against the answer as it now reads
        final["voice_fixes"] = ver.get("voice_fixes") or []
        final["verified"] = True
    final["unconfirmed"] = checks.architect_claims(final["claims"])  # K10
    final["model_confidence"] = final.get("confidence")
    final["confidence"], final["confidence_why"] = confidence(final)
    final["segments"] = segments(final)
    final["counts"] = counts(final)
    turn["final"] = final
    q["status"] = "done"
    import prose_lint  # noqa: E402  (declauding's linter)
    tics = prose_lint.summary(final.get("shareable_answer") or "", 6) if not ver else ""   # verify already fixed them
    fixes = problems(q, turn, final)
    final["code_flags"] = fixes
    # Routes the research found that the answer doesn't name: a note for the owner, not a rewrite (Nov 20: forcing them in
    # doubled the length and added a 4-minute pass). Shown under "Reasoning and checks".
    final["routes_not_named"] = missing_routes(q, final.get("shareable_answer"))
    # No word cap (Nov 20): length follows the question, and brevity is a writing rule (V10). Code sends an answer back
    # once only for what is wrong in it: numbering, an unchecked "no date", a route left out, AI-prose tics.
    if (tics or fixes) and not turn.get("auto_tighten"):
        q["turns"].append({"question": " ".join(fixes)
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
     "apply": lambda: apply(*sys.argv[2:5]), "lane-prompt": lambda: lane_prompt(*sys.argv[2:7]),
     "lanes": lambda: print("\n".join(f"{n} {qs}" for n, qs in lanes_for(sys.argv[2]))),
     "lane-save": lambda: lane_save(*sys.argv[2:5]), "draft": lambda: draft(*sys.argv[2:4])}[cmd]()
