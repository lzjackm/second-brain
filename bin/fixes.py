#!/usr/bin/env python3
"""The Claude Code fix queue: ~/Library/Application Support/<slug>/approved-fixes.jsonl (AGENTS.md, Approved fixes).

Interactive Claude Code sessions in this folder implement every open entry without asking (owner, Nov 21). Entries come
from the owner pressing Approve fix, from ops_report (jobs that keep failing) and from the learning run's own Fix items
and rules the owner already stated, which never reach the owner's queue (Nov 23: "same deal again").
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import press  # noqa: E402
from identity import TZ  # noqa: E402


def path():
    press._private()
    return press.PRIVATE / "approved-fixes.jsonl"


def entries():
    f = path()
    out = []
    for line in (f.read_text().splitlines() if f.exists() else []):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def queue(title, spec, key, by, item=None, summary=None, not_before=None):
    """Append once per key; returns False when it was already queued. `not_before`: an ISO time before which sessions
    leave the entry alone (a check that only makes sense after a scheduled run)."""
    if any(e.get("key") == key for e in entries()):
        return False
    with open(path(), "a") as fh:
        fh.write(json.dumps({"ts": datetime.now(TZ).isoformat(timespec="seconds"), "key": key, "item": item, "title": title,
                             "summary": summary or title, "spec": spec, "by": by,
                             **({"not_before": not_before} if not_before else {})}, ensure_ascii=False) + "\n")
    return True


def open_entries(now=None):
    """Open entries that are due: not done, and past their `not_before` if they have one."""
    now = now or datetime.now(TZ).isoformat(timespec="seconds")
    return [e for e in entries() if not e.get("done") and (e.get("not_before") or "") <= now]


if __name__ == "__main__":
    for e in open_entries():
        print(f"- {e['title']}  ({e.get('by')}, {e['ts'][:10]})")
