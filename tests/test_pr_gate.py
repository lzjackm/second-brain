"""Items asking the owner to approve or merge a PR they opened are retired in code (Nov 21: digest PR items were skipped
by hand on Nov 13, 16 and 21).

Run: bin/test.sh
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import identity  # noqa: E402
import pr_gate  # noqa: E402

URL = "https://github.com/acme/ledger/pull/62"


def item(iid, kind, author_url=URL):
    return {"id": iid, "area": "main", "status": "open", "history": [],
            "steps": [{"id": "s1", "owner": identity.OWNER, "status": "todo", "execute": {"kind": "none", "url": author_url}},
                      {"id": "s2", "owner": identity.OWNER, "status": "todo", "execute": {"kind": kind, "target": author_url}}]}


class PrGate(unittest.TestCase):
    def setUp(self):
        self.saved, pr_gate.ITEMS = pr_gate.ITEMS, Path(tempfile.mkdtemp())

    def tearDown(self):
        pr_gate.ITEMS = self.saved

    def status(self, iid):
        return json.loads((pr_gate.ITEMS / f"{iid}.json").read_text())["status"]

    def test_own_pr_merge_retired_others_kept(self):
        for iid, kind, url in [("own", "pr_merge", URL), ("approve", "pr_approve", URL), ("theirs", "pr_merge", "https://github.com/acme/ledger/pull/7"),
                               ("send", "slack_send", URL)]:
            (pr_gate.ITEMS / f"{iid}.json").write_text(json.dumps(item(iid, kind, url)))
        authors = {"62": "me-login", "7": "someone-else"}
        pr_gate.sweep(login="me-login", author_of=lambda repo, n: authors.get(n))
        self.assertEqual([self.status(x) for x in ("own", "approve", "theirs", "send")], ["stale", "stale", "open", "open"])


if __name__ == "__main__":
    unittest.main()


class RouteToFixes(unittest.TestCase):
    # Nov 23: the learning run's Fix items and rules the owner already stated go to the fix queue, not the owner.
    def setUp(self):
        sys.path.insert(0, str(ROOT / "app"))
        import server
        import fixes
        self.server, self.fixes = server, fixes
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (fixes.path, server.MEMORY_DIR)
        fixes.path = lambda: self.tmp / "approved-fixes.jsonl"
        server.MEMORY_DIR = self.tmp
        (self.tmp / "feedback_x.md").write_text("rule")

    def tearDown(self):
        self.fixes.path, self.server.MEMORY_DIR = self.saved

    def item(self, kind, evidence, job="distill"):
        return {"id": f"t-{kind}", "status": "open", "made_by": {"job": job}, "evidence": evidence, "history": [],
                "steps": [{"id": "s1", "owner": identity.OWNER, "status": "todo", "draft": "x", "execute": {"kind": kind}}]}

    def test_fix_and_stated_rule_route_inferred_rule_stays(self):
        fix, stated = self.item("approve_fix", []), self.item("brain_edit", [{"label": "feedback_x.md (owner, Nov 8)"}])
        inferred, ux = self.item("brain_edit", [{"label": "3 edits this week"}]), self.item("approve_fix", [], job="ux-review")
        got = [self.server.route_to_fixes(i, i["steps"][0]) for i in (fix, stated, inferred, ux)]
        self.assertEqual(got, [True, True, False, False])
        self.assertEqual(len(self.fixes.entries()), 2)
        self.assertEqual(fix["steps"][0]["status"], "done")
