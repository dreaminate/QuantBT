"""T-031 · 审批 SLA / 杠杆可配 + 真钱超时铁律（D-LEVERAGE）对抗测试。

种坏门必抓：
- 真钱类超时若被 override 成自动放行 → 灾难（无人确认却动钱）→ 必抓。
- 杠杆若被钉系统硬上限 → 违反「用户风险偏好不设硬上限」。
"""

from __future__ import annotations

from app.approval.channels import sla_seconds, timeout_default


_REALMONEY_KINDS = (
    "live_order", "transfer", "leverage_up",
    "promote_production", "promote_staging", "add_position",
)


def test_realmoney_timeout_reject_not_configurable():
    """种坏门：试图把动钱类超时 override 成 default_allow → 必被拒，仍 default_reject。"""
    for k in _REALMONEY_KINDS:
        assert timeout_default(k, {k: "default_allow"}) == "default_reject", \
            f"{k} 超时永远 default_reject，绝不可配成放行"
        assert timeout_default(k, {k: "escalate"}) == "default_reject"


def test_non_realmoney_timeout_configurable():
    assert timeout_default("stop_loss") == "default_allow"
    # 非动钱类可被收紧（放宽到更安全方向允许）
    assert timeout_default("stop_loss", {"stop_loss": "default_reject"}) == "default_reject"


def test_sla_configurable():
    assert sla_seconds("promote_staging") == 86400
    assert sla_seconds("promote_staging", {"promote_staging": 3600}) == 3600


def test_sla_override_rejects_nonpositive():
    assert sla_seconds("promote_staging", {"promote_staging": 0}) == 86400
    assert sla_seconds("promote_staging", {"promote_staging": -5}) == 86400


def test_leverage_cap_configurable_no_hard_cap(monkeypatch):
    """杠杆阈值可配且无系统硬上限（用户风险偏好，D-LEVERAGE）。"""
    from app import main
    monkeypatch.setenv("QUANTBT_AGENT_LEVERAGE_CAP", "50")
    assert main._agent_leverage_cap() == 50.0  # 不被钳到任何硬上限
    monkeypatch.setenv("QUANTBT_AGENT_LEVERAGE_CAP", "bad")
    assert main._agent_leverage_cap() == 3.0  # 非法值回退默认
