"""Mathematical Spine 绑定 · VaR / ES / Kupiec 接 canonical 命门（金融数学 kernel P0-A）。

codex R2 数学治理裁决：金融数学 kernel 首切就接 canonical spine，不建平行弱命门。这里把
真实 ``var_es.py`` / ``backtest.py`` 的实现绑进脊柱（``app/lineage/spine*``），复用与
``app/eval/spine_bindings.py`` 同一套 artifact → binding → 独立 oracle 数值对账 → 一致性门：

    {VAR,ES,KUPIEC}_ARTIFACT（proof_backed 数学定义）
      → build_*_binding（真源码链指纹 code_content_hash）
      → *_consistency_check（impl vs 独立 oracle 数值对账）
      → evaluate_promotion（命门裁定：实现漂离定义 → 拒升级）

独立 oracle 走【另一条计算路径】核同一定义（impl 手写权重/闭式 ↔ oracle 走 numpy 分位 /
稠密网格积分 / scipy power_divergence），故能抓「impl 偏离定义」的漂移。VaR/ES 用
``ARTIFACT_ESTIMATOR``、Kupiec 用 ``ARTIFACT_STATISTICAL_TEST``——都在
``spine_gate.PIT_REQUIRING_TYPES`` 内，故命门强制 PIT 数据契约（估计器输入的回测返回序列
须实现日 PIT 戳记、无 look-ahead）。诚实边界见 ``spine_gate`` DISCLOSURE：门校验「声明 vs
证据自洽 + 标签强度匹配」，不自证数学命题——那靠这里的独立 oracle 内容质量 + Verifier/Critic。
"""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
from scipy.stats import chi2, norm, power_divergence

from ...lineage.spine import (
    ARTIFACT_ESTIMATOR,
    ARTIFACT_STATISTICAL_TEST,
    PROOF_BACKED,
    MathematicalArtifact,
    TheoryImplementationBinding,
)
from ...lineage.ids import content_hash
from ...lineage.spine_binder import code_fingerprint, numerical_consistency_check
from ...lineage.spine_gate import SpineDecision, evaluate_promotion
from . import backtest as _bt
from . import spec as _spec
from . import var_es as _ve

# ════════════════════════════ VaR 绑定（数值对账）════════════════════════════

