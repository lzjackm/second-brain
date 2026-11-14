#!/bin/zsh
# Read-only git for brain runs: a fixed set of read subcommands, with hooks, fsmonitor and external diff tools off,
# and no -c or output options, so a run cannot make git run a program or write a file.
# Usage: bin/gitread.sh <repo> <log|show|diff|grep|ls-files|ls-tree|blame|status|rev-parse|branch> [args...]
set -euo pipefail
ROOT="${0:A:h:h}"
REPO="${1:A}"; SUB="$2"; shift 2
# Only real clones under ~/Projects (or this brain itself): a repo a run created could carry config that runs programs.
TOP=$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null) || { echo "gitread: not a git repo" >&2; exit 2; }
[[ "$TOP" == "$ROOT" || ( "$TOP" == "$HOME/Projects/"* && "$TOP" != "$ROOT/"* ) ]] || { echo "gitread: repo not allowed" >&2; exit 2; }
[[ "$SUB" =~ ^(log|show|diff|grep|ls-files|ls-tree|blame|status|rev-parse|branch)$ ]] || { echo "gitread: $SUB not allowed" >&2; exit 2; }
for a in "$@"; do
  [[ "$a" =~ ^(-c|--config|--output|--ext-diff|--textconv|--exec|--upload-pack|-o|--open-files-in-pager|-O)(=|$) || "$a" == --output=* || "$a" == -O* ]] && { echo "gitread: $a not allowed" >&2; exit 2; }
done
[[ "$SUB" == branch && " $* " =~ " -(d|D|m|M|c|C|f)" ]] && { echo "gitread: branch changes not allowed" >&2; exit 2; }
NOTC=(); [[ "$SUB" =~ ^(log|show|diff|grep|blame)$ ]] && NOTC=(--no-textconv)
[[ "$SUB" =~ ^(log|show|diff)$ ]] && NOTC+=(--no-ext-diff)
exec git -c core.fsmonitor=false -c core.hooksPath=/dev/null -c diff.external= -c core.pager=cat -c log.showSignature=false \
  -c gpg.program=false -c core.sshCommand=false -c protocol.allow=never -C "$TOP" --no-pager "$SUB" "${NOTC[@]}" "$@"
