"""C-S10-COST-GATE + C-S10-CONTROLPLANE-ENFORCE · §10 方法学两道 check（插 SA-3 promote 门链）。

这张卡只建两道 PARALLEL-SAFE 的 check + 各自注册函数——把（库级已建的）§10 成本/TCA 字段与
控制面档位上限**经 SA-3 门链接到 promote 收口**，关掉 codemap 点出的两个洞：
  - `methodology_validation.py` **记** `cost_model_refs`/`tca_ref` 却**无门消费**（C-S10-COST-GATE）；
  - `control_plane.py` 只**封 label**（`effective_label`/`constrain_promotion`），但**无门在 promote
    verdict 上消费它**——放宽档 run 仍能显 `evidence_sufficient`（C-S10-CONTROLPLANE-ENFORCE）。
**不**在此串进 `ide/promote.py`（那是后续 CENTER-SERIAL 的一次性改·两步法）；本模块是新建孤立件，
中心后续调 `register_section10_cost_gate(default_chain())` + `register_section10_controlplane_gate(...)`。

═══ 复用不重造（RULES §1 单一源）═══
- COST 门：唯一源是 `research_os.methodology_validation` 的记录 + canonical validator。本模块做
  manifest(dict)→`ValidationMethodologyRecord`/`ValidationDepthRecord` 的**薄适配**（depth 直接复用
  既有 `validation_depth_record_from_dict`），跑 canonical `validate_validation_methodology`/
  `validate_validation_depth` 取其**成本族**违例（按 `MethodologyViolation.field ∈ {cost_model_refs,
  tca_ref}` 过滤——keyed 在 validator 自己的 field 标签上，不硬编码码字符串），**绝不**重写任何成本判定。
- CONTROL-PLANE 门：唯一源是 `methodology.control_plane.effective_label`（档位→诚实标签上限的原语）。
  本模块**只消费**它（`effective_label(tier, claimed) != claimed` ⇒ 该 verdict 被档位封顶 ⇒ 拒），
  档位↔标签上限逻辑**全委托** control_plane，**绝不**在此重写 tier 规则。`tier` 解析复用
  `MethodologyTier` enum + `tier_of(MethodologyChoiceRecord)`。

═══ 门的「消费」职责（codemap 要求·非重造）═══
- COST 门额外编码一条 promote 期**消费**策略：**任一 record 声明强标签（claim_label ∈ STRONG_LABELS）
  ⇒ 必须携带成本/TCA 证据（cost_model_refs 非空 或 tca_ref 在场），否则拒**。这关掉的洞是：canonical
  validator 只在 *runtime 环境*（paper/testnet/live/production）要求成本——research 环境下一个
  `evidence_sufficient` 强结论缺成本今天能溜过去（codemap C-S10-COST-GATE 的可证伪点）。本门把「要求
  成本」的触发条件从「runtime 环境」扩到「强标签声明」——**消费已记录的字段**，不是新写成本验证器。
- CONTROL-PLANE 门把 `effective_label`（label-cap 原语）抬成 **verdict 级**强制：放宽档把 verdict 显成
  强标签（被 effective_label 降级）⇒ 拒。这正是 codemap「封 verdict 上限（不只封 label）」。

═══ 职责分离（gaming-proof）═══
两道 check **只懂「这个 promote run 过没过」**，返回 `GateCheckResult(ok, reason, missing)`——它们
**不**决定自己是 advisory 还是 enforce。advisory/enforce 由 SA-2 策略（`governance.enforcement_policy`）
经门链统一盖章：仅当各自 producer 接线测试（`s10_cost_runjson_producers` /
`s10_controlplane_runjson_producers`）转绿，门才从 advisory 翻 enforce（LOCKED 决策 1）。check 连 mode
字段都没有 → **无法自封 enforce 绕过 producer 绿灯门**。

═══ 诚实限界（RULES §3·设计极限·非残余）═══
- 节缺省/为空 → `ok=True`，语义是**「未声明 §10 方法学结构 ⇒ 无可证伪违例」**，**不**代表「整本 run 已
  查清 §10 成本/档位」。「是否真有 §10 资产被如实写进 manifest」由 producer 绿灯门负责——producer 未绿
  时本门只 advisory，绝不在未接线门上误拒诚实 run。
- 节存在但格式非法（非 dict / 族非 list / 项非 dict / record 解析炸 / tier 值非法）→ fail-closed 记
  `ok=False`（codex 在 C-S9 找到的「非 list 族静默 skip 让违例溜走」洞，本模块同款堵死）。
- CONTROL-PLANE 的 fail-closed 收口：一条 tier-claim **声明强标签**却**解析不出档位**（漏 tier / tier_of
  归 None）→ 拒（堵「省略档位以躲避 verdict 封顶」的 dodge）；非强标签且无档位 → 无可封之物 → 放过
  （不误拒诚实 run）。

═══ 冷导入安全 ═══
顶层只 import 同包 `promote_gate_chain`（cold-safe·已证）、`research_os.methodology_validation`、
`methodology.control_plane`、`lineage.spine`（三者经 `python -c` 实证冷导入安全·只触 lineage.ids，不触
governance 冷循环）。**不**在顶层 import governance（SA-2 符号由门链在 evaluate 期惰性载入）。**不**碰
`release_gate/__init__.py`（既有冷导入环·SA-3 note）——消费方从本子模块直接 import。模块**无 import 期
副作用**（不 auto-register）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Iterable

from ..lineage.spine import STRONG_LABELS as SPINE_STRONG_LABELS, MethodologyChoiceRecord
from ..methodology.control_plane import (
    MethodologyTier,
    effective_label,
    tier_of,
)
from ..research_os.methodology_validation import (
    STRONG_LABELS as METHODOLOGY_STRONG_LABELS,
    MethodologyDecision,
    ValidationMethodologyRecord,
    validate_validation_depth,
    validate_validation_methodology,
    validation_depth_record_from_dict,
)
from .promote_gate_chain import GateCheckResult, PromoteGateChain, RunManifest

# ════════════════════════════════════════════════════════════════════════════
# 门身份 + 证据 producer key（中心注册/绿灯账据此钉）。gate_name 与门链其它节门同族短名。
# ════════════════════════════════════════════════════════════════════════════
# —— COST 门 ——
SECTION10_COST_GATE_NAME = "s10_cost"
SECTION10_COST_PRODUCER_KEY = "s10_cost_runjson_producers"
SECTION10_COST_MANIFEST_KEY = "section10_cost"
# —— CONTROL-PLANE 门 ——
SECTION10_CONTROLPLANE_GATE_NAME = "s10_controlplane"
SECTION10_CONTROLPLANE_PRODUCER_KEY = "s10_controlplane_runjson_producers"
SECTION10_CONTROLPLANE_MANIFEST_KEY = "section10_control_plane"

# canonical 成本族违例的判定 = validator 自己打的 field 标签（不硬编码码字符串·防漂）。
_COST_FIELDS = frozenset({"cost_model_refs", "tca_ref"})
# 门的消费码（promote 期策略·非 canonical validator 码）。
_STRONG_MISSING_COST_CODE = "s10_strong_claim_missing_cost_tca"
_RELAXED_CAPPED_CODE = "s10_relaxed_tier_strong_verdict_capped"

_COST_NOTHING_DECLARED = (
    "§10：manifest 未声明 section10_cost 结构 —— 无可证伪成本/TCA 违例"
    "（诚实限界：非『整本已查清』·查清由 producer 绿灯门负责）"
)
_COST_ALL_SATISFIED = "§10 成本/TCA 全部满足（强标签均携带成本证据·无成本族违例）"
_CP_NOTHING_DECLARED = (
    "§10：manifest 未声明 section10_control_plane 结构 —— 无可证伪档位封顶违例"
    "（诚实限界：非『整本已查清』·查清由 producer 绿灯门负责）"
)
_CP_ALL_SATISFIED = "§10 控制面全部满足（无放宽档把 verdict 显成强标签）"


def _present(value: Any) -> bool:
    """字符串存在性（非空·去空白）。trivial helper·非成本/档位判定逻辑。"""

    return bool(str(value or "").strip())


def _has_cost(record: Any) -> bool:
    """复用 record 已记录的成本字段：cost_model_refs 含**非空** ref 或 tca_ref 在场。

    严格非空（gaming-proof·codex 对抗复审后加固）：`cost_model_refs=[""]` 这类空白占位 ref **不算**
    成本证据（否则填个空串即可伪造「有成本」躲过门）。tca_ref 同理走 `_present` 去空白判存在。
    """

    refs = getattr(record, "cost_model_refs", ()) or ()
    return any(_present(r) for r in refs) or _present(getattr(record, "tca_ref", None))


def _record_ref(record: Any) -> str:
    return str(getattr(record, "validation_ref", "") or getattr(record, "depth_ref", "") or "")


def _dedup_codes(violations: list[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(code for code, _ in violations))  # 去重·保首现序


def _reason(prefix: str, violations: list[tuple[str, str]]) -> str:
    sample = "; ".join(f"{code}@{ref}" if ref else code for code, ref in violations[:8])
    more = "" if len(violations) <= 8 else f" …(+{len(violations) - 8})"
    return f"{prefix} {len(violations)} 项: {sample}{more}"


# ════════════════════════════════════════════════════════════════════════════
# COST 门：成本/TCA 缺 → 拦强标签声明（复用 methodology_validation·消费已记录字段）
# ════════════════════════════════════════════════════════════════════════════
def _validation_methodology_from_dict(d: Mapping[str, Any]) -> ValidationMethodologyRecord:
    """manifest dict → ValidationMethodologyRecord（faithful·字段名即 dataclass 字段名）。

    `sample_size` 走 `int(...)`：非数值 → 抛 → 由 `_collect_cost_family` fail-closed 记 unparseable。
    """

    return ValidationMethodologyRecord(
        validation_ref=str(d.get("validation_ref") or ""),
        claim_label=str(d.get("claim_label") or ""),
        sample_size=int(d.get("sample_size") or 0),
        pbo_ref=d.get("pbo_ref"),
        dsr_ref=d.get("dsr_ref"),
        bootstrap_ci_ref=d.get("bootstrap_ci_ref"),
        cpcv_ref=d.get("cpcv_ref"),
        walk_forward_ref=d.get("walk_forward_ref"),
        purge_embargo_ref=d.get("purge_embargo_ref"),
        honest_n_ref=d.get("honest_n_ref"),
        multiple_testing_ref=d.get("multiple_testing_ref"),
        cost_model_refs=d.get("cost_model_refs"),  # dataclass __post_init__ 归一为 tuple
        tca_ref=d.get("tca_ref"),
        methodology_choice_ref=d.get("methodology_choice_ref"),
        responsibility_boundary_ref=d.get("responsibility_boundary_ref"),
        user_waived_path=bool(d.get("user_waived_path", False)),
        target_environment=str(d.get("target_environment") or "research"),
    )


def _collect_cost_family(
    out: list[tuple[str, str]],
    section: Mapping[str, Any],
    key: str,
    adapter: Callable[[Mapping[str, Any]], Any],
    validator: Callable[[Any], MethodologyDecision],
    family: str,
) -> None:
    """跑一族 §10 成本结构 · fail-closed（不静默 skip 让违例溜走·codex C-S9 洞同款堵死）。

    缺省/None → 未声明（跳过·诚实空）；present 但非 list/tuple / list 内非 dict 项 → 记
    `section10_cost_<family>_malformed`（ok=False）；单条 adapt/validate 抛 → 记
    `section10_cost_<family>_unparseable`。每条 record：① canonical validator 的**成本族**违例
    （field ∈ {cost_model_refs, tca_ref}·单一源）；② 门消费策略：强标签缺成本 → `_STRONG_MISSING_COST_CODE`。
    """

    value = section.get(key)
    if value is None:
        return
    if not isinstance(value, (list, tuple)):
        out.append((f"section10_cost_{family}_malformed", ""))
        return
    for item in value:
        if not isinstance(item, Mapping):
            out.append((f"section10_cost_{family}_malformed", ""))
            continue
        try:
            record = adapter(dict(item))
        except Exception:  # noqa: BLE001 — 解析炸 → fail-closed（不静默放行·不炸整链）
            out.append((f"section10_cost_{family}_unparseable", ""))
            continue
        try:
            decision = validator(record)
        except Exception:  # noqa: BLE001
            out.append((f"section10_cost_{family}_unparseable", _record_ref(record)))
            continue
        for violation in getattr(decision, "violations", ()) or ():
            if getattr(violation, "field", "") in _COST_FIELDS:
                out.append((violation.code, violation.ref or ""))
        # 门消费：强标签声明必须携带成本/TCA（把「要求成本」从 runtime 环境扩到强标签·关 research 洞）。
        # claim_label 去空白后比对（gaming-proof：'evidence_sufficient ' 这类加空白变体也按强标签判）。
        if str(getattr(record, "claim_label", "") or "").strip() in METHODOLOGY_STRONG_LABELS and not _has_cost(record):
            out.append((_STRONG_MISSING_COST_CODE, _record_ref(record)))


def section10_cost_check(manifest: RunManifest) -> GateCheckResult:
    """§10 成本/TCA check：强标签缺成本 → ok=False（复用 canonical 成本族 + 门消费策略）。

    - 节缺省/为空 → ok=True（无可证伪违例·诚实限界见模块 docstring）。
    - 节存在但非 dict → ok=False（fail-closed）。
    - 任一族任一成本违例 → ok=False·missing=去重码·reason=带 ref 样本。
    """

    # 非 Mapping manifest → manifest.get 抛 → 由门链 _run_one fail-closed（errored·绝不静默放行）。
    section = manifest.get(SECTION10_COST_MANIFEST_KEY)

    if section is None:
        return GateCheckResult(ok=True, reason=_COST_NOTHING_DECLARED)
    if not isinstance(section, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§10 成本节存在但格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section10_cost_malformed",),
        )

    violations: list[tuple[str, str]] = []
    _collect_cost_family(
        violations, section, "validation_methodologies",
        _validation_methodology_from_dict, validate_validation_methodology, "validation_methodology",
    )
    _collect_cost_family(
        violations, section, "validation_depths",
        validation_depth_record_from_dict, validate_validation_depth, "validation_depth",
    )

    if not violations:
        return GateCheckResult(ok=True, reason=_COST_ALL_SATISFIED)
    return GateCheckResult(ok=False, reason=_reason("§10 成本/TCA 违例", violations), missing=_dedup_codes(violations))


# ════════════════════════════════════════════════════════════════════════════
# CONTROL-PLANE 门：放宽档把 verdict 显成强标签 → 封顶/拒（复用 control_plane.effective_label）
# ════════════════════════════════════════════════════════════════════════════
def _resolve_tier(item: Mapping[str, Any]) -> tuple[MethodologyTier | None, str | None]:
    """从一条 tier-claim 解析档位（复用 MethodologyTier + tier_of·不重写 tier 逻辑）。

    返回 `(tier, malformed_code)`：
      - tier 字段是合法档名 → (MethodologyTier, None)；
      - tier 字段非法值 / 非字符串 / methodology_choice 非 Mapping → (None, "..._malformed")（fail-closed）；
      - 仅给 methodology_choice 且 tier_of 命中 → (MethodologyTier, None)；tier_of 归 None → (None, None)（未解析）；
      - 两者皆缺 → (None, None)（未声明档位·由调用方按 claimed 强弱定 fail-closed/放过）。
    """

    raw_tier = item.get("tier")
    if isinstance(raw_tier, str) and raw_tier.strip():
        try:
            return MethodologyTier(raw_tier.strip()), None
        except ValueError:
            return None, "s10_control_plane_tier_malformed"  # 非法档名 = 格式非法·fail-closed
    if raw_tier is not None:
        return None, "s10_control_plane_tier_malformed"  # tier 在场但非字符串

    mc = item.get("methodology_choice")
    if mc is not None and not isinstance(mc, Mapping):
        return None, "s10_control_plane_tier_malformed"
    if isinstance(mc, Mapping):
        choice = MethodologyChoiceRecord(chosen_path=str(mc.get("chosen_path") or ""))
        return tier_of(choice), None  # tier_of 可能归 None（chosen_path 不映射到档位）

    return None, None  # 未声明档位


def _collect_control_plane(out: list[tuple[str, str]], claims: Iterable[Any]) -> None:
    """跑 tier-claims · fail-closed。每条：解析档位 → `effective_label` 封顶判定。

    - 项非 dict → malformed。
    - tier 非法 → malformed（fail-closed）。
    - tier 未解析（漏档位/tier_of 归 None）：claimed 是强标签 → unresolved（堵 dodge）；否则放过（无可封之物·不误拒）。
    - tier 解析出 + `effective_label(tier, claimed) != claimed` → 该 verdict 被档位封顶 → 拒。
    """

    for item in claims:
        if not isinstance(item, Mapping):
            out.append(("s10_control_plane_malformed", ""))
            continue
        # claimed_label 去空白（gaming-proof：'evidence_sufficient ' 加空白变体也按强标签判·防躲封顶）。
        claimed = str(item.get("claimed_label") or "").strip()
        tier, malformed = _resolve_tier(item)
        if malformed is not None:
            out.append((malformed, claimed))
            continue
        if tier is None:
            # 未解析出档位：声明强标签却无可核档位 → fail-closed（堵省略档位躲封顶的 dodge）。
            if claimed in SPINE_STRONG_LABELS:
                out.append(("s10_control_plane_tier_unresolved", claimed))
            continue
        try:
            downgraded = effective_label(tier, claimed)
        except Exception:  # noqa: BLE001 — effective_label 异常 → fail-closed（不静默放行）
            out.append(("s10_control_plane_unparseable", claimed))
            continue
        if downgraded != claimed:
            out.append((_RELAXED_CAPPED_CODE, f"{tier.value}:{claimed}->{downgraded}"))


def section10_controlplane_check(manifest: RunManifest) -> GateCheckResult:
    """§10 控制面 check：放宽档把 verdict 显成强标签 → ok=False（封到诚实标签）。

    - 节缺省/为空 / 无 tier_claims → ok=True（无可证伪违例·诚实限界）。
    - 节存在但非 dict / tier_claims 非 list → ok=False（fail-closed）。
    - 任一放宽档把强 verdict 显出 → ok=False·missing 含 `_RELAXED_CAPPED_CODE`。
    """

    section = manifest.get(SECTION10_CONTROLPLANE_MANIFEST_KEY)

    if section is None:
        return GateCheckResult(ok=True, reason=_CP_NOTHING_DECLARED)
    if not isinstance(section, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§10 控制面节存在但格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section10_control_plane_malformed",),
        )

    claims = section.get("tier_claims")
    if claims is None:
        return GateCheckResult(ok=True, reason=_CP_NOTHING_DECLARED)
    if not isinstance(claims, (list, tuple)):
        return GateCheckResult(
            ok=False,
            reason="§10 控制面 tier_claims 存在但格式非法（应为列表）—— fail-closed 视为未过",
            missing=("section10_control_plane_malformed",),
        )

    violations: list[tuple[str, str]] = []
    _collect_control_plane(violations, claims)

    if not violations:
        return GateCheckResult(ok=True, reason=_CP_ALL_SATISFIED)
    return GateCheckResult(
        ok=False, reason=_reason("§10 控制面封顶/违例", violations), missing=_dedup_codes(violations)
    )


# ════════════════════════════════════════════════════════════════════════════
# 注册（中心后续串 promote.py 时各调一次）
# ════════════════════════════════════════════════════════════════════════════
def register_section10_cost_gate(chain: PromoteGateChain, *, enforce_intent: bool = True) -> None:
    """把 §10 成本 check 注册进给定门链。

    用法（CENTER-SERIAL·第三波）：
        from app.release_gate.promote_gate_chain import default_chain
        from app.release_gate.section10_methodology_gate import register_section10_cost_gate
        register_section10_cost_gate(default_chain())

    `enforce_intent=True`：成本门有 GOAL「拒」语义（缺成本却声强标签 → 拒）·**有资格** enforce——但
    仅当 `s10_cost_runjson_producers` 转绿才真翻 enforce；未绿则被 SA-2 策略降级 advisory（绝不误拒）。
    """

    chain.register(
        gate_name=SECTION10_COST_GATE_NAME,
        check=section10_cost_check,
        required_producer=SECTION10_COST_PRODUCER_KEY,
        enforce_intent=enforce_intent,
    )


def register_section10_controlplane_gate(chain: PromoteGateChain, *, enforce_intent: bool = True) -> None:
    """把 §10 控制面 check 注册进给定门链。

    用法（CENTER-SERIAL·第三波）：
        from app.release_gate.promote_gate_chain import default_chain
        from app.release_gate.section10_methodology_gate import register_section10_controlplane_gate
        register_section10_controlplane_gate(default_chain())

    `enforce_intent=True`：控制面门有 GOAL「封顶」语义（放宽档显强 verdict → 封到诚实标签）·有资格
    enforce——仅当 `s10_controlplane_runjson_producers` 转绿才真翻 enforce；未绿则降级 advisory。
    """

    chain.register(
        gate_name=SECTION10_CONTROLPLANE_GATE_NAME,
        check=section10_controlplane_check,
        required_producer=SECTION10_CONTROLPLANE_PRODUCER_KEY,
        enforce_intent=enforce_intent,
    )


__all__ = [
    "SECTION10_COST_GATE_NAME",
    "SECTION10_COST_PRODUCER_KEY",
    "SECTION10_COST_MANIFEST_KEY",
    "SECTION10_CONTROLPLANE_GATE_NAME",
    "SECTION10_CONTROLPLANE_PRODUCER_KEY",
    "SECTION10_CONTROLPLANE_MANIFEST_KEY",
    "section10_cost_check",
    "section10_controlplane_check",
    "register_section10_cost_gate",
    "register_section10_controlplane_gate",
]
