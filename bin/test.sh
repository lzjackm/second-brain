#!/bin/zsh
# Regression tests for the brain's code checks (tests/). Run before every commit.
cd "${0:A:h:h}" && exec /opt/homebrew/bin/python3 -I -m unittest discover -s tests -q
