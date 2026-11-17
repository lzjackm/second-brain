#!/bin/zsh
# Snapshot the Solutions Architect's sources (modules.architect.sources in config/brain.json). See bin/prefetch_sa.py.
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
exec /opt/homebrew/bin/python3 -I "${0:A:h}/prefetch_sa.py" "$@"
