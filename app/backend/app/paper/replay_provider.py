"""模拟台 bar/mark provider —— **真捆绑样本回放** + **确定性合成游走兜底**驱动 PaperScheduler.tick_once。

⚠️ 这是【模拟】非实盘——**绝不取实盘 key、绝不打交易所行情 API**。两类 bar 源、source 标签诚实区分
（§3 不假绿灯：不谎称真数据、也不谎称合成是真）：
  · `bundled_sample_replay`  —— 有捆样本的市场(crypto，复用 DS-1 落盘的 `data/samples/crypto/
    BTCUSDT_1d.csv` 真 BTC close 序列)真回放；陌生人晋级的真回测策略在 paper 跑**真历史 bars**。
  · `deterministic_sim_walk` —— 无捆样本的市场(A股 token-gated 无免费样本)用 content_hash 派生的
    确定性伪随机游走(可复现、无外部依赖)兜底；**绝不为无样本市场伪造真样本**。

A股恒拒 live（D-PERM default_to_paper）；本 provider 只喂【模拟 bars】让模拟台跑出移动净值序列，
不改任何治理门——动钱/晋级/live 下单一律走既有阶梯，与本模块无关。

设计：
- 每个 symbol 一条 bar 序列：crypto 配捆样本→真 close 序列(截到 length)；否则→content_hash 派生合成游走。
- `make_bar_provider`：symbol → 下一根 bar（被 tick_once 调用，喂给 PaperVenue.feed_bar 撮合 open orders）。
- `make_mark_provider`：symbols → 当前 mark（被 mtm_once 调用，让 mark_to_market 写出移动的净值）。
- `seed_positions`：注册时注入模拟建仓引子（非下单路径），entry_price/qty **用各 symbol 首价反推**——
  真样本首价 ~47704 时 qty=notional/47704，合成时首价 100，使 MTM P&L 各自尺度自洽(不跨尺度失真)。

样本定位**复用** `agent.sample_data`（`sample_path`/`has_sample`/`SAMPLE_COLUMNS`，单一源不另造），
路径走 `paths.DATA_ROOT`（env `BACKTEST_DATA_ROOT` 可覆盖）。样本缺失→诚实降级合成兜底(不崩、不谎称 bundled)。

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
from .scheduler import MarketKind


# ── source 标签（诚实区分 bar 来源；与 simulated_source 同义域）──
SIMULATED_SOURCE = "deterministic_sim_walk"  # 确定性合成游走（无样本市场兜底，非实盘 key、非真样本）
BUNDLED_SOURCE = "bundled_sample_replay"  # 真捆样本回放（DS-1 落盘真 close 序列）

# MarketKind → sample_data 的 market 键（仅 crypto 接捆样本；A股本卡不映射——见下注）。
# ⚠️ 范围纪律 + 治理：本卡(64717fe6)只接 BTC 一个捆样本。sample_data 虽有 "stocks_cn" 槽，但 A股
# 仅 paper、token-gated 无免费样本——**故意不**把 equity_cn 映到 stocks_cn(避免改 A股 paper 标签/语义、
# 避免越界采购)。A股恒走合成兜底 deterministic_sim_walk。要接 A股真样本是未来卡(需 TUSHARE_TOKEN)。
_MARKETKIND_TO_SAMPLE: dict[str, str] = {
    "crypto": "crypto_perp",
}


def _normalize_symbol(symbol: str) -> str:
    """归一 symbol 用于与样本 base 资产匹配：去分隔符、大写（BTC-USDT / BTCUSDT / btc/usdt → BTCUSDT）。"""

    return symbol.replace("-", "").replace("/", "").replace("_", "").upper()


def _load_sample_closes(market: MarketKind, symbol: str) -> list[float] | None:
    """有捆样本的 (market, symbol) → 真 close 序列；否则 None（→ 合成兜底）。

    诚实降级：样本未映射 / 文件缺失 / 读失败 / symbol 与样本 base 不匹配 → 返 None（绝不崩、绝不谎称
    bundled）。复用 `agent.sample_data` 单一源定位，不另造路径解析。
    """

    sample_mkt = _MARKETKIND_TO_SAMPLE.get(market)
    if sample_mkt is None:
        return None
    try:
        from ..agent.sample_data import SAMPLE_BENCHMARK, has_sample, sample_path
    except Exception:  # noqa: BLE001  样本模块不可用→兜底合成
        return None
    if not has_sample(sample_mkt):
        return None
    # symbol 须与样本 base 资产匹配：捆样本是单一 BTC 序列，BTC* 系列(BTCUSDT/BTC-USDT)才回放，
    # 其它 crypto symbol(如 ETHUSDT)无对应样本→合成兜底(诚实，不拿 BTC 序列冒充 ETH)。
    bench = SAMPLE_BENCHMARK.get(sample_mkt, "")
    base = _normalize_symbol(bench)[:3] if bench else "BTC"  # "BTC-USDT"→"BTCUSDT"→"BTC"
    if not _normalize_symbol(symbol).startswith(base):
        return None
    try:
        import polars as pl

        path = sample_path(sample_mkt)
        df = pl.read_csv(path, columns=["close"])
        closes = [float(x) for x in df["close"].to_list() if x is not None]
    except Exception:  # noqa: BLE001  读/解析失败→兜底合成(不崩、不谎称 bundled)
        return None
    return closes or None


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
    """模拟 provider：每 symbol 一条 OHLC 序列——crypto 配捆样本→真 BTC close 序列回放，否则→合成游走。

    source 标签按 symbol 实际来源诚实分流（bundled_sample_replay / deterministic_sim_walk）；run 级
    `source` 反映整 run（混源→honest 混合标，绝不把混源谎称纯 bundled）。线程安全（PaperScheduler 后台
    线程 + 测试同步驱动共用）。耗尽序列后停在末根（不抛错、不假数据）。
    """

    symbols: list[str]
    length: int = 64
    market: MarketKind = "equity_cn"  # 默认 = 无样本兜底分支（向后兼容旧调用）
    _series: dict[str, list[float]] = field(default_factory=dict)
    _cursor: dict[str, int] = field(default_factory=dict)
    _first_price: dict[str, float] = field(default_factory=dict)
    _source: dict[str, str] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        for sym in self.symbols:
            closes = _load_sample_closes(self.market, sym)
            if closes is not None:
                # 真捆样本回放：截到 length（prime ticks≪length，截断足够且与合成保持幂等同形）。
                series = [round(float(c), 4) for c in closes[: self.length]]
                self._series[sym] = series
                self._first_price[sym] = series[0]
                self._source[sym] = BUNDLED_SOURCE
            else:
                # 无样本→确定性合成游走兜底（base=100，首价 100）。
                series = _seeded_walk(sym, self.length)
                self._series[sym] = series
                self._first_price[sym] = 100.0
                self._source[sym] = SIMULATED_SOURCE
            self._cursor[sym] = 0

    @property
    def source(self) -> str:
        """run 级数据来源标签（诚实）：

        全 bundled → bundled_sample_replay；全合成 → deterministic_sim_walk；混源 → 显式混合标
        `mixed:bundled_sample_replay+deterministic_sim_walk`（绝不把含合成的 run 谎称纯 bundled，§3）。
        单 symbol（最常见）即无歧义。空 → 合成兜底标（与旧默认一致）。
        """

        srcs = set(self._source.values())
        if not srcs:
            return SIMULATED_SOURCE
        if srcs == {BUNDLED_SOURCE}:
            return BUNDLED_SOURCE
        if srcs == {SIMULATED_SOURCE}:
            return SIMULATED_SOURCE
        # 混源：honest 复合标签（含 bundled 与合成）。
        return f"mixed:{BUNDLED_SOURCE}+{SIMULATED_SOURCE}"

    def source_for(self, symbol: str) -> str:
        """单 symbol 的来源标签（bundled_sample_replay / deterministic_sim_walk）。"""

        return self._source.get(symbol, SIMULATED_SOURCE)

    def first_price(self, symbol: str) -> float:
        """该 symbol 序列首价（真样本→样本首 close ~47704；合成→100）。seed_positions 反推 qty 用。"""

        return self._first_price.get(symbol, 100.0)

    def reset(self) -> None:
        """游标归零（不重算序列）——让 prime_run 可重复跑出同一确定性窗口（幂等）。"""

        with self._lock:
            for sym in self._series:
                self._cursor[sym] = 0

    def next_bar(self, symbol: str) -> dict[str, Any] | None:
        """下一根 bar（OHLC + ts + source）。耗尽则恒返末根 close（停更，绝不造新数据）。"""

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
                "ts": f"replay-{i:04d}",
                "source": self._source.get(symbol, SIMULATED_SOURCE),
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
    venue: PaperVenue,
    symbols: list[str],
    *,
    provider: ReplayBarProvider | None = None,
    notional_per_symbol: float = 50_000.0,
) -> int:
    """注册时为各 symbol 注入模拟建仓引子（venue.seed_position，非下单路径），使 MTM 反映持仓盈亏。

    qty/entry_price **用各 symbol 序列首价反推**（provider.first_price）：真样本首价 ~47704 → qty=
    notional/47704，合成首价 100 → qty=notional/100。entry_price==除数 → 扣现金恰=notional（不变量），
    MTM 各自尺度自洽——**避免** base=100 entry 配 47704 价序列的几百倍 P&L 失真。返回建仓数。

    provider=None 时退化用首价 100（向后兼容旧调用）。纯模拟、不经 OrderGuard、无 live。
    """

    count = 0
    for sym in symbols:
        first_price = provider.first_price(sym) if provider is not None else 100.0
        if first_price <= 0:
            first_price = 100.0  # 异常守：绝不除零/负价
        qty = round(notional_per_symbol / first_price, 8)  # 名义 ≈ notional_per_symbol
        venue.seed_position(sym, quantity=qty, entry_price=first_price)
        count += 1
    return count


__all__ = [
    "ReplayBarProvider",
    "SIMULATED_SOURCE",
    "BUNDLED_SOURCE",
    "make_bar_provider",
    "make_mark_provider",
    "seed_positions",
]
