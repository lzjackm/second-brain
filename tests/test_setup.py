"""Fresh-install regressions (setup feedback on v0.5.0, Nov 17):
1. Claude Code installed by the native installer lives in ~/.local/bin; runs must find it under launchd's bare PATH.
2. Connector discovery must keep prefixed read tools (slack_read_channel), store only real tool names, and still
   refuse writes.

Run: bin/test.sh
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import connectors  # noqa: E402


class FindsClaude(unittest.TestCase):
    def test_native_install_in_local_bin(self):
        home = Path(tempfile.mkdtemp())
        (home / ".local" / "bin").mkdir(parents=True)
        stub = home / ".local" / "bin" / "claude"
        stub.write_text("#!/bin/sh\necho stub\n")
        stub.chmod(0o755)
        out = subprocess.run(["/usr/bin/env", "-i", f"HOME={home}", "PATH=/usr/bin:/bin", "/bin/zsh", "-c",
                              f"source {ROOT}/bin/_env.zsh; print -r -- $CLAUDE"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, str(stub))


class ScriptsLoadEnv(unittest.TestCase):
    def test_every_script_sets_its_path(self):
        """The app and launchd start scripts with a bare PATH; one that skips bin/_env.zsh can't find gh or claude
        (Nov 17: the meeting agent stopped before starting)."""
        skip = {"sandbox.sh", "gitread.sh"}     # run by other scripts, with absolute paths
        missing = [p.name for p in sorted((ROOT / "bin").glob("*.sh"))
                   if p.name not in skip and "_env.zsh" not in p.read_text()]
        self.assertEqual(missing, [])


class OwnerNames(unittest.TestCase):
    def test_first_name_counts_as_owner(self):
        """Nov 17: runs wrote the owner's first name, so the template's app hid Send, Skip, Ask and the agent."""
        import identity
        if identity.OWNER_FIRST and identity.OWNER_FIRST != "the owner":
            self.assertTrue(identity.is_owner(identity.OWNER_FIRST))
            self.assertTrue(identity.is_owner(identity.OWNER_FIRST.lower()))
        self.assertTrue(identity.is_owner(identity.OWNER))


class Discovery(unittest.TestCase):
    S = "claude_ai_Slack"
    REAL = {f"mcp__claude_ai_Slack__{n}" for n in ("slack_read_channel", "slack_read_thread", "slack_search_public",
                                                   "slack_send_message", "slack_send_message_draft", "slack_create_canvas")}

    def test_prefixed_read_tools_kept_and_writes_refused(self):
        read, write = connectors.classify(self.S, self.REAL)
        self.assertEqual(read, ["slack_read_channel", "slack_read_thread", "slack_search_public"])
        self.assertIn("slack_send_message", write)

    def test_model_shortened_names_map_to_real_ones(self):
        read, _ = connectors.classify(self.S, self.REAL, ["read_channel", "mcp__claude_ai_Slack__read_thread", "invented_tool"])
        self.assertEqual(read, ["slack_read_channel", "slack_read_thread"])

    def test_verbs(self):
        for name, want in [("conversational_search", True), ("execute-sql", False), ("get_social_post_analytics", True),
                           ("get_or_create_drive", False), ("manage_blog_post", False), ("create_session", True)]:
            self.assertEqual(connectors.is_read(name), want, name)


if __name__ == "__main__":
    unittest.main()


class ZshGlobs(unittest.TestCase):
    # Nov 20: `rm -f state/sa-lane-*-ID.json` with no match aborted architect.sh (zsh "no matches found" under set -e),
    # so every Solution Architect run stopped in its first second. A bare glob in rm needs (N).
    def test_rm_globs_allow_no_match(self):
        import re
        root = Path(__file__).resolve().parent.parent
        for f in sorted((root / "bin").glob("*.sh")):
            for n, line in enumerate(f.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if re.search(r"\brm\b", code) and re.search(r"\*[^\"']*(?:\s|$)", code) and "(N)" not in code:
                    self.fail(f"{f.name}:{n}: rm with a glob needs (N): {line.strip()}")
