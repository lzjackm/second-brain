#!/usr/bin/env python3
"""Pick the brain/knowledge files whose triggers match some text, and print them for a prompt.

Each file in brain/knowledge/ starts with front matter listing `triggers:` (comma-separated phrases). A file is
included when any trigger appears in the text as a whole word or phrase, case-insensitive.
Usage: knowledge.py <file-or-text>...   (each argument is read as a file if it exists, else used as text)
Prints nothing when no file matches.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def triggers(path):
    m = re.search(r"^triggers:\s*(.+)$", path.read_text(), flags=re.M)
    return [t.strip().lower() for t in m.group(1).split(",") if t.strip()] if m else []


def match(text):
    text = text.lower()
    out = []
    for f in sorted((ROOT / "brain" / "knowledge").glob("*.md")):
        hit = next((t for t in triggers(f) if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text)), None)
        if hit:
            out.append((f, hit))
    return out


def main(args):
    text = " ".join(Path(a).read_text() if Path(a).is_file() else a for a in args)
    hits = match(text)
    if not hits:
        return
    print("\n## Knowledge that applies (brain/knowledge; the owner's positions, follow them)\n")
    for f, hit in hits:
        body = re.sub(r"^---.*?---\n", "", f.read_text(), flags=re.S).strip()
        print(f"<!-- {f.relative_to(ROOT)}: matched '{hit}' -->\n{body}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
