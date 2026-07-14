"""GOAL §1/§6/§8 runtime spine contracts.

The module is intentionally small and strict:
- all formal assets become QRO records with separated status axes;
- canvas/chat/API/IDE/scheduler writes enter as versioned Research Graph commands;
- theory-backed claims require TheoryImplementationBinding + ConsistencyCheck;
- user methodology waivers are recorded and cannot be promoted as strong proof.

It does not claim to complete the whole GOAL. It gives later desks and endpoints
one shared runtime contract instead of ad hoc status booleans.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..lineage.ids import content_hash
from ..lineage.spine import (
    ConsistencyCheck as SpineConsistencyCheck,
    MathematicalSpineChainRecord as CanonicalMathematicalSpineChainRecord,
    MathematicalArtifact as SpineMathematicalArtifact,
    MethodologyChoiceRecord as SpineMethodologyChoiceRecord,
    TheoryImplementationBinding as SpineTheoryImplementationBinding,
    canonical_mathematical_spine_chain_ref as canonical_lineage_chain_ref,
    mathematical_spine_chain_from_dict as lineage_chain_from_dict,
)
from ..lineage.spine_ledger import SpineLedger
from ..cross_process_lock import acquire_exclusive_fd
from .canvas_layout import CanvasLayoutRecord, validate_canvas_layout_record
from .desk_projection import CanvasMutationRecord


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _require_text(value: str, field_name: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"{field_name} is required")


def _require_tuple(value: tuple[Any, ...], field_name: str) -> None:
    if not value:
        raise ValueError(f"{field_name} is required")


def _stable_for_hash(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _stable_for_hash(asdict(value))
    if isinstance(value, dict):
        return {str(k): _stable_for_hash(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stable_for_hash(v) for v in value]
    return value


def _enum_text(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value)


# ── SA-4 占位种子 write门 ──────────────────────────────────────────────────────
# 已移除的 "goal closure" 闭合 materializer 曾往运行时账本（mathematical_spine_chains.jsonl /
# research_graph_commands.jsonl）播种自证闭合的占位记录，使纯解析检查可被骗过
# （见 platform_coverage._PLACEHOLDER_TOKENS 的 goal_closure 项）。这些 token 是自证闭合
# 占位、不是真持久化对象的 id。下面的 write门在**写路径**fail-closed 掉新种子；既存残留行由
# scripts/purge_goal_closure_seeds.py 清理（中心在 main 数据目录跑）。
# 故意只覆盖 goal_closure 族（不含 synthetic/fixture 等更宽的 platform_coverage 项），避免误伤
# 合法 synthetic 测试 ref；按子串小写匹配，goal_closure / goal-closure / goalclosure（任意大小写）全抓。
_GOAL_CLOSURE_SEED_TOKENS: tuple[str, ...] = ("goal_closure", "goal-closure", "goalclosure")


def _carries_goal_closure_seed(serialized: str) -> bool:
    """True 当序列化后的 id/内容携带任一 goal_closure 占位 token（大小写不敏感子串）。"""

    lowered = serialized.lower()
    return any(token in lowered for token in _GOAL_CLOSURE_SEED_TOKENS)


class ResearchGraphError(ValueError):
    """Research Graph command or guard rejected a mutation."""


class ResearchGraphDurabilityError(ResearchGraphError):
    """A failed append could not be rolled back to a known durable boundary."""


_RESEARCH_GRAPH_PROCESS_WRITE_LOCK = threading.RLock()
_PLATFORM_IMMUTABLE_BINDING_ENTRYPOINT_PREFIXES = (
    "api:research_os.platform.spine_bindings.",
    "api:research_os.platform.business_attestations.",
)


@contextmanager
def _persistent_research_graph_write_lock(path: Path):
    """Serialize refresh/check/append for every writer of one Graph log."""

    with _RESEARCH_GRAPH_PROCESS_WRITE_LOCK:
        lock_path = Path(str(path) + ".write.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)


class QROType(str, Enum):
    QUANT_INTENT = "QuantIntent"
    DATASET = "Dataset"
    OBSERVABLE = "Observable"
    DATA_SOURCE_ASSET = "DataSourceAsset"
    INTEGRATION_CONFIG = "IntegrationConfig"
    SECRET_REF = "SecretRef"
    TOKEN_REF = "TokenRef"
    INGESTION_SKILL = "IngestionSkill"
    DATASET_VERSION = "DatasetVersion"
    FRESHNESS_STATUS = "FreshnessStatus"
    SCHEMA_DRIFT_EVENT = "SchemaDriftEvent"
    THEORY_SPEC = "TheorySpec"
    MATHEMATICAL_REQUIREMENT = "MathematicalRequirement"
    THEORY_IMPLEMENTATION_BINDING = "TheoryImplementationBinding"
    CONSISTENCY_CHECK = "ConsistencyCheck"
    METHODOLOGY_CHOICE_RECORD = "MethodologyChoiceRecord"
    RESPONSIBILITY_DISCLOSURE_RECORD = "ResponsibilityDisclosureRecord"
    LLM_PROVIDER = "LLMProvider"
    LLM_PROVIDER_AUTH = "LLMProviderAuth"
    LLM_CREDENTIAL_POOL = "LLMCredentialPool"
    LLM_MODEL_PROFILE = "LLMModelProfile"
    MODEL_ROUTING_POLICY = "ModelRoutingPolicy"
    LLM_CALL_RECORD = "LLMCallRecord"
    PROVIDER_HEALTH = "ProviderHealth"
    PROVIDER_QUOTA_STATUS = "ProviderQuotaStatus"
    FACTOR = "Factor"
    LABEL = "Label"
    MODEL = "Model"
    FORECAST = "Forecast"
    SIGNAL = "Signal"
    STRATEGY_BOOK = "StrategyBook"
    PORTFOLIO_POLICY = "PortfolioPolicy"
    RISK_POLICY = "RiskPolicy"
    EXECUTION_POLICY = "ExecutionPolicy"
    EXPERIMENT = "Experiment"
    BACKTEST_RUN = "BacktestRun"
    VALIDATION_DOSSIER = "ValidationDossier"
    RESEARCH_REPORT = "ResearchReport"
    DESK_HANDOFF = "DeskHandoff"
    MARKET_CAPABILITY_MATRIX = "MarketCapabilityMatrix"
    MATHEMATICAL_ARTIFACT = "MathematicalArtifact"
    DOCUMENT_ARTIFACT = "DocumentArtifact"


class ActorSource(str, Enum):
    USER_MANUAL = "user_manual"
    AGENT = "agent"
    USER_CONFIRMED_AGENT = "user_confirmed_agent"
    SCHEDULED_AGENT = "scheduled_agent"


class EntrySource(str, Enum):
    CHAT = "chat"
    CANVAS = "canvas"
    API = "api"
    IDE = "ide"
    SCHEDULER = "scheduler"
    AGENT_SHELL = "agent_shell"


class DefinitionStatus(str, Enum):
    DRAFT = "draft"
    SPECIFIED = "specified"
    IMPLEMENTED = "implemented"


class TheoryStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    DRAFTED = "drafted"
    DERIVED = "derived"
    CHALLENGED = "challenged"
    ACCEPTED = "accepted"
    USER_WAIVED = "user_waived"


class ConsistencyStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    UNBOUND = "unbound"
    CHECKED = "checked"
    MISMATCH = "mismatch"
    ACCEPTED = "accepted"
    WAIVED_FOR_EXPLORATORY = "waived_for_exploratory"


class EvidenceStatus(str, Enum):
    UNTESTED = "untested"
    EXPLORATORY = "exploratory"
    CHALLENGED = "challenged"
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    UNVERIFIED_RESIDUAL = "unverified_residual"


class GovernanceStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class RuntimeStatus(str, Enum):
    OFFLINE = "offline"
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class MethodologyPath(str, Enum):
    STRICT = "strict"
    STANDARD = "standard"
    LOOSE = "loose"
    EXPLORATORY = "exploratory"
    CUSTOM = "custom"
    USER_WAIVED = "user_waived"
    USER_WAIVED_THEORY = "user_waived_theory"
    USER_WAIVED_VALIDATION = "user_waived_validation"


class PromotionLabel(str, Enum):
    PROOF_BACKED = "proof_backed"
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    PRODUCTION_READY = "production_ready"


@dataclass(frozen=True)
class MethodologyChoiceRecord:
    asset_ref: str | None
    run_ref: str | None
    chosen_path: MethodologyPath | str
    available_options: tuple[str, ...]
    recommendation: str
    tradeoffs_shown: tuple[str, ...]
    risks_shown: tuple[str, ...]
    responsibility_boundary: str
    actor: ActorSource | str
    allowed_environment: RuntimeStatus | str
    skipped_steps: tuple[str, ...] = ()
    display_label: str = ""
    timestamp: str = field(default_factory=_now)
    choice_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "available_options", tuple(self.available_options))
        object.__setattr__(self, "tradeoffs_shown", tuple(self.tradeoffs_shown))
        object.__setattr__(self, "risks_shown", tuple(self.risks_shown))
        object.__setattr__(self, "skipped_steps", tuple(self.skipped_steps))
        _require_tuple(self.available_options, "available_options")
        _require_text(self.recommendation, "recommendation")
        _require_tuple(self.tradeoffs_shown, "tradeoffs_shown")
        _require_tuple(self.risks_shown, "risks_shown")
        _require_text(self.responsibility_boundary, "responsibility_boundary")
        path = str(self.chosen_path.value if isinstance(self.chosen_path, Enum) else self.chosen_path)
        if path.startswith("user_waived") and not self.skipped_steps:
            raise ValueError("user-waived methodology must record skipped_steps")
        if not self.choice_id:
            object.__setattr__(
                self,
                "choice_id",
                "mchoice_" + content_hash(
                    {
                        "asset_ref": self.asset_ref,
                        "run_ref": self.run_ref,
                        "chosen_path": path,
                        "available_options": self.available_options,
                        "recommendation": self.recommendation,
                        "tradeoffs_shown": self.tradeoffs_shown,
                        "risks_shown": self.risks_shown,
                        "responsibility_boundary": self.responsibility_boundary,
                        "actor": str(self.actor.value if isinstance(self.actor, Enum) else self.actor),
                        "allowed_environment": str(
                            self.allowed_environment.value
                            if isinstance(self.allowed_environment, Enum)
                            else self.allowed_environment
                        ),
                        "skipped_steps": self.skipped_steps,
                    }
                ),
            )

    @property
    def is_user_waiver(self) -> bool:
        path = str(self.chosen_path.value if isinstance(self.chosen_path, Enum) else self.chosen_path)
        return path.startswith("user_waived")


@dataclass(frozen=True)
class ResponsibilityDisclosureRecord:
    asset_ref: str | None
    run_ref: str | None
    responsibility_boundary: str
    risks_disclosed: tuple[str, ...]
    actor: ActorSource | str
    timestamp: str = field(default_factory=_now)
    disclosure_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "risks_disclosed", tuple(self.risks_disclosed))
        _require_text(self.responsibility_boundary, "responsibility_boundary")
        _require_tuple(self.risks_disclosed, "risks_disclosed")
        if not self.disclosure_id:
            object.__setattr__(
                self,
                "disclosure_id",
                "resp_" + content_hash(
                    {
                        "asset_ref": self.asset_ref,
                        "run_ref": self.run_ref,
                        "responsibility_boundary": self.responsibility_boundary,
                        "risks_disclosed": self.risks_disclosed,
                        "actor": str(self.actor.value if isinstance(self.actor, Enum) else self.actor),
                    }
                ),
            )


@dataclass(frozen=True)
class MathematicalArtifact:
    artifact_type: str
    notation: str
    assumptions: tuple[str, ...]
    definition: str
    statement: str
    derivation: str
    proof_sketch: str
    counterexamples: tuple[str, ...]
    units_dimensions: str
    applicability: str
    failure_conditions: tuple[str, ...]
    implementation_ref: str | None = None
    test_ref: str | None = None
    simulation_ref: str | None = None
    validation_ref: str | None = None
    used_by: tuple[str, ...] = ()
    artifact_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "counterexamples", tuple(self.counterexamples))
        object.__setattr__(self, "failure_conditions", tuple(self.failure_conditions))
        object.__setattr__(self, "used_by", tuple(self.used_by))
        _require_text(self.artifact_type, "artifact_type")
        _require_tuple(self.assumptions, "assumptions")
        _require_text(self.definition, "definition")
        _require_text(self.applicability, "applicability")
        _require_tuple(self.failure_conditions, "failure_conditions")
        if not self.artifact_id:
            object.__setattr__(
                self,
                "artifact_id",
                "math_" + content_hash(
                    {
                        "artifact_type": self.artifact_type,
                        "notation": self.notation,
                        "definition": self.definition,
                        "statement": self.statement,
                        "assumptions": self.assumptions,
                        "applicability": self.applicability,
                    }
                ),
            )


@dataclass(frozen=True)
class ConsistencyCheck:
    binding_id: str
    check_type: str
    input_refs: tuple[str, ...]
    expected_property: str
    observed_property: str
    result: ConsistencyStatus | str
    affected_assets: tuple[str, ...]
    verifier_ref: str
    tolerance: str | None = None
    failure_reason: str = ""
    repair_plan: str = ""
    timestamp: str = field(default_factory=_now)
    check_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_refs", tuple(self.input_refs))
        object.__setattr__(self, "affected_assets", tuple(self.affected_assets))
        _require_text(self.binding_id, "binding_id")
        _require_text(self.check_type, "check_type")
        _require_tuple(self.input_refs, "input_refs")
        _require_text(self.expected_property, "expected_property")
        _require_text(self.observed_property, "observed_property")
        _require_text(self.verifier_ref, "verifier_ref")
        if str(self.result.value if isinstance(self.result, Enum) else self.result) == ConsistencyStatus.MISMATCH.value:
            _require_text(self.failure_reason, "failure_reason")
        if not self.check_id:
            object.__setattr__(
                self,
                "check_id",
                "ccheck_" + content_hash(
                    {
                        "binding_id": self.binding_id,
                        "check_type": self.check_type,
                        "input_refs": self.input_refs,
                        "expected_property": self.expected_property,
                        "observed_property": self.observed_property,
                        "result": str(self.result.value if isinstance(self.result, Enum) else self.result),
                        "verifier_ref": self.verifier_ref,
                    }
                ),
            )

    @property
    def accepted(self) -> bool:
        value = str(self.result.value if isinstance(self.result, Enum) else self.result)
        return value in {ConsistencyStatus.ACCEPTED.value, ConsistencyStatus.CHECKED.value}


@dataclass(frozen=True)
class TheoryImplementationBinding:
    theory_ref: str
    implementation_ref: str
    implementation_spec: str
    code_ref: str
    config_ref: str
    data_contract_ref: str
    test_refs: tuple[str, ...]
    simulation_refs: tuple[str, ...]
    numerical_check_refs: tuple[str, ...]
    symbol_mapping: dict[str, str]
    unit_mapping: dict[str, str]
    dimension_check: str
    tolerance: str
    known_differences: tuple[str, ...]
    consistency_verdict: ConsistencyStatus | str
    verifier_ref: str
    waiver_ref: str | None = None
    used_by: tuple[str, ...] = ()
    binding_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_refs", tuple(self.test_refs))
        object.__setattr__(self, "simulation_refs", tuple(self.simulation_refs))
        object.__setattr__(self, "numerical_check_refs", tuple(self.numerical_check_refs))
        object.__setattr__(self, "known_differences", tuple(self.known_differences))
        object.__setattr__(self, "used_by", tuple(self.used_by))
        _require_text(self.theory_ref, "theory_ref")
        _require_text(self.implementation_ref, "implementation_ref")
        _require_text(self.code_ref, "code_ref")
        _require_text(self.config_ref, "config_ref")
        _require_text(self.data_contract_ref, "data_contract_ref")
        _require_tuple(self.test_refs, "test_refs")
        _require_text(self.dimension_check, "dimension_check")
        _require_text(self.verifier_ref, "verifier_ref")
        if not self.binding_id:
            object.__setattr__(
                self,
                "binding_id",
                "tbind_" + content_hash(
                    {
                        "theory_ref": self.theory_ref,
                        "implementation_ref": self.implementation_ref,
                        "code_ref": self.code_ref,
                        "config_ref": self.config_ref,
                        "data_contract_ref": self.data_contract_ref,
                        "symbol_mapping": self.symbol_mapping,
                        "unit_mapping": self.unit_mapping,
                    }
                ),
            )

    @property
    def accepted(self) -> bool:
        value = str(self.consistency_verdict.value if isinstance(self.consistency_verdict, Enum) else self.consistency_verdict)
        return value == ConsistencyStatus.ACCEPTED.value


MathematicalSpineChainRecord = CanonicalMathematicalSpineChainRecord


@dataclass(frozen=True)
class MathematicalSpineChainViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class MathematicalSpineChainDecision:
    accepted: bool
    violations: tuple[MathematicalSpineChainViolation, ...]


def _chain_required_text(
    violations: list[MathematicalSpineChainViolation],
    *,
    record: MathematicalSpineChainRecord,
    field_name: str,
) -> None:
    if not str(getattr(record, field_name, "") or "").strip():
        violations.append(
            MathematicalSpineChainViolation(
                "mathematical_spine_chain_required_ref_missing",
                f"{field_name} is required for full-chain Mathematical Spine records",
                field=field_name,
                ref=record.chain_ref,
            )
        )


def _chain_required_tuple(
    violations: list[MathematicalSpineChainViolation],
    *,
    record: MathematicalSpineChainRecord,
    field_name: str,
) -> None:
    if not getattr(record, field_name):
        violations.append(
            MathematicalSpineChainViolation(
                "mathematical_spine_chain_required_ref_missing",
                f"{field_name} is required for full-chain Mathematical Spine records",
                field=field_name,
                ref=record.chain_ref,
            )
        )


def validate_mathematical_spine_chain(record: MathematicalSpineChainRecord) -> MathematicalSpineChainDecision:
    violations: list[MathematicalSpineChainViolation] = []
    for field_name in (
        "chain_ref",
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
        "methodology_choice_ref",
        "responsibility_boundary_ref",
        "recorded_by",
    ):
        _chain_required_text(violations, record=record, field_name=field_name)
    for field_name in ("theory_binding_refs", "consistency_check_refs", "evidence_refs", "validation_refs"):
        _chain_required_tuple(violations, record=record, field_name=field_name)
    verdict = str(
        record.consistency_verdict.value
        if isinstance(record.consistency_verdict, Enum)
        else record.consistency_verdict
    )
    if verdict not in {ConsistencyStatus.ACCEPTED.value, ConsistencyStatus.CHECKED.value}:
        violations.append(
            MathematicalSpineChainViolation(
                "mathematical_spine_chain_consistency_not_accepted",
                "full-chain Mathematical Spine records require checked or accepted consistency",
                field="consistency_verdict",
                ref=record.chain_ref,
            )
        )
    if record.silent_mock_fallback_used:
        violations.append(
            MathematicalSpineChainViolation(
                "mathematical_spine_chain_silent_mock_fallback",
                "full-chain Mathematical Spine records cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=record.chain_ref,
            )
        )
    return MathematicalSpineChainDecision(accepted=not violations, violations=tuple(violations))


def mathematical_spine_chain_from_dict(data: dict[str, Any]) -> MathematicalSpineChainRecord:
    return lineage_chain_from_dict(data)


def _chain_decision_message(decision: MathematicalSpineChainDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "mathematical spine chain rejected"


def _chain_event_row(
    record: MathematicalSpineChainRecord,
    *,
    schema_version: int = 2,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "event_type": "mathematical_spine_chain_recorded",
        "chain": _stable_for_hash(record),
    }


def canonical_mathematical_spine_chain_ref(
    record: MathematicalSpineChainRecord,
) -> str:
    return canonical_lineage_chain_ref(record)


class PersistentMathematicalSpineChainRegistry:
    """Append-only chain projection backed by the canonical Spine ledger."""

    def __init__(
        self,
        path: str | Path,
        spine_ledger: SpineLedger | None = None,
        *,
        external_ref_resolver: Callable[[str, str, str], bool] | None = None,
        current_hash_resolver: Callable[[str, str, str], str | None] | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._spine_ledger = spine_ledger
        self._external_ref_resolver = external_ref_resolver
        self._current_hash_resolver = current_hash_resolver
        self._chains: dict[str, MathematicalSpineChainRecord] = {}
        if self._spine_ledger is not None:
            self._chains = {
                record.chain_ref: record for record in self._spine_ledger.chains()
            }
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if self._spine_ledger is None:
                        self._apply_row(row, persist=False)
                        continue
                    if row.get("schema_version") != 2:
                        raise ValueError(
                            "legacy Mathematical Spine chain schema requires explicit quarantine/migration"
                        )
                    raw = row.get("chain")
                    if not isinstance(raw, dict):
                        raise ValueError("Mathematical Spine chain event missing chain")
                    projected = mathematical_spine_chain_from_dict(raw)
                    canonical = self._spine_ledger.chain(
                        projected.chain_ref,
                        owner=projected.recorded_by,
                    )
                    if canonical != projected:
                        raise ValueError(
                            "Mathematical Spine JSONL projection differs from canonical SQLite"
                        )
                except Exception as exc:  # noqa: BLE001 - bad spine history must block startup.
                    raise ValueError(f"invalid persisted Mathematical Spine chain at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def set_resolvers(
        self,
        *,
        external_ref_resolver: Callable[[str, str, str], bool] | None,
        current_hash_resolver: Callable[[str, str, str], str | None] | None,
    ) -> None:
        self._external_ref_resolver = external_ref_resolver
        self._current_hash_resolver = current_hash_resolver

    def _strict_decision(self, record: MathematicalSpineChainRecord):
        if self._spine_ledger is None:
            raise ValueError("canonical Mathematical Spine ledger is unavailable")
        return self._spine_ledger.validate_chain_backing(
            record,
            owner=record.recorded_by,
            external_ref_resolver=self._external_ref_resolver,
            current_hash_resolver=self._current_hash_resolver,
        )

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> MathematicalSpineChainRecord:
        schema_version = row.get("schema_version")
        if schema_version not in {1, 2}:
            raise ValueError("unsupported Mathematical Spine chain schema_version")
        if row.get("event_type") != "mathematical_spine_chain_recorded":
            raise ValueError(f"unknown Mathematical Spine chain event_type={row.get('event_type')!r}")
        raw = row.get("chain")
        if not isinstance(raw, dict):
            raise ValueError("Mathematical Spine chain event missing chain")
        record = mathematical_spine_chain_from_dict(raw)
        decision = validate_mathematical_spine_chain(record)
        if not decision.accepted:
            raise ValueError(_chain_decision_message(decision))
        if schema_version == 2 and record.chain_ref != canonical_mathematical_spine_chain_ref(record):
            residual_goal_closure = (
                not persist
                and self._spine_ledger is None
                and _carries_goal_closure_seed(
                    json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                )
            )
            if not residual_goal_closure:
                raise ValueError("Mathematical Spine chain identity mismatch")
        existing = self._chains.get(record.chain_ref)
        if existing is not None:
            if existing != record:
                raise ValueError("Mathematical Spine chain identity collision")
            return existing
        if persist:
            self._append_event(
                _chain_event_row(record, schema_version=int(schema_version))
            )
        self._chains[record.chain_ref] = record
        return record

    def record_chain(self, record: MathematicalSpineChainRecord) -> MathematicalSpineChainRecord:
        if self._spine_ledger is not None:
            record = replace(
                record,
                chain_ref="",
                consistency_verdict=ConsistencyStatus.ACCEPTED.value,
            )
            record = replace(
                record,
                chain_ref=canonical_mathematical_spine_chain_ref(record),
            )
            strict = self._strict_decision(record)
            if not strict.accepted:
                raise ValueError(
                    "; ".join(
                        f"{violation.code}:{violation.field}:{violation.ref}"
                        for violation in strict.violations
                    )
                )
        row = _chain_event_row(
            record,
            schema_version=2 if self._spine_ledger is not None else 1,
        )
        # SA-4 write门：拒任何 id/内容携 goal_closure 占位 token 的链（自证闭合种子≠真绑定）。
        # 扫描的是即将持久化的整行（含每个 ref 字段），故 token 藏在任一字段都抓得到。fail-closed。
        if _carries_goal_closure_seed(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)):
            raise ValueError(
                "mathematical spine chain rejected: goal_closure placeholder seed is not a real "
                "Mathematical Spine binding (SA-4 write門 fail-closes self-certifying closure seeds)"
            )
        if self._spine_ledger is not None:
            persisted = self._spine_ledger.record_chain(
                record,
                owner=record.recorded_by,
            )
            self._chains[persisted.chain_ref] = persisted
            return persisted
        return self._apply_row(row, persist=True)

    def chain(self, chain_ref: str) -> MathematicalSpineChainRecord:
        if self._spine_ledger is not None:
            return self._spine_ledger.chain(chain_ref)
        return self._chains[chain_ref]

    def verified_chain(
        self,
        chain_ref: str,
        *,
        owner: str | None = None,
    ) -> MathematicalSpineChainRecord:
        record = self.chain(chain_ref)
        if record.chain_ref != chain_ref:
            raise KeyError(chain_ref)
        if owner is not None and record.recorded_by != owner:
            raise KeyError(chain_ref)
        strict = self._strict_decision(record)
        if not strict.accepted:
            raise ValueError(
                "; ".join(
                    f"{violation.code}:{violation.field}:{violation.ref}"
                    for violation in strict.violations
                )
            )
        return record

    def verified_chain_record_refs(
        self,
        chain_ref: str,
        *,
        owner: str,
    ):
        """Return the canonical typed record closure for a currently verified chain."""

        record = self.verified_chain(chain_ref, owner=owner)
        if self._spine_ledger is None:
            raise ValueError("canonical Mathematical Spine ledger is unavailable")
        return self._spine_ledger.chain_record_refs(record, owner=owner)

    def chains(self, *, owner: str | None = None) -> list[MathematicalSpineChainRecord]:
        if self._spine_ledger is not None:
            return self._spine_ledger.chains(owner=owner)
        records = list(self._chains.values())
        if owner is not None:
            records = [record for record in records if record.recorded_by == owner]
        return records


@dataclass(frozen=True)
class QRORecord:
    qro_type: QROType | str
    owner: str
    actor: ActorSource | str
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]
    market: str
    universe: str
    horizon: str
    frequency: str
    lineage: tuple[str, ...]
    implementation_hash: str
    assumptions: tuple[str, ...]
    known_limits: tuple[str, ...]
    failure_modes: tuple[str, ...]
    validation_plan: tuple[str, ...]
    definition_status: DefinitionStatus | str = DefinitionStatus.DRAFT
    theory_status: TheoryStatus | str = TheoryStatus.NOT_REQUIRED
    consistency_status: ConsistencyStatus | str = ConsistencyStatus.NOT_APPLICABLE
    evidence_status: EvidenceStatus | str = EvidenceStatus.UNTESTED
    governance_status: GovernanceStatus | str = GovernanceStatus.UNREVIEWED
    runtime_status: RuntimeStatus | str = RuntimeStatus.OFFLINE
    event_time: str | None = None
    known_at: str | None = None
    effective_at: str | None = None
    evidence_refs: tuple[str, ...] = ()
    mathematical_refs: tuple[str, ...] = ()
    methodology_choice_ref: str | None = None
    responsibility_boundary: str = ""
    theory_implementation_binding: str | None = None
    consistency_verdict: ConsistencyStatus | str = ConsistencyStatus.NOT_APPLICABLE
    verdict: str = ""
    permission: str = ""
    approval: str = ""
    allowed_environment: RuntimeStatus | str = RuntimeStatus.OFFLINE
    monitor_rules: tuple[str, ...] = ()
    qro_id: str = ""
    version: int = 1
    mock_profile: str = "none"

    def __post_init__(self) -> None:
        # QRO contracts cross the append-only JSONL boundary.  Canonicalize
        # them at construction time so the in-memory command and its replayed
        # durable form have the same nested sequence/enumeration shape.  A
        # tuple otherwise becomes a list during JSON decoding and makes an
        # unchanged command fail the exact-current-head equality check after
        # ``PersistentResearchGraphStore.refresh()``.
        object.__setattr__(
            self,
            "input_contract",
            _stable_for_hash(dict(self.input_contract)),
        )
        object.__setattr__(
            self,
            "output_contract",
            _stable_for_hash(dict(self.output_contract)),
        )
        object.__setattr__(self, "lineage", tuple(self.lineage))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "known_limits", tuple(self.known_limits))
        object.__setattr__(self, "failure_modes", tuple(self.failure_modes))
        object.__setattr__(self, "validation_plan", tuple(self.validation_plan))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "mathematical_refs", tuple(self.mathematical_refs))
        object.__setattr__(self, "monitor_rules", tuple(self.monitor_rules))
        _require_text(self.owner, "owner")
        _require_text(self.market, "market")
        _require_text(self.frequency, "frequency")
        _require_tuple(self.lineage, "lineage")
        _require_text(self.implementation_hash, "implementation_hash")
        _require_tuple(self.assumptions, "assumptions")
        _require_tuple(self.known_limits, "known_limits")
        _require_tuple(self.failure_modes, "failure_modes")
        _require_tuple(self.validation_plan, "validation_plan")
        if not self.qro_id:
            object.__setattr__(
                self,
                "qro_id",
                "qro_" + content_hash(
                    {
                        "qro_type": str(self.qro_type.value if isinstance(self.qro_type, Enum) else self.qro_type),
                        "owner": self.owner,
                        "input_contract": self.input_contract,
                        "output_contract": self.output_contract,
                        "market": self.market,
                        "universe": self.universe,
                        "horizon": self.horizon,
                        "frequency": self.frequency,
                        "lineage": self.lineage,
                        "implementation_hash": self.implementation_hash,
                        "version": self.version,
                    }
                ),
            )

    def status_axes(self) -> dict[str, str]:
        def _value(v: Any) -> str:
            return str(v.value if isinstance(v, Enum) else v)

        return {
            "definition": _value(self.definition_status),
            "theory": _value(self.theory_status),
            "consistency": _value(self.consistency_status),
            "evidence": _value(self.evidence_status),
            "governance": _value(self.governance_status),
            "runtime": _value(self.runtime_status),
        }


@dataclass(frozen=True)
class ResearchGraphCommand:
    source: EntrySource | str
    command_type: str
    actor_source: ActorSource | str
    actor: str
    payload: dict[str, Any]
    version: int = 1
    evidence_refs: tuple[str, ...] = ()
    tool_record_refs: tuple[str, ...] = ()
    timestamp: str = field(default_factory=_now)
    command_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "tool_record_refs", tuple(self.tool_record_refs))
        _require_text(self.command_type, "command_type")
        _require_text(self.actor, "actor")
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if not self.command_id:
            object.__setattr__(
                self,
                "command_id",
                "rgcmd_" + content_hash(
                    {
                        "source": str(self.source.value if isinstance(self.source, Enum) else self.source),
                        "command_type": self.command_type,
                        "actor_source": str(
                            self.actor_source.value if isinstance(self.actor_source, Enum) else self.actor_source
                        ),
                        "actor": self.actor,
                        "payload": _stable_for_hash(self.payload),
                        "version": self.version,
                        "timestamp": self.timestamp,
                    }
                ),
            )


@dataclass(frozen=True)
class ResearchGraphProjectionRecord:
    projection_ref: str
    qro_id: str
    qro_type: str
    command_id: str
    source: str
    actor_source: str
    actor: str
    owner: str
    market: str
    universe: str
    horizon: str
    frequency: str
    status_axes: dict[str, str]
    lineage: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    mathematical_refs: tuple[str, ...]
    permission: str
    allowed_environment: str
    mock_profile: str
    event_time: str | None
    known_at: str | None
    effective_at: str | None
    input_contract_keys: tuple[str, ...]
    output_contract_keys: tuple[str, ...]
    input_contract_hash: str
    output_contract_hash: str
    qro_version: int
    command_timestamp: str

    @classmethod
    def from_qro_command(cls, *, command: ResearchGraphCommand, qro: QRORecord) -> "ResearchGraphProjectionRecord":
        input_keys = tuple(sorted(str(key) for key in qro.input_contract.keys()))
        output_keys = tuple(sorted(str(key) for key in qro.output_contract.keys()))
        projection_ref = "rgproj_" + content_hash(
            {
                "qro_id": qro.qro_id,
                "qro_version": qro.version,
                "command_id": command.command_id,
                "command_timestamp": command.timestamp,
            }
        )
        return cls(
            projection_ref=projection_ref,
            qro_id=qro.qro_id,
            qro_type=_enum_text(qro.qro_type),
            command_id=command.command_id,
            source=_enum_text(command.source),
            actor_source=_enum_text(command.actor_source),
            actor=command.actor,
            owner=qro.owner,
            market=qro.market,
            universe=qro.universe,
            horizon=qro.horizon,
            frequency=qro.frequency,
            status_axes=qro.status_axes(),
            lineage=tuple(qro.lineage),
            evidence_refs=tuple(qro.evidence_refs),
            mathematical_refs=tuple(qro.mathematical_refs),
            permission=qro.permission,
            allowed_environment=_enum_text(qro.allowed_environment),
            mock_profile=qro.mock_profile,
            event_time=qro.event_time,
            known_at=qro.known_at,
            effective_at=qro.effective_at,
            input_contract_keys=input_keys,
            output_contract_keys=output_keys,
            input_contract_hash=content_hash(qro.input_contract),
            output_contract_hash=content_hash(qro.output_contract),
            qro_version=qro.version,
            command_timestamp=command.timestamp,
        )

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "projection_ref": self.projection_ref,
            "qro_id": self.qro_id,
            "qro_type": self.qro_type,
            "command_id": self.command_id,
            "source": self.source,
            "actor_source": self.actor_source,
            "actor": self.actor,
            "owner": self.owner,
            "market": self.market,
            "universe": self.universe,
            "horizon": self.horizon,
            "frequency": self.frequency,
            "status_axes": dict(self.status_axes),
            "lineage": list(self.lineage),
            "evidence_refs": list(self.evidence_refs),
            "mathematical_refs": list(self.mathematical_refs),
            "permission": self.permission,
            "allowed_environment": self.allowed_environment,
            "mock_profile": self.mock_profile,
            "event_time": self.event_time,
            "known_at": self.known_at,
            "effective_at": self.effective_at,
            "input_contract_keys": list(self.input_contract_keys),
            "output_contract_keys": list(self.output_contract_keys),
            "input_contract_hash": self.input_contract_hash,
            "output_contract_hash": self.output_contract_hash,
            "qro_version": self.qro_version,
            "command_timestamp": self.command_timestamp,
        }


@dataclass(frozen=True)
class ResearchGraphEdgeRecord:
    command_ref: str
    from_qro_id: str
    to_qro_id: str
    relation_type: str
    source_desk: str
    actor_source: str
    actor: str
    canonical_command_ref: str
    audit_ref: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = field(default_factory=_now)
    edge_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        for field_name in (
            "command_ref",
            "from_qro_id",
            "to_qro_id",
            "relation_type",
            "source_desk",
            "actor_source",
            "actor",
            "canonical_command_ref",
            "audit_ref",
        ):
            _require_text(str(getattr(self, field_name)), field_name)
        if self.from_qro_id == self.to_qro_id:
            raise ValueError("graph edge must connect two different QROs")
        if not self.edge_ref:
            object.__setattr__(
                self,
                "edge_ref",
                "rgedge_" + content_hash(
                    {
                        "command_ref": self.command_ref,
                        "from_qro_id": self.from_qro_id,
                        "to_qro_id": self.to_qro_id,
                        "relation_type": self.relation_type,
                        "source_desk": self.source_desk,
                        "actor_source": self.actor_source,
                        "actor": self.actor,
                        "canonical_command_ref": self.canonical_command_ref,
                        "audit_ref": self.audit_ref,
                        "evidence_refs": self.evidence_refs,
                        "created_at": self.created_at,
                    }
                ),
            )


@dataclass(frozen=True)
class ResearchGraphEdgeDeletionRecord:
    command_ref: str
    edge_ref: str
    source_desk: str
    actor_source: str
    actor: str
    canonical_command_ref: str
    audit_ref: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = field(default_factory=_now)
    deletion_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        for field_name in (
            "command_ref",
            "edge_ref",
            "source_desk",
            "actor_source",
            "actor",
            "canonical_command_ref",
            "audit_ref",
        ):
            _require_text(str(getattr(self, field_name)), field_name)
        if not self.deletion_ref:
            object.__setattr__(
                self,
                "deletion_ref",
                "rgedgedel_" + content_hash(
                    {
                        "command_ref": self.command_ref,
                        "edge_ref": self.edge_ref,
                        "source_desk": self.source_desk,
                        "actor_source": self.actor_source,
                        "actor": self.actor,
                        "canonical_command_ref": self.canonical_command_ref,
                        "audit_ref": self.audit_ref,
                        "evidence_refs": self.evidence_refs,
                        "created_at": self.created_at,
                    }
                ),
            )


@dataclass(frozen=True)
class QROTombstoneRecord:
    command_ref: str
    qro_id: str
    source_desk: str
    actor_source: str
    actor: str
    canonical_command_ref: str
    audit_ref: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = field(default_factory=_now)
    tombstone_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        for field_name in (
            "command_ref",
            "qro_id",
            "source_desk",
            "actor_source",
            "actor",
            "canonical_command_ref",
            "audit_ref",
        ):
            _require_text(str(getattr(self, field_name)), field_name)
        if not self.tombstone_ref:
            object.__setattr__(
                self,
                "tombstone_ref",
                "rgqrodel_" + content_hash(
                    {
                        "command_ref": self.command_ref,
                        "qro_id": self.qro_id,
                        "source_desk": self.source_desk,
                        "actor_source": self.actor_source,
                        "actor": self.actor,
                        "canonical_command_ref": self.canonical_command_ref,
                        "audit_ref": self.audit_ref,
                        "evidence_refs": self.evidence_refs,
                        "created_at": self.created_at,
                    }
                ),
            )


@dataclass(frozen=True)
class GraphPatchApplicationRecord:
    command_ref: str
    target_qro_id: str
    patch_kind: str
    patch_ref: str
    patch_hash: str
    source_desk: str
    actor_source: str
    actor: str
    canonical_command_ref: str
    audit_ref: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = field(default_factory=_now)
    application_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        for field_name in (
            "command_ref",
            "target_qro_id",
            "patch_kind",
            "patch_ref",
            "patch_hash",
            "source_desk",
            "actor_source",
            "actor",
            "canonical_command_ref",
            "audit_ref",
        ):
            _require_text(str(getattr(self, field_name)), field_name)
        if self.patch_kind not in {"ghost", "auto"}:
            raise ValueError("patch_kind must be ghost or auto")
        if any(ch.isspace() for ch in self.patch_ref):
            raise ValueError("patch_ref must be a compact reference token")
        if any(ch.isspace() for ch in self.patch_hash):
            raise ValueError("patch_hash must be a compact hash token")
        if not self.application_ref:
            object.__setattr__(
                self,
                "application_ref",
                "rgpatch_" + content_hash(
                    {
                        "command_ref": self.command_ref,
                        "target_qro_id": self.target_qro_id,
                        "patch_kind": self.patch_kind,
                        "patch_ref": self.patch_ref,
                        "patch_hash": self.patch_hash,
                        "source_desk": self.source_desk,
                        "actor_source": self.actor_source,
                        "actor": self.actor,
                        "canonical_command_ref": self.canonical_command_ref,
                        "audit_ref": self.audit_ref,
                        "evidence_refs": self.evidence_refs,
                        "created_at": self.created_at,
                    }
                ),
            )


@dataclass(frozen=True)
class CanvasParameterValueRecord:
    command_ref: str
    target_qro_id: str
    target_asset_type: str
    param_key: str
    param_value: str
    source_desk: str
    actor_source: str
    actor: str
    canonical_command_ref: str
    audit_ref: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = field(default_factory=_now)
    value_hash: str = ""
    parameter_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        for field_name in (
            "command_ref",
            "target_qro_id",
            "target_asset_type",
            "param_key",
            "param_value",
            "source_desk",
            "actor_source",
            "actor",
            "canonical_command_ref",
            "audit_ref",
        ):
            _require_text(str(getattr(self, field_name)), field_name)
        if any(ch.isspace() for ch in self.param_key) or "." in self.param_key:
            raise ValueError("param_key must be one compact field name")
        if len(self.param_value) > 512:
            raise ValueError("param_value must be 512 characters or fewer")
        if self.value_hash and any(ch.isspace() for ch in self.value_hash):
            raise ValueError("value_hash must be a compact hash token")
        if not self.value_hash:
            object.__setattr__(
                self,
                "value_hash",
                content_hash({"param_key": self.param_key, "param_value": self.param_value}),
            )
        if not self.parameter_ref:
            object.__setattr__(
                self,
                "parameter_ref",
                "rgparam_" + content_hash(
                    {
                        "command_ref": self.command_ref,
                        "target_qro_id": self.target_qro_id,
                        "target_asset_type": self.target_asset_type,
                        "param_key": self.param_key,
                        "value_hash": self.value_hash,
                        "source_desk": self.source_desk,
                        "actor_source": self.actor_source,
                        "actor": self.actor,
                        "canonical_command_ref": self.canonical_command_ref,
                        "audit_ref": self.audit_ref,
                        "evidence_refs": self.evidence_refs,
                        "created_at": self.created_at,
                    }
                ),
            )


_COMMAND_RECORD_FIELD: dict[str, tuple[str, type[Any]]] = {
    "upsert_qro": ("qro", QRORecord),
    "tombstone_qro": ("qro_tombstone", QROTombstoneRecord),
    "apply_graph_patch": ("patch_application", GraphPatchApplicationRecord),
    "set_canvas_parameter": ("parameter_value", CanvasParameterValueRecord),
    "record_canvas_mutation": ("mutation", CanvasMutationRecord),
    "record_canvas_layout": ("layout", CanvasLayoutRecord),
    "record_graph_edge": ("edge", ResearchGraphEdgeRecord),
    "delete_graph_edge": ("edge_deletion", ResearchGraphEdgeDeletionRecord),
    "record_methodology_choice": ("choice", MethodologyChoiceRecord),
    "record_responsibility_disclosure": ("responsibility", ResponsibilityDisclosureRecord),
    "record_theory_binding": ("binding", TheoryImplementationBinding),
    "record_consistency_check": ("check", ConsistencyCheck),
}


def _dataclass_payload(record: Any) -> dict[str, Any]:
    if not is_dataclass(record):
        raise ResearchGraphError(f"persistent Research Graph payload must be a dataclass, got {type(record).__name__}")
    return _stable_for_hash(asdict(record))


def _command_to_json(command: ResearchGraphCommand) -> dict[str, Any]:
    spec = _COMMAND_RECORD_FIELD.get(command.command_type)
    if spec is None:
        raise ResearchGraphError(f"persistent Research Graph command_type unsupported: {command.command_type!r}")
    field_name, record_type = spec
    record = command.payload.get(field_name)
    if not isinstance(record, record_type):
        raise ResearchGraphError(
            f"persistent Research Graph command {command.command_type!r} requires payload[{field_name!r}] "
            f"as {record_type.__name__}"
        )
    return {
        "schema_version": 1,
        "command": {
            "source": _enum_text(command.source),
            "command_type": command.command_type,
            "actor_source": _enum_text(command.actor_source),
            "actor": command.actor,
            "payload": {field_name: _dataclass_payload(record)},
            "version": command.version,
            "evidence_refs": list(command.evidence_refs),
            "tool_record_refs": list(command.tool_record_refs),
            "timestamp": command.timestamp,
            "command_id": command.command_id,
        },
    }


def _command_from_json(value: dict[str, Any]) -> ResearchGraphCommand:
    if value.get("schema_version") != 1:
        raise ResearchGraphError("unsupported Research Graph command schema_version")
    raw = value.get("command")
    if not isinstance(raw, dict):
        raise ResearchGraphError("persisted Research Graph row missing command")
    command_type = str(raw.get("command_type") or "")
    spec = _COMMAND_RECORD_FIELD.get(command_type)
    if spec is None:
        raise ResearchGraphError(f"persisted Research Graph command_type unsupported: {command_type!r}")
    field_name, record_type = spec
    payload = raw.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get(field_name), dict):
        raise ResearchGraphError(f"persisted Research Graph command missing payload[{field_name!r}]")
    record = record_type(**payload[field_name])
    return ResearchGraphCommand(
        source=str(raw.get("source") or ""),
        command_type=command_type,
        actor_source=str(raw.get("actor_source") or ""),
        actor=str(raw.get("actor") or ""),
        payload={field_name: record},
        version=int(raw.get("version") or 1),
        evidence_refs=_as_tuple(raw.get("evidence_refs")),
        tool_record_refs=_as_tuple(raw.get("tool_record_refs")),
        timestamp=str(raw.get("timestamp") or _now()),
        command_id=str(raw.get("command_id") or ""),
    )


def _atomic_rewrite_research_graph_rows(
    path: Path,
    rows: Sequence[dict[str, Any]],
) -> None:
    """Reject physical history rewrites for the append-only Graph log."""

    del path, rows
    raise ResearchGraphError(
        "Research Graph command log is append-only; rewrite is unsupported"
    )


def _research_graph_command_projection_key(
    command: ResearchGraphCommand,
) -> tuple[str, str]:
    """Return the logical projection slot controlled by one command."""

    spec = _COMMAND_RECORD_FIELD.get(command.command_type)
    if spec is None:
        raise ResearchGraphError(
            f"Research Graph rollback command_type unsupported: {command.command_type!r}"
        )
    field_name, record_type = spec
    record = command.payload.get(field_name)
    if not isinstance(record, record_type):
        raise ResearchGraphError(
            f"Research Graph rollback command {command.command_type!r} requires "
            f"payload[{field_name!r}] as {record_type.__name__}"
        )
    key_field = {
        "upsert_qro": "qro_id",
        "tombstone_qro": "qro_id",
        "apply_graph_patch": "application_ref",
        "set_canvas_parameter": "parameter_ref",
        "record_canvas_mutation": "command_ref",
        "record_canvas_layout": "layout_ref",
        "record_graph_edge": "edge_ref",
        "delete_graph_edge": "edge_ref",
        "record_methodology_choice": "choice_id",
        "record_responsibility_disclosure": "disclosure_id",
        "record_theory_binding": "binding_id",
        "record_consistency_check": "check_id",
    }[command.command_type]
    family = {
        "upsert_qro": "qro",
        "tombstone_qro": "qro",
        "record_graph_edge": "graph_edge",
        "delete_graph_edge": "graph_edge",
    }.get(command.command_type, command.command_type)
    projection_ref = str(getattr(record, key_field, "") or "").strip()
    if not projection_ref:
        raise ResearchGraphError(
            f"Research Graph rollback command is missing projection identity {key_field!r}"
        )
    return family, projection_ref


class ResearchGraphStore:
    """In-memory Research Graph command applier.

    Durable storage should wrap this contract later. The important invariant is
    that every write comes through a command, including Canvas edits.
    """

    def __init__(self) -> None:
        self._write_lock = threading.RLock()
        self._commands: list[ResearchGraphCommand] = []
        self._qros: dict[str, QRORecord] = {}
        self._projection_index: dict[str, ResearchGraphProjectionRecord] = {}
        self._qro_tombstones: dict[str, QROTombstoneRecord] = {}
        self._graph_patch_applications: dict[str, GraphPatchApplicationRecord] = {}
        self._canvas_parameter_values: dict[str, CanvasParameterValueRecord] = {}
        self._canvas_mutations: dict[str, CanvasMutationRecord] = {}
        self._canvas_layouts: dict[str, CanvasLayoutRecord] = {}
        self._graph_edges: dict[str, ResearchGraphEdgeRecord] = {}
        self._graph_edge_deletions: dict[str, ResearchGraphEdgeDeletionRecord] = {}
        self._methodology_choices: dict[str, MethodologyChoiceRecord] = {}
        self._responsibilities: dict[str, ResponsibilityDisclosureRecord] = {}
        self._bindings: dict[str, TheoryImplementationBinding] = {}
        self._checks: dict[str, ConsistencyCheck] = {}

    def _require_canvas_command_ownership(
        self,
        command: ResearchGraphCommand,
        record: Any,
        *qro_ids: str,
    ) -> tuple[QRORecord, ...]:
        """Enforce Canvas ownership at the command-store trust boundary."""

        actor = str(command.actor or "").strip()
        if not actor:
            raise ResearchGraphError("Canvas command actor is required")
        if hasattr(record, "actor") and str(getattr(record, "actor") or "").strip() != actor:
            raise ResearchGraphError("Canvas command actor does not match the mutation record actor")
        qros: list[QRORecord] = []
        for qro_id in qro_ids:
            qro = self._qros.get(qro_id)
            if qro is None or qro_id in self._qro_tombstones:
                raise ResearchGraphError(f"Canvas mutation target QRO not found: {qro_id}")
            if str(qro.owner or "") != actor:
                raise ResearchGraphError("Canvas mutation target belongs to a different owner")
            qros.append(qro)
        return tuple(qros)

    def apply(self, command: ResearchGraphCommand) -> str:
        with self._write_lock:
            return self._apply_unlocked(command)

    def _prepare_exact_command_rollback_unlocked(
        self,
        command: ResearchGraphCommand,
    ) -> ResearchGraphStore | None:
        matches = [
            (index, existing)
            for index, existing in enumerate(self._commands)
            if existing.command_id == command.command_id
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise ResearchGraphError(
                "Research Graph rollback command identity is not unique"
            )
        target_index, persisted = matches[0]
        if persisted != command:
            raise ResearchGraphError(
                "Research Graph rollback command identity mismatch"
            )
        target_key = _research_graph_command_projection_key(persisted)
        later_same_projection = tuple(
            existing.command_id
            for existing in self._commands[target_index + 1 :]
            if _research_graph_command_projection_key(existing) == target_key
        )
        if later_same_projection:
            raise ResearchGraphError(
                "Research Graph rollback command is not the current projection head:"
                + ",".join(later_same_projection)
            )

        replayed = ResearchGraphStore()
        try:
            for index, existing in enumerate(self._commands):
                if index != target_index:
                    replayed.apply(existing)
        except Exception as exc:
            raise ResearchGraphError(
                "Research Graph rollback refused because a later command depends "
                f"on {command.command_id!r}"
            ) from exc
        return replayed

    def _publish_replayed_state_unlocked(self, replayed: ResearchGraphStore) -> None:
        write_lock = self._write_lock
        self.__dict__.update(replayed.__dict__)
        self._write_lock = write_lock

    def rollback_exact_command(self, command: ResearchGraphCommand) -> bool:
        """Reject command deletion; Research Graph history is append-only."""

        del command
        raise ResearchGraphError(
            "Research Graph command log is append-only; rollback is unsupported"
        )

    def _assert_current_qro_command_unlocked(
        self,
        *,
        expected_command_ref: str,
        command: ResearchGraphCommand,
    ) -> None:
        expected = str(expected_command_ref or "").strip()
        if not expected or expected != str(expected_command_ref or ""):
            raise ResearchGraphError(
                "expected current Research Graph command ref is required"
            )
        qro = command.payload.get("qro")
        if command.command_type != "upsert_qro" or not isinstance(qro, QRORecord):
            raise ResearchGraphError(
                "compare-and-append requires an upsert_qro command"
            )
        projection = self._projection_index.get(qro.qro_id)
        actual = str(getattr(projection, "command_id", "") or "")
        if actual != expected:
            raise ResearchGraphError(
                "Research Graph current-head conflict:"
                f"expected={expected}:actual={actual or '<missing>'}"
            )

    def apply_if_current(
        self,
        expected_command_ref: str,
        command: ResearchGraphCommand,
    ) -> str:
        """Atomically append one QRO command only if its current head is expected."""

        with self._write_lock:
            self._assert_current_qro_command_unlocked(
                expected_command_ref=expected_command_ref,
                command=command,
            )
            return self.apply(command)

    def _apply_unlocked(self, command: ResearchGraphCommand) -> str:
        duplicate_commands = tuple(
            item
            for item in self._commands
            if item.command_id == command.command_id
        )
        if duplicate_commands:
            if len(duplicate_commands) != 1 or duplicate_commands[0] != command:
                raise ResearchGraphError(
                    "Research Graph command identity collision"
                )
            return command.command_id
        ctype = command.command_type
        if ctype == "upsert_qro":
            qro = command.payload.get("qro")
            if not isinstance(qro, QRORecord):
                raise ResearchGraphError("upsert_qro requires payload['qro'] as QRORecord")
            current_projection = self._projection_index.get(qro.qro_id)
            current_command = next(
                (
                    item
                    for item in reversed(self._commands)
                    if current_projection is not None
                    and item.command_id == current_projection.command_id
                ),
                None,
            )
            if current_command is not None and any(
                str(ref).startswith(prefix)
                for ref in tuple(current_command.tool_record_refs or ())
                for prefix in _PLATFORM_IMMUTABLE_BINDING_ENTRYPOINT_PREFIXES
            ):
                raise ResearchGraphError(
                    "platform-bound QRO is immutable; create a governed fork/new QRO"
                )
            if _enum_text(command.source) == EntrySource.CANVAS.value:
                actor = str(command.actor or "").strip()
                if not actor or str(qro.owner or "") != actor:
                    raise ResearchGraphError("Canvas QRO upsert belongs to a different owner")
                existing = self._qros.get(qro.qro_id)
                if existing is not None and str(existing.owner or "") != actor:
                    raise ResearchGraphError("Canvas QRO upsert cannot transfer ownership")
            self._qros[qro.qro_id] = qro
            self._projection_index[qro.qro_id] = ResearchGraphProjectionRecord.from_qro_command(
                command=command,
                qro=qro,
            )
        elif ctype == "tombstone_qro":
            record = command.payload.get("qro_tombstone")
            if not isinstance(record, QROTombstoneRecord):
                raise ResearchGraphError("tombstone_qro requires QROTombstoneRecord")
            if _enum_text(command.source) == EntrySource.CANVAS.value:
                (qro,) = self._require_canvas_command_ownership(command, record, record.qro_id)
            else:
                qro = self._qros.get(record.qro_id)
                if qro is None:
                    raise ResearchGraphError(f"QRO not found: {record.qro_id}")
            if _enum_text(qro.runtime_status) == RuntimeStatus.LIVE.value:
                raise ResearchGraphError("cannot tombstone live QRO; fork a draft/offline asset first")
            self._qro_tombstones[record.qro_id] = record
        elif ctype == "apply_graph_patch":
            record = command.payload.get("patch_application")
            if not isinstance(record, GraphPatchApplicationRecord):
                raise ResearchGraphError("apply_graph_patch requires GraphPatchApplicationRecord")
            if _enum_text(command.source) == EntrySource.CANVAS.value:
                (qro,) = self._require_canvas_command_ownership(command, record, record.target_qro_id)
            else:
                qro = self._qros.get(record.target_qro_id)
                if qro is None or record.target_qro_id in self._qro_tombstones:
                    raise ResearchGraphError(f"graph patch target QRO not found: {record.target_qro_id}")
            if _enum_text(qro.runtime_status) == RuntimeStatus.LIVE.value:
                raise ResearchGraphError("cannot apply graph patch to live QRO; fork a draft/offline asset first")
            self._graph_patch_applications[record.application_ref] = record
        elif ctype == "set_canvas_parameter":
            record = command.payload.get("parameter_value")
            if not isinstance(record, CanvasParameterValueRecord):
                raise ResearchGraphError("set_canvas_parameter requires CanvasParameterValueRecord")
            if _enum_text(command.source) == EntrySource.CANVAS.value:
                (qro,) = self._require_canvas_command_ownership(command, record, record.target_qro_id)
            else:
                qro = self._qros.get(record.target_qro_id)
                if qro is None or record.target_qro_id in self._qro_tombstones:
                    raise ResearchGraphError(f"canvas parameter target QRO not found: {record.target_qro_id}")
            if _enum_text(qro.qro_type) != record.target_asset_type:
                raise ResearchGraphError(
                    f"canvas parameter target_asset_type mismatch: expected {_enum_text(qro.qro_type)}, got {record.target_asset_type}"
                )
            if _enum_text(qro.runtime_status) == RuntimeStatus.LIVE.value:
                raise ResearchGraphError("cannot save canvas parameter on live QRO; fork a draft/offline asset first")
            self._canvas_parameter_values[record.parameter_ref] = record
        elif ctype == "record_canvas_mutation":
            record = command.payload.get("mutation")
            if not isinstance(record, CanvasMutationRecord):
                raise ResearchGraphError("record_canvas_mutation requires CanvasMutationRecord")
            if _enum_text(command.source) == EntrySource.CANVAS.value:
                self._require_canvas_command_ownership(command, record, record.target_ref)
            self._canvas_mutations[record.command_ref] = record
        elif ctype == "record_canvas_layout":
            record = command.payload.get("layout")
            if not isinstance(record, CanvasLayoutRecord):
                raise ResearchGraphError("record_canvas_layout requires CanvasLayoutRecord")
            validate_canvas_layout_record(record)
            if _enum_text(command.source) == EntrySource.CANVAS.value:
                self._require_canvas_command_ownership(command, record, record.qro_id)
            self._canvas_layouts[record.layout_ref] = record
        elif ctype == "record_graph_edge":
            record = command.payload.get("edge")
            if not isinstance(record, ResearchGraphEdgeRecord):
                raise ResearchGraphError("record_graph_edge requires ResearchGraphEdgeRecord")
            if record.from_qro_id not in self._qros:
                raise ResearchGraphError(f"graph edge source QRO not found: {record.from_qro_id}")
            if record.to_qro_id not in self._qros:
                raise ResearchGraphError(f"graph edge target QRO not found: {record.to_qro_id}")
            if _enum_text(command.source) == EntrySource.CANVAS.value:
                self._require_canvas_command_ownership(
                    command,
                    record,
                    record.from_qro_id,
                    record.to_qro_id,
                )
            self._graph_edges[record.edge_ref] = record
        elif ctype == "delete_graph_edge":
            record = command.payload.get("edge_deletion")
            if not isinstance(record, ResearchGraphEdgeDeletionRecord):
                raise ResearchGraphError("delete_graph_edge requires ResearchGraphEdgeDeletionRecord")
            if record.edge_ref not in self._graph_edges:
                raise ResearchGraphError(f"graph edge not found: {record.edge_ref}")
            if _enum_text(command.source) == EntrySource.CANVAS.value:
                edge = self._graph_edges[record.edge_ref]
                self._require_canvas_command_ownership(
                    command,
                    record,
                    edge.from_qro_id,
                    edge.to_qro_id,
                )
            self._graph_edge_deletions[record.edge_ref] = record
        elif ctype == "record_methodology_choice":
            record = command.payload.get("choice")
            if not isinstance(record, MethodologyChoiceRecord):
                raise ResearchGraphError("record_methodology_choice requires MethodologyChoiceRecord")
            self._methodology_choices[record.choice_id] = record
        elif ctype == "record_responsibility_disclosure":
            record = command.payload.get("responsibility")
            if not isinstance(record, ResponsibilityDisclosureRecord):
                raise ResearchGraphError("record_responsibility_disclosure requires ResponsibilityDisclosureRecord")
            self._responsibilities[record.disclosure_id] = record
        elif ctype == "record_theory_binding":
            binding = command.payload.get("binding")
            if not isinstance(binding, TheoryImplementationBinding):
                raise ResearchGraphError("record_theory_binding requires TheoryImplementationBinding")
            self._bindings[binding.binding_id] = binding
        elif ctype == "record_consistency_check":
            check = command.payload.get("check")
            if not isinstance(check, ConsistencyCheck):
                raise ResearchGraphError("record_consistency_check requires ConsistencyCheck")
            self._checks[check.check_id] = check
        else:
            raise ResearchGraphError(f"unknown command_type={ctype!r}")
        self._commands.append(command)
        return command.command_id

    def qro(self, qro_id: str, *, include_tombstoned: bool = False) -> QRORecord:
        if not include_tombstoned and qro_id in self._qro_tombstones:
            raise KeyError(qro_id)
        return self._qros[qro_id]

    def canvas_mutations(self) -> list[CanvasMutationRecord]:
        return list(self._canvas_mutations.values())

    def canvas_layout(self, layout_ref: str) -> CanvasLayoutRecord:
        return self._canvas_layouts[layout_ref]

    def canvas_layouts(self, qro_id: str | None = None) -> list[CanvasLayoutRecord]:
        records = list(self._canvas_layouts.values())
        if qro_id is not None:
            records = [record for record in records if record.qro_id == qro_id]
        return records

    def graph_edges(
        self,
        qro_id: str | None = None,
        *,
        include_deleted: bool = False,
    ) -> list[ResearchGraphEdgeRecord]:
        records = list(self._graph_edges.values())
        if not include_deleted:
            deleted = set(self._graph_edge_deletions)
            records = [record for record in records if record.edge_ref not in deleted]
            tombstoned_qros = set(self._qro_tombstones)
            records = [
                record
                for record in records
                if record.from_qro_id not in tombstoned_qros and record.to_qro_id not in tombstoned_qros
            ]
        if qro_id is not None:
            records = [record for record in records if qro_id in {record.from_qro_id, record.to_qro_id}]
        return records

    def graph_edge_deletions(self) -> list[ResearchGraphEdgeDeletionRecord]:
        return list(self._graph_edge_deletions.values())

    def qro_tombstones(self) -> list[QROTombstoneRecord]:
        return list(self._qro_tombstones.values())

    def graph_patch_applications(self) -> list[GraphPatchApplicationRecord]:
        return list(self._graph_patch_applications.values())

    def canvas_parameter_values(self) -> list[CanvasParameterValueRecord]:
        return list(self._canvas_parameter_values.values())

    def methodology_choice(self, choice_id: str) -> MethodologyChoiceRecord:
        return self._methodology_choices[choice_id]

    def binding(self, binding_id: str) -> TheoryImplementationBinding:
        return self._bindings[binding_id]

    def checks_for_binding(self, binding_id: str) -> list[ConsistencyCheck]:
        return [c for c in self._checks.values() if c.binding_id == binding_id]

    def commands(self) -> list[ResearchGraphCommand]:
        return list(self._commands)

    def projection_index(
        self,
        *,
        qro_type: str | None = None,
        owner: str | None = None,
        market: str | None = None,
        universe: str | None = None,
        definition_status: str | None = None,
        evidence_status: str | None = None,
        runtime_status: str | None = None,
        lineage_token: str | None = None,
        include_tombstoned: bool = False,
    ) -> list[ResearchGraphProjectionRecord]:
        records = list(self._projection_index.values())
        if not include_tombstoned:
            tombstoned_qros = set(self._qro_tombstones)
            records = [record for record in records if record.qro_id not in tombstoned_qros]

        def _same(actual: str, expected: str | None) -> bool:
            return not expected or actual == expected

        filtered: list[ResearchGraphProjectionRecord] = []
        for record in records:
            if not _same(record.qro_type, qro_type):
                continue
            if not _same(record.owner, owner):
                continue
            if not _same(record.market, market):
                continue
            if not _same(record.universe, universe):
                continue
            if definition_status and record.status_axes.get("definition") != definition_status:
                continue
            if evidence_status and record.status_axes.get("evidence") != evidence_status:
                continue
            if runtime_status and record.status_axes.get("runtime") != runtime_status:
                continue
            if lineage_token and lineage_token not in record.lineage:
                continue
            filtered.append(record)
        return filtered


class PersistentResearchGraphStore(ResearchGraphStore):
    """JSONL-backed Research Graph command store.

    The file is an append-only command log. Startup replays every command and
    fails closed on malformed rows so audit history cannot silently disappear.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        fresh = ResearchGraphStore()
        if not self._path.exists():
            write_lock = self._write_lock
            self.__dict__.update(fresh.__dict__)
            self._write_lock = write_lock
            return
        seen_command_refs: set[str] = set()
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    command = _command_from_json(row)
                    if command.command_id in seen_command_refs:
                        raise ResearchGraphError(
                            "persisted Research Graph command id is duplicated"
                        )
                    seen_command_refs.add(command.command_id)
                    fresh.apply(command)
                except Exception as exc:  # noqa: BLE001 - startup must report the exact bad row.
                    raise ResearchGraphError(
                        f"invalid persisted Research Graph command at {self._path}:{line_no}"
                    ) from exc
        write_lock = self._write_lock
        self.__dict__.update(fresh.__dict__)
        self._write_lock = write_lock

    def refresh(self) -> None:
        """Replace the in-memory projection with a fresh replay of the log."""

        with _persistent_research_graph_write_lock(self._path):
            with self._write_lock:
                self._load_existing()

    def _publish_projection_unlocked(self, fresh: ResearchGraphStore) -> None:
        write_lock = self._write_lock
        path = self._path
        self.__dict__.update(fresh.__dict__)
        self._write_lock = write_lock
        self._path = path

    def _append_command_row_unlocked(self, row: dict[str, Any]) -> None:
        payload = (
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        with self._path.open("a+b") as fh:
            fh.seek(0, os.SEEK_END)
            original_size = fh.tell()
            try:
                written = fh.write(payload)
                if written != len(payload):
                    raise OSError(
                        "Research Graph append wrote a partial event"
                    )
                fh.flush()
                os.fsync(fh.fileno())
            except Exception as exc:
                try:
                    fh.seek(original_size, os.SEEK_SET)
                    fh.truncate()
                    fh.flush()
                    os.fsync(fh.fileno())
                except Exception as rollback_exc:
                    raise ResearchGraphDurabilityError(
                        "Research Graph append failed and tail rollback failed:"
                        f"append={type(exc).__name__}:{exc}:"
                        f"rollback={type(rollback_exc).__name__}:{rollback_exc}"
                    ) from rollback_exc
                raise

    def _persist_command_unlocked(self, command: ResearchGraphCommand) -> str:
        row = _command_to_json(command)
        # SA-4 write门：拒任何 id/内容携 goal_closure 占位 token 的 research-graph 命令。
        # 在 super().apply（内存）与落盘之前拒 → 既不污染内存也不留半行（原子 fail-closed）。
        # 扫的是即将持久化的整行（含 _dataclass_payload 展开的 QRO refs），藏在 payload 里也抓。
        if _carries_goal_closure_seed(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)):
            raise ResearchGraphError(
                "research graph command rejected: goal_closure placeholder seed is not a real "
                "research-graph command (SA-4 write門 fail-closes self-certifying closure seeds)"
            )
        duplicate_commands = tuple(
            item
            for item in self._commands
            if item.command_id == command.command_id
        )
        if duplicate_commands:
            if len(duplicate_commands) != 1 or duplicate_commands[0] != command:
                raise ResearchGraphError(
                    "Research Graph command identity collision"
                )
            return command.command_id
        projected = ResearchGraphStore()
        for existing in self._commands:
            projected.apply(existing)
        command_id = projected.apply(command)
        try:
            self._append_command_row_unlocked(row)
            self._publish_projection_unlocked(projected)
        except Exception as exc:
            try:
                self._load_existing()
            except Exception as observation_exc:
                raise ResearchGraphDurabilityError(
                    "Research Graph append/publish failed and durable state "
                    "could not be observed:"
                    f"append={type(exc).__name__}:{exc}:"
                    f"observation={type(observation_exc).__name__}:"
                    f"{observation_exc}"
                ) from observation_exc
            raise
        return command_id

    def apply(self, command: ResearchGraphCommand) -> str:
        with _persistent_research_graph_write_lock(self._path):
            with self._write_lock:
                self._load_existing()
                return self._persist_command_unlocked(command)

    def apply_if_current(
        self,
        expected_command_ref: str,
        command: ResearchGraphCommand,
    ) -> str:
        with _persistent_research_graph_write_lock(self._path):
            with self._write_lock:
                self._load_existing()
                self._assert_current_qro_command_unlocked(
                    expected_command_ref=expected_command_ref,
                    command=command,
                )
                return self._persist_command_unlocked(command)

    def rollback_exact_command(self, command: ResearchGraphCommand) -> bool:
        """Reject durable deletion; the persisted command log is append-only."""

        return super().rollback_exact_command(command)


