"""M9.1 · DIY 交易 API · YAML 驱动的通用交易 connector。

类似 GenericRESTConnector 的概念，但用于"用户接入自己的交易所/券商/虚拟账户"。
所有 path / method / response_mapping 都在 YAML 里，工程师不写 Python 就能让 QuantBT
对接一个新交易场所（只接受被动 limit/market；不做做市）。

**安全要求**（GOAL §M9.3 同理）：
- API key 永不写 YAML，走 env 或 keystore 解析
- 启动时必须能调一个"权限/账户余额"端点确认账号能读 + 能下单（不能 withdraw）
- 所有下单走 client_order_id 幂等
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Literal

import requests
import yaml
from pydantic import BaseModel, Field

from .base import (
    Balance,
    CancelAck,
    ExecutionAuditLog,
    ExecutionVenue,
    Order,
    OrderAck,
    Position,
)


class _AuthSpec(BaseModel):
    mode: Literal["none", "bearer", "header", "query", "hmac"] = "none"
    header_name: str | None = None
    query_param: str | None = None
    value_env: str | None = None
    secret_env: str | None = None  # 用于 hmac 签名


class _EndpointSpec(BaseModel):
    method: Literal["GET", "POST", "DELETE"] = "POST"
    path: str
    body_template: dict[str, str] | None = None
    response_mapping: dict[str, str] | None = None  # JSONPath-ish


class GenericTradingConfig(BaseModel):
    venue_name: str
    base_url: str
    label: str = ""
    auth: _AuthSpec = Field(default_factory=_AuthSpec)
    place_order: _EndpointSpec
    cancel_order: _EndpointSpec
    get_balance: _EndpointSpec
    get_position: _EndpointSpec
    permission_check: _EndpointSpec | None = None
    blacklist_symbols: list[str] = Field(default_factory=list)
    per_order_max_notional: float | None = None
    # D-T025-DIY 接活进真钱面：deny-by-default 白名单。deny_by_default=True 时不在 allowed_symbols
    # （含空白名单 = 全拒）一律拒。默认 False → 向后兼容既有黑名单语义（死代码期行为不变）。
    allowed_symbols: list[str] = Field(default_factory=list)
    deny_by_default: bool = False

    @classmethod
    def from_yaml(cls, text: str) -> "GenericTradingConfig":
        return cls.model_validate(yaml.safe_load(text))


def _resolve_template(value: str, ctx: dict[str, Any]) -> str:
    import re

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        v = ctx.get(key, "")
        return "" if v is None else str(v)

    return re.sub(r"\{(\w+)\}", _sub, value)


class GenericTradingVenue(ExecutionVenue):
    """DIY 交易 venue：用户填一份 YAML，软件即可在前端下拉看到该 venue。"""

    def __init__(
        self,
        config: GenericTradingConfig,
        http: requests.Session | None = None,
        audit: ExecutionAuditLog | None = None,
    ) -> None:
        self._cfg = config
        self.name = config.venue_name
        self._http = http or requests.Session()
        self._audit = audit or ExecutionAuditLog()

    @property
    def audit(self) -> ExecutionAuditLog:
        return self._audit

    def assert_safe_startup(self) -> dict[str, Any]:
        """若 YAML 配了 permission_check，必须返回非 withdraw 权限才允许工作。"""

        if not self._cfg.permission_check:
            return {"ok": True, "checked": False, "reason": "no permission_check configured"}
        payload = self._call(self._cfg.permission_check, ctx={})
        if not isinstance(payload, dict):
            raise PermissionError(
                f"DIY venue {self.name} 的 permission_check 必须返回结构化 dict，实际 {type(payload).__name__}"
            )
        for key, value in payload.items():
            if "withdraw" in str(key).lower() and bool(value):
                raise PermissionError(
                    f"DIY venue {self.name} 检测到 {key}=True，拒绝启动（必须无 withdraw 权限）。"
                )
        return {"ok": True, "checked": True, "raw": payload}

    def place_order(self, order: Order) -> OrderAck:
        # deny-by-default 白名单（D-T025-DIY，接活进真钱面的红线）：开启后不在白名单（含空白名单）一律拒。
        # 这是 venue 级纵深防御；OrderGuard.wrap 后还要再过会话外策略门（见 guarded_generic_venue）。
        if self._cfg.deny_by_default and order.symbol not in set(self._cfg.allowed_symbols):
            raise PermissionError(
                f"{order.symbol} 不在 deny-by-default 白名单(allowed_symbols)，拒绝下单（DIY venue 接活红线）"
            )
        if order.symbol in self._cfg.blacklist_symbols:
            raise PermissionError(f"{order.symbol} 在 blacklist 中，禁止下单")
        if self._cfg.per_order_max_notional and order.price:
            notional = order.quantity * order.price
            if notional > self._cfg.per_order_max_notional:
                raise PermissionError(
                    f"订单名义 {notional:.2f} 超过单笔上限 {self._cfg.per_order_max_notional}"
                )
        client_id = order.client_order_id or str(uuid.uuid4())
        ctx = {**order.to_dict(), "client_order_id": client_id}
        payload = self._call(self._cfg.place_order, ctx=ctx)
        ack = OrderAck(
            order_id=str(payload.get("order_id") or payload.get("id") or client_id),
            client_order_id=client_id,
            status=str(payload.get("status", "new")),  # type: ignore[arg-type]
            raw=payload if isinstance(payload, dict) else {"raw": payload},
        )
        self._audit.log("generic_place", {"venue": self.name, "ack": ack.to_dict()})
        return ack

    def cancel_order(self, order_id: str) -> CancelAck:
        payload = self._call(self._cfg.cancel_order, ctx={"order_id": order_id})
        self._audit.log("generic_cancel", {"venue": self.name, "order_id": order_id, "raw": payload})
        return CancelAck(order_id=order_id, raw=payload if isinstance(payload, dict) else {})

    def get_position(self, symbol: str) -> Position:
        payload = self._call(self._cfg.get_position, ctx={"symbol": symbol})
        qty = float(payload.get("quantity", 0)) if isinstance(payload, dict) else 0.0
        return Position(symbol=symbol, quantity=qty)

    def get_balance(self) -> dict[str, Balance]:
        payload = self._call(self._cfg.get_balance, ctx={})
        if not isinstance(payload, list):
            return {}
        out: dict[str, Balance] = {}
        for item in payload:
            asset = str(item.get("asset")) if isinstance(item, dict) else None
            if not asset:
                continue
            out[asset] = Balance(asset=asset, free=float(item.get("free", 0)), locked=float(item.get("locked", 0)))
        return out

    def _call(self, spec: _EndpointSpec, ctx: dict[str, Any]) -> Any:
        url = self._cfg.base_url.rstrip("/") + "/" + _resolve_template(spec.path, ctx).lstrip("/")
        headers: dict[str, str] = {}
        params: dict[str, Any] = {}
        if self._cfg.auth.mode == "bearer":
            headers["Authorization"] = f"Bearer {self._resolve_secret('value')}"
        elif self._cfg.auth.mode == "header" and self._cfg.auth.header_name:
            headers[self._cfg.auth.header_name] = self._resolve_secret("value")
        elif self._cfg.auth.mode == "query" and self._cfg.auth.query_param:
            params[self._cfg.auth.query_param] = self._resolve_secret("value")
        body = None
        if spec.body_template:
            body = {k: _resolve_template(v, ctx) for k, v in spec.body_template.items()}
        resp = self._http.request(spec.method, url, params=params, json=body, headers=headers, timeout=15)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return {"raw": resp.text}

    def _resolve_secret(self, kind: Literal["value", "secret"]) -> str:
        env_name = self._cfg.auth.value_env if kind == "value" else self._cfg.auth.secret_env
        if not env_name:
            return ""
        return os.environ.get(env_name, "")


def guarded_generic_venue(
    config: GenericTradingConfig,
    *,
    gate: Any,
    nonce_ledger: Any | None = None,
    on_event: Any | None = None,
    http: requests.Session | None = None,
    audit: ExecutionAuditLog | None = None,
) -> Any:
    """接活 GenericTradingVenue 进真钱执行面（D-T025-DIY，D2）。

    与 relay/lease 同一道门：强制 deny_by_default 白名单（venue 级）+ OrderGuard.wrap（会话外策略门：
    S1 防重放 → S2 deny-by-default 策略门 → S3 升级）。CRYPTO_LIVE 缺 nonce 台 → OrderGuard 内部 fail-closed。
    **唯一受支持的「把 DIY venue 放进真钱面」入口**——绕过它直发 place_order 即触审计不变量红线（T-025 #1）。
    """

    from ..security.gate.enforcer import OrderGuard  # 局部 import 避免 execution→security 模块级耦合

    guarded_cfg = config.model_copy(update={"deny_by_default": True})  # 接活恒 deny-by-default，不可关
    venue = GenericTradingVenue(guarded_cfg, http=http, audit=audit)
    return OrderGuard.wrap(venue, gate=gate, nonce_ledger=nonce_ledger, on_event=on_event)


__all__ = ["GenericTradingConfig", "GenericTradingVenue", "guarded_generic_venue"]
