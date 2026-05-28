"""v0.8.8.1 · 复现社区合规测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.community.compliance import (
    FORBIDDEN_PROFIT_PATTERNS,
    ComplianceService,
    check_content_for_forbidden,
)


@pytest.fixture
def svc(tmp_path: Path) -> ComplianceService:
    return ComplianceService(tmp_path / "compliance.db")


def test_clean_content_passes():
    assert check_content_for_forbidden("这是我的回测分享，PBO=0.3，Sharpe=1.2") == []


def test_detects_guaranteed_profit():
    found = check_content_for_forbidden("保证收益 20% 起步")
    assert len(found) > 0


def test_detects_stable_profit():
    assert len(check_content_for_forbidden("稳赚不赔的策略")) > 0


def test_detects_must_win():
    assert len(check_content_for_forbidden("必赚 50%")) > 0


def test_detects_100_percent_profit():
    assert len(check_content_for_forbidden("100% 盈利")) > 0


def test_detects_risk_free():
    assert len(check_content_for_forbidden("无风险回报每月 5%")) > 0


def test_normal_strategy_share_passes():
    """正常的策略分享内容不被误伤。"""
    content = "我的 BTC 动量策略 v2：Sharpe 1.4，PBO 0.32，回撤 12%。代码 fork 自 BTC_momentum_v1。"
    assert check_content_for_forbidden(content) == []


def test_record_compliance_clean(svc: ComplianceService):
    result = svc.record_compliance(
        "post_1",
        content="分享一个 sharpe 1.2 的策略",
        attached_run_id="run_abc",
        risk_summary={"trust_level": "ok", "flags": []},
    )
    assert result.passed is True
    assert result.attached_run_id == "run_abc"
    assert result.risk_summary_snapshot == {"trust_level": "ok", "flags": []}


def test_record_compliance_blocks_profit_promise(svc: ComplianceService):
    result = svc.record_compliance(
        "post_2",
        content="跟我的策略稳赚不赔",
    )
    assert result.passed is False
    assert len(result.forbidden_phrases_found) > 0


def test_get_compliance_returns_persisted(svc: ComplianceService):
    svc.record_compliance("post_3", content="clean", attached_run_id="r1")
    rec = svc.get_compliance("post_3")
    assert rec is not None
    assert rec.attached_run_id == "r1"


def test_get_compliance_missing_returns_none(svc: ComplianceService):
    assert svc.get_compliance("never_recorded") is None


def test_compliance_to_dict_schema(svc: ComplianceService):
    rec = svc.record_compliance("post_4", content="clean")
    d = rec.to_dict()
    assert {"post_id", "passed", "attached_run_id", "risk_summary_snapshot",
            "forbidden_phrases_found", "checked_at_utc"} <= set(d.keys())


def test_forbidden_patterns_non_empty():
    assert len(FORBIDDEN_PROFIT_PATTERNS) >= 5
