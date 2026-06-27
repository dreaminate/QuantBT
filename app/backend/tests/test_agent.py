from __future__ import annotations

import json

import pytest

from app.agent import (
    AgentRuntime,
    CodeReplicator,
    DevLocalLLM,
    StrategyGoalSlotFiller,
    TOOL_SCHEMA,
)


def test_tool_schema_has_minimum_set() -> None:
    names = {t["name"] for t in TOOL_SCHEMA}
    expected = {"strategy_goal.create", "factor.create_expression", "factor.run_ic", "model.train", "backtest.run", "code.replicate"}
    assert expected.issubset(names)


def test_dev_local_llm_returns_template_for_a_share() -> None:
    llm = DevLocalLLM()
    rs = llm.chat([__user_msg("我想做一个 A股 周频 选股策略，目标 IR")], tools=TOOL_SCHEMA)
    assert rs.tool_calls
    args = json.loads(rs.tool_calls[0]["arguments"])
    assert args["asset_class"] == "equity_cn"


def test_dev_local_llm_returns_template_for_crypto_perp() -> None:
    llm = DevLocalLLM()
    rs = llm.chat([__user_msg("加密永续 资金费率 趋势")], tools=TOOL_SCHEMA)
    assert rs.tool_calls
    args = json.loads(rs.tool_calls[0]["arguments"])
    assert args["asset_class"] == "crypto_perp"


def test_strategy_goal_slot_filling_a_share() -> None:
    filler = StrategyGoalSlotFiller()
    goal = filler.fill("做 A股 周频 选股，回撤 15%，单标的 5%")
    assert goal.asset_class == "equity_cn"
    assert goal.horizon == "weekly"
    assert goal.constraints.max_dd == 0.15
    assert goal.constraints.single_pos_max == 0.05
    assert goal.constraints.leverage_max == 1.0


def test_strategy_goal_slot_filling_crypto_perp_with_leverage() -> None:
    filler = StrategyGoalSlotFiller()
    goal = filler.fill("加密 永续 日频 趋势，做空允许，杠杆 4x")
    assert goal.asset_class == "crypto_perp"
    assert goal.constraints.leverage_max == 4.0
    assert goal.constraints.short_allowed


def test_code_replicator_pandas_finds_function() -> None:
    code = """
import pandas as pd

def predict(df):
    return df['close'].rolling(20).mean()
"""
    report = CodeReplicator().replicate(code, dialect="pandas")
    assert "predict" in report.target_code
    assert report.dialect == "pandas"


def test_code_replicator_vnpy_warns_about_orders() -> None:
    code = """
class MyStrategy:
    def on_bar(self, bar):
        if bar.close > bar.open:
            self.buy(bar.close, 1)
"""
    report = CodeReplicator().replicate(code, dialect="vnpy")
    assert any("vnpy" in n.lower() or "禁止" in n for n in report.notes)
    assert "ExecutionVenue" in report.target_code


def test_agent_runtime_invokes_tool_and_returns_final_message() -> None:
    llm = DevLocalLLM()
    calls: list[str] = []

    def fake_strategy_goal(_name, args):
        calls.append("strategy_goal")
        return {"strategy_goal_id": "sg-1", "echo": args}

    runtime = AgentRuntime(llm, tools={"strategy_goal.create": fake_strategy_goal})
    turn = runtime.run("我想做一个 A股 周频 选股策略")
    assert "strategy_goal" in calls
    # 第二轮 LLM 没有 tool_calls 模板（不是 a股/加密/help 关键词）→ 退回默认终态
    assert turn.steps[-1].role in {"assistant", "tool"}


def test_agent_help_template() -> None:
    runtime = AgentRuntime(DevLocalLLM())
    turn = runtime.run("你能做什么")
    assert turn.succeeded
    assert "可以处理四类请求" in turn.final_message


def __user_msg(text: str):
    from app.agent import LLMMessage
    return LLMMessage(role="user", content=text)
