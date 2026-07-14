from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.connectors.base import FetchRequest, make_wide_fetch_result
from app.data_quality import DatasetRegistry
from app.research_os import (
    DataConnectorConnectionCheckRecord,
    DataConnectorFieldMappingRecord,
    DataConnectorPITBitemporalRuleRecord,
    DataConnectorSchemaProbeRecord,
    DataSourceAssetRecord,
    IngestionLifecycleState,
    IngestionSkillRecord,
    LLMCredentialPoolRecord,
    LLMGatewayCallRequest,
    LLMProviderHealthSnapshotRecord,
    LLMProviderRecord,
    ModelRoutingPolicyRecord,
    SecretRefRecord,
    SecretRefStatus,
    PersistentAssetLifecycleRegistry,
    PersistentCompilerIRStore,
    PersistentEntrypointEvidenceRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentMarketDataRegistry,
    PersistentOnboardingRegistry,
    PersistentResearchGraphStore,
    data_connector_field_mapping_hash,
    data_connector_pit_bitemporal_rule_hash,
    validate_data_source_asset,
    validate_data_connector_connection_check,
    validate_data_connector_field_mapping,
    validate_data_connector_pit_bitemporal_rule,
    validate_data_connector_schema_probe,
    validate_ingestion_skill_run,
    validate_llm_gateway_call,
    validate_llm_provider,
    validate_llm_provider_health_snapshot,
    validate_model_routing_policy,
    validate_secret_ref,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver
from app.security import InMemoryKeystore, SecureKeystore


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _warning_codes(decision) -> set[str]:
    return {warning.code for warning in decision.warnings}


def _secret(**overrides) -> SecretRefRecord:
    data = {
        "secret_ref": "secretref:tushare:read",
        "scope": "market_data:read",
        "status": SecretRefStatus.ACTIVE,
        "created_at": "2026-06-26T00:00:00Z",
        "last_test": "ok",
        "affected_skills": ("ingest:tushare:daily",),
    }
    data.update(overrides)
    return SecretRefRecord(**data)


def _skill(**overrides) -> IngestionSkillRecord:
    data = {
        "skill_id": "ingest:tushare:daily",
        "source_type": "third_party_api",
        "source_ref": "datasource:tushare",
        "connector_config": {"auth_ref": "secretref:tushare:read", "endpoint": "daily"},
        "schema_mapping_ref": "schema_map:tushare:daily",
        "secret_refs": ("secretref:tushare:read",),
        "refresh_mode": "scheduled",
        "data_quality_tests": ("not_null:trade_date",),
        "pit_bitemporal_rules_ref": "pit:tushare:daily",
        "output_dataset_id": "dataset:cn_equity_daily",
        "owner": "dreaminate",
        "version": "1",
        "lifecycle_state": IngestionLifecycleState.ACTIVE,
        "freshness_status": "fresh",
        "permission_scope": "market_data:read",
        "dependency_lock_ref": "deps:tushare:v1",
        "schedule_owner": "scheduler:daily",
        "rollback_plan_ref": "rollback:tushare:v1",
    }
    data.update(overrides)
    return IngestionSkillRecord(**data)


def _data_source(**overrides) -> DataSourceAssetRecord:
    data = {
        "source_ref": "datasource:tushare",
        "license": "commercial:user-provided",
        "redistribution_rights": "internal_only",
        "rate_limit": "500/min",
        "tos_constraints": "no_redistribution",
        "commercial_use_status": "allowed_by_user_account",
        "retention_policy": "retain:research-cache",
        "source_owner": "user",
        "source_url_or_path": "https://api.tushare.pro",
    }
    data.update(overrides)
    return DataSourceAssetRecord(**data)


def _binance_source(**overrides) -> DataSourceAssetRecord:
    data = {
        "source_ref": "datasource:binance:public",
        "license": "public_api_terms",
        "rate_limit": "1200/min",
        "tos_constraints": "binance_public_market_data_terms",
        "commercial_use_status": "public_market_data",
        "retention_policy": "retain:research-cache",
        "source_owner": "binance",
        "source_url_or_path": "https://api.binance.com",
    }
    data.update(overrides)
    return _data_source(**data)


def _binance_skill(**overrides) -> IngestionSkillRecord:
    data = {
        "skill_id": "ingest:binance:btcusdt:1m",
        "source_type": "public_api",
        "source_ref": "datasource:binance:public",
        "connector_config": {
            "connector_name": "binance_rest_spot",
            "auth_mode": "none",
            "data_kind": "ohlcv",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "market": "binance_spot",
        },
        "schema_mapping_ref": "schema_map:binance:ohlcv",
        "secret_refs": (),
        "refresh_mode": "manual",
        "data_quality_tests": ("not_null:ts", "not_null:close"),
        "pit_bitemporal_rules_ref": "pit:binance:ohlcv",
        "output_dataset_id": "dataset:binance_spot_btcusdt_1m",
        "owner": "dreaminate",
        "version": "1",
        "lifecycle_state": IngestionLifecycleState.ACTIVE,
        "freshness_status": "fresh",
        "permission_scope": "market_data:read",
        "dependency_lock_ref": "deps:binance-rest:v1",
        "schedule_owner": "scheduler:manual",
        "rollback_plan_ref": "rollback:binance:v1",
    }
    data.update(overrides)
    return IngestionSkillRecord(**data)


def _stooq_source(**overrides) -> DataSourceAssetRecord:
    data = {
        "source_ref": "datasource:stooq:public",
        "license": "stooq_public_terms",
        "rate_limit": "60/min",
        "tos_constraints": "stooq_public_market_data_terms",
        "commercial_use_status": "user_responsibility",
        "retention_policy": "retain:research-cache",
        "source_owner": "stooq",
        "source_url_or_path": "https://stooq.com/q/d/l/",
    }
    data.update(overrides)
    return _data_source(**data)


def _stooq_skill(**overrides) -> IngestionSkillRecord:
    data = {
        "skill_id": "ingest:stooq:aapl:daily",
        "source_type": "public_csv",
        "source_ref": "datasource:stooq:public",
        "connector_config": {
            "connector_name": "stooq",
            "auth_mode": "none",
            "data_kind": "ohlcv",
            "symbol": "AAPL.US",
            "interval": "1d",
            "market": "stooq",
            "start": "2026-06-25",
            "end": "2026-06-26",
        },
        "schema_mapping_ref": "schema_map:stooq:ohlcv",
        "secret_refs": (),
        "refresh_mode": "manual",
        "data_quality_tests": ("not_null:ts", "not_null:close"),
        "pit_bitemporal_rules_ref": "pit:stooq:daily",
        "output_dataset_id": "dataset:stooq_aapl_daily",
        "owner": "dreaminate",
        "version": "1",
        "lifecycle_state": IngestionLifecycleState.ACTIVE,
        "freshness_status": "fresh",
        "permission_scope": "market_data:read",
        "dependency_lock_ref": "deps:stooq-public:v1",
        "schedule_owner": "scheduler:manual",
        "rollback_plan_ref": "rollback:stooq:v1",
    }
    data.update(overrides)
    return IngestionSkillRecord(**data)


def _generic_rest_yaml() -> str:
    return """
connector_name: custom_bars
label: Custom Bars
asset_class: custom
base_url: https://example.invalid
supported_markets: [custom]
supported_intervals: [1d]
auth:
  mode: none
endpoints:
  ohlcv:
    method: GET
    path: /bars/{symbol}
    query:
      start: "{start_date}"
      end: "{end_date}"
    rate_limit_per_minute: 600
    response_mapping:
      records: "$.data[*]"
      fields:
        ts: t
        open: o
        high: h
        low: l
        close: c
        volume: v
      ts_unit: ms
      tz: UTC
schema_target: ohlcv
"""


def _generic_rest_source(**overrides) -> DataSourceAssetRecord:
    data = {
        "source_ref": "datasource:custom:rest",
        "license": "user_provided",
        "rate_limit": "600/min",
        "tos_constraints": "user_supplied_terms",
        "commercial_use_status": "user_responsibility",
        "retention_policy": "retain:research-cache",
        "source_owner": "user",
        "source_url_or_path": "https://example.invalid",
    }
    data.update(overrides)
    return _data_source(**data)


def _generic_rest_skill(**overrides) -> IngestionSkillRecord:
    data = {
        "skill_id": "ingest:custom:bars",
        "source_type": "generic_rest_api",
        "source_ref": "datasource:custom:rest",
        "connector_config": {
            "connector_name": "generic_rest",
            "auth_mode": "none",
            "generic_rest_yaml": _generic_rest_yaml(),
            "data_kind": "ohlcv",
            "symbol": "DEMO",
            "interval": "1d",
            "market": "custom",
            "start": "2026-06-26",
            "end": "2026-06-27",
        },
        "schema_mapping_ref": "schema_map:custom:bars",
        "secret_refs": (),
        "refresh_mode": "manual",
        "data_quality_tests": ("not_null:ts", "not_null:close"),
        "pit_bitemporal_rules_ref": "pit:custom:bars",
        "output_dataset_id": "dataset:custom_bars",
        "owner": "dreaminate",
        "version": "1",
        "lifecycle_state": IngestionLifecycleState.ACTIVE,
        "freshness_status": "fresh",
        "permission_scope": "market_data:read",
        "dependency_lock_ref": "deps:generic-rest:v1",
        "schedule_owner": "scheduler:manual",
        "rollback_plan_ref": "rollback:generic-rest:v1",
    }
    data.update(overrides)
    return IngestionSkillRecord(**data)


def _connector_check(**overrides) -> DataConnectorConnectionCheckRecord:
    data = {
        "check_ref": "connector_check:tushare:001",
        "skill_id": "ingest:tushare:daily",
        "source_ref": "datasource:tushare",
        "secret_refs": ("secretref:tushare:read",),
        "checked_at": "2026-06-27T00:00:00Z",
        "checker_ref": "checker:tushare:test",
        "status": "ok",
        "health_status": "ok",
        "quota_status": "ok",
        "permission_scope": "market_data:read",
        "capability_refs": ("capability:daily_bar",),
        "schema_probe_ref": "schema_probe:tushare:daily:001",
        "response_hash": "sha256:tushare-sanitized-response",
        "recorded_by": "u1",
    }
    data.update(overrides)
    return DataConnectorConnectionCheckRecord(**data)


def _schema_probe(**overrides) -> DataConnectorSchemaProbeRecord:
    data = {
        "probe_ref": "schema_probe:tushare:daily:001",
        "skill_id": "ingest:tushare:daily",
        "source_ref": "datasource:tushare",
        "connector_check_ref": "connector_check:tushare:001",
        "probed_at": "2026-06-27T00:01:00Z",
        "schema_signature_hash": "schema_signature:ohlcv-v1",
        "columns": ("ts", "symbol", "close"),
        "dtypes": {"ts": "String", "symbol": "String", "close": "Float64"},
        "row_count": 2,
        "dataset_version_ref": "dataset_version:dataset:cn_equity_daily:v1",
        "drift_status": "none",
        "recorded_by": "u1",
    }
    data.update(overrides)
    return DataConnectorSchemaProbeRecord(**data)


def _field_mapping(**overrides) -> DataConnectorFieldMappingRecord:
    data = {
        "mapping_ref": "schema_map:tushare:daily",
        "skill_id": "ingest:tushare:daily",
        "source_ref": "datasource:tushare",
        "schema_probe_ref": "schema_probe:tushare:daily:001",
        "mapped_at": "2026-06-27T00:02:00Z",
        "schema_signature_hash": "schema_signature:ohlcv-v1",
        "source_to_canonical": {"ts": "event_time", "symbol": "instrument_id", "close": "close"},
        "event_time_column": "ts",
        "known_at_column": "ts",
        "effective_at_column": "ts",
        "symbol_column": "symbol",
        "unmapped_columns": (),
        "mapping_method": "manual",
        "pit_bitemporal_candidate_ref": "pit_candidate:tushare:daily:001",
        "evidence_refs": ("schema_probe:tushare:daily:001",),
        "recorded_by": "u1",
    }
    data.update(overrides)
    record = DataConnectorFieldMappingRecord(**data)
    if overrides.get("mapping_hash") is not None:
        return record
    return replace(record, mapping_hash=data_connector_field_mapping_hash(record))


def _pit_rule(**overrides) -> DataConnectorPITBitemporalRuleRecord:
    data = {
        "rule_ref": "pit:tushare:daily",
        "skill_id": "ingest:tushare:daily",
        "source_ref": "datasource:tushare",
        "field_mapping_ref": "schema_map:tushare:daily",
        "schema_probe_ref": "schema_probe:tushare:daily:001",
        "generated_at": "2026-06-27T00:03:00Z",
        "event_time_column": "ts",
        "known_at_column": "ts",
        "effective_at_column": "ts",
        "known_at_policy": "source_column",
        "effective_at_policy": "source_column",
        "asof_join_policy": "known_at_lte_decision_time_latest",
        "timezone": "UTC",
        "calendar_ref": "calendar:datasource:tushare:default",
        "lookahead_guard_ref": "lookahead_guard:ingest:tushare:daily:pit",
        "monotonicity_check_ref": "monotonicity:schema_map:tushare:daily:event_known",
        "restatement_policy": "latest_known_at_before_decision_time",
        "evidence_refs": ("schema_map:tushare:daily", "schema_probe:tushare:daily:001"),
        "recorded_by": "u1",
    }
    data.update(overrides)
    record = DataConnectorPITBitemporalRuleRecord(**data)
    if overrides.get("rule_hash") is not None:
        return record
    return replace(record, rule_hash=data_connector_pit_bitemporal_rule_hash(record))


def _provider(**overrides) -> LLMProviderRecord:
    data = {
        "provider_id": "openai",
        "provider_type": "openai_api",
        "auth_methods": ("api_key",),
        "base_url": "https://api.openai.com/v1",
        "model_profiles": ("gpt-5.5",),
        "capability_tags": ("tool_calling", "structured_output"),
        "context_window": 200000,
        "tool_calling_support": True,
        "structured_output_support": True,
        "cost_model_ref": "cost:openai:gpt55",
        "rate_limits": "tier:project",
        "data_retention_policy": "zero-retention-required",
        "region_residency": "us",
        "allowed_roles": ("researcher", "verifier"),
        "allowed_desks": ("research", "strategy"),
        "health_status": "ok",
        "quota_status": "ok",
        "auth_refs": ("secretref:openai:project",),
    }
    data.update(overrides)
    return LLMProviderRecord(**data)


def _provider_health_snapshot(**overrides) -> LLMProviderHealthSnapshotRecord:
    data = {
        "snapshot_ref": "llm_health:openai:001",
        "provider_id": "openai",
        "auth_ref": "secretref:openai:project",
        "checked_at": "2026-06-28T00:00:00Z",
        "checker_ref": "checker:settings-llm:test",
        "health_status": "ok",
        "quota_status": "ok",
        "latency_ms": 123,
        "response_hash": "sha256:llm-health-response",
        "capability_refs": ("capability:tool-calling",),
        "evidence_refs": ("evidence:llm-health",),
    }
    data.update(overrides)
    return LLMProviderHealthSnapshotRecord(**data)


def _pool(**overrides) -> LLMCredentialPoolRecord:
    data = {
        "pool_id": "pool:openai:research",
        "provider_id": "openai",
        "auth_refs": ("secretref:openai:project",),
        "priority": ("secretref:openai:project",),
        "rotation_policy": "rotate:90d",
        "fallback_policy": "no-cross-provider-without-policy",
        "rate_limit_policy": "respect-provider",
        "quota_policy": "stop-at-budget",
        "owner": "dreaminate",
    }
    data.update(overrides)
    return LLMCredentialPoolRecord(**data)


def _policy(**overrides) -> ModelRoutingPolicyRecord:
    data = {
        "routing_policy_id": "routing:researcher:strategy",
        "role_agent": "researcher",
        "desk": "strategy",
        "task_type": "research_code_review",
        "required_capabilities": ("tool_calling",),
        "allowed_providers": ("openai",),
        "allowed_models": ("gpt-5.5",),
        "credential_pool_ref": "pool:openai:research",
        "fallback_order": ("gpt-5.5",),
        "cost_limit": "usd:10/day",
        "latency_limit": "p95:30s",
        "data_retention_requirement": "zero-retention-required",
        "independence_requirement": "verifier-model-different-family",
        "replay_requirement": "record",
    }
    data.update(overrides)
    return ModelRoutingPolicyRecord(**data)


def _request(**overrides) -> LLMGatewayCallRequest:
    data = {
        "role_agent": "researcher",
        "desk": "strategy",
        "task_type": "research_code_review",
        "provider_id": "openai",
        "model_id": "gpt-5.5",
        "routing_policy_ref": "routing:researcher:strategy",
        "credential_pool_ref": "pool:openai:research",
        "auth_ref": "secretref:openai:project",
        "via_gateway": True,
        "replay_record_ref": "llm_replay:001",
    }
    data.update(overrides)
    return LLMGatewayCallRequest(**data)


def _payload(record) -> dict:
    return record.__dict__.copy()


def _patch_goal_proof_stores(tmp_path, monkeypatch):  # noqa: ANN001
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)


