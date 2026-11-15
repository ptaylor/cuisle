from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from conftest import FakeRunner, fixture_text

from cuisle.backends import (
    http_backend,
    run_all_throughput,
    run_iperf3_backend,
    run_speedtest_backend,
)
from cuisle.config import Anchor, Config, GeneralConfig, ThroughputConfig
from cuisle.networkquality import run_networkquality


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"x" * 4096
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, fmt, *args):
        return


def local_config(tmp_path: Path, anchor: Anchor) -> Config:
    return Config(
        path=tmp_path / "config.toml",
        general=GeneralConfig(data_dir=tmp_path / "data", log_dir=tmp_path / "logs"),
        throughput=ThroughputConfig(
            download_bytes=2048, upload_bytes=512, timeout_seconds=5
        ),
        anchors=[anchor],
    )


def test_http_backend_roundtrip(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    anchor = Anchor(
        name="local",
        scope="lan",
        download_url=f"http://127.0.0.1:{port}/down",
        upload_url=f"http://127.0.0.1:{port}/up",
    )
    config = local_config(tmp_path, anchor)
    try:
        sample = http_backend(anchor, config, 1000, "lo0")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert sample.success
    assert sample.down_bps and sample.down_bps > 0
    assert sample.up_bps and sample.up_bps > 0
    assert sample.bytes_down == 2048
    assert sample.bytes_up == 512
    assert sample.backend == "http"


def test_run_all_throughput_skips_health_only(tmp_path: Path) -> None:
    anchor = Anchor(name="health", scope="country", host="example.test", health=("tcp",))
    config = local_config(tmp_path, anchor)
    assert run_all_throughput(config, FakeRunner(), 1000, "en0") == []


def test_networkquality_runner() -> None:
    sample = run_networkquality(
        FakeRunner({"networkQuality": fixture_text("networkquality.json")}),
        ts=1000,
        timeout=30,
        interface="en0",
    )
    assert sample.success
    assert sample.down_bps == 80377312.0
    assert sample.up_bps == 26294538.0
    assert sample.backend == "networkquality"


def test_speedtest_runner() -> None:
    anchor = Anchor(
        name="ookla",
        scope="europe",
        backend="speedtest",
        server_id=12345,
    )
    sample = run_speedtest_backend(
        anchor,
        FakeRunner({"speedtest": fixture_text("speedtest.json")}),
        ts=1000,
        interface="en0",
    )
    assert sample.success
    assert sample.down_bps == 500_000_000.0
    assert sample.up_bps == 48_000_000.0
    assert sample.server == "Example Server"


def test_iperf3_runner() -> None:
    anchor = Anchor(
        name="iperf",
        scope="international",
        backend="iperf3",
        host="iperf.test",
        port=5201,
        direction="both",
    )
    sample = run_iperf3_backend(
        anchor,
        FakeRunner({"iperf3": fixture_text("iperf3.json")}),
        ts=1000,
        interface="en0",
    )
    assert sample.success
    assert sample.down_bps == 47_000_000.0
    assert sample.up_bps == 48_000_000.0
    assert sample.server == "iperf.test:5201"
