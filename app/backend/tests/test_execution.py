from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import polars as pl
import pytest

from app.execution import (
    BacktestCostModel,
    BacktestVenue,
    GenericTradingConfig,
    GenericTradingVenue,
    Order,
    PaperVenue,
)


def _ohlcv(n_days: int = 5) -> pl.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n_days):
        ts = base + timedelta(days=i)
        rows.append({"ts": ts, "symbol": "BTC", "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i})
    return pl.DataFrame(rows)


def test_backtest_venue_market_fill_and_audit() -> None:
    venue = BacktestVenue(_ohlcv())
    ack = venue.place_order(Order(venue="backtest", symbol="BTC", side="buy", quantity=1, order_type="market"))
    assert ack.status == "new"
    reports = venue.step()
    assert len(reports) == 1
    assert reports[0]["filled_qty"] == 1
    pos = venue.get_position("BTC")
    assert pos.quantity == 1
    assert any(r["kind"] == "fill" for r in venue.audit.export())


def test_backtest_venue_limit_no_touch_stays_open() -> None:
    venue = BacktestVenue(_ohlcv())
    venue.place_order(Order(venue="backtest", symbol="BTC", side="buy", quantity=1, order_type="limit", price=50.0))
    reports = venue.step()
    assert reports == []
    assert venue.get_position("BTC").quantity == 0


def test_backtest_venue_cost_model_charges_commission() -> None:
    cost = BacktestCostModel(commission_bps=10, slippage_bps=5)
    venue = BacktestVenue(_ohlcv(), cost_model=cost, cash=1000)
    venue.place_order(Order(venue="backtest", symbol="BTC", side="buy", quantity=2, order_type="market"))
    venue.step()
    bal = venue.get_balance()
    # 现金减少 = 名义 + 成本
    assert bal["USDT"].free < 1000


def test_paper_venue_feed_bar_and_mark_to_market(tmp_path) -> None:
    log = tmp_path / "equity.log"
    venue = PaperVenue(cash=1000, equity_log_path=log)
    venue.place_order(Order(venue="paper", symbol="BTC", side="buy", quantity=1, order_type="market"))
    fills = venue.feed_bar({"symbol": "BTC", "open": 100, "high": 101, "low": 99, "close": 100.5, "ts": "2024-01-01"})
    assert fills and fills[0]["filled_qty"] == 1
    snap = venue.mark_to_market({"BTC": 110})
    assert snap.total_equity > 0
    assert log.exists()


def test_generic_trading_venue_mocked_place_and_cancel() -> None:
    yaml_text = """
venue_name: my_dex
label: My Custom DEX
base_url: https://dex.invalid
auth:
  mode: header
  header_name: X-API-KEY
  value_env: TEST_DEX_KEY
place_order:
  method: POST
  path: /api/order
  body_template: {symbol: "{symbol}", side: "{side}", qty: "{quantity}", cid: "{client_order_id}"}
cancel_order:
  method: DELETE
  path: /api/order/{order_id}
get_balance:
  method: GET
  path: /api/balances
get_position:
  method: GET
  path: /api/position/{symbol}
permission_check:
  method: GET
  path: /api/permissions
blacklist_symbols: [SCAM]
per_order_max_notional: 1000
"""
    cfg = GenericTradingConfig.from_yaml(yaml_text)
    session = MagicMock()
    place_resp = MagicMock()
    place_resp.json.return_value = {"order_id": "abc-123", "status": "new"}
    place_resp.raise_for_status.return_value = None
    cancel_resp = MagicMock()
    cancel_resp.json.return_value = {"canceled": True}
    cancel_resp.raise_for_status.return_value = None
    permission_resp = MagicMock()
    permission_resp.json.return_value = {"can_trade": True, "can_withdraw": False}
    permission_resp.raise_for_status.return_value = None

    def _request_side_effect(method, url, **_):
        if "permissions" in url:
            return permission_resp
        if method == "DELETE":
            return cancel_resp
        return place_resp

    session.request.side_effect = _request_side_effect
    venue = GenericTradingVenue(cfg, http=session)
    assert venue.assert_safe_startup()["ok"]
    ack = venue.place_order(Order(venue="my_dex", symbol="BTC", side="buy", quantity=1, price=100))
    assert ack.order_id == "abc-123"
    cancel = venue.cancel_order("abc-123")
    assert cancel.order_id == "abc-123"
    with pytest.raises(PermissionError, match="blacklist"):
        venue.place_order(Order(venue="my_dex", symbol="SCAM", side="buy", quantity=1))
    with pytest.raises(PermissionError, match="单笔"):
        venue.place_order(Order(venue="my_dex", symbol="BTC", side="buy", quantity=100, price=100))


def test_generic_trading_rejects_withdraw_permission() -> None:
    yaml_text = """
venue_name: dangerous
base_url: https://invalid
place_order: {path: /place}
cancel_order: {path: /cancel, method: DELETE}
get_balance: {path: /bal, method: GET}
get_position: {path: /pos, method: GET}
permission_check: {path: /perm, method: GET}
"""
    cfg = GenericTradingConfig.from_yaml(yaml_text)
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"can_trade": True, "can_withdraw": True}
    resp.raise_for_status.return_value = None
    session.request.return_value = resp
    venue = GenericTradingVenue(cfg, http=session)
    with pytest.raises(PermissionError, match="withdraw"):
        venue.assert_safe_startup()


def test_generic_trading_rejects_missing_permission_check_instead_of_false_ok() -> None:
    cfg = GenericTradingConfig(
        venue_name="unchecked",
        base_url="https://invalid",
        place_order={"path": "/place"},
        cancel_order={"path": "/cancel", "method": "DELETE"},
        get_balance={"path": "/bal", "method": "GET"},
        get_position={"path": "/pos", "method": "GET"},
    )

    with pytest.raises(PermissionError, match="permission_check"):
        GenericTradingVenue(cfg).assert_safe_startup()


def test_execution_venue_default_health_check_is_not_a_hardcoded_success() -> None:
    with pytest.raises(NotImplementedError, match="venue-native health check"):
        PaperVenue().health_check()
