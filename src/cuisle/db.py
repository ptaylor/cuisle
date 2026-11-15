"""SQLite schema, writes, queries and the dashboard snapshot."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from cuisle.model import (
    ConnectionSample,
    EventSample,
    HostSample,
    InterfaceSample,
    ProbeSample,
    ProcessSample,
    ThroughputSample,
)

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS host_samples (
    ts INTEGER PRIMARY KEY,
    cpu_pct REAL NOT NULL,
    mem_used INTEGER NOT NULL,
    mem_total INTEGER NOT NULL,
    load1 REAL NOT NULL,
    process_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS process_samples (
    ts INTEGER NOT NULL,
    pid INTEGER NOT NULL,
    name TEXT NOT NULL,
    username TEXT,
    cpu_pct REAL NOT NULL,
    rss_bytes INTEGER NOT NULL,
    threads INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at REAL,
    rx_bps REAL,
    tx_bps REAL,
    PRIMARY KEY (ts, pid)
);
CREATE INDEX IF NOT EXISTS idx_process_pid_ts ON process_samples(pid, ts);

CREATE TABLE IF NOT EXISTS connection_samples (
    ts INTEGER NOT NULL,
    pid INTEGER,
    name TEXT,
    proto TEXT NOT NULL,
    local_addr TEXT NOT NULL,
    local_port INTEGER,
    remote_addr TEXT NOT NULL,
    remote_port INTEGER,
    state TEXT NOT NULL,
    rx_bytes INTEGER NOT NULL,
    tx_bytes INTEGER NOT NULL,
    rx_bps REAL NOT NULL,
    tx_bps REAL NOT NULL,
    interface TEXT
);
CREATE INDEX IF NOT EXISTS idx_connection_ts ON connection_samples(ts);
CREATE INDEX IF NOT EXISTS idx_connection_pid_ts ON connection_samples(pid, ts);

CREATE TABLE IF NOT EXISTS interface_samples (
    ts INTEGER NOT NULL,
    ifname TEXT NOT NULL,
    kind TEXT NOT NULL,
    is_up INTEGER NOT NULL,
    is_default INTEGER NOT NULL,
    ipv4 TEXT,
    ipv6 TEXT,
    gateway TEXT,
    ssid TEXT,
    bssid TEXT,
    rssi_dbm INTEGER,
    noise_dbm INTEGER,
    channel INTEGER,
    band TEXT,
    width_mhz INTEGER,
    tx_rate_mbps REAL,
    link_speed_mbps INTEGER,
    rx_bytes INTEGER,
    tx_bytes INTEGER,
    rx_errors INTEGER,
    tx_errors INTEGER,
    PRIMARY KEY (ts, ifname)
);
CREATE INDEX IF NOT EXISTS idx_interface_ifname_ts ON interface_samples(ifname, ts);

CREATE TABLE IF NOT EXISTS probe_samples (
    ts INTEGER NOT NULL,
    anchor TEXT NOT NULL,
    scope TEXT NOT NULL,
    method TEXT NOT NULL,
    success INTEGER NOT NULL,
    latency_ms REAL,
    jitter_ms REAL,
    loss_pct REAL,
    status TEXT,
    detail TEXT,
    interface TEXT
);
CREATE INDEX IF NOT EXISTS idx_probe_anchor_ts ON probe_samples(anchor, ts);
CREATE INDEX IF NOT EXISTS idx_probe_method_ts ON probe_samples(method, ts);

CREATE TABLE IF NOT EXISTS throughput_samples (
    ts INTEGER NOT NULL,
    anchor TEXT NOT NULL,
    scope TEXT NOT NULL,
    backend TEXT NOT NULL,
    success INTEGER NOT NULL,
    down_bps REAL,
    up_bps REAL,
    latency_ms REAL,
    jitter_ms REAL,
    bytes_down INTEGER,
    bytes_up INTEGER,
    server TEXT,
    interface TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_throughput_anchor_ts ON throughput_samples(anchor, ts);

CREATE TABLE IF NOT EXISTS events (
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS rollup_5m (
    bucket INTEGER NOT NULL,
    metric TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    anchor TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    avg REAL,
    min REAL,
    max REAL,
    n INTEGER,
    PRIMARY KEY (bucket, metric, scope, anchor, method)
);

CREATE TABLE IF NOT EXISTS rollup_hourly (
    bucket INTEGER NOT NULL,
    metric TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    anchor TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    avg REAL,
    min REAL,
    max REAL,
    n INTEGER,
    PRIMARY KEY (bucket, metric, scope, anchor, method)
);
"""


