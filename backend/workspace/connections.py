# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Runtime NextCloud connection management — GUI-driven, no .env editing.

Credentials entered in the GUI are written into ``os.environ`` at runtime, so
every existing call-time ``os.getenv("NEXTCLOUD_*")`` read across the codebase
picks them up with no refactoring. Optionally persisted to a gitignored local
file so the connection is restored on the next start.

Env vars set before launch still work and take precedence — Docker/CI can
preset them headlessly; the GUI is just the friendlier path for everyone else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Tuple

import requests

ENV_BASE = "NEXTCLOUD_BASE_URL"
ENV_USER = "NEXTCLOUD_BASIC_USERNAME"
ENV_PASS = "NEXTCLOUD_BASIC_PASSWORD"

# Defaults for the local NextCloud overlay (docker-compose.nextcloud.yml).
# The base URL is the in-container service URL (http://nextcloud:80) because the
# connection test runs server-side; browse from the host at http://localhost:8080.
# admin/admin are the documented LOCAL-STACK defaults, overridable via env.
LOCAL_DEFAULT_BASE = os.environ.get("NEXTCLOUD_LOCAL_DEFAULT_URL", "http://nextcloud:80")
LOCAL_DEFAULT_USER = os.environ.get("NEXTCLOUD_LOCAL_DEFAULT_USER", "admin")
LOCAL_DEFAULT_PASS = os.environ.get("NEXTCLOUD_LOCAL_DEFAULT_PASS", "admin")


def _connections_dir() -> Path:
    override = os.environ.get("DIGICITIES_CONNECTIONS_DIR")
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parents[2]  # backend/workspace/ -> repo root
    return repo_root / "data" / ".connections"


def _store_path() -> Path:
    return _connections_dir() / "nextcloud.json"


# --- state inspection -------------------------------------------------------

def nextcloud_is_configured() -> bool:
    return bool(os.environ.get(ENV_USER) and (os.environ.get(ENV_BASE) or os.environ.get(ENV_PASS)))


def current_nextcloud_connection() -> dict:
    return {
        "base_url": os.environ.get(ENV_BASE, ""),
        "username": os.environ.get(ENV_USER, ""),
        "password": os.environ.get(ENV_PASS, ""),
    }


def default_nextcloud_connection() -> dict:
    """Values to pre-fill the connector form with.

    A live env/saved connection wins; otherwise fall back to the local NextCloud
    overlay defaults so the user can just hit 'Connect & test'.
    """
    cur = current_nextcloud_connection()
    if cur["base_url"] or cur["username"]:
        return cur
    return {
        "base_url": LOCAL_DEFAULT_BASE,
        "username": LOCAL_DEFAULT_USER,
        "password": LOCAL_DEFAULT_PASS,
    }


def saved_connection_exists() -> bool:
    return _store_path().exists()


# --- apply / clear ----------------------------------------------------------

def apply_nextcloud_connection(base_url: str, username: str, password: str) -> None:
    """Write credentials into the process env so all call-time reads see them."""
    os.environ[ENV_BASE] = (base_url or "").strip().rstrip("/")
    os.environ[ENV_USER] = (username or "").strip()
    os.environ[ENV_PASS] = password or ""


def clear_nextcloud_connection(remove_saved: bool = True) -> None:
    for k in (ENV_BASE, ENV_USER, ENV_PASS):
        os.environ.pop(k, None)
    if remove_saved:
        delete_saved()


# --- persistence ------------------------------------------------------------

def save_nextcloud_connection(base_url: str, username: str, password: str) -> Path:
    """Persist credentials to a gitignored local file (plaintext) for auto-load."""
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "base_url": (base_url or "").strip().rstrip("/"),
                "username": (username or "").strip(),
                "password": password or "",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    try:
        os.chmod(p, 0o600)  # best-effort; no-op on some filesystems
    except Exception:
        pass
    return p


def load_saved_nextcloud_connection() -> Optional[dict]:
    p = _store_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("username") and data.get("base_url"):
            return data
    except Exception:
        pass
    return None


def delete_saved() -> None:
    try:
        _store_path().unlink()
    except FileNotFoundError:
        pass


def bootstrap_from_saved() -> bool:
    """Apply a saved connection to env if one exists and env isn't already set.
    Returns True if a saved connection was applied."""
    if nextcloud_is_configured():
        return False
    data = load_saved_nextcloud_connection()
    if not data:
        return False
    apply_nextcloud_connection(data["base_url"], data["username"], data.get("password", ""))
    return True


# --- connection test --------------------------------------------------------

def test_nextcloud_connection(base_url: str, username: str, password: str) -> Tuple[bool, str]:
    """PROPFIND the user's WebDAV root to validate the credentials live."""
    base = (base_url or "").strip().rstrip("/")
    username = (username or "").strip()
    if not (base and username and password):
        return False, "Base URL, username and password are all required."
    dav_url = f"{base}/remote.php/dav/files/{username}/"
    try:
        r = requests.request(
            "PROPFIND", dav_url,
            headers={"Depth": "0"},
            auth=(username, password),
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, f"Could not reach NextCloud: {exc}"
    if r.status_code in (200, 207):
        return True, f"Connected to {base} as {username}."
    if r.status_code in (401, 403):
        return False, "Authentication failed — check the username/password (an app password is recommended)."
    if r.status_code == 404:
        return False, f"Reached the server but the WebDAV path 404'd — check the base URL ({base})."
    return False, f"NextCloud returned HTTP {r.status_code}."
