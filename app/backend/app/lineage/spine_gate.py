"""脊柱 · Mathematical Spine 一致性硬门（GOAL §6 可证伪验收 + §8 治理硬不变量）。

决策 D-MATH-SPINE：「理论正确但实现跑偏视为系统错误」。这道门是命门——任何声称
「按理论实现」的产物要升级到强标签（evidence_sufficient / proof_backed / production_ready），
必须过升级健全谓词 Π 的全部必需子句；任一失败 → 拒升级、降级到诚实标签、绝不冒充。

谓词与每条门为何必要：见 `dev/research/findings/dreaminate/spine-consistency-gate/00-*.md`。
8 子句逐条对 §6/§8 一条「→ 拒」：
  (1) binding-exists     §6 公式无 impl/test binding → 不得 promoted
  (2) binding-complete   §8 TIB ⇒ code_ref+config_ref+data_contract_ref
  (3) consistency-present §8 TIB ⇒ ConsistencyCheck（监控/执行称数学依据缺 CC → 拒）
  (4) consistency-pass   §6 代码实现与数学定义不一致 → 拒
  (5) fresh              §6 实现改动后未刷新 binding → 拒
  (6) proof-honest       §6 理论证明被 user 跳过但标 proof-backed → 拒
  (7) pit-bound          §6 estimator 未绑定 data timing/PIT → 拒
  (8) claim-grounded     §8 TheoryClaim ⇒ MathematicalArtifact exists

诚实边界（这道门**不**做什么）：它按「声明的 binding + ConsistencyCheck 结果 + 实现内容
指纹」判定「声明 vs 证据是否自洽 + 强度是否够」。它**不**自行证明 code 真的实现了
definition——那靠 ConsistencyCheck 的 numerical/symbolic 内容质量 + Verifier/Critic。
门绝不声称证明了任何下游数学命题（参 ids.py「绝不声称能去语义重」的同款诚实口径）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .spine import (
    ARTIFACT_DATA_TIMING,
    ARTIFACT_ESTIMATOR,
    ARTIFACT_STATISTICAL_TEST,
    CHECK_FAIL,
    CHECK_PENDING,
    LABEL_CHALLENGED,
    LABEL_DRAFT,
    LABEL_EXPLORATORY,
    PROOF_BACKED,
    PROOF_REQUIRING_LABELS,
    STRONG_LABELS,
    WAIVER_LABELS,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)

# estimator / 统计检验 / 数据时间语义：在未来信息上「一致」= look-ahead 泄露，撞红线。
PIT_REQUIRING_TYPES = frozenset(
    {ARTIFACT_ESTIMATOR, ARTIFACT_STATISTICAL_TEST, ARTIFACT_DATA_TIMING}
)

# 拒绝口径里绝不能出现的越权正向断言（防「不给小白假绿灯」原则反噬自身）。
# 注意：label token（如 proof_backed）允许在拒绝文里被「命名」，但不允许正向断言「已证明/证据充分/保证/可信」。
BANNED_POSITIVE_TERMS = (
    "已证明",
    "证据充分",
    "保证一致",
    "可信",
    "production-ready 达成",
    "evidence 充分",
)

DISCLOSURE = (
    "一致性门按声明的 TheoryImplementationBinding + ConsistencyCheck 结果 + 实现内容指纹判定，"
    "校验「声明 vs 证据自洽 + 标签强度匹配」；不自行证明数学命题，"
    "实现是否真的对仍依赖 ConsistencyCheck 内容质量与 Verifier/Critic。"
)


@dataclass(frozen=True)
class SpineDecision:
    """一致性门裁定（frozen，参 security/gate PolicyDecision 范式）。

    `allow_existence` 恒 True——脊柱不挡产物*存在*（P2 不挡探索 + D-MATH-SPINE 放权），
    只挡*越权标注*。`promotable` 才是「能否升级到请求的标签」。`granted_label` 是诚实可授标签。
    """

    requested_label: str
    granted_label: str
    promotable: bool
    allow_existence: bool
    violations: tuple[str, ...]
    matched_rules: tuple[str, ...]
    notes: tuple[str, ...]
    verdict_text: str
    disclosure: str = DISCLOSURE


def _granted_label(
    requested: str,
    promotable: bool,
    checks: list[ConsistencyCheck],
    binding: TheoryImplementationBinding | None,
    choice: MethodologyChoiceRecord | None,
) -> str:
    """被拒后给诚实降级标签（不是一律 block，留 repair/探索空间）。"""

    if promotable:
        return requested
    if choice is not None and choice.chosen_path in WAIVER_LABELS:
        return choice.chosen_path  # 诚实：用户选择了跳过严格路径
    if any(c.result == CHECK_FAIL for c in checks):
        return LABEL_CHALLENGED  # 已知不一致，可留待 repair
    if binding is None or not binding.test_refs or not checks:
        return LABEL_DRAFT  # 还没接实现/检查
    return LABEL_EXPLORATORY


def evaluate_promotion(
    artifact: MathematicalArtifact | None,
    binding: TheoryImplementationBinding | None,
    checks: Iterable[ConsistencyCheck] | None = None,
    *,
    requested_label: str,
    current_code_hash: str | None = None,
    choice: MethodologyChoiceRecord | None = None,
    data_contract: Mapping[str, Any] | None = None,
) -> SpineDecision:
    """裁定能否把产物升级到 `requested_label`。强标签需过 Π 全部必需子句。

    - `current_code_hash`：运行时 `content_hash(实现源)`；与 `binding.code_content_hash` 比对查 staleness。
      不传 → 仅凭 binding 既存指纹，记 note「未实时复核」，但 binding 从未冻结指纹则强标签直接拒。
    - `choice`：用户方法学选择；放权（waiver）在场时 proof_backed 被拒，降级到放权标签（诚实，不冒充）。
    - `data_contract`：估计器/统计检验/数据时间语义类必须携带 PIT 时间语义（known_at∧effective_at）。
    """

    check_list = list(checks or [])
    violations: list[str] = []
    matched: list[str] = []
    notes: list[str] = []

    strong = requested_label in STRONG_LABELS
    proof_req = requested_label in PROOF_REQUIRING_LABELS
    has_artifact = artifact is not None and bool(artifact.statement.strip())
    has_binding = binding is not None

    # (8) claim-grounded —— 请求 proof_backed 必须真有数学产物（§8 TheoryClaim ⇒ Artifact exists）
    if proof_req:
        if has_artifact and artifact is not None and artifact.derivation.strip():
            matched.append("claim-grounded(§8 TheoryClaim⇒Artifact)")
        else:
            violations.append(
                "§8 claim-grounded：请求 proof_backed 但缺 MathematicalArtifact 或 statement/derivation 空 → 拒"
            )

    if strong:
        # (1) binding-exists —— 公式无 implementation/test binding → 不得 promoted
        if has_binding and binding is not None and binding.test_refs:
            matched.append("binding-exists(§6 impl/test binding)")
        else:
            violations.append("§6 binding-exists：公式无 implementation/test binding → 不得 promoted")

        # (2) binding-complete —— TIB ⇒ code_ref + config_ref + data_contract_ref
        if has_binding and binding is not None:
            miss = [
                n
                for n, v in (
                    ("code_ref", binding.code_ref),
                    ("config_ref", binding.config_ref),
                    ("data_contract_ref", binding.data_contract_ref),
                )
                if not v
            ]
            if not miss:
                matched.append("binding-complete(§8 code+config+data_contract)")
            else:
                violations.append(
                    f"§8 binding-complete：TheoryImplementationBinding 缺 {','.join(miss)} → 拒"
                )

        # (3) consistency-present + (4) consistency-pass.  A PASS belonging to
        # another binding is unrelated evidence and must never satisfy this one.
        bound_checks = (
            [c for c in check_list if c.binding_id == binding.binding_id]
            if binding is not None
            else []
        )
        foreign_checks = [c for c in check_list if c not in bound_checks]
        if foreign_checks:
            violations.append(
                "§6 consistency-binding：ConsistencyCheck 未绑定当前 TheoryImplementationBinding → 拒"
            )
        decisive = [c for c in bound_checks if c.result != CHECK_PENDING]
        failed = [c for c in bound_checks if c.result == CHECK_FAIL]
        if not decisive:
            violations.append(
                "§8 consistency-present：声称按理论实现但无决定性 ConsistencyCheck → 拒"
            )
        else:
            matched.append("consistency-present(§8 TIB⇒ConsistencyCheck)")
        if failed:
            reasons = "; ".join(f"{c.check_type}:{c.failure_reason or 'fail'}" for c in failed)
            violations.append(f"§6 consistency-pass：代码实现与数学定义不一致（{reasons}）→ 拒")
        elif decisive:
            matched.append("consistency-pass(§6 实现↔定义一致)")

        # (5) fresh —— 实现改动后未刷新 binding → 拒（content_hash 内容寻址指纹）
        if has_binding and binding is not None:
            if not binding.code_content_hash:
                violations.append(
                    "§6 fresh：binding 从未冻结 code_content_hash，无法证明实现未漂移 → 拒"
                )
            elif current_code_hash is not None and current_code_hash != binding.code_content_hash:
                violations.append(
                    "§6 fresh：实现改动后未刷新 TheoryImplementationBinding（code_content_hash 失配）→ 拒"
                )
            else:
                matched.append("fresh(§6 binding 未过期)")
                if current_code_hash is None:
                    notes.append(
                        "freshness_unverified：本次未传 current_code_hash，仅凭 binding 既存指纹（未实时复核）"
                    )

        # (7) pit-bound —— estimator/统计检验/数据时间语义必须绑 PIT 时间
        if artifact is not None and artifact.artifact_type in PIT_REQUIRING_TYPES:
            dc = data_contract or {}
            has_pit = (
                has_binding
                and binding is not None
                and bool(binding.data_contract_ref)
                and bool(dc.get("known_at"))
                and bool(dc.get("effective_at"))
            )
            if has_pit:
                matched.append("pit-bound(§6 estimator 绑 PIT)")
            else:
                violations.append(
                    "§6 pit-bound：estimator/统计检验未绑定 data timing/PIT(known_at∧effective_at) → 拒"
                )

        waiver_present = (choice is not None and choice.is_waiver) or (
            has_binding and binding is not None and bool(binding.waiver_ref)
        )
        if waiver_present:
            violations.append(
                "§6 strong-label-honest：用户 waiver/skip 产物不得标为 evidence_sufficient、"
                "proof_backed 或 production_ready → 拒"
            )

    # (6) proof-honest —— 理论未达证明却请求 proof_backed/production_ready → 拒
    if proof_req:
        waiver_present = (choice is not None and choice.is_waiver) or (
            has_binding and binding is not None and bool(binding.waiver_ref)
        )
        proof_ok = has_artifact and artifact is not None and artifact.proof_status == PROOF_BACKED
        if proof_ok and not waiver_present:
            matched.append("proof-honest(§6 proof_status=proof_backed 且无 waiver)")
        else:
            why = []
            if not proof_ok:
                why.append(
                    f"proof_status={artifact.proof_status if artifact else 'none'}≠proof_backed"
                )
            if waiver_present:
                why.append("存在用户 waiver/skip")
            violations.append(
                f"§6 proof-honest：理论未达证明却请求 proof_backed（{'; '.join(why)}）→ 拒"
            )

    # 弱/诚实标签永远可授（它们不越权，如实陈述「还没证 / 用户跳过」）；
    # 强标签需零必需子句失败。
    promotable = (not violations) if strong else True
    granted = _granted_label(requested_label, promotable, check_list, binding, choice)

    if promotable:
        verdict = (
            f"一致性门放行：granted_label={granted}；过子句 {len(matched)} 条"
            f"（{', '.join(matched) if matched else '弱标签如实陈述，无强证据义务'}）。"
        )
    else:
        verdict = (
            f"一致性门拒绝升级到「{requested_label}」：" + "；".join(violations)
            + f"。降级到诚实标签「{granted}」——按真实状态展示，不冒充强标签。"
        )
        # 门的自检：拒绝口径绝不能出现越权正向断言（假绿灯反噬自身）。
        for term in BANNED_POSITIVE_TERMS:
            if term in verdict:
                raise AssertionError(
                    f"一致性门自检失败：拒绝口径出现越权词 {term!r}（= 我们自己打了假绿灯）"
                )

    return SpineDecision(
        requested_label=requested_label,
        granted_label=granted,
        promotable=promotable,
        allow_existence=True,
        violations=tuple(violations),
        matched_rules=tuple(matched),
        notes=tuple(notes),
        verdict_text=verdict,
    )
