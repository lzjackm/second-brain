#!/usr/bin/env python3
"""Daily (5:30 PM ET) cost and efficacy check. Plain Python, no model calls.

Writes state/ops/<date>.json (shown in Performance). Flags and suggestions stay there: the owner doesn't press anything
to acknowledge a report. Only a job that keeps failing (its last 3 runs all failed) becomes a queue item, since
that needs fixing. Flags: a run far above its job's usual cost, errors, cost per unit drifting up,
turn counts spiking, and whether lead or pipeline is cheaper per unit with quality holding.
Usage: ops_report.py [days=7]
"""
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import OWNER  # noqa: E402  (config/brain.json)
ET = ZoneInfo("America/New_York")
PIPELINE = {"scout", "director", "specialist-reply", "specialist-decision", "specialist-review", "specialist-synopsis"}


def jsonl(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def outcome(link, items):
    """What became of a signal: the item that cites its Slack message (by channel + message ts) and what the owner did."""
    import re
    m = re.search(r"archives/([A-Z0-9]+)(?:/p(\d+))?", link or "")
    if not m or not m.group(2):  # a channel-only link can't be told apart from other items in that channel or DM
        return "unclear (no message link)"
    key = m.group(1) + (m.group(2) or "")
    for it in items:
        if key in it["_links"]:
            acts = {h.get("event", "") for h in it.get("history", [])}
            if it.get("status") == "dismissed":
                return "item dismissed (no action needed)"
            if it.get("status") == "done" or any("done" in a for a in acts):
                return "item acted on"
            return f"item {it.get('status')}"
    return "no item"


def shadow_routes(days):
    """The shadow router (config/router.json) vs the live router on the same signals: agreement, how often it was sure, and each disagreement with
    its outcome, so the comparison settles itself from what the owner did."""
    import re
    since = (datetime.now(ET) - timedelta(days=days)).isoformat()
    rows = [r for r in jsonl(ROOT / "log" / "routes.jsonl") if r.get("ts", "") >= since and (r.get("shadow") or r.get("jev_shadow"))]
    for r in rows:
        r["shadow"] = r.get("shadow") or r.pop("jev_shadow")
    if not rows:
        return None
    items = []
    for f in (ROOT / "queue" / "items").glob("*.json"):
        try:
            it = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        it["_links"] = " ".join(a + (b or "") for a, b in re.findall(r"archives/([A-Z0-9]+)(?:/p(\d+))?", json.dumps(it)))
        items.append(it)
    sig_links = {}
    for f in (ROOT / "state" / "signals").glob("*.routed"):
        run = f.name.split(".")[0]
        for line in f.read_text().splitlines():
            x = json.loads(line)
            sig_links[(run, x["id"])] = x.get("link")
    sure = [r for r in rows if r["shadow"]["to"]]
    agree = [r for r in sure if r["shadow"]["to"] == r["to"]]
    dis = [{"ts": r["ts"][:16], "summary": r.get("summary", "")[:140], "router": r["to"], "shadow": r["shadow"]["to"],
            "shadow_conf": round(r["shadow"]["confidence"] or 0, 2), "outcome": outcome(sig_links.get((r["run"], r["signal"])), items)}
           for r in sure if r["shadow"]["to"] != r["to"]]
    return {"signals": len(rows), "shadow_sure": len(sure), "agree": len(agree), "disagreements": dis}


OWNER_CAUSES = {"signed out": "Sign in to Claude again (/login)", "spend limit": "Raise the Claude spend limit (/usage-credits)"}


def failure_cause(recs):
    """Why a job's recent runs failed, from their logs: only the owner can fix a sign-in or a spend limit."""
    text = ""
    for r in recs:
        for f in sorted((ROOT / "logs").glob(f"{r.get('name', '')}-*.log"))[-3:]:
            for x in (f, f.with_name(f.name + ".err")):
                try:
                    text += x.read_text(errors="ignore")[-2000:].lower()
                except OSError:
                    pass
        text += (r.get("error_short") or "").lower()
    if "signed out" in text or "oauth access token has expired" in text or "failed to authenticate" in text or "isn't signed in" in text:
        return "signed out"
    if "spend limit" in text or "usage limit" in text or "credit balance" in text:
        return "spend limit"
    if "timed out" in text or "stalled" in text:
        return "timed out (check whether the Mac slept; dark wakes are now skipped)"
    return "failed; see the logs"


def queue_fix(title, spec, key):
    """A fix the brain found it needs, queued for the next Claude Code session without an owner step (bin/fixes.py)."""
    sys.path.insert(0, str(ROOT / "bin"))
    import fixes  # noqa: E402
    fixes.queue(title, spec, key, "ops_report")


def main(days=7):
    now = datetime.now(ET)
    day_ago, since = (now - timedelta(days=1)).isoformat(), (now - timedelta(days=days)).isoformat()
    runs = [r for r in jsonl(ROOT / "log" / "usage.jsonl") if r.get("ts", "") >= since]
    last = [r for r in runs if r["ts"] >= day_ago]
    by_job = {}
    for r in runs:
        by_job.setdefault(r["job"], []).append(r)

    flags = []
    for r in last:
        hist = [x["cost_usd"] for x in by_job[r["job"]] if x["run"] != r["run"]]
        if r.get("error"):
            flags.append(f"{r['job']} run failed at {r['ts'][11:16]}")
        if len(hist) >= 3 and r["cost_usd"] > max(0.25, 3 * statistics.median(hist)):
            top = (r.get("tools") or [{}])[0]
            flags.append(f"{r['job']} cost ${r['cost_usd']:.2f} at {r['ts'][11:16]}, over 3x its usual ${statistics.median(hist):.2f}"
                         + (f"; biggest read: {top.get('tool')} {str(top.get('arg', ''))[-40:]}" if top else ""))
        if len(hist) >= 3 and (r.get("turns") or 0) > 2 * statistics.median([x.get("turns") or 0 for x in by_job[r["job"]]]) + 5:
            flags.append(f"{r['job']} took {r['turns']} turns at {r['ts'][11:16]}, about double its usual")

    # Stalls: the daytime schedule should produce a lead or pipeline run at least every 2 hours.
    day_runs = sorted(r["ts"] for r in last if r["job"] in ("lead", "scout") and 7 <= int(r["ts"][11:13]) <= 21)
    for a, b in zip(day_runs, day_runs[1:]):
        gap = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
        if gap > 2.5:
            flags.append(f"No lead or pipeline run for {gap:.1f} hours between {a[11:16]} and {b[11:16]}")
    for r in last:
        if r.get("error") and (r.get("duration_ms") or 0) > 10 * 60 * 1000:
            flags.append(f"{r['job']} ran {r['duration_ms'] // 60000} min and failed at {r['ts'][11:16]} (likely a hung run)")

    def side(jobs):
        rs = [r for r in last if r["job"] in jobs]
        cost = sum(r["cost_usd"] for r in rs)
        return {"runs": len(rs), "cost": round(cost, 2)}
    pipe = side(PIPELINE)
    lead = side({"lead"})
    # Quality per side from the server's jobs report (same definitions as the Jobs table).
    try:
        sys.path.insert(0, str(ROOT / "app"))
        import server  # noqa: E402
        jobs = server.jobs_report(days)
        q = lambda names: [j for j in jobs if j["job"] in names and j.get("judged")]
        def wq(rows):
            n = sum(j["judged"] for j in rows)
            return round(sum(j["quality"] * j["judged"] for j in rows) / n, 2) if n else None
        pipe["quality"], lead["quality"] = wq(q(PIPELINE)), wq(q({"lead"}))
        pipe["judged"], lead["judged"] = sum(j["judged"] for j in q(PIPELINE)), sum(j["judged"] for j in q({"lead"}))
    except Exception as e:
        pipe["quality"] = lead["quality"] = None
        flags.append(f"quality lookup failed: {e}")

    total_day = round(sum(r["cost_usd"] for r in last), 2)
    week = round(sum(r["cost_usd"] for r in runs), 2)
    per_job = {j: {"runs_24h": sum(1 for r in last if r["job"] == j), "cost_24h": round(sum(r["cost_usd"] for r in last if r["job"] == j), 2),
                   "median_run": round(statistics.median([r["cost_usd"] for r in rs]), 3)} for j, rs in by_job.items()}
    report = {"date": now.date().isoformat(), "generated": now.isoformat(timespec="seconds"), "cost_24h": total_day,
              "cost_7d": week, "pipeline_24h": pipe, "lead_24h": lead, "jobs": per_job, "flags": flags}
    # A frequency suggestion only when there is enough data on both sides.
    if (pipe.get("judged") or 0) >= 10 and (lead.get("judged") or 0) >= 10 and pipe["runs"] and lead["runs"]:
        pr, lr = pipe["cost"] / pipe["runs"], lead["cost"] / lead["runs"]
        if pipe["quality"] is not None and lead["quality"] is not None and pipe["quality"] >= lead["quality"] - 0.05 and pr < 0.6 * lr:
            report["suggestion"] = f"Pipeline costs ${pr:.2f} a run vs lead ${lr:.2f} with quality {pipe['quality']:.0%} vs {lead['quality']:.0%}: worth moving more slots to the pipeline or running it more often."
    report["shadow"] = shadow_routes(days)
    out = ROOT / "state" / "ops"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{report['date']}.json").write_text(json.dumps(report, indent=2))

    seq = {}
    for r in sorted(runs, key=lambda r: r["ts"]):
        seq.setdefault(r["job"], []).append(r)
    broken = [j for j, rs in seq.items() if len(rs) >= 3 and all(x.get("error") for x in rs[-3:])]
    # Nov 21: failures went to the owner as "Fix the failing runs" with nothing to press. Now: a cause only the owner can
    # fix (sign-in, spend limit) is a one-line item saying what to do; anything else is queued as a fix for the next Claude
    # Code session with its diagnosis, no owner step. Runs started in a dark wake are skipped in _claude.sh, not failed.
    owner_only, to_fix = {}, {}
    for job in broken:
        why = failure_cause(seq[job][-3:])
        (owner_only if why in OWNER_CAUSES else to_fix)[job] = why
    if owner_only:
        item_id = f"brain-ops-{report['date']}"
        act = sorted({OWNER_CAUSES[w] for w in owner_only.values()})
        steps = [{"id": "s1", "text": act[0] if len(act) == 1 else "Sign in again and check the spend limit", "owner": OWNER,
                  "status": "todo", "draft": "\n".join(f"{j}: {w}" for j, w in owner_only.items()), "execute": {"kind": "none"}}]
        item = {"id": item_id, "key": f"brain:ops:{report['date']}", "area": "brain", "type": "action",
                "title": act[0] if len(act) == 1 else "Runs need your sign-in and spend limit",
                "context": f"{', '.join(owner_only)} can't run until you do this.", "why_owner": "Only you can sign in or raise the limit.",
                "priority": 60, "status": "open", "steps": steps,
                "created": now.isoformat(timespec="seconds"), "history": [{"ts": now.isoformat(timespec="seconds"), "by": "ops_report", "event": "created"}],
                "made_by": {"run": f"ops-{report['date']}", "job": "ops_report"}}
        (ROOT / "queue" / "items" / f"{item_id}.json").write_text(json.dumps(item, indent=2))
    if to_fix:
        queue_fix(f"Runs keep failing: {', '.join(to_fix)}",
                  "The last 3 runs of each failed. Read their logs (logs/<job>-*.log, .err, .trace.jsonl), find the cause, fix it "
                  "in code with a test, and confirm the next run succeeds:\n" + "\n".join(f"- {j}: {w}" for j, w in to_fix.items()),
                  key=f"ops:{report['date']}:{','.join(sorted(to_fix))}")
    print(f"24h ${total_day:.2f}, 7d ${week:.2f}, flags {len(flags)}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
