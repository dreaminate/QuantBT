"""Agent Orchestrator · 12 role agent 登记 + 工具权限按台过滤（GOAL §7「后台 role agent」）。

GOAL §7 列了 12 个后台 role agent；本模块把它们登记为不可变 `RoleAgent`，每个绑定：
- `home_desk`：写权限归属台（复用 research_graph 的 DESK_* 单一源，不另立台名）。
- `permitted_tools`：该 role 在受控权限内可调的工具集（GOAL §7「工具权限按台过滤」的落点）。
  工具名是**能力类**抽象占位（read_asset / run_validation / …）——真业务工具在 business_tools.py
  （非本卡领地），本卡只定**权限模型**：dispatch 期按此白名单拒越权工具（governance.py 兑现）。
- `default_difficulty / default_risk`：交给 LLM Gateway 的能力需求默认档（可被单次 dispatch 覆盖）。
- `independence_capable`：是否 Verifier/Critic（要独立 provider/model·GOAL §7）。

诚实边界：工具白名单是**最小可证伪权限模型**，不号称穷尽真实工具目录；它保证的是「越白名单的
工具在 dispatch 期被拒」这条可测边界（种坏门必抓）。具体业务工具注册由 orchestrator 调用方按 role
注入，注入的工具名必须 ⊆ 该 role 的 permitted_tools，否则登记期即拒。
"""

from __future__ import annotations

from dataclasses import dataclass

from ...graph.research_graph import (
    DESK_BACKTEST,
    DESK_DATA,
    DESK_EXECUTION,
    DESK_FACTOR,
    DESK_MODEL,
    DESK_RESEARCH,
    DESK_SIGNAL,
    DESK_STRATEGY,
    DESKS,
)
from ...llm.routing import RiskLevel, RoleCapabilityRequest, TaskDifficulty

# ── 12 role agent 名（GOAL §7「后台 role agent」逐条）─────────────────────────────
ROLE_COORDINATOR = "coordinator_planner"          # Coordinator / Planner
ROLE_LITERATURE = "literature_researcher"         # Literature Researcher
ROLE_MATH = "mathematical_researcher"             # Mathematical Researcher
ROLE_DATA = "data_engineer"                       # Data Engineer
ROLE_FACTOR = "factor_engineer"                   # Factor Engineer
ROLE_MODEL = "model_engineer"                     # Model Engineer
ROLE_SIGNAL = "signal_engineer"                   # Signal Engineer
ROLE_STRATEGYBOOK = "strategybook_engineer"       # StrategyBook Engineer
ROLE_BACKTEST = "backtest_engineer"               # Backtest Engineer
ROLE_RISK = "risk_analyst"                        # Risk Analyst
ROLE_VERIFIER = "verifier_critic"                 # Verifier / Critic
ROLE_REPORTER = "reporter"                        # Reporter

# 抽象能力类工具（GOAL §7「tool / asset / code / math / data operations」）——权限模型占位。
TOOL_READ_ASSET = "read_asset"
TOOL_RAG_SEARCH = "rag_search"
TOOL_EXTRACT_EVIDENCE = "extract_evidence"
TOOL_WRITE_MATH = "write_math"
TOOL_CHECK_CONSISTENCY = "check_consistency"
TOOL_REGISTER_DATA = "register_data"
TOOL_QUALITY_CHECK = "quality_check"
TOOL_DEFINE_FACTOR = "define_factor"
TOOL_COMPUTE_IC = "compute_ic"
TOOL_TRAIN_MODEL = "train_model"
TOOL_MODEL_CARD = "model_card"
TOOL_DEFINE_SIGNAL = "define_signal"
TOOL_BUILD_STRATEGYBOOK = "build_strategybook"
TOOL_RUN_BACKTEST = "run_backtest"
TOOL_RUN_VALIDATION = "run_validation"
TOOL_RISK_CHECK = "risk_check"
TOOL_RAISE_CHALLENGE = "raise_challenge"
TOOL_WRITE_REPORT = "write_report"
TOOL_PROPOSE_PLAN = "propose_plan"
TOOL_OPEN_HANDOFF = "open_handoff"


