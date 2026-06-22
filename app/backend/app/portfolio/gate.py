"""C · 组合层 M8 多证据三角守门（D-WAVE1A）。

把组合权重 × 标的已实现收益 → 组合净收益序列 → 复用**单一源** `eval.gate_runner.evaluate_overfit_gate`
（绝不自建第二条 gate）。已拍板口径：
- Q1=A1：组合独立命名空间 `portfolio:<id>`（与成分因子主题隔离；`_theme_matrix` 按 strategy_goal_ref 过滤）。
- Q1=A2：组合层 override R2 —— PBO 冷启动不可达时凭 DSR 保守端 + Bootstrap CI 双正放行（PBO 显式 N/A），
  仍受 gate 内 strong_neg→red 兜底（过拟合 DSR<0.2/CI≤0 仍 red，不误绿）。
- Q2=A：组合 promote honest-N 独立 +1（默认；复用 ledger 同一本账）。
- Q3=A：多市场混合组合取最严 min_T（任一成分 a_share → a_share/504），C 接线侧预解析。
- ADV2 反作弊：成分集+权重规范成排序 (symbol,weight) 序列入 config_hash → 重排标的同 hash、honest-N 不重复
  +1（在本调用方规范化，绝不改 `lineage.ids` 单一身份源、绝不抑制计数触 honest-N 不可改小）。
"""

from __future__ import annotations

from ..eval.gate_runner import GateRunResult, asset_class_of, evaluate_overfit_gate, freq_to_ppy


def portfolio_net_returns(
    weights: dict[str, float], asset_returns: dict[str, list[float]]
) -> list[float]:
    """组合净收益序列 = Σ_symbol w_symbol × 标的逐期已实现收益。

    只纳入 weights 与 asset_returns 都有且非空的 symbol；按各序列最短长度对齐（调用方负责 PIT/
    as-of-known join，避免前视——可经 D 的 `load_panel(as_of_known=...)` 取已实现收益）。
    """

    syms = [s for s in weights if s in asset_returns and asset_returns[s]]
    if not syms:
        return []
    length = min(len(asset_returns[s]) for s in syms)
    return [sum(weights[s] * float(asset_returns[s][t]) for s in syms) for t in range(length)]


def portfolio_strategy_goal_ref(portfolio_id: str) -> str:
    """Q1=A1：组合独立命名空间，与成分因子主题彻底隔离（不混算 N / PBO 池）。"""

    return f"portfolio:{portfolio_id}"


def portfolio_composition(weights: dict[str, float]) -> list[list]:
    """ADV2 反作弊规范化：成分+权重 → 按 symbol 排序的 [symbol, weight] 序列。

    使 [A,B,C] 与 [C,B,A]（同权重）坍缩到同一 config_hash 簇 → honest-N 不重复刷。
    权重做有限精度归一（round 12 位）防浮点抖动制造伪不同。
    """

    return [[str(s), round(float(w), 12)] for s, w in sorted(weights.items())]


def strictest_asset_class(markets) -> str:
    """Q3=A：多市场混合组合取最严资产类（任一成分 a_share → a_share，min_T=504）。"""

    for m in markets:
        if asset_class_of(m) == "a_share":
            return "a_share"
    return "crypto"


def gate_portfolio(
    *,
    portfolio_id: str,
    weights: dict[str, float],
    asset_returns: dict[str, list[float]],
    markets,
    freq: str = "1d",
    dataset_version: str = "unknown",
    ledger=None,
    returns_store=None,
    record: bool,
) -> GateRunResult:
    """组合层多证据三角守门（C full-fat）。

    复用 evaluate_overfit_gate（单一源）；A2 放行 + 独立命名空间 + 最严 min_T + 反作弊 config_hash。
    验收（已重写，非「必红」假命题）：组合层过拟合 → 三角**不达 green**（red 仅当 DSR<0.2/CI 上界≤0/
    PBO>0.7 等 strong_neg）；冷启动 N<10 → PBO N/A，A2 下凭 DSR+CI 双正放行、过拟合仍被 strong_neg red。
    """

    net = portfolio_net_returns(weights, asset_returns)
    return evaluate_overfit_gate(
        returns=net,
        factor="portfolio",
        params={"composition": portfolio_composition(weights)},
        universe="portfolio",
        dataset_version=dataset_version,
        freq=freq,
        label="portfolio_net_return",
        strategy_goal_ref=portfolio_strategy_goal_ref(portfolio_id),
        asset_class=strictest_asset_class(markets),
        periods_per_year=freq_to_ppy(freq),
        ledger=ledger,
        returns_store=returns_store,
        allow_pbo_absent_green=True,
        record=record,
    )


__all__ = [
    "gate_portfolio",
    "portfolio_composition",
    "portfolio_net_returns",
    "portfolio_strategy_goal_ref",
    "strictest_asset_class",
]