def connect(path: str | Path, readonly: bool = False) -> sqlite3.Connection:
    db_path = Path(path).expanduser()
    if readonly:
        if not db_path.is_file():
            raise FileNotFoundError(db_path)
        uri = db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {version} is newer than this Cuisle ({SCHEMA_VERSION})"
        )
    if version < SCHEMA_VERSION:
        # Schema v1 is the baseline. A future version adds its ALTERs here,
        # gated by this user_version check, then bumps SCHEMA_VERSION.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def insert_host(conn: sqlite3.Connection, sample: HostSample) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO host_samples"
        "(ts, cpu_pct, mem_used, mem_total, load1, process_count) VALUES (?,?,?,?,?,?)",
        (
            sample.ts,
            sample.cpu_pct,
            sample.mem_used,
            sample.mem_total,
            sample.load1,
            sample.process_count,
        ),
    )


def insert_processes(conn: sqlite3.Connection, samples: Iterable[ProcessSample]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO process_samples"
        "(ts, pid, name, username, cpu_pct, rss_bytes, threads, status, started_at,"
        " rx_bps, tx_bps) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                s.ts,
                s.pid,
                s.name,
                s.username,
                s.cpu_pct,
                s.rss_bytes,
                s.threads,
                s.status,
                s.started_at,
                s.rx_bps,
                s.tx_bps,
            )
            for s in samples
        ],
    )


def insert_connections(conn: sqlite3.Connection, samples: Iterable[ConnectionSample]) -> None:
    conn.executemany(
        "INSERT INTO connection_samples"
        "(ts, pid, name, proto, local_addr, local_port, remote_addr, remote_port,"
        " state, rx_bytes, tx_bytes, rx_bps, tx_bps, interface)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                s.ts,
                s.pid,
                s.name,
                s.proto,
                s.local_addr,
                s.local_port,
                s.remote_addr,
                s.remote_port,
                s.state,
                s.rx_bytes,
                s.tx_bytes,
                s.rx_bps,
                s.tx_bps,
                s.interface,
            )
            for s in samples
        ],
    )


def insert_interfaces(conn: sqlite3.Connection, samples: Iterable[InterfaceSample]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO interface_samples"
        "(ts, ifname, kind, is_up, is_default, ipv4, ipv6, gateway, ssid, bssid,"
        " rssi_dbm, noise_dbm, channel, band, width_mhz, tx_rate_mbps,"
        " link_speed_mbps, rx_bytes, tx_bytes, rx_errors, tx_errors)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                s.ts,
                s.ifname,
                s.kind,
                int(s.is_up),
                int(s.is_default),
                s.ipv4,
                s.ipv6,
                s.gateway,
                s.ssid,
                s.bssid,
                s.rssi_dbm,
                s.noise_dbm,
                s.channel,
                s.band,
                s.width_mhz,
                s.tx_rate_mbps,
                s.link_speed_mbps,
                s.rx_bytes,
                s.tx_bytes,
                s.rx_errors,
                s.tx_errors,
            )
            for s in samples
        ],
    )