VAR_ARTIFACT = MathematicalArtifact(
    artifact_type=ARTIFACT_ESTIMATOR,
    statement=(
        "VaR_c = -F^{-1}(alpha), alpha=1-c（损失单位）。historical=-经验逆CDF(inverted_cdf)@alpha；"
        "parametric-Gaussian h 日=-h·mu+sqrt(h)·sigma·Phi^{-1}(c)"
    ),
    notation="c=置信; alpha=1-c=尾概率; F^{-1}=经验逆CDF; mu/sigma=样本均值/样本std(ddof=1); h=持有期; Phi^{-1}=正态分位",
    assumptions=(
        "返回序列 PIT 正确（无 look-ahead）",
        "historical 用经验分布、不缩放持有期（多日须传多日返回）",
        "parametric 假定 i.i.d. 高斯：drift~h、vol~sqrt(h)",
    ),
    definition="Value-at-Risk：置信 c 下持有期损失的分位数（损失单位，不 clamp，保 translation equivariance）",
    derivation=(
        "损失 L=-r 的 c 分位 = -（返回的 alpha 分位）。h 日 i.i.d.：r_h~N(h·mu,h·sigma²)→"
        "L_h~N(-h·mu,h·sigma²)→VaR_c=-h·mu+sqrt(h)·sigma·Phi^{-1}(c)"
    ),
    proof_sketch="经验逆CDF 是分位的一致估计；高斯闭式由 loc/scale 变换直接得（drift 随 h、vol 随 sqrt(h)）",
    counterexamples=(
        "全正返回 → VaR 为负（不 clamp，风险度量非负钳）",
        "generic sqrt(h)·(1日 VaR) 对 mu≠0 错缩 drift",
    ),
    units="损失单位（与返回同量纲）",
    applicability="historical: n≥1；parametric: n≥2（样本 std）、h≥1 整数",
    failure_conditions=(
        "非有限输入/输出 → fail-closed",
        "厚尾/非高斯下 parametric 低估尾部（historical/EVT 更稳，EVT 为登记 follow-on）",
    ),
    proof_status=PROOF_BACKED,
    implementation_ref="app/backend/app/math/risk_measures/var_es.py:historical_var,parametric_gaussian_var",
    test_ref="app/backend/tests/test_math_risk_measures_spine.py",
    validation_ref="app/backend/tests/test_math_risk_measures.py",
)
# VaR 消费的返回序列须 PIT 正确——估计器输入的时间语义（满足门 pit-bound 子句）。
VAR_DATA_CONTRACT = {
    "known_at": "return_realization_date",
    "effective_at": "return_realization_date",
    "desc": "VaR 输入的回测返回序列按实现日 PIT 戳记，无 look-ahead",
}
_VAR_IMPL_CHAIN = (
    _ve.historical_var,
    _ve.parametric_gaussian_var,
    _ve._historical_tail,
    _ve._exact_tail_split,
    _ve._exact_alpha,
    _ve._clean_returns,
    _ve._check_confidence,
    _ve._check_horizon,
    _ve._finite,
    _spec.compute_measure,   # public dispatch entrypoint (codex R4)
    _spec.RiskMeasureSpec,   # spec construction invariants (codex R5: validation in fingerprint)
)
# 【已审定】VaR 实现链固定指纹（改 var_es.py 任一环 → live≠pinned → fresh 子句真触发 staleness）。
# 改实现后必须：重跑 test_math_risk_measures_spine 复核 impl↔定义一致 + 把此常量更新为新指纹。
VAR_PINNED_FINGERPRINT = "ebf4698fc1665691"

# ════════════════════════════ ES 绑定（数值对账）═════════════════════════════

ES_ARTIFACT = MathematicalArtifact(
    artifact_type=ARTIFACT_ESTIMATOR,
    statement=(
        "ES_c = -(1/alpha)∫_0^alpha F^{-1}(u)du（Acerbi-Tasche 相干）。historical=区间权重尾均值；"
        "parametric-Gaussian h 日=-h·mu+sqrt(h)·sigma·phi(Phi^{-1}(alpha))/alpha"
    ),
    notation="alpha=1-c; F^{-1}=经验逆CDF; phi=正态pdf; 权重=各序统计量CDF区间与(0,alpha]的重叠",
    assumptions=(
        "返回序列 PIT 正确（无 look-ahead）",
        "historical 用经验分布；ES 由与 VaR 共享的单一尾分解算得（相干由构造保证）",
        "parametric 假定 i.i.d. 高斯",
    ),
    definition="Expected Shortfall（CVaR）：alpha 尾内损失的条件期望；相干风险度量（ES>=VaR）",
    derivation=(
        "ES=尾部 F^{-1} 在(0,alpha]上的积分均值。序统计量 r_(i) 权重=其CDF区间((i-1)/n,i/n]与(0,alpha]"
        "的重叠。实现取结构相干式 ES=VaR+dot(w, L_tail-VaR)/alpha（L_tail=-r_(i)>=VaR）→ 加项为非负项之和 → 恒 >= VaR"
    ),
    proof_sketch=(
        "每个尾内序统计量 <= 边界序统计量（VaR）→ 尾损失 L_tail=-r_(i) >= VaR → L_tail-VaR>=0 → "
        "VaR+非负 >= VaR（浮点级·加非负不会舍到 VaR 以下·无经验容差）；高斯闭式由截尾正态期望得"
    ),
    counterexamples=(
        "naive mean(r[r<=q]) 尾均值在 fractional alpha·N 上错（AT 0.0914 vs naive 0.085）",
        "raw -dot(w,srt)/alpha：sum(w)!=alpha 与 dot 舍入共同可让 ES 跌破 VaR ~1 ULP（结构式规避）",
    ),
    units="损失单位（与返回同量纲）",
    applicability="historical: n≥1；parametric: n≥2、h≥1 整数",
    failure_conditions=(
        "非有限输入/输出 → fail-closed",
        "ES 跌破 VaR 超 ULP 容差 → 逻辑错 fail-closed",
    ),
    proof_status=PROOF_BACKED,
    implementation_ref="app/backend/app/math/risk_measures/var_es.py:historical_es,parametric_gaussian_es",
    test_ref="app/backend/tests/test_math_risk_measures_spine.py",
    validation_ref="app/backend/tests/test_math_risk_measures.py",
)
ES_DATA_CONTRACT = {
    "known_at": "return_realization_date",
    "effective_at": "return_realization_date",
    "desc": "ES 输入的回测返回序列按实现日 PIT 戳记，无 look-ahead",
}
_ES_IMPL_CHAIN = (
    _ve.historical_es,
    _ve.parametric_gaussian_es,
    _ve._historical_tail,
    _ve._exact_tail_split,
    _ve._exact_alpha,
    _ve._clean_returns,
    _ve._check_confidence,
    _ve._check_horizon,
    _ve._finite,
    _spec.compute_measure,   # public dispatch entrypoint (codex R4)
    _spec.RiskMeasureSpec,   # spec construction invariants (codex R5: validation in fingerprint)
)
ES_PINNED_FINGERPRINT = "af99db87e43c14df"

