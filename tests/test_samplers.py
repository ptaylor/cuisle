from __future__ import annotations

import socket
from types import SimpleNamespace

from conftest import FakeProcess, FakePsutil, FakeRunner, addr, fixture_text

from cuisle.model import ProcessSample
from cuisle.samplers.connections import ConnectionSampler
from cuisle.samplers.interfaces import is_expensive, on_battery, sample_interfaces
from cuisle.samplers.processes import ProcessSampler, select_top


def test_select_top_deduplicates() -> None:
    rows = [
        ProcessSample(ts=1, pid=1, name="cpu", username=None, cpu_pct=90, rss_bytes=1, threads=1, status="running"),
        ProcessSample(ts=1, pid=2, name="mem", username=None, cpu_pct=1, rss_bytes=999, threads=1, status="running"),
        ProcessSample(ts=1, pid=3, name="net", username=None, cpu_pct=2, rss_bytes=2, threads=1, status="running", rx_bps=1000, tx_bps=2000),
    ]
    selected = select_top(rows, 1)
    assert {row.pid for row in selected} == {1, 2, 3}


def test_process_sampler() -> None:
    ps = FakePsutil(
        processes=[
            FakeProcess(1, "cpu-hog", cpu=10.0, rss=100),
            FakeProcess(2, "mem-hog", cpu=2.0, rss=999_999),
        ],
        cpu=12.5,
    )
    host, rows = ProcessSampler(top_n=1, psutil_module=ps).sample(1000, {1: (1000.0, 2000.0)})
    assert host.cpu_pct == 12.5
    assert host.process_count == 2
    assert {row.pid for row in rows} == {1, 2}
    assert next(row for row in rows if row.pid == 1).rx_bps == 1000.0


def test_connection_sampler_delta() -> None:
    tcp = fixture_text("netstat_tcp.txt")
    udp = fixture_text("netstat_udp.txt")
    runner = FakeRunner(
        {
            ("netstat", "-anv", "-p", "tcp"): tcp,
            ("netstat", "-anv", "-p", "udp"): udp,
        }
    )
    ps = FakePsutil(
        addrs={"en0": [addr(socket.AF_INET, "192.168.100.20")]},
        processes=[FakeProcess(2499, "browser")],
    )
    sampler = ConnectionSampler(runner, psutil_module=ps)
    first, _, _ = sampler.sample(1000)
    assert first
    runner.responses[("netstat", "-anv", "-p", "tcp")] = tcp.replace("171548", "172548", 1)
    second, net, resets = sampler.sample(2000)
    assert net[2499][0] > 0
    assert any(row.pid == 2499 and row.rx_bps > 0 for row in second)
    assert all(row.interface in (None, "en0") for row in second)
    assert resets == []


def test_sample_interfaces() -> None:
    runner = FakeRunner(
        {
            ("route", "-n", "get", "default"): fixture_text("route_default.txt"),
            ("networksetup", "-listallhardwareports"): fixture_text("hardware_ports.txt"),
            ("scutil", "--nwi"): fixture_text("scutil_nwi.txt"),
            ("netstat", "-ib"): fixture_text("netstat_ib.txt"),
        }
    )
    ps = FakePsutil(
        addrs={
            "en0": [
                addr(socket.AF_INET, "192.168.100.20"),
                addr(socket.AF_INET6, "fe80::1%en0"),
            ],
            "en1": [],
            "lo0": [addr(socket.AF_INET, "127.0.0.1")],
        },
        stats={
            "en0": SimpleNamespace(isup=True, speed=0),
            "en1": SimpleNamespace(isup=True, speed=0),
        },
    )
    wifi = {
        "ssid": "example",
        "bssid": "aa:bb:cc:dd:ee:ff",
        "rssi_dbm": -57,
        "noise_dbm": -96,
        "channel": 44,
        "band": "5 GHz",
        "width_mhz": 80,
        "tx_rate_mbps": 866.0,
    }
    samples, active = sample_interfaces(
        runner, 1000, psutil_module=ps, wifi_fn=lambda: wifi
    )
    assert active.ifname == "en0"
    assert active.kind == "wifi"
    assert active.gateway == "192.168.100.1"
    assert active.ssid == "example"
    en0 = next(sample for sample in samples if sample.ifname == "en0")
    assert en0.is_default
    assert en0.rx_bytes and en0.rx_bytes > 0
    assert en0.ssid == "example"
    assert en0.tx_rate_mbps == 866.0
    assert not next((sample for sample in samples if sample.ifname == "lo0"), None)


def test_power_helpers() -> None:
    assert on_battery(FakeRunner({"pmset": "Now drawing from 'Battery Power'"}))
    assert not on_battery(FakeRunner({"pmset": "Now drawing from 'AC Power'"}))
    assert is_expensive(
        FakeRunner({"nettop": ",interface,bytes_in,bytes_out,\nbrowser.1,,1,2,\n"})
    )
    assert not is_expensive(FakeRunner({"nettop": ",interface,bytes_in,bytes_out,\n"}))
