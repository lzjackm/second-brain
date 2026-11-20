#!/usr/bin/env python3
"""The reply gate (P26, in code): a reply item stays in the queue only while the ask is still the owner's to answer.

Every owner reply step (slack_send) records the ask it answers, read from the thread to its latest message:
  "ask": {"from": "...", "at": "ISO", "link": "...", "names_owner": true|false, "after_owner_last": true|false,
          "answered_by": ["names of anyone who answered it since"]}
An item whose ask did not name the owner, came before the owner's own last reply, or was answered by someone else is
retired (status stale, with the reason in history) instead of sitting in Needs me. Steps without `ask` are only
flagged (checks.py K12). Plain code; runs after each lead, sync and pipeline pass. Nov 16: a channel question that
three others answered, in a thread the owner had already replied to, reached Needs me.

Usage: reply_gate.py [area] [--dry]
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import TZ, is_owner  # noqa: E402

ITEMS = ROOT / "queue" / "items"
LIVE = {"open", "waiting", "working"}
PENDING = {"todo", "failed"}


OWNER_CHOSE = ("slack-saved:", "own:")


def verdict(ask):
    if not isinstance(ask, dict):
        return None
    if ask.get("answered_by"):
        return "already answered by " + ", ".join(map(str, ask["answered_by"]))[:80]
    if ask.get("after_owner_last") is False:
        return "you already replied after this ask"
    if ask.get("names_owner") is False:
        return "the ask went to the channel and didn't name you"
    return None


def sweep(area=None, dry=False):
    ts = datetime.now(TZ).isoformat(timespec="seconds")
    for f in sorted(ITEMS.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if it.get("status") not in LIVE or (area and it.get("area") != area):
            continue
        if (it.get("key") or "").startswith(OWNER_CHOSE):   # the owner made it theirs: saved in Slack, or added it
            continue
        cur = next((s for s in it.get("steps") or [] if s.get("status", "todo") in PENDING), None)
        if not cur or not is_owner(cur.get("owner")) or (cur.get("execute") or {}).get("kind") not in ("slack_send", "slack_draft"):
            continue
        why = verdict(cur.get("ask"))
        if not why:
            continue
        print(f"{it['id']}: retired ({why})")
        if dry:
            continue
        it["status"] = "stale"
        it.setdefault("history", []).append({"ts": ts, "by": "reply_gate", "event": f"retired: {why}", "step": cur["id"]})
        f.write_text(json.dumps(it, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sweep(args[0] if args else None, "--dry" in sys.argv)
