"""Queue app server. Python stdlib only. Binds to 127.0.0.1.

Items live in queue/items/<id>.json (written by leads). Each item is a path to done:
a list of steps, each with an owner. The owner acts on steps (do it, done elsewhere, skip)
or on the whole item (done elsewhere, waiting on someone, snooze, delegate, dismiss).
The server owns item status: it is computed from the steps.

Every action is appended to log/actions.jsonl with the original and final draft and
The owner's input, which distill reads.
"""

import json
import secrets
import threading
import traceback
import os
import re
import hashlib
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "queue" / "items"
LOG = ROOT / "log" / "actions.jsonl"
SYNOPSIS = ROOT / "synopsis"
STATE = ROOT / "state"
INDEX = Path(__file__).resolve().parent / "index.html"
ET = ZoneInfo("America/New_York")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else int((json.loads((ROOT / "config" / "brain.json").read_text()) if (ROOT / "config" / "brain.json").exists() else {}).get("port") or 7878)   # main() may move it
# A fresh secret per launch, embedded in the page: every /api call must carry it, so other sites and other local
# pages cannot drive the app even when the browser sends the request.
TOKEN = secrets.token_urlsafe(32)
ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
MAX_BODY = 1_000_000
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")   # item, step and area ids: they become file and folder names

STICKY = {"snoozed", "delegated", "dismissed", "stale"}
PENDING = {"todo", "queued", "failed"}
ITEM_ACTIONS = {"note", "done_elsewhere", "waiting", "snooze", "delegate", "dismiss", "reopen", "ask", "feedback"}
STEP_ACTIONS = {"do_step", "step_done_elsewhere", "skip_step", "edit_step", "revise_step", "agent_step", "take_back", "apply_draft", "nudge", "talk"}
AGENTS = ROOT / "agents"
sys.path.insert(0, str(ROOT / "bin"))
from identity import OWNER, is_owner  # noqa: E402  (config/brain.json)
import identity  # noqa: E402
from stale import stale_info  # noqa: E402  (shared with the hourly notifier)
import checks  # noqa: E402  (item invariants; docs/incidents.md)
import meetings  # noqa: E402  (meetings the owner runs: calendar, agenda, debrief)
import agent_session  # noqa: E402
import press  # noqa: E402
import reply_gate  # noqa: E402  (the owner's presses: the only thing that lets the executor act)
import connectors  # noqa: E402  (config/connectors.json: what runs may read)  (Talk: the owner and a step's research agent)


def now():
    return datetime.now(ET).isoformat(timespec="seconds")


def parse(ts):
    """ISO time; a time with no zone is read as ET, so comparing it with aware times never raises."""
    try:
        d = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    return d.replace(tzinfo=ET) if d.tzinfo is None else d