@dataclass(frozen=True)
class GuardViolation:
    code: str
    message: str


@dataclass(frozen=True)
class GuardDecision:
    accepted: bool
    violations: tuple[GuardViolation, ...]


class PromotionGuard:
    """Reject over-claims before proof/evidence/production labels are applied."""

    @staticmethod
    def evaluate(
        qro: QRORecord,
        *,
        target_labels: set[PromotionLabel] | set[str],
        methodology_choices: dict[str, MethodologyChoiceRecord] | None = None,
        bindings: dict[str, TheoryImplementationBinding] | None = None,
        consistency_checks: dict[str, list[ConsistencyCheck]] | None = None,
    ) -> GuardDecision:
        labels = {str(v.value if isinstance(v, Enum) else v) for v in target_labels}
        strong = bool(
            labels
            & {
                PromotionLabel.PROOF_BACKED.value,
                PromotionLabel.EVIDENCE_SUFFICIENT.value,
                PromotionLabel.PRODUCTION_READY.value,
            }
        )
        violations: list[GuardViolation] = []
        if strong and not qro.evidence_refs:
            violations.append(GuardViolation("missing_evidence_ref", "formal promotion requires evidence_refs"))

        choices = methodology_choices or {}
        if qro.methodology_choice_ref and qro.methodology_choice_ref in choices:
            choice = choices[qro.methodology_choice_ref]
            if strong and choice.is_user_waiver:
                violations.append(
                    GuardViolation(
                        "user_waiver_overclaim",
                        "user-waived methodology cannot be promoted as proof-backed/evidence-sufficient/production-ready",
                    )
                )

        theory_value = str(qro.theory_status.value if isinstance(qro.theory_status, Enum) else qro.theory_status)
        consistency_value = str(
            qro.consistency_status.value if isinstance(qro.consistency_status, Enum) else qro.consistency_status
        )
        needs_theory_binding = bool(qro.mathematical_refs or theory_value in {
            TheoryStatus.REQUIRED.value,
            TheoryStatus.DRAFTED.value,
            TheoryStatus.DERIVED.value,
            TheoryStatus.ACCEPTED.value,
            TheoryStatus.USER_WAIVED.value,
        })
        if strong and theory_value == TheoryStatus.USER_WAIVED.value:
            violations.append(
                GuardViolation("theory_waived_overclaim", "user-waived theory cannot be labeled as strong proof")
            )
        if strong and needs_theory_binding:
            if not qro.theory_implementation_binding:
                violations.append(
                    GuardViolation(
                        "missing_theory_binding",
                        "theory-backed claim requires TheoryImplementationBinding",
                    )
                )
            else:
                binding = (bindings or {}).get(qro.theory_implementation_binding)
                if binding is None:
                    violations.append(
                        GuardViolation("unknown_theory_binding", "referenced TheoryImplementationBinding is not recorded")
                    )
                elif not binding.accepted:
                    violations.append(
                        GuardViolation("binding_not_accepted", "TheoryImplementationBinding is not accepted")
                    )
                else:
                    checks = (consistency_checks or {}).get(binding.binding_id, [])
                    if not any(c.accepted for c in checks):
                        violations.append(
                            GuardViolation("missing_consistency_check", "accepted binding requires accepted ConsistencyCheck")
                        )
        if strong and consistency_value in {ConsistencyStatus.UNBOUND.value, ConsistencyStatus.MISMATCH.value}:
            violations.append(
                GuardViolation("consistency_not_accepted", f"consistency status is {consistency_value}")
            )
        if PromotionLabel.PRODUCTION_READY.value in labels and qro.mock_profile != "none":
            violations.append(
                GuardViolation("production_mock_fallback", "production-ready QRO cannot carry a mock/fallback profile")
            )
        return GuardDecision(accepted=not violations, violations=tuple(violations))


