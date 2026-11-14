#!/bin/zsh
# Runs queued steps the owner pressed. Plain code (bin/execute.py): each step needs a matching press (bin/press.py).
exec /opt/homebrew/bin/python3 -I "${0:A:h}/execute.py" "$@"
