"""M14 · LLM 客户端抽象 + 开发期 DevLocalLLM。

用户在生产里可以挂 Claude / GPT-4 / Qwen / 本地 ollama；开发期由 `DevLocalLLM` 模拟
LLM 响应（基于关键词规则 + 预制模板），让 Agent UI 与流程能 e2e 跑通。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class LLMMessage:
    role: Role
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class NoLLMConfigured(RuntimeError):
    pass


class LLMClient(ABC):
    """所有 provider 实现的统一接口。"""

    provider: str

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse: ...


DevTemplate = Callable[[str, list[LLMMessage], list[dict[str, Any]] | None], LLMResponse]


class DevLocalLLM(LLMClient):
    """开发期 / CI 用的可预测 LLM。

    根据 user 最后一条 message 的关键词命中规则模板；命中后构造
    `tool_calls` 让 AgentRuntime 真去调用后端工具，闭环可测。

    支持注入额外模板：`DevLocalLLM(extra_templates=[...])`。
    """

    provider = "dev_local"

    def __init__(self, extra_templates: list[DevTemplate] | None = None) -> None:
        self._templates: list[DevTemplate] = [*_DEFAULT_TEMPLATES, *(extra_templates or [])]

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,  # noqa: ARG002
        temperature: float = 0.2,  # noqa: ARG002
    ) -> LLMResponse:
        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        text = (last_user.content if last_user else "").lower()
        for template in self._templates:
            try:
                response = template(text, messages, tools)
            except Exception:  # noqa: BLE001
                response = None
            if response is not None:
                return response
        return LLMResponse(content="（开发期 LLM 未命中模板）请用更具体的关键词，例如『a股 周频 选股』或『加密 资金费率 永续』。")


def _strategy_template(text: str, messages: list[LLMMessage], tools: list[dict[str, Any]] | None) -> LLMResponse | None:  # noqa: ARG001
    if "a股" in text and ("选股" in text or "周频" in text):
        tool_call = {
            "id": "call_strategy_goal_a_share",
            "name": "strategy_goal.create",
            "arguments": json.dumps(
                {
                    "name": "A股周频选股 Top 10%",
                    "asset_class": "equity_cn",
                    "objective": "info_ratio",
                    "horizon": "weekly",
                    "benchmark": "000300.SH",
                    "constraints": {"single_pos_max": 0.05, "max_dd": 0.20, "turnover_max": 0.30},
                }
            ),
        }
        return LLMResponse(
            content="我建议从 hs300 + zz500 池子起步，先用动量/反转 + 截面分位特征，目标函数 max IR。开始拉数前请确认。",
            tool_calls=[tool_call],
        )
    if "加密" in text and ("永续" in text or "资金费率" in text):
        tool_call = {
            "id": "call_strategy_goal_crypto",
            "name": "strategy_goal.create",
            "arguments": json.dumps(
                {
                    "name": "加密永续日频趋势",
                    "asset_class": "crypto_perp",
                    "objective": "max_calmar",
                    "horizon": "daily",
                    "benchmark": "BTC-USDT",
                    "constraints": {"single_pos_max": 0.20, "max_dd": 0.30, "leverage_max": 3.0, "short_allowed": True},
                }
            ),
        }
        return LLMResponse(
            content="加密永续策略，资金费率成本入账，建议 3x 杠杆上限。我先建 StrategyGoal，等你确认。",
            tool_calls=[tool_call],
        )
    return None


def _factor_template(text: str, messages: list[LLMMessage], tools: list[dict[str, Any]] | None) -> LLMResponse | None:  # noqa: ARG001
    if "因子" in text and ("ic" in text or "回测" in text):
        return LLMResponse(
            content="我用 alpha_lite 内置 30 因子先跑一遍 IC 衰减，给你前 5 个高 IC 的候选。",
            tool_calls=[{
                "id": "call_factor_ic",
                "name": "factor.run_ic",
                "arguments": json.dumps({"factor_ids": "alpha_lite_top30", "horizons": [1, 5, 10, 20]}),
            }],
        )
    return None


def _help_template(text: str, messages: list[LLMMessage], tools: list[dict[str, Any]] | None) -> LLMResponse | None:  # noqa: ARG001
    if any(k in text for k in ["你能做什么", "能力", "help"]):
        return LLMResponse(
            content=(
                "我可以帮你做四件事：\n"
                "1. 把一句话需求 → StrategyGoal（说『A股 周频 选股』或『加密 永续 趋势』触发）\n"
                "2. 跑因子 IC（说『因子 IC』）\n"
                "3. 复刻你粘贴的 vnpy/backtrader/pandas 策略代码到 QuantBT 模板\n"
                "4. 解读回测报告并给优化建议\n"
                "今天用的是开发期 LLM（DevLocalLLM）；接通真实模型后能力会更强。"
            )
        )
    return None


_DEFAULT_TEMPLATES: list[DevTemplate] = [_strategy_template, _factor_template, _help_template]


__all__ = [
    "DevLocalLLM",
    "DevTemplate",
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "NoLLMConfigured",
    "Role",
]
