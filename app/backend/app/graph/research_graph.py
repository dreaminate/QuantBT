"""Research Graph IR（GOAL §1 统一对象链 · §2 多台工作系统）——QRO 与 Compiler 之间的 typed 图。

GOAL §1 链：`Quant Intent → Typed Canvas/Command → QRO → Research Graph → Governed Compiler → …`。
A-QRO-1（`qro/envelope.py`）已出**统一信封**（身份 + 状态六轴 + 治理）。本模块建链里
**QRO → Compiler 之间的 IR**：一张 typed 图，持有 QRO 节点 + 边（lineage/dependency/DeskHandoff），
对外只通过 **canonical command 单一写路径** 改图，并按 §2「每台 Canvas = 同一 Research Graph 的
typed projection」做各台投影。**不建 Governed Compiler（A-COMPILER 另卡）、不建 CanonicalCommand
全栈翻译（A-CMD 另卡）**——本模块只定 IR 图结构 + projection + 单一真相源门 + canonical command 落点。

为什么图是「持有信封 + 单写路径」而非「另存一套状态」（RULES §1 单一源 + §4 扩展不替换）：
- 节点**就是** QRO（`qro/envelope.QualifiedResearchObject`·frozen·内容寻址）——图只**收编只读**它，
  绝不重写资产、绝不另造第二套身份。`node_id == qro.identity`（已是 `qro_`+content_hash），
  边/命令/交接 id 同走 `lineage.ids.content_hash`（前缀 `edge_`/`cmd_`/`handoff_`，同 spine.py
  `math_`/`tib_`/`cc_` 范式）——**绝不**新造哈希族。
- 真相状态（六轴）只存在图里**唯一**一份（节点内的 QRO）。各台是**派生只读投影**，不持独立可写副本
  ——这是 §2「任一台维护独立真相状态 → 拒」的结构性保证；`assert_single_source*` 是其可证伪探针。
- 图的**唯一公共写口** = `apply(command)`。没有第二条裸写路径——这是 §2「user 手动改动未落
  canonical command → 拒」的结构性落点；`assert_commanded` 是其可证伪探针。

七个命门（可证伪验收 · 种坏门必抓 · RULES §2 · GOAL §1/§2）：
1. 单一真相源：任一台维护独立真相状态（与图节点矛盾）→ `SingleSourceViolation`（§2）。
2. typed contract：signal/forecast 节点无 typed input/output contract 进图 → `NodeAdmissionError`（§1）。
   非 QRO 对象（裸 dict / duck 对象）进图 → 拒（图只收编真信封）。
3. canonical command 落点：改动未经 `apply(command)` 落图（节点/边/交接缺 command_ref）→
   `CanonicalCommandViolation`（§2）。
4. DeskHandoff 完成（resolved）缺 produced_ref → `HandoffIncompleteError`（§2）。
5. 写权限按台隔离：非 home 台写某对象（如策略台写 Factor）→ `WriteAuthorityViolation`（§2）。
6. 机构级投影：声称机构级方法的投影缺 math/consistency 轴 → `ProjectionError`（§2）。
7. 正路径不误伤：home 台写本台对象、跨台引用（dependency 边）、交接带 produced_ref 解决 —— 全放行。

诚实边界（本模块**不**做什么）：
- 它**不**判 evidence 是否真充分 / 理论是否真证明 / 一致性是否真成立——那是 verification、
  `spine_gate.evaluate_promotion`、Governed Compiler（A-COMPILER）的活。本 IR 只承载信封状态、
  保证「单一真相源 + 单写路径 + typed projection」结构，绝不把任一轴渲染成整体可信。
- 它**不**做 canonical command 的语义翻译 / 解析 / 全栈校验（A-CMD）——只定**落点**：改图必经命令、
  命令带四类 actor + 目标台 + 内容寻址 id，图据此 stamp `command_ref` 并 append 命令日志。
- 写权限是**对象定义级**（哪个台能创建/编辑某类对象本体）。**轴级**权限（执行台推 runtime、回测台
  动 evidence、审批台动 governance）是下游台 / 治理门的活，不在本卡（诚实残余）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Mapping

from ..lineage.ids import content_hash
from ..qro.envelope import (
    ACTOR_CLASSES,
    CONSISTENCY_STATES,
    CONTRACT_REQUIRING_TYPES,
    THEORY_STATES,
    OBJ_BACKTEST_RUN,
    OBJ_CONSISTENCY_CHECK,
    OBJ_DATA_SOURCE_ASSET,
    OBJ_DATASET,
    OBJ_DATASET_VERSION,
    OBJ_DESK_HANDOFF,
    OBJ_DOCUMENT_ARTIFACT,
    OBJ_EXECUTION_POLICY,
    OBJ_EXPERIMENT,
    OBJ_FACTOR,
    OBJ_FORECAST,
    OBJ_FRESHNESS_STATUS,
    OBJ_INGESTION_SKILL,
    OBJ_INTEGRATION_CONFIG,
    OBJ_LABEL,
    OBJ_LLM_CALL_RECORD,
    OBJ_LLM_CREDENTIAL_POOL,
    OBJ_LLM_MODEL_PROFILE,
    OBJ_LLM_PROVIDER,
    OBJ_LLM_PROVIDER_AUTH,
    OBJ_MARKET_CAPABILITY_MATRIX,
    OBJ_MATHEMATICAL_ARTIFACT,
    OBJ_MATHEMATICAL_REQUIREMENT,
    OBJ_METHODOLOGY_CHOICE_RECORD,
    OBJ_MODEL,
    OBJ_MODEL_ROUTING_POLICY,
    OBJ_OBSERVABLE,
    OBJ_PORTFOLIO_POLICY,
    OBJ_PROVIDER_HEALTH,
    OBJ_PROVIDER_QUOTA_STATUS,
    OBJ_RESEARCH_REPORT,
    OBJ_RESPONSIBILITY_DISCLOSURE_RECORD,
    OBJ_RISK_POLICY,
    OBJ_SCHEMA_DRIFT_EVENT,
    OBJ_SECRET_REF,
    OBJ_SIGNAL,
    OBJ_STRATEGY_BOOK,
    OBJ_THEORY_IMPLEMENTATION_BINDING,
    OBJ_THEORY_SPEC,
    OBJ_TOKEN_REF,
    OBJ_VALIDATION_DOSSIER,
    OBJECT_TYPES,
    QualifiedResearchObject,
)

# ─────────────────────────────────────────────────────────────────────────────
# 台（GOAL §2 各台职责）——写权限按台隔离的命名空间。
# ─────────────────────────────────────────────────────────────────────────────
DESK_DATA = "data_desk"  # 数据台：数据源/Integration/PIT/DatasetVersion/IngestionSkill/freshness/drift
DESK_FACTOR = "factor_desk"  # 因子台：创建/编辑/验证/分类/退役因子
DESK_MODEL = "model_desk"  # 模型台：训练/验证/登记/模型卡/护照/晋级
DESK_SIGNAL = "signal_desk"  # 信号台：Signal Contract，把 factor/model output 转信号
DESK_STRATEGY = "strategy_desk"  # 策略台：StrategyBook/组合意图/约束/成本/回测计划（引用 factor/signal/model id）
DESK_BACKTEST = "backtest_desk"  # 回测/验证台：实验/PBO/DSR/CPCV/bootstrap/归因/反证/verdict
DESK_EXECUTION = "execution_desk"  # 执行/风控台：paper/testnet/live ladder/risk gate/kill switch/退役
DESK_RESEARCH = "research_desk"  # 研究台：论文/研报/网页/代码/数学定义/证据抽取/RDP
DESK_SETTINGS = "settings_desk"  # 设置台：Integrations/Data Sources/LLM Providers/Secrets/Credential Pools/Routing

DESKS: frozenset[str] = frozenset(
    {
        DESK_DATA,
        DESK_FACTOR,
        DESK_MODEL,
        DESK_SIGNAL,
        DESK_STRATEGY,
        DESK_BACKTEST,
        DESK_EXECUTION,
        DESK_RESEARCH,
        DESK_SETTINGS,
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# home 台映射（对象类型 → 唯一写权限台 · GOAL §2「写权限按台隔离」单一源）。
# 命门 #5（策略台直接写 Factor → 拒）= 写某对象时 target_desk 必须 == HOME_DESK_OF[object_type]。
# 这是「可编辑资产类型」投影的单一源（projection 的 editable 由它派生，不另立一套）。
#
# 诚实点名（语义微岔·见 done 卡·非阻塞）：integration_config / data_source_asset 在 GOAL §2 由
# 数据台与设置台共同触及（两台都列 Integrations/Data Sources）。本表按**主责**切分：连接/凭据/
# Provider 配置层归设置台、数据语义/质量/版本层归数据台。可逆（仅一条 dict 项）、下游只读不破坏。
# ─────────────────────────────────────────────────────────────────────────────
HOME_DESK_OF: dict[str, str] = {
    # 数据层（数据语义 / 质量 / 版本 / 摄入）→ 数据台
    OBJ_DATASET: DESK_DATA,
    OBJ_OBSERVABLE: DESK_DATA,
    OBJ_DATA_SOURCE_ASSET: DESK_DATA,
    OBJ_INGESTION_SKILL: DESK_DATA,
    OBJ_DATASET_VERSION: DESK_DATA,
    OBJ_FRESHNESS_STATUS: DESK_DATA,
    OBJ_SCHEMA_DRIFT_EVENT: DESK_DATA,
    OBJ_MARKET_CAPABILITY_MATRIX: DESK_DATA,
    # 连接 / 凭据 / Provider 配置层 → 设置台
    OBJ_INTEGRATION_CONFIG: DESK_SETTINGS,
    OBJ_SECRET_REF: DESK_SETTINGS,
    OBJ_TOKEN_REF: DESK_SETTINGS,
    OBJ_LLM_PROVIDER: DESK_SETTINGS,
    OBJ_LLM_PROVIDER_AUTH: DESK_SETTINGS,
    OBJ_LLM_CREDENTIAL_POOL: DESK_SETTINGS,
    OBJ_LLM_MODEL_PROFILE: DESK_SETTINGS,
    OBJ_MODEL_ROUTING_POLICY: DESK_SETTINGS,
    OBJ_LLM_CALL_RECORD: DESK_SETTINGS,
    OBJ_PROVIDER_HEALTH: DESK_SETTINGS,
    OBJ_PROVIDER_QUOTA_STATUS: DESK_SETTINGS,
    # 理论 / 数学 / 方法学 / 文档 / 研报 / 跨台交接 → 研究台
    OBJ_THEORY_SPEC: DESK_RESEARCH,
    OBJ_MATHEMATICAL_REQUIREMENT: DESK_RESEARCH,
    OBJ_THEORY_IMPLEMENTATION_BINDING: DESK_RESEARCH,
    OBJ_CONSISTENCY_CHECK: DESK_RESEARCH,
    OBJ_METHODOLOGY_CHOICE_RECORD: DESK_RESEARCH,
    OBJ_RESPONSIBILITY_DISCLOSURE_RECORD: DESK_RESEARCH,
    OBJ_MATHEMATICAL_ARTIFACT: DESK_RESEARCH,
    OBJ_DOCUMENT_ARTIFACT: DESK_RESEARCH,
    OBJ_RESEARCH_REPORT: DESK_RESEARCH,
    OBJ_DESK_HANDOFF: DESK_RESEARCH,
    # 研究资产层 → 各专台
    OBJ_FACTOR: DESK_FACTOR,
    OBJ_LABEL: DESK_FACTOR,
    OBJ_MODEL: DESK_MODEL,
    OBJ_SIGNAL: DESK_SIGNAL,
    OBJ_FORECAST: DESK_SIGNAL,
    OBJ_STRATEGY_BOOK: DESK_STRATEGY,
    OBJ_PORTFOLIO_POLICY: DESK_STRATEGY,
    OBJ_RISK_POLICY: DESK_EXECUTION,
    OBJ_EXECUTION_POLICY: DESK_EXECUTION,
    OBJ_EXPERIMENT: DESK_BACKTEST,
    OBJ_BACKTEST_RUN: DESK_BACKTEST,
    OBJ_VALIDATION_DOSSIER: DESK_BACKTEST,
}

# import 期自检（fail-fast·非 assert·-O 不剥）：HOME_DESK_OF 必须恰好覆盖 GOAL §1 QRO 全类型。
# 上游新增对象类型却漏在此登记 home 台 → 写权限/投影留盲区（某类型谁都不能写 / editable 永假）。
# 在此硬拦，逼新类型显式登记台归属（写权限单一源·防漂）。
_unmapped_types = set(OBJECT_TYPES) - set(HOME_DESK_OF)
if _unmapped_types:
    raise RuntimeError(
        f"HOME_DESK_OF 漏映射 QRO 对象类型 {sorted(_unmapped_types)}——"
        "新增 QRO 对象类型须在此登记 home 台（GOAL §2 写权限按台隔离·单一源·防投影盲区）"
    )


def home_desk_of(object_type: str) -> str:
    """对象类型 → 唯一 home（写权限）台。未映射即拒（deny-by-default·防漂未登记类型）。"""

    desk = HOME_DESK_OF.get(object_type)
    if desk is None:
        raise WriteAuthorityViolation(
            f"object_type {object_type!r} 无 home 台登记（HOME_DESK_OF 未覆盖）——"
            "无法判定写权限归属（GOAL §2 写权限按台隔离）"
        )
    return desk


# ─────────────────────────────────────────────────────────────────────────────
# 边类型（GOAL §2「lineage / dependency / DeskHandoff」）。
# ─────────────────────────────────────────────────────────────────────────────
EDGE_LINEAGE = "lineage"  # src 由 dst 派生 / 产出（数据血统）
EDGE_DEPENDENCY = "dependency"  # src 依赖 dst（如 strategy 依赖 factor/signal/model·引用非写）
EDGE_DESK_HANDOFF = "desk_handoff"  # 跨台交接连接（伴随 DeskHandoff 记录）
EDGE_TYPES: frozenset[str] = frozenset({EDGE_LINEAGE, EDGE_DEPENDENCY, EDGE_DESK_HANDOFF})

# ─────────────────────────────────────────────────────────────────────────────
# DeskHandoff 状态（GOAL §2）——resolved = 已产出（命门 #4：必须带 produced_ref）。
# ─────────────────────────────────────────────────────────────────────────────
HANDOFF_OPEN = "open"
HANDOFF_IN_PROGRESS = "in_progress"
HANDOFF_RESOLVED = "resolved"  # 完成态：必须带 produced_ref
HANDOFF_REJECTED = "rejected"  # 拒绝态：无需 produced_ref
HANDOFF_STATES: frozenset[str] = frozenset(
    {HANDOFF_OPEN, HANDOFF_IN_PROGRESS, HANDOFF_RESOLVED, HANDOFF_REJECTED}
)

# ─────────────────────────────────────────────────────────────────────────────
# Canonical command 类型（GOAL §2 落点·非 A-CMD 全栈）——改图的唯一动作词汇。
# ─────────────────────────────────────────────────────────────────────────────
CMD_CREATE_NODE = "create_node"  # 收编一个 QRO 进图（首次）
CMD_UPDATE_NODE = "update_node"  # 状态迁移：同身份换 QRO（六轴变·新值）
CMD_ADD_EDGE = "add_edge"  # 加 lineage/dependency 边
CMD_OPEN_HANDOFF = "open_handoff"  # 开一条跨台交接
CMD_RESOLVE_HANDOFF = "resolve_handoff"  # 解决交接（必带 produced_ref）
COMMAND_TYPES: frozenset[str] = frozenset(
    {CMD_CREATE_NODE, CMD_UPDATE_NODE, CMD_ADD_EDGE, CMD_OPEN_HANDOFF, CMD_RESOLVE_HANDOFF}
)


# ─────────────────────────────────────────────────────────────────────────────
# 异常族（每门一类·诚实拒绝文案·绝不静默放行）。
# ─────────────────────────────────────────────────────────────────────────────
class ResearchGraphError(Exception):
    """Research Graph IR 不变量被违反的基类。"""


class SingleSourceViolation(ResearchGraphError):
    """命门 #1：某台维护的真相状态与图节点（唯一真相源）矛盾（GOAL §2）。"""


