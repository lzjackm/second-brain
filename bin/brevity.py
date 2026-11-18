#!/usr/bin/env python3
"""Enforce the S10/S16 writing limits in code, so the owner never has to repeat them (Nov 13: "way too much text").

Finds open items that break a limit and sends each back with a redraft note the lead (or reviser) must follow:
- context over 25 words; recommendation or recommendation_short over 18 words; why_owner over 18 words;
- item evidence with more than 2 sources (only the ask belongs there; research goes on steps);
- a title that still names a finished step (most of its words match a done step's text) while steps remain open.
An item is sent back at most once a day, so a run that misses again doesn't loop. Plain code; runs in prefetch.

Usage: brevity.py [area] [--dry]
"""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "queue" / "items"
ET = ZoneInfo("America/New_York")
LIVE = {"open", "waiting", "working", "snoozed"}
PENDING = {"todo", "queued", "failed"}
TAG = "[brevity]"


def words(t):
    return len(re.findall(r"\S+", t or ""))


def wordset(t):
    return set(re.findall(r"[a-z0-9']+", (t or "").lower())) - {"the", "a", "an", "and", "to", "of", "on", "for", "with", "as", "in"}


def problems(item):
    out = []
    if words(item.get("context")) > 25:
        out.append(f"context is {words(item.get('context'))} words; one sentence, at most 20")
    for f in ("recommendation_short", "recommendation"):
        if words(item.get(f)) > 18:
            out.append(f"{f} is {words(item.get(f))} words; the owner's next move only, at most 15, no figures or caveats")
    if words(item.get("why_owner")) > 18:
        out.append("why_owner over 12 words")
    if len(item.get("evidence") or []) > 2:
        out.append(f"{len(item['evidence'])} item sources; keep only the message(s) that make this an action item, move research to step evidence")
    steps = item.get("steps") or []
    for s in steps:  # The owner's pending Slack drafts: one line, a table, at most a closing line
        if s.get("status", "todo") in PENDING and (s.get("execute") or {}).get("kind") in ("slack_send", "slack_draft"):
            draft = s.get("draft") or ""
            pipes = [l for l in draft.splitlines() if re.match(r"^\s*\|.*\|\s*$", l)]
            if "```" in draft:
                out.append(f"step {s['id']} draft has a code block; a table goes as a pipe table in its own message (S17)")
            if any("\t" in l for l in draft.splitlines()):
                out.append(f"step {s['id']} draft has a tab-separated table; sent by the app it shows as spaced text, use a pipe table in its own message (S17)")
            if pipes and len(pipes) < len([l for l in draft.splitlines() if l.strip()]):
                out.append(f"step {s['id']} draft mixes a table with text; the table renders only on its own, split the lead-in into a separate step (S17)")
            prose = [l for l in draft.splitlines() if l.strip() and l not in pipes]
            if len(prose) > 5:
                out.append(f"step {s['id']} draft has {len(prose)} lines of prose outside any table; at most 5, figures as a table")
    for s in steps:   # text the owner reads must be plain words, not an agent's spec (Nov 18: a K9/K12 code spec as the draft)
        if s.get("status", "todo") in PENDING and (s.get("execute") or {}).get("kind", "none") in ("none", "approve_fix"):
            d = s.get("draft") or ""
            code = len(re.findall(r"`[^`]+`|\\b|\b[\w/-]+\.(?:py|json|md|sh|zsh|html)\b|\b[a-z]+_[a-z_]+\b|\bK\d{1,2}\b|\[[^\]]*\|[^\]]*\]", d))
            if code >= 4:
                out.append(f"step {s['id']} draft reads like an agent spec ({code} code terms); write at most three plain lines for the owner and move the detail to the step's `spec`")
    if any(s.get("status", "todo") in PENDING for s in steps):
        t = wordset(item.get("title"))
        for s in steps:
            if s.get("status") in ("done", "done_elsewhere", "skipped") and t:
                d = wordset(s.get("text"))
                if d and len(t & d) >= 0.6 * len(t):
                    out.append(f"title still describes the finished step \"{s.get('text')}\"; retitle to the open work")
                    break
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    area, dry = (args[0] if args else None), "--dry" in sys.argv
    now = datetime.now(ET)
    ts = now.isoformat(timespec="seconds")
    sent = 0
    for f in sorted(ITEMS.glob("*.json")):
        try:
            item = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if item.get("status") not in LIVE or item.get("type") == "meeting" or (area and item.get("area") != area):
            continue
        found = problems(item)
        if not found:
            continue
        recent = [n for n in item.get("notes") or [] if (n.get("text") or "").startswith(TAG)
                  and (n.get("ts") or "") > (now - timedelta(days=1)).isoformat()]
        print(f"{item['id']}: " + "; ".join(found) + (" (sent back in the last day)" if recent else ""))
        if recent or dry:
            continue
        item.setdefault("notes", []).append({"ts": ts, "action": "note", "redraft": True, "by": "brevity",
                                             "text": f"{TAG} Fix to brain/style.md S10 and S16, changing nothing else: " + "; ".join(found) + "."})
        item["redraft_requested"] = ts
        item.setdefault("history", []).append({"ts": ts, "by": "brevity", "event": "sent back for S10/S16 limits"})
        f.write_text(json.dumps(item, indent=1, ensure_ascii=False))
        sent += 1
    print(f"sent back {sent}")


if __name__ == "__main__":
    main()
