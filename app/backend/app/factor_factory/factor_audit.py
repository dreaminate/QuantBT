"""F2 · 因子 alpha 审查方法学组装层（决策 D-F2-AUDIT「全采纳 + 数值可调」）。

把 app/eval 既有原语【组装】成一份多证据三角的因子审查（绝不重写原语）：
  - cscv_pbo            过拟合概率（PBO）
  - deflated_sharpe_ratio  诚实-N 通缩后的 Sharpe 显著性（DSR）
  - n_eff_from_matrix   收益相关聚类的有效独立试验数（N_eff 区间）
  - bootstrap_sharpe_ci moving-block Sharpe 置信区间
  - ic.compute_ic_report  IC（已纳 Newey-West HAC t，重叠窗口自相关调整）

裁决（D-F2-AUDIT c）：多证据三角，绝不单点——
  - 全部达标            → consistent（证据一致）
  - 任一不达标          → concern（证据存疑）
  - 多个严重不达标       → blocked（证据不一致）
文案（D-F2-AUDIT d）：一律走 verification.Verifier._verdict_note（措辞守门单一源），
禁 R7 词（可信 / 安全 / 排除过拟合 / 保证 / 可复现）。

honest-N 三档阈值（D-F2-AUDIT a，§0.1 研究侧旋钮——可调不锁）：
  谨慎 strict / 标准 standard / 宽松 lenient；标准档=DSR 诚实 N_eff 通缩后 t>3（文献默认）。
  调用方可经 query/body 传 overrides 覆盖单档阈值，但：
    (1) 覆盖值计入裁决披露（显示「阈值被调到 X」+ 通缩后真相），不静默放水；
    (2) 防呆 guardrail 挡离谱值（dsr 必 ∈[0,1]、pbo 阈 ∈[0,1]、t 阈 ≥0）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
import polars as pl

from ..eval.bootstrap import bootstrap_sharpe_ci
from ..eval.dsr import deflated_sharpe_ratio, sharpe_ratio
from ..eval.n_eff import n_eff_from_matrix
from ..eval.pbo import cscv_pbo
from ..verification.schema import Independence
from ..verification.verifier import Verifier
from .ic import attach_forward_returns, compute_ic_report
from .panel_source import factor_panel

Tier = Literal["strict", "standard", "lenient"]

# 三档诚实-N 阈值（文献默认值，Bailey-López de Prado DSR / Harvey-Liu-Zhu t>3）。
# 数值可调（D-F2-AUDIT §0.1）：调用方覆盖单字段，其余取该档默认。
DEFAULT_THRESHOLDS: dict[Tier, dict[str, float]] = {
    # 谨慎：最高门槛，最不容易给 consistent。
    "strict": {"min_dsr": 0.95, "max_pbo": 0.20, "min_ic_t": 3.5, "min_n_eff": 5},
    # 标准（文献默认）：DSR 诚实 N_eff 通缩后 t>3。
    "standard": {"min_dsr": 0.90, "max_pbo": 0.50, "min_ic_t": 3.0, "min_n_eff": 3},
    # 宽松：探索期放松，但仍非「无门槛」。
    "lenient": {"min_dsr": 0.80, "max_pbo": 0.70, "min_ic_t": 2.0, "min_n_eff": 2},
}

# 防呆区间：覆盖值越界即夹回 + 披露（不让研究侧旋钮把门拧到无意义）。
_GUARDRAILS: dict[str, tuple[float, float]] = {
    "min_dsr": (0.0, 1.0),
    "max_pbo": (0.0, 1.0),
    "min_ic_t": (0.0, 10.0),
    "min_n_eff": (1.0, 1e6),
}


class FactorAuditError(ValueError):
    """因子审查输入口径违规（市场未知 / 公式编译失败 / 截面不足）。"""


@dataclass
class AuditCheck:
    """单条证据的达标判定（多证据三角的一条腿）。"""

    key: str
    value: float | None
    threshold: float
    passed: bool
    severe: bool          # 严重不达标（多个 severe → blocked）
    direction: str        # ">=" 或 "<="（value 该方向满足 threshold）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FactorAuditReport:
    factor_id: str
    market: str
    formula: str
    horizon: int
    tier: Tier
    thresholds: dict[str, float]
    thresholds_overridden: dict[str, float]   # 被调过的字段（披露用，空=全默认）
    # 各原语原始产物（结构化，前端可展开看真相）
    dsr: float
    pbo: dict[str, Any]
    n_eff: dict[str, Any]
    bootstrap_ci: dict[str, Any]
    ic: dict[str, Any]
    sharpe: float
    n_trials: int
    checks: list[AuditCheck]
    verdict: Literal["consistent", "concern", "blocked"]
    verdict_note: str
    disclosure: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "market": self.market,
            "formula": self.formula,
            "horizon": self.horizon,
            "tier": self.tier,
            "thresholds": self.thresholds,
            "thresholds_overridden": self.thresholds_overridden,
            "dsr": self.dsr,
            "pbo": self.pbo,
            "n_eff": self.n_eff,
            "bootstrap_ci": self.bootstrap_ci,
            "ic": self.ic,
            "sharpe": self.sharpe,
            "n_trials": self.n_trials,
            "checks": [c.to_dict() for c in self.checks],
            "verdict": self.verdict,
            "verdict_note": self.verdict_note,
            "disclosure": self.disclosure,
        }


def resolve_thresholds(
    tier: Tier,
    overrides: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """取某档默认阈值 + 应用调用方覆盖（防呆夹值）。

    返回 (生效阈值, 实际被覆盖的字段)。被覆盖字段计入披露（显示调到了多少）。
    """

    if tier not in DEFAULT_THRESHOLDS:
        raise FactorAuditError(f"未知档位 tier={tier!r}（支持 {list(DEFAULT_THRESHOLDS)}）")
    effective = dict(DEFAULT_THRESHOLDS[tier])
    applied: dict[str, float] = {}
    for key, raw in (overrides or {}).items():
        if key not in effective:
            continue  # 未知阈值键忽略（不静默接受任意旋钮）
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        lo, hi = _GUARDRAILS[key]
        clamped = min(max(val, lo), hi)   # 防呆：越界夹回
        effective[key] = clamped
        applied[key] = clamped
    return effective, applied


def _quantile_portfolio_matrix(
    panel: pl.DataFrame,
    factor_col: str,
    fwd_col: str,
    n_quantiles: int,
) -> tuple[np.ndarray, list[float]]:
    """把因子构成的 N 个分位组合的逐期收益拼成 (T × N) 矩阵，供 PBO/N_eff。

    每列 = 一个分位组合的逐期截面等权 forward-return 序列（这 N 个组合就是「同因子的
    一族策略」——PBO 衡量在其中选 argmax 的 OOS 可靠性，正合「过拟合概率」语义）。
    第二个返回值 = 多空（QN−Q1）逐期收益序列，供 DSR / bootstrap 单序列原语。
    """

    df = panel.select(["ts", "symbol", factor_col, fwd_col]).drop_nulls()
    # 截面 breadth 不足请求分位数时下调（同 layered，避免空列污染 PBO/N_eff 矩阵）。
    min_breadth = int(
        df.group_by("ts").agg(pl.len().alias("n")).get_column("n").min() or 0
    )
    eff_q = min(n_quantiles, max(2, min_breadth)) if min_breadth >= 2 else 2
    binned = df.with_columns(
        (
            (
                (pl.col(factor_col).rank(method="ordinal").over("ts") - 1)
                * eff_q
                / pl.len().over("ts")
            )
            .floor()
            .clip(0, eff_q - 1)
            .cast(pl.Int64)
        ).alias("q")
    )
    # 每 (ts, q) 截面等权 → pivot 成 (ts × q) 宽表。
    by = (
        binned.group_by(["ts", "q"])
        .agg(pl.col(fwd_col).mean().alias("ret"))
        .sort("ts")
    )
    wide = by.pivot(values="ret", index="ts", on="q").sort("ts")
    q_cols = [c for c in wide.columns if c != "ts"]
    # 列名是 q 值（0..n-1），按数值序排，缺列填 0。
    ordered = sorted(q_cols, key=lambda c: int(c))
    mat = wide.select(ordered).fill_null(0.0).to_numpy()
    # 多空 = 最高分位列 − 最低分位列（逐期）。
    if mat.shape[1] >= 2:
        ls = (mat[:, -1] - mat[:, 0]).tolist()
    else:
        ls = mat[:, 0].tolist() if mat.shape[1] == 1 else []
    return mat, ls


def run_factor_audit(
    factor_id: str,
    market: str,
    formula: str,
    *,
    horizon: int = 5,
    n_quantiles: int = 5,
    tier: Tier = "standard",
    threshold_overrides: dict[str, float] | None = None,
    n_trials: int | None = None,
    generator_model: str = "factor_factory",
    checker_model: str = "factor_audit",
) -> FactorAuditReport:
    """组装一份多证据三角因子审查（不重写原语，只编排 + 裁决）。

    n_trials：诚实-N 试验数（喂 DSR 通缩）。None → 用 N_eff 点估计（收益相关聚类后的
    有效独立 N，而非名义计数——防等价改写撑大 N 后 DSR 通缩不足）。
    """

    effective, overridden = resolve_thresholds(tier, threshold_overrides)

    factor_col = "factor_value"
    try:
        fp = factor_panel(market, formula, horizon=horizon, factor_alias=factor_col)
    except Exception as exc:  # noqa: BLE001
        raise FactorAuditError(f"因子面板构建失败: {exc}") from exc
    fwd_col = f"forward_return_h{horizon}"
    panel = attach_forward_returns(fp, [horizon])

    # IC（已含 Newey-West HAC t）。
    ic_report = compute_ic_report(panel, factor_col, horizon=horizon)
    ic_dict = ic_report.to_dict()

    # 分位组合矩阵 → PBO / N_eff；多空序列 → DSR / bootstrap。
    matrix, ls_returns = _quantile_portfolio_matrix(panel, factor_col, fwd_col, n_quantiles)
    ls_arr = np.asarray(ls_returns, dtype=float)

    # N_eff：从分位组合矩阵聚类（这 N 列就是同因子的一族「试验」）。
    neff = n_eff_from_matrix(matrix)
    neff_dict = neff.to_dict()

    # 诚实-N：默认用 N_eff 点估计（≥1），可被显式 n_trials 覆盖。
    eff_n_trials = int(n_trials) if n_trials is not None else max(1, int(neff.point))

    # DSR：多空序列在诚实-N 下的显著性。var_sr_hat 用矩阵各列 per-period SR 的横截面方差
    # （False Strategy Theorem 的 V，比退化极值近似通缩更诚实）。
    var_sr_hat = _cross_sectional_sr_var(matrix)
    dsr = deflated_sharpe_ratio(ls_arr, n_trials=eff_n_trials, var_sr_hat=var_sr_hat)
    sharpe = sharpe_ratio(ls_arr)

    # bootstrap：moving-block 保留自相关（block ~ horizon）。
    boot = bootstrap_sharpe_ci(ls_arr, block_size=max(1, horizon))
    boot_dict = boot.to_dict()

    # PBO：分位组合族的过拟合概率（strict 关闭以容小样本合成 panel，但报真实结构）。
    pbo_res = cscv_pbo(matrix, s_blocks=8, max_combinations=200)
    pbo_dict = pbo_res.to_dict()

    # ── 多证据三角裁决（D-F2-AUDIT c）────────────────────────────────────
    ic_t = ic_dict.get("ic_tstat_nw")
    checks = _build_checks(
        dsr=dsr,
        pbo=pbo_res.pbo,
        ic_t=ic_t,
        n_eff_point=int(neff.point),
        thr=effective,
    )
    verdict = _verdict_from_checks(checks)
    note = _audit_note(verdict, checks)
    disclosure = _disclosure(tier, overridden, eff_n_trials, neff_dict, ic_dict)

    return FactorAuditReport(
        factor_id=factor_id,
        market=market,
        formula=formula,
        horizon=horizon,
        tier=tier,
        thresholds=effective,
        thresholds_overridden=overridden,
        dsr=round(float(dsr), 6),
        pbo=pbo_dict,
        n_eff=neff_dict,
        bootstrap_ci=boot_dict,
        ic=ic_dict,
        sharpe=round(float(sharpe), 6),
        n_trials=eff_n_trials,
        checks=checks,
        verdict=verdict,
        verdict_note=note,
        disclosure=disclosure,
    )


def _cross_sectional_sr_var(matrix: np.ndarray) -> float | None:
    """各列 per-period Sharpe 的横截面方差 V（False Strategy Theorem）。"""

    if matrix.ndim != 2 or matrix.shape[1] < 2:
        return None
    means = matrix.mean(axis=0)
    stds = matrix.std(axis=0, ddof=1)
    srs = np.divide(means, stds, out=np.zeros_like(means), where=stds > 1e-12)
    if srs.size < 2:
        return None
    v = float(np.var(srs, ddof=1))
    return v if v > 0 else None


def _build_checks(
    *,
    dsr: float,
    pbo: float,
    ic_t: float | None,
    n_eff_point: int,
    thr: dict[str, float],
) -> list[AuditCheck]:
    """逐证据建达标判定。「严重」= 该证据是过拟合核心信号（DSR/PBO/IC-t/N_eff 缺或反向）。"""

    checks: list[AuditCheck] = []

    # DSR ≥ 阈值（诚实-N 通缩后仍显著）。缺/低 = 严重。
    dsr_ok = dsr is not None and dsr == dsr and dsr >= thr["min_dsr"]
    checks.append(AuditCheck(
        key="dsr", value=None if dsr is None else round(float(dsr), 6),
        threshold=thr["min_dsr"], passed=bool(dsr_ok),
        severe=not dsr_ok, direction=">=",
    ))

    # PBO ≤ 阈值（过拟合概率不过高）。NaN（小样本算不出）→ 不达标且严重（不能当 pass）。
    pbo_valid = pbo == pbo  # not NaN
    pbo_ok = pbo_valid and pbo <= thr["max_pbo"]
    checks.append(AuditCheck(
        key="pbo", value=None if not pbo_valid else round(float(pbo), 6),
        threshold=thr["max_pbo"], passed=bool(pbo_ok),
        severe=not pbo_ok, direction="<=",
    ))

    # IC Newey-West t ≥ 阈值。None（样本不足）→ 不达标且严重（IC 显著性是核心证据）。
    ic_ok = ic_t is not None and ic_t == ic_t and abs(ic_t) >= thr["min_ic_t"]
    checks.append(AuditCheck(
        key="ic_tstat_nw", value=None if ic_t is None else round(float(ic_t), 6),
        threshold=thr["min_ic_t"], passed=bool(ic_ok),
        severe=not ic_ok, direction=">=",
    ))

    # N_eff ≥ 阈值（有效独立试验数够，DSR 通缩才有意义）。低 = 非严重（弱证据非核心反向）。
    neff_ok = n_eff_point >= thr["min_n_eff"]
    checks.append(AuditCheck(
        key="n_eff", value=float(n_eff_point),
        threshold=thr["min_n_eff"], passed=bool(neff_ok),
        severe=False, direction=">=",
    ))

    return checks


def _verdict_from_checks(checks: list[AuditCheck]) -> Literal["consistent", "concern", "blocked"]:
    """D-F2-AUDIT c：全达标 consistent / 任一不达标 concern / 多个严重不达标 blocked。"""

    failed = [c for c in checks if not c.passed]
    severe_failed = [c for c in failed if c.severe]
    if len(severe_failed) >= 2:
        return "blocked"
    if failed:
        return "concern"
    return "consistent"


def _audit_note(verdict: Literal["consistent", "concern", "blocked"], checks: list[AuditCheck]) -> str:
    """走 Verifier._verdict_note 单一措辞源（禁 R7 词）。

    把因子审查的不达标项映射成 verifier 的 ClaimCheck 形态（severe→mismatch=blocking，
    非 severe 未达标→unverified=concern 触发），让裁决文案与 verification 全局一致。
    """

    from ..verification.schema import ClaimCheck

    vchecks: list[ClaimCheck] = []
    for c in checks:
        if c.passed:
            status = "match"
        elif c.severe:
            status = "mismatch"   # 严重不达标 = 对账意义上的「不一致」
        else:
            status = "unverified"  # 弱证据缺失 = 「未能复算」→ concern
        vchecks.append(ClaimCheck(
            key=c.key, claimed=None, recomputed=c.value,
            abs_diff=None, within_tol=c.passed, status=status,
        ))
    # 因子审查是单主体「方法学三角」复核：独立性按非组织独立度量（异「方法」非异模型）。
    independence = Independence(
        model_differs=False, seed_differs=False, slice_differs=False,
        axes=0, established=False,
        note="因子审查为单主体多证据三角（DSR/PBO/IC-NW/N_eff 互证），非组织独立验证；"
             "结论只陈述证据一致/存疑/不一致 + 适用域 + 未验证项。",
    )
    return Verifier._verdict_note(verdict, vchecks, independence)  # noqa: SLF001  单一措辞源，刻意复用


def _disclosure(
    tier: Tier,
    overridden: dict[str, float],
    n_trials: int,
    neff_dict: dict[str, Any],
    ic_dict: dict[str, Any],
) -> str:
    parts = [
        f"档位={tier}；诚实-N 试验数 N={n_trials}（取 N_eff 点估计，"
        f"区间[{neff_dict.get('low')},{neff_dict.get('high')}]）；DSR 在此 N 下通缩。",
        f"IC 显著性用 Newey-West HAC t（lag={ic_dict.get('nw_lag')}），重叠 forward 窗口自相关已调整。",
    ]
    if overridden:
        kv = ", ".join(f"{k}→{v}" for k, v in overridden.items())
        parts.append(
            f"⚠ 阈值被研究侧调整（{kv}）：门槛随之变化、已计入裁决；调松不等于结论变好，"
            f"通缩后真相不变（见上 DSR/N_eff 原值）。"
        )
    else:
        parts.append("阈值取该档文献默认（未调整）。")
    # 措辞守门（R7）：本句刻意不写「可信/安全/保证/可复现/排除过拟合」字面词——
    # 只陈述「证据强度」，不对因子下任何定性背书。
    parts.append("本审查只陈述各项证据的强度与未达标项，不对因子本身下任何定性背书。")
    return " ".join(parts)


__all__ = [
    "DEFAULT_THRESHOLDS",
    "AuditCheck",
    "FactorAuditError",
    "FactorAuditReport",
    "Tier",
    "resolve_thresholds",
    "run_factor_audit",
]