def _client_with_onboarding_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTBT_LLM_ADMIN_USER_IDS", "u1")
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    monkeypatch.setattr(main, "ONBOARDING_REGISTRY", registry)
    _patch_goal_proof_stores(tmp_path, monkeypatch)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), registry


def _assert_compiler_coverage(body: dict, *, entrypoint_ref: str) -> None:
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.input_qro_refs == (body["qro_id"],)
    assert compiler_pass.entry_source == "api"
    assert coverage.entry_source == "api"
    assert coverage.entrypoint_ref == entrypoint_ref
    assert coverage.qro_refs == (body["qro_id"],)
    assert coverage.research_graph_command_refs == (body["research_graph_command_id"],)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert compiler_pass.direct_graph_mutation is False
    assert compiler_pass.bypassed_permission is False
    assert compiler_pass.raw_llm_output_embedded_as_ir is False
    assert coverage.silent_mock_fallback_used is False
    assert coverage.raw_payload_persisted is False


def _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch):
    lifecycle = PersistentAssetLifecycleRegistry(tmp_path / "asset_lifecycle.jsonl")
    datasets = DatasetRegistry(tmp_path / "datasets.jsonl")
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(main, "DATASET_REGISTRY", datasets)
    monkeypatch.setattr(main, "DATA_ROOT", tmp_path)
    return lifecycle, datasets


def _install_readiness_llm_chain(tmp_path, monkeypatch, registry, *, suffix: str):
    from app.agent import LLMMessage, LLMResponse, ensure_settings_managed_llm_provider
    from app.llm import (
        GatewayBackedLLMClient,
        PersistentLLMUseBindingStore,
        build_agent_llm_gateway,
    )
    from app.llm.call_record_store import LLMCallRecordStore
    from app.research_os import PersistentOnboardingReadinessRegistry
    from app.security import KeystoreRecord

    service_owner = main._LLM_SERVICE_PRINCIPAL
    now = datetime.now(UTC).isoformat()
    ensure_settings_managed_llm_provider(
        registry=registry,
        provider="openai",
        owner=service_owner,
        created_at=now,
    )
    registry.record_llm_provider_health_snapshot(
        _provider_health_snapshot(
            snapshot_ref=f"llm_health:openai:{suffix}",
            auth_ref="secretref:llm:openai",
            checked_at=now,
            recorded_by=service_owner,
        ),
        owner_user_id=service_owner,
    )
    call_store = LLMCallRecordStore(tmp_path / f"llm_call_records_{suffix}.jsonl")
    binding_store = PersistentLLMUseBindingStore(
        tmp_path / f"llm_gateway_use_bindings_{suffix}.jsonl",
        seal_secret=call_store.seal_secret,
        terminal_record_resolver=call_store.resolve_terminal_record,
    )
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(
        KeystoreRecord(
            name="llm_openai",
            api_key="sk-test-only-readiness-key-0123456789",
            api_secret="sk-test-only-readiness-key-0123456789",
        )
    )

    class ReadinessLLM:
        def chat(self, messages, *, tools=None, model=None, temperature=0.2):
            return LLMResponse(content="readiness-ok")

    gateway = build_agent_llm_gateway(
        keystore,
        client_factory=lambda _credential: ReadinessLLM(),
        seal_secret=call_store.seal_secret,
        use_binding_sink=binding_store.append,
        service_principal_ref=service_owner,
        credential_pool_refs={"openai": "pool:llm:openai:default"},
        routing_policy_refs={"openai": "routing:llm:openai:default"},
    )
    workflow_ref = f"readiness-workflow-{suffix}"
    llm_client = GatewayBackedLLMClient(
        gateway,
        session_id=workflow_ref,
        owner_user_id="u1",
        workflow_id=workflow_ref,
        invocation_id_factory=lambda: f"readiness-invocation-{suffix}",
        record_sink=call_store.append,
    )
    assert llm_client.chat([LLMMessage(role="user", content="readiness check")]).content == (
        "readiness-ok"
    )
    monkeypatch.setattr(main, "LLM_CALL_RECORD_STORE", call_store)
    monkeypatch.setattr(main, "LLM_USE_BINDING_STORE", binding_store)
    readiness_registry = PersistentOnboardingReadinessRegistry(
        tmp_path / f"onboarding_readiness_{suffix}.jsonl",
        resolve_snapshot=main._resolve_onboarding_readiness_snapshot,
    )
    monkeypatch.setattr(main, "ONBOARDING_READINESS_REGISTRY", readiness_registry)
    return llm_client.last_record.call_id, readiness_registry


def _register_dataset_version(registry: DatasetRegistry, *, checksum: str | None = None):
    frame = pl.DataFrame({"ts": ["2026-06-26", "2026-06-27"], "close": [1.0, 1.1]})
    result = make_wide_fetch_result(frame, "tushare")
    result = replace(
        result,
        fetched_at_utc="2026-06-27T00:00:00Z",
        coverage_start_utc="2026-06-26T00:00:00Z",
        coverage_end_utc="2026-06-27T00:00:00Z",
        sha256=checksum or result.sha256,
    )
    return registry.register(
        "dataset:cn_equity_daily",
        result,
    )


def _dataset_version_ref(version) -> str:
    return f"dataset_version:{version.dataset_id}:{version.version_id}"


def _seed_ok_connector_check(registry: PersistentOnboardingRegistry, **overrides):
    return registry.record_data_connector_check(
        _connector_check(**overrides),
        owner_user_id="u1",
    )


def _runner_fetch_result(frame: pl.DataFrame | None = None):
    result = make_wide_fetch_result(
        frame
        if frame is not None
        else pl.DataFrame(
            {
                "ts": ["2026-06-26T00:00:00Z", "2026-06-27T00:00:00Z"],
                "symbol": ["000001.SZ", "000001.SZ"],
                "close": [10.0, 10.5],
            }
        ),
        source_name="tushare",
    )
    result.fetched_at_utc = "2026-06-27T01:00:00Z"
    return result


def test_agent_plaintext_key_in_connector_config_is_rejected():
    decision = validate_ingestion_skill_run(
        _skill(connector_config={"api_key": "sk-plaintext-1234567890"}),
        secrets={"secretref:tushare:read": _secret()},
    )
    assert not decision.accepted
    assert "plaintext_secret_in_connector_config" in _codes(decision)


def test_revoked_secret_ref_prevents_skill_from_running_silently():
    decision = validate_ingestion_skill_run(
        _skill(lifecycle_state=IngestionLifecycleState.ACTIVE),
        secrets={"secretref:tushare:read": _secret(status=SecretRefStatus.REVOKED, revoked_at="2026-06-26")},
    )
    assert not decision.accepted
    assert "revoked_secret_skill_running" in _codes(decision)


def test_data_source_asset_missing_license_rate_limit_or_retention_restricts_export_and_share():
    asset = DataSourceAssetRecord(
        source_ref="datasource:unknown_csv",
        license=None,
        redistribution_rights="unknown",
        rate_limit=None,
        tos_constraints="unknown",
        commercial_use_status="unknown",
        retention_policy=None,
        source_owner="user",
        source_url_or_path="/tmp/data.csv",
    )
    decision = validate_data_source_asset(asset)
    assert decision.accepted
    assert not decision.export_allowed
    assert not decision.share_allowed
    assert _warning_codes(decision) >= {"missing_license", "missing_rate_limit", "missing_retention_policy"}


def test_schema_drift_requires_event_and_downstream_impact():
    decision = validate_ingestion_skill_run(
        _skill(schema_drift_status="drifted", schema_drift_event_refs=(), downstream_impact_refs=()),
        secrets={"secretref:tushare:read": _secret()},
    )
    assert not decision.accepted
    assert "schema_drift_missing_event_or_impact" in _codes(decision)


def test_data_connector_connection_check_requires_settings_managed_secret_and_sanitized_hash():
    decision = validate_data_connector_connection_check(
        _connector_check(),
        skill=_skill(),
        source=_data_source(),
        secrets={"secretref:tushare:read": _secret()},
    )
    assert decision.accepted
    assert decision.violations == ()

    revoked = validate_data_connector_connection_check(
        _connector_check(),
        skill=_skill(lifecycle_state=IngestionLifecycleState.PAUSED),
        source=_data_source(),
        secrets={"secretref:tushare:read": _secret(status=SecretRefStatus.REVOKED, revoked_at="2026-06-27")},
    )
    assert not revoked.accepted
    assert "connector_check_uses_revoked_secret_ref" in _codes(revoked)

    raw = validate_data_connector_connection_check(
        _connector_check(error_message="api_key=sk-leaked-1234567890abcdef"),
        skill=_skill(),
        source=_data_source(),
        secrets={"secretref:tushare:read": _secret()},
    )
    assert not raw.accepted
    assert "plaintext_secret_in_connector_check" in _codes(raw)


def test_data_connector_schema_probe_requires_ok_check_and_drift_event_refs():
    decision = validate_data_connector_schema_probe(
        _schema_probe(),
        skill=_skill(),
        source=_data_source(),
        connector_check=_connector_check(),
    )
    assert decision.accepted
    assert decision.violations == ()

    drift = validate_data_connector_schema_probe(
        _schema_probe(
            probe_ref="schema_probe:tushare:daily:changed",
            drift_status="changed",
            previous_probe_ref="schema_probe:tushare:daily:001",
            schema_drift_event_ref=None,
            downstream_impact_refs=(),
        ),
        skill=_skill(),
        source=_data_source(),
        connector_check=_connector_check(),
    )
    assert not drift.accepted
    assert "schema_drift_missing_event_or_impact" in _codes(drift)

    leaky = validate_data_connector_schema_probe(
        _schema_probe(columns=("ts", "api_key"), dtypes={"ts": "String", "api_key": "String"}),
        skill=_skill(),
        source=_data_source(),
        connector_check=_connector_check(),
    )
    assert not leaky.accepted
    assert "plaintext_secret_in_schema_probe" in _codes(leaky)


def test_data_connector_field_mapping_binds_schema_probe_and_time_axes():
    record = _field_mapping()
    decision = validate_data_connector_field_mapping(
        record,
        skill=_skill(),
        source=_data_source(),
        schema_probe=_schema_probe(),
    )
    assert decision.accepted
    assert decision.violations == ()

    unknown_column = _field_mapping(source_to_canonical={"ts": "event_time", "adj_close": "close", "symbol": "instrument_id"})
    decision = validate_data_connector_field_mapping(
        unknown_column,
        skill=_skill(),
        source=_data_source(),
        schema_probe=_schema_probe(),
    )
    assert not decision.accepted
    assert "field_mapping_unknown_source_column" in _codes(decision)
    assert "field_mapping_missing_column_coverage" in _codes(decision)

    no_time_axis = _field_mapping(event_time_column="trade_dt")
    decision = validate_data_connector_field_mapping(
        no_time_axis,
        skill=_skill(),
        source=_data_source(),
        schema_probe=_schema_probe(),
    )
    assert not decision.accepted
    assert "field_mapping_event_time_unknown" in _codes(decision)
    assert "field_mapping_event_time_unmapped" in _codes(decision)

    crypto_token_column = _field_mapping(
        source_to_canonical={"ts": "event_time", "token": "instrument_id", "close": "close"},
        symbol_column="token",
    )
    decision = validate_data_connector_field_mapping(
        crypto_token_column,
        skill=_skill(),
        source=_data_source(),
        schema_probe=_schema_probe(columns=("ts", "token", "close"), dtypes={"ts": "String", "token": "String", "close": "Float64"}),
    )
    assert decision.accepted

    leaky = _field_mapping(source_to_canonical={"ts": "event_time", "symbol": "instrument_id", "api_key": "credential"})
    decision = validate_data_connector_field_mapping(
        leaky,
        skill=_skill(),
        source=_data_source(),
        schema_probe=_schema_probe(columns=("ts", "symbol", "api_key"), dtypes={"ts": "String", "symbol": "String", "api_key": "String"}),
    )
    assert not decision.accepted
    assert "field_mapping_secret_like_column_or_field" in _codes(decision)

    tampered = _field_mapping(mapping_hash="field_mapping:tampered")
    decision = validate_data_connector_field_mapping(
        tampered,
        skill=_skill(),
        source=_data_source(),
        schema_probe=_schema_probe(),
    )
    assert not decision.accepted
    assert "field_mapping_hash_mismatch" in _codes(decision)


def test_data_connector_pit_bitemporal_rule_binds_field_mapping_and_safe_asof_policy():
    record = _pit_rule()
    decision = validate_data_connector_pit_bitemporal_rule(
        record,
        skill=_skill(),
        source=_data_source(),
        field_mapping=_field_mapping(),
        schema_probe=_schema_probe(),
    )
    assert decision.accepted
    assert decision.violations == ()

    unsafe_asof = _pit_rule(asof_join_policy="current_snapshot")
    decision = validate_data_connector_pit_bitemporal_rule(
        unsafe_asof,
        skill=_skill(),
        source=_data_source(),
        field_mapping=_field_mapping(),
        schema_probe=_schema_probe(),
    )
    assert not decision.accepted
    assert "pit_rule_asof_policy_not_pit_safe" in _codes(decision)

    unknown_time_column = _pit_rule(event_time_column="trade_dt")
    decision = validate_data_connector_pit_bitemporal_rule(
        unknown_time_column,
        skill=_skill(),
        source=_data_source(),
        field_mapping=_field_mapping(),
        schema_probe=_schema_probe(),
    )
    assert not decision.accepted
    assert "pit_rule_event_time_unknown" in _codes(decision)
    assert "pit_rule_event_time_not_field_mapping_axis" in _codes(decision)

    missing_evidence = _pit_rule(evidence_refs=("schema_probe:tushare:daily:001",))
    decision = validate_data_connector_pit_bitemporal_rule(
        missing_evidence,
        skill=_skill(),
        source=_data_source(),
        field_mapping=_field_mapping(),
        schema_probe=_schema_probe(),
    )
    assert not decision.accepted
    assert "pit_rule_missing_evidence_refs" in _codes(decision)

    tampered = _pit_rule(rule_hash="pit_bitemporal_rule:tampered")
    decision = validate_data_connector_pit_bitemporal_rule(
        tampered,
        skill=_skill(),
        source=_data_source(),
        field_mapping=_field_mapping(),
        schema_probe=_schema_probe(),
    )
    assert not decision.accepted
    assert "pit_rule_hash_mismatch" in _codes(decision)


