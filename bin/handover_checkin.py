#!/usr/bin/env python3
"""Handover check-in: every few days, one queue item that lists where each handed-over item stands, plus what else is
in flight (items waiting on someone else).

Plain code, no agent. Run daily by launchd; it creates a check-in only when the last one is at least `every_days`
old (config/handover.json). The status table is written as a report (agents/<id>/s1/REPORT.md) and linked on the
first step. An unresolved earlier check-in is marked stale when a new one replaces it.
Usage: handover_checkin.py [--dry-run] [--force]
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stale import   ET, ITEMS, current_step, parse, since

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import OWNER  # noqa: E402  (config/brain.json)
import identity  # noqa: E402
AGENTS = ROOT / "agents"
CONFIG = ROOT / "config" / "handover.json"
CLOSED = {"done", "dismissed", "stale"}
KEY = f"{identity.LEDGER_AREA}:handover-checkin:"


def load():
    out = []
    for f in sorted(ITEMS.glob("*.json")):
        try:
            out.append((f, json.loads(f.read_text())))
        except (json.JSONDecodeError, OSError):
            pass
    return out


def row(item, now):
    s = current_step(item)
    moved = since(item, s) if s else parse(item.get("updated"))
    days = (now - moved).days if moved else None
    who = "You" if s and s.get("owner") == OWNER else (s or {}).get("owner", "nobody")
    nxt = s.get("text", "") if s else "no open step"
    due = item.get("due") or ""
    flag = " **(stuck)**" if days is not None and days >= 3 or (due and due < now.date().isoformat()) else ""
    return f"| {item['title']} | {who}: {nxt} | {days if days is not None else '?'}d{flag} | {due} |"


def main(dry=False, force=False):
    cfg = json.loads(CONFIG.read_text())
    now = datetime.now(ET)
    items = load()
    prev = [(f, it) for f, it in items if it.get("key", "").startswith(KEY)]
    last = max((parse(it.get("created")) for _, it in prev), default=None)
    if last and now - last < timedelta(days=cfg["every_days"]) and not force:
        print(f"last check-in {last:%a %b %d}; next due in {cfg['every_days']} days")
        return
    prefixes = tuple(h["key_prefix"] for h in cfg["handovers"])
    handed = [it for _, it in items if it.get("key", "").startswith(prefixes) and it.get("status") not in CLOSED]
    flight = [it for _, it in items if it.get("area") == identity.LEDGER_AREA and it.get("status") in ("waiting", "working")
              and not it.get("key", "").startswith(prefixes + (KEY,))]
    if not handed and not flight:
        print("nothing handed over or in flight")
        return
    head = "| Item | Next step | Since it moved | Due |\n|---|---|---|---|"
    names = ", ".join(h["from"] for h in cfg["handovers"])
    report = [f"# Handover check-in, {now:%a %b %d}", "",
              f"## Handed over by {names} ({len(handed)} open)", "", head, *[row(i, now) for i in sorted(handed, key=lambda i: i.get('due') or '9')], "",
              f"## Other items in flight ({len(flight)})", "", head, *[row(i, now) for i in sorted(flight, key=lambda i: i.get('due') or '9')], "",
              "Stuck: no movement in 3 days or more, or past due."]
    stuck = sum("(stuck)" in r for r in report)
    iid = f"{identity.LEDGER_AREA}-{now:%Y%m%d-%H%M}-handover-checkin"
    item = {
        "id": iid, "key": f"{KEY}{now:%Y-%m-%d}", "area": identity.LEDGER_AREA, "type": "review",
        "title": f"Check in on {names}'s handover and in-flight items",
        "context": f"{len(handed)} handed-over items open, {len(flight)} others waiting on people; {stuck} stuck.",
        "recommendation_short": "Nudge owners on the stuck rows; close or snooze anything no longer yours.",
        "summary": f"Recurring check-in every {cfg['every_days']} days while {names} is out. The report lists each item's next step, who owns it and how long since it moved.",
        "why_owner": f"You cover {names}'s items while {names} is out (handoff, Nov 10) and asked for this check-in every 2 to 3 days.",
        "priority": 45 + min(stuck, 10) * 2, "priority_why": f"review 45 + {min(stuck, 10)} stuck x2",
        "due": now.date().isoformat(),
        "evidence": [{"label": "Handover status", "url": f"/report/{iid}/s1"}],
        "steps": [
            {"id": "s1", "text": "Read the status table and nudge owners on stuck rows", "owner": OWNER, "status": "todo",
             "evidence": [{"label": "Handover status", "url": f"/report/{iid}/s1"}], "execute": {"kind": "none"}},
            {"id": "s2", "text": "Close or snooze rows that no longer need you", "owner": OWNER, "status": "todo", "execute": {"kind": "none"}},
        ],
        "status": "open", "created": now.isoformat(timespec="seconds"), "updated": now.isoformat(timespec="seconds"),
        "history": [{"ts": now.isoformat(timespec="seconds"), "by": "handover-checkin", "event": "created"}],
    }
    if dry:
        print("\n".join(report))
        return
    d = AGENTS / iid / "s1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "REPORT.md").write_text("\n".join(report) + "\n")
    (ITEMS / f"{iid}.json").write_text(json.dumps(item, indent=2, ensure_ascii=False))
    for f, it in prev:
        if it.get("status") not in CLOSED:
            it["status"] = "stale"
            it.setdefault("history", []).append({"ts": item["created"], "by": "handover-checkin", "event": f"replaced by {iid}"})
            f.write_text(json.dumps(it, indent=2, ensure_ascii=False))
    print(f"created {iid}: {len(handed)} handed over, {len(flight)} in flight, {stuck} stuck")


if __name__ == "__main__":
    main("--dry-run" in sys.argv, "--force" in sys.argv)
