"""Owner-scoped encrypted LLM fixture store with durable replay audit.

The JSONL metadata contains hashes/refs plus AES-GCM ciphertext. Prompt text,
provider output, tool arguments, run ids, and owner ids are never serialized in
plaintext. The local key is still a same-machine key: this is encryption at rest
and tamper detection, not protection from a process that can read the key file.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ...cross_process_lock import acquire_exclusive_fd
from ...lineage.ids import canonical_json
from .fixture import LLMFixture, compute_hmac, is_alias_model_id, owner_scope_ref, verify_hmac

FIXTURES_FILENAME = "fixtures.jsonl"
AUDIT_FILENAME = "replay_audit.jsonl"
HMAC_KEY_FILENAME = "hmac.key"
LOCK_FILENAME = ".replay.lock"
FIXTURES_HEAD_FILENAME = "fixtures.head.json"
AUDIT_HEAD_FILENAME = "replay_audit.head.json"
STORAGE_VERSION = 2
CHECKPOINT_VERSION = 1
PAYLOAD_ALGORITHM = "AES-256-GCM"
_AUDIT_EVENTS = frozenset({"replay_hit", "replay_miss"})
_PAYLOAD_FIELDS = frozenset({"payload_alg", "payload_nonce", "payload_ciphertext"})


class IntegrityError(Exception):
    """Fixture/audit authentication failed; dirty data is never returned."""


class FixtureConflict(Exception):
    """The same owner-scoped fixture key was written with different content."""


class ReplayMiss(Exception):
    """Replay mode missed and must not fall back to a live provider."""


class OwnerScopeError(Exception):
    """A persisted replay operation did not carry a non-empty authenticated owner."""


EventSink = Callable[[str, dict[str, Any]], None]


def _owner(value: str) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise OwnerScopeError("owner_user_id is required for persisted replay operations")
    return owner


def _run_ref(run_id: str) -> str:
    digest = hashlib.sha256(str(run_id or "").encode("utf-8")).hexdigest()
    return f"runref:{digest[:32]}"


class FixtureStore:
    def __init__(self, root: Path | str, *, hmac_key: bytes | None = None, on_event: EventSink | None = None) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / FIXTURES_FILENAME
        self._audit_path = self._root / AUDIT_FILENAME
        self._fixtures_head_path = self._root / FIXTURES_HEAD_FILENAME
        self._audit_head_path = self._root / AUDIT_HEAD_FILENAME
        self._lock_path = self._root / LOCK_FILENAME
        self._lock = threading.RLock()
        self._on_event = on_event
        # Every index key includes the non-plaintext owner scope.
        self._rows_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._latest: dict[tuple[str, str], dict[str, Any]] = {}
        self._distinct: set[tuple[str, str]] = set()
        self._consumed: set[tuple[str, str]] = set()
        self._last_fp: dict[tuple[str, str, str], str | None] = {}
        self._corrupt_lines = 0
        self._poisoned = False
        # Key creation and initial replay share the same process lock as every
        # later write. Two workers can therefore never create different keys
        # for one store or build an index across a half-written append.
        with self._process_lock():
            self._key = hmac_key if hmac_key is not None else self._load_or_create_key()
            self._prepare_journal(self._path, self._fixtures_head_path)
            self._prepare_journal(self._audit_path, self._audit_head_path)
            self._replay_index(reset=True)
            self._verified_journal_bytes(self._audit_path, self._audit_head_path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def audit_path(self) -> Path:
        return self._audit_path

    def _load_or_create_key(self) -> bytes:
        kp = self._root / HMAC_KEY_FILENAME
        try:
            existing = os.lstat(kp)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            self._require_secure_stat(kp, existing, label="replay key")
            fd = os.open(kp, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                self._require_secure_stat(kp, os.fstat(fd), label="replay key")
                raw_text = self._read_all(fd).decode("ascii").strip()
            finally:
                os.close(fd)
            try:
                raw = bytes.fromhex(raw_text)
            except ValueError as exc:
                raise IntegrityError(f"invalid replay key encoding at {kp}") from exc
            if len(raw) != 32:
                raise IntegrityError(f"invalid replay key length at {kp}")
            return raw
        key = secrets.token_bytes(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(kp, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            self._write_all(fd, key.hex().encode("ascii"))
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(kp)
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(fd)
        self._fsync_parent()
        return key

    @staticmethod
    def _read_all(fd: int) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError("short write while persisting replay state")
            offset += written

    @staticmethod
    def _require_secure_stat(path: Path, file_stat: os.stat_result, *, label: str) -> None:
        if not stat.S_ISREG(file_stat.st_mode):
            raise IntegrityError(f"{label} must be a regular non-symlink file: {path}")
        if file_stat.st_uid != os.geteuid():
            raise IntegrityError(f"{label} owner mismatch at {path}")
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise IntegrityError(f"{label} mode must be 0600 at {path}")

    def _ensure_secure_file(self, path: Path, *, permit_legacy_mode_fix: bool) -> None:
        try:
            file_stat = os.lstat(path)
        except FileNotFoundError:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                os.fchmod(fd, 0o600)
                os.fsync(fd)
            finally:
                os.close(fd)
            self._fsync_parent()
            return
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise IntegrityError(f"replay journal must be a regular non-symlink file: {path}")
        if file_stat.st_uid != os.geteuid():
            raise IntegrityError(f"replay journal owner mismatch at {path}")
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            if not permit_legacy_mode_fix:
                raise IntegrityError(f"replay journal mode must be 0600 at {path}")
            fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fchmod(fd, 0o600)
                os.fsync(fd)
            finally:
                os.close(fd)
            self._fsync_parent()

    def _fsync_parent(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        fd = os.open(self._root, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _prepare_journal(self, journal_path: Path, head_path: Path) -> None:
        # Journals from the previous schema did not have durable heads and were
        # commonly created with the process umask. Tighten their mode exactly
        # once, before adopting their current bytes into the first checkpoint.
        try:
            os.lstat(head_path)
            head_exists = True
        except FileNotFoundError:
            head_exists = False
        self._ensure_secure_file(journal_path, permit_legacy_mode_fix=not head_exists)
        if head_exists:
            self._verified_journal_bytes(journal_path, head_path)
            return
        self._atomic_replace_bytes(head_path, self._checkpoint_bytes(journal_path, journal_path.read_bytes()))

    def _checkpoint_body(self, journal_path: Path, payload: bytes) -> dict[str, Any]:
        return {
            "checkpoint_version": CHECKPOINT_VERSION,
            "journal": journal_path.name,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def _checkpoint_bytes(self, journal_path: Path, payload: bytes) -> bytes:
        body = self._checkpoint_body(journal_path, payload)
        domain = b"replay-journal-head\x00" + journal_path.name.encode("utf-8") + b"\x00"
        integrity = hmac.new(
            self._key,
            domain + canonical_json(body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return (json.dumps({**body, "integrity": integrity}, sort_keys=True) + "\n").encode("utf-8")

    def _read_checkpoint(self, journal_path: Path, head_path: Path) -> tuple[dict[str, Any], bytes]:
        try:
            head_stat = os.lstat(head_path)
        except FileNotFoundError as exc:
            raise IntegrityError(f"missing durable replay checkpoint: {head_path}") from exc
        self._require_secure_stat(head_path, head_stat, label="replay checkpoint")
        raw = head_path.read_bytes()
        try:
            row = json.loads(raw.decode("utf-8"))
            integrity = str(row.pop("integrity"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise IntegrityError(f"invalid replay checkpoint: {head_path}") from exc
        domain = b"replay-journal-head\x00" + journal_path.name.encode("utf-8") + b"\x00"
        expected = hmac.new(
            self._key,
            domain + canonical_json(row).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, integrity):
            raise IntegrityError(f"replay checkpoint HMAC failed: {head_path}")
        if row.get("checkpoint_version") != CHECKPOINT_VERSION or row.get("journal") != journal_path.name:
            raise IntegrityError(f"replay checkpoint identity failed: {head_path}")
        return row, raw

    def _verified_journal_bytes(self, journal_path: Path, head_path: Path) -> bytes:
        if self._poisoned:
            raise IntegrityError("replay store is fail-closed after an incomplete durability rollback")
        journal_stat = os.lstat(journal_path)
        self._require_secure_stat(journal_path, journal_stat, label="replay journal")
        checkpoint, _raw = self._read_checkpoint(journal_path, head_path)
        payload = journal_path.read_bytes()
        if checkpoint.get("size") != len(payload):
            raise IntegrityError(f"replay journal size diverged from checkpoint: {journal_path}")
        digest = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(str(checkpoint.get("sha256") or ""), digest):
            raise IntegrityError(f"replay journal digest diverged from checkpoint: {journal_path}")
        return payload

    def _atomic_replace_bytes(self, path: Path, payload: bytes) -> None:
        temp = self._root / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temp, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            self._write_all(fd, payload)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(fd)
        try:
            os.replace(temp, path)
            self._fsync_parent()
        except BaseException:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
            raise

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(event, payload)

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        fd = os.open(
            self._lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        held = None
        try:
            lock_stat = os.fstat(fd)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.geteuid():
                raise IntegrityError(f"replay lock must be an owned regular file: {self._lock_path}")
            if stat.S_IMODE(lock_stat.st_mode) != 0o600:
                os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _payload_key(self, owner_user_id: str) -> bytes:
        owner = _owner(owner_user_id)
        return hmac.new(self._key, b"fixture-payload\x00" + owner.encode("utf-8"), hashlib.sha256).digest()

    @staticmethod
    def _aad(metadata: dict[str, Any]) -> bytes:
        return canonical_json({"storage_version": STORAGE_VERSION, **metadata}).encode("utf-8")

    def _storage_row(self, fixture: LLMFixture, owner_user_id: str) -> dict[str, Any]:
        owner = _owner(owner_user_id)
        expected_owner_ref = owner_scope_ref(owner)
        if fixture.owner_ref and fixture.owner_ref != expected_owner_ref:
            raise OwnerScopeError("fixture owner scope does not match the persisted operation owner")
        fixture.owner_ref = expected_owner_ref
        fixture.integrity = compute_hmac(fixture, self._key)
        metadata = fixture.to_dict()
        plaintext = canonical_json(fixture.sensitive_payload()).encode("utf-8")
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._payload_key(owner)).encrypt(nonce, plaintext, self._aad(metadata))
        return {
            "storage_version": STORAGE_VERSION,
            **metadata,
            "payload_alg": PAYLOAD_ALGORITHM,
            "payload_nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "payload_ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        }

    def _decode_row(self, row: dict[str, Any], owner_user_id: str) -> LLMFixture:
        owner = _owner(owner_user_id)
        expected_owner_ref = owner_scope_ref(owner)
        if row.get("storage_version") != STORAGE_VERSION:
            raise IntegrityError("legacy/plaintext fixture row rejected; encrypted storage_version=2 required")
        if row.get("owner_ref") != expected_owner_ref:
            raise OwnerScopeError("fixture does not belong to this owner")
        if row.get("payload_alg") != PAYLOAD_ALGORITHM:
            raise IntegrityError("unsupported fixture payload algorithm")
        metadata = {k: v for k, v in row.items() if k not in _PAYLOAD_FIELDS and k != "storage_version"}
        try:
            nonce = base64.urlsafe_b64decode(str(row["payload_nonce"]).encode("ascii"))
            ciphertext = base64.urlsafe_b64decode(str(row["payload_ciphertext"]).encode("ascii"))
            plaintext = AESGCM(self._payload_key(owner)).decrypt(nonce, ciphertext, self._aad(metadata))
            payload = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise IntegrityError("fixture ciphertext or authenticated metadata was tampered") from exc
        fixture = LLMFixture(
            fixture_key=str(metadata.get("fixture_key") or ""),
            run_id=str(payload.get("run_id") or ""),
            repro_level=str(metadata.get("repro_level") or ""),
            model_pin=dict(metadata.get("model_pin") or {}),
            request=dict(payload.get("request") or {}),
            response=dict(payload.get("response") or {}),
            tool_calls=list(payload.get("tool_calls") or []),
            translation_status=str(metadata.get("translation_status") or ""),
            owner_ref=expected_owner_ref,
            schema_ref=metadata.get("schema_ref"),
            decision_authority=str(metadata.get("decision_authority") or "none"),
            created_at_utc=str(metadata.get("created_at_utc") or ""),
            integrity=str(metadata.get("integrity") or ""),
            consumed=bool(metadata.get("consumed")),
            tombstoned=bool(metadata.get("tombstoned")),
        )
        if not verify_hmac(fixture, self._key):
            raise IntegrityError("fixture HMAC verification failed")
        return fixture

    def _append_row(self, row: dict[str, Any]) -> None:
        payload = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self._transactional_append(self._path, self._fixtures_head_path, payload)

    def _restore_transaction(
        self,
        journal_path: Path,
        head_path: Path,
        *,
        prior_journal: bytes,
        prior_head: bytes,
    ) -> list[str]:
        errors: list[str] = []
        try:
            if journal_path.read_bytes() != prior_journal:
                fd = os.open(journal_path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.ftruncate(fd, 0)
                    self._write_all(fd, prior_journal)
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except BaseException as exc:  # noqa: BLE001 - preserve every durability failure in fail-closed state.
            errors.append(f"journal restore: {type(exc).__name__}: {exc}")
        try:
            if not head_path.exists() or head_path.read_bytes() != prior_head:
                self._atomic_replace_bytes(head_path, prior_head)
        except BaseException as exc:  # noqa: BLE001 - preserve every durability failure in fail-closed state.
            errors.append(f"checkpoint restore: {type(exc).__name__}: {exc}")
        try:
            # Byte equality is useful even if an injected fsync failure made
            # durability unprovable; the instance remains poisoned below.
            if journal_path.read_bytes() != prior_journal or head_path.read_bytes() != prior_head:
                errors.append("restored bytes do not match the pre-append state")
        except BaseException as exc:  # noqa: BLE001
            errors.append(f"rollback verification: {type(exc).__name__}: {exc}")
        return errors

    def _transactional_append(self, journal_path: Path, head_path: Path, payload: bytes) -> None:
        prior_journal = self._verified_journal_bytes(journal_path, head_path)
        _checkpoint, prior_head = self._read_checkpoint(journal_path, head_path)
        fd = -1
        try:
            fd = os.open(
                journal_path,
                os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
            )
            self._require_secure_stat(journal_path, os.fstat(fd), label="replay journal")
            self._write_all(fd, payload)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            updated = prior_journal + payload
            self._atomic_replace_bytes(head_path, self._checkpoint_bytes(journal_path, updated))
            # Re-read both surfaces before exposing success to the caller.
            if self._verified_journal_bytes(journal_path, head_path) != updated:
                raise IntegrityError(f"replay append postcondition failed: {journal_path}")
        except BaseException as exc:
            if fd >= 0:
                os.close(fd)
            rollback_errors = self._restore_transaction(
                journal_path,
                head_path,
                prior_journal=prior_journal,
                prior_head=prior_head,
            )
            if rollback_errors:
                self._poisoned = True
                raise IntegrityError(
                    "replay append failed and rollback durability is unverified; "
                    + "; ".join(rollback_errors)
                ) from exc
            raise

    def _replay_index(self, *, reset: bool = False) -> None:
        if reset:
            self._rows_by_key.clear()
            self._latest.clear()
            self._distinct.clear()
            self._consumed.clear()
            self._last_fp.clear()
            self._corrupt_lines = 0
        try:
            lines = self._verified_journal_bytes(self._path, self._fixtures_head_path).decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise IntegrityError(f"fixture journal is not UTF-8: {self._path}") from exc
        n = len(lines)
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                self._corrupt_lines += 1
                self._emit("fixture_line_corrupt", {"line": i, "is_tail": i == n - 1})
                continue
            if row.get("storage_version") != STORAGE_VERSION or not row.get("owner_ref") or not row.get("payload_ciphertext"):
                # Old rows may contain plaintext. Never index or replay them silently.
                self._corrupt_lines += 1
                self._emit("fixture_legacy_plaintext_rejected", {"line": i})
                continue
            key = str(row.get("fixture_key") or "")
            owner_ref = str(row.get("owner_ref") or "")
            if not key:
                self._corrupt_lines += 1
                self._emit("fixture_line_corrupt", {"line": i, "reason": "no fixture_key"})
                continue
            scoped_key = (owner_ref, key)
            self._rows_by_key.setdefault(scoped_key, []).append(row)
            self._latest[scoped_key] = row
            self._distinct.add(scoped_key)
            if row.get("consumed"):
                self._consumed.add(scoped_key)
            pin = row.get("model_pin") if isinstance(row.get("model_pin"), dict) else {}
            provider = str(pin.get("provider") or "")
            model_id = str(pin.get("model_id") or "")
            if provider or model_id:
                self._last_fp[(owner_ref, provider, model_id)] = pin.get("system_fingerprint")

    def _valid_from_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        owner_user_id: str,
        fixture_key: str,
    ) -> LLMFixture:
        if not rows:
            raise IntegrityError(f"fixture_key={fixture_key} has no authenticated row")
        try:
            return self._decode_row(rows[-1], owner_user_id)
        except IntegrityError as exc:
            self._emit(
                "integrity_violation",
                {"fixture_key": fixture_key, "detail": "latest row failed authentication; replay rejected"},
            )
            raise IntegrityError(f"fixture_key={fixture_key} latest row failed authentication") from exc

    # ── writes ──
    def put(self, fixture: LLMFixture, *, owner_user_id: str) -> LLMFixture:
        owner = _owner(owner_user_id)
        owner_ref = owner_scope_ref(owner)
        scoped_key = (owner_ref, fixture.fixture_key)
        with self._lock, self._process_lock():
            self._replay_index(reset=True)
            existing = self._rows_by_key.get(scoped_key, [])
            if existing:
                current = self._valid_from_rows(existing, owner_user_id=owner, fixture_key=fixture.fixture_key)
                fixture.owner_ref = owner_ref
                if current.signing_payload() == fixture.signing_payload():
                    return current
                raise FixtureConflict(
                    f"fixture_key={fixture.fixture_key} already exists with different owner-scoped content"
                )
            fixture.owner_ref = owner_ref
            pin = fixture.model_pin or {}
            prov, mid = str(pin.get("provider", "")), str(pin.get("model_id", ""))
            fp = pin.get("system_fingerprint")
            if is_alias_model_id(mid):
                self._emit("model_id_is_alias", {"fixture_key": fixture.fixture_key, "model_id": mid})
            model_key = (owner_ref, prov, mid)
            if model_key in self._last_fp and self._last_fp[model_key] != fp:
                self._emit(
                    "fingerprint_drift",
                    {"fixture_key": fixture.fixture_key, "provider": prov, "model_id": mid,
                     "from": self._last_fp[model_key], "to": fp},
                )
            self._last_fp[model_key] = fp
            row = self._storage_row(fixture, owner)
            self._append_row(row)
            self._rows_by_key.setdefault(scoped_key, []).append(row)
            self._latest[scoped_key] = row
            self._distinct.add(scoped_key)
            return fixture

    def tombstone(self, fixture_key: str, *, owner_user_id: str) -> None:
        owner = _owner(owner_user_id)
        scoped_key = (owner_scope_ref(owner), fixture_key)
        with self._lock, self._process_lock():
            self._replay_index(reset=True)
            rows = self._rows_by_key.get(scoped_key, [])
            if not rows:
                raise KeyError(f"fixture not found: {fixture_key}")
            fixture = self._valid_from_rows(rows, owner_user_id=owner, fixture_key=fixture_key)
            fixture.tombstoned = True
            row = self._storage_row(fixture, owner)
            self._append_row(row)
            self._rows_by_key[scoped_key].append(row)
            self._latest[scoped_key] = row

    def consume(self, fixture_key: str, *, owner_user_id: str) -> None:
        owner = _owner(owner_user_id)
        scoped_key = (owner_scope_ref(owner), fixture_key)
        with self._lock, self._process_lock():
            self._replay_index(reset=True)
            if scoped_key in self._consumed:
                self._emit("consumed_again", {"fixture_key": fixture_key})
                return
            rows = self._rows_by_key.get(scoped_key, [])
            if not rows:
                raise KeyError(f"fixture not found: {fixture_key}")
            fixture = self._valid_from_rows(rows, owner_user_id=owner, fixture_key=fixture_key)
            fixture.consumed = True
            row = self._storage_row(fixture, owner)
            self._append_row(row)
            self._rows_by_key[scoped_key].append(row)
            self._latest[scoped_key] = row
            self._consumed.add(scoped_key)

    # ── reads ──
    def get(self, fixture_key: str, *, owner_user_id: str) -> LLMFixture:
        owner = _owner(owner_user_id)
        scoped_key = (owner_scope_ref(owner), fixture_key)
        with self._lock, self._process_lock():
            self._replay_index(reset=True)
            rows = list(self._rows_by_key.get(scoped_key, []))
        if not rows:
            raise KeyError(f"fixture not found: {fixture_key}")
        return self._valid_from_rows(rows, owner_user_id=owner, fixture_key=fixture_key)

    def get_optional(self, fixture_key: str, *, owner_user_id: str) -> LLMFixture | None:
        owner = _owner(owner_user_id)
        scoped_key = (owner_scope_ref(owner), fixture_key)
        with self._lock, self._process_lock():
            self._replay_index(reset=True)
            present = scoped_key in self._latest
            rows = list(self._rows_by_key.get(scoped_key, []))
        return (
            self._valid_from_rows(rows, owner_user_id=owner, fixture_key=fixture_key)
            if present
            else None
        )

    def distinct_count(self, *, owner_user_id: str) -> int:
        owner_ref = owner_scope_ref(_owner(owner_user_id))
        with self._lock, self._process_lock():
            self._replay_index(reset=True)
            return sum(1 for scope, _key in self._distinct if scope == owner_ref)

    # ── durable replay hit/miss audit ──
    def record_replay_event(
        self,
        event: str,
        *,
        owner_user_id: str,
        fixture_key: str,
        run_id: str,
    ) -> dict[str, Any]:
        owner = _owner(owner_user_id)
        if event not in _AUDIT_EVENTS:
            raise ValueError(f"unsupported replay audit event: {event}")
        at = datetime.now(UTC).isoformat()
        body = {
            "event_id": "replayevt:" + secrets.token_hex(12),
            "event": event,
            "owner_ref": owner_scope_ref(owner),
            "fixture_key": str(fixture_key),
            "run_ref": _run_ref(run_id),
            "at": at,
        }
        integrity = hmac.new(self._key, canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()
        row = {**body, "integrity": integrity}
        with self._lock, self._process_lock():
            payload = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            self._transactional_append(self._audit_path, self._audit_head_path, payload)
        self._emit(event, {k: v for k, v in body.items() if k != "owner_ref"})
        return dict(row)

    def replay_events(self, *, owner_user_id: str) -> tuple[dict[str, Any], ...]:
        owner_ref = owner_scope_ref(_owner(owner_user_id))
        with self._lock, self._process_lock():
            try:
                lines = self._verified_journal_bytes(
                    self._audit_path,
                    self._audit_head_path,
                ).decode("utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise IntegrityError(f"replay audit journal is not UTF-8: {self._audit_path}") from exc
        out: list[dict[str, Any]] = []
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                integrity = str(row.pop("integrity"))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise IntegrityError(f"invalid replay audit row at line {line_no}") from exc
            expected = hmac.new(self._key, canonical_json(row).encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, integrity):
                raise IntegrityError(f"replay audit integrity failed at line {line_no}")
            if row.get("owner_ref") == owner_ref:
                out.append({**row, "integrity": integrity})
        return tuple(out)


__all__ = [
    "AUDIT_FILENAME",
    "FIXTURES_FILENAME",
    "FixtureConflict",
    "FixtureStore",
    "IntegrityError",
    "LOCK_FILENAME",
    "OwnerScopeError",
    "ReplayMiss",
]
