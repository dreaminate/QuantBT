"""F2 · 因子注册前置三检查门（编译 / 前视 / 无重名）。

红线（决策卡 ①）：POST /api/factors 注册一个因子绝不裸写 registry——必经本门：
  1. 编译门：表达式能编译成合法 polars Expr（语法 + 列名 + 算子已注册）。
  2. 前视门（look-ahead）：在 panel 后追加 future 行后，历史输出不得改变。这是因子级
     shift-invariance contract（audit.assert_shift_invariant 的整公式版）——任何 center=True
     / 无窗口 over() / 显式 shift(负) 引入未来函数立刻被抓。
  3. 无重名门：同 factor_id 已存在即拒（除非显式 overwrite=True 升版本）。
通过后由 LifecycleManager 侧的 registry.register() 落库（初始 NEW），事件可经 evaluate 触发迁移。

诚实边界：前视门用合成 panel（多 symbol 单调价 + 噪声）做对抗，能抓住「后追加 future 改历史」
这一类穿越；它不保证因子在真实数据上无任何泄露（语义级泄露如用了未来才知道的列需契约门管），
只钉死「时间方向」这一刀。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from .expression import ExpressionError, compile_expression, evaluate_on_panel
from .registry import FactorRegistry


@dataclass
class RegisterCheckResult:
    compiled: bool
    no_lookahead: bool
    name_available: bool
    detail: str

    @property
    def ok(self) -> bool:
        return self.compiled and self.no_lookahead and self.name_available


class RegisterGateError(ValueError):
    """注册三检查门拦截（编译失败 / 前视 / 重名）。携带哪一刀挡的。"""

    def __init__(self, message: str, *, gate: str) -> None:
        super().__init__(message)
        self.gate = gate


_REQUIRED_BASE_COLS = ("open", "high", "low", "close", "volume")


def _synthetic_panel(n_ts: int, symbols: tuple[str, ...] = ("A", "B", "C")) -> pl.DataFrame:
    """构造对抗用合成 panel：每 symbol 单调递增价 + 小噪声，让前视一旦发生立即放大。

    红线：同 seed 下，n_ts 越大其前 k 行必须与小 panel 完全一致（每 symbol 用确定性
    per-(symbol, t) 噪声，不靠 RNG 抽取顺序）——否则 short/long 历史不一致会把因果算子误判前视。
    """

    rng = np.random.default_rng(7)
    rows: list[dict] = []
    for si, s in enumerate(symbols):
        # per-(symbol, t) 确定性噪声：与 n_ts 无关，保证前缀一致。
        sym_rng = np.random.default_rng(1000 + si)
        noise = sym_rng.standard_normal(n_ts) * 0.5
        vol_noise = sym_rng.standard_normal(n_ts) * 5
        for t in range(n_ts):
            c = float(t + 100.0 + noise[t])
            rows.append({
                "ts": t, "symbol": s,
                "open": c, "high": c + 0.3, "low": c - 0.3,
                "close": c, "volume": float(1000.0 + t + vol_noise[t]),
            })
    _ = rng  # 保留以防未来扩展；当前用 per-symbol 确定性流
    return pl.DataFrame(rows).sort(["symbol", "ts"])


def _eval_factor_col(panel: pl.DataFrame, formula: str) -> pl.DataFrame:
    """评估公式 → 返回含 (ts, symbol, factor_value) 的 DF（排序固定，便于对齐比较）。"""

    feat = evaluate_on_panel(panel, formula, alias="factor_value")
    return feat.sort(["symbol", "ts"])


def check_no_lookahead(formula: str, *, n_ts: int = 60, future_len: int = 25, atol: float = 1e-8) -> tuple[bool, str]:
    """因子级前视门：panel 后追加 future_len 行 → 历史 [0, n_ts) 的因子值不得变。"""

    short = _synthetic_panel(n_ts)
    # 在每个 symbol 末尾追加 future 行（ts 接续、价更高，明显偏离）。
    long = _synthetic_panel(n_ts + future_len)
    try:
        out_short = _eval_factor_col(short, formula)
        out_long = _eval_factor_col(long, formula)
    except ExpressionError as exc:
        return False, f"前视门：公式评估崩溃 {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"前视门：公式评估异常 {exc}"

    # 对每个 symbol 比较 long 的前 n_ts 行 vs short 的全部。
    for sym in short.select("symbol").unique().to_series().to_list():
        a = out_short.filter(pl.col("symbol") == sym).get_column("factor_value").to_numpy()
        b_full = out_long.filter(pl.col("symbol") == sym).get_column("factor_value").to_numpy()
        b = b_full[: len(a)]
        if len(a) == 0:
            continue
        a_nan = np.isnan(a.astype(float))
        b_nan = np.isnan(b.astype(float))
        if np.any(a_nan != b_nan):
            idx = int(np.argmax(a_nan != b_nan))
            return False, (
                f"前视门：symbol={sym} index={idx} NaN 位置因追加 future 而变——"
                f"公式引入了未来函数（look-ahead）"
            )
        valid = ~a_nan
        if not np.any(valid):
            continue
        diff = np.abs(a[valid] - b[valid])
        md = float(np.max(diff))
        if md >= atol:
            bad = int(np.flatnonzero(valid)[int(np.argmax(diff))])
            return False, (
                f"前视门：symbol={sym} index={bad} 历史输出因追加 future 改变 "
                f"(|Δ|={md:.3g})——公式引入了未来函数（center=True/负 shift/无窗 over）"
            )
    return True, "前视门：shift-invariance 通过（追加 future 不改历史）"


def precheck_register(
    registry: FactorRegistry,
    factor_id: str,
    formula: str,
    *,
    overwrite: bool = False,
) -> RegisterCheckResult:
    """注册前三检查（编译 / 前视 / 无重名）。任一失败 raise RegisterGateError（携 gate 名）。"""

    fid = (factor_id or "").strip()
    if not fid:
        raise RegisterGateError("factor_id 不能为空", gate="name")

    # 1. 无重名门（先查，编译/前视较贵）。
    name_available = True
    try:
        registry.get(fid)
        name_available = False
    except KeyError:
        name_available = True
    if not name_available and not overwrite:
        raise RegisterGateError(
            f"重名门：factor_id={fid!r} 已注册（升版本请显式 overwrite=True）", gate="name"
        )

    # 2. 编译门。
    try:
        compile_expression(formula)
    except ExpressionError as exc:
        raise RegisterGateError(f"编译门：{exc}", gate="compile") from exc
    except Exception as exc:  # noqa: BLE001
        raise RegisterGateError(f"编译门：表达式无法编译 {exc}", gate="compile") from exc

    # 3. 前视门。
    no_la, detail = check_no_lookahead(formula)
    if not no_la:
        raise RegisterGateError(detail, gate="lookahead")

    return RegisterCheckResult(
        compiled=True, no_lookahead=True, name_available=name_available,
        detail=detail,
    )


__all__ = [
    "RegisterCheckResult",
    "RegisterGateError",
    "check_no_lookahead",
    "precheck_register",
]
