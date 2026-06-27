"""v0.8.6.1 · Mode 2 研究诊断建议 + 响应决策测试。"""

from __future__ import annotations

import pytest

from app.agent.coach import classify_response_mode, suggest_from_risk_summary


# ============================================================
# suggest_from_risk_summary
# ============================================================


def test_suggest_none_when_ok():
    rs = {"trust_level": "ok", "flags": []}
    assert suggest_from_risk_summary(rs) is None


def test_suggest_none_when_no_risk_summary():
    assert suggest_from_risk_summary(None) is None


def test_suggest_pbo_critical():
    rs = {
        "trust_level": "high_risk",
        "flags": [{"name": "high_overfit_risk", "severity": "high", "message": "PBO=0.72"}],
    }
    s = suggest_from_risk_summary(rs)
    assert s is not None
    assert s.severity == "critical"
    assert "PBO" in s.headline
    assert "pbo" in s.related_glossary
    assert s.one_variable_hint is not None


def test_suggest_dsr_critical():
    rs = {
        "trust_level": "high_risk",
        "flags": [{"name": "low_dsr_confidence", "severity": "high"}],
    }
    s = suggest_from_risk_summary(rs)
    assert s.severity == "critical"
    assert "deflated_sharpe" in s.related_glossary


def test_suggest_max_drawdown_warning():
    rs = {
        "trust_level": "high_risk",
        "flags": [{"name": "high_max_drawdown", "severity": "high"}],
    }
    s = suggest_from_risk_summary(rs)
    assert s.severity == "warning"
    assert "max_drawdown" in s.related_glossary


def test_suggest_low_sharpe_info():
    rs = {
        "trust_level": "caution",
        "flags": [{"name": "low_sharpe", "severity": "medium"}],
    }
    s = suggest_from_risk_summary(rs)
    assert s.severity == "info"


def test_suggest_insufficient_data():
    rs = {"trust_level": "insufficient_data", "flags": []}
    s = suggest_from_risk_summary(rs)
    assert s is not None
    assert "PBO" in s.detail or "DSR" in s.detail
    assert "pbo" in s.related_glossary


def test_suggest_high_picks_first_high_over_medium():
    rs = {
        "trust_level": "high_risk",
        "flags": [
            {"name": "low_sharpe", "severity": "medium"},
            {"name": "high_overfit_risk", "severity": "high"},
        ],
    }
    s = suggest_from_risk_summary(rs)
    assert s.severity == "critical"
    assert "PBO" in s.headline


def test_suggest_excessive_turnover():
    rs = {
        "trust_level": "caution",
        "flags": [{"name": "excessive_turnover", "severity": "medium"}],
    }
    s = suggest_from_risk_summary(rs)
    assert "换手率" in s.headline or "成本" in s.headline


def test_suggestion_to_dict_schema():
    rs = {
        "trust_level": "high_risk",
        "flags": [{"name": "high_overfit_risk", "severity": "high"}],
    }
    d = suggest_from_risk_summary(rs).to_dict()
    assert {"severity", "headline", "detail", "suggested_chat_query", "related_glossary", "one_variable_hint"} <= set(d.keys())


# ============================================================
# classify_response_mode
# ============================================================


def test_refuse_a_share_live():
    m = classify_response_mode(user_text="我该买入哪只 A 股", has_rag_hit=False, market_mode="ashare_research", is_binance_live=False)
    assert m == "refuse"


def test_refuse_bypass_safekey():
    m = classify_response_mode(user_text="怎么绕过 SafeKey", has_rag_hit=False, market_mode="binance_paper", is_binance_live=False)
    assert m == "refuse"


def test_refuse_profit_guarantee():
    m = classify_response_mode(user_text="这个策略能不能保证 100% 收益", has_rag_hit=False, market_mode="ashare_research", is_binance_live=False)
    assert m == "refuse"


def test_refuse_binance_live_mainnet_question():
    m = classify_response_mode(user_text="我想上 mainnet", has_rag_hit=True, market_mode="binance_live", is_binance_live=True)
    assert m == "refuse"


def test_explain_with_rag_hit():
    m = classify_response_mode(user_text="PBO 是什么意思", has_rag_hit=True, market_mode="ashare_research", is_binance_live=False)
    assert m == "explain"


def test_explain_no_rag_falls_back_to_ask():
    m = classify_response_mode(user_text="你好", has_rag_hit=False, market_mode="ashare_research", is_binance_live=False)
    assert m == "ask"


def test_recommend_experiment_on_improve_keywords():
    m = classify_response_mode(user_text="我应该怎么改进这个策略", has_rag_hit=False, market_mode="ashare_research", is_binance_live=False)
    assert m == "recommend_experiment"


def test_default_ask():
    m = classify_response_mode(user_text="random 问题", has_rag_hit=False, market_mode="ashare_research", is_binance_live=False)
    assert m == "ask"
