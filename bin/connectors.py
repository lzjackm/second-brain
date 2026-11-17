#!/usr/bin/env python3
"""The connectors this brain reads (config/connectors.json), turned into what runs need.

  connectors.py tools            every listed connector's read tools, one per line (mcp__<server>__<tool>), for --allowedTools
  connectors.py required         the names runs wait for before starting (one per line)
  connectors.py sources [area] [mode]   the "Connected sources" prompt section. For a lead run (mode lead) it lists
                                 the connectors to watch this run, each with its own window since it was last read,
                                 and the ones to use only when an item needs them; other runs get them all as lookups
  connectors.py settings <server> <json>   set role, areas, cadence, required, use
  connectors.py stats            JSON: per connector, items it sourced and tool calls in the last 7 days
  connectors.py claude           JSON: the Claude account runs use (`claude auth status`)

Each connector's settings (config/connectors.json):
  role     watch: read for new work in lead runs · lookup: only when an item or agent needs it · off
  areas    the areas whose runs read it ([] = all)
  cadence  every: each lead run · daily: the first lead run of the day
  required runs wait for it to connect (watch connectors only)
  connectors.py status           JSON: each connector from `claude mcp list` with its state (connected, needs_auth, failed)
Write tools are never listed: the executor keeps its own short list and uses it only when the owner presses a step.
"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "config" / "connectors.json"
CATALOG = ROOT / "config" / "connector-catalog.json"
READS = ROOT / "state" / "connectors-read.json"     # {area: {connector: ISO time last read by a successful lead run}}
sys.path.insert(0, str(ROOT / "bin"))
from identity import TZ  # noqa: E402
ROLES, CADENCES = ("watch", "lookup", "off"), ("every", "daily")
# Defaults by catalog category: where new work shows up is watched; the rest is looked up when an item links to it.
WATCH = {"Messaging": "every", "Email": "every", "Project tracking": "daily", "Meetings": "daily", "Support": "daily", "Engineering": "daily"}
FIRST_WINDOW_H = 48


def registry():
    return json.loads(REG.read_text()).get("connectors", []) if REG.exists() else []


def role(c):
    return c.get("role") or "watch"


def tools():
    return [f"mcp__{c['server']}__{t}" for c in registry() if role(c) != "off" for t in c.get("read_tools") or []]


def defaults(name):
    """Role and cadence a newly added connector starts with, from its catalog category."""
    try:
        cat = next((c for c in json.loads(CATALOG.read_text())["catalog"] if c["name"].lower() == name.lower()), {})
    except (OSError, json.JSONDecodeError, KeyError):
        cat = {}
    cad = WATCH.get(cat.get("category"))
    return {"role": "watch" if cad else "lookup", "cadence": cad or "daily", "areas": []}


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
    conns.append({"name": name, "server": server, "use": use, **defaults(name), "read_tools": [], "required": required,
                  "discovery": "pending", "added_at": datetime.now(TZ).isoformat(timespec="seconds")})
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


READ_WORDS = {"get", "list", "search", "read", "query", "fetch", "find", "describe", "discover", "view", "whoami", "lookup",
              "retrieve", "count", "aggregate", "guidance", "download", "export", "session"}
WRITE_WORDS = {"create", "update", "delete", "send", "post", "write", "upload", "set", "add", "remove", "archive", "merge",
               "execute", "run", "manage", "share", "trash", "insert", "append", "import", "submit", "mark", "resolve",
               "schedule", "invite", "assign", "move", "edit", "publish", "clear", "copy", "restore", "retire", "unshare",
               "save", "respond", "patch", "put", "deploy", "cancel", "approve", "reject", "transfer", "pay", "sql"}


STRONG_WRITE = WRITE_WORDS - {"post", "set", "add", "run", "move", "copy", "save", "put", "patch", "mark", "sql"}


def is_read(tool):
    """Read-only by its verb. The leading verb decides (a service prefix like `slack_` is skipped): a read verb is read
    unless a strong write verb also appears (send, create, delete, execute...); a write verb is write. With neither
    leading (conversational_search), any read word and no write word at all. Unknown names are not read."""
    if tool.lower() in ("create_session",):     # Figma: opens a read session, nothing changes
        return True
    words = [w for w in re.split(r"[_\-.]+", tool.lower()) if w]
    lead = next((w for w in words if w in READ_WORDS or w in WRITE_WORDS), None)
    if lead in READ_WORDS and words.index(lead) <= 1:
        return not (set(words) & STRONG_WRITE)
    if lead in WRITE_WORDS and words.index(lead) <= 1:
        return False
    return bool(set(words) & READ_WORDS) and not set(words) & WRITE_WORDS


def classify(server, real, model_read=None):
    """Read tools of one connector. `real` = the tool names Claude Code actually listed for it (tool search results),
    so a name the model shortened or invented is never stored. `model_read`, if given, narrows to what the model
    judged read-only from the descriptions; its names are matched to real ones by suffix."""
    prefix = f"mcp__{server}__"
    names = sorted({r[len(prefix):] for r in real if r.startswith(prefix)})
    picked = names
    if model_read is not None:
        want = {m.split("__")[-1] for m in model_read}
        picked = [n for n in names if any(n == w or n.endswith("_" + w) for w in want)]
    return [n for n in picked if is_read(n)], [n for n in names if not is_read(n)]


def settings(server, new):
    """Apply the owner's settings from the Connectors page, checked field by field."""
    conns = registry()
    c = next((x for x in conns if x["server"] == server), None)
    if not c:
        return False
    areas = {p.stem for p in (ROOT / "leads").glob("*.md") if not p.stem.startswith("_")}
    if new.get("role") in ROLES:
        c["role"] = new["role"]
    if new.get("cadence") in CADENCES:
        c["cadence"] = new["cadence"]
    if isinstance(new.get("areas"), list):
        c["areas"] = sorted(a for a in new["areas"] if a in areas)
    if isinstance(new.get("use"), str) and new["use"].strip():
        c["use"] = new["use"].strip()[:300]
    if isinstance(new.get("required"), bool):
        c["required"] = new["required"]
    if role(c) != "watch":
        c["required"] = False
    save(conns)
    return True


