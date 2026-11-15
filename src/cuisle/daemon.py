"""The long-running sampler loop."""

from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path
from typing import Any

from cuisle import __version__, db
from cuisle.config import Config, ensure_dirs
from cuisle.model import ActiveLink, EventSample
from cuisle.networkquality import run_networkquality
from cuisle.rollup import maintenance
from cuisle.runner import Runner
from cuisle.samplers.connections import ConnectionSampler
from cuisle.samplers.health import sample_health
from cuisle.samplers.interfaces import is_expensive, on_battery, sample_interfaces
from cuisle.samplers.processes import ProcessSampler
from cuisle.samplers.throughput import sample_throughput
from cuisle.server import serve_in_thread

LOG = logging.getLogger("cuisle.daemon")


class Daemon:
    def __init__(
        self,
        config: Config,
        runner: Runner | None = None,
        db_path: str | Path | None = None,
        clock: Any = time.monotonic,
        wall: Any = time.time,
    ) -> None:
        self.config = config
        self.runner = runner or Runner()
        self.db_path = Path(db_path) if db_path else config.db_path
        self.clock = clock
        self.wall = wall
        self.conn = None
        self.stop_event = threading.Event()
        self.active = ActiveLink(ifname=None, kind=None, ipv4=None, gateway=None)
        self.net_by_pid: dict[int, tuple[float, float]] = {}
        self.process_sampler = ProcessSampler(config.sampling.process_top_n)
        self.connection_sampler = ConnectionSampler(self.runner)
        self._next: dict[str, float] = {}
        self._last_wall_tick = 0.0
        self._last_active: tuple[Any, ...] | None = None
        self._battery: bool | None = None
        self._expensive: bool | None = None
        self._power_checked = 0.0
        self._failures: dict[str, int] = {}
        self._server = None
        self._server_thread = None

    # -- lifecycle ---------------------------------------------------------

    def run(self, once: bool = False) -> None:
        ensure_dirs(self.config)
        self.conn = db.connect(self.db_path)
        db.init_db(self.conn)
        self.process_sampler.prime()
        LOG.info("cuisle %s starting; database %s", __version__, self.db_path)
        self._install_signals()
        if not once and self.config.general.dashboard_enabled:
            try:
                self._server, self._server_thread = serve_in_thread(self.config)
                LOG.info(
                    "dashboard on http://%s:%s",
                    self.config.general.dashboard_host,
                    self.config.general.dashboard_port,
                )
            except OSError as exc:
                LOG.warning("dashboard could not start: %s", exc)
        try:
            if once:
                self._run_once()
            else:
                self._loop()
        finally:
            self._shutdown()

    def _loop(self) -> None:
        now = self.clock()
        self._next = {
            "interface": 0.0,
            "connections": 0.0,
            "processes": 0.0,
            "health": 0.0,
            "throughput": now + 60.0,
            "networkquality": now + 120.0,
            "maintenance": now + 3600.0,
        }
        self._last_wall_tick = self.wall()
        while not self.stop_event.is_set():
            now = self.clock()
            wall_now = self.wall()
            wall_delta = wall_now - self._last_wall_tick
            if wall_delta > self._gap_threshold():
                self._event("sleep_gap", f"{wall_delta:.0f}s without a sample")
            elif wall_delta < -60:
                self._event("clock_jump", f"{wall_delta:.0f}s")
            self._last_wall_tick = wall_now
            self._refresh_power(now)

            if now >= self._next["interface"]:
                self._run_task("interface", now, self._run_interface, self.config.sampling.interface_seconds)
            if now >= self._next["connections"]:
                self._run_task(
                    "connections", now, self._run_connections, self.config.sampling.connection_seconds
                )
            if now >= self._next["processes"]:
                self._run_task(
                    "processes", now, self._run_processes, self.config.sampling.process_seconds
                )
            if now >= self._next["health"]:
                self._run_task("health", now, self._run_health, self._health_interval())
            if now >= self._next["throughput"]:
                if self._throughput_allowed():
                    self._run_task(
                        "throughput",
                        now,
                        self._run_throughput,
                        self.config.sampling.throughput_seconds,
                    )
                else:
                    self._next["throughput"] = now + self.config.sampling.throughput_seconds
            if now >= self._next["networkquality"]:
                if self._networkquality_allowed():
                    self._run_task(
                        "networkquality",
                        now,
                        self._run_networkquality,
                        self.config.sampling.networkquality_seconds,
                    )
                else:
                    self._next["networkquality"] = now + self.config.sampling.networkquality_seconds
            if now >= self._next["maintenance"]:
                self._run_task("maintenance", now, self._run_maintenance, 3600)

            timeout = min(self._next.values()) - self.clock()
            self.stop_event.wait(max(0.2, min(30.0, timeout)))

    def _run_once(self) -> None:
        now = self.clock()
        self._last_wall_tick = self.wall()
        self._refresh_power(now)
        self._run_interface(now)
        self._run_connections(now)
        self._run_processes(now)
        self._run_health(now)
        self._run_maintenance(now)

    def _shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        LOG.info("cuisle stopped")

    def _install_signals(self) -> None:
        def stop(_signum: int, _frame: Any) -> None:
            self.stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, stop)
            except (ValueError, OSError):
                pass

    # -- tasks -------------------------------------------------------------

    def _run_task(self, name: str, now: float, func: Any, interval: int) -> None:
        try:
            func(now)
        except Exception as exc:  # a sampler must never stop the daemon
            self._failures[name] = self._failures.get(name, 0) + 1
            if self._failures[name] == 1:
                LOG.exception("%s sampler failed", name)
            else:
                LOG.warning("%s sampler still failing: %s", name, exc)
            self._next[name] = now + max(interval * 2, 30)
        else:
            self._failures[name] = 0
            self._next[name] = now + interval

    def _run_interface(self, _now: float) -> None:
        ts = int(self.wall() * 1000)
        samples, active = sample_interfaces(self.runner, ts)
        if samples:
            db.insert_interfaces(self.conn, samples)
            self.conn.commit()
        signature = (active.ifname, active.ipv4, active.gateway, active.ssid, active.bssid)
        if self._last_active is not None and signature != self._last_active:
            self._event(
                "link_change",
                f"{self._last_active[0] or 'none'} -> {active.ifname or 'none'}"
                f", {active.kind or 'unknown'}",
            )
        elif self._last_active is None:
            self._event("start", f"{active.ifname or 'no interface'} ({active.kind or 'unknown'})")
        self._last_active = signature
        self.active = active

    def _run_connections(self, _now: float) -> None:
        ts = int(self.wall() * 1000)
        samples, net, resets = self.connection_sampler.sample(ts)
        if samples:
            db.insert_connections(self.conn, samples)
            self.conn.commit()
        if resets:
            self._event("counter_reset", "; ".join(resets[:5]))
        self.net_by_pid = net

    def _run_processes(self, _now: float) -> None:
        ts = int(self.wall() * 1000)
        host, processes = self.process_sampler.sample(ts, self.net_by_pid)
        db.insert_host(self.conn, host)
        if processes:
            db.insert_processes(self.conn, processes)
        self.conn.commit()

    def _run_health(self, _now: float) -> None:
        ts = int(self.wall() * 1000)
        samples = sample_health(self.config, self.runner, self.active, ts)
        if samples:
            db.insert_probes(self.conn, samples)
            self.conn.commit()

    def _run_throughput(self, _now: float) -> None:
        ts = int(self.wall() * 1000)
        samples = sample_throughput(
            self.config,
            self.runner,
            self.active,
            ts,
            include_networkquality=False,
        )
        if samples:
            db.insert_throughputs(self.conn, samples)
            self.conn.commit()

    def _run_networkquality(self, _now: float) -> None:
        ts = int(self.wall() * 1000)
        sample = run_networkquality(
            self.runner,
            ts,
            timeout=max(30, self.config.throughput.timeout_seconds * 2),
            interface=self.active.ifname,
        )
        db.insert_throughputs(self.conn, [sample])
        self.conn.commit()

    def _run_maintenance(self, _now: float) -> None:
        maintenance(self.conn, self.config.retention, int(self.wall() * 1000))

    # -- policy ------------------------------------------------------------

    def _refresh_power(self, now: float) -> None:
        if now - self._power_checked < 60:
            return
        self._power_checked = now
        battery = on_battery(self.runner)
        expensive = is_expensive(self.runner)
        if self._battery is None or battery != self._battery or expensive != self._expensive:
            self._event(
                "power",
                f"{'battery' if battery else 'ac'}"
                f", {'expensive link' if expensive else 'normal link'}",
            )
        self._battery = battery
        self._expensive = expensive

    def _health_interval(self) -> int:
        if self._battery:
            return self.config.battery.slow_health_seconds
        return self.config.sampling.health_seconds

    def _throughput_allowed(self) -> bool:
        return not (
            (self._battery and self.config.battery.pause_throughput)
            or (self._expensive and not self.config.throughput.allow_expensive)
        )

    def _networkquality_allowed(self) -> bool:
        return not (
            (self._battery and self.config.battery.pause_networkquality)
            or (self._expensive and not self.config.throughput.allow_expensive)
        )

    def _gap_threshold(self) -> float:
        smallest = min(
            self.config.sampling.process_seconds,
            self.config.sampling.connection_seconds,
            self.config.sampling.interface_seconds,
            self.config.sampling.health_seconds,
        )
        return max(120.0, smallest * 3)

    def _event(self, kind: str, detail: str) -> None:
        db.insert_event(self.conn, EventSample(ts=int(self.wall() * 1000), kind=kind, detail=detail))
        self.conn.commit()
