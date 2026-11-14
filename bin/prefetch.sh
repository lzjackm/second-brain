#!/bin/zsh
# Deterministic work before an area's lead or pipeline run, so the run needs no shell access to other repos:
# the area's own bin/prefetch-<area>.sh if there is one, the decision ledger if this is its area, then the
# writing-limit enforcer (bin/brevity.py) and duplicate merge (bin/dedupe.py) for the area's items.
# Usage: bin/prefetch.sh <area>
set -euo pipefail
ROOT="${0:A:h:h}"; AREA="$1"; PY=/opt/homebrew/bin/python3
[[ -x "$ROOT/bin/prefetch-$AREA.sh" ]] && { "$ROOT/bin/prefetch-$AREA.sh" || echo "prefetch-$AREA failed" >&2; }
LEDGER_AREA=$($PY -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import identity as i; print(i.LEDGER_AREA if i.LEDGER_PATH else "")' "$ROOT/bin")
[[ "$AREA" == "$LEDGER_AREA" ]] && { "$ROOT/bin/prefetch-ledger.sh" || echo "prefetch-ledger failed" >&2; }
$PY -I "$ROOT/bin/brevity.py" "$AREA" > /dev/null || echo "brevity failed" >&2
$PY -I "$ROOT/bin/dedupe.py" "$AREA" || true
