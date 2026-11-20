"""Pasted images for the Solution Architect (Nov 18): real images only, by their bytes; attached to the question.

Run: bin/test.sh
"""
import base64
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import server  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


class Images(unittest.TestCase):
    def setUp(self):
        self.saved = server.ARCH_IMG
        server.ARCH_IMG = Path(tempfile.mkdtemp())

    def tearDown(self):
        server.ARCH_IMG = self.saved

    def test_png_saved_and_attached(self):
        code, r = server.arch_image_save({"data": "data:image/png;base64," + base64.b64encode(PNG).decode()})
        self.assertEqual(code, 200)
        self.assertEqual(server.arch_images({"images": [r["name"], "../../etc/passwd", "ffffffffffffffff.png"]}), [r["name"]])

    def test_non_image_refused(self):
        for data in ("data:image/png;base64," + base64.b64encode(b"<script>").decode(), "not a data url"):
            self.assertEqual(server.arch_image_save({"data": data})[0], 400)


if __name__ == "__main__":
    unittest.main()
