"""S19 (Nov 17): AI-prose tics are flagged in code with the declauding skill's linter, without misfiring on chat.

Run: bin/test.sh
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import prose_lint  # noqa: E402


class Tics(unittest.TestCase):
    def test_flags_staged_prose(self):
        self.assertTrue(prose_lint.tics("Here's the thing: the bottleneck was never compute."))

    def test_plain_text_and_chat_pass(self):
        self.assertFalse(prose_lint.tics("Sounds good, sending now."))
        self.assertFalse(prose_lint.tics("1. Full key and withdrawals: No. Only the owner key can withdraw or transfer."))


if __name__ == "__main__":
    unittest.main()
