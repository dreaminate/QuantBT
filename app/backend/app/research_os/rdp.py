"""Research Delivery Package manifest and gate.

GOAL §17 requires formal research delivery to be an open package, not a chart
or a code snippet. This module gives that package a typed manifest and a
validator that rejects missing graph/data/math/repro/evidence fields.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import urllib.parse
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import canonical_json, content_hash
from .onboarding_gateway import contains_plaintext_secret
from .spine import QRORecord, RuntimeStatus


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


_LEGACY_ASSET_KINDS = frozenset({"factor", "model", "signal", "strategybook"})


@dataclass(frozen=True)
class DatasetVersionRef:
    """Open, resolvable reference to one immutable dataset version."""

    dataset_id: str
    version: str
    manifest_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatasetVersionRef":
        if not isinstance(data, dict):
            raise TypeError("DatasetVersionRef must be constructed from an object")
        return cls(
            dataset_id=str(data.get("dataset_id") or ""),
            version=str(data.get("version") or ""),
            manifest_sha256=str(data.get("manifest_sha256") or ""),
        )

    @property
    def is_resolvable(self) -> bool:
        return bool(self.dataset_id.strip()) and bool(self.version.strip())


@dataclass(frozen=True)
class RDPViolation:
    code: str
    message: str


@dataclass(frozen=True)
class RDPManifest:
    """Single canonical RDP model for research-os persistence and release delivery.

    The first field group is the canonical ref-oriented contract.  The second
    group keeps legacy delivery names as a migration surface only; ``__post_init__``
    projects them into the canonical fields and both packages import this exact
    class.  There is no second RDP identity model.
    """

    research_question: str = ""
    graph_refs: tuple[str, ...] = ()
    data_refs: tuple[str, ...] = ()
    dataset_version_refs: tuple[str, ...] = ()
    market_data_use_validation_refs: tuple[str, ...] = ()
    ingestion_skill_refs: tuple[str, ...] = ()
    mathematical_refs: tuple[str, ...] = ()
    theory_binding_refs: tuple[str, ...] = ()
    consistency_check_refs: tuple[str, ...] = ()
    methodology_choice_refs: tuple[str, ...] = ()
    responsibility_refs: tuple[str, ...] = ()
    asset_refs: tuple[str, ...] = ()
    code_refs: tuple[str, ...] = ()
    environment_lock_ref: str = ""
    reproducibility_command: str = ""
    artifact_hash: str = ""
    test_refs: tuple[str, ...] = ()
    run_refs: tuple[str, ...] = ()
    honest_n_refs: tuple[str, ...] = ()
    cost_and_execution_assumptions: tuple[str, ...] = ()
    attribution_refs: tuple[str, ...] = ()
    known_limits: tuple[str, ...] = ()
    unverified_residuals: tuple[str, ...] | None = None
    verifier_verdict_ref: str = ""
    compiler_artifact_refs: tuple[str, ...] = ()
    mathematical_spine_chain_refs: tuple[str, ...] = ()
    goal_entrypoint_coverage_refs: tuple[str, ...] = ()
    trust_release_ref: str = ""
    approval_ref: str | None = None
    deployment_refs: tuple[str, ...] = ()
    monitor_refs: tuple[str, ...] = ()
    rollback_plan_ref: str | None = None
    retire_plan_ref: str | None = None
    target_runtime: RuntimeStatus | str = RuntimeStatus.OFFLINE
    llm_call_refs: tuple[str, ...] = ()
    source_file_refs: tuple[str, ...] = ()
    package_id: str = ""
    manifest_version: str = "rdp.v3"

    # Legacy delivery vocabulary.  These fields are compatibility inputs and
    # open-format aliases; canonical gates consume the fields above.
    asset_ref: str = ""
    asset_kind: str = ""
    schema_version: str = ""
    rdp_id: str = ""
    created_at_utc: str = ""
    created_by: str = ""
    research_proposition: str = ""
    research_graph_ref: str = ""
    data_pit_semantics: str = ""
    dataset_versions: tuple[Any, ...] = ()
    data_source_refs: tuple[str, ...] = ()
    llm_provider: str = ""
    model_routing_policy_ref: str = ""
    llm_call_record_refs: tuple[str, ...] = ()
    replay_state: str = ""
    math_artifact_refs: tuple[str, ...] = ()
    theory_spec_refs: tuple[str, ...] = ()
    responsibility_disclosure_refs: tuple[str, ...] = ()
    asset_versions: tuple[str, ...] = ()
    environment: str = ""
    code_hash: str = ""
    seed: int | None = None
    adversarial_test_refs: tuple[str, ...] = ()
    backtest_run_refs: tuple[str, ...] = ()
    training_run_refs: tuple[str, ...] = ()
    validation_run_refs: tuple[str, ...] = ()
    honest_n: int | None = None
    honest_n_strategy_goal_ref: str = ""
    honest_n_disclosure: str = ""
    selection_process: str = ""
    cost_execution_assumptions: str = ""
    attribution: str = ""
    known_limitations: tuple[str, ...] = ()
    unverified_residual: tuple[str, ...] | None = None
    residual_attestation: str = ""
    verifier_verdict_refs: tuple[str, ...] = ()
    approval_refs: tuple[str, ...] = ()
    promotion_record: str = ""
    deployment_plan: str = ""
    monitor_plan: str = ""
    rollback_plan: str = ""
    retire_plan: str = ""
    environment_lock: str = ""

    def __post_init__(self) -> None:
        if self.asset_kind and self.asset_kind not in _LEGACY_ASSET_KINDS:
            raise ValueError(
                f"asset_kind invalid: {self.asset_kind!r} not in {sorted(_LEGACY_ASSET_KINDS)}"
            )
        tuple_fields = (
            "graph_refs",
            "data_refs",
            "dataset_version_refs",
            "market_data_use_validation_refs",
            "ingestion_skill_refs",
            "mathematical_refs",
            "theory_binding_refs",
            "consistency_check_refs",
            "methodology_choice_refs",
            "responsibility_refs",
            "asset_refs",
            "code_refs",
            "test_refs",
            "run_refs",
            "honest_n_refs",
            "cost_and_execution_assumptions",
            "attribution_refs",
            "known_limits",
            "unverified_residuals",
            "compiler_artifact_refs",
            "mathematical_spine_chain_refs",
            "goal_entrypoint_coverage_refs",
            "deployment_refs",
            "monitor_refs",
            "llm_call_refs",
            "source_file_refs",
            "dataset_versions",
            "data_source_refs",
            "llm_call_record_refs",
            "math_artifact_refs",
            "theory_spec_refs",
            "responsibility_disclosure_refs",
            "asset_versions",
            "adversarial_test_refs",
            "backtest_run_refs",
            "training_run_refs",
            "validation_run_refs",
            "known_limitations",
            "verifier_verdict_refs",
            "approval_refs",
        )
        for name in tuple_fields:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, tuple(value))
        if self.unverified_residuals is not None:
            object.__setattr__(self, "unverified_residuals", tuple(self.unverified_residuals))
        if self.unverified_residual is not None:
            object.__setattr__(self, "unverified_residual", tuple(self.unverified_residual))

        normalized_dataset_versions: list[DatasetVersionRef] = []
        for value in self.dataset_versions:
            if isinstance(value, DatasetVersionRef):
                normalized_dataset_versions.append(value)
            elif isinstance(value, dict):
                normalized_dataset_versions.append(DatasetVersionRef.from_dict(value))
            else:
                raise TypeError(
                    "dataset_versions entries must be DatasetVersionRef objects or JSON objects"
                )
        object.__setattr__(self, "dataset_versions", tuple(normalized_dataset_versions))

        def merge(name: str, values: tuple[str, ...]) -> None:
            current = tuple(getattr(self, name) or ())
            if not current and values:
                object.__setattr__(self, name, tuple(dict.fromkeys(str(value) for value in values if str(value))))

        if not self.research_question and self.research_proposition:
            object.__setattr__(self, "research_question", self.research_proposition)
        if not self.research_proposition and self.research_question:
            object.__setattr__(self, "research_proposition", self.research_question)
        merge("graph_refs", (self.research_graph_ref,) if self.research_graph_ref else ())
        if not self.research_graph_ref and self.graph_refs:
            object.__setattr__(self, "research_graph_ref", self.graph_refs[0])
        merge("data_refs", self.data_source_refs)
        if not self.data_source_refs and self.data_refs:
            object.__setattr__(self, "data_source_refs", self.data_refs)

        legacy_dataset_refs: list[str] = []
        for value in self.dataset_versions:
            dataset_id = value.dataset_id
            version = value.version
            sha = value.manifest_sha256
            legacy_dataset_refs.append(
                f"dataset_version:{dataset_id}:{version}:{sha}" if dataset_id and version else ""
            )
        merge("dataset_version_refs", tuple(legacy_dataset_refs))
        merge("mathematical_refs", self.math_artifact_refs + self.theory_spec_refs)
        merge("responsibility_refs", self.responsibility_disclosure_refs)
        merge("asset_refs", tuple(ref for ref in (self.asset_ref, *self.asset_versions) if ref))
        if not self.asset_ref and self.asset_refs:
            object.__setattr__(self, "asset_ref", self.asset_refs[0])
        merge("test_refs", self.adversarial_test_refs)
        merge("run_refs", self.backtest_run_refs + self.training_run_refs + self.validation_run_refs)
        if not self.environment_lock_ref:
            object.__setattr__(self, "environment_lock_ref", self.environment_lock or self.environment)
        if not self.environment_lock and self.environment_lock_ref:
            object.__setattr__(self, "environment_lock", self.environment_lock_ref)
        if not self.honest_n_refs and self.honest_n is not None and self.honest_n_strategy_goal_ref:
            object.__setattr__(
                self,
                "honest_n_refs",
                (f"ledger_honest_n:{self.honest_n_strategy_goal_ref}:{self.honest_n}:lower_bound",),
            )
        if not self.cost_and_execution_assumptions and self.cost_execution_assumptions:
            object.__setattr__(self, "cost_and_execution_assumptions", (self.cost_execution_assumptions,))
        if not self.attribution_refs and self.attribution:
            object.__setattr__(self, "attribution_refs", (self.attribution,))
        merge("known_limits", self.known_limitations)
        if not self.known_limitations and self.known_limits:
            object.__setattr__(self, "known_limitations", self.known_limits)
        if self.unverified_residuals is None and self.unverified_residual is not None:
            object.__setattr__(self, "unverified_residuals", self.unverified_residual)
        if self.unverified_residual is None and self.unverified_residuals is not None:
            object.__setattr__(self, "unverified_residual", self.unverified_residuals)
        if not self.verifier_verdict_ref and self.verifier_verdict_refs:
            object.__setattr__(self, "verifier_verdict_ref", self.verifier_verdict_refs[0])
        if not self.verifier_verdict_refs and self.verifier_verdict_ref:
            object.__setattr__(self, "verifier_verdict_refs", (self.verifier_verdict_ref,))
        if not self.approval_ref and self.approval_refs:
            object.__setattr__(self, "approval_ref", self.approval_refs[0])
        if not self.approval_refs and self.approval_ref:
            object.__setattr__(self, "approval_refs", (self.approval_ref,))
        merge("deployment_refs", (self.deployment_plan,) if self.deployment_plan else ())
        merge("monitor_refs", (self.monitor_plan,) if self.monitor_plan else ())
        if not self.rollback_plan_ref and self.rollback_plan:
            object.__setattr__(self, "rollback_plan_ref", self.rollback_plan)
        if not self.retire_plan_ref and self.retire_plan:
            object.__setattr__(self, "retire_plan_ref", self.retire_plan)
        merge("llm_call_refs", self.llm_call_record_refs)
        if not self.llm_call_record_refs and self.llm_call_refs:
            object.__setattr__(self, "llm_call_record_refs", self.llm_call_refs)

        version = self.manifest_version or self.schema_version or "rdp.v3"
        object.__setattr__(self, "manifest_version", version)
        object.__setattr__(self, "schema_version", version)
        computed_identity = "rdp_" + content_hash(self._identity_payload())
        supplied_identities = tuple(
            value for value in (str(self.package_id or ""), str(self.rdp_id or "")) if value
        )
        if supplied_identities and any(value != computed_identity for value in supplied_identities):
            raise ValueError("RDP supplied identity does not match canonical content identity")
        object.__setattr__(self, "package_id", computed_identity)
        object.__setattr__(self, "rdp_id", computed_identity)

    @property
    def canonical_package_id(self) -> str:
        return "rdp_" + content_hash(self._identity_payload())

    def _identity_payload(self) -> dict[str, Any]:
        """Content-addressed identity payload, excluding identity and decoration."""

        semantic = _jsonable(self)
        for key in ("package_id", "rdp_id", "created_at_utc", "created_by"):
            semantic.pop(key, None)
        return semantic

    def to_open_json(self) -> str:
        return canonical_json(_jsonable(self))

    def to_open_dict(self) -> dict[str, Any]:
        return _jsonable(self)

    def to_dict(self) -> dict[str, Any]:
        return self.to_open_dict()

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_open_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RDPManifest":
        known = set(cls.__dataclass_fields__)
        payload = {key: value for key, value in data.items() if key in known}
        payload.pop("package_id", None)
        payload.pop("rdp_id", None)
        return cls(**payload)

    @classmethod
    def from_json(cls, text: str) -> "RDPManifest":
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("RDP JSON must contain an object")
        return cls.from_dict(raw)


def manifest_from_qro(
    qro: QRORecord,
    *,
    research_question: str,
    graph_refs: tuple[str, ...],
    data_refs: tuple[str, ...],
    dataset_version_refs: tuple[str, ...],
    market_data_use_validation_refs: tuple[str, ...],
    ingestion_skill_refs: tuple[str, ...],
    consistency_check_refs: tuple[str, ...],
    code_refs: tuple[str, ...],
    environment_lock_ref: str,
    reproducibility_command: str,
    artifact_hash: str,
    test_refs: tuple[str, ...],
    run_refs: tuple[str, ...],
    honest_n_refs: tuple[str, ...],
    cost_and_execution_assumptions: tuple[str, ...],
    attribution_refs: tuple[str, ...],
    unverified_residuals: tuple[str, ...] | None,
    verifier_verdict_ref: str,
    compiler_artifact_refs: tuple[str, ...] = (),
    mathematical_spine_chain_refs: tuple[str, ...] = (),
    goal_entrypoint_coverage_refs: tuple[str, ...] = (),
    responsibility_refs: tuple[str, ...] = (),
    approval_ref: str | None = None,
    deployment_refs: tuple[str, ...] = (),
    monitor_refs: tuple[str, ...] = (),
    rollback_plan_ref: str | None = None,
    retire_plan_ref: str | None = None,
    llm_call_refs: tuple[str, ...] = (),
    source_file_refs: tuple[str, ...] = (),
    residual_attestation: str = "",
) -> RDPManifest:
    binding_refs = (qro.theory_implementation_binding,) if qro.theory_implementation_binding else ()
    methodology_refs = (qro.methodology_choice_ref,) if qro.methodology_choice_ref else ()
    return RDPManifest(
        research_question=research_question,
        graph_refs=graph_refs,
        data_refs=data_refs,
        dataset_version_refs=dataset_version_refs,
        market_data_use_validation_refs=market_data_use_validation_refs,
        ingestion_skill_refs=ingestion_skill_refs,
        mathematical_refs=qro.mathematical_refs,
        theory_binding_refs=binding_refs,
        consistency_check_refs=consistency_check_refs,
        methodology_choice_refs=methodology_refs,
        responsibility_refs=responsibility_refs,
        asset_refs=(qro.qro_id,),
        code_refs=code_refs,
        environment_lock_ref=environment_lock_ref,
        reproducibility_command=reproducibility_command,
        artifact_hash=artifact_hash,
        test_refs=test_refs,
        run_refs=run_refs,
        honest_n_refs=honest_n_refs,
        cost_and_execution_assumptions=cost_and_execution_assumptions,
        attribution_refs=attribution_refs,
        known_limits=qro.known_limits,
        unverified_residuals=unverified_residuals,
        residual_attestation=residual_attestation,
        verifier_verdict_ref=verifier_verdict_ref,
        compiler_artifact_refs=compiler_artifact_refs,
        mathematical_spine_chain_refs=mathematical_spine_chain_refs,
        goal_entrypoint_coverage_refs=goal_entrypoint_coverage_refs,
        approval_ref=approval_ref,
        deployment_refs=deployment_refs,
        monitor_refs=monitor_refs,
        rollback_plan_ref=rollback_plan_ref,
        retire_plan_ref=retire_plan_ref,
        target_runtime=qro.allowed_environment,
        llm_call_refs=llm_call_refs,
        source_file_refs=source_file_refs,
    )


def validate_rdp_manifest(manifest: RDPManifest, *, has_user_waiver: bool = False) -> tuple[RDPViolation, ...]:
    violations: list[RDPViolation] = []

    if (
        manifest.package_id != manifest.canonical_package_id
        or manifest.rdp_id != manifest.canonical_package_id
    ):
        violations.append(
            RDPViolation(
                "content_identity_mismatch",
                "package_id and rdp_id must equal the canonical manifest content identity",
            )
        )

    def required_text(field_name: str, value: str | None) -> None:
        if not str(value or "").strip():
            violations.append(RDPViolation(f"missing_{field_name}", f"{field_name} is required"))

    def required_list(field_name: str, value: tuple[Any, ...]) -> None:
        if not value:
            violations.append(RDPViolation(f"missing_{field_name}", f"{field_name} is required"))

    required_text("research_question", manifest.research_question)
    required_list("graph_refs", manifest.graph_refs)
    required_list("data_refs", manifest.data_refs)
    required_list("dataset_version_refs", manifest.dataset_version_refs)
    required_list("market_data_use_validation_refs", manifest.market_data_use_validation_refs)
    required_list("ingestion_skill_refs", manifest.ingestion_skill_refs)
    required_list("mathematical_refs", manifest.mathematical_refs)
    required_list("theory_binding_refs", manifest.theory_binding_refs)
    required_list("consistency_check_refs", manifest.consistency_check_refs)
    required_list("asset_refs", manifest.asset_refs)
    required_list("code_refs", manifest.code_refs)
    required_text("environment_lock_ref", manifest.environment_lock_ref)
    required_text("reproducibility_command", manifest.reproducibility_command)
    required_text("artifact_hash", manifest.artifact_hash)
    required_list("test_refs", manifest.test_refs)
    required_list("run_refs", manifest.run_refs)
    required_list("honest_n_refs", manifest.honest_n_refs)
    required_list("cost_and_execution_assumptions", manifest.cost_and_execution_assumptions)
    required_list("known_limits", manifest.known_limits)
    if manifest.unverified_residuals is None:
        violations.append(
            RDPViolation(
                "missing_unverified_residuals",
                "unverified_residuals must be explicitly declared",
            )
        )
    elif not manifest.unverified_residuals and not str(
        manifest.residual_attestation or ""
    ).strip():
        violations.append(
            RDPViolation(
                "missing_residual_attestation",
                "an explicit zero-residual declaration requires residual_attestation",
            )
        )
    required_text("verifier_verdict_ref", manifest.verifier_verdict_ref)
    required_list("compiler_artifact_refs", manifest.compiler_artifact_refs)
    required_list("mathematical_spine_chain_refs", manifest.mathematical_spine_chain_refs)
    required_list("goal_entrypoint_coverage_refs", manifest.goal_entrypoint_coverage_refs)

    if has_user_waiver:
        required_list("methodology_choice_refs", manifest.methodology_choice_refs)
        required_list("responsibility_refs", manifest.responsibility_refs)

    runtime = str(manifest.target_runtime.value if isinstance(manifest.target_runtime, Enum) else manifest.target_runtime)
    if runtime in {RuntimeStatus.PAPER.value, RuntimeStatus.TESTNET.value, RuntimeStatus.LIVE.value}:
        required_text("approval_ref", manifest.approval_ref)
    if runtime == RuntimeStatus.LIVE.value:
        required_list("deployment_refs", manifest.deployment_refs)
        required_list("monitor_refs", manifest.monitor_refs)
        required_text("rollback_plan_ref", manifest.rollback_plan_ref)
        required_text("retire_plan_ref", manifest.retire_plan_ref)

    return tuple(violations)


_RDP_V1_EVENT_FIELDS = frozenset(
    {"schema_version", "event_type", "has_user_waiver", "manifest"}
)
_RDP_V2_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "owner_user_id",
        "recorded_by",
        "has_user_waiver",
        "manifest",
    }
)


def _exact_rdp_event_text(value: Any, *, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(f"RDP event {field_name} must be an exact non-empty string")
    return value


def _validated_rdp_manifest_payload(
    raw: Any,
    *,
    has_user_waiver: bool,
    require_current_identity: bool,
) -> RDPManifest:
    if type(raw) is not dict:
        raise ValueError("RDP event missing manifest")
    unknown_fields = set(raw) - set(RDPManifest.__dataclass_fields__)
    if unknown_fields:
        raise ValueError("RDP event manifest has unknown fields")
    if require_current_identity:
        if "package_id" not in raw or "rdp_id" not in raw:
            raise ValueError("RDP schema-v2 manifest must persist both canonical identities")
        manifest = RDPManifest(**raw)
        if (
            raw.get("package_id") != manifest.canonical_package_id
            or raw.get("rdp_id") != manifest.canonical_package_id
        ):
            raise ValueError("RDP schema-v2 manifest identity is not canonical")
    else:
        # Schema-v1 identities were computed by the retired rdp.v2 identity
        # algorithm.  Reconstruct without trusting that obsolete identity, then
        # validate the semantic payload.  The row remains quarantined and is
        # never inserted into an owner map.
        package_id = _exact_rdp_event_text(
            raw.get("package_id"),
            field_name="legacy manifest package_id",
        )
        if not re.fullmatch(r"rdp_[0-9a-f]{16}", package_id):
            raise ValueError("RDP legacy manifest package_id is malformed")
        if raw.get("manifest_version") != "rdp.v2":
            raise ValueError("RDP legacy manifest_version is unsupported")
        expected_legacy_id = "rdp_" + content_hash(
            {
                "manifest_version": raw.get("manifest_version"),
                "research_question": raw.get("research_question"),
                "graph_refs": raw.get("graph_refs"),
                "asset_refs": raw.get("asset_refs"),
                "artifact_hash": raw.get("artifact_hash"),
                "market_data_use_validation_refs": raw.get(
                    "market_data_use_validation_refs"
                ),
                "compiler_artifact_refs": raw.get("compiler_artifact_refs"),
                "mathematical_spine_chain_refs": raw.get(
                    "mathematical_spine_chain_refs"
                ),
                "goal_entrypoint_coverage_refs": raw.get(
                    "goal_entrypoint_coverage_refs"
                ),
                "run_refs": raw.get("run_refs"),
            }
        )
        if package_id != expected_legacy_id:
            raise ValueError("RDP legacy manifest identity is not canonical for rdp.v2")
        legacy_rdp_id = raw.get("rdp_id")
        if legacy_rdp_id is not None and legacy_rdp_id != package_id:
            raise ValueError("RDP legacy manifest identities disagree")
        manifest = RDPManifest.from_dict(raw)
    violations = validate_rdp_manifest(
        manifest,
        has_user_waiver=has_user_waiver,
    )
    if violations:
        raise ValueError(_rdp_violation_message(violations))
    return manifest


def parse_quarantined_rdp_manifest_event_v1(row: Any) -> RDPManifest:
    """Validate one recognized ownerless legacy row without attributing it."""

    if type(row) is not dict or set(row) != _RDP_V1_EVENT_FIELDS:
        raise ValueError("RDP schema-v1 event has an inexact envelope")
    if type(row.get("schema_version")) is not int or row["schema_version"] != 1:
        raise ValueError("RDP schema-v1 event has an unsupported schema_version")
    if row.get("event_type") != "rdp_manifest_recorded":
        raise ValueError(f"unknown RDP event_type={row.get('event_type')!r}")
    waiver = row.get("has_user_waiver")
    if type(waiver) is not bool:
        raise ValueError("RDP event has_user_waiver must be a boolean")
    return _validated_rdp_manifest_payload(
        row.get("manifest"),
        has_user_waiver=waiver,
        require_current_identity=False,
    )


def parse_rdp_manifest_event_v2(
    row: Any,
) -> tuple[str, str, bool, RDPManifest]:
    """Lock-free strict parser shared by the canonical store and closure."""

    if type(row) is not dict or set(row) != _RDP_V2_EVENT_FIELDS:
        raise ValueError("RDP schema-v2 event has an inexact envelope")
    if type(row.get("schema_version")) is not int or row["schema_version"] != 2:
        raise ValueError("RDP schema-v2 event has an unsupported schema_version")
    if row.get("event_type") != "rdp_manifest_recorded":
        raise ValueError(f"unknown RDP event_type={row.get('event_type')!r}")
    owner_user_id = _exact_rdp_event_text(
        row.get("owner_user_id"),
        field_name="owner_user_id",
    )
    recorded_by = _exact_rdp_event_text(
        row.get("recorded_by"),
        field_name="recorded_by",
    )
    waiver = row.get("has_user_waiver")
    if type(waiver) is not bool:
        raise ValueError("RDP event has_user_waiver must be a boolean")
    manifest = _validated_rdp_manifest_payload(
        row.get("manifest"),
        has_user_waiver=waiver,
        require_current_identity=True,
    )
    return owner_user_id, recorded_by, waiver, manifest


def _rdp_event_row(
    manifest: RDPManifest,
    *,
    owner_user_id: str,
    recorded_by: str,
    has_user_waiver: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "event_type": "rdp_manifest_recorded",
        "owner_user_id": owner_user_id,
        "recorded_by": recorded_by,
        "has_user_waiver": bool(has_user_waiver),
        "manifest": manifest.to_open_dict(),
    }


def _rdp_violation_message(violations: tuple[RDPViolation, ...]) -> str:
    return "; ".join(v.code for v in violations) or "RDP manifest rejected"


class RDPStoreCommitUncertain(RuntimeError):
    """An RDP journal mutation could not prove commit or durable rollback."""


@dataclass(frozen=True)
class RDPLegacyQuarantineStatus:
    quarantined_count: int
    status: str


class PersistentRDPStore:
    """Append-only owner-enveloped RDP manifest registry.

    ``package_id`` remains a portable content identity. Authorization is a
    separate server-derived envelope keyed by ``(owner_user_id, package_id)``.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._manifests: dict[tuple[str, str], RDPManifest] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        with self._lock, self._exclusive_lock():
            self._refresh_unlocked()
            return self._legacy_quarantined_count

    @property
    def legacy_quarantine_status(self) -> RDPLegacyQuarantineStatus:
        with self._lock, self._exclusive_lock():
            self._refresh_unlocked()
            count = self._legacy_quarantined_count
            return RDPLegacyQuarantineStatus(
                quarantined_count=count,
                status="read_only_unattributed" if count else "clear",
            )

    def _load_existing(self) -> None:
        with self._lock, self._exclusive_lock():
            self._refresh_unlocked()

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _manifest_from_row(self, row: dict[str, Any]) -> tuple[str, RDPManifest]:
        owner_user_id, _recorded_by, _waiver, manifest = parse_rdp_manifest_event_v2(row)
        return owner_user_id, manifest

    def _replay_unlocked(self) -> tuple[dict[tuple[str, str], RDPManifest], int]:
        manifests: dict[tuple[str, str], RDPManifest] = {}
        legacy_quarantined_count = 0
        if not self._path.exists():
            return manifests, legacy_quarantined_count
        try:
            # JSON permits raw U+2028/U+2029 inside strings.  ``splitlines``
            # treats both as record separators, so JSONL must split only on LF.
            lines = self._path.read_text(encoding="utf-8").split("\n")
        except Exception as exc:  # noqa: BLE001 - unreadable history must fail closed.
            raise ValueError(f"invalid persisted RDP journal at {self._path}") from exc
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("RDP event must be an object")
                if row.get("schema_version") == 1:
                    parse_quarantined_rdp_manifest_event_v1(row)
                    legacy_quarantined_count += 1
                    continue
                owner_user_id, manifest = self._manifest_from_row(row)
                key = (owner_user_id, manifest.package_id)
                existing = manifests.get(key)
                if existing is not None and existing.to_open_dict() != manifest.to_open_dict():
                    raise ValueError("RDP package_id collision with different manifest content")
                manifests[key] = manifest
            except Exception as exc:  # noqa: BLE001 - bad history must block every read/write.
                raise ValueError(
                    f"invalid persisted RDP row at {self._path}:{line_no}"
                ) from exc
        return manifests, legacy_quarantined_count

    def _refresh_unlocked(self) -> dict[tuple[str, str], RDPManifest]:
        # Clear first so a poisoned refresh cannot leave a stale cache available
        # to later private or diagnostic access after the public operation fails.
        self._manifests = {}
        self._legacy_quarantined_count = 0
        manifests, legacy_quarantined_count = self._replay_unlocked()
        self._manifests = manifests
        self._legacy_quarantined_count = legacy_quarantined_count
        return manifests

    @staticmethod
    def _event_bytes(row: dict[str, Any]) -> bytes:
        return (
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise OSError("RDP journal temporary write made no progress")
            offset += written

    def _disk_state(self) -> tuple[bool, bytes]:
        exists = self._path.exists()
        return exists, self._path.read_bytes() if exists else b""

    def _fsync_parent(self) -> None:
        parent_fd = os.open(
            self._path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def _restore_unlocked(self, *, original_exists: bool, original: bytes) -> None:
        if original_exists:
            fd, raw_restore = tempfile.mkstemp(
                prefix=f".{self._path.name}.restore.",
                dir=self._path.parent,
            )
            restore = Path(raw_restore)
            try:
                os.fchmod(fd, 0o600)
                self._write_all(fd, original)
                os.fsync(fd)
                os.close(fd)
                fd = -1
                os.replace(restore, self._path)
            finally:
                if fd >= 0:
                    os.close(fd)
                restore.unlink(missing_ok=True)
        else:
            self._path.unlink(missing_ok=True)
        self._fsync_parent()
        expected = (original_exists, original if original_exists else b"")
        if self._disk_state() != expected:
            raise OSError("RDP journal rollback bytes could not be verified")

    def _atomic_append_unlocked(self, row: dict[str, Any]) -> None:
        original_state = self._disk_state()
        original_exists, original = original_state
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        payload = original + separator + self._event_bytes(row)
        target_state = (True, payload)
        fd, raw_temporary = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            dir=self._path.parent,
        )
        temporary = Path(raw_temporary)
        try:
            os.fchmod(fd, 0o600)
            self._write_all(fd, payload)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, self._path)
            self._fsync_parent()
            if self._disk_state() != target_state:
                raise OSError("RDP journal append bytes could not be verified")
        except Exception as exc:
            try:
                current_state = self._disk_state()
            except Exception as recovery_exc:
                raise RDPStoreCommitUncertain(
                    "RDP journal append failed and journal state cannot be read"
                ) from recovery_exc
            if current_state == original_state:
                raise
            if current_state != target_state:
                raise RDPStoreCommitUncertain(
                    "RDP journal append failed with unexpected journal bytes"
                ) from exc
            try:
                self._restore_unlocked(
                    original_exists=original_exists,
                    original=original,
                )
            except Exception as recovery_exc:  # noqa: BLE001 - disk state is uncertain.
                raise RDPStoreCommitUncertain(
                    "RDP journal append failed and durable rollback is uncertain"
                ) from recovery_exc
            raise
        finally:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _owner(value: Any) -> str:
        return _exact_rdp_event_text(value, field_name="owner_user_id")

    def record_manifest(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str,
        recorded_by: str,
        has_user_waiver: bool = False,
    ) -> RDPManifest:
        owner_user_id = self._owner(owner_user_id)
        recorded_by = _exact_rdp_event_text(recorded_by, field_name="recorded_by")
        if type(has_user_waiver) is not bool:
            raise ValueError("RDP has_user_waiver must be a boolean")
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        key = (owner_user_id, manifest.package_id)
        with self._lock, self._exclusive_lock():
            manifests = self._refresh_unlocked()
            existing = manifests.get(key)
            if existing is not None:
                if existing.to_open_dict() != manifest.to_open_dict():
                    raise ValueError("RDP package_id collision with different manifest content")
                return existing
            row = _rdp_event_row(
                manifest,
                owner_user_id=owner_user_id,
                recorded_by=recorded_by,
                has_user_waiver=has_user_waiver,
            )
            try:
                self._atomic_append_unlocked(row)
            except RDPStoreCommitUncertain:
                self._manifests = {}
                self._legacy_quarantined_count = 0
                raise
            except Exception:
                # _atomic_append_unlocked proved exact rollback; the freshly
                # replayed pre-transaction state remains authoritative.
                self._manifests = manifests
                raise
            manifests[key] = manifest
            self._manifests = manifests
            return manifest

    def manifest(self, package_id: str, *, owner_user_id: str) -> RDPManifest:
        owner = self._owner(owner_user_id)
        with self._lock, self._exclusive_lock():
            manifests = self._refresh_unlocked()
            return manifests[(owner, str(package_id))]

    def manifests(self, *, owner_user_id: str) -> list[RDPManifest]:
        owner_user_id = self._owner(owner_user_id)
        with self._lock, self._exclusive_lock():
            manifests = self._refresh_unlocked()
            return [
                manifest
                for (owner, _package_id), manifest in manifests.items()
                if owner == owner_user_id
            ]