class NodeAdmissionError(ResearchGraphError):
    """命门 #2：节点进图非法（非 QRO 对象 / signal·forecast 缺 typed contract · GOAL §1）。"""


class CanonicalCommandViolation(ResearchGraphError):
    """命门 #3：改动未经 canonical command 落图（缺 command_ref / 命令非法 · GOAL §2）。"""


class HandoffIncompleteError(ResearchGraphError):
    """命门 #4：DeskHandoff 完成（resolved）却缺 produced_ref（GOAL §2）。"""


class WriteAuthorityViolation(ResearchGraphError):
    """命门 #5：非 home 台写某对象（如策略台写 Factor · GOAL §2 写权限按台隔离）。"""


class ProjectionError(ResearchGraphError):
    """命门 #6：声称机构级方法的投影缺 math/consistency 轴（GOAL §2）。"""


class GraphIntegrityError(ResearchGraphError):
    """引用完整性：边/交接指向不存在的节点 / 交接（无悬空·GOAL §8 DAG 精神）。"""


def _graph_id(prefix: str, payload: Mapping[str, Any]) -> str:
    """内容寻址 id = 前缀 + content_hash(payload)（复用单一身份源 ids.content_hash·同 spine._frozen_id）。"""

    return f"{prefix}_{content_hash(dict(payload))}"


