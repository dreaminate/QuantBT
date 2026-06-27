"""GOAL §3 lifecycle and governed asset-library contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value or "")


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


class AssetCategory(str, Enum):
    EXAMPLE = "example"
    TEMPLATE = "template"
    DEMO = "demo"
    TUTORIAL = "tutorial"
    USER_ASSET = "user_asset"
    PRODUCTION_ASSET = "production_asset"


class LifecycleState(str, Enum):
    IDEA = "idea"
    DRAFT = "draft"
    SPECIFIED = "specified"
    LINKED = "linked"
    BACKTEST_CANDIDATE = "backtest_candidate"
    VALIDATION_DOSSIER = "validation_dossier"
    PAPER_CANDIDATE = "paper_candidate"
    APPROVED_RUNTIME = "approved_runtime"
    MONITORED_RUNTIME = "monitored_runtime"
    SUSPENDED = "suspended"
    DEMOTED = "demoted"
    RETIRED = "retired"
    ARCHIVED = "archived"


STRONG_LABELS = {"proof_backed", "evidence_sufficient", "production_ready"}


@dataclass(frozen=True)
class LifecycleViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class LifecycleDecision:
    accepted: bool
    violations: tuple[LifecycleViolation, ...]


@dataclass(frozen=True)
class GovernedAssetRecord:
    asset_ref: str
    asset_type: str
    category: AssetCategory | str | None
    lifecycle_state: LifecycleState | str | None
    evidence_refs: tuple[str, ...]
    validation_plan_ref: str | None
    promotion_history: tuple[str, ...]
    source_category: AssetCategory | str | None = None
    retire_reason: str | None = None
    consistency_check_ref: str | None = None
    methodology_choice_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    display_label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        object.__setattr__(self, "promotion_history", _tuple(self.promotion_history))


@dataclass(frozen=True)
class IngestionSkillUpdateRecord:
    update_ref: str
    skill_ref: str
    skill_version: str
    dataset_version_ref: str | None
    checksum: str | None
    lineage_ref: str | None
    quality_verdict_ref: str | None
    source_ref: str | None = None
    secret_ref: str | None = None
    known_at_ref: str | None = None
    effective_at_ref: str | None = None
    freshness_status: str | None = None
    schema_drift_status: str = "none"
    row_count: int | None = None
    recorded_by: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))


@dataclass(frozen=True)
class RetiredAssetUseRequest:
    request_ref: str
    asset_ref: str
    new_run_ref: str
    default_reference: bool
    override_ref: str | None = None


@dataclass(frozen=True)
class LifecycleTransitionRequest:
    request_ref: str
    asset_ref: str
    from_state: LifecycleState | str
    to_state: LifecycleState | str
    promotion_record_ref: str | None
    approval_ref: str | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))


def validate_governed_asset(asset: GovernedAssetRecord) -> LifecycleDecision:
    violations: list[LifecycleViolation] = []
    if asset.category is None:
        violations.append(
            LifecycleViolation(
                "asset_missing_category",
                "governed assets require category",
                field="category",
                ref=asset.asset_ref,
            )
        )
    if asset.lifecycle_state is None:
        violations.append(
            LifecycleViolation(
                "asset_missing_lifecycle_state",
                "governed assets require lifecycle_state",
                field="lifecycle_state",
                ref=asset.asset_ref,
            )
        )
    if not asset.evidence_refs:
        violations.append(
            LifecycleViolation(
                "asset_missing_evidence_refs",
                "governed assets require evidence refs",
                field="evidence_refs",
                ref=asset.asset_ref,
            )
        )
    if _value(asset.category) == AssetCategory.PRODUCTION_ASSET.value:
        if _value(asset.source_category) in {
            AssetCategory.DEMO.value,
            AssetCategory.TEMPLATE.value,
            AssetCategory.EXAMPLE.value,
            AssetCategory.TUTORIAL.value,
        } and not asset.promotion_history:
            violations.append(
                LifecycleViolation(
                    "template_or_demo_promoted_without_record",
                    "template/demo/example assets require promotion history before production use",
                    field="promotion_history",
                    ref=asset.asset_ref,
                )
            )
    if _value(asset.lifecycle_state) == LifecycleState.RETIRED.value and not _present(asset.retire_reason):
        violations.append(
            LifecycleViolation(
                "retired_asset_missing_retire_reason",
                "retired assets require retire_reason",
                field="retire_reason",
                ref=asset.asset_ref,
            )
        )
    if asset.display_label in STRONG_LABELS and not _present(asset.consistency_check_ref):
        violations.append(
            LifecycleViolation(
                "proof_backed_asset_missing_consistency_check",
                "proof-backed/evidence-sufficient assets require ConsistencyCheck",
                field="consistency_check_ref",
                ref=asset.asset_ref,
            )
        )
    if asset.methodology_choice_ref and not _present(asset.responsibility_boundary_ref):
        violations.append(
            LifecycleViolation(
                "methodology_choice_missing_responsibility_boundary",
                "user-waived/custom methodology requires responsibility boundary",
                field="responsibility_boundary_ref",
                ref=asset.asset_ref,
            )
        )
    return LifecycleDecision(accepted=not violations, violations=tuple(violations))


def validate_ingestion_skill_update(update: IngestionSkillUpdateRecord) -> LifecycleDecision:
    violations: list[LifecycleViolation] = []
    for field_name in (
        "update_ref",
        "skill_ref",
        "skill_version",
        "source_ref",
        "secret_ref",
        "dataset_version_ref",
        "checksum",
        "lineage_ref",
        "quality_verdict_ref",
        "known_at_ref",
        "effective_at_ref",
    ):
        if not _present(getattr(update, field_name)):
            violations.append(
                LifecycleViolation(
                    "ingestion_update_missing_dataset_version_lineage",
                    "IngestionSkill data updates require source, SecretRef, DatasetVersion, checksum, lineage, quality verdict, known_at, and effective_at",
                    field=field_name,
                    ref=update.update_ref,
                )
            )
    return LifecycleDecision(accepted=not violations, violations=tuple(violations))


def validate_retired_asset_use(request: RetiredAssetUseRequest) -> LifecycleDecision:
    violations: list[LifecycleViolation] = []
    if request.default_reference and not _present(request.override_ref):
        violations.append(
            LifecycleViolation(
                "retired_asset_default_referenced_by_new_run",
                "retired assets cannot be default references for new runs",
                field="default_reference",
                ref=request.request_ref,
            )
        )
    return LifecycleDecision(accepted=not violations, violations=tuple(violations))


def validate_lifecycle_transition(request: LifecycleTransitionRequest) -> LifecycleDecision:
    violations: list[LifecycleViolation] = []
    if _value(request.to_state) in {
        LifecycleState.APPROVED_RUNTIME.value,
        LifecycleState.MONITORED_RUNTIME.value,
    }:
        for field_name in ("promotion_record_ref", "approval_ref"):
            if not _present(getattr(request, field_name)):
                violations.append(
                    LifecycleViolation(
                        "runtime_transition_missing_promotion_or_approval",
                        "runtime lifecycle transitions require promotion and approval records",
                        field=field_name,
                        ref=request.request_ref,
                    )
                )
        if not request.evidence_refs:
            violations.append(
                LifecycleViolation(
                    "runtime_transition_missing_evidence",
                    "runtime lifecycle transitions require evidence refs",
                    field="evidence_refs",
                    ref=request.request_ref,
                )
            )
    return LifecycleDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: LifecycleDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "asset lifecycle record rejected"


class PersistentAssetLifecycleRegistry:
    """Append-only lifecycle records that need replay outside pure validators."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ingestion_updates: dict[str, IngestionSkillUpdateRecord] = {}
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
                except Exception as exc:  # noqa: BLE001 - bad lifecycle history must block startup.
                    raise ValueError(f"invalid persisted asset lifecycle row at {self._path}:{line_no}") from exc

    def _append_event(self, event_type: str, field_name: str, record: Any) -> None:
        row = {
            "schema_version": 1,
            "event_type": event_type,
            field_name: _json_value(record),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported asset lifecycle schema_version")
        event_type = str(row.get("event_type") or "")
        if event_type != "ingestion_skill_update_recorded":
            raise ValueError(f"unknown asset lifecycle event_type={event_type!r}")
        raw = row.get("ingestion_skill_update")
        if not isinstance(raw, dict):
            raise ValueError("asset lifecycle event missing ingestion_skill_update")
        self._record_ingestion_skill_update(IngestionSkillUpdateRecord(**raw), persist=persist)

    def record_ingestion_skill_update(self, record: IngestionSkillUpdateRecord) -> IngestionSkillUpdateRecord:
        return self._record_ingestion_skill_update(record, persist=True)

    def _record_ingestion_skill_update(
        self,
        record: IngestionSkillUpdateRecord,
        *,
        persist: bool,
    ) -> IngestionSkillUpdateRecord:
        decision = validate_ingestion_skill_update(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._ingestion_updates[record.update_ref] = record
        if persist:
            self._append_event("ingestion_skill_update_recorded", "ingestion_skill_update", record)
        return record

    def ingestion_skill_update(self, update_ref: str) -> IngestionSkillUpdateRecord:
        return self._ingestion_updates[update_ref]

    def ingestion_skill_updates(self) -> list[IngestionSkillUpdateRecord]:
        return list(self._ingestion_updates.values())


def validate_asset_lifecycle(
    assets: tuple[GovernedAssetRecord, ...],
    *,
    ingestion_updates: tuple[IngestionSkillUpdateRecord, ...] = (),
    retired_use_requests: tuple[RetiredAssetUseRequest, ...] = (),
    transitions: tuple[LifecycleTransitionRequest, ...] = (),
) -> LifecycleDecision:
    violations: list[LifecycleViolation] = []
    for asset in assets:
        violations.extend(validate_governed_asset(asset).violations)
    for update in ingestion_updates:
        violations.extend(validate_ingestion_skill_update(update).violations)
    for request in retired_use_requests:
        violations.extend(validate_retired_asset_use(request).violations)
    for transition in transitions:
        violations.extend(validate_lifecycle_transition(transition).violations)
    return LifecycleDecision(accepted=not violations, violations=tuple(violations))


__all__ = [
    "AssetCategory",
    "GovernedAssetRecord",
    "IngestionSkillUpdateRecord",
    "LifecycleDecision",
    "LifecycleState",
    "LifecycleTransitionRequest",
    "LifecycleViolation",
    "PersistentAssetLifecycleRegistry",
    "RetiredAssetUseRequest",
    "validate_asset_lifecycle",
    "validate_governed_asset",
    "validate_ingestion_skill_update",
    "validate_lifecycle_transition",
    "validate_retired_asset_use",
]
