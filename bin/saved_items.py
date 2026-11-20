#!/usr/bin/env python3
"""The owner's Slack "Saved for later" messages are their own to-dos (Nov 19): each becomes a Needs me item, and
clearing it in Slack closes the item. Printed into the default area's lead, editor and sync prompts only when Slack
is connected, so one area owns them and no two runs create the same item.

Usage: saved_items.py <area> <mode>   prints the prompt block (nothing when it doesn't apply)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import connectors  # noqa: E402
import identity  # noqa: E402

PREFIX = "slack-saved:"
LIVE = {"open", "waiting", "working", "reconciling", "snoozed"}
SEARCH = "slack_search_public_and_private"


def slack():
    return next((c for c in connectors.registry() if connectors.role(c) != "off" and SEARCH in (c.get("read_tools") or [])), None)


def items(items_dir=None):
    out = []
    for f in sorted((items_dir or ROOT / "queue" / "items").glob("*.json")):
        try:
            it = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if (it.get("key") or "").startswith(PREFIX):
            out.append(it)
    return out


def owning_area():
    """One area owns saved items: the default area, else the first area with a lead spec."""
    return identity.CFG.get("default_area") or next((f.stem for f in sorted((ROOT / "leads").glob("*.md"))), None)


def block(area, mode, items_dir=None):
    c = slack()
    if not c or area != owning_area() or mode not in ("lead", "edit", "sync"):
        return ""
    first, tok = identity.OWNER_FIRST, identity.OWNER
    have = items(items_dir)
    live = [it for it in have if it.get("status") in LIVE]
    tool = f"mcp__{c['server']}__{SEARCH}"
    lines = ["", "## Slack Saved for later", ""]
    if mode in ("lead", "edit"):
        lines += [
            f"{first} saves Slack messages as to-dos. Search `{tool}` with query `is:saved`, sort `timestamp`, every page.",
            f"For each result with no item keyed `{PREFIX}<channel id>:<message ts>` (any status; the keys below), create one:",
            f"type `action`, that key, `why_owner` \"You saved it in Slack\", evidence = the message link first.",
            f"Read the message and its thread to its latest message: the title and steps say what {first} has to do about it",
            f"(review the doc, answer the question, follow up), with the usual step rules; the first step is owned by `{tok}`.",
            "If the thread shows it is already done, still create it, with a note in `summary` saying so.",
            f"Never create one for a saved message that already has an item, even a done or dismissed one: {first} closed it.",
        ]
    if live:
        lines += ["", f"Open saved items. If a message is no longer returned by `is:saved`, {first} cleared it in Slack: set its open",
                  f"`{tok}` steps `done_elsewhere` with `elsewhere_note` \"cleared from Slack Saved\" (search once per run, not per item):"]
        lines += [f"- {it['id']}: {it['key']}" for it in live]
    if mode in ("lead", "edit") and have:
        lines += ["", "Saved messages that already have an item: " + ", ".join(it["key"][len(PREFIX):] for it in have)]
    if mode == "sync" and not live:
        return ""
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(block(sys.argv[1], sys.argv[2]))
