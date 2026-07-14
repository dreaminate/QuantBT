"""M9.3 · Binance USDM Futures venue。

订单类型（GOAL §M9.3 A）：LIMIT / MARKET / STOP / STOP_MARKET / TAKE_PROFIT /
TAKE_PROFIT_MARKET / TRAILING_STOP_MARKET + reduceOnly / closePosition。
保证金模式默认 ISOLATED；杠杆默认上限 5x，超过需显式确认。
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..lineage.ids import content_hash
from .base import (
    Balance,
    CancelAck,
    ExecutionAuditLog,
    ExecutionReport,
    ExecutionVenue,
    Order,
    OrderAck,
    OrderExecutionObservation,
    Position,
    canonical_raw_event_hash,
)
from .binance_client import BinanceAPIError, BinanceClient
from .emergency_journal import (
    emergency_close_request_hash,
    emergency_close_request_params,
)


logger = logging.getLogger(__name__)


_FUTURES_TYPE_MAP = {
    "market": "MARKET",
    "limit": "LIMIT",
    "stop_market": "STOP_MARKET",
    "stop_loss": "STOP",
    "take_profit": "TAKE_PROFIT",
    "take_profit_market": "TAKE_PROFIT_MARKET",
    "take_profit_limit": "TAKE_PROFIT",
    "trailing_stop_market": "TRAILING_STOP_MARKET",
}

# Binance 2025-12-09 强制迁移：5 类条件单走 /fapi/v1/algoOrder（algoType=CONDITIONAL）
# 旧 /fapi/v1/order 收到这些类型返回 -4120。
_CONDITIONAL_TYPES = {"STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET"}

_ACK_STATUS_MAP = {
    "NEW": "new",
    "PARTIALLY_FILLED": "partially_filled",
    "FILLED": "filled",
    "CANCELED": "canceled",
    "REJECTED": "rejected",
    "EXPIRED": "expired",
}

_INT64_MAX = (1 << 63) - 1


def _positive_int64(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value <= 0 or value > _INT64_MAX:
        raise ValueError(f"Binance response has invalid {field_name}")
    return value


def _canonical_positive_int64(value: Any, *, field_name: str) -> str:
    if type(value) is int:
        return str(_positive_int64(value, field_name=field_name))
    if not isinstance(value, str) or not value or not value.isascii() or not value.isdecimal():
        raise ValueError(f"Binance request has invalid {field_name}")
    if value.startswith("0"):
        raise ValueError(f"Binance request has noncanonical {field_name}")
    parsed = int(value)
    if parsed <= 0 or parsed > _INT64_MAX:
        raise ValueError(f"Binance request has invalid {field_name}")
    return value


def _positive_finite_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a positive finite number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field_name} must be a positive finite number")
    return parsed


def _positive_integral_leverage(value: Any, *, field_name: str) -> int:
    parsed = _positive_finite_number(value, field_name=field_name)
    if not parsed.is_integer():
        raise ValueError(f"{field_name} must be a positive integer")
    return int(parsed)


def _strict_ack_status(value: Any, *, field_name: str) -> str:
    raw = str(value or "").strip().upper()
    if raw not in _ACK_STATUS_MAP:
        raise ValueError(f"Binance response has unsupported {field_name} {raw or '<missing>'}")
    return _ACK_STATUS_MAP[raw]


@dataclass
class FuturesSymbolFilters:
    min_qty: float = 0.0
    step_size: float = 0.0
    tick_size: float = 0.0
    min_notional: float = 0.0


def _quantize_down(value: float, step: float) -> float:
    if not step:
        return value
    return math.floor(value / step) * step


class BinanceUMFuturesVenue(ExecutionVenue):
    name = "binance_um_futures"

    def __init__(
        self,
        client: BinanceClient,
        max_leverage: int = 5,
        margin_mode: str = "ISOLATED",
        audit: ExecutionAuditLog | None = None,
    ) -> None:
        if client.product != "usdm_futures":
            raise ValueError("BinanceUMFuturesVenue 需要 product=usdm_futures 的 client")
        resolved_max_leverage = _positive_integral_leverage(
            max_leverage,
            field_name="USDM Futures max_leverage",
        )
        if resolved_max_leverage > 20:
            raise ValueError("USDM Futures 杠杆上限 20x（GOAL §M9.3 B）")
        self._client = client
        self._max_leverage = resolved_max_leverage
        self._margin_mode = margin_mode
        self._audit = audit or ExecutionAuditLog()
        self._filters: dict[str, FuturesSymbolFilters] = {}
        self._configured: set[str] = set()

    @property
    def audit(self) -> ExecutionAuditLog:
        return self._audit

    def _assert_one_way_position_mode(self) -> None:
        """Reject Hedge Mode because this adapter has no ``positionSide`` model.

        Binance's documented response is a boolean ``dualSidePosition``.  Any
        missing, differently typed, or true value is unsafe for this adapter:
        reduce-only and emergency-close semantics would otherwise be ambiguous.
        """

        payload = self._client.signed("GET", "/fapi/v1/positionSide/dual", {})
        if not isinstance(payload, dict):
            raise ValueError("futures position-mode endpoint returned a non-object")
        dual_side = payload.get("dualSidePosition")
        if not isinstance(dual_side, bool):
            raise ValueError("futures position-mode response lacks boolean dualSidePosition")
        if dual_side:
            raise PermissionError(
                "Binance Hedge Mode is unsupported by this execution adapter; switch to One-way Mode"
            )

    def _assert_execution_account_configuration(self) -> None:
        """Re-read mutable account safety state immediately before a trade POST."""

        self._assert_one_way_position_mode()
        payload = self._client.signed("GET", "/fapi/v2/account", {})
        if not isinstance(payload, dict):
            raise ValueError("futures account endpoint returned a non-object")
        if payload.get("canTrade") is not True:
            raise PermissionError("futures account does not prove canTrade=true")
        if payload.get("multiAssetsMargin") is not False:
            raise PermissionError("multi-assets margin mode is unsupported by this execution adapter")

    @staticmethod
    def _require_object_list(value: Any, *, label: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError(f"{label} endpoint returned a non-list")
        if any(not isinstance(item, dict) for item in value):
            raise ValueError(f"{label} endpoint returned a malformed row")
        return [dict(item) for item in value]

    @staticmethod
    def _decimal(value: Any, *, field_name: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"Binance response has invalid {field_name}") from exc
        if not parsed.is_finite():
            raise ValueError(f"Binance response has non-finite {field_name}")
        return parsed

    @classmethod
    def _validate_standard_order_ack(
        cls,
        response: dict[str, Any],
        *,
        params: dict[str, Any],
    ) -> tuple[str, str]:
        if response.get("orderId") in (None, ""):
            raise ValueError("Binance order response lacks venue orderId")
        order_id = str(_positive_int64(response.get("orderId"), field_name="orderId"))
        client_order_id = str(response.get("clientOrderId") or "").strip()
        if not order_id:
            raise ValueError("Binance order response lacks venue orderId")
        if client_order_id != params["newClientOrderId"]:
            raise ValueError("Binance order response clientOrderId mismatch")
        for field_name, expected in (
            ("symbol", params["symbol"]),
            ("side", params["side"]),
            ("type", params["type"]),
            ("positionSide", "BOTH"),
        ):
            if str(response.get(field_name) or "").strip().upper() != str(expected).upper():
                raise ValueError(f"Binance order response {field_name} mismatch")
        if response.get("reduceOnly") is not (params.get("reduceOnly") == "true"):
            raise ValueError("Binance order response reduceOnly mismatch")
        if response.get("closePosition") is not (params.get("closePosition") == "true"):
            raise ValueError("Binance order response closePosition mismatch")
        expected_quantity = cls._decimal(params["quantity"], field_name="requested quantity")
        original_quantity = cls._decimal(response.get("origQty"), field_name="origQty")
        executed_quantity = cls._decimal(response.get("executedQty"), field_name="executedQty")
        if original_quantity != expected_quantity or executed_quantity < 0 or executed_quantity > original_quantity:
            raise ValueError("Binance order response quantity mismatch")
        normalized_status = _strict_ack_status(response.get("status"), field_name="status")
        if normalized_status == "new" and executed_quantity != 0:
            raise ValueError("Binance NEW order response has executed quantity")
        if normalized_status == "partially_filled" and not (0 < executed_quantity < original_quantity):
            raise ValueError("Binance partially-filled response has inconsistent quantity")
        if normalized_status == "filled" and executed_quantity != original_quantity:
            raise ValueError("Binance FILLED response does not cover origQty")
        _positive_int64(response.get("updateTime"), field_name="updateTime")
        return order_id, normalized_status

    @classmethod
    def _validate_algo_order_ack(
        cls,
        response: dict[str, Any],
        *,
        params: dict[str, Any],
    ) -> tuple[str, str]:
        if response.get("algoId") in (None, ""):
            raise ValueError("Binance algo-order response lacks venue algoId")
        algo_id = str(_positive_int64(response.get("algoId"), field_name="algoId"))
        client_algo_id = str(response.get("clientAlgoId") or "").strip()
        if not algo_id:
            raise ValueError("Binance algo-order response lacks venue algoId")
        if client_algo_id != params["clientAlgoId"]:
            raise ValueError("Binance algo-order response clientAlgoId mismatch")
        for field_name, expected in (
            ("algoType", "CONDITIONAL"),
            ("symbol", params["symbol"]),
            ("side", params["side"]),
            ("orderType", params["type"]),
            ("positionSide", "BOTH"),
        ):
            if str(response.get(field_name) or "").strip().upper() != str(expected).upper():
                raise ValueError(f"Binance algo-order response {field_name} mismatch")
        if response.get("reduceOnly") is not (params.get("reduceOnly") == "true"):
            raise ValueError("Binance algo-order response reduceOnly mismatch")
        if response.get("closePosition") is not (params.get("closePosition") == "true"):
            raise ValueError("Binance algo-order response closePosition mismatch")
        if "quantity" in params:
            expected_quantity = cls._decimal(params["quantity"], field_name="requested quantity")
            response_quantity = cls._decimal(response.get("quantity"), field_name="quantity")
            if response_quantity != expected_quantity:
                raise ValueError("Binance algo-order response quantity mismatch")
        normalized_status = _strict_ack_status(response.get("algoStatus"), field_name="algoStatus")
        _positive_int64(response.get("updateTime"), field_name="updateTime")
        return algo_id, normalized_status

    def warmup(self) -> None:
        info = self._client.public("GET", "/fapi/v1/exchangeInfo")
        for sym in info.get("symbols", []):
            f = FuturesSymbolFilters()
            for flt in sym.get("filters", []):
                if flt["filterType"] == "LOT_SIZE":
                    f.min_qty = float(flt.get("minQty", 0))
                    f.step_size = float(flt.get("stepSize", 0))
                elif flt["filterType"] == "PRICE_FILTER":
                    f.tick_size = float(flt.get("tickSize", 0))
                elif flt["filterType"] in {"MIN_NOTIONAL", "NOTIONAL"}:
                    f.min_notional = float(flt.get("minNotional", flt.get("notional", 0)))
            self._filters[sym["symbol"].upper()] = f

    def configure_symbol(self, symbol: str, leverage: int) -> None:
        resolved_leverage = _positive_integral_leverage(
            leverage,
            field_name="Binance futures leverage",
        )
        if resolved_leverage > self._max_leverage:
            raise ValueError(f"leverage {resolved_leverage} 超过 max_leverage {self._max_leverage}")
        sym = symbol.upper()
        try:
            margin_response = self._client.signed(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": sym, "marginType": self._margin_mode},
            )
        except BinanceAPIError as exc:
            if exc.code != -4046:
                raise
            logger.debug("marginType already configured for %s", sym)
        else:
            if not isinstance(margin_response, dict):
                raise ValueError("Binance margin-type response is not an object")
            if "code" in margin_response and (
                type(margin_response.get("code")) is not int
                or margin_response.get("code") != 200
            ):
                raise ValueError("Binance margin-type response did not confirm success")
        leverage_response = self._client.signed(
            "POST",
            "/fapi/v1/leverage",
            {"symbol": sym, "leverage": resolved_leverage},
        )
        if not isinstance(leverage_response, dict):
            raise ValueError("Binance leverage response is not an object")
        if str(leverage_response.get("symbol") or "").upper() != sym:
            raise ValueError("Binance leverage response symbol mismatch")
        applied_leverage = _positive_int64(
            leverage_response.get("leverage"),
            field_name="applied leverage",
        )
        if applied_leverage != resolved_leverage:
            raise ValueError("Binance leverage response does not match requested leverage")
        self._configured.add(sym)

    def place_order(self, order: Order, *, before_order_request: Any = None) -> OrderAck:
        self._assert_one_way_position_mode()
        binance_type = _FUTURES_TYPE_MAP.get(order.order_type)
        if binance_type is None:
            raise NotImplementedError(f"binance_um_futures 不支持 {order.order_type}")
        sym = order.symbol.upper()
        if not sym:
            raise ValueError("Binance futures order requires symbol")
        if order.side not in {"buy", "sell"}:
            raise ValueError("Binance futures order has unsupported side")
        order_quantity = _positive_finite_number(
            order.quantity,
            field_name="Binance futures order quantity",
        )
        for field_name, value in (("price", order.price), ("stop_price", order.stop_price)):
            if value is not None:
                _positive_finite_number(
                    value,
                    field_name=f"Binance futures order {field_name}",
                )
        if order.leverage is not None:
            leverage = _positive_integral_leverage(
                order.leverage,
                field_name="Binance futures leverage",
            )
            if sym not in self._configured:
                self.configure_symbol(sym, leverage)
        filt = self._filters.get(sym, FuturesSymbolFilters())
        qty = _quantize_down(order_quantity, filt.step_size) if filt.step_size else order_quantity
        qty = _positive_finite_number(
            qty,
            field_name="Binance futures quantized quantity",
        )
        if filt.min_qty and qty < filt.min_qty:
            raise PermissionError(f"qty {qty} 低于 {sym} minQty {filt.min_qty}")

        # v0.8.3.1 hotfix · 2025-12-09 起条件单必须走 /fapi/v1/algoOrder
        if binance_type in _CONDITIONAL_TYPES:
            return self._place_algo_order(
                order,
                binance_type,
                sym,
                qty,
                filt,
                before_order_request=before_order_request,
            )

        params: dict[str, Any] = {
            "symbol": sym,
            "side": order.side.upper(),
            "type": binance_type,
            "quantity": qty,
            "positionSide": "BOTH",
            "newClientOrderId": order.client_order_id or str(uuid.uuid4()),
        }
        if order.close_position:
            raise ValueError("closePosition is supported only by conditional algo orders")
        if order.price is not None:
            params["price"] = _positive_finite_number(
                _quantize_down(float(order.price), filt.tick_size)
                if filt.tick_size
                else order.price,
                field_name="Binance futures quantized price",
            )
        if order.stop_price is not None:
            params["stopPrice"] = _positive_finite_number(
                _quantize_down(float(order.stop_price), filt.tick_size)
                if filt.tick_size
                else order.stop_price,
                field_name="Binance futures quantized stopPrice",
            )
        if filt.min_notional and "price" in params and qty * float(params["price"]) < filt.min_notional:
            raise PermissionError(
                f"order notional {qty * float(params['price'])} below {sym} minNotional {filt.min_notional}"
            )
        if order.reduce_only:
            params["reduceOnly"] = "true"
        if binance_type == "LIMIT":
            params["timeInForce"] = order.time_in_force or "GTC"
        self._assert_execution_account_configuration()
        if before_order_request is not None:
            before_order_request()
        resp = self._client.signed("POST", "/fapi/v1/order", params)
        if not isinstance(resp, dict):
            raise ValueError("Binance order response is not an object")
        order_id, ack_status = self._validate_standard_order_ack(resp, params=params)
        ack = OrderAck(
            order_id=order_id,
            client_order_id=params["newClientOrderId"],
            status=ack_status,  # type: ignore[arg-type]
            raw=resp,
        )
        self._audit.log("binance_um_place", {"order": order.to_dict(), "ack": ack.to_dict()})
        return ack

    def _place_algo_order(
        self,
        order: Order,
        binance_type: str,
        sym: str,
        qty: float,
        filt: FuturesSymbolFilters,
        *,
        before_order_request: Any = None,
    ) -> OrderAck:
        """USDM 条件单专用 endpoint（Binance 2025-12-09 强制）。

        与旧 endpoint 关键差异：
          - path: /fapi/v1/algoOrder
          - 必填 algoType=CONDITIONAL
          - clientAlgoId 替代 newClientOrderId
          - triggerPrice 替代 stopPrice
          - 响应 algoId / algoStatus 替代 orderId / status
        """

        client_algo_id = order.client_order_id or str(uuid.uuid4())
        params: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": sym,
            "side": order.side.upper(),
            "type": binance_type,
            "positionSide": "BOTH",
            "clientAlgoId": client_algo_id,
        }
        # quantity 与 closePosition=true 互斥
        if not order.close_position:
            params["quantity"] = qty
        if order.price is not None:
            params["price"] = _positive_finite_number(
                _quantize_down(float(order.price), filt.tick_size)
                if filt.tick_size
                else order.price,
                field_name="Binance futures quantized algo price",
            )
        if order.stop_price is not None:
            params["triggerPrice"] = _positive_finite_number(
                _quantize_down(float(order.stop_price), filt.tick_size)
                if filt.tick_size
                else order.stop_price,
                field_name="Binance futures quantized triggerPrice",
            )
        if order.close_position and binance_type not in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}:
            raise ValueError("closePosition is supported only for STOP_MARKET or TAKE_PROFIT_MARKET")
        if order.close_position and order.reduce_only:
            raise ValueError("closePosition conditional order cannot also set reduceOnly")
        if order.reduce_only:
            params["reduceOnly"] = "true"
        if order.close_position:
            params["closePosition"] = "true"
        # TRAILING_STOP_MARKET 需要 callbackRate（Order 没明确字段 → 默认 1%；调用方可在后续版本扩展）
        if binance_type == "TRAILING_STOP_MARKET":
            params.setdefault("callbackRate", 1.0)
            if order.price is not None:
                params["activatePrice"] = params.pop("price", None)
        for field_name in ("quantity", "price", "triggerPrice", "activatePrice", "callbackRate"):
            if field_name in params:
                params[field_name] = _positive_finite_number(
                    params[field_name],
                    field_name=f"Binance futures algo {field_name}",
                )
        if filt.min_notional and "price" in params and qty * float(params["price"]) < filt.min_notional:
            raise PermissionError(
                f"order notional {qty * float(params['price'])} below {sym} minNotional {filt.min_notional}"
            )
        self._assert_execution_account_configuration()
        if before_order_request is not None:
            before_order_request()
        resp = self._client.signed("POST", "/fapi/v1/algoOrder", params)
        if not isinstance(resp, dict):
            raise ValueError("Binance algo-order response is not an object")
        algo_id, ack_status = self._validate_algo_order_ack(resp, params=params)
        ack = OrderAck(
            order_id=algo_id,
            client_order_id=client_algo_id,
            status=ack_status,  # type: ignore[arg-type]
            raw={**resp, "_qb_algo": True},
        )
        self._audit.log("binance_um_place_algo", {"order": order.to_dict(), "ack": ack.to_dict()})
        return ack

    def cancel_algo_order(self, algo_id: str, symbol: str | None = None) -> CancelAck:
        """Cancel one classic USD-M algo order by its exact ``algoId``.

        ``symbol`` remains as a compatibility-only argument for older callers;
        Binance's classic endpoint does not accept it and it is never signed.
        """

        resolved_algo_id = _canonical_positive_int64(algo_id, field_name="algoId")
        resp = self._client.signed(
            "DELETE",
            "/fapi/v1/algoOrder",
            {"algoId": resolved_algo_id},
        )
        if not isinstance(resp, dict):
            raise ValueError("Binance algo-cancel response is not an object")
        response_algo_id = str(_positive_int64(resp.get("algoId"), field_name="algoId"))
        if response_algo_id != resolved_algo_id:
            raise ValueError("Binance algo-cancel response identity mismatch")
        if type(resp.get("code")) is not int or resp.get("code") != 200:
            raise ValueError("Binance algo-cancel response did not confirm code=200")
        self._audit.log("binance_um_cancel_algo", {"algo_id": resolved_algo_id, "raw": resp})
        return CancelAck(order_id=resolved_algo_id, raw={**resp, "_qb_algo": True})

    def cancel_order(self, order_id: str, symbol: str | None = None) -> CancelAck:  # type: ignore[override]
        resolved_order_id = _canonical_positive_int64(order_id, field_name="orderId")
        params: dict[str, Any] = {"orderId": resolved_order_id}
        if symbol:
            params["symbol"] = symbol.upper()
        resp = self._client.signed("DELETE", "/fapi/v1/order", params)
        if not isinstance(resp, dict):
            raise ValueError("Binance order-cancel response is not an object")
        response_order_id = str(_positive_int64(resp.get("orderId"), field_name="orderId"))
        if response_order_id != resolved_order_id:
            raise ValueError("Binance order-cancel response identity mismatch")
        if str(resp.get("status") or "").strip().upper() != "CANCELED":
            raise ValueError("Binance order-cancel response did not confirm CANCELED")
        self._audit.log("binance_um_cancel", {"order_id": resolved_order_id, "raw": resp})
        return CancelAck(order_id=resolved_order_id, raw=resp)

    def cancel_all_open(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Cancel classic normal orders, grouped by the required symbol."""

        symbols = (
            {str(symbol).strip().upper()}
            if str(symbol or "").strip()
            else {str(item.get("symbol") or "").strip().upper() for item in self.list_open_orders()}
        )
        if "" in symbols:
            raise ValueError("normal open-order discovery row lacks symbol")
        results: list[dict[str, Any]] = []
        for current_symbol in sorted(symbols):
            try:
                resp = self._client.signed(
                    "DELETE",
                    "/fapi/v1/allOpenOrders",
                    {"symbol": current_symbol},
                )
                if not isinstance(resp, dict):
                    raise ValueError("normal cancel-all response is not an object")
                if type(resp.get("code")) is not int or resp.get("code") != 200:
                    raise ValueError("normal cancel-all response did not confirm code=200")
                results.append({"kind": "normal", "symbol": current_symbol, "response": dict(resp)})
            except Exception as exc:  # noqa: BLE001 - emergency continues across symbols
                results.append({"kind": "normal", "symbol": current_symbol, "error": str(exc)})
        self._audit.log("binance_um_cancel_all", {"kind": "normal", "actions": results})
        return results

    def cancel_all_algo_open(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Cancel classic algo orders, grouped by the endpoint-required symbol."""

        symbols = (
            {str(symbol).strip().upper()}
            if str(symbol or "").strip()
            else {str(item.get("symbol") or "").strip().upper() for item in self.list_open_algo_orders()}
        )
        if "" in symbols:
            raise ValueError("algo open-order discovery row lacks symbol")
        results: list[dict[str, Any]] = []
        for current_symbol in sorted(symbols):
            try:
                resp = self._client.signed(
                    "DELETE",
                    "/fapi/v1/algoOpenOrders",
                    {"symbol": current_symbol},
                )
                if not isinstance(resp, dict):
                    raise ValueError("algo cancel-all response is not an object")
                if type(resp.get("code")) is not int or resp.get("code") != 200:
                    raise ValueError("algo cancel-all response did not confirm code=200")
                results.append({"kind": "algo", "symbol": current_symbol, "response": dict(resp)})
            except Exception as exc:  # noqa: BLE001 - emergency continues across symbols
                results.append({"kind": "algo", "symbol": current_symbol, "error": str(exc)})
        self._audit.log("binance_um_cancel_all", {"kind": "algo", "actions": results})
        return results

    def emergency_cancel_all(self) -> dict[str, Any]:
        initial_normal = self.list_open_orders()
        initial_algo = self.list_open_algo_orders()
        normal_symbols = sorted({str(item["symbol"]).upper() for item in initial_normal})
        algo_symbols = sorted({str(item["symbol"]).upper() for item in initial_algo})
        actions: list[dict[str, Any]] = []
        for symbol in normal_symbols:
            actions.extend(self.cancel_all_open(symbol))
        for symbol in algo_symbols:
            actions.extend(self.cancel_all_algo_open(symbol))
        errors = [str(item.get("error")) for item in actions if item.get("error")]
        proof: dict[str, Any]
        try:
            remaining_normal = self.list_open_orders()
            remaining_algo = self.list_open_algo_orders()
            proof = {
                "normal_open_order_refs": self._normal_order_refs(remaining_normal),
                "algo_open_order_refs": self._algo_order_refs(remaining_algo),
            }
            if remaining_normal or remaining_algo:
                errors.append("fresh post-cancel proof still contains open orders")
        except Exception as exc:  # noqa: BLE001 - report the failed proof, never claim success
            proof = {"error": str(exc)}
            errors.append(f"fresh post-cancel proof unavailable: {exc}")
        return {
            "ok": not errors,
            "verified_noop": not initial_normal and not initial_algo and not actions and not errors,
            "actions": actions,
            "proof": proof,
            "error": "; ".join(errors) or None,
        }

    def list_open_positions(self) -> list[Position]:
        """Return non-zero USDM positions from the position-risk endpoint."""

        self._assert_one_way_position_mode()
        rows = self._client.signed("GET", "/fapi/v2/positionRisk", {})
        return self._parse_open_positions(rows)

    def _parse_open_positions(self, rows: Any) -> list[Position]:
        raw_positions = self._require_object_list(rows, label="futures position-risk")
        positions: list[Position] = []
        seen_symbols: set[str] = set()
        for item in raw_positions:
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                raise ValueError("futures position-risk row lacks symbol")
            if str(item.get("positionSide") or "").strip().upper() != "BOTH":
                raise PermissionError("futures position-risk row is not One-way Mode")
            if (
                "positionAmt" not in item
                or item.get("positionAmt") in (None, "")
                or isinstance(item.get("positionAmt"), bool)
            ):
                raise ValueError("futures position-risk row lacks explicit numeric positionAmt")
            quantity = float(item["positionAmt"])
            if not math.isfinite(quantity):
                raise ValueError("futures position-risk row contains non-finite quantity")
            if quantity == 0:
                continue
            if symbol in seen_symbols:
                raise ValueError("futures position-risk response has duplicate open symbol")
            seen_symbols.add(symbol)
            entry_price = float(item.get("entryPrice", 0) or 0)
            mark_price = float(item.get("markPrice", 0) or 0)
            unrealized_pnl = float(item.get("unRealizedProfit", 0) or 0)
            leverage = float(item.get("leverage", 1) or 1)
            if not all(
                math.isfinite(value)
                for value in (entry_price, mark_price, unrealized_pnl, leverage)
            ):
                raise ValueError("futures position-risk row contains non-finite state")
            positions.append(
                Position(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=entry_price,
                    mark_price=mark_price,
                    unrealized_pnl=unrealized_pnl,
                    leverage=leverage,
                    side="buy" if quantity > 0 else "sell",
                )
            )
        return positions

    def close_open_position(
        self,
        position: Position,
        *,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Close a discovered position using an opposite-side reduce-only MARKET order."""

        if not position.symbol or position.quantity == 0:
            raise ValueError("emergency close requires a non-zero position with symbol")
        if (
            isinstance(position.quantity, bool)
            or not isinstance(position.quantity, (int, float))
            or not math.isfinite(float(position.quantity))
        ):
            raise ValueError("emergency close requires a finite position quantity")
        resolved_client_order_id = client_order_id or f"kill-{uuid.uuid4().hex[:30]}"
        params = emergency_close_request_params(
            symbol=position.symbol,
            side="sell" if position.quantity > 0 else "buy",
            quantity=abs(float(position.quantity)),
            client_order_id=resolved_client_order_id,
        )
        return self.close_prepared_emergency_request(
            request_params=params,
            request_hash=emergency_close_request_hash(params),
        )

    def close_prepared_emergency_request(
        self,
        *,
        request_params: dict[str, Any],
        request_hash: str,
    ) -> dict[str, Any]:
        """Submit the exact request sealed by the emergency action journal."""

        if not isinstance(request_params, dict):
            raise TypeError("prepared emergency request_params must be an object")
        normalized = emergency_close_request_params(
            symbol=str(request_params.get("symbol") or ""),
            side=str(request_params.get("side") or "").lower(),  # type: ignore[arg-type]
            quantity=request_params.get("quantity"),
            client_order_id=str(request_params.get("newClientOrderId") or ""),
        )
        if request_params != normalized:
            raise ValueError("prepared emergency request params are not canonical")
        if emergency_close_request_hash(normalized) != str(request_hash or ""):
            raise ValueError("prepared emergency request_hash mismatch")
        self._assert_execution_account_configuration()
        params = normalized
        resolved_client_order_id = str(params["newClientOrderId"])
        resp = self._client.signed("POST", "/fapi/v1/order", params)
        if not isinstance(resp, dict):
            raise ValueError("emergency close response is not an object")
        order_id = str(_positive_int64(resp.get("orderId"), field_name="orderId"))
        if str(resp.get("clientOrderId") or "").strip() != resolved_client_order_id:
            raise ValueError("emergency close response clientOrderId mismatch")
        if str(resp.get("symbol") or "").strip().upper() != params["symbol"]:
            raise ValueError("emergency close response symbol mismatch")
        if str(resp.get("side") or "").strip().upper() != params["side"]:
            raise ValueError("emergency close response side mismatch")
        if str(resp.get("type") or "").strip().upper() != "MARKET":
            raise ValueError("emergency close response type mismatch")
        if str(resp.get("positionSide") or "").strip().upper() != "BOTH":
            raise ValueError("emergency close response positionSide mismatch")
        if resp.get("reduceOnly") is not True or resp.get("closePosition") is not False:
            raise ValueError("emergency close response does not prove reduce-only non-closePosition semantics")
        if str(resp.get("status") or "").strip().upper() != "FILLED":
            raise ValueError("emergency close RESULT response is not FILLED")
        expected_quantity = self._decimal(params["quantity"], field_name="requested quantity")
        original_quantity = self._decimal(resp.get("origQty"), field_name="origQty")
        executed_quantity = self._decimal(resp.get("executedQty"), field_name="executedQty")
        if original_quantity != expected_quantity or executed_quantity != expected_quantity:
            raise ValueError("emergency close response quantity mismatch")
        update_time = _positive_int64(resp.get("updateTime"), field_name="updateTime")

        fresh_rows = self._client.signed("GET", "/fapi/v2/positionRisk", {})
        remaining = [
            item
            for item in self._parse_open_positions(fresh_rows)
            if item.symbol == params["symbol"]
        ]
        if remaining:
            raise RuntimeError("fresh post-close proof still contains the closed symbol")
        self._audit.log(
            "binance_um_close_position",
            {
                "symbol": params["symbol"],
                "quantity": params["quantity"],
                "order_id": order_id,
                "response_hash": canonical_raw_event_hash(resp),
                "verified_flat": True,
            },
        )
        return {
            "order_id": order_id,
            "client_order_id": resolved_client_order_id,
            "symbol": params["symbol"],
            "status": "filled",
            "filled_quantity": float(executed_quantity),
            "update_time": update_time,
            "response_hash": canonical_raw_event_hash(resp),
            "verified_flat": True,
        }

    def close_position(self, symbol: str, side: str = "sell") -> dict[str, Any]:
        """Compatibility wrapper; KillSwitch uses list_open_positions + close_open_position."""

        position = self.get_position(symbol)
        if position.quantity == 0:
            return {"symbol": symbol.upper(), "verified_noop": True}
        return self.close_open_position(position)

    def get_position(self, symbol: str) -> Position:
        self._assert_one_way_position_mode()
        positions = self._client.signed("GET", "/fapi/v2/positionRisk", {"symbol": symbol.upper()})
        if not positions:
            return Position(symbol=symbol, quantity=0)
        item = positions[0]
        return Position(
            symbol=symbol,
            quantity=float(item.get("positionAmt", 0)),
            entry_price=float(item.get("entryPrice", 0)),
            mark_price=float(item.get("markPrice", 0)),
            unrealized_pnl=float(item.get("unRealizedProfit", 0)),
            leverage=float(item.get("leverage", 1)),
        )

    def get_balance(self) -> dict[str, Balance]:
        resp = self._client.signed("GET", "/fapi/v2/balance", {})
        return {
            b["asset"]: Balance(asset=b["asset"], free=float(b.get("availableBalance", 0)), locked=0.0)
            for b in resp or []
        }

    def margin_equity(self) -> float:
        """Return documented account margin equity, not withdrawable balance."""

        account = self._client.signed("GET", "/fapi/v2/account", {})
        if not isinstance(account, dict):
            raise ValueError("futures account endpoint returned a non-object")
        value = float(account.get("totalMarginBalance", 0) or 0)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("futures account lacks positive finite totalMarginBalance")
        return value

    def list_open_orders(self) -> list[dict[str, Any]]:
        response = self._client.signed("GET", "/fapi/v1/openOrders", {})
        rows = self._require_object_list(response, label="futures open-orders")
        for item in rows:
            if not str(item.get("symbol") or "").strip():
                raise ValueError("futures open-order row lacks symbol")
            if item.get("orderId") not in (None, ""):
                _positive_int64(item.get("orderId"), field_name="open orderId")
            elif not str(item.get("clientOrderId") or "").strip():
                raise ValueError("futures open-order row lacks exact order identity")
        return rows

    def list_open_algo_orders(self) -> list[dict[str, Any]]:
        response = self._client.signed("GET", "/fapi/v1/openAlgoOrders", {})
        rows = self._require_object_list(response, label="futures open-algo-orders")
        for item in rows:
            if not str(item.get("symbol") or "").strip():
                raise ValueError("futures open-algo-order row lacks symbol")
            if item.get("algoId") not in (None, ""):
                _positive_int64(item.get("algoId"), field_name="open algoId")
            elif not str(item.get("clientAlgoId") or "").strip():
                raise ValueError("futures open-algo-order row lacks exact algo identity")
            status = str(item.get("algoStatus") or "").strip().upper()
            if status not in {"NEW", "TRIGGERED"}:
                raise ValueError(
                    f"futures open-algo-order row has unsupported status {status or '<missing>'}"
                )
        return rows

    @staticmethod
    def _normal_order_refs(rows: list[dict[str, Any]]) -> list[str]:
        return sorted(
            {
                "normal:" + str(item.get("orderId") or item.get("clientOrderId") or "").strip()
                for item in rows
            }
        )

    @staticmethod
    def _algo_order_refs(rows: list[dict[str, Any]]) -> list[str]:
        return sorted(
            {
                "algo:" + str(item.get("algoId") or item.get("clientAlgoId") or "").strip()
                for item in rows
            }
        )

    def list_open_exposure_orders(self) -> list[dict[str, Any]]:
        return [
            *({**item, "_qb_order_kind": "normal"} for item in self.list_open_orders()),
            *({**item, "_qb_order_kind": "algo"} for item in self.list_open_algo_orders()),
        ]

    def verify_emergency_flat(self, *, close_positions: bool = True) -> dict[str, Any]:
        """Fresh account-wide proof covering normal orders, algo orders, and positions."""

        normal = self.list_open_orders()
        algo = self.list_open_algo_orders()
        positions = self.list_open_positions()
        return {
            "ok": not normal and not algo and (not close_positions or not positions),
            "normal_open_order_refs": self._normal_order_refs(normal),
            "algo_open_order_refs": self._algo_order_refs(algo),
            "open_positions": [
                {"symbol": position.symbol, "quantity": position.quantity}
                for position in positions
            ],
        }

    def _query_order_observation(
        self,
        symbol: str,
        *,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> OrderExecutionObservation:
        """Read and strictly parse one exact authoritative order snapshot."""

        sym = str(symbol or "").strip().upper()
        if not sym or not (str(order_id or "").strip() or str(client_order_id or "").strip()):
            raise ValueError("order observation query requires symbol and exact order identity")
        query: dict[str, Any] = {"symbol": sym}
        if str(order_id or "").strip():
            query["orderId"] = _canonical_positive_int64(order_id, field_name="orderId")
        else:
            query["origClientOrderId"] = str(client_order_id)
        order = self._client.signed("GET", "/fapi/v1/order", query) or {}
        if not isinstance(order, dict):
            raise ValueError("futures order endpoint returned a non-object")
        resolved_order_id = str(_positive_int64(order.get("orderId"), field_name="orderId"))
        resolved_client_id = str(order.get("clientOrderId") or "").strip()
        if not resolved_order_id or not resolved_client_id:
            raise ValueError("futures order response lacks exact venue and client order identities")
        if "orderId" in query and resolved_order_id != query["orderId"]:
            raise ValueError("futures order identity mismatch")
        if str(client_order_id or "").strip() and resolved_client_id != str(client_order_id):
            raise ValueError("futures client-order identity mismatch")
        if str(order.get("symbol") or "").upper() != sym:
            raise ValueError("futures order symbol mismatch")
        raw_side = str(order.get("side") or "").upper()
        if raw_side not in {"BUY", "SELL"}:
            raise ValueError("futures order response has unsupported side")
        raw_status = str(order.get("status") or "").upper()
        status_map = {
            "NEW": "new",
            "PARTIALLY_FILLED": "partially_filled",
            "FILLED": "filled",
            "CANCELED": "canceled",
            "REJECTED": "rejected",
            "EXPIRED": "expired",
            "EXPIRED_IN_MATCH": "expired",
        }
        if raw_status not in status_map:
            raise ValueError(f"futures order response has unsupported status {raw_status or '<missing>'}")
        requested = float(order.get("origQty", 0) or 0)
        cumulative = float(order.get("executedQty", 0) or 0)
        if not all(math.isfinite(value) for value in (requested, cumulative)):
            raise ValueError("futures order response contains non-finite quantities")
        tolerance = max(requested, 1.0) * 1e-9
        if requested <= 0 or cumulative < 0 or cumulative > requested + tolerance:
            raise ValueError("futures order response contains invalid requested/executed quantity")
        normalized_status = status_map[raw_status]
        if normalized_status == "filled" and abs(cumulative - requested) > tolerance:
            raise ValueError("filled futures order does not cover the requested quantity")
        if normalized_status == "partially_filled" and not (
            cumulative > tolerance and cumulative < requested - tolerance
        ):
            raise ValueError("partially-filled futures order has inconsistent executed quantity")
        if normalized_status in {"new", "rejected"} and cumulative > tolerance:
            raise ValueError("unfilled futures order status conflicts with executed quantity")
        timestamp_field = "updateTime" if order.get("updateTime") not in (None, "") else "time"
        observed_ms = _positive_int64(order.get(timestamp_field), field_name=timestamp_field)
        raw_hash = canonical_raw_event_hash(order)
        source_ref = "binance_order_observation_" + content_hash(
            {
                "order_id": resolved_order_id,
                "client_order_id": resolved_client_id,
                "status": normalized_status,
                "requested_qty": requested,
                "cumulative_filled_qty": cumulative,
                "observed_ms": observed_ms,
                "raw_event_hash": raw_hash,
            }
        )
        return OrderExecutionObservation(
            order_id=resolved_order_id,
            client_order_id=resolved_client_id,
            symbol=sym,
            side="buy" if raw_side == "BUY" else "sell",
            status=normalized_status,  # type: ignore[arg-type]
            requested_qty=requested,
            cumulative_filled_qty=cumulative,
            observed_at_utc=datetime.fromtimestamp(observed_ms / 1000, tz=UTC).isoformat(),
            source_event_ref=source_ref,
            raw_event_hash=raw_hash,
            raw=dict(order),
        )

    def order_execution_observation(
        self,
        symbol: str,
        *,
        order_id: str | None = None,
        client_order_id: str | None = None,
        expected_emergency_close: bool = False,
    ) -> OrderExecutionObservation:
        """Public exact-identity observation used by durable emergency recovery."""

        observation = self._query_order_observation(
            symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )
        if expected_emergency_close:
            raw = observation.raw
            if (
                str(raw.get("type") or "").strip().upper() != "MARKET"
                or raw.get("reduceOnly") is not True
                or raw.get("closePosition") is not False
                or str(raw.get("positionSide") or "").strip().upper() != "BOTH"
            ):
                raise ValueError(
                    "futures order observation does not prove exact emergency reduce-only semantics"
                )
        return observation

    def execution_bundle_for_order(
        self,
        symbol: str,
        *,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> tuple[OrderExecutionObservation, list[ExecutionReport]]:
        """Read one authoritative order snapshot and every matching fill row."""

        observation = self._query_order_observation(
            symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )
        sym = observation.symbol
        resolved_order_id = observation.order_id
        resolved_client_id = observation.client_order_id
        trades = self._client.signed(
            "GET",
            "/fapi/v1/userTrades",
            {"symbol": sym, "orderId": resolved_order_id, "limit": 1000},
        ) or []
        trade_rows = self._require_object_list(trades, label="futures user-trades")
        for row in trade_rows:
            _positive_int64(row.get("time"), field_name="trade time")
            _positive_int64(row.get("id"), field_name="trade id")
            _positive_int64(row.get("orderId"), field_name="trade orderId")
        rows = sorted(
            trade_rows,
            key=lambda row: (row["time"], row["id"]),
        )
        cumulative = 0.0
        seen_trade_ids: set[str] = set()
        requested = observation.requested_qty
        side = observation.side
        reports: list[ExecutionReport] = []
        for row in rows:
            if str(row["orderId"]) != resolved_order_id:
                raise ValueError("futures trade row belongs to a different order")
            trade_id = str(row["id"])
            if trade_id in seen_trade_ids:
                raise ValueError("futures trade rows lack unique trade identities")
            seen_trade_ids.add(trade_id)
            quantity = float(row.get("qty", 0) or 0)
            price = float(row.get("price", 0) or 0)
            commission = float(row.get("commission", 0) or 0)
            if "realizedPnl" not in row:
                raise ValueError("futures trade row lacks realized PnL economics")
            realized_pnl = float(row.get("realizedPnl", 0) or 0)
            if not all(
                math.isfinite(value)
                for value in (quantity, price, commission, realized_pnl)
            ):
                raise ValueError("futures trade row contains non-finite numeric state")
            if quantity <= 0 or price <= 0 or commission < 0:
                raise ValueError("futures trade row contains invalid fill economics")
            cumulative += quantity
            raw_hash = canonical_raw_event_hash(row)
            source_ref = "binance_execution_" + content_hash(
                {
                    "order_id": resolved_order_id,
                    "trade_id": trade_id,
                    "time": row.get("time"),
                    "raw_event_hash": raw_hash,
                }
            )
            trade_ms = row["time"]
            timestamp = datetime.fromtimestamp(trade_ms / 1000, tz=UTC).isoformat()
            terminal = requested > 0 and math.isclose(cumulative, requested, rel_tol=1e-9, abs_tol=1e-12)
            reports.append(
                ExecutionReport(
                    order_id=resolved_order_id,
                    client_order_id=resolved_client_id,
                    symbol=sym,
                    side=side,
                    filled_qty=quantity,
                    cumulative_filled_qty=cumulative,
                    fill_price=price,
                    commission=commission,
                    commission_asset=str(row.get("commissionAsset") or ""),
                    status="filled" if terminal else "partially_filled",
                    realized_pnl_delta=realized_pnl,
                    realized_pnl_complete=True,
                    timestamp_utc=timestamp,
                    raw=row,
                    source_event_ref=source_ref,
                    raw_event_hash=raw_hash,
                )
            )
        tolerance = max(requested, 1.0) * 1e-9
        if abs(cumulative - observation.cumulative_filled_qty) > tolerance:
            raise ValueError("futures trade rows do not cover the authoritative executed quantity")
        return observation, reports

    def execution_reports_for_order(
        self,
        symbol: str,
        *,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> list[ExecutionReport]:
        """Compatibility fill-only projection; lifecycle is available in the bundle."""

        _observation, reports = self.execution_bundle_for_order(
            symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )
        return reports

    def execution_account_snapshot(self, symbol: str) -> dict[str, Any]:
        """Read the private/public state required by the live pre-trade gate.

        This method does not place or cancel orders.  Raw exchange responses stay
        inside the venue boundary; callers receive only typed numeric fields and
        the permission-check result needed to derive content-bound audit refs.
        """

        sym = str(symbol or "").strip().upper()
        if not sym:
            raise ValueError("execution account snapshot requires symbol")
        safety = self._client.assert_safe_startup()
        self._assert_one_way_position_mode()
        account = self._client.signed("GET", "/fapi/v2/account", {}) or {}
        if not isinstance(account, dict):
            raise ValueError("futures account endpoint returned a non-object")
        if account.get("canTrade") is not True:
            raise PermissionError("futures account does not prove canTrade=true")
        if account.get("multiAssetsMargin") is not False:
            raise PermissionError("multi-assets margin mode is unsupported by the live risk model")
        balances = self._client.signed("GET", "/fapi/v2/balance", {}) or []
        if not isinstance(balances, list) or not balances:
            raise ValueError("futures balance endpoint returned no account identity rows")
        account_aliases = {
            str(row.get("accountAlias") or "").strip()
            for row in balances
            if isinstance(row, dict)
        }
        if "" in account_aliases or len(account_aliases) != 1:
            raise ValueError("futures balance rows lack one consistent accountAlias")
        account_alias = next(iter(account_aliases))
        raw_positions = self._client.signed("GET", "/fapi/v2/positionRisk", {}) or []
        premium = self._client.public("GET", "/fapi/v1/premiumIndex", {"symbol": sym}) or {}
        book = self._client.public("GET", "/fapi/v1/ticker/bookTicker", {"symbol": sym}) or {}
        commission = self._client.signed("GET", "/fapi/v1/commissionRate", {"symbol": sym}) or {}

        total_margin_balance = account.get("totalMarginBalance")
        if total_margin_balance in (None, ""):
            raise ValueError("futures account response lacks totalMarginBalance")
        equity = float(total_margin_balance)
        if not math.isfinite(equity):
            raise ValueError("futures account totalMarginBalance is non-finite")
        positions = []
        for row in raw_positions:
            if not isinstance(row, dict):
                raise ValueError("futures position-risk endpoint returned a malformed row")
            quantity = float(row.get("positionAmt", 0) or 0)
            if quantity == 0:
                continue
            if str(row.get("positionSide") or "BOTH").upper() != "BOTH":
                raise PermissionError("futures position row is not compatible with One-way Mode")
            positions.append(
                {
                    "symbol": str(row.get("symbol") or "").upper(),
                    "quantity": quantity,
                    "entry_price": float(row.get("entryPrice", 0) or 0),
                    "mark_price": float(row.get("markPrice", 0) or 0),
                    "unrealized_pnl": float(row.get("unRealizedProfit", 0) or 0),
                    "leverage": float(row.get("leverage", 0) or 0),
                    "liquidation_price": float(row.get("liquidationPrice", 0) or 0),
                    "margin_mode": "isolated" if bool(row.get("isolated")) else "cross",
                }
            )

        return {
            "account_uid": account_alias,
            "account_identity_source": "fapi_v2_balance.accountAlias",
            "position_mode": "one_way",
            "can_trade": True,
            "multi_assets_margin": False,
            "equity": equity,
            "positions": positions,
            "mark_price": float(premium.get("markPrice", 0) or 0),
            "funding_rate": float(premium.get("lastFundingRate", 0) or 0),
            "bid_price": float(book.get("bidPrice", 0) or 0),
            "ask_price": float(book.get("askPrice", 0) or 0),
            "maker_commission_rate": float(commission.get("makerCommissionRate", 0) or 0),
            "taker_commission_rate": float(commission.get("takerCommissionRate", 0) or 0),
            "permission_state": dict(safety.get("permission_state") or {}),
            "ip_restricted": safety.get("ip_restricted"),
            "permission_warnings": tuple(str(item) for item in safety.get("warnings") or ()),
        }


__all__ = ["BinanceUMFuturesVenue", "FuturesSymbolFilters"]
