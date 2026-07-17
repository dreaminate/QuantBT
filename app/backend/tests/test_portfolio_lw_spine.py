"""真 Ledoit-Wolf solver 对抗测试 + canonical 命门绑定（金融数学 kernel P0-A #8 续）。

覆盖：solver correctness（impl sklearn δ* == 手写 LW-2004 oracle δ*·独立路径·SPD·regime）、诚实命名
（constant_shrinkage 固定-α·ledoit_wolf_shrinkage DeprecationWarning shim）、fail-closed（非法 returns/
T<2/μ=0/非有限即 raise·无静默兜底）、命门（promote proof_backed·MUTATION 固定-α 必被逮·staleness·
pinned-fingerprint tripwire）。数学口径经 codex/GPT-5.6-sol 授权裁决（classic δ*=min(1,π̂/Tγ̂)·不塞 ρ̂）。
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from app.lineage.spine import PROOF_BACKED
from app.portfolio import _lw_shrinkage as _lw
from app.portfolio import hrp_shrinkage_binding as lwb
from app.portfolio._lw_shrinkage import (
    CovarianceEstimationError,
    constant_shrinkage,
    ledoit_wolf,
)
from app.portfolio.hrp_audit import is_near_singular, optimize_hrp_safe


def _factor_returns(t_obs: int, n: int, amp: float, seed: int) -> np.ndarray:
    idx = np.arange(t_obs).reshape(-1, 1)
    cols = np.arange(n).reshape(1, -1)
    common = np.sin((idx + seed) * 0.37) * np.cos(cols * 1.3 + seed)
    idio = np.cos((idx + seed) * 1.1 + cols * 2.1)
    return (amp * common + 0.5 * idio) * 0.01


def _oracle_delta(returns: np.ndarray) -> float:
    """手写 LW-2004 δ*（独立 outer-product 路径·不经 sklearn）。"""

    delta, _sig, _s, _mu = lwb._lw_delta_oracle(returns)
    return delta


# ════════════════════════════ solver correctness ═══════════════════════════


def test_ledoit_wolf_matches_handrolled_oracle():
    """真 impl（sklearn）δ* == 手写 LW-2004 oracle δ* 到机器精度（独立代码路径·correctness+独立性）。"""

    for r in (_factor_returns(30, 4, 1.5, 1), _factor_returns(20, 40, 0.3, 5), _factor_returns(2000, 4, 3.0, 9)):
        res = ledoit_wolf(r)
        assert abs(res.shrinkage - _oracle_delta(r)) < 1e-12
        assert 0.0 <= res.shrinkage <= 1.0


def test_ledoit_wolf_data_driven_not_fixed():
    """δ* 数据驱动·随 regime 变（非固定 α）：不同 fixture 得不同 δ*。"""

    d_corr = ledoit_wolf(_factor_returns(30, 4, 1.5, 1)).shrinkage
    d_high = ledoit_wolf(_factor_returns(20, 40, 0.3, 5)).shrinkage
    d_low = ledoit_wolf(_factor_returns(2000, 4, 3.0, 9)).shrinkage
    assert len({round(d_corr, 4), round(d_high, 4), round(d_low, 4)}) == 3  # 三 regime 三 δ*
    assert d_high > d_low  # 此对 T<N(δ*=0.089) > 大T(δ*=0.0004)·具体数值·非「T<N⇒δ*→1」普适律（codex floor2 #4）


def test_ledoit_wolf_spd_including_rank_deficient():
    """Σ* 在 δ*>0 时严格 SPD（Cholesky 过）·含 T<N 秩亏 S。"""

    for r in (_factor_returns(30, 4, 1.5, 1), _factor_returns(20, 40, 0.3, 5)):
        res = ledoit_wolf(r)
        np.linalg.cholesky(res.covariance)  # δ*>0 → SPD·不抛即过
        assert res.shrinkage > 0.0


def test_ledoit_wolf_scale_invariant_delta():
    """δ* 尺度不变：returns→100·returns 得同 δ*（covariance 乘 scale²）。"""

    r = _factor_returns(30, 4, 1.5, 1)
    d0, d1 = ledoit_wolf(r).shrinkage, ledoit_wolf(r * 100.0).shrinkage
    assert abs(d0 - d1) < 1e-10


# ════════════════════════════ 诚实命名 ══════════════════════════════════════


def test_constant_shrinkage_is_honest_fixed_alpha():
    """constant_shrinkage = 固定-α (1-α)cov+α·tr/N·I（非数据驱动）。"""

    cov = np.array([[1.0, 0.9], [0.9, 1.0]])
    out = constant_shrinkage(cov, alpha=0.3)
    expected = 0.7 * cov + 0.3 * (np.trace(cov) / 2) * np.eye(2)
    assert np.allclose(out, expected)


def test_ledoit_wolf_shrinkage_shim_deprecated():
    """旧错标名 ledoit_wolf_shrinkage 仍可 direct import·发 DeprecationWarning·=constant_shrinkage·**出 __all__**。"""

    cov = np.array([[1.0, 0.9], [0.9, 1.0]])
    with pytest.warns(DeprecationWarning):
        legacy = _lw.ledoit_wolf_shrinkage(cov, shrinkage=0.2)
    assert np.allclose(legacy, constant_shrinkage(cov, alpha=0.2))
    from app.portfolio import hrp_audit

    assert "ledoit_wolf_shrinkage" not in hrp_audit.__all__
    assert "ledoit_wolf" in hrp_audit.__all__ and "constant_shrinkage" in hrp_audit.__all__


# ════════════════════════════ fail-closed ══════════════════════════════════


def test_ledoit_wolf_fail_closed():
    """非法 returns → raise（绝不静默兜底/用坏协方差）。"""

    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(np.array([[0.01, 0.02]]))  # T<2
    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(np.array([0.01, 0.02, 0.03]))  # 1D
    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(np.array([[np.nan, 0.01], [0.01, 0.02], [0.0, 0.01]]))  # 非有限
    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(np.array([[1 + 1j, 0], [0, 1]]))  # 复数
    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(np.ones((5, 3)) * 0.01)  # μ=0（中心化后全零）
    with pytest.raises(CovarianceEstimationError):
        constant_shrinkage(np.eye(3), alpha=1.5)  # α 越界
    with pytest.raises(CovarianceEstimationError):
        constant_shrinkage(np.eye(3), alpha=True)  # bool


# ════════════════════════════ 命门 binding ═════════════════════════════════


def test_pinned_code_fingerprint_matches_repository_chain():
    """Commit tripwire（codex 裁 C+·`lw-code-v2`）：已审查的 LW 源 / re-export 链 / 运行时 solver 身份未漂移。

    **诚实契约**：在所有受支持且能读到仓库源码的环境**无条件成立·不得 skip**——指纹已去依赖版本 →
    **commit/source 耦合**（正确耦合）·非环境耦合。它**只**证「审查过的源与绑定身份没变」；**不**证
    sklearn 数学正确·**不**证整个运行环境可复现（那由每环境现场跑的 oracle 对账 + config_ref
    provenance 披露承担）。**本测试正是 CI 逮到的 defect 的回归**：旧 v1 指纹含 sklearn/numpy 版本 +
    requirements 无上界 → 异环境 live≠pinned 必红（本机 a0e2c805 vs CI 9f08cc6b）。"""

    assert lwb.LW_PINNED_FINGERPRINT == lwb.lw_code_fingerprint()


def test_lw_binding_promotes_proof_backed():
    """走**生产默认路径**（codex 裁）：不自注入 live 指纹——自注入会绕过 pinned 常量·只靠旁测间接兜底=假绿。"""

    decision = lwb.verify_lw_consistency()  # 默认 = binding 用 pinned·current 用 live（真产线比对）
    assert decision.granted_label == PROOF_BACKED


def test_code_fingerprint_is_environment_independent(monkeypatch):
    """**CI 逮到的 defect 的直接回归**（codex 裁 C+）：指纹不得依赖 sklearn/numpy 版本。

    v1 指纹哈希 `sklearn.__version__`+`numpy.__version__`，而 requirements 无上界（`numpy>=1.26`/
    `scikit-learn>=1.5`）→ CI 全新 pip install 解析出异版本（实装 sklearn1.9.0/numpy2.5.1）→
    live(`9f08cc6b`)≠pinned(`a0e2c805`) → pinned 测试在任何非本机环境必红。v2 只哈希源+绑定身份 →
    版本变而指纹恒定。**若把版本串塞回指纹·本测试即 RED**（种坏门必抓）。"""

    import numpy
    import sklearn

    fp0 = lwb.lw_code_fingerprint()
    monkeypatch.setattr(sklearn, "__version__", "9.9.9-fake-ci")
    monkeypatch.setattr(numpy, "__version__", "8.8.8-fake-ci")
    assert lwb.lw_code_fingerprint() == fp0  # 依赖版本变 → 指纹恒定（环境无关·commit/source 耦合）
    assert lwb.verify_lw_consistency().granted_label == PROOF_BACKED  # 异版本环境仍走通产线路径


def test_lw_consistency_check_passes_real():
    binding = lwb.build_lw_binding(lwb.lw_code_fingerprint())
    assert lwb.lw_consistency_check(binding=binding).result == "pass"


# ════════════════════════ MUTATION：种坏门必抓 ═════════════════════════════


def test_mutation_fixed_alpha_as_lw_rejected():
    """把固定-α 当 LW impl（原错标·optimize_hrp_safe 曾用 0.3）→ oracle δ*≠α → dense fail → 命门拒 proof_backed。"""

    fp = lwb.lw_code_fingerprint()
    binding = lwb.build_lw_binding(fp)

    for alpha in (0.2, 0.3):
        def _mut(returns, s, mu, _a=alpha):
            return constant_shrinkage(s, alpha=_a), _a

        assert lwb.lw_consistency_check(_mut, binding=binding).result == "fail"
        decision = lwb.verify_lw_consistency(impl=_mut, pinned_code_hash=fp, current_code_hash=fp)
        assert decision.granted_label != PROOF_BACKED


def test_staleness_refuses_strong_label():
    fp = lwb.lw_code_fingerprint()
    decision = lwb.verify_lw_consistency(pinned_code_hash=fp, current_code_hash="deadbeef")
    assert decision.granted_label != PROOF_BACKED


# ════════════════════ codex floor2 洞收口（4 findings 回归）════════════════════


def test_ledoit_wolf_delta_zero_singular_raises():
    """δ*=0 且 S 秩亏 → Σ*=S 非 SPD → fail-closed raise（codex floor2 #1·补 `if δ*>0` 才查 Cholesky 的洞）。

    T=2,N=3：中心化后两行对映（x₂=−x₁）→ S=x₁x₁ᵀ 秩1 奇异 → LW π̂=0 → δ*=0 → 无收缩 → 秩亏 → raise。
    旧码只在 δ*>0 时查 Cholesky·会静默返回特征值含负的非 SPD 协方差（违 fail-closed SPD 契约）。"""

    r = np.array([[0.01, -0.02, 0.03], [-0.01, 0.02, -0.03]])
    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(r)


def test_ledoit_wolf_tiny_scale_underflow_raises():
    """returns 幅度 ~1e-200 → scale² 下溢成 0.0 → fail-closed raise（不静默返回零协方差·codex floor2 #1）。"""

    r = np.array([[0.0, 1e-200, 2e-200], [1e-200, 0.0, 1e-200], [2e-200, 1e-200, 0.0]])
    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(r)


