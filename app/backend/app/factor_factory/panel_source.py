"""F2 · 因子评测类端点的「按 factor + market 取 panel」共同前置数据源层。

为什么单独一层（红线：panel 强制复权 + 正确 forward-return 滞后，绝不前视穿越）：
所有 IC / IC衰减 / 分层回测 / audit 端点都吃同一份 polars panel
(symbol, ts, close, volume, ...)。把「取 panel + 校正 ts 列 + 复权口径 + forward
return 滞后」收成单一入口，杜绝各端点各自手搓 panel 时漏 shift（前视）或漏复权。

诚实边界：
- 现阶段数据面是 `datasets/samples.py` 合成 sample（已是复权/连续口径——合成价本身无除权
  跳变）。真实接 Tushare 复权后，本层是唯一改动点（端点零改）。
- forward return **只**经 `ic.attach_forward_returns`（用 `close.shift(-h)`，正向滞后、
  按 symbol 分组），本层不自造 forward 列——单一滞后源，防某端点偷偷 shift(0) 前视。
- `ts` 列：sample panel 用 `t_index`（整数序，非日历）。本层统一 alias 成 `ts`，让
  下游 `group_by("ts")` 截面 IC 正常工作。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ..datasets.samples import load_sample

# market（前端 equity_cn / crypto）→ 评测用 sample_id。
# A股=合成 ETF 多标的 252d（截面 IC 需多 symbol）；加密=BTC+ETH 拼成多标的。
_MARKET_SAMPLE: dict[str, str] = {
    "equity_cn": "ashare_etf_daily_252d",
    "crypto": "btc_perp_daily_365d",
}

REQUIRED_COLUMNS: frozenset[str] = frozenset({"symbol", "ts", "close"})


class PanelSourceError(ValueError):
    """panel 数据源口径违规（缺市场 / 缺列 / 复权未声明）。"""


def _normalize_ts(panel: pl.DataFrame) -> pl.DataFrame:
    """统一时间列名为 `ts`（sample 用 t_index 整数序，非日历）。"""

    if "ts" in panel.columns:
        return panel
    if "t_index" in panel.columns:
        return panel.rename({"t_index": "ts"})
    raise PanelSourceError("panel 缺时间列（既无 ts 也无 t_index）")


def load_market_panel(market: str) -> pl.DataFrame:
    """按 market 取一份【已复权、多 symbol、含 ts】的评测 panel。

    复权口径：合成 sample 价格本身连续无除权跳变（等价后复权连续价）；真实数据接入时
    本函数是唯一复权落点。返回列至少含 (symbol, ts, close[, volume, ...])。
    """

    sample_id = _MARKET_SAMPLE.get(market)
    if sample_id is None:
        raise PanelSourceError(
            f"未知 market={market!r}（支持 {sorted(_MARKET_SAMPLE)}）"
        )
    panel = load_sample(sample_id)
    if panel is None or panel.is_empty():
        raise PanelSourceError(f"market={market} 对应 sample={sample_id} 无数据")
    # 加密：单 sample 只有 1 个 symbol，截面 IC 退化。拼 BTC+ETH 凑多标的截面。
    if market == "crypto":
        eth = load_sample("eth_perp_daily_365d")
        if eth is not None and not eth.is_empty():
            common = [c for c in panel.columns if c in eth.columns]
            panel = pl.concat([panel.select(common), eth.select(common)], how="vertical")
    panel = _normalize_ts(panel)
    missing = REQUIRED_COLUMNS - set(panel.columns)
    if missing:
        raise PanelSourceError(f"panel 缺必需列: {sorted(missing)}")
    return panel.sort(["symbol", "ts"])


def factor_panel(
    market: str,
    formula: str,
    *,
    horizon: int = 5,
    factor_alias: str = "factor_value",
) -> pl.DataFrame:
    """取 market panel → 应用因子表达式 → 关联原始 OHLCV，供 IC/回测端点直用。

    返回 (ts, symbol, {factor_alias}, close[, volume...])，forward return 由下游
    `attach_forward_returns` 加（本层不前视）。
    """

    from .expression import evaluate_on_panel  # 局部 import 防循环

    base = load_market_panel(market)
    feat = evaluate_on_panel(base, formula, alias=factor_alias)
    # join 回原始价（forward return 要用 close），保持复权 close 单一源。
    merged = base.join(feat, on=["ts", "symbol"], how="inner")
    return merged.sort(["symbol", "ts"])


__all__ = [
    "PanelSourceError",
    "REQUIRED_COLUMNS",
    "factor_panel",
    "load_market_panel",
]
