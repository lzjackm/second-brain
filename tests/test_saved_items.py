"""Slack Saved for later as to-dos (Nov 19): the default area's runs get the block, other areas don't; the reply gate
leaves saved and owner-added items alone; dedupe merges one key twice and undoes a recreated, already-closed save.

Run: bin/test.sh
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import dedupe  # noqa: E402
import identity  # noqa: E402
import reply_gate  # noqa: E402
import saved_items  # noqa: E402

AREA = saved_items.owning_area() or "main"


def write(d, iid, **kw):
    it = {"id": iid, "area": AREA, "status": "open", "created": "2026-11-19T10:00:00-05:00", "history": [], **kw}
    (d / f"{iid}.json").write_text(json.dumps(it))
    return it


class Block(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.saved = saved_items.slack, saved_items.owning_area
        saved_items.slack = lambda: {"server": "claude_ai_Slack"}
        saved_items.owning_area = lambda: AREA

    def tearDown(self):
        saved_items.slack, saved_items.owning_area = self.saved

    def test_default_area_only(self):
        self.assertIn("is:saved", saved_items.block(AREA, "lead", self.d))
        self.assertIn("is:saved", saved_items.block(AREA, "edit", self.d))
        self.assertEqual(saved_items.block(AREA + "-other", "lead", self.d), "")

    def test_no_slack_no_block(self):
        saved_items.slack = lambda: None
        self.assertEqual(saved_items.block(AREA, "lead", self.d), "")

    def test_sync_lists_open_saved_items(self):
        self.assertEqual(saved_items.block(AREA, "sync", self.d), "")
        write(self.d, "a1", key="slack-saved:C1:1.2")
        self.assertIn("slack-saved:C1:1.2", saved_items.block(AREA, "sync", self.d))


class Gate(unittest.TestCase):
    def test_owner_chosen_items_not_retired(self):
        d = Path(tempfile.mkdtemp())
        saved, reply_gate.ITEMS = reply_gate.ITEMS, d
        try:
            step = {"id": "s1", "owner": identity.OWNER, "status": "todo", "execute": {"kind": "slack_send"}, "ask": {"names_owner": False}}
            write(d, "saved", key="slack-saved:C1:1.2", steps=[step])
            write(d, "other", key="x:1", steps=[step])
            reply_gate.sweep()
            self.assertEqual(json.loads((d / "saved.json").read_text())["status"], "open")
            self.assertEqual(json.loads((d / "other.json").read_text())["status"], "stale")
        finally:
            reply_gate.ITEMS = saved


class Dedupe(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.saved, dedupe.ITEMS = dedupe.ITEMS, self.d

    def tearDown(self):
        dedupe.ITEMS = self.saved

    def status(self, iid):
        return json.loads((self.d / f"{iid}.json").read_text())["status"]

    def test_same_key_merged(self):
        write(self.d, "a", key="slack-saved:C1:1.2", title="Review docs")
        write(self.d, "b", key="slack-saved:C1:1.2", title="Something else entirely", created="2026-11-19T11:00:00-05:00")
        dedupe.main(AREA)
        self.assertEqual((self.status("a"), self.status("b")), ("open", "stale"))

    def test_closed_save_not_recreated(self):
        write(self.d, "old", key="slack-saved:C1:1.2", status="done")
        write(self.d, "new", key="slack-saved:C1:1.2", created="2026-11-20T10:00:00-05:00")
        dedupe.main(AREA)
        self.assertEqual(self.status("new"), "stale")


if __name__ == "__main__":
    unittest.main()
