"""真 ERC solver 对抗测试 + canonical 命门绑定（金融数学 kernel P0-A #8）。

覆盖：solver correctness（等风险贡献·退化 oracle·metamorphic）、fail-closed（非法协方差/不收敛/
下溢即 raise·无静默钳/等权兜底）、命门（promote proof_backed·MUTATION 错标必被逮·staleness·
pinned-fingerprint tripwire）。数学口径经 codex/GPT-5.6-sol 授权裁决（D-MATH-DECIDER）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.lineage.spine import PROOF_BACKED
from app.portfolio import spine_binding as sb
from app.portfolio.optimizers import (
    ERCError,
    equal_risk_contribution,
    inverse_volatility,
)


def _mkcov(sigmas: list[float], corr: list[list[float]]) -> pd.DataFrame:
    d = np.diag(sigmas)
    cov = d @ np.asarray(corr, dtype=float) @ d
    labels = [f"A{i}" for i in range(len(sigmas))]
    return pd.DataFrame(cov, index=labels, columns=labels)


def _rc(cov: pd.DataFrame, w: dict[str, float]) -> np.ndarray:
    syms = list(cov.columns)
    sigma = cov.loc[syms, syms].values
    wv = np.array([w[s] for s in syms], dtype=float)
    v = float(wv @ sigma @ wv)
    return wv * (sigma @ wv) / v


# codex 跨厂商实证例：inverse-vol 相对贡献=(3/7,3/14,5/14)≠ERC。
CORR3 = _mkcov([0.1, 0.2, 0.3], [[1, 0.1, 0.7], [0.1, 1, -0.2], [0.7, -0.2, 1.0]])
DIAG4 = _mkcov([0.1, 0.25, 0.4, 0.15], [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])


# ════════════════════════════ solver correctness ═══════════════════════════


def test_erc_equal_risk_contributions():
    """真 ERC：所有相对风险贡献 = 1/N（E_RC≤1e-8）。"""

    w = equal_risk_contribution(CORR3)
    rc = _rc(CORR3, w)
    assert float(np.max(np.abs(3 * rc - 1.0))) < 1e-8
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert all(v > 0 for v in w.values())


def test_erc_diagonal_reduces_to_inverse_vol():
    """对角 Σ ⇒ ERC 精确退化为 inverse-volatility（闭式 oracle 交叉核）。"""

    we, wi = equal_risk_contribution(DIAG4), inverse_volatility(DIAG4)
    for s in DIAG4.columns:
        assert abs(we[s] - wi[s]) < 1e-10


def test_erc_two_asset_reduces_to_inverse_vol():
    """N=2 任意相关 ⇒ 协方差交叉项抵消 ⇒ ERC 仍=inverse-vol。"""

    cov = _mkcov([0.12, 0.31], [[1, 0.83], [0.83, 1]])
    we, wi = equal_risk_contribution(cov), inverse_volatility(cov)
    for s in cov.columns:
        assert abs(we[s] - wi[s]) < 1e-10


def test_erc_differs_from_inverse_vol_when_correlated_n3():
    """mislabel proof：N≥3 相关结构下 ERC 明显≠inverse-vol（这正是本切修的错标）。"""

    we, wi = equal_risk_contribution(CORR3), inverse_volatility(CORR3)
    assert max(abs(we[s] - wi[s]) for s in CORR3.columns) > 0.05


def test_erc_permutation_equivariance():
    """置换资产 → 权重同置换（metamorphic）。"""

    perm = CORR3.iloc[[2, 0, 1], [2, 0, 1]]
    w0, wp = equal_risk_contribution(CORR3), equal_risk_contribution(perm)
    for s in CORR3.columns:
        assert abs(w0[s] - wp[s]) < 1e-8


def test_erc_positive_scale_invariance():
    """Σ→100·Σ 权重不变（相关空间尺度不变·metamorphic）。"""

    w0, ws = equal_risk_contribution(CORR3), equal_risk_contribution(CORR3 * 100.0)
    for s in CORR3.columns:
        assert abs(w0[s] - ws[s]) < 1e-10


def test_erc_single_and_empty():
    assert equal_risk_contribution(_mkcov([0.2], [[1.0]])) == {"A0": 1.0}
    assert equal_risk_contribution(pd.DataFrame()) == {}


# ════════════════════════════ fail-closed ══════════════════════════════════


def test_erc_singular_raises():
    """奇异 Σ（完全相关资产）→ raise（拒 clip/jitter/shrink）。"""

    sing = _mkcov([0.1, 0.2, 0.1], [[1, 0, 1], [0, 1, 0], [1, 0, 1]])
    with pytest.raises(ERCError):
        equal_risk_contribution(sing)


def test_erc_nonsymmetric_raises():
    cov = CORR3.copy()
    cov.iloc[0, 1] += 0.05
    with pytest.raises(ERCError):
        equal_risk_contribution(cov)


def test_erc_nonpositive_variance_raises():
    bad = CORR3.copy()
    bad.iloc[1, 1] = -0.04
    with pytest.raises(ERCError):
        equal_risk_contribution(bad)


def test_erc_nonfinite_raises():
    cov = CORR3.copy()
    cov.iloc[0, 0] = np.inf
    with pytest.raises(ERCError):
        equal_risk_contribution(cov)


def test_erc_nonconvergence_raises_no_garbage():
    """预算耗尽（CORR3 需 4 迭代·给 1）→ 循环真跑但未达 → raise（绝不返回未收敛迭代/等权兜底，
    不同于 mean_variance 的失败即返回等权）。max_iterations=0 走 <1 守卫同样 raise。"""

    with pytest.raises(ERCError):
        equal_risk_contribution(CORR3, max_iterations=1)
    with pytest.raises(ERCError):
        equal_risk_contribution(CORR3, max_iterations=0)


def test_erc_perfectly_correlated_raises():
    """完全相关（秩亏）→ raise，绝不静默返回等权。"""

    sing = _mkcov([0.15, 0.15], [[1, 1], [1, 1]])
    with pytest.raises(ERCError):
        equal_risk_contribution(sing)


# ════════════════════════════ 命门 binding ═════════════════════════════════


def test_pinned_fingerprint_matches_live_source():
    """指纹 tripwire：改 ERC 实现链任一环未重 pin → 本测试 RED（提醒刷新绑定）。"""

    assert sb.ERC_PINNED_FINGERPRINT == sb.erc_code_fingerprint()


def test_erc_binding_promotes_proof_backed():
    fp = sb.erc_code_fingerprint()
    decision = sb.verify_erc_consistency(pinned_code_hash=fp, current_code_hash=fp)
    assert decision.granted_label == PROOF_BACKED


def test_erc_dense_rc_and_closedform_checks_pass():
    binding = sb.build_erc_binding(sb.erc_code_fingerprint())
    assert sb.erc_dense_rc_check(binding=binding).result == "pass"
    assert sb.erc_closedform_check(binding=binding).result == "pass"


# ════════════════════════ MUTATION：种坏门必抓 ═════════════════════════════


def test_mutation_inverse_vol_as_erc_impl_rejected():
    """把错标 inverse-vol 当 ERC impl → dense-RC 门必 fail（N≥3 相关处）→ 命门拒 proof_backed。"""

    fp = sb.erc_code_fingerprint()
    binding = sb.build_erc_binding(fp)
    dense = sb.erc_dense_rc_check(inverse_volatility, binding=binding)
    assert dense.result == "fail"
    decision = sb.verify_erc_consistency(
        impl=inverse_volatility, pinned_code_hash=fp, current_code_hash=fp
    )
    assert decision.granted_label != PROOF_BACKED


def test_mutation_equal_weight_as_erc_impl_rejected():
    """等权当 ERC impl（相关结构下 RC 不等）→ dense-RC fail。"""

    fp = sb.erc_code_fingerprint()
    binding = sb.build_erc_binding(fp)

    def _equal_weight(cov):
        syms = list(cov.columns)
        n = len(syms)
        return {s: 1.0 / n for s in syms}

    assert sb.erc_dense_rc_check(_equal_weight, binding=binding).result == "fail"


def test_staleness_refuses_strong_label():
    """current 源指纹≠pinned（实现改了没重 pin）→ 强标签被拒。"""

    fp = sb.erc_code_fingerprint()
    decision = sb.verify_erc_consistency(pinned_code_hash=fp, current_code_hash="deadbeef")
    assert decision.granted_label != PROOF_BACKED


# ════════════════════ codex floor 修复回归（6 洞对抗测）═══════════════════════


def test_positivity_gate_isolates_true_signed_erc():
    """codex floor R2 #7：**真**签名 ERC 解（RC=1/N 精确·仅正负号不同）→ 唯 positivity 门能逮。

    对角 Σ 上 w_i=s_i/σ_i 归一 对任意符号 s 恒 RC=1/N（闭式）。此向量含负权重但 RC 精确相等——
    故 RC 门放行、**只有** positivity 门 catch 它。这才真隔离 positivity（旧测的向量非 ERC·被 RC 门
    逮·换成常数 positivity 也过 = fake-green）。断言：诊断的 N·r_i 全≈1（RC 门不 catch）、pos_flag=0。"""

    cov = _mkcov([0.1, 0.2, 0.4], [[1, 0, 0], [0, 1, 0], [0, 0, 1]])  # diagonal
    sig = np.array([0.1, 0.2, 0.4])
    s = np.array([1.0, -1.0, 1.0])  # 混合符号
    wv = (s / sig) / float((s / sig).sum())
    signed = {f"A{i}": float(wv[i]) for i in range(3)}
    # 前置：确是 ERC（RC=1/N 精确·否则 RC 门就逮了·测不到 positivity）+ 含负权重
    S = cov.values
    v = float(wv @ S @ wv)
    rc = wv * (S @ wv) / v
    assert float(np.max(np.abs(3 * rc - 1.0))) < 1e-9, "签名向量必须真 RC=1/N"
    assert any(x < 0 for x in signed.values()), "必须含负权重"
    # 诊断 [sum, pos_flag, N·r_i...]：N·r_i 全≈1（证 RC 门放行）、pos_flag=0（唯一 catch 点）
    diag = sb._erc_dense_rc_diagnostic(lambda _c: signed)(cov=cov)
    assert abs(diag[0] - 1.0) < 1e-9  # sum(w)=1
    assert diag[1] == 0.0  # pos_flag=0 ← 唯一判据
    assert all(abs(x - 1.0) < 1e-6 for x in diag[2:])  # N·r_i≈1 → RC 门不 catch
    # 全门实证：dense check（单对角 fixture）必 fail
    binding = sb.build_erc_binding(sb.erc_code_fingerprint())
    chk = sb.numerical_consistency_check(
        binding.binding_id,
        sb._erc_dense_rc_diagnostic(lambda _c: signed),
        sb._erc_dense_rc_oracle,
        [{"cov": cov}],
        tolerance=1e-6,
    )
    assert chk.result == "fail"


def test_erc_scalar_invalid_inputs_raise():
    """codex floor #3：N=1 快捷路径也全验——非有限/方差非正 → raise（不返回 {A:1.0}）。"""

    for bad in (0.0, -1.0, np.nan, np.inf):
        with pytest.raises(ERCError):
            equal_risk_contribution(pd.DataFrame([[bad]], index=["A"], columns=["A"]))
    assert equal_risk_contribution(pd.DataFrame([[0.04]], index=["A"], columns=["A"])) == {"A": 1.0}


