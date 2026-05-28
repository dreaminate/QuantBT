"""v0.8.3.1 hotfix · USDM Futures 条件单走 /fapi/v1/algoOrder。

Binance 2025-12-09 强制迁移：5 类条件单 (STOP_MARKET / TAKE_PROFIT_MARKET / STOP /
TAKE_PROFIT / TRAILING_STOP_MARKET) 必须用 algoOrder endpoint。旧 /fapi/v1/order
收到返回 -4120。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.execution.base import Order
from app.execution.binance_um_futures import BinanceUMFuturesVenue


@pytest.fixture
def venue() -> BinanceUMFuturesVenue:
    client = MagicMock()
    client.product = "usdm_futures"
    # client.signed will be set per-test
    return BinanceUMFuturesVenue(client)


def _capture_signed_call(client_mock: MagicMock) -> list[dict[str, Any]]:
    """记录所有 signed(method, path, params) 调用。"""

    calls: list[dict[str, Any]] = []

    def _record(method: str, path: str, params: dict[str, Any]):
        calls.append({"method": method, "path": path, "params": dict(params)})
        # 默认返回 algoOrder 响应
        if "algoOrder" in path:
            return {"algoId": 999, "algoStatus": "NEW", "clientAlgoId": params.get("clientAlgoId")}
        return {"orderId": 12345, "status": "NEW", "clientOrderId": params.get("newClientOrderId")}

    client_mock.signed.side_effect = _record
    return calls


def test_market_order_still_uses_fapi_v1_order(venue: BinanceUMFuturesVenue):
    calls = _capture_signed_call(venue._client)
    ack = venue.place_order(Order(
        venue="binance_um_futures", symbol="BTCUSDT", side="buy",
        quantity=0.01, order_type="market",
    ))
    assert any(c["path"] == "/fapi/v1/order" for c in calls)
    assert not any("algoOrder" in c["path"] for c in calls)
    assert ack.order_id == "12345"


def test_limit_order_still_uses_fapi_v1_order(venue: BinanceUMFuturesVenue):
    calls = _capture_signed_call(venue._client)
    venue.place_order(Order(
        venue="binance_um_futures", symbol="BTCUSDT", side="buy",
        quantity=0.01, order_type="limit", price=60000.0,
    ))
    order_calls = [c for c in calls if c["path"] == "/fapi/v1/order"]
    assert len(order_calls) == 1
    assert order_calls[0]["params"]["type"] == "LIMIT"
    assert order_calls[0]["params"]["timeInForce"] == "GTC"
    assert "newClientOrderId" in order_calls[0]["params"]


def test_stop_market_routes_to_algo_order(venue: BinanceUMFuturesVenue):
    calls = _capture_signed_call(venue._client)
    ack = venue.place_order(Order(
        venue="binance_um_futures", symbol="BTCUSDT", side="sell",
        quantity=0.01, order_type="stop_market", stop_price=58000.0,
    ))
    algo_calls = [c for c in calls if c["path"] == "/fapi/v1/algoOrder"]
    legacy_calls = [c for c in calls if c["path"] == "/fapi/v1/order"]
    assert len(algo_calls) == 1, f"expected 1 algoOrder call, got {algo_calls}"
    assert len(legacy_calls) == 0, "STOP_MARKET 必须不走旧 endpoint（会返回 -4120）"
    params = algo_calls[0]["params"]
    assert params["algoType"] == "CONDITIONAL"
    assert params["type"] == "STOP_MARKET"
    assert "clientAlgoId" in params, "新 endpoint 用 clientAlgoId 而非 newClientOrderId"
    assert "newClientOrderId" not in params
    assert params["triggerPrice"] == 58000.0, "新 endpoint 用 triggerPrice 而非 stopPrice"
    assert "stopPrice" not in params
    # 响应解析 algoId 而非 orderId
    assert ack.order_id == "999"


def test_take_profit_market_routes_to_algo_order(venue: BinanceUMFuturesVenue):
    calls = _capture_signed_call(venue._client)
    # type map 中 "take_profit" → "TAKE_PROFIT"，这是条件单
    venue.place_order(Order(
        venue="binance_um_futures", symbol="ETHUSDT", side="sell",
        quantity=0.1, order_type="take_profit", stop_price=4000.0, price=3950.0,
    ))
    algo_calls = [c for c in calls if c["path"] == "/fapi/v1/algoOrder"]
    assert len(algo_calls) == 1
    assert algo_calls[0]["params"]["type"] == "TAKE_PROFIT"


def test_stop_aka_stop_loss_routes_to_algo_order(venue: BinanceUMFuturesVenue):
    """order_type=stop_loss → binance type STOP（带 price 的条件 limit 单）"""

    calls = _capture_signed_call(venue._client)
    venue.place_order(Order(
        venue="binance_um_futures", symbol="BTCUSDT", side="sell",
        quantity=0.01, order_type="stop_loss", stop_price=58000.0, price=57500.0,
    ))
    algo_calls = [c for c in calls if c["path"] == "/fapi/v1/algoOrder"]
    assert len(algo_calls) == 1
    assert algo_calls[0]["params"]["type"] == "STOP"


def test_trailing_stop_market_routes_to_algo_order_with_callback_rate(venue: BinanceUMFuturesVenue):
    calls = _capture_signed_call(venue._client)
    venue.place_order(Order(
        venue="binance_um_futures", symbol="BTCUSDT", side="sell",
        quantity=0.01, order_type="trailing_stop_market", price=60000.0,
    ))
    algo_calls = [c for c in calls if c["path"] == "/fapi/v1/algoOrder"]
    assert len(algo_calls) == 1
    params = algo_calls[0]["params"]
    assert params["type"] == "TRAILING_STOP_MARKET"
    assert "callbackRate" in params
    # price → activatePrice 重命名
    assert "activatePrice" in params
    assert "price" not in params


def test_close_position_excludes_quantity(venue: BinanceUMFuturesVenue):
    """closePosition=true 与 quantity 互斥（Binance 文档约束）。"""

    calls = _capture_signed_call(venue._client)
    venue.place_order(Order(
        venue="binance_um_futures", symbol="BTCUSDT", side="sell",
        quantity=0.01, order_type="stop_market", stop_price=58000.0,
        close_position=True,
    ))
    algo_call = next(c for c in calls if c["path"] == "/fapi/v1/algoOrder")
    params = algo_call["params"]
    assert params.get("closePosition") == "true"
    assert "quantity" not in params, "closePosition=true 时不能带 quantity"


def test_algo_response_marks_qb_algo_flag(venue: BinanceUMFuturesVenue):
    _capture_signed_call(venue._client)
    ack = venue.place_order(Order(
        venue="binance_um_futures", symbol="BTCUSDT", side="sell",
        quantity=0.01, order_type="stop_market", stop_price=58000.0,
    ))
    assert ack.raw.get("_qb_algo") is True, "算法单需打 _qb_algo 标记，便于 cancel 路由"


def test_cancel_algo_order_uses_algo_id(venue: BinanceUMFuturesVenue):
    calls = _capture_signed_call(venue._client)
    venue.cancel_algo_order("999", "BTCUSDT")
    cancel_calls = [c for c in calls if c["path"] == "/fapi/v1/algoOrder" and c["method"] == "DELETE"]
    assert len(cancel_calls) == 1
    assert cancel_calls[0]["params"]["algoId"] == "999"
    assert cancel_calls[0]["params"]["symbol"] == "BTCUSDT"