@dataclass(frozen=True)
class RoleAgent:
    """一个后台 role agent 的登记（GOAL §7）。frozen——登记表是不可变单一源。"""

    name: str
    home_desk: str
    permitted_tools: frozenset[str]
    default_difficulty: str
    default_risk: str
    independence_capable: bool = False

    def __post_init__(self) -> None:
        if self.home_desk not in DESKS:
            raise ValueError(f"RoleAgent {self.name!r} home_desk 非法台：{self.home_desk!r}")

    def capability(
        self,
        *,
        difficulty: str | None = None,
        risk: str | None = None,
        independence_required: bool | None = None,
        replay_required: bool = False,
    ) -> RoleCapabilityRequest:
        """构造交给 LLM Gateway 的能力需求（GOAL §7：role 提交能力需求/上下文/权限/replay）。

        Verifier/Critic 默认 `independence_required=True`（GOAL §7：要独立 provider/model）；
        其余 role 默认不要求独立。难度/风险缺省取 role 默认档，可被单次覆盖。
        """

        indep = self.independence_capable if independence_required is None else independence_required
        return RoleCapabilityRequest(
            role=self.name,
            difficulty=difficulty or self.default_difficulty,
            risk=risk or self.default_risk,
            independence_required=bool(indep),
            replay_required=replay_required,
        )

    def permits(self, tool: str) -> bool:
        return tool in self.permitted_tools


_HARD = TaskDifficulty.HARD.value
_NORMAL = TaskDifficulty.NORMAL.value
_RISK_NORMAL = RiskLevel.NORMAL.value
_RISK_ELEVATED = RiskLevel.ELEVATED.value

# 12 role agent 登记表（GOAL §7）——每个 role 的工具白名单 = 工具权限按台过滤的落点。
ROLE_AGENTS: dict[str, RoleAgent] = {
    ROLE_COORDINATOR: RoleAgent(
        name=ROLE_COORDINATOR,
        home_desk=DESK_RESEARCH,
        permitted_tools=frozenset({TOOL_PROPOSE_PLAN, TOOL_OPEN_HANDOFF, TOOL_READ_ASSET}),
        default_difficulty=_HARD,  # 规划/编排是硬推理（GOAL §7 Plan 形态）
        default_risk=_RISK_NORMAL,
    ),
    ROLE_LITERATURE: RoleAgent(
        name=ROLE_LITERATURE,
        home_desk=DESK_RESEARCH,
        permitted_tools=frozenset({TOOL_RAG_SEARCH, TOOL_EXTRACT_EVIDENCE, TOOL_READ_ASSET}),
        default_difficulty=_NORMAL,
        default_risk=_RISK_NORMAL,
    ),
    ROLE_MATH: RoleAgent(
        name=ROLE_MATH,
        home_desk=DESK_RESEARCH,
        permitted_tools=frozenset({TOOL_WRITE_MATH, TOOL_CHECK_CONSISTENCY, TOOL_READ_ASSET}),
        default_difficulty=_HARD,  # 数学推导是硬推理（GOAL §7 Mathematical Researcher）
        default_risk=_RISK_NORMAL,
    ),
    ROLE_DATA: RoleAgent(
        name=ROLE_DATA,
        home_desk=DESK_DATA,
        permitted_tools=frozenset({TOOL_REGISTER_DATA, TOOL_QUALITY_CHECK, TOOL_READ_ASSET}),
        default_difficulty=_NORMAL,
        default_risk=_RISK_ELEVATED,  # 数据接入触 PIT/泄露风险面
    ),
    ROLE_FACTOR: RoleAgent(
        name=ROLE_FACTOR,
        home_desk=DESK_FACTOR,
        permitted_tools=frozenset({TOOL_DEFINE_FACTOR, TOOL_COMPUTE_IC, TOOL_READ_ASSET}),
        default_difficulty=_NORMAL,
        default_risk=_RISK_NORMAL,
    ),
    ROLE_MODEL: RoleAgent(
        name=ROLE_MODEL,
        home_desk=DESK_MODEL,
        permitted_tools=frozenset({TOOL_TRAIN_MODEL, TOOL_MODEL_CARD, TOOL_READ_ASSET}),
        default_difficulty=_HARD,  # 模型方案/训练是硬推理
        default_risk=_RISK_NORMAL,
    ),
    ROLE_SIGNAL: RoleAgent(
        name=ROLE_SIGNAL,
        home_desk=DESK_SIGNAL,
        permitted_tools=frozenset({TOOL_DEFINE_SIGNAL, TOOL_READ_ASSET}),
        default_difficulty=_NORMAL,
        default_risk=_RISK_NORMAL,
    ),
    ROLE_STRATEGYBOOK: RoleAgent(
        name=ROLE_STRATEGYBOOK,
        home_desk=DESK_STRATEGY,
        permitted_tools=frozenset({TOOL_BUILD_STRATEGYBOOK, TOOL_READ_ASSET}),
        default_difficulty=_NORMAL,
        default_risk=_RISK_ELEVATED,  # 组合/成本/约束面
    ),
    ROLE_BACKTEST: RoleAgent(
        name=ROLE_BACKTEST,
        home_desk=DESK_BACKTEST,
        permitted_tools=frozenset({TOOL_RUN_BACKTEST, TOOL_RUN_VALIDATION, TOOL_READ_ASSET}),
        default_difficulty=_HARD,  # 验证/反证设计是硬推理
        default_risk=_RISK_NORMAL,
    ),
    ROLE_RISK: RoleAgent(
        name=ROLE_RISK,
        home_desk=DESK_EXECUTION,
        permitted_tools=frozenset({TOOL_RISK_CHECK, TOOL_READ_ASSET}),
        default_difficulty=_NORMAL,
        default_risk=_RISK_ELEVATED,  # 风控/执行面
    ),
    ROLE_VERIFIER: RoleAgent(
        name=ROLE_VERIFIER,
        home_desk=DESK_BACKTEST,  # 验证台是其挑战落点（实验/PBO/反证）
        permitted_tools=frozenset({TOOL_READ_ASSET, TOOL_RUN_VALIDATION, TOOL_RAISE_CHALLENGE}),
        default_difficulty=_HARD,  # 挑战/找反例是硬推理
        default_risk=_RISK_NORMAL,
        independence_capable=True,  # GOAL §7：Verifier/Critic 要独立 provider/model
    ),
    ROLE_REPORTER: RoleAgent(
        name=ROLE_REPORTER,
        home_desk=DESK_RESEARCH,
        permitted_tools=frozenset({TOOL_READ_ASSET, TOOL_WRITE_REPORT}),
        default_difficulty=_NORMAL,
        default_risk=_RISK_NORMAL,
    ),
}

