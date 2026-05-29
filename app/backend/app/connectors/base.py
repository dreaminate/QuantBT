"""M3a · DataConnector 抽象基类。

设计原则（对齐 QuantBT-GOAL.md §M3）：

- **统一 schema**：所有 OHLCV connector 都必须把数据归一化到 `UNIFIED_OHLCV_COLUMNS`，
  时区统一存 UTC（用 pl.Datetime("us", "UTC")）；展示层再按市场转地区时区。
- **可注册**：`ConnectorRegistry` 提供进程内的注册/查找，新加 connector 只要
  `@registry.register(name="my")` 装饰一下。
- **可枚举**：每个 connector 通过 `describe()` 报告自己的 metadata（用于前端
  下拉、Agent tool schema、freshness 显示）。
- **可健康检查**：`health_check()` 用最便宜的请求探活，前端 freshness 板用。
- **可分页 + 退避**：fetch 必须能在限流下自动 sleep + 退避（具体策略由各
  connector 决定，但调用方拿到的永远是合并后的完整 polars DataFrame）。
- **可审计**：每次 fetch 都返回 `FetchResult`，包含 source/checksum/row_count
  /coverage，便于 `data_quality.py` 登记 `dataset_version`。
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import polars as pl


AssetClassTag = Literal[
    "equity_cn",
    "crypto_spot",
    "crypto_perp",
    "crypto_options",
    "external_macro",
    "external_onchain",
    "custom",
]
ConnectorAuthMode = Literal["none", "token", "api_key", "oauth2", "header", "query"]


UNIFIED_OHLCV_COLUMNS: tuple[str, ...] = (
    "ts",          # pl.Datetime("us", "UTC")
    "symbol",      # str
    "market",      # str e.g. "stocks_cn", "binanceusdm", "binance_spot"
    "interval",    # str e.g. "1d", "1h", "1m"
    "open",        # f64
    "high",        # f64
    "low",         # f64
    "close",       # f64
    "volume",      # f64
    "amount",      # f64 (turnover, optional → 0.0 fill)
)


UNIFIED_OHLCV_SCHEMA: dict[str, pl.DataType] = {
    "ts": pl.Datetime("us", "UTC"),
    "symbol": pl.String,
    "market": pl.String,
    "interval": pl.String,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "amount": pl.Float64,
}


@dataclass(frozen=True)
class ConnectorCapability:
    """对前端 / Agent 暴露的 connector 元数据。"""

    name: str
    label: str
    asset_class: AssetClassTag
    supported_markets: tuple[str, ...]
    supported_intervals: tuple[str, ...]
    supported_data_kinds: tuple[str, ...]  # 例如 "ohlcv" / "funding_rate" / "trades"
    auth_mode: ConnectorAuthMode
    rate_limit_per_minute: int | None
    realtime: bool
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "asset_class": self.asset_class,
            "supported_markets": list(self.supported_markets),
            "supported_intervals": list(self.supported_intervals),
            "supported_data_kinds": list(self.supported_data_kinds),
            "auth_mode": self.auth_mode,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "realtime": self.realtime,
            "note": self.note,
        }


@dataclass
class ConnectorHealth:
    name: str
    ok: bool
    checked_at_utc: str
    latency_ms: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "checked_at_utc": self.checked_at_utc,
            "latency_ms": round(self.latency_ms, 2),
            "detail": self.detail,
        }


@dataclass
class FetchRequest:
    symbol: str
    interval: str
    start: datetime | None = None
    end: datetime | None = None
    data_kind: str = "ohlcv"
    market: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def cache_key(self) -> str:
        payload = {
            "symbol": self.symbol,
            "interval": self.interval,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "data_kind": self.data_kind,
            "market": self.market,
            "extra": _normalize(self.extra),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass
class FetchResult:
    """`fetch` 返回的标准结果，便于 data_quality.py 直接登记。"""

    frame: pl.DataFrame
    source_name: str
    fetched_at_utc: str
    row_count: int
    coverage_start_utc: str | None
    coverage_end_utc: str | None
    sha256: str

    def to_meta(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "fetched_at_utc": self.fetched_at_utc,
            "row_count": self.row_count,
            "coverage_start_utc": self.coverage_start_utc,
            "coverage_end_utc": self.coverage_end_utc,
            "sha256": self.sha256,
        }


def make_fetch_result(frame: pl.DataFrame, source_name: str) -> FetchResult:
    """从 polars DataFrame 构造 FetchResult，自动算 checksum / coverage。"""

    aligned = enforce_unified_schema(frame)
    rows = aligned.height
    coverage_start = coverage_end = None
    if rows:
        ts_col = aligned.get_column("ts")
        coverage_start = ts_col.min().isoformat() if ts_col.min() is not None else None
        coverage_end = ts_col.max().isoformat() if ts_col.max() is not None else None
    return FetchResult(
        frame=aligned,
        source_name=source_name,
        fetched_at_utc=datetime.now(UTC).isoformat(),
        row_count=rows,
        coverage_start_utc=coverage_start,
        coverage_end_utc=coverage_end,
        sha256=_sha256_of_frame(aligned),
    )


def make_wide_fetch_result(frame: pl.DataFrame, source_name: str) -> FetchResult:
    """`make_fetch_result` 的对偶：**保留全部原生列（宽字段）**，不做 OHLCV 投影。

    用于数据平台 v2 的"拉全字段"落盘（Tushare 基本面/财务/资金流、Binance 资金费率/持仓量等）。
    消费侧需要固定 10 列时再调 `to_ohlcv_view()`。
    """

    df = frame if frame is not None else pl.DataFrame()
    rows = df.height
    coverage_start = coverage_end = None
    if rows and "ts" in df.columns:
        ts_col = df.get_column("ts")
        cmin, cmax = ts_col.min(), ts_col.max()
        try:
            coverage_start = cmin.isoformat() if cmin is not None else None
            coverage_end = cmax.isoformat() if cmax is not None else None
        except AttributeError:
            coverage_start = str(cmin) if cmin is not None else None
            coverage_end = str(cmax) if cmax is not None else None
    return FetchResult(
        frame=df,
        source_name=source_name,
        fetched_at_utc=datetime.now(UTC).isoformat(),
        row_count=rows,
        coverage_start_utc=coverage_start,
        coverage_end_utc=coverage_end,
        sha256=_sha256_of_frame(df),
    )


def enforce_unified_schema(frame: pl.DataFrame) -> pl.DataFrame:
    """把任意 DataFrame 强制对齐到统一 OHLCV schema，缺失列填空。"""

    if frame is None or frame.is_empty():
        return pl.DataFrame(schema=UNIFIED_OHLCV_SCHEMA)
    missing = [c for c in UNIFIED_OHLCV_COLUMNS if c not in frame.columns]
    df = frame
    for col in missing:
        dtype = UNIFIED_OHLCV_SCHEMA[col]
        if col == "amount":
            df = df.with_columns(pl.lit(0.0).cast(dtype).alias(col))
        else:
            df = df.with_columns(pl.lit(None).cast(dtype).alias(col))
    df = df.select(list(UNIFIED_OHLCV_COLUMNS))
    df = df.with_columns(
        [
            pl.col(c).cast(dtype, strict=False)
            for c, dtype in UNIFIED_OHLCV_SCHEMA.items()
        ]
    )
    if df.height:
        df = df.sort(["symbol", "ts"])
    return df


# 语义别名：消费侧"把宽表投影成固定 10 列 OHLCV 视图"，与落盘侧的"强制门"用途区分开。
# 数据平台 v2 起，落盘走 make_wide_fetch_result 保留宽字段，只有兼容路径调 to_ohlcv_view。
to_ohlcv_view = enforce_unified_schema


def _sha256_of_frame(df: pl.DataFrame) -> str:
    if df.is_empty():
        return hashlib.sha256(b"").hexdigest()
    buf = df.write_ipc(file=None, compression="uncompressed")
    return hashlib.sha256(buf.getvalue() if hasattr(buf, "getvalue") else buf).hexdigest()


def _normalize(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _normalize(v[k]) for k in sorted(v)}
    if isinstance(v, list | tuple):
        return [_normalize(x) for x in v]
    return v


class DataConnector(ABC):
    """所有数据 connector 的基类。"""

    @abstractmethod
    def describe(self) -> ConnectorCapability: ...

    @abstractmethod
    def fetch(self, request: FetchRequest) -> FetchResult: ...

    def list_symbols(self, market: str | None = None) -> list[str]:  # noqa: ARG002
        return []

    def health_check(self) -> ConnectorHealth:
        cap = self.describe()
        return ConnectorHealth(
            name=cap.name,
            ok=True,
            checked_at_utc=datetime.now(UTC).isoformat(),
            latency_ms=0.0,
            detail="default ok",
        )


class ConnectorFactory(Protocol):
    def __call__(self, **kwargs: Any) -> DataConnector: ...


class ConnectorRegistry:
    """全局 connector 注册中心。"""

    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}
        self._singletons: dict[str, DataConnector] = {}

    def register(
        self, name: str | None = None
    ):
        def _decorator(factory: ConnectorFactory) -> ConnectorFactory:
            key = name or getattr(factory, "__name__", str(factory))
            self._factories[key] = factory
            return factory
        return _decorator

    def register_instance(self, name: str, connector: DataConnector) -> None:
        self._singletons[name] = connector
        self._factories[name] = lambda **_: connector

    def names(self) -> list[str]:
        return sorted(self._factories.keys())

    def get(self, name: str, **kwargs: Any) -> DataConnector:
        if name in self._singletons and not kwargs:
            return self._singletons[name]
        if name not in self._factories:
            raise KeyError(f"connector 不存在: {name}（已注册 {self.names()}）")
        connector = self._factories[name](**kwargs)
        return connector

    def describe_all(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for name in self.names():
            try:
                c = self.get(name)
                items.append(c.describe().to_dict())
            except Exception as exc:  # noqa: BLE001
                items.append({"name": name, "error": str(exc)})
        return items

    def health_all(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for name in self.names():
            try:
                t0 = time.perf_counter()
                hc = self.get(name).health_check()
                hc.latency_ms = (time.perf_counter() - t0) * 1000
                results.append(hc.to_dict())
            except Exception as exc:  # noqa: BLE001
                results.append(
                    ConnectorHealth(
                        name=name,
                        ok=False,
                        checked_at_utc=datetime.now(UTC).isoformat(),
                        latency_ms=0.0,
                        detail=f"health check failed: {exc}",
                    ).to_dict()
                )
        return results


registry = ConnectorRegistry()


__all__ = [
    "AssetClassTag",
    "ConnectorAuthMode",
    "ConnectorCapability",
    "ConnectorHealth",
    "ConnectorRegistry",
    "DataConnector",
    "FetchRequest",
    "FetchResult",
    "UNIFIED_OHLCV_COLUMNS",
    "UNIFIED_OHLCV_SCHEMA",
    "enforce_unified_schema",
    "make_fetch_result",
    "make_wide_fetch_result",
    "registry",
    "to_ohlcv_view",
]
