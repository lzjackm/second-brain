"""Telegram export slicing (Nov 23): group chats become text runs can read; one-to-one chats stay out.

Run: bin/test.sh
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import telegram_slice  # noqa: E402

PAGE = """<html><head><title>{title}</title></head><body><div class="page_header"><div class="body">
<div class="name bold">{title}</div>{sub}</div></div>
<div class="message default clearfix" id="m1"><div class="body"><div class="pull_right date details" title="9 October 2026, 10:00:00">10:00</div>
<div class="from_name">Sam</div><div class="text">Limits are <b>5k</b> per day<br>for now</div></div></div>
<div class="message default clearfix joined" id="m2"><div class="body"><div class="pull_right date details" title="9 October 2026, 10:01:00">10:01</div>
<div class="text">Confirmed &amp; live</div></div></div></body></html>"""


class Slice(unittest.TestCase):
    def test_groups_only_with_authors_carried(self):
        src = Path(tempfile.mkdtemp())
        for d, title, sub in (("chat_1", "Acme &lt;&gt; Us", '<div class="subtitle details">7 members</div>'), ("chat_2", "Sam Lee", "")):
            (src / "chats" / d).mkdir(parents=True)
            (src / "chats" / d / "messages.html").write_text(PAGE.format(title=title, sub=sub))
        saved = telegram_slice.OUT
        telegram_slice.OUT = Path(tempfile.mkdtemp())
        try:
            telegram_slice.main(src)
            files = sorted(p.name for p in telegram_slice.OUT.glob("*.md"))
            self.assertEqual(files, ["INDEX.md", "acme-us.md"])
            body = (telegram_slice.OUT / "acme-us.md").read_text()
            self.assertIn("Sam: Limits are 5k per day\nfor now", body)
            self.assertIn("[9 October 2026, 10:01:00] Sam: Confirmed & live", body)
        finally:
            telegram_slice.OUT = saved
