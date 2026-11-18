#!/usr/bin/env python3
"""One-page review of the pipeline with the lead as editor, against the week before it.

Counts, per source of new items: items created, acted on by the owner, dismissed or stale; the editor's proposal
decisions (kept, merged, dropped); coverage gaps the editor caught that the scout missed; and run cost.
Usage: pipeline_review.py <area> <start YYYY-MM-DD> [days=7]
"""
import collections
import glob
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import OWNER_NAMES  # noqa: E402


def window(start, days):
    return start.isoformat(), (start + timedelta(days=days)).isoformat()


def items(area, lo, hi):
    out = collections.defaultdict(collections.Counter)
    gaps = 0
    for f in glob.glob(str(ROOT / "queue/items/*.json")):
        it = json.load(open(f))
        if it.get("area") != area or not (lo <= (it.get("created") or "") < hi) or it.get("type") == "meeting":
            continue
        h = [x for x in it.get("history", []) if "created" in str(x.get("event", ""))]
        by = (h[0].get("by") if h else "") or ""
        src = "editor" if by.startswith("editor") else "lead" if by.startswith("lead") else "specialists" if by.startswith("specialist") else "other"
        gaps += any(x.get("coverage_gap") for x in it.get("history", []))
        acted = any(s.get("done_by") in OWNER_NAMES | {"executor"} or s.get("status") == "done_elsewhere" for s in it.get("steps", []))
        o = "dismissed/stale" if it.get("status") in ("dismissed", "stale") else "acted on" if acted else "open/other"
        out[src][o] += 1
        out[src]["total"] += 1
    return out, gaps


def cost(lo, hi):
    c = collections.Counter()
    for line in open(ROOT / "log/usage.jsonl"):
        r = json.loads(line)
        if lo <= r.get("ts", "") < hi:
            j = r.get("job", "")
            c["specialists" if j.startswith("specialist") else j] += float(r.get("cost_usd") or 0)
    return c


def main():
    area, start = sys.argv[1], date.fromisoformat(sys.argv[2])
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
    for label, s in (("before", start - timedelta(days=days)), ("after", start)):
        lo, hi = window(s, days)
        it, gaps = items(area, lo, hi)
        c = cost(lo, hi)
        print(f"== {label}: {lo} to {hi}")
        for src, v in sorted(it.items()):
            print(f"  {src:12} {dict(v)}")
        ingest = sum(c[k] for k in ("lead", "edit", "scout", "specialists"))
        print(f"  ingest cost ${ingest:.2f} (lead {c['lead']:.2f}, editor {c['edit']:.2f}, scout {c['scout']:.2f}, specialists {c['specialists']:.2f}); sync ${c['sync']:.2f}; coverage gaps caught {gaps}")
    dec = collections.Counter()
    for f in glob.glob(str(ROOT / "state/proposals/*/decisions.jsonl")):
        for line in open(f):
            dec[json.loads(line).get("decision")] += 1
    print("proposals:", dict(dec))


if __name__ == "__main__":
    main()
