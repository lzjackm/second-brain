#!/usr/bin/env python3
"""The executor: carries out queued steps the owner pressed in the app. Plain code; no model decides what is sent.

A step runs only when bin/press.py has the owner's press for it, matching the step's target and draft exactly.
Anything else marked queued (by a lead, a debrief or a hand edit) is refused and sent back to the owner.

Per kind:
- slack_send, slack_draft, gdoc_create, gsheet_write, calendar_event: one connector call. A small model run loads
  the tool and calls it with placeholder arguments; bin/tool_guard.py swaps in the exact pressed arguments and
  blocks every other call. The model never sees the draft.
- pr_comment, pr_approve, pr_request_changes, pr_merge: gh, with the draft as a body file; merges via gh_enqueue.sh.
- brain_edit: a model run that may edit only the one brain file named; code commits it.
- ledger_pr: code picks the PR and makes a worktree; a model run may edit only inside that worktree (rows and the
  PR body); code checks only Markdown changed, commits, pushes and updates or opens the PR. Never merges.

Usage: bin/execute.py   (the app starts it on a press; one at a time)
"""
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import identity  # noqa: E402
import press  # noqa: E402

ITEMS = ROOT / "queue" / "items"
STATE = ROOT / "state"
CACHE = Path.home() / "Library" / "Caches" / identity.SLUG
PR_URL = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)/?$")
LEDGER_FILES = re.compile(r"\.md$")
os.umask(0o077)
# The app starts this under launchd, whose PATH lacks Homebrew: gh and git must still be found (Nov 16: every PR step
# crashed with "No such file: gh" and stayed Running).
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "/usr/bin:/bin")


def now():
    return datetime.now(identity.TZ).isoformat(timespec="seconds")


def tilde(p):
    p = str(p)
    return "~" + p[len(str(Path.home())):] if p.startswith(str(Path.home())) else "/" + p


class Fail(Exception):
    pass


# ---------- connector calls through the guard ----------

def placeholder(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return 0
    if isinstance(v, list):
        return []
    if isinstance(v, dict):
        return {}
    return "PLACEHOLDER"


def mcp_call(tool, args, label):
    """Call one connector tool with exactly `args`. Returns the tool's response text."""
    work = press.PRIVATE / "exec"
    work.mkdir(parents=True, exist_ok=True)
    key = uuid.uuid4().hex[:10]
    expect, result = work / f"{key}.json", work / f"{key}.result.json"
    expect.write_text(json.dumps({"tool": tool, "input": args}, ensure_ascii=False))
    prompt = STATE / f"prompt-execcall-{key}.md"
    prompt.write_text(
        f"Load the tool {tool} with ToolSearch (query \"select:{tool}\"), then call it exactly once with these "
        f"placeholder arguments: {json.dumps({k: placeholder(v) for k, v in args.items()})}. The app fills in the real "
        "arguments. Do not call anything else. Reply with one word: done.")
    env = {**os.environ, "JB_GUARD_EXPECT": str(expect), "JB_GUARD_RESULT": str(result)}
    subprocess.run([str(ROOT / "bin" / "_claude.sh"), f"execcall-{label}", str(prompt), "--allowedTools", "ToolSearch", tool],
                   cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    prompt.unlink(missing_ok=True)
    called = Path(str(expect) + ".used").exists()
    for f in (expect, Path(str(expect) + ".used")):
        f.unlink(missing_ok=True)
    if not result.exists():
        raise Fail("The connector call failed" if called else "The connector call did not run (is the connector connected?)")
    text = result.read_text()
    result.unlink()
    if re.search(r'"(ok)"\s*:\s*false|\\"error\\"|"error"\s*:', text):
        raise Fail("The connector returned an error: " + text[:200])
    return text


def first_url(text, pattern):
    m = re.search(pattern, text.replace("\\/", "/"))
    return m.group(0) if m else ""


# ---------- Markdown to HTML for Google Docs ----------

def inline(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)


def md_html(md):
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if re.match(r"^\s*\|.*\|\s*$", ln):
            rows = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                if not re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table border=\"1\">" + "".join(
                "<tr>" + "".join(f"<{'th' if n == 0 else 'td'}>{inline(c)}</{'th' if n == 0 else 'td'}>" for c in r) + "</tr>"
                for n, r in enumerate(rows)) + "</table>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", ln)
        if m:
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
        elif re.match(r"^\s*([-*]|\d+\.)\s+", ln):
            tag = "ol" if re.match(r"^\s*\d+\.", ln) else "ul"
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                items.append("<li>" + inline(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i])) + "</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    return "\n".join(out)


