"""CanonicalCommand 全栈（GOAL §1 统一对象链 · §2 多台工作系统）——写 Research Graph 的唯一治理通道。

GOAL §1 链：`Quant Intent → Typed Canvas/Command → QRO → Research Graph → Governed Compiler → …`。
A-GRAPH-1（`graph/research_graph.py`）已落**命令最小信封**（`CanonicalCommand`：四类 actor + 目标台 +
内容寻址 id + payload）与图的写口 `ResearchGraph.apply(command)`。本模块（A-CMD）在写口**之前**建
**CanonicalCommand 全栈**——GOAL §2「user 手动画布/表单/IDE/API 改动都落 canonical command·与 Agent
动作进入同一 audit/lineage/lifecycle」：

  ① typed 命令层（`CommandBus`）：写 Research Graph 的**唯一通道**。user 手动 + agent 动作同源进同一门，
     由它铸 `CanonicalCommand` 并落图（`apply`）；没有第二条公共写路径。
  ② 语义翻译 / 解析（`translate_intent`）：把**面向台面的语义动作**（intent / canvas action：create /
     update / link / request_handoff / fulfill_handoff）翻成图的 **typed command**（CMD_CREATE_NODE …）。
  ③ 全栈校验（`validate_intent` + `assert_content_addressed`）：actor 四类 / 目标台 / 内容寻址 id /
     **payload schema**（每命令类型的载荷形状——A-GRAPH-1 信封未做的那层）。
  ④ provenance（`Provenance` + `CommandLedger`）：命令来源面（canvas / form / ide / api / agent_runtime /
     scheduler）+ actor 四类，落进**同一本** append-only audit/lineage 账——user 手动与 agent 同链、
     provenance 区分但不分账。

为什么是「通道 + 翻译 + 账」而非「另造一套命令 / 身份」（RULES §1 单一源 + §4 扩展不替换）：
- typed command **就是** `research_graph.CanonicalCommand`（frozen·内容寻址）——本层**收编只读**它、铸它、
  落它，**绝不**另定第二套命令类型或第二套身份哈希。`command_id` / `qro.identity` / `handoff_id` 全走
  `lineage.ids.content_hash`（前缀族·不另造）；actor 四类从 `qro.envelope.ACTOR_CLASSES` 导入（单一源）。
- 写权限按台隔离（home 台）是**图的门**（`research_graph._assert_write_authority`·单一源）——本层**不**重算，
  只在 actor / 目标台 / 内容寻址 / payload schema / provenance 五面把关，把 well-formed 的命令交给图，
  图独立 re-assert 写权限（分层防御·不双源）。
- 唯一公共写口 = `CommandBus.submit(intent)`；图命令账与命令通道账对账（`assert_single_channel`）是
  「user 手动改动未落 canonical command（通道）→ 拒」的可证伪探针——任一图命令不在通道账 = 绕通道直写 = 拒。

六个命门（可证伪验收 · 种坏门必抓 · RULES §2 · GOAL §1/§2）：
1. 通道唯一：任一图命令未经命令通道（bus）铸入（绕 bus 直写图）→ `ChannelBypassViolation`（§2「user 手动
   改动未落 canonical command → 拒」的通道形态）。
2. actor 四类：命令意图的 actor 非四类动作来源 → `ProvenanceError`（由 `assert_actor_surface_coherent`
   首检单点把关·与 #6 同门·§0/§2）。
3. 目标台：命令意图缺 / 错目标台 / 未知语义动作 → `CommandValidationError`（§2）。
4. 内容寻址：命令 `command_id` 缺 / 被伪造（≠ 单一源 content_hash 重算）→ `ContentAddressViolation`（§0/§2）。
5. payload schema：每命令类型的载荷形状不合（create/update 缺真 QRO、link 缺 src/dst/合法 edge_type、
   handoff 缺必填）→ `PayloadSchemaError`（§2 全栈校验）。
6. provenance 同链 + 来源面相容：user 手动与 agent 命令进同一本账（§2「同一 audit/lineage」），且 actor 与
   来源面相容（user_manual 只能来自 canvas/form/ide/api；agent 不能冒充人手面）→ `ProvenanceError`（§0/§2）。

诚实边界（本模块**不**做什么）：
- 它**不**建 Governed Compiler（A-COMPILER 另卡）——不消费命令跑确定性 run、不判 evidence/理论/一致性。
  本层止于「翻译 + 校验 + provenance + 落图」，绝不把任一状态渲染成可信。
- 它**不**重算图的写权限（home 台）/ 节点准入（typed contract）/ 单一真相源——那些是图的门（单一源），
  本层只把关命令层五面，图独立 re-assert（分层防御）。
- 它**不**建前端 Canvas 交互——只提供后端命令通道；canvas/form/ide/api 是 provenance 来源面标注，非 UI。
- provenance 来源面相容门只判**actor↔来源面结构相容**（§2 人手面 vs agent 面），**不**判动作是否真由该
  actor 发起（那需运行时身份认证·上游 Auth 的活·诚实残余）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..graph.research_graph import (
    CMD_ADD_EDGE,
    CMD_CREATE_NODE,
    CMD_OPEN_HANDOFF,
    CMD_RESOLVE_HANDOFF,
    CMD_UPDATE_NODE,
    COMMAND_TYPES,
    DESKS,
    EDGE_DEPENDENCY,
    EDGE_LINEAGE,
    CanonicalCommand,
    DeskHandoff,
    GraphEdge,
    GraphNode,
    ResearchGraph,
)
from ..lineage.ids import content_hash
from ..qro.envelope import (
    ACTOR_AGENT,
    ACTOR_CLASSES,
    ACTOR_SCHEDULED_AGENT,
    ACTOR_USER_CONFIRMED_AGENT,
    ACTOR_USER_MANUAL,
    QualifiedResearchObject,
)

# ─────────────────────────────────────────────────────────────────────────────
# Provenance 来源面（GOAL §2「user 手动画布/表单/IDE/API 改动」+ agent/scheduled 面）。
# 这是命令**从哪个面进入系统**的 typed 标注（A-GRAPH-1 把 origin 留作自由串·此处细化为门）。
# ─────────────────────────────────────────────────────────────────────────────
ORIGIN_CANVAS = "canvas"  # 台面画布（§2 手动面）
ORIGIN_FORM = "form"  # 表单（§2 手动面）
ORIGIN_IDE = "ide"  # IDE（§2 手动面）
ORIGIN_API = "api"  # API（§2：人或 agent 皆可程控调用——共享边界）
ORIGIN_AGENT_RUNTIME = "agent_runtime"  # 常驻 Agent 运行时（§0 agent 动作面）
ORIGIN_SCHEDULER = "scheduler"  # 调度器（§0 scheduled_agent 面）
ORIGIN_SURFACES: frozenset[str] = frozenset(
    {ORIGIN_CANVAS, ORIGIN_FORM, ORIGIN_IDE, ORIGIN_API, ORIGIN_AGENT_RUNTIME, ORIGIN_SCHEDULER}
)

# 人手面（§2「user 手动画布/表单/IDE/API」verbatim）——user_manual 只能来自这一组。
HUMAN_MANUAL_SURFACES: frozenset[str] = frozenset(
    {ORIGIN_CANVAS, ORIGIN_FORM, ORIGIN_IDE, ORIGIN_API}
)

# ─────────────────────────────────────────────────────────────────────────────
# actor ↔ 来源面相容（命门 #6 · GOAL §0 四类 actor × §2 来源面）。
# 这是 §2「user 手动画布/表单/IDE/API」与 §0 四类动作来源的**结构编码**，非价值判断：
#   - user_manual 只能来自人手面（canvas/form/ide/api）——绝不来自 agent_runtime/scheduler。
#   - 纯 agent / scheduled_agent 绝不冒充人手画布/表单/IDE（那是 §2 的「手动」面）。
#   - api 是共享边界（人或 agent 皆可程控）——对所有 actor 放行（诚实承认这一面歧义）。
# 抓的是 provenance 洗白：手动动作伪称来自 agent 运行时、或 agent 动作伪称来自人手画布。
# actor 四类常量从 qro.envelope 导入（**单一源·不另造**）；本表 key 必恰好 == ACTOR_CLASSES（import 期自检）。
# ─────────────────────────────────────────────────────────────────────────────
ACTOR_SURFACE_ALLOWED: dict[str, frozenset[str]] = {
    # 人手动：只人手面（§2 verbatim）
    ACTOR_USER_MANUAL: HUMAN_MANUAL_SURFACES,
    # 人确认 + agent 执行：人经手面确认（canvas/form/ide/api）或 agent 运行时执行
    ACTOR_USER_CONFIRMED_AGENT: HUMAN_MANUAL_SURFACES | {ORIGIN_AGENT_RUNTIME},
    # 自治 agent：运行时 / api（程控）——不冒充人手画布/表单/IDE
    ACTOR_AGENT: frozenset({ORIGIN_AGENT_RUNTIME, ORIGIN_API}),
    # 调度 agent：调度器 / 运行时 / api
    ACTOR_SCHEDULED_AGENT: frozenset({ORIGIN_SCHEDULER, ORIGIN_AGENT_RUNTIME, ORIGIN_API}),
}

# import 期自检（fail-fast·非 assert·-O 不剥）：相容表 key 必须恰好覆盖 §0 四类 actor（单一源·防漂）。
_actor_keys = frozenset(ACTOR_SURFACE_ALLOWED)
if _actor_keys != ACTOR_CLASSES:
    raise RuntimeError(
        f"ACTOR_SURFACE_ALLOWED 与 ACTOR_CLASSES（单一源 qro.envelope）不一致："
        f"缺 {sorted(ACTOR_CLASSES - _actor_keys)}、多 {sorted(_actor_keys - ACTOR_CLASSES)}"
        "——provenance 来源面门须恰好覆盖四类 actor（GOAL §0）"
    )
for _a, _surfs in ACTOR_SURFACE_ALLOWED.items():
    _stray = _surfs - ORIGIN_SURFACES
    if _stray:
        raise RuntimeError(
            f"ACTOR_SURFACE_ALLOWED[{_a!r}] 含未登记来源面 {sorted(_stray)} ∉ ORIGIN_SURFACES"
        )

# ─────────────────────────────────────────────────────────────────────────────
# 语义动作（GOAL §2「intent / canvas action」面向台面词汇）→ 图 typed command（②翻译表）。
# 台面（canvas/form/ide/api/agent）说**语义动作**；本表是把它翻成图命令的**单一翻译源**。
# ─────────────────────────────────────────────────────────────────────────────
ACTION_CREATE_ASSET = "create_asset"  # 画布落子 / 表单新建一个资产 → 收编 QRO 进图
ACTION_UPDATE_ASSET = "update_asset"  # 画布编辑 / 表单改字段 → 同身份状态迁移
ACTION_LINK_ASSETS = "link_assets"  # 画布连线 → 加 lineage/dependency 边
ACTION_REQUEST_HANDOFF = "request_handoff"  # 跨台请求 → 开一条 DeskHandoff
ACTION_FULFILL_HANDOFF = "fulfill_handoff"  # 交付 → 解决 DeskHandoff（带 produced_ref）
ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_CREATE_ASSET,
        ACTION_UPDATE_ASSET,
        ACTION_LINK_ASSETS,
        ACTION_REQUEST_HANDOFF,
        ACTION_FULFILL_HANDOFF,
    }
)

ACTION_TO_COMMAND: dict[str, str] = {
    ACTION_CREATE_ASSET: CMD_CREATE_NODE,
    ACTION_UPDATE_ASSET: CMD_UPDATE_NODE,
    ACTION_LINK_ASSETS: CMD_ADD_EDGE,
    ACTION_REQUEST_HANDOFF: CMD_OPEN_HANDOFF,
    ACTION_FULFILL_HANDOFF: CMD_RESOLVE_HANDOFF,
}

# link 动作允许的边类型：lineage / dependency（desk_handoff 边走 handoff 动作·不走 link）。
LINK_EDGE_TYPES: frozenset[str] = frozenset({EDGE_LINEAGE, EDGE_DEPENDENCY})

# import 期自检：翻译表必须恰好覆盖 ACTIONS，且每个目标都是图的合法 command（单一源·防漂）。
if frozenset(ACTION_TO_COMMAND) != ACTIONS:
    raise RuntimeError(
        f"ACTION_TO_COMMAND 与 ACTIONS 不一致：缺 {sorted(ACTIONS - frozenset(ACTION_TO_COMMAND))}、"
        f"多 {sorted(frozenset(ACTION_TO_COMMAND) - ACTIONS)}（语义翻译单一源·防漂）"
    )
_bad_targets = set(ACTION_TO_COMMAND.values()) - set(COMMAND_TYPES)
if _bad_targets:
    raise RuntimeError(
        f"ACTION_TO_COMMAND 映射到非法图 command_type {sorted(_bad_targets)} ∉ COMMAND_TYPES"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 异常族（每门一类·诚实拒绝文案·绝不静默放行）。与图的 CanonicalCommandViolation 正交并存：
# 那是图写口内不变量，这是命令**通道**层（翻译 / 校验 / provenance / 通道唯一）不变量。
# ─────────────────────────────────────────────────────────────────────────────
class CommandError(Exception):
    """CanonicalCommand 全栈（通道层）不变量被违反的基类。"""


class CommandValidationError(CommandError):
    """命门 #3：命令意图缺 / 错目标台 / 未知语义动作（GOAL §2）。actor 四类归 ProvenanceError（命门 #2/#6）。"""