def test_llm_provider_credential_must_be_settings_managed():
    decision = validate_llm_provider(
        _provider(auth_refs=("sk-raw-inline",), plaintext_credential="sk-inline-1234567890")
    )
    assert not decision.accepted
    assert _codes(decision) >= {"plaintext_llm_provider_credential", "llm_auth_ref_not_settings_managed"}


def test_role_agent_cannot_bypass_llm_gateway():
    decision = validate_llm_gateway_call(
        _request(via_gateway=False),
        policy=_policy(),
        credential_pool=_pool(),
    )
    assert not decision.accepted
    assert "role_agent_bypassed_llm_gateway" in _codes(decision)


def test_model_routing_policy_requires_allowed_models_pool_and_replay_requirement():
    decision = validate_model_routing_policy(
        _policy(allowed_models=(), credential_pool_ref=None, replay_requirement=None)
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "missing_allowed_models",
        "missing_credential_pool_ref",
        "missing_replay_requirement",
    }


def test_llm_gateway_call_accepts_complete_policy_pool_and_replay_record():
    decision = validate_llm_gateway_call(
        _request(),
        policy=_policy(),
        credential_pool=_pool(),
    )
    assert decision.accepted
    assert decision.violations == ()


def test_secret_ref_metadata_rejects_plaintext_and_revoked_without_revoked_at():
    plaintext = validate_secret_ref(
        _secret(stale_warning="rotating leaked key sk-live-1234567890abcdef")
    )
    assert not plaintext.accepted
    assert "plaintext_secret_in_secret_ref_metadata" in _codes(plaintext)

    revoked = validate_secret_ref(_secret(status=SecretRefStatus.REVOKED, revoked_at=None))
    assert not revoked.accepted
    assert "revoked_secret_missing_revoked_at" in _codes(revoked)