# ---------- kinds ----------

def do_slack(item, step):
    ex = step["execute"]
    t = press.slack_target(ex.get("target"))
    if not t:
        raise Fail("The target is not a Slack channel or user ID")
    args = {"channel_id": t[0], "message": step.get("draft") or ""}
    if t[1]:
        args["thread_ts"] = t[1]
    if not args["message"].strip():
        raise Fail("The draft is empty")
    tool = "mcp__claude_ai_Slack__slack_send_message" + ("_draft" if ex["kind"] == "slack_draft" else "")
    text = mcp_call(tool, args, f"{item['id']}-{step['id']}")
    if ex["kind"] == "slack_send":
        press.add_recipient(t[0])
    link = first_url(text, r"https://[\w.-]*slack\.com/[^\s\"'\\]+")
    return ("sent" if ex["kind"] == "slack_send" else "saved as a Slack draft"), link


def gh(*args, cwd=None):
    r = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise Fail((r.stderr or r.stdout).strip()[-300:] or "gh failed")
    return r.stdout.strip()


def pr_url(target):
    t = (target or "").strip()
    m = re.match(r"^([\w.-]+)/([\w.-]+)#(\d+)$", t)
    if m:
        t = f"https://github.com/{m.group(1)}/{m.group(2)}/pull/{m.group(3)}"
    if not PR_URL.match(t):
        raise Fail("The target is not a GitHub PR link")
    return t.rstrip("/")


def do_pr(item, step):
    ex, url = step["execute"], pr_url(step["execute"].get("target"))
    kind = ex["kind"]
    if kind == "pr_merge":
        r = subprocess.run([str(ROOT / "bin" / "gh_enqueue.sh"), url], capture_output=True, text=True)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        if r.returncode or not last:
            raise Fail((r.stderr or r.stdout).strip()[-300:] or "merge failed")
        return last, url
    body = CACHE / f"body-{uuid.uuid4().hex[:8]}.md"
    CACHE.mkdir(parents=True, exist_ok=True)
    body.write_text(step.get("draft") or "")
    try:
        if kind == "pr_comment":
            out = gh("pr", "comment", url, "--body-file", str(body))
            return "commented", first_url(out, r"https://github\.com/\S+") or url
        flag = "--approve" if kind == "pr_approve" else "--request-changes"
        gh("pr", "review", url, flag, "--body-file", str(body))
        return ("approved" if kind == "pr_approve" else "requested changes"), url
    finally:
        body.unlink(missing_ok=True)


def do_gdoc(item, step):
    ex = step["execute"]
    title = (ex.get("title") or step.get("text") or "Untitled").strip()[:200]
    args = {"title": title, "textContent": md_html(step.get("draft") or ""), "contentMimeType": "text/html"}
    if ex.get("parent_id"):
        args["parentId"] = ex["parent_id"]
    text = mcp_call("mcp__claude_ai_Google_Drive__create_file", args, f"{item['id']}-{step['id']}")
    fid = re.search(r'\\?"id\\?"\s*:\s*\\?"([\w-]{20,})', text)
    link = f"https://docs.google.com/document/d/{fid.group(1)}/edit" if fid else first_url(text, r"https://docs\.google\.com/\S+")
    for later in item["steps"][item["steps"].index(step) + 1:]:   # a later step that shares the doc gets its link
        if link and later.get("status", "todo") in ("todo", "failed") and "{{DOC_LINK}}" in (later.get("draft") or ""):
            later["draft"] = later["draft"].replace("{{DOC_LINK}}", link)
    return "doc created", link


