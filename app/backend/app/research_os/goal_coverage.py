"""GOAL §0-§17 implementation coverage manifest contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .spine import EntrySource


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _str_tuple(value: Any) -> tuple[str, ...]:
    items: list[str] = []
    for item in _tuple(value):
        text = str(item.value if isinstance(item, Enum) else item or "")
        if text.strip():
            items.append(text)
    return tuple(items)


def _present(value: Any) -> bool:
    return bool(str(value or "").strip())


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


class GoalSection(str, Enum):
    SECTION_0 = "§0"
    SECTION_1 = "§1"
    SECTION_2 = "§2"
    SECTION_3 = "§3"
    SECTION_4 = "§4"
    SECTION_5 = "§5"
    SECTION_6 = "§6"
    SECTION_7 = "§7"
    SECTION_8 = "§8"
    SECTION_9 = "§9"
    SECTION_10 = "§10"
    SECTION_11 = "§11"
    SECTION_12 = "§12"
    SECTION_13 = "§13"
    SECTION_14 = "§14"
    SECTION_15 = "§15"
    SECTION_16 = "§16"
    SECTION_17 = "§17"


REQUIRED_GOAL_SECTIONS = tuple(section.value for section in GoalSection)
REQUIRED_ENTRY_SOURCES = tuple(source.value for source in EntrySource)


@dataclass(frozen=True)
class GoalCoverageViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class GoalCoverageDecision:
    accepted: bool
    violations: tuple[GoalCoverageViolation, ...]


@dataclass(frozen=True)
class GoalSectionCoverageRecord:
    section: GoalSection | str
    contract_refs: tuple[str, ...]
    test_refs: tuple[str, ...]
    task_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    full_entrypoint_wired: bool = False
    entrypoint_wiring_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_refs", _tuple(self.contract_refs))
        object.__setattr__(self, "test_refs", _tuple(self.test_refs))
        object.__setattr__(self, "task_refs", _tuple(self.task_refs))
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        object.__setattr__(self, "entrypoint_wiring_refs", _tuple(self.entrypoint_wiring_refs))


@dataclass(frozen=True)
class GoalEntrypointCoverageRecord:
    coverage_ref: str
    entry_source: EntrySource | str
    entrypoint_ref: str
    goal_sections: tuple[GoalSection | str, ...]
    qro_refs: tuple[str, ...]
    research_graph_command_refs: tuple[str, ...]
    compiler_ir_refs: tuple[str, ...]
    compiler_pass_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...]
    permission_refs: tuple[str, ...]
    replay_refs: tuple[str, ...]
    canonical_command_refs: tuple[str, ...] = ()
    lifecycle_refs: tuple[str, ...] = ()
    rdp_refs: tuple[str, ...] = ()
    recorded_by: str = ""
    claims_full_product_entrypoint: bool = False
    silent_mock_fallback_used: bool = False
    raw_payload_persisted: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "goal_sections",
            "qro_refs",
            "research_graph_command_refs",
            "compiler_ir_refs",
            "compiler_pass_refs",
            "evidence_refs",
            "validation_refs",
            "permission_refs",
            "replay_refs",
            "canonical_command_refs",
            "lifecycle_refs",
            "rdp_refs",
        ):
            object.__setattr__(self, field_name, _str_tuple(getattr(self, field_name)))


def _section_value(section: GoalSection | str) -> str:
    if isinstance(section, GoalSection):
        return section.value
    return str(section)


def _entry_source_value(entry_source: EntrySource | str) -> str:
    if isinstance(entry_source, EntrySource):
        return entry_source.value
    return str(entry_source)


def validate_goal_section_coverage(record: GoalSectionCoverageRecord) -> GoalCoverageDecision:
    violations: list[GoalCoverageViolation] = []
    section = _section_value(record.section)
    for field_name in ("contract_refs", "test_refs", "task_refs", "evidence_refs"):
        if not getattr(record, field_name):
            violations.append(
                GoalCoverageViolation(
                    "goal_section_missing_contract_evidence",
                    "each GOAL section requires contract, test, task, and evidence refs",
                    field=field_name,
                    ref=section,
                )
            )
    if record.full_entrypoint_wired and not record.entrypoint_wiring_refs:
        violations.append(
            GoalCoverageViolation(
                "goal_section_claimed_wired_without_refs",
                "full entrypoint wiring claims require wiring refs",
                field="entrypoint_wiring_refs",
                ref=section,
            )
        )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_goal_entrypoint_coverage(record: GoalEntrypointCoverageRecord) -> GoalCoverageDecision:
    violations: list[GoalCoverageViolation] = []
    ref = record.coverage_ref
    entry_source = _entry_source_value(record.entry_source)
    if not _present(record.coverage_ref):
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_required_ref_missing",
                "entrypoint coverage requires coverage_ref",
                field="coverage_ref",
                ref=ref,
            )
        )
    if entry_source not in REQUIRED_ENTRY_SOURCES:
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_unknown_source",
                "entrypoint coverage source must be a known EntrySource",
                field="entry_source",
                ref=ref,
            )
        )
    if not _present(record.entrypoint_ref):
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_required_ref_missing",
                "entrypoint coverage requires entrypoint_ref",
                field="entrypoint_ref",
                ref=ref,
            )
        )
    for section in record.goal_sections:
        if section not in REQUIRED_GOAL_SECTIONS:
            violations.append(
                GoalCoverageViolation(
                    "goal_entrypoint_unknown_section",
                    "entrypoint coverage section must be one of §0 through §17",
                    field="goal_sections",
                    ref=section,
                )
            )
    for field_name in (
        "goal_sections",
        "qro_refs",
        "research_graph_command_refs",
        "compiler_ir_refs",
        "compiler_pass_refs",
        "evidence_refs",
        "validation_refs",
        "permission_refs",
        "replay_refs",
    ):
        if not getattr(record, field_name):
            violations.append(
                GoalCoverageViolation(
                    "goal_entrypoint_required_ref_missing",
                    "entrypoint coverage requires QRO, graph, compiler, evidence, permission, replay, and validation refs",
                    field=field_name,
                    ref=ref,
                )
            )
    if record.claims_full_product_entrypoint and set(record.goal_sections) != set(REQUIRED_GOAL_SECTIONS):
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_full_product_claim_missing_sections",
                "full-product entrypoint claims must cite every GOAL section from §0 to §17",
                field="goal_sections",
                ref=ref,
            )
        )
    if record.silent_mock_fallback_used:
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_silent_mock_fallback",
                "entrypoint coverage cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=ref,
            )
        )
    if record.raw_payload_persisted:
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_raw_payload_persisted",
                "entrypoint coverage must cite refs/hashes, not persisted raw user or tool payloads",
                field="raw_payload_persisted",
                ref=ref,
            )
        )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_goal_coverage_manifest(
    records: tuple[GoalSectionCoverageRecord, ...],
    *,
    claims_full_product_implementation: bool = False,
) -> GoalCoverageDecision:
    violations: list[GoalCoverageViolation] = []
    seen = {_section_value(record.section) for record in records}
    for section in REQUIRED_GOAL_SECTIONS:
        if section not in seen:
            violations.append(
                GoalCoverageViolation(
                    "goal_section_missing",
                    "GOAL coverage manifest must include every section from §0 to §17",
                    field="section",
                    ref=section,
                )
            )
    for record in records:
        section_decision = validate_goal_section_coverage(record)
        violations.extend(section_decision.violations)
        if claims_full_product_implementation and not record.full_entrypoint_wired:
            violations.append(
                GoalCoverageViolation(
                    "goal_section_not_full_entrypoint_wired",
                    "contract coverage cannot be reported as full product implementation without entrypoint wiring refs",
                    field="full_entrypoint_wired",
                    ref=_section_value(record.section),
                )
            )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_goal_entrypoint_coverage_manifest(
    records: tuple[GoalEntrypointCoverageRecord, ...],
    *,
    claims_all_entrypoints_wired: bool = False,
) -> GoalCoverageDecision:
    violations: list[GoalCoverageViolation] = []
    seen_sources: set[str] = set()
    for record in records:
        source = _entry_source_value(record.entry_source)
        if source in REQUIRED_ENTRY_SOURCES:
            seen_sources.add(source)
        violations.extend(validate_goal_entrypoint_coverage(record).violations)
    if claims_all_entrypoints_wired:
        for source in REQUIRED_ENTRY_SOURCES:
            if source not in seen_sources:
                violations.append(
                    GoalCoverageViolation(
                        "goal_entrypoint_source_missing",
                        "all-entrypoints-wired claims require coverage for every EntrySource",
                        field="entry_source",
                        ref=source,
                    )
                )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: GoalCoverageDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "goal coverage record rejected"


def goal_entrypoint_coverage_record_from_dict(data: dict[str, Any]) -> GoalEntrypointCoverageRecord:
    return GoalEntrypointCoverageRecord(
        coverage_ref=str(data.get("coverage_ref") or ""),
        entry_source=str(data.get("entry_source") or ""),
        entrypoint_ref=str(data.get("entrypoint_ref") or ""),
        goal_sections=_str_tuple(data.get("goal_sections")),
        qro_refs=_str_tuple(data.get("qro_refs")),
        research_graph_command_refs=_str_tuple(data.get("research_graph_command_refs")),
        compiler_ir_refs=_str_tuple(data.get("compiler_ir_refs")),
        compiler_pass_refs=_str_tuple(data.get("compiler_pass_refs")),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        validation_refs=_str_tuple(data.get("validation_refs")),
        permission_refs=_str_tuple(data.get("permission_refs")),
        replay_refs=_str_tuple(data.get("replay_refs")),
        canonical_command_refs=_str_tuple(data.get("canonical_command_refs")),
        lifecycle_refs=_str_tuple(data.get("lifecycle_refs")),
        rdp_refs=_str_tuple(data.get("rdp_refs")),
        recorded_by=str(data.get("recorded_by") or ""),
        claims_full_product_entrypoint=bool(data.get("claims_full_product_entrypoint", False)),
        silent_mock_fallback_used=bool(data.get("silent_mock_fallback_used", False)),
        raw_payload_persisted=bool(data.get("raw_payload_persisted", False)),
    )


def goal_section_coverage_record_from_dict(data: dict[str, Any]) -> GoalSectionCoverageRecord:
    return GoalSectionCoverageRecord(
        section=str(data.get("section") or ""),
        contract_refs=_str_tuple(data.get("contract_refs")),
        test_refs=_str_tuple(data.get("test_refs")),
        task_refs=_str_tuple(data.get("task_refs")),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        full_entrypoint_wired=bool(data.get("full_entrypoint_wired", False)),
        entrypoint_wiring_refs=_str_tuple(data.get("entrypoint_wiring_refs")),
    )


class PersistentGoalEntrypointCoverageRegistry:
    """Append-only JSONL registry for QRO -> Graph -> Compiler -> Evidence entrypoint coverage."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, GoalEntrypointCoverageRecord] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad coverage history must block startup.
                    raise ValueError(f"invalid persisted GOAL entrypoint coverage row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> GoalEntrypointCoverageRecord:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported GOAL entrypoint coverage schema_version")
        if row.get("event_type") != "goal_entrypoint_coverage_recorded":
            raise ValueError(f"unknown GOAL entrypoint coverage event_type={row.get('event_type')!r}")
        raw = row.get("entrypoint_coverage")
        if not isinstance(raw, dict):
            raise ValueError("GOAL entrypoint coverage event missing entrypoint_coverage")
        record = goal_entrypoint_coverage_record_from_dict(raw)
        decision = validate_goal_entrypoint_coverage(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._records[record.coverage_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "goal_entrypoint_coverage_recorded",
                    "entrypoint_coverage": _json_value(record),
                }
            )
        return record

    def record_coverage(self, record: GoalEntrypointCoverageRecord) -> GoalEntrypointCoverageRecord:
        return self._apply_row(
            {
                "schema_version": 1,
                "event_type": "goal_entrypoint_coverage_recorded",
                "entrypoint_coverage": _json_value(record),
            },
            persist=True,
        )

    def coverage(self, coverage_ref: str) -> GoalEntrypointCoverageRecord:
        return self._records[coverage_ref]

    def records(self) -> list[GoalEntrypointCoverageRecord]:
        return list(self._records.values())

    def records_for_entry_source(self, entry_source: EntrySource | str) -> list[GoalEntrypointCoverageRecord]:
        source = _entry_source_value(entry_source)
        return [record for record in self._records.values() if _entry_source_value(record.entry_source) == source]


