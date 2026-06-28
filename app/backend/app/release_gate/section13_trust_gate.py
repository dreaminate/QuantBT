"""C-S13-RELEASE-ENFORCE · §13 信任发版 check（插 SA-3 promote 门链）。

这张卡只建 PARALLEL-SAFE 的 check + 注册函数——把（库级已建的）§13 信任发版门经 SA-3 门链接到
promote 收口，关掉 codemap 点出的洞：信任层判定（`research_os/trust_layer.py`）今 advisory-only，
`require_trustworthy()` 从未在 release/promote 决定上被调——谄媚强结论 / 藏弱点 / mock 不诚实 / 冷启动
冒充统计证据的 run 今天能溜过 release。**不**在此串进 `ide/promote.py`（那是后续 CENTER-SERIAL 的一次性
改·两步法）；本模块是新建孤立件，中心后续经 `gate_registry` 调 `register_section13_trust_gate(...)`。

═══ 复用不重造（RULES §1 单一源）═══
§13 信任判定的唯一源是 `research_os.trust_layer`：本模块**只**做 manifest(dict)→canonical record 的薄
适配（全程复用 trust_layer 自己的 `*_from_dict` 适配器），再把判定**整体委托**给 canonical 聚合器
`validate_trust_layer(...)`——它内部循环 `validate_trust_claim` / `validate_external_expert_review` /
`validate_user_autonomy` / `validate_trust_release_gate` / `validate_trust_release_check` /
`validate_trust_pressure_run` / `validate_trust_release_approval` / `validate_functional_independence`。
本模块**绝不**重写任何一条信任门判定，连违例码都直接搬运 trust_layer 的原码。

═══ 5 道发版门 → trust_layer 违例（construction-map C-S13 的可证伪点）═══
  - 反谄媚施压（anti-sycophancy）：用户 wishful → 强标签 ⇒ `wishful_pressure_strong_conclusion`；
    强标签无证据 ⇒ `strong_claim_without_evidence`。
  - 弱点折叠（weakness-fold）：弱点默认隐藏 ⇒ `weakness_hidden_by_default` /
    `user_waived_weakness_hidden`。
  - 冷启动（cold-start）：N≤1 冒充统计证据撑强标签 ⇒ `cold_start_packaged_as_statistical_evidence`。
  - mock 诚实（mock-honesty）：发版 check / 施压跑 / 专家评审 / 审批 靠静默 mock 兜底 ⇒
    `*_silent_mock_fallback`。
  - 专家否决（expert-veto）：评审记成 agent/system/self、缺否决理由、verdict 非法 ⇒
    `external_expert_review_*`。

═══ 职责分离（gaming-proof）═══
check **只懂「这个 promote run 的 §13 信任过没过」**，返回 `GateCheckResult(ok, reason, missing)`——它
**不**决定自己是 advisory 还是 enforce。advisory/enforce 由 SA-2 策略（`governance.enforcement_policy`）
经门链统一盖章：仅当 `s13_trust_runjson_producers`（§13 信任结构进 manifest 的接线测试）转绿，门才从
advisory 翻 enforce（LOCKED 决策 1）。check 连 mode 字段都没有 → **无法自封 enforce 绕过 producer 绿灯门**。

═══ 诚实限界（RULES §3·设计极限·非残余）═══
`section13_trust` 缺省/为空 → `ok=True`，语义是**「未声明 §13 信任结构 ⇒ 无可证伪信任违例」**，**不**代表
「整本 run 已查清 §13」。「是否真有信任资产被如实写进 manifest」由 producer 绿灯门
（`s13_trust_runjson_producers` 接线测试）负责——producer 未绿时本门只 advisory，绝不在未接线门上误拒
诚实 run。节存在但格式非法（非 dict / 族非 list / 项非 dict / record 解析炸）→ fail-closed 记 ok=False
（codex 在 C-S9 找到的「非 list 族静默 skip 让违例溜走」洞，本模块同款堵死·绝不 fail-open）。

═══ 委托边界（诚实限界·非本门 fail-open·canonical trust_layer 加固候选已上报中心）═══
本门**严格只与 trust_layer.validate_trust_layer 同强**——它判过的本门判过，它放过的本门放过。codex 对抗
复审发现 canonical 判定层有三处 gaming 缺口，**均属 trust_layer.py 单一源加固范畴**（本门遵「reuse·不擅改
trust_layer」只忠实委托·绝不在网关层重写判定 = 防 §1 单一源漂移），已作为发现上报中心：
  ① `validate_trust_claim` 用**不去空白/不归一大小写**的 `claim_label` 比 STRONG_CLAIMS —— `'evidence_sufficient '`
     / `'Evidence_Sufficient'` 这类变体会逃出反谄媚 / 强标签无证据 / 冷启动三门（真实 producer 出 enum 小写值
     ⇒ 真路径无此 dodge·属对手手搓 manifest 的稳健性缺口）。
  ② 各 validator 的 ref-list 空判用 `not refs` —— `evidence_refs=[""]` 这类空白占位 ref 被当「有证据」（应逐项
     去空白判存在·参 section10 `_has_cost`）。
  ③ `validate_trust_layer` 逐条独立校验 —— 不交叉核对 approval.expert_review_ref ↔ 被引 expert_review.verdict
     （该跨记录一致性在 `record_trust_release_approval` builder 内·聚合器不覆盖）。

═══ 冷导入安全 ═══
顶层只 import 同包 `promote_gate_chain`（cold-safe·已证）与 `research_os.trust_layer`（经 `python -c`
实证冷导入安全·只触 lineage.ids + cryptography·不触 governance 冷循环）。**不**在顶层 import
governance（SA-2 符号由门链在 evaluate 期惰性载入）。**不**碰 `release_gate/__init__.py`（既有冷导入环·
SA-3 note）——消费方从本子模块直接 import。模块**无 import 期副作用**（不 auto-register）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from ..research_os.trust_layer import (
    TrustLayerDecision,
    external_expert_review_from_dict,
    functional_independence_disclosure_from_dict,
    trust_claim_record_from_dict,
    trust_pressure_run_record_from_dict,
    trust_release_approval_record_from_dict,
    trust_release_check_record_from_dict,
    trust_release_gate_record_from_dict,
    user_autonomy_record_from_dict,
    validate_trust_layer,
)
from .promote_gate_chain import GateCheckResult, PromoteGateChain, RunManifest

# —— 门身份 + 证据 producer key（中心注册/绿灯账据此钉）。gate_name 与门链其它节门同族短名 ——
SECTION13_TRUST_GATE_NAME = "s13_trust"
# 证据 producer：§13 信任结构进 promote manifest 的接线测试。转绿前门停 advisory（LOCKED 决策 1）。
SECTION13_TRUST_PRODUCER_KEY = "s13_trust_runjson_producers"
# manifest 里承载 §13 信任结构的 key（producer 填·check 读）。
SECTION13_TRUST_MANIFEST_KEY = "section13_trust"

_NOTHING_DECLARED = (
    "§13：manifest 未声明 section13_trust 结构 —— 无可证伪信任违例"
    "（诚实限界：非『整本已查清』·查清由 producer 绿灯门负责）"
)
_ALL_SATISFIED = "§13 信任发版全部满足（已声明信任结构无违例）"

# ════════════════════════════════════════════════════════════════════════════
# 每族：(manifest_key, validate_trust_layer 的 kwarg, dict→record 适配器, family 标签)。
# 适配器**全是 trust_layer.py 的 canonical `*_from_dict`**（单一源·不另造）；判定全委托
# validate_trust_layer。**mutation 目标**：注释掉 trust_claims 这一行 → 谄媚/藏弱点/冷启动不再被收集
# → 对应对抗测试转 RED（见 test_section13_trust_gate 文件头 mutation 三态）。
# ════════════════════════════════════════════════════════════════════════════
_FAMILIES: tuple[tuple[str, str, Callable[[dict[str, Any]], Any], str], ...] = (
    ("trust_claims", "claims", trust_claim_record_from_dict, "trust_claim"),
    ("independence_disclosures", "independence_disclosures",
     functional_independence_disclosure_from_dict, "independence_disclosure"),
    ("expert_reviews", "expert_reviews", external_expert_review_from_dict, "expert_review"),
    ("user_choices", "user_choices", user_autonomy_record_from_dict, "user_autonomy"),
    ("release_gates", "release_gates", trust_release_gate_record_from_dict, "release_gate"),
    ("release_checks", "release_checks", trust_release_check_record_from_dict, "release_check"),
    ("pressure_runs", "pressure_runs", trust_pressure_run_record_from_dict, "pressure_run"),
    ("release_approvals", "release_approvals",
     trust_release_approval_record_from_dict, "release_approval"),
)

# canonical record 的 ref 字段名（各族不同·取首个非空作样本·纯展示·非判定）。
_REF_KEYS = (
    "claim_ref", "disclosure_ref", "review_ref", "choice_ref",
    "check_ref", "runner_ref", "approval_ref", "release_ref", "ref",
)


def _ref_of(d: Mapping[str, Any]) -> str:
    for key in _REF_KEYS:
        val = d.get(key)
        if val:
            return str(val)
    return ""


def _parse_family(
    section: Mapping[str, Any],
    manifest_key: str,
    adapter: Callable[[dict[str, Any]], Any],
    family: str,
    malformed: list[tuple[str, str]],
) -> list[Any]:
    """把一族 §13 信任 dict 解析成 canonical record · fail-closed（不静默 skip 让违例溜走）。

    缺省/None → 未声明（返回空·诚实空）；present 但非 list/tuple（被填成 {id:rec} 映射 / 标量）→ 记
    `section13_trust_<family>_malformed`（ok=False·不当空通过）；list 内非 dict 项 → 同样 malformed；
    单条 from_dict 抛 → 记 `section13_trust_<family>_unparseable`。**只做 dict→record 适配
    （trust_layer canonical `*_from_dict`）**，信任判定留给 validate_trust_layer。
    """

    value = section.get(manifest_key)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        malformed.append((f"section13_trust_{family}_malformed", ""))
        return []
    records: list[Any] = []
    for item in value:
        if not isinstance(item, Mapping):
            malformed.append((f"section13_trust_{family}_malformed", ""))
            continue
        try:
            records.append(adapter(dict(item)))
        except Exception:  # noqa: BLE001 — 解析炸 → fail-closed（记族违例·不静默放行·不炸整链）
            malformed.append((f"section13_trust_{family}_unparseable", _ref_of(item)))
    return records


# ════════════════════════════════════════════════════════════════════════════
# 公开 check：promote manifest → GateCheckResult（门链插它）
# ════════════════════════════════════════════════════════════════════════════
def section13_trust_check(manifest: RunManifest) -> GateCheckResult:
    """§13 信任发版 check：把信任结构喂 trust_layer canonical 判定·聚合违例·返回过/不过。

    - 节缺省/为空 → ok=True（无可证伪违例·诚实限界见模块 docstring）。
    - 节存在但非 dict → ok=False（fail-closed·格式非法不静默放行）。
    - 任一族任一信任违例（谄媚强结论 / 藏弱点 / mock 不诚实 / 冷启动冒充统计证据 / 专家否决缺据 …）
      → ok=False·missing=去重违例码（全来自 trust_layer canonical validator）·reason=带 ref 样本。

    判定**单一源**：全委托 `trust_layer.validate_trust_layer`（不碰 advisory/enforce·不重写任何门判定）。
    """

    # 非 Mapping manifest → manifest.get 抛 → 由门链 _run_one fail-closed（errored·绝不静默放行）。
    # 刻意不在此 catch 成 ok=True（那是 fail-open）。
    section = manifest.get(SECTION13_TRUST_MANIFEST_KEY)

    if section is None:
        return GateCheckResult(ok=True, reason=_NOTHING_DECLARED)
    if not isinstance(section, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§13 信任节存在但格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section13_trust_malformed",),
        )

    violations: list[tuple[str, str]] = []
    buckets: dict[str, list[Any]] = {}
    for manifest_key, kwarg, adapter, family in _FAMILIES:
        buckets[kwarg] = _parse_family(section, manifest_key, adapter, family, violations)

    # —— 信任判定**单一源**：全委托 trust_layer.validate_trust_layer（绝不重写任何门判定）——
    # 用 `.get(..., ())` 取桶：注释掉 _FAMILIES 任一行（mutation）只让该族变空·不 KeyError 崩链。
    try:
        decision: TrustLayerDecision = validate_trust_layer(
            claims=tuple(buckets.get("claims", ())),
            independence_disclosures=tuple(buckets.get("independence_disclosures", ())),
            expert_reviews=tuple(buckets.get("expert_reviews", ())),
            user_choices=tuple(buckets.get("user_choices", ())),
            release_gates=tuple(buckets.get("release_gates", ())),
            release_checks=tuple(buckets.get("release_checks", ())),
            pressure_runs=tuple(buckets.get("pressure_runs", ())),
            release_approvals=tuple(buckets.get("release_approvals", ())),
        )
    except Exception as exc:  # noqa: BLE001 — 判定炸 → fail-closed（记违例·绝不静默 ok=True 放行）
        violations.append(("section13_trust_evaluation_unparseable", type(exc).__name__))
    else:
        for violation in decision.violations:
            violations.append((violation.code, violation.ref or ""))

    if not violations:
        return GateCheckResult(ok=True, reason=_ALL_SATISFIED)

    codes = tuple(dict.fromkeys(code for code, _ in violations))  # 去重·保首现序
    sample = "; ".join(f"{code}@{ref}" if ref else code for code, ref in violations[:8])
    more = "" if len(violations) <= 8 else f" …(+{len(violations) - 8})"
    reason = f"§13 信任发版违例 {len(violations)} 项: {sample}{more}"
    return GateCheckResult(ok=False, reason=reason, missing=codes)


def register_section13_trust_gate(
    chain: PromoteGateChain, *, enforce_intent: bool = True
) -> None:
    """把 §13 信任发版 check 注册进给定门链（中心后续经 gate_registry 串 promote.py 时调一次）。

    用法（CENTER-SERIAL·经单一注册收口）：
        from app.release_gate.gate_registry import ensure_default_chain  # 已含本门
        ensure_default_chain().evaluate(manifest, producer_status=ledger)

    `enforce_intent=True`：§13 门有 GOAL「拒」语义（谄媚强结论 / 藏弱点 / mock 不诚实 / 冷启动冒充统计
    证据 → 拒发版），**有资格** enforce——但仅当 `s13_trust_runjson_producers` 转绿才真翻 enforce；未绿
    则被 SA-2 策略降级 advisory + 记录（绝不误拒诚实 run）。check 无 mode 字段·无从自封 enforce。
    """

    chain.register(
        gate_name=SECTION13_TRUST_GATE_NAME,
        check=section13_trust_check,
        required_producer=SECTION13_TRUST_PRODUCER_KEY,
        enforce_intent=enforce_intent,
    )


__all__ = [
    "SECTION13_TRUST_GATE_NAME",
    "SECTION13_TRUST_PRODUCER_KEY",
    "SECTION13_TRUST_MANIFEST_KEY",
    "section13_trust_check",
    "register_section13_trust_gate",
]
