#!/usr/bin/env python3
"""The reply gate (P26, in code): a reply item stays in the queue only while the ask is still the owner's to answer.

Every owner reply step (slack_send) records the ask it answers, read from the thread to its latest message:
  "ask": {"from": "...", "at": "ISO", "link": "...", "names_owner": true|false, "after_owner_last": true|false,
          "answered_by": ["names of anyone who answered it since"]}
An item whose ask did not name the owner, came before the owner's own last reply, or was answered by someone else is
retired (status stale, with the reason in history) instead of sitting in Needs me. Steps without `ask` are only
flagged (checks.py K12). Plain code; runs after each lead, sync and pipeline pass. Nov 16: a channel question that
three others answered, in a thread the owner had already replied to, reached Needs me.

Nov 25, two more misses:
- The ask also records `said` (their exact words since the owner's last message) and `request` (what they asked the owner
  to do, or ""). Words with no request in them (a partner reacting to news the owner had already given)
  are not an ask, and the item is retired.
- A message the owner promised to send, with no ask behind it, records `owed`: {"promised": quote, "at", "link",
  "read_since": ISO, "called_off": [quotes], "handled_by": [names]}. It is retired when the recipient or requester called it
  off, when someone else took it over, or when the run did not read the recipient's conversation from at least 7 days
  before the promise (it missed the partner's message from the day before that called it off). A send step with neither
  record is retired from ASK_REQUIRED_SINCE.

Usage: reply_gate.py [area] [--dry]
"""
import json
import re
import sys
from datetime import timedelta
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import TZ, is_owner  # noqa: E402

ITEMS = ROOT / "queue" / "items"
LIVE = {"open", "waiting", "working"}
PENDING = {"todo", "failed"}


OWNER_CHOSE = ("slack-saved:", "own:")
ASK_REQUIRED_SINCE = "2026-11-25T12:00"   # items created from here need an ask or an owed record (Nov 25)
REQUEST = re.compile(r"\?|\b(can|could|would|will) (you|u)\b|\bplease\b|\bpls\b|\blet (me|us) know\b|\bneed (you|u|your)\b|"
                     r"\b(send|share|confirm|tell|check|sign|review|approve|update|fix)\b (me|us|it|the|this|that|over)\b|"
                     r"^\s*(what|which|when|where|who|why|how|is|are|do|does|did)\b", re.I | re.M)


def asks_something(said):
    return bool(REQUEST.search(said or ""))


def verdict(ask):
    if not isinstance(ask, dict):
        return None
    if ask.get("answered_by"):
        return "already answered by " + ", ".join(map(str, ask["answered_by"]))[:80]
    if ask.get("after_owner_last") is False:
        return "you already replied after this ask"
    if ask.get("names_owner") is False:
        return "the ask went to the channel and didn't name you"
    if "said" in ask and not (ask.get("request") or "").strip() and not asks_something(ask.get("said")):
        return "nothing was asked of you since your last reply"
    return None


def owed_verdict(owed):
    if not isinstance(owed, dict):
        return None
    if owed.get("called_off"):
        return "called off: " + str(owed["called_off"][0])[:80]
    if owed.get("handled_by"):
        return ", ".join(map(str, owed["handled_by"]))[:60] + " is handling it"
    try:
        at, since = datetime.fromisoformat(owed["at"]), datetime.fromisoformat(owed["read_since"])
    except (KeyError, TypeError, ValueError):
        return "the promise wasn't checked against the recipient's conversation"
    if since > at - timedelta(days=7):
        return "the recipient's conversation wasn't read far enough back to know it's still wanted"
    return None


def step_verdict(item, step):
    if "ask" in step:
        return verdict(step.get("ask"))
    if "owed" in step:
        return owed_verdict(step.get("owed"))
    if (item.get("created") or "") >= ASK_REQUIRED_SINCE:
        return "it records neither the ask it answers nor the promise it keeps"
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
        why = step_verdict(it, cur)
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
