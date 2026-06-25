"""R18 平方根市场冲击 回测成本项 对抗测试。

设计/推导见 `dev/research/findings/dreaminate/sqrt-impact-backtest-cost.md`。门必抓：
- 向后兼容：impact_coef=0（默认）→ 成本与改前逐位相等（现有回测不破）。
- 平方根标度：participation×4 → impact_frac×2（δ=0.5）；写成线性/常数 → 抓。
- 大单惩罚：高 participation 单位成本 > 低 participation。
- 命门交叉校验：容量 C 处单期冲击占 AUM 比 == 毛 alpha（绑 strategy_capacity）。
- 不假绿灯：impact_coef>0 但无 volume → init raise（绝不静默 0 冲击）。
"""

from __future__ import annotations

import json
import math
import warnings

import numpy as np
import polars as pl
import pytest

from app.execution.backtest_venue import BacktestCostModel, BacktestVenue
from app.execution.impact import IMPACT_DELTA, square_root_impact_fraction
from app.factor_factory.lifecycle_metrics import strategy_capacity


def _panel(n=60, sigma=0.02, seed=0, with_volume=True):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * sigma))
    cols = {
        "ts": list(range(n)), "symbol": ["BTC"] * n,
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
    }
    if with_volume:
        cols["volume"] = [1000.0] * n
    return pl.DataFrame(cols)


def _panel_latevol(n=30, vol_early=1000.0, vol_late=1000.0, late_from=15, seed=0):
    """同一 close 序列（seed 锁定），仅**未来 bar(≥late_from)** 量不同 → 测扩张窗 as-of 无泄露。"""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * 0.02))
    vol = [vol_early] * late_from + [vol_late] * (n - late_from)
    return pl.DataFrame({
        "ts": list(range(n)), "symbol": ["BTC"] * n,
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": vol,
    })


# ===========================================================================
# square_root_impact_fraction（单一公式源）
# ===========================================================================


def test_impact_fraction_sqrt_scaling():
    """participation×4 → impact_frac×2（δ=0.5 √律）。写成 δ=1 线性会得 ×4。"""
    f1 = square_root_impact_fraction(0.01, 0.02, 0.1)
    f4 = square_root_impact_fraction(0.04, 0.02, 0.1)
    assert abs(f4 / f1 - 2.0) < 1e-9


def test_impact_fraction_monotone_in_participation():
    fr = [square_root_impact_fraction(p, 0.02, 0.1) for p in (0.001, 0.01, 0.1, 0.3)]
    for i in range(len(fr) - 1):
        assert fr[i] < fr[i + 1]


def test_impact_fraction_degenerate_safe():
    assert square_root_impact_fraction(0.0, 0.02, 0.1) == 0.0          # participation 0
    assert square_root_impact_fraction(0.01, 0.0, 0.1) == 0.0          # σ 0
    assert square_root_impact_fraction(0.01, 0.02, 0.0) == 0.0         # coef 0
    assert square_root_impact_fraction(-0.5, 0.02, 0.1) == 0.0         # 负 participation
    assert square_root_impact_fraction(float("nan"), 0.02, 0.1) == 0.0


def test_impact_delta_locked_default_half():
    assert IMPACT_DELTA == 0.5


# ===========================================================================
# 回测成本集成
# ===========================================================================


def test_backward_compatible_impact_off_byte_identical():
    """默认 impact_coef=0 → 成本 = commission+slippage+stamp+transfer（无冲击项），与改前逐位相等。"""
    v = BacktestVenue(_panel(), BacktestCostModel())   # 默认 impact_coef=0
    cost = v._cost_for_trade("buy", 10, 100.0, "BTC")
    legacy = 10 * 100 * (5e-4) + 10 * 100 * (5e-4)     # commission 5bps + slippage 5bps
    assert abs(cost - legacy) < 1e-12


def test_large_order_costs_more_per_notional():
    """启用冲击：大单（高 participation）单位名义成本 > 小单（平 slippage 不会有此差）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(_panel(sigma=0.03), BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
    small = v._cost_for_trade("buy", 10, 100.0, "BTC") / (10 * 100)     # participation=0.01
    big = v._cost_for_trade("buy", 300, 100.0, "BTC") / (300 * 100)     # participation=0.3
    assert big > small > 0.0
    assert abs((big / small) - (0.3 / 0.01) ** 0.5) < 1e-6              # 单位成本比 = √(part 比)


def test_impact_enabled_without_volume_raises():
    """不假绿灯：impact_coef>0 但 prices 无 volume → init raise（绝不静默当 0 冲击）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match="volume"):
            BacktestVenue(_panel(with_volume=False), BacktestCostModel(impact_coef=0.5))


