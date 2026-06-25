"""因子归因 **消费侧报告构建器** 对抗测试（卡 e4496023）。

绑定 math 件命门到端点输出 + 守不假绿灯（§0/§13 信任层）：
- **命门加总恒等式端到端**：报告 identity.holds 真、residual≈0（跨多 seed）——consume 层若误聚合则崩。
- **abstain 不出假 β**：insufficient / collinear → evidence_state 落 abstain 家族、betas 空。
- **低 R² 不标已归因**（核心 MUT）：status=ok 但解释占比低 → evidence_state "specific_driven"、
  **绝不** "factor_explained"。种坏：若把低 R² 渲成已归因，此门立红。
- JSON-safe（nan→None）+ note R7 措辞门（无绝对化禁词）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.eval.attribution_report import build_factor_attribution_report

# R7 措辞门禁词（镜像前端 harness.FORBIDDEN_VERDICT_WORDS，后端 note 同守，防绕过）。
_FORBIDDEN = ["可信", "安全", "保证", "排除过拟合", "可复现", "组织独立"]


def _factors(rng, n, k):
    return {f"f{i}": (rng.standard_normal(n) * 0.02).tolist() for i in range(k)}


def test_sum_identity_end_to_end_holds():
    """**命门端到端**：报告 identity.residual≈0 且 holds=True，跨多 seed/因子数。

    consume 层独立重算 Σcontrib+specific 与 total 比对 → 真牙：报告若误传 / 误聚合贡献则 residual 爆。
    """
    for s in range(30):
        rng = np.random.default_rng(s)
        n = int(rng.integers(40, 240))
        k = int(rng.integers(1, 5))
        rep = build_factor_attribution_report(
            (rng.standard_normal(n) * 0.03).tolist(), _factors(rng, n, k)
        )
        assert rep["status"] == "ok"
        assert rep["identity"]["holds"] is True, f"seed={s} 加总恒等式破：{rep['identity']}"
        assert abs(rep["identity"]["residual"]) <= 1e-9 * max(1.0, abs(rep["total_return"])) + 1e-12
        # 报告自重组与 math total 一致（独立校验，不信任单一字段）。
        recomposed = sum(v for v in rep["factor_contributions"].values()) + rep["specific_contribution"]
        assert abs(recomposed - rep["total_return"]) <= 1e-9 * max(1.0, abs(rep["total_return"])) + 1e-12


def test_known_beta_high_r2_marks_factor_explained():
    """已知 β 高解释 → factor_explained、贡献≈β·ΣF、identity 闭合（真判别器）。"""
    rng = np.random.default_rng(7)
    n = 400
    f1 = rng.standard_normal(n) * 0.02
    f2 = rng.standard_normal(n) * 0.02
    y = 2.0 * f1 + 3.0 * f2 + rng.standard_normal(n) * 1e-4  # R²≈1
    rep = build_factor_attribution_report(
        y.tolist(), {"f1": f1.tolist(), "f2": f2.tolist()},
        factor_set_label="style-2", return_basis="raw", regression_window="full",
    )
    assert rep["status"] == "ok" and rep["evidence_state"] == "factor_explained"
    assert rep["r_squared"] > 0.999
    assert abs(rep["factor_contributions"]["f1"] - rep["betas"]["f1"] * f1.sum()) < 1e-8
    assert rep["identity"]["holds"] is True
    # 方法学原样回显（不替拍）。
    assert rep["methodology"]["factor_set_label"] == "style-2"
    assert rep["methodology"]["return_basis"] == "raw"
    assert rep["methodology"]["regression_window"] == "full"


def test_low_r2_marks_specific_driven_not_explained():
    """**不假绿灯核心 MUT**：组合与因子无关 → 低 R² → specific_driven，**绝不** factor_explained。

    种坏门：若 consume 层把低解释占比包装成「已归因」(factor_explained)，此断言立红。
    """
    rng = np.random.default_rng(11)
    n = 300
    # 组合 = 独立噪声，与因子不相关 → 因子几乎不解释 → R²≈0。
    y = (rng.standard_normal(n) * 0.03).tolist()
    fac = _factors(rng, n, 2)
    rep = build_factor_attribution_report(y, fac, low_explained_floor=0.30)
    assert rep["status"] == "ok"
    assert rep["r_squared"] < 0.30
    assert rep["evidence_state"] == "specific_driven"        # 诚实：特异驱动
    assert rep["evidence_state"] != "factor_explained"       # 绝不渲染成已归因绿
    assert rep["identity"]["holds"] is True                  # 恒等式仍闭合（特异吃掉未解释部分）
    assert "特异" in rep["note"]                              # 措辞诚实点名特异驱动（不冒充已归因）


def test_insufficient_abstains_no_fake_beta():
    """样本不足 → evidence_state insufficient、betas 空、不出假 β（恒等式仍闭合）。"""
    rng = np.random.default_rng(1)
    rep = build_factor_attribution_report(
        (rng.standard_normal(4) * 0.02).tolist(), _factors(rng, 4, 3)
    )
    assert rep["status"] == "insufficient" and rep["evidence_state"] == "insufficient"
    assert rep["betas"] == {} and rep["factor_contributions"] == {}    # 绝不编造 β
    assert rep["evidence_state"] != "factor_explained"
    assert "证据不足" in rep["note"]
    # abstain 下恒等式仍闭合：specific == total。
    assert rep["identity"]["holds"] is True
    assert abs(rep["specific_contribution"] - rep["total_return"]) < 1e-12


def test_collinear_abstains_no_fake_beta():
    """共线（重复因子）→ evidence_state collinear、betas 空（不报不可识别 β）。"""
    rng = np.random.default_rng(2)
    n = 120
    f = (rng.standard_normal(n) * 0.02).tolist()
    rep = build_factor_attribution_report(
        (rng.standard_normal(n) * 0.03).tolist(), {"a": f, "b": f}  # a==b 共线
    )
    assert rep["status"] == "collinear" and rep["evidence_state"] == "collinear"
    assert rep["betas"] == {}
    assert rep["evidence_state"] != "factor_explained"
    assert "证据不足" in rep["note"]


def test_undefined_r2_not_marked_explained():
    """收益近无波动 → R² 无定义 → specific_driven（不无中生有标已归因）。"""
    n = 80
    y = [0.001] * n                      # 常数收益 → ss_tot≈0 → R² nan
    rng = np.random.default_rng(3)
    rep = build_factor_attribution_report(y, _factors(rng, n, 1))
    assert rep["status"] == "ok"
    assert rep["r_squared"] is None                          # nan→None（JSON-safe）
    assert rep["evidence_state"] == "specific_driven"        # 无定义≠已解释
    assert rep["evidence_state"] != "factor_explained"


def test_report_is_strict_json_safe():
    """报告严格 JSON-safe：含 abstain（nan 字段）也能 json.dumps（allow_nan=False）。"""
    rng = np.random.default_rng(5)
    # insufficient（alpha=nan, r2=nan）→ 须已转 None。
    rep_abstain = build_factor_attribution_report(
        (rng.standard_normal(3) * 0.02).tolist(), _factors(rng, 3, 2)
    )
    json.dumps(rep_abstain, allow_nan=False)
    assert rep_abstain["alpha"] is None and rep_abstain["r_squared"] is None
    rep_ok = build_factor_attribution_report(
        (rng.standard_normal(80) * 0.02).tolist(), _factors(rng, 80, 2)
    )
    json.dumps(rep_ok, allow_nan=False)


def test_note_no_forbidden_verdict_words_all_states():
    """note 单一源走 R7 措辞门：四态 note 均无绝对化禁词（后端防御，前端原样渲染才安全）。"""
    rng = np.random.default_rng(9)
    cases = [
        build_factor_attribution_report((rng.standard_normal(3) * 0.02).tolist(), _factors(rng, 3, 2)),   # insufficient
        build_factor_attribution_report((rng.standard_normal(60) * 0.03).tolist(), _factors(rng, 60, 2)), # low R² specific_driven
    ]
    # collinear
    f = (rng.standard_normal(50) * 0.02).tolist()
    cases.append(build_factor_attribution_report((rng.standard_normal(50) * 0.03).tolist(), {"a": f, "b": f}))
    # factor_explained
    n = 300
    f1 = rng.standard_normal(n) * 0.02
    yy = (2.0 * f1 + rng.standard_normal(n) * 1e-4).tolist()
    cases.append(build_factor_attribution_report(yy, {"f1": f1.tolist()}))
    for rep in cases:
        hits = [w for w in _FORBIDDEN if w in rep["note"]]
        assert hits == [], f"note 触 R7 禁词 {hits}：{rep['note']}"


def test_length_mismatch_propagates():
    """因子与组合不等长 → math 件 raise 透传（消费层不吞错）。"""
    with pytest.raises(ValueError, match="长度|等长"):
        build_factor_attribution_report([0.01, 0.02, 0.03], {"f1": [0.01, 0.02]})
