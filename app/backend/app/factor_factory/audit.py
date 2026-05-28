"""v0.9.7 学术 audit (patch1 §G.a #5) · 因子 AST shift-invariance 检测器。

学术依据: López de Prado 2018 §3.5 / Kakushadze 2016 Alpha101

漏洞: polars `over()` 默认中心化、pandas `rolling().mean(center=True)` 等会引入
       未来函数 (lookahead bias)，让 IC 看起来很高但实盘必崩。

修复: shift-invariance contract:
  对任意 ts_op(x, w) 算子，
  ts_op(x ++ future, w)[:len(x)] 必须 == ts_op(x, w)

也就是说: 后追加 future 值不能改 历史输出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import polars as pl


@dataclass
class ShiftInvarianceResult:
    op_name: str
    passed: bool
    max_diff: float
    diff_at_index: int | None
    detail: str


def assert_shift_invariant(
    op_fn: Callable[[Any, int], Any],
    op_name: str,
    *,
    window: int = 5,
    series_length: int = 50,
    future_length: int = 20,
    atol: float = 1e-8,
    series_factory: Callable[[int], Any] | None = None,
) -> ShiftInvarianceResult:
    """对一个 ts_/cs_ 算子做 shift-invariance contract test。

    流程:
      1. 构造 series_short (len=N) + series_long (len=N+M, 后追加 future)
      2. 计算 op(series_short, window) 和 op(series_long, window)[:N]
      3. element-wise diff，max(|diff|) < atol → pass

    series_factory: 默认用 np.arange (单调) 让 lookahead 一旦发生立刻被放大
    """
    rng = np.random.default_rng(42)

    def default_factory(n: int) -> np.ndarray:
        # 单调递增基础 + 小噪声让 op 算结果非平凡
        return np.arange(n, dtype=float) + rng.standard_normal(n) * 0.1

    factory = series_factory or default_factory
    series_short = factory(series_length)
    future = factory(future_length) + series_length  # 让 future 明显偏离
    if isinstance(series_short, np.ndarray):
        series_long = np.concatenate([series_short, future])
    elif isinstance(series_short, pl.Series):
        series_long = pl.concat([series_short, pl.Series(future)])
    else:
        raise TypeError(f"Unsupported series type: {type(series_short)}")

    try:
        out_short = op_fn(series_short, window)
        out_long = op_fn(series_long, window)
    except Exception as exc:  # noqa: BLE001
        return ShiftInvarianceResult(
            op_name=op_name, passed=False, max_diff=float("nan"),
            diff_at_index=None, detail=f"op crashed: {exc}",
        )

    # 转 numpy 比较
    if isinstance(out_short, pl.Series):
        arr_short = out_short.to_numpy()
        arr_long = out_long.to_numpy()
    elif isinstance(out_short, np.ndarray):
        arr_short = out_short
        arr_long = np.asarray(out_long)
    else:
        try:
            arr_short = np.asarray(out_short)
            arr_long = np.asarray(out_long)
        except Exception:
            return ShiftInvarianceResult(
                op_name=op_name, passed=False, max_diff=float("nan"),
                diff_at_index=None, detail=f"unsupported output type {type(out_short)}",
            )

    if arr_short.shape[0] > arr_long.shape[0]:
        return ShiftInvarianceResult(
            op_name=op_name, passed=False, max_diff=float("nan"),
            diff_at_index=None, detail="op_long output 比 op_short 短，shape 错乱",
        )

    # 比较 long 的前 N 个 vs short 的全部
    n = arr_short.shape[0]
    sub = arr_long[:n]

    # NaN 兼容比较
    short_nan = np.isnan(arr_short.astype(float))
    long_nan = np.isnan(sub.astype(float))
    nan_diff = short_nan != long_nan
    if np.any(nan_diff):
        first_diff = int(np.argmax(nan_diff))
        return ShiftInvarianceResult(
            op_name=op_name, passed=False, max_diff=float("inf"),
            diff_at_index=first_diff,
            detail=f"NaN 位置不一致 (index {first_diff}): short={arr_short[first_diff]} long={sub[first_diff]}",
        )

    # 非 NaN 区域 numeric diff
    valid = ~short_nan
    if not np.any(valid):
        return ShiftInvarianceResult(
            op_name=op_name, passed=True, max_diff=0.0,
            diff_at_index=None, detail="all NaN, vacuous pass",
        )

    diff = np.abs(arr_short[valid] - sub[valid])
    max_diff = float(np.max(diff))
    if max_diff < atol:
        return ShiftInvarianceResult(
            op_name=op_name, passed=True, max_diff=max_diff,
            diff_at_index=None, detail="shift-invariance OK",
        )
    bad_idx = int(np.argmax(diff))
    # 映射回原 index
    real_idx = int(np.flatnonzero(valid)[bad_idx])
    return ShiftInvarianceResult(
        op_name=op_name, passed=False, max_diff=max_diff,
        diff_at_index=real_idx,
        detail=(
            f"LOOKAHEAD detected: short[{real_idx}]={arr_short[real_idx]:.6g} "
            f"vs long[{real_idx}]={sub[real_idx]:.6g}; 后追加 future 改变了历史输出，"
            f"算子 '{op_name}' 引入了未来函数 (e.g. center=True / over()无窗口约束)"
        ),
    )


__all__ = ["ShiftInvarianceResult", "assert_shift_invariant"]
