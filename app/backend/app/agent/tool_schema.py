"""M14 · Agent 工具 schema。

OpenAPI 风格描述。Agent 调 LLM 时把这些当作 functions 传入；LLM 决策返回的
`tool_calls` 由 AgentRuntime 派发到真实后端服务。
"""

from __future__ import annotations

from typing import Any


TOOL_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "data.list_sources",
        "description": "列出当前所有数据源（官方 official / 用户 user）及各源覆盖的 markets 与 data_kinds；无开关、不隔离",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "data.describe_fields",
        "description": "某市场当前全部源的字段宇宙（canonical + freeform；官方字段带 official_ 前缀）及各数据集真实列",
        "parameters": {
            "type": "object",
            "properties": {"market": {"type": "string"}, "interval": {"type": "string"}},
            "required": ["market"],
        },
    },
    {
        "name": "data.infer_mapping",
        "description": "对用户源的陌生列名推断到 canonical 字段的映射建议（精确/近似/freeform），供人工确认",
        "parameters": {
            "type": "object",
            "properties": {
                "columns": {"type": "array", "items": {"type": "string"}},
                "market": {"type": "string"},
                "sample": {"type": "object"},
            },
            "required": ["columns"],
        },
    },
    {
        "name": "data.apply_mapping",
        "description": "把确认后的「原始列→canonical/freeform 字段」映射写入某 (源, data_kind)",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "data_kind": {"type": "string"},
                "mappings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "raw_column": {"type": "string"},
                            "field_id": {"type": "string"},
                            "is_freeform": {"type": "boolean"},
                        },
                        "required": ["raw_column", "field_id"],
                    },
                },
            },
            "required": ["source", "mappings"],
        },
    },
    {
        "name": "factor.validate_columns",
        "description": "校验因子表达式引用的列是否都在当前市场的可用字段宇宙内；缺失则给映射建议",
        "parameters": {
            "type": "object",
            "properties": {
                "formula": {"type": "string"},
                "market": {"type": "string"},
                "interval": {"type": "string"},
            },
            "required": ["formula", "market"],
        },
    },
    {
        "name": "data.pull",
        "description": "拉取一份数据集到本地（按 dataset_id + symbols + 日期范围）",
        "parameters": {
            "type": "object",
            "properties": {
                "connector": {"type": "string"},
                "symbol": {"type": "string"},
                "interval": {"type": "string", "enum": ["1m", "5m", "15m", "1h", "4h", "1d"]},
                "start": {"type": "string", "format": "date"},
                "end": {"type": "string", "format": "date"},
            },
            "required": ["connector", "symbol", "interval"],
        },
    },
    {
        "name": "strategy_goal.create",
        "description": "把一句话需求落成 StrategyGoal Pydantic 对象",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "asset_class": {"type": "string", "enum": ["equity_cn", "crypto_spot", "crypto_perp", "mixed"]},
                "objective": {"type": "string"},
                "horizon": {"type": "string", "enum": ["intraday", "daily", "weekly", "monthly"]},
                "benchmark": {"type": "string"},
                "constraints": {"type": "object"},
            },
            "required": ["name", "asset_class"],
        },
    },
    {
        "name": "factor.create_expression",
        "description": "在 FactorRegistry 注册一个表达式因子",
        "parameters": {
            "type": "object",
            "properties": {
                "factor_id": {"type": "string"},
                "formula": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["factor_id", "formula"],
        },
    },
    {
        "name": "factor.run_ic",
        "description": "对一批因子在给定 panel 上计算 IC / RankIC / IC 衰减",
        "parameters": {
            "type": "object",
            "properties": {
                "factor_ids": {"type": "string"},
                "horizons": {"type": "array", "items": {"type": "integer"}},
            },
        },
    },
    {
        "name": "model.train",
        "description": "训练一个 LightGBM / sklearn 模型 + Purged k-fold",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "enum": ["classification", "regression", "lambdarank"]},
                "feature_cols": {"type": "array", "items": {"type": "string"}},
                "label_col": {"type": "string"},
                "n_splits": {"type": "integer"},
            },
            "required": ["task", "feature_cols", "label_col"],
        },
    },
    {
        "name": "backtest.run",
        "description": "用 BacktestVenue 跑一次回测，输出标准 run 目录",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_goal_id": {"type": "string"},
                "factor_set": {"type": "string"},
                "model_id": {"type": "string"},
                "cost_preset": {"type": "string", "enum": ["optimistic", "neutral", "pessimistic"]},
            },
        },
    },
    {
        "name": "eval.pbo",
        "description": "对一组策略 returns matrix 跑 CSCV → PBO",
        "parameters": {
            "type": "object",
            "properties": {"s_blocks": {"type": "integer"}, "max_combinations": {"type": "integer"}},
        },
    },
    {
        "name": "eval.dsr",
        "description": "Deflated Sharpe Ratio",
        "parameters": {"type": "object", "properties": {"n_trials": {"type": "integer"}}},
    },
    {
        "name": "attribution.brinson",
        "description": "对一份 portfolio panel + benchmark panel 跑 Brinson 三层归因",
        "parameters": {"type": "object", "properties": {"group_col": {"type": "string"}}},
    },
    {
        "name": "experiment.compare",
        "description": "对比 N 个 run 的指标（sharpe / pbo / dsr / 回撤 等）",
        "parameters": {"type": "object", "properties": {"run_ids": {"type": "array", "items": {"type": "string"}}}},
    },
    {
        "name": "report.generate",
        "description": "把当前 run 输出渲染成 markdown 报告",
        "parameters": {"type": "object", "properties": {"run_id": {"type": "string"}}},
    },
    {
        "name": "code.replicate",
        "description": "把用户粘贴的 vnpy/backtrader/pandas 策略代码 → QuantBT 模板",
        "parameters": {
            "type": "object",
            "properties": {
                "source_dialect": {"type": "string", "enum": ["vnpy", "backtrader", "pandas", "qlib"]},
                "code": {"type": "string"},
            },
            "required": ["source_dialect", "code"],
        },
    },
]


def tool_openapi_skeleton() -> dict[str, Any]:
    """把 TOOL_SCHEMA 包装成 OpenAPI 风格 functions list。"""

    return {"functions": TOOL_SCHEMA, "version": "v0.4"}


__all__ = ["TOOL_SCHEMA", "tool_openapi_skeleton"]
