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

    def test_reaction_is_not_an_ask(self):
        # Nov 25: the owner had replied; the partner's next messages were a reaction, not a request.
        base = {"names_owner": True, "after_owner_last": True, "answered_by": []}
        said = "wish I had known that earlier\nthat changes our sizing\nthe risk is a lot higher"
        self.assertIn("nothing was asked", reply_gate.verdict({**base, "said": said, "request": ""}))
        self.assertIsNone(reply_gate.verdict({**base, "said": "what time on Monday?", "request": ""}))
        self.assertIsNone(reply_gate.verdict({**base, "said": "ok", "request": "send the signed copy"}))
        self.assertIsNone(reply_gate.verdict(base))   # older records without `said` keep the old rules

    def test_owed_send(self):
        # Nov 25: a promised message the partner had already called off the day before; someone else was handling it.
        ok = {"promised": "Sure", "at": "2026-11-24T15:24:00-05:00", "link": "x", "read_since": "2026-11-17T00:00:00-05:00",
              "called_off": [], "handled_by": []}
        self.assertIsNone(reply_gate.owed_verdict(ok))
        self.assertIn("called off", reply_gate.owed_verdict({**ok, "called_off": ["No need, leave it as it is"]}))
        self.assertIn("handling", reply_gate.owed_verdict({**ok, "handled_by": ["Sam"]}))
        self.assertIn("far enough", reply_gate.owed_verdict({**ok, "read_since": "2026-11-24T00:00:00-05:00"}))
        self.assertIn("wasn't checked", reply_gate.owed_verdict({"promised": "Sure"}))

    def test_send_needs_ask_or_owed(self):
        step = {"id": "s1", "execute": {"kind": "slack_send"}}
        self.assertIn("neither", reply_gate.step_verdict({"created": "2026-11-25T13:00:00-05:00"}, step))
        self.assertIsNone(reply_gate.step_verdict({"created": "2026-11-20T13:00:00-05:00"}, step))


if __name__ == "__main__":
    unittest.main()
