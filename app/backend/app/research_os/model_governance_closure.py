"""Durable, owner-scoped semantic closure for GOAL section 15.

The canonical producers stay in the training, model-registry, approval, reviewer-
grant, and model-governance stores.  This module only resolves their current
state and records a content-bound receipt.  It never trains, promotes, approves,
loads an artifact, or manufactures a missing governance ref.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
from ..experiments.store import ModelRegistry, ModelVersion
from ..lineage.ids import content_hash
from ..models.card_loader import DEFAULT_CARDS_DIR, parse_model_card
from .goal_coverage import strict_current_entrypoint_coverage
from .goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
)
from .model_governance import (
    ModelArtifactFormat,
    ModelArtifactManifestEntry,
    ModelArtifactSource,
    ModelGovernancePassport,
    ModelMonitoringProfile,
    ModelRecertificationRecord,
    ModelRiskTier,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
    validate_model_promotion,
)
from .model_recertification_events import (
    PersistentModelRecertificationEventRegistry,
    resolve_current_recertification_requirements,
)
from .model_recertification_evidence import (
    DependencyKind,
    ModelEvidenceError,
    PersistentModelRecertificationEvidenceRegistry,
)
from .ref_resolution import is_placeholder_ref


MODEL_GOVERNANCE_CLOSURE_SCHEMA_VERSION = 1
MODEL_GOVERNANCE_CLOSURE_RECEIPT_VERSION = "model_governance_closure_receipt.v1"
MODEL_GOVERNANCE_CLOSURE_ENTRYPOINT_REF = "api:goal.model_governance_closure.current"
MODEL_GOVERNANCE_SOURCE_ENTRYPOINT_REF = "api:training.jobs"

_MODEL_VERSION_EVENT = "model_passport_recorded"
_PROFILE_EVENT = "model_monitoring_profile_recorded"
_INSPECTION_EVENT = "model_artifact_inspection_recorded"
_RECERTIFICATION_EVENT = "model_recertification_recorded"
_REQUIRED_RECERTIFICATION_TRIGGERS = frozenset(item.value for item in RecertificationTrigger)
_REQUIRED_DOSSIER_FIELDS = frozenset(
    {
        "validation_dossier_ref",
        "model_version_ref",
        "training_run_ref",
        "dataset_refs",
        "market_data_use_validation_refs",
        "feature_refs",
        "label_refs",
        "cv_scheme",
        "n_splits",
        "metrics",
        "artifact_path",
        "artifact_hash",
        "artifact_inspection_ref",
        "artifact_inspection_mode",
        "result_oos_metrics",
        "fold_count",
    }
)
_POLICY_EXPECTATIONS = {
    "missing_validation_dossier": frozenset({"missing_validation_dossier_ref"}),
    "external_pickle_direct_load": frozenset(
        {
            "external_serialized_artifact_blocked",
            "external_pickle_direct_load",
            "unsafe_serialized_direct_load",
        }
    ),
    "high_risk_without_challenger": frozenset({"missing_challenger_result"}),
    "material_change_without_recertification": frozenset(
        {"material_model_change_without_recertification"}
    ),
    "data_schema_change_without_recertification": frozenset(
        {"missing_recertification_record"}
    ),
    "feature_drift_without_recertification": frozenset(
        {"missing_recertification_record"}
    ),
    "performance_degradation_without_recertification": frozenset(
        {"missing_recertification_record"}
    ),
    "new_asset_class_without_recertification": frozenset(
        {"missing_recertification_record"}
    ),
    "new_execution_environment_without_recertification": frozenset(
        {"missing_recertification_record"}
    ),
    "dependency_update_without_recertification": frozenset(
        {"missing_recertification_record"}
    ),
    "torch_without_weights_only": frozenset({"torch_weights_only_required"}),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _stable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _stable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_stable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _state_hash(value: Any) -> str:
    return _sha256_bytes(_canonical_json(_stable(value)).encode("utf-8"))


def _owner(value: Any) -> str:
    owner = _text(value)
    if not owner or owner != value or any(ord(char) < 32 for char in owner):
        raise ModelGovernanceClosureError(
            "owner_user_id must be a stable non-empty exact string"
        )
    if is_placeholder_ref(owner):
        raise ModelGovernanceClosureError("owner_user_id contains banned placeholder material")
    return owner


def _real_ref(value: Any, *, field: str) -> str:
    ref = _text(value)
    if not ref:
        raise ModelGovernanceClosureError(f"{field} is required")
    if is_placeholder_ref(ref):
        raise ModelGovernanceClosureError(f"{field} contains banned placeholder material")
    return ref


def _strict_json_rows(path: Path, *, label: str) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        raise ModelGovernanceClosureError(f"{label} durable store is unavailable")
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ModelGovernanceClosureError(f"{label} durable store cannot be read") from exc
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ModelGovernanceClosureError(
                f"{label} durable store has invalid JSON at line {line_no}"
            ) from exc
        if not isinstance(row, dict):
            raise ModelGovernanceClosureError(
                f"{label} durable store row {line_no} is not an object"
            )
        rows.append(row)
    return rows


def _latest_row_marker(
    path: Path,
    *,
    label: str,
    matches: Any,
    expected: Any,
) -> dict[str, Any]:
    rows = _strict_json_rows(path, label=label)
    selected: tuple[int, dict[str, Any]] | None = None
    for index, row in enumerate(rows, start=1):
        if matches(row):
            selected = (index, row)
    if selected is None:
        raise ModelGovernanceClosureError(f"{label} current durable row is missing")
    index, row = selected
    if _stable(row) != _stable(expected):
        raise ModelGovernanceClosureError(f"{label} current durable row differs from resolved state")
    return {
        "durable_row_number": index,
        "durable_row_hash": _state_hash(row),
    }


def _private_path(value: Any, *names: str, label: str) -> Path:
    current = value
    for name in names:
        current = getattr(current, name, None)
    if not isinstance(current, Path):
        raise ModelGovernanceClosureError(f"{label} does not expose its durable path")
    return current


def _read_confined_file(path: Path, *, root: Path, label: str) -> bytes:
    root = root.resolve()
    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ModelGovernanceClosureError(f"{label} is absent or outside the training job root") from exc
    if not resolved.is_file() or candidate.is_symlink():
        raise ModelGovernanceClosureError(f"{label} must be a regular non-symlink file")
    relative = resolved.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ModelGovernanceClosureError(f"{label} path cannot traverse a symlink")
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise ModelGovernanceClosureError(f"{label} cannot be read") from exc


def _json_object(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ModelGovernanceClosureError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ModelGovernanceClosureError(f"{label} must be a JSON object")
    return value


def _source_bundle() -> tuple[tuple[str, str], ...]:
    app_root = Path(__file__).resolve().parents[1]
    files = sorted(
        {
            *list((app_root / "training").rglob("*.py")),
            *list((app_root / "models").rglob("*.py")),
        }
    )
    if not files:
        raise ModelGovernanceClosureError("training source bundle is empty")
    return tuple(
        (str(path.relative_to(app_root)), _sha256_bytes(path.read_bytes())) for path in files
    )


def model_training_code_hash(training_plan: dict[str, Any]) -> str:
    """Hash the exact plan plus the executable training/model Python source tree."""

    if not isinstance(training_plan, dict) or not training_plan:
        raise ValueError("training_plan must be a non-empty object")
    return _state_hash(
        {
            "hash_contract": "quantbt_model_training_code.v1",
            "training_plan": training_plan,
            "source_bundle": _source_bundle(),
        }
    )


@dataclass(frozen=True)
class ModelGovernanceClosureViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class ModelGovernanceClosureDecision:
    accepted: bool
    violations: tuple[ModelGovernanceClosureViolation, ...]


class ModelGovernanceClosureError(ValueError):
    """The current owner-scoped §15 chain could not be resolved."""


class ModelGovernanceClosureCommitUncertain(ModelGovernanceClosureError):
    """The receipt file may be visible but directory durability was not confirmed."""


@dataclass(frozen=True)
class ModelGovernanceClosureComponentState:
    component_kind: str
    component_ref: str
    state_hash: str

    def __post_init__(self) -> None:
        for field in ("component_kind", "component_ref", "state_hash"):
            object.__setattr__(self, field, _text(getattr(self, field)))


@dataclass(frozen=True)
class ModelGovernancePolicyProbeState:
    probe_name: str
    accepted: bool
    violation_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "probe_name", _text(self.probe_name))
        object.__setattr__(self, "violation_codes", tuple(sorted(set(self.violation_codes))))


@dataclass(frozen=True)
class ModelGovernanceClosureSnapshot:
    owner_user_id: str
    model_id: str
    model_asset_ref: str
    version: int
    stage: str
    model_version_ref: str
    passport_ref: str
    training_plan_ref: str
    training_run_ref: str
    validation_dossier_ref: str
    promotion_gate_ref: str
    monitoring_profile_ref: str
    reviewer_grant_ref: str
    source_qro_ref: str
    source_graph_ref: str
    source_compiler_ir_ref: str
    source_compiler_pass_ref: str
    source_entrypoint_coverage_ref: str
    components: tuple[ModelGovernanceClosureComponentState, ...]
    policy_probes: tuple[ModelGovernancePolicyProbeState, ...]

    def __post_init__(self) -> None:
        for field in (
            "owner_user_id",
            "model_id",
            "model_asset_ref",
            "stage",
            "model_version_ref",
            "passport_ref",
            "training_plan_ref",
            "training_run_ref",
            "validation_dossier_ref",
            "promotion_gate_ref",
            "monitoring_profile_ref",
            "reviewer_grant_ref",
            "source_qro_ref",
            "source_graph_ref",
            "source_compiler_ir_ref",
            "source_compiler_pass_ref",
            "source_entrypoint_coverage_ref",
        ):
            object.__setattr__(self, field, _text(getattr(self, field)))
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("model governance closure version must be positive")
        object.__setattr__(
            self,
            "components",
            tuple(sorted(self.components, key=lambda item: (item.component_kind, item.component_ref))),
        )
        object.__setattr__(
            self,
            "policy_probes",
            tuple(sorted(self.policy_probes, key=lambda item: item.probe_name)),
        )


@dataclass(frozen=True)
class ModelGovernanceClosureReceipt:
    receipt_ref: str
    owner_user_id: str
    model_id: str
    version: int
    passport_ref: str
    snapshot: ModelGovernanceClosureSnapshot
    receipt_version: str = MODEL_GOVERNANCE_CLOSURE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for field in ("receipt_ref", "owner_user_id", "model_id", "passport_ref", "receipt_version"):
            object.__setattr__(self, field, _text(getattr(self, field)))

    @property
    def canonical_receipt_ref(self) -> str:
        return model_governance_closure_receipt_identity(
            owner_user_id=self.owner_user_id,
            model_id=self.model_id,
            version=self.version,
            passport_ref=self.passport_ref,
            snapshot=self.snapshot,
            receipt_version=self.receipt_version,
        )


@dataclass(frozen=True)
class ModelGovernanceClosureSemanticMaterial:
    subject_ref: str
    producer_refs: tuple[str, ...]
    store_refs: tuple[str, ...]
    consumer_refs: tuple[str, ...]
    gate_verdict_refs: tuple[str, ...]
    test_refs: tuple[str, ...]


def model_governance_closure_receipt_identity(
    *,
    owner_user_id: str,
    model_id: str,
    version: int,
    passport_ref: str,
    snapshot: ModelGovernanceClosureSnapshot,
    receipt_version: str = MODEL_GOVERNANCE_CLOSURE_RECEIPT_VERSION,
) -> str:
    return "model_governance_closure_receipt:" + content_hash(
        {
            "owner_user_id": owner_user_id,
            "model_id": model_id,
            "version": version,
            "passport_ref": passport_ref,
            "snapshot": asdict(snapshot),
            "receipt_version": receipt_version,
        }
    )


def _component_from_dict(value: Any) -> ModelGovernanceClosureComponentState:
    expected = {"component_kind", "component_ref", "state_hash"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("model governance closure component has an inexact field set")
    return ModelGovernanceClosureComponentState(**value)


def _probe_from_dict(value: Any) -> ModelGovernancePolicyProbeState:
    expected = {"probe_name", "accepted", "violation_codes"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("model governance policy probe has an inexact field set")
    if not isinstance(value["accepted"], bool) or not isinstance(value["violation_codes"], list):
        raise ValueError("model governance policy probe has invalid field types")
    return ModelGovernancePolicyProbeState(
        probe_name=value["probe_name"],
        accepted=value["accepted"],
        violation_codes=tuple(value["violation_codes"]),
    )


def model_governance_closure_snapshot_from_dict(value: Any) -> ModelGovernanceClosureSnapshot:
    expected = {
        "owner_user_id",
        "model_id",
        "model_asset_ref",
        "version",
        "stage",
        "model_version_ref",
        "passport_ref",
        "training_plan_ref",
        "training_run_ref",
        "validation_dossier_ref",
        "promotion_gate_ref",
        "monitoring_profile_ref",
        "reviewer_grant_ref",
        "source_qro_ref",
        "source_graph_ref",
        "source_compiler_ir_ref",
        "source_compiler_pass_ref",
        "source_entrypoint_coverage_ref",
        "components",
        "policy_probes",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or not isinstance(value["components"], list)
        or not isinstance(value["policy_probes"], list)
    ):
        raise ValueError("model governance closure snapshot has an inexact field set")
    return ModelGovernanceClosureSnapshot(
        **{
            **{key: item for key, item in value.items() if key not in {"components", "policy_probes"}},
            "components": tuple(_component_from_dict(item) for item in value["components"]),
            "policy_probes": tuple(_probe_from_dict(item) for item in value["policy_probes"]),
        }
    )


def model_governance_closure_receipt_from_dict(value: Any) -> ModelGovernanceClosureReceipt:
    expected = {
        "receipt_ref",
        "owner_user_id",
        "model_id",
        "version",
        "passport_ref",
        "snapshot",
        "receipt_version",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("model governance closure receipt has an inexact field set")
    return ModelGovernanceClosureReceipt(
        receipt_ref=value["receipt_ref"],
        owner_user_id=value["owner_user_id"],
        model_id=value["model_id"],
        version=value["version"],
        passport_ref=value["passport_ref"],
        snapshot=model_governance_closure_snapshot_from_dict(value["snapshot"]),
        receipt_version=value["receipt_version"],
    )


def validate_model_governance_closure_receipt_shape(
    receipt: ModelGovernanceClosureReceipt,
) -> ModelGovernanceClosureDecision:
    violations: list[ModelGovernanceClosureViolation] = []

    def reject(code: str, message: str, field: str, ref: str) -> None:
        violations.append(ModelGovernanceClosureViolation(code, message, field, ref))

    if receipt.receipt_version != MODEL_GOVERNANCE_CLOSURE_RECEIPT_VERSION:
        reject(
            "model_governance_closure_receipt_version_unsupported",
            "model governance closure receipt version is unsupported",
            "receipt_version",
            receipt.receipt_ref,
        )
    for field in ("receipt_ref", "owner_user_id", "model_id", "passport_ref"):
        if not getattr(receipt, field):
            reject(
                "model_governance_closure_required_field_missing",
                "model governance closure receipt is incomplete",
                field,
                receipt.receipt_ref,
            )
    if receipt.snapshot.owner_user_id != receipt.owner_user_id:
        reject("model_governance_closure_owner_mismatch", "snapshot owner mismatch", "snapshot", receipt.receipt_ref)
    if receipt.snapshot.model_id != receipt.model_id or receipt.snapshot.version != receipt.version:
        reject("model_governance_closure_model_mismatch", "snapshot model identity mismatch", "snapshot", receipt.receipt_ref)
    if receipt.snapshot.passport_ref != receipt.passport_ref:
        reject("model_governance_closure_passport_mismatch", "snapshot passport mismatch", "snapshot", receipt.receipt_ref)
    if receipt.receipt_ref and receipt.receipt_ref != receipt.canonical_receipt_ref:
        reject("model_governance_closure_identity_mismatch", "receipt_ref must bind the exact snapshot", "receipt_ref", receipt.receipt_ref)
    refs = [item.component_ref for item in receipt.snapshot.components]
    if not refs or len(refs) != len(set(refs)):
        reject("model_governance_closure_component_identity_invalid", "component refs must be non-empty and unique", "components", receipt.receipt_ref)
    required_kinds = {
        "model_type_card",
        "training_plan",
        "training_spec",
        "training_source_bundle",
        "training_run",
        "training_entrypoint_lineage",
        "model_version",
        "model_passport",
        "validation_dossier",
        "model_artifact",
        "artifact_inspection",
        "monitoring_profile",
        "promotion_record",
        "reviewer_grant",
        "recertification_producer_status",
        "recertification_evidence",
        "policy_engine",
    }
    kinds = {item.component_kind for item in receipt.snapshot.components}
    missing = sorted(required_kinds - kinds)
    if missing:
        reject("model_governance_closure_components_missing", f"required components missing: {missing!r}", "components", receipt.receipt_ref)
    probes = {item.probe_name: item for item in receipt.snapshot.policy_probes}
    if set(probes) != set(_POLICY_EXPECTATIONS):
        reject("model_governance_closure_policy_probe_set_invalid", "§15 negative policy probes are incomplete", "policy_probes", receipt.receipt_ref)
    else:
        for name, expected in _POLICY_EXPECTATIONS.items():
            probe = probes[name]
            if probe.accepted or not expected.issubset(set(probe.violation_codes)):
                reject("model_governance_closure_policy_probe_failed", f"policy probe {name} did not fail closed", "policy_probes", name)
    return ModelGovernanceClosureDecision(not violations, tuple(violations))


class PersistentModelGovernanceClosureRegistry:
    """Hash-chained §15 receipts over current production governance stores."""

    def __init__(
        self,
        path: Path | str,
        *,
        governance_registry: PersistentModelGovernanceRegistry,
        training_service: Any,
        model_registry: ModelRegistry,
        recertification_event_registry: PersistentModelRecertificationEventRegistry
        | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._governance = governance_registry
        self._training = training_service
        self._models = model_registry
        attached_events = getattr(
            training_service,
            "_model_recertification_events",
            None,
        )
        self._recertification_events = (
            recertification_event_registry or attached_events
        )
        if getattr(training_service, "_model_governance", None) is not governance_registry:
            raise ValueError("model governance closure requires the training service governance registry identity")
        if getattr(training_service, "_models", None) is not model_registry:
            raise ValueError("model governance closure requires the training service model registry identity")
        if not isinstance(
            self._recertification_events,
            PersistentModelRecertificationEventRegistry,
        ):
            raise ValueError(
                "model governance closure requires the automatic recertification event registry"
            )
        if attached_events is not self._recertification_events:
            raise ValueError(
                "model governance closure recertification registry identity mismatch"
            )
        self._recertification_evidence = getattr(
            self._recertification_events,
            "evidence_registry",
            None,
        )
        if not isinstance(
            self._recertification_evidence,
            PersistentModelRecertificationEvidenceRegistry,
        ):
            raise ValueError(
                "model governance closure requires the durable recertification evidence registry"
            )
        if (
            getattr(model_registry, "model_recertification_event_registry", None)
            is not self._recertification_events
        ):
            raise ValueError(
                "model governance closure model registry recertification identity mismatch"
            )
        self._thread_lock = threading.RLock()
        self._receipts: dict[tuple[str, str], ModelGovernanceClosureReceipt] = {}
        self._heads: dict[tuple[str, str, int], ModelGovernanceClosureReceipt] = {}
        self._last_revision = 0
        self._last_record_hash = ""
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    def _exclusive_lock(self):
        class _Lock:
            def __init__(inner, path: Path) -> None:
                inner.path = path
                inner.fd: int | None = None
                inner.held: Any = None

            def __enter__(inner):
                inner.fd = os.open(inner.path, os.O_RDWR | os.O_CREAT, 0o600)
                os.chmod(inner.path, 0o600)
                inner.held = acquire_exclusive_fd(inner.fd, timeout_seconds=30.0)
                return inner

            def __exit__(inner, exc_type, exc, tb) -> None:
                if inner.held is not None:
                    inner.held.release()
                if inner.fd is not None:
                    os.close(inner.fd)

        return _Lock(self._lock_path)

    def _reset(self) -> None:
        self._receipts = {}
        self._heads = {}
        self._last_revision = 0
        self._last_record_hash = ""

    def _load_existing_unlocked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                self._apply_row(row)
            except Exception as exc:  # noqa: BLE001 - corrupt evidence must fail closed.
                raise ModelGovernanceClosureError(
                    f"invalid persisted model governance closure row at {self._path}:{line_no}"
                ) from exc

    def _apply_row(self, row: Any) -> ModelGovernanceClosureReceipt:
        expected = {
            "schema_version",
            "event_type",
            "owner_user_id",
            "revision",
            "previous_record_hash",
            "record_hash",
            "model_governance_closure",
        }
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError("model governance closure row has an inexact field set")
        if row["schema_version"] != MODEL_GOVERNANCE_CLOSURE_SCHEMA_VERSION:
            raise ValueError("unsupported model governance closure schema version")
        if row["event_type"] != "model_governance_closure_receipt_recorded":
            raise ValueError("unsupported model governance closure event type")
        revision = row["revision"]
        if type(revision) is not int or revision != self._last_revision + 1:
            raise ValueError("model governance closure revision chain is discontinuous")
        if row["previous_record_hash"] != self._last_record_hash:
            raise ValueError("model governance closure previous record hash mismatch")
        unsigned = dict(row)
        supplied_hash = _text(unsigned.pop("record_hash"))
        if supplied_hash != _state_hash(unsigned):
            raise ValueError("model governance closure record hash mismatch")
        owner = _owner(row["owner_user_id"])
        receipt = model_governance_closure_receipt_from_dict(row["model_governance_closure"])
        if receipt.owner_user_id != owner:
            raise ValueError("model governance closure owner envelope mismatch")
        decision = validate_model_governance_closure_receipt_shape(receipt)
        if not decision.accepted:
            raise ValueError(",".join(item.code for item in decision.violations))
        key = (owner, receipt.receipt_ref)
        if key in self._receipts and self._receipts[key] != receipt:
            raise ValueError("model governance closure receipt identity collision")
        self._receipts[key] = receipt
        self._heads[(owner, receipt.model_id, receipt.version)] = receipt
        self._last_revision = revision
        self._last_record_hash = supplied_hash
        return receipt

    def _atomic_append(self, receipt: ModelGovernanceClosureReceipt) -> None:
        unsigned = {
            "schema_version": MODEL_GOVERNANCE_CLOSURE_SCHEMA_VERSION,
            "event_type": "model_governance_closure_receipt_recorded",
            "owner_user_id": receipt.owner_user_id,
            "revision": self._last_revision + 1,
            "previous_record_hash": self._last_record_hash,
            "model_governance_closure": asdict(receipt),
        }
        row = {**unsigned, "record_hash": _state_hash(unsigned)}
        original_exists = self._path.exists()
        original = self._path.read_bytes() if original_exists else b""
        previous = original
        if previous and not previous.endswith(b"\n"):
            previous += b"\n"
        encoded = previous + _canonical_json(row).encode("utf-8") + b"\n"
        fd, raw_temp = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        temp_path = Path(raw_temp)
        replaced = False
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._path)
            replaced = True
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception as exc:
            if replaced:
                try:
                    self._restore_original(existed=original_exists, payload=original)
                except Exception as recovery_exc:  # noqa: BLE001
                    raise ModelGovernanceClosureCommitUncertain(
                        "model governance closure append failed and rollback is uncertain"
                    ) from recovery_exc
            raise exc
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _restore_original(self, *, existed: bool, payload: bytes) -> None:
        if not existed:
            if self._path.exists():
                self._path.unlink()
        else:
            fd, raw_temp = tempfile.mkstemp(prefix=f".{self._path.name}.rollback.", dir=self._path.parent)
            temp_path = Path(raw_temp)
            replaced = False
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb", closefd=True) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self._path)
                replaced = True
            finally:
                if not replaced and temp_path.exists():
                    temp_path.unlink()
        directory_fd = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _strict_backing_files(self) -> None:
        jobs = getattr(self._training, "_jobs", None)
        runs = getattr(self._training, "_runs", None)
        gate_service = getattr(self._models, "_gate_service", None)
        gate_store = getattr(gate_service, "_store", None)
        reviewer = getattr(self._models, "reviewer_grant_registry", None)
        paths = (
            (self._governance.path, "model governance"),
            (_private_path(jobs, "_path", label="training job store"), "training job"),
            (_private_path(runs, "_store", "_path", label="training run store"), "training run"),
            (_private_path(self._models, "_store", "_path", label="model registry"), "model registry"),
            (_private_path(gate_store, "_store", "_path", label="approval gate store"), "approval gate"),
            (Path(reviewer.path), "reviewer grant"),
            (self._recertification_evidence.path, "model recertification evidence"),
        )
        for path, label in paths:
            if label == "model recertification evidence" and not path.exists():
                continue
            _strict_json_rows(path, label=label)
        if self._recertification_events.path.exists():
            _strict_json_rows(
                self._recertification_events.path,
                label="model recertification event",
            )

    @staticmethod
    def _component(kind: str, ref: str, state: Any) -> ModelGovernanceClosureComponentState:
        return ModelGovernanceClosureComponentState(kind, _real_ref(ref, field=f"{kind}.ref"), _state_hash(state))

    @staticmethod
    def _latest_profile(
        governance: PersistentModelGovernanceRegistry,
        owner: str,
        passport: ModelGovernancePassport,
    ) -> ModelMonitoringProfile:
        matches = [
            item
            for item in governance.monitoring_profiles(owner_user_id=owner)
            if item.model_passport_ref == passport.passport_id
            and item.model_version_ref == passport.model_version_ref
        ]
        if not matches:
            raise ModelGovernanceClosureError("current owner-scoped monitoring profile is missing")
        return matches[-1]

    @staticmethod
    def _policy_probes(passport: ModelGovernancePassport) -> tuple[ModelGovernancePolicyProbeState, ...]:
        artifact = passport.artifact_manifest[0]
        unsafe = ModelArtifactManifestEntry(
            artifact_ref=artifact.artifact_ref,
            uri="external://model.pkl",
            artifact_format=ModelArtifactFormat.PICKLE,
            source=ModelArtifactSource.EXTERNAL,
            content_hash=artifact.content_hash,
            producer_run_ref=artifact.producer_run_ref,
            direct_load=True,
            sandbox_inspection_ref=artifact.sandbox_inspection_ref,
        )
        torch_artifact = ModelArtifactManifestEntry(
            artifact_ref=artifact.artifact_ref,
            uri="project://model.pt",
            artifact_format=ModelArtifactFormat.TORCH,
            source=ModelArtifactSource.PROJECT_PRODUCED,
            content_hash=artifact.content_hash,
            producer_run_ref=artifact.producer_run_ref,
            direct_load=False,
            sandbox_inspection_ref=artifact.sandbox_inspection_ref,
        )
        cases = {
            "missing_validation_dossier": (
                replace(passport, validation_dossier_ref=None, passport_id=""),
                (),
            ),
            "external_pickle_direct_load": (
                replace(passport, artifact_manifest=(unsafe,), passport_id=""),
                (),
            ),
            "high_risk_without_challenger": (
                replace(
                    passport,
                    model_risk_tier=ModelRiskTier.HIGH,
                    challenger_result=None,
                    passport_id="",
                ),
                (),
            ),
            "material_change_without_recertification": (
                replace(passport, recertification_records=(), passport_id=""),
                (RecertificationTrigger.MATERIAL_MODEL_CHANGE,),
            ),
            "data_schema_change_without_recertification": (
                replace(passport, recertification_records=(), passport_id=""),
                (RecertificationTrigger.DATA_SCHEMA_CHANGE,),
            ),
            "feature_drift_without_recertification": (
                replace(passport, recertification_records=(), passport_id=""),
                (RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,),
            ),
            "performance_degradation_without_recertification": (
                replace(passport, recertification_records=(), passport_id=""),
                (RecertificationTrigger.PERFORMANCE_DEGRADATION,),
            ),
            "new_asset_class_without_recertification": (
                replace(passport, recertification_records=(), passport_id=""),
                (RecertificationTrigger.NEW_ASSET_CLASS,),
            ),
            "new_execution_environment_without_recertification": (
                replace(passport, recertification_records=(), passport_id=""),
                (RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT,),
            ),
            "dependency_update_without_recertification": (
                replace(passport, recertification_records=(), passport_id=""),
                (RecertificationTrigger.DEPENDENCY_UPDATE,),
            ),
            "torch_without_weights_only": (
                replace(
                    passport,
                    artifact_manifest=(torch_artifact,),
                    safe_loading_policy=replace(
                        passport.safe_loading_policy,
                        torch_weights_only=False,
                    ),
                    passport_id="",
                ),
                (),
            ),
        }
        states = []
        for name, (candidate, events) in cases.items():
            decision = validate_model_promotion(candidate, change_events=events)
            states.append(
                ModelGovernancePolicyProbeState(
                    probe_name=name,
                    accepted=decision.accepted,
                    violation_codes=tuple(item.code for item in decision.violations),
                )
            )
        return tuple(states)

    def _promotion(self, *, owner: str, model: str, version: ModelVersion, passport: ModelGovernancePassport):
        gate_service = getattr(self._models, "_gate_service", None)
        gate_store = getattr(gate_service, "_store", None)
        gate_path = _private_path(gate_store, "_store", "_path", label="approval gate store")
        rows = _strict_json_rows(gate_path, label="approval gate")
        latest: dict[str, tuple[int, Any]] = {}
        from ..approval.schema import ApprovalGate

        for index, row in enumerate(rows):
            try:
                gate = ApprovalGate.from_dict(row)
            except Exception as exc:  # noqa: BLE001
                raise ModelGovernanceClosureError("approval gate store contains an invalid gate") from exc
            if not gate.gate_id:
                raise ModelGovernanceClosureError("approval gate store contains an ownerless identity")
            latest[gate.gate_id] = (index, gate)
        expected_action = "promote_production" if version.stage == "production" else "promote_staging"
        candidates = []
        for index, gate in latest.values():
            evidence = gate.evidence if isinstance(gate.evidence, dict) else {}
            if (
                gate.model_id == version.model_asset_ref
                and gate.version == version.version
                and gate.to_stage == version.stage
                and gate.action_kind == expected_action
                and gate.decision == "approved"
                and evidence.get("owner_user_id") == owner
                and evidence.get("logical_model_id") == model
                and evidence.get("model_asset_ref") == version.model_asset_ref
                and evidence.get("model_passport_ref") == passport.passport_id
                and evidence.get("validation_dossier_ref") == passport.validation_dossier_ref
            ):
                candidates.append((index, gate))
        if not candidates:
            raise ModelGovernanceClosureError("current approved owner-scoped promotion record is missing")
        gate = max(candidates, key=lambda item: item[0])[1]
        try:
            current = self._models.promotion_gate(
                gate.gate_id,
                owner_user_id=owner,
            )
        except Exception as exc:  # noqa: BLE001 - current promotion policy is fail closed.
            raise ModelGovernanceClosureError(
                f"promotion record no longer satisfies current §15 policy: {exc}"
            ) from exc
        if current != gate:
            raise ModelGovernanceClosureError("selected promotion record is not current")
        if not gate.side_effect_executed or gate.side_effect_ref != (
            f"stage:{owner}:{model}:v{version.version}:{version.stage}"
        ):
            raise ModelGovernanceClosureError("promotion record does not bind the executed model stage")
        if not gate.approver or gate.approver.strip().casefold() == gate.created_by.strip().casefold():
            raise ModelGovernanceClosureError("promotion record lacks an independent reviewer")
        evidence = gate.evidence or {}
        grant_id = _real_ref(evidence.get("reviewer_grant_id"), field="reviewer_grant_id")
        grant_hash = _real_ref(evidence.get("reviewer_grant_record_hash"), field="reviewer_grant_record_hash")
        reviewer = _real_ref(evidence.get("reviewer_user_id"), field="reviewer_user_id")
        if reviewer != gate.approver:
            raise ModelGovernanceClosureError("promotion reviewer grant does not match approver")
        try:
            grant = self._models.promotion_reviewer_authority_evidence(
                gate.gate_id,
                model_id=model,
                reviewer_user_id=reviewer,
                grant_id=grant_id,
                grant_record_hash=grant_hash,
                permission="approve",
            )
        except Exception as exc:  # noqa: BLE001 - authority resolution must fail closed.
            raise ModelGovernanceClosureError("promotion reviewer authority evidence is invalid") from exc
        gate_marker = {
            "durable_row_number": max(candidates, key=lambda item: item[0])[0] + 1,
            "durable_row_hash": _state_hash(gate.to_dict()),
        }
        return gate, grant, gate_marker

    def _resolve_snapshot(self, *, owner: str, model: str, version_number: int) -> ModelGovernanceClosureSnapshot:
        self._strict_backing_files()
        versions = [
            item
            for item in self._models.list_versions(model, owner_user_id=owner)
            if item.version == version_number
        ]
        if len(versions) != 1:
            raise ModelGovernanceClosureError("owner-scoped model version is missing or ambiguous")
        version = versions[0]
        if version.stage not in {"staging", "production"}:
            raise ModelGovernanceClosureError("§15 closure requires an approved staging or production model")
        passport_ref = _real_ref(version.model_passport_ref, field="model_passport_ref")
        try:
            passport = self._governance.passport(passport_ref, owner_user_id=owner)
        except KeyError as exc:
            raise ModelGovernanceClosureError("model passport is not recorded for owner") from exc
        expected_version_ref = f"model_version:{model}:v{version_number}"
        if (
            passport.passport_id != passport_ref
            or passport.owner_user_id != owner
            or passport.model_version_ref != expected_version_ref
        ):
            raise ModelGovernanceClosureError("model passport does not bind the owner-scoped model version")
        if version.model_asset_ref == "" or version.validation_dossier_ref != passport.validation_dossier_ref:
            raise ModelGovernanceClosureError("model version dossier or asset binding is invalid")
        if version.source_run_id is None:
            raise ModelGovernanceClosureError("model version source run is missing")

        plan_prefix = "training_plan:"
        run_prefix = "training_run:"
        dossier_prefix = "validation_dossier:"
        if not passport.training_plan_ref.startswith(plan_prefix):
            raise ModelGovernanceClosureError("training_plan_ref is not produced by the training service")
        job_id = passport.training_plan_ref[len(plan_prefix) :]
        if not job_id or passport.validation_dossier_ref != dossier_prefix + job_id:
            raise ModelGovernanceClosureError("validation dossier does not bind the training plan")
        if not passport.training_run_ref.startswith(run_prefix):
            raise ModelGovernanceClosureError("training_run_ref is not produced by the run store")
        run_id = passport.training_run_ref[len(run_prefix) :]
        if run_id != version.source_run_id:
            raise ModelGovernanceClosureError("model version source run does not match passport")
        try:
            job = self._training.get_job(job_id)
            run = getattr(self._training, "_runs").get_run(run_id)
        except KeyError as exc:
            raise ModelGovernanceClosureError("training job or run is missing") from exc
        if (
            job.status != "succeeded"
            or _text(getattr(job, "owner_user_id", "")) != owner
            or job.model != model
            or job.run_id != run_id
            or job.model_version != version_number
            or job.model_passport_ref != passport.passport_id
            or job.validation_dossier_ref != passport.validation_dossier_ref
        ):
            raise ModelGovernanceClosureError("training job does not bind the current model version")
        source_qro_ref = _real_ref(job.qro_id, field="training_job.qro_id")
        source_graph_ref = _real_ref(
            job.research_graph_command_id,
            field="training_job.research_graph_command_id",
        )
        source_compiler_ir_ref = _real_ref(
            job.compiler_ir_ref,
            field="training_job.compiler_ir_ref",
        )
        source_compiler_pass_ref = _real_ref(
            job.compiler_pass_ref,
            field="training_job.compiler_pass_ref",
        )
        source_entrypoint_coverage_ref = _real_ref(
            job.entrypoint_coverage_ref,
            field="training_job.entrypoint_coverage_ref",
        )
        if (
            run.status != "succeeded"
            or not run.finished_at_utc
            or job.experiment_id != run.experiment_id
            or run.inputs != job.request
        ):
            raise ModelGovernanceClosureError("training run is not durably succeeded")

        job_path = _private_path(getattr(self._training, "_jobs", None), "_path", label="training job store")
        run_path = _private_path(
            getattr(self._training, "_runs", None),
            "_store",
            "_path",
            label="training run store",
        )
        model_path = _private_path(self._models, "_store", "_path", label="model registry")
        job_marker = _latest_row_marker(
            job_path,
            label="training job",
            matches=lambda row: row.get("job_id") == job_id,
            expected=asdict(job),
        )
        run_marker = _latest_row_marker(
            run_path,
            label="training run",
            matches=lambda row: row.get("run_id") == run_id,
            expected=asdict(run),
        )
        version_marker = _latest_row_marker(
            model_path,
            label="model version",
            matches=lambda row: (
                row.get("owner_user_id") == owner
                and row.get("model_id") == model
                and row.get("version") == version_number
            ),
            expected=version.to_dict(),
        )

        training_root = Path(getattr(self._training, "_root", ""))
        job_root = (training_root / job_id).resolve()
        try:
            job_root.relative_to(training_root.resolve())
        except ValueError as exc:
            raise ModelGovernanceClosureError("training job root escapes training service root") from exc
        if Path(job.artifact_dir or "").resolve() != job_root:
            raise ModelGovernanceClosureError("training job artifact directory does not match its durable root")
        spec_bytes = _read_confined_file(job_root / "spec.json", root=job_root, label="training spec")
        dossier_bytes = _read_confined_file(
            job_root / "validation_dossier.json", root=job_root, label="validation dossier"
        )
        spec = _json_object(spec_bytes, label="training spec")
        dossier = _json_object(dossier_bytes, label="validation dossier")
        if spec != job.request:
            raise ModelGovernanceClosureError("training spec does not match the current training job")
        if set(dossier) != _REQUIRED_DOSSIER_FIELDS:
            raise ModelGovernanceClosureError("validation dossier has an inexact field set")

        card_key = f"model_type_card:{model}"
        if passport.model_type_card_ref != card_key:
            raise ModelGovernanceClosureError("model type card does not match model identity")
        card_path = DEFAULT_CARDS_DIR / f"{model}.md"
        card_bytes = _read_confined_file(card_path, root=DEFAULT_CARDS_DIR, label="model type card")
        card = parse_model_card(card_path)
        if (
            card.key != model
            or job.task not in card.tasks
            or job.family != card.family
            or not card.runnable
        ):
            raise ModelGovernanceClosureError("model type card does not authorize the training plan")

        try:
            recertification_resolution = resolve_current_recertification_requirements(
                governance=self._governance,
                event_registry=self._recertification_events,
                training_jobs=getattr(self._training, "_jobs", None),
                owner_user_id=owner,
                current_passport_ref=passport.passport_id,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelGovernanceClosureError(
                f"current automatic recertification requirements are not cleared: {exc}"
            ) from exc
        change_events = tuple(
            requirement.trigger.value
            for requirement in recertification_resolution.requirements
        )
        expected_training_hash = model_training_code_hash(spec)
        if passport.training_code_hash != expected_training_hash:
            raise ModelGovernanceClosureError(
                "passport training_code_hash does not bind the executable training source and plan"
            )
        governance_rows = _strict_json_rows(self._governance.path, label="model governance")
        passport_history = [
            row
            for row in governance_rows
            if row.get("schema_version") == 2
            and row.get("event_type") == _MODEL_VERSION_EVENT
            and row.get("owner_user_id") == owner
            and isinstance(row.get("passport"), dict)
            and row["passport"].get("passport_id") == passport.passport_id
        ]
        if not passport_history:
            raise ModelGovernanceClosureError("training passport durable history is missing")
        if (
            _stable(passport_history[-1]["passport"]) != _stable(passport)
            or any(row.get("recorded_by") != "training_service" for row in passport_history)
            or any(
                row["passport"].get("training_code_hash") != expected_training_hash
                for row in passport_history
            )
        ):
            raise ModelGovernanceClosureError(
                "training_code_hash must be immutable and correct from the initial training-service passport"
            )
        passport_history_marker = {
            "initial_revision": passport_history[0].get("revision"),
            "current_revision": passport_history[-1].get("revision"),
            "current_row_hash": _state_hash(passport_history[-1]),
        }
        source_bundle = _source_bundle()

        if len(passport.artifact_manifest) != 1:
            raise ModelGovernanceClosureError("training-service §15 closure requires exactly one model artifact")
        artifact = passport.artifact_manifest[0]
        if artifact.artifact_ref != f"model_artifact:{job_id}":
            raise ModelGovernanceClosureError("model artifact does not bind the training job")
        if artifact.producer_run_ref != passport.training_run_ref:
            raise ModelGovernanceClosureError("model artifact producer run mismatch")
        if str(getattr(artifact.source, "value", artifact.source)) not in {
            ModelArtifactSource.PROJECT_PRODUCED.value,
            ModelArtifactSource.INTERNAL_REGISTRY.value,
        }:
            raise ModelGovernanceClosureError("model artifact source is not governed project output")
        try:
            resolved_vendor_dependencies = self._recertification_evidence.resolve_dependencies(
                passport.vendor_dependency_refs,
                owner_user_id=owner,
                dependency_kind=DependencyKind.VENDOR,
            )
            resolved_foundation_dependencies = self._recertification_evidence.resolve_dependencies(
                passport.foundation_model_dependency_refs,
                owner_user_id=owner,
                dependency_kind=DependencyKind.FOUNDATION_MODEL,
            )
        except (KeyError, ModelEvidenceError) as exc:
            raise ModelGovernanceClosureError(
                "external model dependencies require a durable dependency producer"
            ) from exc
        resolved_dependencies = (
            *resolved_vendor_dependencies,
            *resolved_foundation_dependencies,
        )
        risk_tier = str(getattr(passport.model_risk_tier, "value", passport.model_risk_tier))
        challenger_result = None
        if risk_tier in {ModelRiskTier.HIGH.value, ModelRiskTier.CRITICAL.value}:
            try:
                challenger_result = self._recertification_evidence.challenger_result(
                    _real_ref(passport.challenger_result, field="challenger_result"),
                    owner_user_id=owner,
                )
            except (KeyError, ModelEvidenceError) as exc:
                raise ModelGovernanceClosureError(
                    "high-risk challenger evidence requires a durable challenger-result producer"
                ) from exc
            succeeded_model_jobs = {
                f"training_run:{item.run_id}": item
                for item in self._training.list_jobs()
                if _text(getattr(item, "owner_user_id", "")) == owner
                and getattr(item, "model", None) == model
                and getattr(item, "status", None) == "succeeded"
                and _text(getattr(item, "run_id", ""))
            }
            bound_run_refs = {
                challenger_result.baseline_run_ref,
                challenger_result.challenger_run_ref,
            }
            metric_values: dict[str, float] = {}
            try:
                for run_ref in bound_run_refs:
                    prefix = "training_run:"
                    if not run_ref.startswith(prefix):
                        raise ValueError("challenger run ref is not training-service produced")
                    bound_run = getattr(self._training, "_runs").get_run(run_ref[len(prefix):])
                    if bound_run.status != "succeeded":
                        raise ValueError("challenger run is not succeeded")
                    value = bound_run.metrics[challenger_result.metric_ref]
                    if isinstance(value, bool):
                        raise ValueError("challenger metric is not numeric")
                    metric_values[run_ref] = float(value)
            except (KeyError, TypeError, ValueError) as exc:
                raise ModelGovernanceClosureError(
                    "durable challenger-result producer metric evidence is missing"
                ) from exc
            if (
                challenger_result.model_type_card_ref != passport.model_type_card_ref
                or challenger_result.model_version_ref != passport.model_version_ref
                or challenger_result.model_passport_ref != passport.passport_id
                or challenger_result.challenger_run_ref != passport.training_run_ref
                or not challenger_result.passed
                or bound_run_refs - set(succeeded_model_jobs)
                or getattr(
                    succeeded_model_jobs.get(challenger_result.challenger_run_ref),
                    "model_passport_ref",
                    None,
                )
                != passport.passport_id
                or getattr(
                    succeeded_model_jobs.get(challenger_result.challenger_run_ref),
                    "model_version",
                    None,
                )
                != version.version
                or getattr(
                    succeeded_model_jobs.get(challenger_result.challenger_run_ref),
                    "validation_dossier_ref",
                    None,
                )
                != passport.validation_dossier_ref
                or metric_values[challenger_result.baseline_run_ref]
                != challenger_result.baseline_value
                or metric_values[challenger_result.challenger_run_ref]
                != challenger_result.challenger_value
            ):
                raise ModelGovernanceClosureError(
                    "durable challenger-result producer does not bind two succeeded owner/model runs"
                )
        artifact_path = Path(artifact.uri)
        artifact_bytes = _read_confined_file(artifact_path, root=job_root, label="model artifact")
        artifact_hash = _sha256_bytes(artifact_bytes)
        if artifact_hash != artifact.content_hash:
            raise ModelGovernanceClosureError("model artifact bytes do not match passport hash")
        if version.artifact_path != str(artifact_path) or str(artifact_path) not in run.artifact_paths:
            raise ModelGovernanceClosureError("model registry or run artifact path mismatch")

        expected_dossier = {
            "validation_dossier_ref": passport.validation_dossier_ref,
            "model_version_ref": passport.model_version_ref,
            "training_run_ref": passport.training_run_ref,
            "dataset_refs": list(passport.dataset_refs),
            "feature_refs": list(passport.feature_refs),
            "label_refs": list(passport.label_refs),
            "metrics": job.metrics,
            "artifact_path": str(artifact_path),
            "artifact_hash": artifact.content_hash,
            "artifact_inspection_ref": artifact.sandbox_inspection_ref,
        }
        for key, expected in expected_dossier.items():
            if dossier.get(key) != expected:
                raise ModelGovernanceClosureError(f"validation dossier {key} does not match current records")
        if dossier["result_oos_metrics"] != job.metrics or version.metrics != job.metrics or run.metrics != job.metrics:
            raise ModelGovernanceClosureError("training metrics differ across job, run, model, and dossier")
        if dossier["cv_scheme"] != spec.get("cv_scheme") or dossier["n_splits"] != spec.get("n_splits"):
            raise ModelGovernanceClosureError("validation dossier does not bind the training plan validation method")
        if type(dossier["fold_count"]) is not int or dossier["fold_count"] < 0:
            raise ModelGovernanceClosureError("validation dossier fold_count is invalid")

        policy_passport = replace(
            passport,
            recertification_records=tuple(
                record.recertification_record_id
                for record in recertification_resolution.recertification_records
            ),
            passport_id="",
        )
        promotion_decision = validate_model_promotion(
            policy_passport,
            change_events=change_events,
        )
        if not promotion_decision.accepted:
            raise ModelGovernanceClosureError(
                "current passport fails §15 promotion policy: "
                + ",".join(item.code for item in promotion_decision.violations)
            )
        declared_triggers = {
            str(getattr(item, "value", item)) for item in passport.recertification_triggers
        }
        if declared_triggers != _REQUIRED_RECERTIFICATION_TRIGGERS:
            raise ModelGovernanceClosureError("passport recertification triggers are incomplete or inexact")
        if not (
            passport.safe_loading_policy.sandboxed_load_inspect
            and passport.safe_loading_policy.prefer_safe_tensors
            and not passport.safe_loading_policy.direct_load_allowed
        ):
            raise ModelGovernanceClosureError("passport safe loading policy is incomplete")
        if artifact.is_torch and passport.safe_loading_policy.torch_weights_only is not True:
            raise ModelGovernanceClosureError("torch artifact does not require weights_only loading")

        inspections = [
            item
            for item in self._governance.artifact_inspections(owner_user_id=owner)
            if item.model_passport_ref == passport.passport_id
            and item.artifact_ref == artifact.artifact_ref
        ]
        if not inspections:
            raise ModelGovernanceClosureError("current artifact inspection is missing")
        inspection = inspections[-1]
        if (
            inspection.inspection_status != "accepted"
            or inspection.inspection_ref != artifact.sandbox_inspection_ref
            or inspection.artifact_hash != artifact.content_hash
            or dossier["artifact_inspection_mode"] != inspection.inspection_mode
        ):
            raise ModelGovernanceClosureError("artifact inspection does not bind current artifact bytes")
        if artifact.is_unsafe_serialized and inspection.inspection_mode != "metadata_only_no_deserialize":
            raise ModelGovernanceClosureError("serialized artifact inspection must not deserialize the artifact")

        profile = self._latest_profile(self._governance, owner, passport)
        profile_triggers = {
            str(getattr(item, "value", item)) for item in profile.recertification_trigger_refs
        }
        if profile_triggers != _REQUIRED_RECERTIFICATION_TRIGGERS:
            raise ModelGovernanceClosureError("monitoring profile recertification triggers are incomplete")
        if not profile.metric_refs or not profile.schedule_ref or not profile.alert_policy_ref:
            raise ModelGovernanceClosureError("monitoring profile is incomplete")

        # Decision authority comes only from the exact event-resolution result.
        # Caller-supplied change_events and passport recertification refs are
        # not consulted, so they cannot mint or clear an obligation.
        recertifications = list(
            recertification_resolution.recertification_records
        )
        recertification_by_requirement = {
            (str(getattr(record.trigger, "value", record.trigger)), record.change_event_ref): record
            for record in recertifications
        }

        gate, grant, gate_marker = self._promotion(
            owner=owner,
            model=model,
            version=version,
            passport=passport,
        )
        probes = self._policy_probes(passport)

        passport_head = self._governance.current_head_hash(
            passport.passport_id, owner_user_id=owner, event_type=_MODEL_VERSION_EVENT
        )
        profile_head = self._governance.current_head_hash(
            profile.monitoring_profile_id, owner_user_id=owner, event_type=_PROFILE_EVENT
        )
        inspection_head = self._governance.current_head_hash(
            inspection.artifact_inspection_record_id,
            owner_user_id=owner,
            event_type=_INSPECTION_EVENT,
        )
        components = [
            self._component("model_type_card", card_key, {"card": asdict(card), "file_hash": _sha256_bytes(card_bytes)}),
            self._component(
                "training_plan",
                passport.training_plan_ref,
                {"durable_head": job_marker, "record": job},
            ),
            self._component("training_spec", f"training_spec:{job_id}", {"content_hash": _sha256_bytes(spec_bytes), "spec": spec}),
            self._component("training_source_bundle", expected_training_hash, source_bundle),
            self._component(
                "training_run",
                passport.training_run_ref,
                {"durable_head": run_marker, "record": run},
            ),
            self._component(
                "training_entrypoint_lineage",
                source_entrypoint_coverage_ref,
                {
                    "qro_ref": source_qro_ref,
                    "research_graph_ref": source_graph_ref,
                    "compiler_ir_ref": source_compiler_ir_ref,
                    "compiler_pass_ref": source_compiler_pass_ref,
                    "entrypoint_coverage_ref": source_entrypoint_coverage_ref,
                },
            ),
            self._component(
                "model_version",
                passport.model_version_ref,
                {"durable_head": version_marker, "record": version},
            ),
            self._component(
                "model_passport",
                passport.passport_id,
                {
                    "durable_history": passport_history_marker,
                    "head_hash": passport_head,
                    "passport": passport,
                    "derived_change_events": change_events,
                },
            ),
            self._component("validation_dossier", passport.validation_dossier_ref or "", {"content_hash": _sha256_bytes(dossier_bytes), "dossier": dossier}),
            self._component("model_artifact", artifact.artifact_ref, {"content_hash": artifact_hash, "manifest": artifact}),
            self._component("artifact_inspection", inspection.artifact_inspection_record_id, {"head_hash": inspection_head, "inspection": inspection}),
            self._component("monitoring_profile", profile.monitoring_profile_id, {"head_hash": profile_head, "profile": profile}),
            self._component(
                "promotion_record",
                gate.gate_id,
                {"durable_head": gate_marker, "record": gate},
            ),
            self._component("reviewer_grant", grant.grant_id, grant),
            self._component(
                "recertification_producer_status",
                f"recertification_producer_status:{passport.passport_id}",
                {
                    "event_registry_path": self._recertification_events.path,
                    "producer_source_hash": _sha256_bytes(
                        Path(__file__).with_name("model_recertification_events.py").read_bytes()
                    ),
                    "statuses": recertification_resolution.producer_statuses,
                },
            ),
            self._component(
                "recertification_evidence",
                f"model_recertification_evidence:{passport.passport_id}",
                {
                    "producer_source_hash": _sha256_bytes(
                        Path(__file__).with_name(
                            "model_recertification_evidence.py"
                        ).read_bytes()
                    ),
                    "current_owner_state": self._recertification_evidence.current_state(
                        owner_user_id=owner,
                        model_type_card_ref=passport.model_type_card_ref,
                        model_passport_ref=passport.passport_id,
                        dependency_refs=(
                            *passport.vendor_dependency_refs,
                            *passport.foundation_model_dependency_refs,
                        ),
                        challenger_ref=passport.challenger_result,
                    ),
                    "resolved_dependencies": resolved_dependencies,
                    "challenger_result": challenger_result,
                },
            ),
            self._component("policy_engine", "model_governance_policy_engine:v1", {"source_hash": _sha256_bytes(Path(__file__).with_name("model_governance.py").read_bytes()), "probes": probes}),
        ]
        for requirement in recertification_resolution.requirements:
            record = recertification_by_requirement[
                (requirement.trigger.value, requirement.change_event_ref)
            ]
            components.append(
                self._component(
                    "recertification_requirement",
                    f"recertification_requirement:{requirement.change_event_ref}",
                    {
                        "requirement": requirement,
                        "resolved_record_ref": record.recertification_record_id,
                        "resolved_record_head_hash": self._governance.current_head_hash(
                            record.recertification_record_id,
                            owner_user_id=owner,
                            event_type=_RECERTIFICATION_EVENT,
                        ),
                    },
                )
            )
        for record in recertifications:
            head = self._governance.current_head_hash(
                record.recertification_record_id,
                owner_user_id=owner,
                event_type=_RECERTIFICATION_EVENT,
            )
            components.append(
                self._component(
                    "recertification_record",
                    record.recertification_record_id,
                    {"head_hash": head, "record": record},
                )
            )
        return ModelGovernanceClosureSnapshot(
            owner_user_id=owner,
            model_id=model,
            model_asset_ref=version.model_asset_ref,
            version=version_number,
            stage=version.stage,
            model_version_ref=passport.model_version_ref,
            passport_ref=passport.passport_id,
            training_plan_ref=passport.training_plan_ref,
            training_run_ref=passport.training_run_ref,
            validation_dossier_ref=passport.validation_dossier_ref or "",
            promotion_gate_ref=gate.gate_id,
            monitoring_profile_ref=profile.monitoring_profile_id,
            reviewer_grant_ref=grant.grant_id,
            source_qro_ref=source_qro_ref,
            source_graph_ref=source_graph_ref,
            source_compiler_ir_ref=source_compiler_ir_ref,
            source_compiler_pass_ref=source_compiler_pass_ref,
            source_entrypoint_coverage_ref=source_entrypoint_coverage_ref,
            components=tuple(components),
            policy_probes=probes,
        )

    def record_current(
        self,
        *,
        owner_user_id: str,
        model_id: str,
        version: int,
    ) -> ModelGovernanceClosureReceipt:
        owner = _owner(owner_user_id)
        model = _real_ref(model_id, field="model_id")
        if type(version) is not int or version <= 0:
            raise ModelGovernanceClosureError("version must be a positive integer")
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            first = self._resolve_snapshot(owner=owner, model=model, version_number=version)
            second = self._resolve_snapshot(owner=owner, model=model, version_number=version)
            if first != second:
                raise ModelGovernanceClosureError("model governance state changed while closure was evaluated")
            blank = ModelGovernanceClosureReceipt(
                receipt_ref="",
                owner_user_id=owner,
                model_id=model,
                version=version,
                passport_ref=second.passport_ref,
                snapshot=second,
            )
            receipt = replace(blank, receipt_ref=blank.canonical_receipt_ref)
            decision = validate_model_governance_closure_receipt_shape(receipt)
            if not decision.accepted:
                raise ModelGovernanceClosureError(",".join(item.code for item in decision.violations))
            existing = self._receipts.get((owner, receipt.receipt_ref))
            if existing is not None and self._heads.get((owner, model, version)) == existing:
                return existing
            original_exists = self._path.exists()
            original = self._path.read_bytes() if original_exists else b""
            self._atomic_append(receipt)
            try:
                third = self._resolve_snapshot(owner=owner, model=model, version_number=version)
                if third != second:
                    raise ModelGovernanceClosureError(
                        "model governance state changed while closure was committed"
                    )
                self._load_existing_unlocked()
                if self._receipts.get((owner, receipt.receipt_ref)) != receipt:
                    raise ModelGovernanceClosureError(
                        "model governance closure append cannot be verified"
                    )
            except ModelGovernanceClosureCommitUncertain:
                raise
            except Exception:
                try:
                    self._restore_original(existed=original_exists, payload=original)
                    self._load_existing_unlocked()
                except Exception as rollback_exc:  # noqa: BLE001
                    raise ModelGovernanceClosureCommitUncertain(
                        "model governance closure rollback could not be verified"
                    ) from rollback_exc
                raise
            return receipt

    def receipt(self, receipt_ref: str, *, owner_user_id: str) -> ModelGovernanceClosureReceipt:
        owner = _owner(owner_user_id)
        ref = _real_ref(receipt_ref, field="receipt_ref")
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._receipts[(owner, ref)]
            except KeyError as exc:
                raise KeyError("model governance closure receipt is not recorded for owner") from exc

    def validate_current(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> ModelGovernanceClosureDecision:
        try:
            owner = _owner(owner_user_id)
            with self._thread_lock, self._exclusive_lock():
                self._load_existing_unlocked()
                receipt = self._receipts[(owner, _real_ref(receipt_ref, field="receipt_ref"))]
                if self._heads.get((owner, receipt.model_id, receipt.version)) != receipt:
                    raise ModelGovernanceClosureError("model governance closure receipt is superseded")
                current = self._resolve_snapshot(
                    owner=owner,
                    model=receipt.model_id,
                    version_number=receipt.version,
                )
        except Exception as exc:  # noqa: BLE001 - current resolution is fail closed.
            return ModelGovernanceClosureDecision(
                False,
                (
                    ModelGovernanceClosureViolation(
                        "model_governance_closure_current_resolution_failed",
                        f"current model governance closure cannot be resolved: {type(exc).__name__}",
                        "receipt_ref",
                        _text(receipt_ref),
                    ),
                ),
            )
        violations = list(validate_model_governance_closure_receipt_shape(receipt).violations)
        if current != receipt.snapshot:
            violations.append(
                ModelGovernanceClosureViolation(
                    "model_governance_closure_current_state_drifted",
                    "training, artifact, governance, promotion, reviewer, or monitoring state changed",
                    "snapshot",
                    receipt.receipt_ref,
                )
            )
        return ModelGovernanceClosureDecision(not violations, tuple(violations))


def model_governance_closure_semantic_material(
    receipt: ModelGovernanceClosureReceipt,
) -> ModelGovernanceClosureSemanticMaterial:
    producers = tuple(
        sorted(
            {
                *(
                    f"model_governance_producer:{item.component_kind}:{item.component_ref}:{item.state_hash}"
                    for item in receipt.snapshot.components
                ),
                receipt.snapshot.source_qro_ref,
                receipt.snapshot.source_graph_ref,
                receipt.snapshot.source_compiler_ir_ref,
                receipt.snapshot.source_compiler_pass_ref,
            }
        )
    )
    stores = tuple(
        sorted(
            {
                receipt.receipt_ref,
                *(
                    f"model_governance_state:{item.component_kind}:{item.component_ref}:{item.state_hash}"
                    for item in receipt.snapshot.components
                ),
                receipt.snapshot.source_entrypoint_coverage_ref,
            }
        )
    )
    consumers = (
        MODEL_GOVERNANCE_SOURCE_ENTRYPOINT_REF,
        MODEL_GOVERNANCE_CLOSURE_ENTRYPOINT_REF,
        f"model_registry_stage:{receipt.snapshot.model_asset_ref}:v{receipt.version}:{receipt.snapshot.stage}",
        f"model_monitoring_consumer:{receipt.snapshot.monitoring_profile_ref}",
    )
    gates = tuple(
        sorted(
            {
                receipt.receipt_ref,
                receipt.snapshot.passport_ref,
                receipt.snapshot.validation_dossier_ref,
                receipt.snapshot.promotion_gate_ref,
                receipt.snapshot.reviewer_grant_ref,
            }
        )
    )
    tests = tuple(
        sorted(
            {
                *(
                    f"model_governance_current_check:{item.component_kind}:{item.component_ref}:{item.state_hash}"
                    for item in receipt.snapshot.components
                ),
                *(
                    f"model_governance_policy_probe:{probe.probe_name}:{','.join(probe.violation_codes)}"
                    for probe in receipt.snapshot.policy_probes
                ),
            }
        )
    )
    return ModelGovernanceClosureSemanticMaterial(
        subject_ref=(
            f"goal_section:§15:model_governance:{receipt.snapshot.model_asset_ref}:"
            f"v{receipt.version}:{receipt.receipt_ref}"
        ),
        producer_refs=producers,
        store_refs=stores,
        consumer_refs=consumers,
        gate_verdict_refs=gates,
        test_refs=tests,
    )


class ModelGovernanceClosureSectionAdapter:
    """Resolve §15 from one current receipt and its training source lineage."""

    def __init__(self, entrypoint_registry: Any, closure_registry: PersistentModelGovernanceClosureRegistry) -> None:
        self._entrypoints = entrypoint_registry
        self._closure = closure_registry

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, message: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_model_governance_closure_invalid",
                    message,
                    field,
                    ref,
                )
            )

        owner = _text(owner)
        if record.section != "§15":
            reject("section", record.section, "model governance closure adapter only supports §15")
            return GoalSemanticDecision(False, tuple(violations))
        if record.recorded_by != owner:
            reject("recorded_by", record.recorded_by, "§15 semantic proof owner mismatch")
        if not record.claims_section_complete or record.unverified_residuals:
            reject("claims_section_complete", record.proof_ref, "§15 requires a complete claim with no residuals")
        receipt_refs = tuple(
            ref
            for ref in record.gate_verdict_refs
            if ref.startswith("model_governance_closure_receipt:")
        )
        if len(receipt_refs) != 1:
            reject("gate_verdict_refs", ",".join(receipt_refs), "§15 requires exactly one durable closure receipt")
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._closure.receipt(receipt_ref, owner_user_id=owner)
            current = self._closure.validate_current(receipt_ref, owner_user_id=owner)
        except Exception as exc:  # noqa: BLE001
            reject("gate_verdict_refs", receipt_ref, f"§15 closure receipt cannot be resolved: {type(exc).__name__}")
            return GoalSemanticDecision(False, tuple(violations))
        if not current.accepted:
            reject("gate_verdict_refs", receipt_ref, "§15 closure receipt is no longer current")
        if record.entrypoint_coverage_refs != (
            receipt.snapshot.source_entrypoint_coverage_ref,
        ):
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "§15 requires the exact current training source lineage",
            )
            return GoalSemanticDecision(False, tuple(violations))
        coverage_ref = record.entrypoint_coverage_refs[0]
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoints,
                coverage_ref,
                owner=owner,
            )
            backing = self._entrypoints.validate_real_backing(coverage)
        except Exception as exc:  # noqa: BLE001
            reject("entrypoint_coverage_refs", coverage_ref, f"§15 training source lineage cannot be resolved: {type(exc).__name__}")
            return GoalSemanticDecision(False, tuple(violations))
        source = getattr(getattr(coverage, "entry_source", ""), "value", getattr(coverage, "entry_source", ""))
        sections = tuple(getattr(item, "value", item) for item in (getattr(coverage, "goal_sections", ()) or ()))
        if (
            _text(source) != "api"
            or _text(getattr(coverage, "entrypoint_ref", "")) != MODEL_GOVERNANCE_SOURCE_ENTRYPOINT_REF
            or "§15" not in sections
            or _text(getattr(coverage, "recorded_by", "")) != owner
            or not bool(getattr(backing, "accepted", False))
            or bool(getattr(coverage, "silent_mock_fallback_used", False))
            or bool(getattr(coverage, "raw_payload_persisted", False))
        ):
            reject("entrypoint_coverage_refs", coverage_ref, "§15 training source lineage is not exact and current")
        for field, actual, expected_refs in (
            ("qro_refs", getattr(coverage, "qro_refs", ()), (receipt.snapshot.source_qro_ref,)),
            (
                "research_graph_command_refs",
                getattr(coverage, "research_graph_command_refs", ()),
                (receipt.snapshot.source_graph_ref,),
            ),
            (
                "compiler_ir_refs",
                getattr(coverage, "compiler_ir_refs", ()),
                (receipt.snapshot.source_compiler_ir_ref,),
            ),
            (
                "compiler_pass_refs",
                getattr(coverage, "compiler_pass_refs", ()),
                (receipt.snapshot.source_compiler_pass_ref,),
            ),
        ):
            if tuple(actual or ()) != expected_refs:
                reject(field, coverage_ref, f"§15 source {field} does not match the closure snapshot")
        validation_refs = tuple(_text(item) for item in (getattr(coverage, "validation_refs", ()) or ()))
        if len(validation_refs) != len(set(validation_refs)):
            reject("test_refs", coverage_ref, "§15 validation refs must be unique")
        if not any(item.startswith("goal_validation_receipt:") for item in validation_refs):
            reject("test_refs", coverage_ref, "§15 lineage requires a durable GOAL validation receipt")
        expected = model_governance_closure_semantic_material(receipt)
        for field in (
            "subject_ref",
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            if getattr(record, field) != getattr(expected, field):
                reject(field, record.proof_ref, f"§15 {field} does not match current closure material")
        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "MODEL_GOVERNANCE_CLOSURE_ENTRYPOINT_REF",
    "MODEL_GOVERNANCE_CLOSURE_RECEIPT_VERSION",
    "MODEL_GOVERNANCE_CLOSURE_SCHEMA_VERSION",
    "MODEL_GOVERNANCE_SOURCE_ENTRYPOINT_REF",
    "ModelGovernanceClosureCommitUncertain",
    "ModelGovernanceClosureComponentState",
    "ModelGovernanceClosureDecision",
    "ModelGovernanceClosureError",
    "ModelGovernanceClosureReceipt",
    "ModelGovernanceClosureSectionAdapter",
    "ModelGovernanceClosureSemanticMaterial",
    "ModelGovernanceClosureSnapshot",
    "ModelGovernanceClosureViolation",
    "ModelGovernancePolicyProbeState",
    "PersistentModelGovernanceClosureRegistry",
    "model_governance_closure_receipt_from_dict",
    "model_governance_closure_receipt_identity",
    "model_governance_closure_semantic_material",
    "model_governance_closure_snapshot_from_dict",
    "model_training_code_hash",
    "validate_model_governance_closure_receipt_shape",
]
