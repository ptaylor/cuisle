"""Interface, route and optional Wi-Fi sampling."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import psutil

from cuisle.model import ActiveLink, InterfaceSample
from cuisle.runner import Runner

BANDS = {1: "2.4 GHz", 2: "5 GHz", 3: "6 GHz"}
WIDTHS = {1: 20, 2: 40, 3: 80, 4: 160}


def parse_route_default(text: str) -> dict[str, str | None]:
    return {
        "interface": _first(r"interface:\s*(\S+)", text),
        "gateway": _first(r"gateway:\s*(\S+)", text),
    }


def parse_hardware_ports(text: str) -> dict[str, str]:
    ports: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"Hardware Port:\s*(.+)", line.strip())
        if match:
            current = match.group(1).strip()
            continue
        match = re.match(r"Device:\s*(\S+)", line.strip())
        if match and current:
            ports[match.group(1)] = current
            current = None
    return ports


def parse_netstat_ib(text: str) -> dict[str, dict[str, int]]:
    counters: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 10 or not fields[2].startswith("<Link#"):
            continue
        try:
            if len(fields) >= 11:
                ipkts, ierrs, ibytes = int(fields[4]), int(fields[5]), int(fields[6])
                opkts, oerrs, obytes = int(fields[7]), int(fields[8]), int(fields[9])
                collisions = int(fields[10])
            else:
                ipkts, ierrs, ibytes = int(fields[3]), int(fields[4]), int(fields[5])
                opkts, oerrs, obytes = int(fields[6]), int(fields[7]), int(fields[8])
                collisions = int(fields[9])
        except (ValueError, IndexError):
            continue
        counters[fields[0]] = {
            "ipkts": ipkts,
            "ierrs": ierrs,
            "ibytes": ibytes,
            "opkts": opkts,
            "oerrs": oerrs,
            "obytes": obytes,
            "collisions": collisions,
        }
    return counters


def parse_scutil_nwi(text: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^\s*(\w+)\s*:\s*flags", line)
        if match:
            current = match.group(1)
            result[current] = {"addresses": [], "reach": None}
            continue
        if current is None:
            continue
        match = re.match(r"^\s+address\s*:\s*(\S+)", line)
        if match:
            result[current]["addresses"].append(match.group(1))
            continue
        match = re.match(r"^\s+reach\s*:\s*(.+)$", line)
        if match:
            result[current]["reach"] = match.group(1).strip()
    return result


def classify_port(port_name: str) -> str:
    name = port_name.lower()
    if "wi-fi" in name or "airport" in name:
        return "wifi"
    if "ethernet" in name or " lan" in f" {name}" or "thunderbolt" in name:
        return "ethernet"
    if "vpn" in name:
        return "vpn"
    if "bridge" in name:
        return "bridge"
    return "other"


def classify_interface(ifname: str, port_name: str | None) -> str:
    if ifname.startswith("utun"):
        return "vpn"
    if ifname.startswith("bridge"):
        return "bridge"
    if ifname.startswith(("awdl", "llw")):
        return "wifi"
    return classify_port(port_name or ifname)


def wifi_snapshot() -> dict[str, Any] | None:
    """Read the active Wi-Fi link through CoreWLAN, if the optional extra exists."""
    try:
        import CoreWLAN  # type: ignore
    except ImportError:
        return None
    try:
        client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
        interface = client.interface()
        if interface is None:
            return None
        channel = interface.channel()
        rssi = int(interface.rssiValue() or 0)
        noise = int(interface.noiseValue() or 0)
        rate = float(interface.transmitRate() or 0)
        band_value = int(channel.channelBand()) if channel else 0
        width_value = int(channel.channelWidth()) if channel else 0
        return {
            "ssid": interface.ssid(),
            "bssid": interface.bssid(),
            "rssi_dbm": rssi or None,
            "noise_dbm": noise or None,
            "channel": int(channel.channelNumber()) if channel else None,
            "band": BANDS.get(band_value, str(band_value) if band_value else None),
            "width_mhz": WIDTHS.get(width_value),
            "tx_rate_mbps": rate or None,
        }
    except Exception:  # noqa: BLE001 - PyObjC can raise arbitrary bridge errors
        return None


def on_battery(runner: Runner) -> bool:
    result = runner.run(["pmset", "-g", "batt"], timeout=5)
    return result.ok and "Battery Power" in result.stdout


def is_expensive(runner: Runner) -> bool:
    """Best effort: `nettop -t expensive` lists processes on an expensive link."""
    result = runner.run(["nettop", "-L", "1", "-P", "-x", "-t", "expensive"], timeout=6)
    if not result.ok:
        return False
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith(",interface"):
            return True
    return False


def _first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _family(family: Any) -> str:
    return getattr(family, "name", str(family))


def _ipv4(addresses: list[Any]) -> str | None:
    for address in addresses:
        if _family(address.family) == "AF_INET" and not address.address.startswith("127."):
            return address.address.split("%", 1)[0]
    return None


def _ipv6(addresses: list[Any]) -> str | None:
    candidates = [
        address.address
        for address in addresses
        if _family(address.family) == "AF_INET6"
    ]
    for address in candidates:
        if not address.startswith("fe80"):
            return address.split("%", 1)[0]
    return candidates[0].split("%", 1)[0] if candidates else None


def sample_interfaces(
    runner: Runner,
    ts: int,
    psutil_module: Any = psutil,
    wifi_fn: Callable[[], dict[str, Any] | None] = wifi_snapshot,
) -> tuple[list[InterfaceSample], ActiveLink]:
    route_result = runner.run(["route", "-n", "get", "default"], timeout=3)
    route = parse_route_default(route_result.stdout) if route_result.ok else {}
    ports_result = runner.run(["networksetup", "-listallhardwareports"], timeout=5)
    ports = parse_hardware_ports(ports_result.stdout) if ports_result.ok else {}
    nwi_result = runner.run(["scutil", "--nwi"], timeout=5)
    nwi = parse_scutil_nwi(nwi_result.stdout) if nwi_result.ok else {}
    netstat_result = runner.run(["netstat", "-ib"], timeout=5)
    counters = parse_netstat_ib(netstat_result.stdout) if netstat_result.ok else {}

    try:
        addresses = psutil_module.net_if_addrs()
    except (psutil.Error, OSError):
        addresses = {}
    try:
        stats = psutil_module.net_if_stats()
    except (psutil.Error, OSError):
        stats = {}

    active_if = route.get("interface")
    if not active_if:
        for ifname, address_list in addresses.items():
            if ifname != "lo0" and _ipv4(address_list):
                stat = stats.get(ifname)
                if stat is None or stat.isup:
                    active_if = ifname
                    break
    if not active_if and nwi:
        active_if = next(iter(nwi))

    samples: list[InterfaceSample] = []
    active_sample: InterfaceSample | None = None
    for ifname, address_list in addresses.items():
        if ifname == "lo0":
            continue
        ipv4 = _ipv4(address_list)
        ipv6 = _ipv6(address_list)
        stat = stats.get(ifname)
        is_up = bool(stat.isup) if stat is not None else bool(ipv4 or ipv6)
        if not is_up and not ipv4 and not ipv6:
            continue
        kind = classify_interface(ifname, ports.get(ifname))
        counter = counters.get(ifname, {})
        wifi: dict[str, Any] = {}
        if kind == "wifi" and ifname == active_if:
            wifi = wifi_fn() or {}
        sample = InterfaceSample(
            ts=ts,
            ifname=ifname,
            kind=kind,
            is_up=is_up,
            is_default=(ifname == active_if),
            ipv4=ipv4,
            ipv6=ipv6,
            gateway=route.get("gateway") if ifname == active_if else None,
            ssid=wifi.get("ssid"),
            bssid=wifi.get("bssid"),
            rssi_dbm=wifi.get("rssi_dbm"),
            noise_dbm=wifi.get("noise_dbm"),
            channel=wifi.get("channel"),
            band=wifi.get("band"),
            width_mhz=wifi.get("width_mhz"),
            tx_rate_mbps=wifi.get("tx_rate_mbps"),
            link_speed_mbps=int(stat.speed) if stat and stat.speed > 0 else None,
            rx_bytes=counter.get("ibytes"),
            tx_bytes=counter.get("obytes"),
            rx_errors=counter.get("ierrs"),
            tx_errors=counter.get("oerrs"),
        )
        samples.append(sample)
        if ifname == active_if:
            active_sample = sample

    if active_if and active_sample is None:
        kind = classify_interface(str(active_if), ports.get(str(active_if)))
        counter = counters.get(str(active_if), {})
        active_sample = InterfaceSample(
            ts=ts,
            ifname=str(active_if),
            kind=kind,
            is_up=True,
            is_default=True,
            gateway=route.get("gateway"),
            rx_bytes=counter.get("ibytes"),
            tx_bytes=counter.get("obytes"),
            rx_errors=counter.get("ierrs"),
            tx_errors=counter.get("oerrs"),
        )
        samples.append(active_sample)

    if active_sample is not None:
        active = ActiveLink(
            ifname=active_sample.ifname,
            kind=active_sample.kind,
            ipv4=active_sample.ipv4,
            gateway=active_sample.gateway,
            ssid=active_sample.ssid,
            bssid=active_sample.bssid,
            rssi_dbm=active_sample.rssi_dbm,
        )
    else:
        active = ActiveLink(ifname=None, kind=None, ipv4=None, gateway=None)
    return samples, active
