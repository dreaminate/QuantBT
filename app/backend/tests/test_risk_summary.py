"""v0.8.4 Day 4 · risk_summary 规则测试。

7 条规则覆盖：PBO / DSR / MaxDD (high) + Sharpe / IC-IR / Turnover / Concentration (medium)
+ insufficient_data fallback。
"""

from __future__ import annotations

import pytest

from app.eval.risk_summary import compute_risk_summary


# ============================================================
# 高风险触发：trust_level = high_risk
# ============================================================


def test_pbo_above_threshold_triggers_high_risk():
    r = compute_risk_summary({"sharpe": 1.5, "pbo": 0.7})
    assert r.trust_level == "high_risk"
    assert any(f.name == "high_overfit_risk" for f in r.flags)


def test_pbo_at_threshold_does_not_trigger():
    r = compute_risk_summary({"sharpe": 1.5, "pbo": 0.6, "dsr": 0.5})
    assert r.trust_level == "ok"


def test_dsr_below_threshold_triggers_high_risk():
    r = compute_risk_summary({"sharpe": 2.0, "dsr": 0.15})
    assert r.trust_level == "high_risk"
    assert any(f.name == "low_dsr_confidence" for f in r.flags)


def test_max_drawdown_negative_triggers_high_risk():
    """max_drawdown 为负数 (-0.30) 也应触发。"""
    r = compute_risk_summary({"sharpe": 1.5, "max_drawdown": -0.30, "dsr": 0.5})
    assert r.trust_level == "high_risk"
    assert any(f.name == "high_max_drawdown" for f in r.flags)


def test_max_drawdown_positive_form_also_triggers():
    """有些实现给正数 0.30 也应识别。"""
    r = compute_risk_summary({"sharpe": 1.5, "max_drawdown": 0.30, "dsr": 0.5})
    assert r.trust_level == "high_risk"
    assert any(f.name == "high_max_drawdown" for f in r.flags)


# ============================================================
# 中等风险触发：trust_level = caution
# ============================================================


def test_low_sharpe_triggers_caution():
    r = compute_risk_summary({"sharpe": 0.7, "pbo": 0.3, "dsr": 0.8})
    assert r.trust_level == "caution"
    assert any(f.name == "low_sharpe" for f in r.flags)


def test_low_ic_ir_triggers_caution():
    r = compute_risk_summary({"sharpe": 1.5, "ic_ir": 0.2, "pbo": 0.3})
    assert r.trust_level == "caution"
    assert any(f.name == "low_factor_predictive" for f in r.flags)


def test_excessive_turnover_triggers_caution():
    r = compute_risk_summary({"sharpe": 1.5, "turnover": 4.5, "pbo": 0.3})
    assert r.trust_level == "caution"
    assert any(f.name == "excessive_turnover" for f in r.flags)


def test_high_concentration_triggers_caution():
    r = compute_risk_summary({"sharpe": 1.5, "max_position_weight": 0.3, "pbo": 0.3})
    assert r.trust_level == "caution"
    assert any(f.name == "high_concentration" for f in r.flags)


# ============================================================
# 优先级：high > medium
# ============================================================


def test_high_and_medium_present_returns_high():
    r = compute_risk_summary({
        "sharpe": 0.5,        # medium
        "ic_ir": 0.2,         # medium
        "pbo": 0.7,           # high
    })
    assert r.trust_level == "high_risk"
    # 但 flags 应该包含所有 3 条
    names = {f.name for f in r.flags}
    assert "high_overfit_risk" in names
    assert "low_sharpe" in names
    assert "low_factor_predictive" in names


# ============================================================
# insufficient_data 兜底
# ============================================================


def test_empty_metrics_returns_insufficient():
    r = compute_risk_summary({})
    assert r.trust_level == "insufficient_data"


def test_none_metrics_returns_insufficient():
    r = compute_risk_summary(None)
    assert r.trust_level == "insufficient_data"


def test_only_sharpe_no_overfit_evidence_returns_insufficient():
    """有 sharpe 没 pbo/dsr → 反过拟合证据缺失，归 insufficient。"""
    r = compute_risk_summary({"sharpe": 2.5})
    assert r.trust_level == "insufficient_data"
    assert "PBO/DSR" in r.summary


def test_only_unknown_fields_returns_insufficient():
    r = compute_risk_summary({"foo": 1, "bar": "x"})
    assert r.trust_level == "insufficient_data"


# ============================================================
# 全清白 trust_level = ok
# ============================================================


def test_all_metrics_healthy_returns_ok():
    r = compute_risk_summary({
        "sharpe": 1.5,
        "pbo": 0.2,
        "dsr": 0.85,
        "max_drawdown": -0.10,
        "ic_ir": 0.4,
        "turnover": 1.5,
        "max_position_weight": 0.15,
    })
    assert r.trust_level == "ok"
    assert r.flags == []
    assert "已检" in r.summary


# ============================================================
# alias 兼容性
# ============================================================


def test_dsr_alias_deflated_sharpe():
    r = compute_risk_summary({"sharpe": 1.5, "deflated_sharpe": 0.15, "pbo": 0.3})
    assert any(f.name == "low_dsr_confidence" for f in r.flags)


def test_max_drawdown_alias_drawdown():
    r = compute_risk_summary({"sharpe": 1.5, "drawdown": -0.30, "dsr": 0.5})
    assert any(f.name == "high_max_drawdown" for f in r.flags)


def test_ic_ir_alias():
    r = compute_risk_summary({"sharpe": 1.5, "ic_information_ratio": 0.2, "pbo": 0.3})
    assert any(f.name == "low_factor_predictive" for f in r.flags)


