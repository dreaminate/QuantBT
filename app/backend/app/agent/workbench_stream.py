"""A4 · agent 工作台结构化 SSE 投影（把 AgentTurn 投影成前端 7 种 block 事件）。

纯投影逻辑（与 FastAPI 解耦，便于用 scripted runtime 单测 tool_start/tool_end/gate/milestone/
thinking/say/milestone/done 事件序列）。治理：

  · gate 挂起严格走 agent_runtime.permission_gate(mode, side_effect)——realmoney 恒 confirm（含
    bypass），权限轴 ⟂ 治理轴（D-PERM）。
  · tool 的 side_effect 取自 runtime 真值（runtime._side_effects），前端不伪造。
  · 不在此执行任何工具/动钱——只把已跑完的 turn 投影成事件（执行/挂起判定在 AgentRuntime.run 里）。
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from .agent_runtime import permission_gate

# tool_name → 里程碑 key（策略台脊柱 7 节点；前端进度线据此点亮）。
TOOL_MILESTONE: dict[str, str] = {
    "hypothesis.create": "立题",
    "data.describe_fields": "市场",
    "data.list_sources": "市场",
    "factor_set.compose": "因子集",
    "model_registry.select": "模型",
    "signal.define": "信号",
    "portfolio.construct": "仓位风控",
    "backtest.run": "回测",
}


def _tool_name(call: dict[str, Any]) -> str:
    return call.get("name") or call.get("function", {}).get("name", "")


def project_turn_events(
    turn,
    *,
    side_effects: dict[str, str],
    permission_mode: str,
) -> Iterator[dict[str, Any]]:
    """把一个 AgentTurn 投影成结构化事件 dict 序列（event + data）。

    事件类型：thinking / say / tool_start / tool_end / gate / milestone。
    （user/done/error 由调用方（端点）在前后补——它们不属于 turn 内部投影。）
    """

    reached: list[str] = []
    for step in turn.steps:
        role = step.role
        if role == "assistant" and step.content and not step.tool_calls:
            yield {"event": "say", "data": {"text": step.content}}
        if role == "assistant" and step.tool_calls:
            if step.content:
                yield {"event": "thinking", "data": {"text": step.content}}
            for call in step.tool_calls:
                tname = _tool_name(call)
                se = side_effects.get(tname, "none")  # 受控真值单一源
                # 治理门：是否需确认（realmoney 恒 confirm，含 bypass）。
                if permission_gate(permission_mode, se) == "confirm":
                    yield {"event": "gate",
                           "data": {"tool": tname, "side_effect": se,
                                    "governance_weakness": se in ("realmoney", "external")}}
                else:
                    yield {"event": "tool_start", "data": {"tool": tname, "side_effect": se}}
        if role == "system" and step.content:
            yield {"event": "say", "data": {"text": step.content}}
        if role == "tool":
            try:
                payload = json.loads(step.content)
            except Exception:  # noqa: BLE001
                payload = {"raw": step.content}
            # DS-3 贯穿：若 tool 结果里带 run_id（backtest.run 落 RUN_ROOT 的真 run_id），
            # 提升到 tool_end 事件顶层，方便前端 onToolEnd 直取贯穿裁决/paper（不必前端再翻 result）。
            data: dict[str, Any] = {"result": payload}
            if isinstance(payload, dict):
                rid = payload.get("run_id")
                if rid:
                    data["run_id"] = str(rid)
            yield {"event": "tool_end", "data": data}
    # 里程碑事件：从执行过的 tool 推出（点亮进度线）。
    for step in turn.steps:
        for call in (step.tool_calls or []):
            tname = _tool_name(call)
            ms = TOOL_MILESTONE.get(tname)
            if ms and ms not in reached:
                reached.append(ms)
                yield {"event": "milestone", "data": {"key": ms, "tool": tname}}


def sse_format(event: str, data: dict[str, Any]) -> str:
    """格式化成 SSE 帧（event: + data:）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


__all__ = ["TOOL_MILESTONE", "project_turn_events", "sse_format"]
