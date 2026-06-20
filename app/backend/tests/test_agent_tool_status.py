"""T-028 · /api/agent/tools 诚实暴露每工具真实可用状态（防绿灯错觉/能力名不副实）。

种坏门必抓：schema 声明但未接通的工具若被标成 live → 绿灯错觉 → 必抓。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _status_map():
    r = TestClient(app).get("/api/agent/tools")
    assert r.status_code == 200
    body = r.json()
    assert "tool_status" in body, "agent/tools 应返回 tool_status"
    return {t["name"]: t for t in body["tool_status"]}


def test_tool_status_marks_unwired():
    """schema 声明但未接通的高价值工具必须诚实标 unwired（防绿灯错觉）。"""
    m = _status_map()
    for name in ("backtest.run", "eval.pbo", "model.train", "report.generate"):
        assert m[name]["status"] == "unwired", f"{name} 应标 unwired（schema 声明未接通）"


def test_tool_status_marks_stub():
    m = _status_map()
    assert m["factor.run_ic"]["status"] == "stub", "factor.run_ic 仅返回 queued，应标 stub 而非 live"


def test_tool_status_marks_live():
    m = _status_map()
    assert m["strategy_goal.create"]["status"] == "live"
    assert m["data.list_sources"]["status"] == "live"


def test_tool_status_carries_side_effect():
    m = _status_map()
    assert m["strategy_goal.create"]["side_effect"] == "none"


def test_tool_status_not_all_live_probe():
    """探针防假绿：若所有工具都标 live（绿灯错觉）→ 必抓。"""
    m = _status_map()
    statuses = {t["status"] for t in m.values()}
    assert "unwired" in statuses and len(statuses) >= 2, \
        f"工具状态未区分（疑似全标 live 假绿）：{statuses}"
