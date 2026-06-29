"""§11 可证伪验收（种坏门必抓）· InstrumentSpec typed 本体 + MarketCapabilityMatrix。

对抗门（坏门被种入即必抓红）：
  1. 期权 spec 缺 expiry/strike/contract_multiplier/settlement → 拒
     （MUT：把任一改为可选/删 gt=0 即红）。
  2. MarketCapabilityMatrix 缺 live 权限仍尝试 live → 拒；**A股 live = 恒拒**，
     哪怕伪造 live=True + 权限齐 + execution available 仍恒拒
     （MUT：删 live_forbidden 硬墙 / 删缺权限检查即红）。
  3. 跨币种缺 base currency / FX conversion → 拒；桥接不匹配 → 拒
     （MUT：删 base 检查 / 删 conversion 检查即红）。
  4. 各资产类 typed 字段齐 → 正常放行不误伤（spec_id 内容寻址、crypto live 过门、A股 paper 过门）。

单一源核对：A股 live 恒拒与 security.gate.policy.classify 同源（不另造第二本 A股账）。
下游回填：InstrumentSpec.spec_ref 可直接填 strategy_book.ShortExecutionRequirement.instrument_spec_ref。

测试只 import app.instruments（被测对象）+ security.gate.policy（核对单一源，不改）+
strategy（只读验回填，不改）。不碰 execution/main/OrderGuard。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

# C-S11：typed 合约本体单一源 = research_os.market_data_contract（orphan instruments/spec.py 已删）。
from app.research_os.market_data_contract import (
    BondSpec,
    CommoditySpec,
    CrossCurrencyError,
    CryptoPerpSpec,
    CryptoSpotSpec,
    EquitySpec,
    FutureSpec,
    FxConversion,
    FxSpec,
    GenericInstrumentSpec,
    InstrumentSpecError,
    OptionSpec,
    parse_instrument_spec,
)
# capability 层仍在 instruments.capability（C-S11 外·不动）。
from app.instruments import (
    MarketCapability,
    MarketCapabilityError,
    MarketCapabilityMatrix,
    live_forbidden,
)
from app.security.gate.policy import TrustTier, classify

_EXPIRY = datetime(2026, 12, 31, tzinfo=UTC)
_MATURITY = datetime(2035, 1, 1, tzinfo=UTC)


# ───────────────────────── 构造器（typed 齐全的正路径基线）─────────────────────────
def _option_kwargs(**over) -> dict:
    base = dict(
        spec_kind="option",
        symbol="510300C2612M04000",
        asset_class="options",
        quote_currency="CNY",
        expiry=_EXPIRY,
        strike=4.0,
        contract_multiplier=10000,
        settlement="cash",
        exercise_style="european",
        option_type="call",
        underlying_ref="510300.SH",
    )
    base.update(over)
    return base


def _crypto_perp_cap(**over) -> MarketCapability:
    base = dict(
        asset_class="crypto_perp",
        instrument_type="perp",
        market="BINANCE",
        testnet=True,
        live=True,
        short=True,
        leverage=True,
        margin=True,
        data_availability="available",
        cost_model_availability="available",
        execution_availability="available",
        permission_requirement="binance_trade_key",
    )
    base.update(over)
    return MarketCapability(**base)


def _ashare_cap(**over) -> MarketCapability:
    base = dict(
        asset_class="equity_cn",
        instrument_type="spot",
        market="CN",
        paper=True,
        data_availability="available",
        cost_model_availability="available",
        execution_availability="available",
    )
    base.update(over)
    return MarketCapability(**base)


# ═══════════════════════ 门 1 · 期权 typed 必填（缺即拒，MUT 放过→红）═══════════════════════
@pytest.mark.parametrize("missing", ["expiry", "strike", "contract_multiplier", "settlement"])
def test_option_missing_required_field_rejected_via_factory(missing):
    data = _option_kwargs()
    data.pop(missing)
    with pytest.raises(InstrumentSpecError) as ei:
        parse_instrument_spec(data)
    assert missing in str(ei.value)


@pytest.mark.parametrize("missing", ["expiry", "strike", "contract_multiplier", "settlement"])
def test_option_missing_required_field_rejected_on_direct_construction(missing):
    data = _option_kwargs()
    data.pop(missing)
    with pytest.raises(ValidationError):
        OptionSpec(**data)


@pytest.mark.parametrize("field,bad", [("strike", 0.0), ("strike", -1.0),
                                       ("contract_multiplier", 0.0), ("contract_multiplier", -5.0)])
def test_option_degenerate_value_rejected(field, bad):
    # strike/multiplier 必 > 0：种 0/负值即拒（MUT 删 gt=0 → 红）。
    with pytest.raises((InstrumentSpecError, ValidationError)):
        parse_instrument_spec(_option_kwargs(**{field: bad}))


def test_option_bad_settlement_rejected():
    with pytest.raises((InstrumentSpecError, ValidationError)):
        parse_instrument_spec(_option_kwargs(settlement="weird"))


# ═══════════════ 门 2 · MarketCapability live（缺权限→拒 / A股恒拒不可绕）═══════════════
def test_ashare_live_forbidden_single_source_matches_classify():
    # 单一源核对：本模块 live_forbidden 与执行门 classify 同口径，绝不另造第二本 A股账。
    assert live_forbidden("equity_cn") is True
    assert live_forbidden("equity_cn") == (classify("equity_cn", is_live=True) == TrustTier.PAPER)
    # equity / cn 各自独立触发恒拒（双保险）。
    assert live_forbidden("equity", "US") is True
    assert live_forbidden("rate", "CN") is True
    # crypto 可达 live（非恒拒）。
    assert live_forbidden("crypto_perp", "BINANCE") is False
    assert classify("crypto_perp", is_live=True) == TrustTier.CRYPTO_LIVE


def test_ashare_clean_record_live_is_hard_denied():
    # 合法 A股记录（live=False）：paper 放行，live 端恒拒。
    cap = _ashare_cap()
    cap.assert_can_execute("research")
    cap.assert_can_execute("backtest")
    cap.assert_can_execute("paper")
    with pytest.raises(MarketCapabilityError) as ei:
        cap.assert_can_execute("live")
    assert "恒拒" in str(ei.value)


def test_ashare_forged_live_true_still_hard_denied_cannot_be_bypassed():
    # 关键 MUT 抓点：哪怕伪造 live=True + 权限齐 + execution available，A股 live 仍恒拒。
    forged = _ashare_cap(
        live=True,
        permission_requirement="cn_broker_key",
        execution_availability="available",
    )
    # 诚实派生：声明 live 但市场恒拒 → 有效 live 权限 False。
    assert forged.live is True
    assert forged.effective_live_permission() is False
    with pytest.raises(MarketCapabilityError) as ei:
        forged.assert_can_execute("live", granted_permissions={"cn_broker_key"})
    assert "恒拒" in str(ei.value)


def test_crypto_missing_live_permission_rejected():
    # 缺 live 权限仍尝试 live → 拒（§11）。
    cap = _crypto_perp_cap(live=False)
    with pytest.raises(MarketCapabilityError) as ei:
        cap.assert_can_execute("live")
    assert "未授予 live 权限" in str(ei.value)


def test_crypto_live_permission_requirement_not_granted_rejected():
    cap = _crypto_perp_cap()  # permission_requirement="binance_trade_key"
    with pytest.raises(MarketCapabilityError):
        cap.assert_can_execute("live", granted_permissions=set())  # 未授予
    with pytest.raises(MarketCapabilityError):
        cap.assert_can_execute("live", granted_permissions={"wrong_key"})


def test_crypto_live_unavailable_execution_rejected():
    cap = _crypto_perp_cap(execution_availability="unavailable")
    with pytest.raises(MarketCapabilityError):
        cap.assert_can_execute("live", granted_permissions={"binance_trade_key"})


def test_matrix_unregistered_market_deny_by_default():
    matrix = MarketCapabilityMatrix()
    matrix.register(_crypto_perp_cap())
    with pytest.raises(MarketCapabilityError) as ei:
        matrix.get("equity_us", "US")
    assert "deny-by-default" in str(ei.value)
    with pytest.raises(MarketCapabilityError):
        matrix.assert_can_execute("unknown_class", "NOWHERE", env="live")


def test_capability_action_gate_short_borrow():
    # A股记录默认不可做空/不可借 → assert_supports 拒（§11 capability flags）。
    ashare = _ashare_cap()
    with pytest.raises(MarketCapabilityError):
        ashare.assert_supports("short")
    with pytest.raises(MarketCapabilityError):
        ashare.assert_supports("borrow")
    # crypto perp 支持 short/leverage/margin。
    _crypto_perp_cap().assert_supports("short", "leverage", "margin")


# ═══════════════════ 门 3 · 跨币种结算（缺 base / 缺 FX conversion → 拒）═══════════════════
def _btc_spot() -> CryptoSpotSpec:
    return CryptoSpotSpec(symbol="BTC-USDT", asset_class="crypto_spot",
                          quote_currency="USDT", base_asset="BTC")


def test_cross_currency_missing_base_currency_rejected():
    with pytest.raises(CrossCurrencyError) as ei:
        _btc_spot().assert_currency_settleable(base_currency=None)
    assert "base currency" in str(ei.value)
    with pytest.raises(CrossCurrencyError):
        _btc_spot().assert_currency_settleable(base_currency="   ")


def test_cross_currency_missing_fx_conversion_rejected():
    with pytest.raises(CrossCurrencyError) as ei:
        _btc_spot().assert_currency_settleable(base_currency="USD")  # USDT != USD, 无 conversion
    assert "FX conversion" in str(ei.value)


def test_cross_currency_mismatched_conversion_rejected():
    bad = FxConversion(base_currency="JPY", quote_currency="EUR", rate_source="x")
    with pytest.raises(CrossCurrencyError):
        _btc_spot().assert_currency_settleable(base_currency="USD", conversion=bad)


def test_fx_conversion_requires_rate_source():
    # rate_source 必填（缺来源 = 无据换算）。
    with pytest.raises(ValidationError):
        FxConversion(base_currency="USD", quote_currency="USDT", rate_source="")


# ═══════════════════ 门 4 · 各资产类 typed 齐 → 正常放行（不误伤）═══════════════════
def test_all_asset_classes_typed_complete_construct_ok():
    specs = [
        OptionSpec(**_option_kwargs()),
        FutureSpec(symbol="ES", asset_class="futures", quote_currency="USD", expiry=_EXPIRY,
                   contract_multiplier=50, settlement="cash", roll_rule="volume_oi_switch",
                   continuous_contract_rule="panama"),
        BondSpec(symbol="US10Y", asset_class="bond", quote_currency="USD", coupon_rate=0.04,
                 maturity=_MATURITY, day_count="ACT/ACT", duration=8.5, convexity=0.9,
                 coupon_frequency=2),
        FxSpec(symbol="EURUSD", asset_class="fx", quote_currency="", base_ccy="EUR", quote_ccy="USD"),
        CommoditySpec(symbol="CL", asset_class="commodity", quote_currency="USD",
                      contract_multiplier=1000, storage_cost_bps=12, seasonality="winter_demand"),
        EquitySpec(symbol="510300.SH", asset_class="equity_cn", quote_currency="CNY",
                   lot_size=100, is_etf=True, underlying_index_ref="000300.SH"),
        CryptoSpotSpec(symbol="BTC-USDT", asset_class="crypto_spot", quote_currency="USDT", base_asset="BTC"),
        CryptoPerpSpec(symbol="BTC-USDT-PERP", asset_class="crypto_perp", quote_currency="USDT",
                       funding_interval_hours=8, max_leverage=20.0),
        GenericInstrumentSpec(symbol="X", asset_class="custom", quote_currency="USD", attributes={"k": "v"}),
    ]
    # 全部构造成功 + spec_id 非空且唯一。
    assert all(s.spec_id and s.spec_id.startswith("instr_") for s in specs)
    assert len({s.spec_id for s in specs}) == len(specs)


def test_fx_spec_quote_currency_synced_to_quote_ccy():
    fx = FxSpec(symbol="EURUSD", asset_class="fx", quote_currency="", base_ccy="EUR", quote_ccy="USD")
    assert fx.quote_currency == "USD"
    # 显式传不一致的 quote_currency → 拒（口径裂）。
    with pytest.raises((InstrumentSpecError, ValidationError)):
        FxSpec(symbol="EURUSD", asset_class="fx", quote_currency="JPY", base_ccy="EUR", quote_ccy="USD")


def test_spec_id_content_addressed_decorative_excluded():
    a = OptionSpec(**_option_kwargs())
    b = OptionSpec(**_option_kwargs(name="renamed contract", description="some note"))
    assert a.spec_id == b.spec_id  # 改名/改描述不算新标的
    c = OptionSpec(**_option_kwargs(strike=5.0))
    assert a.spec_id != c.spec_id  # 改结构字段 → 新身份


def test_same_currency_settlement_ok_no_conversion_needed():
    spec = _btc_spot()
    spec.assert_currency_settleable(base_currency="USDT")  # 同币种，不 raise
    spec.assert_currency_settleable(base_currency="usdt")  # 大小写不敏感


def test_cross_currency_with_matching_conversion_ok():
    conv = FxConversion(base_currency="USD", quote_currency="USDT", rate_source="binance_spot")
    _btc_spot().assert_currency_settleable(base_currency="USD", conversion=conv)  # 不 raise


def test_crypto_live_full_capability_passes_not_a_false_negative():
    # 正路径不误伤：crypto perp，live 权限 + 要件齐 → 过 live 门。
    matrix = MarketCapabilityMatrix()
    matrix.register(_crypto_perp_cap())
    matrix.assert_can_execute("crypto_perp", "BINANCE", env="live",
                              granted_permissions={"binance_trade_key"})
    matrix.assert_can_execute("crypto_perp", "BINANCE", env="paper")
    matrix.assert_can_execute("crypto_perp", "BINANCE", env="testnet")


def test_ashare_paper_passes_live_denied_via_matrix():
    matrix = MarketCapabilityMatrix()
    matrix.register(_ashare_cap())
    matrix.assert_can_execute("equity_cn", "CN", env="paper")  # 放行
    with pytest.raises(MarketCapabilityError):
        matrix.assert_can_execute("equity_cn", "CN", env="live")  # 恒拒


# ═══════════════════ 下游回填：spec_ref → instrument_spec_ref（只读验证）═══════════════════
def test_spec_ref_backfills_strategy_book_instrument_spec_ref():
    # InstrumentSpec.spec_ref 是非空 str，可直接填 strategy_book 的 instrument_spec_ref 槽。
    from app.strategy import ShortExecutionRequirement, StrategyBook, StrategyLeg

    opt = OptionSpec(**_option_kwargs(asset_class="crypto_option", quote_currency="USDT",
                                      symbol="BTC-CALL", underlying_ref="BTC-USDT"))
    assert isinstance(opt.spec_ref, str) and opt.spec_ref
    req = ShortExecutionRequirement(
        instrument_spec_ref=opt.spec_ref, venue="BINANCE", borrow_available=True,
        margin_ratio=0.1, regulation_ok=True,
    )
    assert req.is_satisfied()  # 回填后要件齐（非 A股）
    assert "InstrumentSpec" not in req.missing()
    # 非 A股 short 腿 + 要件齐 → runtime 执行门放行（不下单，仅 typed 守门）。
    book = StrategyBook(
        name="crypto option short demo",
        asset_class="crypto_option",
        legs=[StrategyLeg(asset_ref="sig::x", asset_kind="signal", side="short",
                          weight=-0.2, short_exec=req)],
    )
    book.assert_runtime_executable()  # 不 raise（A股才硬拒）
