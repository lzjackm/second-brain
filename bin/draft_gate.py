#!/usr/bin/env python3
"""The draft gate: a high-stakes draft reaches the owner only after it shows its thinking (Nov 25, framework phase 1).

Five drafts went wrong on Nov 25 for one reason: each was written in a single pass. A reaction was read as an ask; a
promise the recipient had called off was sent anyway; a 16-point redline reply took Legal's fix where the owner had
already settled the points with the firm. So every high-stakes owner send step carries a `brief` (queue/SCHEMA.md):

  "brief": {"read": [{"source": "Slack DM with the vendor contact", "kind": "chat", "from": "2026-11-17", "to": "2026-11-25"}],
            "points": [{"point": "1. uptime", "position": "the owner's newest stated position, or null",
                        "source": "where and when the owner said it", "theirs": "who recommended what, or null",
                        "rule": "the knowledge rule applied, or null"}]}

Stage 1 (is it real and the owner's) is bin/reply_gate.py and bin/self_task_gate.py. This gate checks stages 2 and 3:
- read: the source kinds the draft's class needs (CLASSES), the sources a matching knowledge file names (its
  `sources:` line), and chats read back at least 7 days before the ask or promise;
- points: a point-by-point draft lists each point with the owner's position and its source, and every point without
  one is left in the draft as "[your call: ...]". Someone else's recommendation is never the owner's position.

A failing step goes back for one automatic revision with the reasons (step `revisions`, by draft_gate) and the item
shows as working meanwhile; if the revision still fails, the owner sees it with checks.py K18 blocking the send.
The owner's own edits are never gated. Runs in the app's sweep and at the start of every run (prefetch.sh).

Usage: draft_gate.py [area] [--dry]
"""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import TZ, is_owner  # noqa: E402

ITEMS = ROOT / "queue" / "items"
KNOWLEDGE = ROOT / "brain" / "knowledge"
LIVE = {"open", "waiting", "working"}
PENDING = {"todo", "failed"}
SENDS = {"slack_send", "slack_draft", "email_draft", "gdoc_create", "gdoc_update"}
KINDS = {"chat", "email", "doc", "knowledge", "ledger", "code", "calendar"}
GATE_SINCE = "2026-11-25T15:35"   # items created from here carry a brief
POINT = re.compile(r"^\s*\d{1,2}[.)]\s", re.M)
REVIEWED = re.compile(r"redline|contract|agreement|term sheet|mark-?up|comments on|review", re.I)
YOUR_CALL = re.compile(r"\[your call", re.I)

# What each class of draft must have read. A draft can be in several classes; it needs all their kinds.
CLASSES = {
    "external": ("goes outside the company", {"chat"}),
    "point_list": ("answers a list point by point", {"doc", "chat", "knowledge"}),
    "decision": ("settles a decision", {"chat", "ledger"}),
}


def text_of(item, step):
    return " ".join(str(x or "") for x in (item.get("title"), item.get("context"), item.get("summary"), step.get("draft")))


def classes(item, step):
    out = []
    if (step.get("execute") or {}).get("audience") == "external":
        out.append("external")
    draft = step.get("draft") or ""
    head = " ".join(str(item.get(k) or "") for k in ("title", "context", "summary"))
    if len(POINT.findall(draft)) >= 3 or REVIEWED.search(head):
        out.append("point_list")
    if item.get("type") == "decide":
        out.append("decision")
    return out


def knowledge_sources(item, step):
    """Sources a matching knowledge file says every draft on its subject must read (`sources:` frontmatter line)."""
    text, need = text_of(item, step).lower(), []
    for f in sorted(KNOWLEDGE.glob("*.md")):
        head = f.read_text(errors="ignore").split("\n---", 1)[0]
        trig = re.search(r"^triggers:\s*(.+)$", head, re.M)
        src = re.search(r"^sources:\s*(.+)$", head, re.M)
        if trig and src and any(t.strip().lower() and re.search(r"\b" + re.escape(t.strip().lower()) + r"\b", text)
                                for t in trig.group(1).split(",")):
            need += [s.strip() for s in src.group(1).split(",") if s.strip()]
    return need


def anchor(item, step):
    for rec in (step.get("ask"), step.get("owed")):
        if isinstance(rec, dict) and rec.get("at"):
            return rec["at"]
    return item.get("created")


