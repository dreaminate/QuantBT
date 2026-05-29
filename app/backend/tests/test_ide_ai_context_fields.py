"""数据平台 v2 · IDE/Agent 上下文注入"当前可用字段宇宙"（聚宽式回测 + Agent 代写吃上动态字段）。"""

from __future__ import annotations

from app.ide import build_ai_context


def test_build_ai_context_injects_field_universe() -> None:
    ctx = build_ai_context(
        connectors=[],
        factors=[],
        operators=[],
        fields_by_market={"stocks_cn": {"canonical": ["close", "pe_ttm"], "freeform": ["tushare__pre_close"]}},
    )
    block = ctx.to_system_prompt_block()
    assert "可用字段宇宙" in block
    assert "pe_ttm" in block and "stocks_cn" in block
    assert "tushare__pre_close" in block
    d = ctx.to_dict()
    assert d["fields_by_market"]["stocks_cn"]["canonical"] == ["close", "pe_ttm"]


def test_build_ai_context_without_fields_omits_block() -> None:
    """向后兼容：不传 fields_by_market 时 system prompt 不出现字段宇宙块。"""
    ctx = build_ai_context(connectors=[], factors=[], operators=[])
    assert "可用字段宇宙" not in ctx.to_system_prompt_block()
    assert ctx.to_dict()["fields_by_market"] == {}
