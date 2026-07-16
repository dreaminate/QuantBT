"""DIY 数据源 · YAML 驱动的通用 REST connector。

用户场景：希望接入一个 QuantBT 还没内置的数据源（卖方研究、第三方API、内部系统）。
不需要写 Python，只要在 UI 里粘一份 YAML，软件即可在前端下拉看到这个 connector，
Agent 也能调用它。

YAML schema 与 §QuantBT-GOAL.md §5.5 对齐，例：

```yaml
connector_name: my_alpha_source
label: My Alpha Source
asset_class: equity_cn
base_url: https://api.example.com
auth:
  mode: header             # none | header | query | bearer
  header_name: X-API-KEY   # 仅 header
  value_env: MY_TOKEN_ENV  # 真实值不写 YAML，走环境变量
endpoints:
  ohlcv:
    method: GET
    path: /v1/quote/{symbol}/daily
    query:
      start: "{start_date}"
      end: "{end_date}"
    pagination: { style: cursor, cursor_in: "$.next", cursor_out_param: cursor }
    rate_limit_per_minute: 60
    response_mapping:
      records: "$.data[*]"        # 把数组拿出来
      fields:
        ts: timestamp
        open: o
        high: h
        low: l
        close: c
        volume: v
        amount: amt
      ts_unit: ms                  # s | ms | iso | date
      tz: UTC                      # 原始时区，自动转 UTC
schema_target: ohlcv
```

不在 YAML 里：API key/secret —— 永远走环境变量或 keyring。
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import polars as pl
import requests
import yaml
from pydantic import BaseModel, Field

from .base import (
    AssetClassTag,
    ConnectorAuthMode,
    ConnectorCapability,
    ConnectorHealth,
    DataConnector,
    FetchRequest,
    FetchResult,
    enforce_unified_schema,
    make_fetch_result,
)


class _AuthSpec(BaseModel):
    mode: Literal["none", "bearer", "header", "query"] = "none"
    header_name: str | None = None
    query_param: str | None = None
    value_env: str | None = None
    static_value: str | None = Field(default=None, repr=False)  # 仅本地调试；生产用 value_env。防明文：repr/str 永不渲染（含内嵌本 spec 的 GenericRESTConfig）


class _PaginationSpec(BaseModel):
    style: Literal["none", "cursor", "page", "offset"] = "none"
    cursor_in: str | None = None
    cursor_out_param: str | None = None
    page_param: str | None = None
    page_size_param: str | None = None
    page_size: int = 1000
    max_pages: int = 50


class _ResponseMapping(BaseModel):
    records: str = "$"
    fields: dict[str, str]
    ts_unit: Literal["s", "ms", "us", "iso", "date"] = "ms"
    tz: str = "UTC"


class _EndpointSpec(BaseModel):
    method: Literal["GET", "POST"] = "GET"
    path: str
    query: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    pagination: _PaginationSpec = Field(default_factory=_PaginationSpec)
    rate_limit_per_minute: int | None = None
    response_mapping: _ResponseMapping


class GenericRESTConfig(BaseModel):
    connector_name: str
    label: str
    asset_class: AssetClassTag = "custom"
    supported_markets: list[str] = Field(default_factory=list)
    supported_intervals: list[str] = Field(default_factory=list)
    base_url: str
    auth: _AuthSpec = Field(default_factory=_AuthSpec)
    endpoints: dict[str, _EndpointSpec]
    schema_target: Literal["ohlcv"] = "ohlcv"
    note: str = ""

    @classmethod
    def from_yaml(cls, source: str) -> "GenericRESTConfig":
        return cls.model_validate(yaml.safe_load(source))


@dataclass
class _TokenBucket:
    rate_per_minute: int | None
    _tokens: float = 0.0
    _last: float = field(default_factory=time.perf_counter)

    def consume(self) -> None:
        if not self.rate_per_minute:
            return
        rate_per_sec = self.rate_per_minute / 60.0
        capacity = max(self.rate_per_minute, 1)
        now = time.perf_counter()
        self._tokens = min(capacity, self._tokens + (now - self._last) * rate_per_sec)
        self._last = now
        if self._tokens < 1:
            sleep_s = (1 - self._tokens) / rate_per_sec
            time.sleep(sleep_s)
            self._tokens = 0
        else:
            self._tokens -= 1


def _resolve_template(template: str, ctx: dict[str, Any]) -> str:
    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        val = ctx.get(key, "")
        return "" if val is None else str(val)
    return re.sub(r"\{(\w+)\}", _sub, template)


def _resolve_dict(template: dict[str, str], ctx: dict[str, Any]) -> dict[str, str]:
    return {k: _resolve_template(v, ctx) for k, v in template.items()}


def _resolve_jsonpath(payload: Any, path: str) -> Any:
    """极简 JSONPath 子集：`$.a.b` 取标量；`$.list[*]` 取数组。"""

    if not path or path == "$":
        return payload
    if not path.startswith("$"):
        raise ValueError(f"JSONPath 必须以 $ 开头：{path}")
    cur: Any = payload
    expr = path[1:]
    tokens = re.findall(r"\.[\w_-]+|\[\d+\]|\[\*\]", expr)
    for tok in tokens:
        if cur is None:
            return None
        if tok == "[*]":
            if not isinstance(cur, list):
                raise ValueError(f"JSONPath [*] 期望 list，实际 {type(cur).__name__}")
            return cur  # 命中数组就返回；后续字段由 records 子树取
        if tok.startswith("[") and tok.endswith("]"):
            idx = int(tok[1:-1])
            cur = cur[idx] if isinstance(cur, list) and 0 <= idx < len(cur) else None
            continue
        if tok.startswith("."):
            key = tok[1:]
            cur = cur.get(key) if isinstance(cur, dict) else None
    return cur


def _coerce_ts(value: Any, unit: str) -> datetime | None:
    if value is None:
        return None
    try:
        if unit == "iso":
            ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        elif unit == "date":
            ts = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        else:
            num = float(value)
            if unit == "ms":
                num /= 1_000
            elif unit == "us":
                num /= 1_000_000
            ts = datetime.fromtimestamp(num, tz=UTC)
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    else:
        ts = ts.astimezone(UTC)
    return ts


class GenericRESTConnector(DataConnector):
    """DIY 数据源 · YAML 驱动的通用 REST connector。"""

    def __init__(
        self,
        config: GenericRESTConfig,
        http: requests.Session | None = None,
        sleep: float = 0.0,
    ) -> None:
        self._config = config
        self._http = http or requests.Session()
        self._sleep = sleep
        self._buckets: dict[str, _TokenBucket] = {
            ep_name: _TokenBucket(spec.rate_limit_per_minute)
            for ep_name, spec in config.endpoints.items()
        }

    def describe(self) -> ConnectorCapability:
        auth_mode_map: dict[str, ConnectorAuthMode] = {
            "none": "none",
            "bearer": "token",
            "header": "header",
            "query": "query",
        }
        return ConnectorCapability(
            name=self._config.connector_name,
            label=self._config.label,
            asset_class=self._config.asset_class,
            supported_markets=tuple(self._config.supported_markets),
            supported_intervals=tuple(self._config.supported_intervals or ("1d",)),
            supported_data_kinds=tuple(self._config.endpoints.keys()),
            auth_mode=auth_mode_map.get(self._config.auth.mode, "none"),
            rate_limit_per_minute=next(
                (s.rate_limit_per_minute for s in self._config.endpoints.values() if s.rate_limit_per_minute),
                None,
            ),
            realtime=False,
            note=self._config.note or "DIY YAML connector",
        )

    def health_check(self) -> ConnectorHealth:
        url = self._config.base_url
        t0 = time.perf_counter()
        try:
            resp = self._http.head(url, timeout=5)
            ok = resp.status_code < 500
            detail = f"HEAD {url} → {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = f"unreachable: {exc}"
        latency = (time.perf_counter() - t0) * 1000
        return ConnectorHealth(
            name=self._config.connector_name,
            ok=ok,
            checked_at_utc=datetime.now(UTC).isoformat(),
            latency_ms=latency,
            detail=detail,
        )

    def fetch(self, request: FetchRequest) -> FetchResult:
        spec = self._config.endpoints.get(request.data_kind)
        if spec is None:
            raise KeyError(
                f"endpoint 未在 YAML 定义：{request.data_kind}（已定义 {list(self._config.endpoints)}）"
            )
        ctx = self._build_ctx(request)
        records: list[dict[str, Any]] = []
        next_token: str | None = None
        pages = 0
        while True:
            self._buckets[request.data_kind].consume()
            page = self._call_once(spec, ctx, next_token)
            mapped = self._map_records(page, spec.response_mapping, request)
            records.extend(mapped)
            pages += 1
            if spec.pagination.style == "none" or pages >= spec.pagination.max_pages:
                break
            next_token = _resolve_jsonpath(page, spec.pagination.cursor_in or "$")
            if not next_token or spec.pagination.style not in {"cursor", "page", "offset"}:
                break
            if self._sleep:
                time.sleep(self._sleep)
        df = self._records_to_frame(records, request)
        return make_fetch_result(df, source_name=self._config.connector_name)

    def _build_ctx(self, request: FetchRequest) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "symbol": request.symbol,
            "interval": request.interval,
            "market": request.market or "",
        }
        if request.start:
            ctx["start"] = int(request.start.replace(tzinfo=UTC).timestamp())
            ctx["start_date"] = request.start.strftime("%Y-%m-%d")
            ctx["start_iso"] = request.start.isoformat()
        if request.end:
            ctx["end"] = int(request.end.replace(tzinfo=UTC).timestamp())
            ctx["end_date"] = request.end.strftime("%Y-%m-%d")
            ctx["end_iso"] = request.end.isoformat()
        ctx.update(request.extra)
        return ctx

    def _call_once(
        self,
        spec: _EndpointSpec,
        ctx: dict[str, Any],
        next_token: str | None,
    ) -> Any:
        url = self._config.base_url.rstrip("/") + "/" + _resolve_template(spec.path, ctx).lstrip("/")
        params = _resolve_dict(spec.query, ctx) if spec.query else {}
        headers: dict[str, str] = {}
        if self._config.auth.mode == "bearer":
            token = self._resolve_auth_value()
            headers["Authorization"] = f"Bearer {token}"
        elif self._config.auth.mode == "header" and self._config.auth.header_name:
            headers[self._config.auth.header_name] = self._resolve_auth_value()
        elif self._config.auth.mode == "query" and self._config.auth.query_param:
            params[self._config.auth.query_param] = self._resolve_auth_value()
        if next_token and spec.pagination.style == "cursor" and spec.pagination.cursor_out_param:
            params[spec.pagination.cursor_out_param] = str(next_token)
        elif next_token and spec.pagination.style == "page" and spec.pagination.page_param:
            params[spec.pagination.page_param] = str(next_token)
        resp = self._http.request(
            spec.method,
            url,
            params=params,
            json=spec.body,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _resolve_auth_value(self) -> str:
        auth = self._config.auth
        if auth.value_env:
            return os.environ.get(auth.value_env, "")
        return auth.static_value or ""

    def _map_records(
        self,
        payload: Any,
        mapping: _ResponseMapping,
        request: FetchRequest,
    ) -> list[dict[str, Any]]:
        rows = _resolve_jsonpath(payload, mapping.records)
        if not isinstance(rows, list):
            rows = [rows] if rows is not None else []
        out: list[dict[str, Any]] = []
        market = request.market or self._config.supported_markets[0] if self._config.supported_markets else ""
        for row in rows:
            if not isinstance(row, dict):
                continue
            mapped: dict[str, Any] = {
                "symbol": request.symbol,
                "market": market,
                "interval": request.interval,
            }
            for target, src in mapping.fields.items():
                mapped[target] = row.get(src) if isinstance(row, dict) else None
            ts_raw = mapped.get("ts")
            mapped["ts"] = _coerce_ts(ts_raw, mapping.ts_unit)
            out.append(mapped)
        return out

    def _records_to_frame(
        self,
        records: Iterable[dict[str, Any]],
        request: FetchRequest,  # noqa: ARG002
    ) -> pl.DataFrame:
        rows = list(records)
        if not rows:
            return enforce_unified_schema(pl.DataFrame())
        df = pl.DataFrame(rows)
        return enforce_unified_schema(df)


__all__ = ["GenericRESTConfig", "GenericRESTConnector"]
