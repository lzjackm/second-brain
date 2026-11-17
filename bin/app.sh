#!/bin/zsh
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
ROOT="${0:A:h:h}"
exec /opt/homebrew/bin/python3 "$ROOT/app/server.py" "$@"