# ════════════════════════════════════════════════════════════════════════════
# NC-S6-MATHCHAIN-PRODUCER · §6 数学贯穿链 promote-manifest record builder（孤立·PARALLEL-SAFE）
# ════════════════════════════════════════════════════════════════════════════
# 缺口（codemap v2 头号结论）：§6 数学链门 `section6_mathchain_gate.section6_mathchain_check` 委托
# `lineage.spine_gate.evaluate_promotion`（8-clause Π）判「声称按理论实现、要升级到强标签的产物·数学链
# 过没过」，但真 promote 路径**从未把真 run 的 typed 数学链记录（MathematicalArtifact /
# TheoryImplementationBinding / ConsistencyCheck / MethodologyChoiceRecord）如实序列化进 manifest** →
# 门恒见「未声明」→ 其证据 producer `s6_mathchain_runjson_producers` 无真对象可证 → 永停 advisory（出厂
# 红·守 LOCKED 决策「转绿前只 advisory + 记录·绝不误拒诚实 run」）。本段补这块 producer：从真 theory-backed
# run 的 **canonical lineage.spine typed 对象** 如实序列化成 section6_mathchain_gate 的 producer 契约 dict
# （`{"promotion_claims": [...]}`·key 对齐其 `_adapt_*` 读的 lineage 字段名）——让门有真对象可判（合规 run
# 过、坏 run 拒），转绿后门才从 advisory 翻 enforce。
#
# 诚实红线（= GOAL §0「no silent mock / no template false success」+ RULES.project「未验证≠已验证」对准
# 本 builder 自己）：
#   - **只忠实序列化·零判定重造（单一源）**：本 builder 只把 typed 对象转 JSON-safe dict；「数学链完整否 /
#     标签强度够否 / 实现是否漂移」全留给 section6_mathchain_gate → spine_gate.evaluate_promotion 的 8 子句。
#     坏 claim（强标签缺 ConsistencyCheck / 缺 binding / proof 没证）**如实序列化** → 门据真值拒，**绝不**
#     在此预判 / 补默认 / 过滤 / 洗白（洗白=假绿灯）。
#   - **缺即真缺·绝不补占位（no whitewash）**：claim 缺 ConsistencyCheck → 序列化就缺（绝不 fabricate 一条
#     pass 的假 check）；缺 binding → 缺；artifact.statement 空 → 空（不填假证）。门据此诚实拒强晋级。
#   - **honest-absent**：无 claim → 返回 `None`（中心 `_take` 不发该 section key·门 honest-bound·未声明≠
#     违例·不误拒「只是没 theory 声明」的诚实 run）。
#   - **fail-closed 入参**：claim 携错 flavor / 错类型对象（非 lineage.spine canonical 类型）→ raise
#     `Section6RecordError`（不静默吞坏输入·不产「能骗过门」的 dict）。
#   - **faithful 往返**：builder 序列化 lineage 对象 → dict → 门 `_adapt_*` 复原 lineage 对象 →
#     evaluate_promotion，无损往返（test 钉死门裁定 == 直算 evaluate_promotion·复用不重造）。
#
# 复用不重造：序列化复用本模块既有 `_stable_for_hash`（enum→value / dataclass→dict / tuple→list·已用于
# `_chain_event_row` 落 JSONL）。消费的 typed 对象复用 lineage.spine canonical 类型（aliased Spine*·与本
# 模块同名的 research_os flavor 区分·**不另造**第三套数学链类型）。判定复用 spine_gate（经门）·零判定。


