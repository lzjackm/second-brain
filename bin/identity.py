"""Who owns this brain, from config/brain.json (written by onboarding). Every script and the app read identity here,
so no name, email or login is hard-coded anywhere else."""
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
_f = ROOT / "config" / "brain.json"
CFG = json.loads(_f.read_text()) if _f.exists() else {}

BRAIN_NAME = CFG.get("brain_name") or "Second Brain"
SLUG = CFG.get("slug") or "second-brain"          # Keychain service and notification names: "<slug>-figma"
OWNER = CFG.get("owner_token") or "me"                 # marks the owner's steps, chat messages and history entries
OWNER_NAME = CFG.get("owner_name") or ""
OWNER_FIRST = CFG.get("owner_first") or (OWNER_NAME.split()[0] if OWNER_NAME else "the owner")
# Every way a run may write the owner: the token, "me", aliases, the full and the first name. Runs echo the first name
# the prompts use; missing it made the template's app treat the owner's own steps as someone else's (Nov 17).
OWNER_NAMES = {OWNER, "me", *(a.strip().lower() for a in CFG.get("owner_aliases") or []),
               *([OWNER_NAME.lower()] if OWNER_NAME else []), *([OWNER_FIRST.lower()] if CFG.get("owner_first") or OWNER_NAME else [])}
OWNER_EMAILS = {e.lower() for e in CFG.get("owner_emails") or []}
GITHUB_LOGINS = set(CFG.get("github_logins") or [])
TZ = ZoneInfo(CFG.get("timezone") or "America/New_York")
WORK_HOURS = tuple(CFG.get("work_hours") or (9, 19))


def is_owner(owner):
    """A step or item owned by the brain's owner. An empty owner counts as the owner (the app shows it as theirs)."""
    return (owner or OWNER).strip().lower() in OWNER_NAMES


def public():
    """What the app's page needs to know (no emails)."""
    return {"brain_name": BRAIN_NAME, "owner_token": OWNER, "owner_name": OWNER_NAME, "owner_first": OWNER_FIRST,
            "owner_initials": CFG.get("owner_initials") or "".join(w[0] for w in OWNER_NAME.split()[:2]).upper() or "ME",
            "owner_names": sorted(OWNER_NAMES), "timezone": CFG.get("timezone") or "America/New_York",
            "modules": CFG.get("modules") or {}, "repo_aliases": CFG.get("repo_aliases") or {}}


# Optional decision-ledger repo (modules.ledger: path, url, name, area). Empty strings when not configured.
LEDGER = (CFG.get("modules") or {}).get("ledger") or {}
LEDGER_PATH = LEDGER.get("path") or ""                       # "~/code/decisions"
LEDGER_URL = (LEDGER.get("url") or "").rstrip("/")             # "https://github.com/org/decisions"
LEDGER_REPO = "/".join(LEDGER_URL.split("/")[-2:]) if LEDGER_URL else ""   # "org/decisions", for gh
LEDGER_NAME = LEDGER.get("name") or (LEDGER_REPO.split("/")[-1] if LEDGER_REPO else "")
LEDGER_AREA = LEDGER.get("area") or CFG.get("default_area") or "main"
