"""RDP 4 条拒绝门（GOAL §17 可证伪验收 · 北极星总闸）。

§17 行 2069-2076 的 4 条「→ 拒」是正式研究交付的硬闸。本模块把它们落成**真能拒**的纯逻辑门：
缺字段【真拒】（raise / outcome.passed=False），绝不静默填默认放行（诚实纪律 RULES §3）。

  门1 manifest 完整性：缺 manifest 身份 / artifact hash / reproducibility command → 拒。
  门2 数据血统：缺 DatasetVersion 或 IngestionSkill 引用 → 拒。
  门3 未验证残余：缺「未验证残余」声明 → 拒（诚实闸：未声明残余的交付不完整）。
  门4 晋级可追溯：晋级资产追不到一份**关于本资产**的有效 RDP → 拒。

门的对抗契约（RULES §2「种已知坏门必抓」）：每条门配「去掉对应必填字段 → 必拒」的探针；
若有人把门改弱（放过缺字段），对抗测试 `test_rdp_gate.py` 立刻红。门若是纸做的，测试抓不住。

诚实边界：门4 只是纯追溯逻辑门，**未**接进真实 ApprovalGateService / paper.PromotionGate 的晋级
路径（那是 follow-on，诚实标 P2）。但门本身真能拒——给它残缺/错配的追溯断言即返拒。
"""

from __future__ import annotations

from dataclasses import dataclass

from .rdp import PromotionClaim, RDPManifest

GATE_MANIFEST = "gate1_manifest_completeness"
GATE_DATASET_LINEAGE = "gate2_dataset_lineage"
GATE_UNVERIFIED_RESIDUAL = "gate3_unverified_residual"
GATE_PROMOTION_TRACEABILITY = "gate4_promotion_traceability"


def _blank(s: object) -> bool:
    """字符串视角的「缺」：None / 空 / 纯空白都算缺（不当有效值放行）。"""

    return not isinstance(s, str) or not s.strip()


@dataclass(frozen=True)
class RDPGateOutcome:
    """单条门的裁定。`passed=False` + `missing` 列缺了哪些必填项 + `reason` 诚实说明。"""

    gate_id: str
    passed: bool
    missing: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class RDPValidation:
    """一次 RDP 校验的聚合结果（不抛异常的结构化面，供调用方读 / 投影）。"""

    ok: bool
    outcomes: tuple[RDPGateOutcome, ...]

    @property
    def rejections(self) -> tuple[RDPGateOutcome, ...]:
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
            return "RDP 通过全部已运行的拒绝门"
        return "；".join(f"[{o.gate_id}] {o.reason}" for o in self.rejections)


class RDPRejected(Exception):
    """RDP 未过拒绝门：缺必填字段 / 追溯断裂。携带结构化 `validation` 供调用方读缺口。"""

    def __init__(self, validation: RDPValidation) -> None:
        self.validation = validation
        super().__init__(validation.reason_text)


# ── 门1：manifest 完整性（§17：缺 manifest / artifact hash / reproducibility command → 拒）──
def gate_manifest_completeness(rdp: RDPManifest) -> RDPGateOutcome:
    missing: list[str] = []
    if _blank(rdp.asset_ref):
        missing.append("asset_ref")        # manifest 身份：这份交付描述的是哪个资产
    if _blank(rdp.rdp_id):
        missing.append("rdp_id")           # 内容寻址身份（正常由 __post_init__ 填；空 = 异常）
    if _blank(rdp.schema_version):
        missing.append("schema_version")
    if _blank(rdp.artifact_hash):
        missing.append("artifact_hash")    # §17 行 2072
    if _blank(rdp.reproducibility_command):
        missing.append("reproducibility_command")  # §17 行 2072
    if missing:
        return RDPGateOutcome(
            GATE_MANIFEST, False, tuple(missing),
            f"缺 manifest 必填项 {missing} → 拒（§17：manifest / artifact hash / reproducibility command 任缺即拒）",
        )
    return RDPGateOutcome(GATE_MANIFEST, True)


# ── 门2：数据血统（§17：缺 DatasetVersion 或 IngestionSkill 引用 → 拒）──────────────
def gate_dataset_lineage(rdp: RDPManifest) -> RDPGateOutcome:
    missing: list[str] = []
    resolvable_dvs = [dv for dv in rdp.dataset_versions if dv.is_resolvable]
    if not resolvable_dvs:
        # 空 list 或全是空壳引用（dataset_id/version 空）都算缺有效 DatasetVersion。
        missing.append("dataset_versions")
    skills = [s for s in rdp.ingestion_skill_refs if isinstance(s, str) and s.strip()]
    if not skills:
        missing.append("ingestion_skill_refs")
    if missing:
        return RDPGateOutcome(
            GATE_DATASET_LINEAGE, False, tuple(missing),
            f"缺数据血统引用 {missing} → 拒（§17：缺 DatasetVersion 或 IngestionSkill 引用即拒；空壳引用不算）",
        )
    return RDPGateOutcome(GATE_DATASET_LINEAGE, True)


