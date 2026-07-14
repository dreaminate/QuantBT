"""Durable, owner-bound verification receipts for successful IDE promotion.

The public write API accepts promotion identities only.  All proof fields come
from a server-owned ``verification_loader`` and are reloaded during validation;
caller-controlled sandbox output or producer-status values therefore cannot
mint or refresh a receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeAlias

from ..cross_process_lock import acquire_exclusive_fd
from ..release_gate.section6_mathchain_gate import (
    SECTION6_MATHCHAIN_GATE_NAME,
    SECTION6_MATHCHAIN_MANIFEST_KEY,
    SECTION6_MATHCHAIN_PRODUCER_KEY,
)
from ..release_gate.section9_boundary_gate import (
    SECTION9_BOUNDARY_GATE_NAME,
    SECTION9_BOUNDARY_MANIFEST_KEY,
    SECTION9_BOUNDARY_PRODUCER_KEY,
)
from ..release_gate.section10_methodology_gate import (
    SECTION10_CONTROLPLANE_GATE_NAME,
    SECTION10_CONTROLPLANE_MANIFEST_KEY,
    SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION10_COST_GATE_NAME,
    SECTION10_COST_MANIFEST_KEY,
    SECTION10_COST_PRODUCER_KEY,
)
from ..release_gate.section13_trust_gate import (
    SECTION13_TRUST_GATE_NAME,
    SECTION13_TRUST_MANIFEST_KEY,
    SECTION13_TRUST_PRODUCER_KEY,
)
from ..release_gate.section16_engineering_standards_gate import (
    SECTION16_ENGINEERING_STANDARDS_GATE_NAME,
    SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
    SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
)
from ..release_gate.section17_rdp_gate import (
    SECTION17_RDP_GATE_NAME,
    SECTION17_RDP_MANIFEST_KEY,
    SECTION17_RDP_PRODUCER_KEY,
)


RECEIPT_VERSION = "ide_promotion_verification_receipt.v1"
RECEIPT_PREFIX = "ide_promotion_receipt:"
GENERATED_ARTIFACT_INVENTORY_KEY = "generated_artifact_inventory"
GENERATED_ARTIFACT_NAMES = (
    "portfolio.csv",
    "trades.csv",
    "attribution.csv",
    "strategy.py",
)
REQUIRED_GENERATED_ARTIFACT_NAMES = ("portfolio.csv",)


_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


def _shared_process_lock(path: Path) -> threading.RLock:
    """Return one thread lock for every process-local view of a ledger lock."""

    key = os.path.abspath(os.fspath(path))
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())

# A promotion receipt proves the complete currently registered gate family, not
# an arbitrary green subset selected by a caller or loader implementation.
EXPECTED_GATE_BINDINGS: tuple[tuple[str, str, str, str], ...] = (
    (
        "6",
        SECTION6_MATHCHAIN_MANIFEST_KEY,
        SECTION6_MATHCHAIN_PRODUCER_KEY,
        SECTION6_MATHCHAIN_GATE_NAME,
    ),
    (
        "9",
        SECTION9_BOUNDARY_MANIFEST_KEY,
        SECTION9_BOUNDARY_PRODUCER_KEY,
        SECTION9_BOUNDARY_GATE_NAME,
    ),
    (
        "10_cost",
        SECTION10_COST_MANIFEST_KEY,
        SECTION10_COST_PRODUCER_KEY,
        SECTION10_COST_GATE_NAME,
    ),
    (
        "10_control_plane",
        SECTION10_CONTROLPLANE_MANIFEST_KEY,
        SECTION10_CONTROLPLANE_PRODUCER_KEY,
        SECTION10_CONTROLPLANE_GATE_NAME,
    ),
    (
        "13",
        SECTION13_TRUST_MANIFEST_KEY,
        SECTION13_TRUST_PRODUCER_KEY,
        SECTION13_TRUST_GATE_NAME,
    ),
    (
        "16",
        SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
        SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
        SECTION16_ENGINEERING_STANDARDS_GATE_NAME,
    ),
    (
        "17",
        SECTION17_RDP_MANIFEST_KEY,
        SECTION17_RDP_PRODUCER_KEY,
        SECTION17_RDP_GATE_NAME,
    ),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list)) else (value,)
    return tuple(text for item in values if (text := _text(item)))


def _is_full_sha256(value: Any) -> bool:
    token = _text(value)
    return len(token) == 64 and all(char in "0123456789abcdef" for char in token)


def canonical_payload_sha256(value: Any) -> str:
    """Return a full SHA-256 over strict canonical JSON."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PromotionGateVerification:
    """Canonical section assembly plus its server-derived gate verdict."""

    section: str
    manifest_key: str
    producer_key: str
    gate_name: str
    canonical_source_refs: tuple[str, ...]
    assembled_payload_sha256: str
    gate_verdict_sha256: str
    mode: str
    ok: bool
    producer_green: bool
    errored: bool
    missing: tuple[str, ...] = ()
    residuals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "section",
            "manifest_key",
            "producer_key",
            "gate_name",
            "assembled_payload_sha256",
            "gate_verdict_sha256",
            "mode",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        for field_name in ("canonical_source_refs", "missing", "residuals"):
            object.__setattr__(self, field_name, _strings(getattr(self, field_name)))