# ════════════════════════════ Kupiec 绑定（数值对账）═════════════════════════

KUPIEC_ARTIFACT = MathematicalArtifact(
    artifact_type=ARTIFACT_STATISTICAL_TEST,
    statement=(
        "LR_POF = -2·[(N-x)ln(1-p)+x·ln p − ((N-x)ln(1-pihat)+x·ln pihat)] ~ chi²(1)，"
        "p=1-c 期望失败率、pihat=x/N 观测失败率；LR>chi²_{1,tc} 则拒无条件覆盖"
    ),
    notation="N=预测数; x=突破数; p=alpha=1-c; pihat=x/N; tc=检验置信; chi²(1)=1自由度卡方",
    assumptions=(
        "返回序列 PIT 正确（VaR 预测在实现前已知）",
        "突破 i.i.d. Bernoulli(p)（无条件覆盖 H0）",
        "chi²(1) 零分布为渐近——极小 N/极少期望突破不可靠（exact-binomial 为登记 follow-on）",
    ),
    definition="Kupiec Proportion-of-Failures：VaR 无条件覆盖的似然比检验（Kupiec 1995）",
    derivation="Bernoulli 似然比 = 二项偏差 2·[bd0(x,Np)+bd0(N-x,N(1-p))]（Loader 2000 稳定偏差·两分量非负→无符号抵消）；x=0/x=N 的 0·ln0=0 极限使边界良定",
    proof_sketch="Wilks 定理：H0 下 -2lnΛ → chi²(自由度=参数差=1)；bd0 近均值用收敛级数、远均值用 log 差·避大 N 抵消/比值溢出",
    counterexamples=("x=0 → LR=-2N·ln(1-p)（非零）", "pihat=p → LR=0（完美校准不拒）"),
    units="无量纲卡方统计量（LR>=0）",
    applicability="N≥1、0<=x<=N 整数、c∈(0,1)；N·p 不太小时渐近可靠",
    failure_conditions=("小样本/稀有事件下 chi²(1) 近似失真 → 用 exact-binomial", "只测无条件覆盖、不测独立性（Christoffersen 为 follow-on）"),
    proof_status=PROOF_BACKED,
    implementation_ref="app/backend/app/math/risk_measures/backtest.py:kupiec_pof_test",
    test_ref="app/backend/tests/test_math_risk_measures_spine.py",
    validation_ref="app/backend/tests/test_math_risk_measures.py",
)
KUPIEC_DATA_CONTRACT = {
    "known_at": "forecast_date",
    "effective_at": "return_realization_date",
    "desc": "Kupiec 输入：VaR 预测在 forecast_date 已知、突破在 return_realization_date 实现（预测先于实现，无 look-ahead）",
}
_KUPIEC_IMPL_CHAIN = (
    _bt.kupiec_pof_test,
    _bt.count_exceedances,   # end-to-end path (codex R4: cover kupiec_from_returns)
    _bt.kupiec_from_returns,
    _bt.KupiecResult,        # public return contract (codex R8: shape change must trip staleness)
    _bt._bd0,                # Loader deviance helper (codex R10: numerical behavior must be pinned)
    _bt._int_ratio,          # overflow-safe int ratio (codex R10)
    _bt._to_float,           # overflow-safe count→float (codex R11)
    _bt._finite,             # fail-closed guard (codex R10)
)
KUPIEC_PINNED_FINGERPRINT = "5faf05ee5208228d"


