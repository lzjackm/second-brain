#!/bin/zsh
# Shared headless runner. Usage: _claude.sh <name> <prompt-file> [extra claude args...]
# Telegram and Vercel plugins are disabled: a second Telegram instance steals the bot's
# polling from the interactive session, and Vercel hooks add noise.
# Every run appends one line to log/usage.jsonl (cost, tokens, duration, model) and stamps
# what it writes with made_by, so Learning can compare cost and quality per job and model.
set -euo pipefail
umask 077   # traces, logs and state hold Slack, Drive and memory content: readable by the owner only
ROOT="${0:A:h:h}"
NAME="$1"; PROMPT_FILE="$2"; shift 2
cd "$ROOT"
LOCK="$ROOT/state/$NAME.lock"
# A lock whose owner is gone (crash, sleep, kill) is stale: take it over instead of skipping forever.
if ! mkdir "$LOCK" 2>/dev/null; then
  OWNER=$(cat "$LOCK/pid" 2>/dev/null || echo "")
  if [[ -n "$OWNER" ]] && kill -0 "$OWNER" 2>/dev/null; then echo "$NAME already running"; exit 0; fi
  echo "$NAME: clearing stale lock" >&2
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
TS=$(TZ=America/New_York date +%Y%m%d-%H%M)
LOG="$ROOT/logs/$NAME-$TS.log"
echo "$LOG" > "$ROOT/state/$NAME.current"   # the live trace, for the Talk panel and run views
RUN_ID="$NAME-$TS-$$"
JOB="$NAME"; for a in "$ROOT"/leads/*.md(N); do JOB="${JOB%%-${a:t:r}*}"; done; JOB="${JOB%-20*}"   # lead-<area> -> lead, agent-<item> -> agent
[[ "$NAME" == agent-* ]] && JOB="agent"; [[ "$NAME" == execcall-* ]] && JOB="execcall"; [[ "$NAME" == execedit-* ]] && JOB="execedit"; [[ "$NAME" == execledger-* ]] && JOB="execledger"; [[ "$NAME" == chat-* ]] && JOB="chat"; [[ "$NAME" == learn-* ]] && JOB="learn"; [[ "$NAME" == architect-verify-* ]] && JOB="architect-verify"; [[ "$NAME" == architect-* && "$NAME" != architect-verify-* ]] && JOB="architect"
MODEL=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],"") or "")' "$ROOT/config/models.json" "$JOB" 2>/dev/null || true)
MODEL_ARGS=(); [[ -n "$MODEL" ]] && MODEL_ARGS=(--model "$MODEL")
# Context budget (docs/context.md): skills off for every run; built-in tools restricted for jobs that need no connectors.
TOOLS=$(python3 -I -c 'import json,sys; j=json.load(open(sys.argv[1]))["jobs"].get(sys.argv[2],{}); print(",".join(j.get("tools",[])))' "$ROOT/config/context.json" "$JOB" 2>/dev/null || true)
# Restricting built-in tools removes ToolSearch, which is what defers connector tool definitions; so a restricted
# job must also drop connectors (--strict-mcp-config) or every connector's tools load in full on every turn (~185k on Opus).
CTX_ARGS=(--disable-slash-commands); [[ -n "$TOOLS" ]] && CTX_ARGS+=(--tools "$TOOLS" --strict-mcp-config)
# bin/tool_guard.py checks every tool call of every run (secrets, network, connector writes; the executor's one pressed call).
export BRAIN_PRIVATE=$(/opt/homebrew/bin/python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import press; print(press.PRIVATE)' "$ROOT/bin")
GUARD="/opt/homebrew/bin/python3 -I $ROOT/bin/tool_guard.py"
SETTINGS=$(/opt/homebrew/bin/python3 -I -c 'import json,sys; g={"matcher": "*", "hooks": [{"type": "command", "command": sys.argv[1]}]}; print(json.dumps({"enabledPlugins": {"telegram@claude-plugins-official": False, "vercel@claude-plugins-official": False}, "hooks": {"PreToolUse": [g], "PostToolUse": [g]}}))' "$GUARD")
# Connector jobs: right after the Mac wakes, the claude.ai connectors (Slack, Drive, Linear) can be missing for minutes,
# and a run without them reads nothing and reports "new 0" (Nov 13 9:05 lead). Wait for the required ones to connect, up to 10 min;
# if they never do, record a failed run and tell the owner instead of a quiet empty one. After the run, the trace is checked too
# (connectors can still be missing inside the session): such a run is marked failed and retried once 3 min later.
alert() {  # title, body: a Mac notification the owner sees
  local tn=$(command -v terminal-notifier || true)
  if [[ -n "$tn" ]]; then "$tn" -title "$1" -message "$2" -open "http://127.0.0.1:7878/#ops" -sound default >/dev/null 2>&1 || true
  else osascript -e "display notification \"$2\" with title \"$1\" sound name \"default\"" >/dev/null 2>&1 || true; fi
  printf '{"ts": "%s", "kind": "run_failed", "run": "%s", "note": "%s"}\n' "$(date +%Y-%m-%dT%H:%M:%S%z | sed 's/\(..\)$/:\1/')" "$RUN_ID" "$2" >> "$ROOT/log/notify.jsonl"
}
NEED_CONNECTORS=0; [[ -z "$TOOLS" && "${JB_NO_CONNECTORS:-}" != 1 ]] && NEED_CONNECTORS=1
if (( NEED_CONNECTORS )); then
  for try in {1..10}; do
    REQ=(${(f)"$(python3 -I "$ROOT/bin/connectors.py" required 2>/dev/null)"})   # config/connectors.json "required"
    LIST=$(claude mcp list 2>/dev/null)
    MISSING=(); for c in $REQ; do print -r -- "$LIST" | grep -qE "^(claude.ai )?$c:.*Connected" || MISSING+=($c); done
    (( ${#MISSING} == 0 )) && break
    if (( try == 10 )); then
      echo "Connectors not loaded: ${(j:, :)MISSING} wasn't connected after 10 min, so this run was skipped." > "$LOG"
      cp "$LOG" "$LOG.err"
      printf '{"ts": "%s", "run": "%s", "name": "%s", "job": "%s", "cost_usd": 0, "error": true, "error_short": "connectors not loaded"}\n' \
        "$(date +%Y-%m-%dT%H:%M:%S%z | sed 's/\(..\)$/:\1/')" "$RUN_ID" "$NAME" "$JOB" >> "$ROOT/log/usage.jsonl"
      alert "$NAME skipped" "${(j:, :)MISSING} isn't connected. Check claude.ai connectors."
      cat "$LOG"; exit 0
    fi
    sleep 60
  done
fi
# Owner placeholders ({{OWNER}}, {{OWNER_FIRST}}, {{BRAIN_NAME}}) come from config/brain.json, so prompts carry no name.
PROMPT_TEXT="$(python3 -I - "$ROOT" "$PROMPT_FILE" <<'PY'
import json, sys
root, src = sys.argv[1:3]
try:
    c = json.load(open(f"{root}/config/brain.json"))
except Exception:
    c = {}
name = c.get("owner_name") or "the owner"
t = open(src).read()
for k, v in {"{{OWNER}}": name, "{{OWNER_FIRST}}": c.get("owner_first") or name.split()[0], "{{BRAIN_NAME}}": c.get("brain_name") or "Second Brain", "{{OWNER_TOKEN}}": c.get("owner_token") or "me",
            "{{LEDGER_NAME}}": (c.get("modules") or {}).get("ledger", {}).get("name") or "the ledger",
            "{{LEDGER_REPO}}": "/".join(((c.get("modules") or {}).get("ledger", {}).get("url") or "").rstrip("/").split("/")[-2:]),
            "{{LEDGER_PATH}}": (c.get("modules") or {}).get("ledger", {}).get("path") or "",
            "{{MEMORY_DIR}}": __import__("os").path.expanduser("~/.claude/projects/") + __import__("os").path.expanduser("~").replace("/", "-").replace(".", "-") + "/memory"}.items():
    t = t.replace(k, v)
sys.stdout.write(t)
PY
)"
PROMPT="$PROMPT_TEXT

Attribution: on every queue item, step, idea or report you create or rewrite, set \"made_by\": {\"run\": \"$RUN_ID\", \"job\": \"$JOB\"}."
# Hard time limit per job: a run stuck on a dead network call (common after sleep) is killed, not left holding its lock.
case "$JOB" in
  lead|scout|agent|architect) LIMIT=40 ;;
  architect-verify) LIMIT=25 ;;
  sync|execute|distill|specialist-*) LIMIT=20 ;;
  *) LIMIT=12 ;;
esac
# Agent runs keep their session (JB_KEEP_SESSION) so the owner can talk to them afterwards; everything else is one-shot.
PERSIST=(--no-session-persistence); [[ -n "${JB_KEEP_SESSION:-}" ]] && PERSIST=()
claude -p "$PROMPT" \
  --settings "$SETTINGS" \
  --setting-sources user \
  --permission-mode dontAsk \
  "${PERSIST[@]}" \
  --output-format stream-json --verbose \
  "${CTX_ARGS[@]}" "${MODEL_ARGS[@]}" "$@" > "$LOG.trace.jsonl" 2> "$LOG.err" < /dev/null &
CPID=$!
# Hold off idle sleep while the run lives: distill kept timing out because the Mac slept mid-run and the sleep counted against the deadline.
caffeinate -i -w $CPID &
# Wall-clock deadline, checked every 30s: a plain `sleep N` pauses while the Mac sleeps, so it never fired on runs that started in a dark wake.
DEADLINE=$(( $(date +%s) + LIMIT * 60 ))
( while kill -0 $CPID 2>/dev/null; do
    if (( $(date +%s) >= DEADLINE )); then echo "timed out after ${LIMIT} min" >> "$LOG.err"; kill $CPID; sleep 5; kill -9 $CPID 2>/dev/null; break; fi
    sleep 30
  done ) &
WATCH=$!
wait $CPID || true
kill $WATCH 2>/dev/null || true
# Keep the full trace (every tool call and result size) for diagnosing cost; the last event is the result.
grep '"type":"result"' "$LOG.trace.jsonl" | tail -1 > "$LOG.json" || true
python3 -I - "$LOG.json" "$LOG" "$ROOT/log/usage.jsonl" "$RUN_ID" "$NAME" "$JOB" "${JB_UNITS:-}" "$NEED_CONNECTORS" <<'PY'
import json, sys, datetime, re
src, log, usage, run, name, job, units, need = sys.argv[1:9]
try:
    d = json.load(open(src))
except Exception as e:
    err = open(src.replace(".log.json", ".log.err")).read()[-300:] if __import__("os").path.exists(src.replace(".log.json", ".log.err")) else ""
    d = {"is_error": True, "result": ("TIMED OUT. " if "timed out" in err else "") + f"no JSON result ({e})"}
open(log, "w").write((d.get("result") or "") + "\n")
u = d.get("usage") or {}
models = d.get("modelUsage") or {}
rec = {
    "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "run": run, "name": name, "job": job,
    "models": {m: round(v.get("costUSD", 0), 4) for m, v in models.items()},
    "model": max(models, key=lambda m: models[m].get("costUSD", 0)) if models else None,
    "cost_usd": round(d.get("total_cost_usd") or 0, 4),
    "input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
    "cache_read": u.get("cache_read_input_tokens", 0), "cache_write": u.get("cache_creation_input_tokens", 0),
    "web_searches": (u.get("server_tool_use") or {}).get("web_search_requests", 0),
    "duration_ms": d.get("duration_ms"), "turns": d.get("num_turns"), "error": bool(d.get("is_error")),
    "units": int(units) if units.isdigit() else None,
}
# Tool calls and how much each returned, from the trace, so expensive reads are visible per run.
try:
    calls = {}
    for line in open(src.replace(".log.json", ".log.trace.jsonl")):
        ev = json.loads(line)
        for c in (ev.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                calls[c["id"]] = {"tool": c["name"], "arg": str(c.get("input", {}).get("file_path") or c.get("input", {}).get("pattern") or c.get("input", {}).get("query") or "")[:80]}
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                body = c.get("content")
                calls[c["tool_use_id"]]["chars"] = len(json.dumps(body)) if not isinstance(body, str) else len(body)
    rec["tools"] = sorted(calls.values(), key=lambda x: -x.get("chars", 0))[:12]
except Exception:
    pass
# A connector run whose session never got its connectors: a search for one found no connector tool, and none was ever called.
if need == "1":
    try:
        asked, missing, used = {}, False, False
        for line in open(src.replace(".log.json", ".log.trace.jsonl")):
            ev = json.loads(line)
            m = ev.get("message")
            if not isinstance(m, dict):
                continue
            for c in m.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use" and str(c.get("name", "")).startswith("mcp__claude_ai_"):
                    used = True
                if c.get("type") == "tool_use" and c.get("name") == "ToolSearch":
                    asked[c["id"]] = str((c.get("input") or {}).get("query", ""))
                if c.get("type") == "tool_result" and c.get("tool_use_id") in asked \
                        and re.search(r"slack|drive|linear", asked[c["tool_use_id"]], re.I) \
                        and "mcp__" not in json.dumps(c.get("content")):
                    missing = True
        if missing and not used:  # searched for a connector, found none, and never called one
            rec["error"], rec["error_short"] = True, "connectors missing in session"
            open(log + ".noconn", "w").write("1")
    except Exception:
        pass
with open(usage, "a") as fh:
    fh.write(json.dumps(rec) + "\n")
PY
if [[ -f "$LOG.noconn" ]]; then
  rm -f "$LOG.noconn"
  if [[ -z "${JB_RETRY:-}" ]]; then
    echo "$NAME: connectors missing in session, retrying in 3 min" >&2
    rm -rf "$LOCK"; trap - EXIT; sleep 180
    JB_RETRY=1 exec "$0" "$NAME" "$PROMPT_FILE" "$@"
  fi
  alert "$NAME failed twice" "Slack, Drive or Linear tools didn't load in the run. Check claude.ai connectors."
fi
tail -1 "$LOG"
