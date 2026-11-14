#!/bin/zsh
# Test read: a dry run of one connector over the last 48 hours for one area, so the owner sees what it would bring in
# before it goes live. Writes only state/connector-test-<server>.json; nothing reaches the queue.
# Usage: bin/connector-test.sh <server> <area>
set -euo pipefail
ROOT="${0:A:h:h}"
SERVER="$1"; AREA="$2"
[[ "$SERVER" =~ '^[A-Za-z][A-Za-z0-9_.-]{1,79}$' && "$AREA" =~ '^[a-z0-9][a-z0-9-]*$' && -f "$ROOT/leads/$AREA.md" ]] || { echo "bad connector or area" >&2; exit 2; }
PY=/opt/homebrew/bin/python3
OUT="$ROOT/state/connector-test-$SERVER.json"
TMP="$ROOT/state/prompt-conntest-$SERVER.md"
NOW=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z)
echo "{\"status\": \"running\", \"area\": \"$AREA\", \"started\": \"$NOW\"}" > "$OUT"
TOOLS=(${(f)"$($PY -I - "$ROOT" "$SERVER" "$AREA" "$NOW" "$TMP" <<'PY'
import json, sys
root, server, area, now, tmp = sys.argv[1:6]
c = next(x for x in json.load(open(f"{root}/config/connectors.json"))["connectors"] if x["server"] == server)
t = open(f"{root}/prompts/connector-test.md").read()
for k, v in {"{{NAME}}": c["name"], "{{AREA}}": area, "{{NOW}}": now, "{{USE}}": c.get("use") or "anything relevant"}.items():
    t = t.replace(k, v)
open(tmp, "w").write(t)
print("\n".join(f"mcp__{server}__{x}" for x in c.get("read_tools") or []))
PY
)"})
"$ROOT/bin/_claude.sh" "conntest-$SERVER" "$TMP" --allowedTools ToolSearch Read Grep Glob "${TOOLS[@]}" --disallowedTools Bash Write Edit WebFetch || true
LOG=$(ls -t "$ROOT"/logs/conntest-$SERVER-*.log(N) | head -1)
$PY -I - "$LOG" "$OUT" "$AREA" "$NOW" <<'PY'
import json, re, sys
log, out, area, started = sys.argv[1:5]
text = open(log).read() if log else ""
m = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S) or re.findall(r"(\{.*\})", text, re.S)
try:
    d = json.loads(m[-1]) if m else {"read": "The test run gave no answer.", "items": []}
except json.JSONDecodeError:
    d = {"read": "The test run's answer was unreadable.", "items": []}
d.update(status="done", area=area, started=started, items=(d.get("items") or [])[:5])
open(out, "w").write(json.dumps(d, ensure_ascii=False, indent=1))
PY
