"""LLM Gateway · ModelRoutingPolicy（混合自适应 · D-LLM-ROUTING）。

D-LLM-ROUTING（2026-06-26 用户拍板）：默认路由 = **混合自适应**——按任务难度/风险自动选档：
硬推理（架构/数学/难调试/不可逆决策）走强模型、机械活（格式化/简单提取/样板）走轻模型。
策略**可配**（可切质量优先 / 成本优先），默认混合自适应。**绝不静默降质**难任务到不适配轻模型
（难任务误走轻模型 = correctness 风险 → 必标 `degraded`）。

本模块只决「该用哪档/哪个 model/哪个 pool」，不碰明文凭据、不发请求（那在 gateway）。
路由产物 `RoutingDecision` 由 gateway 写进 LLMCallRecord（可审计 · 进 RDP）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from .model_identity import has_independent_model_route


class TaskDifficulty(str, Enum):
    HARD = "hard"            # 架构 / 数学 / 难调试 / 不可逆决策推理
    NORMAL = "normal"
    MECHANICAL = "mechanical"  # 格式化 / 简单提取 / 样板


class RiskLevel(str, Enum):
    IRREVERSIBLE = "irreversible"  # 动钱 / 不可逆 / 删除 / 实盘相关
    ELEVATED = "elevated"
    NORMAL = "normal"
    LOW = "low"


class ModelTier(str, Enum):
    STRONG = "strong"
    NORMAL = "normal"
    LIGHT = "light"


_TIER_RANK: dict[str, int] = {ModelTier.LIGHT.value: 0, ModelTier.NORMAL.value: 1, ModelTier.STRONG.value: 2}


def tier_rank(tier: str) -> int:
    return _TIER_RANK.get(tier, 1)


class RoutingMode(str, Enum):
    HYBRID_ADAPTIVE = "hybrid_adaptive"  # 默认（D-LLM-ROUTING）
    QUALITY_FIRST = "quality_first"      # 一律强模型
    COST_FIRST = "cost_first"            # 在不破「不可逆/难任务下限」前提下尽量轻


class RoutingError(RuntimeError):
    pass


class PinnedModelUnavailable(RoutingError):
    """用户手选(hard pin)的模型/厂商无可用 profile 或凭据。

    继承 RoutingError → 现有 except RoutingError 仍捕获；但语义明确「pin 失败」，
    **绝不静默跨厂商 fallback**（跨厂商洗白无声降级 = 破 no-mix + 误导用户）。
    """


@dataclass(frozen=True)
class LLMModelProfile:
    """已知 model 的能力档登记（路由候选 + 降质探测的依据）。"""

    provider: str
    model: str
    capability_tier: str          # ModelTier.value
    pool_id: str                  # 指向 credential_pool 的池
    supports_tools: bool = True
    context_window: int = 0
    note: str = ""

    @property
    def signature(self) -> tuple[str, str]:
        return (self.provider, self.model)


@dataclass
class RoleCapabilityRequest:
    """role agent 提交的能力需求（GOAL §7：能力需求/上下文范围/权限/replay 要求）。"""

    role: str = ""
    difficulty: str = TaskDifficulty.NORMAL.value
    risk: str = RiskLevel.NORMAL.value
    independence_required: bool = False     # Verifier/Critic 要 provider + model family 双重异源
    replay_required: bool = False
    prefer_provider: str | None = None      # 软偏好——绝不压过「不可逆/难任务不降档」
    prefer_model: str | None = None
    # —— 用户手选（hard pin，跨厂商切模型 S2）——
    # 硬约束（区别于上面的软 prefer_*）：只保留 pin_provider 的候选、用 pin_model，
    # **仅当 independence_required==False 时生效**——dual-model 独立审查门物理免疫手选洗白。
    pin_provider: str | None = None
    pin_model: str | None = None


@dataclass
class RoutingDecision:
    tier_requested: str
    tier_resolved: str
    profile: LLMModelProfile
    mode: str
    degraded: bool = False
    degrade_reason: str = ""
    independence_required: bool = False
    independence_distinct: bool = False     # 是否证明 provider + model family 双重异源
    fallback_candidates: list[LLMModelProfile] = field(default_factory=list)
    rationale: str = ""


def infer_capability_tier(model: str) -> str:
    """把 model 名粗分到能力档——**默认启发式，可被显式 LLMModelProfile 覆盖**（诚实限界）。

    只在没有显式 profile 时兜底，给「开箱即用」一个不离谱的初值；判错就配 profile 纠正。
    """

    m = (model or "").lower()
    light_tokens = ("haiku", "mini", "nano", "small", "flash", "lite", "8b", "7b", "1.5b", "3b", "dev_local")
    strong_tokens = (
        "opus", "sonnet-4", "gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3", "qwen-max", "max",
        "ultra", "pro", "70b", "405b", "large", "deepseek-r", "r1",
    )
    if any(t in m for t in light_tokens):
        return ModelTier.LIGHT.value
    if any(t in m for t in strong_tokens):
        return ModelTier.STRONG.value
    return ModelTier.NORMAL.value


class ModelRoutingPolicy:
    """混合自适应路由（可配）。绝不静默降质：降档必标 `degraded` + reason。"""

    def __init__(
        self,
        profiles: list[LLMModelProfile],
        *,
        mode: RoutingMode | str = RoutingMode.HYBRID_ADAPTIVE,
    ) -> None:
        if not profiles:
            raise RoutingError("ModelRoutingPolicy 至少需要一个 LLMModelProfile")
        self._profiles = list(profiles)
        self._mode = RoutingMode(mode) if not isinstance(mode, RoutingMode) else mode

    @property
    def mode(self) -> RoutingMode:
        return self._mode

    @property
    def profiles(self) -> list[LLMModelProfile]:
        return list(self._profiles)

    # —— 第一步：需求 → 应当的档（混合自适应核心）——

    def required_tier(self, req: RoleCapabilityRequest) -> ModelTier:
        """风险/难度 → 应当档位。

        不变量（不可逆 / 难任务永远不降档，先于任何 mode / prefer）：
        - risk == IRREVERSIBLE → STRONG（动钱/不可逆永远强模型）
        - difficulty == HARD   → STRONG
        其余按 mode：
        - QUALITY_FIRST → STRONG
        - COST_FIRST    → 机械活 LIGHT，其余 NORMAL（仍守上面两条下限）
        - HYBRID_ADAPTIVE（默认）→ 机械活且低风险 LIGHT，其余 NORMAL
        """

        if req.risk == RiskLevel.IRREVERSIBLE.value:
            return ModelTier.STRONG
        if req.difficulty == TaskDifficulty.HARD.value:
            return ModelTier.STRONG
        if self._mode == RoutingMode.QUALITY_FIRST:
            return ModelTier.STRONG
        if self._mode == RoutingMode.COST_FIRST:
            return ModelTier.LIGHT if req.difficulty == TaskDifficulty.MECHANICAL.value else ModelTier.NORMAL
        # HYBRID_ADAPTIVE
        if req.difficulty == TaskDifficulty.MECHANICAL.value and req.risk in (
            RiskLevel.LOW.value,
            RiskLevel.NORMAL.value,
        ):
            return ModelTier.LIGHT
        return ModelTier.NORMAL

    # —— 第二步：选具体 profile（健康/排除/独立性/不降档）——

    def resolve(
        self,
        req: RoleCapabilityRequest,
        *,
        unavailable_providers: set[str] | None = None,
        exclude_signatures: set[tuple[str, str]] | None = None,
        builder_signature: tuple[str, str] | None = None,
    ) -> RoutingDecision:
        """解析出 RoutingDecision。

        - `unavailable_providers`：provider 不健康/配额耗尽/无可用凭据 → 排除。
        - `exclude_signatures`：本轮 fallback 已试过的 (provider,model)。
        - `builder_signature` + req.independence_required：Verifier 要相对 builder 换 provider，
          且换到可识别的不同 foundation-model family；未知家族 fail closed。
        """

        unavailable = unavailable_providers or set()
        excluded = set(exclude_signatures or set())
        required = self.required_tier(req)

        usable = [
            p for p in self._profiles
            if p.provider not in unavailable and p.signature not in excluded
        ]

        # —— 用户手选 hard pin（跨厂商切模型 S2）——
        # 仅 non-independence 生效：dual-model 独立审查门（independence_required=True）物理免疫——
        # pin 到此为止不参与，continue 走下面的自动异源指派。pin 是**硬过滤**（区别软 prefer_*）：
        # 只留 pin_provider 候选（pool_id==provider 不变→no-mix 保住）、换 pin_model；
        # pin 厂商无候选 → PinnedModelUnavailable，**绝不静默跨厂商 fallback**。
        pinned = bool(req.pin_provider) and not req.independence_required
        if pinned:
            usable = [p for p in usable if p.provider == req.pin_provider]
            if not usable:
                raise PinnedModelUnavailable(
                    f"手选厂商 {req.pin_provider!r} 无可用 profile/凭据"
                    f"（unavailable={sorted(unavailable)}, excluded={sorted(excluded)}）——绝不跨厂商 fallback"
                )
            if req.pin_model:
                # 换 model 字符串：provider/pool_id 不动（no-mix），tier 按 pin_model 重判（诚实档位）。
                usable = [
                    replace(
                        p, model=req.pin_model,
                        capability_tier=infer_capability_tier(req.pin_model),
                    )
                    for p in usable
                ]
        # If a route that can actually satisfy the requested independence is
        # available, non-independent routes are not candidates for this
        # decision.  This must happen before tier partitioning: an exact-tier
        # alias must not outrank a higher-tier independent model.
        if req.independence_required and builder_signature is not None:
            independent_usable = [
                p
                for p in usable
                if has_independent_model_route(
                    builder_provider=builder_signature[0],
                    builder_model=builder_signature[1],
                    verifier_provider=p.provider,
                    verifier_model=p.model,
                )
            ]
            if independent_usable:
                usable = independent_usable
        # 软偏好排序：可证明的双重异源优先 → 命中 prefer → tier 贴近 required。
        # 独立性是【软】偏好而非硬排除：只剩不可证明的 route 时仍会调它，但由
        # IndependenceRecord 如实标 satisfied=False（绝不假报独立），而不是直接路由失败。
        usable.sort(key=lambda p: self._pref_key(p, req, required, builder_signature))

        # 优先：tier 恰好 == required，再不行 tier > required（升档可，绝不主动降）。
        exact = [p for p in usable if p.capability_tier == required.value]
        higher = [p for p in usable if tier_rank(p.capability_tier) > tier_rank(required.value)]
        lower = [p for p in usable if tier_rank(p.capability_tier) < tier_rank(required.value)]

        chosen: LLMModelProfile | None = None
        degraded = False
        reason = ""
        if exact:
            chosen = exact[0]
        elif higher:
            chosen = sorted(higher, key=lambda p: tier_rank(p.capability_tier))[0]  # 最贴近 required 的更高档
            reason = f"无 {required.value} 档候选，升档到 {chosen.capability_tier}（升档不算降质）"
        elif lower:
            # 只剩更低档 → 降质，**必标，绝不静默**。
            chosen = sorted(lower, key=lambda p: tier_rank(p.capability_tier), reverse=True)[0]
            degraded = True
            reason = (
                f"required={required.value} 无健康候选，被迫降到 {chosen.capability_tier}"
                "——已标 degraded（D-LLM-ROUTING：绝不静默降质难任务）"
            )
        else:
            raise RoutingError(
                f"无任何可用 provider（unavailable={sorted(unavailable)}, excluded={sorted(excluded)}）"
            )

        independence_distinct = False
        if req.independence_required and builder_signature is not None:
            independence_distinct = has_independent_model_route(
                builder_provider=builder_signature[0],
                builder_model=builder_signature[1],
                verifier_provider=chosen.provider,
                verifier_model=chosen.model,
            )

        # pinned 决策不给 fallback 集：pin 厂商失败即 PinnedModelUnavailable，绝不换模型/换厂商。
        fallback_candidates = (
            [] if pinned else [p for p in usable if p.signature != chosen.signature]
        )
        rationale = self._rationale(req, required, chosen)
        return RoutingDecision(
            tier_requested=required.value,
            tier_resolved=chosen.capability_tier,
            profile=chosen,
            mode=self._mode.value,
            degraded=degraded,
            degrade_reason=reason,
            independence_required=req.independence_required,
            independence_distinct=independence_distinct,
            fallback_candidates=fallback_candidates,
            rationale=rationale,
        )

    # —— 内部 ——

    def _pref_key(
        self,
        p: LLMModelProfile,
        req: RoleCapabilityRequest,
        required: ModelTier,
        builder_signature: tuple[str, str] | None,
    ) -> tuple:
        # 独立性优先：只有 provider + model family 双重异源的候选排在前面。
        indep_penalty = 0
        if req.independence_required and builder_signature is not None:
            indep_penalty = 0 if has_independent_model_route(
                builder_provider=builder_signature[0],
                builder_model=builder_signature[1],
                verifier_provider=p.provider,
                verifier_model=p.model,
            ) else 1
        # 命中 prefer 的优先（0 在前）；同优先级里 tier 更贴近 required 的优先。
        pref_hit = 0
        if req.prefer_provider and p.provider == req.prefer_provider:
            pref_hit -= 1
        if req.prefer_model and p.model == req.prefer_model:
            pref_hit -= 1
        tier_gap = abs(tier_rank(p.capability_tier) - tier_rank(required.value))
        return (indep_penalty, pref_hit, tier_gap, p.provider, p.model)

    def _rationale(self, req: RoleCapabilityRequest, required: ModelTier, chosen: LLMModelProfile) -> str:
        return (
            f"mode={self._mode.value} difficulty={req.difficulty} risk={req.risk} "
            f"→ required={required.value} → {chosen.provider}/{chosen.model}({chosen.capability_tier})"
        )


__all__ = [
    "LLMModelProfile",
    "ModelRoutingPolicy",
    "ModelTier",
    "PinnedModelUnavailable",
    "RiskLevel",
    "RoleCapabilityRequest",
    "RoutingDecision",
    "RoutingError",
    "RoutingMode",
    "TaskDifficulty",
    "infer_capability_tier",
    "tier_rank",
]
