#!/bin/zsh
# Snapshot the Solutions Architect's sources (modules.architect.sources in config/brain.json). See bin/prefetch_sa.py.
exec /opt/homebrew/bin/python3 -I "${0:A:h}/prefetch_sa.py" "$@"
