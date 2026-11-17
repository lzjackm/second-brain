#!/usr/bin/env python3
"""AI-prose tics in text people will read (S19), using the declauding skill's linter (bin/vendor/declaude_lint.py).

The linter finds candidates, it doesn't decide; so this keeps the categories that hold up on short business text.
Rhythm and density checks (fragment cadence, short-sentence share) misfire on chat-length messages, so they apply
only from 80 words up.
"""
import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location("declaude_lint", Path(__file__).resolve().parent / "vendor" / "declaude_lint.py")
_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lint)
LONG_ONLY = {"cadence", "density", "reuse", "typography", "participle"}


def tics(text):
    """[(category, matched words, note)] for prose tics in text; quoted passages someone else wrote are skipped."""
    if not (text or "").strip():
        return []
    long = len(re.findall(r"\S+", text)) >= 80
    hits = _lint.scan_lines(text) + (_lint.scan_density(text) if long else [])
    return [(h["category"], h.get("match", ""), h.get("note", "")) for h in hits if long or h["category"] not in LONG_ONLY]


def summary(text, limit=3):
    found = tics(text)
    return "; ".join(f"\"{m[:40]}\" ({c})" for c, m, _ in found[:limit]) + (f" and {len(found) - limit} more" if len(found) > limit else "")
