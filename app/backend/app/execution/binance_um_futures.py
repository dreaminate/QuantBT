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
from typing import Any

from .base import (
    Balance,
    CancelAck,
    ExecutionAuditLog,
    ExecutionVenue,
    Order,
    OrderAck,
    Position,
)
from .binance_client import BinanceClient


logger = logging.getLogger(__name__)


_FUTURES_TYPE_MAP = {
    "market": "MARKET",
    "limit": "LIMIT",
    "stop_market": "STOP_MARKET",
    "stop_loss": "STOP",
    "take_profit": "TAKE_PROFIT",
    "take_profit_limit": "TAKE_PROFIT",
    "trailing_stop_market": "TRAILING_STOP_MARKET",
}

# Binance 2025-12-09 强制迁移：5 类条件单走 /fapi/v1/algoOrder（algoType=CONDITIONAL）
# 旧 /fapi/v1/order 收到这些类型返回 -4120。
_CONDITIONAL_TYPES = {"STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET"}


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
        if max_leverage > 20:
            raise ValueError("USDM Futures 杠杆上限 20x（GOAL §M9.3 B）")
        self._client = client
        self._max_leverage = max_leverage
        self._margin_mode = margin_mode
        self._audit = audit or ExecutionAuditLog()
        self._filters: dict[str, FuturesSymbolFilters] = {}
        self._configured: set[str] = set()

    @property
    def audit(self) -> ExecutionAuditLog:
        return self._audit

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
        if leverage > self._max_leverage:
            raise ValueError(f"leverage {leverage} 超过 max_leverage {self._max_leverage}")
        sym = symbol.upper()
        try:
            self._client.signed("POST", "/fapi/v1/marginType", {"symbol": sym, "marginType": self._margin_mode})
        except Exception as exc:  # noqa: BLE001
            # Binance 在已经是该 mode 时会返回 4046 错误；可忽略
            logger.debug("marginType 设置返回 %s（多半已配置过）", exc)
        self._client.signed("POST", "/fapi/v1/leverage", {"symbol": sym, "leverage": leverage})
        self._configured.add(sym)

    def place_order(self, order: Order) -> OrderAck:
        binance_type = _FUTURES_TYPE_MAP.get(order.order_type)
        if binance_type is None:
            raise NotImplementedError(f"binance_um_futures 不支持 {order.order_type}")
        sym = order.symbol.upper()
        if sym not in self._configured and order.leverage:
            self.configure_symbol(sym, int(order.leverage))
        filt = self._filters.get(sym, FuturesSymbolFilters())
        qty = _quantize_down(order.quantity, filt.step_size) if filt.step_size else order.quantity
        if filt.min_qty and qty < filt.min_qty:
            raise PermissionError(f"qty {qty} 低于 {sym} minQty {filt.min_qty}")

        # v0.8.3.1 hotfix · 2025-12-09 起条件单必须走 /fapi/v1/algoOrder
        if binance_type in _CONDITIONAL_TYPES:
            return self._place_algo_order(order, binance_type, sym, qty, filt)

        params: dict[str, Any] = {
            "symbol": sym,
            "side": order.side.upper(),
            "type": binance_type,
            "quantity": qty,
            "newClientOrderId": order.client_order_id or str(uuid.uuid4()),
        }
        if order.price is not None:
            params["price"] = _quantize_down(order.price, filt.tick_size) if filt.tick_size else order.price
        if order.stop_price is not None:
            params["stopPrice"] = _quantize_down(order.stop_price, filt.tick_size) if filt.tick_size else order.stop_price
        if order.reduce_only:
            params["reduceOnly"] = "true"
        if order.close_position:
            params["closePosition"] = "true"
        if binance_type == "LIMIT":
            params["timeInForce"] = order.time_in_force or "GTC"
        resp = self._client.signed("POST", "/fapi/v1/order", params)
        ack = OrderAck(
            order_id=str(resp.get("orderId") or params["newClientOrderId"]),
            client_order_id=params["newClientOrderId"],
            status=str(resp.get("status", "new")).lower(),
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
            "clientAlgoId": client_algo_id,
        }
        # quantity 与 closePosition=true 互斥
        if not order.close_position:
            params["quantity"] = qty
        if order.price is not None:
            params["price"] = _quantize_down(order.price, filt.tick_size) if filt.tick_size else order.price
        if order.stop_price is not None:
            params["triggerPrice"] = _quantize_down(order.stop_price, filt.tick_size) if filt.tick_size else order.stop_price
        if order.reduce_only:
            params["reduceOnly"] = "true"
        if order.close_position:
            params["closePosition"] = "true"
        # TRAILING_STOP_MARKET 需要 callbackRate（Order 没明确字段 → 默认 1%；调用方可在后续版本扩展）
        if binance_type == "TRAILING_STOP_MARKET":
            params.setdefault("callbackRate", 1.0)
            if order.price is not None:
                params["activatePrice"] = params.pop("price", None)
        resp = self._client.signed("POST", "/fapi/v1/algoOrder", params)
        algo_id = str(resp.get("algoId") or client_algo_id)
        ack = OrderAck(
            order_id=algo_id,
            client_order_id=client_algo_id,
            status=str(resp.get("algoStatus", "new")).lower(),
            raw={**resp, "_qb_algo": True},
        )
        self._audit.log("binance_um_place_algo", {"order": order.to_dict(), "ack": ack.to_dict()})
        return ack

    def cancel_algo_order(self, algo_id: str, symbol: str) -> CancelAck:
        """取消条件单。需要 algoId（不是 orderId）。"""

        resp = self._client.signed(
            "DELETE",
            "/fapi/v1/algoOrder",
            {"algoId": algo_id, "symbol": symbol.upper()},
        )
        self._audit.log("binance_um_cancel_algo", {"algo_id": algo_id, "raw": resp})
        return CancelAck(order_id=algo_id, raw={**resp, "_qb_algo": True})

    def cancel_order(self, order_id: str, symbol: str | None = None) -> CancelAck:  # type: ignore[override]
        params: dict[str, Any] = {"orderId": order_id}
        if symbol:
            params["symbol"] = symbol.upper()
        resp = self._client.signed("DELETE", "/fapi/v1/order", params)
        self._audit.log("binance_um_cancel", {"order_id": order_id, "raw": resp})
        return CancelAck(order_id=order_id, raw=resp)

    def cancel_all_open(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Kill Switch · USDM 提供 batch endpoint。"""

        if symbol:
            try:
                resp = self._client.signed("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol.upper()})
            except Exception as exc:  # noqa: BLE001
                resp = {"error": str(exc)}
            self._audit.log("binance_um_cancel_all", {"symbol": symbol, "raw": resp})
            return [resp]
        # 全 symbol：拉一次 open orders 再逐 symbol cancel
        open_orders = self._client.signed("GET", "/fapi/v1/openOrders", {})
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for o in open_orders or []:
            s = o.get("symbol")
            if s in seen:
                continue
            seen.add(s)
            try:
                results.append(self._client.signed("DELETE", "/fapi/v1/allOpenOrders", {"symbol": s}))
            except Exception as exc:  # noqa: BLE001
                results.append({"error": str(exc), "symbol": s})
        self._audit.log("binance_um_cancel_all", {"count": len(results)})
        return results

    def close_position(self, symbol: str, side: str = "sell") -> dict[str, Any]:
        """市价 closePosition；Kill Switch 另一半。"""

        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "closePosition": "true",
            "newClientOrderId": f"kill-{uuid.uuid4()}",
        }
        resp = self._client.signed("POST", "/fapi/v1/order", params)
        self._audit.log("binance_um_close_position", {"symbol": symbol, "raw": resp})
        return resp

    def get_position(self, symbol: str) -> Position:
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


__all__ = ["BinanceUMFuturesVenue", "FuturesSymbolFilters"]
