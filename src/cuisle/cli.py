"""The `cuisle` command line."""

from __future__ import annotations

import logging
import os
import platform
import sqlite3
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

import click
import psutil

from cuisle import __version__, db
from cuisle.config import (
    Config,
    ConfigError,
    ensure_dirs,
    load_config,
    write_default_config,
)
from cuisle.config import (
    paths as config_paths,
)
from cuisle.render import (
    json_dump,
    render_connections,
    render_doctor,
    render_health,
    render_history,
    render_processes,
    render_status,
    render_throughput,
)
from cuisle.runner import Runner, which
from cuisle.util import DAY_MS, parse_since


def _now_ms() -> int:
    return int(time.time() * 1000)


def _since(value: str | None, default: str) -> int:
    return parse_since(value or default, _now_ms(), 0)


def _open_db(config: Config) -> Any:
    if not config.db_path.is_file():
        return None
    try:
        return db.connect(config.db_path, readonly=True)
    except (OSError, sqlite3.Error):
        return None


def _print_json(payload: Any) -> None:
    click.echo(json_dump(payload))


@click.group(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="cuisle")
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    envvar="CUISLE_CONFIG",
    help="Configuration file (default ~/.config/cuisle/config.toml).",
)
@click.pass_context
def main(ctx: click.Context, config_path: Path | None) -> None:
    """Cuisle — an always-on monitor for the network and its processes."""
    try:
        ctx.obj = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_obj
def paths(config: Config, as_json: bool) -> None:
    """Show the config, data, log and launchd paths."""
    payload = config_paths(config)
    if as_json:
        _print_json(payload)
        return
    for key, value in payload.items():
        click.echo(f"{key:<10} {value}")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--anchors", is_flag=True, help="Run the configured probes now.")
@click.pass_context
def doctor(ctx: click.Context, as_json: bool, anchors: bool) -> None:
    """Check tools, permissions, storage, launchd and anchors."""
    config: Config = ctx.obj
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    add("macOS", "ok" if platform.system() == "Darwin" else "fail", f"{platform.system()} {platform.release()}")
    add(
        "Python",
        "ok" if sys.version_info >= (3, 11) else "fail",
        platform.python_version(),
    )
    add("psutil", "ok", psutil.__version__)

    required = {"netstat": True, "route": True, "ping": True, "networksetup": False,
                "scutil": False, "pmset": False, "networkQuality": False, "dig": False}
    for tool, hard in required.items():
        found = which(tool)
        if found:
            add(tool, "ok", found)
        else:
            add(tool, "fail" if hard else "warn", "not found")

    runner = Runner()
    speedtest = which("speedtest")
    if speedtest:
        res = runner.run(["speedtest", "--version"], timeout=5)
        if res.ok and ("speedtest" in res.stdout.lower() or "ookla" in res.stdout.lower()):
            add("speedtest", "ok", speedtest)
        else:
            add(
                "speedtest",
                "warn",
                "not the Ookla CLI (the Python speedtest-cli shim?)",
            )
    else:
        add("speedtest", "warn", "not installed (optional)")
    add("iperf3", "ok" if which("iperf3") else "warn", which("iperf3") or "not installed (optional)")

    try:
        import CoreWLAN  # type: ignore  # noqa: F401

        add("CoreWLAN", "ok", "optional Wi-Fi detail available")
    except ImportError:
        add("CoreWLAN", "warn", "optional extra not installed")

    if config.path.is_file():
        add("config", "ok", str(config.path))
    else:
        add("config", "warn", f"using defaults; run 'cuisle config' to create {config.path}")

    try:
        ensure_dirs(config)
        probe = config.data_dir / ".cuisle-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("data dir", "ok", str(config.data_dir))
    except OSError as exc:
        add("data dir", "fail", str(exc))

    try:
        conn = db.connect(config.db_path)
        db.init_db(conn)
        conn.close()
        add("database", "ok", str(config.db_path))
    except (OSError, sqlite3.Error) as exc:
        add("database", "fail", str(exc))

    from cuisle import service

    svc = service.status(runner)
    if svc["loaded"]:
        add("launchd", "ok", svc["label"])
    elif svc["installed"]:
        add("launchd", "warn", "installed but not loaded")
    else:
        add("launchd", "warn", "not installed; run 'cuisle service install'")

    for anchor in config.enabled_anchors():
        add(
            f"anchor:{anchor.name}",
            "ok",
            f"scope {anchor.scope}; {anchor.host or 'gateway'}"
            f"; backend {anchor.resolved_backend(config.throughput.backend)}",
        )

    if anchors:
        from cuisle.samplers.health import sample_health
        from cuisle.samplers.interfaces import sample_interfaces

        _, active = sample_interfaces(runner, _now_ms())
        for sample in sample_health(config, runner, active, _now_ms()):
            add(
                f"probe:{sample.anchor}:{sample.method}",
                "ok" if sample.success else "fail",
                sample.detail or sample.status or "",
            )

    if as_json:
        _print_json({"checks": checks, "ok": all(c["status"] != "fail" for c in checks)})
    else:
        click.echo(render_doctor(checks))
    if any(c["status"] == "fail" for c in checks):
        ctx.exit(1)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_obj