@dataclass(frozen=True)
class PromotionVerificationSnapshot:
    """Current proof returned by the read-only server verification loader."""

    section_verifications: tuple[PromotionGateVerification, ...]
    release_verdict_sha256: str
    gate_chain_sha256: str
    run_manifest_sha256: str
    outcome: str
    release_ok: bool
    release_ready: bool
    chain_rejected: bool
    chain_release_ready: bool
    errors: tuple[str, ...] = ()
    residuals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "section_verifications",
            tuple(self.section_verifications or ()),
        )
        for field_name in (
            "release_verdict_sha256",
            "gate_chain_sha256",
            "run_manifest_sha256",
            "outcome",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        for field_name in ("errors", "residuals"):
            object.__setattr__(self, field_name, _strings(getattr(self, field_name)))


@dataclass(frozen=True)
class PromotionCandidateProof:
    """Exact hidden candidate identity accepted by the canonical verifier."""

    staging_name: str
    st_dev: int
    st_ino: int
    run_manifest_sha256: str

    def __post_init__(self) -> None:
        raw_name = str(self.staging_name or "")
        name = raw_name.strip()
        if (
            raw_name != name
            or not name
            or name in {".", ".."}
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or "\x00" in name
        ):
            raise ValueError(
                "promotion candidate must name one direct .staging child"
            )
        if (
            not isinstance(self.st_dev, int)
            or isinstance(self.st_dev, bool)
            or self.st_dev < 0
            or not isinstance(self.st_ino, int)
            or isinstance(self.st_ino, bool)
            or self.st_ino <= 0
        ):
            raise ValueError(
                "promotion candidate requires exact device and inode identity"
            )
        if not _is_full_sha256(self.run_manifest_sha256):
            raise ValueError(
                "promotion candidate requires a full run manifest SHA-256"
            )
        object.__setattr__(self, "staging_name", name)
        object.__setattr__(
            self,
            "run_manifest_sha256",
            _text(self.run_manifest_sha256),
        )


@dataclass(frozen=True)
class PromotionVerificationReceipt:
    """Immutable, content-addressed receipt persisted after verification."""

    receipt_ref: str
    owner_user_id: str
    source_ide_run_id: str
    promoted_run_id: str
    rdp_package_id: str
    requested_label: str
    section_verifications: tuple[PromotionGateVerification, ...]
    release_verdict_sha256: str
    gate_chain_sha256: str
    run_manifest_sha256: str
    outcome: str
    release_ok: bool
    release_ready: bool
    chain_rejected: bool
    chain_release_ready: bool
    errors: tuple[str, ...] = ()
    residuals: tuple[str, ...] = ()
    receipt_version: str = RECEIPT_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_ref",
            "owner_user_id",
            "source_ide_run_id",
            "promoted_run_id",
            "rdp_package_id",
            "requested_label",
            "release_verdict_sha256",
            "gate_chain_sha256",
            "run_manifest_sha256",
            "outcome",
            "receipt_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        object.__setattr__(
            self,
            "section_verifications",
            tuple(self.section_verifications or ()),
        )
        for field_name in ("errors", "residuals"):
            object.__setattr__(self, field_name, _strings(getattr(self, field_name)))

    @property
    def canonical_receipt_ref(self) -> str:
        return promotion_receipt_identity(
            owner_user_id=self.owner_user_id,
            source_ide_run_id=self.source_ide_run_id,
            promoted_run_id=self.promoted_run_id,
            rdp_package_id=self.rdp_package_id,
            requested_label=self.requested_label,
            section_verifications=self.section_verifications,
            release_verdict_sha256=self.release_verdict_sha256,
            gate_chain_sha256=self.gate_chain_sha256,
            run_manifest_sha256=self.run_manifest_sha256,
            outcome=self.outcome,
            release_ok=self.release_ok,
            release_ready=self.release_ready,
            chain_rejected=self.chain_rejected,
            chain_release_ready=self.chain_release_ready,
            errors=self.errors,
            residuals=self.residuals,
            receipt_version=self.receipt_version,
        )


@dataclass(frozen=True)
class PromotionReceiptViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class PromotionReceiptDecision:
    accepted: bool
    violations: tuple[PromotionReceiptViolation, ...]


VerificationLoader: TypeAlias = Callable[
    [str, str, str, str, str], PromotionVerificationSnapshot | Mapping[str, Any]
]


def promotion_gate_verification_from_dict(
    raw: Mapping[str, Any],
) -> PromotionGateVerification:
    return PromotionGateVerification(
        section=raw.get("section", ""),
        manifest_key=raw.get("manifest_key", ""),
        producer_key=raw.get("producer_key", ""),
        gate_name=raw.get("gate_name", ""),
        canonical_source_refs=_strings(raw.get("canonical_source_refs")),
        assembled_payload_sha256=raw.get("assembled_payload_sha256", ""),
        gate_verdict_sha256=raw.get("gate_verdict_sha256", ""),
        mode=raw.get("mode", ""),
        ok=raw.get("ok", False),
        producer_green=raw.get("producer_green", False),
        errored=raw.get("errored", True),
        missing=_strings(raw.get("missing")),
        residuals=_strings(raw.get("residuals")),
    )


def promotion_verification_snapshot_from_dict(
    raw: Mapping[str, Any],
) -> PromotionVerificationSnapshot:
    rows = raw.get("section_verifications")
    if not isinstance(rows, (tuple, list)) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError("section_verifications must be a list of objects")
    return PromotionVerificationSnapshot(
        section_verifications=tuple(
            promotion_gate_verification_from_dict(row) for row in rows
        ),
        release_verdict_sha256=raw.get("release_verdict_sha256", ""),
        gate_chain_sha256=raw.get("gate_chain_sha256", ""),
        run_manifest_sha256=raw.get("run_manifest_sha256", ""),
        outcome=raw.get("outcome", ""),
        release_ok=raw.get("release_ok", False),
        release_ready=raw.get("release_ready", False),
        chain_rejected=raw.get("chain_rejected", True),
        chain_release_ready=raw.get("chain_release_ready", False),
        errors=_strings(raw.get("errors")),
        residuals=_strings(raw.get("residuals")),
    )


