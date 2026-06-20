"""T-030 · 单人 self-approve 仅非真钱通道（D-SELFAPPROVE）对抗测试。

种坏门必抓：
- 真钱场景（promote_production / 动钱）self-approve → 必拒（保留硬双人，§5）。
- self-approve 缺二次确认 → 拒（绝不伪装双控）。
- 未开 self_approve 的自批 → 仍 approver≠creator 硬拒（原不变量）。
- 双人审批 self_approved=False（诚实标注不误标）。
"""

from __future__ import annotations

from app.approval import (
    ApprovalGateService,
    ApprovalGateStore,
    ApproverEqualsCreator,
    EvidenceSnapshot,
)
from app.approval.schema import EmptyReason, SelfApproveForbidden
from app.lineage.ledger import Ledger

import pytest


def _svc(tmp_path):
    return ApprovalGateService(ApprovalGateStore(tmp_path), ledger=Ledger(tmp_path / "ledger"))


def _good_evidence():
    return EvidenceSnapshot(
        config_hash="cfg_v1_aaaa", dataset_version="ds1", n_eff=5, n_trials_raw=5,
        dsr=0.92, pbo=0.10, bootstrap_ci=(0.4, 1.8), bootstrap_estimate=1.0,
        champion_challenger={"verdict": "challenger_wins"}, returns_sha256="r1",
    ).to_dict()


def _open(svc, to_stage, created_by="alice"):
    return svc.open_gate(
        model_id="m1", version=2, from_stage="dev", to_stage=to_stage,
        action_kind=("promote_production" if to_stage == "production" else "promote_staging"),
        created_by=created_by, verification_record_id="v-1",
        evidence=_good_evidence(), strategy_goal_ref="theme",
    )


def test_self_approve_non_realmoney_ok(tmp_path):
    svc = _svc(tmp_path)
    g = _open(svc, "staging", created_by="alice")
    assert g.decision == "pending"
    out = svc.approve(g.gate_id, approver="alice",
                      reason="单人非真钱自批，已知晓风险并复核证据充分",
                      self_approve=True, acknowledged=True)
    assert out.decision == "approved"
    assert out.self_approved is True
    assert "self-approved" in out.verdict_text  # 诚实标注，不伪装双控


def test_self_approve_realmoney_forbidden(tmp_path):
    svc = _svc(tmp_path)
    g = _open(svc, "production", created_by="alice")  # promote_production = 真钱
    assert g.decision == "pending"
    with pytest.raises(SelfApproveForbidden):
        svc.approve(g.gate_id, approver="alice", reason="想自批上生产真钱，理由够长",
                    self_approve=True, acknowledged=True)


def test_self_approve_requires_acknowledge(tmp_path):
    svc = _svc(tmp_path)
    g = _open(svc, "staging", created_by="alice")
    with pytest.raises(EmptyReason):
        svc.approve(g.gate_id, approver="alice", reason="非真钱但没二次确认，理由够长",
                    self_approve=True, acknowledged=False)


def test_self_approve_cooling_not_elapsed(tmp_path):
    """冷却未过 → 拒（后端可强制冷却，时长默认放客户端）。"""
    from app.approval.schema import GateStateError
    svc = _svc(tmp_path)
    g = _open(svc, "staging", created_by="alice")
    with pytest.raises(GateStateError):
        svc.approve(g.gate_id, approver="alice", reason="刚建就想自批，理由够长",
                    self_approve=True, acknowledged=True, cooling_seconds=99999)


def test_self_approve_off_still_blocks_self(tmp_path):
    """未开 self_approve 的自批 → 仍 approver≠creator 硬拒（原不变量不变）。"""
    svc = _svc(tmp_path)
    g = _open(svc, "staging", created_by="alice")
    with pytest.raises(ApproverEqualsCreator):
        svc.approve(g.gate_id, approver="alice", reason="没开 self_approve，理由够长",
                    self_approve=False)


def test_two_person_approve_not_self_approved(tmp_path):
    """双人审批 self_approved=False（诚实标注不误标）。"""
    svc = _svc(tmp_path)
    g = _open(svc, "staging", created_by="alice")
    out = svc.approve(g.gate_id, approver="bob", reason="双人审批，证据充分适用域明确")
    assert out.decision == "approved"
    assert out.self_approved is False
