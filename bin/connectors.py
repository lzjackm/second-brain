#!/usr/bin/env python3
"""The connectors this brain reads (config/connectors.json), turned into what runs need.

  connectors.py tools            every listed connector's read tools, one per line (mcp__<server>__<tool>), for --allowedTools
  connectors.py required         the names runs wait for before starting (one per line)
  connectors.py sources          a markdown "Connected sources" section for lead and agent prompts
  connectors.py status           JSON: each connector from `claude mcp list` with its state (connected, needs_auth, failed)
Write tools are never listed: the executor keeps its own short list and uses it only when the owner presses a step.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "config" / "connectors.json"


def registry():
    return json.loads(REG.read_text()).get("connectors", []) if REG.exists() else []


def tools():
    return [f"mcp__{c['server']}__{t}" for c in registry() for t in c.get("read_tools") or []]


def status():
    """Every connector Claude Code sees, with its state. `claude mcp list` prints 'claude.ai Name: url - ✔ Connected'."""
    import os, shutil
    exe = shutil.which("claude") or next((p for p in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude", os.path.expanduser("~/.local/bin/claude"), os.path.expanduser("~/.claude/local/claude")) if os.path.exists(p)), "claude")
    out = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True, timeout=90).stdout  # launchd's PATH lacks Homebrew
    found = []
    for line in out.splitlines():
        m = re.match(r"^(claude\.ai )?(.+?): (\S+)(?: \(.*?\))? - (.+)$", line.strip())
        if not m:
            continue
        state = m.group(4).lower()
        found.append({"name": m.group(2), "url": m.group(3), "claude_ai": bool(m.group(1)),
                      "server": ("claude_ai_" + re.sub(r"[^A-Za-z0-9]+", "_", m.group(2)).strip("_")) if m.group(1) else m.group(2),
                      "state": "connected" if "connected" in state else "needs_auth" if "auth" in state else "failed"})
    return found


def save(conns):
    data = json.loads(REG.read_text()) if REG.exists() else {"_doc": "Connectors this brain reads."}
    data["connectors"] = conns
    REG.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def add(name, server, use, required=False):
    """Add a connector to the brain (no tools until discovery lists its read tools)."""
    conns = registry()
    if any(c["server"] == server for c in conns):
        return False
    conns.append({"name": name, "server": server, "use": use, "read_tools": [], "required": required, "discovery": "pending"})
    save(conns)
    return True


def remove(server):
    save([c for c in registry() if c["server"] != server])


def set_tools(server, read, write, state="done", error=""):
    conns = registry()
    for c in conns:
        if c["server"] == server:
            c["read_tools"], c["discovery"] = sorted(set(read)), state
            c["write_tools_skipped"] = sorted(set(write))
            if error:
                c["discovery_error"] = error
            else:
                c.pop("discovery_error", None)
    save(conns)


def sources():
    lines = ["## Connected sources", "", "Read these since the last run, read only (write tools are not available to you):", ""]
    lines += [f"- **{c['name']}**: {c.get('use') or 'anything relevant to the open items and the owner'}." for c in registry()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "tools":
        print("\n".join(tools()))
    elif cmd == "required":
        print("\n".join(c["name"] for c in registry() if c.get("required")))
    elif cmd == "sources":
        print(sources())
    elif cmd == "set-tools" and len(sys.argv) == 4:  # server, JSON {"read": [...], "write": [...], "error": "..."}
        d = json.loads(sys.argv[3])
        set_tools(sys.argv[2], d.get("read") or [], d.get("write") or [], "failed" if d.get("error") else "done", d.get("error") or "")
    elif cmd == "status":
        print(json.dumps(status(), indent=1))
    else:
        sys.exit(__doc__)
