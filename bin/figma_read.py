#!/usr/bin/env python3
"""Read-only Figma access for agents, through the Figma REST API.

The token lives in the macOS Keychain (service f"{SLUG}-figma") and should be a
personal access token with read-only scopes (file content: read, comments: read),
so Figma itself refuses any write.

Usage:
  figma_read.py slides   <file_key_or_url> [--grep TEXT]     list slides/frames with their text
  figma_read.py comments <file_key_or_url> [--grep TEXT]     list comments (who, when, which node, text)
  figma_read.py render   <file_key_or_url> <node_id,...> <out_dir> [--scale 1]   save PNGs of nodes
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.figma.com/v1"


def token():
    try:
        return subprocess.run(["security", "find-generic-password", "-s", f"{SLUG}-figma", "-w"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        sys.exit(f"No Figma token in Keychain (service {SLUG}-figma). See the README, Figma access.")


def get(path, params=None):
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={"X-Figma-Token": token()})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Figma API {e.code} on {path}: {e.read().decode()[:300]}")


def file_key(s):
    m = re.search(r"figma\.com/(?:file|design|slides|deck|proto|board)/([A-Za-z0-9]+)", s)
    return m.group(1) if m else s


def texts(node):
    out = []
    if node.get("type") == "TEXT" and node.get("characters"):
        out.append(node["characters"].strip())
    for c in node.get("children", []) or []:
        out.extend(texts(c))
    return out


def slides(key, grep):
    url = f"{API}/files/{key}"
    req = urllib.request.Request(url, headers={"X-Figma-Token": token()})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            doc = json.load(r)["document"]
    except urllib.error.HTTPError as e:
        if e.code == 400 and b"not supported" in e.read():
            sys.exit("This is a Figma Slides file: the API does not return slide text. Use `comments` to find the "
                     "nodes people commented on, then `render` those node ids and Read the PNGs.")
        raise
    found = []

    def walk(node, depth):
        t = node.get("type")
        if t == "SLIDE" or (t == "FRAME" and depth == 2 and not found_slides[0]):
            found.append(node)
            return
        for c in node.get("children", []) or []:
            walk(c, depth + 1)

    # Prefer real SLIDE nodes (Figma Slides); fall back to top-level frames per page (Design files).
    found_slides = [False]

    def has_slide(node):
        return node.get("type") == "SLIDE" or any(has_slide(c) for c in node.get("children", []) or [])
    found_slides[0] = has_slide(doc)
    walk(doc, 0)
    for n, s in enumerate(found, 1):
        body = " | ".join(x for x in texts(s) if x)
        if grep and grep.lower() not in (s.get("name", "") + " " + body).lower():
            continue
        print(json.dumps({"n": n, "id": s["id"], "name": s.get("name"), "text": body[:4000]}, ensure_ascii=False))


def comments(key, grep):
    for c in get(f"/files/{key}/comments").get("comments", []):
        row = {"id": c.get("id"), "at": c.get("created_at"), "by": (c.get("user") or {}).get("handle"),
               "node": (c.get("client_meta") or {}).get("node_id"), "parent": c.get("parent_id") or None,
               "resolved": bool(c.get("resolved_at")), "text": c.get("message")}
        if grep and grep.lower() not in json.dumps(row).lower():
            continue
        print(json.dumps(row, ensure_ascii=False))


def render(key, ids, out_dir, scale):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    images = get(f"/images/{key}", {"ids": ids, "format": "png", "scale": scale}).get("images", {})
    for node_id, url in images.items():
        if not url:
            print(f"{node_id}: no image")
            continue
        dest = out / f"{node_id.replace(':', '-')}.png"
        urllib.request.urlretrieve(url, dest)
        print(dest)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("slides", "comments"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--grep")
    p = sub.add_parser("render")
    p.add_argument("file")
    p.add_argument("ids")
    p.add_argument("out_dir")
    p.add_argument("--scale", type=float, default=1)
    a = ap.parse_args()
    k = file_key(a.file)
    if a.cmd == "slides":
        slides(k, a.grep)
    elif a.cmd == "comments":
        comments(k, a.grep)
    else:
        render(k, a.ids, a.out_dir, a.scale)
