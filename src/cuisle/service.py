"""launchd LaunchAgent install, start, stop and status."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path
from typing import Any

from cuisle.config import LAUNCHD_LABEL, Config, ensure_dirs
from cuisle.runner import Runner


def launch_agent_path(home: str | Path | None = None) -> Path:
    base = Path(home).expanduser() if home else Path.home()
    return base / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def build_plist(
    config: Config,
    executable: str | None = None,
    home: str | Path | None = None,
) -> bytes:
    log_dir = config.log_dir
    payload: dict[str, Any] = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [
            str(executable or sys.executable),
            "-m",
            "cuisle",
            "daemon",
            "run",
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "Nice": 5,
        "LowPriorityIO": True,
        "StandardOutPath": str(log_dir / "daemon.log"),
        "StandardErrorPath": str(log_dir / "daemon.err"),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False)


def _uid() -> str:
    return str(os.getuid())


def _domain() -> str:
    return f"gui/{_uid()}"


def _target() -> str:
    return f"{_domain()}/{LAUNCHD_LABEL}"


def _bootstrap(runner: Runner, plist: Path) -> None:
    result = runner.run(["launchctl", "bootstrap", _domain(), str(plist)], timeout=15)
    if result.ok:
        return
    fallback = runner.run(["launchctl", "load", "-w", str(plist)], timeout=15)
    if not fallback.ok:
        detail = (result.stderr or fallback.stderr or "launchctl bootstrap failed").strip()
        raise RuntimeError(detail)


def install(
    config: Config,
    runner: Runner | None = None,
    executable: str | None = None,
    home: str | Path | None = None,
) -> Path:
    ensure_dirs(config)
    runner = runner or Runner()
    path = launch_agent_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_plist(config, executable=executable, home=home))
    runner.run(["launchctl", "bootout", _target()], timeout=10)
    _bootstrap(runner, path)
    return path


def uninstall(
    config: Config,
    runner: Runner | None = None,
    home: str | Path | None = None,
) -> Path:
    runner = runner or Runner()
    runner.run(["launchctl", "bootout", _target()], timeout=10)
    path = launch_agent_path(home)
    if path.exists():
        path.unlink()
    return path


def start(config: Config, runner: Runner | None = None, home: str | Path | None = None) -> None:
    runner = runner or Runner()
    path = launch_agent_path(home)
    if not path.exists():
        install(config, runner=runner, home=home)
        return
    runner.run(["launchctl", "bootout", _target()], timeout=10)
    _bootstrap(runner, path)


def stop(runner: Runner | None = None) -> None:
    runner = runner or Runner()
    result = runner.run(["launchctl", "bootout", _target()], timeout=10)
    if not result.ok and "No such process" not in (result.stderr or ""):
        raise RuntimeError((result.stderr or "launchctl bootout failed").strip())


def restart(runner: Runner | None = None) -> None:
    runner = runner or Runner()
    result = runner.run(["launchctl", "kickstart", "-k", _target()], timeout=10)
    if not result.ok:
        raise RuntimeError((result.stderr or "launchctl kickstart failed").strip())


def status(runner: Runner | None = None, home: str | Path | None = None) -> dict[str, Any]:
    runner = runner or Runner()
    path = launch_agent_path(home)
    result = runner.run(["launchctl", "print", _target()], timeout=10)
    return {
        "label": LAUNCHD_LABEL,
        "installed": path.exists(),
        "path": str(path),
        "loaded": result.ok,
        "detail": (result.stdout or result.stderr or "").strip()[:400],
    }
