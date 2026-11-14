#!/usr/bin/env python3
"""Keep the ledger area's lead off stale repo state. Plain code; runs in prefetch-ledger.sh after the snapshot of origin/main.

- pending-rows.json: rows that open ledger PRs close or rewrite (main lags until they merge).
- stale-rows.json: the repo's stale-row sweep (tools/stale_rows.py): launch rows due within 7 days that nothing has
  confirmed for 3 days, and tracked sources not reread for 2 days.
- One queue item per open digest PR: skim it, then merge it, so main does not fall days behind (Nov 13: main still
  showed five tracked docs last read Nov 7 because the digest PR holding the newer reads was unmerged).
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import identity  # noqa: E402
from identity import OWNER  # noqa: E402  (config/brain.json)
import meetings  # noqa: E402

LEDGER = Path(identity.LEDGER_PATH).expanduser()
OUT = ROOT / "state" / "snapshots" / identity.LEDGER_AREA
AREA = identity.LEDGER_AREA
ITEMS = ROOT / "queue" / "items"
ET = ZoneInfo("America/New_York")


def pending_rows():
    (OUT / "pending-rows.json").write_text(json.dumps(meetings.open_pr_changes(), indent=1, ensure_ascii=False))


def stale_rows():
    for ref in identity.LEDGER.get("tool_refs") or ["origin/main"]:  # where tools/stale_rows.py lives in the ledger repo
        src = subprocess.run(["git", "-C", str(LEDGER), "show", f"{ref}:tools/stale_rows.py"], capture_output=True, text=True)
        if src.returncode == 0:
            break
    else:
        return
    tool = ROOT / "state" / "stale_rows.py"
    tool.write_text(src.stdout)
    r = subprocess.run([sys.executable, "-I", str(tool), "--ref", "origin/main", "--json"], capture_output=True, text=True,
                       env={**os.environ, "ZPM_ROOT": str(LEDGER)})  # the ledger tool's own variable name
    if r.returncode == 0:
        (OUT / "stale-rows.json").write_text(r.stdout)


def digest_items():
    prs = json.loads((OUT / "open-prs.json").read_text())
    now = datetime.now(ET)
    ts = now.isoformat(timespec="seconds")
    for pr in prs:
        if not (pr.get("headRefName") or "").startswith("digest/") or pr.get("isDraft"):
            continue
        n = pr["number"]
        f = ITEMS / f"{AREA}-digest-pr-{n}.json"
        if f.exists():
            continue
        f.write_text(json.dumps({
            "id": f"{AREA}-digest-pr-{n}", "key": f"{AREA}:digest-pr:{n}", "area": AREA, "type": "review", "category": "review",
            "title": f"Merge the {identity.LEDGER_NAME} digest (PR #{n})",
            "context": "The repo's main branch, which every reader and agent uses, stays behind until this merges.",
            "recommendation_short": "Skim the rows added and any Unverified rows or Sources not read, then merge.",
            "why_owner": f"You own {identity.LEDGER_REPO}, and merges need your approval.",
            "priority": 65, "due": now.date().isoformat(),
            "evidence": [{"label": f"PR #{n}", "url": pr["url"]}],
            "steps": [
                {"id": "s1", "text": f"Skim digest PR #{n}", "owner": OWNER, "status": "todo",
                 "execute": {"kind": "none", "url": pr["url"], "target_label": f"PR #{n}"}},
                {"id": "s2", "text": f"Merge digest PR #{n}", "owner": OWNER, "status": "todo",
                 "execute": {"kind": "pr_merge", "target": pr["url"], "target_label": f"PR #{n}"}},
            ],
            "status": "open", "created": ts, "updated": ts,
            "made_by": {"run": "ledger_freshness", "job": "prefetch"},
            "history": [{"ts": ts, "by": "prefetch", "event": "created", "note": "open digest PR"}],
        }, indent=1, ensure_ascii=False))
        print(f"queued digest PR #{n}")


if __name__ == "__main__":
    for step in (pending_rows, stale_rows, digest_items):
        try:
            step()
        except Exception as e:  # one failed step must not stop the others or the lead
            print(f"ledger_freshness {step.__name__} failed: {e}", file=sys.stderr)
