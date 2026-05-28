from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.monitor.cost_drift import compute_weekly_cost_drift, write_weekly_report


def _audit_records() -> list[dict]:
    base = datetime(2024, 5, 1, tzinfo=UTC)  # Wed of W18
    return [
        {
            "kind": "fill",
            "logged_at_utc": (base).isoformat(),
            "payload": {"symbol": "BTC", "filled_qty": 1, "fill_price": 30000, "commission": 30},
        },
        {
            "kind": "fill",
            "logged_at_utc": (base + timedelta(days=1)).isoformat(),
            "payload": {"symbol": "ETH", "filled_qty": 10, "fill_price": 2000, "commission": 25},
        },
        {
            "kind": "binance_um_place",  # 应被忽略（不是 fill）
            "logged_at_utc": base.isoformat(),
            "payload": {"symbol": "BTC"},
        },
        {
            "kind": "fill",
            "logged_at_utc": (base - timedelta(days=30)).isoformat(),  # 不在本周
            "payload": {"symbol": "BTC", "filled_qty": 1, "fill_price": 25000, "commission": 25},
        },
    ]


def test_weekly_drift_filters_by_week_and_computes_per_symbol() -> None:
    records = _audit_records()
    report = compute_weekly_cost_drift(records, week=date(2024, 5, 1), asset_class="crypto_perp")
    assert report.n_fills == 2
    assert set(report.by_symbol) == {"BTC", "ETH"}
    assert report.by_symbol["BTC"]["actual"] == 30
    assert report.by_symbol["ETH"]["actual"] == 25
    # expected: (4+2)bps * 30000 + funding 3bps * 30000 = 18 + 9 = 27
    assert abs(report.by_symbol["BTC"]["expected"] - 27.0) < 0.01


def test_weekly_drift_pct_when_no_actual() -> None:
    report = compute_weekly_cost_drift([], week=date(2024, 5, 1))
    assert report.n_fills == 0
    assert report.drift_pct is None


def test_weekly_drift_warns_when_over_30pct() -> None:
    records = [
        {
            "kind": "fill",
            "logged_at_utc": datetime(2024, 5, 1, tzinfo=UTC).isoformat(),
            "payload": {"symbol": "BTC", "filled_qty": 1, "fill_price": 30000, "commission": 1000},  # 远超预期
        }
    ]
    report = compute_weekly_cost_drift(records, week=date(2024, 5, 1))
    assert any("⚠️" in n for n in report.notes)


def test_write_markdown_creates_file(tmp_path: Path) -> None:
    report = compute_weekly_cost_drift(_audit_records(), week=date(2024, 5, 1))
    target = write_weekly_report(report, tmp_path)
    assert target.exists()
    body = target.read_text(encoding="utf-8")
    assert "成本偏差报告" in body
    assert "| BTC" in body