# ─────────────────────────────────────────────────────────────────────────────
# DeskHandoff（GOAL §2 字段 verbatim「这些必须包含，可以添加新内容」）。
# frozen：解决一条交接 = 产生新版本实例（不原地改·同 QRO/spine 范式）。
# 命门 #4 在 __post_init__ 兑现：resolved 缺 produced_ref 直接拒（构造期即拦·无法绕）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DeskHandoff:
    """跨台交接（GOAL §2）——连接「需求台」与「产出台」，承载 blocking 依赖与产出引用。"""

    from_desk: str
    to_desk: str
    requested_asset: str
    reason: str = ""
    blocking_dependency: str = ""
    status: str = HANDOFF_OPEN
    produced_ref: str = ""
    evidence_refs: tuple[str, ...] = ()
    created_by: str = ""  # 四类 actor（GOAL §0·复用 ACTOR_CLASSES）
    resolved_by: str = ""
    handoff_id: str = ""

    def __post_init__(self) -> None:
        if self.from_desk not in DESKS:
            raise ResearchGraphError(f"from_desk 非法台：{self.from_desk!r} ∉ {sorted(DESKS)}")
        if self.to_desk not in DESKS:
            raise ResearchGraphError(f"to_desk 非法台：{self.to_desk!r} ∉ {sorted(DESKS)}")
        if self.status not in HANDOFF_STATES:
            raise ResearchGraphError(
                f"DeskHandoff.status 非法：{self.status!r} ∉ {sorted(HANDOFF_STATES)}"
            )
        if self.created_by and self.created_by not in ACTOR_CLASSES:
            raise ResearchGraphError(
                f"DeskHandoff.created_by 非四类 actor：{self.created_by!r}（GOAL §0）"
            )
        if self.resolved_by and self.resolved_by not in ACTOR_CLASSES:
            raise ResearchGraphError(
                f"DeskHandoff.resolved_by 非四类 actor：{self.resolved_by!r}（GOAL §0）"
            )
        # 命门 #4：完成态必须带 produced_ref（GOAL §2「DeskHandoff 完成后缺 produced_ref → 拒」）。
        if self.status == HANDOFF_RESOLVED and not self.produced_ref:
            raise HandoffIncompleteError(
                "DeskHandoff 完成（resolved）缺 produced_ref："
                "已完成的交接必须指向真实产出（GOAL §2 DeskHandoff 完成后缺 produced_ref → 拒）"
            )
        if not self.handoff_id:
            object.__setattr__(
                self,
                "handoff_id",
                _graph_id(
                    "handoff",
                    {
                        "from_desk": self.from_desk,
                        "to_desk": self.to_desk,
                        "requested_asset": self.requested_asset,
                        "created_by": self.created_by,
                    },
                ),
            )


