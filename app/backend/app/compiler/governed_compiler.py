"""Governed Compiler（GOAL §1 统一对象链 capstone · §7 role agent 受治理 · §8 治理脊柱）。

GOAL §1 链：`Quant Intent → Typed Canvas/Command → QRO → Research Graph → Governed Compiler →
Deterministic Run → Evidence Verdict → Promotion/Approval → Runtime → Monitor/Retire`。
A-QRO-1（`qro/envelope.py`）/ A-GRAPH-1（`graph/research_graph.py`）/ A-CMD（`command/canonical_command.py`）
已落 QRO 信封 → Research Graph IR → CanonicalCommand 全栈通道。本模块（A-COMPILER）建链里
**`→ Governed Compiler → Deterministic Run → Evidence Verdict → Promotion/Approval`** 那一段——
**完成 QRO→Graph→Command→Compiler→Run→Verdict 整脊柱**。

四段编译管线（每段**收编只读**一个既有件·不重造·扩展不替换 · RULES §1/§4）：
  ① 消费 **canonical command + Research Graph IR**：编译目标必须是经 canonical command 落进图
     （`graph.command_log()`）的真资产节点——绕 canonical command 通道的命令不给编译（§1/§2 链整完整）。
  ② → **Deterministic Run**（收编 `dag.kernel.DurableExecutor` 确定性内核·不重造）：把 run plan
     （DAG tasks）交内核执行，run 携带**确定性内核身份**（`node_id_by_task` 经 `compute_node_id`
     内容寻址·单一身份源 `lineage.ids`）。未经 DurableExecutor 内核 / 身份非确定性派生 → 拒。
  ③ → **Evidence Verdict**（收编 `verification.verifier.Verifier` 验证官 + `eval.overfit_gate.run_overfit_gate`
     多证据三角脊柱门·不重造）：异模型一致性裁决（consistent/concern/blocked）+ DSR/PBO/Bootstrap
     三角裁决（green/yellow/red/insufficient）。verdict **绑定本 run**（`target_ref == kernel_run_id`）。
     绕过 verifier / 三角门的 verdict（伪造裁决）→ 拒。
  ④ governs **Promotion / Approval**（收编 `approval.gate.ApprovalGateService` 审批门·不重造）：
     晋级**必经**审批门（三要件 + **approver≠creator** + 反套话 reason）。绕审批门直造晋级 / approver==creator
     → 拒（§8 治理脊柱「approver=creator 的晋级 → 拒」）。

为什么是「治理结构编排」而非「另造内核/门/裁决」（RULES §1 单一源 + §4 扩展不替换 + §5 不破基线）：
- 内核身份只有一个源：`dag.kernel.compute_node_id`（经 `lineage.ids.node_id`·全库 16 位哈希族）。
  本模块**收编只读**它来 re-derive 校验内核身份，**绝不**另写第二套节点身份哈希。
- evidence 裁决归验证官 + 三角脊柱门（收编 `Verifier.reconcile` + `run_overfit_gate`·原样调用），
  本模块**不**重算一致性/过拟合逻辑、**不**改阈值——只把 evidence 交它们裁、把 verdict 绑定到 run。
- 晋级治理归审批门（收编 `ApprovalGateService`·approver≠creator 在其内强制），本模块**不**重写审批
  状态机、**绝不**开「不经审批直翻 governance=approved」的旁路。
- run/verdict/promotion 三本治理账（`CompileLedger`）+ `assert_*` 可证伪探针，是「绕 compiler 直造 run /
  伪造内核身份 / 伪造 verdict / 绕审批门晋级」四类逃逸的**可证伪**抓手（同 A-CMD `assert_single_channel`、
  A-GRAPH `assert_commanded` 的「单一通道 + 内容寻址 + 落账探针」范式）。

五个命门（可证伪验收 · 种坏门必抓 · RULES §2 · GOAL §1/§7/§8）：
1. 命令未经 compiler 落 run → 拒：命令未经 canonical command 通道落图（不在 `command_log`）→ `UncommandedRunError`；
   绕 `compile()` 直造 run（不在编译账）→ `RunNotCompiledError`（attest/promote 入口的单一通道探针）。
2. run 无 deterministic 内核身份（未经 DurableExecutor）→ `KernelIdentityViolation`：内核报的 `node_id_by_task`
   与 `compute_node_id` 独立重算不符（伪造内核 / 假执行器）→ 拒；`kernel_run_id` 与 node_ids 不自洽（被篡改）→ 拒。
3. verdict 绕过 verifier/三角门 → `VerdictBypassViolation`：verdict_id 非验证官单一源 `compute_verdict_id` 重算
   （伪造裁决）/ verdict.target_ref 未绑定本 run（张冠李戴）/ 缺三角门裁决 → 拒（§7「verdict 绕过 verifier → 拒」）。
4. promotion 未经 approval 门（approver≠creator）→ 拒：晋级必经 `ApprovalGateService`，approver==creator → 审批门
   抛 `ApproverEqualsCreator`；绕审批门直造 PromotedRun（不在治理账）/ approved 却 approver==creator →
   `PromotionGovernanceViolation`（§8「approver=creator 的晋级 → 拒」）。
5. 正路径：合法 command+IR → deterministic run（确定性内核身份）→ verifier verdict（consistent + 三角 green）
   → approval（approver≠creator）→ 正确编译·不误伤。

诚实边界（本模块**不**做什么）：
- 它**不**重造确定性内核 / 验证官 / 三角门 / 审批门——全收编只读、原样调用（RULES §4 收编不改）。
- 它**不**判 evidence 是否「真」充分——那是验证官 + 三角脊柱门的裁决；本模块只编排它们、绑定到 run、
  按其裁决（consistent + green）决定能否进审批门，绝不把任一裁决渲染成「整体可信」。verdict 非 consistent /
  三角非 green → 诚实拒晋级（`EvidenceVerdictUnfavorable`·这是证据不足、**非误伤**）。
- 它**不**重写 honest-N / 三要件 / approver≠creator 逻辑——审批门的依赖（honest-N 账 / verdict 查询）由
  调用方按 `ApprovalGateService` 契约接线，本模块只路由晋级进门、读其裁决。
- 它**不**接 main.py / 不建前端 / 不动被收编模块内部（领地外·中心接线）。无新公式 → **不**造 MathematicalArtifact
  （编译管线是治理结构·非数学产物）。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from ..approval.gate import ApprovalGateService
from ..approval.schema import ApprovalGate, EvidenceSnapshot
from ..dag.engine import DAGTask, _OPS, _topological_sort
from ..dag.kernel import (
    DurableExecutor,
    KernelRunResult,
    compute_node_id,
    op_fingerprint,
)
from ..graph.research_graph import (
    CMD_CREATE_NODE,
    CMD_UPDATE_NODE,
    CanonicalCommand,
    ResearchGraph,
)
from ..lineage.ids import content_hash
from ..qro.envelope import QualifiedResearchObject
from ..verification.schema import VerdictRecord, compute_verdict_id
from ..verification.verifier import Verifier

if TYPE_CHECKING:  # 仅类型——避免 import 期拖 numpy/spine_bindings（run_overfit_gate 在 attest 内懒导）
    from ..eval.n_eff import NEffResult
    from ..eval.overfit_gate import GateVerdict


# ─────────────────────────────────────────────────────────────────────────────
# 异常族（每命门一类·诚实拒绝文案·绝不静默放行）。与被收编模块各自的不变量异常正交并存：
# 那些是各件内部门（内核 effect 边界 / 验证官输入 / 审批 approver≠creator），这是**编译管线**层
# （命令→run→verdict→promotion 四段衔接 + 单一通道 + 内容寻址身份）的治理不变量。
# ─────────────────────────────────────────────────────────────────────────────
class CompilerError(Exception):
    """Governed Compiler 编译管线不变量被违反的基类。"""


class CompilerInputError(CompilerError):
    """编译输入非法（非 CanonicalCommand / 非 ResearchGraph / 缺 run plan / 缺 evidence 等）。"""


class UncommandedRunError(CompilerError):
    """命门 #1（上游）：命令未经 canonical command 通道落图（不在 graph.command_log）→ 不给编译 run。"""


