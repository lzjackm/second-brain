#!/usr/bin/env python3
"""Director: route each scout signal to one handler, with only the slim summary as input.

Usage: director.py <signals.jsonl> <area> <run>
Writes <signals>.<handler>.jsonl per handler, <signals>.routed (all signals with their route),
and appends every decision to log/routes.jsonl so misroutes can be measured.

Backends (config/router.json): "claude" (a small model through claude -p) or "decisions" (a decisions model
behind the Vercel AI Gateway /v1/decisions endpoint, set by decisions_model; low-confidence routes and errors go to claude).
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import SLUG, OWNER_NAME  # noqa: E402
HANDLERS = ["reply", "decision", "review", "update", "synopsis"]


def slim(s):
    return {k: s.get(k) for k in ("id", "where", "who", "summary", "asks_owner", "owner_spoke", "related")}


def route_claude(signals, area, cfg):
    tpl = (ROOT / "prompts" / "director-route.md").read_text()
    prompt = ROOT / "state" / f"prompt-director-{area}.md"
    prompt.write_text(tpl.replace("{{SIGNALS}}", "\n".join(json.dumps(slim(s), ensure_ascii=False) for s in signals)))
    subprocess.run([str(ROOT / "bin" / "_claude.sh"), f"director-{area}", str(prompt),
                    "--model", cfg.get("claude_model", "haiku"), "--allowedTools", "Read"],
                   cwd=ROOT, check=False, capture_output=True, text=True)
    logs = sorted((ROOT / "logs").glob(f"director-{area}-*.log.json"))
    if not logs:
        return {}
    text = json.loads(logs[-1].read_text()).get("result", "")
    text = text[text.find("{"): text.rfind("}") + 1]
    try:
        return {r["id"]: (r.get("to"), r.get("confidence")) for r in json.loads(text)["routes"]}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


# A decisions model answers independent yes/no questions far better than one five-way choice (in testing on live signals,
# the choice form called a direct ask of the owner "no action" at 0.94). Code combines the answers.
YESNO_QUESTIONS = [
    {"type": "predicate", "name": "asks_owner", "instructions": f"Does this message ask {OWNER_NAME or 'the owner'} (directly or by name) to answer, do, attend, review or confirm something they have not already done?"},
    {"type": "predicate", "name": "owner_done", "instructions": "Has the owner already responded to or handled the ask in this message?"},
    {"type": "predicate", "name": "review", "instructions": "Is a PR, document, deck or sheet waiting for the owner's review or approval?"},
    {"type": "predicate", "name": "decision", "instructions": "Does this message state a final decision on terms, dates, scope or design, or say that one must now be made by a named person? Proposals, preferences and discussion do not count."},
]


def decision_answers(signals, cfg):
    """Ask the decisions model the yes/no questions about each signal (Vercel AI Gateway /v1/decisions), in parallel."""
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    key = subprocess.run(["security", "find-generic-password", "-s", f"{SLUG}-ai-gateway", "-w"],
                         capture_output=True, text=True).stdout.strip()
    if not key:
        raise NotImplementedError(f"no AI Gateway key in Keychain ({SLUG}-ai-gateway)")

    def ask(s):
        text = (f"Signal from {s.get('where')} by {s.get('who')}: {s.get('summary')}\nExcerpt: {s.get('excerpt', '')}\n"
                f"the owner spoke in it: {s.get('owner_spoke')}")
        body = json.dumps({"model": cfg["decisions_model"], "input": text, "questions": YESNO_QUESTIONS}).encode()
        req = urllib.request.Request("https://ai-gateway.vercel.sh/v1/decisions", body,
                                     {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            return s["id"], {a["name"]: a["probability"] for a in json.loads(urllib.request.urlopen(req, timeout=20).read())["answers"]}
        except Exception as e:  # network or API error: no answer, the caller falls back
            print(f"decisions model {s['id']}: {e}", file=sys.stderr)
            return s["id"], None
    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(ask, signals))


def decision_route(p, floor):
    """Combine the probabilities into a handler and a confidence; None when no answer clears the floor."""
    if not p:
        return None, 0.0
    if p["owner_done"] >= floor:
        return "update", p["owner_done"]
    if p["review"] >= floor:
        return "review", p["review"]
    if p["asks_owner"] >= floor:
        return "reply", p["asks_owner"]
    if p["decision"] >= floor:
        return "decision", p["decision"]
    if max(p.values()) <= 1 - floor:
        return "synopsis", 1 - max(p.values())
    return None, max(p.values())


def route_decisions(signals, area, cfg):
    """The decisions model decides what it is sure of; everything else goes to the Claude router, so a hard call never rides on a guess."""
    floor = cfg.get("decisions_min_confidence", 0.7)
    answers = decision_answers(signals, cfg)
    routes = {}
    for s in signals:
        to, conf = decision_route(answers.get(s["id"]), floor)
        if to:
            routes[s["id"]] = (to, conf, "decisions")
    unsure = [s for s in signals if s["id"] not in routes]
    if unsure:
        for k, v in route_claude(unsure, area, cfg).items():
            routes[k] = (v[0], v[1], "claude")
    return routes


def main(sig_path, area, run):
    sig_path = Path(sig_path)
    signals = [json.loads(l) for l in sig_path.read_text().splitlines() if l.strip()]
    cfg = json.loads((ROOT / "config" / "router.json").read_text())
    # Deterministic first: anything tied to an existing item goes to update, no model needed.
    fixed = {s["id"]: ("update", 1.0) for s in signals if s.get("related")}
    rest = [s for s in signals if s["id"] not in fixed]
    backend = cfg.get("backend", "claude")
    routes = {}
    if rest:
        try:
            routes = route_decisions(rest, area, cfg) if backend == "decisions" else route_claude(rest, area, cfg)
        except NotImplementedError as e:
            print(f"{e}; using claude", file=sys.stderr)
            backend = "claude"
            routes = route_claude(rest, area, cfg)
    routes.update(fixed)
    shadow = {}
    if rest and backend == "claude" and cfg.get("shadow"):
        try:
            floor = cfg.get("decisions_min_confidence", 0.7)
            shadow = {k: (decision_route(v, floor), v) for k, v in decision_answers(rest, cfg).items()}
        except Exception as e:
            print(f"shadow router failed: {e}", file=sys.stderr)
    by = {h: [] for h in HANDLERS}
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    with (ROOT / "log" / "routes.jsonl").open("a") as log, sig_path.with_suffix(".jsonl.routed").open("w") as routed:
        for s in signals:
            r = routes.get(s["id"], (None, None))
            to, conf, by_backend = r[0], r[1], (r[2] if len(r) > 2 else backend)
            if to not in HANDLERS:  # unrouted or unknown: anything asking the owner is a reply, else synopsis
                to, conf = ("reply" if s.get("asks_owner") and not s.get("owner_spoke") else "synopsis"), 0.0
            s["route"] = to
            by[to].append(s)
            routed.write(json.dumps(s, ensure_ascii=False) + "\n")
            log.write(json.dumps({"ts": ts, "run": run, "area": area, "signal": s["id"], "where": s.get("where"),
                                  "summary": s.get("summary"), "to": to, "confidence": conf,
                                  "backend": "rule" if s["id"] in fixed else by_backend,
                                  **({"shadow": {"to": shadow[s["id"]][0][0], "confidence": shadow[s["id"]][0][1], "p": shadow[s["id"]][1]}}
                                     if s["id"] in shadow else {})}, ensure_ascii=False) + "\n")
    for h, items in by.items():
        if items:
            Path(f"{sig_path.with_suffix('')}.{h}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items))
    print(" ".join(f"{h}={len(v)}" for h, v in by.items()))


if __name__ == "__main__":
    main(*sys.argv[1:4])
