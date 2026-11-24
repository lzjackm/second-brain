#!/usr/bin/env python3
"""The owner's meetings today and on the next working day, for every drafting run's prompt (Nov 23: two runs couldn't
check the calendar, so they couldn't tell a message from something to say on a call already booked; P38). Read from
state/calendar/<date>.json, which bin/calendar.sh writes each weekday morning. Code, not a calendar tool (P40).

Usage: calendar_block.py   prints a prompt section, or nothing when there is no saved calendar
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import TZ, is_owner  # noqa: E402


def days(now=None):
    now = now or datetime.now(TZ)
    nxt = now + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return [now.date(), nxt.date()]


def block(now=None, cal_dir=None):
    cal_dir = cal_dir or ROOT / "state" / "calendar"
    out = []
    for d in days(now):
        f = cal_dir / f"{d.isoformat()}.json"
        try:
            evs = json.loads(f.read_text()).get("events") or []
        except (OSError, ValueError):
            continue
        rows = []
        for e in sorted(evs, key=lambda e: e.get("start") or ""):
            when = "all day" if e.get("all_day") else (e.get("start") or "")[11:16]
            names = [(a.get("name") or a.get("email") or "") if isinstance(a, dict) else str(a) for a in e.get("attendees") or []]
            names = [n for n in names if n and not is_owner(n) and not is_owner(n.split("@")[0].replace(".", " "))]
            who = ", ".join(names[:6])
            rows.append(f"- {when} {e.get('title', '')}" + (f" (with {who})" if who else ""))
        out.append(f"{d:%A %b %-d}:\n" + ("\n".join(rows) if rows else "- nothing booked"))
    if not out:
        return ""
    return ("\n## Your calendar (ET)\nBefore drafting a message, check whether it belongs on a call already booked here "
            "(P38): then the step is a talking point for that call, not a message.\n\n" + "\n\n".join(out) + "\n")


if __name__ == "__main__":
    sys.stdout.write(block())
