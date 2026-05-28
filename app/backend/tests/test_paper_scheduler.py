from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.execution import Order, PaperVenue
from app.paper import PaperScheduler, PaperSchedulerConfig
from app.paper.scheduler import _next_close_utc


def test_next_close_a_share_skips_weekend() -> None:
    sunday = datetime(2024, 5, 5, 10, 0, tzinfo=UTC)  # Sun
    target = _next_close_utc("equity_cn", now=sunday)
    assert target.weekday() < 5


def test_next_close_crypto_returns_next_midnight_utc() -> None:
    noon = datetime(2024, 5, 1, 12, 0, tzinfo=UTC)
    target = _next_close_utc("crypto", now=noon)
    assert target.hour == 0
    assert target.day == 2


def test_tick_once_feeds_bar_and_fills_orders(tmp_path: Path) -> None:
    venue = PaperVenue(cash=10_000, equity_log_path=tmp_path / "equity.log")
    cfg = PaperSchedulerConfig(strategy_id="t1", symbols=["BTC"], bar_interval_seconds=0.01, market="crypto")

    venue.place_order(Order(venue="paper", symbol="BTC", side="buy", quantity=1, order_type="market"))

    def _bar(sym: str):
        return {"symbol": sym, "open": 100, "high": 101, "low": 99, "close": 100.5, "ts": "2024-01-01T00:00:00Z"}

    sched = PaperScheduler(venue, cfg, bar_provider=_bar)
    fills = sched.tick_once()
    assert fills == 1
    assert sched.state.bars_fed == 1
    assert venue.get_position("BTC").quantity == 1


def test_mtm_once_writes_snapshot(tmp_path: Path) -> None:
    venue = PaperVenue(cash=10_000, equity_log_path=tmp_path / "equity.log")
    cfg = PaperSchedulerConfig(strategy_id="t2", symbols=["BTC"], market="crypto")
    venue.place_order(Order(venue="paper", symbol="BTC", side="buy", quantity=1, order_type="market"))
    venue.feed_bar({"symbol": "BTC", "open": 100, "high": 100, "low": 100, "close": 100, "ts": "2024-01-01"})
    sched = PaperScheduler(venue, cfg, bar_provider=lambda _s: None, mark_provider=lambda _: {"BTC": 110})
    snap = sched.mtm_once()
    assert snap.total_equity > 0
    assert sched.state.mtm_count == 1
    assert (tmp_path / "equity.log").exists()


def test_snapshot_exposes_positions_and_balance() -> None:
    venue = PaperVenue(cash=10_000)
    cfg = PaperSchedulerConfig(strategy_id="t3", symbols=["X"], market="crypto")
    sched = PaperScheduler(venue, cfg)
    snap = sched.snapshot()
    assert snap["strategy_id"] == "t3"
    assert "balance" in snap
    assert "positions" in snap
    assert snap["config"]["symbols"] == ["X"]
