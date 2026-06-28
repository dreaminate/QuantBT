from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import math
import os
import threading
import re
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .agent import (
    AgentRAGContext,
    AgentRAGContextHit,
    AgentRuntime,
    AgentTurn,
    CodeReplicator,
    DevLocalLLM,
    NoLLMConfigured,
    StrategyGoalSlotFiller,
    TOOL_SCHEMA,
    ensure_settings_managed_llm_provider,
    list_llm_status,
    make_settings_managed_llm_client,
)
from .auth import AuthError, AuthService, current_user_dependency, require_user_dependency
from .auth.service import set_service as set_auth_service
from .community import CommunityService
from .connectors import registry as connector_registry
from .connectors.base import FetchRequest, FetchResult, make_wide_fetch_result
from .copy_trade import CopyTradeError, CopyTradeService, SignalRelayer
from .ide import (
    IDEError,
    IDEService,
    PromoteError,
    PromotedRun,
    build_ai_context,
    promote_ide_run,
    strategy_content_hash,
    validate_graph,
)
from .ide.service import IDERun, StrategyFile, run_to_dict, strategy_to_dict, version_to_dict
from .agent.conversations import (
    ChatError,
    ChatService,
    VALID_MARKET_MODES,
    message_to_dict,
    thread_to_dict,
)
from .agent.coach import classify_response_mode, suggest_from_risk_summary
from .agent.prompts import build_mode2_prompt
from .agent.rag import format_rag_context, format_run_context, retrieve
from .agent.replay import ControlledTranslator, FixtureStore, RecordingLLMClient
from .events import EventService, EventTrackError
from .execution import ExecutionAuditLog
from .glossary import GlossaryError, GlossaryRegistry, load_glossary_dir
from .sharing import SharingService
from .data_center_services import (
    get_data_files_response,
    get_data_kinds_response,
    get_data_overview_response,
    get_data_pools_response,
    get_data_preview_response,
    get_markets_response,
)
from .data_export import estimate_export_size, export_tar_gz_stream
from .data_quality import DatasetRegistry, DatasetVersion, compute_freshness
from .datasets import get_template as get_strategy_template, list_samples, list_templates as list_strategy_templates, load_sample
from .experiments import ExperimentStore, ModelRegistry, RunStore
from .factor_factory import (
    CorrelationError,
    ExpressionError,
    FactorAuditError,
    FactorRegistry,
    LayeredError,
    LifecycleManager,
    PanelSourceError,
    SignalContractError,
    SignalContractRegistry,
    admit_artifact_to_factor_lib,
    compile_expression,
    compute_ic_decay,
    compute_ic_report,
    correlation_matrix,
    factor_panel,
    layered_backtest,
    list_operators,
    register_alpha_lite,
    run_factor_audit,
)
from .factor_factory.mining import MiningError, MiningGateLeakError, run_mining
from .observability import get_reporter, init_error_reporting
from .jobs import InMemoryJobStore
from .monitor import (
    MONITOR_WEEKLY_DAG_NAME,
    MONITOR_WEEKLY_OP,
    WeeklyMonitorResult,
    build_weekly_monitor_scheduler,
    configure_monitor_runtime,
    observation_from_payload,
    run_weekly_monitor_tick,
)
from .paths import DATA_ROOT, PROJECT_ROOT, RUN_ROOT, ensure_runtime_dirs
from .portfolio.gate import gate_portfolio, portfolio_composition, portfolio_strategy_goal_ref
from .risk import KillSwitch, RiskLimits, RiskMonitor
from .security import InMemoryKeystore, KeystoreRecord, SecureKeystore, load_secrets
from .run_detail_services import (
    artifact_download_path,
    compare_runs_response,
    delete_run_response,
    export_path,
    get_compare_series_response,
    get_run_attribution_response,
    get_run_logs_response,
    get_run_response,
    get_run_series_response,
    get_run_source_response,
    get_run_table_response,
    list_runs_response,
    query_runs_response,
)
from .lineage.ids import content_hash
from .research_os import (
    ActorSource,
    AssetRAGDocument,
    AssetRAGError,
    CanvasLayoutRecord,
    CanvasMutationRecord,
    CompilerArtifactRecord,
    CompilerIRRecord,
    CompilerPassRecord,
    CanvasParameterValueRecord,
    DataConnectorConnectionCheckRecord,
    DataConnectorFieldMappingRecord,
    DataConnectorPITBitemporalRuleRecord,
    DataConnectorSchemaProbeRecord,
    DataSourceAssetRecord,
    DefinitionStatus,
    DatasetSemanticsRecord,
    CPCVCalculatorRecord,
    ConformalCalculatorRecord,
    EvidenceSpanRecord,
    EntrySource,
    EvidenceStatus,
    ExtractedResearchClaim,
    GoalEntrypointCoverageRecord,
    GoalSectionCoverageRecord,
    GraphPatchApplicationRecord,
    GovernanceStatus,
    LLMCredentialPoolRecord,
    LLMProviderHealthSnapshotRecord,
    LLMProviderRecord,
    LocalDocumentParseResult,
    MathematicalSpineChainRecord,
    IngestionSkillRecord,
    IngestionSkillUpdateRecord,
    InstrumentSpec,
    ExecutionOrderIntentRecord,
    ExecutionOrderMaterializationRecord,
    ExecutionOrderSubmissionRecord,
    ExecutionSubmitRequestRecord,
    ExecutionVenueConnectivityCheckRecord,
    ExecutionReconciliationActionRecord,
    ExecutionReconciliationRecord,
    ExecutionVenueCapabilityRecord,
    ExecutionVenueEventRecord,
    ExecutionVenueSafetyAttestationRecord,
    ExternalExpertSignatureRecord,
    ModelArtifactInspectionRecord,
    ModelRoutingPolicyRecord,
    ModelMonitoringProfile,
    ModelRecertificationRecord,
    ModelServingInvocationRecord,
    MarketCapabilityMatrixRecord,
    MarketDataUseRequest,
    MarketDataUseValidationRecord,
    PersistentResearchGraphStore,
    PersistentResearchAssetRAGIndex,
    PersistentDocumentIntelligenceStore,
    PersistentAssetLifecycleRegistry,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalSectionCoverageRegistry,
    PersistentMathematicalSpineChainRegistry,
    PersistentMethodologyCalculatorRegistry,
    PersistentMethodologyRuntimeDrillRegistry,
    PersistentTrustDisclosureRegistry,
    PersistentExternalExpertSignatureRegistry,
    PersistentTrustPressureRunRegistry,
    PersistentTrustReleaseApprovalRegistry,
    PersistentTrustReleaseCheckRegistry,
    PersistentTrustReleaseGateRegistry,
    PersistentValidationDepthRegistry,
    RuntimeDrillRecord,
    FunctionalIndependenceDisclosure,
    PersistentExecutionReconciliationActionRegistry,
    PersistentExecutionReconciliationRegistry,
    PersistentExecutionVenueCapabilityRegistry,
    PersistentExecutionVenueEventRegistry,
    PersistentExecutionVenueSafetyAttestationRegistry,
    PersistentExecutionOrderIntentRegistry,
    PersistentExecutionOrderMaterializationRegistry,
    PersistentExecutionOrderSubmissionRegistry,
    PersistentExecutionSubmitRequestRegistry,
    PersistentExecutionVenueConnectivityCheckRegistry,
    PersistentMarketDataRegistry,
    PersistentModelGovernanceRegistry,
    PersistentOnboardingRegistry,
    PersistentPlatformCoverageRegistry,
    PersistentRuntimePromotionRegistry,
    PersistentRDPCIReleaseAttestationStore,
    PersistentRDPDeploymentAttestationStore,
    PersistentRDPDeploymentHealthCheckStore,
    PersistentRDPExternalPublicationProofStore,
    PersistentRDPPackagePublishStore,
    PersistentRDPSourceRunIntegrityStore,
    PersistentRDPStore,
    PersistentSignalValidationRegistry,
    PrivilegedToolUseRequest,
    QROTombstoneRecord,
    QRORecord,
    QROType,
    DENSE_EMBEDDING_MODEL_REF,
    RAGPermission,
    RAGProjection,
    RAGQueryContext,
    RDPLocalPackagePublisher,
    RDPOpenPackageMaterializer,
    RDPManifest,
    RDPPackageArchiveExporter,
    RDPSourceFileBundler,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    REQUIRED_PLATFORM_ROWS,
    ResearchGraphCommand,
    ResearchGraphEdgeDeletionRecord,
    ResearchGraphEdgeRecord,
    ResearchGraphError,
    RuntimePromotionRecord,
    RuntimeStatus,
    TCACalculatorRecord,
    ExternalExpertReviewRecord,
    TrustPressureRunRecord,
    TrustReleaseApprovalRecord,
    TrustReleaseGateRecord,
    TrustReleaseCheckRecord,
    TrustClaimRecord,
    ExternalReviewerIdentityRecord,
    UserAutonomyRecord,
    ValidationUseContext,
    ValidationDepthRecord,
    SecretRefRecord,
    SignalPerformanceValidationRecord,
    SignalProtocolRecord,
    SourceDocumentIntakeRecord,
    calculate_conformal,
    calculate_cpcv,
    calculate_tca,
    record_runtime_drill,
    record_external_expert_review,
    record_trust_pressure_run,
    record_trust_release_approval,
    record_trust_release_check,
    record_trust_release_check_suite,
    parse_local_document,
    contains_plaintext_secret,
    cross_currency_capital_record_from_dict,
    data_transformation_claim_from_dict,
    execute_canvas_asset_mutation,
    artifact_inspection_record_from_dict,
    dataset_semantics_record_from_dict,
    execution_order_intent_from_dict,
    execution_order_materialization_from_dict,
    execution_order_submission_from_dict,
    execution_submit_request_from_dict,
    execution_venue_connectivity_check_from_dict,
    execution_reconciliation_action_from_dict,
    execution_venue_capability_from_dict,
    execution_venue_event_from_dict,
    execution_venue_safety_attestation_from_dict,
    goal_entrypoint_coverage_record_from_dict,
    goal_section_coverage_record_from_dict,
    instrument_spec_from_dict,
    ingestion_skill_allows_no_secret_connector,
    mathematical_spine_chain_from_dict,
    market_capability_matrix_record_from_dict,
    platform_capability_record_from_dict,
    platform_capability_record_to_dict,
    validate_market_data_use,
    make_canvas_layout_record,
    monitoring_profile_from_dict,
    model_passport_from_dict,
    recertification_record_from_dict,
    reconcile_execution_venue_events,
    runtime_promotion_record_from_dict,
    signal_validation_record_from_dict,
    external_expert_review_from_dict,
    external_reviewer_identity_from_dict,
    functional_independence_disclosure_from_dict,
    trust_claim_record_from_dict,
    trust_release_gate_record_from_dict,
    user_autonomy_record_from_dict,
    validate_goal_entrypoint_coverage,
    validate_goal_entrypoint_coverage_manifest,
    validate_goal_coverage_manifest,
    validate_platform_coverage_real_manifest,
    validate_rdp_manifest,
    validate_canvas_mutation,
    validate_compiler_artifact,
    validate_compiler_ir,
    validate_compiler_pass,
    validation_depth_record_from_dict,
    validate_data_connector_connection_check,
    data_connector_field_mapping_hash,
    data_connector_pit_bitemporal_rule_hash,
    validate_data_connector_field_mapping,
    validate_data_connector_pit_bitemporal_rule,
    validate_data_connector_schema_probe,
    validate_data_source_asset,
    validate_ingestion_skill_run,
    validate_secret_ref,
    validate_execution_order_intent,
    validate_execution_order_materialization,
    validate_execution_order_submission,
    validate_execution_submit_request,
    validate_execution_venue_connectivity_check,
    validate_execution_reconciliation_action,
    validate_execution_reconciliation,
    validate_execution_venue_capability,
    validate_execution_venue_event,
    validate_execution_venue_safety_attestation,
    validate_runtime_promotion_record,
    validate_signal_protocol,
)
from .research_os.factor_strategy_boundary import (
    FactorAssetKind,
    FactorGeneratorSpec,
    FactorLibraryEntry,
    StrategyBookContract,
    validate_factor_generator,
    validate_factor_library_entry,
    validate_strategy_book,
)
from .schemas import BinanceFullPullRequest, DataPullRequest, RunQueryRequest


app = FastAPI(title="1Backtest API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 脊柱内核 01 接线（T-023）：JOB_STORE 携内核 store（ArtifactStore+EffectLedger 落 DATA_ROOT/kernel）。
# kernel_dag job 的 retry 即「从最近 checkpoint 恢复 + is_consumed 去重、绝不重发单」；既有数据拉取 job 零影响。
JOB_STORE = InMemoryJobStore(kernel_root=DATA_ROOT / "kernel")
DATASET_REGISTRY = DatasetRegistry(DATA_ROOT / "datasets" / "registry.jsonl")
FACTOR_REGISTRY = FactorRegistry(DATA_ROOT / "factors" / "registry.json")
if not FACTOR_REGISTRY.list():
    register_alpha_lite(FACTOR_REGISTRY)
# F2 · 因子五态机生命周期管理器（绑定 FACTOR_REGISTRY）。POST /api/factors 经此初始 NEW、
# /lifecycle/events 从此读事件日志——注册绝不裸写 registry（生命周期门单一入口）。
FACTOR_LIFECYCLE = LifecycleManager(FACTOR_REGISTRY)
# F4 · R17 信号契约登记表（ML/DL 输出→信号→入因子库；本体绝不入库）。
SIGNAL_CONTRACTS = SignalContractRegistry(DATA_ROOT / "audit" / "signal_contracts.jsonl")
SIGNAL_VALIDATIONS = PersistentSignalValidationRegistry(DATA_ROOT / "audit" / "signal_validations.jsonl")
EXECUTION_ORDER_INTENTS = PersistentExecutionOrderIntentRegistry(DATA_ROOT / "audit" / "execution_order_intents.jsonl")
EXECUTION_ORDER_MATERIALIZATIONS = PersistentExecutionOrderMaterializationRegistry(
    DATA_ROOT / "audit" / "execution_order_materializations.jsonl"
)
EXECUTION_VENUE_CONNECTIVITY_CHECKS = PersistentExecutionVenueConnectivityCheckRegistry(
    DATA_ROOT / "audit" / "execution_venue_connectivity_checks.jsonl"
)
EXECUTION_VENUE_SAFETY_ATTESTATIONS = PersistentExecutionVenueSafetyAttestationRegistry(
    DATA_ROOT / "audit" / "execution_venue_safety_attestations.jsonl"
)
EXECUTION_VENUE_CAPABILITIES = PersistentExecutionVenueCapabilityRegistry(
    DATA_ROOT / "audit" / "execution_venue_capabilities.jsonl"
)
EXECUTION_SUBMIT_REQUESTS = PersistentExecutionSubmitRequestRegistry(DATA_ROOT / "audit" / "execution_submit_requests.jsonl")
EXECUTION_ORDER_SUBMISSIONS = PersistentExecutionOrderSubmissionRegistry(DATA_ROOT / "audit" / "execution_order_submissions.jsonl")
RUNTIME_PROMOTIONS = PersistentRuntimePromotionRegistry(DATA_ROOT / "audit" / "runtime_promotions.jsonl")
EXECUTION_VENUE_EVENTS = PersistentExecutionVenueEventRegistry(DATA_ROOT / "audit" / "execution_venue_events.jsonl")
EXECUTION_RECONCILIATIONS = PersistentExecutionReconciliationRegistry(DATA_ROOT / "audit" / "execution_reconciliations.jsonl")
EXECUTION_RECONCILIATION_ACTIONS = PersistentExecutionReconciliationActionRegistry(DATA_ROOT / "audit" / "execution_reconciliation_actions.jsonl")
# GOAL §1/§7/§8：Agent Shell/API/IDE/Scheduler/Canvas 入口接 QRO / Research Graph。
# 命令以 JSONL 落 audit；未接的业务入口继续按 GOAL 缺口推进。
RESEARCH_GRAPH_STORE = PersistentResearchGraphStore(DATA_ROOT / "audit" / "research_graph_commands.jsonl")
RESEARCH_ASSET_RAG_INDEX = PersistentResearchAssetRAGIndex(DATA_ROOT / "audit" / "research_asset_rag.jsonl")
DOCUMENT_INTELLIGENCE_STORE = PersistentDocumentIntelligenceStore(DATA_ROOT / "audit" / "document_intelligence.jsonl")
COMPILER_IR_STORE = PersistentCompilerIRStore(DATA_ROOT / "audit" / "compiler_ir.jsonl")
GOAL_ENTRYPOINT_COVERAGE_REGISTRY = PersistentGoalEntrypointCoverageRegistry(
    DATA_ROOT / "audit" / "goal_entrypoint_coverage.jsonl"
)
GOAL_SECTION_COVERAGE_REGISTRY = PersistentGoalSectionCoverageRegistry(
    DATA_ROOT / "audit" / "goal_section_coverage.jsonl",
    GOAL_ENTRYPOINT_COVERAGE_REGISTRY,
)
PLATFORM_COVERAGE_REGISTRY = PersistentPlatformCoverageRegistry(DATA_ROOT / "audit" / "platform_coverage_manifest.jsonl")
MATHEMATICAL_SPINE_CHAIN_REGISTRY = PersistentMathematicalSpineChainRegistry(
    DATA_ROOT / "audit" / "mathematical_spine_chains.jsonl"
)
TRUST_RELEASE_GATE_REGISTRY = PersistentTrustReleaseGateRegistry(DATA_ROOT / "audit" / "trust_release_gates.jsonl")
TRUST_RELEASE_CHECK_REGISTRY = PersistentTrustReleaseCheckRegistry(DATA_ROOT / "audit" / "trust_release_checks.jsonl")
TRUST_PRESSURE_RUN_REGISTRY = PersistentTrustPressureRunRegistry(DATA_ROOT / "audit" / "trust_pressure_runs.jsonl")
TRUST_RELEASE_APPROVAL_REGISTRY = PersistentTrustReleaseApprovalRegistry(DATA_ROOT / "audit" / "trust_release_approvals.jsonl")
TRUST_DISCLOSURE_REGISTRY = PersistentTrustDisclosureRegistry(DATA_ROOT / "audit" / "trust_disclosures.jsonl")
TRUST_EXPERT_SIGNATURE_REGISTRY = PersistentExternalExpertSignatureRegistry(
    DATA_ROOT / "audit" / "trust_expert_signatures.jsonl"
)
VALIDATION_DEPTH_REGISTRY = PersistentValidationDepthRegistry(DATA_ROOT / "audit" / "methodology_validation_depth.jsonl")
METHODOLOGY_CALCULATOR_REGISTRY = PersistentMethodologyCalculatorRegistry(
    DATA_ROOT / "audit" / "methodology_calculators.jsonl"
)
METHODOLOGY_RUNTIME_DRILL_REGISTRY = PersistentMethodologyRuntimeDrillRegistry(
    DATA_ROOT / "audit" / "methodology_runtime_drills.jsonl"
)
ONBOARDING_REGISTRY = PersistentOnboardingRegistry(DATA_ROOT / "audit" / "onboarding_settings.jsonl")
ASSET_LIFECYCLE_REGISTRY = PersistentAssetLifecycleRegistry(DATA_ROOT / "audit" / "asset_lifecycle.jsonl")
MARKET_DATA_REGISTRY = PersistentMarketDataRegistry(DATA_ROOT / "audit" / "market_data_assets.jsonl")
MODEL_GOVERNANCE_REGISTRY = PersistentModelGovernanceRegistry(DATA_ROOT / "audit" / "model_governance.jsonl")
RDP_STORE = PersistentRDPStore(DATA_ROOT / "audit" / "rdp_manifests.jsonl")
RDP_PACKAGE_MATERIALIZER = RDPOpenPackageMaterializer(DATA_ROOT / "rdp_packages")
RDP_SOURCE_FILE_BUNDLER = RDPSourceFileBundler(DATA_ROOT / "rdp_packages", PROJECT_ROOT)
RDP_PACKAGE_ARCHIVE_EXPORTER = RDPPackageArchiveExporter(DATA_ROOT / "rdp_packages")
RDP_PACKAGE_PUBLISHER = RDPLocalPackagePublisher(DATA_ROOT / "rdp_packages")
RDP_PACKAGE_PUBLISH_STORE = PersistentRDPPackagePublishStore(DATA_ROOT / "audit" / "rdp_package_publishes.jsonl")
RDP_EXTERNAL_PUBLICATION_PROOF_STORE = PersistentRDPExternalPublicationProofStore(
    DATA_ROOT / "audit" / "rdp_external_publication_proofs.jsonl"
)
RDP_CI_RELEASE_ATTESTATION_STORE = PersistentRDPCIReleaseAttestationStore(
    DATA_ROOT / "audit" / "rdp_ci_release_attestations.jsonl"
)
RDP_EXTERNAL_PUBLICATION_UPLOADER = None
RDP_CI_RELEASE_RUNNER = None
RDP_DEPLOYMENT_ATTESTATION_STORE = PersistentRDPDeploymentAttestationStore(
    DATA_ROOT / "audit" / "rdp_deployment_attestations.jsonl"
)
RDP_DEPLOYMENT_HEALTH_CHECK_STORE = PersistentRDPDeploymentHealthCheckStore(
    DATA_ROOT / "audit" / "rdp_deployment_health_checks.jsonl"
)
RDP_DEPLOYMENT_RUNNER = None
RDP_SOURCE_RUN_INTEGRITY_STORE = PersistentRDPSourceRunIntegrityStore(
    DATA_ROOT / "audit" / "rdp_source_run_integrity.jsonl"
)
EXPERIMENT_STORE = ExperimentStore(DATA_ROOT / "experiments")
RUN_STORE = RunStore(DATA_ROOT / "experiments")
MODEL_REGISTRY = ModelRegistry(DATA_ROOT / "experiments", model_governance_registry=MODEL_GOVERNANCE_REGISTRY)
ERROR_REPORTER = init_error_reporting(DATA_ROOT / "audit" / "errors.jsonl")
EXECUTION_AUDIT_LOG = ExecutionAuditLog()
MONITOR_SCHEDULER = None


class DisabledExecutionOrderMaterializer:
    """Default order materializer adapter.

    Production must inject an adapter that returns refs and hashes only. The
    default raises so API use cannot turn an intent into a venue payload.
    """

    materializer_ref = "disabled_execution_order_materializer"

    def materialize_order(
        self,
        *,
        materialization: ExecutionOrderMaterializationRecord,
        order_intent: ExecutionOrderIntentRecord,
        runtime_promotion: RuntimePromotionRecord,
        actor: str,
    ) -> dict[str, Any]:
        raise RuntimeError("execution order materializer disabled; inject an OrderGuard-backed materializer")


class DisabledExecutionVenueConnectivityChecker:
    """Default guarded venue connectivity checker adapter.

    Production must inject an adapter that returns refs and hashes only. The
    default raises so local API use cannot claim venue connectivity.
    """

    checker_ref = "disabled_execution_venue_connectivity_checker"

    def check_connectivity(
        self,
        *,
        order_intent: ExecutionOrderIntentRecord,
        runtime_promotion: RuntimePromotionRecord,
        actor: str,
    ) -> dict[str, Any]:
        raise RuntimeError("execution venue connectivity checker disabled; inject a SecretRef-backed checker")


class DisabledDataConnectorConnectionChecker:
    """Default Settings-managed data connector checker adapter.

    Production must inject a checker that dereferences SecretRef/TokenRef inside
    the backend connector boundary and returns sanitized refs/status only.
    """

    checker_ref = "disabled_data_connector_connection_checker"

    def check_connection(
        self,
        *,
        skill: IngestionSkillRecord,
        source: DataSourceAssetRecord,
        secrets: tuple[SecretRefRecord, ...],
        actor: str,
    ) -> dict[str, Any]:
        raise RuntimeError("data connector connection checker disabled; inject a SecretRef-backed checker")


class DisabledDataConnectorIngestionRunner:
    """Default Settings-managed data connector ingestion runner.

    Production must inject a runner that dereferences SecretRef/TokenRef inside
    the connector boundary and returns a FetchResult plus refs only. The default
    raises so local API use cannot claim a DatasetVersion was produced.
    """

    runner_ref = "disabled_data_connector_ingestion_runner"

    def run_ingestion(
        self,
        *,
        skill: IngestionSkillRecord,
        source: DataSourceAssetRecord,
        secrets: tuple[SecretRefRecord, ...],
        connector_check: DataConnectorConnectionCheckRecord,
        request: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        raise RuntimeError("data connector ingestion runner disabled; inject a SecretRef-backed runner")


def _settings_connector_config_value(skill: IngestionSkillRecord, request: dict[str, Any], key: str) -> Any:
    return request.get(key) if request.get(key) not in (None, "", [], ()) else skill.connector_config.get(key)


def _settings_connector_name_for_skill(
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    request: dict[str, Any] | None = None,
) -> str:
    req = request or {}
    for key in ("connector_name", "connector", "adapter", "provider"):
        value = req.get(key) or skill.connector_config.get(key)
        if value:
            return str(value)
    text = " ".join(
        str(value or "")
        for value in (
            skill.skill_id,
            skill.source_type,
            skill.source_ref,
            source.source_ref,
            source.source_url_or_path,
            skill.connector_config.get("endpoint"),
            skill.connector_config.get("market"),
        )
    ).lower()
    if "tushare" in text:
        return "tushare"
    if "binance" in text:
        if "spot" in text:
            return "binance_rest_spot"
        return "binance_rest_usdm"
    if "stooq" in text:
        return "stooq"
    raise ValueError("settings connector adapter cannot infer connector_name from IngestionSkill/DataSourceAsset")


def _settings_first_keystore_record(secrets: tuple[SecretRefRecord, ...]) -> KeystoreRecord | None:
    for secret in secrets:
        for name in _settings_keystore_refs(secret):
            return KEYSTORE.fetch(name)
    return None


def _settings_generic_rest_connector_for_skill(
    skill: IngestionSkillRecord,
    request: dict[str, Any] | None = None,
):
    from .connectors import GenericRESTConfig, GenericRESTConnector

    req = request or {}
    yaml_source = (
        _settings_connector_config_value(skill, req, "generic_rest_yaml")
        or _settings_connector_config_value(skill, req, "connector_yaml")
    )
    config_source = (
        _settings_connector_config_value(skill, req, "generic_rest_config")
        or _settings_connector_config_value(skill, req, "connector_config")
    )
    if yaml_source:
        if not isinstance(yaml_source, str):
            raise ValueError("settings generic_rest connector generic_rest_yaml must be a string")
        config = GenericRESTConfig.from_yaml(yaml_source)
    elif config_source:
        if not isinstance(config_source, dict):
            raise ValueError("settings generic_rest connector generic_rest_config must be an object")
        config = GenericRESTConfig.model_validate(config_source)
    else:
        raise ValueError("settings generic_rest connector requires generic_rest_yaml or generic_rest_config")
    if config.auth.static_value:
        raise ValueError("settings generic_rest connector must not use auth.static_value; use SecretRef/value_env")
    return config.connector_name, GenericRESTConnector(config)


def _settings_connector_for_skill(
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    secrets: tuple[SecretRefRecord, ...],
    request: dict[str, Any] | None = None,
):
    connector_name = _settings_connector_name_for_skill(skill, source, request)
    if connector_name == "tushare":
        from .connectors import TushareConnector

        secret = _settings_first_keystore_record(secrets)
        return connector_name, TushareConnector(token=secret.api_key if secret else None)
    if connector_name in {"binance_rest_spot", "binance_rest_usdm"}:
        from .connectors import BinanceRESTConnector

        market = "binance_spot" if connector_name == "binance_rest_spot" else "binanceusdm"
        return connector_name, BinanceRESTConnector(market)
    if connector_name in {"generic_rest", "generic_rest_yaml", "generic_rest_connector"}:
        return _settings_generic_rest_connector_for_skill(skill, request)
    return connector_name, connector_registry.get(connector_name)


def _settings_parse_connector_datetime(value: Any) -> _dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.UTC)
    text = str(value).strip()
    try:
        if len(text) == 8 and text.isdigit():
            return _dt.datetime.strptime(text, "%Y%m%d").replace(tzinfo=_dt.UTC)
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return _dt.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=_dt.UTC)
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.UTC)
    except ValueError as exc:
        raise ValueError(f"invalid connector datetime: {text}") from exc


def _settings_connector_data_kind(skill: IngestionSkillRecord, request: dict[str, Any], connector_name: str) -> str:
    value = _settings_connector_config_value(skill, request, "data_kind")
    if value:
        return str(value)
    endpoint = str(skill.connector_config.get("endpoint") or "").strip()
    if connector_name == "tushare" and endpoint == "daily":
        return "ohlcv"
    return endpoint or "ohlcv"


def _settings_connector_fetch_request(
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    request: dict[str, Any],
    connector_name: str,
) -> FetchRequest:
    symbol = (
        _settings_connector_config_value(skill, request, "symbol")
        or _settings_connector_config_value(skill, request, "ts_code")
        or _settings_connector_config_value(skill, request, "instrument")
    )
    if not symbol:
        symbols = _settings_connector_config_value(skill, request, "symbols")
        if isinstance(symbols, (list, tuple)) and symbols:
            symbol = symbols[0]
    if not symbol:
        raise ValueError("settings connector adapter requires symbol or symbols[0] for ingestion run")
    extra = _settings_connector_config_value(skill, request, "extra") or {}
    if not isinstance(extra, dict):
        raise ValueError("settings connector adapter extra must be an object")
    return FetchRequest(
        symbol=str(symbol),
        interval=str(_settings_connector_config_value(skill, request, "interval") or "1d"),
        start=_settings_parse_connector_datetime(
            _settings_connector_config_value(skill, request, "start")
            or _settings_connector_config_value(skill, request, "start_date")
        ),
        end=_settings_parse_connector_datetime(
            _settings_connector_config_value(skill, request, "end")
            or _settings_connector_config_value(skill, request, "end_date")
        ),
        data_kind=_settings_connector_data_kind(skill, request, connector_name),
        market=_settings_connector_config_value(skill, request, "market") or source.source_ref,
        extra=extra,
    )


class SettingsRegistryDataConnectorConnectionChecker:
    """Settings-managed connector checker backed by the built-in connector registry."""

    checker_ref = "settings_connector_registry_checker"

    def check_connection(
        self,
        *,
        skill: IngestionSkillRecord,
        source: DataSourceAssetRecord,
        secrets: tuple[SecretRefRecord, ...],
        actor: str,
    ) -> dict[str, Any]:
        connector_name, connector = _settings_connector_for_skill(skill=skill, source=source, secrets=secrets)
        health = connector.health_check()
        detail = health.detail if not contains_plaintext_secret(health.detail) else "connector health detail redacted"
        ok = bool(health.ok)
        return {
            "checker_ref": self.checker_ref,
            "status": "ok" if ok else "failed",
            "health_status": "ok" if ok else "failed",
            "quota_status": "unknown",
            "capability_refs": [f"connector_capability:{connector_name}"],
            "response_hash": "connector_health:" + content_hash(
                {
                    "connector": connector_name,
                    "skill_id": skill.skill_id,
                    "source_ref": source.source_ref,
                    "ok": ok,
                    "detail": detail,
                }
            ),
            "error_code": None if ok else "connector_health_failed",
            "error_message": None if ok else detail,
        }


class SettingsRegistryDataConnectorIngestionRunner:
    """Settings-managed ingestion runner backed by the built-in connector registry."""

    runner_ref = "settings_connector_registry_runner"

    def run_ingestion(
        self,
        *,
        skill: IngestionSkillRecord,
        source: DataSourceAssetRecord,
        secrets: tuple[SecretRefRecord, ...],
        connector_check: DataConnectorConnectionCheckRecord,
        request: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        connector_name, connector = _settings_connector_for_skill(
            skill=skill,
            source=source,
            secrets=secrets,
            request=request,
        )
        fetch_request = _settings_connector_fetch_request(
            skill=skill,
            source=source,
            request=request,
            connector_name=connector_name,
        )
        fetch_result = connector.fetch(fetch_request)
        return {
            "fetch_result": fetch_result,
            "runner_ref": self.runner_ref,
            "connector_name": connector_name,
            "dataset_id": skill.output_dataset_id,
            "connector_check_ref": connector_check.check_ref,
            "market": fetch_request.market,
            "data_kind": fetch_request.data_kind,
            "interval": fetch_request.interval,
            "symbols": [fetch_request.symbol],
        }


class DisabledExecutionSubmitRequestBuilder:
    """Default guarded submit request builder adapter.

    Production must inject an adapter that returns refs and hashes only. The
    default raises so local API use cannot invent a venue submit envelope.
    """

    builder_ref = "disabled_execution_submit_request_builder"

    def build_submit_request(
        self,
        *,
        order_intent: ExecutionOrderIntentRecord,
        runtime_promotion: RuntimePromotionRecord,
        order_materialization: ExecutionOrderMaterializationRecord,
        venue_capability: ExecutionVenueCapabilityRecord,
        actor: str,
    ) -> dict[str, Any]:
        raise RuntimeError("execution submit request builder disabled; inject an OrderGuard-backed builder")


class DisabledExecutionVenueEventIngester:
    """Default venue event ingester adapter.

    Production must inject an adapter that returns venue event refs and hashes
    only. The default raises so local API use cannot claim venue ack/fill ingest.
    """

    ingester_ref = "disabled_execution_venue_event_ingester"

    def ingest_event(
        self,
        *,
        submission: ExecutionOrderSubmissionRecord,
        order_intent: ExecutionOrderIntentRecord,
        runtime_promotion: RuntimePromotionRecord,
        actor: str,
    ) -> dict[str, Any]:
        raise RuntimeError("execution venue event ingester disabled; inject a refs-only venue event ingester")


class DisabledExecutionOrderSubmitter:
    """Default guarded submission adapter.

    Production must inject an adapter that submits through OrderGuard. The
    default raises so tests and local API use cannot accidentally reach a venue.
    """

    submitter_ref = "disabled_guarded_order_submitter"

    def submit_guarded_order(
        self,
        *,
        submission: ExecutionOrderSubmissionRecord,
        order_intent: ExecutionOrderIntentRecord,
        runtime_promotion: RuntimePromotionRecord,
        order_materialization: ExecutionOrderMaterializationRecord | None,
        venue_capability: ExecutionVenueCapabilityRecord | None,
        submit_request: ExecutionSubmitRequestRecord | None,
        actor: str,
    ) -> dict[str, Any]:
        raise RuntimeError("guarded order submitter disabled; inject an OrderGuard-backed submitter")


EXECUTION_ORDER_MATERIALIZER = DisabledExecutionOrderMaterializer()
EXECUTION_VENUE_CONNECTIVITY_CHECKER = DisabledExecutionVenueConnectivityChecker()
DATA_CONNECTOR_CONNECTION_CHECKER = SettingsRegistryDataConnectorConnectionChecker()
DATA_CONNECTOR_INGESTION_RUNNER = SettingsRegistryDataConnectorIngestionRunner()
EXECUTION_SUBMIT_REQUEST_BUILDER = DisabledExecutionSubmitRequestBuilder()
EXECUTION_VENUE_EVENT_INGESTER = DisabledExecutionVenueEventIngester()
EXECUTION_ORDER_SUBMITTER = DisabledExecutionOrderSubmitter()

# 脊柱第 0 层：honest-N 一本账（T-013）+ 收益快照内容寻址存储（T-014 ArtifactStore 复用），
# 供 T-015 多证据三角 gate 接进 promote/risk_preview（让 PBO/DSR 守门器从死接活）。
from .dag import ArtifactStore as _ArtifactStore  # noqa: E402
from .lineage import Ledger as _Ledger  # noqa: E402

LEDGER = _Ledger(DATA_ROOT / "lineage")
RETURNS_STORE = _ArtifactStore(DATA_ROOT / "lineage" / "returns")

# 脊柱 04：可证伪假设卡接进 Run 生命周期（T-024 / P2 不挡探索）。
# exploratory run 一律放行；仅晋级 confirmatory 可下注结论才强制冻结三必填 + 一次性 OOS 闸门。
from .hypothesis import (  # noqa: E402
    FreezeRejected as _FreezeRejected,
    HypothesisCardStore as _HypothesisCardStore,
    PromoteRejected as _PromoteRejected,
    can_touch_final_oos as _can_touch_final_oos,
)

HYPOTHESIS_STORE = _HypothesisCardStore(DATA_ROOT / "experiments")

# A4 · 策略台 → 模拟台 候选池（handoff 终点，止于模拟盘，绝不导向直接实盘 / D-PERM 不跳级）。
from .strategy import CandidatePoolStore as _CandidatePoolStore, HandoffRejected as _HandoffRejected  # noqa: E402
CANDIDATE_POOL = _CandidatePoolStore(DATA_ROOT / "strategy")

# 社区 / Auth / Sharing 共享同一 sqlite
_COMMUNITY_DB = DATA_ROOT / "community.db"
AUTH_SERVICE = AuthService(_COMMUNITY_DB)
set_auth_service(AUTH_SERVICE)
COMMUNITY_SERVICE = CommunityService(_COMMUNITY_DB)
SHARING_SERVICE = SharingService(_COMMUNITY_DB, DATA_ROOT / "artifacts" / "experiments")
COPY_TRADE_SERVICE = CopyTradeService(_COMMUNITY_DB)
IDE_SERVICE = IDEService(DATA_ROOT / "ide_strategies.db", run_root=DATA_ROOT / "ide_runs")
EVENT_SERVICE = EventService(_COMMUNITY_DB)  # 复用 community.db，单文件好查
CHAT_SERVICE = ChatService(_COMMUNITY_DB)  # v0.8.6 · Mode 2 多轮对话
from .trading import SafetyService, SafetyServiceError  # noqa: E402
SAFETY_SERVICE = SafetyService(_COMMUNITY_DB)  # v0.8.8 · 实盘安全阶梯
# P2 模拟台：多 run 注册 + 晋级判定门(INV-5) + 风险门冻结哈希/违规链——全部复用 paper/execution 既有引擎。
from .paper import (  # noqa: E402
    AShareLiveForbidden,
    PaperDeskService,
    PaperRunNotFound,
    RiskGateMutationForbidden,
    TESTNET_REALTIME_SOURCE,
    TESTNET_UNAVAILABLE_SOURCE,
    make_binance_testnet_provider,
)
PAPER_DESK = PaperDeskService()


# M7 惰性 prime：import 期只 register_run（纯内存，便宜），prime（16 ticks + MTM 文件 I/O，慢）
# 推迟到首次访问该 run 时再跑——不阻塞 import/startup，仍诚实（未 prime 的 seed 是空壳净值，访问即补）。
_SEED_PRIME_PENDING: set[str] = set()
_SEED_PRIME_LOCK = threading.Lock()


def _seed_paper_runs() -> None:
    """种入 demo 模拟盘（dev 友好；生产由策略台 promote 注册）。判定输入保守=未达标，绝不假绿灯。

    weekly_cn_multifactor 配成「4 门可过」以便前端晋升判定走真端点演示人工审批；其余保守。
    M7：本函数只 register_run（便宜）并标记待 prime；真 prime（喂 bars + MTM 文件 I/O）惰性化，
    由 `_prime_pending_seed` 在首次访问时补——绝不在 import/startup 阻塞起后端。
    """

    paper_root = DATA_ROOT / "paper"
    seeds = [
        dict(run_id="weekly_cn_multifactor", name="weekly_cn_multifactor",
             origin="策略台 · strat_wk_cn_01", market="equity_cn",
             symbols=["600519", "300750", "600036"], bench="中证500", creator="strat_wk_cn_01",
             days_running=28, paper_excess_return=0.018, backtest_annual=0.224, paper_annual=0.189),
        dict(run_id="crypto_perp_mom", name="crypto_perp_mom",
             origin="策略台 · strat_crypto_02", market="crypto",
             symbols=["BTCUSDT", "ETHUSDT"], bench="BTC", creator="strat_crypto_02",
             days_running=42, paper_excess_return=0.031, backtest_annual=0.40, paper_annual=0.36),
        dict(run_id="dividend_lowvol_cn", name="dividend_lowvol_cn",
             origin="策略台 · strat_div_03", market="equity_cn",
             symbols=["601398", "600900"], bench="中证红利", creator="strat_div_03",
             days_running=14, paper_excess_return=-0.004, backtest_annual=0.12, paper_annual=0.07),
    ]
    for s in seeds:
        try:
            PAPER_DESK.register_run(
                equity_log_path=paper_root / s["run_id"] / "equity_log.jsonl", **s,
            )
            _SEED_PRIME_PENDING.add(s["run_id"])  # 待惰性 prime（首次访问才喂模拟 bars 产净值）
        except Exception:  # noqa: BLE001  种子失败不阻塞 app 启动
            logging.getLogger(__name__).warning("seed paper run failed: %s", s["run_id"])


def _prime_pending_seed(run_id: str) -> None:
    """惰性补 prime 单个 seed run（首次访问触发）：喂模拟 bars 跑出真净值序列（非空壳）。

    数据源按市场分流：crypto 配捆样本→真 BTC close 回放(bundled_sample_replay)，无样本市场(A股)→
    确定性合成游走兜底(deterministic_sim_walk)；均为模拟非实盘 key。幂等（prime_run 自身复位）；
    线程安全（取出后才 prime，避免重复跑）。慢/只读 DATA_ROOT 时 prime 失败降级空壳是诚实行为。
    """

    with _SEED_PRIME_LOCK:
        if run_id not in _SEED_PRIME_PENDING:
            return
        _SEED_PRIME_PENDING.discard(run_id)
    try:
        PAPER_DESK.prime_run(run_id)
    except Exception:  # noqa: BLE001  prime 失败降级空壳（诚实），不阻塞访问
        logging.getLogger(__name__).warning("lazy prime seed run failed: %s", run_id)


def _prime_all_pending_seeds() -> None:
    """列表端点入口：把所有待 prime 的 seed 一次补齐（首次列模拟台时触发）。"""

    for rid in list(_SEED_PRIME_PENDING):
        _prime_pending_seed(rid)


_seed_paper_runs()
# T-019 审批门：接进 MODEL_REGISTRY（晚绑定，避免重排 :94 实例化）；staging/production promote 必经门。
from .approval import (  # noqa: E402
    ApprovalGateService,
    ApprovalGateStore,
    ApproverEqualsCreator,
    EmptyReason,
    GateRejection,
    GateStateError,
)
APPROVAL_GATE_STORE = ApprovalGateStore(DATA_ROOT / "experiments")
# T-020 部件12 验证官：异模型一致性裁决（产 verdict_id，喂审批门/假设卡）。
from .verification import Verifier, VerdictStore  # noqa: E402
VERDICT_STORE = VerdictStore(DATA_ROOT / "verification")
VERIFIER = Verifier()
# verdict_lookup 接进闸门：晋升 staging/production 时，verification_record_id 不止要存在——
# 还要异模型一致（blocked/concern/查不到 → 晋升缺口；闭合 T-019 [集成必补] 缝）。
GATE_SERVICE = ApprovalGateService(APPROVAL_GATE_STORE, safety_service=SAFETY_SERVICE,
                                   ledger=LEDGER, verdict_lookup=VERDICT_STORE.record_for)
MODEL_REGISTRY._gate_service = GATE_SERVICE
from .community.compliance import ComplianceService, check_content_for_forbidden  # noqa: E402
COMPLIANCE_SERVICE = ComplianceService(_COMMUNITY_DB)  # v0.8.8.1 · 帖子合规
from .copy_trade.beta import CopyTradeBetaService  # noqa: E402
CT_BETA_SERVICE = CopyTradeBetaService(_COMMUNITY_DB)  # v0.8.9 · 跟单灰度
from .security.mainnet_guards import MainnetGuardError, MainnetGuardsService  # noqa: E402
MAINNET_GUARDS = MainnetGuardsService(_COMMUNITY_DB)  # v1.0 · mainnet 7 项防御
from .billing import BillingService, PLAN_IDS  # noqa: E402
from .billing.stripe_service import PLAN_INFO  # noqa: E402
BILLING_SERVICE = BillingService(_COMMUNITY_DB)  # v1.0.3 · Stripe scaffold

# v2 数据平台 · 字段目录（inventory 为主 + registry 为辅）+ 字段映射 + 字段宇宙持久化表；官方字段带 official_ 前缀，无源开关/隔离
from .field_catalog import FieldCatalog, FieldCatalogStore, FieldMappingStore, InventoryDatasetSource  # noqa: E402


from .tushare_quant1 import qb_project_paths as _qb_project_paths  # noqa: E402

# B5: inventory 读路径 = rebuild 写路径（都取自 qb_project_paths），避免 BACKTEST_DATA_ROOT 非默认时读写分叉、字段宇宙恒空。
_QB_PATHS = _qb_project_paths()


def _rebuild_inventory() -> None:
    from .tushare_quant1.data_catalog import rebuild_data_catalog

    rebuild_data_catalog(_QB_PATHS)


FIELD_MAPPING_STORE = FieldMappingStore(str(_COMMUNITY_DB))
FIELD_CATALOG = FieldCatalog(
    DATASET_REGISTRY,
    sources=[InventoryDatasetSource(_QB_PATHS.data_catalog_inventory_file, rebuild=_rebuild_inventory)],
    mapping=FIELD_MAPPING_STORE,
)
# 字段宇宙持久化表：Agent 拉取辅助/写策略 + 官方数据更新的合并目标
FIELD_CATALOG_STORE = FieldCatalogStore(str(_COMMUNITY_DB))


def _field_universe_for_prompt(market: str | None = None) -> dict[str, dict]:
    """给 IDE/Agent system prompt 用的当前可用字段宇宙（按市场，随启用的源动态变化）。"""
    markets = [market] if market else ["stocks_cn", "binanceusdm", "binance_spot"]
    out: dict[str, dict] = {}
    for mkt in markets:
        try:
            uni = FIELD_CATALOG.available_fields(mkt)
        except Exception:  # noqa: BLE001
            continue
        out[mkt] = {"canonical": list(uni.canonical.keys()), "freeform": list(uni.freeform.keys())}
    return out

_main_logger = logging.getLogger(__name__)

# v0.8.4 · Glossary 词条仓库（启动时从 docs/glossary/ 加载，加载失败不阻断启动）
# main.py 在 app/backend/app/main.py → 仓库根是 parents[3]
_GLOSSARY_DIR = Path(__file__).resolve().parents[3] / "docs" / "glossary"
try:
    GLOSSARY = load_glossary_dir(_GLOSSARY_DIR) if _GLOSSARY_DIR.exists() else GlossaryRegistry()
except GlossaryError as exc:
    _main_logger.warning("Glossary 加载失败: %s（启动继续，词条 endpoint 返空）", exc)
    GLOSSARY = GlossaryRegistry()


def _binance_venue_for_follower(follower, keystore):
    """生产 venue factory（T-022 lease-only）：构造时**不 self-fetch key**。

    返回 LeasedBinanceVenue——真 key 仅在 OrderGuard S4 发 JIT lease 那一刻现身（INV-3）。
    key 存在性预检在 relayer step-2 走 broker.has_key（不返回 key 本体）。测试中由 mock factory 替代。
    `keystore` 入参保留作 VenueFactory 协议兼容（本实现不再用它取 key）。
    """
    network = follower.binance_network if follower.binance_network in {"testnet", "mainnet"} else "testnet"
    master = COPY_TRADE_SERVICE.get_master(follower.master_id)
    if master is None:
        return None
    from .execution.leased_binance import LeasedBinanceVenue
    if master.asset_class == "crypto_perp":
        return LeasedBinanceVenue(product="usdm_futures", network=network, audit=EXECUTION_AUDIT_LOG)
    if master.asset_class == "crypto_spot":
        return LeasedBinanceVenue(product="spot", network=network, audit=EXECUTION_AUDIT_LOG)
    return None  # equity_cn 等不联实盘

# 安全：开发环境用内存 keystore；上线时切换到 keyring/fernet（由 settings 控制）
KEYSTORE = SecureKeystore(InMemoryKeystore())
# 启动时自动读 ~/.quantbt/secrets.yaml（如有），把字段注入 keystore + env
_SECRETS_REPORT = load_secrets(KEYSTORE)

_LLM_PROVIDER_VALUES = ("anthropic", "openai", "qwen", "custom")


def _llm_keystore_extras(provider: str) -> dict[str, str]:
    try:
        record = KEYSTORE.fetch(f"llm_{provider}")
    except Exception:  # noqa: BLE001
        return {}
    try:
        raw = json.loads(record.note or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value is not None}


def _record_settings_managed_llm_provider(
    provider: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    owner: str = "settings-api",
    replace_secret: bool = True,
) -> dict[str, str]:
    extras = _llm_keystore_extras(provider)
    return ensure_settings_managed_llm_provider(
        registry=ONBOARDING_REGISTRY,
        provider=provider,  # type: ignore[arg-type]
        base_url=base_url if base_url is not None else extras.get("base_url"),
        model=model if model is not None else extras.get("model"),
        owner=owner,
        replace_secret=replace_secret,
    )


def _bootstrap_loaded_llm_settings_metadata() -> list[dict[str, str]]:
    bootstrapped: list[dict[str, str]] = []
    names = set(KEYSTORE.list_names())
    for provider in _LLM_PROVIDER_VALUES:
        if f"llm_{provider}" not in names:
            continue
        try:
            bootstrapped.append(
                {
                    "provider": provider,
                    **_record_settings_managed_llm_provider(
                        provider,
                        owner="secrets-loader",
                        replace_secret=False,
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            _main_logger.warning("LLM Settings metadata bootstrap skipped for %s: %s", provider, exc)
    return bootstrapped


_LLM_SETTINGS_BOOTSTRAP_REPORT = _bootstrap_loaded_llm_settings_metadata()
RISK_LIMITS = RiskLimits()
# T-021 生产接线：relay 下单热路径的会话外硬墙依赖。RELAY_NONCE_LEDGER=防重放（INV-4，crypto_live 强制）。
# 生产 relayer enforce_gate=True → 所有 follower 下单必经 deny-by-default 策略门（INV-2/M17 命门）。
from .security.gate.nonce import NonceLedger as _NonceLedger  # noqa: E402
RELAY_NONCE_LEDGER = _NonceLedger(DATA_ROOT / "security" / "relay_nonce")
# T-022 INV-3：ORDER_BROKER = 唯一持 keystore 句柄、发 JIT lease 的地方；relay venue 改 lease-only
# （构造不持 key），真 key 仅在 OrderGuard S4 发 lease 那一刻现身后端内存。
from .security.gate.broker import KeyBroker as _KeyBroker  # noqa: E402
ORDER_BROKER = _KeyBroker(KEYSTORE)
RISK_MONITOR = RiskMonitor(RISK_LIMITS)
KILL_SWITCH = KillSwitch([])  # 实盘 venue 启用时由 settings 注入

# M（卡 de764e1c · D-WAVE1A 残余②）：监控生产调度。startup 才构造 Scheduler(strict=True) +
# 注册 weekly 监控 DAG（让 monitor_tick 在生产真跑）。缺 croniter → strict=True 启动响亮失败
# （绝不静默不 tick = paper-true）。调用方在 loop 里周期 tick；本进程级 holder 供运维/测试取句柄。
PRODUCTION_SCHEDULER: "Scheduler | None" = None

# M driver（接线缺口修复）：`_start_production_monitor_scheduler` 只**注册** weekly DAG，engine.py 明载
# 「调用方在 loop 里 every N seconds 调 tick()」——但此前生产**无任何 driver** 去 tick → cron=0 9 * * 1
# 永不到点触发、退役闭环空转（log「已启动」是假绿灯）。本 daemon 线程即那个缺失的生产调用方。
_MONITOR_DRIVER_THREAD: "threading.Thread | None" = None
_MONITOR_DRIVER_STOP = threading.Event()

AGENT_SLOT_FILLER = StrategyGoalSlotFiller()
CODE_REPLICATOR = CodeReplicator()
# DS-2（真实后端接线 · blocker #2）：strategy_goal.create 校验落库产真 goal_id（被 DS-1 backtest 消费）。
from .strategy_goal_store import StrategyGoalStore  # noqa: E402

STRATEGY_GOAL_STORE = StrategyGoalStore(DATA_ROOT / "artifacts" / "strategy_goals")


# T-016 · LLM record/replay fixture store（脊柱 02）。默认 passthrough（行为不变）；
# 运维用 LLM_REPLAY_MODE=record|replay 开启（record 落不可变 fixture，replay 只读、绝不打真 API）。
FIXTURE_STORE = FixtureStore(
    DATA_ROOT / "artifacts" / "llm_fixtures",
    on_event=lambda e, p: _main_logger.info("llm_fixture_event %s %s", e, p),
)
# 受控翻译门（脊柱 02）：LLM 输出 schema 合规但语义越界（如越权杠杆）→ 不自动派发、挂人工确认。
def _agent_leverage_cap() -> float:
    # T-031 / D-LEVERAGE：翻译门杠杆阈值可配（默认 3.0），不钉系统硬上限（用户风险偏好）。
    # 真钱门不受影响——OrderGuard/PolicyGate 在端点层独立管真钱杠杆（杠杆放开数值≠绕门）。
    import os
    try:
        return float(os.environ.get("QUANTBT_AGENT_LEVERAGE_CAP", "3.0"))
    except ValueError:
        return 3.0


AGENT_TRANSLATOR = ControlledTranslator(leverage_cap=_agent_leverage_cap())


def _current_agent_llm(run_id: str | None = None):
    """按 keystore + env 选最优 provider；都失败 fallback DevLocalLLM。
    不缓存 client，让 secrets 热加载立即生效。LLM_REPLAY_MODE!=passthrough 时套 record/replay 装饰器（R11）。

    复核 #1/#7：run_id 缺省时【每次生成唯一值】，绝不退化为进程级常量——否则同 prompt 跨 turn
    撞同一 fixture_key、record 模式静默复用陈旧答案、replay 跨 run 假命中。
    """
    mode = os.environ.get("LLM_REPLAY_MODE", "passthrough")
    replay_ref = None
    if mode in ("record", "replay"):
        replay_ref = f"llm_replay:{run_id or 'agent-runtime'}"
    try:
        inner = make_settings_managed_llm_client(
            keystore=KEYSTORE,
            registry=ONBOARDING_REGISTRY,
            role_agent="agent",
            desk="agent",
            task_type="llm_chat",
            replay_record_ref=replay_ref,
        )
    except NoLLMConfigured as exc:
        _main_logger.warning("Agent LLM Gateway route unavailable; using DevLocalLLM: %s", exc)
        inner = DevLocalLLM()
    if mode in ("record", "replay"):
        rid = run_id or f"agent-{uuid.uuid4().hex[:12]}"
        return RecordingLLMClient(inner, FIXTURE_STORE, mode=mode, run_id=rid, translator=AGENT_TRANSLATOR)
    return inner


# 启动时探一次，仅用于 /api/agent/tools status 显示
AGENT_LLM = _current_agent_llm()


_DEFAULT_AGENT_RAG_PROJECTIONS = (
    RAGProjection.RESEARCH.value,
    RAGProjection.MATH.value,
    RAGProjection.CONSISTENCY.value,
    RAGProjection.DATA.value,
    RAGProjection.FACTOR.value,
    RAGProjection.MODEL.value,
    RAGProjection.SIGNAL.value,
    RAGProjection.STRATEGY.value,
    RAGProjection.RUN.value,
)


def _payload_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _agent_rag_prompt_context(hits) -> str:
    lines = [
        "Research Asset RAG candidate context. These hits are permission-filtered candidate context, not verdicts.",
        "Use them only with source_id/version citation and keep uncertainty visible.",
    ]
    for idx, hit in enumerate(hits, start=1):
        lines.append(
            f"[{idx}] source_id={hit.source_id}; version={hit.version}; projection={hit.projection}; "
            f"asset_ref={hit.asset_ref}; evidence_label={hit.evidence_label}; context_role={hit.context_role}; "
            f"title={hit.title}; applicability={hit.applicability}; snippet={hit.snippet}"
        )
    return "\n".join(lines)


def _agent_rag_hit_for_turn(hit) -> AgentRAGContextHit:
    return AgentRAGContextHit(
        source_id=hit.source_id,
        version=hit.version,
        asset_ref=hit.asset_ref,
        projection=hit.projection,
        title=hit.title,
        evidence_label=hit.evidence_label,
        context_role=hit.context_role,
        score=hit.score,
    )


def _agent_shell_rag_context_provider(payload: dict[str, Any], current: Any):
    username = getattr(current, "username", None) or getattr(current, "user_id", None)
    if not username:
        return None
    visible_asset_refs = _payload_tuple(payload.get("visible_asset_refs") or payload.get("rag_visible_asset_refs"))
    if not visible_asset_refs:
        return None
    desk = str(payload.get("desk") or payload.get("rag_desk") or "research")
    permission_tags = _payload_tuple(
        payload.get("permission_tags") or payload.get("rag_permission_tags") or ("research.read",)
    )
    projections = _payload_tuple(
        payload.get("projections") or payload.get("rag_projections") or _DEFAULT_AGENT_RAG_PROJECTIONS
    )
    try:
        top_k = int(payload.get("rag_top_k") or payload.get("top_k") or 5)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="rag_top_k must be an integer") from exc
    top_k = max(1, min(top_k, 10))
    search_mode = str(payload.get("rag_search") or payload.get("search_mode") or "vector").lower()
    if search_mode not in {"vector", "dense", "lexical"}:
        raise HTTPException(status_code=422, detail="rag_search must be 'vector', 'dense', or 'lexical'")
    agent_id = str(payload.get("agent_id") or f"agent:{desk}")
    purpose = str(payload.get("rag_purpose") or "agent_shell_context")

    def provide(query: str) -> AgentRAGContext:
        context = RAGQueryContext(
            user_id=str(username),
            desk=desk,
            visible_asset_refs=visible_asset_refs,
            permission_tags=permission_tags,
            actor="agent",
        )
        if search_mode == "lexical":
            hits = RESEARCH_ASSET_RAG_INDEX.retrieve(query, context=context, projections=projections, top_k=top_k)
        elif search_mode == "dense":
            hits = RESEARCH_ASSET_RAG_INDEX.dense_vector_search(
                query,
                context=context,
                projections=projections,
                top_k=top_k,
            )
        else:
            hits = RESEARCH_ASSET_RAG_INDEX.vector_search(query, context=context, projections=projections, top_k=top_k)
        usage_ids: list[str] = []
        for hit in hits:
            usage_ids.append(
                RESEARCH_ASSET_RAG_INDEX.record_agent_usage(
                    agent_id=agent_id,
                    hit=hit,
                    purpose=purpose,
                    user_id=str(username),
                ).usage_id
            )
        if not hits:
            return AgentRAGContext(prompt_context="")
        return AgentRAGContext(
            prompt_context=_agent_rag_prompt_context(hits),
            hits=tuple(_agent_rag_hit_for_turn(hit) for hit in hits),
            usage_ids=tuple(usage_ids),
        )

    return provide


def _agent_runtime(
    run_id: str | None = None,
    permission_mode: str = "auto",
    system_prompt: str | None = None,
    rag_context_provider=None,
) -> AgentRuntime:
    # 每次 agent turn 用唯一 run_id（复核 #1/#7）+ 武装受控翻译门（复核 #3）+ 权限三态（T-027/D-PERM）。
    runtime = AgentRuntime(
        _current_agent_llm(run_id=run_id or f"agent-{uuid.uuid4().hex[:12]}"),
        translator=AGENT_TRANSLATOR,
        permission_mode=permission_mode,
        research_graph=RESEARCH_GRAPH_STORE,
        entry_source="agent_shell",
        actor="agent_runtime",
        owner="agent_runtime",
        rag_context_provider=rag_context_provider,
        **({"system_prompt": system_prompt} if system_prompt else {}),
    )
    # 注册【无副作用】工具（side_effect=none，auto/bypass 可自主执行）；
    # 动钱/晋级永不注册给 agent —— 治理门钉在端点层（D-PERM 权限轴⟂治理轴）。
    # DS-2：真实后端接线，校验成 StrategyGoal（cost_model dispatch）+ 落库 → 真 goal_id（不再回显 args）。
    runtime.register_tool(
        "strategy_goal.create",
        lambda _n, args: _create_strategy_goal_with_compiler_coverage(
            args,
            entry_source="agent_shell",
            actor_source="agent",
            actor="agent_runtime",
            owner="strategy_goal_store",
        ),
        side_effect="none",
    )
    runtime.register_tool("factor.run_ic", lambda _n, args: {"queued": True, "args": args}, side_effect="none")
    runtime.register_tool("code.replicate", lambda _n, args: CODE_REPLICATOR.replicate(args.get("code", ""), args.get("source_dialect", "pandas")).__dict__, side_effect="none")
    # v2 数据平台 · 字段对齐工具（list_sources / describe_fields / infer_mapping / apply_mapping / validate_columns）
    from .agent.tool_handlers import register_field_tools
    register_field_tools(
        runtime,
        field_catalog=FIELD_CATALOG,
        mapping_store=FIELD_MAPPING_STORE,
    )
    # A4 · 策略台脊柱业务工具（hypothesis.create / factor_set.compose / model_registry.select[只读] /
    # signal.define / portfolio.construct / backtest.run / eval.pbo / report.generate）——全部
    # side_effect="none"（本地可重置、不动钱、不外发单）。动钱/晋级永不注册（治理门在端点层，D-PERM）。
    from .agent.business_tools import register_business_tools
    register_business_tools(
        runtime,
        hypothesis_store=HYPOTHESIS_STORE,
        factor_registry=FACTOR_REGISTRY,
        model_registry=MODEL_REGISTRY,
        run_store=RUN_STORE,
        experiment_store=EXPERIMENT_STORE,
        verdict_store=VERDICT_STORE,
        verifier=VERIFIER,
        # DS-1 脊梁（Fork3=A）：backtest.run 无 run_id → 合成→沙箱→promote 落 RUN_ROOT 产真 run_id。
        ledger=LEDGER,                  # 多证据三角 gate + honest-N 单一源
        returns_store=RETURNS_STORE,
        data_root=DATA_ROOT,            # 真行情样本位置 + run_root 派生
        market_data_registry=MARKET_DATA_REGISTRY,
        # llm_client 暂不注入 → 走确定性模板兜底；DS-2 真实后端接线注入真 LLM 客户端。
    )
    return runtime


def _start_production_monitor_scheduler() -> "Scheduler":
    """构造生产 `Scheduler(strict=True)` + 注册 weekly 监控 DAG（卡 de764e1c）。

    扩展不替换：在既有 startup 钩子里加监控调度起点，不动其它启动逻辑。
    - strict=True：缺 croniter → 构造即 raise（响亮失败），绝不让监控 tick 静默不跑（paper-true 红线）。
    - 幂等：startup 可能被多次触发（如多个 TestClient），重复构造/重复 `.add` 同名 DAG 仅覆盖，无副作用。
    返回 scheduler 句柄（也存进 PRODUCTION_SCHEDULER 进程级单例，供运维 loop tick / 测试取用）。
    """

    global PRODUCTION_SCHEDULER
    from .dag.engine import Scheduler  # 局部导入：与 dag 包解耦，按需起调度
    from .monitor.production import build_weekly_monitor_dag

    scheduler = Scheduler(strict=True)  # 缺 croniter → 此处响亮失败
    scheduler.add(build_weekly_monitor_dag())  # 周一早 9 点跑监控扫描（monitor_tick 生产真跑）
    PRODUCTION_SCHEDULER = scheduler
    _main_logger.info("生产监控调度已注册：weekly_factor_monitor cron=0 9 * * 1（待 driver 周期 tick）")
    return scheduler


def _monitor_driver_loop(interval_seconds: float) -> None:
    """后台 driver：every `interval_seconds` 调 `PRODUCTION_SCHEDULER.tick()`，让注册的 weekly cron 真到点 fire。

    `Scheduler.tick()` 是轮询式（`scheduled_at<=now` 才 fire，见 dag/engine.py），其 docstring 明载
    「调用方在 loop 里 every N seconds 调 tick()」——本 loop 就是那个生产调用方。补上后 weekly_factor_monitor
    cron 才真触发（此前空转=假绿灯：log 称已启动、实则无人 tick）。
    daemon 线程：不阻塞进程退出；`_MONITOR_DRIVER_STOP` 可停（shutdown/测试隔离）；单次 tick 异常吞掉续跑
    （一次失败不杀 driver，下周期重试）。每次 tick 读全局 `PRODUCTION_SCHEDULER`（startup 重建则跟随最新句柄）。
    """

    while not _MONITOR_DRIVER_STOP.wait(interval_seconds):
        sched = PRODUCTION_SCHEDULER
        if sched is None:
            continue
        try:
            sched.tick()
        except Exception:  # noqa: BLE001  单次 tick 失败不杀 driver（下周期重试）
            _main_logger.exception("监控调度 driver tick 失败（driver 续跑）")


def _start_monitor_driver() -> "threading.Thread | None":
    """启动监控调度 driver（幂等 · env 可关 · daemon）。返回线程句柄；env 关时返 None。

    - `QUANTBT_MONITOR_DRIVER`（默认开）：设 0/false/off/no → 不起 driver（scheduler 仍注册但不自动 tick，
      由运维外部 cron 调 `run_production_monitor_cycle`；不替用户拍「是否自动跑」松紧）。
    - `QUANTBT_MONITOR_TICK_SECONDS`（默认 60）：tick 周期。daemon + 默认 60s ⇒ 秒级测试永不误触发 weekly op。
    - 幂等：startup 可能被多次触发（多 TestClient），已有活线程则复用、绝不重复起。
    """

    global _MONITOR_DRIVER_THREAD
    if os.getenv("QUANTBT_MONITOR_DRIVER", "1").strip().lower() in ("0", "false", "off", "no"):
        _main_logger.info("监控调度 driver 按 env QUANTBT_MONITOR_DRIVER 关闭（scheduler 注册但不自动 tick）")
        return None
    if _MONITOR_DRIVER_THREAD is not None and _MONITOR_DRIVER_THREAD.is_alive():
        return _MONITOR_DRIVER_THREAD  # 幂等：不重复起线程
    try:
        interval = float(os.getenv("QUANTBT_MONITOR_TICK_SECONDS", "60"))
    except ValueError:
        interval = 60.0
    interval = max(0.001, interval)
    _MONITOR_DRIVER_STOP.clear()
    thread = threading.Thread(
        target=_monitor_driver_loop, args=(interval,),
        name="monitor-scheduler-driver", daemon=True,
    )
    thread.start()
    _MONITOR_DRIVER_THREAD = thread
    _main_logger.info("监控调度 driver 已启动：every %.3gs 调 PRODUCTION_SCHEDULER.tick()（weekly cron 真 fire）", interval)
    return thread


def stop_monitor_driver() -> None:
    """停 driver（shutdown/测试隔离）：set stop + join。daemon 本不阻塞退出，显式停便于测试干净复位。"""

    global _MONITOR_DRIVER_THREAD
    _MONITOR_DRIVER_STOP.set()
    thread = _MONITOR_DRIVER_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    _MONITOR_DRIVER_THREAD = None


_QRO_INPUT_AUDIT_FIELDS = {
    "arg_hash",
    "arg_keys",
    "asset_class",
    "code_hash",
    "context_hash",
    "dataset_id",
    "description_hash",
    "entry_source",
    "feature_count",
    "job_id",
    "mode",
    "model",
    "prompt_hash",
    "provider",
    "action_kind",
    "evidence_hash",
    "gate_id",
    "model_version",
    "model_version_ref",
    "market_data_use_validation_refs",
    "request_hash",
    "strategy_goal_ref",
    "target_stage",
    "verification_record_id",
    "scheduler_dag",
    "scheduler_op",
    "source_run_id",
    "strategy_id",
    "strategy_content_hash",
    "strategy_name",
    "task",
    "trigger",
    "turn_input_hash",
    "step_index",
    "role",
    "tool_name",
    "tool_call_id",
    "version",
}
_QRO_OUTPUT_AUDIT_FIELDS = {
    "asset_class",
    "benchmark",
    "action_count",
    "duration_s",
    "drift_pct_present",
    "exit_code",
    "factors_checked",
    "finished_at_utc",
    "gate_verdict_present",
    "action_kind",
    "decision",
    "evidence_hash",
    "from_stage",
    "gap_count",
    "gaps_hash",
    "gate_id",
    "goal_hash",
    "horizon",
    "lifecycle_event_count",
    "metric_count",
    "metrics_hash",
    "model",
    "model_passport_ref",
    "model_version",
    "model_version_ref",
    "market_data_use_validation_refs",
    "n_fills",
    "objective",
    "output_char_count",
    "output_hash",
    "promoted_run_id",
    "result_hash",
    "result_key_count",
    "run_id",
    "reason_hash",
    "risk_restated_hash",
    "side_effect_ref",
    "source_run_id",
    "started_at_utc",
    "step_hash",
    "content_hash",
    "strategy_id",
    "strategy_name",
    "target_stage",
    "updated_at_utc",
    "tool_call_count",
    "tool_call_id",
    "strategy_goal_id",
    "status",
    "validation_dossier_ref",
    "verdict_hash",
}


def _enum_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _safe_contract_fields(contract: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    """Only expose stable audit metadata, never raw prompt/tool payload fields."""

    out: dict[str, Any] = {}
    for key in sorted(allowed):
        if key not in contract:
            continue
        value = contract[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (str, int, float, bool)) or item is None for item in value
        ):
            out[key] = list(value)
    return out


def _qro_audit_summary(qro: QRORecord) -> dict[str, Any]:
    return {
        "qro_id": qro.qro_id,
        "qro_type": _enum_text(qro.qro_type),
        "owner": qro.owner,
        "actor": _enum_text(qro.actor),
        "market": qro.market,
        "universe": qro.universe,
        "horizon": qro.horizon,
        "frequency": qro.frequency,
        "status_axes": qro.status_axes(),
        "input_contract": _safe_contract_fields(qro.input_contract, _QRO_INPUT_AUDIT_FIELDS),
        "output_contract": _safe_contract_fields(qro.output_contract, _QRO_OUTPUT_AUDIT_FIELDS),
        "input_contract_keys": sorted(qro.input_contract.keys()),
        "output_contract_keys": sorted(qro.output_contract.keys()),
        "lineage": list(qro.lineage),
        "evidence_refs": list(qro.evidence_refs),
        "mathematical_refs": list(qro.mathematical_refs),
        "methodology_choice_ref": qro.methodology_choice_ref,
        "theory_implementation_binding": qro.theory_implementation_binding,
        "permission": qro.permission,
        "allowed_environment": _enum_text(qro.allowed_environment),
        "mock_profile": qro.mock_profile,
        "event_time": qro.event_time,
        "known_at": qro.known_at,
        "effective_at": qro.effective_at,
    }


def _research_graph_command_summary(command: ResearchGraphCommand) -> dict[str, Any]:
    payload = command.payload
    qro = payload.get("qro")
    payload_summary: dict[str, Any]
    if isinstance(qro, QRORecord):
        payload_summary = {"qro": _qro_audit_summary(qro)}
    else:
        payload_summary = {"payload_keys": sorted(str(k) for k in payload.keys())}
    return {
        "command_id": command.command_id,
        "source": _enum_text(command.source),
        "command_type": command.command_type,
        "actor_source": _enum_text(command.actor_source),
        "actor": command.actor,
        "version": command.version,
        "timestamp": command.timestamp,
        "evidence_refs": list(command.evidence_refs),
        "tool_record_refs": list(command.tool_record_refs),
        "payload": payload_summary,
    }


_MISSING_MARKET_DATA_USE_REFS = object()


def _ide_strategy_market_data_use_validation_refs(
    payload: dict[str, Any],
    *,
    operation: str,
    fallback_refs: Iterable[str] | None = None,
) -> tuple[str, ...]:
    raw_refs = payload.get("market_data_use_validation_refs", _MISSING_MARKET_DATA_USE_REFS)
    if raw_refs is _MISSING_MARKET_DATA_USE_REFS and fallback_refs is not None:
        raw_refs = list(fallback_refs)
    if raw_refs is _MISSING_MARKET_DATA_USE_REFS or raw_refs in (None, "", [], ()):
        raise HTTPException(
            status_code=422,
            detail=f"market_data_use_validation_refs is required for {operation}",
        )
    if isinstance(raw_refs, (str, bytes)) or not isinstance(raw_refs, (list, tuple)):
        raise HTTPException(
            status_code=422,
            detail="market_data_use_validation_refs must be a list of refs",
        )

    validation_refs: list[str] = []
    for idx, raw_ref in enumerate(raw_refs):
        validation_ref = str(raw_ref or "").strip()
        if not validation_ref:
            raise HTTPException(
                status_code=422,
                detail=f"market_data_use_validation_refs[{idx}] must be a non-empty ref",
            )
        try:
            record = MARKET_DATA_REGISTRY.use_validation(validation_ref)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"unknown market data use validation: {validation_ref}") from exc
        if not bool(getattr(record, "accepted", False)):
            raise HTTPException(status_code=422, detail=f"market data use validation {validation_ref} is not accepted")
        if tuple(getattr(record, "violation_codes", ()) or ()):
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} has unresolved violations",
            )
        validation_refs.append(validation_ref)
    return tuple(validation_refs)


def _record_ide_strategy_qro(
    strategy: StrategyFile,
    *,
    actor: str,
    market_data_use_validation_refs: Iterable[str] = (),
) -> dict[str, str]:
    """Record a saved IDE strategy draft as a StrategyBook QRO without copying source code."""

    now = _dt.datetime.now(_dt.UTC).isoformat()
    validation_refs = tuple(str(ref) for ref in market_data_use_validation_refs)
    code_hash = content_hash(strategy.code)
    description_hash = content_hash(strategy.description or "")
    draft_hash = strategy_content_hash(
        name=strategy.name,
        code=strategy.code,
        asset_class=strategy.asset_class,
    )
    implementation_payload = {
        "draft_hash": draft_hash,
        "market_data_use_validation_refs": list(validation_refs),
    }
    qro = QRORecord(
        qro_type=QROType.STRATEGY_BOOK,
        owner=strategy.owner_username,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.IDE.value,
            "strategy_id": strategy.strategy_id,
            "strategy_name": strategy.name,
            "asset_class": strategy.asset_class,
            "code_hash": code_hash,
            "description_hash": description_hash,
            "market_data_use_validation_refs": list(validation_refs),
        },
        output_contract={
            "strategy_id": strategy.strategy_id,
            "strategy_name": strategy.name,
            "asset_class": strategy.asset_class,
            "content_hash": draft_hash,
            "updated_at_utc": strategy.updated_at_utc,
            "market_data_use_validation_refs": list(validation_refs),
        },
        market=strategy.asset_class,
        universe="unspecified",
        horizon="strategy_draft",
        frequency="strategy_draft",
        lineage=("ide", "strategy.save", strategy.strategy_id, *validation_refs),
        implementation_hash="ide_strategy:" + content_hash(implementation_payload),
        assumptions=(
            "The IDE save endpoint has persisted this strategy draft for the owner namespace.",
            "Each listed MarketDataUse validation ref resolved to an accepted no-violation record before save.",
        ),
        known_limits=(
            "Saving a StrategyBook draft is not validation, backtest evidence, promotion, or execution readiness.",
            "Raw strategy source code and description text are not copied into QRO contracts.",
            "MarketDataUse validation refs are not proof that the IDE run consumed those datasets or instruments.",
        ),
        failure_modes=(
            "The draft may be syntactically invalid, economically invalid, overfit, or unsafe until later gates run.",
            "A later IDE run can drift from the saved draft unless run-level lineage also binds the data-use refs.",
        ),
        validation_plan=(
            "Bind the draft to graph validation, sandbox runs, evidence refs, and promotion gates before claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.UNTESTED,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        permission="ide.strategy.save:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.IDE,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.IDE.value,
        entrypoint_ref="ide:strategy.save",
        pass_name="ide_strategybook_qro_to_strategy_ir",
        validation_refs=_compiler_unique_refs(
            validation_refs,
            f"validation:ide.strategy.save:{strategy.strategy_id}",
        ),
        evidence_refs=(f"evidence:ide.strategy.save:{strategy.strategy_id}:{draft_hash}",),
        environment_lock_ref="env:ide_strategy_service:v1",
        permission_ref="ide.strategy.save:user_manual",
        deterministic_run_plan_ref=f"runplan:ide.strategy.save:{strategy.strategy_id}:{draft_hash}",
        rollback_ref=f"rollback:ide.strategy.save:{strategy.strategy_id}:previous_version",
        tool_record_refs=("api:ide.strategies", f"ide_strategy:{strategy.strategy_id}"),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.STRATEGY_BOOK.value}", f"ide_strategy:{strategy.strategy_id}"),
        canonical_command_refs=(f"research_graph_command:{command_id}", f"ide_strategy:{strategy.strategy_id}"),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_ide_run_qro(
    strategy: StrategyFile,
    run: IDERun,
    *,
    actor: str,
    market_data_use_validation_refs: Iterable[str] = (),
) -> dict[str, str]:
    """Record an IDE sandbox run as a BacktestRun QRO without copying logs or result payloads."""

    now = _dt.datetime.now(_dt.UTC).isoformat()
    validation_refs = tuple(str(ref) for ref in market_data_use_validation_refs)
    code_hash = content_hash(strategy.code)
    draft_hash = strategy_content_hash(
        name=strategy.name,
        code=strategy.code,
        asset_class=strategy.asset_class,
    )
    qro = QRORecord(
        qro_type=QROType.BACKTEST_RUN,
        owner=run.owner_username,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.IDE.value,
            "strategy_id": strategy.strategy_id,
            "strategy_name": strategy.name,
            "asset_class": strategy.asset_class,
            "code_hash": code_hash,
            "strategy_content_hash": draft_hash,
            "market_data_use_validation_refs": list(validation_refs),
        },
        output_contract={
            "run_id": run.run_id,
            "strategy_id": run.strategy_id,
            "status": run.status,
            "exit_code": run.exit_code,
            "duration_s": round(float(run.duration_s or 0.0), 6),
            "result_key_count": len(run.result_keys),
            "started_at_utc": run.started_at_utc,
            "finished_at_utc": run.finished_at_utc,
            "market_data_use_validation_refs": list(validation_refs),
        },
        market=strategy.asset_class,
        universe="unspecified",
        horizon="ide_run",
        frequency="ide_run",
        lineage=("ide", "strategy.run", strategy.strategy_id, run.run_id, *validation_refs),
        implementation_hash="ide_run:" + content_hash(
            {
                "run_id": run.run_id,
                "strategy_content_hash": draft_hash,
                "status": run.status,
                "market_data_use_validation_refs": list(validation_refs),
            }
        ),
        assumptions=(
            "The IDE sandbox executed the saved strategy code and persisted an IDERun record.",
            "Each listed MarketDataUse validation ref resolved to an accepted no-violation record before run.",
        ),
        known_limits=(
            "An IDE sandbox run is not proof of alpha, promotion approval, or execution readiness.",
            "Stdout, stderr, result payloads, result key names, and raw strategy source are not copied into QRO contracts.",
            "MarketDataUse validation refs are not proof that sandbox code consumed those exact data rows.",
        ),
        failure_modes=(
            "The run can fail, timeout, emit misleading user results, or depend on invalid economic assumptions.",
        ),
        validation_plan=(
            "Bind the run to validation dossiers, overfit gates, evidence refs, and promotion approvals before claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY if run.status == "ok" else EvidenceStatus.INSUFFICIENT,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        permission="ide.strategy.run:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.IDE,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.IDE.value,
        entrypoint_ref="ide:strategy.run",
        pass_name="ide_backtestrun_qro_to_backtest_ir",
        validation_refs=_compiler_unique_refs(
            validation_refs,
            f"validation:ide.strategy.run:{run.run_id}:{run.status}",
        ),
        evidence_refs=(f"evidence:ide.strategy.run:{run.run_id}:{run.status}",),
        environment_lock_ref="env:ide_sandbox:v1",
        permission_ref="ide.strategy.run:user_manual",
        deterministic_run_plan_ref=f"runplan:ide.strategy.run:{run.run_id}",
        rollback_ref=f"rollback:ide.strategy.run:{run.run_id}:discard_run",
        tool_record_refs=("api:ide.strategies.run", f"ide_run:{run.run_id}"),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.BACKTEST_RUN.value}", f"ide_run:{run.run_id}"),
        canonical_command_refs=(f"research_graph_command:{command_id}", f"ide_run:{run.run_id}"),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_ide_promote_qro(
    *,
    ide_run: IDERun,
    promoted: PromotedRun,
    strategy: StrategyFile | None,
    strategy_name: str,
    actor: str,
    market_data_use_validation_refs: Iterable[str] = (),
) -> dict[str, str]:
    """Record IDE promote as a formal BacktestRun QRO without copying promoted artifacts."""

    now = _dt.datetime.now(_dt.UTC).isoformat()
    validation_refs = tuple(str(ref) for ref in market_data_use_validation_refs)
    strategy_code = strategy.code if strategy is not None else ""
    asset_class = strategy.asset_class if strategy is not None else "unknown"
    code_hash = content_hash(strategy_code)
    draft_hash = (
        strategy_content_hash(name=strategy.name, code=strategy.code, asset_class=strategy.asset_class)
        if strategy is not None
        else None
    )
    qro = QRORecord(
        qro_type=QROType.BACKTEST_RUN,
        owner=ide_run.owner_username,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.IDE.value,
            "source_run_id": ide_run.run_id,
            "strategy_id": ide_run.strategy_id,
            "strategy_name": strategy_name,
            "asset_class": asset_class,
            "code_hash": code_hash,
            "strategy_content_hash": draft_hash,
            "market_data_use_validation_refs": list(validation_refs),
        },
        output_contract={
            "promoted_run_id": promoted.run_id,
            "source_run_id": ide_run.run_id,
            "status": "completed",
            "metric_count": len(promoted.metrics),
            "gate_verdict_present": promoted.gate_verdict is not None,
            "market_data_use_validation_refs": list(validation_refs),
        },
        market=asset_class,
        universe="unspecified",
        horizon="ide_promote",
        frequency="ide_promote",
        lineage=("ide", "strategy.promote", ide_run.run_id, promoted.run_id, *validation_refs),
        implementation_hash="ide_promote:" + content_hash(
            {
                "source_run_id": ide_run.run_id,
                "promoted_run_id": promoted.run_id,
                "strategy_content_hash": draft_hash,
                "market_data_use_validation_refs": list(validation_refs),
            }
        ),
        assumptions=(
            "The IDE promote endpoint wrote a formal run artifact from an existing ok sandbox run.",
            "Each listed MarketDataUse validation ref resolved to an accepted no-violation record before promote.",
        ),
        known_limits=(
            "IDE promote is not approval, production readiness, or live execution permission.",
            "Promoted strategy source, equity curve, trades, metrics payload, and gate verdict details are not copied into QRO contracts.",
        ),
        failure_modes=(
            "The promoted run can still be overfit, economically invalid, unsupported by validation, or rejected by later gates.",
        ),
        validation_plan=(
            "Bind the promoted run to validation dossiers, approvals, monitor rules, and runtime promotion gates before claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        permission="ide.run.promote:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.IDE,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.IDE.value,
        entrypoint_ref="ide:run.promote",
        pass_name="ide_promoted_backtestrun_qro_to_backtest_ir",
        validation_refs=_compiler_unique_refs(
            validation_refs,
            f"validation:ide.run.promote:{promoted.run_id}",
        ),
        evidence_refs=(f"evidence:ide.run.promote:{promoted.run_id}",),
        environment_lock_ref="env:ide_promote:v1",
        permission_ref="ide.run.promote:user_manual",
        deterministic_run_plan_ref=f"runplan:ide.run.promote:{promoted.run_id}",
        rollback_ref=f"rollback:ide.run.promote:{promoted.run_id}:manual_review",
        tool_record_refs=("api:ide.runs.promote", f"ide_run:{ide_run.run_id}", f"promoted_run:{promoted.run_id}"),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.BACKTEST_RUN.value}", f"promoted_run:{promoted.run_id}"),
        canonical_command_refs=(f"research_graph_command:{command_id}", f"promoted_run:{promoted.run_id}"),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_ide_ai_complete_qro(
    *,
    mode: str,
    prompt: str,
    context_code: str,
    provider: str,
    output_text: str,
    actor: str,
    market: str | None = None,
    market_data_use_validation_refs: Iterable[str] = (),
) -> dict[str, str]:
    """Record an IDE code-generation LLM call without copying prompt, context, or output."""

    now = _dt.datetime.now(_dt.UTC).isoformat()
    validation_refs = tuple(str(ref) for ref in market_data_use_validation_refs)
    qro = QRORecord(
        qro_type=QROType.LLM_CALL_RECORD,
        owner=actor,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.IDE.value,
            "mode": mode,
            "provider": provider,
            "prompt_hash": content_hash(prompt),
            "context_hash": content_hash(context_code or ""),
            "asset_class": market or "unspecified",
            "market_data_use_validation_refs": list(validation_refs),
        },
        output_contract={
            "status": "completed",
            "provider": provider,
            "output_hash": content_hash(output_text or ""),
            "output_char_count": len(output_text or ""),
            "market_data_use_validation_refs": list(validation_refs),
        },
        market=market or "unspecified",
        universe="unspecified",
        horizon="ide_ai_complete",
        frequency="ide_ai_complete",
        lineage=("ide", "ai_complete", mode, provider, *validation_refs),
        implementation_hash="ide_ai_complete:" + content_hash(
            {
                "mode": mode,
                "provider": provider,
                "prompt_hash": content_hash(prompt),
                "context_hash": content_hash(context_code or ""),
                "output_hash": content_hash(output_text or ""),
                "market_data_use_validation_refs": list(validation_refs),
            }
        ),
        assumptions=(
            "The IDE AI complete endpoint called the configured LLM client and returned text to the user.",
            "Each listed MarketDataUse validation ref resolved to an accepted no-violation record before the LLM call.",
        ),
        known_limits=(
            "LLM generated code or explanation is not validated, sandboxed, promoted, or evidence-backed by this call.",
            "Prompt text, editor context, and generated output are not copied into QRO contracts.",
            "MarketDataUse validation refs are not proof that generated code consumed those exact data rows.",
        ),
        failure_modes=(
            "The generated text can be syntactically invalid, unsafe, misleading, or economically invalid until reviewed and tested.",
        ),
        validation_plan=(
            "Route generated strategy code through IDE save, sandbox run, graph validation, and promotion gates before claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.UNTESTED,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        permission="ide.ai_complete:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.IDE,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    output_hash = content_hash(output_text or "")
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.IDE.value,
        entrypoint_ref="ide:ai_complete",
        pass_name="ide_llmcallrecord_qro_to_llm_audit_ir",
        validation_refs=_compiler_unique_refs(
            validation_refs,
            f"validation:ide.ai_complete:{mode}:{provider}",
        ),
        evidence_refs=(f"evidence:ide.ai_complete:{output_hash}",),
        environment_lock_ref="env:ide_ai_complete:v1",
        permission_ref="ide.ai_complete:user_manual",
        deterministic_run_plan_ref=f"runplan:ide.ai_complete:{mode}:{provider}:{output_hash}",
        rollback_ref=f"rollback:ide.ai_complete:{output_hash}:discard_suggestion",
        tool_record_refs=("api:ide.ai_complete", f"llm_provider:{provider}"),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.LLM_CALL_RECORD.value}", f"llm_provider:{provider}"),
        canonical_command_refs=(f"research_graph_command:{command_id}", f"llm_call:{qro.qro_id}"),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _compile_entrypoint_qro(
    *,
    qro_id: str,
    graph_command_id: str,
    actor: str,
    actor_source: str,
    entry_source: str,
    entrypoint_ref: str,
    pass_name: str,
    validation_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    environment_lock_ref: str,
    permission_ref: str,
    deterministic_run_plan_ref: str,
    rollback_ref: str,
    tool_record_refs: Iterable[str] = (),
    node_refs: Iterable[str] = (),
    canonical_command_refs: Iterable[str] = (),
) -> dict[str, str]:
    """Compile a just-recorded entrypoint QRO without embedding raw payloads."""

    ir, compiler_pass = _compile_qro_payload(
        {
            "qro_id": qro_id,
            "validation_refs": _compiler_unique_refs(validation_refs),
            "evidence_refs": _compiler_unique_refs(evidence_refs),
            "environment_lock_ref": environment_lock_ref,
            "permission_ref": permission_ref,
            "pass_name": pass_name,
            "compiler_version": "governed-compiler-ir.v1",
            "deterministic_run_plan_ref": deterministic_run_plan_ref,
            "rollback_ref": rollback_ref,
            "actor_source": actor_source,
            "entry_source": entry_source,
            "tool_record_refs": _compiler_unique_refs(tool_record_refs),
            "graph_command_refs": (graph_command_id,),
            "canonical_command_refs": _compiler_unique_refs(
                canonical_command_refs,
                (f"research_graph_command:{graph_command_id}",),
            ),
            "node_refs": _compiler_unique_refs(node_refs, (f"qro:{qro_id}",)),
        },
        actor=actor,
    )
    coverage_candidate = _validate_goal_entrypoint_coverage_candidate(
        _goal_entrypoint_coverage_from_compiler_records(
            ir,
            compiler_pass,
            entrypoint_ref=entrypoint_ref,
        )
    )
    COMPILER_IR_STORE.record_ir(ir)
    COMPILER_IR_STORE.record_pass(compiler_pass)
    coverage = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(coverage_candidate)
    return {
        "compiler_ir_ref": ir.ir_ref,
        "compiler_pass_ref": compiler_pass.pass_ref,
        "entrypoint_coverage_ref": coverage.coverage_ref,
    }


def _record_agent_turn_entrypoint_coverage(
    turn: AgentTurn,
    *,
    entry_source: EntrySource | str,
    entrypoint_ref: str,
    actor: str,
    actor_source: ActorSource | str,
    permission_ref: str,
    environment_lock_ref: str,
    pass_name: str,
    deterministic_run_plan_ref: str,
    rollback_ref: str,
    validation_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    tool_record_refs: Iterable[str] = (),
    node_refs: Iterable[str] = (),
    canonical_command_refs: Iterable[str] = (),
) -> dict[str, str]:
    if not turn.succeeded:
        return {}
    if not turn.qro_ids or not turn.research_graph_command_ids:
        raise ValueError("agent turn coverage requires qro_ids and research_graph_command_ids")
    if len(turn.qro_ids) != len(turn.research_graph_command_ids):
        raise ValueError("agent turn coverage requires aligned qro_ids and research_graph_command_ids")

    source_text = entry_source.value if hasattr(entry_source, "value") else str(entry_source)
    actor_source_text = actor_source.value if hasattr(actor_source, "value") else str(actor_source)
    turn_ref = "agent_turn:" + content_hash(
        {
            "entry_source": source_text,
            "entrypoint_ref": entrypoint_ref,
            "qro_ids": turn.qro_ids,
            "research_graph_command_ids": turn.research_graph_command_ids,
            "rag_usage_ids": turn.rag_usage_ids,
            "succeeded": turn.succeeded,
            "step_roles": [step.role for step in turn.steps],
        }
    )
    qro_id = turn.qro_ids[-1]
    graph_command_id = turn.research_graph_command_ids[-1]
    refs = _compile_entrypoint_qro(
        qro_id=qro_id,
        graph_command_id=graph_command_id,
        actor=actor,
        actor_source=actor_source_text,
        entry_source=source_text,
        entrypoint_ref=entrypoint_ref,
        pass_name=pass_name,
        validation_refs=_compiler_unique_refs(
            validation_refs,
            f"validation:{entrypoint_ref}:succeeded",
            f"validation:{entrypoint_ref}:qro_graph_refs_present",
            f"validation:{entrypoint_ref}:raw_payload_excluded:{turn_ref}",
        ),
        evidence_refs=_compiler_unique_refs(evidence_refs, f"evidence:{turn_ref}"),
        environment_lock_ref=environment_lock_ref,
        permission_ref=permission_ref,
        deterministic_run_plan_ref=deterministic_run_plan_ref,
        rollback_ref=rollback_ref,
        tool_record_refs=_compiler_unique_refs(tool_record_refs, turn_ref),
        node_refs=_compiler_unique_refs(node_refs, f"qro:{qro_id}", f"entrypoint:{entrypoint_ref}", turn_ref),
        canonical_command_refs=_compiler_unique_refs(
            canonical_command_refs,
            f"research_graph_command:{graph_command_id}",
            f"entrypoint:{entrypoint_ref}",
            turn_ref,
        ),
    )
    turn.compiler_ir_refs.append(refs["compiler_ir_ref"])
    turn.compiler_pass_refs.append(refs["compiler_pass_ref"])
    turn.entrypoint_coverage_refs.append(refs["entrypoint_coverage_ref"])
    return refs


def _record_agent_turn_goal_entrypoint_coverage(
    turn: AgentTurn,
    *,
    endpoint_ref: str,
    actor: str,
    permission_mode: str,
    include_chat: bool = True,
    include_agent_shell: bool = True,
) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {
        "compiler_ir_refs": [],
        "compiler_pass_refs": [],
        "entrypoint_coverage_refs": [],
    }
    if not turn.succeeded:
        return refs

    specs: list[tuple[str, str]] = []
    if include_agent_shell:
        specs.append((EntrySource.AGENT_SHELL.value, f"agent_shell:{endpoint_ref}"))
    if include_chat:
        specs.append((EntrySource.CHAT.value, f"chat:{endpoint_ref}"))

    turn_hash = content_hash(
        {
            "endpoint_ref": endpoint_ref,
            "qro_ids": turn.qro_ids,
            "research_graph_command_ids": turn.research_graph_command_ids,
            "rag_usage_ids": turn.rag_usage_ids,
            "succeeded": turn.succeeded,
        }
    )
    for source_text, entrypoint_ref in specs:
        result = _record_agent_turn_entrypoint_coverage(
            turn,
            entry_source=source_text,
            entrypoint_ref=entrypoint_ref,
            actor=actor,
            actor_source=ActorSource.AGENT,
            permission_ref=f"{entrypoint_ref}:permission_mode:{permission_mode}",
            environment_lock_ref=f"env:{entrypoint_ref.replace(':', '.')}:v1",
            pass_name=f"{source_text}_agent_turn_qro_to_research_report_ir",
            deterministic_run_plan_ref=f"runplan:{entrypoint_ref}:{turn_hash}",
            rollback_ref=f"rollback:{entrypoint_ref}:{turn_hash}:manual_review",
            validation_refs=(f"validation:{endpoint_ref}:agent_turn_succeeded",),
            evidence_refs=(f"evidence:agent_turn:{turn_hash}",),
            tool_record_refs=(f"endpoint:{endpoint_ref}",),
            canonical_command_refs=(f"endpoint:{endpoint_ref}",),
        )
        for key, value in (
            ("compiler_ir_refs", result.get("compiler_ir_ref")),
            ("compiler_pass_refs", result.get("compiler_pass_ref")),
            ("entrypoint_coverage_refs", result.get("entrypoint_coverage_ref")),
        ):
            if value:
                refs[key].append(value)
    return refs


def _record_legacy_chat_message_entrypoint_coverage(
    *,
    entrypoint_ref: str,
    actor: str,
    user_text: str,
    assistant_text: str,
    thread_id: str,
    research_asset_rag_hits: Iterable[dict[str, Any]] = (),
    research_asset_rag_usage_ids: Iterable[str] = (),
    streamed: bool = False,
) -> dict[str, Any]:
    rag_hits = tuple(research_asset_rag_hits)
    rag_usage_ids = tuple(str(usage_id) for usage_id in research_asset_rag_usage_ids)
    user_hash = content_hash({"user_text": user_text})
    assistant_hash = content_hash({"assistant_text": assistant_text})
    event_hash = content_hash(
        {
            "entrypoint_ref": entrypoint_ref,
            "thread_id": thread_id,
            "user_hash": user_hash,
            "assistant_hash": assistant_hash,
            "streamed": streamed,
        }
    )
    timestamp = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = _compiler_unique_refs(
        tuple(str(hit.get("evidence_ref") or "") for hit in rag_hits),
        tuple(f"rag_usage:{usage_id}" for usage_id in rag_usage_ids),
        f"evidence:legacy_chat_message:{event_hash}",
    )
    qro = QRORecord(
        qro_type=QROType.RESEARCH_REPORT,
        owner="legacy_mode2_chat",
        actor=ActorSource.AGENT,
        input_contract={
            "entry_source": EntrySource.CHAT.value,
            "entrypoint_ref": entrypoint_ref,
            "thread_id_hash": content_hash({"thread_id": thread_id}),
            "user_text_hash": user_hash,
            "streamed": streamed,
        },
        output_contract={
            "assistant_text_hash": assistant_hash,
            "research_asset_rag_hit_count": len(rag_hits),
            "research_asset_rag_usage_count": len(rag_usage_ids),
        },
        market="unspecified",
        universe="legacy_mode2_chat",
        horizon="event",
        frequency="event",
        lineage=("legacy_mode2_chat", entrypoint_ref, f"event:{event_hash}"),
        implementation_hash="legacy_mode2_chat:" + event_hash,
        assumptions=("Legacy chat message captured as a hash-only Research OS entrypoint event.",),
        known_limits=(
            "Chat output is not sufficient evidence for trading decisions.",
            "Plaintext user and assistant messages are not copied into QRO or coverage contracts.",
        ),
        failure_modes=("LLM output may be incomplete, unsafe, or require downstream validation.",),
        validation_plan=("Validate downstream claims through Research Graph evidence and promotion gates.",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.UNTESTED,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=timestamp,
        known_at=timestamp,
        effective_at=timestamp,
        evidence_refs=evidence_refs,
        permission=f"{entrypoint_ref}:no_side_effect",
        responsibility_boundary="records legacy chat response metadata only; does not validate research claims",
    )
    command = ResearchGraphCommand(
        source=EntrySource.CHAT,
        command_type="upsert_qro",
        actor_source=ActorSource.AGENT,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
        tool_record_refs=(f"endpoint:{entrypoint_ref}",),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.AGENT.value,
        entry_source=EntrySource.CHAT.value,
        entrypoint_ref=entrypoint_ref,
        pass_name="chat_legacy_message_qro_to_research_report_ir",
        validation_refs=(
            f"validation:{entrypoint_ref}:assistant_content_hash",
            f"validation:{entrypoint_ref}:raw_payload_excluded:{event_hash}",
        ),
        evidence_refs=evidence_refs,
        environment_lock_ref=f"env:{entrypoint_ref.replace(':', '.')}:v1",
        permission_ref=qro.permission,
        deterministic_run_plan_ref=f"runplan:{entrypoint_ref}:{event_hash}",
        rollback_ref=f"rollback:{entrypoint_ref}:{event_hash}:manual_review",
        tool_record_refs=(f"endpoint:{entrypoint_ref}",),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.RESEARCH_REPORT.value}", f"thread:{thread_id}"),
        canonical_command_refs=(f"research_graph_command:{command_id}", f"entrypoint:{entrypoint_ref}"),
    )
    return {
        "qro_ids": [qro.qro_id],
        "research_graph_command_ids": [command_id],
        "compiler_ir_refs": [refs["compiler_ir_ref"]],
        "compiler_pass_refs": [refs["compiler_pass_ref"]],
        "entrypoint_coverage_refs": [refs["entrypoint_coverage_ref"]],
    }


def _create_strategy_goal_with_compiler_coverage(
    args: dict[str, Any],
    *,
    entry_source: EntrySource | str,
    actor_source: ActorSource | str,
    actor: str,
    owner: str,
) -> dict[str, Any]:
    result = STRATEGY_GOAL_STORE.create_from_args(
        args,
        research_graph=RESEARCH_GRAPH_STORE,
        entry_source=entry_source,
        actor_source=actor_source,
        actor=actor,
        owner=owner,
    )
    if result.get("error") or not result.get("qro_id") or not result.get("research_graph_command_id"):
        return result
    goal_id = str(result["strategy_goal_id"])
    source_text = entry_source.value if hasattr(entry_source, "value") else str(entry_source)
    actor_source_text = actor_source.value if hasattr(actor_source, "value") else str(actor_source)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=str(result["qro_id"]),
        graph_command_id=str(result["research_graph_command_id"]),
        actor=actor,
        actor_source=actor_source_text,
        entry_source=source_text,
        entrypoint_ref=(
            "agent_shell:strategy_goal.create"
            if source_text == EntrySource.AGENT_SHELL.value
            else "api:strategy_goals"
        ),
        pass_name=f"{source_text}_quant_intent_qro_to_research_intent_ir",
        validation_refs=(
            f"validation:strategy_goal.create:{goal_id}",
            f"validation:strategy_goal.slots:{result.get('asset_class')}:{result.get('horizon')}",
        ),
        evidence_refs=(f"evidence:strategy_goal_store:{goal_id}",),
        environment_lock_ref="env:strategy_goal_store:v1",
        permission_ref="strategy_goal.create:no_side_effect",
        deterministic_run_plan_ref=f"runplan:strategy_goal.create:{goal_id}",
        rollback_ref=f"rollback:strategy_goal.create:{goal_id}:manual_review",
        tool_record_refs=("tool:strategy_goal.create", f"strategy_goal:{goal_id}"),
        node_refs=(f"qro:{result['qro_id']}", f"qro_type:{QROType.QUANT_INTENT.value}", f"strategy_goal:{goal_id}"),
        canonical_command_refs=(f"research_graph_command:{result['research_graph_command_id']}", f"strategy_goal:{goal_id}"),
    )
    return {**result, **compiler_refs}


# ── GOAL §9 边界验证器 · advisory-first 接线（RULES §3 诚实纪律）────────────────────────
# 诚实边界（必读）：以下助手把 §9 factor/model/signal/strategy 边界裁决接到真实
# register/admit 生产路径，但**只记录、不强制**——裁决以 `boundary_verdict` 字段挂到产物
# 响应上供审计/前端展示，**违例不 raise、不拒请求**。强制（hard-reject）是后续显式决策，
# 不在本波。任何调用方/前端**不得**把 advisory 的 `ok=False` 渲染成硬保证或硬阻断。
def _boundary_verdict_payload(decision: Any, *, boundary: str) -> dict[str, Any]:
    """把一个 §9 BoundaryDecision 转成 advisory-only 的 `boundary_verdict` 载荷。

    诚实纪律（RULES §3）：advisory-first —— 裁决被**记录**（挂到响应），**不被强制**
    （违例不拒请求）。`ok` 仅表「§9 边界此刻是否被满足」，**不**代表已验证 / 已保证 / 已放行。
    `enforced=False` 钉死该语义；调用方不得把它当硬门。
    """

    violations = [
        {"code": v.code, "message": v.message, "field": v.field, "ref": v.ref}
        for v in (getattr(decision, "violations", ()) or ())
    ]
    return {
        "boundary": boundary,
        "ok": bool(getattr(decision, "accepted", False)),
        "advisory": True,
        "enforced": False,
        "violations": violations,
    }


def _strategy_candidate_boundary_verdict(payload: dict, candidate_id: str) -> dict[str, Any]:
    """§9 `validate_strategy_book` 的 advisory 接线（退役因子默认采用边界）。

    生产现实（诚实 · RULES §3）：StrategyBookContract / pydantic StrategyBook 都**无原生
    生产端构造方**（仅测试构造），故 strategy-book 整契约属 library-ahead-of-path。本助手在
    **候选交接**（submit_candidate = 新策略 admit）这一真实路径上，把 `factor_set` 里**能解析到
    FACTOR_REGISTRY 的因子**当作「该候选默认采用」，交给 `validate_strategy_book` 跑 GOAL §9
    「退役因子被新策略默认采用 → 拒」这条可证伪验收（advisory，不拒候选）。

    覆盖边界：仅 retired-factor-default-adoption（§9 criterion 4），且只覆盖 factor_set 里**能直接
    解析到 FACTOR_REGISTRY 的 factor_id**。strategy-book 的 short-intent 执行检查（criterion 3）与
    run_config 数学绑定（criterion 5）在此路径上**无结构化输入**（submit_candidate 不带 legs /
    signal_refs / math_refs），仍属 KNOWN_RUN_GAP。

    诚实边界（RULES §3，关键）：不透明 `factor_set_id`（如 UI 的 "fs_core3"）**无法**解析到成员
    factor_id——本仓库无 fs_id→members 注册表（compose 的 fs_id 是 content_hash，不落可解析存储），
    属 KNOWN_RUN_GAP。这类 ref 计入 `unresolved_factor_refs` 并置 `evaluated=False`：此时 `ok=True`
    **只表「无可证伪退役采用」而非「整本已查清」**，消费方**必须**看 `evaluated`，不得当干净通过。
    （补充：退役采用在真实 UI 流里其实已被上游 `factor_set.compose` 的 QUALIFIED+ 血统门挡在
    factor_set 之外——RETIRED 因子根本进不了 compose 出的 factor_set；本 advisory 补的是直接给
    submit_candidate 传裸 factor_id 绕过 compose 的那条路径。）
    """

    raw = payload.get("factor_set")
    if isinstance(raw, str):
        candidate_refs = [s.strip() for s in raw.split(",") if s.strip()]
    elif isinstance(raw, (list, tuple)):
        candidate_refs = [str(x).strip() for x in raw if str(x).strip()]
    else:
        candidate_refs = []

    factor_library: dict[str, FactorLibraryEntry] = {}
    resolved_refs: list[str] = []
    unresolved_refs: list[str] = []
    for ref in candidate_refs:
        try:
            resolved = FACTOR_REGISTRY.get(ref)
        except KeyError:
            unresolved_refs.append(ref)  # 不透明 set-id / 非因子标签：无法判定 → 记 unresolved，不假装查过
            continue
        resolved_refs.append(ref)
        factor_library[ref] = FactorLibraryEntry(
            factor_ref=ref,
            kind=FactorAssetKind.EXPRESSION,
            ref=resolved.formula,
            lifecycle_state=str(resolved.lifecycle_state),
        )
    book = StrategyBookContract(
        strategy_book_ref=str(candidate_id or "candidate"),
        factor_refs=tuple(resolved_refs),
        signal_refs=(),
        legs=(),
        default_factor_refs=tuple(resolved_refs),
    )
    verdict = _boundary_verdict_payload(
        validate_strategy_book(book, factor_library=factor_library),
        boundary="strategy_book_§9",
    )
    verdict["resolved_factor_refs"] = resolved_refs
    verdict["unresolved_factor_refs"] = unresolved_refs
    # 诚实：有未解析 ref（含不透明 factor_set_id）时 evaluated=False —— ok=True 不等于「整本已查清」。
    verdict["evaluated"] = not unresolved_refs
    verdict["coverage"] = (
        "retired_factor_default_adoption over registry-resolvable factor_ids only; "
        "opaque factor_set_id (no fs_id->members registry), short-intent execution, and "
        "run_config math binding remain KNOWN_RUN_GAP"
    )
    return verdict


def _record_factor_qro(factor: Any, check: Any, *, actor: str, overwrite: bool = False) -> dict[str, Any]:
    factor_id = str(getattr(factor, "factor_id", "") or "").strip()
    version = int(getattr(factor, "version", 0) or 0)
    formula = str(getattr(factor, "formula", "") or "")
    formula_hash = content_hash({"formula": formula})
    params = getattr(factor, "params", {}) if isinstance(getattr(factor, "params", {}), dict) else {}
    params_hash = content_hash({"params": params})
    factor_ref = f"factor:{factor_id}:v{version}"
    evidence_refs = (
        factor_ref,
        f"factor_formula_hash:{formula_hash}",
        f"factor_params_hash:{params_hash}",
        "factor_register_gate:compiled",
        "factor_register_gate:no_lookahead",
        "factor_register_gate:name_available",
    )
    qro = QRORecord(
        qro_type=QROType.FACTOR,
        owner=actor,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "factor_id": factor_id,
            "version": version,
            "formula_hash": formula_hash,
            "params_hash": params_hash,
            "overwrite": bool(overwrite),
        },
        output_contract={
            "factor_ref": factor_ref,
            "lifecycle_state": str(getattr(factor, "lifecycle_state", "") or ""),
            "compiled": bool(getattr(check, "compiled", False)),
            "no_lookahead": bool(getattr(check, "no_lookahead", False)),
            "name_available": bool(getattr(check, "name_available", False)),
        },
        market="unspecified",
        universe=f"factor:{factor_id}",
        horizon="factor_formula",
        frequency="factor_formula",
        lineage=("factor_registry", factor_ref, f"formula_hash:{formula_hash}"),
        implementation_hash="factor_register:" + content_hash(
            {
                "factor_id": factor_id,
                "version": version,
                "formula_hash": formula_hash,
                "params_hash": params_hash,
                "lifecycle_state": str(getattr(factor, "lifecycle_state", "") or ""),
            }
        ),
        assumptions=("factor registration precheck uses synthetic shift-invariance panel",),
        known_limits=("formula registration is not alpha validation", "formula body is stored in factor registry, not compiler IR"),
        failure_modes=("compile gate failure", "lookahead gate failure", "duplicate factor id"),
        validation_plan=("run factor audit and signal/strategy validation before promotion",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        allowed_environment=RuntimeStatus.OFFLINE,
        evidence_refs=evidence_refs,
        permission="factor_register_no_runtime_side_effect",
        responsibility_boundary="records factor formula registration only; does not validate alpha or tradeability",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=("api:factors", factor_ref),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:factors",
        pass_name="api_factor_qro_to_factor_ir",
        validation_refs=(
            f"validation:factor_register:{factor_ref}",
            "factor_register_gate:compiled",
            "factor_register_gate:no_lookahead",
            "factor_register_gate:name_available",
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:factor_register:offline:v1",
        deterministic_run_plan_ref=f"runplan:factor_register:{factor_ref}",
        rollback_ref=f"rollback:factor_register:{factor_ref}",
        tool_record_refs=("api:factors", factor_ref),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.FACTOR.value}", factor_ref),
        canonical_command_refs=(f"research_graph_command:{command_id}", factor_ref),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_factor_audit_qro(
    factor: Any,
    report: Any,
    *,
    actor: str,
    market_data_use_validation_refs: Iterable[str],
) -> dict[str, Any]:
    factor_id = str(getattr(factor, "factor_id", "") or "").strip()
    version = int(getattr(factor, "version", 0) or 0)
    formula = str(getattr(factor, "formula", "") or "")
    factor_ref = f"factor:{factor_id}:v{version}"
    formula_hash = content_hash({"formula": formula})
    report_payload = report.to_dict() if hasattr(report, "to_dict") else {}
    report_hash = content_hash(report_payload)
    thresholds = report_payload.get("thresholds") if isinstance(report_payload.get("thresholds"), dict) else {}
    thresholds_overridden = (
        report_payload.get("thresholds_overridden")
        if isinstance(report_payload.get("thresholds_overridden"), dict)
        else {}
    )
    threshold_hash = content_hash({"thresholds": thresholds, "overridden": thresholds_overridden})
    checks = report_payload.get("checks") if isinstance(report_payload.get("checks"), list) else []
    check_summaries = []
    for raw_check in checks:
        if not isinstance(raw_check, dict):
            continue
        key = str(raw_check.get("key") or "").strip()
        if not key:
            continue
        passed = bool(raw_check.get("passed"))
        severe = bool(raw_check.get("severe"))
        check_summaries.append({"key": key, "passed": passed, "severe": severe})
    check_summary_hash = content_hash(check_summaries)
    severe_failed = sum(1 for check in check_summaries if check["severe"] and not check["passed"])
    passed_checks = sum(1 for check in check_summaries if check["passed"])
    verdict = str(getattr(report, "verdict", "") or report_payload.get("verdict") or "")
    market = str(getattr(report, "market", "") or report_payload.get("market") or "unspecified")
    horizon = str(getattr(report, "horizon", "") or report_payload.get("horizon") or "factor_audit")
    tier = str(getattr(report, "tier", "") or report_payload.get("tier") or "standard")
    n_trials = int(getattr(report, "n_trials", 0) or report_payload.get("n_trials") or 0)
    validation_dossier_ref = f"validation_dossier:{factor_ref}:audit:{report_hash}"
    validation_refs = tuple(str(ref).strip() for ref in market_data_use_validation_refs if str(ref).strip())
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_status = EvidenceStatus.INSUFFICIENT if verdict in {"concern", "blocked"} else EvidenceStatus.CHALLENGED
    governance_status = GovernanceStatus.REJECTED if verdict == "blocked" else GovernanceStatus.UNREVIEWED
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                factor_ref,
                validation_dossier_ref,
                f"factor_formula_hash:{formula_hash}",
                f"factor_audit_report_hash:{report_hash}",
                f"factor_audit_threshold_hash:{threshold_hash}",
                f"factor_audit_check_summary_hash:{check_summary_hash}",
                f"factor_audit_verdict:{verdict}",
                *(f"factor_audit_check:{item['key']}:{'passed' if item['passed'] else 'failed'}" for item in check_summaries),
                *validation_refs,
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.VALIDATION_DOSSIER,
        owner=actor,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "factor_ref": factor_ref,
            "formula_hash": formula_hash,
            "market": market,
            "horizon": horizon,
            "tier": tier,
            "n_trials": n_trials,
            "threshold_hash": threshold_hash,
            "check_summary_hash": check_summary_hash,
            "market_data_use_validation_refs": list(validation_refs),
        },
        output_contract={
            "validation_dossier_ref": validation_dossier_ref,
            "factor_ref": factor_ref,
            "verdict": verdict,
            "report_hash": report_hash,
            "checks_total": len(check_summaries),
            "checks_passed": passed_checks,
            "severe_failed_count": severe_failed,
            "market_data_use_validation_refs": list(validation_refs),
        },
        market=market,
        universe=f"factor:{factor_id}",
        horizon=f"factor_audit_h{horizon}",
        frequency="factor_audit",
        lineage=("factor_audit", factor_ref, validation_dossier_ref, f"report_hash:{report_hash}", *validation_refs),
        implementation_hash="factor_audit:" + content_hash(
            {
                "factor_ref": factor_ref,
                "formula_hash": formula_hash,
                "report_hash": report_hash,
                "threshold_hash": threshold_hash,
                "check_summary_hash": check_summary_hash,
                "verdict": verdict,
                "market_data_use_validation_refs": validation_refs,
            }
        ),
        assumptions=(
            "factor audit report was computed by the existing multi-evidence audit primitives",
            "each listed MarketDataUse validation ref resolved to an accepted no-violation record covering this market and PIT timing refs",
        ),
        known_limits=(
            "records audit refs and hashes, not the raw factor formula or raw return panels",
            "a factor audit dossier is not strategy promotion, portfolio construction, or execution permission",
            "MarketDataUse validation refs are not proof that the audit consumed every declared dataset row",
        ),
        failure_modes=("factor panel construction failure", "insufficient evidence verdict", "later strategy or portfolio validation rejection"),
        validation_plan=("bind accepted signal, strategy, portfolio, market-data, and execution refs before promotion claims",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=evidence_status,
        governance_status=governance_status,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="factor_audit:no_runtime_side_effect",
        allowed_environment=RuntimeStatus.OFFLINE,
        responsibility_boundary="records factor audit dossier refs and hashes only; does not approve alpha, strategy, portfolio, or execution readiness",
        verdict=verdict,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=("api:factors.audit", factor_ref, validation_dossier_ref),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:factors.audit",
        pass_name="api_factor_audit_qro_to_validation_dossier_ir",
        validation_refs=(
            validation_dossier_ref,
            f"factor_audit_verdict:{verdict}",
            f"factor_audit_report_hash:{report_hash}",
            *validation_refs,
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:factor_audit:offline:v1",
        deterministic_run_plan_ref=f"runplan:factor_audit:{factor_ref}:{report_hash}",
        rollback_ref=f"rollback:factor_audit:{factor_ref}:{report_hash}",
        tool_record_refs=("api:factors.audit", factor_ref, validation_dossier_ref),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.VALIDATION_DOSSIER.value}", validation_dossier_ref),
        canonical_command_refs=(f"research_graph_command:{command_id}", validation_dossier_ref),
    )
    return {
        "qro_id": qro.qro_id,
        "research_graph_command_id": command_id,
        "validation_dossier_ref": validation_dossier_ref,
        "market_data_use_validation_refs": list(validation_refs),
        **compiler_refs,
    }


_FACTOR_MARKET_ASSET_ALIASES: dict[str, set[str]] = {
    "equity_cn": {"equity_cn", "a_share", "stocks_cn", "cn_equity"},
    "a_share": {"equity_cn", "a_share", "stocks_cn", "cn_equity"},
    "stocks_cn": {"equity_cn", "a_share", "stocks_cn", "cn_equity"},
    "cn_equity": {"equity_cn", "a_share", "stocks_cn", "cn_equity"},
    "crypto": {"crypto", "crypto_spot", "crypto_perp"},
    "crypto_spot": {"crypto", "crypto_spot", "crypto_perp"},
    "crypto_perp": {"crypto", "crypto_spot", "crypto_perp"},
}


def _factor_market_asset_aliases(market: str) -> set[str]:
    normalized = str(market or "").strip().lower()
    return _FACTOR_MARKET_ASSET_ALIASES.get(normalized, {normalized} if normalized else set())


def _factor_market_data_use_validation_refs(
    payload: dict[str, Any],
    *,
    market: str,
    operation_label: str,
    market_coverage_label: str,
) -> tuple[str, ...]:
    raw_refs = payload.get("market_data_use_validation_refs", _MISSING_MARKET_DATA_USE_REFS)
    if raw_refs is _MISSING_MARKET_DATA_USE_REFS or raw_refs in (None, "", [], ()):
        raise HTTPException(
            status_code=422,
            detail=f"market_data_use_validation_refs is required for {operation_label}",
        )
    if isinstance(raw_refs, (str, bytes)) or not isinstance(raw_refs, (list, tuple)):
        raise HTTPException(
            status_code=422,
            detail="market_data_use_validation_refs must be a list of refs",
        )

    expected_assets = _factor_market_asset_aliases(market)
    validation_refs: list[str] = []
    covers_market = False
    for idx, raw_ref in enumerate(raw_refs):
        validation_ref = str(raw_ref or "").strip()
        if not validation_ref:
            raise HTTPException(
                status_code=422,
                detail=f"market_data_use_validation_refs[{idx}] must be a non-empty ref",
            )
        try:
            record = MARKET_DATA_REGISTRY.use_validation(validation_ref)
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"unknown market data use validation: {validation_ref}",
            ) from exc
        if not bool(getattr(record, "accepted", False)):
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} is not accepted",
            )
        violation_codes = tuple(getattr(record, "violation_codes", ()) or ())
        if violation_codes:
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} has unresolved violations",
            )

        use_context = str(getattr(record, "use_context", "") or "").strip()
        allowed_contexts = {
            ValidationUseContext.BACKTEST.value,
            ValidationUseContext.CONFIRMATORY_VALIDATION.value,
        }
        if use_context not in allowed_contexts:
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} is not for backtest use",
            )

        dataset_refs = tuple(str(ref) for ref in getattr(record, "dataset_refs", ()) or ())
        if not dataset_refs:
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} has no dataset refs",
            )
        for dataset_ref in dataset_refs:
            try:
                dataset = MARKET_DATA_REGISTRY.dataset(dataset_ref)
            except KeyError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"unknown dataset semantics for market data use validation {validation_ref}: {dataset_ref}",
                ) from exc
            if not (
                getattr(dataset, "known_at_ref", None)
                and getattr(dataset, "effective_at_ref", None)
                and getattr(dataset, "pit_bitemporal_rules_ref", None)
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"market data use validation {validation_ref} is missing PIT timing refs",
                )

        capability_ref = str(getattr(record, "capability_matrix_ref", "") or "").strip()
        if not capability_ref:
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} has no capability_matrix_ref",
            )
        try:
            capability = MARKET_DATA_REGISTRY.capability_matrix(capability_ref)
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"unknown capability matrix for market data use validation {validation_ref}: {capability_ref}",
            ) from exc
        if not bool(getattr(capability, "backtest", False)):
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} does not allow backtest",
            )
        capability_asset = str(getattr(capability, "asset_class", "") or "").strip().lower()
        if capability_asset in expected_assets:
            covers_market = True

        instrument_refs = tuple(str(ref) for ref in getattr(record, "instrument_refs", ()) or ())
        if not instrument_refs:
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} has no instrument refs",
            )
        for instrument_ref in instrument_refs:
            try:
                instrument = MARKET_DATA_REGISTRY.instrument(instrument_ref)
            except KeyError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"unknown instrument spec for market data use validation {validation_ref}: {instrument_ref}",
                ) from exc
            instrument_asset = str(getattr(instrument, "asset_class", "") or "").strip().lower()
            if instrument_asset in expected_assets:
                covers_market = True
        validation_refs.append(validation_ref)

    if not covers_market:
        raise HTTPException(
            status_code=422,
            detail=f"market_data_use_validation_refs do not cover {market_coverage_label}: {market}",
        )
    return tuple(dict.fromkeys(validation_refs))


def _factor_layered_market_data_use_validation_refs(
    payload: dict[str, Any],
    *,
    market: str,
) -> tuple[str, ...]:
    return _factor_market_data_use_validation_refs(
        payload,
        market=market,
        operation_label="factor layered backtests",
        market_coverage_label="factor layered backtest market",
    )


def _factor_audit_market_data_use_validation_refs(
    payload: dict[str, Any],
    *,
    market: str,
) -> tuple[str, ...]:
    return _factor_market_data_use_validation_refs(
        payload,
        market=market,
        operation_label="factor audits",
        market_coverage_label="factor audit market",
    )


def _factor_preview_market_data_use_validation_refs(
    payload: dict[str, Any],
    *,
    market: str,
) -> tuple[str, ...]:
    return _factor_market_data_use_validation_refs(
        payload,
        market=market,
        operation_label="factor preview validations",
        market_coverage_label="factor preview market",
    )


def _run_report_market_data_use_validation_refs(
    run_id: str,
    raw_refs: list[str] | None,
    *,
    operation_label: str,
) -> tuple[str, ...]:
    from .run_detail_core import load_run

    run = load_run(run_id)
    market = str((run.manifest or {}).get("market") or "").strip()
    if not market:
        raise HTTPException(
            status_code=422,
            detail=f"run {run_id} has no market for market_data_use_validation_refs coverage",
        )
    return _factor_market_data_use_validation_refs(
        {"market_data_use_validation_refs": raw_refs},
        market=market,
        operation_label=operation_label,
        market_coverage_label="run report market",
    )


def _record_factor_layered_backtest_qro(
    factor: Any,
    report: Any,
    *,
    actor: str,
    market: str,
    market_data_use_validation_refs: Iterable[str],
) -> dict[str, Any]:
    factor_id = str(getattr(factor, "factor_id", "") or "").strip()
    version = int(getattr(factor, "version", 0) or 0)
    formula = str(getattr(factor, "formula", "") or "")
    factor_ref = f"factor:{factor_id}:v{version}"
    formula_hash = content_hash({"formula": formula})
    report_payload = report.to_dict() if hasattr(report, "to_dict") else {}
    report_hash = content_hash(report_payload)
    horizon = int(getattr(report, "horizon", 0) or report_payload.get("horizon") or 0)
    n_quantiles = int(getattr(report, "n_quantiles", 0) or report_payload.get("n_quantiles") or 0)
    effective_quantiles = int(
        getattr(report, "effective_quantiles", 0) or report_payload.get("effective_quantiles") or 0
    )
    sample_count = int(getattr(report, "sample_count", 0) or report_payload.get("sample_count") or 0)
    monotonic = bool(getattr(report, "monotonic", False) or report_payload.get("monotonic"))
    buckets = report_payload.get("buckets") if isinstance(report_payload.get("buckets"), list) else []
    backtest_run_ref = f"backtest_run:{factor_ref}:layered:{report_hash}"
    validation_refs = tuple(str(ref).strip() for ref in market_data_use_validation_refs if str(ref).strip())
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                factor_ref,
                backtest_run_ref,
                f"factor_formula_hash:{formula_hash}",
                f"factor_layered_report_hash:{report_hash}",
                f"factor_layered_monotonic:{str(monotonic).lower()}",
                f"factor_layered_effective_quantiles:{effective_quantiles}",
                *validation_refs,
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.BACKTEST_RUN,
        owner=actor,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "factor_ref": factor_ref,
            "formula_hash": formula_hash,
            "market": market,
            "horizon": horizon,
            "n_quantiles": n_quantiles,
            "market_data_use_validation_refs": list(validation_refs),
        },
        output_contract={
            "backtest_run_ref": backtest_run_ref,
            "factor_ref": factor_ref,
            "report_hash": report_hash,
            "effective_quantiles": effective_quantiles,
            "bucket_count": len(buckets),
            "sample_count": sample_count,
            "monotonic": monotonic,
            "market_data_use_validation_refs": list(validation_refs),
        },
        market=market,
        universe=f"factor:{factor_id}",
        horizon=f"factor_layered_h{horizon}",
        frequency="factor_layered_backtest",
        lineage=("factor_layered_backtest", factor_ref, backtest_run_ref, f"report_hash:{report_hash}", *validation_refs),
        implementation_hash="factor_layered_backtest:" + content_hash(
            {
                "factor_ref": factor_ref,
                "formula_hash": formula_hash,
                "report_hash": report_hash,
                "horizon": horizon,
                "n_quantiles": n_quantiles,
                "effective_quantiles": effective_quantiles,
                "sample_count": sample_count,
                "monotonic": monotonic,
                "market_data_use_validation_refs": validation_refs,
            }
        ),
        assumptions=(
            "layered factor backtest used the existing point-in-time quantile diagnostic",
            "each listed MarketDataUse validation ref resolved to an accepted no-violation record covering this market and PIT timing refs",
        ),
        known_limits=(
            "records layered backtest refs and hashes, not raw buckets, raw returns, or the factor formula",
            "a layered diagnostic is not alpha approval, cost-aware strategy performance, portfolio promotion, or execution permission",
            "MarketDataUse validation refs are not proof that the diagnostic consumed every declared dataset row",
        ),
        failure_modes=("factor panel construction failure", "insufficient cross-section breadth", "later audit or strategy validation rejection"),
        validation_plan=("bind factor audit, strategy backtest, market-data, signal, portfolio, and execution refs before promotion claims",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="factor_layered_backtest:no_runtime_side_effect",
        allowed_environment=RuntimeStatus.OFFLINE,
        responsibility_boundary="records factor layered diagnostic refs and hashes only; does not approve alpha, strategy, portfolio, or execution readiness",
        verdict="exploratory",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=("api:factors.layered_backtest", factor_ref, backtest_run_ref),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:factors.layered_backtest",
        pass_name="api_factor_layered_backtest_qro_to_backtest_ir",
        validation_refs=(
            backtest_run_ref,
            f"factor_layered_report_hash:{report_hash}",
            f"factor_layered_monotonic:{str(monotonic).lower()}",
            *validation_refs,
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:factor_layered_backtest:offline:v1",
        deterministic_run_plan_ref=f"runplan:factor_layered_backtest:{factor_ref}:{report_hash}",
        rollback_ref=f"rollback:factor_layered_backtest:{factor_ref}:{report_hash}",
        tool_record_refs=("api:factors.layered_backtest", factor_ref, backtest_run_ref),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.BACKTEST_RUN.value}", backtest_run_ref),
        canonical_command_refs=(f"research_graph_command:{command_id}", backtest_run_ref),
    )
    return {
        "qro_id": qro.qro_id,
        "research_graph_command_id": command_id,
        "backtest_run_ref": backtest_run_ref,
        "market_data_use_validation_refs": list(validation_refs),
        **compiler_refs,
    }


def _record_factor_preview_validation_qro(
    *,
    formula: str,
    result: dict[str, Any],
    actor: str,
    market: str,
    horizon: int,
    market_data_use_validation_refs: Iterable[str] = (),
) -> dict[str, Any]:
    formula_hash = content_hash({"formula": formula})
    valid = bool(result.get("valid"))
    stage = str(result.get("stage") or "unknown")
    reason = str(result.get("reason") or "")
    reason_hash = content_hash({"reason": reason}) if reason else ""
    ic_payload = result.get("ic") if isinstance(result.get("ic"), dict) else {}
    ic_summary_hash = content_hash({"ic": ic_payload}) if ic_payload else ""
    validation_refs = tuple(str(ref).strip() for ref in market_data_use_validation_refs if str(ref).strip())
    result_hash = content_hash(
        {
            "valid": valid,
            "stage": stage,
            "reason_hash": reason_hash,
            "ic_summary_hash": ic_summary_hash,
            "market": market,
            "horizon": horizon,
            "market_data_use_validation_refs": validation_refs,
        }
    )
    validation_dossier_ref = f"validation_dossier:factor_preview:{formula_hash}:{stage}:{result_hash}"
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                validation_dossier_ref,
                f"factor_preview_formula_hash:{formula_hash}",
                f"factor_preview_stage:{stage}",
                f"factor_preview_valid:{str(valid).lower()}",
                f"factor_preview_result_hash:{result_hash}",
                f"factor_preview_reason_hash:{reason_hash}" if reason_hash else "",
                f"factor_preview_ic_summary_hash:{ic_summary_hash}" if ic_summary_hash else "",
                *validation_refs,
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.VALIDATION_DOSSIER,
        owner=actor,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "formula_hash": formula_hash,
            "market": market,
            "horizon": horizon,
            "market_data_use_validation_refs": list(validation_refs),
        },
        output_contract={
            "validation_dossier_ref": validation_dossier_ref,
            "valid": valid,
            "stage": stage,
            "result_hash": result_hash,
            "reason_hash": reason_hash,
            "ic_summary_hash": ic_summary_hash,
            "ic_metric_count": len(ic_payload),
            "market_data_use_validation_refs": list(validation_refs),
        },
        market=market,
        universe="factor_preview",
        horizon=f"factor_preview_h{horizon}",
        frequency="factor_preview",
        lineage=("factor_preview_validate", validation_dossier_ref, f"formula_hash:{formula_hash}", *validation_refs),
        implementation_hash="factor_preview_validate:" + content_hash(
            {
                "formula_hash": formula_hash,
                "result_hash": result_hash,
                "stage": stage,
                "valid": valid,
                "market": market,
                "horizon": horizon,
                "market_data_use_validation_refs": validation_refs,
            }
        ),
        assumptions=(
            "factor preview validation ran compile/lookahead gates and optional IC preview without registering a factor",
            "when IC preview is present, each listed MarketDataUse validation ref resolved to an accepted no-violation record covering this market and PIT timing refs",
        ),
        known_limits=(
            "records preview validation refs and hashes, not the raw formula, raw IC values, or return panels",
            "a preview validation dossier is not factor registration, alpha approval, strategy promotion, or execution permission",
            "MarketDataUse validation refs are not proof that the preview consumed every declared dataset row",
        ),
        failure_modes=("compile rejection", "lookahead rejection", "IC preview panel construction failure", "later factor audit rejection"),
        validation_plan=("register the factor, run factor audit and strategy validation, then bind downstream refs before promotion claims",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY if valid else EvidenceStatus.INSUFFICIENT,
        governance_status=GovernanceStatus.UNREVIEWED if valid else GovernanceStatus.REJECTED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="factor_preview_validate:no_runtime_side_effect",
        allowed_environment=RuntimeStatus.OFFLINE,
        responsibility_boundary="records factor preview validation refs and hashes only; does not register, approve, promote, or execute the factor",
        verdict="exploratory" if valid else "rejected",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=("api:factors.validate", validation_dossier_ref),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:factors.validate",
        pass_name="api_factor_preview_validation_qro_to_validation_dossier_ir",
        validation_refs=(
            validation_dossier_ref,
            f"factor_preview_stage:{stage}",
            f"factor_preview_valid:{str(valid).lower()}",
            *validation_refs,
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:factor_preview_validate:offline:v1",
        deterministic_run_plan_ref=f"runplan:factor_preview_validate:{formula_hash}:{stage}:{result_hash}",
        rollback_ref=f"rollback:factor_preview_validate:{formula_hash}:{stage}:{result_hash}",
        tool_record_refs=("api:factors.validate", validation_dossier_ref),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.VALIDATION_DOSSIER.value}", validation_dossier_ref),
        canonical_command_refs=(f"research_graph_command:{command_id}", validation_dossier_ref),
    )
    return {
        "qro_id": qro.qro_id,
        "research_graph_command_id": command_id,
        "validation_dossier_ref": validation_dossier_ref,
        "market_data_use_validation_refs": list(validation_refs),
        **compiler_refs,
    }


def _record_signal_contract_qro(contract: Any, *, actor: str) -> dict[str, Any]:
    signal_ref = str(getattr(contract, "signal_ref", "") or "").strip()
    signal_id = str(getattr(contract, "signal_id", "") or "").strip()
    model_ref = str(getattr(contract, "model_ref", "") or "").strip()
    source_lib = str(getattr(contract, "source_lib", "") or "").strip()
    output_kind = str(getattr(contract, "output_kind", "") or "").strip()
    horizon = str(getattr(contract, "horizon", "") or "").strip() or "unspecified"
    leakage = getattr(contract, "leakage", None)
    leakage_dict = leakage.to_dict() if hasattr(leakage, "to_dict") else {}
    model_ref_hash = content_hash({"model_ref": model_ref})
    evidence_refs = (
        f"signal_contract:{signal_ref}",
        f"signal_model_ref_hash:{model_ref_hash}",
        f"signal_leakage_declaration:{signal_id}",
    )
    qro = QRORecord(
        qro_type=QROType.SIGNAL,
        owner=actor,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "source_lib": source_lib,
            "model_ref_hash": model_ref_hash,
            "output_kind": output_kind,
            "horizon": horizon,
            "leakage_declared": bool(
                leakage_dict.get("oof") and leakage_dict.get("purge") and leakage_dict.get("embargo")
            ),
        },
        output_contract={
            "signal_ref": signal_ref,
            "signal_id": signal_id,
            "signal_contract_ref": f"signal_contract:{signal_ref}",
        },
        market="unspecified",
        universe=f"signal:{signal_ref}",
        horizon=horizon,
        frequency="signal_contract",
        lineage=("signal_contract_registry", signal_ref, f"model_ref_hash:{model_ref_hash}"),
        implementation_hash="signal_contract:" + content_hash(
            {
                "signal_ref": signal_ref,
                "source_lib": source_lib,
                "model_ref_hash": model_ref_hash,
                "output_kind": output_kind,
                "horizon": horizon,
                "leakage": leakage_dict,
            }
        ),
        assumptions=("leakage fields are declared by the caller",),
        known_limits=("signal contract is not alpha proof", "model body is only referenced by hash"),
        failure_modes=("missing leakage declaration", "orphan model reference", "model body registered as factor"),
        validation_plan=("require SignalPerformanceValidation before StrategyBook/portfolio promote consumes signal",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        allowed_environment=RuntimeStatus.OFFLINE,
        evidence_refs=evidence_refs,
        permission="offline_signal_contract_record",
        responsibility_boundary="records ML/DL output contract only; does not validate alpha or tradeability",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=("api:factors.signal_contracts", signal_ref),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:factors.signal_contracts",
        pass_name="api_signal_contract_qro_to_signal_ir",
        validation_refs=(f"validation:signal_contract:{signal_ref}", f"leakage_declaration:{signal_id}"),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:signal_contract:offline:v1",
        deterministic_run_plan_ref=f"runplan:signal_contract:{signal_id}",
        rollback_ref=f"rollback:signal_contract:{signal_id}",
        tool_record_refs=("api:factors.signal_contracts", signal_ref),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.SIGNAL.value}", f"signal_contract:{signal_ref}"),
        canonical_command_refs=(f"research_graph_command:{command_id}", f"signal_contract:{signal_ref}"),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_signal_validation_qro(record: SignalPerformanceValidationRecord, *, actor: str) -> dict[str, Any]:
    verdict = str(getattr(record.verdict, "value", record.verdict) or "")
    if verdict == "accepted":
        evidence_status = EvidenceStatus.SUFFICIENT
        governance_status = GovernanceStatus.APPROVED
    elif verdict == "rejected":
        evidence_status = EvidenceStatus.INSUFFICIENT
        governance_status = GovernanceStatus.REJECTED
    else:
        evidence_status = EvidenceStatus.CHALLENGED
        governance_status = GovernanceStatus.UNREVIEWED
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                *tuple(record.evidence_refs),
                record.validation_id,
                record.validation_dataset_ref,
                record.evaluation_window_ref,
                record.methodology_ref,
                record.performance_summary_ref,
                record.leakage_check_ref,
                record.regime_check_ref,
                record.capacity_check_ref,
                *tuple(record.known_limits_refs),
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.SIGNAL,
        owner=actor,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "signal_ref": record.signal_ref,
            "validation_dataset_ref": record.validation_dataset_ref,
            "evaluation_window_ref": record.evaluation_window_ref,
            "methodology_ref": record.methodology_ref,
            "metric_refs": tuple(record.metric_refs),
            "leakage_check_ref": record.leakage_check_ref,
            "regime_check_ref": record.regime_check_ref,
            "capacity_check_ref": record.capacity_check_ref,
            "known_limits_refs": tuple(record.known_limits_refs),
        },
        output_contract={
            "validation_id": record.validation_id,
            "verdict": verdict,
            "performance_summary_ref": record.performance_summary_ref,
            "evidence_ref_count": len(record.evidence_refs),
        },
        market="unspecified",
        universe=f"signal:{record.signal_ref}",
        horizon="signal_validation",
        frequency="signal_validation",
        lineage=("signal_validation_registry", record.signal_ref, record.validation_id),
        implementation_hash="signal_validation:" + content_hash(record.to_dict()),
        assumptions=("validation record cites external evidence refs instead of raw predictions",),
        known_limits=tuple(dict.fromkeys((*tuple(record.known_limits_refs), "signal validation is not order emission proof"))),
        failure_modes=("missing validation evidence", "rejected validation", "unknown signal contract"),
        validation_plan=("require accepted validation before portfolio promote consumes signal_ref",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=evidence_status,
        governance_status=governance_status,
        runtime_status=RuntimeStatus.OFFLINE,
        allowed_environment=RuntimeStatus.OFFLINE,
        evidence_refs=evidence_refs,
        permission="offline_signal_validation_record",
        responsibility_boundary="records signal performance validation refs only; does not persist raw predictions or returns",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=("api:research_os.signal_validations", record.validation_id, record.signal_ref),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:research_os.signal_validations",
        pass_name="api_signal_validation_qro_to_signal_ir",
        validation_refs=(record.validation_id, record.performance_summary_ref, record.leakage_check_ref),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:signal_validation:offline:v1",
        deterministic_run_plan_ref=f"runplan:signal_validation:{record.validation_id}",
        rollback_ref=f"rollback:signal_validation:{record.validation_id}",
        tool_record_refs=("api:research_os.signal_validations", record.validation_id, record.signal_ref),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.SIGNAL.value}", f"signal_validation:{record.validation_id}"),
        canonical_command_refs=(f"research_graph_command:{command_id}", f"signal_validation:{record.validation_id}"),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_portfolio_promote_qro(
    *,
    portfolio_id: str,
    weights: dict[str, float],
    asset_returns: dict[str, list[float]],
    markets: list[str],
    dataset_version: str,
    freq: str,
    signal_refs: tuple[str, ...],
    signal_validation_refs: tuple[str, ...],
    market_data_use_validation_refs: tuple[str, ...],
    strategy_goal_ref: str,
    honest_n_before: int,
    result: Any,
    actor: str,
) -> dict[str, Any]:
    symbols = tuple(weights)
    composition = portfolio_composition(weights)
    weights_hash = content_hash({"composition": composition})
    returns_hash = content_hash(
        {
            symbol: content_hash([float(value) for value in asset_returns[symbol]])
            for symbol in sorted(asset_returns)
        }
    )
    returns_count_by_symbol = {symbol: len(asset_returns[symbol]) for symbol in sorted(asset_returns)}
    verdict = result.verdict.to_dict()
    verdict_hash = content_hash(verdict)
    color = str(verdict.get("color") or "")
    if color == "green":
        evidence_status = EvidenceStatus.SUFFICIENT
    elif color == "red":
        evidence_status = EvidenceStatus.INSUFFICIENT
    else:
        evidence_status = EvidenceStatus.CHALLENGED
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                strategy_goal_ref,
                result.config_hash,
                dataset_version,
                f"portfolio_gate:{portfolio_id}:{result.config_hash}",
                *signal_refs,
                *signal_validation_refs,
                *market_data_use_validation_refs,
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.PORTFOLIO_POLICY,
        owner=actor,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "portfolio_id": portfolio_id,
            "strategy_goal_ref": strategy_goal_ref,
            "symbols": symbols,
            "markets": tuple(markets),
            "dataset_version": dataset_version,
            "freq": freq,
            "weights_hash": weights_hash,
            "returns_hash": returns_hash,
            "returns_count_by_symbol": returns_count_by_symbol,
            "signal_refs": signal_refs,
            "signal_validation_refs": signal_validation_refs,
            "market_data_use_validation_refs": market_data_use_validation_refs,
        },
        output_contract={
            "promote_state": "gate_recorded",
            "config_hash": result.config_hash,
            "gate_verdict_color": color,
            "gate_verdict_hash": verdict_hash,
            "honest_n_before": honest_n_before,
            "honest_n_after": result.honest_n,
            "honest_n_delta": result.honest_n - honest_n_before,
        },
        market="multi_asset",
        universe=f"portfolio:{portfolio_id}",
        horizon="portfolio_gate",
        frequency=freq,
        lineage=("portfolio_promote_gate", strategy_goal_ref, result.config_hash),
        implementation_hash="portfolio_promote:" + content_hash(
            {
                "portfolio_id": portfolio_id,
                "dataset_version": dataset_version,
                "freq": freq,
                "weights_hash": weights_hash,
                "returns_hash": returns_hash,
                "signal_refs": signal_refs,
                "signal_validation_refs": signal_validation_refs,
                "market_data_use_validation_refs": market_data_use_validation_refs,
                "config_hash": result.config_hash,
                "gate_verdict_hash": verdict_hash,
            }
        ),
        assumptions=("caller supplied PIT-safe realized returns",),
        known_limits=("records portfolio gate evidence only", "does not flip stage or emit orders"),
        failure_modes=("missing market data validation", "missing signal validation", "overfit gate not green"),
        validation_plan=("human approval and execution boundary records are required before any runtime promotion",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=evidence_status,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        allowed_environment=RuntimeStatus.OFFLINE,
        evidence_refs=evidence_refs,
        permission="portfolio_promote_record_only",
        responsibility_boundary="records portfolio gate evidence only; no order, no money movement, no stage flip",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=("api:portfolios.promote", portfolio_id, strategy_goal_ref, result.config_hash),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:portfolios.promote",
        pass_name="api_portfolio_policy_qro_to_portfolio_ir",
        validation_refs=(
            f"portfolio_gate:{portfolio_id}:{result.config_hash}",
            *signal_validation_refs,
            *market_data_use_validation_refs,
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:portfolio_promote:record_only:v1",
        deterministic_run_plan_ref=f"runplan:portfolio_promote:{portfolio_id}:{result.config_hash}",
        rollback_ref=f"rollback:portfolio_promote:{portfolio_id}:{result.config_hash}",
        tool_record_refs=("api:portfolios.promote", portfolio_id, strategy_goal_ref, result.config_hash),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.PORTFOLIO_POLICY.value}", strategy_goal_ref),
        canonical_command_refs=(
            f"research_graph_command:{command_id}",
            f"portfolio_gate:{portfolio_id}:{result.config_hash}",
        ),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _compile_execution_boundary_qro(
    *,
    qro_id: str,
    graph_command_id: str,
    actor: str,
    entrypoint_ref: str,
    pass_name: str,
    record_ref: str,
    permission_ref: str,
    evidence_refs: Iterable[str],
    validation_refs: Iterable[str] = (),
) -> dict[str, str]:
    safe_pass = pass_name.replace(":", "_").replace(".", "_")
    return _compile_entrypoint_qro(
        qro_id=qro_id,
        graph_command_id=graph_command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref=entrypoint_ref,
        pass_name=pass_name,
        validation_refs=_compiler_unique_refs(
            validation_refs,
            evidence_refs,
            f"validation:{entrypoint_ref}:{record_ref}",
        ),
        evidence_refs=evidence_refs,
        environment_lock_ref=f"env:execution_boundary:{safe_pass}:v1",
        permission_ref=permission_ref,
        deterministic_run_plan_ref=f"runplan:{entrypoint_ref}:{record_ref}",
        rollback_ref=f"rollback:{entrypoint_ref}:{record_ref}:manual_review",
        tool_record_refs=(entrypoint_ref, record_ref),
        node_refs=(f"qro:{qro_id}", f"qro_type:{QROType.EXECUTION_POLICY.value}", record_ref),
        canonical_command_refs=(f"research_graph_command:{graph_command_id}", record_ref),
    )


def _record_weekly_monitor_qro(
    result: WeeklyMonitorResult,
    *,
    actor: str,
    scheduled: bool,
    asset_class: str,
    trigger: str,
    drift_threshold: float | None = None,
) -> dict[str, Any]:
    """Record and compile a weekly monitor tick without copying monitor payloads."""

    result_payload = result.to_dict()
    result_hash = content_hash(result_payload)
    now = _dt.datetime.now(_dt.UTC).isoformat()
    lifecycle_event_count = len(result.lifecycle_events)
    action_count = len(result.actions)
    actor_source = ActorSource.SCHEDULED_AGENT if scheduled else ActorSource.USER_MANUAL
    safe_actor = str(actor or (MONITOR_WEEKLY_OP if scheduled else "monitor_user"))
    evidence_refs = (
        f"monitor_weekly_tick:{result.week_iso}",
        f"monitor_result_hash:{result_hash}",
        f"scheduler_dag:{MONITOR_WEEKLY_DAG_NAME}",
    )
    qro = QRORecord(
        qro_type=QROType.OBSERVABLE,
        owner="scheduler" if scheduled else safe_actor,
        actor=actor_source,
        input_contract={
            "entry_source": EntrySource.SCHEDULER.value,
            "scheduler_dag": MONITOR_WEEKLY_DAG_NAME,
            "scheduler_op": MONITOR_WEEKLY_OP,
            "trigger": trigger,
            "week": result.week_iso,
            "asset_class": asset_class,
            "drift_threshold_hash": content_hash(drift_threshold) if drift_threshold is not None else None,
        },
        output_contract={
            "status": "completed",
            "result_hash": result_hash,
            "n_fills": result.n_fills,
            "factors_checked": result.factors_checked,
            "action_count": action_count,
            "lifecycle_event_count": lifecycle_event_count,
            "drift_pct_present": result.drift_pct is not None,
        },
        market=asset_class,
        universe="factor_lifecycle",
        horizon="weekly",
        frequency="weekly",
        lineage=("scheduler", MONITOR_WEEKLY_OP, result.week_iso, trigger),
        implementation_hash="monitor_weekly_tick:" + result_hash,
        assumptions=("The weekly monitor tick ran through the configured production monitor path.",),
        known_limits=(
            "This QRO records the scheduler monitor result summary, not raw factor observations or cost drift payloads.",
            "A monitor tick is not alpha evidence, production deployment proof, or live broker connectivity proof.",
        ),
        failure_modes=(
            "Missing schedule execution, stale factor registry state, missing observations, or incomplete execution audit data can produce weak monitor coverage.",
        ),
        validation_plan=(
            "Bind monitor refs into RDP deployment and lifecycle evidence before release claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission=f"monitor.weekly_tick:{'scheduled_agent' if scheduled else 'user_manual'}",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.SCHEDULER,
        command_type="upsert_qro",
        actor_source=actor_source,
        actor=safe_actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    graph_refs = {
        "qro_id": qro.qro_id,
        "research_graph_command_id": command_id,
        "research_graph_result_hash": result_hash,
    }
    compiler_refs = _compile_weekly_monitor_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        result_hash=result_hash,
        result=result,
        actor=safe_actor,
        actor_source=actor_source,
        scheduled=scheduled,
        asset_class=asset_class,
        trigger=trigger,
    )
    return {**graph_refs, **compiler_refs}


def _compile_weekly_monitor_qro(
    *,
    qro_id: str,
    graph_command_id: str,
    result_hash: str,
    result: WeeklyMonitorResult,
    actor: str,
    actor_source: ActorSource,
    scheduled: bool,
    asset_class: str,
    trigger: str,
) -> dict[str, Any]:
    """Compile scheduler Observable QRO into governed IR/pass and entrypoint coverage."""

    run_ref = content_hash(
        {
            "scheduler_dag": MONITOR_WEEKLY_DAG_NAME,
            "scheduler_op": MONITOR_WEEKLY_OP,
            "week": result.week_iso,
            "asset_class": asset_class,
            "trigger": trigger,
            "result_hash": result_hash,
        }
    )
    ir, compiler_pass = _compile_qro_payload(
        {
            "qro_id": qro_id,
            "validation_refs": (
                f"validation:monitor.weekly_tick:input_guard:v1",
                f"validation:monitor.weekly_tick:result_hash:{result_hash}",
            ),
            "environment_lock_ref": f"env:monitor.weekly_tick:{MONITOR_WEEKLY_DAG_NAME}:v1",
            "permission_ref": f"monitor.weekly_tick:{'scheduled_agent' if scheduled else 'user_manual'}",
            "pass_name": "scheduler_observable_qro_to_monitor_ir",
            "compiler_version": "governed-compiler-ir.v1",
            "deterministic_run_plan_ref": f"runplan:monitor.weekly_tick:{run_ref}",
            "rollback_ref": f"rollback:monitor.weekly_tick:{run_ref}:manual_review",
            "actor_source": actor_source.value if hasattr(actor_source, "value") else str(actor_source),
            "entry_source": EntrySource.SCHEDULER.value,
            "tool_record_refs": (
                f"scheduler_dag:{MONITOR_WEEKLY_DAG_NAME}",
                f"scheduler_op:{MONITOR_WEEKLY_OP}",
                f"trigger:{trigger}",
            ),
            "graph_command_refs": (graph_command_id,),
            "canonical_command_refs": (
                f"research_graph_command:{graph_command_id}",
                f"scheduler_op:{MONITOR_WEEKLY_OP}",
            ),
            "node_refs": (
                f"qro:{qro_id}",
                f"qro_type:{QROType.OBSERVABLE.value}",
                f"scheduler_op:{MONITOR_WEEKLY_OP}",
            ),
        },
        actor=actor,
    )
    coverage_candidate = _validate_goal_entrypoint_coverage_candidate(
        _goal_entrypoint_coverage_from_compiler_records(
            ir,
            compiler_pass,
            entrypoint_ref=f"scheduler:{MONITOR_WEEKLY_OP}",
        )
    )
    COMPILER_IR_STORE.record_ir(ir)
    COMPILER_IR_STORE.record_pass(compiler_pass)
    coverage = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(coverage_candidate)
    return {
        "compiler_ir_ref": ir.ir_ref,
        "compiler_pass_ref": compiler_pass.pass_ref,
        "entrypoint_coverage_ref": coverage.coverage_ref,
    }


def _record_weekly_monitor_qro_from_scheduler(
    result: WeeklyMonitorResult,
    context: dict[str, Any],
) -> dict[str, Any]:
    graph_refs = _record_weekly_monitor_qro(
        result,
        actor=str(context.get("actor") or MONITOR_WEEKLY_OP),
        scheduled=bool(context.get("scheduled", True)),
        asset_class=str(context.get("asset_class") or "crypto_perp"),
        trigger=str(context.get("trigger") or "dag"),
    )
    reconciliation_action_result = _run_pending_execution_reconciliation_actions(
        actor=str(context.get("actor") or MONITOR_WEEKLY_OP),
        audit_record_ref=f"audit:{MONITOR_WEEKLY_OP}:{result.week_iso}:execution_reconciliation_actions",
        evidence_refs=(graph_refs["qro_id"], graph_refs["research_graph_command_id"], f"monitor_weekly_tick:{result.week_iso}"),
        owner_ref=MONITOR_WEEKLY_OP,
    )
    return {
        **graph_refs,
        "execution_reconciliation_action_producer": reconciliation_action_result,
    }


def _record_training_job_qro(job: Any) -> dict[str, Any]:
    """Record a completed model training job as a Model QRO without copying metrics or artifact paths."""

    if getattr(job, "status", "") != "succeeded":
        raise ValueError("training QRO requires succeeded job")
    if getattr(job, "model_version", None) is None:
        raise ValueError("training QRO requires a registered model version")
    now = _dt.datetime.now(_dt.UTC).isoformat()
    request_payload = dict(getattr(job, "request", {}) or {})
    metrics_payload = dict(getattr(job, "metrics", {}) or {})
    model = str(getattr(job, "model", "") or "unknown")
    model_version = int(getattr(job, "model_version"))
    model_version_ref = f"model_version:{model}:v{model_version}"
    dataset_id = str(request_payload.get("dataset_id") or "unspecified")
    asset_class = str(request_payload.get("asset_class") or "unspecified")
    task = str(getattr(job, "task", "") or request_payload.get("task") or "unspecified")
    job_id = str(getattr(job, "job_id", "") or "")
    run_id = str(getattr(job, "run_id", "") or "")
    model_passport_ref = str(getattr(job, "model_passport_ref", "") or "")
    validation_dossier_ref = str(getattr(job, "validation_dossier_ref", "") or "")
    market_data_use_validation_refs = tuple(
        str(ref).strip()
        for ref in (request_payload.get("market_data_use_validation_refs") or ())
        if str(ref).strip()
    )
    request_hash = content_hash(request_payload)
    metrics_hash = content_hash(metrics_payload)
    evidence_refs = tuple(
        ref
        for ref in (
            f"training_job:{job_id}",
            f"training_run:{run_id}" if run_id else "",
            model_version_ref,
            model_passport_ref,
            validation_dossier_ref,
            *market_data_use_validation_refs,
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.MODEL,
        owner="training_service",
        actor=ActorSource.AGENT,
        input_contract={
            "entry_source": EntrySource.API.value,
            "job_id": job_id,
            "model": model,
            "task": task,
            "asset_class": asset_class,
            "dataset_id": dataset_id,
            "market_data_use_validation_refs": list(market_data_use_validation_refs),
            "feature_count": len(request_payload.get("feature_cols") or []),
            "request_hash": request_hash,
        },
        output_contract={
            "status": "succeeded",
            "job_id": job_id,
            "model": model,
            "model_version": model_version,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "validation_dossier_ref": validation_dossier_ref,
            "market_data_use_validation_refs": list(market_data_use_validation_refs),
            "run_id": run_id,
            "metrics_hash": metrics_hash,
        },
        market=asset_class,
        universe=dataset_id,
        horizon="training_job",
        frequency="training_job",
        lineage=("training", "job", job_id, model_version_ref, *market_data_use_validation_refs),
        implementation_hash="training_job:" + content_hash(
            {
                "job_id": job_id,
                "model_version_ref": model_version_ref,
                "request_hash": request_hash,
                "metrics_hash": metrics_hash,
            }
        ),
        assumptions=("The training service completed the job and registered a model version.",),
        known_limits=(
            "The Model QRO records training refs and hashes, not raw metrics, artifact paths, or model binaries.",
            "A successful training job is not promotion approval, live serving readiness, or execution permission.",
        ),
        failure_modes=(
            "The trained model can be overfit, economically invalid, unsafe to load, or rejected by later promotion gates.",
        ),
        validation_plan=(
            "Bind the model version to accepted MarketDataUseValidation, ModelPassport, ValidationDossier, promotion gates, monitor rules, and RDP before release claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="training.job:service",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.AGENT,
        actor="training_service",
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    graph_refs = {
        "qro_id": qro.qro_id,
        "research_graph_command_id": command_id,
    }
    compiler_refs = _compile_training_job_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        job_id=job_id,
        model=model,
        model_version_ref=model_version_ref,
        model_passport_ref=model_passport_ref,
        validation_dossier_ref=validation_dossier_ref,
        market_data_use_validation_refs=market_data_use_validation_refs,
        request_hash=request_hash,
        metrics_hash=metrics_hash,
    )
    return {**graph_refs, **compiler_refs}


def _compile_training_job_qro(
    *,
    qro_id: str,
    graph_command_id: str,
    job_id: str,
    model: str,
    model_version_ref: str,
    model_passport_ref: str,
    validation_dossier_ref: str,
    market_data_use_validation_refs: Iterable[str],
    request_hash: str,
    metrics_hash: str,
) -> dict[str, Any]:
    """Compile a successful training Model QRO into governed IR/pass and coverage."""

    run_ref = content_hash(
        {
            "job_id": job_id,
            "model": model,
            "model_version_ref": model_version_ref,
            "request_hash": request_hash,
            "metrics_hash": metrics_hash,
        }
    )
    validation_refs = tuple(
        ref
        for ref in (
            validation_dossier_ref,
            model_passport_ref,
            *tuple(str(ref).strip() for ref in market_data_use_validation_refs if str(ref).strip()),
            f"validation:training.job:registered_model_version:{model_version_ref}",
        )
        if ref
    )
    ir, compiler_pass = _compile_qro_payload(
        {
            "qro_id": qro_id,
            "validation_refs": validation_refs,
            "environment_lock_ref": f"env:training_service:{model}:v1",
            "permission_ref": "training.job:service",
            "pass_name": "api_training_model_qro_to_model_ir",
            "compiler_version": "governed-compiler-ir.v1",
            "deterministic_run_plan_ref": f"runplan:training.job:{run_ref}",
            "rollback_ref": f"rollback:training.job:{run_ref}:manual_review",
            "actor_source": ActorSource.AGENT.value,
            "entry_source": EntrySource.API.value,
            "tool_record_refs": (
                "training_service:result_recorder",
                f"training_job:{job_id}",
                model_version_ref,
            ),
            "graph_command_refs": (graph_command_id,),
            "canonical_command_refs": (
                f"research_graph_command:{graph_command_id}",
                f"training_job:{job_id}",
            ),
            "node_refs": (
                f"qro:{qro_id}",
                f"qro_type:{QROType.MODEL.value}",
                model_version_ref,
            ),
        },
        actor="training_service",
    )
    coverage_candidate = _validate_goal_entrypoint_coverage_candidate(
        _goal_entrypoint_coverage_from_compiler_records(
            ir,
            compiler_pass,
            entrypoint_ref="api:training.jobs",
        )
    )
    COMPILER_IR_STORE.record_ir(ir)
    COMPILER_IR_STORE.record_pass(compiler_pass)
    coverage = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(coverage_candidate)
    return {
        "compiler_ir_ref": ir.ir_ref,
        "compiler_pass_ref": compiler_pass.pass_ref,
        "entrypoint_coverage_ref": coverage.coverage_ref,
    }


def _record_training_job_backtest_qro(
    *,
    job: Any,
    request_payload: dict[str, Any],
    backtest_payload: dict[str, Any],
    backtest_result: dict[str, Any],
    dataset_id: str,
    train_dataset: str,
    market_data_use_validation_refs: Iterable[str],
    is_cross_dataset: bool,
    strict_oos: bool,
    oos_fraction: float | None,
) -> dict[str, str]:
    """Record a training-job backtest as a BacktestRun QRO without copying equity or metric payloads."""

    now = _dt.datetime.now(_dt.UTC).isoformat()
    refs = tuple(str(ref).strip() for ref in market_data_use_validation_refs if str(ref).strip())
    job_id = str(getattr(job, "job_id", "") or "")
    model = str(getattr(job, "model", "") or request_payload.get("model") or "unknown")
    task = str(getattr(job, "task", "") or request_payload.get("task") or "unspecified")
    asset_class = str(request_payload.get("asset_class") or "unspecified")
    model_version = getattr(job, "model_version", None)
    model_version_ref = f"model_version:{model}:v{int(model_version)}" if model_version is not None else ""
    model_passport_ref = str(getattr(job, "model_passport_ref", "") or "")
    validation_dossier_ref = str(getattr(job, "validation_dossier_ref", "") or "")
    metrics_payload = dict(backtest_result.get("metrics") or {})
    equity_curve = backtest_result.get("equity_curve")
    equity_values = [round(float(value), 12) for value in equity_curve.to_numpy()] if equity_curve is not None else []
    metrics_hash = content_hash(metrics_payload)
    equity_curve_hash = content_hash(equity_values)
    result_hash = content_hash(
        {
            "job_id": job_id,
            "dataset_id": dataset_id,
            "metrics_hash": metrics_hash,
            "equity_curve_hash": equity_curve_hash,
            "n_days": backtest_result.get("n_days"),
            "n_symbols": backtest_result.get("n_symbols"),
        }
    )
    backtest_run_ref = f"backtest_run:training_job:{job_id}:{result_hash[:12]}"
    request_hash = content_hash(request_payload)
    payload_hash = content_hash(backtest_payload)
    evidence_refs = _compiler_unique_refs(
        f"training_job:{job_id}",
        backtest_run_ref,
        model_version_ref,
        model_passport_ref,
        validation_dossier_ref,
        refs,
    )
    qro = QRORecord(
        qro_type=QROType.BACKTEST_RUN,
        owner="training_service",
        actor=ActorSource.AGENT,
        input_contract={
            "entry_source": EntrySource.API.value,
            "job_id": job_id,
            "model": model,
            "task": task,
            "asset_class": asset_class,
            "train_dataset": train_dataset,
            "dataset_id": dataset_id,
            "market_data_use_validation_refs": list(refs),
            "feature_count": len(request_payload.get("feature_cols") or []),
            "request_hash": request_hash,
            "payload_hash": payload_hash,
            "oos_fraction": oos_fraction,
            "is_cross_dataset": is_cross_dataset,
        },
        output_contract={
            "status": "succeeded",
            "backtest_run_ref": backtest_run_ref,
            "job_id": job_id,
            "model": model,
            "dataset_id": dataset_id,
            "train_dataset": train_dataset,
            "market_data_use_validation_refs": list(refs),
            "metrics_hash": metrics_hash,
            "equity_curve_hash": equity_curve_hash,
            "metric_count": len(metrics_payload),
            "equity_point_count": len(equity_values),
            "n_days": backtest_result.get("n_days"),
            "n_symbols": backtest_result.get("n_symbols"),
            "is_oos": bool(is_cross_dataset or oos_fraction),
            "is_cross_dataset": is_cross_dataset,
            "strict_oos": strict_oos,
        },
        market=asset_class,
        universe=dataset_id,
        horizon="training_job_backtest",
        frequency="training_job_backtest",
        lineage=("training", "job.backtest", job_id, dataset_id, backtest_run_ref, *refs),
        implementation_hash="training_job_backtest:" + result_hash,
        assumptions=(
            "The training service backtested an already succeeded training job artifact against a loaded training panel.",
            "Each listed MarketDataUse validation ref resolved to an accepted no-violation record covering the backtest dataset.",
        ),
        known_limits=(
            "The BacktestRun QRO records refs and hashes, not raw metrics, equity curves, prices, features, or artifact paths.",
            "A training-job backtest is not promotion approval, alpha proof, live serving readiness, or execution permission.",
            "MarketDataUse validation refs are not proof that every downstream consumer is now PIT-complete.",
        ),
        failure_modes=(
            "The backtest can be overfit, economically invalid, fee-incomplete, sample-limited, or rejected by later validation gates.",
        ),
        validation_plan=(
            "Bind this BacktestRun to validation dossiers, overfit gates, market-data timing evidence, promotion gates, monitor rules, and RDP before release claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="training.job.backtest:service",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.AGENT,
        actor="training_service",
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor="training_service",
        actor_source=ActorSource.AGENT.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:training.jobs.backtest",
        pass_name="api_training_backtest_qro_to_backtest_ir",
        validation_refs=_compiler_unique_refs(
            refs,
            validation_dossier_ref,
            model_passport_ref,
            f"validation:training.job.backtest:{job_id}:{dataset_id}",
        ),
        evidence_refs=_compiler_unique_refs(
            evidence_refs,
            f"metrics_hash:{metrics_hash}",
            f"equity_curve_hash:{equity_curve_hash}",
        ),
        environment_lock_ref=f"env:training_backtest:{model}:v1",
        permission_ref="training.job.backtest:service",
        deterministic_run_plan_ref=f"runplan:training.job.backtest:{result_hash}",
        rollback_ref=f"rollback:training.job.backtest:{job_id}:discard_backtest",
        tool_record_refs=("api:training.jobs.backtest", f"training_job:{job_id}", backtest_run_ref),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.BACKTEST_RUN.value}", backtest_run_ref),
        canonical_command_refs=(f"research_graph_command:{command_id}", backtest_run_ref),
    )
    return {
        "backtest_run_ref": backtest_run_ref,
        "qro_id": qro.qro_id,
        "research_graph_command_id": command_id,
        **compiler_refs,
    }


def _model_version_ref(model_id: str, version: int) -> str:
    return f"model_version:{model_id}:v{version}"


def _record_model_promotion_request_qro(
    *,
    model_id: str,
    payload: dict[str, Any],
    result: Any,
    actor: str,
) -> dict[str, Any]:
    """Record a model promotion request or direct registry stage update without copying raw evidence."""

    version = int(payload["version"])
    target_stage = str(payload.get("stage") or "")
    model_version_ref = _model_version_ref(model_id, version)
    gate_id = str(getattr(result, "gate_id", "") or "")
    decision = str(getattr(result, "decision", "") or ("pending" if gate_id else "applied"))
    from_stage = str(getattr(result, "from_stage", "") or "")
    action_kind = str(getattr(result, "action_kind", "") or "model_stage_apply")
    result_evidence = getattr(result, "evidence", None)
    evidence = result_evidence if isinstance(result_evidence, dict) else dict(payload.get("evidence") or {})
    evidence_hash = content_hash(evidence) if evidence else ""
    gap_list = tuple(str(gap) for gap in (getattr(result, "gap_list", None) or ()))
    gaps_hash = content_hash(gap_list) if gap_list else ""
    verdict_text = str(getattr(result, "verdict_text", "") or "")
    verdict_hash = content_hash({"verdict_text": verdict_text}) if verdict_text else ""
    model_passport_ref = str(
        evidence.get("model_passport_ref")
        or payload.get("model_passport_ref")
        or getattr(result, "model_passport_ref", "")
        or ""
    )
    validation_dossier_ref = str(
        evidence.get("validation_dossier_ref")
        or getattr(result, "validation_dossier_ref", "")
        or ""
    )
    verification_record_id = str(getattr(result, "verification_record_id", "") or payload.get("verification_record_id") or "")
    strategy_goal_ref = str(payload.get("strategy_goal_ref") or "")
    request_hash = content_hash(
        {
            "model_id": model_id,
            "version": version,
            "target_stage": target_stage,
            "verification_record_id": verification_record_id,
            "strategy_goal_ref": strategy_goal_ref,
            "model_passport_ref": model_passport_ref,
            "evidence_hash": evidence_hash,
            "gaps_hash": gaps_hash,
            "verdict_hash": verdict_hash,
        }
    )
    status = "stage_applied" if not gate_id else f"promotion_gate_{decision}"
    governance_status = (
        GovernanceStatus.APPROVED
        if decision == "approved"
        else GovernanceStatus.REJECTED if decision == "rejected" else GovernanceStatus.UNREVIEWED
    )
    evidence_status = (
        EvidenceStatus.SUFFICIENT
        if decision == "approved"
        else EvidenceStatus.INSUFFICIENT if decision == "rejected" else EvidenceStatus.CHALLENGED if gate_id else EvidenceStatus.EXPLORATORY
    )
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in (
            model_version_ref,
            f"approval_gate:{gate_id}" if gate_id else "",
            verification_record_id,
            strategy_goal_ref,
            model_passport_ref,
            validation_dossier_ref,
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.MODEL,
        owner="model_registry",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "model": model_id,
            "model_version": version,
            "model_version_ref": model_version_ref,
            "target_stage": target_stage,
            "gate_id": gate_id,
            "action_kind": action_kind,
            "verification_record_id": verification_record_id,
            "strategy_goal_ref": strategy_goal_ref,
            "evidence_hash": evidence_hash,
            "request_hash": request_hash,
        },
        output_contract={
            "status": status,
            "model": model_id,
            "model_version": version,
            "model_version_ref": model_version_ref,
            "from_stage": from_stage,
            "target_stage": target_stage,
            "gate_id": gate_id,
            "decision": decision,
            "action_kind": action_kind,
            "verification_record_id": verification_record_id,
            "strategy_goal_ref": strategy_goal_ref,
            "model_passport_ref": model_passport_ref,
            "validation_dossier_ref": validation_dossier_ref,
            "evidence_hash": evidence_hash,
            "gap_count": len(gap_list),
            "gaps_hash": gaps_hash,
            "verdict_hash": verdict_hash,
        },
        market="model_registry",
        universe=model_id,
        horizon="model_promotion",
        frequency="model_promotion",
        lineage=("model_registry", "promotion_request", model_version_ref, target_stage, gate_id or "direct"),
        implementation_hash="model_promotion_request:" + content_hash(
            {
                "model_version_ref": model_version_ref,
                "target_stage": target_stage,
                "gate_id": gate_id,
                "decision": decision,
                "request_hash": request_hash,
                "gaps_hash": gaps_hash,
                "verdict_hash": verdict_hash,
            }
        ),
        assumptions=("The Model Registry accepted the stage request and returned a registry object or approval gate.",),
        known_limits=(
            "The Model QRO records registry and gate refs, not raw evidence snapshots, model metrics, or artifact paths.",
            "A pending promotion gate is not approval, live serving readiness, safe loading approval, or execution permission.",
        ),
        failure_modes=(
            "The gate can still be rejected, expire, or approve a model that later fails runtime loading, monitoring, or execution gates.",
        ),
        validation_plan=(
            "Approve the promotion gate, bind the ModelPassport and ValidationDossier, and monitor recertification triggers before release claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=evidence_status,
        governance_status=governance_status,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="model_registry.promote:user_manual",
        approval=gate_id,
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    graph_refs = {
        "qro_id": qro.qro_id,
        "research_graph_command_id": command_id,
    }
    compiler_refs = _compile_model_registry_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        model_id=model_id,
        model_version_ref=model_version_ref,
        model_passport_ref=model_passport_ref,
        validation_dossier_ref=validation_dossier_ref,
        gate_id=gate_id,
        action_kind=action_kind,
        request_hash=request_hash,
        permission_ref="model_registry.promote:user_manual",
        actor=actor,
        pass_name="api_model_promotion_qro_to_model_ir",
        entrypoint_ref="api:models.promote",
    )
    return {**graph_refs, **compiler_refs}


def _compile_model_registry_qro(
    *,
    qro_id: str,
    graph_command_id: str,
    model_id: str,
    model_version_ref: str,
    model_passport_ref: str,
    validation_dossier_ref: str,
    gate_id: str,
    action_kind: str,
    request_hash: str,
    permission_ref: str,
    actor: str,
    pass_name: str,
    entrypoint_ref: str,
) -> dict[str, Any]:
    """Compile a Model Registry QRO into governed IR/pass and entrypoint coverage."""

    run_ref = content_hash(
        {
            "model_id": model_id,
            "model_version_ref": model_version_ref,
            "gate_id": gate_id,
            "action_kind": action_kind,
            "request_hash": request_hash,
            "permission_ref": permission_ref,
        }
    )
    validation_refs = tuple(
        ref
        for ref in (
            validation_dossier_ref,
            model_passport_ref,
            f"validation:model_registry:{action_kind or 'promotion'}:{model_version_ref}",
        )
        if ref
    )
    ir, compiler_pass = _compile_qro_payload(
        {
            "qro_id": qro_id,
            "validation_refs": validation_refs,
            "environment_lock_ref": "env:model_registry:v1",
            "permission_ref": permission_ref,
            "pass_name": pass_name,
            "compiler_version": "governed-compiler-ir.v1",
            "deterministic_run_plan_ref": f"runplan:model_registry:{run_ref}",
            "rollback_ref": f"rollback:model_registry:{run_ref}:manual_review",
            "actor_source": ActorSource.USER_MANUAL.value,
            "entry_source": EntrySource.API.value,
            "tool_record_refs": (
                "model_registry:promotion",
                model_version_ref,
                f"approval_gate:{gate_id}" if gate_id else "approval_gate:none",
            ),
            "graph_command_refs": (graph_command_id,),
            "canonical_command_refs": (
                f"research_graph_command:{graph_command_id}",
                f"model_registry:{action_kind or 'promotion'}",
            ),
            "node_refs": (
                f"qro:{qro_id}",
                f"qro_type:{QROType.MODEL.value}",
                model_version_ref,
            ),
        },
        actor=actor,
    )
    coverage_candidate = _validate_goal_entrypoint_coverage_candidate(
        _goal_entrypoint_coverage_from_compiler_records(
            ir,
            compiler_pass,
            entrypoint_ref=entrypoint_ref,
        )
    )
    COMPILER_IR_STORE.record_ir(ir)
    COMPILER_IR_STORE.record_pass(compiler_pass)
    coverage = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(coverage_candidate)
    return {
        "compiler_ir_ref": ir.ir_ref,
        "compiler_pass_ref": compiler_pass.pass_ref,
        "entrypoint_coverage_ref": coverage.coverage_ref,
    }


def _record_model_promotion_approval_qro(
    *,
    model_id: str,
    gate: Any,
    payload: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    """Record successful model promotion approval without storing raw human rationale."""

    version = int(getattr(gate, "version"))
    target_stage = str(getattr(gate, "to_stage", "") or "")
    from_stage = str(getattr(gate, "from_stage", "") or "")
    gate_id = str(getattr(gate, "gate_id", "") or "")
    action_kind = str(getattr(gate, "action_kind", "") or "")
    model_version_ref = _model_version_ref(model_id, version)
    evidence = getattr(gate, "evidence", None) if isinstance(getattr(gate, "evidence", None), dict) else {}
    evidence_hash = content_hash(evidence) if evidence else ""
    reason_hash = content_hash({"reason": payload.get("reason") or ""}) if payload.get("reason") else ""
    risk_restated_hash = (
        content_hash({"risk_restated": payload.get("risk_restated") or ""})
        if payload.get("risk_restated")
        else ""
    )
    model_passport_ref = str(evidence.get("model_passport_ref") or "")
    validation_dossier_ref = str(evidence.get("validation_dossier_ref") or "")
    verification_record_id = str(getattr(gate, "verification_record_id", "") or "")
    strategy_goal_ref = str(evidence.get("strategy_goal_ref") or "")
    side_effect_ref = str(getattr(gate, "side_effect_ref", "") or "")
    request_hash = content_hash(
        {
            "gate_id": gate_id,
            "decision": getattr(gate, "decision", ""),
            "reason_hash": reason_hash,
            "risk_restated_hash": risk_restated_hash,
        }
    )
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in (
            model_version_ref,
            f"approval_gate:{gate_id}",
            verification_record_id,
            model_passport_ref,
            validation_dossier_ref,
            side_effect_ref,
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.MODEL,
        owner="model_registry",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "model": model_id,
            "model_version": version,
            "model_version_ref": model_version_ref,
            "target_stage": target_stage,
            "gate_id": gate_id,
            "action_kind": action_kind,
            "request_hash": request_hash,
        },
        output_contract={
            "status": "promotion_gate_approved",
            "model": model_id,
            "model_version": version,
            "model_version_ref": model_version_ref,
            "from_stage": from_stage,
            "target_stage": target_stage,
            "gate_id": gate_id,
            "decision": str(getattr(gate, "decision", "") or ""),
            "action_kind": action_kind,
            "verification_record_id": verification_record_id,
            "model_passport_ref": model_passport_ref,
            "validation_dossier_ref": validation_dossier_ref,
            "evidence_hash": evidence_hash,
            "reason_hash": reason_hash,
            "risk_restated_hash": risk_restated_hash,
            "side_effect_ref": side_effect_ref,
        },
        market="model_registry",
        universe=model_id,
        horizon="model_promotion",
        frequency="model_promotion",
        lineage=("model_registry", "promotion_approval", model_version_ref, target_stage, gate_id),
        implementation_hash="model_promotion_approval:" + content_hash(
            {
                "model_version_ref": model_version_ref,
                "target_stage": target_stage,
                "gate_id": gate_id,
                "request_hash": request_hash,
                "side_effect_ref": side_effect_ref,
            }
        ),
        assumptions=("The approval gate returned approved and executed the Model Registry stage side effect.",),
        known_limits=(
            "The approval QRO records gate approval refs and hashes, not raw approval rationale or model artifacts.",
            "Model promotion approval is not live order permission, safe loading execution, or future monitoring success.",
        ),
        failure_modes=(
            "A promoted model can later fail artifact loading, recertification, performance monitoring, or downstream execution gates.",
        ),
        validation_plan=(
            "Bind the promoted version to monitor profiles, recertification records, and runtime loading checks before release claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.SUFFICIENT,
        governance_status=GovernanceStatus.APPROVED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="model_registry.promotion.approve:user_manual",
        approval=gate_id,
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    graph_refs = {
        "qro_id": qro.qro_id,
        "research_graph_command_id": command_id,
    }
    compiler_refs = _compile_model_registry_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        model_id=model_id,
        model_version_ref=model_version_ref,
        model_passport_ref=model_passport_ref,
        validation_dossier_ref=validation_dossier_ref,
        gate_id=gate_id,
        action_kind=action_kind,
        request_hash=request_hash,
        permission_ref="model_registry.promotion.approve:user_manual",
        actor=actor,
        pass_name="api_model_promotion_approval_qro_to_model_ir",
        entrypoint_ref="api:models.gates.approve",
    )
    return {**graph_refs, **compiler_refs}


def _api_actor_ref(user: Any) -> str:
    return str(getattr(user, "user_id", "") or getattr(user, "username", "") or "unknown")


def _status_from_model_governance_decision(decision: str) -> tuple[EvidenceStatus, GovernanceStatus]:
    normalized = str(decision or "").strip().lower()
    if normalized in {"accepted", "approved", "pass", "passed"}:
        return EvidenceStatus.SUFFICIENT, GovernanceStatus.APPROVED
    if normalized in {"rejected", "blocked", "failed", "failure"}:
        return EvidenceStatus.INSUFFICIENT, GovernanceStatus.REJECTED
    return EvidenceStatus.CHALLENGED, GovernanceStatus.UNREVIEWED


def _record_model_monitoring_profile_qro(profile: ModelMonitoringProfile, *, actor: str) -> dict[str, Any]:
    model_version_ref = str(profile.model_version_ref)
    model_passport_ref = str(profile.model_passport_ref)
    runtime = str(getattr(profile.runtime, "value", profile.runtime) or RuntimeStatus.OFFLINE.value)
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                model_version_ref,
                model_passport_ref,
                profile.monitoring_profile_id,
                *tuple(profile.metric_refs),
                profile.schedule_ref,
                profile.alert_policy_ref,
                *tuple(profile.drift_signal_refs),
                *tuple(profile.performance_threshold_refs),
                *(str(getattr(ref, "value", ref)) for ref in profile.recertification_trigger_refs),
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.MODEL,
        owner="model_governance",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "metric_ref_count": len(profile.metric_refs),
            "schedule_ref": profile.schedule_ref,
            "alert_policy_ref": profile.alert_policy_ref,
            "recertification_trigger_count": len(profile.recertification_trigger_refs),
        },
        output_contract={
            "status": "monitoring_profile_recorded",
            "monitoring_profile_id": profile.monitoring_profile_id,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "runtime": runtime,
            "owner": profile.owner,
            "drift_signal_count": len(profile.drift_signal_refs),
            "performance_threshold_count": len(profile.performance_threshold_refs),
        },
        market="model_governance",
        universe=model_version_ref,
        horizon="model_monitoring",
        frequency="model_monitoring_profile",
        lineage=("model_governance", "monitoring_profile", model_version_ref, profile.monitoring_profile_id),
        implementation_hash="model_monitoring_profile:" + content_hash(
            {
                "model_version_ref": model_version_ref,
                "model_passport_ref": model_passport_ref,
                "monitoring_profile_id": profile.monitoring_profile_id,
                "metric_ref_count": len(profile.metric_refs),
                "schedule_ref": profile.schedule_ref,
                "alert_policy_ref": profile.alert_policy_ref,
            }
        ),
        assumptions=("The monitoring profile was recorded after the model passport was present in the registry.",),
        known_limits=(
            "The Model QRO records monitoring refs and counts, not raw metric series or alert payloads.",
            "A monitoring profile is not recertification, promotion approval, live serving proof, or execution permission.",
        ),
        failure_modes=("monitor schedule drift", "alert policy mismatch", "missing future recertification evidence"),
        validation_plan=(
            "Bind serving invocations and recertification records to this profile before claiming runtime model governance closure.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="model_governance.monitoring_profile:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
        monitor_rules=tuple(profile.metric_refs),
        responsibility_boundary="records monitoring profile refs only; does not certify model quality or authorize serving",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
        tool_record_refs=("api:research_os.model_governance.monitoring_profiles", profile.monitoring_profile_id),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:research_os.model_governance.monitoring_profiles",
        pass_name="api_model_monitoring_profile_qro_to_model_ir",
        validation_refs=(
            model_passport_ref,
            f"validation:model_governance:monitoring_profile:{model_version_ref}",
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:model_governance:offline:v1",
        deterministic_run_plan_ref=f"runplan:model_governance:monitoring_profile:{profile.monitoring_profile_id}",
        rollback_ref=f"rollback:model_governance:monitoring_profile:{profile.monitoring_profile_id}",
        tool_record_refs=("api:research_os.model_governance.monitoring_profiles", profile.monitoring_profile_id),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.MODEL.value}", model_version_ref),
        canonical_command_refs=(f"research_graph_command:{command_id}", profile.monitoring_profile_id),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_model_recertification_qro(record: ModelRecertificationRecord, *, actor: str) -> dict[str, Any]:
    model_version_ref = str(record.model_version_ref)
    model_passport_ref = str(record.model_passport_ref)
    trigger = str(getattr(record.trigger, "value", record.trigger) or "")
    evidence_hash = content_hash({"evidence_refs": record.evidence_refs})
    evidence_status, governance_status = _status_from_model_governance_decision(record.decision)
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                model_version_ref,
                model_passport_ref,
                record.recertification_record_id,
                f"recertification_trigger:{trigger}",
                record.change_event_ref,
                *tuple(record.evidence_refs),
                f"recertification_evidence_hash:{evidence_hash}",
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.VALIDATION_DOSSIER,
        owner="model_governance",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "trigger": trigger,
            "change_event_ref": record.change_event_ref,
            "evidence_ref_count": len(record.evidence_refs),
            "evidence_hash": evidence_hash,
        },
        output_contract={
            "status": "recertification_recorded",
            "recertification_record_id": record.recertification_record_id,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "trigger": trigger,
            "decision": record.decision,
            "evidence_hash": evidence_hash,
        },
        market="model_governance",
        universe=model_version_ref,
        horizon="model_recertification",
        frequency="model_recertification",
        lineage=("model_governance", "recertification", model_version_ref, record.recertification_record_id),
        implementation_hash="model_recertification:" + content_hash(
            {
                "model_version_ref": model_version_ref,
                "model_passport_ref": model_passport_ref,
                "trigger": trigger,
                "change_event_ref": record.change_event_ref,
                "decision": record.decision,
                "evidence_hash": evidence_hash,
            }
        ),
        assumptions=("The recertification trigger was declared on the model passport before recording this decision.",),
        known_limits=(
            "The ValidationDossier QRO records evidence refs and hashes, not raw validation payloads.",
            "A recertification record is not model artifact inspection, model serving approval, or execution permission.",
        ),
        failure_modes=("trigger drift", "stale evidence refs", "later artifact or serving gate rejection"),
        validation_plan=("Bind this recertification record to monitoring profile, artifact inspection, and serving invocation refs."),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=evidence_status,
        governance_status=governance_status,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="model_governance.recertification:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
        responsibility_boundary="records recertification refs and decision only; does not authorize prediction serving or execution",
        verdict=record.decision,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
        tool_record_refs=("api:research_os.model_governance.recertification_records", record.recertification_record_id),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:research_os.model_governance.recertification_records",
        pass_name="api_model_recertification_qro_to_validation_dossier_ir",
        validation_refs=(
            model_passport_ref,
            record.recertification_record_id,
            f"validation:model_governance:recertification:{model_version_ref}",
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:model_governance:offline:v1",
        deterministic_run_plan_ref=f"runplan:model_governance:recertification:{record.recertification_record_id}",
        rollback_ref=f"rollback:model_governance:recertification:{record.recertification_record_id}",
        tool_record_refs=("api:research_os.model_governance.recertification_records", record.recertification_record_id),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.VALIDATION_DOSSIER.value}", record.recertification_record_id),
        canonical_command_refs=(f"research_graph_command:{command_id}", record.recertification_record_id),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_model_artifact_inspection_qro(record: ModelArtifactInspectionRecord, *, actor: str) -> dict[str, Any]:
    model_version_ref = str(record.model_version_ref)
    model_passport_ref = str(record.model_passport_ref)
    checks_hash = content_hash({"checks": record.checks})
    limitations_hash = content_hash({"limitations": record.limitations}) if record.limitations else ""
    evidence_status, governance_status = _status_from_model_governance_decision(record.inspection_status)
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                model_version_ref,
                model_passport_ref,
                record.artifact_inspection_record_id,
                record.artifact_ref,
                record.inspection_ref,
                record.artifact_hash,
                record.inspector_ref,
                f"artifact_inspection_status:{record.inspection_status}",
                f"artifact_inspection_checks_hash:{checks_hash}",
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.VALIDATION_DOSSIER,
        owner="model_governance",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "artifact_ref": record.artifact_ref,
            "inspection_ref": record.inspection_ref,
            "artifact_hash": record.artifact_hash,
            "inspection_mode": record.inspection_mode,
            "inspector_ref": record.inspector_ref,
            "checks_hash": checks_hash,
            "limitations_hash": limitations_hash,
        },
        output_contract={
            "status": "artifact_inspection_recorded",
            "artifact_inspection_record_id": record.artifact_inspection_record_id,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "artifact_ref": record.artifact_ref,
            "inspection_ref": record.inspection_ref,
            "inspection_status": record.inspection_status,
            "checks_count": len(record.checks),
            "limitations_count": len(record.limitations),
        },
        market="model_governance",
        universe=model_version_ref,
        horizon="model_artifact_inspection",
        frequency="model_artifact_inspection",
        lineage=("model_governance", "artifact_inspection", model_version_ref, record.inspection_ref),
        implementation_hash="model_artifact_inspection:" + content_hash(
            {
                "model_version_ref": model_version_ref,
                "model_passport_ref": model_passport_ref,
                "artifact_ref": record.artifact_ref,
                "inspection_ref": record.inspection_ref,
                "artifact_hash": record.artifact_hash,
                "inspection_status": record.inspection_status,
                "checks_hash": checks_hash,
                "limitations_hash": limitations_hash,
            }
        ),
        assumptions=("The artifact inspection was recorded after the model passport declared the artifact manifest.",),
        known_limits=(
            "The ValidationDossier QRO records inspection refs and hashes, not model binaries, artifact paths, or raw loader output.",
            "Accepted artifact inspection is not model promotion, monitoring success, or execution permission.",
        ),
        failure_modes=("artifact hash mismatch", "unsafe serialized artifact", "later serving or recertification gate rejection"),
        validation_plan=("Bind accepted artifact inspection to model serving invocation and monitoring profile refs."),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=evidence_status,
        governance_status=governance_status,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="model_governance.artifact_inspection:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
        responsibility_boundary="records artifact inspection refs and hashes only; does not load the artifact or authorize execution",
        verdict=record.inspection_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
        tool_record_refs=("api:research_os.model_governance.artifact_inspections", record.inspection_ref),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:research_os.model_governance.artifact_inspections",
        pass_name="api_model_artifact_inspection_qro_to_validation_dossier_ir",
        validation_refs=(
            model_passport_ref,
            record.artifact_inspection_record_id,
            f"validation:model_governance:artifact_inspection:{record.inspection_ref}",
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:model_governance:offline:v1",
        deterministic_run_plan_ref=f"runplan:model_governance:artifact_inspection:{record.inspection_ref}",
        rollback_ref=f"rollback:model_governance:artifact_inspection:{record.inspection_ref}",
        tool_record_refs=("api:research_os.model_governance.artifact_inspections", record.inspection_ref),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.VALIDATION_DOSSIER.value}", record.inspection_ref),
        canonical_command_refs=(f"research_graph_command:{command_id}", record.inspection_ref),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_model_serving_invocation_qro(record: ModelServingInvocationRecord, *, actor: str) -> dict[str, Any]:
    model_version_ref = str(record.model_version_ref)
    model_passport_ref = str(record.model_passport_ref)
    runtime = str(getattr(record.runtime, "value", record.runtime) or "")
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in dict.fromkeys(
            (
                model_version_ref,
                model_passport_ref,
                record.serving_invocation_id,
                record.artifact_inspection_ref,
                record.monitoring_profile_ref,
                f"request_hash:{record.request_hash}",
                f"prediction_hash:{record.prediction_hash}",
            )
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.FORECAST,
        owner="model_governance",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "artifact_inspection_ref": record.artifact_inspection_ref,
            "monitoring_profile_ref": record.monitoring_profile_ref,
            "feature_ref_count": len(record.feature_refs),
            "row_count": record.row_count,
            "request_hash": record.request_hash,
        },
        output_contract={
            "status": "serving_invocation_recorded",
            "serving_invocation_id": record.serving_invocation_id,
            "model_version_ref": model_version_ref,
            "model_passport_ref": model_passport_ref,
            "prediction_hash": record.prediction_hash,
            "runtime": runtime,
        },
        market="model_governance",
        universe=model_version_ref,
        horizon="model_prediction",
        frequency="model_serving_invocation",
        lineage=("model_governance", "serving_invocation", model_version_ref, record.serving_invocation_id),
        implementation_hash="model_serving_invocation:" + content_hash(
            {
                "model_version_ref": model_version_ref,
                "model_passport_ref": model_passport_ref,
                "artifact_inspection_ref": record.artifact_inspection_ref,
                "monitoring_profile_ref": record.monitoring_profile_ref,
                "row_count": record.row_count,
                "request_hash": record.request_hash,
                "prediction_hash": record.prediction_hash,
                "runtime": runtime,
            }
        ),
        assumptions=("The serving path loaded an inspected model artifact and wrote a hashed invocation record.",),
        known_limits=(
            "The Forecast QRO records request and prediction hashes, not feature rows or prediction values.",
            "A model serving invocation is not portfolio construction, order intent, order submission, or live trading permission.",
        ),
        failure_modes=("model load failure", "schema drift", "prediction drift", "later signal or portfolio gate rejection"),
        validation_plan=("Bind serving forecasts to signal protocol, portfolio policy, and execution boundary refs before trading claims."),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.PAPER,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="model_governance.serving_invocation:user_manual",
        allowed_environment=RuntimeStatus.PAPER,
        responsibility_boundary="records model forecast refs and hashes only; does not authorize portfolio construction or execution",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
        tool_record_refs=("api:models.predict", record.serving_invocation_id),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:models.predict",
        pass_name="api_model_serving_invocation_qro_to_forecast_ir",
        validation_refs=(
            model_passport_ref,
            record.artifact_inspection_ref,
            record.monitoring_profile_ref,
            f"validation:model_governance:serving_invocation:{model_version_ref}",
        ),
        evidence_refs=qro.evidence_refs,
        permission_ref=qro.permission,
        environment_lock_ref="env:model_governance:serving:v1",
        deterministic_run_plan_ref=f"runplan:model_governance:serving_invocation:{record.serving_invocation_id}",
        rollback_ref=f"rollback:model_governance:serving_invocation:{record.serving_invocation_id}",
        tool_record_refs=("api:models.predict", record.serving_invocation_id),
        node_refs=(f"qro:{qro.qro_id}", f"qro_type:{QROType.FORECAST.value}", record.serving_invocation_id),
        canonical_command_refs=(f"research_graph_command:{command_id}", record.serving_invocation_id),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


@app.on_event("startup")
def startup_event() -> None:
    global MONITOR_SCHEDULER
    ensure_runtime_dirs()
    configure_monitor_runtime(
        lifecycle_manager=FACTOR_LIFECYCLE,
        factor_registry=FACTOR_REGISTRY,
        execution_audit_log=EXECUTION_AUDIT_LOG,
        result_recorder=_record_weekly_monitor_qro_from_scheduler,
    )
    MONITOR_SCHEDULER = build_weekly_monitor_scheduler(strict=True)
    _start_production_monitor_scheduler()
    _start_monitor_driver()  # 周期 tick 让 weekly production cron 真 fire


@app.on_event("shutdown")
def shutdown_event() -> None:
    stop_monitor_driver()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/connectors")
def list_connectors() -> list[dict]:
    """所有已注册的数据 connector（内置 + DIY YAML + 用户上传）。"""
    return connector_registry.describe_all()


@app.get("/api/connectors/health")
def connectors_health() -> list[dict]:
    """对每个 connector 跑一次健康检查；freshness 板用。"""
    return connector_registry.health_all()


@app.get("/api/datasets")
def list_datasets() -> list[dict]:
    """列出所有已注册 dataset_id 与各自最新 version。"""
    out: list[dict] = []
    for did in DATASET_REGISTRY.list_dataset_ids():
        latest = DATASET_REGISTRY.latest(did)
        out.append({"dataset_id": did, "latest_version": latest.to_dict() if latest else None})
    return out


@app.get("/api/datasets/{dataset_id}/versions")
def list_dataset_versions(dataset_id: str) -> list[dict]:
    return [v.to_dict() for v in DATASET_REGISTRY.list_versions(dataset_id)]


@app.get("/api/data/freshness")
def data_freshness(dataset_id: str | None = Query(None), market_kind: str = Query("stocks_cn")) -> list[dict]:
    """对单个 dataset_id 或所有 dataset 给出 green/yellow/red 报告。"""
    ids = [dataset_id] if dataset_id else DATASET_REGISTRY.list_dataset_ids()
    return [compute_freshness(did, market_kind, DATASET_REGISTRY).to_dict() for did in ids]


@app.get("/api/fields")
def list_available_fields(
    market: str = Query(...), interval: str | None = Query(None), enabled_only: bool = Query(True)
) -> dict:
    """当前可用字段宇宙（canonical + freeform），按 enabled 源过滤——量化流程/Agent 的字段真相源。"""
    return FIELD_CATALOG.available_fields(market, interval=interval, enabled_only=enabled_only).to_dict()


@app.get("/api/fields/catalog")
def fields_catalog(market: str | None = Query(None), official: bool | None = Query(None)) -> list[dict]:
    """字段宇宙持久化表（含 canonical_id/单位/含义/来源/数据种类）。Agent 拉取辅助 + 写策略用。"""
    try:
        FIELD_CATALOG_STORE.sync_from_catalog(FIELD_CATALOG)
    except Exception:  # noqa: BLE001
        pass
    return FIELD_CATALOG_STORE.list(market=market, official=official)


from pydantic import BaseModel as _BaseModel  # noqa: E402


class _FieldInferRequest(_BaseModel):
    columns: list[str]
    market: str | None = None
    data_kind: str = "ohlcv"
    sample: dict | None = None


class _FieldMappingItem(_BaseModel):
    raw_column: str
    field_id: str
    is_freeform: bool = False


class _FieldMappingApplyRequest(_BaseModel):
    source: str
    data_kind: str = "ohlcv"
    mappings: list[_FieldMappingItem]


@app.post("/api/fields/infer-mapping")
def infer_field_mapping(req: _FieldInferRequest) -> dict:
    """字段映射向导：对一批原始列名给出对齐到 canonical 的建议（供前端/用户确认）。"""
    from .field_catalog.infer import infer_mapping_report

    return infer_mapping_report(req.columns, market=req.market, data_kind=req.data_kind, sample=req.sample)


@app.post("/api/fields/mapping")
def apply_field_mapping(req: _FieldMappingApplyRequest) -> dict:
    """把确认后的映射写入 (源, data_kind)。非法 field_id 返回 422。"""
    from .field_catalog import FieldMapping

    for m in req.mappings:
        try:
            FIELD_MAPPING_STORE.set(
                FieldMapping(
                    source=req.source,
                    data_kind=req.data_kind,
                    raw_column=m.raw_column,
                    field_id=m.field_id,
                    is_freeform=m.is_freeform,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{m.raw_column}: {exc}") from exc
    return {"applied": len(req.mappings)}


@app.get("/api/factors/operators")
def list_factor_operators() -> list[dict]:
    """前端因子表达式编辑器 / Agent tool 的算子目录。"""
    return list_operators()


@app.get("/api/factors")
def list_factors() -> list[dict]:
    """全部已注册因子（含 alpha_lite 默认 30 个）。"""
    return [f.to_dict() for f in FACTOR_REGISTRY.list()]


# F4 · 静态 GET 路由须在 /api/factors/{factor_id} 动态路由【之前】注册，
# 否则 factor_id="signal_contracts" 会吞掉本端点（FastAPI 按注册序匹配）。
@app.get("/api/factors/signal_contracts")
def list_signal_contracts() -> list[dict[str, Any]]:
    """已登记的信号契约（ML/DL 输出 → 信号 → 入因子库）。"""

    return [c.to_dict() for c in SIGNAL_CONTRACTS.list()]


# ════════════ F2 · 因子台真实后端接线（compute / correlation / validate / audit / layered）════════════
# 红线：静态路径（correlation/validate）须在 /api/factors/{factor_id} 动态路由【之前】注册，
# 否则 factor_id="correlation" 会吞掉本端点（同 F4 signal_contracts 的处理）。


@app.get("/api/factors/correlation")
def factors_correlation(
    market: str = Query("equity_cn"),
    threshold: float = Query(0.8),
    factor_ids: str | None = Query(None, description="逗号分隔；缺省=注册表前若干个有公式的因子"),
    market_data_use_validation_refs: list[str] | None = Query(None),
) -> dict[str, Any]:
    """F2 · 多因子拥挤度 Spearman 矩阵 + 冗余对（去冗余）。复用 panel_source 复权 panel。"""

    validation_refs = _factor_market_data_use_validation_refs(
        {"market_data_use_validation_refs": market_data_use_validation_refs},
        market=market,
        operation_label="factor correlation reports",
        market_coverage_label="factor correlation market",
    )
    if factor_ids:
        want = [fid.strip() for fid in factor_ids.split(",") if fid.strip()]
        pairs: list[tuple[str, str]] = []
        for fid in want:
            try:
                f = FACTOR_REGISTRY.get(fid)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if f.formula:
                pairs.append((f.factor_id, f.formula))
    else:
        pairs = [(f.factor_id, f.formula) for f in FACTOR_REGISTRY.list() if f.formula][:12]
    try:
        report = correlation_matrix(market, pairs, threshold=threshold)
    except (CorrelationError, PanelSourceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**report.to_dict(), "market_data_use_validation_refs": list(validation_refs)}


@app.post("/api/factors/validate")
def factors_validate(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """F2 · 构建台「即时 IC 预览」：编译 + 前视门 + 截面 IC（不落库）。

    红线：本端点【不】注册——它是 POST /api/factors 之前的预检，让用户在注册前看到
    编译/前视是否过关 + 即时 IC。前视未过 → valid=False（绝不假绿灯）。
    """

    from .factor_factory.register_guard import RegisterGateError, check_no_lookahead

    formula = str(payload.get("formula", "")).strip()
    market = str(payload.get("market", "equity_cn")).strip() or "equity_cn"
    horizon = int(payload.get("horizon", 5) or 5)
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    if not formula:
        raise HTTPException(status_code=422, detail="formula 不能为空")
    # 编译门。
    try:
        compile_expression(formula)
    except ExpressionError as exc:
        result = {"valid": False, "stage": "compile", "reason": str(exc), "ic": None}
        return {
            **result,
            **_record_factor_preview_validation_qro(
                formula=formula,
                result=result,
                actor=actor,
                market=market,
                horizon=horizon,
            ),
        }
    # 前视门（编译过才查，较贵）。
    no_la, la_detail = check_no_lookahead(formula)
    if not no_la:
        result = {"valid": False, "stage": "lookahead", "reason": la_detail, "ic": None}
        return {
            **result,
            **_record_factor_preview_validation_qro(
                formula=formula,
                result=result,
                actor=actor,
                market=market,
                horizon=horizon,
            ),
        }
    # 即时 IC（不落库）。
    market_data_use_validation_refs = _factor_preview_market_data_use_validation_refs(payload, market=market)
    try:
        fp = factor_panel(market, formula, horizon=horizon, factor_alias="factor_value")
        ic = compute_ic_report(fp, "factor_value", horizon=horizon)
    except (PanelSourceError, RegisterGateError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"IC 计算失败: {exc}") from exc
    result = {"valid": True, "stage": "ok", "reason": la_detail, "ic": ic.to_dict()}
    return {
        **result,
        **_record_factor_preview_validation_qro(
            formula=formula,
            result=result,
            actor=actor,
            market=market,
            horizon=horizon,
            market_data_use_validation_refs=market_data_use_validation_refs,
        ),
    }


@app.post("/api/factors")
def create_factor(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """F2 · 注册新因子（红线：必经三检查门 + LifecycleManager 初始 NEW，绝不裸写 registry）。

    入库门（违一条即 422，携 gate 名）：
    - 编译门：表达式能编译成合法 polars Expr。
    - 前视门：追加 future 不改历史（shift-invariance contract，整公式版）。
    - 无重名门：同 factor_id 已存在即拒（升版本须显式 overwrite=True）。
    通过后经 FACTOR_REGISTRY.register（初始 NEW）落库；返回因子 + 三检查明细。
    """

    from .factor_factory.register_guard import RegisterGateError, precheck_register

    factor_id = str(payload.get("factor_id", "")).strip()
    formula = str(payload.get("formula", "")).strip()
    overwrite = bool(payload.get("overwrite", False))
    if not factor_id or not formula:
        raise HTTPException(status_code=422, detail="factor_id 与 formula 必填")
    try:
        check = precheck_register(FACTOR_REGISTRY, factor_id, formula, overwrite=overwrite)
    except RegisterGateError as exc:
        raise HTTPException(
            status_code=422,
            detail={"registered": False, "gate": exc.gate, "reason": str(exc)},
        ) from exc
    factor = FACTOR_REGISTRY.register(
        factor_id,
        formula,
        author=getattr(user, "user_id", "system"),
        description=str(payload.get("description", "")),
        params=payload.get("params") if isinstance(payload.get("params"), dict) else None,
        overwrite=overwrite,
    )
    # 初始状态恒为 NEW（registry.register 默认 NEW；这里断言生命周期门已就位，未来迁移走 evaluate）。
    assert factor.lifecycle_state == "NEW"
    graph_refs = _record_factor_qro(
        factor,
        check,
        actor=str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system"),
        overwrite=overwrite,
    )
    # GOAL §9 advisory（只记录不强制）：把 canonical validate_factor_library_entry 裁决挂到产物上。
    # 本端点是表达式注册路径：kind 固定 expression、ref=formula，故此处实际触发的是「因子数学产物缺
    # theory/run_config 绑定 → 拒」子准则；mathematical_refs / theory_binding_ref / run_config_binding_ref
    # 为可选 §9 spine 槽。validator 的「模型本体塞进 Factor Library → 拒」分支在此基本不可达（formula 须过
    # 编译门，.pt/.pkl 之类编译即 422）——该子准则的**专用硬门**在 POST /api/factors/admit
    # （admit_artifact_to_factor_lib，既有，已被 test_adv1 钉死）。违例**不拒注册**。
    boundary_verdict = _boundary_verdict_payload(
        validate_factor_library_entry(
            FactorLibraryEntry(
                factor_ref=factor_id,
                kind=FactorAssetKind.EXPRESSION,
                ref=formula,
                lifecycle_state=str(factor.lifecycle_state),
                mathematical_refs=payload.get("mathematical_refs"),
                theory_binding_ref=payload.get("theory_binding_ref"),
                run_config_binding_ref=payload.get("run_config_binding_ref"),
            )
        ),
        boundary="factor_library_entry_§9",
    )
    return {
        "registered": True,
        "gates": {
            "compiled": check.compiled,
            "no_lookahead": check.no_lookahead,
            "name_available": check.name_available,
            "detail": check.detail,
        },
        "boundary_verdict": boundary_verdict,
        **graph_refs,
        **factor.to_dict(),
    }


@app.get("/api/factors/{factor_id}")
def get_factor(factor_id: str, version: int | None = Query(None)) -> dict:
    try:
        return FACTOR_REGISTRY.get(factor_id, version).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/factors/{factor_id}/ic")
def factor_ic(
    factor_id: str,
    market: str = Query("equity_cn"),
    horizon: int = Query(5),
    market_data_use_validation_refs: list[str] | None = Query(None),
    version: int | None = Query(None),
) -> dict[str, Any]:
    """F2 · 因子截面 IC / Rank-IC / IC-IR（已纳 Newey-West HAC t）。复用 ic.compute_ic_report。"""

    try:
        factor = FACTOR_REGISTRY.get(factor_id, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    validation_refs = _factor_market_data_use_validation_refs(
        {"market_data_use_validation_refs": market_data_use_validation_refs},
        market=market,
        operation_label="factor IC reports",
        market_coverage_label="factor IC market",
    )
    try:
        fp = factor_panel(market, factor.formula, horizon=horizon, factor_alias="factor_value")
        report = compute_ic_report(fp, "factor_value", horizon=horizon)
    except (PanelSourceError, ExpressionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "factor_id": factor.factor_id,
        "version": factor.version,
        "market": market,
        "market_data_use_validation_refs": list(validation_refs),
        **report.to_dict(),
    }


@app.get("/api/factors/{factor_id}/ic_decay")
def factor_ic_decay(
    factor_id: str,
    market: str = Query("equity_cn"),
    market_data_use_validation_refs: list[str] | None = Query(None),
    version: int | None = Query(None),
) -> dict[str, Any]:
    """F2 · IC 衰减曲线（默认 [1,3,5,10,20] 日 horizon）。复用 ic.compute_ic_decay。"""

    try:
        factor = FACTOR_REGISTRY.get(factor_id, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    validation_refs = _factor_market_data_use_validation_refs(
        {"market_data_use_validation_refs": market_data_use_validation_refs},
        market=market,
        operation_label="factor IC decay reports",
        market_coverage_label="factor IC decay market",
    )
    try:
        fp = factor_panel(market, factor.formula, factor_alias="factor_value")
        reports = compute_ic_decay(fp, "factor_value")
    except (PanelSourceError, ExpressionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "factor_id": factor.factor_id,
        "version": factor.version,
        "market": market,
        "market_data_use_validation_refs": list(validation_refs),
        "decay": [r.to_dict() for r in reports],
    }


@app.get("/api/factors/{factor_id}/lifecycle/events")
def factor_lifecycle_events(factor_id: str) -> dict[str, Any]:
    """F2 · 五态机生命周期事件日志（从 LifecycleManager 读，审计追溯）。"""

    try:
        FACTOR_REGISTRY.get(factor_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    events = FACTOR_LIFECYCLE.events(factor_id)
    return {"factor_id": factor_id, "events": [e.to_dict() for e in events]}


_MONITOR_ACTIVE_STATES = {"QUALIFIED", "PROBATION", "OBSERVATION", "WARNING"}


def _monitor_finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise HTTPException(status_code=422, detail=f"{field} must be a finite number")
    return number


def _monitor_observations_from_payload(payload: dict[str, Any]) -> list | None:
    raw = payload.get("factor_observations")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="factor_observations must be a list")
    observations = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"factor_observations[{idx}] must be an object")
        try:
            observation = observation_from_payload(item)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            factor = FACTOR_REGISTRY.get(observation.factor_id, observation.version)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if str(factor.lifecycle_state).upper() not in _MONITOR_ACTIVE_STATES:
            raise HTTPException(
                status_code=422,
                detail=f"factor {observation.factor_id} is not active for weekly monitor "
                f"(state={factor.lifecycle_state})",
            )
        observations.append(observation)
    return observations


@app.post("/api/monitor/weekly_tick")
def run_monitor_weekly_tick_endpoint(
    payload: dict[str, Any] = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """手动触发 production weekly monitor tick 的同一路径。

    Scheduler 在 startup 已注册 weekly cron；本端点用于本地运维/测试证明同一条 tick。
    输入只能是绩效/IC 观测，不能把 DSR/PBO/gate verdict 接成 live monitor。
    """

    _ = user
    week = None
    if payload.get("week"):
        try:
            week = _dt.date.fromisoformat(str(payload["week"]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="week must be YYYY-MM-DD") from exc
    drift_threshold = (
        _monitor_finite_number(payload.get("drift_threshold"), "drift_threshold")
        if payload.get("drift_threshold") is not None
        else 0.30
    )
    observations = _monitor_observations_from_payload(payload)
    result = run_weekly_monitor_tick(
        lifecycle_manager=FACTOR_LIFECYCLE,
        factor_registry=FACTOR_REGISTRY,
        execution_audit_log=EXECUTION_AUDIT_LOG,
        factor_observations=observations,
        week=week,
        asset_class=str(payload.get("asset_class") or "crypto_perp"),
        drift_threshold=drift_threshold,
    )
    graph_refs = _record_weekly_monitor_qro(
        result,
        actor=str(getattr(user, "username", None) or getattr(user, "user_id", None) or "monitor_user"),
        scheduled=False,
        asset_class=str(payload.get("asset_class") or "crypto_perp"),
        trigger="manual_api",
        drift_threshold=drift_threshold,
    )
    reconciliation_action_result = _run_pending_execution_reconciliation_actions(
        actor=str(getattr(user, "username", None) or getattr(user, "user_id", None) or "monitor_user"),
        audit_record_ref=f"audit:manual_weekly_monitor:{result.week_iso}:execution_reconciliation_actions",
        evidence_refs=(graph_refs["qro_id"], graph_refs["research_graph_command_id"], f"monitor_weekly_tick:{result.week_iso}"),
        owner_ref="monitor.weekly_tick",
    )
    return {
        "scheduled": False,
        "scheduler_configured": MONITOR_SCHEDULER is not None,
        **result.to_dict(),
        **graph_refs,
        "execution_reconciliation_action_producer": reconciliation_action_result,
    }


@app.post("/api/factors/{factor_id}/audit")
def factor_audit_endpoint(
    factor_id: str,
    payload: dict = Body(default={}),
    version: int | None = Query(None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """F2 · 因子 alpha 审查（D-F2-AUDIT 全采纳+数值可调）：cscv_pbo / DSR / N_eff /
    bootstrap CI / IC-NW 组装的多证据三角；honest-N 三档阈值可调（body/query 传）；
    verdict 全达标 consistent / 任一不达标 concern / 多个严重 blocked；文案走
    verifier._verdict_note（禁 R7 词）。绝不重写 eval 原语。
    """

    try:
        factor = FACTOR_REGISTRY.get(factor_id, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    market = str(payload.get("market", "equity_cn")).strip() or "equity_cn"
    horizon = int(payload.get("horizon", 5) or 5)
    tier = str(payload.get("tier", "standard")).strip() or "standard"
    n_trials = payload.get("n_trials")
    n_trials = int(n_trials) if isinstance(n_trials, (int, float)) and not isinstance(n_trials, bool) else None
    market_data_use_validation_refs = _factor_audit_market_data_use_validation_refs(payload, market=market)
    # 阈值覆盖：body.thresholds（dict）或顶层 min_dsr/max_pbo/min_ic_t/min_n_eff。
    overrides: dict[str, float] = {}
    raw_thr = payload.get("thresholds")
    if isinstance(raw_thr, dict):
        overrides.update(raw_thr)
    for k in ("min_dsr", "max_pbo", "min_ic_t", "min_n_eff"):
        if k in payload:
            overrides[k] = payload[k]
    try:
        report = run_factor_audit(
            factor.factor_id,
            market,
            factor.formula,
            horizon=horizon,
            tier=tier,  # type: ignore[arg-type]
            threshold_overrides=overrides or None,
            n_trials=n_trials,
        )
    except FactorAuditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    graph_refs = _record_factor_audit_qro(
        factor,
        report,
        actor=str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system"),
        market_data_use_validation_refs=market_data_use_validation_refs,
    )
    return {"version": factor.version, **report.to_dict(), **graph_refs}


@app.post("/api/factors/{factor_id}/layered_backtest")
def factor_layered_backtest(
    factor_id: str,
    payload: dict = Body(default={}),
    version: int | None = Query(None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """F2 · 分层（五分位）回测：单调性 + 多空价差。复用 layered.layered_backtest（不前视）。"""

    try:
        factor = FACTOR_REGISTRY.get(factor_id, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    market = str(payload.get("market", "equity_cn")).strip() or "equity_cn"
    horizon = int(payload.get("horizon", 5) or 5)
    n_quantiles = int(payload.get("n_quantiles", 5) or 5)
    market_data_use_validation_refs = _factor_layered_market_data_use_validation_refs(payload, market=market)
    try:
        report = layered_backtest(market, factor.formula, horizon=horizon, n_quantiles=n_quantiles)
    except (LayeredError, PanelSourceError, ExpressionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    graph_refs = _record_factor_layered_backtest_qro(
        factor,
        report,
        actor=str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system"),
        market=market,
        market_data_use_validation_refs=market_data_use_validation_refs,
    )
    return {"factor_id": factor.factor_id, "version": factor.version, **report.to_dict(), **graph_refs}


# -------- F4 · 三纯库 / 信号契约 / 暴力遍历挖掘 (R16/R17/R19) --------


@app.post("/api/factors/admit")
def factor_admit(payload: dict = Body(...)) -> dict[str, Any]:
    """R17 范畴门预检：判定某产物能否进【因子库】（不落库，只裁决）。

    - kind=model_body（或 ref 像 .pt/.pkl 本体）→ 拒（范畴错误，本体只进模型注册表）。
    - kind=expression / signal_contract 且非本体文件 → 准入。
    措辞诚实，不染绿；拒绝走 422 + 结构化原因（前端三纯库入库门用）。
    """

    kind = str(payload.get("kind", "")).strip()
    ref = str(payload.get("ref", "")).strip()
    admitted, reason = admit_artifact_to_factor_lib(kind, ref)
    if not admitted:
        raise HTTPException(
            status_code=422,
            detail={"admitted": False, "kind": kind, "ref": ref, "reason": reason},
        )
    return {"admitted": True, "kind": kind, "ref": ref, "reason": ""}


@app.post("/api/factors/signal_contracts")
def register_signal_contract(
    payload: dict = Body(...), user=Depends(require_user_dependency)
) -> dict[str, Any]:
    """R17 信号契约登记：ML/DL 模型【输出】经契约登记后才作为信号进因子库。

    入库门（违一条即 422）：
    - 范畴门：source_lib ∈ {ml, dl}；model_ref 非空（孤儿信号拒）。
    - 血统门：model_ref 必须回指模型注册表里的本体文件（.pt/.pkl…），禁止悬空。
    - 泄露声明门：leakage 须自报 OOF+purge+embargo 齐全（R18），否则拒。
    本端点【不】注册「本体」入因子库——把 .pt 当因子塞库是范畴错误，由 admit 门挡死。
    """

    try:
        contract = SIGNAL_CONTRACTS.register(
            name=str(payload.get("name", "")),
            source_lib=str(payload.get("source_lib", "")),
            model_ref=str(payload.get("model_ref", "")),
            output_kind=str(payload.get("output_kind", "")),
            horizon=int(payload.get("horizon", 0)),
            leakage=payload.get("leakage"),
            author=getattr(user, "user_id", "system"),
            description=str(payload.get("description", "")),
        )
    except SignalContractError as exc:
        raise HTTPException(
            status_code=422, detail={"registered": False, "reason": str(exc)}
        ) from exc
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    graph_refs = _record_signal_contract_qro(contract, actor=actor)
    return {"registered": True, **contract.to_dict(), **graph_refs}


@app.post("/api/factors/mine")
def factor_mine(payload: dict = Body(...)) -> dict[str, Any]:
    """R16/R19 暴力遍历挖掘：生成器（结构排序）× 守门器（独立后置）× 诚实-N。

    输入 {exprs:[{expr,fam}...], sort_key}。生成器排序键只允许结构维度；任何守门指标
    （IC/IR/DSR/Sharpe/PBO/t/return…）作排序键 → 422（解耦门，防验证集泄露）。
    诚实-N 走 lineage.config_hash 归一去重，等价改写不抬高 N_eff。
    返回 candidates 与 gate【物理分离】（守门指标从不与生成结构同列表排序）。
    """

    raw = payload.get("exprs") or []
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=422, detail="exprs 须为非空列表 [{expr, fam}]")
    exprs: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("expr"):
            exprs.append({"expr": str(item["expr"]), "fam": str(item.get("fam", "未知"))})
        elif isinstance(item, str):
            exprs.append({"expr": item, "fam": "未知"})
    if not exprs:
        raise HTTPException(status_code=422, detail="exprs 中无有效 expr")
    sort_key = str(payload.get("sort_key", "complexity"))
    try:
        result = run_mining(exprs, sort_key=sort_key)
    except MiningGateLeakError as exc:
        raise HTTPException(
            status_code=422, detail={"gate_leak": True, "reason": str(exc)}
        ) from exc
    except MiningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # GOAL §9 advisory（只记录不强制）：生成器/守门解耦边界裁决挂到产物。run_mining 已硬挡
    # 「守门指标作 sort_key」（gate_leak→422，行为不变）；本裁决在 200 路径上补充 §9 canonical
    # validator 的超集项「generator 必须命名独立 gatekeeper」（缺 gatekeeper_ref→flag）。违例不拒挖掘。
    result["boundary_verdict"] = _boundary_verdict_payload(
        validate_factor_generator(
            FactorGeneratorSpec(
                generator_ref=str(payload.get("generator_ref") or "factor_mine_request"),
                structure_inputs=tuple(sorted({str(item.get("fam", "")) for item in exprs})),
                fitness_inputs=(sort_key,),
                gatekeeper_ref=payload.get("gatekeeper_ref"),
            )
        ),
        boundary="factor_generator_§9",
    )
    return result


# -------- M12 实验追踪 --------

@app.get("/api/experiments")
def list_experiments() -> list[dict]:
    return [e.to_dict() for e in EXPERIMENT_STORE.list_experiments()]


@app.post("/api/experiments")
def create_experiment(payload: dict = Body(...)) -> dict:
    return EXPERIMENT_STORE.create_experiment(
        name=payload["name"],
        asset_class=payload.get("asset_class", "mixed"),
        description=payload.get("description", ""),
    ).to_dict()


@app.get("/api/experiments/{experiment_id}/runs")
def list_experiment_runs(experiment_id: str) -> list[dict]:
    return [r.to_dict() for r in RUN_STORE.list_runs(experiment_id)]


@app.get("/api/experiment_runs/{run_id}/lineage")
def run_lineage(run_id: str) -> list[dict]:
    try:
        return [r.to_dict() for r in RUN_STORE.lineage(run_id)]
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/models")
def list_models() -> list[str]:
    return MODEL_REGISTRY.list_models()


@app.get("/api/models/{model_id}/versions")
def list_model_versions(model_id: str) -> list[dict]:
    return [v.to_dict() for v in MODEL_REGISTRY.list_versions(model_id)]


def _model_version_ref(model_id: str, version: int) -> str:
    return f"model_version:{model_id}:v{version}"


@app.post("/api/models/{model_id}/versions/{version}/predict")
def predict_model_version(
    model_id: str,
    version: int,
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    version_record = next((v for v in MODEL_REGISTRY.list_versions(model_id) if v.version == version), None)
    if version_record is None:
        raise HTTPException(404, f"model={model_id} version={version} 未注册")
    if version_record.stage not in {"staging", "production"}:
        raise HTTPException(422, "model prediction serving requires staging or production stage")
    if not version_record.artifact_path:
        raise HTTPException(422, "model version has no artifact_path")
    if not version_record.model_passport_ref:
        raise HTTPException(422, "model prediction serving requires model_passport_ref")
    try:
        passport = MODEL_GOVERNANCE_REGISTRY.passport(version_record.model_passport_ref)
    except KeyError as exc:
        raise HTTPException(422, "model_passport_ref is not recorded") from exc
    expected_ref = _model_version_ref(model_id, version)
    if passport.model_version_ref != expected_ref:
        raise HTTPException(
            422,
            f"model_passport_ref does not match model version: {passport.model_version_ref} != {expected_ref}",
        )
    if version_record.validation_dossier_ref != passport.validation_dossier_ref:
        raise HTTPException(422, "model version validation_dossier_ref does not match passport")
    inspection = next(
        (
            item
            for item in MODEL_GOVERNANCE_REGISTRY.artifact_inspections()
            if item.model_passport_ref == passport.passport_id and item.inspection_status == "accepted"
        ),
        None,
    )
    if inspection is None:
        raise HTTPException(422, "model prediction serving requires accepted artifact inspection")
    profile = next(
        (
            item
            for item in MODEL_GOVERNANCE_REGISTRY.monitoring_profiles()
            if item.model_passport_ref == passport.passport_id
        ),
        None,
    )
    if profile is None:
        raise HTTPException(422, "model prediction serving requires monitoring profile")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(422, "rows must be a non-empty list")
    if len(rows) > 200:
        raise HTTPException(422, "rows limit is 200 per governed prediction call")
    if not all(isinstance(row, dict) for row in rows):
        raise HTTPException(422, "rows must contain objects")
    feature_cols = payload.get("feature_cols") or list(passport.feature_refs)
    if not isinstance(feature_cols, list) or not feature_cols:
        raise HTTPException(422, "feature_cols must be a non-empty list")
    feature_cols = [str(col) for col in feature_cols]
    import pandas as pd

    frame = pd.DataFrame(rows)
    missing = [col for col in feature_cols if col not in frame.columns]
    if missing:
        raise HTTPException(422, {"missing_feature_cols": missing})
    try:
        from .training.lib import load_model

        model = load_model(version_record.artifact_path)
        raw_predictions = model.predict(frame[feature_cols])
    except Exception as exc:  # noqa: BLE001 - governed serving must fail closed.
        raise HTTPException(422, f"model prediction failed: {type(exc).__name__}: {exc}") from exc
    predictions = [float(value) for value in list(raw_predictions)]
    rows_hash = content_hash(rows)
    request_hash = content_hash(
        {
            "model_id": model_id,
            "version": version,
            "stage": version_record.stage,
            "feature_cols": feature_cols,
            "row_count": len(rows),
            "rows_hash": rows_hash,
        }
    )
    prediction_hash = content_hash({"prediction_count": len(predictions), "predictions": predictions})
    signal_response: dict[str, Any] = {}
    if "signal_contract" in payload:
        signal_payload = payload.get("signal_contract")
        if not isinstance(signal_payload, dict):
            raise HTTPException(422, "signal_contract must be an object")
        leakage = signal_payload.get("leakage") or {}
        if not isinstance(leakage, dict):
            raise HTTPException(422, "signal_contract.leakage must be an object")
        horizon = int(signal_payload.get("horizon") or 0)
        if horizon <= 0:
            raise HTTPException(422, "signal_contract.horizon must be > 0")
        output_kind = str(signal_payload.get("output_kind") or "prediction_signal")
        if not output_kind.strip():
            raise HTTPException(422, "signal_contract.output_kind is required")
        protocol = SignalProtocolRecord(
            signal_ref="sig::pending_model_prediction",
            source_model_ref=str(version_record.artifact_path),
            oof=bool(leakage.get("oof")),
            purge=bool(leakage.get("purge")),
            embargo=bool(leakage.get("embargo")),
            train_test_lock_ref=signal_payload.get("train_test_lock_ref"),
            honest_n_ref=signal_payload.get("honest_n_ref"),
            forecast_time_ref=signal_payload.get("forecast_time_ref"),
            prediction_horizon_ref=signal_payload.get("prediction_horizon_ref"),
            unit_ref=signal_payload.get("unit_ref"),
            direction_semantics_ref=signal_payload.get("direction_semantics_ref"),
            confidence_ref=signal_payload.get("confidence_ref"),
            expires_at_ref=signal_payload.get("expires_at_ref"),
        )
        decision = validate_signal_protocol(protocol)
        if not decision.accepted:
            raise HTTPException(
                422,
                {
                    "signal_protocol_accepted": False,
                    "violations": [violation.__dict__ for violation in decision.violations],
                },
            )
        try:
            contract = SIGNAL_CONTRACTS.register(
                name=str(signal_payload.get("name") or f"{model_id} v{version} prediction signal"),
                source_lib=str(signal_payload.get("source_lib") or "ml"),
                model_ref=str(version_record.artifact_path),
                output_kind=output_kind,
                horizon=horizon,
                leakage=leakage,
                author=str(getattr(user, "user_id", "") or getattr(user, "username", "") or "system"),
                description=str(signal_payload.get("description") or ""),
            )
        except SignalContractError as exc:
            raise HTTPException(422, {"registered": False, "reason": str(exc)}) from exc
        signal_response = {
            "signal_ref": contract.signal_ref,
            "signal_contract": contract.to_dict(),
            "signal_protocol_refs": {
                "forecast_time_ref": protocol.forecast_time_ref,
                "prediction_horizon_ref": protocol.prediction_horizon_ref,
                "unit_ref": protocol.unit_ref,
                "direction_semantics_ref": protocol.direction_semantics_ref,
                "confidence_ref": protocol.confidence_ref,
                "expires_at_ref": protocol.expires_at_ref,
            },
        }
    serving_record = MODEL_GOVERNANCE_REGISTRY.record_serving_invocation(
        ModelServingInvocationRecord(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            artifact_inspection_ref=inspection.inspection_ref,
            monitoring_profile_ref=profile.monitoring_profile_id,
            feature_refs=tuple(feature_cols),
            row_count=len(rows),
            request_hash=request_hash,
            prediction_hash=prediction_hash,
            runtime=version_record.stage,
            recorded_by=str(getattr(user, "user_id", "") or getattr(user, "username", "") or "unknown"),
        )
    )
    serving_qro_refs = _record_model_serving_invocation_qro(serving_record, actor=_api_actor_ref(user))
    return {
        "model_id": model_id,
        "version": version,
        "stage": version_record.stage,
        "prediction_count": len(predictions),
        "predictions": predictions,
        "serving_invocation_id": serving_record.serving_invocation_id,
        "request_hash": request_hash,
        "prediction_hash": prediction_hash,
        "artifact_inspection_ref": inspection.inspection_ref,
        "monitoring_profile_ref": profile.monitoring_profile_id,
        **serving_qro_refs,
        **signal_response,
    }


@app.post("/api/models/{model_id}/promote")
def promote_model(model_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict:
    """T-019：dev/archived 直翻；staging/production 开审批门（返 pending gate 或 422+缺口清单）。

    T-024 假设卡闸门（向后兼容，传 hypothesis_card_id 才启用，不破坏既有 promote）：
    - confirmatory 卡：先过 can_touch_final_oos（探索层/未冻结/OOS 已消费 → 409 BLOCK）。
    - 非 confirmatory 卡（exploratory/secondary）走真钱（production / live_crypto / paper）→ 409 拒：
      绝不自动晋级，晋级是用户显式动作（D-T024）。纯探索（无真钱意图）不挡（P2）。
    """
    hcid = payload.get("hypothesis_card_id")
    if hcid:
        try:
            _hcard = HYPOTHESIS_STORE.get(hcid)
        except KeyError as exc:
            raise HTTPException(404, f"假设卡不存在: {hcid}") from exc
        _real_money = (payload.get("stage") in {"production"}
                       or payload.get("execution_mode") in {"live_crypto", "paper"})
        if _hcard.layer == "confirmatory":
            _gate = _can_touch_final_oos(_hcard, honest_n_now=LEDGER.honest_n(_hcard.strategy_goal_ref))
            if not _gate.allow:
                raise HTTPException(409, detail={
                    "hypothesis_gate_blocked": True, "block_reason": _gate.block_reason,
                    "warnings": _gate.warnings, "disclaimer": _gate.disclaimer,
                })
        elif _real_money:
            raise HTTPException(409, detail={
                "hypothesis_gate_blocked": True,
                "block_reason": (f"假设卡 layer={_hcard.layer} 非 confirmatory，不得直接走真钱执行/晋级；"
                                 "先显式 promote 为 confirmatory 并冻结假设卡（P2/D-T024，晋级是用户显式动作）"),
            })
    try:
        result = MODEL_REGISTRY.promote(
            model_id, int(payload["version"]), payload["stage"],
            created_by=payload.get("created_by") or user.user_id,
            verification_record_id=payload.get("verification_record_id"),
            evidence=payload.get("evidence"),
            strategy_goal_ref=payload.get("strategy_goal_ref"),
            model_passport_ref=payload.get("model_passport_ref"),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except GateStateError as exc:
        raise HTTPException(422, str(exc)) from exc
    if isinstance(result, GateRejection):
        try:
            qro_result = APPROVAL_GATE_STORE.get(result.gate_id)
        except KeyError:
            qro_result = result
        detail = {
            "rejected": True,
            "gaps": result.gap_list,
            "gate_id": result.gate_id,
            "verdict_text": result.verdict_text,
        }
        detail.update(
            _record_model_promotion_request_qro(
                model_id=model_id,
                payload=payload,
                result=qro_result,
                actor=str(getattr(user, "user_id", "") or "unknown"),
            )
        )
        raise HTTPException(422, detail=detail)
    body = result.to_dict()
    body.update(
        _record_model_promotion_request_qro(
            model_id=model_id,
            payload=payload,
            result=result,
            actor=str(getattr(user, "user_id", "") or "unknown"),
        )
    )
    return body


@app.post("/api/models/{model_id}/gates/{gate_id}/approve")
def approve_promotion_gate(model_id: str, gate_id: str, payload: dict = Body(...),
                           user=Depends(require_user_dependency)) -> dict:
    """审批 pending promote 门并真翻 stage。approver≠creator / 缺要件 / 非 pending → 422。"""
    try:
        gate = MODEL_REGISTRY.approve_promotion(
            gate_id, approver=payload.get("approver") or user.user_id,
            reason=payload.get("reason", ""), risk_restated=payload.get("risk_restated"),
        )
    except (ApproverEqualsCreator, EmptyReason, GateStateError) as exc:
        raise HTTPException(422, str(exc)) from exc
    body = gate.to_dict()
    body.update(
        _record_model_promotion_approval_qro(
            model_id=model_id,
            gate=gate,
            payload=payload,
            actor=str(getattr(user, "user_id", "") or "unknown"),
        )
    )
    return body


@app.post("/api/models/{model_id}/gates/{gate_id}/reject")
def reject_promotion_gate(model_id: str, gate_id: str, payload: dict = Body(...),
                          user=Depends(require_user_dependency)) -> dict:
    try:
        return GATE_SERVICE.reject(gate_id, approver=payload.get("approver") or user.user_id,
                                   reason=payload.get("reason", "")).to_dict()
    except GateStateError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/approval/gates/{gate_id}")
def get_approval_gate(gate_id: str, user=Depends(require_user_dependency)) -> dict:
    """R2 一键下钻：暴露门状态/缺口清单/裁决文案。"""
    try:
        return APPROVAL_GATE_STORE.get(gate_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# -------- 部件12 · 验证官（异模型一致性，产 verdict_id；T-020）--------
@app.post("/api/verification/verdicts")
def create_verdict(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict:
    """对生成方自报值做异模型重算对账，产权威 verdict_id（落 VerdictStore，供审批门/假设卡引用）。

    body: {target_ref, generator_model, checker_model, claims:{k:v}, recomputed:{k:v},
           generator_seed?, checker_seed?, generator_slice?, checker_slice?, replay_ref?, notes?}
    异模型不一致即 verdict=blocked（不取均值）；同模型→独立性未确立降 concern。
    """
    from .verification import VerifierError
    try:
        rec = VERIFIER.reconcile(
            target_ref=payload.get("target_ref", ""),
            claims=payload.get("claims") or {},
            recomputed=payload.get("recomputed") or {},
            generator_model=payload.get("generator_model", ""),
            checker_model=payload.get("checker_model", ""),
            generator_seed=payload.get("generator_seed"),
            checker_seed=payload.get("checker_seed"),
            generator_slice=payload.get("generator_slice"),
            checker_slice=payload.get("checker_slice"),
            replay_ref=payload.get("replay_ref"),
            notes=payload.get("notes", ""),
            created_at_utc=_dt.datetime.now(_dt.UTC).isoformat(),
        )
    except VerifierError as exc:
        raise HTTPException(422, str(exc)) from exc
    VERDICT_STORE.record(rec)
    return rec.to_dict()


@app.get("/api/verification/verdicts/{verdict_id}")
def get_verdict(verdict_id: str, user=Depends(require_user_dependency)) -> dict:
    try:
        return VERDICT_STORE.get(verdict_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# -------- 脊柱 04 · 可证伪假设卡端点（T-024，P2 不挡探索）--------
@app.post("/api/hypothesis_cards")
def create_hypothesis_card(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict:
    """建 draft 假设卡。P2：探索卡 falsifiable 可空，create 永不校验可证伪性。

    body: {strategy_goal_ref, layer, falsifiable?, touched_versions?, parent_card_id?}
    """
    try:
        card = HYPOTHESIS_STORE.create(
            strategy_goal_ref=payload["strategy_goal_ref"],
            layer=payload.get("layer", "exploratory"),
            falsifiable=payload.get("falsifiable"),
            touched_versions=payload.get("touched_versions"),
            parent_card_id=payload.get("parent_card_id"),
        )
    except KeyError as exc:
        raise HTTPException(422, f"缺字段: {exc}") from exc
    return card.to_dict()


@app.get("/api/hypothesis_cards/{card_id}")
def get_hypothesis_card(card_id: str, user=Depends(require_user_dependency)) -> dict:
    try:
        return HYPOTHESIS_STORE.get(card_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/hypothesis_cards/{card_id}/promote")
def promote_hypothesis_card(card_id: str, payload: dict = Body(...),
                            user=Depends(require_user_dependency)) -> dict:
    """探索→确认晋级（用户显式动作，D-T024）：校验新 OOS 切片未被源卡触碰过（防探索污染）。"""
    try:
        card = HYPOTHESIS_STORE.promote_to_confirmatory(card_id, payload["fresh_dataset_version"])
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except _PromoteRejected as exc:
        raise HTTPException(409, str(exc)) from exc
    return card.to_dict()


@app.post("/api/hypothesis_cards/{card_id}/freeze")
def freeze_hypothesis_card(card_id: str, payload: dict = Body(...),
                           user=Depends(require_user_dependency)) -> dict:
    """冻结 confirmatory 卡：三必填非空 + 可证伪性 + honest-N 实读（自 LEDGER，绝不收调用方传 N）。

    body: {frozen_oos:{dataset_version,...}, review?, human_reviewed?, override_note?}
    可证伪性 low + human_reviewed=False → 409（硬透明，不静默冻结）；human_reviewed=True 显式 override
    后仍可冻结，override 留痕进卡（D-T024-FALS，启发式绝不自动硬挡）。结构空机制 / 验证官 blocked 仍硬拒。
    """
    try:
        card = HYPOTHESIS_STORE.freeze(
            card_id,
            frozen_oos=payload.get("frozen_oos"),
            ledger=LEDGER,
            review=payload.get("review"),
            human_reviewed=bool(payload.get("human_reviewed", False)),
            override_note=payload.get("override_note"),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except _FreezeRejected as exc:
        raise HTTPException(409, str(exc)) from exc
    return card.to_dict()


@app.get("/api/hypothesis_cards/{card_id}/gate")
def hypothesis_card_gate(card_id: str, user=Depends(require_user_dependency)) -> dict:
    """can_touch_final_oos 软闸门：探索层/未冻结/OOS 已消费 → BLOCK；其余产风险提示 + needs_human_review。"""
    try:
        card = HYPOTHESIS_STORE.get(card_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    decision = _can_touch_final_oos(card, honest_n_now=LEDGER.honest_n(card.strategy_goal_ref))
    return decision.to_dict()


@app.post("/api/hypothesis_cards/{card_id}/deviation")
def hypothesis_card_deviation(card_id: str, payload: dict = Body(...),
                              user=Depends(require_user_dependency)) -> dict:
    """提交偏离：append + 自动降级标记 + 发 PROV 事件（deviations 非只读字段）。"""
    try:
        card = HYPOTHESIS_STORE.deviation(card_id, payload.get("deviation") or {})
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return card.to_dict()


# -------- 模型中心 · 训练台 (v3) --------
# 训练台"本质是跑代码"：ML 进程内、DL/代码走全功率子进程。主进程不 import torch。
from .models.catalog import (  # noqa: E402
    add_model_card,
    get_model_card,
    model_catalog_summary,
)
from .models.card_loader import ModelCardError  # noqa: E402
from .training import TrainingRequest, TrainingService, spec_to_code  # noqa: E402
from .training.agent_context import training_system_prompt  # noqa: E402
from .training.datasets import list_training_datasets, load_training_panel  # noqa: E402

TRAINING_SERVICE = TrainingService(
    DATA_ROOT / "training_runs",
    experiment_store=EXPERIMENT_STORE,
    run_store=RUN_STORE,
    model_registry=MODEL_REGISTRY,
    model_governance_registry=MODEL_GOVERNANCE_REGISTRY,
    result_recorder=_record_training_job_qro,
    timeout=1800,
)

from .training.tensorboard import TensorBoardManager  # noqa: E402

TENSORBOARD_MANAGER = TensorBoardManager()


@app.get("/api/training/models")
def training_models() -> list[dict]:
    """模型目录（类型卡：优缺点/调参 schema/算力/可用性）。"""
    return model_catalog_summary()


@app.get("/api/training/models/{key}")
def training_model_detail(key: str) -> dict:
    """单张模型卡详情（含 L1-L4 正文）。"""
    try:
        return get_model_card(key).to_detail()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/training/models")
def training_add_model(payload: dict = Body(...)) -> dict:
    """Agent/用户搜到新模型 → 补全信息加入模型卡（默认仅收录，runnable=False）。

    这是『agent 只能在卡内做，除非用户让它搜新模型加卡』的落点。
    """
    try:
        return add_model_card(payload).to_dict()
    except ModelCardError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/training/agent_context")
def training_agent_context() -> dict:
    """训练台对话 agent 的 system prompt（约束 agent 只能在模型卡内选）。"""
    return {"system_prompt": training_system_prompt()}


@app.get("/api/training/datasets")
def training_datasets() -> list[dict]:
    return list_training_datasets()


@app.post("/api/training/codegen")
def training_codegen(payload: dict = Body(...)) -> dict:
    """预览：把结构化 spec（或构建台图）渲染成将要跑的训练代码（让用户看到'本质是跑代码'）。

    - payload 带 `graph`(nodes/edges) → 走 `graph_to_code`（构建台线性链子集，D-DESK-F1B(a)）。
    - 否则按结构化 spec 走 `spec_to_code`（向后兼容既有卡内模型路径，不破坏）。
    【M6】无论哪条都是**纯字符串拼装**，主进程绝不 import torch；真编译/训练唯经 runner 子进程。
    """
    graph = payload.get("graph")
    try:
        if graph is not None:
            from .training.codegen import GraphCodegenError, graph_to_code
            try:
                return {"code": graph_to_code(graph), "mode": "graph", "compiled": False}
            except GraphCodegenError as exc:
                raise HTTPException(400, str(exc)) from exc
        return {"code": spec_to_code(payload), "mode": "spec"}
    except (KeyError, NotImplementedError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/training/jobs")
def training_jobs() -> list[dict]:
    return [j.to_dict() for j in TRAINING_SERVICE.list_jobs()]


@app.get("/api/training/jobs/{job_id}")
def training_job(job_id: str) -> dict:
    try:
        return TRAINING_SERVICE.get_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/training/jobs/{job_id}/eval")
def training_job_eval(job_id: str) -> dict:
    """训练结束的评价图（特征重要度/学习曲线/预测-实际/残差/ROC/分fold）。"""
    import json  # main.py 无模块级 json，函数内 import（与本文件其它端点一致）

    from .eval.model_eval import build_eval_charts, conformal_prediction_band, summarize_metrics

    try:
        job = TRAINING_SERVICE.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not job.artifact_dir:
        return {"status": job.status, "charts": [], "metrics": {}}
    result_path = Path(job.artifact_dir) / "result.json"
    if not result_path.exists():
        return {"status": job.status, "charts": [], "metrics": job.metrics}
    result = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "status": job.status,
        "model": job.model,
        "family": job.family,
        "charts": build_eval_charts(result),
        "metrics": summarize_metrics(result),
        # R23 闭环：回归 OOS 的 split-conformal 校准区间 + 真留出覆盖率（None=分类/无 OOS，不适用）。
        "conformal_interval": conformal_prediction_band(result),
        # R4 闭环：CPCV 路径稳健性分布（q05/路径方差=过拟合脆弱度）。None=未开 compute_cpcv（不假绿灯：未算≠已算）。
        "cpcv_distribution": result.get("cpcv_distribution"),
    }


@app.get("/api/training/jobs/{job_id}/walkforward")
def training_job_walkforward(job_id: str) -> dict:
    """walk-forward 逐窗明细（模型库 DRILL-IN 用：每窗训练段/测试段 + OOS 主指标）。

    诚实合约（不假绿）：只有 cv_scheme=='walk_forward' 才标 ran=True；purged_kfold 等 → ran=False、
    前端显示「walk-forward 待跑」。负窗 metric 原样返回（可为负），由前端按正负诚实上色。
    未训完 / 无 result.json → windows=[]，绝不编造逐窗。
    """
    import json

    from .eval.model_eval import walk_forward_windows

    try:
        job = TRAINING_SERVICE.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not job.artifact_dir:
        return {"status": job.status, "ran": False, "n_windows": 0, "windows": []}
    result_path = Path(job.artifact_dir) / "result.json"
    if not result_path.exists():
        return {"status": job.status, "ran": False, "n_windows": 0, "windows": []}
    result = json.loads(result_path.read_text(encoding="utf-8"))
    out = walk_forward_windows(result)
    out["status"] = job.status
    out["model"] = job.model
    return out


@app.post("/api/training/jobs/{job_id}/backtest")
def training_job_backtest(job_id: str, payload: dict = Body(default={})) -> dict:
    """用训练好的模型回测。支持样本外(OOS)：

    - `dataset_id`：在**另一个**数据集上回测（模型没训过的数据 → 真·样本外）。默认=训练数据集。
    - `oos_fraction`：只回测末尾这一比例的交易日（如 0.3 = 后 30%）。默认 None=全段。
    predict_with → 每日 top-N 权重(shift1 防前视) → 组合收益 → 指标 + 净值曲线。
    """
    from .training.backtest_bridge import backtest_job
    from .training.datasets import FEATURES

    try:
        job = TRAINING_SERVICE.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if job.status != "succeeded" or not job.artifact_dir:
        raise HTTPException(400, f"任务未成功完成，无法回测（status={job.status}）")

    req = job.request or {}
    train_dataset = req.get("dataset_id") or "demo_ashare_xsec"
    # payload.dataset_id 优先（用户选的 OOS 数据集）；否则回训练集
    dataset_id = payload.get("dataset_id") or train_dataset
    feature_cols = req.get("feature_cols") or FEATURES
    oos_fraction = payload.get("oos_fraction")
    is_cross_dataset = dataset_id != train_dataset
    train_fraction = req.get("train_fraction")
    # 严格无泄露 walk-forward：若模型只用前 train_fraction 训练，且回测同一数据集、用户没显式指定
    # oos_fraction → 自动取互补的后段 (1 - train_fraction)，使回测窗口正好是训练未见过的那段。
    strict_oos = False
    if oos_fraction is None and train_fraction is not None and not is_cross_dataset:
        oos_fraction = 1.0 - float(train_fraction)
        strict_oos = True
    try:
        panel = load_training_panel(dataset_id)
    except KeyError as exc:
        raise HTTPException(400, f"未知数据集: {dataset_id}") from exc
    market_data_use_validation_refs = _training_market_data_use_validation_refs(
        payload,
        dataset_id=dataset_id,
        fallback_refs=req.get("market_data_use_validation_refs") or (),
        operation="training job backtests",
        dataset_label="backtest dataset",
    )
    try:
        bt = backtest_job(
            job.artifact_dir,
            panel,
            feature_cols=feature_cols,
            symbol_col=req.get("symbol_col", "symbol"),
            top_n=int(payload.get("top_n", 5)),
            long_short=bool(payload.get("long_short", False)),
            oos_fraction=float(oos_fraction) if oos_fraction is not None else None,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    eq = bt["equity_curve"]
    graph_refs = _record_training_job_backtest_qro(
        job=job,
        request_payload=req,
        backtest_payload=payload,
        backtest_result=bt,
        dataset_id=str(dataset_id),
        train_dataset=str(train_dataset),
        market_data_use_validation_refs=market_data_use_validation_refs,
        is_cross_dataset=bool(is_cross_dataset),
        strict_oos=bool(strict_oos),
        oos_fraction=float(oos_fraction) if oos_fraction is not None else None,
    )
    return {
        "job_id": job_id,
        "model": job.model,
        "dataset_id": dataset_id,
        "train_dataset": train_dataset,
        "market_data_use_validation_refs": list(market_data_use_validation_refs),
        "train_fraction": train_fraction,
        "is_oos": bool(is_cross_dataset or oos_fraction),
        "is_cross_dataset": is_cross_dataset,
        "strict_oos": strict_oos,  # True = 训练前段/回测后段严格互补、零泄露
        "oos_cutoff": bt.get("oos_cutoff"),
        "metrics": bt["metrics"],
        "equity_curve": [float(x) for x in eq.to_numpy()],
        "n_days": bt["n_days"],
        "n_symbols": bt["n_symbols"],
        **graph_refs,
    }


@app.post("/api/training/jobs/{job_id}/tensorboard")
def training_tensorboard_start(job_id: str) -> dict:
    """为 DL 训练 job 启动 TensorBoard（独立端口），返回可直接打开的本机 URL。"""
    if not TENSORBOARD_MANAGER.is_available():
        raise HTTPException(400, "未安装 tensorboard")
    try:
        job = TRAINING_SERVICE.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    logdir = Path(job.artifact_dir) / "tb" if job.artifact_dir else None
    if not logdir or not logdir.exists():
        raise HTTPException(404, "该任务没有 TensorBoard 日志（仅 DL 训练产出）")
    try:
        inst = TENSORBOARD_MANAGER.start(job_id, logdir)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"url": inst.url, "port": inst.port, "job_id": job_id}


@app.get("/api/training/jobs/{job_id}/tensorboard")
def training_tensorboard_status(job_id: str) -> dict:
    inst = TENSORBOARD_MANAGER.get(job_id)
    if inst is None:
        return {"running": False, "available": TENSORBOARD_MANAGER.is_available()}
    return {"running": True, "url": inst.url, "port": inst.port}


def _training_dataset_ref_matches(dataset_ref: str, dataset_id: str) -> bool:
    ref = str(dataset_ref or "").strip()
    dataset = str(dataset_id or "").strip()
    if not ref or not dataset:
        return False
    if ref == dataset:
        return True
    parts = ref.split(":")
    return len(parts) >= 2 and parts[0] == "dataset" and parts[1] == dataset


def _training_market_data_use_validation_refs(
    payload: dict[str, Any],
    *,
    dataset_id: str,
    fallback_refs: Iterable[str] = (),
    operation: str = "training jobs",
    dataset_label: str = "training dataset",
) -> tuple[str, ...]:
    raw_refs = payload.get("market_data_use_validation_refs")
    if raw_refs is None:
        candidate_refs: list[Any] = list(fallback_refs or ())
    elif isinstance(raw_refs, list):
        candidate_refs = raw_refs
    else:
        raise HTTPException(
            status_code=422,
            detail="market_data_use_validation_refs must be a list of refs",
        )
    if not candidate_refs:
        raise HTTPException(
            status_code=422,
            detail=f"market_data_use_validation_refs is required for {operation}",
        )
    validation_refs: list[str] = []
    covers_dataset = False
    for idx, raw_ref in enumerate(candidate_refs):
        validation_ref = str(raw_ref or "").strip()
        if not validation_ref:
            raise HTTPException(
                status_code=422,
                detail=f"market_data_use_validation_refs[{idx}] must be a non-empty ref",
            )
        try:
            record = MARKET_DATA_REGISTRY.use_validation(validation_ref)
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"unknown market data use validation: {validation_ref}",
            ) from exc
        if not bool(getattr(record, "accepted", False)):
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} is not accepted",
            )
        violation_codes = tuple(getattr(record, "violation_codes", ()) or ())
        if violation_codes:
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} has unresolved violations",
            )
        if any(_training_dataset_ref_matches(dataset_ref, dataset_id) for dataset_ref in getattr(record, "dataset_refs", ())):
            covers_dataset = True
        validation_refs.append(validation_ref)
    if not covers_dataset:
        raise HTTPException(
            status_code=422,
            detail=f"market_data_use_validation_refs do not cover {dataset_label}: {dataset_id}",
        )
    return tuple(dict.fromkeys(validation_refs))


@app.post("/api/training/jobs")
def training_submit(payload: dict = Body(...)) -> dict:
    """提交训练（异步，前端轮询 jobs/{id}）。dataset_id 选内置训练集。"""
    dataset_id = str(payload.get("dataset_id") or "")
    try:
        panel = load_training_panel(dataset_id)
    except KeyError as exc:
        raise HTTPException(400, f"未知数据集: {payload.get('dataset_id')}") from exc
    market_data_use_validation_refs = _training_market_data_use_validation_refs(payload, dataset_id=dataset_id)
    try:
        req = TrainingRequest(
            name=payload.get("name") or "训练任务",
            model=payload["model"],
            task=payload["task"],
            feature_cols=payload.get("feature_cols") or [],
            label_col=payload.get("label_col", "label"),
            asset_class=payload.get("asset_class", "a_share"),
            dataset_id=dataset_id,
            market_data_use_validation_refs=list(market_data_use_validation_refs),
            cv_scheme=payload.get("cv_scheme", "purged_kfold"),
            n_splits=int(payload.get("n_splits", 5)),
            group_col=payload.get("group_col"),
            symbol_col=payload.get("symbol_col", "symbol"),
            ts_col=payload.get("ts_col", "ts"),
            train_fraction=payload.get("train_fraction"),
            hyperparams=payload.get("hyperparams") or {},
            input_models=payload.get("input_models") or [],
            detail=payload.get("detail") or {},  # 动机/设计富文档（持久化进 job，作业台动机卡用）
            as_of_known=payload.get("as_of_known"),  # B-PIT-1 全链：PIT 双时态知识时点透传进 service（None=现状·向后兼容）
        )
        job = TRAINING_SERVICE.submit(req, panel)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return job.to_dict()


# -------- M9.3 安全 / 风控 --------

@app.get("/api/security/keystore")
def list_keystore_names() -> dict[str, Any]:
    return {"backend": KEYSTORE.backend_name, "names": KEYSTORE.list_names()}


@app.post("/api/security/keystore")
def store_keystore_record(payload: dict = Body(...)) -> dict:
    KEYSTORE.store(
        KeystoreRecord(
            name=payload["name"],
            api_key=payload["api_key"],
            api_secret=payload["api_secret"],
            note=payload.get("note", ""),
        )
    )
    return {"stored": payload["name"], "backend": KEYSTORE.backend_name}


@app.get("/api/security/secrets")
def secrets_status() -> dict[str, Any]:
    """返回最近一次 secrets.yaml 加载状态（不回显 key）。"""
    return _SECRETS_REPORT.to_dict()


# ---- mainnet/testnet 网络切换 + 二次确认 ----

_NETWORK_STATE: dict[str, str] = {"binance_network": "testnet", "confirmed_at_utc": ""}


@app.get("/api/security/network")
def get_network() -> dict[str, Any]:
    return {**_NETWORK_STATE, "mode": "live_crypto" if _NETWORK_STATE["binance_network"] == "mainnet" else "paper"}


@app.post("/api/security/network")
def set_network(payload: dict = Body(...)) -> dict[str, Any]:
    """切换 binance_network。mainnet 必须传 acknowledged=true（二次确认）。"""
    import datetime as _dt

    network = payload.get("binance_network", "testnet")
    if network not in {"testnet", "mainnet"}:
        raise HTTPException(400, "binance_network 必须是 testnet 或 mainnet")
    if network == "mainnet" and not payload.get("acknowledged"):
        raise HTTPException(
            400,
            "切到 mainnet 必须传 acknowledged=true 且文案需含 '我已阅读 Binance 安全指南'",
        )
    if network == "mainnet":
        statement = (payload.get("statement") or "").strip()
        if "我已阅读" not in statement and "I have read" not in statement:
            raise HTTPException(400, "statement 必须包含「我已阅读」字样")
    _NETWORK_STATE["binance_network"] = network
    _NETWORK_STATE["confirmed_at_utc"] = _dt.datetime.now(_dt.UTC).isoformat()
    ERROR_REPORTER.report(  # 用 error reporter 顺道写 audit
        Exception(f"network_switch:{network}"),
        {"network": network, "confirmed_at_utc": _NETWORK_STATE["confirmed_at_utc"]},
    ) if False else None  # 不发 sentry；仅留位
    return _NETWORK_STATE


@app.post("/api/security/reload_secrets")
def reload_secrets() -> dict[str, Any]:
    """热加载 ~/.quantbt/secrets.yaml。"""
    global _SECRETS_REPORT
    _SECRETS_REPORT = load_secrets(KEYSTORE)
    global _LLM_SETTINGS_BOOTSTRAP_REPORT
    _LLM_SETTINGS_BOOTSTRAP_REPORT = _bootstrap_loaded_llm_settings_metadata()
    return _SECRETS_REPORT.to_dict()


# -------- LLM 配置（UI 直填用） --------

@app.get("/api/llm/status")
def llm_status() -> dict:
    """列出每个 provider 配置状态 + 当前 active provider。"""
    return {
        "providers": list_llm_status(KEYSTORE, onboarding_registry=ONBOARDING_REGISTRY),
        "active_provider": os.environ.get("LLM_PROVIDER", "auto"),
    }


# ============================================================
# v1.0.3 · Stripe 订阅 endpoint (scaffold)
# ============================================================


@app.get("/api/billing/plans")
def billing_list_plans() -> list[dict[str, Any]]:
    return [
        {"id": p, **{k: v for k, v in PLAN_INFO[p].items() if not k.startswith("stripe_")}}
        for p in PLAN_IDS
    ]


@app.get("/api/billing/me")
def billing_me(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return BILLING_SERVICE.get_subscription(user.user_id).to_dict()


@app.post("/api/billing/upgrade_request")
def billing_upgrade_request(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    plan = payload.get("plan", "")
    cycle = payload.get("billing_cycle", "monthly")
    if plan not in PLAN_IDS:
        raise HTTPException(400, f"plan must be one of {PLAN_IDS}")
    if plan == "community":
        from .billing.stripe_service import SubscriptionRecord as _SR
        import time as _t
        sub = BILLING_SERVICE.get_subscription(user.user_id)
        sub.plan = "community"
        sub.status = "active"
        BILLING_SERVICE.upsert_subscription(sub)
        return {"status": "downgraded", "plan": "community"}
    return {
        "status": "pending_payment",
        "plan": plan,
        "billing_cycle": cycle,
        "checkout_url": f"/stripe_checkout_stub?plan={plan}&cycle={cycle}&user_id={user.user_id}",
        "note": "scaffold - 接入 Stripe SDK 后此 URL 是 stripe.com/c/pay/cs_xxx",
    }


@app.post("/api/billing/webhook")
def billing_webhook(payload: dict = Body(...)) -> dict[str, Any]:
    try:
        result = BILLING_SERVICE.process_stripe_event(payload)
        return {"received": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"webhook 处理失败: {exc}") from exc


@app.get("/api/billing/check_feature")
def billing_check_feature(feature: str = Query(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    ok = BILLING_SERVICE.user_can_access_feature(user.user_id, feature)
    return {"feature": feature, "allowed": ok}


# ============================================================
# v1.0 · mainnet 7 项防御 endpoint
# ============================================================


@app.get("/api/security/mainnet/config")
def mainnet_get_config(user=Depends(require_user_dependency)) -> dict[str, Any]:
    cfg = MAINNET_GUARDS.get_config(user.user_id)
    # 不回显加密 secret 给前端
    return {
        "user_id": cfg.user_id,
        "trusted_ips": cfg.trusted_ips,
        "totp_enabled": cfg.totp_enabled,
        "daily_operation_limit": cfg.daily_operation_limit,
        "daily_notional_limit_usdt": cfg.daily_notional_limit_usdt,
        "require_password_per_order": cfg.require_password_per_order,
        "updated_at_utc": cfg.updated_at_utc,
    }


@app.post("/api/security/mainnet/config")
def mainnet_update_config(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    cfg = MAINNET_GUARDS.get_config(user.user_id)
    if "trusted_ips" in payload:
        ips = payload["trusted_ips"]
        if not isinstance(ips, list):
            raise HTTPException(400, "trusted_ips 必须是 list")
        cfg.trusted_ips = [str(ip) for ip in ips]
    if "daily_operation_limit" in payload:
        cfg.daily_operation_limit = int(payload["daily_operation_limit"])
    if "daily_notional_limit_usdt" in payload:
        cfg.daily_notional_limit_usdt = float(payload["daily_notional_limit_usdt"])
    if "require_password_per_order" in payload:
        cfg.require_password_per_order = bool(payload["require_password_per_order"])
    MAINNET_GUARDS.upsert_config(cfg)
    return mainnet_get_config(user=user)


@app.post("/api/security/mainnet/2fa/enable")
def mainnet_2fa_enable(user=Depends(require_user_dependency)) -> dict[str, Any]:
    secret, uri = MAINNET_GUARDS.enable_totp(user.user_id)
    # 返回一次明文 secret + otpauth URI (前端展示 QR + 文字)
    return {"secret": secret, "otpauth_uri": uri, "enabled": True}


@app.post("/api/security/mainnet/2fa/verify")
def mainnet_2fa_verify(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    code = payload.get("code", "")
    ok = MAINNET_GUARDS.verify_totp(user.user_id, code)
    return {"ok": ok}


@app.get("/api/security/mainnet/usage")
def mainnet_today_usage(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return MAINNET_GUARDS.get_today_usage(user.user_id)


@app.get("/api/security/mainnet/audit_log")
def mainnet_audit_log(limit: int = Query(100, ge=1, le=500), user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return MAINNET_GUARDS.list_audit_log(user.user_id, limit=limit)


def _client_ip(request: Request) -> str:
    """动钱端点的真客户端 IP：服务端从连接派生，绝不信 body。

    body 里的 source_ip 可被任意伪造 → IP 白名单形同虚设（攻击者填一个已加白的值即过）；
    故所有需 IP 校验的动钱端点一律用本函数取真实来源 IP。
    注：若部署在反向代理后，request.client.host 是代理 IP——须在受信代理层处理 X-Forwarded-For
    并相应配置 trusted_ips；此处默认【不信任】XFF 头（客户端可伪造）。
    """
    return request.client.host if request.client else "unknown"


def _verify_second_factor(user_id: str, payload: dict) -> bool:
    """动钱端点 per-request 二次鉴权：服务端【真校验】账户密码(PBKDF2) 或 2FA TOTP，至少一个通过。

    绝不信 body 里的自证 bool（旧 password_verified）——那是客户端自我声称、可伪造（持 token 即可置 true）。
    现改为后端用 AUTH_SERVICE.verify_password / MAINNET_GUARDS.verify_totp 真比对凭据本身。
    """
    password = str(payload.get("password") or "")
    totp_code = str(payload.get("totp_code") or "")
    if password and AUTH_SERVICE.verify_password(user_id, password):
        return True
    if totp_code and MAINNET_GUARDS.verify_totp(user_id, totp_code):
        return True
    return False


@app.post("/api/security/mainnet/emergency_close_all")
def mainnet_emergency_close_all(request: Request, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """v1.0 · 紧急一键 cancel_all_open + close_position 全 symbol。

    不需要 TOTP 强制（紧急情况），但必须 IP 白名单 + 二次鉴权（密码或 TOTP，服务端真校验）。
    IP 由服务端从连接派生（_client_ip），二次鉴权由 _verify_second_factor 真比对凭据，均不信 body 自证值。
    """
    source_ip = _client_ip(request)
    if not MAINNET_GUARDS.check_ip(user.user_id, source_ip):
        raise HTTPException(403, f"IP {source_ip} 不在白名单 - emergency 仍需 IP 校验")
    if not _verify_second_factor(user.user_id, payload):
        raise HTTPException(403, "emergency_close_all 二次鉴权失败：需服务端校验账户密码或 2FA TOTP")
    # T-025/D-T025：从空壳改为真执行——真调 KILL_SWITCH（cancel_all_open + close_position 全 symbol）。
    # 平仓本体 fail-open（门坏也要能平仓），护栏在上面的 IP+密码二次鉴权，不在「能不能平仓」。
    results = KILL_SWITCH.trigger(close_positions=True)
    # 含 venue 平仓失败 → 绝不报 ok:True（5-lens HIGH：操作者读 ok 会误信已平仓，真钱面不假绿灯）。
    ok, audit_result, err = _killswitch_status(results)
    MAINNET_GUARDS.log_operation(
        user.user_id, "emergency_close_all",
        source_ip=source_ip, password_verified=True, result=audit_result, error=err,
    )
    return {"ok": ok, "status": audit_result, "results": results}


@app.get("/api/security/binance/verify")
def security_binance_verify(network: str = Query("testnet")) -> dict[str, Any]:
    """v0.9.5+ · 真发签名请求验证 binance API key 是否真的是该 network。

    流程:
      1. 从 keystore 拿 binance_<network> record (绝不返回 key)
      2. 对 https://testnet.binancefuture.com/fapi/v1/apiKey/permissions 发签名 GET
         (或 mainnet 对应 url)
      3. 返回 {ok, is_correct_network, permissions, signed_url_base}
         · 签名通过 → key 真属于该 network
         · -2014/-2015 invalid api key → key 不属于该 network
         · 其他错误透传

    安全:
      - 整流程不暴露 api_key/secret 到响应或日志
      - 只返回 permission bool 字段（不返回 key/secret 自身）
      - 如果 key 验证为 mainnet 但 network=testnet（或反过来），明确警告
    """

    if network not in ("testnet", "mainnet"):
        raise HTTPException(400, "network must be testnet or mainnet")

    from .execution.binance_client import BinanceClient, BinanceCredentials
    from .security.keystore import KeystoreError

    try:
        record = KEYSTORE.fetch(f"binance_{network}")
    except KeystoreError:
        return {
            "ok": False,
            "error": "key_not_found",
            "detail": f"keystore 里没有 binance_{network}，secrets.yaml 是否填了 binance.{network}.api_key/api_secret？",
            "is_correct_network": None,
        }

    cred = BinanceCredentials(api_key=record.api_key, api_secret=record.api_secret, network=network)
    client = BinanceClient(cred, product="usdm_futures")

    base_url = client.base_url  # 已自动选 testnet/mainnet URL
    # 用 /fapi/v2/balance 验证 (testnet 必有 + 签名校验路径)
    try:
        payload = client._signed("GET", "/fapi/v2/balance", {})
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "-2014" in msg or "-2015" in msg or "API-key format invalid" in msg:
            err_kind = "invalid_api_key"
            detail = "API key 格式或权限有问题，大概率是把 mainnet key 填进了 testnet slot（反之同理）"
        elif "Signature" in msg or "-1022" in msg:
            err_kind = "bad_signature"
            detail = "签名校验失败 - api_secret 不匹配 api_key (复制时少了字符？)"
        elif "404" in msg:
            err_kind = "endpoint_not_found"
            detail = "endpoint 路径错；可能是 spot key 填进了 futures slot"
        else:
            err_kind = "unknown"
            detail = msg
        return {
            "ok": False,
            "error": err_kind,
            "detail": detail,
            "raw_error": msg,
            "signed_url_base": base_url,
            "is_correct_network": False,
            "remediation": (
                "1. 确认 https://testnet.binancefuture.com 的 API Key 和 Secret 完整复制（Secret 只显示一次，可能漏字符）\n"
                "2. testnet key 不定期失效，需要重新生成\n"
                "3. 不要把 testnet.binance.vision (spot) 的 key 填到 futures 这边"
            ),
        }

    # 签名通过 → key 真属于该 network；payload 是余额列表
    # Permission 信息走另一个 endpoint（如 /fapi/v1/account 或 testnet 直接根据下单结果推断）
    asset_count = len(payload) if isinstance(payload, list) else 0
    total_usdt = 0.0
    if isinstance(payload, list):
        for asset in payload:
            if asset.get("asset") == "USDT":
                try:
                    total_usdt = float(asset.get("balance", 0))
                except (TypeError, ValueError):
                    pass
                break

    return {
        "ok": True,
        "is_correct_network": True,
        "network": network,
        "signed_url_base": base_url,
        "assets_count": asset_count,
        "usdt_balance": total_usdt,
        "safekey_status": "PASS",
        "note": (
            f"✅ testnet key 验证通过。"
            f"账户有 {asset_count} 种资产，USDT 余额 {total_usdt:.2f}。"
            f"如果 USDT=0，去 testnet.binancefuture.com → Wallet → 领取 testnet 测试 USDT。"
            if network == "testnet"
            else f"⚠️ MAINNET key 验证通过。USDT 余额 {total_usdt:.2f}。请先确认 enableWithdrawals=False 再下单。"
        ),
    }


@app.post("/api/llm/active")
def llm_set_active(payload: dict = Body(...)) -> dict[str, Any]:
    """v0.9.5 · 进程内切 active LLM provider。不持久化到 secrets.yaml；重启回 auto。

    安全考虑：
    - 仅允许切到 already-configured 的 provider（防 enum injection）
    - 不接受 base_url/api_key 修改（那是 /api/llm/configure 的事）
    """

    provider = (payload.get("provider") or "").strip().lower()
    if provider not in ("auto", "anthropic", "openai", "qwen", "custom"):
        raise HTTPException(400, "provider must be auto/anthropic/openai/qwen/custom")
    if provider != "auto":
        # 校验该 provider 真已配置
        statuses = list_llm_status(KEYSTORE, onboarding_registry=ONBOARDING_REGISTRY)
        match = next((s for s in statuses if s["provider"] == provider), None)
        if not match or not match.get("configured"):
            raise HTTPException(400, f"provider {provider} 未配置 (configured=False)，请先去 /api/llm/configure")
    if provider == "auto":
        os.environ.pop("LLM_PROVIDER", None)
    else:
        os.environ["LLM_PROVIDER"] = provider
    return {"active_provider": os.environ.get("LLM_PROVIDER", "auto")}


@app.post("/api/llm/configure")
def llm_configure(payload: dict = Body(...)) -> dict[str, Any]:
    """从前端表单接收：provider + api_key + base_url + model，写入 keystore。

    payload 形如：
        {"provider": "anthropic", "api_key": "sk-ant-...", "base_url": "", "model": ""}
    或：
        {"provider": "custom", "api_key": "ollama", "base_url": "http://localhost:11434/v1", "model": "qwen2.5:32b"}
    """
    import json as _json

    provider = payload.get("provider")
    if provider not in {"anthropic", "openai", "qwen", "custom"}:
        raise HTTPException(400, f"unknown provider: {provider}")
    api_key = (payload.get("api_key") or "").strip()
    base_url = (payload.get("base_url") or "").strip()
    model = (payload.get("model") or "").strip()
    if provider == "custom" and not (base_url and model):
        raise HTTPException(400, "custom 必须同时填 base_url 和 model")
    if not api_key and provider != "custom":
        raise HTTPException(400, f"{provider} 必须填 api_key")
    KEYSTORE.store(
        KeystoreRecord(
            name=f"llm_{provider}",
            api_key=api_key or "no-key",
            api_secret=api_key or "no-key",
            note=_json.dumps({"base_url": base_url, "model": model}, ensure_ascii=False),
        )
    )
    settings_refs = _record_settings_managed_llm_provider(
        provider,
        base_url=base_url,
        model=model,
        owner="llm-configure-api",
        replace_secret=True,
    )
    return {"configured": provider, "base_url": base_url, "model": model, "settings_refs": settings_refs}


@app.get("/api/observability/errors")
def observability_errors() -> dict:
    return ERROR_REPORTER.info_snapshot()


@app.get("/api/jobs/{job_id}/stream")
def stream_job_events(job_id: str):
    """SSE：连上后立即收到 snapshot，每次 progress 改动 push 一条事件，终态自动关闭。"""

    def _sse():
        import json as _json
        for evt in JOB_STORE.stream_job(job_id):
            line = (
                f"event: {evt['event']}\n"
                f"data: {_json.dumps(evt['data'], ensure_ascii=False, default=str)}\n\n"
            )
            yield line.encode("utf-8")
            if evt["event"] in {"done", "error"}:
                return

    return StreamingResponse(_sse(), media_type="text/event-stream")


@app.get("/api/data/export/size")
def data_export_size() -> dict:
    return estimate_export_size(DATA_ROOT)


@app.get("/api/data/export")
def data_export():
    fname = f"quantbt-export-{__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    return StreamingResponse(
        export_tar_gz_stream(DATA_ROOT),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# --- 官方数据更新通道（与软件更新分两条线；客户端 Win/Mac 据此下载官方数据库更新）-----------

def _official_catalog_files() -> list[dict]:
    from .tushare_quant1.data_catalog import load_data_catalog

    return load_data_catalog(_QB_PATHS, rebuild_if_missing=True).get("files") or []


@app.get("/api/data-packages/manifest")
def data_package_manifest() -> dict:
    """官方数据清单 + 数据版本号 + 每文件指纹 + 官方字段定义。客户端据此算增量、并把 official_fields 合并进本地字段表。"""
    from .data_packages import official_manifest

    m = official_manifest(_official_catalog_files(), _QB_PATHS.root)
    try:
        FIELD_CATALOG_STORE.sync_from_catalog(FIELD_CATALOG)
    except Exception:  # noqa: BLE001
        pass
    m["official_fields"] = FIELD_CATALOG_STORE.list(official=True)  # 供客户端 merge_official 合并
    return m


@app.get("/api/data-packages/download")
def data_package_download(paths: str | None = Query(None)):
    """下载官方数据 zip（内含 manifest.json）。paths=逗号分隔相对路径→增量；省略→全量。

    按 data_version 缓存复用（避免每次重压 + 客户端断连导致临时文件泄漏）。
    """
    import hashlib as _hl

    from fastapi.responses import FileResponse

    from .data_packages import build_package_zip, official_manifest

    files = _official_catalog_files()
    manifest = official_manifest(files, _QB_PATHS.root)
    try:
        FIELD_CATALOG_STORE.sync_from_catalog(FIELD_CATALOG)
        manifest["official_fields"] = FIELD_CATALOG_STORE.list(official=True)  # 让 zip 内 manifest 带官方字段定义供客户端合并
    except Exception:  # noqa: BLE001
        pass
    version = manifest["data_version"]
    rel = [p for p in paths.split(",") if p.strip()] if paths else None
    key = version if rel is None else f"{version}-{_hl.sha256(','.join(sorted(rel)).encode()).hexdigest()[:10]}"
    cache_dir = DATA_ROOT / "_cache" / "data-packages"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"quantbt-official-data-{key}.zip"
    if not out.exists():
        build_package_zip(files, _QB_PATHS.root, out, rel_paths=rel, manifest=manifest)
    return FileResponse(out, media_type="application/zip", filename=out.name)


class _DataPullUpstreamRequest(_BaseModel):
    upstream_url: str
    paths: list[str] | None = None


@app.post("/api/data-packages/pull")
def data_package_pull(req: _DataPullUpstreamRequest) -> dict:
    """客户端(Win/Mac 本地后端)从上游网站拉官方数据更新并应用：防 zip-slip 解压进本地数据湖 →
    重建 inventory → 把 official_fields 合并进字段宇宙表。与软件更新是两条独立通道。"""
    from .data_packages import pull_and_apply

    report = pull_and_apply(req.upstream_url, DATA_ROOT, paths=req.paths)
    try:
        _rebuild_inventory()
    except Exception:  # noqa: BLE001
        pass
    merged = 0
    try:
        merged = FIELD_CATALOG_STORE.merge_official(report.get("official_fields") or [])
        FIELD_CATALOG_STORE.sync_from_catalog(FIELD_CATALOG)
    except Exception:  # noqa: BLE001
        pass
    return {
        "applied_files": len(report.get("applied_files") or []),
        "skipped": len(report.get("skipped") or []),
        "data_version": report.get("data_version"),
        "merged_official_fields": merged,
    }


@app.middleware("http")
async def _report_unhandled_exceptions(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001
        ERROR_REPORTER.report(exc, {"path": str(request.url.path), "method": request.method})
        raise


@app.post("/api/llm/test")
def llm_test(payload: dict = Body(default_factory=dict)) -> dict[str, Any]:
    """让前端"测试连接"按钮一键 ping LLM provider。"""
    provider = payload.get("provider")
    try:
        client = make_settings_managed_llm_client(
            provider=provider,
            keystore=KEYSTORE,
            registry=ONBOARDING_REGISTRY,
            role_agent="settings_connection_test",
            desk="settings",
            task_type="connection_test",
        )
        from .agent import LLMMessage
        resp = client.chat(
            [LLMMessage(role="user", content=payload.get("ping", "回我一句 ok"))],
            tools=None,
            temperature=0.0,
        )
        return {
            "provider": client.provider,
            "ok": True,
            "reply_preview": (resp.content or "")[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {"provider": provider, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/risk/alerts")
def risk_alerts() -> dict[str, Any]:
    return {
        "paused": RISK_MONITOR.paused,
        "alerts": RISK_MONITOR.alerts(),
        "limits": {
            "per_order_max_usdt": RISK_LIMITS.per_order_max_usdt,
            "daily_loss_limit_pct": RISK_LIMITS.daily_loss_limit_pct,
            "daily_order_count_max": RISK_LIMITS.daily_order_count_max,
        },
    }


def _killswitch_status(results: dict[str, Any]) -> tuple[bool, str, str | None]:
    """据 KILL_SWITCH.trigger 的 per-venue results 派生【诚实】状态——绝不一律 ok（不假绿灯）。

    trigger 是 fail-open（cancel/close 抛错不上抛，塞 {error,stage,...} 进 results）：故含 error 项时
    顶层绝不能报 ok=True。全成功→ok/ok；部分失败→partial；全失败→failed。失败 symbol/error 透传供审计。
    （5-lens 复核 HIGH：真钱急停最不容假绿灯——含失败的平仓硬编码 ok:True = 🟡当✅。）
    """
    items = [it for v in (results or {}).values() for it in v if isinstance(it, dict)]
    errors = [it for it in items if it.get("error")]
    if not errors:
        return True, "ok", None
    audit = "failed" if len(errors) == len(items) else "partial"
    return False, audit, "; ".join(str(it.get("error")) for it in errors[:5])


@app.post("/api/risk/kill_switch")
def trigger_kill_switch(request: Request, payload: dict = Body(default_factory=dict),
                        user=Depends(require_user_dependency)) -> dict:
    """急停红按钮：撤单 + 平仓全 symbol。

    D-T025：护栏放在「谁能按按钮」= 人在环 IP + 密码二次鉴权（复用 mainnet_guards）；平仓/撤单本体
    fail-open（风险降低动作永不被策略门挡——门坏也要能救命平仓，与「下新单 fail-closed」相反方向）。
    IP 由服务端从连接派生（_client_ip），二次鉴权由 _verify_second_factor 服务端真比对凭据，均不信 body 自证值。
    """
    source_ip = _client_ip(request)
    if not MAINNET_GUARDS.check_ip(user.user_id, source_ip):
        raise HTTPException(403, f"IP {source_ip} 不在白名单 - kill_switch 需 IP 校验")
    if not _verify_second_factor(user.user_id, payload):
        raise HTTPException(403, "kill_switch 二次鉴权失败：需服务端校验账户密码或 2FA TOTP")
    close = bool(payload.get("close_positions", True))
    results = KILL_SWITCH.trigger(close_positions=close)
    ok, audit_result, err = _killswitch_status(results)   # 含 venue 失败 → 绝不报 ok（不假绿灯）
    MAINNET_GUARDS.log_operation(user.user_id, "kill_switch", source_ip=source_ip,
                                 password_verified=True, result=audit_result, error=err)
    return {"ok": ok, "status": audit_result, "results": results}


# -------- M14 Agent --------

@app.get("/api/research-os/graph/commands")
def research_os_graph_commands(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    """Read-only audit view of Research Graph commands.

    The response is intentionally a summary: it exposes ids, status axes, lineage,
    contract field names, and selected hashes, but never raw prompt text or tool payloads.
    """

    commands = RESEARCH_GRAPH_STORE.commands()
    selected = commands[-limit:]
    return {
        "total": len(commands),
        "limit": limit,
        "commands": [_research_graph_command_summary(command) for command in selected],
    }


@app.get("/api/research-os/graph/projection_index")
def research_os_graph_projection_index(
    limit: int = Query(100, ge=1, le=1000),
    qro_type: str | None = Query(None),
    owner: str | None = Query(None),
    market: str | None = Query(None),
    universe: str | None = Query(None),
    definition_status: str | None = Query(None),
    evidence_status: str | None = Query(None),
    runtime_status: str | None = Query(None),
    lineage_token: str | None = Query(None),
) -> dict[str, Any]:
    """Read-only QRO projection index derived from the Research Graph command log.

    This is a query/read model, not a second truth store. It exposes filterable
    QRO identity, status axes, lineage, refs, and contract hashes; raw contracts
    and tool payloads stay behind the graph command boundary.
    """

    filters = {
        "qro_type": qro_type,
        "owner": owner,
        "market": market,
        "universe": universe,
        "definition_status": definition_status,
        "evidence_status": evidence_status,
        "runtime_status": runtime_status,
        "lineage_token": lineage_token,
    }
    filtered = RESEARCH_GRAPH_STORE.projection_index(**filters)
    selected = filtered[-limit:]
    return {
        "total": len(filtered),
        "limit": limit,
        "filters": {key: value for key, value in filters.items() if value},
        "projections": [record.to_audit_dict() for record in selected],
    }


def _graph_canvas_cat_for_qro(qro_type: str) -> str:
    if qro_type in {"Dataset", "DataSourceAsset", "DatasetVersion", "Observable", "IngestionSkill"}:
        return "data"
    if qro_type == "Factor":
        return "factor"
    if qro_type in {"Model", "Forecast"}:
        return "model"
    if qro_type == "Signal":
        return "signal"
    if qro_type in {"StrategyBook", "PortfolioPolicy"}:
        return "position"
    if qro_type in {"RiskPolicy", "ExecutionPolicy"}:
        return "risk"
    if qro_type in {"BacktestRun", "Experiment", "ValidationDossier"}:
        return "eval"
    if qro_type in {"LLMCallRecord", "LLMProvider", "ModelRoutingPolicy"}:
        return "scope"
    return "research"


def _graph_canvas_state(status_axes: dict[str, str]) -> str:
    governance = status_axes.get("governance")
    evidence = status_axes.get("evidence")
    runtime = status_axes.get("runtime")
    definition = status_axes.get("definition")
    if governance in {"rejected", "revoked"}:
        return "failed"
    if evidence == "insufficient":
        return "warning"
    if runtime in {"paper", "testnet", "live"}:
        return "running"
    if definition == "implemented":
        return "valid"
    if definition == "specified":
        return "validating"
    return "idle"


def _bound_canvas_layout_for_qro(qro_id: str) -> CanvasLayoutRecord | None:
    try:
        qro = RESEARCH_GRAPH_STORE.qro(qro_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"canvas projection QRO not found: {qro_id}") from exc
    layout_ref = str(qro.output_contract.get("canvas_layout_ref") or "").strip()
    if not layout_ref:
        return None
    try:
        layout = RESEARCH_GRAPH_STORE.canvas_layout(layout_ref)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"canvas layout ref is missing: {layout_ref}") from exc
    if layout.qro_id != qro_id:
        raise HTTPException(status_code=422, detail="canvas layout ref does not match QRO")
    return layout


def _graph_canvas_projection(records: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    projected_qro_ids: set[str] = set()
    for idx, record in enumerate(records):
        projected_qro_ids.add(record.qro_id)
        y = 40 + idx * 146
        command_node_id = f"canvas_node:command:{record.command_id}"
        qro_node_id = f"canvas_node:qro:{record.qro_id}"
        command_out = f"out:{record.command_id}"
        qro_in = f"in:{record.qro_id}"
        qro_out = f"out:{record.qro_id}"
        status = record.status_axes
        layout = _bound_canvas_layout_for_qro(record.qro_id)
        qro_x = layout.x if layout else 304
        qro_y = layout.y if layout else y
        qro_w = layout.w if layout else 184
        nodes.append(
            {
                "id": command_node_id,
                "cat": "research",
                "title": "Graph command",
                "x": 40,
                "y": y,
                "w": 184,
                "state": "valid",
                "lines": [
                    f"type {record.source}",
                    f"actor {record.actor_source}",
                    f"cmd {record.command_id[:18]}",
                ],
                "ins": [],
                "outs": [{"id": command_out, "name": "upsert_qro"}],
                "badge": "Research Graph",
                "locked": True,
            }
        )
        nodes.append(
            {
                "id": qro_node_id,
                "cat": _graph_canvas_cat_for_qro(record.qro_type),
                "title": record.qro_type,
                "x": qro_x,
                "y": qro_y,
                "w": qro_w,
                "state": _graph_canvas_state(status),
                "lines": [
                    f"qro {record.qro_id[:18]}",
                    f"{record.market or '-'} / {record.universe or '-'}",
                    f"evidence {status.get('evidence', '-')}",
                    f"keys {','.join(record.input_contract_keys[:3]) or '-'}",
                ],
                "ins": [{"id": qro_in, "name": "graph"}],
                "outs": [{"id": qro_out, "name": "qro"}],
                "badge": record.owner,
                "locked": True,
            }
        )
        edges.append(
            {
                "id": f"canvas_edge:{record.command_id}:{record.qro_id}",
                "from": {"node": command_node_id, "port": command_out},
                "to": {"node": qro_node_id, "port": qro_in},
                "compat": "ok",
            }
        )
    for edge in RESEARCH_GRAPH_STORE.graph_edges():
        if edge.from_qro_id not in projected_qro_ids or edge.to_qro_id not in projected_qro_ids:
            continue
        edges.append(
            {
                "id": f"canvas_edge:graph:{edge.edge_ref}",
                "from": {
                    "node": f"canvas_node:qro:{edge.from_qro_id}",
                    "port": f"out:{edge.from_qro_id}",
                },
                "to": {
                    "node": f"canvas_node:qro:{edge.to_qro_id}",
                    "port": f"in:{edge.to_qro_id}",
                },
                "compat": "ok",
            }
        )
    return nodes, edges


@app.get("/api/research-os/graph/canvas_projection")
def research_os_graph_canvas_projection(
    limit: int = Query(100, ge=1, le=500),
    qro_type: str | None = Query(None),
    owner: str | None = Query(None),
    market: str | None = Query(None),
    universe: str | None = Query(None),
    definition_status: str | None = Query(None),
    evidence_status: str | None = Query(None),
    runtime_status: str | None = Query(None),
    lineage_token: str | None = Query(None),
) -> dict[str, Any]:
    """Read-only GraphCanvas projection from the Research Graph QRO index."""

    filters = {
        "qro_type": qro_type,
        "owner": owner,
        "market": market,
        "universe": universe,
        "definition_status": definition_status,
        "evidence_status": evidence_status,
        "runtime_status": runtime_status,
        "lineage_token": lineage_token,
    }
    filtered = RESEARCH_GRAPH_STORE.projection_index(**filters)
    selected = filtered[-limit:]
    nodes, edges = _graph_canvas_projection(selected)
    return {
        "total": len(filtered),
        "limit": limit,
        "filters": {key: value for key, value in filters.items() if value},
        "read_only": True,
        "source_projection_refs": [record.projection_ref for record in selected],
        "nodes": nodes,
        "edges": edges,
    }


_CANVAS_MUTATION_FORBIDDEN_VALUE_FIELDS = {"value", "raw_value", "raw_payload", "payload"}


def _canvas_payload_text(payload: dict[str, Any], key: str, *, required: bool = True) -> str:
    value = str(payload.get(key) or "").strip()
    if required and not value:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value


def _canvas_payload_float(payload: dict[str, Any], key: str) -> float:
    if key not in payload:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    try:
        return float(payload[key])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} must be numeric") from exc


def _canvas_mutation_record_from_payload(
    payload: dict[str, Any],
    *,
    actor_override: str | None = None,
) -> CanvasMutationRecord:
    forbidden = sorted(key for key in _CANVAS_MUTATION_FORBIDDEN_VALUE_FIELDS if key in payload)
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"canvas mutation cannot include raw value fields: {','.join(forbidden)}",
        )
    value_ref = _canvas_payload_text(payload, "value_ref", required=False) or None
    value_hash = _canvas_payload_text(payload, "value_hash", required=False) or None
    if not value_ref and not value_hash:
        raise HTTPException(status_code=422, detail="value_ref or value_hash is required")
    return CanvasMutationRecord(
        command_ref=_canvas_payload_text(payload, "command_ref"),
        source_desk=_canvas_payload_text(payload, "source_desk"),
        actor_source=_canvas_payload_text(payload, "actor_source"),
        actor=actor_override or _canvas_payload_text(payload, "actor"),
        target_asset_type=_canvas_payload_text(payload, "target_asset_type"),
        target_ref=_canvas_payload_text(payload, "target_ref"),
        field_path=_canvas_payload_text(payload, "field_path"),
        operation=_canvas_payload_text(payload, "operation"),
        canonical_command_ref=_canvas_payload_text(payload, "canonical_command_ref", required=False) or None,
        audit_ref=_canvas_payload_text(payload, "audit_ref", required=False) or None,
        value_ref=value_ref,
        value_hash=value_hash,
        evidence_refs=_payload_tuple(payload.get("evidence_refs")),
    )


def _graph_edge_record_from_payload(
    payload: dict[str, Any],
    *,
    actor: str,
) -> ResearchGraphEdgeRecord:
    forbidden = sorted(key for key in _CANVAS_MUTATION_FORBIDDEN_VALUE_FIELDS if key in payload)
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"graph edge command cannot include raw value fields: {','.join(forbidden)}",
        )
    return ResearchGraphEdgeRecord(
        command_ref=_canvas_payload_text(payload, "command_ref"),
        from_qro_id=_canvas_payload_text(payload, "from_qro_id"),
        to_qro_id=_canvas_payload_text(payload, "to_qro_id"),
        relation_type=_canvas_payload_text(payload, "relation_type"),
        source_desk=_canvas_payload_text(payload, "source_desk"),
        actor_source=_canvas_payload_text(payload, "actor_source"),
        actor=actor,
        canonical_command_ref=_canvas_payload_text(payload, "canonical_command_ref"),
        audit_ref=_canvas_payload_text(payload, "audit_ref"),
        evidence_refs=_payload_tuple(payload.get("evidence_refs")),
        edge_ref=_canvas_payload_text(payload, "edge_ref", required=False),
    )


def _graph_edge_deletion_record_from_payload(
    payload: dict[str, Any],
    *,
    actor: str,
) -> ResearchGraphEdgeDeletionRecord:
    forbidden = sorted(key for key in _CANVAS_MUTATION_FORBIDDEN_VALUE_FIELDS if key in payload)
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"graph edge deletion cannot include raw value fields: {','.join(forbidden)}",
        )
    return ResearchGraphEdgeDeletionRecord(
        command_ref=_canvas_payload_text(payload, "command_ref"),
        edge_ref=_canvas_payload_text(payload, "edge_ref"),
        source_desk=_canvas_payload_text(payload, "source_desk"),
        actor_source=_canvas_payload_text(payload, "actor_source"),
        actor=actor,
        canonical_command_ref=_canvas_payload_text(payload, "canonical_command_ref"),
        audit_ref=_canvas_payload_text(payload, "audit_ref"),
        evidence_refs=_payload_tuple(payload.get("evidence_refs")),
        deletion_ref=_canvas_payload_text(payload, "deletion_ref", required=False),
    )


def _qro_tombstone_record_from_payload(
    payload: dict[str, Any],
    *,
    actor: str,
) -> QROTombstoneRecord:
    forbidden = sorted(key for key in _CANVAS_MUTATION_FORBIDDEN_VALUE_FIELDS if key in payload)
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"QRO tombstone cannot include raw value fields: {','.join(forbidden)}",
        )
    return QROTombstoneRecord(
        command_ref=_canvas_payload_text(payload, "command_ref"),
        qro_id=_canvas_payload_text(payload, "qro_id"),
        source_desk=_canvas_payload_text(payload, "source_desk"),
        actor_source=_canvas_payload_text(payload, "actor_source"),
        actor=actor,
        canonical_command_ref=_canvas_payload_text(payload, "canonical_command_ref"),
        audit_ref=_canvas_payload_text(payload, "audit_ref"),
        evidence_refs=_payload_tuple(payload.get("evidence_refs")),
        tombstone_ref=_canvas_payload_text(payload, "tombstone_ref", required=False),
    )


_GRAPH_PATCH_FORBIDDEN_VALUE_FIELDS = _CANVAS_MUTATION_FORBIDDEN_VALUE_FIELDS | {
    "diff",
    "edge",
    "generated_patch",
    "node",
    "ops",
    "params",
    "patch",
    "proposal",
}


def _graph_patch_application_record_from_payload(
    payload: dict[str, Any],
    *,
    actor: str,
) -> GraphPatchApplicationRecord:
    forbidden = sorted(key for key in _GRAPH_PATCH_FORBIDDEN_VALUE_FIELDS if key in payload)
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"graph patch application cannot include raw patch fields: {','.join(forbidden)}",
        )
    return GraphPatchApplicationRecord(
        command_ref=_canvas_payload_text(payload, "command_ref"),
        target_qro_id=_canvas_payload_text(payload, "target_qro_id"),
        patch_kind=_canvas_payload_text(payload, "patch_kind"),
        patch_ref=_canvas_payload_text(payload, "patch_ref"),
        patch_hash=_canvas_payload_text(payload, "patch_hash"),
        source_desk=_canvas_payload_text(payload, "source_desk"),
        actor_source=_canvas_payload_text(payload, "actor_source"),
        actor=actor,
        canonical_command_ref=_canvas_payload_text(payload, "canonical_command_ref"),
        audit_ref=_canvas_payload_text(payload, "audit_ref"),
        evidence_refs=_payload_tuple(payload.get("evidence_refs")),
        application_ref=_canvas_payload_text(payload, "application_ref", required=False),
    )


_CANVAS_PARAMETER_FORBIDDEN_FIELDS = _CANVAS_MUTATION_FORBIDDEN_VALUE_FIELDS | {"node", "params", "raw_node"}


def _canvas_parameter_value_record_from_payload(
    payload: dict[str, Any],
    *,
    actor: str,
) -> CanvasParameterValueRecord:
    forbidden = sorted(key for key in _CANVAS_PARAMETER_FORBIDDEN_FIELDS if key in payload)
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"canvas parameter value cannot include raw wrapper fields: {','.join(forbidden)}",
        )
    param_key = _canvas_payload_text(payload, "param_key")
    param_value = _canvas_payload_text(payload, "param_value")
    if contains_plaintext_secret({param_key: param_value}):
        raise HTTPException(status_code=422, detail="canvas parameter value cannot contain plaintext credential material")
    return CanvasParameterValueRecord(
        command_ref=_canvas_payload_text(payload, "command_ref"),
        target_qro_id=_canvas_payload_text(payload, "target_qro_id"),
        target_asset_type=_canvas_payload_text(payload, "target_asset_type"),
        param_key=param_key,
        param_value=param_value,
        source_desk=_canvas_payload_text(payload, "source_desk"),
        actor_source=_canvas_payload_text(payload, "actor_source"),
        actor=actor,
        canonical_command_ref=_canvas_payload_text(payload, "canonical_command_ref"),
        audit_ref=_canvas_payload_text(payload, "audit_ref"),
        evidence_refs=_payload_tuple(payload.get("evidence_refs")),
        value_hash=_canvas_payload_text(payload, "value_hash", required=False),
        parameter_ref=_canvas_payload_text(payload, "parameter_ref", required=False),
    )


def _record_canvas_goal_entrypoint_coverage(
    *,
    qro_id: str,
    qro_command_id: str,
    actor: str,
    actor_source: ActorSource | str,
    source_desk: str,
    entrypoint_ref: str,
    operation_ref: str,
    validation_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    tool_record_refs: Iterable[str] = (),
    node_refs: Iterable[str] = (),
    canonical_command_refs: Iterable[str] = (),
) -> dict[str, str]:
    source_desk_ref = str(source_desk or "canvas").replace(":", ".")
    entrypoint_key = entrypoint_ref.replace(":", ".")
    operation_hash = content_hash(
        {
            "entrypoint_ref": entrypoint_ref,
            "operation_ref": operation_ref,
            "qro_id": qro_id,
            "qro_command_id": qro_command_id,
        }
    )
    actor_source_text = actor_source.value if hasattr(actor_source, "value") else str(actor_source)
    return _compile_entrypoint_qro(
        qro_id=qro_id,
        graph_command_id=qro_command_id,
        actor=actor,
        actor_source=actor_source_text,
        entry_source=EntrySource.CANVAS.value,
        entrypoint_ref=entrypoint_ref,
        pass_name=f"{entrypoint_key}_qro_to_canvas_projection_ir",
        validation_refs=_compiler_unique_refs(
            validation_refs,
            f"validation:{entrypoint_ref}:refs_only",
            f"validation:{entrypoint_ref}:qro_graph_refs_present",
            f"validation:{entrypoint_ref}:raw_payload_excluded:{operation_hash}",
        ),
        evidence_refs=_compiler_unique_refs(evidence_refs, f"evidence:{entrypoint_ref}:{operation_hash}"),
        environment_lock_ref=f"env:{entrypoint_key}:{source_desk_ref}:v1",
        permission_ref=f"{entrypoint_ref}:{source_desk_ref}:{actor_source_text}",
        deterministic_run_plan_ref=f"runplan:{entrypoint_ref}:{operation_hash}",
        rollback_ref=f"rollback:{entrypoint_ref}:{operation_hash}:manual_review",
        tool_record_refs=_compiler_unique_refs(tool_record_refs, f"canvas_operation:{operation_ref}"),
        node_refs=_compiler_unique_refs(node_refs, f"qro:{qro_id}", f"entrypoint:{entrypoint_ref}"),
        canonical_command_refs=_compiler_unique_refs(
            canonical_command_refs,
            f"research_graph_command:{qro_command_id}",
            f"entrypoint:{entrypoint_ref}",
            f"canvas_operation:{operation_ref}",
        ),
    )


def _graph_edge_qros(edge_ref: str) -> tuple[QRORecord, QRORecord]:
    matches = [edge for edge in RESEARCH_GRAPH_STORE.graph_edges(include_deleted=True) if edge.edge_ref == edge_ref]
    if not matches:
        raise ResearchGraphError(f"graph edge not found: {edge_ref}")
    edge = matches[-1]
    return RESEARCH_GRAPH_STORE.qro(edge.from_qro_id), RESEARCH_GRAPH_STORE.qro(edge.to_qro_id)


def _qro_runtime(qro: QRORecord) -> str:
    return str(qro.runtime_status.value if hasattr(qro.runtime_status, "value") else qro.runtime_status)


def _reject_live_graph_edge_qros(from_qro: QRORecord, to_qro: QRORecord) -> None:
    if RuntimeStatus.LIVE.value in {_qro_runtime(from_qro), _qro_runtime(to_qro)}:
        raise ResearchGraphError("graph edge cannot edit live QRO topology; fork a draft/offline asset first")


def _reject_live_qro_tombstone(qro: QRORecord) -> None:
    if _qro_runtime(qro) == RuntimeStatus.LIVE.value:
        raise ResearchGraphError("cannot tombstone live QRO; fork a draft/offline asset first")


def _reject_live_graph_patch_target(qro: QRORecord) -> None:
    if _qro_runtime(qro) == RuntimeStatus.LIVE.value:
        raise ResearchGraphError("cannot apply graph patch to live QRO; fork a draft/offline asset first")


@app.post("/api/research-os/graph/edges")
def research_os_graph_edge(
    payload: dict[str, Any],
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Create a first-class QRO-to-QRO Research Graph edge from a Canvas connect."""

    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "unknown")
    try:
        record = _graph_edge_record_from_payload(payload, actor=actor)
        from_qro = RESEARCH_GRAPH_STORE.qro(record.from_qro_id)
        to_qro = RESEARCH_GRAPH_STORE.qro(record.to_qro_id)
        _reject_live_graph_edge_qros(from_qro, to_qro)
        command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_graph_edge",
            actor_source=record.actor_source,
            actor=actor,
            payload={"edge": record},
            evidence_refs=record.evidence_refs,
            tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
        )
        command_id = RESEARCH_GRAPH_STORE.apply(command)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"graph edge QRO not found: {exc.args[0]}") from exc
    except (ResearchGraphError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "command_type": "record_graph_edge",
        "graph_edge_command_id": command_id,
        "edge_ref": record.edge_ref,
        "from_qro_id": record.from_qro_id,
        "to_qro_id": record.to_qro_id,
        "relation_type": record.relation_type,
        "projection_edge_id": f"canvas_edge:graph:{record.edge_ref}",
        "recorded_by": actor,
    }


@app.post("/api/research-os/graph/edge_deletions")
def research_os_graph_edge_deletion(
    payload: dict[str, Any],
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Tombstone an active QRO-to-QRO Research Graph edge from a Canvas delete."""

    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "unknown")
    try:
        record = _graph_edge_deletion_record_from_payload(payload, actor=actor)
        from_qro, to_qro = _graph_edge_qros(record.edge_ref)
        _reject_live_graph_edge_qros(from_qro, to_qro)
        command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="delete_graph_edge",
            actor_source=record.actor_source,
            actor=actor,
            payload={"edge_deletion": record},
            evidence_refs=record.evidence_refs,
            tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
        )
        command_id = RESEARCH_GRAPH_STORE.apply(command)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"graph edge QRO not found: {exc.args[0]}") from exc
    except (ResearchGraphError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "command_type": "delete_graph_edge",
        "graph_edge_deletion_command_id": command_id,
        "edge_ref": record.edge_ref,
        "deletion_ref": record.deletion_ref,
        "projection_edge_id": f"canvas_edge:graph:{record.edge_ref}",
        "recorded_by": actor,
    }


@app.post("/api/research-os/graph/qro_tombstones")
def research_os_graph_qro_tombstone(
    payload: dict[str, Any],
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Tombstone an active QRO node from a Canvas delete without erasing history."""

    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "unknown")
    try:
        record = _qro_tombstone_record_from_payload(payload, actor=actor)
        qro = RESEARCH_GRAPH_STORE.qro(record.qro_id)
        _reject_live_qro_tombstone(qro)
        command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="tombstone_qro",
            actor_source=record.actor_source,
            actor=actor,
            payload={"qro_tombstone": record},
            evidence_refs=record.evidence_refs,
            tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
        )
        command_id = RESEARCH_GRAPH_STORE.apply(command)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"QRO not found: {exc.args[0]}") from exc
    except (ResearchGraphError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "command_type": "tombstone_qro",
        "qro_tombstone_command_id": command_id,
        "qro_id": record.qro_id,
        "tombstone_ref": record.tombstone_ref,
        "projection_node_id": f"canvas_node:qro:{record.qro_id}",
        "recorded_by": actor,
    }


@app.post("/api/research-os/graph/patch_applications")
def research_os_graph_patch_application(
    payload: dict[str, Any],
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Apply a governed Ghost/Auto patch by adding a patch QRO and Graph edge."""

    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "unknown")
    try:
        record = _graph_patch_application_record_from_payload(payload, actor=actor)
        target_qro = RESEARCH_GRAPH_STORE.qro(record.target_qro_id)
        _reject_live_graph_patch_target(target_qro)
        patch_command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="apply_graph_patch",
            actor_source=record.actor_source,
            actor=actor,
            payload={"patch_application": record},
            evidence_refs=record.evidence_refs,
            tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
        )
        patch_command_id = RESEARCH_GRAPH_STORE.apply(patch_command)
        patch_qro = QRORecord(
            qro_type="GraphPatchApplication",
            owner=target_qro.owner,
            actor=record.actor_source,
            input_contract={
                "target_qro_ref": record.target_qro_id,
                "patch_kind": record.patch_kind,
                "patch_ref": record.patch_ref,
                "patch_hash": record.patch_hash,
            },
            output_contract={
                "patch_application_ref": record.application_ref,
                "application_audit_ref": record.audit_ref,
                "canonical_command_ref": record.canonical_command_ref,
            },
            market=target_qro.market,
            universe=target_qro.universe,
            horizon=target_qro.horizon,
            frequency=target_qro.frequency,
            lineage=(target_qro.qro_id, "graph_patch_application", record.command_ref),
            implementation_hash=f"graph_patch_application:{record.patch_hash}",
            assumptions=("patch application metadata was recorded before projection",),
            known_limits=("patch operation body is stored by reference/hash, not copied into the QRO",),
            failure_modes=("missing patch artifact prevents operation-level replay",),
            validation_plan=("verify patch command, patch QRO, and graph edge replay",),
            definition_status=DefinitionStatus.IMPLEMENTED,
            evidence_status=EvidenceStatus.EXPLORATORY,
            runtime_status=RuntimeStatus.OFFLINE,
            evidence_refs=record.evidence_refs,
            permission=f"canvas.patch:{record.source_desk}",
            allowed_environment=RuntimeStatus.OFFLINE,
        )
        qro_command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="upsert_qro",
            actor_source=record.actor_source,
            actor=actor,
            payload={"qro": patch_qro},
            evidence_refs=patch_qro.evidence_refs,
            tool_record_refs=(patch_command_id, *_payload_tuple(payload.get("tool_record_refs"))),
        )
        qro_command_id = RESEARCH_GRAPH_STORE.apply(qro_command)
        edge = ResearchGraphEdgeRecord(
            command_ref=f"{record.command_ref}:edge",
            from_qro_id=record.target_qro_id,
            to_qro_id=patch_qro.qro_id,
            relation_type="graph_patch_application",
            source_desk=record.source_desk,
            actor_source=record.actor_source,
            actor=actor,
            canonical_command_ref=f"{record.canonical_command_ref}:edge",
            audit_ref=f"{record.audit_ref}:edge",
            evidence_refs=record.evidence_refs,
        )
        edge_command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_graph_edge",
            actor_source=record.actor_source,
            actor=actor,
            payload={"edge": edge},
            evidence_refs=edge.evidence_refs,
            tool_record_refs=(patch_command_id, qro_command_id, *_payload_tuple(payload.get("tool_record_refs"))),
        )
        edge_command_id = RESEARCH_GRAPH_STORE.apply(edge_command)
        compiler_refs = _record_canvas_goal_entrypoint_coverage(
            qro_id=patch_qro.qro_id,
            qro_command_id=qro_command_id,
            actor=actor,
            actor_source=record.actor_source,
            source_desk=record.source_desk,
            entrypoint_ref="canvas:graph_patch_application",
            operation_ref=record.application_ref,
            validation_refs=(f"validation:canvas.graph_patch_application:{record.application_ref}",),
            evidence_refs=_compiler_unique_refs(record.evidence_refs, record.audit_ref, record.patch_ref),
            tool_record_refs=(patch_command_id, edge_command_id, *_payload_tuple(payload.get("tool_record_refs"))),
            node_refs=(f"qro:{patch_qro.qro_id}", f"qro_type:{_enum_text(patch_qro.qro_type)}", f"target_qro:{record.target_qro_id}"),
            canonical_command_refs=(
                f"research_graph_command:{patch_command_id}",
                f"research_graph_command:{edge_command_id}",
                record.canonical_command_ref,
                record.audit_ref,
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"graph patch target QRO not found: {exc.args[0]}") from exc
    except (ResearchGraphError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "command_type": "apply_graph_patch",
        "patch_application_command_id": patch_command_id,
        "patch_qro_command_id": qro_command_id,
        "graph_edge_command_id": edge_command_id,
        "application_ref": record.application_ref,
        "patch_qro_id": patch_qro.qro_id,
        "target_qro_id": record.target_qro_id,
        "patch_kind": record.patch_kind,
        "projection_node_id": f"canvas_node:qro:{patch_qro.qro_id}",
        "projection_edge_id": f"canvas_edge:graph:{edge.edge_ref}",
        "recorded_by": actor,
        **compiler_refs,
    }


@app.post("/api/research-os/graph/canvas_parameter_values")
def research_os_graph_canvas_parameter_value(
    payload: dict[str, Any],
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Save an explicit Canvas parameter value as an append-only Research Graph record."""

    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "unknown")
    try:
        record = _canvas_parameter_value_record_from_payload(payload, actor=actor)
        target_qro = RESEARCH_GRAPH_STORE.qro(record.target_qro_id)
        parameter_command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="set_canvas_parameter",
            actor_source=record.actor_source,
            actor=actor,
            payload={"parameter_value": record},
            evidence_refs=record.evidence_refs,
            tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
        )
        parameter_command_id = RESEARCH_GRAPH_STORE.apply(parameter_command)
        output_contract = dict(target_qro.output_contract)
        output_contract.update(
            {
                "canvas_param_value_ref": record.parameter_ref,
                "canvas_param_value_hash": record.value_hash,
                "canvas_param_key": record.param_key,
            }
        )
        evidence_refs = tuple(
            ref
            for ref in dict.fromkeys(
                (
                    *target_qro.evidence_refs,
                    *record.evidence_refs,
                    record.audit_ref,
                    record.canonical_command_ref,
                    record.parameter_ref,
                )
            )
            if ref
        )
        updated_qro = replace(
            target_qro,
            output_contract=output_contract,
            version=target_qro.version + 1,
            implementation_hash="canvas_parameter_value:"
            + content_hash(
                {
                    "qro_id": target_qro.qro_id,
                    "previous_version": target_qro.version,
                    "parameter_ref": record.parameter_ref,
                    "value_hash": record.value_hash,
                }
            ),
            lineage=tuple(dict.fromkeys((*target_qro.lineage, "canvas_parameter_value", record.command_ref))),
            evidence_refs=evidence_refs,
            qro_id=target_qro.qro_id,
        )
        qro_command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="upsert_qro",
            actor_source=record.actor_source,
            actor=actor,
            payload={"qro": updated_qro},
            evidence_refs=updated_qro.evidence_refs,
            tool_record_refs=(parameter_command_id, *_payload_tuple(payload.get("tool_record_refs"))),
        )
        qro_command_id = RESEARCH_GRAPH_STORE.apply(qro_command)
        compiler_refs = _record_canvas_goal_entrypoint_coverage(
            qro_id=updated_qro.qro_id,
            qro_command_id=qro_command_id,
            actor=actor,
            actor_source=record.actor_source,
            source_desk=record.source_desk,
            entrypoint_ref="canvas:parameter_value",
            operation_ref=record.parameter_ref,
            validation_refs=(f"validation:canvas.parameter_value:{record.parameter_ref}",),
            evidence_refs=_compiler_unique_refs(record.evidence_refs, record.audit_ref, record.parameter_ref),
            tool_record_refs=(parameter_command_id, *_payload_tuple(payload.get("tool_record_refs"))),
            node_refs=(f"qro:{updated_qro.qro_id}", f"qro_type:{_enum_text(updated_qro.qro_type)}", f"canvas_parameter:{record.parameter_ref}"),
            canonical_command_refs=(
                f"research_graph_command:{parameter_command_id}",
                record.canonical_command_ref,
                record.audit_ref,
            ),
        )
        projection = [record for record in RESEARCH_GRAPH_STORE.projection_index() if record.qro_id == updated_qro.qro_id][-1]
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"canvas parameter target QRO not found: {exc.args[0]}") from exc
    except (ResearchGraphError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "command_type": "set_canvas_parameter",
        "parameter_command_id": parameter_command_id,
        "qro_command_id": qro_command_id,
        "qro_id": updated_qro.qro_id,
        "qro_version": updated_qro.version,
        "projection_ref": projection.projection_ref,
        "param_key": record.param_key,
        "parameter_ref": record.parameter_ref,
        "value_hash": record.value_hash,
        "updated_field_path": "output_contract.canvas_param_value_ref",
        "recorded_by": actor,
        **compiler_refs,
    }


@app.post("/api/research-os/graph/canvas_mutations")
def research_os_graph_canvas_mutation(payload: dict[str, Any]) -> dict[str, Any]:
    """Record a governed Canvas mutation as a canonical Research Graph command.

    This endpoint does not directly rewrite the QRO projection index. It records
    the mutation audit only after the caller supplies a canonical command ref,
    audit lineage, and a non-raw value reference/hash.
    """

    evidence_refs = _payload_tuple(payload.get("evidence_refs"))
    record = _canvas_mutation_record_from_payload(payload)
    decision = validate_canvas_mutation(record)
    if not decision.accepted:
        raise HTTPException(
            status_code=422,
            detail={
                "accepted": False,
                "violations": [
                    {
                        "code": violation.code,
                        "field": violation.field,
                        "message": violation.message,
                    }
                    for violation in decision.violations
                ],
            },
        )
    command = ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="record_canvas_mutation",
        actor_source=record.actor_source,
        actor=record.actor,
        payload={"mutation": record},
        evidence_refs=evidence_refs,
        tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    return {
        "accepted": True,
        "research_graph_command_id": command_id,
        "command_type": "record_canvas_mutation",
        "canonical_command_ref": record.canonical_command_ref,
        "audit_ref": record.audit_ref,
        "command_ref": record.command_ref,
    }


@app.post("/api/research-os/graph/canvas_layouts")
def research_os_graph_canvas_layout(
    payload: dict[str, Any],
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Record exact QRO-node layout via the Research Graph command log."""

    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "unknown")
    target_ref = _canvas_payload_text(payload, "target_ref")
    target_asset_type = _canvas_payload_text(payload, "target_asset_type")
    try:
        current = RESEARCH_GRAPH_STORE.qro(target_ref)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"canvas layout target QRO not found: {target_ref}") from exc
    current_type = str(current.qro_type.value if hasattr(current.qro_type, "value") else current.qro_type)
    current_runtime = str(current.runtime_status.value if hasattr(current.runtime_status, "value") else current.runtime_status)
    if current_type != target_asset_type:
        raise HTTPException(
            status_code=422,
            detail=f"canvas layout target_asset_type mismatch: expected {current_type}, got {target_asset_type}",
        )
    if current_runtime == RuntimeStatus.LIVE.value:
        raise HTTPException(status_code=422, detail="canvas layout cannot edit live QRO; fork a draft/offline asset first")

    command_ref = _canvas_payload_text(payload, "command_ref")
    canonical_command_ref = _canvas_payload_text(payload, "canonical_command_ref")
    audit_ref = _canvas_payload_text(payload, "audit_ref")
    try:
        layout = make_canvas_layout_record(
            qro_id=target_ref,
            qro_type=target_asset_type,
            node_id=_canvas_payload_text(payload, "node_id"),
            x=_canvas_payload_float(payload, "x"),
            y=_canvas_payload_float(payload, "y"),
            w=_canvas_payload_float(payload, "w"),
            source_desk=_canvas_payload_text(payload, "source_desk"),
            actor_source=_canvas_payload_text(payload, "actor_source"),
            actor=actor,
            mutation_command_ref=command_ref,
            canonical_command_ref=canonical_command_ref,
            audit_ref=audit_ref,
            evidence_refs=_payload_tuple(payload.get("evidence_refs")),
        )
        layout_command = ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_canvas_layout",
            actor_source=layout.actor_source,
            actor=actor,
            payload={"layout": layout},
            evidence_refs=(*layout.evidence_refs, layout.layout_ref),
            tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
        )
        layout_command_id = RESEARCH_GRAPH_STORE.apply(layout_command)
        mutation = _canvas_mutation_record_from_payload(
            {
                "command_ref": command_ref,
                "source_desk": layout.source_desk,
                "actor_source": layout.actor_source,
                "actor": actor,
                "target_asset_type": target_asset_type,
                "target_ref": target_ref,
                "field_path": "output_contract.canvas_layout_ref",
                "operation": "set_ref",
                "canonical_command_ref": canonical_command_ref,
                "audit_ref": audit_ref,
                "value_ref": layout.layout_ref,
                "value_hash": layout.layout_hash,
                "evidence_refs": [*layout.evidence_refs, layout.layout_ref],
            },
            actor_override=actor,
        )
        result = execute_canvas_asset_mutation(
            RESEARCH_GRAPH_STORE,
            mutation,
            tool_record_refs=(layout_command_id, layout.layout_ref, *_payload_tuple(payload.get("tool_record_refs"))),
        )
        compiler_refs = _record_canvas_goal_entrypoint_coverage(
            qro_id=result.qro_id,
            qro_command_id=result.qro_command_id,
            actor=actor,
            actor_source=layout.actor_source,
            source_desk=layout.source_desk,
            entrypoint_ref="canvas:layout",
            operation_ref=layout.layout_ref,
            validation_refs=(f"validation:canvas.layout:{layout.layout_ref}",),
            evidence_refs=_compiler_unique_refs(layout.evidence_refs, layout.audit_ref, layout.layout_ref),
            tool_record_refs=(layout_command_id, result.mutation_command_id, *_payload_tuple(payload.get("tool_record_refs"))),
            node_refs=(f"qro:{result.qro_id}", f"canvas_layout:{layout.layout_ref}"),
            canonical_command_refs=(
                f"research_graph_command:{layout_command_id}",
                f"research_graph_command:{result.mutation_command_id}",
                layout.canonical_command_ref,
                layout.audit_ref,
            ),
        )
    except (ResearchGraphError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "command_type": "record_canvas_layout",
        "layout_command_id": layout_command_id,
        "layout_ref": layout.layout_ref,
        "layout_hash": layout.layout_hash,
        "mutation_command_id": result.mutation_command_id,
        "qro_command_id": result.qro_command_id,
        "qro_id": result.qro_id,
        "qro_version": result.qro_version,
        "projection_ref": result.projection_ref,
        "updated_field_path": result.updated_field_path,
        "recorded_by": actor,
        **compiler_refs,
    }


@app.post("/api/research-os/graph/canvas_asset_mutations")
def research_os_graph_canvas_asset_mutation(
    payload: dict[str, Any],
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Execute a Canvas edit against a real QRO asset version.

    The old ``canvas_mutations`` endpoint remains audit-only. This endpoint is
    the canonical asset mutation path: validate desk scope, record the mutation,
    then upsert a new QRO version containing only reference/hash edits.
    """

    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "unknown")
    try:
        record = _canvas_mutation_record_from_payload(payload, actor_override=actor)
        result = execute_canvas_asset_mutation(
            RESEARCH_GRAPH_STORE,
            record,
            tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
        )
        compiler_refs = _record_canvas_goal_entrypoint_coverage(
            qro_id=result.qro_id,
            qro_command_id=result.qro_command_id,
            actor=actor,
            actor_source=record.actor_source,
            source_desk=record.source_desk,
            entrypoint_ref="canvas:asset_mutation",
            operation_ref=record.command_ref,
            validation_refs=(f"validation:canvas.asset_mutation:{record.command_ref}",),
            evidence_refs=_compiler_unique_refs(
                record.evidence_refs,
                record.audit_ref,
                record.canonical_command_ref,
                record.value_ref,
                record.value_hash,
            ),
            tool_record_refs=_payload_tuple(payload.get("tool_record_refs")),
            node_refs=(f"qro:{result.qro_id}", f"canvas_mutation:{record.command_ref}"),
            canonical_command_refs=(record.canonical_command_ref, record.audit_ref),
        )
    except ResearchGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "accepted": True,
        "command_type": "execute_canvas_asset_mutation",
        "mutation_command_id": result.mutation_command_id,
        "qro_command_id": result.qro_command_id,
        "qro_id": result.qro_id,
        "qro_version": result.qro_version,
        "projection_ref": result.projection_ref,
        "updated_field_path": result.updated_field_path,
        "recorded_by": actor,
        **compiler_refs,
    }


def _rag_permission_from_payload(payload: dict[str, Any], username: str) -> RAGPermission:
    raw = payload.get("permission") or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="permission must be an object")
    allowed_users = raw.get("allowed_users")
    if allowed_users in (None, [], ()):
        allowed_users = [username]
    allowed_users_set = {str(v) for v in allowed_users}
    if username not in allowed_users_set:
        raise HTTPException(status_code=403, detail="RAG document permission must include current user")
    return RAGPermission(
        allowed_users=tuple(allowed_users_set),
        allowed_desks=tuple(str(v) for v in raw.get("allowed_desks") or ()),
        allowed_assets=tuple(str(v) for v in raw.get("allowed_assets") or ()),
        permission_tags=tuple(str(v) for v in raw.get("permission_tags") or ()),
    )


def _rag_document_from_payload(payload: dict[str, Any], username: str) -> AssetRAGDocument:
    try:
        return AssetRAGDocument(
            source_id=str(payload.get("source_id") or ""),
            version=str(payload.get("version") or ""),
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or ""),
            projection=str(payload.get("projection") or ""),
            asset_ref=str(payload.get("asset_ref") or ""),
            permission=_rag_permission_from_payload(payload, username),
            applicability=str(payload.get("applicability") or ""),
            source_kind=str(payload.get("source_kind") or ""),
            timestamp=str(payload.get("timestamp") or _dt.datetime.now(_dt.UTC).isoformat()),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            evidence_label=str(payload.get("evidence_label") or "candidate_context"),
            methodology_path=payload.get("methodology_path"),
            document_id=str(payload.get("document_id") or ""),
        )
    except AssetRAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _rag_hit_to_dict(hit) -> dict[str, Any]:
    return {
        "source_id": hit.source_id,
        "version": hit.version,
        "timestamp": hit.timestamp,
        "permission": hit.permission,
        "applicability": hit.applicability,
        "projection": hit.projection,
        "asset_ref": hit.asset_ref,
        "title": hit.title,
        "snippet": hit.snippet,
        "score": hit.score,
        "evidence_label": hit.evidence_label,
        "context_role": hit.context_role,
    }


def _settings_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _settings_raw_payload(payload: dict[str, Any], key: str) -> dict[str, Any]:
    raw = payload.get(key) if isinstance(payload.get(key), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail=f"{key} payload must be an object")
    if contains_plaintext_secret(raw):
        raise HTTPException(status_code=422, detail="settings payload cannot contain plaintext credential material")
    return raw


_SECRET_VALUE_FIELDS = {"secret_value", "api_key", "api_secret", "value", "token", "secret"}


def _settings_keystore_ref_for_secret_ref(secret_ref: str) -> str:
    normalized = str(secret_ref or "").strip().lower()
    parts = [part for part in normalized.split(":") if part]
    if len(parts) >= 3 and parts[0] in {"secretref", "secret_ref", "secref"}:
        if parts[1] == "llm" and parts[2] in _LLM_PROVIDER_VALUES:
            return f"llm_{parts[2]}"
        if parts[1] == "binance" and parts[2] in {"testnet", "mainnet"}:
            return f"binance_{parts[2]}"
    if len(parts) >= 2 and parts[0] in {"secretref", "secret_ref", "secref", "tokenref", "token_ref"}:
        if parts[1] == "tushare":
            return "tushare"
    fragment = re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")
    return f"settings_{fragment or 'secret'}"


def _settings_keystore_refs(record: SecretRefRecord) -> tuple[str, ...]:
    refs: list[str] = []
    for item in record.access_audit:
        text = str(item or "").strip()
        if text.startswith("keystore:"):
            name = text.split(":", 1)[1].strip()
            if name:
                refs.append(name)
    return tuple(dict.fromkeys(refs))


def _settings_secret_is_stored(record: SecretRefRecord) -> bool:
    for name in _settings_keystore_refs(record):
        try:
            KEYSTORE.fetch(name)
            return True
        except Exception:  # noqa: BLE001 - status only, never echo backend detail.
            continue
    return False


def _settings_require_declared_secret_values(secrets: Iterable[SecretRefRecord]) -> None:
    for secret in secrets:
        for name in _settings_keystore_refs(secret):
            try:
                KEYSTORE.fetch(name)
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"SecretRef {secret.secret_ref} declares keystore:{name} but secret value is missing") from exc


def _settings_secret_value_from_payload(payload: dict[str, Any]) -> tuple[SecretRefRecord, KeystoreRecord, str]:
    raw = payload.get("secret_value") if isinstance(payload.get("secret_value"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="secret_value payload must be an object")
    metadata = {key: value for key, value in raw.items() if str(key) not in _SECRET_VALUE_FIELDS}
    if contains_plaintext_secret(metadata):
        raise HTTPException(status_code=422, detail="settings SecretValue metadata cannot contain plaintext credential material")

    secret_ref = str(raw.get("secret_ref") or "").strip()
    if not secret_ref:
        raise ValueError("secret_value.secret_ref is required")
    try:
        existing = ONBOARDING_REGISTRY.secret_ref(secret_ref)
    except KeyError:
        existing = None
    status = raw.get("status")
    if status is None and existing is not None:
        status = existing.status
    if status is None:
        status = "active"
    status_text = status.value if hasattr(status, "value") else str(status)
    if status_text.lower() == "revoked":
        raise ValueError("cannot store secret value for a revoked SecretRef")
    if existing is not None:
        existing_status = existing.status.value if hasattr(existing.status, "value") else str(existing.status)
        if existing_status == "revoked":
            raise ValueError("cannot store secret value for a revoked SecretRef")

    api_key = raw.get("secret_value")
    if api_key in (None, ""):
        api_key = raw.get("api_key")
    if api_key in (None, ""):
        api_key = raw.get("value")
    if api_key in (None, ""):
        api_key = raw.get("token")
    if api_key in (None, ""):
        raise ValueError("secret_value.secret_value is required")
    api_secret = raw.get("api_secret")
    if api_secret in (None, ""):
        api_secret = raw.get("secret")
    if api_secret in (None, ""):
        api_secret = api_key

    keystore_ref = str(raw.get("keystore_ref") or raw.get("keystore_name") or "").strip()
    if not keystore_ref:
        keystore_ref = _settings_keystore_ref_for_secret_ref(secret_ref)
    note_payload: dict[str, Any] = {}
    if isinstance(raw.get("note_payload"), dict):
        note_payload.update(raw["note_payload"])
    for field in ("base_url", "model"):
        if raw.get(field) not in (None, ""):
            note_payload[field] = raw.get(field)
    if contains_plaintext_secret(note_payload):
        raise HTTPException(status_code=422, detail="settings SecretValue note metadata cannot contain plaintext credential material")
    note = json.dumps(note_payload, ensure_ascii=False) if note_payload else str(raw.get("note") or "")

    access_audit = list(existing.access_audit if existing else _settings_tuple(raw.get("access_audit")))
    access_audit.append(f"keystore:{keystore_ref}")
    record = SecretRefRecord(
        secret_ref=secret_ref,
        scope=str(raw.get("scope") or (existing.scope if existing else "")),
        status=status,
        created_at=str(raw.get("created_at") or (existing.created_at if existing else _utc_now_iso_seconds())),
        last_test=raw.get("last_test", existing.last_test if existing else None),
        last_used=raw.get("last_used", existing.last_used if existing else None),
        rotation_record=raw.get("rotation_record", existing.rotation_record if existing else None),
        access_audit=tuple(dict.fromkeys(access_audit)),
        stale_warning=raw.get("stale_warning", existing.stale_warning if existing else None),
        connector_scope_review=raw.get(
            "connector_scope_review",
            existing.connector_scope_review if existing else None,
        ),
        revoked_at=raw.get("revoked_at", existing.revoked_at if existing else None),
        affected_skills=_settings_tuple(raw.get("affected_skills") or (existing.affected_skills if existing else ())),
    )
    decision = validate_secret_ref(record)
    if not decision.accepted:
        raise ValueError("; ".join(violation.code for violation in decision.violations))
    return (
        record,
        KeystoreRecord(name=keystore_ref, api_key=str(api_key), api_secret=str(api_secret), note=note),
        keystore_ref,
    )


def _secret_ref_from_payload(payload: dict[str, Any]) -> SecretRefRecord:
    raw = _settings_raw_payload(payload, "secret_ref")
    return SecretRefRecord(
        secret_ref=str(raw.get("secret_ref") or ""),
        scope=str(raw.get("scope") or ""),
        status=raw.get("status") or "active",
        created_at=str(raw.get("created_at") or ""),
        last_test=raw.get("last_test"),
        last_used=raw.get("last_used"),
        rotation_record=raw.get("rotation_record"),
        access_audit=_settings_tuple(raw.get("access_audit")),
        stale_warning=raw.get("stale_warning"),
        connector_scope_review=raw.get("connector_scope_review"),
        revoked_at=raw.get("revoked_at"),
        affected_skills=_settings_tuple(raw.get("affected_skills")),
    )


def _data_source_asset_from_payload(payload: dict[str, Any]) -> DataSourceAssetRecord:
    raw = _settings_raw_payload(payload, "data_source_asset")
    return DataSourceAssetRecord(
        source_ref=str(raw.get("source_ref") or ""),
        license=raw.get("license"),
        redistribution_rights=raw.get("redistribution_rights"),
        rate_limit=raw.get("rate_limit"),
        tos_constraints=raw.get("tos_constraints"),
        commercial_use_status=raw.get("commercial_use_status"),
        retention_policy=raw.get("retention_policy"),
        source_owner=raw.get("source_owner"),
        source_url_or_path=raw.get("source_url_or_path"),
    )


def _ingestion_skill_from_payload(payload: dict[str, Any]) -> IngestionSkillRecord:
    raw = _settings_raw_payload(payload, "ingestion_skill")
    connector_config = raw.get("connector_config") or {}
    if not isinstance(connector_config, dict):
        raise HTTPException(status_code=422, detail="ingestion_skill.connector_config must be an object")
    return IngestionSkillRecord(
        skill_id=str(raw.get("skill_id") or ""),
        source_type=str(raw.get("source_type") or ""),
        source_ref=str(raw.get("source_ref") or ""),
        connector_config=connector_config,
        schema_mapping_ref=str(raw.get("schema_mapping_ref") or raw.get("schema_mapping") or ""),
        secret_refs=_settings_tuple(raw.get("secret_refs")),
        refresh_mode=str(raw.get("refresh_mode") or ""),
        data_quality_tests=_settings_tuple(raw.get("data_quality_tests")),
        pit_bitemporal_rules_ref=str(raw.get("pit_bitemporal_rules_ref") or raw.get("pit_bitemporal_rules") or ""),
        output_dataset_id=str(raw.get("output_dataset_id") or ""),
        owner=str(raw.get("owner") or ""),
        version=str(raw.get("version") or ""),
        lifecycle_state=raw.get("lifecycle_state") or "active",
        freshness_status=str(raw.get("freshness_status") or ""),
        permission_scope=str(raw.get("permission_scope") or ""),
        dependency_lock_ref=str(raw.get("dependency_lock_ref") or raw.get("dependency_lock") or ""),
        schedule_owner=str(raw.get("schedule_owner") or ""),
        rollback_plan_ref=str(raw.get("rollback_plan_ref") or raw.get("rollback_plan") or ""),
        last_run=raw.get("last_run"),
        last_success=raw.get("last_success"),
        drift_alerts=_settings_tuple(raw.get("drift_alerts")),
        failure_reason=raw.get("failure_reason"),
        schema_drift_status=str(raw.get("schema_drift_status") or "none"),
        schema_drift_event_refs=_settings_tuple(raw.get("schema_drift_event_refs")),
        downstream_impact_refs=_settings_tuple(raw.get("downstream_impact_refs")),
        dry_run_diff_ref=raw.get("dry_run_diff_ref"),
        quarantine_ref=raw.get("quarantine_ref"),
    )


def _ingestion_skill_update_from_payload(payload: dict[str, Any]) -> IngestionSkillUpdateRecord:
    raw = _settings_raw_payload(payload, "ingestion_skill_update")
    return IngestionSkillUpdateRecord(
        update_ref=str(raw.get("update_ref") or ""),
        skill_ref=str(raw.get("skill_ref") or raw.get("skill_id") or ""),
        skill_version=str(raw.get("skill_version") or ""),
        source_ref=raw.get("source_ref"),
        secret_ref=raw.get("secret_ref"),
        dataset_version_ref=raw.get("dataset_version_ref"),
        checksum=raw.get("checksum"),
        lineage_ref=raw.get("lineage_ref"),
        quality_verdict_ref=raw.get("quality_verdict_ref"),
        known_at_ref=raw.get("known_at_ref"),
        effective_at_ref=raw.get("effective_at_ref"),
        freshness_status=raw.get("freshness_status"),
        schema_drift_status=str(raw.get("schema_drift_status") or "none"),
        row_count=int(raw["row_count"]) if raw.get("row_count") is not None else None,
        recorded_by=raw.get("recorded_by"),
        evidence_refs=_settings_tuple(raw.get("evidence_refs")),
    )


def _llm_provider_from_payload(payload: dict[str, Any]) -> LLMProviderRecord:
    raw = _settings_raw_payload(payload, "llm_provider")
    return LLMProviderRecord(
        provider_id=str(raw.get("provider_id") or ""),
        provider_type=str(raw.get("provider_type") or ""),
        auth_methods=_settings_tuple(raw.get("auth_methods")),
        base_url=str(raw.get("base_url") or ""),
        model_profiles=_settings_tuple(raw.get("model_profiles")),
        capability_tags=_settings_tuple(raw.get("capability_tags")),
        context_window=int(raw.get("context_window") or 0),
        tool_calling_support=bool(raw.get("tool_calling_support", False)),
        structured_output_support=bool(raw.get("structured_output_support", False)),
        cost_model_ref=str(raw.get("cost_model_ref") or ""),
        rate_limits=str(raw.get("rate_limits") or ""),
        data_retention_policy=str(raw.get("data_retention_policy") or ""),
        region_residency=str(raw.get("region_residency") or ""),
        allowed_roles=_settings_tuple(raw.get("allowed_roles")),
        allowed_desks=_settings_tuple(raw.get("allowed_desks")),
        health_status=str(raw.get("health_status") or ""),
        quota_status=str(raw.get("quota_status") or ""),
        auth_refs=_settings_tuple(raw.get("auth_refs")),
        plaintext_credential=raw.get("plaintext_credential"),
    )


def _llm_provider_health_snapshot_from_payload(payload: dict[str, Any]) -> LLMProviderHealthSnapshotRecord:
    raw = _settings_raw_payload(payload, "llm_provider_health_snapshot")
    allowed_fields = {
        "snapshot_ref",
        "provider_id",
        "auth_ref",
        "checked_at",
        "checker_ref",
        "health_status",
        "quota_status",
        "latency_ms",
        "response_hash",
        "capability_refs",
        "evidence_refs",
        "error_code",
        "recorded_by",
        "snapshot_hash",
    }
    forbidden_markers = (
        "api_key",
        "api_secret",
        "oauth_token",
        "output",
        "payload",
        "prompt",
        "raw_",
        "response_body",
        "secret",
        "token",
    )
    for key in raw:
        lowered = str(key).lower()
        if any(marker in lowered for marker in forbidden_markers):
            raise ValueError(f"LLM provider health snapshot cannot contain raw or secret-bearing field: {key}")
        if lowered not in allowed_fields:
            raise ValueError(f"unsupported LLM provider health snapshot field: {key}")
    return LLMProviderHealthSnapshotRecord(
        snapshot_ref=str(raw.get("snapshot_ref") or ""),
        provider_id=str(raw.get("provider_id") or ""),
        auth_ref=str(raw.get("auth_ref") or ""),
        checked_at=str(raw.get("checked_at") or ""),
        checker_ref=str(raw.get("checker_ref") or ""),
        health_status=str(raw.get("health_status") or "").strip().lower(),
        quota_status=str(raw.get("quota_status") or "").strip().lower(),
        latency_ms=int(raw.get("latency_ms") or 0),
        response_hash=str(raw.get("response_hash") or ""),
        capability_refs=_settings_tuple(raw.get("capability_refs")),
        evidence_refs=_settings_tuple(raw.get("evidence_refs")),
        error_code=raw.get("error_code"),
        recorded_by=raw.get("recorded_by"),
        snapshot_hash=raw.get("snapshot_hash"),
    )


def _credential_pool_from_payload(payload: dict[str, Any]) -> LLMCredentialPoolRecord:
    raw = _settings_raw_payload(payload, "credential_pool")
    return LLMCredentialPoolRecord(
        pool_id=str(raw.get("pool_id") or ""),
        provider_id=str(raw.get("provider_id") or ""),
        auth_refs=_settings_tuple(raw.get("auth_refs")),
        priority=_settings_tuple(raw.get("priority")),
        rotation_policy=str(raw.get("rotation_policy") or ""),
        fallback_policy=str(raw.get("fallback_policy") or ""),
        rate_limit_policy=str(raw.get("rate_limit_policy") or ""),
        quota_policy=str(raw.get("quota_policy") or ""),
        owner=str(raw.get("owner") or ""),
        last_test=raw.get("last_test"),
        last_used=raw.get("last_used"),
        revoked_refs=_settings_tuple(raw.get("revoked_refs")),
        affected_role_agents=_settings_tuple(raw.get("affected_role_agents")),
    )


def _routing_policy_from_payload(payload: dict[str, Any]) -> ModelRoutingPolicyRecord:
    raw = _settings_raw_payload(payload, "routing_policy")
    return ModelRoutingPolicyRecord(
        routing_policy_id=str(raw.get("routing_policy_id") or ""),
        role_agent=str(raw.get("role_agent") or ""),
        desk=str(raw.get("desk") or ""),
        task_type=str(raw.get("task_type") or ""),
        required_capabilities=_settings_tuple(raw.get("required_capabilities")),
        allowed_providers=_settings_tuple(raw.get("allowed_providers")),
        allowed_models=_settings_tuple(raw.get("allowed_models")),
        credential_pool_ref=raw.get("credential_pool_ref"),
        fallback_order=_settings_tuple(raw.get("fallback_order")),
        cost_limit=raw.get("cost_limit"),
        latency_limit=raw.get("latency_limit"),
        data_retention_requirement=raw.get("data_retention_requirement"),
        independence_requirement=raw.get("independence_requirement"),
        replay_requirement=raw.get("replay_requirement"),
    )


def _utc_now_iso_seconds() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _data_connector_check_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "data_connector_check")


def _data_connector_ingestion_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "ingestion_skill_run")


def _data_connector_field_mapping_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "data_connector_field_mapping")


def _settings_string_map(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a non-empty object")
    return {str(key): str(child) for key, child in value.items()}


def _data_connector_field_mapping_from_payload(payload: dict[str, Any]) -> DataConnectorFieldMappingRecord:
    raw = _data_connector_field_mapping_payload(payload)
    record = DataConnectorFieldMappingRecord(
        mapping_ref=str(raw.get("mapping_ref") or raw.get("schema_mapping_ref") or ""),
        skill_id=str(raw.get("skill_id") or ""),
        source_ref=str(raw.get("source_ref") or ""),
        schema_probe_ref=str(raw.get("schema_probe_ref") or ""),
        mapped_at=str(raw.get("mapped_at") or _utc_now_iso_seconds()),
        schema_signature_hash=str(raw.get("schema_signature_hash") or ""),
        source_to_canonical=_settings_string_map(raw.get("source_to_canonical"), "source_to_canonical"),
        event_time_column=str(raw.get("event_time_column") or ""),
        known_at_column=raw.get("known_at_column"),
        effective_at_column=raw.get("effective_at_column"),
        symbol_column=raw.get("symbol_column"),
        unmapped_columns=_settings_tuple(raw.get("unmapped_columns")),
        mapping_hash=raw.get("mapping_hash"),
        mapping_method=str(raw.get("mapping_method") or "manual"),
        pit_bitemporal_candidate_ref=raw.get("pit_bitemporal_candidate_ref"),
        evidence_refs=_settings_tuple(raw.get("evidence_refs")),
        recorded_by=raw.get("recorded_by"),
    )
    return record


def _data_connector_pit_bitemporal_rule_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "data_connector_pit_bitemporal_rule")


def _data_connector_pit_bitemporal_rule_from_payload(payload: dict[str, Any]) -> DataConnectorPITBitemporalRuleRecord:
    raw = _data_connector_pit_bitemporal_rule_payload(payload)
    return DataConnectorPITBitemporalRuleRecord(
        rule_ref=str(raw.get("rule_ref") or raw.get("pit_bitemporal_rules_ref") or ""),
        skill_id=str(raw.get("skill_id") or ""),
        source_ref=str(raw.get("source_ref") or ""),
        field_mapping_ref=str(raw.get("field_mapping_ref") or raw.get("mapping_ref") or ""),
        schema_probe_ref=str(raw.get("schema_probe_ref") or ""),
        generated_at=str(raw.get("generated_at") or _utc_now_iso_seconds()),
        event_time_column=str(raw.get("event_time_column") or ""),
        known_at_policy=str(raw.get("known_at_policy") or ""),
        effective_at_policy=str(raw.get("effective_at_policy") or ""),
        asof_join_policy=str(raw.get("asof_join_policy") or ""),
        timezone=str(raw.get("timezone") or "UTC"),
        lookahead_guard_ref=str(raw.get("lookahead_guard_ref") or ""),
        restatement_policy=str(raw.get("restatement_policy") or ""),
        known_at_column=raw.get("known_at_column"),
        effective_at_column=raw.get("effective_at_column"),
        calendar_ref=raw.get("calendar_ref"),
        monotonicity_check_ref=raw.get("monotonicity_check_ref"),
        rule_hash=raw.get("rule_hash"),
        evidence_refs=_settings_tuple(raw.get("evidence_refs")),
        recorded_by=raw.get("recorded_by"),
    )


def _settings_dataset_semantics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "dataset_semantics")


def _settings_instrument_spec_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "instrument_spec")


def _settings_capability_matrix_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "capability_matrix")


def _settings_market_data_use_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "market_data_use")


def _settings_data_connector_onboarding_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _settings_raw_payload(payload or {}, "data_connector_onboarding_run")


def _settings_onboarding_nested_payload(
    request: dict[str, Any],
    *,
    step_key: str,
    wrapper_key: str,
    skill_id: str,
) -> dict[str, Any]:
    raw = request.get(step_key)
    if raw is None:
        raw = request.get(wrapper_key)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{step_key} must be an object")
    step_payload = dict(_settings_raw_payload(raw, wrapper_key))
    payload_skill_id = str(step_payload.get("skill_id") or step_payload.get("skill_ref") or "").strip()
    if payload_skill_id and payload_skill_id != skill_id:
        raise ValueError(f"{step_key}.skill_id must match data_connector_onboarding_run.skill_id")
    step_payload["skill_id"] = skill_id
    return step_payload


def _settings_onboarding_merge_payload(
    request: dict[str, Any],
    *,
    step_key: str,
    wrapper_key: str,
    skill_id: str,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step_payload = _settings_onboarding_nested_payload(
        request,
        step_key=step_key,
        wrapper_key=wrapper_key,
        skill_id=skill_id,
    )
    for key, value in (defaults or {}).items():
        if value not in (None, "", [], ()):
            step_payload.setdefault(key, value)
    return step_payload


def _settings_normalize_column_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _settings_first_schema_column(columns: tuple[str, ...], candidates: set[str]) -> str | None:
    for column in columns:
        normalized = _settings_normalize_column_name(column)
        if normalized in candidates:
            return column
    return None


def _settings_infer_source_to_canonical(columns: tuple[str, ...]) -> dict[str, str]:
    aliases = {
        "ts": "event_time",
        "time": "event_time",
        "date": "event_time",
        "datetime": "event_time",
        "timestamp": "event_time",
        "trade_date": "event_time",
        "open_time": "event_time",
        "event_time": "event_time",
        "symbol": "instrument_id",
        "ticker": "instrument_id",
        "ts_code": "instrument_id",
        "code": "instrument_id",
        "instrument": "instrument_id",
        "instrument_id": "instrument_id",
        "market": "market",
        "exchange": "exchange",
        "interval": "interval",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "vol": "volume",
        "amount": "amount",
        "quote_volume": "amount",
        "turnover": "amount",
        "adj_factor": "adjustment_factor",
        "pre_close": "previous_close",
    }
    mapping: dict[str, str] = {}
    used_targets: set[str] = set()
    for column in columns:
        target = aliases.get(_settings_normalize_column_name(column))
        if target and target not in used_targets:
            mapping[column] = target
            used_targets.add(target)
    return mapping


def _settings_auto_field_mapping_payload(
    *,
    skill: IngestionSkillRecord,
    schema_probe_ref: str,
    step_payload: dict[str, Any],
) -> dict[str, Any]:
    schema_probe = ONBOARDING_REGISTRY.data_connector_schema_probe(schema_probe_ref)
    if schema_probe.skill_id != skill.skill_id:
        raise ValueError("data_connector_onboarding_run schema_probe_ref must match IngestionSkill")
    columns = tuple(str(column) for column in schema_probe.columns)
    source_to_canonical = dict(step_payload.get("source_to_canonical") or {})
    mapping_method = str(step_payload.get("mapping_method") or "manual")
    if not source_to_canonical:
        source_to_canonical = _settings_infer_source_to_canonical(columns)
        mapping_method = "agent_suggested"
    event_time_column = str(step_payload.get("event_time_column") or "").strip() or _settings_first_schema_column(
        columns,
        {"ts", "time", "date", "datetime", "timestamp", "trade_date", "open_time", "event_time"},
    )
    symbol_column = step_payload.get("symbol_column")
    if symbol_column in (None, ""):
        symbol_column = _settings_first_schema_column(
            columns,
            {"symbol", "ticker", "ts_code", "code", "instrument", "instrument_id"},
        )
    if not event_time_column:
        raise ValueError("data_connector_onboarding_run cannot infer event_time_column from schema probe")
    if event_time_column not in source_to_canonical:
        source_to_canonical[event_time_column] = "event_time"
    if symbol_column and symbol_column not in source_to_canonical:
        source_to_canonical[str(symbol_column)] = "instrument_id"
    unmapped_columns = tuple(
        str(column)
        for column in columns
        if str(column) not in source_to_canonical and str(column) not in _settings_tuple(step_payload.get("unmapped_columns"))
    )
    evidence_refs = tuple(
        ref
        for ref in (
            schema_probe.probe_ref,
            *(_settings_tuple(step_payload.get("evidence_refs"))),
        )
        if ref
    )
    return {
        **step_payload,
        "schema_probe_ref": schema_probe.probe_ref,
        "schema_signature_hash": schema_probe.schema_signature_hash,
        "source_to_canonical": source_to_canonical,
        "event_time_column": event_time_column,
        "known_at_column": step_payload.get("known_at_column", event_time_column),
        "effective_at_column": step_payload.get("effective_at_column", event_time_column),
        "symbol_column": symbol_column,
        "unmapped_columns": tuple(dict.fromkeys((*_settings_tuple(step_payload.get("unmapped_columns")), *unmapped_columns))),
        "mapping_method": mapping_method,
        "pit_bitemporal_candidate_ref": step_payload.get("pit_bitemporal_candidate_ref")
        or f"pit_candidate:{_settings_ref_fragment(skill.skill_id)}:auto",
        "evidence_refs": evidence_refs,
    }


def _settings_ref_fragment(value: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value or "").strip())
    return fragment.strip("_:") or "default"


def _settings_infer_asset_class(skill: IngestionSkillRecord, source: DataSourceAssetRecord) -> str:
    text = " ".join(
        str(value or "").lower()
        for value in (
            skill.output_dataset_id,
            skill.source_type,
            source.source_ref,
            source.source_url_or_path,
        )
    )
    if any(token in text for token in ("cn_equity", "a_share", "ashare", "tushare", "china")):
        return "cn_equity"
    if any(token in text for token in ("crypto", "binance", "okx", "coinbase", "usdt")):
        return "crypto"
    if any(token in text for token in ("fx", "forex", "currency")):
        return "fx"
    if any(token in text for token in ("future", "futures", "perpetual")):
        return "futures"
    return "equity"


def _settings_default_instrument_type(asset_class: str) -> str:
    normalized = str(asset_class or "").lower()
    if normalized in {"crypto"}:
        return "spot"
    if normalized in {"futures", "future"}:
        return "future"
    return "equity"


def _settings_default_currency(asset_class: str) -> str:
    normalized = str(asset_class or "").lower()
    if normalized in {"cn_equity", "a_share", "equity_cn", "stocks_cn"}:
        return "CNY"
    if normalized == "crypto":
        return "USDT"
    if normalized == "fx":
        return "USD"
    return "USD"


def _settings_dataset_for_skill(
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    request: dict[str, Any],
) -> DatasetSemanticsRecord:
    dataset_ref = str(
        request.get("dataset_ref")
        or request.get("dataset_semantics_ref")
        or request.get("market_data_dataset_ref")
        or ""
    ).strip()
    if dataset_ref:
        dataset = MARKET_DATA_REGISTRY.dataset(dataset_ref)
    else:
        candidates = [record for record in MARKET_DATA_REGISTRY.datasets() if record.source_ref == source.source_ref]
        if not candidates:
            raise ValueError("settings market-data generation requires a recorded DatasetSemantics")
        dataset = sorted(candidates, key=lambda item: (str(item.version or ""), str(item.dataset_ref or "")))[-1]
    if dataset.source_ref != source.source_ref:
        raise ValueError("settings dataset_ref must match IngestionSkill source_ref")
    return dataset


def _settings_instrument_for_skill(
    skill: IngestionSkillRecord,
    request: dict[str, Any],
) -> InstrumentSpec:
    instrument_ref = str(request.get("instrument_ref") or "").strip()
    if instrument_ref:
        instrument = MARKET_DATA_REGISTRY.instrument(instrument_ref)
    else:
        candidates = [
            record for record in MARKET_DATA_REGISTRY.instruments() if record.symbol_mapping_ref == skill.schema_mapping_ref
        ]
        if not candidates:
            raise ValueError("settings market-data use requires a recorded InstrumentSpec")
        instrument = sorted(candidates, key=lambda item: str(item.instrument_ref or ""))[-1]
    if instrument.symbol_mapping_ref and instrument.symbol_mapping_ref != skill.schema_mapping_ref:
        raise ValueError("settings InstrumentSpec must match IngestionSkill schema_mapping_ref")
    return instrument


def _settings_capability_for_instrument(
    instrument: InstrumentSpec,
    request: dict[str, Any],
) -> MarketCapabilityMatrixRecord:
    matrix_ref = str(request.get("capability_matrix_ref") or request.get("matrix_ref") or "").strip()
    if matrix_ref:
        capability = MARKET_DATA_REGISTRY.capability_matrix(matrix_ref)
    else:
        candidates = [
            record
            for record in MARKET_DATA_REGISTRY.capability_matrices()
            if record.asset_class == instrument.asset_class and record.instrument_type == instrument.instrument_type
        ]
        if not candidates:
            raise ValueError("settings market-data use requires a recorded MarketCapabilityMatrix")
        capability = sorted(candidates, key=lambda item: str(item.matrix_ref or ""))[-1]
    if capability.asset_class != instrument.asset_class or capability.instrument_type != instrument.instrument_type:
        raise ValueError("settings capability_matrix_ref must match InstrumentSpec asset_class/instrument_type")
    return capability


def _dataset_version_ref_candidates(version: DatasetVersion) -> set[str]:
    return {
        version.version_id,
        f"dataset_version:{version.version_id}",
        f"dataset_version:{version.dataset_id}:{version.version_id}",
        f"dataset_version:{version.dataset_id}@{version.version_id}",
    }


def _resolve_dataset_version_ref(ref: str | None) -> DatasetVersion:
    ref_text = str(ref or "").strip()
    if not ref_text:
        raise ValueError("dataset_version_ref is required")
    for version in DATASET_REGISTRY.list_versions():
        if ref_text in _dataset_version_ref_candidates(version):
            return version
    raise ValueError(f"dataset_version_ref {ref_text!r} is not recorded")


def _dataset_version_ref(version: DatasetVersion) -> str:
    return f"dataset_version:{version.dataset_id}:{version.version_id}"


def _latest_ok_connector_check(skill: IngestionSkillRecord, request: dict[str, Any]) -> DataConnectorConnectionCheckRecord:
    check_ref = str(request.get("connector_check_ref") or request.get("check_ref") or "").strip()
    if check_ref:
        check = ONBOARDING_REGISTRY.data_connector_check(check_ref)
    else:
        checks = [
            record
            for record in ONBOARDING_REGISTRY.data_connector_checks()
            if record.skill_id == skill.skill_id
            and record.source_ref == skill.source_ref
            and str(record.status or "").lower() == "ok"
        ]
        if not checks:
            raise ValueError("ingestion run requires an ok DataConnectorConnectionCheck")
        check = sorted(checks, key=lambda item: str(item.checked_at or ""))[-1]
    if check.skill_id != skill.skill_id:
        raise ValueError("ingestion run connector_check_ref must match IngestionSkill skill_id")
    if check.source_ref != skill.source_ref:
        raise ValueError("ingestion run connector_check_ref must match IngestionSkill source_ref")
    if set(check.secret_refs) != set(skill.secret_refs):
        raise ValueError("ingestion run connector_check_ref must match IngestionSkill secret_refs")
    if str(check.status or "").lower() != "ok":
        raise ValueError("ingestion run requires an ok DataConnectorConnectionCheck")
    return check


def _frame_contains_plaintext_secret(fetch_result: FetchResult) -> bool:
    frame = fetch_result.frame
    if contains_plaintext_secret(list(frame.columns)):
        return True
    for column_name in frame.columns:
        series = frame.get_column(column_name)
        dtype_text = str(series.dtype).lower()
        if "str" not in dtype_text and "categorical" not in dtype_text and "enum" not in dtype_text:
            continue
        for value in series.drop_nulls().to_list():
            if contains_plaintext_secret(value):
                return True
    return False


def _verified_runner_fetch_result(result: dict[str, Any] | FetchResult, *, skill: IngestionSkillRecord) -> tuple[FetchResult, dict[str, Any]]:
    raw_result: dict[str, Any]
    if isinstance(result, FetchResult):
        raw_result = {"fetch_result": result}
    elif isinstance(result, dict):
        raw_result = result
    else:
        raise ValueError("data connector ingestion runner must return an object")
    raw_fetch = raw_result.get("fetch_result")
    if not isinstance(raw_fetch, FetchResult):
        raise ValueError("data connector ingestion runner must return FetchResult in fetch_result")
    if raw_result.get("dataset_id") and str(raw_result.get("dataset_id")) != skill.output_dataset_id:
        raise ValueError("ingestion runner dataset_id must match IngestionSkill output_dataset_id")
    if raw_fetch.frame is None or raw_fetch.frame.is_empty():
        raise ValueError("ingestion runner returned empty dataset; DatasetVersion not recorded")
    if int(raw_fetch.row_count or 0) != raw_fetch.frame.height:
        raise ValueError("ingestion runner row_count must match FetchResult frame height")
    metadata_without_frame = {key: value for key, value in raw_result.items() if key != "fetch_result"}
    if contains_plaintext_secret(metadata_without_frame) or contains_plaintext_secret(raw_fetch.to_meta()):
        raise ValueError("ingestion runner result cannot contain plaintext credential material")
    if _frame_contains_plaintext_secret(raw_fetch):
        raise ValueError("ingestion runner frame cannot contain plaintext credential material")
    computed = make_wide_fetch_result(raw_fetch.frame, source_name=raw_fetch.source_name)
    if raw_fetch.sha256 != computed.sha256:
        raise ValueError("ingestion runner sha256 must match FetchResult frame content")
    verified = FetchResult(
        frame=raw_fetch.frame,
        source_name=raw_fetch.source_name,
        fetched_at_utc=str(raw_fetch.fetched_at_utc or computed.fetched_at_utc),
        row_count=computed.row_count,
        coverage_start_utc=computed.coverage_start_utc,
        coverage_end_utc=computed.coverage_end_utc,
        sha256=computed.sha256,
    )
    return verified, raw_result


def _settings_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._") or "x"


def _write_ingestion_dataset_file(dataset_id: str, fetch_result: FetchResult) -> Path:
    dataset_dir = DATA_ROOT / "datasets" / "ingestion" / _settings_slug(dataset_id)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    target = dataset_dir / f"{fetch_result.sha256[:12]}.parquet"
    if target.exists():
        return target
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        fetch_result.frame.write_parquet(temp)
        os.replace(temp, target)
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise
    return target


def _schema_signature_for_fetch(fetch_result: FetchResult) -> tuple[str, tuple[str, ...], dict[str, str]]:
    columns = tuple(str(name) for name in fetch_result.frame.columns)
    dtypes = {name: str(fetch_result.frame.get_column(name).dtype) for name in columns}
    signature_hash = "schema_signature:" + content_hash({"columns": columns, "dtypes": dtypes})
    return signature_hash, columns, dtypes


def _schema_probe_for_fetch(
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    connector_check: DataConnectorConnectionCheckRecord,
    fetch_result: FetchResult,
    runner_result: dict[str, Any],
    actor: str,
) -> DataConnectorSchemaProbeRecord:
    signature_hash, columns, dtypes = _schema_signature_for_fetch(fetch_result)
    previous = sorted(
        (
            probe
            for probe in ONBOARDING_REGISTRY.data_connector_schema_probes()
            if probe.skill_id == skill.skill_id and probe.source_ref == source.source_ref
        ),
        key=lambda item: str(item.probed_at or ""),
    )
    previous_probe = previous[-1] if previous else None
    if previous_probe is None:
        drift_status = "none"
    elif previous_probe.schema_signature_hash == signature_hash:
        drift_status = "unchanged"
    else:
        drift_status = str(runner_result.get("schema_drift_status") or "changed").lower()
        if drift_status not in {"changed", "drifted"}:
            drift_status = "changed"
    probe_ref = str(
        runner_result.get("schema_probe_ref")
        or connector_check.schema_probe_ref
        or "schema_probe:"
        + content_hash(
            {
                "skill_id": skill.skill_id,
                "source_ref": source.source_ref,
                "connector_check_ref": connector_check.check_ref,
                "schema_signature_hash": signature_hash,
                "sha256": fetch_result.sha256,
            }
        )
    )
    event_ref = runner_result.get("schema_drift_event_ref")
    if not event_ref and runner_result.get("schema_drift_event_refs"):
        event_refs = _settings_tuple(runner_result.get("schema_drift_event_refs"))
        event_ref = event_refs[0] if event_refs else None
    probe = DataConnectorSchemaProbeRecord(
        probe_ref=probe_ref,
        skill_id=skill.skill_id,
        source_ref=source.source_ref,
        connector_check_ref=connector_check.check_ref,
        probed_at=str(runner_result.get("probed_at") or fetch_result.fetched_at_utc or _utc_now_iso_seconds()),
        schema_signature_hash=signature_hash,
        columns=columns,
        dtypes=dtypes,
        row_count=fetch_result.row_count,
        dataset_version_ref=None,
        drift_status=drift_status,
        previous_probe_ref=previous_probe.probe_ref if previous_probe else None,
        schema_drift_event_ref=event_ref,
        downstream_impact_refs=_settings_tuple(runner_result.get("downstream_impact_refs")),
        recorded_by=actor,
    )
    decision = validate_data_connector_schema_probe(
        probe,
        skill=skill,
        source=source,
        connector_check=connector_check,
    )
    if not decision.accepted:
        raise ValueError("; ".join(violation.code for violation in decision.violations))
    return probe


def _record_ingestion_dataset_version_and_update(
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    secret: SecretRefRecord | None,
    connector_check: DataConnectorConnectionCheckRecord,
    fetch_result: FetchResult,
    runner_result: dict[str, Any],
    actor: str,
) -> tuple[DatasetVersion, IngestionSkillUpdateRecord]:
    schema_probe = _schema_probe_for_fetch(
        skill=skill,
        source=source,
        connector_check=connector_check,
        fetch_result=fetch_result,
        runner_result=runner_result,
        actor=actor,
    )
    file_path = _write_ingestion_dataset_file(skill.output_dataset_id, fetch_result)
    metadata = {
        "source_ref": source.source_ref,
        "secret_refs": list(skill.secret_refs),
        "ingestion_skill_id": skill.skill_id,
        "ingestion_skill_version": skill.version,
        "connector_check_ref": connector_check.check_ref,
        "schema_probe_ref": schema_probe.probe_ref,
        "schema_signature_hash": schema_probe.schema_signature_hash,
        "schema_drift_status": schema_probe.drift_status,
        "permission_scope": skill.permission_scope,
        "pit_bitemporal_rules_ref": skill.pit_bitemporal_rules_ref,
        "schema": {name: str(fetch_result.frame.get_column(name).dtype) for name in fetch_result.frame.columns},
    }
    for key in ("market", "data_kind", "interval", "symbols"):
        value = runner_result.get(key) or skill.connector_config.get(key)
        if value not in (None, "", [], ()):
            metadata[key] = value
    version = DATASET_REGISTRY.register(
        skill.output_dataset_id,
        fetch_result,
        file_paths=[str(file_path)],
        metadata=metadata,
    )
    dataset_version_ref = _dataset_version_ref(version)
    schema_probe = ONBOARDING_REGISTRY.record_data_connector_schema_probe(
        replace(schema_probe, dataset_version_ref=dataset_version_ref)
    )
    update_ref = str(
        runner_result.get("update_ref")
        or "ingestion_update:"
        + content_hash(
            {
                "skill_id": skill.skill_id,
                "skill_version": skill.version,
                "source_ref": source.source_ref,
                "connector_check_ref": connector_check.check_ref,
                "dataset_version_ref": dataset_version_ref,
                "sha256": version.sha256,
            }
        )
    )
    lineage_ref = str(
        runner_result.get("lineage_ref")
        or "lineage:ingestion:" + content_hash({"dataset_version_ref": dataset_version_ref, "file_paths": version.file_paths})
    )
    quality_verdict_ref = str(
        runner_result.get("quality_verdict_ref")
        or "quality:basic_non_empty_schema:" + content_hash(
            {
                "dataset_version_ref": dataset_version_ref,
                "row_count": version.row_count,
                "schema_probe_ref": schema_probe.probe_ref,
            }
        )
    )
    known_at_ref = str(
        runner_result.get("known_at_ref")
        or "known_at:connector_fetch:" + content_hash(
            {"skill_id": skill.skill_id, "fetched_at_utc": version.fetched_at_utc}
        )
    )
    effective_at_ref = str(
        runner_result.get("effective_at_ref")
        or "effective_at:coverage:" + content_hash(
            {
                "dataset_version_ref": dataset_version_ref,
                "coverage_start_utc": version.coverage_start_utc,
                "coverage_end_utc": version.coverage_end_utc,
            }
        )
    )
    evidence_refs = (
        connector_check.check_ref,
        schema_probe.probe_ref,
        f"dataset_file:{version.sha256}",
        *_settings_tuple(runner_result.get("evidence_refs")),
    )
    update = ASSET_LIFECYCLE_REGISTRY.record_ingestion_skill_update(
        IngestionSkillUpdateRecord(
            update_ref=update_ref,
            skill_ref=skill.skill_id,
            skill_version=skill.version,
            source_ref=source.source_ref,
            secret_ref=secret.secret_ref
            if secret is not None
            else str(
                runner_result.get("secret_ref")
                or "secret:none:"
                + _settings_slug(str(runner_result.get("connector_name") or skill.connector_config.get("connector_name") or skill.skill_id))
            ),
            dataset_version_ref=dataset_version_ref,
            checksum=version.sha256,
            lineage_ref=lineage_ref,
            quality_verdict_ref=quality_verdict_ref,
            known_at_ref=known_at_ref,
            effective_at_ref=effective_at_ref,
            freshness_status=runner_result.get("freshness_status") or skill.freshness_status,
            schema_drift_status=str(runner_result.get("schema_drift_status") or skill.schema_drift_status or "none"),
            row_count=version.row_count,
            recorded_by=actor,
            evidence_refs=evidence_refs,
        )
    )
    return version, update


def _data_connector_check_record_from_result(
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    skill: IngestionSkillRecord,
    source: DataSourceAssetRecord,
    actor: str,
) -> DataConnectorConnectionCheckRecord:
    checked_at = str(result.get("checked_at") or request.get("checked_at") or _utc_now_iso_seconds())
    checker_ref = str(
        result.get("checker_ref")
        or request.get("checker_ref")
        or getattr(DATA_CONNECTOR_CONNECTION_CHECKER, "checker_ref", "data_connector_connection_checker")
    )
    status = str(result.get("status") or "failed").lower()
    health_status = str(result.get("health_status") or ("ok" if status == "ok" else "failed")).lower()
    quota_status = str(result.get("quota_status") or "unknown").lower()
    response_hash = result.get("response_hash")
    if status == "ok" and not response_hash:
        response_hash = "connector_check_response:" + content_hash(
            {
                "skill_id": skill.skill_id,
                "source_ref": source.source_ref,
                "checker_ref": checker_ref,
                "checked_at": checked_at,
                "status": status,
                "health_status": health_status,
                "quota_status": quota_status,
                "capability_refs": _settings_tuple(result.get("capability_refs")),
                "schema_probe_ref": result.get("schema_probe_ref"),
            }
        )
    check_ref = str(
        result.get("check_ref")
        or request.get("check_ref")
        or "connector_check:"
        + content_hash(
            {
                "skill_id": skill.skill_id,
                "source_ref": source.source_ref,
                "checked_at": checked_at,
                "checker_ref": checker_ref,
                "status": status,
            }
        )
    )
    return DataConnectorConnectionCheckRecord(
        check_ref=check_ref,
        skill_id=skill.skill_id,
        source_ref=source.source_ref,
        secret_refs=_settings_tuple(result.get("secret_refs") or request.get("secret_refs") or skill.secret_refs),
        checked_at=checked_at,
        checker_ref=checker_ref,
        status=status,
        health_status=health_status,
        quota_status=quota_status,
        permission_scope=str(result.get("permission_scope") or request.get("permission_scope") or skill.permission_scope or ""),
        capability_refs=_settings_tuple(result.get("capability_refs")),
        schema_probe_ref=result.get("schema_probe_ref"),
        response_hash=response_hash,
        error_code=result.get("error_code"),
        error_message=result.get("error_message"),
        recorded_by=actor,
    )


def _secret_ref_summary(record: SecretRefRecord) -> dict[str, Any]:
    keystore_refs = _settings_keystore_refs(record)
    return {
        "secret_ref": record.secret_ref,
        "scope": record.scope,
        "status": record.status.value if hasattr(record.status, "value") else str(record.status),
        "last_test": record.last_test,
        "last_used": record.last_used,
        "revoked_at": record.revoked_at,
        "affected_skills": record.affected_skills,
        "keystore_refs": list(keystore_refs),
        "secret_value_stored": _settings_secret_is_stored(record),
        "keystore_backend": KEYSTORE.backend_name if keystore_refs else None,
    }


def _data_source_asset_summary(record: DataSourceAssetRecord) -> dict[str, Any]:
    decision = validate_data_source_asset(record)
    return {
        "source_ref": record.source_ref,
        "license": record.license,
        "redistribution_rights": record.redistribution_rights,
        "rate_limit": record.rate_limit,
        "tos_constraints": record.tos_constraints,
        "commercial_use_status": record.commercial_use_status,
        "retention_policy": record.retention_policy,
        "source_owner": record.source_owner,
        "source_url_or_path": record.source_url_or_path,
        "export_allowed": decision.export_allowed,
        "share_allowed": decision.share_allowed,
        "warning_codes": [warning.code for warning in decision.warnings],
    }


def _ingestion_skill_summary(record: IngestionSkillRecord) -> dict[str, Any]:
    return {
        "skill_id": record.skill_id,
        "source_type": record.source_type,
        "source_ref": record.source_ref,
        "schema_mapping_ref": record.schema_mapping_ref,
        "secret_refs": record.secret_refs,
        "refresh_mode": record.refresh_mode,
        "data_quality_tests": record.data_quality_tests,
        "pit_bitemporal_rules_ref": record.pit_bitemporal_rules_ref,
        "output_dataset_id": record.output_dataset_id,
        "owner": record.owner,
        "version": record.version,
        "lifecycle_state": record.lifecycle_state.value if hasattr(record.lifecycle_state, "value") else str(record.lifecycle_state),
        "freshness_status": record.freshness_status,
        "permission_scope": record.permission_scope,
        "dependency_lock_ref": record.dependency_lock_ref,
        "schedule_owner": record.schedule_owner,
        "rollback_plan_ref": record.rollback_plan_ref,
        "last_run": record.last_run,
        "last_success": record.last_success,
        "schema_drift_status": record.schema_drift_status,
    }


def _data_connector_check_summary(record: DataConnectorConnectionCheckRecord) -> dict[str, Any]:
    return {
        "check_ref": record.check_ref,
        "skill_id": record.skill_id,
        "source_ref": record.source_ref,
        "secret_refs": record.secret_refs,
        "checked_at": record.checked_at,
        "checker_ref": record.checker_ref,
        "status": record.status,
        "health_status": record.health_status,
        "quota_status": record.quota_status,
        "permission_scope": record.permission_scope,
        "capability_refs": record.capability_refs,
        "schema_probe_ref": record.schema_probe_ref,
        "response_hash": record.response_hash,
        "error_code": record.error_code,
        "error_message": record.error_message,
    }


def _data_connector_schema_probe_summary(record: DataConnectorSchemaProbeRecord) -> dict[str, Any]:
    return {
        "probe_ref": record.probe_ref,
        "skill_id": record.skill_id,
        "source_ref": record.source_ref,
        "connector_check_ref": record.connector_check_ref,
        "probed_at": record.probed_at,
        "schema_signature_hash": record.schema_signature_hash,
        "columns": record.columns,
        "dtypes": record.dtypes,
        "row_count": record.row_count,
        "dataset_version_ref": record.dataset_version_ref,
        "drift_status": record.drift_status,
        "previous_probe_ref": record.previous_probe_ref,
        "schema_drift_event_ref": record.schema_drift_event_ref,
        "downstream_impact_refs": record.downstream_impact_refs,
    }


def _data_connector_field_mapping_summary(record: DataConnectorFieldMappingRecord) -> dict[str, Any]:
    return {
        "mapping_ref": record.mapping_ref,
        "skill_id": record.skill_id,
        "source_ref": record.source_ref,
        "schema_probe_ref": record.schema_probe_ref,
        "mapped_at": record.mapped_at,
        "schema_signature_hash": record.schema_signature_hash,
        "source_to_canonical": record.source_to_canonical,
        "event_time_column": record.event_time_column,
        "known_at_column": record.known_at_column,
        "effective_at_column": record.effective_at_column,
        "symbol_column": record.symbol_column,
        "unmapped_columns": record.unmapped_columns,
        "mapping_hash": record.mapping_hash,
        "mapping_method": record.mapping_method,
        "pit_bitemporal_candidate_ref": record.pit_bitemporal_candidate_ref,
        "evidence_refs": record.evidence_refs,
    }


def _data_connector_pit_bitemporal_rule_summary(record: DataConnectorPITBitemporalRuleRecord) -> dict[str, Any]:
    return {
        "rule_ref": record.rule_ref,
        "skill_id": record.skill_id,
        "source_ref": record.source_ref,
        "field_mapping_ref": record.field_mapping_ref,
        "schema_probe_ref": record.schema_probe_ref,
        "generated_at": record.generated_at,
        "event_time_column": record.event_time_column,
        "known_at_column": record.known_at_column,
        "effective_at_column": record.effective_at_column,
        "known_at_policy": record.known_at_policy,
        "effective_at_policy": record.effective_at_policy,
        "asof_join_policy": record.asof_join_policy,
        "timezone": record.timezone,
        "calendar_ref": record.calendar_ref,
        "lookahead_guard_ref": record.lookahead_guard_ref,
        "monotonicity_check_ref": record.monotonicity_check_ref,
        "restatement_policy": record.restatement_policy,
        "rule_hash": record.rule_hash,
        "evidence_refs": record.evidence_refs,
    }


def _ingestion_skill_update_summary(record: IngestionSkillUpdateRecord) -> dict[str, Any]:
    return {
        "update_ref": record.update_ref,
        "skill_ref": record.skill_ref,
        "skill_version": record.skill_version,
        "source_ref": record.source_ref,
        "secret_ref": record.secret_ref,
        "dataset_version_ref": record.dataset_version_ref,
        "checksum": record.checksum,
        "lineage_ref": record.lineage_ref,
        "quality_verdict_ref": record.quality_verdict_ref,
        "known_at_ref": record.known_at_ref,
        "effective_at_ref": record.effective_at_ref,
        "freshness_status": record.freshness_status,
        "schema_drift_status": record.schema_drift_status,
        "row_count": record.row_count,
        "evidence_refs": record.evidence_refs,
    }


def _llm_provider_summary(record: LLMProviderRecord) -> dict[str, Any]:
    return {
        "provider_id": record.provider_id,
        "provider_type": record.provider_type,
        "model_profiles": record.model_profiles,
        "capability_tags": record.capability_tags,
        "allowed_roles": record.allowed_roles,
        "allowed_desks": record.allowed_desks,
        "health_status": record.health_status,
        "quota_status": record.quota_status,
        "auth_refs": record.auth_refs,
    }


def _llm_provider_health_snapshot_summary(record: LLMProviderHealthSnapshotRecord) -> dict[str, Any]:
    return {
        "snapshot_ref": record.snapshot_ref,
        "provider_id": record.provider_id,
        "auth_ref": record.auth_ref,
        "checked_at": record.checked_at,
        "checker_ref": record.checker_ref,
        "health_status": record.health_status,
        "quota_status": record.quota_status,
        "latency_ms": record.latency_ms,
        "response_hash": record.response_hash,
        "capability_refs": record.capability_refs,
        "evidence_refs": record.evidence_refs,
        "error_code": record.error_code,
        "snapshot_hash": record.snapshot_hash,
    }


def _credential_pool_summary(record: LLMCredentialPoolRecord) -> dict[str, Any]:
    return {
        "pool_id": record.pool_id,
        "provider_id": record.provider_id,
        "auth_refs": record.auth_refs,
        "priority": record.priority,
        "rotation_policy": record.rotation_policy,
        "fallback_policy": record.fallback_policy,
        "owner": record.owner,
        "revoked_refs": record.revoked_refs,
    }


def _routing_policy_summary(record: ModelRoutingPolicyRecord) -> dict[str, Any]:
    return {
        "routing_policy_id": record.routing_policy_id,
        "role_agent": record.role_agent,
        "desk": record.desk,
        "task_type": record.task_type,
        "allowed_providers": record.allowed_providers,
        "allowed_models": record.allowed_models,
        "credential_pool_ref": record.credential_pool_ref,
        "replay_requirement": record.replay_requirement,
    }


def _model_governance_raw_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("passport") if isinstance(payload.get("passport"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="passport payload must be an object")
    return raw


def _model_governance_change_events(payload: dict[str, Any]) -> tuple[str, ...]:
    raw = payload.get("change_events")
    if raw in (None, "", [], ()):
        return ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(value) for value in raw)
    return (str(raw),)


def _model_passport_summary(passport: Any) -> dict[str, Any]:
    return {
        "passport_id": passport.passport_id,
        "model_version_ref": passport.model_version_ref,
        "training_run_ref": passport.training_run_ref,
        "model_risk_tier": getattr(passport.model_risk_tier, "value", passport.model_risk_tier),
        "target_runtime": getattr(passport.target_runtime, "value", passport.target_runtime),
        "artifact_refs": [artifact.artifact_ref for artifact in passport.artifact_manifest],
        "validation_dossier_ref": passport.validation_dossier_ref,
        "recertification_records": passport.recertification_records,
    }


def _model_monitoring_profile_summary(profile: ModelMonitoringProfile) -> dict[str, Any]:
    return {
        "monitoring_profile_id": profile.monitoring_profile_id,
        "model_version_ref": profile.model_version_ref,
        "model_passport_ref": profile.model_passport_ref,
        "metric_refs": profile.metric_refs,
        "schedule_ref": profile.schedule_ref,
        "alert_policy_ref": profile.alert_policy_ref,
        "drift_signal_refs": profile.drift_signal_refs,
        "performance_threshold_refs": profile.performance_threshold_refs,
        "recertification_trigger_refs": profile.recertification_trigger_refs,
        "runtime": getattr(profile.runtime, "value", profile.runtime),
        "owner": profile.owner,
    }


def _model_recertification_summary(record: ModelRecertificationRecord) -> dict[str, Any]:
    return {
        "recertification_record_id": record.recertification_record_id,
        "model_version_ref": record.model_version_ref,
        "model_passport_ref": record.model_passport_ref,
        "trigger": getattr(record.trigger, "value", record.trigger),
        "change_event_ref": record.change_event_ref,
        "evidence_refs": record.evidence_refs,
        "decision": record.decision,
        "recorded_by": record.recorded_by,
    }


def _model_artifact_inspection_summary(record: ModelArtifactInspectionRecord) -> dict[str, Any]:
    return {
        "artifact_inspection_record_id": record.artifact_inspection_record_id,
        "model_version_ref": record.model_version_ref,
        "model_passport_ref": record.model_passport_ref,
        "artifact_ref": record.artifact_ref,
        "inspection_ref": record.inspection_ref,
        "artifact_hash": record.artifact_hash,
        "inspection_status": record.inspection_status,
        "inspection_mode": record.inspection_mode,
        "inspector_ref": record.inspector_ref,
        "checks": record.checks,
        "limitations": record.limitations,
        "recorded_by": record.recorded_by,
    }


def _model_serving_invocation_summary(record: ModelServingInvocationRecord) -> dict[str, Any]:
    return {
        "serving_invocation_id": record.serving_invocation_id,
        "model_version_ref": record.model_version_ref,
        "model_passport_ref": record.model_passport_ref,
        "artifact_inspection_ref": record.artifact_inspection_ref,
        "monitoring_profile_ref": record.monitoring_profile_ref,
        "feature_refs": record.feature_refs,
        "row_count": record.row_count,
        "request_hash": record.request_hash,
        "prediction_hash": record.prediction_hash,
        "runtime": getattr(record.runtime, "value", record.runtime),
        "recorded_by": record.recorded_by,
    }


def _signal_validation_summary(record: SignalPerformanceValidationRecord) -> dict[str, Any]:
    return {
        "validation_id": record.validation_id,
        "signal_ref": record.signal_ref,
        "validation_dataset_ref": record.validation_dataset_ref,
        "evaluation_window_ref": record.evaluation_window_ref,
        "methodology_ref": record.methodology_ref,
        "metric_refs": record.metric_refs,
        "performance_summary_ref": record.performance_summary_ref,
        "leakage_check_ref": record.leakage_check_ref,
        "regime_check_ref": record.regime_check_ref,
        "capacity_check_ref": record.capacity_check_ref,
        "evidence_refs": record.evidence_refs,
        "known_limits_refs": record.known_limits_refs,
        "verdict": getattr(record.verdict, "value", record.verdict),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _execution_order_intent_summary(record: ExecutionOrderIntentRecord) -> dict[str, Any]:
    return {
        "order_intent_ref": record.order_intent_ref,
        "source_portfolio_ref": record.source_portfolio_ref,
        "strategy_book_ref": record.strategy_book_ref,
        "signal_ref": record.signal_ref,
        "signal_validation_ref": record.signal_validation_ref,
        "market_data_use_validation_ref": record.market_data_use_validation_ref,
        "execution_policy_ref": record.execution_policy_ref,
        "risk_policy_ref": record.risk_policy_ref,
        "runtime": getattr(record.runtime, "value", record.runtime),
        "asset_class": record.asset_class,
        "instrument_ref": record.instrument_ref,
        "side": record.side,
        "order_type": record.order_type,
        "venue_ref": record.venue_ref,
        "quantity_ref": record.quantity_ref,
        "notional_ref": record.notional_ref,
        "price_ref": record.price_ref,
        "time_in_force_ref": record.time_in_force_ref,
        "permission_gate_ref": record.permission_gate_ref,
        "order_guard_ref": record.order_guard_ref,
        "idempotency_key": record.idempotency_key,
        "audit_record_ref": record.audit_record_ref,
        "kill_switch_ref": record.kill_switch_ref,
        "secret_ref": record.secret_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "failure_mode_refs": record.failure_mode_refs,
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _execution_order_materialization_summary(record: ExecutionOrderMaterializationRecord) -> dict[str, Any]:
    return {
        "materialization_ref": record.materialization_ref,
        "order_intent_ref": record.order_intent_ref,
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "materializer_ref": record.materializer_ref,
        "materialization_mode": record.materialization_mode,
        "materialization_status": record.materialization_status,
        "permission_gate_ref": record.permission_gate_ref,
        "order_guard_ref": record.order_guard_ref,
        "idempotency_key": record.idempotency_key,
        "audit_record_ref": record.audit_record_ref,
        "order_schema_ref": record.order_schema_ref,
        "order_payload_hash": record.order_payload_hash,
        "quantity_resolution_ref": record.quantity_resolution_ref,
        "notional_resolution_ref": record.notional_resolution_ref,
        "price_resolution_ref": record.price_resolution_ref,
        "time_in_force_resolution_ref": record.time_in_force_resolution_ref,
        "market_snapshot_ref": record.market_snapshot_ref,
        "risk_check_ref": record.risk_check_ref,
        "kill_switch_ref": record.kill_switch_ref,
        "secret_ref": record.secret_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "materialize_enabled": record.materialize_enabled,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _execution_venue_connectivity_check_summary(record: ExecutionVenueConnectivityCheckRecord) -> dict[str, Any]:
    return {
        "venue_connectivity_check_ref": record.venue_connectivity_check_ref,
        "order_intent_ref": record.order_intent_ref,
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "venue_ref": record.venue_ref,
        "guarded_venue_ref": record.guarded_venue_ref,
        "runtime": record.runtime,
        "asset_class": record.asset_class,
        "instrument_ref": record.instrument_ref,
        "connectivity_status": record.connectivity_status,
        "checker_ref": record.checker_ref,
        "permission_gate_ref": record.permission_gate_ref,
        "order_guard_ref": record.order_guard_ref,
        "idempotency_key": record.idempotency_key,
        "audit_record_ref": record.audit_record_ref,
        "credential_check_ref": record.credential_check_ref,
        "ip_allowlist_ref": record.ip_allowlist_ref,
        "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
        "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
        "health_check_ref": record.health_check_ref,
        "rate_limit_ref": record.rate_limit_ref,
        "sandbox_proof_ref": record.sandbox_proof_ref,
        "connectivity_check_hash": record.connectivity_check_hash,
        "kill_switch_ref": record.kill_switch_ref,
        "secret_ref": record.secret_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _execution_venue_safety_attestation_summary(record: ExecutionVenueSafetyAttestationRecord) -> dict[str, Any]:
    return {
        "venue_safety_attestation_ref": record.venue_safety_attestation_ref,
        "order_intent_ref": record.order_intent_ref,
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "venue_ref": record.venue_ref,
        "guarded_venue_ref": record.guarded_venue_ref,
        "runtime": record.runtime,
        "asset_class": record.asset_class,
        "instrument_ref": record.instrument_ref,
        "attestation_status": record.attestation_status,
        "permission_gate_ref": record.permission_gate_ref,
        "order_guard_ref": record.order_guard_ref,
        "idempotency_key": record.idempotency_key,
        "audit_record_ref": record.audit_record_ref,
        "credential_check_ref": record.credential_check_ref,
        "ip_allowlist_ref": record.ip_allowlist_ref,
        "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
        "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
        "health_check_ref": record.health_check_ref,
        "rate_limit_ref": record.rate_limit_ref,
        "venue_connectivity_check_ref": record.venue_connectivity_check_ref,
        "sandbox_proof_ref": record.sandbox_proof_ref,
        "kill_switch_ref": record.kill_switch_ref,
        "secret_ref": record.secret_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _execution_venue_capability_summary(record: ExecutionVenueCapabilityRecord) -> dict[str, Any]:
    return {
        "venue_capability_ref": record.venue_capability_ref,
        "order_intent_ref": record.order_intent_ref,
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "venue_ref": record.venue_ref,
        "guarded_venue_ref": record.guarded_venue_ref,
        "submitter_ref": record.submitter_ref,
        "runtime": record.runtime,
        "asset_class": record.asset_class,
        "instrument_ref": record.instrument_ref,
        "capability_status": record.capability_status,
        "can_submit_orders": record.can_submit_orders,
        "permission_gate_ref": record.permission_gate_ref,
        "order_guard_ref": record.order_guard_ref,
        "idempotency_key": record.idempotency_key,
        "audit_record_ref": record.audit_record_ref,
        "venue_safety_attestation_ref": record.venue_safety_attestation_ref,
        "credential_check_ref": record.credential_check_ref,
        "ip_allowlist_ref": record.ip_allowlist_ref,
        "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
        "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
        "health_check_ref": record.health_check_ref,
        "rate_limit_ref": record.rate_limit_ref,
        "sandbox_proof_ref": record.sandbox_proof_ref,
        "kill_switch_ref": record.kill_switch_ref,
        "secret_ref": record.secret_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _execution_submit_request_summary(record: ExecutionSubmitRequestRecord) -> dict[str, Any]:
    return {
        "submit_request_ref": record.submit_request_ref,
        "order_intent_ref": record.order_intent_ref,
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "order_materialization_ref": record.order_materialization_ref,
        "venue_capability_ref": record.venue_capability_ref,
        "submitter_ref": record.submitter_ref,
        "guarded_venue_ref": record.guarded_venue_ref,
        "venue_ref": record.venue_ref,
        "submit_request_mode": record.submit_request_mode,
        "submit_request_status": record.submit_request_status,
        "permission_gate_ref": record.permission_gate_ref,
        "order_guard_ref": record.order_guard_ref,
        "idempotency_key": record.idempotency_key,
        "audit_record_ref": record.audit_record_ref,
        "order_schema_ref": record.order_schema_ref,
        "order_payload_hash": record.order_payload_hash,
        "submit_request_schema_ref": record.submit_request_schema_ref,
        "submit_request_hash": record.submit_request_hash,
        "client_order_ref_hash": record.client_order_ref_hash,
        "kill_switch_ref": record.kill_switch_ref,
        "secret_ref": record.secret_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _execution_order_submission_summary(record: ExecutionOrderSubmissionRecord) -> dict[str, Any]:
    return {
        "submission_ref": record.submission_ref,
        "order_intent_ref": record.order_intent_ref,
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "submitter_ref": record.submitter_ref,
        "guarded_venue_ref": record.guarded_venue_ref,
        "venue_ref": record.venue_ref,
        "submission_mode": record.submission_mode,
        "permission_gate_ref": record.permission_gate_ref,
        "order_guard_ref": record.order_guard_ref,
        "idempotency_key": record.idempotency_key,
        "audit_record_ref": record.audit_record_ref,
        "kill_switch_ref": record.kill_switch_ref,
        "secret_ref": record.secret_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "submit_enabled": record.submit_enabled,
        "order_materialization_ref": record.order_materialization_ref,
        "venue_capability_ref": record.venue_capability_ref,
        "submit_request_ref": record.submit_request_ref,
        "submission_status": record.submission_status,
        "venue_order_ref": record.venue_order_ref,
        "ack_ref": record.ack_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


_ORDER_INTENT_FORBIDDEN_RAW_FIELDS = {
    "api_key",
    "client_order_id",
    "commission",
    "fill_price",
    "filled_qty",
    "notional",
    "order",
    "password",
    "payload",
    "price",
    "quantity",
    "raw_ack",
    "raw_event",
    "raw_execution_report",
    "raw_fill",
    "raw_order",
    "raw_payload",
    "secret",
    "token",
}


def _runtime_status_from_order_intent(record: ExecutionOrderIntentRecord) -> RuntimeStatus:
    runtime = str(getattr(record.runtime, "value", record.runtime) or RuntimeStatus.OFFLINE.value)
    try:
        return RuntimeStatus(runtime)
    except ValueError:
        return RuntimeStatus.OFFLINE


def _runtime_status_from_value(value: Any) -> RuntimeStatus:
    runtime = str(getattr(value, "value", value) or RuntimeStatus.OFFLINE.value)
    try:
        return RuntimeStatus(runtime)
    except ValueError:
        return RuntimeStatus.OFFLINE


def _record_execution_order_intent_qro(
    record: ExecutionOrderIntentRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    runtime_status = _runtime_status_from_order_intent(record)
    evidence_refs = tuple(
        ref
        for ref in (
            record.order_intent_ref,
            record.source_portfolio_ref,
            record.strategy_book_ref,
            record.signal_ref,
            record.signal_validation_ref,
            record.market_data_use_validation_ref,
            record.execution_policy_ref,
            record.risk_policy_ref,
            record.audit_record_ref,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.order_intent",
            record.order_intent_ref,
            record.source_portfolio_ref,
            record.strategy_book_ref,
            record.signal_ref,
            record.signal_validation_ref,
            record.market_data_use_validation_ref,
            record.execution_policy_ref,
            record.risk_policy_ref,
            record.instrument_ref,
        )
        if ref
    )
    implementation_hash = "execution_order_intent:" + content_hash(
        {
            "order_intent_ref": record.order_intent_ref,
            "source_portfolio_ref": record.source_portfolio_ref,
            "strategy_book_ref": record.strategy_book_ref,
            "signal_ref": record.signal_ref,
            "signal_validation_ref": record.signal_validation_ref,
            "market_data_use_validation_ref": record.market_data_use_validation_ref,
            "execution_policy_ref": record.execution_policy_ref,
            "risk_policy_ref": record.risk_policy_ref,
            "instrument_ref": record.instrument_ref,
            "side": record.side,
            "order_type": record.order_type,
            "runtime": runtime_status.value,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "order_intent_ref": record.order_intent_ref,
            "source_portfolio_ref": record.source_portfolio_ref,
            "strategy_book_ref": record.strategy_book_ref,
            "signal_ref": record.signal_ref,
            "signal_validation_ref": record.signal_validation_ref,
            "market_data_use_validation_ref": record.market_data_use_validation_ref,
            "runtime": runtime_status.value,
            "asset_class": record.asset_class,
            "instrument_ref": record.instrument_ref,
            "side": record.side,
            "order_type": record.order_type,
        },
        output_contract={
            "status": "order_intent_recorded",
            "execution_policy_ref": record.execution_policy_ref,
            "risk_policy_ref": record.risk_policy_ref,
            "venue_ref": record.venue_ref,
            "market_data_use_validation_ref": record.market_data_use_validation_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "kill_switch_ref": record.kill_switch_ref,
            "secret_ref": record.secret_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
            "place_order_called": False,
        },
        market=record.asset_class or "unspecified",
        universe=record.instrument_ref or "unspecified",
        horizon=record.time_in_force_ref or "order_intent",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records a typed execution order intent only; it does not place an order or move funds.",
        ),
        known_limits=(
            "Broker/order emission, venue acknowledgment, fill reconciliation, and live runtime transition remain separate gates.",
        ),
        failure_modes=(
            "Missing downstream OrderGuard wiring, stale policy refs, or venue failures can still block any later order emission.",
        ),
        validation_plan=(
            "Bind order intent QRO to guarded order-emission proof before claiming runtime execution.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=runtime_status,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.order_intent:user_manual",
        allowed_environment=runtime_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.order_intents",
        pass_name="api_execution_order_intent_qro_to_execution_policy_ir",
        record_ref=record.order_intent_ref,
        permission_ref="execution.order_intent:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.signal_validation_ref, record.market_data_use_validation_ref),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _runtime_promotion_summary(record: RuntimePromotionRecord) -> dict[str, Any]:
    return {
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "request_ref": record.request_ref,
        "asset_class": record.asset_class,
        "source_runtime": getattr(record.source_runtime, "value", record.source_runtime),
        "target_runtime": getattr(record.target_runtime, "value", record.target_runtime),
        "paper_run_ref": record.paper_run_ref,
        "testnet_run_ref": record.testnet_run_ref,
        "approval_ref": record.approval_ref,
        "permission_gate_ref": record.permission_gate_ref,
        "order_guard_ref": record.order_guard_ref,
        "audit_record_ref": record.audit_record_ref,
        "kill_switch_ref": record.kill_switch_ref,
        "secret_ref": record.secret_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _record_runtime_promotion_qro(
    record: RuntimePromotionRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    target_status = _runtime_status_from_value(record.target_runtime)
    evidence_refs = tuple(
        ref
        for ref in (
            record.runtime_promotion_ref,
            record.request_ref,
            record.paper_run_ref,
            record.testnet_run_ref,
            record.approval_ref,
            record.permission_gate_ref,
            record.order_guard_ref,
            record.audit_record_ref,
            record.kill_switch_ref,
            record.responsibility_boundary_ref,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.runtime_promotion",
            record.runtime_promotion_ref,
            record.request_ref,
            str(getattr(record.source_runtime, "value", record.source_runtime)),
            str(getattr(record.target_runtime, "value", record.target_runtime)),
            record.paper_run_ref,
            record.testnet_run_ref,
            record.approval_ref,
        )
        if ref
    )
    implementation_hash = "runtime_promotion:" + content_hash(
        {
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "request_ref": record.request_ref,
            "asset_class": record.asset_class,
            "source_runtime": getattr(record.source_runtime, "value", record.source_runtime),
            "target_runtime": getattr(record.target_runtime, "value", record.target_runtime),
            "paper_run_ref": record.paper_run_ref,
            "testnet_run_ref": record.testnet_run_ref,
            "approval_ref": record.approval_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "kill_switch_ref": record.kill_switch_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "request_ref": record.request_ref,
            "asset_class": record.asset_class,
            "source_runtime": getattr(record.source_runtime, "value", record.source_runtime),
            "target_runtime": getattr(record.target_runtime, "value", record.target_runtime),
            "mock_profile": record.mock_profile,
        },
        output_contract={
            "status": "runtime_promotion_recorded",
            "paper_run_ref": record.paper_run_ref,
            "testnet_run_ref": record.testnet_run_ref,
            "approval_ref": record.approval_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "kill_switch_ref": record.kill_switch_ref,
            "secret_ref": record.secret_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
            "runtime_transition_recorded": True,
            "place_order_called": False,
            "venue_call_called": False,
        },
        market=record.asset_class or "unspecified",
        universe=record.asset_class or "unspecified",
        horizon=f"{getattr(record.source_runtime, 'value', record.source_runtime)}->{getattr(record.target_runtime, 'value', record.target_runtime)}",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records a governed runtime promotion decision only; it does not call a venue or place an order.",
        ),
        known_limits=(
            "Broker connectivity, order emission, fill reconciliation, and live exchange behavior remain separate proof steps.",
        ),
        failure_modes=(
            "Permission, OrderGuard, secret, kill-switch, venue, or user-responsibility refs can still block later execution.",
        ),
        validation_plan=(
            "Bind runtime promotions to order-intent, guarded emission, venue acknowledgment, and monitor evidence before execution claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=target_status,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.runtime_promotion:user_manual",
        allowed_environment=target_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.runtime_promotions",
        pass_name="api_execution_runtime_promotion_qro_to_execution_policy_ir",
        record_ref=record.runtime_promotion_ref,
        permission_ref="execution.runtime_promotion:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.approval_ref, record.permission_gate_ref, record.order_guard_ref),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_execution_order_materialization_qro(
    record: ExecutionOrderMaterializationRecord,
    order_intent: ExecutionOrderIntentRecord,
    runtime_promotion: RuntimePromotionRecord,
    *,
    actor: str,
    materializer_result: dict[str, Any],
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    runtime_status = _runtime_status_from_value(record.materialization_mode)
    materializer_called = bool(materializer_result.get("materializer_called", False))
    evidence_refs = tuple(
        ref
        for ref in (
            record.materialization_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.materializer_ref,
            record.permission_gate_ref,
            record.order_guard_ref,
            record.audit_record_ref,
            record.order_schema_ref,
            record.order_payload_hash,
            record.quantity_resolution_ref,
            record.notional_resolution_ref,
            record.price_resolution_ref,
            record.time_in_force_resolution_ref,
            record.market_snapshot_ref,
            record.risk_check_ref,
            record.kill_switch_ref,
            record.secret_ref,
            record.responsibility_boundary_ref,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.order_materialization",
            record.materialization_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            order_intent.instrument_ref,
            runtime_promotion.request_ref,
            record.materialization_mode,
            record.materialization_status,
        )
        if ref
    )
    implementation_hash = "execution_order_materialization:" + content_hash(
        {
            "materialization_ref": record.materialization_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "materializer_ref": record.materializer_ref,
            "materialization_mode": record.materialization_mode,
            "materialization_status": record.materialization_status,
            "materialize_enabled": record.materialize_enabled,
            "order_schema_ref": record.order_schema_ref,
            "order_payload_hash": record.order_payload_hash,
            "quantity_resolution_ref": record.quantity_resolution_ref,
            "notional_resolution_ref": record.notional_resolution_ref,
            "price_resolution_ref": record.price_resolution_ref,
            "market_snapshot_ref": record.market_snapshot_ref,
            "risk_check_ref": record.risk_check_ref,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "materialization_ref": record.materialization_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "materializer_ref": record.materializer_ref,
            "materialization_mode": record.materialization_mode,
            "materialize_enabled": record.materialize_enabled,
        },
        output_contract={
            "status": "execution_order_materialization_recorded",
            "materialization_status": record.materialization_status,
            "materializer_ref": record.materializer_ref,
            "materializer_called": materializer_called,
            "record_only": not record.materialize_enabled,
            "api_place_order_called": False,
            "api_venue_call_called": False,
            "order_schema_ref": record.order_schema_ref,
            "order_payload_hash": record.order_payload_hash,
            "quantity_resolution_ref": record.quantity_resolution_ref,
            "notional_resolution_ref": record.notional_resolution_ref,
            "price_resolution_ref": record.price_resolution_ref,
            "time_in_force_resolution_ref": record.time_in_force_resolution_ref,
            "market_snapshot_ref": record.market_snapshot_ref,
            "risk_check_ref": record.risk_check_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "kill_switch_ref": record.kill_switch_ref,
            "secret_ref": record.secret_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
        },
        market=order_intent.asset_class or "execution",
        universe=order_intent.instrument_ref or record.order_intent_ref or "unspecified",
        horizon=record.materialization_mode or "order_materialization",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records order-materialization refs and payload hash only; it does not persist raw order material.",
        ),
        known_limits=(
            "Default runtime has no materializer; venue-native payload construction and submission require injected guarded adapters.",
        ),
        failure_modes=(
            "Disabled materializer, stale guard refs, unresolved sizing/price refs, risk-check failure, or kill-switch state can block submission.",
        ),
        validation_plan=(
            "Require materialized hash refs before submit_enabled order submission, then bind ack/fill venue events and reconciliation.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=runtime_status,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.order_materialization:user_manual",
        allowed_environment=runtime_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.order_materializations",
        pass_name="api_execution_order_materialization_qro_to_execution_policy_ir",
        record_ref=record.materialization_ref,
        permission_ref="execution.order_materialization:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.order_intent_ref, record.runtime_promotion_ref, record.order_payload_hash),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_execution_venue_connectivity_check_qro(
    record: ExecutionVenueConnectivityCheckRecord,
    order_intent: ExecutionOrderIntentRecord,
    runtime_promotion: RuntimePromotionRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    runtime_status = _runtime_status_from_value(record.runtime)
    evidence_refs = tuple(
        ref
        for ref in (
            record.venue_connectivity_check_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.venue_ref,
            record.guarded_venue_ref,
            record.checker_ref,
            record.permission_gate_ref,
            record.order_guard_ref,
            record.idempotency_key,
            record.audit_record_ref,
            record.venue_connectivity_check_ref,
            record.credential_check_ref,
            record.ip_allowlist_ref,
            record.withdrawal_disabled_ref,
            record.hmac_replay_protection_ref,
            record.health_check_ref,
            record.rate_limit_ref,
            record.sandbox_proof_ref,
            record.connectivity_check_hash,
            record.kill_switch_ref,
            record.secret_ref,
            record.responsibility_boundary_ref,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.venue_connectivity_check",
            record.venue_connectivity_check_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            order_intent.instrument_ref,
            runtime_promotion.request_ref,
            record.venue_ref,
            record.guarded_venue_ref,
            record.checker_ref,
            record.runtime,
            record.connectivity_status,
        )
        if ref
    )
    implementation_hash = "execution_venue_connectivity_check:" + content_hash(
        {
            "venue_connectivity_check_ref": record.venue_connectivity_check_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "runtime": record.runtime,
            "asset_class": record.asset_class,
            "connectivity_status": record.connectivity_status,
            "checker_ref": record.checker_ref,
            "credential_check_ref": record.credential_check_ref,
            "ip_allowlist_ref": record.ip_allowlist_ref,
            "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
            "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
            "health_check_ref": record.health_check_ref,
            "rate_limit_ref": record.rate_limit_ref,
            "connectivity_check_hash": record.connectivity_check_hash,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "venue_connectivity_check_ref": record.venue_connectivity_check_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "checker_ref": record.checker_ref,
            "runtime": record.runtime,
        },
        output_contract={
            "status": "execution_venue_connectivity_check_recorded",
            "connectivity_status": record.connectivity_status,
            "record_only": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "checker_ref": record.checker_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "credential_check_ref": record.credential_check_ref,
            "ip_allowlist_ref": record.ip_allowlist_ref,
            "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
            "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
            "health_check_ref": record.health_check_ref,
            "rate_limit_ref": record.rate_limit_ref,
            "sandbox_proof_ref": record.sandbox_proof_ref,
            "connectivity_check_hash": record.connectivity_check_hash,
            "kill_switch_ref": record.kill_switch_ref,
            "secret_ref": record.secret_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
        },
        market=record.asset_class or order_intent.asset_class or "execution",
        universe=record.instrument_ref or order_intent.instrument_ref or record.venue_ref or "unspecified",
        horizon=record.runtime or "venue_connectivity_check",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records guarded venue connectivity check refs only; it does not prove an emitted venue order.",
        ),
        known_limits=(
            "Default runtime has no real checker; real credential and venue connectivity require an injected checker and fresh evidence.",
        ),
        failure_modes=(
            "Missing credential/IP/withdrawal/HMAC/health/rate-limit refs or stale secret and kill-switch refs block safety attestation.",
        ),
        validation_plan=(
            "Require accepted connectivity check before accepted venue safety attestation and ready venue capability.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=runtime_status,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.venue_connectivity_check:user_manual",
        allowed_environment=runtime_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.venue_connectivity_checks",
        pass_name="api_execution_venue_connectivity_check_qro_to_execution_policy_ir",
        record_ref=record.venue_connectivity_check_ref,
        permission_ref="execution.venue_connectivity_check:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.credential_check_ref, record.health_check_ref, record.connectivity_check_hash),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_execution_venue_safety_attestation_qro(
    record: ExecutionVenueSafetyAttestationRecord,
    order_intent: ExecutionOrderIntentRecord,
    runtime_promotion: RuntimePromotionRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    runtime_status = _runtime_status_from_value(record.runtime)
    evidence_refs = tuple(
        ref
        for ref in (
            record.venue_safety_attestation_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.venue_ref,
            record.guarded_venue_ref,
            record.permission_gate_ref,
            record.order_guard_ref,
            record.idempotency_key,
            record.audit_record_ref,
            record.venue_safety_attestation_ref,
            record.credential_check_ref,
            record.ip_allowlist_ref,
            record.withdrawal_disabled_ref,
            record.hmac_replay_protection_ref,
            record.health_check_ref,
            record.rate_limit_ref,
            record.sandbox_proof_ref,
            record.kill_switch_ref,
            record.secret_ref,
            record.responsibility_boundary_ref,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.venue_safety_attestation",
            record.venue_safety_attestation_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            order_intent.instrument_ref,
            runtime_promotion.request_ref,
            record.venue_ref,
            record.guarded_venue_ref,
            record.runtime,
            record.attestation_status,
            record.venue_connectivity_check_ref,
        )
        if ref
    )
    implementation_hash = "execution_venue_safety_attestation:" + content_hash(
        {
            "venue_safety_attestation_ref": record.venue_safety_attestation_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "runtime": record.runtime,
            "asset_class": record.asset_class,
            "attestation_status": record.attestation_status,
            "venue_connectivity_check_ref": record.venue_connectivity_check_ref,
            "credential_check_ref": record.credential_check_ref,
            "ip_allowlist_ref": record.ip_allowlist_ref,
            "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
            "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
            "health_check_ref": record.health_check_ref,
            "rate_limit_ref": record.rate_limit_ref,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "venue_safety_attestation_ref": record.venue_safety_attestation_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "runtime": record.runtime,
            "venue_connectivity_check_ref": record.venue_connectivity_check_ref,
        },
        output_contract={
            "status": "execution_venue_safety_attestation_recorded",
            "attestation_status": record.attestation_status,
            "venue_connectivity_check_ref": record.venue_connectivity_check_ref,
            "record_only": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "credential_check_ref": record.credential_check_ref,
            "ip_allowlist_ref": record.ip_allowlist_ref,
            "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
            "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
            "health_check_ref": record.health_check_ref,
            "rate_limit_ref": record.rate_limit_ref,
            "sandbox_proof_ref": record.sandbox_proof_ref,
            "kill_switch_ref": record.kill_switch_ref,
            "secret_ref": record.secret_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
        },
        market=record.asset_class or order_intent.asset_class or "execution",
        universe=record.instrument_ref or order_intent.instrument_ref or record.venue_ref or "unspecified",
        horizon=record.runtime or "venue_safety_attestation",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records safety-attestation refs only; it is not proof of an emitted venue order.",
        ),
        known_limits=(
            "Attestation refs can become stale when credentials, IP allowlists, venue permissions, or health state change.",
        ),
        failure_modes=(
            "Missing credential, allowlist, withdrawal-disable, HMAC/replay, health, rate-limit, or guard refs block ready capability.",
        ),
        validation_plan=(
            "Require accepted safety attestation before ready venue capability and guarded submission.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=runtime_status,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.venue_safety_attestation:user_manual",
        allowed_environment=runtime_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.venue_safety_attestations",
        pass_name="api_execution_venue_safety_attestation_qro_to_execution_policy_ir",
        record_ref=record.venue_safety_attestation_ref,
        permission_ref="execution.venue_safety_attestation:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.venue_connectivity_check_ref, record.health_check_ref, record.hmac_replay_protection_ref),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_execution_venue_capability_qro(
    record: ExecutionVenueCapabilityRecord,
    order_intent: ExecutionOrderIntentRecord,
    runtime_promotion: RuntimePromotionRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    runtime_status = _runtime_status_from_value(record.runtime)
    evidence_refs = tuple(
        ref
        for ref in (
            record.venue_capability_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.venue_ref,
            record.guarded_venue_ref,
            record.submitter_ref,
            record.permission_gate_ref,
            record.order_guard_ref,
            record.idempotency_key,
            record.audit_record_ref,
            record.credential_check_ref,
            record.ip_allowlist_ref,
            record.withdrawal_disabled_ref,
            record.hmac_replay_protection_ref,
            record.health_check_ref,
            record.rate_limit_ref,
            record.sandbox_proof_ref,
            record.kill_switch_ref,
            record.secret_ref,
            record.responsibility_boundary_ref,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.venue_capability",
            record.venue_capability_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            order_intent.instrument_ref,
            runtime_promotion.request_ref,
            record.venue_ref,
            record.guarded_venue_ref,
            record.submitter_ref,
            record.runtime,
            record.capability_status,
        )
        if ref
    )
    implementation_hash = "execution_venue_capability:" + content_hash(
        {
            "venue_capability_ref": record.venue_capability_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "submitter_ref": record.submitter_ref,
            "runtime": record.runtime,
            "asset_class": record.asset_class,
            "capability_status": record.capability_status,
            "can_submit_orders": record.can_submit_orders,
            "venue_safety_attestation_ref": record.venue_safety_attestation_ref,
            "credential_check_ref": record.credential_check_ref,
            "ip_allowlist_ref": record.ip_allowlist_ref,
            "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
            "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
            "health_check_ref": record.health_check_ref,
            "rate_limit_ref": record.rate_limit_ref,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "venue_capability_ref": record.venue_capability_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "submitter_ref": record.submitter_ref,
            "runtime": record.runtime,
            "venue_safety_attestation_ref": record.venue_safety_attestation_ref,
        },
        output_contract={
            "status": "execution_venue_capability_recorded",
            "capability_status": record.capability_status,
            "can_submit_orders": record.can_submit_orders,
            "record_only": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
            "venue_ref": record.venue_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "submitter_ref": record.submitter_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "venue_safety_attestation_ref": record.venue_safety_attestation_ref,
            "credential_check_ref": record.credential_check_ref,
            "ip_allowlist_ref": record.ip_allowlist_ref,
            "withdrawal_disabled_ref": record.withdrawal_disabled_ref,
            "hmac_replay_protection_ref": record.hmac_replay_protection_ref,
            "health_check_ref": record.health_check_ref,
            "rate_limit_ref": record.rate_limit_ref,
            "sandbox_proof_ref": record.sandbox_proof_ref,
            "kill_switch_ref": record.kill_switch_ref,
            "secret_ref": record.secret_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
        },
        market=record.asset_class or order_intent.asset_class or "execution",
        universe=record.instrument_ref or order_intent.instrument_ref or record.venue_ref or "unspecified",
        horizon=record.runtime or "venue_capability",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records guarded venue capability refs only; it is not proof of an emitted venue order.",
        ),
        known_limits=(
            "Credential connectivity, venue outage, permission drift, and kill-switch state can change after this readiness record.",
        ),
        failure_modes=(
            "Missing credential check, IP allowlist, withdrawal-disable proof, HMAC/replay protection, health check, or stale guard refs block submission.",
        ),
        validation_plan=(
            "Require this ready capability ref plus materialized order payload hash before submit_enabled order submission.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=runtime_status,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.venue_capability:user_manual",
        allowed_environment=runtime_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.venue_capabilities",
        pass_name="api_execution_venue_capability_qro_to_execution_policy_ir",
        record_ref=record.venue_capability_ref,
        permission_ref="execution.venue_capability:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.venue_safety_attestation_ref, record.capability_status, record.submitter_ref),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_execution_submit_request_qro(
    record: ExecutionSubmitRequestRecord,
    order_intent: ExecutionOrderIntentRecord,
    runtime_promotion: RuntimePromotionRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    runtime_status = _runtime_status_from_value(record.submit_request_mode)
    evidence_refs = tuple(
        ref
        for ref in (
            record.submit_request_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.order_materialization_ref,
            record.venue_capability_ref,
            record.submitter_ref,
            record.guarded_venue_ref,
            record.venue_ref,
            record.permission_gate_ref,
            record.order_guard_ref,
            record.idempotency_key,
            record.audit_record_ref,
            record.order_schema_ref,
            record.order_payload_hash,
            record.submit_request_schema_ref,
            record.submit_request_hash,
            record.client_order_ref_hash,
            record.kill_switch_ref,
            record.secret_ref,
            record.responsibility_boundary_ref,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.submit_request",
            record.submit_request_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.order_materialization_ref,
            record.venue_capability_ref,
            order_intent.instrument_ref,
            runtime_promotion.request_ref,
            record.venue_ref,
            record.guarded_venue_ref,
            record.submitter_ref,
            record.submit_request_mode,
            record.submit_request_status,
        )
        if ref
    )
    implementation_hash = "execution_submit_request:" + content_hash(
        {
            "submit_request_ref": record.submit_request_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "order_materialization_ref": record.order_materialization_ref,
            "venue_capability_ref": record.venue_capability_ref,
            "submitter_ref": record.submitter_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "venue_ref": record.venue_ref,
            "submit_request_mode": record.submit_request_mode,
            "submit_request_status": record.submit_request_status,
            "order_schema_ref": record.order_schema_ref,
            "order_payload_hash": record.order_payload_hash,
            "submit_request_schema_ref": record.submit_request_schema_ref,
            "submit_request_hash": record.submit_request_hash,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "submit_request_ref": record.submit_request_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "order_materialization_ref": record.order_materialization_ref,
            "venue_capability_ref": record.venue_capability_ref,
            "submitter_ref": record.submitter_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "venue_ref": record.venue_ref,
            "submit_request_mode": record.submit_request_mode,
        },
        output_contract={
            "status": "execution_submit_request_recorded",
            "submit_request_status": record.submit_request_status,
            "record_only": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
            "order_materialization_ref": record.order_materialization_ref,
            "venue_capability_ref": record.venue_capability_ref,
            "submitter_ref": record.submitter_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "venue_ref": record.venue_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "order_schema_ref": record.order_schema_ref,
            "order_payload_hash": record.order_payload_hash,
            "submit_request_schema_ref": record.submit_request_schema_ref,
            "submit_request_hash": record.submit_request_hash,
            "client_order_ref_hash": record.client_order_ref_hash,
            "kill_switch_ref": record.kill_switch_ref,
            "secret_ref": record.secret_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
        },
        market=order_intent.asset_class or "execution",
        universe=order_intent.instrument_ref or record.venue_ref or "unspecified",
        horizon=record.submit_request_mode or "submit_request",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records a refs-only guarded submit request envelope; it is not proof that a venue accepted an order.",
        ),
        known_limits=(
            "Default runtime has no real venue submitter; connectivity, venue permissions, and account state require separate evidence.",
        ),
        failure_modes=(
            "Missing payload hash, stale capability, idempotency conflict, kill-switch state, or disabled submitter can block execution.",
        ),
        validation_plan=(
            "Require this ready submit_request_ref before submit_enabled order submission and then bind ack/fill events to reconciliation.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=runtime_status,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.submit_request:user_manual",
        allowed_environment=runtime_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.submit_requests",
        pass_name="api_execution_submit_request_qro_to_execution_policy_ir",
        record_ref=record.submit_request_ref,
        permission_ref="execution.submit_request:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.order_materialization_ref, record.venue_capability_ref, record.submit_request_hash),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_execution_order_submission_qro(
    record: ExecutionOrderSubmissionRecord,
    order_intent: ExecutionOrderIntentRecord,
    runtime_promotion: RuntimePromotionRecord,
    *,
    actor: str,
    submitter_result: dict[str, Any],
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    runtime_status = _runtime_status_from_value(record.submission_mode)
    submitter_called = bool(submitter_result.get("submitter_called", False))
    api_venue_call_called = bool(submitter_result.get("api_venue_call_called", False))
    evidence_refs = tuple(
        ref
        for ref in (
            record.submission_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.order_materialization_ref,
            record.venue_capability_ref,
            record.submitter_ref,
            record.guarded_venue_ref,
            record.venue_ref,
            record.permission_gate_ref,
            record.order_guard_ref,
            record.audit_record_ref,
            record.kill_switch_ref,
            record.secret_ref,
            record.responsibility_boundary_ref,
            record.submit_request_ref,
            record.venue_order_ref,
            record.ack_ref,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.order_submission",
            record.submission_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.order_materialization_ref,
            record.venue_capability_ref,
            record.submit_request_ref,
            order_intent.instrument_ref,
            runtime_promotion.request_ref,
            record.submission_mode,
            record.submission_status,
        )
        if ref
    )
    implementation_hash = "execution_order_submission:" + content_hash(
        {
            "submission_ref": record.submission_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "order_materialization_ref": record.order_materialization_ref,
            "venue_capability_ref": record.venue_capability_ref,
            "submit_request_ref": record.submit_request_ref,
            "submitter_ref": record.submitter_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "venue_ref": record.venue_ref,
            "submission_mode": record.submission_mode,
            "submission_status": record.submission_status,
            "submit_enabled": record.submit_enabled,
            "ack_ref": record.ack_ref,
            "venue_order_ref": record.venue_order_ref,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "submission_ref": record.submission_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "order_materialization_ref": record.order_materialization_ref,
            "venue_capability_ref": record.venue_capability_ref,
            "submit_request_ref": record.submit_request_ref,
            "submitter_ref": record.submitter_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "venue_ref": record.venue_ref,
            "submission_mode": record.submission_mode,
            "submit_enabled": record.submit_enabled,
        },
        output_contract={
            "status": "execution_order_submission_recorded",
            "submission_status": record.submission_status,
            "submitter_ref": record.submitter_ref,
            "order_materialization_ref": record.order_materialization_ref,
            "venue_capability_ref": record.venue_capability_ref,
            "submit_request_ref": record.submit_request_ref,
            "guarded_venue_ref": record.guarded_venue_ref,
            "venue_ref": record.venue_ref,
            "permission_gate_ref": record.permission_gate_ref,
            "order_guard_ref": record.order_guard_ref,
            "audit_record_ref": record.audit_record_ref,
            "kill_switch_ref": record.kill_switch_ref,
            "secret_ref": record.secret_ref,
            "responsibility_boundary_ref": record.responsibility_boundary_ref,
            "submitter_called": submitter_called,
            "record_only": not record.submit_enabled,
            "api_place_order_called": False,
            "api_venue_call_called": api_venue_call_called,
            "venue_order_ref": record.venue_order_ref,
            "ack_ref": record.ack_ref,
        },
        market=order_intent.asset_class or "execution",
        universe=order_intent.instrument_ref or record.venue_ref or "unspecified",
        horizon=record.submission_mode or "order_submission",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records a guarded submission seam using refs only; the API does not call place_order directly.",
        ),
        known_limits=(
            "Default runtime has no real venue submitter; Binance testnet key connectivity and external venue API behavior need separate proof.",
        ),
        failure_modes=(
            "Disabled submitter, stale guard refs, idempotency conflict, venue rejection, or missing ack evidence can block execution.",
        ),
        validation_plan=(
            "Verify injected submitter evidence, then bind ack/fill venue events and reconciliation before claiming real order emission.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=runtime_status,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.order_submission:user_manual",
        allowed_environment=runtime_status,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.order_submissions",
        pass_name="api_execution_order_submission_qro_to_execution_policy_ir",
        record_ref=record.submission_ref,
        permission_ref="execution.order_submission:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.order_materialization_ref, record.venue_capability_ref, record.submit_request_ref),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _execution_venue_event_summary(record: ExecutionVenueEventRecord) -> dict[str, Any]:
    return {
        "venue_event_ref": record.venue_event_ref,
        "order_intent_ref": record.order_intent_ref,
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "venue_ref": record.venue_ref,
        "event_kind": record.event_kind,
        "status": record.status,
        "venue_order_ref": record.venue_order_ref,
        "client_order_ref": record.client_order_ref,
        "ack_ref": record.ack_ref,
        "fill_ref": record.fill_ref,
        "reconcile_ref": record.reconcile_ref,
        "quantity_ref": record.quantity_ref,
        "price_ref": record.price_ref,
        "fee_ref": record.fee_ref,
        "raw_event_hash": record.raw_event_hash,
        "audit_record_ref": record.audit_record_ref,
        "order_guard_ref": record.order_guard_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _record_execution_venue_event_qro(
    record: ExecutionVenueEventRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in (
            record.venue_event_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.audit_record_ref,
            record.order_guard_ref,
            record.venue_order_ref,
            record.client_order_ref,
            record.ack_ref,
            record.fill_ref,
            record.reconcile_ref,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.venue_event",
            record.venue_event_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.venue_ref,
            record.event_kind,
            record.status,
        )
        if ref
    )
    implementation_hash = "execution_venue_event:" + content_hash(
        {
            "venue_event_ref": record.venue_event_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_ref": record.venue_ref,
            "event_kind": record.event_kind,
            "status": record.status,
            "venue_order_ref": record.venue_order_ref,
            "ack_ref": record.ack_ref,
            "fill_ref": record.fill_ref,
            "reconcile_ref": record.reconcile_ref,
            "raw_event_hash": record.raw_event_hash,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "venue_event_ref": record.venue_event_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_ref": record.venue_ref,
            "event_kind": record.event_kind,
            "status": record.status,
        },
        output_contract={
            "status": "venue_event_recorded",
            "venue_order_ref": record.venue_order_ref,
            "client_order_ref": record.client_order_ref,
            "ack_ref": record.ack_ref,
            "fill_ref": record.fill_ref,
            "reconcile_ref": record.reconcile_ref,
            "quantity_ref": record.quantity_ref,
            "price_ref": record.price_ref,
            "fee_ref": record.fee_ref,
            "raw_event_hash": record.raw_event_hash,
            "audit_record_ref": record.audit_record_ref,
            "order_guard_ref": record.order_guard_ref,
            "record_only": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
        },
        market="execution",
        universe=record.venue_ref or "unspecified",
        horizon=record.event_kind or "venue_event",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records venue event evidence refs only; the API does not call the venue or submit an order.",
        ),
        known_limits=(
            "Venue raw payload, external connector behavior, and account state must be verified through separate evidence refs.",
        ),
        failure_modes=(
            "Missing ack, fill, reconcile, audit, or guard refs can still make execution evidence insufficient.",
        ),
        validation_plan=(
            "Bind venue events to order intent, runtime promotion, guard audit, fills, reconciliation, and monitor evidence before execution claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.venue_event:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.venue_events",
        pass_name="api_execution_venue_event_qro_to_execution_policy_ir",
        record_ref=record.venue_event_ref,
        permission_ref="execution.venue_event:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.ack_ref, record.fill_ref, record.reconcile_ref, record.raw_event_hash),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _execution_reconciliation_summary(record: ExecutionReconciliationRecord) -> dict[str, Any]:
    return {
        "reconciliation_ref": record.reconciliation_ref,
        "order_intent_ref": record.order_intent_ref,
        "runtime_promotion_ref": record.runtime_promotion_ref,
        "venue_order_ref": record.venue_order_ref,
        "event_refs": list(record.event_refs),
        "status": record.status,
        "discrepancy_refs": list(record.discrepancy_refs),
        "action_required": record.action_required,
        "audit_record_ref": record.audit_record_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _record_execution_reconciliation_qro(
    record: ExecutionReconciliationRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in (
            record.reconciliation_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.venue_order_ref,
            record.audit_record_ref,
            *record.event_refs,
            *record.discrepancy_refs,
            *record.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.reconciliation",
            record.reconciliation_ref,
            record.order_intent_ref,
            record.runtime_promotion_ref,
            record.venue_order_ref,
            record.status,
        )
        if ref
    )
    implementation_hash = "execution_reconciliation:" + content_hash(
        {
            "reconciliation_ref": record.reconciliation_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_order_ref": record.venue_order_ref,
            "event_refs": record.event_refs,
            "status": record.status,
            "discrepancy_refs": record.discrepancy_refs,
            "action_required": record.action_required,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "reconciliation_ref": record.reconciliation_ref,
            "order_intent_ref": record.order_intent_ref,
            "runtime_promotion_ref": record.runtime_promotion_ref,
            "venue_order_ref": record.venue_order_ref,
        },
        output_contract={
            "status": "execution_reconciliation_recorded",
            "reconciliation_status": record.status,
            "event_refs": list(record.event_refs),
            "discrepancy_refs": list(record.discrepancy_refs),
            "action_required": record.action_required,
            "audit_record_ref": record.audit_record_ref,
            "record_only": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
        },
        market="execution",
        universe=record.venue_order_ref or record.order_intent_ref,
        horizon="execution_reconciliation",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records reconciliation over already-recorded venue event refs; it does not call a venue or submit an order.",
        ),
        known_limits=(
            "Reconciliation quality depends on upstream venue event evidence and separate connector proofs.",
        ),
        failure_modes=(
            "Missing events, missing reconcile refs, or conflicting terminal events require manual or automated follow-up.",
        ),
        validation_plan=(
            "Route action_required reconciliations into monitor actions, HALT handling, or user-visible remediation before execution claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.reconciliation:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.reconciliations",
        pass_name="api_execution_reconciliation_qro_to_execution_policy_ir",
        record_ref=record.reconciliation_ref,
        permission_ref="execution.reconciliation:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.status, record.audit_record_ref, *record.event_refs),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _execution_reconciliation_action_summary(record: ExecutionReconciliationActionRecord) -> dict[str, Any]:
    return {
        "action_ref": record.action_ref,
        "reconciliation_ref": record.reconciliation_ref,
        "action_kind": record.action_kind,
        "action_status": record.action_status,
        "action_owner_ref": record.action_owner_ref,
        "remediation_ref": record.remediation_ref,
        "halt_plan_ref": record.halt_plan_ref,
        "waiver_ref": record.waiver_ref,
        "audit_record_ref": record.audit_record_ref,
        "evidence_refs": list(record.evidence_refs),
        "recorded_by": record.recorded_by,
        "created_at_utc": record.created_at_utc,
    }


def _record_execution_reconciliation_action_qro(
    action: ExecutionReconciliationActionRecord,
    reconciliation: ExecutionReconciliationRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in (
            action.action_ref,
            action.reconciliation_ref,
            reconciliation.order_intent_ref,
            reconciliation.runtime_promotion_ref,
            reconciliation.venue_order_ref,
            action.action_owner_ref,
            action.remediation_ref,
            action.halt_plan_ref,
            action.waiver_ref,
            action.audit_record_ref,
            *reconciliation.event_refs,
            *reconciliation.discrepancy_refs,
            *action.evidence_refs,
        )
        if ref
    )
    lineage = tuple(
        ref
        for ref in (
            "execution.reconciliation_action",
            action.action_ref,
            action.reconciliation_ref,
            action.action_kind,
            action.action_status,
        )
        if ref
    )
    implementation_hash = "execution_reconciliation_action:" + content_hash(
        {
            "action_ref": action.action_ref,
            "reconciliation_ref": action.reconciliation_ref,
            "action_kind": action.action_kind,
            "action_status": action.action_status,
            "action_owner_ref": action.action_owner_ref,
            "remediation_ref": action.remediation_ref,
            "halt_plan_ref": action.halt_plan_ref,
            "waiver_ref": action.waiver_ref,
            "evidence_refs": action.evidence_refs,
        }
    )
    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner="execution_boundary",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "action_ref": action.action_ref,
            "reconciliation_ref": action.reconciliation_ref,
            "order_intent_ref": reconciliation.order_intent_ref,
            "runtime_promotion_ref": reconciliation.runtime_promotion_ref,
        },
        output_contract={
            "status": "execution_reconciliation_action_recorded",
            "action_kind": action.action_kind,
            "action_status": action.action_status,
            "reconciliation_status": reconciliation.status,
            "action_required": reconciliation.action_required,
            "audit_record_ref": action.audit_record_ref,
            "record_only": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
        },
        market="execution",
        universe=reconciliation.venue_order_ref or reconciliation.order_intent_ref,
        horizon="execution_reconciliation_action",
        frequency="event_driven",
        lineage=lineage,
        implementation_hash=implementation_hash,
        assumptions=(
            "This QRO records a governance action over an existing reconciliation ref; it does not execute remediation.",
        ),
        known_limits=(
            "Action completion requires a separate remediation, halt, waiver, or operator workflow evidence ref.",
        ),
        failure_modes=(
            "Open actions can remain unresolved if no operator, scheduler, or remediation system processes them.",
        ),
        validation_plan=(
            "Verify action_required reconciliations produce action records before claiming execution monitor closure.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="execution.reconciliation_action:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_execution_boundary_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref="api:research_os.execution.reconciliation_actions",
        pass_name="api_execution_reconciliation_action_qro_to_execution_policy_ir",
        record_ref=action.action_ref,
        permission_ref="execution.reconciliation_action:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(action.reconciliation_ref, action.action_kind, action.audit_record_ref),
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _reject_raw_order_intent_fields(value: Any, *, path: str = "order_intent") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _ORDER_INTENT_FORBIDDEN_RAW_FIELDS:
                raise HTTPException(
                    status_code=422,
                    detail=f"{path}.{key} is raw order/secret material; use *_ref fields only",
                )
            _reject_raw_order_intent_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _reject_raw_order_intent_fields(item, path=f"{path}[{idx}]")


_MARKET_DATA_FORBIDDEN_RAW_FIELDS = {
    "raw_data",
    "raw_dataset",
    "raw_payload",
    "payload",
    "rows",
    "records",
    "bars",
    "ohlcv",
    "prices",
    "quantity",
    "price",
    "notional",
    "api_key",
    "api_secret",
    "secret",
    "password",
    "oauth_token",
    "token",
}


def _reject_raw_market_data_fields(value: Any, *, path: str = "market_data") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _MARKET_DATA_FORBIDDEN_RAW_FIELDS:
                raise HTTPException(
                    status_code=422,
                    detail=f"{path}.{key} is raw market-data or credential material; use refs and checksums only",
                )
            _reject_raw_market_data_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _reject_raw_market_data_fields(item, path=f"{path}[{idx}]")
    elif contains_plaintext_secret(value):
        raise HTTPException(status_code=422, detail=f"{path} contains plaintext secret material")


def _market_data_use_context(payload: dict[str, Any]) -> str:
    return str(payload.get("use_context") or "research")


def _market_data_dataset_summary(record: DatasetSemanticsRecord) -> dict[str, Any]:
    return record.to_dict()


def _market_data_instrument_summary(record: InstrumentSpec) -> dict[str, Any]:
    return record.to_dict()


def _market_data_capability_summary(record: MarketCapabilityMatrixRecord) -> dict[str, Any]:
    return record.to_dict()


def _market_data_use_validation_summary(record: MarketDataUseValidationRecord) -> dict[str, Any]:
    return record.to_dict()


def _compile_market_data_contract_qro(
    *,
    qro_id: str,
    graph_command_id: str,
    actor: str,
    entrypoint_ref: str,
    pass_name: str,
    record_ref: str,
    permission_ref: str,
    evidence_refs: Iterable[str],
    validation_refs: Iterable[str] = (),
    tool_record_ref: str,
    qro_type: QROType,
) -> dict[str, str]:
    safe_pass = pass_name.replace(":", "_").replace(".", "_")
    return _compile_entrypoint_qro(
        qro_id=qro_id,
        graph_command_id=graph_command_id,
        actor=actor,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref=entrypoint_ref,
        pass_name=pass_name,
        validation_refs=_compiler_unique_refs(
            validation_refs,
            evidence_refs,
            f"validation:{entrypoint_ref}:{record_ref}",
        ),
        evidence_refs=evidence_refs,
        environment_lock_ref=f"env:market_data_contract:{safe_pass}:v1",
        permission_ref=permission_ref,
        deterministic_run_plan_ref=f"runplan:{entrypoint_ref}:{record_ref}",
        rollback_ref=f"rollback:{entrypoint_ref}:{record_ref}:manual_review",
        tool_record_refs=(tool_record_ref, record_ref),
        node_refs=(f"qro:{qro_id}", f"qro_type:{qro_type.value}", record_ref),
        canonical_command_refs=(f"research_graph_command:{graph_command_id}", record_ref),
    )


def _record_market_data_dataset_qro(
    record: DatasetSemanticsRecord,
    *,
    actor: str,
    use_context: str,
    entrypoint_ref: str = "api:research_os.market_data.datasets",
    pass_name: str = "api_market_data_dataset_qro_to_dataset_ir",
    tool_record_ref: str = "api:market_data.datasets",
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in (
            record.dataset_ref,
            record.source_ref,
            f"dataset_version:{record.version}",
            f"checksum:{record.checksum}" if record.checksum else "",
            record.known_at_ref,
            record.effective_at_ref,
            record.pit_bitemporal_rules_ref,
            *record.lineage_refs,
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.DATASET,
        owner="market_data_registry",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "dataset_ref": record.dataset_ref,
            "source_ref": record.source_ref,
            "version": record.version,
            "use_context": use_context,
            "record_hash": content_hash(record.to_dict()),
        },
        output_contract={
            "status": "dataset_semantics_recorded",
            "dataset_ref": record.dataset_ref,
            "known_at_ref": record.known_at_ref,
            "effective_at_ref": record.effective_at_ref,
            "pit_bitemporal_rules_ref": record.pit_bitemporal_rules_ref,
            "quality_status": record.quality_status,
            "freshness_status": record.freshness_status,
            "lineage_ref_count": len(record.lineage_refs),
            "raw_data_stored": False,
            "connector_called": False,
        },
        market=record.source_ref or "market_data",
        universe=record.dataset_ref,
        horizon=use_context,
        frequency="metadata_event",
        lineage=("market_data.dataset_semantics", record.dataset_ref, record.source_ref, *record.lineage_refs),
        implementation_hash="market_data_dataset:" + content_hash(record.to_dict()),
        assumptions=(
            "This QRO records dataset semantics refs and metadata only; it does not store raw market data rows.",
        ),
        known_limits=(
            "A dataset semantics QRO is not proof that a connector pulled fresh data or that downstream runs consumed it.",
        ),
        failure_modes=(
            "Dataset refs can still be stale, unavailable, low quality, or incompatible with later strategy/run requirements.",
        ),
        validation_plan=(
            "Bind dataset refs to DatasetVersion, PIT/as-of checks, quality reports, and run/RDP evidence before production claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="market_data.dataset:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_market_data_contract_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref=entrypoint_ref,
        pass_name=pass_name,
        record_ref=record.dataset_ref,
        permission_ref="market_data.dataset:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.dataset_ref, record.source_ref, record.pit_bitemporal_rules_ref),
        tool_record_ref=tool_record_ref,
        qro_type=QROType.DATASET,
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_market_data_instrument_qro(
    record: InstrumentSpec,
    *,
    actor: str,
    entrypoint_ref: str = "api:research_os.market_data.instruments",
    pass_name: str = "api_market_data_instrument_qro_to_instrument_ir",
    tool_record_ref: str = "api:market_data.instruments",
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in (
            record.instrument_ref,
            record.exchange_calendar_ref,
            record.contract_spec_ref,
            record.option_chain_ref,
            record.futures_roll_rule_ref,
            record.continuous_contract_rule_ref,
            record.corporate_actions_ref,
            record.symbol_mapping_ref,
            record.expiry_ref,
            record.strike_ref,
            record.contract_multiplier_ref,
            record.settlement_ref,
            record.margin_ref,
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.DATA_SOURCE_ASSET,
        owner="market_data_registry",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "instrument_ref": record.instrument_ref,
            "asset_class": record.asset_class,
            "instrument_type": record.instrument_type,
            "currency": record.currency,
            "record_hash": content_hash(record.to_dict()),
        },
        output_contract={
            "status": "instrument_spec_recorded",
            "instrument_ref": record.instrument_ref,
            "exchange_calendar_ref": record.exchange_calendar_ref,
            "symbol_mapping_ref": record.symbol_mapping_ref,
            "option_terms_present": all(
                bool(ref)
                for ref in (
                    record.expiry_ref,
                    record.strike_ref,
                    record.contract_multiplier_ref,
                    record.settlement_ref,
                )
            )
            if record.instrument_type.lower() == "option"
            else None,
            "raw_data_stored": False,
            "connector_called": False,
        },
        market=record.asset_class,
        universe=record.instrument_ref,
        horizon="instrument_spec",
        frequency="metadata_event",
        lineage=("market_data.instrument_spec", record.instrument_ref, record.asset_class, record.instrument_type),
        implementation_hash="market_data_instrument:" + content_hash(record.to_dict()),
        assumptions=(
            "This QRO maps InstrumentSpec metadata into the existing DataSourceAsset QRO type because QROType has no dedicated InstrumentSpec member.",
        ),
        known_limits=(
            "InstrumentSpec registration is not a live venue capability check, data availability proof, or connector verification.",
        ),
        failure_modes=(
            "Symbol mapping, calendars, contract terms, and downstream capability checks can still reject use of the instrument.",
        ),
        validation_plan=(
            "Bind instrument refs to DatasetSemantics, MarketCapabilityMatrix, execution capability records, and run evidence before runtime claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="market_data.instrument:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_market_data_contract_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref=entrypoint_ref,
        pass_name=pass_name,
        record_ref=record.instrument_ref,
        permission_ref="market_data.instrument:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.instrument_ref, record.asset_class, record.instrument_type),
        tool_record_ref=tool_record_ref,
        qro_type=QROType.DATA_SOURCE_ASSET,
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_market_data_capability_qro(
    record: MarketCapabilityMatrixRecord,
    *,
    actor: str,
    use_context: str,
    entrypoint_ref: str = "api:research_os.market_data.capability_matrices",
    pass_name: str = "api_market_data_capability_qro_to_capability_ir",
    tool_record_ref: str = "api:market_data.capability_matrices",
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    evidence_refs = tuple(
        ref
        for ref in (
            record.matrix_ref,
            record.permission_requirement,
            record.data_availability,
            record.cost_model_availability,
            record.execution_availability,
        )
        if ref
    )
    qro = QRORecord(
        qro_type=QROType.MARKET_CAPABILITY_MATRIX,
        owner="market_data_registry",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "matrix_ref": record.matrix_ref,
            "asset_class": record.asset_class,
            "instrument_type": record.instrument_type,
            "use_context": use_context,
            "record_hash": content_hash(record.to_dict()),
        },
        output_contract={
            "status": "market_capability_matrix_recorded",
            "matrix_ref": record.matrix_ref,
            "research": record.research,
            "backtest": record.backtest,
            "paper": record.paper,
            "testnet": record.testnet,
            "live": record.live,
            "permission_requirement": record.permission_requirement,
            "raw_data_stored": False,
            "connector_called": False,
            "venue_called": False,
        },
        market=record.asset_class,
        universe=record.instrument_type,
        horizon=use_context,
        frequency="metadata_event",
        lineage=("market_data.capability_matrix", record.matrix_ref, record.asset_class, record.instrument_type),
        implementation_hash="market_data_capability:" + content_hash(record.to_dict()),
        assumptions=(
            "This QRO records declared market capability metadata only; it does not test live venue permissions.",
        ),
        known_limits=(
            "Real data-provider access, execution venue readiness, cost model validation, and live broker permissions remain separate gates.",
        ),
        failure_modes=(
            "A later run can still fail if provider data, cost model, permissions, or execution adapters are unavailable.",
        ),
        validation_plan=(
            "Bind capability refs to dataset versions, execution venue checks, permission gates, and paper/testnet/live evidence before runtime claims.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=evidence_refs,
        permission="market_data.capability:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_market_data_contract_qro(
        qro_id=qro.qro_id,
        graph_command_id=command_id,
        actor=actor,
        entrypoint_ref=entrypoint_ref,
        pass_name=pass_name,
        record_ref=record.matrix_ref,
        permission_ref="market_data.capability:user_manual",
        evidence_refs=evidence_refs,
        validation_refs=(record.matrix_ref, record.asset_class, record.instrument_type),
        tool_record_ref=tool_record_ref,
        qro_type=QROType.MARKET_CAPABILITY_MATRIX,
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _record_market_data_use_validation_qro(
    record: MarketDataUseValidationRecord,
    *,
    actor: str,
) -> dict[str, str]:
    now = _dt.datetime.now(_dt.UTC).isoformat()
    record_hash = content_hash(record.to_dict())
    qro = QRORecord(
        qro_type=QROType.MARKET_CAPABILITY_MATRIX,
        owner="market_data_registry",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "validation_ref": record.validation_ref,
            "request_ref": record.request_ref,
            "use_context": record.use_context,
            "dataset_ref_count": len(record.dataset_refs),
            "instrument_ref_count": len(record.instrument_refs),
            "capability_matrix_ref": record.capability_matrix_ref,
            "record_hash": record_hash,
        },
        output_contract={
            "status": "market_data_use_validated",
            "validation_ref": record.validation_ref,
            "accepted": record.accepted,
            "dataset_refs": list(record.dataset_refs),
            "instrument_refs": list(record.instrument_refs),
            "capability_matrix_ref": record.capability_matrix_ref,
            "capital_record_ref": record.capital_record_ref,
            "transformation_refs": list(record.transformation_refs),
            "raw_data_stored": False,
            "connector_called": False,
            "strategy_builder_called": False,
            "venue_called": False,
        },
        market="market_data",
        universe=record.request_ref,
        horizon=record.use_context,
        frequency="metadata_event",
        lineage=("market_data.use_validation", record.validation_ref, record.request_ref, record.capability_matrix_ref),
        implementation_hash="market_data_use_validation:" + record_hash,
        assumptions=(
            "This QRO records an accepted refs-only market data use gate; it does not run a connector or strategy builder.",
        ),
        known_limits=(
            "Accepted market data use is not proof that data rows were downloaded, a strategy consumed the refs, or live permissions were tested.",
        ),
        failure_modes=(
            "A later strategy, run, connector, or execution gate can still reject stale data, missing rows, or unavailable provider permissions.",
        ),
        validation_plan=(
            "Require downstream strategy, backtest, RDP, and execution records to cite this validation ref before claiming end-to-end data binding.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=now,
        known_at=now,
        effective_at=now,
        evidence_refs=record.evidence_refs,
        permission="market_data.use:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=actor,
        payload={"qro": qro},
        evidence_refs=record.evidence_refs,
    )
    command_id = RESEARCH_GRAPH_STORE.apply(command)
    compiler_refs = _compile_market_data_use_validation_qro(
        record,
        qro_id=qro.qro_id,
        actor=actor,
        entrypoint_ref="api:research_os.settings.market_data_use_validations",
        pass_name="settings_market_data_use_qro_to_market_data_ir",
        tool_record_ref="api:settings.market_data_use_validations",
    )
    return {"qro_id": qro.qro_id, "research_graph_command_id": command_id, **compiler_refs}


def _compile_market_data_use_validation_qro(
    record: MarketDataUseValidationRecord,
    *,
    qro_id: str,
    actor: str,
    entrypoint_ref: str,
    pass_name: str,
    tool_record_ref: str,
) -> dict[str, str]:
    validation_refs = _compiler_unique_refs(
        record.validation_ref,
        record.request_ref,
        record.dataset_refs,
        record.instrument_refs,
        record.capability_matrix_ref,
        record.evidence_refs,
    )
    ir, compiler_pass = _compile_qro_payload(
        {
            "qro_id": qro_id,
            "entry_source": EntrySource.API.value,
            "actor_source": ActorSource.USER_MANUAL.value,
            "pass_name": pass_name,
            "validation_refs": validation_refs,
            "environment_lock_ref": "env:market_data_use:v1",
            "permission_ref": "market_data.use:user_manual",
            "deterministic_run_plan_ref": f"runplan:market_data_use:{record.validation_ref}",
            "rollback_ref": f"rollback:market_data_use:{record.validation_ref}",
            "tool_record_refs": (tool_record_ref, record.validation_ref),
        },
        actor=actor,
    )
    coverage_candidate = _validate_goal_entrypoint_coverage_candidate(
        _goal_entrypoint_coverage_from_compiler_records(
            ir,
            compiler_pass,
            entrypoint_ref=entrypoint_ref,
        )
    )
    COMPILER_IR_STORE.record_ir(ir)
    COMPILER_IR_STORE.record_pass(compiler_pass)
    coverage = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(coverage_candidate)
    return {
        "compiler_ir_ref": ir.ir_ref,
        "compiler_pass_ref": compiler_pass.pass_ref,
        "entrypoint_coverage_ref": coverage.coverage_ref,
    }


def _market_data_use_ref_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    refs = tuple(str(ref) for ref in _payload_tuple(value) if str(ref).strip())
    if not refs:
        raise ValueError(f"{field_name} must contain at least one ref")
    return refs


def _market_data_transformation_payloads(value: Any) -> tuple[dict[str, Any], ...]:
    if value in (None, "", [], ()):
        return ()
    raw_items = value if isinstance(value, (list, tuple)) else (value,)
    items: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ValueError(f"transformation_claims[{idx}] must be an object")
        items.append(item)
    return tuple(items)


@app.post("/api/research-os/market_data/datasets")
def research_os_record_market_data_dataset(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("dataset") if isinstance(payload.get("dataset"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("dataset payload must be an object")
        _reject_raw_market_data_fields(raw, path="dataset")
        use_context = _market_data_use_context(payload)
        record = dataset_semantics_record_from_dict(raw)
        recorded = MARKET_DATA_REGISTRY.record_dataset(record, use_context=use_context)
        graph_refs = _record_market_data_dataset_qro(recorded, actor=actor, use_context=use_context)
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "dataset_ref": recorded.dataset_ref,
        "use_context": use_context,
        "recorded_by": actor,
        "raw_data_stored": False,
        "connector_called": False,
        **graph_refs,
        "boundary": "records dataset semantics refs only; no market data rows, no connector call, no credential material",
    }


@app.post("/api/research-os/market_data/instruments")
def research_os_record_market_data_instrument(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("instrument") if isinstance(payload.get("instrument"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("instrument payload must be an object")
        _reject_raw_market_data_fields(raw, path="instrument")
        record = instrument_spec_from_dict(raw)
        recorded = MARKET_DATA_REGISTRY.record_instrument(record)
        graph_refs = _record_market_data_instrument_qro(recorded, actor=actor)
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "instrument_ref": recorded.instrument_ref,
        "asset_class": recorded.asset_class,
        "recorded_by": actor,
        "raw_data_stored": False,
        "connector_called": False,
        **graph_refs,
        "boundary": "records InstrumentSpec metadata only; no data pull, no venue capability check",
    }


@app.post("/api/research-os/market_data/capability_matrices")
def research_os_record_market_data_capability_matrix(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("capability_matrix") if isinstance(payload.get("capability_matrix"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("capability_matrix payload must be an object")
        _reject_raw_market_data_fields(raw, path="capability_matrix")
        use_context = _market_data_use_context(payload)
        record = market_capability_matrix_record_from_dict(raw)
        recorded = MARKET_DATA_REGISTRY.record_capability_matrix(record, use_context=use_context)
        graph_refs = _record_market_data_capability_qro(recorded, actor=actor, use_context=use_context)
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "matrix_ref": recorded.matrix_ref,
        "use_context": use_context,
        "recorded_by": actor,
        "raw_data_stored": False,
        "connector_called": False,
        "venue_called": False,
        **graph_refs,
        "boundary": "records declared MarketCapabilityMatrix refs only; no provider, broker, or live venue call",
    }


@app.post("/api/research-os/market_data/use_requests")
def research_os_record_market_data_use_request(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("market_data_use") if isinstance(payload.get("market_data_use"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("market_data_use payload must be an object")
        _reject_raw_market_data_fields(raw, path="market_data_use")
        request_ref = str(raw.get("request_ref") or "").strip()
        if not request_ref:
            raise ValueError("request_ref is required")
        use_context = str(raw.get("use_context") or "research")
        dataset_refs = _market_data_use_ref_tuple(raw.get("dataset_refs"), field_name="dataset_refs")
        instrument_refs = _market_data_use_ref_tuple(raw.get("instrument_refs"), field_name="instrument_refs")
        capability_matrix_ref = str(raw.get("capability_matrix_ref") or "").strip()
        if not capability_matrix_ref:
            raise ValueError("capability_matrix_ref is required")
        datasets = tuple(MARKET_DATA_REGISTRY.dataset(ref) for ref in dataset_refs)
        instruments = tuple(MARKET_DATA_REGISTRY.instrument(ref) for ref in instrument_refs)
        capability_matrix = MARKET_DATA_REGISTRY.capability_matrix(capability_matrix_ref)
        capital_record = cross_currency_capital_record_from_dict(raw.get("capital_record"))
        transformation_claims = tuple(
            data_transformation_claim_from_dict(item)
            for item in _market_data_transformation_payloads(raw.get("transformation_claims"))
        )
        request_record = MarketDataUseRequest(
            request_ref=request_ref,
            use_context=use_context,
            datasets=datasets,
            instruments=instruments,
            capability_matrix=capability_matrix,
            capital_record=capital_record,
            transformation_claims=transformation_claims,
        )
        decision = validate_market_data_use(request_record)
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        capital_refs = tuple(
            ref
            for ref in (
                capital_record.fx_conversion_ref if capital_record else "",
                capital_record.collateral_ref if capital_record else "",
                capital_record.margin_ref if capital_record else "",
                capital_record.leverage_ref if capital_record else "",
                capital_record.net_exposure_ref if capital_record else "",
                capital_record.gross_exposure_ref if capital_record else "",
                capital_record.capital_allocation_ref if capital_record else "",
                capital_record.financing_cost_ref if capital_record else "",
            )
            if ref
        )
        transformation_refs = tuple(claim.transform_ref for claim in transformation_claims)
        validation_ref = str(raw.get("validation_ref") or "").strip() or "market_data_use:" + content_hash(
            {
                "request_ref": request_ref,
                "use_context": use_context,
                "dataset_refs": dataset_refs,
                "instrument_refs": instrument_refs,
                "capability_matrix_ref": capability_matrix_ref,
                "capital_refs": capital_refs,
                "transformation_refs": transformation_refs,
            }
        )
        now = _dt.datetime.now(_dt.UTC).isoformat()
        evidence_refs = tuple(
            ref
            for ref in (
                validation_ref,
                request_ref,
                *dataset_refs,
                *instrument_refs,
                capability_matrix_ref,
                *capital_refs,
                *transformation_refs,
            )
            if ref
        )
        record = MarketDataUseValidationRecord(
            validation_ref=validation_ref,
            request_ref=request_ref,
            use_context=use_context,
            dataset_refs=dataset_refs,
            instrument_refs=instrument_refs,
            capability_matrix_ref=capability_matrix_ref,
            capital_record_ref=str(raw.get("capital_record_ref") or "").strip() or None,
            transformation_refs=transformation_refs,
            accepted=True,
            violation_codes=(),
            evidence_refs=evidence_refs,
            recorded_by=actor,
            created_at_utc=now,
        )
        recorded = MARKET_DATA_REGISTRY.record_use_validation(record)
        graph_refs = _record_market_data_use_validation_qro(recorded, actor=actor)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "validation_ref": recorded.validation_ref,
        "request_ref": recorded.request_ref,
        "use_context": recorded.use_context,
        "accepted": recorded.accepted,
        "recorded_by": actor,
        "raw_data_stored": False,
        "connector_called": False,
        "strategy_builder_called": False,
        "venue_called": False,
        **graph_refs,
        "boundary": "records accepted refs-only market data use gate; no connector, strategy builder, or venue call",
    }


@app.get("/api/research-os/market_data/summary")
def research_os_market_data_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    datasets = MARKET_DATA_REGISTRY.datasets()
    instruments = MARKET_DATA_REGISTRY.instruments()
    capability_matrices = MARKET_DATA_REGISTRY.capability_matrices()
    use_validations = MARKET_DATA_REGISTRY.use_validations()
    return {
        "user": actor,
        "dataset_total": len(datasets),
        "instrument_total": len(instruments),
        "capability_matrix_total": len(capability_matrices),
        "use_validation_total": len(use_validations),
        "datasets": [_market_data_dataset_summary(record) for record in datasets],
        "instruments": [_market_data_instrument_summary(record) for record in instruments],
        "capability_matrices": [_market_data_capability_summary(record) for record in capability_matrices],
        "use_validations": [_market_data_use_validation_summary(record) for record in use_validations],
        "boundary": "summary exposes refs and metadata only; raw market data rows and credentials are never returned",
    }


@app.post("/api/research-os/signal_validations")
def research_os_record_signal_validation(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("signal_validation") if isinstance(payload.get("signal_validation"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("signal_validation payload must be an object")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = signal_validation_record_from_dict(raw)
        SIGNAL_CONTRACTS.get(record.signal_ref)
        recorded = SIGNAL_VALIDATIONS.record_validation(record, known_signal_refs={record.signal_ref})
        graph_refs = _record_signal_validation_qro(recorded, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"unknown SignalContract: {record.signal_ref}") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "validation_id": recorded.validation_id,
        "signal_ref": recorded.signal_ref,
        "verdict": getattr(recorded.verdict, "value", recorded.verdict),
        "recorded_by": actor,
        **graph_refs,
    }


@app.get("/api/research-os/signal_validations/summary")
def research_os_signal_validation_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = SIGNAL_VALIDATIONS.validations()
    accepted = SIGNAL_VALIDATIONS.accepted_for_signal
    signal_refs = sorted({record.signal_ref for record in records})
    return {
        "user": actor,
        "signal_validation_total": len(records),
        "accepted_signal_refs": [
            signal_ref
            for signal_ref in signal_refs
            if accepted(signal_ref)
        ],
        "validations": [_signal_validation_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/order_intents")
def research_os_record_execution_order_intent(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("order_intent") if isinstance(payload.get("order_intent"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("order_intent payload must be an object")
        _reject_raw_order_intent_fields(raw)
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = execution_order_intent_from_dict(raw)
        known_signal_validation_refs: set[str] | None = None
        if record.signal_validation_ref:
            validation = SIGNAL_VALIDATIONS.validation(str(record.signal_validation_ref))
            if record.signal_ref and validation.signal_ref != record.signal_ref:
                raise ValueError("signal_validation_ref does not match signal_ref")
            if str(getattr(validation.verdict, "value", validation.verdict)) != "accepted":
                raise ValueError("signal_validation_ref is not accepted")
            known_signal_validation_refs = {validation.validation_id}
        known_market_data_use_validation_refs: set[str] | None = None
        if record.market_data_use_validation_ref:
            market_data_use = MARKET_DATA_REGISTRY.use_validation(str(record.market_data_use_validation_ref))
            if not bool(getattr(market_data_use, "accepted", False)):
                raise ValueError("market_data_use_validation_ref is not accepted")
            known_market_data_use_validation_refs = {market_data_use.validation_ref}
        decision = validate_execution_order_intent(
            record,
            known_signal_validation_refs=known_signal_validation_refs,
            known_market_data_use_validation_refs=known_market_data_use_validation_refs,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_ORDER_INTENTS.record_intent(
            record,
            known_signal_validation_refs=known_signal_validation_refs,
            known_market_data_use_validation_refs=known_market_data_use_validation_refs,
        )
        graph_refs = _record_execution_order_intent_qro(recorded, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "order_intent_ref": recorded.order_intent_ref,
        "runtime": getattr(recorded.runtime, "value", recorded.runtime),
        "instrument_ref": recorded.instrument_ref,
        "market_data_use_validation_ref": recorded.market_data_use_validation_ref,
        "recorded_by": actor,
        "place_order_called": False,
        **graph_refs,
        "boundary": "records typed execution order intent only; no order placement, no venue call, no money movement",
    }


@app.get("/api/research-os/execution/order_intents/summary")
def research_os_execution_order_intent_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_ORDER_INTENTS.intents()
    return {
        "user": actor,
        "order_intent_total": len(records),
        "order_intents": [_execution_order_intent_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/runtime_promotions")
def research_os_record_runtime_promotion(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("runtime_promotion") if isinstance(payload.get("runtime_promotion"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("runtime_promotion payload must be an object")
        _reject_raw_order_intent_fields(raw, path="runtime_promotion")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = runtime_promotion_record_from_dict(raw)
        decision = validate_runtime_promotion_record(record)
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = RUNTIME_PROMOTIONS.record_promotion(record)
        graph_refs = _record_runtime_promotion_qro(recorded, actor=actor)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "request_ref": recorded.request_ref,
        "source_runtime": getattr(recorded.source_runtime, "value", recorded.source_runtime),
        "target_runtime": getattr(recorded.target_runtime, "value", recorded.target_runtime),
        "recorded_by": actor,
        "place_order_called": False,
        "venue_call_called": False,
        **graph_refs,
        "boundary": "records governed runtime transition only; no order placement, no venue call, no money movement",
    }


@app.get("/api/research-os/execution/runtime_promotions/summary")
def research_os_runtime_promotion_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = RUNTIME_PROMOTIONS.promotions()
    return {
        "user": actor,
        "runtime_promotion_total": len(records),
        "runtime_promotions": [_runtime_promotion_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/order_materializations")
def research_os_record_execution_order_materialization(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    materializer_result: dict[str, Any] = {
        "materializer_called": False,
        "api_place_order_called": False,
        "api_venue_call_called": False,
    }
    try:
        raw = payload.get("order_materialization") if isinstance(payload.get("order_materialization"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("order_materialization payload must be an object")
        _reject_raw_order_intent_fields(raw, path="order_materialization")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = execution_order_materialization_from_dict(raw)
        order_intent = EXECUTION_ORDER_INTENTS.intent(record.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(record.runtime_promotion_ref)
        decision = validate_execution_order_materialization(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))

        if record.materialize_enabled:
            raw_result = EXECUTION_ORDER_MATERIALIZER.materialize_order(
                materialization=record,
                order_intent=order_intent,
                runtime_promotion=runtime_promotion,
                actor=actor,
            )
            if not isinstance(raw_result, dict):
                raise ValueError("execution order materializer must return a dict")
            _reject_raw_order_intent_fields(raw_result, path="order_materializer_result")
            if bool(raw_result.get("api_place_order_called", False)):
                raise ValueError("execution order materializer cannot call place_order")
            if bool(raw_result.get("api_venue_call_called", False)):
                raise ValueError("execution order materializer cannot call a venue API")
            materializer_result = {
                **raw_result,
                "materializer_called": True,
                "api_place_order_called": False,
                "api_venue_call_called": False,
            }
            evidence_refs = tuple(
                dict.fromkeys(
                    (
                        *record.evidence_refs,
                        *_payload_tuple(raw_result.get("evidence_refs")),
                        *_payload_tuple(raw_result.get("evidence_ref")),
                    )
                )
            )
            record = replace(
                record,
                materializer_ref=str(raw_result.get("materializer_ref") or record.materializer_ref),
                materialization_status=str(
                    raw_result.get("materialization_status")
                    or raw_result.get("status")
                    or "materialized"
                ),
                order_schema_ref=raw_result.get("order_schema_ref") or record.order_schema_ref,
                order_payload_hash=raw_result.get("order_payload_hash") or record.order_payload_hash,
                quantity_resolution_ref=raw_result.get("quantity_resolution_ref") or record.quantity_resolution_ref,
                notional_resolution_ref=raw_result.get("notional_resolution_ref") or record.notional_resolution_ref,
                price_resolution_ref=raw_result.get("price_resolution_ref") or record.price_resolution_ref,
                time_in_force_resolution_ref=raw_result.get("time_in_force_resolution_ref")
                or record.time_in_force_resolution_ref,
                market_snapshot_ref=raw_result.get("market_snapshot_ref") or record.market_snapshot_ref,
                risk_check_ref=raw_result.get("risk_check_ref") or record.risk_check_ref,
                evidence_refs=evidence_refs,
                materialization_ref="",
            )

        decision = validate_execution_order_materialization(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_ORDER_MATERIALIZATIONS.record_materialization(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        graph_refs = _record_execution_order_materialization_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
            materializer_result=materializer_result,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "materialization_ref": recorded.materialization_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "materialization_mode": recorded.materialization_mode,
        "materialization_status": recorded.materialization_status,
        "materializer_ref": recorded.materializer_ref,
        "materialize_enabled": recorded.materialize_enabled,
        "materializer_called": bool(materializer_result.get("materializer_called", False)),
        "record_only": not recorded.materialize_enabled,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        "order_schema_ref": recorded.order_schema_ref,
        "order_payload_hash": recorded.order_payload_hash,
        "quantity_resolution_ref": recorded.quantity_resolution_ref,
        "notional_resolution_ref": recorded.notional_resolution_ref,
        "price_resolution_ref": recorded.price_resolution_ref,
        "market_snapshot_ref": recorded.market_snapshot_ref,
        "risk_check_ref": recorded.risk_check_ref,
        **graph_refs,
        "boundary": "records order materialization refs and payload hash only; no raw order, no direct place_order, no venue call",
    }


@app.get("/api/research-os/execution/order_materializations/summary")
def research_os_execution_order_materialization_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_ORDER_MATERIALIZATIONS.materializations()
    return {
        "user": actor,
        "order_materialization_total": len(records),
        "order_materializations": [_execution_order_materialization_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/venue_connectivity_checks/run")
def research_os_run_execution_venue_connectivity_check(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    checker_result: dict[str, Any] = {
        "checker_called": False,
        "api_place_order_called": False,
        "api_venue_call_called": False,
    }
    try:
        if not isinstance(payload, dict):
            raise ValueError("venue connectivity check run payload must be an object")
        _reject_raw_order_intent_fields(payload, path="venue_connectivity_check_run")
        order_intent_ref = str(payload.get("order_intent_ref") or "")
        runtime_promotion_ref = str(payload.get("runtime_promotion_ref") or "")
        if not order_intent_ref or not runtime_promotion_ref:
            raise ValueError("venue connectivity check run requires order_intent_ref and runtime_promotion_ref")
        order_intent = EXECUTION_ORDER_INTENTS.intent(order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(runtime_promotion_ref)

        raw_result = EXECUTION_VENUE_CONNECTIVITY_CHECKER.check_connectivity(
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            actor=actor,
        )
        if not isinstance(raw_result, dict):
            raise ValueError("execution venue connectivity checker must return a dict")
        _reject_raw_order_intent_fields(raw_result, path="venue_connectivity_checker_result")
        if bool(raw_result.get("api_place_order_called", False)):
            raise ValueError("execution venue connectivity checker cannot call place_order")
        if bool(raw_result.get("api_venue_call_called", False)):
            raise ValueError("execution venue connectivity checker cannot call a venue API in this seam")
        raw_check = (
            raw_result.get("venue_connectivity_check")
            if isinstance(raw_result.get("venue_connectivity_check"), dict)
            else raw_result
        )
        if not isinstance(raw_check, dict):
            raise ValueError("execution venue connectivity checker result must include a check object")
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *_payload_tuple(raw_check.get("evidence_refs")),
                    *_payload_tuple(raw_check.get("evidence_ref")),
                    *_payload_tuple(raw_result.get("evidence_refs")),
                    *_payload_tuple(raw_result.get("evidence_ref")),
                )
            )
        )
        record = execution_venue_connectivity_check_from_dict(
            {
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "venue_ref": raw_check.get("venue_ref") or order_intent.venue_ref,
                "guarded_venue_ref": raw_check.get("guarded_venue_ref") or raw_result.get("guarded_venue_ref"),
                "runtime": raw_check.get("runtime") or str(getattr(order_intent.runtime, "value", order_intent.runtime)),
                "asset_class": raw_check.get("asset_class") or order_intent.asset_class,
                "instrument_ref": raw_check.get("instrument_ref") or order_intent.instrument_ref,
                "connectivity_status": raw_check.get("connectivity_status") or raw_check.get("status") or "accepted",
                "checker_ref": raw_check.get("checker_ref")
                or raw_result.get("checker_ref")
                or getattr(EXECUTION_VENUE_CONNECTIVITY_CHECKER, "checker_ref", "execution_venue_connectivity_checker"),
                "permission_gate_ref": raw_check.get("permission_gate_ref") or order_intent.permission_gate_ref,
                "order_guard_ref": raw_check.get("order_guard_ref") or order_intent.order_guard_ref,
                "idempotency_key": raw_check.get("idempotency_key") or order_intent.idempotency_key,
                "audit_record_ref": raw_check.get("audit_record_ref") or raw_result.get("audit_record_ref"),
                "credential_check_ref": raw_check.get("credential_check_ref") or raw_result.get("credential_check_ref"),
                "ip_allowlist_ref": raw_check.get("ip_allowlist_ref") or raw_result.get("ip_allowlist_ref"),
                "withdrawal_disabled_ref": raw_check.get("withdrawal_disabled_ref")
                or raw_result.get("withdrawal_disabled_ref"),
                "hmac_replay_protection_ref": raw_check.get("hmac_replay_protection_ref")
                or raw_result.get("hmac_replay_protection_ref"),
                "health_check_ref": raw_check.get("health_check_ref") or raw_result.get("health_check_ref"),
                "rate_limit_ref": raw_check.get("rate_limit_ref") or raw_result.get("rate_limit_ref"),
                "sandbox_proof_ref": raw_check.get("sandbox_proof_ref") or raw_result.get("sandbox_proof_ref"),
                "connectivity_check_hash": raw_check.get("connectivity_check_hash")
                or raw_result.get("connectivity_check_hash"),
                "kill_switch_ref": raw_check.get("kill_switch_ref") or order_intent.kill_switch_ref,
                "secret_ref": raw_check.get("secret_ref") or order_intent.secret_ref,
                "responsibility_boundary_ref": raw_check.get("responsibility_boundary_ref")
                or order_intent.responsibility_boundary_ref,
                "evidence_refs": evidence_refs,
                "recorded_by": actor,
            }
        )
        decision = validate_execution_venue_connectivity_check(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_VENUE_CONNECTIVITY_CHECKS.record_check(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        checker_result = {
            **raw_result,
            "checker_called": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
        }
        graph_refs = _record_execution_venue_connectivity_check_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "venue_connectivity_check_ref": recorded.venue_connectivity_check_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "venue_ref": recorded.venue_ref,
        "guarded_venue_ref": recorded.guarded_venue_ref,
        "runtime": recorded.runtime,
        "asset_class": recorded.asset_class,
        "connectivity_status": recorded.connectivity_status,
        "checker_ref": recorded.checker_ref,
        "connectivity_check_hash": recorded.connectivity_check_hash,
        "checker_called": bool(checker_result.get("checker_called", False)),
        "record_only": False,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "runs an injected refs-only connectivity checker; no raw order, no venue call in this seam, no money movement",
    }


@app.post("/api/research-os/execution/venue_connectivity_checks")
def research_os_record_execution_venue_connectivity_check(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = (
            payload.get("venue_connectivity_check")
            if isinstance(payload.get("venue_connectivity_check"), dict)
            else payload
        )
        if not isinstance(raw, dict):
            raise ValueError("venue_connectivity_check payload must be an object")
        _reject_raw_order_intent_fields(raw, path="venue_connectivity_check")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = execution_venue_connectivity_check_from_dict(raw)
        order_intent = EXECUTION_ORDER_INTENTS.intent(record.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(record.runtime_promotion_ref)
        decision = validate_execution_venue_connectivity_check(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_VENUE_CONNECTIVITY_CHECKS.record_check(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
        )
        graph_refs = _record_execution_venue_connectivity_check_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "venue_connectivity_check_ref": recorded.venue_connectivity_check_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "venue_ref": recorded.venue_ref,
        "guarded_venue_ref": recorded.guarded_venue_ref,
        "runtime": recorded.runtime,
        "asset_class": recorded.asset_class,
        "connectivity_status": recorded.connectivity_status,
        "checker_ref": recorded.checker_ref,
        "connectivity_check_hash": recorded.connectivity_check_hash,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "records guarded venue connectivity refs only; no raw order, no venue call, no money movement",
    }


@app.get("/api/research-os/execution/venue_connectivity_checks/summary")
def research_os_execution_venue_connectivity_check_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_VENUE_CONNECTIVITY_CHECKS.checks()
    return {
        "user": actor,
        "venue_connectivity_check_total": len(records),
        "venue_connectivity_checks": [_execution_venue_connectivity_check_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/venue_safety_attestations")
def research_os_record_execution_venue_safety_attestation(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = (
            payload.get("venue_safety_attestation")
            if isinstance(payload.get("venue_safety_attestation"), dict)
            else payload
        )
        if not isinstance(raw, dict):
            raise ValueError("venue_safety_attestation payload must be an object")
        _reject_raw_order_intent_fields(raw, path="venue_safety_attestation")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = execution_venue_safety_attestation_from_dict(raw)
        order_intent = EXECUTION_ORDER_INTENTS.intent(record.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(record.runtime_promotion_ref)
        venue_connectivity_check = None
        known_venue_connectivity_check_refs = None
        if record.venue_connectivity_check_ref:
            venue_connectivity_check = EXECUTION_VENUE_CONNECTIVITY_CHECKS.check(
                str(record.venue_connectivity_check_ref)
            )
            known_venue_connectivity_check_refs = {
                venue_connectivity_check.venue_connectivity_check_ref
            }
        decision = validate_execution_venue_safety_attestation(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_venue_connectivity_check_refs=known_venue_connectivity_check_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            venue_connectivity_check=venue_connectivity_check,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_VENUE_SAFETY_ATTESTATIONS.record_attestation(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_venue_connectivity_check_refs=known_venue_connectivity_check_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            venue_connectivity_check=venue_connectivity_check,
        )
        graph_refs = _record_execution_venue_safety_attestation_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "venue_safety_attestation_ref": recorded.venue_safety_attestation_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "venue_ref": recorded.venue_ref,
        "guarded_venue_ref": recorded.guarded_venue_ref,
        "runtime": recorded.runtime,
        "asset_class": recorded.asset_class,
        "attestation_status": recorded.attestation_status,
        "venue_connectivity_check_ref": recorded.venue_connectivity_check_ref,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "records guarded venue safety attestation refs only; no raw order, no venue call, no money movement",
    }


@app.get("/api/research-os/execution/venue_safety_attestations/summary")
def research_os_execution_venue_safety_attestation_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_VENUE_SAFETY_ATTESTATIONS.attestations()
    return {
        "user": actor,
        "venue_safety_attestation_total": len(records),
        "venue_safety_attestations": [_execution_venue_safety_attestation_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/venue_capabilities")
def research_os_record_execution_venue_capability(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("venue_capability") if isinstance(payload.get("venue_capability"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("venue_capability payload must be an object")
        _reject_raw_order_intent_fields(raw, path="venue_capability")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = execution_venue_capability_from_dict(raw)
        order_intent = EXECUTION_ORDER_INTENTS.intent(record.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(record.runtime_promotion_ref)
        venue_safety_attestation = None
        known_venue_safety_attestation_refs = None
        if record.venue_safety_attestation_ref:
            venue_safety_attestation = EXECUTION_VENUE_SAFETY_ATTESTATIONS.attestation(
                str(record.venue_safety_attestation_ref)
            )
            known_venue_safety_attestation_refs = {venue_safety_attestation.venue_safety_attestation_ref}
        decision = validate_execution_venue_capability(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_venue_safety_attestation_refs=known_venue_safety_attestation_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            venue_safety_attestation=venue_safety_attestation,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_VENUE_CAPABILITIES.record_capability(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_venue_safety_attestation_refs=known_venue_safety_attestation_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            venue_safety_attestation=venue_safety_attestation,
        )
        graph_refs = _record_execution_venue_capability_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "venue_capability_ref": recorded.venue_capability_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "venue_ref": recorded.venue_ref,
        "guarded_venue_ref": recorded.guarded_venue_ref,
        "submitter_ref": recorded.submitter_ref,
        "runtime": recorded.runtime,
        "asset_class": recorded.asset_class,
        "capability_status": recorded.capability_status,
        "can_submit_orders": recorded.can_submit_orders,
        "venue_safety_attestation_ref": recorded.venue_safety_attestation_ref,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "records guarded venue capability refs only; no raw order, no venue call, no money movement",
    }


@app.get("/api/research-os/execution/venue_capabilities/summary")
def research_os_execution_venue_capability_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_VENUE_CAPABILITIES.capabilities()
    return {
        "user": actor,
        "venue_capability_total": len(records),
        "venue_capabilities": [_execution_venue_capability_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/submit_requests/run")
def research_os_run_execution_submit_request_builder(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    builder_result: dict[str, Any] = {
        "builder_called": False,
        "api_place_order_called": False,
        "api_venue_call_called": False,
    }
    try:
        if not isinstance(payload, dict):
            raise ValueError("submit request builder payload must be an object")
        _reject_raw_order_intent_fields(payload, path="submit_request_builder")
        order_materialization_ref = str(payload.get("order_materialization_ref") or "")
        venue_capability_ref = str(payload.get("venue_capability_ref") or "")
        if not order_materialization_ref or not venue_capability_ref:
            raise ValueError("submit request builder requires order_materialization_ref and venue_capability_ref")
        order_materialization = EXECUTION_ORDER_MATERIALIZATIONS.materialization(order_materialization_ref)
        venue_capability = EXECUTION_VENUE_CAPABILITIES.capability(venue_capability_ref)
        order_intent = EXECUTION_ORDER_INTENTS.intent(order_materialization.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(order_materialization.runtime_promotion_ref)

        raw_result = EXECUTION_SUBMIT_REQUEST_BUILDER.build_submit_request(
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            actor=actor,
        )
        if not isinstance(raw_result, dict):
            raise ValueError("execution submit request builder must return a dict")
        _reject_raw_order_intent_fields(raw_result, path="submit_request_builder_result")
        if bool(raw_result.get("api_place_order_called", False)):
            raise ValueError("execution submit request builder cannot call place_order")
        if bool(raw_result.get("api_venue_call_called", False)):
            raise ValueError("execution submit request builder cannot call a venue API in this seam")
        raw_request = (
            raw_result.get("submit_request")
            if isinstance(raw_result.get("submit_request"), dict)
            else raw_result
        )
        if not isinstance(raw_request, dict):
            raise ValueError("execution submit request builder result must include a submit_request object")
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *_payload_tuple(raw_request.get("evidence_refs")),
                    *_payload_tuple(raw_request.get("evidence_ref")),
                    *_payload_tuple(raw_result.get("evidence_refs")),
                    *_payload_tuple(raw_result.get("evidence_ref")),
                )
            )
        )
        record = execution_submit_request_from_dict(
            {
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "order_materialization_ref": order_materialization.materialization_ref,
                "venue_capability_ref": venue_capability.venue_capability_ref,
                "submitter_ref": raw_request.get("submitter_ref") or venue_capability.submitter_ref,
                "guarded_venue_ref": raw_request.get("guarded_venue_ref") or venue_capability.guarded_venue_ref,
                "venue_ref": raw_request.get("venue_ref") or venue_capability.venue_ref,
                "submit_request_mode": raw_request.get("submit_request_mode")
                or str(venue_capability.runtime or order_materialization.materialization_mode),
                "submit_request_status": raw_request.get("submit_request_status") or raw_request.get("status") or "ready",
                "permission_gate_ref": raw_request.get("permission_gate_ref") or venue_capability.permission_gate_ref,
                "order_guard_ref": raw_request.get("order_guard_ref") or venue_capability.order_guard_ref,
                "idempotency_key": raw_request.get("idempotency_key") or venue_capability.idempotency_key,
                "audit_record_ref": raw_request.get("audit_record_ref") or raw_result.get("audit_record_ref"),
                "order_schema_ref": raw_request.get("order_schema_ref") or order_materialization.order_schema_ref,
                "order_payload_hash": raw_request.get("order_payload_hash") or order_materialization.order_payload_hash,
                "submit_request_schema_ref": raw_request.get("submit_request_schema_ref")
                or raw_result.get("submit_request_schema_ref"),
                "submit_request_hash": raw_request.get("submit_request_hash") or raw_result.get("submit_request_hash"),
                "client_order_ref_hash": raw_request.get("client_order_ref_hash")
                or raw_result.get("client_order_ref_hash"),
                "kill_switch_ref": raw_request.get("kill_switch_ref") or venue_capability.kill_switch_ref,
                "secret_ref": raw_request.get("secret_ref") or venue_capability.secret_ref,
                "responsibility_boundary_ref": raw_request.get("responsibility_boundary_ref")
                or venue_capability.responsibility_boundary_ref,
                "evidence_refs": evidence_refs,
                "recorded_by": actor,
            }
        )
        decision = validate_execution_submit_request(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs={order_materialization.materialization_ref},
            known_venue_capability_refs={venue_capability.venue_capability_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_SUBMIT_REQUESTS.record_request(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs={order_materialization.materialization_ref},
            known_venue_capability_refs={venue_capability.venue_capability_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
        )
        builder_result = {
            **raw_result,
            "builder_called": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
        }
        graph_refs = _record_execution_submit_request_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "submit_request_ref": recorded.submit_request_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "order_materialization_ref": recorded.order_materialization_ref,
        "venue_capability_ref": recorded.venue_capability_ref,
        "submitter_ref": recorded.submitter_ref,
        "guarded_venue_ref": recorded.guarded_venue_ref,
        "venue_ref": recorded.venue_ref,
        "submit_request_mode": recorded.submit_request_mode,
        "submit_request_status": recorded.submit_request_status,
        "order_payload_hash": recorded.order_payload_hash,
        "submit_request_hash": recorded.submit_request_hash,
        "builder_ref": str(raw_result.get("builder_ref") or getattr(EXECUTION_SUBMIT_REQUEST_BUILDER, "builder_ref", "")),
        "builder_called": bool(builder_result.get("builder_called", False)),
        "record_only": False,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "runs an injected refs-only submit request builder; no raw order, no venue call, no money movement",
    }


@app.post("/api/research-os/execution/submit_requests")
def research_os_record_execution_submit_request(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("submit_request") if isinstance(payload.get("submit_request"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("submit_request payload must be an object")
        _reject_raw_order_intent_fields(raw, path="submit_request")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = execution_submit_request_from_dict(raw)
        order_intent = EXECUTION_ORDER_INTENTS.intent(record.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(record.runtime_promotion_ref)
        order_materialization = EXECUTION_ORDER_MATERIALIZATIONS.materialization(record.order_materialization_ref)
        venue_capability = EXECUTION_VENUE_CAPABILITIES.capability(record.venue_capability_ref)
        decision = validate_execution_submit_request(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs={order_materialization.materialization_ref},
            known_venue_capability_refs={venue_capability.venue_capability_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_SUBMIT_REQUESTS.record_request(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs={order_materialization.materialization_ref},
            known_venue_capability_refs={venue_capability.venue_capability_ref},
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
        )
        graph_refs = _record_execution_submit_request_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "submit_request_ref": recorded.submit_request_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "order_materialization_ref": recorded.order_materialization_ref,
        "venue_capability_ref": recorded.venue_capability_ref,
        "submitter_ref": recorded.submitter_ref,
        "guarded_venue_ref": recorded.guarded_venue_ref,
        "venue_ref": recorded.venue_ref,
        "submit_request_mode": recorded.submit_request_mode,
        "submit_request_status": recorded.submit_request_status,
        "order_payload_hash": recorded.order_payload_hash,
        "submit_request_hash": recorded.submit_request_hash,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "records guarded submit request refs and hashes only; no raw order, no venue call, no money movement",
    }


@app.get("/api/research-os/execution/submit_requests/summary")
def research_os_execution_submit_request_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_SUBMIT_REQUESTS.requests()
    return {
        "user": actor,
        "submit_request_total": len(records),
        "submit_requests": [_execution_submit_request_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/order_submissions/run")
def research_os_run_execution_order_submission(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    submitter_result: dict[str, Any] = {
        "submitter_called": False,
        "api_venue_call_called": False,
    }
    try:
        if not isinstance(payload, dict):
            raise ValueError("order submission runner payload must be an object")
        _reject_raw_order_intent_fields(payload, path="order_submission_runner")
        submit_request_ref = str(payload.get("submit_request_ref") or "")
        if not submit_request_ref:
            raise ValueError("order submission runner requires submit_request_ref")
        submit_request = EXECUTION_SUBMIT_REQUESTS.request(submit_request_ref)
        order_intent = EXECUTION_ORDER_INTENTS.intent(submit_request.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(submit_request.runtime_promotion_ref)
        order_materialization = EXECUTION_ORDER_MATERIALIZATIONS.materialization(
            submit_request.order_materialization_ref
        )
        venue_capability = EXECUTION_VENUE_CAPABILITIES.capability(submit_request.venue_capability_ref)
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *_payload_tuple(payload.get("evidence_refs")),
                    *_payload_tuple(payload.get("evidence_ref")),
                )
            )
        )
        record = execution_order_submission_from_dict(
            {
                "order_intent_ref": submit_request.order_intent_ref,
                "runtime_promotion_ref": submit_request.runtime_promotion_ref,
                "submitter_ref": submit_request.submitter_ref,
                "guarded_venue_ref": submit_request.guarded_venue_ref,
                "venue_ref": submit_request.venue_ref,
                "submission_mode": submit_request.submit_request_mode,
                "permission_gate_ref": submit_request.permission_gate_ref,
                "order_guard_ref": submit_request.order_guard_ref,
                "idempotency_key": submit_request.idempotency_key,
                "audit_record_ref": payload.get("audit_record_ref")
                or f"audit:order_submission:{submit_request.submit_request_ref}",
                "kill_switch_ref": submit_request.kill_switch_ref,
                "secret_ref": submit_request.secret_ref,
                "responsibility_boundary_ref": submit_request.responsibility_boundary_ref,
                "submit_enabled": True,
                "order_materialization_ref": submit_request.order_materialization_ref,
                "venue_capability_ref": submit_request.venue_capability_ref,
                "submit_request_ref": submit_request.submit_request_ref,
                "submission_status": "recorded",
                "evidence_refs": evidence_refs,
                "recorded_by": actor,
            }
        )
        known_order_materialization_refs = {order_materialization.materialization_ref}
        known_venue_capability_refs = {venue_capability.venue_capability_ref}
        known_submit_request_refs = {submit_request.submit_request_ref}
        decision = validate_execution_order_submission(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs=known_order_materialization_refs,
            known_venue_capability_refs=known_venue_capability_refs,
            known_submit_request_refs=known_submit_request_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            submit_request=submit_request,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))

        raw_result = EXECUTION_ORDER_SUBMITTER.submit_guarded_order(
            submission=record,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            submit_request=submit_request,
            actor=actor,
        )
        if not isinstance(raw_result, dict):
            raise ValueError("guarded order submitter must return a dict")
        _reject_raw_order_intent_fields(raw_result, path="guarded_submitter_result")
        if bool(raw_result.get("api_place_order_called", False)):
            raise ValueError("guarded order submitter cannot report direct place_order")
        if bool(raw_result.get("api_venue_call_called", False)):
            raise ValueError("guarded order submitter cannot call a venue API in this runner seam")
        submitter_result = {
            **raw_result,
            "submitter_called": True,
            "api_venue_call_called": False,
        }
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *record.evidence_refs,
                    *_payload_tuple(raw_result.get("evidence_refs")),
                    *_payload_tuple(raw_result.get("evidence_ref")),
                )
            )
        )
        record = replace(
            record,
            submitter_ref=str(raw_result.get("submitter_ref") or record.submitter_ref),
            submission_status=str(raw_result.get("submission_status") or raw_result.get("status") or "submitted"),
            venue_order_ref=raw_result.get("venue_order_ref") or record.venue_order_ref,
            ack_ref=raw_result.get("ack_ref") or record.ack_ref,
            evidence_refs=evidence_refs,
            submission_ref="",
        )
        decision = validate_execution_order_submission(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs=known_order_materialization_refs,
            known_venue_capability_refs=known_venue_capability_refs,
            known_submit_request_refs=known_submit_request_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            submit_request=submit_request,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_ORDER_SUBMISSIONS.record_submission(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs=known_order_materialization_refs,
            known_venue_capability_refs=known_venue_capability_refs,
            known_submit_request_refs=known_submit_request_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            submit_request=submit_request,
        )
        graph_refs = _record_execution_order_submission_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
            submitter_result=submitter_result,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "submission_ref": recorded.submission_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "order_materialization_ref": recorded.order_materialization_ref,
        "venue_capability_ref": recorded.venue_capability_ref,
        "submit_request_ref": recorded.submit_request_ref,
        "submission_mode": recorded.submission_mode,
        "submission_status": recorded.submission_status,
        "submitter_ref": recorded.submitter_ref,
        "guarded_venue_ref": recorded.guarded_venue_ref,
        "venue_ref": recorded.venue_ref,
        "submit_enabled": recorded.submit_enabled,
        "submitter_called": bool(submitter_result.get("submitter_called", False)),
        "record_only": False,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        "venue_order_ref": recorded.venue_order_ref,
        "ack_ref": recorded.ack_ref,
        **graph_refs,
        "boundary": "runs an injected guarded submitter from a ready submit request; no raw order, no venue call in this runner seam, no money movement",
    }


@app.post("/api/research-os/execution/order_submissions")
def research_os_record_execution_order_submission(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    submitter_result: dict[str, Any] = {
        "submitter_called": False,
        "api_venue_call_called": False,
    }
    try:
        raw = payload.get("order_submission") if isinstance(payload.get("order_submission"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("order_submission payload must be an object")
        _reject_raw_order_intent_fields(raw, path="order_submission")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = execution_order_submission_from_dict(raw)
        order_intent = EXECUTION_ORDER_INTENTS.intent(record.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(record.runtime_promotion_ref)
        order_materialization = None
        known_order_materialization_refs = None
        if record.order_materialization_ref:
            order_materialization = EXECUTION_ORDER_MATERIALIZATIONS.materialization(str(record.order_materialization_ref))
            known_order_materialization_refs = {order_materialization.materialization_ref}
        venue_capability = None
        known_venue_capability_refs = None
        if record.venue_capability_ref:
            venue_capability = EXECUTION_VENUE_CAPABILITIES.capability(str(record.venue_capability_ref))
            known_venue_capability_refs = {venue_capability.venue_capability_ref}
        submit_request = None
        known_submit_request_refs = None
        if record.submit_request_ref:
            submit_request = EXECUTION_SUBMIT_REQUESTS.request(str(record.submit_request_ref))
            known_submit_request_refs = {submit_request.submit_request_ref}
        decision = validate_execution_order_submission(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs=known_order_materialization_refs,
            known_venue_capability_refs=known_venue_capability_refs,
            known_submit_request_refs=known_submit_request_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            submit_request=submit_request,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))

        if record.submit_enabled:
            raw_result = EXECUTION_ORDER_SUBMITTER.submit_guarded_order(
                submission=record,
                order_intent=order_intent,
                runtime_promotion=runtime_promotion,
                order_materialization=order_materialization,
                venue_capability=venue_capability,
                submit_request=submit_request,
                actor=actor,
            )
            if not isinstance(raw_result, dict):
                raise ValueError("guarded order submitter must return a dict")
            _reject_raw_order_intent_fields(raw_result, path="guarded_submitter_result")
            if bool(raw_result.get("api_place_order_called", False)):
                raise ValueError("guarded order submitter cannot report direct place_order")
            submitter_result = {
                **raw_result,
                "submitter_called": True,
                "api_venue_call_called": bool(raw_result.get("api_venue_call_called", False)),
            }
            evidence_refs = tuple(
                dict.fromkeys(
                    (
                        *record.evidence_refs,
                        *_payload_tuple(raw_result.get("evidence_refs")),
                        *(_payload_tuple(raw_result.get("evidence_ref"))),
                    )
                )
            )
            record = replace(
                record,
                submitter_ref=str(raw_result.get("submitter_ref") or record.submitter_ref),
                submission_status=str(
                    raw_result.get("submission_status")
                    or raw_result.get("status")
                    or record.submission_status
                    or "submitted"
                ),
                venue_order_ref=raw_result.get("venue_order_ref") or record.venue_order_ref,
                ack_ref=raw_result.get("ack_ref") or record.ack_ref,
                evidence_refs=evidence_refs,
                submission_ref="",
            )

        decision = validate_execution_order_submission(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs=known_order_materialization_refs,
            known_venue_capability_refs=known_venue_capability_refs,
            known_submit_request_refs=known_submit_request_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            submit_request=submit_request,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_ORDER_SUBMISSIONS.record_submission(
            record,
            known_order_intent_refs={order_intent.order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
            known_order_materialization_refs=known_order_materialization_refs,
            known_venue_capability_refs=known_venue_capability_refs,
            known_submit_request_refs=known_submit_request_refs,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            order_materialization=order_materialization,
            venue_capability=venue_capability,
            submit_request=submit_request,
        )
        graph_refs = _record_execution_order_submission_qro(
            recorded,
            order_intent,
            runtime_promotion,
            actor=actor,
            submitter_result=submitter_result,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "submission_ref": recorded.submission_ref,
        "order_intent_ref": recorded.order_intent_ref,
        "runtime_promotion_ref": recorded.runtime_promotion_ref,
        "order_materialization_ref": recorded.order_materialization_ref,
        "venue_capability_ref": recorded.venue_capability_ref,
        "submit_request_ref": recorded.submit_request_ref,
        "submission_mode": recorded.submission_mode,
        "submission_status": recorded.submission_status,
        "submitter_ref": recorded.submitter_ref,
        "guarded_venue_ref": recorded.guarded_venue_ref,
        "venue_ref": recorded.venue_ref,
        "submit_enabled": recorded.submit_enabled,
        "submitter_called": bool(submitter_result.get("submitter_called", False)),
        "record_only": not recorded.submit_enabled,
        "api_place_order_called": False,
        "api_venue_call_called": bool(submitter_result.get("api_venue_call_called", False)),
        "venue_order_ref": recorded.venue_order_ref,
        "ack_ref": recorded.ack_ref,
        **graph_refs,
        "boundary": "records guarded order submission refs; API never calls place_order directly and default submitter is disabled",
    }


@app.get("/api/research-os/execution/order_submissions/summary")
def research_os_execution_order_submission_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_ORDER_SUBMISSIONS.submissions()
    return {
        "user": actor,
        "order_submission_total": len(records),
        "order_submissions": [_execution_order_submission_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/venue_events/run")
def research_os_run_execution_venue_event_ingester(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    ingester_result: dict[str, Any] = {
        "ingester_called": False,
        "api_place_order_called": False,
        "api_venue_call_called": False,
    }
    try:
        if not isinstance(payload, dict):
            raise ValueError("venue event ingester payload must be an object")
        _reject_raw_order_intent_fields(payload, path="venue_event_ingester")
        submission_ref = str(payload.get("submission_ref") or "")
        if not submission_ref:
            raise ValueError("venue event ingester requires submission_ref")
        submission = EXECUTION_ORDER_SUBMISSIONS.submission(submission_ref)
        order_intent = EXECUTION_ORDER_INTENTS.intent(submission.order_intent_ref)
        runtime_promotion = RUNTIME_PROMOTIONS.promotion(submission.runtime_promotion_ref)
        raw_result = EXECUTION_VENUE_EVENT_INGESTER.ingest_event(
            submission=submission,
            order_intent=order_intent,
            runtime_promotion=runtime_promotion,
            actor=actor,
        )
        if not isinstance(raw_result, dict):
            raise ValueError("execution venue event ingester must return a dict")
        _reject_raw_order_intent_fields(raw_result, path="venue_event_ingester_result")
        if bool(raw_result.get("api_place_order_called", False)):
            raise ValueError("execution venue event ingester cannot report direct place_order")
        if bool(raw_result.get("api_venue_call_called", False)):
            raise ValueError("execution venue event ingester cannot call a venue API in this seam")
        raw_event = raw_result.get("venue_event") if isinstance(raw_result.get("venue_event"), dict) else raw_result
        if not isinstance(raw_event, dict):
            raise ValueError("execution venue event ingester result must include a venue_event object")
        event_kind = str(raw_event.get("event_kind") or raw_event.get("status") or "accepted")
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *_payload_tuple(raw_event.get("evidence_refs")),
                    *_payload_tuple(raw_event.get("evidence_ref")),
                    *_payload_tuple(raw_result.get("evidence_refs")),
                    *_payload_tuple(raw_result.get("evidence_ref")),
                )
            )
        )
        record = execution_venue_event_from_dict(
            {
                "order_intent_ref": submission.order_intent_ref,
                "runtime_promotion_ref": submission.runtime_promotion_ref,
                "venue_ref": raw_event.get("venue_ref") or submission.venue_ref,
                "event_kind": event_kind,
                "status": raw_event.get("status") or event_kind,
                "audit_record_ref": raw_event.get("audit_record_ref")
                or raw_result.get("audit_record_ref")
                or f"audit:venue_event:{submission.submission_ref}",
                "order_guard_ref": raw_event.get("order_guard_ref") or submission.order_guard_ref,
                "idempotency_key": raw_event.get("idempotency_key") or submission.idempotency_key,
                "venue_order_ref": raw_event.get("venue_order_ref") or submission.venue_order_ref,
                "client_order_ref": raw_event.get("client_order_ref"),
                "ack_ref": raw_event.get("ack_ref") or submission.ack_ref,
                "fill_ref": raw_event.get("fill_ref"),
                "reconcile_ref": raw_event.get("reconcile_ref"),
                "quantity_ref": raw_event.get("quantity_ref"),
                "price_ref": raw_event.get("price_ref"),
                "fee_ref": raw_event.get("fee_ref"),
                "raw_event_hash": raw_event.get("raw_event_hash") or raw_result.get("raw_event_hash"),
                "evidence_refs": evidence_refs,
                "recorded_by": actor,
            }
        )
        decision = validate_execution_venue_event(
            record,
            known_order_intent_refs={record.order_intent_ref},
            known_runtime_promotion_refs={record.runtime_promotion_ref},
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_VENUE_EVENTS.record_event(
            record,
            known_order_intent_refs={record.order_intent_ref},
            known_runtime_promotion_refs={record.runtime_promotion_ref},
        )
        ingester_result = {
            **raw_result,
            "ingester_called": True,
            "api_place_order_called": False,
            "api_venue_call_called": False,
        }
        graph_refs = _record_execution_venue_event_qro(recorded, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "venue_event_ref": recorded.venue_event_ref,
        "submission_ref": submission.submission_ref,
        "event_kind": recorded.event_kind,
        "status": recorded.status,
        "venue_order_ref": recorded.venue_order_ref,
        "ack_ref": recorded.ack_ref,
        "fill_ref": recorded.fill_ref,
        "ingester_ref": str(raw_result.get("ingester_ref") or getattr(EXECUTION_VENUE_EVENT_INGESTER, "ingester_ref", "")),
        "ingester_called": bool(ingester_result.get("ingester_called", False)),
        "record_only": False,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "runs an injected refs-only venue event ingester; no raw venue payload, no venue call in this seam, no money movement",
    }


@app.post("/api/research-os/execution/venue_events")
def research_os_record_execution_venue_event(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("venue_event") if isinstance(payload.get("venue_event"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("venue_event payload must be an object")
        _reject_raw_order_intent_fields(raw, path="venue_event")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or actor}
        record = execution_venue_event_from_dict(raw)
        EXECUTION_ORDER_INTENTS.intent(record.order_intent_ref)
        RUNTIME_PROMOTIONS.promotion(record.runtime_promotion_ref)
        decision = validate_execution_venue_event(
            record,
            known_order_intent_refs={record.order_intent_ref},
            known_runtime_promotion_refs={record.runtime_promotion_ref},
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_VENUE_EVENTS.record_event(
            record,
            known_order_intent_refs={record.order_intent_ref},
            known_runtime_promotion_refs={record.runtime_promotion_ref},
        )
        graph_refs = _record_execution_venue_event_qro(recorded, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "venue_event_ref": recorded.venue_event_ref,
        "event_kind": recorded.event_kind,
        "status": recorded.status,
        "recorded_by": actor,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "records external venue event refs only; this API does not place orders, call venues, or move money",
    }


@app.get("/api/research-os/execution/venue_events/summary")
def research_os_execution_venue_event_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_VENUE_EVENTS.events()
    return {
        "user": actor,
        "venue_event_total": len(records),
        "venue_events": [_execution_venue_event_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/reconciliations")
def research_os_record_execution_reconciliation(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("reconciliation") if isinstance(payload.get("reconciliation"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("reconciliation payload must be an object")
        _reject_raw_order_intent_fields(raw, path="reconciliation")
        order_intent_ref = str(raw.get("order_intent_ref") or "")
        runtime_promotion_ref = str(raw.get("runtime_promotion_ref") or "")
        audit_record_ref = str(raw.get("audit_record_ref") or "")
        venue_order_ref = raw.get("venue_order_ref")
        evidence_refs = _payload_tuple(raw.get("evidence_refs"))
        EXECUTION_ORDER_INTENTS.intent(order_intent_ref)
        RUNTIME_PROMOTIONS.promotion(runtime_promotion_ref)
        record = reconcile_execution_venue_events(
            order_intent_ref=order_intent_ref,
            runtime_promotion_ref=runtime_promotion_ref,
            venue_order_ref=venue_order_ref,
            audit_record_ref=audit_record_ref,
            events=tuple(EXECUTION_VENUE_EVENTS.events()),
            evidence_refs=evidence_refs,
            recorded_by=actor,
        )
        known_event_refs = {event.venue_event_ref for event in EXECUTION_VENUE_EVENTS.events()}
        decision = validate_execution_reconciliation(
            record,
            known_order_intent_refs={order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion_ref},
            known_venue_event_refs=known_event_refs,
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_RECONCILIATIONS.record_reconciliation(
            record,
            known_order_intent_refs={order_intent_ref},
            known_runtime_promotion_refs={runtime_promotion_ref},
            known_venue_event_refs=known_event_refs,
        )
        graph_refs = _record_execution_reconciliation_qro(recorded, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "reconciliation_ref": recorded.reconciliation_ref,
        "status": recorded.status,
        "action_required": recorded.action_required,
        "discrepancy_refs": list(recorded.discrepancy_refs),
        "recorded_by": actor,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "records reconciliation over existing venue event refs only; no venue call, no order placement, no money movement",
    }


@app.get("/api/research-os/execution/reconciliations/summary")
def research_os_execution_reconciliation_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_RECONCILIATIONS.reconciliations()
    return {
        "user": actor,
        "reconciliation_total": len(records),
        "reconciliations": [_execution_reconciliation_summary(record) for record in records],
    }


@app.post("/api/research-os/execution/reconciliation_actions")
def research_os_record_execution_reconciliation_action(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        raw = payload.get("reconciliation_action") if isinstance(payload.get("reconciliation_action"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("reconciliation_action payload must be an object")
        _reject_raw_order_intent_fields(raw, path="reconciliation_action")
        reconciliation_ref = str(raw.get("reconciliation_ref") or "")
        reconciliation = EXECUTION_RECONCILIATIONS.reconciliation(reconciliation_ref)
        evidence_refs = _payload_tuple(raw.get("evidence_refs")) or (reconciliation_ref,)
        raw = {
            **raw,
            "recorded_by": raw.get("recorded_by") or actor,
            "evidence_refs": evidence_refs,
        }
        record = execution_reconciliation_action_from_dict(raw)
        decision = validate_execution_reconciliation_action(
            record,
            known_reconciliation_refs={reconciliation.reconciliation_ref},
            action_required_by_ref={reconciliation.reconciliation_ref: reconciliation.action_required},
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        recorded = EXECUTION_RECONCILIATION_ACTIONS.record_action(
            record,
            known_reconciliation_refs={reconciliation.reconciliation_ref},
            action_required_by_ref={reconciliation.reconciliation_ref: reconciliation.action_required},
        )
        graph_refs = _record_execution_reconciliation_action_qro(recorded, reconciliation, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "action_ref": recorded.action_ref,
        "reconciliation_ref": recorded.reconciliation_ref,
        "action_kind": recorded.action_kind,
        "action_status": recorded.action_status,
        "recorded_by": actor,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
        **graph_refs,
        "boundary": "records reconciliation follow-up action refs only; no venue call, no order placement, no money movement",
    }


@app.get("/api/research-os/execution/reconciliation_actions/summary")
def research_os_execution_reconciliation_action_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    records = EXECUTION_RECONCILIATION_ACTIONS.actions()
    return {
        "user": actor,
        "reconciliation_action_total": len(records),
        "reconciliation_actions": [_execution_reconciliation_action_summary(record) for record in records],
    }


def _default_reconciliation_action_kind(record: ExecutionReconciliationRecord) -> str:
    if record.status == "needs_reconcile":
        return "request_missing_reconcile"
    if record.status in {"terminal_conflict", "venue_order_mismatch"}:
        return "escalate_manual_review"
    return "investigate"


def _run_pending_execution_reconciliation_actions(
    *,
    actor: str,
    audit_record_ref: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    owner_ref: str = "execution-monitor",
) -> dict[str, Any]:
    pending = [record for record in EXECUTION_RECONCILIATIONS.reconciliations() if record.action_required]
    batch_ref = "execution_reconcile_action_batch_" + content_hash(
        {
            "reconciliation_refs": [record.reconciliation_ref for record in pending],
            "evidence_refs": evidence_refs,
            "owner_ref": owner_ref,
        }
    )
    resolved_audit_record_ref = str(audit_record_ref or f"audit:{batch_ref}")
    existing = {
        (action.reconciliation_ref, action.action_kind)
        for action in EXECUTION_RECONCILIATION_ACTIONS.actions()
        if action.action_status in {"open", "acknowledged"}
    }
    prepared: list[tuple[ExecutionReconciliationActionRecord, ExecutionReconciliationRecord]] = []
    for reconciliation in pending:
        action_kind = _default_reconciliation_action_kind(reconciliation)
        key = (reconciliation.reconciliation_ref, action_kind)
        if key in existing:
            continue
        action = execution_reconciliation_action_from_dict(
            {
                "reconciliation_ref": reconciliation.reconciliation_ref,
                "action_kind": action_kind,
                "action_status": "open",
                "action_owner_ref": owner_ref,
                "remediation_ref": f"remediation:{action_kind}:{reconciliation.reconciliation_ref}",
                "audit_record_ref": resolved_audit_record_ref,
                "evidence_refs": (
                    batch_ref,
                    reconciliation.reconciliation_ref,
                    *reconciliation.discrepancy_refs,
                    *evidence_refs,
                ),
                "recorded_by": actor,
            }
        )
        decision = validate_execution_reconciliation_action(
            action,
            known_reconciliation_refs={reconciliation.reconciliation_ref},
            action_required_by_ref={reconciliation.reconciliation_ref: reconciliation.action_required},
        )
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        prepared.append((action, reconciliation))
    created: list[dict[str, Any]] = []
    for action, reconciliation in prepared:
        recorded = EXECUTION_RECONCILIATION_ACTIONS.record_action(
            action,
            known_reconciliation_refs={reconciliation.reconciliation_ref},
            action_required_by_ref={reconciliation.reconciliation_ref: reconciliation.action_required},
        )
        graph_refs = _record_execution_reconciliation_action_qro(recorded, reconciliation, actor=actor)
        created.append({**_execution_reconciliation_action_summary(recorded), **graph_refs})
    return {
        "batch_ref": batch_ref,
        "pending_total": len(pending),
        "created_count": len(created),
        "skipped_count": len(pending) - len(created),
        "created": created,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
    }


@app.post("/api/research-os/execution/reconciliation_actions/run_pending")
def research_os_run_pending_execution_reconciliation_actions(
    payload: dict | None = Body(default=None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    raw = payload or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="reconciliation action batch payload must be an object")
    _reject_raw_order_intent_fields(raw, path="reconciliation_action_batch")
    evidence_refs = _payload_tuple(raw.get("evidence_refs"))
    owner_ref = str(raw.get("action_owner_ref") or "execution-monitor")
    try:
        result = _run_pending_execution_reconciliation_actions(
            actor=actor,
            audit_record_ref=raw.get("audit_record_ref"),
            evidence_refs=evidence_refs,
            owner_ref=owner_ref,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "user": actor,
        **result,
    }


@app.post("/api/research-os/execution/reconciliations/run_pending")
def research_os_run_pending_execution_reconciliations(
    payload: dict | None = Body(default=None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    raw = payload or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="reconciliation batch payload must be an object")
    _reject_raw_order_intent_fields(raw, path="reconciliation_batch")
    evidence_refs = _payload_tuple(raw.get("evidence_refs"))
    batch_ref = "execution_reconcile_batch_" + content_hash(
        {
            "venue_event_refs": [event.venue_event_ref for event in EXECUTION_VENUE_EVENTS.events()],
            "evidence_refs": evidence_refs,
        }
    )
    audit_record_ref = str(raw.get("audit_record_ref") or f"audit:{batch_ref}")
    groups: dict[tuple[str, str, str | None], list[ExecutionVenueEventRecord]] = {}
    try:
        for event in EXECUTION_VENUE_EVENTS.events():
            EXECUTION_ORDER_INTENTS.intent(event.order_intent_ref)
            RUNTIME_PROMOTIONS.promotion(event.runtime_promotion_ref)
            key = (event.order_intent_ref, event.runtime_promotion_ref, event.venue_order_ref)
            groups.setdefault(key, []).append(event)
        existing = {
            (
                record.order_intent_ref,
                record.runtime_promotion_ref,
                record.venue_order_ref,
                tuple(record.event_refs),
            )
            for record in EXECUTION_RECONCILIATIONS.reconciliations()
        }
        prepared: list[ExecutionReconciliationRecord] = []
        for (order_intent_ref, runtime_promotion_ref, venue_order_ref), events in sorted(groups.items()):
            record = reconcile_execution_venue_events(
                order_intent_ref=order_intent_ref,
                runtime_promotion_ref=runtime_promotion_ref,
                venue_order_ref=venue_order_ref,
                audit_record_ref=audit_record_ref,
                events=tuple(events),
                evidence_refs=(batch_ref, *evidence_refs),
                recorded_by=actor,
            )
            key = (
                record.order_intent_ref,
                record.runtime_promotion_ref,
                record.venue_order_ref,
                tuple(record.event_refs),
            )
            if key not in existing:
                decision = validate_execution_reconciliation(
                    record,
                    known_order_intent_refs={order_intent_ref},
                    known_runtime_promotion_refs={runtime_promotion_ref},
                    known_venue_event_refs={event.venue_event_ref for event in events},
                )
                if not decision.accepted:
                    raise ValueError(",".join(violation.code for violation in decision.violations))
                prepared.append(record)
        created: list[dict[str, Any]] = []
        for record in prepared:
            recorded = EXECUTION_RECONCILIATIONS.record_reconciliation(
                record,
                known_order_intent_refs={record.order_intent_ref},
                known_runtime_promotion_refs={record.runtime_promotion_ref},
                known_venue_event_refs=set(record.event_refs),
            )
            graph_refs = _record_execution_reconciliation_qro(recorded, actor=actor)
            created.append({**_execution_reconciliation_summary(recorded), **graph_refs})
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "user": actor,
        "batch_ref": batch_ref,
        "group_total": len(groups),
        "created_count": len(created),
        "skipped_count": len(groups) - len(created),
        "created": created,
        "record_only": True,
        "api_place_order_called": False,
        "api_venue_call_called": False,
    }


@app.post("/api/research-os/settings/secret_refs")
def research_os_settings_record_secret_ref(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = ONBOARDING_REGISTRY.record_secret_ref(_secret_ref_from_payload(payload))
        return {"secret_ref": record.secret_ref, "recorded_by": user.username}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/secret_values")
def research_os_settings_store_secret_value(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record, keystore_record, keystore_ref = _settings_secret_value_from_payload(payload)
        KEYSTORE.store(keystore_record)
        stored = ONBOARDING_REGISTRY.record_secret_ref(record)
        return {
            "secret_ref": stored.secret_ref,
            "scope": stored.scope,
            "status": stored.status.value if hasattr(stored.status, "value") else str(stored.status),
            "keystore_ref": keystore_ref,
            "keystore_backend": KEYSTORE.backend_name,
            "secret_value_stored": True,
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/data_sources")
def research_os_settings_record_data_source(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = ONBOARDING_REGISTRY.record_data_source_asset(_data_source_asset_from_payload(payload))
        decision = validate_data_source_asset(record)
        return {
            "source_ref": record.source_ref,
            "export_allowed": decision.export_allowed,
            "share_allowed": decision.share_allowed,
            "warning_codes": [warning.code for warning in decision.warnings],
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/ingestion_skills")
def research_os_settings_record_ingestion_skill(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = ONBOARDING_REGISTRY.record_ingestion_skill(_ingestion_skill_from_payload(payload))
        return {
            "skill_id": record.skill_id,
            "source_ref": record.source_ref,
            "secret_refs": list(record.secret_refs),
            "lifecycle_state": record.lifecycle_state.value
            if hasattr(record.lifecycle_state, "value")
            else str(record.lifecycle_state),
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/data_connector_checks")
def research_os_settings_test_data_connector(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        request = _data_connector_check_payload(payload)
        skill_id = str(request.get("skill_id") or "")
        if not skill_id:
            raise ValueError("data_connector_check.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(skill_id)
        source_ref = str(request.get("source_ref") or skill.source_ref)
        if source_ref != skill.source_ref:
            raise ValueError("data_connector_check.source_ref must match the IngestionSkill source_ref")
        source = ONBOARDING_REGISTRY.data_source(source_ref)
        requested_refs = _settings_tuple(request.get("secret_refs"))
        if requested_refs and set(requested_refs) != set(skill.secret_refs):
            raise ValueError("data_connector_check.secret_refs must match the IngestionSkill secret_refs")
        secrets: list[SecretRefRecord] = []
        for ref in skill.secret_refs:
            secret = ONBOARDING_REGISTRY.secret_ref(ref)
            status = secret.status.value if hasattr(secret.status, "value") else str(secret.status)
            if status == "revoked":
                raise ValueError("connector check cannot use a revoked SecretRef")
            secrets.append(secret)
        _settings_require_declared_secret_values(secrets)
        try:
            raw_result = DATA_CONNECTOR_CONNECTION_CHECKER.check_connection(
                skill=skill,
                source=source,
                secrets=tuple(secrets),
                actor=user.username,
            )
        except Exception as exc:  # noqa: BLE001 - connector failures become audited failed checks.
            message = str(exc)
            if contains_plaintext_secret(message):
                raise ValueError("connector checker failure contained plaintext credential material") from exc
            checker_ref = getattr(DATA_CONNECTOR_CONNECTION_CHECKER, "checker_ref", "data_connector_connection_checker")
            raw_result = {
                "checker_ref": checker_ref,
                "status": "disabled" if isinstance(DATA_CONNECTOR_CONNECTION_CHECKER, DisabledDataConnectorConnectionChecker) else "failed",
                "health_status": "disabled" if isinstance(DATA_CONNECTOR_CONNECTION_CHECKER, DisabledDataConnectorConnectionChecker) else "failed",
                "quota_status": "unknown",
                "error_code": "checker_disabled"
                if isinstance(DATA_CONNECTOR_CONNECTION_CHECKER, DisabledDataConnectorConnectionChecker)
                else type(exc).__name__,
                "error_message": message,
            }
        if not isinstance(raw_result, dict):
            raise ValueError("data connector checker must return an object")
        if contains_plaintext_secret(raw_result):
            raise ValueError("connector checker result cannot contain plaintext credential material")
        record = ONBOARDING_REGISTRY.record_data_connector_check(
            _data_connector_check_record_from_result(
                request,
                raw_result,
                skill=skill,
                source=source,
                actor=user.username,
            )
        )
        return {
            **_data_connector_check_summary(record),
            "ok": record.status == "ok",
            "recorded_by": user.username,
        }
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/ingestion_skill_runs")
def research_os_settings_run_ingestion_skill(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        request = _data_connector_ingestion_run_payload(payload)
        skill_id = str(request.get("skill_id") or request.get("skill_ref") or "").strip()
        if not skill_id:
            raise ValueError("ingestion_skill_run.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(skill_id)
        lifecycle_state = skill.lifecycle_state.value if hasattr(skill.lifecycle_state, "value") else str(skill.lifecycle_state)
        if str(lifecycle_state).lower() != "active":
            raise ValueError("ingestion_skill_run requires an active IngestionSkill")
        source = ONBOARDING_REGISTRY.data_source(skill.source_ref)
        secrets_by_ref: dict[str, SecretRefRecord] = {}
        secrets: list[SecretRefRecord] = []
        for ref in skill.secret_refs:
            secret = ONBOARDING_REGISTRY.secret_ref(ref)
            status = secret.status.value if hasattr(secret.status, "value") else str(secret.status)
            if status == "revoked":
                raise ValueError("ingestion_skill_run cannot use a revoked SecretRef")
            secrets_by_ref[ref] = secret
            secrets.append(secret)
        _settings_require_declared_secret_values(secrets)
        skill_decision = validate_ingestion_skill_run(skill, secrets=secrets_by_ref)
        if not skill_decision.accepted:
            raise ValueError("; ".join(violation.code for violation in skill_decision.violations))
        connector_check = _latest_ok_connector_check(skill, request)
        check_decision = validate_data_connector_connection_check(
            connector_check,
            skill=skill,
            source=source,
            secrets=secrets_by_ref,
        )
        if not check_decision.accepted:
            raise ValueError("; ".join(violation.code for violation in check_decision.violations))
        secret_ref = str(request.get("secret_ref") or (skill.secret_refs[0] if skill.secret_refs else "")).strip()
        if secrets_by_ref:
            if secret_ref not in secrets_by_ref:
                raise ValueError("ingestion_skill_run.secret_ref must belong to the recorded IngestionSkill")
            update_secret = secrets_by_ref[secret_ref]
        else:
            if request.get("secret_ref"):
                raise ValueError("ingestion_skill_run.secret_ref cannot be supplied for auth_mode=none connectors")
            if not ingestion_skill_allows_no_secret_connector(skill):
                raise ValueError("ingestion_skill_run requires SecretRef unless IngestionSkill declares auth_mode=none")
            update_secret = None
        try:
            raw_result = DATA_CONNECTOR_INGESTION_RUNNER.run_ingestion(
                skill=skill,
                source=source,
                secrets=tuple(secrets),
                connector_check=connector_check,
                request=request,
                actor=user.username,
            )
        except Exception as exc:  # noqa: BLE001 - connector failures must not write dataset/update records.
            message = str(exc)
            if contains_plaintext_secret(message):
                raise ValueError("ingestion runner failure contained plaintext credential material") from exc
            raise ValueError(message) from exc
        fetch_result, runner_result = _verified_runner_fetch_result(raw_result, skill=skill)
        version, update = _record_ingestion_dataset_version_and_update(
            skill=skill,
            source=source,
            secret=update_secret,
            connector_check=connector_check,
            fetch_result=fetch_result,
            runner_result=runner_result,
            actor=user.username,
        )
        return {
            "skill_id": skill.skill_id,
            "source_ref": source.source_ref,
            "connector_check_ref": connector_check.check_ref,
            "dataset_id": version.dataset_id,
            "dataset_version_ref": _dataset_version_ref(version),
            "version_id": version.version_id,
            "checksum": version.sha256,
            "row_count": version.row_count,
            "coverage_start_utc": version.coverage_start_utc,
            "coverage_end_utc": version.coverage_end_utc,
            "file_paths": version.file_paths,
            "schema_probe_ref": version.metadata.get("schema_probe_ref"),
            "update_ref": update.update_ref,
            "quality_verdict_ref": update.quality_verdict_ref,
            "known_at_ref": update.known_at_ref,
            "effective_at_ref": update.effective_at_ref,
            "recorded_by": user.username,
        }
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/data_connector_field_mappings")
def research_os_settings_record_data_connector_field_mapping(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        raw_record = _data_connector_field_mapping_from_payload(payload)
        if not raw_record.skill_id:
            raise ValueError("data_connector_field_mapping.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(raw_record.skill_id)
        source_ref = raw_record.source_ref or skill.source_ref
        if source_ref != skill.source_ref:
            raise ValueError("data_connector_field_mapping.source_ref must match the IngestionSkill source_ref")
        source = ONBOARDING_REGISTRY.data_source(source_ref)
        if raw_record.schema_probe_ref:
            schema_probe = ONBOARDING_REGISTRY.data_connector_schema_probe(raw_record.schema_probe_ref)
        else:
            probes = [
                probe
                for probe in ONBOARDING_REGISTRY.data_connector_schema_probes()
                if probe.skill_id == skill.skill_id and probe.source_ref == source.source_ref
            ]
            if not probes:
                raise ValueError("data_connector_field_mapping requires a recorded schema probe")
            schema_probe = sorted(probes, key=lambda item: str(item.probed_at or ""))[-1]
        mapping_ref = raw_record.mapping_ref or skill.schema_mapping_ref
        record_without_hash = replace(
            raw_record,
            mapping_ref=mapping_ref,
            source_ref=source.source_ref,
            schema_probe_ref=schema_probe.probe_ref,
            schema_signature_hash=raw_record.schema_signature_hash or schema_probe.schema_signature_hash,
            mapping_hash=None,
            recorded_by=user.username,
        )
        expected_hash = data_connector_field_mapping_hash(record_without_hash)
        if raw_record.mapping_hash and raw_record.mapping_hash != expected_hash:
            raise ValueError("data_connector_field_mapping.mapping_hash does not match mapping content")
        record = replace(record_without_hash, mapping_hash=expected_hash)
        decision = validate_data_connector_field_mapping(
            record,
            skill=skill,
            source=source,
            schema_probe=schema_probe,
        )
        if not decision.accepted:
            raise ValueError("; ".join(violation.code for violation in decision.violations))
        recorded = ONBOARDING_REGISTRY.record_data_connector_field_mapping(record)
        return {
            **_data_connector_field_mapping_summary(recorded),
            "recorded_by": user.username,
        }
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/pit_bitemporal_rules")
def research_os_settings_record_pit_bitemporal_rule(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        raw_record = _data_connector_pit_bitemporal_rule_from_payload(payload)
        if not raw_record.skill_id:
            raise ValueError("data_connector_pit_bitemporal_rule.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(raw_record.skill_id)
        source_ref = raw_record.source_ref or skill.source_ref
        if source_ref != skill.source_ref:
            raise ValueError("data_connector_pit_bitemporal_rule.source_ref must match the IngestionSkill source_ref")
        source = ONBOARDING_REGISTRY.data_source(source_ref)
        if raw_record.field_mapping_ref:
            field_mapping = ONBOARDING_REGISTRY.data_connector_field_mapping(raw_record.field_mapping_ref)
        else:
            mappings = [
                mapping
                for mapping in ONBOARDING_REGISTRY.data_connector_field_mappings()
                if mapping.skill_id == skill.skill_id and mapping.source_ref == source.source_ref
            ]
            if not mappings:
                raise ValueError("data_connector_pit_bitemporal_rule requires a recorded field mapping")
            field_mapping = sorted(mappings, key=lambda item: str(item.mapped_at or ""))[-1]
        schema_probe_ref = raw_record.schema_probe_ref or field_mapping.schema_probe_ref
        schema_probe = ONBOARDING_REGISTRY.data_connector_schema_probe(schema_probe_ref)
        known_at_column = raw_record.known_at_column if raw_record.known_at_column is not None else field_mapping.known_at_column
        effective_at_column = (
            raw_record.effective_at_column
            if raw_record.effective_at_column is not None
            else field_mapping.effective_at_column
        )
        base_evidence = [str(ref) for ref in raw_record.evidence_refs]
        for ref in (field_mapping.mapping_ref, schema_probe.probe_ref):
            if ref not in base_evidence:
                base_evidence.append(ref)
        record_without_hash = replace(
            raw_record,
            rule_ref=raw_record.rule_ref or skill.pit_bitemporal_rules_ref,
            source_ref=source.source_ref,
            field_mapping_ref=field_mapping.mapping_ref,
            schema_probe_ref=schema_probe.probe_ref,
            event_time_column=raw_record.event_time_column or field_mapping.event_time_column,
            known_at_column=known_at_column,
            effective_at_column=effective_at_column,
            known_at_policy=raw_record.known_at_policy or ("source_column" if known_at_column else "connector_fetched_at"),
            effective_at_policy=raw_record.effective_at_policy or ("source_column" if effective_at_column else "event_time"),
            asof_join_policy=raw_record.asof_join_policy or "known_at_lte_decision_time_latest",
            timezone=raw_record.timezone or "UTC",
            calendar_ref=raw_record.calendar_ref or f"calendar:{source.source_ref}:default",
            lookahead_guard_ref=raw_record.lookahead_guard_ref or f"lookahead_guard:{skill.skill_id}:pit",
            monotonicity_check_ref=raw_record.monotonicity_check_ref
            or f"monotonicity:{field_mapping.mapping_ref}:event_known",
            restatement_policy=raw_record.restatement_policy or "latest_known_at_before_decision_time",
            evidence_refs=tuple(base_evidence),
            rule_hash=None,
            recorded_by=user.username,
        )
        expected_hash = data_connector_pit_bitemporal_rule_hash(record_without_hash)
        if raw_record.rule_hash and raw_record.rule_hash != expected_hash:
            raise ValueError("data_connector_pit_bitemporal_rule.rule_hash does not match rule content")
        record = replace(record_without_hash, rule_hash=expected_hash)
        decision = validate_data_connector_pit_bitemporal_rule(
            record,
            skill=skill,
            source=source,
            field_mapping=field_mapping,
            schema_probe=schema_probe,
        )
        if not decision.accepted:
            raise ValueError("; ".join(violation.code for violation in decision.violations))
        recorded = ONBOARDING_REGISTRY.record_data_connector_pit_bitemporal_rule(record)
        return {
            **_data_connector_pit_bitemporal_rule_summary(recorded),
            "recorded_by": user.username,
        }
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/dataset_semantics")
def research_os_settings_record_dataset_semantics(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        request = _settings_dataset_semantics_payload(payload)
        skill_id = str(request.get("skill_id") or request.get("skill_ref") or "").strip()
        if not skill_id:
            raise ValueError("dataset_semantics.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(skill_id)
        source = ONBOARDING_REGISTRY.data_source(skill.source_ref)
        update_ref = str(request.get("update_ref") or "").strip()
        if update_ref:
            update = ASSET_LIFECYCLE_REGISTRY.ingestion_skill_update(update_ref)
        else:
            updates = [
                record
                for record in ASSET_LIFECYCLE_REGISTRY.ingestion_skill_updates()
                if record.skill_ref == skill.skill_id and record.source_ref == source.source_ref
            ]
            if not updates:
                raise ValueError("dataset_semantics requires a recorded IngestionSkillUpdate")
            update = sorted(updates, key=lambda item: str(item.update_ref or ""))[-1]
        if update.skill_ref != skill.skill_id:
            raise ValueError("dataset_semantics.update_ref must match IngestionSkill skill_id")
        if update.source_ref != source.source_ref:
            raise ValueError("dataset_semantics.update_ref must match IngestionSkill source_ref")
        version = _resolve_dataset_version_ref(update.dataset_version_ref)
        if version.dataset_id != skill.output_dataset_id:
            raise ValueError("dataset_semantics DatasetVersion must match IngestionSkill output_dataset_id")
        if update.checksum != version.sha256:
            raise ValueError("dataset_semantics checksum must match DatasetVersion sha256")
        rule_ref = str(request.get("pit_bitemporal_rules_ref") or request.get("rule_ref") or skill.pit_bitemporal_rules_ref).strip()
        pit_rule = ONBOARDING_REGISTRY.data_connector_pit_bitemporal_rule(rule_ref)
        if pit_rule.skill_id != skill.skill_id or pit_rule.source_ref != source.source_ref:
            raise ValueError("dataset_semantics PIT rule must match IngestionSkill and DataSourceAsset")
        use_context = str(request.get("use_context") or ValidationUseContext.CONFIRMATORY_VALIDATION.value)
        dataset_ref = str(request.get("dataset_ref") or update.dataset_version_ref or _dataset_version_ref(version))
        lineage_refs = tuple(
            ref
            for ref in (
                update.lineage_ref,
                update.update_ref,
                pit_rule.rule_ref,
                pit_rule.field_mapping_ref,
                pit_rule.schema_probe_ref,
                *update.evidence_refs,
            )
            if ref
        )
        record = DatasetSemanticsRecord(
            dataset_ref=dataset_ref,
            source_ref=source.source_ref,
            version=version.version_id,
            known_at_ref=update.known_at_ref,
            effective_at_ref=update.effective_at_ref,
            pit_bitemporal_rules_ref=pit_rule.rule_ref,
            quality_status=str(request.get("quality_status") or "passed"),
            lineage_refs=lineage_refs,
            freshness_status=str(update.freshness_status or skill.freshness_status or "unknown"),
            checksum=version.sha256,
            sampling_rule_ref=request.get("sampling_rule_ref"),
            adjustment_formula_ref=request.get("adjustment_formula_ref"),
            asof_join_rule_ref=pit_rule.rule_ref,
            missingness_model_ref=request.get("missingness_model_ref"),
            survivorship_rule_ref=request.get("survivorship_rule_ref"),
        )
        _reject_raw_market_data_fields(record.to_dict(), path="dataset_semantics")
        recorded = MARKET_DATA_REGISTRY.record_dataset(record, use_context=use_context)
        graph_refs = _record_market_data_dataset_qro(
            recorded,
            actor=actor,
            use_context=use_context,
            entrypoint_ref="api:research_os.settings.dataset_semantics",
            pass_name="settings_dataset_semantics_qro_to_dataset_ir",
            tool_record_ref="api:settings.dataset_semantics",
        )
        return {
            "dataset_ref": recorded.dataset_ref,
            "dataset_version_ref": update.dataset_version_ref,
            "update_ref": update.update_ref,
            "pit_bitemporal_rules_ref": recorded.pit_bitemporal_rules_ref,
            "use_context": use_context,
            "recorded_by": actor,
            "raw_data_stored": False,
            "connector_called": False,
            **graph_refs,
            "boundary": "records dataset semantics refs only; no connector call, no raw market data rows",
        }
    except HTTPException:
        raise
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/instrument_specs")
def research_os_settings_record_instrument_spec(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        request = _settings_instrument_spec_payload(payload)
        skill_id = str(request.get("skill_id") or request.get("skill_ref") or "").strip()
        if not skill_id:
            raise ValueError("instrument_spec.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(skill_id)
        source = ONBOARDING_REGISTRY.data_source(skill.source_ref)
        dataset = _settings_dataset_for_skill(skill, source, request)
        pit_rule = None
        if dataset.pit_bitemporal_rules_ref:
            pit_rule = ONBOARDING_REGISTRY.data_connector_pit_bitemporal_rule(dataset.pit_bitemporal_rules_ref)
            if pit_rule.skill_id != skill.skill_id or pit_rule.source_ref != source.source_ref:
                raise ValueError("instrument_spec DatasetSemantics PIT rule must match IngestionSkill")
        asset_class = str(request.get("asset_class") or _settings_infer_asset_class(skill, source))
        instrument_type = str(request.get("instrument_type") or _settings_default_instrument_type(asset_class))
        instrument_ref = str(
            request.get("instrument_ref")
            or f"instrument:{_settings_ref_fragment(skill.skill_id)}:{_settings_ref_fragment(asset_class)}:{_settings_ref_fragment(instrument_type)}"
        )
        record = InstrumentSpec(
            instrument_ref=instrument_ref,
            asset_class=asset_class,
            instrument_type=instrument_type,
            currency=str(request.get("currency") or _settings_default_currency(asset_class)),
            exchange_calendar_ref=str(
                request.get("exchange_calendar_ref")
                or (pit_rule.calendar_ref if pit_rule else "")
                or f"calendar:{source.source_ref}:default"
            ),
            contract_spec_ref=request.get("contract_spec_ref") or f"contract_spec:{instrument_ref}:default",
            option_chain_ref=request.get("option_chain_ref"),
            futures_roll_rule_ref=request.get("futures_roll_rule_ref"),
            continuous_contract_rule_ref=request.get("continuous_contract_rule_ref"),
            corporate_actions_ref=request.get("corporate_actions_ref"),
            symbol_mapping_ref=request.get("symbol_mapping_ref") or skill.schema_mapping_ref,
            expiry_ref=request.get("expiry_ref"),
            strike_ref=request.get("strike_ref"),
            contract_multiplier_ref=request.get("contract_multiplier_ref"),
            settlement_ref=request.get("settlement_ref"),
            exercise_style_ref=request.get("exercise_style_ref"),
            margin_ref=request.get("margin_ref"),
        )
        _reject_raw_market_data_fields(record.to_dict(), path="instrument_spec")
        recorded = MARKET_DATA_REGISTRY.record_instrument(record)
        graph_refs = _record_market_data_instrument_qro(
            recorded,
            actor=actor,
            entrypoint_ref="api:research_os.settings.instrument_specs",
            pass_name="settings_instrument_spec_qro_to_instrument_ir",
            tool_record_ref="api:settings.instrument_specs",
        )
        return {
            "instrument_ref": recorded.instrument_ref,
            "dataset_ref": dataset.dataset_ref,
            "asset_class": recorded.asset_class,
            "instrument_type": recorded.instrument_type,
            "currency": recorded.currency,
            "recorded_by": actor,
            "raw_data_stored": False,
            "connector_called": False,
            "venue_called": False,
            **graph_refs,
            "boundary": "records InstrumentSpec metadata from Settings refs only; no connector call, no venue permission check",
        }
    except HTTPException:
        raise
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/capability_matrices")
def research_os_settings_record_capability_matrix(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        request = _settings_capability_matrix_payload(payload)
        skill_id = str(request.get("skill_id") or request.get("skill_ref") or "").strip()
        if not skill_id:
            raise ValueError("capability_matrix.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(skill_id)
        source = ONBOARDING_REGISTRY.data_source(skill.source_ref)
        dataset = _settings_dataset_for_skill(skill, source, request)
        instrument_ref = str(request.get("instrument_ref") or "").strip()
        if instrument_ref:
            instrument = MARKET_DATA_REGISTRY.instrument(instrument_ref)
        else:
            candidates = [
                record
                for record in MARKET_DATA_REGISTRY.instruments()
                if record.symbol_mapping_ref == skill.schema_mapping_ref
            ]
            if not candidates:
                raise ValueError("capability_matrix requires a recorded InstrumentSpec")
            instrument = sorted(candidates, key=lambda item: str(item.instrument_ref or ""))[-1]
        if instrument.symbol_mapping_ref and instrument.symbol_mapping_ref != skill.schema_mapping_ref:
            raise ValueError("capability_matrix InstrumentSpec must match IngestionSkill schema_mapping_ref")
        use_context = str(request.get("use_context") or ValidationUseContext.CONFIRMATORY_VALIDATION.value)

        def request_bool(name: str, default: bool) -> bool:
            value = request.get(name)
            if value is None:
                return default
            return bool(value)

        live = request_bool("live", False)
        testnet = request_bool("testnet", False)
        matrix_ref = str(
            request.get("matrix_ref")
            or f"capability:{_settings_ref_fragment(skill.skill_id)}:{_settings_ref_fragment(instrument.asset_class)}:{_settings_ref_fragment(instrument.instrument_type)}"
        )
        record = MarketCapabilityMatrixRecord(
            matrix_ref=matrix_ref,
            asset_class=instrument.asset_class,
            instrument_type=instrument.instrument_type,
            research=request_bool("research", True),
            backtest=request_bool("backtest", True),
            paper=request_bool("paper", True),
            testnet=testnet,
            live=live,
            long=request_bool("long", True),
            short=request_bool("short", False),
            leverage=request_bool("leverage", False),
            options=request_bool("options", instrument.instrument_type.lower() == "option"),
            margin=request_bool("margin", instrument.instrument_type.lower() in {"future", "futures", "perpetual"}),
            borrow=request_bool("borrow", False),
            data_availability=request.get("data_availability") or dataset.dataset_ref,
            cost_model_availability=request.get("cost_model_availability")
            or f"cost_model:{instrument.asset_class}:{instrument.instrument_type}:default",
            execution_availability=request.get("execution_availability")
            or ("execution:permission_required" if live or testnet else "execution:paper_only"),
            permission_requirement=request.get("permission_requirement") or (None if live else skill.permission_scope),
        )
        _reject_raw_market_data_fields(record.to_dict(), path="capability_matrix")
        recorded = MARKET_DATA_REGISTRY.record_capability_matrix(record, use_context=use_context)
        graph_refs = _record_market_data_capability_qro(
            recorded,
            actor=actor,
            use_context=use_context,
            entrypoint_ref="api:research_os.settings.capability_matrices",
            pass_name="settings_capability_matrix_qro_to_capability_ir",
            tool_record_ref="api:settings.capability_matrices",
        )
        return {
            "matrix_ref": recorded.matrix_ref,
            "dataset_ref": dataset.dataset_ref,
            "instrument_ref": instrument.instrument_ref,
            "use_context": use_context,
            "recorded_by": actor,
            "raw_data_stored": False,
            "connector_called": False,
            "venue_called": False,
            **graph_refs,
            "boundary": "records declared MarketCapabilityMatrix refs from Settings metadata only; no provider, broker, or live venue call",
        }
    except HTTPException:
        raise
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/market_data_use_validations")
def research_os_settings_record_market_data_use_validation(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        request = _settings_market_data_use_payload(payload)
        _reject_raw_market_data_fields(request, path="market_data_use")
        skill_id = str(request.get("skill_id") or request.get("skill_ref") or "").strip()
        if not skill_id:
            raise ValueError("market_data_use.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(skill_id)
        source = ONBOARDING_REGISTRY.data_source(skill.source_ref)
        dataset = _settings_dataset_for_skill(skill, source, request)
        instrument = _settings_instrument_for_skill(skill, request)
        capability = _settings_capability_for_instrument(instrument, request)
        use_context = str(request.get("use_context") or ValidationUseContext.CONFIRMATORY_VALIDATION.value)
        capital_record = cross_currency_capital_record_from_dict(request.get("capital_record"))
        transformation_claims = tuple(
            data_transformation_claim_from_dict(item)
            for item in _market_data_transformation_payloads(request.get("transformation_claims"))
        )
        request_ref = str(request.get("request_ref") or "").strip() or "market_data_use_request:" + content_hash(
            {
                "skill_id": skill.skill_id,
                "dataset_ref": dataset.dataset_ref,
                "instrument_ref": instrument.instrument_ref,
                "capability_matrix_ref": capability.matrix_ref,
                "use_context": use_context,
            }
        )
        request_record = MarketDataUseRequest(
            request_ref=request_ref,
            use_context=use_context,
            datasets=(dataset,),
            instruments=(instrument,),
            capability_matrix=capability,
            capital_record=capital_record,
            transformation_claims=transformation_claims,
        )
        decision = validate_market_data_use(request_record)
        if not decision.accepted:
            raise ValueError(",".join(violation.code for violation in decision.violations))
        capital_refs = tuple(
            ref
            for ref in (
                capital_record.fx_conversion_ref if capital_record else "",
                capital_record.collateral_ref if capital_record else "",
                capital_record.margin_ref if capital_record else "",
                capital_record.leverage_ref if capital_record else "",
                capital_record.net_exposure_ref if capital_record else "",
                capital_record.gross_exposure_ref if capital_record else "",
                capital_record.capital_allocation_ref if capital_record else "",
                capital_record.financing_cost_ref if capital_record else "",
            )
            if ref
        )
        transformation_refs = tuple(claim.transform_ref for claim in transformation_claims)
        validation_ref = str(request.get("validation_ref") or "").strip() or "market_data_use:" + content_hash(
            {
                "request_ref": request_ref,
                "use_context": use_context,
                "dataset_refs": (dataset.dataset_ref,),
                "instrument_refs": (instrument.instrument_ref,),
                "capability_matrix_ref": capability.matrix_ref,
                "capital_refs": capital_refs,
                "transformation_refs": transformation_refs,
            }
        )
        now = _dt.datetime.now(_dt.UTC).isoformat()
        evidence_refs = tuple(
            ref
            for ref in (
                validation_ref,
                request_ref,
                skill.skill_id,
                dataset.dataset_ref,
                instrument.instrument_ref,
                capability.matrix_ref,
                *capital_refs,
                *transformation_refs,
            )
            if ref
        )
        record = MarketDataUseValidationRecord(
            validation_ref=validation_ref,
            request_ref=request_ref,
            use_context=use_context,
            dataset_refs=(dataset.dataset_ref,),
            instrument_refs=(instrument.instrument_ref,),
            capability_matrix_ref=capability.matrix_ref,
            capital_record_ref=str(request.get("capital_record_ref") or "").strip() or None,
            transformation_refs=transformation_refs,
            accepted=True,
            violation_codes=(),
            evidence_refs=evidence_refs,
            recorded_by=actor,
            created_at_utc=now,
        )
        recorded = MARKET_DATA_REGISTRY.record_use_validation(record)
        graph_refs = _record_market_data_use_validation_qro(recorded, actor=actor)
        return {
            "validation_ref": recorded.validation_ref,
            "request_ref": recorded.request_ref,
            "use_context": recorded.use_context,
            "accepted": recorded.accepted,
            "recorded_by": actor,
            "raw_data_stored": False,
            "connector_called": False,
            "strategy_builder_called": False,
            "venue_called": False,
            **graph_refs,
            "boundary": "records accepted refs-only market data use gate from Settings metadata; no connector, strategy builder, or venue call",
        }
    except HTTPException:
        raise
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/data_connector_onboarding_runs")
def research_os_settings_run_data_connector_onboarding(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    try:
        request = _settings_data_connector_onboarding_run_payload(payload)
        skill_id = str(request.get("skill_id") or request.get("skill_ref") or "").strip()
        if not skill_id:
            raise ValueError("data_connector_onboarding_run.skill_id is required")
        skill = ONBOARDING_REGISTRY.ingestion_skill(skill_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    completed_steps: list[str] = []
    step_outputs: dict[str, dict[str, Any]] = {}

    def fail_step(step_name: str, exc: Exception) -> None:
        detail = str(exc)
        if contains_plaintext_secret(detail):
            detail = "step failed with plaintext credential material redacted"
        raise HTTPException(
            status_code=422,
            detail={
                "failed_step": step_name,
                "completed_steps": tuple(completed_steps),
                "error": detail,
            },
        ) from exc

    def prepare_step(
        step_name: str,
        *,
        step_key: str,
        wrapper_key: str,
        defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return _settings_onboarding_merge_payload(
                request,
                step_key=step_key,
                wrapper_key=wrapper_key,
                skill_id=skill_id,
                defaults=defaults,
            )
        except (KeyError, ValueError) as exc:
            fail_step(step_name, exc)

    def run_step(step_name: str, step_payload: dict[str, Any], handler) -> dict[str, Any]:
        try:
            result = handler(step_payload, user=user)
        except HTTPException as exc:
            detail: Any = exc.detail
            if contains_plaintext_secret(detail):
                detail = "step failed with plaintext credential material redacted"
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "failed_step": step_name,
                    "completed_steps": tuple(completed_steps),
                    "error": detail,
                },
            ) from exc
        if contains_plaintext_secret(result):
            raise HTTPException(
                status_code=422,
                detail={
                    "failed_step": step_name,
                    "completed_steps": tuple(completed_steps),
                    "error": "step result contained plaintext credential material",
                },
            )
        completed_steps.append(step_name)
        step_outputs[step_name] = result
        return result

    check_payload = prepare_step(
        "connection_check",
        step_key="connection_check",
        wrapper_key="data_connector_check",
    )
    check = run_step("connection_check", check_payload, research_os_settings_test_data_connector)

    ingestion_payload = prepare_step(
        "ingestion_run",
        step_key="ingestion_run",
        wrapper_key="ingestion_skill_run",
        defaults={"connector_check_ref": check.get("check_ref")},
    )
    run = run_step("ingestion_run", ingestion_payload, research_os_settings_run_ingestion_skill)

    raw_mapping_payload = prepare_step(
        "field_mapping",
        step_key="field_mapping",
        wrapper_key="data_connector_field_mapping",
        defaults={"schema_probe_ref": run.get("schema_probe_ref")},
    )
    try:
        mapping_payload = _settings_auto_field_mapping_payload(
            skill=skill,
            schema_probe_ref=str(raw_mapping_payload.get("schema_probe_ref") or ""),
            step_payload=raw_mapping_payload,
        )
    except (KeyError, ValueError) as exc:
        fail_step("field_mapping", exc)
    mapping = run_step(
        "field_mapping",
        mapping_payload,
        research_os_settings_record_data_connector_field_mapping,
    )

    pit_payload = prepare_step(
        "pit_bitemporal_rule",
        step_key="pit_bitemporal_rule",
        wrapper_key="data_connector_pit_bitemporal_rule",
        defaults={
            "field_mapping_ref": mapping.get("mapping_ref"),
            "schema_probe_ref": mapping.get("schema_probe_ref"),
        },
    )
    pit = run_step(
        "pit_bitemporal_rule",
        pit_payload,
        research_os_settings_record_pit_bitemporal_rule,
    )

    semantics_payload = prepare_step(
        "dataset_semantics",
        step_key="dataset_semantics",
        wrapper_key="dataset_semantics",
        defaults={
            "update_ref": run.get("update_ref"),
            "pit_bitemporal_rules_ref": pit.get("rule_ref"),
        },
    )
    semantics = run_step(
        "dataset_semantics",
        semantics_payload,
        research_os_settings_record_dataset_semantics,
    )

    instrument_payload = prepare_step(
        "instrument_spec",
        step_key="instrument_spec",
        wrapper_key="instrument_spec",
        defaults={"dataset_ref": semantics.get("dataset_ref")},
    )
    instrument = run_step(
        "instrument_spec",
        instrument_payload,
        research_os_settings_record_instrument_spec,
    )

    capability_payload = prepare_step(
        "capability_matrix",
        step_key="capability_matrix",
        wrapper_key="capability_matrix",
        defaults={
            "dataset_ref": semantics.get("dataset_ref"),
            "instrument_ref": instrument.get("instrument_ref"),
        },
    )
    capability = run_step(
        "capability_matrix",
        capability_payload,
        research_os_settings_record_capability_matrix,
    )

    use_payload = prepare_step(
        "market_data_use",
        step_key="market_data_use",
        wrapper_key="market_data_use",
        defaults={
            "dataset_ref": semantics.get("dataset_ref"),
            "instrument_ref": instrument.get("instrument_ref"),
            "capability_matrix_ref": capability.get("matrix_ref"),
        },
    )
    use_validation = run_step(
        "market_data_use",
        use_payload,
        research_os_settings_record_market_data_use_validation,
    )
    try:
        one_shot_compiler_refs = _compile_market_data_use_validation_qro(
            MARKET_DATA_REGISTRY.use_validation(str(use_validation.get("validation_ref") or "")),
            qro_id=str(use_validation.get("qro_id") or ""),
            actor=actor,
            entrypoint_ref="api:research_os.settings.data_connector_onboarding_runs",
            pass_name="settings_data_connector_onboarding_qro_to_market_data_ir",
            tool_record_ref="api:settings.data_connector_onboarding_runs",
        )
    except (KeyError, ValueError) as exc:
        fail_step("compiler_coverage", exc)
    completed_steps.append("compiler_coverage")
    step_outputs["compiler_coverage"] = one_shot_compiler_refs

    run_ref = "data_connector_onboarding_run:" + content_hash(
        {
            "skill_id": skill_id,
            "connector_check_ref": check.get("check_ref"),
            "dataset_version_ref": run.get("dataset_version_ref"),
            "mapping_ref": mapping.get("mapping_ref"),
            "pit_bitemporal_rules_ref": pit.get("rule_ref"),
            "dataset_ref": semantics.get("dataset_ref"),
            "instrument_ref": instrument.get("instrument_ref"),
            "capability_matrix_ref": capability.get("matrix_ref"),
            "market_data_use_validation_ref": use_validation.get("validation_ref"),
        }
    )
    return {
        "run_ref": run_ref,
        "skill_id": skill_id,
        "recorded_by": actor,
        "completed_steps": tuple(completed_steps),
        "connector_check_ref": check.get("check_ref"),
        "dataset_version_ref": run.get("dataset_version_ref"),
        "update_ref": run.get("update_ref"),
        "schema_probe_ref": run.get("schema_probe_ref"),
        "mapping_ref": mapping.get("mapping_ref"),
        "mapping_method": mapping.get("mapping_method"),
        "pit_bitemporal_rules_ref": pit.get("rule_ref"),
        "dataset_ref": semantics.get("dataset_ref"),
        "instrument_ref": instrument.get("instrument_ref"),
        "capability_matrix_ref": capability.get("matrix_ref"),
        "market_data_use_validation_ref": use_validation.get("validation_ref"),
        "accepted": bool(use_validation.get("accepted")),
        "step_outputs": step_outputs,
        "connector_called": True,
        "dataset_file_written": True,
        "strategy_builder_called": False,
        "venue_called": False,
        **one_shot_compiler_refs,
        "boundary": "runs Settings connector check and ingestion, then records mapping/PIT/market-data refs; no strategy builder or venue execution call",
    }


@app.post("/api/research-os/settings/ingestion_skill_updates")
def research_os_settings_record_ingestion_skill_update(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = replace(_ingestion_skill_update_from_payload(payload), recorded_by=user.username)
        skill = ONBOARDING_REGISTRY.ingestion_skill(record.skill_ref)
        if record.skill_version != skill.version:
            raise ValueError("ingestion_skill_update.skill_version must match the recorded IngestionSkill version")
        if record.source_ref != skill.source_ref:
            raise ValueError("ingestion_skill_update.source_ref must match the recorded IngestionSkill source_ref")
        if record.secret_ref not in skill.secret_refs:
            raise ValueError("ingestion_skill_update.secret_ref must belong to the recorded IngestionSkill")
        secret = ONBOARDING_REGISTRY.secret_ref(str(record.secret_ref))
        status = secret.status.value if hasattr(secret.status, "value") else str(secret.status)
        if status == "revoked":
            raise ValueError("ingestion_skill_update cannot use a revoked SecretRef")
        version = _resolve_dataset_version_ref(record.dataset_version_ref)
        if version.dataset_id != skill.output_dataset_id:
            raise ValueError("ingestion_skill_update.dataset_version_ref must match IngestionSkill output_dataset_id")
        if record.checksum != version.sha256:
            raise ValueError("ingestion_skill_update.checksum must match DatasetVersion sha256")
        if record.row_count is not None and record.row_count != version.row_count:
            raise ValueError("ingestion_skill_update.row_count must match DatasetVersion row_count")
        recorded = ASSET_LIFECYCLE_REGISTRY.record_ingestion_skill_update(record)
        return {
            **_ingestion_skill_update_summary(recorded),
            "recorded_by": user.username,
        }
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/llm_providers")
def research_os_settings_record_llm_provider(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = ONBOARDING_REGISTRY.record_llm_provider(_llm_provider_from_payload(payload))
        return {"provider_id": record.provider_id, "auth_refs": list(record.auth_refs), "recorded_by": user.username}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/llm_provider_health_snapshots")
def research_os_settings_record_llm_provider_health_snapshot(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        candidate = _llm_provider_health_snapshot_from_payload(payload)
        record = ONBOARDING_REGISTRY.record_llm_provider_health_snapshot(
            replace(candidate, recorded_by=candidate.recorded_by or user.username, snapshot_hash=None)
        )
        return {**_llm_provider_health_snapshot_summary(record), "recorded_by": user.username}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/credential_pools")
def research_os_settings_record_credential_pool(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = ONBOARDING_REGISTRY.record_credential_pool(_credential_pool_from_payload(payload))
        return {"pool_id": record.pool_id, "provider_id": record.provider_id, "recorded_by": user.username}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/settings/routing_policies")
def research_os_settings_record_routing_policy(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = ONBOARDING_REGISTRY.record_routing_policy(_routing_policy_from_payload(payload))
        return {
            "routing_policy_id": record.routing_policy_id,
            "credential_pool_ref": record.credential_pool_ref,
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/settings/summary")
def research_os_settings_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    secret_refs = ONBOARDING_REGISTRY.secret_refs()
    data_sources = ONBOARDING_REGISTRY.data_sources()
    ingestion_skills = ONBOARDING_REGISTRY.ingestion_skills()
    data_connector_checks = ONBOARDING_REGISTRY.data_connector_checks()
    data_connector_schema_probes = ONBOARDING_REGISTRY.data_connector_schema_probes()
    data_connector_field_mappings = ONBOARDING_REGISTRY.data_connector_field_mappings()
    data_connector_pit_bitemporal_rules = ONBOARDING_REGISTRY.data_connector_pit_bitemporal_rules()
    ingestion_skill_updates = ASSET_LIFECYCLE_REGISTRY.ingestion_skill_updates()
    market_data_datasets = MARKET_DATA_REGISTRY.datasets()
    market_data_instruments = MARKET_DATA_REGISTRY.instruments()
    market_data_capability_matrices = MARKET_DATA_REGISTRY.capability_matrices()
    market_data_use_validations = MARKET_DATA_REGISTRY.use_validations()
    providers = ONBOARDING_REGISTRY.llm_providers()
    provider_health_snapshots = ONBOARDING_REGISTRY.llm_provider_health_snapshots()
    pools = ONBOARDING_REGISTRY.credential_pools()
    policies = ONBOARDING_REGISTRY.routing_policies()
    return {
        "user": user.username,
        "secret_ref_total": len(secret_refs),
        "data_source_total": len(data_sources),
        "ingestion_skill_total": len(ingestion_skills),
        "data_connector_check_total": len(data_connector_checks),
        "data_connector_schema_probe_total": len(data_connector_schema_probes),
        "data_connector_field_mapping_total": len(data_connector_field_mappings),
        "data_connector_pit_bitemporal_rule_total": len(data_connector_pit_bitemporal_rules),
        "ingestion_skill_update_total": len(ingestion_skill_updates),
        "market_data_dataset_total": len(market_data_datasets),
        "market_data_instrument_total": len(market_data_instruments),
        "market_data_capability_matrix_total": len(market_data_capability_matrices),
        "market_data_use_validation_total": len(market_data_use_validations),
        "llm_provider_total": len(providers),
        "llm_provider_health_snapshot_total": len(provider_health_snapshots),
        "credential_pool_total": len(pools),
        "routing_policy_total": len(policies),
        "secret_refs": [_secret_ref_summary(record) for record in secret_refs],
        "data_sources": [_data_source_asset_summary(record) for record in data_sources],
        "ingestion_skills": [_ingestion_skill_summary(record) for record in ingestion_skills],
        "data_connector_checks": [_data_connector_check_summary(record) for record in data_connector_checks],
        "data_connector_schema_probes": [
            _data_connector_schema_probe_summary(record) for record in data_connector_schema_probes
        ],
        "data_connector_field_mappings": [
            _data_connector_field_mapping_summary(record) for record in data_connector_field_mappings
        ],
        "data_connector_pit_bitemporal_rules": [
            _data_connector_pit_bitemporal_rule_summary(record) for record in data_connector_pit_bitemporal_rules
        ],
        "ingestion_skill_updates": [_ingestion_skill_update_summary(record) for record in ingestion_skill_updates],
        "market_data_datasets": [_market_data_dataset_summary(record) for record in market_data_datasets],
        "market_data_instruments": [_market_data_instrument_summary(record) for record in market_data_instruments],
        "market_data_capability_matrices": [
            _market_data_capability_summary(record) for record in market_data_capability_matrices
        ],
        "market_data_use_validations": [
            _market_data_use_validation_summary(record) for record in market_data_use_validations
        ],
        "llm_providers": [_llm_provider_summary(record) for record in providers],
        "llm_provider_health_snapshots": [
            _llm_provider_health_snapshot_summary(record) for record in provider_health_snapshots
        ],
        "credential_pools": [_credential_pool_summary(record) for record in pools],
        "routing_policies": [_routing_policy_summary(record) for record in policies],
    }


@app.post("/api/research-os/model_governance/passports")
def research_os_model_governance_record_passport(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        passport = model_passport_from_dict(_model_governance_raw_payload(payload))
        recorded = MODEL_GOVERNANCE_REGISTRY.record_passport(
            passport,
            change_events=_model_governance_change_events(payload),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "passport_id": recorded.passport_id,
        "model_version_ref": recorded.model_version_ref,
        "recorded_by": user.username,
    }


@app.post("/api/research-os/model_governance/monitoring_profiles")
def research_os_model_governance_record_monitoring_profile(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        raw = payload.get("monitoring_profile") if isinstance(payload.get("monitoring_profile"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("monitoring_profile payload must be an object")
        record = MODEL_GOVERNANCE_REGISTRY.record_monitoring_profile(monitoring_profile_from_dict(raw))
        qro_refs = _record_model_monitoring_profile_qro(record, actor=_api_actor_ref(user))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "monitoring_profile_id": record.monitoring_profile_id,
        "model_version_ref": record.model_version_ref,
        "model_passport_ref": record.model_passport_ref,
        "recorded_by": user.username,
        **qro_refs,
    }


@app.post("/api/research-os/model_governance/recertification_records")
def research_os_model_governance_record_recertification(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        raw = payload.get("recertification_record") if isinstance(payload.get("recertification_record"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("recertification_record payload must be an object")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or user.username}
        record = MODEL_GOVERNANCE_REGISTRY.record_recertification_record(
            recertification_record_from_dict(raw)
        )
        qro_refs = _record_model_recertification_qro(record, actor=_api_actor_ref(user))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "recertification_record_id": record.recertification_record_id,
        "model_version_ref": record.model_version_ref,
        "model_passport_ref": record.model_passport_ref,
        "trigger": getattr(record.trigger, "value", record.trigger),
        "recorded_by": user.username,
        **qro_refs,
    }


@app.post("/api/research-os/model_governance/artifact_inspections")
def research_os_model_governance_record_artifact_inspection(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        raw = payload.get("artifact_inspection") if isinstance(payload.get("artifact_inspection"), dict) else payload
        if not isinstance(raw, dict):
            raise ValueError("artifact_inspection payload must be an object")
        raw = {**raw, "recorded_by": raw.get("recorded_by") or user.username}
        record = MODEL_GOVERNANCE_REGISTRY.record_artifact_inspection(
            artifact_inspection_record_from_dict(raw)
        )
        qro_refs = _record_model_artifact_inspection_qro(record, actor=_api_actor_ref(user))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "artifact_inspection_record_id": record.artifact_inspection_record_id,
        "model_version_ref": record.model_version_ref,
        "model_passport_ref": record.model_passport_ref,
        "artifact_ref": record.artifact_ref,
        "inspection_ref": record.inspection_ref,
        "recorded_by": user.username,
        **qro_refs,
    }


@app.get("/api/research-os/model_governance/summary")
def research_os_model_governance_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    passports = MODEL_GOVERNANCE_REGISTRY.passports()
    monitoring_profiles = MODEL_GOVERNANCE_REGISTRY.monitoring_profiles()
    recertification_records = MODEL_GOVERNANCE_REGISTRY.recertification_records()
    artifact_inspections = MODEL_GOVERNANCE_REGISTRY.artifact_inspections()
    serving_invocations = MODEL_GOVERNANCE_REGISTRY.serving_invocations()
    return {
        "user": user.username,
        "passport_total": len(passports),
        "monitoring_profile_total": len(monitoring_profiles),
        "recertification_record_total": len(recertification_records),
        "artifact_inspection_total": len(artifact_inspections),
        "serving_invocation_total": len(serving_invocations),
        "passports": [
            {
                **_model_passport_summary(passport),
                "change_events": MODEL_GOVERNANCE_REGISTRY.change_events(passport.passport_id),
            }
            for passport in passports
        ],
        "monitoring_profiles": [_model_monitoring_profile_summary(profile) for profile in monitoring_profiles],
        "recertification_records": [
            _model_recertification_summary(record)
            for record in recertification_records
        ],
        "artifact_inspections": [
            _model_artifact_inspection_summary(record)
            for record in artifact_inspections
        ],
        "serving_invocations": [
            _model_serving_invocation_summary(record)
            for record in serving_invocations
        ],
    }


def _compiler_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _compiler_ir_from_payload(payload: dict[str, Any]) -> CompilerIRRecord:
    raw = payload.get("ir") if isinstance(payload.get("ir"), dict) else payload
    return CompilerIRRecord(
        ir_ref=str(raw.get("ir_ref") or ""),
        source_qro_refs=_compiler_tuple(raw.get("source_qro_refs")),
        graph_command_refs=_compiler_tuple(raw.get("graph_command_refs")),
        canonical_command_refs=_compiler_tuple(raw.get("canonical_command_refs")),
        node_refs=_compiler_tuple(raw.get("node_refs")),
        edge_refs=_compiler_tuple(raw.get("edge_refs")),
        artifact_refs=_compiler_tuple(raw.get("artifact_refs")),
        theory_binding_refs=_compiler_tuple(raw.get("theory_binding_refs")),
        consistency_check_refs=_compiler_tuple(raw.get("consistency_check_refs")),
        evidence_refs=_compiler_tuple(raw.get("evidence_refs")),
        validation_refs=_compiler_tuple(raw.get("validation_refs")),
        permission_ref=str(raw.get("permission_ref") or ""),
        deterministic_run_plan_ref=str(raw.get("deterministic_run_plan_ref") or ""),
        rollback_ref=str(raw.get("rollback_ref") or ""),
        environment_lock_ref=str(raw.get("environment_lock_ref") or ""),
        target_runtime=raw.get("target_runtime") or RuntimeStatus.OFFLINE.value,
        compiler_version=str(raw.get("compiler_version") or "governed-compiler-ir.v1"),
        mock_profile=str(raw.get("mock_profile") or "none"),
    )


def _compiler_pass_from_payload(payload: dict[str, Any]) -> CompilerPassRecord:
    raw = payload.get("compiler_pass") if isinstance(payload.get("compiler_pass"), dict) else payload
    return CompilerPassRecord(
        pass_ref=str(raw.get("pass_ref") or ""),
        pass_name=str(raw.get("pass_name") or ""),
        input_ir_refs=_compiler_tuple(raw.get("input_ir_refs")),
        output_ir_ref=str(raw.get("output_ir_ref") or ""),
        input_qro_refs=_compiler_tuple(raw.get("input_qro_refs")),
        graph_command_refs=_compiler_tuple(raw.get("graph_command_refs")),
        canonical_command_refs=_compiler_tuple(raw.get("canonical_command_refs")),
        actor=str(raw.get("actor") or ""),
        actor_source=raw.get("actor_source") or ActorSource.USER_MANUAL.value,
        entry_source=raw.get("entry_source") or EntrySource.API.value,
        permission_ref=str(raw.get("permission_ref") or ""),
        tool_record_refs=_compiler_tuple(raw.get("tool_record_refs")),
        evidence_refs=_compiler_tuple(raw.get("evidence_refs")),
        validation_refs=_compiler_tuple(raw.get("validation_refs")),
        deterministic_run_plan_ref=str(raw.get("deterministic_run_plan_ref") or ""),
        rollback_ref=str(raw.get("rollback_ref") or ""),
        status=str(raw.get("status") or "compiled"),
        direct_graph_mutation=bool(raw.get("direct_graph_mutation", False)),
        bypassed_permission=bool(raw.get("bypassed_permission", False)),
        raw_llm_output_embedded_as_ir=bool(raw.get("raw_llm_output_embedded_as_ir", False)),
    )


def _compiler_artifact_from_payload(payload: dict[str, Any]) -> CompilerArtifactRecord:
    raw = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else payload
    return CompilerArtifactRecord(
        artifact_ref=str(raw.get("artifact_ref") or ""),
        artifact_kind=str(raw.get("artifact_kind") or ""),
        source_ir_refs=_compiler_tuple(raw.get("source_ir_refs")),
        compiler_pass_refs=_compiler_tuple(raw.get("compiler_pass_refs")),
        graph_command_refs=_compiler_tuple(raw.get("graph_command_refs")),
        canonical_command_refs=_compiler_tuple(raw.get("canonical_command_refs")),
        deterministic_run_plan_ref=str(raw.get("deterministic_run_plan_ref") or ""),
        environment_lock_ref=str(raw.get("environment_lock_ref") or ""),
        permission_ref=str(raw.get("permission_ref") or ""),
        output_contract_ref=str(raw.get("output_contract_ref") or ""),
        manifest_hash=str(raw.get("manifest_hash") or ""),
        evidence_refs=_compiler_tuple(raw.get("evidence_refs")),
        validation_refs=_compiler_tuple(raw.get("validation_refs")),
        mathematical_spine_chain_refs=_compiler_tuple(raw.get("mathematical_spine_chain_refs")),
        target_runtime=raw.get("target_runtime") or RuntimeStatus.OFFLINE.value,
        compiler_version=str(raw.get("compiler_version") or "governed-compiler-ir.v1"),
        mock_profile=str(raw.get("mock_profile") or "none"),
        executable=bool(raw.get("executable", False)),
        contains_source_code=bool(raw.get("contains_source_code", False)),
        raw_llm_output_embedded=bool(raw.get("raw_llm_output_embedded", False)),
        plaintext_secret_embedded=bool(raw.get("plaintext_secret_embedded", False)),
        silent_mock_fallback=bool(raw.get("silent_mock_fallback", False)),
    )


def _compiler_unique_refs(*values: Any) -> tuple[str, ...]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        for ref in _compiler_tuple(value):
            if not ref or ref in seen:
                continue
            refs.append(ref)
            seen.add(ref)
    return tuple(refs)


def _research_graph_qro_command(qro_id: str) -> tuple[QRORecord, ResearchGraphCommand]:
    qro_id = str(qro_id or "").strip()
    if not qro_id:
        raise ValueError("qro_id is required")
    for command in reversed(RESEARCH_GRAPH_STORE.commands()):
        qro = command.payload.get("qro")
        if isinstance(qro, QRORecord) and qro.qro_id == qro_id:
            return qro, command
    raise ValueError(f"qro_id {qro_id!r} is not present in Research Graph commands")


def _compile_qro_payload(payload: dict[str, Any], *, actor: str) -> tuple[CompilerIRRecord, CompilerPassRecord]:
    qro, command = _research_graph_qro_command(str(payload.get("qro_id") or ""))
    validation_refs = _compiler_unique_refs(payload.get("validation_refs"))
    if not validation_refs:
        raise ValueError("validation_refs is required for compile_qro")
    environment_lock_ref = str(payload.get("environment_lock_ref") or "").strip()
    if not environment_lock_ref:
        raise ValueError("environment_lock_ref is required for compile_qro")
    evidence_refs = _compiler_unique_refs(payload.get("evidence_refs"), qro.evidence_refs, command.evidence_refs)
    if not evidence_refs:
        raise ValueError("compile_qro requires QRO or command evidence_refs")
    graph_command_refs = _compiler_unique_refs(payload.get("graph_command_refs"), (command.command_id,))
    canonical_command_refs = _compiler_unique_refs(
        payload.get("canonical_command_refs"),
        (f"research_graph_command:{command.command_id}",),
    )
    permission_ref = str(payload.get("permission_ref") or qro.permission or "").strip()
    if not permission_ref:
        raise ValueError("permission_ref is required for compile_qro")
    pass_name = str(payload.get("pass_name") or "qro_to_governed_ir").strip()
    compiler_version = str(payload.get("compiler_version") or "governed-compiler-ir.v1").strip()
    theory_binding_refs = _compiler_unique_refs(
        payload.get("theory_binding_refs"),
        ((qro.theory_implementation_binding,) if qro.theory_implementation_binding else ()),
    )
    consistency_check_refs = _compiler_unique_refs(payload.get("consistency_check_refs"))
    ir_ref = "compiler_ir:" + content_hash(
        {
            "qro_id": qro.qro_id,
            "command_id": command.command_id,
            "pass_name": pass_name,
            "compiler_version": compiler_version,
        }
    )
    deterministic_run_plan_ref = str(payload.get("deterministic_run_plan_ref") or f"runplan:{ir_ref}").strip()
    rollback_ref = str(payload.get("rollback_ref") or f"rollback:{ir_ref}").strip()
    node_refs = _compiler_unique_refs(
        payload.get("node_refs"),
        (f"qro:{qro.qro_id}", f"qro_type:{_enum_text(qro.qro_type)}"),
    )
    ir = CompilerIRRecord(
        ir_ref=ir_ref,
        source_qro_refs=(qro.qro_id,),
        graph_command_refs=graph_command_refs,
        canonical_command_refs=canonical_command_refs,
        node_refs=node_refs,
        edge_refs=_compiler_unique_refs(payload.get("edge_refs")),
        artifact_refs=_compiler_unique_refs(payload.get("artifact_refs")),
        theory_binding_refs=theory_binding_refs,
        consistency_check_refs=consistency_check_refs,
        evidence_refs=evidence_refs,
        validation_refs=validation_refs,
        permission_ref=permission_ref,
        deterministic_run_plan_ref=deterministic_run_plan_ref,
        rollback_ref=rollback_ref,
        environment_lock_ref=environment_lock_ref,
        target_runtime=payload.get("target_runtime") or _enum_text(qro.allowed_environment),
        compiler_version=compiler_version,
        mock_profile=qro.mock_profile,
    )
    pass_ref = "compiler_pass:" + content_hash(
        {
            "qro_id": qro.qro_id,
            "command_id": command.command_id,
            "output_ir_ref": ir.ir_ref,
            "pass_name": pass_name,
        }
    )
    compiler_pass = CompilerPassRecord(
        pass_ref=pass_ref,
        pass_name=pass_name,
        input_ir_refs=_compiler_unique_refs(payload.get("input_ir_refs")),
        output_ir_ref=ir.ir_ref,
        input_qro_refs=(qro.qro_id,),
        graph_command_refs=graph_command_refs,
        canonical_command_refs=canonical_command_refs,
        actor=actor,
        actor_source=payload.get("actor_source") or ActorSource.USER_MANUAL.value,
        entry_source=payload.get("entry_source") or _enum_text(command.source),
        permission_ref=permission_ref,
        tool_record_refs=_compiler_unique_refs(payload.get("tool_record_refs"), command.tool_record_refs, ("api:compile_qro",)),
        evidence_refs=evidence_refs,
        validation_refs=validation_refs,
        deterministic_run_plan_ref=deterministic_run_plan_ref,
        rollback_ref=rollback_ref,
        status="compiled",
    )
    ir_decision = validate_compiler_ir(ir)
    if not ir_decision.accepted:
        raise ValueError("; ".join(f"{v.code}:{v.field}" for v in ir_decision.violations))
    pass_decision = validate_compiler_pass(compiler_pass)
    if not pass_decision.accepted:
        raise ValueError("; ".join(f"{v.code}:{v.field}" for v in pass_decision.violations))
    return ir, compiler_pass


def _goal_entrypoint_coverage_from_compiler_records(
    ir: CompilerIRRecord,
    compiler_pass: CompilerPassRecord,
    *,
    entrypoint_ref: str,
) -> GoalEntrypointCoverageRecord:
    entry_source = compiler_pass.entry_source.value if hasattr(compiler_pass.entry_source, "value") else str(
        compiler_pass.entry_source
    )
    coverage_ref = "goal_entrypoint_coverage:" + content_hash(
        {
            "entry_source": entry_source,
            "source_qro_refs": ir.source_qro_refs,
            "graph_command_refs": ir.graph_command_refs,
            "compiler_ir_ref": ir.ir_ref,
            "compiler_pass_ref": compiler_pass.pass_ref,
        }
    )
    return GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source=entry_source,
        entrypoint_ref=entrypoint_ref,
        goal_sections=("§0", "§1", "§7", "§8"),
        qro_refs=ir.source_qro_refs,
        research_graph_command_refs=ir.graph_command_refs,
        compiler_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
        evidence_refs=_compiler_unique_refs(ir.evidence_refs, compiler_pass.evidence_refs),
        validation_refs=_compiler_unique_refs(ir.validation_refs, compiler_pass.validation_refs),
        permission_refs=_compiler_unique_refs(ir.permission_ref, compiler_pass.permission_ref),
        replay_refs=_compiler_unique_refs(
            tuple(f"replay:research_graph:{ref}" for ref in ir.graph_command_refs),
            (f"replay:compiler_ir:{ir.ir_ref}", f"replay:compiler_pass:{compiler_pass.pass_ref}"),
        ),
        canonical_command_refs=ir.canonical_command_refs,
        recorded_by=compiler_pass.actor,
        silent_mock_fallback_used=str(ir.mock_profile).lower() == "silent",
    )


def _goal_entrypoint_coverage_from_compiler_artifact(
    artifact: CompilerArtifactRecord,
) -> GoalEntrypointCoverageRecord:
    irs = tuple(COMPILER_IR_STORE.ir(ref) for ref in artifact.source_ir_refs)
    compiler_passes = tuple(COMPILER_IR_STORE.compiler_pass(ref) for ref in artifact.compiler_pass_refs)
    if not compiler_passes:
        raise ValueError("compiler artifact coverage requires compiler_pass_refs")

    entry_sources = {
        compiler_pass.entry_source.value
        if hasattr(compiler_pass.entry_source, "value")
        else str(compiler_pass.entry_source)
        for compiler_pass in compiler_passes
    }
    if len(entry_sources) != 1:
        raise ValueError("compiler artifact coverage requires one entry_source across compiler passes")
    entry_source = next(iter(entry_sources))

    qro_refs = _compiler_unique_refs(
        *(ir.source_qro_refs for ir in irs),
        *(compiler_pass.input_qro_refs for compiler_pass in compiler_passes),
    )
    graph_command_refs = _compiler_unique_refs(
        artifact.graph_command_refs,
        *(ir.graph_command_refs for ir in irs),
        *(compiler_pass.graph_command_refs for compiler_pass in compiler_passes),
    )
    compiler_ir_refs = _compiler_unique_refs(artifact.source_ir_refs)
    compiler_pass_refs = _compiler_unique_refs(artifact.compiler_pass_refs)
    coverage_ref = "goal_entrypoint_coverage:" + content_hash(
        {
            "entry_source": entry_source,
            "entrypoint_ref": f"compiler_artifact:{artifact.artifact_ref}",
            "source_qro_refs": qro_refs,
            "graph_command_refs": graph_command_refs,
            "compiler_ir_refs": compiler_ir_refs,
            "compiler_pass_refs": compiler_pass_refs,
            "artifact_ref": artifact.artifact_ref,
        }
    )
    silent_mock_fallback_used = artifact.silent_mock_fallback or str(artifact.mock_profile).lower() == "silent" or any(
        str(ir.mock_profile).lower() == "silent" for ir in irs
    )
    recorded_by = compiler_passes[0].actor
    return GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source=entry_source,
        entrypoint_ref=f"compiler_artifact:{artifact.artifact_kind or artifact.artifact_ref}",
        goal_sections=("§0", "§1", "§7", "§8"),
        qro_refs=qro_refs,
        research_graph_command_refs=graph_command_refs,
        compiler_ir_refs=compiler_ir_refs,
        compiler_pass_refs=compiler_pass_refs,
        evidence_refs=_compiler_unique_refs(
            artifact.evidence_refs,
            *(ir.evidence_refs for ir in irs),
            *(compiler_pass.evidence_refs for compiler_pass in compiler_passes),
        ),
        validation_refs=_compiler_unique_refs(
            artifact.validation_refs,
            *(ir.validation_refs for ir in irs),
            *(compiler_pass.validation_refs for compiler_pass in compiler_passes),
        ),
        permission_refs=_compiler_unique_refs(
            artifact.permission_ref,
            *(ir.permission_ref for ir in irs),
            *(compiler_pass.permission_ref for compiler_pass in compiler_passes),
        ),
        replay_refs=_compiler_unique_refs(
            tuple(f"replay:research_graph:{ref}" for ref in graph_command_refs),
            tuple(f"replay:compiler_ir:{ref}" for ref in compiler_ir_refs),
            tuple(f"replay:compiler_pass:{ref}" for ref in compiler_pass_refs),
            (f"replay:compiler_artifact:{artifact.artifact_ref}",),
        ),
        canonical_command_refs=_compiler_unique_refs(
            artifact.canonical_command_refs,
            *(ir.canonical_command_refs for ir in irs),
            *(compiler_pass.canonical_command_refs for compiler_pass in compiler_passes),
        ),
        lifecycle_refs=_compiler_unique_refs(artifact.artifact_ref, artifact.mathematical_spine_chain_refs),
        recorded_by=recorded_by,
        silent_mock_fallback_used=silent_mock_fallback_used,
    )


def _validate_goal_entrypoint_coverage_candidate(
    record: GoalEntrypointCoverageRecord,
) -> GoalEntrypointCoverageRecord:
    decision = validate_goal_entrypoint_coverage(record)
    if not decision.accepted:
        raise ValueError("; ".join(f"{v.code}:{v.field}" for v in decision.violations))
    return record


def _compiler_ir_summary(ir: CompilerIRRecord) -> dict[str, Any]:
    return {
        "ir_ref": ir.ir_ref,
        "source_qro_refs": ir.source_qro_refs,
        "graph_command_refs": ir.graph_command_refs,
        "canonical_command_refs": ir.canonical_command_refs,
        "target_runtime": ir.target_runtime.value if hasattr(ir.target_runtime, "value") else str(ir.target_runtime),
        "compiler_version": ir.compiler_version,
        "mock_profile": ir.mock_profile,
    }


def _compiler_pass_summary(record: CompilerPassRecord) -> dict[str, Any]:
    return {
        "pass_ref": record.pass_ref,
        "pass_name": record.pass_name,
        "input_ir_refs": record.input_ir_refs,
        "output_ir_ref": record.output_ir_ref,
        "actor": record.actor,
        "entry_source": record.entry_source.value if hasattr(record.entry_source, "value") else str(record.entry_source),
        "status": record.status,
    }


def _compiler_artifact_summary(record: CompilerArtifactRecord) -> dict[str, Any]:
    return {
        "artifact_ref": record.artifact_ref,
        "artifact_kind": record.artifact_kind,
        "source_ir_refs": record.source_ir_refs,
        "compiler_pass_refs": record.compiler_pass_refs,
        "canonical_command_refs": record.canonical_command_refs,
        "deterministic_run_plan_ref": record.deterministic_run_plan_ref,
        "environment_lock_ref": record.environment_lock_ref,
        "output_contract_ref": record.output_contract_ref,
        "manifest_hash": record.manifest_hash,
        "mathematical_spine_chain_refs": record.mathematical_spine_chain_refs,
        "target_runtime": record.target_runtime.value
        if hasattr(record.target_runtime, "value")
        else str(record.target_runtime),
        "mock_profile": record.mock_profile,
        "executable": record.executable,
    }


def _validate_compiler_artifact_mathematical_spine_refs(record: CompilerArtifactRecord) -> None:
    for chain_ref in record.mathematical_spine_chain_refs:
        try:
            MATHEMATICAL_SPINE_CHAIN_REGISTRY.chain(chain_ref)
        except KeyError as exc:
            raise ValueError(f"compiler artifact mathematical_spine_chain_ref {chain_ref!r} is not recorded") from exc


@app.post("/api/research-os/compiler/ir")
def research_os_compiler_record_ir(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        ir = COMPILER_IR_STORE.record_ir(_compiler_ir_from_payload(payload))
        return {"ir_ref": ir.ir_ref, "recorded_by": user.username}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/compiler/passes")
def research_os_compiler_record_pass(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        candidate = _compiler_pass_from_payload(payload)
        try:
            ir = COMPILER_IR_STORE.ir(candidate.output_ir_ref)
        except KeyError as exc:
            raise ValueError(f"compiler pass output_ir_ref {candidate.output_ir_ref!r} is not recorded") from exc
        coverage_candidate = _validate_goal_entrypoint_coverage_candidate(
            _goal_entrypoint_coverage_from_compiler_records(
                ir,
                candidate,
                entrypoint_ref=f"compiler_pass:{candidate.pass_name or candidate.pass_ref}",
            )
        )
        compiler_pass = COMPILER_IR_STORE.record_pass(candidate)
        coverage = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(coverage_candidate)
        return {
            "pass_ref": compiler_pass.pass_ref,
            "output_ir_ref": compiler_pass.output_ir_ref,
            "entrypoint_coverage_ref": coverage.coverage_ref,
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/compiler/artifacts")
def research_os_compiler_record_artifact(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        candidate = _compiler_artifact_from_payload(payload)
        decision = validate_compiler_artifact(candidate)
        if not decision.accepted:
            raise ValueError("; ".join(f"{v.code}:{v.field}" for v in decision.violations))
        _validate_compiler_artifact_mathematical_spine_refs(candidate)
        coverage_candidate = _validate_goal_entrypoint_coverage_candidate(
            _goal_entrypoint_coverage_from_compiler_artifact(candidate)
        )
        artifact = COMPILER_IR_STORE.record_artifact(candidate)
        coverage = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(coverage_candidate)
        return {
            "artifact_ref": artifact.artifact_ref,
            "artifact_kind": artifact.artifact_kind,
            "source_ir_refs": list(artifact.source_ir_refs),
            "compiler_pass_refs": list(artifact.compiler_pass_refs),
            "mathematical_spine_chain_refs": list(artifact.mathematical_spine_chain_refs),
            "entrypoint_coverage_ref": coverage.coverage_ref,
            "executable": artifact.executable,
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/compiler/compile_qro")
def research_os_compiler_compile_qro(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Compile an existing Research Graph QRO into governed Compiler IR.

    This pass is deterministic and audit-only: it derives IR/pass refs from the
    QRO and its Research Graph command, then records both in the Compiler store.
    It refuses to fabricate validation, environment, permission, or evidence refs.
    """

    try:
        ir, compiler_pass = _compile_qro_payload(payload, actor=user.username)
        coverage_candidate = _validate_goal_entrypoint_coverage_candidate(
            _goal_entrypoint_coverage_from_compiler_records(
                ir,
                compiler_pass,
                entrypoint_ref=f"compile_qro:{_enum_text(compiler_pass.entry_source)}",
            )
        )
        COMPILER_IR_STORE.record_ir(ir)
        COMPILER_IR_STORE.record_pass(compiler_pass)
        coverage = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(coverage_candidate)
        return {
            "ir_ref": ir.ir_ref,
            "pass_ref": compiler_pass.pass_ref,
            "entrypoint_coverage_ref": coverage.coverage_ref,
            "source_qro_ref": ir.source_qro_refs[0],
            "graph_command_refs": list(ir.graph_command_refs),
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/compiler/summary")
def research_os_compiler_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    irs = COMPILER_IR_STORE.irs()
    passes = COMPILER_IR_STORE.passes()
    artifacts = COMPILER_IR_STORE.artifacts()
    return {
        "user": user.username,
        "ir_total": len(irs),
        "pass_total": len(passes),
        "artifact_total": len(artifacts),
        "irs": [_compiler_ir_summary(ir) for ir in irs],
        "passes": [_compiler_pass_summary(record) for record in passes],
        "artifacts": [_compiler_artifact_summary(record) for record in artifacts],
    }


def _goal_entrypoint_coverage_from_payload(
    payload: dict[str, Any],
    *,
    actor: str,
) -> GoalEntrypointCoverageRecord:
    raw = payload.get("entrypoint_coverage") if isinstance(payload.get("entrypoint_coverage"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="goal entrypoint coverage payload must be an object")
    raw = dict(raw)
    raw["recorded_by"] = actor
    return goal_entrypoint_coverage_record_from_dict(raw)


def _goal_entrypoint_coverage_summary(record: GoalEntrypointCoverageRecord) -> dict[str, Any]:
    entry_source = record.entry_source.value if hasattr(record.entry_source, "value") else str(record.entry_source)
    return {
        "coverage_ref": record.coverage_ref,
        "entry_source": entry_source,
        "entrypoint_ref": record.entrypoint_ref,
        "goal_sections": list(record.goal_sections),
        "qro_refs": list(record.qro_refs),
        "research_graph_command_refs": list(record.research_graph_command_refs),
        "compiler_ir_refs": list(record.compiler_ir_refs),
        "compiler_pass_refs": list(record.compiler_pass_refs),
        "evidence_refs": list(record.evidence_refs),
        "validation_refs": list(record.validation_refs),
        "permission_refs": list(record.permission_refs),
        "replay_refs": list(record.replay_refs),
        "canonical_command_refs": list(record.canonical_command_refs),
        "lifecycle_refs": list(record.lifecycle_refs),
        "rdp_refs": list(record.rdp_refs),
        "recorded_by": record.recorded_by,
        "claims_full_product_entrypoint": record.claims_full_product_entrypoint,
    }


def _goal_section_coverage_from_payload(payload: dict[str, Any]) -> GoalSectionCoverageRecord:
    raw = payload.get("section_coverage") if isinstance(payload.get("section_coverage"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="goal section coverage payload must be an object")
    return goal_section_coverage_record_from_dict(dict(raw))


def _goal_section_coverage_summary(record: GoalSectionCoverageRecord) -> dict[str, Any]:
    return {
        "section": record.section.value if hasattr(record.section, "value") else str(record.section),
        "contract_refs": list(record.contract_refs),
        "test_refs": list(record.test_refs),
        "task_refs": list(record.task_refs),
        "evidence_refs": list(record.evidence_refs),
        "full_entrypoint_wired": record.full_entrypoint_wired,
        "entrypoint_wiring_refs": list(record.entrypoint_wiring_refs),
    }


@app.post("/api/research-os/goal/entrypoint_coverage_records")
def research_os_goal_record_entrypoint_coverage(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.record_coverage(
            _goal_entrypoint_coverage_from_payload(payload, actor=user.username)
        )
        entry_source = record.entry_source.value if hasattr(record.entry_source, "value") else str(record.entry_source)
        return {
            "coverage_ref": record.coverage_ref,
            "entry_source": entry_source,
            "entrypoint_ref": record.entrypoint_ref,
            "recorded_by": record.recorded_by,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/goal/entrypoint_coverage/summary")
def research_os_goal_entrypoint_coverage_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    records = GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    decision = validate_goal_entrypoint_coverage_manifest(tuple(records), claims_all_entrypoints_wired=True)
    present = sorted(
        {
            record.entry_source.value if hasattr(record.entry_source, "value") else str(record.entry_source)
            for record in records
        }
    )
    missing = sorted(
        {
            violation.ref
            for violation in decision.violations
            if violation.code == "goal_entrypoint_source_missing"
        }
    )
    return {
        "user": user.username,
        "coverage_total": len(records),
        "required_entry_sources": list(REQUIRED_ENTRY_SOURCES),
        "entry_sources_present": present,
        "missing_entry_sources": missing,
        "all_entrypoints_wired": decision.accepted,
        "coverage_records": [_goal_entrypoint_coverage_summary(record) for record in records],
    }


@app.post("/api/research-os/goal/section_coverage_records")
def research_os_goal_record_section_coverage(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = GOAL_SECTION_COVERAGE_REGISTRY.record_coverage(_goal_section_coverage_from_payload(payload))
        return {
            "section": record.section.value if hasattr(record.section, "value") else str(record.section),
            "full_entrypoint_wired": record.full_entrypoint_wired,
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/goal/section_coverage/summary")
def research_os_goal_section_coverage_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    records = GOAL_SECTION_COVERAGE_REGISTRY.records()
    decision = validate_goal_coverage_manifest(tuple(records), claims_full_product_implementation=True)
    present = sorted(
        record.section.value if hasattr(record.section, "value") else str(record.section)
        for record in records
    )
    missing = sorted(
        {
            violation.ref
            for violation in decision.violations
            if violation.code == "goal_section_missing"
        }
    )
    not_full_wired = sorted(
        {
            violation.ref
            for violation in decision.violations
            if violation.code in {"goal_section_not_full_entrypoint_wired", "goal_section_claimed_wired_without_refs"}
        }
    )
    return {
        "user": user.username,
        "section_total": len(records),
        "required_sections": list(REQUIRED_GOAL_SECTIONS),
        "sections_present": present,
        "missing_sections": missing,
        "not_full_entrypoint_wired_sections": not_full_wired,
        "full_product_implementation": decision.accepted,
        "section_records": [_goal_section_coverage_summary(record) for record in records],
    }


def _platform_coverage_records_from_payload(payload: dict[str, Any]) -> tuple[PlatformCapabilityRecord, ...]:
    raw_records = payload.get("records")
    if raw_records is None and isinstance(payload.get("platform_coverage"), dict):
        raw_records = payload["platform_coverage"].get("records")
    if not isinstance(raw_records, list):
        raise HTTPException(status_code=422, detail="platform coverage payload requires records list")
    if any(not isinstance(item, dict) for item in raw_records):
        raise HTTPException(status_code=422, detail="platform coverage records must be objects")
    return tuple(platform_capability_record_from_dict(item) for item in raw_records)


def _platform_coverage_record_summary(record: PlatformCapabilityRecord) -> dict[str, Any]:
    return platform_capability_record_to_dict(record)


@app.post("/api/research-os/platform/coverage_manifest")
def research_os_platform_record_coverage_manifest(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        records = _platform_coverage_records_from_payload(payload)
        decision = validate_platform_coverage_real_manifest(records)
        if not decision.accepted:
            raise ValueError("; ".join(f"{v.code}:{v.field}:{v.ref}" for v in decision.violations))
        recorded = PLATFORM_COVERAGE_REGISTRY.record_manifest(records)
        return {
            "recorded_by": user.username,
            "platform_row_total": len(recorded),
            "full_platform_coverage": True,
            "rows": [record.m_row.value if hasattr(record.m_row, "value") else str(record.m_row) for record in recorded],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/platform/coverage_summary")
def research_os_platform_coverage_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    records = PLATFORM_COVERAGE_REGISTRY.records()
    decision = validate_platform_coverage_real_manifest(tuple(records))
    present_set = {record.m_row.value if hasattr(record.m_row, "value") else str(record.m_row) for record in records}
    present = [row for row in REQUIRED_PLATFORM_ROWS if row in present_set]
    present.extend(sorted(row for row in present_set if row not in REQUIRED_PLATFORM_ROWS))
    missing = sorted(
        {
            violation.ref
            for violation in decision.violations
            if violation.code == "platform_capability_row_missing"
        }
    )
    return {
        "user": user.username,
        "platform_row_total": len(records),
        "required_platform_rows": list(REQUIRED_PLATFORM_ROWS),
        "platform_rows_present": present,
        "missing_platform_rows": missing,
        "full_platform_coverage": decision.accepted,
        "violations": [
            {
                "code": violation.code,
                "field": violation.field,
                "ref": violation.ref,
                "message": violation.message,
            }
            for violation in decision.violations
        ],
        "records": [_platform_coverage_record_summary(record) for record in records],
    }


def _mathematical_spine_chain_from_payload(payload: dict[str, Any], *, actor: str) -> MathematicalSpineChainRecord:
    raw = payload.get("chain") if isinstance(payload.get("chain"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="mathematical spine chain payload must be an object")
    raw = dict(raw)
    raw["recorded_by"] = actor
    return mathematical_spine_chain_from_dict(raw)


def _mathematical_spine_chain_summary(record: MathematicalSpineChainRecord) -> dict[str, Any]:
    return {
        "chain_ref": record.chain_ref,
        "data_semantics_ref": record.data_semantics_ref,
        "factor_ref": record.factor_ref,
        "model_ref": record.model_ref,
        "forecast_ref": record.forecast_ref,
        "signal_contract_ref": record.signal_contract_ref,
        "strategy_book_ref": record.strategy_book_ref,
        "portfolio_policy_ref": record.portfolio_policy_ref,
        "risk_policy_ref": record.risk_policy_ref,
        "execution_policy_ref": record.execution_policy_ref,
        "backtest_run_ref": record.backtest_run_ref,
        "attribution_ref": record.attribution_ref,
        "monitor_ref": record.monitor_ref,
        "theory_binding_refs": record.theory_binding_refs,
        "consistency_check_refs": record.consistency_check_refs,
        "methodology_choice_ref": record.methodology_choice_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "evidence_refs": record.evidence_refs,
        "validation_refs": record.validation_refs,
        "consistency_verdict": record.consistency_verdict.value
        if hasattr(record.consistency_verdict, "value")
        else str(record.consistency_verdict),
        "target_runtime": record.target_runtime.value if hasattr(record.target_runtime, "value") else str(record.target_runtime),
        "recorded_by": record.recorded_by,
        "silent_mock_fallback_used": record.silent_mock_fallback_used,
        "chain_version": record.chain_version,
        "created_at": record.created_at,
    }


@app.post("/api/research-os/spine/mathematical_chains")
def research_os_spine_record_mathematical_chain(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = MATHEMATICAL_SPINE_CHAIN_REGISTRY.record_chain(
            _mathematical_spine_chain_from_payload(payload, actor=user.username)
        )
        return {
            "chain_ref": record.chain_ref,
            "target_runtime": record.target_runtime.value
            if hasattr(record.target_runtime, "value")
            else str(record.target_runtime),
            "recorded_by": record.recorded_by,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/spine/mathematical_chains/summary")
def research_os_spine_mathematical_chain_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    chains = MATHEMATICAL_SPINE_CHAIN_REGISTRY.chains()
    return {
        "user": user.username,
        "mathematical_chain_total": len(chains),
        "mathematical_chains": [_mathematical_spine_chain_summary(record) for record in chains],
    }


def _validation_depth_from_payload(payload: dict[str, Any]) -> ValidationDepthRecord:
    raw = payload.get("validation_depth") if isinstance(payload.get("validation_depth"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="validation_depth payload must be an object")
    return validation_depth_record_from_dict(raw)


def _validation_depth_summary(record: ValidationDepthRecord) -> dict[str, Any]:
    return {
        "depth_ref": record.depth_ref,
        "claim_ref": record.claim_ref,
        "claim_label": record.claim_label,
        "target_environment": record.target_environment,
        "cpcv_ref": record.cpcv_ref,
        "walk_forward_ref": record.walk_forward_ref,
        "conformal_ref": record.conformal_ref,
        "abstain_policy_ref": record.abstain_policy_ref,
        "tca_ref": record.tca_ref,
        "cost_model_refs": record.cost_model_refs,
        "feature_leakage_probe_refs": record.feature_leakage_probe_refs,
        "feature_leakage_verdict": record.feature_leakage_verdict,
        "fault_injection_refs": record.fault_injection_refs,
        "fault_injection_verdict": record.fault_injection_verdict,
        "recovery_drill_refs": record.recovery_drill_refs,
        "recovery_drill_verdict": record.recovery_drill_verdict,
        "evidence_refs": record.evidence_refs,
        "validation_result_refs": record.validation_result_refs,
        "methodology_choice_ref": record.methodology_choice_ref,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "user_waived_path": record.user_waived_path,
        "silent_mock_fallback_used": record.silent_mock_fallback_used,
    }


def _cpcv_calculator_summary(record: CPCVCalculatorRecord) -> dict[str, Any]:
    return {
        "cpcv_ref": record.cpcv_ref,
        "claim_ref": record.claim_ref,
        "fold_count": record.fold_count,
        "embargo_observations": record.embargo_observations,
        "sample_count": record.sample_count,
        "mean_metric": record.mean_metric,
        "min_metric": record.min_metric,
        "max_metric": record.max_metric,
        "source_hash": record.source_hash,
        "evidence_refs": record.evidence_refs,
        "validation_result_refs": record.validation_result_refs,
    }


def _conformal_calculator_summary(record: ConformalCalculatorRecord) -> dict[str, Any]:
    return {
        "conformal_ref": record.conformal_ref,
        "claim_ref": record.claim_ref,
        "alpha": record.alpha,
        "calibration_count": record.calibration_count,
        "nonconformity_threshold": record.nonconformity_threshold,
        "coverage_estimate": record.coverage_estimate,
        "source_hash": record.source_hash,
        "evidence_refs": record.evidence_refs,
        "validation_result_refs": record.validation_result_refs,
        "abstain_policy_ref": record.abstain_policy_ref,
    }


def _tca_calculator_summary(record: TCACalculatorRecord) -> dict[str, Any]:
    return {
        "tca_ref": record.tca_ref,
        "claim_ref": record.claim_ref,
        "sample_count": record.sample_count,
        "gross_mean_bps": record.gross_mean_bps,
        "total_cost_bps": record.total_cost_bps,
        "net_mean_bps": record.net_mean_bps,
        "cost_component_refs": record.cost_component_refs,
        "cost_model_refs": record.cost_model_refs,
        "source_hash": record.source_hash,
        "evidence_refs": record.evidence_refs,
        "validation_result_refs": record.validation_result_refs,
    }


def _runtime_drill_summary(record: RuntimeDrillRecord) -> dict[str, Any]:
    return {
        "runtime_drill_ref": record.runtime_drill_ref,
        "claim_ref": record.claim_ref,
        "target_environment": record.target_environment,
        "drill_mode": record.drill_mode,
        "venue_ref": record.venue_ref,
        "fault_scenario": record.fault_scenario,
        "expected_guard_ref": record.expected_guard_ref,
        "observed_guard_ref": record.observed_guard_ref,
        "recovery_action_ref": record.recovery_action_ref,
        "fault_injection_ref": record.fault_injection_ref,
        "recovery_drill_ref": record.recovery_drill_ref,
        "fault_injection_verdict": record.fault_injection_verdict,
        "recovery_drill_verdict": record.recovery_drill_verdict,
        "source_hash": record.source_hash,
        "evidence_refs": record.evidence_refs,
        "validation_result_refs": record.validation_result_refs,
    }


@app.post("/api/research-os/methodology/cpcv")
def research_os_methodology_calculate_cpcv(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = METHODOLOGY_CALCULATOR_REGISTRY.record_cpcv(
            calculate_cpcv(
                claim_ref=str(payload.get("claim_ref") or ""),
                fold_metric_values=payload.get("fold_metric_values"),
                embargo_observations=int(payload.get("embargo_observations") or 0),
                evidence_refs=tuple(str(v) for v in payload.get("evidence_refs") or ()),
                validation_result_refs=tuple(str(v) for v in payload.get("validation_result_refs") or ()),
                cpcv_ref=payload.get("cpcv_ref"),
                silent_mock_fallback_used=bool(payload.get("silent_mock_fallback_used", False)),
            )
        )
        return {**_cpcv_calculator_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/methodology/conformal")
def research_os_methodology_calculate_conformal(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = METHODOLOGY_CALCULATOR_REGISTRY.record_conformal(
            calculate_conformal(
                claim_ref=str(payload.get("claim_ref") or ""),
                calibration_scores=payload.get("calibration_scores"),
                alpha=float(payload.get("alpha")),
                evidence_refs=tuple(str(v) for v in payload.get("evidence_refs") or ()),
                validation_result_refs=tuple(str(v) for v in payload.get("validation_result_refs") or ()),
                abstain_policy_ref=payload.get("abstain_policy_ref"),
                conformal_ref=payload.get("conformal_ref"),
                silent_mock_fallback_used=bool(payload.get("silent_mock_fallback_used", False)),
            )
        )
        return {**_conformal_calculator_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/methodology/tca")
def research_os_methodology_calculate_tca(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        raw_components = payload.get("cost_components_bps") or {}
        if not isinstance(raw_components, dict):
            raise ValueError("cost_components_bps must be an object")
        record = METHODOLOGY_CALCULATOR_REGISTRY.record_tca(
            calculate_tca(
                claim_ref=str(payload.get("claim_ref") or ""),
                gross_return_bps=payload.get("gross_return_bps"),
                cost_components_bps=raw_components,
                cost_model_refs=tuple(str(v) for v in payload.get("cost_model_refs") or ()),
                evidence_refs=tuple(str(v) for v in payload.get("evidence_refs") or ()),
                validation_result_refs=tuple(str(v) for v in payload.get("validation_result_refs") or ()),
                tca_ref=payload.get("tca_ref"),
                silent_mock_fallback_used=bool(payload.get("silent_mock_fallback_used", False)),
            )
        )
        return {**_tca_calculator_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/methodology/runtime_drills")
def research_os_methodology_record_runtime_drill(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = METHODOLOGY_RUNTIME_DRILL_REGISTRY.record_runtime_drill(
            record_runtime_drill(
                claim_ref=str(payload.get("claim_ref") or ""),
                target_environment=str(payload.get("target_environment") or ""),
                drill_mode=str(payload.get("drill_mode") or ""),
                venue_ref=str(payload.get("venue_ref") or ""),
                fault_scenario=str(payload.get("fault_scenario") or ""),
                expected_guard_ref=str(payload.get("expected_guard_ref") or ""),
                observed_guard_ref=str(payload.get("observed_guard_ref") or ""),
                recovery_action_ref=str(payload.get("recovery_action_ref") or ""),
                evidence_refs=tuple(str(v) for v in payload.get("evidence_refs") or ()),
                validation_result_refs=tuple(str(v) for v in payload.get("validation_result_refs") or ()),
                runtime_drill_ref=payload.get("runtime_drill_ref"),
                fault_injection_ref=payload.get("fault_injection_ref"),
                recovery_drill_ref=payload.get("recovery_drill_ref"),
                fault_injection_verdict=str(payload.get("fault_injection_verdict") or "passed"),
                recovery_drill_verdict=str(payload.get("recovery_drill_verdict") or "passed"),
                silent_mock_fallback_used=bool(payload.get("silent_mock_fallback_used", False)),
            )
        )
        return {**_runtime_drill_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/methodology/validation_depth_records")
def research_os_methodology_record_validation_depth(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = VALIDATION_DEPTH_REGISTRY.record_depth(_validation_depth_from_payload(payload))
        return {
            "depth_ref": record.depth_ref,
            "claim_ref": record.claim_ref,
            "target_environment": record.target_environment,
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/methodology/summary")
def research_os_methodology_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    depths = VALIDATION_DEPTH_REGISTRY.depths()
    cpcv_records = METHODOLOGY_CALCULATOR_REGISTRY.cpcv_records()
    conformal_records = METHODOLOGY_CALCULATOR_REGISTRY.conformal_records()
    tca_records = METHODOLOGY_CALCULATOR_REGISTRY.tca_records()
    runtime_drills = METHODOLOGY_RUNTIME_DRILL_REGISTRY.runtime_drills()
    return {
        "user": user.username,
        "validation_depth_total": len(depths),
        "validation_depths": [_validation_depth_summary(record) for record in depths],
        "runtime_drill_total": len(runtime_drills),
        "runtime_drills": [_runtime_drill_summary(record) for record in runtime_drills],
        "calculator_totals": {
            "cpcv": len(cpcv_records),
            "conformal": len(conformal_records),
            "tca": len(tca_records),
        },
        "cpcv_calculations": [_cpcv_calculator_summary(record) for record in cpcv_records],
        "conformal_calculations": [_conformal_calculator_summary(record) for record in conformal_records],
        "tca_calculations": [_tca_calculator_summary(record) for record in tca_records],
    }


def _trust_claim_from_payload(payload: dict[str, Any]) -> TrustClaimRecord:
    raw = payload.get("trust_claim") if isinstance(payload.get("trust_claim"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="trust_claim payload must be an object")
    return trust_claim_record_from_dict(raw)


def _functional_independence_disclosure_from_payload(
    payload: dict[str, Any],
) -> FunctionalIndependenceDisclosure:
    raw = (
        payload.get("independence_disclosure")
        if isinstance(payload.get("independence_disclosure"), dict)
        else payload
    )
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="independence_disclosure payload must be an object")
    return functional_independence_disclosure_from_dict(raw)


def _external_expert_review_from_payload(payload: dict[str, Any]) -> ExternalExpertReviewRecord:
    raw = payload.get("external_expert_review") if isinstance(payload.get("external_expert_review"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="external_expert_review payload must be an object")
    if "source_hash" in raw:
        return external_expert_review_from_dict(raw)
    return record_external_expert_review(
        release_ref=str(raw.get("release_ref") or ""),
        reviewer_ref=str(raw.get("reviewer_ref") or ""),
        reviewer_independence_ref=str(raw.get("reviewer_independence_ref") or ""),
        artifact_ref=str(raw.get("artifact_ref") or ""),
        review_protocol_ref=str(raw.get("review_protocol_ref") or ""),
        verdict=str(raw.get("verdict") or ""),
        evidence_refs=tuple(str(v) for v in raw.get("evidence_refs") or ()),
        veto_reason_refs=tuple(str(v) for v in raw.get("veto_reason_refs") or ()),
        signed_attestation_ref=raw.get("signed_attestation_ref"),
        review_ref=raw.get("review_ref"),
        silent_mock_fallback_used=bool(raw.get("silent_mock_fallback_used", False)),
    )


def _external_reviewer_identity_from_payload(payload: dict[str, Any]) -> ExternalReviewerIdentityRecord:
    raw = payload.get("external_reviewer_identity") if isinstance(payload.get("external_reviewer_identity"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="external_reviewer_identity payload must be an object")
    return external_reviewer_identity_from_dict(raw)


def _external_expert_signature_payload(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("external_expert_signature") if isinstance(payload.get("external_expert_signature"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="external_expert_signature payload must be an object")
    return {
        "review_ref": str(raw.get("review_ref") or ""),
        "identity_ref": str(raw.get("identity_ref") or ""),
        "signature_b64": str(raw.get("signature_b64") or ""),
        "attestation_ref": str(raw.get("attestation_ref") or ""),
        "verified_signature_ref": str(raw.get("verified_signature_ref") or ""),
    }


def _user_autonomy_from_payload(payload: dict[str, Any]) -> UserAutonomyRecord:
    raw = payload.get("user_autonomy") if isinstance(payload.get("user_autonomy"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="user_autonomy payload must be an object")
    return user_autonomy_record_from_dict(raw)


def _trust_claim_summary(record: TrustClaimRecord) -> dict[str, Any]:
    return {
        "claim_ref": record.claim_ref,
        "claim_label": str(record.claim_label),
        "evidence_refs": record.evidence_refs,
        "weakness_refs": record.weakness_refs,
        "weakness_visible_by_default": record.weakness_visible_by_default,
        "cold_start_n": record.cold_start_n,
        "pressure_context": record.pressure_context,
        "user_waiver_ref": record.user_waiver_ref,
        "waiver_weakness_visible_by_default": record.waiver_weakness_visible_by_default,
    }


def _functional_independence_summary(record: FunctionalIndependenceDisclosure) -> dict[str, Any]:
    return {
        "disclosure_ref": record.disclosure_ref,
        "mode": record.mode,
        "claims_organizational_independence": record.claims_organizational_independence,
        "isolated_validation_ref": record.isolated_validation_ref,
        "immutable_evidence_ref": record.immutable_evidence_ref,
        "second_confirmation_ref": record.second_confirmation_ref,
        "alternate_model_verification_ref": record.alternate_model_verification_ref,
        "organization_process_ref": record.organization_process_ref,
    }


def _external_expert_review_summary(record: ExternalExpertReviewRecord) -> dict[str, Any]:
    return {
        "review_ref": record.review_ref,
        "release_ref": record.release_ref,
        "reviewer_ref": record.reviewer_ref,
        "reviewer_independence_ref": record.reviewer_independence_ref,
        "artifact_ref": record.artifact_ref,
        "review_protocol_ref": record.review_protocol_ref,
        "verdict": record.verdict,
        "source_hash": record.source_hash,
        "evidence_refs": record.evidence_refs,
        "veto_reason_refs": record.veto_reason_refs,
        "signed_attestation_ref": record.signed_attestation_ref,
    }


def _external_reviewer_identity_summary(record: ExternalReviewerIdentityRecord) -> dict[str, Any]:
    return {
        "identity_ref": record.identity_ref,
        "reviewer_ref": record.reviewer_ref,
        "identity_provider_ref": record.identity_provider_ref,
        "public_key_ref": record.public_key_ref,
        "public_key_fingerprint": record.public_key_fingerprint,
        "reviewer_independence_ref": record.reviewer_independence_ref,
        "evidence_refs": record.evidence_refs,
        "status": record.status,
        "identity_hash": record.identity_hash,
    }


def _external_expert_signature_summary(record: ExternalExpertSignatureRecord) -> dict[str, Any]:
    return {
        "verified_signature_ref": record.verified_signature_ref,
        "attestation_ref": record.attestation_ref,
        "review_ref": record.review_ref,
        "reviewer_ref": record.reviewer_ref,
        "identity_ref": record.identity_ref,
        "public_key_ref": record.public_key_ref,
        "public_key_fingerprint": record.public_key_fingerprint,
        "signed_payload_hash": record.signed_payload_hash,
        "verification_hash": record.verification_hash,
    }


def _user_autonomy_summary(record: UserAutonomyRecord) -> dict[str, Any]:
    return {
        "choice_ref": record.choice_ref,
        "agent_recommendation_ref": record.agent_recommendation_ref,
        "tradeoff_refs": record.tradeoff_refs,
        "alternative_path_refs": record.alternative_path_refs,
        "responsibility_boundary_ref": record.responsibility_boundary_ref,
        "user_final_choice_ref": record.user_final_choice_ref,
        "agent_made_final_choice": record.agent_made_final_choice,
        "system_blocked_after_user_acceptance": record.system_blocked_after_user_acceptance,
        "redline_refs": record.redline_refs,
    }


def _trust_release_gate_from_payload(payload: dict[str, Any]) -> TrustReleaseGateRecord:
    raw = payload.get("release_gate") if isinstance(payload.get("release_gate"), dict) else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="release_gate payload must be an object")
    return trust_release_gate_record_from_dict(raw)


def _trust_release_gate_summary(record: TrustReleaseGateRecord) -> dict[str, Any]:
    return {
        "release_ref": record.release_ref,
        "anti_flattery_pressure_test_ref": record.anti_flattery_pressure_test_ref,
        "multi_turn_pressure_test_ref": record.multi_turn_pressure_test_ref,
        "expert_veto_ref": record.expert_veto_ref,
        "weakness_collapse_check_ref": record.weakness_collapse_check_ref,
        "mock_honesty_check_ref": record.mock_honesty_check_ref,
        "cold_start_honesty_check_ref": record.cold_start_honesty_check_ref,
    }


def _trust_release_check_summary(record: TrustReleaseCheckRecord) -> dict[str, Any]:
    return {
        "check_ref": record.check_ref,
        "release_ref": record.release_ref,
        "check_kind": record.check_kind,
        "scenario_ref": record.scenario_ref,
        "expected_behavior_ref": record.expected_behavior_ref,
        "observed_behavior_ref": record.observed_behavior_ref,
        "verdict": record.verdict,
        "source_hash": record.source_hash,
        "evidence_refs": record.evidence_refs,
        "validation_result_refs": record.validation_result_refs,
    }


def _trust_pressure_run_summary(record: TrustPressureRunRecord) -> dict[str, Any]:
    return {
        "runner_ref": record.runner_ref,
        "release_ref": record.release_ref,
        "runner_mode": record.runner_mode,
        "source_hash": record.source_hash,
        "release_gate_ref": record.release_gate_ref,
        "check_refs": record.check_refs,
        "scenario_refs": record.scenario_refs,
        "evidence_refs": record.evidence_refs,
        "validation_result_refs": record.validation_result_refs,
        "failed_scenario_refs": record.failed_scenario_refs,
    }


def _trust_release_approval_summary(record: TrustReleaseApprovalRecord) -> dict[str, Any]:
    return {
        "approval_ref": record.approval_ref,
        "release_ref": record.release_ref,
        "release_gate_ref": record.release_gate_ref,
        "pressure_run_ref": record.pressure_run_ref,
        "expert_review_ref": record.expert_review_ref,
        "artifact_ref": record.artifact_ref,
        "approval_protocol_ref": record.approval_protocol_ref,
        "verdict": record.verdict,
        "source_hash": record.source_hash,
        "evidence_refs": record.evidence_refs,
        "signed_approval_ref": record.signed_approval_ref,
        "residual_blocker_refs": record.residual_blocker_refs,
    }


@app.post("/api/research-os/trust/claims")
def research_os_trust_record_claim(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = TRUST_DISCLOSURE_REGISTRY.record_claim(_trust_claim_from_payload(payload))
        return {**_trust_claim_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/independence_disclosures")
def research_os_trust_record_independence_disclosure(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = TRUST_DISCLOSURE_REGISTRY.record_independence_disclosure(
            _functional_independence_disclosure_from_payload(payload)
        )
        return {**_functional_independence_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/expert_reviews")
def research_os_trust_record_external_expert_review(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = TRUST_DISCLOSURE_REGISTRY.record_external_expert_review(
            _external_expert_review_from_payload(payload)
        )
        return {**_external_expert_review_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/expert_identities")
def research_os_trust_record_external_reviewer_identity(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = TRUST_EXPERT_SIGNATURE_REGISTRY.record_identity(_external_reviewer_identity_from_payload(payload))
        return {**_external_reviewer_identity_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/expert_signatures")
def research_os_trust_record_external_expert_signature(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    del user
    try:
        parsed = _external_expert_signature_payload(payload)
        review = TRUST_DISCLOSURE_REGISTRY.external_expert_review(parsed["review_ref"])
        record = TRUST_EXPERT_SIGNATURE_REGISTRY.record_signature(
            review=review,
            identity_ref=parsed["identity_ref"],
            signature_b64=parsed["signature_b64"],
            attestation_ref=parsed["attestation_ref"] or None,
            verified_signature_ref=parsed["verified_signature_ref"] or None,
        )
        return _external_expert_signature_summary(record)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"unknown expert signature dependency: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/user_autonomy")
def research_os_trust_record_user_autonomy(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = TRUST_DISCLOSURE_REGISTRY.record_user_autonomy(_user_autonomy_from_payload(payload))
        return {**_user_autonomy_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/release_checks")
def research_os_trust_record_release_check(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = TRUST_RELEASE_CHECK_REGISTRY.record_check(
            record_trust_release_check(
                release_ref=str(payload.get("release_ref") or ""),
                check_kind=str(payload.get("check_kind") or ""),
                scenario_ref=str(payload.get("scenario_ref") or ""),
                expected_behavior_ref=str(payload.get("expected_behavior_ref") or ""),
                observed_behavior_ref=str(payload.get("observed_behavior_ref") or ""),
                evidence_refs=tuple(str(v) for v in payload.get("evidence_refs") or ()),
                validation_result_refs=tuple(str(v) for v in payload.get("validation_result_refs") or ()),
                verdict=str(payload.get("verdict") or "passed"),
                check_ref=payload.get("check_ref"),
                silent_mock_fallback_used=bool(payload.get("silent_mock_fallback_used", False)),
            )
        )
        return {**_trust_release_check_summary(record), "recorded_by": user.username}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/release_check_suites")
def research_os_trust_record_release_check_suite(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        gate, checks = record_trust_release_check_suite(
            release_ref=str(payload.get("release_ref") or ""),
            checks=payload.get("checks") or (),
        )
        for check in checks:
            TRUST_RELEASE_CHECK_REGISTRY.record_check(check)
        TRUST_RELEASE_GATE_REGISTRY.record_gate(gate)
        return {
            "release_ref": gate.release_ref,
            "recorded_by": user.username,
            "release_gate": _trust_release_gate_summary(gate),
            "release_checks": [_trust_release_check_summary(record) for record in checks],
            "check_refs": {record.check_kind: record.check_ref for record in checks},
        }
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/pressure_runs")
def research_os_trust_record_pressure_run(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        run, gate, checks = record_trust_pressure_run(
            release_ref=str(payload.get("release_ref") or ""),
            runner_mode=str(payload.get("runner_mode") or ""),
            scenarios=payload.get("scenarios") or (),
            evidence_refs=tuple(str(v) for v in payload.get("evidence_refs") or ()),
            validation_result_refs=tuple(str(v) for v in payload.get("validation_result_refs") or ()),
            runner_ref=payload.get("runner_ref"),
            silent_mock_fallback_used=bool(payload.get("silent_mock_fallback_used", False)),
        )
        for check in checks:
            TRUST_RELEASE_CHECK_REGISTRY.record_check(check)
        TRUST_RELEASE_GATE_REGISTRY.record_gate(gate)
        TRUST_PRESSURE_RUN_REGISTRY.record_run(run)
        return {
            "runner_ref": run.runner_ref,
            "release_ref": run.release_ref,
            "recorded_by": user.username,
            "pressure_run": _trust_pressure_run_summary(run),
            "release_gate": _trust_release_gate_summary(gate),
            "release_checks": [_trust_release_check_summary(record) for record in checks],
            "check_refs": {record.check_kind: record.check_ref for record in checks},
        }
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/release_approvals")
def research_os_trust_record_release_approval(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        release_ref = str(payload.get("release_ref") or "")
        gate_ref = str(payload.get("release_gate_ref") or "")
        pressure_run_ref = str(payload.get("pressure_run_ref") or "")
        expert_review_ref = str(payload.get("expert_review_ref") or "")
        gate = TRUST_RELEASE_GATE_REGISTRY.gate(gate_ref)
        pressure_run = TRUST_PRESSURE_RUN_REGISTRY.run(pressure_run_ref)
        expert_review = TRUST_DISCLOSURE_REGISTRY.external_expert_review(expert_review_ref)
        record = record_trust_release_approval(
            release_ref=release_ref,
            release_gate=gate,
            pressure_run=pressure_run,
            expert_review=expert_review,
            artifact_ref=str(payload.get("artifact_ref") or ""),
            approval_protocol_ref=str(payload.get("approval_protocol_ref") or ""),
            verdict=str(payload.get("verdict") or ""),
            evidence_refs=tuple(str(v) for v in payload.get("evidence_refs") or ()),
            signed_approval_ref=payload.get("signed_approval_ref"),
            residual_blocker_refs=tuple(str(v) for v in payload.get("residual_blocker_refs") or ()),
            approval_ref=payload.get("approval_ref"),
            silent_mock_fallback_used=bool(payload.get("silent_mock_fallback_used", False)),
        )
        persisted = TRUST_RELEASE_APPROVAL_REGISTRY.record_approval(record)
        return {
            "approval_ref": persisted.approval_ref,
            "release_ref": persisted.release_ref,
            "recorded_by": user.username,
            "release_approval": _trust_release_approval_summary(persisted),
        }
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"unknown trust release approval ref: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/trust/release_gates")
def research_os_trust_record_release_gate(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        record = TRUST_RELEASE_GATE_REGISTRY.record_gate(_trust_release_gate_from_payload(payload))
        return {"release_ref": record.release_ref, "recorded_by": user.username}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/trust/summary")
def research_os_trust_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    gates = TRUST_RELEASE_GATE_REGISTRY.gates()
    checks = TRUST_RELEASE_CHECK_REGISTRY.checks()
    pressure_runs = TRUST_PRESSURE_RUN_REGISTRY.runs()
    release_approvals = TRUST_RELEASE_APPROVAL_REGISTRY.approvals()
    claims = TRUST_DISCLOSURE_REGISTRY.claims()
    disclosures = TRUST_DISCLOSURE_REGISTRY.independence_disclosures()
    expert_reviews = TRUST_DISCLOSURE_REGISTRY.external_expert_reviews()
    expert_identities = TRUST_EXPERT_SIGNATURE_REGISTRY.identities()
    expert_signatures = TRUST_EXPERT_SIGNATURE_REGISTRY.signatures()
    user_autonomy_records = TRUST_DISCLOSURE_REGISTRY.user_autonomy_records()
    return {
        "user": user.username,
        "trust_claim_total": len(claims),
        "trust_claims": [_trust_claim_summary(record) for record in claims],
        "independence_disclosure_total": len(disclosures),
        "independence_disclosures": [_functional_independence_summary(record) for record in disclosures],
        "expert_review_total": len(expert_reviews),
        "expert_reviews": [_external_expert_review_summary(record) for record in expert_reviews],
        "expert_identity_total": len(expert_identities),
        "expert_identities": [_external_reviewer_identity_summary(record) for record in expert_identities],
        "expert_signature_total": len(expert_signatures),
        "expert_signatures": [_external_expert_signature_summary(record) for record in expert_signatures],
        "user_autonomy_total": len(user_autonomy_records),
        "user_autonomy_records": [_user_autonomy_summary(record) for record in user_autonomy_records],
        "release_gate_total": len(gates),
        "release_gates": [_trust_release_gate_summary(record) for record in gates],
        "release_check_total": len(checks),
        "release_checks": [_trust_release_check_summary(record) for record in checks],
        "pressure_run_total": len(pressure_runs),
        "pressure_runs": [_trust_pressure_run_summary(record) for record in pressure_runs],
        "release_approval_total": len(release_approvals),
        "release_approvals": [_trust_release_approval_summary(record) for record in release_approvals],
    }


def _rdp_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _rdp_manifest_from_payload(payload: dict[str, Any]) -> RDPManifest:
    raw = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else payload
    return RDPManifest(
        research_question=str(raw.get("research_question") or ""),
        graph_refs=_rdp_tuple(raw.get("graph_refs")),
        data_refs=_rdp_tuple(raw.get("data_refs")),
        dataset_version_refs=_rdp_tuple(raw.get("dataset_version_refs")),
        market_data_use_validation_refs=_rdp_tuple(raw.get("market_data_use_validation_refs")),
        ingestion_skill_refs=_rdp_tuple(raw.get("ingestion_skill_refs")),
        mathematical_refs=_rdp_tuple(raw.get("mathematical_refs")),
        theory_binding_refs=_rdp_tuple(raw.get("theory_binding_refs")),
        consistency_check_refs=_rdp_tuple(raw.get("consistency_check_refs")),
        methodology_choice_refs=_rdp_tuple(raw.get("methodology_choice_refs")),
        responsibility_refs=_rdp_tuple(raw.get("responsibility_refs")),
        asset_refs=_rdp_tuple(raw.get("asset_refs")),
        code_refs=_rdp_tuple(raw.get("code_refs")),
        environment_lock_ref=str(raw.get("environment_lock_ref") or ""),
        reproducibility_command=str(raw.get("reproducibility_command") or ""),
        artifact_hash=str(raw.get("artifact_hash") or ""),
        test_refs=_rdp_tuple(raw.get("test_refs")),
        run_refs=_rdp_tuple(raw.get("run_refs")),
        honest_n_refs=_rdp_tuple(raw.get("honest_n_refs")),
        cost_and_execution_assumptions=_rdp_tuple(raw.get("cost_and_execution_assumptions")),
        attribution_refs=_rdp_tuple(raw.get("attribution_refs")),
        known_limits=_rdp_tuple(raw.get("known_limits")),
        unverified_residuals=_rdp_tuple(raw.get("unverified_residuals")),
        verifier_verdict_ref=str(raw.get("verifier_verdict_ref") or ""),
        compiler_artifact_refs=_rdp_tuple(raw.get("compiler_artifact_refs")),
        mathematical_spine_chain_refs=_rdp_tuple(raw.get("mathematical_spine_chain_refs")),
        goal_entrypoint_coverage_refs=_rdp_tuple(raw.get("goal_entrypoint_coverage_refs")),
        approval_ref=raw.get("approval_ref"),
        deployment_refs=_rdp_tuple(raw.get("deployment_refs")),
        monitor_refs=_rdp_tuple(raw.get("monitor_refs")),
        rollback_plan_ref=raw.get("rollback_plan_ref"),
        retire_plan_ref=raw.get("retire_plan_ref"),
        target_runtime=raw.get("target_runtime") or RuntimeStatus.OFFLINE.value,
        llm_call_refs=_rdp_tuple(raw.get("llm_call_refs")),
        source_file_refs=_rdp_tuple(raw.get("source_file_refs")),
        package_id=str(raw.get("package_id") or ""),
        manifest_version=str(raw.get("manifest_version") or "rdp.v2"),
    )


def _rdp_manifest_summary(manifest: RDPManifest) -> dict[str, Any]:
    runtime = manifest.target_runtime.value if hasattr(manifest.target_runtime, "value") else str(manifest.target_runtime)
    return {
        "package_id": manifest.package_id,
        "manifest_version": manifest.manifest_version,
        "research_question": manifest.research_question,
        "asset_refs": manifest.asset_refs,
        "run_refs": manifest.run_refs,
        "market_data_use_validation_refs": manifest.market_data_use_validation_refs,
        "compiler_artifact_refs": manifest.compiler_artifact_refs,
        "mathematical_spine_chain_refs": manifest.mathematical_spine_chain_refs,
        "goal_entrypoint_coverage_refs": manifest.goal_entrypoint_coverage_refs,
        "target_runtime": runtime,
        "artifact_hash": manifest.artifact_hash,
    }


def _rdp_manifest_violation_message(manifest: RDPManifest, *, has_user_waiver: bool) -> str:
    violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
    return "; ".join(violation.code for violation in violations)


def _validate_rdp_manifest_registered_refs(manifest: RDPManifest) -> None:
    covered_dataset_refs: set[str] = set()
    allowed_use_contexts = {
        ValidationUseContext.BACKTEST.value,
        ValidationUseContext.CONFIRMATORY_VALIDATION.value,
    }
    for validation_ref in manifest.market_data_use_validation_refs:
        try:
            record = MARKET_DATA_REGISTRY.use_validation(validation_ref)
        except KeyError as exc:
            raise ValueError(f"RDP manifest market_data_use_validation_ref {validation_ref!r} is not recorded") from exc
        if not bool(getattr(record, "accepted", False)):
            raise ValueError(f"RDP manifest market_data_use_validation_ref {validation_ref!r} is not accepted")
        if tuple(getattr(record, "violation_codes", ()) or ()):
            raise ValueError(f"RDP manifest market_data_use_validation_ref {validation_ref!r} has unresolved violations")
        use_context = str(getattr(record, "use_context", "") or "")
        if use_context not in allowed_use_contexts:
            raise ValueError(f"RDP manifest market_data_use_validation_ref {validation_ref!r} is not for backtest evidence")
        dataset_refs = tuple(str(ref) for ref in getattr(record, "dataset_refs", ()) or ())
        if not dataset_refs:
            raise ValueError(f"RDP manifest market_data_use_validation_ref {validation_ref!r} has no dataset refs")
        for dataset_ref in dataset_refs:
            try:
                dataset = MARKET_DATA_REGISTRY.dataset(dataset_ref)
            except KeyError as exc:
                raise ValueError(
                    f"RDP manifest market_data_use_validation_ref {validation_ref!r} cites unknown dataset {dataset_ref!r}"
                ) from exc
            if not (
                getattr(dataset, "known_at_ref", None)
                and getattr(dataset, "effective_at_ref", None)
                and getattr(dataset, "pit_bitemporal_rules_ref", None)
            ):
                raise ValueError(
                    f"RDP manifest market_data_use_validation_ref {validation_ref!r} cites dataset without PIT timing refs"
                )
            covered_dataset_refs.add(dataset_ref)

    manifest_dataset_refs = {str(ref) for ref in manifest.data_refs if str(ref).startswith("dataset:")}
    missing_dataset_refs = sorted(manifest_dataset_refs - covered_dataset_refs)
    if missing_dataset_refs:
        raise ValueError(
            "RDP manifest market_data_use_validation_refs do not cover data_ref "
            f"{missing_dataset_refs[0]!r}"
        )

    artifacts: list[CompilerArtifactRecord] = []
    for artifact_ref in manifest.compiler_artifact_refs:
        try:
            artifacts.append(COMPILER_IR_STORE.artifact(artifact_ref))
        except KeyError as exc:
            raise ValueError(f"RDP manifest compiler_artifact_ref {artifact_ref!r} is not recorded") from exc

    for chain_ref in manifest.mathematical_spine_chain_refs:
        try:
            MATHEMATICAL_SPINE_CHAIN_REGISTRY.chain(chain_ref)
        except KeyError as exc:
            raise ValueError(f"RDP manifest mathematical_spine_chain_ref {chain_ref!r} is not recorded") from exc

    coverages: list[GoalEntrypointCoverageRecord] = []
    for coverage_ref in manifest.goal_entrypoint_coverage_refs:
        try:
            coverages.append(GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(coverage_ref))
        except KeyError as exc:
            raise ValueError(f"RDP manifest goal_entrypoint_coverage_ref {coverage_ref!r} is not recorded") from exc

    manifest_chain_refs = set(manifest.mathematical_spine_chain_refs)
    lifecycle_refs = {str(ref) for coverage in coverages for ref in coverage.lifecycle_refs}
    for artifact in artifacts:
        if artifact.artifact_ref not in lifecycle_refs:
            raise ValueError(
                f"RDP manifest goal_entrypoint_coverage_refs do not cite compiler_artifact_ref {artifact.artifact_ref!r}"
            )
        for chain_ref in artifact.mathematical_spine_chain_refs:
            if chain_ref not in manifest_chain_refs:
                raise ValueError(
                    f"RDP manifest missing mathematical_spine_chain_ref {chain_ref!r} required by compiler artifact"
                )
            if chain_ref not in lifecycle_refs:
                raise ValueError(
                    f"RDP manifest goal_entrypoint_coverage_refs do not cite mathematical_spine_chain_ref {chain_ref!r}"
                )


def _validate_rdp_manifest_for_runtime(manifest: RDPManifest, *, has_user_waiver: bool) -> None:
    violation_message = _rdp_manifest_violation_message(manifest, has_user_waiver=has_user_waiver)
    if violation_message:
        raise ValueError(violation_message)
    _validate_rdp_manifest_registered_refs(manifest)


def _validate_rdp_publish_attestations(manifest: RDPManifest) -> None:
    manifest_hash = "sha16:" + content_hash(manifest.to_open_dict())
    if manifest.source_file_refs:
        integrity_records = [
            record
            for record in RDP_SOURCE_RUN_INTEGRITY_STORE.records(manifest.package_id)
            if record.manifest_hash == manifest_hash and record.artifact_hash == manifest.artifact_hash
        ]
        covered_run_refs = {record.run_ref for record in integrity_records}
        missing_run_refs = sorted(set(manifest.run_refs) - covered_run_refs)
        if missing_run_refs:
            raise ValueError(
                f"RDP source-run integrity attestation is required before publish for run_ref {missing_run_refs[0]!r}"
            )

    runtime = manifest.target_runtime.value if hasattr(manifest.target_runtime, "value") else str(manifest.target_runtime)
    if runtime == RuntimeStatus.LIVE.value:
        deployment_attestations = [
            record
            for record in RDP_DEPLOYMENT_ATTESTATION_STORE.attestations(manifest.package_id)
            if record.manifest_hash == manifest_hash
        ]
        covered_deployment_refs = {record.deployment_ref for record in deployment_attestations}
        missing_deployment_refs = sorted(set(manifest.deployment_refs) - covered_deployment_refs)
        if missing_deployment_refs:
            raise ValueError(
                "RDP deployment attestation is required before live publish "
                f"for deployment_ref {missing_deployment_refs[0]!r}"
            )


def _rdp_publication_by_hash(package_id: str, publish_hash: str):
    normalized = str(publish_hash or "").strip()
    if not normalized:
        raise ValueError("local_publish_hash is required before external publication proof")
    for record in RDP_PACKAGE_PUBLISH_STORE.publications(package_id):
        if record.publish_hash == normalized:
            return record
    raise ValueError(f"unknown local_publish_hash: {normalized}")


def _rdp_external_proof_by_hash(package_id: str, proof_hash: str):
    normalized = str(proof_hash or "").strip()
    if not normalized:
        raise ValueError("external_proof_hash is required before CI release attestation")
    for record in RDP_EXTERNAL_PUBLICATION_PROOF_STORE.proofs(package_id):
        if record.proof_hash == normalized:
            return record
    raise ValueError(f"unknown external_proof_hash: {normalized}")


_RDP_CI_RUNNER_ALLOWED_RESULT_FIELDS = {
    "ci_system_ref",
    "ci_workflow_ref",
    "ci_run_ref",
    "source_commit_ref",
    "ci_status",
    "artifact_digest",
    "test_report_ref",
    "test_report_hash",
    "build_log_digest",
    "required_check_refs",
    "failed_check_refs",
    "skipped_check_refs",
    "missing_check_refs",
    "evidence_refs",
}
_RDP_CI_RUNNER_SEQUENCE_RESULT_FIELDS = {
    "required_check_refs",
    "failed_check_refs",
    "skipped_check_refs",
    "missing_check_refs",
    "evidence_refs",
}
_RDP_CI_RUNNER_SCALAR_RESULT_FIELDS = _RDP_CI_RUNNER_ALLOWED_RESULT_FIELDS - _RDP_CI_RUNNER_SEQUENCE_RESULT_FIELDS
_RDP_CI_RUNNER_FORBIDDEN_FIELD_MARKERS = (
    "api_key",
    "api_secret",
    "artifact_bytes",
    "artifact_payload",
    "ci_log",
    "device_code",
    "oauth_token",
    "provider_token",
    "raw_",
    "secret",
    "stderr",
    "stdout",
    "token",
)
_RDP_EXTERNAL_UPLOADER_ALLOWED_REQUEST_FIELDS = {
    "local_publish_hash",
    "archive_sha256",
    "trust_release_ref",
    "trust_release_approval_ref",
    "external_channel",
    "immutable_pointer_ref",
    "destination_allowlist_ref",
    "evidence_refs",
    "has_user_waiver",
}
_RDP_EXTERNAL_UPLOADER_ALLOWED_RESULT_FIELDS = {
    "external_channel",
    "external_uri_digest",
    "immutable_pointer_ref",
    "destination_allowlist_ref",
    "publication_status",
    "evidence_refs",
}
_RDP_EXTERNAL_UPLOADER_SEQUENCE_FIELDS = {"evidence_refs"}
_RDP_EXTERNAL_UPLOADER_SCALAR_RESULT_FIELDS = (
    _RDP_EXTERNAL_UPLOADER_ALLOWED_RESULT_FIELDS - _RDP_EXTERNAL_UPLOADER_SEQUENCE_FIELDS
)
_RDP_EXTERNAL_UPLOADER_FORBIDDEN_EXACT_FIELDS = {
    "artifact_bytes",
    "artifact_payload",
    "external_uri",
    "local_archive_path",
    "published_archive_path",
    "raw_artifact",
    "raw_external_uri",
    "signed_url",
}
_RDP_EXTERNAL_UPLOADER_FORBIDDEN_FIELD_MARKERS = (
    "api_key",
    "api_secret",
    "artifact_bytes",
    "artifact_payload",
    "device_code",
    "oauth_token",
    "provider_token",
    "raw_",
    "secret",
    "stderr",
    "stdout",
    "token",
)
_RDP_DEPLOYMENT_RUNNER_ALLOWED_REQUEST_FIELDS = {
    "deployment_ref",
    "source_bundle_required",
    "has_user_waiver",
}
_RDP_DEPLOYMENT_RUNNER_ALLOWED_RESULT_FIELDS = {
    "deployment_ref",
    "deployment_status",
    "deployment_event_ref",
    "deployment_artifact_digest",
    "monitor_refs",
    "rollback_plan_ref",
    "retire_plan_ref",
    "evidence_refs",
}
_RDP_DEPLOYMENT_RUNNER_SEQUENCE_FIELDS = {"monitor_refs", "evidence_refs"}
_RDP_DEPLOYMENT_RUNNER_SCALAR_RESULT_FIELDS = (
    _RDP_DEPLOYMENT_RUNNER_ALLOWED_RESULT_FIELDS - _RDP_DEPLOYMENT_RUNNER_SEQUENCE_FIELDS
)
_RDP_DEPLOYMENT_RUNNER_FORBIDDEN_EXACT_FIELDS = {
    "deploy_payload",
    "kubeconfig",
    "manifest_payload",
    "package_path",
    "raw_deploy_payload",
    "raw_manifest",
    "raw_package",
    "ssh_key",
}
_RDP_DEPLOYMENT_RUNNER_FORBIDDEN_FIELD_MARKERS = (
    "api_key",
    "api_secret",
    "artifact_bytes",
    "artifact_payload",
    "device_code",
    "oauth_token",
    "provider_token",
    "raw_",
    "secret",
    "stderr",
    "stdout",
    "token",
)
_RDP_DEPLOYMENT_HEALTH_ALLOWED_FIELDS = {
    "deployment_attestation_hash",
    "deployment_ref",
    "health_status",
    "health_check_refs",
    "monitor_refs",
    "rollback_plan_ref",
    "rollback_readiness_ref",
    "rollback_drill_ref",
    "retire_plan_ref",
    "evidence_refs",
    "has_user_waiver",
}
_RDP_DEPLOYMENT_HEALTH_SEQUENCE_FIELDS = {"health_check_refs", "monitor_refs", "evidence_refs"}
_RDP_DEPLOYMENT_HEALTH_FORBIDDEN_EXACT_FIELDS = {
    "health_response",
    "kubeconfig",
    "manifest_payload",
    "package_payload",
    "provider_payload",
    "raw_health_response",
    "raw_log",
    "raw_manifest",
    "raw_package",
    "rollback_payload",
    "ssh_key",
}
_RDP_DEPLOYMENT_HEALTH_FORBIDDEN_FIELD_MARKERS = (
    "api_key",
    "api_secret",
    "device_code",
    "log",
    "oauth_token",
    "payload",
    "provider_token",
    "raw_",
    "secret",
    "stderr",
    "stdout",
    "token",
)


def _rdp_validate_trust_release_refs(trust_release_ref: str, trust_release_approval_ref: str) -> None:
    try:
        TRUST_RELEASE_GATE_REGISTRY.gate(trust_release_ref)
    except KeyError as exc:
        raise ValueError(f"unknown trust_release_ref: {trust_release_ref}") from exc
    try:
        approval = TRUST_RELEASE_APPROVAL_REGISTRY.approval(trust_release_approval_ref)
    except KeyError as exc:
        raise ValueError(f"unknown trust_release_approval_ref: {trust_release_approval_ref}") from exc
    if approval.release_ref != trust_release_ref:
        raise ValueError("trust_release_approval_ref does not match trust_release_ref")
    if approval.verdict != "approved":
        raise ValueError("trust_release_approval_ref is not approved")


def _rdp_ci_release_attestation_fields(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "ci_system_ref": str(source.get("ci_system_ref") or ""),
        "ci_workflow_ref": str(source.get("ci_workflow_ref") or ""),
        "ci_run_ref": str(source.get("ci_run_ref") or ""),
        "source_commit_ref": str(source.get("source_commit_ref") or ""),
        "ci_status": str(source.get("ci_status") or "passed"),
        "artifact_digest": str(source.get("artifact_digest") or ""),
        "test_report_ref": str(source.get("test_report_ref") or ""),
        "test_report_hash": str(source.get("test_report_hash") or ""),
        "build_log_digest": str(source.get("build_log_digest") or ""),
        "required_check_refs": source.get("required_check_refs") or (),
        "failed_check_refs": source.get("failed_check_refs") or (),
        "skipped_check_refs": source.get("skipped_check_refs") or (),
        "missing_check_refs": source.get("missing_check_refs") or (),
        "evidence_refs": source.get("evidence_refs") or (),
    }


def _reject_rdp_external_uploader_raw_fields(
    value: Any,
    *,
    path: str,
    top_level_path: str,
    allowed_top_fields: set[str],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in _RDP_EXTERNAL_UPLOADER_FORBIDDEN_EXACT_FIELDS or lowered.endswith("_payload") or any(
                marker in lowered for marker in _RDP_EXTERNAL_UPLOADER_FORBIDDEN_FIELD_MARKERS
            ):
                raise ValueError(
                    f"RDP external publication uploader cannot contain raw or secret-bearing field: {path}.{key_text}"
                )
            if path == top_level_path and key_text not in allowed_top_fields:
                raise ValueError(f"unsupported RDP external publication uploader field: {key_text}")
            _reject_rdp_external_uploader_raw_fields(
                child,
                path=f"{path}.{key_text}",
                top_level_path=top_level_path,
                allowed_top_fields=allowed_top_fields,
            )
    elif isinstance(value, (list, tuple, set)):
        for idx, child in enumerate(value):
            _reject_rdp_external_uploader_raw_fields(
                child,
                path=f"{path}[{idx}]",
                top_level_path=top_level_path,
                allowed_top_fields=allowed_top_fields,
            )


def _validate_rdp_external_uploader_field_shapes(source: dict[str, Any], *, label: str) -> None:
    for field in _RDP_EXTERNAL_UPLOADER_SCALAR_RESULT_FIELDS:
        if isinstance(source.get(field), (dict, list, tuple, set)):
            raise ValueError(f"{label} field must be scalar: {field}")
    value = source.get("evidence_refs")
    if isinstance(value, dict):
        raise ValueError(f"{label} field must be a ref list: evidence_refs")
    if isinstance(value, (list, tuple, set)) and any(isinstance(item, (dict, list, tuple, set)) for item in value):
        raise ValueError(f"{label} field must contain scalar refs: evidence_refs")


def _rdp_external_publication_fields(source: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_channel": str(source.get("external_channel") or payload.get("external_channel") or "object_store"),
        "external_uri_digest": str(source.get("external_uri_digest") or ""),
        "immutable_pointer_ref": str(source.get("immutable_pointer_ref") or payload.get("immutable_pointer_ref") or ""),
        "destination_allowlist_ref": str(
            source.get("destination_allowlist_ref") or payload.get("destination_allowlist_ref") or ""
        ),
        "evidence_refs": source.get("evidence_refs") or payload.get("evidence_refs") or (),
    }


def _rdp_external_uploader_result_from_raw(raw_result: Any, *, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        raise ValueError("RDP external publication uploader must return an object")
    _reject_rdp_external_uploader_raw_fields(
        raw_result,
        path="uploader_result",
        top_level_path="uploader_result",
        allowed_top_fields=_RDP_EXTERNAL_UPLOADER_ALLOWED_RESULT_FIELDS,
    )
    if contains_plaintext_secret(raw_result):
        raise ValueError("RDP external publication uploader result cannot contain plaintext secret")
    _validate_rdp_external_uploader_field_shapes(
        raw_result,
        label="RDP external publication uploader result",
    )
    publication_status = str(raw_result.get("publication_status") or "").strip().lower()
    if publication_status != "published":
        raise ValueError("RDP external publication uploader requires publication_status=published")
    return _rdp_external_publication_fields(raw_result, payload=payload)


def _reject_rdp_deployment_runner_raw_fields(
    value: Any,
    *,
    path: str,
    top_level_path: str,
    allowed_top_fields: set[str],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in _RDP_DEPLOYMENT_RUNNER_FORBIDDEN_EXACT_FIELDS or lowered.endswith("_payload") or any(
                marker in lowered for marker in _RDP_DEPLOYMENT_RUNNER_FORBIDDEN_FIELD_MARKERS
            ):
                raise ValueError(f"RDP deployment runner cannot contain raw or secret-bearing field: {path}.{key_text}")
            if path == top_level_path and key_text not in allowed_top_fields:
                raise ValueError(f"unsupported RDP deployment runner field: {key_text}")
            _reject_rdp_deployment_runner_raw_fields(
                child,
                path=f"{path}.{key_text}",
                top_level_path=top_level_path,
                allowed_top_fields=allowed_top_fields,
            )
    elif isinstance(value, (list, tuple, set)):
        for idx, child in enumerate(value):
            _reject_rdp_deployment_runner_raw_fields(
                child,
                path=f"{path}[{idx}]",
                top_level_path=top_level_path,
                allowed_top_fields=allowed_top_fields,
            )


def _validate_rdp_deployment_runner_field_shapes(source: dict[str, Any], *, label: str) -> None:
    for field in _RDP_DEPLOYMENT_RUNNER_SCALAR_RESULT_FIELDS:
        if isinstance(source.get(field), (dict, list, tuple, set)):
            raise ValueError(f"{label} field must be scalar: {field}")
    for field in _RDP_DEPLOYMENT_RUNNER_SEQUENCE_FIELDS:
        value = source.get(field)
        if isinstance(value, dict):
            raise ValueError(f"{label} field must be a ref list: {field}")
        if isinstance(value, (list, tuple, set)) and any(isinstance(item, (dict, list, tuple, set)) for item in value):
            raise ValueError(f"{label} field must contain scalar refs: {field}")


def _rdp_deployment_runner_result_from_raw(
    raw_result: Any,
    *,
    deployment_ref: str,
    manifest: RDPManifest,
) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        raise ValueError("RDP deployment runner must return an object")
    _reject_rdp_deployment_runner_raw_fields(
        raw_result,
        path="deployment_runner_result",
        top_level_path="deployment_runner_result",
        allowed_top_fields=_RDP_DEPLOYMENT_RUNNER_ALLOWED_RESULT_FIELDS,
    )
    if contains_plaintext_secret(raw_result):
        raise ValueError("RDP deployment runner result cannot contain plaintext secret")
    _validate_rdp_deployment_runner_field_shapes(raw_result, label="RDP deployment runner result")
    status = str(raw_result.get("deployment_status") or "").strip().lower()
    if status != "deployed":
        raise ValueError("RDP deployment runner requires deployment_status=deployed")
    result_deployment_ref = str(raw_result.get("deployment_ref") or deployment_ref or "").strip()
    if result_deployment_ref != deployment_ref:
        raise ValueError("RDP deployment runner deployment_ref does not match request")
    result_monitor_refs = tuple(str(ref).strip() for ref in _settings_tuple(raw_result.get("monitor_refs")) if str(ref).strip())
    if result_monitor_refs and result_monitor_refs != tuple(manifest.monitor_refs):
        raise ValueError("RDP deployment runner monitor_refs do not match manifest")
    rollback_plan_ref = str(raw_result.get("rollback_plan_ref") or manifest.rollback_plan_ref or "").strip()
    if rollback_plan_ref != str(manifest.rollback_plan_ref or "").strip():
        raise ValueError("RDP deployment runner rollback_plan_ref does not match manifest")
    retire_plan_ref = str(raw_result.get("retire_plan_ref") or manifest.retire_plan_ref or "").strip()
    if retire_plan_ref != str(manifest.retire_plan_ref or "").strip():
        raise ValueError("RDP deployment runner retire_plan_ref does not match manifest")
    return {
        "deployment_ref": result_deployment_ref,
        "deployment_event_ref": str(raw_result.get("deployment_event_ref") or ""),
        "deployment_artifact_digest": str(raw_result.get("deployment_artifact_digest") or ""),
        "evidence_refs": raw_result.get("evidence_refs") or (),
    }


def _reject_rdp_deployment_health_raw_fields(value: Any, *, path: str = "deployment_health") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in _RDP_DEPLOYMENT_HEALTH_FORBIDDEN_EXACT_FIELDS or any(
                marker in lowered for marker in _RDP_DEPLOYMENT_HEALTH_FORBIDDEN_FIELD_MARKERS
            ):
                raise ValueError(f"RDP deployment health proof cannot contain raw or secret-bearing field: {path}.{key_text}")
            if path == "deployment_health" and key_text not in _RDP_DEPLOYMENT_HEALTH_ALLOWED_FIELDS:
                raise ValueError(f"unsupported RDP deployment health field: {key_text}")
            _reject_rdp_deployment_health_raw_fields(child, path=f"{path}.{key_text}")
    elif isinstance(value, (list, tuple, set)):
        for idx, child in enumerate(value):
            _reject_rdp_deployment_health_raw_fields(child, path=f"{path}[{idx}]")


def _validate_rdp_deployment_health_field_shapes(payload: dict[str, Any]) -> None:
    for field in _RDP_DEPLOYMENT_HEALTH_SEQUENCE_FIELDS:
        value = payload.get(field)
        if isinstance(value, dict):
            raise ValueError(f"RDP deployment health proof field must be a ref list: {field}")
        if isinstance(value, (list, tuple, set)) and any(isinstance(item, (dict, list, tuple, set)) for item in value):
            raise ValueError(f"RDP deployment health proof field must contain scalar refs: {field}")


def _reject_rdp_ci_runner_raw_fields(value: Any, *, path: str = "runner_result") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered.endswith("_payload") or any(marker in lowered for marker in _RDP_CI_RUNNER_FORBIDDEN_FIELD_MARKERS):
                raise ValueError(f"RDP CI release runner result cannot contain raw or secret-bearing field: {path}.{key_text}")
            if (
                key_text not in _RDP_CI_RUNNER_ALLOWED_RESULT_FIELDS
                and path == "runner_result"
            ):
                raise ValueError(f"unsupported RDP CI release runner result field: {key_text}")
            _reject_rdp_ci_runner_raw_fields(child, path=f"{path}.{key_text}")
    elif isinstance(value, (list, tuple, set)):
        for idx, child in enumerate(value):
            _reject_rdp_ci_runner_raw_fields(child, path=f"{path}[{idx}]")


def _rdp_ci_runner_result_from_raw(raw_result: Any) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        raise ValueError("RDP CI release runner must return an object")
    _reject_rdp_ci_runner_raw_fields(raw_result)
    if contains_plaintext_secret(raw_result):
        raise ValueError("RDP CI release runner result cannot contain plaintext secret")
    for field in _RDP_CI_RUNNER_SCALAR_RESULT_FIELDS:
        if isinstance(raw_result.get(field), (dict, list, tuple, set)):
            raise ValueError(f"RDP CI release runner result field must be scalar: {field}")
    for field in _RDP_CI_RUNNER_SEQUENCE_RESULT_FIELDS:
        value = raw_result.get(field)
        if isinstance(value, dict):
            raise ValueError(f"RDP CI release runner result field must be a ref list: {field}")
        if isinstance(value, (list, tuple, set)) and any(isinstance(item, (dict, list, tuple, set)) for item in value):
            raise ValueError(f"RDP CI release runner result field must contain scalar refs: {field}")
    return _rdp_ci_release_attestation_fields(raw_result)


def _rdp_ci_release_runner_request(
    manifest: RDPManifest,
    local_publication: Any,
    external_proof: Any,
    *,
    payload: dict[str, Any],
    trust_release_ref: str,
    trust_release_approval_ref: str,
) -> dict[str, Any]:
    request = {
        "package_id": manifest.package_id,
        "target_runtime": manifest.target_runtime.value
        if hasattr(manifest.target_runtime, "value")
        else str(manifest.target_runtime),
        "manifest_hash": "sha16:" + content_hash(manifest.to_open_dict()),
        "local_publish_hash": local_publication.publish_hash,
        "external_proof_hash": external_proof.proof_hash,
        "archive_sha256": local_publication.archive_sha256,
        "trust_release_ref": trust_release_ref,
        "trust_release_approval_ref": trust_release_approval_ref,
        "source_file_refs": list(manifest.source_file_refs),
        "run_refs": list(manifest.run_refs),
        "ci_system_ref": str(payload.get("ci_system_ref") or ""),
        "ci_workflow_ref": str(payload.get("ci_workflow_ref") or ""),
        "source_commit_ref": str(payload.get("source_commit_ref") or ""),
        "required_check_refs": payload.get("required_check_refs") or (),
        "evidence_refs": payload.get("evidence_refs") or (),
    }
    if contains_plaintext_secret(request):
        raise ValueError("RDP CI release runner request cannot contain plaintext secret")
    return request


def _rdp_external_publication_uploader_request(
    manifest: RDPManifest,
    local_publication: Any,
    *,
    payload: dict[str, Any],
    archive_sha256: str,
    trust_release_ref: str,
    trust_release_approval_ref: str,
) -> dict[str, Any]:
    _reject_rdp_external_uploader_raw_fields(
        payload,
        path="uploader_request",
        top_level_path="uploader_request",
        allowed_top_fields=_RDP_EXTERNAL_UPLOADER_ALLOWED_REQUEST_FIELDS,
    )
    if contains_plaintext_secret(payload):
        raise ValueError("RDP external publication uploader request cannot contain plaintext secret")
    if archive_sha256 != local_publication.archive_sha256:
        raise ValueError("RDP external publication archive_sha256 does not match local publication")
    request = {
        "package_id": manifest.package_id,
        "target_runtime": manifest.target_runtime.value
        if hasattr(manifest.target_runtime, "value")
        else str(manifest.target_runtime),
        "manifest_hash": "sha16:" + content_hash(manifest.to_open_dict()),
        "local_publish_hash": local_publication.publish_hash,
        "archive_sha256": archive_sha256,
        "trust_release_ref": trust_release_ref,
        "trust_release_approval_ref": trust_release_approval_ref,
        "source_file_refs": list(manifest.source_file_refs),
        "run_refs": list(manifest.run_refs),
        "external_channel": str(payload.get("external_channel") or "object_store"),
        "immutable_pointer_ref": str(payload.get("immutable_pointer_ref") or ""),
        "destination_allowlist_ref": str(payload.get("destination_allowlist_ref") or ""),
        "evidence_refs": payload.get("evidence_refs") or (),
    }
    if contains_plaintext_secret(request):
        raise ValueError("RDP external publication uploader request cannot contain plaintext secret")
    return request


def _rdp_deployment_runner_request(
    manifest: RDPManifest,
    *,
    payload: dict[str, Any],
    deployment_ref: str,
    source_bundle_required: bool,
) -> dict[str, Any]:
    _reject_rdp_deployment_runner_raw_fields(
        payload,
        path="deployment_runner_request",
        top_level_path="deployment_runner_request",
        allowed_top_fields=_RDP_DEPLOYMENT_RUNNER_ALLOWED_REQUEST_FIELDS,
    )
    if contains_plaintext_secret(payload):
        raise ValueError("RDP deployment runner request cannot contain plaintext secret")
    if not deployment_ref:
        raise ValueError("deployment_ref is required")
    if manifest.deployment_refs and deployment_ref not in manifest.deployment_refs:
        raise ValueError("deployment_ref is not declared in manifest deployment_refs")
    request = {
        "package_id": manifest.package_id,
        "target_runtime": manifest.target_runtime.value
        if hasattr(manifest.target_runtime, "value")
        else str(manifest.target_runtime),
        "manifest_hash": "sha16:" + content_hash(manifest.to_open_dict()),
        "deployment_ref": deployment_ref,
        "approval_ref": manifest.approval_ref,
        "monitor_refs": list(manifest.monitor_refs),
        "rollback_plan_ref": manifest.rollback_plan_ref,
        "retire_plan_ref": manifest.retire_plan_ref,
        "source_file_refs": list(manifest.source_file_refs),
        "run_refs": list(manifest.run_refs),
        "artifact_hash": manifest.artifact_hash,
        "environment_lock_ref": manifest.environment_lock_ref,
        "source_bundle_required": source_bundle_required,
    }
    if contains_plaintext_secret(request):
        raise ValueError("RDP deployment runner request cannot contain plaintext secret")
    return request


def _run_rdp_external_publication_uploader(request: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    uploader = RDP_EXTERNAL_PUBLICATION_UPLOADER
    if uploader is None:
        raise ValueError("RDP external publication uploader is not configured")
    run_method = getattr(uploader, "run", None)
    if callable(run_method):
        raw_result = run_method(request)
    elif callable(uploader):
        raw_result = uploader(request)
    else:
        raise ValueError("RDP external publication uploader is not callable")
    return _rdp_external_uploader_result_from_raw(raw_result, payload=payload)


def _run_rdp_deployment_runner(request: dict[str, Any], *, deployment_ref: str, manifest: RDPManifest) -> dict[str, Any]:
    runner = RDP_DEPLOYMENT_RUNNER
    if runner is None:
        raise ValueError("RDP deployment runner is not configured")
    run_method = getattr(runner, "run", None)
    if callable(run_method):
        raw_result = run_method(request)
    elif callable(runner):
        raw_result = runner(request)
    else:
        raise ValueError("RDP deployment runner is not callable")
    return _rdp_deployment_runner_result_from_raw(raw_result, deployment_ref=deployment_ref, manifest=manifest)


def _run_rdp_ci_release_runner(request: dict[str, Any]) -> dict[str, Any]:
    runner = RDP_CI_RELEASE_RUNNER
    if runner is None:
        raise ValueError("RDP CI release runner is not configured")
    run_method = getattr(runner, "run", None)
    if callable(run_method):
        raw_result = run_method(request)
    elif callable(runner):
        raw_result = runner(request)
    else:
        raise ValueError("RDP CI release runner is not callable")
    return _rdp_ci_runner_result_from_raw(raw_result)


def _rdp_external_publication_response(record: Any) -> dict[str, Any]:
    return {
        "package_id": record.package_id,
        "external_channel": record.external_channel,
        "target_runtime": record.target_runtime,
        "local_publish_hash": record.local_publish_hash,
        "archive_sha256": record.archive_sha256,
        "external_uri_digest": record.external_uri_digest,
        "immutable_pointer_ref": record.immutable_pointer_ref,
        "destination_allowlist_ref": record.destination_allowlist_ref,
        "trust_release_ref": record.trust_release_ref,
        "trust_release_approval_ref": record.trust_release_approval_ref,
        "evidence_refs": list(record.evidence_refs),
        "proof_hash": record.proof_hash,
        "attested_by": record.attested_by,
        "attested_at": record.attested_at,
    }


def _rdp_deployment_attestation_response(record: Any) -> dict[str, Any]:
    return {
        "package_id": record.package_id,
        "deployment_ref": record.deployment_ref,
        "target_runtime": record.target_runtime,
        "attestation_hash": record.attestation_hash,
        "manifest_hash": record.manifest_hash,
        "source_bundle_index_sha256": record.source_bundle_index_sha256,
        "deployment_event_ref": getattr(record, "deployment_event_ref", ""),
        "deployment_artifact_digest": getattr(record, "deployment_artifact_digest", ""),
        "evidence_refs": list(getattr(record, "evidence_refs", ())),
        "attested_by": record.attested_by,
        "attested_at": record.attested_at,
    }


def _rdp_deployment_health_response(record: Any) -> dict[str, Any]:
    return {
        "package_id": record.package_id,
        "deployment_ref": record.deployment_ref,
        "target_runtime": record.target_runtime,
        "manifest_hash": record.manifest_hash,
        "deployment_attestation_hash": record.deployment_attestation_hash,
        "health_status": record.health_status,
        "health_check_refs": list(record.health_check_refs),
        "monitor_refs": list(record.monitor_refs),
        "rollback_plan_ref": record.rollback_plan_ref,
        "rollback_readiness_ref": record.rollback_readiness_ref,
        "rollback_drill_ref": record.rollback_drill_ref,
        "retire_plan_ref": record.retire_plan_ref,
        "evidence_refs": list(record.evidence_refs),
        "proof_hash": record.proof_hash,
        "attested_by": record.attested_by,
        "attested_at": record.attested_at,
    }


def _rdp_ci_release_attestation_response(record: Any) -> dict[str, Any]:
    return {
        "package_id": record.package_id,
        "target_runtime": record.target_runtime,
        "manifest_hash": record.manifest_hash,
        "local_publish_hash": record.local_publish_hash,
        "external_proof_hash": record.external_proof_hash,
        "archive_sha256": record.archive_sha256,
        "trust_release_ref": record.trust_release_ref,
        "trust_release_approval_ref": record.trust_release_approval_ref,
        "ci_system_ref": record.ci_system_ref,
        "ci_workflow_ref": record.ci_workflow_ref,
        "ci_run_ref": record.ci_run_ref,
        "source_commit_ref": record.source_commit_ref,
        "ci_status": record.ci_status,
        "artifact_digest": record.artifact_digest,
        "test_report_ref": record.test_report_ref,
        "test_report_hash": record.test_report_hash,
        "build_log_digest": record.build_log_digest,
        "required_check_refs": list(record.required_check_refs),
        "evidence_refs": list(record.evidence_refs),
        "attestation_hash": record.attestation_hash,
        "attested_by": record.attested_by,
        "attested_at": record.attested_at,
    }


@app.post("/api/research-os/rdp/manifests")
def research_os_rdp_record_manifest(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        has_user_waiver = bool(payload.get("has_user_waiver", False))
        candidate = _rdp_manifest_from_payload(payload)
        _validate_rdp_manifest_for_runtime(candidate, has_user_waiver=has_user_waiver)
        manifest = RDP_STORE.record_manifest(
            candidate,
            has_user_waiver=has_user_waiver,
        )
        return {
            "package_id": manifest.package_id,
            "manifest_version": manifest.manifest_version,
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/rdp/manifests")
def research_os_rdp_list_manifests(user=Depends(require_user_dependency)) -> dict[str, Any]:
    manifests = RDP_STORE.manifests()
    return {
        "user": user.username,
        "total": len(manifests),
        "manifests": [_rdp_manifest_summary(manifest) for manifest in manifests],
    }


@app.get("/api/research-os/rdp/manifests/{package_id}")
def research_os_rdp_get_manifest(package_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc
    return {"user": user.username, "manifest": manifest.to_open_dict()}


@app.post("/api/research-os/rdp/manifests/{package_id}/materialize")
def research_os_rdp_materialize_package(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc
    try:
        _validate_rdp_manifest_for_runtime(
            manifest,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
        package = RDP_PACKAGE_MATERIALIZER.materialize(
            manifest,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "package_id": package.package_id,
        "manifest_hash": package.manifest_hash,
        "manifest_path": package.manifest_path,
        "refs_index_path": package.refs_index_path,
        "source_file_refs": package.source_file_refs,
        "materialized_by": user.username,
    }


@app.post("/api/research-os/rdp/manifests/{package_id}/bundle_sources")
def research_os_rdp_bundle_source_files(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    has_user_waiver = bool(payload.get("has_user_waiver", False))
    try:
        _validate_rdp_manifest_for_runtime(manifest, has_user_waiver=has_user_waiver)
        package = RDP_PACKAGE_MATERIALIZER.materialize(
            manifest,
            has_user_waiver=has_user_waiver,
        )
        bundle = RDP_SOURCE_FILE_BUNDLER.bundle(
            manifest,
            source_map=payload.get("source_map") or {},
            has_user_waiver=has_user_waiver,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "package_id": bundle.package_id,
        "manifest_hash": package.manifest_hash,
        "manifest_path": package.manifest_path,
        "refs_index_path": package.refs_index_path,
        "source_files_index_path": bundle.index_path,
        "source_files_dir": bundle.files_dir,
        "source_files": [entry.__dict__ for entry in bundle.source_files],
        "bundled_by": user.username,
    }


@app.post("/api/research-os/rdp/manifests/{package_id}/deployment_attestations")
def research_os_rdp_record_deployment_attestation(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        _validate_rdp_manifest_for_runtime(
            manifest,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
        record = RDP_DEPLOYMENT_ATTESTATION_STORE.record_attestation(
            manifest,
            package_root=RDP_PACKAGE_MATERIALIZER.package_root,
            deployment_ref=str(payload.get("deployment_ref") or ""),
            attested_by=user.username,
            source_bundle_required=bool(payload.get("source_bundle_required", True)),
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _rdp_deployment_attestation_response(record)


@app.post("/api/research-os/rdp/manifests/{package_id}/deployment_attestations/run")
def research_os_rdp_run_deployment_attestation(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        has_user_waiver = bool(payload.get("has_user_waiver", False))
        source_bundle_required = bool(payload.get("source_bundle_required", True))
        deployment_ref = str(payload.get("deployment_ref") or "").strip()
        _validate_rdp_manifest_for_runtime(
            manifest,
            has_user_waiver=has_user_waiver,
        )
        runner_request = _rdp_deployment_runner_request(
            manifest,
            payload=payload,
            deployment_ref=deployment_ref,
            source_bundle_required=source_bundle_required,
        )
        runner_fields = _run_rdp_deployment_runner(
            runner_request,
            deployment_ref=deployment_ref,
            manifest=manifest,
        )
        record = RDP_DEPLOYMENT_ATTESTATION_STORE.record_attestation(
            manifest,
            package_root=RDP_PACKAGE_MATERIALIZER.package_root,
            **runner_fields,
            attested_by=user.username,
            source_bundle_required=source_bundle_required,
            has_user_waiver=has_user_waiver,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _rdp_deployment_attestation_response(record)


@app.post("/api/research-os/rdp/manifests/{package_id}/deployment_health_checks")
def research_os_rdp_record_deployment_health_check(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        has_user_waiver = bool(payload.get("has_user_waiver", False))
        _reject_rdp_deployment_health_raw_fields(payload)
        if contains_plaintext_secret(payload):
            raise ValueError("RDP deployment health proof cannot contain plaintext secret")
        _validate_rdp_deployment_health_field_shapes(payload)
        _validate_rdp_manifest_for_runtime(
            manifest,
            has_user_waiver=has_user_waiver,
        )
        record = RDP_DEPLOYMENT_HEALTH_CHECK_STORE.record_health_check(
            manifest,
            deployment_attestations=RDP_DEPLOYMENT_ATTESTATION_STORE.attestations(package_id),
            deployment_attestation_hash=str(payload.get("deployment_attestation_hash") or ""),
            deployment_ref=str(payload.get("deployment_ref") or ""),
            health_status=str(payload.get("health_status") or ""),
            health_check_refs=payload.get("health_check_refs") or (),
            monitor_refs=payload.get("monitor_refs") or (),
            rollback_plan_ref=str(payload.get("rollback_plan_ref") or ""),
            rollback_readiness_ref=str(payload.get("rollback_readiness_ref") or ""),
            rollback_drill_ref=str(payload.get("rollback_drill_ref") or ""),
            retire_plan_ref=str(payload.get("retire_plan_ref") or ""),
            evidence_refs=payload.get("evidence_refs") or (),
            attested_by=user.username,
            has_user_waiver=has_user_waiver,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _rdp_deployment_health_response(record)


@app.get("/api/research-os/rdp/manifests/{package_id}/archive")
def research_os_rdp_export_archive(package_id: str, user=Depends(require_user_dependency)):
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        _validate_rdp_manifest_for_runtime(manifest, has_user_waiver=False)
        record = RDP_PACKAGE_ARCHIVE_EXPORTER.export(manifest)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return FileResponse(
        record.archive_path,
        media_type="application/zip",
        filename=f"{record.package_id}.zip",
        headers={
            "X-RDP-Archive-SHA256": record.archive_sha256,
            "X-RDP-Archive-File-Count": str(record.file_count),
            "X-RDP-Archive-User": user.username,
        },
    )


@app.post("/api/research-os/rdp/manifests/{package_id}/source_run_integrity_attestations")
def research_os_rdp_record_source_run_integrity(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        _validate_rdp_manifest_for_runtime(
            manifest,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
        record = RDP_SOURCE_RUN_INTEGRITY_STORE.record_integrity(
            manifest,
            package_root=RDP_PACKAGE_MATERIALIZER.package_root,
            run_root=RUN_ROOT,
            run_id=str(payload.get("run_id") or ""),
            source_file_ref=payload.get("source_file_ref"),
            attested_by=user.username,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "package_id": record.package_id,
        "run_ref": record.run_ref,
        "run_id": record.run_id,
        "source_file_ref": record.source_file_ref,
        "artifact_hash": record.artifact_hash,
        "integrity_hash": record.integrity_hash,
        "source_bundle_index_sha256": record.source_bundle_index_sha256,
        "run_strategy_sha256": record.run_strategy_sha256,
        "attested_by": record.attested_by,
        "attested_at": record.attested_at,
    }


@app.post("/api/research-os/rdp/manifests/{package_id}/publish")
def research_os_rdp_publish_package(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    has_user_waiver = bool(payload.get("has_user_waiver", False))
    trust_release_ref = str(payload.get("trust_release_ref") or "").strip()
    if not trust_release_ref:
        raise HTTPException(status_code=422, detail="trust_release_ref is required before RDP publish")
    trust_release_approval_ref = str(payload.get("trust_release_approval_ref") or "").strip()
    if not trust_release_approval_ref:
        raise HTTPException(status_code=422, detail="trust_release_approval_ref is required before RDP publish")
    try:
        TRUST_RELEASE_GATE_REGISTRY.gate(trust_release_ref)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"unknown trust_release_ref: {trust_release_ref}") from exc
    try:
        approval = TRUST_RELEASE_APPROVAL_REGISTRY.approval(trust_release_approval_ref)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"unknown trust_release_approval_ref: {trust_release_approval_ref}") from exc
    if approval.release_ref != trust_release_ref:
        raise HTTPException(status_code=422, detail="trust_release_approval_ref does not match trust_release_ref")
    if approval.verdict != "approved":
        raise HTTPException(status_code=422, detail="trust_release_approval_ref is not approved")
    try:
        _validate_rdp_manifest_for_runtime(manifest, has_user_waiver=has_user_waiver)
        archive = RDP_PACKAGE_ARCHIVE_EXPORTER.export(
            manifest,
            has_user_waiver=has_user_waiver,
        )
        _validate_rdp_publish_attestations(manifest)
        record = RDP_PACKAGE_PUBLISHER.publish(
            manifest,
            archive,
            channel=str(payload.get("channel") or "local_registry"),
            published_by=user.username,
            has_user_waiver=has_user_waiver,
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
        )
        persisted = RDP_PACKAGE_PUBLISH_STORE.record_publication(record)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "package_id": persisted.package_id,
        "channel": persisted.channel,
        "target_runtime": persisted.target_runtime,
        "archive_sha256": persisted.archive_sha256,
        "published_archive_path": persisted.published_archive_path,
        "publish_hash": persisted.publish_hash,
        "trust_release_ref": persisted.trust_release_ref,
        "trust_release_approval_ref": persisted.trust_release_approval_ref,
        "published_by": persisted.published_by,
        "published_at": persisted.published_at,
    }


@app.post("/api/research-os/rdp/manifests/{package_id}/external_publications")
def research_os_rdp_record_external_publication(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        local_publication = _rdp_publication_by_hash(package_id, str(payload.get("local_publish_hash") or ""))
        trust_release_ref = str(payload.get("trust_release_ref") or local_publication.trust_release_ref or "").strip()
        trust_release_approval_ref = str(
            payload.get("trust_release_approval_ref") or local_publication.trust_release_approval_ref or ""
        ).strip()
        _rdp_validate_trust_release_refs(trust_release_ref, trust_release_approval_ref)
        record = RDP_EXTERNAL_PUBLICATION_PROOF_STORE.record_proof(
            manifest,
            local_publication,
            external_channel=str(payload.get("external_channel") or ""),
            external_uri=str(payload.get("external_uri") or ""),
            immutable_pointer_ref=str(payload.get("immutable_pointer_ref") or ""),
            destination_allowlist_ref=str(payload.get("destination_allowlist_ref") or ""),
            evidence_refs=payload.get("evidence_refs") or (),
            attested_by=user.username,
            archive_sha256=str(payload.get("archive_sha256") or ""),
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _rdp_external_publication_response(record)


@app.post("/api/research-os/rdp/manifests/{package_id}/external_publications/run")
def research_os_rdp_run_external_publication(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        local_publication = _rdp_publication_by_hash(package_id, str(payload.get("local_publish_hash") or ""))
        archive_sha256 = str(payload.get("archive_sha256") or local_publication.archive_sha256 or "").strip()
        trust_release_ref = str(payload.get("trust_release_ref") or local_publication.trust_release_ref or "").strip()
        trust_release_approval_ref = str(
            payload.get("trust_release_approval_ref") or local_publication.trust_release_approval_ref or ""
        ).strip()
        _rdp_validate_trust_release_refs(trust_release_ref, trust_release_approval_ref)
        runner_request = _rdp_external_publication_uploader_request(
            manifest,
            local_publication,
            payload=payload,
            archive_sha256=archive_sha256,
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
        )
        proof_fields = _run_rdp_external_publication_uploader(runner_request, payload=payload)
        record = RDP_EXTERNAL_PUBLICATION_PROOF_STORE.record_proof_from_digest(
            manifest,
            local_publication,
            **proof_fields,
            attested_by=user.username,
            archive_sha256=archive_sha256,
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _rdp_external_publication_response(record)


@app.post("/api/research-os/rdp/manifests/{package_id}/ci_release_attestations")
def research_os_rdp_record_ci_release_attestation(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        local_publication = _rdp_publication_by_hash(package_id, str(payload.get("local_publish_hash") or ""))
        external_proof = _rdp_external_proof_by_hash(package_id, str(payload.get("external_proof_hash") or ""))
        trust_release_ref = str(payload.get("trust_release_ref") or local_publication.trust_release_ref or "").strip()
        trust_release_approval_ref = str(
            payload.get("trust_release_approval_ref") or local_publication.trust_release_approval_ref or ""
        ).strip()
        _rdp_validate_trust_release_refs(trust_release_ref, trust_release_approval_ref)
        attestation_fields = _rdp_ci_release_attestation_fields(payload)
        record = RDP_CI_RELEASE_ATTESTATION_STORE.record_attestation(
            manifest,
            local_publication,
            external_proof,
            **attestation_fields,
            attested_by=user.username,
            archive_sha256=str(payload.get("archive_sha256") or ""),
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _rdp_ci_release_attestation_response(record)


@app.post("/api/research-os/rdp/manifests/{package_id}/ci_release_attestations/run")
def research_os_rdp_run_ci_release_attestation(
    package_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        manifest = RDP_STORE.manifest(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RDP package not found") from exc

    try:
        if contains_plaintext_secret(payload):
            raise ValueError("RDP CI release runner request cannot contain plaintext secret")
        local_publication = _rdp_publication_by_hash(package_id, str(payload.get("local_publish_hash") or ""))
        external_proof = _rdp_external_proof_by_hash(package_id, str(payload.get("external_proof_hash") or ""))
        trust_release_ref = str(payload.get("trust_release_ref") or local_publication.trust_release_ref or "").strip()
        trust_release_approval_ref = str(
            payload.get("trust_release_approval_ref") or local_publication.trust_release_approval_ref or ""
        ).strip()
        _rdp_validate_trust_release_refs(trust_release_ref, trust_release_approval_ref)
        runner_request = _rdp_ci_release_runner_request(
            manifest,
            local_publication,
            external_proof,
            payload=payload,
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
        )
        attestation_fields = _run_rdp_ci_release_runner(runner_request)
        record = RDP_CI_RELEASE_ATTESTATION_STORE.record_attestation(
            manifest,
            local_publication,
            external_proof,
            **attestation_fields,
            attested_by=user.username,
            archive_sha256=str(payload.get("archive_sha256") or local_publication.archive_sha256 or ""),
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
            has_user_waiver=bool(payload.get("has_user_waiver", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _rdp_ci_release_attestation_response(record)


@app.get("/api/research-os/rdp/publications")
def research_os_rdp_publications(user=Depends(require_user_dependency)) -> dict[str, Any]:
    records = RDP_PACKAGE_PUBLISH_STORE.publications()
    external_records = RDP_EXTERNAL_PUBLICATION_PROOF_STORE.proofs()
    ci_release_records = RDP_CI_RELEASE_ATTESTATION_STORE.attestations()
    return {
        "user": user.username,
        "total": len(records),
        "external_total": len(external_records),
        "ci_release_total": len(ci_release_records),
        "publications": [
            {
                "package_id": record.package_id,
                "channel": record.channel,
                "target_runtime": record.target_runtime,
                "archive_sha256": record.archive_sha256,
                "published_archive_path": record.published_archive_path,
                "publish_hash": record.publish_hash,
                "trust_release_ref": record.trust_release_ref,
                "trust_release_approval_ref": record.trust_release_approval_ref,
                "published_by": record.published_by,
                "published_at": record.published_at,
            }
            for record in records
        ],
        "external_publications": [
            {
                "package_id": record.package_id,
                "external_channel": record.external_channel,
                "target_runtime": record.target_runtime,
                "local_publish_hash": record.local_publish_hash,
                "archive_sha256": record.archive_sha256,
                "external_uri_digest": record.external_uri_digest,
                "immutable_pointer_ref": record.immutable_pointer_ref,
                "destination_allowlist_ref": record.destination_allowlist_ref,
                "trust_release_ref": record.trust_release_ref,
                "trust_release_approval_ref": record.trust_release_approval_ref,
                "evidence_refs": list(record.evidence_refs),
                "proof_hash": record.proof_hash,
                "attested_by": record.attested_by,
                "attested_at": record.attested_at,
            }
            for record in external_records
        ],
        "ci_release_attestations": [
            {
                "package_id": record.package_id,
                "target_runtime": record.target_runtime,
                "manifest_hash": record.manifest_hash,
                "local_publish_hash": record.local_publish_hash,
                "external_proof_hash": record.external_proof_hash,
                "archive_sha256": record.archive_sha256,
                "trust_release_ref": record.trust_release_ref,
                "trust_release_approval_ref": record.trust_release_approval_ref,
                "ci_system_ref": record.ci_system_ref,
                "ci_workflow_ref": record.ci_workflow_ref,
                "ci_run_ref": record.ci_run_ref,
                "source_commit_ref": record.source_commit_ref,
                "ci_status": record.ci_status,
                "artifact_digest": record.artifact_digest,
                "test_report_ref": record.test_report_ref,
                "test_report_hash": record.test_report_hash,
                "build_log_digest": record.build_log_digest,
                "required_check_refs": list(record.required_check_refs),
                "evidence_refs": list(record.evidence_refs),
                "attestation_hash": record.attestation_hash,
                "attested_by": record.attested_by,
                "attested_at": record.attested_at,
            }
            for record in ci_release_records
        ],
    }


def _document_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _source_intake_from_payload(payload: dict[str, Any]) -> SourceDocumentIntakeRecord:
    return SourceDocumentIntakeRecord(
        source_ref=str(payload.get("source_ref") or ""),
        quarantine_ref=payload.get("quarantine_ref"),
        parser_sandbox_ref=payload.get("parser_sandbox_ref"),
        mime_magic_check_ref=payload.get("mime_magic_check_ref"),
        source_hash=payload.get("source_hash"),
        license_rights_ref=payload.get("license_rights_ref"),
        no_network_parser=bool(payload.get("no_network_parser", False)),
        untrusted_data_boundary_ref=payload.get("untrusted_data_boundary_ref"),
    )


def _evidence_span_from_payload(payload: dict[str, Any]) -> EvidenceSpanRecord:
    page_value = payload.get("page")
    return EvidenceSpanRecord(
        span_ref=str(payload.get("span_ref") or ""),
        source_id=str(payload.get("source_id") or ""),
        doc_version_id=str(payload.get("doc_version_id") or ""),
        parser_run_id=str(payload.get("parser_run_id") or ""),
        block_id=str(payload.get("block_id") or ""),
        page=int(page_value) if page_value is not None else None,
        quoted_excerpt_hash=payload.get("quoted_excerpt_hash"),
        parser_confidence=float(payload.get("parser_confidence", 0.0)),
        span_support_verification_ref=payload.get("span_support_verification_ref"),
        verified=bool(payload.get("verified", False)),
    )


def _extracted_claim_from_payload(payload: dict[str, Any]) -> ExtractedResearchClaim:
    return ExtractedResearchClaim(
        claim_ref=str(payload.get("claim_ref") or ""),
        claim_kind=str(payload.get("claim_kind") or ""),
        evidence_span_refs=tuple(str(v) for v in payload.get("evidence_span_refs") or ()),
        confirmatory_use=bool(payload.get("confirmatory_use", False)),
    )


def _tool_request_from_payload(payload: dict[str, Any]) -> PrivilegedToolUseRequest:
    return PrivilegedToolUseRequest(
        request_ref=str(payload.get("request_ref") or ""),
        source_document_ref=str(payload.get("source_document_ref") or ""),
        direct_document_payload=bool(payload.get("direct_document_payload", False)),
        schema_constrained_artifact_ref=payload.get("schema_constrained_artifact_ref"),
    )


def _document_payload_bool(payload: dict[str, Any], name: str, *, default: bool) -> bool:
    value = payload.get(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    raise ValueError(f"{name} must be a boolean")


def _document_payload_tuple(value: Any, *, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return default
    if isinstance(value, (list, tuple, set)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _local_document_rag_permission(
    payload: dict[str, Any],
    *,
    username: str,
    desk: str,
    asset_ref: str,
) -> RAGPermission:
    if "permission" in payload:
        return _rag_permission_from_payload({"permission": payload.get("permission")}, username)
    return RAGPermission(
        allowed_users=(username,),
        allowed_desks=(desk,),
        allowed_assets=(asset_ref,),
        permission_tags=_document_payload_tuple(
            payload.get("permission_tags"),
            default=("research.read",),
        ),
    )


def _rag_documents_from_local_parse(
    parsed: LocalDocumentParseResult,
    payload: dict[str, Any],
    *,
    username: str,
) -> list[AssetRAGDocument]:
    if not _document_payload_bool(payload, "ingest_to_rag", default=True):
        return []
    desk = str(payload.get("desk") or "research")
    asset_ref = str(payload.get("asset_ref") or parsed.source.source_ref)
    projection = str(payload.get("projection") or RAGProjection.RESEARCH.value)
    permission = _local_document_rag_permission(payload, username=username, desk=desk, asset_ref=asset_ref)
    span_by_block = {span.block_id: span for span in parsed.spans}
    documents: list[AssetRAGDocument] = []
    for block in parsed.blocks:
        span = span_by_block[block.block_id]
        documents.append(
            AssetRAGDocument(
                source_id=span.span_ref,
                version=span.doc_version_id,
                title=f"{parsed.source_path} · {block.section or block.block_id}",
                body=block.text,
                projection=projection,
                asset_ref=asset_ref,
                permission=permission,
                applicability="candidate document evidence; not a system verdict",
                source_kind="EvidenceSpan",
                metadata={
                    "source_ref": parsed.source.source_ref,
                    "source_hash": parsed.source.source_hash,
                    "doc_version_id": parsed.doc_version_id,
                    "parser_run_id": parsed.parser_run_id,
                    "block_id": block.block_id,
                    "page": block.page,
                    "section": block.section,
                    "char_span": [block.char_start, block.char_end],
                    "layout_bbox": list(block.layout_bbox) if block.layout_bbox else None,
                    "layout_block_index": block.layout_block_index,
                    "layout_kind": block.layout_kind,
                    "quoted_excerpt_hash": block.quoted_excerpt_hash,
                    "span_support_verification_ref": span.span_support_verification_ref,
                    "source_path": parsed.source_path,
                    "source_url": parsed.source_url,
                },
                evidence_label="candidate_context",
                methodology_path="document_intelligence_local_parse",
            )
        )
    return documents


def _parse_local_document_for_rag(
    payload: dict[str, Any],
    *,
    username: str,
    root: Path | None = None,
) -> tuple[LocalDocumentParseResult, list[AssetRAGDocument]]:
    parsed = parse_local_document(
        str(payload.get("source_path") or ""),
        root=root or PROJECT_ROOT,
        source_ref=payload.get("source_ref"),
        source_url=payload.get("source_url"),
        allowed_url_hosts=_document_payload_tuple(payload.get("allowed_url_hosts")),
        license_rights_ref=payload.get("license_rights_ref"),
        max_bytes=int(payload.get("max_bytes") or 1_000_000),
        max_pages=int(payload.get("max_pages") or 100),
    )
    return parsed, _rag_documents_from_local_parse(parsed, payload, username=username)


def _local_batch_item_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("items must be a non-empty list")
    defaults = {
        key: payload.get(key)
        for key in (
            "allowed_url_hosts",
            "asset_ref",
            "desk",
            "ingest_to_rag",
            "license_rights_ref",
            "max_bytes",
            "max_pages",
            "permission",
            "permission_tags",
            "projection",
        )
        if key in payload
    }
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"items[{index}] must be an object")
        item = {**defaults, **raw}
        source_path = str(item.get("source_path") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        key = (source_path, source_url)
        if key in seen:
            raise ValueError("items contains duplicate source_path/source_url")
        seen.add(key)
        items.append(item)
    return items


_DOCUMENT_UPLOAD_ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".pdf", ".html", ".htm"}
_DOCUMENT_SYNC_ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".pdf"}
_DOCUMENT_UPLOAD_SENSITIVE_STEMS = {
    "credential",
    "credentials",
    "secret",
    "secrets",
    "token",
    "tokens",
}
_DOCUMENT_SYNC_SENSITIVE_NAMES = _DOCUMENT_UPLOAD_SENSITIVE_STEMS | {
    ".env",
    ".env.local",
    "id_ed25519",
    "id_rsa",
}
_DOCUMENT_SYNC_SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


def _document_upload_safe_filename(filename: str | None) -> str:
    raw = str(filename or "").strip()
    if not raw:
        raise ValueError("uploaded document filename is required")
    if "\x00" in raw or "/" in raw or "\\" in raw:
        raise ValueError("uploaded document filename must not contain path separators")
    path = Path(raw)
    suffix = path.suffix.lower()
    if suffix not in _DOCUMENT_UPLOAD_ALLOWED_SUFFIXES:
        raise ValueError("uploaded document parser supports only text/Markdown/PDF/HTML sources")
    stem = path.stem.strip()
    if not stem or stem.startswith(".") or stem.lower() in _DOCUMENT_UPLOAD_SENSITIVE_STEMS:
        raise ValueError("uploaded document filename is hidden or sensitive")
    safe_stem = "".join(ch if ch.isascii() and (ch.isalnum() or ch in ("-", "_", ".")) else "_" for ch in stem)
    safe_stem = safe_stem.strip("._-") or "document"
    return f"{safe_stem[:80]}{suffix}"


async def _read_upload_bytes(upload: UploadFile, *, max_bytes: int) -> bytes:
    safe_max = max(1, min(int(max_bytes or 1_000_000), 5_000_000))
    raw = await upload.read(safe_max + 1)
    if not raw:
        raise ValueError("uploaded document is empty")
    if len(raw) > safe_max:
        raise ValueError("uploaded document exceeds parser size limit")
    return raw


def _store_uploaded_document(upload: UploadFile, raw: bytes) -> tuple[str, Path, bool]:
    filename = _document_upload_safe_filename(upload.filename)
    digest = hashlib.sha256(raw).hexdigest()
    relative_path = Path("document_uploads") / digest[:16] / filename
    root = DATA_ROOT.resolve()
    target = (root / relative_path).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("uploaded document storage path escapes data root") from exc
    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not existed:
        target.write_bytes(raw)
    return relative_path.as_posix(), target, existed


def _cleanup_failed_upload(target: Path, *, existed: bool) -> None:
    if existed:
        return
    try:
        target.unlink(missing_ok=True)
        if not any(target.parent.iterdir()):
            target.parent.rmdir()
    except OSError:
        return


def _document_form_list(value: str | None) -> tuple[str, ...]:
    raw = str(value or "")
    return tuple(part.strip() for part in re.split(r"[\n,]", raw) if part.strip())


def _document_sync_root(root_name: str | None) -> Path:
    name = str(root_name or "project").strip().lower()
    if name == "project":
        return PROJECT_ROOT
    if name == "data":
        return DATA_ROOT
    raise ValueError("root must be 'project' or 'data'")


def _document_path_has_sensitive_part(path: Path) -> bool:
    for part in path.parts:
        lower = part.lower()
        if lower.startswith(".") or lower in _DOCUMENT_SYNC_SENSITIVE_NAMES:
            return True
        if Path(lower).suffix in _DOCUMENT_SYNC_SENSITIVE_SUFFIXES:
            return True
    return False


def _safe_document_sync_base(root: Path, base_path: str) -> Path:
    raw = str(base_path or "").strip()
    if not raw:
        raise ValueError("base_path is required")
    if "\x00" in raw:
        raise ValueError("base_path contains NUL byte")
    requested = Path(raw)
    if requested.is_absolute():
        raise ValueError("base_path must be relative")
    if any(part in ("..", "") for part in requested.parts):
        raise ValueError("base_path must not contain path traversal")
    if _document_path_has_sensitive_part(requested):
        raise ValueError("base_path points at a hidden or sensitive path")
    root_path = root.resolve()
    candidate = root_path / requested
    current = candidate
    while True:
        if current.exists() and current.is_symlink():
            raise ValueError("base_path must not traverse symlinks")
        if current == root_path:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("base_path escapes root") from exc
    if not resolved.exists():
        raise ValueError("base_path does not exist")
    if not resolved.is_dir():
        raise ValueError("base_path must point to a directory")
    return resolved


def _document_sync_file_paths(root: Path, base_path: str, *, max_files: int) -> tuple[list[str], list[str]]:
    root_path = root.resolve()
    base = _safe_document_sync_base(root_path, base_path)
    safe_max = max(1, min(int(max_files or 100), 100))
    files: list[str] = []
    skipped: list[str] = []
    for child in sorted(base.rglob("*")):
        if child.is_symlink():
            raise ValueError("sync directory contains a symlink")
        relative = child.resolve(strict=False).relative_to(root_path)
        if _document_path_has_sensitive_part(relative):
            raise ValueError("sync directory contains a hidden or sensitive path")
        if not child.is_file():
            continue
        rel_text = relative.as_posix()
        if child.suffix.lower() in _DOCUMENT_SYNC_ALLOWED_SUFFIXES:
            files.append(rel_text)
            if len(files) > safe_max:
                raise ValueError("sync directory exceeds max_files")
        else:
            skipped.append(rel_text)
    if not files:
        raise ValueError("sync directory contains no supported documents")
    return files, skipped


@app.post("/api/research-os/documents/parse_local")
def document_intelligence_parse_local_document(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Parse a safe local UTF-8 text/Markdown document into evidence spans.

    Raw document content is not returned. When `ingest_to_rag` is true, each
    parsed block is indexed as ResearchRAG candidate context and still obeys the
    RAG permission and secret-boundary guards.
    """

    try:
        parsed, rag_documents = _parse_local_document_for_rag(payload, username=user.username)

        source = DOCUMENT_INTELLIGENCE_STORE.record_source(parsed.source)
        spans = [DOCUMENT_INTELLIGENCE_STORE.record_span(span) for span in parsed.spans]
        for document in rag_documents:
            RESEARCH_ASSET_RAG_INDEX.add(document)
        return {
            "source_ref": source.source_ref,
            "source_path": parsed.source_path,
            "source_url": parsed.source_url,
            "source_hash": source.source_hash,
            "doc_version_id": parsed.doc_version_id,
            "parser_run_id": parsed.parser_run_id,
            "mime_magic_check_ref": parsed.mime_magic_check_ref,
            "span_refs": [span.span_ref for span in spans],
            "rag_document_ids": [document.document_id for document in rag_documents],
            "rag_source_ids": [document.source_id for document in rag_documents],
            "blocks": [
                {
                    "block_id": block.block_id,
                    "page": block.page,
                    "section": block.section,
                    "char_start": block.char_start,
                    "char_end": block.char_end,
                    "layout_bbox": list(block.layout_bbox) if block.layout_bbox else None,
                    "layout_block_index": block.layout_block_index,
                    "layout_kind": block.layout_kind,
                    "quoted_excerpt_hash": block.quoted_excerpt_hash,
                }
                for block in parsed.blocks
            ],
            "recorded_by": user.username,
        }
    except HTTPException:
        raise
    except (AssetRAGError, ValueError) as exc:
        raise _document_error(exc) from exc


@app.post("/api/research-os/documents/parse_upload")
async def document_intelligence_parse_uploaded_document(
    file: UploadFile = File(...),
    license_rights_ref: str = Form(...),
    asset_ref: str = Form(""),
    desk: str = Form("research"),
    permission_tags: str = Form("research.read"),
    source_url: str = Form(""),
    allowed_url_hosts: str = Form(""),
    ingest_to_rag: bool = Form(True),
    projection: str = Form(RAGProjection.RESEARCH.value),
    max_bytes: int = Form(1_000_000),
    max_pages: int = Form(100),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Parse an uploaded document through the same no-network parser/RAG guards.

    The raw upload is quarantined under DATA_ROOT/document_uploads only after
    filename and size checks. If parser or RAG guards reject it, the quarantine
    file is removed and no Document/RAG records are written.
    """

    target: Path | None = None
    existed = False
    try:
        raw = await _read_upload_bytes(file, max_bytes=max_bytes)
        source_path, target, existed = _store_uploaded_document(file, raw)
        payload = {
            "source_path": source_path,
            "source_url": source_url.strip() or None,
            "allowed_url_hosts": _document_form_list(allowed_url_hosts),
            "license_rights_ref": license_rights_ref,
            "asset_ref": asset_ref.strip() or None,
            "desk": desk.strip() or "research",
            "permission_tags": _document_form_list(permission_tags) or ("research.read",),
            "ingest_to_rag": ingest_to_rag,
            "projection": projection,
            "max_bytes": max_bytes,
            "max_pages": max_pages,
        }
        parsed, rag_documents = _parse_local_document_for_rag(payload, username=user.username, root=DATA_ROOT)

        source = DOCUMENT_INTELLIGENCE_STORE.record_source(parsed.source)
        spans = [DOCUMENT_INTELLIGENCE_STORE.record_span(span) for span in parsed.spans]
        for document in rag_documents:
            RESEARCH_ASSET_RAG_INDEX.add(document)
        upload_ref = "document_upload:" + content_hash(
            {"source_path": parsed.source_path, "source_hash": source.source_hash}
        )
        return {
            "upload_ref": upload_ref,
            "source_ref": source.source_ref,
            "source_path": parsed.source_path,
            "source_url": parsed.source_url,
            "source_hash": source.source_hash,
            "doc_version_id": parsed.doc_version_id,
            "parser_run_id": parsed.parser_run_id,
            "mime_magic_check_ref": parsed.mime_magic_check_ref,
            "span_refs": [span.span_ref for span in spans],
            "rag_document_ids": [document.document_id for document in rag_documents],
            "rag_source_ids": [document.source_id for document in rag_documents],
            "recorded_by": user.username,
        }
    except HTTPException:
        if target is not None:
            _cleanup_failed_upload(target, existed=existed)
        raise
    except (AssetRAGError, ValueError) as exc:
        if target is not None:
            _cleanup_failed_upload(target, existed=existed)
        raise _document_error(exc) from exc
    finally:
        await file.close()


@app.post("/api/research-os/documents/sync_local_directory")
def document_intelligence_sync_local_directory(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Atomically sync supported documents from an explicit safe local directory."""

    try:
        asset_ref = str(payload.get("asset_ref") or "").strip()
        if not asset_ref:
            raise ValueError("asset_ref is required for directory sync")
        root = _document_sync_root(payload.get("root"))
        source_paths, skipped_paths = _document_sync_file_paths(
            root,
            str(payload.get("base_path") or ""),
            max_files=int(payload.get("max_files") or 100),
        )
        defaults = {
            "asset_ref": asset_ref,
            "desk": payload.get("desk") or "research",
            "ingest_to_rag": _document_payload_bool(payload, "ingest_to_rag", default=True),
            "license_rights_ref": payload.get("license_rights_ref"),
            "max_bytes": payload.get("max_bytes") or 1_000_000,
            "max_pages": payload.get("max_pages") or 100,
            "permission": payload.get("permission"),
            "permission_tags": payload.get("permission_tags") or ["research.read"],
            "projection": payload.get("projection") or RAGProjection.RESEARCH.value,
        }
        prepared = [
            _parse_local_document_for_rag({**defaults, "source_path": source_path}, username=user.username, root=root)
            for source_path in source_paths
        ]
        sources: list[dict[str, Any]] = []
        total_spans = 0
        total_rag_documents = 0
        for parsed, rag_documents in prepared:
            source = DOCUMENT_INTELLIGENCE_STORE.record_source(parsed.source)
            spans = [DOCUMENT_INTELLIGENCE_STORE.record_span(span) for span in parsed.spans]
            for document in rag_documents:
                RESEARCH_ASSET_RAG_INDEX.add(document)
            total_spans += len(spans)
            total_rag_documents += len(rag_documents)
            sources.append(
                {
                    "source_ref": source.source_ref,
                    "source_path": parsed.source_path,
                    "source_hash": source.source_hash,
                    "doc_version_id": parsed.doc_version_id,
                    "parser_run_id": parsed.parser_run_id,
                    "mime_magic_check_ref": parsed.mime_magic_check_ref,
                    "span_refs": [span.span_ref for span in spans],
                    "rag_document_ids": [document.document_id for document in rag_documents],
                    "rag_source_ids": [document.source_id for document in rag_documents],
                }
            )
        return {
            "root": str(payload.get("root") or "project"),
            "base_path": str(payload.get("base_path") or ""),
            "parsed_count": len(sources),
            "span_count": total_spans,
            "rag_document_count": total_rag_documents,
            "skipped_paths": skipped_paths,
            "sources": sources,
            "recorded_by": user.username,
        }
    except HTTPException:
        raise
    except (AssetRAGError, ValueError) as exc:
        raise _document_error(exc) from exc


@app.post("/api/research-os/documents/parse_local_batch")
def document_intelligence_parse_local_batch(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Atomically parse an explicit list of local document snapshots into RAG."""

    try:
        prepared = [
            _parse_local_document_for_rag(item, username=user.username)
            for item in _local_batch_item_payloads(payload)
        ]
        sources: list[dict[str, Any]] = []
        total_spans = 0
        total_rag_documents = 0
        for parsed, rag_documents in prepared:
            source = DOCUMENT_INTELLIGENCE_STORE.record_source(parsed.source)
            spans = [DOCUMENT_INTELLIGENCE_STORE.record_span(span) for span in parsed.spans]
            for document in rag_documents:
                RESEARCH_ASSET_RAG_INDEX.add(document)
            total_spans += len(spans)
            total_rag_documents += len(rag_documents)
            sources.append(
                {
                    "source_ref": source.source_ref,
                    "source_path": parsed.source_path,
                    "source_url": parsed.source_url,
                    "source_hash": source.source_hash,
                    "doc_version_id": parsed.doc_version_id,
                    "parser_run_id": parsed.parser_run_id,
                    "mime_magic_check_ref": parsed.mime_magic_check_ref,
                    "span_refs": [span.span_ref for span in spans],
                    "rag_document_ids": [document.document_id for document in rag_documents],
                    "rag_source_ids": [document.source_id for document in rag_documents],
                }
            )
        return {
            "parsed_count": len(sources),
            "span_count": total_spans,
            "rag_document_count": total_rag_documents,
            "sources": sources,
            "recorded_by": user.username,
        }
    except HTTPException:
        raise
    except (AssetRAGError, ValueError) as exc:
        raise _document_error(exc) from exc


@app.post("/api/research-os/documents/sources")
def document_intelligence_record_source(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Record safe source intake metadata.

    Raw document bytes are not accepted here; this endpoint records only the
    sandbox/hash/rights boundary refs required before parsing.
    """

    try:
        source = DOCUMENT_INTELLIGENCE_STORE.record_source(_source_intake_from_payload(payload))
        return {"source_ref": source.source_ref, "recorded_by": user.username}
    except ValueError as exc:
        raise _document_error(exc) from exc


@app.post("/api/research-os/documents/evidence_spans")
def document_intelligence_record_span(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        span = DOCUMENT_INTELLIGENCE_STORE.record_span(_evidence_span_from_payload(payload))
        return {"span_ref": span.span_ref, "source_id": span.source_id, "recorded_by": user.username}
    except ValueError as exc:
        raise _document_error(exc) from exc


@app.post("/api/research-os/documents/extracted_claims")
def document_intelligence_record_claim(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        claim = DOCUMENT_INTELLIGENCE_STORE.record_claim(_extracted_claim_from_payload(payload))
        return {"claim_ref": claim.claim_ref, "claim_kind": claim.claim_kind, "recorded_by": user.username}
    except ValueError as exc:
        raise _document_error(exc) from exc


@app.post("/api/research-os/documents/tool_requests")
def document_intelligence_record_tool_request(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        request = DOCUMENT_INTELLIGENCE_STORE.record_tool_request(_tool_request_from_payload(payload))
        return {
            "request_ref": request.request_ref,
            "source_document_ref": request.source_document_ref,
            "recorded_by": user.username,
        }
    except ValueError as exc:
        raise _document_error(exc) from exc


@app.get("/api/research-os/documents/summary")
def document_intelligence_summary(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return {
        "user": user.username,
        "sources": [source.__dict__ for source in DOCUMENT_INTELLIGENCE_STORE.sources()],
        "spans": [span.__dict__ for span in DOCUMENT_INTELLIGENCE_STORE.spans()],
        "claims": [claim.__dict__ for claim in DOCUMENT_INTELLIGENCE_STORE.claims()],
        "tool_requests": [request.__dict__ for request in DOCUMENT_INTELLIGENCE_STORE.tool_requests()],
    }


@app.post("/api/research-os/rag/documents")
def research_asset_rag_add_document(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Persist a Research Asset RAG document without weakening secret or permission rules."""

    doc = _rag_document_from_payload(payload, user.username)
    RESEARCH_ASSET_RAG_INDEX.add(doc)
    return {
        "document_id": doc.document_id,
        "source_id": doc.source_id,
        "version": doc.version,
        "projection": doc.projection_value,
        "asset_ref": doc.asset_ref,
    }


@app.post("/api/research-os/rag/retrieve")
def research_asset_rag_retrieve(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Retrieve candidate context from Research Asset RAG.

    Actor mode `agent` records source/version usage for user inspection. Hits
    remain candidate context and do not become verdicts.
    """

    try:
        context = RAGQueryContext(
            user_id=user.username,
            desk=str(payload.get("desk") or ""),
            visible_asset_refs=tuple(str(v) for v in payload.get("visible_asset_refs") or ()),
            permission_tags=tuple(str(v) for v in payload.get("permission_tags") or ()),
            actor=str(payload.get("actor") or "user"),
        )
        projections = tuple(str(v) for v in payload.get("projections") or ())
        hits = RESEARCH_ASSET_RAG_INDEX.retrieve(
            str(payload.get("query") or ""),
            context=context,
            projections=projections,
            top_k=int(payload.get("top_k") or 5),
        )
        usage_ids: list[str] = []
        if context.actor == "agent" and hits:
            agent_id = str(payload.get("agent_id") or "")
            purpose = str(payload.get("purpose") or "")
            for hit in hits:
                usage_ids.append(
                    RESEARCH_ASSET_RAG_INDEX.record_agent_usage(
                        agent_id=agent_id,
                        hit=hit,
                        purpose=purpose,
                        user_id=user.username,
                    ).usage_id
                )
        return {
            "hits": [_rag_hit_to_dict(hit) for hit in hits],
            "agent_usage_ids": usage_ids,
        }
    except (AssetRAGError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/rag/vector_search")
def research_asset_rag_vector_search(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Search RAG documents with deterministic sparse token vectors.

    This is a backend vector-search seam, not a dense embedding provider or a
    verdict generator. Actor mode `agent` records the same source/version usage
    ledger as lexical retrieval.
    """

    try:
        context = RAGQueryContext(
            user_id=user.username,
            desk=str(payload.get("desk") or ""),
            visible_asset_refs=tuple(str(v) for v in payload.get("visible_asset_refs") or ()),
            permission_tags=tuple(str(v) for v in payload.get("permission_tags") or ()),
            actor=str(payload.get("actor") or "user"),
        )
        projections = tuple(str(v) for v in payload.get("projections") or ())
        hits = RESEARCH_ASSET_RAG_INDEX.vector_search(
            str(payload.get("query") or ""),
            context=context,
            projections=projections,
            top_k=int(payload.get("top_k") or 5),
        )
        usage_ids: list[str] = []
        if context.actor == "agent" and hits:
            agent_id = str(payload.get("agent_id") or "")
            purpose = str(payload.get("purpose") or "")
            for hit in hits:
                usage_ids.append(
                    RESEARCH_ASSET_RAG_INDEX.record_agent_usage(
                        agent_id=agent_id,
                        hit=hit,
                        purpose=purpose,
                        user_id=user.username,
                    ).usage_id
                )
        return {
            "hits": [_rag_hit_to_dict(hit) for hit in hits],
            "agent_usage_ids": usage_ids,
        }
    except (AssetRAGError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research-os/rag/dense_vector_search")
def research_asset_rag_dense_vector_search(
    payload: dict = Body(...),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Search RAG documents with the local dense embedding index.

    The embedding model is deterministic and local (`local_hash_dense_v1`).
    It is not an external embedding provider or a production vector database.
    Actor mode `agent` records source/version usage for the same audit trail.
    """

    try:
        context = RAGQueryContext(
            user_id=user.username,
            desk=str(payload.get("desk") or ""),
            visible_asset_refs=tuple(str(v) for v in payload.get("visible_asset_refs") or ()),
            permission_tags=tuple(str(v) for v in payload.get("permission_tags") or ()),
            actor=str(payload.get("actor") or "user"),
        )
        projections = tuple(str(v) for v in payload.get("projections") or ())
        hits = RESEARCH_ASSET_RAG_INDEX.dense_vector_search(
            str(payload.get("query") or ""),
            context=context,
            projections=projections,
            top_k=int(payload.get("top_k") or 5),
        )
        usage_ids: list[str] = []
        if context.actor == "agent" and hits:
            agent_id = str(payload.get("agent_id") or "")
            purpose = str(payload.get("purpose") or "")
            for hit in hits:
                usage_ids.append(
                    RESEARCH_ASSET_RAG_INDEX.record_agent_usage(
                        agent_id=agent_id,
                        hit=hit,
                        purpose=purpose,
                        user_id=user.username,
                    ).usage_id
                )
        return {
            "embedding_model_ref": DENSE_EMBEDDING_MODEL_REF,
            "hits": [_rag_hit_to_dict(hit) for hit in hits],
            "agent_usage_ids": usage_ids,
        }
    except (AssetRAGError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/research-os/rag/agent_usage")
def research_asset_rag_agent_usage(
    source_id: str | None = Query(None),
    asset_ref: str | None = Query(None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """Inspect Agent RAG citations by source or asset.

    The underlying hit was already permission-filtered at retrieval time; this
    view exposes usage provenance, not document bodies or secrets.
    """

    usage = RESEARCH_ASSET_RAG_INDEX.agent_usage(source_id=source_id, asset_ref=asset_ref, user_id=user.username)
    return {"usage": [u.__dict__ for u in usage]}


@app.post("/api/strategy_goals")
def strategy_goal_create_api(
    payload: dict = Body(...),
    current=Depends(current_user_dependency),
) -> dict[str, Any]:
    """M1 / GOAL §1: direct API entrypoint for Quant Intent -> StrategyGoal.

    This path uses the same StrategyGoalStore as Agent Shell. Successful creates
    also write a QuantIntent QRO into the Research Graph. Invalid or underspecified
    requests return 422 and do not fabricate business QROs.
    """

    actor = getattr(current, "user_id", None) or "api_user"
    result = _create_strategy_goal_with_compiler_coverage(
        payload,
        entry_source="api",
        actor_source="user_manual",
        actor=str(actor),
        owner="strategy_goal_store",
    )
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result)
    return result


@app.get("/api/strategy_goals")
def strategy_goal_list_api() -> dict[str, Any]:
    return {"strategy_goal_ids": STRATEGY_GOAL_STORE.list_ids()}


@app.get("/api/strategy_goals/{goal_id}")
def strategy_goal_get_api(goal_id: str) -> dict[str, Any]:
    try:
        goal = STRATEGY_GOAL_STORE.get(goal_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=goal_id) from exc
    return {"strategy_goal_id": goal_id, "goal": goal.model_dump(mode="json")}


@app.get("/api/agent/tools")
def agent_tools() -> dict[str, Any]:
    # T-028：诚实暴露每个 schema 工具的真实可用状态（live/stub/unwired）+ 副作用级别——
    # 打击「能力名不副实」（schema 声明 N 个、实际只接通部分），符合 R25「弱点一等呈现」。
    rt = _agent_runtime()
    registered = set(rt._tools.keys())
    stub = {"factor.run_ic"}  # 已注册但未接入真实引擎（仅返回 queued）
    tool_status = []
    for fn in TOOL_SCHEMA:
        name = fn.get("name") or fn.get("function", {}).get("name", "")
        status = "unwired" if name not in registered else ("stub" if name in stub else "live")
        tool_status.append({"name": name, "status": status, "side_effect": rt._side_effects.get(name, "none")})
    return {"functions": TOOL_SCHEMA, "llm_provider": AGENT_LLM.provider, "tool_status": tool_status}


@app.post("/api/agent/chat")
def agent_chat(payload: dict = Body(...), current=Depends(current_user_dependency)) -> dict[str, Any]:
    user_input = str(payload.get("message", "")).strip()
    if not user_input:
        raise HTTPException(400, "message 不能为空")
    runtime = _agent_runtime(rag_context_provider=_agent_shell_rag_context_provider(payload, current))
    try:
        turn = runtime.run(user_input)
    except AssetRAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        coverage_refs = _record_agent_turn_goal_entrypoint_coverage(
            turn,
            endpoint_ref="api.agent.chat",
            actor="agent_runtime",
            permission_mode="auto",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "final_message": turn.final_message,
        "succeeded": turn.succeeded,
        "steps": [s.to_dict() for s in turn.steps],
        "qro_ids": turn.qro_ids,
        "research_graph_command_ids": turn.research_graph_command_ids,
        "compiler_ir_refs": coverage_refs["compiler_ir_refs"],
        "compiler_pass_refs": coverage_refs["compiler_pass_refs"],
        "entrypoint_coverage_refs": coverage_refs["entrypoint_coverage_refs"],
        "rag_hits": turn.rag_hits,
        "rag_usage_ids": turn.rag_usage_ids,
    }


@app.post("/api/agent/slot_fill")
def agent_slot_fill(payload: dict = Body(...)) -> dict[str, Any]:
    text = str(payload.get("text", ""))
    name = payload.get("name")
    goal = AGENT_SLOT_FILLER.fill(text, name=name)
    return goal.model_dump(mode="json")


@app.post("/api/agent/replicate")
def agent_replicate(payload: dict = Body(...)) -> dict[str, Any]:
    dialect = payload.get("source_dialect", "pandas")
    code = payload.get("code", "")
    report = CODE_REPLICATOR.replicate(code, dialect=dialect)
    return {"dialect": report.dialect, "target_code": report.target_code, "notes": report.notes}


# A4 · agent 工作台结构化 SSE：把 AgentRuntime 的 turn 投影成前端 7 种 block 事件
# （tool 开始/结束 · gate 挂起 · thinking · 里程碑 · say · done）。投影纯逻辑在
# agent.workbench_stream.project_turn_events（可单测 scripted runtime 的事件序列）。
# 治理：gate 挂起严格走 permission_gate（realmoney 恒 confirm，含 bypass——权限轴 ⟂ 治理轴 D-PERM）；
# tool 的 side_effect 取自 runtime 真值（前端不伪造）。


@app.get("/api/agent/workbench/stream")
def agent_workbench_stream(
    q: str = Query(..., description="user message"),
    permission_mode: str = Query("ask"),
    desk: str = Query("research"),
    visible_asset_refs: list[str] | None = Query(None),
    permission_tags: list[str] | None = Query(None),
    projections: list[str] | None = Query(None),
    rag_search: str = Query("vector"),
    rag_top_k: int = Query(5, ge=1, le=10),
    current=Depends(current_user_dependency),
):
    """SSE：策略台 agent 工作台真流。把 turn 投影成结构化 block 事件（替代前端 mock 剧本）。

    事件类型（event:）：
      user / thinking / say / tool_start / tool_end / gate / milestone / done / error
    gate 挂起：permission_gate(mode, side_effect)=="confirm" → 发 gate 事件并停（不自动执行）。
    realmoney 恒 confirm（含 bypass）；动钱/晋级工具根本未注册给 agent（纵深防御）。
    """

    user_text = (q or "").strip()
    mode = str(permission_mode or "ask")
    rag_payload = {
        "desk": desk,
        "visible_asset_refs": visible_asset_refs or (),
        "permission_tags": permission_tags or (),
        "projections": projections or (),
        "rag_search": rag_search,
        "rag_top_k": rag_top_k,
        "agent_id": f"agent-workbench:{desk}",
        "rag_purpose": "agent_workbench_stream_context",
    }

    def event_stream():
        from .agent.workbench_stream import project_turn_events, sse_format

        if not user_text:
            yield sse_format("error", {"error": "empty content"})
            return
        yield sse_format("user", {"text": user_text})

        runtime = _agent_runtime(
            permission_mode=mode,
            rag_context_provider=_agent_shell_rag_context_provider(rag_payload, current),
        )
        try:
            turn = runtime.run(user_text)
        except Exception as exc:  # noqa: BLE001
            yield sse_format("error", {"error": f"{type(exc).__name__}: {exc}"})
            return
        try:
            coverage_refs = _record_agent_turn_goal_entrypoint_coverage(
                turn,
                endpoint_ref="agent.workbench.stream",
                actor="agent_runtime",
                permission_mode=mode,
            )
        except ValueError as exc:
            yield sse_format("error", {"error": str(exc)})
            return

        for ev in project_turn_events(turn, side_effects=runtime._side_effects, permission_mode=mode):  # noqa: SLF001
            yield sse_format(ev["event"], ev["data"])

        yield sse_format(
            "done",
            {
                "final_message": turn.final_message,
                "succeeded": turn.succeeded,
                "qro_ids": turn.qro_ids,
                "research_graph_command_ids": turn.research_graph_command_ids,
                "compiler_ir_refs": coverage_refs["compiler_ir_refs"],
                "compiler_pass_refs": coverage_refs["compiler_pass_refs"],
                "entrypoint_coverage_refs": coverage_refs["entrypoint_coverage_refs"],
                "rag_hits": turn.rag_hits,
                "rag_usage_ids": turn.rag_usage_ids,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/strategy/submit_candidate")
def strategy_submit_candidate(
    payload: dict = Body(...), user=Depends(require_user_dependency)
) -> dict[str, Any]:
    """A4 handoff：把候选策略提交进【模拟台候选池】——止于模拟盘，绝不导向直接实盘。

    治理红线（D-PERM 不跳级 / R8）：
      · destination 钉死 paper_desk；任何 live/mainnet/realmoney 目的地 → 422（直推实盘=跳级，硬拒）。
      · 本端点只登记候选意图，不下单、不动钱；进场/监控/动钱由模拟台与实盘安全阶梯决定。
    """

    run_id = (payload.get("run_id") or "").strip()
    name = (payload.get("name") or run_id or "candidate").strip()
    destination = payload.get("destination", "paper_desk")
    try:
        record = CANDIDATE_POOL.submit(
            run_id=run_id,
            name=name,
            created_by=user.user_id,
            destination=destination,
            factor_set=payload.get("factor_set"),
            model_id=payload.get("model_id"),
            note=payload.get("note", ""),
        )
    except _HandoffRejected as exc:
        raise HTTPException(status_code=422, detail={"rejected": True, "reason": str(exc)}) from exc
    # 候选过裁决 → 注册成模拟台可跑 run（止于 paper；A股恒拒 live、不绕审批门）。
    # 失败不回滚候选登记（候选已 append-only 落库）；模拟台注册是派生动作，独立容错。
    paper = _register_candidate_paper_run(record, payload, creator=user.user_id)
    # H4：注册派生失败带显式 error（前端可显「候选已提交但模拟台注册失败：<原因>」），不静默假成功。
    out: dict[str, Any] = {**record, "paper_run": paper}
    if paper is not None and paper.get("error"):
        out["paper_run_error"] = paper["error"]
    # GOAL §9 advisory（只记录不强制）：candidate = 新策略 admit。把 factor_set 里可解析到
    # FACTOR_REGISTRY 的因子当「默认采用」，跑 validate_strategy_book 的「退役因子被新策略默认采用 → 拒」
    # 这条可证伪验收；违例**不拒候选**（候选仍登记、仍止于 paper）。覆盖见 helper docstring（含 KNOWN_RUN_GAP）。
    out["boundary_verdict"] = _strategy_candidate_boundary_verdict(payload, record.get("candidate_id", ""))
    return out


# H3 市场派生：market/asset_class 显式信号映射到 paper 市场枚举（"equity_cn"/"crypto"）。
# 绝不默认 A股、绝不凭空造标的——无法判定就返 None（unknown），由调用方标 error 不注册伪造 run。
_VALID_PAPER_MARKETS = ("equity_cn", "crypto")


# asset_class → 市场关键词。equity_cn 先判（其 token 更专指）：避免 "equity_cn_spot" 被宽 token
# "spot" 抢成 crypto。crypto token 去掉非专指的 "spot"（现货也存在于股票/FX，非 crypto 独有）。
_EQUITY_CN_TOKENS = ("a_share", "ashare", "equity_cn", "stock", "ashr")
_CRYPTO_TOKENS = ("crypto", "perp", "usdt", "usdc", "btc", "eth", "binance")


def _derive_candidate_market(payload: dict) -> str | None:
    """从 payload 的 market / asset_class 显式信号派生 paper 市场枚举；判不出返 None（unknown）。

    candidate 源自 goal/run，本应知其市场——传 market（equity_cn/crypto，大小写不敏感）或 asset_class
    （a_share/equity_cn/stock… → equity_cn；crypto/perp/usdt/btc… → crypto）。两者皆无/不识别 → None。
    绝不默认 equity_cn（H3：crypto 候选不可被静默注册成 A股 + 伪造 600519；A股 spot 亦不可误判成 crypto）。
    """

    market = payload.get("market")
    if isinstance(market, str) and market.strip().casefold() in _VALID_PAPER_MARKETS:
        return market.strip().casefold()
    asset_class = payload.get("asset_class")
    if isinstance(asset_class, str) and asset_class.strip():
        ac = asset_class.strip().casefold()
        # equity_cn 先判（token 更专指）→ 再 crypto；末尾才用宽 "cn"（避免误吃含 cn 的 crypto 串）。
        if any(t in ac for t in _EQUITY_CN_TOKENS):
            return "equity_cn"
        if any(t in ac for t in _CRYPTO_TOKENS):
            return "crypto"
        if "cn" in ac:  # 宽兜底（如 "cn_daily"）——放最后，前面专指 token 都没命中才用。
            return "equity_cn"
    return None


def _register_candidate_paper_run(
    record: dict[str, Any], payload: dict, *, creator: str
) -> dict[str, Any] | None:
    """把过裁决候选注册进模拟台并喂模拟 bars 跑出真净值（idempotent；A股恒 paper）。

    治理：register_run 只建模拟台 run，绝不绕审批/动钱/live 下单（A股 attempt_live_order 仍恒拒）。
    provider 数据源按市场分流【crypto 真捆样本回放 bundled_sample_replay / 无样本市场合成兜底
    deterministic_sim_walk】，均为模拟非实盘 key。

    返回（永不返 None，让 H4 端点显式透传失败原因）：
      · 成功：{"registered": True, "run_id", "market", "symbols", **primed}
      · 失败：{"registered": False, "run_id", "error": <可读原因>}——含市场判不出（H3 unknown）/
        二次注册市场/标的不符（M3 reconcile 冲突）/ register/prime 异常。
    """

    run_id = record["run_id"]
    # 已注册？取既有 run 以便：① 缺显式市场时复用其市场（不凭空猜）② M3 reconcile 二次注册不符。
    existing = None
    try:
        existing = PAPER_DESK.get(run_id)
    except PaperRunNotFound:
        existing = None

    # H3 市场派生：先显式信号；判不出且已有 run 则复用其市场；仍判不出 → unknown，不伪造。
    market = _derive_candidate_market(payload)
    if market is None and existing is not None:
        market = existing.market
    if market is None:
        return {
            "registered": False, "run_id": run_id,
            "error": "无法判定候选市场（payload 缺 market/asset_class，且无既有 run 可复用）"
                     "——拒绝默认 A股 / 伪造标的（H3）；请在 handoff 带 market=equity_cn|crypto",
        }

    # 标的：只用 payload 显式提供的真标的；缺则空壳注册（不凭空造 600519/BTCUSDT，§3 不假绿灯）。
    raw_symbols = payload.get("symbols")
    symbols = [str(s) for s in raw_symbols] if isinstance(raw_symbols, list) and raw_symbols else []
    # 二次注册缺标的：报既有 run 的真实标的（不返空列表谎称无标的——§3 反向不假）。
    reported_symbols = symbols or ([str(s) for s in existing.symbols] if existing is not None else [])
    bench = payload.get("bench") or ("BTC" if market == "crypto" else "中证500")

    # M3 reconcile：同 run_id 二次注册若市场/标的与既有不符，显式拒绝（不静默沿用旧值还报 success）。
    if existing is not None:
        if existing.market != market:
            return {
                "registered": False, "run_id": run_id,
                "error": f"二次注册市场冲突（M3）：已注册为 {existing.market!r}，本次传 {market!r}"
                         "——拒绝静默改市场；如需换市场请用新 run_id",
            }
        if symbols and [str(s) for s in existing.symbols] != symbols:
            return {
                "registered": False, "run_id": run_id,
                "error": f"二次注册标的冲突（M3）：已注册 {list(existing.symbols)}，本次传 {symbols}"
                         "——拒绝静默改标的；如需换标的请用新 run_id",
            }

    # DS-4「都做」testnet 真喂可选档（默认 off）：payload.testnet=True 且配 testnet key → 喂 Binance testnet
    # 公共实时 bar；无 key/连接失败 → 诚实回退兜底（fail-open 留痕）。治理：testnet key 仅查名存在性不进 LLM、
    # 永走模拟撮合不下 live 单、A股恒拒 testnet（crypto only，desk 内守门）。
    want_testnet = bool(payload.get("testnet", False))
    try:
        if existing is None:  # idempotent：已注册的不重复建（重复 submit 不另造，只重 prime）
            provider_override = None
            provider_status: dict[str, Any] | None = None
            requested_provider = str(payload.get("provider") or payload.get("data_provider") or "").strip()
            if requested_provider:
                provider_override, provider_status = _paper_provider_override(
                    market=market,
                    symbols=[str(s) for s in symbols],
                    payload=payload,
                )
            PAPER_DESK.register_run(
                run_id=run_id, name=record.get("name") or run_id,
                origin=f"策略台 · {creator}", market=market, symbols=symbols,
                bench=bench, creator=creator,
                equity_log_path=DATA_ROOT / "paper" / run_id / "equity_log.jsonl",
                testnet=want_testnet,
                provider_override=provider_override,
                provider_status=provider_status,
            )
        primed = PAPER_DESK.prime_run(run_id)
        # provider 档位 + 降级留痕透传（§3 诚实：testnet 真喂 vs 回退兜底对用户透明）。
        try:
            _st = PAPER_DESK.status(run_id)
            primed = {**primed, "provider_kind": _st.get("provider_kind"),
                      "degrade_reason": _st.get("degrade_reason")}
        except Exception:  # noqa: BLE001  status 取不到不阻断注册结果
            pass
        return {"registered": True, "run_id": run_id, "market": market, "symbols": reported_symbols, **primed}
    except Exception as exc:  # noqa: BLE001  注册派生失败不阻塞候选 handoff，但带显式 error（H4）
        logging.getLogger(__name__).warning("candidate→paper register failed: %s (%s)", run_id, exc)
        return {"registered": False, "run_id": run_id, "error": f"模拟台注册/prime 失败：{exc}"}


def _paper_provider_override(
    *, market: str, symbols: list[str], payload: dict[str, Any]
) -> tuple[Any | None, dict[str, Any]]:
    requested = str(payload.get("provider") or payload.get("data_provider") or "replay").strip().lower()
    if requested not in {"testnet", "binance_testnet", TESTNET_REALTIME_SOURCE}:
        return None, {"requested_provider": "replay", "active_provider": "replay", "connected": False}
    if market != "crypto":
        return None, {
            "requested_provider": TESTNET_REALTIME_SOURCE,
            "active_provider": "replay",
            "connected": False,
            "fallback_reason": "testnet_provider_only_supports_crypto_paper",
        }
    key_name = (
        payload.get("testnet_keystore_name")
        or payload.get("binance_testnet_key_name")
        or os.environ.get("QUANTBT_BINANCE_TESTNET_KEY")
    )
    product = str(payload.get("testnet_product") or "usdm_futures")
    if product not in {"usdm_futures", "spot"}:
        return None, {
            "requested_provider": TESTNET_REALTIME_SOURCE,
            "active_provider": TESTNET_UNAVAILABLE_SOURCE,
            "connected": False,
            "credential_configured": bool(key_name),
            "fallback_reason": "unsupported_testnet_product",
        }
    provider, status = make_binance_testnet_provider(
        symbols=symbols,
        keystore=KEYSTORE,
        key_name=str(key_name) if key_name else None,
        product=product,  # type: ignore[arg-type]
        interval=str(payload.get("testnet_interval") or "1m"),
    )
    return provider, status


@app.get("/api/strategy/candidates")
def strategy_list_candidates(user=Depends(require_user_dependency)) -> dict[str, Any]:
    """列出模拟台候选池（策略台终点产物）。"""
    _ = user
    return {"candidates": CANDIDATE_POOL.list_candidates()}


# =============== AUTH ===============

@app.post("/api/auth/register")
def auth_register(payload: dict = Body(...)) -> dict[str, Any]:
    try:
        user = AUTH_SERVICE.register(
            username=payload["username"],
            password=payload["password"],
            display_name=payload.get("display_name", ""),
        )
        _u, token = AUTH_SERVICE.login(payload["username"], payload["password"])
        # v0.9.x · funnel 埋点 (patch2 §H.b)
        try:
            EVENT_SERVICE.track(
                "user_registered",
                user_id=user.user_id,
                properties={
                    "auth_method": "password",
                    "persona_hint": payload.get("persona_hint", "unknown"),
                    "referrer": payload.get("referrer"),
                    "client_tz": payload.get("client_tz"),
                },
            )
        except Exception:  # noqa: BLE001 - 埋点失败不阻塞注册
            pass
        return {"user": user.to_dict(), "token": token}
    except AuthError as exc:
        raise HTTPException(400, str(exc))
    except KeyError as exc:
        raise HTTPException(400, f"缺少字段: {exc}")


@app.post("/api/auth/login")
def auth_login(payload: dict = Body(...)) -> dict[str, Any]:
    try:
        user, token = AUTH_SERVICE.login(payload.get("username", ""), payload.get("password", ""))
        return {"user": user.to_dict(), "token": token}
    except AuthError as exc:
        raise HTTPException(401, str(exc))


@app.post("/api/auth/logout")
def auth_logout(authorization: str | None = None) -> dict[str, str]:
    if authorization and authorization.lower().startswith("bearer "):
        AUTH_SERVICE.logout(authorization[7:].strip())
    return {"status": "ok"}


@app.get("/api/auth/me")
def auth_me(user=Depends(current_user_dependency)) -> dict[str, Any]:
    if user is None:
        return {"user": None, "anonymous": True}
    return {"user": user.to_dict(), "anonymous": False}


@app.get("/api/auth/users/{username}")
def auth_user_profile(username: str, current=Depends(current_user_dependency)) -> dict[str, Any]:
    u = AUTH_SERVICE.get_user_by_username(username)
    if u is None:
        raise HTTPException(404, "用户不存在")
    stats = COMMUNITY_SERVICE.follow_stats(u.user_id, current.user_id if current else None)
    return {"user": u.to_dict(), **stats}


# =============== COMMUNITY ===============

@app.get("/api/community/feed")
def community_feed(
    feed_type: str = "recent",
    author: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current=Depends(current_user_dependency),
) -> list[dict[str, Any]]:
    author_id = None
    if author:
        u = AUTH_SERVICE.get_user_by_username(author)
        if u:
            author_id = u.user_id
    items = COMMUNITY_SERVICE.feed(
        feed_type=feed_type,
        current_user_id=current.user_id if current else None,
        author_id=author_id,
        limit=limit,
        offset=offset,
    )
    return [it.to_dict() for it in items]


@app.post("/api/community/posts")
def community_create_post(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        post = COMMUNITY_SERVICE.create_post(
            author_id=user.user_id,
            content=payload.get("content", ""),
            tags=payload.get("tags") or [],
            attached_run_id=payload.get("attached_run_id"),
            attached_factor_id=payload.get("attached_factor_id"),
            repost_of=payload.get("repost_of"),
        )
        return post.to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/community/posts/{post_id}")
def community_get_post(post_id: str, current=Depends(current_user_dependency)) -> dict[str, Any]:
    item = COMMUNITY_SERVICE.get_post(post_id, current.user_id if current else None)
    if item is None:
        raise HTTPException(404, "帖子不存在")
    return item.to_dict()


@app.delete("/api/community/posts/{post_id}")
def community_delete_post(post_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        return {"deleted": COMMUNITY_SERVICE.delete_post(post_id, user.user_id)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.post("/api/community/posts/{post_id}/like")
def community_like(post_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"liked": COMMUNITY_SERVICE.like(user.user_id, post_id)}


@app.delete("/api/community/posts/{post_id}/like")
def community_unlike(post_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"unliked": COMMUNITY_SERVICE.unlike(user.user_id, post_id)}


@app.get("/api/community/posts/{post_id}/comments")
def community_comments(post_id: str) -> list[dict[str, Any]]:
    return COMMUNITY_SERVICE.list_comments(post_id)


@app.post("/api/community/posts/{post_id}/comments")
def community_add_comment(post_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        c = COMMUNITY_SERVICE.add_comment(post_id, user.user_id, payload.get("content", ""), payload.get("reply_to"))
        return c.to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/community/users/{target_username}/follow")
def community_follow(target_username: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    target = AUTH_SERVICE.get_user_by_username(target_username)
    if target is None:
        raise HTTPException(404, "目标用户不存在")
    try:
        return {"followed": COMMUNITY_SERVICE.follow(user.user_id, target.user_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/community/users/{target_username}/follow")
def community_unfollow(target_username: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    target = AUTH_SERVICE.get_user_by_username(target_username)
    if target is None:
        raise HTTPException(404, "目标用户不存在")
    return {"unfollowed": COMMUNITY_SERVICE.unfollow(user.user_id, target.user_id)}


# =============== STRATEGY SHARING ===============

@app.post("/api/sharing/publish")
def sharing_publish(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        s = SHARING_SERVICE.publish_strategy(
            run_id=payload["run_id"],
            author_id=user.user_id,
            title=payload.get("title") or payload["run_id"],
            description=payload.get("description", ""),
            tags=payload.get("tags") or [],
            asset_class=payload.get("asset_class", ""),
            public=bool(payload.get("public", True)),
        )
        return s.to_dict()
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/sharing/feed")
def sharing_feed(
    asset_class: str | None = None,
    author: str | None = None,
    sort_by: str = "recent",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    author_id = None
    if author:
        u = AUTH_SERVICE.get_user_by_username(author)
        if u:
            author_id = u.user_id
    items = SHARING_SERVICE.list_strategies(
        asset_class=asset_class,
        author_id=author_id,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    cache: dict[str, dict[str, str]] = {}
    out: list[dict[str, Any]] = []
    for s in items:
        if s.author_id not in cache:
            u = AUTH_SERVICE.get_user_by_id(s.author_id)
            cache[s.author_id] = (
                {"author_username": u.username, "author_display_name": u.display_name}
                if u else {"author_username": "unknown", "author_display_name": "unknown"}
            )
        d = s.to_dict()
        d.update(cache[s.author_id])
        out.append(d)
    return out


@app.get("/api/sharing/{share_id}")
def sharing_get(share_id: str) -> dict[str, Any]:
    s = SHARING_SERVICE.get_strategy(share_id)
    if s is None:
        raise HTTPException(404, "share 不存在")
    return s.to_dict()


@app.post("/api/sharing/{share_id}/fork")
def sharing_fork(share_id: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        s = SHARING_SERVICE.fork_strategy(share_id, user.user_id, title=payload.get("title"))
        return s.to_dict()
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/sharing/{share_id}/like")
def sharing_like(share_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"liked": SHARING_SERVICE.like(user.user_id, share_id)}


@app.delete("/api/sharing/{share_id}/like")
def sharing_unlike(share_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"unliked": SHARING_SERVICE.unlike(user.user_id, share_id)}


@app.delete("/api/sharing/{share_id}")
def sharing_delete(share_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        return {"deleted": SHARING_SERVICE.delete_strategy(share_id, user.user_id)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


# ============ COPY TRADE ============

@app.get("/api/copy_trade/masters")
def ct_list_masters(
    asset_class: str | None = None,
    sort_by: str = "followers",
    invite_only: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    masters = COPY_TRADE_SERVICE.list_masters(
        asset_class=asset_class, sort_by=sort_by,
        invite_only=invite_only, limit=limit,
    )
    cache: dict[str, dict[str, str]] = {}
    out: list[dict[str, Any]] = []
    for m in masters:
        if m.user_id not in cache:
            u = AUTH_SERVICE.get_user_by_id(m.user_id)
            cache[m.user_id] = (
                {"author_username": u.username, "author_display_name": u.display_name}
                if u else {"author_username": "unknown", "author_display_name": "unknown"}
            )
        d = m.to_dict()
        d.update(cache[m.user_id])
        # 私域不回显 invite_code（仅 owner 看得到，走单独 endpoint）
        if d.get("is_invite_only"):
            d["invite_code"] = ""
        out.append(d)
    return out


@app.get("/api/copy_trade/masters/{master_id}")
def ct_get_master(master_id: str, current=Depends(current_user_dependency)) -> dict[str, Any]:
    m = COPY_TRADE_SERVICE.get_master(master_id)
    if m is None:
        raise HTTPException(404, "master 不存在")
    d = m.to_dict()
    # 私域：非 owner 看不到 invite_code
    if d.get("is_invite_only") and (current is None or current.user_id != m.user_id):
        d["invite_code"] = ""
    u = AUTH_SERVICE.get_user_by_id(m.user_id)
    if u:
        d["author_username"] = u.username
        d["author_display_name"] = u.display_name
    return d


@app.post("/api/copy_trade/masters")
def ct_register_master(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        m = COPY_TRADE_SERVICE.register_master(
            user_id=user.user_id,
            display_name=payload.get("display_name") or user.display_name,
            description=payload.get("description", ""),
            asset_class=payload.get("asset_class", "crypto_perp"),
            profit_share_pct=float(payload.get("profit_share_pct", 0.10)),
            is_invite_only=bool(payload.get("is_invite_only", False)),
            risk_params=payload.get("risk_params") or {},
        )
        return m.to_dict()
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.patch("/api/copy_trade/masters/{master_id}")
def ct_update_master(master_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        m = COPY_TRADE_SERVICE.update_master(
            master_id, user.user_id,
            description=payload.get("description"),
            profit_share_pct=payload.get("profit_share_pct"),
            is_invite_only=payload.get("is_invite_only"),
            risk_params=payload.get("risk_params"),
        )
        return m.to_dict()
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/copy_trade/masters/{master_id}/rotate_invite")
def ct_rotate_invite(master_id: str, user=Depends(require_user_dependency)) -> dict[str, str]:
    try:
        code = COPY_TRADE_SERVICE.rotate_invite_code(master_id, user.user_id)
        return {"invite_code": code}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/copy_trade/masters/{master_id}/redeem")
def ct_redeem(master_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        ok = COPY_TRADE_SERVICE.redeem_invite(user.user_id, master_id, payload.get("invite_code", ""))
        return {"redeemed": ok}
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/copy_trade/masters/{master_id}/subscribe")
def ct_subscribe(master_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        f = COPY_TRADE_SERVICE.subscribe(
            user_id=user.user_id,
            master_id=master_id,
            invest_amount=float(payload.get("invest_amount", 0)),
            binance_keystore_name=payload.get("binance_keystore_name", ""),
            binance_network=payload.get("binance_network", "testnet"),
            per_order_max_usdt=float(payload.get("per_order_max_usdt", 100)),
            daily_loss_limit_pct=float(payload.get("daily_loss_limit_pct", 0.05)),
            max_positions=int(payload.get("max_positions", 5)),
            max_leverage=(float(payload["max_leverage"]) if payload.get("max_leverage") is not None else None),
        )
        return f.to_dict()
    except (CopyTradeError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/copy_trade/masters/{master_id}/unsubscribe")
def ct_unsubscribe(master_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"unsubscribed": COPY_TRADE_SERVICE.unsubscribe(user.user_id, master_id)}


@app.post("/api/copy_trade/masters/{master_id}/pause")
def ct_pause(master_id: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)) -> dict[str, bool]:
    paused = bool(payload.get("paused", True))
    return {"updated": COPY_TRADE_SERVICE.pause_subscription(user.user_id, master_id, paused=paused)}


@app.get("/api/copy_trade/me/subscriptions")
def ct_my_subscriptions(user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    subs = COPY_TRADE_SERVICE.list_subscriptions(user.user_id)
    out: list[dict[str, Any]] = []
    for s in subs:
        d = s.to_dict()
        m = COPY_TRADE_SERVICE.get_master(s.master_id)
        if m:
            d["master_display_name"] = m.display_name
            d["master_asset_class"] = m.asset_class
        out.append(d)
    return out


@app.get("/api/copy_trade/me/master")
def ct_my_master(user=Depends(require_user_dependency)) -> dict[str, Any] | None:
    m = COPY_TRADE_SERVICE.get_master_by_user(user.user_id)
    return m.to_dict() if m else None


@app.get("/api/copy_trade/masters/{master_id}/followers")
def ct_master_followers(master_id: str, user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    m = COPY_TRADE_SERVICE.get_master(master_id)
    if m is None:
        raise HTTPException(404)
    if m.user_id != user.user_id:
        raise HTTPException(403, "只有 master 自己看得到 follower 列表")
    followers = COPY_TRADE_SERVICE.list_followers(master_id, active_only=False)
    out: list[dict[str, Any]] = []
    for f in followers:
        d = f.to_dict()
        # 隐藏 keystore 名字（敏感引用）
        d["binance_keystore_name"] = "***"
        u = AUTH_SERVICE.get_user_by_id(f.user_id)
        if u:
            d["username"] = u.username
        out.append(d)
    return out


@app.post("/api/copy_trade/signals")
def ct_publish_signal(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    master = COPY_TRADE_SERVICE.get_master_by_user(user.user_id)
    if master is None:
        raise HTTPException(400, "请先注册成 master")
    try:
        sig = COPY_TRADE_SERVICE.publish_signal(
            master_id=master.master_id,
            user_id=user.user_id,
            symbol=payload["symbol"],
            side=payload["side"],
            quantity=float(payload["quantity"]),
            price=payload.get("price"),
            order_type=payload.get("order_type", "market"),
            stop_loss=payload.get("stop_loss"),
            take_profit=payload.get("take_profit"),
            leverage=(float(payload["leverage"]) if payload.get("leverage") is not None else None),
            note=payload.get("note", ""),
        )
    except (CopyTradeError, KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    # relay → 所有 active follower 真下单。T-021：enforce_gate=True → 必经会话外硬墙
    # （deny-by-default 策略门 + 防重放 + 真钱档 fail-closed），INV-2/M17 生产强制；beta=幂等+杠杆硬截断。
    relayer = SignalRelayer(
        COPY_TRADE_SERVICE, KEYSTORE, _binance_venue_for_follower, beta=CT_BETA_SERVICE,
        enforce_gate=True, nonce_ledger=RELAY_NONCE_LEDGER, broker=ORDER_BROKER,
    )
    relay_results = relayer.relay(sig)
    return {"signal": sig.to_dict(), "relay": relay_results}


@app.delete("/api/copy_trade/signals/{signal_id}")
def ct_cancel_signal(signal_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        return {"canceled": COPY_TRADE_SERVICE.cancel_signal(signal_id, user.user_id)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.get("/api/copy_trade/signals")
def ct_list_signals(master_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return [s.to_dict() for s in COPY_TRADE_SERVICE.list_signals(master_id=master_id, limit=limit)]


@app.get("/api/copy_trade/executions")
def ct_list_executions(signal_id: str | None = None, follower_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return [
        e.to_dict()
        for e in COPY_TRADE_SERVICE.list_executions(signal_id=signal_id, follower_id=follower_id, limit=limit)
    ]


# -------- P3.5 setup 向导状态 --------

@app.get("/api/setup/status")
def setup_status() -> dict[str, Any]:
    """引导式 setup 向导用：告诉前端哪几步还没完成。"""
    import os
    tushare_ok = bool(os.environ.get("TUSHARE_TOKEN"))
    keystore_names = KEYSTORE.list_names()
    demo_run_exists = (DATA_ROOT / "artifacts" / "experiments" / "quant1-demo").exists()
    return {
        "tushare_token_configured": tushare_ok,
        "binance_keystore_configured": any("binance" in n.lower() for n in keystore_names),
        "demo_run_exists": demo_run_exists,
        "factors_count": len(FACTOR_REGISTRY.list()),
        "connectors_count": len(connector_registry.names()),
        "next_step": (
            "configure_tushare" if not tushare_ok
            else "configure_binance" if not keystore_names
            else "run_demo" if not demo_run_exists
            else "ready"
        ),
    }


@app.get("/api/data/markets")
def get_markets() -> list[dict]:
    return get_markets_response()


@app.get("/api/data/kinds")
def get_data_kinds(market: str | None = Query(None)) -> list[dict]:
    return get_data_kinds_response(market)


@app.get("/api/data/pools")
def get_data_pools(market: str | None = Query(None)) -> list[dict]:
    return get_data_pools_response(market)


@app.get("/api/data/overview")
def get_data_overview() -> list[dict]:
    return get_data_overview_response()


@app.get("/api/data/files")
def get_data_files(
    market: str | None = Query(None),
    interval: str | None = Query(None),
    data_kind: str | None = Query(None),
) -> list[dict]:
    return get_data_files_response(market=market, interval=interval, data_kind=data_kind)


@app.get("/api/data/preview")
def get_data_preview(
    file_id: str | None = Query(None),
    market: str | None = Query(None),
    interval: str | None = Query(None),
    symbol: str | None = Query(None),
    data_kind: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
) -> dict:
    try:
        return get_data_preview_response(
            file_id=file_id,
            market=market,
            interval=interval,
            symbol=symbol,
            data_kind=data_kind,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/jobs")
def list_jobs(
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(None),
    job_type: str | None = Query(None),
) -> list[dict]:
    return [job.to_dict() for job in JOB_STORE.list_jobs(limit=limit, status=status, job_type=job_type)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return JOB_STORE.get_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}") from exc


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    try:
        return JOB_STORE.retry_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    try:
        return JOB_STORE.cancel_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}") from exc


@app.post("/api/jobs/data/pull")
def create_data_pull_job(request: DataPullRequest) -> dict:
    try:
        return JOB_STORE.create_data_pull_job(request).to_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/data/pull-binance-full")
def create_binance_full_pull_job(request: BinanceFullPullRequest = BinanceFullPullRequest()) -> dict:
    try:
        return JOB_STORE.create_binance_full_pull_job(request).to_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return list_runs_response()


@app.post("/api/runs/query")
def query_runs(request: RunQueryRequest) -> dict:
    return query_runs_response(request.model_dump())


@app.get("/api/runs/compare")  # type: ignore[misc]
def _compare_runs_with_risk(run_ids: list[str] = Query(...)) -> dict:  # type: ignore[assignment]
    """v0.9.4 · 在 compare 响应每个 run 上追加 risk_summary，便于 ComparePage 显示信任色块。"""
    resp = compare_runs_response(run_ids)
    from .eval.risk_summary import compute_risk_summary
    runs = resp.get("runs") or []
    for r in runs:
        # 合并 metrics + jq_overview_metrics + overall (compare 用 overall snapshot)
        combined: dict[str, Any] = {}
        for src_key in ("metrics", "jq_overview_metrics", "overall", "out_of_sample"):
            v = r.get(src_key)
            if isinstance(v, dict):
                combined.update(v)
        r["risk_summary"] = compute_risk_summary(combined).to_dict()
    return resp


@app.get("/api/runs/compare_legacy")
def compare_runs(run_ids: list[str] = Query(...)) -> dict:
    return compare_runs_response(run_ids)


@app.get("/api/runs/compare/series")
def get_compare_series(
    run_ids: list[str] = Query(...),
    series: str = Query(...),
    segment: str = Query("overall"),
) -> dict:
    return get_compare_series_response(run_ids, series, segment)


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> dict[str, str]:
    try:
        delete_run_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        resp = get_run_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # v0.8.4 Day 4 · 计算 risk_summary 挂到响应（不改 run.json on-disk schema）
    from .eval.risk_summary import compute_risk_summary
    combined: dict[str, Any] = {}
    combined.update(resp.get("metrics") or {})
    combined.update(resp.get("jq_overview_metrics") or {})
    resp["risk_summary"] = compute_risk_summary(combined).to_dict()
    return resp


@app.get("/api/runs/{run_id}/series")
def get_run_series(run_id: str, series: str = Query(...), segment: str = Query("overall")) -> dict:
    try:
        return get_run_series_response(run_id, series, segment)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/tables/{table_name}")
def get_run_table(
    run_id: str,
    table_name: str,
    limit: int = Query(200, ge=1, le=100000),
    offset: int = Query(0, ge=0),
    sort: str | None = Query(None),
    order: str = Query("desc"),
    start_ts: str | None = Query(None),
    end_ts: str | None = Query(None),
    symbol: str | None = Query(None),
    side: str | None = Query(None),
) -> dict:
    try:
        return get_run_table_response(
            run_id,
            table_name,
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
            start_ts=start_ts,
            end_ts=end_ts,
            symbol=symbol,
            side=side,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/logs")
def get_run_logs(run_id: str, limit: int = Query(500, ge=1, le=100000), offset: int = Query(0, ge=0)) -> dict:
    try:
        return get_run_logs_response(run_id, limit=limit, offset=offset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/source")
def get_run_source(run_id: str) -> dict:
    try:
        return get_run_source_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/attribution")
def get_run_attribution(run_id: str) -> dict:
    try:
        return get_run_attribution_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/artifacts/{artifact_name}/download")
def download_artifact(run_id: str, artifact_name: str):
    try:
        path = artifact_download_path(run_id, artifact_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path.name}")
    return FileResponse(path, filename=path.name)


@app.get("/api/runs/{run_id}/export/{export_type}")
def export_run(run_id: str, export_type: str):
    try:
        path = export_path(run_id, export_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path.name}")
    return FileResponse(path, filename=f"{run_id}_{path.name}")


# ============================================================
# v0.8.2 · 聚宽风 IDE：策略 CRUD + 沙箱运行 + 代码生成
# ============================================================


@app.get("/api/ide/strategies")
def ide_list_strategies(user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return [strategy_to_dict(s) for s in IDE_SERVICE.list_strategies(user.username)]


@app.get("/api/ide/strategies/{name}")
def ide_get_strategy(name: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        return strategy_to_dict(IDE_SERVICE.get_strategy(user.username, name))
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/ide/strategies")
def ide_save_strategy(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    market_data_use_validation_refs = _ide_strategy_market_data_use_validation_refs(
        payload,
        operation="IDE strategy save",
    )
    try:
        s = IDE_SERVICE.save_strategy(
            user.username,
            payload.get("name", ""),
            payload.get("code", ""),
            asset_class=payload.get("asset_class", "crypto_perp"),
            description=payload.get("description", ""),
            market_data_use_validation_refs=market_data_use_validation_refs,
        )
    except IDEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    graph_refs = _record_ide_strategy_qro(
        s,
        actor=user.username,
        market_data_use_validation_refs=market_data_use_validation_refs,
    )
    out = strategy_to_dict(s)
    out["market_data_use_validation_refs"] = list(market_data_use_validation_refs)
    out.update(graph_refs)
    return out


@app.delete("/api/ide/strategies/{name}")
def ide_delete_strategy(name: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        IDE_SERVICE.delete_strategy(user.username, name)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/ide/strategies/{name}/run")
def ide_run_strategy(
    name: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    try:
        strategy = IDE_SERVICE.get_strategy(user.username, name)
        market_data_use_validation_refs = _ide_strategy_market_data_use_validation_refs(
            payload,
            operation="IDE strategy run",
            fallback_refs=getattr(strategy, "market_data_use_validation_refs", ()),
        )
        run = IDE_SERVICE.run_strategy(
            user.username,
            name,
            market_data_use_validation_refs=market_data_use_validation_refs,
        )
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    graph_refs = _record_ide_run_qro(
        strategy,
        run,
        actor=user.username,
        market_data_use_validation_refs=market_data_use_validation_refs,
    )
    out = run_to_dict(run)
    out["market_data_use_validation_refs"] = list(market_data_use_validation_refs)
    out.update(graph_refs)
    return out


@app.get("/api/ide/runs")
def ide_list_runs(limit: int = Query(50, ge=1, le=200), user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return [run_to_dict(r) for r in IDE_SERVICE.list_runs(user.username, limit=limit)]


@app.get("/api/ide/runs/{run_id}")
def ide_get_run(run_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        run = IDE_SERVICE.get_run(run_id)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.owner_username != user.username:
        raise HTTPException(status_code=403, detail="无权访问该 run")
    return run_to_dict(run)


@app.get("/api/ide/runs/{run_id}/{kind}")
def ide_get_run_artifact(run_id: str, kind: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        run = IDE_SERVICE.get_run(run_id)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.owner_username != user.username:
        raise HTTPException(status_code=403, detail="无权访问该 run")
    try:
        return IDE_SERVICE.get_run_artifact(run_id, kind)
    except IDEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ide/ai_complete")
def ide_ai_complete(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """IDE 代码生成：让 LLM 写 / 解释 / 修复 策略代码。

    payload: {prompt: str, context_code?: str, mode?: 'write'|'explain'|'fix'}
    """
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 必填")
    market_data_use_validation_refs = _ide_strategy_market_data_use_validation_refs(
        payload,
        operation="IDE AI complete",
    )
    mode = payload.get("mode", "write")
    context_code = (payload.get("context_code") or "")[:8000]
    system_prompts = {
        "write": (
            "你是 QuantBT 的策略代码生成层。用户在浏览器 IDE 里写 Python 策略。"
            "约束：(1) 输出必须是纯 Python 代码片段，不要 markdown 围栏；"
            "(2) 用 `quantbt.emit_result({...})` 在结尾发出回测结果；"
            "(3) 禁止 socket/subprocess/os.system；"
            "(4) 可用 numpy/pandas/polars/math。"
            "保持简短可读。"
        ),
        "explain": (
            "你是 QuantBT 的策略代码解释层。逐段解释下面这段策略代码的意图、"
            "因子逻辑、潜在风险（过拟合 / 前视偏差 / 流动性假设）。"
            "用中文，分条列出，不要返回代码。"
        ),
        "fix": (
            "你是 QuantBT 的策略代码修复层。下面的代码运行报错。"
            "请定位 bug 并给出修复后的完整 Python 代码片段（不要 markdown）。"
        ),
    }
    base_prompt = system_prompts.get(mode, system_prompts["write"])
    # 喂给 LLM 完整的写策略上下文（connector / factor / operator / 沙箱规则 / emit_result schema）
    ctx = build_ai_context(
        connectors=connector_registry.describe_all(),
        factors=[f.to_dict() for f in FACTOR_REGISTRY.list()],
        operators=list_operators(),
        fields_by_market=_field_universe_for_prompt(payload.get("market")),
    )
    sys_prompt = base_prompt + "\n\n" + ctx.to_system_prompt_block()
    user_text = f"{prompt}\n\n# 当前编辑器内容（context）:\n{context_code}" if context_code else prompt
    from .agent.llm_client import LLMMessage
    try:
        client = _current_agent_llm()
        reply = client.chat([
            LLMMessage(role="system", content=sys_prompt),
            LLMMessage(role="user", content=user_text),
        ])
        text = reply.content or ""
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败: {exc}") from exc
    provider = str(getattr(client, "provider", "unknown"))
    graph_refs = _record_ide_ai_complete_qro(
        mode=str(mode),
        prompt=prompt,
        context_code=context_code,
        provider=provider,
        output_text=text.strip(),
        actor=user.username,
        market=payload.get("market"),
        market_data_use_validation_refs=market_data_use_validation_refs,
    )
    return {
        "mode": mode,
        "code": text.strip(),
        "provider": provider,
        "market_data_use_validation_refs": list(market_data_use_validation_refs),
        **graph_refs,
    }


@app.get("/api/ide/ai_context")
def ide_ai_context(user=Depends(require_user_dependency)) -> dict[str, Any]:
    """UI 透明展示 LLM 拿到的上下文（connector / factor / operator / 沙箱规则）。"""

    _ = user
    ctx = build_ai_context(
        connectors=connector_registry.describe_all(),
        factors=[f.to_dict() for f in FACTOR_REGISTRY.list()],
        operators=list_operators(),
        fields_by_market=_field_universe_for_prompt(),
    )
    return ctx.to_dict()


@app.get("/api/ide/runs/{run_id}/risk_preview")
def ide_run_risk_preview(run_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """v0.9.2 · promote 前预算 risk_summary，让 IDE 前端实时展示证据状态。"""
    try:
        ide_run = IDE_SERVICE.get_run(run_id)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if ide_run.owner_username != user.username:
        raise HTTPException(status_code=403, detail="无权访问该 run")
    if ide_run.status != "ok":
        return {"risk_summary": None, "reason": f"run status={ide_run.status}"}

    try:
        result = IDE_SERVICE.get_run_artifact(run_id, "result")["body"]
    except IDEError:
        return {"risk_summary": None, "reason": "no emit_result"}

    # 从 result.json 抽 metrics (兼容 emit_result 顶层直接给 metrics dict 或挂 metrics 字段)
    metrics_combined: dict[str, Any] = {}
    if isinstance(result, dict):
        if isinstance(result.get("metrics"), dict):
            metrics_combined.update(result["metrics"])
        # 平铺字段（用户也可能直接顶层放 sharpe）
        for k in ("sharpe", "sharpe_ratio", "pbo", "dsr", "deflated_sharpe",
                   "max_drawdown", "drawdown", "alpha", "beta", "ic_ir",
                   "turnover", "max_position_weight", "information_ratio"):
            if k in result and not isinstance(result[k], dict):
                metrics_combined.setdefault(k, result[k])

    # T-015：preview 也经多证据三角 gate（record=False，不刷 honest-N），把 dsr/pbo 注入
    # metrics → 让 risk_summary 的 _rule_dsr/_rule_pbo 从「永远拿 None」变真生效。
    gate_verdict = None
    eq = result.get("equity_curve") if isinstance(result, dict) else None
    if isinstance(eq, list) and len(eq) >= 2:
        try:
            from .eval.gate_runner import asset_class_of, evaluate_overfit_gate, freq_to_ppy
            from .ide.promote import _normalize_equity_curve
            rows = _normalize_equity_curve(eq)
            returns = [r["net_return"] or 0.0 for r in rows]
            meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            market = str(meta.get("market") or "crypto_perp")
            freq = str(meta.get("frequency") or "1d")
            theme = str(meta.get("research_theme_id") or meta.get("strategy_name") or ide_run.strategy_id)
            if len(returns) >= 2:
                gr = evaluate_overfit_gate(
                    returns=returns, factor=meta.get("factor_formula") or ide_run.strategy_id,
                    params=meta.get("params") or {}, universe=market,
                    dataset_version=str(meta.get("dataset_version") or "unknown"),
                    freq=freq, label="net_return",
                    strategy_goal_ref=theme, asset_class=asset_class_of(market),
                    periods_per_year=freq_to_ppy(freq),
                    ledger=LEDGER, returns_store=RETURNS_STORE, record=False,
                )
                v = gr.verdict
                if v.color != "insufficient_evidence":
                    metrics_combined["dsr"] = v.dsr_conservative
                    if v.pbo is not None:
                        metrics_combined["pbo"] = v.pbo
                gate_verdict = v.to_dict()
                gate_verdict["honest_n"] = gr.honest_n
        except Exception as exc:  # noqa: BLE001  preview 不因 gate 失败而 500，但【不静默】——标错给前端
            _main_logger.warning("risk_preview gate 失败: %s", exc, exc_info=True)
            gate_verdict = {"error": type(exc).__name__}

    from .eval.risk_summary import compute_risk_summary
    rs = compute_risk_summary(metrics_combined).to_dict()
    return {"risk_summary": rs, "metrics_used": metrics_combined, "gate_verdict": gate_verdict}


@app.post("/api/ide/runs/{run_id}/promote")
def ide_promote_run(run_id: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """把 IDE 沙箱 run 提升为正式 Run（落 runs/<new_id>/ 进 RunDetail pipeline）。"""

    try:
        ide_run = IDE_SERVICE.get_run(run_id)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if ide_run.owner_username != user.username:
        raise HTTPException(status_code=403, detail="无权操作该 run")
    if ide_run.status != "ok":
        raise HTTPException(status_code=400, detail=f"only ok run can promote, got status={ide_run.status}")

    market_data_use_validation_refs = _ide_strategy_market_data_use_validation_refs(
        payload,
        operation="IDE run promote",
        fallback_refs=getattr(ide_run, "market_data_use_validation_refs", ()),
    )

    try:
        result = IDE_SERVICE.get_run_artifact(run_id, "result")["body"]
    except IDEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 拿对应 strategy 的源码（如果还在）
    strategy_code = ""
    strategy_name = "ide_strategy"
    strategy_match: StrategyFile | None = None
    try:
        strategies = IDE_SERVICE.list_strategies(user.username)
        match = next((s for s in strategies if s.strategy_id == ide_run.strategy_id), None)
        if match is not None:
            strategy_match = match
            strategy_code = match.code
            strategy_name = match.name
    except IDEError:
        pass

    try:
        promoted = promote_ide_run(
            ide_run_id=ide_run.run_id,
            owner_username=user.username,
            strategy_name=strategy_name,
            strategy_code=strategy_code,
            result=result,
            record_name=payload.get("record_name"),
            ledger=LEDGER,                 # T-015：记账 honest-N + 跑多证据三角 gate
            returns_store=RETURNS_STORE,
        )
    except PromoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    graph_refs = _record_ide_promote_qro(
        ide_run=ide_run,
        promoted=promoted,
        strategy=strategy_match,
        strategy_name=strategy_name,
        actor=user.username,
        market_data_use_validation_refs=market_data_use_validation_refs,
    )

    # v0.9.x · funnel 埋点 - run_completed
    try:
        sharpe = promoted.metrics.get("sharpe")
        EVENT_SERVICE.track(
            "run_completed",
            user_id=user.user_id,
            properties={
                "run_id": promoted.run_id,
                "strategy_id": ide_run.strategy_id,
                "market_mode": "ide_sandbox",
                "duration_ms": int(ide_run.duration_s * 1000),
                "status": "success",
                "sharpe": sharpe,
                "max_drawdown": promoted.metrics.get("max_drawdown"),
                "total_return": promoted.metrics.get("total_return"),
                "trigger": "promote_ide_run",
            },
        )
    except Exception:  # noqa: BLE001
        pass

    return {
        "run_id": promoted.run_id,
        "run_url": f"/runs/{promoted.run_id}",
        "metrics": promoted.metrics,
        "gate_verdict": promoted.gate_verdict,   # T-015 多证据三角裁决（前端下钻用）
        "market_data_use_validation_refs": list(market_data_use_validation_refs),
        **graph_refs,
    }


# ============================================================
# S2 · 策略台后端接线：图校验 / 版本史 / Fork / Live 只读快照
# 复用 IDE_SERVICE + lineage/ids.py（身份单一源）。不新增任何绕 OrderGuard 的下单路径。
# ============================================================


@app.post("/api/ide/strategies/{name}/validate")
def ide_validate_strategy_graph(
    name: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)
) -> dict[str, Any]:
    """图校验（B6 三层硬强制，前后端同一套规则）：

    ① 必填 in 端口未连 → warning ② exec 入口未经 Final Risk Gate → error
    ③ 连线 compat=bad → error。返回 {ok, errors, warnings}。

    无副作用纯校验——只读图、出诊断，绝不下单 / 动钱 / 碰 OrderGuard。
    name 用于 owner 命名空间校验（策略须属于本人；图本体由前端传 nodes/edges）。
    """

    # owner 隔离：图属于本人的某策略才校验（404 防越权读他人策略名空间）。
    try:
        IDE_SERVICE.get_strategy(user.username, name)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if nodes is None or edges is None:
        raise HTTPException(status_code=400, detail="payload 须含 nodes 与 edges")
    if not isinstance(nodes, (list, dict)) or not isinstance(edges, list):
        raise HTTPException(status_code=400, detail="nodes 须为 list/dict，edges 须为 list")
    return validate_graph(nodes, edges)


@app.get("/api/ide/strategies/{name}/versions")
def ide_strategy_versions(name: str, user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    """读策略版本史（lineage ledger 风 append-only；身份经 lineage.content_hash）。新→旧。"""

    try:
        versions = IDE_SERVICE.list_versions(user.username, name)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [version_to_dict(v) for v in versions]


@app.post("/api/ide/strategies/{name}/fork")
def ide_fork_strategy(
    name: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)
) -> dict[str, Any]:
    """策略级 Fork：派生可编辑副本，血缘父锚经 lineage/ids.py 单一身份源。

    ≠模板 fork / 社区分享 fork：这是同一作者把自己草稿派生出新草稿，
    新草稿版本史首条 origin='fork' 且 parent_content_hash 指向父策略内容指纹。
    """

    try:
        forked = IDE_SERVICE.fork_strategy(user.username, name, fork_name=payload.get("fork_name"))
    except IDEError as exc:
        # 父策略不存在 → 404；命名等业务约束 → 400。
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return strategy_to_dict(forked)


@app.get("/api/ide/strategies/{name}/live_snapshot")
def ide_strategy_live_snapshot(name: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """Live 只读聚合快照（B7）：聚合该策略最近运行的只读视图。

    硬约束：
    - **只读**：无任何下单参数 / 无 venue 句柄 / 不调 place_order —— 物理上无法从此端点下单。
    - **A股 live 永拒**（INV / RULES.project）：asset_class=equity_cn 的策略 live 直接 forbidden，
      不返回任何可被误当作「已上线」的运行态，措辞诚实标 live_allowed=False。
    """

    try:
        s = IDE_SERVICE.get_strategy(user.username, name)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # A股 live 永拒：直接给只读拒绝快照（不抛 500，前端据 live_allowed 渲染禁用态）。
    if s.asset_class == "equity_cn":
        return {
            "strategy_id": s.strategy_id,
            "name": s.name,
            "asset_class": s.asset_class,
            "live_allowed": False,
            "reason": "A股（equity_cn）实盘交易永久禁止（合规红线，不可绕过）",
            "runtime": "live",
            "readonly": True,
            "positions": [],
            "recent_runs": [],
        }

    # 只读聚合：拿本人该策略最近的沙箱运行做 Live 只读视图（无任何下单面）。
    runs = [r for r in IDE_SERVICE.list_runs(user.username, limit=200) if r.strategy_id == s.strategy_id]
    recent = [
        {
            "run_id": r.run_id,
            "status": r.status,
            "started_at_utc": r.started_at_utc,
            "finished_at_utc": r.finished_at_utc,
            "duration_s": r.duration_s,
            "result_keys": r.result_keys,
        }
        for r in runs[:10]
    ]
    return {
        "strategy_id": s.strategy_id,
        "name": s.name,
        "asset_class": s.asset_class,
        "live_allowed": True,        # crypto：策略层只读快照可看；真实下单仍须经 OrderGuard 全链
        "runtime": "live",
        "readonly": True,            # B7：Live 只读，编辑须 Fork
        "positions": [],             # 只读快照层不持仓句柄；持仓真值在 paper/live 账户域，非此端点
        "recent_runs": recent,
        "run_count": len(runs),
    }


# ============================================================
# R2 · 裁决卡（RunVerdictCard）后端接线：三态裁决 / 过拟合三角 / 成本敏感性 / 月度热力 / 晋级登记
# 复用 verification（三态 + 措辞守门）+ eval/overfit_gate（PBO/DSR/honest-N）+ approval（审批门）。
# 红线：verdict 锁三态、note 走 _verdict_note、promote 经审批门 approver≠creator——本块只投影/把关，不重造。
# ============================================================


@app.get("/api/runs/{run_id}/verdict")
def get_run_verdict(
    run_id: str,
    market_data_use_validation_refs: list[str] | None = Query(None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """验证官三态裁决投影（consistent/concern/blocked + disclosure + note）。

    note 由 verifier._verdict_note 供给（一致/存疑/不一致 + 适用域 + 未验证项），禁可信/安全/排除过拟合。
    run 无权威 verdict_id → concern（未验证 ≠ 已验证，不假绿灯）；篡改 fail-closed 投影 concern。
    """

    from .run_verdict import project_verdict

    try:
        validation_refs = _run_report_market_data_use_validation_refs(
            run_id,
            market_data_use_validation_refs,
            operation_label="run verdict reports",
        )
        return {
            **project_verdict(run_id, verdict_store=VERDICT_STORE, verifier=VERIFIER),
            "market_data_use_validation_refs": list(validation_refs),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/overfit")
def get_run_overfit(
    run_id: str,
    market_data_use_validation_refs: list[str] | None = Query(None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """过拟合三角门投影（PBO/DSR/honest-N/GateVerdict）。

    gate_label（晋级候选/证据分歧/…）来自 GateVerdict.color——【过拟合门】另一条管线，
    **绝不**作验证官三态 verdict 用（前端 verdict pill ≠ gate_label）。
    """

    from .run_verdict import project_overfit

    try:
        validation_refs = _run_report_market_data_use_validation_refs(
            run_id,
            market_data_use_validation_refs,
            operation_label="run overfit reports",
        )
        return {
            **project_overfit(run_id),
            "market_data_use_validation_refs": list(validation_refs),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/cost-sensitivity")
def get_run_cost_sensitivity(
    run_id: str,
    preset: str | None = Query(None),
    market_data_use_validation_refs: list[str] | None = Query(None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """成本敏感性 3 预设（optimistic/neutral/pessimistic）的 Sharpe/超额（P0 派生，诚实标 derived）。"""

    from .run_verdict import project_cost_sensitivity

    try:
        validation_refs = _run_report_market_data_use_validation_refs(
            run_id,
            market_data_use_validation_refs,
            operation_label="run cost-sensitivity reports",
        )
        return {
            **project_cost_sensitivity(run_id, preset),
            "market_data_use_validation_refs": list(validation_refs),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/monthly-heatmap")
def get_run_monthly_heatmap(
    run_id: str,
    market_data_use_validation_refs: list[str] | None = Query(None),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """月度（超额）收益热力真聚合（逐期收益按年-月累乘；非前端 seed 造数）。"""

    from .run_verdict import project_monthly_heatmap

    try:
        validation_refs = _run_report_market_data_use_validation_refs(
            run_id,
            market_data_use_validation_refs,
            operation_label="run monthly heatmap reports",
        )
        return {
            **project_monthly_heatmap(run_id),
            "market_data_use_validation_refs": list(validation_refs),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


_PORTFOLIO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _portfolio_promote_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise HTTPException(status_code=422, detail=f"{field} must be a finite number")
    return number


def _portfolio_promote_mapping(payload: dict[str, Any], field: str) -> dict[str, Any]:
    raw = payload.get(field)
    if not isinstance(raw, dict) or not raw:
        raise HTTPException(status_code=422, detail=f"{field} must be a non-empty object keyed by symbol")
    out: dict[str, Any] = {}
    for raw_symbol, value in raw.items():
        symbol = str(raw_symbol).strip()
        if not symbol:
            raise HTTPException(status_code=422, detail=f"{field} contains an empty symbol")
        if symbol in out:
            raise HTTPException(status_code=422, detail=f"{field} contains duplicate symbol {symbol!r}")
        out[symbol] = value
    return out


def _portfolio_promote_ref_tuple(payload: dict[str, Any], field: str, *, required: bool = False) -> tuple[str, ...]:
    raw = payload.get(field)
    if raw in (None, "", [], ()):
        if required:
            raise HTTPException(status_code=422, detail=f"{field} is required")
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise HTTPException(status_code=422, detail=f"{field} must be a list of refs")
    refs: list[str] = []
    for idx, value in enumerate(raw):
        ref = str(value or "").strip()
        if not ref:
            raise HTTPException(status_code=422, detail=f"{field}[{idx}] must be a non-empty ref")
        refs.append(ref)
    return tuple(refs)


def _portfolio_promote_signal_validation_gate(payload: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    signal_refs = _portfolio_promote_ref_tuple(payload, "signal_refs")
    validation_refs = _portfolio_promote_ref_tuple(
        payload,
        "signal_validation_refs",
        required=bool(signal_refs),
    )
    if validation_refs and not signal_refs:
        raise HTTPException(status_code=422, detail="signal_refs is required when signal_validation_refs are provided")
    if not signal_refs:
        return (), ()

    for signal_ref in signal_refs:
        try:
            SIGNAL_CONTRACTS.get(signal_ref)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"unknown SignalContract: {signal_ref}") from exc

    accepted_by_signal: dict[str, set[str]] = {signal_ref: set() for signal_ref in signal_refs}
    for validation_ref in validation_refs:
        try:
            record = SIGNAL_VALIDATIONS.validation(validation_ref)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"unknown signal validation: {validation_ref}") from exc
        if record.signal_ref not in accepted_by_signal:
            raise HTTPException(
                status_code=422,
                detail=f"signal validation {validation_ref} points at {record.signal_ref}, not this portfolio signal set",
            )
        if str(getattr(record.verdict, "value", record.verdict)) != "accepted":
            raise HTTPException(status_code=422, detail=f"signal validation {validation_ref} is not accepted")
        accepted_by_signal[record.signal_ref].add(record.validation_id)

    missing = [signal_ref for signal_ref, refs in accepted_by_signal.items() if not refs]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"signal_refs require accepted signal_validation_refs before portfolio promote: {missing}",
        )
    return signal_refs, validation_refs


def _portfolio_promote_market_data_use_validation_gate(
    payload: dict[str, Any],
    symbols: Iterable[str],
) -> tuple[str, ...]:
    validation_refs = _portfolio_promote_ref_tuple(
        payload,
        "market_data_use_validation_refs",
        required=True,
    )
    covered_instrument_refs: set[str] = set()
    for validation_ref in validation_refs:
        try:
            record = MARKET_DATA_REGISTRY.use_validation(validation_ref)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"unknown market data use validation: {validation_ref}") from exc
        if not bool(getattr(record, "accepted", False)):
            raise HTTPException(status_code=422, detail=f"market data use validation {validation_ref} is not accepted")
        if tuple(getattr(record, "violation_codes", ()) or ()):
            raise HTTPException(
                status_code=422,
                detail=f"market data use validation {validation_ref} has unresolved violations",
            )
        covered_instrument_refs.update(str(ref) for ref in getattr(record, "instrument_refs", ()) or ())

    missing: list[str] = []
    for symbol in symbols:
        normalized_symbol = str(symbol)
        candidates = {normalized_symbol, f"instrument:{normalized_symbol}"}
        if candidates.isdisjoint(covered_instrument_refs):
            missing.append(normalized_symbol)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"market_data_use_validation_refs do not cover portfolio symbols: {missing}",
        )
    return validation_refs


def _portfolio_promote_inputs(
    portfolio_id: str, payload: dict[str, Any]
) -> tuple[dict[str, float], dict[str, list[float]], list[str], str, str]:
    pid = str(portfolio_id or "").strip()
    if not _PORTFOLIO_ID_RE.fullmatch(pid):
        raise HTTPException(status_code=422, detail="portfolio_id must be 1-128 safe id characters")
    if payload.get("record") is False:
        raise HTTPException(status_code=422, detail="portfolio promote is a record=True endpoint")

    weights_raw = _portfolio_promote_mapping(payload, "weights")
    weights = {
        symbol: _portfolio_promote_number(value, f"weights.{symbol}")
        for symbol, value in weights_raw.items()
    }
    if not any(weight != 0.0 for weight in weights.values()):
        raise HTTPException(status_code=422, detail="weights must contain at least one non-zero weight")

    returns_raw = _portfolio_promote_mapping(payload, "asset_returns")
    markets_raw = _portfolio_promote_mapping(payload, "markets")
    expected = set(weights)
    if set(returns_raw) != expected:
        raise HTTPException(
            status_code=422,
            detail="asset_returns symbols must exactly match weights symbols",
        )
    if set(markets_raw) != expected:
        raise HTTPException(
            status_code=422,
            detail="markets symbols must exactly match weights symbols",
        )

    asset_returns: dict[str, list[float]] = {}
    lengths: set[int] = set()
    for symbol in weights:
        raw_series = returns_raw[symbol]
        if isinstance(raw_series, (str, bytes)) or not isinstance(raw_series, list):
            raise HTTPException(status_code=422, detail=f"asset_returns.{symbol} must be a list")
        series = [
            _portfolio_promote_number(value, f"asset_returns.{symbol}[{idx}]")
            for idx, value in enumerate(raw_series)
        ]
        if len(series) < 2:
            raise HTTPException(status_code=422, detail=f"asset_returns.{symbol} must contain at least 2 returns")
        asset_returns[symbol] = series
        lengths.add(len(series))
    if len(lengths) != 1:
        raise HTTPException(status_code=422, detail="asset_returns series must have identical lengths")

    markets: list[str] = []
    for symbol in weights:
        market = str(markets_raw[symbol] or "").strip()
        if not market:
            raise HTTPException(status_code=422, detail=f"markets.{symbol} must be a non-empty string")
        markets.append(market)

    dataset_version = str(payload.get("dataset_version") or "").strip()
    if not dataset_version:
        raise HTTPException(status_code=422, detail="dataset_version is required for production portfolio promote")
    freq = str(payload.get("freq") or "1d").strip().lower()
    if not freq:
        raise HTTPException(status_code=422, detail="freq must be a non-empty string")
    return weights, asset_returns, markets, dataset_version, freq


@app.post("/api/portfolios/{portfolio_id}/promote")
def promote_portfolio_to_production_gate(
    portfolio_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """组合 production promote gate：record=True 接入一本账，返回三角 gate 裁决。

    本端点只记录组合确证评估与 gate 结果，不翻真钱 stage、不下单、不绕审批。
    调用方必须给已实现收益流；端点只校验结构、对齐和数值有限性，不能替调用方证明收益来源。
    """

    weights, asset_returns, markets, dataset_version, freq = _portfolio_promote_inputs(portfolio_id, payload)
    signal_refs, signal_validation_refs = _portfolio_promote_signal_validation_gate(payload)
    market_data_use_validation_refs = _portfolio_promote_market_data_use_validation_gate(payload, weights)
    strategy_goal_ref = portfolio_strategy_goal_ref(portfolio_id)
    honest_n_before = LEDGER.honest_n(strategy_goal_ref)
    result = gate_portfolio(
        portfolio_id=portfolio_id,
        weights=weights,
        asset_returns=asset_returns,
        markets=markets,
        freq=freq,
        dataset_version=dataset_version,
        ledger=LEDGER,
        returns_store=RETURNS_STORE,
        record=True,
    )
    verdict = result.verdict.to_dict()
    verdict["honest_n"] = result.honest_n
    actor = str(getattr(user, "username", None) or getattr(user, "user_id", None) or "system")
    graph_refs = _record_portfolio_promote_qro(
        portfolio_id=portfolio_id,
        weights=weights,
        asset_returns=asset_returns,
        markets=markets,
        dataset_version=dataset_version,
        freq=freq,
        signal_refs=signal_refs,
        signal_validation_refs=signal_validation_refs,
        market_data_use_validation_refs=market_data_use_validation_refs,
        strategy_goal_ref=strategy_goal_ref,
        honest_n_before=honest_n_before,
        result=result,
        actor=actor,
    )
    return {
        "portfolio_id": portfolio_id,
        "strategy_goal_ref": strategy_goal_ref,
        "record": True,
        "promote_state": "gate_recorded",
        "dataset_version": dataset_version,
        "freq": freq,
        "symbols": list(weights),
        "signal_refs": list(signal_refs),
        "signal_validation_refs": list(signal_validation_refs),
        "market_data_use_validation_refs": list(market_data_use_validation_refs),
        "composition": portfolio_composition(weights),
        "config_hash": result.config_hash,
        "honest_n_before": honest_n_before,
        "honest_n_after": result.honest_n,
        "honest_n_delta": result.honest_n - honest_n_before,
        "gate_verdict": verdict,
        "actor": actor,
        **graph_refs,
        "boundary": "records portfolio gate evidence only; no order, no money movement, no stage flip",
    }


@app.post("/api/runs/{run_id}/promote")
def promote_run_to_candidate(
    run_id: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)
) -> dict[str, Any]:
    """把 run 登记为晋级候选（写动作）——经审批门，approver≠creator（INV-5，防自审）。

    本端点不绕 GATE_SERVICE：开一个 confirmatory promote 门。
    - approver 缺省/等于 creator → 422（绝不 self-approve 晋级；R7 生成≠验证）。
    - 三要件缺（无权威异模型裁决 / 过拟合证据 / honest-N）→ 422 + 缺口清单（诚实：未达放行）。
    晋级是用户显式动作（D-T024）；本端点只【登记+把关】，不动钱、不翻真钱 stage。
    """

    from .run_verdict import load_run

    # run 必须存在（404 防对幽灵 run 开门）。
    try:
        run = load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    creator = payload.get("created_by") or user.user_id
    approver = payload.get("approver")
    # approver≠creator 硬门（归一比较，防大小写/空白绕过）——缺 approver 或自审即 422。
    if not approver or (approver or "").strip().casefold() == (creator or "").strip().casefold():
        raise HTTPException(
            status_code=422,
            detail={
                "rejected": True,
                "reason": "approver 不得等于 creator 且不可空（防自审晋级，R7/INV-5 生成≠验证）",
            },
        )

    cfg_hash = (run.manifest.get("config_hash")
                or (run.manifest.get("source") or {}).get("config_hash")
                or run_id)
    try:
        gate = GATE_SERVICE.open_gate(
            model_id=f"run:{run_id}", version=1,
            from_stage="dev", to_stage="staging", action_kind="promote_staging",
            created_by=creator,
            verification_record_id=payload.get("verification_record_id"),
            evidence=payload.get("evidence") or {"config_hash": cfg_hash},
            strategy_goal_ref=payload.get("strategy_goal_ref"),
        )
    except GateStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if gate.decision == "rejected":
        # 三要件未达 → 诚实返缺口清单（前端据此知道还差什么，不假「已晋级」绿灯）。
        raise HTTPException(
            status_code=422,
            detail={
                "rejected": True,
                "gate_id": gate.gate_id,
                "gaps": gate.gap_list,
                "verdict_text": gate.verdict_text,
                "promoteState": "candidate",
            },
        )
    # pending：门已开、待 approver 人工审批（approver≠creator 已在 approve 步硬约束）。
    return {
        "run_id": run_id,
        "gate_id": gate.gate_id,
        "decision": gate.decision,          # pending
        "promoteState": "candidate",        # 仅「已登记开门」，真翻态须经 approve（≠ 已晋级）
        "verdict_text": gate.verdict_text,
        "approver_required": True,
        "note": "已开晋级审批门（待 approver≠creator 人工审批）；门未批前不视为已晋级。",
    }


@app.post("/api/portfolio/{portfolio_id}/promote")
def promote_portfolio(
    portfolio_id: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)
) -> dict[str, Any]:
    """组合 promote 生产端点（D-WAVE1A 残余① · ba59fb7b）：组合三角 gate `record=True` 真记 honest-N。

    `ide_promote_run`/`risk_preview` 的【组合层孪生 + record=True 版】：复用单一源 `LEDGER`/
    `RETURNS_STORE`（一本账，绝不另造）调 `gate_portfolio(record=True, ...)` → 组合独立计入
    `portfolio:<id>` 命名空间的 honest-N（与单策略串号物理隔离）。是 agent `portfolio.gate` 预览
    工具（record=False、business_tools.py:5b）的 production 记账孪生：同一组输入契约。

    诚实/PIT 铁律（gate 不自取数，避免前视——调用方喂【已实现】逐期收益，可经 D `load_panel(
    as_of_known)` PIT join）：
    - 结构非法（空 weights / 空 asset_returns / 空 markets / 非有限数值）→ 422，**不入账**。
    - 不可评分（成分集与收益集无交集 → 组合净收益序列 < 2 点）→ 422 **入账前拒绝**：honest-N
      不可改小（一本账无 set_n/delete），绝不用不可评分的 garbage 永久污染账本。
    - 有效但样本太短（T≥2 但 < min_T）→ gate 诚实返 `insufficient_evidence`（200，非 HTTP 错误）+
      照常入账（gate 能评分=一次真实多重检验）。
    - 裁决 red/yellow → 200，**照常入账**（失败的试验也消耗一次多重检验，绝不靠不记账洗白 honest-N）；
      `promoted=False`。promote 已记账 ≠ promote 已过闸。
    - A2 放行（冷启动 PBO N/A）→ 透传 `pbo=None` + `all_agree_positive=False`（非完整三角、组合层
      override，诚实标，绝不粉饰成三支同向）；强负仍 red（strong_neg 兜底守北极星不假绿灯）。

    本端点不绕单一源：weights/asset_returns 原样透传 `gate_portfolio`（不归一权重、不改序、不改 key
    大小写——任一都会改 config_hash、破 ADV2 重排同 hash 反作弊）；不接受 body 的 `record`/`ledger`/
    `strategy_goal_ref`（防 honest-N 洗白：production 只一本账、record 恒 True）。
    """

    import math

    from .lineage.ledger import HONEST_N_DISCLOSURE
    from .portfolio.gate import gate_portfolio, portfolio_net_returns

    # —— 结构校验（malformed request → 422，绝不 500、绝不入账）——
    weights = payload.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise HTTPException(status_code=422, detail="weights 须为非空 {symbol: weight}（先构建组合）")
    asset_returns = payload.get("asset_returns")
    if not isinstance(asset_returns, dict) or not asset_returns:
        raise HTTPException(
            status_code=422,
            detail="asset_returns 须为非空 {symbol: [逐期已实现收益]}（调用方喂已实现收益，gate 不自取数防前视）",
        )
    markets = payload.get("markets")
    if isinstance(markets, str):
        markets = [m.strip() for m in markets.split(",") if m.strip()]
    if not isinstance(markets, list) or not markets:
        # 空 markets → strictest_asset_class 退化 crypto/252，静默放松 A股 504 min_T → 诚实硬拒。
        raise HTTPException(
            status_code=422,
            detail="markets 须为非空列表（决定最严 min_T：任一成分 A股→504；空列表会静默放松门槛）",
        )

    # 数值强转（bad float → 422，绝不 500）。
    try:
        w_clean = {str(k): float(v) for k, v in weights.items()}
        ar_clean = {str(k): [float(x) for x in v] for k, v in asset_returns.items()}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"weights/asset_returns 含非数值: {exc}") from exc
    if any(not math.isfinite(v) for v in w_clean.values()):
        raise HTTPException(status_code=422, detail="weights 含非有限值（NaN/Inf）")
    if any(not math.isfinite(x) for series in ar_clean.values() for x in series):
        raise HTTPException(status_code=422, detail="asset_returns 含非有限值（NaN/Inf）")

    # —— 不可评分前拒绝（入账前）：成分↔收益无交集 → 组合净收益 < 2 点 → 422，绝不入不可评分行污染账本 ——
    net = portfolio_net_returns(w_clean, ar_clean)
    if len(net) < 2:
        raise HTTPException(
            status_code=422,
            detail="组合净收益序列不足 2 点（weights 与 asset_returns 无对齐成分）：无法评分，拒绝入账（honest-N 不可改小）",
        )

    freq = str(payload.get("freq") or "1d")
    dataset_version = str(payload.get("dataset_version") or "unknown")

    # —— 生产记账：复用单一源一本账（LEDGER/RETURNS_STORE 引用模块全局，便于测试 monkeypatch 隔离）——
    try:
        res = gate_portfolio(
            portfolio_id=str(portfolio_id),
            weights=w_clean,
            asset_returns=ar_clean,
            markets=markets,
            freq=freq,
            dataset_version=dataset_version,
            ledger=LEDGER,                 # 单一源一本账：honest-N 真记账（不另造 store）
            returns_store=RETURNS_STORE,
            record=True,                   # production promote 恒记账（≠ 预览 record=False）
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"组合 gate 入参非法: {exc}") from exc

    v = res.verdict
    out = v.to_dict()
    out.update({
        "portfolio_id": str(portfolio_id),
        "strategy_goal_ref": f"portfolio:{portfolio_id}",   # 独立命名空间（与单策略串号物理隔离）
        "config_hash": res.config_hash,                      # 复用 ids 单一身份源
        "honest_n": res.honest_n,                            # 该组合命名空间记账后名义 N（真值下界、不可改小）
        "honest_n_disclaimer": HONEST_N_DISCLOSURE,          # 诚实免责，逐字（措辞黑名单守门）
        "recorded": True,                                    # 已写一本账（confirmatory 试验，无论裁决色）
        "promoted": v.color == "green",                      # 仅 green 视为过闸；记账 ≠ 过闸（诚实）
        "net_len": len(net),                                 # PIT 对齐后实际入算长度（调用方可见截断）
        "note": "组合 promote 已记 honest-N（一本账，portfolio:<id> 独立命名空间）。已记账≠已过闸；"
                "冷启动 PBO=N/A 时 A2 凭 DSR+CI 双正放行(非完整三角)、过拟合仍 red。",
    })
    return out


@app.get("/api/research/themes/{theme}/honest_n")
def research_theme_honest_n(theme: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """R2 一键下钻：暴露某研究主题的 honest-N（名义 distinct config 计数）+ 诚实免责。

    只读、不可改小（T-013 一本账无 set_n/delete API）。N_eff 区间在各 run 的 gate_verdict 里。
    """

    from .lineage.ledger import HONEST_N_DISCLOSURE

    return {
        "strategy_goal_ref": theme,
        "honest_n": LEDGER.honest_n(theme),
        "disclaimer": HONEST_N_DISCLOSURE,
    }


# ============================================================
# v0.8.4 Day 2 · Glossary endpoints
# ============================================================


@app.get("/api/glossary")
def glossary_list(
    category: str | None = Query(None, description="按 category 过滤"),
    level: str | None = Query(None, description="按 level 过滤"),
) -> list[dict[str, Any]]:
    """列出全部词条 summary（用于 RunDetail ⓘ mapping 选词 + 词典页）。"""

    items = GLOSSARY.list_summary()
    if category:
        items = [x for x in items if x["category"] == category]
    if level:
        items = [x for x in items if x["level"] == level]
    return items


@app.get("/api/glossary/{term}")
def glossary_get(
    term: str,
    level: str | None = Query(None, description="渐进披露：'l1'/'l2'/'l3'/'l4'；省略=全部"),
) -> dict[str, Any]:
    """通过 slug 或 alias 拿单个词条。404 返 {error, term, suggestions}。"""

    t = GLOSSARY.lookup(term)
    if t is None:
        # 拼写相近建议：difflib 模糊匹配 slug + aliases
        import difflib
        q = term.strip().lower()
        candidates: list[tuple[str, str]] = []  # (key, slug)
        for x in GLOSSARY.list_summary():
            candidates.append((x["slug"].lower(), x["slug"]))
            for a in x["aliases"]:
                candidates.append((a.lower(), x["slug"]))
        keys = [k for k, _ in candidates]
        close = difflib.get_close_matches(q, keys, n=8, cutoff=0.4)
        # 去重 slug 保序
        seen: set[str] = set()
        suggestions: list[str] = []
        for k in close:
            for kk, slug in candidates:
                if kk == k and slug not in seen:
                    seen.add(slug)
                    suggestions.append(slug)
                    break
            if len(suggestions) >= 5:
                break
        raise HTTPException(
            status_code=404,
            detail={"error": "term_not_found", "term": term, "suggestions": suggestions},
        )
    return t.to_dict(level=level)


@app.get("/api/glossary/{term}/usage_in_runs")
def glossary_usage_in_runs(term: str, user_id: str | None = Query(None)) -> dict[str, Any]:
    """v0.8.5 · 该 metric 在用户历史 runs 的分布 (bucket histogram)。

    GlossaryDetailPage 侧栏用，让用户看到"我的 SR 落在第 X 分位"。
    """

    t = GLOSSARY.lookup(term)
    if t is None:
        return {"count": 0, "buckets": []}
    # 简化实现：扫 runs/<run_id>/run.json，找 metrics 中该 metric_name 值
    metric_name = t.slug
    # 别名映射
    alias_for_metric = {"sharpe_ratio": ["sharpe", "sharpe_ratio"], "max_drawdown": ["max_drawdown", "drawdown"]}
    candidates = alias_for_metric.get(metric_name, [metric_name])
    runs_root = DATA_ROOT / "artifacts" / "experiments"
    values: list[float] = []
    if runs_root.exists():
        for run_dir in runs_root.iterdir():
            manifest = run_dir / "run.json"
            if not manifest.exists():
                continue
            try:
                import json
                m = json.loads(manifest.read_text(encoding="utf-8-sig"))
                metrics = m.get("metrics") or {}
                for c in candidates:
                    if c in metrics and isinstance(metrics[c], (int, float)):
                        values.append(float(metrics[c]))
                        break
            except Exception:  # noqa: BLE001
                continue
    if not values:
        return {"count": 0, "buckets": []}
    # 5-bucket histogram
    lo, hi = min(values), max(values)
    if lo == hi:
        return {"count": len(values), "buckets": [{"range": f"{lo:.2f}", "users": len(values)}]}
    width = (hi - lo) / 5
    buckets = []
    for i in range(5):
        b_lo = lo + i * width
        b_hi = lo + (i + 1) * width
        cnt = sum(1 for v in values if b_lo <= v < (b_hi if i < 4 else b_hi + 1e-9))
        buckets.append({"range": f"{b_lo:.2f}~{b_hi:.2f}", "users": cnt})
    return {"count": len(values), "buckets": buckets}


@app.post("/api/events/track")
def events_track(payload: dict = Body(...), current=Depends(current_user_dependency)) -> dict[str, Any]:
    """前端埋点入口。fire-and-forget，不阻塞 UI。"""

    try:
        rec = EVENT_SERVICE.track(
            event_name=payload.get("event_name", ""),
            user_id=current.user_id if current else None,
            anonymous_id=payload.get("anonymous_id"),
            session_id=payload.get("session_id"),
            app_version=payload.get("app_version"),
            market_mode=payload.get("market_mode"),
            properties=payload.get("properties") or {},
        )
    except EventTrackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event_id": rec.event_id, "ok": True}


@app.get("/api/datasets/samples")
def datasets_samples() -> list[dict[str, Any]]:
    """v0.8.7 · 列出全部内置 sample。"""
    return list_samples()


@app.get("/api/datasets/samples/{sample_id}/preview")
def datasets_sample_preview(sample_id: str, rows: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """sample 前 N 行预览 (前端表格用)。"""
    df = load_sample(sample_id)
    if df is None:
        raise HTTPException(status_code=404, detail=f"sample 不存在: {sample_id}")
    preview = df.head(rows)
    return {
        "sample_id": sample_id,
        "total_rows": df.height,
        "columns": preview.columns,
        "rows": preview.to_dicts(),
    }


@app.get("/api/strategies/templates")
def strategies_templates() -> list[dict[str, Any]]:
    """v0.8.7 · 列出 3 个策略模板 (BTC momentum / ETH funding / A股 ETF rotation)。"""
    items = list_strategy_templates()
    # 不返回完整 code，只返回 metadata + code 长度（前端按需 fetch detail）
    return [
        {**{k: v for k, v in t.items() if k != "code"}, "code_length": len(t["code"])}
        for t in items
    ]


@app.get("/api/strategies/templates/{template_id}")
def strategies_template_detail(template_id: str) -> dict[str, Any]:
    """单个模板完整代码 + metadata。"""
    t = get_strategy_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"template 不存在: {template_id}")
    return t.to_dict()


@app.post("/api/strategies/templates/{template_id}/fork_to_ide")
def strategies_template_fork(
    template_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """v0.9.3 · 把策略模板 fork 到用户 IDE 名下，可立刻在 /ide 改 + 跑。"""
    t = get_strategy_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"template 不存在: {template_id}")
    new_name = payload.get("name") or f"{t.template_id}_fork"
    description = payload.get("description") or f"forked from template {t.template_id}"
    try:
        strategy = IDE_SERVICE.save_strategy(
            user.username, new_name, t.code,
            asset_class=t.asset_class, description=description,
        )
    except IDEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "strategy_id": strategy.strategy_id,
        "name": strategy.name,
        "ide_url": f"/ide?open={strategy.name}",
        "expected_metrics": t.expected_metrics,
    }


@app.get("/api/runs/{run_id}/coach_suggestion")
def runs_coach_suggestion(run_id: str) -> dict[str, Any]:
    """v0.8.6.1 · 基于 risk_summary 给出主动建议 (RunDetail 顶部浮卡片用)。"""
    try:
        resp = get_run_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    combined: dict[str, Any] = {}
    combined.update(resp.get("metrics") or {})
    combined.update(resp.get("jq_overview_metrics") or {})
    from .eval.risk_summary import compute_risk_summary
    rs = compute_risk_summary(combined).to_dict()
    sugg = suggest_from_risk_summary(rs)
    if sugg is None:
        return {"suggestion": None, "risk_summary": rs}
    return {"suggestion": sugg.to_dict(), "risk_summary": rs}


@app.post("/api/copy_trade/beta/apply")
def ct_beta_apply(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    role = payload.get("role", "follower")
    s = CT_BETA_SERVICE.apply_for_beta(user.user_id, role)
    return s.to_dict()


@app.get("/api/copy_trade/beta/status")
def ct_beta_status(role: str = Query("follower"), user=Depends(require_user_dependency)) -> dict[str, Any] | None:
    s = CT_BETA_SERVICE.get_beta_status(user.user_id, role)
    return s.to_dict() if s else None


@app.get("/api/copy_trade/beta/summary")
def ct_beta_summary() -> dict[str, Any]:
    return CT_BETA_SERVICE.waitlist_summary()


@app.get("/api/copy_trade/beta/dispatches")
def ct_beta_dispatches(user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return [d.to_dict() for d in CT_BETA_SERVICE.list_dispatches(user.user_id, limit=100)]


@app.post("/api/community/posts/{post_id}/check_compliance")
def community_post_compliance(post_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """v0.8.8.1 · 复检帖子合规（含 risk_summary snapshot）。"""
    try:
        post = COMMUNITY_SERVICE.get_post(post_id, current_user_id=user.user_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    risk_summary = None
    if post.get("attached_run_id"):
        try:
            run_resp = get_run_response(post["attached_run_id"])
            combined: dict[str, Any] = {}
            combined.update(run_resp.get("metrics") or {})
            combined.update(run_resp.get("jq_overview_metrics") or {})
            from .eval.risk_summary import compute_risk_summary
            risk_summary = compute_risk_summary(combined).to_dict()
        except FileNotFoundError:
            pass
    result = COMPLIANCE_SERVICE.record_compliance(
        post_id,
        content=post.get("content", ""),
        attached_run_id=post.get("attached_run_id"),
        risk_summary=risk_summary,
    )
    return result.to_dict()


@app.get("/api/community/posts/{post_id}/compliance")
def community_post_compliance_get(post_id: str) -> dict[str, Any]:
    rec = COMPLIANCE_SERVICE.get_compliance(post_id)
    if rec is None:
        return {"post_id": post_id, "passed": True, "checked": False}
    return {**rec.to_dict(), "checked": True}


@app.post("/api/community/check_text")
def community_check_text(payload: dict = Body(...)) -> dict[str, Any]:
    """前端发帖时调，提前预检文本是否含禁词。"""
    content = payload.get("content", "")
    forbidden = check_content_for_forbidden(content)
    return {
        "passed": len(forbidden) == 0,
        "forbidden_phrases_found": forbidden,
    }


# ============================================================
# v0.8.8 · Binance 安全阶梯 (SafeKey wizard + testnet matrix + live ladder)
# ============================================================


@app.post("/api/trading/safety/safekey_check")
def safety_safekey_check(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """记录 SafeKey wizard 检查结果。"""
    rec = SAFETY_SERVICE.record_safekey_check(
        user_id=user.user_id,
        key_id_hash=payload.get("key_id_hash", ""),
        enable_withdrawals=bool(payload.get("enable_withdrawals", False)),
        enable_internal_transfer=bool(payload.get("enable_internal_transfer", False)),
        enable_universal_transfer=bool(payload.get("enable_universal_transfer", False)),
        enable_margin=bool(payload.get("enable_margin", False)),
        enable_futures=bool(payload.get("enable_futures", True)),
        ip_restricted=bool(payload.get("ip_restricted", True)),
    )
    # v0.9.x · funnel 埋点
    try:
        EVENT_SERVICE.track(
            "safekey_check_completed",
            user_id=user.user_id,
            properties={
                "venue": payload.get("venue", "binance_um_futures"),
                "key_id_hash": rec.key_id_hash,
                "passed": rec.passed,
                "enable_withdrawals": rec.enable_withdrawals,
                "enable_futures": rec.enable_futures,
                "enable_margin": rec.enable_margin,
                "ip_restricted": rec.ip_restricted,
                "failure_reason": (rec.failures[0] if rec.failures else None),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return rec.to_dict()


@app.get("/api/trading/safety/safekey_latest")
def safety_safekey_latest(user=Depends(require_user_dependency)) -> dict[str, Any] | None:
    rec = SAFETY_SERVICE.get_latest_safekey(user.user_id)
    return rec.to_dict() if rec else None


@app.post("/api/trading/safety/matrix_attempt")
def safety_matrix_attempt(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    cell = SAFETY_SERVICE.record_matrix_attempt(
        user_id=user.user_id,
        order_type=payload.get("order_type", ""),
        side=payload.get("side", ""),
        place_ok=bool(payload.get("place_ok", False)),
        query_ok=bool(payload.get("query_ok", False)),
        cancel_ok=bool(payload.get("cancel_ok", False)),
        reconcile_ok=bool(payload.get("reconcile_ok", False)),
        error_code=payload.get("error_code"),
    )
    return cell.to_dict()


@app.get("/api/trading/safety/matrix")
def safety_matrix(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return SAFETY_SERVICE.get_matrix(user.user_id).to_dict()


@app.get("/api/trading/safety/ladder")
def safety_ladder(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return SAFETY_SERVICE.get_ladder(user.user_id).to_dict()


@app.post("/api/trading/safety/ladder/promote")
def safety_ladder_promote(user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        return SAFETY_SERVICE.promote_level(user.user_id).to_dict()
    except SafetyServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/trading/safety/ladder/demote")
def safety_ladder_demote(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    reason = payload.get("reason", "manual demote")
    state = SAFETY_SERVICE.demote(user.user_id, reason)
    # v0.9.x · kill_switch_triggered 事件（降级通常由 kill switch 触发）
    try:
        EVENT_SERVICE.track(
            "kill_switch_triggered",
            user_id=user.user_id,
            properties={
                "venue": payload.get("venue", "binance_um_futures"),
                "trigger_type": reason,
                "severity": payload.get("severity", "critical"),
                "action_taken": "demote_ladder",
                "blocked_until": state.promotion_blocked_until_utc,
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return state.to_dict()


@app.post("/api/trading/safety/matrix_attempt_e2e")
def safety_matrix_attempt_e2e(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """v0.9.x · testnet matrix 完整 e2e 一次性记录（含埋点）。"""
    cell = SAFETY_SERVICE.record_matrix_attempt(
        user_id=user.user_id,
        order_type=payload.get("order_type", ""),
        side=payload.get("side", ""),
        place_ok=bool(payload.get("place_ok", False)),
        query_ok=bool(payload.get("query_ok", False)),
        cancel_ok=bool(payload.get("cancel_ok", False)),
        reconcile_ok=bool(payload.get("reconcile_ok", False)),
        error_code=payload.get("error_code"),
    )
    try:
        EVENT_SERVICE.track(
            "testnet_order_e2e_completed",
            user_id=user.user_id,
            properties={
                "venue": payload.get("venue", "binance_um_futures"),
                "symbol": payload.get("symbol", "BTC-USDT"),
                "order_type": cell.order_type,
                "side": cell.side,
                "place_ok": cell.place_ok,
                "query_ok": cell.query_ok,
                "cancel_ok": cell.cancel_ok,
                "reconcile_ok": cell.reconcile_ok,
                "latency_ms": payload.get("latency_ms"),
                "error_code": cell.error_code,
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return cell.to_dict()


# ============================================================
# v0.8.6 · Mode 2 多轮对话 + SSE chat + RAG
# ============================================================


@app.post("/api/agent/chat/start")
def chat_start(payload: dict = Body(...), current=Depends(current_user_dependency)) -> dict[str, Any]:
    """创建 thread。market_mode / active_run_id / active_strategy_id 可选。"""
    try:
        t = CHAT_SERVICE.start_thread(
            user_id=current.user_id if current else None,
            market_mode=payload.get("market_mode", "ashare_research"),
            active_run_id=payload.get("active_run_id"),
            active_strategy_id=payload.get("active_strategy_id"),
            title=payload.get("title", ""),
        )
    except ChatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return thread_to_dict(t)


@app.get("/api/agent/chat/threads")
def chat_list_threads(user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return [thread_to_dict(t) for t in CHAT_SERVICE.list_threads(user.user_id)]


@app.get("/api/agent/chat/{thread_id}")
def chat_get_thread(thread_id: str, current=Depends(current_user_dependency)) -> dict[str, Any]:
    try:
        t = CHAT_SERVICE.get_thread(thread_id)
    except ChatError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _ = current  # 简化访问控制：所有 thread 自己 user 可见，留 v0.8.6.1 加 ACL
    msgs = CHAT_SERVICE.list_messages(thread_id)
    return {"thread": thread_to_dict(t), "messages": [message_to_dict(m) for m in msgs]}


@app.post("/api/agent/chat/{thread_id}/message")
def chat_send_message(
    thread_id: str,
    payload: dict = Body(...),
    current=Depends(current_user_dependency),
) -> dict[str, Any]:
    """非流式：发用户消息 → 触发 RAG + LLM → 返回 assistant 完整回复。

    流式版在 /api/agent/chat/{thread_id}/stream（SSE）。
    """
    try:
        thread = CHAT_SERVICE.get_thread(thread_id)
    except ChatError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    user_text = (payload.get("content") or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="content 必填")

    CHAT_SERVICE.add_message(thread_id, "user", user_text)

    # 1. RAG
    run_data: dict[str, Any] | None = None
    if thread.active_run_id:
        try:
            run_resp = get_run_response(thread.active_run_id)
            run_data = {
                "run_id": thread.active_run_id,
                **(run_resp.get("metrics") or {}),
                **(run_resp.get("jq_overview_metrics") or {}),
                "trust_level": (run_resp.get("risk_summary") or {}).get("trust_level"),
            }
        except FileNotFoundError:
            pass
    hits = retrieve(user_text, glossary=GLOSSARY, run_context=run_data)
    rag_text = format_rag_context(hits)
    run_text = format_run_context(run_data)
    history_text = CHAT_SERVICE.compress_history(thread_id)
    sys_prompt = build_mode2_prompt(
        rag_context=rag_text,
        run_context=run_text,
        conversation_history=history_text,
    )
    research_rag_payload = {
        **payload,
        "desk": payload.get("desk") or payload.get("rag_desk") or "research",
        "agent_id": payload.get("agent_id") or f"legacy-mode2-chat:{thread_id}",
        "rag_purpose": payload.get("rag_purpose") or "legacy_mode2_chat_context",
    }
    research_rag_provider = _agent_shell_rag_context_provider(research_rag_payload, current)

    # 2. Agent（T-027/D-PERM）：经 AgentRuntime 支持工具派发 + 权限三态（ask/auto/bypass），
    #    替代裸 client.chat。无副作用工具 auto/bypass 自主执行；动钱/晋级永不注册（治理门在端点层）。
    permission_mode = str(payload.get("permission_mode") or "auto")
    turn = None
    try:
        runtime = _agent_runtime(
            permission_mode=permission_mode,
            system_prompt=sys_prompt,
            rag_context_provider=research_rag_provider,
        )
        turn = runtime.run(user_text)
        reply_text = turn.final_message or "(LLM 无内容)"
        coverage_refs = _record_agent_turn_goal_entrypoint_coverage(
            turn,
            endpoint_ref="legacy_mode2.chat.message",
            actor="agent_runtime",
            permission_mode=permission_mode,
        )
    except AssetRAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        reply_text = f"[LLM 错误] {exc}"
        coverage_refs = {
            "compiler_ir_refs": [],
            "compiler_pass_refs": [],
            "entrypoint_coverage_refs": [],
        }

    # 3. 持久化 assistant 消息（含 RAG metadata 便于审计）
    msg = CHAT_SERVICE.add_message(
        thread_id,
        "assistant",
        reply_text,
        metadata={
            "rag_hits": [{"kind": h.kind, "slug": h.slug, "title": h.title, "score": h.score} for h in hits],
            "had_run_context": run_data is not None,
            "qro_ids": turn.qro_ids if turn else [],
            "research_graph_command_ids": turn.research_graph_command_ids if turn else [],
            "compiler_ir_refs": coverage_refs["compiler_ir_refs"],
            "compiler_pass_refs": coverage_refs["compiler_pass_refs"],
            "entrypoint_coverage_refs": coverage_refs["entrypoint_coverage_refs"],
            "research_asset_rag_hits": turn.rag_hits if turn else [],
            "research_asset_rag_usage_ids": turn.rag_usage_ids if turn else [],
        },
    )
    CHAT_SERVICE.update_state(thread_id, "FOLLOW_UP_UPDATE")
    return message_to_dict(msg)


@app.get("/api/agent/chat/{thread_id}/stream")
def chat_stream(
    thread_id: str,
    q: str = Query(..., description="user message"),
    desk: str = Query("research"),
    visible_asset_refs: list[str] | None = Query(None),
    permission_tags: list[str] | None = Query(None),
    projections: list[str] | None = Query(None),
    rag_search: str = Query("vector"),
    rag_top_k: int = Query(5, ge=1, le=10),
    current=Depends(current_user_dependency),
):
    """SSE：用户消息 → 流式输出 assistant tokens。

    简化版：LLM client 当前是同步整段返回，所以这里把整段分块输出模拟流式。
    v0.8.7 LLM client 升级支持真 streaming 后改成 token-by-token。
    """
    try:
        thread = CHAT_SERVICE.get_thread(thread_id)
    except ChatError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    research_rag_payload = {
        "desk": desk,
        "visible_asset_refs": visible_asset_refs or (),
        "permission_tags": permission_tags or (),
        "projections": projections or (),
        "rag_search": rag_search,
        "rag_top_k": rag_top_k,
        "agent_id": f"legacy-mode2-chat-stream:{thread_id}",
        "rag_purpose": "legacy_mode2_chat_stream_context",
    }
    research_rag_provider = _agent_shell_rag_context_provider(research_rag_payload, current)

    def event_stream():
        import json as _json
        user_text = q.strip()
        if not user_text:
            yield f"data: {_json.dumps({'error': 'empty content'})}\n\n"
            return
        CHAT_SERVICE.add_message(thread_id, "user", user_text)
        # RAG + LLM
        research_rag_context: AgentRAGContext | None = None
        if research_rag_provider is not None:
            try:
                research_rag_context = research_rag_provider(user_text)
            except AssetRAGError as exc:
                yield f"event: error\ndata: {_json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
                return
        run_data = None
        if thread.active_run_id:
            try:
                run_resp = get_run_response(thread.active_run_id)
                run_data = {
                    "run_id": thread.active_run_id,
                    **(run_resp.get("metrics") or {}),
                    **(run_resp.get("jq_overview_metrics") or {}),
                    "trust_level": (run_resp.get("risk_summary") or {}).get("trust_level"),
                }
            except FileNotFoundError:
                pass
        hits = retrieve(user_text, glossary=GLOSSARY, run_context=run_data)
        rag_text = format_rag_context(hits)
        research_rag_text = ""
        if research_rag_context is not None and research_rag_context.hits:
            research_rag_text = research_rag_context.prompt_context
        combined_rag_text = "\n\n".join(text for text in (rag_text, research_rag_text) if text)
        run_text = format_run_context(run_data)
        history_text = CHAT_SERVICE.compress_history(thread_id)
        sys_prompt = build_mode2_prompt(
            rag_context=combined_rag_text or rag_text,
            run_context=run_text,
            conversation_history=history_text,
        )
        # 给前端 RAG 命中预告
        yield f"event: rag\ndata: {_json.dumps({'hits': [{'kind': h.kind, 'slug': h.slug, 'title': h.title} for h in hits]})}\n\n"
        if research_rag_context is not None and research_rag_context.hits:
            yield (
                "event: research_rag\n"
                f"data: {_json.dumps({'hits': [hit.to_dict() for hit in research_rag_context.hits], 'usage_ids': list(research_rag_context.usage_ids)}, ensure_ascii=False)}\n\n"
            )

        from .agent.llm_client import LLMMessage
        full_text = ""
        try:
            client = _current_agent_llm()
            # v0.9.8 · 真 streaming - 调 stream_chat() iterator
            for token in client.stream_chat([
                LLMMessage(role="system", content=sys_prompt),
                LLMMessage(role="user", content=user_text),
            ]):
                full_text += token
                yield f"data: {_json.dumps({'chunk': token}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            err_text = f"[LLM 错误] {exc}"
            full_text = full_text or err_text
            yield f"data: {_json.dumps({'chunk': err_text, 'error': True}, ensure_ascii=False)}\n\n"

        # 持久化 + done
        research_asset_rag_hits = (
            [hit.to_dict() for hit in research_rag_context.hits]
            if research_rag_context is not None
            else []
        )
        research_asset_rag_usage_ids = (
            list(research_rag_context.usage_ids)
            if research_rag_context is not None
            else []
        )
        try:
            coverage_refs = _record_legacy_chat_message_entrypoint_coverage(
                entrypoint_ref="chat:legacy_mode2.chat.stream",
                actor="legacy_mode2_chat_stream",
                user_text=user_text,
                assistant_text=full_text,
                thread_id=thread_id,
                research_asset_rag_hits=research_asset_rag_hits,
                research_asset_rag_usage_ids=research_asset_rag_usage_ids,
                streamed=True,
            )
        except ValueError as exc:
            yield f"event: error\ndata: {_json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            return
        msg = CHAT_SERVICE.add_message(
            thread_id, "assistant", full_text,
            metadata={
                "rag_hits": [{"kind": h.kind, "slug": h.slug} for h in hits],
                "qro_ids": coverage_refs["qro_ids"],
                "research_graph_command_ids": coverage_refs["research_graph_command_ids"],
                "compiler_ir_refs": coverage_refs["compiler_ir_refs"],
                "compiler_pass_refs": coverage_refs["compiler_pass_refs"],
                "entrypoint_coverage_refs": coverage_refs["entrypoint_coverage_refs"],
                "research_asset_rag_hits": research_asset_rag_hits,
                "research_asset_rag_usage_ids": research_asset_rag_usage_ids,
                "streamed": True,
            },
        )
        CHAT_SERVICE.update_state(thread_id, "FOLLOW_UP_UPDATE")
        yield (
            "event: done\n"
            f"data: {_json.dumps({'message_id': msg.message_id, 'qro_ids': coverage_refs['qro_ids'], 'research_graph_command_ids': coverage_refs['research_graph_command_ids'], 'compiler_ir_refs': coverage_refs['compiler_ir_refs'], 'compiler_pass_refs': coverage_refs['compiler_pass_refs'], 'entrypoint_coverage_refs': coverage_refs['entrypoint_coverage_refs'], 'research_asset_rag_hits': research_asset_rag_hits, 'research_asset_rag_usage_ids': research_asset_rag_usage_ids}, ensure_ascii=False)}\n\n"
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/metrics/funnel")
def metrics_funnel() -> dict[str, Any]:
    """v0.8.5.1 · 漏斗 dashboard 用：事件总计 + 首次 run 耗时 bucket。"""

    import sqlite3
    db_path = _COMMUNITY_DB
    by_event: list[dict[str, Any]] = []
    first_run_buckets: list[dict[str, Any]] = []
    total = 0

    if db_path.exists():
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            try:
                rows = c.execute(
                    "SELECT event_name, COUNT(*) as cnt FROM events GROUP BY event_name ORDER BY cnt DESC"
                ).fetchall()
                by_event = [{"event_name": r["event_name"], "count": r["cnt"]} for r in rows]
                total = sum(x["count"] for x in by_event)
            except sqlite3.OperationalError:
                pass
            # 首次 run 耗时 bucket
            try:
                sql = """
                WITH registered AS (
                  SELECT user_id, MIN(datetime(occurred_at)) AS registered_at
                  FROM events WHERE event_name='user_registered' AND user_id IS NOT NULL GROUP BY user_id
                ),
                first_success_run AS (
                  SELECT user_id, MIN(datetime(occurred_at)) AS first_run_at
                  FROM events WHERE event_name='run_completed'
                  AND json_extract(properties,'$.status')='success'
                  AND user_id IS NOT NULL GROUP BY user_id
                ),
                delta AS (
                  SELECT r.user_id,
                         CAST((julianday(f.first_run_at)-julianday(r.registered_at))*24*60 AS INTEGER) AS minutes
                  FROM registered r JOIN first_success_run f ON r.user_id=f.user_id
                  WHERE f.first_run_at >= r.registered_at
                ),
                bucketed AS (
                  SELECT CASE
                    WHEN minutes < 5 THEN '00_<5min'
                    WHEN minutes < 15 THEN '01_5-15min'
                    WHEN minutes < 30 THEN '02_15-30min'
                    WHEN minutes < 60 THEN '03_30-60min'
                    WHEN minutes < 180 THEN '04_1-3h'
                    WHEN minutes < 1440 THEN '05_3-24h'
                    ELSE '06_>24h'
                  END AS bucket, COUNT(*) AS users FROM delta GROUP BY 1
                )
                SELECT bucket, users, ROUND(users*100.0/SUM(users) OVER (), 2) AS pct
                FROM bucketed ORDER BY bucket;
                """
                rows = c.execute(sql).fetchall()
                first_run_buckets = [
                    {"bucket": r["bucket"], "users": r["users"], "pct": r["pct"] or 0.0}
                    for r in rows
                ]
            except sqlite3.OperationalError:
                pass

    return {"total_events": total, "by_event": by_event, "first_run_buckets": first_run_buckets}


@app.get("/api/events/recent")
def events_recent(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    """调试 / 监控用：拉最近事件。"""

    return EVENT_SERVICE.recent(limit=limit)


@app.get("/api/glossary_meta")
def glossary_meta() -> dict[str, Any]:
    """词典统计：用于 RunDetail 风险卡片判断 'glossary 是否就绪'。"""

    summary = GLOSSARY.list_summary()
    by_category: dict[str, int] = {}
    by_level: dict[str, int] = {}
    for x in summary:
        by_category[x["category"]] = by_category.get(x["category"], 0) + 1
        by_level[x["level"]] = by_level.get(x["level"], 0) + 1
    related_violations = GLOSSARY.validate_related_closure()
    return {
        "count": len(summary),
        "by_category": by_category,
        "by_level": by_level,
        "related_closure_ok": not related_violations,
        "related_violations": related_violations[:10],  # 前 10 条便于调试
    }


# ════════════════════════════════════════════════════════════════════
# P2 · 模拟台 /api/paper/*（复用 PaperScheduler/PaperVenue/晋级判定/风险门，不重造）
# ════════════════════════════════════════════════════════════════════
@app.get("/api/paper/runs")
def paper_runs() -> dict[str, Any]:
    """模拟盘列表（侧栏 + 选择）。只读。"""

    _prime_all_pending_seeds()  # M7：列表首访惰性补 seed 净值（import 不阻塞）
    return {"runs": PAPER_DESK.list_runs()}


@app.post("/api/paper/runs")
def paper_register_run(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """注册一条模拟台 run（过裁决候选 → 可跑 run）并喂模拟 bars 跑出真净值。

    治理红线（绝不削弱）：
      · A股恒 paper：本端点只建模拟台 run，绝不下 live 单（A股 live_order 端点仍恒拒）。
      · 不绕审批：晋级仍走 INV-5 人工审批门（approver≠creator + 背书），本端点与晋级无关。
      · provider 数据源按市场分流【crypto 真捆样本回放 bundled_sample_replay / 无样本市场合成兜底 deterministic_sim_walk】——均为模拟，绝非实盘行情取数。
      · DS-4 testnet 真喂可选档（payload `testnet=true`，默认 off、crypto only）：配 Binance testnet key 时
        喂 testnet 公共实时 bar(binance_testnet_live)；无 key/连接失败 → 诚实回退兜底(fail-open 留痕，
        provider_kind=replay_fallback + degrade_reason)。testnet key 仅查名存在性**不进 LLM**、永走模拟撮合
        **不下 live 单**（R10/INV-3/D-T021-3）。回退态 source 绝不标 testnet（§3）。
    idempotent：同 run_id 重复 POST 不另造（复用既有 run），只重新 prime 出净值。
    """

    run_id = (payload.get("run_id") or "").strip()
    if not run_id:
        raise HTTPException(422, detail={"reason": "run_id 必填（不对幽灵 run 开模拟台）"})
    record = {"run_id": run_id, "name": (payload.get("name") or run_id).strip()}
    paper = _register_candidate_paper_run(record, payload, creator=getattr(user, "user_id", "system"))
    # H4/H3：注册失败带显式 error（市场判不出/二次冲突/异常）——不静默假成功、不对未建 run 取 status。
    if paper is None or not paper.get("registered"):
        reason = (paper or {}).get("error") or "模拟台注册失败（见服务日志）"
        raise HTTPException(422, detail={"reason": reason, "register": paper})
    return {"run": PAPER_DESK.status(run_id), "register": paper}


@app.get("/api/paper/runs/{run_id}/status")
def paper_status(run_id: str) -> dict[str, Any]:
    """调度器状态 + 配置 + 余额/持仓（直映 PaperSchedulerState.snapshot）。"""

    _prime_pending_seed(run_id)  # M7：首访该 seed 惰性补净值
    try:
        return PAPER_DESK.status(run_id)
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc


@app.post("/api/paper/runs/{run_id}/start")
def paper_start(run_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """启动调度器线程（喂 bar + MTM 时钟）。"""

    try:
        return PAPER_DESK.start(run_id)
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc


@app.post("/api/paper/runs/{run_id}/stop")
def paper_stop(run_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """停止调度器（join 线程）。"""

    try:
        return PAPER_DESK.stop(run_id)
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc


@app.get("/api/paper/runs/{run_id}/positions")
def paper_positions(run_id: str) -> dict[str, Any]:
    """持仓表（来自 PaperVenue 单一持仓源 + MTM）。"""

    _prime_pending_seed(run_id)  # M7：首访该 seed 惰性补净值
    try:
        return {"positions": PAPER_DESK.positions(run_id)}
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc


@app.get("/api/paper/runs/{run_id}/balance")
def paper_balance(run_id: str) -> dict[str, Any]:
    """余额条（总权益/可用现金/持仓市值/冻结）。"""

    _prime_pending_seed(run_id)  # M7：首访该 seed 惰性补净值
    try:
        return PAPER_DESK.balance(run_id)
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc


@app.get("/api/paper/runs/{run_id}/fills")
def paper_fills(run_id: str) -> dict[str, Any]:
    """成交回报：从 ExecutionAuditLog(paper_fill) 派生（不另存第二份）。"""

    _prime_pending_seed(run_id)  # M7：首访该 seed 惰性补净值
    try:
        return {"fills": PAPER_DESK.fills(run_id)}
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc


@app.get("/api/paper/runs/{run_id}/equity_log")
def paper_equity_log(run_id: str) -> dict[str, Any]:
    """净值曲线：读 mark_to_market 写的 JSONL（每收盘一笔）。"""

    _prime_pending_seed(run_id)  # M7：首访该 seed 惰性补净值
    try:
        return {"equity_log": PAPER_DESK.equity_log(run_id)}
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc


@app.get("/api/paper/runs/{run_id}/risk_gate")
def paper_risk_gate(run_id: str) -> dict[str, Any]:
    """风险门：发布冻结哈希 + append-only 违规链 + 链完整性自证（会话外不可改的证据）。"""

    try:
        PAPER_DESK.get(run_id)
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc
    return {
        "run_id": run_id,
        "frozen_hash": PAPER_DESK.risk.frozen_hash(run_id),
        "limits": PAPER_DESK.risk._limits.get(run_id, {}),  # noqa: SLF001  发布快照（只读）
        "violation_count": PAPER_DESK.risk.violation_count(run_id),
        "chain": PAPER_DESK.risk.chain(run_id),
        "chain_intact": PAPER_DESK.risk.verify_chain(run_id),
        "disclosure": "本地门=防篡改证据、非防篡改；唯一硬墙在交易所侧远程信任域。",
    }


@app.post("/api/paper/runs/{run_id}/risk_gate/mutate")
def paper_risk_gate_mutate(run_id: str, payload: dict = Body(default_factory=dict),
                           user=Depends(require_user_dependency)) -> dict[str, Any]:
    """会话内改门请求：恒拒（会话外不可改）并入哈希链。返 409（绝不真改门）。"""

    try:
        PAPER_DESK.risk.attempt_mutation(run_id, payload, actor=getattr(user, "user_id", "session"))
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc
    except RiskGateMutationForbidden as exc:
        raise HTTPException(409, detail={
            "risk_gate_frozen": True, "reason": str(exc),
            "chain_intact": PAPER_DESK.risk.verify_chain(run_id),
        }) from exc
    raise HTTPException(500, "改门未被拒——治理门失效（不可达）")  # pragma: no cover


@app.post("/api/paper/runs/{run_id}/live_order")
def paper_live_order(run_id: str, payload: dict = Body(default_factory=dict),
                     user=Depends(require_user_dependency)) -> dict[str, Any]:
    """A股 live 下单：永远拒绝（致命错误防线）。crypto live 不在本模拟台域（走 BinanceTrading）。"""

    try:
        PAPER_DESK.attempt_live_order(run_id, payload)
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc
    except AShareLiveForbidden as exc:
        raise HTTPException(403, detail={"a_share_live_forbidden": True, "reason": str(exc)}) from exc
    raise HTTPException(403, detail={  # crypto 也不从模拟台下 live 单
        "live_order_not_supported_here": True,
        "reason": "模拟台止于 paper；crypto live 走真钱阶梯页（testnet→mainnet），不在此端点。",
    })


@app.get("/api/paper/runs/{run_id}/promotion")
def paper_promotion_status(run_id: str) -> dict[str, Any]:
    """晋级判定聚合（4 门只读派生）：≥28 天 / 模拟段超额>0 / 风险门 0 违规 / 实盘衰减<阈值。"""

    try:
        return PAPER_DESK.promotion_status(run_id)
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc


@app.post("/api/paper/runs/{run_id}/promotion/open")
def paper_promotion_open(run_id: str, payload: dict = Body(default_factory=dict),
                         user=Depends(require_user_dependency)) -> dict[str, Any]:
    """开晋级判定门（pending）。仅判定+落门，绝不翻态——晋级是后续显式人工动作。"""

    try:
        gate = PAPER_DESK.open_promotion_gate(run_id, creator=payload.get("creator") or user.user_id)
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"paper run 不存在: {run_id}") from exc
    return gate.to_dict()


@app.post("/api/paper/promotion/{gate_id}/approve")
def paper_promotion_approve(gate_id: str, payload: dict = Body(...),
                            user=Depends(require_user_dependency)) -> dict[str, Any]:
    """人工审批晋级（INV-5）：approver≠creator + 验证背书(endorsement_ref) + 4 门全过 + 理由。

    裸翻（无背书）必拒；自审（approver==creator）必拒；不可跳级（判定门未全过）必拒。
    Agent 永不自动晋级——本端点是显式人工动作，且晋级工具永不注册进 agent 工具集。
    """

    from .approval import ApproverEqualsCreator, EmptyReason, GateStateError

    try:
        gate = PAPER_DESK.approve_promotion(
            gate_id, approver=payload.get("approver") or user.user_id,
            endorsement_ref=payload.get("endorsement_ref"),
            reason=payload.get("reason", ""),
        )
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"晋级门不存在: {gate_id}") from exc
    except ApproverEqualsCreator as exc:
        raise HTTPException(422, detail={"approver_equals_creator": True, "reason": str(exc)}) from exc
    except EmptyReason as exc:
        raise HTTPException(422, detail={"endorsement_or_reason_missing": True, "reason": str(exc)}) from exc
    except GateStateError as exc:
        raise HTTPException(422, detail={"gate_not_eligible": True, "reason": str(exc)}) from exc
    return gate.to_dict()


@app.get("/api/paper/promotion/{gate_id}")
def paper_promotion_gate(gate_id: str) -> dict[str, Any]:
    """晋级门状态下钻（判定/审批/背书）。"""

    try:
        return PAPER_DESK.get_promotion_gate(gate_id).to_dict()
    except PaperRunNotFound as exc:
        raise HTTPException(404, f"晋级门不存在: {gate_id}") from exc
