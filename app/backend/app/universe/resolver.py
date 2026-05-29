"""M2 · 资产池解析器（point-in-time，幸存者偏差安全）。

`resolve_universe` 解析单个 as-of 日的成分；`resolve_universe_series` 解析一串再平衡日，
每个日期只看截至当日的数据 → 成分随时间变化且不泄漏未来。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import polars as pl

from .definition import UniverseRules

# as_of 支持 date / datetime / ISO 字符串；int 不支持（epoch 含义不明确，见 _as_of_bound）。
AsOf = date | datetime | str

_NUMERIC_DTYPES = (
    pl.Int8, pl.Int16, pl.Int32, pl.Int64,
    pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
    pl.Float32, pl.Float64,
)
_TRUTHY_STR = ("y", "yes", "true", "t", "1", "st", "*st")


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


def _as_of_bound(as_of: AsOf, ts_dtype: pl.DataType) -> pl.Expr:
    """把 as_of 规整成与 ts 列 dtype 对齐、对当日含尾的上界表达式。

    - str → ISO 解析（date 或 datetime）；int/bool → 拒绝（epoch 含义不明确）。
    - Datetime 列 + 纯 date as_of → 抬到当日 23:59:59.999999，使 `<=` 含当日全部 bar
      （否则 date 被 polars 强转零点会丢掉 09:30/15:00 等当日 bar，破坏 point-in-time）。
    - tz-aware 列 → 给裸时刻附上同一时区。
    """

    val: Any = as_of
    if isinstance(val, bool):
        raise ValueError("as_of 不支持 bool 类型")
    if isinstance(val, str):
        s = val.strip()
        val = datetime.fromisoformat(s) if ("T" in s or " " in s) else date.fromisoformat(s)
    elif isinstance(val, int):
        raise ValueError("as_of 不支持 int（epoch 含义不明确）；请用 date/datetime 或 ISO 字符串")

    if isinstance(ts_dtype, pl.Datetime):
        bound = val if isinstance(val, datetime) else datetime.combine(val, time(23, 59, 59, 999999))
        expr = pl.lit(bound)
        if ts_dtype.time_zone is not None and bound.tzinfo is None:
            expr = expr.dt.replace_time_zone(ts_dtype.time_zone)
        return expr.cast(ts_dtype)

    # Date（或其它非 Datetime 时间列）：按 date 比较。
    if isinstance(val, datetime):
        val = val.date()
    return pl.lit(val)


def _st_is_flagged(col_name: str, dtype: pl.DataType | None) -> pl.Expr:
    """ST/风险警示真值判定，兼容 bool / 数值(≠0) / 字符串('Y'/'1'/'ST…'/'*ST…')。"""

    col = pl.col(col_name)
    if dtype == pl.Boolean:
        return col.fill_null(False)
    if dtype is not None and dtype in _NUMERIC_DTYPES:
        return col.cast(pl.Float64).fill_nan(0.0).fill_null(0.0) != 0.0
    s = col.cast(pl.Utf8).fill_null("").str.to_lowercase().str.strip_chars()
    return s.is_in(_TRUTHY_STR) | s.str.contains(r"^\*?st")


def _nan_to_null(stats: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """把浮点列里的 NaN 归一成 null（polars 里 NaN≠null，只判 null 的缺值防御会漏 NaN）。"""

    exprs = [
        pl.col(c).fill_nan(None).alias(c)
        for c in columns
        if c in stats.columns and stats.schema[c] in (pl.Float32, pl.Float64)
    ]
    return stats.with_columns(exprs) if exprs else stats


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
    df = panel.filter(pl.col(ts_col) <= _as_of_bound(as_of, panel.schema[ts_col]))
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
        # NaN→null：让下面的缺值防御（fill_null(-inf) 比较、nulls_last、rank 剔除）对 NaN 同样生效。
        stats = _nan_to_null(stats, ["rank_value", "avg_amount", "last_price"])

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
        # st_flag 为真 → 剔除；空值视为非 ST 保留。兼容 bool/数值/字符串编码。
        stats = _drop(~_st_is_flagged("st_flag", stats.schema.get("st_flag")), "st", stats)
    if rules.min_price is not None:
        stats = _drop(pl.col("last_price").fill_null(float("-inf")) >= rules.min_price, "price", stats)
    if rules.min_avg_amount is not None:
        stats = _drop(pl.col("avg_amount").fill_null(float("-inf")) >= rules.min_avg_amount, "amount", stats)

    # 排序取前 top_n。排序值缺失(null/NaN)的标的视为不可排序，剔除并计入 dropped['rank']，
    # 与价格/流动性的缺值剔除保持一致，避免脏数据标的靠 nulls_last 悄悄沉底进池。
    if rules.rank_by is not None:
        n_bad = stats.filter(pl.col("rank_value").is_null()).height
        if n_bad:
            dropped["rank"] = dropped.get("rank", 0) + n_bad
            stats = stats.filter(pl.col("rank_value").is_not_null())
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
