"""Solution Architect checks in code: numbering, unchecked negatives, routes left out, no word cap.

Run: bin/test.sh
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import architect  # noqa: E402


class NoWordCap(unittest.TestCase):
    # Nov 20: a word cap cut routes and dates to fit and added a 4-minute rewrite pass; brevity is a writing rule only.
    def test_prompts_have_no_cap(self):
        root = Path(__file__).resolve().parent.parent
        for f in ["prompts/architect.md", "prompts/architect-verify.md", "prompts/architect-revise.md", "bin/architect.py"]:
            text = (root / f).read_text()
            self.assertNotIn("SA_LIMIT", text, f)
            self.assertNotRegex(text, r"at most \{?\{?\w*\}?\}? words", f)


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



class Routes(unittest.TestCase):
    # Nov 20: the research found three solver and API routes; the answer said there was no direct route.
    def test_routes_found_must_be_named(self):
        import json
        q = {"id": "test-routes-x"}
        f = architect.lane_file(q["id"], "live")
        f.write_text(json.dumps({"routes": [{"q": "4", "route": "Relay solver payout from the hub", "status": "planned (Nov 25)"},
                                            {"q": "4", "route": "Old Bridge", "status": "not planned"}]}))
        try:
            self.assertTrue(architect.missing_routes(q, "4. Withdrawals: no direct route at launch."))
            self.assertEqual(architect.missing_routes(q, "4. Withdrawals: through the hub, then a Relay solver from Nov 25."), [])
        finally:
            f.unlink()


class CodeConfirmed(unittest.TestCase):
    # Nov 20: code checks quotes from local files so verify only checks the rest; a made-up quote must not pass.
    def test_real_quote_passes_fake_fails(self):
        import tempfile
        f = Path(tempfile.mkdtemp()) / "spec.md"
        f.write_text("A `MARKET` order is turned into a limit at the aggressive edge of that band.\nNo retry.")
        real = {"id": "C1", "sources": [{"ref": f"{f}#collar", "quote": "a MARKET order is turned into a limit ... aggressive edge of that band"}]}
        fake = {"id": "C2", "sources": [{"ref": f"{f}#collar", "quote": "every fired exit is retried three times"}]}
        link = {"id": "C3", "sources": [{"ref": "https://example.com/x", "quote": "No retry."}]}
        self.assertEqual(architect.code_confirmed([real, fake, link]), ["C1"])


class FindingIds(unittest.TestCase):
    # Nov 20: the writer cites findings by id and code copies their sources in, instead of the writer copying quotes.
    def test_claims_get_sources_from_findings(self):
        import json
        i = "test-findings-x"
        f = architect.lane_file(i, "docs")
        f.write_text(json.dumps({"findings": [{"id": "d1", "fact": "x", "source": {"ref": "a.md:3", "quote": "No retry."}}],
                                 "searched": ["ADRs: grep retry"]}))
        try:
            ans = architect.expand(i, {"claims": [{"id": "C1", "text": "No retry", "findings": ["d1", "zz"]}]})
            self.assertEqual(ans["claims"][0]["sources"], [{"ref": "a.md:3", "quote": "No retry."}])
            self.assertEqual(ans["searched"], ["ADRs: grep retry"])
        finally:
            f.unlink()


class SourceOrder(unittest.TestCase):
    # Nov 20: code, ADRs, specs and published docs are the source of truth; Slack, Drive and ledgers are secondary.
    def test_every_step_ranks_code_and_docs_first(self):
        root = Path(__file__).resolve().parent.parent
        for f in ["prompts/architect.md", "prompts/architect-lane.md", "prompts/architect-verify.md"]:
            self.assertRegex((root / f).read_text(), r"(?i)secondary", f)
        self.assertIn("primary finding", (root / "bin/architect.py").read_text())


class Sent(unittest.TestCase):
    # Nov 20: "What I sent" stores the owner's real reply; it is logged as an edit and shown to the writer as an example.
    def test_sent_is_logged_and_becomes_an_example(self):
        import json
        import tempfile
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
        import server
        saved = server.ARCH, server.LOG
        server.ARCH, server.LOG = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / "actions.jsonl"
        try:
            q = {"id": "t1", "created": "x", "status": "done", "feedback": [],
                 "turns": [{"question": "1. Is there a retry?", "final": {"shareable_answer": "1. No retry. Long explanation."}}]}
            (server.ARCH / "t1.json").write_text(json.dumps(q))
            self.assertEqual(server.arch_post("t1", {"action": "sent", "text": "1. No retry."})[0], 200)
            log = json.loads(server.LOG.read_text().splitlines()[-1])
            self.assertEqual((log["action"], log["original_draft"], log["final_draft"], log["edited"]),
                             ("sent", "1. No retry. Long explanation.", "1. No retry.", True))
            self.assertEqual(server.arch_post("t1", {"action": "sent", "text": " "})[0], 400)
        finally:
            server.ARCH, server.LOG = saved
        architect_root = architect.ROOT
        try:
            architect.ROOT = Path(tempfile.mkdtemp())
            (architect.ROOT / "architect").mkdir()
            (architect.ROOT / "architect" / "t1.json").write_text(json.dumps({"id": "t1", "turns": [
                {"question": "1. Is there a retry?", "sent": {"text": "1. No retry."}}]}))
            ex = architect.sent_examples("other")
            self.assertIn("Owner sent:\n1. No retry.", ex)
        finally:
            architect.ROOT = architect_root