@dataclass(frozen=True)
class RDPPackageRecord:
    package_id: str
    package_dir: str
    manifest_path: str
    refs_index_path: str
    manifest_hash: str
    source_file_refs: tuple[str, ...]
    package_version: str = "rdp.package.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_file_refs", tuple(self.source_file_refs))


@dataclass(frozen=True)
class RDPPackageArchiveRecord:
    package_id: str
    archive_path: str
    archive_sha256: str
    byte_size: int
    file_count: int
    included_paths: tuple[str, ...]
    archive_version: str = "rdp.package_archive.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "included_paths", tuple(self.included_paths))

    def to_open_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True)
class RDPPackagePublishRecord:
    package_id: str
    channel: str
    target_runtime: str
    manifest_hash: str
    archive_sha256: str
    source_archive_path: str
    published_archive_path: str
    byte_size: int
    file_count: int
    published_by: str
    published_at: str
    trust_release_ref: str = ""
    trust_release_approval_ref: str = ""
    publish_hash: str = ""
    publish_version: str = "rdp.local_publish.v1"

    def __post_init__(self) -> None:
        payload = {
            "publish_version": self.publish_version,
            "package_id": self.package_id,
            "channel": self.channel,
            "target_runtime": self.target_runtime,
            "manifest_hash": self.manifest_hash,
            "archive_sha256": self.archive_sha256,
            "source_archive_path": self.source_archive_path,
            "published_archive_path": self.published_archive_path,
            "byte_size": self.byte_size,
            "file_count": self.file_count,
            "published_by": self.published_by,
            "published_at": self.published_at,
        }
        if self.trust_release_ref:
            payload["trust_release_ref"] = self.trust_release_ref
        if self.trust_release_approval_ref:
            payload["trust_release_approval_ref"] = self.trust_release_approval_ref
        expected_hash = "sha16:" + content_hash(payload)
        if self.publish_hash and self.publish_hash != expected_hash:
            raise ValueError("RDP package publish hash mismatch")
        object.__setattr__(self, "publish_hash", expected_hash)

    def to_open_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True)
