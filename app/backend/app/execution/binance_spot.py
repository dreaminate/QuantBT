"""M9.3 · Binance Spot venue。

支持订单类型（GOAL §M9.3 A）：LIMIT / MARKET / STOP_LOSS_LIMIT / TAKE_PROFIT_LIMIT
/ LIMIT_MAKER / OCO。下单前自动按 exchangeInfo `LOT_SIZE` / `PRICE_FILTER` /
`MIN_NOTIONAL` quantize；clientOrderId 幂等；所有动作走 audit log。
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


_BINANCE_TYPE_MAP = {
    "market": "MARKET",
    "limit": "LIMIT",
    "limit_maker": "LIMIT_MAKER",
    "stop_loss_limit": "STOP_LOSS_LIMIT",
    "stop_loss": "STOP_LOSS",
    "take_profit_limit": "TAKE_PROFIT_LIMIT",
    "take_profit": "TAKE_PROFIT",
    "oco": "OCO",
}


@dataclass
class SymbolFilters:
    min_qty: float = 0.0
    step_size: float = 0.0
    min_price: float = 0.0
    tick_size: float = 0.0
    min_notional: float = 0.0


def _quantize_down(value: float, step: float) -> float:
    if not step:
        return value
    return math.floor(value / step) * step


def _quantize_price(value: float, tick: float) -> float:
    if not tick:
        return value
    return math.floor(value / tick) * tick


class BinanceSpotVenue(ExecutionVenue):
    name = "binance_spot"

    def __init__(self, client: BinanceClient, audit: ExecutionAuditLog | None = None) -> None:
        if client.product != "spot":
            raise ValueError("BinanceSpotVenue 需要 product=spot 的 client")
        self._client = client
        self._audit = audit or ExecutionAuditLog()
        self._filters: dict[str, SymbolFilters] = {}

    @property
    def audit(self) -> ExecutionAuditLog:
        return self._audit

    def warmup(self) -> None:
        """启动时缓存 exchangeInfo 用于 quantize。"""

        info = self._client.public("GET", "/api/v3/exchangeInfo")
        for symbol in info.get("symbols", []):
            f = SymbolFilters()
            for flt in symbol.get("filters", []):
                if flt["filterType"] == "LOT_SIZE":
                    f.min_qty = float(flt.get("minQty", 0))
                    f.step_size = float(flt.get("stepSize", 0))
                elif flt["filterType"] == "PRICE_FILTER":
                    f.min_price = float(flt.get("minPrice", 0))
                    f.tick_size = float(flt.get("tickSize", 0))
                elif flt["filterType"] in {"MIN_NOTIONAL", "NOTIONAL"}:
                    f.min_notional = float(flt.get("minNotional", flt.get("notional", 0)))
            self._filters[symbol["symbol"].upper()] = f

    def place_order(self, order: Order) -> OrderAck:
        binance_type = _BINANCE_TYPE_MAP.get(order.order_type)
        if binance_type is None:
            raise NotImplementedError(f"binance_spot 不支持 {order.order_type}")
        sym = order.symbol.upper()
        filt = self._filters.get(sym, SymbolFilters())
        qty = _quantize_down(order.quantity, filt.step_size) if filt.step_size else order.quantity
        if filt.min_qty and qty < filt.min_qty:
            raise PermissionError(f"qty {qty} 低于 {sym} minQty {filt.min_qty}")
        params: dict[str, Any] = {
            "symbol": sym,
            "side": order.side.upper(),
            "type": binance_type,
            "quantity": qty,
            "newClientOrderId": order.client_order_id or str(uuid.uuid4()),
        }
        if order.price is not None:
            price = _quantize_price(order.price, filt.tick_size) if filt.tick_size else order.price
            params["price"] = price
        if order.stop_price is not None:
            params["stopPrice"] = _quantize_price(order.stop_price, filt.tick_size) if filt.tick_size else order.stop_price
        if filt.min_notional and order.price:
            notional = qty * (order.price or 0)
            if notional < filt.min_notional:
                raise PermissionError(f"name {sym} 名义 {notional} 低于 minNotional {filt.min_notional}")
        if binance_type in {"LIMIT", "LIMIT_MAKER", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"}:
            params["timeInForce"] = order.time_in_force or "GTC"
        endpoint = "/api/v3/order/oco" if binance_type == "OCO" else "/api/v3/order"
        resp = self._client.signed("POST", endpoint, params)
        ack = OrderAck(
            order_id=str(resp.get("orderId") or resp.get("orderListId") or params["newClientOrderId"]),
            client_order_id=params["newClientOrderId"],
            status=str(resp.get("status", "new")).lower(),
            raw=resp,
        )
        self._audit.log("binance_spot_place", {"order": order.to_dict(), "ack": ack.to_dict()})
        return ack

    def cancel_order(self, order_id: str, symbol: str | None = None) -> CancelAck:  # type: ignore[override]
        params: dict[str, Any] = {"orderId": order_id}
        if symbol:
            params["symbol"] = symbol.upper()
        resp = self._client.signed("DELETE", "/api/v3/order", params)
        self._audit.log("binance_spot_cancel", {"order_id": order_id, "raw": resp})
        return CancelAck(order_id=order_id, raw=resp)

    def cancel_all_open(self) -> list[dict[str, Any]]:
        """Kill Switch 一部分：撤销所有当前 open orders。"""

        open_orders = self._client.signed("GET", "/api/v3/openOrders", {})
        results: list[dict[str, Any]] = []
        for o in open_orders or []:
            try:
                results.append(self._client.signed("DELETE", "/api/v3/order", {"symbol": o["symbol"], "orderId": o["orderId"]}))
            except Exception as exc:  # noqa: BLE001
                results.append({"error": str(exc), "order_id": o.get("orderId")})
        self._audit.log("binance_spot_cancel_all", {"count": len(results)})
        return results

    def get_position(self, symbol: str) -> Position:
        balances = self.get_balance()
        base = symbol.replace("USDT", "").replace("BUSD", "").replace("USD", "")
        bal = balances.get(base.upper())
        qty = bal.total if bal else 0.0
        return Position(symbol=symbol, quantity=qty)

    def get_balance(self) -> dict[str, Balance]:
        resp = self._client.signed("GET", "/api/v3/account", {})
        out: dict[str, Balance] = {}
        for b in resp.get("balances", []):
            asset = b.get("asset")
            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))
            if free or locked:
                out[asset] = Balance(asset=asset, free=free, locked=locked)
        return out


__all__ = ["BinanceSpotVenue", "SymbolFilters"]
