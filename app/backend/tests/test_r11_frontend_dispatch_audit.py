"""T-026 · R11 前端派发审计——agent tool_call 不旁路治理门。

裁决（三角调查 no_bypass / r11_gap=False）：治理门钉在端点/执行层，前端 display-only，
agent 层物理上派发不了动钱/晋级/实盘动作。本测试把该裁决钉成回归不变量。

A4 更新：backtest.run（side_effect=none，本地可重置）改由 agent 真实引擎执行，已从高危标记移除；
真正动钱/晋级/实盘控制工具（place_order/promote/kill_switch/…）仍永不可注册（详见 _HIGH_RISK_MARKERS）。

种已知坏门必抓（每组配探针自检证明非 no-op）：
1. agent 白名单守门：生产 agent 注册的工具集绝不含动钱/晋级/实盘高危工具；种一个误注册 → 必抓。
2. dispatch 不执行未注册工具：LLM 即便吐 place_order tool_call → 返回「未注册工具」、handler 绝不调；探针：已注册工具确会被调（证明非 no-op）。
3. 翻译门拦非 ok：语义越界 tool_call → 不派发、handler 0 调用；探针：ok 时同 tool_call 放行派发。
4. 前端 display-only：agent 对话页绝不直接 fetch 业务/动钱模块端点（只 /api/agent/*）；探针：种一个直调 /api/ide/.../run → 必抓。

注（转交 T-029）：个别端点门「真有效/不可绕」逐一压测（copy_trade subscribe/redeem 把校验下沉 service、
裸 place_order 扫描、main.py:282「前端继续派发」注释钉 RULES.project 红线）属端点层审计，不在本卡。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import app as app_pkg
from app.agent.agent_runtime import AgentRuntime
from app.agent.llm_client import LLMResponse
from app.main import _agent_runtime

APP_ROOT = Path(app_pkg.__file__).resolve().parent
FRONTEND_SRC = APP_ROOT.parents[1] / "frontend" / "src"

# 永不该被 agent 注册的高危工具标记（动钱 / 晋级 / 跟单 / 实盘控制）：
#
# A4 更新（2026-06）：`backtest.run` 改由 agent 真实引擎执行（side_effect="none"，本地可重置、不动钱、
# 不外发单——策略台脊柱终点，设计稿剧本核心动作）。故从高危标记里移除 "backtest"——它不再是
# 「永不可注册」类，而是受治理门管控（permission_gate）的 none 副作用能力。**真正动钱/晋级/实盘控制
# 标记一个不少**（place_order/promote/kill_switch/leverage/withdraw/transfer/copy_trade/subscribe/
# redeem/emergency/upgrade/ladder/approve 全保留），种这些必抓（探针 test_high_risk_tool_guard_probe
# 用 place_order 证守门非 no-op）。
_HIGH_RISK_MARKERS = (
    "place_order", "copy_trade", "subscribe", "redeem",
    "promote", "approve", "kill_switch", "emergency", "upgrade",
    "leverage", "withdraw", "transfer", "ladder",
)


# ── fake LLM / translator ───────────────────────────────────────────────────
class _ScriptedLLM:
    """按脚本逐轮返回 LLMResponse 的假 LLM（不发任何真请求）。"""

    provider = "test"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._q = list(responses)
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.calls += 1
        return self._q.pop(0) if self._q else LLMResponse(content="(end)")


def _tool_call(name: str, args: dict) -> dict:
    return {"id": "c1", "name": name, "arguments": json.dumps(args)}


# ── 1. agent 白名单守门：生产注册集不含高危工具 ──────────────────────────────
def test_agent_registers_no_high_risk_tools():
    names = set(_agent_runtime()._tools.keys())
    assert names, "agent 未注册任何工具，疑似 _agent_runtime 失效（防空集假绿）"
    offenders = {n for n in names if any(m in n.lower() for m in _HIGH_RISK_MARKERS)}
    assert not offenders, f"agent 注册了高危工具（动钱/晋级/回测永不可注册）：{offenders}"


def test_high_risk_tool_guard_probe():
    """探针（变异）：误注册一个 place_order handler → 守门必抓（证明 #1 非 no-op）。"""
    rt = _agent_runtime()
    rt.register_tool("execution.place_order", lambda _n, _a: {})
    offenders = {n for n in rt._tools if any(m in n.lower() for m in _HIGH_RISK_MARKERS)}
    assert "execution.place_order" in offenders


# ── 2. dispatch 不执行未注册的高危工具 ──────────────────────────────────────
def test_unregistered_high_risk_toolcall_returns_error_not_dispatched():
    """LLM 吐 place_order tool_call，但生产工具集未注册 → 返回「未注册工具」，绝不执行。"""
    prod_tools = dict(_agent_runtime()._tools)  # 复制生产工具集，隔离翻译门单测 dispatch
    rt = AgentRuntime(
        _ScriptedLLM([
            LLMResponse(content="下单", tool_calls=[
                _tool_call("execution.place_order", {"symbol": "BTCUSDT", "side": "buy", "quantity": 99})
            ]),
            LLMResponse(content="(终态)"),
        ]),
        tools=prod_tools,
    )
    turn = rt.run("帮我直接下单买 99 个 BTC")
    tool_steps = [s for s in turn.steps if s.role == "tool"]
    assert tool_steps, "应有 tool 结果步骤"
    assert any("未注册工具" in s.content for s in tool_steps), \
        f"高危工具应返回『未注册工具』而非执行：{[s.content for s in tool_steps]}"


