"""Make `from app.<module>` work when pytest runs from repo root.

附加：自动隔离 SENTRY_DSN，避免开发机配过的 DSN 让每次跑 pytest 时
sentry-sdk 在结束阶段去发 2 个 pending events、阻塞退出 ~2 秒。
真实想测 sentry 集成的 case 自己 setenv 即可。
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Pytest imports application modules during collection, before fixtures run.
# Set the runtime root here so module-level registries never bind to the shared
# repository data/audit directory.  Copy only the small, checked-in read-only
# fixtures required by integration tests; runtime/audit history is never seeded.
PYTEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="quantbt-pytest-data-")).resolve()
os.environ["BACKTEST_DATA_ROOT"] = str(PYTEST_DATA_ROOT)
os.environ["QUANTBT_KEYSTORE_BACKEND"] = "memory"
os.environ["QUANTBT_RUNTIME_MODE"] = "test"
os.environ["QUANTBT_SECRETS_PATH"] = str(PYTEST_DATA_ROOT / "absent-secrets.yaml")


def _audit_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        payload = path.read_bytes()
        snapshot[str(path.relative_to(root))] = (
            len(payload),
            payload.count(b"\n"),
            hashlib.sha256(payload).hexdigest(),
        )
    return snapshot


SHARED_AUDIT_ROOT = PROJECT_ROOT / "data" / "audit"
SHARED_AUDIT_BASELINE = _audit_snapshot(SHARED_AUDIT_ROOT)


def _seed_read_only_fixture(relative_path: str) -> None:
    source = PROJECT_ROOT / relative_path
    if not source.exists():
        return
    destination = PYTEST_DATA_ROOT / relative_path.removeprefix("data/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)


for _fixture_path in (
    "data/_symbol_pools/example_stocks_cn.json",
    "data/samples",
    "data/artifacts/experiments/a_share_ml_demo",
    "data/artifacts/experiments/a_share_real_demo",
    "data/artifacts/experiments/crypto_perp_demo",
    "data/artifacts/experiments/demo",
    "data/artifacts/experiments/quant1-demo",
):
    _seed_read_only_fixture(_fixture_path)

atexit.register(shutil.rmtree, PYTEST_DATA_ROOT, ignore_errors=True)

# 默认 unset SENTRY_DSN —— 单测不该真发数据到 Sentry
os.environ.pop("SENTRY_DSN", None)


def build_test_agent_gateway(client, *, seal_secret: bytes):
    """Build an offline real LLMGateway around a scripted test client."""

    from app.llm import (
        LLMCredentialPool,
        LLMGateway,
        LLMModelProfile,
        ModelRoutingPolicy,
        ModelTier,
        RoutingMode,
        SecretRef,
    )
    from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore

    profile = LLMModelProfile(
        provider="test-provider",
        model="test-model",
        capability_tier=ModelTier.STRONG.value,
        pool_id="test-pool",
    )
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(
        KeystoreRecord(
            name="test-pool",
            api_key="test-key-offline-xxxxxxxx",
            api_secret="test-key-offline-xxxxxxxx",
        )
    )
    pool = LLMCredentialPool(keystore)
    pool.register(
        "test-pool",
        SecretRef(
            keystore_name="test-pool",
            provider=profile.provider,
            auth_kind="api_key",
        ),
        default_model=profile.model,
    )
    return LLMGateway(
        policy=ModelRoutingPolicy([profile], mode=RoutingMode.HYBRID_ADAPTIVE),
        credential_pool=pool,
        client_factory=lambda _credential: client,
        strict_degrade=False,
        seal_secret=seal_secret,
    )


def build_verified_spine_chain(tmp_path: Path, candidate):
    """Mint a real canonical Spine package and its strictly verified chain."""

    from dataclasses import replace

    from app.lineage import content_hash
    from app.lineage.spine import (
        CHECK_PASS,
        PROOF_BACKED,
        ConsistencyCheck,
        ImplementationSpec,
        MathematicalArtifact,
        MethodologyChoiceRecord,
        ResponsibilityDisclosureRecord,
        TheoryImplementationBinding,
        TheorySpec,
    )
    from app.lineage.spine_ledger import SpineLedger
    from app.research_os import PersistentMathematicalSpineChainRegistry

    owner = str(candidate.recorded_by)
    stage_fields = (
        "data_semantics_ref",
        "factor_ref",
        "model_ref",
        "forecast_ref",
        "signal_contract_ref",
        "strategy_book_ref",
        "portfolio_policy_ref",
        "risk_policy_ref",
        "execution_policy_ref",
        "backtest_run_ref",
        "attribution_ref",
        "monitor_ref",
    )
    stage_refs = tuple(str(getattr(candidate, field)) for field in stage_fields)
    ledger = SpineLedger(tmp_path / "canonical_spine")
    current_hashes: dict[tuple[str, str], str] = {}

    def add_binding(kind: str, used_by: tuple[str, ...]):
        artifact = MathematicalArtifact(
            artifact_type=kind,
            statement=f"{kind} statement",
            definition=f"{kind} definition",
            derivation=f"{kind} derivation",
            assumptions=("PIT inputs",),
            applicability="test contract",
            failure_conditions=("stale implementation",),
            proof_status=PROOF_BACKED,
            used_by=used_by,
        )
        ledger.record_artifact(artifact, owner=owner)
        theory = TheorySpec(
            mathematical_requirement_ref=f"requirement:{kind}",
            artifact_ref=artifact.artifact_id,
            definitions=(artifact.definition,),
            assumptions=artifact.assumptions,
            derivation=artifact.derivation,
            applicability=artifact.applicability,
            failure_conditions=artifact.failure_conditions,
            proof_status=PROOF_BACKED,
            used_by=used_by,
        )
        ledger.record_theory_spec(theory, owner=owner)
        refs = {
            "code": f"code:{kind}",
            "config": f"config:{kind}",
            "data_contract": f"data:{kind}",
        }
        hashes = {name: content_hash(ref) for name, ref in refs.items()}
        current_hashes.update({(name, refs[name]): value for name, value in hashes.items()})
        implementation = ImplementationSpec(
            theory_ref=theory.theory_spec_id,
            code_ref=refs["code"],
            config_ref=refs["config"],
            data_contract_ref=refs["data_contract"],
            code_content_hash=hashes["code"],
            config_content_hash=hashes["config"],
            data_contract_content_hash=hashes["data_contract"],
            test_refs=(f"test:{kind}",),
            simulation_refs=(f"simulation:{kind}",),
            numerical_check_refs=(f"numerical:{kind}",),
        )
        ledger.record_implementation_spec(implementation, owner=owner)
        binding = TheoryImplementationBinding(
            theory_ref=theory.theory_spec_id,
            implementation_ref=implementation.implementation_spec_id,
            implementation_spec=implementation.implementation_spec_id,
            code_ref=implementation.code_ref,
            code_content_hash=implementation.code_content_hash,
            config_ref=implementation.config_ref,
            config_content_hash=implementation.config_content_hash,
            data_contract_ref=implementation.data_contract_ref,
            data_contract_content_hash=implementation.data_contract_content_hash,
            test_refs=implementation.test_refs,
            simulation_refs=implementation.simulation_refs,
            numerical_check_refs=implementation.numerical_check_refs,
            consistency_verdict=CHECK_PASS,
            verifier_ref=f"verifier:{kind}",
            used_by=used_by,
        )
        ledger.record_binding(binding, owner=owner)
        check = ConsistencyCheck(
            binding_id=binding.binding_id,
            check_type="numerical",
            result=CHECK_PASS,
            input_refs=(f"input:{kind}",),
            expected_property="expected",
            observed_property="expected",
            verifier_ref=f"verifier:{kind}",
        )
        ledger.record_check(check, owner=owner)
        return binding, check

    stage_artifacts = (
        ("data_timing", (str(candidate.data_semantics_ref),)),
        ("factor_formula", (str(candidate.factor_ref),)),
        ("loss_function", (str(candidate.model_ref),)),
        (
            "estimator",
            (str(candidate.forecast_ref), str(candidate.backtest_run_ref)),
        ),
        ("signal_transform", (str(candidate.signal_contract_ref),)),
        ("payoff_definition", (str(candidate.strategy_book_ref),)),
        ("portfolio_objective", (str(candidate.portfolio_policy_ref),)),
        ("risk_measure", (str(candidate.risk_policy_ref),)),
        ("execution_cost", (str(candidate.execution_policy_ref),)),
        ("attribution_decomposition", (str(candidate.attribution_ref),)),
        ("monitor_trigger", (str(candidate.monitor_ref),)),
    )
    binding_checks = tuple(
        add_binding(kind, used_by) for kind, used_by in stage_artifacts
    )
    choice = MethodologyChoiceRecord(
        chosen_path="strict",
        asset_ref=str(candidate.strategy_book_ref),
        available_options=("strict", "standard"),
        recommendation="strict",
        tradeoffs_shown=("more validation",),
        risks_shown=("residual model risk",),
        responsibility_boundary="test user chooses methodology",
        actor=owner,
        allowed_environment="paper",
    )
    ledger.record_choice(choice, owner=owner)
    responsibility = ResponsibilityDisclosureRecord(
        asset_ref=choice.asset_ref,
        responsibility_boundary=choice.responsibility_boundary,
        risks_disclosed=choice.risks_shown,
        risk_owner=owner,
        actor=owner,
        allowed_environment="paper",
        methodology_choice_ref=choice.choice_id,
    )
    ledger.record_responsibility(responsibility, owner=owner)
    strict_candidate = replace(
        candidate,
        theory_binding_refs=tuple(binding.binding_id for binding, _check in binding_checks),
        consistency_check_refs=tuple(check.check_id for _binding, check in binding_checks),
        methodology_choice_ref=choice.choice_id,
        responsibility_boundary_ref=responsibility.disclosure_id,
    )
    registry = PersistentMathematicalSpineChainRegistry(
        tmp_path / "mathematical_spine_chains.jsonl",
        ledger,
        external_ref_resolver=lambda _role, _ref, seen_owner: seen_owner == owner,
        current_hash_resolver=lambda kind, ref, seen_owner: (
            current_hashes.get((kind, ref)) if seen_owner == owner else None
        ),
    )
    chain = registry.record_chain(strict_candidate)
    return registry, chain, ledger


@pytest.fixture(scope="session", autouse=True)
def _shared_audit_must_remain_unchanged():
    """Fail the test run if any test touches the developer's shared audit history."""

    yield
    current = _audit_snapshot(SHARED_AUDIT_ROOT)
    assert current == SHARED_AUDIT_BASELINE, (
        "pytest modified PROJECT_ROOT/data/audit; all runtime writes must stay under "
        f"the isolated BACKTEST_DATA_ROOT={PYTEST_DATA_ROOT}"
    )


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
        owner_user_id="pytest",
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
        ),
        owner_user_id="pytest",
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
        owner_user_id="pytest",
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
        ),
        owner_user_id="pytest",
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
        owner_user_id="pytest",
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
        ),
        owner_user_id="pytest",
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
        owner_user_id="pytest",
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
        ),
        owner_user_id="pytest",
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
        source_ir_refs=("compiler_ir:strategy:001",),
        compiler_pass_refs=("compiler_pass:strategy:001",),
        owner="u1",
    )
    ir = SimpleNamespace(
        theory_binding_refs=("tbind:momentum",),
        consistency_check_refs=("ccheck:momentum",),
        mathematical_spine_chain_refs=("math_spine_chain:btc_momentum:v1",),
        owner="u1",
    )
    compiler_pass = SimpleNamespace(actor="u1")
    closure = SimpleNamespace(
        mathematical_refs=("math:momentum",),
        theory_binding_refs=("tbind:momentum",),
        consistency_check_refs=("ccheck:momentum",),
        methodology_choice_refs=("mchoice:standard",),
        responsibility_refs=("resp:standard",),
    )
    coverage = SimpleNamespace(
        coverage_ref="goal_entrypoint_coverage:strategy:001",
        lifecycle_refs=("compiler_artifact:strategy:001", "math_spine_chain:btc_momentum:v1"),
        recorded_by="u1",
        claims_full_product_entrypoint=False,
    )
    market_data_use = SimpleNamespace(
        validation_ref="market_data_use:BTCUSDT_1d:backtest",
        accepted=True,
        violation_codes=(),
        use_context="backtest",
        dataset_refs=("dataset:BTCUSDT_1d",),
        recorded_by="u1",
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
        SimpleNamespace(
            canonical_artifact=lambda ref, *, owner: {
                ("u1", "compiler_artifact:strategy:001"): artifact
            }[(owner, ref)],
            canonical_ir=lambda ref, *, owner: {
                ("u1", "compiler_ir:strategy:001"): ir
            }[(owner, ref)],
            canonical_compiler_pass=lambda ref, *, owner: {
                ("u1", "compiler_pass:strategy:001"): compiler_pass
            }[(owner, ref)],
            is_canonical_current=lambda record, *, owner: owner == "u1"
            and record in (artifact, ir, compiler_pass),
            artifact=lambda ref, *, owner: {
                ("u1", "compiler_artifact:strategy:001"): artifact
            }[(owner, ref)],
            ir=lambda ref, *, owner: {
                ("u1", "compiler_ir:strategy:001"): ir
            }[(owner, ref)],
            compiler_pass=lambda ref, *, owner: {
                ("u1", "compiler_pass:strategy:001"): compiler_pass
            }[(owner, ref)],
        ),
    )
    monkeypatch.setattr(
        main,
        "MATHEMATICAL_SPINE_CHAIN_REGISTRY",
        SimpleNamespace(
            verified_chain_record_refs=lambda ref, owner: {
                ("math_spine_chain:btc_momentum:v1", "u1"): closure
            }[(ref, owner)],
        ),
    )
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        SimpleNamespace(
            refresh=lambda: None,
            canonical_coverage=lambda ref, *, owner: {
                ("u1", "goal_entrypoint_coverage:strategy:001"): coverage
            }[(owner, ref)],
            coverage=lambda ref, *, owner: {
                ("u1", "goal_entrypoint_coverage:strategy:001"): coverage
            }[(owner, ref)],
            validate_real_backing=lambda record: SimpleNamespace(
                accepted=record is coverage,
                violations=(),
            ),
        ),
    )
    monkeypatch.setattr(
        main,
        "MARKET_DATA_REGISTRY",
        SimpleNamespace(
            use_validation=lambda ref, *, owner_user_id: {
                ("u1", "market_data_use:BTCUSDT_1d:backtest"): market_data_use
            }[(owner_user_id, ref)],
            dataset=lambda ref, *, owner_user_id: {
                ("u1", "dataset:BTCUSDT_1d"): dataset
            }[(owner_user_id, ref)],
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
