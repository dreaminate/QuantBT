"""v0.8.7 · 3 个策略模板 (BTC momentum / ETH funding arb / A股 ETF rotation)。

模板代码可直接粘到 IDE 跑沙箱 (用 quantbt.emit_result 结尾)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyTemplate:
    template_id: str
    name: str
    asset_class: str  # crypto_perp / crypto_spot / equity_cn
    description: str
    expected_metrics: dict[str, float]  # 模板预期 metric 范围（用户对照看是否过拟合）
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "asset_class": self.asset_class,
            "description": self.description,
            "expected_metrics": self.expected_metrics,
            "code": self.code,
        }


_BTC_MOMENTUM = StrategyTemplate(
    template_id="btc_momentum_v1",
    name="BTC 20 日动量",
    asset_class="crypto_perp",
    description="基于 BTC-USDT 20 日累计收益的简单动量，正动量持多，负动量持空，单标的策略。",
    expected_metrics={
        "sharpe_min": 0.5, "sharpe_max": 1.8,
        "pbo_max": 0.5, "max_drawdown_min": -0.35,
    },
    code='''"""BTC 20 日动量策略 (模板 v1)。

回测期 365 日 BTC-USDT 永续，每日决定多/空仓位。
"""
import math, random

random.seed(42)

# 生成同 sample 一致的数据 (复用沙箱可允许的最小依赖)
days = 365
close, prices = 30000.0, []
for d in range(days):
    ret = random.gauss(0.0005, 0.025) + (random.choice([-0.05, 0.05]) if random.random() < 0.05 else 0)
    close *= (1 + ret)
    prices.append(close)

# 20 日动量 + 简单等权
equity = 1.0
curve = []
for i in range(days):
    if i < 20:
        signal = 0
        ret_day = 0.0
    else:
        mom = (prices[i-1] / prices[i-21]) - 1
        signal = 1 if mom > 0 else -1
        daily_ret = (prices[i] / prices[i-1]) - 1
        ret_day = signal * daily_ret
        # 0.05% 单次成本
        if i > 20 and curve[-1].get("signal", 0) != signal:
            ret_day -= 0.001
    equity *= (1 + ret_day)
    curve.append({
        "t": f"2025-{(i//30)+1:02d}-{(i%30)+1:02d}",
        "equity": round(equity, 6),
        "net_return": round(ret_day, 6),
        "benchmark_return": round((prices[i]/prices[i-1] - 1) if i > 0 else 0, 6),
        "signal": signal,
    })

quantbt.emit_result({
    "equity_curve": curve,
    "metadata": {
        "strategy_name": "BTC 20 日动量",
        "market": "crypto_perp",
        "frequency": "1d",
        "benchmark": "BTC-USDT",
    },
})
''',
)


_ETH_FUNDING_ARB = StrategyTemplate(
    template_id="eth_funding_arb_v1",
    name="ETH 资金费率套利",
    asset_class="crypto_perp",
    description="资金费率 > 0.03% 时做空永续 + 持现货 spot 多头 (delta-neutral)，赚 funding。模板纯展示思路，实盘需双 venue。",
    expected_metrics={
        "sharpe_min": 0.8, "sharpe_max": 2.5,
        "pbo_max": 0.4, "max_drawdown_min": -0.08,
    },
    code='''"""ETH 资金费率套利 (模板 v1)。

思路：当 funding > 0.03% 时做空 ETH 永续 + 持等量现货 ETH，赚 funding 费率。
注意：模板是单 venue 模拟，真实需 spot + perp 两个 venue 同时持仓。
"""
import math, random

random.seed(43)

days = 365
funding_returns = []
equity = 1.0
curve = []
for d in range(days):
    # 模拟 funding rate
    funding = random.gauss(0.0001, 0.0003)
    # 套利条件
    if funding > 0.00015:
        # 做空 perp 持 spot：每日赚 funding，但承担小额成本和滑点
        ret = funding * 3 - 0.0002  # 3 次/日 funding；0.02% 维持成本
    else:
        ret = 0  # 不进场
    equity *= (1 + ret)
    curve.append({
        "t": f"2025-{(d//30)+1:02d}-{(d%30)+1:02d}",
        "equity": round(equity, 6),
        "net_return": round(ret, 6),
        "benchmark_return": 0.0,  # 现金 benchmark
    })

quantbt.emit_result({
    "equity_curve": curve,
    "metadata": {
        "strategy_name": "ETH 资金费率套利",
        "market": "crypto_perp",
        "frequency": "1d",
        "benchmark": "Cash",
    },
})
''',
)


_ASHARE_ETF_ROTATION = StrategyTemplate(
    template_id="ashare_etf_rotation_v1",
    name="A股 ETF 月轮动",
    asset_class="equity_cn",
    description="4 个 ETF (沪深300/中证500/上证50/中证红利) 每月轮动，持过去 20 日动量最高的 1 个。研究级 paper trading。",
    expected_metrics={
        "sharpe_min": 0.6, "sharpe_max": 1.5,
        "pbo_max": 0.6, "max_drawdown_min": -0.25,
    },
    code='''"""A股 ETF 月轮动 (模板 v1)。

4 个 ETF 候选池：沪深300 / 中证500 / 上证50 / 中证红利
每 20 日检查动量，持过去 20 日累计收益最高的 1 个。
"""
import math, random

random.seed(7)

symbols = ["510300", "510500", "510050", "510880"]
days = 252  # 1 年 trading days
# 每个 symbol 独立价格路径
prices = {s: [random.uniform(2.5, 5.0)] for s in symbols}
for s in symbols:
    for _ in range(days - 1):
        ret = random.gauss(0.0003, 0.012)
        prices[s].append(prices[s][-1] * (1 + ret))

held = None
equity = 1.0
curve = []
for d in range(days):
    # 每 20 日 rebalance
    if d % 20 == 0 and d >= 20:
        # 找过去 20 日动量最高
        scores = {s: (prices[s][d-1] / prices[s][d-21]) - 1 for s in symbols}
        held = max(scores, key=scores.get)
    if held is None:
        ret_day = 0.0
    else:
        ret_day = (prices[held][d] / prices[held][d-1]) - 1 if d > 0 else 0
    equity *= (1 + ret_day)
    # benchmark: 沪深300 等权
    bench = (prices["510300"][d] / prices["510300"][d-1]) - 1 if d > 0 else 0
    curve.append({
        "t": f"2024-{(d//22)+1:02d}-{(d%22)+1:02d}",
        "equity": round(equity, 6),
        "net_return": round(ret_day, 6),
        "benchmark_return": round(bench, 6),
        "held": held,
    })

quantbt.emit_result({
    "equity_curve": curve,
    "metadata": {
        "strategy_name": "A股 ETF 月轮动",
        "market": "equity_cn",
        "frequency": "1d",
        "benchmark": "510300",
    },
})
''',
)


STRATEGY_TEMPLATES: dict[str, StrategyTemplate] = {
    _BTC_MOMENTUM.template_id: _BTC_MOMENTUM,
    _ETH_FUNDING_ARB.template_id: _ETH_FUNDING_ARB,
    _ASHARE_ETF_ROTATION.template_id: _ASHARE_ETF_ROTATION,
}


def list_templates() -> list[dict[str, Any]]:
    return [t.to_dict() for t in STRATEGY_TEMPLATES.values()]


def get_template(template_id: str) -> StrategyTemplate | None:
    return STRATEGY_TEMPLATES.get(template_id)


__all__ = ["STRATEGY_TEMPLATES", "StrategyTemplate", "get_template", "list_templates"]
