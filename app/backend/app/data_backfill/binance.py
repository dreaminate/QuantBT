"""Binance Vision 全量拉取 + zip 拼接管线（像 API 一样丝滑读）。

Vision 同时提供 monthly 与 daily zip：
- monthly：`.../{market}/monthly/{kind}/{SYM}/{interval}/{SYM}-{interval}-YYYY-MM.zip`（全历史首选，请求少）
- daily：  `.../{market}/daily/{kind}/{SYM}/{interval}/{SYM}-{interval}-YYYY-MM-DD.zip`（补当月/近几天）

stitch_klines：拉所有可用月 + 近月日 → 解压 → 按 open_time 去重排序 → 拼接成**连续 parquet** +
缺口检测；read_klines：统一读取，列名与 REST klines 对齐 → 上层无感，和 API 一样。

下载用 `fetch(url)->bytes|None`（404→None）注入，单测无需联网。
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

_BASE = "https://data.binance.vision/data"
_MARKET_PATH = {"um": "futures/um", "cm": "futures/cm", "spot": "spot"}

# REST /klines 同款 12 列
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count", "taker_buy_base", "taker_buy_quote", "ignore",
]

# interval → 毫秒（缺口检测）
_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000, "1w": 604_800_000,
}

Fetch = Callable[[str], bytes | None]


def _http_fetch(url: str) -> bytes | None:
    import requests

    resp = requests.get(url, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


def _monthly_url(market: str, kind: str, sym: str, interval: str, y: int, m: int) -> str:
    return f"{_BASE}/{_MARKET_PATH[market]}/monthly/{kind}/{sym}/{interval}/{sym}-{interval}-{y:04d}-{m:02d}.zip"


def _daily_url(market: str, kind: str, sym: str, interval: str, d: date) -> str:
    return f"{_BASE}/{_MARKET_PATH[market]}/daily/{kind}/{sym}/{interval}/{sym}-{interval}-{d.isoformat()}.zip"


def _parse_zip(raw: bytes) -> list[list[str]]:
    rows: list[list[str]] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            with zf.open(name) as fh:
                for r in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
                    # 跳过表头行（新版 Vision 月文件首行可能是列名）
                    if r and r[0].isdigit():
                        rows.append(r)
    return rows


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


@dataclass
class StitchResult:
    symbol: str
    interval: str
    market: str
    kind: str
    path: str | None
    rows: int
    gaps: int
    months_pulled: int
    days_pulled: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "interval": self.interval, "market": self.market, "kind": self.kind,
            "path": self.path, "rows": self.rows, "gaps": self.gaps,
            "months_pulled": self.months_pulled, "days_pulled": self.days_pulled,
        }


def stitch_klines(
    symbol: str,
    interval: str,
    *,
    market: str = "um",
    kind: str = "klines",
    start: date,
    end: date | None = None,
    data_root: Path,
    fetch: Fetch = _http_fetch,
    progress: Callable[[str], None] | None = None,
) -> StitchResult:
    """拉 [start, end] 全历史并拼接成连续 parquet。月 zip 打底 + 当月日 zip 收尾。"""
    sym = symbol.upper()
    end = end or datetime.now(timezone.utc).date()
    if market not in _MARKET_PATH:
        raise ValueError(f"market 必须 ∈ {sorted(_MARKET_PATH)}")

    rows: list[list[str]] = []
    months = 0
    days = 0
    # 1) 月 zip 覆盖到 end 的上个月
    last_full_month = (end.replace(day=1) - timedelta(days=1))
    for y, m in _month_iter(start.replace(day=1), last_full_month):
        raw = fetch(_monthly_url(market, kind, sym, interval, y, m))
        if raw is not None:
            rows.extend(_parse_zip(raw))
            months += 1
            if progress:
                progress(f"{sym} {interval} 月 {y}-{m:02d}")
    # 2) 当月日 zip 收尾：从 max(start, 当月1号) 起，避免拉早于 start 的天
    d = max(start, end.replace(day=1))
    while d <= end:
        raw = fetch(_daily_url(market, kind, sym, interval, d))
        if raw is not None:
            rows.extend(_parse_zip(raw))
            days += 1
        d += timedelta(days=1)

    if not rows:
        return StitchResult(sym, interval, market, kind, None, 0, 0, months, days)

    df = pd.DataFrame(rows, columns=KLINE_COLUMNS[: len(rows[0])])
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["open_time"]).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume", "quote_volume"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    step_ms = _INTERVAL_MS.get(interval)
    if step_ms is None:
        gaps = -1  # 未知 interval 间隔 → 无法判定缺口（不静默当 0 掩盖空洞）
        if progress:
            progress(f"{sym} {interval} 缺口检测跳过（未知间隔，gaps=-1）")
    else:
        gaps = _count_gaps(df["open_time"].astype("int64").tolist(), step_ms)

    out = data_root / "binance" / market / kind / sym
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{interval}.parquet"
    df.to_parquet(target)
    return StitchResult(sym, interval, market, kind, str(target), len(df), gaps, months, days)


def _count_gaps(open_times: list[int], step_ms: int) -> int:
    """统计相邻 open_time 间隔 > step_ms 的缺口数。step_ms<=0 视为不可判定 → -1。"""
    if step_ms <= 0:
        return -1
    if len(open_times) < 2:
        return 0
    return sum(1 for a, b in zip(open_times, open_times[1:]) if b - a > step_ms)


def read_klines(
    symbol: str, interval: str, *, market: str = "um", kind: str = "klines", data_root: Path
) -> pd.DataFrame:
    """像 API 一样读：返回拼好的连续 klines（不存在则空 DataFrame）。"""
    p = data_root / "binance" / market / kind / symbol.upper() / f"{interval}.parquet"
    if not p.exists():
        return pd.DataFrame(columns=KLINE_COLUMNS)
    return pd.read_parquet(p)


def list_symbols(market: str = "um", *, fetch_json: Callable[[str], Any] | None = None) -> list[str]:
    """全交易对（exchangeInfo）。fetch_json 可注入便于测试。"""
    urls = {
        "um": "https://fapi.binance.com/fapi/v1/exchangeInfo",
        "cm": "https://dapi.binance.com/dapi/v1/exchangeInfo",
        "spot": "https://api.binance.com/api/v3/exchangeInfo",
    }
    if fetch_json is None:
        import requests

        def fetch_json(u: str) -> Any:  # noqa: ANN001
            return requests.get(u, timeout=30).json()

    data = fetch_json(urls[market])
    return sorted(s["symbol"] for s in data.get("symbols", []) if s.get("status", "TRADING") in ("TRADING", None))


@dataclass
class BinanceBackfillPlan:
    market: str = "um"
    kind: str = "klines"
    intervals: tuple[str, ...] = ("1d", "1h")
    symbols: tuple[str, ...] = ()  # 空 = 全市场
    start: date = field(default_factory=lambda: date(2020, 1, 1))


def backfill_all_binance(
    plan: BinanceBackfillPlan,
    *,
    data_root: Path,
    fetch: Fetch = _http_fetch,
    fetch_json: Callable[[str], Any] | None = None,
    progress: Callable[[str], None] | None = None,
    skip_existing: bool = True,
) -> list[StitchResult]:
    """全量编排：全 symbol × interval 拼接。断点续传(skip_existing 跳过已存在 parquet)。"""
    symbols = list(plan.symbols) or list_symbols(plan.market, fetch_json=fetch_json)
    results: list[StitchResult] = []
    for sym in symbols:
        for interval in plan.intervals:
            target = data_root / "binance" / plan.market / plan.kind / sym.upper() / f"{interval}.parquet"
            if skip_existing and target.exists():
                if progress:
                    progress(f"skip {sym} {interval}（已存在）")
                continue
            results.append(
                stitch_klines(
                    sym, interval, market=plan.market, kind=plan.kind,
                    start=plan.start, data_root=data_root, fetch=fetch, progress=progress,
                )
            )
    return results


__all__ = [
    "KLINE_COLUMNS",
    "BinanceBackfillPlan",
    "StitchResult",
    "backfill_all_binance",
    "list_symbols",
    "read_klines",
    "stitch_klines",
]
