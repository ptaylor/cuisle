"""Periodic throughput tests."""

from __future__ import annotations

from cuisle.backends import run_all_throughput
from cuisle.config import Anchor, Config
from cuisle.model import ActiveLink, ThroughputSample
from cuisle.runner import Runner


def sample_throughput(
    config: Config,
    runner: Runner,
    active: ActiveLink | None,
    ts: int,
    anchors: list[Anchor] | None = None,
    include_networkquality: bool = True,
) -> list[ThroughputSample]:
    return run_all_throughput(
        config,
        runner,
        ts,
        active.ifname if active else None,
        anchors=anchors,
        include_networkquality=include_networkquality,
    )
