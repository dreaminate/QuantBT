"""§17 RDP gate for formal promotion.

The check delegates RDP completeness, lineage, residual, traceability, and
reproduction-receipt decisions to :mod:`app.delivery.rdp_gate`.  A promotion
claim requires an exact current receipt resolved from the trusted persistent
issuer store and bound to the owner, RDP manifest, artifact, structured
reproduction spec, and source IDE result.  The receipt is
stored at run-manifest top level to avoid a receipt/manifest hash cycle.

The free-form ``reproducibility_command`` remains documentary and is never
executed here.  Missing sections remain an honest advisory surface until the
canonical §17 producer is green; malformed or declared-but-incomplete sections
fail closed.  A self-hashed receipt without the trusted store is also red.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..delivery.rdp import PromotionClaim, RDPManifest
from ..delivery.rdp_gate import gate_promotion_traceability, validate_rdp
from ..research_os.rdp_reproduction import reproduction_receipt_from_dict
from ..research_os.rdp_reproduction import PersistentRDPReproductionReceiptStore
from .promote_gate_chain import GateCheckResult, PromoteGateChain, RunManifest

# —— 门身份 + 证据 producer key（中心注册/绿灯账据此钉）。gate_name 与门链其它节门同族短名 ——
SECTION17_RDP_GATE_NAME = "s17_rdp"
# 证据 producer：§17 RDP 结构进 promote manifest 的接线测试。转绿前门停 advisory（LOCKED 决策 1）。
SECTION17_RDP_PRODUCER_KEY = "s17_rdp_runjson_producers"
# manifest 里承载 §17 RDP 的 key（producer 填·check 读）。其值是一个 dict：
#   {"rdp": {...RDPManifest 字段...}, "promotion": {...PromotionClaim 字段·可选...}}
# rdp 缺省 ⇒ 未声明；promotion 在场而 rdp 缺 ⇒ 晋级追不到 RDP ⇒ 拒（gate4 语义）。
SECTION17_RDP_MANIFEST_KEY = "section17_rdp"
# Top-level proof remains outside the content-addressed RDP manifest to avoid a
# receipt↔manifest hash cycle.  The final run manifest and §17 verdict both bind
# this exact payload, so the existing promotion-verification digest covers it.
RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY = "rdp_reproduction_receipt"
# 子键名（producer 契约）。
_RDP_KEY = "rdp"
_PROMOTION_KEY = "promotion"

_NOTHING_DECLARED = (
    "§17：manifest 未声明 section17_rdp（rdp/promotion 均缺）—— 无可证伪 RDP 违例"
    "（诚实限界：非『整本已查清』·查清由 producer 绿灯门负责）"
)
_ALL_SATISFIED = (
    "§17 RDP 完整且可追溯（正式晋级另已验证当前、内容绑定的 ReproductionReceipt）"
)


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
def section17_rdp_check(
    manifest: RunManifest,
    *,
    reproduction_receipt_store: PersistentRDPReproductionReceiptStore | None = None,
) -> GateCheckResult:
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
    receipt_dict = manifest.get(RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY)

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
    if not rdp_dict or not (rdp_dict.get("asset_ref") or rdp_dict.get("asset_refs")):
        return GateCheckResult(
            ok=False,
            reason="§17 RDP 缺资产身份，无法构造正式交付 manifest（fail-closed·视为未过）",
            missing=("section17_rdp_unparseable",),
        )
    try:
        rdp = RDPManifest.from_dict(dict(rdp_dict))
    except Exception as exc:  # noqa: BLE001 — 构造炸 → fail-closed（记违例·不静默 ok=True·不炸整链）
        return GateCheckResult(
            ok=False,
            reason=f"§17 RDP 字段无法构造为合法 RDPManifest（fail-closed·视为未过）: {type(exc).__name__}: {exc}",
            missing=("section17_rdp_unparseable",),
        )

    reproduction_receipt = None
    if promotion is not None:
        if receipt_dict is not None and not isinstance(receipt_dict, Mapping):
            return GateCheckResult(
                ok=False,
                reason="§17 RDP ReproductionReceipt 格式非法（应为对象/dict）—— fail-closed 视为未过",
                missing=("rdp_reproduction_receipt_malformed",),
            )
        if isinstance(receipt_dict, Mapping):
            try:
                reproduction_receipt = reproduction_receipt_from_dict(receipt_dict)
            except Exception as exc:  # noqa: BLE001 - forged/malformed receipt is red.
                return GateCheckResult(
                    ok=False,
                    reason=(
                        "§17 RDP ReproductionReceipt 无法构造（fail-closed·视为未过）: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    missing=("rdp_reproduction_receipt_unparseable",),
                )

    source = manifest.get("source")
    source_owner_user_id = (
        str(source.get("owner_user_id") or "").strip()
        if isinstance(source, Mapping)
        else ""
    )
    source_result_content_hash = (
        str(source.get("result_content_hash") or "").strip()
        if isinstance(source, Mapping)
        else ""
    )

    # —— 完整性 + 追溯判定**单一源**：全委托 rdp_gate.validate_rdp（gate1-3 恒跑·gate4 仅当 promotion 在场）——
    # ★ mutation 目标（见 test 文件头三态）：把下面 `if validation.ok:` 弱化成 `if True:`（无视 canonical
    #   裁定）→ incomplete RDP 溜成 ok=True → 对抗测试转 RED → 还原 → GREEN。
    try:
        validation = validate_rdp(
            rdp,
            promotion=promotion,
            reproduction_receipt=reproduction_receipt,
            reproduction_owner_user_id=source_owner_user_id,
            source_result_content_hash=source_result_content_hash,
            require_reproduction_receipt=promotion is not None,
            reproduction_receipt_store=reproduction_receipt_store,
        )
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
    chain: PromoteGateChain,
    *,
    enforce_intent: bool = True,
    reproduction_receipt_store: PersistentRDPReproductionReceiptStore | None = None,
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
        check=lambda manifest: section17_rdp_check(
            manifest,
            reproduction_receipt_store=reproduction_receipt_store,
        ),
        required_producer=SECTION17_RDP_PRODUCER_KEY,
        enforce_intent=enforce_intent,
    )


__all__ = [
    "SECTION17_RDP_GATE_NAME",
    "SECTION17_RDP_PRODUCER_KEY",
    "SECTION17_RDP_MANIFEST_KEY",
    "RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY",
    "section17_rdp_check",
    "register_section17_rdp_gate",
]