class RDPExternalPublicationProofRecord:
    package_id: str
    external_channel: str
    target_runtime: str
    local_publish_hash: str
    archive_sha256: str
    external_uri_digest: str
    immutable_pointer_ref: str
    destination_allowlist_ref: str
    trust_release_ref: str
    trust_release_approval_ref: str
    evidence_refs: tuple[str, ...]
    attested_by: str
    attested_at: str
    proof_hash: str = ""
    proof_version: str = "rdp.external_publication_proof.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in _tuple(self.evidence_refs)))
        payload = {
            "proof_version": self.proof_version,
            "package_id": self.package_id,
            "external_channel": self.external_channel,
            "target_runtime": self.target_runtime,
            "local_publish_hash": self.local_publish_hash,
            "archive_sha256": self.archive_sha256,
            "external_uri_digest": self.external_uri_digest,
            "immutable_pointer_ref": self.immutable_pointer_ref,
            "destination_allowlist_ref": self.destination_allowlist_ref,
            "trust_release_ref": self.trust_release_ref,
            "trust_release_approval_ref": self.trust_release_approval_ref,
            "evidence_refs": self.evidence_refs,
            "attested_by": self.attested_by,
            "attested_at": self.attested_at,
        }
        expected_hash = "sha16:" + content_hash(payload)
        if self.proof_hash and self.proof_hash != expected_hash:
            raise ValueError("RDP external publication proof hash mismatch")
        object.__setattr__(self, "proof_hash", expected_hash)

    def to_open_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True)
class RDPCIReleaseAttestationRecord:
    package_id: str
    target_runtime: str
    manifest_hash: str
    local_publish_hash: str
    external_proof_hash: str
    archive_sha256: str
    trust_release_ref: str
    trust_release_approval_ref: str
    ci_system_ref: str
    ci_workflow_ref: str
    ci_run_ref: str
    source_commit_ref: str
    ci_status: str
    artifact_digest: str
    test_report_ref: str
    test_report_hash: str
    build_log_digest: str
    required_check_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    attested_by: str
    attested_at: str
    attestation_hash: str = ""
    attestation_version: str = "rdp.ci_release_attestation.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_check_refs", tuple(str(ref) for ref in _tuple(self.required_check_refs)))
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in _tuple(self.evidence_refs)))
        payload = {
            "attestation_version": self.attestation_version,
            "package_id": self.package_id,
            "target_runtime": self.target_runtime,
            "manifest_hash": self.manifest_hash,
            "local_publish_hash": self.local_publish_hash,
            "external_proof_hash": self.external_proof_hash,
            "archive_sha256": self.archive_sha256,
            "trust_release_ref": self.trust_release_ref,
            "trust_release_approval_ref": self.trust_release_approval_ref,
            "ci_system_ref": self.ci_system_ref,
            "ci_workflow_ref": self.ci_workflow_ref,
            "ci_run_ref": self.ci_run_ref,
            "source_commit_ref": self.source_commit_ref,
            "ci_status": self.ci_status,
            "artifact_digest": self.artifact_digest,
            "test_report_ref": self.test_report_ref,
            "test_report_hash": self.test_report_hash,
            "build_log_digest": self.build_log_digest,
            "required_check_refs": self.required_check_refs,
            "evidence_refs": self.evidence_refs,
            "attested_by": self.attested_by,
            "attested_at": self.attested_at,
        }
        expected_hash = "sha16:" + content_hash(payload)
        if self.attestation_hash and self.attestation_hash != expected_hash:
            raise ValueError("RDP CI release attestation hash mismatch")
        object.__setattr__(self, "attestation_hash", expected_hash)

    def to_open_dict(self) -> dict[str, Any]:
        return _jsonable(self)


_RESERVED_PACKAGE_IDS = {"_archives", "_published"}
_ALLOWED_LOCAL_PUBLISH_CHANNELS = {"local_registry"}
_ALLOWED_EXTERNAL_PUBLISH_CHANNELS = {"object_store", "release_registry", "artifact_registry"}
_EXTERNAL_SECRET_MARKER = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|password|oauth[_-]?token|access[_-]?token|token|secret|x-amz-signature|signature)\s*="
)


def _rdp_owner_user_id(value: Any) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise ValueError("RDP owner_user_id is required")
    return owner


def _rdp_owner_storage_root(package_root: str | Path, owner_user_id: str) -> Path:
    owner = _rdp_owner_user_id(owner_user_id)
    owner_key = hashlib.sha256(owner.encode("utf-8")).hexdigest()
    root = Path(package_root).resolve()
    scoped = (root / "_owners" / owner_key).resolve()
    try:
        scoped.relative_to(root)
    except ValueError as exc:  # pragma: no cover - digest path is defensive.
        raise ValueError("RDP owner storage path escapes package root") from exc
    return scoped


def _resolve_rdp_owner(explicit: str | None, bound: str | None) -> str:
    return _rdp_owner_user_id(explicit or bound)


def _append_owner_enveloped_event(
    path: Path,
    lock_path: Path,
    row: dict[str, Any],
) -> None:
    """Append one owner-enveloped row durably and idempotently across processes."""

    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    held = None
    try:
        os.chmod(lock_path, 0o600)
        held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
        if path.exists():
            with path.open("r", encoding="utf-8") as existing_fh:
                for line in existing_fh:
                    if line.strip() and json.loads(line) == row:
                        return
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            fh.flush()
            os.fsync(fh.fileno())
    finally:
        if held is not None:
            held.release()
        os.close(fd)


def _safe_package_id(package_id: str) -> bool:
    return (
        bool(package_id)
        and package_id not in _RESERVED_PACKAGE_IDS
        and all(ch.isalnum() or ch in {"_", "-"} for ch in package_id)
    )


def _safe_publish_channel(channel: str) -> bool:
    return channel in _ALLOWED_LOCAL_PUBLISH_CHANNELS


def _safe_external_publish_channel(channel: str) -> bool:
    return channel in _ALLOWED_EXTERNAL_PUBLISH_CHANNELS


def _contains_external_secret(value: Any) -> bool:
    if contains_plaintext_secret(value):
        return True
    if isinstance(value, dict):
        return any(_contains_external_secret(child) for child in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_external_secret(child) for child in value)
    return bool(_EXTERNAL_SECRET_MARKER.search(str(value or "")))


def _external_uri_digest(external_uri: str) -> str:
    return "sha16:" + content_hash({"external_uri": external_uri})


def _validate_external_uri_digest(external_uri_digest: str) -> str:
    normalized = str(external_uri_digest or "").strip()
    if not normalized:
        raise ValueError("external_uri_digest is required")
    if not re.fullmatch(r"sha16:[0-9a-f]{16}", normalized):
        raise ValueError("external_uri_digest must be a sha16 digest")
    if _contains_external_secret(normalized):
        raise ValueError("RDP external publication proof cannot contain plaintext secret")
    return normalized