# ── 独立 oracle：从数学定义【另一条计算路径】重算 ─────────────────────────────


def _historical_rank_oracle(n: int, confidence: float) -> int:
    """独立 array-free VaR rank：纯【整数有理数】路径（codex R6/R7·`_var_oracle` 真调用它）。

    ``Decimal(str(c)).as_integer_ratio()`` 取精确 p/q（字符串构造·无舍入·免 Decimal context），
    ``rank = ceil(n*(q-p)/q)`` 走整数 ceil 除法。不做任何 Decimal/float 算术：与 impl 的 Fraction
    路径（``var_es._exact_tail_split``）是两段独立精确实现——单侧回退（Decimal-28/float/round-9）
    即与另一侧分歧、被大 N/context 黄金逮住（R7：旧测试重写公式没调本 helper→单侧回退假绿）。
    """

    p, q = Decimal(str(float(confidence))).as_integer_ratio()  # c = p/q exactly
    m_num = n * (q - p)                                          # m = n*alpha = m_num / q
    return max(1, min(n, -(-m_num // q)))                        # integer ceil division


def _var_oracle(*, returns, confidence, method, horizon=1) -> float:
    """VaR 独立 oracle：historical 走独立整数有理数 rank；parametric 走 scipy loc/scale 分位。"""

    arr = np.asarray(returns, dtype=float)
    c = float(confidence)
    if method == "historical":
        rank = _historical_rank_oracle(arr.size, c)
        srt = np.sort(arr)
        return -float(srt[rank - 1])
    h = int(horizon)
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))
    # 损失分布 N(-h·mu, h·sigma²) 的 c 分位（scipy loc/scale ppf ≠ impl 的手写闭式）。
    return float(norm.ppf(c, loc=-h * mu, scale=math.sqrt(h) * sigma))


def _es_oracle(*, returns, confidence, method, horizon=1) -> float:
    """ES 独立 oracle：稠密网格对分位函数做中点 Riemann 积分（≠ impl 的区间权重点积/闭式）。"""

    arr = np.asarray(returns, dtype=float)
    c = float(confidence)
    alpha = 1.0 - c
    grid = 2_000_000
    mids = (np.arange(1, grid + 1) - 0.5) / grid  # (0,1) 中点
    if method == "historical":
        us = mids * alpha  # (0, alpha] 上的中点
        q = np.quantile(arr, us, method="inverted_cdf")
        return -float(np.mean(q))
    h = int(horizon)
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))
    us = c + mids * alpha  # (c, 1) 上的中点
    loss_q = norm.ppf(us, loc=-h * mu, scale=math.sqrt(h) * sigma)
    return float(np.mean(loss_q))


def _kupiec_oracle(*, n_obs, n_exceedances, var_confidence, test_confidence=0.95) -> tuple:
    """Kupiec 独立 oracle：(LR, p_value, reject) 三元组全对账（codex R3：不只核 LR）。

    LR 走 scipy power_divergence(log-likelihood) = G 统计量 = 2·Σ O·ln(O/E)，O=[x,N-x]、
    E=[N·p,N·(1-p)]（与 impl 手写似然比两条独立路径；0·ln0=0 极限 scipy 对 f_obs=0 按 0 处理）。
    p_value=chi2.sf(LR,1)、reject=LR>chi2.ppf(test_confidence,1)——test_confidence 变量化 →
    捕获「永远用 tc=.95」的 mutation。
    """

    n = int(n_obs)
    x = int(n_exceedances)
    p = 1.0 - float(var_confidence)
    stat, _ = power_divergence(
        f_obs=[x, n - x], f_exp=[n * p, n * (1.0 - p)], lambda_="log-likelihood"
    )
    lr = float(stat)
    p_value = float(chi2.sf(lr, df=1))
    reject = float(lr > float(chi2.ppf(float(test_confidence), df=1)))
    return (lr, p_value, reject)


