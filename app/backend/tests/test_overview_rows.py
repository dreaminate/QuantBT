# -*- coding: utf-8 -*-
"""build_overview_rows 与 RunDetailPage.tsx 手算预期 / fixture 对齐。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from run_detail_research_export import (
    OverviewRow,
    build_overview_rows,
    export_run_bundle_for_detail,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _assert_row_close(a: OverviewRow, b: dict) -> None:
    assert a["date"] == b["date"]
    for key in ("strategy_return", "benchmark_return", "excess_daily", "turnover", "daily_buy", "daily_sell"):
        av = a.get(key)
        bv = b.get(key)
        if av is None and bv is None:
            continue
        if av is None or bv is None:
            assert av == bv
        else:
            assert av == pytest.approx(bv)


def test_build_overview_rows_from_json_fixture() -> None:
    data = json.loads((_FIXTURES / "overview_basic.json").read_text(encoding="utf-8-sig"))
    rows = build_overview_rows(
        data["equity"],
        data["benchmark"],
        data["turnover"],
        data["daily_buy"],
        data["daily_sell"],
    )
    assert len(rows) == len(data["expected"])
    for got, exp in zip(rows, data["expected"], strict=True):
        _assert_row_close(got, exp)


def test_turnover_buy_sell_maps_by_date() -> None:
    equity = [
        {"timestamp": "2026-01-01T00:00:00Z", "value": 100},
        {"timestamp": "2026-01-02T00:00:00Z", "value": 100},
    ]
    bench = [{"timestamp": "2026-01-01T00:00:00Z", "value": 0}]
    turnover = [{"timestamp": "2026-01-02T00:00:00Z", "value": 0.05}]
    buy = [{"timestamp": "2026-01-01T00:00:00Z", "value": 1000}]
    sell = [{"timestamp": "2026-01-02T00:00:00Z", "value": 500}]
    rows = build_overview_rows(equity, bench, turnover, buy, sell)
    by_date = {r["date"]: r for r in rows}
    assert by_date["2026-01-01"]["turnover"] is None
    assert by_date["2026-01-01"]["daily_buy"] == pytest.approx(1000.0)
    assert by_date["2026-01-02"]["turnover"] == pytest.approx(0.05)
    assert by_date["2026-01-02"]["daily_sell"] == pytest.approx(500.0)


def test_export_run_bundle_for_detail_writes_under_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import run_detail_research_export as rde

    monkeypatch.setattr(rde, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(rde, "ensure_runtime_dirs", lambda: None)

    portfolio = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02"],
            "equity": [1.0, 1.01],
        }
    )
    manifest = {"run_id": "pytest-export", "status": "completed", "strategy_name": "t"}
    root = export_run_bundle_for_detail(
        "pytest-export",
        manifest,
        portfolio,
        overwrite=True,
        report_md="# hi",
    )
    assert root == tmp_path / "pytest-export"
    assert (root / "run.json").is_file()
    assert (root / "portfolio.csv").is_file()
    assert (root / "report.md").read_text(encoding="utf-8") == "# hi"