def _reads():
    try:
        return json.loads(READS.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _commit_pending(area):
    """A lead run's watched connectors count as read once that run finished (it writes state/<area>.last_run last)."""
    pend = ROOT / "state" / f"connectors-pending-{area}.json"
    last = ROOT / "state" / f"{area}.last_run"
    if not pend.exists() or not last.exists():
        return
    p = json.loads(pend.read_text())
    if last.read_text().strip() >= p["started"]:
        r = _reads()
        r.setdefault(area, {}).update({n: p["started"] for n in p["names"]})
        READS.write_text(json.dumps(r, indent=1))
        pend.unlink()


def sources(area=None, mode="lead"):
    live = [c for c in registry() if role(c) != "off" and c.get("read_tools") and (not area or not c.get("areas") or area in c["areas"])]
    use = lambda c: c.get("use") or "anything relevant to the open items and the owner"
    head = ["## Connected sources", "", "Read only; write tools are not available to you.", ""]
    if mode != "lead" or not area:
        return "\n".join(head + [f"- **{c['name']}**: {use(c)}." for c in live]) + "\n"
    _commit_pending(area)
    now = datetime.now(TZ)
    reads = _reads().get(area, {})
    watch, look = [], []
    for c in live:
        last = reads.get(c["name"])
        due = role(c) == "watch" and (c.get("cadence") != "daily" or not last or last[:10] < now.date().isoformat())
        (watch if due else look).append((c, last))
    out = head
    if watch:
        out += ["**Watch for new work** (each since the time given):", ""]
        for c, last in watch:
            since = last or (now - timedelta(hours=FIRST_WINDOW_H)).isoformat(timespec="seconds")
            out.append(f"- **{c['name']}** since {since}{' (first read: 48 hours back)' if not last else ''}: {use(c)}.")
        out.append("")
    if look:
        out += ["**Use only when an item, link or step needs them** (do not sweep these):", ""]
        out += [f"- **{c['name']}**: {use(c)}." for c, _ in look]
    (ROOT / "state" / f"connectors-pending-{area}.json").write_text(
        json.dumps({"started": now.isoformat(timespec="seconds"), "names": [c["name"] for c, _ in watch]}))
    return "\n".join(out) + "\n"


def _hosts(name):
    try:
        cat = next((c for c in json.loads(CATALOG.read_text())["catalog"] if c["name"].lower() == name.lower()), {})
    except (OSError, json.JSONDecodeError, KeyError):
        cat = {}
    return cat.get("hosts") or [re.sub(r"[^a-z0-9]", "", name.lower()) + "."]


def stats(days=7):
    """Per connector: queue items created in the window whose sources point at it, and its tool calls per day in runs."""
    since = (datetime.now(TZ) - timedelta(days=days)).isoformat()
    conns = registry()
    items = 0
    out = {c["name"]: {"items": 0, "calls": 0} for c in conns}
    for f in (ROOT / "queue" / "items").glob("*.json"):
        try:
            it = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if (it.get("created") or "") < since:
            continue
        items += 1
        urls = " ".join(str(e.get("url") or "") for e in it.get("evidence") or []).lower()
        for c in conns:
            if any(h in urls for h in _hosts(c["name"])):
                out[c["name"]]["items"] += 1
    servers = {c["server"]: c["name"] for c in conns}
    cutoff = time.time() - days * 86400
    for f in (ROOT / "logs").glob("*.trace.jsonl*"):
        if f.stat().st_mtime < cutoff:
            continue
        try:
            text = (gzip.open(f, "rt", errors="ignore") if f.suffix == ".gz" else f.open(errors="ignore")).read()
        except OSError:
            continue
        for server in re.findall(r'"name":\s*"mcp__([A-Za-z0-9_.-]+?)__', text):
            if server in servers:
                out[servers[server]]["calls"] += 1
    for v in out.values():
        v["calls_per_day"] = round(v.pop("calls") / days, 1)
    return {"days": days, "items_total": items, "by_connector": out, "ts": datetime.now(TZ).isoformat(timespec="seconds")}


def claude_exe():
    return shutil.which("claude") or next((p for p in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude", os.path.expanduser("~/.local/bin/claude"),
                                                       os.path.expanduser("~/.claude/local/claude")) if os.path.exists(p)), "")