class Section6RecordError(ValueError):
    """fail-closed：§6 promotion claim 携错类型对象（非 lineage.spine canonical 数学链类型）。

    拒绝把错 flavor / 错类型对象序列化进 §6 producer 契约——坏输入绝不静默吞成「能骗过门的 dict」
    （守 RULES.project「未验证≠已验证」·不产假绿灯素材）。
    """


@dataclass(frozen=True)
class Section6PromotionClaim:
    """一条 §6 数学链升级 claim 的 producer 输入（复用 lineage.spine canonical typed 对象·不另造）。

    承载一次 theory-backed 晋级意图的 canonical 数学链对象（= `evaluate_promotion` 直接裁定的那套记录）：
    `artifact`（MathematicalArtifact·含 statement/derivation/proof_status）+ `binding`
    （TheoryImplementationBinding）+ `consistency_checks`（ConsistencyCheck 序列）+ 可选 `choice`
    （MethodologyChoiceRecord 放权）/ `data_contract`（PIT 时间语义）/ `current_code_hash`（staleness 复核）/
    `asset_ref`（违例定位）。builder 只忠实序列化这些对象——**完整性 / 强度判定全留给 §6 门 →
    spine_gate.evaluate_promotion**（单一源）；缺证据保持缺（无 whitewash），门据真值诚实拒。
    """

    requested_label: str
    artifact: "SpineMathematicalArtifact | None" = None
    binding: "SpineTheoryImplementationBinding | None" = None
    consistency_checks: "Sequence[SpineConsistencyCheck]" = ()
    choice: "SpineMethodologyChoiceRecord | None" = None
    data_contract: "Mapping[str, Any] | None" = None
    current_code_hash: str | None = None
    asset_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "consistency_checks", tuple(self.consistency_checks))
        # fail-closed（codex 复审 High）：requested_label 必须是真 str。非 str（如 ['production_ready']）若被
        # 下面序列化 str() 洗成 "['production_ready']"，门的 isinstance 守卫（section6_mathchain_gate
        # _evaluate_claim·拒非 str label）就不会触发 → 强标签被悄悄当未知弱标签 promotable=True 放行
        # （假绿灯）。在源头就拒，绝不让强晋级义务被类型洗白绕过。
        if not isinstance(self.requested_label, str):
            raise Section6RecordError(
                f"requested_label 须为 str，得到 {type(self.requested_label).__name__}"
                "（fail-closed·拒非 str 强标签被 str() 洗成弱标签溜过门）"
            )
        _require_text(self.requested_label, "requested_label")