def test_erc_complex_covariance_rejected():
    """codex floor #3：复数协方差 → raise（不丢弃虚部）。"""

    cov = pd.DataFrame([[1 + 1j, 0], [0, 1 + 0j]], index=["A", "B"], columns=["A", "B"])
    with pytest.raises(ERCError):
        equal_risk_contribution(cov)


def test_erc_nonsquare_rejected_only_true_empty_ok():
    """codex floor #3：1×0 非方阵 → raise；只有真 0×0 → {}。"""

    with pytest.raises(ERCError):
        equal_risk_contribution(pd.DataFrame(index=["A"]))  # 1×0
    assert equal_risk_contribution(pd.DataFrame()) == {}  # 0×0


def test_erc_asymmetry_masked_by_scale_rejected():
    """codex floor #4：强异方差下小尺度子块反对称——相对相关尺度对称性检查必抓（旧全局绝对容差漏）。"""

    cov = _mkcov([1e153, 1.0, 1.0], [[1, 0, 0], [0, 1, 0.316], [0, 0.316, 1]])
    cov.iloc[2, 1] = -0.316  # Σ_CB=-0.316 ≠ Σ_BC=0.316（子块反对称·被巨对角掩盖）
    with pytest.raises(ERCError):
        equal_risk_contribution(cov)


