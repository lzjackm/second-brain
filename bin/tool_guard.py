#!/usr/bin/env python3
"""PreToolUse and PostToolUse hook for every headless run (bin/_claude.sh passes it in --settings).

Every run reads untrusted text (Slack, Drive, meeting notes, PRs, client questions), so a run's allowlist is not
trusted to be tight enough on its own. This hook works by allowlist, whatever the run's own allowlist says:
- files: reads only inside this brain, ~/Projects (minus .env, keys and git credentials), the Claude memory folder,
  the configured source folders, temp folders and system folders outside the home folder; writes only inside this
  brain's data folders, its cache and temp. Code folders (bin, app, prompts, config, launchd, .claude) are never
  written, and the private press store is never touched.
- shell: no substitution, variables, escapes or `..`; every path argument must pass the read rule; output may go
  only to /dev/null; no network, secret, shell or git commands (git only through bin/gitread.sh).
- web fetches: short URLs only, so a fetch cannot carry data out.
- connectors: only the read tools registered in config/connectors.json.

Executor mode (JB_GUARD_EXPECT=<file>): the run may call exactly the one tool named in the file, once, and the hook
replaces the run's arguments with the file's. The model never sees or chooses what is sent: the owner's pressed
draft and target go straight from the file to the tool. PostToolUse saves the tool's response to JB_GUARD_RESULT.
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

HOME = os.path.realpath(str(Path.home()))
ROOT = os.path.realpath(str(Path(__file__).resolve().parent.parent))
try:
    CFG = json.loads((Path(ROOT) / "config" / "brain.json").read_text())
except (OSError, json.JSONDecodeError):
    CFG = {}
SLUG = CFG.get("slug") or "second-brain"
PRIVATE = os.path.realpath(os.environ.get("BRAIN_PRIVATE") or f"{HOME}/Library/Application Support/{SLUG}")
CACHE = os.path.realpath(f"{HOME}/Library/Caches/{SLUG}")
MEMORY = os.path.realpath(f"{HOME}/.claude/projects/{re.sub(r'[/.]', '-', str(Path.home()))}/memory")
_extra = [*(CFG.get("source_dirs") or []), *(((CFG.get("modules") or {}).get("architect") or {}).get("search_dirs") or [])]
READ_ROOTS = [ROOT, f"{HOME}/Projects", MEMORY, CACHE, *(os.path.realpath(os.path.expanduser(d)) for d in _extra)]
TEMP = ["/tmp", "/private/tmp", "/private/var/folders"]
SECRET_FILE = re.compile(r"(/\.env[^/]*$|\.(pem|key|p12|pfx)$|/\.git/config$|/\.git-credentials$|/id_(rsa|ed25519|ecdsa)[^/]*$)")
NO_WRITE = [f"{ROOT}/{d}" for d in ("bin", "app", "prompts", "config", "launchd", ".claude", ".git", "template", "tests")]
WRITE_ROOTS = [ROOT, CACHE, *TEMP]
BAD_CMD = re.compile(
    r"(^|[\s;&|(])(security|curl|wget|nc|ncat|netcat|ssh|scp|sftp|rsync|osascript|telnet|ftp|socat|openssl|base64|"
    r"xxd|launchctl|crontab|sudo|chmod|chown|ln|eval|source|env|printenv|export|cd|pushd|open|nohup|xargs|tee|dd|"
    r"perl|ruby|node|bash|sh|zsh|python3?|/opt/homebrew/bin/python3?|git)(\s|$)"
    r"|--endpoint-url|--endpoint\b|\bENV\b|\$__loc__|input_filename|/dev/tcp|/dev/udp")
WRAPPED = re.compile(r"(^|[\s;&|(])(\S*/)?bin/(sandbox\.sh\s+python3|gitread\.sh)(?=\s|$)")
OK_REDIRECT = re.compile(r"\d?>&\d|&?\d?>\s*/dev/null")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": f"Blocked by tool_guard: {reason}"}}))
    sys.exit(0)


def inside(p, roots):
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)


def real(p, base=ROOT):
    p = os.path.expanduser(str(p))
    return os.path.realpath(p if os.path.isabs(p) else os.path.join(base, p))


def readable(p):
    p = real(p)
    if inside(p, [PRIVATE]) or SECRET_FILE.search(p):
        return False
    if not inside(p, [HOME]):
        return True                       # system folders and temp
    return inside(p, READ_ROOTS)


def writable(p):
    p = real(p)
    return inside(p, WRITE_ROOTS) and not inside(p, NO_WRITE + [PRIVATE]) and not SECRET_FILE.search(p)


def glob_prefix(p):
    """The fixed part of a path with glob characters: the folder a glob could reach into."""
    parts = []
    for part in str(p).split("/"):
        if re.search(r"[*?\[\]{}]", part):
            break
        parts.append(part)
    return "/".join(parts) or "."


def check_bash(cmd):
    unquoted = re.sub(r"'[^']*'", "''", cmd)               # single-quoted text is literal to the shell
    if re.search(r"[$`\\]|<\(|>\(", unquoted):
        deny("no variables, substitution or escapes in brain shell commands")
    if re.search(r"(^|[\s/'\"=])\.\.(/|\s|$|['\"])", cmd):
        deny("no .. in paths")
    if BAD_CMD.search(WRAPPED.sub(r"\1WRAPPED", unquoted)):
        deny("command not allowed in brain runs (network, secrets, shells, inline code, or git outside bin/gitread.sh)")
    for m in re.finditer(r"&?\d?>>?\|?\s*(&\d|[^\s;&|]*)", unquoted):
        if not OK_REDIRECT.fullmatch(m.group(0).strip()):
            deny("shell output may go only to /dev/null; write files with the Write tool")
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        deny("unparseable command")
    code = False
    for t in tokens:
        if code:                                   # the -c argument of sandboxed python: the sandbox confines it
            code = False
            continue
        if t == "-c":
            code = True
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*://", t) or t.startswith("-") or ("/" not in t and not t.startswith("~")):
            continue
        if not readable(glob_prefix(t)):
            deny(f"path outside the brain's readable folders: {t[:60]}")


def risky_url(url):
    m = re.match(r"^https?://([^/?#]+)([^?#]*)(\?[^#]*)?$", url or "")
    if not m:
        return "only plain http and https URLs"
    host, path, query = m.group(1), m.group(2), m.group(3) or ""
    if "@" in host or len(host) > 60 or any(len(label) > 24 for label in host.split(".")):
        return "unusual host"
    if len(url) > 160 or len(query) > 80:
        return "URL too long"
    if any(len(seg) > 32 for seg in re.split(r"[/&=?.+_-]", path + query) if re.search(r"\d", seg) and re.search(r"[A-Za-z]", seg)):
        return "long opaque segment in the URL"
    return None


def read_tools():
    try:
        reg = json.loads((Path(ROOT) / "config" / "connectors.json").read_text()).get("connectors") or []
    except (OSError, json.JSONDecodeError):
        return set()
    return {f"mcp__{c['server']}__{t}" for c in reg for t in c.get("read_tools") or []}


def pre(ev):
    tool, inp = ev.get("tool_name", ""), ev.get("tool_input") or {}
    expect = os.environ.get("JB_GUARD_EXPECT")
    if expect:
        if tool == "ToolSearch":
            return
        want = json.loads(Path(expect).read_text())
        used = Path(expect + ".used")
        if tool != want["tool"]:
            deny(f"this run may call only {want['tool']}")
        if used.exists():
            deny("the pressed action was already done once")
        used.write_text("1")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                 "permissionDecisionReason": "the owner's pressed action",
                                                 "updatedInput": want["input"]}}))
        sys.exit(0)
    if tool == "Read":
        if not readable(inp.get("file_path") or ""):
            deny("file outside the brain's readable folders")
    elif tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        if not writable(inp.get("file_path") or inp.get("notebook_path") or ""):
            deny("runs write only the brain's data folders")
    elif tool in ("Grep", "Glob", "LS"):
        base = real(inp.get("path") or ROOT)
        reach = glob_prefix(os.path.join(base, inp.get("pattern") or "")) if tool == "Glob" else base
        if not readable(base) or not readable(reach) or (inside(base, [HOME]) and not inside(base, READ_ROOTS)):
            deny("search outside the brain's readable folders")
    elif tool == "Bash":
        check_bash(inp.get("command") or "")
    elif tool == "WebFetch":
        why = risky_url(inp.get("url"))
        if why:
            deny(why)
    elif tool.startswith("mcp__"):
        if tool not in read_tools():
            deny("only the read tools registered in config/connectors.json; connector writes happen in the executor after the owner's press")


def post(ev):
    out = os.environ.get("JB_GUARD_RESULT")
    if out and os.environ.get("JB_GUARD_EXPECT"):
        Path(out).write_text(json.dumps(ev.get("tool_response"), ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        ev = json.load(sys.stdin)
    except json.JSONDecodeError:
        deny("unreadable hook input")
    (post if ev.get("hook_event_name") == "PostToolUse" else pre)(ev)
