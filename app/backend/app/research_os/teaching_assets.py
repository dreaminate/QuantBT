"""Owner-scoped teaching assets with visible weakness and evidence lineage.

The ledger records actual tutorial/example/template catalog objects.  It does
not create platform-coverage evidence.  Every bundle binds one current
governed asset to a visible-by-default weakness disclosure and a teaching
evidence record.  Events are hash chained and replaced atomically so restart,
concurrent writers, and partial writes fail closed.
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
from typing import Any, Iterator

from ..cross_process_lock import acquire_exclusive_fd


TEACHING_ASSET_SCHEMA_VERSION = 1
_EVENT_TYPE = "teaching_asset_bundle_recorded"
_GENESIS = "0" * 64


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _owner(value: Any) -> str:
    owner = _text(value)
    if not owner or owner != value or any(ord(char) < 32 for char in owner):
        raise ValueError("teaching owner_user_id must be a stable exact string")
    return owner


def _refs(values: Any, label: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, (tuple, list)):
        raise ValueError(f"{label} must be a list/tuple of refs")
    refs = tuple(_text(value) for value in values)
    if not refs or any(not ref for ref in refs) or len(refs) != len(set(refs)):
        raise ValueError(f"{label} must contain unique non-empty refs")
    return refs


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TutorialAssetRecord:
    tutorial_asset_ref: str
    owner_user_id: str
    governed_asset_ref: str
    category: str
    title: str

    @property
    def canonical_ref(self) -> str:
        return "tutorial_asset:" + _digest(
            {
                "owner_user_id": self.owner_user_id,
                "governed_asset_ref": self.governed_asset_ref,
                "category": self.category,
                "title": self.title,
            }
        )


@dataclass(frozen=True)
class WeaknessDisclosureRecord:
    weakness_disclosure_ref: str
    owner_user_id: str
    tutorial_asset_ref: str
    weakness_refs: tuple[str, ...]
    visible_by_default: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "weakness_refs", tuple(self.weakness_refs))

    @property
    def canonical_ref(self) -> str:
        return "weakness_disclosure:" + _digest(
            {
                "owner_user_id": self.owner_user_id,
                "tutorial_asset_ref": self.tutorial_asset_ref,
                "weakness_refs": list(self.weakness_refs),
                "visible_by_default": self.visible_by_default,
            }
        )


@dataclass(frozen=True)
class TeachingEvidenceRecord:
    teaching_evidence_ref: str
    owner_user_id: str
    tutorial_asset_ref: str
    weakness_disclosure_ref: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    @property
    def canonical_ref(self) -> str:
        return "teaching_evidence:" + _digest(
            {
                "owner_user_id": self.owner_user_id,
                "tutorial_asset_ref": self.tutorial_asset_ref,
                "weakness_disclosure_ref": self.weakness_disclosure_ref,
                "evidence_refs": list(self.evidence_refs),
            }
        )


@dataclass(frozen=True)
class TeachingAssetBundle:
    tutorial: TutorialAssetRecord
    weakness: WeaknessDisclosureRecord
    evidence: TeachingEvidenceRecord


def _validate_bundle(bundle: TeachingAssetBundle, *, owner_user_id: str) -> None:
    owner = _owner(owner_user_id)
    tutorial = bundle.tutorial
    weakness = bundle.weakness
    evidence = bundle.evidence
    if any(
        _owner(item.owner_user_id) != owner
        for item in (tutorial, weakness, evidence)
    ):
        raise ValueError("teaching bundle owner mismatch")
    if tutorial.category not in {"tutorial", "example", "template"}:
        raise ValueError("teaching asset category must be tutorial/example/template")
    if not tutorial.governed_asset_ref or not tutorial.title:
        raise ValueError("teaching asset governed ref and title are required")
    if tutorial.tutorial_asset_ref != tutorial.canonical_ref:
        raise ValueError("tutorial asset identity mismatch")
    if weakness.weakness_disclosure_ref != weakness.canonical_ref:
        raise ValueError("weakness disclosure identity mismatch")
    if evidence.teaching_evidence_ref != evidence.canonical_ref:
        raise ValueError("teaching evidence identity mismatch")
    if (
        weakness.tutorial_asset_ref != tutorial.tutorial_asset_ref
        or evidence.tutorial_asset_ref != tutorial.tutorial_asset_ref
        or evidence.weakness_disclosure_ref != weakness.weakness_disclosure_ref
    ):
        raise ValueError("teaching bundle lineage mismatch")
    if weakness.visible_by_default is not True:
        raise ValueError("teaching weaknesses must be visible by default")
    _refs(weakness.weakness_refs, "weakness_refs")
    _refs(evidence.evidence_refs, "evidence_refs")


def _bundle_to_dict(bundle: TeachingAssetBundle) -> dict[str, Any]:
    return {
        "tutorial": asdict(bundle.tutorial),
        "weakness": asdict(bundle.weakness),
        "evidence": asdict(bundle.evidence),
    }


def _bundle_from_dict(value: Any) -> TeachingAssetBundle:
    if not isinstance(value, dict) or set(value) != {"tutorial", "weakness", "evidence"}:
        raise ValueError("teaching bundle has an inexact schema")
    expected = {
        "tutorial": {
            "tutorial_asset_ref",
            "owner_user_id",
            "governed_asset_ref",
            "category",
            "title",
        },
        "weakness": {
            "weakness_disclosure_ref",
            "owner_user_id",
            "tutorial_asset_ref",
            "weakness_refs",
            "visible_by_default",
        },
        "evidence": {
            "teaching_evidence_ref",
            "owner_user_id",
            "tutorial_asset_ref",
            "weakness_disclosure_ref",
            "evidence_refs",
        },
    }
    for key, fields in expected.items():
        if not isinstance(value[key], dict) or set(value[key]) != fields:
            raise ValueError(f"teaching {key} record has an inexact schema")
    return TeachingAssetBundle(
        tutorial=TutorialAssetRecord(**value["tutorial"]),
        weakness=WeaknessDisclosureRecord(**value["weakness"]),
        evidence=TeachingEvidenceRecord(**value["evidence"]),
    )


class PersistentTeachingAssetRegistry:
    """Hash-chained current teaching catalog over governed lifecycle assets."""

    def __init__(self, path: str | Path, *, lifecycle_registry: Any) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lifecycle = lifecycle_registry
        self._thread_lock = threading.RLock()
        self._by_tutorial: dict[tuple[str, str], TeachingAssetBundle] = {}
        self._by_weakness: dict[tuple[str, str], TeachingAssetBundle] = {}
        self._by_evidence: dict[tuple[str, str], TeachingAssetBundle] = {}
        self._row_count = 0
        self._last_hash = _GENESIS
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
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

    def _reset(self) -> None:
        self._by_tutorial = {}
        self._by_weakness = {}
        self._by_evidence = {}
        self._row_count = 0
        self._last_hash = _GENESIS

    def _load(self) -> None:
        with self._thread_lock, self._exclusive():
            self._load_unlocked()

    def _load_unlocked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                self._apply(json.loads(line))
            except Exception as exc:
                raise ValueError(
                    f"invalid persisted teaching asset event at {self._path}:{line_no}"
                ) from exc

    def _apply(self, row: Any) -> None:
        fields = {
            "schema_version",
            "event_type",
            "ledger_revision",
            "previous_record_hash",
            "owner_user_id",
            "bundle",
            "record_hash",
        }
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("teaching asset event has an inexact schema")
        if row["schema_version"] != TEACHING_ASSET_SCHEMA_VERSION or row["event_type"] != _EVENT_TYPE:
            raise ValueError("teaching asset event version/type mismatch")
        if type(row["ledger_revision"]) is not int or row["ledger_revision"] != self._row_count + 1:
            raise ValueError("teaching asset ledger revision is discontinuous")
        if row["previous_record_hash"] != self._last_hash:
            raise ValueError("teaching asset previous hash mismatch")
        body = {key: value for key, value in row.items() if key != "record_hash"}
        if row["record_hash"] != _digest(body):
            raise ValueError("teaching asset record hash mismatch")
        owner = _owner(row["owner_user_id"])
        bundle = _bundle_from_dict(row["bundle"])
        _validate_bundle(bundle, owner_user_id=owner)
        keys = (
            (self._by_tutorial, (owner, bundle.tutorial.tutorial_asset_ref)),
            (self._by_weakness, (owner, bundle.weakness.weakness_disclosure_ref)),
            (self._by_evidence, (owner, bundle.evidence.teaching_evidence_ref)),
        )
        for index, key in keys:
            existing = index.get(key)
            if existing is not None and existing != bundle:
                raise ValueError("teaching asset identity collision")
            index[key] = bundle
        self._row_count = row["ledger_revision"]
        self._last_hash = row["record_hash"]

    def record_bundle(
        self,
        *,
        owner_user_id: str,
        governed_asset_ref: str,
        title: str,
        weakness_refs: tuple[str, ...] | list[str],
        evidence_refs: tuple[str, ...] | list[str],
    ) -> TeachingAssetBundle:
        owner = _owner(owner_user_id)
        asset_ref = _text(governed_asset_ref)
        resolved_title = _text(title)
        weaknesses = _refs(weakness_refs, "weakness_refs")
        evidence = _refs(evidence_refs, "evidence_refs")
        try:
            governed = self._lifecycle.governed_asset(asset_ref, owner_user_id=owner)
        except Exception as exc:
            raise ValueError("teaching governed asset is unavailable for owner") from exc
        category = _text(getattr(governed, "category", ""))
        if category not in {"tutorial", "example", "template"}:
            raise ValueError("teaching governed asset category is not tutorial/example/template")
        if not resolved_title:
            resolved_title = _text(getattr(governed, "display_label", ""))
        tutorial_blank = TutorialAssetRecord("", owner, asset_ref, category, resolved_title)
        tutorial = TutorialAssetRecord(
            tutorial_blank.canonical_ref,
            owner,
            asset_ref,
            category,
            resolved_title,
        )
        weakness_blank = WeaknessDisclosureRecord("", owner, tutorial.tutorial_asset_ref, weaknesses)
        weakness = WeaknessDisclosureRecord(
            weakness_blank.canonical_ref,
            owner,
            tutorial.tutorial_asset_ref,
            weaknesses,
        )
        evidence_blank = TeachingEvidenceRecord(
            "",
            owner,
            tutorial.tutorial_asset_ref,
            weakness.weakness_disclosure_ref,
            evidence,
        )
        teaching_evidence = TeachingEvidenceRecord(
            evidence_blank.canonical_ref,
            owner,
            tutorial.tutorial_asset_ref,
            weakness.weakness_disclosure_ref,
            evidence,
        )
        bundle = TeachingAssetBundle(tutorial, weakness, teaching_evidence)
        _validate_bundle(bundle, owner_user_id=owner)
        with self._thread_lock, self._exclusive():
            self._load_unlocked()
            current = self._by_tutorial.get((owner, tutorial.tutorial_asset_ref))
            if current is not None:
                if current != bundle:
                    raise ValueError("teaching tutorial identity collision")
                return current
            body = {
                "schema_version": TEACHING_ASSET_SCHEMA_VERSION,
                "event_type": _EVENT_TYPE,
                "ledger_revision": self._row_count + 1,
                "previous_record_hash": self._last_hash,
                "owner_user_id": owner,
                "bundle": _bundle_to_dict(bundle),
            }
            row = {**body, "record_hash": _digest(body)}
            self._atomic_replace_append(row)
            self._apply(row)
            return bundle

    def tutorial_asset(self, ref: str, *, owner_user_id: str) -> TutorialAssetRecord:
        return self._bundle("tutorial", ref, owner_user_id).tutorial

    def weakness_disclosure(
        self, ref: str, *, owner_user_id: str
    ) -> WeaknessDisclosureRecord:
        return self._bundle("weakness", ref, owner_user_id).weakness

    def teaching_evidence(
        self, ref: str, *, owner_user_id: str
    ) -> TeachingEvidenceRecord:
        return self._bundle("evidence", ref, owner_user_id).evidence

    def _bundle(
        self,
        kind: str,
        ref: str,
        owner_user_id: str,
    ) -> TeachingAssetBundle:
        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive():
            self._load_unlocked()
            index = {
                "tutorial": self._by_tutorial,
                "weakness": self._by_weakness,
                "evidence": self._by_evidence,
            }.get(kind)
            if index is None:
                raise ValueError("unknown teaching asset record kind")
            try:
                return index[(owner, _text(ref))]
            except KeyError:
                raise KeyError("teaching asset record is unavailable for owner") from None

    def bundles(self, *, owner_user_id: str) -> tuple[TeachingAssetBundle, ...]:
        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive():
            self._load_unlocked()
            return tuple(
                bundle
                for (record_owner, _), bundle in sorted(self._by_tutorial.items())
                if record_owner == owner
            )

    def _atomic_replace_append(self, row: dict[str, Any]) -> None:
        original = self._path.read_bytes() if self._path.exists() else b""
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        payload = original + separator + (_canonical(row) + "\n").encode("utf-8")
        fd, raw = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        temp = Path(raw)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            fd = -1
            os.replace(temp, self._path)
            parent_fd = os.open(self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            temp.unlink(missing_ok=True)


__all__ = [
    "TEACHING_ASSET_SCHEMA_VERSION",
    "PersistentTeachingAssetRegistry",
    "TeachingAssetBundle",
    "TeachingEvidenceRecord",
    "TutorialAssetRecord",
    "WeaknessDisclosureRecord",
]