class RunNotCompiledError(CompilerError):
    """命门 #1（下游）：run 绕 compile() 直造（不在编译账）——单一通道探针（GOAL §1/§2/§7）。"""


class KernelIdentityViolation(CompilerError):
    """命门 #2：run 无确定性内核身份（未经 DurableExecutor / node_id 非 compute_node_id 派生 / 身份被篡改）。"""


class VerdictBypassViolation(CompilerError):
    """命门 #3：evidence verdict 绕过验证官/三角门（verdict_id 非单一源重算 / 未绑本 run / 缺三角门）。"""


class EvidenceVerdictUnfavorable(CompilerError):
    """证据裁决不利（verifier 非 consistent / 三角门非 green）——诚实拒晋级（证据不足·**非误伤**）。"""


class PromotionGovernanceViolation(CompilerError):
    """命门 #4：晋级绕审批门（不在治理账 / approved 却 approver==creator）→ 拒（§8 治理脊柱）。"""


# ─────────────────────────────────────────────────────────────────────────────
# actor 归一（approver≠creator 防御纵深 re-check）——对齐 approval/gate.py 的 strip+casefold 口径。
# ─────────────────────────────────────────────────────────────────────────────
def _norm_actor(name: str | None) -> str:
    """approver/creator 归一比较（与 approval/gate.py:180 同口径 strip+casefold·加 NFC 防 Unicode 拼写差）。"""

    return unicodedata.normalize("NFC", str(name or "")).strip().casefold()


# ─────────────────────────────────────────────────────────────────────────────
# Evidence 输入（attest 段·调用方从 run 产物抽取后呈上）——本模块只把它交验证官 + 三角门裁，不伪造。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EvidenceInputs:
    """证据裁决输入（GOAL §1 Evidence Verdict 段）——验证官异模型对账 + 三角脊柱门所需的原始证据。

    `claims`/`recomputed`：生成方自报值 vs 异模型重算值（验证官对账·R7 生成≠验证）。
    `returns`/`returns_matrix`/`n_eff`/`honest_n`：本策略逐期净收益 + 同主题历史矩阵 + N_eff + 名义 N
    （三角门 DSR/PBO/Bootstrap）。本模块**不**计算这些（来自 deterministic run 产物·调用方抽取），只交门裁。
    """

    # 验证官（异模型一致性）
    claims: Mapping[str, float]
    recomputed: Mapping[str, float]
    generator_model: str
    checker_model: str
    generator_seed: Any = None
    checker_seed: Any = None
    generator_slice: str | None = None
    checker_slice: str | None = None
    replay_ref: str | None = None
    # 三角脊柱门（过拟合多证据三角）
    returns: Sequence[float] = ()
    n_eff: "NEffResult | None" = None
    honest_n: int | None = None
    returns_matrix: Any = None
    asset_class: str = "crypto"
    periods_per_year: int = 252
    check_spine_consistency: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# Promotion 请求（promote 段·调用方呈上）——本模块据它路由进审批门，approver≠creator 在门内强制。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PromotionRequest:
    """晋级请求（GOAL §1 Promotion/Approval 段 · §8 治理脊柱）——路由进 `ApprovalGateService` 的参数。

    `created_by` / `approver` 必须不同（approver≠creator·审批门强制·§8）；`to_stage` ∈ staging/production
    走 confirmatory 重门（三要件）、其余走 exploratory（P2 零门）。`reason` confirmatory 不可空/纯套话。
    """

    model_id: str
    version: int
    from_stage: str
    to_stage: str
    action_kind: str
    created_by: str
    approver: str
    reason: str = ""
    dataset_version: str = ""
    strategy_goal_ref: str | None = None
    n_trials_raw: int = 0
    self_approve: bool = False
    acknowledged: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# 编译产物（三段·全 frozen 内容寻址·复用单一身份源 content_hash·前缀 crun_/att_/promo_，
