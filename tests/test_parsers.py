from __future__ import annotations

import json

import pytest
from conftest import fixture_text

from cuisle.backends import parse_iperf3_json, parse_speedtest_json
from cuisle.networkquality import parse_networkquality
from cuisle.probes import parse_dig, parse_ping
from cuisle.samplers.connections import parse_address, parse_netstat
from cuisle.samplers.interfaces import (
    classify_interface,
    classify_port,
    parse_hardware_ports,
    parse_netstat_ib,
    parse_route_default,
    parse_scutil_nwi,
)
from cuisle.util import format_bps, format_bytes, format_ms, format_pct, parse_since


def test_parse_address() -> None:
    assert parse_address("192.168.1.2.443") == ("192.168.1.2", 443)
    assert parse_address("fe80::1%en0.49662") == ("fe80::1%en0", 49662)
    assert parse_address("*.*") == ("*", None)
    assert parse_address("*.1234") == ("*", 1234)
    assert parse_address("no-port") == ("no-port", None)


def test_parse_netstat_tcp() -> None:
    rows = parse_netstat(fixture_text("netstat_tcp.txt"))
    assert len(rows) >= 5
    first = rows[0]
    assert first["proto"] == "tcp4"
    assert first["local_addr"] == "192.168.100.20"
    assert first["local_port"] == 49930
    assert first["remote_addr"] == "203.0.113.11111"
    assert first["remote_port"] == 443
    assert first["state"] == "ESTABLISHED"
    assert first["pid"] == 2499


def test_parse_netstat_udp() -> None:
    rows = parse_netstat(fixture_text("netstat_udp.txt"))
    assert rows
    first = rows[0]
    assert first["proto"] == "udp4"
    assert first["local_addr"] == "*"
    assert first["local_port"] == 49272
    assert first["remote_addr"] == "*"
    assert first["state"] == "-"
    assert first["pid"] == 828


def test_parse_route_and_ports() -> None:
    route = parse_route_default(fixture_text("route_default.txt"))
    assert route == {"interface": "en0", "gateway": "192.168.100.1"}
    ports = parse_hardware_ports(fixture_text("hardware_ports.txt"))
    assert ports["en0"] == "Wi-Fi"
    assert ports["bridge0"] == "Thunderbolt Bridge"


def test_parse_netstat_ib() -> None:
    counters = parse_netstat_ib(fixture_text("netstat_ib.txt"))
    assert counters["en0"]["ibytes"] > 0
    assert counters["en0"]["ierrs"] == 0
    assert counters["lo0"]["ipkts"] > 0


def test_parse_scutil_nwi() -> None:
    nwi = parse_scutil_nwi(fixture_text("scutil_nwi.txt"))
    assert nwi["en0"]["addresses"] == ["192.168.100.20"]
    assert "Reachable" in nwi["en0"]["reach"]


def test_classification() -> None:
    assert classify_port("Wi-Fi") == "wifi"
    assert classify_port("USB 10/100/1000 LAN") == "ethernet"
    assert classify_port("Thunderbolt Bridge") == "ethernet"
    assert classify_port("VPN (utun4)") == "vpn"
    assert classify_interface("utun4", None) == "vpn"
    assert classify_interface("awdl0", None) == "wifi"


def test_parse_ping_and_dig() -> None:
    ping = parse_ping(fixture_text("ping.txt"))
    assert ping["loss_pct"] == 0.0
    assert ping["latency_ms"] is not None
    dig = parse_dig(fixture_text("dig.txt"))
    assert dig["status"] == "NOERROR"
    assert dig["latency_ms"] == 32.0


def test_parse_networkquality() -> None:
    data = json.loads(fixture_text("networkquality.json"))
    parsed = parse_networkquality(data)
    assert parsed["down_bps"] == 80377312.0
    assert parsed["up_bps"] == 26294538.0
    assert parsed["latency_ms"] is not None
    assert parsed["server"]


def test_parse_speedtest() -> None:
    parsed = parse_speedtest_json(json.loads(fixture_text("speedtest.json")))
    assert parsed["down_bps"] == 500_000_000.0
    assert parsed["up_bps"] == 48_000_000.0
    assert parsed["latency_ms"] == 18.4
    assert parsed["server"] == "Example Server"
    assert parsed["interface"] == "en0"


def test_parse_iperf3() -> None:
    data = json.loads(fixture_text("iperf3.json"))
    both = parse_iperf3_json(data, "both")
    assert both["up_bps"] == 48_000_000.0
    assert both["down_bps"] == 47_000_000.0
    up = parse_iperf3_json(data, "up")
    assert up["down_bps"] is None
    down = parse_iperf3_json(data, "down")
    assert down["up_bps"] is None


def test_parse_since() -> None:
    now = 1_000_000_000
    assert parse_since("24h", now, 0) == now - 86_400_000
    assert parse_since("7d", now, 0) == now - 604_800_000
    assert parse_since("30m", now, 0) == now - 1_800_000
    assert parse_since("1y", now, 0) == now - 31_536_000_000
    with pytest.raises(ValueError):
        parse_since("nonsense", now, 0)


def test_formatters() -> None:
    assert format_bytes(1024) == "1.0 KiB"
    assert format_bps(1_500_000) == "1.5 Mbps"
    assert format_ms(12.34) == "12.3 ms"
    assert format_pct(12.34) == "12.3%"
