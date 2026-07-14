"""Durable, exact-gate reviewer authorization for model promotion gates.

These grants are authorization records, not descriptive reviewer metadata.  A
grant is bound to one owner-scoped promotion gate and one authenticated reviewer
principal.  Schema-v1/ownerless rows are quarantined; malformed schema-v2 rows
fail closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..cross_process_lock import acquire_exclusive_fd


ReviewerGrantPermission = Literal["view", "approve", "reject"]
ReviewerGrantStatus = Literal["active", "revoked"]

_SCHEMA_VERSION = 2
_ALLOWED_PERMISSIONS = frozenset({"view", "approve", "reject"})
_AUTHORIZATION_FAILURE = "promotion gate not found or reviewer not authorized"


class ReviewerGrantError(ValueError):
    """A reviewer grant request or persisted record is invalid."""


class ReviewerGrantAuthorizationError(PermissionError):
    """No current exact grant authorizes the requested reviewer operation."""


def _required(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ReviewerGrantError(f"reviewer grant {field_name} is required")
    return normalized


def _parse_utc(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReviewerGrantError(
            f"reviewer grant {field_name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReviewerGrantError(
            f"reviewer grant {field_name} must include a timezone"
        )
    return parsed.astimezone(UTC)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _canonical_hash(row: dict[str, Any]) -> str:
    material = dict(row)
    material.pop("record_hash", None)
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "model_reviewer_grant_" + hashlib.sha256(encoded).hexdigest()


def _grant_id(
    *,
    gate_id: str,
    owner_user_id: str,
    model_id: str,
    model_asset_ref: str,
    model_version: int,
    reviewer_user_id: str,
) -> str:
    encoded = json.dumps(
        {
            "gate_id": gate_id,
            "owner_user_id": owner_user_id,
            "model_id": model_id,
            "model_asset_ref": model_asset_ref,
            "model_version": model_version,
            "reviewer_user_id": reviewer_user_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "model_reviewer_grant_" + hashlib.sha256(encoded).hexdigest()


def _permissions(values: Any) -> tuple[ReviewerGrantPermission, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise ReviewerGrantError("reviewer grant permissions must be a collection")
    normalized = tuple(sorted({_required(value, "permission") for value in values}))
    if not normalized:
        raise ReviewerGrantError("reviewer grant permissions must not be empty")
    unknown = set(normalized) - _ALLOWED_PERMISSIONS
    if unknown:
        raise ReviewerGrantError(
            f"reviewer grant permissions are unsupported: {sorted(unknown)!r}"
        )
    return normalized  # type: ignore[return-value]


@dataclass(frozen=True)
class ModelReviewerGrant:
    grant_id: str
    gate_id: str
    owner_user_id: str
    model_id: str
    model_asset_ref: str
    model_version: int
    reviewer_user_id: str
    permissions: tuple[ReviewerGrantPermission, ...]
    status: ReviewerGrantStatus
    expires_at_utc: str
    issued_by: str
    issued_at_utc: str
    revoked_by: str | None
    revoked_at_utc: str | None
    revision: int
    previous_record_hash: str
    record_hash: str
    schema_version: int = _SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["permissions"] = list(self.permissions)
        return payload


class PersistentModelReviewerGrantRegistry:
    """Append-only reviewer grants with per-grant revision/hash chains."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._current: dict[str, ModelReviewerGrant] = {}
        self._legacy_quarantined_count = 0
        self._refresh()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        self._refresh()
        return self._legacy_quarantined_count

    def _acquire_file_lock(self) -> tuple[int, Any]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
        except Exception:
            os.close(fd)
            raise
        return fd, held

    def _refresh(self) -> None:
        with self._lock:
            fd, held = self._acquire_file_lock()
            try:
                self._load_existing_locked()
            finally:
                held.release()
                os.close(fd)

    def _load_existing_locked(self) -> None:
        self._current = {}
        self._legacy_quarantined_count = 0
        with self._path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ReviewerGrantError("reviewer grant row must be an object")
                    schema_version = row.get("schema_version")
                    if schema_version in {None, 1}:
                        self._legacy_quarantined_count += 1
                        continue
                    if schema_version != _SCHEMA_VERSION:
                        raise ReviewerGrantError(
                            f"unsupported reviewer grant schema_version={schema_version!r}"
                        )
                    self._apply_row(row)
                except Exception as exc:  # noqa: BLE001 - corruption must fail closed.
                    raise ReviewerGrantError(
                        f"invalid persisted reviewer grant row at {self._path}:{line_no}"
                    ) from exc

    def _apply_row(self, row: dict[str, Any]) -> ModelReviewerGrant:
        if row.get("schema_version") != _SCHEMA_VERSION:
            raise ReviewerGrantError("reviewer grants require schema_version=2")
        grant_id = _required(row.get("grant_id"), "grant_id")
        gate_id = _required(row.get("gate_id"), "gate_id")
        owner = _required(row.get("owner_user_id"), "owner_user_id")
        model_id = _required(row.get("model_id"), "model_id")
        model_asset_ref = _required(row.get("model_asset_ref"), "model_asset_ref")
        reviewer = _required(row.get("reviewer_user_id"), "reviewer_user_id")
        issued_by = _required(row.get("issued_by"), "issued_by")
        if issued_by != owner:
            raise ReviewerGrantError("reviewer grant must be issued by its owner")
        if reviewer.casefold() == owner.casefold():
            raise ReviewerGrantError("reviewer grant reviewer must differ from owner")
        version = row.get("model_version")
        if type(version) is not int or version <= 0:
            raise ReviewerGrantError("reviewer grant model_version must be positive")
        expected_grant_id = _grant_id(
            gate_id=gate_id,
            owner_user_id=owner,
            model_id=model_id,
            model_asset_ref=model_asset_ref,
            model_version=version,
            reviewer_user_id=reviewer,
        )
        if grant_id != expected_grant_id:
            raise ReviewerGrantError("reviewer grant id does not match exact identity")
        permissions = _permissions(row.get("permissions"))
        status = row.get("status")
        if status not in {"active", "revoked"}:
            raise ReviewerGrantError("reviewer grant status is invalid")
        expires_at = _required(row.get("expires_at_utc"), "expires_at_utc")
        _parse_utc(expires_at, "expires_at_utc")
        issued_at = _required(row.get("issued_at_utc"), "issued_at_utc")
        _parse_utc(issued_at, "issued_at_utc")
        revoked_by = row.get("revoked_by")
        revoked_at = row.get("revoked_at_utc")
        if status == "active":
            if revoked_by is not None or revoked_at is not None:
                raise ReviewerGrantError("active reviewer grant cannot have revocation fields")
        else:
            if _required(revoked_by, "revoked_by") != owner:
                raise ReviewerGrantError("reviewer grant must be revoked by its owner")
            _parse_utc(_required(revoked_at, "revoked_at_utc"), "revoked_at_utc")
        revision = row.get("revision")
        if type(revision) is not int or revision <= 0:
            raise ReviewerGrantError("reviewer grant revision must be positive")
        previous_hash = str(row.get("previous_record_hash") or "").strip()
        record_hash = _required(row.get("record_hash"), "record_hash")
        if record_hash != _canonical_hash(row):
            raise ReviewerGrantError("reviewer grant record hash does not match content")
        current = self._current.get(grant_id)
        if current is None:
            if revision != 1 or previous_hash:
                raise ReviewerGrantError(
                    "first reviewer grant revision must be 1 with no previous hash"
                )
        else:
            if current.status == "revoked":
                raise ReviewerGrantError("revoked reviewer grant cannot be reactivated")
            if revision != current.revision + 1:
                raise ReviewerGrantError("reviewer grant revision chain is stale or forked")
            if previous_hash != current.record_hash:
                raise ReviewerGrantError("reviewer grant previous hash does not match current head")
        grant = ModelReviewerGrant(
            grant_id=grant_id,
            gate_id=gate_id,
            owner_user_id=owner,
            model_id=model_id,
            model_asset_ref=model_asset_ref,
            model_version=version,
            reviewer_user_id=reviewer,
            permissions=permissions,
            status=status,
            expires_at_utc=expires_at,
            issued_by=issued_by,
            issued_at_utc=issued_at,
            revoked_by=revoked_by,
            revoked_at_utc=revoked_at,
            revision=revision,
            previous_record_hash=previous_hash,
            record_hash=record_hash,
        )
        self._current[grant_id] = grant
        return grant

    def _append_locked(self, row: dict[str, Any]) -> ModelReviewerGrant:
        row["record_hash"] = _canonical_hash(row)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        directory_fd = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return self._apply_row(row)

    def issue_grant(
        self,
        *,
        gate_id: str,
        owner_user_id: str,
        model_id: str,
        model_asset_ref: str,
        model_version: int,
        reviewer_user_id: str,
        permissions: tuple[ReviewerGrantPermission, ...],
        expires_at_utc: str,
        issued_by: str,
        expected_record_hash: str | None = None,
    ) -> ModelReviewerGrant:
        gate = _required(gate_id, "gate_id")
        owner = _required(owner_user_id, "owner_user_id")
        model = _required(model_id, "model_id")
        asset = _required(model_asset_ref, "model_asset_ref")
        reviewer = _required(reviewer_user_id, "reviewer_user_id")
        actor = _required(issued_by, "issued_by")
        if actor != owner:
            raise ReviewerGrantError("only the exact owner can issue a reviewer grant")
        if reviewer.casefold() == owner.casefold():
            raise ReviewerGrantError("reviewer must differ from owner")
        if type(model_version) is not int or model_version <= 0:
            raise ReviewerGrantError("reviewer grant model_version must be positive")
        allowed = _permissions(permissions)
        expires = _parse_utc(
            _required(expires_at_utc, "expires_at_utc"),
            "expires_at_utc",
        )
        if expires <= _now_utc():
            raise ReviewerGrantError("reviewer grant expiry must be in the future")
        grant_id = _grant_id(
            gate_id=gate,
            owner_user_id=owner,
            model_id=model,
            model_asset_ref=asset,
            model_version=model_version,
            reviewer_user_id=reviewer,
        )
        with self._lock:
            fd, held = self._acquire_file_lock()
            try:
                self._load_existing_locked()
                current = self._current.get(grant_id)
                expected = str(expected_record_hash or "").strip()
                if current is not None:
                    if current.status == "revoked":
                        raise ReviewerGrantError("revoked reviewer grant cannot be reissued")
                    if expected != current.record_hash:
                        raise ReviewerGrantError("reviewer grant expected_record_hash is stale")
                    revision = current.revision + 1
                    previous_hash = current.record_hash
                else:
                    if expected:
                        raise ReviewerGrantError("reviewer grant expected_record_hash is stale")
                    revision = 1
                    previous_hash = ""
                row = {
                    "schema_version": _SCHEMA_VERSION,
                    "grant_id": grant_id,
                    "gate_id": gate,
                    "owner_user_id": owner,
                    "model_id": model,
                    "model_asset_ref": asset,
                    "model_version": model_version,
                    "reviewer_user_id": reviewer,
                    "permissions": list(allowed),
                    "status": "active",
                    "expires_at_utc": expires.isoformat(),
                    "issued_by": actor,
                    "issued_at_utc": _now_utc().isoformat(),
                    "revoked_by": None,
                    "revoked_at_utc": None,
                    "revision": revision,
                    "previous_record_hash": previous_hash,
                }
                return self._append_locked(row)
            finally:
                held.release()
                os.close(fd)

    def revoke_grant(
        self,
        grant_id: str,
        *,
        owner_user_id: str,
        revoked_by: str,
        expected_record_hash: str,
    ) -> ModelReviewerGrant:
        identity = _required(grant_id, "grant_id")
        owner = _required(owner_user_id, "owner_user_id")
        actor = _required(revoked_by, "revoked_by")
        if actor != owner:
            raise ReviewerGrantError("only the exact owner can revoke a reviewer grant")
        expected = _required(expected_record_hash, "expected_record_hash")
        with self._lock:
            fd, held = self._acquire_file_lock()
            try:
                self._load_existing_locked()
                current = self._current.get(identity)
                if current is None or current.owner_user_id != owner:
                    raise ReviewerGrantError("reviewer grant not found for owner")
                if current.record_hash != expected:
                    raise ReviewerGrantError("reviewer grant expected_record_hash is stale")
                if current.status != "active":
                    raise ReviewerGrantError("reviewer grant is not active")
                row = current.to_dict()
                row.update(
                    {
                        "status": "revoked",
                        "revoked_by": actor,
                        "revoked_at_utc": _now_utc().isoformat(),
                        "revision": current.revision + 1,
                        "previous_record_hash": current.record_hash,
                    }
                )
                row.pop("record_hash", None)
                return self._append_locked(row)
            finally:
                held.release()
                os.close(fd)

    def get_for_owner(
        self,
        grant_id: str,
        *,
        owner_user_id: str,
    ) -> ModelReviewerGrant:
        identity = _required(grant_id, "grant_id")
        owner = _required(owner_user_id, "owner_user_id")
        self._refresh()
        current = self._current.get(identity)
        if current is None or current.owner_user_id != owner:
            raise KeyError("reviewer grant not found for owner")
        return current

    def authorize(
        self,
        *,
        gate_id: str,
        owner_user_id: str,
        model_id: str,
        model_asset_ref: str,
        model_version: int,
        reviewer_user_id: str,
        permission: ReviewerGrantPermission,
        now_utc: datetime | None = None,
    ) -> ModelReviewerGrant:
        with self.authorization(
            gate_id=gate_id,
            owner_user_id=owner_user_id,
            model_id=model_id,
            model_asset_ref=model_asset_ref,
            model_version=model_version,
            reviewer_user_id=reviewer_user_id,
            permission=permission,
            now_utc=now_utc,
        ) as current:
            return current

    @contextmanager
    def authorization(
        self,
        *,
        gate_id: str,
        owner_user_id: str,
        model_id: str,
        model_asset_ref: str,
        model_version: int,
        reviewer_user_id: str,
        permission: ReviewerGrantPermission,
        now_utc: datetime | None = None,
    ) -> Iterator[ModelReviewerGrant]:
        """Hold the durable grant lock through one protected operation.

        This makes a reviewer decision and owner revocation serializable: a
        revocation that wins the lock first blocks the decision, while a decision
        that wins first completes before the revocation is recorded.
        """

        gate = _required(gate_id, "gate_id")
        owner = _required(owner_user_id, "owner_user_id")
        model = _required(model_id, "model_id")
        asset = _required(model_asset_ref, "model_asset_ref")
        reviewer = _required(reviewer_user_id, "reviewer_user_id")
        if permission not in _ALLOWED_PERMISSIONS:
            raise ReviewerGrantError(f"unsupported reviewer permission={permission!r}")
        if type(model_version) is not int or model_version <= 0:
            raise ReviewerGrantError("reviewer grant model_version must be positive")
        identity = _grant_id(
            gate_id=gate,
            owner_user_id=owner,
            model_id=model,
            model_asset_ref=asset,
            model_version=model_version,
            reviewer_user_id=reviewer,
        )
        supplied_now = now_utc or _now_utc()
        if supplied_now.tzinfo is None or supplied_now.utcoffset() is None:
            raise ReviewerGrantError("reviewer authorization time must include a timezone")
        when = supplied_now.astimezone(UTC)
        with self._lock:
            fd, held = self._acquire_file_lock()
            try:
                self._load_existing_locked()
                current = self._current.get(identity)
                if (
                    current is None
                    or current.status != "active"
                    or permission not in current.permissions
                    or _parse_utc(current.expires_at_utc, "expires_at_utc") <= when
                ):
                    raise ReviewerGrantAuthorizationError(_AUTHORIZATION_FAILURE)
                yield current
            finally:
                held.release()
                os.close(fd)


__all__ = [
    "ModelReviewerGrant",
    "PersistentModelReviewerGrantRegistry",
    "ReviewerGrantAuthorizationError",
    "ReviewerGrantError",
    "ReviewerGrantPermission",
    "ReviewerGrantStatus",
]
