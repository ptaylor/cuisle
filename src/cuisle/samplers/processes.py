"""Host and per-process CPU, memory, thread and network sampling."""

from __future__ import annotations

import os
import time
from typing import Any

import psutil

from cuisle.model import HostSample, ProcessSample


def select_top(rows: list[ProcessSample], top_n: int) -> list[ProcessSample]:
    """Keep the top rows by CPU, memory and network, without duplicates."""
    top_n = max(1, top_n)
    selected: list[ProcessSample] = []
    seen: set[int] = set()

    def take(candidates: list[ProcessSample]) -> None:
        for row in candidates[:top_n]:
            if row.pid not in seen:
                seen.add(row.pid)
                selected.append(row)

    take(sorted(rows, key=lambda r: r.cpu_pct, reverse=True))
    take(sorted(rows, key=lambda r: r.rss_bytes, reverse=True))
    take(sorted((r for r in rows if (r.rx_bps or 0) > 0), key=lambda r: r.rx_bps or 0, reverse=True))
    take(sorted((r for r in rows if (r.tx_bps or 0) > 0), key=lambda r: r.tx_bps or 0, reverse=True))
    return selected


class ProcessSampler:
    """Keeps one psutil.Process per PID so cpu_percent() deltas are meaningful."""

    def __init__(self, top_n: int = 15, psutil_module: Any = psutil) -> None:
        self.top_n = max(1, top_n)
        self.psutil = psutil_module
        self._cache: dict[int, Any] = {}
        self._started: dict[int, float | None] = {}

    def prime(self, seconds: float = 0.2) -> None:
        """Seed cpu_percent() so the first real sample is not all zeros."""
        self.psutil.cpu_percent(interval=None)
        try:
            for proc in self.psutil.process_iter(["pid"]):
                try:
                    self._cache[int(proc.pid)] = proc
                    proc.cpu_percent(interval=None)
                except Exception:  # noqa: BLE001, S112 - priming is best effort
                    continue
        except Exception:  # noqa: BLE001 - priming is best effort
            return
        time.sleep(seconds)

    def sample(
        self, ts: int, net_by_pid: dict[int, tuple[float, float]] | None = None
    ) -> tuple[HostSample, list[ProcessSample]]:
        net_by_pid = net_by_pid or {}
        host = self._host(ts)
        rows: list[ProcessSample] = []
        alive: set[int] = set()

        try:
            iterator = self.psutil.process_iter(["pid"])
        except Exception:  # noqa: BLE001 - never stop the sampler
            iterator = []

        for proc in iterator:
            try:
                pid = int(proc.info.get("pid", proc.pid))
            except Exception:  # noqa: BLE001, S112 - skip an unreadable process
                continue
            alive.add(pid)
            cached = self._cache.get(pid)
            if cached is None:
                cached = proc
                self._cache[pid] = proc
                try:
                    self._started[pid] = float(cached.create_time())
                except Exception:  # noqa: BLE001 - start time is optional
                    self._started[pid] = None
            try:
                name = str(cached.name())
                username = str(cached.username())
                cpu = float(cached.cpu_percent(interval=None))
                rss = int(cached.memory_info().rss)
                threads = int(cached.num_threads())
                status = str(cached.status())
            except Exception:  # noqa: BLE001, S112 - a denied process is not fatal
                continue
            rx, tx = net_by_pid.get(pid, (0.0, 0.0))
            rows.append(
                ProcessSample(
                    ts=ts,
                    pid=pid,
                    name=name,
                    username=username,
                    cpu_pct=cpu,
                    rss_bytes=rss,
                    threads=threads,
                    status=status,
                    started_at=self._started.get(pid),
                    rx_bps=rx,
                    tx_bps=tx,
                )
            )

        for pid in list(self._cache):
            if pid not in alive:
                self._cache.pop(pid, None)
                self._started.pop(pid, None)

        return host, select_top(rows, self.top_n)

    def _host(self, ts: int) -> HostSample:
        cpu = float(self.psutil.cpu_percent(interval=None))
        vm = self.psutil.virtual_memory()
        try:
            load1 = float(os.getloadavg()[0])
        except (OSError, AttributeError):
            load1 = 0.0
        try:
            count = len(self.psutil.pids())
        except Exception:  # noqa: BLE001 - process count is best effort
            count = 0
        return HostSample(
            ts=ts,
            cpu_pct=cpu,
            mem_used=int(vm.used),
            mem_total=int(vm.total),
            load1=load1,
            process_count=count,
        )
