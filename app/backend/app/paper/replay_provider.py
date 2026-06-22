"""模拟台 bar/mark provider —— **确定性合成 bar 流**驱动 PaperScheduler.tick_once。

⚠️ 这是【模拟】非实盘：bar 来自 content_hash 派生的**确定性伪随机游走**（可复现、无外部依赖），
**非真实盘行情、亦非捆绑样本回放**——**绝不取实盘 key、绝不打交易所行情 API**。source 标注
`deterministic_sim_walk` 诚实声明此性质（§3 不假绿灯：不谎称真数据）。A股恒拒 live（D-PERM
default_to_paper）；本 provider 只喂模拟 bars 让模拟台跑出移动净值序列，不改任何治理门——动钱/晋级/
live 下单一律走既有阶梯，与本模块无关。
（真样本回放 / testnet 真喂 = 后续增强卡，本模块是零依赖模拟兜底。）

设计：
- 每个 symbol 一条确定性 OHLC 序列（content_hash 派生的伪随机游走，无外部依赖、可复现）。
- `make_bar_provider`：symbol → 下一根 bar（被 tick_once 调用，喂给 PaperVenue.feed_bar 撮合 open orders）。
- `make_mark_provider`：symbols → 当前 mark（被 mtm_once 调用，让 mark_to_market 写出移动的净值）。
- `seed_positions`：注册时注入模拟建仓引子（非下单路径），使 MTM 反映价格变动 → 净值非空壳。

为什么不直接用回测 batch：模拟台语义是「每 tick 收一根实时 bar 喂入」，与回测预批量不同；此 provider
即「实时 bar 流」的模拟源，与生产真 connector 同形（生产把本 provider 换成 connector-driven 实时拉取）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..execution.paper_venue import PaperVenue
from ..lineage.ids import content_hash


SIMULATED_SOURCE = "deterministic_sim_walk"  # 数据来源标注：确定性合成游走（模拟，非实盘 key、非真样本回放）


def _seeded_walk(seed: str, n: int) -> list[float]:
    """从 content_hash(seed) 派生确定性收益序列 → 价格游走（无外部随机源，可复现）。"""

    # content_hash 是全库单一哈希族（16 hex）；逐 step 重哈希得稳定伪随机增量。
    prices: list[float] = []
    base = 100.0
    cur = base
    for i in range(n):
        h = content_hash([seed, i])
        # 取哈希前 8 hex → [0,1) → 居中到 [-0.5,0.5)，振幅 ~1.6%（含轻微正漂以产非平净值）。
        frac = int(h[:8], 16) / 0xFFFFFFFF
        ret = 0.0008 + (frac - 0.5) * 0.016
        cur = cur * (1.0 + ret)
        prices.append(round(cur, 4))
    return prices


@dataclass
class ReplayBarProvider:
    """确定性模拟 provider：每 symbol 一条合成 OHLC 序列（content_hash 派生游走，非真样本）；tick 推进游标。

    线程安全（PaperScheduler 后台线程 + 测试同步驱动共用）。耗尽序列后停在末根（不抛错、不假数据）。
    """

    symbols: list[str]
    length: int = 64
    _series: dict[str, list[float]] = field(default_factory=dict)
    _cursor: dict[str, int] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        for sym in self.symbols:
            self._series[sym] = _seeded_walk(sym, self.length)
            self._cursor[sym] = 0

    @property
    def source(self) -> str:
        return SIMULATED_SOURCE

    def reset(self) -> None:
        """游标归零（不重算序列）——让 prime_run 可重复跑出同一确定性窗口（幂等）。"""

        with self._lock:
            for sym in self._series:
                self._cursor[sym] = 0

    def next_bar(self, symbol: str) -> dict[str, Any] | None:
        """下一根 bar（OHLC + ts）。耗尽则恒返末根 close（停更，绝不造新数据）。"""

        with self._lock:
            series = self._series.get(symbol)
            if not series:
                return None
            i = self._cursor[symbol]
            if i >= len(series):
                i = len(series) - 1  # 停在末根：不推进、不假新数据
            close = series[i]
            prev = series[i - 1] if i > 0 else close
            self._cursor[symbol] = min(i + 1, len(series))
            high = max(prev, close) * 1.001
            low = min(prev, close) * 0.999
            return {
                "symbol": symbol,
                "open": round(prev, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "ts": f"sim-{i:04d}",
                "source": SIMULATED_SOURCE,
            }

    def current_marks(self, symbols: list[str]) -> dict[str, float]:
        """当前 mark = 各 symbol 游标处 close（MTM 用，使净值随回放移动）。"""

        with self._lock:
            out: dict[str, float] = {}
            for sym in symbols:
                series = self._series.get(sym)
                if not series:
                    continue
                i = min(max(self._cursor[sym] - 1, 0), len(series) - 1)
                out[sym] = series[i]
            return out


def make_bar_provider(provider: ReplayBarProvider) -> Callable[[str], dict[str, Any] | None]:
    return provider.next_bar


def make_mark_provider(provider: ReplayBarProvider) -> Callable[[list[str]], dict[str, float]]:
    return provider.current_marks


def seed_positions(
    venue: PaperVenue, symbols: list[str], *, notional_per_symbol: float = 50_000.0
) -> int:
    """注册时为各 symbol 注入模拟建仓引子（venue.seed_position，非下单路径），使 MTM 反映持仓盈亏。

    qty 由初始价 100（_seeded_walk base）反推目标名义；返回建仓数。纯模拟、不经 OrderGuard、无 live。
    """

    count = 0
    for sym in symbols:
        qty = round(notional_per_symbol / 100.0, 4)  # 初始价 ~100 → 名义 ≈ notional_per_symbol
        venue.seed_position(sym, quantity=qty, entry_price=100.0)
        count += 1
    return count


__all__ = [
    "ReplayBarProvider",
    "SIMULATED_SOURCE",
    "make_bar_provider",
    "make_mark_provider",
    "seed_positions",
]
