"""Sync back-off (Nov 18): quiet items are checked less often; any activity resets them.

Run: bin/test.sh
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import sync_due  # noqa: E402
from identity import TZ  # noqa: E402


class BackOff(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.state = self.d / "state.json"
        self.now = datetime(2026, 11, 18, 12, 0, tzinfo=TZ)

    def item(self, synced, hist=1):
        (self.d / "a.json").write_text(json.dumps({"id": "a", "area": "w", "status": "open", "synced_at": synced.isoformat(),
                                                  "history": [{"event": "x"}] * hist}))

    def run_at(self, minutes):
        return sync_due.due("w", self.now + timedelta(minutes=minutes), self.d, self.state)

    def test_quiet_item_backs_off_then_activity_resets(self):
        t = self.now
        for k in range(5):                    # five syncs in a row that change nothing
            self.item(t + timedelta(minutes=30 * k))
            self.run_at(30 * k + 1)
        self.item(t + timedelta(minutes=120))
        self.assertEqual(self.run_at(150), [])          # quiet 4+: 30 minutes later is not due
        self.assertEqual(self.run_at(245), ["a"])       # 2 hours later it is
        self.item(t + timedelta(minutes=120), hist=2)   # the owner acted on it
        self.assertEqual(self.run_at(150), ["a"])       # back to every run

    def test_new_item_is_due(self):
        self.item(self.now - timedelta(hours=1))
        self.assertEqual(self.run_at(0), ["a"])


if __name__ == "__main__":
    unittest.main()
