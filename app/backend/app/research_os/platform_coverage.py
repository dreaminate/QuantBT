"""GOAL §14 M1-M21 platform coverage contracts."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from ..cross_process_lock import acquire_exclusive_fd
from .goal_proof_head_lock import acquire_goal_proof_head_lock

from .ref_resolution import (
    RealRefResolver as RealPlatformCoverageRefResolver,
    RefResolver as PlatformCoverageRefResolver,
    build_real_ref_resolver as build_real_platform_coverage_resolver,
    is_placeholder_ref,
    resolve_typed_ref,
)


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


def _str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _tuple(value) if str(item or "").strip())


class PlatformRow(str, Enum):
    M1_M2 = "M1-M2"
    M3 = "M3"
    M4_M5 = "M4-M5"
    M6 = "M6"
    M7_M8 = "M7-M8"
    M9 = "M9"
    M10 = "M10"
    M11 = "M11"
    M12 = "M12"
    M13 = "M13"
    M14 = "M14"
    M15 = "M15"
    M16 = "M16"
    M17 = "M17"
    M18 = "M18"
    M19 = "M19"
    M20 = "M20"
    M21 = "M21"


REQUIRED_PLATFORM_ROWS = tuple(row.value for row in PlatformRow)

SPECIFIC_REQUIRED_REFS: dict[str, tuple[str, ...]] = {
    PlatformRow.M1_M2.value: (
        "strategy_goal_ref",
        "hypothesis_card_ref",
        "universe_definition_ref",
        "regime_scenario_ref",
    ),
    PlatformRow.M3.value: ("ingestion_skill_ref", "instrument_spec_ref"),
    PlatformRow.M4_M5.value: ("factor_ref", "label_ref"),
    PlatformRow.M6.value: ("model_passport_ref", "validation_dossier_ref"),
    PlatformRow.M7_M8.value: (
        "signal_contract_ref",
        "signal_validation_ref",
        "strategy_book_ref",
        "portfolio_policy_ref",
    ),
    PlatformRow.M9.value: ("execution_boundary_ref", "market_capability_matrix_ref"),
    PlatformRow.M10.value: (
        "backtest_run_ref",
        "validation_methodology_ref",
        "validation_depth_ref",
        "attribution_ref",
        "monitor_ref",
    ),
    PlatformRow.M11.value: ("governed_asset_ref", "lifecycle_transition_ref"),
    PlatformRow.M12.value: (
        "model_passport_ref",
        "model_promotion_ref",
        "approval_ref",
        "recertification_ref",
    ),
    PlatformRow.M13.value: (
        "dag_run_ref",
        "checkpoint_ref",
        "replay_ref",
        "fork_ref",
        "rollback_ref",
    ),
    PlatformRow.M14.value: (
        "llm_gateway_ref",
        "model_routing_policy_ref",
        "credential_pool_ref",
        "theory_implementation_binding_ref",
    ),
    PlatformRow.M15.value: ("typed_canvas_projection_ref",),
    PlatformRow.M16.value: (
        "shared_asset_ref",
        "permission_ref",
        "source_ref",
        "status_ref",
    ),
    PlatformRow.M17.value: (
        "copy_trade_subscription_ref",
        "runtime_promotion_ref",
        "risk_gate_ref",
        "execution_audit_ref",
    ),
    PlatformRow.M18.value: ("canonical_code_command_ref", "consistency_check_ref"),
    PlatformRow.M19.value: (
        "tutorial_asset_ref",
        "weakness_disclosure_ref",
        "teaching_evidence_ref",
    ),
    PlatformRow.M20.value: ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
    PlatformRow.M21.value: ("mock_label_ref", "asset_category_ref"),
}

SPECIFIC_REF_PREFIXES: dict[str, tuple[str, ...]] = {
    "strategy_goal_ref": ("strategy_goal:", "goal:"),
    "hypothesis_card_ref": ("hypothesis:", "hypothesis_card:"),
    "universe_definition_ref": ("universe:",),
    "regime_scenario_ref": ("regime:", "scenario:"),
    "ingestion_skill_ref": ("ingestion_skill:",),
    "instrument_spec_ref": ("instrument_spec:", "instrument:"),
    "factor_ref": ("factor:",),
    "label_ref": ("label:",),
    "model_passport_ref": ("model_passport:", "model_passport_"),
    "validation_dossier_ref": ("validation_dossier:",),
    "signal_contract_ref": ("signal_contract:", "sig::"),
    "signal_validation_ref": ("signal_validation_", "signal_validation:"),
    "strategy_book_ref": ("strategy_book:",),
    "portfolio_policy_ref": ("portfolio_policy:", "portfolio:"),
    "execution_boundary_ref": (
        "execution_boundary:",
        "execution_policy:",
        "execution_closure_receipt:",
    ),
    "market_capability_matrix_ref": ("market_capability_matrix:", "capability:"),
    "backtest_run_ref": ("backtest_run:", "qro_"),
    "validation_methodology_ref": ("validation_methodology:", "methodology:"),
    "validation_depth_ref": ("validation_depth:",),
    "attribution_ref": ("attribution:",),
    "monitor_ref": ("monitor:",),
    "governed_asset_ref": ("governed_asset:",),
    "lifecycle_transition_ref": ("lifecycle_transition:",),
    "model_promotion_ref": ("model_promotion:", "gate-"),
    "approval_ref": ("approval:", "gate-"),
    "recertification_ref": ("recertification:", "model_recertification_"),
    "dag_run_ref": ("dag_run:",),
    "checkpoint_ref": ("checkpoint:",),
    "replay_ref": ("replay:",),
    "fork_ref": ("fork:",),
    "rollback_ref": ("rollback:",),
    "llm_gateway_ref": ("llm_gateway:",),
    "model_routing_policy_ref": ("model_routing_policy:", "routing:"),
    "credential_pool_ref": ("credential_pool:", "pool:"),
    "theory_implementation_binding_ref": ("tib_",),
    "typed_canvas_projection_ref": ("rgproj_", "typed_canvas_projection:"),
    "shared_asset_ref": ("shared_asset:",),
    "permission_ref": ("permission:",),
    "source_ref": ("source:", "datasource:"),
    "status_ref": ("status:",),
    "copy_trade_subscription_ref": ("copy_trade_subscription_",),
    "runtime_promotion_ref": ("runtime_promotion_", "runtime_promotion:"),
    "risk_gate_ref": ("copy_risk_check_",),
    "execution_audit_ref": ("copy_submission_audit_",),
    "canonical_code_command_ref": ("rgcmd_", "canonical_code_command:"),
    "consistency_check_ref": ("cc_",),
    "tutorial_asset_ref": ("tutorial_asset:",),
    "weakness_disclosure_ref": ("weakness_disclosure:",),
    "teaching_evidence_ref": ("teaching_evidence:",),
    "secret_ref": ("secret:", "secretref:", "tokenref:"),
    "kill_switch_ref": ("kill_switch:", "account_halt_"),
    "mock_label_ref": ("mock_label:",),
    "asset_category_ref": ("asset_category:",),
}


@dataclass(frozen=True)
class PlatformCoverageViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class PlatformCoverageDecision:
    accepted: bool
    violations: tuple[PlatformCoverageViolation, ...]


class PlatformCoverageCommitUncertain(RuntimeError):
    """A manifest append failed and byte-exact durable rollback is unverified."""


@dataclass(frozen=True)
class PlatformSpecificRef:
    key: str
    ref: str


@dataclass(frozen=True)
class PlatformCapabilityRecord:
    m_row: PlatformRow | str
    qro_ref: str | None
    research_graph_ref: str | None
    lifecycle_ref: str | None
    governance_ref: str | None
    rag_ref: str | None
    math_spine_ref: str | None
    evidence_refs: tuple[str, ...]
    specific_refs: tuple[PlatformSpecificRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        object.__setattr__(self, "specific_refs", _tuple(self.specific_refs))


def _row_value(row: PlatformRow | str) -> str:
    if isinstance(row, PlatformRow):
        return row.value
    return str(row)


def validate_platform_capability(record: PlatformCapabilityRecord) -> PlatformCoverageDecision:
    violations: list[PlatformCoverageViolation] = []
    row = _row_value(record.m_row)
    for field_name in (
        "qro_ref",
        "research_graph_ref",
        "lifecycle_ref",
        "governance_ref",
        "rag_ref",
        "math_spine_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_missing_common_ref",
                    "M1-M21 capabilities must connect to QRO, Research Graph, lifecycle, governance, RAG, and Mathematical Spine",
                    field=field_name,
                    ref=row,
                )
            )
    if not record.evidence_refs:
        violations.append(
            PlatformCoverageViolation(
                "platform_capability_missing_evidence",
                "platform capability coverage requires evidence refs",
                field="evidence_refs",
                ref=row,
            )
        )
    refs = {item.key: item.ref for item in record.specific_refs}
    specific_keys = [str(item.key or "") for item in record.specific_refs]
    for key in sorted(set(specific_keys)):
        if key and specific_keys.count(key) > 1:
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_duplicate_specific_ref",
                    "platform row cannot contain duplicate specific ref keys",
                    field=key,
                    ref=row,
                )
            )
    for key in SPECIFIC_REQUIRED_REFS.get(row, ()):
        if not _present(refs.get(key)):
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_missing_specific_ref",
                    "platform row is missing GOAL-specific coverage ref",
                    field=key,
                    ref=row,
                )
            )
    return PlatformCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_platform_coverage(records: tuple[PlatformCapabilityRecord, ...]) -> PlatformCoverageDecision:
    violations: list[PlatformCoverageViolation] = []
    rows = [_row_value(record.m_row) for record in records]
    seen = set(rows)
    for row in sorted(seen):
        if rows.count(row) > 1:
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_row_duplicate",
                    "M1-M21 coverage manifest cannot contain duplicate rows",
                    field="m_row",
                    ref=row,
                )
            )
        if row not in REQUIRED_PLATFORM_ROWS:
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_row_unknown",
                    "platform coverage manifest contains an unknown row",
                    field="m_row",
                    ref=row,
                )
            )
    for row in REQUIRED_PLATFORM_ROWS:
        if row not in seen:
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_row_missing",
                    "M1-M21 coverage manifest is missing a GOAL platform row",
                    field="m_row",
                    ref=row,
                )
            )
    for record in records:
        violations.extend(validate_platform_capability(record).violations)
    return PlatformCoverageDecision(accepted=not violations, violations=tuple(violations))


def platform_capability_record_from_dict(data: dict[str, Any]) -> PlatformCapabilityRecord:
    raw_specific_refs = data.get("specific_refs") or ()
    specific_refs: list[PlatformSpecificRef] = []
    for item in _tuple(raw_specific_refs):
        if isinstance(item, PlatformSpecificRef):
            specific_refs.append(item)
        elif isinstance(item, dict):
            specific_refs.append(PlatformSpecificRef(key=str(item.get("key") or ""), ref=str(item.get("ref") or "")))
    return PlatformCapabilityRecord(
        m_row=str(data.get("m_row") or ""),
        qro_ref=str(data.get("qro_ref") or ""),
        research_graph_ref=str(data.get("research_graph_ref") or ""),
        lifecycle_ref=str(data.get("lifecycle_ref") or ""),
        governance_ref=str(data.get("governance_ref") or ""),
        rag_ref=str(data.get("rag_ref") or ""),
        math_spine_ref=str(data.get("math_spine_ref") or ""),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        specific_refs=tuple(specific_refs),
    )


def platform_capability_record_to_dict(record: PlatformCapabilityRecord) -> dict[str, Any]:
    return {
        "m_row": _row_value(record.m_row),
        "qro_ref": record.qro_ref,
        "research_graph_ref": record.research_graph_ref,
        "lifecycle_ref": record.lifecycle_ref,
        "governance_ref": record.governance_ref,
        "rag_ref": record.rag_ref,
        "math_spine_ref": record.math_spine_ref,
        "evidence_refs": list(record.evidence_refs),
        "specific_refs": [{"key": item.key, "ref": item.ref} for item in record.specific_refs],
    }


# Legacy dependency-injection compatibility seam. Strict validators no longer
# consult this module-global value: callers and registries must pass/bind an
# explicit owner-scoped resolver. Keeping the setter avoids breaking imports
# while preventing cross-request resolver state from becoming authorization.
_DEFAULT_RESOLVER: PlatformCoverageRefResolver | None = None


def set_default_platform_coverage_resolver(resolver: PlatformCoverageRefResolver | None) -> None:
    global _DEFAULT_RESOLVER
    _DEFAULT_RESOLVER = resolver


def get_default_platform_coverage_resolver() -> PlatformCoverageRefResolver | None:
    return _DEFAULT_RESOLVER


def _real_ref_violation(field: str, row: str, ref: str, reason: str) -> PlatformCoverageViolation:
    return PlatformCoverageViolation(
        "platform_capability_ref_not_backed",
        reason,
        field=field,
        ref=f"{row}:{ref}",
    )


def validate_platform_capability_real_backing(
    record: PlatformCapabilityRecord,
    *,
    resolver: PlatformCoverageRefResolver | None = None,
) -> PlatformCoverageDecision:
    """Require every common platform ref to resolve to a real backend object.

    Unlike :func:`validate_platform_capability` (presence-only), this gate
    REQUIRES each of the six common refs (QRO, research-graph command,
    lifecycle, governance, RAG, Mathematical Spine) to resolve to a real object
    in its real store via ``resolver``. With no resolver (neither the argument
    nor the module default) the gate is fail-closed: nothing is provably backed,
    so the capability is rejected rather than rubber-stamped. Placeholder /
    goal-closure / synthetic tokens are rejected before resolution, so a
    dependency store seeded with a ``goal_closure:*`` placeholder record cannot
    launder a ref into "backed".

    Evidence and specific refs also fail closed unless the active resolver
    proves an independently persisted, owner-scoped typed object. Compiler
    containment alone is lineage, not backing evidence. Prefix shape is never
    backing evidence.
    """

    active_resolver = resolver
    violations: list[PlatformCoverageViolation] = list(validate_platform_capability(record).violations)
    row = _row_value(record.m_row)
    common_refs = {
        "qro_ref": str(record.qro_ref or ""),
        "research_graph_ref": str(record.research_graph_ref or ""),
        "lifecycle_ref": str(record.lifecycle_ref or ""),
        "governance_ref": str(record.governance_ref or ""),
        "rag_ref": str(record.rag_ref or ""),
        "math_spine_ref": str(record.math_spine_ref or ""),
    }
    for field_name, ref in common_refs.items():
        if not ref:
            # Absence already reported by validate_platform_capability above.
            continue
        if is_placeholder_ref(ref):
            violations.append(
                _real_ref_violation(
                    field_name,
                    row,
                    ref,
                    "platform coverage refs cannot be synthetic/placeholder/goal-closure tokens",
                )
            )
            continue
        if ref == f"{field_name.removesuffix('_ref')}:{row}" or ref in {row, "research_graph"}:
            violations.append(
                _real_ref_violation(field_name, row, ref, "platform coverage refs cannot be row placeholders")
            )
            continue
        row_common_resolver = getattr(
            active_resolver,
            "has_platform_common_ref",
            None,
        )
        row_backed: bool | None = None
        if row_common_resolver is not None:
            try:
                resolved = row_common_resolver(field_name, ref, record)
                row_backed = None if resolved is None else bool(resolved)
            except Exception:  # noqa: BLE001 - platform proof fails closed.
                row_backed = False
        backed = (
            resolve_typed_ref(
                active_resolver,
                field_name.removesuffix("_ref"),
                ref,
            )
            if row_backed is None
            else row_backed
        )
        if not backed:
            violations.append(
                _real_ref_violation(
                    field_name,
                    row,
                    ref,
                    f"platform coverage {field_name} does not resolve to a real object in its backend store",
                )
            )
    for ref in record.evidence_refs:
        ref = str(ref or "")
        if is_placeholder_ref(ref) or ref.endswith(":001"):
            violations.append(
                _real_ref_violation(
                    "evidence_refs",
                    row,
                    ref,
                    "platform evidence refs must point to audit/test evidence, not placeholders",
                )
            )
            continue
        evidence_resolver = getattr(active_resolver, "has_platform_evidence", None)
        try:
            evidence_backed = bool(evidence_resolver(record, ref)) if evidence_resolver is not None else False
        except Exception:  # noqa: BLE001 - coverage proof fails closed.
            evidence_backed = False
        if not evidence_backed:
            violations.append(
                _real_ref_violation(
                    "evidence_refs",
                    row,
                    ref,
                    "platform evidence ref does not resolve to independently persisted owner-scoped evidence",
                )
            )
    for item in record.specific_refs:
        ref = str(item.ref or "")
        if is_placeholder_ref(ref) or ref.endswith(":001"):
            violations.append(
                _real_ref_violation(
                    f"specific_refs.{item.key}",
                    row,
                    ref,
                    "platform specific refs must point to real registry/audit refs, not placeholders",
                )
            )
        prefixes = SPECIFIC_REF_PREFIXES.get(item.key)
        if prefixes and not ref.startswith(prefixes):
            violations.append(
                _real_ref_violation(
                    f"specific_refs.{item.key}",
                    row,
                    ref,
                    "platform specific refs must use the registry/audit prefix for their key",
                )
            )
        backed = False
        if item.key in {
            "theory_implementation_binding_ref",
            "consistency_check_ref",
        }:
            member_resolver = getattr(active_resolver, "has_math_spine_member", None)
            try:
                member_backed = bool(
                    member_resolver(str(record.math_spine_ref or ""), item.key, ref)
                ) if member_resolver is not None else False
            except Exception:  # noqa: BLE001 - coverage proof fails closed.
                member_backed = False
            backed = member_backed
        else:
            specific_resolver = getattr(active_resolver, "has_platform_specific_ref", None)
            try:
                backed = bool(specific_resolver(item.key, ref, record)) if specific_resolver is not None else False
            except Exception:  # noqa: BLE001 - coverage proof fails closed.
                backed = False
        if not backed:
            violations.append(
                _real_ref_violation(
                    f"specific_refs.{item.key}",
                    row,
                    ref,
                    "platform specific ref does not resolve to the required owner-scoped typed record",
                )
            )
    linkage_resolver = getattr(active_resolver, "platform_linkage_violations", None)
    if linkage_resolver is not None:
        try:
            linkage = tuple(linkage_resolver(record) or ())
        except Exception:  # noqa: BLE001 - coverage proof fails closed.
            linkage = (("research_graph_ref", str(record.research_graph_ref or ""), "platform linkage resolver failed"),)
        for field, ref, reason in linkage:
            violations.append(_real_ref_violation(str(field), row, str(ref), str(reason)))
    return PlatformCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_platform_coverage_real_manifest(
    records: tuple[PlatformCapabilityRecord, ...],
    *,
    resolver: PlatformCoverageRefResolver | None = None,
) -> PlatformCoverageDecision:
    active_resolver = resolver
    base = validate_platform_coverage(records)
    violations: list[PlatformCoverageViolation] = [
        violation
        for violation in base.violations
        if violation.code in {
            "platform_capability_row_missing",
            "platform_capability_row_duplicate",
            "platform_capability_row_unknown",
        }
    ]
    seen = {_row_value(record.m_row) for record in records}
    lineage_rows: dict[tuple[str, str], str] = {}
    for record in records:
        row = _row_value(record.m_row)
        lineage_key = (str(record.qro_ref or ""), str(record.research_graph_ref or ""))
        prior_row = lineage_rows.get(lineage_key)
        if prior_row is not None and prior_row != row:
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_duplicate_lineage",
                    "different platform rows cannot reuse the same QRO and graph command as proof",
                    field="qro_ref",
                    ref=f"{prior_row},{row}:{lineage_key[0]}:{lineage_key[1]}",
                )
            )
        else:
            lineage_rows[lineage_key] = row
    for record in records:
        violations.extend(
            validate_platform_capability_real_backing(record, resolver=active_resolver).violations
        )
    return PlatformCoverageDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: PlatformCoverageDecision) -> str:
    return "; ".join(f"{violation.code}:{violation.field}:{violation.ref}" for violation in decision.violations)


def _stable_platform_owner(value: Any) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise ValueError("owner_user_id is required")
    return owner


def _platform_owner_resolver(
    resolver: PlatformCoverageRefResolver | None,
    owner_user_id: str,
) -> PlatformCoverageRefResolver | None:
    if resolver is None:
        return None
    binder = getattr(resolver, "for_owner", None)
    if binder is None:
        return resolver
    try:
        return binder(owner_user_id)
    except Exception:  # noqa: BLE001 - owner binding fails closed.
        return None


class PersistentPlatformCoverageRegistry:
    """Owner-enveloped append-only registry for strict M1-M21 manifests."""

    def __init__(
        self,
        path: str | Path,
        *,
        resolver: PlatformCoverageRefResolver | None = None,
        proof_head_ledger_path: str | Path | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._resolver = resolver
        self._proof_head_ledger_path = (
            None
            if proof_head_ledger_path is None
            else Path(proof_head_ledger_path).expanduser().absolute()
        )
        self._records: dict[tuple[str, str], PlatformCapabilityRecord] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def proof_head_ledger_path(self) -> Path | None:
        return self._proof_head_ledger_path

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    @contextmanager
    def _exclusive_journal_lock(self) -> Iterator[None]:
        lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        held = None
        try:
            held = acquire_exclusive_fd(lock_fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(lock_fd)

    @contextmanager
    def _proof_head_boundary(self) -> Iterator[None]:
        """Serialize composed §14 manifest writes with the GOAL proof head.

        Standalone registries may omit the composition path.  Production
        composition injects the canonical entrypoint coverage ledger path, so
        the deterministic writer order is proof-head before this journal lock.
        """

        if self._proof_head_ledger_path is None:
            yield
            return
        with acquire_goal_proof_head_lock(self._proof_head_ledger_path):
            yield

    @staticmethod
    def _canonical_event(row: dict[str, Any]) -> str:
        return json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _read_event_rows(self, payload: bytes) -> list[tuple[int, dict[str, Any]]]:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"invalid platform coverage row at {self._path}:1") from exc
        rows: list[tuple[int, dict[str, Any]]] = []
        # JSON strings may legally contain U+2028/U+2029. ``str.splitlines``
        # treats those code points as record boundaries even though this JSONL
        # journal is delimited only by LF bytes.
        for line_no, line in enumerate(text.split("\n"), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise TypeError("platform coverage event must be a JSON object")
            except Exception as exc:  # noqa: BLE001 - poisoned history blocks all writes.
                raise ValueError(
                    f"invalid platform coverage row at {self._path}:{line_no}"
                ) from exc
            rows.append((line_no, row))
        return rows

    def _replay_rows(self, rows: list[tuple[int, dict[str, Any]]]) -> None:
        prior_records = dict(self._records)
        prior_quarantined = self._legacy_quarantined_count
        self._records.clear()
        self._legacy_quarantined_count = 0
        try:
            for line_no, row in rows:
                try:
                    if row.get("schema_version") == 1:
                        self._legacy_quarantined_count += 1
                        continue
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - invalid history must block startup/writes.
                    raise ValueError(
                        f"invalid platform coverage row at {self._path}:{line_no}"
                    ) from exc
        except Exception:
            self._records = prior_records
            self._legacy_quarantined_count = prior_quarantined
            raise

    def _load_existing(self) -> None:
        with self._lock, self._exclusive_journal_lock():
            payload = self._path.read_bytes() if self._path.exists() else b""
            self._replay_rows(self._read_event_rows(payload))

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("platform coverage journal write made no progress")
            view = view[written:]

    def _write_temp(self, payload: bytes, *, suffix: str) -> Path:
        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{self._path.name}.{suffix}.",
            dir=self._path.parent,
        )
        temp = Path(raw_temp)
        try:
            os.fchmod(fd, 0o600)
            self._write_all(fd, payload)
            os.fsync(fd)
        except Exception:
            os.close(fd)
            temp.unlink(missing_ok=True)
            raise
        os.close(fd)
        return temp

    def _fsync_parent(self) -> None:
        fd = os.open(
            self._path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _disk_state(self) -> tuple[bool, bytes]:
        exists = self._path.exists()
        return exists, self._path.read_bytes() if exists else b""

    def _restore_original(self, *, existed: bool, payload: bytes) -> None:
        if not existed:
            if self._path.exists():
                self._path.unlink()
                self._fsync_parent()
            if self._path.exists():
                raise OSError("platform coverage rollback did not remove new journal")
            return
        temp = self._write_temp(payload, suffix="restore")
        try:
            try:
                os.replace(temp, self._path)
            except Exception:
                if self._disk_state() != (True, payload):
                    raise
            self._fsync_parent()
            if self._disk_state() != (True, payload):
                raise OSError("platform coverage rollback bytes could not be verified")
        finally:
            temp.unlink(missing_ok=True)

    def _atomic_replace_append(
        self,
        *,
        original_exists: bool,
        original: bytes,
        payload: bytes,
    ) -> None:
        temp = self._write_temp(payload, suffix="append")
        original_state = (original_exists, original)
        try:
            try:
                os.replace(temp, self._path)
                self._fsync_parent()
                if self._disk_state() != (True, payload):
                    raise OSError("platform coverage append bytes could not be verified")
                return
            except Exception as exc:
                try:
                    current_state = self._disk_state()
                except Exception as recovery_exc:  # noqa: BLE001 - commit location is unknown.
                    raise PlatformCoverageCommitUncertain(
                        "platform coverage append failed and journal state cannot be read"
                    ) from recovery_exc
                if current_state == original_state:
                    raise
                if current_state != (True, payload):
                    raise PlatformCoverageCommitUncertain(
                        "platform coverage append failed with unexpected journal bytes"
                    ) from exc
                try:
                    self._restore_original(existed=original_exists, payload=original)
                except Exception as recovery_exc:  # noqa: BLE001 - durable state is uncertain.
                    raise PlatformCoverageCommitUncertain(
                        "platform coverage append failed and byte-exact rollback is unverified; "
                        f"original_error={type(exc).__name__}:{exc}"
                    ) from recovery_exc
                raise
        finally:
            temp.unlink(missing_ok=True)

    def _append_event(self, row: dict[str, Any]) -> bool:
        encoded = self._canonical_event(row)
        owner = _stable_platform_owner(row.get("owner_user_id"))
        with self._exclusive_journal_lock():
            original_exists = self._path.exists()
            original = self._path.read_bytes() if original_exists else b""
            existing_rows = self._read_event_rows(original)
            # Fresh replay under the same cross-process lock prevents an instance
            # from making an idempotency decision against a stale in-memory head.
            self._replay_rows(existing_rows)
            exact_seen = False
            current_owner_event: str | None = None
            for _line_no, existing in existing_rows:
                if existing.get("schema_version") != 2:
                    continue
                if str(existing.get("owner_user_id") or "").strip() != owner:
                    continue
                canonical = self._canonical_event(existing)
                exact_seen = exact_seen or canonical == encoded
                current_owner_event = canonical
            if current_owner_event == encoded:
                return False
            if exact_seen:
                raise ValueError(
                    "stale platform coverage manifest replay conflicts with the current owner manifest"
                )
            separator = b"" if not original or original.endswith(b"\n") else b"\n"
            payload = original + separator + (encoded + "\n").encode("utf-8")
            self._atomic_replace_append(
                original_exists=original_exists,
                original=original,
                payload=payload,
            )
            return True

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> tuple[PlatformCapabilityRecord, ...]:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported or ownerless platform coverage schema_version")
        owner = _stable_platform_owner(row.get("owner_user_id"))
        if row.get("event_type") != "platform_coverage_manifest_recorded":
            raise ValueError(f"unknown platform coverage event_type={row.get('event_type')!r}")
        raw_records = row.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("platform coverage manifest event requires records list")
        if any(not isinstance(item, dict) for item in raw_records):
            raise ValueError("platform coverage manifest records must be objects")
        records = tuple(platform_capability_record_from_dict(item) for item in raw_records)
        decision = self.validate_manifest(records, owner_user_id=owner)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        with self._lock:
            if persist:
                self._append_event(row)
            for key in tuple(self._records):
                if key[0] == owner:
                    del self._records[key]
            for record in records:
                self._records[(owner, _row_value(record.m_row))] = record
            return records

    def validate_manifest(
        self,
        records: tuple[PlatformCapabilityRecord, ...],
        *,
        owner_user_id: str,
    ) -> PlatformCoverageDecision:
        owner = _stable_platform_owner(owner_user_id)
        resolver = _platform_owner_resolver(self._resolver, owner)
        return validate_platform_coverage_real_manifest(records, resolver=resolver)

    def record_manifest(
        self,
        records: tuple[PlatformCapabilityRecord, ...],
        *,
        owner_user_id: str,
    ) -> tuple[PlatformCapabilityRecord, ...]:
        owner = _stable_platform_owner(owner_user_id)
        with self._proof_head_boundary():
            return self._apply_row(
                {
                    "schema_version": 2,
                    "event_type": "platform_coverage_manifest_recorded",
                    "owner_user_id": owner,
                    "records": [
                        platform_capability_record_to_dict(record)
                        for record in records
                    ],
                },
                persist=True,
            )

    def records(self, *, owner_user_id: str) -> list[PlatformCapabilityRecord]:
        owner = _stable_platform_owner(owner_user_id)
        self._load_existing()
        with self._lock:
            return [
                record
                for (record_owner, _), record in self._records.items()
                if record_owner == owner
            ]


__all__ = [
    "PersistentPlatformCoverageRegistry",
    "PlatformCapabilityRecord",
    "PlatformCoverageDecision",
    "PlatformCoverageCommitUncertain",
    "PlatformCoverageRefResolver",
    "PlatformCoverageViolation",
    "PlatformRow",
    "PlatformSpecificRef",
    "REQUIRED_PLATFORM_ROWS",
    "SPECIFIC_REQUIRED_REFS",
    "RealPlatformCoverageRefResolver",
    "build_real_platform_coverage_resolver",
    "get_default_platform_coverage_resolver",
    "platform_capability_record_from_dict",
    "platform_capability_record_to_dict",
    "set_default_platform_coverage_resolver",
    "validate_platform_capability",
    "validate_platform_capability_real_backing",
    "validate_platform_coverage",
    "validate_platform_coverage_real_manifest",
]
