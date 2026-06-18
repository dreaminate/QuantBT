"""门后真实硬限额（T-019 / spine 07 §3.5，R7：审批≠授权）。

production 动钱动作即便审批通过，仍被 `SafetyService` 阶梯的单笔 notional cap 卡死——批了仍授不了权。
不新造限额，唯一真硬边界事实源 = `trading/safety.py` 阶梯（与 T-018 交易所侧硬墙同源精神）。
"""

from __future__ import annotations

from typing import Any


class HardLimitExceeded(Exception):
    """门后动作超阶梯单笔 cap：审批通过也拒执行。"""


def enforce(gate: Any, safety_service: Any) -> None:
    """真钱订单：notional 超当前阶梯 cap → raise（审批≠授权）。**fail-closed**（复核 #13）：
    动钱动作缺 notional / cap 取不到 → 一律 raise，绝不静默放过。
    """

    ev = gate.evidence or {}
    notional = ev.get("notional_usdt") if isinstance(ev, dict) else None
    if notional is None:
        raise HardLimitExceeded(f"动钱动作 {gate.action_kind} 未声明 notional_usdt → 无法核额度（fail-closed）")
    cap = _current_cap(safety_service)
    if cap is None:
        raise HardLimitExceeded("无法从 safety_service 取当前阶梯单笔上限 → fail-closed 拒执行")
    if float(notional) > cap:
        raise HardLimitExceeded(
            f"门后硬限额：notional {notional} 超当前安全阶梯单笔上限 {cap}（审批≠授权，R7）"
        )


def _current_cap(safety_service: Any) -> float | None:
    """从 SafetyService 取当前阶梯单笔 cap；取不到/异常返 None（由 enforce fail-closed 处理）。"""

    for attr in ("current_single_order_cap", "single_order_cap", "max_single_notional"):
        fn = getattr(safety_service, attr, None)
        if callable(fn):
            try:
                return float(fn())
            except Exception:  # noqa: BLE001
                return None
        if isinstance(fn, (int, float)):
            return float(fn)
    return None


__all__ = ["HardLimitExceeded", "enforce"]
