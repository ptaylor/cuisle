"""Roll raw samples up into 5-minute and hourly buckets, then prune."""

from __future__ import annotations

import sqlite3
from typing import Any

from cuisle.config import RetentionConfig

FIVE_MINUTES_MS = 5 * 60 * 1000
HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000

RAW_TABLES = (
    "host_samples",
    "process_samples",
    "connection_samples",
    "interface_samples",
    "probe_samples",
    "throughput_samples",
)


def _rollup_sql(table: str, bucket_ms: int) -> str:
    statements = [
        f"""
        INSERT OR REPLACE INTO {table}
        (bucket, metric, scope, anchor, method, avg, min, max, n)
        SELECT (ts / {bucket_ms}) * {bucket_ms}, 'cpu_pct', '', '', '',
               avg(cpu_pct), min(cpu_pct), max(cpu_pct), count(*)
        FROM host_samples GROUP BY 1
        """,
        f"""
        INSERT OR REPLACE INTO {table}
        (bucket, metric, scope, anchor, method, avg, min, max, n)
        SELECT (ts / {bucket_ms}) * {bucket_ms}, 'mem_pct', '', '', '',
               avg(mem_used * 100.0 / NULLIF(mem_total, 0)),
               min(mem_used * 100.0 / NULLIF(mem_total, 0)),
               max(mem_used * 100.0 / NULLIF(mem_total, 0)), count(*)
        FROM host_samples GROUP BY 1
        """,
        f"""
        INSERT OR REPLACE INTO {table}
        (bucket, metric, scope, anchor, method, avg, min, max, n)
        SELECT (ts / {bucket_ms}) * {bucket_ms}, 'latency_ms', scope, anchor, method,
               avg(latency_ms), min(latency_ms), max(latency_ms), count(*)
        FROM probe_samples WHERE latency_ms IS NOT NULL
        GROUP BY 1, 3, 4, 5
        """,
        f"""
        INSERT OR REPLACE INTO {table}
        (bucket, metric, scope, anchor, method, avg, min, max, n)
        SELECT (ts / {bucket_ms}) * {bucket_ms}, 'loss_pct', scope, anchor, method,
               avg(loss_pct), min(loss_pct), max(loss_pct), count(*)
        FROM probe_samples WHERE loss_pct IS NOT NULL
        GROUP BY 1, 3, 4, 5
        """,
        f"""
        INSERT OR REPLACE INTO {table}
        (bucket, metric, scope, anchor, method, avg, min, max, n)
        SELECT (ts / {bucket_ms}) * {bucket_ms}, 'down_bps', scope, anchor, backend,
               avg(down_bps), min(down_bps), max(down_bps), count(*)
        FROM throughput_samples WHERE down_bps IS NOT NULL
        GROUP BY 1, 3, 4, 5
        """,
        f"""
        INSERT OR REPLACE INTO {table}
        (bucket, metric, scope, anchor, method, avg, min, max, n)
        SELECT (ts / {bucket_ms}) * {bucket_ms}, 'up_bps', scope, anchor, backend,
               avg(up_bps), min(up_bps), max(up_bps), count(*)
        FROM throughput_samples WHERE up_bps IS NOT NULL
        GROUP BY 1, 3, 4, 5
        """,
        f"""
        INSERT OR REPLACE INTO {table}
        (bucket, metric, scope, anchor, method, avg, min, max, n)
        SELECT (ts / {bucket_ms}) * {bucket_ms}, 'rssi_dbm', '', ifname, '',
               avg(rssi_dbm), min(rssi_dbm), max(rssi_dbm), count(*)
        FROM interface_samples WHERE rssi_dbm IS NOT NULL
        GROUP BY 1, 4
        """,
    ]
    return ";\n".join(statements)


def rollup(conn: sqlite3.Connection) -> None:
    conn.executescript(_rollup_sql("rollup_5m", FIVE_MINUTES_MS))
    conn.executescript(_rollup_sql("rollup_hourly", HOUR_MS))
    conn.commit()


def prune(conn: sqlite3.Connection, retention: RetentionConfig, now_ms: int) -> None:
    raw_cutoff = now_ms - retention.raw_days * DAY_MS
    five_cutoff = now_ms - retention.five_minute_days * DAY_MS
    hourly_cutoff = now_ms - retention.hourly_days * DAY_MS
    for table in RAW_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE ts < ?", (raw_cutoff,))
    conn.execute("DELETE FROM events WHERE ts < ?", (hourly_cutoff,))
    conn.execute("DELETE FROM rollup_5m WHERE bucket < ?", (five_cutoff,))
    conn.execute("DELETE FROM rollup_hourly WHERE bucket < ?", (hourly_cutoff,))
    conn.execute("PRAGMA optimize")
    conn.commit()


def maintenance(conn: sqlite3.Connection, retention: RetentionConfig, now_ms: int) -> None:
    rollup(conn)
    prune(conn, retention, now_ms)


def rollup_count(conn: sqlite3.Connection, table: str = "rollup_5m") -> int:
    row: Any = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()
    return int(row["n"]) if row else 0