def do_gsheet(item, step):
    ex = step["execute"]
    rows = [line.split("\t") for line in (step.get("draft") or "").splitlines() if line.strip()]
    if not (ex.get("spreadsheet_id") and ex.get("range") and rows):
        raise Fail("The sheet, range or rows are missing")
    tool = "mcp__claude_ai_Google_Sheets__" + ("append_values" if ex.get("mode") == "append" else "update_values")
    mcp_call(tool, {"spreadsheetId": ex["spreadsheet_id"], "range": ex["range"], "values": rows}, f"{item['id']}-{step['id']}")
    return f"{len(rows)} rows written", f"https://docs.google.com/spreadsheets/d/{ex['spreadsheet_id']}/edit"


def do_calendar(item, step):
    ex = step["execute"]
    try:
        start = datetime.fromisoformat(str(ex.get("start")))
    except ValueError:
        raise Fail("Set the start time in the step first")
    end = start + timedelta(minutes=int(ex.get("duration_min") or 30))
    args = {"summary": ex.get("title") or step.get("text"), "startTime": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "endTime": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "attendees": [{"email": a} for a in ex.get("attendees") or [] if re.fullmatch(r"[^@\s]+@[^@\s]+\.\w+", a)]}
    if (step.get("draft") or "").strip():
        args["description"] = step["draft"]
    text = mcp_call("mcp__claude_ai_Google_Calendar__create_event", args, f"{item['id']}-{step['id']}")
    return "invite created", first_url(text, r"https://www\.google\.com/calendar/\S+")


def edit_run(name, prompt, allowed):
    p = STATE / f"prompt-{name}.md"
    p.write_text(prompt)
    subprocess.run([str(ROOT / "bin" / "_claude.sh"), name, str(p), "--allowedTools", *allowed], cwd=ROOT,
                   env={**os.environ}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p.unlink(missing_ok=True)


def git(*args, cwd=None):
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd or ROOT, capture_output=True, text=True)
    if r.returncode:
        raise Fail((r.stderr or r.stdout).strip()[-300:])
    return r.stdout.rstrip("\n")    # keep leading spaces: `status --porcelain` lines start with them


def brain_state():
    """Each changed file under brain/ with a hash of its contents, to see exactly what an edit run touched."""
    out = {}
    for line in git("status", "--porcelain", "--", "brain").splitlines():
        path = line[3:].strip('"')
        f = ROOT / path
        out[path] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else "gone"
    return out


def do_brain_edit(item, step):
    target = (step["execute"].get("target") or "").strip()
    if not re.fullmatch(r"brain/[\w/-]+\.md", target) or ".." in target or not (ROOT / target).is_file():
        raise Fail("The target is not a file in brain/")
    if git("status", "--porcelain", "--", target):
        raise Fail(f"{target} has changes no rule press made; commit or discard them, then press again")
    before = brain_state()
    edit_run(f"execedit-{item['id']}-{step['id']}",
             f"Add this rule to {target}, following brain/README.md (supersede an older rule it replaces). Change nothing "
             f"else and touch no other file.\n\nThe rule:\n{step.get('draft')}\n",
             ["Read", "Grep", "Glob", f"Edit({tilde(ROOT / target)})"])
    after = brain_state()
    if target not in after:
        raise Fail("The rule was not added")
    other = [p for p in after if p != target and after[p] != before.get(p)]
    if other:
        git("checkout", "--", target)       # leave nothing half-done behind
        raise Fail(f"The edit also changed {', '.join(other)}; nothing was kept. Press again.")
    rid = re.search(r"\*\*([A-Z]{1,4}\d+)\*\*", step.get("draft") or "")
    short = re.sub(r"[*_`]", "", (step.get("draft") or "").split("\n")[0])[:70]
    git("add", "--", target)
    git("commit", "-q", "-m", f"brain: {(rid.group(1) + ' ') if rid else ''}{short}", "--", target)
    return "rule added", ""


