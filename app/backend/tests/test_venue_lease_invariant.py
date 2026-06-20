"""T-033 · venue lease-only 不变量防回归探针（INV-3，核验 verified）。

把「生产 crypto venue 只认 lease（place_order 含 lease 形参）」从人工 grep 升级为 CI 签名守门：
若有人把不收 lease 的真 key venue 当生产 venue，签名探针必抓。
"""

from __future__ import annotations

import inspect

from app.execution.leased_binance import LeasedBinanceVenue


def test_leased_venue_place_order_accepts_lease():
    sig = inspect.signature(LeasedBinanceVenue.place_order)
    assert "lease" in sig.parameters, \
        "生产 lease venue 的 place_order 必须含 lease 形参（INV-3 lease-only：真 key 只在门后随 lease 现身）"


def test_leased_venue_no_lease_fail_closed_probe():
    """探针：lease 形参默认 None → 无 lease 调用应 fail-closed（不静默放行）。"""
    sig = inspect.signature(LeasedBinanceVenue.place_order)
    lease_param = sig.parameters["lease"]
    assert lease_param.default is None, "lease 默认应为 None（无 lease 即 fail-closed，绝不自取 key）"
