"""发版门禁 —— §16 工程标准作不可绕的 release gate（GOAL §16 + §0 · 卡 D-RELEASE-GATE）。

晋级/发版前，把 GOAL §16「工程标准」逐条核成硬门：任一缺 → 拒发版。本模块【不重造】已建门，
而是把它们【收编只读·聚合】成单一 release gate —— 一个调用方在「翻态/上线之前」调的唯一闸：

  §16 标准                                          → 本门          → 实现（收编 / 新建）
  ─────────────────────────────────────────────────────────────────────────────────────
  no silent mock fallback / no template false success → GATE_MOCK    新建 mock_honesty（全仓原无）
  dataset_version + checksum                          → GATE_DATASET 收编 data_quality.DatasetVersion /
                                                                      delivery.DatasetVersionRef（duck-typed）
  TheoryImplementationBinding required for proof-backed→ GATE_SPINE   收编 spine_gate.evaluate_promotion
  ConsistencyCheck required before theory promotion    → GATE_SPINE   （同上·一处委派覆盖 §16 ④⑤）
  MethodologyChoiceRecord required for user-waived     → GATE_MCR     新建 presence 门（evaluate_promotion
                                                                      只在 waiver 在场时用它·不强制其存在）
  LLM Gateway enforced + provider/model/auth_ref/replay → GATE_LLM    收编 llm.call_record 准入门 + 封印
  ─────────────────────────────────────────────────────────────────────────────────────
  附·聚合已建证据（给则核·缺则软披露不误伤）：
  Verifier 裁决 blocked 不得发版                       → GATE_VERIFIER 收编 verification.VerdictRecord
  Approval 非 approved 不得发版                         → GATE_APPROVAL 收编 approval.ApprovalGate
  RDP 未过 §17 四门不得发版                             → GATE_RDP      收编 delivery.rdp_gate.validate_rdp

为什么委派而非重写（RULES §1 单一源 / 卡红线「复用已建门不另造」）：
- §16 ④⑤ 的「TIB/CC 是否齐 + 一致性是否过」全权在 `spine_gate.evaluate_promotion`——本门只把强标签
  candidate 喂进去、读它的 `promotable` + `violations`，绝不另写一套一致性判定（否则双源必漂）。
- §16 ⑦ 的「LLMCallRecord 必填字段」单一定义是 `call_record.REQUIRED_FIELDS`——本门 `assert_record_admissible`
  复用它，不另立第二套必填集。

诚实纪律（RULES §3 · 北极星 correctness）：
- 缺标准【真拒】（outcome.passed=False / require_releasable raise），绝不静默填默认放行。
- 单一源准入门不含 cost（provider 常不返 usage）——§16 虽列 cost，本门把「cost 未记」作【软披露】
  honest_gap、**不**硬拒（硬拒会与单一源矛盾、误伤已封印的真账）。同理「未给 gateway_secret 无法验
  封印来路」也作软披露而非硬拒（无证据证明绕过，就不假装拒得有理）。
- 安全红线（北极星·撞即停工报告）：给了 `known_secrets` 而明文进了任一 LLMCallRecord 序列化面 →
  `assert_no_plaintext_secret` raise `SecretLeakError`（复用 LLM Gateway 门2 单一扫描器·绝不回显 secret）。

诚实限界（不号称做到的）：
- 本门核查【声明的治理工件是否齐全自洽】，**不**自行证明数学命题 / 不识破谎报 mode 的执行块
  （见 mock_honesty 模块诚实限界）/ 不在 main.py 接发版编排（那是中心/下游另卡·诚实残余）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# —— 收编只读：各已建门按其单一源直接 import（只引轻量子模块·不拉 polars 等重依赖）——
from ..approval.schema import ApprovalGate
from ..delivery.rdp import PromotionClaim, RDPManifest
from ..delivery.rdp_gate import validate_rdp
from ..lineage.spine import (
    LABEL_CUSTOM_METHODOLOGY,
    LABEL_PRODUCTION_READY,
    PROMOTION_LABELS,
    LABEL_USER_WAIVED_THEORY,
    LABEL_USER_WAIVED_VALIDATION,
    STRONG_LABELS,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from ..lineage.spine_gate import evaluate_promotion
from ..llm.call_record import (
    LLMCallRecord,
    LLMRecordError,
    assert_no_plaintext_secret,
    assert_record_admissible,
    verify_record_seal,
)
from ..verification.schema import VerdictRecord
from .mock_honesty import (
    GRADE_PRODUCTION,
    MODE_LIVE,
    ExecutionBlock,
    check_execution_blocks,
)

# —— 门 id（投影/测试据此精确断言抓到哪条门·非泛绿）——
GATE_MOCK_HONESTY = "gate_mock_honesty"
GATE_DATASET_VERSION = "gate_dataset_version"
GATE_SPINE_CONSISTENCY = "gate_spine_consistency"
GATE_METHODOLOGY_CHOICE = "gate_methodology_choice"
GATE_LLM_GATEWAY = "gate_llm_gateway"
GATE_VERIFIER = "gate_verifier"
GATE_APPROVAL = "gate_approval"
GATE_RDP = "gate_rdp"

# user-waived 触发标签（§16 ⑥）：用户【明确选择跳过/放宽】严格路径的三个标签。
# 刻意不含 LABEL_EXPLORATORY —— 它是默认诚实弱标签，非「用户 waiver」，否则会误伤探索态。
USER_WAIVED_LABELS = frozenset(
    {LABEL_USER_WAIVED_THEORY, LABEL_USER_WAIVED_VALIDATION, LABEL_CUSTOM_METHODOLOGY}
)


def _clean(s: object) -> str:
    """非空白字符串视图（None / 非串 / 纯空白 → ""）。"""

    return s.strip() if isinstance(s, str) and s.strip() else ""


# ════════════════════════════════════════════════════════════════════════════
# 裁定结构（镜像 rdp_gate.RDPGateOutcome / RDPValidation 范式 · 保持账面一致）
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ReleaseGateOutcome:
    """单条工程标准门的裁定。`passed=False` + `missing` 列缺了哪些 + `reason` 诚实说明。"""

    gate_id: str
    passed: bool
    missing: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "missing": list(self.missing),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReleaseValidation:
    """一次发版核查的聚合结果（不抛异常的结构化面·供调用方读/投影）。

    `ok` 只由【硬门】裁定（任一 passed=False → 不可发版）；`honest_gaps` 是【软披露】——§16 列了
    但单一源不硬拒的项（如 cost 未记 / 封印来路未验），surface 但不挡发版（与硬门正交并存）。
    """

    ok: bool
    outcomes: tuple[ReleaseGateOutcome, ...]
    honest_gaps: tuple[str, ...] = ()

    @property
    def rejections(self) -> tuple[ReleaseGateOutcome, ...]:
        return tuple(o for o in self.outcomes if not o.passed)

    @property
    def missing(self) -> tuple[str, ...]:
        out: list[str] = []
        for o in self.rejections:
            out.extend(o.missing)
        return tuple(out)

    @property
    def reason_text(self) -> str:
        if self.ok:
            return "发版候选过全部已运行的工程标准门（§16）"
        return "；".join(f"[{o.gate_id}] {o.reason}" for o in self.rejections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "rejections": [o.to_dict() for o in self.rejections],
            "honest_gaps": list(self.honest_gaps),
            "reason_text": self.reason_text,
        }


class ReleaseRejected(Exception):
    """发版候选未过工程标准门：缺标准 / 状态非法。携带结构化 `validation` 供调用方读缺口。"""

    def __init__(self, validation: ReleaseValidation) -> None:
        self.validation = validation
        super().__init__(validation.reason_text)


# ════════════════════════════════════════════════════════════════════════════
# 发版候选（一份「待发版/晋级」的治理工件束·喂给 release gate）
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ReleaseCandidate:
    """一份发版/晋级候选的治理证据束。全字段默认空 → 部分候选也能核（相关门才触发）。

    `requested_label` 是 spine 升级标签（draft/exploratory/.../proof_backed/production_ready），
    驱动哪些门触发：强标签 → 触发 spine 一致性门；user-waived 标签 → 触发 MCR 门。
    """

    asset_ref: str
    asset_kind: str = ""
    requested_label: str = ""

    # —— §16 ①② Mock 诚实 ——
    execution_blocks: tuple[ExecutionBlock, ...] = ()

    # —— §16 ③ dataset_version + checksum（duck-typed：DatasetVersion 或 DatasetVersionRef）——
    dataset_versions: tuple[Any, ...] = ()

    # —— §16 ④⑤ spine（TIB / CC）+ ⑥ MCR：收编 spine_gate.evaluate_promotion ——
    artifact: MathematicalArtifact | None = None
    binding: TheoryImplementationBinding | None = None
    consistency_checks: tuple[ConsistencyCheck, ...] = ()
    methodology_choice: MethodologyChoiceRecord | None = None
    user_waived: bool = False
    current_code_hash: str | None = None
    data_contract: Mapping[str, Any] | None = None

    # —— §16 ⑦ LLM Gateway ——
    llm_used: bool | None = None              # None=由 records/provider 推断
    llm_call_records: tuple[LLMCallRecord, ...] = ()
    gateway_secret: bytes | None = None       # 给则验每条账封印（证明 Gateway 铸出）
    known_secrets: tuple[str, ...] = ()       # 给则扫明文 secret 泄露（撞即停）

    # —— 附·聚合已建证据（给则核·缺则软披露）——
    verifier_verdict: VerdictRecord | None = None
    approval: ApprovalGate | None = None
    rdp: RDPManifest | None = None
    promotion: PromotionClaim | None = None

    def __post_init__(self) -> None:
        if self.requested_label and self.requested_label not in PROMOTION_LABELS:
            raise ValueError(
                f"requested_label must be one of {sorted(PROMOTION_LABELS)}"
            )

    @property
    def is_strong_label(self) -> bool:
        return self.requested_label in STRONG_LABELS

    @property
    def is_user_waived(self) -> bool:
        """是否走了「用户放宽/跳过严格路径」（§16 ⑥ 触发条件）。"""

        return (
            self.user_waived
            or self.requested_label in USER_WAIVED_LABELS
            or bool(self.methodology_choice and self.methodology_choice.is_waiver)
        )


# ════════════════════════════════════════════════════════════════════════════
# §16 工程标准门（逐条·收编已建门 / 新建缺口门）
# ════════════════════════════════════════════════════════════════════════════
def gate_mock_honesty(
    blocks: Sequence[ExecutionBlock],
    *,
    requested_label: str = "",
) -> ReleaseGateOutcome:
    """§16 ①② no silent mock fallback / no template false success（委派新建 mock_honesty 原语）。"""

    violations = check_execution_blocks(tuple(blocks))
    if violations:
        missing = tuple(f"{v.block_id}:{v.code}" for v in violations)
        reason = "；".join(f"[{v.block_id}] {v.reason}" for v in violations)
        return ReleaseGateOutcome(GATE_MOCK_HONESTY, False, missing, reason)
    if requested_label == LABEL_PRODUCTION_READY and not any(
        block.mode == MODE_LIVE and block.result_grade == GRADE_PRODUCTION
        for block in blocks
    ):
        return ReleaseGateOutcome(
            GATE_MOCK_HONESTY,
            False,
            ("production_ready:live_production_execution_block",),
            (
                "requested_label='production_ready' requires at least one "
                "live execution block consumed as a production result"
            ),
        )
    return ReleaseGateOutcome(
        GATE_MOCK_HONESTY, True, reason=f"{len(blocks)} 个执行块均过 Mock 诚实核查"
    )


def _dataset_identity(dv: Any) -> tuple[str, str, str]:
    """从 DatasetVersion(data_quality) 或 DatasetVersionRef(delivery) duck-type 取 (id, version, checksum)。

    DatasetVersion: dataset_id / version_id / sha256；DatasetVersionRef: dataset_id / version / manifest_sha256。
    收编只读·不 import 二者（DatasetVersion 拉 polars·重）——按属性名取，缺则空串。
    """

    dataset_id = _clean(getattr(dv, "dataset_id", ""))
    version = getattr(dv, "version_id", None)
    version = _clean(version if version is not None else getattr(dv, "version", ""))
    checksum = getattr(dv, "sha256", None)
    checksum = _clean(checksum if checksum is not None else getattr(dv, "manifest_sha256", ""))
    return dataset_id, version, checksum


def gate_dataset_version(dataset_versions: Sequence[Any]) -> ReleaseGateOutcome:
    """§16 ③ dataset_version + checksum：每个登记的数据集引用须带【非空 version + 非空 checksum】。

    收编 DatasetVersion / DatasetVersionRef 身份（duck-typed）。空 version / 空 sha256 = 未追踪数据 →
    拒（§16 致命：数据更新缺 dataset_version / checksum）。不强制 ≥1（无外部数据的纯产物合法·≥1 由
    RDP gate_dataset_lineage 在 §17 层管）。
    """

    missing: list[str] = []
    reasons: list[str] = []
    for i, dv in enumerate(dataset_versions):
        dataset_id, version, checksum = _dataset_identity(dv)
        tag = dataset_id or f"#{i}"
        if not version:
            missing.append(f"{tag}:dataset_version")
            reasons.append(f"数据集 {tag} 缺 dataset_version → 拒（§16：dataset_version 必在场）")
        if not checksum:
            missing.append(f"{tag}:checksum")
            reasons.append(f"数据集 {tag} 缺 checksum → 拒（§16：checksum 必在场·未追踪数据不得发版）")
    if missing:
        return ReleaseGateOutcome(GATE_DATASET_VERSION, False, tuple(missing), "；".join(reasons))
    return ReleaseGateOutcome(
        GATE_DATASET_VERSION, True,
        reason=f"{len(dataset_versions)} 个数据集引用均带 dataset_version + checksum",
    )


def gate_spine_consistency(candidate: ReleaseCandidate) -> ReleaseGateOutcome:
    """§16 ④ TIB required for proof-backed + ⑤ ConsistencyCheck required before theory promotion。

    【委派】`spine_gate.evaluate_promotion`（不另写一致性判定·单一源）。仅强标签
    （evidence_sufficient/proof_backed/production_ready）触发；弱标签无强证据义务 → 直接过。
    `evaluate_promotion` 的 binding-exists 子句兑现 §16 ④（缺 TIB → 拒）、consistency-present 子句
    兑现 §16 ⑤（缺决定性 ConsistencyCheck → 拒）。
    """

    label = candidate.requested_label
    if not candidate.is_strong_label:
        return ReleaseGateOutcome(
            GATE_SPINE_CONSISTENCY, True,
            reason=f"requested_label={label!r} 非强标签 → 无 TIB/ConsistencyCheck 强证据义务（§16 ④⑤ 不触发）",
        )
    decision = evaluate_promotion(
        candidate.artifact,
        candidate.binding,
        candidate.consistency_checks,
        requested_label=label,
        current_code_hash=candidate.current_code_hash,
        choice=candidate.methodology_choice,
        data_contract=candidate.data_contract,
    )
    if decision.promotable:
        return ReleaseGateOutcome(GATE_SPINE_CONSISTENCY, True, reason=decision.verdict_text)
    return ReleaseGateOutcome(
        GATE_SPINE_CONSISTENCY, False, decision.violations,
        f"spine 一致性门拒升级到 {label!r}：{'；'.join(decision.violations)}"
        f"（§16 ④TIB/⑤ConsistencyCheck）→ 拒发版",
    )


def gate_methodology_choice(candidate: ReleaseCandidate) -> ReleaseGateOutcome:
    """§16 ⑥ MethodologyChoiceRecord required for user-waived paths（新建 presence 门）。

    为何新建而非靠 evaluate_promotion：后者只在 waiver【在场】时拿 MCR 判 proof-honest，**不**强制
    「user-waived 路径必须有 MCR」——故 user-waived 标签 + MCR 缺会从一致性门静默漏过。本门补这条：
    user-waived 路径缺 MCR → 拒（卡可证伪验收③）；给了也须 is_waiver + 绑本资产 + 有责任边界
    （否则 §16 致命「user waiver 被展示成系统强证据」）。
    """

    if not candidate.is_user_waived:
        return ReleaseGateOutcome(
            GATE_METHODOLOGY_CHOICE, True,
            reason=f"requested_label={candidate.requested_label!r} 非 user-waived 路径（§16 ⑥ 不触发）",
        )
    mcr = candidate.methodology_choice
    if mcr is None:
        return ReleaseGateOutcome(
            GATE_METHODOLOGY_CHOICE, False, ("methodology_choice",),
            "user-waived 路径缺 MethodologyChoiceRecord → 拒"
            "（§16：MethodologyChoiceRecord required for user-waived paths）",
        )
    missing: list[str] = []
    reasons: list[str] = []
    if not mcr.is_waiver:
        missing.append("methodology_choice.is_waiver")
        reasons.append("提供的 MethodologyChoiceRecord 非 waiver（chosen_path 非放权标签且无 skipped_steps）")
    if candidate.asset_ref and _clean(mcr.asset_ref) and _clean(mcr.asset_ref) != candidate.asset_ref:
        missing.append("methodology_choice.asset_ref")
        reasons.append(
            f"MethodologyChoiceRecord 绑的资产({mcr.asset_ref}) ≠ 本资产({candidate.asset_ref}) → 张冠李戴"
        )
    if not _clean(mcr.responsibility_boundary):
        missing.append("methodology_choice.responsibility_boundary")
        reasons.append(
            "MethodologyChoiceRecord 缺 responsibility_boundary → 拒"
            "（§16 致命：user waiver 不得被展示成系统强证据·须记责任边界）"
        )
    if missing:
        return ReleaseGateOutcome(GATE_METHODOLOGY_CHOICE, False, tuple(missing), "；".join(reasons))
    return ReleaseGateOutcome(
        GATE_METHODOLOGY_CHOICE, True,
        reason=f"user-waived 路径已附有效 MethodologyChoiceRecord（choice_id={mcr.choice_id}）",
    )


def gate_llm_gateway(candidate: ReleaseCandidate) -> ReleaseGateOutcome:
    """§16 ⑦ LLM Gateway enforced + provider/model/auth_ref/replay logged（收编 call_record 门）。

    硬拒：① 声明用 LLM 但无 LLMCallRecord（无调用账=未经 Gateway）→ 拒。② 任一账缺必填四要素
    （复用单一源 `assert_record_admissible`）→ 拒。③ 给了 `gateway_secret` 而某账封印验不过（绕过
    Gateway 自造账）→ 拒。安全闸：给了 `known_secrets` 而明文进账 → raise SecretLeakError（撞即停）。

    软披露（不硬拒·见 collect_honest_gaps）：未给 gateway_secret（封印来路未验）/ cost 未记。
    """

    records = candidate.llm_call_records

    # 安全闸（北极星·撞即停工报告）：明文 secret 进任一账序列化面 → raise（绝不回显 secret）。
    if candidate.known_secrets and records:
        for rec in records:
            assert_no_plaintext_secret(rec, candidate.known_secrets)

    llm_used = candidate.llm_used if candidate.llm_used is not None else bool(records)
    if not llm_used:
        return ReleaseGateOutcome(GATE_LLM_GATEWAY, True, reason="本发版未用 LLM（§16 ⑦ 不触发）")
    if not records:
        return ReleaseGateOutcome(
            GATE_LLM_GATEWAY, False, ("llm_call_records",),
            "声明用了 LLM 但无 LLMCallRecord → 拒（§16：LLM Gateway enforced·无调用账=未经 Gateway/无审计）",
        )

    missing: list[str] = []
    reasons: list[str] = []
    for i, rec in enumerate(records):
        tag = (_clean(rec.call_id) or f"#{i}")[:16]
        try:
            assert_record_admissible(rec)  # 复用单一源必填四要素（provider/model/auth_ref/replay_state）
        except LLMRecordError as e:
            missing.append(f"record[{tag}]:admissible")
            reasons.append(str(e))
        if candidate.gateway_secret is not None and not verify_record_seal(rec, candidate.gateway_secret):
            missing.append(f"record[{tag}]:seal")
            reasons.append(
                f"record[{tag}] 封印验不过 gateway_secret → 拒"
                "（§16/§7：绕过 LLM Gateway 自造账不可准入）"
            )
    if missing:
        return ReleaseGateOutcome(GATE_LLM_GATEWAY, False, tuple(missing), "；".join(reasons))
    sealed = "且封印验真" if candidate.gateway_secret is not None else "（封印来路未验·见 honest_gaps）"
    return ReleaseGateOutcome(
        GATE_LLM_GATEWAY, True, reason=f"{len(records)} 条 LLMCallRecord 均过准入门{sealed}"
    )


def gate_verifier(candidate: ReleaseCandidate) -> ReleaseGateOutcome:
    """附·收编 Verifier 裁决：给了 VerdictRecord 且 verdict=blocked（异模型不一致）→ 拒发版。"""

    v = candidate.verifier_verdict
    if v is None:
        return ReleaseGateOutcome(GATE_VERIFIER, True, reason="未提供 Verifier 裁决（不强制·软披露见 honest_gaps）")
    if candidate.asset_ref and _clean(v.target_ref) and _clean(v.target_ref) != candidate.asset_ref:
        return ReleaseGateOutcome(
            GATE_VERIFIER, False, ("verifier_verdict.target_ref",),
            f"Verifier 裁决 target_ref({v.target_ref}) ≠ 本资产({candidate.asset_ref}) → 拒（张冠李戴）",
        )
    if v.verdict == "blocked":
        return ReleaseGateOutcome(
            GATE_VERIFIER, False, ("verifier_verdict",),
            f"Verifier 裁决 blocked（异模型不一致·不取均值）→ 拒发版：{v.notes}",
        )
    return ReleaseGateOutcome(GATE_VERIFIER, True, reason=f"Verifier 裁决={v.verdict}")


def gate_approval(candidate: ReleaseCandidate) -> ReleaseGateOutcome:
    """附·收编 ApprovalGate：给了审批门且 decision≠approved（pending/rejected/timed_out）→ 拒发版。"""

    a = candidate.approval
    if a is None:
        return ReleaseGateOutcome(GATE_APPROVAL, True, reason="未提供 ApprovalGate（不强制·软披露见 honest_gaps）")
    if a.decision != "approved":
        return ReleaseGateOutcome(
            GATE_APPROVAL, False, ("approval.decision",),
            f"ApprovalGate decision={a.decision!r}（非 approved）→ 拒发版（未获批不得晋级）",
        )
    return ReleaseGateOutcome(GATE_APPROVAL, True, reason="ApprovalGate=approved")


def gate_rdp(candidate: ReleaseCandidate) -> ReleaseGateOutcome:
    """附·收编 §17 RDP 四门：给了 RDPManifest 则委派 `validate_rdp`，未过 → 拒发版。"""

    rdp = candidate.rdp
    if rdp is None:
        return ReleaseGateOutcome(
            GATE_RDP, True, reason="未提供 RDP（§17 全量强制待中心/聚合器·软披露见 honest_gaps）"
        )
    validation = validate_rdp(rdp, promotion=candidate.promotion)
    if validation.ok:
        return ReleaseGateOutcome(GATE_RDP, True, reason="RDP 过 §17 全部已跑门")
    return ReleaseGateOutcome(
        GATE_RDP, False, validation.missing, f"RDP 未过 §17 拒绝门：{validation.reason_text}"
    )


# ── 软披露：§16 列了但单一源不硬拒的项（surface 不挡发版·与硬门正交）────────────────
def collect_honest_gaps(candidate: ReleaseCandidate) -> tuple[str, ...]:
    """诚实软披露：non-blocking 但绝不美化吞掉（北极星·no template false success 的反面就是诚实surface）。"""

    gaps: list[str] = []
    records = candidate.llm_call_records
    if records:
        if candidate.gateway_secret is None:
            gaps.append(
                "llm:gateway_provenance_unverified（未给 gateway_secret·无法证明账由 Gateway 铸出·软披露不硬拒）"
            )
        for i, rec in enumerate(records):
            if not rec.usage:
                tag = (_clean(rec.call_id) or f"#{i}")[:16]
                gaps.append(
                    f"llm:record[{tag}]:cost_unlogged（§16 列 cost 但单一源准入门不含·provider 可能未返 usage·软披露）"
                )
    if candidate.is_strong_label and candidate.verifier_verdict is None:
        gaps.append("verifier:missing_for_strong_label（强标签未附 Verifier 裁决·§16 不硬拒·软披露）")
    if (
        candidate.verifier_verdict is not None
        and candidate.verifier_verdict.verdict == "concern"
    ):
        gaps.append("verifier:concern（裁决存疑·非 blocked 不挡发版·但须 surface）")
    if candidate.is_strong_label and candidate.approval is None:
        gaps.append("approval:missing_for_strong_label（强标签未附 ApprovalGate·软披露）")
    if candidate.is_strong_label and candidate.rdp is None:
        gaps.append("rdp:missing_for_strong_label（§17 全量强制待中心·软披露）")
    return tuple(gaps)


# ════════════════════════════════════════════════════════════════════════════
# 聚合入口：跑全部门 + 软披露
# ════════════════════════════════════════════════════════════════════════════
def evaluate_release(candidate: ReleaseCandidate) -> ReleaseValidation:
    """对发版候选跑 §16 全部工程标准门，返结构化结果（不抛门拒·结构化）。

    `ok = 全部硬门 passed`。任一标准缺 → 对应门 passed=False → ok=False（不可发版）。
    安全红线（明文 secret 进账）走 raise（SecretLeakError·不在此吞）——撞即停工报告。
    """

    outcomes = (
        gate_mock_honesty(
            candidate.execution_blocks,
            requested_label=candidate.requested_label,
        ),
        gate_dataset_version(candidate.dataset_versions),
        gate_spine_consistency(candidate),
        gate_methodology_choice(candidate),
        gate_llm_gateway(candidate),       # 内含安全闸（明文 secret → raise）
        gate_verifier(candidate),
        gate_approval(candidate),
        gate_rdp(candidate),
    )
    ok = all(o.passed for o in outcomes)
    return ReleaseValidation(ok=ok, outcomes=outcomes, honest_gaps=collect_honest_gaps(candidate))


def require_releasable(candidate: ReleaseCandidate) -> ReleaseCandidate:
    """核查并在未过工程标准门时 raise ReleaseRejected（带结构化缺口）。过 → 原样返回。

    这是「发版即核查」入口：晋级/上线之前调这一脚——任一 §16 标准缺即【真拒】，绝不静默放行。
    安全红线（明文 secret 进账）走 SecretLeakError（更严于发版拒·撞即停工报告）。
    """

    v = evaluate_release(candidate)
    if not v.ok:
        raise ReleaseRejected(v)
    return candidate


__all__ = [
    "GATE_MOCK_HONESTY",
    "GATE_DATASET_VERSION",
    "GATE_SPINE_CONSISTENCY",
    "GATE_METHODOLOGY_CHOICE",
    "GATE_LLM_GATEWAY",
    "GATE_VERIFIER",
    "GATE_APPROVAL",
    "GATE_RDP",
    "USER_WAIVED_LABELS",
    "ReleaseGateOutcome",
    "ReleaseValidation",
    "ReleaseRejected",
    "ReleaseCandidate",
    "gate_mock_honesty",
    "gate_dataset_version",
    "gate_spine_consistency",
    "gate_methodology_choice",
    "gate_llm_gateway",
    "gate_verifier",
    "gate_approval",
    "gate_rdp",
    "collect_honest_gaps",
    "evaluate_release",
    "require_releasable",
]