class ProvenanceError(CommandError):
    """命门 #2/#6：actor 非四类 / actor 与来源面不相容（手动面 vs agent 面洗白 · GOAL §0/§2）。"""


class PayloadSchemaError(CommandValidationError):
    """命门 #5：命令载荷形状不合该命令类型（缺真 QRO / 缺 src·dst / 缺 handoff 必填 · GOAL §2）。"""


class CommandTranslationError(CommandError):
    """语义动作无法翻成 typed command（未知 action / 载荷无法解析 · GOAL §2 翻译）。"""


class ContentAddressViolation(CommandError):
    """命门 #4：command_id 缺 / 被伪造（≠ 单一源 content_hash 重算 · GOAL §0/§2 内容寻址）。"""


class ChannelBypassViolation(CommandError):
    """命门 #1：图里有命令未经命令通道（bus）铸入——绕通道直写图（GOAL §2「未落 canonical command → 拒」）。"""


# ─────────────────────────────────────────────────────────────────────────────
# Provenance（④ · GOAL §2 命令来源面 + §0 四类 actor）——frozen 内容寻址来源记录。
# actor 与来源面在 __post_init__ 即过相容门（命门 #6）；`token()` 是落进 command.origin 的确定性指纹，
# 让图命令账也带上 provenance 来源（与通道账同源·可对账）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Provenance:
    """命令来源（GOAL §2：user 手动画布/表单/IDE/API 改动·与 Agent 动作同 audit/lineage）。

    `actor` ∈ 四类动作来源（GOAL §0·单一源 ACTOR_CLASSES）；`surface` ∈ 来源面（ORIGIN_SURFACES）。
    `actor_id`/`session_ref`/`request_ref` 为可选审计细节（谁 / 哪个会话 / 哪个请求·默认空 = 命令指纹稳定）。
    """

    actor: str
    surface: str
    actor_id: str = ""
    session_ref: str = ""
    request_ref: str = ""

    def __post_init__(self) -> None:
        assert_actor_surface_coherent(self.actor, self.surface)

    def token(self) -> str:
        """落进 `command.origin` 的确定性 provenance 指纹（复用单一源 content_hash·前缀 prov_·不另造哈希）。"""

        return "prov_" + content_hash(
            {
                "actor": self.actor,
                "surface": self.surface,
                "actor_id": self.actor_id,
                "session_ref": self.session_ref,
                "request_ref": self.request_ref,
            }
        )


