#!/usr/bin/env python3
"""Check the ledger files against the repo's own rules (AGENTS.md capture scope and house style, PROCESS.md).

Errors fail the check; warnings are printed. By default only rows added or changed since BASE are checked, so
old rows never block a new PR; --all checks every row (a baseline report).

Usage: python3 tools/check_ledger.py [--base origin/main] [--all]

Errors (each is a written rule in AGENTS.md or PROCESS.md):
- a row whose cell count differs from its table header
- a duplicate ID
- a D row status other than Locked, Still to Decide, Superseded by D##, or Out of scope: <workstream>
- Superseded by a D## (one or more) that does not exist
- a Locked row without a YYYY-MM-DD date
- a link to a Slack DM (archives/D...), or a link in a row whose source is a DM or private medium
- an email address or phone number
- an em dash
- a CONFLICTS.md row whose status is not Open or Settled by D##, or settled by a D## that does not exist
Warnings:
- a D, G or A reference to an ID that does not exist (closed gaps and actions are removed, so this can be legitimate)
- a Still to Decide row with no card in decisions/ (PROCESS.md, Open decisions)
- "Day 1" or "at launch" in a ledger row (house style asks for absolute dates)
- words that suggest out-of-scope content (pay, hiring, departures, health)
"""
import re
import subprocess
import sys
from pathlib import Path

# Vendored from the ledger repo's tools/check_ledger.py. The PR reviewer runs this copy, never the one in a
# PR branch (a PR could change that file). --root points it at a checkout; it only reads files there.
ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve() if "--root" in sys.argv else Path(__file__).resolve().parent.parent
FILES = ["DECISIONS.md", "OPEN-ITEMS.md", "ACTIONS.md", "CONFLICTS.md"]
ID = re.compile(r"\b([DGAC])(\d{1,4})\b")
STATUS = re.compile(r"^(Locked|Still to Decide|Superseded by D\d+(, D\d+)*|Out of scope: .+)$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DM_LINK = re.compile(r"slack\.com/archives/D[A-Z0-9]+")
LINK = re.compile(r"https?://")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"(?<![\w/.-])\+?\d[\d\s().-]{8,}\d(?![\w/.-])")
PRIVATE_SOURCE = re.compile(r"\b(DM|direct message|1:1|private channel)\b", re.I)
SCOPE_WORDS = re.compile(r"\b(salary|salaries|compensation|bonus(es)?|equity grant|hiring|hired|fired|resign(ed|ation)?|departure|leaving the company|parental leave|sick leave|medical)\b", re.I)
DAY1 = re.compile(r"\b(Day 1|at launch)\b", re.I)


def rows(path):
    """Yield (line_no, header, cells, raw) for each data row of each table in the file."""
    header = None
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if set(line.replace("|", "").strip()) <= set("-: "):
            continue
        yield n, header, cells, line


def changed_lines(base):
    """Line numbers added or changed since base, per file."""
    out = {}
    for f in FILES:
        diff = subprocess.run(["git", "-C", str(ROOT), "diff", "-U0", base, "--", f], capture_output=True, text=True).stdout
        lines, cur = set(), None
        for line in diff.splitlines():
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                lines |= set(range(start, start + count))
        out[f] = lines
    return out


def main():
    args = sys.argv[1:]
    base = args[args.index("--base") + 1] if "--base" in args else "origin/main"
    only = None if "--all" in args else changed_lines(base)
    errors, warnings = [], []
    ids, d_status = {}, {}
    all_rows = []
    for f in FILES:
        p = ROOT / f
        if not p.exists():
            continue
        for n, header, cells, raw in rows(p):
            all_rows.append((f, n, header, cells, raw))
            m = re.match(r"^([DGAC]\d+)$", cells[0]) if cells else None
            if m:
                ids.setdefault(m.group(1), []).append(f"{f}:{n}")
                if f == "DECISIONS.md" and "Status" in header and len(cells) == len(header):
                    d_status[m.group(1)] = cells[header.index("Status")]
    cards = {re.match(r"(D\d+)", x.name).group(1) for x in (ROOT / "decisions").glob("D*.md") if re.match(r"D\d+", x.name)}

    for f, n, header, cells, raw in all_rows:
        if only is not None and n not in only.get(f, set()):
            continue
        where = f"{f}:{n}"
        rid = cells[0] if cells else "?"
        if len(cells) != len(header):
            errors.append(f"{where} {rid}: {len(cells)} cells, header has {len(header)} (an unescaped | in the text?)")
            continue
        if len(ids.get(rid, [])) > 1:
            errors.append(f"{where} {rid}: duplicate ID, also at {', '.join(x for x in ids[rid] if x != where)}")
        if "—" in raw:
            errors.append(f"{where} {rid}: em dash (house style)")
        if DM_LINK.search(raw):
            errors.append(f"{where} {rid}: links a Slack DM; private sources name the medium and date only (capture scope)")
        src = cells[header.index("Source")] if "Source" in header else ""
        if PRIVATE_SOURCE.search(src) and LINK.search(src):
            errors.append(f"{where} {rid}: private source with a link; name the medium and date only (capture scope)")
        if EMAIL.search(raw):
            errors.append(f"{where} {rid}: email address (capture scope: never contact details)")
        for ph in PHONE.findall(re.sub(r"https?://\S+", "", raw)):
            if len(re.sub(r"\D", "", ph)) >= 10:
                errors.append(f"{where} {rid}: looks like a phone number '{ph.strip()}' (capture scope)")
        if SCOPE_WORDS.search(raw):
            warnings.append(f"{where} {rid}: mentions '{SCOPE_WORDS.search(raw).group(0)}'; check the capture scope's never-captured list")
        if f in ("DECISIONS.md", "OPEN-ITEMS.md", "ACTIONS.md") and DAY1.search(raw):
            warnings.append(f"{where} {rid}: '{DAY1.search(raw).group(0)}'; house style prefers an absolute date")
        if f == "DECISIONS.md" and "Status" in header:
            st = cells[header.index("Status")]
            if not STATUS.match(st):
                errors.append(f"{where} {rid}: status '{st}' is not Locked, Still to Decide, Superseded by D## or Out of scope: <workstream>")
            for target in re.findall(r"D\d+", st) if st.startswith("Superseded") else []:
                if target not in ids:
                    errors.append(f"{where} {rid}: superseded by {target}, which does not exist")
            if st == "Locked" and "Date" in header and not DATE.match(cells[header.index("Date")]):
                errors.append(f"{where} {rid}: Locked without a YYYY-MM-DD date")
            if st == "Still to Decide" and rid not in cards:
                warnings.append(f"{where} {rid}: Still to Decide with no card in decisions/ (PROCESS.md, Open decisions)")
        if f == "CONFLICTS.md" and "Status" in header:
            st = cells[header.index("Status")]
            m = re.match(r"^(Open|Settled by (D\d+))$", st)
            if not m:
                errors.append(f"{where} {rid}: status '{st}' is not Open or Settled by D##")
            elif m.group(2) and m.group(2) not in ids:
                errors.append(f"{where} {rid}: settled by {m.group(2)}, which does not exist")
        for kind, num in ID.findall(" ".join(cells[1:])):
            ref = f"{kind}{num}"
            if kind in "DGA" and ref not in ids:
                warnings.append(f"{where} {rid}: refers to {ref}, which is not in the ledger (closed and removed?)")

    for w in sorted(set(warnings)):
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    scope = "all rows" if only is None else f"rows changed since {base}"
    print(f"\n{len(errors)} errors, {len(set(warnings))} warnings ({scope}).")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
