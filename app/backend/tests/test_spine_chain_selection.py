from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from app.research_os.spine_chain_selection import (
    SpineChainSelectionError,
    resolve_unique_verified_spine_chain,
)


OWNER = "owner:spine-selection"


@dataclass(frozen=True)
class _Chain:
    chain_ref: str
    recorded_by: str = OWNER
    data_semantics_ref: str = "dataset:prices:v1"
    factor_ref: str = "factor:momentum:v1"
    model_ref: str = "model_version:momentum:v1"
    forecast_ref: str = "forecast:momentum:v1"
    signal_contract_ref: str = "signal_contract:momentum:v1"
    strategy_book_ref: str = "strategy_book:momentum:v1"
    portfolio_policy_ref: str = "portfolio_policy:momentum:v1"
    risk_policy_ref: str = "risk_policy:momentum:v1"
    execution_policy_ref: str = "execution_policy:momentum:v1"
    backtest_run_ref: str = "qro_backtest_momentum"
    attribution_ref: str = "backtest_attribution:momentum:v1"
    monitor_ref: str = "backtest_monitor:momentum:v1"
    methodology_choice_ref: str = "methodology_choice:momentum:v1"
    responsibility_boundary_ref: str = "responsibility:momentum:v1"
    theory_binding_refs: tuple[str, ...] = ("tib:momentum:v1",)
    consistency_check_refs: tuple[str, ...] = ("cc_momentum_v1",)
    evidence_refs: tuple[str, ...] = (
        "hypothesis_card:momentum:v1",
        "label:forward_return:v1",
    )
    validation_refs: tuple[str, ...] = ("validation:momentum:v1",)


class _Registry:
    def __init__(self, *chains: _Chain, replacement: _Chain | None = None) -> None:
        self._chains = tuple(chains)
        self._replacement = replacement
        self.verify_calls: list[tuple[str, str]] = []

    def chains(self, *, owner: str):
        return tuple(item for item in self._chains if item.recorded_by == owner)

    def verified_chain(self, ref: str, *, owner: str):
        self.verify_calls.append((ref, owner))
        if self._replacement is not None:
            return self._replacement
        return next(
            item
            for item in self._chains
            if item.chain_ref == ref and item.recorded_by == owner
        )


def test_selects_one_chain_by_exact_scalar_and_typed_membership() -> None:
    selected = _Chain("math_spine_chain:momentum:v1")
    unrelated = replace(
        selected,
        chain_ref="math_spine_chain:other:v1",
        strategy_book_ref="strategy_book:other:v1",
    )
    registry = _Registry(selected, unrelated)

    resolved = resolve_unique_verified_spine_chain(
        registry,
        owner_user_id=OWNER,
        scalar_refs={
            "strategy_book_ref": selected.strategy_book_ref,
            "risk_policy_ref": selected.risk_policy_ref,
            "execution_policy_ref": selected.execution_policy_ref,
        },
        contains_refs={
            "evidence_refs": ("hypothesis_card:momentum:v1",),
        },
    )

    assert resolved == selected
    assert registry.verify_calls == [(selected.chain_ref, OWNER)]


def test_scalar_one_of_and_tuple_union_preserve_global_uniqueness() -> None:
    selected = _Chain("math_spine_chain:momentum:v1")
    split = replace(
        selected,
        evidence_refs=("hypothesis_card:momentum:v1",),
        validation_refs=("label:forward_return:v1",),
    )
    resolved = resolve_unique_verified_spine_chain(
        _Registry(split),
        owner_user_id=OWNER,
        scalar_one_of_refs={
            "model_ref": ("model_passport:momentum:v1", split.model_ref),
        },
        union_contains_refs=(
            (
                ("evidence_refs", "validation_refs"),
                (
                    "hypothesis_card:momentum:v1",
                    "label:forward_return:v1",
                ),
            ),
        ),
    )
    assert resolved == split

    second = replace(
        split,
        chain_ref="math_spine_chain:passport:v1",
        model_ref="model_passport:momentum:v1",
    )
    with pytest.raises(SpineChainSelectionError, match="found 2"):
        resolve_unique_verified_spine_chain(
            _Registry(split, second),
            owner_user_id=OWNER,
            scalar_one_of_refs={
                "model_ref": (split.model_ref, second.model_ref),
            },
            union_contains_refs=(
                (
                    ("evidence_refs", "validation_refs"),
                    (
                        "hypothesis_card:momentum:v1",
                        "label:forward_return:v1",
                    ),
                ),
            ),
        )


