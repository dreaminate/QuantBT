"""Canonical filesystem resolver for promoted backtest attribution artifacts.

The resolver accepts only the four identities required by
``PersistentBacktestEvidenceRegistry``.  It derives every returned field from
an owner-scoped BacktestRun QRO and the exact bytes of the promoted run's
``attribution.csv``.  Caller-reported hashes, row counts, and component refs
never enter the result.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import stat
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .backtest_evidence import BacktestArtifactState


class BacktestArtifactResolutionError(ValueError):
    """The QRO or promoted attribution artifact cannot be resolved exactly."""


CANONICAL_ATTRIBUTION_COLUMNS = (
    "period",
    "component",
    "portfolio_weight",
    "benchmark_weight",
    "portfolio_return",
    "benchmark_return",
    "benchmark_total_return",
    "allocation_effect",
    "selection_effect",
    "interaction_effect",
    "cost_effect",
    "net_contribution",
)
_NUMERIC_ATTRIBUTION_COLUMNS = CANONICAL_ATTRIBUTION_COLUMNS[2:]
_ATTRIBUTION_RECONCILIATION_TOLERANCE = Decimal("1e-12")


def _exact_text(value: Any, field: str) -> str:
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        raise BacktestArtifactResolutionError(f"{field} must be an exact string")
    token = raw.strip()
    if (
        not token
        or token != raw
        or "\x00" in token
        or any(ord(character) < 32 for character in token)
    ):
        raise BacktestArtifactResolutionError(
            f"{field} must be a stable non-empty exact string"
        )
    return token


def _direct_child(value: Any, field: str) -> str:
    token = _exact_text(value, field)
    if (
        token in {".", ".."}
        or Path(token).name != token
        or "/" in token
        or "\\" in token
        or not all(
            character.isalnum() or character in {"_", "-", "."}
            for character in token
        )
    ):
        raise BacktestArtifactResolutionError(
            f"{field} must name one direct run_root child"
        )
    return token


def _stat_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, value.st_mode


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


@dataclass(frozen=True)
class _ArtifactSnapshot:
    data: bytes
    root_identity: tuple[int, int, int]
    run_identity: tuple[int, int, int]
    file_identity: tuple[int, int, int, int, int, int]


def _component_refs(
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
) -> tuple[str, ...]:
    refs: list[str] = []
    for index, header in enumerate(headers):
        payload = json.dumps(
            {
                "column_index": index,
                "header": header,
                "values": [row[index] for row in rows],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        refs.append(
            "attribution_component:sha256:" + hashlib.sha256(payload).hexdigest()
        )
    return tuple(refs)


def _decimal_cell(value: str, *, row_number: int, field: str) -> Decimal:
    if not value or value != value.strip():
        raise BacktestArtifactResolutionError(
            f"attribution.csv row {row_number} {field} must be an exact number"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise BacktestArtifactResolutionError(
            f"attribution.csv row {row_number} {field} must be numeric"
        ) from exc
    if not parsed.is_finite():
        raise BacktestArtifactResolutionError(
            f"attribution.csv row {row_number} {field} must be finite"
        )
    return parsed


def _within_reconciliation_tolerance(actual: Decimal, expected: Decimal) -> bool:
    scale = max(Decimal(1), abs(expected))
    return abs(actual - expected) <= _ATTRIBUTION_RECONCILIATION_TOLERANCE * scale


def _parse_csv(data: bytes) -> tuple[int, tuple[str, ...]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BacktestArtifactResolutionError(
            "attribution.csv must be strict UTF-8"
        ) from exc
    if "\x00" in text:
        raise BacktestArtifactResolutionError("attribution.csv contains a NUL byte")
    try:
        parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise BacktestArtifactResolutionError("attribution.csv is malformed") from exc
    if not parsed:
        raise BacktestArtifactResolutionError("attribution.csv is empty")

    raw_headers = parsed[0]
    headers: list[str] = []
    seen: set[str] = set()
    for raw_header in raw_headers:
        header = raw_header.strip()
        identity = header.casefold()
        if (
            not header
            or header != raw_header
            or any(ord(character) < 32 for character in header)
        ):
            raise BacktestArtifactResolutionError(
                "attribution.csv headers must be non-empty exact strings"
            )
        if identity in seen:
            raise BacktestArtifactResolutionError(
                "attribution.csv headers must be unique"
            )
        seen.add(identity)
        headers.append(header)
    normalized_headers = tuple(headers)
    if normalized_headers != CANONICAL_ATTRIBUTION_COLUMNS:
        raise BacktestArtifactResolutionError(
            "attribution.csv must use the exact canonical Brinson/cost schema"
        )

    rows: list[tuple[str, ...]] = []
    seen_components: set[tuple[str, str]] = set()
    for row_number, row in enumerate(parsed[1:], start=2):
        if len(row) != len(headers):
            raise BacktestArtifactResolutionError(
                f"attribution.csv row {row_number} has the wrong column count"
            )
        if not any(cell.strip() for cell in row):
            raise BacktestArtifactResolutionError(
                f"attribution.csv row {row_number} is blank"
            )
        period, component = row[:2]
        for field, value in (("period", period), ("component", component)):
            if (
                not value
                or value != value.strip()
                or any(ord(character) < 32 for character in value)
            ):
                raise BacktestArtifactResolutionError(
                    f"attribution.csv row {row_number} {field} must be an exact string"
                )
        component_key = (period, component)
        if component_key in seen_components:
            raise BacktestArtifactResolutionError(
                f"attribution.csv row {row_number} duplicates period/component"
            )
        seen_components.add(component_key)
        numeric = {
            field: _decimal_cell(row[index], row_number=row_number, field=field)
            for index, field in enumerate(_NUMERIC_ATTRIBUTION_COLUMNS, start=2)
        }
        if numeric["cost_effect"] < 0:
            raise BacktestArtifactResolutionError(
                f"attribution.csv row {row_number} cost_effect cannot be negative"
            )
        expected_allocation = (
            numeric["portfolio_weight"] - numeric["benchmark_weight"]
        ) * (numeric["benchmark_return"] - numeric["benchmark_total_return"])
        expected_selection = numeric["benchmark_weight"] * (
            numeric["portfolio_return"] - numeric["benchmark_return"]
        )
        expected_interaction = (
            numeric["portfolio_weight"] - numeric["benchmark_weight"]
        ) * (numeric["portfolio_return"] - numeric["benchmark_return"])
        for field, expected in (
            ("allocation_effect", expected_allocation),
            ("selection_effect", expected_selection),
            ("interaction_effect", expected_interaction),
        ):
            if not _within_reconciliation_tolerance(numeric[field], expected):
                raise BacktestArtifactResolutionError(
                    f"attribution.csv row {row_number} {field} does not reconcile"
                )
        expected_net = (
            expected_allocation
            + expected_selection
            + expected_interaction
            - numeric["cost_effect"]
        )
        if not _within_reconciliation_tolerance(
            numeric["net_contribution"], expected_net
        ):
            raise BacktestArtifactResolutionError(
                f"attribution.csv row {row_number} net_contribution does not reconcile"
            )
        rows.append(tuple(row))
    if not rows:
        raise BacktestArtifactResolutionError(
            "attribution.csv requires at least one data row"
        )
    normalized_rows = tuple(rows)
    return len(normalized_rows), _component_refs(normalized_headers, normalized_rows)


def canonical_attribution_csv_bytes(rows: Any) -> bytes:
    """Encode caller-produced attribution rows only after exact semantic validation."""

    if not isinstance(rows, list) or not rows:
        raise BacktestArtifactResolutionError(
            "attribution must be a non-empty list of canonical row objects"
        )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CANONICAL_ATTRIBUTION_COLUMNS),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row_number, row in enumerate(rows, start=2):
        if not isinstance(row, dict) or tuple(row) != CANONICAL_ATTRIBUTION_COLUMNS:
            raise BacktestArtifactResolutionError(
                f"attribution row {row_number} must use the exact canonical field order"
            )
        for field in CANONICAL_ATTRIBUTION_COLUMNS:
            value = row[field]
            if value is None or isinstance(value, (dict, list, tuple, set, bool)):
                raise BacktestArtifactResolutionError(
                    f"attribution row {row_number} {field} must be a scalar value"
                )
        writer.writerow(row)
    encoded = buffer.getvalue().encode("utf-8")
    _parse_csv(encoded)
    return encoded


class CanonicalBacktestArtifactResolver:
    """Resolve one owner BacktestRun QRO to its canonical attribution CSV."""

    def __init__(
        self,
        *,
        run_root: str | Path,
        research_graph_store: Any,
    ) -> None:
        self._run_root = Path(run_root)
        self._graph = research_graph_store

    @staticmethod
    def _source_run_id(qro: Any, output_contract: dict[str, Any]) -> str:
        if "source_run_id" in output_contract:
            source_run_id = _exact_text(
                output_contract["source_run_id"],
                "BacktestRun output_contract.source_run_id",
            )
            input_contract = getattr(qro, "input_contract", None)
            if isinstance(input_contract, dict) and "source_run_id" in input_contract:
                input_source = _exact_text(
                    input_contract["source_run_id"],
                    "BacktestRun input_contract.source_run_id",
                )
                if input_source != source_run_id:
                    raise BacktestArtifactResolutionError(
                        "BacktestRun input/output source_run_id mismatch"
                    )
            if "run_id" in output_contract:
                legacy = _exact_text(
                    output_contract["run_id"],
                    "BacktestRun output_contract.run_id",
                )
                if legacy != source_run_id:
                    raise BacktestArtifactResolutionError(
                        "BacktestRun output source_run_id/run_id conflict"
                    )
            return source_run_id

        if "run_id" not in output_contract:
            raise BacktestArtifactResolutionError(
                "BacktestRun output_contract.source_run_id is required"
            )
        legacy = _exact_text(
            output_contract["run_id"],
            "BacktestRun output_contract.run_id",
        )
        input_contract = getattr(qro, "input_contract", None)
        input_source = ""
        if isinstance(input_contract, dict) and "source_run_id" in input_contract:
            input_source = _exact_text(
                input_contract["source_run_id"],
                "BacktestRun input_contract.source_run_id",
            )
        lineage = {
            str(item)
            for item in tuple(getattr(qro, "lineage", ()) or ())
            if str(item)
        }
        if input_source != legacy and not {
            legacy,
            f"ide_run:{legacy}",
        }.intersection(lineage):
            raise BacktestArtifactResolutionError(
                "legacy BacktestRun output run_id lacks canonical source lineage"
            )
        return legacy

    def _resolve_promoted_run(
        self,
        *,
        owner_user_id: str,
        backtest_run_ref: str,
        source_run_ref: str,
    ) -> str:
        try:
            qro = self._graph.qro(backtest_run_ref)
        except Exception as exc:  # noqa: BLE001 - every graph failure closes resolution.
            raise BacktestArtifactResolutionError(
                "BacktestRun QRO is unavailable"
            ) from exc
        if _exact_text(getattr(qro, "qro_id", ""), "BacktestRun qro_id") != backtest_run_ref:
            raise BacktestArtifactResolutionError("BacktestRun QRO identity mismatch")
        if _exact_text(getattr(qro, "owner", ""), "BacktestRun owner") != owner_user_id:
            raise BacktestArtifactResolutionError("BacktestRun QRO owner mismatch")
        if _exact_text(getattr(qro, "qro_type", ""), "BacktestRun qro_type") != "BacktestRun":
            raise BacktestArtifactResolutionError("QRO is not a BacktestRun")
        output_contract = getattr(qro, "output_contract", None)
        if not isinstance(output_contract, dict):
            raise BacktestArtifactResolutionError(
                "BacktestRun output_contract is unavailable"
            )
        source_run_id = self._source_run_id(qro, output_contract)
        expected_source_ref = f"ide_run:{source_run_id}"
        if source_run_ref != expected_source_ref:
            raise BacktestArtifactResolutionError(
                "source_run_ref does not match the BacktestRun QRO"
            )
        return _direct_child(
            output_contract.get("promoted_run_id"),
            "BacktestRun output_contract.promoted_run_id",
        )

    def _read_snapshot(self, promoted_run_id: str) -> _ArtifactSnapshot:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if self._run_root.is_symlink():
            raise BacktestArtifactResolutionError("run_root symlinks are not allowed")
        root_fd: int | None = None
        run_fd: int | None = None
        file_fd: int | None = None
        try:
            root_fd = os.open(self._run_root, directory_flags | nofollow)
            root_state = os.fstat(root_fd)
            if not stat.S_ISDIR(root_state.st_mode):
                raise BacktestArtifactResolutionError("run_root is not a directory")
            run_fd = os.open(
                promoted_run_id,
                directory_flags | nofollow,
                dir_fd=root_fd,
            )
            run_state = os.fstat(run_fd)
            if not stat.S_ISDIR(run_state.st_mode):
                raise BacktestArtifactResolutionError(
                    "promoted run is not a directory"
                )
            file_fd = os.open(
                "attribution.csv",
                os.O_RDONLY | nofollow,
                dir_fd=run_fd,
            )
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                raise BacktestArtifactResolutionError(
                    "attribution.csv is not a regular file"
                )
            with os.fdopen(file_fd, "rb", closefd=True) as handle:
                file_fd = None
                data = handle.read()
                after = os.fstat(handle.fileno())
            if _file_identity(before) != _file_identity(after) or len(data) != after.st_size:
                raise BacktestArtifactResolutionError(
                    "attribution.csv changed while being read"
                )
            return _ArtifactSnapshot(
                data=data,
                root_identity=_stat_identity(root_state),
                run_identity=_stat_identity(run_state),
                file_identity=_file_identity(after),
            )
        except BacktestArtifactResolutionError:
            raise
        except OSError as exc:
            raise BacktestArtifactResolutionError(
                "attribution.csv is missing, linked, or outside run_root"
            ) from exc
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if run_fd is not None:
                os.close(run_fd)
            if root_fd is not None:
                os.close(root_fd)

    def __call__(
        self,
        owner_user_id: str,
        backtest_run_ref: str,
        source_run_ref: str,
        artifact_path: str,
    ) -> BacktestArtifactState:
        owner = _exact_text(owner_user_id, "owner_user_id")
        backtest_ref = _exact_text(backtest_run_ref, "backtest_run_ref")
        source_ref = _exact_text(source_run_ref, "source_run_ref")
        path = _exact_text(artifact_path, "artifact_path")
        if path != "attribution.csv":
            raise BacktestArtifactResolutionError(
                "artifact_path must equal attribution.csv"
            )
        promoted_run_id = self._resolve_promoted_run(
            owner_user_id=owner,
            backtest_run_ref=backtest_ref,
            source_run_ref=source_ref,
        )
        first = self._read_snapshot(promoted_run_id)
        second = self._read_snapshot(promoted_run_id)
        if first != second:
            raise BacktestArtifactResolutionError(
                "attribution.csv changed during stable resolution"
            )
        row_count, component_refs = _parse_csv(first.data)
        return BacktestArtifactState(
            artifact_sha256="sha256:" + hashlib.sha256(first.data).hexdigest(),
            row_count=row_count,
            component_refs=component_refs,
        )


__all__ = [
    "CANONICAL_ATTRIBUTION_COLUMNS",
    "BacktestArtifactResolutionError",
    "CanonicalBacktestArtifactResolver",
    "canonical_attribution_csv_bytes",
]
