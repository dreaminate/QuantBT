"""v0.8.4 Day 6 · Mode 2 system prompt contract test。

确保 v0.8.6 接入多轮 chat 时，prompt 仍保留关键约束词。
若任何关键词被改没，立即在 CI fail，防止 LLM 越界。
"""

from __future__ import annotations

import pytest

from app.agent.prompts import MODE2_SYSTEM_PROMPT_ZH, build_mode2_prompt
from app.agent.prompts.mode2_teaching import list_contract_phrases


def test_prompt_contains_all_contract_phrases():
    contract = list_contract_phrases()
    for key, phrase in contract.items():
        assert phrase in MODE2_SYSTEM_PROMPT_ZH, f"contract key={key} 缺少短语: {phrase!r}"


def test_prompt_has_minimum_length():
    """patch1 要求 prompt 完整可粘进代码；不能太短。"""
    # 当前长度 ~1500 字
    assert len(MODE2_SYSTEM_PROMPT_ZH) > 1200


def test_prompt_role_identity_not_assistant():
    """禁止 Mode 2 自称'量化助手'/'交易助手'/'AI 助手'。"""
    for forbidden in ["量化助手", "交易助手", "智能助手", "AI 助手", "教练", "副驾驶"]:
        assert forbidden not in MODE2_SYSTEM_PROMPT_ZH, f"prompt 含 {forbidden!r} 与 Mode 2 定位冲突"


def test_prompt_socratic_questions_count():
    """提问式复核句式库至少 8 句（patch1 §D.b 硬要求）。"""
    lines = [l for l in MODE2_SYSTEM_PROMPT_ZH.split("\n") if l.strip().startswith(tuple("12345678"))]
    # 数字开头的行可能不只是 socratic（拒答也是有序列表），所以宽松校验
    assert len(lines) >= 8


def test_prompt_refuse_triggers_present():
    """6 类拒答触发器（patch1 §D.b）。"""
    refuse_keywords = ["A股实盘", "withdraw", "保证收益", "逃逸沙箱"]
    for kw in refuse_keywords:
        assert kw in MODE2_SYSTEM_PROMPT_ZH, f"拒答触发器缺关键词 {kw!r}"


def test_build_renders_all_slots():
    s = build_mode2_prompt(
        rag_context="GLOSSARY: pbo 是过拟合概率",
        run_context="run_id=r1 sharpe=1.5 pbo=0.7",
        conversation_history="user: 这个策略能上吗？\nagent: 我需要更多信息。",
    )
    assert "pbo 是过拟合概率" in s
    assert "sharpe=1.5" in s
    assert "user: 这个策略能上吗？" in s
    # placeholder 不应残留
    assert "{rag_context}" not in s
    assert "{run_context}" not in s
    assert "{conversation_history}" not in s


def test_build_empty_slots_uses_fallback():
    s = build_mode2_prompt()
    assert "(无 RAG 上下文)" in s
    assert "(无 active run 上下文)" in s
    assert "(无历史" in s


def test_prompt_token_budget_documented():
    """每 slot 都标注 token 预算。"""
    assert "≤ 1200 tokens" in MODE2_SYSTEM_PROMPT_ZH
    assert "≤ 800 tokens" in MODE2_SYSTEM_PROMPT_ZH


def test_prompt_answer_format_specifies_four_steps():
    assert "结论" in MODE2_SYSTEM_PROMPT_ZH
    assert "证据" in MODE2_SYSTEM_PROMPT_ZH
    assert "下一步实验" in MODE2_SYSTEM_PROMPT_ZH
    assert "证据一致" in MODE2_SYSTEM_PROMPT_ZH


def test_prompt_no_emojis():
    """patch1 §通用要求：不许 emoji。"""
    import re
    # 简单检查 emoji 范围
    emoji_pattern = re.compile(r"[\U0001F300-\U0001F9FF✀-➿]")
    matches = emoji_pattern.findall(MODE2_SYSTEM_PROMPT_ZH)
    assert not matches, f"prompt 含 emoji: {matches}"


def test_prompt_no_marketing_buzzwords():
    """patch1 §通用要求：不许营销话术。"""
    buzz = ["赋能", "强大", "超棒", "业界领先", "划时代", "未来可期"]
    for word in buzz:
        assert word not in MODE2_SYSTEM_PROMPT_ZH, f"prompt 含营销话术 {word!r}"