def test_exact_tuple_constraint_is_order_independent_but_not_subset_only() -> None:
    selected = _Chain("math_spine_chain:momentum:v1")
    resolved = resolve_unique_verified_spine_chain(
        _Registry(selected),
        owner_user_id=OWNER,
        exact_tuple_refs={
            "evidence_refs": tuple(reversed(selected.evidence_refs)),
        },
    )
    assert resolved == selected

    with pytest.raises(SpineChainSelectionError, match="found 0"):
        resolve_unique_verified_spine_chain(
            _Registry(selected),
            owner_user_id=OWNER,
            exact_tuple_refs={
                "evidence_refs": (selected.evidence_refs[0],),
            },
        )


@pytest.mark.parametrize(
    "registry",
    (
        _Registry(),
        _Registry(
            _Chain("math_spine_chain:one"),
            _Chain("math_spine_chain:two"),
        ),
    ),
)
def test_zero_or_ambiguous_candidates_fail_closed(registry: _Registry) -> None:
    with pytest.raises(SpineChainSelectionError, match="exactly one"):
        resolve_unique_verified_spine_chain(
            registry,
            owner_user_id=OWNER,
            scalar_refs={"factor_ref": "factor:momentum:v1"},
        )


def test_foreign_owner_projection_from_filtered_registry_is_corruption() -> None:
    class _BrokenRegistry(_Registry):
        def chains(self, *, owner: str):
            return (
                replace(
                    _Chain("math_spine_chain:foreign"),
                    recorded_by="owner:foreign",
                ),
            )

    with pytest.raises(SpineChainSelectionError, match="foreign chain"):
        resolve_unique_verified_spine_chain(
            _BrokenRegistry(),
            owner_user_id=OWNER,
            scalar_refs={"factor_ref": "factor:momentum:v1"},
        )


def test_verified_projection_drift_and_unverified_match_fail_closed() -> None:
    selected = _Chain("math_spine_chain:momentum:v1")
    replacement = replace(selected, monitor_ref="backtest_monitor:drifted:v2")
    with pytest.raises(SpineChainSelectionError, match="differ"):
        resolve_unique_verified_spine_chain(
            _Registry(selected, replacement=replacement),
            owner_user_id=OWNER,
            scalar_refs={"monitor_ref": selected.monitor_ref},
        )

    class _RejectingRegistry(_Registry):
        def verified_chain(self, ref: str, *, owner: str):
            raise ValueError("current backing failed")

    with pytest.raises(SpineChainSelectionError, match="not verified:ValueError"):
        resolve_unique_verified_spine_chain(
            _RejectingRegistry(selected),
            owner_user_id=OWNER,
            scalar_refs={"monitor_ref": selected.monitor_ref},
        )


@pytest.mark.parametrize(
    "kwargs, message",
    (
        ({}, "at least one"),
        ({"scalar_refs": {"unknown_ref": "x:y"}}, "unsupported fields"),
        (
            {
                "contains_refs": {"evidence_refs": ("evidence:one",)},
                "exact_tuple_refs": {"evidence_refs": ("evidence:one",)},
            },
            "cannot use contains and exact",
        ),
        (
            {
                "scalar_refs": {"model_ref": "model:one"},
                "scalar_one_of_refs": {"model_ref": ("model:one", "model:two")},
            },
            "cannot use exact and one-of",
        ),
        (
            {
                "union_contains_refs": (
                    (("evidence_refs", "unknown_refs"), ("evidence:one",)),
                )
            },
            "invalid tuple fields",
        ),
        (
            {"scalar_refs": {"factor_ref": "placeholder:factor"}},
            "not an exact stable ref",
        ),
        (
            {
                "contains_refs": {
                    "evidence_refs": ("evidence:one", "evidence:one"),
                }
            },
            "duplicate refs",
        ),
    ),
)
def test_invalid_or_placeholder_constraints_are_rejected_before_reads(
    kwargs: dict,
    message: str,
) -> None:
    registry = _Registry(_Chain("math_spine_chain:momentum:v1"))
    with pytest.raises(SpineChainSelectionError, match=message):
        resolve_unique_verified_spine_chain(
            registry,
            owner_user_id=OWNER,
            **kwargs,
        )
    assert registry.verify_calls == []


def test_duplicate_projected_tuple_refs_cannot_match_exact_constraint() -> None:
    selected = replace(
        _Chain("math_spine_chain:momentum:v1"),
        evidence_refs=("evidence:one", "evidence:one"),
    )
    with pytest.raises(SpineChainSelectionError, match="found 0"):
        resolve_unique_verified_spine_chain(
            _Registry(selected),
            owner_user_id=OWNER,
            exact_tuple_refs={"evidence_refs": ("evidence:one",)},
        )
