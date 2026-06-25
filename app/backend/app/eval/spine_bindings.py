"""eval · DSR 的 Mathematical Spine 绑定（全链贯穿第一段 · 决策 D-MATH-SPINE）。

把信任层核心估计器 Deflated Sharpe Ratio（`eval/dsr.py`）经脊柱绑定：
  DSR_ARTIFACT（数学定义，proof_backed）
    → build_dsr_binding（真源码指纹 code_content_hash）
    → dsr_consistency_check（impl vs 独立 oracle 数值对账）
    → evaluate_promotion（一致性门裁定）

`dsr_oracle` 是【独立】重算：矩走 `scipy.stats`（bias=True）而非 `dsr.py` 手算的 m_k，
走另一条计算路径核同一数学定义。impl 偏离定义（如丢通缩 / ddof 错）→ oracle 对账 fail →
门拒升级（命门：理论对、实现跑偏=系统错误）。诚实边界见 finding `spine-consistency-gate/01`。
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import kurtosis as _scipy_kurt
from scipy.stats import norm
from scipy.stats import skew as _scipy_skew

from ..lineage.spine import (
    ARTIFACT_STATISTICAL_TEST,
    PROOF_BACKED,
    MathematicalArtifact,
    TheoryImplementationBinding,
)
from ..lineage.spine_binder import (
    code_fingerprint,
    numerical_consistency_check,
    property_consistency_check,
)
from ..lineage.spine_gate import SpineDecision, evaluate_promotion
from . import bootstrap as _bootstrap_mod
from . import dsr as _dsr_mod
from . import pbo as _pbo_mod

_EULER = 0.5772156649

# ── DSR 数学产物（同行评审发表结果 → proof_backed）──────────────────────────
DSR_ARTIFACT = MathematicalArtifact(
    artifact_type=ARTIFACT_STATISTICAL_TEST,
    statement=(
        "DSR = Φ( SR_pp·√(T−1)/denom − E[max] )，"
        "denom=√(1 − γ3·SR_pp + (γ4−3+2)/4·SR_pp²)，E[max]=√(2 ln N) − γ_euler/√(2 ln N)"
    ),
    notation="SR_pp=每期Sharpe; γ3=有偏偏度; γ4−3=有偏超额峰度; N=试验数; T=样本期数; Φ=标准正态CDF",
    assumptions=(
        "返回序列 PIT 正确（无 look-ahead）",
        "诚实提交试验数 N（honest-N，不可手动改小）",
        "γ3/γ4 用有偏总体矩（= scipy bias=True）",
    ),
    definition="Deflated Sharpe Ratio：在 N 次试验的多重检验偏差下，SR 显著性的标度修正概率",
    derivation=(
        "由 False Strategy Theorem：N 个独立 SR 的极大值期望 E[max]≈√(2 ln N)−γ_euler/√(2 ln N)；"
        "把观测 SR 的 t 统计量减去该极值期望、并按偏度/峰度 studentize，再过 Φ 得显著性概率。"
    ),
    proof_sketch="Bailey & López de Prado (2014) 给出极值期望近似与渐近正态性证明",
    counterexamples=("N 报小（谎报试验数）→ DSR 虚高（不是公式错，是输入不诚实）",),
    units="无量纲概率 ∈ [0,1]",
    applicability="样本期 T≥3、N≥1；返回近似 i.i.d. 或弱相关",
    failure_conditions=(
        "var_sr_hat 不可估时退化旧极值近似（V 隐含=1），通缩可能不足，须裁决披露",
        "DSR 只做显著性标度修正，不保证'真有效'",
    ),
    proof_status=PROOF_BACKED,
    implementation_ref="app/backend/app/eval/dsr.py:deflated_sharpe_ratio",
    test_ref="app/backend/tests/test_spine_dsr_binding.py",
    validation_ref="app/backend/tests/test_overfit_gate.py",
)

# DSR 消费的回测返回序列须 PIT 正确——统计检验的输入时间语义（满足门 pit-bound 子句）。
DSR_DATA_CONTRACT = {
    "known_at": "return_realization_date",
    "effective_at": "return_realization_date",
    "desc": "DSR 输入的回测返回序列按实现日 PIT 戳记，无 look-ahead",
}

# 绑定进指纹的整条 DSR 计算链（改任一环 → 指纹变 → staleness 抓）。
_DSR_IMPL_CHAIN = (
    _dsr_mod.deflated_sharpe_ratio,
    _dsr_mod.sharpe_ratio,
    _dsr_mod._expected_max_sr,
    _dsr_mod._skew,
    _dsr_mod._kurt_excess,
)

# 【已审定】DSR 实现链的固定指纹（= 本切片审过的 dsr.py 计算链 content_hash）。
# 生产一致性核（overfit_gate）用它当 binding 的【记录】hash、用 live 指纹当 current：
#   live == PINNED → 实现未漂移、binding 未过期 → fresh 子句过；
#   live != PINNED → dsr.py 改了但 binding 未刷新 → §6「实现改动后未刷新 binding → 拒」真触发。
# **改 dsr.py 后必须**：重新核对 DSR↔数学定义一致（跑 test_spine_dsr_binding）+ 把此常量更新为新指纹
# （= 显式「刷新 TheoryImplementationBinding」的审定动作）。tripwire 测试会在不一致时硬失败提醒。
DSR_PINNED_FINGERPRINT = "77bd7ce66bf157a9"


def dsr_oracle(
    *,
    returns: np.ndarray,
    n_trials: int,
    periods_per_year: int = 252,
    var_sr_hat: float | None = None,
) -> float:
    """从数学定义【独立】重算 DSR（矩走 scipy，非 dsr.py 手算）——用于一致性对账。"""

    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n < 3 or n_trials < 1:
        return 0.0
    std = arr.std(ddof=1)
    if std <= 0:
        return 0.0
    sr_pp = arr.mean() / std
    if sr_pp == 0:
        return 0.0
    g3 = float(_scipy_skew(arr, bias=True))
    g4_excess = float(_scipy_kurt(arr, fisher=True, bias=True))
    denom = math.sqrt(max(1e-12, 1 - g3 * sr_pp + (g4_excess + 2) / 4.0 * sr_pp**2))
    if n_trials <= 1:
        expected = 0.0
    elif var_sr_hat is None:
        a = math.sqrt(2 * math.log(n_trials))
        expected = a - _EULER / a
    else:
        v = max(float(var_sr_hat), 0.0)
        expected = math.sqrt(v) * (
            (1 - _EULER) * norm.ppf(1 - 1.0 / n_trials)
            + _EULER * norm.ppf(1 - 1.0 / (n_trials * math.e))
        )
    if var_sr_hat is not None:
        z = (sr_pp - expected) * math.sqrt(n - 1) / denom
    else:
        z = sr_pp * math.sqrt(n - 1) / denom - expected
    return float(norm.cdf(z))


def _fixtures() -> list[dict]:
    """确定性 fixtures（无 RNG）——覆盖不同形状/试验数。"""

    base = np.linspace(-0.015, 0.025, 120)
    skewed = np.concatenate([np.full(90, 0.004), np.full(30, -0.02)])
    wavy = 0.01 * np.sin(np.linspace(0, 8 * math.pi, 200)) + 0.001
    return [
        {"returns": base, "n_trials": 20},
        {"returns": base, "n_trials": 200},
        {"returns": skewed, "n_trials": 50},
        {"returns": wavy, "n_trials": 10},
        {"returns": base, "n_trials": 50, "var_sr_hat": 0.25},
    ]


def dsr_code_fingerprint() -> str:
    """当前 DSR 实现链的真源码指纹（运行时取，用于门 fresh/staleness 子句）。"""

    return code_fingerprint(*_DSR_IMPL_CHAIN)


def build_dsr_binding(code_content_hash: str | None = None) -> TheoryImplementationBinding:
    """产出 DSR 的 TheoryImplementationBinding。

    `code_content_hash`：binding【记录】的实现指纹。None → 用当前实现链指纹（孤立可证用）；
    生产传 `DSR_PINNED_FINGERPRINT`（已审定指纹）→ 与 live 指纹比对才能真触发 staleness 子句。
    """

    return TheoryImplementationBinding(
        theory_ref=DSR_ARTIFACT.artifact_id,
        code_ref="app/backend/app/eval/dsr.py:deflated_sharpe_ratio",
        code_content_hash=code_content_hash or dsr_code_fingerprint(),
        config_ref="eval/dsr:periods_per_year=252,var_sr_hat=optional",
        data_contract_ref="contract/backtest_returns_pit",
        implementation_spec="deflated_sharpe_ratio(returns, n_trials, periods_per_year, var_sr_hat)",
        test_refs=("app/backend/tests/test_spine_dsr_binding.py",),
        dimension_check="无量纲概率 [0,1]",
        tolerance=1e-6,
    )


def dsr_consistency_check(impl=_dsr_mod.deflated_sharpe_ratio, *, tolerance: float = 1e-6, binding=None):
    """impl vs 独立 oracle 在确定性 fixtures 上对账，产出 ConsistencyCheck。

    `binding`：复用调用方的 binding（保证 check.binding_id 与门裁定的 binding 一致）；None → 自建。
    """

    binding = binding if binding is not None else build_dsr_binding()
    return numerical_consistency_check(
        binding.binding_id,
        impl,
        dsr_oracle,
        _fixtures(),
        tolerance=tolerance,
        affected_assets=("DSR", "overfit_gate", "run_verdict"),
    )


def verify_dsr_consistency(
    *,
    requested_label: str = PROOF_BACKED,
    impl=_dsr_mod.deflated_sharpe_ratio,
    pinned_code_hash: str | None = None,
    current_code_hash: str | None = None,
) -> SpineDecision:
    """跑通 artifact→binding→numerical check→门 全链，返回 DSR 的升级裁定。

    - `pinned_code_hash`：binding【记录】的已审定指纹（生产传 `DSR_PINNED_FINGERPRINT`）。None → 用当前
      实现链指纹做 binding 记录（此时 binding 记录 == live，fresh 子句恒过——仅孤立可证用，**不查 staleness**）。
    - `current_code_hash`：live 实现指纹。None → 实时取当前实现链指纹。
    生产路径传 `pinned_code_hash=DSR_PINNED_FINGERPRINT`：dsr.py 改了但常量未刷新 → live≠pinned → fresh 子句拒。
    """

    binding = build_dsr_binding(code_content_hash=pinned_code_hash)
    check = dsr_consistency_check(impl, binding=binding)
    code_hash = current_code_hash if current_code_hash is not None else dsr_code_fingerprint()
    return evaluate_promotion(
        DSR_ARTIFACT,
        binding,
        [check],
        requested_label=requested_label,
        current_code_hash=code_hash,
        data_contract=DSR_DATA_CONTRACT,
    )


# ════════════════════════ PBO (CSCV) 绑定（property-based）════════════════════
# 难做闭式独立 oracle（组合算法）→ 用从定义推出的【必要性质】对账（finding 02）。

PBO_ARTIFACT = MathematicalArtifact(
    artifact_type=ARTIFACT_STATISTICAL_TEST,
    statement="PBO = frac_combos(logit(ω̄)<0)：CSCV 对称组合 C(S,S/2)，IS-argmax 在 OOS 排名落 median 下的频率",
    notation="S=时间块数(偶); ω̄=OOS 相对排名∈(0,1); λ=logit(ω̄); PBO∈[0,1]",
    assumptions=("返回序列 PIT 正确（无 look-ahead）", "策略数 N≥min（少策略估计噪声大）", "S 偶数对称分割"),
    definition="Probability of Backtest Overfitting（López de Prado 2014 CSCV）：策略选择程序 OOS 退化概率",
    derivation="分 S 块、组合选 S/2 训练 S/2 测试，IS-argmax 的 OOS 相对排名分布 → PBO=P(排名<median)",
    proof_sketch="纯噪声下 IS-best 的 OOS 排名均匀 → E[PBO]=0.5；过拟合 IS-best OOS 系统性差 → PBO→1",
    counterexamples=("少策略/S 奇 → 估计无意义（strict 拒/非 strict 返 NaN）",),
    units="无量纲概率 ∈ [0,1]",
    applicability="N≥10 策略、S≥4 偶数、T≥2S",
    failure_conditions=("单策略 PBO 无意义", "组合爆炸 cap 采样 → 非全枚举近似"),
    proof_status=PROOF_BACKED,
    implementation_ref="app/backend/app/eval/pbo.py:cscv_pbo",
    test_ref="app/backend/tests/test_spine_pbo_bootstrap_binding.py",
    validation_ref="app/backend/tests/test_overfit_gate.py",
)
PBO_DATA_CONTRACT = {
    "known_at": "trial_return_date",
    "effective_at": "trial_return_date",
    "desc": "PBO 输入历史试验返回矩阵按实现日 PIT 戳记，无 look-ahead",
}
_PBO_IMPL_CHAIN = (_pbo_mod.cscv_pbo, _pbo_mod._sharpe_per_period)
PBO_PINNED_FINGERPRINT = "8a7179e0db1006b3"


def pbo_code_fingerprint() -> str:
    return code_fingerprint(*_PBO_IMPL_CHAIN)


def build_pbo_binding(code_content_hash: str | None = None) -> TheoryImplementationBinding:
    return TheoryImplementationBinding(
        theory_ref=PBO_ARTIFACT.artifact_id,
        code_ref="app/backend/app/eval/pbo.py:cscv_pbo",
        code_content_hash=code_content_hash or pbo_code_fingerprint(),
        config_ref="eval/pbo:s_blocks=8,min_n_strategies=10",
        data_contract_ref="contract/trial_returns_pit",
        implementation_spec="cscv_pbo(returns_matrix, s_blocks, max_combinations)",
        test_refs=("app/backend/tests/test_spine_pbo_bootstrap_binding.py",),
        dimension_check="无量纲概率 [0,1]",
    )


def _pbo_properties(impl=_pbo_mod.cscv_pbo) -> list[tuple[str, bool, str]]:
    """从 PBO 数学定义推出的必要性质（确定性 fixtures）。"""

    import math as _m

    noise = np.random.default_rng(12345).normal(size=(480, 20)) * 0.01
    r_noise = impl(noise, s_blocks=8, enumerate_all=True)
    skill = np.random.default_rng(777).normal(size=(480, 20)) * 0.01
    skill[:, 0] = skill[:, 0] + 0.01  # 一列恒强 alpha → IS-best 也 OOS-best
    r_skill = impl(skill, s_blocks=8, enumerate_all=True)

    sign_ok = True
    if _m.isfinite(r_noise.lambda_logit_mean):
        sign_ok = (r_noise.pbo >= 0.5) == (r_noise.lambda_logit_mean <= 0)
    return [
        ("P1_range", 0.0 <= r_noise.pbo <= 1.0, f"noise_pbo={r_noise.pbo:.3f}"),
        ("P2_noise≈0.5", 0.3 <= r_noise.pbo <= 0.7, f"noise_pbo={r_noise.pbo:.3f}"),
        ("P5_sign一致", sign_ok, f"pbo={r_noise.pbo:.3f},λ={r_noise.lambda_logit_mean:.3f}"),
        ("P4_真信号低pbo", r_skill.pbo <= 0.4, f"skill_pbo={r_skill.pbo:.3f}"),
    ]


def pbo_consistency_check(impl=_pbo_mod.cscv_pbo, *, binding=None):
    binding = binding if binding is not None else build_pbo_binding()
    return property_consistency_check(
        binding.binding_id,
        _pbo_properties(impl),
        affected_assets=("PBO", "overfit_gate", "run_verdict"),
    )


def verify_pbo_consistency(
    *,
    requested_label: str = PROOF_BACKED,
    impl=_pbo_mod.cscv_pbo,
    pinned_code_hash: str | None = None,
    current_code_hash: str | None = None,
) -> SpineDecision:
    binding = build_pbo_binding(code_content_hash=pinned_code_hash)
    check = pbo_consistency_check(impl, binding=binding)
    code_hash = current_code_hash if current_code_hash is not None else pbo_code_fingerprint()
    return evaluate_promotion(
        PBO_ARTIFACT, binding, [check],
        requested_label=requested_label, current_code_hash=code_hash, data_contract=PBO_DATA_CONTRACT,
    )


# ════════════════════════ Bootstrap Sharpe CI 绑定（property-based）═══════════

BOOTSTRAP_ARTIFACT = MathematicalArtifact(
    artifact_type=ARTIFACT_STATISTICAL_TEST,
    statement="Bootstrap percentile CI：[Q_{α/2}, Q_{1−α/2}] of {Sharpe(resample_b)}_{b=1..B}；moving-block 保序列相关",
    notation="B=重抽次数; α=1−confidence; Q=经验分位; block_size=块长",
    assumptions=("返回序列 PIT 正确（无 look-ahead）", "（近似）平稳", "block 重抽保留自相关"),
    definition="Sharpe 比率的 bootstrap 置信区间（GOAL §6.1）：重抽分布的经验分位",
    derivation="对收益序列 moving-block 重抽 B 次、各算 Sharpe → 经验分布 → 取 α/2 与 1−α/2 分位为 CI",
    proof_sketch="bootstrap 一致性：经验分位收敛到真分位（平稳/弱相关下）；block 保自相关 → CI 不低估方差",
    counterexamples=("iid 重抽抹掉序列相关 → 低估方差 CI 过窄", "block≥T → 零宽伪精确 CI"),
    units="Sharpe 单位（年化）区间",
    applicability="T≥5；block_size≥1 启用 moving-block",
    failure_conditions=("非平稳 regime 漂移下覆盖失真", "重抽分布偏态 → percentile CI 偏"),
    proof_status=PROOF_BACKED,
    implementation_ref="app/backend/app/eval/bootstrap.py:bootstrap_sharpe_ci",
    test_ref="app/backend/tests/test_spine_pbo_bootstrap_binding.py",
    validation_ref="app/backend/tests/test_overfit_gate.py",
)
BOOTSTRAP_DATA_CONTRACT = {
    "known_at": "return_realization_date",
    "effective_at": "return_realization_date",
    "desc": "bootstrap 输入回测返回序列按实现日 PIT 戳记，无 look-ahead",
}
_BOOTSTRAP_IMPL_CHAIN = (
    _bootstrap_mod.bootstrap_sharpe_ci,
    _bootstrap_mod._moving_block_sample,
    _dsr_mod.sharpe_ratio,
)
BOOTSTRAP_PINNED_FINGERPRINT = "fc9f5c540e5834b8"


def bootstrap_code_fingerprint() -> str:
    return code_fingerprint(*_BOOTSTRAP_IMPL_CHAIN)


def build_bootstrap_binding(code_content_hash: str | None = None) -> TheoryImplementationBinding:
    return TheoryImplementationBinding(
        theory_ref=BOOTSTRAP_ARTIFACT.artifact_id,
        code_ref="app/backend/app/eval/bootstrap.py:bootstrap_sharpe_ci",
        code_content_hash=code_content_hash or bootstrap_code_fingerprint(),
        config_ref="eval/bootstrap:n_boot=1000,confidence=0.95,seed=42",
        data_contract_ref="contract/backtest_returns_pit",
        implementation_spec="bootstrap_sharpe_ci(returns, n_boot, confidence, seed, block_size)",
        test_refs=("app/backend/tests/test_spine_pbo_bootstrap_binding.py",),
        dimension_check="Sharpe 区间 lower≤upper",
    )


def _bootstrap_properties(impl=_bootstrap_mod.bootstrap_sharpe_ci) -> list[tuple[str, bool, str]]:
    """从 bootstrap percentile CI 定义推出的必要性质（seed 固定 → 确定可复现）。"""

    strong = np.linspace(0.0005, 0.0015, 300)  # 恒正 → 强 Sharpe
    ci = impl(strong, n_boot=500, block_size=10)
    ci2 = impl(strong, n_boot=500, block_size=10)
    noise = 0.01 * np.sin(np.linspace(0.0, 20.0 * np.pi, 300))  # 零均值振荡 → Sharpe≈0
    cin = impl(noise, n_boot=500, block_size=10)
    return [
        ("B1_lower≤upper", ci.lower <= ci.upper, f"[{ci.lower:.3f},{ci.upper:.3f}]"),
        ("B2_estimate==sharpe", abs(ci.estimate - _dsr_mod.sharpe_ratio(strong)) < 1e-9, f"est={ci.estimate:.4f}"),
        ("B3_可复现", (ci.lower == ci2.lower and ci.upper == ci2.upper), "同 seed→同 CI"),
        ("B4_真信号lower>0", ci.lower > 0, f"lower={ci.lower:.3f}"),
        ("B5_噪声跨0", cin.lower < 0 < cin.upper, f"[{cin.lower:.3f},{cin.upper:.3f}]"),
    ]


def bootstrap_consistency_check(impl=_bootstrap_mod.bootstrap_sharpe_ci, *, binding=None):
    binding = binding if binding is not None else build_bootstrap_binding()
    return property_consistency_check(
        binding.binding_id,
        _bootstrap_properties(impl),
        affected_assets=("Bootstrap", "overfit_gate", "run_verdict"),
    )


def verify_bootstrap_consistency(
    *,
    requested_label: str = PROOF_BACKED,
    impl=_bootstrap_mod.bootstrap_sharpe_ci,
    pinned_code_hash: str | None = None,
    current_code_hash: str | None = None,
) -> SpineDecision:
    binding = build_bootstrap_binding(code_content_hash=pinned_code_hash)
    check = bootstrap_consistency_check(impl, binding=binding)
    code_hash = current_code_hash if current_code_hash is not None else bootstrap_code_fingerprint()
    return evaluate_promotion(
        BOOTSTRAP_ARTIFACT, binding, [check],
        requested_label=requested_label, current_code_hash=code_hash, data_contract=BOOTSTRAP_DATA_CONTRACT,
    )
