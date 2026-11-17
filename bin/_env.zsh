# Shared environment for every script and schedule. launchd starts jobs with a bare PATH, so set one that finds
# Homebrew and Claude Code wherever it was installed (the native installer uses ~/.local/bin), and resolve `claude`
# once: CLAUDE is its full path, empty when it isn't installed.
export PATH="$HOME/.local/bin:$HOME/.claude/local:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
CLAUDE=$(command -v claude 2>/dev/null || true)
