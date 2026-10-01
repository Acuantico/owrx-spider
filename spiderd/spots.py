"""Spot parsing and normalization.

Every source (telnet DX cluster or MQTT broker) ends up producing the same
dictionary, which is what the browser plugin receives:

    {
        "freq": 14025000,          # Hz
        "call": "K1ABC",
        "mode": "CW",              # best effort, may be ""
        "group": "CW",             # CW | DIGITAL | PHONE
        "comment": "599 tnx",
        "spotter": "EA1ABC",
        "band": "20m",
        "time": 1767225600,        # unix seconds
        "source": "telnet",        # telnet | mqtt
    }
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

GROUPS = ("CW", "DIGITAL", "PHONE")

BANDS = [
    ("160m", 1_800_000, 2_000_000),
    ("80m", 3_500_000, 4_000_000),
    ("60m", 5_250_000, 5_450_000),
    ("40m", 7_000_000, 7_300_000),
    ("30m", 10_100_000, 10_150_000),
    ("20m", 14_000_000, 14_350_000),
    ("17m", 18_068_000, 18_168_000),
    ("15m", 21_000_000, 21_450_000),
    ("12m", 24_890_000, 24_990_000),
    ("11m", 26_965_000, 27_405_000),
    ("10m", 28_000_000, 29_700_000),
    ("6m", 50_000_000, 54_000_000),
    ("4m", 70_000_000, 70_500_000),
    ("2m", 144_000_000, 148_000_000),
    ("70cm", 430_000_000, 440_000_000),
]

CW_MODES = {"CW"}
DIGITAL_MODES = {
    "FT8", "FT4", "RTTY", "PSK", "PSK31", "PSK63", "PSK125", "BPSK", "QPSK",
    "JT65", "JT9", "JS8", "MSK144", "Q65", "FST4", "FST4W", "WSPR", "OLIVIA",
    "MFSK", "CONTESTI", "DIGI", "DIG", "DIGITAL", "DATA", "HELL", "THOR",
    "SSTV", "VARA", "VARAC", "PACKET", "PKT", "FSK441", "ROS", "DOMINO",
}
PHONE_MODES = {
    "SSB", "USB", "LSB", "AM", "FM", "NFM", "PHONE", "PH", "PHO", "FONIA",
    "VOICE", "DV", "DSTAR", "C4FM", "DMR", "FREEDV",
}
ALL_MODES = CW_MODES | DIGITAL_MODES | PHONE_MODES

# Canonical names for the aliases above (what the plugin shows/filters).
MODE_ALIASES = {
    "DIGI": "DIGITAL", "DIG": "DIGITAL", "DATA": "DIGITAL", "PKT": "PACKET",
    "PH": "SSB", "PHO": "SSB", "PHONE": "SSB", "FONIA": "SSB", "VOICE": "SSB",
}

# Typical FT8/FT4 dial frequencies (kHz); the signals sit up to 3 kHz above.
_DIGITAL_DIALS_KHZ = (
    1840, 3573, 3575.5, 5357, 7074, 7047.5, 10136, 10140, 14074, 14080,
    18100, 18104, 21074, 21140, 24915, 24919, 28074, 28180, 50313, 50318,
    50323, 144174,
)

# Rough IARU R1 band plan segments (kHz) used only when no mode is given.
_CW_SEGMENTS_KHZ = (
    (1810, 1838), (3500, 3570), (7000, 7040), (10100, 10130), (14000, 14070),
    (18068, 18095), (21000, 21070), (24890, 24915), (28000, 28070),
    (50000, 50100), (144000, 144150),
)
_DIGITAL_SEGMENTS_KHZ = (
    (1838, 1843), (3570, 3600), (7040, 7060), (10130, 10150), (14070, 14100),
    (18095, 18110), (21070, 21120), (24915, 24930), (28070, 28190),
)

_TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")

DX_LINE_RE = re.compile(
    r"^DX\s+de\s+([^\s:]+):?\s+(\d+(?:[.,]\d+)?)\s+(\S+)\s*(.*)$",
    re.IGNORECASE,
)
_TRAILING_TIME_RE = re.compile(r"\s*\b(\d{4})Z(?:\s+([A-R]{2}\d{2}[A-X]{0,2}))?\s*$", re.IGNORECASE)


def band_for_freq(freq_hz: int) -> str:
    for name, lo, hi in BANDS:
        if lo <= freq_hz <= hi:
            return name
    return ""


def _band_label(value: Any) -> str:
    """Normalize ``40``, ``"40"`` or ``"40M"`` to ``"40m"``."""
    text = str(value if value is not None else "").strip().lower()
    if re.fullmatch(r"\d+", text):
        text += "m"
    return text


def _band_range(label: str) -> Optional[Tuple[int, int]]:
    text = _band_label(label)
    for name, lo, hi in BANDS:
        if text == name:
            return lo, hi
    return None


def parse_frequency(value: Any, unit: str = "auto") -> Optional[int]:
    """Return Hz. ``auto`` guesses: <1000 is MHz, <1e6 is kHz, else Hz."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        freq = float(value)
    except (TypeError, ValueError):
        return None
    if freq <= 0:
        return None
    unit = (unit or "auto").lower()
    if unit == "hz":
        return int(round(freq))
    if unit == "khz":
        return int(round(freq * 1_000))
    if unit == "mhz":
        return int(round(freq * 1_000_000))
    if freq < 1_000:
        return int(round(freq * 1_000_000))
    if freq < 1_000_000:
        return int(round(freq * 1_000))
    return int(round(freq))


