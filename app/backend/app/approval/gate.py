"""ApprovalGateService · 带审批门的状态机（T-019 / spine 07 §3.4-3.5）。

open_gate → 探索直批(P2) / 确证走三要件校验（缺即拒 + 缺口清单，绝不进 pending）。
approve → approver≠creator 硬约束 + 反套话 reason + 幂等门后副作用。resume/on_sla_expire 恢复与超时默认。
裁决措辞只说「证据充分/不足 + 适用域 + 未验证项」，绝不说「可信/安全/保证」（R5）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from ..delivery import PromotionClaim, RDPManifest, require_promotion_rdp
from .channels import classify_channel, sla_seconds, timeout_default
from .schema import (
    MONEY_ACTIONS,
    ApprovalGate,
    ApproverEqualsCreator,
    EmptyReason,
    EvidenceSnapshot,
    GateRejection,
    GateStateError,
    SelfApproveForbidden,
)
from .store import ApprovalGateStore

# 三角放行档（R 决策：t>3 不硬编 → 可配置档位、默认保守；裁决里明示「这是档位非物理常数」）。
DSR_FLOOR = 0.5
PBO_CEIL = 0.5

_BANNED = ("可信", "安全", "保证")
# 带 notional 的真钱【订单】动作（须 safety + 限额）；promote_* 由审批门三要件把关、无 notional。
_ORDER_MONEY = frozenset({"live_order", "transfer", "add_position", "leverage_up"})
# 纯套话审批理由黑名单（反敷衍；§7 open Q：先粗判，长期需更稳）。
_BOILERPLATE = {"ok", "okay", "lgtm", "approved", "同意", "通过", "可以", "没问题", "批准", "go", "fine"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_substantive(reason: str | None) -> bool:
    r = (reason or "").strip()
    if len(r) < 10:
        return False
    return r.lower() not in _BOILERPLATE


def _verdict(passed: bool, gaps: list[str], domain: str) -> str:
    head = "证据充分：三要件齐全且多证据三角同向" if passed else "证据不足：未满足放行要件"
    detail = ("缺口：" + "、".join(gaps)) if gaps else "无缺口"
    disc = ("守门器自身有模型风险（DSR/PBO/honest-N 只与诚实 N 一样诚实，DSR_FLOOR/PBO_CEIL 是档位选择"
            "非物理常数）；单机本地 approver≠creator 是防自欺约定 + 防篡改证据，非组织独立、非防恶意。")
    return f"{head}（{detail}）。适用域={domain}；未验证=门外自适应攻击/决策疲劳疗效/属主恶意。{disc}"


class ApprovalGateService:
    def __init__(self, store: ApprovalGateStore, *, safety_service: Any = None,
                 ledger: Any = None, dsr_floor: float = DSR_FLOOR, pbo_ceil: float = PBO_CEIL,
                 verdict_lookup: Callable[[str | None], str | None] | None = None) -> None:
        self._store = store
        self._safety = safety_service
        self._ledger = ledger
        self._dsr_floor = dsr_floor
        self._pbo_ceil = pbo_ceil
        # T-020 集成：部件12 验证官记录查询（verdict_id → VerdictRecord，含 verdict + target_ref）。
        # None = 退化为「仅查 verification_record_id 存在」（向后兼容 T-019 基线）。
        self._verdict_lookup = verdict_lookup

    # ── 三要件校验 + 缺口清单 ──
    def validate_three_requirements(self, gate: ApprovalGate, *, strategy_goal_ref: str | None = None) -> list[str]:
        gaps: list[str] = []
        if gate.to_stage not in ("staging", "production"):
            return gaps
        # (a) 独立验证记录
        if not gate.verification_record_id:
            gaps.append("缺独立验证记录(verification_record_id)：'生成≠验证'未满足")
        elif self._verdict_lookup is not None:
            # T-020 集成：接入验证官后，verification_record_id 不止要存在——还要
            #   (i) 记录未被篡改（读路径校验，复核 #3）、(ii) target_ref 绑定本次晋升的 config
            #   （防拿无关/trivial 裁决冒名顶替，复核 #1）、(iii) verdict==consistent（blocked/concern≠pass，T9）。
            try:
                rec = self._verdict_lookup(gate.verification_record_id)
            except Exception as exc:  # noqa: BLE001  篡改/读失败一律 fail-closed（绝不放行，也不让异常 500 掉晋升）
                rec = None
                gaps.append(f"验证记录不可信（读失败/被篡改）：{exc}；fail-closed 不予晋升")
            if rec is None:
                if not any("验证记录不可信" in g for g in gaps):
                    gaps.append("verification_record_id 查无权威裁决：验证官未产 verdict_id 或已失效")
            else:
                expected = (gate.evidence or {}).get("config_hash")
                target_ref = getattr(rec, "target_ref", None)
                if not expected:
                    gaps.append("裁决无法绑定本次晋升：evidence 缺 config_hash（fail-closed，防张冠李戴）")
                elif target_ref != expected:
                    gaps.append(f"验证官裁决张冠李戴：verdict.target_ref={target_ref} ≠ 本次 config_hash={expected}")
                v = getattr(rec, "verdict", None)
                if v == "blocked":
                    gaps.append("验证官裁决 verdict=blocked：异模型不一致(不取均值)，不予晋升")
                elif v == "concern":
                    gaps.append("验证官裁决 verdict=concern：异模型一致性存疑/独立性未确立，不予晋升")
                elif v != "consistent":
                    gaps.append(f"验证官裁决非法(verdict={v})")
        # (c) 多证据三角快照。复核 #5：坏/缺字段 evidence 不得抛 TypeError，转成缺口。
        try:
            ev = EvidenceSnapshot.from_dict(gate.evidence)
        except (TypeError, ValueError, KeyError):
            ev = None
            gaps.append("过拟合证据快照字段缺失/非法（无法解析）")
        if gate.evidence is not None and ev is None and "过拟合证据快照字段缺失/非法（无法解析）" not in gaps:
            gaps.append("过拟合证据快照字段缺失/非法（无法解析）")
        if gate.evidence is None:
            gaps.append("缺过拟合证据快照(DSR+PBO+bootstrap CI)")
        elif ev is not None:
            if not ev.champion_challenger.get("verdict"):
                gaps.append("缺 champion/challenger 结论")
            # R2 同向放行：【重算】三角，不信调用方自报 triangle_aligned（T2：dsr 填高也得过 pbo/ci）。
            ci_low = ev.bootstrap_ci[0] if ev.bootstrap_ci else -1.0
            if not (ev.dsr >= self._dsr_floor and ev.pbo <= self._pbo_ceil and ci_low > 0):
                gaps.append(
                    f"三角不同向：DSR={ev.dsr:.2f}(需≥{self._dsr_floor}) "
                    f"PBO={ev.pbo:.2f}(需≤{self._pbo_ceil}) CI下界={ci_low:.2f}(需>0)"
                )
        # honest-N 核验（复核 #3/#4/#14）：confirmatory 必做，不可因缺账本/缺 goal 静默跳过。
        # 比【名义计数 n_trials_raw】vs 账本 distinct——n_eff 是聚类后下界、本就 ≤ 名义，拿它比会错杀合法晋级。
        if self._ledger is None or not strategy_goal_ref:
            gaps.append("honest-N 无法核验：confirmatory 晋升须接一本账 + strategy_goal_ref（不可豁免，防低报 N）")
        elif ev is not None:
            real_n = self._ledger.honest_n(strategy_goal_ref)
            if ev.n_trials_raw < real_n:
                gaps.append(f"honest-N 被改小：自报 n_trials_raw={ev.n_trials_raw} < 账本实计 {real_n}（防作弊，硬）")
        return gaps

    # ── 开门 ──
    def open_gate(self, *, model_id: str, version: int, from_stage: str, to_stage: str,
                  action_kind: str, created_by: str, verification_record_id: str | None = None,
                  evidence: dict[str, Any] | None = None, strategy_goal_ref: str | None = None) -> ApprovalGate:
        gid = "gate-" + uuid.uuid4().hex[:12]
        idem = f"{model_id}::v{version}::{to_stage}::{(evidence or {}).get('config_hash', '')[:12]}"
        channel = classify_channel(action_kind, to_stage)
        gate = ApprovalGate(
            gate_id=gid, model_id=model_id, version=version, from_stage=from_stage, to_stage=to_stage,
            channel=channel, action_kind=action_kind, created_by=created_by,
            verification_record_id=verification_record_id, evidence=evidence,
            idempotency_key=idem, on_timeout=timeout_default(action_kind),
        )
        if channel == "exploratory":
            gate.decision = "approved"            # P2：探索不挡（仅事后记录）
            gate.decided_at_utc = _now()
            gate.verdict_text = _verdict(True, [], f"探索通道/{to_stage}")
            return self._store.append(gate)
        gaps = self.validate_three_requirements(gate, strategy_goal_ref=strategy_goal_ref)
        if gaps:
            gate.decision = "rejected"
            gate.gap_list = gaps
            gate.decided_at_utc = _now()
            gate.verdict_text = _verdict(False, gaps, f"{to_stage}/confirmatory")
            return self._store.append(gate)
        gate.decision = "pending"
        gate.sla_deadline_utc = (datetime.now(UTC) + timedelta(seconds=sla_seconds(action_kind))).isoformat()
        gate.verdict_text = _verdict(True, [], f"{to_stage}/confirmatory（待人工审批）")
        return self._store.append(gate)

    # ── 审批 / 拒绝 ──
    def approve(self, gate_id: str, *, approver: str, reason: str, risk_restated: str | None = None,
                self_approve: bool = False, acknowledged: bool = False, cooling_seconds: int = 0,
                execute_fn: Callable[[ApprovalGate], str] | None = None,
                rdp: RDPManifest | None = None, promotion_claim: PromotionClaim | None = None,
                require_rdp: bool = False) -> ApprovalGate:
        gate = self._store.get(gate_id)
        if gate.decision != "pending":
            raise GateStateError(f"非 pending 不可批准: {gate.decision}")
        # §17 RDP 追溯接线（D-RDP-1 wire）：在【翻态 / 动副作用之前】把交付包过 §17 拒绝门。
        # 残缺 RDP（缺 manifest/hash/repro/DatasetVersion/未验证残余）或追溯断裂 → raise RDPRejected，
        # 此时 gate 尚未任何 mutation（fail-closed：不进 approved、不跑 execute_fn）。
        # 默认 rdp=None+require_rdp=False = 向后兼容 no-op（既有晋级不破基线；全量强制待 D-RDP-2 聚合器供 RDP）。
        require_promotion_rdp(rdp, promotion_claim, require_rdp=require_rdp)
        # 复核 #7：归一后比较，大小写/空白差异不能绕过 approver≠creator。
        is_self = (approver or "").strip().casefold() == (gate.created_by or "").strip().casefold()
        if is_self:
            # T-030 / D-SELFAPPROVE：单人 self-approve 仅限【非真钱】场景 + 冷却 + 二次确认 + 诚实标注。
            if not self_approve:
                raise ApproverEqualsCreator("approver 不得等于 creator（归一比较，防自审，R7）")
            if gate.action_kind in MONEY_ACTIONS:
                raise SelfApproveForbidden(
                    f"真钱场景（{gate.action_kind}）禁 self-approve：CRYPTO_LIVE/动钱/production 保留硬双人（§5）")
            if not acknowledged:
                raise EmptyReason("self-approve 需二次确认（acknowledged=True），绝不伪装双控")
            if cooling_seconds > 0 and gate.created_at_utc:
                try:
                    elapsed = (datetime.now(UTC) - datetime.fromisoformat(gate.created_at_utc)).total_seconds()
                    if elapsed < cooling_seconds:
                        raise GateStateError(f"self-approve 冷却未过（需 {cooling_seconds}s，已过 {int(elapsed)}s）")
                except ValueError:
                    pass
            gate.self_approved = True  # 诚实标注（审计可查），绝不伪装成双人
        if gate.channel == "confirmatory" and not _is_substantive(reason):
            raise EmptyReason("confirmatory 审批理由不可空/不可纯套话")
        gate.approver = approver
        gate.decision_reason = reason
        gate.risk_restated = risk_restated
        gate.decision = "approved"
        gate.decided_at_utc = _now()
        tag = "self-approved(单人非真钱·冷却+留痕)" if gate.self_approved else f"approver={approver}"
        gate.verdict_text = _verdict(True, [], f"{gate.to_stage}/已审批({tag})")
        self._store.append(gate)
        return self._after_approved_execute(gate, execute_fn)

    def reject(self, gate_id: str, *, approver: str, reason: str) -> ApprovalGate:
        gate = self._store.get(gate_id)
        if gate.decision != "pending":
            raise GateStateError(f"非 pending 不可拒绝: {gate.decision}")
        gate.approver = approver
        gate.decision_reason = reason
        gate.decision = "rejected"
        gate.decided_at_utc = _now()
        gate.verdict_text = _verdict(False, gate.gap_list or ["人工拒绝"], f"{gate.to_stage}/confirmatory")
        return self._store.append(gate)

    # ── 门后幂等执行 ──
    def _after_approved_execute(self, gate: ApprovalGate, execute_fn) -> ApprovalGate:
        if gate.side_effect_executed:             # 幂等护栏（T12）：命中存量绝不重发
            return gate
        # 复核 #9：跨 gate 同 idempotency_key 已执行 → 复用、不重发（防换 gate 重放同副作用）。
        for other in self._store.list_executed_keys():
            if other == gate.idempotency_key:
                gate.side_effect_executed = True
                gate.side_effect_ref = f"deduped:{gate.idempotency_key}"
                return self._store.append(gate)
        # 复核 #11/#12：硬限额绑【真钱订单动作本身】（非 to_stage=='production'）；这类动作必须有 safety，
        # 否则 fail-closed raise（绝不静默放过无限额的真钱动作）。promote_* 由三要件把关、不走 notional 限额。
        if gate.action_kind in _ORDER_MONEY:
            if self._safety is None:
                raise GateStateError(f"动钱订单 {gate.action_kind} 未绑 safety_service → 门后硬限额无法强制（fail-closed）")
            from .hard_limits import enforce
            enforce(gate, self._safety)
        # 复核 #6：意图先落盘（标 executed）再做不可逆副作用 → 崩溃后 resume 见 executed=True 不重发
        # （宁可漏执行交对账，不可重复动钱；venue 级对账是 T-021 deferred）。
        gate.side_effect_executed = True
        self._store.append(gate)
        ref = execute_fn(gate) if execute_fn is not None else f"applied:{gate.idempotency_key}"
        gate.side_effect_ref = ref
        return self._store.append(gate)

    # ── 恢复 / 超时 ──
    def resume(self, gate_id: str, *, execute_fn=None) -> ApprovalGate:
        gate = self._store.get(gate_id)            # 读已落盘工件（R11）
        if gate.decision == "approved":
            return self._after_approved_execute(gate, execute_fn)
        return gate                                # rejected/timed_out/pending：record_and_halt

    def on_sla_expire(self, gate_id: str, *, execute_fn=None) -> ApprovalGate:
        gate = self._store.get(gate_id)
        if gate.decision != "pending":
            return gate
        # 复核 #10：未到 SLA 截止不得提前触发默认动作（否则 durable-interrupt 形同虚设、提前自动放行）。
        if gate.sla_deadline_utc:
            try:
                if datetime.now(UTC) < datetime.fromisoformat(gate.sla_deadline_utc):
                    return gate                    # 仍在窗口内，保持 pending
            except ValueError:
                pass
        default = timeout_default(gate.action_kind)
        if default == "default_allow":
            gate.decision = "approved"
            gate.decision_reason = "SLA 到期默认放行（延迟即风险类：止损/降险）"
            gate.decided_at_utc = _now()
            self._store.append(gate)
            return self._after_approved_execute(gate, execute_fn)
        # default_reject / escalate → timed_out，不执行副作用
        gate.decision = "timed_out"
        gate.decision_reason = f"SLA 到期默认拒绝（{default}）"
        gate.decided_at_utc = _now()
        return self._store.append(gate)


__all__ = ["ApprovalGateService", "DSR_FLOOR", "PBO_CEIL"]
