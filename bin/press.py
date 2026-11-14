#!/usr/bin/env python3
"""The owner's presses: the only thing that lets the executor act.

When the owner presses a step's action in the app, the server records a fingerprint of exactly what that press
covers (the item, the step, its execute target and its draft). The executor runs a queued step only when the latest
press for it matches the step as it is now: a step queued by anything else (a lead, a meeting debrief, a hand edit),
or changed after the press, is refused.

Records live outside the repo (PRIVATE, default ~/Library/Application Support/<slug>), where no run's tools can
write. Also kept there: recipients the owner has already sent to, so the app can flag a first send to a new one.
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from identity import SLUG, TZ  # noqa: E402

PRIVATE = Path(os.environ.get("BRAIN_PRIVATE") or Path.home() / "Library" / "Application Support" / SLUG)
PRESSES = PRIVATE / "presses.jsonl"
RECIPIENTS = PRIVATE / "recipients.json"
# Fields of `execute` that only describe the step for people; everything else decides what happens.
DESCRIPTIVE = {"target_label", "notes", "medium_why"}
SLACK_TARGET = re.compile(r"^(?:DM\s+)?([CDGU][A-Z0-9]{6,})(?:\s+thread_ts\s+(\d{6,}\.\d{1,9}))?\s*$")


def _private():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    os.chmod(PRIVATE, 0o700)


def fingerprint(item_id, step):
    ex = {k: v for k, v in (step.get("execute") or {}).items() if k not in DESCRIPTIVE}
    blob = json.dumps({"item": item_id, "step": step.get("id"), "execute": ex, "draft": step.get("draft") or "",
                       "text": step.get("text") or ""},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def record(item_id, step):
    _private()
    rec = {"ts": datetime.now(TZ).isoformat(timespec="seconds"), "item": item_id, "step": step.get("id"),
           "fp": fingerprint(item_id, step)}
    fd = os.open(PRESSES, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def latest(item_id, step_id):
    last = None
    for line in (PRESSES.read_text().splitlines() if PRESSES.exists() else []):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("item") == item_id and r.get("step") == step_id:
            last = r
    return last


def pressed(item_id, step):
    """True when the owner's latest press on this step covers it exactly as it is now."""
    r = latest(item_id, step.get("id"))
    return bool(r) and r.get("fp") == fingerprint(item_id, step)


def slack_target(target):
    """(channel, thread_ts) from a slack_send target, or None when it is not a plain ID."""
    m = SLACK_TARGET.match((target or "").strip())
    return (m.group(1), m.group(2)) if m else None


def known_recipients():
    try:
        return set(json.loads(RECIPIENTS.read_text()))
    except (OSError, json.JSONDecodeError):
        return set()


def add_recipient(channel):
    _private()
    known = known_recipients() | {channel}
    RECIPIENTS.write_text(json.dumps(sorted(known)))
    os.chmod(RECIPIENTS, 0o600)


def new_recipient(item, step):
    """A Slack send to a channel or person the owner has never sent to from the app, and that none of the item's
    sources mention: the app asks for a second confirmation before it goes."""
    ex = step.get("execute") or {}
    if ex.get("kind") not in ("slack_send", "slack_draft"):
        return False
    t = slack_target(ex.get("target"))
    if not t:
        return False
    seen = json.dumps([item.get("evidence"), [s.get("evidence") for s in item.get("steps") or []]])
    return t[0] not in known_recipients() and t[0] not in seen
