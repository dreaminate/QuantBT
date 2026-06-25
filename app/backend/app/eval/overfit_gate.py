"""多证据三角 gate（T-015）—— 把从不被调用的 DSR / PBO / Bootstrap 真正接进 run 闸门。

这是脊柱层2「真正落地的第一个活性证明」：M10 的三个守门器（`dsr.py`/`pbo.py`/`bootstrap.py`）
此前全仓零非测试调用、`risk_summary._rule_dsr/_rule_pbo` 永远拿 None 不触发。本模块把它们组装成
**多证据三角**（R2：三支同向才放行 + 通缩区间 + 一键下钻），由 promote 关卡注入 metrics → 守门器从
死接活。

R2/R5 铁律（刻进裁决）：
- **绝不单点裁决**：DSR / PBO / bootstrap CI 三支【同向正】才 green；任一【强负】red；分歧 yellow。
- **通缩区间非单点**：DSR 用 N_eff 的 [low, high] 各算一遍 → dsr_optimistic / dsr_conservative。
- **短样本判「证据不足」**：T < min_T 不给红绿、不输出会被误读为"修复后好夏普"的单点数字。
- **裁决永远说「证据充分/不足 + 适用域 + 未验证项」，绝不说「可信/安全/保证」**。
- **守门器自身模型风险固定披露**（`model_risk_disclosure`，不可关）。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np

from .bootstrap import bootstrap_sharpe_ci
from .dsr import deflated_sharpe_ratio
from .n_eff import NEffResult
from .pbo import cscv_pbo

GateColor = Literal["green", "yellow", "red", "insufficient_evidence"]

_MIN_T = {"a_share": 504, "equity_cn": 504}   # 其它（crypto）默认 252
_DEFAULT_MIN_T = 252
_PBO_MIN_STRATEGIES = 10
_PBO_S_BLOCKS = 8

# DSR 阈值（保守端 ≥ 此为正）、PBO 上限（≤ 此为正）。
_DSR_POS = 0.5
_DSR_STRONG_NEG = 0.2
_PBO_POS = 0.5
_PBO_STRONG_NEG = 0.7

_MODEL_RISK_DISCLOSURE = [
    "DSR 是显著性阈值的标度修正(studentize)，不是修复夏普被低估；它只与你诚实提交的 N 一样诚实。",
    "N_eff 用收益相关聚类估计，是启发式、对超参敏感、可被低报放水；这里报区间不报单点。",
    "N_observed 是真值下界：agent 单次推理内的隐式试验无法计入。",
    "本闸门只管统计显著性，未计交易成本/容量/拥挤；过闸 ≠ 会赚钱，regime 漂移才是中低频 OOS 失效主因。",
]


@dataclass
class GateVerdict:
    color: GateColor
    dsr_optimistic: float        # N_eff.low（少试验）→ 通缩不足端
    dsr_conservative: float      # N_eff.high（多试验）→ 通缩过度端
    pbo: float | None            # None = 策略数不足以做 PBO
    bootstrap_ci: tuple[float, float]
    bootstrap_method: str
    all_agree_positive: bool
    n_observed: int
    n_eff: dict
    var_sr_estimated: bool       # False → DSR 退化旧近似，通缩可能不足（须披露）
    reason: str
    verdict_phrasing: str
    model_risk_disclosure: list[str]
    # R4 CPCV 路径稳健性（report-only·正交于 PBO/DSR/CI 三角）：q05<无技能基线=过拟合/切分脆弱（advisory）。
    # None=未提供 CPCV 或样本不足。cpcv_conservative policy 下脆弱可 green→yellow（绝不硬 red，守 R2 单点不承重）。
    cpcv: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bootstrap_ci"] = [self.bootstrap_ci[0], self.bootstrap_ci[1]]
        return d


def _decide(
    dsr_cons: float, pbo: float | None, ci_lower: float, ci_upper: float,
    *, allow_pbo_absent_green: bool = False,
) -> tuple[GateColor, bool]:
    """纯裁决逻辑（R2 无单点承重）：三支【同向正】才 green；任一【强负】red；缺 PBO/分歧 yellow。

    抽成纯函数便于直测：把任一支异议（pbo 偏高 / ci 跨零 / dsr 不足）都必须能把 green 降级——
    任何「只看一支就放行」的实现都会在直测里露馅。

    `allow_pbo_absent_green`（**组合层 A2 · 用户 override R2 · D-WAVE1A**）：默认 False = 原语义
    （缺 PBO → 至多 yellow，单策略不变）。组合层冷启动（同主题历史<10 列、PBO 永不可达）传 True 时，
    PBO 缺席仍可凭 DSR 保守端 + Bootstrap CI **双正**放行（PBO 显式 N/A）。**仍受 strong_neg→red 兜底**：
    过拟合致 DSR<0.2 / CI 上界≤0 仍 red，绝不因放松而误绿（北极星不假绿灯由 strong_neg 守）。
    """

    dsr_ok = dsr_cons >= _DSR_POS
    ci_ok = ci_lower > 0
    pbo_ok = pbo is not None and pbo <= _PBO_POS
    strong_neg = (dsr_cons < _DSR_STRONG_NEG) or (ci_upper <= 0) or (pbo is not None and pbo > _PBO_STRONG_NEG)
    all_agree = bool(pbo_ok and dsr_ok and ci_ok)
    if strong_neg:
        return "red", all_agree
    if pbo is None:
        # A2 组合层 override：缺 PBO 但 DSR 保守端 + CI 双正 → 放行（PBO N/A，非完整三角，all_agree=False）。
        if allow_pbo_absent_green and dsr_ok and ci_ok:
            return "green", all_agree
        return "yellow", all_agree        # 默认：缺一支证据，构不成完整三角 → 不放行
    if all_agree:
        return "green", all_agree
    return "yellow", all_agree


def _auto_block(t: int) -> int:
    return max(1, int(round(math.sqrt(t))))


def _var_sr_hat(returns_matrix: np.ndarray | None) -> float | None:
    """试验间【每期】SR 的横截面方差 V（False Strategy Theorem）。<2 列 → 不可估。"""

    if returns_matrix is None:
        return None
    rm = np.asarray(returns_matrix, dtype=float)
    if rm.ndim != 2 or rm.shape[1] < 2:
        return None
    means = rm.mean(axis=0)
    stds = rm.std(axis=0, ddof=1)
    mask = stds > 1e-12
    if mask.sum() < 2:
        return None
    sr = means[mask] / stds[mask]
    v = float(np.var(sr, ddof=1))
    return v if math.isfinite(v) and v > 0 else None


def _insufficient(t: int, min_t: int, n_eff: NEffResult) -> GateVerdict:
    return GateVerdict(
        color="insufficient_evidence",
        dsr_optimistic=float("nan"), dsr_conservative=float("nan"),
        pbo=None, bootstrap_ci=(float("nan"), float("nan")), bootstrap_method="n/a",
        all_agree_positive=False, n_observed=n_eff.n_observed, n_eff=n_eff.to_dict(),
        var_sr_estimated=False,
        reason=f"样本不足（T={t} < 最低 {min_t}）：证据不足以判过拟合，不给红绿、不报会被误读的单点夏普。",
        verdict_phrasing="证据不足：样本期太短，无法对过拟合做有效裁决；适用域=无；未验证=全部。",
        model_risk_disclosure=list(_MODEL_RISK_DISCLOSURE),
    )


def run_overfit_gate(
    returns,
    *,
    n_eff: NEffResult,
    honest_n: int | None = None,
    returns_matrix: np.ndarray | None = None,
    asset_class: str = "crypto",
    periods_per_year: int = 252,
    allow_pbo_absent_green: bool = False,
    cpcv_distribution: dict | None = None,
    cpcv_policy: Literal["report_only", "cpcv_conservative"] = "report_only",
) -> GateVerdict:
    """多证据三角裁决。`returns`=本策略逐期净收益；`returns_matrix`=同主题历史试验矩阵（PBO 用）。

    `honest_n`=该主题名义 distinct config 计数（T-013 一本账）。**保守端通缩必须以 honest_n 兜底**
    （复核 #1/#4）：N_eff 聚类只在【乐观端】抵扣等价写法，**绝不让聚类把过闸决策用的通缩降到 1**
    ——否则矩阵拼不出来（首次 promote / 异长）时 N_eff=1、通缩归零，泄露策略直接过闸。
    """

    arr = np.asarray(returns, dtype=float)
    t = arr.size
    min_t = _MIN_T.get(asset_class, _DEFAULT_MIN_T)
    if t < min_t:
        return _insufficient(t, min_t, n_eff)

    var = _var_sr_hat(returns_matrix)
    n_floor = honest_n if (honest_n is not None and honest_n > 0) else n_eff.n_observed
    # 保守端（过闸决策用）：名义计数兜底，聚类信用不抵扣 → 非 gameable。
    n_high = max(1, n_eff.high, n_floor)
    # 乐观端（仅展示/区间）：给聚类信用（等价写法折叠）。
    n_low = max(1, n_eff.low)
    dsr_opt = deflated_sharpe_ratio(arr, n_trials=n_low, periods_per_year=periods_per_year, var_sr_hat=var)
    dsr_cons = deflated_sharpe_ratio(arr, n_trials=n_high, periods_per_year=periods_per_year, var_sr_hat=var)

    # PBO：需 ≥ min_n_strategies 列且行足够。不足 → None（无法形成完整三角 → 至多 yellow）。
    pbo: float | None = None
    if returns_matrix is not None:
        rm = np.asarray(returns_matrix, dtype=float)
        if rm.ndim == 2 and rm.shape[1] >= _PBO_MIN_STRATEGIES and rm.shape[0] >= _PBO_S_BLOCKS * 2:
            res = cscv_pbo(rm, s_blocks=_PBO_S_BLOCKS)
            pbo = None if (res.pbo != res.pbo) else float(res.pbo)   # NaN → None

    ci = bootstrap_sharpe_ci(arr, block_size=_auto_block(t), periods_per_year=periods_per_year)
    ci_t = ci.to_tuple()

    color, all_agree = _decide(dsr_cons, pbo, ci_t[0], ci_t[1], allow_pbo_absent_green=allow_pbo_absent_green)

    # R4 CPCV 路径稳健性接入（正交第四视角·绝不单点承重）：q05<无技能基线 = 相当比例组合路径 OOS 无优于随机
    # = 过拟合/切分脆弱。**report_only（默认）**：只附报告、绝不改裁决（守「不替方法学拍板」）。
    # **cpcv_conservative**（用户 opt-in）：脆弱**仅** green→yellow（advisory concern），**绝不硬 red、绝不升级**
    # （R2：单支不承重、red 只由 strong_neg 兜底；CPCV 是降级提醒非熔断）。
    cpcv_report: dict | None = None
    if isinstance(cpcv_distribution, dict) and cpcv_distribution.get("status") == "ok":
        q05 = cpcv_distribution.get("q05")
        baseline = cpcv_distribution.get("baseline", 0.0)
        fragile = isinstance(q05, (int, float)) and math.isfinite(q05) and isinstance(baseline, (int, float)) and q05 < baseline
        cpcv_report = {
            "metric": cpcv_distribution.get("metric"), "q05": q05, "baseline": baseline,
            "n_paths": cpcv_distribution.get("n_paths"), "fragile": bool(fragile), "policy": cpcv_policy,
        }
        if cpcv_policy == "cpcv_conservative" and fragile and color == "green":
            color = "yellow"                 # advisory 降级：脆弱不给完整放行（绝不 red、绝不升级）
            cpcv_report["downgraded_green_to_yellow"] = True
    if color == "red":
        phr = "证据不足以支持：至少一支证据强负（DSR 保守端低 / Sharpe CI 上界≤0 / PBO 偏高）。"
    elif color == "green" and pbo is None:
        phr = "证据充分(组合层放行)：DSR 保守端 + Bootstrap CI 双正；PBO=N/A(策略数不足)，R2 完整三角由组合层 override(D-WAVE1A 已记决策)。"
    elif color == "green":
        phr = "证据充分：DSR 保守端、PBO、Bootstrap CI 三支同向正。"
    elif pbo is None:
        phr = "证据分歧/不全：策略数不足以做 PBO（缺一支证据），无法构成完整三角 → 不放行。"
    else:
        phr = "证据分歧：三支未同向正，不放行（绝不因单支漂亮指标过闸）。"

    domain = f"适用域=该样本期/该资产({asset_class})/honest_n={n_floor}、过闸通缩试验数∈[{n_low},{n_high}]"
    unverified = "未验证=交易成本/容量/拥挤/regime 漂移/样本外持续性"
    var_note = "" if var is not None else "；V 未独立估计(退化旧近似)，通缩可能不足"
    # CPCV 注（report-only 仅陈述脆弱度；cpcv_conservative 降级时点明 advisory 来由）。
    cpcv_note = ""
    if cpcv_report is not None:
        if cpcv_report.get("downgraded_green_to_yellow"):
            cpcv_note = f"；CPCV 路径脆弱(q05={cpcv_report['q05']:.3g}<基线{cpcv_report['baseline']})→advisory 降 yellow(非熔断)"
        elif cpcv_report["fragile"]:
            cpcv_note = f"；CPCV 路径脆弱(q05={cpcv_report['q05']:.3g}<基线{cpcv_report['baseline']}·report-only 未改裁决)"
        else:
            cpcv_note = f"；CPCV 路径稳健(q05={cpcv_report['q05']:.3g}≥基线{cpcv_report['baseline']})"
    verdict_phrasing = f"{phr} {domain}；{unverified}{var_note}{cpcv_note}。"
    reason = (
        f"DSR[{dsr_opt:.2f}~{dsr_cons:.2f}] PBO={'n/a' if pbo is None else f'{pbo:.2f}'} "
        f"BootstrapCI=[{ci_t[0]:.2f},{ci_t[1]:.2f}]({ci.method})"
        f"{'' if cpcv_report is None else f' CPCV-q05={cpcv_report['q05']}'} → {color}"
    )

    return GateVerdict(
        color=color,
        dsr_optimistic=float(dsr_opt), dsr_conservative=float(dsr_cons),
        pbo=pbo, bootstrap_ci=ci_t, bootstrap_method=ci.method,
        all_agree_positive=all_agree, n_observed=n_eff.n_observed, n_eff=n_eff.to_dict(),
        var_sr_estimated=var is not None,
        reason=reason, verdict_phrasing=verdict_phrasing,
        model_risk_disclosure=list(_MODEL_RISK_DISCLOSURE),
        cpcv=cpcv_report,
    )


__all__ = ["GateColor", "GateVerdict", "run_overfit_gate"]