# ── 确定性 fixtures（无 RNG；覆盖 historical/parametric、整数/fractional 边界、多日、突破边界）──


def _var_es_fixtures() -> list[dict]:
    base = np.linspace(-0.06, 0.05, 40)
    frac = np.array([-0.10, -0.07, -0.05, -0.02, 0.01, 0.03, 0.06])  # fractional alpha·N=1.4 @ c=0.8
    tied = np.array([-0.10, -0.10, -0.10, -0.02, 0.0, 0.01, 0.03, 0.05])  # ties multiplicity
    drift = np.array([-0.02, -0.01, 0.0, 0.01, 0.02, 0.03])  # mu≠0 → 多日 drift 判别
    allpos = np.array([0.01, 0.02, 0.03, 0.04, 0.05])  # 全正收益 → VaR/ES 落负损失域（非 clamp 判别）
    return [
        {"returns": base, "confidence": 0.95, "method": "historical", "horizon": 1},
        {"returns": frac, "confidence": 0.80, "method": "historical", "horizon": 1},
        {"returns": tied, "confidence": 0.75, "method": "historical", "horizon": 1},
        {"returns": base, "confidence": 0.99, "method": "historical", "horizon": 1},
        {"returns": allpos, "confidence": 0.90, "method": "historical", "horizon": 1},
        {"returns": base, "confidence": 0.95, "method": "parametric_gaussian", "horizon": 1},
        {"returns": drift, "confidence": 0.99, "method": "parametric_gaussian", "horizon": 10},
        {"returns": base, "confidence": 0.975, "method": "parametric_gaussian", "horizon": 5},
        {"returns": allpos, "confidence": 0.95, "method": "parametric_gaussian", "horizon": 1},  # 正收益 → 负 VaR/ES
    ]


def _kupiec_fixtures() -> list[dict]:
    return [
        {"n_obs": 500, "n_exceedances": 50, "var_confidence": 0.95},
        {"n_obs": 500, "n_exceedances": 25, "var_confidence": 0.95},
        {"n_obs": 500, "n_exceedances": 0, "var_confidence": 0.95},
        {"n_obs": 500, "n_exceedances": 500, "var_confidence": 0.95},  # x=N 边界
        {"n_obs": 250, "n_exceedances": 12, "var_confidence": 0.95},
        {"n_obs": 500, "n_exceedances": 29, "var_confidence": 0.95, "test_confidence": 0.50},  # 非默认 tc
        {"n_obs": 1000, "n_exceedances": 5, "var_confidence": 0.99},
        {"n_obs": 2000, "n_exceedances": 1, "var_confidence": 0.999},   # 极端置信·罕见事件（codex R8）
        {"n_obs": 1000, "n_exceedances": 995, "var_confidence": 0.001},  # 极端置信·多数突破
    ]


def _kupiec_impl(*, n_obs, n_exceedances, var_confidence, test_confidence=0.95) -> tuple:
    r = _bt.kupiec_pof_test(
        n_obs, n_exceedances, var_confidence, test_confidence=test_confidence
    )
    return (r.lr_stat, r.p_value, float(r.reject))


# ── 实现链指纹 ────────────────────────────────────────────────────────────────


def _public_api_source() -> str:
    """SOURCE TEXT of the package public ``__init__`` (the export bindings), folded into every
    fingerprint so re-binding a public name (``historical_var = historical_es``) trips staleness
    (codex R9). Uses the .py TEXT, not the module object — passing the module to code_fingerprint
    would hash ``repr(module)`` which embeds the absolute checkout path, making the fingerprint
    path-dependent (fake pinned-match on this machine, breaks on CI — codex R10). Lazy import
    avoids the circular load.
    """

    import importlib
    import inspect

    return inspect.getsource(importlib.import_module("app.math.risk_measures"))


