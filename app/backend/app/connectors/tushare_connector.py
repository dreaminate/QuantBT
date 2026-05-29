"""Tushare connector · A股全字段拉取（数据平台 v2）。

设计：
- describe() 报告 A股能力 + 2000 积分档**可用**的 data_kind 全集。
- fetch(data_kind) 按接口规格调用 `pro.<method>(ts_code=, start_date=, end_date=)`，
  **保留接口返回的全部原始列**（宽字段），只把 ts 列规整为 UTC datetime、价格类把
  vol→volume（保证 OHLCV 兼容视图可用），并补 symbol/market/interval。落 make_wide_fetch_result。
- 需 5000+ 积分的接口（stk_factor / fund_daily / top_inst 等）在 2000 档显式拒绝并提示，
  不静默返回空。
- token 走环境变量 `TUSHARE_TOKEN`，绝不进 YAML。令牌桶限流 + 命中错误自动 sleep。
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

from .base import (
    ConnectorCapability,
    ConnectorHealth,
    DataConnector,
    FetchRequest,
    FetchResult,
    enforce_unified_schema,
    make_fetch_result,
    make_wide_fetch_result,
)


_RATE_LIMIT_PER_MIN = 480
_MARKETS = ("stocks_cn", "indices_cn", "funds_cn", "bonds_cn", "stocks_hk", "stocks_us")
_INTERVALS = ("1d", "1w", "1mo", "1m", "5m", "15m", "30m", "60m")

# data_kind -> (pro 方法名, 时间列, 是否价格类[需 vol→volume + OHLCV 兼容], 默认市场)
# 仅收录 Tushare 2000 积分档**可用**的接口（已对官方积分表核实）。
_TUSHARE_SPEC: dict[str, tuple[str, str, bool, str]] = {
    "ohlcv": ("daily", "trade_date", True, "stocks_cn"),
    "daily_basic": ("daily_basic", "trade_date", False, "stocks_cn"),
    "adj_factor": ("adj_factor", "trade_date", False, "stocks_cn"),
    "moneyflow": ("moneyflow", "trade_date", False, "stocks_cn"),
    "index_daily": ("index_daily", "trade_date", True, "indices_cn"),
    "fina_indicator": ("fina_indicator", "end_date", False, "stocks_cn"),
    "income": ("income", "end_date", False, "stocks_cn"),
    "balancesheet": ("balancesheet", "end_date", False, "stocks_cn"),
    "cashflow": ("cashflow", "end_date", False, "stocks_cn"),
}

# 高积分档接口，2000 档不可用 —— 显式拒绝并提示（而非静默空 / 被服务端拒）。
# index_dailybasic 实测需 4000 积分（见 tushare_quant1/tushare_provider.py），其余需 5000+。
_TUSHARE_GATED = {"stk_factor", "stk_factor_pro", "fund_daily", "top_inst", "index_basic", "index_dailybasic"}


class TushareConnector(DataConnector):
    def __init__(self, token: str | None = None, sleep: float = 0.0) -> None:
        self._token = token or os.environ.get("TUSHARE_TOKEN", "")
        self._sleep = sleep
        self._last_call: float | None = None
        self._calls_in_window: list[float] = []

    def describe(self) -> ConnectorCapability:
        return ConnectorCapability(
            name="tushare",
            label="Tushare Pro (A股)",
            asset_class="equity_cn",
            supported_markets=_MARKETS,
            supported_intervals=_INTERVALS,
            supported_data_kinds=tuple(_TUSHARE_SPEC.keys()),
            auth_mode="token",
            rate_limit_per_minute=_RATE_LIMIT_PER_MIN,
            realtime=False,
            note=(
                "Token 走 TUSHARE_TOKEN 环境变量；480 次/分钟令牌桶。"
                "全字段拉取保留接口原生列；stk_factor/fund_daily/top_inst 需 5000+ 积分不在此列。"
            ),
        )

    def health_check(self) -> ConnectorHealth:
        ts_iso = datetime.now(UTC).isoformat()
        if not self._token:
            return ConnectorHealth(
                name="tushare",
                ok=False,
                checked_at_utc=ts_iso,
                latency_ms=0.0,
                detail="TUSHARE_TOKEN 未配置",
            )
        try:
            t0 = time.perf_counter()
            pro = self._client()
            df = pro.stock_basic(exchange="SSE", list_status="L", limit=1)
            latency = (time.perf_counter() - t0) * 1000
            return ConnectorHealth(
                name="tushare",
                ok=df is not None,
                checked_at_utc=ts_iso,
                latency_ms=latency,
                detail=f"stock_basic rows={len(df) if df is not None else 0}",
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(
                name="tushare",
                ok=False,
                checked_at_utc=ts_iso,
                latency_ms=0.0,
                detail=f"tushare error: {exc}",
            )

    def list_symbols(self, market: str | None = None) -> list[str]:
        if market not in (None, "stocks_cn"):
            return []
        if not self._token:
            return []
        try:
            df = self._client().stock_basic(exchange="", list_status="L", fields="ts_code")
            return df["ts_code"].astype(str).tolist() if df is not None else []
        except Exception:  # noqa: BLE001
            return []

    def fetch(self, request: FetchRequest) -> FetchResult:
        if not self._token:
            raise RuntimeError("TUSHARE_TOKEN 未配置（请通过环境变量或 UI 设置后再使用 Tushare connector）")
        kind = request.data_kind or "ohlcv"
        if kind in _TUSHARE_GATED:
            raise NotImplementedError(
                f"Tushare 接口 {kind} 需更高积分档（index_dailybasic=4000 / stk_factor 等=5000+），2000 积分档不可用"
            )
        if kind not in _TUSHARE_SPEC:
            raise NotImplementedError(f"tushare connector 不支持 data_kind={kind}（可用：{sorted(_TUSHARE_SPEC)}）")

        method, ts_col, price_like, default_market = _TUSHARE_SPEC[kind]
        self._throttle()
        pro = self._client()
        start = (request.start or datetime.now(UTC) - timedelta(days=365)).strftime("%Y%m%d")
        end = (request.end or datetime.now(UTC)).strftime("%Y%m%d")
        fn = getattr(pro, method)
        df = fn(ts_code=request.symbol, start_date=start, end_date=end)
        if df is None or df.empty:
            return make_fetch_result(enforce_unified_schema(pl.DataFrame()), source_name="tushare")

        pl_df = pl.from_pandas(df)
        # ts_code 与 symbol 冗余，去掉避免噪声列
        if "ts_code" in pl_df.columns:
            pl_df = pl_df.drop("ts_code")
        # 时间列规整为 UTC datetime
        if ts_col in pl_df.columns:
            pl_df = pl_df.rename({ts_col: "ts"}).with_columns(
                pl.col("ts").cast(pl.String).str.to_datetime("%Y%m%d", time_zone="UTC", strict=False)
            )
        # 价格类：vol→volume，保证固定 10 列 OHLCV 兼容视图可用
        if price_like and "vol" in pl_df.columns and "volume" not in pl_df.columns:
            pl_df = pl_df.rename({"vol": "volume"})
        market = request.market or default_market
        pl_df = pl_df.with_columns(
            [
                pl.lit(request.symbol).alias("symbol"),
                pl.lit(market).alias("market"),
                pl.lit(request.interval or "1d").alias("interval"),
            ]
        )
        if "amount" in pl_df.columns:
            pl_df = pl_df.with_columns(pl.col("amount").cast(pl.Float64, strict=False))
        # 保留**全部**原生列（宽字段），不投影
        return make_wide_fetch_result(pl_df, source_name="tushare")

    def _throttle(self) -> None:
        now = time.perf_counter()
        window = 60.0
        self._calls_in_window = [t for t in self._calls_in_window if now - t < window]
        if len(self._calls_in_window) >= _RATE_LIMIT_PER_MIN:
            sleep_s = window - (now - self._calls_in_window[0]) + 0.01
            if sleep_s > 0:
                time.sleep(sleep_s)
        self._calls_in_window.append(time.perf_counter())
        if self._sleep:
            time.sleep(self._sleep)

    def _client(self) -> Any:
        import tushare as ts  # 延迟 import，避免无 token 时仍触发 SDK 初始化

        ts.set_token(self._token)
        return ts.pro_api()


__all__ = ["TushareConnector"]