# ─────────────────────────────────────────────────────────────────────────────
# 图元素：GraphNode 持有 QRO（唯一真相）+ command_ref（单写路径凭证）；GraphEdge 同。
# command_ref 是命门 #3 的命门：每个图元素都必须由一条 canonical command 落入并 stamp 之。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GraphNode:
    """图节点 = 一个 QRO（唯一真相状态·frozen 内容寻址）+ 落图命令引用。

    `node_id == qro.identity`（单一身份源·不另造）；`home_desk` 由 object_type 派生（不存独立副本）；
    `command_ref` = 把本节点落/改图的 canonical command id（命门 #3）。
    """

    qro: QualifiedResearchObject
    command_ref: str
    node_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.qro, QualifiedResearchObject):
            raise NodeAdmissionError(
                "GraphNode.qro 必须是 QualifiedResearchObject（图只收编真信封·"
                "非裸 dict / duck 对象——绕过 QRO = 绕过单一真相源·GOAL §1/§2）"
            )
        if not self.command_ref:
            raise CanonicalCommandViolation(
                "GraphNode 缺 command_ref：改动必经 canonical command 落图"
                "（GOAL §2 user 手动改动未落 canonical command → 拒）"
            )
        if not self.node_id:
            object.__setattr__(self, "node_id", self.qro.identity)

    @property
    def home_desk(self) -> str:
        """写权限归属台（由 object_type 派生·单一源 HOME_DESK_OF·不存独立副本防漂）。"""

        return home_desk_of(self.qro.object_type)


@dataclass(frozen=True)
class GraphEdge:
    """图边（lineage / dependency / desk_handoff）+ 落图命令引用。

    `edge_id = edge_+content_hash({src,dst,edge_type})`（复用单一身份源）；`command_ref` 同命门 #3。
    `handoff_id` 仅 desk_handoff 边非空（指向 DeskHandoff 记录）。
    """

    src: str
    dst: str
    edge_type: str
    command_ref: str
    handoff_id: str = ""
    edge_id: str = ""

    def __post_init__(self) -> None:
        if self.edge_type not in EDGE_TYPES:
            raise ResearchGraphError(
                f"edge_type 非法：{self.edge_type!r} ∉ {sorted(EDGE_TYPES)}"
            )
        if not self.command_ref:
            raise CanonicalCommandViolation(
                "GraphEdge 缺 command_ref：加边必经 canonical command 落图（GOAL §2）"
            )
        if not self.edge_id:
            object.__setattr__(
                self,
                "edge_id",
                _graph_id(
                    "edge", {"src": self.src, "dst": self.dst, "edge_type": self.edge_type}
                ),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Canonical command（GOAL §2 落点·非 A-CMD 全栈翻译）——改图的唯一载体。
# 本卡只定**落点最小信封**：四类 actor（GOAL §0）+ 目标台 + 内容寻址 id + payload。
# 语义翻译 / 解析 / 全栈校验归 A-CMD（另卡）；本信封只保证「改图必经命令、命令可审计可寻址」。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CanonicalCommand:
    """改图的 canonical command（GOAL §2：user 手动画布/表单/IDE/API 改动都落 canonical command）。

    `actor` ∈ 四类动作来源（GOAL §0）——user_manual 即「手动画布/表单/IDE/API」那一类，与 agent
    动作进同一 audit/lineage。`origin` 是来源面自由标注（canvas/form/ide/api/...·非门·A-CMD 细化）。
    `target_desk` = 发命令的台（命门 #5 写权限按它判）。`payload` = 改动内容（QRO / 边 spec / 交接）。
    """

    command_type: str
    actor: str
    target_desk: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    origin: str = ""
    command_id: str = ""

    def __post_init__(self) -> None:
        if self.command_type not in COMMAND_TYPES:
            raise CanonicalCommandViolation(
                f"command_type 非法：{self.command_type!r} ∉ {sorted(COMMAND_TYPES)}"
            )
        if self.actor not in ACTOR_CLASSES:
            raise CanonicalCommandViolation(
                f"command.actor 非四类动作来源：{self.actor!r} ∉ {sorted(ACTOR_CLASSES)}（GOAL §0）"
            )
        if self.target_desk not in DESKS:
            raise CanonicalCommandViolation(
                f"command.target_desk 非法台：{self.target_desk!r} ∉ {sorted(DESKS)}"
            )
        if not self.command_id:
            object.__setattr__(
                self,
                "command_id",
                _graph_id(
                    "cmd",
                    {
                        "command_type": self.command_type,
                        "actor": self.actor,
                        "target_desk": self.target_desk,
                        # payload 摘要：QRO 取 identity、其余取其确定性指纹（content_hash 内部 canonical）。
                        "payload_digest": content_hash(_payload_digest(self.payload)),
                        "origin": self.origin,
                    },
                ),
            )


def _payload_digest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """把 payload 归一为可内容寻址的摘要（QRO/DeskHandoff 取其稳定 id，其余 JSON-safe 化）。

    鲁棒性：command id 计算绝不能因畸形 payload（如非 QRO 的 duck 对象）崩在构造期——畸形对象的
    准入拒绝归 `_admit_qro`（NodeAdmissionError·诚实文案），不能让 content_hash 先抛 TypeError。
    故非 QRO/DeskHandoff 值若不可 JSON 序列化，退化为确定性 `repr`（仅为命令指纹·非真相载体）。
    """

    out: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, QualifiedResearchObject):
            out[k] = v.identity
        elif isinstance(v, DeskHandoff):
            out[k] = v.handoff_id
        else:
            try:
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = repr(v)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Projection（GOAL §2「每台 Canvas = 同一 Research Graph 的 typed projection」）。
# NodeView / DeskProjection 都是**派生只读视图**——不存独立真相，故结构上不可能与图漂移
# （单一真相源的结构性保证）。`editable` 由 home 台派生；theory/consistency/math 轴恒投影
# （命门 #6：机构级投影必须含 math/consistency）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class NodeView:
    """一个节点在某台的投影视图（派生自图节点·只读）。

    六轴状态 + theory/consistency + mathematical_refs/tib 全从 QRO 读取（单一源）。`editable` =
    本台是否对该对象类型有写权限（home 台）。本视图**不**承载可写真相——改它必须回 `graph.apply`。
    """

    node_id: str
    object_type: str
    natural_key: str
    editable: bool
    # 六轴（分离·不混单绿灯·照搬信封口径）
    definition: str
    theory: str
    consistency: str
    evidence: str
    governance: str
    runtime: str
    # math/consistency 投影载荷（命门 #6）
    mathematical_refs: tuple[str, ...] = ()
    theory_implementation_binding: str = ""
    consistency_verdict: str = ""


