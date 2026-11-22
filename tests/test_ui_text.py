"""On-screen text stays minimal (Nov 20): placeholders are a few words and never explain keys; no explanatory
paragraphs under fields or in dialogs. Supporting detail goes in Details or nowhere.

Run: bin/test.sh
"""
import re
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "app" / "index.html").read_text()


class UiText(unittest.TestCase):
    def test_placeholders_are_short(self):
        for p in re.findall(r'placeholder(?:="|: "|:\s*")([^"$]*)"', HTML) + re.findall(r'\bbox\([^,]+,\s*"([^"]*)"\)', HTML):
            self.assertLessEqual(len(p.split()), 5, p)
            self.assertNotRegex(p, r"(?i)\benter\b|shift|e\.g\.", p)

    def test_no_explainer_lines(self):
        for t in re.findall(r'class="(?:soft|cs-help|muted|dempty)"[^>]*>([^<$`]+)<', HTML) + re.findall(r'\bsub: "([^"]*)"', HTML):
            self.assertLessEqual(len(t.split()), 12, t)


    def test_hover_text_is_a_few_words(self):
        # Nov 20: hover text grew into sentences ("Hand this step to an agent: it researches, writes a report and...").
        for tip in re.findall(r'title="([^"$]+)"', HTML):
            self.assertLessEqual(len(tip.split()), 4, tip)
        i = HTML.index("function consequence(s)")
        for tip in re.findall(r'^\s+\w+: "([^"]*)"', HTML[i:HTML.index("}[k]", i)], re.M):
            self.assertLessEqual(len(tip.split()), 3, tip)


if __name__ == "__main__":
    unittest.main()