def insert_probes(conn: sqlite3.Connection, samples: Iterable[ProbeSample]) -> None:
    conn.executemany(
        "INSERT INTO probe_samples"
        "(ts, anchor, scope, method, success, latency_ms, jitter_ms, loss_pct,"
        " status, detail, interface) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                s.ts,
                s.anchor,
                s.scope,
                s.method,
                int(s.success),
                s.latency_ms,
                s.jitter_ms,
                s.loss_pct,
                s.status,
                s.detail,
                s.interface,
            )
            for s in samples
        ],
    )


def insert_throughputs(conn: sqlite3.Connection, samples: Iterable[ThroughputSample]) -> None:
    conn.executemany(
        "INSERT INTO throughput_samples"
        "(ts, anchor, scope, backend, success, down_bps, up_bps, latency_ms,"
        " jitter_ms, bytes_down, bytes_up, server, interface, detail)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                s.ts,
                s.anchor,
                s.scope,
                s.backend,
                int(s.success),
                s.down_bps,
                s.up_bps,
                s.latency_ms,
                s.jitter_ms,
                s.bytes_down,
                s.bytes_up,
                s.server,
                s.interface,
                s.detail,
            )
            for s in samples
        ],
    )


def insert_event(conn: sqlite3.Connection, event: EventSample) -> None:
    conn.execute(
        "INSERT INTO events(ts, kind, detail) VALUES (?,?,?)",
        (event.ts, event.kind, event.detail),
    )


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _max_ts(conn: sqlite3.Connection, table: str) -> int | None:
    row = conn.execute(f"SELECT MAX(ts) AS ts FROM {table}").fetchone()
    return int(row["ts"]) if row and row["ts"] is not None else None


def latest_host(conn: sqlite3.Connection) -> dict[str, Any] | None:
    ts = _max_ts(conn, "host_samples")
    if ts is None:
        return None
    row = conn.execute("SELECT * FROM host_samples WHERE ts=?", (ts,)).fetchone()
    return dict(row) if row else None


def latest_interfaces(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ts = _max_ts(conn, "interface_samples")
    if ts is None:
        return []
    return _rows(conn, "SELECT * FROM interface_samples WHERE ts=? ORDER BY ifname", (ts,))


def processes_since(
    conn: sqlite3.Connection, since_ms: int, sort: str = "cpu", limit: int = 25
) -> list[dict[str, Any]]:
    order = {
        "cpu": "cpu_pct DESC",
        "mem": "rss_bytes DESC",
        "rx": "rx_bps DESC",
        "tx": "tx_bps DESC",
    }.get(sort, "cpu_pct DESC")
    return _rows(
        conn,
        "SELECT pid, name, MAX(username) AS username, MAX(cpu_pct) AS cpu_pct,"
        " MAX(rss_bytes) AS rss_bytes, MAX(threads) AS threads,"
        " MAX(status) AS status, MAX(started_at) AS started_at,"
        " MAX(rx_bps) AS rx_bps, MAX(tx_bps) AS tx_bps, MAX(ts) AS ts"
        " FROM process_samples WHERE ts>=? GROUP BY pid, name"
        f" ORDER BY {order} LIMIT ?",
        (since_ms, limit),
    )


def connections_since(
    conn: sqlite3.Connection,
    since_ms: int,
    state: str | None = None,
    process: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses = ["ts>=?"]
    params: list[Any] = [since_ms]
    if state:
        clauses.append("state=?")
        params.append(state.upper())
    if process:
        clauses.append("(name LIKE ? OR CAST(pid AS TEXT)=?)")
        params.extend([f"%{process}%", process])
    params.append(limit)
    return _rows(
        conn,
        "SELECT * FROM connection_samples WHERE "
        + " AND ".join(clauses)
        + " ORDER BY ts DESC, rx_bps DESC, tx_bps DESC LIMIT ?",
        params,
    )


def probes_since(
    conn: sqlite3.Connection, since_ms: int, anchor: str | None = None
) -> list[dict[str, Any]]:
    params: list[Any] = [since_ms]
    clause = "ts>=?"
    if anchor:
        clause += " AND anchor=?"
        params.append(anchor)
    return _rows(
        conn,
        f"SELECT * FROM probe_samples WHERE {clause} ORDER BY ts DESC, anchor, method",
        params,
    )


def latest_probes(
    conn: sqlite3.Connection, since_ms: int, anchor: str | None = None
) -> list[dict[str, Any]]:
    rows = probes_since(conn, since_ms, anchor)
    seen: set[tuple[str, str]] = set()
    latest: list[dict[str, Any]] = []
    for row in rows:
        key = (row["anchor"], row["method"])
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)
    return sorted(latest, key=lambda r: (r["scope"], r["anchor"], r["method"]))


def throughputs_since(
    conn: sqlite3.Connection, since_ms: int, anchor: str | None = None
) -> list[dict[str, Any]]:
    params: list[Any] = [since_ms]
    clause = "ts>=?"
    if anchor:
        clause += " AND anchor=?"
        params.append(anchor)
    return _rows(
        conn,
        f"SELECT * FROM throughput_samples WHERE {clause} ORDER BY ts DESC",
        params,
    )


def latest_throughputs(
    conn: sqlite3.Connection, since_ms: int, anchor: str | None = None
) -> list[dict[str, Any]]:
    rows = throughputs_since(conn, since_ms, anchor)
    seen: set[str] = set()
    latest: list[dict[str, Any]] = []
    for row in rows:
        key = f"{row['anchor']}/{row['backend']}"
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)
    return sorted(latest, key=lambda r: (r["scope"], r["anchor"], r["backend"]))


