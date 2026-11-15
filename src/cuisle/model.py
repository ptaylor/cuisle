"""Data shapes shared by samplers, storage, the API and the renderers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


def iso_local(ts_ms: int) -> str:
    """Render an epoch-millisecond timestamp in the system timezone."""
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone().isoformat(
        timespec="seconds"
    )


def _with_ts(data: dict[str, Any]) -> dict[str, Any]:
    data["ts_iso"] = iso_local(data["ts"])
    return data


@dataclass(slots=True)
class HostSample:
    ts: int
    cpu_pct: float
    mem_used: int
    mem_total: int
    load1: float
    process_count: int

    def as_dict(self) -> dict[str, Any]:
        return _with_ts(asdict(self))


@dataclass(slots=True)
class ProcessSample:
    ts: int
    pid: int
    name: str
    username: str | None
    cpu_pct: float
    rss_bytes: int
    threads: int
    status: str
    started_at: float | None = None
    rx_bps: float | None = None
    tx_bps: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return _with_ts(asdict(self))


@dataclass(slots=True)
class ConnectionSample:
    ts: int
    pid: int | None
    name: str | None
    proto: str
    local_addr: str
    local_port: int | None
    remote_addr: str
    remote_port: int | None
    state: str
    rx_bytes: int
    tx_bytes: int
    rx_bps: float
    tx_bps: float
    interface: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return _with_ts(asdict(self))


@dataclass(slots=True)
class InterfaceSample:
    ts: int
    ifname: str
    kind: str
    is_up: bool
    is_default: bool
    ipv4: str | None = None
    ipv6: str | None = None
    gateway: str | None = None
    ssid: str | None = None
    bssid: str | None = None
    rssi_dbm: int | None = None
    noise_dbm: int | None = None
    channel: int | None = None
    band: str | None = None
    width_mhz: int | None = None
    tx_rate_mbps: float | None = None
    link_speed_mbps: int | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    rx_errors: int | None = None
    tx_errors: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return _with_ts(asdict(self))


@dataclass(slots=True)
class ProbeSample:
    ts: int
    anchor: str
    scope: str
    method: str
    success: bool
    latency_ms: float | None = None
    jitter_ms: float | None = None
    loss_pct: float | None = None
    status: str | None = None
    detail: str | None = None
    interface: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return _with_ts(asdict(self))


@dataclass(slots=True)
class ThroughputSample:
    ts: int
    anchor: str
    scope: str
    backend: str
    success: bool
    down_bps: float | None = None
    up_bps: float | None = None
    latency_ms: float | None = None
    jitter_ms: float | None = None
    bytes_down: int | None = None
    bytes_up: int | None = None
    server: str | None = None
    interface: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return _with_ts(asdict(self))


@dataclass(slots=True)
class EventSample:
    ts: int
    kind: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return _with_ts(asdict(self))


@dataclass(slots=True)
class ActiveLink:
    """The interface that currently carries the default route."""

    ifname: str | None
    kind: str | None
    ipv4: str | None
    gateway: str | None
    ssid: str | None = None
    bssid: str | None = None
    rssi_dbm: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
