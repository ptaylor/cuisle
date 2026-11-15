"""TCP/UDP socket sampling from `netstat -anv -p tcp|udp`."""

from __future__ import annotations

from typing import Any

import psutil

from cuisle.model import ConnectionSample
from cuisle.runner import Runner


def parse_address(token: str) -> tuple[str, int | None]:
    """Split a macOS netstat address such as `192.168.1.2.443` from the right."""
    token = token.strip()
    if token in ("", "*", "*.*"):
        return "*", None
    if "." not in token:
        return token, None
    host, _, port = token.rpartition(".")
    if port.isdigit():
        return host or "*", int(port)
    return token, None


def parse_netstat(text: str) -> list[dict[str, Any]]:
    """Parse `netstat -anv -p tcp|udp` output using the header's rxbytes column."""
    rows: list[dict[str, Any]] = []
    rx_index: int | None = None
    for raw_line in text.splitlines():
        if raw_line.startswith("Proto") and "rxbytes" in raw_line:
            rx_index = raw_line.index("rxbytes")
            continue
        if rx_index is None or not raw_line.strip():
            continue
        if len(raw_line) <= rx_index:
            continue
        head = raw_line[:rx_index].split()
        tail = raw_line[rx_index:].split()
        if len(head) < 5 or len(tail) < 5:
            continue
        proto, local, remote = head[0], head[3], head[4]
        state = head[5] if len(head) >= 6 else "-"
        try:
            rx = int(tail[0])
            tx = int(tail[1])
        except ValueError:
            continue
        pid = int(tail[4]) if tail[4].isdigit() else None
        local_addr, local_port = parse_address(local)
        remote_addr, remote_port = parse_address(remote)
        rows.append(
            {
                "proto": proto,
                "local_addr": local_addr,
                "local_port": local_port,
                "remote_addr": remote_addr,
                "remote_port": remote_port,
                "state": state,
                "rx_bytes": rx,
                "tx_bytes": tx,
                "pid": pid,
            }
        )
    return rows


class ConnectionSampler:
    """Turn cumulative socket counters into per-socket and per-process rates."""

    def __init__(self, runner: Runner, psutil_module: Any = psutil) -> None:
        self.runner = runner
        self.psutil = psutil_module
        self._prev: dict[tuple[Any, ...], tuple[int, int, int, str]] = {}
        self._names: dict[int | None, str | None] = {}

    def sample(
        self, ts: int
    ) -> tuple[
        list[ConnectionSample], dict[int, tuple[float, float]], list[str]
    ]:
        rows: list[dict[str, Any]] = []
        for proto in ("tcp", "udp"):
            result = self.runner.run(["netstat", "-anv", "-p", proto], timeout=10)
            if result.ok:
                rows.extend(parse_netstat(result.stdout))

        address_map = self._address_map()
        samples: list[ConnectionSample] = []
        net: dict[int, tuple[float, float]] = {}
        resets: list[str] = []
        seen: set[tuple[Any, ...]] = set()

        for row in rows:
            key = (
                row["proto"],
                row["local_addr"],
                row["local_port"],
                row["remote_addr"],
                row["remote_port"],
                row["pid"],
            )
            prev = self._prev.get(key)
            if prev is not None:
                if row["rx_bytes"] < prev[0] or row["tx_bytes"] < prev[1]:
                    resets.append(
                        f"{row['proto']} {row['local_addr']}:{row['local_port']} -> "
                        f"{row['remote_addr']}:{row['remote_port']} pid {row['pid']}"
                    )
                dt = max(0.001, (ts - prev[2]) / 1000)
                rx_bps = max(0.0, (row["rx_bytes"] - prev[0]) / dt)
                tx_bps = max(0.0, (row["tx_bytes"] - prev[1]) / dt)
                state_changed = prev[3] != row["state"]
            else:
                rx_bps = 0.0
                tx_bps = 0.0
                state_changed = True

            pid = row["pid"]
            if pid is not None:
                total = net.get(pid, (0.0, 0.0))
                net[pid] = (total[0] + rx_bps, total[1] + tx_bps)

            if prev is None or state_changed or rx_bps > 0 or tx_bps > 0:
                interface = self._interface(row["local_addr"], address_map)
                samples.append(
                    ConnectionSample(
                        ts=ts,
                        pid=pid,
                        name=self._name(pid),
                        proto=row["proto"],
                        local_addr=row["local_addr"],
                        local_port=row["local_port"],
                        remote_addr=row["remote_addr"],
                        remote_port=row["remote_port"],
                        state=row["state"],
                        rx_bytes=row["rx_bytes"],
                        tx_bytes=row["tx_bytes"],
                        rx_bps=rx_bps,
                        tx_bps=tx_bps,
                        interface=interface,
                    )
                )

            self._prev[key] = (row["rx_bytes"], row["tx_bytes"], ts, row["state"])
            seen.add(key)

        cutoff = ts - 300_000
        self._prev = {
            key: value for key, value in self._prev.items() if value[2] >= cutoff or key in seen
        }
        if len(self._names) > 5000:
            self._names.clear()
        return samples, net, resets

    def _name(self, pid: int | None) -> str | None:
        if pid is None:
            return None
        if pid in self._names:
            return self._names[pid]
        try:
            name = self.psutil.Process(pid).name()
        except Exception:  # noqa: BLE001 - a vanished or denied process is not fatal
            name = None
        self._names[pid] = name
        return name

    def _address_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        try:
            interfaces = self.psutil.net_if_addrs()
        except Exception:  # noqa: BLE001 - interface lookup is best effort
            return mapping
        for ifname, addresses in interfaces.items():
            for address in addresses:
                try:
                    mapping[address.address.split("%", 1)[0]] = ifname
                except AttributeError:
                    continue
        return mapping

    @staticmethod
    def _interface(local_addr: str, mapping: dict[str, str]) -> str | None:
        if local_addr in ("", "*"):
            return None
        if "%" in local_addr:
            return local_addr.rsplit("%", 1)[-1]
        return mapping.get(local_addr.split("%", 1)[0])