def _section6_check_typed(claim: Any) -> None:
    """fail-closed 类型守卫：claim 每个数学链子对象必须是 lineage.spine canonical 类型（错则拒序列化）。

    防错 flavor（research_os.spine 同名类型 / 任意 dict / 半成品）混进 §6 producer 契约——坏输入在序列化
    前就拒，绝不产「能骗过门」的 dict。**只校验类型·绝不判过没过**（过没过整体是门的事）。
    """

    if not isinstance(claim, Section6PromotionClaim):
        raise Section6RecordError(
            f"§6 promotion claim 须为 Section6PromotionClaim，得到 {type(claim).__name__}（fail-closed）"
        )
    if claim.artifact is not None and not isinstance(claim.artifact, SpineMathematicalArtifact):
        raise Section6RecordError(
            "§6 claim.artifact 须为 lineage.spine.MathematicalArtifact，"
            f"得到 {type(claim.artifact).__name__}（fail-closed·拒错 flavor）"
        )
    if claim.binding is not None and not isinstance(claim.binding, SpineTheoryImplementationBinding):
        raise Section6RecordError(
            "§6 claim.binding 须为 lineage.spine.TheoryImplementationBinding，"
            f"得到 {type(claim.binding).__name__}（fail-closed·拒错 flavor）"
        )
    for c in claim.consistency_checks:
        if not isinstance(c, SpineConsistencyCheck):
            raise Section6RecordError(
                "§6 claim.consistency_checks[*] 须为 lineage.spine.ConsistencyCheck，"
                f"得到 {type(c).__name__}（fail-closed·拒错 flavor）"
            )
    if claim.choice is not None and not isinstance(claim.choice, SpineMethodologyChoiceRecord):
        raise Section6RecordError(
            "§6 claim.choice 须为 lineage.spine.MethodologyChoiceRecord，"
            f"得到 {type(claim.choice).__name__}（fail-closed·拒错 flavor）"
        )


