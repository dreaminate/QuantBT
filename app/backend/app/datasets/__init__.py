"""v0.8.7 · 样例数据集生成 + manifest。

提供：
- generate_btc_perp_sample(days=365) · 加密永续合成 OHLCV (随机游走 + GBM)
- generate_eth_perp_sample(days=365)
- generate_ashare_etf_sample(symbols=['510300','510500','510050','510880'], days=252)
- 3 个策略模板 (BTC momentum / ETH funding arbitrage / A股 ETF rotation)
- /api/datasets/samples endpoint serve manifest
"""

from __future__ import annotations

from .samples import (
    SampleManifest,
    generate_ashare_etf_sample,
    generate_btc_perp_sample,
    generate_eth_perp_sample,
    list_samples,
    load_sample,
)
from .templates import STRATEGY_TEMPLATES, get_template, list_templates

__all__ = [
    "STRATEGY_TEMPLATES",
    "SampleManifest",
    "generate_ashare_etf_sample",
    "generate_btc_perp_sample",
    "generate_eth_perp_sample",
    "get_template",
    "list_samples",
    "list_templates",
    "load_sample",
]
