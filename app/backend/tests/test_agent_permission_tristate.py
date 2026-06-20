"""T-027 · agent 权限三态（ask/auto/bypass）+ 权限轴⟂治理轴（D-PERM）对抗测试。

核心不变量（种坏门必抓）：
- none（无副作用）：ask 每步确认、auto/bypass 自动。
- external（如 testnet 真发单）：仅 bypass 自动、ask/auto 需确认。
- realmoney（动钱/晋级）：【任何】模式（含 bypass）都挂起确认——权限轴绝不跳治理门（致命，§5）。
"""

from __future__ import annotations

import json

import pytest

from app.agent.agent_runtime import AgentRuntime, permission_gate
from app.agent.llm_client import LLMResponse


class _ScriptedLLM:
    provider = "test"

    def __init__(self, responses):
        self._q = list(responses)
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.calls += 1
        return self._q.pop(0) if self._q else LLMResponse(content="(end)")


def _tc(name, args=None):
    return {"id": "c1", "name": name, "arguments": json.dumps(args or {})}


def _counting_spy():
    state = {"n": 0, "last": None}

    def spy(_n, args):
        state["n"] += 1
        state["last"] = args
        return {"ok": True}

    return spy, state


def _run_one(mode, tool_name, side_effect):
    spy, state = _counting_spy()
    rt = AgentRuntime(
        _ScriptedLLM([
            LLMResponse(content="x", tool_calls=[_tc(tool_name)]),
            LLMResponse(content="(end)"),
        ]),
        permission_mode=mode,
    )
    rt.register_tool(tool_name, spy, side_effect=side_effect)
    turn = rt.run("op")
    return turn, state


# ── 1. permission_gate 决策矩阵 ─────────────────────────────────────────────
@pytest.mark.parametrize("mode,se,expect", [
    ("ask", "none", "confirm"), ("auto", "none", "execute"), ("bypass", "none", "execute"),
    ("ask", "external", "confirm"), ("auto", "external", "confirm"), ("bypass", "external", "execute"),
    ("ask", "realmoney", "confirm"), ("auto", "realmoney", "confirm"), ("bypass", "realmoney", "confirm"),
])
def test_permission_gate_matrix(mode, se, expect):
    assert permission_gate(mode, se) == expect


def test_bypass_never_skips_realmoney_unit():
    """治理正交（命门）：realmoney 即便 bypass 也 confirm。"""
    assert permission_gate("bypass", "realmoney") == "confirm"


# ── 2. AgentRuntime 集成：执行/挂起按 (mode, side_effect) ────────────────────
def test_auto_executes_no_side_effect():
    _turn, state = _run_one("auto", "factor.run_ic", "none")
    assert state["n"] == 1, "auto 下无副作用工具应自主执行"


def test_ask_suspends_even_no_side_effect():
    turn, state = _run_one("ask", "factor.run_ic", "none")
    assert state["n"] == 0, "ask 模式每步确认，工具不应自动执行"
    assert turn.succeeded is False


def test_auto_suspends_external():
    turn, state = _run_one("auto", "testnet.place", "external")
    assert state["n"] == 0, "auto 下 external（testnet 真发单）应挂起确认"
    assert turn.succeeded is False


def test_bypass_executes_external():
    _turn, state = _run_one("bypass", "testnet.place", "external")
    assert state["n"] == 1, "bypass 下 external 可自动执行"


def test_bypass_suspends_realmoney_governance_orthogonal():
    """种坏门：realmoney 工具 + bypass，若被自动执行=权限轴跳了治理门（致命）→ 必抓。"""
    turn, state = _run_one("bypass", "execution.place_order", "realmoney")
    assert state["n"] == 0, "bypass 绝不能执行 realmoney 工具（权限轴跳治理门=致命）"
    assert turn.succeeded is False


def test_realmoney_suspended_in_every_mode():
    """探针：realmoney 在 ask/auto/bypass 三模式全挂起（证明治理正交非 no-op）。"""
    for mode in ("ask", "auto", "bypass"):
        _turn, state = _run_one(mode, "execution.place_order", "realmoney")
        assert state["n"] == 0, f"{mode} 模式不应执行 realmoney 工具"
