from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cuisle.config import Anchor, Config, GeneralConfig
from cuisle.runner import Result

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeRunner:
    def __init__(self, responses: dict[object, object] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, timeout=10.0, input=None, env=None):
        args = tuple(str(a) for a in argv)
        self.calls.append(args)
        value = self.responses.get(args)
        if value is None:
            value = self.responses.get(args[0])
        if value is None:
            return Result(args, 127, "", "not found", 0.0, "not found")
        if callable(value):
            value = value(args)
        if isinstance(value, Result):
            return value
        return Result(args, 0, str(value), "", 0.0)


class FakeProcess:
    def __init__(
        self,
        pid: int,
        name: str = "process",
        cpu: float = 1.0,
        rss: int = 1024,
        threads: int = 1,
        status: str = "running",
        user: str = "paul",
    ) -> None:
        self.pid = pid
        self.info = {"pid": pid}
        self._name = name
        self._cpu = cpu
        self._rss = rss
        self._threads = threads
        self._status = status
        self._user = user

    def name(self):
        return self._name

    def username(self):
        return self._user

    def cpu_percent(self, interval=None):
        return self._cpu

    def memory_info(self):
        return SimpleNamespace(rss=self._rss)

    def num_threads(self):
        return self._threads

    def status(self):
        return self._status

    def create_time(self):
        return 1_700_000_000.0


def addr(family, address):
    return SimpleNamespace(family=family, address=address)


class FakePsutil:
    Error = Exception

    def __init__(
        self,
        processes=None,
        addrs=None,
        stats=None,
        cpu: float = 12.5,
        mem_used: int = 8 << 30,
        mem_total: int = 16 << 30,
    ) -> None:
        self.processes = processes or []
        self.addrs = addrs or {}
        self.stats = stats or {}
        self.cpu = cpu
        self.mem_used = mem_used
        self.mem_total = mem_total

    def process_iter(self, attrs=None):
        return list(self.processes)

    def Process(self, pid):
        for proc in self.processes:
            if proc.pid == pid:
                return proc
        raise KeyError(pid)

    def cpu_percent(self, interval=None):
        return self.cpu

    def virtual_memory(self):
        return SimpleNamespace(used=self.mem_used, total=self.mem_total)

    def pids(self):
        return [proc.pid for proc in self.processes]

    def net_if_addrs(self):
        return self.addrs

    def net_if_stats(self):
        return self.stats


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        path=tmp_path / "config.toml",
        general=GeneralConfig(data_dir=tmp_path / "data", log_dir=tmp_path / "logs"),
        anchors=[
            Anchor(
                name="test",
                scope="country",
                host="example.test",
                port=443,
                url="https://example.test/",
                health=("dns", "tcp", "tls", "http"),
            )
        ],
    )


@pytest.fixture
def sample_db(config: Config) -> Config:
    from cuisle import db
    from cuisle.model import (
        ConnectionSample,
        EventSample,
        HostSample,
        InterfaceSample,
        ProbeSample,
        ProcessSample,
        ThroughputSample,
    )

    config.data_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(config.db_path)
    db.init_db(conn)
    now = int(time.time() * 1000)
    db.insert_host(conn, HostSample(now, 12.5, 8 << 30, 16 << 30, 1.5, 300))
    db.insert_interfaces(
        conn,
        [
            InterfaceSample(
                ts=now,
                ifname="en0",
                kind="wifi",
                is_up=True,
                is_default=True,
                ipv4="192.168.100.20",
                gateway="192.168.100.1",
                ssid="example",
                rssi_dbm=-57,
                noise_dbm=-96,
                channel=44,
                band="5 GHz",
                width_mhz=80,
                tx_rate_mbps=866,
                rx_bytes=1234,
                tx_bytes=567,
            )
        ],
    )
    db.insert_processes(
        conn,
        [
            ProcessSample(
                ts=now,
                pid=1,
                name="browser",
                username="paul",
                cpu_pct=10.0,
                rss_bytes=100 << 20,
                threads=20,
                status="running",
                rx_bps=1000,
                tx_bps=200,
            )
        ],
    )
    db.insert_connections(
        conn,
        [
            ConnectionSample(
                ts=now,
                pid=1,
                name="browser",
                proto="tcp4",
                local_addr="192.168.100.20",
                local_port=50000,
                remote_addr="203.0.113.10",
                remote_port=443,
                state="ESTABLISHED",
                rx_bytes=1000,
                tx_bytes=500,
                rx_bps=100,
                tx_bps=50,
                interface="en0",
            )
        ],
    )
    db.insert_probes(
        conn,
        [
            ProbeSample(
                ts=now,
                anchor="test",
                scope="country",
                method="icmp",
                success=True,
                latency_ms=12.0,
                loss_pct=0.0,
                status="ok",
                interface="en0",
            )
        ],
    )
    db.insert_throughputs(
        conn,
        [
            ThroughputSample(
                ts=now,
                anchor="test",
                scope="country",
                backend="http",
                success=True,
                down_bps=100_000_000,
                up_bps=20_000_000,
                server="example.test",
                interface="en0",
            )
        ],
    )
    db.insert_event(conn, EventSample(now, "start", "test"))
    conn.commit()
    conn.close()
    return config


__all__ = [
    "FakeProcess",
    "FakePsutil",
    "FakeRunner",
    "addr",
    "fixture_text",
]
