"""Network probes: ICMP, DNS, TCP, TLS and HTTP."""

from __future__ import annotations

import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from cuisle import __version__
from cuisle.config import Anchor
from cuisle.model import ProbeSample
from cuisle.runner import Runner


@dataclass(slots=True)
class ProbeResult:
    method: str
    success: bool
    latency_ms: float | None = None
    jitter_ms: float | None = None
    loss_pct: float | None = None
    status: str | None = None
    detail: str | None = None


def parse_ping(text: str) -> dict[str, float | None]:
    loss = re.search(r"([\d.]+)%\s+packet loss", text)
    rtt = re.search(
        r"round-trip min/avg/max/stddev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms", text
    )
    return {
        "loss_pct": float(loss.group(1)) if loss else None,
        "latency_ms": float(rtt.group(2)) if rtt else None,
        "jitter_ms": float(rtt.group(4)) if rtt else None,
        "min_ms": float(rtt.group(1)) if rtt else None,
        "max_ms": float(rtt.group(3)) if rtt else None,
    }


def icmp_probe(host: str, runner: Runner, count: int = 3) -> ProbeResult:
    res = runner.run(
        ["ping", "-n", "-c", str(count), "-W", "1000", host],
        timeout=count + 4,
    )
    if res.returncode == 127:
        return ProbeResult("icmp", False, detail="ping not installed")
    parsed = parse_ping(res.stdout)
    loss = parsed["loss_pct"]
    latency = parsed["latency_ms"]
    success = loss is not None and loss < 100 and latency is not None
    detail = None if success else (res.stderr.strip() or "no ICMP reply")
    return ProbeResult(
        "icmp",
        success,
        latency_ms=latency,
        jitter_ms=parsed["jitter_ms"],
        loss_pct=loss,
        status="ok" if success else "unreachable",
        detail=detail,
    )


def parse_dig(text: str) -> dict[str, str | float | None]:
    status = re.search(r"status:\s*([A-Z]+)", text)
    query = re.search(r"Query time:\s*(\d+)\s*msec", text)
    server = re.search(r"SERVER:\s*(\S+)", text)
    return {
        "status": status.group(1) if status else None,
        "latency_ms": float(query.group(1)) if query else None,
        "server": server.group(1) if server else None,
    }


def dns_probe(host: str, runner: Runner, server: str | None = None, timeout: int = 5) -> ProbeResult:
    argv = ["dig", "+time=2", "+tries=1"]
    if server:
        argv.append(f"@{server}")
    argv.append(host)
    res = runner.run(argv, timeout=timeout)
    if res.returncode not in (0, 127) or not res.stdout.strip():
        parsed = None
    else:
        parsed = parse_dig(res.stdout)

    if parsed and parsed["latency_ms"] is not None:
        ok = parsed["status"] == "NOERROR"
        return ProbeResult(
            "dns",
            ok,
            latency_ms=parsed["latency_ms"],
            status=str(parsed["status"]),
            detail=f"server {parsed['server']}" if parsed["server"] else None,
        )

    # dig is missing or unusable: time the system resolver instead.
    started = time.perf_counter()
    try:
        socket.getaddrinfo(host, None)
        elapsed = (time.perf_counter() - started) * 1000
        return ProbeResult(
            "dns",
            True,
            latency_ms=elapsed,
            status="system-resolver",
            detail="dig unavailable; system resolver timed",
        )
    except OSError as exc:
        return ProbeResult("dns", False, status="error", detail=str(exc))


def tcp_probe(host: str, port: int, timeout: float = 3.0) -> ProbeResult:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = (time.perf_counter() - started) * 1000
        return ProbeResult("tcp", True, latency_ms=elapsed, status="connected")
    except OSError as exc:
        return ProbeResult("tcp", False, status="error", detail=str(exc))


def tls_probe(host: str, port: int, timeout: float = 5.0) -> ProbeResult:
    context = ssl.create_default_context()
    started = time.perf_counter()
    try:
        with (
            socket.create_connection((host, port), timeout=timeout) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            elapsed = (time.perf_counter() - started) * 1000
            cert = tls.getpeercert()
        not_after = cert.get("notAfter") if cert else None
        detail = None
        if not_after:
            expires = ssl.cert_time_to_seconds(not_after)
            days = (expires - time.time()) / 86400
            detail = f"certificate expires in {days:.0f} day(s)"
        return ProbeResult("tls", True, latency_ms=elapsed, status="ok", detail=detail)
    except (OSError, ssl.SSLError) as exc:
        return ProbeResult("tls", False, status="error", detail=str(exc))


def http_probe(url: str, timeout: float = 10.0, max_bytes: int = 65536) -> ProbeResult:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"Cuisle/{__version__}"},
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            data = response.read(max_bytes)
            elapsed = (time.perf_counter() - started) * 1000
            ok = 200 <= status < 400
            detail = f"{len(data)} bytes read"
            final = response.geturl()
            if final and final != url:
                detail += f"; redirected to {final}"
            return ProbeResult(
                "http", ok, latency_ms=elapsed, status=str(status), detail=detail
            )
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return ProbeResult(
            "http",
            200 <= exc.code < 400,
            latency_ms=elapsed,
            status=str(exc.code),
            detail=str(exc),
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return ProbeResult("http", False, status="error", detail=str(exc))


def _failure(method: str, detail: str) -> ProbeResult:
    return ProbeResult(method, False, status="unavailable", detail=detail)


def run_anchor_health(
    anchor: Anchor,
    gateway: str | None,
    interface: str | None,
    ts: int,
    runner: Runner,
) -> list[ProbeSample]:
    host = anchor.host or (gateway if anchor.scope == "lan" else None)
    port = anchor.port or 443
    samples: list[ProbeSample] = []

    for method in anchor.health:
        if method == "icmp":
            result = (
                icmp_probe(host, runner)
                if host
                else _failure("icmp", "no host and no default gateway")
            )
        elif method == "dns":
            result = dns_probe(host, runner) if host else _failure("dns", "no host")
        elif method == "tcp":
            result = tcp_probe(host, port) if host else _failure("tcp", "no host")
        elif method == "tls":
            result = tls_probe(host, port) if host else _failure("tls", "no host")
        elif method == "http":
            url = anchor.url
            if not url and host:
                url = f"https://{host}/" if port == 443 else f"http://{host}/"
            result = http_probe(url) if url else _failure("http", "no url or host")
        else:
            result = _failure(method, "unknown method")

        samples.append(
            ProbeSample(
                ts=ts,
                anchor=anchor.name,
                scope=anchor.scope,
                method=method,
                success=result.success,
                latency_ms=result.latency_ms,
                jitter_ms=result.jitter_ms,
                loss_pct=result.loss_pct,
                status=result.status,
                detail=result.detail,
                interface=interface,
            )
        )
    return samples
