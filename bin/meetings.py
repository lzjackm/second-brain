#!/usr/bin/env python3
"""Meetings the owner runs: today's calendar, and the open items owned by each attendee.

Plain code, no agent. The calendar itself is fetched by bin/calendar.sh (a headless run with the Google Calendar
connector) into state/calendar/<date>.json; this module reads it and does everything deterministic:

- `events(date)`: the day's meetings, with attendees as names.
- `prep_item(event)`: the queue item for "run this meeting": draft the agenda (agent), run it (the owner), read the notes
  and propose updates (agent), then the owner's apply steps, which the debrief adds.
- `collect(item)`: the at-risk ledger rows (launch rows blocked, past or near target; gaps flagged at risk; actions due;
  rows a risky launch row cites) owned by an attendee, read through open PRs. Written to agents/<id>/s1/items.json and
  items.md; the prep agent checks each one's latest status in Slack, Linear, GitHub and meeting notes.

Usage: meetings.py events [YYYY-MM-DD] | meetings.py collect <item_id>
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
import identity  # noqa: E402
from identity import OWNER, OWNER_EMAILS, OWNER_NAMES  # noqa: E402  (config/brain.json)
ITEMS = ROOT / "queue" / "items"
AGENTS = ROOT / "agents"
CAL = ROOT / "state" / "calendar"
# Optional decision-ledger repo (config/brain.json modules.ledger: {"path", "url"}): its open actions, gaps and
# decisions join each attendee's agenda. Without it, the agenda comes from the queue alone.
_LEDGER = (identity.CFG.get("modules") or {}).get("ledger") or {}
LEDGER = Path(_LEDGER["path"]).expanduser() if _LEDGER.get("path") else Path("/nonexistent")
LEDGER_URL = (_LEDGER.get("url") or "").rstrip("/") + "/blob/main/"
LEDGER_REPO = "/".join((_LEDGER.get("url") or "").rstrip("/").split("/")[-2:])  # owner/repo for gh
ET = ZoneInfo("America/New_York")
CLOSED = re.compile(r"^(done|shipped|complete|completed|closed|cancel+ed|descoped|n/?a|live|merged|locked|superseded)", re.I)
PENDING = {"todo", "queued", "failed"}


# ---------- calendar ----------

def name_of(att):
    """A person's name from a calendar attendee: the display name, else first.last@ from the email."""
    if att.get("name"):
        return att["name"].strip()
    local = (att.get("email") or "").split("@")[0]
    return " ".join(p.capitalize() for p in re.split(r"[._-]+", local) if p) or att.get("email", "")


def is_owner_att(att):
    e = (att.get("email") or "").lower()
    return att.get("self") or e in OWNER_EMAILS or name_of(att).lower() in OWNER_NAMES


def events(date=None, items=None):
    """The day's meetings from the last calendar fetch: [{id, title, start, end, attendees: [{name, email, response}], ...}].
    Meetings with no one but the owner are left out."""
    date = date or datetime.now(ET).date().isoformat()
    f = CAL / f"{date}.json"
    if not f.exists():
        return {"date": date, "fetched_at": None, "events": []}
    data = json.loads(f.read_text())
    out = []
    for ev in data.get("events") or []:
        people = [a for a in ev.get("attendees") or [] if not a.get("resource") and not is_owner_att(a)]
        if not people or ev.get("all_day"):
            continue
        out.append({**ev, "attendees": [{"name": name_of(a), "email": a.get("email"), "response": a.get("response")} for a in people]})
    out.sort(key=lambda e: e.get("start") or "")
    prepped = {i.get("meeting", {}).get("event_id"): i["id"] for i in (items if items is not None else load_items()) if i.get("type") == "meeting"}
    for ev in out:
        ev["item_id"] = prepped.get(ev.get("id"))
    return {"date": date, "fetched_at": data.get("fetched_at"), "events": out}


def load_items():
    out = []
    for f in sorted(ITEMS.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    return out


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:32] or "meeting"


