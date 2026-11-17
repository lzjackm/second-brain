#!/bin/zsh
# Fast revision pass for one area. The app starts it on Revise and on Save and redraft.
source "${0:A:h}/_env.zsh"   # PATH for Homebrew and Claude Code: the app and launchd start scripts with a bare one
exec "${0:A:h}/run-lead.sh" "$1" revise
