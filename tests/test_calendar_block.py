"""Drafting runs see the owner's meetings today and on the next working day (Nov 23, P38).

Run: bin/test.sh
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import calendar_block  # noqa: E402
from identity import TZ, OWNER  # noqa: E402


class CalendarBlock(unittest.TestCase):
    def test_friday_shows_monday_and_drops_the_owner(self):
        d = Path(tempfile.mkdtemp())
        (d / "2026-11-20.json").write_text(json.dumps({"events": [{"title": "Partner sync", "start": "2026-11-20T11:30:00-05:00",
                                                                    "attendees": [{"email": "Sam Lee"}, {"name": OWNER}]}]}))
        (d / "2026-11-23.json").write_text(json.dumps({"events": []}))
        out = calendar_block.block(datetime(2026, 11, 20, 9, tzinfo=TZ), d)
        self.assertIn("11:30 Partner sync (with Sam Lee)", out)
        self.assertIn("Monday Nov 23:\n- nothing booked", out)
        self.assertEqual(calendar_block.block(datetime(2026, 11, 20, 9, tzinfo=TZ), Path(tempfile.mkdtemp())), "")


if __name__ == "__main__":
    unittest.main()
