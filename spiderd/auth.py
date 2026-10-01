"""Admin login for the spiderd configuration page.

The page accepts exactly the accounts of the OpenWebRX+ installation it runs
next to: its ``users.json`` is read (never written) on every login, so
password changes made in OpenWebRX+ apply at once, and passwords are checked
the way OpenWebRX+ does (PBKDF2-HMAC, 100000 iterations).
"""

from __future__ import annotations

import configparser
import glob
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("spiderd.auth")

ITERATIONS = 100_000
SESSION_TTL = 12 * 3600
MAX_FAILURES = 5
LOCKOUT_SEC = 60


def owrx_data_directory(etc_dir: str = "/etc/openwebrx") -> str:
    """Where OpenWebRX+ keeps users.json (``[core] data_directory``)."""
    parser = configparser.ConfigParser()
    files = [os.path.join(etc_dir, "openwebrx.conf")]
    files += sorted(glob.glob(os.path.join(etc_dir, "openwebrx.conf.d", "*.conf")))
    try:
        parser.read(files, encoding="utf-8")
    except configparser.Error as exc:
        log.warning("cannot parse OpenWebRX+ config: %s", exc)
    return parser.get("core", "data_directory", fallback="/var/lib/openwebrx")


def check_password(entry: Dict, password: str) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("encoding") == "string":
        return hmac.compare_digest(str(entry.get("value", "")).encode(), password.encode())
    if entry.get("encoding") == "hash":
        try:
            salt = bytes.fromhex(entry["salt"])
            digest = hashlib.pbkdf2_hmac(entry.get("algorithm", "sha256"), password.encode(), salt, ITERATIONS)
        except (KeyError, ValueError, TypeError):
            return False
        return hmac.compare_digest(digest.hex(), str(entry.get("value", "")))
    return False


class Authenticator:
    def __init__(self, owrx_users_file: str) -> None:
        self.owrx_users_file = owrx_users_file
        self.sessions: Dict[str, Tuple[str, float]] = {}
        self.failures: Dict[str, Tuple[int, float]] = {}

    def _load(self) -> Optional[List[Dict]]:
        try:
            with open(self.owrx_users_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("cannot read %s: %s", self.owrx_users_file, exc)
            return None
        return data if isinstance(data, list) else None

    def accounts_state(self) -> str:
        """``ok``, ``empty`` (no enabled account) or ``unreadable``, for the login page."""
        users = self._load()
        if users is None:
            return "unreadable"
        if not any(isinstance(u, dict) and u.get("enabled", True) for u in users):
            return "empty"
        return "ok"

    def verify(self, user: str, password: str) -> bool:
        for entry in self._load() or []:
            if not isinstance(entry, dict) or entry.get("user") != user:
                continue
            if entry.get("enabled", True) and check_password(entry.get("password", {}), password):
                return True
        return False

    # -- throttling and sessions -------------------------------------------

    def locked_out(self, client: str) -> int:
        count, until = self.failures.get(client, (0, 0.0))
        remaining = int(until - time.time())
        return remaining if count >= MAX_FAILURES and remaining > 0 else 0

    def login(self, client: str, user: str, password: str) -> Optional[str]:
        if self.locked_out(client):
            return None
        if not self.verify(user, password):
            count, _ = self.failures.get(client, (0, 0.0))
            count += 1
            self.failures[client] = (count, time.time() + LOCKOUT_SEC)
            log.warning("failed admin login for %r from %s", user, client)
            return None
        self.failures.pop(client, None)
        token = secrets.token_urlsafe(32)
        self.sessions[token] = (user, time.time() + SESSION_TTL)
        log.info("admin %r logged in from %s", user, client)
        return token

    def session_user(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        entry = self.sessions.get(token)
        if not entry:
            return None
        user, expires = entry
        if expires < time.time():
            self.sessions.pop(token, None)
            return None
        return user

    def logout(self, token: Optional[str]) -> None:
        if token:
            self.sessions.pop(token, None)
