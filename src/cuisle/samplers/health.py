"""Health probes for the configured anchors."""

from __future__ import annotations

from cuisle.config import Config
from cuisle.model import ActiveLink, ProbeSample
from cuisle.probes import run_anchor_health
from cuisle.runner import Runner


def sample_health(
    config: Config, runner: Runner, active: ActiveLink, ts: int
) -> list[ProbeSample]:
    samples: list[ProbeSample] = []
    for anchor in config.enabled_anchors():
        if not anchor.health:
            continue
        samples.extend(
            run_anchor_health(
                anchor,
                active.gateway,
                active.ifname,
                ts,
                runner,
            )
        )
    return samples
