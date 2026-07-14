"""Durable evidence producers used by GOAL section 15 recertification.

This ledger stores observations and their immutable thresholds, content-bound
dependency resolutions, and challenger comparisons.  None of its write APIs
accepts a recertification trigger or a caller-computed pass/fail flag: trigger
kind and verdicts are derived from typed records when the event registry reads
the ledger.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash


MODEL_RECERTIFICATION_EVIDENCE_SCHEMA_VERSION = 1


class ModelEvidenceError(ValueError):
    """Evidence is malformed, cross-owner, corrupt, or cannot be persisted."""


class ModelEvidenceCommitUncertain(RuntimeError):
    """An append failed and exact rollback could not be confirmed."""


class MonitoringSignalKind(str, Enum):
    FEATURE_DISTRIBUTION = "feature_distribution"
    PERFORMANCE = "performance"


class ThresholdComparison(str, Enum):
    ABOVE = "above"
    BELOW = "below"


class DependencyKind(str, Enum):
    VENDOR = "vendor"
    FOUNDATION_MODEL = "foundation_model"


def _required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or text != value or any(ord(char) < 32 for char in text):
        raise ModelEvidenceError(f"{field} must be a stable non-empty exact string")
    return text


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ModelEvidenceError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelEvidenceError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ModelEvidenceError(f"{field} must be a finite number")
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(prefix: str, value: Any) -> str:
    return prefix + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelMonitoringRule:
    owner_user_id: str
    model_type_card_ref: str
    model_version_ref: str
    model_passport_ref: str
    monitoring_profile_ref: str
    signal_kind: MonitoringSignalKind
    signal_ref: str
    baseline_value: float
    threshold_value: float
    comparison: ThresholdComparison
    recorded_by: str
    rule_ref: str = ""

    def __post_init__(self) -> None:
        for field in (
            "owner_user_id", "model_type_card_ref", "model_version_ref",
            "model_passport_ref", "monitoring_profile_ref", "signal_ref", "recorded_by",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        try:
            object.__setattr__(self, "signal_kind", MonitoringSignalKind(self.signal_kind))
            object.__setattr__(self, "comparison", ThresholdComparison(self.comparison))
        except ValueError as exc:
            raise ModelEvidenceError("monitoring rule enum is unsupported") from exc
        object.__setattr__(self, "baseline_value", _finite(self.baseline_value, "baseline_value"))
        object.__setattr__(self, "threshold_value", _finite(self.threshold_value, "threshold_value"))
        material = {key: value.value if isinstance(value, Enum) else value for key, value in asdict(self).items() if key != "rule_ref"}
        expected = _hash("model_monitoring_rule_", material)
        if self.rule_ref and self.rule_ref != expected:
            raise ModelEvidenceError("monitoring rule ref does not match content")
        object.__setattr__(self, "rule_ref", expected)

    def breached(self, value: float) -> bool:
        observed = _finite(value, "observed_value")
        if self.comparison == ThresholdComparison.ABOVE:
            return observed > self.threshold_value
        return observed < self.threshold_value


@dataclass(frozen=True)
class ModelMonitoringObservation:
    owner_user_id: str
    rule_ref: str
    observed_value: float
    observation_ref: str
    producer_ref: str
    recorded_by: str
    record_ref: str = ""

    def __post_init__(self) -> None:
        for field in ("owner_user_id", "rule_ref", "observation_ref", "producer_ref", "recorded_by"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        object.__setattr__(self, "observed_value", _finite(self.observed_value, "observed_value"))
        material = {key: value for key, value in asdict(self).items() if key != "record_ref"}
        expected = _hash("model_monitoring_observation_", material)
        if self.record_ref and self.record_ref != expected:
            raise ModelEvidenceError("monitoring observation ref does not match content")
        object.__setattr__(self, "record_ref", expected)


@dataclass(frozen=True)
class ModelDependencyFingerprint:
    owner_user_id: str
    dependency_kind: DependencyKind
    dependency_ref: str
    content_fingerprint: str
    resolver_ref: str
    recorded_by: str
    fingerprint_ref: str = ""

    def __post_init__(self) -> None:
        for field in ("owner_user_id", "dependency_ref", "content_fingerprint", "resolver_ref", "recorded_by"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        try:
            object.__setattr__(self, "dependency_kind", DependencyKind(self.dependency_kind))
        except ValueError as exc:
            raise ModelEvidenceError("dependency kind is unsupported") from exc
        fingerprint = self.content_fingerprint
        if not fingerprint.startswith("sha256:") or len(fingerprint) != 71:
            raise ModelEvidenceError("content_fingerprint must be a sha256 digest")
        try:
            int(fingerprint[7:], 16)
        except ValueError as exc:
            raise ModelEvidenceError("content_fingerprint must be a sha256 digest") from exc
        material = {key: value.value if isinstance(value, Enum) else value for key, value in asdict(self).items() if key != "fingerprint_ref"}
        expected = _hash("model_dependency_fingerprint_", material)
        if self.fingerprint_ref and self.fingerprint_ref != expected:
            raise ModelEvidenceError("dependency fingerprint ref does not match content")
        object.__setattr__(self, "fingerprint_ref", expected)


@dataclass(frozen=True)
class ModelChallengerResult:
    owner_user_id: str
    model_type_card_ref: str
    model_version_ref: str
    model_passport_ref: str
    baseline_run_ref: str
    challenger_run_ref: str
    metric_ref: str
    baseline_value: float
    challenger_value: float
    minimum_improvement: float
    higher_is_better: bool
    producer_ref: str
    reviewer_user_id: str
    recorded_by: str
    result_ref: str = ""

    def __post_init__(self) -> None:
        for field in (
            "owner_user_id", "model_type_card_ref", "model_version_ref", "model_passport_ref",
            "baseline_run_ref", "challenger_run_ref", "metric_ref", "producer_ref",
            "reviewer_user_id", "recorded_by",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        if self.baseline_run_ref == self.challenger_run_ref:
            raise ModelEvidenceError("challenger and baseline runs must be distinct")
        if self.reviewer_user_id.casefold() == self.recorded_by.casefold():
            raise ModelEvidenceError("challenger result requires an independent reviewer")
        if type(self.higher_is_better) is not bool:
            raise ModelEvidenceError("higher_is_better must be boolean")
        for field in ("baseline_value", "challenger_value", "minimum_improvement"):
            object.__setattr__(self, field, _finite(getattr(self, field), field))
        if self.minimum_improvement < 0:
            raise ModelEvidenceError("minimum_improvement cannot be negative")
        material = {key: value for key, value in asdict(self).items() if key != "result_ref"}
        expected = _hash("model_challenger_result_", material)
        if self.result_ref and self.result_ref != expected:
            raise ModelEvidenceError("challenger result ref does not match content")
        object.__setattr__(self, "result_ref", expected)

    @property
    def improvement(self) -> float:
        delta = self.challenger_value - self.baseline_value
        return delta if self.higher_is_better else -delta

    @property
    def passed(self) -> bool:
        return self.improvement >= self.minimum_improvement


_RECORD_TYPES = {
    "monitoring_rule": ModelMonitoringRule,
    "monitoring_observation": ModelMonitoringObservation,
    "dependency_fingerprint": ModelDependencyFingerprint,
    "challenger_result": ModelChallengerResult,
}


class PersistentModelRecertificationEvidenceRegistry:
    """Owner-scoped append-only hash-chain for §15 producer evidence."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._thread_lock = threading.RLock()
        self._reset()
        self._refresh()

    @property
    def path(self) -> Path:
        return self._path

    def _reset(self) -> None:
        self._records: dict[tuple[str, str], Any] = {}
        self._record_hashes: dict[tuple[str, str], str] = {}
        self._observation_refs: dict[tuple[str, str], str] = {}
        self._ordered: list[tuple[str, Any]] = []
        self._last_hash = ""

    def _lock(self):
        class Lock:
            def __init__(inner, path: Path) -> None:
                inner.path = path
            def __enter__(inner):
                inner.fd = os.open(inner.path, os.O_RDWR | os.O_CREAT, 0o600)
                try:
                    os.chmod(inner.path, 0o600)
                    inner.held = acquire_exclusive_fd(inner.fd, timeout_seconds=30.0)
                except Exception:
                    os.close(inner.fd)
                    raise
            def __exit__(inner, exc_type, exc, tb):
                inner.held.release()
                os.close(inner.fd)
        return Lock(self._lock_path)

    @staticmethod
    def _ref(record: Any) -> str:
        by_type = {
            ModelMonitoringRule: "rule_ref",
            ModelMonitoringObservation: "record_ref",
            ModelDependencyFingerprint: "fingerprint_ref",
            ModelChallengerResult: "result_ref",
        }
        for cls, field in by_type.items():
            if isinstance(record, cls):
                return getattr(record, field)
        raise ModelEvidenceError("unsupported evidence record")

    @staticmethod
    def _payload(record: Any) -> dict[str, Any]:
        value = asdict(record)
        for key, item in tuple(value.items()):
            if isinstance(item, Enum):
                value[key] = item.value
        return value

    def _apply(self, row: Any) -> None:
        expected = {"schema_version", "sequence", "record_type", "owner_user_id", "previous_record_hash", "record", "record_hash"}
        if not isinstance(row, dict) or set(row) != expected:
            raise ModelEvidenceError("model evidence row has an inexact field set")
        if row["schema_version"] != MODEL_RECERTIFICATION_EVIDENCE_SCHEMA_VERSION:
            raise ModelEvidenceError("unsupported model evidence schema version")
        if type(row["sequence"]) is not int or row["sequence"] != len(self._ordered) + 1:
            raise ModelEvidenceError("model evidence sequence is discontinuous")
        if row["previous_record_hash"] != self._last_hash:
            raise ModelEvidenceError("model evidence hash chain is forked")
        unsigned = dict(row)
        supplied_hash = unsigned.pop("record_hash")
        if supplied_hash != _hash("model_evidence_row_", unsigned):
            raise ModelEvidenceError("model evidence row hash mismatch")
        record_type = row["record_type"]
        cls = _RECORD_TYPES.get(record_type)
        if cls is None or not isinstance(row["record"], dict):
            raise ModelEvidenceError("unsupported model evidence record type")
        try:
            record = cls(**row["record"])
        except (TypeError, ValueError) as exc:
            raise ModelEvidenceError("invalid model evidence record") from exc
        if row["owner_user_id"] != record.owner_user_id:
            raise ModelEvidenceError("model evidence owner envelope mismatch")
        key = (record.owner_user_id, self._ref(record))
        if key in self._records:
            raise ModelEvidenceError("duplicate model evidence identity")
        if isinstance(record, ModelMonitoringObservation):
            rule = self._records.get((record.owner_user_id, record.rule_ref))
            if not isinstance(rule, ModelMonitoringRule):
                raise ModelEvidenceError("monitoring observation rule is missing or cross-owner")
            observation_key = (record.owner_user_id, record.observation_ref)
            if observation_key in self._observation_refs:
                raise ModelEvidenceError("monitoring observation_ref is duplicated")
            self._observation_refs[observation_key] = record.record_ref
        self._records[key] = record
        self._record_hashes[key] = supplied_hash
        self._ordered.append((record_type, record))
        self._last_hash = supplied_hash

    def _load(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ModelEvidenceError("model evidence ledger cannot be read") from exc
        for line_no, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                self._apply(json.loads(line))
            except Exception as exc:
                raise ModelEvidenceError(f"invalid model evidence row at {self._path}:{line_no}") from exc

    def _refresh(self) -> None:
        with self._thread_lock, self._lock():
            self._load()

    def _record(self, record_type: str, record: Any) -> Any:
        with self._thread_lock, self._lock():
            self._load()
            key = (record.owner_user_id, self._ref(record))
            existing = self._records.get(key)
            if existing is not None:
                if existing != record:
                    raise ModelEvidenceError("model evidence identity collision")
                return existing
            if isinstance(record, ModelMonitoringObservation):
                if not isinstance(
                    self._records.get((record.owner_user_id, record.rule_ref)),
                    ModelMonitoringRule,
                ):
                    raise ModelEvidenceError(
                        "monitoring observation rule is missing or cross-owner"
                    )
                existing_observation = self._observation_refs.get(
                    (record.owner_user_id, record.observation_ref)
                )
                if existing_observation is not None:
                    raise ModelEvidenceError("monitoring observation_ref is duplicated")
            unsigned = {
                "schema_version": MODEL_RECERTIFICATION_EVIDENCE_SCHEMA_VERSION,
                "sequence": len(self._ordered) + 1,
                "record_type": record_type,
                "owner_user_id": record.owner_user_id,
                "previous_record_hash": self._last_hash,
                "record": self._payload(record),
            }
            row = {**unsigned, "record_hash": _hash("model_evidence_row_", unsigned)}
            original_exists = self._path.exists()
            original = self._path.read_bytes() if original_exists else b""
            fd: int | None = None
            try:
                fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                data = (_canonical(row) + "\n").encode("utf-8")
                offset = 0
                while offset < len(data):
                    written = os.write(fd, data[offset:])
                    if written <= 0:
                        raise OSError("model evidence append made no progress")
                    offset += written
                os.fsync(fd)
                os.close(fd)
                fd = None
                if not original_exists:
                    directory_fd = os.open(self._path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            except Exception as append_exc:
                if fd is not None:
                    os.close(fd)
                try:
                    restore_fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    try:
                        offset = 0
                        while offset < len(original):
                            written = os.write(restore_fd, original[offset:])
                            if written <= 0:
                                raise OSError("model evidence rollback made no progress")
                            offset += written
                        os.fsync(restore_fd)
                    finally:
                        os.close(restore_fd)
                    if not original_exists and not original:
                        self._path.unlink(missing_ok=True)
                    directory_fd = os.open(self._path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                    self._load()
                except Exception as rollback_exc:
                    raise ModelEvidenceCommitUncertain(
                        "model evidence append failed and rollback is uncertain"
                    ) from rollback_exc
                raise append_exc
            self._load()
            return self._records[key]

    def record_monitoring_rule(self, rule: ModelMonitoringRule) -> ModelMonitoringRule:
        return self._record("monitoring_rule", rule)

    def record_monitoring_observation(self, observation: ModelMonitoringObservation) -> ModelMonitoringObservation:
        return self._record("monitoring_observation", observation)

    def record_dependency_fingerprint(self, fingerprint: ModelDependencyFingerprint) -> ModelDependencyFingerprint:
        return self._record("dependency_fingerprint", fingerprint)

    def record_dependency_content(
        self,
        *,
        owner_user_id: str,
        dependency_kind: DependencyKind,
        dependency_ref: str,
        content: bytes,
        resolver_ref: str,
        recorded_by: str,
    ) -> ModelDependencyFingerprint:
        """Hash resolver-returned bytes; callers cannot supply the digest verdict."""

        if not isinstance(content, bytes) or not content:
            raise ModelEvidenceError("dependency content must be non-empty bytes")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        return self.record_dependency_fingerprint(
            ModelDependencyFingerprint(
                owner_user_id=owner_user_id,
                dependency_kind=dependency_kind,
                dependency_ref=dependency_ref,
                content_fingerprint=digest,
                resolver_ref=resolver_ref,
                recorded_by=recorded_by,
            )
        )

    def record_dependency_file(
        self,
        path: str | Path,
        *,
        owner_user_id: str,
        dependency_kind: DependencyKind,
        dependency_ref: str,
        recorded_by: str,
    ) -> ModelDependencyFingerprint:
        """Resolve a regular non-symlink lock/manifest file and hash its bytes."""

        candidate = Path(path)
        try:
            resolved = candidate.resolve(strict=True)
            if candidate.is_symlink() or not resolved.is_file():
                raise OSError
            content = resolved.read_bytes()
        except OSError as exc:
            raise ModelEvidenceError("dependency file must be a readable regular non-symlink file") from exc
        return self.record_dependency_content(
            owner_user_id=owner_user_id,
            dependency_kind=dependency_kind,
            dependency_ref=dependency_ref,
            content=content,
            resolver_ref=f"file-sha256:{resolved}",
            recorded_by=recorded_by,
        )

    def record_challenger_result(self, result: ModelChallengerResult) -> ModelChallengerResult:
        return self._record("challenger_result", result)

    def _get(self, owner_user_id: str, ref: str, cls: type) -> Any:
        owner = _required(owner_user_id, "owner_user_id")
        evidence_ref = _required(ref, "evidence_ref")
        self._refresh()
        record = self._records.get((owner, evidence_ref))
        if not isinstance(record, cls):
            raise KeyError("model evidence is not recorded for owner")
        return record

    def monitoring_rule(self, rule_ref: str, *, owner_user_id: str) -> ModelMonitoringRule:
        return self._get(owner_user_id, rule_ref, ModelMonitoringRule)

    def dependency_fingerprint(self, fingerprint_ref: str, *, owner_user_id: str) -> ModelDependencyFingerprint:
        return self._get(owner_user_id, fingerprint_ref, ModelDependencyFingerprint)

    def challenger_result(self, result_ref: str, *, owner_user_id: str) -> ModelChallengerResult:
        return self._get(owner_user_id, result_ref, ModelChallengerResult)

    def breached_observations(
        self, *, owner_user_id: str, model_type_card_ref: str, model_passport_ref: str
    ) -> tuple[tuple[ModelMonitoringRule, ModelMonitoringObservation], ...]:
        owner = _required(owner_user_id, "owner_user_id")
        model_ref = _required(model_type_card_ref, "model_type_card_ref")
        passport_ref = _required(model_passport_ref, "model_passport_ref")
        self._refresh()
        result: list[tuple[ModelMonitoringRule, ModelMonitoringObservation]] = []
        for record_type, record in self._ordered:
            if record_type != "monitoring_observation" or record.owner_user_id != owner:
                continue
            rule = self._records.get((owner, record.rule_ref))
            if (
                isinstance(rule, ModelMonitoringRule)
                and rule.model_type_card_ref == model_ref
                and rule.model_passport_ref == passport_ref
                and rule.breached(record.observed_value)
            ):
                result.append((rule, record))
        return tuple(result)

    def resolve_dependencies(
        self,
        refs: Iterable[str],
        *,
        owner_user_id: str,
        dependency_kind: DependencyKind,
    ) -> tuple[ModelDependencyFingerprint, ...]:
        owner = _required(owner_user_id, "owner_user_id")
        normalized = tuple(_required(ref, "dependency_fingerprint_ref") for ref in refs)
        if normalized == ("none",):
            return ()
        if not normalized or any(not ref for ref in normalized) or len(normalized) != len(set(normalized)):
            raise ModelEvidenceError("dependency refs must be unique and non-empty")
        resolved = tuple(self.dependency_fingerprint(ref, owner_user_id=owner) for ref in normalized)
        if any(item.dependency_kind != dependency_kind for item in resolved):
            raise ModelEvidenceError("dependency fingerprint kind mismatch")
        for item in resolved:
            prefix = "file-sha256:"
            if item.resolver_ref.startswith(prefix):
                path = Path(item.resolver_ref[len(prefix):])
                try:
                    if path.is_symlink() or not path.is_file():
                        raise OSError
                    current = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError as exc:
                    raise ModelEvidenceError("dependency resolver file is no longer readable") from exc
                if current != item.content_fingerprint:
                    raise ModelEvidenceError("dependency resolver file content has drifted")
        return tuple(sorted(resolved, key=lambda item: item.fingerprint_ref))

    def current_record_hash(self, evidence_ref: str, *, owner_user_id: str) -> str:
        owner = _required(owner_user_id, "owner_user_id")
        ref = _required(evidence_ref, "evidence_ref")
        self._refresh()
        try:
            return self._record_hashes[(owner, ref)]
        except KeyError as exc:
            raise KeyError("model evidence is not recorded for owner") from exc

    def current_state(
        self,
        *,
        owner_user_id: str,
        model_type_card_ref: str | None = None,
        model_passport_ref: str | None = None,
        dependency_refs: Iterable[str] = (),
        challenger_ref: str | None = None,
    ) -> dict[str, Any]:
        owner = _required(owner_user_id, "owner_user_id")
        self._refresh()
        model_ref = str(model_type_card_ref or "").strip()
        passport_ref = str(model_passport_ref or "").strip()
        selected_dependency_refs = set(dependency_refs)
        selected_challenger_ref = str(challenger_ref or "").strip()
        selected_rules = {
            record.rule_ref
            for kind, record in self._ordered
            if kind == "monitoring_rule"
            and record.owner_user_id == owner
            and (not model_ref or record.model_type_card_ref == model_ref)
            and (not passport_ref or record.model_passport_ref == passport_ref)
        }
        def included(kind: str, record: Any) -> bool:
            if record.owner_user_id != owner:
                return False
            if kind == "monitoring_rule":
                return record.rule_ref in selected_rules
            if kind == "monitoring_observation":
                return record.rule_ref in selected_rules
            if kind == "dependency_fingerprint":
                return record.fingerprint_ref in selected_dependency_refs
            if kind == "challenger_result":
                return bool(selected_challenger_ref) and record.result_ref == selected_challenger_ref
            return False
        records = [
            {"record_type": kind, "record_ref": self._ref(record), "record_hash": self._record_hashes[(owner, self._ref(record))]}
            for kind, record in self._ordered if included(kind, record)
        ]
        return {"path": str(self._path), "records": records, "state_hash": content_hash(records)}


__all__ = [
    "DependencyKind",
    "MODEL_RECERTIFICATION_EVIDENCE_SCHEMA_VERSION",
    "ModelChallengerResult",
    "ModelDependencyFingerprint",
    "ModelEvidenceCommitUncertain",
    "ModelEvidenceError",
    "ModelMonitoringObservation",
    "ModelMonitoringRule",
    "MonitoringSignalKind",
    "PersistentModelRecertificationEvidenceRegistry",
    "ThresholdComparison",
]
