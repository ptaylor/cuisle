from __future__ import annotations

import time
from pathlib import Path

from cuisle.config import Config
from cuisle.report import generate_report


def test_report_defaults_to_cwd(
    tmp_path: Path, sample_db: Config, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = generate_report(sample_db, int(time.time() * 1000) - 3_600_000)
    assert path.parent == tmp_path / "reports"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Cuisle report" in text
    assert "en0" in text


def test_report_output_override(tmp_path: Path, sample_db: Config) -> None:
    target = tmp_path / "custom-report.html"
    path = generate_report(sample_db, int(time.time() * 1000) - 3_600_000, target)
    assert path == target
    assert target.is_file()
