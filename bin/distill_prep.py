#!/usr/bin/env python3
"""Prepare distill's input in code, and advance its cursor only after a run that finished.

prepare: writes state/distill/input.md with
  1. queue actions logged after the cursor (state/distill.last_run), oldest first, at most MAX_ACTIONS;
  2. feedback memories from Claude Code sessions that are new or changed since distill last saw them,
     at most MAX_MEMORIES (corrections the owner makes in interactive sessions, which the queue log never sees);
  3. what runs could not read (steps' basis.not_read) on items changed since the cursor, plus sources
     missed on two or more items across the whole queue.
  and state/distill/pending.json (the cursor and memory hashes to save once the run succeeds).
  Exit 0 with work to do, 3 with nothing new (the caller skips the model run).
commit <run log>: if the run's result is not an error, saves the pending cursor and memory hashes.
  A timed-out or failed run leaves the cursor where it was, so nothing is skipped and the next run retries
  the same bounded slice.

The model never reads the raw log or writes the cursor: P40.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("JB_ROOT") or Path(__file__).resolve().parent.parent)
MEMORY_DIR = Path(os.environ.get("JB_MEMORY_DIR") or
                  Path.home() / ".claude" / "projects" / str(Path.home()).replace("/", "-").replace(".", "-") / "memory")
MAX_ACTIONS, MAX_MEMORIES, MAX_DRAFT = 80, 12, 1500


def paths():
    st = ROOT / "state"
    return {"cursor": st / "distill.last_run", "seen": st / "distill.memory.json",
            "dir": st / "distill", "input": st / "distill" / "input.md", "pending": st / "distill" / "pending.json"}


def ts(s):
    return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))


def read_cursor():
    p = paths()["cursor"]
    return ts(p.read_text()) if p.exists() and p.read_text().strip() else None


def new_actions(cursor):
    log = ROOT / "log" / "actions.jsonl"
    rows = []
    for line in log.read_text().splitlines() if log.exists() else []:
        try:
            d = json.loads(line)
            t = ts(d["ts"])
        except (ValueError, KeyError):
            continue
        if cursor is None or t > cursor:
            rows.append((t, d))
    rows.sort(key=lambda r: r[0])
    return rows


def compact(d):
    out = {}
    for k, v in d.items():
        if v is None or v is False or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, str) and len(v) > MAX_DRAFT:
            v = v[:MAX_DRAFT] + " [cut]"
        out[k] = v
    return out


def is_feedback(path):
    head = path.read_text(errors="replace")[:600]
    return path.name.startswith("feedback_") or re.search(r"^\s*type:\s*feedback\s*$", head, re.M) is not None


def brain_seed_time():
    """Memories unchanged since the brain was seeded from them (2026-11-07) are already in it."""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "log", "--reverse", "--format=%cI", "--", "brain/principles.md"],
                             capture_output=True, text=True, timeout=10).stdout.split()
        return ts(out[0]).timestamp() if out else 0
    except Exception:
        return 0


def changed_memories():
    seen_path = paths()["seen"]
    first = not seen_path.exists()
    seen = json.loads(seen_path.read_text()) if not first else {}
    seed = brain_seed_time() if first else 0
    files = sorted((p for p in MEMORY_DIR.glob("*.md") if p.name != "MEMORY.md" and is_feedback(p)),
                   key=lambda p: p.stat().st_mtime) if MEMORY_DIR.is_dir() else []
    out = []
    for p in files:
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        if first and p.stat().st_mtime <= seed:
            seen[p.name] = h   # baseline: the seed already covered it
        elif seen.get(p.name) != h:
            out.append((p, h))
    return out, seen


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower())).strip()


def gaps(cursor):
    recent, across = [], defaultdict(set)
    for f in (ROOT / "queue" / "items").glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        fresh = cursor is None or f.stat().st_mtime > cursor.timestamp()
        key = d.get("key") or f.stem
        for s in d.get("steps") or []:
            b = s.get("basis") if isinstance(s, dict) else None
            for x in (b.get("not_read") or []) if isinstance(b, dict) else []:
                across[norm(x)].add(key)
                if fresh:
                    recent.append(f"- {key} / {s.get('id', '?')}: {str(x)[:200]}")
    repeated = sorted(((len(k), t) for t, k in across.items() if len(k) >= 2), reverse=True)
    return recent[:200], [f"- {n} items: {t}" for n, t in repeated[:40]]


def prepare():
    p = paths()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    cursor = read_cursor()
    acts = new_actions(cursor)
    batch, more = acts[:MAX_ACTIONS], len(acts) > MAX_ACTIONS
    mems, seen = changed_memories()
    mem_batch = mems[:MAX_MEMORIES]
    recent, repeated = gaps(cursor)
    if not batch and not mem_batch and not recent:
        print("nothing new")
        return 3
    # A full slice runs to now (gaps and memories are judged up to now too); a capped one stops at its last action.
    upto = batch[-1][0].isoformat() if more else now
    parts = [f"# Distill input (prepared by bin/distill_prep.py {datetime.now().astimezone().isoformat(timespec='seconds')})",
             f"Cursor: {cursor.isoformat() if cursor else 'none'}. This slice runs to {upto}."
             + (f" {len(acts) - len(batch)} later actions wait for the next run." if more else ""),
             "", f"## 1. Queue actions ({len(batch)})", ""]
    parts += [json.dumps(compact(d), ensure_ascii=False) for _, d in batch] or ["None."]
    parts += ["", f"## 2. Feedback memories new or changed since distill last read them ({len(mem_batch)}"
              + (f"; {len(mems) - len(mem_batch)} more next run" if len(mems) > len(mem_batch) else "") + ")", ""]
    for m, _ in mem_batch:
        parts += [f"### {m.name}", m.read_text(errors="replace").strip(), ""]
    if not mem_batch:
        parts.append("None.")
    parts += ["", f"## 3. What runs could not read", "", "### On items changed in this window", ""]
    parts += recent or ["None."]
    parts += ["", "### Sources missed on two or more items (whole queue, exact wording)", ""]
    parts += repeated or ["None."]
    p["dir"].mkdir(parents=True, exist_ok=True)
    p["input"].write_text("\n".join(parts) + "\n")
    for m, h in mem_batch:
        seen[m.name] = h
    p["pending"].write_text(json.dumps({"cursor": upto, "seen": seen}))
    print(f"actions {len(batch)}{' (more waiting)' if more else ''}, memories {len(mem_batch)}, gaps {len(recent)}")
    return 0


def run_ok(log):
    """The run's final result, as _claude.sh saved it next to the log, is not an error."""
    try:
        d = json.loads(Path(str(log) + ".json").read_text())
    except (OSError, ValueError):
        return False
    return not d.get("is_error") and "TIMED OUT" not in str(d.get("result", ""))


def commit(log):
    p = paths()
    if not p["pending"].exists():
        print("no pending slice")
        return 1
    if not run_ok(log):
        print("run failed; cursor kept")
        return 1
    pend = json.loads(p["pending"].read_text())
    p["cursor"].write_text(pend["cursor"] + "\n")
    p["seen"].write_text(json.dumps(pend["seen"], indent=1, sort_keys=True))
    p["pending"].unlink()
    print(f"cursor -> {pend['cursor']}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["prepare"]:
        sys.exit(prepare())
    if a[:1] == ["commit"] and len(a) == 2:
        sys.exit(commit(a[1]))
    sys.exit(__doc__)