def test_ledoit_wolf_covariance_rescales_by_scale_squared():
    """metamorphic：returns×k → Σ* ×k²（协方差二阶齐次·scale-safe rescale 精确·codex floor2 #1 请求）。"""

    r = _factor_returns(30, 4, 1.5, 1)
    c0 = ledoit_wolf(r).covariance
    c1 = ledoit_wolf(r * 10.0).covariance
    assert np.allclose(c1, c0 * 100.0, rtol=1e-9)


def test_module_rebind_solver_trips_staleness(monkeypatch):
    """模块级重绑 solver（`_lw.LedoitWolf = OAS`·源码不变）→ 指纹变 → staleness（codex floor2 #3）。

    旧指纹 `code_fingerprint(*chain)` 只哈希函数体·漏此重绑（δ 从 0.052→0.113 而指纹不变）；
    改 whole-module 源 + 运行时 `solver_binding_intact` 身份双查后·重绑即触发 staleness 拒 proof_backed。"""

    from sklearn.covariance import OAS

    fp_before = lwb.lw_code_fingerprint()
    monkeypatch.setattr(_lw, "LedoitWolf", OAS)
    fp_after = lwb.lw_code_fingerprint()
    assert fp_after != fp_before  # 身份变 → 指纹变
    decision = lwb.verify_lw_consistency(pinned_code_hash=fp_before, current_code_hash=fp_after)
    assert decision.granted_label != PROOF_BACKED  # 漂移 → staleness 拒强标签


