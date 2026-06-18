"""Agent OS 脊柱 07 · HITL 审批门双通道 + promote 状态机 + 幂等恢复（T-019）。

把裸状态翻转升级成带审批门的状态机：晋升 staging/production 强制三要件（独立验证 + approver≠creator +
多证据三角），缺即拒并返缺口清单；探索通道不挡（P2）；门后真硬限额（审批≠授权）；幂等到下单级。
"""

from __future__ import annotations

from .channels import classify_channel, timeout_default
from .gate import ApprovalGateService, DSR_FLOOR, PBO_CEIL
from .hard_limits import HardLimitExceeded, enforce
from .schema import (
    ActionKind,
    ApprovalGate,
    ApproverEqualsCreator,
    EmptyReason,
    EvidenceSnapshot,
    GateChannel,
    GateRejection,
    GateStateError,
)
from .store import ApprovalGateStore

__all__ = [
    "ActionKind",
    "ApprovalGate",
    "ApprovalGateService",
    "ApprovalGateStore",
    "ApproverEqualsCreator",
    "DSR_FLOOR",
    "EmptyReason",
    "EvidenceSnapshot",
    "GateChannel",
    "GateRejection",
    "GateStateError",
    "HardLimitExceeded",
    "PBO_CEIL",
    "classify_channel",
    "enforce",
    "timeout_default",
]
