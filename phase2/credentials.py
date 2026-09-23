"""IBM Quantum credentials: where they come from, and what may be said aloud.

Credentials reach the code through environment variables and nothing else. As a
convenience, a git-ignored `.env` in the project root is read into the
environment first - `.env` is listed in `.gitignore`, so it never reaches a
commit.

Two rules this module exists to enforce:

  * a real environment variable always wins over `.env`, so an operator can
    override a stale file without editing it;
  * a secret value is never returned, printed, or logged. `credential_status`
    reports only whether a variable is set and how many characters it holds,
    which is enough to debug a bad paste and useless to anyone reading a log.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

#: The variables the IBM backend understands. Only the token is required.
TOKEN_VAR = "IBM_QUANTUM_TOKEN"
CREDENTIAL_VARS = (
    (TOKEN_VAR, True, "API key from the IBM Quantum dashboard"),
    ("IBM_QUANTUM_INSTANCE", False, "CRN / instance identifier"),
    ("IBM_QUANTUM_CHANNEL", False, "default: ibm_quantum_platform"),
    ("IBM_QUANTUM_BACKEND", False, "default: least busy operational device"),
)

#: Variables whose value must never be shown, not even partially.
SECRET_VARS = frozenset({TOKEN_VAR})


def parse_env_file(text: str) -> dict:
    """Parse `.env` text into a mapping. Values are not interpreted further."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(path=None) -> list:
    """Load `.env` into `os.environ` without overriding what is already set.

    Returns the names of the variables that were loaded - names only, never
    values. Missing or unreadable files are not an error: the environment on its
    own is a perfectly good way to supply credentials.
    """
    env_path = Path(path) if path else ENV_FILE
    try:
        text = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    loaded = []
    for key, value in parse_env_file(text).items():
        if os.environ.get(key):
            continue                    # a real environment variable wins
        os.environ[key] = value
        loaded.append(key)
    return loaded


def describe_value(name: str, value: str) -> str:
    """A safe description of a configured value. Secrets show length only."""
    if not value:
        return "not set"
    if name in SECRET_VARS:
        return f"set ({len(value)} characters, value hidden)"
    return f"set ({value})"


def credential_status(load_file: bool = True) -> list:
    """(name, required, present, description) for every credential variable.

    Nothing in the returned description reveals a secret.
    """
    if load_file:
        load_env_file()
    status = []
    for name, required, hint in CREDENTIAL_VARS:
        value = os.environ.get(name, "")
        status.append((name, required, bool(value), describe_value(name, value),
                       hint))
    return status


def env_file_present() -> bool:
    return ENV_FILE.is_file()


def gitignore_covers_env() -> bool:
    """True when `.gitignore` keeps `.env` out of commits."""
    gitignore = PROJECT_ROOT / ".gitignore"
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(line.strip() in {".env", "*.env", "/.env"} for line in lines)