def test_persistent_onboarding_registry_replays_settings_records(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    registry = PersistentOnboardingRegistry(path)
    secret = _secret(secret_ref="secretref:openai:project", scope="llm:openai")
    registry.record_secret_ref(secret, owner_user_id="u1")
    registry.record_llm_provider(_provider(), owner_user_id="u1")
    registry.record_llm_provider_health_snapshot(
        _provider_health_snapshot(recorded_by="u1"), owner_user_id="u1"
    )
    registry.record_credential_pool(_pool(), owner_user_id="u1")
    registry.record_routing_policy(_policy(), owner_user_id="u1")

    reloaded = PersistentOnboardingRegistry(path)
    assert reloaded.secret_ref("secretref:openai:project", owner_user_id="u1").scope == "llm:openai"
    assert reloaded.llm_provider("openai", owner_user_id="u1").auth_refs == ("secretref:openai:project",)
    assert reloaded.llm_provider_health_snapshot(
        "llm_health:openai:001", owner_user_id="u1"
    ).snapshot_hash.startswith("sha16:")
    assert reloaded.llm_provider_health_snapshots("openai", owner_user_id="u1")[0].quota_status == "ok"
    assert reloaded.credential_pool("pool:openai:research", owner_user_id="u1").provider_id == "openai"
    assert reloaded.routing_policy(
        "routing:researcher:strategy", owner_user_id="u1"
    ).allowed_models == ("gpt-5.5",)


def test_persistent_onboarding_registry_replays_data_connector_records(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_secret_ref(_secret(), owner_user_id="u1")
    registry.record_data_source_asset(_data_source(), owner_user_id="u1")
    registry.record_ingestion_skill(_skill(), owner_user_id="u1")
    registry.record_data_connector_check(_connector_check(), owner_user_id="u1")
    registry.record_data_connector_schema_probe(_schema_probe(), owner_user_id="u1")
    registry.record_data_connector_field_mapping(_field_mapping(), owner_user_id="u1")
    registry.record_data_connector_pit_bitemporal_rule(_pit_rule(), owner_user_id="u1")

    reloaded = PersistentOnboardingRegistry(path)
    assert reloaded.data_source("datasource:tushare", owner_user_id="u1").license == "commercial:user-provided"
    assert reloaded.ingestion_skill("ingest:tushare:daily", owner_user_id="u1").secret_refs == ("secretref:tushare:read",)
    assert reloaded.data_connector_check(
        "connector_check:tushare:001", owner_user_id="u1"
    ).health_status == "ok"
    assert reloaded.data_connector_schema_probe(
        "schema_probe:tushare:daily:001", owner_user_id="u1"
    ).columns == ("ts", "symbol", "close")
    assert reloaded.data_connector_field_mapping(
        "schema_map:tushare:daily", owner_user_id="u1"
    ).source_to_canonical["close"] == "close"
    assert reloaded.data_connector_pit_bitemporal_rule(
        "pit:tushare:daily", owner_user_id="u1"
    ).asof_join_policy == "known_at_lte_decision_time_latest"


def test_persistent_onboarding_registry_rejects_provider_for_unrecorded_secret(tmp_path):
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")

    with pytest.raises(ValueError, match="auth_ref"):
        registry.record_llm_provider(_provider(), owner_user_id="u1")

    assert not registry.path.exists()


def test_llm_provider_health_snapshot_rejects_bad_status_and_plaintext_secret():
    bad_status = validate_llm_provider_health_snapshot(_provider_health_snapshot(health_status="green"))
    assert not bad_status.accepted
    assert "invalid_llm_provider_health_status" in _codes(bad_status)

    bad_quota = validate_llm_provider_health_snapshot(_provider_health_snapshot(quota_status="unlimited"))
    assert not bad_quota.accepted
    assert "invalid_llm_provider_quota_status" in _codes(bad_quota)

    plaintext = validate_llm_provider_health_snapshot(
        _provider_health_snapshot(evidence_refs=("evidence:ok", "api_key=sk-secret-value"))
    )
    assert not plaintext.accepted
    assert "plaintext_llm_provider_health_payload" in _codes(plaintext)


def test_persistent_onboarding_registry_rejects_health_snapshot_for_unknown_or_wrong_provider(tmp_path):
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    registry.record_secret_ref(
        _secret(secret_ref="secretref:openai:project", scope="llm:openai"),
        owner_user_id="u1",
    )

    with pytest.raises(ValueError, match="provider_id"):
        registry.record_llm_provider_health_snapshot(
            _provider_health_snapshot(recorded_by="u1"), owner_user_id="u1"
        )

    registry.record_llm_provider(_provider(), owner_user_id="u1")
    with pytest.raises(ValueError, match="not recorded for provider"):
        registry.record_llm_provider_health_snapshot(
            _provider_health_snapshot(
                auth_ref="secretref:anthropic:project", recorded_by="u1"
            ),
            owner_user_id="u1",
        )


def _record_all_onboarding_registry_families(
    registry: PersistentOnboardingRegistry,
    *,
    owner_user_id: str,
) -> None:
    registry.record_secret_ref(_secret(), owner_user_id=owner_user_id)
    registry.record_data_source_asset(_data_source(), owner_user_id=owner_user_id)
    registry.record_ingestion_skill(_skill(), owner_user_id=owner_user_id)
    registry.record_data_connector_check(
        _connector_check(recorded_by=owner_user_id),
        owner_user_id=owner_user_id,
    )
    registry.record_data_connector_schema_probe(
        _schema_probe(recorded_by=owner_user_id),
        owner_user_id=owner_user_id,
    )
    registry.record_data_connector_field_mapping(
        _field_mapping(recorded_by=owner_user_id),
        owner_user_id=owner_user_id,
    )
    registry.record_data_connector_pit_bitemporal_rule(
        _pit_rule(recorded_by=owner_user_id),
        owner_user_id=owner_user_id,
    )
    registry.record_secret_ref(
        _secret(secret_ref="secretref:openai:project", scope="llm:openai"),
        owner_user_id=owner_user_id,
    )
    registry.record_llm_provider(_provider(), owner_user_id=owner_user_id)
    registry.record_llm_provider_health_snapshot(
        _provider_health_snapshot(recorded_by=owner_user_id),
        owner_user_id=owner_user_id,
    )
    registry.record_credential_pool(_pool(), owner_user_id=owner_user_id)
    registry.record_routing_policy(_policy(), owner_user_id=owner_user_id)


def test_persistent_onboarding_registry_v2_scopes_all_families_by_owner_and_replays(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    registry = PersistentOnboardingRegistry(path)
    _record_all_onboarding_registry_families(registry, owner_user_id="u1")
    _record_all_onboarding_registry_families(registry, owner_user_id="u2")

    reloaded = PersistentOnboardingRegistry(path)
    for owner_user_id in ("u1", "u2"):
        assert len(reloaded.secret_refs(owner_user_id=owner_user_id)) == 2
        assert len(reloaded.data_sources(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.ingestion_skills(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.data_connector_checks(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.data_connector_schema_probes(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.data_connector_field_mappings(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.data_connector_pit_bitemporal_rules(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.llm_providers(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.llm_provider_health_snapshots(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.credential_pools(owner_user_id=owner_user_id)) == 1
        assert len(reloaded.routing_policies(owner_user_id=owner_user_id)) == 1
        assert reloaded.secret_ref(
            "secretref:tushare:read", owner_user_id=owner_user_id
        ).scope == "market_data:read"

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 24
    assert {row["schema_version"] for row in rows} == {2}
    assert {row["owner_user_id"] for row in rows} == {"u1", "u2"}
    assert all(row["record_revision"] == 1 for row in rows)
    assert all(row["previous_record_hash"] is None for row in rows)
    assert all(row["record_hash"].startswith("sha256:") for row in rows)
    assert all(set(row) == {
        "schema_version",
        "owner_user_id",
        "event_type",
        "record_revision",
        "previous_record_hash",
        "record_hash",
        "payload",
    } for row in rows)


def test_persistent_onboarding_registry_v2_exact_retry_and_explicit_cas_are_atomic(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    registry = PersistentOnboardingRegistry(path)
    original = _secret(last_used=None)
    registry.record_secret_ref(original, owner_user_id="u1")
    first_bytes = path.read_bytes()

    registry.record_secret_ref(original, owner_user_id="u1")
    assert path.read_bytes() == first_bytes

    changed = replace(original, last_used="2026-07-12T01:00:00Z")
    with pytest.raises(ValueError, match="matching previous revision and hash"):
        registry.record_secret_ref(changed, owner_user_id="u1")
    assert path.read_bytes() == first_bytes

    revision, record_hash = registry.record_state(
        "secret_ref_recorded", original.secret_ref, owner_user_id="u1"
    )
    registry.record_secret_ref(
        changed,
        owner_user_id="u1",
        expected_previous_revision=revision,
        expected_previous_hash=record_hash,
    )
    second_bytes = path.read_bytes()
    rows = [json.loads(line) for line in second_bytes.decode().splitlines()]
    assert rows[-1]["record_revision"] == 2
    assert rows[-1]["previous_record_hash"] == rows[0]["record_hash"]

    with pytest.raises(ValueError, match="matching previous revision and hash"):
        registry.record_secret_ref(
            replace(changed, last_used="2026-07-12T02:00:00Z"),
            owner_user_id="u1",
            expected_previous_revision=revision,
            expected_previous_hash=record_hash,
        )
    assert path.read_bytes() == second_bytes


def test_persistent_onboarding_registry_v2_rejects_spoofed_recorded_by_without_write(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_secret_ref(_secret(), owner_user_id="u1")
    registry.record_data_source_asset(_data_source(), owner_user_id="u1")
    registry.record_ingestion_skill(_skill(), owner_user_id="u1")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="recorded_by must exactly match owner_user_id"):
        registry.record_data_connector_check(
            _connector_check(recorded_by="u2"),
            owner_user_id="u1",
        )
    assert path.read_bytes() == before
    assert registry.data_connector_checks(owner_user_id="u1") == []


def test_persistent_onboarding_registry_v2_rejects_cross_owner_dependencies_without_write(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_secret_ref(_secret(), owner_user_id="u1")
    registry.record_data_source_asset(_data_source(), owner_user_id="u1")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="not recorded for owner"):
        registry.record_ingestion_skill(_skill(), owner_user_id="u2")
    assert path.read_bytes() == before
    assert registry.ingestion_skills(owner_user_id="u1") == []
    assert registry.ingestion_skills(owner_user_id="u2") == []


def test_persistent_onboarding_registry_v2_quarantines_legacy_rows_without_assigning_owner(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    legacy = {
        "schema_version": 1,
        "event_type": "secret_ref_recorded",
        "secret_ref": {"secret_ref": "secretref:legacy:unowned"},
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    registry = PersistentOnboardingRegistry(path)
    assert registry.legacy_quarantined_count == 1
    assert registry.secret_refs(owner_user_id="u1") == []
    registry.record_secret_ref(_secret(), owner_user_id="u1")

    rows = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0]) == legacy
    assert json.loads(rows[1])["schema_version"] == 2
    assert PersistentOnboardingRegistry(path).legacy_quarantined_count == 1


@pytest.mark.parametrize("corruption", ["hash", "partial"])
def test_persistent_onboarding_registry_v2_corrupt_history_fails_closed(tmp_path, corruption):
    path = tmp_path / "onboarding_settings.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_secret_ref(_secret(), owner_user_id="u1")
    if corruption == "hash":
        row = json.loads(path.read_text(encoding="utf-8"))
        row["payload"]["scope"] = "tampered"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{")

    with pytest.raises(ValueError, match="invalid persisted onboarding settings row"):
        PersistentOnboardingRegistry(path)


def test_persistent_onboarding_registry_v2_serializes_cross_process_writers(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    watcher = PersistentOnboardingRegistry(path)
    backend_dir = Path(__file__).resolve().parents[1]
    script = """
import sys
from app.research_os.onboarding_gateway import PersistentOnboardingRegistry, SecretRefRecord

path, owner_user_id, secret_ref = sys.argv[1:4]
registry = PersistentOnboardingRegistry(path)
registry.record_secret_ref(
    SecretRefRecord(
        secret_ref=secret_ref,
        scope="market_data:read",
        status="active",
        created_at="2026-07-12T00:00:00Z",
        last_test="ok",
    ),
    owner_user_id=owner_user_id,
)
"""
    refs = ["secretref:shared"] * 2 + [f"secretref:worker:{index}" for index in range(6)]
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), "u1", ref],
            cwd=backend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for ref in refs
    ]
    results = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0] * len(processes), results

    assert len(watcher.secret_refs(owner_user_id="u1")) == 7
    reloaded = PersistentOnboardingRegistry(path)
    assert reloaded.secret_refs(owner_user_id="u1") == watcher.secret_refs(owner_user_id="u1")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 7
    assert len({(row["owner_user_id"], row["payload"]["secret_ref"]) for row in rows}) == 7


def test_settings_api_records_llm_routing_summary_without_plaintext_secret(tmp_path, monkeypatch):
    client, _registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    try:
        secret = client.post(
            "/api/research-os/settings/secret_refs",
            json=_payload(_secret(secret_ref="secretref:openai:project", scope="llm:openai")),
        )
        assert secret.status_code == 200, secret.text
        assert secret.json() == {
            "secret_ref": "secretref:openai:project",
            "recorded_by": main._LLM_SERVICE_PRINCIPAL,
        }

        provider = client.post("/api/research-os/settings/llm_providers", json=_payload(_provider()))
        assert provider.status_code == 200, provider.text
        assert provider.json()["auth_refs"] == ["secretref:openai:project"]

        snapshot = client.post(
            "/api/research-os/settings/llm_provider_health_snapshots",
            json=_payload(_provider_health_snapshot()),
        )
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["snapshot_hash"].startswith("sha16:")
        assert snapshot.json()["health_status"] == "ok"

        pool = client.post("/api/research-os/settings/credential_pools", json=_payload(_pool()))
        assert pool.status_code == 200, pool.text
        assert pool.json()["pool_id"] == "pool:openai:research"

        policy = client.post("/api/research-os/settings/routing_policies", json=_payload(_policy()))
        assert policy.status_code == 200, policy.text
        assert policy.json()["routing_policy_id"] == "routing:researcher:strategy"

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["secret_ref_total"] == 1
        assert body["llm_provider_total"] == 1
        assert body["llm_provider_health_snapshot_total"] == 1
        assert body["credential_pool_total"] == 1
        assert body["routing_policy_total"] == 1
        assert body["llm_providers"][0]["provider_id"] == "openai"
        assert body["llm_provider_health_snapshots"][0]["snapshot_ref"] == "llm_health:openai:001"
        assert "raw_response" not in summary.text
        assert "sk-" not in summary.text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_bad_llm_provider_health_snapshot_without_partial_write(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    try:
        secret = client.post(
            "/api/research-os/settings/secret_refs",
            json=_payload(_secret(secret_ref="secretref:openai:project", scope="llm:openai")),
        )
        assert secret.status_code == 200, secret.text
        provider = client.post("/api/research-os/settings/llm_providers", json=_payload(_provider()))
        assert provider.status_code == 200, provider.text

        bad_status = client.post(
            "/api/research-os/settings/llm_provider_health_snapshots",
            json=_payload(_provider_health_snapshot(health_status="green")),
        )
        assert bad_status.status_code == 422
        assert "health_status" in bad_status.json()["detail"]

        raw_payload = _payload(_provider_health_snapshot())
        raw_payload["raw_response"] = {"usage": {"remaining": 10}}
        raw = client.post("/api/research-os/settings/llm_provider_health_snapshots", json=raw_payload)
        assert raw.status_code == 422
        assert "raw or secret-bearing field" in raw.json()["detail"]

        unknown_provider = client.post(
            "/api/research-os/settings/llm_provider_health_snapshots",
            json=_payload(_provider_health_snapshot(provider_id="anthropic")),
        )
        assert unknown_provider.status_code == 422
        assert "provider_id" in unknown_provider.json()["detail"]

        assert registry.llm_provider_health_snapshots(
            owner_user_id=main._LLM_SERVICE_PRINCIPAL
        ) == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_plaintext_payload_without_partial_write(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/settings/secret_refs",
            json={
                "secret_ref": "secretref:openai:project",
                "scope": "llm:openai",
                "status": "active",
                "created_at": "2026-06-27T00:00:00Z",
                "api_key": "sk-live-1234567890abcdef",
            },
        )
        assert rejected.status_code == 422
        assert "plaintext credential" in rejected.json()["detail"]
        assert registry.secret_refs(owner_user_id="u1") == []
        assert not registry.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_stores_secret_value_in_keystore_without_summary_echo(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    keystore = SecureKeystore(InMemoryKeystore())
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    secret_value = "sk-live-1234567890abcdef"
    try:
        stored = client.post(
            "/api/research-os/settings/secret_values",
            json={
                "secret_ref": "secretref:tushare:read",
                "scope": "market_data:read",
                "secret_value": secret_value,
                "affected_skills": ["ingest:tushare:daily"],
                "connector_scope_review": "datasource:tushare",
            },
        )
        assert stored.status_code == 200, stored.text
        body = stored.json()
        assert body == {
            "secret_ref": "secretref:tushare:read",
            "scope": "market_data:read",
            "status": "active",
            "keystore_ref": "user_c2624fc1593b530f_secretref_tushare_read",
            "keystore_backend": "memory",
            "secret_value_stored": True,
            "recorded_by": "u1",
        }
        assert secret_value not in stored.text
        assert keystore.fetch(body["keystore_ref"]).api_key == secret_value
        assert keystore.fetch(body["keystore_ref"]).api_secret == secret_value
        recorded = registry.secret_ref(
            "secretref:tushare:read",
            owner_user_id="u1",
        )
        assert recorded.access_audit == (
            "keystore:user_c2624fc1593b530f_secretref_tushare_read",
        )
        assert recorded.affected_skills == ("ingest:tushare:daily",)

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["secret_ref_total"] == 1
        assert summary_body["secret_refs"][0]["secret_ref"] == "secretref:tushare:read"
        assert summary_body["secret_refs"][0]["keystore_refs"] == [
            "user_c2624fc1593b530f_secretref_tushare_read"
        ]
        assert summary_body["secret_refs"][0]["keystore_backend"] == "memory"
        assert summary_body["secret_refs"][0]["secret_value_stored"] is True
        assert secret_value not in summary.text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_secret_value_for_revoked_secret_without_keystore_write(tmp_path, monkeypatch):
    client, _registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    keystore = SecureKeystore(InMemoryKeystore())
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    try:
        revoked = client.post(
            "/api/research-os/settings/secret_refs",
            json=_payload(_secret(status=SecretRefStatus.REVOKED, revoked_at="2026-06-27T00:00:00Z")),
        )
        assert revoked.status_code == 200, revoked.text

        stored = client.post(
            "/api/research-os/settings/secret_values",
            json={
                "secret_ref": "secretref:tushare:read",
                "scope": "market_data:read",
                "secret_value": "sk-live-1234567890abcdef",
            },
        )
        assert stored.status_code == 422
        assert "revoked SecretRef" in stored.json()["detail"]
        assert keystore.list_names() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_connector_check_can_dereference_stored_secret_without_response_echo(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    keystore = SecureKeystore(InMemoryKeystore())
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    secret_value = "sk-live-1234567890abcdef"

    class KeystoreBackedChecker:
        checker_ref = "keystore_backed_checker"

        def __init__(self):
            self.calls = []

        def check_connection(self, *, skill, source, secrets, actor):
            secret = secrets[0]
            keystore_ref = next(item.split(":", 1)[1] for item in secret.access_audit if item.startswith("keystore:"))
            record = main.KEYSTORE.fetch(keystore_ref)
            assert record.api_key == secret_value
            self.calls.append((skill.skill_id, source.source_ref, keystore_ref, actor))
            return {
                "check_ref": "connector_check:tushare:keystore",
                "status": "ok",
                "health_status": "ok",
                "quota_status": "ok",
                "response_hash": "sha256:sanitized-keystore-check",
            }

    checker = KeystoreBackedChecker()
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", checker)
    try:
        stored = client.post(
            "/api/research-os/settings/secret_values",
            json={
                "secret_ref": "secretref:tushare:read",
                "scope": "market_data:read",
                "secret_value": secret_value,
                "affected_skills": ["ingest:tushare:daily"],
            },
        )
        assert stored.status_code == 200, stored.text
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_data_source()))
        assert source.status_code == 200, source.text
        skill = client.post("/api/research-os/settings/ingestion_skills", json=_payload(_skill()))
        assert skill.status_code == 200, skill.text

        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert checked.status_code == 200, checked.text
        body = checked.json()
        assert body["ok"] is True
        assert body["check_ref"] == "connector_check:tushare:keystore"
        assert secret_value not in checked.text
        assert checker.calls == [
            (
                "ingest:tushare:daily",
                "datasource:tushare",
                "user_c2624fc1593b530f_secretref_tushare_read",
                "u1",
            )
        ]
        assert len(registry.data_connector_checks(owner_user_id="u1")) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_connector_check_requires_declared_keystore_value_before_checker_call(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "KEYSTORE", SecureKeystore(InMemoryKeystore()))

    class ShouldNotCallChecker:
        checker_ref = "should_not_call"

        def __init__(self):
            self.calls = 0

        def check_connection(self, **_kwargs):
            self.calls += 1
            return {"status": "ok", "health_status": "ok", "quota_status": "ok", "response_hash": "sha256:bad"}

    checker = ShouldNotCallChecker()
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", checker)
    try:
        secret = client.post(
            "/api/research-os/settings/secret_refs",
            json=_payload(_secret(access_audit=("keystore:tushare",))),
        )
        assert secret.status_code == 200, secret.text
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_data_source()))
        assert source.status_code == 200, source.text
        skill = client.post("/api/research-os/settings/ingestion_skills", json=_payload(_skill()))
        assert skill.status_code == 200, skill.text

        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert checked.status_code == 422
        assert "secret value is missing" in checked.json()["detail"]
        assert checker.calls == 0
        assert registry.data_connector_checks(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_default_connector_adapter_uses_keystore_secret_for_tushare_check(tmp_path, monkeypatch):
    client, _registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    keystore = SecureKeystore(InMemoryKeystore())
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.SettingsRegistryDataConnectorConnectionChecker())
    secret_value = "sk-live-1234567890abcdef"

    from app.connectors.tushare_connector import TushareConnector

    class FakeTusharePro:
        def stock_basic(self, **_kwargs):
            return pd.DataFrame({"ts_code": ["000001.SZ"]})

    def fake_client(self):
        assert self._token == secret_value
        return FakeTusharePro()

    monkeypatch.setattr(TushareConnector, "_client", fake_client)
    try:
        stored = client.post(
            "/api/research-os/settings/secret_values",
            json={
                "secret_ref": "secretref:tushare:read",
                "scope": "market_data:read",
                "secret_value": secret_value,
                "affected_skills": ["ingest:tushare:daily"],
            },
        )
        assert stored.status_code == 200, stored.text
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_data_source()))
        assert source.status_code == 200, source.text
        skill = client.post(
            "/api/research-os/settings/ingestion_skills",
            json=_payload(_skill(connector_config={"auth_ref": "secretref:tushare:read", "connector_name": "tushare"})),
        )
        assert skill.status_code == 200, skill.text

        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert checked.status_code == 200, checked.text
        body = checked.json()
        assert body["ok"] is True
        assert body["checker_ref"] == "settings_connector_registry_checker"
        assert body["health_status"] == "ok"
        assert body["capability_refs"] == ["connector_capability:tushare"]
        assert secret_value not in checked.text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_default_ingestion_runner_fetches_tushare_dataset_without_secret_echo(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    _lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    keystore = SecureKeystore(InMemoryKeystore())
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.SettingsRegistryDataConnectorConnectionChecker())
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", main.SettingsRegistryDataConnectorIngestionRunner())
    secret_value = "sk-live-1234567890abcdef"

    from app.connectors.tushare_connector import TushareConnector

    class FakeTusharePro:
        def stock_basic(self, **_kwargs):
            return pd.DataFrame({"ts_code": ["000001.SZ"]})

        def daily(self, **kwargs):
            assert kwargs["ts_code"] == "000001.SZ"
            assert kwargs["start_date"] == "20260626"
            assert kwargs["end_date"] == "20260627"
            return pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000001.SZ"],
                    "trade_date": ["20260626", "20260627"],
                    "open": [10.0, 10.5],
                    "high": [11.0, 11.5],
                    "low": [9.5, 10.0],
                    "close": [10.8, 11.2],
                    "vol": [1000.0, 1100.0],
                    "amount": [10800.0, 12320.0],
                }
            )

    def fake_client(self):
        assert self._token == secret_value
        return FakeTusharePro()

    monkeypatch.setattr(TushareConnector, "_client", fake_client)
    try:
        stored = client.post(
            "/api/research-os/settings/secret_values",
            json={
                "secret_ref": "secretref:tushare:read",
                "scope": "market_data:read",
                "secret_value": secret_value,
                "affected_skills": ["ingest:tushare:daily"],
            },
        )
        assert stored.status_code == 200, stored.text
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_data_source()))
        assert source.status_code == 200, source.text
        skill = client.post(
            "/api/research-os/settings/ingestion_skills",
            json=_payload(
                _skill(
                    connector_config={
                        "auth_ref": "secretref:tushare:read",
                        "connector_name": "tushare",
                        "data_kind": "ohlcv",
                        "symbol": "000001.SZ",
                        "start": "2026-06-26",
                        "end": "2026-06-27",
                        "market": "stocks_cn",
                    },
                )
            ),
        )
        assert skill.status_code == 200, skill.text
        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert checked.status_code == 200, checked.text
        check_ref = checked.json()["check_ref"]

        run = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:tushare:daily", "connector_check_ref": check_ref},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["dataset_id"] == "dataset:cn_equity_daily"
        assert body["row_count"] == 2
        assert body["schema_probe_ref"].startswith("schema_probe:")
        assert body["update_ref"].startswith("ingestion_update:")
        assert len(registry.data_connector_schema_probes(owner_user_id="u1")) == 1
        assert datasets.latest("dataset:cn_equity_daily").row_count == 2
        assert secret_value not in run.text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_default_connector_adapter_supports_binance_public_check_without_secret(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.SettingsRegistryDataConnectorConnectionChecker())

    from app.connectors.binance_rest_connector import BinanceRESTConnector

    calls: list[str] = []

    def fake_health(self):
        calls.append(self._market)
        return SimpleNamespace(ok=True, detail="serverTime=202606270000")

    monkeypatch.setattr(BinanceRESTConnector, "health_check", fake_health)
    try:
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_binance_source()))
        assert source.status_code == 200, source.text
        skill = client.post("/api/research-os/settings/ingestion_skills", json=_payload(_binance_skill()))
        assert skill.status_code == 200, skill.text

        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:binance:btcusdt:1m"},
        )
        assert checked.status_code == 200, checked.text
        body = checked.json()
        assert body["ok"] is True
        assert body["checker_ref"] == "settings_connector_registry_checker"
        assert body["secret_refs"] == []
        assert body["capability_refs"] == ["connector_capability:binance_rest_spot"]
        assert calls == ["binance_spot"]
        assert registry.data_connector_checks(owner_user_id="u1")[0].secret_refs == ()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_default_ingestion_runner_fetches_binance_public_dataset_without_secret(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.SettingsRegistryDataConnectorConnectionChecker())
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", main.SettingsRegistryDataConnectorIngestionRunner())

    from app.connectors.binance_rest_connector import BinanceRESTConnector

    def fake_health(self):
        assert self._market == "binance_spot"
        return SimpleNamespace(ok=True, detail="serverTime=202606270000")

    def fake_fetch(self, request):
        assert self._market == "binance_spot"
        assert request.symbol == "BTCUSDT"
        assert request.interval == "1m"
        assert request.data_kind == "ohlcv"
        assert request.market == "binance_spot"
        return make_wide_fetch_result(
            pl.DataFrame(
                {
                    "ts": [datetime(2026, 6, 27, 0, 0, tzinfo=UTC), datetime(2026, 6, 27, 0, 1, tzinfo=UTC)],
                    "symbol": ["BTCUSDT", "BTCUSDT"],
                    "market": ["binance_spot", "binance_spot"],
                    "interval": ["1m", "1m"],
                    "open": [61000.0, 61010.0],
                    "high": [61020.0, 61030.0],
                    "low": [60990.0, 61000.0],
                    "close": [61010.0, 61020.0],
                    "volume": [12.0, 13.0],
                    "amount": [732120.0, 793260.0],
                }
            ),
            source_name="binance_rest::binance_spot",
        )

    monkeypatch.setattr(BinanceRESTConnector, "health_check", fake_health)
    monkeypatch.setattr(BinanceRESTConnector, "fetch", fake_fetch)
    try:
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_binance_source()))
        assert source.status_code == 200, source.text
        skill = client.post("/api/research-os/settings/ingestion_skills", json=_payload(_binance_skill()))
        assert skill.status_code == 200, skill.text
        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:binance:btcusdt:1m"},
        )
        assert checked.status_code == 200, checked.text
        check_ref = checked.json()["check_ref"]

        run = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:binance:btcusdt:1m", "connector_check_ref": check_ref},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["dataset_id"] == "dataset:binance_spot_btcusdt_1m"
        assert body["row_count"] == 2
        assert datasets.latest("dataset:binance_spot_btcusdt_1m").row_count == 2
        assert len(registry.data_connector_schema_probes(owner_user_id="u1")) == 1
        updates = lifecycle.ingestion_skill_updates(owner_user_id="u1")
        assert len(updates) == 1
        assert updates[0].secret_ref == "secret:none:binance_rest_spot"
        assert "api_key" not in run.text
        assert "secret" not in run.text.lower()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_stooq_connector_fetches_daily_csv_without_secret():
    from app.connectors.stooq_connector import StooqConnector

    class FakeResponse:
        text = "Date,Open,High,Low,Close,Volume\n2026-06-25,200.1,202.0,199.5,201.3,123456\n"

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None, timeout=None):
            self.calls.append((url, params, timeout))
            return FakeResponse()

    session = FakeSession()
    connector = StooqConnector(session=session)

    result = connector.fetch(
        FetchRequest(
            symbol="AAPL.US",
            interval="1d",
            start=datetime(2026, 6, 25, tzinfo=UTC),
            end=datetime(2026, 6, 26, tzinfo=UTC),
            market="stooq",
        )
    )

    assert result.source_name == "stooq"
    assert result.row_count == 1
    assert result.frame.row(0, named=True)["symbol"] == "AAPL.US"
    assert result.frame.row(0, named=True)["market"] == "stooq"
    assert session.calls[0][1] == {"s": "aapl.us", "i": "d", "d1": "20260625", "d2": "20260626"}
    assert "secret" not in result.frame.write_csv().lower()

    with pytest.raises(NotImplementedError, match="daily interval only"):
        connector.fetch(FetchRequest(symbol="AAPL.US", interval="1h", market="stooq"))


