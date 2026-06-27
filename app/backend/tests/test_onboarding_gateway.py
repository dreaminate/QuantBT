from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
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
    PersistentGoalEntrypointCoverageRegistry,
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


def _client_with_onboarding_registry(tmp_path, monkeypatch):
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    monkeypatch.setattr(main, "ONBOARDING_REGISTRY", registry)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", PersistentResearchGraphStore(tmp_path / "research_graph.jsonl"))
    monkeypatch.setattr(main, "COMPILER_IR_STORE", PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl"))
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl"),
    )
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
    return registry.record_data_connector_check(_connector_check(**overrides))


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
    registry.record_secret_ref(secret)
    registry.record_llm_provider(_provider())
    registry.record_llm_provider_health_snapshot(_provider_health_snapshot())
    registry.record_credential_pool(_pool())
    registry.record_routing_policy(_policy())

    reloaded = PersistentOnboardingRegistry(path)
    assert reloaded.secret_ref("secretref:openai:project").scope == "llm:openai"
    assert reloaded.llm_provider("openai").auth_refs == ("secretref:openai:project",)
    assert reloaded.llm_provider_health_snapshot("llm_health:openai:001").snapshot_hash.startswith("sha16:")
    assert reloaded.llm_provider_health_snapshots("openai")[0].quota_status == "ok"
    assert reloaded.credential_pool("pool:openai:research").provider_id == "openai"
    assert reloaded.routing_policy("routing:researcher:strategy").allowed_models == ("gpt-5.5",)


def test_persistent_onboarding_registry_replays_data_connector_records(tmp_path):
    path = tmp_path / "onboarding_settings.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_secret_ref(_secret())
    registry.record_data_source_asset(_data_source())
    registry.record_ingestion_skill(_skill())
    registry.record_data_connector_check(_connector_check())
    registry.record_data_connector_schema_probe(_schema_probe())
    registry.record_data_connector_field_mapping(_field_mapping())
    registry.record_data_connector_pit_bitemporal_rule(_pit_rule())

    reloaded = PersistentOnboardingRegistry(path)
    assert reloaded.data_source("datasource:tushare").license == "commercial:user-provided"
    assert reloaded.ingestion_skill("ingest:tushare:daily").secret_refs == ("secretref:tushare:read",)
    assert reloaded.data_connector_check("connector_check:tushare:001").health_status == "ok"
    assert reloaded.data_connector_schema_probe("schema_probe:tushare:daily:001").columns == ("ts", "symbol", "close")
    assert reloaded.data_connector_field_mapping("schema_map:tushare:daily").source_to_canonical["close"] == "close"
    assert reloaded.data_connector_pit_bitemporal_rule("pit:tushare:daily").asof_join_policy == "known_at_lte_decision_time_latest"


def test_persistent_onboarding_registry_rejects_provider_for_unrecorded_secret(tmp_path):
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")

    with pytest.raises(ValueError, match="auth_ref"):
        registry.record_llm_provider(_provider())

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
    registry.record_secret_ref(_secret(secret_ref="secretref:openai:project", scope="llm:openai"))

    with pytest.raises(ValueError, match="provider_id"):
        registry.record_llm_provider_health_snapshot(_provider_health_snapshot())

    registry.record_llm_provider(_provider())
    with pytest.raises(ValueError, match="not recorded for provider"):
        registry.record_llm_provider_health_snapshot(_provider_health_snapshot(auth_ref="secretref:anthropic:project"))


