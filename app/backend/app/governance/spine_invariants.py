"""治理脊柱 · §8 硬不变量统一核查门（GOAL §8 治理脊柱 · 收编已建 enforcement 聚合）。

GOAL §8「治理脊柱」列了一串硬不变量；本卡聚合其中**七条**（agent / canvas / secret / event 一脉）
成一道**可证伪的统一核查门**：把分散在各已建件里的 §8 判定收编只读、聚合成一个总裁定，
**任一硬不变量违反 → 拒**。

七条硬不变量 → 收编的已建 enforcement（**绝不重造**·诚实标已 enforce vs 本门聚合补的缺口）：

  ① CanvasMutation ⇒ canonical versioned command
     收编 `command/canonical_command.py`（A-CMD）：`CommandBus.assert_single_channel` ——图里每条
     canvas mutation 都必经命令通道铸成 canonical command（content-addressed id + append-only 账=「versioned」
     的落地形态：内容寻址身份 + 账内单调序，非另立 semver）。本门调其对账探针；**全权已 enforce**。
  ② AgentAction ⇒ scoped permission + tool record + no secret exposure
     收编 `agent/orchestrator/governance.py`（`GovernedToolDispatcher`）：越权 / 绕 DAG 的派发留
     `ToolViolation`、每次派发落 `ToolCallRecord`——scoped permission + tool record **全权已 enforce**。
     `no secret exposure` 那一面是**本门聚合补的真缺口**：派发闸只记工具名、**不扫 arg 值**（事件投影也
     只投 args_keys 不投值），故 action 暴露面（工具入参 / 结果）夹带在册明文 secret 现有链路无人扫——
     本门用**单一源** `llm.call_record.scan_messages_for_secret` 扫之（不另造扫描器）。
  ③ AgentPlan ⇒ todo + dependencies + acceptance gates
     收编 `agent/orchestrator/plan.py`：`AgentPlan.validate / is_ready`——缺三者（或悬空依赖）→ 维持
     draft（不晋升为可执行）。**全权已 enforce**；本门调其判定。
  ④ AgentCodeChange ⇒ diff + test/validation result + rollback point
     收编 `agent/orchestrator/plan.py`：`AgentCodeChange` 构造门——缺三者 → `AgentCodeChangeError`。
     **全权已 enforce**；本门以原始字段过其构造门作可证伪边界。
  ⑤ RoleAgentAction ⇒ visible workflow event + audit record
     收编 `agent/orchestrator/events.py`（`EventProjector`·24 可见事件 + `assert_event_clean`）——可见
     事件面 **全权已 enforce**（白名单 + 投影即扫 secret / 禁 provider 思维链）。「可见事件 ∧ audit
     record **同时在**」的联合判定是**本门聚合的 join**（单一已建件各管一半·本门把两半并起来核）。
  ⑥ SecretPlaintext ⇒ Settings / Secrets only
     收编 `llm/call_record.py`（`assert_no_plaintext_secret` / `scan_messages_for_secret`）+
     `security/keystore.py`（`SecureKeystore` 单一门面·secret 永不落 YAML/DB/日志）：任一在册明文
     secret 出现在序列化 / 导出 / 日志面 → 拒。**全权已 enforce**；本门调其扫描门。
  ⑦ AgentDataAccess ⇒ SecretRef only
     收编 `llm/credential_pool.py`（`SecretRef`）：数据访问只持 `secretref://provider/name` 受控引用、
     **绝非明文 key**。本门按单一源 `SecretRef` 的 scheme 校验引用形态（结构层·**已 enforce**），
     并扫随行暴露面防明文 key 偷渡。

诚实边界（本门**不**做什么）：
- 本门是**聚合核查**——按调用方提供的 evidence 判「这些 §8 硬不变量是否被违反」。它**不**自己拦截
  每个动作（拦截是各已建件的本分·本门收编它们的判定），**不重造**已建 enforcement，**不**为已
  enforce 的不变量「再证明一遍」。它管的是「把七条聚成一道可证伪总门 + 补 AgentAction 暴露面那条真缺口」。
- secret 扫描沿用 call_record 的「在册明文逐字匹配」诚实口径——抓「真把某条在册 secret 写进了暴露
  面」，**不**号称识别任意未在册高熵串（那是另一层启发式，不在本门诚实承诺内）。
- ⑦ 只校验引用**形态**是 SecretRef（结构相容），**不**核验该引用真能解出 keystore 记录（那是
  keystore 的活·未验证残余）。
- 范围：本门只管 §8 这七条**治理脊柱**硬不变量。§8 里**数学一脉**（TheoryClaim⇒MathematicalArtifact /
  TheoryImplementationBinding⇒ConsistencyCheck / ImplementationClaim⇒consistency_verdict）由
  `lineage/spine_gate.py` 另门 enforce；**approver≠creator** 由 `approval/gate.py` enforce；
  **LLMCallRecord 必填 / AgentLLMCall⇒Gateway / Verifier 独立性**由 `llm/gateway.py` + `call_record.py`
  enforce——本门**不掺手、不重造**（无新公式 → 不造 MathematicalArtifact）。
- 裁决只说「证据充分 / 证据不足 / 适用域 / 未验证残余 / 失败原因 / 下一步验证缺口」（GOAL §8 裁决语言
  + RULES §3）；拒绝口径**绝不**出现「可信 / 安全 / 保证」等越权正向断言（`_assert_no_banned_terms` 自检兜底）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..command.canonical_command import ChannelBypassViolation, CommandError
from ..llm.call_record import (
    LLMCallRecord,
    SecretLeakError,
    assert_no_plaintext_secret,
    scan_messages_for_secret,
)
from ..llm.credential_pool import SecretRef

# ─────────────────────────────────────────────────────────────────────────────
# 七条硬不变量 id（GOAL §8 治理脊柱·顺序照 GOAL 原文）。
# ─────────────────────────────────────────────────────────────────────────────
INV_CANVAS_MUTATION = "CanvasMutation⇒canonical_versioned_command"
INV_AGENT_ACTION = "AgentAction⇒scoped_permission+tool_record+no_secret"
INV_AGENT_PLAN = "AgentPlan⇒todo+dependencies+acceptance_gates"
INV_AGENT_CODE_CHANGE = "AgentCodeChange⇒diff+test+rollback_point"
INV_ROLE_AGENT_ACTION = "RoleAgentAction⇒visible_event+audit_record"
INV_SECRET_PLAINTEXT = "SecretPlaintext⇒Settings_only"
INV_AGENT_DATA_ACCESS = "AgentDataAccess⇒SecretRef_only"

CLAUSES: tuple[str, ...] = (
    INV_CANVAS_MUTATION,
    INV_AGENT_ACTION,
    INV_AGENT_PLAN,
    INV_AGENT_CODE_CHANGE,
    INV_ROLE_AGENT_ACTION,
    INV_SECRET_PLAINTEXT,
    INV_AGENT_DATA_ACCESS,
)

# ─────────────────────────────────────────────────────────────────────────────
# 收编登记（诚实层）：每条硬不变量被哪已建件 enforce + 是「全权收编」还是「本门聚合补」。
# 这张表本身就是卡要的交付物——「诚实标已 enforce vs 本门补缺口·不冒充新建已有的」机器可读化。
# ─────────────────────────────────────────────────────────────────────────────
STATUS_DELEGATED = "delegated"          # 已建件全权 enforce·本门只调用其判定（收编只读）
STATUS_AGGREGATION = "aggregation"      # 本门在聚合点补的判定（已建件在该面未做）
STATUS_MIXED = "mixed"                  # 一半收编已建·一半本门聚合补


@dataclass(frozen=True)
class EnforcementBinding:
    """一条硬不变量 → 收编的已建 enforcement + 诚实状态标注。"""

    clause: str
    enforced_by: str
    status: str
    note: str


ENFORCEMENT_BINDINGS: dict[str, EnforcementBinding] = {
    INV_CANVAS_MUTATION: EnforcementBinding(
        clause=INV_CANVAS_MUTATION,
        enforced_by="command.canonical_command.CommandBus.assert_single_channel",
        status=STATUS_DELEGATED,
        note=(
            "A-CMD 已建·收编只读：图里每条 canvas mutation 必经命令通道铸成 canonical command"
            "（content-addressed id + append-only 命令账=「versioned」落地）。本门调其对账探针，绕通道直写图 → 拒。"
        ),
    ),
    INV_AGENT_ACTION: EnforcementBinding(
        clause=INV_AGENT_ACTION,
        enforced_by=(
            "agent.orchestrator.governance.GovernedToolDispatcher（scoped perm + ToolCallRecord·delegated）"
            " + llm.call_record.scan_messages_for_secret（暴露面 no-secret·aggregation）"
        ),
        status=STATUS_MIXED,
        note=(
            "scoped permission + tool record 由派发闸全权 enforce（越权/绕 DAG 留 ToolViolation·每派发落 record）；"
            "no-secret-exposure 是本门补的**真缺口**——派发闸只记工具名、不扫 arg 值，本门用单一源扫描器扫 action 暴露面。"
        ),
    ),
    INV_AGENT_PLAN: EnforcementBinding(
        clause=INV_AGENT_PLAN,
        enforced_by="agent.orchestrator.plan.AgentPlan.validate / is_ready",
        status=STATUS_DELEGATED,
        note="已建·收编只读：缺 todo/dependencies/acceptance_gates 或悬空依赖 → 维持 draft（不晋升）。本门调其判定。",
    ),
    INV_AGENT_CODE_CHANGE: EnforcementBinding(
        clause=INV_AGENT_CODE_CHANGE,
        enforced_by="agent.orchestrator.plan.AgentCodeChange.__post_init__",
        status=STATUS_DELEGATED,
        note="已建·收编只读：缺 diff/test_result/rollback_point → AgentCodeChangeError。本门以原始字段过其构造门作可证伪边界。",
    ),
    INV_ROLE_AGENT_ACTION: EnforcementBinding(
        clause=INV_ROLE_AGENT_ACTION,
        enforced_by=(
            "agent.orchestrator.events.EventProjector（24 可见事件 + assert_event_clean·delegated）"
            " + 本门 join（可见事件 ∧ audit record 同在·aggregation）"
        ),
        status=STATUS_MIXED,
        note=(
            "可见事件面由 EventProjector 全权 enforce（白名单 + 投影即扫 secret/禁 provider 思维链）；"
            "本门聚合补「可见 ∧ 留痕**双在**」的联合判定（单一已建件各管一半·本门把两半并起来核）。"
        ),
    ),
    INV_SECRET_PLAINTEXT: EnforcementBinding(
        clause=INV_SECRET_PLAINTEXT,
        enforced_by=(
            "llm.call_record.assert_no_plaintext_secret / scan_messages_for_secret"
            " + security.keystore.SecureKeystore"
        ),
        status=STATUS_DELEGATED,
        note="已建·收编只读：在册明文 secret 出现在序列化/导出/日志面 → 拒；secret 只在 SecureKeystore（永不落 YAML/DB/日志）。",
    ),
    INV_AGENT_DATA_ACCESS: EnforcementBinding(
        clause=INV_AGENT_DATA_ACCESS,
        enforced_by="llm.credential_pool.SecretRef（secretref://provider/name 受控引用）",
        status=STATUS_DELEGATED,
        note=(
            "已建·收编只读：数据访问只持 SecretRef 引用·绝非明文 key。本门按单一源 SecretRef 的 scheme 校验引用形态"
            "（结构层）+ 扫随行暴露面防明文 key 偷渡；不核验引用真能解出 keystore 记录（未验证残余）。"
        ),
    ),
}

# import 期自检（fail-fast·非 assert·-O 不剥）：收编登记必须恰好覆盖七条硬不变量（防漏标/重标·防漂）。
_binding_keys = frozenset(ENFORCEMENT_BINDINGS)
if _binding_keys != frozenset(CLAUSES):
    raise RuntimeError(
        "ENFORCEMENT_BINDINGS 必须恰好覆盖 GOAL §8 治理脊柱七条硬不变量："
        f"缺 {sorted(frozenset(CLAUSES) - _binding_keys)}、多 {sorted(_binding_keys - frozenset(CLAUSES))}"
    )
if len(CLAUSES) != 7 or len(frozenset(CLAUSES)) != 7:
    raise RuntimeError(f"CLAUSES 必须恰好七条硬不变量（实得 {len(CLAUSES)} / unique {len(frozenset(CLAUSES))}）")

# 拒绝口径里绝不能出现的越权正向断言（RULES §3·防「不给小白假绿灯」原则反噬自身）。
# 注：「安全」单字不进黑名单（会误伤「安全后端 / 安全边界」等正当用词）；只禁实打实的越权断言短语。
BANNED_IN_REJECTION: tuple[str, ...] = ("可信", "保证", "证据充分", "已验证一致", "绝对安全")

DISCLOSURE = (
    "治理脊柱核查门是**聚合判定**：按提供的 evidence 收编各已建 enforcement 的裁定，判 §8 七条硬不变量"
    "是否被违反；它不自己拦截每个动作、不重造已建门、不为已 enforce 的不变量再证明一遍。secret 扫描沿用"
    "「在册明文逐字匹配」口径，不识别任意未在册高熵串。裁决只陈述证据状态，不作「可信/安全/保证」越权断言。"
)


# ─────────────────────────────────────────────────────────────────────────────
# 裁定数据类（frozen·参 lineage/spine_gate.SpineDecision 范式）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ClauseResult:
    """单条硬不变量的核查结果。

    `checked=False` = 本次未提供该 clause 的 evidence（**未验证残余**·不误伤、不算违反）。
    `enforced_by` / `enforcement_status` 透传收编登记——裁定里随身带「这条谁 enforce / 是否本门补缺口」。
    """

    clause: str
    passed: bool
    checked: bool
    enforced_by: str
    enforcement_status: str
    violation: str = ""
    matched: str = ""

    @classmethod
    def skipped(cls, clause: str) -> "ClauseResult":
        b = ENFORCEMENT_BINDINGS[clause]
        return cls(
            clause=clause, passed=True, checked=False,
            enforced_by=b.enforced_by, enforcement_status=b.status,
            violation="", matched="未提供 evidence·本次未核查（未验证残余）",
        )

    @classmethod
    def _decide(cls, clause: str, *, passed: bool, violation: str = "", matched: str = "") -> "ClauseResult":
        b = ENFORCEMENT_BINDINGS[clause]
        return cls(
            clause=clause, passed=passed, checked=True,
            enforced_by=b.enforced_by, enforcement_status=b.status,
            violation="" if passed else violation, matched=matched if passed else "",
        )


@dataclass(frozen=True)
class SpineVerdict:
    """治理脊柱统一核查裁定。

    `allowed` = 所**核查**的硬不变量无一被违反（跳过的不算违反·但裁决文如实点名「未核查」）。
    任一被核查不变量违反 → `allowed=False`、`violations` 非空。
    """

    allowed: bool
    clauses: tuple[ClauseResult, ...]
    violations: tuple[str, ...]
    checked_clauses: tuple[str, ...]
    skipped_clauses: tuple[str, ...]
    verdict_text: str
    disclosure: str = DISCLOSURE

    def clause(self, clause_id: str) -> ClauseResult | None:
        for c in self.clauses:
            if c.clause == clause_id:
                return c
        return None


class GovernanceSpineViolation(RuntimeError):
    """`assert_allowed` 下任一被核查硬不变量被违反 → 抛（fail-closed 调用方用）。"""


# ─────────────────────────────────────────────────────────────────────────────
# 暴露面序列化（secret 扫描用）——沿用 events._serialize 同款 json 口径，不另造规范化。
# ─────────────────────────────────────────────────────────────────────────────
def _surface_text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return str(obj)


# ─────────────────────────────────────────────────────────────────────────────
# 七条 clause 的纯核查函数（各收编一/多个已建件·单点可独测·种坏门必抓）。
# ─────────────────────────────────────────────────────────────────────────────
def check_canvas_mutation(command_bus: Any) -> ClauseResult:
    """① CanvasMutation ⇒ canonical versioned command（收编 A-CMD `CommandBus.assert_single_channel`）。

    `command_bus` 须是 `command.canonical_command.CommandBus`（或同接口·duck）：本门调其对账探针——
    图里每条命令都必经命令通道铸入（canonical command·内容寻址·入 append-only 账），否则 → 拒。
    种坏门必抓：绕 bus 直接 `graph.apply(...)`（canvas mutation 未落 canonical command）→ 探针抓 → 本门判违反。
    """

    try:
        command_bus.assert_single_channel()
    except ChannelBypassViolation as exc:
        return ClauseResult._decide(
            INV_CANVAS_MUTATION, passed=False,
            violation=f"CanvasMutation 未落 canonical versioned command（绕命令通道直写图）→ 拒：{exc}",
        )
    except CommandError as exc:  # 通道层其他不变量（内容寻址/翻译等）破 → 同判违反（收编其拒绝）
        return ClauseResult._decide(
            INV_CANVAS_MUTATION, passed=False,
            violation=f"canonical command 通道层不变量被违反 → 拒：{exc}",
        )
    return ClauseResult._decide(
        INV_CANVAS_MUTATION, passed=True,
        matched="图命令账 ⊆ 命令通道账：每条 canvas mutation 都经 canonical command 铸入（A-CMD 对账探针过）",
    )


def check_agent_action(
    *,
    dispatcher: Any,
    node_id: str,
    exposed_payload: Any = None,
    secret_values: Sequence[str] = (),
) -> ClauseResult:
    """② AgentAction ⇒ scoped permission + tool record + no secret exposure。

    收编 `GovernedToolDispatcher`（scoped perm + tool record·delegated）+ 本门补暴露面 no-secret（aggregation）：
    - scoped permission：该节点有任一 `ToolViolation`（越权 / 绕 DAG）→ 拒（派发闸已判·本门收编其 violation 簿记）。
    - tool record：每次受治理派发由派发闸落 `ToolCallRecord`（结构保证·留痕面由 ⑤ RoleAgentAction 审计）。
    - no secret exposure：`exposed_payload`（工具入参 / 结果）夹带在册明文 secret → 拒（**本门补的真缺口**：
      派发闸只记工具名不扫 arg 值，本门用单一源 `scan_messages_for_secret` 扫之）。

    种坏门必抓：① 节点派发越权工具（留 violation）→ 本门判违反；② 暴露面塞在册明文 secret → 本门判违反。
    `dispatcher` 须保留其 violation 簿记（**勿在核查前 drain** 该节点）。
    """

    node_violations = [v for v in dispatcher.violations() if getattr(v, "node_id", "") == node_id]
    if node_violations:
        kinds = sorted({getattr(v, "kind", "?") for v in node_violations})
        reasons = "; ".join(getattr(v, "reason", "") for v in node_violations)
        return ClauseResult._decide(
            INV_AGENT_ACTION, passed=False,
            violation=(
                f"AgentAction 在节点 {node_id!r} 检出 {len(node_violations)} 次越界工具派发"
                f"（scoped permission 破·{kinds}）→ 拒：{reasons}"
            ),
        )
    if exposed_payload is not None and secret_values:
        hit = scan_messages_for_secret(_surface_text(exposed_payload), list(secret_values))
        if hit is not None:
            return ClauseResult._decide(
                INV_AGENT_ACTION, passed=False,
                violation=(
                    f"AgentAction 暴露面（工具入参/结果）夹带在册明文 secret（len={len(hit)}）→ 拒"
                    "（本门聚合补缺口：派发闸不扫 arg 值）。绝不回显 secret 本身。"
                ),
            )
    n_records = len(dispatcher.records_for(node_id))
    return ClauseResult._decide(
        INV_AGENT_ACTION, passed=True,
        matched=(
            f"节点 {node_id!r} scoped permission 无破（0 violation）·tool record={n_records} 条（派发闸落账）"
            "·暴露面无在册明文 secret"
        ),
    )


def check_agent_plan(plan: AgentPlan) -> ClauseResult:
    """③ AgentPlan ⇒ todo + dependencies + acceptance gates（收编 `AgentPlan.validate / is_ready`）。

    缺三者（或悬空依赖）→ plan 维持 draft（不晋升为可执行）→ 本门判违反。
    种坏门必抓：plan 缺 acceptance_gates / 缺 dependencies / 缺 todo → 本门判违反。
    """

    plan.validate()
    if not plan.is_ready:
        return ClauseResult._decide(
            INV_AGENT_PLAN, passed=False,
            violation=f"AgentPlan 未达晋升前提（维持 draft）→ 拒：{plan.draft_reason}",
        )
    return ClauseResult._decide(
        INV_AGENT_PLAN, passed=True,
        matched=f"AgentPlan ready：todo×{len(plan.todos)} + dependencies + acceptance_gates×{len(plan.acceptance_gates)} 齐·无悬空依赖",
    )


def check_agent_code_change(
    *,
    path: str = "",
    diff: str,
    test_result: str,
    rollback_point: str,
    claims_theory_backed: bool = False,
    theory_implementation_binding: str = "",
) -> ClauseResult:
    """④ AgentCodeChange ⇒ diff + test/validation result + rollback point（收编 `AgentCodeChange` 构造门）。

    以原始字段过 `AgentCodeChange.__post_init__`——缺三者（或声称按理论实现却缺 TIB）→ `AgentCodeChangeError`
    → 本门判违反。种坏门必抓：把 rollback_point / test_result / diff 任一置空 → 本门判违反。
    """

    from ..agent.orchestrator.plan import AgentCodeChange, AgentCodeChangeError

    try:
        AgentCodeChange(
            path=path, diff=diff, test_result=test_result, rollback_point=rollback_point,
            claims_theory_backed=claims_theory_backed,
            theory_implementation_binding=theory_implementation_binding,
        )
    except AgentCodeChangeError as exc:
        return ClauseResult._decide(
            INV_AGENT_CODE_CHANGE, passed=False,
            violation=f"AgentCodeChange 缺 diff/test/rollback（或声称按理论实现却缺 TIB）→ 拒：{exc}",
        )
    return ClauseResult._decide(
        INV_AGENT_CODE_CHANGE, passed=True,
        matched="AgentCodeChange 带 diff + test_result + rollback_point（过构造门）",
    )


def check_role_agent_action(
    *,
    events: Sequence[Any],
    role: str,
    node_id: str = "",
    audit_records: Sequence[Any] = (),
) -> ClauseResult:
    """⑤ RoleAgentAction ⇒ visible workflow event + audit record。

    收编 `EventProjector` 产的可见事件（投影即过 `assert_event_clean`·delegated）+ 本门 join（aggregation）：
    一次 role agent 动作须**同时**有 (a) ≥1 条投影到 user 的可见 `WorkflowEvent`（按 role / node 命中）、
    (b) ≥1 条 audit record（如 `ToolCallRecord` / CommandLedger entry）。任一缺 → 拒。

    种坏门必抓：① role 动作无任何可见事件（投影黑箱）→ 拒；② 有可见事件但无 audit record（不可审计）→ 拒。
    """

    visible = [
        e for e in events
        if getattr(e, "role", "") == role and (not node_id or getattr(e, "node_id", "") == node_id)
    ]
    if not visible:
        return ClauseResult._decide(
            INV_ROLE_AGENT_ACTION, passed=False,
            violation=(
                f"RoleAgentAction（role={role!r} node={node_id!r}）无任何投影到 user 的可见 workflow event"
                "（执行黑箱·违 §8 可见性）→ 拒"
            ),
        )
    if not list(audit_records):
        return ClauseResult._decide(
            INV_ROLE_AGENT_ACTION, passed=False,
            violation=(
                f"RoleAgentAction（role={role!r} node={node_id!r}）有可见事件但无 audit record"
                "（不可审计·违 §8 audit 留痕）→ 拒"
            ),
        )
    return ClauseResult._decide(
        INV_ROLE_AGENT_ACTION, passed=True,
        matched=f"role={role!r} 可见事件×{len(visible)} ∧ audit record×{len(list(audit_records))} 双在",
    )


def check_secret_plaintext(*, surface: Any, secret_values: Sequence[str]) -> ClauseResult:
    """⑥ SecretPlaintext ⇒ Settings / Secrets only（收编 call_record secret 门 + keystore 单一门面）。

    `surface` = 任一可能泄露面（`LLMCallRecord` / 导出 dict / 日志串 / 事件 data …）。在册明文 secret 出现
    在其序列化面 → 拒（= secret 漏出了 Settings/Secrets 安全后端）。`LLMCallRecord` 直接走已建
    `assert_no_plaintext_secret`；其余序列化后走单一源 `scan_messages_for_secret`。

    种坏门必抓：把在册明文 secret 塞进 surface 任一字段 → 本门判违反。绝不回显 secret 本身。
    """

    values = list(secret_values)
    if isinstance(surface, LLMCallRecord):
        try:
            assert_no_plaintext_secret(surface, values)
        except SecretLeakError as exc:
            return ClauseResult._decide(
                INV_SECRET_PLAINTEXT, passed=False,
                violation=f"SecretPlaintext 漏出 Settings/Secrets（进 LLMCallRecord 序列化面）→ 拒：{exc}",
            )
    else:
        hit = scan_messages_for_secret(_surface_text(surface), values)
        if hit is not None:
            return ClauseResult._decide(
                INV_SECRET_PLAINTEXT, passed=False,
                violation=(
                    f"SecretPlaintext 漏出 Settings/Secrets（在册明文 secret len={len(hit)} 进导出/日志/事件面）→ 拒。"
                    "绝不回显 secret 本身。"
                ),
            )
    return ClauseResult._decide(
        INV_SECRET_PLAINTEXT, passed=True,
        matched=f"暴露面无任一在册明文 secret（扫 {len(values)} 条在册值·只 SecretRef 引用面流通）",
    )


def _is_secretref(ref: Any) -> bool:
    """引用是否 `credential_pool.SecretRef` 产的 `secretref://provider/name` 形态（round-trip 对齐单一源·防自造 scheme 漂移）。"""

    if not isinstance(ref, str) or not ref.startswith("secretref://"):
        return False
    provider, sep, name = ref[len("secretref://"):].partition("/")
    if not sep or not provider or not name:
        return False
    # 用单一源 SecretRef 重算同形引用比对——绑死 credential_pool.SecretRef.ref，不另立一套 scheme。
    return SecretRef(keystore_name=name, provider=provider).ref == ref


def check_agent_data_access(
    *,
    auth_ref: Any,
    accompanying_payload: Any = None,
    secret_values: Sequence[str] = (),
) -> ClauseResult:
    """⑦ AgentDataAccess ⇒ SecretRef only（收编 `credential_pool.SecretRef` scheme）。

    数据访问携带的凭据引用必须是 `secretref://provider/name`（受控引用·绝非明文 key）；并扫随行暴露面
    防明文 key 偷渡。`auth_ref` 也可直接传一个 `SecretRef`（取其 `.ref`）。

    种坏门必抓：① auth_ref 传明文 key（非 secretref://）→ 拒；② 随行暴露面夹带在册明文 secret → 拒。
    诚实边界：只校验引用**形态**，不核验引用真能解出 keystore 记录（keystore 的活·未验证残余）。
    """

    ref = auth_ref.ref if isinstance(auth_ref, SecretRef) else auth_ref
    if not _is_secretref(ref):
        shown = "<空>" if not ref else (str(ref)[:12] + "…")  # 绝不整串回显（万一是明文 key）
        return ClauseResult._decide(
            INV_AGENT_DATA_ACCESS, passed=False,
            violation=(
                f"AgentDataAccess 的凭据引用非 SecretRef 形态（auth_ref≈{shown}·非 secretref://provider/name）"
                "→ 拒：数据访问绝不持明文 key·只 SecretRef 引用。"
            ),
        )
    if accompanying_payload is not None and secret_values:
        hit = scan_messages_for_secret(_surface_text(accompanying_payload), list(secret_values))
        if hit is not None:
            return ClauseResult._decide(
                INV_AGENT_DATA_ACCESS, passed=False,
                violation=(
                    f"AgentDataAccess 随行暴露面夹带在册明文 secret（len={len(hit)}）→ 拒（明文 key 绕 SecretRef 偷渡）。"
                    "绝不回显 secret 本身。"
                ),
            )
    return ClauseResult._decide(
        INV_AGENT_DATA_ACCESS, passed=True,
        matched=f"凭据引用为 SecretRef 形态（{ref}）·随行暴露面无在册明文 secret",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Evidence 聚合（统一门入口）——各 clause 的 evidence 容器（缺省 None = 本次不核查该条·未验证残余）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AgentActionEvidence:
    dispatcher: Any                       # GovernedToolDispatcher（保留 violation 簿记·勿先 drain 该节点）
    node_id: str
    exposed_payload: Any = None
    secret_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeChangeEvidence:
    diff: str
    test_result: str
    rollback_point: str
    path: str = ""
    claims_theory_backed: bool = False
    theory_implementation_binding: str = ""


@dataclass(frozen=True)
class RoleActionEvidence:
    events: tuple[Any, ...]               # Sequence[WorkflowEvent]
    role: str
    node_id: str = ""
    audit_records: tuple[Any, ...] = ()


@dataclass(frozen=True)
class SecretSurfaceEvidence:
    surface: Any
    secret_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataAccessEvidence:
    auth_ref: Any
    accompanying_payload: Any = None
    secret_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpineEvidence:
    """统一门一次核查的 evidence 包——每字段对应一条硬不变量（None = 本次不提供·跳过该条·未验证残余）。"""

    canvas_mutation: Any = None                         # CommandBus
    agent_action: AgentActionEvidence | None = None
    agent_plan: AgentPlan | None = None
    agent_code_change: CodeChangeEvidence | None = None
    role_agent_action: RoleActionEvidence | None = None
    secret_plaintext: SecretSurfaceEvidence | None = None
    agent_data_access: DataAccessEvidence | None = None


def _assert_no_banned_terms(reject_text: str) -> None:
    """门自检（RULES §3）：拒绝口径绝不出现越权正向断言——出现 = 我们自己打了假绿灯。"""

    for term in BANNED_IN_REJECTION:
        if term in reject_text:
            raise AssertionError(
                f"治理脊柱核查门自检失败：拒绝口径出现越权词 {term!r}（= 假绿灯反噬自身·RULES §3）"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 统一核查门。
# ─────────────────────────────────────────────────────────────────────────────
class GovernanceSpineGate:
    """§8 治理脊柱硬不变量**统一核查门**——聚合七条·任一违反 → 拒。

    `secret_values` = 在册明文 secret 缺省集（如 `credential_pool.known_secret_values()`）——各 secret
    相关 clause 的 evidence 未自带 secret_values 时回退到它（省得每次重传·同 EventProjector 范式）。
    它本身是**受控读取的明文集**，本门只逐字比对、绝不落账 / 打印 / 回显。
    """

    def __init__(self, *, secret_values: Sequence[str] = ()) -> None:
        self._secret_values = tuple(s for s in secret_values if s)

    def _secrets(self, override: Sequence[str]) -> tuple[str, ...]:
        ov = tuple(s for s in override if s)
        return ov or self._secret_values

    def evaluate(self, evidence: SpineEvidence) -> SpineVerdict:
        """按 evidence 核查七条硬不变量（提供者核查·缺省跳过）→ 统一裁定。任一被核查不变量违反 → allowed=False。"""

        results: list[ClauseResult] = []

        if evidence.canvas_mutation is not None:
            results.append(check_canvas_mutation(evidence.canvas_mutation))
        else:
            results.append(ClauseResult.skipped(INV_CANVAS_MUTATION))

        if evidence.agent_action is not None:
            ev = evidence.agent_action
            results.append(check_agent_action(
                dispatcher=ev.dispatcher, node_id=ev.node_id,
                exposed_payload=ev.exposed_payload, secret_values=self._secrets(ev.secret_values),
            ))
        else:
            results.append(ClauseResult.skipped(INV_AGENT_ACTION))

        if evidence.agent_plan is not None:
            results.append(check_agent_plan(evidence.agent_plan))
        else:
            results.append(ClauseResult.skipped(INV_AGENT_PLAN))

        if evidence.agent_code_change is not None:
            ev = evidence.agent_code_change
            results.append(check_agent_code_change(
                path=ev.path, diff=ev.diff, test_result=ev.test_result, rollback_point=ev.rollback_point,
                claims_theory_backed=ev.claims_theory_backed,
                theory_implementation_binding=ev.theory_implementation_binding,
            ))
        else:
            results.append(ClauseResult.skipped(INV_AGENT_CODE_CHANGE))

        if evidence.role_agent_action is not None:
            ev = evidence.role_agent_action
            results.append(check_role_agent_action(
                events=ev.events, role=ev.role, node_id=ev.node_id, audit_records=ev.audit_records,
            ))
        else:
            results.append(ClauseResult.skipped(INV_ROLE_AGENT_ACTION))

        if evidence.secret_plaintext is not None:
            ev = evidence.secret_plaintext
            results.append(check_secret_plaintext(
                surface=ev.surface, secret_values=self._secrets(ev.secret_values),
            ))
        else:
            results.append(ClauseResult.skipped(INV_SECRET_PLAINTEXT))

        if evidence.agent_data_access is not None:
            ev = evidence.agent_data_access
            results.append(check_agent_data_access(
                auth_ref=ev.auth_ref, accompanying_payload=ev.accompanying_payload,
                secret_values=self._secrets(ev.secret_values),
            ))
        else:
            results.append(ClauseResult.skipped(INV_AGENT_DATA_ACCESS))

        return self._finalize(tuple(results))

    def assert_allowed(self, evidence: SpineEvidence) -> SpineVerdict:
        """fail-closed 变体：任一被核查硬不变量被违反 → 抛 `GovernanceSpineViolation`。"""

        verdict = self.evaluate(evidence)
        if not verdict.allowed:
            raise GovernanceSpineViolation(verdict.verdict_text)
        return verdict

    @staticmethod
    def _finalize(results: tuple[ClauseResult, ...]) -> SpineVerdict:
        failed = [c for c in results if c.checked and not c.passed]
        checked = [c.clause for c in results if c.checked]
        skipped = [c.clause for c in results if not c.checked]
        violations = tuple(c.violation for c in failed)
        allowed = not failed

        if allowed:
            if checked:
                verdict = (
                    f"治理脊柱核查放行：核查 {len(checked)} 条硬不变量全过（证据充分=所核查不变量无违反）；"
                    f"跳过 {len(skipped)} 条（本次未提供 evidence·未验证残余）。适用域=本次提供的 evidence 面。"
                )
            else:
                verdict = (
                    "治理脊柱核查：本次未提供任何 evidence·七条全跳过（未验证残余）——非放行结论，"
                    "仅表示无可核查项。适用域=空。"
                )
        else:
            verdict = (
                f"治理脊柱核查拒绝：{len(failed)} 条硬不变量被违反 → 拒（证据不足）。"
                f"失败原因：{'；'.join(violations)}。"
                f"下一步验证缺口：补齐被违反不变量对应的已建 enforcement 后重核；"
                f"另有 {len(skipped)} 条未提供 evidence（未验证残余）。"
            )
            _assert_no_banned_terms(verdict)

        return SpineVerdict(
            allowed=allowed,
            clauses=results,
            violations=violations,
            checked_clauses=tuple(checked),
            skipped_clauses=tuple(skipped),
            verdict_text=verdict,
        )


__all__ = [
    # clause id + 收编登记
    "INV_CANVAS_MUTATION",
    "INV_AGENT_ACTION",
    "INV_AGENT_PLAN",
    "INV_AGENT_CODE_CHANGE",
    "INV_ROLE_AGENT_ACTION",
    "INV_SECRET_PLAINTEXT",
    "INV_AGENT_DATA_ACCESS",
    "CLAUSES",
    "STATUS_DELEGATED",
    "STATUS_AGGREGATION",
    "STATUS_MIXED",
    "ENFORCEMENT_BINDINGS",
    "EnforcementBinding",
    "DISCLOSURE",
    "BANNED_IN_REJECTION",
    # 裁定数据类
    "ClauseResult",
    "SpineVerdict",
    "GovernanceSpineViolation",
    # 七条 clause 纯核查函数
    "check_canvas_mutation",
    "check_agent_action",
    "check_agent_plan",
    "check_agent_code_change",
    "check_role_agent_action",
    "check_secret_plaintext",
    "check_agent_data_access",
    # evidence 容器
    "AgentActionEvidence",
    "CodeChangeEvidence",
    "RoleActionEvidence",
    "SecretSurfaceEvidence",
    "DataAccessEvidence",
    "SpineEvidence",
    # 统一门
    "GovernanceSpineGate",
]