def test_settings_default_connector_adapter_supports_stooq_public_check_without_secret(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.SettingsRegistryDataConnectorConnectionChecker())

    from app.connectors.stooq_connector import StooqConnector

    calls: list[str] = []

    def fake_health(self):
        calls.append(self.describe().name)
        return SimpleNamespace(ok=True, detail="daily CSV reachable")

    monkeypatch.setattr(StooqConnector, "health_check", fake_health)
    try:
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_stooq_source()))
        assert source.status_code == 200, source.text
        skill = client.post("/api/research-os/settings/ingestion_skills", json=_payload(_stooq_skill()))
        assert skill.status_code == 200, skill.text

        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:stooq:aapl:daily"},
        )
        assert checked.status_code == 200, checked.text
        body = checked.json()
        assert body["ok"] is True
        assert body["checker_ref"] == "settings_connector_registry_checker"
        assert body["secret_refs"] == []
        assert body["capability_refs"] == ["connector_capability:stooq"]
        assert calls == ["stooq"]
        assert registry.data_connector_checks(owner_user_id="u1")[0].secret_refs == ()
        assert "api_key" not in checked.text
        assert "token=" not in checked.text.lower()
        assert "sk-live" not in checked.text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_records_and_revokes_explicit_no_secret_policy(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    try:
        source = client.post(
            "/api/research-os/settings/data_sources",
            json=_payload(_stooq_source()),
        )
        assert source.status_code == 200, source.text
        created = client.post(
            "/api/research-os/settings/no_secret_data_source_policies",
            json={
                "policy_ref": "no_secret_policy:stooq:public",
                "source_ref": "datasource:stooq:public",
                "source_type": "public_csv",
                "connector_type": "public_csv_no_auth",
                "external_credential_required": False,
                "permission_scope": "market_data:read",
                "approved_at": "2026-07-12T20:00:00Z",
                "approval_ref": "approval:no-secret:stooq",
                "evidence_refs": [
                    "evidence:stooq:public-docs",
                    "evidence:stooq:anonymous-health-check",
                ],
                "reason": "Stooq daily CSV is a documented anonymous read-only source.",
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["actor_ref"] == "u1"
        assert body["status"] == "active"
        assert body["record_revision"] == 1
        assert body["record_hash"].startswith("sha256:")

        skill = client.post(
            "/api/research-os/settings/ingestion_skills",
            json=_payload(_stooq_skill()),
        )
        assert skill.status_code == 200, skill.text
        assert registry.no_secret_data_source_policies(
            owner_user_id="u1",
            source_ref="datasource:stooq:public",
            status="active",
        )[0].policy_ref == body["policy_ref"]

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        assert summary.json()["no_secret_data_source_policy_total"] == 1
        assert summary.json()["no_secret_data_source_policies"][0]["status"] == "active"

        stale = client.post(
            "/api/research-os/settings/no_secret_data_source_policies/"
            "no_secret_policy:stooq:public/revoke",
            json={
                "expected_previous_revision": 1,
                "expected_previous_hash": "sha256:" + "0" * 64,
                "revoked_at": "2026-07-12T21:00:00Z",
                "revocation_reason": "Anonymous access contract changed.",
                "revocation_evidence_refs": ["evidence:stooq:auth-change"],
            },
        )
        assert stale.status_code == 422
        assert registry.no_secret_data_source_policy(
            body["policy_ref"], owner_user_id="u1"
        ).status == "active"

        revoked = client.post(
            "/api/research-os/settings/no_secret_data_source_policies/"
            "no_secret_policy:stooq:public/revoke",
            json={
                "expected_previous_revision": body["record_revision"],
                "expected_previous_hash": body["record_hash"],
                "revoked_at": "2026-07-12T21:00:00Z",
                "revocation_reason": "Anonymous access contract changed.",
                "revocation_evidence_refs": ["evidence:stooq:auth-change"],
            },
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"
        assert revoked.json()["record_revision"] == 2
        assert registry.no_secret_data_source_policies(
            owner_user_id="u1", status="active"
        ) == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_default_ingestion_runner_fetches_stooq_public_dataset_without_secret(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.SettingsRegistryDataConnectorConnectionChecker())
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", main.SettingsRegistryDataConnectorIngestionRunner())

    from app.connectors.stooq_connector import StooqConnector

    def fake_health(self):
        return SimpleNamespace(ok=True, detail="daily CSV reachable")

    def fake_fetch(self, request):
        assert request.symbol == "AAPL.US"
        assert request.interval == "1d"
        assert request.data_kind == "ohlcv"
        assert request.market == "stooq"
        assert request.start == datetime(2026, 6, 25, tzinfo=UTC)
        assert request.end == datetime(2026, 6, 26, tzinfo=UTC)
        return make_wide_fetch_result(
            pl.DataFrame(
                {
                    "ts": [datetime(2026, 6, 25, tzinfo=UTC), datetime(2026, 6, 26, tzinfo=UTC)],
                    "symbol": ["AAPL.US", "AAPL.US"],
                    "market": ["stooq", "stooq"],
                    "interval": ["1d", "1d"],
                    "open": [200.1, 201.0],
                    "high": [202.0, 203.0],
                    "low": [199.5, 200.5],
                    "close": [201.3, 202.4],
                    "volume": [123456.0, 223456.0],
                    "amount": [0.0, 0.0],
                }
            ),
            source_name="stooq",
        )

    monkeypatch.setattr(StooqConnector, "health_check", fake_health)
    monkeypatch.setattr(StooqConnector, "fetch", fake_fetch)
    try:
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_stooq_source()))
        assert source.status_code == 200, source.text
        skill = client.post("/api/research-os/settings/ingestion_skills", json=_payload(_stooq_skill()))
        assert skill.status_code == 200, skill.text
        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:stooq:aapl:daily"},
        )
        assert checked.status_code == 200, checked.text
        check_ref = checked.json()["check_ref"]

        run = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:stooq:aapl:daily", "connector_check_ref": check_ref},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["dataset_id"] == "dataset:stooq_aapl_daily"
        assert body["row_count"] == 2
        assert datasets.latest("dataset:stooq_aapl_daily").row_count == 2
        assert len(registry.data_connector_schema_probes(owner_user_id="u1")) == 1
        updates = lifecycle.ingestion_skill_updates(owner_user_id="u1")
        assert len(updates) == 1
        assert updates[0].secret_ref == "secret:none:stooq"
        assert "api_key" not in run.text
        assert "token=" not in run.text.lower()
        assert "sk-live" not in run.text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_default_connector_adapter_supports_generic_rest_yaml_check_and_run_without_secret(
    tmp_path, monkeypatch
):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.SettingsRegistryDataConnectorConnectionChecker())
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", main.SettingsRegistryDataConnectorIngestionRunner())

    from app.connectors.generic_rest import GenericRESTConnector

    def fake_health(self):
        assert self._config.connector_name == "custom_bars"
        assert self._config.base_url == "https://example.invalid"
        return SimpleNamespace(ok=True, detail="HEAD mocked")

    def fake_fetch(self, request):
        assert self._config.connector_name == "custom_bars"
        assert request.symbol == "DEMO"
        assert request.interval == "1d"
        assert request.data_kind == "ohlcv"
        assert request.market == "custom"
        assert request.start == datetime(2026, 6, 26, tzinfo=UTC)
        assert request.end == datetime(2026, 6, 27, tzinfo=UTC)
        return make_wide_fetch_result(
            pl.DataFrame(
                {
                    "ts": [datetime(2026, 6, 26, tzinfo=UTC), datetime(2026, 6, 27, tzinfo=UTC)],
                    "symbol": ["DEMO", "DEMO"],
                    "market": ["custom", "custom"],
                    "interval": ["1d", "1d"],
                    "open": [1.0, 1.1],
                    "high": [1.2, 1.3],
                    "low": [0.9, 1.0],
                    "close": [1.1, 1.2],
                    "volume": [100.0, 110.0],
                }
            ),
            source_name="custom_bars",
        )

    monkeypatch.setattr(GenericRESTConnector, "health_check", fake_health)
    monkeypatch.setattr(GenericRESTConnector, "fetch", fake_fetch)
    try:
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_generic_rest_source()))
        assert source.status_code == 200, source.text
        skill = client.post("/api/research-os/settings/ingestion_skills", json=_payload(_generic_rest_skill()))
        assert skill.status_code == 200, skill.text

        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:custom:bars"},
        )
        assert checked.status_code == 200, checked.text
        check_body = checked.json()
        assert check_body["ok"] is True
        assert check_body["checker_ref"] == "settings_connector_registry_checker"
        assert check_body["secret_refs"] == []
        assert check_body["capability_refs"] == ["connector_capability:custom_bars"]
        assert registry.data_connector_checks(owner_user_id="u1")[0].secret_refs == ()

        run = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:custom:bars", "connector_check_ref": check_body["check_ref"]},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["dataset_id"] == "dataset:custom_bars"
        assert body["row_count"] == 2
        assert datasets.latest("dataset:custom_bars").row_count == 2
        assert len(registry.data_connector_schema_probes(owner_user_id="u1")) == 1
        updates = lifecycle.ingestion_skill_updates(owner_user_id="u1")
        assert len(updates) == 1
        assert updates[0].secret_ref == "secret:none:custom_bars"
        assert "api_key" not in run.text
        assert "secret" not in run.text.lower()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_generic_rest_connector_requires_yaml_or_config_as_failed_check(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.SettingsRegistryDataConnectorConnectionChecker())

    bad_config = {
        "connector_name": "generic_rest",
        "auth_mode": "none",
        "data_kind": "ohlcv",
        "symbol": "DEMO",
        "market": "custom",
    }
    try:
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_generic_rest_source()))
        assert source.status_code == 200, source.text
        skill = client.post(
            "/api/research-os/settings/ingestion_skills",
            json=_payload(_generic_rest_skill(connector_config=bad_config)),
        )
        assert skill.status_code == 200, skill.text

        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:custom:bars"},
        )
        assert checked.status_code == 200, checked.text
        body = checked.json()
        assert body["ok"] is False
        assert body["status"] == "failed"
        assert body["health_status"] == "failed"
        assert body["capability_refs"] == []
        assert body["error_code"] == "ValueError"
        assert body["error_message"] == "settings generic_rest connector requires generic_rest_yaml or generic_rest_config"
        assert "api_key" not in checked.text
        assert "sk-live" not in checked.text
        assert "static_value" not in checked.text
        assert len(registry.data_connector_checks(owner_user_id="u1")) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def _seed_data_connector_settings(client):
    secret = client.post("/api/research-os/settings/secret_refs", json=_payload(_secret()))
    assert secret.status_code == 200, secret.text
    source = client.post("/api/research-os/settings/data_sources", json=_payload(_data_source()))
    assert source.status_code == 200, source.text
    skill = client.post("/api/research-os/settings/ingestion_skills", json=_payload(_skill()))
    assert skill.status_code == 200, skill.text


