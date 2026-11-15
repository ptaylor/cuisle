"""Throughput backends: HTTP, optional Ookla Speedtest, optional iperf3."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cuisle import __version__
from cuisle.config import Anchor, Config
from cuisle.model import ThroughputSample
from cuisle.networkquality import run_networkquality
from cuisle.runner import Runner

USER_AGENT = f"Cuisle/{__version__}"


def _number(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _url_host(url: str) -> str | None:
    return urllib.parse.urlsplit(url).hostname


def _download(url: str, max_bytes: int, timeout: float) -> tuple[int, float, int]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": f"bytes=0-{max_bytes - 1}"},
        method="GET",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes)
        elapsed = time.perf_counter() - started
        return len(data), elapsed, int(getattr(response, "status", 0) or 0)


def _upload(url: str, size: int, timeout: float) -> tuple[int, float, int]:
    payload = (b"cuisle-upload-" * (size // 14 + 1))[:size]
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/octet-stream",
        },
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read(1024)
        elapsed = time.perf_counter() - started
        return len(payload), elapsed, int(getattr(response, "status", 0) or 0)


def http_backend(
    anchor: Anchor, config: Config, ts: int, interface: str | None
) -> ThroughputSample:
    timeout = config.throughput.timeout_seconds
    download_bytes = config.throughput.download_bytes
    upload_bytes = config.throughput.upload_bytes
    details: list[str] = []
    down_bps = None
    up_bps = None
    bytes_down = None
    bytes_up = None
    success = False
    server = None

    if anchor.download_url:
        server = _url_host(anchor.download_url)
        try:
            size, elapsed, status = _download(anchor.download_url, download_bytes, timeout)
            if size > 0 and elapsed > 0:
                down_bps = size * 8 / elapsed
                bytes_down = size
                success = True
                details.append(f"download {status}, {size} bytes")
            else:
                details.append("download returned no data")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            details.append(f"download failed: {exc}")
    elif anchor.upload_url:
        server = _url_host(anchor.upload_url)

    if anchor.upload_url:
        server = server or _url_host(anchor.upload_url)
        try:
            size, elapsed, status = _upload(anchor.upload_url, upload_bytes, timeout)
            if size > 0 and elapsed > 0:
                up_bps = size * 8 / elapsed
                bytes_up = size
                success = True
                details.append(f"upload {status}, {size} bytes")
            else:
                details.append("upload returned no data")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            details.append(f"upload failed: {exc}")

    if not anchor.download_url and not anchor.upload_url:
        details.append("no download_url or upload_url")

    return ThroughputSample(
        ts=ts,
        anchor=anchor.name,
        scope=anchor.scope,
        backend="http",
        success=success,
        down_bps=down_bps,
        up_bps=up_bps,
        bytes_down=bytes_down,
        bytes_up=bytes_up,
        server=server,
        interface=interface,
        detail="; ".join(details) or None,
    )


def parse_speedtest_json(data: dict[str, Any]) -> dict[str, Any]:
    download = data.get("download") or {}
    upload = data.get("upload") or {}
    ping = data.get("ping") or {}
    server = data.get("server") or {}
    interface = data.get("interface") or {}
    down_bytes = _number(download, "bandwidth")
    up_bytes = _number(upload, "bandwidth")
    return {
        "down_bps": down_bytes * 8 if down_bytes is not None else None,
        "up_bps": up_bytes * 8 if up_bytes is not None else None,
        "latency_ms": _number(ping, "latency"),
        "jitter_ms": _number(ping, "jitter"),
        "server": server.get("name") or server.get("url"),
        "interface": interface.get("name"),
    }


def run_speedtest_backend(
    anchor: Anchor, runner: Runner, ts: int, interface: str | None, timeout: float = 30.0
) -> ThroughputSample:
    argv = ["speedtest", "--accept-license", "-f", "json"]
    if anchor.server_id is not None:
        argv.extend(["-s", str(anchor.server_id)])
    res = runner.run(argv, timeout=timeout + 60)
    if res.returncode == 127:
        detail = "Ookla speedtest CLI not installed"
        return ThroughputSample(
            ts=ts,
            anchor=anchor.name,
            scope=anchor.scope,
            backend="speedtest",
            success=False,
            server=str(anchor.server_id) if anchor.server_id is not None else None,
            interface=interface,
            detail=detail,
        )
    data = _json_object(res.stdout)
    if data is None:
        return ThroughputSample(
            ts=ts,
            anchor=anchor.name,
            scope=anchor.scope,
            backend="speedtest",
            success=False,
            server=str(anchor.server_id) if anchor.server_id is not None else None,
            interface=interface,
            detail=(res.stderr.strip() or "speedtest returned invalid JSON")[:300],
        )
    parsed = parse_speedtest_json(data)
    return ThroughputSample(
        ts=ts,
        anchor=anchor.name,
        scope=anchor.scope,
        backend="speedtest",
        success=parsed["down_bps"] is not None or parsed["up_bps"] is not None,
        down_bps=parsed["down_bps"],
        up_bps=parsed["up_bps"],
        latency_ms=parsed["latency_ms"],
        jitter_ms=parsed["jitter_ms"],
        server=parsed["server"],
        interface=parsed["interface"] or interface,
        detail=res.stderr.strip()[:300] or None,
    )


def parse_iperf3_json(data: dict[str, Any], direction: str) -> dict[str, Any]:
    end = data.get("end") or {}
    sent = end.get("sum_sent") or {}
    received = end.get("sum_received") or {}
    summary = end.get("sum") or {}
    up = _number(sent, "bits_per_second")
    down = _number(received, "bits_per_second")
    if direction == "up":
        down = None
    elif direction == "down":
        up = None
    return {
        "down_bps": down,
        "up_bps": up,
        "jitter_ms": _number(summary, "jitter_ms"),
    }


def run_iperf3_backend(
    anchor: Anchor, runner: Runner, ts: int, interface: str | None, timeout: float = 30.0
) -> ThroughputSample:
    if not anchor.host:
        return ThroughputSample(
            ts=ts,
            anchor=anchor.name,
            scope=anchor.scope,
            backend="iperf3",
            success=False,
            interface=interface,
            detail="iperf3 needs a host",
        )
    port = anchor.port or 5201
    duration = max(1, anchor.duration_seconds)
    direction = anchor.direction
    argv = [
        "iperf3",
        "-c",
        anchor.host,
        "-p",
        str(port),
        "-t",
        str(duration),
        "-J",
    ]
    if direction == "down":
        argv.append("-R")
    elif direction == "both":
        argv.append("--bidir")
    res = runner.run(argv, timeout=duration + 20)
    data = _json_object(res.stdout)
    if data is None:
        return ThroughputSample(
            ts=ts,
            anchor=anchor.name,
            scope=anchor.scope,
            backend="iperf3",
            success=False,
            server=f"{anchor.host}:{port}",
            interface=interface,
            detail=(res.stderr.strip() or "iperf3 returned invalid JSON")[:300],
        )
    parsed = parse_iperf3_json(data, direction)
    success = res.returncode == 0 and (
        parsed["down_bps"] is not None or parsed["up_bps"] is not None
    )
    return ThroughputSample(
        ts=ts,
        anchor=anchor.name,
        scope=anchor.scope,
        backend="iperf3",
        success=success,
        down_bps=parsed["down_bps"],
        up_bps=parsed["up_bps"],
        jitter_ms=parsed["jitter_ms"],
        server=f"{anchor.host}:{port}",
        interface=interface,
        detail=f"iperf3 {direction} to {anchor.host}:{port}",
    )


def run_anchor_throughput(
    anchor: Anchor,
    config: Config,
    runner: Runner,
    ts: int,
    interface: str | None,
) -> ThroughputSample:
    backend = anchor.resolved_backend(config.throughput.backend)
    if backend == "http":
        return http_backend(anchor, config, ts, interface)
    if backend == "speedtest":
        return run_speedtest_backend(
            anchor, runner, ts, interface, timeout=config.throughput.timeout_seconds
        )
    if backend == "iperf3":
        return run_iperf3_backend(
            anchor, runner, ts, interface, timeout=config.throughput.timeout_seconds
        )
    return ThroughputSample(
        ts=ts,
        anchor=anchor.name,
        scope=anchor.scope,
        backend=backend,
        success=False,
        interface=interface,
        detail=f"unknown backend: {backend}",
    )


def run_all_throughput(
    config: Config,
    runner: Runner,
    ts: int,
    interface: str | None,
    anchors: list[Anchor] | None = None,
    include_networkquality: bool = False,
) -> list[ThroughputSample]:
    samples: list[ThroughputSample] = []
    if include_networkquality:
        samples.append(
            run_networkquality(
                runner,
                ts,
                timeout=max(30, config.throughput.timeout_seconds * 2),
                interface=interface,
            )
        )
    for anchor in anchors if anchors is not None else config.enabled_anchors():
        backend = anchor.resolved_backend(config.throughput.backend)
        if backend == "http" and not (anchor.download_url or anchor.upload_url):
            continue
        samples.append(run_anchor_throughput(anchor, config, runner, ts, interface))
    return samples
