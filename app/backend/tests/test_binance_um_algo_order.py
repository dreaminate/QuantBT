"""v0.8.3.1 hotfix · USDM Futures 条件单走 /fapi/v1/algoOrder。

Binance 2025-12-09 强制迁移：5 类条件单 (STOP_MARKET / TAKE_PROFIT_MARKET / STOP /
TAKE_PROFIT / TRAILING_STOP_MARKET) 必须用 algoOrder endpoint。旧 /fapi/v1/order
收到返回 -4120。
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.execution.base import Order, Position
from app.execution.binance_client import BinanceAPIError
from app.execution.binance_um_futures import BinanceUMFuturesVenue, FuturesSymbolFilters
from app.execution.emergency_journal import (
    emergency_close_request_hash,
    emergency_close_request_params,
)


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
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if path == "/fapi/v1/algoOrder" and method == "DELETE":
            return {
                "algoId": int(params["algoId"]),
                "code": 200,
            }
        if path == "/fapi/v1/algoOrder":
            return {
                "algoId": 999,
                "clientAlgoId": params.get("clientAlgoId"),
                "algoType": "CONDITIONAL",
                "orderType": params.get("type"),
                "quantity": str(params.get("quantity", 0)),
                "algoStatus": "NEW",
                "symbol": params.get("symbol"),
                "side": params.get("side"),
                "positionSide": "BOTH",
                "reduceOnly": params.get("reduceOnly") == "true",
                "closePosition": params.get("closePosition") == "true",
                "updateTime": 1_800_000_000_000,
            }
        return {
            "orderId": 12345,
            "status": "NEW",
            "clientOrderId": params.get("newClientOrderId"),
            "symbol": params.get("symbol"),
            "side": params.get("side"),
            "type": params.get("type"),
            "positionSide": "BOTH",
            "reduceOnly": params.get("reduceOnly") == "true",
            "closePosition": False,
            "origQty": str(params.get("quantity")),
            "executedQty": "0",
            "updateTime": 1_800_000_000_000,
        }

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
    venue.place_order(Order(
        venue="binance_um_futures", symbol="ETHUSDT", side="sell",
        quantity=0.1, order_type="take_profit_market", stop_price=4000.0,
    ))
    algo_calls = [c for c in calls if c["path"] == "/fapi/v1/algoOrder"]
    assert len(algo_calls) == 1
    assert algo_calls[0]["params"]["type"] == "TAKE_PROFIT_MARKET"


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
    assert "symbol" not in cancel_calls[0]["params"]


def test_standard_order_response_never_fabricates_missing_venue_id(
    venue: BinanceUMFuturesVenue,
) -> None:
    def signed(_method: str, path: str, params: dict[str, Any]):
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if path == "/fapi/v1/order":
            return {
                "status": "NEW",
                "clientOrderId": params["newClientOrderId"],
            }
        raise AssertionError(path)

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match="lacks venue orderId"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="buy",
                quantity=0.01,
                order_type="market",
            )
        )


def test_algo_order_response_rejects_client_identity_mismatch(
    venue: BinanceUMFuturesVenue,
) -> None:
    def signed(_method: str, path: str, _params: dict[str, Any]):
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if path == "/fapi/v1/algoOrder":
            return {"algoId": 1, "clientAlgoId": "wrong", "algoStatus": "NEW"}
        raise AssertionError(path)

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match="clientAlgoId mismatch"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="sell",
                quantity=0.01,
                order_type="stop_market",
                stop_price=50_000,
                client_order_id="expected",
            )
        )


def test_standard_order_response_binds_symbol_side_type_quantity_and_flags(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls = _capture_signed_call(venue._client)
    original = venue._client.signed.side_effect

    def signed(method: str, path: str, params: dict[str, Any]):
        response = original(method, path, params)
        if method == "POST" and path == "/fapi/v1/order":
            return {**response, "symbol": "ETHUSDT"}
        return response

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match="symbol mismatch"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="buy",
                quantity=0.01,
                order_type="market",
            )
        )
    assert any(method["path"] == "/fapi/v1/order" for method in calls)


def test_algo_order_response_binds_quantity_and_order_type(
    venue: BinanceUMFuturesVenue,
) -> None:
    _capture_signed_call(venue._client)
    original = venue._client.signed.side_effect

    def signed(method: str, path: str, params: dict[str, Any]):
        response = original(method, path, params)
        if method == "POST" and path == "/fapi/v1/algoOrder":
            return {**response, "quantity": "0.02"}
        return response

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match="quantity mismatch"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="sell",
                quantity=0.01,
                order_type="stop_market",
                stop_price=50_000,
            )
        )


def test_close_position_algo_rejects_reduce_only_contradiction_before_post(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls = _capture_signed_call(venue._client)
    with pytest.raises(ValueError, match="cannot also set reduceOnly"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="sell",
                quantity=0.01,
                order_type="stop_market",
                stop_price=50_000,
                close_position=True,
                reduce_only=True,
            )
        )
    assert not any(call["method"] == "POST" and call["path"] == "/fapi/v1/algoOrder" for call in calls)


def test_close_position_is_limited_to_documented_market_trigger_types(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls = _capture_signed_call(venue._client)
    with pytest.raises(ValueError, match="STOP_MARKET or TAKE_PROFIT_MARKET"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="sell",
                quantity=0.01,
                order_type="trailing_stop_market",
                close_position=True,
            )
        )
    assert not any(call["method"] == "POST" and call["path"] == "/fapi/v1/algoOrder" for call in calls)


def test_fractional_leverage_is_not_silently_truncated(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls = _capture_signed_call(venue._client)
    with pytest.raises(ValueError, match="positive integer"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="buy",
                quantity=0.01,
                order_type="market",
                leverage=2.5,
            )
        )
    assert not any(call["method"] == "POST" for call in calls)


def test_config_failure_before_order_request_does_not_cross_submit_boundary(
    venue: BinanceUMFuturesVenue,
) -> None:
    paths: list[str] = []
    boundary_calls: list[str] = []

    def signed(_method: str, path: str, _params: dict[str, Any]):
        paths.append(path)
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v1/marginType":
            raise BinanceAPIError(status_code=400, code=-4000, message="config denied")
        raise AssertionError(path)

    venue._client.signed.side_effect = signed
    with pytest.raises(BinanceAPIError):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="buy",
                quantity=0.01,
                order_type="market",
                leverage=2,
            ),
            before_order_request=lambda: boundary_calls.append("sent"),
        )
    assert boundary_calls == []
    assert "/fapi/v1/order" not in paths


def test_exact_minus_4046_is_ignored_and_order_boundary_fires_once(
    venue: BinanceUMFuturesVenue,
) -> None:
    boundary_calls: list[str] = []

    def signed(_method: str, path: str, params: dict[str, Any]):
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v1/marginType":
            raise BinanceAPIError(status_code=400, code=-4046, message="No need to change")
        if path == "/fapi/v1/leverage":
            return {"symbol": "BTCUSDT", "leverage": 2}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if path == "/fapi/v1/order":
            return {
                "orderId": 123,
                "clientOrderId": params["newClientOrderId"],
                "status": "NEW",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "MARKET",
                "positionSide": "BOTH",
                "reduceOnly": False,
                "closePosition": False,
                "origQty": "0.01",
                "executedQty": "0",
                "updateTime": 1_800_000_000_000,
            }
        raise AssertionError(path)

    venue._client.signed.side_effect = signed
    ack = venue.place_order(
        Order(
            venue="binance_um_futures",
            symbol="BTCUSDT",
            side="buy",
            quantity=0.01,
            order_type="market",
            leverage=2,
        ),
        before_order_request=lambda: boundary_calls.append("sent"),
    )
    assert ack.order_id == "123"
    assert boundary_calls == ["sent"]


def test_mutable_account_configuration_is_rechecked_before_submit_boundary(
    venue: BinanceUMFuturesVenue,
) -> None:
    boundary_calls: list[str] = []
    paths: list[str] = []

    def signed(_method: str, path: str, _params: dict[str, Any]):
        paths.append(path)
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": False, "multiAssetsMargin": False}
        raise AssertionError(path)

    venue._client.signed.side_effect = signed
    with pytest.raises(PermissionError, match="canTrade"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="buy",
                quantity=0.01,
                order_type="market",
            ),
            before_order_request=lambda: boundary_calls.append("sent"),
        )
    assert boundary_calls == []
    assert "/fapi/v1/order" not in paths


def test_algo_cancel_rejects_response_identity_mismatch(
    venue: BinanceUMFuturesVenue,
) -> None:
    venue._client.signed.return_value = {"algoId": 1000, "algoStatus": "CANCELED", "code": "200"}
    with pytest.raises(ValueError, match="identity mismatch"):
        venue.cancel_algo_order("999", "BTCUSDT")


def test_emergency_cancel_covers_normal_and_algo_then_proves_empty(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []
    normal = [{"symbol": "BTCUSDT", "orderId": 11}]
    algos = [{"symbol": "ETHUSDT", "algoId": 22, "algoStatus": "NEW"}]

    def signed(method: str, path: str, params: dict[str, Any]):
        calls.append((method, path, dict(params)))
        if path == "/fapi/v1/openOrders":
            return list(normal)
        if path == "/fapi/v1/openAlgoOrders":
            return list(algos)
        if method == "DELETE" and path == "/fapi/v1/allOpenOrders":
            normal.clear()
            return {"code": 200, "msg": "The operation of cancel all open order is done."}
        if method == "DELETE" and path == "/fapi/v1/algoOpenOrders":
            algos.clear()
            return {"code": 200, "msg": "success"}
        raise AssertionError((method, path, params))

    venue._client.signed.side_effect = signed
    result = venue.emergency_cancel_all()
    assert result["ok"] is True
    assert result["verified_noop"] is False
    assert {item["kind"] for item in result["actions"]} == {"normal", "algo"}
    assert ("DELETE", "/fapi/v1/allOpenOrders", {"symbol": "BTCUSDT"}) in calls
    assert ("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": "ETHUSDT"}) in calls
    assert result["proof"] == {
        "normal_open_order_refs": [],
        "algo_open_order_refs": [],
    }


def test_emergency_cancel_never_greens_an_error_code_or_residual_order(
    venue: BinanceUMFuturesVenue,
) -> None:
    normal = [{"symbol": "BTCUSDT", "orderId": 11}]

    def signed(method: str, path: str, _params: dict[str, Any]):
        if path == "/fapi/v1/openOrders":
            return list(normal)
        if path == "/fapi/v1/openAlgoOrders":
            return []
        if method == "DELETE" and path == "/fapi/v1/allOpenOrders":
            return {"code": -1, "msg": "failed"}
        raise AssertionError((method, path))

    venue._client.signed.side_effect = signed
    result = venue.emergency_cancel_all()
    assert result["ok"] is False
    assert result["verified_noop"] is False
    assert "code=200" in result["error"]
    assert result["proof"]["normal_open_order_refs"] == ["normal:11"]


def test_open_exposure_discovery_includes_algo_identity(
    venue: BinanceUMFuturesVenue,
) -> None:
    def signed(_method: str, path: str, _params: dict[str, Any]):
        if path == "/fapi/v1/openOrders":
            return [{"symbol": "BTCUSDT", "orderId": 11}]
        if path == "/fapi/v1/openAlgoOrders":
            return [{"symbol": "ETHUSDT", "algoId": 22, "algoStatus": "TRIGGERED"}]
        raise AssertionError(path)

    venue._client.signed.side_effect = signed
    rows = venue.list_open_exposure_orders()
    assert [(row["_qb_order_kind"], row.get("orderId") or row.get("algoId")) for row in rows] == [
        ("normal", 11),
        ("algo", 22),
    ]


@pytest.mark.parametrize("malformed", [{}, "", 0, None])
@pytest.mark.parametrize(
    ("method_name", "path"),
    [
        ("list_open_orders", "/fapi/v1/openOrders"),
        ("list_open_algo_orders", "/fapi/v1/openAlgoOrders"),
    ],
)
def test_open_order_discovery_never_coerces_falsy_malformed_payload_to_empty(
    venue: BinanceUMFuturesVenue,
    method_name: str,
    path: str,
    malformed: Any,
) -> None:
    def signed(_method: str, actual_path: str, _params: dict[str, Any]):
        assert actual_path == path
        return malformed

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match="non-list"):
        getattr(venue, method_name)()


def _filled_emergency_response(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "orderId": 9001,
        "clientOrderId": params["newClientOrderId"],
        "symbol": params["symbol"],
        "side": params["side"],
        "type": "MARKET",
        "positionSide": "BOTH",
        "reduceOnly": True,
        "closePosition": False,
        "status": "FILLED",
        "origQty": str(params["quantity"]),
        "executedQty": str(params["quantity"]),
        "updateTime": 1_800_000_000_000,
    }


def test_emergency_close_requires_result_filled_and_fresh_flat_proof(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def signed(method: str, path: str, params: dict[str, Any]):
        calls.append((method, path, dict(params)))
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if method == "POST" and path == "/fapi/v1/order":
            return _filled_emergency_response(params)
        if path == "/fapi/v2/positionRisk":
            return []
        raise AssertionError((method, path))

    venue._client.signed.side_effect = signed
    result = venue.close_open_position(Position(symbol="BTCUSDT", quantity=0.2))
    assert result["verified_flat"] is True
    post = next(item for item in calls if item[0:2] == ("POST", "/fapi/v1/order"))
    assert post[2]["newOrderRespType"] == "RESULT"
    assert post[2]["reduceOnly"] == "true"
    assert post[2]["positionSide"] == "BOTH"


def test_prepared_emergency_close_submits_exact_sealed_params(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def signed(method: str, path: str, params: dict[str, Any]):
        calls.append((method, path, dict(params)))
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if method == "POST" and path == "/fapi/v1/order":
            return _filled_emergency_response(params)
        if path == "/fapi/v2/positionRisk":
            return []
        raise AssertionError((method, path))

    venue._client.signed.side_effect = signed
    params = emergency_close_request_params(
        symbol="BTCUSDT",
        side="sell",
        quantity="0.2",
        client_order_id="qbt-kill-content-bound",
    )
    result = venue.close_prepared_emergency_request(
        request_params=params,
        request_hash=emergency_close_request_hash(params),
    )
    assert result["verified_flat"] is True
    post = next(item for item in calls if item[0:2] == ("POST", "/fapi/v1/order"))
    assert post[2] == params


@pytest.mark.parametrize("tamper", ["hash", "params"])
def test_prepared_emergency_close_rejects_tamper_before_private_call(
    venue: BinanceUMFuturesVenue,
    tamper: str,
) -> None:
    params = emergency_close_request_params(
        symbol="BTCUSDT",
        side="sell",
        quantity="0.2",
        client_order_id="qbt-kill-content-bound",
    )
    request_hash = emergency_close_request_hash(params)
    if tamper == "hash":
        request_hash = "sha256:" + "0" * 64
    else:
        params = {**params, "quantity": 0.3}
    with pytest.raises(ValueError, match="request_hash mismatch"):
        venue.close_prepared_emergency_request(
            request_params=params,
            request_hash=request_hash,
        )
    venue._client.signed.assert_not_called()


def test_emergency_close_rejects_ack_new_even_with_matching_identity(
    venue: BinanceUMFuturesVenue,
) -> None:
    def signed(method: str, path: str, params: dict[str, Any]):
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if method == "POST" and path == "/fapi/v1/order":
            return {**_filled_emergency_response(params), "status": "NEW", "executedQty": "0"}
        raise AssertionError((method, path))

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match="not FILLED"):
        venue.close_open_position(Position(symbol="BTCUSDT", quantity=0.2))


def test_emergency_close_rejects_residual_position_after_filled_result(
    venue: BinanceUMFuturesVenue,
) -> None:
    def signed(method: str, path: str, params: dict[str, Any]):
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if method == "POST" and path == "/fapi/v1/order":
            return _filled_emergency_response(params)
        if path == "/fapi/v2/positionRisk":
            return [{"symbol": "BTCUSDT", "positionSide": "BOTH", "positionAmt": "0.01"}]
        raise AssertionError((method, path))

    venue._client.signed.side_effect = signed
    with pytest.raises(RuntimeError, match="still contains"):
        venue.close_open_position(Position(symbol="BTCUSDT", quantity=0.2))


@pytest.mark.parametrize("position_amt", [None, "", False])
def test_flat_proof_requires_explicit_numeric_position_amount(
    venue: BinanceUMFuturesVenue,
    position_amt: Any,
) -> None:
    def signed(_method: str, path: str, _params: dict[str, Any]):
        if path == "/fapi/v1/openOrders":
            return []
        if path == "/fapi/v1/openAlgoOrders":
            return []
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/positionRisk":
            return [{"symbol": "BTCUSDT", "positionSide": "BOTH", "positionAmt": position_amt}]
        raise AssertionError(path)

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match="explicit numeric positionAmt"):
        venue.verify_emergency_flat()


@pytest.mark.parametrize(
    "order",
    [
        Order(
            venue="binance_um_futures",
            symbol="BTCUSDT",
            side="buy",
            quantity=True,
            order_type="market",
        ),
        Order(
            venue="binance_um_futures",
            symbol="BTCUSDT",
            side="buy",
            quantity=0.01,
            order_type="limit",
            price=True,
        ),
        Order(
            venue="binance_um_futures",
            symbol="BTCUSDT",
            side="buy",
            quantity=0.01,
            order_type="stop_market",
            stop_price=True,
        ),
        Order(
            venue="binance_um_futures",
            symbol="BTCUSDT",
            side="buy",
            quantity=0.01,
            order_type="market",
            leverage=True,
        ),
    ],
)
def test_order_numeric_booleans_are_rejected_before_any_trade_post(
    venue: BinanceUMFuturesVenue,
    order: Order,
) -> None:
    calls = _capture_signed_call(venue._client)
    with pytest.raises(ValueError, match="positive"):
        venue.place_order(order)
    assert not any(item["method"] == "POST" for item in calls)


@pytest.mark.parametrize("value", [True, False, 0, -1, 2.5, math.nan])
def test_max_leverage_requires_positive_integral_non_bool(value: Any) -> None:
    client = MagicMock(product="usdm_futures")
    with pytest.raises(ValueError, match="positive"):
        BinanceUMFuturesVenue(client, max_leverage=value)


@pytest.mark.parametrize("field", ["orderId", "updateTime"])
@pytest.mark.parametrize("value", [True, "123", 1.5, 0, -1, 1 << 63])
def test_standard_ack_requires_positive_raw_int64_fields(field: str, value: Any) -> None:
    params = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quantity": 0.01,
        "positionSide": "BOTH",
        "newClientOrderId": "client-1",
    }
    response = {
        "orderId": 1,
        "clientOrderId": "client-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "positionSide": "BOTH",
        "reduceOnly": False,
        "closePosition": False,
        "origQty": "0.01",
        "executedQty": "0",
        "status": "NEW",
        "updateTime": 1,
    }
    response[field] = value
    with pytest.raises(ValueError, match=field):
        BinanceUMFuturesVenue._validate_standard_order_ack(response, params=params)


@pytest.mark.parametrize("field", ["algoId", "updateTime"])
@pytest.mark.parametrize("value", [True, "123", 1.5, 0, -1, 1 << 63])
def test_algo_ack_requires_positive_raw_int64_fields(field: str, value: Any) -> None:
    params = {
        "algoType": "CONDITIONAL",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "STOP_MARKET",
        "quantity": 0.01,
        "positionSide": "BOTH",
        "clientAlgoId": "client-1",
    }
    response = {
        "algoId": 1,
        "clientAlgoId": "client-1",
        "algoType": "CONDITIONAL",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "orderType": "STOP_MARKET",
        "positionSide": "BOTH",
        "reduceOnly": False,
        "closePosition": False,
        "quantity": "0.01",
        "algoStatus": "NEW",
        "updateTime": 1,
    }
    response[field] = value
    with pytest.raises(ValueError, match=field):
        BinanceUMFuturesVenue._validate_algo_order_ack(response, params=params)


def test_quantized_price_must_remain_positive_before_trade_post(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls = _capture_signed_call(venue._client)
    venue._filters["BTCUSDT"] = FuturesSymbolFilters(
        min_qty=0.001,
        step_size=0.001,
        tick_size=0.01,
    )
    with pytest.raises(ValueError, match="quantized price"):
        venue.place_order(
            Order(
                venue="binance_um_futures",
                symbol="BTCUSDT",
                side="buy",
                quantity=0.01,
                order_type="limit",
                price=0.005,
            )
        )
    assert not any(item["method"] == "POST" for item in calls)


@pytest.mark.parametrize("order_id", [True, "+77", "077", " 77 ", "0", "-1", str(1 << 63)])
def test_order_observation_rejects_noncanonical_query_id_before_signed_call(
    venue: BinanceUMFuturesVenue,
    order_id: Any,
) -> None:
    with pytest.raises(ValueError, match="orderId"):
        venue._query_order_observation("BTCUSDT", order_id=order_id)
    venue._client.signed.assert_not_called()


@pytest.mark.parametrize("field", ["orderId", "algoId"])
def test_open_order_discovery_rejects_boolean_numeric_identity(
    venue: BinanceUMFuturesVenue,
    field: str,
) -> None:
    if field == "orderId":
        venue._client.signed.return_value = [
            {"symbol": "BTCUSDT", "orderId": True, "clientOrderId": "client"}
        ]
        with pytest.raises(ValueError, match="orderId"):
            venue.list_open_orders()
    else:
        venue._client.signed.return_value = [
            {
                "symbol": "BTCUSDT",
                "algoId": True,
                "clientAlgoId": "client",
                "algoStatus": "NEW",
            }
        ]
        with pytest.raises(ValueError, match="algoId"):
            venue.list_open_algo_orders()


@pytest.mark.parametrize("field", ["orderId", "updateTime"])
@pytest.mark.parametrize("value", [True, "123", 0, -1, 1 << 63])
def test_emergency_close_requires_positive_raw_int64_identity_and_time(
    venue: BinanceUMFuturesVenue,
    field: str,
    value: Any,
) -> None:
    def signed(method: str, path: str, params: dict[str, Any]):
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if method == "POST" and path == "/fapi/v1/order":
            return {**_filled_emergency_response(params), field: value}
        raise AssertionError((method, path))

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match=field):
        venue.close_open_position(Position(symbol="BTCUSDT", quantity=0.2))


def test_emergency_close_rejects_boolean_position_quantity_before_post(
    venue: BinanceUMFuturesVenue,
) -> None:
    calls = _capture_signed_call(venue._client)
    with pytest.raises(ValueError, match="finite position quantity"):
        venue.close_open_position(Position(symbol="BTCUSDT", quantity=True))
    assert not any(item["method"] == "POST" for item in calls)


@pytest.mark.parametrize("field", ["orderId", "updateTime"])
def test_order_observation_rejects_boolean_response_identity_or_time(
    venue: BinanceUMFuturesVenue,
    field: str,
) -> None:
    response = {
        "orderId": 77,
        "clientOrderId": "client-77",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "status": "NEW",
        "origQty": "0.01",
        "executedQty": "0",
        "updateTime": 1_800_000_000_000,
    }
    response[field] = True
    venue._client.signed.return_value = response
    with pytest.raises(ValueError, match=field):
        venue._query_order_observation(
            "BTCUSDT",
            order_id="77",
            client_order_id="client-77",
        )


@pytest.mark.parametrize("field", ["id", "orderId", "time"])
def test_execution_trade_rows_reject_boolean_int64_fields(
    venue: BinanceUMFuturesVenue,
    field: str,
) -> None:
    order = {
        "orderId": 77,
        "clientOrderId": "client-77",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "status": "FILLED",
        "origQty": "0.01",
        "executedQty": "0.01",
        "updateTime": 1_800_000_000_000,
    }
    trade = {
        "id": 1,
        "orderId": 77,
        "qty": "0.01",
        "price": "10000",
        "commission": "0.01",
        "commissionAsset": "USDT",
        "realizedPnl": "0",
        "time": 1_800_000_000_000,
    }
    trade[field] = True

    def signed(_method: str, path: str, _params: dict[str, Any]):
        return order if path == "/fapi/v1/order" else [trade]

    venue._client.signed.side_effect = signed
    with pytest.raises(ValueError, match="trade"):
        venue.execution_bundle_for_order(
            "BTCUSDT",
            order_id="77",
            client_order_id="client-77",
        )
