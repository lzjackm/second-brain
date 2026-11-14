#!/usr/bin/env python3
"""Start a review for every open ledger-repo PR (modules.ledger) opened by someone other than the owner that is new or
has new commits since its last review. Plain code; runs from prefetch-ledger.sh. Draft PRs wait until marked ready.
State: state/pr-reviews.json maps PR number to the head commit last reviewed.
"""
import sys
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import GITHUB_LOGINS, LEDGER_AREA  # noqa: E402  (config/brain.json)
STATE = ROOT / "state" / "pr-reviews.json"


def main():
    prs = json.loads((ROOT / "state" / "snapshots" / LEDGER_AREA / "open-prs.json").read_text())
    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    for pr in prs:
        author = pr.get("author") or {}
        if author.get("login") in GITHUB_LOGINS or author.get("is_bot") or pr.get("isDraft"):
            continue
        n, head = str(pr["number"]), pr.get("headRefOid") or ""
        if seen.get(n) == head or (ROOT / "state" / f"pr-review-{n}.lock").exists():
            continue
        subprocess.Popen([str(ROOT / "bin" / "pr-review.sh"), n, head], cwd=ROOT, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"review started: PR #{n} by {author.get('login')}")


if __name__ == "__main__":
    main()