def test_settings_api_records_llm_routing_summary_without_plaintext_secret(tmp_path, monkeypatch):
    client, _registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    try:
        secret = client.post(
            "/api/research-os/settings/secret_refs",
            json=_payload(_secret(secret_ref="secretref:openai:project", scope="llm:openai")),
        )
        assert secret.status_code == 200, secret.text
        assert secret.json() == {"secret_ref": "secretref:openai:project", "recorded_by": "u1"}

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

        assert registry.llm_provider_health_snapshots() == []
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
        assert registry.secret_refs() == []
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
            "keystore_ref": "tushare",
            "keystore_backend": "memory",
            "secret_value_stored": True,
            "recorded_by": "u1",
        }
        assert secret_value not in stored.text
        assert keystore.fetch("tushare").api_key == secret_value
        assert keystore.fetch("tushare").api_secret == secret_value
        recorded = registry.secret_ref("secretref:tushare:read")
        assert recorded.access_audit == ("keystore:tushare",)
        assert recorded.affected_skills == ("ingest:tushare:daily",)

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["secret_ref_total"] == 1
        assert summary_body["secret_refs"][0]["secret_ref"] == "secretref:tushare:read"
        assert summary_body["secret_refs"][0]["keystore_refs"] == ["tushare"]
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
        assert checker.calls == [("ingest:tushare:daily", "datasource:tushare", "tushare", "u1")]
        assert len(registry.data_connector_checks()) == 1
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
        assert registry.data_connector_checks() == []
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
        assert len(registry.data_connector_schema_probes()) == 1
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
        assert registry.data_connector_checks()[0].secret_refs == ()
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
        assert len(registry.data_connector_schema_probes()) == 1
        updates = lifecycle.ingestion_skill_updates()
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
        assert registry.data_connector_checks()[0].secret_refs == ()
        assert "api_key" not in checked.text
        assert "token=" not in checked.text.lower()
        assert "sk-live" not in checked.text
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
        assert len(registry.data_connector_schema_probes()) == 1
        updates = lifecycle.ingestion_skill_updates()
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
        assert registry.data_connector_checks()[0].secret_refs == ()

        run = client.post(
            "/api/research-os/settings/ingestion_skill_runs",
            json={"skill_id": "ingest:custom:bars", "connector_check_ref": check_body["check_ref"]},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["dataset_id"] == "dataset:custom_bars"
        assert body["row_count"] == 2
        assert datasets.latest("dataset:custom_bars").row_count == 2
        assert len(registry.data_connector_schema_probes()) == 1
        updates = lifecycle.ingestion_skill_updates()
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
        assert len(registry.data_connector_checks()) == 1
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
        assert len(registry.data_connector_checks()) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_records_field_mapping_after_schema_probe_without_partial_write(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    try:
        _seed_data_connector_settings(client)
        registry.record_data_connector_check(_connector_check())
        registry.record_data_connector_schema_probe(_schema_probe())

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
        assert len(registry.data_connector_pit_bitemporal_rules()) == 1

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
        assert len(registry.data_connector_field_mappings()) == 1

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
        assert len(registry.data_connector_checks()) == 1
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
        assert registry.data_connector_checks() == []
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
        assert registry.data_sources() == []
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
        assert registry.data_connector_checks() == []
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
            json=_ingestion_update_payload(version),
        )
        assert recorded.status_code == 200, recorded.text
        body = recorded.json()
        assert body["update_ref"] == "ingestion_update:tushare:daily:001"
        assert body["dataset_version_ref"] == _dataset_version_ref(version)
        assert body["checksum"] == version.sha256

        summary = client.get("/api/research-os/settings/summary")
        assert summary.status_code == 200
        assert summary.json()["ingestion_skill_update_total"] == 1
        assert summary.json()["ingestion_skill_updates"][0]["known_at_ref"] == "known_at:ingest_time"
        assert len(lifecycle.ingestion_skill_updates()) == 1
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
        assert lifecycle.ingestion_skill_updates() == []
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
        assert lifecycle.ingestion_skill_updates() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_api_runs_ingestion_skill_into_dataset_version_and_update(tmp_path, monkeypatch):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    market_data = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market_data)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)

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

        probes = registry.data_connector_schema_probes()
        assert len(probes) == 1
        assert probes[0].probe_ref == "schema_probe:tushare:daily:run"
        assert probes[0].dataset_version_ref == body["dataset_version_ref"]
        assert probes[0].schema_signature_hash.startswith("schema_signature:")
        assert probes[0].drift_status == "none"

        updates = lifecycle.ingestion_skill_updates()
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
        assert market_data.datasets() == []
        missing_dataset_instrument = client.post(
            "/api/research-os/settings/instrument_specs",
            json={"skill_id": "ingest:tushare:daily"},
        )
        assert missing_dataset_instrument.status_code == 422
        assert market_data.instruments() == []
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
        assert len(market_data.datasets()) == 1
        dataset = market_data.datasets()[0]
        assert dataset.known_at_ref == "known_at:ingest_time"
        assert dataset.effective_at_ref == "effective_at:trade_date"
        assert dataset.pit_bitemporal_rules_ref == "pit:tushare:daily"
        assert dataset.checksum == body["checksum"]
        assert graph.commands()
        assert semantics_body["qro_id"].startswith("qro_")
        assert graph.commands()[-1].command_type == "upsert_qro"
        assert graph.commands()[-1].payload["qro"].qro_type.value == "Dataset"
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
        assert len(market_data.instruments()) == 1
        assert market_data.instruments()[0].exchange_calendar_ref == "calendar:datasource:tushare:default"
        assert market_data.instruments()[0].symbol_mapping_ref == "schema_map:tushare:daily"
        assert graph.commands()[-1].payload["qro"].qro_type.value == "DataSourceAsset"
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
        assert market_data.capability_matrices() == []
        missing_capability_use = client.post(
            "/api/research-os/settings/market_data_use_validations",
            json={
                "skill_id": "ingest:tushare:daily",
                "dataset_ref": semantics_body["dataset_ref"],
                "instrument_ref": instrument_body["instrument_ref"],
            },
        )
        assert missing_capability_use.status_code == 422
        assert market_data.use_validations() == []

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
        assert len(market_data.capability_matrices()) == 1
        assert market_data.capability_matrices()[0].data_availability == semantics_body["dataset_ref"]
        assert market_data.capability_matrices()[0].live is False
        assert graph.commands()[-1].payload["qro"].qro_type.value == "MarketCapabilityMatrix"
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
        assert len(market_data.use_validations()) == 1
        recorded_use = market_data.use_validations()[0]
        assert recorded_use.dataset_refs == (semantics_body["dataset_ref"],)
        assert recorded_use.instrument_refs == (instrument_body["instrument_ref"],)
        assert recorded_use.capability_matrix_ref == capability_body["matrix_ref"]
        assert graph.commands()[-1].payload["qro"].qro_type.value == "MarketCapabilityMatrix"
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
        assert len(market_data.datasets()) == 1
        assert len(market_data.instruments()) == 1
        assert len(market_data.capability_matrices()) == 1
        assert len(market_data.use_validations()) == 1

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
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market_data)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)

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
        assert body["step_outputs"]["market_data_use"]["entrypoint_coverage_ref"] != body["entrypoint_coverage_ref"]
        assert "sk-" not in response.text

        assert checker.calls == [("ingest:tushare:daily", "datasource:tushare", ("secretref:tushare:read",), "u1")]
        assert runner.calls == [
            ("ingest:tushare:daily", "datasource:tushare", "connector_check:tushare:ok", "ingest:tushare:daily", "u1")
        ]
        assert datasets.latest("dataset:cn_equity_daily").row_count == 2
        assert len(lifecycle.ingestion_skill_updates()) == 1
        assert len(registry.data_connector_schema_probes()) == 1
        assert registry.data_connector_field_mappings()[0].mapping_method == "agent_suggested"
        assert registry.data_connector_field_mappings()[0].source_to_canonical == {
            "ts": "event_time",
            "symbol": "instrument_id",
            "close": "close",
        }
        assert registry.data_connector_pit_bitemporal_rules()[0].field_mapping_ref == "schema_map:tushare:daily"
        assert len(market_data.datasets()) == 1
        assert len(market_data.instruments()) == 1
        assert len(market_data.capability_matrices()) == 1
        assert len(market_data.use_validations()) == 1
        assert market_data.use_validations()[0].accepted is True
        assert graph.commands()[-1].payload["qro"].output_contract["status"] == "market_data_use_validated"
        qro_id = body["step_outputs"]["market_data_use"]["qro_id"]
        graph_command_id = body["step_outputs"]["market_data_use"]["research_graph_command_id"]
        direct_coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(
            body["step_outputs"]["market_data_use"]["entrypoint_coverage_ref"]
        )
        onboarding_coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
        assert direct_coverage.entrypoint_ref == "api:research_os.settings.market_data_use_validations"
        assert onboarding_coverage.entrypoint_ref == "api:research_os.settings.data_connector_onboarding_runs"
        assert direct_coverage.qro_refs == (qro_id,)
        assert onboarding_coverage.qro_refs == (qro_id,)
        assert onboarding_coverage.research_graph_command_refs == (graph_command_id,)
        top_ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
        top_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
        assert top_ir.source_qro_refs == (qro_id,)
        assert top_pass.input_qro_refs == (qro_id,)
        compiled_text = f"{top_ir.__dict__} {top_pass.__dict__} {onboarding_coverage.__dict__}"
        assert "000001.SZ" not in compiled_text
        assert "10.5" not in compiled_text
        assert "sk-" not in compiled_text
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_settings_one_shot_data_connector_onboarding_stops_before_market_data_records_on_bad_mapping(
    tmp_path,
    monkeypatch,
):
    client, registry = _client_with_onboarding_registry(tmp_path, monkeypatch)
    lifecycle, datasets = _install_lifecycle_and_dataset_registries(tmp_path, monkeypatch)
    market_data = PersistentMarketDataRegistry(tmp_path / "market_data_assets.jsonl")
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market_data)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)

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

        assert len(registry.data_connector_checks()) == 1
        assert len(registry.data_connector_schema_probes()) == 1
        assert len(lifecycle.ingestion_skill_updates()) == 1
        assert datasets.latest("dataset:cn_equity_daily").row_count == 2
        assert registry.data_connector_field_mappings() == []
        assert registry.data_connector_pit_bitemporal_rules() == []
        assert market_data.datasets() == []
        assert market_data.instruments() == []
        assert market_data.capability_matrices() == []
        assert market_data.use_validations() == []
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
        assert lifecycle.ingestion_skill_updates() == []
        assert registry.data_connector_checks() == []
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
        assert lifecycle.ingestion_skill_updates() == []
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
        assert lifecycle.ingestion_skill_updates() == []
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
        assert lifecycle.ingestion_skill_updates() == []
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
        assert len(lifecycle.ingestion_skill_updates()) == 1
        assert len(registry.data_connector_schema_probes()) == 1
        assert not (tmp_path / "datasets" / "ingestion" / "dataset_cn_equity_daily").joinpath(
            "schema_probe_tushare_daily_v2.parquet"
        ).exists()
        assert datasets.list_versions("dataset:cn_equity_daily")[0].file_paths == first_file_paths
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