def _section6_claim_to_dict(claim: Section6PromotionClaim) -> dict[str, Any]:
    """一条 §6 claim → producer 契约 dict（key 对齐 section6_mathchain_gate `_adapt_*` 读的 lineage 字段名）。

    **只序列化·零判定·缺即缺**：子对象在场 → `_stable_for_hash` 无损转 dict（坏值如实保留·门据真值判）；
    缺省 → 不发该 key（缺 binding / 缺 check 如实暴露·门据 binding-exists / consistency-present 拒·非 whitewash）。

    ★ mutation 锚点（见 tests/test_s6_mathchain_producer.py 头）：把下面 `consistency_checks` 序列化弱化成
      「不发 consistency_checks key」（漏 consistency）→ 合规 run 的真 check 消失 → 门 consistency-present
      误拒合规 → `test_compliant_run_builds_record_gate_enforces_ok` 转 RED；反向把空 checks 补一条假 pass
      （whitewash）→ 坏 run 被洗白过门 → `test_bad_run_missing_consistency_check_enforces_reject` 转 RED →
      还原 → GREEN。证明 builder 忠实搬运 ConsistencyCheck（漏报 / 洗白都被对抗测试抓）。
    """

    out: dict[str, Any] = {"requested_label": str(claim.requested_label)}
    if claim.asset_ref:
        out["asset_ref"] = str(claim.asset_ref)
    if claim.artifact is not None:
        out["artifact"] = _stable_for_hash(claim.artifact)
    if claim.binding is not None:
        out["binding"] = _stable_for_hash(claim.binding)
    if claim.consistency_checks:
        out["consistency_checks"] = [_stable_for_hash(c) for c in claim.consistency_checks]
    if claim.choice is not None:
        out["choice"] = _stable_for_hash(claim.choice)
    if claim.data_contract is not None:
        out["data_contract"] = {str(k): _stable_for_hash(v) for k, v in claim.data_contract.items()}
    if claim.current_code_hash is not None:
        out["current_code_hash"] = str(claim.current_code_hash)
    return out


