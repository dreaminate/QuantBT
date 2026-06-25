"""RDP 聚合器——从**真血统**装配 Research Delivery Package（GOAL §17 · 卡 D-RDP-2）。

D-RDP-1 建了 RDP schema（`rdp.py`）+ §17 四拒绝门（`rdp_gate.py`）。本模块**只**做一件事：
把真血统对象（DatasetVersion / LLMCallRecord / Ledger honest-N / VerdictRecord / ApprovalGate）
映射成一份**真 `RDPManifest`**，再喂 D-RDP-1 的门校验，返回结构化装配结果。

**扩展不替换**（RULES §4）：本模块不改 `rdp.py` schema / `rdp_gate.py` 门语义——只消费真对象、
产 string ref、调既有 `validate_rdp`。门怎么拒、拒什么，全权在 D-RDP-1。

诚实纪律（RULES §3 · 北极星 correctness）：
- **单一身份源**：dataset ref 走 `DatasetVersion` 真身份（dataset_id/version_id/sha256）、honest_n 走
  `Ledger.honest_n` 真查询、call/verdict/approval ref 走各自真 id。**绝不另造**哈希族。artifact_hash
  缺时由 `lineage.ids.content_hash(artifact)` 派生（同一身份源），不自立第二套。
- **缺真血统 → 反映为缺，不美化**（no template false success）：声明用了 LLM 却没给 LLMCallRecord →
  `llm_call_record_refs` **留空** + honest_gaps 标 missing，**绝不**塞假 ref；没给 Ledger → honest_n
  留 `None`（**不补 0**）。篡改/替换真源 → 派生 ref 随之变（内容寻址），不静默填默认。
- **门强制不被绕过**：dataset/ingestion-skill/未验证残余/manifest 任缺 → 喂给 D-RDP-1 门即【真拒】。
  本模块不替门放行半成品；`context_fields` passthrough 也禁止覆盖聚合器管理的真血统字段（见下）。

安全红线（北极星 · 撞即停工报告）：
- **实盘 key 绝不进 RDP**：从 `LLMCallRecord` 只取 `call_id` / `provider` / `replay_state`——`auth_ref`
  本身是 SecretRef 引用（非明文），且本模块**根本不把 auth_ref 写进 RDP**。给 `known_secrets` 时，
  装配后扫描 RDP 的开放 JSON：命中任一明文 secret → raise `SecretLeakError`（复用 LLM Gateway 门2 的
  「已知明文逐字匹配」单一源 `scan_messages_for_secret`，绝不另写扫描器，报错绝不回显 secret 本身）。

诚实限界（不号称做到的）：
- `known_secrets` 扫描是「已知明文逐字匹配」防御（与 `llm.call_record.assert_no_plaintext_secret` 同口径），
  **不**号称识别任意未在册高熵串。
- TheorySpec / ResponsibilityDisclosureRecord 等命名对象全仓尚无类 → 经 `context_fields` 走 string ref
  passthrough，**不强造** typed 对象（GOAL §17 命名但未建即诚实保引用）。
- 本聚合器产 RDP + 跑门；**接进真 promote 端到端强制档**（`require_rdp=True` 常开）由用户拍
  （D-SCOPE-CONSERVATIVE：RDP 强制档等聚合器·常开仍待用户）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..lineage.ids import canonical_json, content_hash
# 复用 LLM Gateway 门2 的「已知明文 secret 扫描」单一源 + 泄露异常（绝不另写扫描器）。
# LLMCallRecord 现已建 → typed 引用（call_record.py 轻量·只依赖 lineage.ids）。
from ..llm.call_record import LLMCallRecord, SecretLeakError, scan_messages_for_secret
from .rdp import DatasetVersionRef, PromotionClaim, RDPManifest
from .rdp_gate import RDPRejected, RDPValidation, validate_rdp

if TYPE_CHECKING:
    # 真血统类型仅作注解（duck-typed 读真属性·不在 delivery 层运行时拉 polars/sqlite 等重依赖）。
    # 传进来的都是**真实例**——单一身份源不受「是否运行时 import 类」影响。
    from ..approval.schema import ApprovalGate
    from ..data_quality import DatasetVersion
    from ..lineage.ledger import Ledger
    from ..verification.schema import VerdictRecord


# ── honest_gaps 码（缺真血统的诚实披露·非门硬拒·测试据此断言「标 missing 不美化」）────────
GAP_LLM_RECORD_MISSING = (
    "llm_call_record_refs:声明用了 LLM 但未提供 LLMCallRecord——标 missing 不美化（§17·诚实）"
)
GAP_LLM_CALL_ID_BLANK = (
    "llm_call_record_refs:某 LLMCallRecord 的 call_id 为空（残缺账·跳过不补默认）"
)
GAP_HONEST_N_UNAVAILABLE = (
    "honest_n:未提供 Ledger——无法从真账查 honest-N（留 None·不补 0 美化）"
)
GAP_HONEST_N_NO_GOAL = (
    "honest_n:提供了 Ledger 但缺 honest_n_strategy_goal_ref——无法查（留 None）"
)
GAP_HONEST_N_ZERO = (
    "honest_n:Ledger 查得该主题 0 条记录试验——晋级前 honest-N=0 须披露"
)
GAP_VERDICT_MISSING = (
    "verifier_verdict_refs:无 Verifier 裁决记录（§17 契约携带·未填）"
)
GAP_APPROVAL_MISSING = (
    "approval_refs:无 Approval/promotion 记录（§17 契约携带·未填）"
)
GAP_INGESTION_SKILL_UNDERIVED = (
    "ingestion_skill_refs:DatasetVersion 无 ingestion_skill_version 且未显式提供——门2 将拒"
)


# 聚合器**管理**的 RDP 字段：这些由真血统派生，`context_fields` passthrough 禁止覆盖
# （防有人借 passthrough 绕过真装配、塞假 dataset/llm/honest_n 等）。
_AGGREGATOR_MANAGED = frozenset(
    {
        "asset_ref",
        "asset_kind",
        "rdp_id",
        "schema_version",
        "created_by",
        "created_at_utc",
        "dataset_versions",
        "ingestion_skill_refs",
        "data_source_refs",
        "llm_provider",
        "model_routing_policy_ref",
        "llm_call_record_refs",
        "replay_state",
        "honest_n",
        "honest_n_strategy_goal_ref",
        "verifier_verdict_refs",
        "approval_refs",
        "artifact_hash",
        "reproducibility_command",
        "unverified_residual",
        "residual_attestation",
        "known_limitations",
        "promotion_record",
    }
)


@dataclass(frozen=True)
class RDPAssembly:
    """一次聚合的结果：真 RDP + D-RDP-1 门校验结果 + 诚实缺口披露。

    `validation` 是 `rdp_gate.validate_rdp` 的原样产物（门由 D-RDP-1 把守，本模块不改其语义）。
    `honest_gaps` 是聚合器对**自身完整性**的诚实标注——§17 契约携带字段中缺真血统的项（如「声明用
    LLM 却无 LLMCallRecord」），**非**门硬拒、但绝不美化吞掉（与 4 门的硬拒正交并存）。
    """

    rdp: RDPManifest
    validation: RDPValidation
    honest_gaps: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """是否过 D-RDP-1 全部已跑门（honest_gaps 不影响门裁定——它是软披露）。"""

        return self.validation.ok

    def to_dict(self) -> dict[str, Any]:
        """开放格式投影：RDP 开放 JSON dict + 门裁定 + 诚实缺口（第三方可解析）。"""

        return {
            "rdp": self.rdp.to_dict(),
            "ok": self.ok,
            "validation": {
                "ok": self.validation.ok,
                "rejections": [
                    {"gate_id": o.gate_id, "missing": list(o.missing), "reason": o.reason}
                    for o in self.validation.rejections
                ],
            },
            "honest_gaps": list(self.honest_gaps),
        }


def _dedup(items: Iterable[str]) -> list[str]:
    """保序去重（refs 装配用——同一来源重复列入不该刷大引用集）。"""

    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _clean(s: object) -> str:
    """非空白字符串视图（None / 非串 / 纯空白 → ""）。"""

    return s.strip() if isinstance(s, str) and s.strip() else ""


def aggregate_rdp(
    *,
    asset_ref: str,
    asset_kind: str,
    # ── 真血统对象（真源·duck-typed 读真属性；LLMCallRecord 已 typed）──────────────
    dataset_versions: Sequence["DatasetVersion"] = (),
    llm_call_records: Sequence[LLMCallRecord] = (),
    ledger: "Ledger | None" = None,
    honest_n_strategy_goal_ref: str = "",
    verdicts: Sequence["VerdictRecord"] = (),
    approvals: Sequence["ApprovalGate"] = (),
    # ── 门1 必填（真值·不可造）─────────────────────────────────────────────────
    artifact: Any = None,                 # 给则 content_hash(artifact) 派生 artifact_hash（单一身份源）
    artifact_hash: str = "",
    reproducibility_command: str = "",
    # ── 门3 诚实闸（真值·不可造；None=未声明→门拒）──────────────────────────────
    unverified_residual: Sequence[str] | None = None,
    residual_attestation: str = "",
    # ── §17 契约携带（显式真填 / 由真血统派生 / passthrough）────────────────────
    ingestion_skill_refs: Sequence[str] = (),
    data_source_refs: Sequence[str] = (),
    llm_used: bool | None = None,         # 显式声明本研究是否用过 LLM（None=由 provider/records 推断）
    llm_provider: str = "",
    model_routing_policy_ref: str = "",
    replay_state: str = "",
    known_limitations: Sequence[str] = (),
    promotion_record: str = "",
    context_fields: Mapping[str, Any] | None = None,  # 其余 §17 RDP 字段（math/code/run/deploy 等）passthrough
    # ── 安全闸（北极星·撞即停）──────────────────────────────────────────────────
    known_secrets: Iterable[str] = (),
    # ── 装饰（不入 rdp_id 哈希）──────────────────────────────────────────────────
    created_by: str = "",
    created_at_utc: str = "",
    # ── 门4 可选晋级追溯（给 PromotionClaim 则并跑门4）──────────────────────────
    promotion: "PromotionClaim | None" = None,
) -> RDPAssembly:
    """从真血统装配 RDP 并喂 D-RDP-1 门校验，返回 `RDPAssembly`（不抛门拒·结构化）。

    映射真源 → RDP string ref：
      DatasetVersion → DatasetVersionRef(dataset_id, version_id, sha256) + 派生 ingestion_skill/source；
      LLMCallRecord  → llm_call_record_refs(call_id) + llm_provider + replay_state（**不含 auth_ref/明文**）；
      Ledger         → honest_n(strategy_goal_ref) 真查询（无 Ledger→None·不补 0）；
      VerdictRecord  → verifier_verdict_refs(verdict_id)；ApprovalGate → approval_refs(gate_id)。

    缺真血统 → honest_gaps 标 missing（不美化）；门强制字段缺 → D-RDP-1 门在 `validation` 里【真拒】。
    `known_secrets` 给出且明文进了 RDP 开放面 → raise `SecretLeakError`（实盘 key 不进 RDP）。
    """

    gaps: list[str] = []

    # ── DatasetVersion → DatasetVersionRef（真身份·不另造）+ 派生 ingestion_skill / source ──
    dv_refs = tuple(
        DatasetVersionRef(
            dataset_id=dv.dataset_id,
            version=dv.version_id,
            manifest_sha256=_clean(dv.sha256),
        )
        for dv in dataset_versions
    )
    derived_skills = [_clean(dv.ingestion_skill_version) for dv in dataset_versions]
    all_skills = tuple(_dedup(_clean(s) for s in (*ingestion_skill_refs, *derived_skills) if _clean(s)))
    if not all_skills:
        gaps.append(GAP_INGESTION_SKILL_UNDERIVED)

    derived_sources: list[str] = []
    for dv in dataset_versions:
        if _clean(dv.source_name):
            derived_sources.append(_clean(dv.source_name))
        if _clean(dv.source_ref):
            derived_sources.append(_clean(dv.source_ref))
    all_sources = tuple(_dedup(_clean(s) for s in (*data_source_refs, *derived_sources) if _clean(s)))

    # ── LLMCallRecord → refs + provider + replay_state（绝不取 auth_ref/明文）──────────
    call_refs: list[str] = []
    for r in llm_call_records:
        cid = _clean(r.call_id)
        if cid:
            call_refs.append(cid)
        else:
            gaps.append(GAP_LLM_CALL_ID_BLANK)
    call_refs_t = tuple(_dedup(call_refs))

    if llm_call_records:
        rec_providers = _dedup(_clean(r.provider) for r in llm_call_records if _clean(r.provider))
        rec_states = _dedup(_clean(r.replay_state) for r in llm_call_records if _clean(r.replay_state))
        llm_provider_final = ",".join(rec_providers) if rec_providers else _clean(llm_provider)
        replay_state_final = ",".join(rec_states) if rec_states else _clean(replay_state)
    else:
        llm_provider_final = _clean(llm_provider)
        replay_state_final = _clean(replay_state)

    effective_llm_used = (
        llm_used if llm_used is not None else bool(_clean(llm_provider) or llm_call_records)
    )
    if effective_llm_used and not call_refs_t:
        # 用了 LLM 却无调用账 → 标 missing（不塞假 ref·不美化）。
        gaps.append(GAP_LLM_RECORD_MISSING)

    # ── Ledger → honest_n 真查询（无 Ledger→None·不补 0 美化）───────────────────────
    honest_n_val: int | None = None
    if ledger is None:
        gaps.append(GAP_HONEST_N_UNAVAILABLE)
    elif not _clean(honest_n_strategy_goal_ref):
        gaps.append(GAP_HONEST_N_NO_GOAL)
    else:
        honest_n_val = int(ledger.honest_n(honest_n_strategy_goal_ref))
        if honest_n_val == 0:
            gaps.append(GAP_HONEST_N_ZERO)

    # ── Verdict / Approval → refs ──────────────────────────────────────────────────
    verdict_refs = tuple(_dedup(_clean(v.verdict_id) for v in verdicts if _clean(v.verdict_id)))
    if not verdict_refs:
        gaps.append(GAP_VERDICT_MISSING)
    approval_refs = tuple(_dedup(_clean(a.gate_id) for a in approvals if _clean(a.gate_id)))
    if not approval_refs:
        gaps.append(GAP_APPROVAL_MISSING)

    # ── artifact_hash：显式优先；缺则由真 artifact 经单一身份源派生（不另造哈希族）────
    artifact_hash_final = _clean(artifact_hash)
    if not artifact_hash_final and artifact is not None:
        artifact_hash_final = content_hash(artifact)

    # ── 未验证残余：保留 None 哨兵（未声明→门3 拒）；显式 list → tuple ──────────────
    residual_final: tuple[str, ...] | None = (
        None if unverified_residual is None else tuple(unverified_residual)
    )

    # ── 装配字段 dict（聚合器管理项）────────────────────────────────────────────────
    fields: dict[str, Any] = {
        "asset_ref": asset_ref,
        "asset_kind": asset_kind,
        "created_by": created_by,
        "created_at_utc": created_at_utc,
        "dataset_versions": dv_refs,
        "ingestion_skill_refs": all_skills,
        "data_source_refs": all_sources,
        "llm_provider": llm_provider_final,
        "model_routing_policy_ref": _clean(model_routing_policy_ref),
        "llm_call_record_refs": call_refs_t,
        "replay_state": replay_state_final,
        "honest_n": honest_n_val,
        "honest_n_strategy_goal_ref": _clean(honest_n_strategy_goal_ref),
        "verifier_verdict_refs": verdict_refs,
        "approval_refs": approval_refs,
        "artifact_hash": artifact_hash_final,
        "reproducibility_command": reproducibility_command,
        "unverified_residual": residual_final,
        "residual_attestation": residual_attestation,
        "known_limitations": tuple(known_limitations),
        "promotion_record": promotion_record,
    }

    # ── context_fields passthrough（其余 §17 字段）：键须合法、且禁覆盖聚合器管理项 ──
    if context_fields:
        valid = set(RDPManifest.__dataclass_fields__)  # type: ignore[attr-defined]
        unknown = set(context_fields) - valid
        if unknown:
            raise ValueError(
                f"context_fields 含非 RDPManifest 字段 {sorted(unknown)}（防 typo 静默丢失）"
            )
        clobber = set(context_fields) & _AGGREGATOR_MANAGED
        if clobber:
            raise ValueError(
                f"context_fields 禁止覆盖聚合器管理的真血统字段 {sorted(clobber)}"
                "（防借 passthrough 绕过真装配塞假源）"
            )
        fields.update(context_fields)

    rdp = RDPManifest(**fields)

    # ── 安全闸：实盘 key 绝不进 RDP（给 known_secrets 时逐字扫开放 JSON·撞即停）──────
    secrets = [s for s in known_secrets if isinstance(s, str) and s]
    if secrets:
        blob = canonical_json(rdp.to_dict())
        hit = scan_messages_for_secret(blob, secrets)
        if hit is not None:
            # 绝不回显 secret 本身——只报字段族泄露 + 长度（与 LLM Gateway 门2 同口径）。
            raise SecretLeakError(
                f"明文 secret（len={len(hit)}）进入 RDP 开放序列化面——"
                "致命红线：实盘 key/secret 不进 RDP，只允许 auth_ref/SecretRef 引用"
            )

    validation = validate_rdp(rdp, promotion=promotion)
    return RDPAssembly(rdp=rdp, validation=validation, honest_gaps=tuple(gaps))


def require_aggregated_rdp(**kwargs: Any) -> RDPManifest:
    """聚合 + 强制过门：未过 D-RDP-1 门 → raise `RDPRejected`（带结构化缺口）。过 → 返真 RDP。

    参数同 `aggregate_rdp`。这是「装配即校验」的强制入口：半成品（缺 dataset/skill/残余/manifest）
    别想冒充正式交付。安全闸（`known_secrets`）在 `aggregate_rdp` 内先跑，明文泄露即 `SecretLeakError`。
    """

    assembly = aggregate_rdp(**kwargs)
    if not assembly.validation.ok:
        raise RDPRejected(assembly.validation)
    return assembly.rdp


__all__ = [
    "RDPAssembly",
    "GAP_LLM_RECORD_MISSING",
    "GAP_LLM_CALL_ID_BLANK",
    "GAP_HONEST_N_UNAVAILABLE",
    "GAP_HONEST_N_NO_GOAL",
    "GAP_HONEST_N_ZERO",
    "GAP_VERDICT_MISSING",
    "GAP_APPROVAL_MISSING",
    "GAP_INGESTION_SKILL_UNDERIVED",
    "aggregate_rdp",
    "require_aggregated_rdp",
]
