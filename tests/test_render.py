from __future__ import annotations

import time

from cuisle import db, render
from cuisle.config import Config


def test_render_status(sample_db: Config) -> None:
    conn = db.connect(sample_db.db_path, readonly=True)
    try:
        snapshot = db.status_snapshot(conn, int(time.time() * 1000) - 3_600_000)
    finally:
        conn.close()
    text = render.render_status(snapshot)
    assert "ACTIVE LINK" in text
    assert "NETWORK HEALTH" in text
    assert "THROUGHPUT" in text
    assert "en0" in text


def test_render_empty() -> None:
    assert "No samples" in render.render_status({})


def test_render_doctor() -> None:
    text = render.render_doctor([{"name": "macOS", "status": "ok", "detail": "Darwin"}])
    assert "macOS" in text
    assert "Darwin" in text


def test_render_history() -> None:
    text = render.render_history(
        [{"ts": 1_700_000_000_000, "value": 12.5, "min": 10.0, "max": 15.0, "n": 3}],
        "cpu_pct",
        "5m",
    )
    assert "CPU_PCT" in text
    assert "5m" in text
    assert "12.5%" in text
    assert "MIN" in text
    assert "MAX" in text
