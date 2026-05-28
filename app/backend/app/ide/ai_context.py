"""喂给 LLM 的策略写作上下文。

包含：
- 可用数据 connector 列表（含 sample 标的）
- 可用因子（lifecycle ∈ {QUALIFIED, PROBATION, OBSERVATION}）
- 白名单算子目录
- emit_result 协议 + 代码骨架
- 沙箱黑名单（禁 import / 禁调用）

设计：build_context() 一次性收集所有信息；调用方决定哪些 inject 到 system prompt。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


CODE_SKELETON = """\"\"\"我的策略 v1。\"\"\"
import math, statistics
# 沙箱允许: math / statistics / json / random / itertools / collections
# numpy / pandas / polars 也可（已预装）
# 禁: socket / subprocess / os.system / requests / urllib / open(远程)

# === 1. 准备 / 模拟数据（沙箱不联网，真数据需要先在主进程拉好放 DATA_DIR） ===
# 真接入数据的写法（后端会注入 DATA_DIR 环境变量）：
#   import polars as pl, os
#   df = pl.read_parquet(f"{os.environ['DATA_DIR']}/market/binance/BTCUSDT_1d.parquet")

# === 2. 计算因子 / 信号 ===
# 例：写一个 20 日动量
# returns_20 = (close / close.shift(20)) - 1
# signal = (returns_20 > 0).astype(int)

# === 3. 模拟下单 / 维护 equity_curve ===
equity_curve = []  # list of {"t": ts, "equity": float, "net_return": float, "benchmark_return": float?}
trades = []        # list of {"timestamp": ts, "symbol": str, "side": "BUY|SELL", "quantity": float, "price": float}

# TODO 真逻辑

# === 4. 必须用 quantbt.emit_result 在末尾输出 ===
quantbt.emit_result({
    "equity_curve": equity_curve,
    "trades": trades,
    "metadata": {
        "strategy_name": "我的策略 v1",
        "market": "crypto_perp",       # stocks_cn | crypto_perp | crypto_spot
        "frequency": "1d",
        "benchmark": "BTC-USDT",
    },
})
"""


EMIT_RESULT_SCHEMA = {
    "equity_curve": [
        {"t": "2026-01-01", "equity": 1.0000, "net_return": 0.0, "benchmark_return": 0.0},
        {"t": "2026-01-02", "equity": 1.0120, "net_return": 0.0120, "benchmark_return": 0.0050},
    ],
    "trades": [
        {"timestamp": "2026-01-02T09:30:00Z", "symbol": "BTC-USDT", "side": "BUY", "quantity": 0.01, "price": 67200.5},
    ],
    "metadata": {
        "strategy_name": "动量 v1",
        "market": "crypto_perp",
        "frequency": "1d",
        "benchmark": "BTC-USDT",
    },
}


SANDBOX_RULES = [
    "代码跑在 subprocess + rlimit + socket-monkey-patch 沙箱中，wallclock ≤ 30s / CPU ≤ 15s / 内存 ≤ 2GB",
    "禁止 import: socket / requests / urllib / http.client / ssl / pickle / subprocess / ftplib / smtplib",
    "禁止调用: os.system / os.popen / os.fork / os.exec* / os.chdir / subprocess.*",
    "必须在末尾用 `quantbt.emit_result({...})` 输出回测结果，equity_curve 是 promote 为正式 Run 的硬要求",
    "用户代码 cwd 是隔离 tempdir，写文件只能写到当前目录，单文件 ≤ 50MB",
]


@dataclass
class AIContext:
    connectors: list[dict[str, Any]]
    factors: list[dict[str, Any]]
    operators: list[dict[str, Any]]
    rules: list[str]
    code_skeleton: str
    emit_result_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "connectors": self.connectors,
            "factors": self.factors,
            "operators": self.operators,
            "rules": self.rules,
            "code_skeleton": self.code_skeleton,
            "emit_result_schema": self.emit_result_schema,
        }

    def to_system_prompt_block(self, *, max_factors: int = 20, max_operators: int = 30) -> str:
        """压缩到 LLM system prompt 块；避免超 token。"""

        connectors_brief = [
            f"- {c.get('name')} · {c.get('asset_class', '')} · {c.get('kind', '')}"
            for c in self.connectors[:10]
        ]
        factors_brief = [
            f"- {f.get('factor_id')} ({f.get('lifecycle_state', '')}) · {(f.get('description') or '')[:40]}"
            for f in self.factors[:max_factors]
        ]
        ops_brief = ", ".join(
            (o.get("name") if isinstance(o, dict) else str(o))
            for o in self.operators[:max_operators]
        )
        return (
            "## 可用数据 connector\n"
            + "\n".join(connectors_brief) + "\n\n"
            + f"## 可用因子（top {max_factors}）\n"
            + "\n".join(factors_brief) + "\n\n"
            + f"## 白名单算子（共 {len(self.operators)}）\n"
            + ops_brief + "\n\n"
            + "## 沙箱规则\n"
            + "\n".join(f"- {r}" for r in self.rules) + "\n\n"
            + "## emit_result schema（最末尾必须调）\n"
            + "```json\n" + json.dumps(self.emit_result_schema, ensure_ascii=False, indent=2) + "\n```\n"
        )


def build_ai_context(
    *,
    connectors: list[dict[str, Any]] | None = None,
    factors: list[dict[str, Any]] | None = None,
    operators: list[dict[str, Any]] | None = None,
) -> AIContext:
    """调用方传入注册表快照（main.py 注入），返回 AIContext。

    保持 pure-function，便于测试。
    """

    safe_connectors = [c for c in (connectors or []) if isinstance(c, dict)]
    safe_factors = [f for f in (factors or []) if isinstance(f, dict)]
    safe_operators = [o for o in (operators or []) if isinstance(o, dict)]

    # 因子：优先 QUALIFIED / PROBATION / OBSERVATION，过滤 RETIRED
    keep_states = {"QUALIFIED", "PROBATION", "OBSERVATION", "NEW"}
    safe_factors = [
        f for f in safe_factors
        if (f.get("lifecycle_state") or f.get("state") or "QUALIFIED") in keep_states
    ]

    return AIContext(
        connectors=safe_connectors,
        factors=safe_factors,
        operators=safe_operators,
        rules=SANDBOX_RULES,
        code_skeleton=CODE_SKELETON,
        emit_result_schema=EMIT_RESULT_SCHEMA,
    )


__all__ = [
    "AIContext",
    "CODE_SKELETON",
    "EMIT_RESULT_SCHEMA",
    "SANDBOX_RULES",
    "build_ai_context",
]
