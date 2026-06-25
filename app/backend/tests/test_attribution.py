"""因子收益归因 对抗测试。设计/推导见 dev/research/findings/dreaminate/factor-return-attribution.md。

门必抓：
- **命门加总恒等式**：Σ factor_contrib + specific == total_return 逐位（跨随机/多 seed）——contrib 算错则崩。
- **已知 β 恢复**：r=2F1+3F2+小噪 → β̂≈[2,3]、contrib≈[2ΣF1,3ΣF2]、R²≈1（真判别器）。
- **不假绿灯**：insufficient（n<K+2）/collinear（重复因子）→ 各自 status、不出假 β。
"""

from __future__ import annotations

import numpy as np
import pytest

from app.eval.attribution import AttributionResult, attribution_from_series, factor_return_attribution


def _factors(rng, n, k):
    return {f"f{i}": (rng.standard_normal(n) * 0.02).tolist() for i in range(k)}


def test_sum_identity_holds_exactly_random():
    """**命门**：Σ contrib_k + specific == total（逐位 1e-9）——跨多 seed/因子数随机。

    contrib（β·ΣF）与 specific（T·α+Σε）是**独立公式**，其和等于 total 仅当回归代数正确 → 真牙：
    contrib 用错聚合（如 mean 代 sum）或漏截距 → 此恒等式立崩。
    """
    for s in range(40):
        rng = np.random.default_rng(s)
        n = int(rng.integers(40, 300))
        k = int(rng.integers(1, 5))
        fac = _factors(rng, n, k)
        y = (rng.standard_normal(n) * 0.03).tolist()
        r = factor_return_attribution(y, fac)
        assert r.status == "ok"
        recomposed = sum(r.factor_contributions.values()) + r.specific_contribution
        assert abs(recomposed - r.total_return) <= 1e-9 * max(1.0, abs(r.total_return)) + 1e-12, \
            f"seed={s} 加总恒等式破：Σcontrib+specific={recomposed} ≠ total={r.total_return}"


def test_known_beta_recovery():
    """**已知 β 恢复（真判别器）**：r=2·F1+3·F2+小噪 → β̂≈[2,3]、contrib≈β·ΣF、R²≈1。"""
    rng = np.random.default_rng(7)
    n = 400
    f1 = rng.standard_normal(n) * 0.02
    f2 = rng.standard_normal(n) * 0.02
    y = 2.0 * f1 + 3.0 * f2 + rng.standard_normal(n) * 1e-4  # 小噪 → R²≈1
    r = factor_return_attribution(y.tolist(), {"f1": f1.tolist(), "f2": f2.tolist()})
    assert r.status == "ok"
    assert abs(r.betas["f1"] - 2.0) < 1e-2 and abs(r.betas["f2"] - 3.0) < 1e-2   # 恢复已知 β（松，含噪）
    # contrib == β̂·ΣF 精确定义一致（用估计 β̂ 非真值 2.0/3.0——β̂ 含估计误差）。
    assert abs(r.factor_contributions["f1"] - r.betas["f1"] * f1.sum()) < 1e-9
    assert abs(r.factor_contributions["f2"] - r.betas["f2"] * f2.sum()) < 1e-9
    assert r.r_squared > 0.999                                   # 因子几乎全解释
    assert abs(r.specific_contribution) < 1e-2                   # 特异≈0（小噪）


def test_insufficient_sample_abstains():
    """样本不足 n<K+2 → insufficient、不出 β（不假绿灯：先验断言未经检验）。"""
    rng = np.random.default_rng(1)
    r = factor_return_attribution((rng.standard_normal(4) * 0.02).tolist(), _factors(rng, 4, 3))
    assert r.status == "insufficient" and r.betas == {} and not np.isfinite(r.alpha)
    # 恒等式在 abstain 下仍闭合（specific=total）。
    assert r.specific_contribution == r.total_return


def test_collinear_factors_abstain():
    """共线（重复因子列）→ collinear、不报不可识别 β（绝不把噪声 β 当真）。"""
    rng = np.random.default_rng(2)
    n = 100
    f = (rng.standard_normal(n) * 0.02).tolist()
    r = factor_return_attribution((rng.standard_normal(n) * 0.03).tolist(), {"a": f, "b": f})  # a==b 共线
    assert r.status == "collinear" and r.betas == {}


