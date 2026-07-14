"""Owner-scoped durable research-design assets for GOAL section 14 M1-M8.

The existing Universe, regime, label, factor, hypothesis, signal, and IDE
strategy implementations are useful domain objects, but several of their
stores predate stable owner envelopes.  This module does not replace those
objects.  It records either a typed definition or an exact, content-bound
owner envelope around the object produced by its existing store.

Every journal row is append-only, hash chained, cross-process locked, and
anchored by a prefix marker.  A getter is owner scoped.  Envelope consumers
must additionally re-read the source store and compare ``source_content_hash``
so an overwrite or later mutation makes the old binding stale rather than
silently transferring it to new content.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from ..universe.definition import UniverseDefinition


def _text(value: Any, label: str) -> str:
    token = str(getattr(value, "value", value) or "").strip()
    if not token:
        raise ValueError(f"{label} is required")
    return token


def _optional_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def source_object_hash(value: Any) -> str:
    """Hash one exact source object without inventing a second hash family."""

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
    else:
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            payload = model_dump(mode="json")
        elif is_dataclass(value):
            payload = asdict(value)
        elif isinstance(value, dict):
            payload = value
        else:
            raise TypeError("research-design source object is not serializable")
    return content_hash(_json_value(payload))


@dataclass(frozen=True)
class ResearchDesignLinkage:
    qro_ref: str
    research_graph_ref: str
    lifecycle_ref: str

    def __post_init__(self) -> None:
        for name in ("qro_ref", "research_graph_ref", "lifecycle_ref"):
            object.__setattr__(self, name, _text(getattr(self, name), name))


@dataclass(frozen=True)
class UniverseDefinitionRecord:
    universe_definition_ref: str
    owner_user_id: str
    definition: dict[str, Any]
    source_content_hash: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        owner = _text(self.owner_user_id, "owner_user_id")
        definition = UniverseDefinition.model_validate(self.definition).model_dump(mode="json")
        digest = content_hash(definition)
        expected_ref = f"universe:{digest}"
        if self.universe_definition_ref != expected_ref or self.source_content_hash != digest:
            raise ValueError("UniverseDefinition canonical identity/content hash mismatch")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "definition", definition)


@dataclass(frozen=True)
class RegimeScenarioRecord:
    regime_scenario_ref: str
    owner_user_id: str
    universe_definition_ref: str
    scenario: dict[str, Any]
    source_content_hash: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        owner = _text(self.owner_user_id, "owner_user_id")
        universe_ref = _text(self.universe_definition_ref, "universe_definition_ref")
        if not universe_ref.startswith("universe:"):
            raise ValueError("RegimeScenario requires a canonical UniverseDefinition ref")
        scenario = dict(self.scenario or {})
        name = _text(scenario.get("name"), "regime scenario name")
        detector = _text(scenario.get("detector"), "regime scenario detector")
        config = scenario.get("config")
        if not isinstance(config, dict) or not config:
            raise ValueError("RegimeScenario config must be a non-empty object")
        normalized = {**scenario, "name": name, "detector": detector, "config": _json_value(config)}
        digest = content_hash(
            {"universe_definition_ref": universe_ref, "scenario": normalized}
        )
        if self.regime_scenario_ref != f"regime:{digest}" or self.source_content_hash != digest:
            raise ValueError("RegimeScenario canonical identity/content hash mismatch")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "universe_definition_ref", universe_ref)
        object.__setattr__(self, "scenario", normalized)


_LABEL_KINDS = frozenset({"time_series", "cross_sectional", "triple_barrier"})


@dataclass(frozen=True)
class LabelDefinitionRecord:
    label_ref: str
    owner_user_id: str
    label_kind: str
    output_column: str
    horizon: int
    parameters: dict[str, Any]
    known_at_rule: str
    effective_at_rule: str
    source_content_hash: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        owner = _text(self.owner_user_id, "owner_user_id")
        kind = _text(self.label_kind, "label_kind")
        if kind not in _LABEL_KINDS:
            raise ValueError(f"label_kind must be one of {sorted(_LABEL_KINDS)}")
        output = _text(self.output_column, "output_column")
        horizon = int(self.horizon)
        if horizon <= 0:
            raise ValueError("LabelDefinition horizon must be > 0")
        known_at_rule = _text(self.known_at_rule, "known_at_rule")
        effective_at_rule = _text(self.effective_at_rule, "effective_at_rule")
        parameters = _json_value(dict(self.parameters or {}))
        payload = {
            "label_kind": kind,
            "output_column": output,
            "horizon": horizon,
            "parameters": parameters,
            "known_at_rule": known_at_rule,
            "effective_at_rule": effective_at_rule,
        }
        digest = content_hash(payload)
        if self.label_ref != f"label:{digest}" or self.source_content_hash != digest:
            raise ValueError("LabelDefinition canonical identity/content hash mismatch")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "label_kind", kind)
        object.__setattr__(self, "output_column", output)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "known_at_rule", known_at_rule)
        object.__setattr__(self, "effective_at_rule", effective_at_rule)


@dataclass(frozen=True)
class PortfolioPolicyRecord:
    portfolio_policy_ref: str
    owner_user_id: str
    portfolio_id: str
    strategy_book_ref: str
    signal_contract_ref: str
    signal_validation_ref: str
    strategy_book_source_hash: str
    signal_contract_source_hash: str
    policy: dict[str, Any]
    source_content_hash: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        owner = _text(self.owner_user_id, "owner_user_id")
        portfolio_id = _text(self.portfolio_id, "portfolio_id")
        strategy_ref = _text(self.strategy_book_ref, "strategy_book_ref")
        signal_ref = _text(self.signal_contract_ref, "signal_contract_ref")
        validation_ref = _text(self.signal_validation_ref, "signal_validation_ref")
        strategy_hash = _text(self.strategy_book_source_hash, "strategy_book_source_hash")
        signal_hash = _text(self.signal_contract_source_hash, "signal_contract_source_hash")
        if not strategy_ref.startswith("strategy_book:"):
            raise ValueError("PortfolioPolicy strategy_book_ref is not canonical")
        if not signal_ref.startswith(("signal_contract:", "sig::")):
            raise ValueError("PortfolioPolicy signal_contract_ref is not canonical")
        policy = _json_value(dict(self.policy or {}))
        if not policy:
            raise ValueError("PortfolioPolicy policy must be a non-empty object")
        payload = {
            "portfolio_id": portfolio_id,
            "strategy_book_ref": strategy_ref,
            "signal_contract_ref": signal_ref,
            "signal_validation_ref": validation_ref,
            "strategy_book_source_hash": strategy_hash,
            "signal_contract_source_hash": signal_hash,
            "policy": policy,
        }
        digest = content_hash(payload)
        if self.portfolio_policy_ref != f"portfolio_policy:{digest}" or self.source_content_hash != digest:
            raise ValueError("PortfolioPolicy canonical identity/content hash mismatch")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "portfolio_id", portfolio_id)
        object.__setattr__(self, "strategy_book_ref", strategy_ref)
        object.__setattr__(self, "signal_contract_ref", signal_ref)
        object.__setattr__(self, "signal_validation_ref", validation_ref)
        object.__setattr__(self, "strategy_book_source_hash", strategy_hash)
        object.__setattr__(self, "signal_contract_source_hash", signal_hash)
        object.__setattr__(self, "policy", policy)


@dataclass(frozen=True)
class StrategyBookRecord:
    """One validated, owner-scoped §9 multi-leg StrategyBook source.

    The authoritative §9 validator owns the semantic checks.  This registry
    stores the exact normalized contract that passed that validator so M7-M8
    never has to reinterpret an IDE source file as a StrategyBook.
    """

    strategy_book_ref: str
    owner_user_id: str
    strategy_book: dict[str, Any]
    source_content_hash: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        owner = _text(self.owner_user_id, "owner_user_id")
        strategy_ref = _text(self.strategy_book_ref, "strategy_book_ref")
        if not strategy_ref.startswith("strategy_book:"):
            raise ValueError("StrategyBook ref is not canonical")
        strategy_book = _json_value(dict(self.strategy_book or {}))
        if _text(strategy_book.get("strategy_book_ref"), "strategy_book.strategy_book_ref") != strategy_ref:
            raise ValueError("StrategyBook payload/ref mismatch")
        legs = strategy_book.get("legs")
        if not isinstance(legs, list) or not legs:
            raise ValueError("StrategyBook requires at least one typed leg")
        for field_name in (
            "factor_refs",
            "signal_refs",
            "signal_validation_refs",
            "mathematical_refs",
            "theory_binding_refs",
            "run_config_binding_refs",
        ):
            if not isinstance(strategy_book.get(field_name), list):
                raise ValueError(f"StrategyBook {field_name} must be a list")
        digest = content_hash(strategy_book)
        if self.source_content_hash != digest:
            raise ValueError("StrategyBook content hash mismatch")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "strategy_book_ref", strategy_ref)
        object.__setattr__(self, "strategy_book", strategy_book)


@dataclass(frozen=True)
class HypothesisOwnerEnvelope:
    envelope_ref: str
    hypothesis_card_ref: str
    owner_user_id: str
    card_id: str
    source_content_hash: str
    strategy_goal_ref: str
    universe_definition_ref: str
    regime_scenario_ref: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        _validate_envelope(self, "hypothesis_card", self.card_id)
        if self.hypothesis_card_ref != f"hypothesis_card:{self.card_id}":
            raise ValueError("HypothesisCard source ref mismatch")
        for name, prefix in (
            ("strategy_goal_ref", ("strategy_goal:", "goal:")),
            ("universe_definition_ref", ("universe:",)),
            ("regime_scenario_ref", ("regime:", "scenario:")),
        ):
            if not _text(getattr(self, name), name).startswith(prefix):
                raise ValueError(f"HypothesisCard {name} is not canonical")


@dataclass(frozen=True)
class FactorOwnerEnvelope:
    envelope_ref: str
    factor_ref: str
    owner_user_id: str
    factor_id: str
    version: int
    source_content_hash: str
    label_ref: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        version = int(self.version)
        if version <= 0:
            raise ValueError("Factor envelope version must be > 0")
        identity = f"{_text(self.factor_id, 'factor_id')}:v{version}"
        _validate_envelope(self, "factor", identity)
        if self.factor_ref != f"factor:{identity}":
            raise ValueError("Factor source ref mismatch")
        if not _text(self.label_ref, "label_ref").startswith("label:"):
            raise ValueError("Factor envelope label_ref is not canonical")
        object.__setattr__(self, "version", version)


@dataclass(frozen=True)
class SignalContractOwnerEnvelope:
    envelope_ref: str
    signal_contract_ref: str
    owner_user_id: str
    signal_id: str
    source_content_hash: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        signal_id = _text(self.signal_id, "signal_id")
        _validate_envelope(self, "signal_contract", signal_id)
        if self.signal_contract_ref not in {
            f"sig::{signal_id}",
            f"signal_contract:{signal_id}",
            f"signal_contract:sig::{signal_id}",
        }:
            raise ValueError("SignalContract source ref mismatch")


@dataclass(frozen=True)
class StrategyBookOwnerEnvelope:
    envelope_ref: str
    strategy_book_ref: str
    owner_user_id: str
    strategy_id: str
    source_content_hash: str
    linkage: ResearchDesignLinkage

    def __post_init__(self) -> None:
        strategy_id = _text(self.strategy_id, "strategy_id")
        _validate_envelope(self, "strategy_book", strategy_id)
        if self.strategy_book_ref != f"strategy_book:{strategy_id}":
            raise ValueError("StrategyBook source ref mismatch")


def _validate_envelope(value: Any, kind: str, identity: str) -> None:
    owner = _text(value.owner_user_id, "owner_user_id")
    source_hash = _text(value.source_content_hash, "source_content_hash")
    expected = "research_design_envelope:" + content_hash(
        {
            "kind": kind,
            "owner_user_id": owner,
            "source_identity": _text(identity, "source_identity"),
            "source_content_hash": source_hash,
            "linkage": asdict(value.linkage),
        }
    )
    if value.envelope_ref != expected:
        raise ValueError(f"{kind} owner envelope canonical identity mismatch")
    object.__setattr__(value, "owner_user_id", owner)


ResearchDesignRecord = (
    UniverseDefinitionRecord
    | RegimeScenarioRecord
    | LabelDefinitionRecord
    | PortfolioPolicyRecord
    | StrategyBookRecord
    | HypothesisOwnerEnvelope
    | FactorOwnerEnvelope
    | SignalContractOwnerEnvelope
    | StrategyBookOwnerEnvelope
)


_RECORD_TYPES: dict[str, type[ResearchDesignRecord]] = {
    cls.__name__: cls
    for cls in (
        UniverseDefinitionRecord,
        RegimeScenarioRecord,
        LabelDefinitionRecord,
        PortfolioPolicyRecord,
        StrategyBookRecord,
        HypothesisOwnerEnvelope,
        FactorOwnerEnvelope,
        SignalContractOwnerEnvelope,
        StrategyBookOwnerEnvelope,
    )
}


def _record_ref(record: ResearchDesignRecord) -> str:
    if isinstance(record, UniverseDefinitionRecord):
        return record.universe_definition_ref
    if isinstance(record, RegimeScenarioRecord):
        return record.regime_scenario_ref
    if isinstance(record, LabelDefinitionRecord):
        return record.label_ref
    if isinstance(record, PortfolioPolicyRecord):
        return record.portfolio_policy_ref
    if isinstance(record, StrategyBookRecord):
        return record.strategy_book_ref
    if isinstance(
        record,
        (
            HypothesisOwnerEnvelope,
            FactorOwnerEnvelope,
            SignalContractOwnerEnvelope,
            StrategyBookOwnerEnvelope,
        ),
    ):
        return record.envelope_ref
    raise TypeError("unsupported research-design record")


def _source_key(record: ResearchDesignRecord) -> tuple[str, str, str] | None:
    if isinstance(record, HypothesisOwnerEnvelope):
        return (record.owner_user_id, "hypothesis", record.hypothesis_card_ref)
    if isinstance(record, FactorOwnerEnvelope):
        return (record.owner_user_id, "factor", record.factor_ref)
    if isinstance(record, SignalContractOwnerEnvelope):
        return (record.owner_user_id, "signal", record.signal_contract_ref)
    if isinstance(record, StrategyBookOwnerEnvelope):
        return (record.owner_user_id, "strategy_book", record.strategy_book_ref)
    return None


T = TypeVar("T", bound=ResearchDesignRecord)


class PersistentResearchDesignAssetRegistry:
    """Hash-chained append-only registry with strict owner-scoped getters."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._marker_path = self._path.with_suffix(self._path.suffix + ".head")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str, str], ResearchDesignRecord] = {}
        self._source_heads: dict[tuple[str, str, str], str] = {}
        self._known_rows: tuple[str, ...] = ()
        self._refresh(allow_initial_missing=True)

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _row_hash(row: dict[str, Any]) -> str:
        payload = {key: value for key, value in row.items() if key != "row_sha256"}
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _record_from_payload(type_name: str, payload: dict[str, Any]) -> ResearchDesignRecord:
        record_type = _RECORD_TYPES.get(type_name)
        if record_type is None:
            raise ValueError(f"unknown research-design record type {type_name!r}")
        raw = dict(payload)
        linkage = raw.get("linkage")
        if not isinstance(linkage, dict):
            raise ValueError("research-design record linkage is missing")
        raw["linkage"] = ResearchDesignLinkage(**linkage)
        return record_type(**raw)  # type: ignore[arg-type]

    def _read_marker(self) -> tuple[int, str] | None:
        if self._marker_path.is_symlink():
            raise ValueError("research-design journal marker cannot be a symlink")
        if not self._marker_path.exists():
            return None
        try:
            raw = json.loads(self._marker_path.read_text(encoding="utf-8"))
            count = int(raw["row_count"])
            head = str(raw["head_sha256"])
            if raw.get("schema_version") != 1 or count < 0 or len(head) != 64:
                raise ValueError
            int(head, 16)
            return count, head
        except Exception as exc:  # noqa: BLE001 - integrity metadata fails closed.
            raise ValueError("invalid research-design journal marker") from exc

    def _write_marker(self, count: int, head: str) -> None:
        encoded = _canonical_json(
            {"schema_version": 1, "row_count": count, "head_sha256": head}
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            dir=self._marker_path.parent,
            prefix=f".{self._marker_path.name}.",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            if os.write(fd, encoded) != len(encoded):
                raise OSError("short research-design marker write")
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, self._marker_path)
            directory_fd = os.open(self._marker_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)

    def _read_rows(self, *, allow_initial_missing: bool) -> tuple[tuple[str, ...], list[ResearchDesignRecord]]:
        marker = self._read_marker()
        if not self._path.exists():
            if allow_initial_missing and marker in (None, (0, "0" * 64)):
                return (), []
            raise ValueError("persisted research-design journal is missing")
        rows: list[str] = []
        records: list[ResearchDesignRecord] = []
        previous = "0" * 64
        with self._path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    raise ValueError(f"invalid research-design row at {self._path}:{line_no}")
                try:
                    row = json.loads(line)
                    if row.get("schema_version") != self.SCHEMA_VERSION:
                        raise ValueError("unsupported schema")
                    if int(row.get("sequence")) != line_no:
                        raise ValueError("sequence mismatch")
                    if row.get("previous_sha256") != previous:
                        raise ValueError("hash-chain predecessor mismatch")
                    actual_hash = self._row_hash(row)
                    if row.get("row_sha256") != actual_hash:
                        raise ValueError("row hash mismatch")
                    owner = _text(row.get("owner_user_id"), "owner_user_id")
                    payload = row.get("record")
                    if not isinstance(payload, dict):
                        raise ValueError("record payload missing")
                    record = self._record_from_payload(str(row.get("record_type") or ""), payload)
                    if record.owner_user_id != owner:
                        raise ValueError("row/record owner mismatch")
                    previous = actual_hash
                    rows.append(_canonical_json(row))
                    records.append(record)
                except Exception as exc:  # noqa: BLE001 - corrupt history fails closed.
                    raise ValueError(
                        f"invalid research-design row at {self._path}:{line_no}"
                    ) from exc
        row_tuple = tuple(rows)
        if marker is None:
            if row_tuple:
                raise ValueError("research-design journal marker is missing")
        else:
            marker_count, marker_head = marker
            if marker_count != len(row_tuple):
                if marker_count > len(row_tuple):
                    raise ValueError("research-design journal was truncated")
                raise ValueError("research-design journal contains an uncommitted suffix")
            expected_head = "0" * 64 if marker_count == 0 else json.loads(row_tuple[marker_count - 1])["row_sha256"]
            if expected_head != marker_head:
                raise ValueError("research-design journal changed before marker")
        if self._known_rows and row_tuple[: len(self._known_rows)] != self._known_rows:
            raise ValueError("research-design append-only history changed")
        return row_tuple, records

    def _install(self, records: list[ResearchDesignRecord]) -> None:
        by_ref: dict[tuple[str, str, str], ResearchDesignRecord] = {}
        heads: dict[tuple[str, str, str], str] = {}
        for record in records:
            ref = _record_ref(record)
            key = (record.owner_user_id, type(record).__name__, ref)
            prior = by_ref.get(key)
            if prior is not None and prior != record:
                raise ValueError("research-design canonical identity collision")
            by_ref[key] = record
            source_key = _source_key(record)
            if source_key is not None:
                heads[source_key] = ref
        self._records = by_ref
        self._source_heads = heads

    def _refresh(self, *, allow_initial_missing: bool = False) -> None:
        with self._lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            held = None
            try:
                os.chmod(self._lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                if not self._path.exists() and self._read_marker() is None:
                    self._path.touch(mode=0o600)
                    self._write_marker(0, "0" * 64)
                rows, records = self._read_rows(allow_initial_missing=allow_initial_missing)
                self._install(records)
                self._known_rows = rows
                head = "0" * 64 if not rows else json.loads(rows[-1])["row_sha256"]
                marker = self._read_marker()
                if marker != (len(rows), head):
                    self._write_marker(len(rows), head)
            finally:
                if held is not None:
                    held.release()
                os.close(fd)

    def record(self, record: T) -> T:
        if type(record).__name__ not in _RECORD_TYPES:
            raise TypeError("unsupported research-design record")
        with self._lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            held = None
            try:
                os.chmod(self._lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                rows, records = self._read_rows(allow_initial_missing=True)
                self._install(records)
                ref = _record_ref(record)
                key = (record.owner_user_id, type(record).__name__, ref)
                existing = self._records.get(key)
                if existing is not None:
                    if existing != record:
                        raise ValueError("research-design canonical identity collision")
                    return existing  # type: ignore[return-value]
                previous = "0" * 64 if not rows else json.loads(rows[-1])["row_sha256"]
                row = {
                    "schema_version": self.SCHEMA_VERSION,
                    "sequence": len(rows) + 1,
                    "previous_sha256": previous,
                    "owner_user_id": record.owner_user_id,
                    "record_type": type(record).__name__,
                    "record": _json_value(record),
                }
                row["row_sha256"] = self._row_hash(row)
                encoded = _canonical_json(row)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(encoded + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                rows = (*rows, encoded)
                self._write_marker(len(rows), row["row_sha256"])
                self._known_rows = rows
                self._install([*records, record])
                return record
            finally:
                if held is not None:
                    held.release()
                os.close(fd)

    def _get(self, owner: str, record_type: type[T], ref: str) -> T:
        self._refresh()
        key = (_text(owner, "owner_user_id"), record_type.__name__, _text(ref, "ref"))
        return self._records[key]  # type: ignore[return-value]

    def universe_definition(self, ref: str, *, owner_user_id: str) -> UniverseDefinitionRecord:
        return self._get(owner_user_id, UniverseDefinitionRecord, ref)

    def regime_scenario(self, ref: str, *, owner_user_id: str) -> RegimeScenarioRecord:
        return self._get(owner_user_id, RegimeScenarioRecord, ref)

    def label_definition(self, ref: str, *, owner_user_id: str) -> LabelDefinitionRecord:
        return self._get(owner_user_id, LabelDefinitionRecord, ref)

    def portfolio_policy(self, ref: str, *, owner_user_id: str) -> PortfolioPolicyRecord:
        return self._get(owner_user_id, PortfolioPolicyRecord, ref)

    def strategy_book(self, ref: str, *, owner_user_id: str) -> StrategyBookRecord:
        return self._get(owner_user_id, StrategyBookRecord, ref)

    def _current_envelope(self, owner: str, kind: str, source_ref: str, record_type: type[T]) -> T:
        self._refresh()
        owner_value = _text(owner, "owner_user_id")
        source = _text(source_ref, "source_ref")
        envelope_ref = self._source_heads[(owner_value, kind, source)]
        return self._records[(owner_value, record_type.__name__, envelope_ref)]  # type: ignore[return-value]

    def hypothesis_envelope(self, ref: str, *, owner_user_id: str) -> HypothesisOwnerEnvelope:
        return self._current_envelope(owner_user_id, "hypothesis", ref, HypothesisOwnerEnvelope)

    def factor_envelope(self, ref: str, *, owner_user_id: str) -> FactorOwnerEnvelope:
        return self._current_envelope(owner_user_id, "factor", ref, FactorOwnerEnvelope)

    def signal_contract_envelope(self, ref: str, *, owner_user_id: str) -> SignalContractOwnerEnvelope:
        return self._current_envelope(owner_user_id, "signal", ref, SignalContractOwnerEnvelope)

def make_universe_definition_record(
    definition: UniverseDefinition | dict[str, Any],
    *,
    owner_user_id: str,
    linkage: ResearchDesignLinkage,
) -> UniverseDefinitionRecord:
    payload = (
        definition.model_dump(mode="json")
        if isinstance(definition, UniverseDefinition)
        else UniverseDefinition.model_validate(definition).model_dump(mode="json")
    )
    digest = content_hash(payload)
    return UniverseDefinitionRecord(
        universe_definition_ref=f"universe:{digest}",
        owner_user_id=owner_user_id,
        definition=payload,
        source_content_hash=digest,
        linkage=linkage,
    )


def make_regime_scenario_record(
    *,
    owner_user_id: str,
    universe_definition_ref: str,
    scenario: dict[str, Any],
    linkage: ResearchDesignLinkage,
) -> RegimeScenarioRecord:
    normalized = _json_value(dict(scenario))
    digest = content_hash(
        {"universe_definition_ref": universe_definition_ref, "scenario": normalized}
    )
    return RegimeScenarioRecord(
        regime_scenario_ref=f"regime:{digest}",
        owner_user_id=owner_user_id,
        universe_definition_ref=universe_definition_ref,
        scenario=normalized,
        source_content_hash=digest,
        linkage=linkage,
    )


def make_label_definition_record(
    *,
    owner_user_id: str,
    label_kind: str,
    output_column: str,
    horizon: int,
    parameters: dict[str, Any],
    known_at_rule: str,
    effective_at_rule: str,
    linkage: ResearchDesignLinkage,
) -> LabelDefinitionRecord:
    payload = {
        "label_kind": label_kind,
        "output_column": output_column,
        "horizon": int(horizon),
        "parameters": _json_value(parameters),
        "known_at_rule": known_at_rule,
        "effective_at_rule": effective_at_rule,
    }
    digest = content_hash(payload)
    return LabelDefinitionRecord(
        label_ref=f"label:{digest}",
        owner_user_id=owner_user_id,
        source_content_hash=digest,
        linkage=linkage,
        **payload,
    )


def make_portfolio_policy_record(
    *,
    owner_user_id: str,
    portfolio_id: str,
    strategy_book_ref: str,
    signal_contract_ref: str,
    signal_validation_ref: str,
    strategy_book_source_hash: str,
    signal_contract_source_hash: str,
    policy: dict[str, Any],
    linkage: ResearchDesignLinkage,
) -> PortfolioPolicyRecord:
    payload = {
        "portfolio_id": portfolio_id,
        "strategy_book_ref": strategy_book_ref,
        "signal_contract_ref": signal_contract_ref,
        "signal_validation_ref": signal_validation_ref,
        "strategy_book_source_hash": strategy_book_source_hash,
        "signal_contract_source_hash": signal_contract_source_hash,
        "policy": _json_value(policy),
    }
    canonical_ref = portfolio_policy_ref(**payload)
    digest = canonical_ref.removeprefix("portfolio_policy:")
    return PortfolioPolicyRecord(
        portfolio_policy_ref=canonical_ref,
        owner_user_id=owner_user_id,
        source_content_hash=digest,
        linkage=linkage,
        **payload,
    )


def portfolio_policy_ref(
    *,
    portfolio_id: str,
    strategy_book_ref: str,
    signal_contract_ref: str,
    signal_validation_ref: str,
    strategy_book_source_hash: str,
    signal_contract_source_hash: str,
    policy: dict[str, Any],
) -> str:
    """Return the canonical PortfolioPolicy ref from the single payload source."""

    payload = {
        "portfolio_id": portfolio_id,
        "strategy_book_ref": strategy_book_ref,
        "signal_contract_ref": signal_contract_ref,
        "signal_validation_ref": signal_validation_ref,
        "strategy_book_source_hash": strategy_book_source_hash,
        "signal_contract_source_hash": signal_contract_source_hash,
        "policy": _json_value(policy),
    }
    return f"portfolio_policy:{content_hash(payload)}"


def make_strategy_book_record(
    strategy_book: Any,
    *,
    owner_user_id: str,
    linkage: ResearchDesignLinkage,
) -> StrategyBookRecord:
    payload = _json_value(asdict(strategy_book) if is_dataclass(strategy_book) else strategy_book)
    if not isinstance(payload, dict):
        raise TypeError("StrategyBook source must serialize to an object")
    strategy_ref = _text(payload.get("strategy_book_ref"), "strategy_book_ref")
    return StrategyBookRecord(
        strategy_book_ref=strategy_ref,
        owner_user_id=owner_user_id,
        strategy_book=payload,
        source_content_hash=content_hash(payload),
        linkage=linkage,
    )


def _envelope_ref(
    *, kind: str, owner_user_id: str, source_identity: str, source_content_hash: str, linkage: ResearchDesignLinkage
) -> str:
    return "research_design_envelope:" + content_hash(
        {
            "kind": kind,
            "owner_user_id": owner_user_id,
            "source_identity": source_identity,
            "source_content_hash": source_content_hash,
            "linkage": asdict(linkage),
        }
    )


def make_hypothesis_envelope(
    card: Any,
    *,
    owner_user_id: str,
    strategy_goal_ref: str,
    universe_definition_ref: str,
    regime_scenario_ref: str,
    linkage: ResearchDesignLinkage,
) -> HypothesisOwnerEnvelope:
    card_id = _text(getattr(card, "card_id", ""), "card_id")
    digest = source_object_hash(card)
    return HypothesisOwnerEnvelope(
        envelope_ref=_envelope_ref(
            kind="hypothesis_card", owner_user_id=owner_user_id,
            source_identity=card_id, source_content_hash=digest, linkage=linkage,
        ),
        hypothesis_card_ref=f"hypothesis_card:{card_id}",
        owner_user_id=owner_user_id,
        card_id=card_id,
        source_content_hash=digest,
        strategy_goal_ref=strategy_goal_ref,
        universe_definition_ref=universe_definition_ref,
        regime_scenario_ref=regime_scenario_ref,
        linkage=linkage,
    )


def make_factor_envelope(
    factor: Any,
    *, owner_user_id: str, label_ref: str, linkage: ResearchDesignLinkage
) -> FactorOwnerEnvelope:
    factor_id = _text(getattr(factor, "factor_id", ""), "factor_id")
    version = int(getattr(factor, "version", 0))
    identity = f"{factor_id}:v{version}"
    digest = source_object_hash(factor)
    return FactorOwnerEnvelope(
        envelope_ref=_envelope_ref(
            kind="factor", owner_user_id=owner_user_id,
            source_identity=identity, source_content_hash=digest, linkage=linkage,
        ),
        factor_ref=f"factor:{identity}",
        owner_user_id=owner_user_id,
        factor_id=factor_id,
        version=version,
        source_content_hash=digest,
        label_ref=label_ref,
        linkage=linkage,
    )


def make_signal_contract_envelope(
    contract: Any,
    *, owner_user_id: str, linkage: ResearchDesignLinkage
) -> SignalContractOwnerEnvelope:
    signal_id = _text(getattr(contract, "signal_id", ""), "signal_id")
    digest = source_object_hash(contract)
    return SignalContractOwnerEnvelope(
        envelope_ref=_envelope_ref(
            kind="signal_contract", owner_user_id=owner_user_id,
            source_identity=signal_id, source_content_hash=digest, linkage=linkage,
        ),
        signal_contract_ref=f"signal_contract:sig::{signal_id}",
        owner_user_id=owner_user_id,
        signal_id=signal_id,
        source_content_hash=digest,
        linkage=linkage,
    )


__all__ = [
    "FactorOwnerEnvelope",
    "HypothesisOwnerEnvelope",
    "LabelDefinitionRecord",
    "PersistentResearchDesignAssetRegistry",
    "PortfolioPolicyRecord",
    "RegimeScenarioRecord",
    "ResearchDesignLinkage",
    "SignalContractOwnerEnvelope",
    "StrategyBookRecord",
    "UniverseDefinitionRecord",
    "make_factor_envelope",
    "make_hypothesis_envelope",
    "make_label_definition_record",
    "make_portfolio_policy_record",
    "make_regime_scenario_record",
    "make_signal_contract_envelope",
    "make_strategy_book_record",
    "make_universe_definition_record",
    "source_object_hash",
    "portfolio_policy_ref",
]