# 同 spine.py math_/tib_/cc_ 与 graph edge_/cmd_ 范式·绝不另造哈希族）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CompiledRun:
    """编译产物·Deterministic Run 段（GOAL §1）——命令 → 经 DurableExecutor 的确定性 run。

    `command_ref` = 落本资产进图的 canonical command id（命令→run 绑定·provenance）。
    `target_node_id` = 本 run 服务的图节点（资产）id（== 经 IR 校验存在的 QRO identity）。
    `kernel_run_id` = `krn_`+content_hash(sorted(node_ids))——**确定性内核身份指纹**（证明经内核·命门 #2）。
    `node_id_by_task` = 内核为每个 task 算的 node_id（`compute_node_id` 内容寻址·可独立 re-derive 核验）。
    `run_id` = 本编译产物的内容寻址 id（编译账主键·命门 #1 单一通道凭证）。
    """

    command_ref: str
    target_node_id: str
    kernel_run_id: str
    node_id_by_task: Mapping[str, str]
    kernel_mode: str
    kernel_succeeded: bool
    run_id: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            object.__setattr__(
                self,
                "run_id",
                "crun_"
                + content_hash(
                    {
                        "command_ref": self.command_ref,
                        "target_node_id": self.target_node_id,
                        "kernel_run_id": self.kernel_run_id,
                    }
                ),
            )


@dataclass(frozen=True)
class AttestedRun:
    """编译产物·Evidence Verdict 段（GOAL §1）——deterministic run + 验证官裁决 + 三角脊柱门裁决。

    `verdict_record` = 验证官产 `VerdictRecord`（content-addressed·`verdict_id` 可经单一源 `compute_verdict_id`
    重算·命门 #3）；`verdict` ∈ consistent/concern/blocked。`gate_verdict` = `run_overfit_gate` 产 `GateVerdict`；
    `gate_color` ∈ green/yellow/red/insufficient_evidence。两者皆**绑定本 run**（verdict.target_ref==kernel_run_id）。
    """

    run_id: str
    compiled_run: CompiledRun
    verdict_record: VerdictRecord
    verdict_id: str
    verdict: str
    gate_verdict: "GateVerdict"
    gate_color: str
    attest_id: str = ""

    def __post_init__(self) -> None:
        if not self.attest_id:
            object.__setattr__(
                self,
                "attest_id",
                "att_"
                + content_hash(
                    {
                        "run_id": self.run_id,
                        "verdict_id": self.verdict_id,
                        "verdict": self.verdict,
                        "gate_color": self.gate_color,
                    }
                ),
            )


@dataclass(frozen=True)
class PromotedRun:
    """编译产物·Promotion/Approval 段（GOAL §1 · §8 治理脊柱）——attested run 经审批门的晋级裁定。

    `gate_id` = 审批门 `ApprovalGate` id（晋级经审批门凭证·命门 #4）；`governance` ∈ approved/rejected/
    pending/timed_out（审批门裁定·非本模块自判）；`approver`/`created_by` 落账供 approver≠creator 复核；
    `gap_list` = 审批门拒绝时的缺口清单（诚实承载·绝不渲染成「已批」）。
    """

    run_id: str
    attested_run: AttestedRun
    gate_id: str
    governance: str
    approver: str | None
    created_by: str
    self_approved: bool = False
    gap_list: tuple[str, ...] = ()
    promo_id: str = ""

    def __post_init__(self) -> None:
        if not self.promo_id:
            object.__setattr__(
                self,
                "promo_id",
                "promo_"
                + content_hash(
                    {
                        "run_id": self.run_id,
                        "gate_id": self.gate_id,
                        "governance": self.governance,
                    }
                ),
            )


# ─────────────────────────────────────────────────────────────────────────────
# 治理账（GOAL §1/§7/§8「每次产物/证据/审批都落账·可 replay/fork/rollback」）——append-only·三段同源一本。
# 单一通道凭证：compile/attest/promote 是唯一记账写口；`is_*`/`*_ids` 供 assert_* 探针对账（绕通道直造 → 不在账 → 拒）。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CompileLedgerEntry:
    """治理账一条（GOAL §8 audit）——段（compiled/attested/promoted）+ 产物身份 + 绑定的上游 run。"""

    seq: int
    stage: str
    artifact_id: str
    run_id: str


