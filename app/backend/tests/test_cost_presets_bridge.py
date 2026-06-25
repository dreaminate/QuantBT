"""e2afc5c2 #① · 三档成本预设 → 回测引擎(opt-in 平方根冲击)桥 对抗测试。

门必抓(种已知坏门):
- **opt-in 默认关·向后兼容**:默认预设(impact_model='linear'、不传 Y)→ 冲击恒 0、
  与直接构造的平成本 BacktestCostModel 逐位相等(生产默认不被翻)。
- **opt-in 启用是真 size-aware**:impact_model='sqrt'+给 Y → 大单单位成本 > 小单。
- **MUT-静默吞 sqrt**:桥若把 impact_model='sqrt'+Y 静默当 0 冲击(死字段没接通)→ 抓。
- **MUT-impact 混入 commission**:经桥跑一笔成交,commission 成分须=纯 commission_bps、
  impact 单列(②归因不被本路破坏)→ 把 impact 塞进 commission 即抓。
- **不假绿灯/不静默**:声明 sqrt 却没给 Y → raise;给 Y 却非 sqrt 预设 → raise;无效 Y → raise。
- **不伪造 funding**:crypto_perp 桥出的 funding_bps_per_8h=0(funding 是持仓成本、不伪造)。

桥只透传无泄露 ADV/σ 口径、不碰 venue 自估路(d9bf88b1)——本测一律传显式点位 ADV/σ,
既确定性又不触发前视 warning。
"""

from __future__ import annotations

import warnings

import numpy as np
import polars as pl
import pytest

from app.execution.backtest_venue import BacktestCostModel, BacktestVenue
from app.execution.base import Order
from app.execution.cost_presets import backtest_cost_model_for, to_backtest_cost_model
from app.execution.impact import IMPACT_DELTA, square_root_impact_fraction
from app.strategy_goal import (
    CryptoPerpCostModel,
    CryptoSpotCostModel,
    EquityCostModel,
)


def _panel(n=40, sigma=0.02, seed=0):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * sigma))
    return pl.DataFrame({
        "ts": list(range(n)), "symbol": ["BTC"] * n,
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": [1000.0] * n,
    })


# ===========================================================================
# opt-in 默认关 · 向后兼容(生产默认不被翻)
# ===========================================================================


def test_default_equity_preset_impact_off_and_fees_mapped():
    """默认 EquityCostModel(impact_model='linear')、不传 Y → 冲击关、费率逐项映射对。"""
    cm = to_backtest_cost_model(EquityCostModel())
    assert cm.impact_coef == 0.0                          # 冲击关(生产默认)
    assert cm.commission_bps == 2.5 and cm.slippage_bps == 5.0
    assert cm.stamp_duty_bps == 10.0 and cm.transfer_fee_bps == 0.1
    assert cm.impact_delta == IMPACT_DELTA                # δ=0.5 文献默认随转换流入


def test_default_preset_cost_byte_identical_to_direct_construction():
    """**向后兼容门**:默认预设(冲击关)经桥 → 与直接构造的平成本模型成交成本**逐位相等**。"""
    via_bridge = BacktestVenue(_panel(), to_backtest_cost_model(EquityCostModel()))
    direct = BacktestVenue(_panel(), BacktestCostModel(
        commission_bps=2.5, slippage_bps=5.0, stamp_duty_bps=10.0, transfer_fee_bps=0.1))
    # 买入(无印花)与卖出(含印花)两路都比
    assert via_bridge._cost_for_trade("buy", 10, 100.0, "BTC") == direct._cost_for_trade("buy", 10, 100.0, "BTC")
    assert via_bridge._cost_for_trade("sell", 10, 100.0, "BTC") == direct._cost_for_trade("sell", 10, 100.0, "BTC")


def test_default_preset_emits_no_warning_impact_off():
    """默认关 → 不预算冲击、零 warning(现有回测零噪声)。"""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        BacktestVenue(_panel(), to_backtest_cost_model(EquityCostModel()))


