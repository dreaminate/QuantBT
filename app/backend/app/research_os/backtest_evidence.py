"""Durable owner-scoped attribution and monitor evidence for one real backtest.

The records in this module are business evidence, not platform-closure aliases.
An attribution can be recorded only when an injected resolver reads the current
run artifact twice and returns the exact hash, row count, and component set.
Monitors are content-addressed, append-only heads over that current attribution.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from ..cross_process_lock import acquire_exclusive_fd


BACKTEST_EVIDENCE_SCHEMA_VERSION = 1
_ATTRIBUTION_EVENT = "backtest_attribution_recorded"
_MONITOR_EVENT = "backtest_monitor_recorded"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        value = (value,)
    return tuple(_text(item) for item in value if _text(item))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _valid_sha256(value: Any) -> bool:
    token = _text(value).lower()
    return (
        token.startswith("sha256:")
        and len(token) == 71
        and all(char in "0123456789abcdef" for char in token[7:])
    )


def _required(value: Any, field: str) -> str:
    token = _text(value)
    if not token or token != value or any(ord(char) < 32 for char in token):
        raise ValueError(f"{field} must be a stable non-empty exact string")
    return token


@dataclass(frozen=True)
class BacktestArtifactState:
    artifact_sha256: str
    row_count: int
    component_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_sha256", _text(self.artifact_sha256))
        object.__setattr__(self, "component_refs", _texts(self.component_refs))


BacktestArtifactResolver = Callable[
    [str, str, str, str],
    BacktestArtifactState,
]


@dataclass(frozen=True)
class BacktestAttributionRecord:
    owner_user_id: str
    recorded_by: str
    backtest_run_ref: str
    source_run_ref: str
    validation_methodology_ref: str
    validation_depth_ref: str
    artifact_path: str
    artifact_sha256: str
    row_count: int
    component_refs: tuple[str, ...]
    cost_model_refs: tuple[str, ...]
    attribution_ref: str = ""

    def __post_init__(self) -> None:
        for field in (
            "owner_user_id",
            "recorded_by",
            "backtest_run_ref",
            "source_run_ref",
            "validation_methodology_ref",
            "validation_depth_ref",
            "artifact_path",
            "artifact_sha256",
        ):
            object.__setattr__(self, field, _text(getattr(self, field)))
        object.__setattr__(self, "component_refs", _texts(self.component_refs))
        object.__setattr__(self, "cost_model_refs", _texts(self.cost_model_refs))
        supplied = _text(self.attribution_ref)
        canonical = self.canonical_attribution_ref
        if supplied and supplied != canonical:
            raise ValueError("backtest attribution identity does not match durable content")
        object.__setattr__(self, "attribution_ref", canonical)

    @property
    def canonical_attribution_ref(self) -> str:
        return "attribution:" + _sha256(
            {
                "owner_user_id": self.owner_user_id,
                "backtest_run_ref": self.backtest_run_ref,
                "source_run_ref": self.source_run_ref,
                "validation_methodology_ref": self.validation_methodology_ref,
                "validation_depth_ref": self.validation_depth_ref,
                "artifact_path": self.artifact_path,
                "artifact_sha256": self.artifact_sha256,
                "row_count": self.row_count,
                "component_refs": self.component_refs,
                "cost_model_refs": self.cost_model_refs,
            }
        ).removeprefix("sha256:")


@dataclass(frozen=True)
class BacktestMonitorRecord:
    owner_user_id: str
    recorded_by: str
    backtest_run_ref: str
    attribution_ref: str
    monitoring_profile_ref: str
    performance_primary_alert_ref: str
    cost_drift_ref: str
    drift_root_cause_ref: str
    mathematical_trigger_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    used_dsr_as_primary_live_alert: bool = False
    monitor_ref: str = ""

    def __post_init__(self) -> None:
        for field in (
            "owner_user_id",
            "recorded_by",
            "backtest_run_ref",
            "attribution_ref",
            "monitoring_profile_ref",
            "performance_primary_alert_ref",
            "cost_drift_ref",
            "drift_root_cause_ref",
        ):
            object.__setattr__(self, field, _text(getattr(self, field)))
        object.__setattr__(
            self,
            "mathematical_trigger_refs",
            _texts(self.mathematical_trigger_refs),
        )
        object.__setattr__(self, "evidence_refs", _texts(self.evidence_refs))
        supplied = _text(self.monitor_ref)
        canonical = self.canonical_monitor_ref
        if supplied and supplied != canonical:
            raise ValueError("backtest monitor identity does not match durable content")
        object.__setattr__(self, "monitor_ref", canonical)

    @property
    def canonical_monitor_ref(self) -> str:
        return "monitor:" + _sha256(
            {
                "owner_user_id": self.owner_user_id,
                "backtest_run_ref": self.backtest_run_ref,
                "attribution_ref": self.attribution_ref,
                "monitoring_profile_ref": self.monitoring_profile_ref,
                "performance_primary_alert_ref": self.performance_primary_alert_ref,
                "cost_drift_ref": self.cost_drift_ref,
                "drift_root_cause_ref": self.drift_root_cause_ref,
                "mathematical_trigger_refs": self.mathematical_trigger_refs,
                "evidence_refs": self.evidence_refs,
                "used_dsr_as_primary_live_alert": self.used_dsr_as_primary_live_alert,
            }
        ).removeprefix("sha256:")


@dataclass(frozen=True)
class BacktestEvidenceViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class BacktestEvidenceDecision:
    accepted: bool
    violations: tuple[BacktestEvidenceViolation, ...]


class BacktestEvidenceError(ValueError):
    """Backtest evidence is missing, corrupt, stale, or recombined."""


class BacktestEvidenceCommitUncertain(BacktestEvidenceError):
    """The evidence file changed but directory durability was not confirmed."""


def validate_backtest_attribution_record(
    record: BacktestAttributionRecord,
) -> BacktestEvidenceDecision:
    violations: list[BacktestEvidenceViolation] = []

    def reject(code: str, field: str, message: str) -> None:
        violations.append(
            BacktestEvidenceViolation(code, message, field, record.attribution_ref)
        )

    for field in (
        "owner_user_id",
        "recorded_by",
        "backtest_run_ref",
        "source_run_ref",
        "validation_methodology_ref",
        "validation_depth_ref",
    ):
        if not _text(getattr(record, field)):
            reject("backtest_attribution_required_field", field, f"{field} is required")
    if not record.source_run_ref.startswith("ide_run:"):
        reject(
            "backtest_attribution_source_run_invalid",
            "source_run_ref",
            "source_run_ref must be the exact persisted IDE run identity",
        )
    if record.artifact_path != "attribution.csv":
        reject(
            "backtest_attribution_path_invalid",
            "artifact_path",
            "the canonical backtest attribution artifact is attribution.csv",
        )
    if not _valid_sha256(record.artifact_sha256):
        reject(
            "backtest_attribution_hash_invalid",
            "artifact_sha256",
            "artifact_sha256 must be a canonical sha256 digest",
        )
    if type(record.row_count) is not int or record.row_count <= 0:
        reject(
            "backtest_attribution_empty",
            "row_count",
            "backtest attribution requires at least one persisted row",
        )
    for field in ("component_refs", "cost_model_refs"):
        values = tuple(getattr(record, field) or ())
        if not values or len(values) != len(set(values)):
            reject(
                "backtest_attribution_refs_invalid",
                field,
                f"{field} must be non-empty and unique",
            )
    if record.attribution_ref != record.canonical_attribution_ref:
        reject(
            "backtest_attribution_identity_mismatch",
            "attribution_ref",
            "attribution_ref must content-bind the current artifact and methodology",
        )
    return BacktestEvidenceDecision(not violations, tuple(violations))


def validate_backtest_monitor_record(
    record: BacktestMonitorRecord,
) -> BacktestEvidenceDecision:
    violations: list[BacktestEvidenceViolation] = []

    def reject(code: str, field: str, message: str) -> None:
        violations.append(BacktestEvidenceViolation(code, message, field, record.monitor_ref))

    for field in (
        "owner_user_id",
        "recorded_by",
        "backtest_run_ref",
        "attribution_ref",
        "monitoring_profile_ref",
        "performance_primary_alert_ref",
        "cost_drift_ref",
        "drift_root_cause_ref",
    ):
        if not _text(getattr(record, field)):
            reject("backtest_monitor_required_field", field, f"{field} is required")
    if not record.attribution_ref.startswith("attribution:"):
        reject(
            "backtest_monitor_attribution_invalid",
            "attribution_ref",
            "monitor must bind a canonical Attribution record",
        )
    for field in ("mathematical_trigger_refs", "evidence_refs"):
        values = tuple(getattr(record, field) or ())
        if not values or len(values) != len(set(values)):
            reject(
                "backtest_monitor_refs_invalid",
                field,
                f"{field} must be non-empty and unique",
            )
    if record.used_dsr_as_primary_live_alert:
        reject(
            "backtest_monitor_dsr_primary_forbidden",
            "used_dsr_as_primary_live_alert",
            "DSR cannot be the primary alert for one live strategy",
        )
    required_evidence_refs = {
        record.attribution_ref,
        record.monitoring_profile_ref,
        record.performance_primary_alert_ref,
        record.cost_drift_ref,
        record.drift_root_cause_ref,
        *record.mathematical_trigger_refs,
    }
    if not required_evidence_refs.issubset(set(record.evidence_refs)):
        reject(
            "backtest_monitor_evidence_incomplete",
            "evidence_refs",
            "monitor evidence must include attribution, profile, performance, cost drift, root cause, and mathematical triggers",
        )
    if record.monitor_ref != record.canonical_monitor_ref:
        reject(
            "backtest_monitor_identity_mismatch",
            "monitor_ref",
            "monitor_ref must content-bind attribution, cost drift, and math triggers",
        )
    return BacktestEvidenceDecision(not violations, tuple(violations))


def backtest_attribution_record_from_dict(value: Any) -> BacktestAttributionRecord:
    if not isinstance(value, dict):
        raise TypeError("backtest attribution must be an object")
    return BacktestAttributionRecord(
        owner_user_id=value.get("owner_user_id", ""),
        recorded_by=value.get("recorded_by", ""),
        backtest_run_ref=value.get("backtest_run_ref", ""),
        source_run_ref=value.get("source_run_ref", ""),
        validation_methodology_ref=value.get("validation_methodology_ref", ""),
        validation_depth_ref=value.get("validation_depth_ref", ""),
        artifact_path=value.get("artifact_path", ""),
        artifact_sha256=value.get("artifact_sha256", ""),
        row_count=value.get("row_count", 0),
        component_refs=tuple(value.get("component_refs") or ()),
        cost_model_refs=tuple(value.get("cost_model_refs") or ()),
        attribution_ref=value.get("attribution_ref", ""),
    )


def backtest_monitor_record_from_dict(value: Any) -> BacktestMonitorRecord:
    if not isinstance(value, dict):
        raise TypeError("backtest monitor must be an object")
    return BacktestMonitorRecord(
        owner_user_id=value.get("owner_user_id", ""),
        recorded_by=value.get("recorded_by", ""),
        backtest_run_ref=value.get("backtest_run_ref", ""),
        attribution_ref=value.get("attribution_ref", ""),
        monitoring_profile_ref=value.get("monitoring_profile_ref", ""),
        performance_primary_alert_ref=value.get("performance_primary_alert_ref", ""),
        cost_drift_ref=value.get("cost_drift_ref", ""),
        drift_root_cause_ref=value.get("drift_root_cause_ref", ""),
        mathematical_trigger_refs=tuple(value.get("mathematical_trigger_refs") or ()),
        evidence_refs=tuple(value.get("evidence_refs") or ()),
        used_dsr_as_primary_live_alert=bool(
            value.get("used_dsr_as_primary_live_alert", False)
        ),
        monitor_ref=value.get("monitor_ref", ""),
    )


class PersistentBacktestEvidenceRegistry:
    """Hash-chained owner ledger for current Attribution and Monitor heads."""

    def __init__(
        self,
        path: str | Path,
        *,
        artifact_resolver: BacktestArtifactResolver | None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._thread_lock = threading.RLock()
        self._artifact_resolver = artifact_resolver
        self._attributions: dict[tuple[str, str], BacktestAttributionRecord] = {}
        self._monitors: dict[tuple[str, str], BacktestMonitorRecord] = {}
        self._attribution_heads: dict[tuple[str, str], BacktestAttributionRecord] = {}
        self._monitor_heads: dict[tuple[str, str], BacktestMonitorRecord] = {}
        self._last_revision = 0
        self._last_record_hash = ""
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _clear(self) -> None:
        self._attributions.clear()
        self._monitors.clear()
        self._attribution_heads.clear()
        self._monitor_heads.clear()
        self._last_revision = 0
        self._last_record_hash = ""

    def _load_existing(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _load_existing_unlocked(self) -> None:
        self._clear()
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row)
                except Exception as exc:  # noqa: BLE001 - corrupt evidence must fail closed.
                    self._clear()
                    raise BacktestEvidenceError(
                        f"invalid persisted backtest evidence row at {self._path}:{line_no}"
                    ) from exc

    def _apply_row(self, row: Any) -> None:
        expected = {
            "schema_version",
            "event_type",
            "ledger_revision",
            "previous_record_hash",
            "owner_user_id",
            "payload",
            "record_hash",
        }
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError("backtest evidence event schema is inexact")
        if row["schema_version"] != BACKTEST_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported backtest evidence schema_version")
        revision = row["ledger_revision"]
        if type(revision) is not int or revision != self._last_revision + 1:
            raise ValueError("backtest evidence ledger revision is not contiguous")
        if row["previous_record_hash"] != self._last_record_hash:
            raise ValueError("backtest evidence hash chain is broken")
        body = {key: value for key, value in row.items() if key != "record_hash"}
        if row["record_hash"] != _sha256(body):
            raise ValueError("backtest evidence event hash mismatch")
        owner = _required(row["owner_user_id"], "owner_user_id")
        event_type = row["event_type"]
        if event_type == _ATTRIBUTION_EVENT:
            record = backtest_attribution_record_from_dict(row["payload"])
            decision = validate_backtest_attribution_record(record)
            ref = record.attribution_ref
            mapping = self._attributions
            heads = self._attribution_heads
        elif event_type == _MONITOR_EVENT:
            record = backtest_monitor_record_from_dict(row["payload"])
            decision = validate_backtest_monitor_record(record)
            ref = record.monitor_ref
            mapping = self._monitors
            heads = self._monitor_heads
        else:
            raise ValueError("unsupported backtest evidence event_type")
        if not decision.accepted:
            raise ValueError(",".join(item.code for item in decision.violations))
        if record.owner_user_id != owner or record.recorded_by != owner:
            raise ValueError("backtest evidence owner envelope mismatch")
        key = (owner, ref)
        existing = mapping.get(key)
        if existing is not None and existing != record:
            raise ValueError("backtest evidence identity collision")
        mapping[key] = record
        heads[(owner, record.backtest_run_ref)] = record
        self._last_revision = revision
        self._last_record_hash = row["record_hash"]

    def _artifact_state(self, record: BacktestAttributionRecord) -> BacktestArtifactState:
        if self._artifact_resolver is None:
            raise BacktestEvidenceError("backtest artifact resolver is unavailable")
        first = self._artifact_resolver(
            record.owner_user_id,
            record.backtest_run_ref,
            record.source_run_ref,
            record.artifact_path,
        )
        second = self._artifact_resolver(
            record.owner_user_id,
            record.backtest_run_ref,
            record.source_run_ref,
            record.artifact_path,
        )
        if not isinstance(first, BacktestArtifactState) or first != second:
            raise BacktestEvidenceError("backtest attribution artifact changed during resolution")
        if not _valid_sha256(first.artifact_sha256) or first.row_count <= 0:
            raise BacktestEvidenceError("backtest attribution artifact state is invalid")
        return first

    @staticmethod
    def _artifact_matches(
        record: BacktestAttributionRecord,
        state: BacktestArtifactState,
    ) -> bool:
        return bool(
            record.artifact_sha256 == state.artifact_sha256
            and record.row_count == state.row_count
            and record.component_refs == state.component_refs
        )

    def _atomic_append_unlocked(self, row: dict[str, Any]) -> None:
        original_exists = self._path.exists()
        original = self._path.read_bytes() if original_exists else b""
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        payload = original + separator + (_canonical_json(row) + "\n").encode("utf-8")
        fd, raw_temp = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        temp = Path(raw_temp)
        replaced = False
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            fd = -1
            os.replace(temp, self._path)
            replaced = True
            parent_fd = os.open(
                self._path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except Exception as exc:
            if replaced:
                raise BacktestEvidenceCommitUncertain(
                    "backtest evidence append replaced the ledger but directory fsync failed"
                ) from exc
            raise
        finally:
            if fd >= 0:
                os.close(fd)
            temp.unlink(missing_ok=True)

    def _record(self, record: Any, *, event_type: str) -> Any:
        owner = _required(record.owner_user_id, "owner_user_id")
        if record.recorded_by != owner:
            raise BacktestEvidenceError("recorded_by must equal the authenticated owner")
        if event_type == _ATTRIBUTION_EVENT:
            decision = validate_backtest_attribution_record(record)
            state = self._artifact_state(record)
            if not self._artifact_matches(record, state):
                raise BacktestEvidenceError("backtest attribution artifact state mismatch")
        else:
            decision = validate_backtest_monitor_record(record)
        if not decision.accepted:
            raise BacktestEvidenceError(",".join(item.code for item in decision.violations))
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            if event_type == _ATTRIBUTION_EVENT:
                state = self._artifact_state(record)
                if not self._artifact_matches(record, state):
                    raise BacktestEvidenceError("backtest attribution artifact drifted before append")
                existing = self._attributions.get((owner, record.attribution_ref))
            else:
                attribution = self._attributions.get((owner, record.attribution_ref))
                current = self._attribution_heads.get((owner, record.backtest_run_ref))
                if attribution is None or current != attribution:
                    raise BacktestEvidenceError(
                        "backtest monitor requires the current exact attribution head"
                    )
                state = self._artifact_state(attribution)
                if not self._artifact_matches(attribution, state):
                    raise BacktestEvidenceError("backtest monitor attribution artifact drifted")
                existing = self._monitors.get((owner, record.monitor_ref))
            if existing is not None:
                if existing != record:
                    raise BacktestEvidenceError("backtest evidence identity collision")
                return existing
            body = {
                "schema_version": BACKTEST_EVIDENCE_SCHEMA_VERSION,
                "event_type": event_type,
                "ledger_revision": self._last_revision + 1,
                "previous_record_hash": self._last_record_hash,
                "owner_user_id": owner,
                "payload": asdict(record),
            }
            row = {**body, "record_hash": _sha256(body)}
            self._atomic_append_unlocked(row)
            self._apply_row(row)
            return record

    def record_attribution(
        self,
        record: BacktestAttributionRecord,
    ) -> BacktestAttributionRecord:
        return self._record(record, event_type=_ATTRIBUTION_EVENT)

    def record_monitor(self, record: BacktestMonitorRecord) -> BacktestMonitorRecord:
        return self._record(record, event_type=_MONITOR_EVENT)

    def attribution(
        self,
        attribution_ref: str,
        *,
        owner_user_id: str,
    ) -> BacktestAttributionRecord:
        owner = _required(owner_user_id, "owner_user_id")
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._attributions[(owner, _text(attribution_ref))]
            except KeyError:
                raise KeyError("backtest attribution is not recorded for owner") from None

    def monitor(self, monitor_ref: str, *, owner_user_id: str) -> BacktestMonitorRecord:
        owner = _required(owner_user_id, "owner_user_id")
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._monitors[(owner, _text(monitor_ref))]
            except KeyError:
                raise KeyError("backtest monitor is not recorded for owner") from None

    def current_attribution(
        self,
        *,
        owner_user_id: str,
        backtest_run_ref: str,
    ) -> BacktestAttributionRecord:
        owner = _required(owner_user_id, "owner_user_id")
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._attribution_heads[(owner, _text(backtest_run_ref))]
            except KeyError:
                raise KeyError("current backtest attribution is unavailable") from None

    def current_monitor(
        self,
        *,
        owner_user_id: str,
        backtest_run_ref: str,
    ) -> BacktestMonitorRecord:
        owner = _required(owner_user_id, "owner_user_id")
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._monitor_heads[(owner, _text(backtest_run_ref))]
            except KeyError:
                raise KeyError("current backtest monitor is unavailable") from None

    def validate_current_attribution(
        self,
        attribution_ref: str,
        *,
        owner_user_id: str,
    ) -> BacktestEvidenceDecision:
        try:
            record = self.attribution(attribution_ref, owner_user_id=owner_user_id)
            current = self.current_attribution(
                owner_user_id=owner_user_id,
                backtest_run_ref=record.backtest_run_ref,
            )
            state = self._artifact_state(record)
            if current != record or not self._artifact_matches(record, state):
                raise BacktestEvidenceError("backtest attribution is stale")
            return validate_backtest_attribution_record(record)
        except (BacktestEvidenceError, KeyError, OSError, TypeError, ValueError) as exc:
            return BacktestEvidenceDecision(
                False,
                (
                    BacktestEvidenceViolation(
                        "backtest_attribution_not_current",
                        f"current attribution resolution failed:{type(exc).__name__}",
                        "attribution_ref",
                        _text(attribution_ref),
                    ),
                ),
            )

    def validate_current_monitor(
        self,
        monitor_ref: str,
        *,
        owner_user_id: str,
    ) -> BacktestEvidenceDecision:
        try:
            record = self.monitor(monitor_ref, owner_user_id=owner_user_id)
            current = self.current_monitor(
                owner_user_id=owner_user_id,
                backtest_run_ref=record.backtest_run_ref,
            )
            attribution = self.attribution(
                record.attribution_ref,
                owner_user_id=owner_user_id,
            )
            attribution_decision = self.validate_current_attribution(
                attribution.attribution_ref,
                owner_user_id=owner_user_id,
            )
            if (
                current != record
                or attribution.backtest_run_ref != record.backtest_run_ref
                or not attribution_decision.accepted
            ):
                raise BacktestEvidenceError("backtest monitor is stale")
            return validate_backtest_monitor_record(record)
        except (BacktestEvidenceError, KeyError, OSError, TypeError, ValueError) as exc:
            return BacktestEvidenceDecision(
                False,
                (
                    BacktestEvidenceViolation(
                        "backtest_monitor_not_current",
                        f"current monitor resolution failed:{type(exc).__name__}",
                        "monitor_ref",
                        _text(monitor_ref),
                    ),
                ),
            )


__all__ = [
    "BACKTEST_EVIDENCE_SCHEMA_VERSION",
    "BacktestArtifactResolver",
    "BacktestArtifactState",
    "BacktestAttributionRecord",
    "BacktestEvidenceCommitUncertain",
    "BacktestEvidenceDecision",
    "BacktestEvidenceError",
    "BacktestEvidenceViolation",
    "BacktestMonitorRecord",
    "PersistentBacktestEvidenceRegistry",
    "backtest_attribution_record_from_dict",
    "backtest_monitor_record_from_dict",
    "validate_backtest_attribution_record",
    "validate_backtest_monitor_record",
]