def rescue_frequency(freq_hz: int, band_label: str = "") -> int:
    """Fix x10/x100/x1000 scaling mistakes seen in some MQTT feeds.

    When the payload carries a band, the frequency is rescaled into it;
    otherwise it is divided by 10 until it lands in a known band.
    """
    rng = _band_range(band_label)
    if rng:
        lo, hi = rng
        if lo <= freq_hz <= hi:
            return freq_hz
        for factor in (10, 100, 1000):
            if lo <= freq_hz // factor <= hi:
                return freq_hz // factor
            if lo <= freq_hz * factor <= hi:
                return freq_hz * factor
        return freq_hz
    if band_for_freq(freq_hz):
        return freq_hz
    val = freq_hz
    for _ in range(4):
        val //= 10
        if val <= 0:
            break
        if band_for_freq(val):
            return val
    return freq_hz


def canonical_mode(mode: str) -> str:
    mode = str(mode or "").strip().upper()
    return MODE_ALIASES.get(mode, mode)


def mode_group(mode: str, freq_hz: int = 0) -> str:
    mode = str(mode or "").strip().upper()
    if mode in CW_MODES:
        return "CW"
    if mode in DIGITAL_MODES:
        return "DIGITAL"
    if mode in PHONE_MODES:
        return "PHONE"
    return group_from_frequency(freq_hz)


def group_from_frequency(freq_hz: int) -> str:
    khz = freq_hz / 1000.0
    for dial in _DIGITAL_DIALS_KHZ:
        if dial <= khz <= dial + 3:
            return "DIGITAL"
    for lo, hi in _CW_SEGMENTS_KHZ:
        if lo <= khz < hi:
            return "CW"
    for lo, hi in _DIGITAL_SEGMENTS_KHZ:
        if lo <= khz < hi:
            return "DIGITAL"
    return "PHONE"


def mode_from_text(text: str) -> str:
    """First mode token found in a free text comment, or ''."""
    for token in _TOKEN_SPLIT.split(str(text or "").upper()):
        if token in ALL_MODES:
            return canonical_mode(token)
    return ""


def make_spot(
    freq_hz: int,
    call: str,
    *,
    mode: str = "",
    comment: str = "",
    spotter: str = "",
    band: str = "",
    timestamp: Optional[int] = None,
    source: str = "",
) -> Dict[str, Any]:
    mode = canonical_mode(mode)
    if mode in ("", "DIGITAL"):
        # Generic or missing: a specific mode in the comment ("FT8 -12dB") wins.
        mode = mode_from_text(comment) or mode
    return {
        "freq": int(freq_hz),
        "call": str(call).strip().upper(),
        "mode": mode,
        "group": mode_group(mode, freq_hz),
        "comment": str(comment or "").strip(),
        "spotter": str(spotter or "").strip().upper(),
        "band": band or band_for_freq(freq_hz),
        "time": int(timestamp if timestamp is not None else time.time()),
        "source": source,
    }