@dataclass(frozen=True)
class EdgeView:
    src: str
    dst: str
    edge_type: str
    handoff_id: str = ""


@dataclass(frozen=True)
class DeskProjection:
    """某台的 typed projection（GOAL §2）——当前台决定可见节点/边/状态/可编辑类型。

    `claims_institutional` = 本投影是否对外声称「机构级方法」。命门 #6：声称机构级则每个 NodeView
    必须带 math/consistency 投影（theory/consistency 轴在枚举内·非空裁剪）——`assert_institutional_projection` 兑现。
    """

    desk: str
    node_views: tuple[NodeView, ...]
    edge_views: tuple[EdgeView, ...]
    handoffs: tuple[DeskHandoff, ...]
    editable_types: frozenset[str]
    claims_institutional: bool = False

    def editable_node_ids(self) -> tuple[str, ...]:
        return tuple(v.node_id for v in self.node_views if v.editable)


# ─────────────────────────────────────────────────────────────────────────────
# 机构级投影门（命门 #6 · GOAL §2「当前台声称机构级方法但 Canvas 无 math/consistency projection → 拒」）。
# theory/consistency 轴合法枚举从信封导入（THEORY_STATES/CONSISTENCY_STATES·单一源·不另立一套）。
# ─────────────────────────────────────────────────────────────────────────────
def assert_institutional_projection(projection: DeskProjection) -> None:
    """声称机构级方法的投影必须含 math/consistency 轴投影，否则 ProjectionError（GOAL §2）。

    诚实边界：本门只判**投影结构是否承载 math/consistency 轴**（theory/consistency 在枚举内、不被裁剪）；
    它**不**判理论是否真成立——那归 spine_gate / A-COMPILER。非机构级声称的台可做精简视图、不受此门。
    """

    if not projection.claims_institutional:
        return  # 未声称机构级 → 台可自定精简投影（§2 当前台决定可见内容·不误伤）
    for view in projection.node_views:
        if view.theory not in THEORY_STATES or view.consistency not in CONSISTENCY_STATES:
            raise ProjectionError(
                f"机构级投影缺 math/consistency 轴：节点 {view.node_id!r} "
                f"theory={view.theory!r} consistency={view.consistency!r}（GOAL §2：当前台声称"
                "机构级方法但 Canvas 无 math/consistency projection → 拒）"
            )


# ── SA-4 占位种子 write门 ──────────────────────────────────────────────────────
# 已移除的 "goal closure" 闭合 materializer 曾播种自证闭合占位记录（见 research_os.spine 同名门
# 与 platform_coverage._PLACEHOLDER_TOKENS 的 goal_closure 项）。canonical command 是图的唯一写口，
# 故在此 fail-closed 掉任何 id/内容携 goal_closure 占位 token 的命令。只覆盖 goal_closure 族（不含
# synthetic/fixture），与 spine 写门对齐；大小写不敏感子串匹配，三变体全抓。
_GOAL_CLOSURE_SEED_TOKENS: tuple[str, ...] = ("goal_closure", "goal-closure", "goalclosure")


