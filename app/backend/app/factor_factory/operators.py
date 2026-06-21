"""M4 · 白箱算子空间 (~40 个)。

设计：
- 所有算子都接受一个 panel DataFrame（必含列 `ts`, `symbol`）并返回 polars Expr。
- **时序算子** (`ts_*`)：在同一 symbol 内沿时间维度计算 → 用 `pl.Expr.over("symbol")`。
- **横截面算子** (`cs_*`)：在同一时间戳沿 symbol 维度计算 → `pl.Expr.over("ts")`。
- **二元算子** 直接落到 polars 自带运算符。

算子全部纯函数，没有副作用，便于表达式引擎按 AST 组合。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import polars as pl


# ----- 时序窗口算子 (over symbol) -----

def ts_lag(expr: pl.Expr, n: int) -> pl.Expr:
    return expr.shift(n).over("symbol")


def ts_delta(expr: pl.Expr, n: int) -> pl.Expr:
    return (expr - expr.shift(n)).over("symbol")


def ts_pct_change(expr: pl.Expr, n: int = 1) -> pl.Expr:
    return ((expr / expr.shift(n)) - 1).over("symbol")


def ts_sum(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_sum(window_size=window).over("symbol")


def ts_mean(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_mean(window_size=window).over("symbol")


def ts_std(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_std(window_size=window).over("symbol")


def ts_min(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_min(window_size=window).over("symbol")


def ts_max(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_max(window_size=window).over("symbol")


def ts_median(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_median(window_size=window).over("symbol")


def ts_argmax(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_map(lambda s: float(s.arg_max() or 0), window_size=window).over("symbol")


def ts_argmin(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_map(lambda s: float(s.arg_min() or 0), window_size=window).over("symbol")


def ts_rank(expr: pl.Expr, window: int) -> pl.Expr:
    """rolling 内的相对排名（0..1）"""
    return expr.rolling_map(
        lambda s: (s.rank().tail(1).item() - 1) / max(len(s) - 1, 1),
        window_size=window,
    ).over("symbol")


def ts_zscore(expr: pl.Expr, window: int) -> pl.Expr:
    mean = expr.rolling_mean(window_size=window)
    std = expr.rolling_std(window_size=window)
    return ((expr - mean) / std).over("symbol")


def ts_skew(expr: pl.Expr, window: int) -> pl.Expr:
    return expr.rolling_skew(window_size=window).over("symbol")


def ts_corr(x: pl.Expr, y: pl.Expr, window: int) -> pl.Expr:
    # 双输入 rolling 必须在每个 symbol 分区【内】沿时间窗口算，且按 ts 排序——
    # 否则 rolling 走物理行序（panel 未必按 (symbol,ts) 排）会跨 symbol 穿窗/乱序。
    # over(..., order_by="ts") 强制分区内时序滚动，杜绝跨界泄露与行序依赖。
    return pl.rolling_corr(x, y, window_size=window).over("symbol", order_by="ts")


def ts_cov(x: pl.Expr, y: pl.Expr, window: int) -> pl.Expr:
    return pl.rolling_cov(x, y, window_size=window).over("symbol", order_by="ts")


def ts_decay_linear(expr: pl.Expr, window: int) -> pl.Expr:
    """线性衰减加权平均：权重 [1,2,...,window] 归一化。"""
    weights = list(range(1, window + 1))
    return expr.rolling_mean(window_size=window, weights=weights).over("symbol")


def ts_ema(expr: pl.Expr, half_life: int) -> pl.Expr:
    return expr.ewm_mean(half_life=half_life).over("symbol")


# ----- 横截面算子 (over ts) -----

def cs_rank(expr: pl.Expr) -> pl.Expr:
    """归一化截面排名到 [0, 1]。"""
    ranked = expr.rank("ordinal").over("ts").cast(pl.Float64)
    n = pl.len().over("ts").cast(pl.Float64)
    return (ranked - 1) / (n - 1).clip(lower_bound=1.0)


def cs_zscore(expr: pl.Expr) -> pl.Expr:
    mean = expr.mean().over("ts")
    std = expr.std().over("ts")
    return (expr - mean) / std


def cs_demean(expr: pl.Expr) -> pl.Expr:
    return (expr - expr.mean().over("ts"))


def cs_winsorize(expr: pl.Expr, q: float = 0.025) -> pl.Expr:
    lo = expr.quantile(q).over("ts")
    hi = expr.quantile(1 - q).over("ts")
    return expr.clip(lower_bound=lo, upper_bound=hi)


def cs_quantile(expr: pl.Expr, q: float) -> pl.Expr:
    return expr.quantile(q).over("ts")


# ----- 简单一元算子 -----

def op_log(expr: pl.Expr) -> pl.Expr:
    return expr.log()


def op_log1p(expr: pl.Expr) -> pl.Expr:
    return expr.log1p()


def op_exp(expr: pl.Expr) -> pl.Expr:
    return expr.exp()


def op_abs(expr: pl.Expr) -> pl.Expr:
    return expr.abs()


def op_sign(expr: pl.Expr) -> pl.Expr:
    return expr.sign()


def op_neg(expr: pl.Expr) -> pl.Expr:
    return -expr


def op_sqrt(expr: pl.Expr) -> pl.Expr:
    return expr.sqrt()


def op_pow(expr: pl.Expr, n: float) -> pl.Expr:
    return expr.pow(n)


def op_clip(expr: pl.Expr, lo: float, hi: float) -> pl.Expr:
    return expr.clip(lower_bound=lo, upper_bound=hi)


# ----- 二元 + 工具 -----

def op_add(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return a + b


def op_sub(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return a - b


def op_mul(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return a * b


def op_div(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return a / b


def op_max(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return pl.max_horizontal(a, b)


def op_min(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    return pl.min_horizontal(a, b)


# ----- 注册表 -----

OPERATOR_REGISTRY: dict[str, Callable[..., pl.Expr]] = {
    # ts_*
    "ts_lag": ts_lag,
    "lag": ts_lag,
    "ts_delta": ts_delta,
    "delta": ts_delta,
    "ts_pct_change": ts_pct_change,
    "ts_sum": ts_sum,
    "ts_mean": ts_mean,
    "ts_std": ts_std,
    "ts_min": ts_min,
    "ts_max": ts_max,
    "ts_median": ts_median,
    "ts_argmax": ts_argmax,
    "ts_argmin": ts_argmin,
    "ts_rank": ts_rank,
    "ts_zscore": ts_zscore,
    "ts_skew": ts_skew,
    "ts_corr": ts_corr,
    "ts_cov": ts_cov,
    "ts_decay_linear": ts_decay_linear,
    "decay_linear": ts_decay_linear,
    "ts_ema": ts_ema,
    "ema": ts_ema,
    # cs_*
    "cs_rank": cs_rank,
    "rank": cs_rank,
    "cs_zscore": cs_zscore,
    "zscore": cs_zscore,
    "cs_demean": cs_demean,
    "cs_winsorize": cs_winsorize,
    "cs_quantile": cs_quantile,
    # 一元
    "log": op_log,
    "log1p": op_log1p,
    "exp": op_exp,
    "abs": op_abs,
    "sign": op_sign,
    "neg": op_neg,
    "sqrt": op_sqrt,
    "pow": op_pow,
    "clip": op_clip,
    # 二元
    "add": op_add,
    "sub": op_sub,
    "mul": op_mul,
    "div": op_div,
    "max": op_max,
    "min": op_min,
}


def list_operators() -> list[dict[str, Any]]:
    return [{"name": name, "arity": _arity(name)} for name in sorted(OPERATOR_REGISTRY)]


def _arity(name: str) -> int:
    import inspect

    fn = OPERATOR_REGISTRY[name]
    sig = inspect.signature(fn)
    return len([p for p in sig.parameters.values() if p.default is inspect.Parameter.empty])


__all__ = ["OPERATOR_REGISTRY", "list_operators"]