# ── 门3：未验证残余（§17：缺「未验证残余」→ 拒。诚实闸：未声明残余的交付不完整）────
def gate_unverified_residual(rdp: RDPManifest) -> RDPGateOutcome:
    residual = rdp.unverified_residual
    if residual is None:
        # 压根没声明 = 忘了想残余 → 拒。
        return RDPGateOutcome(
            GATE_UNVERIFIED_RESIDUAL, False, ("unverified_residual",),
            "未声明未验证残余（unverified_residual=None）→ 拒（诚实闸：未声明残余的交付不完整）",
        )
    if len(residual) == 0 and _blank(rdp.residual_attestation):
        # 显式声明「零残余」却无署名审查记录 → 拒（claim 完美须可归因）。
        return RDPGateOutcome(
            GATE_UNVERIFIED_RESIDUAL, False, ("residual_attestation",),
            "声明零未验证残余但缺 residual_attestation → 拒（claim 无残余须有署名审查，不可空口）",
        )
    return RDPGateOutcome(GATE_UNVERIFIED_RESIDUAL, True)


# ── 门4：晋级可追溯（§17：晋级资产追不到 RDP → 拒；promotion 须带 RDP ref）────────────
def gate_promotion_traceability(
    promotion: PromotionClaim, rdp: RDPManifest | None
) -> RDPGateOutcome:
    if rdp is None:
        return RDPGateOutcome(
            GATE_PROMOTION_TRACEABILITY, False, ("rdp",),
            "晋级断言无任何 RDP 可追溯 → 拒",
        )
    if _blank(promotion.rdp_ref):
        return RDPGateOutcome(
            GATE_PROMOTION_TRACEABILITY, False, ("rdp_ref",),
            "晋级断言缺 rdp_ref → 拒（§17：promotion 须带 RDP ref）",
        )
    if promotion.rdp_ref != rdp.rdp_id:
        return RDPGateOutcome(
            GATE_PROMOTION_TRACEABILITY, False, ("rdp_ref",),
            f"rdp_ref({promotion.rdp_ref}) 解析不到提供的 RDP({rdp.rdp_id}) → 拒（追溯断裂）",
        )
    if promotion.asset_ref != rdp.asset_ref:
        return RDPGateOutcome(
            GATE_PROMOTION_TRACEABILITY, False, ("asset_ref",),
            f"RDP 描述的资产({rdp.asset_ref}) ≠ 被晋级资产({promotion.asset_ref}) → 拒（张冠李戴）",
        )
    # 追溯到的 RDP 本身必须是有效交付——追到一份残缺 RDP 不算可追溯。
    inner = validate_rdp(rdp)
    if not inner.ok:
        return RDPGateOutcome(
            GATE_PROMOTION_TRACEABILITY, False, inner.missing,
            f"被追溯的 RDP 本身未过门 → 拒：{inner.reason_text}",
        )
    return RDPGateOutcome(GATE_PROMOTION_TRACEABILITY, True)


def validate_rdp(
    rdp: RDPManifest, *, promotion: PromotionClaim | None = None
) -> RDPValidation:
    """跑门1-3（恒）+ 门4（仅当给 promotion）。返结构化结果，不抛。

    缺字段 → 对应门 passed=False；整体 ok = 全部已跑门通过。
    """

    outcomes = [
        gate_manifest_completeness(rdp),
        gate_dataset_lineage(rdp),
        gate_unverified_residual(rdp),
    ]
    if promotion is not None:
        outcomes.append(gate_promotion_traceability(promotion, rdp))
    ok = all(o.passed for o in outcomes)
    return RDPValidation(ok=ok, outcomes=tuple(outcomes))


def require_valid_rdp(
    rdp: RDPManifest, *, promotion: PromotionClaim | None = None
) -> RDPManifest:
    """校验并在未过门时 raise RDPRejected（带结构化缺口）。过 → 原样返回。"""

    v = validate_rdp(rdp, promotion=promotion)
    if not v.ok:
        raise RDPRejected(v)
    return rdp


def assemble_rdp(**fields: object) -> RDPManifest:
    """组装一份 RDP 并即时过门1-3——缺必填字段【真拒】（raise RDPRejected），绝不静默放行。

    这是「装配即校验」入口：半成品别想冒充正式交付。门4（晋级追溯）是另一关注点，
    用 `require_valid_rdp(rdp, promotion=...)` 单独跑。
    """

    rdp = RDPManifest(**fields)  # type: ignore[arg-type]
    return require_valid_rdp(rdp)


__all__ = [
    "GATE_MANIFEST",
    "GATE_DATASET_LINEAGE",
    "GATE_UNVERIFIED_RESIDUAL",
    "GATE_PROMOTION_TRACEABILITY",
    "RDPGateOutcome",
    "RDPValidation",
    "RDPRejected",
    "gate_manifest_completeness",
    "gate_dataset_lineage",
    "gate_unverified_residual",
    "gate_promotion_traceability",
    "validate_rdp",
    "require_valid_rdp",
    "assemble_rdp",
]
