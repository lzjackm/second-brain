#!/usr/bin/env python3
"""Everything a meeting prep run used to open file by file, gathered in code and appended to its prompt: the meeting,
the agenda source (items.md), the owner's rules, the ledger's AGENTS.md and the ledger rows changed in the last week.
Each file read cost the agent a turn (Nov 18: about 10 of a prep's 45 calls were setup).

Usage: meeting_context.py <item> <step>   prints Markdown
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import identity  # noqa: E402


def section(title, body):
    return f"\n### {title}\n\n{body.strip()}\n" if body and body.strip() else ""


def ledger_changes(days=7, cap=14000):
    repo = os.path.expanduser(identity.LEDGER_PATH) if identity.LEDGER_PATH else ""
    if not repo or not Path(repo, ".git").exists():
        return ""
    r = subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=/dev/null", "log", "origin/main", f"--since={days} days ago",
                        "-p", "-U0", "--format=@@@ %h %ad %s", "--date=short", "--", "DECISIONS.md", "OPEN-ITEMS.md", "ACTIONS.md"],
                       capture_output=True, text=True)
    keep = [ln[:400] for ln in r.stdout.splitlines() if ln.startswith("@@@") or ln.startswith("+|")]   # added rows: the current text
    out, size = [], 0
    for ln in keep:
        if size + len(ln) > cap:
            out.append("(older changes cut; the at-risk rows are in items.md)")
            break
        out.append(ln)
        size += len(ln) + 1
    return "\n".join(out)


def main():
    item, step = sys.argv[1:3]
    it = json.loads((ROOT / "queue" / "items" / f"{item}.json").read_text())
    m = it.get("meeting") or {}
    meeting = json.dumps({k: m.get(k) for k in ("title", "start", "end", "attendees", "description", "organizer") if m.get(k)},
                         ensure_ascii=False, indent=1)[:6000]
    out = ["\n## Loaded for you\n\nAlready read for you, current as of this run. Do not open these files again; go straight to step 1."]
    out.append(section("The meeting (from the item)", meeting))
    out.append(section(f"Agenda source: agents/{item}/{step}/items.md", (ROOT / "agents" / item / step / "items.md").read_text()
                       if (ROOT / "agents" / item / step / "items.md").exists() else ""))
    for f in ("style", "guardrails", "principles"):
        p = ROOT / "brain" / f"{f}.md"
        out.append(section(f"brain/{f}.md", p.read_text() if p.exists() else ""))
    if identity.LEDGER_PATH:
        a = Path(os.path.expanduser(identity.LEDGER_PATH), "AGENTS.md")
        out.append(section(f"{identity.LEDGER_NAME} AGENTS.md", a.read_text()[:12000] if a.exists() else ""))
        out.append(section(f"{identity.LEDGER_NAME} rows changed in the last 7 days (commit, then added/removed table rows)",
                           "```\n" + ledger_changes() + "\n```" if ledger_changes() else ""))
    print("".join(out))


if __name__ == "__main__":
    main()
