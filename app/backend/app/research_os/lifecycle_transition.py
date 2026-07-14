"""Durable current-head transitions and closure receipts for GOAL §3."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .asset_lifecycle import (
    GovernedAssetRecord,
    LifecycleState,
    validate_governed_asset,
)
from .ref_resolution import is_placeholder_ref


REQUIRED_LIFECYCLE_ASSET_TYPES = frozenset(
    {
        "StrategyBook",
        "ResearchAsset",
        "DataSourceAsset",
        "Integration",
        "IngestionSkill",
        "Dataset",
        "Observable",
        "MathematicalSpine",
        "TheoryImplementationBinding",
        "LLMProvider",
        "ModelRoutingPolicy",
        "Factor",
        "Model",
        "Signal",
        "PortfolioPolicy",
        "RiskPolicy",
        "ExecutionPolicy",
        "Experiment",
        "Run",
    }
)


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list)) else (value,)
    return tuple(text for item in values if (text := _text(item)))


def _owner(value: Any) -> str:
    owner = _text(value)
    if not owner:
        raise ValueError("lifecycle transition owner_user_id is required")
    return owner


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class LifecycleTransitionRecord:
    transition_ref: str
    owner_user_id: str
    logical_asset_ref: str
    before_asset_ref: str
    after_asset_ref: str
    from_state: str
    to_state: str
    before_asset_sha256: str
    after_asset_sha256: str
    promotion_record_ref: str
    approval_ref: str
    evidence_refs: tuple[str, ...]
    transition_version: str = "lifecycle_transition.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "transition_ref",
            "owner_user_id",
            "logical_asset_ref",
            "before_asset_ref",
            "after_asset_ref",
            "from_state",
            "to_state",
            "before_asset_sha256",
            "after_asset_sha256",
            "promotion_record_ref",
            "approval_ref",
            "transition_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs))

    @property
    def canonical_ref(self) -> str:
        return "lifecycle_transition:" + content_hash(
            {**asdict(self), "transition_ref": ""}
        )


@dataclass(frozen=True)
class LifecycleClosureReceipt:
    receipt_ref: str
    owner_user_id: str
    transition_refs: tuple[str, ...]
    current_asset_refs: tuple[str, ...]
    current_asset_sha256s: tuple[str, ...]
    asset_types: tuple[str, ...]
    retired_override_refs: tuple[str, ...]
    receipt_version: str = "lifecycle_closure_receipt.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_ref", _text(self.receipt_ref))
        object.__setattr__(self, "owner_user_id", _text(self.owner_user_id))
        for field_name in (
            "transition_refs",
            "current_asset_refs",
            "current_asset_sha256s",
            "asset_types",
            "retired_override_refs",
        ):
            object.__setattr__(self, field_name, _refs(getattr(self, field_name)))
        object.__setattr__(self, "receipt_version", _text(self.receipt_version))

    @property
    def canonical_ref(self) -> str:
        return "lifecycle_closure_receipt:" + content_hash(
            {**asdict(self), "receipt_ref": ""}
        )


@dataclass(frozen=True)
class LifecycleClosureDecision:
    accepted: bool
    violations: tuple[str, ...]


@dataclass(frozen=True)
class LifecycleCurrentClosureSnapshot:
    """One lock-consistent receipt, transition heads, and aligned assets."""

    receipt: LifecycleClosureReceipt
    transitions: tuple[LifecycleTransitionRecord, ...]
    before_assets: tuple[GovernedAssetRecord, ...]
    after_assets: tuple[GovernedAssetRecord, ...]


AssetLoader = Callable[[str, str], GovernedAssetRecord]
RefValidator = Callable[[str, str, str], bool]
UsageLoader = Callable[[str, str], Iterable[tuple[str, bool, str | None]]]


class PersistentLifecycleTransitionRegistry:
    """Schema-v2 owner journal whose receipts always re-read current assets."""

    def __init__(
        self,
        path: str | Path,
        *,
        asset_loader: AssetLoader,
        ref_validator: RefValidator,
        usage_loader: UsageLoader | None = None,
        required_asset_types: frozenset[str] = REQUIRED_LIFECYCLE_ASSET_TYPES,
    ) -> None:
        if not callable(asset_loader) or not callable(ref_validator):
            raise TypeError("lifecycle transition registry requires asset/ref resolvers")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._history_marker_path = self._path.with_suffix(
            self._path.suffix + ".history"
        )
        self._asset_loader = asset_loader
        self._ref_validator = ref_validator
        self._usage_loader = usage_loader
        self._required_asset_types = frozenset(required_asset_types)
        self._lock = threading.RLock()
        self._transitions: dict[tuple[str, str], LifecycleTransitionRecord] = {}
        self._heads: dict[tuple[str, str], str] = {}
        self._receipts: dict[tuple[str, str], LifecycleClosureReceipt] = {}
        self._replay_violations: dict[str, tuple[str, ...]] = {}
        self._legacy_quarantined_count = 0
        self._known_rows: tuple[str, ...] = ()
        self._ever_had_history = False
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    @staticmethod
    def _transition_from_dict(raw: dict[str, Any]) -> LifecycleTransitionRecord:
        return LifecycleTransitionRecord(
            **{**raw, "evidence_refs": _refs(raw.get("evidence_refs"))}
        )

    @staticmethod
    def _receipt_from_dict(raw: dict[str, Any]) -> LifecycleClosureReceipt:
        return LifecycleClosureReceipt(
            **{
                **raw,
                "transition_refs": _refs(raw.get("transition_refs")),
                "current_asset_refs": _refs(raw.get("current_asset_refs")),
                "current_asset_sha256s": _refs(raw.get("current_asset_sha256s")),
                "asset_types": _refs(raw.get("asset_types")),
                "retired_override_refs": _refs(raw.get("retired_override_refs")),
            }
        )

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
            raise ValueError("lifecycle transition history marker cannot be a symlink")
        if not self._history_marker_path.exists():
            return None
        try:
            raw = json.loads(
                self._history_marker_path.read_text(encoding="utf-8")
            )
            if not isinstance(raw, dict) or raw.get("schema_version") != 1:
                raise ValueError("invalid lifecycle history marker schema")
            row_count = int(raw.get("row_count"))
            prefix_sha256 = str(raw.get("prefix_sha256") or "")
            if row_count < 0 or len(prefix_sha256) != 64:
                raise ValueError("invalid lifecycle history marker content")
            int(prefix_sha256, 16)
            return row_count, prefix_sha256
        except Exception as exc:  # noqa: BLE001 - integrity metadata fails closed.
            raise ValueError("invalid lifecycle transition history marker") from exc

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
                raise OSError("short lifecycle transition history marker write")
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

    @contextmanager
    def _exclusive_ledger_lock(self):
        """Serialize replay, current-head decisions, and appends across processes."""

        with self._lock:
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

    def _replay_unlocked(self) -> None:
        self._transitions = {}
        self._heads = {}
        self._receipts = {}
        self._replay_violations = {}
        self._legacy_quarantined_count = 0
        marker = self._history_marker()
        if not self._path.exists():
            empty_marker = (0, self._rows_digest(()))
            if marker is None and not self._ever_had_history:
                self._write_history_marker(())
                marker = empty_marker
            if marker == empty_marker and not self._ever_had_history:
                self._known_rows = ()
                return
            raise ValueError("persisted lifecycle transition history is missing")
        encoded_rows: list[str] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    raise ValueError(
                        f"invalid lifecycle transition row at {self._path}:{line_no}"
                    )
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("lifecycle transition row must be an object")
                    encoded_rows.append(self._encoded_row(row))
                    if row.get("schema_version") != 2:
                        self._legacy_quarantined_count += 1
                        continue
                    self._install(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        f"invalid lifecycle transition row at {self._path}:{line_no}"
                    ) from exc
        rows = tuple(encoded_rows)
        if marker is None:
            if self._legacy_quarantined_count != len(rows):
                raise ValueError(
                    "persisted lifecycle transition history marker is missing"
                )
        else:
            marker_count, marker_digest = marker
            if len(rows) < marker_count:
                raise ValueError("persisted lifecycle transition history was truncated")
            if self._rows_digest(rows[:marker_count]) != marker_digest:
                raise ValueError(
                    "persisted lifecycle transition history changed before marker"
                )
        if self._known_rows and rows[: len(self._known_rows)] != self._known_rows:
            raise ValueError(
                "persisted lifecycle transition append-only history changed"
            )
        self._known_rows = rows
        self._ever_had_history = self._ever_had_history or bool(rows)
        if (
            marker is None
            or marker[0] != len(rows)
            or marker[1] != self._rows_digest(rows)
        ):
            self._write_history_marker(rows)
        self._collect_replay_violations_unlocked()

    def _collect_replay_violations_unlocked(self) -> None:
        violations: dict[str, list[str]] = {}
        for (owner, _transition_ref), transition in self._transitions.items():
            try:
                before = self._asset_loader(owner, transition.before_asset_ref)
                after = self._asset_loader(owner, transition.after_asset_ref)
            except Exception:  # noqa: BLE001 - unavailable history stays red.
                violations.setdefault(owner, []).append(
                    f"historical_asset_unavailable:{transition.transition_ref}"
                )
                continue
            if _text(before.asset_type) != _text(after.asset_type):
                violations.setdefault(owner, []).append(
                    f"asset_type_changed:{transition.transition_ref}"
                )
        self._replay_violations = {
            owner: tuple(items) for owner, items in violations.items()
        }

    def _load(self) -> None:
        with self._exclusive_ledger_lock():
            self._replay_unlocked()

    def refresh(self) -> None:
        """Replay the durable journal under the cross-process ledger lock."""

        with self._exclusive_ledger_lock():
            self._replay_unlocked()

    def _append_unlocked(self, row: dict[str, Any]) -> None:
        """Append one row while the caller holds ``_exclusive_ledger_lock``."""

        encoded = json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if self._path.exists():
            with self._path.open("r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, start=1):
                    if not line.strip():
                        continue
                    existing = json.loads(line)
                    current = json.dumps(
                        existing,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if current == encoded:
                        return
                    if (
                        existing.get("schema_version") == 2
                        and existing.get("owner_user_id") == row.get("owner_user_id")
                        and existing.get("event_type") == row.get("event_type")
                    ):
                        identity_key = (
                            "transition_ref"
                            if row.get("event_type")
                            == "lifecycle_transition_recorded"
                            else "receipt_ref"
                        )
                        object_key = (
                            "transition"
                            if identity_key == "transition_ref"
                            else "receipt"
                        )
                        if (
                            existing.get(object_key, {}).get(identity_key)
                            == row.get(object_key, {}).get(identity_key)
                        ):
                            raise ValueError(
                                "lifecycle identity collision at "
                                f"{self._path}:{line_no}"
                            )
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(encoded + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        rows = (*self._known_rows, encoded)
        self._write_history_marker(rows)
        self._known_rows = rows
        self._ever_had_history = True

    def _validate_ref(self, owner: str, kind: str, ref: str) -> None:
        if not ref or is_placeholder_ref(ref) or not self._ref_validator(owner, kind, ref):
            raise ValueError(f"lifecycle {kind} ref is not current owner evidence: {ref}")

    def _transition_shape(self, record: LifecycleTransitionRecord) -> None:
        if record.transition_version != "lifecycle_transition.v1":
            raise ValueError("unsupported lifecycle transition version")
        for field_name in (
            "owner_user_id",
            "logical_asset_ref",
            "before_asset_ref",
            "after_asset_ref",
            "from_state",
            "to_state",
            "before_asset_sha256",
            "after_asset_sha256",
            "evidence_refs",
        ):
            if not getattr(record, field_name):
                raise ValueError(f"lifecycle transition missing {field_name}")
        if record.before_asset_ref == record.after_asset_ref:
            raise ValueError("lifecycle transition requires distinct immutable asset versions")
        if record.transition_ref != record.canonical_ref:
            raise ValueError("lifecycle transition identity mismatch")
        if record.to_state in {
            LifecycleState.APPROVED_RUNTIME.value,
            LifecycleState.MONITORED_RUNTIME.value,
        } and (not record.promotion_record_ref or not record.approval_ref):
            raise ValueError("runtime lifecycle transition requires promotion and approval")

    def _install(self, row: dict[str, Any], *, persist: bool) -> Any:
        if row.get("schema_version") != 2:
            raise ValueError("lifecycle transition requires schema_version=2")
        owner = _owner(row.get("owner_user_id"))
        event_type = row.get("event_type")
        if event_type == "lifecycle_transition_recorded":
            raw = row.get("transition")
            if not isinstance(raw, dict):
                raise ValueError("lifecycle transition event missing transition")
            record = self._transition_from_dict(raw)
            self._transition_shape(record)
            if record.owner_user_id != owner:
                raise ValueError("lifecycle transition owner envelope mismatch")
            key = (owner, record.transition_ref)
            existing = self._transitions.get(key)
            if existing is not None:
                if existing != record:
                    raise ValueError("lifecycle transition identity collision")
                return existing
            head_ref = self._heads.get((owner, record.logical_asset_ref))
            if head_ref is not None:
                head = self._transitions[(owner, head_ref)]
                if (
                    head.after_asset_ref != record.before_asset_ref
                    or head.after_asset_sha256 != record.before_asset_sha256
                    or head.to_state != record.from_state
                ):
                    raise ValueError(
                        "lifecycle transition history is not continuous for logical asset"
                    )
            if persist:
                self._append_unlocked(row)
            self._transitions[key] = record
            self._heads[(owner, record.logical_asset_ref)] = record.transition_ref
            return record
        if event_type == "lifecycle_closure_receipt_recorded":
            raw = row.get("receipt")
            if not isinstance(raw, dict):
                raise ValueError("lifecycle receipt event missing receipt")
            receipt = self._receipt_from_dict(raw)
            if receipt.owner_user_id != owner or receipt.receipt_ref != receipt.canonical_ref:
                raise ValueError("lifecycle closure receipt owner or identity mismatch")
            key = (owner, receipt.receipt_ref)
            existing = self._receipts.get(key)
            if existing is not None:
                if existing != receipt:
                    raise ValueError("lifecycle closure receipt identity collision")
                return existing
            if persist:
                self._append_unlocked(row)
            self._receipts[key] = receipt
            return receipt
        raise ValueError("unknown lifecycle transition event_type")

    def record_transition(
        self,
        *,
        owner_user_id: str,
        logical_asset_ref: str,
        before_asset_ref: str,
        after_asset_ref: str,
        promotion_record_ref: str = "",
        approval_ref: str = "",
        evidence_refs: tuple[str, ...],
    ) -> LifecycleTransitionRecord:
        owner = _owner(owner_user_id)
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return self._record_transition_unlocked(
                owner=owner,
                logical_asset_ref=logical_asset_ref,
                before_asset_ref=before_asset_ref,
                after_asset_ref=after_asset_ref,
                promotion_record_ref=promotion_record_ref,
                approval_ref=approval_ref,
                evidence_refs=evidence_refs,
            )

    def _record_transition_unlocked(
        self,
        *,
        owner: str,
        logical_asset_ref: str,
        before_asset_ref: str,
        after_asset_ref: str,
        promotion_record_ref: str,
        approval_ref: str,
        evidence_refs: tuple[str, ...],
    ) -> LifecycleTransitionRecord:
        logical = _text(logical_asset_ref)
        before = self._asset_loader(owner, _text(before_asset_ref))
        after = self._asset_loader(owner, _text(after_asset_ref))
        for asset in (before, after):
            decision = validate_governed_asset(asset)
            if not decision.accepted:
                raise ValueError("lifecycle transition cites invalid governed asset")
        before_asset_type = _text(before.asset_type)
        after_asset_type = _text(after.asset_type)
        if not before_asset_type or before_asset_type != after_asset_type:
            raise ValueError(
                "lifecycle transition requires the same asset_type before and after"
            )
        evidence = _refs(evidence_refs)
        for ref in evidence:
            self._validate_ref(owner, "evidence", ref)
        promotion = _text(promotion_record_ref)
        approval = _text(approval_ref)
        if promotion:
            self._validate_ref(owner, "promotion", promotion)
        if approval:
            self._validate_ref(owner, "approval", approval)
        head_ref = self._heads.get((owner, logical))
        if head_ref is not None:
            head = self._transitions[(owner, head_ref)]
            if (
                head.before_asset_ref == before.asset_ref
                and head.after_asset_ref == after.asset_ref
                and head.promotion_record_ref == promotion
                and head.approval_ref == approval
                and head.evidence_refs == evidence
                and head.before_asset_sha256 == _sha256(asdict(before))
                and head.after_asset_sha256 == _sha256(asdict(after))
            ):
                return head
            if head.after_asset_ref != before.asset_ref:
                raise ValueError("lifecycle transition before asset is not the current head")
        provisional = LifecycleTransitionRecord(
            transition_ref="",
            owner_user_id=owner,
            logical_asset_ref=logical,
            before_asset_ref=before.asset_ref,
            after_asset_ref=after.asset_ref,
            from_state=_text(before.lifecycle_state),
            to_state=_text(after.lifecycle_state),
            before_asset_sha256=_sha256(asdict(before)),
            after_asset_sha256=_sha256(asdict(after)),
            promotion_record_ref=promotion,
            approval_ref=approval,
            evidence_refs=evidence,
        )
        record = LifecycleTransitionRecord(
            **{**asdict(provisional), "transition_ref": provisional.canonical_ref}
        )
        self._transition_shape(record)
        return self._install(
            {
                "schema_version": 2,
                "event_type": "lifecycle_transition_recorded",
                "owner_user_id": owner,
                "transition": asdict(record),
            },
            persist=True,
        )

    def transition(
        self,
        transition_ref: str,
        *,
        owner_user_id: str,
    ) -> LifecycleTransitionRecord:
        owner = _owner(owner_user_id)
        ref = _text(transition_ref)
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return self._transitions[(owner, ref)]

    def _current_material(
        self,
        owner: str,
    ) -> tuple[
        list[LifecycleTransitionRecord],
        list[GovernedAssetRecord],
        list[GovernedAssetRecord],
        tuple[str, ...],
        list[str],
    ]:
        transitions = sorted(
            (
                self._transitions[(owner, transition_ref)]
                for (head_owner, _logical), transition_ref in self._heads.items()
                if head_owner == owner
            ),
            key=lambda item: item.logical_asset_ref,
        )
        before_assets: list[GovernedAssetRecord] = []
        after_assets: list[GovernedAssetRecord] = []
        overrides: set[str] = set()
        violations: list[str] = list(self._replay_violations.get(owner, ()))
        for transition in transitions:
            try:
                before = self._asset_loader(owner, transition.before_asset_ref)
                after = self._asset_loader(owner, transition.after_asset_ref)
            except Exception:  # noqa: BLE001
                violations.append(f"asset_unavailable:{transition.transition_ref}")
                continue
            if (
                _sha256(asdict(before)) != transition.before_asset_sha256
                or _sha256(asdict(after)) != transition.after_asset_sha256
                or _text(before.lifecycle_state) != transition.from_state
                or _text(after.lifecycle_state) != transition.to_state
            ):
                violations.append(f"asset_drift:{transition.transition_ref}")
            if _text(before.asset_type) != _text(after.asset_type):
                violations.append(f"asset_type_changed:{transition.transition_ref}")
            for kind, ref in (
                ("promotion", transition.promotion_record_ref),
                ("approval", transition.approval_ref),
                *(("evidence", ref) for ref in transition.evidence_refs),
            ):
                if ref and (
                    is_placeholder_ref(ref) or not self._ref_validator(owner, kind, ref)
                ):
                    violations.append(f"ref_drift:{transition.transition_ref}:{ref}")
            if _text(after.lifecycle_state) == LifecycleState.RETIRED.value and self._usage_loader:
                for _run_ref, default_reference, override_ref in self._usage_loader(
                    owner, after.asset_ref
                ):
                    if default_reference and not _text(override_ref):
                        violations.append(f"retired_default_use:{after.asset_ref}")
                    elif override_ref:
                        overrides.add(_text(override_ref))
            before_assets.append(before)
            after_assets.append(after)
        asset_types = tuple(
            sorted({_text(asset.asset_type) for asset in after_assets})
        )
        missing_types = sorted(self._required_asset_types - set(asset_types))
        if missing_types:
            violations.extend(f"asset_type_missing:{item}" for item in missing_types)
        return (
            transitions,
            before_assets,
            after_assets,
            tuple(sorted(overrides)),
            violations,
        )

    def record_current_receipt(
        self,
        *,
        owner_user_id: str,
    ) -> LifecycleClosureReceipt:
        owner = _owner(owner_user_id)
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return self._record_current_receipt_unlocked(owner=owner)

    def _record_current_receipt_unlocked(
        self,
        *,
        owner: str,
    ) -> LifecycleClosureReceipt:
        transitions, _before_assets, after_assets, overrides, violations = (
            self._current_material(owner)
        )
        if violations or not transitions:
            raise ValueError(";".join(violations or ["lifecycle_transition_heads_missing"]))
        provisional = LifecycleClosureReceipt(
            receipt_ref="",
            owner_user_id=owner,
            transition_refs=tuple(item.transition_ref for item in transitions),
            current_asset_refs=tuple(item.asset_ref for item in after_assets),
            current_asset_sha256s=tuple(
                _sha256(asdict(item)) for item in after_assets
            ),
            asset_types=tuple(
                sorted({_text(item.asset_type) for item in after_assets})
            ),
            retired_override_refs=overrides,
        )
        receipt = LifecycleClosureReceipt(
            **{**asdict(provisional), "receipt_ref": provisional.canonical_ref}
        )
        return self._install(
            {
                "schema_version": 2,
                "event_type": "lifecycle_closure_receipt_recorded",
                "owner_user_id": owner,
                "receipt": asdict(receipt),
            },
            persist=True,
        )

    def receipt(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> LifecycleClosureReceipt:
        owner = _owner(owner_user_id)
        ref = _text(receipt_ref)
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return self._receipts[(owner, ref)]

    def receipts(self, *, owner_user_id: str) -> list[LifecycleClosureReceipt]:
        owner = _owner(owner_user_id)
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return [
                receipt
                for (record_owner, _ref), receipt in self._receipts.items()
                if record_owner == owner
            ]

    def transitions(self, *, owner_user_id: str) -> list[LifecycleTransitionRecord]:
        owner = _owner(owner_user_id)
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return [
                transition
                for (record_owner, _ref), transition in self._transitions.items()
                if record_owner == owner
            ]

    def _current_receipt_material_unlocked(
        self,
        *,
        owner: str,
        receipt_ref: str,
    ) -> tuple[
        LifecycleClosureReceipt,
        list[LifecycleTransitionRecord],
        list[GovernedAssetRecord],
        list[GovernedAssetRecord],
        list[str],
    ]:
        receipt = self._receipts[(owner, receipt_ref)]
        (
            transitions,
            before_assets,
            after_assets,
            overrides,
            current_violations,
        ) = self._current_material(owner)
        violations = list(current_violations)
        if tuple(item.transition_ref for item in transitions) != receipt.transition_refs:
            violations.append("lifecycle_transition_heads_changed")
        if tuple(item.asset_ref for item in after_assets) != receipt.current_asset_refs:
            violations.append("lifecycle_current_assets_changed")
        if (
            tuple(_sha256(asdict(item)) for item in after_assets)
            != receipt.current_asset_sha256s
        ):
            violations.append("lifecycle_current_asset_hashes_changed")
        if (
            tuple(sorted({_text(item.asset_type) for item in after_assets}))
            != receipt.asset_types
        ):
            violations.append("lifecycle_asset_types_changed")
        if overrides != receipt.retired_override_refs:
            violations.append("lifecycle_retired_overrides_changed")
        if len(before_assets) != len(transitions) or len(after_assets) != len(
            transitions
        ):
            violations.append("lifecycle_transition_asset_alignment_changed")
        return receipt, transitions, before_assets, after_assets, violations

    def current_closure_snapshot(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> LifecycleCurrentClosureSnapshot:
        """Return exact current receipt material from one serialized replay."""

        owner = _owner(owner_user_id)
        ref = _text(receipt_ref)
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            receipt, transitions, before_assets, after_assets, violations = (
                self._current_receipt_material_unlocked(
                    owner=owner,
                    receipt_ref=ref,
                )
            )
            if violations:
                raise ValueError(";".join(violations))
            return LifecycleCurrentClosureSnapshot(
                receipt=receipt,
                transitions=tuple(transitions),
                before_assets=tuple(before_assets),
                after_assets=tuple(after_assets),
            )

    def validate_current(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> LifecycleClosureDecision:
        owner = _owner(owner_user_id)
        ref = _text(receipt_ref)
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            try:
                _receipt, _transitions, _before_assets, _after_assets, violations = (
                    self._current_receipt_material_unlocked(
                        owner=owner,
                        receipt_ref=ref,
                    )
                )
            except KeyError:
                return LifecycleClosureDecision(
                    False,
                    ("lifecycle_receipt_unknown",),
                )
            return LifecycleClosureDecision(not violations, tuple(violations))


__all__ = [
    "LifecycleClosureDecision",
    "LifecycleClosureReceipt",
    "LifecycleCurrentClosureSnapshot",
    "LifecycleTransitionRecord",
    "PersistentLifecycleTransitionRegistry",
    "REQUIRED_LIFECYCLE_ASSET_TYPES",
]
