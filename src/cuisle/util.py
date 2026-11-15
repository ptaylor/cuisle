"""Small formatting and time helpers shared by the CLI, server and report."""

from __future__ import annotations

import re

DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)([smhdwy])$")
DAY_MS = 86_400_000
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31_536_000}


def parse_since(value: str | int | None, now_ms: int, default_ms: int) -> int:
    if value is None:
        return now_ms - default_ms
    if isinstance(value, int):
        return value
    text = value.strip()
    if text.isdigit():
        return int(text)
    match = DURATION_RE.match(text)
    if not match:
        raise ValueError(f"invalid duration: {value!r} (use 30m, 24h, 7d, 1y)")
    amount = float(match.group(1))
    unit = match.group(2)
    return now_ms - int(amount * UNIT_SECONDS[unit] * 1000)


def parse_duration(value: str | int | None, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    text = value.strip()
    if text.isdigit():
        return int(text)
    match = DURATION_RE.match(text)
    if not match:
        raise ValueError(f"invalid duration: {value!r} (use 30m, 24h, 7d, 1y)")
    amount = float(match.group(1))
    unit = match.group(2)
    return int(amount * UNIT_SECONDS[unit])


def format_bytes(value: float | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_bps(value: float | None) -> str:
    if value is None:
        return "-"
    rate = float(value)
    for unit, scale in (("Gbps", 1e9), ("Mbps", 1e6), ("kbps", 1e3)):
        if abs(rate) >= scale:
            return f"{rate / scale:.1f} {unit}"
    return f"{rate:.0f} bps"


def format_ms(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f} ms"


def format_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}%"


def format_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}"
