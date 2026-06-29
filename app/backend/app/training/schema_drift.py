"""GOAL §15 dataset-schema-drift detection feeding model recertification.

This module is the **producer side** of the §15 ``data schema change``
recertification trigger. It fingerprints the schema of a model's training dataset
— the columns the model actually consumes (its ``feature_cols`` + ``label_col``)
together with their dtypes — and diffs the schema of one training run against a
prior run of the *same model*.

It is deliberately pure: no governance imports, no persistence, no hard pandas
dependency (a plain ``{column: dtype}`` mapping is accepted so the logic is unit
testable without building a DataFrame). The training service
(:mod:`app.training.service`) wires the fingerprint + diff to
:class:`app.research_os.model_governance.PersistentModelGovernanceRegistry`:

1. it stores each recorded passport's schema fingerprint, and
2. before the next run of the same model it recomputes the fingerprint and, when it
   differs from the last recorded one, demands an accepted/waived
   ``DATA_SCHEMA_CHANGE`` recertification record (fail-closed) *before* any training
   runs.

The detection here can only ever **add** a recertification obligation. It can never
clear one — clearing requires a human-recorded ``ModelRecertificationRecord`` through
the governed registry path. The judgment of whether a change event clears (declared
trigger + recertification record) is reused from
``model_governance.validate_model_promotion``; this module never re-implements it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Sentinel dtype for a model-consumed column absent from the dataset. A missing
# column is itself a schema difference (and would fail training), so it must take
# part in the fingerprint rather than be silently dropped (no silent mock).
MISSING_DTYPE = "__absent__"

_FINGERPRINT_PREFIX = "dataset_schema_sha256:"
_CHANGE_EVENT_PREFIX = "data_schema_change:"


@dataclass(frozen=True)
class SchemaColumn:
    role: str  # "feature" | "label"
    name: str
    dtype: str


@dataclass(frozen=True)
class DatasetSchema:
    """Ordered schema of the columns a model consumes (features, then label).

    Feature column order is significant: it defines the model's input-vector layout,
    so a reorder of the same feature set is treated as a schema change (conservative
    / fail-closed). Use :attr:`fingerprint` for the stable identity and
    :func:`diff_schemas` for a human-readable delta.
    """

    columns: tuple[SchemaColumn, ...]

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.role == "feature")

    @property
    def label_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.role == "label")

    def _payload(self) -> list[list[str]]:
        return [[c.role, c.name, c.dtype] for c in self.columns]

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self._payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return _FINGERPRINT_PREFIX + hashlib.sha256(encoded).hexdigest()


def _dtype_map(panel: Any) -> dict[str, str]:
    """Best-effort ``{column -> dtype string}`` for a pandas DataFrame or a mapping.

    Accepting a plain mapping keeps the fingerprint logic unit-testable without
    pandas; the training service always passes a real DataFrame.
    """
    dtypes = getattr(panel, "dtypes", None)
    if dtypes is not None and hasattr(dtypes, "items"):
        return {str(name): str(dtype) for name, dtype in dtypes.items()}
    if isinstance(panel, Mapping):
        return {str(name): str(dtype) for name, dtype in panel.items()}
    raise TypeError(
        "compute_dataset_schema expects a pandas DataFrame or a {column: dtype} mapping"
    )


def compute_dataset_schema(
    panel: Any,
    feature_cols: Sequence[str],
    label_col: str,
) -> DatasetSchema:
    """Schema of the columns the model consumes, in training order (features, label)."""
    dtypes = _dtype_map(panel)
    columns: list[SchemaColumn] = []
    for name in feature_cols:
        key = str(name)
        columns.append(SchemaColumn(role="feature", name=key, dtype=dtypes.get(key, MISSING_DTYPE)))
    label_key = str(label_col)
    columns.append(SchemaColumn(role="label", name=label_key, dtype=dtypes.get(label_key, MISSING_DTYPE)))
    return DatasetSchema(columns=tuple(columns))


def schema_fingerprint(panel: Any, feature_cols: Sequence[str], label_col: str) -> str:
    return compute_dataset_schema(panel, feature_cols, label_col).fingerprint


@dataclass(frozen=True)
class SchemaDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    retyped: tuple[tuple[str, str, str], ...]  # (name, prev_dtype, now_dtype)
    label_changed: bool
    reordered: bool

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.retyped or self.label_changed or self.reordered)

    def describe(self) -> str:
        parts: list[str] = []
        if self.added:
            parts.append(f"added_features={list(self.added)}")
        if self.removed:
            parts.append(f"removed_features={list(self.removed)}")
        if self.retyped:
            parts.append(f"retyped_features={[list(item) for item in self.retyped]}")
        if self.label_changed:
            parts.append("label_changed=True")
        if self.reordered:
            parts.append("feature_order_changed=True")
        return "; ".join(parts) or "no_structural_change"


def diff_schemas(prev: DatasetSchema, now: DatasetSchema) -> SchemaDiff:
    """Full schema delta (requires both schemas in memory, dtypes included)."""
    prev_feat = {c.name: c.dtype for c in prev.columns if c.role == "feature"}
    now_feat = {c.name: c.dtype for c in now.columns if c.role == "feature"}
    added = tuple(sorted(set(now_feat) - set(prev_feat)))
    removed = tuple(sorted(set(prev_feat) - set(now_feat)))
    retyped = tuple(
        (name, prev_feat[name], now_feat[name])
        for name in sorted(set(prev_feat) & set(now_feat))
        if prev_feat[name] != now_feat[name]
    )
    prev_label = tuple((c.name, c.dtype) for c in prev.columns if c.role == "label")
    now_label = tuple((c.name, c.dtype) for c in now.columns if c.role == "label")
    label_changed = prev_label != now_label
    prev_order = prev.feature_names
    now_order = now.feature_names
    reordered = (set(prev_order) == set(now_order)) and (prev_order != now_order)
    return SchemaDiff(
        added=added,
        removed=removed,
        retyped=retyped,
        label_changed=label_changed,
        reordered=reordered,
    )


def describe_name_diff(
    prev_features: Sequence[str],
    prev_labels: Sequence[str],
    now_features: Sequence[str],
    now_labels: Sequence[str],
) -> str:
    """Name-level delta for the gate error when only prior *names* are known.

    A recorded passport stores its schema fingerprint and its feature/label names,
    but not prior dtypes. When the fingerprint differs we describe the change with
    the names we do have; if the names are identical the fingerprint mismatch can
    only come from a dtype or feature-order change, and we say so honestly rather
    than pretend nothing changed.
    """
    prev_f = [str(name) for name in prev_features]
    now_f = [str(name) for name in now_features]
    added = sorted(set(now_f) - set(prev_f))
    removed = sorted(set(prev_f) - set(now_f))
    prev_l = [str(name) for name in prev_labels]
    now_l = [str(name) for name in now_labels]
    parts: list[str] = []
    if added:
        parts.append(f"added_features={added}")
    if removed:
        parts.append(f"removed_features={removed}")
    if prev_l != now_l:
        parts.append(f"label={prev_l}->{now_l}")
    if not parts:
        parts.append("feature/label names unchanged; dtype or feature order changed")
    return "; ".join(parts)


def schema_change_event_ref(scope: str, prev_fingerprint: str, new_fingerprint: str) -> str:
    """Deterministic id for a *specific* schema transition of a *specific* model.

    Binding the scope (model identity) and both fingerprints means a recertification
    record can only clear the exact ``(model, prev_schema -> new_schema)`` transition
    it was filed against; it cannot be reused for a different model or a different
    schema change. The training gate hands this ref to the operator so the
    recertification record references back the same transition.
    """
    encoded = json.dumps(
        [str(scope), str(prev_fingerprint), str(new_fingerprint)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _CHANGE_EVENT_PREFIX + hashlib.sha256(encoded).hexdigest()


class DataSchemaRecertificationRequired(RuntimeError):
    """Raised by the training pre-run gate when a model's dataset schema changed and
    no accepted/waived ``DATA_SCHEMA_CHANGE`` recertification clears the transition.

    Fail-closed: training must not start until the change is recertified. The
    attributes carry everything the operator needs to file the recertification
    record (notably :attr:`change_event_ref`).
    """

    def __init__(
        self,
        *,
        model_ref: str,
        change_event_ref: str,
        prev_fingerprint: str,
        new_fingerprint: str,
        diff: str,
    ) -> None:
        self.model_ref = model_ref
        self.change_event_ref = change_event_ref
        self.prev_fingerprint = prev_fingerprint
        self.new_fingerprint = new_fingerprint
        self.diff = diff
        super().__init__(
            "data_schema_change recertification required before training "
            f"model {model_ref!r}: dataset schema changed ({diff}); file an accepted "
            f"DATA_SCHEMA_CHANGE recertification record for change_event_ref="
            f"{change_event_ref!r} (prev={prev_fingerprint}, new={new_fingerprint})"
        )


__all__ = [
    "MISSING_DTYPE",
    "DataSchemaRecertificationRequired",
    "DatasetSchema",
    "SchemaColumn",
    "SchemaDiff",
    "compute_dataset_schema",
    "describe_name_diff",
    "diff_schemas",
    "schema_change_event_ref",
    "schema_fingerprint",
]
