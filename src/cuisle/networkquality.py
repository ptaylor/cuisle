"""Apple's `networkQuality` capacity test."""

from __future__ import annotations

import json
from typing import Any

from cuisle.model import ThroughputSample
from cuisle.runner import Runner


def _number(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_networkquality(data: dict[str, Any]) -> dict[str, Any]:
    other = data.get("other") or {}
    interface_type = other.get("interface-type") if isinstance(other, dict) else None
    detail_parts = []
    if interface_type:
        detail_parts.append(f"type {interface_type}")
    dl_resp = _number(data, "dl_responsiveness")
    ul_resp = _number(data, "ul_responsiveness")
    if dl_resp is not None:
        detail_parts.append(f"down responsiveness {dl_resp:.0f}")
    if ul_resp is not None:
        detail_parts.append(f"up responsiveness {ul_resp:.0f}")
    return {
        "down_bps": _number(data, "dl_throughput"),
        "up_bps": _number(data, "ul_throughput"),
        "latency_ms": _number(data, "base_rtt"),
        "bytes_down": int(_number(data, "dl_bytes_transferred") or 0) or None,
        "bytes_up": int(_number(data, "ul_bytes_transferred") or 0) or None,
        "server": data.get("test_endpoint"),
        "interface": data.get("interface_name"),
        "detail": "; ".join(detail_parts) or None,
    }


def run_networkquality(
    runner: Runner,
    ts: int,
    timeout: float = 60.0,
    interface: str | None = None,
) -> ThroughputSample:
    max_runtime = max(10, int(timeout))
    argv = ["networkQuality", "-c", "-s", "-M", str(max_runtime)]
    if interface:
        argv.extend(["-I", interface])
    res = runner.run(argv, timeout=max_runtime + 15)
    if res.returncode == 127:
        return ThroughputSample(
            ts=ts,
            anchor="networkquality",
            scope="capacity",
            backend="networkquality",
            success=False,
            interface=interface,
            detail="networkQuality not installed",
        )
    if res.error:
        return ThroughputSample(
            ts=ts,
            anchor="networkquality",
            scope="capacity",
            backend="networkquality",
            success=False,
            interface=interface,
            detail=f"networkQuality {res.error}",
        )
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return ThroughputSample(
            ts=ts,
            anchor="networkquality",
            scope="capacity",
            backend="networkquality",
            success=False,
            interface=interface,
            detail=(res.stderr.strip() or "networkQuality returned invalid JSON")[:300],
        )
    parsed = parse_networkquality(data)
    return ThroughputSample(
        ts=ts,
        anchor="networkquality",
        scope="capacity",
        backend="networkquality",
        success=parsed["down_bps"] is not None or parsed["up_bps"] is not None,
        down_bps=parsed["down_bps"],
        up_bps=parsed["up_bps"],
        latency_ms=parsed["latency_ms"],
        bytes_down=parsed["bytes_down"],
        bytes_up=parsed["bytes_up"],
        server=parsed["server"],
        interface=parsed["interface"] or interface,
        detail=parsed["detail"],
    )
