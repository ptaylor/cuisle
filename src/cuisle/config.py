"""Configuration loading, validation and path resolution."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

APP_NAME = "cuisle"
LAUNCHD_LABEL = "com.ptaylor.cuisle"
SCOPES = ("lan", "country", "europe", "international")
HEALTH_METHODS = ("icmp", "dns", "tcp", "tls", "http")
BACKENDS = ("http", "speedtest", "iperf3")
DIRECTIONS = ("up", "down", "both")


class ConfigError(ValueError):
    """A configuration file cannot be used."""


def _default_config_path() -> Path:
    override = os.environ.get("CUISLE_CONFIG_DIR")
    if override:
        return Path(override).expanduser() / "config.toml"
    return Path("~/.config/cuisle/config.toml").expanduser()


def _default_data_dir() -> Path:
    override = os.environ.get("CUISLE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path("~/.local/share/cuisle").expanduser()


def _default_log_dir() -> Path:
    override = os.environ.get("CUISLE_LOG_DIR")
    if override:
        return Path(override).expanduser()
    return Path("~/Library/Logs/cuisle").expanduser()


def plist_path() -> Path:
    return Path("~/Library/LaunchAgents").expanduser() / f"{LAUNCHD_LABEL}.plist"


def _default_anchors() -> list[Anchor]:
    return [
        Anchor(name="gateway", scope="lan", health=("icmp",)),
        Anchor(
            name="ie-health",
            scope="country",
            host="www.heanet.ie",
            port=443,
            url="https://www.heanet.ie/",
            health=("dns", "tcp", "tls", "http"),
        ),
        Anchor(
            name="eu-throughput",
            scope="europe",
            host="ftp.funet.fi",
            port=443,
            url="https://ftp.funet.fi/",
            download_url=(
                "https://ftp.funet.fi/pub/linux/mirrors/debian/dists/stable/main/"
                "Contents-amd64.gz"
            ),
            health=("dns", "tcp", "tls", "http"),
        ),
        Anchor(
            name="world-throughput",
            scope="international",
            host="debian.osuosl.org",
            port=443,
            url="https://debian.osuosl.org/debian/",
            download_url=(
                "https://debian.osuosl.org/debian/dists/stable/main/Contents-amd64.gz"
            ),
            health=("dns", "tcp", "tls", "http"),
        ),
    ]


@dataclass
class GeneralConfig:
    data_dir: Path = field(default_factory=_default_data_dir)
    log_dir: Path = field(default_factory=_default_log_dir)
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8787
    dashboard_enabled: bool = True
    allow_remote_dashboard: bool = False


@dataclass
class RetentionConfig:
    raw_days: int = 7
    five_minute_days: int = 90
    hourly_days: int = 365


@dataclass
class SamplingConfig:
    process_seconds: int = 5
    connection_seconds: int = 10
    interface_seconds: int = 10
    health_seconds: int = 30
    throughput_seconds: int = 21600
    networkquality_seconds: int = 43200
    process_top_n: int = 15


@dataclass
class BatteryConfig:
    pause_throughput: bool = True
    pause_networkquality: bool = True
    slow_health_seconds: int = 60


@dataclass
class ThroughputConfig:
    backend: str = "http"
    download_bytes: int = 1_000_000
    upload_bytes: int = 256_000
    timeout_seconds: int = 30
    allow_expensive: bool = False


@dataclass
class Anchor:
    name: str
    scope: str = "country"
    host: str | None = None
    port: int | None = 443
    url: str | None = None
    download_url: str | None = None
    upload_url: str | None = None
    backend: str | None = None
    server_id: int | None = None
    duration_seconds: int = 10
    direction: str = "both"
    health: tuple[str, ...] = ("dns", "tcp", "tls", "http")
    enabled: bool = True

    def resolved_backend(self, default: str = "http") -> str:
        return self.backend or default

    def as_dict(self, default_backend: str = "http") -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope,
            "host": self.host,
            "port": self.port,
            "url": self.url,
            "download_url": self.download_url,
            "upload_url": self.upload_url,
            "backend": self.resolved_backend(default_backend),
            "server_id": self.server_id,
            "duration_seconds": self.duration_seconds,
            "direction": self.direction,
            "health": list(self.health),
            "enabled": self.enabled,
        }


@dataclass
class Config:
    path: Path
    general: GeneralConfig = field(default_factory=GeneralConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    throughput: ThroughputConfig = field(default_factory=ThroughputConfig)
    anchors: list[Anchor] = field(default_factory=_default_anchors)

    @property
    def data_dir(self) -> Path:
        return self.general.data_dir

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cuisle.db"

    @property
    def log_dir(self) -> Path:
        return self.general.log_dir

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def enabled_anchors(self) -> list[Anchor]:
        return [a for a in self.anchors if a.enabled]

    def anchor(self, name: str) -> Anchor:
        for anchor in self.anchors:
            if anchor.name == name:
                return anchor
        raise KeyError(f"unknown anchor: {name}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "general": {
                "data_dir": str(self.general.data_dir),
                "log_dir": str(self.general.log_dir),
                "dashboard_host": self.general.dashboard_host,
                "dashboard_port": self.general.dashboard_port,
                "dashboard_enabled": self.general.dashboard_enabled,
                "allow_remote_dashboard": self.general.allow_remote_dashboard,
            },
            "retention": self.retention.__dict__,
            "sampling": self.sampling.__dict__,
            "battery": self.battery.__dict__,
            "throughput": self.throughput.__dict__,
            "anchors": [a.as_dict(self.throughput.backend) for a in self.anchors],
        }


def _build(cls: type, mapping: dict[str, Any]) -> Any:
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in mapping.items() if k in names})


def _build_anchor(mapping: dict[str, Any]) -> Anchor:
    known = {f.name for f in fields(Anchor)}
    values = {k: v for k, v in mapping.items() if k in known}
    if "health" in values:
        values["health"] = tuple(str(v) for v in values["health"])
    return Anchor(**values)


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path).expanduser() if path else _default_config_path()
    config = Config(path=config_path)

    if not config_path.is_file():
        return config

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {config_path}: {exc}") from exc

    general = _build(GeneralConfig, raw.get("general", {}))
    if "data_dir" in raw.get("general", {}):
        general.data_dir = Path(general.data_dir).expanduser()
    if "log_dir" in raw.get("general", {}):
        general.log_dir = Path(general.log_dir).expanduser()
    if os.environ.get("CUISLE_DATA_DIR"):
        general.data_dir = Path(os.environ["CUISLE_DATA_DIR"]).expanduser()
    if os.environ.get("CUISLE_LOG_DIR"):
        general.log_dir = Path(os.environ["CUISLE_LOG_DIR"]).expanduser()

    config = Config(
        path=config_path,
        general=general,
        retention=_build(RetentionConfig, raw.get("retention", {})),
        sampling=_build(SamplingConfig, raw.get("sampling", {})),
        battery=_build(BatteryConfig, raw.get("battery", {})),
        throughput=_build(ThroughputConfig, raw.get("throughput", {})),
        anchors=(
            [_build_anchor(a) for a in raw.get("anchor", [])]
            if "anchor" in raw
            else _default_anchors()
        ),
    )
    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    errors: list[str] = []
    intervals = [
        ("process_seconds", config.sampling.process_seconds),
        ("connection_seconds", config.sampling.connection_seconds),
        ("interface_seconds", config.sampling.interface_seconds),
        ("health_seconds", config.sampling.health_seconds),
        ("throughput_seconds", config.sampling.throughput_seconds),
        ("networkquality_seconds", config.sampling.networkquality_seconds),
        ("slow_health_seconds", config.battery.slow_health_seconds),
    ]
    for name, value in intervals:
        if not isinstance(value, int) or value <= 0:
            errors.append(f"{name} must be a positive integer")
    if not 1 <= config.general.dashboard_port <= 65535:
        errors.append("dashboard_port must be between 1 and 65535")
    if config.general.dashboard_host not in ("127.0.0.1", "localhost", "::1") and not (
        config.general.allow_remote_dashboard
    ):
        errors.append(
            "dashboard_host is not loopback; set allow_remote_dashboard=true to permit it"
        )
    if config.throughput.backend not in BACKENDS:
        errors.append(f"throughput.backend must be one of {BACKENDS}")
    if config.throughput.download_bytes <= 0 or config.throughput.upload_bytes <= 0:
        errors.append("throughput byte counts must be positive")
    if config.throughput.timeout_seconds <= 0:
        errors.append("throughput.timeout_seconds must be positive")
    names: set[str] = set()
    for anchor in config.anchors:
        if not anchor.name:
            errors.append("every anchor needs a name")
            continue
        if anchor.name in names:
            errors.append(f"duplicate anchor name: {anchor.name}")
        names.add(anchor.name)
        if anchor.scope not in SCOPES:
            errors.append(f"{anchor.name}: scope must be one of {SCOPES}")
        if anchor.resolved_backend(config.throughput.backend) not in BACKENDS:
            errors.append(f"{anchor.name}: backend must be one of {BACKENDS}")
        if anchor.direction not in DIRECTIONS:
            errors.append(f"{anchor.name}: direction must be one of {DIRECTIONS}")
        for method in anchor.health:
            if method not in HEALTH_METHODS:
                errors.append(f"{anchor.name}: unknown health method {method}")
        if anchor.port is not None and not 1 <= anchor.port <= 65535:
            errors.append(f"{anchor.name}: port must be between 1 and 65535")
        if anchor.duration_seconds <= 0:
            errors.append(f"{anchor.name}: duration_seconds must be positive")
        backend = anchor.resolved_backend(config.throughput.backend)
        if backend == "iperf3" and not anchor.host:
            errors.append(f"{anchor.name}: iperf3 needs a host")
    if errors:
        raise ConfigError("; ".join(errors))


def ensure_dirs(config: Config) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)


def paths(config: Config) -> dict[str, str]:
    return {
        "config": str(config.path),
        "data_dir": str(config.data_dir),
        "database": str(config.db_path),
        "log_dir": str(config.log_dir),
        "plist": str(plist_path()),
    }


DEFAULT_CONFIG_TEXT = """\
# Cuisle configuration. Every scalar setting has a default.
[general]
data_dir = "~/.local/share/cuisle"
log_dir = "~/Library/Logs/cuisle"
dashboard_host = "127.0.0.1"
dashboard_port = 8787
dashboard_enabled = true
allow_remote_dashboard = false

