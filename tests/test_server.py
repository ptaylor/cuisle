from __future__ import annotations

import json
import threading
import urllib.request

from cuisle.config import Config
from cuisle.server import make_server


def test_api_and_assets(sample_db: Config) -> None:
    sample_db.general.dashboard_port = 0
    server = make_server(sample_db)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with urllib.request.urlopen(f"{base}/api/status", timeout=2) as response:
            status = json.load(response)
        assert status["active"]["ifname"] == "en0"
        assert status["host"]["cpu_pct"] == 12.5

        with urllib.request.urlopen(
            f"{base}/api/series?metric=cpu_pct&since=1h", timeout=2
        ) as response:
            series = json.load(response)
        assert series["points"]
        assert series["resolution"] == "raw"
        assert series["window"]["since"] < series["window"]["until"]
        assert {"ts", "value", "min", "max", "n"} <= set(series["points"][0])

        with urllib.request.urlopen(f"{base}/", timeout=2) as response:
            page = response.read().decode("utf-8")
        assert "Cuisle" in page
        assert "/icon.svg" in page

        with urllib.request.urlopen(f"{base}/icon.svg", timeout=2) as response:
            assert b"<svg" in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
