#!/usr/bin/env python3
"""Learn: build a tutor turn's prompt from a topic's state, and apply the tutor's reply back to it.

Usage: learn.py build <slug> <mode> <out.md>   |   learn.py apply <slug> <log>
A topic lives in learn/topics/<slug>.json (skill map, level history, misconceptions, notes, conversation).
After every turn learn/codex/<slug>.md is rewritten: the readable reference the owner and his agents use.
"""
import json
import re
import sys
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin")) if str(ROOT / "bin") not in sys.path else None
from identity import OWNER_NAMES  # noqa: E402
TOPICS, CODEX = ROOT / "learn" / "topics", ROOT / "learn" / "codex"
ET = ZoneInfo("America/New_York")
RECENT = 30  # messages sent each turn; the map and notes carry everything older


def now():
    return datetime.now(ET).isoformat(timespec="seconds")


def load(slug):
    return json.loads((TOPICS / f"{slug}.json").read_text())


def save(t):
    t["updated"] = now()
    (TOPICS / f"{t['slug']}.json").write_text(json.dumps(t, indent=2, ensure_ascii=False))
    write_codex(t)


def due(t, today=None):
    today = today or date.today().isoformat()
    return [s["name"] for s in t.get("subskills", []) if s.get("level", 0) > 0 and (s.get("next_review") or "9") <= today]


def build(slug, mode, out):
    t = load(slug)
    state = {
        "topic": t["topic"], "stage": t.get("stage", "new"), "target": t.get("target", 4),
        "subskills": t.get("subskills", []), "due_for_review": due(t),
        "misconceptions": t.get("misconceptions", []), "covered": t.get("covered", []),
        "notes_md": t.get("notes_md"),
        "earlier_messages": max(0, len(t.get("messages", [])) - RECENT),
    }
    convo = "\n".join(f"{'the owner' if m['role'] in OWNER_NAMES else 'Tutor'} ({m.get('mode', '')}): {m['text']}"
                      for m in t.get("messages", [])[-RECENT:]) or "(none yet)"
    tpl = (ROOT / "prompts" / "learn.md").read_text()
    skill = (ROOT / "skills" / "socratic-tutor" / "SKILL.md").read_text()
    skill = re.sub(r"^---.*?---\n", "", skill, flags=re.S)
    text = (tpl.replace("{{NOW}}", now()).replace("{{TOPIC}}", t["topic"]).replace("{{MODE}}", mode)
            .replace("{{SKILL}}", skill.strip())
            .replace("{{STATE}}", "```json\n" + json.dumps(state, indent=1, ensure_ascii=False) + "\n```\n\n## Recent conversation\n" + convo))
    Path(out).write_text(text)


def apply(slug, log):
    t = load(slug)
    raw = Path(log).read_text() if Path(log).exists() else ""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", raw, flags=re.S)
    data = None
    for b in reversed(blocks):
        try:
            data = json.loads(b)
            break
        except json.JSONDecodeError:
            continue
    ts, mode = now(), t.get("pending_mode", "continue")
    if not data:
        msg = raw.strip() or "The tutor didn't answer. Send again to retry."
        t.setdefault("messages", []).append({"role": "tutor", "text": msg[:4000], "ts": ts, "mode": mode, "error": True})
    else:
        t.setdefault("messages", []).append({"role": "tutor", "text": data.get("say") or "", "ts": ts, "mode": mode,
                                             "sources": data.get("sources") or []})
        if data.get("stage"):
            t["stage"] = data["stage"]
        # Levels are earned: a level only moves when the tutor logs the change with its evidence. Anything else
        # keeps the previous level (guards against a model silently raising or resetting the map).
        prev = {s["name"]: s for s in t.get("subskills", [])}
        changes = {c.get("subskill"): c for c in data.get("level_changes") or [] if c.get("why") and c.get("to") is not None}
        if isinstance(data.get("subskills"), list) and data["subskills"]:
            new = []
            for s in data["subskills"]:
                name, old = s.get("name", "?"), prev.get(s.get("name", "?"))
                level = int(s.get("level", 0))
                if old is not None and level != old["level"] and name not in changes:
                    level = old["level"]
                new.append({"name": name, "level": max(0, min(5, level)), "target": int(s.get("target", t.get("target", 4))),
                            "next_review": s.get("next_review")})
            if prev and len(new) < len(prev):  # a dropped subskill is a model slip, not a change of plan
                new += [v for k, v in prev.items() if k not in {n["name"] for n in new}]
            t["subskills"] = new
        for name, c in changes.items():
            old = prev.get(name)
            if old is None or int(c["to"]) != old["level"]:
                t.setdefault("history", []).append({"ts": ts, **c, "from": old["level"] if old else c.get("from", 0)})
        for k in ("misconceptions", "covered"):
            for x in data.get(k) or []:
                if x not in t.setdefault(k, []):
                    t[k].append(x)
        if data.get("notes_md"):
            t["notes_md"] = data["notes_md"]
        for s in data.get("sources") or []:
            if s.get("url") and s["url"] not in {x.get("url") for x in t.setdefault("sources", [])}:
                t["sources"].append(s)
        if t.get("stage") == "mastered" and not t.get("mastered_at"):
            t["mastered_at"] = ts
    t.pop("pending", None)
    t.pop("pending_mode", None)
    save(t)


def bar(level, n=5):
    return "█" * level + "░" * (n - level)


def write_codex(t):
    CODEX.mkdir(parents=True, exist_ok=True)
    subs = t.get("subskills", [])
    pct = round(100 * sum(s["level"] for s in subs) / (5 * len(subs))) if subs else 0
    lines = [f"# {t['topic']}", "",
             f"Stage: {t.get('stage', 'new')} · {pct}% · started {t['created'][:10]} · last studied {t.get('updated', '')[:10]}", "",
             "## Skill map", "", "| Subskill | Level | Next review |", "|---|---|---|"]
    lines += [f"| {s['name']} | {bar(s['level'])} {s['level']}/5 | {s.get('next_review') or '–'} |" for s in subs]
    lines += ["", t.get("notes_md") or "_No notes yet._", ""]
    if t.get("misconceptions"):
        lines += ["## Misconceptions caught", "", *[f"- {m}" for m in t["misconceptions"]], ""]
    if t.get("history"):
        lines += ["## Level history", "", *[f"- {h['ts'][:10]} {h.get('subskill')}: {h.get('from')} to {h.get('to')}. {h.get('why', '')}" for h in t["history"]], ""]
    (CODEX / f"{t['slug']}.md").write_text("\n".join(lines))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(*sys.argv[2:5])
    elif cmd == "apply":
        apply(*sys.argv[2:4])