def do_ledger(item, steps):
    """All queued ledger_pr steps for the ledger repo, in one PR."""
    repo = Path(os.path.expanduser(identity.LEDGER_PATH)) if identity.LEDGER_PATH else None
    for s in steps:
        tgt = (s["execute"].get("target") or "").split()[0] if (s["execute"].get("target") or "").strip() else ""
        if not repo or Path(os.path.expanduser(tgt)).resolve() != repo.resolve():
            raise Fail("The target is not the configured ledger repo (modules.ledger)")
    prs = json.loads(gh("pr", "list", "--author", "@me", "--state", "open", "--json", "number,title,headRefName,files,body,url", cwd=repo))
    ledgerish = [p for p in prs if any(re.match(r"^(DECISIONS|OPEN-ITEMS|ACTIONS)\.md$|^decisions/", f["path"]) for f in p.get("files") or [])]
    rank = lambda p: (0 if "rulings" in p["title"].lower() else 1 if "digest" in p["title"].lower() else 2)
    pr = sorted(ledgerish, key=rank)[0] if ledgerish else None
    git("fetch", "-q", "origin", cwd=repo)
    wt = CACHE / "worktrees" / f"ledger-{uuid.uuid4().hex[:8]}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    day = datetime.now(identity.TZ)
    branch = pr["headRefName"] if pr else f"rulings/{day:%Y-%m-%d}-{uuid.uuid4().hex[:4]}"
    git("worktree", "add", "-q", "--detach", str(wt), f"origin/{branch}" if pr else "origin/main", cwd=repo)
    body = CACHE / f"body-{uuid.uuid4().hex[:8]}.md"
    try:
        rows = "\n\n".join(f"### Step {s['id']} of {s['item_id']}\n{s.get('draft')}" for s in steps)
        edit_run(f"execledger-{uuid.uuid4().hex[:6]}",
                 f"Add these rows to the decision ledger checked out at {wt}. Follow {wt}/AGENTS.md. Edit only files inside "
                 f"{wt}; renumber an ID if it is already taken. Then write the pull request body to {body}: it lists every "
                 "change now in the PR" + (f", keeping what the current body already lists:\n\n{pr.get('body') or ''}\n\n" if pr else ".\n\n")
                 + f"Rows to add:\n\n{rows}\n",
                 ["Read", "Grep", "Glob", f"Edit({tilde(wt)}/**)", f"Write({tilde(wt)}/**)", f"Write({tilde(body)})"])
        changed = [l[3:].strip('"') for l in git("status", "--porcelain", cwd=wt).splitlines()]
        if not changed:
            raise Fail("No rows were added")
        bad = [f for f in changed if not LEDGER_FILES.search(f)]
        if bad:
            raise Fail(f"Refused: non-Markdown files changed ({', '.join(bad)})")
        git("add", "-A", cwd=wt)
        git("commit", "-q", "-m", f"Product owner rulings {day:%b %-d}", cwd=wt)
        git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", cwd=wt)
        has_body = body.exists() and body.read_text().strip()
        if pr:
            if has_body:
                gh("pr", "edit", str(pr["number"]), "--body-file", str(body), cwd=repo)
            return f"added to PR #{pr['number']}", pr["url"]
        url = gh("pr", "create", "--base", "main", "--head", branch, "--title", f"Product owner rulings {day:%b %-d}",
                 "--body-file", str(body) if has_body else "/dev/null", cwd=repo)
        return f"opened PR #{url.rstrip('/').rsplit('/', 1)[-1]}", url
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, capture_output=True)
        body.unlink(missing_ok=True)


