"""§9 可证伪验收（种坏门必抓）· Forecast typed + StrategyBook typed。

对抗门（坏门被种入即必抓红）：
  1. 裸 Forecast（未绑 Signal Contract）进信号层 → 拒（MUT：删裸输出门即红）。
  2. StrategyBook short intent 缺 borrow/margin/venue/instrument/regulation → 拒（红线·MUT 删任一检查即红）。
  3. StrategyBook 缺 payoff / 资本账 / 引用资产未登记 → 不可晋级。
  4. 正路径：Forecast→Contract→Signal、StrategyBook 全 typed → 放行不误伤。
另含：过期 Forecast 拒、孤儿/伪绑定拒、A股 short 硬拒（R13）、资本账脏账拒。

测试只 import app.strategy（被测对象）+ signal_contract（复用，不改），不碰 execution/main。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.factor_factory.signal_contract import LeakageDeclaration, SignalContractRegistry
from app.strategy import (
    CapitalAccount,
    Forecast,
    ForecastError,
    PayoffSpec,
    ShortExecutionRequirement,
    StrategyBook,
    StrategyBookError,
    StrategyBookExecutionError,
    StrategyLeg,
    bind_forecast_to_signal,
)

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _full_leakage() -> LeakageDeclaration:
    return LeakageDeclaration(oof=True, purge=True, embargo=True, embargo_days=5)


def _forecast(**over) -> Forecast:
    base = dict(
        symbol="000300.SH",
        model_ref="gbdt_xs_rank_v3.pkl",
        source_lib="ml",
        output_kind="xs_score",
        horizon=5,
        value=0.42,
        confidence=0.7,
        event_time=_T0,
        effective_at=_T0,
        valid_until=_T0 + timedelta(days=5),
        leakage=_full_leakage(),
    )
    base.update(over)
    return Forecast(**base)


def _payoff() -> PayoffSpec:
    return PayoffSpec(kind="long_short_spread", description="long A / short B 价差", hedge_ratio=1.0,
                      expected_pnl_bps=30.0, expected_short_pnl_bps=12.0)


def _capital() -> CapitalAccount:
    return CapitalAccount(base_currency="USDT", gross_exposure=1.0, net_exposure=0.0,
                          leverage=2.0, capital_allocation=100_000.0)


def _full_short_exec() -> ShortExecutionRequirement:
    return ShortExecutionRequirement(
        instrument_spec_ref="ispec::btcusdt_perp", venue="binance_um",
        borrow_available=True, borrow_rate_bps_per_day=1.0,
        margin_ratio=0.1, regulation_ok=True, permission_ref="perm::short_crypto",
    )


# ============================ 对抗门 1：裸 Forecast 必拒（MUT 核心） ============================

def test_bare_forecast_unbound_rejected() -> None:
    """裸 Forecast（signal_contract_id=None）进信号层 → 拒。坏门被种入（删裸输出门）即红。"""
    reg = SignalContractRegistry()
    fc = _forecast()
    assert fc.signal_contract_id is None
    with pytest.raises(ForecastError, match="未绑 Signal Contract"):
        bind_forecast_to_signal(fc, reg, ts=_T0)


def test_forecast_incomplete_leakage_register_rejected() -> None:
    """泄露声明不全（缺 embargo）→ 登记契约即被 signal_contract 拒（复用 R18 门，不重造）。"""
    reg = SignalContractRegistry()
    fc = _forecast(leakage=LeakageDeclaration(oof=True, purge=True, embargo=False))
    with pytest.raises(Exception, match="泄露声明门|embargo"):
        fc.register_contract(reg, name="leaky")


def test_forecast_orphan_binding_rejected() -> None:
    """signal_contract_id 指向未登记契约（孤儿绑定）→ 拒。"""
    reg = SignalContractRegistry()
    fc = _forecast(signal_contract_id="deadbeefdeadbeef")
    with pytest.raises(ForecastError, match="孤儿|未在 Signal Contract"):
        bind_forecast_to_signal(fc, reg, ts=_T0)


def test_forecast_forged_binding_rejected() -> None:
    """绑定 id 与字段口径不一致（伪绑定）→ 拒（内容寻址一致性）。"""
    reg = SignalContractRegistry()
    fc = _forecast()
    fc.register_contract(reg, name="real")
    # 篡改字段口径但保留旧 contract id → 重算 id 不匹配。
    fc.output_kind = "prob"
    with pytest.raises(ForecastError, match="伪绑定|不一致"):
        bind_forecast_to_signal(fc, reg, ts=_T0)


def test_forecast_expired_rejected() -> None:
    """过期 Forecast（as_of 越过 valid_until）→ 不得产 live Signal。"""
    reg = SignalContractRegistry()
    fc = _forecast()
    fc.register_contract(reg, name="ok")
    with pytest.raises(ForecastError, match="过期"):
        bind_forecast_to_signal(fc, reg, ts=_T0 + timedelta(days=99))


# ============================ 对抗门 2：short intent ≠ 可执行 short（红线·MUT 核心） ===========

def _short_book(short_exec: ShortExecutionRequirement | None, *, asset_class: str = "crypto_perp") -> StrategyBook:
    return StrategyBook(
        name="ls", asset_class=asset_class,
        legs=[
            StrategyLeg(asset_ref="sig::long", asset_kind="signal", side="long", weight=0.5),
            StrategyLeg(asset_ref="sig::short", asset_kind="signal", side="short", weight=-0.5,
                        short_exec=short_exec),
        ],
        payoff=_payoff(), capital_account=_capital(),
        linked_assets=["sig::long", "sig::short"],
    )


def test_short_intent_no_exec_requirement_rejected() -> None:
    """short 腿无任何执行要件 → 当可执行 short 即拒（§9 红线）。"""
    book = _short_book(short_exec=None)
    with pytest.raises(StrategyBookExecutionError, match="缺执行要件|可执行 short"):
        book.assert_runtime_executable()


@pytest.mark.parametrize(
    ("drop", "needle"),
    [
        ("instrument_spec_ref", "InstrumentSpec"),
        ("venue", "venue"),
        ("borrow_available", "borrow"),
        ("margin", "margin"),
        ("regulation_ok", "regulation"),
    ],
)
def test_short_intent_missing_each_requirement_rejected(drop: str, needle: str) -> None:
    """逐项抽掉 borrow/margin/venue/instrument/regulation → 必拒并点名缺项。

    这是红线的 MUT 锚点：若 ShortExecutionRequirement.missing() 的任一检查被种坏（删除），
    对应 case 不再 raise → 红。"""
    kwargs = dict(
        instrument_spec_ref="ispec::x", venue="binance_um",
        borrow_available=True, margin_ratio=0.1, regulation_ok=True,
    )
    if drop == "instrument_spec_ref":
        kwargs["instrument_spec_ref"] = None
    elif drop == "venue":
        kwargs["venue"] = None
    elif drop == "borrow_available":
        kwargs["borrow_available"] = False
    elif drop == "margin":
        kwargs["margin_ratio"] = None  # 且无 margin_ref
    elif drop == "regulation_ok":
        kwargs["regulation_ok"] = False
    req = ShortExecutionRequirement(**kwargs)
    assert needle in req.missing()
    book = _short_book(short_exec=req)
    with pytest.raises(StrategyBookExecutionError, match=needle):
        book.assert_runtime_executable()


def test_a_share_short_hard_rejected_r13() -> None:
    """A股 short 腿硬拒（R13 禁空头侧 + A股永不实盘），即便要件齐全也不可绕过。"""
    book = _short_book(short_exec=_full_short_exec(), asset_class="equity_cn")
    with pytest.raises(StrategyBookExecutionError, match="A股禁空头侧|R13"):
        book.assert_runtime_executable()
    # 即便 short_exec 全满足，A股 short 也不进可执行集合。
    assert book.executable_short_legs() == []


# ============================ 对抗门 3：StrategyBook typed 契约完整性 ============================

def test_strategybook_missing_payoff_not_promotable() -> None:
    book = StrategyBook(
        name="np", asset_class="crypto_perp",
        legs=[StrategyLeg(asset_ref="sig::a", asset_kind="signal", side="long", weight=1.0)],
        payoff=None, capital_account=_capital(), linked_assets=["sig::a"],
    )
    with pytest.raises(StrategyBookError, match="缺 payoff"):
        book.assert_promotable()


def test_strategybook_missing_capital_account_not_promotable() -> None:
    book = StrategyBook(
        name="nc", asset_class="crypto_perp",
        legs=[StrategyLeg(asset_ref="sig::a", asset_kind="signal", side="long", weight=1.0)],
        payoff=_payoff(), capital_account=None, linked_assets=["sig::a"],
    )
    with pytest.raises(StrategyBookError, match="资本账"):
        book.assert_promotable()


def test_strategybook_unlisted_asset_not_promotable() -> None:
    """引用资产未登记进 linked_assets（run_config 无法注入）→ 拒（§1 可证伪验收）。"""
    book = StrategyBook(
        name="ua", asset_class="crypto_perp",
        legs=[StrategyLeg(asset_ref="sig::a", asset_kind="signal", side="long", weight=1.0)],
        payoff=_payoff(), capital_account=_capital(), linked_assets=[],  # 漏登记
    )
    with pytest.raises(StrategyBookError, match="linked_assets|run_config"):
        book.assert_promotable()


def test_capital_account_dirty_ledger_rejected() -> None:
    """资本账脏账：gross < |net| → 构造即拒（敞口会计恒真）。"""
    with pytest.raises(ValueError, match="gross_exposure"):
        CapitalAccount(base_currency="USDT", gross_exposure=0.5, net_exposure=1.0,
                       leverage=1.0, capital_allocation=1000.0)


# ============================ 对抗门 4：正路径放行不误伤 ============================

def test_forecast_to_signal_happy_path() -> None:
    """Forecast→register_contract→bind → 合法 Signal，谱系回指契约 ref。"""
    reg = SignalContractRegistry()
    fc = _forecast()
    contract = fc.register_contract(reg, name="xs rank v3")
    sig = bind_forecast_to_signal(fc, reg, ts=_T0)
    assert sig.direction == "long"
    assert sig.magnitude == pytest.approx(0.42)
    assert sig.confidence == pytest.approx(0.7)
    assert sig.symbol == "000300.SH"
    assert sig.contributing_factors[0].factor_id == contract.signal_ref
    assert sig.contributing_factors[0].contribution == pytest.approx(0.42)


def test_forecast_short_direction_signal_is_research_layer() -> None:
    """Forecast 可产 short 方向 Signal（研究层合法）——short Signal ≠ 可执行 short（那是 StrategyBook 执行门的事）。"""
    reg = SignalContractRegistry()
    fc = _forecast(value=-0.3)
    fc.register_contract(reg, name="bearish")
    sig = bind_forecast_to_signal(fc, reg, ts=_T0)
    assert sig.direction == "short"
    assert sig.contributing_factors[0].contribution == pytest.approx(-0.3)


def test_strategybook_full_typed_promotable_and_executable() -> None:
    """全 typed 契约 + short 要件齐全（非 A股）→ 晋级门 + 执行门双过，不误伤。"""
    book = _short_book(short_exec=_full_short_exec())
    book.assert_promotable()           # 不抛
    book.assert_runtime_executable()   # 不抛
    assert len(book.executable_short_legs()) == 1
    assert book.referenced_assets() == ["sig::long", "sig::short"]
    assert book.book_id.startswith("book_")


def test_long_only_book_executable_no_short_gate() -> None:
    """纯多头 book：执行门无 short 腿可拒 → 直接过（不误伤多头）。"""
    book = StrategyBook(
        name="lo", asset_class="equity_cn",
        legs=[StrategyLeg(asset_ref="sig::a", asset_kind="signal", side="long", weight=1.0)],
        payoff=_payoff(), capital_account=_capital(), linked_assets=["sig::a"],
    )
    book.assert_promotable()
    book.assert_runtime_executable()  # 无 short 腿 → 不抛（A股纯多头合规）


def test_book_id_stable_ignores_name() -> None:
    """book_id 内容寻址只认结构字段，改 name/description 不变 id（复用单一哈希族）。"""
    b1 = _short_book(short_exec=_full_short_exec())
    b2 = StrategyBook(
        name="DIFFERENT NAME", asset_class="crypto_perp",
        legs=[
            StrategyLeg(asset_ref="sig::long", asset_kind="signal", side="long", weight=0.5),
            StrategyLeg(asset_ref="sig::short", asset_kind="signal", side="short", weight=-0.5,
                        short_exec=_full_short_exec()),
        ],
        payoff=_payoff(), capital_account=_capital(),
        linked_assets=["sig::long", "sig::short"], description="totally different prose",
    )
    assert b1.book_id == b2.book_id