def prep_item(ev, now):
    """The queue item for running one meeting. The first step is an agent step the owner started by choosing the meeting."""
    start = datetime.fromisoformat(ev["start"]).astimezone(ET)
    when = start.strftime("%-I:%M %p").replace(":00 ", " ")
    names = [a["name"] for a in ev["attendees"]]
    who = ", ".join(n.split()[0] for n in names[:4]) + (f" +{len(names) - 4}" if len(names) > 4 else "")
    iid = f"meeting-{start:%Y%m%d-%H%M}-{slug(ev.get('title'))}"
    ts = now.isoformat(timespec="seconds")
    return {
        "id": iid, "key": f"meeting:{ev['id']}", "area": "meetings", "type": "meeting",
        "title": f"Run {ev.get('title') or 'meeting'} at {when}"[:80],
        "context": f"You run this meeting. Attendees: {who}. Agenda: each person's open items and where they stand.",
        "recommendation_short": "Walk each person's items; mark the meeting done after the call so notes update every item.",
        "summary": f"{ev.get('title')} on {start:%a %b %-d} at {when} ET with {', '.join(names)}.",
        "why_owner": "You chose this meeting to run.",
        "priority": 70, "due": start.date().isoformat(),
        "evidence": [{"label": "Calendar event", "url": ev.get("url") or ""}] if ev.get("url") else [{"label": f"Calendar: {ev.get('title')}", "url": ""}],
        "meeting": {"event_id": ev["id"], "title": ev.get("title"), "start": ev["start"], "end": ev.get("end"),
                    "attendees": ev["attendees"], "url": ev.get("url"), "conference": ev.get("conference"),
                    "description": (ev.get("description") or "")[:2000]},
        "steps": [
            {"id": "s1", "text": "Draft the agenda from attendees' open items", "owner": "agent", "status": "todo", "meeting_phase": "prep",
             "agent": {"brief": "meeting prep", "requested_at": ts, "previous_owner": "agent"}},
            {"id": "s2", "text": f"Run the meeting at {when}", "owner": OWNER, "status": "todo",
             "execute": {"kind": "none"}},
            {"id": "s3", "text": "Read the notes and propose updates to each item", "owner": "agent", "status": "todo",
             "meeting_phase": "debrief"},
        ],
        "status": "working", "created": ts, "updated": ts,
        "history": [{"ts": ts, "by": OWNER, "event": "created", "note": "chose meeting to run"}],
    }


# ---------- who owns what ----------

def matcher(names):
    """Match owner text to attendees: full names always; a first name alone only when no other attendee shares it.
    Returns f(text) -> [names matched]."""
    firsts = {}
    for n in names:
        firsts.setdefault(n.split()[0].lower(), []).append(n)
    pats = []
    for n in names:
        if len(n.replace(" ", "")) < 3:  # a calendar name like "M" would match every word starting with M
            continue
        parts = n.split()
        alts = [re.escape(n)]
        if len(firsts[parts[0].lower()]) == 1 and len(parts[0]) > 2:
            alts.append(re.escape(parts[0]) + r"(?![a-z])")
        pats.append((n, re.compile(r"(?<![A-Za-z])(?:" + "|".join(alts) + r")", re.I)))
    return lambda text: [n for n, p in pats if p.search(text or "")]


def table_rows(md):
    """Each markdown table row as {header: cell}, with the table's header names lower-cased."""
    rows, head = [], None
    for line in md.splitlines():
        if not line.startswith("|"):
            head = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            head = [c.lower() for c in cells]
        elif set(line.replace("|", "").strip()) <= set("-: "):
            continue
        elif len(cells) == len(head):
            rows.append(dict(zip(head, cells)))
    return rows