class CompileLedger:
    """Governed Compiler 治理账（GOAL §1/§7/§8）——run/verdict/promotion 三段同进**一本** append-only 账。

    `record_compiled/record_attested/record_promoted` 是唯一记账写口；`compiled_ids/attested_ids/promoted_ids`
    供 `assert_run_compiled` 等探针对账。诚实：Python 不能真隐藏内部 dict；单一通道 = 结构上记账写口唯一 +
    对账探针（同 A-CMD `CommandLedger`/A-GRAPH `_command_log` 范式·绕过仍可能但「是否走了前门」可证伪）。
    """

    def __init__(self) -> None:
        self._entries: list[CompileLedgerEntry] = []
        self._compiled: dict[str, CompiledRun] = {}
        self._attested: dict[str, AttestedRun] = {}
        self._promoted: dict[str, PromotedRun] = {}

    def _append(self, stage: str, artifact_id: str, run_id: str) -> CompileLedgerEntry:
        entry = CompileLedgerEntry(seq=len(self._entries), stage=stage, artifact_id=artifact_id, run_id=run_id)
        self._entries.append(entry)
        return entry

    def record_compiled(self, run: CompiledRun) -> CompiledRun:
        self._compiled[run.run_id] = run
        self._append("compiled", run.run_id, run.run_id)
        return run

    def record_attested(self, attested: AttestedRun) -> AttestedRun:
        self._attested[attested.attest_id] = attested
        self._append("attested", attested.attest_id, attested.run_id)
        return attested

    def record_promoted(self, promoted: PromotedRun) -> PromotedRun:
        self._promoted[promoted.promo_id] = promoted
        self._append("promoted", promoted.promo_id, promoted.run_id)
        return promoted

    def compiled_ids(self) -> frozenset[str]:
        return frozenset(self._compiled)

    def attested_ids(self) -> frozenset[str]:
        return frozenset(self._attested)

    def promoted_ids(self) -> frozenset[str]:
        return frozenset(self._promoted)

    def entries(self) -> tuple[CompileLedgerEntry, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# ─────────────────────────────────────────────────────────────────────────────
# VerdictBook（审批门 verdict_lookup 接线·破构造环）——验证官裁决按 verdict_id 可查。
# attest 段落账；审批门（收编·调用方构造）的 verdict_lookup 读它（确证三要件「裁决未被篡改 + 绑定本次」）。
# ─────────────────────────────────────────────────────────────────────────────
class VerdictBook:
    """验证官裁决簿（GOAL §8）——`verdict_id → VerdictRecord`。

    审批门确证三要件需 `verdict_lookup(verification_record_id) → 含 .target_ref/.verdict 的记录`；
    本簿是 compiler 与审批门之间**不引构造环**的共享只读源（compiler 写、审批门读）。
    """

    def __init__(self) -> None:
        self._records: dict[str, VerdictRecord] = {}

    def put(self, record: VerdictRecord) -> VerdictRecord:
        self._records[record.verdict_id] = record
        return record

    def get(self, verdict_id: str | None) -> VerdictRecord | None:
        if not verdict_id:
            return None
        return self._records.get(verdict_id)


# ─────────────────────────────────────────────────────────────────────────────
# Governed Compiler（GOAL §1 链 capstone）——command+IR → run → verdict → promotion 四段编排 + 五命门。
# ─────────────────────────────────────────────────────────────────────────────
class GovernedCompiler:
    """治理编译器（GOAL §1 链 `Governed Compiler → Deterministic Run → Evidence Verdict → Promotion`）。

    收编只读四件（构造期注入·不另造）：`DurableExecutor`（确定性内核）/`Verifier`（异模型验证官）/
    `ApprovalGateService`（审批门 approver≠creator）/`run_overfit_gate`（三角脊柱门·attest 内懒调）。
    三段公共写口 `compile`/`attest`/`promote`（+ `govern` 一把过整脊柱）各落治理账、各过对应命门；
    `assert_*` 是「绕 compiler 直造 / 伪造内核身份 / 伪造 verdict / 绕审批门晋级」的可证伪探针。
    """

    def __init__(
        self,
        *,
        executor: DurableExecutor,
        verifier: Verifier,
        approval: ApprovalGateService,
        verdict_book: VerdictBook | None = None,
        ops: Mapping[str, Callable[..., Any]] | None = None,
        ledger: CompileLedger | None = None,
    ) -> None:
        if not isinstance(executor, DurableExecutor):
            # 命门 #2 的构造期兜底：确定性内核身份只能来自真 DurableExecutor（收编·单一源）。
            raise KernelIdentityViolation(
                "GovernedCompiler 需 DurableExecutor 确定性内核（收编 dag.kernel·run 确定性身份单一源）"
            )
        if not isinstance(verifier, Verifier):
            raise CompilerInputError("GovernedCompiler 需 verification.Verifier 验证官（收编·evidence 裁决单一源）")
        if not isinstance(approval, ApprovalGateService):
            raise CompilerInputError(
                "GovernedCompiler 需 approval.ApprovalGateService 审批门（收编·approver≠creator 单一源）"
            )
        self._executor = executor
        self._verifier = verifier
        self._approval = approval
        self._verdict_book = verdict_book if verdict_book is not None else VerdictBook()
        # 内核身份 re-derive 用的 op 注册表：默认 = 内核默认 `dag.engine._OPS`（与 DurableExecutor 默认一致）。
        # 诚实残余：若注入的 executor 用了**自定义** ops 注册表，须把同一张表传 `ops=`，否则 re-derive 会
        # 误判（false reject）——治理路径默认共享 _OPS，此为已知边界（非治理漏洞·见模块 docstring）。
        self._ops: Mapping[str, Callable[..., Any]] = ops if ops is not None else _OPS
        self._ledger = ledger if ledger is not None else CompileLedger()

    # ── 只读访问器 ──────────────────────────────────────────────────────────
    @property
    def ledger(self) -> CompileLedger:
        return self._ledger

    @property
    def verdict_book(self) -> VerdictBook:
        return self._verdict_book

    def lookup_verdict(self, verdict_id: str | None) -> VerdictRecord | None:
        """审批门 verdict_lookup 接线点（读验证官裁决簿·破构造环）。"""

        return self._verdict_book.get(verdict_id)

    # ═════════════════════════════════════════════════════════════════════════
    # ① + ② Deterministic Run 段：command + IR → 经 DurableExecutor 的确定性 run（命门 #1 上游 + #2）。
    # ═════════════════════════════════════════════════════════════════════════
    def compile(
        self,
        command: CanonicalCommand,
        tasks: Sequence[DAGTask],
        *,
        graph: ResearchGraph,
        context: dict[str, Any] | None = None,
        target_node_id: str | None = None,
    ) -> CompiledRun:
        """编译一条经 canonical command 落图的资产 → deterministic run（GOAL §1 链 ①②）。

        顺序：命令是真 CanonicalCommand 且**已落图**（command_log·命门 #1 上游）→ 解析编译目标资产
        （在 IR 节点·命门 #1 消费 IR）→ 交 DurableExecutor 执行（deterministic run）→ **独立 re-derive
        校验内核身份**（命门 #2）→ 铸 kernel_run_id + 落编译账（命门 #1 下游单一通道）。任一步失败即抛。
        """

        if not isinstance(command, CanonicalCommand):
            raise CompilerInputError(
                "compile 只接受 graph.CanonicalCommand（§1 链 command→compiler·不收编裸 dict/duck）"
            )
        if not isinstance(graph, ResearchGraph):
            raise CompilerInputError("compile 需 graph.ResearchGraph IR（§1 链 Research Graph→Compiler 消费 IR）")
        # 命门 #1（上游）：命令必须经 canonical command 通道落进图（在 command_log）——绕通道的命令不编译。
        if command.command_id not in {c.command_id for c in graph.command_log()}:
            raise UncommandedRunError(
                f"命令 {command.command_id!r} 未经 Research Graph canonical command 通道落账（不在 command_log）"
                "——拒为其编译 run（GOAL §1/§2/§7：命令未经 canonical command 通道 → 不进 compiler）"
            )
        # 命门 #1（消费 IR）：编译目标资产必须在 IR 节点（绑定 run 到真资产·非凭空）。
        target = target_node_id or self._target_node_from_command(command)
        if not target:
            raise CompilerInputError(
                f"无法解析编译目标资产：命令 {command.command_type!r} 非 create/update 资产命令且未显式给 target_node_id"
            )
        if graph.get_node(target) is None:
            raise CompilerInputError(
                f"编译目标资产 {target!r} 不在 Research Graph IR（§1 链 compiler 消费 IR 节点·绑定真资产）"
            )
        if not tasks:
            raise CompilerInputError("run plan（DAG tasks）为空：deterministic run 段无可执行图")

        # ② Deterministic Run：收编 DurableExecutor 确定性内核（原样调用·不重造）。
        task_list = list(tasks)
        kernel_result = self._executor.run(task_list, context or {})
        # 命门 #2：独立 re-derive 校验内核身份（伪造内核 / 假执行器返伪 node_id → 此处必抓）。
        self.assert_kernel_identity(task_list, kernel_result)
        kernel_run_id = self._kernel_run_id(kernel_result.node_id_by_task)
        compiled = CompiledRun(
            command_ref=command.command_id,
            target_node_id=target,
            kernel_run_id=kernel_run_id,
            node_id_by_task=dict(kernel_result.node_id_by_task),
            kernel_mode=kernel_result.mode,
            kernel_succeeded=kernel_result.succeeded,
        )
        # 命门 #1（下游）：落编译账——单一通道凭证（绕 compile 直造的 run 不在账·attest/promote 必拒）。
        self._ledger.record_compiled(compiled)
        return compiled

    def _target_node_from_command(self, command: CanonicalCommand) -> str | None:
        """从 create/update 命令解析编译目标资产 id（== payload QRO identity·单一身份源）。"""

        if command.command_type not in (CMD_CREATE_NODE, CMD_UPDATE_NODE):
            return None
        payload = command.payload if isinstance(command.payload, Mapping) else {}
        qro = payload.get("qro")
        if isinstance(qro, QualifiedResearchObject):
            return qro.identity
        return None

    @staticmethod
    def _kernel_run_id(node_id_by_task: Mapping[str, str]) -> str:
        """确定性内核身份指纹 = `krn_`+content_hash(sorted(node_ids))（复用单一身份源·不另造哈希族）。"""

        return "krn_" + content_hash(sorted(node_id_by_task.values()))

    def _derive_node_ids(self, tasks: Sequence[DAGTask]) -> dict[str, str]:
        """独立 re-derive 每个 task 的内核 node_id——**完全复刻** DurableExecutor 的身份口径（收编不重造）。

        与 `kernel._execute` 同：topological 走图、上游 node_id 入内容寻址、`compute_node_id` + `op_fingerprint`
        （单一身份源 lineage.ids·全库 16 位哈希族）。op 注册表用 `self._ops`（默认内核 `_OPS`·与执行器默认一致）。
        """

        ordered = _topological_sort(list(tasks))
        by_task: dict[str, str] = {}
        for task in ordered:
            up = sorted(by_task[d] for d in task.deps if d in by_task)
            by_task[task.id] = compute_node_id(
                task, up, op_version=op_fingerprint(self._ops.get(task.op), task.op)
            )
        return by_task

    # ── 命门 #2：内核身份探针（confirm 经 DurableExecutor 确定性内核·身份非伪造/篡改）──
    def assert_kernel_identity(self, tasks: Sequence[DAGTask], kernel_result: Any) -> None:
        """命门 #2：run 的 node_id_by_task 必须是 DurableExecutor 确定性内核身份，否则拒（GOAL §1/§7）。

        必须是真 `KernelRunResult`（非 duck 假执行器返回物）→ 否则无内核身份；`node_id_by_task` 非空；
        且**每个** node_id == `compute_node_id` 独立重算（伪造内核 / 假执行器返伪 id → 重算不符 → 拒）。
        这是「run 无 deterministic 内核身份（未经 DurableExecutor）→ 拒」的可证伪兑现（种坏门必抓）。
        """

        if not isinstance(kernel_result, KernelRunResult):
            raise KernelIdentityViolation(
                f"run 无确定性内核身份：执行结果非 DurableExecutor 的 KernelRunResult（得 {type(kernel_result).__name__}）"
                "——未经确定性内核（GOAL §1：run 必有确定性内核身份）"
            )
        node_id_by_task = kernel_result.node_id_by_task
        if not node_id_by_task:
            raise KernelIdentityViolation("run 无确定性内核身份：node_id_by_task 空（未经内核身份计算）")
        derived = self._derive_node_ids(tasks)
        for task in tasks:
            want = derived.get(task.id)
            got = node_id_by_task.get(task.id)
            if want != got:
                raise KernelIdentityViolation(
                    f"run 内核身份非确定性派生：task {task.id!r} 内核报 node_id={got!r} ≠ "
                    f"compute_node_id 独立重算 {want!r}——未经 DurableExecutor 确定性内核 / 身份被伪造（GOAL §1/§7 → 拒）"
                )

    def _assert_kernel_self_consistent(self, compiled_run: CompiledRun) -> None:
        """命门 #2（自洽）：kernel_run_id 必须 == 由 node_id_by_task 重算（防身份字段被篡改·attest/promote 入口复核）。"""

        want = self._kernel_run_id(compiled_run.node_id_by_task)
        if compiled_run.kernel_run_id != want:
            raise KernelIdentityViolation(
                f"内核身份被篡改：kernel_run_id={compiled_run.kernel_run_id!r} ≠ 由 node_ids 重算 {want!r}"
            )

    # ── 命门 #1（下游）：单一通道探针（run 经 compile 落账）──
    def assert_run_compiled(self, run_id: str) -> None:
        """命门 #1：run 必须经 compile() 落编译账，否则拒（GOAL §1/§2/§7 单一通道·种坏门必抓）。

        正路径下 compile 恒「落账」，此门恒过；它是**绕通道探针**——绕 compile 直造 CompiledRun（维护
        编译外 run / 命令未落 canonical command 就跑 run）→ run_id ∉ 编译账 → 拒（attest/promote 入口都过此门）。
        """

        if run_id not in self._ledger.compiled_ids():
            raise RunNotCompiledError(
                f"run {run_id!r} 未经 Governed Compiler 编译落账（不在编译账）——绕 compiler 直造 run"
                "（GOAL §1/§2/§7：命令未经 compiler 落 run → 拒）"
            )

    # ═════════════════════════════════════════════════════════════════════════
    # ③ Evidence Verdict 段：deterministic run + 证据 → 验证官裁决 + 三角脊柱门裁决（命门 #3 绑定本 run）。
    # ═════════════════════════════════════════════════════════════════════════
    def attest(self, compiled_run: CompiledRun, evidence: EvidenceInputs) -> AttestedRun:
        """对 deterministic run 的证据出**异模型一致性裁决 + 多证据三角裁决**（GOAL §1 链 ③·收编不重造）。

        门：run 经 compile 落账（命门 #1）+ 内核身份自洽（命门 #2）→ 收编 `Verifier.reconcile`（异模型对账·
        verdict 绑定 `target_ref==kernel_run_id`）+ 收编 `run_overfit_gate`（DSR/PBO/Bootstrap 三角脊柱门）→
        裁决落验证官簿（供审批门 verdict_lookup）+ 落治理账。verdict/裁决**原样承载**·绝不渲染成整体可信。
        """

        if not isinstance(compiled_run, CompiledRun):
            raise CompilerInputError("attest 只接受 compile() 产的 CompiledRun")
        if not isinstance(evidence, EvidenceInputs):
            raise CompilerInputError("attest 需 EvidenceInputs（验证官 claims/recomputed + 三角门 returns/n_eff）")
        self.assert_run_compiled(compiled_run.run_id)  # 命门 #1：必经 compile
        self._assert_kernel_self_consistent(compiled_run)  # 命门 #2：内核身份自洽
        if evidence.n_eff is None:
            raise CompilerInputError("attest 需 evidence.n_eff（NEffResult·三角门通缩区间所需·收编 eval.n_eff）")

        # ③-a 异模型一致性裁决：收编验证官（原样 reconcile·target_ref 绑定本 run·防张冠李戴）。
        verdict_record = self._verifier.reconcile(
            target_ref=compiled_run.kernel_run_id,
            claims=evidence.claims,
            recomputed=evidence.recomputed,
            generator_model=evidence.generator_model,
            checker_model=evidence.checker_model,
            generator_seed=evidence.generator_seed,
            checker_seed=evidence.checker_seed,
            generator_slice=evidence.generator_slice,
            checker_slice=evidence.checker_slice,
            replay_ref=evidence.replay_ref,
        )
        # ③-b 多证据三角脊柱门：收编 run_overfit_gate（懒导避免 import 期拖 numpy/spine_bindings）。
        from ..eval.overfit_gate import run_overfit_gate

        gate_verdict = run_overfit_gate(
            evidence.returns,
            n_eff=evidence.n_eff,
            honest_n=evidence.honest_n,
            returns_matrix=evidence.returns_matrix,
            asset_class=evidence.asset_class,
            periods_per_year=evidence.periods_per_year,
            check_spine_consistency=evidence.check_spine_consistency,
        )

        self._verdict_book.put(verdict_record)  # 供审批门 verdict_lookup（确证三要件读它）
        attested = AttestedRun(
            run_id=compiled_run.run_id,
            compiled_run=compiled_run,
            verdict_record=verdict_record,
            verdict_id=verdict_record.verdict_id,
            verdict=verdict_record.verdict,
            gate_verdict=gate_verdict,
            gate_color=gate_verdict.color,
        )
        self._ledger.record_attested(attested)
        return attested

    # ── 命门 #3：verdict 经验证官探针（verdict_id 单一源重算 + 绑定本 run + 三角门在场）──
    def assert_verdict_attested(self, attested_run: AttestedRun) -> None:
        """命门 #3：verdict 必须出自验证官/三角门、未被伪造、绑定本 run，否则拒（GOAL §7「verdict 绕 verifier → 拒」）。

        verdict_id == 验证官单一源 `compute_verdict_id` 重算（伪造裁决·手刻 'consistent' → 重算不符 → 拒）；
        verdict.target_ref == 本 run 的 kernel_run_id（借别 run 的裁决张冠李戴 → 拒）；三角门裁决在场
        （缺三角脊柱门 → 拒）。是「evidence verdict 绕过 verifier/spine_gate → 拒」的可证伪兑现（种坏门必抓）。
        """

        rec = attested_run.verdict_record
        if not isinstance(rec, VerdictRecord):
            raise VerdictBypassViolation("evidence verdict 缺验证官 VerdictRecord（绕验证官 → 拒）")
        # 验证官单一源重算（同 verification.schema.compute_verdict_id·杜绝伪造裁决）。
        recomputed_id = compute_verdict_id(
            target_ref=rec.target_ref,
            generator_model=rec.generator_model,
            checker_model=rec.checker_model,
            verdict=rec.verdict,
            consistency_check=rec.consistency_check,
            independence=rec.independence,
            replay_ref=rec.replay_ref,
        )
        if rec.verdict_id != recomputed_id or attested_run.verdict_id != rec.verdict_id:
            raise VerdictBypassViolation(
                f"evidence verdict 非验证官单一源裁决（伪造/篡改）：声称 verdict_id={attested_run.verdict_id!r} / "
                f"记录 {rec.verdict_id!r} ≠ compute_verdict_id 重算 {recomputed_id!r}（GOAL §7：verdict 绕 verifier → 拒）"
            )
        # 绑定本 run（防借别 run 的 consistent 裁决冒名顶替·同 approval target_ref 绑定精神）。
        if rec.target_ref != attested_run.compiled_run.kernel_run_id:
            raise VerdictBypassViolation(
                f"evidence verdict 未绑定本 run：verdict.target_ref={rec.target_ref!r} ≠ "
                f"kernel_run_id={attested_run.compiled_run.kernel_run_id!r}（张冠李戴 → 拒）"
            )
        # 三角脊柱门必须在场（evidence verdict = 验证官 + 三角门·缺一即绕脊柱门）。
        if not attested_run.gate_color or getattr(attested_run.gate_verdict, "color", None) != attested_run.gate_color:
            raise VerdictBypassViolation("evidence verdict 缺多证据三角脊柱门裁决（绕 overfit_gate → 拒）")

    # ═════════════════════════════════════════════════════════════════════════
    # ④ Promotion / Approval 段：attested run → 经审批门（approver≠creator）的晋级（命门 #3 + #4）。
    # ═════════════════════════════════════════════════════════════════════════
    def promote(self, attested_run: AttestedRun, promotion: PromotionRequest) -> PromotedRun:
        """把 attested run 路由进审批门晋级（GOAL §1 链 ④ · §8 治理脊柱·收编不重造）。

        门：run 经 compile 落账（命门 #1）+ verdict 出自验证官且绑定本 run（命门 #3）→ 证据裁决须**有利**
        （verifier consistent + 三角 green·否则诚实拒晋级·**非误伤**）→ 收编 `ApprovalGateService` 开门 + 审批
        （approver≠creator 在门内强制·命门 #4）→ 落治理账。**绝无**「不经审批直翻 governance=approved」旁路。
        """

        if not isinstance(attested_run, AttestedRun):
            raise CompilerInputError("promote 只接受 attest() 产的 AttestedRun")
        if not isinstance(promotion, PromotionRequest):
            raise CompilerInputError("promote 需 PromotionRequest（model/stage/created_by/approver…）")
        self.assert_run_compiled(attested_run.run_id)  # 命门 #1：必经 compile
        self.assert_verdict_attested(attested_run)  # 命门 #3：verdict 出自验证官·绑定本 run

        # 证据裁决须有利才进审批门——否则诚实拒（证据不足·**非误伤**·绝不把弱证据推进晋级）。
        if attested_run.verdict != "consistent":
            raise EvidenceVerdictUnfavorable(
                f"异模型一致性 verdict={attested_run.verdict!r}（非 consistent）：证据不足/存疑/不一致，拒晋级"
                "（GOAL §8 裁决语言·诚实拒·非误伤）"
            )
        if attested_run.gate_color != "green":
            raise EvidenceVerdictUnfavorable(
                f"多证据三角 gate={attested_run.gate_color!r}（非 green）：DSR/PBO/Bootstrap 未同向充分，拒晋级"
                "（GOAL §8 裁决语言·诚实拒·非误伤）"
            )

        # ④ 收编审批门（原样开门 + 审批·approver≠creator 在 ApprovalGateService 内强制·不重写状态机）。
        evidence_snapshot = self._build_evidence_snapshot(attested_run, promotion)
        gate = self._approval.open_gate(
            model_id=promotion.model_id,
            version=promotion.version,
            from_stage=promotion.from_stage,
            to_stage=promotion.to_stage,
            action_kind=promotion.action_kind,
            created_by=promotion.created_by,
            verification_record_id=attested_run.verdict_id,
            evidence=evidence_snapshot,
            strategy_goal_ref=promotion.strategy_goal_ref,
        )
        # 开门 pending（confirmatory 三要件齐）→ 路由审批（approver==creator → 审批门抛 ApproverEqualsCreator·命门 #4）。
        if gate.decision == "pending":
            gate = self._approval.approve(
                gate.gate_id,
                approver=promotion.approver,
                reason=promotion.reason,
                self_approve=promotion.self_approve,
                acknowledged=promotion.acknowledged,
            )

        promoted = PromotedRun(
            run_id=attested_run.run_id,
            attested_run=attested_run,
            gate_id=gate.gate_id,
            governance=gate.decision,
            approver=gate.approver,
            created_by=promotion.created_by,
            self_approved=bool(getattr(gate, "self_approved", False)),
            gap_list=tuple(gate.gap_list or ()),
        )
        self._ledger.record_promoted(promoted)
        return promoted

    def _build_evidence_snapshot(self, attested_run: AttestedRun, promotion: PromotionRequest) -> dict[str, Any]:
        """从三角门裁决 + 本 run 构 EvidenceSnapshot（审批门确证三要件消费·单一源三角数字·不另算）。

        `config_hash = kernel_run_id`（== verdict.target_ref·审批门据此校验裁决绑定本次晋升·防张冠李戴）；
        DSR/PBO/CI 取三角门裁决数字（绝不另算第二套）；champion/challenger.verdict 带异模型裁决。
        """

        gv = attested_run.gate_verdict
        pbo = gv.pbo if gv.pbo is not None else 1.0  # PBO 缺 → 保守填 1.0（审批门三角必拒·不放水）
        n_eff_dict = gv.n_eff if isinstance(gv.n_eff, dict) else {}
        n_eff_val = int(n_eff_dict.get("high") or n_eff_dict.get("point") or gv.n_observed or 1)
        snapshot = EvidenceSnapshot(
            config_hash=attested_run.compiled_run.kernel_run_id,
            dataset_version=promotion.dataset_version,
            n_eff=n_eff_val,
            n_trials_raw=promotion.n_trials_raw,
            dsr=float(gv.dsr_conservative),
            pbo=float(pbo),
            bootstrap_ci=tuple(gv.bootstrap_ci),
            bootstrap_estimate=0.0,
            champion_challenger={"verdict": attested_run.verdict, "gate_color": attested_run.gate_color},
            triangle_aligned=bool(gv.all_agree_positive),
        )
        return snapshot.to_dict()

    # ── 命门 #4：晋级经审批门探针（治理账 + approver≠creator 复核·防绕审批门直造）──
    def assert_promotion_governed(self, promoted_run: PromotedRun) -> None:
        """命门 #4：晋级必经审批门治理，否则拒（GOAL §8「approver=creator 的晋级 → 拒」·种坏门必抓）。

        正路径下 promote 恒「经审批门 + 落治理账」，此门恒过；它是**绕审批门探针**——绕 promote 直造
        PromotedRun（不在治理账）→ 拒；或 approved 却 approver==creator（绕 approver≠creator 旁路）→ 拒
        （防御纵深·与 ApprovalGateService 内 ApproverEqualsCreator 正交并存：那守开门审批、这守落账产物）。
        """

        if promoted_run.promo_id not in self._ledger.promoted_ids():
            raise PromotionGovernanceViolation(
                f"晋级 {promoted_run.promo_id!r} 未经审批门治理路由（不在治理账）——绕 ApprovalGateService 直造 PromotedRun"
                "（GOAL §8：晋级必经 HITL approval → 拒）"
            )
        # approver≠creator 防御纵深复核（approved 且非单人自批时·approver 必 ≠ creator）。
        if promoted_run.governance == "approved" and not promoted_run.self_approved:
            if _norm_actor(promoted_run.approver) == _norm_actor(promoted_run.created_by):
                raise PromotionGovernanceViolation(
                    f"approved 晋级的 approver==creator：approver={promoted_run.approver!r} == creator="
                    f"{promoted_run.created_by!r}（归一比较·GOAL §8：approver=creator 的晋级 → 拒）"
                )

    # ═════════════════════════════════════════════════════════════════════════
    # 一把过整脊柱（GOAL §1 链）：command+IR → run → verdict → promotion（compile→attest→promote）。
    # ═════════════════════════════════════════════════════════════════════════
    def govern(
        self,
        command: CanonicalCommand,
        tasks: Sequence[DAGTask],
        *,
        graph: ResearchGraph,
        evidence: EvidenceInputs,
        promotion: PromotionRequest,
        context: dict[str, Any] | None = None,
        target_node_id: str | None = None,
    ) -> PromotedRun:
        """整脊柱一把过（GOAL §1：Command→Graph→Compiler→Run→Verdict→Promotion）——compile→attest→promote。

        逐段过门、逐段落账；任一段命门失败即抛（绝不静默推进）。返回终态 PromotedRun（其链可回溯
        attested_run → compiled_run → command_ref·全程可 audit）。
        """

        compiled = self.compile(command, tasks, graph=graph, context=context, target_node_id=target_node_id)
        attested = self.attest(compiled, evidence)
        return self.promote(attested, promotion)


# ─────────────────────────────────────────────────────────────────────────────
# 便捷工厂（语义糖·非门）——把收编四件 + 治理账 + verdict 簿一次接好（破审批门 verdict_lookup 构造环）。
# 门一律在 GovernedCompiler 的 compile/attest/promote 内·此处只省接线样板。
# ─────────────────────────────────────────────────────────────────────────────
def build_default_compiler(
    *,
    executor: DurableExecutor,
    approval_store: Any,
    honest_n_ledger: Any = None,
    safety_service: Any = None,
    verifier: Verifier | None = None,
    ops: Mapping[str, Callable[..., Any]] | None = None,
) -> GovernedCompiler:
    """接好一台 GovernedCompiler：验证官 + 审批门（verdict_lookup 接 VerdictBook·honest-N 账注入）+ 治理账。

    `executor`（收编内核·调用方按需 root/store/ledger 构造）、`approval_store`（审批门落盘）、
    `honest_n_ledger`（审批门确证 honest-N 依赖·调用方按 `ApprovalGateService` 契约提供·本模块不碰 honest-N）。
    VerdictBook 在此创建并同时接给审批门 verdict_lookup 与 compiler（破构造环·共享只读裁决源）。
    """

    book = VerdictBook()
    verifier = verifier if verifier is not None else Verifier()
    approval = ApprovalGateService(
        approval_store,
        safety_service=safety_service,
        ledger=honest_n_ledger,
        verdict_lookup=book.get,
    )
    return GovernedCompiler(
        executor=executor,
        verifier=verifier,
        approval=approval,
        verdict_book=book,
        ops=ops,
    )


__all__ = [
    # 入参 / 产物
    "EvidenceInputs",
    "PromotionRequest",
    "CompiledRun",
    "AttestedRun",
    "PromotedRun",
    # 账 / 簿
    "CompileLedger",
    "CompileLedgerEntry",
    "VerdictBook",
    # 编译器 + 工厂
    "GovernedCompiler",
    "build_default_compiler",
    # 异常族（每命门一类）
    "CompilerError",
    "CompilerInputError",
    "UncommandedRunError",
    "RunNotCompiledError",
    "KernelIdentityViolation",
    "VerdictBypassViolation",
    "EvidenceVerdictUnfavorable",
    "PromotionGovernanceViolation",
]