def status(config: Config, as_json: bool) -> None:
    """Show the current link, health, throughput and top processes."""
    conn = _open_db(config)
    if conn is None:
        click.echo("No samples yet. Start the daemon with: cuisle daemon run")
        return
    try:
        snapshot = db.status_snapshot(conn, _now_ms() - 15 * 60 * 1000)
    finally:
        conn.close()
    if as_json:
        _print_json(snapshot)
    else:
        click.echo(render_status(snapshot))


@main.command()
@click.option("--interval", type=click.IntRange(1, 300), default=5, show_default=True)
@click.pass_obj
def watch(config: Config, interval: int) -> None:
    """Refresh the status screen in place."""
    try:
        while True:
            conn = _open_db(config)
            click.clear()
            if conn is None:
                click.echo("No samples yet. Start the daemon with: cuisle daemon run")
            else:
                try:
                    snapshot = db.status_snapshot(conn, _now_ms() - 15 * 60 * 1000)
                finally:
                    conn.close()
                click.echo(render_status(snapshot))
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


@main.command()
@click.option("--since", default="60s", show_default=True)
@click.option("--sort", type=click.Choice(["cpu", "mem", "rx", "tx"]), default="cpu", show_default=True)
@click.option("--limit", type=click.IntRange(1, 500), default=25, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_obj
def processes(config: Config, since: str, sort: str, limit: int, as_json: bool) -> None:
    """Show the busiest processes in a time range."""
    conn = _open_db(config)
    if conn is None:
        click.echo("No samples yet. Start the daemon with: cuisle daemon run")
        return
    try:
        rows = db.processes_since(conn, _since(since, "60s"), sort, limit)
    finally:
        conn.close()
    if as_json:
        _print_json({"processes": rows})
    else:
        click.echo(render_processes(rows, sort))


@main.command()
@click.option("--since", default="5m", show_default=True)
@click.option("--state", default=None, help="Filter by socket state, e.g. ESTABLISHED.")
@click.option("--process", default=None, help="Filter by process name or PID.")
@click.option("--limit", type=click.IntRange(1, 500), default=50, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_obj
def connections(
    config: Config, since: str, state: str | None, process: str | None, limit: int, as_json: bool
) -> None:
    """Show recent TCP and UDP sockets."""
    conn = _open_db(config)
    if conn is None:
        click.echo("No samples yet. Start the daemon with: cuisle daemon run")
        return
    try:
        rows = db.connections_since(conn, _since(since, "5m"), state, process, limit)
    finally:
        conn.close()
    if as_json:
        _print_json({"connections": rows})
    else:
        click.echo(render_connections(rows))


@main.command()
@click.option("--since", default="5m", show_default=True)
@click.option("--anchor", default=None, help="Only one anchor.")
@click.option("--now", is_flag=True, help="Run the probes now instead of reading the database.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_obj
def health(config: Config, since: str, anchor: str | None, now: bool, as_json: bool) -> None:
    """Show the latest health probes, or run them now."""
    if now:
        from cuisle.samplers.health import sample_health
        from cuisle.samplers.interfaces import sample_interfaces

        runner = Runner()
        _, active = sample_interfaces(runner, _now_ms())
        anchors = [config.anchor(anchor)] if anchor else config.enabled_anchors()
        saved = config.anchors
        config.anchors = anchors
        try:
            rows = [s.as_dict() for s in sample_health(config, runner, active, _now_ms())]
        finally:
            config.anchors = saved
    else:
        conn = _open_db(config)
        if conn is None:
            click.echo("No samples yet. Start the daemon with: cuisle daemon run")
            return
        try:
            rows = db.latest_probes(conn, _since(since, "5m"), anchor)
        finally:
            conn.close()
    if as_json:
        _print_json({"probes": rows})
    else:
        click.echo(render_health(rows))


@main.command()
@click.option("--now", is_flag=True, help="Run the throughput tests now.")
@click.option("--anchor", default=None, help="Only one anchor.")
@click.option("--backend", type=click.Choice(["http", "speedtest", "iperf3"]), default=None)
@click.option(
    "--networkquality/--no-networkquality",
    default=True,
    show_default=True,
    help="Include the Apple capacity test (about 90 MB).",
)
@click.option("--since", default="7d", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_obj
def speed(
    config: Config,
    now: bool,
    anchor: str | None,
    backend: str | None,
    networkquality: bool,
    since: str,
    as_json: bool,
) -> None:
    """Run a throughput test now, or show the latest results."""
    if now:
        from cuisle.backends import run_all_throughput
        from cuisle.samplers.interfaces import sample_interfaces

        runner = Runner()
        ts = _now_ms()
        _, active = sample_interfaces(runner, ts)
        anchors = [config.anchor(anchor)] if anchor else config.enabled_anchors()
        if backend:
            anchors = [
                a for a in anchors if a.resolved_backend(config.throughput.backend) == backend
            ]
        samples = run_all_throughput(
            config,
            runner,
            ts,
            active.ifname,
            anchors=anchors,
            include_networkquality=networkquality,
        )
        rows = [s.as_dict() for s in samples]
    else:
        conn = _open_db(config)
        if conn is None:
            click.echo("No samples yet. Start the daemon with: cuisle daemon run")
            return
        try:
            rows = db.latest_throughputs(conn, _since(since, "7d"), anchor)
        finally:
            conn.close()
    if as_json:
        _print_json({"throughputs": rows})
    else:
        click.echo(render_throughput(rows))


@main.command()
@click.option("--metric", required=True, type=click.Choice(sorted(db.SERIES)))
@click.option("--since", default="1h", show_default=True)
@click.option("--scope", default=None)
@click.option("--anchor", default=None)
@click.option("--method", default=None)
@click.option(
    "--resolution",
    type=click.Choice(["auto", "raw", "5m", "1h"]),
    default="auto",
    show_default=True,
    help="Data source; auto uses raw, then 5-minute, then hourly rollups.",
)
@click.option("--points", type=click.IntRange(50, 2000), default=300, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_obj
def history(
    config: Config,
    metric: str,
    since: str,
    scope: str | None,
    anchor: str | None,
    method: str | None,
    resolution: str,
    points: int,
    as_json: bool,
) -> None:
    """Query a metric series over time, including long rollup-backed ranges."""
    conn = _open_db(config)
    if conn is None:
        click.echo("No samples yet. Start the daemon with: cuisle daemon run")
        return
    now = _now_ms()
    since_ms = _since(since, "1h")
    if metric in ("latency_ms", "loss_pct"):
        method = method or "icmp"
        anchor = anchor or next(
            (a.name for a in config.enabled_anchors() if method in a.health), None
        )
    elif metric in ("down_bps", "up_bps"):
        anchor = anchor or "networkquality"
        method = method or "networkquality"
    elif metric == "rssi_dbm" and not anchor:
        interfaces = db.latest_interfaces(conn)
        active = next((row for row in interfaces if row["is_default"]), None)
        if active is None:
            active = next((row for row in interfaces if row["is_up"]), None)
        if active:
            anchor = active["ifname"]
    try:
        result = db.series_window(
            conn,
            metric,
            since_ms,
            now,
            scope=scope,
            anchor=anchor,
            method=method,
            max_points=points,
            resolution=resolution,
            raw_cutoff_ms=now - config.retention.raw_days * DAY_MS,
            five_cutoff_ms=now - config.retention.five_minute_days * DAY_MS,
            hourly_cutoff_ms=now - config.retention.hourly_days * DAY_MS,
        )
    finally:
        conn.close()
    if as_json:
        _print_json(
            {
                "metric": metric,
                "resolution": result["resolution"],
                "points": result["points"],
                "window": {"since": since_ms, "until": now},
                "series": {"scope": scope, "anchor": anchor, "method": method},
            }
        )
    else:
        click.echo(render_history(result["points"], metric, result["resolution"]))


@main.command()
@click.option("--since", default="24h", show_default=True)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Report path; defaults to ./reports/cuisle-report-<timestamp>.html.",
)
@click.option("--open", "open_after", is_flag=True, help="Open the report in the browser.")
@click.pass_obj
def report(config: Config, since: str, output: Path | None, open_after: bool) -> None:
    """Generate a self-contained HTML report in ./reports/."""
    from cuisle.report import generate_report, open_report

    if not config.db_path.is_file():
        raise click.ClickException("no database yet; start the daemon first")
    try:
        path = generate_report(config, _since(since, "24h"), output)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(str(path))
    if open_after:
        open_report(path)


@main.command()
@click.option("--standalone", is_flag=True, help="Serve the database read-only instead of using a running daemon.")
@click.option(
    "--open/--no-open",
    "open_after",
    default=True,
    show_default=True,
    help="Open the dashboard in the default browser.",
)
@click.option("--port", type=click.IntRange(1, 65535), default=None)
@click.pass_obj
def dashboard(config: Config, standalone: bool, open_after: bool, port: int | None) -> None:
    """Serve or open the loopback dashboard."""
    from cuisle.server import is_running, serve_in_thread

    if port:
        config.general.dashboard_port = port
    host = config.general.dashboard_host
    url = f"http://{host}:{config.general.dashboard_port}/"
    if not standalone and is_running(host, config.general.dashboard_port):
        click.echo(url)
        if open_after:
            _open_dashboard(url)
        return
    try:
        server, thread = serve_in_thread(config)
    except OSError as exc:
        raise click.ClickException(f"dashboard could not bind {host}:{config.general.dashboard_port}: {exc}") from exc
    click.echo(f"Cuisle dashboard: {url}")
    if open_after:
        _open_dashboard(url)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


def _open_dashboard(url: str) -> None:
    try:
        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001 - a headless session has no browser
        opened = False
    if not opened:
        click.echo(f"Could not open a browser; visit {url}", err=True)


@main.group()
def daemon() -> None:
    """Run the sampler loop."""


@daemon.command("run")
@click.option("--once", is_flag=True, help="Take one light sample and exit (no throughput tests).")
@click.pass_obj
def daemon_run(config: Config, once: bool) -> None:
    """Run the daemon in the foreground."""
    logging.basicConfig(
        level=os.environ.get("CUISLE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from cuisle.daemon import Daemon

    Daemon(config).run(once=once)


@main.group()
def service() -> None:
    """Install and control the launchd user agent."""


@service.command("install")
@click.pass_obj
def service_install(config: Config) -> None:
    """Install and start the launchd agent."""
    from cuisle import service as svc

    try:
        path = svc.install(config)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Installed {path}")
    click.echo(render_doctor([_svc_check(svc.status())]))


@service.command("uninstall")
@click.pass_obj
def service_uninstall(config: Config) -> None:
    """Stop and remove the launchd agent."""
    from cuisle import service as svc

    path = svc.uninstall(config)
    click.echo(f"Removed {path}")


@service.command("start")
@click.pass_obj
def service_start(config: Config) -> None:
    """Start the installed launchd agent."""
    from cuisle import service as svc

    try:
        svc.start(config)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Started")


@service.command("stop")
def service_stop() -> None:
    """Stop the launchd agent."""
    from cuisle import service as svc

    try:
        svc.stop()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Stopped")


@service.command("restart")
def service_restart() -> None:
    """Restart the launchd agent."""
    from cuisle import service as svc

    try:
        svc.restart()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Restarted")


@service.command("status")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def service_status(as_json: bool) -> None:
    """Show whether the launchd agent is installed and loaded."""
    from cuisle import service as svc

    payload = svc.status()
    if as_json:
        _print_json(payload)
    else:
        click.echo(render_doctor([_svc_check(payload)]))


def _svc_check(payload: dict[str, Any]) -> dict[str, str]:
    if payload["loaded"]:
        status = "ok"
    elif payload["installed"]:
        status = "warn"
    else:
        status = "warn"
    detail = payload.get("detail") or payload.get("path") or ""
    return {"name": payload["label"], "status": status, "detail": detail}


@main.command("config")
@click.option("--show", is_flag=True, help="Print the configuration instead of editing it.")
@click.option("--path", "show_path", is_flag=True, help="Print the configuration path only.")
@click.pass_obj
def config_command(config: Config, show: bool, show_path: bool) -> None:
    """Create or edit the configuration file."""
    if not config.path.is_file():
        write_default_config(config.path)
        click.echo(f"Created {config.path}", err=True)
    if show_path:
        click.echo(str(config.path))
    elif show:
        click.echo(config.path.read_text(encoding="utf-8"))
    elif click.edit(filename=str(config.path)) is None:
        click.echo(f"Configuration unchanged: {config.path}")