def test_nonfinite_rows_dropped_and_disclosed():
    """非有限行整行剔除并披露（n_obs 反映、warning 提示）。"""
    rng = np.random.default_rng(3)
    n = 60
    y = (rng.standard_normal(n) * 0.02)
    f1 = (rng.standard_normal(n) * 0.02)
    y[5] = np.nan
    f1[9] = np.inf
    r = factor_return_attribution(y.tolist(), {"f1": f1.tolist()})
    assert r.status == "ok" and r.n_obs == n - 2
    assert any("非有限" in w for w in r.warnings)


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="长度|等长"):
        factor_return_attribution([0.01, 0.02, 0.03], {"f1": [0.01, 0.02]})


def test_no_factors_all_specific():
    """K=0（无因子）→ 全部归特异、R²=nan、不崩。"""
    rng = np.random.default_rng(4)
    y = (rng.standard_normal(50) * 0.02).tolist()
    r = factor_return_attribution(y, {})
    assert r.status == "ok" and r.factor_contributions == {}
    assert abs(r.specific_contribution - r.total_return) < 1e-9


def test_to_dict_json_safe():
    import json
    rng = np.random.default_rng(5)
    r = factor_return_attribution((rng.standard_normal(80) * 0.02).tolist(), _factors(rng, 80, 2))
    json.dumps(r.to_dict())
    assert isinstance(r, AttributionResult)


# ── attribution_from_series：ts 键对齐（消除手工位置 misalign 假绿灯）─────────────────
def test_attribution_from_series_aligns_by_ts_not_insertion_order():
    """**牙**：按 ts 键对齐非插入顺序。组合 dict 逆序插入、因子正序 → 结果须等于 ts-排序后的位置归因。

    MUT（若 helper 改成按插入顺序 zip）→ 组合逆序与因子正序错位 → 结果不等，断言崩。
    """
    ts = [f"d{i}" for i in range(6)]
    p = {t: float(v) for t, v in zip(ts, [0.01, -0.02, 0.03, 0.00, 0.04, -0.01])}
    f = {t: float(v) for t, v in zip(ts, [0.02, -0.01, 0.02, 0.01, 0.03, -0.02])}
    # 组合与因子 **各自不同的非排序插入顺序**：correct helper 按 ts 键查值对齐两侧；若误按各自插入顺序
    # 取值（独立 zip）则组合(逆序)与因子(乱序)错位 → β/contrib 变 → 本测红。
    port_reversed = {t: p[t] for t in reversed(ts)}
    fac_shuffled = {t: f[t] for t in ["d2", "d5", "d0", "d3", "d1", "d4"]}
    out = attribution_from_series(port_reversed, {"f": fac_shuffled})
    ref = factor_return_attribution([p[t] for t in ts], {"f": [f[t] for t in ts]})  # ts-排序基准
    assert out.status == "ok" and ref.status == "ok"
    assert abs(out.total_return - ref.total_return) < 1e-12
    assert abs(out.betas["f"] - ref.betas["f"]) < 1e-12
    assert abs(out.factor_contributions["f"] - ref.factor_contributions["f"]) < 1e-12


def test_attribution_from_series_inner_join_drops_noncommon_ts():
    """内连接：仅保留组合与所有因子都覆盖的 ts；非公共 ts 丢弃（不臆造对齐）。"""
    p = {"d1": 0.01, "d2": 0.02, "d3": 0.03, "dX": 0.99}   # dX 因子缺
    f = {"d1": 0.02, "d2": 0.01, "d3": 0.02, "dY": 0.88}   # dY 组合缺
    out = attribution_from_series(p, {"f": f})
    assert out.n_obs == 3                                   # 仅 d1/d2/d3 公共
    assert out.status == "ok"


def test_attribution_from_series_accepts_tuple_sequences():
    """接受 [(ts, val)] 序列形式（factor_return_series 的产物可直接喂）。"""
    p = [("d1", 0.01), ("d2", 0.02), ("d3", 0.03), ("d4", -0.01)]
    f = [("d1", 0.02), ("d2", -0.01), ("d3", 0.02), ("d4", 0.01)]
    out = attribution_from_series(p, {"f": f})
    ref = factor_return_attribution([0.01, 0.02, 0.03, -0.01], {"f": [0.02, -0.01, 0.02, 0.01]})
    assert out.status == "ok" and abs(out.total_return - ref.total_return) < 1e-12


def test_attribution_from_series_insufficient_when_few_common():
    """公共 ts < K+2 → 底层 insufficient（不出假 β·不假绿灯）。"""
    p = {"d1": 0.01, "d2": 0.02}                            # 仅 2 公共，K=1 需 ≥3
    f = {"d1": 0.02, "d2": 0.01}
    out = attribution_from_series(p, {"f": f})
    assert out.status == "insufficient" and out.betas == {}
