"""T-034 · 实盘因子血统门（D-PROVENANCE）对抗测试。

种坏门必抓：含未过检验因子上真钱线却不警告 → 必抓；已过因子被误拦 → 必抓；
已知情确认仍死挡 → 违反「硬透明+软决定」。
"""

from __future__ import annotations

from app.provenance import check_factor_provenance, gate_live_promotion


def _status_map(mapping):
    return lambda fid: mapping.get(fid, "unknown")


def test_all_cleared_passes_no_ack():
    look = _status_map({"f1": "cleared", "f2": "cleared"})
    v = gate_live_promotion(["f1", "f2"], look)
    assert v.cleared is True
    assert v.requires_acknowledge is False
    assert not v.uncleared_factors


def test_uncleared_factor_flagged_requires_ack():
    """种坏门：策略含未过假设卡/验证的因子 → 必列出 + 要求知情确认。"""
    look = _status_map({"f1": "cleared", "f2": "draft"})  # f2 未走完
    v = gate_live_promotion(["f1", "f2"], look)
    assert v.cleared is False
    assert v.uncleared_factors == ["f2"]
    assert v.requires_acknowledge is True


def test_uncleared_with_acknowledge_passes_with_audit():
    """已知情确认 → 放行 + 留痕（硬透明+软决定，绝不死挡）。"""
    look = _status_map({"f2": "draft"})
    v = gate_live_promotion(["f2"], look, acknowledged=True)
    assert v.cleared is False
    assert v.requires_acknowledge is False
    assert v.acknowledged is True
    assert "知情确认" in v.message


def test_lookup_failure_is_failsafe_uncleared():
    """探针：状态查询缺失/异常 → 按未过处理（绝不当作已过，fail-safe）。"""
    look = _status_map({})  # 全 unknown
    v = check_factor_provenance(["fx"], look)
    assert v.cleared is False and "fx" in v.uncleared_factors


def test_no_false_block_probe():
    """探针防误拦：全 cleared 不应被拦（否则血统门过度封锁正常上线）。"""
    look = _status_map({f"f{i}": "cleared" for i in range(5)})
    v = gate_live_promotion([f"f{i}" for i in range(5)], look)
    assert v.cleared is True and v.requires_acknowledge is False
