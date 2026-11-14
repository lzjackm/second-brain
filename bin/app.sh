#!/bin/zsh
ROOT="${0:A:h:h}"
exec /opt/homebrew/bin/python3 "$ROOT/app/server.py" "$@"