def build_section6_mathchain_record(
    claims: "Sequence[Section6PromotionClaim]",
) -> dict[str, Any] | None:
    """从真 theory-backed run 的 canonical 数学链对象组装 §6 门 producer 契约 record（honest-absent）。

    返回 `{"promotion_claims": [<每条 claim 的 dict>, ...]}`（key 对齐 section6_mathchain_gate 的
    `SECTION6_MATHCHAIN_MANIFEST_KEY` 契约）；honest-absent（无 claim）时返回 `None`（无 theory 声明 →
    中心 `_take` 不发该 section·门 honest-bound·未声明≠违例·不误拒诚实 run）。

    **只忠实序列化·零判定重造**：数学链「完整否 / 强度够否 / 实现漂移否」全委托 section6_mathchain_gate →
    spine_gate.evaluate_promotion 的 8 子句（单一源）。坏 claim 如实序列化 → 门据真值拒；缺 ConsistencyCheck
    保持缺 → 门 consistency-present 拒（**绝不** fabricate 假 check 洗白·守 GOAL §0 no-silent-mock）。
    fail-closed：claim 携错 flavor / 错类型对象 → raise `Section6RecordError`（不静默吞坏输入·不产骗门 dict）。
    """

    # fail-closed（codex 复审 Medium）：honest-absent（无 theory 声明）须**显式**传空序列 []/()；拒 None
    # 静默当作「无 claim」躲过判定——上游抽取失败返回 None 时，`list(claims or ())` 会把它洗成 honest-absent
    # 放行（fail-open：失败的抽取悄悄躲过门）。None ≠ 空声明，强制调用方区分。
    if claims is None:
        raise Section6RecordError(
            "claims 不能为 None——honest-absent（无 theory 声明）须显式传空序列 []；"
            "拒 None 静默当作『无 claim』躲过判定（防上游抽取失败返回 None 的 fail-open）"
        )
    typed = list(claims)
    if not typed:
        return None  # honest-absent：无 theory 声明 → 整节不发（门未声明≠违例·绝不误拒诚实 run）
    for claim in typed:
        _section6_check_typed(claim)  # fail-closed：错 flavor / 错类型在序列化前就拒
    return {"promotion_claims": [_section6_claim_to_dict(c) for c in typed]}


