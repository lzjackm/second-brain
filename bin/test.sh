#!/bin/zsh
# Regression tests for the brain's code checks (tests/). Run before every commit.
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
cd "${0:A:h:h}" && exec /opt/homebrew/bin/python3 -I -m unittest discover -s tests -q
