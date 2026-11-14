"""Smoke tests for a fresh template: the core modules import, a queue item's status is computed, and the checks run.
Run: bin/test.sh"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "app"))
sys.argv = sys.argv[:1]
import identity  # noqa: E402
import checks  # noqa: E402
import brevity  # noqa: E402
import server  # noqa: E402


class Smoke(unittest.TestCase):
    def item(self, owner):
        return {"id": "work-1", "title": "Reply to Sam about the launch date", "context": "Sam asked for the date.",
                "status": "open", "evidence": [{"label": "Slack", "url": "https://example.com"}],
                "steps": [{"id": "s1", "text": "Reply to Sam", "owner": owner, "status": "todo",
                           "execute": {"kind": "slack_send"}, "draft": "Friday works."}]}

    def test_owner_step_needs_owner(self):
        self.assertEqual(server.compute_status(self.item(identity.OWNER)), "open")

    def test_someone_elses_step_waits(self):
        self.assertEqual(server.compute_status(self.item("Sam Lee")), "waiting")

    def test_checks_and_brevity_run(self):
        self.assertIsInstance(checks.run(self.item(identity.OWNER)), list)
        self.assertEqual(brevity.problems(self.item(identity.OWNER)), [])


if __name__ == "__main__":
    unittest.main()
