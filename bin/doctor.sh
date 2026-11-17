#!/bin/zsh
# Checks this brain can run the way the schedules run it: launchd's bare environment, not your Terminal's.
# Run it after setup and whenever runs stop. Prints one line per check; exits 1 if anything blocks runs.
set -u
ROOT="${0:A:h:h}"
if [[ -z "${DOCTOR_INNER:-}" ]]; then   # re-run in a bare environment, the way launchd starts jobs
  exec env -i HOME="$HOME" USER="${USER:-}" PATH=/usr/bin:/bin DOCTOR_INNER=1 /bin/zsh "$0" "$@"
fi
source "$ROOT/bin/_env.zsh"
bad=0
ok()   { print -r -- "ok    $1"; }
fail() { print -r -- "FIX   $1"; bad=1; }
warn() { print -r -- "note  $1"; }
[[ -x /opt/homebrew/bin/python3 ]] && ok "Python: /opt/homebrew/bin/python3" || fail "Python: install with \`brew install python\`"
if [[ -z "$CLAUDE" ]]; then
  fail "Claude Code: not found on the PATH runs use ($PATH). Install it from claude.com/claude-code"
else
  ok "Claude Code: $CLAUDE ($("$CLAUDE" --version 2>/dev/null | head -1))"
  if "$CLAUDE" auth status --json 2>/dev/null | grep -q '"loggedIn": *true'; then
    ok "Signed in: $("$CLAUDE" auth status --text 2>/dev/null | grep -iE 'email|plan|organization|method' | head -3 | tr '\n' ' ')"
  else
    fail "Signed in: no. Run \`claude auth login\` in Terminal"
  fi
fi
[[ -f "$ROOT/config/brain.json" ]] && ok "Config: config/brain.json" || fail "Config: copy config/brain.example.json to config/brain.json (/onboard does this)"
command -v gh >/dev/null && { gh auth status >/dev/null 2>&1 && ok "GitHub CLI: signed in" || warn "GitHub CLI: installed but not signed in (\`gh auth login\`); PR features need it"; } || warn "GitHub CLI: not installed; PR features need it (\`brew install gh\`)"
if [[ -n "$CLAUDE" ]]; then
  REQ=(${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" required 2>/dev/null)"})
  LIST=$("$CLAUDE" mcp list 2>/dev/null)
  for c in $REQ; do print -r -- "$LIST" | grep -qE "^(claude.ai )?$c:.*Connected" && ok "Connector: $c connected" || fail "Connector: $c isn't connected (connect it at claude.ai, Settings, Connectors)"; done
  (( ${#REQ} )) || warn "Connectors: none required yet; add them on the Connectors page"
fi
(( bad )) && print "\nRuns will fail until the FIX lines are done." || print "\nReady: scheduled runs will work."
exit $bad
