#!/usr/bin/env python3
"""Merge duplicate queue items: two open items in one area that cite the same Slack message and are about the same
thing (shared distinctive words) are one item.

Plain code; runs at the start of every lead run (prefetch-<area>.sh) and at the end of the pipeline. Keeps the item
The owner has touched, else the older one, and marks the other stale with a pointer to the keeper. Items the owner touched
on both sides are left alone and reported.
Usage: dedupe.py [area]
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import OWNER, OWNER_NAMES, LEDGER_AREA  # noqa: E402  (config/brain.json)
ITEMS = ROOT / "queue" / "items"
LIVE = {"open", "waiting", "working", "snoozed"}
MSG = re.compile(r"slack\.com/archives/([A-Z0-9]+)/p(\d+)")


def msgs(item):
    return set(MSG.findall(json.dumps({k: item.get(k) for k in ("evidence", "steps")})))


STOP = set("the a an and or of to in on for with is are be by from as at it this that what which when who will can your you log reply answer give send get ask".split()) | OWNER_NAMES


def words(item):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (item.get("title", "") + " " + item.get("context", "")).lower()) if w not in STOP}


def title_words(item):
    return {w for w in re.findall(r"[a-z0-9]{3,}", item.get("title", "").lower()) if w not in STOP}


def same_batch(a, b):
    """Created in the same run by the same creator: a deliberate split (one handoff into several items), not a
    duplicate. Duplicates come from separate runs finding the same thing again."""
    by = lambda it: next((h.get("by") for h in it.get("history", []) if h.get("event", "").startswith("created")), None)
    return a.get("created", "")[:16] == b.get("created", "")[:16] != "" and by(a) == by(b)


def same_thing(a, b):
    """Shared words across title and context are not enough: items split from one handoff message share its
    vocabulary. The titles must overlap too: at least two shared title words and at least half of the shorter title."""
    if same_batch(a, b):
        return False
    ta, tb = title_words(a), title_words(b)
    shared = len(ta & tb)
    return len(words(a) & words(b)) >= 3 and shared >= 2 and shared * 2 >= min(len(ta), len(tb))


def touched(item):
    return any(h.get("by") == OWNER for h in item.get("history", []))


def same_key(a, b):
    """One key is one underlying thing (queue/SCHEMA.md): the same key twice is a duplicate whatever the wording."""
    return bool(a.get("key")) and a.get("key") == b.get("key")


def closed_again(area=None):
    """A Slack saved message the owner already closed (done, dismissed) is not their to-do again: a run that recreated
    it is undone here."""
    closed, live = set(), []
    for f in sorted(ITEMS.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        k = it.get("key") or ""
        if not k.startswith("slack-saved:"):
            continue
        if it.get("status") in LIVE:
            live.append((f, it))
        elif it.get("status") in ("done", "dismissed", "delegated"):
            closed.add((k, it.get("created", "")))
    now = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    for f, it in live:
        if (area and it.get("area") != area) or touched(it):
            continue
        if any(k == it["key"] and c < it.get("created", "") for k, c in closed):
            it["status"] = "stale"
            it["updated"] = now
            it.setdefault("history", []).append({"ts": now, "by": "dedupe", "event": "already closed by the owner (same saved Slack message)"})
            f.write_text(json.dumps(it, indent=2, ensure_ascii=False))
            print(f"closed before: {it['id']}")


def main(area=None):
    closed_again(area)
    items = []
    for f in sorted(ITEMS.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if it.get("status") in LIVE and (not area or it.get("area") == area) and not it.get("key", "").startswith((f"{LEDGER_AREA}:pr:", "brain:")):
            items.append((f, it, msgs(it)))
    gone = set()
    now = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    for i, (fa, a, ma) in enumerate(items):
        for fb, b, mb in items[i + 1:]:
            if fa in gone or fb in gone or a.get("area") != b.get("area") or not (ma & mb or same_key(a, b)):
                continue
            # A shared message is not enough on its own: a busy group thread or a handoff message is cited by
            # different items. Require the items to be about the same thing too.
            if not (same_key(a, b) or same_thing(a, b)):
                continue
            if touched(a) and touched(b):
                print(f"both touched, left alone: {a['id']} and {b['id']}")
                continue
            keep, drop, fdrop = (a, b, fb) if touched(a) or (not touched(b) and a.get("created", "") <= b.get("created", "")) else (b, a, fa)
            drop["status"] = "stale"
            drop["updated"] = now
            drop.setdefault("history", []).append({"ts": now, "by": "dedupe", "event": f"duplicate of {keep['id']} (same {'key' if same_key(a, b) else 'Slack message'})"})
            fdrop.write_text(json.dumps(drop, indent=2, ensure_ascii=False))
            gone.add(fdrop)
            print(f"merged: {drop['id']} -> {keep['id']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