def test_optimize_hrp_safe_rejects_invalid_returns():
    """非法 returns 不得伪装成 inverse_volatility 权重（codex floor2 #2·input-contract 违反 → raise·非静默降级）。"""

    syms = ["A", "B", "C"]
    with pytest.raises(CovarianceEstimationError):  # NaN
        optimize_hrp_safe(np.array([[0.01, np.nan, 0.02], [0.01, 0.02, 0.03]]), syms)
    with pytest.raises(CovarianceEstimationError):  # T=1
        optimize_hrp_safe(np.array([[0.01, 0.02, 0.03]]), syms)
    with pytest.raises(CovarianceEstimationError):  # 全零（零方差·μ=0 传播·不吞成 {1/3,1/3,1/3}）
        optimize_hrp_safe(np.zeros((10, 3)), syms)
    with pytest.raises(CovarianceEstimationError):  # 复数
        optimize_hrp_safe(np.array([[1 + 1j, 0, 0], [0, 1, 0], [0, 0, 1]]), syms)


def test_optimize_hrp_safe_prevalidates_before_shortcircuit_paths():
    """入口 prevalidation 独有守的两条路（ledoit_wolf 内校验够不着·codex floor2 #2）：

    ① 单资产分支——非法 returns 也须先过契约（旧码 n==1 直接返回 100%·不看 returns）；
    ② `enable_shrinkage_fallback=False`——非法 returns 够不到 ledoit_wolf·旧码会 inverse_volatility 出 NaN 权重。
    这两路只有入口 `_validate_returns` 拦得住——若删 prevalidation·本测试即 RED（种坏门必抓）。"""

    # ① 单资产 + 非有限 returns（T=2 过 T 门·靠 finite 门拦）→ raise（非静默 {A:1.0}）
    with pytest.raises(CovarianceEstimationError):
        optimize_hrp_safe(np.array([[0.01], [np.nan]]), ["A"])
    # ② fallback 关 + 非法 returns → raise（非 inverse_volatility NaN 权重）
    with pytest.raises(CovarianceEstimationError):
        optimize_hrp_safe(
            np.array([[0.01, np.nan, 0.02], [0.01, 0.02, 0.03]]),
            ["A", "B", "C"],
            enable_shrinkage_fallback=False,
        )