def _validate_external_uri(external_uri: str) -> str:
    normalized = str(external_uri or "").strip()
    if not normalized:
        raise ValueError("external_uri is required")
    if _contains_external_secret(normalized):
        raise ValueError("RDP external publication proof cannot contain plaintext secret")
    parsed = urllib.parse.urlsplit(normalized)
    if parsed.scheme not in {"https", "s3"}:
        raise ValueError("RDP external publication proof requires https or s3 URI")
    if parsed.username or parsed.password:
        raise ValueError("RDP external publication proof URI cannot contain credentials")
    if not parsed.netloc:
        raise ValueError("RDP external publication proof URI requires host or bucket")
    if parsed.query or parsed.fragment:
        raise ValueError("RDP external publication proof URI cannot contain query or fragment")
    return normalized


@dataclass(frozen=True)
class RDPSourceFileBundleEntry:
    source_file_ref: str
    source_path: str
    bundled_path: str
    content_sha256: str
    byte_size: int
    text_encoding: str = "utf-8"


@dataclass(frozen=True)
class RDPSourceFileBundleRecord:
    package_id: str
    package_dir: str
    files_dir: str
    index_path: str
    source_files: tuple[RDPSourceFileBundleEntry, ...]
    bundle_version: str = "rdp.source_bundle.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_files", tuple(self.source_files))

    def to_open_dict(self) -> dict[str, Any]:
        return {
            "bundle_version": self.bundle_version,
            "package_id": self.package_id,
            "files_dir": "source_files",
            "index_path": "source_files_index.json",
            "source_files": [_jsonable(entry) for entry in self.source_files],
        }


_SAFE_BASENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_bundle_basename(path: Path) -> str:
    name = _SAFE_BASENAME_RE.sub("_", path.name).strip("._")
    if not name:
        name = "source"
    return name[:80]


class RDPOpenPackageMaterializer:
    """Materialize accepted RDP manifests into deterministic open package files."""

    def __init__(
        self,
        package_root: str | Path,
        *,
        owner_user_id: str | None = None,
    ) -> None:
        self._package_root = Path(package_root)
        self._package_root.mkdir(parents=True, exist_ok=True)
        self._owner_user_id = str(owner_user_id or "").strip() or None

    @property
    def package_root(self) -> Path:
        return self._package_root

    def materialize(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
        has_user_waiver: bool = False,
    ) -> RDPPackageRecord:
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if not _safe_package_id(manifest.package_id):
            raise ValueError("RDP package_id is unsafe")

        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        owner_root = _rdp_owner_storage_root(self._package_root, owner)
        package_dir = owner_root / manifest.package_id
        package_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = package_dir / "manifest.json"
        refs_index_path = package_dir / "refs.json"

        manifest_dict = manifest.to_open_dict()
        manifest_json = canonical_json(manifest_dict)
        manifest_hash = "sha16:" + content_hash(manifest_dict)
        refs_index = {
            "package_id": manifest.package_id,
            "manifest_hash": manifest_hash,
            "graph_refs": list(manifest.graph_refs),
            "asset_refs": list(manifest.asset_refs),
            "data_refs": list(manifest.data_refs),
            "dataset_version_refs": list(manifest.dataset_version_refs),
            "market_data_use_validation_refs": list(manifest.market_data_use_validation_refs),
            "ingestion_skill_refs": list(manifest.ingestion_skill_refs),
            "mathematical_refs": list(manifest.mathematical_refs),
            "theory_binding_refs": list(manifest.theory_binding_refs),
            "consistency_check_refs": list(manifest.consistency_check_refs),
            "methodology_choice_refs": list(manifest.methodology_choice_refs),
            "responsibility_refs": list(manifest.responsibility_refs),
            "code_refs": list(manifest.code_refs),
            "test_refs": list(manifest.test_refs),
            "run_refs": list(manifest.run_refs),
            "compiler_artifact_refs": list(manifest.compiler_artifact_refs),
            "mathematical_spine_chain_refs": list(manifest.mathematical_spine_chain_refs),
            "goal_entrypoint_coverage_refs": list(manifest.goal_entrypoint_coverage_refs),
            "source_file_refs": list(manifest.source_file_refs),
            "artifact_hash": manifest.artifact_hash,
            "environment_lock_ref": manifest.environment_lock_ref,
            "reproducibility_command": manifest.reproducibility_command,
        }

        manifest_payload = manifest_json + "\n"
        if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != manifest_payload:
            raise ValueError("RDP package manifest path exists with different content")
        manifest_path.write_text(manifest_payload, encoding="utf-8")
        refs_index_path.write_text(canonical_json(refs_index) + "\n", encoding="utf-8")

        return RDPPackageRecord(
            package_id=manifest.package_id,
            package_dir=str(package_dir),
            manifest_path=str(manifest_path),
            refs_index_path=str(refs_index_path),
            manifest_hash=manifest_hash,
            source_file_refs=manifest.source_file_refs,
        )


class RDPSourceFileBundler:
    """Copy declared RDP source refs into package files without widening FS access."""

    def __init__(
        self,
        package_root: str | Path,
        source_root: str | Path,
        *,
        max_bytes: int = 1_000_000,
        owner_user_id: str | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("RDP source max_bytes must be positive")
        self._package_root = Path(package_root).resolve()
        self._package_root.mkdir(parents=True, exist_ok=True)
        self._source_root = Path(source_root).resolve()
        self._max_bytes = int(max_bytes)
        self._owner_user_id = str(owner_user_id or "").strip() or None

    @property
    def package_root(self) -> Path:
        return self._package_root

    @property
    def source_root(self) -> Path:
        return self._source_root

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def _package_dir(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
    ) -> Path:
        if not _safe_package_id(manifest.package_id):
            raise ValueError("RDP package_id is unsafe")
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        owner_root = _rdp_owner_storage_root(self._package_root, owner)
        package_dir = (owner_root / manifest.package_id).resolve()
        try:
            package_dir.relative_to(owner_root)
        except ValueError as exc:
            raise ValueError("RDP package path escapes package root") from exc
        if not (package_dir / "manifest.json").exists():
            raise ValueError("RDP package must be materialized before bundling source files")
        return package_dir

    def _resolve_source_path(self, source_path: str) -> tuple[Path, Path]:
        raw = Path(str(source_path or ""))
        if str(raw).strip() in {"", "."}:
            raise ValueError("source file path is required")
        if raw.is_absolute():
            raise ValueError("source file path must be relative")
        resolved = (self._source_root / raw).resolve()
        try:
            relative = resolved.relative_to(self._source_root)
        except ValueError as exc:
            raise ValueError("source file path escapes source root") from exc
        if not resolved.exists():
            raise ValueError("source file path does not exist")
        if not resolved.is_file():
            raise ValueError("source file path is not a file")
        return resolved, relative

    def _validate_source_refs(self, manifest: RDPManifest, provided_refs: set[str]) -> None:
        declared = set(manifest.source_file_refs)
        if not declared:
            raise ValueError("RDP manifest has no source_file_refs")
        undeclared = sorted(provided_refs - declared)
        if undeclared:
            raise ValueError(f"source file ref not declared: {undeclared[0]}")
        missing = sorted(declared - provided_refs)
        if missing:
            raise ValueError(f"missing source file mapping: {missing[0]}")

    def _validate_source_map(self, manifest: RDPManifest, source_map: dict[str, str]) -> None:
        self._validate_source_refs(manifest, set(source_map))

    def _validated_source_content(self, content: bytes) -> str:
        if len(content) > self._max_bytes:
            raise ValueError("source file exceeds RDP bundle max_bytes")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("source file must be UTF-8 text") from exc
        if contains_plaintext_secret(text):
            raise ValueError("source file appears to contain plaintext secret")
        return text

    @staticmethod
    def _trusted_source_path(source_ref: str) -> Path:
        """Derive a package-local provenance label without accepting a caller path."""

        _prefix, separator, suffix = str(source_ref).partition(":")
        raw = Path(suffix if separator else source_ref)
        if str(raw).strip() in {"", "."}:
            raise ValueError("source file path is required")
        if raw.is_absolute():
            raise ValueError("source file path must be relative")
        if any(part in {"", ".", ".."} for part in raw.parts):
            raise ValueError("source file path escapes source root")
        return raw

    def _write_bundle(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None,
        sources: list[tuple[str, Path, bytes]],
    ) -> RDPSourceFileBundleRecord:
        package_dir = self._package_dir(manifest, owner_user_id=owner_user_id)
        files_dir = package_dir / "source_files"
        files_dir.mkdir(parents=True, exist_ok=True)
        entries: list[RDPSourceFileBundleEntry] = []

        for source_ref, relative_path, content in sources:
            content_sha256 = hashlib.sha256(content).hexdigest()
            bundled_name = f"{content_sha256[:16]}-{_safe_bundle_basename(relative_path)}"
            bundled_path = files_dir / bundled_name
            if bundled_path.exists() and bundled_path.read_bytes() != content:
                raise ValueError("RDP source bundle path exists with different content")
            bundled_path.write_bytes(content)
            entries.append(
                RDPSourceFileBundleEntry(
                    source_file_ref=source_ref,
                    source_path=relative_path.as_posix(),
                    bundled_path=f"source_files/{bundled_name}",
                    content_sha256=f"sha256:{content_sha256}",
                    byte_size=len(content),
                )
            )

        record = RDPSourceFileBundleRecord(
            package_id=manifest.package_id,
            package_dir=str(package_dir),
            files_dir=str(files_dir),
            index_path=str(package_dir / "source_files_index.json"),
            source_files=tuple(entries),
        )
        Path(record.index_path).write_text(
            canonical_json(record.to_open_dict()) + "\n",
            encoding="utf-8",
        )
        return record

    def bundle(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
        source_map: dict[str, str],
        has_user_waiver: bool = False,
    ) -> RDPSourceFileBundleRecord:
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if not isinstance(source_map, dict):
            raise ValueError("source_map must be an object")
        normalized_map = {str(ref): str(path) for ref, path in source_map.items()}
        self._validate_source_map(manifest, normalized_map)

        sources: list[tuple[str, Path, bytes]] = []
        for source_ref in manifest.source_file_refs:
            source_path, relative_path = self._resolve_source_path(normalized_map[source_ref])
            content = source_path.read_bytes()
            self._validated_source_content(content)
            sources.append((source_ref, relative_path, content))
        return self._write_bundle(
            manifest,
            owner_user_id=owner_user_id,
            sources=sources,
        )

    def bundle_trusted_text_sources(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
        source_texts: dict[str, str],
        has_user_waiver: bool = False,
    ) -> RDPSourceFileBundleRecord:
        """Bundle exact server-resolved text without exposing raw-content HTTP input."""

        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if not isinstance(source_texts, dict):
            raise ValueError("source_texts must be an object")
        normalized_texts: dict[str, str] = {}
        for source_ref, text in source_texts.items():
            if not isinstance(source_ref, str):
                raise ValueError("source file ref must be a string")
            normalized_texts[source_ref] = text
        self._validate_source_refs(manifest, set(normalized_texts))

        sources: list[tuple[str, Path, bytes]] = []
        for source_ref in manifest.source_file_refs:
            text = normalized_texts[source_ref]
            if not isinstance(text, str):
                raise ValueError("source text must be a string")
            try:
                content = text.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("source file must be UTF-8 text") from exc
            self._validated_source_content(content)
            sources.append((source_ref, self._trusted_source_path(source_ref), content))
        return self._write_bundle(
            manifest,
            owner_user_id=owner_user_id,
            sources=sources,
        )


@dataclass(frozen=True)
class RDPDeploymentAttestationRecord:
    package_id: str
    deployment_ref: str
    target_runtime: str
    manifest_hash: str
    manifest_file_sha256: str
    refs_index_sha256: str
    source_bundle_index_sha256: str
    approval_ref: str | None
    monitor_refs: tuple[str, ...]
    rollback_plan_ref: str | None
    retire_plan_ref: str | None
    attested_by: str
    attested_at: str
    deployment_event_ref: str = ""
    deployment_artifact_digest: str = ""
    evidence_refs: tuple[str, ...] = ()
    attestation_hash: str = ""
    attestation_version: str = "rdp.deployment_attestation.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "monitor_refs", tuple(self.monitor_refs))
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in _tuple(self.evidence_refs)))
        payload = {
            "attestation_version": self.attestation_version,
            "package_id": self.package_id,
            "deployment_ref": self.deployment_ref,
            "target_runtime": self.target_runtime,
            "manifest_hash": self.manifest_hash,
            "manifest_file_sha256": self.manifest_file_sha256,
            "refs_index_sha256": self.refs_index_sha256,
            "source_bundle_index_sha256": self.source_bundle_index_sha256,
            "approval_ref": self.approval_ref,
            "monitor_refs": self.monitor_refs,
            "rollback_plan_ref": self.rollback_plan_ref,
            "retire_plan_ref": self.retire_plan_ref,
            "attested_by": self.attested_by,
            "attested_at": self.attested_at,
        }
        if (
            self.attestation_version != "rdp.deployment_attestation.v1"
            or self.deployment_event_ref
            or self.deployment_artifact_digest
            or self.evidence_refs
        ):
            payload["deployment_event_ref"] = self.deployment_event_ref
            payload["deployment_artifact_digest"] = self.deployment_artifact_digest
            payload["evidence_refs"] = self.evidence_refs
        expected_hash = "sha16:" + content_hash(payload)
        if self.attestation_hash and self.attestation_hash != expected_hash:
            raise ValueError("RDP deployment attestation hash mismatch")
        object.__setattr__(self, "attestation_hash", expected_hash)

    def to_open_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True)
