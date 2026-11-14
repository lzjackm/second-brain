#!/bin/zsh
# Fast revision pass for one area. The app starts it on Revise and on Save and redraft.
exec "${0:A:h}/run-lead.sh" "$1" revise