def test_optimize_hrp_safe_corr1_reaches_hrp_shrunk():
    """合法 corr=1 近奇异 → LW 正则化后**精确达 hrp_shrunk**（finite 正 δ*）·非 raise·非放宽三选一（codex floor4 #5 收紧）。"""

    rng = np.random.RandomState(0)
    base = rng.randn(252) * 0.01
    returns = np.column_stack([base.copy() for _ in range(5)])  # corr=1 合法数据
    result = optimize_hrp_safe(returns, [f"Y{i}" for i in range(5)], singularity_threshold=1e-4)
    assert result.fallback_used == "hrp_shrunk"  # 精确断言（不变量：corr=1 经 LW 达 hrp_shrunk）
    assert np.isfinite(result.lw_shrinkage) and result.lw_shrinkage > 0.0  # 数据驱动正 δ*
    assert all(np.isfinite(w) for w in result.weights.values())


# ════════════════════ codex floor3 洞收口（4 findings 回归）════════════════════


def test_ledoit_wolf_extreme_scale_no_inf():
    """极端尺度 returns → Σ* 对称化不得溢出成 inf（codex floor3 #1·`0.5*(cov+cov.T)` 中间 2× 溢出洞）。

    [[-1e154],[1e154]]：旧码 cov+cov.T=2e308 溢出 → Σ*=inf·Cholesky 不抛。overflow-safe 对称化后返回有限 [1e308]；
    更极端 1e160 → scale²/分解上溢 → fail-closed raise（绝不返回 inf 协方差）。"""

    res = ledoit_wolf(np.array([[-1e154], [1e154]]))
    assert np.all(np.isfinite(res.covariance))  # 无 inf 泄漏
    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(np.array([[-1e160], [1e160]]))


