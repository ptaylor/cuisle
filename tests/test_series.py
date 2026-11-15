from __future__ import annotations

import time

from cuisle import db
from cuisle.config import Config
from cuisle.model import HostSample, ProbeSample, ThroughputSample

DAY = 86_400_000


def now_ms() -> int:
    return int(time.time() * 1000)


def test_raw_downsampling(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path)
    now = now_ms()
    for i in range(100):
        db.insert_host(
            conn,
            HostSample(now - 100_000 + i * 1000, float(i), 1, 2, 0.0, 1),
        )
    conn.commit()
    result = db.series_window(
        conn,
        "cpu_pct",
        now - 3_600_000,
        now,
        max_points=10,
        raw_cutoff_ms=now - 7 * DAY,
        five_cutoff_ms=now - 90 * DAY,
        hourly_cutoff_ms=now - 365 * DAY,
    )
    assert result["resolution"] == "raw"
    assert 0 < len(result["points"]) <= 10
    assert all({"ts", "value", "min", "max", "n"} <= set(point) for point in result["points"])


def test_rollup_selection(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path)
    now = now_ms()
    conn.execute(
        "INSERT OR REPLACE INTO rollup_5m"
        "(bucket, metric, scope, anchor, method, avg, min, max, n)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (now - 30 * DAY, "cpu_pct", "", "", "", 5.0, 1.0, 9.0, 10),
    )
    conn.execute(
        "INSERT OR REPLACE INTO rollup_hourly"
        "(bucket, metric, scope, anchor, method, avg, min, max, n)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (now - 200 * DAY, "cpu_pct", "", "", "", 7.0, 2.0, 11.0, 20),
    )
    conn.commit()
    five = db.series_window(
        conn,
        "cpu_pct",
        now - 40 * DAY,
        now,
        raw_cutoff_ms=now - 7 * DAY,
        five_cutoff_ms=now - 90 * DAY,
        hourly_cutoff_ms=now - 365 * DAY,
    )
    assert five["resolution"] == "5m"
    assert five["points"][0]["value"] == 5.0
    hourly = db.series_window(
        conn,
        "cpu_pct",
        now - 300 * DAY,
        now,
        raw_cutoff_ms=now - 7 * DAY,
        five_cutoff_ms=now - 90 * DAY,
        hourly_cutoff_ms=now - 365 * DAY,
    )
    assert hourly["resolution"] == "1h"
    assert hourly["points"][0]["value"] == 7.0


def test_throughput_filter(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path)
    now = now_ms()
    db.insert_throughputs(
        conn,
        [
            ThroughputSample(
                now - 1000, "networkquality", "capacity", "networkquality", True,
                down_bps=100.0,
            ),
            ThroughputSample(
                now - 1000, "eu", "europe", "http", True, down_bps=200.0,
            ),
        ],
    )
    conn.commit()
    result = db.series_window(
        conn,
        "down_bps",
        now - 3_600_000,
        now,
        anchor="networkquality",
        method="networkquality",
        max_points=10,
        raw_cutoff_ms=now - 7 * DAY,
        five_cutoff_ms=now - 90 * DAY,
        hourly_cutoff_ms=now - 365 * DAY,
    )
    assert result["resolution"] == "raw"
    assert result["points"]
    assert all(point["value"] == 100.0 for point in result["points"])


def test_probe_filter(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path)
    now = now_ms()
    db.insert_probes(
        conn,
        [
            ProbeSample(now - 1000, "gw", "lan", "icmp", True, latency_ms=10.0),
            ProbeSample(now - 1000, "gw", "lan", "tcp", True, latency_ms=20.0),
        ],
    )
    conn.commit()
    result = db.series_window(
        conn,
        "latency_ms",
        now - 3_600_000,
        now,
        anchor="gw",
        method="icmp",
        max_points=10,
        raw_cutoff_ms=now - 7 * DAY,
        five_cutoff_ms=now - 90 * DAY,
        hourly_cutoff_ms=now - 365 * DAY,
    )
    assert result["points"]
    assert all(point["value"] == 10.0 for point in result["points"])