def parse_dx_line(line: str, now: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Parse a DXSpider / CC-Cluster / AR-Cluster ``DX de`` line."""
    match = DX_LINE_RE.match(line.strip())
    if not match:
        return None
    spotter, freq_raw, call, rest = match.groups()
    freq_hz = parse_frequency(freq_raw, "khz")
    if not freq_hz or not re.search(r"[A-Z0-9]", call, re.IGNORECASE):
        return None
    comment = _TRAILING_TIME_RE.sub("", rest).strip()
    return make_spot(
        freq_hz,
        call,
        comment=comment,
        spotter=spotter.rstrip(":"),
        timestamp=now,
        source="telnet",
    )


# ---------------------------------------------------------------------------
# MQTT payloads
# ---------------------------------------------------------------------------

FIELD_ALIASES = {
    "frequency": ("frequencyHz", "qrg", "frequency", "freq"),
    "call": ("dx", "call", "callsign", "dxcall"),
    "spotter": ("spotter", "src", "de"),
    "mode": ("mode", "submode", "md"),
    "comment": ("comment", "cmt", "info"),
    "time": ("timestamp", "isots", "utc", "time", "ts"),
    "band": ("band",),
}


def _first(raw: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def parse_timestamp(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if ts > 1e12:  # milliseconds
            ts /= 1000.0
        return int(ts) if ts > 0 else None
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return parse_timestamp(float(text))
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _mode_from_topic(topic: str) -> str:
    t = topic.lower()
    if "rbn-cw" in t or "/cw" in t:
        return "CW"
    if "rbn-dig" in t or "/digi" in t or "ft8" in t:
        return "DIGITAL"
    return ""


def parse_mqtt_payload(topic: str, payload: bytes, now: Optional[int] = None) -> List[Dict[str, Any]]:
    """Turn one MQTT message into zero or more spots.

    Accepts a JSON object, an array of objects, ``{"data": ...}`` or
    ``{"spot": ...}``. A plain text ``DX de`` line is accepted as well.
    """
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        spot = parse_dx_line(text, now)
        if spot:
            spot["source"] = "mqtt"
            return [spot]
        return []

    if isinstance(data, dict):
        for wrapper in ("data", "spot", "spots"):
            if isinstance(data.get(wrapper), (dict, list)):
                data = data[wrapper]
                break
    items = data if isinstance(data, list) else [data]
    spots = []
    for item in items:
        if isinstance(item, dict):
            spot = _spot_from_dict(topic, item, now)
            if spot:
                spots.append(spot)
    return spots


def _spot_from_dict(topic: str, raw: Dict[str, Any], now: Optional[int]) -> Optional[Dict[str, Any]]:
    freq_hz = parse_frequency(_first(raw, FIELD_ALIASES["frequency"]))
    call = _first(raw, FIELD_ALIASES["call"])
    if not freq_hz or not call:
        return None
    band = _band_label(_first(raw, FIELD_ALIASES["band"]))
    freq_hz = rescue_frequency(freq_hz, band)
    comment = str(_first(raw, FIELD_ALIASES["comment"]) or "")
    mode = str(_first(raw, FIELD_ALIASES["mode"]) or "")
    if not mode:
        mode = mode_from_text(comment) or _mode_from_topic(topic)
    timestamp = parse_timestamp(_first(raw, FIELD_ALIASES["time"]))
    if timestamp is None:
        timestamp = now
    return make_spot(
        freq_hz,
        str(call),
        mode=mode,
        comment=comment,
        spotter=str(_first(raw, FIELD_ALIASES["spotter"]) or ""),
        band=band if _band_range(band) else "",
        timestamp=timestamp,
        source="mqtt",
    )
