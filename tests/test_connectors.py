"""Connector settings: roles, cadence and per-connector read windows (config/connectors.json, bin/connectors.py).

Run: bin/test.sh
"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import connectors  # noqa: E402


class Sources(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "state").mkdir()
        (self.d / "leads").mkdir()
        (self.d / "leads" / "work.md").write_text("x")
        self.saved = (connectors.ROOT, connectors.REG, connectors.READS)
        connectors.ROOT, connectors.REG, connectors.READS = self.d, self.d / "connectors.json", self.d / "state" / "connectors-read.json"
        base = {"read_tools": ["read_x"], "use": "things"}
        connectors.REG.write_text(json.dumps({"connectors": [
            {**base, "name": "Chat", "server": "s_chat", "role": "watch", "cadence": "every"},
            {**base, "name": "Tracker", "server": "s_tr", "role": "watch", "cadence": "daily"},
            {**base, "name": "Design", "server": "s_d", "role": "lookup"},
            {**base, "name": "Old", "server": "s_o", "role": "off"},
            {**base, "name": "Other", "server": "s_x", "role": "watch", "areas": ["elsewhere"]}]}))

    def tearDown(self):
        connectors.ROOT, connectors.REG, connectors.READS = self.saved
        shutil.rmtree(self.d)

    def test_roles_and_first_window(self):
        out = connectors.sources("work", "lead")
        watch, look = out.split("**Use only")[0], out.split("**Use only")[1]
        self.assertIn("**Chat** since", watch)
        self.assertIn("first read: 48 hours back", watch)
        self.assertIn("**Design**", look)
        self.assertNotIn("Old", out)
        self.assertNotIn("Other", out)                 # another area's connector
        self.assertNotIn("mcp__s_o__", "\n".join(connectors.tools()))

    def test_daily_cadence_and_commit_after_success(self):
        connectors.sources("work", "lead")
        started = json.loads((self.d / "state" / "connectors-pending-work.json").read_text())["started"]
        (self.d / "state" / "work.last_run").write_text(started)     # the lead finished
        out = connectors.sources("work", "lead")
        self.assertIn(f"**Chat** since {started}", out)
        self.assertIn("**Tracker**", out.split("**Use only")[1])     # daily: already read today, so lookup now

    def test_failed_run_does_not_advance(self):
        connectors.sources("work", "lead")
        (self.d / "state" / "work.last_run").write_text((datetime.now() - timedelta(days=1)).isoformat())
        self.assertIn("first read: 48 hours back", connectors.sources("work", "lead"))

    def test_settings_are_checked(self):
        self.assertTrue(connectors.settings("s_d", {"role": "watch", "cadence": "hourly", "areas": ["work", "nope"], "required": True}))
        c = next(x for x in connectors.registry() if x["server"] == "s_d")
        self.assertEqual((c["role"], c.get("cadence"), c["areas"], c["required"]), ("watch", None, ["work"], True))
        connectors.settings("s_d", {"role": "lookup"})
        self.assertFalse(next(x for x in connectors.registry() if x["server"] == "s_d")["required"])


if __name__ == "__main__":
    unittest.main()
