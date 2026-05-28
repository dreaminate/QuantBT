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


def _mode2_socratic_template(text: str, messages: list[LLMMessage], tools: list[dict[str, Any]] | None) -> LLMResponse | None:  # noqa: ARG001
    """v0.8.6.1 · DevLocalLLM 的 Mode 2 教学型 fallback。

    检查 system prompt 是否含 'Mode 2'/'研究流程教练' → 走教学模板而不是 strategy 模板。
    针对常见量化问题给 Socratic / explain / refuse 回复，让没接真 LLM 的用户也能体验流程。
    """

    # 1. 检测是否 Mode 2 上下文（system prompt 含特征词）
    system_text = ""
    for m in messages:
        if m.role == "system":
            system_text = m.content
            break
    is_mode2 = "研究流程教练" in system_text or "Mode 2" in system_text
    if not is_mode2:
        return None

    # 2. refuse 类
    if any(s in text for s in ["a股实盘", "下单买入", "买入哪", "推荐买", "稳赚", "100% 收益", "保证收益"]):
        return LLMResponse(content=(
            "**结论：拒答（高风险问题）**\n\n"
            "我不能：(1) A 股不接券商，只能 paper trading；(2) 不能推荐具体买卖点；(3) 不能保证任何收益。\n\n"
            "建议你换个问法：\n"
            "- 你这次跑出来的策略 PBO / DSR / MaxDD 怎么样？\n"
            "- 你想验证的是因子方向、标签设计还是组合约束？\n"
            "- 你有 walk-forward 样本外结果吗？"
        ))

    # 3. PBO/DSR 解释类
    if "pbo" in text:
        return LLMResponse(content=(
            "**结论：解释（基于 RAG 命中 pbo 词条）**\n\n"
            "**证据**：\n"
            "- PBO (Probability of Backtest Overfitting) 是 Bailey-LdP 2014 CSCV 算法\n"
            "- 衡量 IS 选出的最优策略在 OOS 排到下半区的概率\n"
            "- 业界阈值: < 0.2 可信 / 0.2-0.4 警惕 / > 0.6 强烈过拟合\n\n"
            "**下一步实验**：先看你当前 run 的 PBO 是多少；如果 > 0.5，建议把参数搜索次数减半重跑。\n\n"
            "（DevLocalLLM fallback；接通真 LLM 后会给更具体的诊断）"
        ))
    if "dsr" in text or "deflated" in text:
        return LLMResponse(content=(
            "**结论：解释（基于 RAG 命中 deflated_sharpe）**\n\n"
            "**证据**：DSR = 校正多次试验偏差后的 Sharpe 真实有效概率，∈ [0, 1]。\n"
            "- > 0.95 强证据 / 0.5-0.8 模糊 / < 0.2 几乎是噪声\n"
            "- 输入需要 N (试验次数) + 收益序列偏度/峰度\n\n"
            "**下一步实验**：估算你的隐藏试验次数(包括 mentally try 过的参数)。Lopez de Prado 2018 建议至少按显式 N 的 10× 估。"
        ))

    # 4. "可信吗" / "好不好" 类 → Socratic ask
    if any(s in text for s in ["可信", "好不好", "怎么样", "如何评判"]):
        return LLMResponse(content=(
            "**结论：先问几个问题，再判断**\n\n"
            "1. 你这次最想验证的是因子方向、标签设计，还是组合约束？\n"
            "2. 如果只允许改一个参数，你认为最可能影响结果的是哪个？\n"
            "3. 你愿意先把 universe 缩小，还是先降低调参次数来检查 PBO？\n\n"
            "回答其中一条就能往下走。"
        ))

    # 5. "怎么改 / 优化" 类 → recommend experiment
    if any(s in text for s in ["怎么改", "下一步", "优化", "试试", "改进"]):
        return LLMResponse(content=(
            "**结论：下一次只改一个变量**\n\n"
            "几个常见 minimal experiment：\n"
            "- 把 label horizon 从 20 日 → 10 日\n"
            "- 把 factor lookback 从 20 日 → 30 日（看 IC-IR 是否更稳）\n"
            "- 在组合层加 max_single_weight=0.15 约束\n"
            "- 把交易成本调高一倍，看策略是否还站得住\n\n"
            "选一个，跑一次，对比 PBO / DSR / MaxDD。"
        ))

    # 6. 默认 Socratic
    return LLMResponse(content=(
        "**结论：信息不足**\n\n"
        "你想先聊收益指标可信度，还是先聊下一步实验设计？或者给我一个 active_run_id 让我对着具体数据说？\n\n"
        "（这是 DevLocalLLM Mode 2 fallback；正式接 Anthropic/Qwen 后能给更具体回答）"
    ))


_DEFAULT_TEMPLATES: list[DevTemplate] = [_mode2_socratic_template, _strategy_template, _factor_template, _help_template]


__all__ = [
    "DevLocalLLM",
    "DevTemplate",
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "NoLLMConfigured",
    "Role",
]