def claude():
    """The Claude account the brain's runs use: the owner's own Claude Code sign-in. Nothing is stored in this repo."""
    exe = claude_exe()
    if not exe:
        return {"installed": False}
    try:
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        st = json.loads(subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=30).stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {"installed": True, "logged_in": False, "error": "Couldn't read the sign-in status"}
    return {"installed": True, "version": ver.split()[0] if ver else "", "logged_in": bool(st.get("loggedIn")),
            "method": st.get("authMethod"), "provider": st.get("apiProvider"), "plan": st.get("subscriptionType"),
            "account": st.get("email"), "org": st.get("orgName")}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "tools":
        print("\n".join(tools()))
    elif cmd == "required":
        print("\n".join(c["name"] for c in registry() if c.get("required") and role(c) == "watch"))
    elif cmd == "sources":
        print(sources(*(sys.argv[2:4])))
    elif cmd == "settings" and len(sys.argv) == 4:
        sys.exit(0 if settings(sys.argv[2], json.loads(sys.argv[3])) else 1)
    elif cmd == "stats":
        print(json.dumps(stats(), indent=1))
    elif cmd == "claude":
        print(json.dumps(claude(), indent=1))
    elif cmd == "set-tools" and len(sys.argv) == 4:  # server, JSON {"read": [...], "write": [...], "error": "..."}
        d = json.loads(sys.argv[3])
        set_tools(sys.argv[2], d.get("read") or [], d.get("write") or [], "failed" if d.get("error") else "done", d.get("error") or "")
    elif cmd == "status":
        print(json.dumps(status(), indent=1))
    else:
        sys.exit(__doc__)
