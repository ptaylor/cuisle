"""Self-contained HTML reports generated from the local database."""

from __future__ import annotations

import html
import webbrowser
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from cuisle import __version__, db
from cuisle.config import Config
from cuisle.model import iso_local
from cuisle.util import format_bps, format_bytes, format_ms, format_pct


def _icon_svg() -> str:
    try:
        return files("cuisle").joinpath("icons", "icon.svg").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '<p class="empty">No samples in this range.</p>'
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def generate_report(
    config: Config, since_ms: int, output: str | Path | None = None
) -> Path:
    conn = db.connect(config.db_path, readonly=True)
    try:
        snapshot = db.status_snapshot(conn, since_ms)
        events = db.events_since(conn, since_ms, 100)
    finally:
        conn.close()

    host = snapshot.get("host") or {}
    active = snapshot.get("active") or {}
    probes = snapshot.get("probes") or []
    throughputs = snapshot.get("throughputs") or []
    processes = snapshot.get("processes") or []

    mem_pct = (
        (host["mem_used"] / host["mem_total"] * 100)
        if host.get("mem_total")
        else None
    )
    summary_rows = [
        ["Generated", datetime.now().astimezone().isoformat(timespec="seconds")],
        ["Range starts", iso_local(since_ms)],
        ["Last sample", iso_local(host["ts"]) if host.get("ts") else "-"],
        ["Interface", f"{active.get('ifname')} ({active.get('kind') or 'unknown'})" if active else "-"],
        ["Address", active.get("ipv4") or active.get("ipv6") or "-"],
        ["Gateway", active.get("gateway") or "-"],
        ["CPU", format_pct(host.get("cpu_pct"))],
        ["Memory", format_pct(mem_pct)],
        ["Load", f"{host.get('load1', 0):.2f}" if host else "-"],
        ["Processes", str(host.get("process_count", "-"))],
    ]

    health_rows = [
        [
            p["scope"],
            p["anchor"],
            p["method"],
            format_ms(p.get("latency_ms")),
            format_pct(p.get("loss_pct"), 0),
            "ok" if p.get("success") else "fail",
            p.get("detail") or p.get("status") or "",
        ]
        for p in probes
    ]
    throughput_rows = [
        [
            t["scope"],
            t["anchor"],
            t["backend"],
            format_bps(t.get("down_bps")),
            format_bps(t.get("up_bps")),
            t.get("server") or "-",
            "ok" if t.get("success") else "fail",
        ]
        for t in throughputs
    ]
    process_rows = [
        [
            p["pid"],
            p["name"],
            format_pct(p.get("cpu_pct")),
            format_bytes(p.get("rss_bytes")),
            p.get("threads"),
            format_bps(p.get("rx_bps")),
            format_bps(p.get("tx_bps")),
        ]
        for p in processes
    ]
    event_rows = [
        [iso_local(e["ts"]), e["kind"], e["detail"]]
        for e in events
    ]

    icon = _icon_svg()
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cuisle report — {html.escape(iso_local(since_ms))}</title>
<style>
:root {{ --bg:#f3f8f8; --panel:#fff; --ink:#0b2230; --muted:#5a7078; --line:#d5e4e6; --accent:#0f9c86; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#07141c; --panel:#0d2230; --ink:#e9f7f7; --muted:#8fb0b8; --line:#1b4050; --accent:#3be3c4; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:28px; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }}
main {{ max-width:1040px; margin:0 auto; }}
header {{ display:flex; align-items:center; gap:14px; margin-bottom:22px; }}
header svg {{ width:56px; height:56px; border-radius:13px; }}
h1 {{ margin:0; font-size:26px; }}
h2 {{ font-size:13px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:24px 0 8px; }}
p {{ margin:6px 0; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin:14px 0; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ text-align:left; color:var(--muted); font-weight:600; padding:5px 8px 6px 0; border-bottom:1px solid var(--line); white-space:nowrap; }}
td {{ padding:5px 8px 5px 0; border-bottom:1px solid var(--line); vertical-align:top; }}
tr:last-child td {{ border-bottom:0; }}
.empty {{ color:var(--muted); }}
footer {{ color:var(--muted); font-size:12px; margin-top:22px; }}
</style>
</head>
<body>
<main>
<header>{icon}<div><h1>Cuisle report</h1><p class="muted">A heartbeat for the network</p></div></header>
<div class="card"><h2>Summary</h2>{_table(["Item", "Value"], summary_rows)}</div>
<div class="card"><h2>Network health</h2>{_table(["Scope", "Anchor", "Method", "Latency", "Loss", "Status", "Detail"], health_rows)}</div>
<div class="card"><h2>Throughput</h2>{_table(["Scope", "Anchor", "Backend", "Down", "Up", "Server", "Status"], throughput_rows)}</div>
<div class="card"><h2>Top processes</h2>{_table(["PID", "Name", "CPU", "Memory", "Threads", "RX/s", "TX/s"], process_rows)}</div>
<div class="card"><h2>Events</h2>{_table(["Time", "Event", "Detail"], event_rows)}</div>
<footer>Generated by Cuisle {html.escape(__version__)}. Data stayed on this Mac.</footer>
</main>
</body>
</html>
"""

    if output is None:
        report_dir = Path.cwd() / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        output = report_dir / f"cuisle-report-{datetime.now():%Y%m%d-%H%M%S}.html"
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path


def open_report(path: Path) -> None:
    webbrowser.open(path.resolve().as_uri())