def test_optimize_hrp_safe_zero_variance_short_circuits_raise():
    """全零/常数 returns 经单资产分支 / fallback 关路也须 raise（codex floor3 #2·μ=0 不伪装成权重）。"""

    with pytest.raises(CovarianceEstimationError):  # 单资产全零
        optimize_hrp_safe(np.zeros((10, 1)), ["A"])
    with pytest.raises(CovarianceEstimationError):  # 单资产常数（中心化后零方差）
        optimize_hrp_safe(np.full((10, 1), 5.0), ["A"])
    with pytest.raises(CovarianceEstimationError):  # 全零 + fallback 关（够不到 ledoit_wolf 内 μ=0 门）
        optimize_hrp_safe(np.zeros((10, 3)), ["A", "B", "C"], enable_shrinkage_fallback=False)


def test_is_near_singular_fail_closed_on_nonfinite():
    """is_near_singular 非有限协方差 fail-closed 视奇异（codex floor3 #3·seam 直测·非当健康）。

    codex floor4 #5：极端 returns 经 optimize_hrp_safe 归一后不再溢出（尺度不变·见 scale_invariant 测）·
    故此处直测 guard seam（非靠 optimize_hrp_safe 触发·后者归一后 np.cov 不再产 inf）。"""

    assert is_near_singular(np.array([[np.inf]]))[0] is True
    assert is_near_singular(np.array([[np.nan]]))[0] is True
    assert is_near_singular(np.array([[np.inf, 0.0], [0.0, 1.0]]))[0] is True


def test_optimize_hrp_safe_rejects_duplicate_symbols():
    """重复 symbol → dict 塌缩·权重不和 1 → fail-closed raise（codex floor3 #4）·正常+奇异数据都拦。"""

    rng = np.random.RandomState(0)
    with pytest.raises(CovarianceEstimationError):  # 正常数据
        optimize_hrp_safe(rng.randn(50, 2) * 0.01, ["A", "A"])
    base = rng.randn(50) * 0.01
    with pytest.raises(CovarianceEstimationError):  # 奇异数据（corr=1）
        optimize_hrp_safe(np.column_stack([base, base]), ["A", "A"], singularity_threshold=1e-4)


# ════════════════════ codex floor4 洞收口（5 findings 回归）════════════════════


def test_ledoit_wolf_representable_large_scale_returns():
    """可表示的大尺度 Σ* 不得被误拒（codex floor4 #1）。

    确定性 fixture：max|elem|=1.35e154 → **scale²=1.8225e308 溢出 inf**（旧 `sq` 预门会 raise），但 cov_dim 元素<1·
    逐元素 `(cov_dim*scale)*scale` 保持有限（cov_max≈1.03e308<max_float·δ*=1·SPD）→ 应返回。真不可表示（×1e160·
    乘积/分解溢出）仍 fail-closed raise。"""

    fixture = np.array([[1.0, 0.5], [-1.0, -0.5], [0.6, -0.8], [-0.6, 0.8]])
    res = ledoit_wolf(fixture * 1.35e154)  # scale²=inf 但结果可表示
    assert np.all(np.isfinite(res.covariance))  # 可表示 → 返回·非误 raise
    np.linalg.cholesky(res.covariance)  # SPD（不抛即过）
    with pytest.raises(CovarianceEstimationError):
        ledoit_wolf(fixture * 1e160)  # 真不可表示 → raise


def test_optimize_hrp_safe_globally_scale_invariant():
    """HRP 权重对正全局尺度不变（codex floor4 #2·根修=无量纲 xn=xc/cscale 上计算）：

    ×1e154（旧 raw np.cov→inf 误 raise）/ ×1e-160（旧 vol 触 1e-12 地板→伪等权 {0.25×4}）
    须与原尺度得**恒等权重 + 同 fallback**。"""

    rng = np.random.RandomState(0)
    base = rng.randn(120, 4) * 0.01
    syms = [f"A{i}" for i in range(4)]
    w0 = optimize_hrp_safe(base, syms)
    w_big = optimize_hrp_safe(base * 1e154, syms)
    w_small = optimize_hrp_safe(base * 1e-160, syms)
    for s in syms:
        assert abs(w0.weights[s] - w_big.weights[s]) < 1e-9
        assert abs(w0.weights[s] - w_small.weights[s]) < 1e-9
    assert w0.fallback_used == w_big.fallback_used == w_small.fallback_used == "hrp"