def test_erc_extreme_scale_legit_spd_ok():
    """codex floor #5：极端但合法有限 SPD（先缩放再对称化/相关化）不误拒——max-float 与极小方差都能解。"""

    big = _mkcov([1e154, 1e154], [[1, 0.3], [0.3, 1]])  # 方差≈1e308（接近 float max）
    wb = equal_risk_contribution(big)
    assert abs(sum(wb.values()) - 1.0) < 1e-9 and all(v > 0 for v in wb.values())
    tiny = _mkcov([1e-150, 1e-150], [[1, 0.3], [0.3, 1]])  # 方差≈1e-300
    wt = equal_risk_contribution(tiny)
    assert abs(sum(wt.values()) - 1.0) < 1e-9 and all(v > 0 for v in wt.values())


def test_erc_mixed_scale_preserves_small_correlation():
    """codex floor R3 #4：**混合**尺度 diag=(1e308,2e-15,2e-15)·R23=0.1——旧「除全局 max 方差」把
    2e-16 下溢成零、悄解对角化错问题（假 E_RC=0.0625）；逐元素归一 R_ij=Σ_ij/(σ_iσ_j) 保 0.1 相关
    → 真 E_RC≪1e-6。这才真复现 P0（旧均匀大/小矩阵测过不了这关·buggy 实现也能通过均匀测）。"""

    cov = pd.DataFrame(
        [[1e308, 0.0, 0.0], [0.0, 2e-15, 2e-16], [0.0, 2e-16, 2e-15]],
        index=["A", "B", "C"],
        columns=["A", "B", "C"],
    )
    w = equal_risk_contribution(cov)
    rc = _rc(cov, w)
    assert float(np.max(np.abs(3 * rc - 1.0))) < 1e-6  # 真 ERC（非旧假 0.0625）
    assert w["A"] < 1e-3  # 巨方差资产权重≈0


