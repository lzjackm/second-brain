#!/bin/zsh
# Runs python3 for a research or meeting run inside a macOS sandbox: it may read only this brain folder, ~/Projects
# (minus .env, key files and git credentials), the system and Python's own files, and write only agents/, state/ and temp folders. Your home folder (SSH and cloud
# keys, Claude memory, other repos) and the Keychain are out of reach, so code a run writes from untrusted text
# cannot read secrets, and has no network, so it cannot send anything anywhere. Usage: bin/sandbox.sh python3 <args...>
set -euo pipefail
ROOT="${0:A:h:h}"
[[ "${1:-}" == python3 ]] || { echo "sandbox.sh runs python3 only" >&2; exit 2; }
shift
PY=/opt/homebrew/bin/python3
USERSITE=$($PY -c 'import site; print(site.getusersitepackages())')
PROFILE="(version 1)
(allow default)
(deny file-read* (subpath \"$HOME\"))
(allow file-read* (subpath \"$ROOT\") (subpath \"$HOME/Projects\") (subpath \"$USERSITE\") (subpath \"$HOME/Library/Caches\") (literal \"$HOME\"))
(deny file-read* (subpath \"$ROOT/config/slack\") (regex #\"/\\.env\") (regex #\"\\.(pem|key|p12|pfx)$\") (regex #\"/\\.git/config$\") (regex #\"/\\.git-credentials$\"))
(deny file-write*)
(allow file-write* (subpath \"$ROOT/agents\") (subpath \"$ROOT/state\") (subpath \"/private/tmp\") (subpath \"/private/var/folders\") (literal \"/dev/null\") (literal \"/dev/stdout\") (literal \"/dev/stderr\"))
(deny process-exec (literal \"/usr/bin/security\") (literal \"/usr/bin/curl\") (literal \"/usr/bin/ssh\") (literal \"/usr/bin/osascript\"))
(deny network*)
(allow network* (local unix))
(deny mach-lookup (global-name \"com.apple.SecurityServer\") (global-name \"com.apple.securityd.xpc\"))"
exec /usr/bin/sandbox-exec -p "$PROFILE" "$PY" "$@"
