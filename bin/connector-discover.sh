#!/bin/zsh
# Find a newly added connector's read-only tools and record them in config/connectors.json (write tools are never
# allowed to runs). The app starts it when the owner adds a connector, or retries it after they connect one.
# Usage: bin/connector-discover.sh <server>   (e.g. claude_ai_Notion)
set -euo pipefail
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"
SERVER="$1"
[[ "$SERVER" =~ '^[A-Za-z][A-Za-z0-9_.-]{1,79}$' ]] || { echo "bad connector" >&2; exit 2; }
PY=/opt/homebrew/bin/python3
TMP="$ROOT/state/prompt-connector-$SERVER.md"
sed "s|{{SERVER}}|$SERVER|g" "$ROOT/prompts/connector-discover.md" > "$TMP"
JB_NO_CONNECTORS=1 "$ROOT/bin/_claude.sh" "connector-$SERVER" "$TMP" --model haiku --allowedTools "ToolSearch" --disallowedTools "Bash" "Write" "Edit" || true
LOG=$(ls -t "$ROOT"/logs/connector-$SERVER-*.log(N) | head -1)
RESULT=$($PY -I - "$LOG" "$SERVER" "$ROOT/bin" <<'PY'
import json, re, sys
log, server, binp = sys.argv[1:4]
sys.path.insert(0, binp)
import connectors
text = open(log).read() if log else ""
m = re.search(r"\{.*\}", text, re.S)
try:
    d = json.loads(m.group(0)) if m else {"error": "no answer"}
except json.JSONDecodeError:
    d = {"error": "unreadable answer"}
# The tool names Claude Code really has for this connector: the tool search results in the run's trace.
trace = open(log + ".trace.jsonl").read() if log else ""
real = set(re.findall(r'"tool_reference",\s*"tool_name":\s*"(mcp__[^"]+)"', trace))
if not real:
    d = {"error": d.get("error") or "the connector's tools didn't load; connect it, then retry"}
else:
    d["read"], d["write"] = connectors.classify(server, real, d.get("read") if isinstance(d.get("read"), list) and d.get("read") else None)
    if not d["read"]:
        d["read"], _ = connectors.classify(server, real)       # the model's list matched nothing real: trust the names
    if not d["read"] and not d.get("error"):
        d["error"] = "no read-only tools found"
print(json.dumps(d))
PY
)
$PY -I "$ROOT/bin/connectors.py" set-tools "$SERVER" "$RESULT"
echo "$SERVER: $RESULT"
