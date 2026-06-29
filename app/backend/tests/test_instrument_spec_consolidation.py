"""C-S11 §11 · InstrumentSpec 单一源收敛的可证伪验收（种坏门必抓·变异三态）。

背景：原有两套标的本体——`research_os.market_data_contract.InstrumentSpec`（flat·LIVE 登记记录，
main.py + PersistentMarketDataRegistry 在用）与 orphan `instruments/spec.py`（Pydantic typed 富类型，
零生产 importer）。C-S11 Commit 1 把 flat 升 Pydantic + 吸收 orphan 富能力 + 删 orphan = **单一源**。

本文件把「additive·零破坏·单一源」钉成机器可证不变量：
  · 门②  flat InstrumentSpec additive 值 validator（strike>0 / settlement∈{physical,cash}）
          ——仅 provided 时 fire，缺则不强制（additive）。【MUT 删 gt=0 / 放宽 Literal → 红】
  · 门③  orphan instruments/spec.py 已删（import → ModuleNotFoundError）+ 单一 InstrumentSpec 源
          （app.research_os.InstrumentSpec is market_data_contract.InstrumentSpec）。
  · 门④  持久化 read-back tolerance：旧 JSONL 含窄枚举外 token（instrument_type=perpetual·
          asset_class=cn_equity）replay 不 raise。【MUT 把 asset_class/instrument_type 收紧成 Literal
          → load 期 fail-closed → 红（app 起不来 hazard 被锁）】
  · 门⑥  to_dict() superset-stable（exclude None）→ 既有记录 content_hash 零漂移。
  · spec_id additive·非 PK：instrument_ref 仍是 registry 身份，spec_id 不入 to_dict 不扰 record_hash。
  · 门①  ref-presence gate 不削弱（validate_instrument_spec 期权缺 *_ref / 期货缺 margin_ref → 拒）。
"""

from __future__ import annotations

import importlib
import json

import pytest
from pydantic import BaseModel, ValidationError

from app.research_os.market_data_contract import (
    InstrumentSpec,
    PersistentMarketDataRegistry,
    instrument_spec_from_dict,
    validate_instrument_spec,
)
from app.lineage.ids import content_hash


def _flat(**overrides) -> InstrumentSpec:
    data = {
        "instrument_ref": "instrument:BTCUSDT",
        "asset_class": "crypto_spot",
        "instrument_type": "spot",
        "currency": "USDT",
        "exchange_calendar_ref": "calendar:crypto_24_7",
        "symbol_mapping_ref": "symbol:btc_usdt",
    }
    data.update(overrides)
    return InstrumentSpec(**data)


# ═══════════════ 门② · flat InstrumentSpec additive 值 validator（provided 时才 fire）═══════════════
def test_flat_strike_value_validator_only_fires_when_provided():
    # strike>0 提供合法 → 过 + 进 to_dict（有值才 emit）。
    ok = _flat(asset_class="options", instrument_type="option", strike=4.0)
    assert ok.strike == 4.0
    assert ok.to_dict()["strike"] == 4.0
    # strike<=0 提供 → 拒（新 value validator）。【MUT 删 Field(gt=0) → 此处不再 raise → 红】
    with pytest.raises(ValidationError):
        _flat(asset_class="options", instrument_type="option", strike=0.0)
    with pytest.raises(ValidationError):
        _flat(asset_class="options", instrument_type="option", strike=-1.0)
    # strike 缺 → 不强制（additive·过）+ 不进 to_dict（exclude None）。
    miss = _flat(asset_class="options", instrument_type="option")
    assert miss.strike is None
    assert "strike" not in miss.to_dict()


def test_flat_contract_multiplier_and_coupon_value_validators():
    assert _flat(contract_multiplier=10000.0).contract_multiplier == 10000.0
    with pytest.raises(ValidationError):
        _flat(contract_multiplier=0.0)  # multiplier>0
    assert _flat(coupon_rate=0.0).coupon_rate == 0.0  # 零息合法（ge=0）
    with pytest.raises(ValidationError):
        _flat(coupon_rate=-0.01)


def test_flat_settlement_and_day_count_in_domain():
    assert _flat(settlement="cash").settlement == "cash"
    assert _flat(settlement="physical").settlement == "physical"
    # settlement∈{physical,cash}：种域外值即拒。【MUT 把 Settlement 放宽成 str → 不再 raise → 红】
    with pytest.raises(ValidationError):
        _flat(settlement="weird")
    assert _flat(day_count="ACT/365").day_count == "ACT/365"
    with pytest.raises(ValidationError):
        _flat(day_count="bogus")


# ═══════════════ 门③ · orphan 已删 + 单一 InstrumentSpec 源 ═══════════════
def test_orphan_instruments_spec_module_deleted():
    # orphan instruments/spec.py 已删：import 即 ModuleNotFoundError（不再有第二套 InstrumentSpec）。
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.instruments.spec")


def test_single_live_instrument_spec_source():
    import app.research_os as ro
    from app.research_os import market_data_contract as mdc

    # research_os 包 re-export 的 InstrumentSpec 即 market_data_contract 的同一对象（单一源）。
    assert ro.InstrumentSpec is mdc.InstrumentSpec
    assert ro.instrument_spec_from_dict is mdc.instrument_spec_from_dict
    # LIVE flat InstrumentSpec 现为 Pydantic 单一源；typed 基类刻意改名 TypedInstrumentSpec 不撞名。
    assert issubclass(mdc.InstrumentSpec, BaseModel)
    assert mdc.InstrumentSpec is not mdc.TypedInstrumentSpec