def assert_actor_surface_coherent(actor: str, surface: str) -> None:
    """命门 #6：actor ∈ 四类 且 actor 与来源面相容，否则 ProvenanceError（GOAL §0/§2）。

    诚实边界：只判**结构相容**（§2 人手面 vs agent 面），不判动作是否真由该 actor 发起（运行时身份
    认证是上游 Auth 的活·诚实残余）。抓的是 provenance 洗白（手动伪称 agent 面 / agent 冒充人手画布）。
    """

    if actor not in ACTOR_CLASSES:
        raise ProvenanceError(
            f"provenance.actor 非四类动作来源：{actor!r} ∉ {sorted(ACTOR_CLASSES)}（GOAL §0）"
        )
    if surface not in ORIGIN_SURFACES:
        raise ProvenanceError(
            f"provenance.surface 非法来源面：{surface!r} ∉ {sorted(ORIGIN_SURFACES)}（GOAL §2）"
        )
    allowed = ACTOR_SURFACE_ALLOWED[actor]
    if surface not in allowed:
        raise ProvenanceError(
            f"provenance 来源面与 actor 不相容：actor={actor!r} 不能来自 surface={surface!r}"
            f"（允许 {sorted(allowed)}）。GOAL §2：user 手动画布/表单/IDE/API 改动 = 人手面；"
            "agent 动作 = agent 面——provenance 区分但不可互相洗白。"
        )