# ============================================================
# to_dict
# ============================================================


def test_to_dict_schema():
    r = compute_risk_summary({"sharpe": 1.5, "pbo": 0.7})
    d = r.to_dict()
    assert d["trust_level"] == "high_risk"
    assert isinstance(d["flags"], list)
    assert isinstance(d["summary"], str)
    assert isinstance(d["checked_metrics"], list)
    # flag schema
    f = d["flags"][0]
    assert {"name", "severity", "message", "metric_name", "metric_value", "threshold"} <= f.keys()


def test_summary_first_flag_message_priority():
    """summary 应该用 high 级别第一条 flag 的 message。"""
    r = compute_risk_summary({"sharpe": 0.5, "pbo": 0.7})
    assert "PBO" in r.summary
    assert "low_sharpe" not in r.summary.lower()


# ============================================================
# synthetic fixtures (按 §J Day 4 完成判定: PBO=0.7 应展示 high_overfit_risk)
# ============================================================


def test_synthetic_high_overfit_fixture():
    metrics = {
        "sharpe": 2.1,
        "pbo": 0.7,        # 该触发 high_overfit_risk
        "dsr": 0.85,
        "max_drawdown": -0.05,
    }
    r = compute_risk_summary(metrics)
    assert r.trust_level == "high_risk"
    flag_names = {f.name for f in r.flags}
    assert "high_overfit_risk" in flag_names


def test_synthetic_clean_fixture():
    metrics = {
        "sharpe": 1.4,
        "pbo": 0.25,
        "dsr": 0.78,
        "max_drawdown": -0.12,
        "ic_ir": 0.45,
        "turnover": 1.8,
        "max_position_weight": 0.18,
    }
    r = compute_risk_summary(metrics)
    assert r.trust_level == "ok"
    assert r.flags == []


def test_synthetic_caution_only_fixture():
    metrics = {
        "sharpe": 0.85,    # medium
        "pbo": 0.3,
        "dsr": 0.7,
    }
    r = compute_risk_summary(metrics)
    assert r.trust_level == "caution"


# ============================================================
# 不假绿灯：仅辅助指标（零核心证据）绝不判 ok（审计 pass2 #4）
# ============================================================


def test_auxiliary_only_metrics_never_ok():
    """**假绿灯门**：只有健康的辅助指标（换手/回撤/集中度·无 sharpe/pbo/dsr）→ insufficient_data，绝不 ok。

    MUT（还原：ok 分支不要求核心证据）→ 本组断言崩。证据不足时绝不判可信（北极星·§3 不待拍）。
    """
    for aux in ({"turnover": 1.0}, {"max_drawdown": -0.10}, {"max_position_weight": 0.10},
                {"ic_ir": 0.4}, {"turnover": 1.0, "max_drawdown": -0.08}):
        r = compute_risk_summary(aux)
        assert r.trust_level == "insufficient_data", f"仅辅助指标 {aux} 竟判 {r.trust_level}（假绿灯：零核心证据判可信）"
        assert r.trust_level != "ok"


def test_core_evidence_still_reaches_ok():
    """不误伤：有核心证据（sharpe/pbo/dsr）且辅助健康、无 flag → 仍 ok（向后兼容）。"""
    assert compute_risk_summary({"sharpe": 1.5, "pbo": 0.2, "dsr": 0.85, "turnover": 1.0}).trust_level == "ok"
    # sharpe+dsr 无 pbo（单策略 PBO 不可达）仍 ok（保 #6 既有语义·不在本切片动）
    assert compute_risk_summary({"sharpe": 1.5, "dsr": 0.85}).trust_level == "ok"


def test_unhealthy_auxiliary_still_surfaces_flag_not_silenced():
    """辅助指标**不健康**（超阈触 flag）→ 仍 high_risk/caution（不被『零核心证据→insufficient』吞掉风险信号）。"""
    r = compute_risk_summary({"turnover": 50.0})   # 极高换手（>3.0 阈）→ flag
    assert r.trust_level in ("caution", "high_risk")   # 真风险信号照常浮出，非 insufficient
    assert any(f.name == "excessive_turnover" for f in r.flags)


# ============================================================
# DSR 别名单一源：flags 与 trust_level 不自相矛盾（审计 pass2 #8）
# ============================================================


def test_dsr_confidence_alias_consistent_flags_and_trust_level():
    """**矛盾门**：dsr_confidence 是 DSR 别名 → 触 low_dsr_confidence 时 has_dsr 必识得、绝不早返 insufficient。

    种坏（修前）：has_dsr 别名集漏 dsr_confidence → {sharpe, dsr_confidence=0.1} 触 high flag 却判
    insufficient_data（trust 说『缺 DSR 证据』、flags 说『DSR 太低高风险』=自相矛盾·误导）。
    MUT（has_dsr 别名集去掉 dsr_confidence）→ 本测红。
    """
    r = compute_risk_summary({"sharpe": 1.8, "dsr_confidence": 0.1})
    assert any(f.name == "low_dsr_confidence" for f in r.flags)      # DSR 证据确被读到（low flag 触发）
    assert r.trust_level != "insufficient_data", \
        "dsr_confidence 触 low flag 却判 insufficient → has_dsr 别名漂移、flags⊥trust_level 自相矛盾"
    assert r.trust_level == "high_risk"                              # 与 high flag 一致


def test_dsr_confidence_alias_healthy_reaches_ok():
    """dsr_confidence 健康（≥0.2）+ sharpe → has_dsr 识得 → 可达 ok（别名源一致·不误判 insufficient）。"""
    r = compute_risk_summary({"sharpe": 1.5, "dsr_confidence": 0.8})
    assert r.trust_level == "ok"