# ===========================================================================
# opt-in 启用:真 size-aware + MUT(静默吞 sqrt)
# ===========================================================================


def test_optin_sqrt_enables_impact_coef_not_silently_dropped():
    """**MUT-静默吞 sqrt**:impact_model='sqrt'+给 Y → 桥须真置 impact_coef=Y(非 0)。

    种坏:桥忽略 impact_model='sqrt'(死字段没接通)→ impact_coef=0 → 本断言崩。
    """
    cm = to_backtest_cost_model(EquityCostModel(impact_model="sqrt"), impact_coef=0.5,
                                impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    assert cm.impact_coef == 0.5                          # Y 真接通、没被静默吞
    assert cm.impact_adv == {"BTC": 2000.0} and cm.impact_sigma == {"BTC": 0.03}


def test_optin_sqrt_through_preset_is_size_aware():
    """opt-in 启用是真 size-aware:大单(高 participation)单位名义成本 > 小单。"""
    cm = to_backtest_cost_model(
        CryptoSpotCostModel(impact_model="sqrt"),
        impact_coef=0.5, impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    with warnings.catch_warnings():
        warnings.simplefilter("error")                   # 显式口径 → 不该有前视 warning
        v = BacktestVenue(_panel(), cm)
    small = v._cost_for_trade("buy", 10, 100.0, "BTC") / (10 * 100)
    big = v._cost_for_trade("buy", 300, 100.0, "BTC") / (300 * 100)
    assert big > small > 0.0


def test_optin_sqrt_impact_value_matches_single_formula_source():
    """启用后冲击数值=单一公式源 square_root_impact_fraction(口径不漂)。"""
    cm = to_backtest_cost_model(EquityCostModel(impact_model="sqrt", commission_bps=0,
                                                stamp_duty_bps=0, transfer_fee_bps=0, slippage_bps=0),
                                impact_coef=0.4, impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(_panel(), cm)
    cost = v._cost_for_trade("buy", 100, 100.0, "BTC")   # 纯冲击(其它费率=0)
    expected = 100 * 100 * square_root_impact_fraction(100 / 2000.0, 0.03, 0.4)
    assert abs(cost - expected) < 1e-9


# ===========================================================================
# MUT:impact 混入 commission(②归因经本路不被破)
# ===========================================================================


def test_impact_single_column_not_folded_into_commission_through_bridge():
    """**MUT-impact 混入 commission**:经桥 opt-in 跑一笔成交,impact 单列、commission 成分=纯 commission_bps。

    种坏:把 impact 塞进 commission 成分 → commission 虚高 → 本断言崩(②诚实归因经①路守住)。
    """
    cm = to_backtest_cost_model(EquityCostModel(impact_model="sqrt", commission_bps=5, slippage_bps=3,
                                                stamp_duty_bps=0, transfer_fee_bps=0),
                                impact_coef=0.5, impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = BacktestVenue(_panel(), cm)
    v.place_order(Order(venue="backtest", symbol="BTC", side="buy", quantity=100, order_type="market"))
    rep = v.step()[0]
    bd = rep["cost_breakdown"]
    notional = 100 * rep["fill_price"]
    assert abs(bd["commission"] - notional * 5e-4) < 1e-9     # commission=纯 commission_bps、未混 impact
    assert bd["impact"] > 0.0                                 # impact 单列且 >0
    assert abs(rep["commission"] - bd["total"]) < 1e-12       # 顶层 commission=total 向后兼容
    assert rep["commission"] > bd["commission"]               # total 含 impact > 纯 commission 成分


# ===========================================================================
# 不假绿灯 / 不静默:opt-in 合同的 raise 门
# ===========================================================================


def test_sqrt_declared_without_coef_raises_no_silent_zero():
    """声明 impact_model='sqrt' 却没给 Y → raise(绝不静默当 0 冲击=假绿灯)。"""
    with pytest.raises(ValueError, match="impact_coef|Y|sqrt"):
        to_backtest_cost_model(EquityCostModel(impact_model="sqrt"))


def test_coef_given_but_preset_not_sqrt_raises_honest_mismatch():
    """给了 Y 却预设非 sqrt(如默认 linear) → raise(诚实拒绝口径不一致,不偷塞冲击)。"""
    with pytest.raises(ValueError, match="sqrt"):
        to_backtest_cost_model(EquityCostModel(impact_model="linear"), impact_coef=0.3)


@pytest.mark.parametrize("bad", [0.0, -0.5, float("nan"), float("inf")])
def test_invalid_coef_rejected(bad):
    """无效 Y(0/负/非有限)即便声明 sqrt 也 raise(要关用 None、别用 0)。"""
    with pytest.raises(ValueError, match="impact_coef|Y|无效"):
        to_backtest_cost_model(EquityCostModel(impact_model="sqrt"), impact_coef=bad)


def test_unsupported_preset_type_raises():
    with pytest.raises(TypeError, match="不支持|EquityCostModel"):
        to_backtest_cost_model(object())  # type: ignore[arg-type]


# ===========================================================================
# 费率口径映射(保守·诚实):crypto taker / bnb 折让 / perp funding 不伪造
# ===========================================================================


def test_crypto_spot_uses_taker_and_applies_bnb_discount():
    """crypto_spot:commission=taker×(1-bnb_discount)、无印花/过户。"""
    cm = to_backtest_cost_model(CryptoSpotCostModel(taker_bps=10.0, maker_bps=2.0,
                                                    bnb_discount=0.25, slippage_bps=3.0))
    assert abs(cm.commission_bps - 10.0 * 0.75) < 1e-12       # taker 口径 + bnb 折让
    assert cm.slippage_bps == 3.0
    assert cm.stamp_duty_bps == 0.0 and cm.transfer_fee_bps == 0.0
    assert cm.impact_coef == 0.0                              # 默认关


def test_crypto_perp_funding_not_fabricated():
    """**不伪造 funding**:perp 桥出的 funding_bps_per_8h=0(funding 是持仓成本、不属 per-fill)。

    种坏:从 funding_rate_apply=True 编一个 funding 数塞进 funding_bps_per_8h → 本断言崩。
    """
    cm = to_backtest_cost_model(CryptoPerpCostModel(taker_bps=4.0, funding_rate_apply=True,
                                                    borrow_bps_per_day=3.0, slippage_bps=2.0))
    assert cm.funding_bps_per_8h == 0.0                       # 不伪造 funding
    assert cm.commission_bps == 4.0 and cm.slippage_bps == 2.0


# ===========================================================================
# 便捷入口 backtest_cost_model_for(单一默认源·不复制默认值)
# ===========================================================================


def test_backtest_cost_model_for_dispatch_defaults_off():
    """按 asset_class 取默认预设 → 默认冲击关、费率=该档预设默认(单一默认源)。"""
    eq = backtest_cost_model_for("equity_cn")
    assert eq.commission_bps == EquityCostModel().commission_bps and eq.impact_coef == 0.0
    perp = backtest_cost_model_for("crypto_perp")
    assert perp.commission_bps == CryptoPerpCostModel().taker_bps and perp.impact_coef == 0.0


def test_backtest_cost_model_for_optin_sqrt():
    """便捷入口也走同一 opt-in 合同:override impact_model='sqrt'+给 Y → 启用。"""
    cm = backtest_cost_model_for("equity_cn", impact_model="sqrt", impact_coef=0.3,
                                 impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.02})
    assert cm.impact_coef == 0.3


def test_backtest_cost_model_for_invalid_asset_class_raises():
    with pytest.raises(ValueError, match="asset_class|equity_cn"):
        backtest_cost_model_for("mixed")