def ledger_file(path, ref="origin/main"):
    r = subprocess.run(["git", "-C", str(LEDGER), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def row_id(r):
    return r.get("#") or r.get("id") or ""


def open_pr_changes():
    """Rows that open ledger PRs close or rewrite: {row_id: {"pr": n, "row": new row or None}}.
    Compared against each PR's merge base, so a branch that is merely behind main never looks like it removed rows."""
    try:
        prs = json.loads(subprocess.run(["gh", "pr", "list", "-R", LEDGER_REPO, "--state", "open",
                                         "--json", "number,headRefName"], capture_output=True, text=True, timeout=60).stdout or "[]")
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return {}
    out = {}
    for pr in prs:
        ref = f"refs/remotes/origin/pr-{pr['number']}"
        if subprocess.run(["git", "-C", str(LEDGER), "fetch", "-q", "origin", f"+{pr['headRefName']}:{ref}"],
                          capture_output=True, timeout=60).returncode:
            continue
        base = subprocess.run(["git", "-C", str(LEDGER), "merge-base", "origin/main", ref], capture_output=True, text=True).stdout.strip()
        files = subprocess.run(["git", "-C", str(LEDGER), "diff", "--name-only", base, ref], capture_output=True, text=True).stdout.split()
        for f in files:
            if not f.endswith(".md") or not (f in ("ACTIONS.md", "OPEN-ITEMS.md", "DECISIONS.md") or f.startswith("launch/divisions/")):
                continue
            before = {row_id(r): r for r in table_rows(ledger_file(f, base)) if row_id(r)}
            after = {row_id(r): r for r in table_rows(ledger_file(f, ref)) if row_id(r)}
            for k, r in before.items():
                if k not in after:
                    out[k] = {"pr": pr["number"], "row": None}
                elif after[k] != r:
                    out[k] = {"pr": pr["number"], "row": after[k]}
    return out


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(text, year):
    """The first date in a cell: 2026-11-16, 11-16 or Nov 16. None for "not stated", "post-launch" and the like,
    and for "after <date>" (not due by then)."""
    t = (text or "").strip().lower()
    if t.startswith("after"):
        return None
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", t)
    if m:
        return datetime(int(m[1]), int(m[2]), int(m[3])).date()
    m = re.search(r"\b(\d{1,2})-(\d{1,2})\b", t)
    if m and 1 <= int(m[1]) <= 12:
        return datetime(year, int(m[1]), int(m[2])).date()
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* (\d{1,2})\b", t)
    if m:
        return datetime(year, MONTHS[m[1]], int(m[2])).date()
    return None


def ledger_items(match, day):
    """Every open ledger row an attendee owns, as of `day` (the meeting date), each with `risk`: why it is at risk,
    or None. Open PRs count: a row an open PR removes is left out, and a row it rewrites uses the PR's text."""
    if not LEDGER.exists():
        return []
    subprocess.run(["git", "-C", str(LEDGER), "fetch", "-q", "origin", "main"], capture_output=True, timeout=60)
    pending = open_pr_changes()
    out = []

    def rows(path):
        for r in table_rows(ledger_file(path)):
            k = row_id(r)
            if k in pending:
                if pending[k]["row"] is None:
                    continue
                r = {**pending[k]["row"], "_pr": pending[k]["pr"]}
            yield r

    def add(owners, r, **kw):
        for n in owners:
            out.append({"owner": n, "source": "ledger", **({"pending_pr": r["_pr"]} if r.get("_pr") else {}), **kw})

    for r in rows("ACTIONS.md"):
        if r.get("#", "").startswith("A"):
            add(match(r.get("owner")), r, id=r["#"], kind="action", text=r.get("action", ""), owner_text=r.get("owner"),
                due=r.get("due"), gate=r.get("gate"), file="ACTIONS.md")
    for r in rows("OPEN-ITEMS.md"):
        if r.get("#", "").startswith("G"):
            add(match(r.get("owner")), r, id=r["#"], kind="gap", text=f"{r.get('item', '')}: {r.get('gap', '')}",
                owner_text=r.get("owner"), gate=r.get("gate"), file="OPEN-ITEMS.md")
    for r in rows("DECISIONS.md"):
        if r.get("id", "").startswith("D") and r.get("status", "").lower().startswith("still to decide"):
            add(match(r.get("decided by")), r, id=r["id"], kind="decision", text=r.get("decision", ""),
                owner_text=r.get("decided by"), gate=r.get("gate"), file="DECISIONS.md")
    launch = {}
    ls = subprocess.run(["git", "-C", str(LEDGER), "ls-tree", "--name-only", "origin/main", "launch/divisions/"],
                        capture_output=True, text=True).stdout.split()
    for path in ls:
        for r in rows(path):
            rid = r.get("id", "")
            if not re.match(r"^[A-Z]{2,3}-\d+", rid):
                continue
            launch[rid] = r
            if CLOSED.match(r.get("status", "")):
                continue
            add(match(r.get("owner")), r, id=rid, kind="launch", text=r.get("item", ""), owner_text=r.get("owner"),
                status=r.get("status"), due=r.get("target"), dependency=r.get("dependency"), ledger=r.get("ledger"), file=path)

    # Why each launch row is at risk. A blocker counts only while it is itself open.
    def launch_risk(it):
        st, due = (it.get("status") or "").lower(), parse_date(it.get("due"), day.year)
        if st.startswith("blocked"):
            return "blocked"
        blockers = [b for b in re.findall(r"[A-Z]{2,3}-\d+", (it.get("dependency") or "").split("Blocked by:")[-1])
                    if "blocked by" in (it.get("dependency") or "").lower() and not CLOSED.match((launch.get(b) or {}).get("status", "done"))
                    and not (launch.get(b) or {}).get("status", "").lower().startswith("ready")]
        if due and due < day and not st.startswith("ready"):
            return f"past its {due:%b %-d} target ({it.get('status')})"
        if due and (due - day).days <= 7 and not st.startswith("ready"):
            return f"due {due:%b %-d}, {it.get('status')}" + (f", waiting on {', '.join(blockers)}" if blockers else "")
        if blockers and due and (due - day).days <= 14:
            return f"waiting on {', '.join(blockers)} (target {due:%b %-d})"
        if st.startswith("unknown") and due and (due - day).days <= 14:
            return f"no status reported, target {due:%b %-d}"
        return None

    for it in out:
        if it["kind"] == "launch":
            it["risk"] = launch_risk(it)
    # Rows a risky launch row cites (its Ledger column) inherit the risk; gaps flagged At risk count on their own;
    # actions count when overdue or due within two days.
    cited = {}
    for it in out:
        if it["kind"] == "launch" and it.get("risk"):
            for k in re.findall(r"\b[ADG]\d+\b", it.get("ledger") or ""):
                cited.setdefault(k, it["id"])
    for it in out:
        if it["kind"] == "launch":
            continue
        due = parse_date(it.get("due"), day.year) if it["kind"] == "action" else None
        if it["id"] in cited:
            it["risk"] = f"holds up {cited[it['id']]}"
        elif it["kind"] == "gap" and re.search(r"\bat risk\b", it["text"], re.I):
            it["risk"] = "flagged at risk in the row"
        elif due and (due - day).days <= 2:
            it["risk"] = f"due {due:%b %-d}" if due >= day else f"overdue since {due:%b %-d}"
        else:
            it["risk"] = None
    for it in out:
        it["url"] = LEDGER_URL + it.pop("file")
    return out


def queue_items(match, skip_id):
    """Brain queue items with a pending step owned by an attendee (what the owner is waiting on them for)."""
    out = []
    for it in load_items():
        if it.get("id") == skip_id or it.get("type") == "meeting" or it.get("status") not in ("open", "waiting", "working", "snoozed"):
            continue
        for s in it.get("steps") or []:
            if s.get("status", "todo") not in PENDING:
                continue
            for n in match(s.get("owner")):
                out.append({"owner": n, "source": "queue", "id": it["id"], "step_id": s["id"], "kind": it.get("type"),
                            "text": f"{it.get('title', '')}: {s.get('text', '')}", "status": it.get("status"),
                            "due": it.get("due"), "url": f"http://127.0.0.1:{app_port()}/#item={it['id']}"})
    return out


def app_port():
    f = ROOT / "state" / "app.port"
    return f.read_text().strip() if f.exists() else "7878"


def collect(item_id):
    """The agenda's raw material: at-risk ledger rows owned by someone on the call. Rows not at risk, and the brain
    queue's waiting steps, go in as context only (items.json "context"), so the agent can merge and check, not add."""
    item = json.loads((ITEMS / f"{item_id}.json").read_text())
    names = [a["name"] for a in item["meeting"]["attendees"]]
    match = matcher(names)
    day = datetime.fromisoformat(item["meeting"]["start"]).astimezone(ET).date()
    rows = ledger_items(match, day)
    risky = [r for r in rows if r.get("risk")]
    by = {n: [r for r in risky if r["owner"] == n] for n in names}
    unmatched = [n for n in names if len(n.replace(" ", "")) < 3]
    work = AGENTS / item_id / "s1"
    work.mkdir(parents=True, exist_ok=True)
    (work / "items.json").write_text(json.dumps({
        "at_risk": by, "unmatched_attendees": unmatched,
        "context": {"not_at_risk": [r for r in rows if not r.get("risk")], "queue": queue_items(match, item_id)},
    }, indent=1, ensure_ascii=False))
    lines = [f"# At-risk ledger items owned by attendees ({len(risky)}), as of {day:%b %-d}", ""]
    if unmatched:
        lines += [f"Couldn't match these calendar names to owners: {', '.join(unmatched)}. Find who they are (email in the item) before ranking.", ""]
    for n, xs in by.items():
        lines.append(f"## {n} ({len(xs)})")
        lines += [f"- [{x['id']}] {x['text'][:240]} (risk: {x['risk']})" + (f" (status: {x['status']})" if x.get("status") else "")
                  + (f" (open PR #{x['pending_pr']} changes this row)" if x.get("pending_pr") else "") for x in xs] or ["- nothing at risk"]
        lines.append("")
    lines.append(f"Not at risk ({len(rows) - len(risky)} rows) and queue steps are in items.json under context; don't put them on the agenda.")
    (work / "items.md").write_text("\n".join(lines))
    return by


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "events":
        print(json.dumps(events(sys.argv[2] if len(sys.argv) > 2 else None), indent=1))
    elif cmd == "collect" and len(sys.argv) == 3:
        by = collect(sys.argv[2])
        print("\n".join(f"{n}: {len(xs)}" for n, xs in by.items()))
    else:
        sys.exit(__doc__)