[retention]
raw_days = 7
five_minute_days = 90
hourly_days = 365

[sampling]
process_seconds = 5
connection_seconds = 10
interface_seconds = 10
health_seconds = 30
throughput_seconds = 21600
networkquality_seconds = 43200
process_top_n = 15

[battery]
pause_throughput = true
pause_networkquality = true
slow_health_seconds = 60

[throughput]
backend = "http"
download_bytes = 1000000
upload_bytes = 256000
timeout_seconds = 30
allow_expensive = false

[[anchor]]
name = "gateway"
scope = "lan"
health = ["icmp"]

[[anchor]]
name = "ie-health"
scope = "country"
host = "www.heanet.ie"
port = 443
url = "https://www.heanet.ie/"
health = ["dns", "tcp", "tls", "http"]

[[anchor]]
name = "eu-throughput"
scope = "europe"
host = "ftp.funet.fi"
port = 443
url = "https://ftp.funet.fi/"
health = ["dns", "tcp", "tls", "http"]
download_url = "https://ftp.funet.fi/pub/linux/mirrors/debian/dists/stable/main/Contents-amd64.gz"

[[anchor]]
name = "world-throughput"
scope = "international"
host = "debian.osuosl.org"
port = 443
url = "https://debian.osuosl.org/debian/"
health = ["dns", "tcp", "tls", "http"]
download_url = "https://debian.osuosl.org/debian/dists/stable/main/Contents-amd64.gz"
"""


def write_default_config(path: str | Path | None = None) -> Path:
    config_path = Path(path).expanduser() if path else _default_config_path()
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return config_path
