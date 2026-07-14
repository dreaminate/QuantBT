"""Strict, read-only selection of one owner-scoped Mathematical Spine chain.

The platform producers need to bind a business object to an already verified
full-chain record.  Selecting an owner's newest chain, or searching arbitrary
serialized content for a ref-shaped string, would allow unrelated evidence to
be recombined.  This module exposes one small selector over the canonical,
typed chain fields and fails closed unless the constraints identify exactly one
currently verified projection.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .ref_resolution import is_placeholder_ref


SCALAR_CHAIN_FIELDS = frozenset(
    {
        "data_semantics_ref",
        "factor_ref",
        "model_ref",
        "forecast_ref",
        "signal_contract_ref",
        "strategy_book_ref",
        "portfolio_policy_ref",
        "risk_policy_ref",
        "execution_policy_ref",
        "backtest_run_ref",
        "attribution_ref",
        "monitor_ref",
        "methodology_choice_ref",
        "responsibility_boundary_ref",
    }
)

TUPLE_CHAIN_FIELDS = frozenset(
    {
        "theory_binding_refs",
        "consistency_check_refs",
        "evidence_refs",
        "validation_refs",
    }
)


class SpineChainSelectionError(ValueError):
    """The typed constraints did not identify one current verified chain."""


def _exact_ref(value: Any, *, field: str) -> str:
    raw = str(getattr(value, "value", value) or "")
    ref = raw.strip()
    if (
        not ref
        or ref != raw
        or any(ord(char) < 32 for char in ref)
        or is_placeholder_ref(ref)
    ):
        raise SpineChainSelectionError(f"{field} is not an exact stable ref")
    return ref


def _constraint_map(
    values: Mapping[str, Any] | Iterable[tuple[str, Any]] | None,
    *,
    allowed_fields: frozenset[str],
    label: str,
) -> dict[str, Any]:
    items = tuple((values or {}).items()) if isinstance(values, Mapping) else tuple(values or ())
    keys = tuple(str(key) for key, _value in items)
    if len(keys) != len(set(keys)):
        raise SpineChainSelectionError(f"{label} contains duplicate fields")
    unknown = tuple(sorted(set(keys).difference(allowed_fields)))
    if unknown:
        raise SpineChainSelectionError(
            f"{label} contains unsupported fields: {', '.join(unknown)}"
        )
    return {str(key): value for key, value in items}


def _tuple_refs(value: Any, *, field: str) -> tuple[str, ...]:
    refs = tuple(_exact_ref(item, field=field) for item in tuple(value or ()))
    if not refs:
        raise SpineChainSelectionError(f"{field} must contain at least one ref")
    if len(refs) != len(set(refs)):
        raise SpineChainSelectionError(f"{field} contains duplicate refs")
    return refs


def resolve_unique_verified_spine_chain(
    registry: Any,
    *,
    owner_user_id: str,
    scalar_refs: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
    scalar_one_of_refs: Mapping[str, Iterable[Any]]
    | Iterable[tuple[str, Iterable[Any]]]
    | None = None,
    contains_refs: Mapping[str, Iterable[Any]]
    | Iterable[tuple[str, Iterable[Any]]]
    | None = None,
    exact_tuple_refs: Mapping[str, Iterable[Any]]
    | Iterable[tuple[str, Iterable[Any]]]
    | None = None,
    union_contains_refs: Iterable[
        tuple[Iterable[str], Iterable[Any]]
    ] | None = None,
) -> Any:
    """Resolve one verified chain using only explicit canonical fields.

    ``scalar_refs`` requires exact equality on scalar chain fields;
    ``scalar_one_of_refs`` allows an explicit finite set for one field.
    ``contains_refs`` requires every supplied ref to be a member of the named
    tuple field. ``exact_tuple_refs`` requires set equality and rejects
    duplicate projected refs. ``union_contains_refs`` requires refs to be
    members of the union of an explicit tuple-field group. At least one
    constraint is mandatory.

    The function never mutates the registry.  An owner-filtered projection that
    returns a foreign owner is treated as registry corruption, not ignored.
    """

    owner = _exact_ref(owner_user_id, field="owner_user_id")
    scalars = _constraint_map(
        scalar_refs,
        allowed_fields=SCALAR_CHAIN_FIELDS,
        label="scalar_refs",
    )
    scalar_one_of = _constraint_map(
        scalar_one_of_refs,
        allowed_fields=SCALAR_CHAIN_FIELDS,
        label="scalar_one_of_refs",
    )
    contains = _constraint_map(
        contains_refs,
        allowed_fields=TUPLE_CHAIN_FIELDS,
        label="contains_refs",
    )
    exact_tuples = _constraint_map(
        exact_tuple_refs,
        allowed_fields=TUPLE_CHAIN_FIELDS,
        label="exact_tuple_refs",
    )
    overlap = set(contains).intersection(exact_tuples)
    if overlap:
        raise SpineChainSelectionError(
            "tuple fields cannot use contains and exact constraints together: "
            + ", ".join(sorted(overlap))
        )
    scalar_overlap = set(scalars).intersection(scalar_one_of)
    if scalar_overlap:
        raise SpineChainSelectionError(
            "scalar fields cannot use exact and one-of constraints together: "
            + ", ".join(sorted(scalar_overlap))
        )

    union_constraints: list[tuple[tuple[str, ...], frozenset[str]]] = []
    for index, raw_constraint in enumerate(tuple(union_contains_refs or ())):
        try:
            raw_fields, raw_refs = raw_constraint
        except (TypeError, ValueError) as exc:
            raise SpineChainSelectionError(
                f"union_contains_refs[{index}] must be a fields/refs pair"
            ) from exc
        fields = tuple(str(field) for field in tuple(raw_fields or ()))
        if (
            not fields
            or len(fields) != len(set(fields))
            or set(fields).difference(TUPLE_CHAIN_FIELDS)
        ):
            raise SpineChainSelectionError(
                f"union_contains_refs[{index}] contains invalid tuple fields"
            )
        refs = frozenset(
            _tuple_refs(raw_refs, field=f"union_contains_refs[{index}].refs")
        )
        union_constraints.append((fields, refs))

    if (
        not scalars
        and not scalar_one_of
        and not contains
        and not exact_tuples
        and not union_constraints
    ):
        raise SpineChainSelectionError("at least one typed chain constraint is required")

    expected_scalars = {
        field: _exact_ref(value, field=f"scalar_refs.{field}")
        for field, value in scalars.items()
    }
    expected_scalar_one_of = {
        field: frozenset(
            _tuple_refs(value, field=f"scalar_one_of_refs.{field}")
        )
        for field, value in scalar_one_of.items()
    }
    expected_contains = {
        field: frozenset(_tuple_refs(value, field=f"contains_refs.{field}"))
        for field, value in contains.items()
    }
    expected_exact = {
        field: frozenset(_tuple_refs(value, field=f"exact_tuple_refs.{field}"))
        for field, value in exact_tuples.items()
    }

    try:
        projections = tuple(registry.chains(owner=owner) or ())
    except (KeyError, LookupError, OSError, TypeError, ValueError) as exc:
        raise SpineChainSelectionError(
            f"owner Mathematical Spine projection is unavailable:{type(exc).__name__}"
        ) from exc

    matches: list[Any] = []
    for projection in projections:
        projected_owner = _exact_ref(
            getattr(projection, "recorded_by", ""),
            field="chain.recorded_by",
        )
        if projected_owner != owner:
            raise SpineChainSelectionError(
                "owner-scoped Mathematical Spine projection returned a foreign chain"
            )
        if any(
            _exact_ref(getattr(projection, field, ""), field=f"chain.{field}")
            != expected
            for field, expected in expected_scalars.items()
        ):
            continue
        if any(
            _exact_ref(getattr(projection, field, ""), field=f"chain.{field}")
            not in expected
            for field, expected in expected_scalar_one_of.items()
        ):
            continue

        tuple_values: dict[str, frozenset[str]] = {}
        tuple_invalid = False
        union_fields = tuple(
            dict.fromkeys(
                field
                for fields, _expected in union_constraints
                for field in fields
            )
        )
        for field in (*expected_contains, *expected_exact, *union_fields):
            raw_refs = tuple(getattr(projection, field, ()) or ())
            try:
                refs = _tuple_refs(raw_refs, field=f"chain.{field}")
            except SpineChainSelectionError:
                tuple_invalid = True
                break
            tuple_values[field] = frozenset(refs)
        if tuple_invalid:
            continue
        if any(
            not expected.issubset(tuple_values[field])
            for field, expected in expected_contains.items()
        ):
            continue
        if any(
            expected != tuple_values[field]
            for field, expected in expected_exact.items()
        ):
            continue
        if any(
            not expected.issubset(
                frozenset().union(*(tuple_values[field] for field in fields))
            )
            for fields, expected in union_constraints
        ):
            continue

        chain_ref = _exact_ref(
            getattr(projection, "chain_ref", ""),
            field="chain.chain_ref",
        )
        try:
            verified = registry.verified_chain(chain_ref, owner=owner)
        except (KeyError, LookupError, OSError, TypeError, ValueError) as exc:
            raise SpineChainSelectionError(
                f"matching Mathematical Spine chain is not verified:{type(exc).__name__}"
            ) from exc
        if (
            verified != projection
            or _exact_ref(getattr(verified, "chain_ref", ""), field="verified.chain_ref")
            != chain_ref
            or _exact_ref(
                getattr(verified, "recorded_by", ""),
                field="verified.recorded_by",
            )
            != owner
        ):
            raise SpineChainSelectionError(
                "Mathematical Spine projection and verified record differ"
            )
        matches.append(verified)

    if len(matches) != 1:
        raise SpineChainSelectionError(
            "typed business refs must resolve to exactly one owner-scoped verified "
            f"Mathematical Spine chain; found {len(matches)}"
        )
    return matches[0]


__all__ = [
    "SCALAR_CHAIN_FIELDS",
    "TUPLE_CHAIN_FIELDS",
    "SpineChainSelectionError",
    "resolve_unique_verified_spine_chain",
]
