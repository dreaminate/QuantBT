from __future__ import annotations

import os
from pathlib import Path

from app.paths import DATA_ROOT, PROJECT_ROOT


def test_pytest_runtime_root_is_isolated_from_shared_project_data() -> None:
    configured = Path(os.environ["BACKTEST_DATA_ROOT"]).resolve()
    shared = (PROJECT_ROOT / "data").resolve()

    assert DATA_ROOT == configured
    assert DATA_ROOT != shared
    assert (DATA_ROOT / "audit").resolve() != (shared / "audit").resolve()
    assert DATA_ROOT.name.startswith("quantbt-pytest-data-")


def test_pytest_runtime_root_seeds_required_read_only_fixtures_only() -> None:
    assert (DATA_ROOT / "samples" / "crypto" / "BTCUSDT_1d.csv").is_file()
    assert (DATA_ROOT / "artifacts" / "experiments" / "demo" / "run.json").is_file()
