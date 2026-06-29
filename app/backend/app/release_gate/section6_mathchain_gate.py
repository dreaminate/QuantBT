"""C-S6-MATHCHAIN-AUTOWRITE · §6 数学贯穿链发版 check（插 SA-3 promote 门链）。

这张卡只建 PARALLEL-SAFE 的 check + 注册函数——把（lineage 层已建的）§6 一致性硬门
`lineage.spine_gate.evaluate_promotion`（升级健全谓词 Π·8 必需子句）经 SA-3 门链接到 promote 收口，
关掉 codemap C-S6-MATHCHAIN-AUTOWRITE 点出的洞：`spine_gate.evaluate_promotion` 今 library-only，
从未在真 release/promote 决定上被调——一个**声称按理论实现、要升级到强标签**（evidence_sufficient /
proof_backed / production_ready）却**数学链残缺**的产物（公式无 binding / 缺 ConsistencyCheck / 实现与
定义不一致 / 实现改了没刷 binding / estimator 没绑 PIT / 理论没证却标 proof_backed / TheoryClaim 无
MathematicalArtifact）今天能溜过 release，把「理论正确但实现跑偏」（决策 D-MATH-SPINE）当系统正确放行。
**不**在此串进 `ide/promote.py`（那是后续 CENTER-SERIAL 的一次性改·两步法）；本模块是新建孤立件，
中心后续经 `gate_registry` 调 `register_section6_mathchain_gate(...)`（像 §16/§17 那样在单一注册清单加一行）。

═══ 复用不重造（RULES §1 单一源）═══
§6 数学链「能否升级到请求标签」判定的**唯一源**是 `lineage.spine_gate.evaluate_promotion`（8-clause Π）：
本模块**绝不**用 `research_os.spine.PromotionGuard`、**绝不**重写任何一条子句，连违例口径都直接搬运
evaluate_promotion 的 `SpineDecision.violations`（每条违例字符串原样进 missing）。与 §17（rdp 有
`from_dict`）的差异同 §16——`lineage.spine` 的 MathematicalArtifact / TheoryImplementationBinding /
ConsistencyCheck / MethodologyChoiceRecord **没有** `*_from_dict` 适配器，故本模块自带 4 个 dict→record
适配器（`_adapt_*`）。这些适配器**判定中立**：只做字段映射 + 类型 coercion（`str(... or "")` /
`_opt_float` / `_as_tuple`），**绝不**夹带任何升级判定——「过没过」整体委托 evaluate_promotion。
**不**透传外部 `*_id`（artifact_id/binding_id/check_id/choice_id 全由 dataclass `__post_init__` 内容
寻址重算·防伪造 id·与 §17 `RDPManifest.from_dict` 弃外部 rdp_id 同款防伪姿态）。

═══ 8 必需子句 → §6/§8「→ 拒」（GOAL §6 可证伪验收 + §8 治理脊柱·construction-map C-S6 可证伪点）═══
（口径全部来自 evaluate_promotion·本模块只搬运，绝不自判）
  - (1) binding-exists      §6 公式无 implementation/test binding ⇒ 不得 promoted。
  - (2) binding-complete    §8 TheoryImplementationBinding 缺 code_ref/config_ref/data_contract_ref ⇒ 拒。
  - (3) consistency-present §8 声称按理论实现但无决定性 ConsistencyCheck（监控/执行称有数学依据缺 CC）⇒ 拒。
  - (4) consistency-pass    §6 代码实现与数学定义不一致（ConsistencyCheck=fail）⇒ 拒。
  - (5) fresh               §6 实现改动后未刷新 binding（code_content_hash 失配 / 从未冻结）⇒ 拒。
  - (6) proof-honest        §6 理论证明被 user 跳过却请求 proof_backed/production_ready ⇒ 拒。
  - (7) pit-bound           §6 estimator/统计检验/数据时间语义未绑 PIT(known_at∧effective_at) ⇒ 拒。
  - (8) claim-grounded      §8 请求 proof_backed 但缺 MathematicalArtifact（statement/derivation 空）⇒ 拒。
弱/诚实标签（draft/exploratory/challenged/user_waived_*/custom_methodology）evaluate_promotion 恒
promotable=True（如实陈述「还没证 / 用户跳过」·不越权）→ 本门不拒（honest-bound·不误拒诚实 run）。

═══ 职责分离（gaming-proof）═══
check **只懂「这个 promote run 的 §6 数学链过没过」**，返回 `GateCheckResult(ok, reason, missing)`——它
**不**决定自己是 advisory 还是 enforce。advisory/enforce 由 SA-2 策略（`governance.enforcement_policy`）经
门链统一盖章：仅当 `s6_mathchain_runjson_producers`（§6 数学链结构进 manifest 的接线测试·把真 artifact/
真 binding/真 ConsistencyCheck 写进 manifest 那层）转绿，门才从 advisory 翻 enforce（LOCKED 决策 1）。
check 连 mode 字段都没有 → **无法自封 enforce 绕过 producer 绿灯门**。

═══ 诚实限界（RULES §3·设计极限·非残余）═══
`section6_mathchain` 缺省 / promotion_claims 缺省或空 → `ok=True`，语义是**「未声明 §6 数学链结构 ⇒ 无
可证伪数学违例」**，**不**代表「整本 run 已查清 §6」。「是否真有数学链证据被如实写进 manifest」由
producer 绿灯门（`s6_mathchain_runjson_producers` 接线测试 = 未来 C-S6-RUNJSON-PRODUCERS）负责——
producer 未绿时本门只 advisory，绝不在未接线门上误拒诚实 run。一条 claim 不声明 requested_label（或声明
弱标签）→ 默认 draft → evaluate_promotion 恒 promotable=True → 不拒（honest-bound：没有越权标注就无可证伪
违例·过强标签是 producer 契约的事·缺标签的强晋级由 producer 绿灯门兜）。节/claim 存在但格式非法（节非
dict / promotion_claims 非 list / claim 非 dict / 子对象非 dict / record 解析炸 / evaluate 炸）→ fail-closed
记 ok=False（codex 在 C-S9 找到的「非 list/非 dict 静默 skip 让违例溜走」洞，本模块同款堵死·绝不 fail-open）。

═══ 委托边界（诚实限界·非本门 fail-open）═══
本门**严格只与 `lineage.spine_gate.evaluate_promotion` 同强**——它判 promotable 的本门放，它判
not promotable 的本门拒。适配器对「present 即算有」的边界（如 `_as_tuple` 把标量裹成 1 元组·空白
test_refs 视为缺）遵 spine_gate / spine `__post_init__` 单一源语义，本门遵「reuse·不擅改 spine_gate」只
忠实委托·绝不在网关层重写任何子句（= 防 §1 单一源漂移）。门绝不声称证明了任何下游数学命题（同
spine_gate 的诚实口径）——它只判「声明 vs 证据自洽 + 标签强度匹配」。

═══ 冷导入安全 ═══
顶层只 import 同包 `promote_gate_chain`（cold-safe·已证）与 lineage 子模块 `lineage.spine` /
`lineage.spine_gate`（纯 dataclass + stdlib·`spine→ids` 只触 ast/hashlib/unicodedata·经实证不触 governance
冷循环）。**不**在顶层 import governance（SA-2 符号由门链在 evaluate 期惰性载入）。**不**碰
`release_gate/__init__.py`（既有冷导入环·SA-3 note）——消费方从本子模块直接 import。模块**无 import 期
副作用**（不 auto-register）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..lineage.spine import (
    PROOF_UNPROVEN,
    LABEL_DRAFT,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from ..lineage.spine_gate import SpineDecision, evaluate_promotion
from .promote_gate_chain import GateCheckResult, PromoteGateChain, RunManifest

# —— 门身份 + 证据 producer key（中心注册/绿灯账据此钉）。gate_name 与门链其它节门同族短名 ——
SECTION6_MATHCHAIN_GATE_NAME = "s6_mathchain"
# 证据 producer：§6 数学链结构进 promote manifest 的接线测试。转绿前门停 advisory（LOCKED 决策 1）。
SECTION6_MATHCHAIN_PRODUCER_KEY = "s6_mathchain_runjson_producers"
# manifest 里承载 §6 数学链的 key（producer 填·check 读）。其值是一个 dict：
#   {"promotion_claims": [ {requested_label, artifact{...}, binding{...}, consistency_checks[...],
#                           choice{...}?, data_contract{...}?, current_code_hash?, asset_ref?}, ... ]}
# 每条 claim = 一个「要升级到 requested_label 的数学产物」·整体喂 evaluate_promotion。
SECTION6_MATHCHAIN_MANIFEST_KEY = "section6_mathchain"

# 子键名（producer 契约）。
_CLAIMS_KEY = "promotion_claims"
_ARTIFACT_KEY = "artifact"
_BINDING_KEY = "binding"
_CHECKS_KEY = "consistency_checks"
_CHOICE_KEY = "choice"
_DATA_CONTRACT_KEY = "data_contract"

_NOTHING_DECLARED = (
    "§6：manifest 未声明 section6_mathchain 数学链结构（无 promotion_claims）—— 无可证伪数学违例"
    "（诚实限界：非『整本已查清』·查清由 producer 绿灯门负责）"
)
_ALL_SATISFIED = "§6 数学链全部满足（已声明的升级断言均过一致性门 8 子句·无越权标注）"


def _opt_str(value: Any) -> str | None:
    """判定中立的 str|None coercion：None 原样保留，余者转 str。"""

    return None if value is None else str(value)


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)  # 非数 → 抛 → 调用方 fail-closed 记 unparseable


def _as_tuple(value: Any) -> tuple[str, ...]:
    """判定中立的 str-tuple coercion（spine 的 *_refs / 描述 tuple 字段均 tuple[str,...]）。

    None→()·list/tuple→逐项·裸标量→1 元素；**只保留非空白 str**——非 str（dict/标量）与空白元素一律丢弃。
    为何不裸 `(value,)`：那会把 malformed 值 fabricate 成幽灵 ref，让读 `bool(test_refs)` 的 truthy 子句
    （binding-exists）误绿（codex 复审堵的 fail-open：`test_refs={...}` / `test_refs=""` / `test_refs=[""]`
    绝不冒充「有 test/impl binding」）。丢弃 malformed 元素 → 该 tuple 空 → 对应 truthy 子句 fail-closed 拒，
    与 §17 hollow-values 去空白同纪律。**绝不**判「过没过」——空否的语义后果全留给 evaluate_promotion。
    """

    if value is None:
        return ()
    items = value if isinstance(value, (list, tuple)) else (value,)
    return tuple(x for x in items if isinstance(x, str) and x.strip())


# ════════════════════════════════════════════════════════════════════════════
# 4 个 dict→record 适配器（判定中立·lineage.spine 无 `*_from_dict`·故本模块自带）。
# **绝不**夹带升级判定——只字段映射 + 类型 coercion·不透传 *_id（dataclass 内容寻址重算·防伪造）。
# 判定全留给 evaluate_promotion。
# ════════════════════════════════════════════════════════════════════════════
def _adapt_artifact(d: Mapping[str, Any]) -> MathematicalArtifact:
    """§6 MathematicalArtifact 字段 → canonical record。

    `proof_status` 缺省 → PROOF_UNPROVEN（合法默认·不触 proof-honest 误判）；显式非法值（如 'garbage'）→
    `MathematicalArtifact.__post_init__` raise → 调用方 fail-closed 记 unparseable。`artifact_id` 不透传
    （内容寻址重算·防伪造）。
    """

    return MathematicalArtifact(
        artifact_type=str(d.get("artifact_type") or ""),
        statement=str(d.get("statement") or ""),
        notation=str(d.get("notation") or ""),
        assumptions=_as_tuple(d.get("assumptions")),
        definition=str(d.get("definition") or ""),
        derivation=str(d.get("derivation") or ""),
        proof_sketch=str(d.get("proof_sketch") or ""),
        counterexamples=_as_tuple(d.get("counterexamples")),
        units=str(d.get("units") or ""),
        applicability=str(d.get("applicability") or ""),
        failure_conditions=_as_tuple(d.get("failure_conditions")),
        proof_status=str(d.get("proof_status") or PROOF_UNPROVEN),
        implementation_ref=str(d.get("implementation_ref") or ""),
        test_ref=str(d.get("test_ref") or ""),
        simulation_ref=str(d.get("simulation_ref") or ""),
        validation_ref=str(d.get("validation_ref") or ""),
        used_by=_as_tuple(d.get("used_by")),
    )


def _adapt_binding(d: Mapping[str, Any]) -> TheoryImplementationBinding:
    """§6 TheoryImplementationBinding 字段 → canonical record（`binding_id` 内容寻址重算·不透传）。"""

    return TheoryImplementationBinding(
        theory_ref=str(d.get("theory_ref") or ""),
        code_ref=str(d.get("code_ref") or ""),
        code_content_hash=str(d.get("code_content_hash") or ""),
        config_ref=str(d.get("config_ref") or ""),
        data_contract_ref=str(d.get("data_contract_ref") or ""),
        implementation_spec=str(d.get("implementation_spec") or ""),
        test_refs=_as_tuple(d.get("test_refs")),
        simulation_refs=_as_tuple(d.get("simulation_refs")),
        numerical_check_refs=_as_tuple(d.get("numerical_check_refs")),
        symbol_mapping=dict(d.get("symbol_mapping") or {}),
        unit_mapping=dict(d.get("unit_mapping") or {}),
        dimension_check=str(d.get("dimension_check") or ""),
        tolerance=_opt_float(d.get("tolerance")),
        known_differences=_as_tuple(d.get("known_differences")),
        consistency_verdict=str(d.get("consistency_verdict") or ""),
        verifier_ref=str(d.get("verifier_ref") or ""),
        waiver_ref=str(d.get("waiver_ref") or ""),
        used_by=_as_tuple(d.get("used_by")),
    )


def _adapt_consistency_check(d: Mapping[str, Any]) -> ConsistencyCheck:
    """§6 ConsistencyCheck 字段 → canonical record。

    `check_type` / `result` 缺省 → "" → 非 CHECK_TYPES / CHECK_RESULTS → `ConsistencyCheck.__post_init__`
    raise → 调用方 fail-closed 记 unparseable（一条没有类型/结果的 check 无从判定·绝不静默放行）。
    `check_id` 内容寻址重算·不透传。
    """

    return ConsistencyCheck(
        binding_id=str(d.get("binding_id") or ""),
        check_type=str(d.get("check_type") or ""),
        result=str(d.get("result") or ""),
        input_refs=_as_tuple(d.get("input_refs")),
        expected_property=str(d.get("expected_property") or ""),
        observed_property=str(d.get("observed_property") or ""),
        tolerance=_opt_float(d.get("tolerance")),
        failure_reason=str(d.get("failure_reason") or ""),
        affected_assets=_as_tuple(d.get("affected_assets")),
        repair_plan=str(d.get("repair_plan") or ""),
        verifier_ref=str(d.get("verifier_ref") or ""),
        timestamp=str(d.get("timestamp") or ""),
    )


def _adapt_choice(d: Mapping[str, Any]) -> MethodologyChoiceRecord:
    """§6 MethodologyChoiceRecord 字段 → canonical record（`choice_id` 内容寻址重算·不透传）。"""

    return MethodologyChoiceRecord(
        chosen_path=str(d.get("chosen_path") or ""),
        asset_ref=str(d.get("asset_ref") or ""),
        run_ref=str(d.get("run_ref") or ""),
        available_options=_as_tuple(d.get("available_options")),
        recommendation=str(d.get("recommendation") or ""),
        tradeoffs_shown=_as_tuple(d.get("tradeoffs_shown")),
        risks_shown=_as_tuple(d.get("risks_shown")),
        skipped_steps=_as_tuple(d.get("skipped_steps")),
        responsibility_boundary=str(d.get("responsibility_boundary") or ""),
        actor=str(d.get("actor") or ""),
        allowed_environment=str(d.get("allowed_environment") or ""),
        display_label=str(d.get("display_label") or ""),
    )


def _collect(decision: SpineDecision, asset_ref: str, violations: list[tuple[str, str]]) -> None:
    """把一条 canonical 升级裁定的违例搬进聚合表（**单一 mutation 锚点**）。

    ★ mutation 三态（见 test 文件头）：把下面 `if not decision.promotable:` 弱化成 `if False:`（无视
      spine_gate.evaluate_promotion 的 Π 裁定·让残缺数学链溜成 ok=True）→ binding-exists / binding-complete /
      consistency-present / consistency-pass / fresh / proof-honest / pit-bound / claim-grounded 全族对抗
      测试转 RED → 还原 → GREEN。违例口径**逐条原样**来自 `decision.violations`（绝不重写子句·复用不重造）。
    """

    if not decision.promotable:
        for v in decision.violations:
            violations.append((v, asset_ref))


def _evaluate_claim(claim: Any, idx: int, violations: list[tuple[str, str]]) -> None:
    """评估一条升级 claim：dict→record 适配 → 委托 evaluate_promotion → 收违例。fail-closed 不静默放行。

    - claim 非 dict / 子对象（artifact/binding/choice/data_contract）present 但非 dict /
      consistency_checks present 但非 list|dict|其内含非 dict 项 → 记 *_malformed（ok=False·不当空通过）。
    - 任一 adapter 抛（proof_status/check_type/result 非法等）→ 记 claim_unparseable。
    - evaluate_promotion 抛 → 记 evaluation_unparseable。
    - 否则把裁定交 `_collect`：promotable=False ⇒ 搬 canonical 违例；promotable=True ⇒ 无违例。
    """

    pos = f"claim#{idx}"
    if not isinstance(claim, Mapping):
        violations.append(("section6_mathchain_claim_malformed", pos))
        return

    asset_ref = str(claim.get("asset_ref") or pos)

    artifact_d = claim.get(_ARTIFACT_KEY)
    binding_d = claim.get(_BINDING_KEY)
    choice_d = claim.get(_CHOICE_KEY)
    dc_d = claim.get(_DATA_CONTRACT_KEY)

    # —— 子对象形态 fail-closed（present 但非 dict 不静默放行）——
    if artifact_d is not None and not isinstance(artifact_d, Mapping):
        violations.append(("section6_mathchain_artifact_malformed", asset_ref))
        return
    if binding_d is not None and not isinstance(binding_d, Mapping):
        violations.append(("section6_mathchain_binding_malformed", asset_ref))
        return
    if choice_d is not None and not isinstance(choice_d, Mapping):
        violations.append(("section6_mathchain_choice_malformed", asset_ref))
        return
    if dc_d is not None and not isinstance(dc_d, Mapping):
        violations.append(("section6_mathchain_data_contract_malformed", asset_ref))
        return

    # —— consistency_checks 归一（None→[]·单 dict→[dict]·list→list）+ 元素形态守卫 ——
    raw_checks = claim.get(_CHECKS_KEY)
    if raw_checks is None:
        check_dicts: list[Any] = []
    elif isinstance(raw_checks, Mapping):
        check_dicts = [raw_checks]
    elif isinstance(raw_checks, (list, tuple)):
        check_dicts = list(raw_checks)
    else:
        violations.append(("section6_mathchain_consistency_checks_malformed", asset_ref))
        return
    for c in check_dicts:
        if not isinstance(c, Mapping):
            violations.append(("section6_mathchain_consistency_checks_malformed", asset_ref))
            return

    # —— dict→record 适配（fail-closed·任一构造炸 → unparseable·不静默放行半成品冒充正式产物）——
    try:
        artifact = _adapt_artifact(dict(artifact_d)) if artifact_d is not None else None
        binding = _adapt_binding(dict(binding_d)) if binding_d is not None else None
        checks = [_adapt_consistency_check(dict(c)) for c in check_dicts]
        choice = _adapt_choice(dict(choice_d)) if choice_d is not None else None
    except Exception as exc:  # noqa: BLE001 — 构造炸 → fail-closed（记违例·不静默 ok=True·不炸整链）
        violations.append(
            ("section6_mathchain_claim_unparseable", f"{asset_ref}:{type(exc).__name__}")
        )
        return

    # requested_label：缺省/弱标签 → evaluate_promotion 恒 promotable=True（honest-bound·不误拒）。
    # ★ fail-closed（codex 复审）：非 str（list/int…）→ malformed·**绝不** str() 成「未知弱标签」把强晋级
    #   （production_ready 等）悄悄降级放行；str 先 strip——带空白的强标签按真标签判（防 'production_ready '
    #   被当未知弱标签绕过强标签义务）；strip 后空 → draft（无强声明·honest）。
    raw_label = claim.get("requested_label")
    if raw_label is None:
        requested_label = LABEL_DRAFT
    elif isinstance(raw_label, str):
        requested_label = raw_label.strip() or LABEL_DRAFT
    else:
        violations.append(("section6_mathchain_requested_label_malformed", asset_ref))
        return
    current_code_hash = _opt_str(claim.get("current_code_hash"))
    data_contract = dict(dc_d) if dc_d is not None else None

    # —— 升级判定**单一源**：整体委托 spine_gate.evaluate_promotion（8-clause Π·绝不重写任何子句）——
    try:
        decision = evaluate_promotion(
            artifact,
            binding,
            checks,
            requested_label=requested_label,
            current_code_hash=current_code_hash,
            choice=choice,
            data_contract=data_contract,
        )
    except Exception as exc:  # noqa: BLE001 — 判定炸 → fail-closed（记违例·绝不静默 ok=True 放行）
        violations.append(
            ("section6_mathchain_evaluation_unparseable", f"{asset_ref}:{type(exc).__name__}")
        )
        return

    _collect(decision, asset_ref, violations)


# ════════════════════════════════════════════════════════════════════════════
# 公开 check：promote manifest → GateCheckResult（门链插它）
# ════════════════════════════════════════════════════════════════════════════
def section6_mathchain_check(manifest: RunManifest) -> GateCheckResult:
    """§6 数学贯穿链发版 check：把每条升级 claim 喂 spine_gate.evaluate_promotion·聚合违例·返回过/不过。

    - 节缺省 / promotion_claims 缺省或空 → ok=True（无可证伪违例·诚实限界见模块 docstring）。
    - 节非 dict / promotion_claims 非 list / claim 非 dict / 子对象非 dict / record 解析炸 / evaluate 炸 →
      ok=False（fail-closed·格式非法不静默放行）。
    - 任一 claim not promotable（公式无 binding / 缺 ConsistencyCheck / 实现↔定义不一致 / binding 过期 /
      理论没证标 proof_backed / estimator 没绑 PIT / TheoryClaim 无 MathematicalArtifact）→ ok=False·
      missing=去重违例（逐条原样来自 evaluate_promotion.violations）·reason=带 asset_ref 样本。

    判定**单一源**：整体委托 `lineage.spine_gate.evaluate_promotion`（不碰 advisory/enforce·不重写任何子句）。
    """

    # 非 Mapping manifest → manifest.get 抛 → 由门链 _run_one fail-closed（errored·绝不静默放行）。
    # 刻意不在此 catch 成 ok=True（那是 fail-open）。
    section = manifest.get(SECTION6_MATHCHAIN_MANIFEST_KEY)

    if section is None:
        return GateCheckResult(ok=True, reason=_NOTHING_DECLARED)
    if not isinstance(section, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§6 数学链节存在但格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section6_mathchain_malformed",),
        )

    claims = section.get(_CLAIMS_KEY)
    if claims is None:
        return GateCheckResult(ok=True, reason=_NOTHING_DECLARED)
    if not isinstance(claims, (list, tuple)):
        return GateCheckResult(
            ok=False,
            reason="§6 数学链 promotion_claims 格式非法（应为列表）—— fail-closed 视为未过",
            missing=("section6_mathchain_promotion_claims_malformed",),
        )
    if len(claims) == 0:
        return GateCheckResult(ok=True, reason=_NOTHING_DECLARED)

    violations: list[tuple[str, str]] = []
    for idx, claim in enumerate(claims):
        _evaluate_claim(claim, idx, violations)

    if not violations:
        return GateCheckResult(ok=True, reason=_ALL_SATISFIED)

    codes = tuple(dict.fromkeys(code for code, _ in violations))  # 去重·保首现序
    sample = "; ".join(f"{code}@{ref}" if ref else code for code, ref in violations[:6])
    more = "" if len(violations) <= 6 else f" …(+{len(violations) - 6})"
    reason = f"§6 数学链违例 {len(violations)} 项: {sample}{more}"
    return GateCheckResult(ok=False, reason=reason, missing=codes)


def register_section6_mathchain_gate(
    chain: PromoteGateChain, *, enforce_intent: bool = True
) -> None:
    """把 §6 数学链发版 check 注册进给定门链（中心后续经 gate_registry 串 promote.py 时调一次）。

    用法（CENTER-SERIAL·经单一注册收口）：
        from app.release_gate.gate_registry import ensure_default_chain  # 加本门后含它
        ensure_default_chain().evaluate(manifest, producer_status=ledger)

    `enforce_intent=True`：§6 门有 GOAL「拒」语义（数学链残缺却要升级强标签 → 拒发版），**有资格**
    enforce——但仅当 `s6_mathchain_runjson_producers` 转绿才真翻 enforce；未绿则被 SA-2 策略降级
    advisory + 记录（绝不误拒诚实 run）。check 无 mode 字段·无从自封 enforce。
    """

    chain.register(
        gate_name=SECTION6_MATHCHAIN_GATE_NAME,
        check=section6_mathchain_check,
        required_producer=SECTION6_MATHCHAIN_PRODUCER_KEY,
        enforce_intent=enforce_intent,
    )


__all__ = [
    "SECTION6_MATHCHAIN_GATE_NAME",
    "SECTION6_MATHCHAIN_PRODUCER_KEY",
    "SECTION6_MATHCHAIN_MANIFEST_KEY",
    "section6_mathchain_check",
    "register_section6_mathchain_gate",
]