# ═══════════════ 门④ · 持久化 read-back tolerance（Literal hazard 锁）═══════════════
def test_persisted_history_with_narrow_outside_tokens_replays_without_raise(tmp_path):
    # 模拟既有持久化历史：窄枚举外 token（perpetual / cn_equity）。otherwise-valid（含 calendar + margin
    # 以过 perpetual margin gate），故 replay 唯一可能炸点 = asset_class/instrument_type 被收紧成 Literal。
    path = tmp_path / "market_data_assets.jsonl"
    row = {
        "schema_version": 1,
        "event_type": "instrument_spec_recorded",
        "instrument": {
            "instrument_ref": "instrument:legacy_perp",
            "asset_class": "cn_equity",        # §0 目录内但窄枚举外
            "instrument_type": "perpetual",    # 任何 Literal 之外
            "currency": "USDT",
            "exchange_calendar_ref": "calendar:legacy",
            "margin_ref": "margin:legacy",     # perpetual 必需（保 ref-presence gate）
        },
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    # replay 不 raise（MUT 把 asset_class/instrument_type 收紧成 Literal → 此处 ValueError 红）。
    replayed = PersistentMarketDataRegistry(path)
    got = replayed.instrument("instrument:legacy_perp")
    assert got.asset_class == "cn_equity"
    assert got.instrument_type == "perpetual"


def test_from_dict_keeps_valueerror_contract_on_missing_required():
    # 缺 4 必填之一 → ValueError（main.py 422 catch 依赖）。
    for missing in ("instrument_ref", "asset_class", "instrument_type", "currency"):
        data = {
            "instrument_ref": "i",
            "asset_class": "crypto_spot",
            "instrument_type": "spot",
            "currency": "USDT",
            "exchange_calendar_ref": "c",
        }
        data.pop(missing)
        with pytest.raises(ValueError):
            instrument_spec_from_dict(data)


# ═══════════════ 门⑥ · to_dict superset-stable → content_hash 零漂移 ═══════════════
def test_to_dict_superset_stable_excludes_none_additive_fields():
    base = _flat()
    d = base.to_dict()
    # 无新值时 = 恰好原 17 keys（无任何 additive 值键泄漏）。
    assert len(d) == 17
    for key in ("expiry", "strike", "contract_multiplier", "settlement", "roll_rule",
                "coupon_rate", "maturity", "day_count", "spec_id"):
        assert key not in d
    # 同输入两次构造 → content_hash 稳定。
    assert content_hash(d) == content_hash(_flat().to_dict())
    # 同一 base 上提供一个 additive 值 → 恰好多出该键（superset），原 17 keys 逐一不变。
    with_strike = _flat(strike=4.0).to_dict()
    assert set(with_strike) - set(d) == {"strike"}
    assert {k: with_strike[k] for k in d} == d


# ═══════════════ spec_id additive · 非 PK（instrument_ref 仍是身份）═══════════════
def test_spec_id_additive_non_pk_registry_keys_on_instrument_ref(tmp_path):
    rec = _flat()
    # spec_id 内容寻址 additive，但**不入 to_dict**（不扰 record_hash）。
    assert rec.spec_id.startswith("instr_")
    assert "spec_id" not in rec.to_dict()
    # 改 instrument_ref → spec_id 变（内容寻址）；但 registry 身份恒为 instrument_ref。
    assert _flat(instrument_ref="instrument:OTHER").spec_id != rec.spec_id
    registry = PersistentMarketDataRegistry(tmp_path / "md.jsonl")
    registry.record_instrument(rec)
    # registry key = instrument_ref（绝不 swap 成 spec_id）。
    assert registry.instrument("instrument:BTCUSDT").instrument_ref == "instrument:BTCUSDT"
    with pytest.raises(KeyError):
        registry.instrument(rec.spec_id)


# ═══════════════ 门① · ref-presence gate 不削弱（保现有 validate_instrument_spec）═══════════════
def test_ref_presence_gate_preserved_option_and_futures():
    # 期权缺任一 *_ref → option_semantics_incomplete（MUT 删该 gate → 红）。
    option = _flat(
        instrument_ref="instrument:SPY:call",
        asset_class="equity_us_option",
        instrument_type="option",
        currency="USD",
        expiry_ref=None,
        strike_ref=None,
        contract_multiplier_ref=None,
        settlement_ref=None,
    )
    decision = validate_instrument_spec(option)
    assert not decision.accepted
    assert "option_semantics_incomplete" in {v.code for v in decision.violations}
    # 期货/永续缺 margin_ref → futures_margin_missing（MUT 删该 gate → 红）。
    perp = _flat(
        instrument_ref="instrument:perp",
        asset_class="crypto_perp",
        instrument_type="perpetual",
        margin_ref=None,
    )
    decision2 = validate_instrument_spec(perp)
    assert not decision2.accepted
    assert "futures_margin_missing" in {v.code for v in decision2.violations}
