#!/usr/bin/env python3
"""Stale items: things that need the owner, or that the owner is waiting on, and have sat too long.

An item is stale when its current step (the owner's, or someone else's he is waiting on) has not moved:
- if the item has a target date (`due`), from that date;
- otherwise 3 days after the step became current (created, the previous step resolved, or unsnoozed/reopened).

Used two ways:
- the app imports `stale_info` to tag items ("Yours for 4d", "No reply in 4d");
- run hourly by launchd, it sends a macOS notification for newly stale items, and again every 3 days while they stay stale.
  `--dry-run` prints what it would send.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import SLUG  # noqa: E402
ITEMS = ROOT / "queue" / "items"
SENT = ROOT / "state" / "stale-notified.json"
CONFIG = ROOT / "config" / "notify.json"
ET = ZoneInfo("America/New_York")
_cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
STALE_DAYS = _cfg.get("stale_days", 3)
REMIND_DAYS = _cfg.get("remind_days", 3)
INCLUDE_WAITING = _cfg.get("include_waiting", True)
QUIET = tuple(_cfg.get("quiet_hours", [20, 9]))  # no notifications from 8 PM to 9 AM ET
PENDING = {"todo", "queued", "failed"}
APP = "http://127.0.0.1:" + ((Path(__file__).resolve().parent.parent / "state" / "app.port").read_text().strip() if (Path(__file__).resolve().parent.parent / "state" / "app.port").exists() else "7878")


def parse(ts):
    try:
        t = datetime.fromisoformat(ts)
        return t if t.tzinfo else t.replace(tzinfo=ET)
    except (TypeError, ValueError):
        return None


def current_step(item):
    return next((s for s in item.get("steps") or [] if s.get("status", "todo") in PENDING), None)


def since(item, step):
    """When the current step became current: the latest of created, an earlier step resolving, unsnooze, reopen, or the owner handing it to someone."""
    steps = item.get("steps") or []
    before = steps[:steps.index(step)] if step in steps else []
    times = [parse(item.get("created"))]
    times += [parse(s.get("done_at")) for s in before]
    times += [parse(h.get("ts")) for h in item.get("history") or []
              if h.get("event") in ("unsnoozed", "reopen", "waiting", "take_back")]
    times = [t for t in times if t]
    return max(times) if times else None


def stale_info(item, now=None):
    """None, or {kind: mine|waiting, owner, step, since, stale_at, days, reason, label}."""
    if item.get("status") not in ("open", "waiting") or item.get("type") == "meeting":
        return None  # meetings are worked on the Meetings page, not chased
    step = current_step(item)
    if not step:
        return None
    now = now or datetime.now(ET)
    owner = step.get("owner") or ""
    mine = item.get("status") == "open"
    if not mine and owner.strip().lower() in ("lead", "agent"):
        return None  # the brain's own steps; it reports on those itself
    start = since(item, step)
    if item.get("due"):
        try:
            stale_at = datetime.fromisoformat(item["due"]).replace(hour=9, tzinfo=ET)
        except ValueError:
            return None
        if start and start.date() >= stale_at.date():
            stale_at = start + timedelta(days=1)  # handed over on or after the target: give it a day
        reason = "due " + datetime.fromisoformat(item["due"]).strftime("%b %-d")
    elif start:
        stale_at = start + timedelta(days=STALE_DAYS)
        reason = f"no movement in {STALE_DAYS} days"
    else:
        return None
    if now < stale_at:
        return None
    days = (now - start).days if start else 0
    who = short(owner)
    label = (f"Yours for {days}d" if mine else f"No reply in {days}d") if not item.get("due") else ("Past target" if mine else f"{who} past target")
    return {"kind": "mine" if mine else "waiting", "owner": owner, "step": step.get("id"),
            "since": start.isoformat(timespec="seconds") if start else None,
            "stale_at": stale_at.isoformat(timespec="seconds"), "days": days, "reason": reason, "label": label}


def short(owner):
    """First name for a person ("Sam Lee" -> "Sam"); a group or company stays whole ("Design and the support team")."""
    w = (owner or "them").split()
    return w[0] if len(w) == 2 and w[1][:1].isupper() else (owner or "them")


def load():
    out = []
    for f in sorted(ITEMS.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    return out


def line(item, info):
    title = item.get("title", "")[:70]
    if info["kind"] == "mine":
        return f"Yours, {info['reason']}: {title}"
    return f"Waiting on {short(info['owner'])}, {info['reason']}: {title}"


def notify(title, body, url):
    tn = shutil.which("terminal-notifier") or ("/opt/homebrew/bin/terminal-notifier" if Path("/opt/homebrew/bin/terminal-notifier").exists() else None)
    if tn:
        subprocess.run([tn, "-title", title, "-message", body, "-open", url, "-group", f"{SLUG}-stale", "-sound", "default"], check=False)
    else:
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}" sound name "default"'], check=False)


def main():
    dry = "--dry-run" in sys.argv
    now = datetime.now(ET)
    sent = json.loads(SENT.read_text()) if SENT.exists() else {}
    stale = [(i, s) for i in load() if (s := stale_info(i, now)) and (INCLUDE_WAITING or s["kind"] == "mine")]
    due = []
    for item, info in stale:
        prev = sent.get(item["id"])
        fresh = not prev or prev.get("step") != info["step"]
        if fresh or (parse(prev.get("ts")) or now) <= now - timedelta(days=REMIND_DAYS):
            due.append((item, info))
    # Forget items that are no longer stale, so they notify again if they go stale later.
    live = {i["id"] for i, _ in stale}
    sent = {k: v for k, v in sent.items() if k in live}
    if dry:
        for item, info in stale:
            print(("SEND " if (item, info) in due else "sent ") + line(item, info))
        return
    quiet = now.hour >= QUIET[0] or now.hour < QUIET[1]
    if due and not quiet:
        mine = sum(1 for _, s in due if s["kind"] == "mine")
        title = f"{len(due)} stale item{'s' if len(due) > 1 else ''}" + (f" ({mine} yours)" if mine else "")
        body = "\n".join(line(i, s) for i, s in due[:3]) + (f"\n+{len(due) - 3} more" if len(due) > 3 else "")
        view = "queue" if mine else "waiting"
        notify(title if len(due) > 1 else ("Needs you" if mine else "Waiting too long"), body if len(due) > 1 else line(*due[0]),
               f"{APP}/#{view}" if len(due) > 1 else f"{APP}/#item={due[0][0]['id']}")
        for item, info in due:
            sent[item["id"]] = {"step": info["step"], "ts": now.isoformat(timespec="seconds")}
        with (ROOT / "log" / "notify.jsonl").open("a") as f:
            f.write(json.dumps({"ts": now.isoformat(timespec="seconds"), "kind": "stale", "items": [i["id"] for i, _ in due]}) + "\n")
    SENT.parent.mkdir(exist_ok=True)
    SENT.write_text(json.dumps(sent, indent=1))


if __name__ == "__main__":
    main()
