"""Human-readable tables for the CLI."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from typing import Any

from cuisle.model import iso_local
from cuisle.util import format_bps, format_bytes, format_ms, format_pct


def _cell(value: Any) -> str:
    return "-" if value is None or value == "" else str(value)


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    numeric: Sequence[int] = (),
    width: int | None = None,
) -> str:
    if not rows:
        return "(no data)"
    terminal = width or shutil.get_terminal_size((120, 24)).columns
    rendered = [[_cell(cell) for cell in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in rendered:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(cell))

    # Shrink the widest text column until the table fits the terminal.
    while sum(widths) + 2 * (len(widths) - 1) > terminal:
        candidates = [i for i in range(len(widths)) if i not in numeric and widths[i] > 8]
        if not candidates:
            break
        widest = max(candidates, key=lambda i: widths[i])
        widths[widest] -= 1

    def line(values: Sequence[str]) -> str:
        parts = []
        for index, value in enumerate(values):
            clipped = value if len(value) <= widths[index] else value[: max(1, widths[index] - 1)] + "…"
            parts.append(clipped.rjust(widths[index]) if index in numeric else clipped.ljust(widths[index]))
        return "  ".join(parts).rstrip()

    output = [line(headers), "  ".join("-" * w for w in widths)]
    output.extend(line(row) for row in rendered)
    return "\n".join(output)


def _clock(ts: int | None) -> str:
    return iso_local(ts)[11:19] if ts else "-"


def render_status(snapshot: dict[str, Any]) -> str:
    host = snapshot.get("host")
    active = snapshot.get("active")
    if not host and not active:
        return "No samples yet. Start the daemon with: cuisle daemon run"

    lines: list[str] = ["ACTIVE LINK"]
    if active:
        lines.append(f"  Interface   {active.get('ifname')} ({active.get('kind') or 'unknown'})")
        lines.append(f"  Address     {active.get('ipv4') or active.get('ipv6') or '-'}")
        lines.append(f"  Gateway     {active.get('gateway') or '-'}")
        if active.get("ssid"):
            lines.append(f"  SSID        {active['ssid']}")
        signal = []
        if active.get("rssi_dbm") is not None:
            signal.append(f"{active['rssi_dbm']} dBm")
            if active.get("noise_dbm") is not None:
                signal.append(f"SNR {active['rssi_dbm'] - active['noise_dbm']} dB")
        if active.get("band"):
            signal.append(str(active["band"]))
        if active.get("channel"):
            signal.append(f"ch {active['channel']}")
        if active.get("width_mhz"):
            signal.append(f"{active['width_mhz']} MHz")
        if signal:
            lines.append(f"  Signal      {' · '.join(signal)}")
        if active.get("tx_rate_mbps"):
            lines.append(f"  Tx rate     {active['tx_rate_mbps']:.0f} Mbps")
        if active.get("link_speed_mbps"):
            lines.append(f"  Link speed  {active['link_speed_mbps']} Mbps")
        lines.append(
            f"  Counters    {format_bytes(active.get('rx_bytes'))} rx · "
            f"{format_bytes(active.get('tx_bytes'))} tx"
        )
        if active.get("rx_errors") or active.get("tx_errors"):
            lines.append(
                f"  Errors      {active.get('rx_errors') or 0} rx · "
                f"{active.get('tx_errors') or 0} tx"
            )
    else:
        lines.append("  No active interface.")

    if host:
        mem_pct = (host["mem_used"] / host["mem_total"] * 100) if host.get("mem_total") else 0
        lines.extend(
            [
                "",
                "HOST",
                f"  CPU         {format_pct(host.get('cpu_pct'))}",
                (
                    f"  Memory      {format_pct(mem_pct)} "
                    f"({format_bytes(host.get('mem_used'))} of "
                    f"{format_bytes(host.get('mem_total'))})"
                ),
                f"  Load        {host.get('load1', 0):.2f}",
                f"  Processes   {host.get('process_count', 0)}",
                f"  Sampled     {iso_local(host['ts'])}",
            ]
        )

    probes = snapshot.get("probes") or []
    if probes:
        lines.extend(
            [
                "",
                "NETWORK HEALTH",
                table(
                    ["SCOPE", "ANCHOR", "METHOD", "LATENCY", "LOSS", "STATUS"],
                    [
                        [
                            p["scope"],
                            p["anchor"],
                            p["method"],
                            format_ms(p.get("latency_ms")),
                            format_pct(p.get("loss_pct"), 0),
                            "ok" if p.get("success") else "fail",
                        ]
                        for p in probes
                    ],
                    numeric=(3, 4),
                ),
            ]
        )

    throughputs = snapshot.get("throughputs") or []
    if throughputs:
        lines.extend(
            [
                "",
                "THROUGHPUT",
                table(
                    ["SCOPE", "ANCHOR", "BACKEND", "DOWN", "UP", "SERVER"],
                    [
                        [
                            t["scope"],
                            t["anchor"],
                            t["backend"],
                            format_bps(t.get("down_bps")),
                            format_bps(t.get("up_bps")),
                            t.get("server") or "-",
                        ]
                        for t in throughputs
                    ],
                    numeric=(3, 4),
                ),
            ]
        )

    processes = snapshot.get("processes") or []
    if processes:
        lines.extend(
            [
                "",
                "TOP PROCESSES (CPU / MEMORY)",
                table(
                    ["PID", "NAME", "CPU", "MEMORY", "THREADS"],
                    [
                        [
                            p["pid"],
                            p["name"],
                            format_pct(p.get("cpu_pct")),
                            format_bytes(p.get("rss_bytes")),
                            p.get("threads"),
                        ]
                        for p in processes[:10]
                    ],
                    numeric=(0, 2, 3, 4),
                ),
            ]
        )

    network = [p for p in (snapshot.get("network_processes") or []) if (p.get("rx_bps") or 0) + (p.get("tx_bps") or 0) > 0]
    if network:
        lines.extend(
            [
                "",
                "TOP PROCESSES (NETWORK)",
                table(
                    ["NAME", "RX/S", "TX/S"],
                    [[p["name"], format_bps(p.get("rx_bps")), format_bps(p.get("tx_bps"))] for p in network[:10]],
                    numeric=(1, 2),
                ),
            ]
        )

    events = snapshot.get("events") or []
    if events:
        lines.extend(
            [
                "",
                "EVENTS",
                table(
                    ["TIME", "EVENT", "DETAIL"],
                    [[_clock(e.get("ts")), e["kind"], e["detail"]] for e in events[:8]],
                ),
            ]
        )
    return "\n".join(lines)


def render_processes(rows: list[dict[str, Any]], sort: str = "cpu") -> str:
    return table(
        ["PID", "NAME", "CPU", "MEMORY", "THREADS", "RX/S", "TX/S"],
        [
            [
                r.get("pid"),
                r.get("name"),
                format_pct(r.get("cpu_pct")),
                format_bytes(r.get("rss_bytes")),
                r.get("threads"),
                format_bps(r.get("rx_bps")),
                format_bps(r.get("tx_bps")),
            ]
            for r in rows
        ],
        numeric=(0, 2, 3, 4, 5, 6),
    )


def render_connections(rows: list[dict[str, Any]]) -> str:
    return table(
        ["PROCESS", "PROTO", "LOCAL", "REMOTE", "STATE", "RX/S", "TX/S"],
        [
            [
                r.get("name") or (f"pid {r['pid']}" if r.get("pid") is not None else "-"),
                r.get("proto"),
                _endpoint(r.get("local_addr"), r.get("local_port")),
                _endpoint(r.get("remote_addr"), r.get("remote_port")),
                r.get("state"),
                format_bps(r.get("rx_bps")),
                format_bps(r.get("tx_bps")),
            ]
            for r in rows
        ],
        numeric=(5, 6),
    )


def _endpoint(address: Any, port: Any) -> str:
    address = address or "*"
    if port is None:
        return str(address)
    host = f"[{address}]" if ":" in str(address) else str(address)
    return f"{host}:{port}"


def render_health(rows: list[dict[str, Any]]) -> str:
    return table(
        ["SCOPE", "ANCHOR", "METHOD", "LATENCY", "LOSS", "STATUS", "DETAIL"],
        [
            [
                r.get("scope"),
                r.get("anchor"),
                r.get("method"),
                format_ms(r.get("latency_ms")),
                format_pct(r.get("loss_pct"), 0),
                "ok" if r.get("success") else "fail",
                r.get("detail") or r.get("status") or "",
            ]
            for r in rows
        ],
        numeric=(3, 4),
    )


def render_throughput(rows: list[dict[str, Any]]) -> str:
    return table(
        ["SCOPE", "ANCHOR", "BACKEND", "DOWN", "UP", "SERVER", "DETAIL"],
        [
            [
                r.get("scope"),
                r.get("anchor"),
                r.get("backend"),
                format_bps(r.get("down_bps")),
                format_bps(r.get("up_bps")),
                r.get("server") or "-",
                r.get("detail") or "",
            ]
            for r in rows
        ],
        numeric=(3, 4),
    )


def render_history(
    points: list[dict[str, Any]], metric: str, resolution: str | None = None
) -> str:
    if not points:
        return f"No {metric} samples in this range."
    values = [float(p["value"]) for p in points if p.get("value") is not None]
    if not values:
        return f"No numeric {metric} samples in this range."
    formatter = {
        "down_bps": format_bps,
        "up_bps": format_bps,
        "latency_ms": format_ms,
        "loss_pct": lambda v: format_pct(v, 1),
        "cpu_pct": lambda v: format_pct(v, 1),
        "mem_pct": lambda v: format_pct(v, 1),
    }.get(metric, str)
    title = metric.upper() + (f" ({resolution})" if resolution else "")
    return title + "\n" + table(
        ["TIME", metric.upper(), "MIN", "MAX", "N"],
        [
            [
                _clock(p["ts"]),
                formatter(p.get("value")),
                formatter(p.get("min")),
                formatter(p.get("max")),
                p.get("n", "-"),
            ]
            for p in points[-120:]
        ],
        numeric=(1, 2, 3, 4),
    )


def render_doctor(checks: list[dict[str, str]]) -> str:
    return table(
        ["CHECK", "STATUS", "DETAIL"],
        [[c["name"], c["status"], c.get("detail", "")] for c in checks],
    )


def json_dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)
