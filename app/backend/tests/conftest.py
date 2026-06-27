"""Make `from app.<module>` work when pytest runs from repo root.

附加：自动隔离 SENTRY_DSN，避免开发机配过的 DSN 让每次跑 pytest 时
sentry-sdk 在结束阶段去发 2 个 pending events、阻塞退出 ~2 秒。
真实想测 sentry 集成的 case 自己 setenv 即可。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 默认 unset SENTRY_DSN —— 单测不该真发数据到 Sentry
os.environ.pop("SENTRY_DSN", None)


def install_training_market_data_use_validation(
    monkeypatch,
    tmp_path: Path,
    *,
    dataset_id: str = "demo_ashare_xsec",
    validation_ref: str | None = None,
) -> str:
    from app import main
    from app.research_os import (
        DatasetSemanticsRecord,
        InstrumentSpec,
        MarketCapabilityMatrixRecord,
        MarketDataUseValidationRecord,
        PersistentMarketDataRegistry,
        ValidationUseContext,
    )

    registry = PersistentMarketDataRegistry(tmp_path / f"market_data_{dataset_id}.jsonl")
    dataset_ref = f"dataset:{dataset_id}:v1"
    instrument_ref = f"instrument:{dataset_id}:demo"
    capability_ref = f"capability:{dataset_id}:training"
    validation_ref = validation_ref or f"market_data_use:{dataset_id}:training"
    registry.record_dataset(
        DatasetSemanticsRecord(
            dataset_ref=dataset_ref,
            source_ref=f"source:{dataset_id}:synthetic_fixture",
            version="v1",
            known_at_ref=f"known_at:{dataset_id}:fixture",
            effective_at_ref=f"effective_at:{dataset_id}:fixture",
            pit_bitemporal_rules_ref=f"pit:{dataset_id}:fixture",
            quality_status="accepted",
            lineage_refs=(f"lineage:{dataset_id}:fixture",),
            freshness_status="fresh",
            checksum=f"sha256:{dataset_id}:fixture",
            asof_join_rule_ref=f"pit:{dataset_id}:fixture",
        ),
        use_context=ValidationUseContext.CONFIRMATORY_VALIDATION,
    )
    registry.record_instrument(
        InstrumentSpec(
            instrument_ref=instrument_ref,
            asset_class="a_share",
            instrument_type="equity",
            currency="CNY",
            exchange_calendar_ref="calendar:xshg",
            symbol_mapping_ref=f"symbols:{dataset_id}:fixture",
        )
    )
    registry.record_capability_matrix(
        MarketCapabilityMatrixRecord(
            matrix_ref=capability_ref,
            asset_class="a_share",
            instrument_type="equity",
            research=True,
            backtest=True,
            paper=True,
            testnet=False,
            live=False,
            long=True,
            short=False,
            leverage=False,
            options=False,
            margin=False,
            borrow=False,
            data_availability="fixture_pit_bitemporal",
            cost_model_availability="fixture_cost_model",
            execution_availability="paper_only",
            permission_requirement=None,
        ),
        use_context=ValidationUseContext.CONFIRMATORY_VALIDATION,
    )
    registry.record_use_validation(
        MarketDataUseValidationRecord(
            validation_ref=validation_ref,
            request_ref=f"training:{dataset_id}:fixture",
            use_context=ValidationUseContext.CONFIRMATORY_VALIDATION.value,
            dataset_refs=(dataset_ref,),
            instrument_refs=(instrument_ref,),
            capability_matrix_ref=capability_ref,
            capital_record_ref=None,
            transformation_refs=(f"transform:{dataset_id}:features",),
            accepted=True,
            violation_codes=(),
            evidence_refs=(
                f"pit:{dataset_id}:fixture",
                f"known_at:{dataset_id}:fixture",
                f"effective_at:{dataset_id}:fixture",
            ),
            recorded_by="pytest",
            created_at_utc="2026-06-27T00:00:00+00:00",
        )
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", registry)
    return validation_ref


def add_training_market_data_use_validation(
    *,
    dataset_id: str,
    validation_ref: str | None = None,
) -> str:
    from app import main
    from app.research_os import (
        DatasetSemanticsRecord,
        InstrumentSpec,
        MarketCapabilityMatrixRecord,
        MarketDataUseValidationRecord,
        ValidationUseContext,
    )

    registry = main.MARKET_DATA_REGISTRY
    dataset_ref = f"dataset:{dataset_id}:v1"
    instrument_ref = f"instrument:{dataset_id}:demo"
    capability_ref = f"capability:{dataset_id}:training"
    validation_ref = validation_ref or f"market_data_use:{dataset_id}:training"
    asset_class = "crypto" if "crypto" in dataset_id else "a_share"
    currency = "USDT" if asset_class == "crypto" else "CNY"
    registry.record_dataset(
        DatasetSemanticsRecord(
            dataset_ref=dataset_ref,
            source_ref=f"source:{dataset_id}:synthetic_fixture",
            version="v1",
            known_at_ref=f"known_at:{dataset_id}:fixture",
            effective_at_ref=f"effective_at:{dataset_id}:fixture",
            pit_bitemporal_rules_ref=f"pit:{dataset_id}:fixture",
            quality_status="accepted",
            lineage_refs=(f"lineage:{dataset_id}:fixture",),
            freshness_status="fresh",
            checksum=f"sha256:{dataset_id}:fixture",
            asof_join_rule_ref=f"pit:{dataset_id}:fixture",
        ),
        use_context=ValidationUseContext.CONFIRMATORY_VALIDATION,
    )
    registry.record_instrument(
        InstrumentSpec(
            instrument_ref=instrument_ref,
            asset_class=asset_class,
            instrument_type="spot" if asset_class == "crypto" else "equity",
            currency=currency,
            exchange_calendar_ref=f"calendar:{dataset_id}:fixture",
            symbol_mapping_ref=f"symbols:{dataset_id}:fixture",
        )
    )
    registry.record_capability_matrix(
        MarketCapabilityMatrixRecord(
            matrix_ref=capability_ref,
            asset_class=asset_class,
            instrument_type="spot" if asset_class == "crypto" else "equity",
            research=True,
            backtest=True,
            paper=True,
            testnet=False,
            live=False,
            long=True,
            short=False,
            leverage=False,
            options=False,
            margin=False,
            borrow=False,
            data_availability="fixture_pit_bitemporal",
            cost_model_availability="fixture_cost_model",
            execution_availability="paper_only",
            permission_requirement=None,
        ),
        use_context=ValidationUseContext.CONFIRMATORY_VALIDATION,
    )
    registry.record_use_validation(
        MarketDataUseValidationRecord(
            validation_ref=validation_ref,
            request_ref=f"training:{dataset_id}:fixture",
            use_context=ValidationUseContext.CONFIRMATORY_VALIDATION.value,
            dataset_refs=(dataset_ref,),
            instrument_refs=(instrument_ref,),
            capability_matrix_ref=capability_ref,
            capital_record_ref=None,
            transformation_refs=(f"transform:{dataset_id}:features",),
            accepted=True,
            violation_codes=(),
            evidence_refs=(
                f"pit:{dataset_id}:fixture",
                f"known_at:{dataset_id}:fixture",
                f"effective_at:{dataset_id}:fixture",
            ),
            recorded_by="pytest",
            created_at_utc="2026-06-27T00:00:00+00:00",
        )
    )
    return validation_ref


@pytest.fixture
def training_market_data_use_validation_ref(monkeypatch, tmp_path) -> str:
    return install_training_market_data_use_validation(monkeypatch, tmp_path)


@pytest.fixture
def training_market_data_use_validation_refs(monkeypatch, tmp_path) -> dict[str, str]:
    ashare_ref = install_training_market_data_use_validation(monkeypatch, tmp_path)
    crypto_ref = add_training_market_data_use_validation(dataset_id="demo_crypto_ts")
    return {
        "demo_ashare_xsec": ashare_ref,
        "demo_crypto_ts": crypto_ref,
    }


@pytest.fixture(autouse=True)
def _registered_rdp_runtime_refs(request, monkeypatch):
    """Give RDP API tests recorded upstream refs without touching unrelated modules."""
    test_path = Path(str(getattr(request.node, "fspath", "")))
    if not test_path.name.startswith("test_research_os_rdp"):
        return

    from app import main

    artifact = SimpleNamespace(
        artifact_ref="compiler_artifact:strategy:001",
        mathematical_spine_chain_refs=("math_spine_chain:btc_momentum:v1",),
    )
    chain = SimpleNamespace(chain_ref="math_spine_chain:btc_momentum:v1")
    coverage = SimpleNamespace(
        coverage_ref="goal_entrypoint_coverage:strategy:001",
        lifecycle_refs=("compiler_artifact:strategy:001", "math_spine_chain:btc_momentum:v1"),
    )
    market_data_use = SimpleNamespace(
        validation_ref="market_data_use:BTCUSDT_1d:backtest",
        accepted=True,
        violation_codes=(),
        use_context="backtest",
        dataset_refs=("dataset:BTCUSDT_1d",),
    )
    dataset = SimpleNamespace(
        dataset_ref="dataset:BTCUSDT_1d",
        known_at_ref="known_at:BTCUSDT_1d:fixture",
        effective_at_ref="effective_at:BTCUSDT_1d:fixture",
        pit_bitemporal_rules_ref="pit:BTCUSDT_1d:fixture",
    )

    monkeypatch.setattr(
        main,
        "COMPILER_IR_STORE",
        SimpleNamespace(artifact=lambda ref: {"compiler_artifact:strategy:001": artifact}[ref]),
    )
    monkeypatch.setattr(
        main,
        "MATHEMATICAL_SPINE_CHAIN_REGISTRY",
        SimpleNamespace(chain=lambda ref: {"math_spine_chain:btc_momentum:v1": chain}[ref]),
    )
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        SimpleNamespace(coverage=lambda ref: {"goal_entrypoint_coverage:strategy:001": coverage}[ref]),
    )
    monkeypatch.setattr(
        main,
        "MARKET_DATA_REGISTRY",
        SimpleNamespace(
            use_validation=lambda ref: {"market_data_use:BTCUSDT_1d:backtest": market_data_use}[ref],
            dataset=lambda ref: {"dataset:BTCUSDT_1d": dataset}[ref],
        ),
    )


def pytest_collection_modifyitems(config, items):
    """默认 skip @pytest.mark.testnet（真打 Binance）；唯有显式 `-m testnet` 才跑。

    v0.9.10 引入 testnet e2e 后，CI/release_check 跑 pytest 不应该触发真发单
    （网络偶发 -2021 / -4183 让 release check flaky）。
    """
    marker_filter = config.getoption("-m", default="") or ""
    if "testnet" in marker_filter:
        return
    skip_testnet = pytest.mark.skip(reason="testnet 真发单测试默认 skip; 跑 pytest -m testnet 触发")
    for item in items:
        if "testnet" in item.keywords:
            item.add_marker(skip_testnet)