# ─────────────────────────────────────────────────────────────────────────────
# CommandIntent（② · GOAL §2 intent / canvas action）——面向台面的语义请求（待翻译 typed command）。
# 这是 canvas/form/ide/api/agent 各台面共同的**语义请求**入口。它是瞬态请求（被翻译后即弃），故只在
# __post_init__ 做类型形状自检；值级全栈校验（actor/台/schema）归 `validate_intent`（命门 #2/#3/#5·可独测）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CommandIntent:
    """面向台面的语义动作请求（GOAL §2）——`action` 语义动词 + `target_desk` + `provenance` + `args`。

    `args` 按 action 携带载荷：create/update→{"qro": QRO}；link→{"src","dst","edge_type"}；
    request_handoff→{"handoff": DeskHandoff} 或 {from_desk,to_desk,requested_asset,...}；
    fulfill_handoff→{"handoff_id","produced_ref","resolved_by"?,"evidence_refs"?}。
    """

    action: str
    target_desk: str
    provenance: Provenance
    args: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            raise CommandValidationError(
                "CommandIntent.provenance 必须是 Provenance（命令必须带来源·GOAL §2）"
            )
        if not isinstance(self.args, Mapping):
            raise PayloadSchemaError("CommandIntent.args 必须是 Mapping（命令载荷）")