def var_code_fingerprint() -> str:
    return content_hash({"chain": code_fingerprint(*_VAR_IMPL_CHAIN), "public_api": _public_api_source()})


def es_code_fingerprint() -> str:
    return content_hash({"chain": code_fingerprint(*_ES_IMPL_CHAIN), "public_api": _public_api_source()})


def kupiec_code_fingerprint() -> str:
    return content_hash({"chain": code_fingerprint(*_KUPIEC_IMPL_CHAIN), "public_api": _public_api_source()})


# ── binding 构造 ──────────────────────────────────────────────────────────────


def build_var_binding(code_content_hash: str | None = None) -> TheoryImplementationBinding:
    return TheoryImplementationBinding(
        theory_ref=VAR_ARTIFACT.artifact_id,
        code_ref="app/backend/app/math/risk_measures/var_es.py:historical_var,parametric_gaussian_var",
        code_content_hash=code_content_hash or var_code_fingerprint(),
        config_ref="math/risk_measures:quantile_method=inverted_cdf,std_ddof=1",
        data_contract_ref="contract/backtest_returns_pit",
        implementation_spec="historical_var(returns,confidence) / parametric_gaussian_var(returns,confidence,horizon)",
        test_refs=("app/backend/tests/test_math_risk_measures_spine.py",),
        dimension_check="损失单位（与返回同量纲）",
        tolerance=1e-6,
    )


def build_es_binding(code_content_hash: str | None = None) -> TheoryImplementationBinding:
    return TheoryImplementationBinding(
        theory_ref=ES_ARTIFACT.artifact_id,
        code_ref="app/backend/app/math/risk_measures/var_es.py:historical_es,parametric_gaussian_es",
        code_content_hash=code_content_hash or es_code_fingerprint(),
        config_ref="math/risk_measures:quantile_method=inverted_cdf,std_ddof=1",
        data_contract_ref="contract/backtest_returns_pit",
        implementation_spec="historical_es(returns,confidence) / parametric_gaussian_es(returns,confidence,horizon)",
        test_refs=("app/backend/tests/test_math_risk_measures_spine.py",),
        dimension_check="损失单位；相干 ES>=VaR",
        tolerance=1e-7,  # codex R3/R4：binding 元数据容差与 es_consistency_check 一致（同 1e-7）
    )


def build_kupiec_binding(code_content_hash: str | None = None) -> TheoryImplementationBinding:
    return TheoryImplementationBinding(
        theory_ref=KUPIEC_ARTIFACT.artifact_id,
        code_ref="app/backend/app/math/risk_measures/backtest.py:kupiec_pof_test",
        code_content_hash=code_content_hash or kupiec_code_fingerprint(),
        config_ref="math/risk_measures:test_confidence=0.95,null=chi2(1)",
        data_contract_ref="contract/var_forecast_exceedances_pit",
        implementation_spec="kupiec_pof_test(n_obs,n_exceedances,var_confidence,test_confidence)",
        test_refs=("app/backend/tests/test_math_risk_measures_spine.py",),
        dimension_check="无量纲卡方统计量 LR>=0",
        tolerance=1e-6,
    )


# ── 一致性对账 ────────────────────────────────────────────────────────────────


def var_consistency_check(impl=_ve.historical_var, *, binding=None):
    """VaR impl vs 独立 oracle 数值对账（impl 参数仅测试注入漂移用；默认走真实现 dispatch）。"""

    binding = binding if binding is not None else build_var_binding()

    def _impl(*, returns, confidence, method, horizon=1):
        # ``impl`` overrides only the HISTORICAL path (tests inject drift there); parametric
        # always routes to the real implementation.
        if method == "historical":
            return impl(returns, confidence)
        return _ve.parametric_gaussian_var(returns, confidence, horizon=horizon)

    return numerical_consistency_check(
        binding.binding_id,
        _impl,
        _var_oracle,
        _var_es_fixtures(),
        tolerance=1e-6,
        affected_assets=("VaR", "risk_report", "portfolio_risk"),
    )