def lock_live(name):
    """A run's lock counts only while its process is alive; crashed or killed runs leave stale locks."""
    lock = STATE / f"{name}.lock"
    if not lock.exists():
        return False
    try:
        os.kill(int((lock / "pid").read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def write_json(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem + ".", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)




def ensure_steps(item):
    """Older items carry one item-level draft; turn it into a single step owned by the owner."""
    if not item.get("steps"):
        item["steps"] = [{
            "id": "s1", "text": item.get("title", ""), "owner": OWNER, "status": "todo",
            "draft": item.get("draft", ""), "execute": item.get("execute") or {"kind": "none"},
        }]
    return item["steps"]


def compute_status(item):
    if item.get("status") in STICKY:
        return item["status"]
    steps = ensure_steps(item)
    pending = [s for s in steps if s.get("status", "todo") in PENDING]
    if not pending:
        if any(s.get("status") == "done_elsewhere" and not s.get("reconciled_at") for s in steps):
            return "reconciling"
        return "done"
    nxt = pending[0]
    # The owner did an earlier step outside the app: what follows may depend on what he actually said,
    # so his next step waits (In progress) until the lead has read it and redrafted.
    if is_owner(nxt.get("owner")) and any(s.get("status") == "done_elsewhere" and not s.get("reconciled_at")
                                         for s in steps[:steps.index(nxt)]):
        return "reconciling"
    # A failed step (blocked agent, failed send) always comes back to the owner to decide.
    if nxt.get("status") == "failed":
        return "open"
    # In progress: something is underway that comes back to the owner (or runs his action).
    if (item.get("redraft_requested") or "") > (item.get("redrafted_at") or ""):
        return "working"
    if (nxt.get("revise_requested") or "") > (nxt.get("revised_at") or ""):
        return "working"
    if nxt.get("status") == "queued":
        return "working"
    if (nxt.get("owner") or "").strip().lower() == "agent":
        # Only the owner starts agents (agent_step sets agent.requested_at). A step a lead
        # labelled "agent" on its own is treated as the owner's, so it lands in Needs me.
        return "working" if (nxt.get("agent") or {}).get("requested_at") else "open"
    return "open" if is_owner(nxt.get("owner")) else "waiting"


def current_step(item):
    for s in ensure_steps(item):
        if s.get("status", "todo") in PENDING:
            return s
    return None


def safe_checks(item):
    """One malformed item must not take the whole queue down: report the check failure on that item instead."""
    try:
        return checks.run(item)
    except Exception as e:  # noqa: BLE001
        return [{"code": "K0", "level": "warn", "msg": f"Checks failed on this item ({type(e).__name__}: {e})"[:200]}]


def load_items():
    items = []
    current = datetime.now(ET)
    for f in ITEMS.glob("*.json"):
        try:
            item = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        changed = False
        until = parse(item.get("snooze_until"))
        if item.get("status") == "snoozed" and until and until <= current:
            item["status"] = "open"
            item.setdefault("history", []).append({"ts": now(), "by": "app", "event": "unsnoozed"})
            changed = True
        for s in item.get("steps") or []:      # one spelling for the owner's steps: the token (identity.OWNER_NAMES)
            o = (s.get("owner") or "").strip()
            if o and o != OWNER and is_owner(o):
                s["owner"] = OWNER
                changed = True
        had_steps = bool(item.get("steps"))
        status = compute_status(item)
        if status != item.get("status") or not had_steps:
            if status != item.get("status"):
                item.setdefault("history", []).append({"ts": now(), "by": "app", "event": f"status {item.get('status')} -> {status}"})
            item["status"] = status
            changed = True
        if changed:
            write_json(f, item)
        items.append(item)
    return items


def next_morning():
    t = datetime.now(ET) + timedelta(days=1)
    return t.replace(hour=8, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def executor_watch():
    """A step pressed while the executor was finishing can be left queued: restart the executor for steps the owner
    pressed over a minute ago. Runs in the background, never on a page load; the executor refuses unpressed steps."""
    while True:
        threading.Event().wait(60)
        try:
            cutoff = datetime.now(ET) - timedelta(minutes=1)
            stuck = any(s.get("status") == "queued" and (parse(s.get("queued_at")) or cutoff) < cutoff
                        and press.pressed(it["id"], s)
                        for f in ITEMS.glob("*.json") for it in [json.loads(f.read_text())] for s in it.get("steps") or [])
            if stuck and not lock_live("execute"):
                spawn("execute.sh")
            reply_gate.sweep()        # retire replies that stopped being the owner's (bin/reply_gate.py)
        except Exception:
            pass


def slim(item):
    """What the app shows: item history, each step's basis and the made_by stamps stay on disk (agents read them there)."""
    out = {k: v for k, v in item.items() if k not in ("history", "made_by")}
    out["steps"] = [{**{k: v for k, v in s.items() if k not in ("basis", "made_by")},
                     **({"new_recipient": True} if s.get("status", "todo") in PENDING and press.new_recipient(item, s) else {})}
                    for s in item.get("steps") or []]
    return out


def talk_view(item_id, step_id):
    """The Talk panel: the conversation with the step's agent, whether it is running, and what it is doing right now
    (its latest tool calls and notes from the live trace)."""
    running = lock_live(f"agent-{item_id}")
    live = []
    cur = STATE / f"agent-{item_id}.current"
    if running and cur.exists():
        trace = Path(cur.read_text().strip() + ".trace.jsonl")
        try:
            lines = trace.read_text().splitlines()[-200:] if trace.exists() else []
        except OSError:
            lines = []
        for line in lines:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = ev.get("message")
            if ev.get("type") != "assistant" or not isinstance(m, dict):
                continue
            for c in m.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and c.get("text", "").strip():
                    live.append({"kind": "text", "text": c["text"].strip()[:400]})
                elif c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    arg = inp.get("query") or inp.get("pattern") or inp.get("file_path") or inp.get("url") or inp.get("command") \
                        or inp.get("channel_id") or inp.get("description") or ""
                    name = re.sub(r"^mcp__claude_ai_", "", c.get("name", "")).replace("__", ": ").replace("_", " ")
                    live.append({"kind": "tool", "text": f"{name}: {str(arg)[:120]}" if arg else name})
    msgs = agent_session.messages(item_id, step_id)
    if not msgs:  # an agent that ran before Talk existed: show its brief and report as the conversation so far
        f = ITEMS / f"{item_id}.json"
        item = json.loads(f.read_text()) if f.exists() else {}
        st = next((x for x in item.get("steps") or [] if x.get("id") == step_id), {})
        rep = AGENTS / item_id / step_id / "REPORT.md"
        if (st.get("agent") or {}).get("brief"):
            msgs.append({"ts": st["agent"].get("requested_at", ""), "role": "brief", "text": st["agent"]["brief"]})
        if rep.exists():
            msgs.append({"ts": st.get("done_at", ""), "role": "agent", "text": rep.read_text().strip().split("\n")[0][:600], "report": True})
    return {"messages": msgs, "running": running, "live": live[-25:],
            "has_session": bool(agent_session.session(item_id, step_id)),
            "report": (AGENTS / item_id / step_id / "REPORT.md").exists()}


# ---------- connectors ----------
CONN_STATUS = STATE / "connectors-status.json"


def connectors_view(refresh=False):
    """The Connectors page: the catalog (curated order), what this brain reads (config/connectors.json), and each
    connector's live state from `claude mcp list` (cached; about 10 s to read, so it refreshes in the background)."""
    import threading
    cached = json.loads(CONN_STATUS.read_text()) if CONN_STATUS.exists() else {}
    age = (datetime.now(ET) - parse(cached.get("ts"))).total_seconds() if cached.get("ts") else 1e9
    if (refresh or age > 300) and not getattr(connectors_view, "busy", False):
        def run():
            connectors_view.busy = True
            try:
                CONN_STATUS.write_text(json.dumps({"ts": now(), "live": connectors.status(), "claude": connectors.claude(),
                                                   "stats": connectors.stats()}))
            except Exception:
                pass
            connectors_view.busy = False
        threading.Thread(target=run, daemon=True).start()
    cat = json.loads((ROOT / "config" / "connector-catalog.json").read_text())
    live = {c["name"].lower(): c for c in cached.get("live") or []}
    mine = {c["name"].lower(): c for c in connectors.registry()}
    stats = (cached.get("stats") or {}).get("by_connector") or {}

    def setup(k):
        c = mine.get(k)
        if not c:
            return {}
        t = STATE / f"connector-test-{c['server']}.json"
        try:
            test = json.loads(t.read_text()) if t.exists() else None
        except json.JSONDecodeError:
            test = None
        added = parse(c.get("added_at"))
        st = stats.get(c["name"]) or {}
        quiet = (connectors.role(c) == "watch" and st and not st.get("items") and (not added or added < datetime.now(ET) - timedelta(days=7)))
        return {"role": connectors.role(c), "cadence": c.get("cadence") or "every", "areas": c.get("areas") or [],
                "required": bool(c.get("required")), "use": c.get("use") or "", "stats": st, "test": test,
                "suggest_lookup": bool(quiet), "last_read": {a: r.get(c["name"]) for a, r in reads.items() if r.get(c["name"])}}
    try:
        reads = json.loads((STATE / "connectors-read.json").read_text())
    except (OSError, json.JSONDecodeError):
        reads = {}
    rows, seen = [], set()
    for n, c in enumerate(cat["catalog"]):
        k = c["name"].lower(); seen.add(k)
        rows.append({**c, "rank": n + 1, "state": (live.get(k) or {}).get("state", "not_connected"), "added": k in mine,
                     "server": (mine.get(k) or live.get(k) or {}).get("server") or "claude_ai_" + re.sub(r"[^A-Za-z0-9]+", "_", c["name"]).strip("_"),
                     "discovery": (mine.get(k) or {}).get("discovery"), "tools": len((mine.get(k) or {}).get("read_tools") or []),
                     **setup(k)})
    for k, c in live.items():  # on the account but not in the catalog
        if k not in seen:
            rows.append({"name": c["name"], "category": "On your account", "about": "", "use": "anything relevant to the open items",
                         "rank": len(rows) + 1, "state": c["state"], "added": k in mine, "server": c["server"],
                         "discovery": (mine.get(k) or {}).get("discovery"), "tools": len((mine.get(k) or {}).get("read_tools") or []),
                         **setup(k)})
    return {"claude": cached.get("claude"), "areas": sorted(p.stem for p in (ROOT / "leads").glob("*.md") if not p.stem.startswith("_")),
            "testing": sorted(p.name[len("conntest-"):-len(".lock")] for p in STATE.glob("conntest-*.lock") if lock_live(p.name[:-5])),
            "connect_url": cat.get("connect_url"), "checked_at": cached.get("ts"), "checking": getattr(connectors_view, "busy", False),
            "connectors": rows}


def connectors_post(action, body):
    name, server = (body.get("name") or "").strip(), (body.get("server") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{1,79}", server or "x") or len(name) > 60 or len(body.get("use") or "") > 300 \
            or not re.fullmatch(r"[\w .&()+/-]{0,60}", name):
        return 400, {"error": "bad connector"}
    if action == "add":
        if not connectors.add(name, server, body.get("use") or "anything relevant to the open items"):
            return 200, {"ok": True, "already": True}
        spawn("connector-discover.sh", server)
        return 200, {"ok": True}
    if action == "retry":
        spawn("connector-discover.sh", server)
        return 200, {"ok": True}
    if action == "remove":
        if any(c["server"] == server and c.get("required") for c in connectors.registry()):
            return 400, {"error": f"{name} is required by every run; it can't be removed here"}
        connectors.remove(server)
        return 200, {"ok": True}
    if action == "settings":
        if not connectors.settings(server, {k: body.get(k) for k in ("role", "areas", "cadence", "use", "required")}):
            return 404, {"error": "not in your brain"}
        return 200, {"ok": True}
    if action == "test":
        area = body.get("area") or identity.CFG.get("default_area") or ""
        c = next((x for x in connectors.registry() if x["server"] == server), None)
        if not c or not c.get("read_tools"):
            return 400, {"error": "Add it and let it find its read tools first"}
        if not ID_RE.match(area) or not (ROOT / "leads" / f"{area}.md").exists():
            return 400, {"error": "unknown area"}
        if lock_live(f"conntest-{server}"):
            return 200, {"ok": True, "already": True}
        spawn("connector-test.sh", server, area)
        return 200, {"ok": True}
    if action == "refresh":
        connectors_view(refresh=True)
        return 200, {"ok": True}
    return 404, {"error": "unknown action"}


# Children get a PATH that finds Homebrew and Claude Code (as bin/_env.zsh sets): the app runs under launchd, whose bare
# PATH hid gh and stopped the meeting agent and PR steps before they started (Nov 16, Nov 17).
CHILD_ENV = {**os.environ, "PATH": ":".join([str(Path.home() / ".local/bin"), str(Path.home() / ".claude/local"),
                                             "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"])}


def spawn(script, *args):
    """Start a script in the background. Its output goes to logs/spawn-<script>.log, so a start that fails is never silent."""
    log = open(ROOT / "logs" / f"spawn-{Path(script).stem}.log", "a")
    log.write(f"\n== {now()} {script} {' '.join(args)}\n")
    log.flush()
    subprocess.Popen([str(ROOT / "bin" / script), *args], cwd=ROOT, env=CHILD_ENV,
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()


def act(item_id, body):
    path = ITEMS / f"{item_id}.json"
    if not ID_RE.match(item_id or "") or not path.exists():
        return 404, {"error": "not found"}
    if body.get("step_id") is not None and not ID_RE.match(str(body.get("step_id"))):
        return 400, {"error": "bad step id"}
    action = body.get("action")
    if action not in ITEM_ACTIONS | STEP_ACTIONS:
        return 400, {"error": f"unknown action {action}"}
    item = json.loads(path.read_text())
    steps = ensure_steps(item)
    note = (body.get("note") or "").strip()
    redraft = bool(body.get("redraft"))
    created = parse(item.get("created"))
    ts = now()
    step = None
    original_draft = final_draft = None
    run_executor = False
    run_reviser = False
    run_agent = False
    run_chat = False
    run_meeting = None
    run_talk = None

    if action == "apply_draft" and not any(s.get("id") == body.get("step_id") and s.get("status", "todo") in PENDING for s in steps):
        # The draft is for a step already resolved (or none is pending): add it as a new follow-up step after the last one.
        base = next((s for s in steps if s.get("id") == body.get("step_id")), None) or (steps[-1] if steps else {})
        ex = dict(base.get("execute") or {"kind": "none"})
        if ex.get("kind") in ("pr_request_changes", "pr_approve", "pr_merge"):
            ex["kind"] = "pr_comment"
        ex.pop("medium_why", None)
        new_id = "s" + str(max([int(x["id"][1:]) for x in steps if str(x.get("id", "")).startswith("s") and x["id"][1:].isdigit()] or [0]) + 1)
        steps.append({"id": new_id, "text": "Send the follow-up" + (f" to {ex['target_label']}" if ex.get("target_label") else ""), "owner": OWNER, "status": "todo", "execute": ex, "added_by": "chat"})
        body["step_id"] = new_id
    if action in STEP_ACTIONS:
        step = next((s for s in steps if s.get("id") == body.get("step_id")), None)
        if not step:
            return 400, {"error": "step not found"}
        original_draft = step.get("draft", "")
        final_draft = body.get("draft", original_draft)
        step["draft"] = final_draft
        if action == "do_step" and step.get("revise_requested") and step.get("revise_requested") > (step.get("revised_at") or ""):
            return 409, {"error": "A revision is in progress for this step. Wait for it, or edit the draft yourself and try again after it lands."}
        if action == "do_step":
            # Checks are enforced here, not just shown: a blocking failure needs the owner's explicit override.
            failed = checks.blocking({**item, "steps": steps}, step["id"])
            if failed and not body.get("override"):
                return 409, {"error": failed[0]["msg"], "checks": failed}
            if failed:
                step.setdefault("overrides", []).append({"ts": ts, "checks": [c["code"] for c in failed]})
            kind = (step.get("execute") or {}).get("kind", "none")
            if kind == "none":
                step.update(status="done", done_at=ts, done_by=OWNER)
                learned = (body.get("learned") or "").strip()
                if step.get("meeting_phase") == "reconcile":
                    # The owner settled the differences between his notes and the meeting notes: every later update step
                    # waits on a redraft from his answer (do_step refuses a step with a pending revision).
                    if not learned:
                        step.update(status="todo", done_at=None, done_by=None)
                        return 400, {"error": "Say how the differences settle first"}
                    step["result"] = learned
                    for x in steps[steps.index(step) + 1:]:
                        if x.get("status", "todo") in PENDING and is_owner(x.get("owner")) and (x.get("execute") or {}).get("kind", "none") != "none":
                            x["revise_requested"] = ts
                            x.setdefault("revisions", []).append({"ts": ts, "draft_before": x.get("draft", ""),
                                "note": f"the owner settled the note differences: {learned}"})
                    run_meeting = step["id"]
                elif learned:
                    # The owner did it live (a call, a review) and says what came of it: record it, close the step that only
                    # waited on that answer, and redraft his next message from it.
                    step["result"] = learned
                    rest = steps[steps.index(step) + 1:]
                    nxt = next((x for x in rest if x.get("status", "todo") in PENDING), None)
                    if nxt and not is_owner(nxt.get("owner")) and (nxt.get("owner") or "").lower() != "agent":
                        nxt.update(status="done", done_at=ts, done_by=nxt.get("owner"), result=learned,
                                   evidence=[{"label": "the owner, from the conversation", "url": ""}])
                        rest = rest[rest.index(nxt) + 1:]
                    mine = next((x for x in rest if x.get("status", "todo") in PENDING and is_owner(x.get("owner"))
                                 and (x.get("execute") or {}).get("kind", "none") != "none"), None)
                    if mine:
                        mine["revise_requested"] = ts
                        mine.setdefault("revisions", []).append({"ts": ts, "draft_before": mine.get("draft", ""),
                            "note": f"the owner did \"{step.get('text')}\" and learned: {learned}. Redraft this step from that; it is authoritative."})
                        run_reviser = True
                nxt = next((s for s in steps if s.get("status", "todo") in PENDING), None)
                if item.get("type") == "meeting" and nxt and nxt.get("meeting_phase") == "debrief":
                    nxt["agent"] = {"brief": "meeting debrief", "requested_at": ts, "previous_owner": "agent"}
                    run_meeting = nxt["id"]
            elif kind == "queue_update":
                code, res = apply_queue_update(item_id, step, ts)
                if code != 200:
                    return code, res
                # The update may have changed this very item: continue from the saved copy, not the stale one.
                item = json.loads(path.read_text())
                steps = ensure_steps(item)
                step = next(s for s in steps if s.get("id") == body.get("step_id"))
                step.update(status="done", done_at=ts, done_by="app", result=res["result"])
            else:
                step.update(status="queued", queued_at=ts)
                press.record(item_id, step)   # the executor acts only on a press that matches the step exactly
                run_executor = True
        elif action == "step_done_elsewhere":
            # A note helps the lead find it; without one it searches the step's sources (Nov 18: an empty note did nothing).
            step.update(status="done_elsewhere", done_at=ts, done_by=OWNER, elsewhere_note=note)
            run_reviser = True
        elif action == "nudge":
            # A follow-up for a step someone else owes: a new step of the owner's, before theirs, drafted by the reviser.
            # Nothing is sent until the owner presses Send on it.
            owner = step.get("owner") or "them"
            if (owner or "").lower() in (OWNER, "agent"):
                return 400, {"error": "Nudge works on steps someone else owes"}
            ask_note = (f"Draft a short, friendly nudge to {owner} asking where this stands: {step.get('text', '')}. "
                        "Post it in the thread or DM where it was agreed (see the item's evidence). Plain words, one or two lines."
                        + (f" the owner adds: {note}" if note else ""))
            nudge = {"id": f"nudge-{uuid.uuid4().hex[:6]}", "text": f"Nudge {owner.split()[0]}", "owner": OWNER, "status": "todo", "draft": "",
                     "execute": {"kind": "slack_send"}, "revise_requested": ts, "revisions": [{"ts": ts, "note": ask_note, "draft_before": ""}]}
            steps.insert(steps.index(step), nudge)
            step["draft"] = original_draft
            run_reviser = True
        elif action == "revise_step":
            if item.get("area") == "meetings":
                return 400, {"error": "Revise isn't wired for meeting items. Edit the draft yourself, or use Ask."}
            if not note:
                return 400, {"error": "Say what needs to change"}
            step["revise_requested"] = ts
            step.setdefault("revisions", []).append({"ts": ts, "note": note, "draft_before": final_draft})
            run_reviser = True
        elif action == "agent_step":
            if not note:
                return 400, {"error": "Tell the agent what to find or do"}
            prev = (step.get("agent") or {}).get("previous_owner") if (step.get("owner") or "").lower() == "agent" else step.get("owner")
            step["agent"] = {"brief": note, "requested_at": ts, "previous_owner": prev or OWNER}
            step.update(owner="agent", status="todo")
            step.pop("error", None)
            if step.get("meeting_phase"):
                run_meeting = step["id"]
            else:
                agent_session.append(item_id, step["id"], "brief", note)
                run_agent = True
        elif action == "talk":
            # The owner writes to the step's agent (Talk panel). The first message starts it; later ones resume its session.
            if not note:
                return 400, {"error": "Write something to the agent"}
            if step.get("meeting_phase"):
                return 400, {"error": "Meeting agents run from the Meetings page"}
            sid = step["id"]
            worked = agent_session.session(item_id, sid) or lock_live(f"agent-{item_id}") \
                or agent_session.messages(item_id, sid) or (AGENTS / item_id / sid / "REPORT.md").exists()
            if not worked:
                # Nothing to continue: this is the hand-off that starts the agent on the step.
                return act(item_id, {**body, "action": "agent_step"})
            # A reply. It never changes the step's owner or status, so nothing leaves the owner's to-do.
            agent_session.backfill(item_id, sid, (step.get("agent") or {}).get("brief"))
            agent_session.append(item_id, sid, OWNER, note)
            run_talk = sid
        elif action == "apply_draft":
            idx = body.get("chat_index")
            chat = item.get("chat") or []
            if not isinstance(idx, int) or not (0 <= idx < len(chat)) or not chat[idx].get("proposed_draft"):
                return 400, {"error": "No proposed draft there"}
            final_draft = chat[idx]["proposed_draft"]
            step["draft"] = final_draft
            chat[idx]["applied_at"] = ts
        elif action == "take_back":
            prev = (step.get("agent") or {}).get("previous_owner") or OWNER
            step.update(owner=OWNER if prev.strip().lower() == "agent" else prev, status="todo")
            step.pop("error", None)
        elif action == "skip_step":
            step.update(status="skipped", done_at=ts, skip_note=note)
    else:
        if action == "done_elsewhere":
            for s in steps:
                if s.get("status", "todo") in PENDING:
                    s.update(status="done_elsewhere", done_at=ts, done_by=OWNER, elsewhere_note=note)
        elif action == "waiting":
            who = (body.get("who") or "").strip()
            if not who:
                return 400, {"error": "Name who it is waiting on"}
            nxt = current_step(item)
            pos = steps.index(nxt) if nxt else len(steps)
            steps.insert(pos, {"id": f"w{uuid.uuid4().hex[:6]}", "text": note or f"{who} responds", "owner": who,
                               "status": "todo", "added_by": OWNER, "added_at": ts})
        elif action == "snooze":
            item["status"] = "snoozed"
            item["snooze_until"] = body.get("snooze_until") or next_morning()
        elif action == "delegate":
            who = (body.get("who") or "").strip()
            if not who:
                return 400, {"error": "Name who it goes to"}
            item["status"] = "delegated"
            item["delegated_to"] = who
        elif action == "dismiss":
            item["status"] = "dismissed"
        elif action == "reopen":
            item["status"] = "open"
        elif action == "feedback":
            rating = body.get("rating")
            tags = [x for x in (body.get("tags") or []) if isinstance(x, str)][:8]
            if rating not in ("up", "down", None) or not (rating or tags or note):
                return 400, {"error": "Pick a rating or a tag, or write a note"}
            target = next((s for s in steps if s.get("id") == body.get("step_id")), None)
            fb = {"ts": ts, "rating": rating, "tags": tags, "note": note, "step_id": (target or {}).get("id"),
                  "made_by": (target or {}).get("made_by") or item.get("made_by")}
            item.setdefault("feedback", []).append(fb)
            step = None
        elif action == "ask":
            if not note:
                return 400, {"error": "Ask something"}
            cur = current_step(item)
            item.setdefault("chat", []).append({"ts": ts, "role": OWNER, "text": note,
                                                "step_id": body.get("step_id") or (cur or {}).get("id")})
            item["chat_pending"] = ts
            run_chat = True

    if note and action not in ("ask", "feedback"):
        item.setdefault("notes", []).append({"ts": ts, "text": note, "redraft": redraft, "action": action,
                                             **({"step_id": step["id"]} if step else {})})
    if redraft:
        item["redraft_requested"] = ts
    if action in ("done_elsewhere", "step_done_elsewhere"):
        item["reconcile_requested"] = ts
    if item.get("status") not in STICKY or action == "reopen":
        item["status"] = compute_status({**item, "status": "open"} if action == "reopen" else item)
    item["updated"] = ts
    item.setdefault("history", []).append({"ts": ts, "by": OWNER, "event": action, **({"step": step["id"]} if step else {})})
    write_json(path, item)

    if run_executor and not lock_live("execute"):
        spawn("execute.sh")
    if run_chat and not lock_live(f"chat-{item_id}"):
        spawn("chat.sh", item_id)
    if run_agent and not lock_live(f"agent-{item_id}"):
        spawn("agent.sh", item_id, step["id"])
    if run_talk and not lock_live(f"agent-{item_id}"):
        spawn("agent-talk.sh", item_id, run_talk)
    if run_meeting and not lock_live(f"agent-{item_id}"):
        spawn("meeting.sh", item_id, run_meeting)
    if (redraft or run_reviser) and (ROOT / "leads" / f"{item.get('area')}.md").exists() \
            and not lock_live(f"revise-{item.get('area')}"):
        spawn("revise.sh", item["area"])

    entry = {
        "log_id": uuid.uuid4().hex[:12], "ts": ts, "item_id": item_id, "key": item.get("key"),
        "area": item.get("area"), "type": item.get("type"), "title": item.get("title"),
        "priority": item.get("priority"), "action": action, "note": note, "redraft": redraft,
        "learned": (body.get("learned") or "").strip() or None,
        "who": body.get("who"), "status_after": item["status"],
        "rating": body.get("rating"), "tags": body.get("tags"),
        "age_minutes": round((datetime.now(ET) - created).total_seconds() / 60) if created else None,
    }
    entry["made_by"] = (item.get("feedback") or [{}])[-1].get("made_by") if action == "feedback" else ((step or {}).get("made_by") or item.get("made_by"))
    if step:
        entry.update(step_id=step["id"], step_text=step.get("text"), step_owner=step.get("owner"),
                     execute_kind=(step.get("execute") or {}).get("kind", "none"),
                     edited=final_draft != original_draft, original_draft=original_draft, final_draft=final_draft)
    if action != "edit_step" or entry.get("edited"):
        with LOG.open("a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return 200, item


STEP_FIELDS = {"text", "owner", "draft", "execute", "due", "notes"}


def clean_step(s):
    """A step proposed by a run: only descriptive fields, always to-do. Status, ids and history are the app's."""
    return {k: v for k, v in (s or {}).items() if k in STEP_FIELDS} | {"status": "todo"}


QUEUE_OPS = {"note", "step_done", "add_step", "due", "create"}


def apply_queue_update(source_id, step, ts):
    """Apply a meeting debrief's proposed queue changes (the step's draft: a JSON list of operations), in code.
    Never changes a step the owner owns or already resolved. All-or-nothing: every op is checked before any file is written."""
    try:
        ops = json.loads(step.get("draft") or "[]")
        assert isinstance(ops, list) and all(isinstance(o, dict) and o.get("op") in QUEUE_OPS for o in ops)
    except (json.JSONDecodeError, AssertionError):
        return 400, {"error": "The update list isn't valid. Use Revise to have it rewritten."}
    tag = {"by": f"meeting:{source_id}"}
    touched, created, errors = {}, [], []
    for n, o in enumerate(ops, 1):
        if o["op"] == "create":
            it = o.get("item") or {}
            if not it.get("title") or not it.get("steps"):
                errors.append(f"{n}: a new item needs a title and steps")
                continue
            area = it.get("area") or identity.CFG.get("default_area") or "main"
            if not ID_RE.match(area) or not ((ROOT / "leads" / f"{area}.md").exists() or area == identity.CFG.get("default_area")):
                errors.append(f"{n}: unknown area {area}")
                continue
            iid = f"{area}-{datetime.now(ET):%Y%m%d-%H%M}-{meetings.slug(it['title'])}-{uuid.uuid4().hex[:4]}"
            created.append({**it, "id": iid, "key": f"meeting:{source_id}:{n}", "area": area,
                            "type": it.get("type") or "action", "status": "open", "created": ts, "updated": ts,
                            "steps": [{**clean_step(s), "id": f"s{k}"} for k, s in enumerate(it["steps"], 1)],
                            "history": [{"ts": ts, "event": "created", **tag}]})
            continue
        iid = o.get("item_id") or ""
        f = ITEMS / f"{iid}.json"
        if not ID_RE.match(iid) or not f.exists():
            errors.append(f"{n}: no item {iid}")
            continue
        it = touched.get(iid) or json.loads(f.read_text())
        touched[iid] = it
        ss = ensure_steps(it)
        if o["op"] == "note":
            it.setdefault("notes", []).append({"ts": ts, "text": o.get("text", ""), "action": "meeting", "redraft": False})
        elif o["op"] == "due":
            it["due"] = o.get("due")
        elif o["op"] == "step_done":
            s = next((x for x in ss if x.get("id") == o.get("step_id")), None)
            if not s or is_owner(s.get("owner")) or s.get("status", "todo") not in PENDING:
                errors.append(f"{n}: step {o.get('step_id')} on {iid} is yours, resolved or missing")
                continue
            s.update(status="done", done_at=ts, done_by=tag["by"], result=o.get("result", ""), reconciled_at=ts,
                     evidence=(s.get("evidence") or []) + (o.get("evidence") or []))
        elif o["op"] == "add_step":
            new = {**clean_step(o.get("step")), "added_at": ts, "added_by": tag["by"]}
            if not new.get("text"):
                errors.append(f"{n}: the new step on {iid} has no text")
                continue
            new["id"] = f"m{uuid.uuid4().hex[:5]}"
            after = next((k for k, x in enumerate(ss) if x.get("id") == o.get("after")), None)
            ss.insert(after + 1 if after is not None else len(ss), new)
        it.setdefault("history", []).append({"ts": ts, "event": f"meeting_{o['op']}", **tag})
    if errors:
        return 409, {"error": "Nothing applied. " + "; ".join(errors)[:400]}
    for iid, it in touched.items():
        it["updated"] = ts
        if it.get("status") not in STICKY:
            it["status"] = compute_status(it)
        write_json(ITEMS / f"{iid}.json", it)
    for it in created:
        it["status"] = compute_status(it)
        write_json(ITEMS / f"{it['id']}.json", it)
    return 200, {"result": f"Updated {len(touched)} item{'s' if len(touched) != 1 else ''}"
                           + (f", created {len(created)}" if created else "")}


def new_todo(body):
    """The owner's own to-do: something they know about that no run turned into an item. One step of theirs; with
    `plan`, the reviser drafts the steps from the note, as Redraft does."""
    title = (body.get("title") or "").strip()[:120]
    note = (body.get("note") or "").strip()[:2000]
    link = (body.get("link") or "").strip()[:500]
    due = body.get("due") or None
    area = identity.CFG.get("default_area") or "main"
    if not title:
        return 400, {"error": "Give it a title"}
    if link and not re.match(r"https?://", link):
        return 400, {"error": "The link must start with http"}
    if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        return 400, {"error": "Due is a date"}
    if not ID_RE.match(area):
        return 400, {"error": "unknown area"}
    ts = now()
    iid = f"{area}-{datetime.now(ET):%Y%m%d-%H%M}-{meetings.slug(title)}-{uuid.uuid4().hex[:4]}"
    step = {"id": "s1", "text": title, "owner": OWNER, "status": "todo", "execute": {"kind": "none", **({"url": link} if link else {})}}
    plan = bool(body.get("plan")) and (ROOT / "leads" / f"{area}.md").exists()
    item = {"id": iid, "key": f"own:{iid}", "area": area, "type": "action", "category": "action", "title": title,
            "context": note.split("\n")[0][:160], "why_owner": "You added it", "made_by": OWNER, "due": due,
            "evidence": [{"label": "link", "url": link}] if link else [], "steps": [step],
            "notes": [{"ts": ts, "text": f"Plan the steps for this to-do from the note{' and the link' if link else ''}: {note}",
                       "redraft": True, "action": "note"}] if plan else [],
            "redraft_requested": ts if plan else None, "created": ts, "updated": ts,
            "history": [{"ts": ts, "by": OWNER, "event": "created"}]}
    item["status"] = compute_status(item)
    write_json(ITEMS / f"{iid}.json", item)
    if plan and not lock_live(f"revise-{area}"):
        spawn("revise.sh", area)
    return 200, {"ok": True, "id": iid}


def monday_of(date):
    d = datetime.fromisoformat(date).date() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or "") else datetime.now(ET).date()
    return d - timedelta(days=d.weekday())


def trace_steps(prefix, since):
    """What a running agent has looked at so far, from its newest trace: the last few tool calls."""
    p = parse(since)
    traces = [f for f in (ROOT / "logs").glob(f"{prefix}*.log.trace.jsonl") if p and f.stat().st_mtime >= p.timestamp() - 5]
    out = []
    if traces:
        for line in max(traces, key=lambda f: f.stat().st_mtime).read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            for c in (ev.get("message") or {}).get("content", []) if ev.get("type") == "assistant" else []:
                if c.get("type") == "tool_use":
                    tool, inp = c["name"].split("__")[-1], c.get("input") or {}
                    arg = inp.get("query") or inp.get("pattern") or inp.get("file_path") or inp.get("command") or inp.get("url") or ""
                    out.append(f"{ARCH_TOOL_LABEL.get(tool, tool)}: {str(arg).replace(str(Path.home()), '~')[:90]}")
    return {"steps": out[-6:], "count": len(out)}


def meeting_state(item_id):
    """Where a meeting item stands, for the Meetings page: phase, live progress, and which reports exist."""
    f = ITEMS / f"{item_id}.json"
    if not f.exists():
        return None
    it = json.loads(f.read_text())
    ss = {s["id"]: s for s in it.get("steps") or []}
    running = lock_live(f"agent-{item_id}")
    has = lambda sid: (AGENTS / item_id / sid / "REPORT.md").exists()
    out = {"id": item_id, "status": it.get("status"), "agenda": has("s1"), "debrief": has("s3"), "running": running}
    for sid, phase in (("s1", "prep"), ("s3", "debrief")):
        s = ss.get(sid) or {}
        if s.get("status") == "failed":
            out.update(phase=f"{phase}_failed", error=s.get("error_short") or "The agent stopped. Retry.", step=sid)
            return out
        if s.get("status", "todo") in PENDING and (sid == "s1" or (ss.get("s2") or {}).get("status") not in PENDING):
            since = (s.get("agent") or {}).get("requested_at")
            just = parse(since) and (datetime.now(ET) - parse(since)).total_seconds() < 60  # spawned, lock not taken yet
            if running or just:
                out.update(phase=phase, progress=trace_steps(f"agent-{item_id}-", since), step=sid)
            else:
                out.update(phase=f"{phase}_failed", error="The agent isn't running. Retry.", step=sid)
            return out
    out["phase"] = "updates" if ss.get("s3", {}).get("status") == "done" else "agenda"
    # The debrief's apply steps, worked inline on the Meetings page (meeting items don't show in the queue lists).
    after = (it.get("steps") or [])[3:]
    out["steps"] = [{"id": s["id"], "text": s.get("text", ""), "status": s.get("status", "todo"), "kind": (s.get("execute") or {}).get("kind", "none"),
                     "target": (s.get("execute") or {}).get("target_label") or "", "draft": s.get("draft") or "", "result": s.get("result") or "",
                     "error": s.get("error_short") or ""} for s in after if is_owner(s.get("owner"))]
    out["open_steps"] = sum(1 for s in out["steps"] if s["status"] in PENDING)
    out["assumed"] = ((ss.get("s2") or {}).get("basis") or {}).get("assumed") or [] if isinstance((ss.get("s2") or {}).get("basis"), dict) else []
    return out


def meeting_agenda(item_id):
    """The agenda in importance order, with the owner's notes from the call attached to each line."""
    f = ITEMS / f"{item_id}.json"
    if "/" in item_id or not f.exists():
        return None
    it = json.loads(f.read_text())
    try:
        rows = json.loads((AGENTS / item_id / "s1" / "agenda.json").read_text())
    except (OSError, json.JSONDecodeError):
        rows = []
    rows = [r for r in rows if isinstance(r, dict)]
    rows.sort(key=lambda r: (bool(r.get("later")), r.get("importance") or r.get("n") or 999))
    notes = (it.get("meeting") or {}).get("notes") or []
    for r in rows:
        r["notes"] = [x for x in notes if x.get("n") == r.get("n")]
    return {"id": item_id, "rows": rows, "general": [x for x in notes if x.get("n") is None]}


def meeting_note(body):
    """the owner's note during the meeting, on one agenda line (n) or the whole meeting (n null). The debrief reads them."""
    f = ITEMS / f"{body.get('item_id') or ''}.json"
    text = (body.get("text") or "").strip()
    if "/" in str(body.get("item_id")) or not f.exists() or not text:
        return 400, {"error": "Write a note first"}
    it = json.loads(f.read_text())
    n = body.get("n") if isinstance(body.get("n"), int) else None
    it.setdefault("meeting", {}).setdefault("notes", []).append({"ts": now(), "n": n, "text": text[:4000]})
    it["updated"] = now()
    write_json(f, it)
    return 200, meeting_agenda(it["id"])


def meetings_week(date):
    mon = monday_of(date)
    days, fetched, err = [], None, None
    items = meetings.load_items()  # once for the week (events() used to reload every item for each day)
    for n in range(7):
        d = (mon + timedelta(days=n)).isoformat()
        ev = meetings.events(d, items)
        for e in ev["events"]:
            e["date"] = d
            e["state"] = meeting_state(e["item_id"]) if e.get("item_id") else None
        days.append({"date": d, "events": ev["events"]})
        fetched = fetched or ev.get("fetched_at")
        f = STATE / "calendar" / f"{d}.json"
        err = err or (json.loads(f.read_text()).get("error") if f.exists() else None)
    return {"week": mon.isoformat(), "days": days, "fetched_at": fetched, "error": err,
            "fetching": lock_live(f"calendar-{mon.isoformat()}")}


def meetings_post(action, body):
    if any(c in str(body.get("item_id") or "") for c in "/\\") or ".." in str(body.get("item_id") or ""):
        return 400, {"error": "bad item id"}
    date = body.get("date") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.get("date") or "") else datetime.now(ET).date().isoformat()
    if action == "note":
        return meeting_note(body)
    if action == "redraft":
        # The owner asks for a fresh agenda (before the call): the prep step runs again; his notes stay.
        f = ITEMS / f"{body.get('item_id') or ''}.json"
        if "/" in str(body.get("item_id")) or not f.exists() or lock_live(f"agent-{body['item_id']}"):
            return 409, {"error": "Can't redraft right now."}
        it = json.loads(f.read_text())
        ss = {x["id"]: x for x in it.get("steps") or []}
        if (ss.get("s2") or {}).get("status", "todo") not in PENDING:
            return 409, {"error": "The meeting is already marked done."}
        ts = now()
        ss["s1"].update(status="todo", agent={"brief": "meeting prep (redraft)", "requested_at": ts, "previous_owner": "agent"})
        for k in ("done_at", "done_by", "result", "error", "error_short"):
            ss["s1"].pop(k, None)
        it["status"] = compute_status(it)
        it.setdefault("history", []).append({"ts": ts, "by": OWNER, "event": "redraft_agenda"})
        write_json(f, it)
        spawn("meeting.sh", it["id"], "s1")
        return 200, {"started": True}
    if action == "refresh":
        if not lock_live(f"calendar-{monday_of(date).isoformat()}"):
            spawn("calendar.sh", date)
        return 200, {"started": True}
    if action == "done":
        # The owner marks the meeting run: the "Run the meeting" step is done, which starts the debrief.
        it = next((i for i in meetings.load_items() if i.get("id") == body.get("item_id") and i.get("type") == "meeting"), None)
        run = next((s for s in (it or {}).get("steps") or [] if s.get("id") == "s2"), None)
        if not run or run.get("status", "todo") not in PENDING:
            return 409, {"error": "This meeting is already marked done."}
        return act(it["id"], {"action": "do_step", "step_id": "s2"})
    if action == "retry":
        st = meeting_state(body.get("item_id") or "")
        if not st or not st.get("step") or st.get("running"):
            return 409, {"error": "Nothing to retry."}
        return act(st["id"], {"action": "agent_step", "step_id": st["step"], "note": "retry"})
    if action == "prep":
        ev = next((e for e in meetings.events(date)["events"] if e.get("id") == body.get("event_id")), None)
        if not ev:
            return 404, {"error": "That meeting isn't in the calendar list. Refresh and try again."}
        if ev.get("item_id"):
            return 200, {"id": ev["item_id"], "existing": True}
        item = meetings.prep_item(ev, datetime.now(ET))
        write_json(ITEMS / f"{item['id']}.json", item)
        with LOG.open("a") as fh:
            fh.write(json.dumps({"log_id": uuid.uuid4().hex[:12], "ts": now(), "item_id": item["id"], "key": item["key"],
                                 "area": "meetings", "type": "meeting", "title": item["title"], "action": "meeting_prep",
                                 "status_after": item["status"]}, ensure_ascii=False) + "\n")
        spawn("meeting.sh", item["id"], "s1")
        return 200, {"id": item["id"]}
    return 404, {"error": "not found"}


def stats():
    rows = []
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    done = [r for r in rows if r["action"] == "do_step" and r.get("original_draft")]
    by_area = {}
    for r in rows:
        a = by_area.setdefault(r.get("area") or "?", {"steps_done": 0, "unchanged": 0, "elsewhere": 0, "dismissed": 0, "inputs": 0})
        if r["action"] == "do_step":
            a["steps_done"] += 1
            if r.get("original_draft") and not r.get("edited"):
                a["unchanged"] += 1
        if r["action"] in ("done_elsewhere", "step_done_elsewhere"):
            a["elsewhere"] += 1
        if r["action"] == "dismiss":
            a["dismissed"] += 1
        if r["action"] == "note":
            a["inputs"] += 1
    ages = sorted(r["age_minutes"] for r in rows if r.get("age_minutes") is not None and r["action"] != "note")
    today = datetime.now(ET).date().isoformat()
    cleared_today = sum(1 for r in rows if (r.get("ts") or "").startswith(today)
                        and r["action"] in ("do_step", "step_done_elsewhere", "skip_step", "done_elsewhere", "dismiss", "delegate"))
    return {
        "cleared_today": cleared_today,
        "total_actions": len(rows),
        "steps_done": sum(1 for r in rows if r["action"] == "do_step"),
        "unchanged_rate": round(sum(1 for r in done if not r.get("edited")) / len(done), 2) if done else None,
        "elsewhere": sum(1 for r in rows if r["action"] in ("done_elsewhere", "step_done_elsewhere")),
        "median_minutes_to_act": ages[len(ages) // 2] if ages else None,
        "by_area": by_area,
    }


USAGE = ROOT / "log" / "usage.jsonl"


def jsonl(path):
    out = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


LEARN = ROOT / "learn" / "topics"
LEARN_MODES = {"say": "continue", "ask": "ask", "quiz": "quiz", "final": "final"}


def learn_busy(t):
    """A turn is running while its lock is live, or for a minute after the spawn (before the lock exists)."""
    p = parse(t.get("pending"))
    return bool(p) and (lock_live(f"learn-{t['slug']}") or (datetime.now(ET) - p).total_seconds() < 60)


def learn_live(slug, since):
    """The tutor's reply so far, from the running turn's stream (text before the JSON block)."""
    traces = sorted((ROOT / "logs").glob(f"learn-{slug}-*.log.trace.jsonl"), key=lambda f: f.stat().st_mtime)
    p = parse(since)
    if not traces or not p or traces[-1].stat().st_mtime < p.timestamp() - 5:
        return ""
    text = ""
    for line in traces[-1].read_text().splitlines():
        try:
            ev = json.loads(line).get("event") or {}
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "message_start":
            text = ""
        elif ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
            text += ev["delta"]["text"]
    return text.split("```")[0].strip()


def learn_topic(slug):
    path = LEARN / f"{slug}.json"
    if not slug.replace("-", "").isalnum() or not path.exists():
        return None
    t = json.loads(path.read_text())
    t["busy"] = learn_busy(t)
    if t["busy"]:
        t["live"] = learn_live(slug, t.get("pending"))
    if t.get("pending") and not t["busy"]:  # the run died without answering
        t.pop("pending", None)
        t.setdefault("messages", []).append({"role": "tutor", "text": "That turn failed. Send again to retry.", "ts": now(), "error": True})
        path.write_text(json.dumps({k: v for k, v in t.items() if k != "busy"}, indent=2, ensure_ascii=False))
    return t


def learn_summary(md):
    """The first lines under the notes' Summary heading, for the Codex card."""
    m = re.search(r"#+\s*Summary\s*\n+(.+?)(?:\n#|\Z)", md or "", flags=re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:240] if m else ""


def learn_list():
    today = datetime.now(ET).date().isoformat()
    out = []
    for f in sorted(LEARN.glob("*.json")):
        t = learn_topic(f.stem)
        if not t or t.get("archived"):
            continue
        subs = t.get("subskills", [])
        out.append({"slug": t["slug"], "topic": t["topic"], "stage": t.get("stage", "new"), "created": t["created"], "updated": t.get("updated"),
                    "pct": round(100 * sum(s["level"] for s in subs) / (5 * len(subs))) if subs else 0,
                    "subskills": [{"name": s["name"], "level": s["level"]} for s in subs], "busy": t["busy"],
                    "due": sum(1 for s in subs if s.get("level", 0) > 0 and (s.get("next_review") or "9") <= today),
                    "mastered_at": t.get("mastered_at"), "summary": learn_summary(t.get("notes_md"))})
    return sorted(out, key=lambda x: x.get("updated") or "", reverse=True)


def learn_post(slug, body):
    LEARN.mkdir(parents=True, exist_ok=True)
    if slug is None:  # new topic
        topic = (body.get("topic") or "").strip()[:120]
        if not topic:
            return 400, {"error": "topic required"}
        base = "-".join("".join(c if c.isalnum() else " " for c in topic.lower()).split())[:48] or "topic"
        slug, n = base, 2
        while (LEARN / f"{slug}.json").exists():
            existing = json.loads((LEARN / f"{slug}.json").read_text())
            if existing.get("topic", "").lower() == topic.lower():
                return 200, {"slug": slug, "existing": True}
            slug, n = f"{base}-{n}", n + 1
        t = {"slug": slug, "topic": topic, "created": now(), "stage": "new", "target": 5 if body.get("mastery") else 4,
             "subskills": [], "messages": [], "history": [], "misconceptions": [], "covered": [], "notes_md": None,
             "pending": now(), "pending_mode": "start"}
        (LEARN / f"{slug}.json").write_text(json.dumps(t, indent=2, ensure_ascii=False))
        spawn("learn.sh", slug, "start")
        return 200, {"slug": slug}
    t = learn_topic(slug)
    if not t:
        return 404, {"error": "not found"}
    action = body.get("action")
    if action in ("archive", "restore"):
        t["archived"] = action == "archive"
    elif action in LEARN_MODES:
        if t["busy"]:
            return 409, {"error": "tutor is still answering"}
        text = (body.get("text") or "").strip() or {"quiz": "Quiz me on what's due.", "final": "Final assessment."}.get(action, "")
        if not text:
            return 400, {"error": "text required"}
        t.setdefault("messages", []).append({"role": OWNER, "text": text[:4000], "ts": now(), "mode": LEARN_MODES[action]})
        t["pending"], t["pending_mode"] = now(), LEARN_MODES[action]
    else:
        return 400, {"error": f"unknown action {action}"}
    t.pop("busy", None)
    (LEARN / f"{slug}.json").write_text(json.dumps(t, indent=2, ensure_ascii=False))
    if action in LEARN_MODES:
        spawn("learn.sh", slug, LEARN_MODES[action])
    return 200, {"ok": True}


ARCH = ROOT / "architect"
ARCH_IMG = ARCH / "images"
IMG_MAX = 8_000_000
IMG_KINDS = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"GIF8": "gif", b"RIFF": "webp"}
IMG_NAME = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")


def arch_image_save(body):
    """A pasted image for a Solution Architect question: checked by its first bytes (not the name it came with), saved
    under architect/images/, named by a random id. The question's turn lists it; the agent opens it with Read."""
    import base64
    data = body.get("data") or ""
    m = re.match(r"^data:image/[a-z+]+;base64,(.+)$", data, re.S)
    try:
        raw = base64.b64decode(m.group(1), validate=True) if m else b""
    except ValueError:
        raw = b""
    ext = next((e for magic, e in IMG_KINDS.items() if raw.startswith(magic)), None)
    if ext == "webp" and raw[8:12] != b"WEBP":
        ext = None
    if not ext or len(raw) > IMG_MAX:
        return 400, {"error": "Paste a PNG, JPEG, GIF or WebP image under 8 MB"}
    ARCH_IMG.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex[:16]}.{ext}"
    (ARCH_IMG / name).write_bytes(raw)
    return 200, {"name": name}


def arch_images(body):
    """The pasted images a question, follow-up or change request carries: existing files only, at most 6."""
    return [n for n in (body.get("images") or [])[:6] if isinstance(n, str) and IMG_NAME.match(n) and (ARCH_IMG / n).is_file()]
ARCH_TOOL_LABEL = {"Grep": "Searched", "Glob": "Listed", "Read": "Read", "WebSearch": "Web search", "WebFetch": "Opened",
                   "slack_search_public_and_private": "Slack search", "slack_search_public": "Slack search", "slack_read_thread": "Slack thread",
                   "slack_read_channel": "Slack channel", "search_files": "Drive search", "read_file_content": "Drive doc",
                   "list_issues": "Linear", "get_issue": "Linear issue", "Bash": "Ran"}


def arch_busy(q):
    t = (q.get("turns") or [{}])[-1]
    p = parse(t.get("pending"))
    return bool(p) and (lock_live(f"architect-run-{q['id']}") or lock_live(f"architect-{q['id']}") or lock_live(f"architect-verify-{q['id']}")
                        or (datetime.now(ET) - p).total_seconds() < 90)


def arch_progress(qid, since):
    """What the running turn has looked at so far, from its traces: the last steps, newest last."""
    p = parse(since)
    steps, phase = [], "Searching"
    for name, label in ((f"architect-lane-docs-{qid}-", "Searching docs and code"), (f"architect-lane-docs1-{qid}-", "Searching docs and code"),
                        (f"architect-lane-docs2-{qid}-", "Searching docs and code"), (f"architect-lane-live-{qid}-", "Searching Slack and Drive"),
                        (f"architect-lane-live1-{qid}-", "Searching Slack and Drive"), (f"architect-lane-live2-{qid}-", "Searching Slack and Drive"),
                        (f"architect-{qid}-", "Writing the answer"), (f"architect-verify-{qid}-", "Checking every claim")):
        traces = [f for f in (ROOT / "logs").glob(f"{name}*.log.trace.jsonl") if p and f.stat().st_mtime >= p.timestamp() - 5]
        if not traces:
            continue
        phase = label
        for line in max(traces, key=lambda f: f.stat().st_mtime).read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") != "assistant":
                continue
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") != "tool_use":
                    continue
                tool, inp = c["name"].split("__")[-1], c.get("input") or {}
                arg = inp.get("pattern") or inp.get("query") or inp.get("file_path") or inp.get("url") or inp.get("command") or inp.get("path") or ""
                arg = str(arg).replace(str(ROOT / "state" / "snapshots" / "sa") + "/", "").replace(str(Path.home()), "~")
                steps.append(f"{ARCH_TOOL_LABEL.get(tool, tool)}: {arg[:90]}")
    return {"phase": phase, "steps": steps[-8:], "count": len(steps)}


def arch_get(qid):
    path = ARCH / f"{qid}.json"
    if not qid.replace("-", "").isalnum() or not path.exists():
        return None
    q = json.loads(path.read_text())
    q["busy"] = arch_busy(q)
    t = q["turns"][-1]
    if t.get("pending") and not q["busy"]:
        t.pop("pending", None)
        t["error"] = t.get("error") or "The run stopped without an answer. Ask again to retry."
        write_json(path, {k: v for k, v in q.items() if k != "busy"})
    if q["busy"]:
        q["progress"] = arch_progress(qid, t.get("pending"))
    return q


def arch_list():
    out = []
    for f in sorted(ARCH.glob("*.json")):
        q = arch_get(f.stem)
        if not q or q.get("archived"):
            continue
        t = q["turns"][-1]
        out.append({"id": q["id"], "question": q["turns"][0]["question"][:400], "context": q.get("context", ""), "busy": q["busy"],
                    "turns": len(q["turns"]), "confidence": (t.get("final") or {}).get("confidence"), "error": bool(t.get("error")),
                    "rating": (q.get("feedback") or [{}])[-1].get("rating"), "updated": q.get("updated") or q["created"]})
    return sorted(out, key=lambda x: x["updated"], reverse=True)


def arch_log(q, action, extra):
    t = q["turns"][-1]
    entry = {"log_id": uuid.uuid4().hex[:12], "ts": now(), "item_id": f"architect:{q['id']}", "area": "architect", "type": "architect",
             "title": q["turns"][0]["question"][:120], "action": action, "made_by": t.get("made_by"), **extra}
    with LOG.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def arch_post(qid, body):
    ARCH.mkdir(parents=True, exist_ok=True)
    depth = body.get("depth") if body.get("depth") in ("quick", "exhaustive") else "exhaustive"
    if qid is None:
        text = (body.get("question") or "").strip()
        if not text:
            return 400, {"error": "Paste the question"}
        words = "-".join("".join(c if c.isalnum() else " " for c in text.lower()).split()[:6])[:40] or "question"
        qid = f"{datetime.now(ET).strftime('%m%d-%H%M')}-{words}"
        q = {"id": qid, "created": now(), "context": (body.get("context") or "").strip()[:300], "status": "working", "feedback": [],
             "turns": [{"question": text[:6000], "depth": depth, "ts": now(), "pending": now(), "images": arch_images(body)}]}
        write_json(ARCH / f"{qid}.json", q)
        arch_log(q, "ask", {"note": text[:500], "depth": depth})
        spawn("architect.sh", qid)
        return 200, {"id": qid}
    q = arch_get(qid)
    if not q:
        return 404, {"error": "not found"}
    action = body.get("action")
    if action == "followup":
        if q["busy"]:
            return 409, {"error": "Still working on the last question"}
        text = (body.get("text") or "").strip()
        if not text:
            return 400, {"error": "Ask something"}
        q["turns"].append({"question": text[:6000], "depth": depth, "ts": now(), "pending": now(), "images": arch_images(body)})
        q["status"] = "working"
        arch_log(q, "followup", {"note": text[:500], "depth": depth})
        spawn_after = True
    elif action == "revise":
        if q["busy"]:
            return 409, {"error": "Still working on the last answer"}
        text = (body.get("text") or "").strip()
        answered = [n for n, t in enumerate(q["turns"]) if t.get("final")]
        if not text or not answered:
            return 400, {"error": "Say what to change" if not text else "Nothing to modify yet"}
        target = body.get("turn") if isinstance(body.get("turn"), int) and body.get("turn") in answered else answered[-1]
        q["turns"].append({"question": text[:6000], "kind": "revise", "revises": target, "depth": depth, "ts": now(), "pending": now(),
                           "images": arch_images(body)})
        q["status"] = "working"
        # The change request is also feedback on the answer, so distill can turn repeated ones into rules.
        q.setdefault("feedback", []).append({"ts": now(), "rating": None, "tags": ["Modify"], "note": text[:2000], "turn": target,
                                             "made_by": q["turns"][target].get("made_by")})
        arch_log(q, "feedback", {"rating": None, "tags": ["Modify"], "note": text[:2000]})
        spawn_after = True
    elif action == "sent":
        # What the owner actually sent the client, pasted after editing the answer (Nov 20). Logged as an edit of the
        # architect's draft, so the daily learning run turns the differences into rules, and kept on the turn so the
        # writer sees recent real replies as examples.
        text = (body.get("text") or "").strip()
        answered = [n for n, t in enumerate(q["turns"]) if t.get("final")]
        if not text or not answered:
            return 400, {"error": "Paste what you sent" if not text else "Nothing answered yet"}
        t = q["turns"][answered[-1]]
        draft = (t.get("final") or {}).get("shareable_answer", "")
        t["sent"] = {"ts": now(), "text": text[:8000]}
        arch_log(q, "sent", {"step_text": "client answer", "execute_kind": "architect_answer", "original_draft": draft,
                             "final_draft": text[:8000], "edited": draft.strip() != text, "made_by": t.get("made_by")})
        spawn_after = False
    elif action == "retry":
        # A run that failed (signed out, stopped, no answer) runs again for the same turn; nothing else changes.
        t = q["turns"][-1]
        if q["busy"] or t.get("final") or not t.get("error"):
            return 409, {"error": "Nothing to retry"}
        t.pop("error", None)
        t["pending"] = now()
        q["status"] = "working"
        arch_log(q, "retry", {})
        spawn_after = True
    elif action == "feedback":
        rating, tags, note = body.get("rating"), [x for x in (body.get("tags") or []) if isinstance(x, str)][:8], (body.get("note") or "").strip()
        if rating not in ("up", "down", None) or not (rating or tags or note):
            return 400, {"error": "Pick a rating or a tag, or write a note"}
        t = q["turns"][-1]
        q.setdefault("feedback", []).append({"ts": now(), "rating": rating, "tags": tags, "note": note, "turn": len(q["turns"]) - 1, "made_by": t.get("made_by")})
        arch_log(q, "feedback", {"rating": rating, "tags": tags, "note": note})
        spawn_after = False
    elif action in ("archive", "copied"):
        if action == "archive":
            q["archived"] = True
        arch_log(q, action, {})
        spawn_after = False
    else:
        return 400, {"error": f"unknown action {action}"}
    q.pop("busy", None); q.pop("progress", None)
    write_json(ARCH / f"{qid}.json", q)
    if spawn_after:
        spawn("architect.sh", qid)
    return 200, {"ok": True}


def jobs_report(days=7):
    """Cost and quality per job and model over the last `days`.
    Quality (queue steps): clean accepts count 1, edited accepts 0.5, over everything the owner decided on that job's
    drafts (accept, revise, Ask fix applied, skip, dismiss)."""
    since = (datetime.now(ET) - timedelta(days=days)).isoformat()
    runs = [r for r in jsonl(USAGE) if r.get("ts", "") >= since]
    model_of = {r["run"]: r.get("model") for r in runs}
    rows = {}

    def row(job, model):
        return rows.setdefault((job, model or "default"), {"job": job, "model": model or "default", "runs": 0, "cost": 0.0,
               "tokens": 0, "turns": 0, "units": 0, "errors": 0, "clean": 0, "edited": 0, "revise": 0, "fix": 0, "skip": 0, "dismiss": 0})
    for r in runs:
        x = row(r["job"], r.get("model"))
        x["runs"] += 1; x["cost"] += r.get("cost_usd", 0); x["errors"] += r.get("error", False)
        x["turns"] += r.get("turns") or 0; x["units"] += r.get("units") or 0
        x["tokens"] += r.get("input", 0) + r.get("output", 0) + r.get("cache_read", 0) + r.get("cache_write", 0)
    for a in jsonl(LOG):
        mb = a.get("made_by") or {}
        if a.get("ts", "") < since or not mb.get("job"):
            continue
        x = row(mb["job"], model_of.get(mb.get("run")))
        act = a["action"]
        if act == "do_step" and a.get("original_draft"):
            x["edited" if a.get("edited") else "clean"] += 1
        elif act == "revise_step": x["revise"] += 1
        elif act == "apply_draft": x["fix"] += 1
        elif act == "skip_step": x["skip"] += 1
        elif act == "dismiss": x["dismiss"] += 1
        elif act == "feedback" and a.get("rating") == "up": x["clean"] += 1
        elif act == "feedback" and a.get("rating") == "down": x["revise"] += 1
    out = []
    for x in rows.values():
        q_den = x["clean"] + x["edited"] + x["revise"] + x["fix"] + x["skip"] + x["dismiss"]
        if q_den:
            x["quality"] = round((x["clean"] + 0.5 * x["edited"]) / q_den, 2); x["judged"] = q_den
        else:
            x["quality"] = None; x["judged"] = 0
        x["cost"] = round(x["cost"], 2)
        x["cost_per_day"] = round(x["cost"] / days, 2)
        x["avg_tokens"] = round(x["tokens"] / x["runs"]) if x["runs"] else None
        x["avg_turns"] = round(x["turns"] / x["runs"], 1) if x["runs"] else None
        x["cost_per_unit"] = round(x["cost"] / x["units"], 3) if x["units"] else None
        out.append(x)
    return sorted(out, key=lambda x: -x["cost"])


def synopsis():
    files = sorted(SYNOPSIS.glob("*.md"), reverse=True)
    return {"dates": [f.stem for f in files[:30]], "latest": files[0].read_text() if files else ""}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def get(self):
        path = self.path.split("?")[0]
        if path == "/":
            page = INDEX.read_text().replace("/*BRAIN_CONFIG*/{}", json.dumps({**identity.public(), "token": TOKEN}), 1)
            return self.send(200, page.encode(), "text/html; charset=utf-8")
        if path == "/api/items":
            body = json.dumps([slim({**i, "stale": stale_info(i), "checks": safe_checks(i)}) for i in load_items()], ensure_ascii=False).encode()
            tag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
            if self.headers.get("If-None-Match") == tag:  # nothing changed since the app's last poll: no body to send or parse
                self.send_response(304); self.send_header("ETag", tag); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "application/json"); self.send_header("ETag", tag)
            self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-cache")
            self.end_headers(); self.wfile.write(body); return
        if path == "/api/connectors":
            return self.send(200, connectors_view())
        if path == "/api/architect":
            return self.send(200, {"questions": arch_list()})
        if path.startswith("/api/meetings/agenda/"):
            a = meeting_agenda(path.rsplit("/", 1)[-1])
            return self.send(200, a) if a else self.send(404, {"error": "not found"})
        if path == "/api/meetings":
            qs = dict(x.split("=", 1) for x in (self.path.split("?", 1)[1:] or [""])[0].split("&") if "=" in x)
            return self.send(200, meetings_week(qs.get("week")))
        if path.startswith("/api/architect/"):
            q = arch_get(path.split("/")[3])
            return self.send(200, q) if q else self.send(404, {"error": "not found"})
        if path == "/api/learn":
            return self.send(200, {"topics": learn_list()})
        if path.startswith("/api/learn/"):
            t = learn_topic(path.split("/")[3])
            return self.send(200, t) if t else self.send(404, {"error": "not found"})
        if path == "/api/leads":
            return self.send(200, {
                "leads": [{"area": f.stem,
                           "last_run": (STATE / f"{f.stem}.last_run").read_text().strip() if (STATE / f"{f.stem}.last_run").exists() else None,
                           "running": lock_live(f"lead-{f.stem}")}
                          for f in sorted((ROOT / "leads").glob("*.md"))],
                "executor_running": lock_live("execute"),
                "agents": sorted(p.name[len("agent-"):-len(".lock")] for p in STATE.glob("agent-*.lock") if lock_live(p.name[:-5])),
                "chatting": sorted(p.name[len("chat-"):-len(".lock")] for p in STATE.glob("chat-*.lock") if lock_live(p.name[:-5])),
                "revising": sorted(p.name[len("revise-"):-len(".lock")] for p in STATE.glob("revise-*.lock") if lock_live(p.name[:-5])),
            })
        if path.startswith("/api/file/"):
            # An agent's output file to download (to attach in Slack, which the connector can't do): .md and .csv only.
            parts = path.split("/")
            if len(parts) == 6 and all(p and ".." not in p for p in parts[3:]) and parts[5].endswith((".md", ".csv")):
                f = AGENTS / parts[3] / parts[4] / parts[5]
                if f.is_file() and f.resolve().is_relative_to(AGENTS.resolve()):
                    body = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8" if f.suffix == ".md" else "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            return self.send(404, {"error": "not found"})
        if path.startswith("/api/talk/"):
            parts = path.split("/")
            if len(parts) == 5 and all(p and "." not in p and "/" not in p for p in parts[3:]):
                return self.send(200, talk_view(parts[3], parts[4]))
            return self.send(404, {"error": "not found"})
        if path.startswith("/api/architect-image/"):
            name = path.rsplit("/", 1)[-1]
            f = ARCH_IMG / name
            if IMG_NAME.match(name) and f.is_file():
                return self.send(200, f.read_bytes(), {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}[name.rsplit(".", 1)[1]])
            return self.send(404, {"error": "not found"})
        if path.startswith("/api/report/"):
            parts = path.split("/")
            if len(parts) == 5 and all(p and "." not in p for p in parts[3:]):
                f = AGENTS / parts[3] / parts[4] / "REPORT.md"
                inside = f.exists() and f.resolve().is_relative_to(AGENTS.resolve())
                return self.send(200, {"text": f.read_text() if inside else ""})
            return self.send(404, {"error": "not found"})
        if path == "/api/ops":
            files = sorted((STATE / "ops").glob("*.json"))
            return self.send(200, json.loads(files[-1].read_text()) if files else {})
        if path == "/api/jobs":
            jobs = jobs_report(7)
            return self.send(200, {"days": 7, "jobs": jobs, "total_cost": round(sum(j["cost"] for j in jobs), 2)})
        if path == "/api/stats":
            return self.send(200, stats())
        if path == "/api/synopsis":
            return self.send(200, synopsis())
        if path.startswith("/api/synopsis/"):
            f = SYNOPSIS / f"{path.rsplit('/', 1)[-1]}.md"
            return self.send(200, {"text": f.read_text()} if f.exists() and f.parent == SYNOPSIS else {"text": ""})
        self.send(404, {"error": "not found"})

    def token_ok(self):
        q = re.search(r"[?&]t=([\w-]+)", self.path)
        given = self.headers.get("X-Brain-Token") or (q.group(1) if q else "")
        return secrets.compare_digest(given, TOKEN)

    def host_ok(self):
        return (self.headers.get("Host") or "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def allowed(self):
        origin = self.headers.get("Origin")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return (self.host_ok() and (origin is None or origin in ORIGINS) and ctype == "application/json"
                and self.token_ok()
                and 0 <= int(self.headers.get("Content-Length") or 0) <= (IMG_MAX * 4 // 3 + 1000 if self.path.split("?")[0] == "/api/architect-image" else MAX_BODY))

    def fail(self, e):
        with (ROOT / "logs" / "app-errors.log").open("a") as fh:
            fh.write(f"{now()} {self.command} {self.path.split('?')[0]}\n{traceback.format_exc()}\n")
        return self.send(500, {"error": "Something went wrong. Details are in logs/app-errors.log."})

    def do_GET(self):
        try:
            if not self.host_ok():
                return self.send(403, {"error": "forbidden"})
            if self.path.startswith("/api/") and not self.token_ok():
                return self.send(403, {"error": "forbidden"})
            return self.get()
        except Exception as e:  # one bad file or log line must not drop the request
            return self.fail(e)

    def do_POST(self):
        try:
            if not self.allowed():
                return self.send(403, {"error": "forbidden"})
            return self.post()
        except Exception as e:
            return self.fail(e)

    def body(self, default, cap=MAX_BODY):
        raw = self.rfile.read(max(0, min(int(self.headers.get("Content-Length", 0)), cap)))
        data = json.loads(raw or json.dumps(default))
        if not isinstance(data, type(default)):
            raise ValueError("body must be a JSON " + type(default).__name__)
        return data

    def post(self):
        parts = self.path.strip("/").split("/")
        if parts == ["api", "ui"]:
            # Usage events from the app (views, actions and how they were triggered, panels, errors), for the weekly UX review.
            events = self.body([])
            with (ROOT / "log" / "ui.jsonl").open("a") as f:
                for ev in events[:200] if isinstance(events, list) else []:
                    if isinstance(ev, dict) and isinstance(ev.get("e"), str):
                        f.write(json.dumps({k: ev[k] for k in list(ev)[:12]}, ensure_ascii=False)[:2000] + "\n")
            return self.send(200, {"ok": True})
        if parts == ["api", "architect-image"]:
            code, payload = arch_image_save(self.body({}, IMG_MAX * 4 // 3 + 1000))
            return self.send(code, payload)
        if parts[:2] == ["api", "architect"] and len(parts) in (2, 3):
            code, payload = arch_post(parts[2] if len(parts) == 3 else None, self.body({}))
            return self.send(code, payload)
        if parts[:2] == ["api", "connectors"] and len(parts) == 3:
            code, payload = connectors_post(parts[2], self.body({}))
            return self.send(code, payload)
        if parts[:2] == ["api", "meetings"] and len(parts) == 3:
            code, payload = meetings_post(parts[2], self.body({}))
            return self.send(code, payload)
        if parts[:2] == ["api", "learn"] and len(parts) in (2, 3):
            code, payload = learn_post(parts[2] if len(parts) == 3 else None, self.body({}))
            return self.send(code, payload)
        if len(parts) == 3 and parts[:2] == ["api", "run"]:
            area = parts[2]
            if not (ROOT / "leads" / f"{area}.md").exists():
                return self.send(404, {"error": "no such lead"})
            if lock_live(f"lead-{area}"):
                return self.send(200, {"started": False, "reason": "already running"})
            spawn("run-lead.sh", area)
            return self.send(200, {"started": True})
        if parts == ["api", "items"]:
            code, payload = new_todo(self.body({}))
            return self.send(code, payload)
        if len(parts) == 4 and parts[:2] == ["api", "items"] and parts[3] == "action":
            body = self.body({})
            code, payload = act(parts[2], body)
            return self.send(code, payload)
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    os.umask(0o077)   # items, logs and state hold Slack and Drive content: owner-only files
    for d in (ITEMS, LOG.parent, SYNOPSIS, STATE, AGENTS, LEARN):
        d.mkdir(parents=True, exist_ok=True)
    # Another brain (or anything else) may hold the port: take the next free one, so a second copy, such as a sandbox
    # for trying /onboard, runs beside the first. state/app.port records where this one is.
    server = None
    for port in ([PORT] if len(sys.argv) > 1 and sys.argv[1].isdigit() else range(PORT, PORT + 20)):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if not server:
        sys.exit(f"No free port from {PORT}")
    PORT = server.server_address[1]
    ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
    (STATE / "app.port").write_text(str(PORT))
    threading.Thread(target=executor_watch, daemon=True).start()
    print(f"{identity.BRAIN_NAME} queue on http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()