# ─────────────────────────────────────────────────────────────────────────────
# 全栈校验（③ · 命门 #2/#3/#5/#6）——actor 四类 / 目标台 / payload schema / provenance。
# ─────────────────────────────────────────────────────────────────────────────
def validate_intent(intent: CommandIntent) -> None:
    """命令意图全栈校验（GOAL §2）——actor 四类 + 目标台 + 动作合法 + provenance + **payload schema**。

    这是 A-GRAPH-1 信封未做的「全栈校验」那层：除 actor/台/内容寻址外，逐命令类型校验**载荷形状**。
    防御纵深：actor/provenance 在 `Provenance.__post_init__` 已过一道，此处对（可能被 object.__setattr__
    篡改后的）意图**再 re-assert**——绕构造期 = 绕单一门，故通道入口独立 re-assert（命门 #2/#6·可证伪）。
    诚实边界：**不**校验写权限（home 台）——那是图的门（单一源），图在 apply 独立 re-assert。
    """

    if not isinstance(intent, CommandIntent):
        raise CommandValidationError("validate_intent 只接受 CommandIntent")
    # 命门 #2 + #6：actor 四类 + 来源面相容，单点把关（防篡改后绕 Provenance 构造期门·通道入口独立 re-assert）。
    # actor∈四类由 assert_actor_surface_coherent 首检兜住（非四类 → ProvenanceError）——不另设冗余分支，让
    # 「actor 四类 MUT」由本调用单点可证伪；图 CanonicalCommand 仍第三层独立 re-assert actor（分层防御·不双源）。
    assert_actor_surface_coherent(intent.provenance.actor, intent.provenance.surface)
    # 命门 #3：目标台合法。
    if intent.target_desk not in DESKS:
        raise CommandValidationError(
            f"命令缺/错目标台：{intent.target_desk!r} ∉ {sorted(DESKS)}（GOAL §2）"
        )
    if intent.action not in ACTIONS:
        raise CommandValidationError(
            f"未知语义动作：{intent.action!r} ∉ {sorted(ACTIONS)}（GOAL §2 intent/canvas action）"
        )
    # 命门 #5：逐命令类型 payload schema。
    _validate_payload_schema(intent)


