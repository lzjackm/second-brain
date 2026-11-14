# Shared allowlist for leads, the scout and specialists: read-only sources, writes only to this repo's runtime folders.
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
ALLOWED=(
  "Read" "Glob" "Grep" "WebSearch"   # no WebFetch: these runs read Slack, and a fetch could carry its content out
  "Edit($R/queue/**)"
  "Edit($R/synopsis/**)"
  "Edit($R/state/**)"
  "Bash(date:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(jq:*)"
  ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"}
)
