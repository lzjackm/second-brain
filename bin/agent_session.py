#!/usr/bin/env python3
"""The conversation between the owner and the research agent on one step (the app's Talk panel).

agents/<item>/<step>/talk.jsonl holds it, one message per line: {"ts", "role": "brief" | OWNER | "agent", "text"}.
agents/<item>/<step>/session.json holds the agent's Claude session id, so a reply resumes the same run with everything
it already read, and the last log recorded.

Usage:
  agent_session.py record <item> <step>    after a run: save its session id and its final answer as the agent's message
  agent_session.py pending <item> <step>   print the owner's messages since the agent last answered; exit 1 if none
  agent_session.py session <item> <step>   print the session id to resume; exit 1 if none
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import OWNER  # noqa: E402  (config/brain.json)
ET = ZoneInfo("America/New_York")


def folder(item, step):
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}", x or "") for x in (item, step)):
        raise ValueError("bad item or step id")
    return ROOT / "agents" / item / step


def messages(item, step):
    f = folder(item, step) / "talk.jsonl"
    out = []
    for line in (f.read_text().splitlines() if f.exists() else []):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def append(item, step, role, text, report=False):
    d = folder(item, step)
    d.mkdir(parents=True, exist_ok=True)
    m = {"ts": datetime.now(ET).isoformat(timespec="seconds"), "role": role, "text": text, **({"report": True} if report else {})}
    with (d / "talk.jsonl").open("a") as fh:
        fh.write(json.dumps(m, ensure_ascii=False) + "\n")


def pending(item, step):
    """the owner's messages after the agent's last answer (the brief counts as answered once the first run has spoken)."""
    msgs = messages(item, step)
    last = max((n for n, m in enumerate(msgs) if m.get("role") == "agent"), default=None)
    if last is None:
        return []
    return [m for m in msgs[last + 1:] if m.get("role") == OWNER]


def session(item, step):
    f = folder(item, step) / "session.json"
    return json.loads(f.read_text()).get("session_id") if f.exists() else None


def record(item, step):
    cur = ROOT / "state" / f"agent-{item}.current"
    if not cur.exists():
        return
    log = Path(cur.read_text().strip())
    sf = folder(item, step) / "session.json"
    prev = json.loads(sf.read_text()) if sf.exists() else {}
    if prev.get("last_log") == str(log):
        return  # this run is already recorded
    report = folder(item, step) / "REPORT.md"
    rmtime = report.stat().st_mtime if report.exists() else None
    sid, result = None, None
    trace = Path(str(log) + ".trace.jsonl")
    for line in (trace.read_text().splitlines() if trace.exists() else []):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            sid = ev.get("session_id") or sid
        if ev.get("type") == "result":
            result = ev.get("result")
            sid = ev.get("session_id") or sid
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps({"session_id": sid or prev.get("session_id"), "last_log": str(log), "report_mtime": rmtime,
                              "updated": datetime.now(ET).isoformat(timespec="seconds")}, indent=1))
    append(item, step, "agent", (result or (log.read_text().strip() if log.exists() else "") or "The run ended without an answer.").strip(),
           report=bool(rmtime and rmtime != prev.get("report_mtime")))


def backfill(item, step, brief, ts=None):
    """A step whose agent ran before Talk existed has no conversation: start it from the brief and the report, so a
    reply continues that work instead of restarting it."""
    if messages(item, step):
        return
    report = folder(item, step) / "REPORT.md"
    if brief:
        append(item, step, "brief", brief)
    if report.exists():
        append(item, step, "agent", report.read_text().strip().split("\n")[0][:600], report=True)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("record", "pending", "session"):
        sys.exit(__doc__)
    cmd, item, step = sys.argv[1:]
    if cmd == "record":
        record(item, step)
    elif cmd == "pending":
        p = pending(item, step)
        if not p:
            sys.exit(1)
        print("\n\n".join(m["text"] for m in p))
    else:
        s = session(item, step)
        if not s:
            sys.exit(1)
        print(s)
