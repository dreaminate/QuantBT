"""双通道分流 + 超时默认表（T-019 / spine 07 §3.6）。

P2：探索通道零门（仅事后记录）；只有 confirmatory（上 staging/production / 动钱 / 加杠杆 / 删历史）
走重门、可挂数天。超时默认按 action_kind 分流：延迟即风险类（止损/降险）到期放行、动钱类到期拒绝。
"""

from __future__ import annotations

HIGH_IMPACT = frozenset({"live_order", "transfer", "leverage_up", "data_delete",
                         "promote_production", "promote_staging", "add_position"})

# 超时默认（dossier §5/§6）：延迟即风险 vs 动钱默认拒。
TIMEOUT_DEFAULT = {
    "stop_loss": "default_allow",
    "risk_reduction": "default_allow",
    "add_position": "default_reject",
    "transfer": "default_reject",
    "leverage_up": "default_reject",
    "promote_production": "default_reject",
    "promote_staging": "default_reject",
    "live_order": "default_reject",
    "data_delete": "escalate",
}

# SLA 窗口（秒）——保守默认；真实档位需按资产/频率实证标定（§7 open Q）。
_SLA_SECONDS = {
    "stop_loss": 300, "risk_reduction": 600,
    "promote_staging": 86400, "promote_production": 259200,   # 可挂数天
}


def classify_channel(action_kind: str, to_stage: str) -> str:
    if to_stage in ("staging", "production") or action_kind in HIGH_IMPACT:
        return "confirmatory"
    return "exploratory"


def timeout_default(action_kind: str) -> str:
    return TIMEOUT_DEFAULT.get(action_kind, "escalate")


def sla_seconds(action_kind: str) -> int:
    return _SLA_SECONDS.get(action_kind, 3600)


__all__ = ["HIGH_IMPACT", "TIMEOUT_DEFAULT", "classify_channel", "sla_seconds", "timeout_default"]