KINDS = {"slack_send": do_slack, "slack_draft": do_slack, "pr_comment": do_pr, "pr_approve": do_pr,
         "pr_request_changes": do_pr, "pr_merge": do_pr, "gdoc_create": do_gdoc, "gsheet_write": do_gsheet,
         "calendar_event": do_calendar, "brain_edit": do_brain_edit}


# ---------- queue bookkeeping ----------

def finish(item, step, ok, result="", link="", error=""):
    ts = now()
    if ok:
        step.update(status="done", done_at=ts, done_by="executor", result=result)
        if link:
            step.setdefault("evidence", []).append({"label": result, "url": link})
    else:
        step.update(status="failed", error=error, error_short=error[:90])
    item.setdefault("history", []).append({"ts": ts, "by": "executor", "event": "done" if ok else "failed",
                                           "step": step["id"], **({"note": error[:200]} if error else {})})


def save(path, item):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(item, indent=1, ensure_ascii=False))
    tmp.replace(path)


def queued():
    out = []
    for f in sorted(ITEMS.glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out += [(f, it, s) for s in it.get("steps") or [] if s.get("status") == "queued"]
    return out


def run_once():
    done = failed = 0
    ledger = []
    for f, it, s in queued():
        it = json.loads(f.read_text())               # fresh copy: an earlier step may have changed this item
        s = next((x for x in it["steps"] if x.get("id") == s.get("id")), None)
        if not s or s.get("status") != "queued":
            continue
        kind = (s.get("execute") or {}).get("kind")
        if not press.pressed(it["id"], s):
            finish(it, s, False, error="Not pressed in the app, or changed after the press. Review it and press again.")
            save(f, it)
            failed += 1
            continue
        if kind == "ledger_pr":
            ledger.append((f, it["id"], s["id"]))
            continue
        try:
            if kind not in KINDS:
                raise Fail(f"The app can't do '{kind}' steps")
            result, link = KINDS[kind](it, s)
            finish(it, s, True, result, link)
            done += 1
        except Fail as e:
            finish(it, s, False, error=str(e))
            failed += 1
        except Exception as e:      # never leave a pressed step Running: fail it with the reason
            finish(it, s, False, error=f"The app hit an error ({type(e).__name__}: {str(e)[:150]}). Nothing else ran.")
            failed += 1
        save(f, it)
    if ledger:
        loaded = [(f, json.loads(f.read_text()), sid) for f, _, sid in ledger]
        steps = [{**next(x for x in it["steps"] if x["id"] == sid), "item_id": it["id"]} for f, it, sid in loaded]
        try:
            result, link, ok, err = *do_ledger(loaded[0][1], steps), True, ""
        except Fail as e:
            result, link, ok, err = "", "", False, str(e)
        except Exception as e:
            result, link, ok, err = "", "", False, f"The app hit an error ({type(e).__name__}: {str(e)[:150]}). Nothing was merged."
        for f, it, sid in loaded:
            it = json.loads(f.read_text())
            s = next(x for x in it["steps"] if x["id"] == sid)
            finish(it, s, ok, result, link, err)
            save(f, it)
        done, failed = (done + len(loaded), failed) if ok else (done, failed + len(loaded))
    return done, failed


def main():
    # One executor at a time. A kernel lock (released when the process ends, however it ends) closes the race two
    # quick presses hit with a pid file: both started before either had written its pid (Nov 15, brain edits).
    import fcntl
    fh = open(STATE / "execute.flock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("execute already running")
        return
    lock = STATE / "execute.lock"            # the app's "executor running" indicator
    lock.mkdir(exist_ok=True)
    (lock / "pid").write_text(str(os.getpid()))
    try:
        total_d = total_f = 0
        for _ in range(5):                  # the owner may press more while this runs
            d, f = run_once()
            total_d, total_f = total_d + d, total_f + f
            if not d and not f:
                break
        print(f"executed {total_d}, failed {total_f}")
    finally:
        shutil.rmtree(lock, ignore_errors=True)


if __name__ == "__main__":
    main()
