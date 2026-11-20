#!/usr/bin/env python3
"""The Solution Architect's first round of searches, in code (Nov 20): the question's key terms, searched across every
snapshot source with ripgrep, as a digest the docs lane starts from. A run spent 25 model turns on greps like these;
code does them in about a second.

Usage: sa_search.py <question id> <out.md>
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "state" / "snapshots" / "sa"
RG = "/opt/homebrew/bin/rg"
MAX_TERMS, MAX_FILES, MAX_LINES, TOO_COMMON, PLAIN_MAX, CAP = 28, 4, 3, 400, 60, 30000
STOP = set("""about above after again against because before being below between could does doing during each every
further having here itself just more most other ourselves same should some such than that their theirs them
themselves then there these they this those through under until very what when where which while whom will with
would your yours also like into only over need needs want there's we're they're isn't aren't doesn't don't won't
can't still today right currently testnet mainnet launch""".split())


def terms(text):
    """Distinctive terms first: code spans, identifiers, acronyms and slash terms; then longer plain words."""
    out = []
    add = lambda t: t and t.lower() not in {x.lower() for x in out} and out.append(t)
    for t in re.findall(r"`([^`]{2,60})`", text):
        add(t.strip())
    for t in re.findall(r"\b[A-Za-z]+/[A-Za-z]+\b", text):             # TP/SL
        add(t)
    for t in re.findall(r"\b[a-z]+[A-Z][A-Za-z0-9]+\b|\b\w+[._]\w+\b", text):   # camelCase, snake_case, dotted.names
        add(t)
    for t in re.findall(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)+\b", text):    # Asset Hub
        if not re.match(r"(?:Will|What|How|Does|Can|Our|Your|The|Also|Or|And)\b", t):
            add(t)
    for t in re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", text):              # OFT, USDT, IOC
        add(t)
    special = len(out)
    words = Counter(w for w in re.findall(r"\b[a-z][a-z-]{5,}\b", text.lower()) if w not in STOP)
    for w, _ in words.most_common():
        add(w)
    return out[:MAX_TERMS * 2], special


def rg(term):
    r = subprocess.run([RG, "-n", "-i", "-F", "--no-heading", "-M", "300", "--max-count", "20", term, str(SNAP)],
                       capture_output=True, text=True, timeout=30)
    return [ln for ln in r.stdout.splitlines() if ln]


def digest(question):
    parts, kept, plain = [], 0, 0
    ts, special = terms(question)
    for n, t in enumerate(ts):
        if kept >= MAX_TERMS:
            break
        hits = rg(t)
        word = n >= special   # a plain word only helps when it is rare in the sources
        if not hits or len(hits) >= (PLAIN_MAX if word else TOO_COMMON) or (word and plain >= 4):
            continue
        kept += 1
        plain += word
        by = {}
        for ln in hits:
            f, n, txt = (ln.split(":", 2) + ["", ""])[:3]
            by.setdefault(f, []).append(f"  {n}: {txt.strip()[:220]}")
        files = sorted(by, key=lambda f: -len(by[f]))[:MAX_FILES]
        parts.append(f"### `{t}` ({len(hits)} lines in {len(by)} files)\n" + "\n".join(
            f"- {Path(f).relative_to(SNAP)}\n" + "\n".join(by[f][:MAX_LINES]) for f in files))
    body = "\n\n".join(parts)
    return body[:CAP] + ("\n\n(cut at the size cap)" if len(body) > CAP else "")


if __name__ == "__main__":
    q = json.loads((ROOT / "architect" / f"{sys.argv[1]}.json").read_text())
    turn = next(t for t in reversed(q["turns"]) if t.get("kind") != "revise")   # the client's message, not a rewrite request
    Path(sys.argv[2]).write_text(digest(turn["question"]))
