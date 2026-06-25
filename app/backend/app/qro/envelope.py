"""QRO · 统一研究对象信封（GOAL §1 统一对象模型）——对象脊柱地基。

这是 QuantBT 所有受治理资产（factor / model / signal / strategy_book / policy / 数学产物 …）
共享的**身份 + 状态 + 治理**信封。GOAL §1：所有正式入口进入同一条链
`Quant Intent → QRO → Research Graph → Governed Compiler → … → Runtime`，
ResearchGraph / CanonicalCommand / Compiler / Canvas / Agent OS 的写路径都经它。

为什么是「信封」而不是「重写资产」（RULES §4 扩展不替换 + §1 单一源）：
- 现有资产（`factor_factory.registry.Factor` / `signal_contract.SignalContract` /
  `models.catalog.ModelCard` / `strategy.candidate_pool` 候选）已各自有身份与生命周期，
  本模块**只挂信封、不改它们**——`from_*` 适配器读其字段、复用其 id，绝不另造第二套身份。
- 身份只有一个源：`lineage.ids.content_hash`（决策 S1/S4）。QRO identity = `qro_` + content_hash(...)，
  与 `spine.py` 的 `math_`/`tib_`/`cc_` 同一哈希族同一前缀范式——**绝不**新造哈希算法。

四个命门（可证伪验收 · 种坏门必抓 · RULES §2）：
1. actor 必须 ∈ 四类动作来源（GOAL §0）——非四类即拒。
2. Signal QRO 必须携带 typed input/output contract（GOAL §1：Signal 未绑定 Signal Contract → 拒）。
3. 状态轴**分离·不混单绿灯**：definition/evidence/governance/runtime 各自独立判定，
   `axis_clearance` 要四轴各自达强终态才放「整体绿」——任一轴弱（如 evidence 缺）即使
   governance 绿也**绝不**整体绿（GOAL §0/§1 可证伪验收）。
4. 语义边界：模型本体进 Model Registry、不进 Factor Library（GOAL §1 + 决策 R17）——
   `admit_factor_qro` 复用 `signal_contract.admit_artifact_to_factor_lib`（单一源范畴门）。

诚实边界（本模块**不**做什么）：
- 它**不**判定 evidence 是否真充分 / 理论是否真证明——那是验证官（`verification`）、
  一致性门（`spine_gate.evaluate_promotion`）的活。本信封只承载**声明的**状态轴 + 强制
  四轴分离结构，绝不把任一轴的绿渲染成整体可信。
- `theory` / `consistency` 两轴是 GOAL §1 状态轴的一部分（信封如实承载），但其**强标签裁定**
  （proof_backed 是否成立）归 `spine_gate`，本模块不重算理论一致性逻辑（避免双源）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..lineage.ids import content_hash

# ─────────────────────────────────────────────────────────────────────────────
# Actor · 四类动作来源（GOAL §0：四类动作共享同一套 QRO / Research Graph / 审计）
# 非这四类即非法——agent 动作与 user 动作进同一 audit/lineage，但来源必须如实标。
# ─────────────────────────────────────────────────────────────────────────────
ACTOR_USER_MANUAL = "user_manual"
ACTOR_AGENT = "agent"
ACTOR_USER_CONFIRMED_AGENT = "user_confirmed_agent"
ACTOR_SCHEDULED_AGENT = "scheduled_agent"
ACTOR_CLASSES = frozenset(
    {ACTOR_USER_MANUAL, ACTOR_AGENT, ACTOR_USER_CONFIRMED_AGENT, ACTOR_SCHEDULED_AGENT}
)

# ─────────────────────────────────────────────────────────────────────────────
# 状态轴分离（GOAL §1「状态轴分离」）——六轴各自独立枚举，绝不混成单一 bool。
# 四个**核心轴**（definition/evidence/governance/runtime）是「不混单绿灯」命门作用面；
# theory/consistency 两轴如实承载，强标签裁定归 spine_gate（不在此重算）。
# ─────────────────────────────────────────────────────────────────────────────
# definition：定义成熟度
DEFINITION_DRAFT = "draft"
DEFINITION_SPECIFIED = "specified"
DEFINITION_IMPLEMENTED = "implemented"
DEFINITION_STATES = frozenset({DEFINITION_DRAFT, DEFINITION_SPECIFIED, DEFINITION_IMPLEMENTED})

# theory：理论成熟度（GOAL §1）
THEORY_NOT_REQUIRED = "not_required"
THEORY_REQUIRED = "required"
THEORY_DRAFTED = "drafted"
THEORY_DERIVED = "derived"
THEORY_CHALLENGED = "challenged"
THEORY_ACCEPTED = "accepted"
THEORY_USER_WAIVED = "user_waived"
THEORY_STATES = frozenset(
    {
        THEORY_NOT_REQUIRED,
        THEORY_REQUIRED,
        THEORY_DRAFTED,
        THEORY_DERIVED,
        THEORY_CHALLENGED,
        THEORY_ACCEPTED,
        THEORY_USER_WAIVED,
    }
)

# consistency：理论↔实现一致性（GOAL §1）
CONSISTENCY_NOT_APPLICABLE = "not_applicable"
CONSISTENCY_UNBOUND = "unbound"
CONSISTENCY_CHECKED = "checked"
CONSISTENCY_MISMATCH = "mismatch"
CONSISTENCY_ACCEPTED = "accepted"
CONSISTENCY_WAIVED_FOR_EXPLORATORY = "waived_for_exploratory"
CONSISTENCY_STATES = frozenset(
    {
        CONSISTENCY_NOT_APPLICABLE,
        CONSISTENCY_UNBOUND,
        CONSISTENCY_CHECKED,
        CONSISTENCY_MISMATCH,
        CONSISTENCY_ACCEPTED,
        CONSISTENCY_WAIVED_FOR_EXPLORATORY,
    }
)

# evidence：证据强度（GOAL §1）
EVIDENCE_UNTESTED = "untested"
EVIDENCE_EXPLORATORY = "exploratory"
EVIDENCE_CHALLENGED = "challenged"
EVIDENCE_SUFFICIENT = "sufficient"
EVIDENCE_INSUFFICIENT = "insufficient"
EVIDENCE_UNVERIFIED_RESIDUAL = "unverified_residual"
EVIDENCE_STATES = frozenset(
    {
        EVIDENCE_UNTESTED,
        EVIDENCE_EXPLORATORY,
        EVIDENCE_CHALLENGED,
        EVIDENCE_SUFFICIENT,
        EVIDENCE_INSUFFICIENT,
        EVIDENCE_UNVERIFIED_RESIDUAL,
    }
)

# governance：治理状态（GOAL §1）
GOVERNANCE_UNREVIEWED = "unreviewed"
GOVERNANCE_APPROVED = "approved"
GOVERNANCE_REJECTED = "rejected"
GOVERNANCE_REVOKED = "revoked"
GOVERNANCE_STATES = frozenset(
    {GOVERNANCE_UNREVIEWED, GOVERNANCE_APPROVED, GOVERNANCE_REJECTED, GOVERNANCE_REVOKED}
)

# runtime：部署阶梯（GOAL §1 + §12 live ladder · 默认 offline = deny-by-default）
RUNTIME_OFFLINE = "offline"
RUNTIME_PAPER = "paper"
RUNTIME_TESTNET = "testnet"
RUNTIME_LIVE = "live"
RUNTIME_SUSPENDED = "suspended"
RUNTIME_RETIRED = "retired"
RUNTIME_STATES = frozenset(
    {RUNTIME_OFFLINE, RUNTIME_PAPER, RUNTIME_TESTNET, RUNTIME_LIVE, RUNTIME_SUSPENDED, RUNTIME_RETIRED}
)

# 轴名 → 合法枚举（__post_init__ 逐轴校验；漂一个值即拒）。
_AXIS_ENUMS: dict[str, frozenset[str]] = {
    "definition": DEFINITION_STATES,
    "theory": THEORY_STATES,
    "consistency": CONSISTENCY_STATES,
    "evidence": EVIDENCE_STATES,
    "governance": GOVERNANCE_STATES,
    "runtime": RUNTIME_STATES,
}

# 「不混单绿灯」命门的核心四轴 + 各轴的强终态。
# 任一轴未达强终态 → axis_clearance.cleared 必 False（四轴合取，绝不单轴放绿）。
CORE_AXES: tuple[str, ...] = ("definition", "evidence", "governance", "runtime")
# runtime 的强终态 = 已实际部署在某个执行环境（offline/suspended/retired 不算「整体绿」）。
_RUNTIME_DEPLOYED = frozenset({RUNTIME_PAPER, RUNTIME_TESTNET, RUNTIME_LIVE})

# ─────────────────────────────────────────────────────────────────────────────
# Object types（GOAL §1 QRO 覆盖全列；snake_case 规范）
# ─────────────────────────────────────────────────────────────────────────────
# 数据 / 摄入面
OBJ_DATASET = "dataset"
OBJ_OBSERVABLE = "observable"
OBJ_DATA_SOURCE_ASSET = "data_source_asset"
OBJ_INTEGRATION_CONFIG = "integration_config"
OBJ_SECRET_REF = "secret_ref"
OBJ_TOKEN_REF = "token_ref"
OBJ_INGESTION_SKILL = "ingestion_skill"
OBJ_DATASET_VERSION = "dataset_version"
OBJ_FRESHNESS_STATUS = "freshness_status"
OBJ_SCHEMA_DRIFT_EVENT = "schema_drift_event"
# 数学 / 理论面
OBJ_THEORY_SPEC = "theory_spec"
OBJ_MATHEMATICAL_REQUIREMENT = "mathematical_requirement"
OBJ_THEORY_IMPLEMENTATION_BINDING = "theory_implementation_binding"
OBJ_CONSISTENCY_CHECK = "consistency_check"
OBJ_METHODOLOGY_CHOICE_RECORD = "methodology_choice_record"
OBJ_RESPONSIBILITY_DISCLOSURE_RECORD = "responsibility_disclosure_record"
OBJ_MATHEMATICAL_ARTIFACT = "mathematical_artifact"
OBJ_DOCUMENT_ARTIFACT = "document_artifact"
# LLM 面
OBJ_LLM_PROVIDER = "llm_provider"
OBJ_LLM_PROVIDER_AUTH = "llm_provider_auth"
OBJ_LLM_CREDENTIAL_POOL = "llm_credential_pool"
OBJ_LLM_MODEL_PROFILE = "llm_model_profile"
OBJ_MODEL_ROUTING_POLICY = "model_routing_policy"
OBJ_LLM_CALL_RECORD = "llm_call_record"
OBJ_PROVIDER_HEALTH = "provider_health"
OBJ_PROVIDER_QUOTA_STATUS = "provider_quota_status"
# 研究资产面（语义边界命门集中在此）
OBJ_FACTOR = "factor"
OBJ_LABEL = "label"
OBJ_MODEL = "model"
OBJ_FORECAST = "forecast"
OBJ_SIGNAL = "signal"
OBJ_STRATEGY_BOOK = "strategy_book"
OBJ_PORTFOLIO_POLICY = "portfolio_policy"
OBJ_RISK_POLICY = "risk_policy"
OBJ_EXECUTION_POLICY = "execution_policy"
OBJ_EXPERIMENT = "experiment"
OBJ_BACKTEST_RUN = "backtest_run"
OBJ_VALIDATION_DOSSIER = "validation_dossier"
OBJ_RESEARCH_REPORT = "research_report"
OBJ_DESK_HANDOFF = "desk_handoff"
OBJ_MARKET_CAPABILITY_MATRIX = "market_capability_matrix"

OBJECT_TYPES = frozenset(
    {
        OBJ_DATASET,
        OBJ_OBSERVABLE,
        OBJ_DATA_SOURCE_ASSET,
        OBJ_INTEGRATION_CONFIG,
        OBJ_SECRET_REF,
        OBJ_TOKEN_REF,
        OBJ_INGESTION_SKILL,
        OBJ_DATASET_VERSION,
        OBJ_FRESHNESS_STATUS,
        OBJ_SCHEMA_DRIFT_EVENT,
        OBJ_THEORY_SPEC,
        OBJ_MATHEMATICAL_REQUIREMENT,
        OBJ_THEORY_IMPLEMENTATION_BINDING,
        OBJ_CONSISTENCY_CHECK,
        OBJ_METHODOLOGY_CHOICE_RECORD,
        OBJ_RESPONSIBILITY_DISCLOSURE_RECORD,
        OBJ_MATHEMATICAL_ARTIFACT,
        OBJ_DOCUMENT_ARTIFACT,
        OBJ_LLM_PROVIDER,
        OBJ_LLM_PROVIDER_AUTH,
        OBJ_LLM_CREDENTIAL_POOL,
        OBJ_LLM_MODEL_PROFILE,
        OBJ_MODEL_ROUTING_POLICY,
        OBJ_LLM_CALL_RECORD,
        OBJ_PROVIDER_HEALTH,
        OBJ_PROVIDER_QUOTA_STATUS,
        OBJ_FACTOR,
        OBJ_LABEL,
        OBJ_MODEL,
        OBJ_FORECAST,
        OBJ_SIGNAL,
        OBJ_STRATEGY_BOOK,
        OBJ_PORTFOLIO_POLICY,
        OBJ_RISK_POLICY,
        OBJ_EXECUTION_POLICY,
        OBJ_EXPERIMENT,
        OBJ_BACKTEST_RUN,
        OBJ_VALIDATION_DOSSIER,
        OBJ_RESEARCH_REPORT,
        OBJ_DESK_HANDOFF,
        OBJ_MARKET_CAPABILITY_MATRIX,
    }
)

# typed input/output contract 强制项（命门 #2）：信号必须绑定 Signal Contract（GOAL §1）。
# forecast（模型输出）同属「输出口径必须 typed」一类，一并要求（GOAL §9：模型输出登记为信号）。
CONTRACT_REQUIRING_TYPES = frozenset({OBJ_SIGNAL, OBJ_FORECAST})

# ─────────────────────────────────────────────────────────────────────────────
# 语义边界（GOAL §1）：每类对象只能进它该进的库/注册表。
#   模型本体 → Model Registry；模型输出 → Signal Contract；因子 → Factor Library；
#   策略 → StrategyBook；组合/风控/执行 → 各自 Policy 库；数学产物 → 数学库。
# ─────────────────────────────────────────────────────────────────────────────
LIB_FACTOR = "factor_library"
LIB_MODEL = "model_registry"
LIB_SIGNAL = "signal_library"
LIB_STRATEGY = "strategy_book_library"
LIB_PORTFOLIO = "portfolio_policy_library"
LIB_RISK = "risk_policy_library"
LIB_EXECUTION = "execution_policy_library"
LIB_MATH = "mathematical_artifact_library"

LIBRARY_OF: dict[str, str] = {
    OBJ_FACTOR: LIB_FACTOR,
    OBJ_MODEL: LIB_MODEL,
    OBJ_SIGNAL: LIB_SIGNAL,
    OBJ_FORECAST: LIB_SIGNAL,  # 模型输出（forecast）经信号契约进信号库，不进因子库
    OBJ_STRATEGY_BOOK: LIB_STRATEGY,
    OBJ_PORTFOLIO_POLICY: LIB_PORTFOLIO,
    OBJ_RISK_POLICY: LIB_RISK,
    OBJ_EXECUTION_POLICY: LIB_EXECUTION,
    OBJ_MATHEMATICAL_ARTIFACT: LIB_MATH,
}


class QROValidationError(ValueError):
    """QRO 信封构造非法（actor 非四类 / 状态轴漂值 / object_type 未知 / 缺 typed contract）。"""


class QROBoundaryError(ValueError):
    """撞语义边界（模型本体塞因子库 / 对象进错库）——返回诚实拒绝文案，绝不静默放行。"""


@dataclass(frozen=True)
class QualifiedResearchObject:
    """QRO 统一信封（GOAL §1「各对象共享。这些必须包含，可以添加新内容」全列 + 状态六轴）。

    frozen（内容寻址身份记录 · 同 spine.py 范式）：状态迁移产生新版本，不原地改。
    身份 `identity` 缺省由 `content_hash({object_type, natural_key})` 派生（单一身份源 ids.py），
    `natural_key` 是被收编资产的既有 id（factor_id@v / signal_id / candidate_id / model key …）——
    **复用不另造**。
    """

    # ── 身份 ──（GOAL §1 identity / version / owner / actor）
    object_type: str
    natural_key: str
    actor: str = ACTOR_USER_MANUAL
    owner: str = "system"
    version: int = 1
    identity: str = ""

    # ── typed input/output contract ──（命门 #2：signal/forecast 必填）
    typed_contract: dict[str, Any] = field(default_factory=dict)

    # ── market / universe / horizon / frequency ──
    market: str = ""
    universe: str = ""
    horizon: str = ""
    frequency: str = ""

    # ── event_time / known_at / effective_at（双时态 · R28）──
    event_time: str = ""
    known_at: str = ""
    effective_at: str = ""

    # ── lineage / implementation hash ──
    lineage: tuple[str, ...] = ()
    implementation_hash: str = ""

    # ── 诚实承载：假设 / 限界 / 失效 / 验证计划 / 证据 / 数学 / 方法学放权 / 责任边界 ──
    assumptions: tuple[str, ...] = ()
    known_limits: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    validation_plan: str = ""
    evidence_refs: tuple[str, ...] = ()
    mathematical_refs: tuple[str, ...] = ()
    methodology_choice_ref: str = ""
    responsibility_boundary: str = ""
    theory_implementation_binding: str = ""  # → spine.TheoryImplementationBinding.binding_id
    consistency_verdict: str = ""

    # ── verdict / permission / approval / allowed_environment ──
    verdict: str = ""  # → verification.VerdictRecord.verdict_id（异模型一致性裁决）
    permission: str = ""  # 默认空 = deny-by-default（无显式授权即不可用）
    approval: str = ""
    allowed_environment: str = ""

    # ── monitor / alert / retire rules ──
    monitor_rules: tuple[str, ...] = ()
    alert_rules: tuple[str, ...] = ()
    retire_rules: tuple[str, ...] = ()

    # ── 资产类型自有生命周期（carried·不重释 · M-AUTHORITY：registry 仍权威）──
    #   factor → registry.LifecycleState(NEW/QUALIFIED/...)；strategy → §3 stage。
    #   与 runtime 轴正交：lifecycle 是资产研究生命周期，runtime 是部署阶梯。
    lifecycle: str = ""

    # ── 状态六轴（分离·不混单绿灯 · GOAL §1）──
    definition: str = DEFINITION_DRAFT
    theory: str = THEORY_NOT_REQUIRED
    consistency: str = CONSISTENCY_NOT_APPLICABLE
    evidence: str = EVIDENCE_UNTESTED
    governance: str = GOVERNANCE_UNREVIEWED
    runtime: str = RUNTIME_OFFLINE

    def __post_init__(self) -> None:
        if self.object_type not in OBJECT_TYPES:
            raise QROValidationError(
                f"object_type 未知：{self.object_type!r} ∉ GOAL §1 QRO 覆盖（共 {len(OBJECT_TYPES)} 类）"
            )
        if self.actor not in ACTOR_CLASSES:
            raise QROValidationError(
                f"actor 非四类动作来源：{self.actor!r} ∉ {sorted(ACTOR_CLASSES)}（GOAL §0）"
            )
        # 状态六轴逐轴校验——任一轴漂出枚举即拒（证明轴是 typed 枚举、非自由单字段）。
        for axis, allowed in _AXIS_ENUMS.items():
            val = getattr(self, axis)
            if val not in allowed:
                raise QROValidationError(
                    f"状态轴 {axis} 非法：{val!r} ∉ {sorted(allowed)}（GOAL §1 状态轴分离）"
                )
        # 命门 #2：signal/forecast 必须带 typed input/output contract。
        if self.object_type in CONTRACT_REQUIRING_TYPES and not self.typed_contract:
            raise QROValidationError(
                f"{self.object_type!r} QRO 缺 typed input/output contract："
                "信号/预测输出必须绑定 Signal Contract（GOAL §1：Signal 未绑定 Signal Contract → 拒）"
            )
        if not self.natural_key:
            raise QROValidationError("natural_key 不可为空——它是身份锚（被收编资产的既有 id）")
        # 身份：复用单一源 content_hash（前缀 qro_，同 spine.py math_/tib_ 范式，非新哈希族）。
        if not self.identity:
            object.__setattr__(
                self,
                "identity",
                "qro_"
                + content_hash({"object_type": self.object_type, "natural_key": self.natural_key}),
            )

    def state_axes(self) -> dict[str, str]:
        """六轴快照（分离展示 —— 调用方看到的是六个独立值，不是一个融合绿灯）。"""

        return {axis: getattr(self, axis) for axis in _AXIS_ENUMS}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AxisClearance:
    """四核心轴的「整体绿」裁定（命门 #3 的产物）。

    `cleared` = 四轴**各自**达强终态的合取（definition=implemented ∧ evidence=sufficient ∧
    governance=approved ∧ runtime∈已部署）。任一轴弱即 `cleared=False` 且该轴进 `blocking_axes`——
    **绝不**让单轴（如 governance 绿）独自点亮整体绿。
    """

    definition_ok: bool
    evidence_ok: bool
    governance_ok: bool
    runtime_ok: bool
    cleared: bool
    blocking_axes: tuple[str, ...]
    note: str


def axis_clearance(qro: QualifiedResearchObject) -> AxisClearance:
    """四核心轴整体绿裁定——四轴合取，任一弱即拒（GOAL §0/§1：不混单绿灯）。

    诚实边界：本门只判**状态轴分离结构**（四轴是否各自达强终态）。它**不**判证据是否真充分、
    理论是否真证明——proof_backed 类强标签的理论一致性裁定归 `spine_gate.evaluate_promotion`，
    本门不重算（避免双源）。`theory`/`consistency` 两轴如实承载在信封上，由该门消费。
    """

    per_axis = {
        "definition": qro.definition == DEFINITION_IMPLEMENTED,
        "evidence": qro.evidence == EVIDENCE_SUFFICIENT,
        "governance": qro.governance == GOVERNANCE_APPROVED,
        "runtime": qro.runtime in _RUNTIME_DEPLOYED,
    }
    # blocking = 任一未达强终态的核心轴；cleared = 无 blocking（≡ 四轴合取）。
    blocking = tuple(axis for axis in CORE_AXES if not per_axis[axis])
    cleared = not blocking
    if cleared:
        note = "四核心轴各自达强终态（definition/evidence/governance/runtime），整体绿。"
    else:
        note = (
            "整体绿被拒：核心轴未达强终态 → "
            + "、".join(
                f"{axis}={getattr(qro, axis)!r}" for axis in blocking
            )
            + "。任一轴弱即不放整体绿（不混单绿灯）。"
        )
    return AxisClearance(
        definition_ok=per_axis["definition"],
        evidence_ok=per_axis["evidence"],
        governance_ok=per_axis["governance"],
        runtime_ok=per_axis["runtime"],
        cleared=cleared,
        blocking_axes=blocking,
        note=note,
    )


def assert_library_membership(object_type: str, target_library: str) -> None:
    """GOAL §1 语义边界：对象只能进它该进的库。进错库即 QROBoundaryError。

    例：`assert_library_membership(OBJ_MODEL, LIB_FACTOR)` → 拒（模型本体进 Model Registry，
    不进 Factor Library · 命门 #4 的对象级形态）。
    """

    if object_type not in OBJECT_TYPES:
        raise QROValidationError(f"object_type 未知：{object_type!r}")
    home = LIBRARY_OF.get(object_type)
    if home is None:
        raise QROBoundaryError(
            f"{object_type!r} 无归属库定义，无法判定库成员资格（须先在 LIBRARY_OF 登记语义归属）"
        )
    if home != target_library:
        raise QROBoundaryError(
            f"语义边界：{object_type!r} 属于 {home!r}，不能进 {target_library!r}（GOAL §1 语义边界）"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 收编适配器（duck-typed·只读·扩展不替换）：把现有资产挂上 QRO 信封，复用其既有 id。
# 刻意用属性读取（duck typing）而非硬 import 资产类——保持地基模块零重依赖
# （factor_factory 包 import 拖 polars/sklearn ~1.6s；models.catalog import 即加载卡片）。
# ─────────────────────────────────────────────────────────────────────────────
def from_factor(
    factor: Any, *, actor: str = ACTOR_USER_MANUAL, owner: str | None = None
) -> QualifiedResearchObject:
    """收编 `factor_factory.registry.Factor`（算术表达式因子）。

    - natural_key = `factor_id@v{version}`（复用既有身份，不另造）。
    - typed_contract = {formula, params}（因子是自含表达式，公式即契约）。
    - lifecycle = factor.lifecycle_state **原样 carried**（M-AUTHORITY：registry 仍是权威，
      QRO 只快照承载，不重释）。
    """

    version = int(getattr(factor, "version", 1))
    return QualifiedResearchObject(
        object_type=OBJ_FACTOR,
        natural_key=f"{factor.factor_id}@v{version}",
        actor=actor,
        owner=owner if owner is not None else str(getattr(factor, "author", "system")),
        version=version,
        typed_contract={
            "formula": str(getattr(factor, "formula", "")),
            "params": dict(getattr(factor, "params", {}) or {}),
        },
        lifecycle=str(getattr(factor, "lifecycle_state", "")),
        definition=DEFINITION_IMPLEMENTED,  # 已注册的表达式因子 = 已实现
    )


def from_signal_contract(
    contract: Any, *, actor: str = ACTOR_AGENT, owner: str | None = None
) -> QualifiedResearchObject:
    """收编 `factor_factory.signal_contract.SignalContract`（ML/DL 输出 → 信号 · R17）。

    - natural_key = `contract.signal_id`（已是 content_hash，**直接复用**单一身份源）。
    - typed_contract 由契约口径填满（source_lib/output_kind/horizon/model_ref/leakage）——
      天然满足命门 #2（Signal 必须有 typed contract）。
    - lineage 回指模型本体 `model_ref`（血统门：信号必回指 Model Registry 里的本体）。
    """

    leakage = getattr(contract, "leakage", None)
    leakage_d = (
        leakage.to_dict()
        if hasattr(leakage, "to_dict")
        else (dict(leakage) if isinstance(leakage, Mapping) else {})
    )
    return QualifiedResearchObject(
        object_type=OBJ_SIGNAL,
        natural_key=str(contract.signal_id),
        actor=actor,
        owner=owner if owner is not None else str(getattr(contract, "author", "system")),
        typed_contract={
            "source_lib": str(getattr(contract, "source_lib", "")),
            "output_kind": str(getattr(contract, "output_kind", "")),
            "horizon": int(getattr(contract, "horizon", 0)),
            "model_ref": str(getattr(contract, "model_ref", "")),
            "leakage": leakage_d,
        },
        horizon=str(getattr(contract, "horizon", "")),
        lineage=(f"model_ref:{getattr(contract, 'model_ref', '')}",),
        definition=DEFINITION_IMPLEMENTED,
    )


def from_model_card(
    card: Any, *, actor: str = ACTOR_USER_MANUAL, owner: str | None = None
) -> QualifiedResearchObject:
    """收编 `models.catalog.ModelCard`（模型本体进 Model Registry · 语义边界）。"""

    return QualifiedResearchObject(
        object_type=OBJ_MODEL,
        natural_key=str(getattr(card, "key")),
        actor=actor,
        owner=owner if owner is not None else "system",
        typed_contract={
            "family": str(getattr(card, "family", "")),
            "tasks": list(getattr(card, "tasks", []) or []),
        },
    )


def from_strategy_candidate(
    candidate: Mapping[str, Any], *, actor: str = ACTOR_AGENT, owner: str | None = None
) -> QualifiedResearchObject:
    """收编 `strategy.candidate_pool` 候选记录（策略 → StrategyBook）。

    候选池钉死 destination=paper_desk（D-PERM 不跳级）→ runtime 轴映射为 paper（绝不 live）。
    """

    natural_key = str(candidate["candidate_id"])
    stops_at = str(candidate.get("stops_at") or candidate.get("destination") or "")
    runtime = RUNTIME_PAPER if stops_at == "paper_desk" else RUNTIME_OFFLINE
    return QualifiedResearchObject(
        object_type=OBJ_STRATEGY_BOOK,
        natural_key=natural_key,
        actor=actor,
        owner=owner if owner is not None else str(candidate.get("created_by", "system")),
        typed_contract={
            "run_id": str(candidate.get("run_id", "")),
            "factor_set": candidate.get("factor_set"),
            "model_id": candidate.get("model_id"),
        },
        lineage=(f"run_id:{candidate.get('run_id', '')}",),
        lifecycle=str(candidate.get("status", "")),
        runtime=runtime,
    )


def _theory_axis_from_proof_status(proof_status: str) -> str:
    """spine.MathematicalArtifact.proof_status → QRO theory 轴的**粗投影**（快照·非裁定）。

    诚实：这只是信封承载用的粗映射；理论强标签的真裁定归 spine_gate，不在此判。
    unproven→required（待证）、proof_sketch→drafted（草拟）、proof_backed→accepted（已证）。
    """

    return {
        "proof_backed": THEORY_ACCEPTED,
        "proof_sketch": THEORY_DRAFTED,
        "unproven": THEORY_REQUIRED,
    }.get(proof_status, THEORY_REQUIRED)


def from_mathematical_artifact(
    artifact: Any, *, actor: str = ACTOR_AGENT, owner: str | None = None
) -> QualifiedResearchObject:
    """收编 `lineage.spine.MathematicalArtifact`（数学产物进数学库 · GOAL §6）。

    natural_key = artifact.artifact_id（已 content_hash · 复用）；theory 轴由 proof_status 粗投影；
    mathematical_refs 自指。理论一致性强标签裁定仍归 spine_gate（本信封不重算）。
    """

    return QualifiedResearchObject(
        object_type=OBJ_MATHEMATICAL_ARTIFACT,
        natural_key=str(artifact.artifact_id),
        actor=actor,
        owner=owner if owner is not None else "system",
        theory=_theory_axis_from_proof_status(str(getattr(artifact, "proof_status", "unproven"))),
        mathematical_refs=(str(artifact.artifact_id),),
        assumptions=tuple(getattr(artifact, "assumptions", ()) or ()),
        failure_modes=tuple(getattr(artifact, "failure_conditions", ()) or ()),
    )


def admit_factor_qro(
    *,
    kind: str,
    ref: str,
    factor_id: str,
    formula: str = "",
    actor: str = ACTOR_USER_MANUAL,
    owner: str = "system",
    version: int = 1,
) -> QualifiedResearchObject:
    """新产物进**因子库**前的语义边界门（命门 #4 · GOAL §1 + R17）。

    复用 `signal_contract.admit_artifact_to_factor_lib`（**单一源**范畴门，绝不另造）：
    - kind="model_body" 或 ref 像模型本体文件（.pt/.pkl…）→ QROBoundaryError（模型本体进
      Model Registry，不进 Factor Library）。
    - kind ∈ {expression, signal_contract} 且非本体文件 → 准入，挂 factor QRO 信封。

    懒导入 `admit_artifact_to_factor_lib`：避免地基模块 import 即拖 factor_factory 重依赖；
    成本只在真调用准入时付。
    """

    from ..factor_factory.signal_contract import admit_artifact_to_factor_lib

    admitted, reason = admit_artifact_to_factor_lib(kind, ref)
    if not admitted:
        raise QROBoundaryError(reason)
    return QualifiedResearchObject(
        object_type=OBJ_FACTOR,
        natural_key=f"{factor_id}@v{int(version)}",
        actor=actor,
        owner=owner,
        version=int(version),
        typed_contract={"formula": formula or ref, "kind": kind, "ref": ref},
        definition=DEFINITION_IMPLEMENTED,
    )


# ─────────────────────────────────────────────────────────────────────────────
# A-QRO-2 · 语义边界完整切分（GOAL §1 行154-157 + §9）——在 A-QRO-1 信封 / 状态六轴 /
# 结构门之上**扩**三道库归属断言（扩展不替换 · 绝不改 A-QRO-1 核心结构）：
#   ① 模型本体进 Model Registry、不进 Factor Library —— 既有 admit_factor_qro（正门）
#      + 本卡 admit_model_qro（对称**反门**：因子/expression 误放 Model Registry → 拒）。
#   ② 模型输出进 Signal Contract —— assert_signal_contract_bound（Forecast 未绑契约 → 拒）。
#   守门器解耦（generator/gatekeeper）—— assert_generator_fitness_clean（守门指标进生成 fitness → 拒）。
# 三道都**复用单一源**（RULES §1）：looks_like_model_body（什么是本体）/ mining.is_gate_metric_key
# （什么是守门指标，GATE_METRIC_KEYWORDS 单一黑名单、与前端镜像）——QRO 层绝不另造第二判定。
# 重依赖（factor_factory 包 import 即拖 polars/sklearn ~1.6s）一律**懒导入**，成本只在真调用时付
# （与 admit_factor_qro 同范式）。
# ─────────────────────────────────────────────────────────────────────────────
def assert_signal_contract_bound(qro: QualifiedResearchObject) -> None:
    """命门 ②：模型输出（Forecast/Signal）进信号层必须**绑定 Signal Contract**（GOAL §1/§9）。

    未绑定（裸预测序列 / 孤儿信号）→ QROBoundaryError（GOAL §9「Signal 未绑定 Signal Contract → 拒」）。
    作用面只在 signal/forecast（CONTRACT_REQUIRING_TYPES）；其余对象 no-op（不误伤）。

    绑定证据（任一成立即算已绑——诚实承载、不重算契约本身）：
      a) typed_contract.model_ref 回指**真实模型本体文件**——与 signal_contract 血统门**同一单一源**
         looks_like_model_body（单模型输出走此路）；
      b) typed_contract 显式携带信号契约 id（signal_id / signal_contract_ref / contract_ref）——
         集成 / stacking 信号绑契约 id 而非裸本体，亦算已绑（GOAL §9：组合/集成位于信号层）；
      c) lineage 携 model_ref: / signal: / contract: 回指。

    诚实边界：本门只验**绑定存在性**（QRO 层进信号库的关口），不证明无泄露——泄露声明门 /
    血统门在 factor_factory.signal_contract.SignalContractRegistry **单一源**已管，QRO 层不重算
    （避免双源漂移）。
    """

    if qro.object_type not in CONTRACT_REQUIRING_TYPES:
        return
    from ..factor_factory.signal_contract import looks_like_model_body

    tc = qro.typed_contract or {}
    model_ref = str(tc.get("model_ref", "")).strip()
    if model_ref and looks_like_model_body(model_ref):
        return  # a) 回指真实本体（与 signal_contract 血统门同口径）
    for key in ("signal_id", "signal_contract_ref", "contract_ref"):
        if str(tc.get(key, "")).strip():
            return  # b) 显式信号契约 id（集成 / stacking）
    for ref in qro.lineage:
        r = str(ref)
        if r.startswith(("model_ref:", "signal:", "contract:")) and r.split(":", 1)[1].strip():
            return  # c) lineage 回指
    raise QROBoundaryError(
        f"{qro.object_type!r} 未绑定 Signal Contract → 拒（GOAL §1/§9）："
        "模型输出进信号层须经信号契约登记、回指 Model Registry 本体（model_ref 指向 .pt/.pkl…）"
        "或显式契约 id；裸预测序列（孤儿信号）不得直接入信号层"
    )


def admit_model_qro(
    *,
    model_key: str,
    family: str = "ml",
    body_ref: str = "",
    actor: str = ACTOR_USER_MANUAL,
    owner: str = "system",
) -> QualifiedResearchObject:
    """命门 ①（反门）：新产物进 **Model Registry** 前的语义边界门（GOAL §1：ML/DL 本体进 Model Registry）。

    与 admit_factor_qro 对称——拒「因子（算术 / expression）误放进 Model Registry」：
      - family ∉ {ml, dl} → 拒（Model Registry 只收 ML/DL 本体；策略归 StrategyBook、
        组合 / 风控 / 执行各归 Policy 库、因子归 Factor Library）。
      - body_ref 给定但**不是模型本体文件**（.pt/.pkl…）→ 拒：非本体 ref（如 `close/open-1`）
        是算术因子、归 Factor Library，不是模型本体。判「是否本体」**复用单一源**
        looks_like_model_body（与 admit_artifact_to_factor_lib 同一份后缀真相、前端镜像同口径），
        绝不在 QRO 层另造本体判定。

    登记目录模型（runnable 卡片、尚无 body 文件）→ 传 model_key、body_ref 留空即可
    （from_model_card 收编路径亦走 model key、不带 body 文件）。
    """

    fam = str(family).strip().lower()
    if fam not in ("ml", "dl"):
        raise QROBoundaryError(
            f"Model Registry 只收 ML/DL 模型本体（GOAL §1/§9）；family={family!r} ∉ {{ml, dl}}——"
            "算术 / expression 归 Factor Library、策略归 StrategyBook、组合 / 风控 / 执行归各 Policy 库"
        )
    if body_ref:
        from ..factor_factory.signal_contract import looks_like_model_body

        if not looks_like_model_body(body_ref):
            raise QROBoundaryError(
                f"body_ref={body_ref!r} 不是 ML/DL 模型本体文件（.pt/.pkl/.onnx…）——非本体 ref 是"
                "算术因子、归 Factor Library（GOAL §1：因子在 Factor Library / 模型本体进 Model "
                "Registry）；Model Registry 只收本体，登记目录模型请用 model_key、body_ref 留空"
            )
    return QualifiedResearchObject(
        object_type=OBJ_MODEL,
        natural_key=str(model_key),
        actor=actor,
        owner=owner,
        typed_contract={"family": fam, "body_ref": body_ref},
    )


def assert_generator_fitness_clean(fitness_keys: Iterable[str]) -> None:
    """命门（守门器解耦）：守门指标**绝不可**进因子生成器 fitness / 排序维度（GOAL §9）。

    任一 fitness 键命中守门指标（IC / IR / DSR / Sharpe / PBO / CSCV / t / return…）→
    QROBoundaryError（GOAL §9「守门指标进入生成 fitness → 拒」）。这是「先看结果再生成」选择偏误 /
    验证集泄露的硬门：生成器只看结构维度（复杂度 / 算子覆盖 / 族多样性 / 新颖度），守门指标在
    **独立后置**守门环节裁决。

    单一源（RULES §1）：判定**复用** factor_factory.mining.is_gate_metric_key（GATE_METRIC_KEYWORDS
    单一黑名单、与前端镜像、与 mining 层 assert_generator_sort_key_clean 同一份真相）——QRO 层
    绝不另造守门指标黑名单。错误用 QROBoundaryError（QRO 层统一边界异常，调用方统一捕获），
    而非 mining.MiningGateLeakError（避免下层异常类型外泄到 QRO 调用方）。
    """

    from ..factor_factory.mining import is_gate_metric_key

    # 防呆：单个 str 当一个键（否则 Iterable[str] 会逐字符迭代，"ic" 漏判）。
    keys = [fitness_keys] if isinstance(fitness_keys, str) else list(fitness_keys)
    dirty = [k for k in keys if is_gate_metric_key(str(k))]
    if dirty:
        raise QROBoundaryError(
            f"generator/gatekeeper 解耦（GOAL §9）：守门指标 {dirty} 不可进因子生成器 fitness / 排序——"
            "生成器只看结构维度，守门指标在独立后置守门环节裁决（否则验证集泄露：先看结果再生成）"
        )


__all__ = [
    # actor
    "ACTOR_USER_MANUAL",
    "ACTOR_AGENT",
    "ACTOR_USER_CONFIRMED_AGENT",
    "ACTOR_SCHEDULED_AGENT",
    "ACTOR_CLASSES",
    # 状态六轴枚举
    "DEFINITION_STATES",
    "THEORY_STATES",
    "CONSISTENCY_STATES",
    "EVIDENCE_STATES",
    "GOVERNANCE_STATES",
    "RUNTIME_STATES",
    "DEFINITION_DRAFT",
    "DEFINITION_SPECIFIED",
    "DEFINITION_IMPLEMENTED",
    "EVIDENCE_UNTESTED",
    "EVIDENCE_SUFFICIENT",
    "EVIDENCE_INSUFFICIENT",
    "GOVERNANCE_UNREVIEWED",
    "GOVERNANCE_APPROVED",
    "GOVERNANCE_REJECTED",
    "GOVERNANCE_REVOKED",
    "RUNTIME_OFFLINE",
    "RUNTIME_PAPER",
    "RUNTIME_TESTNET",
    "RUNTIME_LIVE",
    "RUNTIME_SUSPENDED",
    "RUNTIME_RETIRED",
    "THEORY_NOT_REQUIRED",
    "THEORY_ACCEPTED",
    "CONSISTENCY_NOT_APPLICABLE",
    "CORE_AXES",
    # object types + 语义边界
    "OBJECT_TYPES",
    "CONTRACT_REQUIRING_TYPES",
    "OBJ_FACTOR",
    "OBJ_LABEL",
    "OBJ_MODEL",
    "OBJ_FORECAST",
    "OBJ_SIGNAL",
    "OBJ_STRATEGY_BOOK",
    "OBJ_PORTFOLIO_POLICY",
    "OBJ_RISK_POLICY",
    "OBJ_EXECUTION_POLICY",
    "OBJ_MATHEMATICAL_ARTIFACT",
    "LIBRARY_OF",
    "LIB_FACTOR",
    "LIB_MODEL",
    "LIB_SIGNAL",
    "LIB_STRATEGY",
    "LIB_MATH",
    # 信封 + 门 + 异常
    "QualifiedResearchObject",
    "AxisClearance",
    "axis_clearance",
    "assert_library_membership",
    "QROValidationError",
    "QROBoundaryError",
    # 收编适配器
    "from_factor",
    "from_signal_contract",
    "from_model_card",
    "from_strategy_candidate",
    "from_mathematical_artifact",
    "admit_factor_qro",
    # A-QRO-2 · 语义边界完整切分门（扩展不替换 · 复用单一源）
    "assert_signal_contract_bound",
    "admit_model_qro",
    "assert_generator_fitness_clean",
]
