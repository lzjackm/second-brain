#!/usr/bin/env python3
"""Keep the ledger area's lead off stale repo state. Plain code; runs in prefetch-ledger.sh after the snapshot of origin/main.

- pending-rows.json: rows that open ledger PRs close or rewrite (main lags until they merge).
- stale-rows.json: the repo's stale-row sweep (tools/stale_rows.py): launch rows due within 7 days that nothing has
  confirmed for 3 days, and tracked sources not reread for 2 days.
- source alert: one queue item, due today, when the daily pull has not read a tracked source for ALERT_DAYS or more,
  read from the open digest PR's branch (main lags while it is open). Closed again once every source is read.
  Nov 24: six Claude Docs went unread for 10 days and the only signal was a line in each PR body and the synopsis.
No queue items for digest PRs: the owner opens them and is not their approver or merger (Nov 13, 16 and 21).
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import identity  # noqa: E402
import meetings  # noqa: E402

LEDGER = Path(identity.LEDGER_PATH).expanduser()
OUT = ROOT / "state" / "snapshots" / identity.LEDGER_AREA
AREA = identity.LEDGER_AREA
ITEMS = ROOT / "queue" / "items"
ALERT_DAYS = 2
ALERT_KEY = f"{AREA}:source-alert"
CLOSED = {"done", "dismissed", "stale"}


def pending_rows():
    (OUT / "pending-rows.json").write_text(json.dumps(meetings.open_pr_changes(), indent=1, ensure_ascii=False))


def tool_path():
    for ref in identity.LEDGER.get("tool_refs") or ["origin/main"]:  # where tools/stale_rows.py lives in the ledger repo
        src = subprocess.run(["git", "-C", str(LEDGER), "show", f"{ref}:tools/stale_rows.py"], capture_output=True, text=True)
        if src.returncode == 0:
            tool = ROOT / "state" / "stale_rows.py"
            tool.write_text(src.stdout)
            return tool
    return None


def newest_digest_ref():
    """The open digest PR's branch, from the open-PR snapshot prefetch writes; main when none is open.
    Squash-merged digest branches stay on the remote, so the newest digest/ branch is not necessarily open."""
    try:
        prs = json.loads((OUT / "open-prs.json").read_text())
    except (OSError, ValueError):
        prs = []
    open_digest = sorted((p for p in prs if str(p.get("headRefName", "")).startswith("digest/")), key=lambda p: p.get("number", 0))
    return f"origin/{open_digest[-1]['headRefName']}" if open_digest else "origin/main"


def late_sources(ref, today=None):
    """Tracked sources the pull has not read for ALERT_DAYS or more, as of the given ref's state.json."""
    tool = tool_path()
    if not tool:
        return None
    args = [sys.executable, "-I", str(tool), "--ref", ref, "--json", "--source-days", str(ALERT_DAYS)]
    if today:
        args += ["--today", today]
    r = subprocess.run(args, capture_output=True, text=True, env={**os.environ, "ZPM_ROOT": str(LEDGER)})
    if r.returncode:
        return None
    try:
        kinds = json.loads(subprocess.run(["git", "-C", str(LEDGER), "show", f"{ref}:sources/artifacts/state.json"],
                                          capture_output=True, text=True).stdout or "{}")
    except json.JSONDecodeError:
        kinds = {}
    out = json.loads(r.stdout).get("sources", [])
    for s in out:
        s["kind"] = (kinds.get(s["source"]) or {}).get("kind", "")
    return out


def source_alert(now=None, items_dir=None, late=None):
    """Open, refresh or close the one source-alert item. Plain code; the owner sees it in Needs me."""
    now = now or datetime.now().astimezone()
    items_dir = items_dir or ITEMS
    ref = None
    if late is None:
        ref = newest_digest_ref()
        late = late_sources(ref)
        if late is None:
            return
    current = None
    for f in sorted(items_dir.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if it.get("key") == ALERT_KEY and it.get("status") not in CLOSED:
            current = (f, it)
    ts = now.isoformat(timespec="seconds")
    if not late:
        if current:
            f, it = current
            it["status"] = "done"
            for s in it.get("steps", []):
                s["status"] = "done"
            it["updated"] = ts
            it.setdefault("history", []).append({"ts": ts, "by": "ledger-freshness", "event": "every tracked source read again"})
            f.write_text(json.dumps(it, indent=2, ensure_ascii=False))
        return
    oldest = max(s["days"] for s in late)
    names = ", ".join(s["source"].removesuffix(".md") for s in sorted(late, key=lambda s: -s["days"]))
    kinds = sorted({s["kind"] for s in late if s["kind"]})
    fix = (f"Reconnect Claude Docs for the {identity.LEDGER_NAME} daily ingest routine, then run it once by hand"
           if kinds == ["claude-doc"] else "Restore the pull's access to these sources, then run it once by hand")
    body = {
        "key": ALERT_KEY, "area": AREA, "type": "action",
        "title": f"Daily pull can't read {len(late)} source{'s' if len(late) > 1 else ''} ({oldest} days)",
        "context": f"The {identity.LEDGER_NAME} pull has not read {names} for up to {oldest} days; their statuses are going stale.",
        "recommendation_short": fix + ".",
        "why_owner": "You asked (Nov 24) for an alert whenever the daily pull cannot read a tracked source.",
        "evidence": [{"label": "Read dates per source (state.json)", "url": f"{identity.LEDGER.get('url', '').rstrip('/')}/blob/main/sources/artifacts/state.json"}],
        "priority": 70 + min(oldest, 15), "priority_why": f"broken source 70 + {min(oldest, 15)} days unread",
        "due": now.date().isoformat(),
        "summary": "From tools/stale_rows.py on " + (ref or "the digest branch") + ": " +
                   "; ".join(f"{s['source']} ({s['kind'] or 'source'}), last read {s['last_read']}" for s in late),
        "updated": ts,
    }
    if current:
        f, it = current
        it.update(body)
        it.setdefault("history", []).append({"ts": ts, "by": "ledger-freshness", "event": f"refreshed: {len(late)} unread, oldest {oldest} days"})
    else:
        iid = f"{AREA}-{now:%Y%m%d-%H%M}-source-alert"
        f = items_dir / f"{iid}.json"
        it = {"id": iid, **body, "status": "open", "created": ts,
              "steps": [{"id": "s1", "text": fix, "owner": identity.OWNER, "status": "todo", "execute": {"kind": "none"}}],
              "history": [{"ts": ts, "by": "ledger-freshness", "event": "created"}]}
    f.write_text(json.dumps(it, indent=2, ensure_ascii=False))


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


if __name__ == "__main__":
    for step in (pending_rows, stale_rows, source_alert):
        try:
            step()
        except Exception as e:  # one failed step must not stop the others or the lead
            print(f"ledger_freshness {step.__name__} failed: {e}", file=sys.stderr)