class PersistentGoalSectionCoverageRegistry:
    """Append-only JSONL registry for §0-§17 section implementation coverage."""

    def __init__(
        self,
        path: str | Path,
        entrypoint_coverage_registry: PersistentGoalEntrypointCoverageRegistry,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entrypoint_coverage_registry = entrypoint_coverage_registry
        self._records: dict[str, GoalSectionCoverageRecord] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad coverage history must block startup.
                    raise ValueError(f"invalid persisted GOAL section coverage row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _validate_entrypoint_refs(self, record: GoalSectionCoverageRecord) -> None:
        section = _section_value(record.section)
        for coverage_ref in record.entrypoint_wiring_refs:
            try:
                entrypoint_record = self._entrypoint_coverage_registry.coverage(coverage_ref)
            except KeyError as exc:
                raise ValueError(f"goal_section_unknown_entrypoint_wiring_ref:entrypoint_wiring_refs:{coverage_ref}") from exc
            decision = validate_goal_entrypoint_coverage(entrypoint_record)
            if not decision.accepted:
                raise ValueError(
                    "goal_section_invalid_entrypoint_wiring_ref:entrypoint_wiring_refs:"
                    + ",".join(f"{violation.code}:{violation.field}" for violation in decision.violations)
                )
            if section not in set(entrypoint_record.goal_sections):
                raise ValueError(
                    f"goal_section_entrypoint_ref_section_mismatch:entrypoint_wiring_refs:{coverage_ref}"
                )

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> GoalSectionCoverageRecord:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported GOAL section coverage schema_version")
        if row.get("event_type") != "goal_section_coverage_recorded":
            raise ValueError(f"unknown GOAL section coverage event_type={row.get('event_type')!r}")
        raw = row.get("section_coverage")
        if not isinstance(raw, dict):
            raise ValueError("GOAL section coverage event missing section_coverage")
        record = goal_section_coverage_record_from_dict(raw)
        decision = validate_goal_section_coverage(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._validate_entrypoint_refs(record)
        self._records[_section_value(record.section)] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "goal_section_coverage_recorded",
                    "section_coverage": _json_value(record),
                }
            )
        return record

    def record_coverage(self, record: GoalSectionCoverageRecord) -> GoalSectionCoverageRecord:
        return self._apply_row(
            {
                "schema_version": 1,
                "event_type": "goal_section_coverage_recorded",
                "section_coverage": _json_value(record),
            },
            persist=True,
        )

    def coverage(self, section: GoalSection | str) -> GoalSectionCoverageRecord:
        return self._records[_section_value(section)]

    def records(self) -> list[GoalSectionCoverageRecord]:
        return list(self._records.values())


__all__ = [
    "GoalCoverageDecision",
    "GoalCoverageViolation",
    "GoalEntrypointCoverageRecord",
    "GoalSection",
    "GoalSectionCoverageRecord",
    "PersistentGoalEntrypointCoverageRegistry",
    "PersistentGoalSectionCoverageRegistry",
    "REQUIRED_ENTRY_SOURCES",
    "REQUIRED_GOAL_SECTIONS",
    "goal_entrypoint_coverage_record_from_dict",
    "goal_section_coverage_record_from_dict",
    "validate_goal_entrypoint_coverage",
    "validate_goal_entrypoint_coverage_manifest",
    "validate_goal_coverage_manifest",
    "validate_goal_section_coverage",
]
