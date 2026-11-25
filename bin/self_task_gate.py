#!/usr/bin/env python3
"""Move work Claude Code can do itself out of the owner's queue and into the fix queue (Nov 25: "this is not my job ...
This is your job"). Two items reached the owner that sessions had written as reminders for themselves: "Ask Claude Code
to verify the token in today's ingest run" and "Review the pipeline's first week" (a script already computes it).

An owner step is Claude's own work when it tells the owner to ask Claude, or when a Claude Code session made the item
as a check or review with nothing for the owner to press. Each moves to bin/fixes.py, held until its snooze or due
time (`not_before`), and the item is closed. Runs at the start of every lead run (prefetch.sh) and in the app's sweep.

Usage: self_task_gate.py [area] [--dry]
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import TZ, is_owner  # noqa: E402
import fixes  # noqa: E402

ITEMS = ROOT / "queue" / "items"
LIVE = {"open", "waiting", "working", "snoozed"}
PENDING = {"todo", "queued", "failed"}
SESSIONS = {"claude-code", "interactive"}
ASK_CLAUDE = re.compile(r"\b(ask|have|get|tell)\s+(a\s+)?claude(\s+code)?(\s+session)?\s+to\b|\bin claude code\b", re.I)


def made_by_session(it):
    h = (it.get("history") or [{}])[0]
    mb = it.get("made_by")
    job = mb.get("job") if isinstance(mb, dict) else mb   # made_by is a dict or a plain string on older items
    return (isinstance(h, dict) and h.get("by") in SESSIONS) or job in SESSIONS


def claude_work(it):
    """True when every pending owner step is Claude's own work, not the owner's."""
    steps = [s for s in it.get("steps") or [] if s.get("status", "todo") in PENDING and is_owner(s.get("owner"))]
    if not steps:
        return False
    def mine(s):
        text = " ".join(str(x or "") for x in (s.get("text"), s.get("draft"), it.get("recommendation_short")))
        if ASK_CLAUDE.search(text):
            return True
        return made_by_session(it) and it.get("type") == "review" and (s.get("execute") or {}).get("kind", "none") == "none"
    return all(mine(s) for s in steps)


def spec(it):
    lines = [it.get("title", ""), it.get("context") or "", it.get("summary") or ""]
    lines += [f"Step: {s.get('text', '')}. {s.get('draft') or ''}" for s in it.get("steps") or []]
    lines.append("Do it, report the result to the owner in the session, and queue an owner item only if the result needs "
                 "something only the owner can do.")
    return "\n".join(x for x in lines if x.strip())


def sweep(area=None, dry=False):
    ts = datetime.now(TZ).isoformat(timespec="seconds")
    for f in sorted(ITEMS.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if it.get("status") not in LIVE or (area and it.get("area") != area) or not claude_work(it):
            continue
        print(f"{it['id']}: moved to the fix queue (Claude's own work)")
        if dry:
            continue
        fixes.queue(it.get("title", it["id"]), spec(it), it.get("key") or it["id"], "self_task_gate", item=it["id"],
                    not_before=it.get("snooze_until") or (it.get("due") and f"{it['due']}T09:00:00"))
        it["status"] = "done"
        it.setdefault("history", []).append({"ts": ts, "by": "self_task_gate",
                                             "event": "moved to the Claude Code fix queue: Claude's own work, not the owner's"})
        f.write_text(json.dumps(it, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sweep(args[0] if args else None, "--dry" in sys.argv)
