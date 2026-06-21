"""聚宽风 IDE · 子进程沙箱 + 策略文件 CRUD + 真回测协议。

设计要点 (GOAL §10 + 三联硬约束)：
- 用户 Python 代码跑在 **subprocess** 里，主进程永远不 exec 用户代码
- 沙箱：resource.setrlimit (CPU/RSS/FSIZE/NOFILE) + socket monkey-patch
  + isolated python (-I) + chdir 到 tempdir + wallclock timeout
- 用户代码必须在 stdout 最后一行 print JSON {"equity_curve": [...], "trades": [...]}
- 后端解析 JSON → 落 runs/<run_id>/ → 复用现有 run.json + metrics pipeline
- AI 辅助 = 现有 /api/agent/chat + system prompt "你是策略代码助手"
"""

from __future__ import annotations

from .ai_context import AIContext, build_ai_context
from .promote import PromoteError, PromotedRun, promote_ide_run
from .sandbox import SandboxResult, run_user_strategy
from .service import IDEError, IDEService, StrategyFile, StrategyVersion
from .strategy_graph import compat, strategy_content_hash, validate_graph

__all__ = [
    "AIContext",
    "IDEError",
    "IDEService",
    "PromoteError",
    "PromotedRun",
    "SandboxResult",
    "StrategyFile",
    "StrategyVersion",
    "build_ai_context",
    "compat",
    "promote_ide_run",
    "run_user_strategy",
    "strategy_content_hash",
    "validate_graph",
]