# import 期自检：必须恰好 12 个 role（GOAL §7「后台 role agent」逐条列 12）。
if len(ROLE_AGENTS) != 12:
    raise RuntimeError(
        f"ROLE_AGENTS 必须恰好登记 GOAL §7 的 12 个 role agent（实得 {len(ROLE_AGENTS)}）"
    )

ROLE_NAMES: frozenset[str] = frozenset(ROLE_AGENTS)


class UnknownRoleError(KeyError):
    pass


def get_role(name: str) -> RoleAgent:
    role = ROLE_AGENTS.get(name)
    if role is None:
        raise UnknownRoleError(
            f"未知 role agent {name!r} ∉ GOAL §7 的 12 role（{sorted(ROLE_NAMES)}）"
        )
    return role


def is_verifier(name: str) -> bool:
    role = ROLE_AGENTS.get(name)
    return bool(role and role.independence_capable)


__all__ = [
    "ROLE_COORDINATOR",
    "ROLE_LITERATURE",
    "ROLE_MATH",
    "ROLE_DATA",
    "ROLE_FACTOR",
    "ROLE_MODEL",
    "ROLE_SIGNAL",
    "ROLE_STRATEGYBOOK",
    "ROLE_BACKTEST",
    "ROLE_RISK",
    "ROLE_VERIFIER",
    "ROLE_REPORTER",
    "ROLE_AGENTS",
    "ROLE_NAMES",
    "RoleAgent",
    "UnknownRoleError",
    "get_role",
    "is_verifier",
    # 工具能力类常量
    "TOOL_READ_ASSET",
    "TOOL_RAG_SEARCH",
    "TOOL_EXTRACT_EVIDENCE",
    "TOOL_WRITE_MATH",
    "TOOL_CHECK_CONSISTENCY",
    "TOOL_REGISTER_DATA",
    "TOOL_QUALITY_CHECK",
    "TOOL_DEFINE_FACTOR",
    "TOOL_COMPUTE_IC",
    "TOOL_TRAIN_MODEL",
    "TOOL_MODEL_CARD",
    "TOOL_DEFINE_SIGNAL",
    "TOOL_BUILD_STRATEGYBOOK",
    "TOOL_RUN_BACKTEST",
    "TOOL_RUN_VALIDATION",
    "TOOL_RISK_CHECK",
    "TOOL_RAISE_CHALLENGE",
    "TOOL_WRITE_REPORT",
    "TOOL_PROPOSE_PLAN",
    "TOOL_OPEN_HANDOFF",
]