def promotion_receipt_from_dict(raw: Mapping[str, Any]) -> PromotionVerificationReceipt:
    rows = raw.get("section_verifications")
    if not isinstance(rows, (tuple, list)) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError("section_verifications must be a list of objects")
    return PromotionVerificationReceipt(
        receipt_ref=raw.get("receipt_ref", ""),
        owner_user_id=raw.get("owner_user_id", ""),
        source_ide_run_id=raw.get("source_ide_run_id", ""),
        promoted_run_id=raw.get("promoted_run_id", ""),
        rdp_package_id=raw.get("rdp_package_id", ""),
        requested_label=raw.get("requested_label", ""),
        section_verifications=tuple(
            promotion_gate_verification_from_dict(row) for row in rows
        ),
        release_verdict_sha256=raw.get("release_verdict_sha256", ""),
        gate_chain_sha256=raw.get("gate_chain_sha256", ""),
        run_manifest_sha256=raw.get("run_manifest_sha256", ""),
        outcome=raw.get("outcome", ""),
        release_ok=raw.get("release_ok", False),
        release_ready=raw.get("release_ready", False),
        chain_rejected=raw.get("chain_rejected", True),
        chain_release_ready=raw.get("chain_release_ready", False),
        errors=_strings(raw.get("errors")),
        residuals=_strings(raw.get("residuals")),
        receipt_version=raw.get("receipt_version", RECEIPT_VERSION),
    )


def promotion_receipt_identity(
    *,
    owner_user_id: str,
    source_ide_run_id: str,
    promoted_run_id: str,
    rdp_package_id: str,
    requested_label: str,
    section_verifications: tuple[PromotionGateVerification, ...],
    release_verdict_sha256: str,
    gate_chain_sha256: str,
    run_manifest_sha256: str,
    outcome: str,
    release_ok: bool,
    release_ready: bool,
    chain_rejected: bool,
    chain_release_ready: bool,
    errors: tuple[str, ...] = (),
    residuals: tuple[str, ...] = (),
    receipt_version: str = RECEIPT_VERSION,
) -> str:
    digest = canonical_payload_sha256(
        {
            "owner_user_id": _text(owner_user_id),
            "source_ide_run_id": _text(source_ide_run_id),
            "promoted_run_id": _text(promoted_run_id),
            "rdp_package_id": _text(rdp_package_id),
            "requested_label": _text(requested_label),
            "section_verifications": [
                asdict(item) for item in tuple(section_verifications or ())
            ],
            "release_verdict_sha256": _text(release_verdict_sha256),
            "gate_chain_sha256": _text(gate_chain_sha256),
            "run_manifest_sha256": _text(run_manifest_sha256),
            "outcome": _text(outcome),
            "release_ok": release_ok,
            "release_ready": release_ready,
            "chain_rejected": chain_rejected,
            "chain_release_ready": chain_release_ready,
            "errors": _strings(errors),
            "residuals": _strings(residuals),
            "receipt_version": _text(receipt_version),
        }
    )
    return RECEIPT_PREFIX + digest


def validate_promotion_receipt_shape(
    receipt: PromotionVerificationReceipt,
) -> PromotionReceiptDecision:
    violations: list[PromotionReceiptViolation] = []

    def reject(code: str, message: str, *, field: str = "", ref: str = "") -> None:
        violations.append(PromotionReceiptViolation(code, message, field, ref))

    for field_name in (
        "receipt_ref",
        "owner_user_id",
        "source_ide_run_id",
        "promoted_run_id",
        "rdp_package_id",
        "requested_label",
    ):
        if not getattr(receipt, field_name):
            reject(
                "promotion_receipt_required_field_missing",
                "promotion receipts require stable owner, run, RDP, and label identities",
                field=field_name,
            )
    if receipt.receipt_version != RECEIPT_VERSION:
        reject(
            "promotion_receipt_version_unsupported",
            "promotion receipt version is unsupported",
            field="receipt_version",
            ref=receipt.receipt_version,
        )
    for field_name in (
        "release_verdict_sha256",
        "gate_chain_sha256",
        "run_manifest_sha256",
    ):
        if not _is_full_sha256(getattr(receipt, field_name)):
            reject(
                "promotion_receipt_digest_invalid",
                "promotion receipt digests must be full lowercase SHA-256 hex",
                field=field_name,
                ref=_text(getattr(receipt, field_name)),
            )

    actual_bindings: dict[str, tuple[str, str, str]] = {}
    for item in receipt.section_verifications:
        if item.gate_name in actual_bindings:
            reject(
                "promotion_receipt_gate_duplicate",
                "each registered promote gate must occur exactly once",
                field="section_verifications",
                ref=item.gate_name,
            )
        actual_bindings[item.gate_name] = (
            item.section,
            item.manifest_key,
            item.producer_key,
        )
        if not item.canonical_source_refs or len(item.canonical_source_refs) != len(
            set(item.canonical_source_refs)
        ):
            reject(
                "promotion_receipt_sources_invalid",
                "each gate requires unique, non-empty canonical source refs",
                field="canonical_source_refs",
                ref=item.gate_name,
            )
        for field_name in ("assembled_payload_sha256", "gate_verdict_sha256"):
            if not _is_full_sha256(getattr(item, field_name)):
                reject(
                    "promotion_receipt_digest_invalid",
                    "section payload and verdict digests must be full lowercase SHA-256 hex",
                    field=field_name,
                    ref=item.gate_name,
                )
        if item.mode != "enforce":
            reject(
                "promotion_receipt_gate_not_enforcing",
                "advisory gates cannot mint promotion verification",
                field="mode",
                ref=item.gate_name,
            )
        if item.ok is not True:
            reject(
                "promotion_receipt_gate_not_passed",
                "every enforced gate must pass",
                field="ok",
                ref=item.gate_name,
            )
        if item.producer_green is not True:
            reject(
                "promotion_receipt_producer_not_green",
                "every enforced gate must have a server-verified green producer",
                field="producer_green",
                ref=item.gate_name,
            )
        if item.errored is not False:
            reject(
                "promotion_receipt_gate_errored",
                "errored gate evaluation cannot mint promotion verification",
                field="errored",
                ref=item.gate_name,
            )
        if item.missing:
            reject(
                "promotion_receipt_gate_missing_evidence",
                "a passing promotion receipt cannot retain missing gate evidence",
                field="missing",
                ref=item.gate_name,
            )
        if item.residuals:
            reject(
                "promotion_receipt_gate_has_residuals",
                "a passing promotion receipt cannot retain gate residuals",
                field="residuals",
                ref=item.gate_name,
            )

    expected_bindings = {
        gate_name: (section, manifest_key, producer_key)
        for section, manifest_key, producer_key, gate_name in EXPECTED_GATE_BINDINGS
    }
    if actual_bindings != expected_bindings:
        reject(
            "promotion_receipt_gate_set_mismatch",
            "promotion receipt must cover the exact registered promote gate family",
            field="section_verifications",
        )
    if receipt.outcome != "passed":
        reject(
            "promotion_receipt_not_passed",
            "only a passed server verification can mint a promotion receipt",
            field="outcome",
            ref=receipt.outcome,
        )
    if receipt.release_ok is not True or receipt.release_ready is not True:
        reject(
            "promotion_receipt_release_not_ready",
            "release evaluation must be passed and ready",
            field="release_ready",
        )
    if receipt.chain_rejected is not False or receipt.chain_release_ready is not True:
        reject(
            "promotion_receipt_chain_not_ready",
            "promote gate chain must be unrejected and release-ready",
            field="chain_release_ready",
        )
    if receipt.errors:
        reject(
            "promotion_receipt_has_errors",
            "promotion verification with errors cannot mint a receipt",
            field="errors",
        )
    if receipt.residuals:
        reject(
            "promotion_receipt_has_residuals",
            "promotion verification with unresolved residuals cannot mint a receipt",
            field="residuals",
        )
    if receipt.receipt_ref and receipt.receipt_ref != receipt.canonical_receipt_ref:
        reject(
            "promotion_receipt_identity_mismatch",
            "receipt_ref must content-bind the owner, identities, digests, and verdicts",
            field="receipt_ref",
            ref=receipt.receipt_ref,
        )
    return PromotionReceiptDecision(not violations, tuple(violations))


