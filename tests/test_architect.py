"""Solution Architect length (V10 in code). Nov 17: a 90-word client question got a 490-word answer.

Run: bin/test.sh
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import architect  # noqa: E402


class Length(unittest.TestCase):
    def q(self, n):
        return {"turns": [{"question": " ".join(["w"] * n)}]}

    def test_limit_tracks_the_question(self):
        self.assertEqual(architect.limit(self.q(90), self.q(90)["turns"][0]), 108)
        self.assertEqual(architect.limit(self.q(10), self.q(10)["turns"][0]), 50)     # floor
        self.assertEqual(architect.limit(self.q(400), self.q(400)["turns"][0]), 160)  # cap

    def test_revision_uses_the_original_question(self):
        q = {"turns": [{"question": " ".join(["w"] * 90)}, {"question": "shorter please", "kind": "revise", "revises": 0}]}
        self.assertEqual(architect.limit(q, q["turns"][1]), 108)


if __name__ == "__main__":
    unittest.main()


class Confidence(unittest.TestCase):
    """Confidence from the checker's results (Nov 18), not the model's self-rating."""

    def final(self, outcomes, unconfirmed=0, answered=("yes",), verified=True):
        return {"verified": verified, "claims": [{"outcome": o, "shareable": True} for o in outcomes],
                "unconfirmed": [{}] * unconfirmed, "questions": [{"answered": a} for a in answered]}

    def test_high_when_everything_holds(self):
        self.assertEqual(architect.confidence(self.final(["confirmed", "revised"]))[0], "high")

    def test_medium_reasons(self):
        lvl, why = architect.confidence(self.final(["confirmed"], unconfirmed=2))
        self.assertEqual((lvl, why), ("medium", ["2 claims only in docs or Slack"]))
        self.assertEqual(architect.confidence(self.final(["confirmed"], answered=("partly",)))[0], "medium")

    def test_low(self):
        self.assertEqual(architect.confidence(self.final(["confirmed", "refuted"]))[0], "low")
        self.assertEqual(architect.confidence(self.final(["confirmed"], answered=("no",)))[0], "low")


class Busy(unittest.TestCase):
    def test_run_lock_covers_gap_between_answer_and_verify(self):
        # Nov 19: past the 90s grace, with neither the answer nor the verify lock held, a finished turn was marked failed.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
        import os
        import server
        qid = "test-busy-gap"
        lock = server.STATE / f"architect-run-{qid}.lock"
        q = {"id": qid, "turns": [{"pending": "2026-01-01T00:00:00-05:00"}]}
        self.assertFalse(server.arch_busy(q))
        lock.mkdir(parents=True)
        try:
            (lock / "pid").write_text(str(os.getpid()))
            self.assertTrue(server.arch_busy(q))
        finally:
            (lock / "pid").unlink()
            lock.rmdir()


class Checks(unittest.TestCase):
    # Nov 19, a client's five numbered questions, answered as "1. 2. 3." by topic, with
    # "no date" and "aren't published" written without a Slack search.
    Q = {"id": "x", "turns": [{"question": "1. Why did exits expire?\n\n2. Will child orders carry a parent id?\n\nDeposits\n\n"
                                            "3. What do we need to bridge in?\n\n4. How does a withdrawal leave the hub?\n\nMarkets\n\n"
                                            "5. Will the symbols endpoint list the real ladder? " + "word " * 300,
                               "answer": {"searched": ["ADRs: grep exits", "Slack/Drive: not searched (quick depth)"]}}]}

    def flags(self, ans):
        return architect.problems(self.Q, self.Q["turns"][0], {"shareable_answer": ans})

    def test_renumbered_by_topic_is_sent_back(self):
        f = self.flags("1. Exits: capped.\n\n2. Deposits: soon.\n\n3. Markets: Yes.")
        self.assertTrue(any("client's own question numbers (1, 2, 3, 4, 5)" in x for x in f))

    def test_combined_blocks_keep_numbers(self):
        self.assertEqual(self.flags("1/2. Exits: capped.\n\n3 and 4. Deposits: by Monday.\n\n5. Markets: Yes."), [])

    def test_no_date_needs_a_slack_search(self):
        f = self.flags("1/2. Not on testnet yet, with no date.\n\n3-4. Addresses aren't published yet.\n\n5. Yes.")
        self.assertTrue(any("Slack was not searched" in x for x in f))
        self.Q["turns"][0]["answer"]["searched"].append("Slack: 'parent id next upgrade' in #dev")
        try:
            self.assertEqual(self.flags("1/2. Not on testnet yet, with no date.\n\n3-4. Not published yet.\n\n5. Yes."), [])
        finally:
            self.Q["turns"][0]["answer"]["searched"].pop()

    def test_five_questions_get_more_room(self):
        self.assertEqual(architect.limit(self.Q, self.Q["turns"][0]), 275)