class RDPDeploymentHealthCheckRecord:
    package_id: str
    deployment_ref: str
    target_runtime: str
    manifest_hash: str
    deployment_attestation_hash: str
    health_status: str
    health_check_refs: tuple[str, ...]
    monitor_refs: tuple[str, ...]
    rollback_plan_ref: str
    rollback_readiness_ref: str
    rollback_drill_ref: str
    retire_plan_ref: str
    evidence_refs: tuple[str, ...]
    attested_by: str
    attested_at: str
    proof_hash: str = ""
    proof_version: str = "rdp.deployment_health.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "health_check_refs", tuple(str(ref) for ref in _tuple(self.health_check_refs)))
        object.__setattr__(self, "monitor_refs", tuple(str(ref) for ref in _tuple(self.monitor_refs)))
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in _tuple(self.evidence_refs)))
        payload = {
            "proof_version": self.proof_version,
            "package_id": self.package_id,
            "deployment_ref": self.deployment_ref,
            "target_runtime": self.target_runtime,
            "manifest_hash": self.manifest_hash,
            "deployment_attestation_hash": self.deployment_attestation_hash,
            "health_status": self.health_status,
            "health_check_refs": self.health_check_refs,
            "monitor_refs": self.monitor_refs,
            "rollback_plan_ref": self.rollback_plan_ref,
            "rollback_readiness_ref": self.rollback_readiness_ref,
            "rollback_drill_ref": self.rollback_drill_ref,
            "retire_plan_ref": self.retire_plan_ref,
            "evidence_refs": self.evidence_refs,
            "attested_by": self.attested_by,
            "attested_at": self.attested_at,
        }
        expected_hash = "sha16:" + content_hash(payload)
        if self.proof_hash and self.proof_hash != expected_hash:
            raise ValueError("RDP deployment health proof hash mismatch")
        object.__setattr__(self, "proof_hash", expected_hash)

    def to_open_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True)
