"""spiderd configuration: a JSON file edited through the admin web page."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from typing import Any, Dict, List, Tuple
from urllib.parse import urlsplit

from .spots import GROUPS

DEFAULT_PORT = 7374

DEFAULTS: Dict[str, Any] = {
    # Master switch: when off no cluster connection is made and the
    # receiver plugin hides itself. Every installation enters its own
    # cluster details: nothing is preset.
    "enabled": False,
    "source": "telnet",  # telnet | mqtt
    "telnet": {
        "host": "",
        "port": 7300,
        "callsign": "",
        "password": "",
    },
    "mqtt": {
        "url": "",
        "topics": [],
        "username": "",
        "password": "",
        "client_id": "",
        "qos": 0,
    },
    "display": {
        "max_age_sec": 600,
        "groups": list(GROUPS),
    },
    # Read at start-up only; not editable from the web page.
    "server": {
        "bind": "0.0.0.0",
        "port": DEFAULT_PORT,
        "tls_cert": "",
        "tls_key": "",
    },
}

SECRET_FIELDS = (("telnet", "password"), ("mqtt", "password"))
SECRET_PLACEHOLDER = "•" * 8

_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$|^\[?[0-9A-Fa-f:]+\]?$")
_CALL_RE = re.compile(r"^[A-Za-z0-9/-]{3,20}$")


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key not in out:
            continue
        if isinstance(out[key], dict):
            if isinstance(value, dict):  # a section; anything else is ignored
                out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, path: str) -> None:
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)

    def load(self) -> "Config":
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
        except FileNotFoundError:
            stored = {}
        if not isinstance(stored, dict):
            raise ValueError("%s: expected a JSON object" % self.path)
        self.data = _merge(DEFAULTS, stored)
        return self

    def save(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.chmod(tmp, 0o600)  # holds cluster/broker passwords
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def public(self) -> Dict[str, Any]:
        """What browsers receive: display settings only, never credentials."""
        return {
            "enabled": bool(self.data["enabled"]),
            "max_age_sec": self.data["display"]["max_age_sec"],
            "groups": list(self.data["display"]["groups"]),
        }

    def redacted(self) -> Dict[str, Any]:
        """Editable settings for the admin page with passwords masked."""
        out = copy.deepcopy(self.data)
        for section, field in SECRET_FIELDS:
            if out[section][field]:
                out[section][field] = SECRET_PLACEHOLDER
        return out

    def update(self, incoming: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate and apply settings posted by the admin page.

        Returns (source_changed, errors). Nothing is applied when there
        are errors. ``server`` is ignored: it only changes on restart.
        """
        candidate = _merge(self.data, {k: v for k, v in incoming.items() if k != "server"})
        for section, field in SECRET_FIELDS:
            if candidate[section][field] == SECRET_PLACEHOLDER:
                candidate[section][field] = self.data[section][field]
        errors = validate(candidate)
        if errors:
            return False, errors
        source_keys = ("enabled", "source", "telnet", "mqtt")
        changed = any(candidate[k] != self.data[k] for k in source_keys)
        self.data = candidate
        return changed, []


def _as_int(value: Any, name: str, lo: int, hi: int, errors: List[str]) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append("%s must be a number" % name)
        return lo
    if not lo <= number <= hi:
        errors.append("%s must be between %d and %d" % (name, lo, hi))
    return number


def validate(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    data["enabled"] = bool(data.get("enabled"))
    if data.get("source") not in ("mqtt", "telnet"):
        errors.append("source must be 'mqtt' or 'telnet'")

    telnet = data["telnet"]
    telnet["host"] = str(telnet.get("host") or "").strip()
    telnet["callsign"] = str(telnet.get("callsign") or "").strip().upper()
    telnet["password"] = str(telnet.get("password") or "")
    telnet["port"] = _as_int(telnet.get("port"), "Telnet port", 1, 65535, errors)

    mqtt = data["mqtt"]
    mqtt["url"] = str(mqtt.get("url") or "").strip()
    topics = mqtt.get("topics")
    if isinstance(topics, str):
        topics = re.split(r"[,\n]", topics)
    mqtt["topics"] = [str(t).strip() for t in (topics or []) if str(t).strip()]
    mqtt["username"] = str(mqtt.get("username") or "")
    mqtt["password"] = str(mqtt.get("password") or "")
    mqtt["client_id"] = str(mqtt.get("client_id") or "").strip()
    mqtt["qos"] = _as_int(mqtt.get("qos"), "MQTT QoS", 0, 2, errors)

    display = data["display"]
    display["max_age_sec"] = _as_int(display.get("max_age_sec"), "Spot lifetime", 30, 7200, errors)
    groups = display.get("groups")
    display["groups"] = [g for g in GROUPS if isinstance(groups, list) and g in groups]

    # Connection details are only mandatory for the source in use.
    if data["enabled"] and data.get("source") == "telnet":
        if not telnet["host"] or not _HOST_RE.match(telnet["host"]):
            errors.append("Telnet host is missing or invalid")
        if not _CALL_RE.match(telnet["callsign"]):
            errors.append("A valid callsign is required to log in to a telnet cluster")
    if data["enabled"] and data.get("source") == "mqtt":
        parts = urlsplit(mqtt["url"])
        if parts.scheme.lower() not in ("mqtt", "mqtts", "ws", "wss") or not parts.hostname:
            errors.append("MQTT URL must look like mqtt://host:1883, mqtts://, ws:// or wss://host/path")
        if not mqtt["topics"]:
            errors.append("At least one MQTT topic is required")
    return errors
