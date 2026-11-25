"""Checks Claude Code can do itself go to the fix queue, never the owner's queue (Nov 25: "this is not my job ...
This is your job"). Cases are the two items that reached the owner that day, plus items that must stay.

Run: bin/test.sh
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import identity  # noqa: E402
import fixes  # noqa: E402
import self_task_gate as g  # noqa: E402


def item(iid, text, draft="", typ="do", by="lead", kind="none", owner=None, **kw):
    return {"id": iid, "key": f"k:{iid}", "area": "main", "type": typ, "status": "open", "title": iid,
            "history": [{"ts": "2026-11-24T15:15:00-05:00", "by": by, "event": "created"}],
            "steps": [{"id": "s1", "owner": owner or identity.OWNER, "status": "todo", "text": text, "draft": draft,
                       "execute": {"kind": kind}}], **kw}


class SelfTaskGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (g.ITEMS, fixes.path)
        g.ITEMS = self.tmp / "items"
        g.ITEMS.mkdir()
        fixes.path = lambda: self.tmp / "approved-fixes.jsonl"

    def tearDown(self):
        g.ITEMS, fixes.path = self.saved

    def put(self, it):
        (g.ITEMS / f"{it['id']}.json").write_text(json.dumps(it))

    def status(self, iid):
        return json.loads((g.ITEMS / f"{iid}.json").read_text())["status"]

    def test_claude_checks_move_owner_work_stays(self):
        self.put(item("token", "Ask Claude Code to verify the token in today's ingest run", by="interactive",
                      snooze_until="2026-11-25T09:00:00-05:00"))
        self.put(item("pipeline", "Review the pipeline's first week", typ="review", by="claude-code"))
        self.put(item("reply", "Reply to Sam", kind="slack_send", by="claude-code", typ="review"))
        self.put(item("decide", "Decide the fee tier", by="lead"))
        self.put(item("theirs", "Ask Claude Code to check X", owner="Sam Lee"))
        self.put(item("oldshape", "Review the launch plan", typ="review", made_by="claude-code"))
        self.put(item("oldlead", "Review the launch plan", typ="review", made_by="lead"))
        g.sweep()
        self.assertEqual([self.status(x) for x in ("token", "pipeline", "reply", "decide", "theirs", "oldshape", "oldlead")],
                         ["done", "done", "open", "open", "open", "done", "open"])
        got = {e["item"]: e for e in fixes.entries()}
        self.assertEqual(set(got), {"token", "pipeline", "oldshape"})
        self.assertEqual(got["token"]["not_before"], "2026-11-25T09:00:00-05:00")
        g.sweep()   # idempotent
        self.assertEqual(len(fixes.entries()), 3)

    def test_not_before_holds_entry(self):
        fixes.queue("later", "x", "k1", "t", not_before="2026-11-25T09:00:00-05:00")
        fixes.queue("now", "x", "k2", "t")
        self.assertEqual([e["title"] for e in fixes.open_entries("2026-11-25T08:00:00-05:00")], ["now"])
        self.assertEqual(len(fixes.open_entries("2026-11-25T10:00:00-05:00")), 2)


if __name__ == "__main__":
    unittest.main()
