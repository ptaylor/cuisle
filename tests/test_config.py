from __future__ import annotations

from pathlib import Path

import pytest

from cuisle.config import (
    Anchor,
    Config,
    ConfigError,
    load_config,
    paths,
    write_default_config,
)


def test_defaults(config: Config) -> None:
    assert config.general.dashboard_host == "127.0.0.1"
    assert config.throughput.backend == "http"
    assert config.anchors[0].name == "test"


def test_load_toml(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[general]
dashboard_port = 9999
[sampling]
process_seconds = 7
[[anchor]]
name = "x"
scope = "europe"
host = "example.test"
health = ["tcp"]
""",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.general.dashboard_port == 9999
    assert cfg.sampling.process_seconds == 7
    assert cfg.anchors[0].name == "x"
    assert cfg.anchors[0].health == ("tcp",)


def test_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUISLE_DATA_DIR", str(tmp_path / "envdata"))
    monkeypatch.setenv("CUISLE_LOG_DIR", str(tmp_path / "envlogs"))
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.data_dir == tmp_path / "envdata"
    assert cfg.log_dir == tmp_path / "envlogs"


def test_bad_scope(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[[anchor]]
name = "x"
scope = "moon"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_remote_dashboard_needs_flag(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[general]\ndashboard_host = "0.0.0.0"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_default_config_roundtrip(tmp_path: Path) -> None:
    path = write_default_config(tmp_path / "config.toml")
    cfg = load_config(path)
    assert {"gateway", "ie-health"}.issubset({a.name for a in cfg.anchors})


def test_paths(config: Config, tmp_path: Path) -> None:
    payload = paths(config)
    assert payload["config"] == str(config.path)
    assert payload["database"].endswith("cuisle.db")
    assert Path(payload["data_dir"]) == tmp_path / "data"


def test_custom_anchor(config: Config) -> None:
    config.anchors.append(
        Anchor(name="iperf", scope="international", host="iperf.test", backend="iperf3")
    )
    assert config.anchor("iperf").resolved_backend() == "iperf3"