def _validate_payload_schema(intent: CommandIntent) -> None:
    """命门 #5：每语义动作的 args 载荷形状校验（缺真 QRO / 缺 src·dst / 缺 handoff 必填 → 拒）。"""

    args = intent.args
    action = intent.action
    if action in (ACTION_CREATE_ASSET, ACTION_UPDATE_ASSET):
        qro = args.get("qro")
        if not isinstance(qro, QualifiedResearchObject):
            raise PayloadSchemaError(
                f"{action!r} 的 args['qro'] 必须是 QualifiedResearchObject（图只收编真信封·"
                "非裸 dict / duck 对象·GOAL §1/§2）"
            )
    elif action == ACTION_LINK_ASSETS:
        src = args.get("src")
        dst = args.get("dst")
        edge_type = args.get("edge_type")
        if not isinstance(src, str) or not src:
            raise PayloadSchemaError("link_assets 缺 args['src']（非空内容寻址节点 id）")
        if not isinstance(dst, str) or not dst:
            raise PayloadSchemaError("link_assets 缺 args['dst']（非空内容寻址节点 id）")
        if edge_type not in LINK_EDGE_TYPES:
            raise PayloadSchemaError(
                f"link_assets 的 edge_type 非法：{edge_type!r} ∉ {sorted(LINK_EDGE_TYPES)}"
                "（desk_handoff 边走 request_handoff/fulfill_handoff 动作·非 link）"
            )
    elif action == ACTION_REQUEST_HANDOFF:
        handoff = args.get("handoff")
        if isinstance(handoff, DeskHandoff):
            return  # 已是 DeskHandoff（其 __post_init__ 自校台/actor/状态）
        # 否则须够字段现建：from_desk / to_desk / requested_asset 必填。
        for key in ("from_desk", "to_desk", "requested_asset"):
            val = args.get(key)
            if not isinstance(val, str) or not val:
                raise PayloadSchemaError(
                    f"request_handoff 缺 args['{key}']（或直接传 args['handoff']=DeskHandoff）"
                )
    elif action == ACTION_FULFILL_HANDOFF:
        for key in ("handoff_id", "produced_ref"):
            val = args.get(key)
            if not isinstance(val, str) or not val:
                # produced_ref 早拦 = §2「DeskHandoff 完成后缺 produced_ref → 拒」的命令层防御纵深。
                raise PayloadSchemaError(
                    f"fulfill_handoff 缺 args['{key}']（GOAL §2：完成交接必须指向真实产出 produced_ref）"
                )
        resolved_by = args.get("resolved_by", intent.provenance.actor)
        if resolved_by not in ACTOR_CLASSES:
            raise PayloadSchemaError(
                f"fulfill_handoff 的 resolved_by 非四类 actor：{resolved_by!r}（GOAL §0）"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 语义翻译（② · GOAL §2 intent/canvas action → typed command）。
# 把语义动作翻成 research_graph.CanonicalCommand：动作→command_type、args→typed payload、
# provenance.actor→command.actor、provenance.token()→command.origin（让图账带 provenance 来源）。
# ─────────────────────────────────────────────────────────────────────────────
def translate_intent(intent: CommandIntent) -> CanonicalCommand:
    """语义动作 → 图 typed command（GOAL §2）。**不**预设已校验——内部仍走 `validate_intent`（翻译即校验）。

    返回 `research_graph.CanonicalCommand`（单一命令类型·不另造）：`command_type` 由 ACTION_TO_COMMAND 翻，
    `payload` 由 args 按类型解析，`actor` = provenance.actor，`origin` = provenance.token()。
    """

    validate_intent(intent)
    command_type = ACTION_TO_COMMAND.get(intent.action)
    if command_type is None:  # ACTIONS 已在 validate_intent 拦·防御性兜底
        raise CommandTranslationError(f"无法翻译语义动作：{intent.action!r}")
    payload = _build_payload(intent)
    return CanonicalCommand(
        command_type=command_type,
        actor=intent.provenance.actor,
        target_desk=intent.target_desk,
        payload=payload,
        origin=intent.provenance.token(),
    )


def _build_payload(intent: CommandIntent) -> dict[str, Any]:
    """把语义动作的 args 解析成图命令的 typed payload（解析/翻译·已过 schema 校验）。"""

    args = intent.args
    action = intent.action
    if action in (ACTION_CREATE_ASSET, ACTION_UPDATE_ASSET):
        return {"qro": args["qro"]}
    if action == ACTION_LINK_ASSETS:
        return {"src": args["src"], "dst": args["dst"], "edge_type": args["edge_type"]}
    if action == ACTION_REQUEST_HANDOFF:
        handoff = args.get("handoff")
        if not isinstance(handoff, DeskHandoff):
            # 现建 DeskHandoff（created_by 缺省取 provenance.actor·四类·满足图 DeskHandoff 门）。
            handoff = DeskHandoff(
                from_desk=args["from_desk"],
                to_desk=args["to_desk"],
                requested_asset=args["requested_asset"],
                reason=str(args.get("reason", "")),
                blocking_dependency=str(args.get("blocking_dependency", "")),
                created_by=str(args.get("created_by", intent.provenance.actor)),
            )
        return {"handoff": handoff}
    if action == ACTION_FULFILL_HANDOFF:
        return {
            "handoff_id": args["handoff_id"],
            "produced_ref": args["produced_ref"],
            "resolved_by": str(args.get("resolved_by", intent.provenance.actor)),
            "evidence_refs": tuple(args.get("evidence_refs", ()) or ()),
        }
    raise CommandTranslationError(f"无法翻译语义动作：{action!r}")  # 防御性兜底


# ─────────────────────────────────────────────────────────────────────────────
# 内容寻址完整性（命门 #4 · GOAL §0/§2「缺内容寻址 id → 拒」）。
# 复用图命令**自身**的单一源派生（构造同字段孪生·比对 command_id），抓被伪造/篡改的 command_id。
# ─────────────────────────────────────────────────────────────────────────────
def assert_content_addressed(command: CanonicalCommand) -> None:
    """命门 #4：命令必须带**真内容寻址** command_id，否则 ContentAddressViolation（GOAL §0/§2）。

    `command_id` 缺 / 前缀错 / 长度错 → 拒；或被伪造（用单一源 content_hash 经图命令自身派生重算 ≠ 原值）→ 拒。
    重算走 `research_graph.CanonicalCommand` 自身的派生（同字段构孪生·不另写一套哈希），故不引入第二源。
    """

    cid = command.command_id
    if not cid or not isinstance(cid, str) or not cid.startswith("cmd_"):
        raise ContentAddressViolation(
            f"命令缺/错内容寻址 id：command_id={cid!r}（须 cmd_+content_hash·GOAL §0/§2）"
        )
    if len(cid) != len("cmd_") + 16:  # 全库 16 位哈希不变量（lineage.ids.HASH_LEN）
        raise ContentAddressViolation(
            f"命令 id 长度非内容寻址族：{cid!r}（应 cmd_ + 16 位·单一源 ids.HASH_LEN）"
        )
    # 用图命令自身的单一源派生重算（同字段孪生·command_id 缺省自派生）——比对抓伪造/篡改。
    twin = CanonicalCommand(
        command_type=command.command_type,
        actor=command.actor,
        target_desk=command.target_desk,
        payload=command.payload,
        origin=command.origin,
    )
    if twin.command_id != cid:
        raise ContentAddressViolation(
            f"command_id 非内容寻址（伪造/篡改）：声称 {cid!r} ≠ 单一源重算 {twin.command_id!r}"
            "（GOAL §0/§2 内容寻址·命令不可手刻 id）"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 命令账（④ · GOAL §2「同一 audit/lineage」）——append-only·一本账·user 手动与 agent 同链。
# provenance 区分（actor/surface 可查），但**不分账**：命门 #6 的同链兑现。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LedgerEntry:
    """命令账一条（GOAL §2 audit/lineage）——命令身份 + 落图影响 + provenance（含 actor/surface 冗余以便查）。"""

    seq: int
    command_id: str
    command_type: str
    target_desk: str
    actor: str
    surface: str
    provenance: Provenance
    affected_id: str


class CommandLedger:
    """append-only 命令账（GOAL §2）——所有经通道的命令同进**一本账**（user 手动 + agent 同链）。

    单一审计源：`record` 是唯一写口；查询按 actor / surface 切片（provenance 区分），但底层只有一条链
    （命门 #6：两源命令同进一本账·不分账）。`command_ids()` 供通道唯一对账（命门 #1）。
    """

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def record(
        self, command: CanonicalCommand, provenance: Provenance, affected_id: str
    ) -> LedgerEntry:
        entry = LedgerEntry(
            seq=len(self._entries),
            command_id=command.command_id,
            command_type=command.command_type,
            target_desk=command.target_desk,
            actor=provenance.actor,
            surface=provenance.surface,
            provenance=provenance,
            affected_id=affected_id,
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def entries_by_actor(self, actor: str) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self._entries if e.actor == actor)

    def entries_by_surface(self, surface: str) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self._entries if e.surface == surface)

    def command_ids(self) -> frozenset[str]:
        return frozenset(e.command_id for e in self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# ─────────────────────────────────────────────────────────────────────────────
# 命令回执（submit 返回）——落图结果的 lineage 凭证（命令身份 + 影响 + provenance）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CommandReceipt:
    """一次 submit 的回执（GOAL §2 lineage）——命令身份 + 落图影响 id + provenance + 图返回结果。"""

    command_id: str
    command_type: str
    target_desk: str
    provenance: Provenance
    affected_id: str
    result: Any


def _affected_id(result: Any) -> str:
    """落图结果 → 受影响元素的内容寻址 id（节点/边/交接·供回执与账记录）。"""

    if isinstance(result, GraphNode):
        return result.node_id
    if isinstance(result, GraphEdge):
        return result.edge_id
    if isinstance(result, DeskHandoff):
        return result.handoff_id
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# CommandBus（① · GOAL §2「写 Research Graph 唯一通道·user 手动 + agent 同源」）。
# 唯一公共写口 = submit(intent)；持私有图 + 私有命令账；assert_single_channel 是通道唯一的可证伪探针。
# ─────────────────────────────────────────────────────────────────────────────
class CommandBus:
    """CanonicalCommand 全栈通道（GOAL §2）——写 Research Graph 的唯一治理门。

    `submit(intent)` 是**唯一公共写口**：校验（③）→ 翻译（②）→ 内容寻址核验（命门 #4）→ 落图（图 apply）→
    记账（④·同一本账）→ 回执。`_graph`/`_ledger` 私有，无第二条公共写路径——这是「user 手动 + agent 同源
    进同一门」的结构兑现。`assert_single_channel` 对账图命令账 vs 通道账，抓绕通道直写图（命门 #1·可证伪探针）。

    诚实：Python 不能真隐藏 `_graph`；通道唯一 = 结构上 submit 是唯一公共写口 + 对账探针（同 research_graph
    以 `assert_commanded` 探针守裸写 `_nodes` 的范式）。绕过仍可能，但探针使「是否都走了前门」可证伪。
    """

    def __init__(self, graph: ResearchGraph | None = None) -> None:
        self._graph: ResearchGraph = graph if graph is not None else ResearchGraph()
        self._ledger = CommandLedger()

    # ── 唯一公共写口 ────────────────────────────────────────────────────────
    def submit(self, intent: CommandIntent) -> CommandReceipt:
        """写 Research Graph 的唯一公共入口（GOAL §2 canonical command 全栈通道）。

        顺序：全栈校验 → 语义翻译 → 内容寻址核验 → 图 apply（图独立 re-assert 写权限/准入/真相源）→
        落同一本命令账（成功落图后才记账·与图命令账同步）→ 回执。任一步失败即抛、绝不静默落图或记账。
        """

        validate_intent(intent)  # ③ 全栈校验（actor 四类 / 目标台 / payload schema / provenance）
        command = translate_intent(intent)  # ② 语义翻译 → typed command
        assert_content_addressed(command)  # 命门 #4：内容寻址完整性
        result = self._graph.apply(command)  # ① 落图（图门独立 re-assert·分层防御）
        affected = _affected_id(result)
        self._ledger.record(command, intent.provenance, affected)  # ④ 同一本账（user/agent 同链）
        return CommandReceipt(
            command_id=command.command_id,
            command_type=command.command_type,
            target_desk=command.target_desk,
            provenance=intent.provenance,
            affected_id=affected,
            result=result,
        )

    # ── 通道唯一对账（命门 #1·可证伪探针）────────────────────────────────────
    def assert_single_channel(self) -> None:
        """命门 #1：图里每条命令都必须经本通道（bus）铸入，否则 ChannelBypassViolation（GOAL §2）。

        正路径下 submit 恒「落图 + 记账」成对，故图命令账 ⊆ 通道账，此门恒过；它是**绕通道探针**——
        若有人绕 submit 直接 `graph.apply(...)`（维护通道外写 / user 手动改动未落 canonical command 通道）→
        该命令 id ∉ 通道账 → 拒。是 §2「user 手动改动未落 canonical command → 拒」的通道层兑现。
        """

        minted = self._ledger.command_ids()
        for command in self._graph.command_log():
            if command.command_id not in minted:
                raise ChannelBypassViolation(
                    f"图命令 {command.command_id!r}（type={command.command_type!r}）未经命令通道铸入"
                    "——绕 canonical command 通道直写图（GOAL §2：user 手动改动未落 canonical command → 拒）"
                )

    # ── 只读访问器（读·不开第二写口）────────────────────────────────────────
    def ledger(self) -> CommandLedger:
        return self._ledger

    def project(self, desk: str, *, claims_institutional: bool = False):
        """各台 typed projection（读·透传图·§2 每台 Canvas = 同一图的 typed projection）。"""

        return self._graph.project(desk, claims_institutional=claims_institutional)

    def node_count(self) -> int:
        return len(self._graph)

    def get_node(self, node_id: str):
        return self._graph.get_node(node_id)


# 便捷构造器（语义糖·非门）：各台面快速构建 provenance / intent，门一律在上面的校验里。
def manual_provenance(surface: str, *, actor_id: str = "", session_ref: str = "") -> Provenance:
    """user 手动来源（§2 人手面 canvas/form/ide/api）——actor 固定 user_manual。"""

    return Provenance(
        actor=ACTOR_USER_MANUAL, surface=surface, actor_id=actor_id, session_ref=session_ref
    )


def agent_provenance(
    *, surface: str = ORIGIN_AGENT_RUNTIME, actor_id: str = "", session_ref: str = ""
) -> Provenance:
    """agent 自治来源（§0 agent 动作·缺省 agent_runtime 面）。"""

    return Provenance(
        actor=ACTOR_AGENT, surface=surface, actor_id=actor_id, session_ref=session_ref
    )


__all__ = [
    # 来源面 ④
    "ORIGIN_CANVAS",
    "ORIGIN_FORM",
    "ORIGIN_IDE",
    "ORIGIN_API",
    "ORIGIN_AGENT_RUNTIME",
    "ORIGIN_SCHEDULER",
    "ORIGIN_SURFACES",
    "HUMAN_MANUAL_SURFACES",
    "ACTOR_SURFACE_ALLOWED",
    # actor（复用单一源·此处便捷常量别名）
    "ACTOR_USER_MANUAL",
    "ACTOR_AGENT",
    "ACTOR_USER_CONFIRMED_AGENT",
    "ACTOR_SCHEDULED_AGENT",
    # 语义动作 ②
    "ACTION_CREATE_ASSET",
    "ACTION_UPDATE_ASSET",
    "ACTION_LINK_ASSETS",
    "ACTION_REQUEST_HANDOFF",
    "ACTION_FULFILL_HANDOFF",
    "ACTIONS",
    "ACTION_TO_COMMAND",
    "LINK_EDGE_TYPES",
    # 数据类
    "Provenance",
    "CommandIntent",
    "LedgerEntry",
    "CommandLedger",
    "CommandReceipt",
    "CommandBus",
    # 门 / 校验 / 翻译
    "assert_actor_surface_coherent",
    "validate_intent",
    "translate_intent",
    "assert_content_addressed",
    # 便捷构造器
    "manual_provenance",
    "agent_provenance",
    # 异常族
    "CommandError",
    "CommandValidationError",
    "ProvenanceError",
    "PayloadSchemaError",
    "CommandTranslationError",
    "ContentAddressViolation",
    "ChannelBypassViolation",
]
