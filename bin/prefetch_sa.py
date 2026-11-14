#!/usr/bin/env python3
"""Read-only snapshot of every source the Solutions Architect searches (modules.architect.sources in config/brain.json),
exported with `git archive` so no working tree is ever checked out or changed. Skips if the snapshot is under an hour
old unless --force. Writes state/snapshots/sa/MANIFEST.md with each source's ref, commit and the authority order.

Each source: {"dest": folder name, "repo": local clone, "ref": "origin/main", "paths": [...],
              "dirs_matching": optional regex of extra directories to include (e.g. "^crates/.*/adrs$")}.
modules.architect.authority lists the folders highest authority first, one line each.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from identity import CFG, TZ  # noqa: E402

OUT = ROOT / "state" / "snapshots" / "sa"
KEEP = {".md", ".mdx", ".json", ".yaml", ".yml", ".txt"}


def git(repo, *args, binary=False):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    return r.stdout if binary else r.stdout.decode().strip()


def main():
    mod = (CFG.get("modules") or {}).get("architect") or {}
    sources = mod.get("sources") or []
    man = OUT / "MANIFEST.md"
    if "--force" not in sys.argv and man.exists() and time.time() - man.stat().st_mtime < 3600:
        print("sa snapshot fresh")
        return
    tmp = OUT.with_suffix(".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    rows = []
    for s in sources:
        repo, ref, dest = os.path.expanduser(s["repo"]), s.get("ref", "origin/main"), s["dest"]
        if not Path(repo, ".git").exists():
            print(f"warn: {repo} is not a git clone, skipped", file=sys.stderr)
            continue
        if subprocess.run(["git", "-C", repo, "fetch", "-q", "origin"], capture_output=True).returncode:
            print(f"warn: fetch {repo} failed, using local refs", file=sys.stderr)
        paths = list(s.get("paths") or [])
        if s.get("dirs_matching"):
            rx = re.compile(s["dirs_matching"])
            paths += [d for d in git(repo, "ls-tree", "-d", "-r", "--name-only", ref).splitlines() if rx.search(d)]
        (tmp / dest).mkdir(parents=True, exist_ok=True)
        for p in paths or ["."]:
            data = git(repo, "archive", ref, "--", p, binary=True)
            if data:
                with tarfile.open(fileobj=io.BytesIO(data)) as t:
                    t.extractall(tmp / dest, filter="data")
        rows.append(f"| {dest} | {s['repo']} @ {ref} {git(repo, 'rev-parse', '--short', ref)} ({git(repo, 'log', '-1', '--format=%cs', ref)}) |")
    for f in tmp.rglob("*"):
        if f.is_file() and f.suffix not in KEEP:
            f.unlink()
    auth = mod.get("authority") or [f"`{s['dest']}/`" for s in sources]
    man_text = (f"# Solutions Architect sources ({datetime.now(TZ):%Y-%m-%d %H:%M %Z})\n\n| Folder | Source |\n|---|---|\n"
                + "\n".join(rows) + "\n\n## Authority (highest first)\n" + "\n".join(f"{n}. {a}" for n, a in enumerate(auth, 1)) + "\n")
    (tmp / "MANIFEST.md").write_text(man_text)
    shutil.rmtree(OUT, ignore_errors=True)
    tmp.rename(OUT)
    n = sum(1 for f in OUT.rglob("*") if f.is_file())
    print(f"sa snapshot: {n} files from {len(rows)} sources")


if __name__ == "__main__":
    main()
