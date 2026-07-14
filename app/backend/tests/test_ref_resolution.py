"""Adversarial tests for the generalized real-reference resolver (card SA-1).

``ref_resolution.resolve_typed_ref`` is the single fail-closed gate that decides
whether a *typed* coverage ref is backed by a real object in a real backend
store. These tests seed known-"bad" refs (unresolvable, placeholder /
goal-closure, wrong type, store error) and prove the gate rejects them, plus
that a genuinely-minted ref is accepted.

Teeth split honestly:
* the math_spine cases run end-to-end against a REAL
  ``PersistentMathematicalSpineChainRegistry`` + ``RealRefResolver``;
* the generalized dispatch / fail-closed matrix runs against an in-memory
  ``RefResolver`` double that exercises the composition logic (ref-type ->
  getter, unknown type, missing method, raising store) independent of any one
  backend's shape. The six per-store getters themselves are adversarially
  covered end-to-end in ``test_platform_coverage.py``.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent.llm_providers import ensure_settings_managed_llm_provider
from app.llm.call_record import (
    CallRecordKind,
    CallStatus,
    LLMCallRecord,
    ReplayState,
    make_call_id,
    seal_record,
)
from app.llm.call_record_store import LLMCallRecordStore
from app.research_os import (
    AssetCategory,
    ConsistencyStatus,
    DataSourceAssetRecord,
    DatasetSemanticsRecord,
    GoalEntrypointCoverageRecord,
    GoalValidationOutcome,
    GoalValidationReceipt,
    GovernedAssetRecord,
    IngestionLifecycleState,
    IngestionSkillRecord,
    IngestionSkillUpdateRecord,
    InstrumentSpec,
    LifecycleState,
    MathematicalSpineChainRecord,
    MarketCapabilityMatrixRecord,
    MarketDataUseValidationRecord,
    PersistentAssetLifecycleRegistry,
    PersistentMarketDataRegistry,
    PersistentMathematicalSpineChainRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentOnboardingRegistry,
    RuntimeStatus,
    goal_entrypoint_coverage_identity,
    validate_goal_entrypoint_real_backing,
)
from app.lineage.ids import content_hash
from app.research_os.ref_resolution import (
    PLACEHOLDER_TOKENS,
    REF_TYPE_RESOLVER_METHODS,
    build_real_ref_resolver,
    is_placeholder_ref,
    resolve_typed_ref,
)
from app.security.gate.account_halt import PersistentAccountHaltBarrier
from conftest import build_verified_spine_chain


class _DictResolver:
    """A ``RefResolver`` whose six getters answer from in-memory sets of "minted"
    ids. Drives the generalized dispatch + fail-closed matrix; it is a
    composition-logic double, not a stand-in for real-store resolution (covered
    against real stores below and in ``test_platform_coverage.py``)."""

    def __init__(self, **backed: set[str]) -> None:
        self._backed = {ref_type: set(ids) for ref_type, ids in backed.items()}

    def _has(self, ref_type: str, ref: str) -> bool:
        return ref in self._backed.get(ref_type, set())

    def has_qro(self, ref: str) -> bool:
        return self._has("qro", ref)

    def has_research_graph_command(self, ref: str) -> bool:
        return self._has("research_graph", ref)

    def has_lifecycle_record(self, ref: str) -> bool:
        return self._has("lifecycle", ref)

    def has_governance_record(self, ref: str) -> bool:
        return self._has("governance", ref)

    def has_rag_asset(self, ref: str) -> bool:
        return self._has("rag", ref)

    def has_math_spine_chain(self, ref: str) -> bool:
        return self._has("math_spine", ref)

    def has_compiler_ir(self, ref: str) -> bool:
        return self._has("compiler_ir", ref)

    def has_compiler_pass(self, ref: str) -> bool:
        return self._has("compiler_pass", ref)

    def has_evidence(self, ref: str) -> bool:
        return self._has("evidence", ref)

    def has_rdp(self, ref: str) -> bool:
        return self._has("rdp", ref)


class _RaisingResolver:
    """Every getter raises -- proves ``resolve_typed_ref`` fails closed on error
    instead of letting the exception (or a default-accept) leak through."""

    def has_qro(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_research_graph_command(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_lifecycle_record(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_governance_record(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_rag_asset(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_math_spine_chain(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_compiler_ir(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_compiler_pass(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_evidence(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_rdp(self, ref: str) -> bool:
        raise RuntimeError("store down")


def _mk_chain(**overrides) -> MathematicalSpineChainRecord:
    data = {
        "chain_ref": "math_spine_chain:ref_resolution_real:v1",
        "data_semantics_ref": "dataset_semantics:btc_1d",
        "factor_ref": "factor:momentum_20d",
        "model_ref": "model:momentum_classifier:v1",
        "forecast_ref": "forecast:btc_momentum:v1",
        "signal_contract_ref": "signal_contract:btc_momentum:v1",
        "strategy_book_ref": "strategy_book:btc_momentum:v1",
        "portfolio_policy_ref": "portfolio_policy:btc_momentum:v1",
        "risk_policy_ref": "risk_policy:btc_momentum:v1",
        "execution_policy_ref": "execution_policy:paper_btc:v1",
        "backtest_run_ref": "backtest_run:bt1",
        "attribution_ref": "attribution:bt1",
        "monitor_ref": "monitor:weekly_btc_momentum",
        "theory_binding_refs": ("tbind:momentum", "tbind:portfolio-risk"),
        "consistency_check_refs": ("ccheck:momentum", "ccheck:risk"),
        "methodology_choice_ref": "mchoice:standard",
        "responsibility_boundary_ref": "resp:standard",
        "evidence_refs": ("evidence:bt1", "evidence:monitor"),
        "validation_refs": ("pytest:test_ref_resolution",),
        "consistency_verdict": ConsistencyStatus.ACCEPTED,
        "target_runtime": RuntimeStatus.PAPER,
        "recorded_by": "u1",
    }
    data.update(overrides)
    return MathematicalSpineChainRecord(**data)


def _real_spine_backing(tmp_path):
    """Real spine store + a real resolver over it (other stores unused here)."""

    spine, _chain, _ledger = build_verified_spine_chain(tmp_path, _mk_chain())
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=spine,
    )
    return spine, resolver


# ---------------------------------------------------------------------------
# Real-store teeth (RealRefResolver end-to-end on the math_spine type)
# ---------------------------------------------------------------------------


def test_real_minted_chain_resolves_as_backed(tmp_path):
    # Positive control: a genuinely-minted chain id resolves to a real object.
    spine, resolver = _real_spine_backing(tmp_path)
    resolver = resolver.for_owner("u1")
    chain = spine.chains()[0]
    assert resolver.has_math_spine_chain(chain.chain_ref) is True
    assert resolve_typed_ref(resolver, "math_spine", chain.chain_ref) is True


def test_unresolvable_ref_is_not_backed_mutation_guard(tmp_path):
    # MUTATION TARGET (accept-without-resolving): a real-shaped id that was never
    # minted must resolve to nothing. Weaken resolve_typed_ref to return True
    # without actually calling the store getter and this assertion turns RED;
    # restore it and the assertion is GREEN. Run against the real resolver.
    spine, resolver = _real_spine_backing(tmp_path)
    assert spine.chains()  # store is non-empty, but not the probed id
    assert resolver.has_math_spine_chain("math_spine_chain:never_minted:v1") is False
    assert resolve_typed_ref(resolver, "math_spine", "math_spine_chain:never_minted:v1") is False


def test_lifecycle_resolver_fails_closed_on_corrupt_or_deleted_history(tmp_path):
    path = tmp_path / "asset_lifecycle.jsonl"
    registry = PersistentAssetLifecycleRegistry(path)
    record = IngestionSkillUpdateRecord(
        update_ref="ingestion:update:resolver",
        skill_ref="skill:rest",
        skill_version="v1",
        source_ref="datasource:rest",
        secret_ref="secretref:rest:read",
        dataset_version_ref="dataset:resolver",
        checksum="sha256:resolver",
        lineage_ref="lineage:resolver",
        quality_verdict_ref="quality:pass",
        known_at_ref="known_at:resolver",
        effective_at_ref="effective_at:resolver",
        recorded_by="u1",
    )
    registry.record_ingestion_skill_update(record, owner_user_id="u1")
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=registry,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        owner="u1",
    )
    assert resolver.has_lifecycle_record(record.update_ref) is True

    original = path.read_text(encoding="utf-8")
    path.write_text(original + "corrupt\n", encoding="utf-8")
    assert resolver.has_lifecycle_record(record.update_ref) is False
    assert resolve_typed_ref(resolver, "lifecycle", record.update_ref) is False

    path.write_text(original, encoding="utf-8")
    path.unlink()
    # Direct construction must fail closed because the durable history marker
    # survives the deleted journal.  The already-bound resolver must also deny.
    with pytest.raises(ValueError, match="history is missing"):
        PersistentAssetLifecycleRegistry(path)
    assert resolver.has_lifecycle_record(record.update_ref) is False


def test_lifecycle_resolver_accepts_one_exact_owner_loader_and_rejects_recombination():
    ref = "desk_topology_receipt:current"

    def exact_loader(candidate: str, owner: str):
        if candidate != ref:
            raise KeyError(candidate)
        return SimpleNamespace(owner_user_id=owner, receipt_ref=candidate)

    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        lifecycle_loaders=(exact_loader,),
    ).for_owner("u1")
    assert resolver.has_lifecycle_record(ref) is True
    assert resolver.has_lifecycle_record("desk_topology_receipt:missing") is False

    def wrong_owner_loader(candidate: str, owner: str):
        del owner
        if candidate != ref:
            raise KeyError(candidate)
        return SimpleNamespace(owner_user_id="u2", receipt_ref=candidate)

    wrong_owner = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        lifecycle_loaders=(wrong_owner_loader,),
        owner="u1",
    )
    assert wrong_owner.has_lifecycle_record(ref) is False

    ambiguous = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        lifecycle_loaders=(exact_loader, exact_loader),
        owner="u1",
    )
    assert ambiguous.has_lifecycle_record(ref) is False


def test_market_data_instrument_resolution_is_owner_scoped_and_accepts_live_ref(tmp_path):
    registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    shared_ref = "instrument:BTCUSDT_PERP"
    registry.record_instrument(
        InstrumentSpec(
            instrument_ref=shared_ref,
            asset_class="crypto_perp",
            instrument_type="perpetual",
            currency="USDT",
            exchange_calendar_ref="calendar:crypto_24_7",
            margin_ref="margin:usdt_perp",
            venue_symbol="BTCUSDT",
        ),
        owner_user_id="u1",
    )
    registry.record_instrument(
        InstrumentSpec(
            instrument_ref=shared_ref,
            asset_class="crypto_perp",
            instrument_type="perpetual",
            currency="USD",
            exchange_calendar_ref="calendar:crypto_24_7",
            margin_ref="margin:usd_perp",
            venue_symbol="BTCUSD_PERP",
        ),
        owner_user_id="u2",
    )
    u1_only_ref = "instrument:ETHUSDT_PERP"
    registry.record_instrument(
        InstrumentSpec(
            instrument_ref=u1_only_ref,
            asset_class="crypto_perp",
            instrument_type="perpetual",
            currency="USDT",
            exchange_calendar_ref="calendar:crypto_24_7",
            margin_ref="margin:usdt_perp",
            venue_symbol="ETHUSDT",
        ),
        owner_user_id="u1",
    )
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        market_data_registry=registry,
    )
    row = SimpleNamespace(m_row="M3")

    assert resolver.for_owner("u1").has_platform_specific_ref(
        "instrument_spec_ref", shared_ref, row
    )
    assert resolver.for_owner("u2").has_platform_specific_ref(
        "instrument_spec_ref", shared_ref, row
    )
    assert registry.instrument(shared_ref, owner_user_id="u1").currency == "USDT"
    assert registry.instrument(shared_ref, owner_user_id="u2").currency == "USD"
    assert resolver.for_owner("u1").has_platform_specific_ref(
        "instrument_spec_ref", u1_only_ref, row
    )
    assert not resolver.for_owner("u2").has_platform_specific_ref(
        "instrument_spec_ref", u1_only_ref, row
    )
    assert not resolver.has_platform_specific_ref(
        "instrument_spec_ref", shared_ref, row
    )


def test_market_capability_matrix_resolution_is_owner_scoped_and_accepts_live_ref(tmp_path):
    registry = PersistentMarketDataRegistry(tmp_path / "market_data.jsonl")
    shared_ref = "capability:crypto_spot"
    base = {
        "matrix_ref": shared_ref,
        "asset_class": "crypto",
        "instrument_type": "spot",
        "research": True,
        "backtest": True,
        "paper": True,
        "testnet": False,
        "live": False,
        "long": True,
        "short": False,
        "leverage": False,
        "options": False,
        "margin": False,
        "borrow": False,
        "data_availability": "available",
        "cost_model_availability": "available",
        "execution_availability": "paper_only",
        "permission_requirement": "market_data:read",
    }
    registry.record_capability_matrix(
        MarketCapabilityMatrixRecord(**base),
        owner_user_id="u1",
    )
    registry.record_capability_matrix(
        MarketCapabilityMatrixRecord(**{**base, "permission_requirement": "market_data:admin"}),
        owner_user_id="u2",
    )
    u1_only_ref = "capability:crypto_perpetual"
    registry.record_capability_matrix(
        MarketCapabilityMatrixRecord(
            **{
                **base,
                "matrix_ref": u1_only_ref,
                "instrument_type": "perpetual",
                "short": True,
                "leverage": True,
                "margin": True,
            }
        ),
        owner_user_id="u1",
    )
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        market_data_registry=registry,
    )
    row = SimpleNamespace(m_row="M9")

    assert resolver.for_owner("u1").has_platform_specific_ref(
        "market_capability_matrix_ref", shared_ref, row
    )
    assert resolver.for_owner("u2").has_platform_specific_ref(
        "market_capability_matrix_ref", shared_ref, row
    )
    assert (
        registry.capability_matrix(shared_ref, owner_user_id="u1").permission_requirement
        == "market_data:read"
    )
    assert (
        registry.capability_matrix(shared_ref, owner_user_id="u2").permission_requirement
        == "market_data:admin"
    )
    assert resolver.for_owner("u1").has_platform_specific_ref(
        "market_capability_matrix_ref", u1_only_ref, row
    )
    assert not resolver.for_owner("u2").has_platform_specific_ref(
        "market_capability_matrix_ref", u1_only_ref, row
    )
    assert not resolver.for_owner("u1").has_platform_specific_ref(
        "market_capability_matrix_ref", "capability:missing", row
    )
    assert not resolver.has_platform_specific_ref(
        "market_capability_matrix_ref", shared_ref, row
    )


def test_onboarding_ingestion_skill_resolution_is_owner_scoped_and_accepts_live_ref(tmp_path):
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    source = DataSourceAssetRecord(
        source_ref="datasource:public-bars",
        license="public-domain",
        redistribution_rights="allowed",
        rate_limit="unlimited",
        tos_constraints="none",
        commercial_use_status="allowed",
        retention_policy="retain:research-cache",
        source_owner="public",
        source_url_or_path="https://example.invalid/public-bars.csv",
    )
    skill = IngestionSkillRecord(
        skill_id="ingestion_skill:public-bars:v1",
        source_type="public_csv",
        source_ref=source.source_ref,
        connector_config={"connector_name": "public-bars", "auth_mode": "none"},
        schema_mapping_ref="schema_map:public-bars:v1",
        secret_refs=(),
        refresh_mode="manual",
        data_quality_tests=("not_null:ts", "not_null:close"),
        pit_bitemporal_rules_ref="pit:public-bars:v1",
        output_dataset_id="dataset:public-bars:v1",
        owner="u1",
        version="v1",
        lifecycle_state=IngestionLifecycleState.ACTIVE,
        freshness_status="fresh",
        permission_scope="market_data:read",
        dependency_lock_ref="deps:public-bars:v1",
        schedule_owner="u1",
        rollback_plan_ref="rollback:public-bars:v1",
    )
    registry.record_data_source_asset(source, owner_user_id="u1")
    registry.record_ingestion_skill(skill, owner_user_id="u1")
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        onboarding_registry=registry,
    )
    row = SimpleNamespace(m_row="M3")

    assert resolver.for_owner("u1").has_platform_specific_ref(
        "ingestion_skill_ref", skill.skill_id, row
    )
    assert not resolver.for_owner("u2").has_platform_specific_ref(
        "ingestion_skill_ref", skill.skill_id, row
    )
    assert not resolver.for_owner("u1").has_platform_specific_ref(
        "ingestion_skill_ref", "ingestion_skill:missing:v1", row
    )


def test_m21_refs_resolve_only_from_owner_scoped_governed_example_asset(tmp_path):
    registry = PersistentAssetLifecycleRegistry(tmp_path / "asset_lifecycle.jsonl")
    record = GovernedAssetRecord(
        asset_ref="template:btc_momentum_v1",
        asset_type="StrategyTemplate",
        category=AssetCategory.TEMPLATE,
        lifecycle_state=LifecycleState.SPECIFIED,
        evidence_refs=("source:datasets.templates:btc_momentum_v1",),
        validation_plan_ref="validation:template_contract:btc_momentum_v1",
        promotion_history=(),
        display_label="MOCK · TEMPLATE · crypto_perp",
        mock_label_ref="mock_label:template:btc_momentum_v1",
        asset_category_ref="asset_category:crypto_perp:btc_momentum_v1",
    )
    registry.record_governed_asset(record, owner_user_id="u1")
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=registry,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
    )
    row = SimpleNamespace(
        m_row="M21",
        specific_refs=(
            SimpleNamespace(key="mock_label_ref", ref=record.mock_label_ref),
            SimpleNamespace(key="asset_category_ref", ref=record.asset_category_ref),
        ),
    )

    for key, ref in (
        ("mock_label_ref", record.mock_label_ref),
        ("asset_category_ref", record.asset_category_ref),
    ):
        assert resolver.for_owner("u1").has_platform_specific_ref(key, str(ref), row)
        assert not resolver.for_owner("u2").has_platform_specific_ref(key, str(ref), row)
        assert not resolver.for_owner("u1").has_platform_specific_ref(
            key, str(ref) + ":missing", row
        )

    other = replace(
        record,
        asset_ref="template:other",
        mock_label_ref="mock_label:template:other",
        asset_category_ref="asset_category:crypto_perp:other",
    )
    registry.record_governed_asset(other, owner_user_id="u1")
    mixed = SimpleNamespace(
        m_row="M21",
        specific_refs=(
            SimpleNamespace(key="mock_label_ref", ref=record.mock_label_ref),
            SimpleNamespace(key="asset_category_ref", ref=other.asset_category_ref),
        ),
    )
    assert not resolver.for_owner("u1").has_platform_specific_ref(
        "mock_label_ref",
        str(record.mock_label_ref),
        mixed,
    )
    assert not resolver.for_owner("u1").has_platform_specific_ref(
        "asset_category_ref",
        str(other.asset_category_ref),
        mixed,
    )


def test_machine_llm_settings_refs_resolve_only_from_service_owner(tmp_path):
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    service_owner = "service:test-llm-gateway"
    refs = ensure_settings_managed_llm_provider(
        registry=registry,
        provider="openai",
        model="gpt-5.5",
        owner=service_owner,
        created_at="2026-07-12T00:00:00Z",
    )
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        onboarding_registry=registry,
        llm_service_owner_user_id=service_owner,
    ).for_owner("u1")
    row = SimpleNamespace(m_row="M14")

    assert resolver.has_platform_specific_ref(
        "model_routing_policy_ref", refs["routing_policy_ref"], row
    )
    assert resolver.has_platform_specific_ref(
        "credential_pool_ref", refs["credential_pool_ref"], row
    )
    assert resolver.has_platform_specific_ref(
        "secret_ref", refs["secret_ref"], row
    )
    wrong_service = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        onboarding_registry=registry,
        llm_service_owner_user_id="service:wrong",
    ).for_owner("u1")
    assert not wrong_service.has_platform_specific_ref(
        "credential_pool_ref", refs["credential_pool_ref"], row
    )


def test_llm_gateway_ref_resolves_to_owner_scoped_persisted_terminal_record(tmp_path):
    store = LLMCallRecordStore(tmp_path / "llm_calls.jsonl")
    common = {
        "provider": "openai",
        "model": "gpt-5.5",
        "auth_ref": "secretref://openai/llm_openai",
        "replay_state": ReplayState.LIVE.value,
        "owner_user_id": "u1",
        "workflow_id": "workflow-platform-m14",
        "invocation_id": "invocation-platform-m14",
        "attempt_no": 1,
        "role": "agent",
        "session_id": "session-platform-m14",
        "routing_policy_ref": "routing:platform-m14:test",
        "routing_policy_state": "configured_ref",
        "prompt_digest": "1" * 16,
        "prompt_hash": "1" * 16,
        "tool_schema_hash": "3" * 16,
        "response_digest": "2" * 16,
        "response_ref": "llm_response:" + "2" * 16,
        "started_at": "2026-07-12T00:00:00+00:00",
        "finished_at": "2026-07-12T00:00:01+00:00",
        "latency_ms": 1000.0,
        "cost": {
            "status": "unavailable", "currency": "USD", "amount": None,
            "source": "none", "reason": "provider_cost_not_reported",
        },
        "status": CallStatus.OK.value,
    }
    records = []
    for kind in (CallRecordKind.ATTEMPT.value, CallRecordKind.TERMINAL.value):
        record = LLMCallRecord(
            **common,
            record_kind=kind,
            call_id=make_call_id(
                prompt_digest="",
                provider="",
                model="",
                role="",
                session_id="",
                seq=1,
                owner_user_id="u1",
                workflow_id="workflow-platform-m14",
                invocation_id="invocation-platform-m14",
                record_kind=kind,
                attempt_no=1,
            ),
        )
        record.seal = seal_record(record, store.seal_secret)
        store.append(record)
        records.append(record)
    terminal = records[-1]
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        llm_call_record_store=store,
    )
    row = SimpleNamespace(m_row="M14")

    assert resolver.for_owner("u1").has_platform_specific_ref(
        "llm_gateway_ref", f"llm_gateway:{terminal.call_id}", row
    )
    assert not resolver.for_owner("u2").has_platform_specific_ref(
        "llm_gateway_ref", f"llm_gateway:{terminal.call_id}", row
    )


def test_m20_kill_switch_ref_resolves_only_from_durable_owner_halt(tmp_path):
    barrier = PersistentAccountHaltBarrier(tmp_path / "account_halt.sqlite3")
    halt_ref = "account_halt_platform_m20"
    account_ref = "account:u1:binance"
    barrier.activate(account_ref, "u1")
    snapshots = barrier.begin_halt_many(
        "u1",
        [account_ref],
        halt_ref=halt_ref,
        action_name="kill_switch",
        close_positions=True,
    )
    epochs = {ref: snapshot.epoch for ref, snapshot in snapshots.items()}
    flat_proof_ref = barrier.record_flat_proof(
        "u1",
        halt_ref=halt_ref,
        close_positions=True,
        account_epochs=epochs,
        results={
            account_ref: {
                "ok": True,
                "normal_open_order_refs": [],
                "algo_open_order_refs": [],
                "open_positions": [],
            }
        },
    )
    barrier.finalize_halt_many(
        "u1",
        epochs,
        flat_proof_ref=flat_proof_ref,
    )
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        account_halt_barrier=barrier,
    )
    row = SimpleNamespace(m_row="M20")

    assert resolver.for_owner("u1").has_platform_specific_ref(
        "kill_switch_ref", halt_ref, row
    )
    assert not resolver.for_owner("u2").has_platform_specific_ref(
        "kill_switch_ref", halt_ref, row
    )
    assert not resolver.for_owner("u1").has_platform_specific_ref(
        "kill_switch_ref", "account_halt_missing", row
    )
    empty_ref = "account_halt_empty_scope"
    barrier.begin_halt_many(
        "u3",
        [],
        halt_ref=empty_ref,
        allow_missing=True,
        action_name="kill_switch",
        close_positions=True,
    )
    assert not resolver.for_owner("u3").has_platform_specific_ref(
        "kill_switch_ref",
        empty_ref,
        row,
    )


def test_m6_m7_and_m9_specific_refs_require_owner_qro_and_real_passport():
    refs = {
        "execution_boundary_ref": "execution_policy:paper_btc:v1",
        "model_passport_ref": "model_passport_real",
        "validation_dossier_ref": "validation_dossier:real",
        "signal_contract_ref": "signal_contract:real",
        "strategy_book_ref": "strategy_book:real",
    }
    commands = [
        SimpleNamespace(
            command_id="rgcmd-model",
            actor="u1",
            payload={
                "qro": SimpleNamespace(
                    qro_id="qro-model",
                    owner="u1",
                    qro_type="Model",
                    output_contract={
                        "model_passport_ref": refs["model_passport_ref"],
                        "validation_dossier_ref": refs["validation_dossier_ref"],
                    },
                )
            },
        ),
        SimpleNamespace(
            command_id="rgcmd-strategy-book",
            actor="u1",
            payload={
                "qro": SimpleNamespace(
                    qro_id="qro-strategy-book",
                    owner="u1",
                    qro_type="StrategyBook",
                    output_contract={
                        "signal_contract_ref": refs["signal_contract_ref"],
                        "strategy_book_ref": refs["strategy_book_ref"],
                    },
                )
            },
        ),
        SimpleNamespace(
            command_id="rgcmd-execution",
            actor="u1",
            payload={
                "qro": SimpleNamespace(
                    qro_id="qro-execution",
                    owner="u1",
                    qro_type="ExecutionPolicy",
                    output_contract={
                        "execution_boundary_ref": refs["execution_boundary_ref"],
                    },
                )
            },
        ),
    ]

    class _Graph:
        def commands(self):
            return commands

    class _Governance:
        def passport(self, ref, *, owner_user_id):
            if ref != refs["model_passport_ref"] or owner_user_id != "u1":
                raise KeyError(ref)
            return SimpleNamespace(passport_id=ref)

    resolver = build_real_ref_resolver(
        research_graph_store=_Graph(),
        lifecycle_registry=None,
        governance_registry=_Governance(),
        rag_index=None,
        spine_chain_registry=None,
    )
    rows = {
        "model_passport_ref": SimpleNamespace(
            m_row="M6", qro_ref="qro-model", research_graph_ref="rgcmd-model"
        ),
        "validation_dossier_ref": SimpleNamespace(
            m_row="M6", qro_ref="qro-model", research_graph_ref="rgcmd-model"
        ),
        "signal_contract_ref": SimpleNamespace(
            m_row="M7-M8",
            qro_ref="qro-strategy-book",
            research_graph_ref="rgcmd-strategy-book",
        ),
        "strategy_book_ref": SimpleNamespace(
            m_row="M7-M8",
            qro_ref="qro-strategy-book",
            research_graph_ref="rgcmd-strategy-book",
        ),
        "execution_boundary_ref": SimpleNamespace(
            m_row="M9", qro_ref="qro-execution", research_graph_ref="rgcmd-execution"
        ),
    }

    for field, ref in refs.items():
        row = rows[field]
        assert resolver.for_owner("u1").has_platform_specific_ref(field, ref, row)
        assert not resolver.for_owner("u2").has_platform_specific_ref(field, ref, row)
        wrong_row = SimpleNamespace(
            m_row=row.m_row,
            qro_ref="qro-other",
            research_graph_ref=row.research_graph_ref,
        )
        assert not resolver.for_owner("u1").has_platform_specific_ref(field, ref, wrong_row)
    assert not resolver.for_owner("u1").has_platform_specific_ref(
        "model_passport_ref", "model_passport_missing", rows["model_passport_ref"]
    )


def test_m3_linkage_requires_one_exact_owner_dataset_bundle():
    owner = "u1"
    skill = SimpleNamespace(
        skill_id="ingestion_skill:bars:v1",
        source_ref="datasource:bars",
        schema_mapping_ref="schema_map:bars:v1",
        pit_bitemporal_rules_ref="pit:bars:v1",
        output_dataset_id="bars",
        owner=owner,
        version="v1",
    )
    source = SimpleNamespace(source_ref=skill.source_ref)
    update = SimpleNamespace(
        update_ref="ingestion_update:bars:v1",
        skill_ref=skill.skill_id,
        skill_version=skill.version,
        dataset_version_ref="dataset_version:bars:version-1",
        checksum="sha256-bars",
        lineage_ref="lineage:bars:v1",
        source_ref=skill.source_ref,
        known_at_ref="known_at:bars:v1",
        effective_at_ref="effective_at:bars:v1",
        row_count=10,
        recorded_by=owner,
    )
    pit = SimpleNamespace(
        rule_ref=skill.pit_bitemporal_rules_ref,
        skill_id=skill.skill_id,
        source_ref=skill.source_ref,
        field_mapping_ref="field_mapping:bars:v1",
        schema_probe_ref="schema_probe:bars:v1",
        recorded_by=owner,
    )
    dataset = DatasetSemanticsRecord(
        dataset_ref="dataset:bars:v1",
        source_ref=skill.source_ref,
        version="version-1",
        known_at_ref=update.known_at_ref,
        effective_at_ref=update.effective_at_ref,
        pit_bitemporal_rules_ref=pit.rule_ref,
        quality_status="passed",
        lineage_refs=(
            update.update_ref,
            update.lineage_ref,
            pit.rule_ref,
            pit.field_mapping_ref,
            pit.schema_probe_ref,
        ),
        freshness_status="fresh",
        checksum=update.checksum,
    )
    instrument = InstrumentSpec(
        instrument_ref="instrument:BTCUSDT",
        asset_class="crypto_spot",
        instrument_type="spot",
        currency="USD",
        exchange_calendar_ref="calendar:crypto:247",
        symbol_mapping_ref=skill.schema_mapping_ref,
    )
    capability = MarketCapabilityMatrixRecord(
        matrix_ref="capability:bars:spot",
        asset_class=instrument.asset_class,
        instrument_type=instrument.instrument_type,
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
        data_availability=dataset.dataset_ref,
        cost_model_availability="cost_model:spot:v1",
        execution_availability="execution:paper_only",
        permission_requirement="market_data:read",
    )
    validation = MarketDataUseValidationRecord(
        validation_ref="market_data_use:bars:v1",
        request_ref="market_data_request:bars:v1",
        use_context="confirmatory_validation",
        dataset_refs=(dataset.dataset_ref,),
        instrument_refs=(instrument.instrument_ref,),
        capability_matrix_ref=capability.matrix_ref,
        capital_record_ref=None,
        transformation_refs=(),
        accepted=True,
        violation_codes=(),
        evidence_refs=("evidence:bars:v1",),
        recorded_by=owner,
        created_at_utc="2026-07-12T00:00:00+00:00",
    )
    version = SimpleNamespace(
        dataset_id=skill.output_dataset_id,
        version_id=dataset.version,
        sha256=dataset.checksum,
        row_count=update.row_count,
        metadata={
            "ingestion_skill_id": skill.skill_id,
            "ingestion_skill_version": skill.version,
            "source_ref": skill.source_ref,
            "pit_bitemporal_rules_ref": pit.rule_ref,
        },
    )
    qro = SimpleNamespace(
        qro_id="qro_dataset_bars_v1",
        qro_type="Dataset",
        owner=owner,
        input_contract={
            "entry_source": "api",
            "dataset_ref": dataset.dataset_ref,
            "source_ref": dataset.source_ref,
            "version": dataset.version,
            "record_hash": content_hash(dataset.to_dict()),
        },
        output_contract={
            "status": "dataset_semantics_recorded",
            "dataset_ref": dataset.dataset_ref,
            "known_at_ref": dataset.known_at_ref,
            "effective_at_ref": dataset.effective_at_ref,
            "pit_bitemporal_rules_ref": dataset.pit_bitemporal_rules_ref,
            "quality_status": dataset.quality_status,
            "freshness_status": dataset.freshness_status,
        },
        implementation_hash="market_data_dataset:" + content_hash(dataset.to_dict()),
    )
    command = SimpleNamespace(
        command_id="rgcmd_dataset_bars_v1",
        command_type="upsert_qro",
        actor=owner,
        payload={"qro": qro},
    )
    chain = SimpleNamespace(data_semantics_ref=dataset.dataset_ref)
    rag_metadata = {
        "m_row": "M3",
        "qro_ref": qro.qro_id,
        "research_graph_ref": command.command_id,
        "ingestion_skill_ref": skill.skill_id,
        "lifecycle_ref": update.update_ref,
        "dataset_ref": dataset.dataset_ref,
        "pit_bitemporal_rules_ref": pit.rule_ref,
        "instrument_spec_ref": instrument.instrument_ref,
        "governance_ref": validation.validation_ref,
        "math_spine_ref": "math_spine:bars:v1",
    }
    rag = SimpleNamespace(
        document_id="ragdoc_dataset_bars_v1",
        asset_ref=dataset.dataset_ref,
        permission=SimpleNamespace(
            allowed_users=(owner,),
            allowed_assets=(dataset.dataset_ref,),
        ),
        metadata=rag_metadata,
    )

    class _Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

        def commands(self):
            return [command]

    class _Onboarding:
        def ingestion_skill(self, ref, *, owner_user_id):
            if ref != skill.skill_id or owner_user_id != owner:
                raise KeyError(ref)
            return skill

        def data_source(self, ref, *, owner_user_id):
            if ref != source.source_ref or owner_user_id != owner:
                raise KeyError(ref)
            return source

        def data_connector_pit_bitemporal_rule(self, ref, *, owner_user_id):
            if ref != pit.rule_ref or owner_user_id != owner:
                raise KeyError(ref)
            return pit

    class _Lifecycle:
        def ingestion_skill_update(self, ref, *, owner_user_id):
            if ref != update.update_ref or owner_user_id != owner:
                raise KeyError(ref)
            return update

    class _MarketData:
        def dataset(self, ref, *, owner_user_id):
            if ref != dataset.dataset_ref or owner_user_id != owner:
                raise KeyError(ref)
            return dataset

        def instrument(self, ref, *, owner_user_id):
            if ref != instrument.instrument_ref or owner_user_id != owner:
                raise KeyError(ref)
            return instrument

        def capability_matrix(self, ref, *, owner_user_id):
            if ref != capability.matrix_ref or owner_user_id != owner:
                raise KeyError(ref)
            return capability

        def use_validation(self, ref, *, owner_user_id):
            if ref != validation.validation_ref or owner_user_id != owner:
                raise KeyError(ref)
            return validation

    class _Versions:
        def resolve_version_ref(self, ref):
            if ref != update.dataset_version_ref:
                raise KeyError(ref)
            return version

    class _Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math_spine:bars:v1" or owner != "u1":
                raise KeyError(ref)
            return chain

    class _RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if (
                ref != rag.document_id
                or owner_user_id != owner
                or require_current is not True
            ):
                raise KeyError(ref)
            return rag

    resolver = build_real_ref_resolver(
        research_graph_store=_Graph(),
        lifecycle_registry=_Lifecycle(),
        governance_registry=None,
        rag_index=_RAG(),
        spine_chain_registry=_Spine(),
        market_data_registry=_MarketData(),
        dataset_registry=_Versions(),
        onboarding_registry=_Onboarding(),
    ).for_owner(owner)
    row = SimpleNamespace(
        m_row="M3",
        qro_ref=qro.qro_id,
        research_graph_ref=command.command_id,
        lifecycle_ref=update.update_ref,
        governance_ref=validation.validation_ref,
        rag_ref=rag.document_id,
        math_spine_ref="math_spine:bars:v1",
        specific_refs=(
            SimpleNamespace(key="ingestion_skill_ref", ref=skill.skill_id),
            SimpleNamespace(key="instrument_spec_ref", ref=instrument.instrument_ref),
        ),
    )

    assert resolver.platform_linkage_violations(row) == ()

    mixed = SimpleNamespace(**{**row.__dict__, "governance_ref": "market_data_use:other"})
    violations = resolver.platform_linkage_violations(mixed)
    assert violations
    assert any("lookup failed" in reason for _field, _ref, reason in violations)


def test_goal_closure_ref_banned_even_when_it_resolves_in_store(tmp_path):
    # Recursive-fake-green defense: a goal_closure:* chain really exists in the
    # store (the removed materializer seeded such records), so the raw getter
    # returns True -- but the token ban makes resolve_typed_ref reject it.
    spine, resolver = _real_spine_backing(tmp_path)
    seeded = _mk_chain(chain_ref="math_spine_chain:goal_closure:section_0_17:v1")
    spine._chains[seeded.chain_ref] = seeded
    assert resolver.has_math_spine_chain(seeded.chain_ref) is False
    assert resolve_typed_ref(resolver, "math_spine", seeded.chain_ref) is False  # gate says not


def _real_entrypoint_lineage(
    tmp_path,
    *,
    independent_evidence_owner: str | None = "u1",
):
    qro = SimpleNamespace(
        qro_id="qro_real",
        owner="u1",
        version=1,
        input_contract={"entry_source": "api"},
    )
    command = SimpleNamespace(
        command_id="rgcmd_real",
        source="api",
        command_type="upsert_qro",
        actor_source="user_manual",
        actor="u1",
        payload={"qro": qro},
        timestamp="2026-07-14T00:00:00+00:00",
    )
    validation_registry = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl"
    )
    provisional_receipt = GoalValidationReceipt(
        validation_ref="",
        owner_user_id="u1",
        subject_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        validator_identifiers=("runtime_validator:coherent_entrypoint_test",),
        test_identifiers=("pytest:test_real_entrypoint_lineage",),
        outcome=GoalValidationOutcome.PASSED,
        evidence_refs=("evidence:real",),
        evidence_digests=("sha256:" + "a" * 64,),
    )
    receipt = validation_registry.record_receipt(
        replace(
            provisional_receipt,
            validation_ref=provisional_receipt.canonical_validation_ref,
        )
    )
    ir = SimpleNamespace(
        ir_ref="compiler_ir:real",
        source_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        evidence_refs=("evidence:real",),
        validation_refs=(receipt.validation_ref,),
        canonical_command_refs=("research_graph_command:rgcmd_real", "entrypoint:api:real"),
        permission_ref="permission:real",
        node_refs=("qro:qro_real", "entrypoint:api:real"),
        owner="u1",
    )
    compiler_pass = SimpleNamespace(
        pass_ref="compiler_pass:real",
        output_ir_ref=ir.ir_ref,
        input_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        evidence_refs=ir.evidence_refs,
        validation_refs=ir.validation_refs,
        canonical_command_refs=ir.canonical_command_refs,
        permission_ref=ir.permission_ref,
        entry_source="api",
        tool_record_refs=("api:real",),
        actor="u1",
    )

    class _GraphStore:
        def __init__(self):
            self.current_qro = qro

        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return self.current_qro

        def commands(self):
            return [command]

        def projection_index(self, *, owner=None):
            if owner not in (None, qro.owner):
                return []
            return [
                SimpleNamespace(
                    qro_id=qro.qro_id,
                    command_id=command.command_id,
                    owner=qro.owner,
                    source=command.source,
                    actor_source=command.actor_source,
                    actor=command.actor,
                    command_timestamp=command.timestamp,
                    qro_version=qro.version,
                )
            ]

    class _CompilerStore:
        def canonical_ir(self, ref, *, owner):
            return self.ir(ref, owner=owner)

        def canonical_compiler_pass(self, ref, *, owner):
            return self.compiler_pass(ref, owner=owner)

        def canonical_artifact(self, ref, *, owner):
            raise KeyError(ref)

        def canonical_records(self, *, owner):
            if owner != "u1":
                return SimpleNamespace(irs=(), passes=(), artifacts=())
            return SimpleNamespace(
                irs=(ir,),
                passes=(compiler_pass,),
                artifacts=(),
            )

        def ir(self, ref, *, owner):
            if owner != "u1":
                raise KeyError(ref)
            if ref != ir.ir_ref:
                raise KeyError(ref)
            return ir

        def compiler_pass(self, ref, *, owner):
            if owner != "u1":
                raise KeyError(ref)
            if ref != compiler_pass.pass_ref:
                raise KeyError(ref)
            return compiler_pass

        def irs(self, *, owner):
            if owner != "u1":
                return []
            return [ir]

        def passes(self, *, owner):
            if owner != "u1":
                return []
            return [compiler_pass]

        def artifacts(self, *, owner):
            return []

    class _DocumentStore:
        def span(self, ref):
            if ref != "evidence:real" or independent_evidence_owner is None:
                raise KeyError(ref)
            return SimpleNamespace(
                span_ref=ref,
                owner=independent_evidence_owner,
                verified=True,
                span_support_verification_ref="span_support:evidence:real",
            )

    entrypoint_ref = "api:real"
    goal_sections = ("§0", "§1", "§7", "§8")
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source="api",
        entrypoint_ref=entrypoint_ref,
        goal_sections=goal_sections,
        qro_refs=(qro.qro_id,),
        research_graph_command_refs=(command.command_id,),
        compiler_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
    )
    record = GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source="api",
        entrypoint_ref=entrypoint_ref,
        goal_sections=goal_sections,
        qro_refs=(qro.qro_id,),
        research_graph_command_refs=(command.command_id,),
        compiler_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
        evidence_refs=ir.evidence_refs,
        validation_refs=ir.validation_refs,
        permission_refs=(ir.permission_ref,),
        replay_refs=(
            f"replay:research_graph:{command.command_id}",
            f"replay:compiler_ir:{ir.ir_ref}",
            f"replay:compiler_pass:{compiler_pass.pass_ref}",
        ),
        canonical_command_refs=ir.canonical_command_refs,
        recorded_by="u1",
    )
    resolver = build_real_ref_resolver(
        research_graph_store=_GraphStore(),
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        compiler_store=_CompilerStore(),
        document_store=_DocumentStore(),
        goal_validation_receipt_registry=validation_registry,
    )
    return record, resolver


def test_real_entrypoint_lineage_accepts_one_coherent_chain(tmp_path):
    record, resolver = _real_entrypoint_lineage(tmp_path)
    decision = validate_goal_entrypoint_real_backing(record, resolver=resolver)
    assert decision.accepted, decision.violations


def test_compiler_lineage_cannot_self_certify_evidence(tmp_path):
    record, resolver = _real_entrypoint_lineage(
        tmp_path,
        independent_evidence_owner=None,
    )
    owner_resolver = resolver.for_owner("u1")

    assert owner_resolver.has_compiler_ir(record.compiler_ir_refs[0]) is True
    assert owner_resolver.has_evidence(record.evidence_refs[0]) is False
    assert owner_resolver.has_platform_evidence(
        SimpleNamespace(qro_ref=record.qro_refs[0]),
        record.evidence_refs[0],
    ) is False

    decision = validate_goal_entrypoint_real_backing(record, resolver=resolver)
    assert not decision.accepted
    assert any(
        violation.field == "evidence_refs"
        and violation.code == "goal_entrypoint_ref_not_backed"
        for violation in decision.violations
    )


def test_independent_evidence_resolution_is_owner_scoped(tmp_path):
    record, resolver = _real_entrypoint_lineage(
        tmp_path,
        independent_evidence_owner="u2",
    )

    assert resolver.for_owner("u1").has_evidence(record.evidence_refs[0]) is False
    assert not validate_goal_entrypoint_real_backing(
        record,
        resolver=resolver,
    ).accepted


def test_real_entrypoint_lineage_rejects_relabelled_source_even_with_recomputed_identity(tmp_path):
    record, resolver = _real_entrypoint_lineage(tmp_path)
    relabelled = replace(record, entry_source="chat")
    relabelled = replace(
        relabelled,
        coverage_ref=goal_entrypoint_coverage_identity(
            entry_source=relabelled.entry_source,
            entrypoint_ref=relabelled.entrypoint_ref,
            goal_sections=relabelled.goal_sections,
            qro_refs=relabelled.qro_refs,
            research_graph_command_refs=relabelled.research_graph_command_refs,
            compiler_ir_refs=relabelled.compiler_ir_refs,
            compiler_pass_refs=relabelled.compiler_pass_refs,
        ),
    )
    decision = validate_goal_entrypoint_real_backing(relabelled, resolver=resolver)
    assert not decision.accepted
    assert any(violation.code == "goal_entrypoint_linkage_invalid" for violation in decision.violations)


def test_real_entrypoint_lineage_rejects_self_declared_full_product_sections(tmp_path):
    record, resolver = _real_entrypoint_lineage(tmp_path)
    relabelled = replace(
        record,
        goal_sections=tuple(f"§{index}" for index in range(18)),
        claims_full_product_entrypoint=True,
    )
    relabelled = replace(
        relabelled,
        coverage_ref=goal_entrypoint_coverage_identity(
            entry_source=relabelled.entry_source,
            entrypoint_ref=relabelled.entrypoint_ref,
            goal_sections=relabelled.goal_sections,
            qro_refs=relabelled.qro_refs,
            research_graph_command_refs=relabelled.research_graph_command_refs,
            compiler_ir_refs=relabelled.compiler_ir_refs,
            compiler_pass_refs=relabelled.compiler_pass_refs,
        ),
    )

    decision = validate_goal_entrypoint_real_backing(relabelled, resolver=resolver)

    assert not decision.accepted
    assert any(
        violation.field == "claims_full_product_entrypoint"
        and "dedicated durable full-product validator" in violation.message
        for violation in decision.violations
    )


def test_real_entrypoint_lineage_rejects_stale_qro_and_surplus_replay_refs(tmp_path):
    record, resolver = _real_entrypoint_lineage(tmp_path / "stale")
    resolver._research_graph_store.current_qro = SimpleNamespace(
        **{
            **resolver._research_graph_store.current_qro.__dict__,
            "input_contract": {"entry_source": "api", "revision": "newer"},
        }
    )
    stale = validate_goal_entrypoint_real_backing(record, resolver=resolver)
    assert not stale.accepted
    assert any("stale" in violation.message for violation in stale.violations)

    current_record, current_resolver = _real_entrypoint_lineage(tmp_path / "surplus")
    surplus = replace(
        current_record,
        replay_refs=(*current_record.replay_refs, "replay:unrelated:extra"),
    )
    surplus_decision = validate_goal_entrypoint_real_backing(
        surplus,
        resolver=current_resolver,
    )
    assert not surplus_decision.accepted
    assert any(
        violation.field == "replay_refs"
        for violation in surplus_decision.violations
    )


# ---------------------------------------------------------------------------
# Generalized dispatch + fail-closed matrix (composition double)
# ---------------------------------------------------------------------------


def test_backed_id_is_backed_unbacked_is_not():
    resolver = _DictResolver(qro={"qro_real_1"}, math_spine={"math_spine_chain:real:v1"})
    assert resolve_typed_ref(resolver, "qro", "qro_real_1") is True
    assert resolve_typed_ref(resolver, "math_spine", "math_spine_chain:real:v1") is True
    assert resolve_typed_ref(resolver, "qro", "qro_never_minted") is False
    assert resolve_typed_ref(resolver, "math_spine", "math_spine_chain:never:v1") is False


def test_every_ref_type_dispatches_to_its_own_getter():
    # Each ref-type must resolve only its own store's minted id; a different
    # type's id must not leak across. Guards the REF_TYPE_RESOLVER_METHODS map.
    for ref_type in REF_TYPE_RESOLVER_METHODS:
        resolver = _DictResolver(**{ref_type: {"id_real"}})
        assert resolve_typed_ref(resolver, ref_type, "id_real") is True
        assert resolve_typed_ref(resolver, ref_type, "id_other") is False


def test_fail_closed_without_resolver():
    assert resolve_typed_ref(None, "qro", "qro_real_1") is False


def test_fail_closed_unknown_ref_type():
    resolver = _DictResolver(qro={"qro_real_1"})
    assert resolve_typed_ref(resolver, "not_a_ref_type", "qro_real_1") is False


def test_fail_closed_empty_ref():
    resolver = _DictResolver(qro={"qro_real_1", ""})
    assert resolve_typed_ref(resolver, "qro", "") is False
    assert resolve_typed_ref(resolver, "qro", None) is False


def test_fail_closed_when_resolution_raises():
    assert resolve_typed_ref(_RaisingResolver(), "qro", "qro_real_1") is False
    assert resolve_typed_ref(_RaisingResolver(), "math_spine", "math_spine_chain:real:v1") is False


def test_placeholder_token_ref_never_backed_even_if_minted():
    # Every banned token, with a resolver that "minted" the placeholder id: the
    # token ban must win over resolution for all of them.
    for token in PLACEHOLDER_TOKENS:
        ref = f"math_spine_chain:{token}:v1"
        resolver = _DictResolver(math_spine={ref})
        assert is_placeholder_ref(ref) is True
        assert resolve_typed_ref(resolver, "math_spine", ref) is False


def test_is_placeholder_ref_matrix():
    assert is_placeholder_ref(None) is False
    assert is_placeholder_ref("") is False
    assert is_placeholder_ref("qro_platform_m3_real") is False
    assert is_placeholder_ref("rgcmd_unbacked0000000000") is False
    assert is_placeholder_ref("GOAL_CLOSURE:section_0_17") is True  # case-insensitive
    assert is_placeholder_ref("math_spine_chain:goalclosure:v1") is True
    assert is_placeholder_ref("x_synthetic_y") is True
    assert is_placeholder_ref("some_PLACEHOLDER_id") is True