def test_settings_api_records_data_connector_check_without_plaintext_secret(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)

    class FakeChecker:
        checker_ref = "fake_data_connector_checker"

        def __init__(self):
            self.calls = []

        def check_connection(self, *, skill, source, secrets, actor):
            self.calls.append((skill.skill_id, source.source_ref, tuple(s.secret_ref for s in secrets), actor))
            return {
                "check_ref": "connector_check:tushare:ok",
                "status": "ok",
                "health_status": "ok",
                "quota_status": "ok",
                "capability_refs": ["capability:daily_bar"],
                "schema_probe_ref": "schema_probe:tushare:daily:001",
                "response_hash": "sha256:sanitized",
            }

    checker = FakeChecker()
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", checker)
    try:
        _seed_data_connector_settings(client)
        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert checked.status_code == 200, checked.text
        body = checked.json()
        assert body["ok"] is True
        assert body["check_ref"] == "connector_check:tushare:ok"
        assert body["response_hash"] == "sha256:sanitized"
        assert checker.calls == [("ingest:tushare:daily", "datasource:tushare", ("secretref:tushare:read",), "u1")]

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["data_source_total"] == 1
        assert summary_body["ingestion_skill_total"] == 1
        assert summary_body["data_connector_check_total"] == 1
        assert summary_body["data_connector_checks"][0]["health_status"] == "ok"
        assert "sk-" not in summary.text
        assert len(registry.data_connector_checks(owner_user_id="u1")) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_records_field_mapping_after_schema_probe_without_partial_write(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    try:
        _seed_data_connector_settings(client)
        registry.record_data_connector_check(
            _connector_check(),
            owner_user_id="u1",
        )
        registry.record_data_connector_schema_probe(
            _schema_probe(),
            owner_user_id="u1",
        )

        recorded = client.post(
            "/api/research-os/settings/data_connector_field_mappings",
            json={
                "skill_id": "ingest:tushare:daily",
                "source_to_canonical": {
                    "ts": "event_time",
                    "symbol": "instrument_id",
                    "close": "close",
                },
                "event_time_column": "ts",
                "known_at_column": "ts",
                "effective_at_column": "ts",
                "symbol_column": "symbol",
                "pit_bitemporal_candidate_ref": "pit_candidate:tushare:daily:001",
            },
        )
        assert recorded.status_code == 200, recorded.text
        body = recorded.json()
        assert body["mapping_ref"] == "schema_map:tushare:daily"
        assert body["source_ref"] == "datasource:tushare"
        assert body["schema_probe_ref"] == "schema_probe:tushare:daily:001"
        assert body["schema_signature_hash"] == "schema_signature:ohlcv-v1"
        assert body["source_to_canonical"]["close"] == "close"
        assert body["mapping_hash"].startswith("field_mapping:")
        assert "sk-" not in recorded.text

        pit = client.post(
            "/api/research-os/settings/pit_bitemporal_rules",
            json={
                "skill_id": "ingest:tushare:daily",
                "field_mapping_ref": "schema_map:tushare:daily",
            },
        )
        assert pit.status_code == 200, pit.text
        pit_body = pit.json()
        assert pit_body["rule_ref"] == "pit:tushare:daily"
        assert pit_body["field_mapping_ref"] == "schema_map:tushare:daily"
        assert pit_body["schema_probe_ref"] == "schema_probe:tushare:daily:001"
        assert pit_body["event_time_column"] == "ts"
        assert pit_body["known_at_policy"] == "source_column"
        assert pit_body["effective_at_policy"] == "source_column"
        assert pit_body["asof_join_policy"] == "known_at_lte_decision_time_latest"
        assert pit_body["rule_hash"].startswith("pit_bitemporal_rule:")

        rejected_pit = client.post(
            "/api/research-os/settings/pit_bitemporal_rules",
            json={
                "skill_id": "ingest:tushare:daily",
                "field_mapping_ref": "schema_map:tushare:daily",
                "asof_join_policy": "current_snapshot",
            },
        )
        assert rejected_pit.status_code == 422
        assert "pit_rule_asof_policy_not_pit_safe" in rejected_pit.json()["detail"]
        assert len(
            registry.data_connector_pit_bitemporal_rules(owner_user_id="u1")
        ) == 1

        rejected = client.post(
            "/api/research-os/settings/data_connector_field_mappings",
            json={
                "skill_id": "ingest:tushare:daily",
                "mapping_ref": "schema_map:tushare:daily",
                "schema_probe_ref": "schema_probe:tushare:daily:001",
                "source_to_canonical": {
                    "ts": "event_time",
                    "symbol": "instrument_id",
                    "adj_close": "close",
                },
                "event_time_column": "ts",
            },
        )
        assert rejected.status_code == 422
        assert "field_mapping_unknown_source_column" in rejected.json()["detail"]
        assert len(registry.data_connector_field_mappings(owner_user_id="u1")) == 1

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["data_connector_field_mapping_total"] == 1
        assert summary_body["data_connector_field_mappings"][0]["mapping_ref"] == "schema_map:tushare:daily"
        assert summary_body["data_connector_field_mappings"][0]["event_time_column"] == "ts"
        assert summary_body["data_connector_pit_bitemporal_rule_total"] == 1
        assert summary_body["data_connector_pit_bitemporal_rules"][0]["rule_ref"] == "pit:tushare:daily"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_default_data_connector_checker_records_disabled_failure(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", main.DisabledDataConnectorConnectionChecker())
    try:
        _seed_data_connector_settings(client)
        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert checked.status_code == 200, checked.text
        body = checked.json()
        assert body["ok"] is False
        assert body["status"] == "disabled"
        assert body["health_status"] == "disabled"
        assert body["error_code"] == "checker_disabled"
        assert len(registry.data_connector_checks(owner_user_id="u1")) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_revoked_secret_before_data_connector_checker_call(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)

    class ShouldNotCallChecker:
        checker_ref = "should_not_call"

        def __init__(self):
            self.calls = 0

        def check_connection(self, **_kwargs):
            self.calls += 1
            return {"status": "ok", "health_status": "ok", "quota_status": "ok", "response_hash": "sha256:bad"}

    checker = ShouldNotCallChecker()
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", checker)
    try:
        revoked_secret = client.post(
            "/api/research-os/settings/secret_refs",
            json=_payload(_secret(status=SecretRefStatus.REVOKED, revoked_at="2026-06-27T00:00:00Z")),
        )
        assert revoked_secret.status_code == 200, revoked_secret.text
        source = client.post("/api/research-os/settings/data_sources", json=_payload(_data_source()))
        assert source.status_code == 200, source.text
        paused_skill = client.post(
            "/api/research-os/settings/ingestion_skills",
            json=_payload(_skill(lifecycle_state=IngestionLifecycleState.PAUSED)),
        )
        assert paused_skill.status_code == 200, paused_skill.text

        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert checked.status_code == 422
        assert "revoked SecretRef" in checked.json()["detail"]
        assert checker.calls == 0
        assert registry.data_connector_checks(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_plaintext_data_connector_payload_without_partial_write(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/settings/data_sources",
            json={
                "source_ref": "datasource:tushare",
                "license": "commercial",
                "rate_limit": "500/min",
                "retention_policy": "retain",
                "api_key": "sk-live-1234567890abcdef",
            },
        )
        assert rejected.status_code == 422
        assert "plaintext credential" in rejected.json()["detail"]
        assert registry.data_sources(owner_user_id="u1") == []
        assert not registry.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_plaintext_checker_result_without_partial_write(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)

    class LeakyChecker:
        checker_ref = "leaky_checker"

        def check_connection(self, **_kwargs):
            return {
                "check_ref": "connector_check:leaky",
                "status": "ok",
                "health_status": "ok",
                "quota_status": "ok",
                "response_hash": "sk-live-1234567890abcdef",
            }

    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", LeakyChecker())
    try:
        _seed_data_connector_settings(client)
        checked = client.post(
            "/api/research-os/settings/data_connector_checks",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert checked.status_code == 422
        assert "plaintext credential" in checked.json()["detail"]
        assert registry.data_connector_checks(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def _ingestion_update_payload(version, **overrides):
    data = {
        "update_ref": "ingestion_update:tushare:daily:001",
        "skill_ref": "ingest:tushare:daily",
        "skill_version": "1",
        "source_ref": "datasource:tushare",
        "secret_ref": "secretref:tushare:read",
        "dataset_version_ref": _dataset_version_ref(version),
        "checksum": version.sha256,
        "lineage_ref": "lineage:tushare:daily:001",
        "quality_verdict_ref": "quality:tushare:daily:pass",
        "known_at_ref": "known_at:ingest_time",
        "effective_at_ref": "effective_at:trade_date",
        "freshness_status": "fresh",
        "schema_drift_status": "none",
        "row_count": version.row_count,
        "evidence_refs": ["connector_check:tushare:ok"],
    }
    data.update(overrides)
    return data


def test_settings_api_records_ingestion_skill_update_against_dataset_version(tmp_path, monkeypatch):
    client, _registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    version = _register_dataset_version(datasets)
    try:
        _seed_data_connector_settings(client)
        recorded = client.post(
            "/api/research-os/settings/ingestion_skill_updates",
            json=_ingestion_update_payload(version, recorded_by="spoofed-owner"),
        )
        assert recorded.status_code == 200, recorded.text
        body = recorded.json()
        assert body["update_ref"] == "ingestion_update:tushare:daily:001"
        assert body["dataset_version_ref"] == _dataset_version_ref(version)
        assert body["checksum"] == version.sha256
        assert body["recorded_by"] == "u1"

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        assert summary.json()["ingestion_skill_update_total"] == 1
        assert summary.json()["ingestion_skill_updates"][0]["known_at_ref"] == "known_at:ingest_time"
        assert len(lifecycle.ingestion_skill_updates(owner_user_id="u1")) == 1
        assert "sk-" not in summary.text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_ingestion_skill_update_unknown_dataset_version_without_write(tmp_path, monkeypatch):
    client, _registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    version = _register_dataset_version(datasets)
    try:
        _seed_data_connector_settings(client)
        rejected = client.post(
            "/api/research-os/settings/ingestion_skill_updates",
            json=_ingestion_update_payload(version, dataset_version_ref="dataset_version:missing"),
        )
        assert rejected.status_code == 422
        assert "not recorded" in rejected.json()["detail"]
        assert lifecycle.ingestion_skill_updates(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_ingestion_skill_update_checksum_mismatch_without_write(tmp_path, monkeypatch):
    client, _registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    version = _register_dataset_version(datasets)
    try:
        _seed_data_connector_settings(client)
        rejected = client.post(
            "/api/research-os/settings/ingestion_skill_updates",
            json=_ingestion_update_payload(version, checksum="sha256:wrong"),
        )
        assert rejected.status_code == 422
        assert "checksum" in rejected.json()["detail"]
        assert lifecycle.ingestion_skill_updates(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_runs_ingestion_skill_into_dataset_version_and_update(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    market_data = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    graph = main.RESEARCH_GRAPH_STORE
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market_data)

    class FakeRunner:
        runner_ref = "fake_ingestion_runner"

        def __init__(self):
            self.calls = []

        def run_ingestion(self, *, skill, source, secrets, connector_check, request, actor):
            self.calls.append((skill.skill_id, source.source_ref, connector_check.check_ref, actor, request["skill_id"]))
            return {
                "fetch_result": _runner_fetch_result(),
                "schema_probe_ref": "schema_probe:tushare:daily:run",
                "lineage_ref": "lineage:tushare:daily:run",
                "quality_verdict_ref": "quality:tushare:daily:pass",
                "known_at_ref": "known_at:ingest_time",
                "effective_at_ref": "effective_at:trade_date",
                "freshness_status": "fresh",
                "evidence_refs": ["runner:evidence:001"],
            }

    runner = FakeRunner()
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", runner)
    try:
        _seed_data_connector_settings(client)
        _seed_ok_connector_check(registry, check_ref="connector_check:tushare:ok")

        response = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:tushare:daily", "connector_check_ref": "connector_check:tushare:ok"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["skill_id"] == "ingest:tushare:daily"
        assert body["connector_check_ref"] == "connector_check:tushare:ok"
        assert body["dataset_id"] == "dataset:cn_equity_daily"
        assert body["row_count"] == 2
        assert body["schema_probe_ref"] == "schema_probe:tushare:daily:run"
        assert body["quality_verdict_ref"] == "quality:tushare:daily:pass"
        assert "sk-" not in response.text
        assert runner.calls == [
            ("ingest:tushare:daily", "datasource:tushare", "connector_check:tushare:ok", "u1", "ingest:tushare:daily")
        ]

        versions = datasets.list_versions("dataset:cn_equity_daily")
        assert len(versions) == 1
        assert body["dataset_version_ref"] == _dataset_version_ref(versions[0])
        assert versions[0].sha256 == body["checksum"]
        assert versions[0].metadata["connector_check_ref"] == "connector_check:tushare:ok"
        assert versions[0].metadata["schema_probe_ref"] == "schema_probe:tushare:daily:run"
        assert versions[0].metadata["schema_drift_status"] == "none"
        assert len(versions[0].file_paths) == 1
        assert versions[0].file_paths[0].endswith(".parquet")
        assert pl.read_parquet(versions[0].file_paths[0]).height == 2

        probes = registry.data_connector_schema_probes(owner_user_id="u1")
        assert len(probes) == 1
        assert probes[0].probe_ref == "schema_probe:tushare:daily:run"
        assert probes[0].dataset_version_ref == body["dataset_version_ref"]
        assert probes[0].schema_signature_hash.startswith("schema_signature:")
        assert probes[0].drift_status == "none"

        updates = lifecycle.ingestion_skill_updates(owner_user_id="u1")
        assert len(updates) == 1
        assert updates[0].dataset_version_ref == body["dataset_version_ref"]
        assert updates[0].checksum == body["checksum"]
        assert updates[0].evidence_refs[:3] == (
            "connector_check:tushare:ok",
            "schema_probe:tushare:daily:run",
            f"dataset_file:{body['checksum']}",
        )

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        assert summary.json()["data_connector_schema_probe_total"] == 1
        assert summary.json()["data_connector_schema_probes"][0]["probe_ref"] == "schema_probe:tushare:daily:run"

        missing_rule = client.post(
            "/api/research-os/settings/dataset_semantics",
            json={"skill_id": "ingest:tushare:daily", "update_ref": updates[0].update_ref},
        )
        assert missing_rule.status_code == 422
        assert market_data.datasets(owner_user_id="u1") == []
        missing_dataset_instrument = client.post(
            "/api/research-os/settings/instrument_specs",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert missing_dataset_instrument.status_code == 422
        assert market_data.instruments(owner_user_id="u1") == []
        assert graph.commands() == []

        mapping = client.post(
            "/api/research-os/settings/data_connector_field_mappings",
            json={
                "skill_id": "ingest:tushare:daily",
                "schema_probe_ref": "schema_probe:tushare:daily:run",
                "source_to_canonical": {
                    "ts": "event_time",
                    "symbol": "instrument_id",
                    "close": "close",
                },
                "event_time_column": "ts",
                "known_at_column": "ts",
                "effective_at_column": "ts",
                "symbol_column": "symbol",
            },
        )
        assert mapping.status_code == 200, mapping.text
        pit = client.post(
            "/api/research-os/settings/pit_bitemporal_rules",
            json={"skill_id": "ingest:tushare:daily", "field_mapping_ref": "schema_map:tushare:daily"},
        )
        assert pit.status_code == 200, pit.text

        semantics = client.post(
            "/api/research-os/settings/dataset_semantics",
            json={"skill_id": "ingest:tushare:daily", "update_ref": updates[0].update_ref},
        )
        assert semantics.status_code == 200, semantics.text
        semantics_body = semantics.json()
        assert semantics_body["dataset_ref"] == body["dataset_version_ref"]
        assert semantics_body["dataset_version_ref"] == body["dataset_version_ref"]
        assert semantics_body["pit_bitemporal_rules_ref"] == "pit:tushare:daily"
        assert semantics_body["use_context"] == "confirmatory_validation"
        assert semantics_body["raw_data_stored"] is False
        assert semantics_body["connector_called"] is False
        assert len(market_data.datasets(owner_user_id="u1")) == 1
        dataset = market_data.datasets(owner_user_id="u1")[0]
        assert dataset.known_at_ref == "known_at:ingest_time"
        assert dataset.effective_at_ref == "effective_at:trade_date"
        assert dataset.pit_bitemporal_rules_ref == "pit:tushare:daily"
        assert dataset.checksum == body["checksum"]
        assert graph.commands()
        assert semantics_body["qro_id"].startswith("qro_")
        assert graph.commands()[-1].command_type == "upsert_qro"
        qro_type = graph.commands()[-1].payload["qro"].qro_type
        assert getattr(qro_type, "value", qro_type) == "Dataset"
        _assert_compiler_coverage(
            semantics_body,
            entrypoint_ref="api:research_os.settings.dataset_semantics",
        )

        instrument = client.post(
            "/api/research-os/settings/instrument_specs",
            json={"skill_id": "ingest:tushare:daily", "dataset_ref": semantics_body["dataset_ref"]},
        )
        assert instrument.status_code == 200, instrument.text
        instrument_body = instrument.json()
        assert instrument_body["instrument_ref"] == "instrument:ingest:tushare:daily:cn_equity:equity"
        assert instrument_body["asset_class"] == "cn_equity"
        assert instrument_body["instrument_type"] == "equity"
        assert instrument_body["currency"] == "CNY"
        assert instrument_body["dataset_ref"] == semantics_body["dataset_ref"]
        assert instrument_body["raw_data_stored"] is False
        assert instrument_body["connector_called"] is False
        assert instrument_body["venue_called"] is False
        assert len(market_data.instruments(owner_user_id="u1")) == 1
        assert market_data.instruments(owner_user_id="u1")[0].exchange_calendar_ref == "calendar:datasource:tushare:default"
        assert market_data.instruments(owner_user_id="u1")[0].symbol_mapping_ref == "schema_map:tushare:daily"
        qro_type = graph.commands()[-1].payload["qro"].qro_type
        assert getattr(qro_type, "value", qro_type) == "DataSourceAsset"
        _assert_compiler_coverage(
            instrument_body,
            entrypoint_ref="api:research_os.settings.instrument_specs",
        )

        live_capability = client.post(
            "/api/research-os/settings/capability_matrices",
            json={
                "skill_id": "ingest:tushare:daily",
                "instrument_ref": instrument_body["instrument_ref"],
                "dataset_ref": semantics_body["dataset_ref"],
                "use_context": "live",
                "live": True,
            },
        )
        assert live_capability.status_code == 422
        assert market_data.capability_matrices(owner_user_id="u1") == []
        missing_capability_use = client.post(
            "/api/research-os/settings/market_data_use_validations",
            json={
                "skill_id": "ingest:tushare:daily",
                "dataset_ref": semantics_body["dataset_ref"],
                "instrument_ref": instrument_body["instrument_ref"],
            },
        )
        assert missing_capability_use.status_code == 422
        assert market_data.use_validations(owner_user_id="u1") == []

        capability = client.post(
            "/api/research-os/settings/capability_matrices",
            json={
                "skill_id": "ingest:tushare:daily",
                "instrument_ref": instrument_body["instrument_ref"],
                "dataset_ref": semantics_body["dataset_ref"],
            },
        )
        assert capability.status_code == 200, capability.text
        capability_body = capability.json()
        assert capability_body["matrix_ref"] == "capability:ingest:tushare:daily:cn_equity:equity"
        assert capability_body["dataset_ref"] == semantics_body["dataset_ref"]
        assert capability_body["instrument_ref"] == instrument_body["instrument_ref"]
        assert capability_body["use_context"] == "confirmatory_validation"
        assert capability_body["raw_data_stored"] is False
        assert capability_body["connector_called"] is False
        assert capability_body["venue_called"] is False
        assert len(market_data.capability_matrices(owner_user_id="u1")) == 1
        assert market_data.capability_matrices(owner_user_id="u1")[0].data_availability == semantics_body["dataset_ref"]
        assert market_data.capability_matrices(owner_user_id="u1")[0].live is False
        qro_type = graph.commands()[-1].payload["qro"].qro_type
        assert getattr(qro_type, "value", qro_type) == "MarketCapabilityMatrix"
        _assert_compiler_coverage(
            capability_body,
            entrypoint_ref="api:research_os.settings.capability_matrices",
        )

        use_validation = client.post(
            "/api/research-os/settings/market_data_use_validations",
            json={
                "skill_id": "ingest:tushare:daily",
                "dataset_ref": semantics_body["dataset_ref"],
                "instrument_ref": instrument_body["instrument_ref"],
                "capability_matrix_ref": capability_body["matrix_ref"],
                "use_context": "confirmatory_validation",
            },
        )
        assert use_validation.status_code == 200, use_validation.text
        use_body = use_validation.json()
        assert use_body["accepted"] is True
        assert use_body["use_context"] == "confirmatory_validation"
        assert use_body["raw_data_stored"] is False
        assert use_body["connector_called"] is False
        assert use_body["strategy_builder_called"] is False
        assert use_body["venue_called"] is False
        assert len(market_data.use_validations(owner_user_id="u1")) == 1
        recorded_use = market_data.use_validations(owner_user_id="u1")[0]
        assert recorded_use.dataset_refs == (semantics_body["dataset_ref"],)
        assert recorded_use.instrument_refs == (instrument_body["instrument_ref"],)
        assert recorded_use.capability_matrix_ref == capability_body["matrix_ref"]
        qro_type = graph.commands()[-1].payload["qro"].qro_type
        assert getattr(qro_type, "value", qro_type) == "MarketCapabilityMatrix"
        assert graph.commands()[-1].payload["qro"].output_contract["status"] == "market_data_use_validated"
        assert use_body["compiler_ir_ref"].startswith("compiler_ir:")
        assert use_body["compiler_pass_ref"].startswith("compiler_pass:")
        assert use_body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
        ir = main.COMPILER_IR_STORE.ir(use_body["compiler_ir_ref"])
        compiler_pass = main.COMPILER_IR_STORE.compiler_pass(use_body["compiler_pass_ref"])
        coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(use_body["entrypoint_coverage_ref"])
        assert ir.source_qro_refs == (use_body["qro_id"],)
        assert compiler_pass.input_qro_refs == (use_body["qro_id"],)
        assert coverage.entrypoint_ref == "api:research_os.settings.market_data_use_validations"
        assert coverage.qro_refs == (use_body["qro_id"],)
        assert coverage.research_graph_command_refs == (use_body["research_graph_command_id"],)
        assert coverage.compiler_ir_refs == (use_body["compiler_ir_ref"],)
        assert coverage.compiler_pass_refs == (use_body["compiler_pass_ref"],)
        compiled_text = f"{ir.__dict__} {compiler_pass.__dict__} {coverage.__dict__}"
        assert "000001.SZ" not in compiled_text
        assert "10.5" not in compiled_text
        assert "sk-" not in compiled_text

        bad_semantics = client.post(
            "/api/research-os/settings/dataset_semantics",
            json={"skill_id": "ingest:tushare:daily", "update_ref": "ingestion_update:missing"},
        )
        assert bad_semantics.status_code == 422
        assert len(market_data.datasets(owner_user_id="u1")) == 1
        assert len(market_data.instruments(owner_user_id="u1")) == 1
        assert len(market_data.capability_matrices(owner_user_id="u1")) == 1
        assert len(market_data.use_validations(owner_user_id="u1")) == 1

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        assert summary.json()["market_data_dataset_total"] == 1
        assert summary.json()["market_data_instrument_total"] == 1
        assert summary.json()["market_data_capability_matrix_total"] == 1
        assert summary.json()["market_data_use_validation_total"] == 1
        assert summary.json()["market_data_datasets"][0]["dataset_ref"] == body["dataset_version_ref"]
        assert summary.json()["market_data_instruments"][0]["instrument_ref"] == instrument_body["instrument_ref"]
        assert summary.json()["market_data_capability_matrices"][0]["matrix_ref"] == capability_body["matrix_ref"]
        assert summary.json()["market_data_use_validations"][0]["validation_ref"] == use_body["validation_ref"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_runs_one_shot_data_connector_onboarding_into_market_data_use_gate(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    market_data = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    graph = main.RESEARCH_GRAPH_STORE
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market_data)

    class FakeChecker:
        checker_ref = "fake_data_connector_checker"

        def __init__(self):
            self.calls = []

        def check_connection(self, *, skill, source, secrets, actor):
            self.calls.append((skill.skill_id, source.source_ref, tuple(s.secret_ref for s in secrets), actor))
            return {
                "check_ref": "connector_check:tushare:ok",
                "status": "ok",
                "health_status": "ok",
                "quota_status": "ok",
                "capability_refs": ["capability:daily_bar"],
                "schema_probe_ref": "schema_probe:tushare:daily:check",
                "response_hash": "sha256:sanitized",
            }

    class FakeRunner:
        runner_ref = "fake_ingestion_runner"

        def __init__(self):
            self.calls = []

        def run_ingestion(self, *, skill, source, secrets, connector_check, request, actor):
            self.calls.append((skill.skill_id, source.source_ref, connector_check.check_ref, request["skill_id"], actor))
            return {
                "fetch_result": _runner_fetch_result(),
                "schema_probe_ref": "schema_probe:tushare:daily:run",
                "lineage_ref": "lineage:tushare:daily:run",
                "quality_verdict_ref": "quality:tushare:daily:pass",
                "known_at_ref": "known_at:ingest_time",
                "effective_at_ref": "effective_at:trade_date",
                "freshness_status": "fresh",
                "evidence_refs": ["runner:evidence:001"],
            }

    checker = FakeChecker()
    runner = FakeRunner()
    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", checker)
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", runner)
    try:
        _seed_data_connector_settings(client)
        response = client.post(
            "/api/research-os/settings/data_connector_onboarding_runs",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["skill_id"] == "ingest:tushare:daily"
        assert body["accepted"] is True
        assert body["completed_steps"] == [
            "connection_check",
            "ingestion_run",
            "field_mapping",
            "pit_bitemporal_rule",
            "dataset_semantics",
            "instrument_spec",
            "capability_matrix",
            "market_data_use",
            "compiler_coverage",
        ]
        assert body["connector_check_ref"] == "connector_check:tushare:ok"
        assert body["schema_probe_ref"] == "schema_probe:tushare:daily:run"
        assert body["mapping_ref"] == "schema_map:tushare:daily"
        assert body["mapping_method"] == "agent_suggested"
        assert body["pit_bitemporal_rules_ref"] == "pit:tushare:daily"
        assert body["dataset_ref"] == body["dataset_version_ref"]
        assert body["instrument_ref"] == "instrument:ingest:tushare:daily:cn_equity:equity"
        assert body["capability_matrix_ref"] == "capability:ingest:tushare:daily:cn_equity:equity"
        assert body["market_data_use_validation_ref"].startswith("market_data_use:")
        assert body["connector_called"] is True
        assert body["dataset_file_written"] is True
        assert body["strategy_builder_called"] is False
        assert body["venue_called"] is False
        assert body["compiler_ir_ref"].startswith("compiler_ir:")
        assert body["compiler_pass_ref"].startswith("compiler_pass:")
        assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
        assert body["step_outputs"]["market_data_use"]["entrypoint_coverage_ref"] == body["entrypoint_coverage_ref"]
        assert body["step_outputs"]["compiler_coverage"] == {
            "compiler_ir_ref": body["compiler_ir_ref"],
            "compiler_pass_ref": body["compiler_pass_ref"],
            "entrypoint_coverage_ref": body["entrypoint_coverage_ref"],
        }
        assert "sk-" not in response.text

        assert checker.calls == [("ingest:tushare:daily", "datasource:tushare", ("secretref:tushare:read",), "u1")]
        assert runner.calls == [
            ("ingest:tushare:daily", "datasource:tushare", "connector_check:tushare:ok", "ingest:tushare:daily", "u1")
        ]
        assert datasets.latest("dataset:cn_equity_daily").row_count == 2
        assert len(lifecycle.ingestion_skill_updates(owner_user_id="u1")) == 1
        assert len(registry.data_connector_schema_probes(owner_user_id="u1")) == 1
        assert registry.data_connector_field_mappings(owner_user_id="u1")[0].mapping_method == "agent_suggested"
        assert registry.data_connector_field_mappings(owner_user_id="u1")[0].source_to_canonical == {
            "ts": "event_time",
            "symbol": "instrument_id",
            "close": "close",
        }
        assert registry.data_connector_pit_bitemporal_rules(
            owner_user_id="u1"
        )[0].field_mapping_ref == "schema_map:tushare:daily"
        assert len(market_data.datasets(owner_user_id="u1")) == 1
        assert len(market_data.instruments(owner_user_id="u1")) == 1
        assert len(market_data.capability_matrices(owner_user_id="u1")) == 1
        assert len(market_data.use_validations(owner_user_id="u1")) == 1
        assert market_data.use_validations(owner_user_id="u1")[0].accepted is True
        assert graph.commands()[-1].payload["qro"].output_contract["status"] == "market_data_use_validated"
        qro_id = body["step_outputs"]["market_data_use"]["qro_id"]
        graph_command_id = body["step_outputs"]["market_data_use"]["research_graph_command_id"]
        direct_coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(
            body["step_outputs"]["market_data_use"]["entrypoint_coverage_ref"]
        )
        reused_coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
        assert direct_coverage.entrypoint_ref == "api:research_os.settings.market_data_use_validations"
        assert reused_coverage == direct_coverage
        assert direct_coverage.qro_refs == (qro_id,)
        assert reused_coverage.research_graph_command_refs == (graph_command_id,)
        subject_coverages = tuple(
            coverage
            for coverage in main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.canonical_records(
                owner="u1"
            )
            if coverage.qro_refs == (qro_id,)
            and coverage.research_graph_command_refs == (graph_command_id,)
        )
        assert subject_coverages == (direct_coverage,)
        top_ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
        top_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
        assert top_ir.source_qro_refs == (qro_id,)
        assert top_pass.input_qro_refs == (qro_id,)
        proof_ledger = main._registry_goal_proof_ledger(main.COMPILER_IR_STORE)
        assert proof_ledger is not None
        required_refs = {
            direct_coverage.validation_refs[0],
            direct_coverage.evidence_refs[0],
            top_ir.ir_ref,
            top_pass.pass_ref,
            direct_coverage.coverage_ref,
        }
        subject_heads = tuple(
            head
            for head in proof_ledger.current(owner="u1").heads
            if head.logical_ref in required_refs
        )
        assert {head.logical_ref for head in subject_heads} == required_refs
        assert len({head.bundle_id for head in subject_heads}) == 1
        compiled_text = f"{top_ir.__dict__} {top_pass.__dict__} {reused_coverage.__dict__}"
        assert "000001.SZ" not in compiled_text
        assert "10.5" not in compiled_text
        assert "sk-" not in compiled_text

        from app.agent import LLMMessage, LLMResponse, ensure_settings_managed_llm_provider
        from app.llm import (
            GatewayBackedLLMClient,
            PersistentLLMUseBindingStore,
            build_agent_llm_gateway,
        )
        from app.llm.call_record_store import LLMCallRecordStore
        from app.research_os import PersistentOnboardingReadinessRegistry
        from app.security import KeystoreRecord

        service_owner = main._LLM_SERVICE_PRINCIPAL
        now = datetime.now(UTC).isoformat()
        ensure_settings_managed_llm_provider(
            registry=registry,
            provider="openai",
            owner=service_owner,
            created_at=now,
        )
        registry.record_llm_provider_health_snapshot(
            _provider_health_snapshot(
                snapshot_ref="llm_health:openai:readiness",
                auth_ref="secretref:llm:openai",
                checked_at=now,
                recorded_by=service_owner,
            ),
            owner_user_id=service_owner,
        )
        call_store = LLMCallRecordStore(tmp_path / "llm_call_records.jsonl")
        binding_store = PersistentLLMUseBindingStore(
            tmp_path / "llm_gateway_use_bindings.jsonl",
            seal_secret=call_store.seal_secret,
            terminal_record_resolver=call_store.resolve_terminal_record,
        )
        keystore = SecureKeystore(InMemoryKeystore())
        keystore.store(
            KeystoreRecord(
                name="llm_openai",
                api_key="sk-test-only-readiness-key-0123456789",
                api_secret="sk-test-only-readiness-key-0123456789",
            )
        )

        class ReadinessLLM:
            def chat(self, messages, *, tools=None, model=None, temperature=0.2):
                return LLMResponse(content="readiness-ok")

        gateway = build_agent_llm_gateway(
            keystore,
            client_factory=lambda _credential: ReadinessLLM(),
            seal_secret=call_store.seal_secret,
            use_binding_sink=binding_store.append,
            service_principal_ref=service_owner,
            credential_pool_refs={"openai": "pool:llm:openai:default"},
            routing_policy_refs={"openai": "routing:llm:openai:default"},
        )
        llm_client = GatewayBackedLLMClient(
            gateway,
            session_id="readiness-workflow",
            owner_user_id="u1",
            workflow_id="readiness-workflow",
            invocation_id_factory=lambda: "readiness-invocation-1",
            record_sink=call_store.append,
        )
        assert llm_client.chat([LLMMessage(role="user", content="readiness check")]).content == "readiness-ok"
        terminal_call_ref = llm_client.last_record.call_id
        monkeypatch.setattr(main, "LLM_CALL_RECORD_STORE", call_store)
        monkeypatch.setattr(main, "LLM_USE_BINDING_STORE", binding_store)
        readiness_registry = PersistentOnboardingReadinessRegistry(
            tmp_path / "onboarding_readiness.jsonl",
            resolve_snapshot=main._resolve_onboarding_readiness_snapshot,
        )
        monkeypatch.setattr(main, "ONBOARDING_READINESS_REGISTRY", readiness_registry)

        readiness = client.post(
            "/api/research-os/goal/onboarding/readiness/current",
            json={
                "data_source_ref": "datasource:tushare",
                "routing_policy_ref": "routing:llm:openai:default",
                "terminal_call_ref": terminal_call_ref,
            },
        )
        assert readiness.status_code == 200, readiness.text
        readiness_body = readiness.json()
        assert readiness_body["receipt_ref"].startswith("onboarding_readiness_receipt:")
        assert readiness_body["component_count"] == 18
        assert readiness_body["terminal_call_ref"] == terminal_call_ref
        assert readiness_body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
        receipt = readiness_registry.receipt(
            readiness_body["receipt_ref"],
            owner_user_id="u1",
        )
        assert readiness_registry.validate_current(
            receipt.receipt_ref,
            owner_user_id="u1",
        ).accepted
        readiness_coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(
            readiness_body["entrypoint_coverage_ref"]
        )
        assert readiness_coverage.entrypoint_ref == "api:goal.onboarding.readiness"
        assert readiness_coverage.goal_sections == ("§4",)
        assert len(readiness_coverage.validation_refs) == 1
        goal_receipt = main.GOAL_VALIDATION_RECEIPT_REGISTRY.receipt(
            readiness_coverage.validation_refs[0],
            owner_user_id="u1",
        )
        assert goal_receipt.subject_qro_refs == (readiness_body["qro_id"],)
        assert receipt.receipt_ref in goal_receipt.evidence_refs

        extra_field = client.post(
            "/api/research-os/goal/onboarding/readiness/current",
            json={
                "data_source_ref": "datasource:tushare",
                "routing_policy_ref": "routing:llm:openai:default",
                "terminal_call_ref": terminal_call_ref,
                "caller_evidence": "must-not-be-accepted",
            },
        )
        assert extra_field.status_code == 422
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_no_secret_policy_drives_current_onboarding_readiness_and_revocation_stales_it(
    tmp_path,
    monkeypatch,
):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    _lifecycle, _datasets = _install_lifecycle_and_dataset_registries(
        tmp_path, monkeypatch
    )
    market_data = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    graph = main.RESEARCH_GRAPH_STORE
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market_data)

    class FakeChecker:
        checker_ref = "fake_public_csv_checker"

        def check_connection(self, *, skill, source, secrets, actor):
            assert secrets == ()
            return {
                "check_ref": "connector_check:stooq:ok",
                "status": "ok",
                "health_status": "ok",
                "quota_status": "ok",
                "capability_refs": ["capability:daily_bar"],
                "schema_probe_ref": "schema_probe:stooq:daily:check",
                "response_hash": "sha256:sanitized-public-check",
            }

    class FakeRunner:
        runner_ref = "fake_public_csv_runner"

        def run_ingestion(
            self, *, skill, source, secrets, connector_check, request, actor
        ):
            assert secrets == ()
            return {
                "fetch_result": _runner_fetch_result(),
                "connector_name": "stooq",
                "schema_probe_ref": "schema_probe:stooq:daily:run",
                "lineage_ref": "lineage:stooq:daily:run",
                "quality_verdict_ref": "quality:stooq:daily:pass",
                "known_at_ref": "known_at:stooq:ingest-time",
                "effective_at_ref": "effective_at:stooq:trade-date",
                "freshness_status": "fresh",
                "evidence_refs": ["runner:evidence:stooq:001"],
            }

    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", FakeChecker())
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", FakeRunner())
    try:
        source = client.post(
            "/api/research-os/settings/data_sources",
            json=_payload(_stooq_source()),
        )
        assert source.status_code == 200, source.text
        policy = client.post(
            "/api/research-os/settings/no_secret_data_source_policies",
            json={
                "policy_ref": "no_secret_policy:stooq:readiness",
                "source_ref": "datasource:stooq:public",
                "source_type": "public_csv",
                "connector_type": "public_csv_no_auth",
                "external_credential_required": False,
                "permission_scope": "market_data:read",
                "approved_at": "2026-07-12T20:00:00Z",
                "approval_ref": "approval:no-secret:stooq:readiness",
                "evidence_refs": [
                    "evidence:stooq:public-docs",
                    "evidence:stooq:anonymous-health-check",
                ],
                "reason": "Public daily CSV is explicitly approved for anonymous read-only use.",
            },
        )
        assert policy.status_code == 200, policy.text
        skill = client.post(
            "/api/research-os/settings/ingestion_skills",
            json=_payload(_stooq_skill()),
        )
        assert skill.status_code == 200, skill.text

        onboarding = client.post(
            "/api/research-os/settings/data_connector_onboarding_runs",
            json={"skill_id": "ingest:stooq:aapl:daily"},
        )
        assert onboarding.status_code == 200, onboarding.text
        assert onboarding.json()["accepted"] is True

        terminal_call_ref, readiness_registry = _install_readiness_llm_chain(
            tmp_path,
            monkeypatch,
            registry,
            suffix="no-secret",
        )
        readiness = client.post(
            "/api/research-os/goal/onboarding/readiness/current",
            json={
                "data_source_ref": "datasource:stooq:public",
                "routing_policy_ref": "routing:llm:openai:default",
                "terminal_call_ref": terminal_call_ref,
            },
        )
        assert readiness.status_code == 200, readiness.text
        receipt = readiness_registry.receipt(
            readiness.json()["receipt_ref"],
            owner_user_id="u1",
        )
        assert receipt.snapshot.credential_mode == "no_secret_policy"
        assert (
            receipt.snapshot.secret_or_no_secret_policy.component_ref
            == "no_secret_policy:stooq:readiness"
        )
        assert readiness_registry.validate_current(
            receipt.receipt_ref,
            owner_user_id="u1",
        ).accepted

        policy_body = policy.json()
        revoked = client.post(
            "/api/research-os/settings/no_secret_data_source_policies/"
            "no_secret_policy:stooq:readiness/revoke",
            json={
                "expected_previous_revision": policy_body["record_revision"],
                "expected_previous_hash": policy_body["record_hash"],
                "revoked_at": "2026-07-12T21:00:00Z",
                "revocation_reason": "Provider documentation now requires authentication.",
                "revocation_evidence_refs": ["evidence:stooq:auth-change"],
            },
        )
        assert revoked.status_code == 200, revoked.text
        assert not readiness_registry.validate_current(
            receipt.receipt_ref,
            owner_user_id="u1",
        ).accepted
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_one_shot_data_connector_onboarding_stops_before_market_data_records_on_bad_mapping(
    tmp_path,
    monkeypatch,
):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    market_data = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    graph = main.RESEARCH_GRAPH_STORE
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market_data)

    class FakeChecker:
        checker_ref = "fake_data_connector_checker"

        def check_connection(self, *, skill, source, secrets, actor):
            return {
                "check_ref": "connector_check:tushare:ok",
                "status": "ok",
                "health_status": "ok",
                "quota_status": "ok",
                "capability_refs": ["capability:daily_bar"],
                "schema_probe_ref": "schema_probe:tushare:daily:check",
                "response_hash": "sha256:sanitized",
            }

    class FakeRunner:
        runner_ref = "fake_ingestion_runner"

        def run_ingestion(self, *, skill, source, secrets, connector_check, request, actor):
            return {
                "fetch_result": _runner_fetch_result(),
                "schema_probe_ref": "schema_probe:tushare:daily:run",
                "lineage_ref": "lineage:tushare:daily:run",
                "quality_verdict_ref": "quality:tushare:daily:pass",
                "known_at_ref": "known_at:ingest_time",
                "effective_at_ref": "effective_at:trade_date",
                "freshness_status": "fresh",
            }

    monkeypatch.setattr(main, "DATA_CONNECTOR_CONNECTION_CHECKER", FakeChecker())
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", FakeRunner())
    try:
        _seed_data_connector_settings(client)
        response = client.post(
            "/api/research-os/settings/data_connector_onboarding_runs",
            json={
                "skill_id": "ingest:tushare:daily",
                "field_mapping": {
                    "source_to_canonical": {"missing_ts": "event_time"},
                    "event_time_column": "missing_ts",
                },
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["failed_step"] == "field_mapping"
        assert detail["completed_steps"] == ["connection_check", "ingestion_run"]
        assert "field_mapping_unknown_source_column" in str(detail["error"])
        assert "sk-" not in response.text

        assert len(registry.data_connector_checks(owner_user_id="u1")) == 1
        assert len(registry.data_connector_schema_probes(owner_user_id="u1")) == 1
        assert len(lifecycle.ingestion_skill_updates(owner_user_id="u1")) == 1
        assert datasets.latest("dataset:cn_equity_daily").row_count == 2
        assert registry.data_connector_field_mappings(owner_user_id="u1") == []
        assert registry.data_connector_pit_bitemporal_rules(owner_user_id="u1") == []
        assert market_data.datasets(owner_user_id="u1") == []
        assert market_data.instruments(owner_user_id="u1") == []
        assert market_data.capability_matrices(owner_user_id="u1") == []
        assert market_data.use_validations(owner_user_id="u1") == []
        assert graph.commands() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_ingestion_run_requires_ok_connector_check_before_runner_call(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)

    class ShouldNotRun:
        def __init__(self):
            self.calls = 0

        def run_ingestion(self, **_kwargs):
            self.calls += 1
            return {"fetch_result": _runner_fetch_result()}

    runner = ShouldNotRun()
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", runner)
    try:
        _seed_data_connector_settings(client)
        rejected = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert rejected.status_code == 422
        assert "ok DataConnectorConnectionCheck" in rejected.json()["detail"]
        assert runner.calls == 0
        assert datasets.list_versions() == []
        assert lifecycle.ingestion_skill_updates(owner_user_id="u1") == []
        assert registry.data_connector_checks(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_default_ingestion_runner_does_not_write_dataset_or_update(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", main.DisabledDataConnectorIngestionRunner())
    try:
        _seed_data_connector_settings(client)
        _seed_ok_connector_check(registry, check_ref="connector_check:tushare:ok")

        rejected = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:tushare:daily", "connector_check_ref": "connector_check:tushare:ok"},
        )
        assert rejected.status_code == 422
        assert "ingestion runner disabled" in rejected.json()["detail"]
        assert datasets.list_versions() == []
        assert lifecycle.ingestion_skill_updates(owner_user_id="u1") == []
        assert not (tmp_path / "datasets" / "ingestion").exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_ingestion_runner_checksum_mismatch_without_write(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)

    class BadChecksumRunner:
        def run_ingestion(self, **_kwargs):
            result = _runner_fetch_result()
            result.sha256 = "sha256:wrong"
            return {"fetch_result": result}

    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", BadChecksumRunner())
    try:
        _seed_data_connector_settings(client)
        _seed_ok_connector_check(registry, check_ref="connector_check:tushare:ok")
        rejected = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:tushare:daily", "connector_check_ref": "connector_check:tushare:ok"},
        )
        assert rejected.status_code == 422
        assert "sha256" in rejected.json()["detail"]
        assert datasets.list_versions() == []
        assert lifecycle.ingestion_skill_updates(owner_user_id="u1") == []
        assert not (tmp_path / "datasets" / "ingestion").exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_rejects_ingestion_runner_plaintext_frame_without_write(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)

    class LeakyFrameRunner:
        def run_ingestion(self, **_kwargs):
            return {
                "fetch_result": _runner_fetch_result(
                    pl.DataFrame(
                        {
                            "ts": ["2026-06-27T00:00:00Z"],
                            "symbol": ["000001.SZ"],
                            "note": ["api_key=sk-live-1234567890abcdef"],
                        }
                    )
                )
            }

    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", LeakyFrameRunner())
    try:
        _seed_data_connector_settings(client)
        _seed_ok_connector_check(registry, check_ref="connector_check:tushare:ok")
        rejected = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:tushare:daily", "connector_check_ref": "connector_check:tushare:ok"},
        )
        assert rejected.status_code == 422
        assert "plaintext credential" in rejected.json()["detail"]
        assert datasets.list_versions() == []
        assert lifecycle.ingestion_skill_updates(owner_user_id="u1") == []
        assert not (tmp_path / "datasets" / "ingestion").exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_ingestion_run_blocks_schema_drift_without_event_or_impact_refs(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)

    class DriftRunner:
        def __init__(self):
            self.calls = 0

        def run_ingestion(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "fetch_result": _runner_fetch_result(),
                    "schema_probe_ref": "schema_probe:tushare:daily:v1",
                }
            return {
                "fetch_result": _runner_fetch_result(
                    pl.DataFrame(
                        {
                            "ts": ["2026-06-28T00:00:00Z"],
                            "symbol": ["000001.SZ"],
                            "close": [10.8],
                            "turnover": [123.0],
                        }
                    )
                ),
                "schema_probe_ref": "schema_probe:tushare:daily:v2",
            }

    monkeypatch.setattr(main, "DATA_CONNECTOR_INGESTION_RUNNER", DriftRunner())
    try:
        _seed_data_connector_settings(client)
        _seed_ok_connector_check(registry, check_ref="connector_check:tushare:ok")

        first = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:tushare:daily", "connector_check_ref": "connector_check:tushare:ok"},
        )
        assert first.status_code == 200, first.text
        first_file_paths = datasets.list_versions("dataset:cn_equity_daily")[0].file_paths

        second = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:tushare:daily", "connector_check_ref": "connector_check:tushare:ok"},
        )
        assert second.status_code == 422
        assert "schema_drift_missing_event_or_impact" in second.json()["detail"]
        assert len(datasets.list_versions("dataset:cn_equity_daily")) == 1
        assert len(lifecycle.ingestion_skill_updates(owner_user_id="u1")) == 1
        assert len(registry.data_connector_schema_probes(owner_user_id="u1")) == 1
        assert not (tmp_path / "datasets" / "ingestion" / "dataset_cn_equity_daily").joinpath(
            "schema_probe_tushare_daily_v2.parquet"
        ).exists()
        assert datasets.list_versions("dataset:cn_equity_daily")[0].file_paths == first_file_paths
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
