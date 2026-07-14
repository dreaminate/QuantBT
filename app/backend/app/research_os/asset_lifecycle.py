"""GOAL §3 lifecycle and governed asset-library contracts."""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd


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


def _stable_owner(value: object) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise ValueError("asset lifecycle owner_user_id is required")
    return owner


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
    mock_label_ref: str | None = None
    asset_category_ref: str | None = None

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
    category = _value(asset.category)
    if category in {
        AssetCategory.DEMO.value,
        AssetCategory.TEMPLATE.value,
        AssetCategory.EXAMPLE.value,
        AssetCategory.TUTORIAL.value,
    }:
        if not str(asset.mock_label_ref or "").startswith("mock_label:"):
            violations.append(
                LifecycleViolation(
                    "example_asset_missing_mock_label_ref",
                    "demo/template/example/tutorial assets require a typed mock_label_ref",
                    field="mock_label_ref",
                    ref=asset.asset_ref,
                )
            )
        if not str(asset.asset_category_ref or "").startswith("asset_category:"):
            violations.append(
                LifecycleViolation(
                    "example_asset_missing_asset_category_ref",
                    "demo/template/example/tutorial assets require a typed asset_category_ref",
                    field="asset_category_ref",
                    ref=asset.asset_ref,
                )
            )
        if not _present(asset.display_label):
            violations.append(
                LifecycleViolation(
                    "example_asset_missing_visible_label",
                    "demo/template/example/tutorial assets require a visible mock/category label",
                    field="display_label",
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
    if category == AssetCategory.PRODUCTION_ASSET.value:
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
    """Owner-enveloped append-only lifecycle records.

    Schema-v1 rows predate stable ownership.  They are counted as quarantined
    history and are never exposed through strict owner-scoped getters.  The
    prefix marker detects accidental loss, truncation, or replacement across
    restarts; it assumes the runtime filesystem itself is trusted against an
    attacker who can replace both the journal and its marker together.
    """

    SCHEMA_VERSION = 2

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._history_marker_path = self._path.with_suffix(
            self._path.suffix + ".history"
        )
        self._lock = threading.RLock()
        self._ingestion_updates: dict[tuple[str, str], IngestionSkillUpdateRecord] = {}
        self._governed_assets: dict[tuple[str, str], GovernedAssetRecord] = {}
        self._legacy_quarantined_count = 0
        self._known_rows: tuple[str, ...] = ()
        self._ever_had_history = False
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        self._refresh_from_disk()
        with self._lock:
            return self._legacy_quarantined_count

    def _load_existing(self) -> None:
        self._refresh_from_disk(allow_initial_missing=True)

    @staticmethod
    def _encoded_row(row: dict[str, Any]) -> str:
        return json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _rows_digest(rows: tuple[str, ...]) -> str:
        payload = "".join(f"{row}\n" for row in rows).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _history_marker(self) -> tuple[int, str] | None:
        if self._history_marker_path.is_symlink():
            raise ValueError("asset lifecycle history marker cannot be a symlink")
        if not self._history_marker_path.exists():
            return None
        try:
            raw = json.loads(self._history_marker_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != 1:
                raise ValueError("invalid history marker schema")
            row_count = int(raw.get("row_count"))
            prefix_sha256 = str(raw.get("prefix_sha256") or "")
            if row_count < 0 or len(prefix_sha256) != 64:
                raise ValueError("invalid history marker content")
            int(prefix_sha256, 16)
            return row_count, prefix_sha256
        except Exception as exc:  # noqa: BLE001 - integrity metadata fails closed.
            raise ValueError("invalid asset lifecycle history marker") from exc

    def _write_history_marker(self, rows: tuple[str, ...]) -> None:
        payload = self._encoded_row(
            {
                "schema_version": 1,
                "row_count": len(rows),
                "prefix_sha256": self._rows_digest(rows),
            }
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            dir=self._history_marker_path.parent,
            prefix=f".{self._history_marker_path.name}.",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            if os.write(fd, payload) != len(payload):
                raise OSError("short asset lifecycle history marker write")
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, self._history_marker_path)
            directory_fd = os.open(self._history_marker_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validated_record(
        row: dict[str, Any],
    ) -> tuple[str, str, IngestionSkillUpdateRecord | GovernedAssetRecord]:
        if row.get("schema_version") != PersistentAssetLifecycleRegistry.SCHEMA_VERSION:
            raise ValueError("unsupported asset lifecycle schema_version")
        owner = _stable_owner(row.get("owner_user_id"))
        event_type = str(row.get("event_type") or "")
        if event_type == "ingestion_skill_update_recorded":
            raw = row.get("ingestion_skill_update")
            if not isinstance(raw, dict):
                raise ValueError("asset lifecycle event missing ingestion_skill_update")
            record = IngestionSkillUpdateRecord(**raw)
            if str(record.recorded_by or "").strip() != owner:
                raise ValueError("ingestion skill update recorded_by must equal owner_user_id")
            decision = validate_ingestion_skill_update(record)
        elif event_type == "governed_asset_recorded":
            raw = row.get("governed_asset")
            if not isinstance(raw, dict):
                raise ValueError("asset lifecycle event missing governed_asset")
            record = GovernedAssetRecord(**raw)
            decision = validate_governed_asset(record)
        else:
            raise ValueError(f"unknown asset lifecycle event_type={event_type!r}")
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        return owner, event_type, record

    def _read_disk_state(
        self,
        *,
        allow_missing: bool,
    ) -> tuple[
        dict[tuple[str, str], IngestionSkillUpdateRecord],
        dict[tuple[str, str], GovernedAssetRecord],
        int,
        tuple[str, ...],
    ]:
        marker = self._history_marker()
        if not self._path.exists():
            if (
                marker == (0, self._rows_digest(()))
                and not self._ever_had_history
            ):
                return {}, {}, 0, ()
            raise ValueError("persisted asset lifecycle history is missing")
        updates: dict[tuple[str, str], IngestionSkillUpdateRecord] = {}
        assets: dict[tuple[str, str], GovernedAssetRecord] = {}
        legacy_count = 0
        encoded_rows: list[str] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    raise ValueError(
                        f"invalid persisted asset lifecycle row at {self._path}:{line_no}"
                    )
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("asset lifecycle row must be an object")
                    encoded_rows.append(self._encoded_row(row))
                    if row.get("schema_version") == 1:
                        legacy_count += 1
                        continue
                    owner, event_type, record = self._validated_record(row)
                    if event_type == "ingestion_skill_update_recorded":
                        assert isinstance(record, IngestionSkillUpdateRecord)
                        target = updates
                        identity = record.update_ref
                    else:
                        assert isinstance(record, GovernedAssetRecord)
                        target = assets
                        identity = record.asset_ref
                    key = (owner, identity)
                    current = target.get(key)
                    if current is not None:
                        raise ValueError("duplicate persisted asset lifecycle identity")
                    target[key] = record
                except Exception as exc:  # noqa: BLE001 - corrupt history fails closed.
                    if isinstance(exc, ValueError) and str(exc).startswith(
                        "invalid persisted asset lifecycle row at"
                    ):
                        raise
                    raise ValueError(
                        f"invalid persisted asset lifecycle row at {self._path}:{line_no}"
                    ) from exc
        rows_tuple = tuple(encoded_rows)
        if marker is None:
            # Schema-v1 history predates both stable owner envelopes and this
            # marker. It is safe to anchor only because every such row remains
            # quarantined and cannot resolve as a current lifecycle record.
            if legacy_count != len(rows_tuple):
                raise ValueError("persisted asset lifecycle history marker is missing")
        else:
            marker_count, marker_digest = marker
            if len(rows_tuple) < marker_count:
                raise ValueError("persisted asset lifecycle history was truncated")
            if self._rows_digest(rows_tuple[:marker_count]) != marker_digest:
                raise ValueError("persisted asset lifecycle history changed before marker")
        if self._known_rows and rows_tuple[: len(self._known_rows)] != self._known_rows:
            raise ValueError("persisted asset lifecycle append-only history changed")
        return updates, assets, legacy_count, rows_tuple

    def _refresh_from_disk(self, *, allow_initial_missing: bool = False) -> None:
        with self._lock:
            lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            held = None
            try:
                held = acquire_exclusive_fd(lock_fd, timeout_seconds=10.0)
                if not self._path.exists() and self._history_marker() is None:
                    self._write_history_marker(())
                updates, assets, legacy_count, rows = self._read_disk_state(
                    allow_missing=allow_initial_missing,
                )
                self._ingestion_updates = updates
                self._governed_assets = assets
                self._legacy_quarantined_count = legacy_count
                self._known_rows = rows
                self._ever_had_history = self._ever_had_history or bool(rows)
                marker = self._history_marker()
                if (
                    marker is None
                    or marker[0] != len(rows)
                    or marker[1] != self._rows_digest(rows)
                ):
                    self._write_history_marker(rows)
            finally:
                if held is not None:
                    held.release()
                os.close(lock_fd)

    def _append_event(self, row: dict[str, Any]) -> bool:
        encoded = self._encoded_row(row)
        owner = _stable_owner(row.get("owner_user_id"))
        event_type = str(row.get("event_type") or "")
        payload_key, identity_field = {
            "ingestion_skill_update_recorded": ("ingestion_skill_update", "update_ref"),
            "governed_asset_recorded": ("governed_asset", "asset_ref"),
        }.get(event_type, ("", ""))
        raw_record = row.get(payload_key)
        if not isinstance(raw_record, dict):
            raise ValueError("asset lifecycle event payload is missing")
        identity = str(raw_record.get(identity_field) or "")
        lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        held = None
        try:
            held = acquire_exclusive_fd(lock_fd, timeout_seconds=10.0)
            updates, assets, _legacy_count, _rows = self._read_disk_state(
                allow_missing=not self._known_rows,
            )
            records = (
                updates
                if event_type == "ingestion_skill_update_recorded"
                else assets
            )
            current = records.get((owner, identity))
            if current is not None:
                existing_row = (
                    self._ingestion_event_row(current, owner_user_id=owner)
                    if isinstance(current, IngestionSkillUpdateRecord)
                    else self._governed_asset_event_row(current, owner_user_id=owner)
                )
                if self._encoded_row(existing_row) == encoded:
                    return False
                raise ValueError("asset lifecycle owner/record identity collision")
            if event_type == "governed_asset_recorded":
                incoming_mock_ref = str(raw_record.get("mock_label_ref") or "")
                incoming_category_ref = str(raw_record.get("asset_category_ref") or "")
                for (record_owner, _), existing in assets.items():
                    if record_owner != owner:
                        continue
                    if incoming_mock_ref and str(existing.mock_label_ref or "") == incoming_mock_ref:
                        raise ValueError("asset lifecycle owner/mock_label_ref identity collision")
                    if incoming_category_ref and str(existing.asset_category_ref or "") == incoming_category_ref:
                        raise ValueError("asset lifecycle owner/asset_category_ref identity collision")
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(encoded + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return True
        finally:
            if held is not None:
                held.release()
            os.close(lock_fd)

    def _ingestion_event_row(
        self,
        record: IngestionSkillUpdateRecord,
        *,
        owner_user_id: str,
    ) -> dict[str, Any]:
        row = {
            "schema_version": self.SCHEMA_VERSION,
            "event_type": "ingestion_skill_update_recorded",
            "owner_user_id": owner_user_id,
            "ingestion_skill_update": _json_value(record),
        }
        return row

    def _governed_asset_event_row(
        self,
        record: GovernedAssetRecord,
        *,
        owner_user_id: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "event_type": "governed_asset_recorded",
            "owner_user_id": owner_user_id,
            "governed_asset": _json_value(record),
        }

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        owner, event_type, record = self._validated_record(row)
        if event_type == "ingestion_skill_update_recorded":
            assert isinstance(record, IngestionSkillUpdateRecord)
            self._record_ingestion_skill_update(
                record,
                owner_user_id=owner,
                persist=persist,
            )
        else:
            assert isinstance(record, GovernedAssetRecord)
            self._record_governed_asset(
                record,
                owner_user_id=owner,
                persist=persist,
            )

    def record_ingestion_skill_update(
        self,
        record: IngestionSkillUpdateRecord,
        *,
        owner_user_id: str,
    ) -> IngestionSkillUpdateRecord:
        return self._record_ingestion_skill_update(
            record,
            owner_user_id=_stable_owner(owner_user_id),
            persist=True,
        )

    def _record_ingestion_skill_update(
        self,
        record: IngestionSkillUpdateRecord,
        *,
        owner_user_id: str,
        persist: bool,
    ) -> IngestionSkillUpdateRecord:
        owner = _stable_owner(owner_user_id)
        if str(record.recorded_by or "").strip() != owner:
            raise ValueError("ingestion skill update recorded_by must equal owner_user_id")
        decision = validate_ingestion_skill_update(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = (owner, record.update_ref)
        if persist:
            self._refresh_from_disk(allow_initial_missing=True)
        with self._lock:
            current = self._ingestion_updates.get(key)
            if current is not None:
                if current != record:
                    raise ValueError(
                        "asset lifecycle owner/update_ref identity collision"
                    )
                return current
            if not persist:
                self._ingestion_updates[key] = record
                return record
        self._append_event(self._ingestion_event_row(record, owner_user_id=owner))
        self._refresh_from_disk()
        with self._lock:
            return self._ingestion_updates[key]

    def ingestion_skill_update(
        self,
        update_ref: str,
        *,
        owner_user_id: str,
    ) -> IngestionSkillUpdateRecord:
        owner = _stable_owner(owner_user_id)
        self._refresh_from_disk()
        with self._lock:
            return self._ingestion_updates[(owner, update_ref)]

    def ingestion_skill_updates(
        self,
        *,
        owner_user_id: str,
    ) -> list[IngestionSkillUpdateRecord]:
        owner = _stable_owner(owner_user_id)
        self._refresh_from_disk()
        with self._lock:
            return [
                record
                for (record_owner, _), record in self._ingestion_updates.items()
                if record_owner == owner
            ]

    def record_governed_asset(
        self,
        record: GovernedAssetRecord,
        *,
        owner_user_id: str,
    ) -> GovernedAssetRecord:
        return self._record_governed_asset(
            record,
            owner_user_id=_stable_owner(owner_user_id),
            persist=True,
        )

    def _record_governed_asset(
        self,
        record: GovernedAssetRecord,
        *,
        owner_user_id: str,
        persist: bool,
    ) -> GovernedAssetRecord:
        owner = _stable_owner(owner_user_id)
        decision = validate_governed_asset(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = (owner, str(record.asset_ref or "").strip())
        if not key[1]:
            raise ValueError("governed asset asset_ref is required")
        if persist:
            self._refresh_from_disk(allow_initial_missing=True)
        with self._lock:
            current = self._governed_assets.get(key)
            if current is not None:
                if current != record:
                    raise ValueError("asset lifecycle owner/asset_ref identity collision")
                return current
            for (record_owner, existing_ref), existing in self._governed_assets.items():
                if record_owner != owner or existing_ref == key[1]:
                    continue
                if record.mock_label_ref and existing.mock_label_ref == record.mock_label_ref:
                    raise ValueError("asset lifecycle owner/mock_label_ref identity collision")
                if record.asset_category_ref and existing.asset_category_ref == record.asset_category_ref:
                    raise ValueError("asset lifecycle owner/asset_category_ref identity collision")
            if not persist:
                self._governed_assets[key] = record
                return record
        self._append_event(self._governed_asset_event_row(record, owner_user_id=owner))
        self._refresh_from_disk()
        with self._lock:
            return self._governed_assets[key]

    def governed_asset(
        self,
        asset_ref: str,
        *,
        owner_user_id: str,
    ) -> GovernedAssetRecord:
        owner = _stable_owner(owner_user_id)
        ref = str(asset_ref or "").strip()
        if not ref:
            raise KeyError("governed asset ref is required")
        self._refresh_from_disk()
        with self._lock:
            return self._governed_assets[(owner, ref)]

    def governed_assets(
        self,
        *,
        owner_user_id: str,
    ) -> list[GovernedAssetRecord]:
        owner = _stable_owner(owner_user_id)
        self._refresh_from_disk()
        with self._lock:
            return sorted(
                (
                    record
                    for (record_owner, _), record in self._governed_assets.items()
                    if record_owner == owner
                ),
                key=lambda record: record.asset_ref,
            )

    def governed_asset_by_mock_label_ref(
        self,
        mock_label_ref: str,
        *,
        owner_user_id: str,
    ) -> GovernedAssetRecord:
        ref = str(mock_label_ref or "").strip()
        matches = [
            record
            for record in self.governed_assets(owner_user_id=owner_user_id)
            if str(record.mock_label_ref or "") == ref
        ]
        if len(matches) != 1:
            raise KeyError(f"unknown governed asset mock label ref: {ref}")
        return matches[0]

    def governed_asset_by_category_ref(
        self,
        asset_category_ref: str,
        *,
        owner_user_id: str,
    ) -> GovernedAssetRecord:
        ref = str(asset_category_ref or "").strip()
        matches = [
            record
            for record in self.governed_assets(owner_user_id=owner_user_id)
            if str(record.asset_category_ref or "") == ref
        ]
        if len(matches) != 1:
            raise KeyError(f"unknown governed asset category ref: {ref}")
        return matches[0]


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
