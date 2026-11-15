from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from cuisle import cli as cli_module
from cuisle.cli import main


def env(tmp_path: Path) -> dict[str, str]:
    return {
        "CUISLE_CONFIG_DIR": str(tmp_path / "config"),
        "CUISLE_DATA_DIR": str(tmp_path / "data"),
        "CUISLE_LOG_DIR": str(tmp_path / "logs"),
    }


def test_paths_json(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["paths", "--json"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["database"].endswith("cuisle.db")
    assert payload["config"].endswith("config.toml")


def test_status_without_database(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["status"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "No samples yet" in result.output


def test_config_show_creates_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["config", "--show"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "[general]" in result.output
    assert (tmp_path / "config" / "config.toml").is_file()


def test_history_without_database(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main, ["history", "--metric", "cpu_pct"], env=env(tmp_path)
    )
    assert result.exit_code == 0, result.output
    assert "No samples yet" in result.output


def test_dashboard_opens_browser_by_default(
    tmp_path: Path, monkeypatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("cuisle.server.is_running", lambda host, port: True)
    monkeypatch.setattr(cli_module.webbrowser, "open", lambda url: opened.append(url) or True)
    result = CliRunner().invoke(main, ["dashboard"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert opened
    assert opened[0].startswith("http://127.0.0.1:8787/")


def test_dashboard_no_open(tmp_path: Path, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("cuisle.server.is_running", lambda host, port: True)
    monkeypatch.setattr(cli_module.webbrowser, "open", lambda url: opened.append(url) or True)
    result = CliRunner().invoke(main, ["dashboard", "--no-open"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert opened == []