def _command_carries_goal_closure_seed(command: "CanonicalCommand") -> bool:
    """True 当命令的 id/内容（含 payload 内嵌 QRO/交接的展开字段）携任一 goal_closure 占位 token。

    用 ``asdict`` 递归展开命令及其嵌套 dataclass（QRO 的 natural_key/contract、DeskHandoff…），
    故 token 即便藏在 QRO 内层字段也抓得到（QRO.identity 是 content_hash·会把明文洗成哈希·不可只扫它）。
    asdict 万一遇非常规 payload 退化为 ``repr`` 兜底（绝不让扫描自身抛错放过种子）。
    """

    try:
        serialized = json.dumps(asdict(command), ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - 扫描兜底：repr 总能拿到全字段文本，宁可多扫不可漏扫。
        serialized = repr(command)
    lowered = serialized.lower()
    return any(token in lowered for token in _GOAL_CLOSURE_SEED_TOKENS)


# ─────────────────────────────────────────────────────────────────────────────
# Research Graph IR（GOAL §1 QRO→Compiler 之间的 typed 图）。
# 唯一公共写口 = apply(command)；真相状态唯一份存图；各台投影派生只读。
# ─────────────────────────────────────────────────────────────────────────────
class ResearchGraph:
    """Research Graph IR——持有 QRO 节点 + 边 + 交接，单写路径（canonical command）+ 各台投影。

    单一真相源（GOAL §2）：节点状态（六轴）只存图里一份；`node_state` 是计算真相态的**唯一**函数，
    投影与单一源门都经它（绝不让两处各算一套）。单写路径（GOAL §2）：`apply(command)` 是唯一公共
    mutator——`_nodes/_edges/_handoffs` 私有，无第二条裸写路径；`assert_commanded` 是其可证伪探针。
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._handoffs: dict[str, DeskHandoff] = {}
        # 交接的落图命令引用（与节点/边的 command_ref 同义·命门 #3 凭证）。
        self._handoff_command_ref: dict[str, str] = {}
        self._command_log: list[CanonicalCommand] = []  # append-only 命令账（命门 #3 凭证源）

    # ── 单写路径：apply(command) ────────────────────────────────────────────
    def apply(self, command: CanonicalCommand) -> Any:
        """图的**唯一公共写口**（GOAL §2 canonical command 落点）。

        按命令类型分派；落任何元素都 stamp `command_ref = command.command_id` 并把命令 append 进账。
        没有第二条公共裸写路径——这是「user 手动改动未落 canonical command → 拒」的结构性兑现。
        """

        if not isinstance(command, CanonicalCommand):
            raise CanonicalCommandViolation(
                "apply 只接受 CanonicalCommand（改图必经 canonical command·GOAL §2）"
            )
        # SA-4 write门：拒任何 id/内容携 goal_closure 占位 token 的命令（自证闭合种子≠真命令）。
        # 在 dispatch 落图之前拒 → 不进 _command_log、不动节点/边（原子 fail-closed）。
        if _command_carries_goal_closure_seed(command):
            raise CanonicalCommandViolation(
                "research-graph command rejected: goal_closure placeholder seed is not a real "
                "canonical command (SA-4 write門 fail-closes self-certifying closure seeds)"
            )
        dispatch = {
            CMD_CREATE_NODE: self._apply_create_node,
            CMD_UPDATE_NODE: self._apply_update_node,
            CMD_ADD_EDGE: self._apply_add_edge,
            CMD_OPEN_HANDOFF: self._apply_open_handoff,
            CMD_RESOLVE_HANDOFF: self._apply_resolve_handoff,
        }
        handler = dispatch.get(command.command_type)
        if handler is None:  # COMMAND_TYPES 已在 __post_init__ 拦，这里是防御性兜底
            raise CanonicalCommandViolation(f"未支持的 command_type：{command.command_type!r}")
        result = handler(command)
        self._command_log.append(command)
        return result

    # ── 节点准入 / 状态迁移 ──────────────────────────────────────────────────
    def _admit_qro(self, qro: Any) -> QualifiedResearchObject:
        """命门 #2：进图的必须是真 QRO，且 signal/forecast 必带 typed contract（GOAL §1）。

        图是 §1 链的 chokepoint——独立 re-assert 信封不变量，绝不盲信上游（CONTRACT_REQUIRING_TYPES
        从信封导入·单一源·不另定一套）。非 QRO 对象（裸 dict/duck）进图即拒（绕信封 = 绕单一真相源）。
        """

        if not isinstance(qro, QualifiedResearchObject):
            raise NodeAdmissionError(
                f"进图对象非 QualifiedResearchObject：{type(qro).__name__}（图只收编真信封·GOAL §1/§2）"
            )
        if qro.object_type in CONTRACT_REQUIRING_TYPES and not qro.typed_contract:
            raise NodeAdmissionError(
                f"{qro.object_type!r} 节点缺 typed input/output contract：信号/预测输出必须绑定"
                " Signal Contract 才能进图（GOAL §1：QRO 节点无 typed contract → 拒）"
            )
        return qro

    def _assert_write_authority(self, target_desk: str, object_type: str) -> None:
        """命门 #5：写某对象的台必须是其 home 台（GOAL §2 写权限按台隔离）。

        例：strategy_desk 写 OBJ_FACTOR → home(factor)=factor_desk ≠ strategy_desk → 拒。
        （策略台可**引用** factor——那是 dependency 边·非写 factor 本体·见 _apply_add_edge。）
        """

        home = home_desk_of(object_type)
        if target_desk != home:
            raise WriteAuthorityViolation(
                f"写权限越界：{target_desk!r} 不能写 {object_type!r}（home 台 = {home!r}）。"
                f"GOAL §2：策略台直接写 Factor formula → 拒；写权限按台隔离。"
            )

    def _apply_create_node(self, command: CanonicalCommand) -> GraphNode:
        qro = self._admit_qro(command.payload.get("qro"))
        self._assert_write_authority(command.target_desk, qro.object_type)
        existing = self._nodes.get(qro.identity)
        if existing is not None:
            # 内容寻址幂等：同身份 + 同状态 → no-op 返回既有；同身份不同状态 → 拒（用 update_node·不静默覆盖）。
            if existing.qro == qro:
                return existing
            raise CanonicalCommandViolation(
                f"节点 {qro.identity!r} 已存在且状态不同：create_node 不静默覆盖——状态迁移请用 update_node"
            )
        node = GraphNode(qro=qro, command_ref=command.command_id)
        self._nodes[node.node_id] = node
        return node

    def _apply_update_node(self, command: CanonicalCommand) -> GraphNode:
        qro = self._admit_qro(command.payload.get("qro"))
        self._assert_write_authority(command.target_desk, qro.object_type)
        if qro.identity not in self._nodes:
            raise CanonicalCommandViolation(
                f"update_node 目标节点不存在：{qro.identity!r}（先 create_node 收编）"
            )
        node = GraphNode(qro=qro, command_ref=command.command_id)
        self._nodes[node.node_id] = node  # 同身份新状态：唯一真相态原地更新、历史在命令账
        return node

    # ── 边（lineage / dependency）──────────────────────────────────────────
    def _apply_add_edge(self, command: CanonicalCommand) -> GraphEdge:
        src = str(command.payload.get("src", ""))
        dst = str(command.payload.get("dst", ""))
        edge_type = str(command.payload.get("edge_type", ""))
        if edge_type == EDGE_DESK_HANDOFF:
            raise CanonicalCommandViolation(
                "desk_handoff 边请用 open_handoff/resolve_handoff 命令（伴随 DeskHandoff 记录）"
            )
        if src not in self._nodes or dst not in self._nodes:
            raise GraphIntegrityError(
                f"加边引用不存在的节点（无悬空·GOAL §8）：src={src!r} dst={dst!r}"
            )
        # 命门 #5（边形态）：加 src 的出边 = 写 src 的依赖/血统 → target_desk 必须是 src 的 home 台。
        # 这放行「策略台加 strategy→factor 依赖」（src=strategy·策略台 home），拦「策略台改 factor 出边」。
        self._assert_write_authority(command.target_desk, self._nodes[src].qro.object_type)
        edge = GraphEdge(src=src, dst=dst, edge_type=edge_type, command_ref=command.command_id)
        self._edges[edge.edge_id] = edge
        return edge

    # ── DeskHandoff（跨台交接·命门 #4）─────────────────────────────────────
    def _apply_open_handoff(self, command: CanonicalCommand) -> DeskHandoff:
        handoff = command.payload.get("handoff")
        if not isinstance(handoff, DeskHandoff):
            raise CanonicalCommandViolation("open_handoff.payload['handoff'] 必须是 DeskHandoff")
        if handoff.status not in (HANDOFF_OPEN, HANDOFF_IN_PROGRESS):
            raise CanonicalCommandViolation(
                f"open_handoff 只能开 open/in_progress 态交接，收到 status={handoff.status!r}"
            )
        # 落图凭证（命门 #3）：交接也必须经命令落图——把 command_ref 记进命令账，交接以 handoff_id 入图。
        self._handoffs[handoff.handoff_id] = handoff
        self._handoff_command_ref[handoff.handoff_id] = command.command_id
        return handoff

    def _apply_resolve_handoff(self, command: CanonicalCommand) -> DeskHandoff:
        handoff_id = str(command.payload.get("handoff_id", ""))
        produced_ref = str(command.payload.get("produced_ref", ""))
        resolved_by = str(command.payload.get("resolved_by", ""))
        evidence_refs = tuple(command.payload.get("evidence_refs", ()) or ())
        open_handoff = self._handoffs.get(handoff_id)
        if open_handoff is None:
            raise GraphIntegrityError(
                f"resolve_handoff 目标交接不存在：{handoff_id!r}（无法解决未开的交接）"
            )
        # 命门 #4 在 DeskHandoff.__post_init__ 兑现：resolved 缺 produced_ref → HandoffIncompleteError。
        resolved = replace(
            open_handoff,
            status=HANDOFF_RESOLVED,
            produced_ref=produced_ref,
            resolved_by=resolved_by,
            evidence_refs=evidence_refs or open_handoff.evidence_refs,
            handoff_id=open_handoff.handoff_id,  # 保身份（解决不改 handoff_id）
        )
        self._handoffs[handoff_id] = resolved
        self._handoff_command_ref[handoff_id] = command.command_id
        return resolved

    # ── 单一真相源（命门 #1）─────────────────────────────────────────────────
    def node_state(self, node_id: str) -> dict[str, str]:
        """节点真相态（六轴）——计算真相的**唯一**函数（投影与单一源门都经它·不另算一套）。"""

        node = self._nodes.get(node_id)
        if node is None:
            raise GraphIntegrityError(f"节点不存在：{node_id!r}")
        return node.qro.state_axes()

    def assert_single_source(
        self, desk: str, claimed_states: Mapping[str, Mapping[str, str]]
    ) -> None:
        """命门 #1：某台声称的真相态必须等于图节点（唯一真相源），否则 SingleSourceViolation（GOAL §2）。

        `claimed_states` 模拟「一个维护独立真相状态的台」呈上的私有副本。任一节点的声称态 ≠ 图的
        canonical 态（或指向图里不存在的节点）→ 拒。正路径（台呈派生只读投影·恒等于图）必过、不误伤。
        """

        for node_id, claimed in claimed_states.items():
            if node_id not in self._nodes:
                raise SingleSourceViolation(
                    f"{desk!r} 声称节点 {node_id!r} 的真相态，但图（唯一真相源）无此节点"
                    "——该台在维护图外独立状态（GOAL §2：任一台维护独立真相状态 → 拒）"
                )
            canonical = self.node_state(node_id)
            divergent = {
                axis: (claimed.get(axis), canonical[axis])
                for axis in canonical
                if axis in claimed and claimed[axis] != canonical[axis]
            }
            if divergent:
                raise SingleSourceViolation(
                    f"{desk!r} 的真相态与图（唯一真相源）矛盾：节点 {node_id!r} 漂移轴 "
                    + "、".join(f"{a}:台={c[0]!r}≠图={c[1]!r}" for a, c in divergent.items())
                    + "（GOAL §2：任一台维护独立真相状态 → 拒）"
                )

    def assert_single_source_across_desks(
        self, claims_by_desk: Mapping[str, Mapping[str, Mapping[str, str]]]
    ) -> None:
        """命门 #1（多台版·卡对抗规格 verbatim）：构造两台不同状态 → 单一源门必抓矛盾。

        每台声称态都对照唯一真相源（图）校验；只要有台漂移即拒——两台彼此矛盾必因至少一台 ≠ 图，
        故对照图即抓。诚实：图是仲裁者，不存在「两台都对、图错」的合法态（图就是真相定义）。
        """

        for desk, claims in claims_by_desk.items():
            self.assert_single_source(desk, claims)

    # ── 落图凭证完整性（命门 #3 探针）──────────────────────────────────────
    def assert_commanded(self) -> None:
        """命门 #3：每个图元素（节点/边/交接）都必须由命令账里的 canonical command 落入（GOAL §2）。

        正路径下 `apply` 恒 stamp command_ref，故此门恒过；它是**裸写探针**——若有人绕 apply 直插
        `_nodes/_edges`（维护图外状态 / 手动改动未落命令）→ 该元素 command_ref ∉ 命令账 → 拒。
        """

        logged = {c.command_id for c in self._command_log}
        for node in self._nodes.values():
            if node.command_ref not in logged:
                raise CanonicalCommandViolation(
                    f"节点 {node.node_id!r} 的 command_ref={node.command_ref!r} 不在命令账"
                    "——改动未落 canonical command（GOAL §2 → 拒）"
                )
        for edge in self._edges.values():
            if edge.command_ref not in logged:
                raise CanonicalCommandViolation(
                    f"边 {edge.edge_id!r} 的 command_ref={edge.command_ref!r} 不在命令账（GOAL §2 → 拒）"
                )
        for hid, cref in self._handoff_command_ref.items():
            if cref not in logged:
                raise CanonicalCommandViolation(
                    f"交接 {hid!r} 的 command_ref={cref!r} 不在命令账（GOAL §2 → 拒）"
                )

    # ── 各台 typed projection（命门 #6 + 不误伤）────────────────────────────
    def project(self, desk: str, *, claims_institutional: bool = False) -> DeskProjection:
        """GOAL §2：某台 Canvas = 同一 Research Graph 的 typed projection（派生只读·不存独立真相）。

        当前台决定**可见节点/边/交接 + 可编辑类型**（editable = home 台）。math/consistency 轴恒投影
        进每个 NodeView（命门 #6 载荷）；`claims_institutional=True` 时该投影过 `assert_institutional_projection`。
        默认全图可见（§2 Agent 能力全局完整）；可编辑仅本台 home 类型（§2 写权限按台隔离）。
        """

        if desk not in DESKS:
            raise ResearchGraphError(f"未知台：{desk!r} ∉ {sorted(DESKS)}")
        editable_types = frozenset(
            obj_type for obj_type, home in HOME_DESK_OF.items() if home == desk
        )
        node_views = tuple(
            self._node_view(node, editable_types) for node in self._nodes.values()
        )
        edge_views = tuple(
            EdgeView(src=e.src, dst=e.dst, edge_type=e.edge_type, handoff_id=e.handoff_id)
            for e in self._edges.values()
        )
        # 交接投影：本台相关（from/to 命中）的交接（§2 跨台需求通过 DeskHandoff 连接）。
        handoffs = tuple(
            h for h in self._handoffs.values() if desk in (h.from_desk, h.to_desk)
        )
        projection = DeskProjection(
            desk=desk,
            node_views=node_views,
            edge_views=edge_views,
            handoffs=handoffs,
            editable_types=editable_types,
            claims_institutional=claims_institutional,
        )
        # 命门 #6：声称机构级 → 验证 math/consistency 投影齐备（未声称则精简视图放行·不误伤）。
        assert_institutional_projection(projection)
        return projection

    def _node_view(self, node: GraphNode, editable_types: frozenset[str]) -> NodeView:
        """节点 → 某台 NodeView（六轴 + math/consistency 从 QRO 单一源读取·editable 由 home 派生）。"""

        q = node.qro
        return NodeView(
            node_id=node.node_id,
            object_type=q.object_type,
            natural_key=q.natural_key,
            editable=q.object_type in editable_types,
            definition=q.definition,
            theory=q.theory,
            consistency=q.consistency,
            evidence=q.evidence,
            governance=q.governance,
            runtime=q.runtime,
            mathematical_refs=tuple(q.mathematical_refs),
            theory_implementation_binding=q.theory_implementation_binding,
            consistency_verdict=q.consistency_verdict,
        )

    # ── 只读访问器 ─────────────────────────────────────────────────────────
    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def get_handoff(self, handoff_id: str) -> DeskHandoff | None:
        return self._handoffs.get(handoff_id)

    def nodes(self) -> tuple[GraphNode, ...]:
        return tuple(self._nodes.values())

    def edges(self) -> tuple[GraphEdge, ...]:
        return tuple(self._edges.values())

    def handoffs(self) -> tuple[DeskHandoff, ...]:
        return tuple(self._handoffs.values())

    def command_log(self) -> tuple[CanonicalCommand, ...]:
        return tuple(self._command_log)

    def __len__(self) -> int:
        return len(self._nodes)


__all__ = [
    # 台
    "DESK_DATA",
    "DESK_FACTOR",
    "DESK_MODEL",
    "DESK_SIGNAL",
    "DESK_STRATEGY",
    "DESK_BACKTEST",
    "DESK_EXECUTION",
    "DESK_RESEARCH",
    "DESK_SETTINGS",
    "DESKS",
    "HOME_DESK_OF",
    "home_desk_of",
    # 边 / 交接 / 命令 词汇
    "EDGE_LINEAGE",
    "EDGE_DEPENDENCY",
    "EDGE_DESK_HANDOFF",
    "EDGE_TYPES",
    "HANDOFF_OPEN",
    "HANDOFF_IN_PROGRESS",
    "HANDOFF_RESOLVED",
    "HANDOFF_REJECTED",
    "HANDOFF_STATES",
    "CMD_CREATE_NODE",
    "CMD_UPDATE_NODE",
    "CMD_ADD_EDGE",
    "CMD_OPEN_HANDOFF",
    "CMD_RESOLVE_HANDOFF",
    "COMMAND_TYPES",
    # 数据类
    "DeskHandoff",
    "GraphNode",
    "GraphEdge",
    "CanonicalCommand",
    "NodeView",
    "EdgeView",
    "DeskProjection",
    "ResearchGraph",
    # 门
    "assert_institutional_projection",
    # 异常
    "ResearchGraphError",
    "SingleSourceViolation",
    "NodeAdmissionError",
    "CanonicalCommandViolation",
    "HandoffIncompleteError",
    "WriteAuthorityViolation",
    "ProjectionError",
    "GraphIntegrityError",
]
