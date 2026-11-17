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
