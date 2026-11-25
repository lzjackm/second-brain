"""The draft gate (framework phase 1): high-stakes drafts show what they read and the owner's position per point before
the owner sees them. Cases replay the Nov 25 misses.

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
import checks  # noqa: E402
import draft_gate as g  # noqa: E402

LIST = "Thanks Pat. By number:\n1. Apply the fix.\n2. Accept the risk.\n3. [your call: hold the date or accept]"
FULL_READ = [{"source": "Vendor A redline docx", "kind": "doc", "from": "2026-11-24", "to": "2026-11-24"},
             {"source": "Slack #deals-legal", "kind": "chat", "from": "2026-11-10", "to": "2026-11-25"},
             {"source": "Slack DM with Sam (Vendor A)", "kind": "chat", "from": "2026-11-10", "to": "2026-11-25"},
             {"source": "brain/knowledge/vendor-terms.md", "kind": "knowledge", "from": None, "to": None}]
POINTS = [{"point": "1", "position": "apply the fix", "source": "Slack DM, Nov 24", "theirs": "Legal: apply the fix"},
          {"point": "2", "position": "accept the risk", "source": "call with Sam, Nov 24", "theirs": None},
          {"point": "3", "position": None, "source": None, "theirs": "Legal: hold Nov 30"}]


def item(draft=LIST, brief=None, audience="external", summary="Vendor A returned redlines; 3 points", **step):
    s = {"id": "s1", "owner": identity.OWNER, "status": "todo", "draft": draft,
         "execute": {"kind": "email_draft", "audience": audience},
         "ask": {"from": "Pat", "at": "2026-11-25T13:54:00-05:00", "names_owner": True, "after_owner_last": True}, **step}
    if brief is not None:
        s["brief"] = brief
    return {"id": "x", "area": "main", "type": "approve_send", "status": "open", "created": "2026-11-25T19:00:00-05:00",
            "title": "Reply to Pat on the Vendor A redlines", "summary": summary, "history": [], "steps": [s]}


class DraftGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (g.ITEMS, g.KNOWLEDGE)
        g.ITEMS, g.KNOWLEDGE = self.tmp / "items", self.tmp / "knowledge"
        g.ITEMS.mkdir()
        g.KNOWLEDGE.mkdir()
        (g.KNOWLEDGE / "vendor-terms.md").write_text("---\ntitle: x\ntriggers: Vendor A, redline\nsources: deals-legal\n---\nbody")

    def tearDown(self):
        g.ITEMS, g.KNOWLEDGE = self.saved

    def why(self, it):
        return " | ".join(g.problems(it, it["steps"][0]))

    def test_redline_reply_needs_reading_and_sourced_points(self):
        # Nov 25, a vendor contract: read only email, took Legal's fix where the owner had settled points with the firm.
        self.assertIn("no brief", self.why(item()))
        email_only = {"read": [{"source": "Email thread", "kind": "email", "from": "2026-11-20", "to": "2026-11-25"}], "points": POINTS}
        w = self.why(item(brief=email_only))
        self.assertIn("read no chat, doc, knowledge source", w)
        self.assertIn("deals-legal", w)
        self.assertEqual(self.why(item(brief={"read": FULL_READ, "points": POINTS})), "")
        unsourced = [dict(p, position=None, source=None) for p in POINTS]
        self.assertIn("3 points have no position", self.why(item(brief={"read": FULL_READ, "points": unsourced})))
        borrowed = [dict(POINTS[0], position="Legal: apply the fix")] + POINTS[1:]
        self.assertIn("someone else's recommendation", self.why(item(brief={"read": FULL_READ, "points": borrowed})))
        self.assertIn("accounts for 2", self.why(item(brief={"read": FULL_READ, "points": POINTS[:2]})))

    def test_chats_read_back_seven_days(self):
        # Nov 25, a promised message: the DM was read from Nov 24 and missed the Nov 23 message that called it off.
        short = [dict(r, **{"from": "2026-11-24"}) if r["kind"] == "chat" else r for r in FULL_READ]
        self.assertIn("read back at least 7 days", self.why(item(brief={"read": short, "points": POINTS})))

    def test_low_stakes_and_owner_words_pass(self):
        internal = item(draft="Sounds good, thanks.", audience=None, summary="Sam asked about lunch")
        internal["title"] = "Reply to Sam"
        self.assertEqual(self.why(internal), "")
        self.assertEqual(self.why(item(owner_edited="2026-11-25T15:10:00-05:00")), "")

    def test_one_automatic_revision_then_k18_blocks(self):
        it = item()
        (g.ITEMS / "x.json").write_text(json.dumps(it))
        self.assertEqual(g.sweep(), {"main"})
        got = json.loads((g.ITEMS / "x.json").read_text())
        self.assertEqual(got["steps"][0]["revisions"][-1]["by"], "draft_gate")
        self.assertEqual(g.sweep(), set())                       # revision underway
        got["steps"][0]["revised_at"] = "2099-01-01T00:00:00-05:00"
        (g.ITEMS / "x.json").write_text(json.dumps(got))
        self.assertEqual(g.sweep(), set())                       # still failing: no second loop
        self.assertIn(("K18", "block"), [(c["code"], c["level"]) for c in checks.run(got)])

    def test_older_items_untouched(self):
        it = item()
        it["created"] = "2026-11-24T10:00:00-05:00"
        self.assertIsNone(g.gated(it))


if __name__ == "__main__":
    unittest.main()