def test_optimize_hrp_safe_rejects_bad_symbol_identity():
    """symbol 身份 fail-closed（codex floor4 #3）：None/""/纯空白/不可哈希 → CovarianceEstimationError（非 dict 键塌缩/raw TypeError）。"""

    rng = np.random.RandomState(0)
    g = rng.randn(50, 2) * 0.01
    for bad in ([None, "B"], ["", "B"], ["  ", "B"], [["x"], "B"]):
        with pytest.raises(CovarianceEstimationError):
            optimize_hrp_safe(g, bad)


def test_optimize_hrp_safe_fallback_labeled_inverse_volatility():
    """奇异降级标 **inverse_volatility**·绝非错标 risk_parity（codex floor4 #4·同 ERC risk_parity→inverse_vol 一类·
    对角反波动率不含相关性≠真 ERC）。fallback 关 + corr=1 奇异 → 走 inverse_volatility 降级。"""

    rng = np.random.RandomState(3)
    base = rng.randn(252) * 0.01
    singular = np.column_stack([base] * 3)  # corr=1 奇异
    res = optimize_hrp_safe(
        singular, ["X", "Y", "Z"], singularity_threshold=1e-4, enable_shrinkage_fallback=False
    )
    assert res.fallback_used == "inverse_volatility"  # 诚实名·非旧错标 "risk_parity"
    assert all(np.isfinite(w) for w in res.weights.values())


# ════════════════════ codex floor5 洞收口（5 findings 回归）════════════════════


def test_ledoit_wolf_scale_safe_centering_translation_invariant():
    """中心化对大常数平移不变（codex floor5 #1）：常数列 0 vs 1e308 → 同结果·naive `r.mean` 会 sum 溢出 inf 误 raise。

    scale-safe `(r-r[0])-mean(r-r[0])` ≡ r-mean(r) 但不 sum 大常数——常数列（零方差）平移到 1e308 仍零方差·δ* 恒等。"""

    base = np.array([[0.0, 1.0], [0.0, 2.0], [0.0, 3.0], [0.0, 2.5]])
    shifted = np.array([[1e308, 1.0], [1e308, 2.0], [1e308, 3.0], [1e308, 2.5]])
    rb, rs = ledoit_wolf(base), ledoit_wolf(shifted)
    assert abs(rb.shrinkage - rs.shrinkage) < 1e-12  # 平移不变（旧 naive r.mean→inf 会 raise）
    assert np.allclose(rb.covariance, rs.covariance)


def test_optimize_hrp_safe_fail_closed_on_extreme_dynamic_range():
    """列间尺度差过大（全局归一把小尺度列冲成 vol 地板下）→ fail-closed raise·非伪权重（codex floor5 #2）。"""

    rng = np.random.RandomState(0)
    cols = np.column_stack(
        [rng.randn(120) * 1e154, rng.randn(120) * 1e-171, rng.randn(120) * 2e-171]
    )
    with pytest.raises(CovarianceEstimationError):
        optimize_hrp_safe(cols, ["A", "B", "C"])


def test_optimize_hrp_safe_exposes_normalization_scale():
    """诊断诚实（codex floor5 #3）：min_eigval/condition_number 在无量纲空间·HRPResult 暴露 normalization_scale=cscale。"""

    rng = np.random.RandomState(0)
    res = optimize_hrp_safe(rng.randn(120, 4) * 0.01, [f"A{i}" for i in range(4)])
    assert np.isfinite(res.normalization_scale) and res.normalization_scale > 0.0
    assert "normalization_scale" in res.to_dict()


def test_optimize_hrp_safe_rejects_whitespace_symbol_aliases():
    """首尾空白 symbol 别名（"A" vs "A "）不得当不同资产（dict 键 alias 塌缩风险）→ fail-closed raise（codex floor5 #4）。"""

    rng = np.random.RandomState(0)
    g = rng.randn(50, 2) * 0.01
    for bad in (["A", "A "], ["A", " A "], ["A ", "B"], [" A", "B"]):
        with pytest.raises(CovarianceEstimationError):
            optimize_hrp_safe(g, bad)
