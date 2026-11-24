"""Executor brain edits end to end in a scratch git repo (the model run is replaced by a stand-in that adds the rule).

Pins two misses from Nov 15 and 16: quick presses ran two executors whose edits blocked each other, and a trimmed
`git status` line hid a successful edit ("The rule was not added").
Run: bin/test.sh
"""
import subprocess
import sys
import tempfile
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import execute  # noqa: E402


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class BrainEdit(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "brain" / "knowledge").mkdir(parents=True)
        (self.d / "brain" / "principles.md").write_text("# Principles\n- **P1** one\n")
        (self.d / "brain" / "knowledge" / "x.md").write_text("x\n")
        sh(self.d, "git", "init", "-q")
        sh(self.d, "git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        sh(self.d, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        self.saved = execute.ROOT, execute.STATE, execute.edit_run
        execute.ROOT, execute.STATE = self.d, self.d
        self.step = {"id": "s1", "draft": "- **P2** two", "execute": {"kind": "brain_edit", "target": "brain/principles.md"}}

    def tearDown(self):
        execute.ROOT, execute.STATE, execute.edit_run = self.saved

    def adds_rule(self, *extra):
        def run(name, prompt, allowed):
            with (self.d / "brain" / "principles.md").open("a") as fh:
                fh.write(self.step["draft"] + "\n")
            for f in extra:
                (self.d / f).write_text("changed by the run\n")
        execute.edit_run = run

    def committed(self):
        return subprocess.run(["git", "log", "-1", "--format=%s"], cwd=self.d, capture_output=True, text=True).stdout

    def test_rule_is_added_and_committed(self):
        self.adds_rule()
        self.assertEqual(execute.do_brain_edit({"id": "i"}, self.step)[0], "rule added")
        self.assertIn("brain: P2", self.committed())
        self.assertEqual(execute.git("status", "--porcelain"), "")

    def test_other_brain_files_changed_meanwhile_do_not_block(self):
        (self.d / "brain" / "knowledge" / "x.md").write_text("edited by another run\n")
        self.adds_rule()
        self.assertEqual(execute.do_brain_edit({"id": "i"}, self.step)[0], "rule added")

    def test_edit_that_touches_another_file_is_undone(self):
        self.adds_rule("brain/knowledge/x.md")
        with self.assertRaises(execute.Fail):
            execute.do_brain_edit({"id": "i"}, self.step)
        self.assertNotIn("P2", (self.d / "brain" / "principles.md").read_text())

    def test_git_keeps_leading_space(self):
        (self.d / "brain" / "principles.md").write_text("changed\n")
        self.assertTrue(execute.git("status", "--porcelain").startswith(" M "))


if __name__ == "__main__":
    unittest.main()


class ApproveFix(unittest.TestCase):
    def test_queues_the_spec_privately(self):
        import json
        import os
        import press
        d = Path(tempfile.mkdtemp())
        saved = press.PRIVATE
        press.PRIVATE = d
        try:
            result, _ = execute.do_approve_fix({"id": "i", "title": "Fix: x"}, {"id": "s1", "draft": "plain", "spec": "tech detail"})
            rec = json.loads((d / "approved-fixes.jsonl").read_text().splitlines()[-1])
            self.assertEqual(rec["spec"], "tech detail")
            self.assertIn("Claude Code", result)
        finally:
            press.PRIVATE = saved


class GdocUpdate(unittest.TestCase):
    # Nov 23: "update the memo" was a by-hand step; the executor now suggests edits in an existing doc.
    def test_pairs_applied_as_suggestions_and_refused_when_text_moved(self):
        import execute
        doc = '{"body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "Vendor A: $1.25M loan\\\\n"}}]}}]}}'
        calls = []
        saved = execute.mcp_call
        wrapped = json.dumps(json.dumps({"content": [{"type": "text", "text": doc}]}))   # as the connector can wrap it
        execute.mcp_call = lambda tool, args, label: calls.append((tool, args)) or (wrapped if tool.endswith("read_doc") else "ok")
        try:
            step = {"id": "s4", "execute": {"kind": "gdoc_update", "target": "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdef/edit"},
                    "draft": "Replace: Vendor A: $1.25M loan\nWith: Vendor B: $1.25M loan"}
            res, link = execute.do_gdoc_update({"id": "x"}, step)
            self.assertIn("1 change suggested", res)
            req = calls[-1][1]
            self.assertEqual(req["writeControl"]["writeMode"], "SUGGEST")
            self.assertEqual(req["requests"][0]["replaceAllText"]["replaceText"], "Vendor B: $1.25M loan")
            step["draft"] = "Replace: Vendor C: $9M loan\nWith: Vendor C: $1.5M loan"
            with self.assertRaises(execute.Fail):
                execute.do_gdoc_update({"id": "x"}, step)
        finally:
            execute.mcp_call = saved
