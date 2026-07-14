"""Experimental Binance user-data WebSocket prototype.

This class is exported for isolated compatibility tests but is **not** wired to
FastAPI startup, account activation, formal execution projection, or health.
It keeps a ``BinanceClient`` for its lifetime and therefore does not satisfy the
production JIT lease-only credential boundary.  Production copy-trade state is
currently recovered by the account-scoped 30-second REST reconciler using the
exact ``/order`` + ``/userTrades`` execution bundle and the persistent formal/
risk ledgers.

Do not instantiate this class in a production path until a lease-scoped stream
supervisor, generation rotation, durable inbox, authoritative gap reconciliation,
and clean shutdown semantics are implemented and tested.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from ..lineage.ids import content_hash
from .base import ExecutionAuditLog, ExecutionReport, Position, canonical_raw_event_hash
from .binance_client import BinanceClient


logger = logging.getLogger(__name__)


_WS_BASES: dict[tuple[str, str], str] = {
    ("spot", "mainnet"): "wss://stream.binance.com:9443/ws",
    ("spot", "testnet"): "wss://stream.testnet.binance.vision/ws",
    ("usdm_futures", "mainnet"): "wss://fstream.binance.com/ws",
    ("usdm_futures", "testnet"): "wss://stream.binancefuture.com/ws",
}


@dataclass
class WSStreamerState:
    listen_key: str = ""
    last_renew_at_utc: str | None = None
    last_message_at_utc: str | None = None
    connected: bool = False
    reconnect_count: int = 0
    reconcile_count: int = 0
    orphan_count: int = 0
    last_error: str | None = None
    backoff_seconds: float = 1.0


@dataclass
class UserDataEvent:
    event_type: str           # "ORDER_TRADE_UPDATE" / "ACCOUNT_UPDATE" / "executionReport" / ...
    timestamp_utc: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"event_type": self.event_type, "timestamp_utc": self.timestamp_utc, "payload": self.payload}


class BinanceUserDataStream:
    """Unwired compatibility prototype; not an authoritative runtime stream."""

    def __init__(
        self,
        client: BinanceClient,
        *,
        on_event: Callable[[UserDataEvent], None] | None = None,
        on_execution: Callable[[ExecutionReport], None] | None = None,
        reconcile_interval_s: float = 120,
        renew_interval_s: float = 25 * 60,  # 30 min Binance 限制；25 留 buffer
        max_backoff_s: float = 60.0,
        audit: ExecutionAuditLog | None = None,
    ) -> None:
        self._client = client
        self._product = client.product
        self._network = client.network
        self._on_event = on_event
        self._on_execution = on_execution
        self._reconcile_interval = reconcile_interval_s
        self._renew_interval = renew_interval_s
        self._max_backoff = max_backoff_s
        self._audit = audit or ExecutionAuditLog()
        self._state = WSStreamerState()
        self._stop_event = threading.Event()
        self._ws_thread: threading.Thread | None = None
        self._renew_thread: threading.Thread | None = None
        self._reconcile_thread: threading.Thread | None = None
        self._open_orders_local: dict[str, dict[str, Any]] = {}  # orderId -> order
        self._positions: dict[str, Position] = {}
        self._lock = threading.RLock()

    @property
    def state(self) -> WSStreamerState:
        return self._state

    # ----- listenKey 生命周期 -----

    def create_listen_key(self) -> str:
        path = (
            "/sapi/v1/userDataStream"  # 注意：Spot 实际为 /api/v3/userDataStream，
            if self._product == "usdm_futures"
            else "/api/v3/userDataStream"
        )
        # USDM Futures 的 listenKey endpoint 是 /fapi/v1/listenKey
        if self._product == "usdm_futures":
            data = self._client.signed("POST", "/fapi/v1/listenKey", {})
        else:
            r = self._client.public("POST", "/api/v3/userDataStream", {})
            data = r if isinstance(r, dict) else {}
        key = data.get("listenKey", "")
        if not key:
            raise RuntimeError(f"未拿到 listenKey, response={data}")
        with self._lock:
            self._state.listen_key = key
            self._state.last_renew_at_utc = datetime.now(UTC).isoformat()
        return key

    def renew_listen_key(self) -> bool:
        if not self._state.listen_key:
            return False
        try:
            if self._product == "usdm_futures":
                self._client.signed("PUT", "/fapi/v1/listenKey", {})
            else:
                self._client.public(
                    "PUT",
                    f"/api/v3/userDataStream?listenKey={self._state.listen_key}",
                    {},
                )
            with self._lock:
                self._state.last_renew_at_utc = datetime.now(UTC).isoformat()
            self._audit.log("listenkey_renew", {"product": self._product})
            return True
        except Exception as exc:  # noqa: BLE001
            self._state.last_error = f"renew_listen_key 失败：{exc}"
            return False

    def close_listen_key(self) -> None:
        if not self._state.listen_key:
            return
        try:
            if self._product == "usdm_futures":
                self._client.signed("DELETE", "/fapi/v1/listenKey", {})
            else:
                self._client.public(
                    "DELETE",
                    f"/api/v3/userDataStream?listenKey={self._state.listen_key}",
                    {},
                )
        except Exception:  # noqa: BLE001
            pass

    # ----- 启动 / 停止 -----

    def start(self) -> None:
        if self._ws_thread and self._ws_thread.is_alive():
            return
        self._stop_event.clear()
        self._ws_thread = threading.Thread(target=self._ws_loop, name="binance-ws", daemon=True)
        self._renew_thread = threading.Thread(target=self._renew_loop, name="binance-renew", daemon=True)
        self._reconcile_thread = threading.Thread(target=self._reconcile_loop, name="binance-reconcile", daemon=True)
        self._ws_thread.start()
        self._renew_thread.start()
        self._reconcile_thread.start()
        self._audit.log("ws_start", {"product": self._product, "network": self._network})

    def stop(self) -> None:
        self._stop_event.set()
        for t in (self._ws_thread, self._renew_thread, self._reconcile_thread):
            if t and t.is_alive():
                t.join(timeout=2)
        self.close_listen_key()
        self._audit.log("ws_stop", {"product": self._product})

    # ----- 后台循环 -----

    def _ws_loop(self) -> None:
        import websocket  # type: ignore[import-not-found]

        url_base = _WS_BASES[(self._product, self._network)]
        while not self._stop_event.is_set():
            try:
                if not self._state.listen_key:
                    self.create_listen_key()
                url = f"{url_base}/{self._state.listen_key}"
                ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                with self._lock:
                    self._state.connected = True
                ws.run_forever(ping_interval=180, ping_timeout=20)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._state.last_error = f"ws_loop: {exc}"
            with self._lock:
                self._state.connected = False
                self._state.reconnect_count += 1
                wait_s = min(self._state.backoff_seconds, self._max_backoff)
                self._state.backoff_seconds = min(self._state.backoff_seconds * 2, self._max_backoff)
            if self._stop_event.wait(wait_s):
                break

    def _on_open(self, _ws: Any) -> None:
        with self._lock:
            self._state.connected = True
            self._state.backoff_seconds = 1.0
        self._audit.log("ws_open", {"listen_key_prefix": self._state.listen_key[:8]})

    def _on_message(self, _ws: Any, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        event_type = data.get("e") or data.get("eventType") or "unknown"
        ts_iso = datetime.now(UTC).isoformat()
        with self._lock:
            self._state.last_message_at_utc = ts_iso
        event = UserDataEvent(event_type=event_type, timestamp_utc=ts_iso, payload=data)
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("on_event handler 抛错：%s", exc)
        self._dispatch_execution(event)

    def _on_error(self, _ws: Any, error: Any) -> None:
        with self._lock:
            self._state.last_error = f"ws error: {error}"
        self._audit.log("ws_error", {"error": str(error)[:200]})

    def _on_close(self, _ws: Any, *_args: Any) -> None:
        with self._lock:
            self._state.connected = False
        self._audit.log("ws_close", {})

    def _renew_loop(self) -> None:
        while not self._stop_event.wait(self._renew_interval):
            self.renew_listen_key()

    def _reconcile_loop(self) -> None:
        while not self._stop_event.wait(self._reconcile_interval):
            try:
                self.reconcile_once()
            except Exception as exc:  # noqa: BLE001
                self._state.last_error = f"reconcile: {exc}"

    # ----- execution 派发 + 对账 -----

    def _dispatch_execution(self, event: UserDataEvent) -> None:
        if not self._on_execution:
            return
        et = event.event_type
        p = event.payload
        if et in {"executionReport", "ORDER_TRADE_UPDATE"}:
            # Spot executionReport 直接用顶层字段；USDM 走 o 子对象
            order = p.get("o", p)
            try:
                source_ms = order.get("T") or p.get("E") or p.get("eventTime")
                source_timestamp = (
                    datetime.fromtimestamp(float(source_ms) / 1000, tz=UTC).isoformat()
                    if source_ms not in (None, "")
                    else event.timestamp_utc
                )
                raw_event_hash = canonical_raw_event_hash(p)
                source_event_ref = "binance_execution_" + content_hash(
                    {
                        "event_type": et,
                        "order_id": str(order.get("i") or order.get("orderId") or ""),
                        "trade_id": str(order.get("t") or order.get("tradeId") or ""),
                        "client_order_id": str(order.get("c") or order.get("clientOrderId") or ""),
                        "event_time": source_timestamp,
                        "cumulative_filled_qty": str(order.get("z") or "0"),
                        "raw_event_hash": raw_event_hash,
                    }
                )
                report = ExecutionReport(
                    order_id=str(order.get("i") or order.get("orderId") or ""),
                    symbol=str(order.get("s") or order.get("symbol") or ""),
                    side=("buy" if str(order.get("S", "")).upper() == "BUY" else "sell"),
                    filled_qty=float(order.get("l") or 0),
                    cumulative_filled_qty=float(order.get("z") or 0),
                    fill_price=float(order.get("L") or order.get("ap") or 0),
                    commission=float(order.get("n") or 0),
                    commission_asset=str(order.get("N") or ""),
                    status=_normalize_status(str(order.get("X", "")).lower()),
                    timestamp_utc=source_timestamp,
                    raw=p,
                    client_order_id=str(order.get("c") or order.get("clientOrderId") or "") or None,
                    source_event_ref=source_event_ref,
                    raw_event_hash=raw_event_hash,
                )
                self._on_execution(report)
                # 本地仓位更新：累计 filled
                with self._lock:
                    oid = report.order_id
                    self._open_orders_local[oid] = {
                        **self._open_orders_local.get(oid, {}),
                        "status": report.status,
                        "cumulative_filled": report.cumulative_filled_qty,
                    }
                    if report.status in {"filled", "canceled", "rejected", "expired"}:
                        self._open_orders_local.pop(oid, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("execution 派发失败：%s", exc)

    def reconcile_once(self) -> list[dict[str, Any]]:
        """对账：远端 openOrders vs 本地缓存；返回 (orphan_remote / orphan_local) 列表。"""

        try:
            remote = self._client.signed(
                "GET",
                "/fapi/v1/openOrders" if self._product == "usdm_futures" else "/api/v3/openOrders",
                {},
            )
        except Exception as exc:  # noqa: BLE001
            self._state.last_error = f"reconcile fetch: {exc}"
            return []
        remote_ids = {str(o.get("orderId")): o for o in (remote or [])}
        with self._lock:
            local_ids = set(self._open_orders_local.keys())
        orphan_local = [oid for oid in local_ids if oid not in remote_ids]
        orphan_remote = [oid for oid in remote_ids if oid not in local_ids]
        diffs: list[dict[str, Any]] = []
        for oid in orphan_local:
            diffs.append({"side": "orphan_local", "order_id": oid})
            with self._lock:
                self._open_orders_local.pop(oid, None)
        for oid in orphan_remote:
            diffs.append({"side": "orphan_remote", "order_id": oid, "raw": remote_ids[oid]})
            with self._lock:
                self._open_orders_local[oid] = {"status": "new", "from": "reconcile"}
        with self._lock:
            self._state.reconcile_count += 1
            self._state.orphan_count += len(diffs)
        self._audit.log("ws_reconcile", {"diffs_count": len(diffs)})
        return diffs

    # ----- 本地状态 snapshot -----

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self._state.connected,
                "listen_key_prefix": (self._state.listen_key or "")[:8],
                "last_message_at_utc": self._state.last_message_at_utc,
                "last_renew_at_utc": self._state.last_renew_at_utc,
                "reconnect_count": self._state.reconnect_count,
                "reconcile_count": self._state.reconcile_count,
                "orphan_count": self._state.orphan_count,
                "open_orders_local": list(self._open_orders_local.keys()),
                "last_error": self._state.last_error,
            }


def _normalize_status(raw: str) -> Literal["new", "partially_filled", "filled", "canceled", "rejected", "expired"]:
    s = raw.lower()
    mapping: dict[str, str] = {
        "new": "new",
        "partially_filled": "partially_filled",
        "filled": "filled",
        "canceled": "canceled",
        "cancelled": "canceled",
        "rejected": "rejected",
        "expired": "expired",
    }
    return mapping.get(s, "new")  # type: ignore[return-value]


__all__ = ["BinanceUserDataStream", "UserDataEvent", "WSStreamerState"]