class PersistentPromotionReceiptRegistry:
    """Schema-v2 append-only owner ledger backed by current server proof."""

    def __init__(self, path: str | Path, verification_loader: VerificationLoader) -> None:
        if not callable(verification_loader):
            raise TypeError("verification_loader must be callable")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._history_marker_path = self._path.with_suffix(
            self._path.suffix + ".history"
        )
        self._verification_loader = verification_loader
        self._lock = _shared_process_lock(self._lock_path)
        self._records: dict[tuple[str, str], PromotionVerificationReceipt] = {}
        self._legacy_quarantined_count = 0
        self._known_rows: tuple[bytes, ...] = ()
        self._ever_had_history = False
        self._ledger_bytes = b""
        self._ledger_fingerprint: tuple[int, int, int, int, int] | None = None
        self._marker_fingerprint: tuple[int, int, int, int, int] | None = None
        self._active_lock_fingerprints: list[tuple[int, int, int, int, int]] = []
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return self._legacy_quarantined_count

    @staticmethod
    def _fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            int(info.st_dev),
            int(info.st_ino),
            int(info.st_size),
            int(info.st_mtime_ns),
            int(info.st_ctime_ns),
        )

    @staticmethod
    def _validate_regular_owned(info: os.stat_result, *, label: str) -> None:
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{label} must be a regular non-symlink file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ValueError(f"{label} is owned by a different runtime user")

    @classmethod
    def _path_fingerprint(
        cls,
        path: Path,
        *,
        label: str,
    ) -> tuple[int, int, int, int, int]:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise ValueError(f"{label} is missing") from exc
        cls._validate_regular_owned(info, label=label)
        return cls._fingerprint(info)

    @classmethod
    def _assert_path_fingerprint(
        cls,
        path: Path,
        expected: tuple[int, int, int, int, int] | None,
        *,
        label: str,
    ) -> None:
        if expected is None:
            if os.path.lexists(path):
                raise ValueError(f"{label} appeared after durable replay")
            return
        current = cls._path_fingerprint(path, label=label)
        if current != expected:
            raise ValueError(f"{label} path identity changed during operation")

    @classmethod
    def _assert_lock_path_identity(
        cls,
        path: Path,
        expected: tuple[int, int, int, int, int],
    ) -> None:
        current = cls._path_fingerprint(
            path,
            label="IDE promotion receipt lock",
        )
        if current[:2] != expected[:2]:
            raise ValueError(
                "IDE promotion receipt lock path identity changed during operation"
            )

    @classmethod
    def _read_regular_bytes(
        cls,
        path: Path,
        *,
        label: str,
    ) -> tuple[bytes, tuple[int, int, int, int, int]]:
        before = cls._path_fingerprint(path, label=label)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            raise ValueError(f"{label} could not be opened without following links") from exc
        try:
            opened_before = os.fstat(fd)
            cls._validate_regular_owned(opened_before, label=label)
            if cls._fingerprint(opened_before) != before:
                raise ValueError(f"{label} changed during secure open")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            opened_after = os.fstat(fd)
            if cls._fingerprint(opened_after) != before:
                raise ValueError(f"{label} changed during secure read")
            after = cls._path_fingerprint(path, label=label)
            if after != before:
                raise ValueError(f"{label} path identity changed during secure read")
            return b"".join(chunks), after
        finally:
            os.close(fd)

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short IDE promotion receipt metadata write")
            view = view[written:]

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @contextmanager
    def _exclusive_ledger_lock(self) -> Iterator[None]:
        """Serialize replay, proof resolution, and append across all writers."""

        with self._lock:
            if self._active_lock_fingerprints:
                raise RuntimeError(
                    "IDE promotion receipt registry does not allow reentrant public access"
                )
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(self._lock_path, flags, 0o600)
            except OSError as exc:
                raise ValueError(
                    "IDE promotion receipt lock could not be opened safely"
                ) from exc
            held = None
            active = False
            try:
                info = os.fstat(fd)
                self._validate_regular_owned(
                    info,
                    label="IDE promotion receipt lock",
                )
                os.fchmod(fd, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                locked = os.fstat(fd)
                self._validate_regular_owned(
                    locked,
                    label="IDE promotion receipt lock",
                )
                lock_fingerprint = self._fingerprint(locked)
                self._assert_lock_path_identity(
                    self._lock_path,
                    lock_fingerprint,
                )
                self._active_lock_fingerprints.append(lock_fingerprint)
                active = True
                try:
                    yield
                except BaseException:
                    raise
                else:
                    self._assert_durable_state_identity_unlocked()
                    self._assert_lock_path_identity(
                        self._lock_path,
                        lock_fingerprint,
                    )
            finally:
                if active:
                    popped = self._active_lock_fingerprints.pop()
                    if popped != lock_fingerprint:
                        raise RuntimeError("IDE promotion receipt lock stack corrupted")
                if held is not None:
                    held.release()
                os.close(fd)

    def _assert_active_lock_identity(self) -> None:
        if not self._active_lock_fingerprints:
            raise RuntimeError("IDE promotion receipt durable operation requires ledger lock")
        self._assert_lock_path_identity(
            self._lock_path,
            self._active_lock_fingerprints[-1],
        )

    def _assert_durable_state_identity_unlocked(self) -> None:
        """Ensure no ledger or marker mutation escaped the held advisory lock."""

        self._assert_path_fingerprint(
            self._path,
            self._ledger_fingerprint,
            label="IDE promotion receipt ledger",
        )
        self._assert_path_fingerprint(
            self._history_marker_path,
            self._marker_fingerprint,
            label="IDE promotion receipt history marker",
        )

    @staticmethod
    def _encoded_row(row: Mapping[str, Any]) -> bytes:
        return json.dumps(
            dict(row),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _physical_rows(payload: bytes) -> tuple[bytes, ...]:
        if not payload:
            return ()
        rows = payload.split(b"\n")
        if rows[-1] == b"":
            rows.pop()
        return tuple(rows)

    @staticmethod
    def _rows_digest(rows: tuple[bytes, ...]) -> str:
        digest = hashlib.sha256()
        for row in rows:
            digest.update(len(row).to_bytes(8, "big"))
            digest.update(row)
        return digest.hexdigest()

    def _history_marker(
        self,
    ) -> tuple[
        tuple[int, str] | None,
        tuple[int, int, int, int, int] | None,
    ]:
        if not os.path.lexists(self._history_marker_path):
            return None, None
        try:
            payload, fingerprint = self._read_regular_bytes(
                self._history_marker_path,
                label="IDE promotion receipt history marker",
            )
            raw = json.loads(payload.decode("utf-8"))
            if not isinstance(raw, dict) or set(raw) != {
                "schema_version",
                "row_count",
                "prefix_sha256",
            }:
                raise ValueError("invalid history marker fields")
            row_count = raw.get("row_count")
            prefix_sha256 = raw.get("prefix_sha256")
            if (
                raw.get("schema_version") != 1
                or type(row_count) is not int
                or row_count < 0
                or not isinstance(prefix_sha256, str)
                or not _is_full_sha256(prefix_sha256)
            ):
                raise ValueError("invalid history marker content")
            return (row_count, prefix_sha256), fingerprint
        except Exception as exc:  # noqa: BLE001 - integrity metadata fails closed.
            raise ValueError("invalid IDE promotion receipt history marker") from exc

    def _atomic_replace_bytes(
        self,
        path: Path,
        payload: bytes,
        *,
        expected: tuple[int, int, int, int, int] | None,
        label: str,
    ) -> tuple[int, int, int, int, int]:
        self._assert_active_lock_identity()
        fd, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            self._write_all(fd, payload)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            self._assert_path_fingerprint(path, expected, label=label)
            self._assert_active_lock_identity()
            os.replace(temporary, path)
            self._fsync_parent(path)
            persisted, fingerprint = self._read_regular_bytes(path, label=label)
            if persisted != payload:
                raise ValueError(f"{label} atomic write postcondition failed")
            return fingerprint
        finally:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)

    def _write_history_marker(
        self,
        rows: tuple[bytes, ...],
        *,
        expected: tuple[int, int, int, int, int] | None,
    ) -> tuple[int, int, int, int, int]:
        payload = self._encoded_row(
            {
                "schema_version": 1,
                "row_count": len(rows),
                "prefix_sha256": self._rows_digest(rows),
            }
        )
        return self._atomic_replace_bytes(
            self._history_marker_path,
            payload,
            expected=expected,
            label="IDE promotion receipt history marker",
        )

    @staticmethod
    def _required_identity(value: Any, field_name: str) -> str:
        identity = _text(value)
        if not identity:
            raise ValueError(f"promotion receipt {field_name} is required")
        return identity

    def _load_snapshot(
        self,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
    ) -> PromotionVerificationSnapshot:
        raw = self._verification_loader(
            owner_user_id,
            source_ide_run_id,
            promoted_run_id,
            rdp_package_id,
            requested_label,
        )
        if isinstance(raw, PromotionVerificationSnapshot):
            return raw
        if isinstance(raw, Mapping):
            return promotion_verification_snapshot_from_dict(raw)
        raise TypeError("verification_loader must return PromotionVerificationSnapshot or mapping")

    def _load_candidate_snapshot(
        self,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
        *,
        candidate: PromotionCandidateProof,
    ) -> PromotionVerificationSnapshot:
        if not isinstance(candidate, PromotionCandidateProof):
            raise TypeError("candidate must be PromotionCandidateProof")
        loader = getattr(self._verification_loader, "verify_candidate", None)
        if not callable(loader):
            raise TypeError(
                "verification_loader must expose verify_candidate for hidden promotion"
            )
        raw = loader(
            owner_user_id,
            source_ide_run_id,
            promoted_run_id,
            rdp_package_id,
            requested_label,
            candidate=candidate,
        )
        if isinstance(raw, PromotionVerificationSnapshot):
            return raw
        if isinstance(raw, Mapping):
            return promotion_verification_snapshot_from_dict(raw)
        raise TypeError(
            "candidate verification must return PromotionVerificationSnapshot or mapping"
        )

    @staticmethod
    def _build_receipt(
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
        snapshot: PromotionVerificationSnapshot,
    ) -> PromotionVerificationReceipt:
        provisional = PromotionVerificationReceipt(
            receipt_ref="",
            owner_user_id=owner_user_id,
            source_ide_run_id=source_ide_run_id,
            promoted_run_id=promoted_run_id,
            rdp_package_id=rdp_package_id,
            requested_label=requested_label,
            section_verifications=snapshot.section_verifications,
            release_verdict_sha256=snapshot.release_verdict_sha256,
            gate_chain_sha256=snapshot.gate_chain_sha256,
            run_manifest_sha256=snapshot.run_manifest_sha256,
            outcome=snapshot.outcome,
            release_ok=snapshot.release_ok,
            release_ready=snapshot.release_ready,
            chain_rejected=snapshot.chain_rejected,
            chain_release_ready=snapshot.chain_release_ready,
            errors=snapshot.errors,
            residuals=snapshot.residuals,
        )
        return PromotionVerificationReceipt(
            **{
                **asdict(provisional),
                "receipt_ref": provisional.canonical_receipt_ref,
                "section_verifications": provisional.section_verifications,
            }
        )

    @staticmethod
    def _event(receipt: PromotionVerificationReceipt) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "event_type": "ide_promotion_verification_recorded",
            "owner_user_id": receipt.owner_user_id,
            "promotion_receipt": asdict(receipt),
        }

    def _load_existing(self) -> None:
        with self._exclusive_ledger_lock():
            self._replay_unlocked()

    def _replay_unlocked(self) -> None:
        """Rebuild the cache from append-only durable history under the lock."""

        self._assert_active_lock_identity()
        marker, marker_fingerprint = self._history_marker()
        empty_marker = (0, self._rows_digest(()))

        if not os.path.lexists(self._path):
            if marker is None:
                if self._ever_had_history or self._known_rows:
                    raise ValueError(
                        "persisted IDE promotion receipt history marker is missing"
                    )
                marker_fingerprint = self._write_history_marker(
                    (),
                    expected=None,
                )
                marker = empty_marker
            if (
                marker != empty_marker
                or self._ever_had_history
                or bool(self._known_rows)
            ):
                raise ValueError("persisted IDE promotion receipt history is missing")
            self._records = {}
            self._legacy_quarantined_count = 0
            self._known_rows = ()
            self._ledger_bytes = b""
            self._ledger_fingerprint = None
            self._marker_fingerprint = marker_fingerprint
            return

        payload, ledger_fingerprint = self._read_regular_bytes(
            self._path,
            label="IDE promotion receipt ledger",
        )
        rows = self._physical_rows(payload)
        parsed_rows: list[tuple[int, dict[str, Any]]] = []
        legacy_count = 0
        has_schema_v2 = False
        for line_no, line in enumerate(rows, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line.decode("utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("IDE promotion receipt row must be an object")
            except Exception as exc:  # noqa: BLE001 - corrupt proof must fail closed.
                raise ValueError(
                    f"invalid persisted IDE promotion receipt at {self._path}:{line_no}"
                ) from exc
            parsed_rows.append((line_no, raw))
            if raw.get("schema_version") == 2:
                has_schema_v2 = True
            else:
                legacy_count += 1

        if marker is None:
            if self._ever_had_history or has_schema_v2:
                raise ValueError(
                    "persisted IDE promotion receipt history marker is missing"
                )
        else:
            marker_count, marker_digest = marker
            if len(rows) < marker_count:
                raise ValueError(
                    "persisted IDE promotion receipt history was truncated"
                )
            if self._rows_digest(rows[:marker_count]) != marker_digest:
                raise ValueError(
                    "persisted IDE promotion receipt history changed before marker"
                )
        if self._known_rows and rows[: len(self._known_rows)] != self._known_rows:
            raise ValueError(
                "persisted IDE promotion receipt append-only history changed"
            )

        self._records = {}
        self._legacy_quarantined_count = legacy_count
        for line_no, raw in parsed_rows:
            if raw.get("schema_version") != 2:
                continue
            try:
                self._apply_row(raw, persist=False)
            except Exception as exc:  # noqa: BLE001 - corrupt proof must fail closed.
                raise ValueError(
                    f"invalid persisted IDE promotion receipt at {self._path}:{line_no}"
                ) from exc

        if (
            marker is None
            or marker[0] != len(rows)
            or marker[1] != self._rows_digest(rows)
        ):
            marker_fingerprint = self._write_history_marker(
                rows,
                expected=marker_fingerprint,
            )
        self._known_rows = rows
        self._ever_had_history = self._ever_had_history or bool(rows)
        self._ledger_bytes = payload
        self._ledger_fingerprint = ledger_fingerprint
        self._marker_fingerprint = marker_fingerprint

    def _append_event(self, row: dict[str, Any]) -> None:
        """Append one event to the exact ledger inode replayed by the caller."""

        self._assert_active_lock_identity()
        serialized = self._encoded_row(row)
        separator = b"\n" if self._ledger_bytes and not self._ledger_bytes.endswith(b"\n") else b""
        suffix = separator + serialized + b"\n"
        updated_payload = self._ledger_bytes + suffix
        expected = self._ledger_fingerprint
        flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        created = expected is None
        if created:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(self._path, flags, 0o600)
        except OSError as exc:
            raise ValueError(
                "IDE promotion receipt ledger identity changed before append"
            ) from exc

        original_size = len(self._ledger_bytes)
        remove_created_after_failure = False
        try:
            if created:
                os.fchmod(fd, 0o600)
            opened = os.fstat(fd)
            self._validate_regular_owned(opened, label="IDE promotion receipt ledger")
            opened_fingerprint = self._fingerprint(opened)
            if expected is not None and opened_fingerprint != expected:
                raise ValueError(
                    "IDE promotion receipt ledger changed between replay and append"
                )
            self._assert_path_fingerprint(
                self._path,
                opened_fingerprint,
                label="IDE promotion receipt ledger",
            )
            self._assert_active_lock_identity()
            try:
                written = os.write(fd, suffix)
                if written != len(suffix):
                    raise OSError("short IDE promotion receipt ledger append")
                os.fsync(fd)
                appended = os.fstat(fd)
                self._validate_regular_owned(
                    appended,
                    label="IDE promotion receipt ledger",
                )
                if (
                    (appended.st_dev, appended.st_ino)
                    != (opened.st_dev, opened.st_ino)
                    or appended.st_size != len(updated_payload)
                ):
                    raise ValueError(
                        "IDE promotion receipt ledger append postcondition failed"
                    )
                self._assert_path_fingerprint(
                    self._path,
                    self._fingerprint(appended),
                    label="IDE promotion receipt ledger",
                )
            except BaseException as exc:
                rollback_errors: list[BaseException] = []
                try:
                    os.ftruncate(fd, original_size)
                    os.fsync(fd)
                except BaseException as rollback_exc:  # noqa: BLE001
                    rollback_errors.append(rollback_exc)
                if created and not rollback_errors:
                    try:
                        current = self._path_fingerprint(
                            self._path,
                            label="IDE promotion receipt ledger",
                        )
                        rolled_back = self._fingerprint(os.fstat(fd))
                        if current == rolled_back:
                            os.unlink(self._path)
                            remove_created_after_failure = True
                    except BaseException as cleanup_exc:  # noqa: BLE001
                        rollback_errors.append(cleanup_exc)
                if rollback_errors:
                    raise ValueError(
                        "IDE promotion receipt append failed and rollback is unverified"
                    ) from exc
                raise
        finally:
            os.close(fd)
            if remove_created_after_failure:
                self._fsync_parent(self._path)

        if created:
            self._fsync_parent(self._path)
        persisted, ledger_fingerprint = self._read_regular_bytes(
            self._path,
            label="IDE promotion receipt ledger",
        )
        if persisted != updated_payload:
            raise ValueError("IDE promotion receipt ledger bytes diverged after append")
        rows = self._physical_rows(updated_payload)
        marker_fingerprint = self._write_history_marker(
            rows,
            expected=self._marker_fingerprint,
        )
        self._ledger_bytes = updated_payload
        self._ledger_fingerprint = ledger_fingerprint
        self._known_rows = rows
        self._ever_had_history = True
        self._marker_fingerprint = marker_fingerprint

    def _apply_row(
        self,
        row: Mapping[str, Any],
        *,
        persist: bool,
    ) -> PromotionVerificationReceipt:
        self._assert_active_lock_identity()
        if row.get("schema_version") != 2:
            raise ValueError("IDE promotion receipts require schema_version=2")
        if row.get("event_type") != "ide_promotion_verification_recorded":
            raise ValueError("unknown IDE promotion receipt event_type")
        owner = self._required_identity(row.get("owner_user_id"), "owner_user_id")
        raw = row.get("promotion_receipt")
        if not isinstance(raw, Mapping):
            raise ValueError("IDE promotion receipt event is missing promotion_receipt")
        receipt = promotion_receipt_from_dict(raw)
        if receipt.owner_user_id != owner:
            raise ValueError("IDE promotion receipt owner envelope mismatch")
        decision = validate_promotion_receipt_shape(receipt)
        if not decision.accepted:
            raise ValueError(
                "; ".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        key = (owner, receipt.receipt_ref)
        existing = self._records.get(key)
        if existing is not None:
            if existing != receipt:
                raise ValueError("IDE promotion receipt identity collision for owner")
            return existing
        if persist:
            self._append_event(dict(row))
        self._records[key] = receipt
        return receipt

    def _identities_unlocked(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
    ) -> dict[str, str]:
        return {
            "owner_user_id": self._required_identity(owner_user_id, "owner_user_id"),
            "source_ide_run_id": self._required_identity(
                source_ide_run_id,
                "source_ide_run_id",
            ),
            "promoted_run_id": self._required_identity(
                promoted_run_id,
                "promoted_run_id",
            ),
            "rdp_package_id": self._required_identity(
                rdp_package_id,
                "rdp_package_id",
            ),
            "requested_label": self._required_identity(
                requested_label,
                "requested_label",
            ),
        }

    def _validated_current_receipt_unlocked(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
        candidate: PromotionCandidateProof | None = None,
    ) -> PromotionVerificationReceipt:
        identities = self._identities_unlocked(
            owner_user_id=owner_user_id,
            source_ide_run_id=source_ide_run_id,
            promoted_run_id=promoted_run_id,
            rdp_package_id=rdp_package_id,
            requested_label=requested_label,
        )
        if candidate is None:
            snapshot = self._load_snapshot(**identities)
        else:
            snapshot = self._load_candidate_snapshot(
                **identities,
                candidate=candidate,
            )
        receipt = self._build_receipt(snapshot=snapshot, **identities)
        decision = validate_promotion_receipt_shape(receipt)
        if not decision.accepted:
            raise ValueError(
                "; ".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        return receipt

    def _receipt_unlocked(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> PromotionVerificationReceipt:
        owner = self._required_identity(owner_user_id, "owner_user_id")
        ref = self._required_identity(receipt_ref, "receipt_ref")
        return self._records[(owner, ref)]

    def record_current(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
    ) -> PromotionVerificationReceipt:
        """Load current proof, validate it, then durably record its exact receipt."""

        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            receipt = self._validated_current_receipt_unlocked(
                owner_user_id=owner_user_id,
                source_ide_run_id=source_ide_run_id,
                promoted_run_id=promoted_run_id,
                rdp_package_id=rdp_package_id,
                requested_label=requested_label,
            )
            return self._apply_row(self._event(receipt), persist=True)

    def prepare_current(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
    ) -> PromotionVerificationReceipt:
        """Build and validate the exact current receipt without persisting it.

        This supports a two-phase integration boundary: downstream governed
        lineage can bind the deterministic receipt ref before the receipt is
        appended as the final authority commit. ``record_current`` must still
        run afterward and its returned ref must exact-match this preview.
        """

        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return self._validated_current_receipt_unlocked(
                owner_user_id=owner_user_id,
                source_ide_run_id=source_ide_run_id,
                promoted_run_id=promoted_run_id,
                rdp_package_id=rdp_package_id,
                requested_label=requested_label,
            )

    def prepare_candidate_current(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
        candidate: PromotionCandidateProof,
    ) -> PromotionVerificationReceipt:
        """Validate one exact hidden staging candidate without persisting."""

        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return self._validated_current_receipt_unlocked(
                owner_user_id=owner_user_id,
                source_ide_run_id=source_ide_run_id,
                promoted_run_id=promoted_run_id,
                rdp_package_id=rdp_package_id,
                requested_label=requested_label,
                candidate=candidate,
            )

    def record_candidate_current(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
        candidate: PromotionCandidateProof,
    ) -> PromotionVerificationReceipt:
        """Durably append a receipt proven from one exact hidden candidate."""

        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            receipt = self._validated_current_receipt_unlocked(
                owner_user_id=owner_user_id,
                source_ide_run_id=source_ide_run_id,
                promoted_run_id=promoted_run_id,
                rdp_package_id=rdp_package_id,
                requested_label=requested_label,
                candidate=candidate,
            )
            return self._apply_row(self._event(receipt), persist=True)

    def receipt(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> PromotionVerificationReceipt:
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            return self._receipt_unlocked(
                receipt_ref,
                owner_user_id=owner_user_id,
            )

    def receipts(self, *, owner_user_id: str) -> list[PromotionVerificationReceipt]:
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            owner = self._required_identity(owner_user_id, "owner_user_id")
            return [
                receipt
                for (record_owner, _receipt_ref), receipt in self._records.items()
                if record_owner == owner
            ]

    def gate_verdict(
        self,
        receipt_ref: str,
        gate_name: str,
        *,
        owner_user_id: str,
    ) -> PromotionGateVerification:
        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            receipt = self._receipt_unlocked(
                receipt_ref,
                owner_user_id=owner_user_id,
            )
            gate = self._required_identity(gate_name, "gate_name")
            for verification in receipt.section_verifications:
                if verification.gate_name == gate:
                    return verification
            raise KeyError((receipt_ref, gate))

    def validate_current(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
    ) -> PromotionReceiptDecision:
        """Re-resolve server proof and exact-compare it with the durable receipt."""

        with self._exclusive_ledger_lock():
            self._replay_unlocked()
            owner = self._required_identity(owner_user_id, "owner_user_id")
            ref = self._required_identity(receipt_ref, "receipt_ref")
            try:
                receipt = self._receipt_unlocked(ref, owner_user_id=owner)
            except KeyError:
                return PromotionReceiptDecision(
                    False,
                    (
                        PromotionReceiptViolation(
                            "promotion_receipt_unknown",
                            "promotion receipt is not persisted for this owner",
                            "receipt_ref",
                            ref,
                        ),
                    ),
                )

            identities = self._identities_unlocked(
                owner_user_id=owner,
                source_ide_run_id=source_ide_run_id,
                promoted_run_id=promoted_run_id,
                rdp_package_id=rdp_package_id,
                requested_label=requested_label,
            )
            persisted_identities = {
                field_name: getattr(receipt, field_name) for field_name in identities
            }
            if persisted_identities != identities:
                return PromotionReceiptDecision(
                    False,
                    (
                        PromotionReceiptViolation(
                            "promotion_receipt_identity_context_mismatch",
                            "receipt must bind the exact owner, source run, promoted run, RDP, and label",
                            "promotion_identity",
                            ref,
                        ),
                    ),
                )
            try:
                snapshot = self._load_snapshot(**identities)
                current = self._build_receipt(snapshot=snapshot, **identities)
            except Exception as exc:  # noqa: BLE001 - unavailable proof remains red.
                return PromotionReceiptDecision(
                    False,
                    (
                        PromotionReceiptViolation(
                            "promotion_receipt_current_verification_unavailable",
                            f"current verification loader failed: {type(exc).__name__}",
                            "verification_loader",
                            ref,
                        ),
                    ),
                )
            shape = validate_promotion_receipt_shape(current)
            if not shape.accepted:
                return shape
            if current != receipt:
                return PromotionReceiptDecision(
                    False,
                    (
                        PromotionReceiptViolation(
                            "promotion_receipt_current_verification_drift",
                            "current canonical promotion proof no longer exactly matches the receipt",
                            "verification_snapshot",
                            ref,
                        ),
                    ),
                )
            return PromotionReceiptDecision(True, ())


__all__ = [
    "EXPECTED_GATE_BINDINGS",
    "GENERATED_ARTIFACT_INVENTORY_KEY",
    "GENERATED_ARTIFACT_NAMES",
    "PersistentPromotionReceiptRegistry",
    "PromotionCandidateProof",
    "PromotionGateVerification",
    "PromotionReceiptDecision",
    "PromotionReceiptViolation",
    "PromotionVerificationReceipt",
    "PromotionVerificationSnapshot",
    "RECEIPT_PREFIX",
    "RECEIPT_VERSION",
    "REQUIRED_GENERATED_ARTIFACT_NAMES",
    "VerificationLoader",
    "canonical_payload_sha256",
    "promotion_gate_verification_from_dict",
    "promotion_receipt_from_dict",
    "promotion_receipt_identity",
    "promotion_verification_snapshot_from_dict",
    "validate_promotion_receipt_shape",
]