class RDPSourceRunIntegrityRecord:
    package_id: str
    run_ref: str
    run_id: str
    source_file_ref: str
    manifest_hash: str
    manifest_file_sha256: str
    refs_index_sha256: str
    source_bundle_index_sha256: str
    bundled_source_sha256: str
    run_manifest_sha256: str
    run_strategy_sha256: str
    run_portfolio_sha256: str
    artifact_hash: str
    attested_by: str
    attested_at: str
    integrity_hash: str = ""
    attestation_version: str = "rdp.source_run_integrity.v1"

    def __post_init__(self) -> None:
        payload = {
            "attestation_version": self.attestation_version,
            "package_id": self.package_id,
            "run_ref": self.run_ref,
            "run_id": self.run_id,
            "source_file_ref": self.source_file_ref,
            "manifest_hash": self.manifest_hash,
            "manifest_file_sha256": self.manifest_file_sha256,
            "refs_index_sha256": self.refs_index_sha256,
            "source_bundle_index_sha256": self.source_bundle_index_sha256,
            "bundled_source_sha256": self.bundled_source_sha256,
            "run_manifest_sha256": self.run_manifest_sha256,
            "run_strategy_sha256": self.run_strategy_sha256,
            "run_portfolio_sha256": self.run_portfolio_sha256,
            "artifact_hash": self.artifact_hash,
            "attested_by": self.attested_by,
            "attested_at": self.attested_at,
        }
        expected_hash = "sha16:" + content_hash(payload)
        if self.integrity_hash and self.integrity_hash != expected_hash:
            raise ValueError("RDP source-run integrity hash mismatch")
        object.__setattr__(self, "integrity_hash", expected_hash)

    def to_open_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime_text(value: RuntimeStatus | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def rdp_run_artifact_hash(
    *,
    run_manifest_sha256: str,
    run_strategy_sha256: str,
    run_portfolio_sha256: str,
) -> str:
    payload = {
        "run_manifest_sha256": run_manifest_sha256,
        "run_strategy_sha256": run_strategy_sha256,
        "run_portfolio_sha256": run_portfolio_sha256,
    }
    return "sha256:" + hashlib.sha256((canonical_json(payload) + "\n").encode("utf-8")).hexdigest()


def _load_source_bundle_index_row(index_path: Path, manifest: RDPManifest) -> dict[str, Any]:
    if not index_path.exists():
        raise ValueError("RDP source bundle index is required before deployment attestation")
    try:
        row = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - malformed open package must fail closed.
        raise ValueError("RDP source bundle index is invalid") from exc
    if row.get("package_id") != manifest.package_id:
        raise ValueError("RDP source bundle package_id does not match manifest")
    if row.get("files_dir") != "source_files" or row.get("index_path") != "source_files_index.json":
        raise ValueError("RDP source bundle index paths must be package-relative")
    if "package_dir" in row:
        raise ValueError("RDP source bundle index must not contain local package_dir")
    source_files = row.get("source_files")
    if not isinstance(source_files, list):
        raise ValueError("RDP source bundle index is invalid")
    refs = tuple(str(entry.get("source_file_ref") or "") for entry in source_files if isinstance(entry, dict))
    if refs != manifest.source_file_refs:
        raise ValueError("RDP source bundle refs do not match manifest source_file_refs")
    for entry in source_files:
        if not isinstance(entry, dict):
            raise ValueError("RDP source bundle index is invalid")
        bundled_path = str(entry.get("bundled_path") or "")
        if Path(bundled_path).is_absolute() or not bundled_path.startswith("source_files/"):
            raise ValueError("RDP source bundle path must be package-relative")
        if not str(entry.get("content_sha256") or "").startswith("sha256:"):
            raise ValueError("RDP source bundle entry missing content_sha256")
    return row


def _load_source_bundle_index(index_path: Path, manifest: RDPManifest) -> str:
    _load_source_bundle_index_row(index_path, manifest)
    return _file_sha256(index_path)


def _source_bundle_entry_for_ref(index_row: dict[str, Any], source_file_ref: str) -> dict[str, Any]:
    for entry in index_row.get("source_files") or ():
        if isinstance(entry, dict) and entry.get("source_file_ref") == source_file_ref:
            return entry
    raise ValueError("RDP source_file_ref is not bundled")


def _safe_run_id(run_id: str) -> bool:
    return (
        bool(run_id)
        and run_id not in {".", ".."}
        and all(ch.isalnum() or ch in {"_", "-", "."} for ch in run_id)
    )


def _resolve_run_dir(run_root: str | Path, run_id: str) -> Path:
    if not _safe_run_id(run_id):
        raise ValueError("RDP run_id is unsafe")
    root = Path(run_root).resolve()
    run_dir = root / run_id
    if run_dir.is_symlink():
        raise ValueError("RDP run directory refuses symlink")
    resolved = run_dir.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("RDP run path escapes run root") from exc
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError("RDP run artifacts are required before source-run integrity attestation")
    return resolved


def _required_run_file(run_dir: Path, name: str) -> Path:
    path = run_dir / name
    if path.is_symlink():
        raise ValueError("RDP source-run integrity refuses symlink")
    if not path.exists() or not path.is_file():
        raise ValueError(f"RDP run artifact is required: {name}")
    return path


def _run_ref_for_id(manifest: RDPManifest, run_id: str) -> str:
    for run_ref in manifest.run_refs:
        text = str(run_ref)
        if text in {run_id, f"run:{run_id}", f"ide_run:{run_id}"}:
            return text
    raise ValueError("run_id is not declared in manifest run_refs")


def _verified_bundled_source_hash(package_dir: Path, source_entry: dict[str, Any]) -> str:
    bundled_path = package_dir / str(source_entry.get("bundled_path") or "")
    if bundled_path.is_symlink():
        raise ValueError("RDP source-run integrity refuses symlink")
    resolved = bundled_path.resolve()
    try:
        resolved.relative_to(package_dir)
    except ValueError as exc:
        raise ValueError("RDP source bundle path escapes package root") from exc
    if not resolved.exists() or not resolved.is_file():
        raise ValueError("RDP bundled source file is required")
    actual_hash = _file_sha256(resolved)
    if actual_hash != str(source_entry.get("content_sha256") or ""):
        raise ValueError("RDP bundled source hash does not match source bundle index")
    if resolved.stat().st_size != source_entry.get("byte_size"):
        raise ValueError("RDP bundled source byte_size does not match source bundle index")
    return actual_hash


def _validate_ide_run_source_snapshot(
    *,
    run_ref: str,
    run_id: str,
    owner_user_id: str,
    run_manifest: dict[str, Any],
    run_manifest_path: Path,
    run_strategy_path: Path,
    run_portfolio_path: Path,
    run_strategy_hash: str,
    run_portfolio_hash: str,
) -> None:
    if run_ref != f"ide_run:{run_id}":
        return
    if run_manifest.get("artifact_version") != "ide.source_run.v1":
        raise ValueError("RDP ide_run requires an immutable IDE source-run manifest")
    if run_manifest.get("status") != "completed":
        raise ValueError("RDP ide_run requires status=completed")
    canonical_manifest = (canonical_json(run_manifest) + "\n").encode("utf-8")
    if run_manifest_path.read_bytes() != canonical_manifest:
        raise ValueError("RDP ide_run run.json is not canonical")

    source = run_manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("RDP ide_run source binding is required")
    if source.get("kind") != "ide_sandbox" or source.get("ide_run_id") != run_id:
        raise ValueError("RDP ide_run source binding does not match requested run_id")
    if str(source.get("owner_user_id") or "").strip() != owner_user_id:
        raise ValueError("RDP ide_run source owner does not match package owner")
    if source.get("strategy_file_sha256") != run_strategy_hash:
        raise ValueError("RDP ide_run strategy file hash does not match source binding")
    if source.get("portfolio_file_sha256") != run_portfolio_hash:
        raise ValueError("RDP ide_run portfolio hash does not match source binding")

    try:
        strategy_text = run_strategy_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("RDP ide_run strategy.py must be UTF-8 text") from exc
    if source.get("strategy_code_content_hash") != content_hash(strategy_text):
        raise ValueError("RDP ide_run strategy content hash does not match strategy.py")
    strategy_identity = {
        "name": str(source.get("strategy_name") or ""),
        "code": strategy_text,
        "asset_class": str(source.get("strategy_asset_class") or ""),
    }
    if (
        not strategy_identity["name"]
        or not strategy_identity["asset_class"]
        or source.get("strategy_content_hash") != content_hash(strategy_identity)
    ):
        raise ValueError("RDP ide_run strategy identity hash does not match strategy.py")

    result_path = _required_run_file(run_manifest_path.parent, "result.json")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - malformed source result must fail closed.
        raise ValueError("RDP ide_run result.json is invalid") from exc
    if not isinstance(result, dict):
        raise ValueError("RDP ide_run result.json must be an object")
    result_hash = _file_sha256(result_path)
    if source.get("result_file_sha256") != result_hash:
        raise ValueError("RDP ide_run result file hash does not match source binding")
    if source.get("result_content_hash") != content_hash(result):
        raise ValueError("RDP ide_run result content hash does not match result.json")


def _select_source_file_ref(manifest: RDPManifest, source_file_ref: str | None) -> str:
    if not manifest.source_file_refs:
        raise ValueError("RDP source_file_refs are required before source-run integrity attestation")
    if source_file_ref:
        selected = str(source_file_ref)
        if selected not in manifest.source_file_refs:
            raise ValueError("source_file_ref is not declared in manifest source_file_refs")
        return selected
    if len(manifest.source_file_refs) == 1:
        return manifest.source_file_refs[0]
    raise ValueError("source_file_ref is required when manifest declares multiple source_file_refs")


class RDPPackageArchiveExporter:
    """Create deterministic downloadable archives for materialized RDP packages."""

    _FIXED_ZIP_DT = (1980, 1, 1, 0, 0, 0)

    def __init__(
        self,
        package_root: str | Path,
        *,
        max_files: int = 10_000,
        max_bytes: int = 250_000_000,
        owner_user_id: str | None = None,
    ) -> None:
        if max_files <= 0:
            raise ValueError("RDP archive max_files must be positive")
        if max_bytes <= 0:
            raise ValueError("RDP archive max_bytes must be positive")
        self._package_root = Path(package_root).resolve()
        self._package_root.mkdir(parents=True, exist_ok=True)
        self._archive_root = self._package_root / "_archives"
        self._max_files = int(max_files)
        self._max_bytes = int(max_bytes)
        self._owner_user_id = str(owner_user_id or "").strip() or None

    @property
    def package_root(self) -> Path:
        return self._package_root

    @property
    def archive_root(self) -> Path:
        return self._archive_root

    def _package_dir(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
    ) -> Path:
        if not _safe_package_id(manifest.package_id):
            raise ValueError("RDP package_id is unsafe")
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        owner_root = _rdp_owner_storage_root(self._package_root, owner)
        package_dir = owner_root / manifest.package_id
        if package_dir.is_symlink():
            raise ValueError("RDP package archive refuses symlink")
        resolved = package_dir.resolve()
        try:
            resolved.relative_to(owner_root)
        except ValueError as exc:
            raise ValueError("RDP package path escapes package root") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError("RDP package must be materialized before archive export")
        return resolved

    def _validated_package_dir(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
        has_user_waiver: bool,
    ) -> Path:
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        package_dir = self._package_dir(manifest, owner_user_id=owner)
        manifest_path = package_dir / "manifest.json"
        refs_index_path = package_dir / "refs.json"
        if not manifest_path.exists() or not refs_index_path.exists():
            raise ValueError("RDP package must be materialized before archive export")
        manifest_payload = canonical_json(manifest.to_open_dict()) + "\n"
        if manifest_path.read_text(encoding="utf-8") != manifest_payload:
            raise ValueError("RDP package manifest file does not match recorded manifest")
        if manifest.source_file_refs:
            _load_source_bundle_index(package_dir / "source_files_index.json", manifest)
        return package_dir

    def _package_files(self, package_dir: Path) -> list[tuple[Path, str, int]]:
        files: list[tuple[Path, str, int]] = []
        total_bytes = 0
        for path in sorted(package_dir.rglob("*"), key=lambda item: item.relative_to(package_dir).as_posix()):
            if path.is_symlink():
                raise ValueError("RDP package archive refuses symlink")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError("RDP package archive only supports regular files")
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(package_dir)
            except ValueError as exc:
                raise ValueError("RDP package archive path escapes package root") from exc
            byte_size = path.stat().st_size
            total_bytes += byte_size
            if len(files) + 1 > self._max_files:
                raise ValueError("RDP package archive exceeds max_files")
            if total_bytes > self._max_bytes:
                raise ValueError("RDP package archive exceeds max_bytes")
            files.append((path, relative.as_posix(), byte_size))
        if not files:
            raise ValueError("RDP package archive has no files")
        return files

    def export(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
        has_user_waiver: bool = False,
    ) -> RDPPackageArchiveRecord:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        package_dir = self._validated_package_dir(
            manifest,
            owner_user_id=owner,
            has_user_waiver=has_user_waiver,
        )
        files = self._package_files(package_dir)
        archive_root = _rdp_owner_storage_root(
            self._package_root,
            owner,
        ) / "_archives"
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = archive_root / f"{manifest.package_id}.zip"
        tmp_path = archive_root / f".{manifest.package_id}.zip.tmp"
        if tmp_path.exists():
            tmp_path.unlink()
        included_paths: list[str] = []
        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path, relative, _byte_size in files:
                    arcname = f"{manifest.package_id}/{relative}"
                    info = zipfile.ZipInfo(arcname, date_time=self._FIXED_ZIP_DT)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o644 << 16
                    archive.writestr(info, path.read_bytes())
                    included_paths.append(arcname)
            tmp_path.replace(archive_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        archive_bytes = archive_path.read_bytes()
        return RDPPackageArchiveRecord(
            package_id=manifest.package_id,
            archive_path=str(archive_path),
            archive_sha256="sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
            byte_size=len(archive_bytes),
            file_count=len(included_paths),
            included_paths=tuple(included_paths),
        )


class RDPLocalPackagePublisher:
    """Publish archived RDP packages into a local registry directory."""

    def __init__(
        self,
        package_root: str | Path,
        publish_root: str | Path | None = None,
        *,
        owner_user_id: str | None = None,
    ) -> None:
        self._package_root = Path(package_root).resolve()
        self._archive_root = self._package_root / "_archives"
        self._publish_root = Path(publish_root).resolve() if publish_root else self._package_root
        self._publish_root.mkdir(parents=True, exist_ok=True)
        self._owner_user_id = str(owner_user_id or "").strip() or None

    @property
    def publish_root(self) -> Path:
        return self._publish_root

    def _validated_archive(
        self,
        archive: RDPPackageArchiveRecord,
        *,
        owner_user_id: str | None = None,
    ) -> Path:
        archive_path = Path(archive.archive_path)
        if archive_path.is_symlink():
            raise ValueError("RDP package publish refuses symlink archive")
        resolved = archive_path.resolve()
        try:
            owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
            owner_archive_root = _rdp_owner_storage_root(
                self._package_root,
                owner,
            ) / "_archives"
            resolved.relative_to(owner_archive_root.resolve())
        except ValueError as exc:
            raise ValueError("RDP package publish source must come from archive exporter") from exc
        if not resolved.exists() or not resolved.is_file():
            raise ValueError("RDP archive is required before package publish")
        archive_sha256 = _file_sha256(resolved)
        if archive_sha256 != archive.archive_sha256:
            raise ValueError("RDP archive sha256 mismatch before package publish")
        if resolved.stat().st_size != archive.byte_size:
            raise ValueError("RDP archive byte_size mismatch before package publish")
        return resolved

    def _published_archive_path(
        self,
        package_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> Path:
        if not _safe_package_id(package_id):
            raise ValueError("RDP package_id is unsafe")
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        owner_publish_root = _rdp_owner_storage_root(
            self._publish_root,
            owner,
        ) / "_published"
        publish_dir = owner_publish_root / package_id
        if publish_dir.is_symlink():
            raise ValueError("RDP package publish refuses symlink destination")
        publish_dir.mkdir(parents=True, exist_ok=True)
        resolved_dir = publish_dir.resolve()
        try:
            resolved_dir.relative_to(owner_publish_root)
        except ValueError as exc:
            raise ValueError("RDP package publish path escapes publish root") from exc
        dest = resolved_dir / f"{package_id}.zip"
        if dest.is_symlink():
            raise ValueError("RDP package publish refuses symlink destination")
        return dest

    def publish(
        self,
        manifest: RDPManifest,
        archive: RDPPackageArchiveRecord,
        *,
        owner_user_id: str | None = None,
        channel: str = "local_registry",
        published_by: str,
        published_at: str | None = None,
        has_user_waiver: bool = False,
        trust_release_ref: str = "",
        trust_release_approval_ref: str = "",
    ) -> RDPPackagePublishRecord:
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if archive.package_id != manifest.package_id:
            raise ValueError("RDP archive package_id does not match manifest")
        if not _safe_publish_channel(channel):
            raise ValueError("RDP package publish only supports local_registry")
        if not str(published_by or "").strip():
            raise ValueError("published_by is required")
        if not str(trust_release_ref or "").strip():
            raise ValueError("trust_release_ref is required before RDP package publish")
        if not str(trust_release_approval_ref or "").strip():
            raise ValueError("trust_release_approval_ref is required before RDP package publish")

        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        source_archive = self._validated_archive(
            archive,
            owner_user_id=owner,
        )
        published_archive = self._published_archive_path(
            manifest.package_id,
            owner_user_id=owner,
        )
        tmp_path = published_archive.with_suffix(".zip.tmp")
        if tmp_path.exists():
            tmp_path.unlink()
        try:
            shutil.copyfile(source_archive, tmp_path)
            tmp_path.replace(published_archive)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        record = RDPPackagePublishRecord(
            package_id=manifest.package_id,
            channel=channel,
            target_runtime=_runtime_text(manifest.target_runtime),
            manifest_hash="sha16:" + content_hash(manifest.to_open_dict()),
            archive_sha256=archive.archive_sha256,
            source_archive_path=str(source_archive),
            published_archive_path=str(published_archive),
            byte_size=archive.byte_size,
            file_count=archive.file_count,
            published_by=published_by,
            published_at=published_at or dt.datetime.now(dt.UTC).isoformat(),
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
        )
        publication_path = published_archive.parent / "publication.json"
        publication_tmp = publication_path.with_suffix(".json.tmp")
        if publication_path.is_symlink():
            raise ValueError("RDP package publish refuses symlink publication metadata")
        try:
            publication_tmp.write_text(canonical_json(record.to_open_dict()) + "\n", encoding="utf-8")
            publication_tmp.replace(publication_path)
        finally:
            if publication_tmp.exists():
                publication_tmp.unlink()
        return record


def _deployment_event_row(
    record: RDPDeploymentAttestationRecord,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "event_type": "rdp_deployment_attestation_recorded",
        "owner_user_id": _rdp_owner_user_id(owner_user_id),
        "record": record.to_open_dict(),
    }


class PersistentRDPDeploymentAttestationStore:
    """Append-only JSONL audit for RDP deployment attestation records."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner_user_id: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], list[RDPDeploymentAttestationRecord]] = {}
        self._owner_user_id = str(owner_user_id or "").strip() or None
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
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad history must block startup.
                    raise ValueError(f"invalid persisted RDP deployment attestation at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        _append_owner_enveloped_event(self._path, self._lock_path, row)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> RDPDeploymentAttestationRecord:
        if row.get("schema_version") != 2:
            raise ValueError("owner-enveloped RDP deployment attestation schema_version=2 is required")
        if row.get("event_type") != "rdp_deployment_attestation_recorded":
            raise ValueError(f"unknown RDP deployment attestation event_type={row.get('event_type')!r}")
        raw = row.get("record")
        if not isinstance(raw, dict):
            raise ValueError("RDP deployment attestation event missing record")
        owner_user_id = _rdp_owner_user_id(row.get("owner_user_id"))
        record = RDPDeploymentAttestationRecord(**raw)
        with self._lock:
            records = self._records.setdefault((owner_user_id, record.package_id), [])
            if record in records:
                return record
            if persist:
                self._append_event(
                    _deployment_event_row(record, owner_user_id=owner_user_id)
                )
            records.append(record)
        return record

    def record_attestation(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
        package_root: str | Path,
        deployment_ref: str,
        attested_by: str,
        attested_at: str | None = None,
        source_bundle_required: bool = True,
        deployment_event_ref: str = "",
        deployment_artifact_digest: str = "",
        evidence_refs: tuple[str, ...] | list[str] = (),
        has_user_waiver: bool = False,
    ) -> RDPDeploymentAttestationRecord:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if not _safe_package_id(manifest.package_id):
            raise ValueError("RDP package_id is unsafe")
        if not str(deployment_ref or "").strip():
            raise ValueError("deployment_ref is required")
        if manifest.deployment_refs and deployment_ref not in manifest.deployment_refs:
            raise ValueError("deployment_ref is not declared in manifest deployment_refs")
        if not str(attested_by or "").strip():
            raise ValueError("attested_by is required")
        event_ref = str(deployment_event_ref or "").strip()
        artifact_digest = str(deployment_artifact_digest or "").strip()
        evidence = tuple(str(ref).strip() for ref in _tuple(evidence_refs) if str(ref).strip())
        if _contains_external_secret(
            {
                "deployment_ref": deployment_ref,
                "deployment_event_ref": event_ref,
                "deployment_artifact_digest": artifact_digest,
                "evidence_refs": evidence,
            }
        ):
            raise ValueError("RDP deployment attestation cannot contain plaintext secret")

        root = _rdp_owner_storage_root(package_root, owner)
        package_dir = (root / manifest.package_id).resolve()
        try:
            package_dir.relative_to(root)
        except ValueError as exc:
            raise ValueError("RDP package path escapes package root") from exc
        manifest_path = package_dir / "manifest.json"
        refs_index_path = package_dir / "refs.json"
        if not manifest_path.exists() or not refs_index_path.exists():
            raise ValueError("RDP package must be materialized before deployment attestation")

        manifest_payload = canonical_json(manifest.to_open_dict()) + "\n"
        if manifest_path.read_text(encoding="utf-8") != manifest_payload:
            raise ValueError("RDP package manifest file does not match recorded manifest")

        source_bundle_hash = ""
        if source_bundle_required and manifest.source_file_refs:
            source_bundle_hash = _load_source_bundle_index(package_dir / "source_files_index.json", manifest)

        runtime = _runtime_text(manifest.target_runtime)
        attestation_version = (
            "rdp.deployment_attestation.v2"
            if event_ref or artifact_digest or evidence
            else "rdp.deployment_attestation.v1"
        )
        record = RDPDeploymentAttestationRecord(
            package_id=manifest.package_id,
            deployment_ref=deployment_ref,
            target_runtime=runtime,
            manifest_hash="sha16:" + content_hash(manifest.to_open_dict()),
            manifest_file_sha256=_file_sha256(manifest_path),
            refs_index_sha256=_file_sha256(refs_index_path),
            source_bundle_index_sha256=source_bundle_hash,
            approval_ref=manifest.approval_ref,
            monitor_refs=manifest.monitor_refs,
            rollback_plan_ref=manifest.rollback_plan_ref,
            retire_plan_ref=manifest.retire_plan_ref,
            attested_by=attested_by,
            attested_at=attested_at or dt.datetime.now(dt.UTC).isoformat(),
            deployment_event_ref=event_ref,
            deployment_artifact_digest=artifact_digest,
            evidence_refs=evidence,
            attestation_version=attestation_version,
        )
        return self._apply_row(
            _deployment_event_row(record, owner_user_id=owner),
            persist=True,
        )

    def attestations(
        self,
        package_id: str | None = None,
        *,
        owner_user_id: str | None = None,
    ) -> list[RDPDeploymentAttestationRecord]:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        if package_id is not None:
            return list(self._records.get((owner, package_id), ()))
        return [
            record
            for (record_owner, _package_id), records in self._records.items()
            if record_owner == owner
            for record in records
        ]


def _deployment_health_event_row(
    record: RDPDeploymentHealthCheckRecord,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "event_type": "rdp_deployment_health_recorded",
        "owner_user_id": _rdp_owner_user_id(owner_user_id),
        "record": record.to_open_dict(),
    }


class PersistentRDPDeploymentHealthCheckStore:
    """Append-only JSONL audit for RDP post-deployment health and rollback proof records."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner_user_id: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], list[RDPDeploymentHealthCheckRecord]] = {}
        self._owner_user_id = str(owner_user_id or "").strip() or None
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
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad history must block startup.
                    raise ValueError(f"invalid persisted RDP deployment health proof at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        _append_owner_enveloped_event(self._path, self._lock_path, row)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> RDPDeploymentHealthCheckRecord:
        if row.get("schema_version") != 2:
            raise ValueError("owner-enveloped RDP deployment health schema_version=2 is required")
        if row.get("event_type") != "rdp_deployment_health_recorded":
            raise ValueError(f"unknown RDP deployment health event_type={row.get('event_type')!r}")
        raw = row.get("record")
        if not isinstance(raw, dict):
            raise ValueError("RDP deployment health event missing record")
        owner_user_id = _rdp_owner_user_id(row.get("owner_user_id"))
        record = RDPDeploymentHealthCheckRecord(**raw)
        with self._lock:
            records = self._records.setdefault((owner_user_id, record.package_id), [])
            if record in records:
                return record
            if persist:
                self._append_event(
                    _deployment_health_event_row(record, owner_user_id=owner_user_id)
                )
            records.append(record)
        return record

    def record_health_check(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
        deployment_attestations: tuple[RDPDeploymentAttestationRecord, ...] | list[RDPDeploymentAttestationRecord],
        deployment_attestation_hash: str,
        health_status: str,
        health_check_refs: tuple[str, ...] | list[str],
        monitor_refs: tuple[str, ...] | list[str],
        rollback_readiness_ref: str,
        rollback_drill_ref: str,
        evidence_refs: tuple[str, ...] | list[str],
        attested_by: str,
        deployment_ref: str = "",
        rollback_plan_ref: str = "",
        retire_plan_ref: str = "",
        attested_at: str | None = None,
        has_user_waiver: bool = False,
    ) -> RDPDeploymentHealthCheckRecord:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if not _safe_package_id(manifest.package_id):
            raise ValueError("RDP package_id is unsafe")

        attestation_hash = str(deployment_attestation_hash or "").strip()
        if not attestation_hash:
            raise ValueError("deployment_attestation_hash is required")
        matching_attestations = [
            record
            for record in deployment_attestations
            if record.package_id == manifest.package_id and record.attestation_hash == attestation_hash
        ]
        if not matching_attestations:
            raise ValueError("RDP deployment health proof requires recorded deployment attestation")
        deployment_attestation = matching_attestations[-1]

        normalized_deployment_ref = str(deployment_ref or deployment_attestation.deployment_ref or "").strip()
        if not normalized_deployment_ref:
            raise ValueError("deployment_ref is required")
        if normalized_deployment_ref != deployment_attestation.deployment_ref:
            raise ValueError("deployment_ref does not match deployment attestation")
        if manifest.deployment_refs and normalized_deployment_ref not in manifest.deployment_refs:
            raise ValueError("deployment_ref is not declared in manifest deployment_refs")

        normalized_status = str(health_status or "").strip().lower()
        if normalized_status != "healthy":
            raise ValueError("RDP deployment health proof requires health_status=healthy")
        health_refs = tuple(str(ref).strip() for ref in _tuple(health_check_refs) if str(ref).strip())
        if not health_refs:
            raise ValueError("health_check_refs are required")
        monitors = tuple(str(ref).strip() for ref in _tuple(monitor_refs) if str(ref).strip())
        if not monitors:
            raise ValueError("monitor_refs are required")
        if manifest.monitor_refs:
            missing_monitors = sorted(set(manifest.monitor_refs) - set(monitors))
            if missing_monitors:
                raise ValueError(f"RDP deployment health proof missing monitor_ref {missing_monitors[0]!r}")

        rollback_plan = str(rollback_plan_ref or "").strip()
        if not rollback_plan:
            raise ValueError("rollback_plan_ref is required")
        if manifest.rollback_plan_ref and rollback_plan != manifest.rollback_plan_ref:
            raise ValueError("rollback_plan_ref does not match manifest")
        rollback_readiness = str(rollback_readiness_ref or "").strip()
        if not rollback_readiness:
            raise ValueError("rollback_readiness_ref is required")
        rollback_drill = str(rollback_drill_ref or "").strip()
        if not rollback_drill:
            raise ValueError("rollback_drill_ref is required")
        retire_plan = str(retire_plan_ref or "").strip()
        if not retire_plan:
            raise ValueError("retire_plan_ref is required")
        if manifest.retire_plan_ref and retire_plan != manifest.retire_plan_ref:
            raise ValueError("retire_plan_ref does not match manifest")
        evidence = tuple(str(ref).strip() for ref in _tuple(evidence_refs) if str(ref).strip())
        if not evidence:
            raise ValueError("evidence_refs are required")
        if not str(attested_by or "").strip():
            raise ValueError("attested_by is required")

        secret_probe = {
            "deployment_ref": normalized_deployment_ref,
            "deployment_attestation_hash": attestation_hash,
            "health_check_refs": health_refs,
            "monitor_refs": monitors,
            "rollback_plan_ref": rollback_plan,
            "rollback_readiness_ref": rollback_readiness,
            "rollback_drill_ref": rollback_drill,
            "retire_plan_ref": retire_plan,
            "evidence_refs": evidence,
        }
        if _contains_external_secret(secret_probe):
            raise ValueError("RDP deployment health proof cannot contain plaintext secret")

        record = RDPDeploymentHealthCheckRecord(
            package_id=manifest.package_id,
            deployment_ref=normalized_deployment_ref,
            target_runtime=_runtime_text(manifest.target_runtime),
            manifest_hash="sha16:" + content_hash(manifest.to_open_dict()),
            deployment_attestation_hash=attestation_hash,
            health_status=normalized_status,
            health_check_refs=health_refs,
            monitor_refs=monitors,
            rollback_plan_ref=rollback_plan,
            rollback_readiness_ref=rollback_readiness,
            rollback_drill_ref=rollback_drill,
            retire_plan_ref=retire_plan,
            evidence_refs=evidence,
            attested_by=str(attested_by).strip(),
            attested_at=attested_at or dt.datetime.now(dt.UTC).isoformat(),
        )
        return self._apply_row(
            _deployment_health_event_row(record, owner_user_id=owner),
            persist=True,
        )

    def health_checks(
        self,
        package_id: str | None = None,
        *,
        owner_user_id: str | None = None,
    ) -> list[RDPDeploymentHealthCheckRecord]:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        if package_id is not None:
            return list(self._records.get((owner, package_id), ()))
        return [
            record
            for (record_owner, _package_id), records in self._records.items()
            if record_owner == owner
            for record in records
        ]


def _source_run_integrity_event_row(
    record: RDPSourceRunIntegrityRecord,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "event_type": "rdp_source_run_integrity_recorded",
        "owner_user_id": _rdp_owner_user_id(owner_user_id),
        "record": record.to_open_dict(),
    }


class PersistentRDPSourceRunIntegrityStore:
    """Append-only JSONL audit for source bundle to run artifact integrity records."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner_user_id: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], list[RDPSourceRunIntegrityRecord]] = {}
        self._owner_user_id = str(owner_user_id or "").strip() or None
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
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad history must block startup.
                    raise ValueError(f"invalid persisted RDP source-run integrity at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        _append_owner_enveloped_event(self._path, self._lock_path, row)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> RDPSourceRunIntegrityRecord:
        if row.get("schema_version") != 2:
            raise ValueError("owner-enveloped RDP source-run integrity schema_version=2 is required")
        if row.get("event_type") != "rdp_source_run_integrity_recorded":
            raise ValueError(f"unknown RDP source-run integrity event_type={row.get('event_type')!r}")
        raw = row.get("record")
        if not isinstance(raw, dict):
            raise ValueError("RDP source-run integrity event missing record")
        owner_user_id = _rdp_owner_user_id(row.get("owner_user_id"))
        record = RDPSourceRunIntegrityRecord(**raw)
        with self._lock:
            records = self._records.setdefault((owner_user_id, record.package_id), [])
            if record in records:
                return record
            if persist:
                self._append_event(
                    _source_run_integrity_event_row(
                        record,
                        owner_user_id=owner_user_id,
                    )
                )
            records.append(record)
        return record

    def record_integrity(
        self,
        manifest: RDPManifest,
        *,
        owner_user_id: str | None = None,
        package_root: str | Path,
        run_root: str | Path,
        run_id: str,
        source_file_ref: str | None = None,
        attested_by: str,
        attested_at: str | None = None,
        has_user_waiver: bool = False,
    ) -> RDPSourceRunIntegrityRecord:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if not _safe_package_id(manifest.package_id):
            raise ValueError("RDP package_id is unsafe")
        if not str(attested_by or "").strip():
            raise ValueError("attested_by is required")

        root = _rdp_owner_storage_root(package_root, owner)
        package_dir = (root / manifest.package_id).resolve()
        try:
            package_dir.relative_to(root)
        except ValueError as exc:
            raise ValueError("RDP package path escapes package root") from exc
        manifest_path = package_dir / "manifest.json"
        refs_index_path = package_dir / "refs.json"
        if not manifest_path.exists() or not refs_index_path.exists():
            raise ValueError("RDP package must be materialized before source-run integrity attestation")

        manifest_payload = canonical_json(manifest.to_open_dict()) + "\n"
        if manifest_path.read_text(encoding="utf-8") != manifest_payload:
            raise ValueError("RDP package manifest file does not match recorded manifest")

        selected_ref = _select_source_file_ref(manifest, source_file_ref)
        source_bundle_index_path = package_dir / "source_files_index.json"
        source_bundle_index = _load_source_bundle_index_row(source_bundle_index_path, manifest)
        source_bundle_hash = _file_sha256(source_bundle_index_path)
        source_entry = _source_bundle_entry_for_ref(source_bundle_index, selected_ref)
        bundled_source_hash = _verified_bundled_source_hash(package_dir, source_entry)

        normalized_run_id = str(run_id or "")
        if not _safe_run_id(normalized_run_id):
            raise ValueError("RDP run_id is unsafe")
        run_ref = _run_ref_for_id(manifest, normalized_run_id)
        run_dir = _resolve_run_dir(run_root, normalized_run_id)
        run_manifest_path = _required_run_file(run_dir, "run.json")
        run_strategy_path = _required_run_file(run_dir, "strategy.py")
        run_portfolio_path = _required_run_file(run_dir, "portfolio.csv")

        try:
            run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001 - malformed run manifest must fail closed.
            raise ValueError("RDP run.json is invalid") from exc
        run_manifest_id = str(run_manifest.get("run_id") or run_dir.name)
        if run_manifest_id != normalized_run_id:
            raise ValueError("RDP run.json run_id does not match requested run_id")
        source = run_manifest.get("source")
        source_owner = (
            str(source.get("owner_user_id") or "").strip()
            if isinstance(source, dict)
            else ""
        )
        run_owner = str(run_manifest.get("owner_user_id") or source_owner).strip()
        if not run_owner or run_owner != owner:
            raise ValueError("RDP run.json is not owned by the package owner")

        run_manifest_hash = _file_sha256(run_manifest_path)
        run_strategy_hash = _file_sha256(run_strategy_path)
        run_portfolio_hash = _file_sha256(run_portfolio_path)
        if bundled_source_hash != run_strategy_hash:
            raise ValueError("RDP bundled source does not match run strategy.py")
        _validate_ide_run_source_snapshot(
            run_ref=run_ref,
            run_id=normalized_run_id,
            owner_user_id=owner,
            run_manifest=run_manifest,
            run_manifest_path=run_manifest_path,
            run_strategy_path=run_strategy_path,
            run_portfolio_path=run_portfolio_path,
            run_strategy_hash=run_strategy_hash,
            run_portfolio_hash=run_portfolio_hash,
        )

        artifact_hash = rdp_run_artifact_hash(
            run_manifest_sha256=run_manifest_hash,
            run_strategy_sha256=run_strategy_hash,
            run_portfolio_sha256=run_portfolio_hash,
        )
        if manifest.artifact_hash != artifact_hash:
            raise ValueError("RDP artifact_hash does not match run artifacts")

        record = RDPSourceRunIntegrityRecord(
            package_id=manifest.package_id,
            run_ref=run_ref,
            run_id=normalized_run_id,
            source_file_ref=selected_ref,
            manifest_hash="sha16:" + content_hash(manifest.to_open_dict()),
            manifest_file_sha256=_file_sha256(manifest_path),
            refs_index_sha256=_file_sha256(refs_index_path),
            source_bundle_index_sha256=source_bundle_hash,
            bundled_source_sha256=bundled_source_hash,
            run_manifest_sha256=run_manifest_hash,
            run_strategy_sha256=run_strategy_hash,
            run_portfolio_sha256=run_portfolio_hash,
            artifact_hash=artifact_hash,
            attested_by=attested_by,
            attested_at=attested_at or dt.datetime.now(dt.UTC).isoformat(),
        )
        return self._apply_row(
            _source_run_integrity_event_row(
                record,
                owner_user_id=owner,
            ),
            persist=True,
        )

    def records(
        self,
        package_id: str | None = None,
        *,
        owner_user_id: str | None = None,
    ) -> list[RDPSourceRunIntegrityRecord]:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        if package_id is not None:
            return list(self._records.get((owner, package_id), ()))
        return [
            record
            for (record_owner, _package_id), records in self._records.items()
            if record_owner == owner
            for record in records
        ]


def _package_publish_event_row(
    record: RDPPackagePublishRecord,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "event_type": "rdp_package_published",
        "owner_user_id": _rdp_owner_user_id(owner_user_id),
        "record": record.to_open_dict(),
    }


class PersistentRDPPackagePublishStore:
    """Append-only JSONL audit for local RDP package publish records."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner_user_id: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], list[RDPPackagePublishRecord]] = {}
        self._owner_user_id = str(owner_user_id or "").strip() or None
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
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad publish history must block startup.
                    raise ValueError(f"invalid persisted RDP package publish at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        _append_owner_enveloped_event(self._path, self._lock_path, row)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> RDPPackagePublishRecord:
        if row.get("schema_version") != 2:
            raise ValueError("owner-enveloped RDP package publish schema_version=2 is required")
        if row.get("event_type") != "rdp_package_published":
            raise ValueError(f"unknown RDP package publish event_type={row.get('event_type')!r}")
        raw = row.get("record")
        if not isinstance(raw, dict):
            raise ValueError("RDP package publish event missing record")
        owner_user_id = _rdp_owner_user_id(row.get("owner_user_id"))
        record = RDPPackagePublishRecord(**raw)
        with self._lock:
            records = self._records.setdefault((owner_user_id, record.package_id), [])
            if record in records:
                return record
            if persist:
                self._append_event(
                    _package_publish_event_row(record, owner_user_id=owner_user_id)
                )
            records.append(record)
        return record

    def record_publication(
        self,
        record: RDPPackagePublishRecord,
        *,
        owner_user_id: str | None = None,
    ) -> RDPPackagePublishRecord:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        return self._apply_row(
            _package_publish_event_row(record, owner_user_id=owner),
            persist=True,
        )

    def publications(
        self,
        package_id: str | None = None,
        *,
        owner_user_id: str | None = None,
    ) -> list[RDPPackagePublishRecord]:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        if package_id is not None:
            return list(self._records.get((owner, package_id), ()))
        return [
            record
            for (record_owner, _package_id), records in self._records.items()
            if record_owner == owner
            for record in records
        ]


def _external_publication_proof_event_row(
    record: RDPExternalPublicationProofRecord,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "event_type": "rdp_external_publication_proof_recorded",
        "owner_user_id": _rdp_owner_user_id(owner_user_id),
        "record": record.to_open_dict(),
    }


class PersistentRDPExternalPublicationProofStore:
    """Append-only JSONL audit for refs-only external RDP publication proofs."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner_user_id: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], list[RDPExternalPublicationProofRecord]] = {}
        self._owner_user_id = str(owner_user_id or "").strip() or None
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
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad proof history must block startup.
                    raise ValueError(f"invalid persisted RDP external publication proof at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        _append_owner_enveloped_event(self._path, self._lock_path, row)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> RDPExternalPublicationProofRecord:
        if row.get("schema_version") != 2:
            raise ValueError("owner-enveloped RDP external publication proof schema_version=2 is required")
        if row.get("event_type") != "rdp_external_publication_proof_recorded":
            raise ValueError(f"unknown RDP external publication proof event_type={row.get('event_type')!r}")
        raw = row.get("record")
        if not isinstance(raw, dict):
            raise ValueError("RDP external publication proof event missing record")
        owner_user_id = _rdp_owner_user_id(row.get("owner_user_id"))
        record = RDPExternalPublicationProofRecord(**raw)
        with self._lock:
            records = self._records.setdefault((owner_user_id, record.package_id), [])
            if record in records:
                return record
            if persist:
                self._append_event(
                    _external_publication_proof_event_row(
                        record,
                        owner_user_id=owner_user_id,
                    )
                )
            records.append(record)
        return record

    def record_proof(
        self,
        manifest: RDPManifest,
        local_publication: RDPPackagePublishRecord,
        *,
        owner_user_id: str | None = None,
        external_channel: str,
        external_uri: str,
        immutable_pointer_ref: str,
        destination_allowlist_ref: str,
        evidence_refs: tuple[str, ...] | list[str],
        attested_by: str,
        attested_at: str | None = None,
        archive_sha256: str = "",
        trust_release_ref: str = "",
        trust_release_approval_ref: str = "",
        has_user_waiver: bool = False,
    ) -> RDPExternalPublicationProofRecord:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        normalized_uri = _validate_external_uri(external_uri)
        return self.record_proof_from_digest(
            manifest,
            local_publication,
            owner_user_id=owner,
            external_channel=external_channel,
            external_uri_digest=_external_uri_digest(normalized_uri),
            immutable_pointer_ref=immutable_pointer_ref,
            destination_allowlist_ref=destination_allowlist_ref,
            evidence_refs=evidence_refs,
            attested_by=attested_by,
            attested_at=attested_at,
            archive_sha256=archive_sha256,
            trust_release_ref=trust_release_ref,
            trust_release_approval_ref=trust_release_approval_ref,
            has_user_waiver=has_user_waiver,
        )

    def record_proof_from_digest(
        self,
        manifest: RDPManifest,
        local_publication: RDPPackagePublishRecord,
        *,
        owner_user_id: str | None = None,
        external_channel: str,
        external_uri_digest: str,
        immutable_pointer_ref: str,
        destination_allowlist_ref: str,
        evidence_refs: tuple[str, ...] | list[str],
        attested_by: str,
        attested_at: str | None = None,
        archive_sha256: str = "",
        trust_release_ref: str = "",
        trust_release_approval_ref: str = "",
        has_user_waiver: bool = False,
    ) -> RDPExternalPublicationProofRecord:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if manifest.package_id != local_publication.package_id:
            raise ValueError("RDP external publication proof package_id does not match local publication")
        if not local_publication.publish_hash:
            raise ValueError("local publication hash is required before external publication proof")
        if archive_sha256 and archive_sha256 != local_publication.archive_sha256:
            raise ValueError("RDP external publication archive_sha256 does not match local publication")
        if not _safe_external_publish_channel(str(external_channel or "")):
            raise ValueError("RDP external publication proof channel is not allowed")
        uri_digest = _validate_external_uri_digest(external_uri_digest)
        pointer_ref = str(immutable_pointer_ref or "").strip()
        allowlist_ref = str(destination_allowlist_ref or "").strip()
        if not pointer_ref:
            raise ValueError("immutable_pointer_ref is required")
        if not allowlist_ref:
            raise ValueError("destination_allowlist_ref is required")
        evidence = tuple(str(ref).strip() for ref in _tuple(evidence_refs) if str(ref).strip())
        if not evidence:
            raise ValueError("evidence_refs are required")
        if not str(attested_by or "").strip():
            raise ValueError("attested_by is required")
        if _contains_external_secret(
            {
                "immutable_pointer_ref": pointer_ref,
                "destination_allowlist_ref": allowlist_ref,
                "evidence_refs": evidence,
            }
        ):
            raise ValueError("RDP external publication proof cannot contain plaintext secret")

        release_ref = str(trust_release_ref or local_publication.trust_release_ref or "").strip()
        approval_ref = str(trust_release_approval_ref or local_publication.trust_release_approval_ref or "").strip()
        if not release_ref:
            raise ValueError("trust_release_ref is required before external publication proof")
        if not approval_ref:
            raise ValueError("trust_release_approval_ref is required before external publication proof")
        if release_ref != local_publication.trust_release_ref:
            raise ValueError("trust_release_ref does not match local publication")
        if approval_ref != local_publication.trust_release_approval_ref:
            raise ValueError("trust_release_approval_ref does not match local publication")

        record = RDPExternalPublicationProofRecord(
            package_id=manifest.package_id,
            external_channel=str(external_channel or "").strip(),
            target_runtime=_runtime_text(manifest.target_runtime),
            local_publish_hash=local_publication.publish_hash,
            archive_sha256=local_publication.archive_sha256,
            external_uri_digest=uri_digest,
            immutable_pointer_ref=pointer_ref,
            destination_allowlist_ref=allowlist_ref,
            trust_release_ref=release_ref,
            trust_release_approval_ref=approval_ref,
            evidence_refs=evidence,
            attested_by=attested_by,
            attested_at=attested_at or dt.datetime.now(dt.UTC).isoformat(),
        )
        return self._apply_row(
            _external_publication_proof_event_row(
                record,
                owner_user_id=owner,
            ),
            persist=True,
        )

    def proofs(
        self,
        package_id: str | None = None,
        *,
        owner_user_id: str | None = None,
    ) -> list[RDPExternalPublicationProofRecord]:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        if package_id is not None:
            return list(self._records.get((owner, package_id), ()))
        return [
            record
            for (record_owner, _package_id), records in self._records.items()
            if record_owner == owner
            for record in records
        ]


def _ci_release_attestation_event_row(
    record: RDPCIReleaseAttestationRecord,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "event_type": "rdp_ci_release_attestation_recorded",
        "owner_user_id": _rdp_owner_user_id(owner_user_id),
        "record": record.to_open_dict(),
    }


class PersistentRDPCIReleaseAttestationStore:
    """Append-only JSONL audit for refs-only RDP CI release attestations."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner_user_id: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], list[RDPCIReleaseAttestationRecord]] = {}
        self._owner_user_id = str(owner_user_id or "").strip() or None
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
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad attestation history must block startup.
                    raise ValueError(f"invalid persisted RDP CI release attestation at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        _append_owner_enveloped_event(self._path, self._lock_path, row)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> RDPCIReleaseAttestationRecord:
        if row.get("schema_version") != 2:
            raise ValueError("owner-enveloped RDP CI release attestation schema_version=2 is required")
        if row.get("event_type") != "rdp_ci_release_attestation_recorded":
            raise ValueError(f"unknown RDP CI release attestation event_type={row.get('event_type')!r}")
        raw = row.get("record")
        if not isinstance(raw, dict):
            raise ValueError("RDP CI release attestation event missing record")
        owner_user_id = _rdp_owner_user_id(row.get("owner_user_id"))
        record = RDPCIReleaseAttestationRecord(**raw)
        with self._lock:
            records = self._records.setdefault((owner_user_id, record.package_id), [])
            if record in records:
                return record
            if persist:
                self._append_event(
                    _ci_release_attestation_event_row(
                        record,
                        owner_user_id=owner_user_id,
                    )
                )
            records.append(record)
        return record

    def record_attestation(
        self,
        manifest: RDPManifest,
        local_publication: RDPPackagePublishRecord,
        external_proof: RDPExternalPublicationProofRecord,
        *,
        owner_user_id: str | None = None,
        ci_system_ref: str,
        ci_workflow_ref: str,
        ci_run_ref: str,
        source_commit_ref: str,
        artifact_digest: str,
        test_report_ref: str,
        test_report_hash: str,
        build_log_digest: str,
        required_check_refs: tuple[str, ...] | list[str],
        evidence_refs: tuple[str, ...] | list[str],
        attested_by: str,
        ci_status: str = "passed",
        failed_check_refs: tuple[str, ...] | list[str] = (),
        skipped_check_refs: tuple[str, ...] | list[str] = (),
        missing_check_refs: tuple[str, ...] | list[str] = (),
        attested_at: str | None = None,
        archive_sha256: str = "",
        trust_release_ref: str = "",
        trust_release_approval_ref: str = "",
        has_user_waiver: bool = False,
    ) -> RDPCIReleaseAttestationRecord:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        violations = validate_rdp_manifest(manifest, has_user_waiver=has_user_waiver)
        if violations:
            raise ValueError(_rdp_violation_message(violations))
        if manifest.package_id != local_publication.package_id:
            raise ValueError("RDP CI release attestation package_id does not match local publication")
        if manifest.package_id != external_proof.package_id:
            raise ValueError("RDP CI release attestation package_id does not match external proof")
        if external_proof.local_publish_hash != local_publication.publish_hash:
            raise ValueError("RDP CI release attestation external proof does not match local publication")
        if archive_sha256 and archive_sha256 != local_publication.archive_sha256:
            raise ValueError("RDP CI release attestation archive_sha256 does not match local publication")
        if external_proof.archive_sha256 != local_publication.archive_sha256:
            raise ValueError("RDP CI release attestation external proof archive_sha256 does not match local publication")

        release_ref = str(trust_release_ref or local_publication.trust_release_ref or "").strip()
        approval_ref = str(trust_release_approval_ref or local_publication.trust_release_approval_ref or "").strip()
        if not release_ref:
            raise ValueError("trust_release_ref is required before CI release attestation")
        if not approval_ref:
            raise ValueError("trust_release_approval_ref is required before CI release attestation")
        if release_ref != local_publication.trust_release_ref or release_ref != external_proof.trust_release_ref:
            raise ValueError("trust_release_ref does not match local publication and external proof")
        if (
            approval_ref != local_publication.trust_release_approval_ref
            or approval_ref != external_proof.trust_release_approval_ref
        ):
            raise ValueError("trust_release_approval_ref does not match local publication and external proof")

        normalized_status = str(ci_status or "").strip().lower()
        if normalized_status != "passed":
            raise ValueError("RDP CI release attestation requires ci_status=passed")
        failed = tuple(str(ref).strip() for ref in _tuple(failed_check_refs) if str(ref).strip())
        skipped = tuple(str(ref).strip() for ref in _tuple(skipped_check_refs) if str(ref).strip())
        missing = tuple(str(ref).strip() for ref in _tuple(missing_check_refs) if str(ref).strip())
        if failed or skipped or missing:
            raise ValueError("RDP CI release attestation has failed, skipped, or missing required checks")

        required_checks = tuple(str(ref).strip() for ref in _tuple(required_check_refs) if str(ref).strip())
        evidence = tuple(str(ref).strip() for ref in _tuple(evidence_refs) if str(ref).strip())
        required_text = {
            "ci_system_ref": str(ci_system_ref or "").strip(),
            "ci_workflow_ref": str(ci_workflow_ref or "").strip(),
            "ci_run_ref": str(ci_run_ref or "").strip(),
            "source_commit_ref": str(source_commit_ref or "").strip(),
            "artifact_digest": str(artifact_digest or "").strip(),
            "test_report_ref": str(test_report_ref or "").strip(),
            "test_report_hash": str(test_report_hash or "").strip(),
            "build_log_digest": str(build_log_digest or "").strip(),
            "attested_by": str(attested_by or "").strip(),
        }
        for field_name, value in required_text.items():
            if not value:
                raise ValueError(f"{field_name} is required")
        if not required_checks:
            raise ValueError("required_check_refs are required")
        if not evidence:
            raise ValueError("evidence_refs are required")
        secret_probe = {
            **required_text,
            "required_check_refs": required_checks,
            "failed_check_refs": failed,
            "skipped_check_refs": skipped,
            "missing_check_refs": missing,
            "evidence_refs": evidence,
        }
        if _contains_external_secret(secret_probe):
            raise ValueError("RDP CI release attestation cannot contain plaintext secret")

        record = RDPCIReleaseAttestationRecord(
            package_id=manifest.package_id,
            target_runtime=_runtime_text(manifest.target_runtime),
            manifest_hash="sha16:" + content_hash(manifest.to_open_dict()),
            local_publish_hash=local_publication.publish_hash,
            external_proof_hash=external_proof.proof_hash,
            archive_sha256=local_publication.archive_sha256,
            trust_release_ref=release_ref,
            trust_release_approval_ref=approval_ref,
            ci_system_ref=required_text["ci_system_ref"],
            ci_workflow_ref=required_text["ci_workflow_ref"],
            ci_run_ref=required_text["ci_run_ref"],
            source_commit_ref=required_text["source_commit_ref"],
            ci_status=normalized_status,
            artifact_digest=required_text["artifact_digest"],
            test_report_ref=required_text["test_report_ref"],
            test_report_hash=required_text["test_report_hash"],
            build_log_digest=required_text["build_log_digest"],
            required_check_refs=required_checks,
            evidence_refs=evidence,
            attested_by=required_text["attested_by"],
            attested_at=attested_at or dt.datetime.now(dt.UTC).isoformat(),
        )
        return self._apply_row(
            _ci_release_attestation_event_row(
                record,
                owner_user_id=owner,
            ),
            persist=True,
        )

    def attestations(
        self,
        package_id: str | None = None,
        *,
        owner_user_id: str | None = None,
    ) -> list[RDPCIReleaseAttestationRecord]:
        owner = _resolve_rdp_owner(owner_user_id, self._owner_user_id)
        if package_id is not None:
            return list(self._records.get((owner, package_id), ()))
        return [
            record
            for (record_owner, _package_id), records in self._records.items()
            if record_owner == owner
            for record in records
        ]


__all__ = [
    "PersistentRDPStore",
    "RDPStoreCommitUncertain",
    "PersistentRDPCIReleaseAttestationStore",
    "PersistentRDPExternalPublicationProofStore",
    "RDPOpenPackageMaterializer",
    "RDPSourceFileBundler",
    "RDPSourceFileBundleEntry",
    "RDPSourceFileBundleRecord",
    "PersistentRDPDeploymentAttestationStore",
    "PersistentRDPDeploymentHealthCheckStore",
    "PersistentRDPPackagePublishStore",
    "RDPCIReleaseAttestationRecord",
    "RDPDeploymentAttestationRecord",
    "RDPDeploymentHealthCheckRecord",
    "RDPExternalPublicationProofRecord",
    "PersistentRDPSourceRunIntegrityStore",
    "RDPSourceRunIntegrityRecord",
    "RDPPackageArchiveExporter",
    "RDPPackageArchiveRecord",
    "RDPLocalPackagePublisher",
    "RDPPackagePublishRecord",
    "RDPManifest",
    "RDPPackageRecord",
    "RDPViolation",
    "manifest_from_qro",
    "rdp_run_artifact_hash",
    "validate_rdp_manifest",
]
