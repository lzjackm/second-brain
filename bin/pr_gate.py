#!/usr/bin/env python3
"""Retire items that ask the owner to approve or merge a pull request they opened themselves (Nov 21).

GitHub does not let an author approve their own PR, and the owner is not the merger of PRs they open; another reviewer
is. Code, not a prompt rule: these items came from fixed code (digest PRs, Nov 13, 16 and 21) and from runs, and the
owner had to skip them by hand each time. Runs at the start of every lead run (prefetch.sh) and in the app's sweep.

Usage: pr_gate.py [area] [--dry]
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import TZ, is_owner  # noqa: E402

ITEMS = ROOT / "queue" / "items"
LIVE = {"open", "waiting", "working", "snoozed"}
PENDING = {"todo", "queued", "failed"}
GATED = {"pr_merge", "pr_approve"}
PR = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")


def gh_json(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def me():
    u = gh_json("api", "user")
    return (u or {}).get("login")


def author(repo, n):
    pr = gh_json("pr", "view", n, "-R", repo, "--json", "author")
    return ((pr or {}).get("author") or {}).get("login")


def own_pr_step(item, login, author_of=author):
    """The owner's pending approve or merge step on a PR the owner opened, if any."""
    for s in item.get("steps") or []:
        if s.get("status", "todo") not in PENDING or not is_owner(s.get("owner")):
            continue
        if (s.get("execute") or {}).get("kind") not in GATED:
            continue
        m = PR.search(" ".join(str(x) for x in ((s.get("execute") or {}).get("target"), (s.get("execute") or {}).get("url"))))
        if m and login and author_of(m.group(1), m.group(2)) == login:
            return s
    return None


def sweep(area=None, dry=False, login=None, author_of=author):
    login = login or me()
    if not login:
        return
    ts = datetime.now(TZ).isoformat(timespec="seconds")
    for f in sorted(ITEMS.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if it.get("status") not in LIVE or (area and it.get("area") != area):
            continue
        s = own_pr_step(it, login, author_of)
        if not s:
            continue
        print(f"{it['id']}: retired (your own PR: someone else approves and merges it)")
        if dry:
            continue
        it["status"] = "stale"
        it.setdefault("history", []).append({"ts": ts, "by": "pr_gate", "event": "retired: you opened this PR; another reviewer approves and merges it", "step": s.get("id")})
        f.write_text(json.dumps(it, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sweep(args[0] if args else None, "--dry" in sys.argv)
