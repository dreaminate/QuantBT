"""Follower → 生产 PolicyGate（默认门模板）+ tier + nonce 绑定（T-021 / spine 06 §4/§7）。

T-018 把 OrderGuard / PolicyGate 建好并单测过，但**生产 relay 路径未 wrap** → INV-2/M17 生产未强制。
本模块是 T-021 的"默认门模板"：把既有 Follower 字段映射成一个 deny-by-default 的 PolicyGate，
relay 在 wrap venue 时用它，使**所有 follower 下单热路径必经会话外硬墙**。

落地决策（AskUserQuestion 工具内部错误丢答 + 用户「继续」→ 采纳推荐保守档，记为可改默认）：
- D-T021-1 `symbol_whitelist={signal.symbol}`：跟单作用域 = 所跟 master 当下交易的标的；余皆 deny。
- D-T021-2 notional = `follower.per_order_max_usdt`（**既有字段**，默认 100；≤0 兜底 100，绝不放无限额单）。
  —— 无需新字段/迁移。
- D-T021-3 fail 模式：**CRYPTO_LIVE 真钱 → fail-closed**（broker+nonce 缺即拒）；TESTNET/PAPER → fail-open
  （假钱/无外流，依赖缺失时门仍评估但不硬阻，避免过度工程化 + 不破坏既有 testnet 基线）。
- 杠杆 = `follower.max_leverage`（None/≤0 → 1.0 保守，未声明上限即不许放杠杆；relay 另有硬截断双保险）。
- turnover = notional × max(max_positions,1)（CRYPTO_LIVE 门要求正的日换手上限）。
"""

from __future__ import annotations

from ..security.gate.policy import PolicyGate, TrustTier, classify
from .service import Follower, Signal

# 保守默认单笔名义额（USDT）：follower 未设/设非正时兜底，绝不放无限额实盘单。属主可在 follower 配置调高。
DEFAULT_NOTIONAL_USDT = 100.0


def follower_tier(f: Follower) -> TrustTier:
    """R9 分级：mainnet=真钱→CRYPTO_LIVE；其余（testnet 默认）→ 假钱档。crypto 资产类。"""

    is_live = (f.binance_network or "").strip().lower() == "mainnet"
    return classify("crypto", is_live=is_live)


def follower_gate(f: Follower, signal: Signal, *, tier: TrustTier | None = None) -> PolicyGate:
    """构造该 follower 这一单的会话外 deny-by-default 策略门（默认门模板）。"""

    t = tier or follower_tier(f)
    notional = f.per_order_max_usdt if (f.per_order_max_usdt or 0) > 0 else DEFAULT_NOTIONAL_USDT
    max_lev = f.max_leverage if (f.max_leverage or 0) > 0 else 1.0
    turnover = notional * max(int(f.max_positions or 1), 1)
    return PolicyGate(
        tier=t,
        symbol_whitelist=frozenset({signal.symbol}),   # D-T021-1：作用域=所跟标的，余皆 deny
        max_notional_per_order_usdt=notional,          # D-T021-2：既有 per_order_max_usdt
        max_leverage=max_lev,
        daily_turnover_cap=turnover,
        require_validation_attestation=t == TrustTier.CRYPTO_LIVE,
    )


def relay_nonce(signal_id: str, follower_id: str) -> str:
    """确定性 nonce（防重放，INV-4）：同 (signal,follower) 只能消费一次。

    与 beta 幂等键同源 → 真重放（截获 relay 调用重打）被 NonceLedger 拒；失败单不盲目自动重试
    （宁可漏不可重，M17 教训）——要重试须发新 signal。
    """

    return f"relay::{signal_id}::{follower_id}"


def live_requires_deps(tier: TrustTier) -> bool:
    """D-T021-3：仅 CRYPTO_LIVE（真钱）要求 broker+nonce 齐备，缺即 fail-closed。"""

    return tier == TrustTier.CRYPTO_LIVE


__all__ = [
    "DEFAULT_NOTIONAL_USDT",
    "follower_tier",
    "follower_gate",
    "relay_nonce",
    "live_requires_deps",
]
