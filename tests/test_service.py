from __future__ import annotations

import plistlib
from pathlib import Path

from conftest import FakeRunner

from cuisle import service
from cuisle.config import Config
from cuisle.runner import Result


def test_build_plist(config: Config, tmp_path: Path) -> None:
    data = service.build_plist(config, executable="/venv/bin/python", home=tmp_path)
    plist = plistlib.loads(data)
    assert plist["Label"] == "com.ptaylor.cuisle"
    assert plist["ProgramArguments"] == [
        "/venv/bin/python",
        "-m",
        "cuisle",
        "daemon",
        "run",
    ]
    assert plist["RunAtLoad"] is True
    assert plist["StandardOutPath"].endswith("daemon.log")


def test_launch_agent_path(tmp_path: Path) -> None:
    path = service.launch_agent_path(tmp_path)
    assert path == tmp_path / "Library" / "LaunchAgents" / "com.ptaylor.cuisle.plist"


def test_install_and_uninstall(config: Config, tmp_path: Path) -> None:
    runner = FakeRunner({"launchctl": Result(("launchctl",), 0, "", "", 0.0)})
    path = service.install(
        config, runner=runner, executable="/venv/bin/python", home=tmp_path
    )
    assert path.exists()
    assert any(call[1] == "bootstrap" for call in runner.calls)
    removed = service.uninstall(config, runner=runner, home=tmp_path)
    assert not removed.exists()