def test_erc_premature_stall_reproducer_converges():
    """codex floor R3#1/R4#3：**真**复现 premature-stall——旧无守卫停滞逻辑在 iter3 E_RC=30 就返回
    （→后置 raise·误拒可解 SPD）；当前守卫（仅 E_RC≤硬地板 1e-6 才停摆）续迭到 E_RC≈1.2e-10。
    旧无守卫逻辑过不了这关（这才是真回归·非旧良态矩阵 fake-green）。"""

    vols = [0.1272423271, 0.0283505396, 0.0827406687, 0.1036022098]
    corr = [
        [1.0, 0.2764606475, -0.9418626916, -0.8009557203],
        [0.2764606475, 1.0, -0.5772363798, -0.7527836813],
        [-0.9418626916, -0.5772363798, 1.0, 0.9218394268],
        [-0.8009557203, -0.7527836813, 0.9218394268, 1.0],
    ]
    cov = _mkcov(vols, corr)
    w = equal_risk_contribution(cov)
    assert float(np.max(np.abs(4 * _rc(cov, w) - 1.0))) < 1e-6


def test_erc_rc_tolerance_validation():
    """codex floor R4#2/R5#3：rc_tolerance 非正/非有限/**bool** → raise（0/负/NaN/inf/True/False 都拒·
    bool 是 int 子类会绕过 isinstance）。"""

    for bad in (0.0, -1e-8, float("nan"), float("inf"), True, False):
        with pytest.raises(ERCError):
            equal_risk_contribution(CORR3, rc_tolerance=bad)


def test_erc_loose_tolerance_not_false_rejected():
    """codex floor R5 #1：loose rc_tolerance（1.0）不得让 solver 早停于 E_RC>1e-6 而后置门误拒可解矩阵——
    求解目标夹到硬地板 min(rc_tolerance,1e-6)·仍返回 E_RC≤1e-6。"""

    w = equal_risk_contribution(CORR3, rc_tolerance=1.0)
    assert float(np.max(np.abs(3 * _rc(CORR3, w) - 1.0))) <= 1e-6


def test_erc_budget_exhaustion_within_floor_returns():
    """codex floor R6：紧 rc_tolerance + 小 max_iterations，预算耗尽但已达硬地板 → 返回（非 raise）——
    每条终止路径（收敛/停滞/线搜停滞/预算耗尽）对硬地板 1e-6 同一裁定；E_RC>1e-6 才真 raise。"""

    w = equal_risk_contribution(CORR3, rc_tolerance=1e-8, max_iterations=3)
    e = float(np.max(np.abs(3 * _rc(CORR3, w) - 1.0)))
    assert 1e-8 < e <= 1e-6  # 达硬地板但未达 1e-8 目标·仍返回（codex 实证 6.69e-8）
    with pytest.raises(ERCError):  # 真不收敛（E_RC>1e-6）仍 raise
        equal_risk_contribution(CORR3, rc_tolerance=1e-8, max_iterations=1)


def test_bridge_rebinding_trips_fingerprint(monkeypatch):
    """codex floor R2 #4：重绑 optimizers.equal_risk_contribution（断 re-export 桥）→ bridge_intact 翻
    False → 指纹变 → staleness 真触发（solver 真身在 _erc_solver·桥拿到的必须 is 真身）。"""

    import app.portfolio.optimizers as _opt

    fp0 = sb.erc_code_fingerprint()
    monkeypatch.setattr(_opt, "equal_risk_contribution", lambda cov: {})
    assert sb.erc_code_fingerprint() != fp0  # 桥断 → 指纹变