def test_impact_off_without_volume_ok():
    """impact 关时无 volume 不报错（向后兼容：现有无 volume 回测照跑）。"""
    v = BacktestVenue(_panel(with_volume=False), BacktestCostModel())
    assert v._cost_for_trade("buy", 10, 100.0, "BTC") > 0


# ===========================================================================
# 成本逐成分诚实归因（e2afc5c2·impact 单列不混入 commission）
# ===========================================================================


def test_cost_breakdown_components_sum_to_total_and_impact_separate():
    """逐成分诚实归因：各成分非负、求和==total，且 impact **单列不混入 commission**。

    种坏（honesty 门）：把 impact 并进 commission 成分（e2afc5c2 eng 指认的下游误读）→ commission 成分
    会虚高、且与「impact 关」时不一致 → 本测抓。
    """
    cm = BacktestCostModel(commission_bps=5, slippage_bps=3, impact_coef=0.5,
                           impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(_panel(), cm)
    bd = v._cost_breakdown("buy", 100, 100.0, "BTC")
    notional = 100 * 100.0
    assert abs(bd["commission"] - notional * 5e-4) < 1e-12         # commission=纯 commission_bps、未混 impact
    assert abs(bd["slippage"] - notional * 3e-4) < 1e-12
    assert bd["impact"] > 0.0 and bd["stamp_duty"] == 0.0          # impact 单列且 >0；买入无印花
    parts = ("commission", "slippage", "stamp_duty", "transfer", "impact")
    assert all(bd[k] >= 0.0 for k in parts)                        # 各成分非负
    assert abs(sum(bd[k] for k in parts) - bd["total"]) < 1e-12    # 求和守恒==total
    # 反证：impact 确实没被并进 commission——启用 impact 时 commission 成分与「impact 关」逐位相同
    bd0 = BacktestVenue(_panel(), BacktestCostModel(commission_bps=5, slippage_bps=3))._cost_breakdown("buy", 100, 100.0, "BTC")
    assert abs(bd["commission"] - bd0["commission"]) < 1e-12 and bd0["impact"] == 0.0


def test_fill_report_has_cost_breakdown_backward_compatible_commission_total():
    """fill 报告 additive 含 cost_breakdown；顶层 commission=total（含 impact）向后兼容（cost_drift 等旧消费者不破）。"""
    from app.execution.base import Order

    cm = BacktestCostModel(commission_bps=5, slippage_bps=3, impact_coef=0.5,
                           impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(_panel(), cm)
    v.place_order(Order(venue="backtest", symbol="BTC", side="buy", quantity=100, order_type="market"))
    rep = v.step()[0]
    assert "cost_breakdown" in rep and rep["cost_breakdown"]["impact"] > 0.0
    assert abs(rep["commission"] - rep["cost_breakdown"]["total"]) < 1e-12   # 顶层 commission=total（向后兼容）
    assert rep["commission"] > rep["cost_breakdown"]["commission"]           # total 含 impact > 纯 commission 成分
    json.dumps(rep["cost_breakdown"])                                        # JSON-safe


def test_cost_breakdown_warmup_impact_zero_still_sums():
    """warmup（自估 prefix 不足）→ impact 成分=0、求和仍==total（不假绿灯：不计冲击但守恒）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(_panel(n=12), BacktestCostModel(commission_bps=5, slippage_bps=3, impact_coef=0.5))
        bd = v._cost_breakdown("buy", 50, 100.0, "BTC", ts=0)     # ts=0 无 prior → warmup（告警已抑）
    parts = ("commission", "slippage", "stamp_duty", "transfer", "impact")
    assert bd["impact"] == 0.0 and v._impact_warmup_fills == 1
    assert abs(sum(bd[k] for k in parts) - bd["total"]) < 1e-12


# ===========================================================================
# run 级成本聚合（cost_summary · per-fill 归因收口到 run 级）
# ===========================================================================


def test_cost_summary_aggregates_fills_with_run_level_identity():
    """run 级聚合 == Σ 各 fill cost_breakdown；**run 加总恒等式 total==Σ成分**（聚合漏成分/错累加→崩）。"""
    from app.execution.base import Order

    cm = BacktestCostModel(commission_bps=5, slippage_bps=3, impact_coef=0.5,
                           impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(_panel(n=20), cm)
    for _ in range(3):
        v.place_order(Order(venue="backtest", symbol="BTC", side="buy", quantity=50, order_type="market"))
        v.step()
    summ = v.cost_summary()
    assert summ["n_fills"] == 3.0
    fills = [r["payload"]["cost_breakdown"] for r in v.audit.export() if r["kind"] == "fill"]
    assert len(fills) == 3
    for c in ("commission", "slippage", "stamp_duty", "transfer", "impact", "total"):
        assert abs(summ[c] - sum(f[c] for f in fills)) < 1e-9, f"成分 {c} run 聚合≠Σfill"
    # run 级加总恒等式：total == Σ成分（total 走独立 Σfill.total 路径 → 有真牙）。
    comp_sum = summ["commission"] + summ["slippage"] + summ["stamp_duty"] + summ["transfer"] + summ["impact"]
    assert abs(summ["total"] - comp_sum) < 1e-9
    assert summ["impact"] > 0.0                      # impact 单列、run 级可见（不淹没在 commission）


def test_cost_summary_empty_no_fills_all_zero():
    """无成交 → 全 0、n_fills=0（不编造）。"""
    v = BacktestVenue(_panel(), BacktestCostModel())
    summ = v.cost_summary()
    assert summ["n_fills"] == 0.0
    assert all(summ[c] == 0.0 for c in ("commission", "slippage", "stamp_duty", "transfer", "impact", "total"))


# ===========================================================================
# 命门：与 §3 容量交叉校验（同一 sqrt-impact 物理）
# ===========================================================================


def test_impact_enabled_invalid_adv_fails_fast_not_silent_zero():
    """codex P2：冲击启用但 symbol volume 全 0 → ADV 无效 → 成交时 raise，绝不静默当 0 冲击（假绿灯）。"""
    df = _panel()
    df = df.with_columns(pl.lit(0.0).alias("volume"))   # volume 全 0 → ADV=0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(df, BacktestCostModel(impact_coef=0.5))
    with pytest.raises(ValueError, match="ADV|无效|volume"):
        v._cost_for_trade("buy", 10, 100.0, "BTC")


def test_intraday_volume_aggregated_to_daily_adv():
    """codex P2：日内 datetime 数据按**日**聚合 ADV（非每 bar 均量）——否则参与率抬高 √(bars/日)、冲击高估。

    核**终端标量**(全样本日 ADV=2400) + **扩张窗 as-of**(day4 仅用 day1-3 已完成日 = 2400；day1 无 prior 日 → NaN warmup)。
    """
    import datetime as dt

    rows = []
    for d in (1, 2, 3, 4):
        for h in range(24):                              # 24 根 1h bar/日，每根量 100
            rows.append((dt.datetime(2020, 1, d, h), "ETH", 50.0, 50.5, 49.5, 50.0, 100.0))
    df = pl.DataFrame(rows, schema=["ts", "symbol", "open", "high", "low", "close", "volume"], orient="row")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(df, BacktestCostModel(impact_coef=0.3))
    assert abs(v._impact_adv["ETH"] - 24 * 100.0) < 1e-6   # 终端日 ADV=2400，非每 bar 100
    adv_d4, _ = v._impact_asof["ETH"][dt.datetime(2020, 1, 4, 0)]   # day4 as-of = mean(day1-3)=2400
    adv_d1, _ = v._impact_asof["ETH"][dt.datetime(2020, 1, 1, 0)]   # day1 无 prior 日 → NaN(warmup)
    assert abs(adv_d4 - 2400.0) < 1e-6 and not math.isfinite(adv_d1)


def test_auto_estimate_expanding_is_leakfree_not_lookahead():
    """**前视红线闭环（P2 0f696e56）**：自估改**扩张窗 as-of**（仅用成交前 F_{t⁻}）→ warning 转 informational
    （扩张窗 / 无前视 / as-of），**不再**宣称 active 前视泄露。mode=expanding。"""
    with pytest.warns(UserWarning, match="扩张窗|无前视|as-of"):
        v = BacktestVenue(_panel(), BacktestCostModel(impact_coef=0.5))
    assert v._impact_mode == "expanding"


def test_explicit_adv_sigma_no_warning_and_used():
    """无泄露路径：调用方传点位 ADV/σ → 不触发前视 warning + 冲击用所传 ADV（绕开自估）。"""
    import warnings as _w

    cm = BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5,
                           impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    with _w.catch_warnings():
        _w.simplefilter("error")            # 若 emit 任何 warning 即失败
        v = BacktestVenue(_panel(), cm)     # 显式口径 → 无 warning
    # 冲击用所传 ADV=2000：participation=100/2000=0.05
    cost = v._cost_for_trade("buy", 100, 100.0, "BTC")
    expected = 100 * 100 * square_root_impact_fraction(100 / 2000.0, 0.03, 0.5)
    assert abs(cost - expected) < 1e-9


def test_default_off_emits_no_warning():
    """向后兼容：默认 impact_coef=0 → 不预算、不 warn（现有回测零噪声）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        BacktestVenue(_panel(), BacktestCostModel())   # 默认关 → 无 warning


# ===========================================================================
# 扩张窗 as-of 无泄露（P2 0f696e56 闭环 · look-ahead 红线）
# ===========================================================================


def test_expanding_adv_leakfree_future_invariant():
    """**命门·门有牙**：扩张窗 as-of 估计是 F_{t⁻}-可测 → **追加任意未来 bar 不改早期成交冲击**。

    种坏（leak-free 判别）：两面板早期 bar(<15) 完全相同、仅未来 bar(≥15) 量×100。早期成交(ts=5)的冲击
    只用 <bar5 历史 → 两面板**逐位相等**；若实现把全样本 ADV 当输入（前视泄露）→ ca≠cb、此断言立崩。
    """
    base = _panel_latevol(vol_early=1000.0, vol_late=1000.0)
    spiked = _panel_latevol(vol_early=1000.0, vol_late=100000.0)        # 仅未来量×100
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        va = BacktestVenue(base, BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
        vb = BacktestVenue(spiked, BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
    ca = va._cost_for_trade("buy", 50, 100.0, "BTC", ts=5)
    cb = vb._cost_for_trade("buy", 50, 100.0, "BTC", ts=5)
    assert ca == cb > 0.0, f"早期成交冲击随未来流动性变（前视泄露）：ca={ca} cb={cb}"
    # 反证：终端全样本标量确因未来不同而不同 → 证未来确实变了、as-of 才是 leak-free 的关键差异
    assert va._impact_adv["BTC"] != vb._impact_adv["BTC"]


def test_warmup_fills_skip_impact_counted_not_silent_zero():
    """**不假绿灯**：warmup 期（prior 历史不足）成交**不计冲击但计数+披露**，绝不偷看未来补、绝不静默假装 0。

    ts=0（无 prior 日/收益）→ warmup → impact 0 + 计数 + 一次性 warning；ts≥3（≥2 prior 收益）→ 正常计冲击。
    """
    p = _panel(n=12)                                                    # int ts 0..11
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(p, BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
    with pytest.warns(UserWarning, match="warmup"):
        c0 = v._cost_for_trade("buy", 50, 100.0, "BTC", ts=0)           # warmup
    assert c0 == 0.0 and v._impact_warmup_fills == 1
    c2 = v._cost_for_trade("buy", 50, 100.0, "BTC", ts=2)              # σ 仍不足(<2 收益) → warmup
    assert c2 == 0.0 and v._impact_warmup_fills == 2
    c5 = v._cost_for_trade("buy", 50, 100.0, "BTC", ts=5)              # 足够 prior → 真计冲击
    assert c5 > 0.0


def test_expanding_sigma_leakfree_future_price_invariant():
    """**σ 通道 leak-free（评审牙缝补强）**：未来**价**任意改、量相同 → 早期成交冲击逐位不变。

    种坏：as-of ADV(对) + **全样本 σ**(泄露) 的实现——全样本 σ 含未来价波动 → ca≠cb。本测专钉 σ 通道
    （原 `_panel_latevol` 只扰动量、close 两面板相同 → 对 σ-leak 无牙；此处量相同、只扰动未来价）。
    """
    rng = np.random.default_rng(7)
    n, split = 30, 15
    close = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * 0.02))

    def _mk(price_mult: float):
        cl = close.copy()
        cl[split:] = cl[split:] * price_mult                           # 仅未来价×mult（量恒 1000）
        return pl.DataFrame({"ts": list(range(n)), "symbol": ["BTC"] * n, "open": cl,
                             "high": cl * 1.01, "low": cl * 0.99, "close": cl, "volume": [1000.0] * n})

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        va = BacktestVenue(_mk(1.0), BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
        vb = BacktestVenue(_mk(4.0), BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
    ca = va._cost_for_trade("buy", 50, 100.0, "BTC", ts=8)            # bar8 σ 仅用 <bar8 收益（<split）
    cb = vb._cost_for_trade("buy", 50, 100.0, "BTC", ts=8)
    assert ca == cb > 0.0, f"早期成交冲击随未来价变（σ 前视泄露）：ca={ca} cb={cb}"
    assert va._impact_sigma["BTC"] != vb._impact_sigma["BTC"]         # 终端全样本 σ 确随未来价不同


def test_asof_adv_is_exact_expanding_prefix_mean_not_lag1():
    """**ADV 机制钉死（评审牙缝补强）**：as-of ADV at bar k == 精确前缀均值 mean(vol[0..k-1])。

    用**非平**早期量区分「扩张窗均值」vs「lag-1（只用前一根）/前一日」——平量下三者重合、测不出机制。
    bar2 前缀均值=(100+200)/2=150，lag-1 会得 200 → 本断言能判别用错机制。
    """
    vols = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0]
    n = len(vols)
    close = 100.0 * np.exp(np.cumsum(np.full(n, 0.01)))
    df = pl.DataFrame({"ts": list(range(n)), "symbol": ["BTC"] * n, "open": close,
                       "high": close * 1.01, "low": close * 0.99, "close": close, "volume": vols})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(df, BacktestCostModel(impact_coef=0.3))
    for k in range(1, n):
        adv_k, _ = v._impact_asof["BTC"][k]
        assert abs(adv_k - float(np.mean(vols[:k]))) < 1e-9, \
            f"bar{k} as-of ADV={adv_k}≠前缀均值{np.mean(vols[:k]):.1f}（疑用 lag-1/前一日而非扩张均值）"


def test_warmup_verdict_is_leakfree_not_flipped_by_future():
    """**命门·PROBE H 回归（评审 critical 修复守门）**：早期成交（zero-vol prefix）的 warmup 裁决
    **只看 F_{t⁻}、绝不被未来量翻转**。

    种坏：用全样本 `max(volume)>0` 判 warmup-vs-fail-fast（评审挖出的残余前视）→ 未来量会翻转裁决
    （future=0→raise、future>0→warmup）。本测三档未来量（含 0）对**逐位相同的早期 bar** 须同一裁决。
    """
    def _mk(future_vol: float):
        n = 10
        close = 100.0 * np.exp(np.cumsum(np.full(n, 0.01)))
        return pl.DataFrame({"ts": list(range(n)), "symbol": ["BTC"] * n, "open": close,
                             "high": close * 1.01, "low": close * 0.99, "close": close,
                             "volume": [0.0] * 6 + [future_vol] * (n - 6)})   # bar0..5 逐位相同(零量)

    costs = []
    for fv in (0.0, 5000.0, 1e9):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            v = BacktestVenue(_mk(fv), BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
            costs.append(v._cost_for_trade("buy", 10, 100.0, "BTC", ts=3))   # 早期成交、prefix 全零量
    assert costs[0] == costs[1] == costs[2] == 0.0, \
        f"早期成交 warmup 裁决被未来量翻转（残余前视 PROBE H）：{costs}"


def test_replay_uses_asof_impact_leakfree():
    """集成：replay 路径每笔成交传 ts → 走扩张窗 as-of（非终端标量）。早期成交冲击与未来量无关。"""
    from app.execution.base import Order

    def _run(panel):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            v = BacktestVenue(panel, BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
        # 推进到 bar4，下市价单 → 成交于 bar5（as-of 仅用 <bar5）
        for _ in range(4):
            v.step()
        v.place_order(Order(venue="backtest", symbol="BTC", side="buy", quantity=50, order_type="market"))
        reports = v.step()
        return reports[0]["commission"] if reports else None

    base = _run(_panel_latevol(vol_early=1000.0, vol_late=1000.0))
    spiked = _run(_panel_latevol(vol_early=1000.0, vol_late=100000.0))
    assert base is not None and base == spiked > 0.0                    # replay 早期成交冲击不随未来变


def test_impact_at_capacity_equals_gross_alpha_cross_check():
    """**命门交叉校验**：策略在 §3 容量 C 处，单期冲击成本（占 AUM 比）== 毛 alpha（容量定义：净 alpha=0）。

    绑回测冲击模型于已验证的 strategy_capacity——同一 Y/σ/δ 物理，口径漂移则崩。
    """
    for a, tau, adv, sig, Y in [(0.0015, 0.08, 5e7, 0.015, 0.1), (0.003, 0.2, 1e8, 0.02, 0.2),
                                 (0.0008, 0.05, 2e7, 0.01, 0.15)]:
        C = strategy_capacity(a, tau, adv, sig, impact_coef=Y).capacity
        participation = tau * C / adv
        frac = square_root_impact_fraction(participation, sig, Y)   # 占成交名义比
        per_period_cost_of_aum = tau * frac                          # 交易 τ·C 名义、÷ C
        assert abs(per_period_cost_of_aum - a) < 1e-9, f"α={a} 冲击↔容量不一致"
