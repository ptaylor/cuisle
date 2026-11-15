from __future__ import annotations

import time

from cuisle import db
from cuisle.config import Config, RetentionConfig
from cuisle.rollup import prune, rollup, rollup_count


def test_status_snapshot(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path, readonly=True)
    try:
        snapshot = db.status_snapshot(conn, int(time.time() * 1000) - 3_600_000)
    finally:
        conn.close()
    assert snapshot["host"]["cpu_pct"] == 12.5
    assert snapshot["active"]["ifname"] == "en0"
    assert snapshot["probes"][0]["anchor"] == "test"
    assert snapshot["throughputs"][0]["down_bps"] == 100_000_000
    assert snapshot["connections"][0]["state"] == "ESTABLISHED"


def test_series(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path, readonly=True)
    try:
        points = db.series(conn, "cpu_pct", int(time.time() * 1000) - 3_600_000)
    finally:
        conn.close()
    assert points and points[0]["value"] == 12.5


def test_processes_since(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path, readonly=True)
    try:
        rows = db.processes_since(conn, int(time.time() * 1000) - 3_600_000, "mem", 10)
    finally:
        conn.close()
    assert rows[0]["name"] == "browser"
    assert rows[0]["rx_bps"] == 1000


def test_rollup_and_prune(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path)
    try:
        rollup(conn)
        assert rollup_count(conn) > 0
        prune(
            conn,
            RetentionConfig(raw_days=0, five_minute_days=0, hourly_days=0),
            int(time.time() * 1000) + 1000,
        )
        assert db.latest_host(conn) is None
    finally:
        conn.close()
