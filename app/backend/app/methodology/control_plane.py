"""方法学控制面 · 6 档（GOAL §10 方法学与验证）——系统提供给 user 运行时选的旋钮。

GOAL §10 把验证严格度做成 **6 档可选**（不是 agent/系统替用户拍）：

    strict / standard / loose / exploratory / custom / user_waived

系统对每一档**展示**：代价（cost）/ 证据缺口（evidence_gap）/ 适用环境
（applicable_environment）/ 推荐路径（recommended_path）/ 责任边界
（responsibility_boundary）。User 据此**自己**选松紧或跳过；系统把选择记成一条
`MethodologyChoiceRecord`，并按**真实状态**限制四个面：展示、晋级、导出、运行环境。

为什么是「控制面」而不是又一个证据门（与现有 spine 一致性门的分工）：
- 身份/记录**复用不另造**（RULES §1 单一源）：`MethodologyChoiceRecord` 与升级标签阶梯
  （`STRONG_LABELS` / 各 `LABEL_*` / `WAIVER_LABELS`）全部 import 自
  `app.lineage.spine`，本模块**绝不**重定义一份。
- 与 `spine_gate.evaluate_promotion` **互补、不替换**（扩展不替换）：那道门的 proof-honest
  子句只挡 `proof_backed` / `production_ready`（`PROOF_REQUIRING_LABELS`），**不**挡
  `evidence_sufficient`——所以单凭 spine 门，一个放宽档资产仍可能滑进 `evidence_sufficient`。
  本控制面补上更宽的一层：**放宽档（loose/exploratory/custom/user_waived）一律不得触及任一
  强标签**（含 `evidence_sufficient`）。两道门在调用点叠乘：真实标签 =
  `effective_label(tier, 下游证据门拟授标签)`。

诚实边界（这道控制面**不**做什么，照 §3 诚实纪律 + spine_gate 同款口径）：
- 它**不授予**强标签。档位层「许可」(`permitted=True`) 是**必要非充分**——强标签仍须下游
  证据门（一致性门 / PBO / DSR / 成本 TCA / 容量）逐条过。passing 控制面 ≠ 证据够。
- 它**不替用户定阈值数值**。PBO/DSR/CPCV 折数、t、样本长度等**数值**是用户可配（文献默认、
  另处持有），本模块只编码「档位姿态 + 诚实标签上限」这层**质性**契约，绝不烤死统计阈值。
- 放宽后系统**继续交付**（P2 不挡探索），但**绝不**把放宽结果标成强证据 / proof_backed /
  production_ready——按真实状态降级到诚实标签（exploratory / custom_methodology /
  user_waived_*），如实陈述放宽口径。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..lineage.spine import (
    LABEL_CUSTOM_METHODOLOGY,
    LABEL_DRAFT,
    LABEL_EVIDENCE_SUFFICIENT,
    LABEL_EXPLORATORY,
    LABEL_PRODUCTION_READY,
    LABEL_PROOF_BACKED,
    LABEL_USER_WAIVED_THEORY,
    LABEL_USER_WAIVED_VALIDATION,
    STRONG_LABELS,
    MethodologyChoiceRecord,
)

__all__ = [
    "MethodologyTier",
    "RELAXED_TIERS",
    "RIGOROUS_TIERS",
    "ALL_TIER_VALUES",
    "TierProfile",
    "TIER_PROFILES",
    "MethodologyDecision",
    "DISCLOSURE",
    "build_methodology_choice",
    "constrain_promotion",
    "effective_label",
    "assert_label_honest_for_export",
    "production_eligible",
    "runtime_environment_ceiling",
    "documentation_gaps",
    "tier_of",
    "validate_profiles",
]


# ── 6 档（GOAL §10 已命名·照建·这是 user 运行时选的旋钮，不是系统替拍）─────────────
class MethodologyTier(str, Enum):
    STRICT = "strict"            # 机构级全套开满——真钱/对外强结论的推荐路径
    STANDARD = "standard"        # 默认主干验证——日常研究合理起点
    LOOSE = "loose"              # 放宽稳健性门——快速探路，不背书
    EXPLORATORY = "exploratory"  # 验证基本旁路——纯生成假设
    CUSTOM = "custom"            # 用户自配口径——偏离机构级默认
    USER_WAIVED = "user_waived"  # 用户主动弃权——跳过验证流程


ALL_TIER_VALUES: tuple[str, ...] = tuple(t.value for t in MethodologyTier)

# 放宽组：一律不得触及强标签（含 evidence_sufficient）；rigorous 组不被本控制面 cap，
# 强标签交由下游证据门裁定。「放宽 = loose 及更松」；standard 是默认基线、strict 在其上，
# 二者都不是 GOAL §10 语义下的「放宽」，故不 cap（见 docstring + recommended_path 提示升档）。
RELAXED_TIERS: frozenset[MethodologyTier] = frozenset(
    {
        MethodologyTier.LOOSE,
        MethodologyTier.EXPLORATORY,
        MethodologyTier.CUSTOM,
        MethodologyTier.USER_WAIVED,
    }
)
RIGOROUS_TIERS: frozenset[MethodologyTier] = frozenset(
    {MethodologyTier.STRICT, MethodologyTier.STANDARD}
)


# ── 每档元数据（GOAL §10：展示 代价/证据缺口/适用环境/推荐路径/责任边界）──────────────
@dataclass(frozen=True)
class TierProfile:
    """一档的可展示契约 + 诚实标签上限。

    `summary/cost/evidence_gap/applicable_environment/recommended_path/responsibility_boundary`
    是 §10 要求**展示给 user** 的五面（让其知情选）；**质性**描述，**不含**统计阈值数值
    （阈值=用户可配、文献默认、别处持有）。

    `permits_strong_labels/honest_downgrade_label/label_ceiling/allowed_environment/
    skipped_steps_hint` 是**真实状态限制门**用的机器字段：放宽档 `permits_strong_labels=False`，
    触强标签时降级到 `honest_downgrade_label`（一个 spine 诚实/放权标签，复用不另造）。
    """

    tier: MethodologyTier
    summary: str
    cost: str
    evidence_gap: str
    applicable_environment: str
    recommended_path: str
    responsibility_boundary: str
    permits_strong_labels: bool
    honest_downgrade_label: str   # 触强标签时降级到的 spine 诚实标签（rigorous 档不适用→""）
    label_ceiling: str            # 本档诚实可达的最强 spine 标签
    allowed_environment: str      # 记进 MethodologyChoiceRecord 的环境上限（限制运行环境）
    skipped_steps_hint: tuple[str, ...]  # 跳过的步骤（非空→spine is_waiver 触发）


TIER_PROFILES: dict[MethodologyTier, TierProfile] = {
    MethodologyTier.STRICT: TierProfile(
        tier=MethodologyTier.STRICT,
        summary=(
            "机构级全套开满：PBO/CSCV、DSR/PSR/MinTRL、CPCV+walk-forward 双轨、purge/embargo、"
            "通缩区间、多重检验账、成本/TCA/容量——最严档。"
        ),
        cost="算力/时间最贵、迭代最慢；多重检验与通缩区间会砍掉大量看似显著的结果。",
        evidence_gap=(
            "最小但非零：方法学严 ≠ 数学命题已证（仍须 spine 一致性门 + proof_status），"
            "也 ≠ 未来不漂；样本外仍是估计。"
        ),
        applicable_environment="真钱上线前的最终验证、对外强结论申报；production_ready 申报路径。",
        recommended_path="真钱/对外强证据走本档；过下游证据门后方可申报 production_ready。",
        responsibility_boundary=(
            "系统提供机构级方法与门；阈值数值仍由用户/文献默认配，最终决策与真钱按键归用户本人。"
        ),
        permits_strong_labels=True,
        honest_downgrade_label="",  # 本档不被控制面 cap，无降级目标
        label_ceiling=LABEL_PRODUCTION_READY,
        allowed_environment="research → paper → 受控生产/实盘（须另过下游证据门 + 安全门；A股永不实盘）",
        skipped_steps_hint=(),
    ),
    MethodologyTier.STANDARD: TierProfile(
        tier=MethodologyTier.STANDARD,
        summary=(
            "默认档：主干验证开启（walk-forward、CPCV、purge/embargo、bootstrap CI、成本基线），"
            "不强制全套最严选项。"
        ),
        cost="比 strict 快/省；省下部分最重的检验（如全量 CPCV 折数 / 通缩区间深扫）。",
        evidence_gap=(
            "比 strict 多一层：部分稳健性/多重检验账可能未铺满（取决于用户配的开关与阈值）。"
        ),
        applicable_environment="日常研究与候选筛选的合理默认；申报 production_ready 前推荐升 strict。",
        recommended_path="作为默认起点；要对外强结论或真钱上线，升 strict 复跑确认。",
        responsibility_boundary=(
            "系统给默认主干方法；松紧/阈值由用户配，结论强度归用户与下游证据门共同裁定。"
        ),
        permits_strong_labels=True,
        honest_downgrade_label="",  # 不被控制面 cap
        label_ceiling=LABEL_PRODUCTION_READY,
        allowed_environment="research → paper → 受控生产（推荐升 strict 再上线；A股永不实盘）",
        skipped_steps_hint=(),  # 默认基线≠放权：spine is_waiver 不触发（否则会误挡 proof_backed）
    ),
    MethodologyTier.LOOSE: TierProfile(
        tier=MethodologyTier.LOOSE,
        summary="放宽档：主干仍跑但关掉/调松部分稳健性门（减少 CPCV 折、放宽多重检验、缩短样本要求）。",
        cost="快、省；代价是稳健性证据大幅变薄，过拟合/多重检验风险未被充分扣减。",
        evidence_gap=(
            "大：选择偏差与样本风险未充分控制；结果只反映「这套放松口径下看起来不错」。"
        ),
        applicable_environment="快速探路、参数扫描、想法初筛；不适合对外结论、不适合真钱。",
        recommended_path="命中后用 standard/strict 复跑确认，再谈强结论；不要据此上线。",
        responsibility_boundary="用户主动放宽稳健性门；放宽后的结论强度与风险由用户承担，系统不背书。",
        permits_strong_labels=False,
        honest_downgrade_label=LABEL_EXPLORATORY,
        label_ceiling=LABEL_EXPLORATORY,
        allowed_environment="research / 探索（非生产、非实盘、非对外强结论）",
        skipped_steps_hint=("部分稳健性/多重检验门放宽（loose）",),
    ),
    MethodologyTier.EXPLORATORY: TierProfile(
        tier=MethodologyTier.EXPLORATORY,
        summary="探索档：最大研究自由，验证门基本旁路，纯为生成假设/看现象。",
        cost="几乎无门槛；代价是几乎无统计证据，结论=未验证假设。",
        evidence_gap="最大：无多重检验、无样本风险控制、无成本扣减保证。",
        applicable_environment="头脑风暴、因子挖掘初期、可视化探索；严禁对外/真钱/上线。",
        recommended_path="仅产假设；任何结论须经 standard/strict 重跑验证才可谈强度。",
        responsibility_boundary="纯探索、系统不做任何证据承诺；一切解读风险归用户。",
        permits_strong_labels=False,
        honest_downgrade_label=LABEL_EXPLORATORY,
        label_ceiling=LABEL_EXPLORATORY,
        allowed_environment="research / 探索（非生产、非实盘、非对外强结论）",
        skipped_steps_hint=("验证门旁路（exploratory）",),
    ),
    MethodologyTier.CUSTOM: TierProfile(
        tier=MethodologyTier.CUSTOM,
        summary="自定义档：用户自配方法学开关与阈值，偏离机构级默认。",
        cost="取决于用户配置；偏离默认 = 失去「机构级默认」这一参照基线的可比性。",
        evidence_gap="由用户配置决定、可能任意大；系统无法替这套自定义口径背书强度。",
        applicable_environment="有明确方法学主张的高级用户；适用域由用户自界定。",
        recommended_path="自定义口径须用户自陈理由与适用域；对外须随附配置与责任声明。",
        responsibility_boundary=(
            "方法学口径由用户定义，强度与适用性解释责任归用户；系统按 custom_methodology 诚实标注。"
        ),
        permits_strong_labels=False,
        honest_downgrade_label=LABEL_CUSTOM_METHODOLOGY,
        label_ceiling=LABEL_CUSTOM_METHODOLOGY,
        allowed_environment="由用户自定义口径界定（非默认强标签环境）",
        skipped_steps_hint=("偏离机构级默认（custom 自定义口径）",),
    ),
    MethodologyTier.USER_WAIVED: TierProfile(
        tier=MethodologyTier.USER_WAIVED,
        summary="弃权档：用户主动跳过方法学验证流程，直接出结果。",
        cost="无验证成本；代价是结果完全无验证背书。",
        evidence_gap="完全：理论未证、实现未对、稳健性未验、成本未扣——全部空白。",
        applicable_environment="用户明知风险、自担后果的一次性出图/占位；严禁对外强结论、真钱、上线。",
        recommended_path="仅占位；要任何强度须回到 standard/strict 走完流程。",
        responsibility_boundary=(
            "用户明示弃权、自负全部后果；系统按 user_waived 诚实标注、绝不冒充强标签。"
        ),
        permits_strong_labels=False,
        honest_downgrade_label=LABEL_USER_WAIVED_VALIDATION,
        label_ceiling=LABEL_USER_WAIVED_VALIDATION,
        allowed_environment="用户自担（非生产、非实盘、非对外强结论）",
        skipped_steps_hint=("用户弃权：跳过方法学验证流程（user_waived）",),
    ),
}


DISCLOSURE = (
    "方法学控制面按 user 所选档位裁『诚实标签上限』：放宽档（loose/exploratory/custom/"
    "user_waived）不得触及强标签（evidence_sufficient/proof_backed/production_ready）。"
    "控制面通过是必要非充分——不授予强标签，强标签仍须下游证据门（一致性门/PBO/DSR/成本TCA）"
    "逐条过；阈值数值由 user 可配（文献默认），本控制面不替用户拍。"
)

# 裁决口径绝不能出现的越权正向断言（与 spine_gate.BANNED_POSITIVE_TERMS 同款诚实自检；
# 防「不给小白假绿灯」原则反噬自身——label token 允许被命名，正向断言禁止）。
_BANNED_VERDICT_TERMS = (
    "已证明",
    "理论已证明",
    "证据充分",
    "evidence 充分",
    "保证一致",
    "保证",
    "可信",
    "production-ready 达成",
)


def _strong_labels_str() -> str:
    """强标签的稳定展示串（按阶梯弱→强排，便于裁决文阅读）。"""

    order = [LABEL_EVIDENCE_SUFFICIENT, LABEL_PROOF_BACKED, LABEL_PRODUCTION_READY]
    return "/".join(x for x in order if x in STRONG_LABELS)


# ── 真实状态限制门（GOAL §10：按真实状态限制 展示/晋级/导出/运行环境）─────────────────
@dataclass(frozen=True)
class MethodologyDecision:
    """档位层裁定（frozen，参 spine_gate.SpineDecision / security.gate PolicyDecision 范式）。

    `permitted` 是**档位层许可**，**非授予**——强标签仍须下游证据门过（见 `notes` / `disclosure`）。
    `granted_label` 是按真实状态可授的诚实标签；`capped=True` 表示请求被档位上限压低了。
    """

    tier: MethodologyTier
    requested_label: str
    granted_label: str
    permitted: bool
    capped: bool
    production_eligible: bool
    runtime_environment_ceiling: str
    violations: tuple[str, ...]
    notes: tuple[str, ...]
    verdict_text: str
    disclosure: str = DISCLOSURE


def documentation_gaps(choice: MethodologyChoiceRecord | None) -> tuple[str, ...]:
    """放宽必须留痕——查 MethodologyChoiceRecord 是否缺 tradeoffs/recommendation/responsibility_boundary。

    GOAL §10 可证伪门：「方法学松紧未记录 tradeoffs/recommendation/responsibility_boundary → 拒」。
    `choice=None`（放宽却没记录）= 全缺。
    """

    if choice is None:
        return ("MethodologyChoiceRecord(缺失)",)
    gaps: list[str] = []
    if not choice.tradeoffs_shown:
        gaps.append("tradeoffs")
    if not (choice.recommendation or "").strip():
        gaps.append("recommendation")
    if not (choice.responsibility_boundary or "").strip():
        gaps.append("responsibility_boundary")
    return tuple(gaps)


def constrain_promotion(
    tier: MethodologyTier,
    requested_label: str,
    *,
    choice: MethodologyChoiceRecord | None = None,
) -> MethodologyDecision:
    """晋级门：给定档位 + 请求标签（+ 可选 choice 记录），裁能否升级到请求标签。

    两条 GOAL §10 可证伪门叠在这里：
    - 放宽档（{loose,exploratory,custom,user_waived}）请求任一强标签 → **拒**、降级诚实标签。
    - 放宽档未留完整 MethodologyChoiceRecord（tradeoffs/recommendation/responsibility_boundary）→ **拒**。

    rigorous 档（strict/standard）请求强标签 → 档位层**许可**（`permitted=True`），但 `notes`
    明示**非授予**：实际升级仍须下游证据门过。诚实标签（draft/exploratory/...）任何档都放行。
    """

    if tier not in TIER_PROFILES:  # 防御：未知档（理应被 Enum 挡住，留作显式拒绝）
        raise ValueError(f"未知方法学档位：{tier!r} ∉ {ALL_TIER_VALUES}")

    profile = TIER_PROFILES[tier]
    relaxed = tier in RELAXED_TIERS
    strong = requested_label in STRONG_LABELS
    violations: list[str] = []
    notes: list[str] = []

    # 门②：放宽必须留完整记录（tradeoffs/recommendation/responsibility_boundary）
    if relaxed:
        gaps = documentation_gaps(choice)
        if gaps:
            violations.append(
                f"§10 方法学放宽（{tier.value}）未记录 {'/'.join(gaps)} → 拒"
                "（MethodologyChoiceRecord 须含 tradeoffs_shown + recommendation + responsibility_boundary）"
            )

    # 门①/③：放宽档不得触及任一强标签（含 evidence_sufficient，比 spine proof-honest 更宽）
    if relaxed and strong:
        violations.append(
            f"§10 放宽档『{tier.value}』不得把结果标成强标签（{_strong_labels_str()}）→ 拒"
        )

    if violations:
        permitted = False
        granted = profile.honest_downgrade_label or LABEL_DRAFT
        verdict = (
            f"控制面拒绝升级到『{requested_label}』："
            + "；".join(violations)
            + f"。按真实状态降级到诚实标签『{granted}』——如实陈述放宽口径，不冒充强标签。"
        )
    elif strong:
        # 必为 rigorous 档（relaxed+strong 已进 violations）：档位层许可、非授予
        permitted = True
        granted = requested_label
        notes.append(
            "控制面仅档位层许可、非授予强标签：实际升级仍须下游证据门"
            "（一致性门 / PBO / DSR / 成本 TCA / 容量）逐条过。"
        )
        verdict = (
            f"控制面放行：档位『{tier.value}』可请求强标签『{requested_label}』"
            "（仅档位层许可、非授予）；实际能否升级由下游证据门裁定。"
        )
    else:
        permitted = True
        granted = requested_label
        verdict = (
            f"控制面放行：档位『{tier.value}』请求诚实标签『{requested_label}』，"
            "如实陈述、无强证据义务。"
        )

    capped = granted != requested_label

    # 自检（假绿灯反噬自身）：裁决口径绝不出现越权正向断言
    for term in _BANNED_VERDICT_TERMS:
        if term in verdict:
            raise AssertionError(
                f"控制面自检失败：裁决口径出现越权词 {term!r}（= 我们自己打了假绿灯）"
            )

    return MethodologyDecision(
        tier=tier,
        requested_label=requested_label,
        granted_label=granted,
        permitted=permitted,
        capped=capped,
        production_eligible=profile.permits_strong_labels,
        runtime_environment_ceiling=profile.allowed_environment,
        violations=tuple(violations),
        notes=tuple(notes),
        verdict_text=verdict,
    )


def effective_label(tier: MethodologyTier, candidate_label: str) -> str:
    """把『下游证据门拟授予的 candidate_label』按档位降到诚实上限（展示/导出/晋级共用的真实状态限制）。

    放宽档 + candidate 是强标签 → 降级到该档 `honest_downgrade_label`；否则原样。
    这是控制面与下游证据门在调用点叠乘的原语：真实标签 = effective_label(tier, 下游拟授标签)。
    """

    if tier in RELAXED_TIERS and candidate_label in STRONG_LABELS:
        return TIER_PROFILES[tier].honest_downgrade_label
    return candidate_label


def assert_label_honest_for_export(tier: MethodologyTier, label: str) -> None:
    """导出守门（限制导出）：放宽档资产携带强标签 → raise（绝不导出为强证据）。

    GOAL §10：放宽后不得标成强证据/proof_backed/production_ready。导出路径硬挡，防越权标签外流。
    """

    if tier in RELAXED_TIERS and label in STRONG_LABELS:
        downgrade = TIER_PROFILES[tier].honest_downgrade_label
        raise ValueError(
            f"导出守门：放宽档『{tier.value}』资产携带强标签『{label}』——"
            f"放宽口径不得导出为强标签（{_strong_labels_str()}）（GOAL §10）。"
            f"请先降级到诚实标签『{downgrade}』再导出。"
        )


def production_eligible(tier: MethodologyTier) -> bool:
    """限制运行环境（方法学维度）：本档是否够格进生产/上线。

    仅 strict/standard 在方法学层面够格（放宽档不够）；**安全/实盘的最终权在 security gate**
    （A股永不实盘等红线另在安全门强制，本函数只表态方法学姿态）。
    """

    return TIER_PROFILES[tier].permits_strong_labels


def runtime_environment_ceiling(tier: MethodologyTier) -> str:
    """本档允许的运行环境上限（展示串，记进 MethodologyChoiceRecord.allowed_environment）。"""

    return TIER_PROFILES[tier].allowed_environment


def tier_of(choice: MethodologyChoiceRecord) -> MethodologyTier | None:
    """从一条 MethodologyChoiceRecord 反推档位（best-effort，供 RDP/消费方用）。

    `chosen_path` 若是档名直接命中；若是 spine 放权标签（如 user_waived_validation）按映射回推；
    都不命中 → None（由调用方决定如何处理，不臆测）。
    """

    cp = choice.chosen_path
    for t in MethodologyTier:
        if cp == t.value:
            return t
    label_to_tier = {
        LABEL_USER_WAIVED_THEORY: MethodologyTier.USER_WAIVED,
        LABEL_USER_WAIVED_VALIDATION: MethodologyTier.USER_WAIVED,
        LABEL_CUSTOM_METHODOLOGY: MethodologyTier.CUSTOM,
        LABEL_EXPLORATORY: MethodologyTier.EXPLORATORY,
    }
    return label_to_tier.get(cp)


def build_methodology_choice(
    tier: MethodologyTier,
    *,
    asset_ref: str = "",
    run_ref: str = "",
    actor: str = "user",
    extra_tradeoffs: tuple[str, ...] = (),
    recommendation_override: str = "",
    responsibility_override: str = "",
) -> MethodologyChoiceRecord:
    """把一次档位选择物化成 `MethodologyChoiceRecord`（复用 spine 类型、不另造）。

    产出的记录**自带**完整 tradeoffs/recommendation/responsibility_boundary（过门②），并：
    - `chosen_path = tier.value`：无损保留 user 选的档（6 档名）。
    - 放宽档 `skipped_steps` 非空 → spine `MethodologyChoiceRecord.is_waiver=True`，喂进
      `spine_gate.evaluate_promotion` 时其 proof-honest 子句也会就 proof_backed/production_ready
      触发（与本控制面更宽的强标签 cap 叠乘，互补不冲突）。
    - `allowed_environment` = 该档运行环境上限；`display_label` = 放宽档的诚实展示标签。
    """

    if tier not in TIER_PROFILES:
        raise ValueError(f"未知方法学档位：{tier!r} ∉ {ALL_TIER_VALUES}")
    profile = TIER_PROFILES[tier]
    return MethodologyChoiceRecord(
        chosen_path=tier.value,
        asset_ref=asset_ref,
        run_ref=run_ref,
        available_options=ALL_TIER_VALUES,
        recommendation=recommendation_override or profile.recommended_path,
        tradeoffs_shown=(profile.cost, profile.evidence_gap) + tuple(extra_tradeoffs),
        risks_shown=(profile.evidence_gap,),
        skipped_steps=profile.skipped_steps_hint,
        responsibility_boundary=responsibility_override or profile.responsibility_boundary,
        actor=actor,
        allowed_environment=profile.allowed_environment,
        display_label=(profile.honest_downgrade_label if tier in RELAXED_TIERS else ""),
    )


def validate_profiles() -> None:
    """框架自检（GOAL §10 门④）：6 档齐 + 每档元数据齐 + 档位↔标签上限结构一致 → 正常不误伤。

    放宽档：不许强标签、ceiling/downgrade ∉ 强标签、skipped_steps 非空（驱动 is_waiver）。
    rigorous 档：许强标签、ceiling=production_ready、无 skipped_steps（默认基线≠放权，否则误挡 proof_backed）。
    """

    missing = [t for t in MethodologyTier if t not in TIER_PROFILES]
    if missing:
        raise AssertionError(f"方法学控制面缺档：{[t.value for t in missing]}（须 6 档齐）")

    display_fields = (
        "summary",
        "cost",
        "evidence_gap",
        "applicable_environment",
        "recommended_path",
        "responsibility_boundary",
        "allowed_environment",
    )
    for t, p in TIER_PROFILES.items():
        if p.tier is not t:
            raise AssertionError(f"档位元数据错配：key={t.value} 但 profile.tier={p.tier.value}")
        for fname in display_fields:
            if not str(getattr(p, fname)).strip():
                raise AssertionError(f"档位『{t.value}』缺展示元数据 {fname}（§10 须展示五面）")
        if t in RELAXED_TIERS:
            if p.permits_strong_labels:
                raise AssertionError(f"放宽档『{t.value}』不得 permits_strong_labels=True")
            if p.label_ceiling in STRONG_LABELS:
                raise AssertionError(f"放宽档『{t.value}』label_ceiling 不得是强标签")
            if not p.honest_downgrade_label or p.honest_downgrade_label in STRONG_LABELS:
                raise AssertionError(f"放宽档『{t.value}』须有非强标签的 honest_downgrade_label")
            if not p.skipped_steps_hint:
                raise AssertionError(f"放宽档『{t.value}』skipped_steps_hint 须非空（驱动 is_waiver）")
        else:
            if not p.permits_strong_labels:
                raise AssertionError(f"rigorous 档『{t.value}』须 permits_strong_labels=True")
            if p.label_ceiling != LABEL_PRODUCTION_READY:
                raise AssertionError(f"rigorous 档『{t.value}』label_ceiling 须 production_ready")
            if p.skipped_steps_hint:
                raise AssertionError(
                    f"rigorous 档『{t.value}』不得有 skipped_steps_hint（默认基线≠放权，否则误挡 proof_backed）"
                )
