"""The owner's own to-do (Nov 19): a Needs me item from something no run picked up. One step of theirs, never sent
anywhere; with plan, the reviser drafts the steps from the note.

Run: bin/test.sh
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import server  # noqa: E402


class NewTodo(unittest.TestCase):
    def setUp(self):
        self.saved = server.ITEMS, server.spawn
        server.ITEMS = Path(tempfile.mkdtemp())
        self.spawned = []
        server.spawn = lambda *a: self.spawned.append(a)

    def tearDown(self):
        server.ITEMS, server.spawn = self.saved

    def item(self, iid):
        return json.loads((server.ITEMS / f"{iid}.json").read_text())

    def test_plain_todo_needs_owner(self):
        code, r = server.new_todo({"title": "Send the deck", "due": "2026-11-21", "link": "https://example.com/d"})
        self.assertEqual(code, 200)
        it = self.item(r["id"])
        self.assertTrue(server.ID_RE.match(r["id"]))
        self.assertEqual(it["status"], "open")
        self.assertEqual(it["due"], "2026-11-21")
        self.assertEqual(len(it["steps"]), 1)
        s = it["steps"][0]
        self.assertTrue(server.is_owner(s["owner"]))
        self.assertEqual(s["execute"], {"kind": "none", "url": "https://example.com/d"})
        self.assertEqual(self.spawned, [])

    def test_plan_asks_reviser(self):
        code, r = server.new_todo({"title": "Prep the partner call", "note": "they asked about fees", "plan": True})
        self.assertEqual(code, 200)
        it = self.item(r["id"])
        if (ROOT / "leads" / f"{it['area']}.md").exists():
            self.assertEqual(it["status"], "working")
            self.assertTrue(it["notes"][0]["redraft"])
            self.assertEqual(self.spawned, [("revise.sh", it["area"])])

    def test_rejects_bad_input(self):
        for body in ({}, {"title": " "}, {"title": "x", "link": "javascript:alert(1)"}, {"title": "x", "due": "tomorrow"}):
            self.assertEqual(server.new_todo(body)[0], 400, body)
        self.assertEqual(list(server.ITEMS.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