def events_since(conn: sqlite3.Connection, since_ms: int, limit: int = 20) -> list[dict[str, Any]]:
    return _rows(
        conn,
        "SELECT * FROM events WHERE ts>=? ORDER BY ts DESC LIMIT ?",
        (since_ms, limit),
    )


SERIES = {
    "cpu_pct": ("host_samples", "cpu_pct", ""),
    "mem_pct": ("host_samples", "mem_used * 100.0 / NULLIF(mem_total,0)", ""),
    "latency_ms": ("probe_samples", "latency_ms", "probe"),
    "loss_pct": ("probe_samples", "loss_pct", "probe"),
    "down_bps": ("throughput_samples", "down_bps", "throughput"),
    "up_bps": ("throughput_samples", "up_bps", "throughput"),
    "rssi_dbm": ("interface_samples", "rssi_dbm", "interface"),
}


def series(
    conn: sqlite3.Connection,
    metric: str,
    since_ms: int,
    scope: str | None = None,
    anchor: str | None = None,
    method: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    if metric not in SERIES:
        raise KeyError(f"unknown metric: {metric}")
    table, expression, kind = SERIES[metric]
    clauses = ["ts>=?"]
    params: list[Any] = [since_ms]
    if kind == "probe":
        if scope:
            clauses.append("scope=?")
            params.append(scope)
        if anchor:
            clauses.append("anchor=?")
            params.append(anchor)
        if method:
            clauses.append("method=?")
            params.append(method)
    elif kind == "throughput":
        if scope:
            clauses.append("scope=?")
            params.append(scope)
        if anchor:
            clauses.append("anchor=?")
            params.append(anchor)
    elif kind == "interface" and anchor:
        clauses.append("ifname=?")
        params.append(anchor)
    params.append(limit)
    rows = _rows(
        conn,
        f"SELECT ts, {expression} AS value FROM {table}"
        f" WHERE {' AND '.join(clauses)} ORDER BY ts DESC LIMIT ?",
        params,
    )
    return list(reversed(rows))


ROLLUP_TABLES = {"5m": "rollup_5m", "1h": "rollup_hourly"}


def _resolve_series(
    metric: str, anchor: str | None, method: str | None
) -> tuple[str | None, str | None]:
    kind = SERIES[metric][2]
    if kind == "probe":
        return anchor, method or "icmp"
    if kind == "throughput":
        return anchor or "networkquality", method or "networkquality"
    return anchor, method


def _raw_series_rows(
    conn: sqlite3.Connection,
    metric: str,
    since_ms: int,
    until_ms: int,
    scope: str | None,
    anchor: str | None,
    method: str | None,
) -> list[tuple[int, float]]:
    table, expression, kind = SERIES[metric]
    clauses = ["ts>=?", "ts<=?", f"({expression}) IS NOT NULL"]
    params: list[Any] = [since_ms, until_ms]
    if kind == "probe":
        if scope:
            clauses.append("scope=?")
            params.append(scope)
        if anchor:
            clauses.append("anchor=?")
            params.append(anchor)
        if method:
            clauses.append("method=?")
            params.append(method)
    elif kind == "throughput":
        if scope:
            clauses.append("scope=?")
            params.append(scope)
        if anchor:
            clauses.append("anchor=?")
            params.append(anchor)
        if method:
            clauses.append("backend=?")
            params.append(method)
    elif kind == "interface" and anchor:
        clauses.append("ifname=?")
        params.append(anchor)
    rows = _rows(
        conn,
        f"SELECT ts, {expression} AS value FROM {table}"
        f" WHERE {' AND '.join(clauses)} ORDER BY ts",
        params,
    )
    return [(int(row["ts"]), float(row["value"])) for row in rows if row["value"] is not None]


def _rollup_series_rows(
    conn: sqlite3.Connection,
    table: str,
    metric: str,
    since_ms: int,
    until_ms: int,
    scope: str | None,
    anchor: str | None,
    method: str | None,
) -> list[dict[str, Any]]:
    kind = SERIES[metric][2]
    clauses = ["metric=?", "bucket>=?", "bucket<=?"]
    params: list[Any] = [metric, since_ms, until_ms]
    if kind in ("probe", "throughput"):
        if scope:
            clauses.append("scope=?")
            params.append(scope)
        if anchor:
            clauses.append("anchor=?")
            params.append(anchor)
        if method:
            clauses.append("method=?")
            params.append(method)
    elif kind == "interface" and anchor:
        clauses.append("anchor=?")
        params.append(anchor)
    return _rows(
        conn,
        f"SELECT bucket, avg, min, max, n FROM {table}"
        f" WHERE {' AND '.join(clauses)} ORDER BY bucket",
        params,
    )


def _downsample_raw(
    rows: list[tuple[int, float]], since_ms: int, until_ms: int, max_points: int
) -> list[dict[str, Any]]:
    if not rows:
        return []
    if len(rows) <= max_points:
        return [
            {"ts": ts, "value": value, "min": value, "max": value, "n": 1}
            for ts, value in rows
        ]
    width = max(1.0, (until_ms - since_ms) / max_points)
    buckets: dict[int, list[float]] = {}
    for ts, value in rows:
        index = int((ts - since_ms) // width)
        bucket = buckets.get(index)
        if bucket is None:
            buckets[index] = [value, value, value, 1.0]
        else:
            bucket[0] += value
            bucket[1] = min(bucket[1], value)
            bucket[2] = max(bucket[2], value)
            bucket[3] += 1
    return [
        {
            "ts": int(since_ms + (index + 0.5) * width),
            "value": values[0] / values[3],
            "min": values[1],
            "max": values[2],
            "n": int(values[3]),
        }
        for index, values in sorted(buckets.items())
    ]


def _downsample_rollup(
    rows: list[dict[str, Any]], since_ms: int, until_ms: int, max_points: int
) -> list[dict[str, Any]]:
    clean = [
        row
        for row in rows
        if row["avg"] is not None and row["min"] is not None and row["max"] is not None
    ]
    if not clean:
        return []
    if len(clean) <= max_points:
        return [
            {
                "ts": int(row["bucket"]),
                "value": float(row["avg"]),
                "min": float(row["min"]),
                "max": float(row["max"]),
                "n": int(row["n"] or 0),
            }
            for row in clean
        ]
    width = max(1.0, (until_ms - since_ms) / max_points)
    buckets: dict[int, list[float]] = {}
    for row in clean:
        index = int((int(row["bucket"]) - since_ms) // width)
        n = float(row["n"] or 1)
        avg = float(row["avg"])
        low = float(row["min"])
        high = float(row["max"])
        bucket = buckets.get(index)
        if bucket is None:
            buckets[index] = [avg * n, low, high, n]
        else:
            bucket[0] += avg * n
            bucket[1] = min(bucket[1], low)
            bucket[2] = max(bucket[2], high)
            bucket[3] += n
    return [
        {
            "ts": int(since_ms + (index + 0.5) * width),
            "value": values[0] / values[3] if values[3] else None,
            "min": values[1],
            "max": values[2],
            "n": int(values[3]),
        }
        for index, values in sorted(buckets.items())
        if values[3]
    ]


def series_window(
    conn: sqlite3.Connection,
    metric: str,
    since_ms: int,
    until_ms: int,
    scope: str | None = None,
    anchor: str | None = None,
    method: str | None = None,
    max_points: int = 300,
    resolution: str = "auto",
    raw_cutoff_ms: int = 0,
    five_cutoff_ms: int = 0,
    hourly_cutoff_ms: int = 0,
) -> dict[str, Any]:
    """Return a downsampled window, using raw, 5-minute or hourly data.

    `resolution` is `auto`, `raw`, `5m` or `1h`. Auto picks raw while the
    window is inside raw retention, then 5-minute, then hourly, and falls back
    to a coarser source if the preferred one is empty.
    """
    if metric not in SERIES:
        raise KeyError(f"unknown metric: {metric}")
    if resolution not in ("auto", "raw", "5m", "1h"):
        raise ValueError(f"unknown resolution: {resolution}")
    anchor, method = _resolve_series(metric, anchor, method)
    max_points = max(10, int(max_points))

    if resolution == "auto":
        if since_ms >= raw_cutoff_ms:
            candidates = ["raw", "5m", "1h"]
        elif since_ms >= five_cutoff_ms:
            candidates = ["5m", "1h", "raw"]
        else:
            candidates = ["1h", "5m", "raw"]
    else:
        candidates = [resolution]

    actual = candidates[0]
    points: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate == "raw":
            rows = _raw_series_rows(
                conn, metric, since_ms, until_ms, scope, anchor, method
            )
            points = _downsample_raw(rows, since_ms, until_ms, max_points)
        else:
            rows = _rollup_series_rows(
                conn,
                ROLLUP_TABLES[candidate],
                metric,
                since_ms,
                until_ms,
                scope,
                anchor,
                method,
            )
            points = _downsample_rollup(rows, since_ms, until_ms, max_points)
        if points:
            actual = candidate
            break
    return {"resolution": actual, "points": points}


def status_snapshot(conn: sqlite3.Connection, since_ms: int) -> dict[str, Any]:
    interfaces = latest_interfaces(conn)
    active = next((row for row in interfaces if row["is_default"]), None)
    if active is None:
        active = next((row for row in interfaces if row["is_up"]), None)
    host = latest_host(conn)
    processes = processes_since(conn, since_ms, "cpu", 12)
    network = processes_since(conn, since_ms, "rx", 8)
    connections = connections_since(conn, since_ms, limit=25)
    probes = latest_probes(conn, since_ms)
    throughputs = latest_throughputs(conn, since_ms)
    events = events_since(conn, since_ms, 12)
    return {
        "generated_at": since_ms,
        "host": host,
        "interfaces": interfaces,
        "active": active,
        "processes": processes,
        "network_processes": network,
        "connections": connections,
        "probes": probes,
        "throughputs": throughputs,
        "events": events,
        "counts": {
            "interfaces": len(interfaces),
            "processes": len(processes),
            "connections": len(connections),
            "probes": len(probes),
            "throughputs": len(throughputs),
        },
    }
