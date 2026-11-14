#!/usr/bin/env python3
"""Condense a week of app usage into a short brief for the UX review (no model calls).

Usage: ux_summary.py [days=7] > brief.md
Reads log/ui.jsonl (what the owner clicks, presses, opens; errors), log/actions.jsonl (what he does with items, edits,
feedback) and the queue (what was handled outside the app, i.e. missed). Reports counts and examples, not raw logs.
"""
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")


def jsonl(p):
    out = []
    for line in p.read_text().splitlines() if p.exists() else []:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def main(days=7):
    since = datetime.now(ET) - timedelta(days=days)
    iso = since.isoformat()
    ui = [e for e in jsonl(ROOT / "log" / "ui.jsonl") if e.get("ts", "") >= since.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M")]
    acts = [a for a in jsonl(ROOT / "log" / "actions.jsonl") if a.get("ts", "") >= iso]
    P = print
    P(f"# App usage, last {days} days\n")
    sessions = [e for e in ui if e["e"] == "session_start"]
    P(f"- Sessions: {len(sessions)}. UI events: {len(ui)}. Item actions: {len(acts)}.")
    P(f"- Views opened: {dict(Counter(e.get('to') for e in ui if e['e'] == 'view').most_common())}")
    P(f"- Time spent by view (event share): {dict(Counter(e.get('view') for e in ui).most_common())}")
    via = Counter((e.get("action"), e.get("via")) for e in ui if e["e"] in ("step_action", "item_action"))
    P(f"- How actions were triggered (action, via): {dict(via.most_common(20))}")
    P(f"- Palette commands: {dict(Counter(e.get('cmd') for e in ui if e['e'] == 'palette').most_common(10))}")
    P(f"- Clicked targets: {dict(Counter(e.get('target') for e in ui if e['e'] == 'click').most_common(25))}")
    P(f"- Details toggled: {sum(1 for e in ui if e['e'] == 'details')}. Ask drawer opened: {sum(1 for e in ui if e['e'] == 'drawer_open')}.")
    errs = Counter(e.get("msg") for e in ui if e["e"] == "error")
    P(f"- Errors shown: {dict(errs.most_common(10))}")
    P("\n## What the owner did with items\n")
    P(f"- Actions: {dict(Counter(a['action'] for a in acts).most_common())}")
    steps = [a for a in acts if a["action"] == "do_step" and a.get("original_draft")]
    edited = [a for a in steps if a.get("edited")]
    P(f"- Drafts sent: {len(steps)}, edited before sending: {len(edited)}.")
    for a in edited[:5]:
        P(f"  - Edited \"{(a.get('step_text') or '')[:60]}\": {len(a.get('original_draft', ''))} to {len(a.get('final_draft', ''))} chars")
    ages = [a["age_minutes"] for a in acts if a.get("age_minutes") is not None and a["action"] == "do_step"]
    if ages:
        P(f"- Minutes from item creation to sending: median {statistics.median(ages):.0f}, max {max(ages)}")
    P(f"- Done elsewhere (the app missed or was slower than the owner): {sum(1 for a in acts if a['action'] in ('done_elsewhere', 'step_done_elsewhere'))}")
    for a in [a for a in acts if a["action"] in ("done_elsewhere", "step_done_elsewhere")][:6]:
        P(f"  - \"{(a.get('title') or '')[:70]}\": {(a.get('note') or '')[:100]}")
    P(f"- Dismissed: {sum(1 for a in acts if a['action'] == 'dismiss')}; notes and redrafts: {sum(1 for a in acts if a['action'] == 'note')}")
    P("\n## Feedback given\n")
    for a in [a for a in acts if a["action"] == "feedback"][:15]:
        P(f"- [{a.get('area')}] {a.get('rating') or ''} {', '.join(a.get('tags') or [])} {(a.get('note') or '')[:140]} (job: {(a.get('made_by') or {}).get('job')})")
    learned = [a for a in acts if a.get("learned")]
    if learned:
        P("\n## Answers the owner typed when marking a call or question done\n")
        for a in learned[:15]:
            P(f"- \"{(a.get('title') or '')[:60]}\": {a['learned'][:140]}")
    P("\n## Features used\n")
    P(f"- Learn turns: {sum(1 for e in ui if e.get('target', '').startswith(('lsend', 'lcmd', 'lact')))}; Architect questions: {sum(1 for a in acts if a.get('area') == 'architect' and a['action'] in ('ask', 'followup'))}, answers copied: {sum(1 for a in acts if a.get('area') == 'architect' and a['action'] == 'copied')}")
    P(f"- Nudges: {sum(1 for a in acts if a['action'] == 'nudge')}; Revise: {sum(1 for a in acts if a['action'] == 'revise_step')}; Agent hand-offs: {sum(1 for a in acts if a['action'] == 'agent_step')}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
