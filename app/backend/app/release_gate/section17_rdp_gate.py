"""C-S17-RDP-PROMOTE-ENFORCE · §17 RDP 发版 check（插 SA-3 promote 门链）。

这张卡只建 PARALLEL-SAFE 的 check + 注册函数——把（已建的）§17 Research Delivery Package 四拒绝门
经 SA-3 门链接到 promote 收口，关掉 codemap C-S17-RDP-PROMOTE-ENFORCE 点出的洞：正式因子/模型/信号/
StrategyBook 晋级**必须能追溯到一套完整 RDP**（GOAL §17 北极星总闸·`delivery/rdp_gate.py` 4 门），但
今天 `validate_rdp` / `require_valid_rdp` **未在真 promote 决定上被调**——追不到完整 RDP（缺 manifest /
artifact hash / reproducibility command / DatasetVersion / IngestionSkill ref / 未验证残余）的晋级今天
能溜过 release。**不**在此串进 `ide/promote.py`（那是后续 CENTER-SERIAL 的一次性改·两步法）；本模块是
新建孤立件，中心后续经 `gate_registry` 调 `register_section17_rdp_gate(...)`。

═══ 复用不重造（RULES §1 单一源）═══
§17 完整性/追溯判定的唯一源是交付层 `delivery.rdp_gate`：本模块**只**做 manifest(dict)→canonical
`RDPManifest`/`PromotionClaim` 的薄适配（全程复用 `delivery.rdp` 自己的 `RDPManifest.from_dict` 适配器·
rdp_id 走单一身份源 `lineage.ids.content_hash`），再把判定**整体委托**给 canonical 聚合器
`validate_rdp(rdp, promotion=...)`——它内部循环 `gate_manifest_completeness`（manifest/artifact_hash/
reproducibility_command）/ `gate_dataset_lineage`（DatasetVersion + IngestionSkill）/
`gate_unverified_residual`（诚实残余闸）/ `gate_promotion_traceability`（晋级可追溯·仅当给 promotion）。
本模块**绝不**重写任何一条 RDP 门判定，连缺字段码都直接搬运 rdp_gate 的原码（missing = 各门 outcome
原 field 名）。

═══ 4 道拒绝门 → rdp_gate 缺字段（construction-map C-S17 的可证伪点）═══
  - manifest 完整性：缺 asset_ref / artifact_hash / reproducibility_command ⇒ ok=False（exact 缺项）。
  - 数据血统：缺可解析 DatasetVersion 或 IngestionSkill ref（空壳引用不算）⇒ ok=False。
  - 未验证残余：`unverified_residual=None`（未声明）⇒ ok=False；显式零残余却无 residual_attestation ⇒ 拒。
  - 晋级可追溯：晋级断言追不到一份**关于本资产**的有效 RDP（无 rdp / 空 rdp_ref / 张冠李戴 / 追到残缺
    RDP）⇒ ok=False。

═══ 职责分离（gaming-proof）═══
check **只懂「这个 promote run 的 §17 RDP 完整且可追溯否」**，返回 `GateCheckResult(ok, reason, missing)`
——它**不**决定自己是 advisory 还是 enforce。advisory/enforce 由 SA-2 策略（`governance.enforcement_policy`）
经门链统一盖章：仅当 `s17_rdp_runjson_producers`（§17 RDP 结构进 manifest 的接线测试·把真血统/真 artifact
hash 写进 manifest 那层）转绿，门才从 advisory 翻 enforce（LOCKED 决策 1）。check 连 mode 字段都没有 →
**无法自封 enforce 绕过 producer 绿灯门**。

═══ 诚实限界（RULES §3·设计极限·非残余）═══
`section17_rdp` 缺省（或 rdp/promotion 均未声明）→ `ok=True`，语义是**「未声明 §17 RDP 结构 ⇒ 无可证伪
RDP 违例」**，**不**代表「整本 run 已查清 §17」。「是否真有完整 RDP 被如实写进 manifest」由 producer
绿灯门（`s17_rdp_runjson_producers` 接线测试 = 未来 C-S17-RUNJSON-PRODUCERS）负责——producer 未绿时本门
只 advisory，绝不在未接线门上误拒诚实 run。节存在但格式非法（section 非 dict / rdp|promotion 子对象非
dict / RDP 字段解析炸）→ fail-closed 记 ok=False（codex 在 C-S9 找到的「非 list/非 dict 静默 skip 让违例
溜走」洞，本模块同款堵死·绝不 fail-open）。**晋级断言在场却无任何 RDP 可追溯**（self-promote without
RDP）→ 经 canonical `gate_promotion_traceability(promotion, None)` 判 ok=False（不当「未声明」放行）。

═══ 委托边界（诚实限界·非本门 fail-open）═══
本门**严格只与 `delivery.rdp_gate.validate_rdp` 同强**——它判过的本门判过，它放过的本门放过。rdp_gate
对「present 即算有」的边界（如 `unverified_residual=()` + residual_attestation 在场 = 显式零残余放行）
属 rdp_gate 单一源语义，本门遵「reuse·不擅改 rdp_gate」只忠实委托·绝不在网关层重写判定（= 防 §1 单一源
漂移）。

═══ 冷导入安全 ═══
顶层只 import 同包 `promote_gate_chain`（cold-safe·已证）与交付层子模块 `delivery.rdp` / `delivery.rdp_gate`
（经 `python -c` 实证冷导入安全·只触 lineage.ids·不触 governance 冷循环）。**不**在顶层 import governance
（SA-2 符号由门链在 evaluate 期惰性载入）。**不**碰 `release_gate/__init__.py`（既有冷导入环·SA-3 note）
——消费方从本子模块直接 import。模块**无 import 期副作用**（不 auto-register）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..delivery.rdp import PromotionClaim, RDPManifest
from ..delivery.rdp_gate import gate_promotion_traceability, validate_rdp
from .promote_gate_chain import GateCheckResult, PromoteGateChain, RunManifest

# —— 门身份 + 证据 producer key（中心注册/绿灯账据此钉）。gate_name 与门链其它节门同族短名 ——
SECTION17_RDP_GATE_NAME = "s17_rdp"
# 证据 producer：§17 RDP 结构进 promote manifest 的接线测试。转绿前门停 advisory（LOCKED 决策 1）。
SECTION17_RDP_PRODUCER_KEY = "s17_rdp_runjson_producers"
# manifest 里承载 §17 RDP 的 key（producer 填·check 读）。其值是一个 dict：
#   {"rdp": {...RDPManifest 字段...}, "promotion": {...PromotionClaim 字段·可选...}}
# rdp 缺省 ⇒ 未声明；promotion 在场而 rdp 缺 ⇒ 晋级追不到 RDP ⇒ 拒（gate4 语义）。
SECTION17_RDP_MANIFEST_KEY = "section17_rdp"
# 子键名（producer 契约）。
_RDP_KEY = "rdp"
_PROMOTION_KEY = "promotion"

_NOTHING_DECLARED = (
    "§17：manifest 未声明 section17_rdp（rdp/promotion 均缺）—— 无可证伪 RDP 违例"
    "（诚实限界：非『整本已查清』·查清由 producer 绿灯门负责）"
)
_ALL_SATISFIED = "§17 RDP 完整且可追溯（已声明 RDP 过全部拒绝门）"


def _build_promotion(d: Mapping[str, Any]) -> PromotionClaim:
    """manifest dict → canonical PromotionClaim（faithful·字段名即 dataclass 字段名）。

    PromotionClaim 三必填（asset_ref/asset_kind/rdp_ref）全走 `str(... or "")`：空/缺 → 空串（由 gate4
    `_blank` 判缺·诚实拒），绝不 raise（构造总成功）。`asset_kind` 不在此校验合法性（那是 gate4 关注的
    asset_ref↔rdp.asset_ref 一致性·非 kind 合法性·与 RDPManifest 不同）。
    """

    return PromotionClaim(
        asset_ref=str(d.get("asset_ref") or ""),
        asset_kind=str(d.get("asset_kind") or ""),
        rdp_ref=str(d.get("rdp_ref") or ""),
        requested_stage=str(d.get("requested_stage") or ""),
        actor=str(d.get("actor") or ""),
    )


# ════════════════════════════════════════════════════════════════════════════
# 公开 check：promote manifest → GateCheckResult（门链插它）
# ════════════════════════════════════════════════════════════════════════════
def section17_rdp_check(manifest: RunManifest) -> GateCheckResult:
    """§17 RDP 发版 check：把 RDP 喂 delivery canonical 4 门·返回完整且可追溯否。

    - 节缺省 / rdp&promotion 均缺 → ok=True（无可证伪违例·诚实限界见模块 docstring）。
    - 节非 dict / rdp|promotion 子对象非 dict / RDP 字段解析炸 → ok=False（fail-closed·不静默放行）。
    - 晋级断言在场却无 rdp → ok=False（gate4：无 RDP 可追溯·堵 self-promote without RDP）。
    - RDP 缺 manifest/artifact hash/repro command / 缺 DatasetVersion/IngestionSkill / 缺未验证残余 /
      晋级不可追溯 → ok=False·missing=exact 缺项码（全来自 rdp_gate canonical 门）·reason=带门拒因。

    判定**单一源**：全委托 `delivery.rdp_gate.validate_rdp`（不碰 advisory/enforce·不重写任何门判定）。
    """

    # 非 Mapping manifest → manifest.get 抛 → 由门链 _run_one fail-closed（errored·绝不静默放行）。
    # 刻意不在此 catch 成 ok=True（那是 fail-open）。
    section = manifest.get(SECTION17_RDP_MANIFEST_KEY)

    if section is None:
        return GateCheckResult(ok=True, reason=_NOTHING_DECLARED)
    if not isinstance(section, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§17 RDP 节存在但格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section17_rdp_malformed",),
        )

    rdp_dict = section.get(_RDP_KEY)
    promo_dict = section.get(_PROMOTION_KEY)

    # rdp 与 promotion 均未声明 → 诚实限界（producer 绿灯门才决定「§17 是否必须在场」）。
    if rdp_dict is None and promo_dict is None:
        return GateCheckResult(ok=True, reason=_NOTHING_DECLARED)

    # —— 子对象形态 fail-closed（非 dict 不静默放行）——
    if rdp_dict is not None and not isinstance(rdp_dict, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§17 RDP 的 rdp 子对象格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section17_rdp_rdp_malformed",),
        )
    if promo_dict is not None and not isinstance(promo_dict, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§17 RDP 的 promotion 子对象格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section17_rdp_promotion_malformed",),
        )

    promotion = _build_promotion(promo_dict) if promo_dict is not None else None

    # —— 晋级断言在场却无 rdp（self-promote without RDP）→ canonical gate4 判「无 RDP 可追溯」→ 拒 ——
    # 复用 gate_promotion_traceability(promotion, None)（不重写·rdp=None ⇒ outcome.passed=False）。
    if rdp_dict is None:
        outcome = gate_promotion_traceability(promotion, None)
        return GateCheckResult(
            ok=outcome.passed is True,  # 此分支恒 False（rdp=None）·严格 bool
            reason=f"§17 RDP 晋级不可追溯: {outcome.reason}",
            missing=tuple(outcome.missing),
        )

    # —— 构造 canonical RDP（薄适配·fail-closed）——
    # RDPManifest.from_dict 重算 rdp_id（弃外部传入·防伪造 id）；asset_kind 非法/缺必填 → raise → 这里
    # fail-closed 记 unparseable（不静默放行半成品冒充正式交付）。
    try:
        rdp = RDPManifest.from_dict(dict(rdp_dict))
    except Exception as exc:  # noqa: BLE001 — 构造炸 → fail-closed（记违例·不静默 ok=True·不炸整链）
        return GateCheckResult(
            ok=False,
            reason=f"§17 RDP 字段无法构造为合法 RDPManifest（fail-closed·视为未过）: {type(exc).__name__}: {exc}",
            missing=("section17_rdp_unparseable",),
        )

    # —— 完整性 + 追溯判定**单一源**：全委托 rdp_gate.validate_rdp（gate1-3 恒跑·gate4 仅当 promotion 在场）——
    # ★ mutation 目标（见 test 文件头三态）：把下面 `if validation.ok:` 弱化成 `if True:`（无视 canonical
    #   裁定）→ incomplete RDP 溜成 ok=True → 对抗测试转 RED → 还原 → GREEN。
    try:
        validation = validate_rdp(rdp, promotion=promotion)
    except Exception as exc:  # noqa: BLE001 — 判定炸 → fail-closed（记违例·绝不静默 ok=True 放行）
        return GateCheckResult(
            ok=False,
            reason=f"§17 RDP 判定异常（fail-closed·视为未过）: {type(exc).__name__}: {exc}",
            missing=("section17_rdp_evaluation_unparseable",),
        )

    if validation.ok:
        return GateCheckResult(ok=True, reason=_ALL_SATISFIED)
    return GateCheckResult(
        ok=False,
        reason=f"§17 RDP 未过拒绝门: {validation.reason_text}",
        missing=tuple(validation.missing),
    )


def register_section17_rdp_gate(
    chain: PromoteGateChain, *, enforce_intent: bool = True
) -> None:
    """把 §17 RDP 发版 check 注册进给定门链（中心后续经 gate_registry 串 promote.py 时调一次）。

    用法（CENTER-SERIAL·经单一注册收口）：
        from app.release_gate.gate_registry import ensure_default_chain  # 已含本门
        ensure_default_chain().evaluate(manifest, producer_status=ledger)

    `enforce_intent=True`：§17 门有 GOAL「拒」语义（追不到完整 RDP 的晋级 → 拒），**有资格** enforce——
    但仅当 `s17_rdp_runjson_producers` 转绿才真翻 enforce；未绿则被 SA-2 策略降级 advisory + 记录（绝不
    误拒诚实 run）。check 无 mode 字段·无从自封 enforce。
    """

    chain.register(
        gate_name=SECTION17_RDP_GATE_NAME,
        check=section17_rdp_check,
        required_producer=SECTION17_RDP_PRODUCER_KEY,
        enforce_intent=enforce_intent,
    )


__all__ = [
    "SECTION17_RDP_GATE_NAME",
    "SECTION17_RDP_PRODUCER_KEY",
    "SECTION17_RDP_MANIFEST_KEY",
    "section17_rdp_check",
    "register_section17_rdp_gate",
]
