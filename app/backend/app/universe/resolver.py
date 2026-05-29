"""M2 · 资产池解析器（point-in-time，幸存者偏差安全）。

`resolve_universe` 解析单个 as-of 日的成分；`resolve_universe_series` 解析一串再平衡日，
每个日期只看截至当日的数据 → 成分随时间变化且不泄漏未来。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import polars as pl

from .definition import UniverseRules

AsOf = date | datetime | str | int


@dataclass(frozen=True)
class UniverseResult:
    """单个 as-of 日的解析结果。"""

    as_of: Any
    symbols: list[str]
    n_candidates: int
    n_selected: int
    dropped: dict[str, int]  # 各过滤环节顺序剔除的标的数（互斥，可累加）


def _require(panel: pl.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in panel.columns]
    if missing:
        raise ValueError(f"panel 缺少列 {missing}")


def resolve_universe(
    rules: UniverseRules,
    panel: pl.DataFrame,
    as_of: AsOf,
    *,
    ts_col: str = "ts",
    symbol_col: str = "symbol",
) -> UniverseResult:
    """按规则解析截至 `as_of` 的资产池成分。"""

    # 静态池：固定成分，仅减去排除项。
    if rules.static_symbols is not None:
        seen: set[str] = set()
        uniq: list[str] = []
        for s in rules.static_symbols:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        excl = set(rules.exclude_symbols)
        symbols = [s for s in uniq if s not in excl]
        dropped = {"excluded": len(uniq) - len(symbols)} if excl else {}
        return UniverseResult(
            as_of=as_of,
            symbols=symbols,
            n_candidates=len(uniq),
            n_selected=len(symbols),
            dropped=dropped,
        )

    _require(panel, [ts_col, symbol_col])
    df = panel.filter(pl.col(ts_col) <= as_of)
    n_candidates = df.select(pl.col(symbol_col).n_unique()).item() if df.height else 0
    if n_candidates == 0:
        return UniverseResult(as_of=as_of, symbols=[], n_candidates=0, n_selected=0, dropped={})

    # 全历史聚合：上市天数代理（bar 数）。
    stats = df.group_by(symbol_col).agg(n_obs=pl.len())

    # 近 lookback 窗口聚合：流动性/最新价/排序值/ST。
    window_exprs: list[pl.Expr] = []
    if rules.rank_by is not None:
        _require(df, [rules.rank_by])
        window_exprs.append(pl.col(rules.rank_by).last().alias("rank_value"))
    if rules.min_avg_amount is not None:
        _require(df, [rules.amount_col])
        window_exprs.append(pl.col(rules.amount_col).mean().alias("avg_amount"))
    if rules.min_price is not None:
        _require(df, [rules.price_col])
        window_exprs.append(pl.col(rules.price_col).last().alias("last_price"))
    if rules.st_col is not None:
        _require(df, [rules.st_col])
        window_exprs.append(pl.col(rules.st_col).last().alias("st_flag"))

    if window_exprs:
        tail = (
            df.sort([symbol_col, ts_col])
            .group_by(symbol_col, maintain_order=True)
            .tail(rules.lookback_days)
        )
        win = tail.group_by(symbol_col, maintain_order=True).agg(window_exprs)
        stats = stats.join(win, on=symbol_col, how="left")

    dropped: dict[str, int] = {}

    def _drop(mask_keep: pl.Expr, reason: str, frame: pl.DataFrame) -> pl.DataFrame:
        kept = frame.filter(mask_keep)
        removed = frame.height - kept.height
        if removed:
            dropped[reason] = dropped.get(reason, 0) + removed
        return kept

    # 顺序剔除（互斥计数）。
    if rules.exclude_symbols:
        stats = _drop(~pl.col(symbol_col).is_in(rules.exclude_symbols), "excluded", stats)
    if rules.min_history_days > 0:
        stats = _drop(pl.col("n_obs") >= rules.min_history_days, "history", stats)
    if rules.st_col is not None:
        # st_flag 为真 → 剔除；空值视为非 ST 保留。
        stats = _drop(~(pl.col("st_flag").fill_null(False).cast(pl.Boolean)), "st", stats)
    if rules.min_price is not None:
        stats = _drop(pl.col("last_price").fill_null(float("-inf")) >= rules.min_price, "price", stats)
    if rules.min_avg_amount is not None:
        stats = _drop(pl.col("avg_amount").fill_null(float("-inf")) >= rules.min_avg_amount, "amount", stats)

    # 排序取前 top_n。
    if rules.rank_by is not None:
        stats = stats.sort("rank_value", descending=True, nulls_last=True)
        if rules.top_n is not None and stats.height > rules.top_n:
            dropped["rank"] = dropped.get("rank", 0) + (stats.height - rules.top_n)
            stats = stats.head(rules.top_n)
        symbols = stats.get_column(symbol_col).to_list()
    else:
        symbols = sorted(stats.get_column(symbol_col).to_list())

    return UniverseResult(
        as_of=as_of,
        symbols=symbols,
        n_candidates=n_candidates,
        n_selected=len(symbols),
        dropped=dropped,
    )


def resolve_universe_series(
    rules: UniverseRules,
    panel: pl.DataFrame,
    dates: list[AsOf],
    *,
    ts_col: str = "ts",
    symbol_col: str = "symbol",
) -> dict[Any, list[str]]:
    """逐再平衡日解析成分（point-in-time）。返回 {as_of: symbols}。"""

    out: dict[Any, list[str]] = {}
    for as_of in dates:
        out[as_of] = resolve_universe(
            rules, panel, as_of, ts_col=ts_col, symbol_col=symbol_col
        ).symbols
    return out
