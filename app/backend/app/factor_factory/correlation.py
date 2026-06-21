"""F2 · 因子拥挤度 / 去冗余：多因子 Spearman 截面相关矩阵 + 冗余对识别。

为什么 Spearman（rank）而非 Pearson：因子台关心的是【排序一致性】（两个因子是否在
选股上殊途同归），不是线性关系强弱。Rank 相关对单调非线性变换不变、对离群值稳健，是
因子拥挤度的行业标准口径（Grinold-Kahn）。

诚实边界：
- 相关矩阵在截面上逐期算 Spearman、再跨期平均（与 IC 的截面口径一致），不是把整条面板
  拉平后算一次（那会把时间维和截面维混为一谈，虚高相关）。
- 「冗余」只是阈值判断（|ρ| ≥ threshold），不对「该删哪个」下结论——删因子是研究决策，
  本层只摆证据（哪些对高度同质），不替用户拍板。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import polars as pl

from .panel_source import factor_panel


@dataclass
class CorrPair:
    a: str
    b: str
    spearman: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CorrelationReport:
    factor_ids: list[str]
    matrix: list[list[float]]          # 对称方阵，对角线 1.0
    redundant_pairs: list[CorrPair]    # |ρ| ≥ threshold 的对（按 |ρ| 降序）
    threshold: float
    sample_count: int                  # 参与平均的有效截面期数
    note: str

    def to_dict(self) -> dict:
        return {
            "factor_ids": self.factor_ids,
            "matrix": self.matrix,
            "redundant_pairs": [p.to_dict() for p in self.redundant_pairs],
            "threshold": self.threshold,
            "sample_count": self.sample_count,
            "note": self.note,
        }


class CorrelationError(ValueError):
    """相关矩阵口径违规（因子不足 2 个 / 对齐后无共同截面）。"""


_NOTE = (
    "Spearman 截面相关逐期算后跨期平均（与 IC 截面口径一致）；|ρ|≥阈值=高度同质（拥挤），"
    "但「删哪个」是研究决策、本表只摆证据不替你拍板。"
)


def _aligned_factor_columns(
    market: str,
    factors: list[tuple[str, str]],
) -> tuple[pl.DataFrame, list[str]]:
    """把多个 (factor_id, formula) 各自算成因子值，按 (ts, symbol) 内连接对齐成宽表。

    返回 (宽表[ts, symbol, f0, f1, ...], 有效列名顺序)。任一因子算不出列则跳过。
    """

    wide: pl.DataFrame | None = None
    cols: list[str] = []
    for fid, formula in factors:
        col = f"f::{fid}"
        try:
            fp = factor_panel(market, formula, factor_alias=col)
        except Exception:  # noqa: BLE001  单因子编译失败不应整体崩，跳过该因子
            continue
        sub = fp.select(["ts", "symbol", col])
        wide = sub if wide is None else wide.join(sub, on=["ts", "symbol"], how="inner")
        cols.append(col)
    if wide is None:
        wide = pl.DataFrame({"ts": [], "symbol": []})
    return wide, cols


def _cross_sectional_spearman(wide: pl.DataFrame, col_a: str, col_b: str) -> tuple[float, int]:
    """逐截面（按 ts）算 a,b 的 Spearman，再跨期平均。返回 (mean_rho, n_periods)。"""

    df = wide.select(["ts", col_a, col_b]).drop_nulls()
    if df.is_empty():
        return (float("nan"), 0)
    by_ts = (
        df.group_by("ts")
        .agg(
            pl.corr(pl.col(col_a).rank(), pl.col(col_b).rank()).alias("rho"),
            pl.len().alias("n"),
        )
        .filter(pl.col("n") >= 2)
    )
    rho = by_ts.get_column("rho").drop_nulls()
    if rho.len() == 0:
        return (float("nan"), 0)
    return (float(rho.mean()), int(rho.len()))


def correlation_matrix(
    market: str,
    factors: list[tuple[str, str]],
    *,
    threshold: float = 0.8,
) -> CorrelationReport:
    """多因子拥挤度矩阵。

    Args:
        market: equity_cn / crypto（panel_source 取复权 panel）。
        factors: [(factor_id, formula), ...]，至少 2 个。
        threshold: |ρ| ≥ threshold 判为冗余对（默认 0.8，可调）。
    """

    if len(factors) < 2:
        raise CorrelationError("相关矩阵至少需要 2 个因子")
    wide, cols = _aligned_factor_columns(market, factors)
    if len(cols) < 2:
        raise CorrelationError("有效因子不足 2 个（编译失败或无共同截面）")
    # col → 展示用 factor_id
    fid_of = {f"f::{fid}": fid for fid, _ in factors}
    factor_ids = [fid_of[c] for c in cols]
    n = len(cols)
    matrix = [[0.0] * n for _ in range(n)]
    pairs: list[CorrPair] = []
    max_periods = 0
    for i in range(n):
        matrix[i][i] = 1.0
        for j in range(i + 1, n):
            rho, periods = _cross_sectional_spearman(wide, cols[i], cols[j])
            max_periods = max(max_periods, periods)
            val = 0.0 if rho != rho else round(rho, 6)  # NaN→0
            matrix[i][j] = val
            matrix[j][i] = val
            if rho == rho and abs(rho) >= threshold:
                pairs.append(CorrPair(a=factor_ids[i], b=factor_ids[j], spearman=val))
    pairs.sort(key=lambda p: abs(p.spearman), reverse=True)
    return CorrelationReport(
        factor_ids=factor_ids,
        matrix=matrix,
        redundant_pairs=pairs,
        threshold=threshold,
        sample_count=max_periods,
        note=_NOTE,
    )


__all__ = ["CorrPair", "CorrelationError", "CorrelationReport", "correlation_matrix"]