__all__ = [
    "ActorSource",
    "CanvasParameterValueRecord",
    "ConsistencyCheck",
    "ConsistencyStatus",
    "DefinitionStatus",
    "EntrySource",
    "EvidenceStatus",
    "GraphPatchApplicationRecord",
    "GovernanceStatus",
    "GuardDecision",
    "GuardViolation",
    "MathematicalArtifact",
    "MathematicalSpineChainDecision",
    "MathematicalSpineChainRecord",
    "MathematicalSpineChainViolation",
    "MethodologyChoiceRecord",
    "MethodologyPath",
    "PersistentMathematicalSpineChainRegistry",
    "PersistentResearchGraphStore",
    "PromotionGuard",
    "PromotionLabel",
    "QROTombstoneRecord",
    "QRORecord",
    "QROType",
    "ResearchGraphCommand",
    "ResearchGraphEdgeDeletionRecord",
    "ResearchGraphEdgeRecord",
    "ResearchGraphError",
    "ResearchGraphProjectionRecord",
    "ResearchGraphStore",
    "ResponsibilityDisclosureRecord",
    "RuntimeStatus",
    "Section6PromotionClaim",
    "Section6RecordError",
    "TheoryImplementationBinding",
    "TheoryStatus",
    "build_section6_mathchain_record",
    "mathematical_spine_chain_from_dict",
    "validate_mathematical_spine_chain",
]
