"""bin/ledger_freshness.py source_alert: a tracked source the daily pull cannot read becomes one Needs-me item,
refreshed while it lasts and closed when every source is read again (Nov 24: Claude Docs unread 10 days unnoticed)."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import ledger_freshness as lf  # noqa: E402

LATE = [{"source": "staking-spec.md", "days": 10, "last_read": "2026-11-14", "kind": "claude-doc"},
        {"source": "gtm-plan.md", "days": 10, "last_read": "2026-11-14", "kind": "claude-doc"}]


class SourceAlert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.now = datetime(2026, 11, 24, 9, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def items(self):
        return [json.loads(f.read_text()) for f in self.dir.glob("*.json")]

    def test_opens_one_item_then_refreshes_then_closes(self):
        lf.source_alert(self.now, self.dir, LATE)
        lf.source_alert(self.now, self.dir, LATE[:1])
        its = self.items()
        self.assertEqual(len(its), 1)
        it = its[0]
        self.assertEqual(it["status"], "open")
        self.assertEqual(it["due"], "2026-11-24")
        self.assertIn("Reconnect Claude Docs", it["steps"][0]["text"])
        self.assertIn("1 source (10 days)", it["title"])
        lf.source_alert(self.now, self.dir, [])
        self.assertEqual(self.items()[0]["status"], "done")

    def test_nothing_late_creates_nothing(self):
        lf.source_alert(self.now, self.dir, [])
        self.assertEqual(self.items(), [])


if __name__ == "__main__":
    unittest.main()
