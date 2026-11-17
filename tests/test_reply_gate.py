"""Reply gate (P26 in code): replies that stopped being the owner's leave the queue. Nov 16: a channel question
three others answered, in a thread the owner had already replied to, reached Needs me.

Run: bin/test.sh
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import reply_gate  # noqa: E402


class Gate(unittest.TestCase):
    def test_retires(self):
        base = {"names_owner": True, "after_owner_last": True, "answered_by": []}
        self.assertIsNone(reply_gate.verdict(base))
        self.assertIn("answered", reply_gate.verdict({**base, "answered_by": ["Sam"]}))
        self.assertIn("already replied", reply_gate.verdict({**base, "after_owner_last": False}))
        self.assertIn("didn't name you", reply_gate.verdict({**base, "names_owner": False}))
        self.assertIsNone(reply_gate.verdict(None))


if __name__ == "__main__":
    unittest.main()
