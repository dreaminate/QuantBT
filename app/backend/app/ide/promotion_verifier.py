"""Read-only, fail-closed verification of a published IDE promotion.

The loader deliberately treats ``run.json`` as a claim, not as the source of
producer authority.  Registered section payloads, producer status, source
identities, and the reproduction receipt are rebuilt or resolved from
owner-scoped canonical stores before the release evaluator and promote gate
chain are run again.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..delivery.rdp import PromotionClaim, RDPManifest
from ..lineage.spine import PROMOTION_LABELS
from ..release_gate.gate_registry import ensure_default_chain
from ..release_gate.promote_assembler import (
    AssembledSections,
    assemble_promote_sections,
    evaluate_run_releasable,
)
from ..research_os.rdp_reproduction import (
    PersistentRDPReproductionReceiptStore,
    reproduction_receipt_from_dict,
)
from .promotion_evidence import CanonicalPromotionEvidence
from .promotion_receipt import (
    EXPECTED_GATE_BINDINGS,
    GENERATED_ARTIFACT_INVENTORY_KEY,
    GENERATED_ARTIFACT_NAMES,
    PromotionCandidateProof,
    PromotionGateVerification,
    PromotionVerificationSnapshot,
    REQUIRED_GENERATED_ARTIFACT_NAMES,
    canonical_payload_sha256,
)


class PromotionVerificationError(ValueError):
    """The final run cannot be re-established from current canonical proof."""


# Only these typed-record attributes may become human-readable source refs.
# Free-form run fields, mapping keys, labels, timestamps, and arbitrary strings
# are intentionally excluded.  A dataclass with none of these identifiers gets
# a full content hash instead.
_SOURCE_ID_FIELDS = frozenset(
    {
        "approval_ref",
        "artifact_id",
        "artifact_ref",
        "baseline_ref",
        "binding_id",
        "call_id",
        "chain_ref",
        "check_id",
        "check_ref",
        "choice_id",
        "choice_ref",
        "claim_ref",
        "depth_ref",
        "disclosure_ref",
        "factor_ref",
        "generator_ref",
        "implementation_spec_id",
        "package_id",
        "performance_summary_ref",
        "qro_id",
        "rdp_id",
        "rdp_ref",
        "record_ref",
        "release_gate_ref",
        "release_ref",
        "review_ref",
        "runner_ref",
        "runtime_ref",
        "signal_ref",
        "strategy_book_ref",
        "theory_spec_id",
        "update_ref",
        "validation_id",
        "validation_ref",
    }
)

_SECTION_SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    EXPECTED_GATE_BINDINGS[0][1]: ("mathchain_claims",),
    EXPECTED_GATE_BINDINGS[1][1]: (
        "factor_library_entries",
        "factor_generators",
        "signal_protocols",
        "strategy_books",
    ),
    EXPECTED_GATE_BINDINGS[2][1]: (
        "validation_methodologies",
        "validation_depths",
    ),
    EXPECTED_GATE_BINDINGS[3][1]: ("tier_claims",),
    EXPECTED_GATE_BINDINGS[4][1]: (
        "expert_reviews",
        "release_gates",
        "release_checks",
        "pressure_runs",
        "release_approvals",
    ),
    EXPECTED_GATE_BINDINGS[5][1]: (
        "mock_records",
        "data_updates",
        "llm_calls",
        "theory_claims",
        "fatal_records",
        "performance_records",
    ),
    EXPECTED_GATE_BINDINGS[6][1]: (),
}


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PromotionVerificationError(f"{field_name} is required")
    return text


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PromotionVerificationError(f"run.json contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise PromotionVerificationError(f"run.json contains non-finite JSON number: {value}")


def _canonical_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_payload_sha256(_json_value(left)) == canonical_payload_sha256(
            _json_value(right)
        )
    except (TypeError, ValueError):
        return False


def _source_scalar_values(value: Any) -> tuple[str, ...]:
    values: Sequence[Any]
    if isinstance(value, (tuple, list, frozenset, set)):
        values = tuple(value)
    else:
        values = (value,)
    result: list[str] = []
    for item in values:
        if isinstance(item, Enum):
            item = item.value
        if isinstance(item, (str, int)) and not isinstance(item, bool):
            text = str(item).strip()
            if text:
                result.append(text)
    return tuple(result)


def _typed_record_source_refs(record: Any) -> tuple[str, ...]:
    """Extract allowlisted IDs, falling back to a content hash per record."""

    if not is_dataclass(record) or isinstance(record, type):
        raise PromotionVerificationError(
            "canonical promotion evidence contains a non-dataclass source record: "
            f"{type(record).__name__}"
        )

    refs: list[str] = []
    type_name = f"{type(record).__module__}.{type(record).__qualname__}"
    for field_name in _SOURCE_ID_FIELDS:
        if not hasattr(record, field_name):
            continue
        for value in _source_scalar_values(getattr(record, field_name)):
            refs.append(f"typed:{type_name}:{field_name}:{value}")

    nested_refs: list[str] = []
    for item in fields(record):
        value = getattr(record, item.name)
        if is_dataclass(value) and not isinstance(value, type):
            nested_refs.extend(_typed_record_source_refs(value))
            continue
        if isinstance(value, Mapping):
            for nested in value.values():
                if is_dataclass(nested) and not isinstance(nested, type):
                    nested_refs.extend(_typed_record_source_refs(nested))
            continue
        if isinstance(value, (tuple, list)):
            for nested in value:
                if is_dataclass(nested) and not isinstance(nested, type):
                    nested_refs.extend(_typed_record_source_refs(nested))

    refs.extend(nested_refs)
    if not refs:
        refs.append(
            f"typed_content_sha256:{type_name}:{canonical_payload_sha256(_json_value(record))}"
        )
    return tuple(dict.fromkeys(refs))


def _section_source_refs(
    manifest_key: str,
    evidence: CanonicalPromotionEvidence,
    *,
    rdp: RDPManifest,
    promotion: PromotionClaim,
    llm_records: tuple[Any, ...],
) -> tuple[str, ...]:
    records: list[Any] = []
    for field_name in _SECTION_SOURCE_FIELDS[manifest_key]:
        records.extend(tuple(getattr(evidence, field_name) or ()))
    if manifest_key == EXPECTED_GATE_BINDINGS[5][1]:
        records.extend(llm_records)
    if manifest_key == EXPECTED_GATE_BINDINGS[6][1]:
        records.extend((rdp, promotion))
    refs: list[str] = []
    for record in records:
        refs.extend(_typed_record_source_refs(record))
    return tuple(sorted(dict.fromkeys(refs)))


class CanonicalPromotionVerificationLoader:
    """Callable used by ``PersistentPromotionReceiptRegistry``.

    All dependencies are read-only.  The callable accepts only stable promotion
    identities and returns a snapshot whose proof fields are reconstructed from
    server-owned stores.
    """

    def __init__(
        self,
        *,
        run_root: str | Path,
        rdp_store: Any,
        promotion_evidence_resolver: Any,
        llm_call_record_store: Any = None,
        reproduction_receipt_store_provider: Any = None,
    ) -> None:
        self._run_root = Path(run_root)
        self._rdp_store = rdp_store
        self._promotion_evidence_resolver = promotion_evidence_resolver
        self._llm_call_record_store = llm_call_record_store
        self._reproduction_receipt_store_provider = (
            reproduction_receipt_store_provider
        )

    def _reproduction_receipt_store(
        self,
    ) -> PersistentRDPReproductionReceiptStore | None:
        provider = self._reproduction_receipt_store_provider
        if provider is None:
            return None
        try:
            store = provider() if callable(provider) else provider
        except Exception as exc:  # noqa: BLE001 - unavailable authority is red.
            raise PromotionVerificationError(
                "RDP reproduction receipt authority provider failed"
            ) from exc
        if not isinstance(store, PersistentRDPReproductionReceiptStore):
            raise PromotionVerificationError(
                "RDP reproduction receipt authority is not the trusted persistent store"
            )
        return store

    @staticmethod
    def _verify_current_reproduction_receipt(
        stored: Mapping[str, Any],
        *,
        store: PersistentRDPReproductionReceiptStore,
        owner_user_id: str,
        rdp: RDPManifest,
        source_result_content_hash: str,
    ) -> None:
        raw = stored.get("rdp_reproduction_receipt")
        if not isinstance(raw, Mapping):
            raise PromotionVerificationError(
                "final run lacks a structured RDP reproduction receipt"
            )
        try:
            claimed = reproduction_receipt_from_dict(raw)
            authoritative = store.current_passed(
                owner_user_id=owner_user_id,
                manifest=rdp,
                source_result_content_hash=source_result_content_hash,
            )
        except Exception as exc:  # noqa: BLE001 - failed authority lookup is red.
            raise PromotionVerificationError(
                "current RDP reproduction receipt authority lookup failed"
            ) from exc
        if authoritative != claimed:
            raise PromotionVerificationError(
                "final run RDP reproduction receipt differs from trusted authority"
            )

    @staticmethod
    def _directory_flags() -> int:
        if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
            raise PromotionVerificationError(
                "safe promotion verification requires O_DIRECTORY and O_NOFOLLOW"
            )
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        return flags

    def _open_run_root(self) -> int:
        try:
            expected = self._run_root.lstat()
        except OSError as exc:
            raise PromotionVerificationError("run_root is unavailable") from exc
        if stat.S_ISLNK(expected.st_mode) or not stat.S_ISDIR(expected.st_mode):
            raise PromotionVerificationError(
                "run_root must be a real no-follow directory"
            )
        try:
            root_fd = os.open(self._run_root, self._directory_flags())
        except OSError as exc:
            raise PromotionVerificationError("run_root is unavailable") from exc
        opened = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (expected.st_dev, expected.st_ino)
        ):
            os.close(root_fd)
            raise PromotionVerificationError(
                "run_root identity changed while opening"
            )
        return root_fd

    @staticmethod
    def _read_run_json(run_fd: int, *, missing_message: str) -> bytes:
        file_fd: int | None = None
        try:
            file_fd = os.open(
                "run.json",
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=run_fd,
            )
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise PromotionVerificationError(
                    "verified run.json is not a regular file"
                )
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = None
                return handle.read()
        except OSError as exc:
            raise PromotionVerificationError(missing_message) from exc
        finally:
            if file_fd is not None:
                os.close(file_fd)

    @staticmethod
    def _generated_artifact_inventory(
        manifest: Mapping[str, Any],
    ) -> dict[str, tuple[int, str]]:
        raw = manifest.get(GENERATED_ARTIFACT_INVENTORY_KEY)
        if not isinstance(raw, Mapping):
            raise PromotionVerificationError(
                "run.json generated artifact inventory is missing or malformed"
            )
        names = set(raw)
        allowed = set(GENERATED_ARTIFACT_NAMES)
        required = set(REQUIRED_GENERATED_ARTIFACT_NAMES)
        if not required.issubset(names) or not names.issubset(allowed):
            raise PromotionVerificationError(
                "run.json generated artifact inventory has an invalid exact name set"
            )
        inventory: dict[str, tuple[int, str]] = {}
        for artifact_name in GENERATED_ARTIFACT_NAMES:
            if artifact_name not in raw:
                continue
            descriptor = raw[artifact_name]
            if not isinstance(descriptor, Mapping) or set(descriptor) != {
                "size_bytes",
                "sha256",
            }:
                raise PromotionVerificationError(
                    f"generated artifact descriptor is malformed: {artifact_name}"
                )
            size_bytes = descriptor.get("size_bytes")
            sha256 = descriptor.get("sha256")
            if (
                not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or size_bytes < 0
            ):
                raise PromotionVerificationError(
                    f"generated artifact size is invalid: {artifact_name}"
                )
            if (
                not isinstance(sha256, str)
                or sha256 != sha256.strip()
                or len(sha256) != 64
                or any(char not in "0123456789abcdef" for char in sha256)
            ):
                raise PromotionVerificationError(
                    f"generated artifact SHA-256 is invalid: {artifact_name}"
                )
            inventory[artifact_name] = (size_bytes, sha256)
        return inventory

    def _verify_generated_artifacts(self, run_fd: int, run_bytes: bytes) -> None:
        manifest = self._decode_manifest(run_bytes)
        inventory = self._generated_artifact_inventory(manifest)
        expected_entries = {"run.json", *inventory}
        if os.listdir not in os.supports_fd:
            raise PromotionVerificationError(
                "safe direct artifact inventory listing is unavailable"
            )
        try:
            observed_entries = set(os.listdir(run_fd))
        except OSError as exc:
            raise PromotionVerificationError(
                "generated artifact directory could not be listed"
            ) from exc
        if observed_entries != expected_entries:
            raise PromotionVerificationError(
                "generated artifact directory does not match the exact inventory"
            )

        read_flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            read_flags |= os.O_CLOEXEC
        for artifact_name, (expected_size, expected_sha256) in inventory.items():
            artifact_fd: int | None = None
            try:
                artifact_fd = os.open(
                    artifact_name,
                    read_flags,
                    dir_fd=run_fd,
                )
                before = os.fstat(artifact_fd)
                if not stat.S_ISREG(before.st_mode):
                    raise PromotionVerificationError(
                        f"generated artifact is not a regular file: {artifact_name}"
                    )
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(artifact_fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(artifact_fd)
                if (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                ) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise PromotionVerificationError(
                        f"generated artifact changed while reading: {artifact_name}"
                    )
                payload = b"".join(chunks)
                if before.st_size != expected_size or len(payload) != expected_size:
                    raise PromotionVerificationError(
                        f"generated artifact size mismatch: {artifact_name}"
                    )
                if hashlib.sha256(payload).hexdigest() != expected_sha256:
                    raise PromotionVerificationError(
                        f"generated artifact hash mismatch: {artifact_name}"
                    )
            except OSError as exc:
                raise PromotionVerificationError(
                    f"generated artifact is missing, linked, or unreadable: {artifact_name}"
                ) from exc
            finally:
                if artifact_fd is not None:
                    os.close(artifact_fd)

        try:
            final_entries = set(os.listdir(run_fd))
        except OSError as exc:
            raise PromotionVerificationError(
                "generated artifact directory could not be relisted"
            ) from exc
        if final_entries != expected_entries:
            raise PromotionVerificationError(
                "generated artifact directory changed during verification"
            )

    def _load_run_bytes(self, promoted_run_id: str) -> bytes:
        token = _required_text(promoted_run_id, "promoted_run_id")
        if (
            token in {".", ".."}
            or Path(token).name != token
            or "/" in token
            or "\\" in token
            or "\x00" in token
        ):
            raise PromotionVerificationError(
                "promoted_run_id must name one direct run_root child"
            )

        root_fd = self._open_run_root()
        run_fd: int | None = None
        try:
            run_fd = os.open(
                token,
                self._directory_flags(),
                dir_fd=root_fd,
            )
            run_bytes = self._read_run_json(
                run_fd,
                missing_message=(
                    "final run.json is missing, linked, or not a direct run child"
                ),
            )
            self._verify_generated_artifacts(run_fd, run_bytes)
            return run_bytes
        except OSError as exc:
            raise PromotionVerificationError(
                "final run.json is missing, linked, or not a direct run child"
            ) from exc
        finally:
            if run_fd is not None:
                os.close(run_fd)
            os.close(root_fd)

    def _load_candidate_run_bytes(
        self,
        candidate: PromotionCandidateProof,
    ) -> bytes:
        if not isinstance(candidate, PromotionCandidateProof):
            raise PromotionVerificationError(
                "candidate must be PromotionCandidateProof"
            )
        root_fd = self._open_run_root()
        staging_fd: int | None = None
        candidate_fd: int | None = None
        try:
            try:
                staging_expected = os.stat(
                    ".staging",
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise PromotionVerificationError(
                    "promotion staging root is unavailable"
                ) from exc
            if stat.S_ISLNK(staging_expected.st_mode) or not stat.S_ISDIR(
                staging_expected.st_mode
            ):
                raise PromotionVerificationError(
                    "promotion staging root must be a real directory"
                )
            staging_fd = os.open(
                ".staging",
                self._directory_flags(),
                dir_fd=root_fd,
            )
            staging_opened = os.fstat(staging_fd)
            if (
                not stat.S_ISDIR(staging_opened.st_mode)
                or (staging_opened.st_dev, staging_opened.st_ino)
                != (staging_expected.st_dev, staging_expected.st_ino)
            ):
                raise PromotionVerificationError(
                    "promotion staging root identity changed while opening"
                )

            try:
                candidate_expected = os.stat(
                    candidate.staging_name,
                    dir_fd=staging_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise PromotionVerificationError(
                    "promotion candidate is unavailable"
                ) from exc
            if (
                stat.S_ISLNK(candidate_expected.st_mode)
                or not stat.S_ISDIR(candidate_expected.st_mode)
                or (candidate_expected.st_dev, candidate_expected.st_ino)
                != (candidate.st_dev, candidate.st_ino)
            ):
                raise PromotionVerificationError(
                    "promotion candidate identity mismatch"
                )
            candidate_fd = os.open(
                candidate.staging_name,
                self._directory_flags(),
                dir_fd=staging_fd,
            )
            candidate_opened = os.fstat(candidate_fd)
            if (
                not stat.S_ISDIR(candidate_opened.st_mode)
                or (candidate_opened.st_dev, candidate_opened.st_ino)
                != (candidate.st_dev, candidate.st_ino)
            ):
                raise PromotionVerificationError(
                    "promotion candidate identity changed while opening"
                )
            raw = self._read_run_json(
                candidate_fd,
                missing_message="candidate run.json is missing or linked",
            )
            if hashlib.sha256(raw).hexdigest() != candidate.run_manifest_sha256:
                raise PromotionVerificationError(
                    "promotion candidate manifest hash mismatch"
                )
            self._verify_generated_artifacts(candidate_fd, raw)
            return raw
        finally:
            if candidate_fd is not None:
                os.close(candidate_fd)
            if staging_fd is not None:
                os.close(staging_fd)
            os.close(root_fd)

    @staticmethod
    def _decode_manifest(raw_bytes: bytes) -> dict[str, Any]:
        try:
            decoded = raw_bytes.decode("utf-8")
            raw = json.loads(
                decoded,
                object_pairs_hook=_no_duplicate_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PromotionVerificationError("final run.json is not strict UTF-8 JSON") from exc
        if not isinstance(raw, dict):
            raise PromotionVerificationError("final run.json must contain one object")
        return raw

    def _load_rdp(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        rdp_package_id: str,
    ) -> RDPManifest:
        if self._rdp_store is None or not hasattr(self._rdp_store, "manifest"):
            raise PromotionVerificationError("canonical owner-scoped RDP store is unavailable")
        try:
            rdp = self._rdp_store.manifest(
                rdp_package_id,
                owner_user_id=owner_user_id,
            )
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            raise PromotionVerificationError(
                "RDP does not resolve in the requested owner scope"
            ) from exc
        if not isinstance(rdp, RDPManifest):
            raise PromotionVerificationError("RDP store returned a non-canonical manifest")
        if rdp.package_id != rdp_package_id:
            raise PromotionVerificationError("RDP store returned a different package identity")
        expected_asset_ref = f"ide_run:{source_ide_run_id}"
        if rdp.asset_ref != expected_asset_ref:
            raise PromotionVerificationError(
                "RDP does not bind the exact source IDE run"
            )
        return rdp

    def _llm_records(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        strategy_name: str,
    ) -> tuple[tuple[Any, ...], bytes | None]:
        store = self._llm_call_record_store
        if store is None:
            return (), None
        if not hasattr(store, "llm_records_for"):
            raise PromotionVerificationError(
                "LLM call record store must expose owner-scoped llm_records_for"
            )
        refs = (
            promoted_run_id,
            source_ide_run_id,
            f"ide_run:{source_ide_run_id}",
            f"strategy:{strategy_name}",
        )
        by_call_id: dict[str, Any] = {}
        try:
            for ref in refs:
                for record in store.llm_records_for(ref, owner_user_id=owner_user_id):
                    if str(getattr(record, "owner_user_id", "") or "") != owner_user_id:
                        raise PromotionVerificationError(
                            "LLM store returned a record from another owner"
                        )
                    call_id = _required_text(
                        getattr(record, "call_id", ""),
                        "LLMCallRecord.call_id",
                    )
                    existing = by_call_id.get(call_id)
                    if existing is not None and existing != record:
                        raise PromotionVerificationError(
                            "LLM call identity resolves to conflicting owner records"
                        )
                    by_call_id[call_id] = record
        except PromotionVerificationError:
            raise
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            raise PromotionVerificationError("owner-scoped LLM evidence lookup failed") from exc
        # Match the production resolver's stable first-seen order.  Re-sorting
        # here could change release outcome ordering and create false drift.
        records = tuple(by_call_id.values())
        if not records:
            return (), None
        secret = getattr(store, "seal_secret", None)
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise PromotionVerificationError(
                "LLM evidence exists but the in-memory gateway seal secret is unavailable"
            )
        return records, secret

    @staticmethod
    def _assemble(
        manifest: Mapping[str, Any],
        evidence: CanonicalPromotionEvidence,
        *,
        rdp: RDPManifest,
        promotion: PromotionClaim,
    ) -> AssembledSections:
        return assemble_promote_sections(
            manifest,
            mathchain_claims=evidence.mathchain_claims,
            factor_library_entries=evidence.factor_library_entries,
            factor_generators=evidence.factor_generators,
            signal_protocols=evidence.signal_protocols,
            strategy_books=evidence.strategy_books,
            validation_methodologies=evidence.validation_methodologies,
            validation_depths=evidence.validation_depths,
            tier_claims=evidence.tier_claims,
            rdp=rdp,
            promotion=promotion,
            expert_reviews=evidence.expert_reviews,
            release_gates=evidence.release_gates,
            release_checks=evidence.release_checks,
            pressure_runs=evidence.pressure_runs,
            release_approvals=evidence.release_approvals,
            mock_records=evidence.mock_records,
            data_updates=evidence.data_updates,
            llm_calls=evidence.llm_calls,
            theory_claims=evidence.theory_claims,
            fatal_records=evidence.fatal_records,
            performance_records=evidence.performance_records,
            verified_producer_keys=evidence.verified_producer_keys,
        )

    @staticmethod
    def _bridge_gaps(manifest: Mapping[str, Any]) -> tuple[str, ...]:
        bridge = manifest.get("research_promote_bridge")
        if bridge is None:
            return ()
        if not isinstance(bridge, Mapping):
            raise PromotionVerificationError("research_promote_bridge must be an object")
        gaps = bridge.get("honest_gaps", ())
        if not isinstance(gaps, (tuple, list)) or any(
            not isinstance(item, str) or not item.strip() for item in gaps
        ):
            raise PromotionVerificationError(
                "research_promote_bridge.honest_gaps must be a list of non-empty strings"
            )
        return tuple(item.strip() for item in gaps)

    @staticmethod
    def _normalized_release_verdict(
        evaluation: Mapping[str, Any], *, unresolved: tuple[str, ...]
    ) -> dict[str, Any]:
        payload = dict(evaluation)
        all_unresolved = list(unresolved)
        release_honest_gaps = evaluation.get("honest_gaps", ())
        if isinstance(release_honest_gaps, (tuple, list)):
            all_unresolved.extend(
                str(item) for item in release_honest_gaps if str(item)
            )
        elif release_honest_gaps:
            raise PromotionVerificationError(
                "release evaluation honest_gaps is malformed"
            )
        unresolved = tuple(dict.fromkeys(all_unresolved))
        gate_evaluation_ok = evaluation.get("ok") is True
        release_ready = gate_evaluation_ok and not unresolved
        payload.update(
            {
                "gate_evaluation_ok": gate_evaluation_ok,
                "ok": release_ready,
                "release_ready": release_ready,
                "readiness": "ready" if release_ready else "unverified",
                "unresolved_required_inputs": list(unresolved),
                "reason": (
                    "release gates rejected the candidate"
                    if not gate_evaluation_ok
                    else "canonical promote evidence retains unresolved required inputs"
                ),
            }
        )
        return payload

    @staticmethod
    def _normalized_chain(
        chain_result: Any, *, release_ready: bool
    ) -> dict[str, Any]:
        payload = chain_result.to_dict()
        verdicts = payload.get("verdicts")
        if not isinstance(verdicts, list) or any(
            not isinstance(verdict, Mapping) for verdict in verdicts
        ):
            raise PromotionVerificationError("gate chain returned malformed verdicts")
        all_green = bool(verdicts) and all(
            verdict.get("producer_green") is True for verdict in verdicts
        )
        payload["all_registered_producers_green"] = all_green
        payload["release_ready"] = bool(
            not bool(getattr(chain_result, "rejected", True))
            and all_green
            and release_ready
        )
        return payload

    def __call__(
        self,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
    ) -> PromotionVerificationSnapshot:
        return self._verify_run_bytes(
            owner_user_id,
            source_ide_run_id,
            promoted_run_id,
            rdp_package_id,
            requested_label,
            run_bytes=self._load_run_bytes(promoted_run_id),
        )

    def verify_candidate(
        self,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
        *,
        candidate: PromotionCandidateProof,
    ) -> PromotionVerificationSnapshot:
        """Verify a content-bound hidden ``.staging`` candidate."""

        return self._verify_run_bytes(
            owner_user_id,
            source_ide_run_id,
            promoted_run_id,
            rdp_package_id,
            requested_label,
            run_bytes=self._load_candidate_run_bytes(candidate),
        )

    def _verify_run_bytes(
        self,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
        *,
        run_bytes: bytes,
    ) -> PromotionVerificationSnapshot:
        owner = _required_text(owner_user_id, "owner_user_id")
        source_run = _required_text(source_ide_run_id, "source_ide_run_id")
        promoted_run = _required_text(promoted_run_id, "promoted_run_id")
        rdp_id = _required_text(rdp_package_id, "rdp_package_id")
        label = _required_text(requested_label, "requested_label")
        if label not in PROMOTION_LABELS:
            raise PromotionVerificationError("requested promotion label is unknown")

        stored = self._decode_manifest(run_bytes)
        if stored.get("run_id") != promoted_run:
            raise PromotionVerificationError("run.json run_id does not match its final directory")
        source = stored.get("source")
        if not isinstance(source, Mapping):
            raise PromotionVerificationError("run.json source must be an object")
        if source.get("ide_run_id") != source_run:
            raise PromotionVerificationError("run.json source IDE identity mismatch")
        if source.get("owner_user_id") != owner:
            raise PromotionVerificationError("run.json source owner mismatch")
        owner_username = _required_text(source.get("owner_username"), "source.owner_username")
        source_result_content_hash = _required_text(
            source.get("result_content_hash"),
            "source.result_content_hash",
        )
        if stored.get("rdp_package_id") != rdp_id:
            raise PromotionVerificationError("run.json RDP identity mismatch")
        if stored.get("requested_label") != label:
            raise PromotionVerificationError("run.json requested label mismatch")

        rdp = self._load_rdp(
            owner_user_id=owner,
            source_ide_run_id=source_run,
            rdp_package_id=rdp_id,
        )
        reproduction_receipt_store = self._reproduction_receipt_store()
        if reproduction_receipt_store is not None:
            self._verify_current_reproduction_receipt(
                stored,
                store=reproduction_receipt_store,
                owner_user_id=owner,
                rdp=rdp,
                source_result_content_hash=source_result_content_hash,
            )
        promotion = PromotionClaim(
            asset_ref=f"ide_run:{source_run}",
            asset_kind=rdp.asset_kind,
            rdp_ref=rdp.package_id,
            requested_stage="formal_run",
            actor=owner_username,
        )
        try:
            evidence = self._promotion_evidence_resolver.resolve(
                owner_user_id=owner,
                source_ide_run_id=source_run,
                requested_label=label,
                rdp=rdp,
                source_result_content_hash=source_result_content_hash,
            )
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            raise PromotionVerificationError(
                "canonical promotion evidence resolution failed"
            ) from exc
        if not isinstance(evidence, CanonicalPromotionEvidence):
            raise PromotionVerificationError(
                "promotion evidence resolver returned a non-canonical record"
            )

        llm_records, gateway_secret = self._llm_records(
            owner_user_id=owner,
            source_ide_run_id=source_run,
            promoted_run_id=promoted_run,
            strategy_name=_required_text(stored.get("strategy_name"), "strategy_name"),
        )

        manifest_keys = {binding[1] for binding in EXPECTED_GATE_BINDINGS}
        base_manifest = {
            key: value
            for key, value in stored.items()
            if key
            not in manifest_keys
            | {
                "release_verdict",
                "promote_gate_chain",
                "section_assembly",
                "producer_status",
            }
        }
        try:
            assembly = self._assemble(
                base_manifest,
                evidence,
                rdp=rdp,
                promotion=promotion,
            )
        except Exception as exc:  # noqa: BLE001 - canonical assembly is a hard boundary.
            raise PromotionVerificationError(
                f"canonical section assembly failed: {type(exc).__name__}"
            ) from exc

        expected_assembly_meta = {
            "emitted": list(assembly.emitted),
            "absent": list(assembly.absent),
            "honest_gaps": list(assembly.honest_gaps),
        }
        if not _canonical_equal(stored.get("section_assembly"), expected_assembly_meta):
            raise PromotionVerificationError("stored section assembly ledger mismatch")

        for _section, manifest_key, _producer_key, _gate_name in EXPECTED_GATE_BINDINGS:
            if manifest_key not in assembly.sections:
                raise PromotionVerificationError(
                    f"canonical assembly is missing registered section {manifest_key}"
                )
            if not _canonical_equal(stored.get(manifest_key), assembly.sections[manifest_key]):
                raise PromotionVerificationError(
                    f"stored registered section payload mismatch: {manifest_key}"
                )

        canonical_manifest = assembly.apply_to(base_manifest)
        canonical_manifest["section_assembly"] = expected_assembly_meta
        bridge_gaps = self._bridge_gaps(canonical_manifest)
        try:
            release_evaluation = evaluate_run_releasable(
                canonical_manifest,
                owner_user_id=owner,
                llm_used=True if llm_records else None,
                llm_call_records=llm_records or None,
                gateway_secret=gateway_secret,
            ).to_dict()
        except Exception as exc:  # noqa: BLE001 - an unevaluated release remains red.
            raise PromotionVerificationError(
                f"fresh release evaluation failed: {type(exc).__name__}"
            ) from exc
        release_payload = self._normalized_release_verdict(
            release_evaluation,
            unresolved=bridge_gaps,
        )
        if not _canonical_equal(stored.get("release_verdict"), release_payload):
            raise PromotionVerificationError(
                "stored release verdict does not match fresh evaluation"
            )
        canonical_manifest["release_verdict"] = release_payload

        try:
            producer_status = assembly.producer_status()
            chain = (
                ensure_default_chain(
                    reproduction_receipt_store=reproduction_receipt_store
                )
                if reproduction_receipt_store is not None
                else ensure_default_chain()
            )
            chain_result = chain.evaluate(
                canonical_manifest,
                producer_status=producer_status,
            )
        except Exception as exc:  # noqa: BLE001 - an unevaluated chain remains red.
            raise PromotionVerificationError(
                f"fresh promote gate chain failed: {type(exc).__name__}"
            ) from exc
        chain_payload = self._normalized_chain(
            chain_result,
            release_ready=release_payload["release_ready"] is True,
        )
        if not _canonical_equal(stored.get("promote_gate_chain"), chain_payload):
            raise PromotionVerificationError(
                "stored promote gate chain does not match fresh evaluation"
            )

        verdict_rows = chain_payload.get("verdicts", [])
        by_gate: dict[str, Mapping[str, Any]] = {}
        for verdict in verdict_rows:
            gate_name = _required_text(verdict.get("gate_name"), "gate verdict name")
            if gate_name in by_gate:
                raise PromotionVerificationError(f"duplicate gate verdict: {gate_name}")
            by_gate[gate_name] = verdict
        expected_gate_names = {binding[3] for binding in EXPECTED_GATE_BINDINGS}
        if set(by_gate) != expected_gate_names:
            raise PromotionVerificationError(
                "fresh gate chain did not cover the exact registered set"
            )

        section_verifications: list[PromotionGateVerification] = []
        global_residuals: list[str] = []
        global_residuals.extend(str(item) for item in evidence.honest_gaps)
        global_residuals.extend(str(item) for item in assembly.honest_gaps)
        global_residuals.extend(bridge_gaps)
        release_honest_gaps = release_evaluation.get("honest_gaps", ())
        if isinstance(release_honest_gaps, (tuple, list)):
            global_residuals.extend(str(item) for item in release_honest_gaps if str(item))
        elif release_honest_gaps:
            raise PromotionVerificationError("release evaluation honest_gaps is malformed")

        for section, manifest_key, producer_key, gate_name in EXPECTED_GATE_BINDINGS:
            verdict = by_gate[gate_name]
            source_refs = _section_source_refs(
                manifest_key,
                evidence,
                rdp=rdp,
                promotion=promotion,
                llm_records=llm_records,
            )
            if not source_refs:
                raise PromotionVerificationError(
                    f"registered gate {gate_name} has no server-derived canonical source refs"
                )
            missing_raw = verdict.get("missing", ())
            if not isinstance(missing_raw, (tuple, list)):
                raise PromotionVerificationError(
                    f"gate {gate_name} returned malformed missing refs"
                )
            missing = tuple(str(item) for item in missing_raw if str(item))
            residuals: list[str] = []
            if verdict.get("advisory_or_enforce") != "enforce":
                residuals.append("gate_not_enforcing")
            if verdict.get("ok") is not True:
                residuals.append("gate_not_passed")
            if verdict.get("producer_green") is not True:
                residuals.append("canonical_producer_not_green")
            if verdict.get("errored") is not False:
                residuals.append("gate_evaluation_errored")
            if missing:
                residuals.append("gate_missing_evidence")
            if residuals:
                global_residuals.extend(f"{gate_name}:{item}" for item in residuals)
            section_verifications.append(
                PromotionGateVerification(
                    section=section,
                    manifest_key=manifest_key,
                    producer_key=producer_key,
                    gate_name=gate_name,
                    canonical_source_refs=source_refs,
                    assembled_payload_sha256=canonical_payload_sha256(
                        _json_value(assembly.sections[manifest_key])
                    ),
                    gate_verdict_sha256=canonical_payload_sha256(_json_value(verdict)),
                    mode=str(verdict.get("advisory_or_enforce") or ""),
                    ok=verdict.get("ok") is True,
                    producer_green=verdict.get("producer_green") is True,
                    errored=verdict.get("errored") is not False,
                    missing=missing,
                    residuals=tuple(residuals),
                )
            )

        release_ok = release_payload.get("gate_evaluation_ok") is True
        release_ready = release_payload.get("release_ready") is True
        chain_rejected = bool(getattr(chain_result, "rejected", True))
        chain_release_ready = chain_payload.get("release_ready") is True
        if not release_ok:
            global_residuals.append("release_evaluation_not_ok")
        if not release_ready:
            global_residuals.append("release_not_ready")
        if chain_rejected:
            global_residuals.append("promote_gate_chain_rejected")
        if not chain_release_ready:
            global_residuals.append("promote_gate_chain_not_ready")
        residuals = tuple(dict.fromkeys(item for item in global_residuals if item))

        return PromotionVerificationSnapshot(
            section_verifications=tuple(section_verifications),
            release_verdict_sha256=canonical_payload_sha256(_json_value(release_payload)),
            gate_chain_sha256=canonical_payload_sha256(_json_value(chain_payload)),
            run_manifest_sha256=hashlib.sha256(run_bytes).hexdigest(),
            outcome="passed" if not residuals else "failed",
            release_ok=release_ok,
            release_ready=release_ready,
            chain_rejected=chain_rejected,
            chain_release_ready=chain_release_ready,
            errors=(),
            residuals=residuals,
        )


__all__ = [
    "CanonicalPromotionVerificationLoader",
    "PromotionVerificationError",
]
