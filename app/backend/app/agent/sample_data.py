"""DS-1 · 交付门垂直切片的【真行情样本】定位 + 捆绑器。

陌生人靠对话走通 chat→backtest 的脊梁要求：agent 回测必须读**真 OHLCV** 跑出**真净值**
（§3 不假绿灯——绝不用合成假数据冒充回测）。但全仓 `data/` 里只有 run 输出（experiments/*），
没有原始行情。故这里捆**起步样本**（演示/起步、非全市场；真用户应在 onboarding 配自己数据源）：

  · BTC 日频  —— 复用 `binance_vision_pull` 的下载/解析【单一源原语】（公开·逐日 zip·零 token）。
  · 沪深300   —— 复用 `connectors.tushare_connector` 的 index_daily（需 `TUSHARE_TOKEN`，绝不伪造）。

落盘到 `DATA_ROOT/samples/<market>/<file>.csv`（**未被 .gitignore，可随仓提交**），统一 schema
`{timestamp(ISO Z), open, high, low, close, volume, symbol}`。沙箱经 `extra_env={DATA_DIR=DATA_ROOT}`
读 `{DATA_DIR}/samples/...`——故捆绑写路径与合成器读路径同源、确定。

注意：本模块**不复用** `binance_vision_pull.pull_vision_klines_date_range` 的逐日 reload-merge 路径
（该路径有预存 schema bug：reload 时 try_parse_dates 把 timestamp 读成 Datetime 与新 String 列 concat
报错）。改为复用其无状态原语（URL 构造 / 下载 / CSV→OHLCV 规整）后在内存累积一次性落盘，绕开该 bug。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from ..paths import DATA_ROOT

# market（emit_result.metadata.market 取值域）→ 样本相对路径（相对 DATA_DIR）。
# crypto_spot 与 crypto_perp 共用 BTC 现货级日 K（起步样本，永续资金费率不在样本内——诚实限界）。
SAMPLE_REL: dict[str, str] = {
    "crypto_perp": "samples/crypto/BTCUSDT_1d.csv",
    "crypto_spot": "samples/crypto/BTCUSDT_1d.csv",
    "stocks_cn": "samples/stocks_cn/000300_SH_1d.csv",
}

# 统一样本 schema（捆绑器产、合成器读）。
SAMPLE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "symbol"]

# 起步样本默认基准代码（emit_result.metadata.benchmark）。
SAMPLE_BENCHMARK: dict[str, str] = {
    "crypto_perp": "BTC-USDT",
    "crypto_spot": "BTC-USDT",
    "stocks_cn": "000300.SH",
}


def sample_path(market: str, *, data_root: Path | None = None) -> Path:
    """样本 CSV 的绝对路径（不保证存在；用 has_sample 判定）。"""
    root = Path(data_root) if data_root is not None else DATA_ROOT
    rel = SAMPLE_REL.get(market)
    if rel is None:
        raise KeyError(f"无样本映射的 market={market}（可选：{sorted(SAMPLE_REL)}）")
    return root / rel


def sample_rel(market: str) -> str:
    rel = SAMPLE_REL.get(market)
    if rel is None:
        raise KeyError(f"无样本映射的 market={market}（可选：{sorted(SAMPLE_REL)}）")
    return rel


def has_sample(market: str, *, data_root: Path | None = None) -> bool:
    try:
        p = sample_path(market, data_root=data_root)
    except KeyError:
        return False
    return p.exists() and p.stat().st_size > 0


# ----------------------------------------------------------------------------
# BTC 日频捆绑（复用 binance_vision_pull 无状态原语，内存累积一次性落盘）
# ----------------------------------------------------------------------------

def bundle_btc_daily(
    *,
    start: date,
    end: date,
    symbol: str = "BTCUSDT",
    data_root: Path | None = None,
    registry_key: str = "vision_klines",
    max_workers: int = 16,
) -> Path:
    """拉 [start, end] BTC 日 K（Binance Vision 公开·零 token），落统一样本 CSV，返回路径。

    默认 `vision_klines` = USDM 永续日 K（data/futures/um/daily/klines），贴 crypto_perp 样本语义。

    复用 `binance_vision_pull` 的 `_daily_zip_url` / `_download_zip` / `_read_first_csv_from_zip`
    / `_vision_kline_csv_to_ohlcv`（§1 单一源），不复用其 buggy reload-merge。
    并发下载（Vision 每请求 ~2s 延迟，顺序 730 天要半小时；16 worker 内存累积一次性落盘）。
    """

    from concurrent.futures import ThreadPoolExecutor

    from .. import binance_vision_pull as bv

    spec = bv.VISION_REGISTRY[registry_key]
    days = bv._daterange_inclusive(start, end)

    def _fetch_day(day):  # noqa: ANN001, ANN202
        url = bv._daily_zip_url(spec, symbol, "1d", day)
        try:
            raw = bv._download_zip(url)
        except FileNotFoundError:
            return None  # 该日无数据——跳过，不伪造
        except Exception:  # noqa: BLE001  网络抖动：跳过该日，不让整批失败
            return None
        ohlcv = bv._vision_kline_csv_to_ohlcv(bv._read_first_csv_from_zip(raw), symbol)
        if ohlcv.height:
            return ohlcv.select([c for c in SAMPLE_COLUMNS if c in ohlcv.columns])
        return None

    frames: list[pl.DataFrame] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for fr in pool.map(_fetch_day, days):
            if fr is not None:
                frames.append(fr)
    if not frames:
        raise RuntimeError(
            f"未拉到任何 BTC 日 K（symbol={symbol} {start}~{end}）——网络不可达或区间无数据；不落空样本"
        )
    merged = (
        pl.concat(frames, how="vertical")
        .unique(subset=["timestamp"], keep="last")
        .sort("timestamp")
    )
    return _write_sample(merged, "crypto_perp", data_root=data_root)


# ----------------------------------------------------------------------------
# 沪深300 日频捆绑（复用 TushareConnector，需 TUSHARE_TOKEN）
# ----------------------------------------------------------------------------

def bundle_hs300_daily(
    *,
    start: date,
    end: date,
    symbol: str = "000300.SH",
    data_root: Path | None = None,
    token: str | None = None,
) -> Path:
    """拉 [start, end] 沪深300 指数日 K（Tushare index_daily），落统一样本 CSV，返回路径。

    需 `TUSHARE_TOKEN`（env 或显式传 token）。无 token → 抛错（绝不伪造 A股样本，§3）。
    复用 `connectors.tushare_connector.TushareConnector`（§1 单一源），不另写 Tushare 客户端。
    """

    import os
    from datetime import datetime as _dt

    from ..connectors.base import FetchRequest
    from ..connectors.tushare_connector import TushareConnector

    tok = token or os.environ.get("TUSHARE_TOKEN", "")
    if not tok:
        raise RuntimeError(
            "TUSHARE_TOKEN 未配置——无法捆绑沪深300 真样本（A股样本绝不伪造）。"
            "设 TUSHARE_TOKEN 环境变量后重跑 bundle_hs300_daily。"
        )
    conn = TushareConnector(token=tok)
    req = FetchRequest(
        symbol=symbol,
        market="indices_cn",
        interval="1d",
        data_kind="index_daily",
        start=_dt(start.year, start.month, start.day),
        end=_dt(end.year, end.month, end.day),
    )
    res = conn.fetch(req)
    df = res.frame if hasattr(res, "frame") else res.data  # FetchResult 兼容字段
    if df is None or df.height == 0:
        raise RuntimeError(f"Tushare index_daily 空返回（{symbol} {start}~{end}）——不落空样本")
    norm = _normalize_index_daily(df, symbol)
    return _write_sample(norm, "stocks_cn", data_root=data_root)


def _normalize_index_daily(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """TushareConnector index_daily 宽表 → 统一样本 schema（ts→ISO Z timestamp）。"""

    out = df
    # ts 列（连接器已把 trade_date 改名 ts 并转 UTC datetime）→ ISO Z 字符串
    if "ts" in out.columns:
        out = out.with_columns(
            pl.col("ts").dt.strftime("%Y-%m-%dT00:00:00Z").alias("timestamp")
        )
    elif "timestamp" not in out.columns:
        raise RuntimeError("index_daily 返回缺时间列（ts/timestamp）")
    keep = {c: c for c in ("open", "high", "low", "close")}
    # 成交量：vol→volume（连接器价格类已 rename，但指数接口列名兜底）
    if "volume" not in out.columns and "vol" in out.columns:
        out = out.rename({"vol": "volume"})
    cols = ["timestamp"] + [c for c in ("open", "high", "low", "close", "volume") if c in out.columns]
    out = out.select(cols).with_columns(pl.lit(symbol).alias("symbol"))
    return out.unique(subset=["timestamp"], keep="last").sort("timestamp")


def _write_sample(df: pl.DataFrame, market: str, *, data_root: Path | None) -> Path:
    path = sample_path(market, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 只保留统一列（缺列容忍，但 timestamp/close 必须在）
    have = [c for c in SAMPLE_COLUMNS if c in df.columns]
    if "timestamp" not in have or "close" not in have:
        raise RuntimeError(f"样本缺必需列 timestamp/close（现有 {df.columns}）")
    df.select(have).write_csv(path)
    return path


__all__ = [
    "SAMPLE_REL",
    "SAMPLE_COLUMNS",
    "SAMPLE_BENCHMARK",
    "sample_path",
    "sample_rel",
    "has_sample",
    "bundle_btc_daily",
    "bundle_hs300_daily",
]