def test_dispatch_probe_registered_tool_is_called():
    """探针：已注册工具确会被 dispatch 调用 → 证明『未注册→error』是真守门、非 no-op。"""
    called: dict = {}

    def spy(_n, args):
        called["hit"] = args
        return {"ok": True}

    rt = AgentRuntime(
        _ScriptedLLM([
            LLMResponse(content="建 goal", tool_calls=[_tool_call("strategy_goal.create", {"name": "t"})]),
            LLMResponse(content="(终态)"),
        ]),
        tools={"strategy_goal.create": spy},
    )
    rt.run("建一个策略目标")
    assert called.get("hit"), "已注册工具应被 dispatch 调用"


# ── 3. 翻译门拦非 ok：越界 tool_call 不派发 ─────────────────────────────────
def _stub_translator(status: str, reason: str = "x"):
    return SimpleNamespace(translate=lambda _calls: SimpleNamespace(status=status, reason=reason))


def test_translation_gate_blocks_non_ok_no_dispatch():
    called = {"n": 0}

    def spy(_n, _a):
        called["n"] += 1
        return {"ok": True}

    rt = AgentRuntime(
        _ScriptedLLM([
            LLMResponse(content="30x", tool_calls=[_tool_call("strategy_goal.create", {"leverage": 30})]),
        ]),
        tools={"strategy_goal.create": spy},
        translator=_stub_translator("human_confirm_required", "越权杠杆"),
    )
    turn = rt.run("用 30 倍杠杆")
    assert called["n"] == 0, "翻译门非 ok 时绝不派发"
    assert turn.succeeded is False
    assert ("需人工确认" in turn.final_message) or ("未通过" in turn.final_message)


def test_translation_gate_probe_ok_allows_dispatch():
    """探针：同一 tool_call，translator=ok → 放行派发（证明翻译门确在拦、非 no-op）。"""
    called = {"n": 0}

    def spy(_n, _a):
        called["n"] += 1
        return {"ok": True}

    rt = AgentRuntime(
        _ScriptedLLM([
            LLMResponse(content="x", tool_calls=[_tool_call("strategy_goal.create", {"leverage": 1})]),
            LLMResponse(content="(终态)"),
        ]),
        tools={"strategy_goal.create": spy},
        translator=_stub_translator("ok"),
    )
    rt.run("正常")
    assert called["n"] == 1, "翻译门 ok 时应放行派发"


# ── 4. 前端 display-only：agent 对话页不直 fetch 业务/动钱端点 ───────────────
_FETCH_PAT = re.compile(r"""(?:authFetch|fetch)\(\s*[`'"]([^`'"]+)""")
# 真正高危的动钱/晋级/回测/跟单【执行】端点——绝不该出现在 agent 对话页（对话≠交易台）。
# 排除配置/只读类：如 /api/security/reload_secrets 是用户手动重载密钥的独立按钮、非 tool_call 桥接。
_BUSINESS_PREFIXES = (
    "/api/copy_trade/", "/api/ide/strategies/", "/api/ide/runs/",
    "/api/training/jobs/", "/api/models/", "/api/trading/",
    "/api/risk/kill_switch", "/api/security/mainnet", "/api/billing/upgrade",
)
_AGENT_PAGES = [
    FRONTEND_SRC / "pages" / "workshop" / "AgentChatPage.tsx",
    FRONTEND_SRC / "pages" / "workshop" / "Mode2ChatPage.tsx",
]


def _fetch_url_literals(text: str) -> list[str]:
    return _FETCH_PAT.findall(text)


@pytest.mark.skipif(not FRONTEND_SRC.exists(), reason="前端源不在此环境")
def test_agent_pages_are_display_only():
    checked = 0
    for page in _AGENT_PAGES:
        if not page.exists():
            continue
        checked += 1
        urls = _fetch_url_literals(page.read_text(encoding="utf-8"))
        offenders = [u for u in urls if any(b in u for b in _BUSINESS_PREFIXES)]
        assert not offenders, f"{page.name} 直接 fetch 业务/动钱端点（R11 前端旁路风险）：{offenders}"
        assert any("/api/agent/" in u for u in urls), \
            f"{page.name} 未见 /api/agent/* fetch，扫描可能失效（防空集假绿）"
    assert checked, "未找到任何 agent 对话页，扫描失效"


def test_frontend_display_only_probe(tmp_path):
    """探针：种一个 agent 页直调 /api/ide/.../run → 扫描必抓（证明 #4 非 no-op）。"""
    rogue = tmp_path / "Rogue.tsx"
    rogue.write_text("const go = () => authFetch(`/api/ide/strategies/${name}/run`, {method:'POST'})")
    urls = _fetch_url_literals(rogue.read_text(encoding="utf-8"))
    offenders = [u for u in urls if any(b in u for b in _BUSINESS_PREFIXES)]
    assert offenders, "探针：扫描应抓到 agent 页直调业务端点"
