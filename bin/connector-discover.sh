#!/bin/zsh
# Find a newly added connector's read-only tools and record them in config/connectors.json (write tools are never
# allowed to runs). The app starts it when the owner adds a connector, or retries it after they connect one.
# Usage: bin/connector-discover.sh <server>   (e.g. claude_ai_Notion)
set -euo pipefail
ROOT="${0:A:h:h}"
SERVER="$1"
[[ "$SERVER" =~ '^[A-Za-z][A-Za-z0-9_.-]{1,79}$' ]] || { echo "bad connector" >&2; exit 2; }
PY=/opt/homebrew/bin/python3
TMP="$ROOT/state/prompt-connector-$SERVER.md"
sed "s|{{SERVER}}|$SERVER|g" "$ROOT/prompts/connector-discover.md" > "$TMP"
JB_NO_CONNECTORS=1 "$ROOT/bin/_claude.sh" "connector-$SERVER" "$TMP" --model haiku --allowedTools "ToolSearch" --disallowedTools "Bash" "Write" "Edit" || true
LOG=$(ls -t "$ROOT"/logs/connector-$SERVER-*.log(N) | head -1)
RESULT=$($PY -I - "$LOG" <<'PY'
import json, re, sys
text = open(sys.argv[1]).read() if sys.argv[1] else ""
m = re.search(r"\{.*\}", text, re.S)
try:
    d = json.loads(m.group(0)) if m else {"error": "no answer"}
except json.JSONDecodeError:
    d = {"error": "unreadable answer"}
safe = re.compile(r"^(get|list|search|read|query|fetch|find|describe|view|whoami|lookup|retrieve)", re.I)
d["read"] = [t for t in d.get("read") or [] if safe.match(t) and not re.search(r"(create|update|delete|send|post|write|upload|set|add|remove|archive|merge)", t, re.I)]
if not d["read"] and not d.get("error"):
    d["error"] = "no read-only tools found"
print(json.dumps(d))
PY
)
$PY -I "$ROOT/bin/connectors.py" set-tools "$SERVER" "$RESULT"
echo "$SERVER: $RESULT"
