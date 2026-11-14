# Tools a research agent may use, shared by agent.sh (first run) and agent-talk.sh (the owner's replies).
# Read access everywhere it needs; writes only to its working folder and the item file.
# Shell is an explicit list of read and analysis commands: no sends, pushes, merges or deletes. Python runs only in
# bin/sandbox.sh (no home folder, no Keychain) and git only through bin/gitread.sh (read subcommands only).
R="${ROOT/#$HOME/~}"   # this folder as ~/..., for permission rules
ALLOWED=(
  "Read" "Glob" "Grep" "WebSearch" "WebFetch"
  "Edit($R/agents/**)" "Edit($R/queue/items/**)"
  "Bash(bin/sandbox.sh python3:*)" "Bash($ROOT/bin/sandbox.sh python3:*)" "Bash(python3 bin/figma_read.py:*)" "Bash(jq:*)"
  "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Bash(tail:*)" "Bash(wc:*)" "Bash(date:*)" "Bash(mkdir:*)"
  "Bash(bin/gitread.sh:*)" "Bash($ROOT/bin/gitread.sh:*)" "Bash(gh pr view:*)" "Bash(gh pr list:*)"
  "Bash(aws s3 ls:*)" "Bash(aws sts get-caller-identity:*)"
  ${(f)"$(/opt/homebrew/bin/python3 -I "$ROOT/bin/connectors.py" tools)"}
)