def day(s):
    try:
        return datetime.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def problems(item, step):
    """Why this draft can't reach the owner yet: a list of plain reasons, empty when it passes."""
    if step.get("owner_edited"):
        return []
    cls = classes(item, step)
    if not cls:
        return []
    brief = step.get("brief")
    if not isinstance(brief, dict):
        return ["no brief: list what you read (with dates) and, point by point, the owner's position and its source"]
    out = []
    read = [r for r in brief.get("read") or [] if isinstance(r, dict)]
    have = {r.get("kind") for r in read}
    for c in cls:
        missing = sorted(CLASSES[c][1] - have)
        if missing:
            out.append(f"it {CLASSES[c][0]} but read no {', '.join(missing)} source")
    names = " | ".join(str(r.get("source") or "") for r in read).lower()
    for need in knowledge_sources(item, step):
        if need.lower() not in names:
            out.append(f"the knowledge file says to read {need}; it isn't in what you read")
    chats = [day(r.get("from")) for r in read if r.get("kind") in ("chat", "email") and day(r.get("from"))]
    a = day(anchor(item, step))
    if chats and a and min(chats) > a - timedelta(days=7):
        out.append("chats were read from " + min(chats).strftime("%b %d") + "; read back at least 7 days before "
                   + a.strftime("%b %d") + " to catch what was already settled or called off")
    if "point_list" in cls:
        pts = [p for p in brief.get("points") or [] if isinstance(p, dict)]
        n = len(POINT.findall(step.get("draft") or ""))
        if len(pts) < n:
            out.append(f"the draft answers {n} points but the brief accounts for {len(pts)}")
        open_pts = [p for p in pts if not (str(p.get("position") or "").strip() and str(p.get("source") or "").strip())]
        if len(open_pts) > len(YOUR_CALL.findall(step.get("draft") or "")):
            out.append(f"{len(open_pts)} points have no position of the owner's with a source; leave each as "
                       "[your call: ...] in the draft instead of answering it")
        borrowed = [p.get("point") for p in pts if p.get("theirs") and str(p.get("position") or "").strip() == str(p.get("theirs")).strip()]
        if borrowed:
            out.append("takes someone else's recommendation as the owner's position on " + ", ".join(map(str, borrowed))[:80])
    return out


def current(item):
    return next((s for s in item.get("steps") or [] if s.get("status", "todo") in PENDING), None)


def gated(item):
    """The owner send step this gate applies to, or None."""
    s = current(item)
    if not s or not is_owner(s.get("owner")) or (s.get("execute") or {}).get("kind") not in SENDS:
        return None
    if (item.get("created") or "") < GATE_SINCE or (item.get("key") or "").startswith(("own:", "slack-saved:")):
        return None
    return s


def sweep(area=None, dry=False):
    """Send failing drafts back for one revision. Returns the areas that need a revise run."""
    ts = datetime.now(TZ).isoformat(timespec="seconds")
    areas = set()
    for f in sorted(ITEMS.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if it.get("status") not in LIVE or (area and it.get("area") != area) or it.get("area") == "meetings":
            continue
        s = gated(it)
        if not s or (s.get("revise_requested") or "") > (s.get("revised_at") or ""):
            continue   # not gated, or a revision is already underway
        why = problems(it, s)
        if not why or any(r.get("by") == "draft_gate" for r in s.get("revisions") or []):
            continue   # passes, or already had its one automatic revision (K18 blocks the send instead)
        print(f"{it['id']}: back for revision ({'; '.join(why)[:160]})")
        if dry:
            continue
        s["revise_requested"] = ts
        s.setdefault("revisions", []).append({"ts": ts, "by": "draft_gate", "draft_before": s.get("draft", ""),
                                              "note": "Brief: before the owner sees this, fix the brief and the draft (queue/SCHEMA.md `brief`): "
                                                      + "; ".join(why)})
        it.setdefault("history", []).append({"ts": ts, "by": "draft_gate", "event": "sent back for revision: " + "; ".join(why)[:300]})
        f.write_text(json.dumps(it, indent=1, ensure_ascii=False))
        areas.add(it.get("area"))
    return areas


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sweep(args[0] if args else None, "--dry" in sys.argv)