def es_consistency_check(impl=_ve.historical_es, *, binding=None):
    binding = binding if binding is not None else build_es_binding()

    def _impl(*, returns, confidence, method, horizon=1):
        # ``impl`` overrides only the HISTORICAL path (tests inject drift there); parametric
        # always routes to the real implementation.
        if method == "historical":
            return impl(returns, confidence)
        return _ve.parametric_gaussian_es(returns, confidence, horizon=horizon)

    return numerical_consistency_check(
        binding.binding_id,
        _impl,
        _es_oracle,
        _var_es_fixtures(),
        tolerance=1e-7,  # codex R3：收紧至 1e-7（实测网格残差最坏 ~6.4e-9·仍远小于真漂移 ~6e-3）
        affected_assets=("ES", "CVaR", "risk_report", "portfolio_risk"),
    )


def kupiec_consistency_check(impl=_kupiec_impl, *, binding=None):
    binding = binding if binding is not None else build_kupiec_binding()
    return numerical_consistency_check(
        binding.binding_id,
        impl,
        _kupiec_oracle,
        _kupiec_fixtures(),
        tolerance=1e-6,
        affected_assets=("Kupiec", "var_backtest", "coverage_verdict"),
    )


# ── 全链裁定 ──────────────────────────────────────────────────────────────────


# staleness 默认路径（codex R3·P1-1）：binding 记录【已审定 pinned】指纹、current 读 live 源指纹。
# 改 var_es/backtest 未重 pin → live≠pinned → 门 fresh 子句真拒（默认即查 staleness·非自我指纹）。
# 显式传 pinned_code_hash 覆写（孤立可证用）；current_code_hash 显式传可模拟 live 漂移。


def verify_var_consistency(
    *,
    requested_label: str = PROOF_BACKED,
    impl=_ve.historical_var,
    pinned_code_hash: str | None = None,
    current_code_hash: str | None = None,
) -> SpineDecision:
    binding = build_var_binding(code_content_hash=pinned_code_hash or VAR_PINNED_FINGERPRINT)
    check = var_consistency_check(impl, binding=binding)
    code_hash = current_code_hash if current_code_hash is not None else var_code_fingerprint()
    return evaluate_promotion(
        VAR_ARTIFACT, binding, [check],
        requested_label=requested_label, current_code_hash=code_hash, data_contract=VAR_DATA_CONTRACT,
    )


def verify_es_consistency(
    *,
    requested_label: str = PROOF_BACKED,
    impl=_ve.historical_es,
    pinned_code_hash: str | None = None,
    current_code_hash: str | None = None,
) -> SpineDecision:
    binding = build_es_binding(code_content_hash=pinned_code_hash or ES_PINNED_FINGERPRINT)
    check = es_consistency_check(impl, binding=binding)
    code_hash = current_code_hash if current_code_hash is not None else es_code_fingerprint()
    return evaluate_promotion(
        ES_ARTIFACT, binding, [check],
        requested_label=requested_label, current_code_hash=code_hash, data_contract=ES_DATA_CONTRACT,
    )


def verify_kupiec_consistency(
    *,
    requested_label: str = PROOF_BACKED,
    impl=_kupiec_impl,
    pinned_code_hash: str | None = None,
    current_code_hash: str | None = None,
) -> SpineDecision:
    binding = build_kupiec_binding(code_content_hash=pinned_code_hash or KUPIEC_PINNED_FINGERPRINT)
    check = kupiec_consistency_check(impl, binding=binding)
    code_hash = current_code_hash if current_code_hash is not None else kupiec_code_fingerprint()
    return evaluate_promotion(
        KUPIEC_ARTIFACT, binding, [check],
        requested_label=requested_label, current_code_hash=code_hash, data_contract=KUPIEC_DATA_CONTRACT,
    )
