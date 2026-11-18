#!/usr/bin/env python3
"""Which open items a sync run checks, so quiet items aren't re-read every 30 minutes.

Each item backs off while nothing happens: checked every run (30 min) while active, every hour after 2 quiet checks,
every 2 hours after 4. Any activity resets it: a sync change, the owner acting, a lead edit, a new item.
State per item lives in state/sync-due-<area>.json: the history length and synced_at seen last time, and how many
checks in a row found nothing. Nov 18: sync ran 20 times a day at about $2, re-reading every thread; about 6 in 10
runs changed nothing.

Usage: sync_due.py <area>   prints the due item ids, one per line (none: the run is skipped)
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import TZ  # noqa: E402

LIVE = {"open", "waiting", "working"}
STEPS = [(4, timedelta(hours=2)), (2, timedelta(hours=1)), (0, timedelta(minutes=25))]   # quiet checks -> interval


def parse(ts):
    try:
        d = datetime.fromisoformat(ts)
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    except (TypeError, ValueError):
        return None


def due(area, now=None, items_dir=None, state_file=None):
    now = now or datetime.now(TZ)
    items_dir = items_dir or ROOT / "queue" / "items"
    state_file = state_file or ROOT / "state" / f"sync-due-{area}.json"
    try:
        seen = json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError):
        seen = {}
    out, new = [], {}
    for f in sorted(items_dir.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if it.get("area") != area or it.get("status") not in LIVE or it.get("type") == "meeting":
            continue
        hist = it.get("history") or []
        prev = seen.get(it["id"], {})
        quiet = prev.get("quiet", 0)
        if prev and it.get("synced_at") != prev.get("synced_at"):          # a sync visited since last time
            grew = hist[prev.get("hist", 0):]
            quiet = 0 if grew else quiet + 1                                  # it (or anyone) changed something?
        elif prev and len(hist) > prev.get("hist", 0):
            quiet = 0                                                         # activity outside sync (owner, lead)
        last = parse(it.get("synced_at"))
        wait = next(w for n, w in STEPS if quiet >= n)
        if not last or now - last >= wait:
            out.append(it["id"])
        new[it["id"]] = {"hist": len(hist), "synced_at": it.get("synced_at"), "quiet": quiet}
    state_file.write_text(json.dumps(new, indent=1))
    return out


if __name__ == "__main__":
    print("\n".join(due(sys.argv[1])))
