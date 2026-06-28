"""Adversarial tests for the generalized real-reference resolver (card SA-1).

``ref_resolution.resolve_typed_ref`` is the single fail-closed gate that decides
whether a *typed* coverage ref is backed by a real object in a real backend
store. These tests seed known-"bad" refs (unresolvable, placeholder /
goal-closure, wrong type, store error) and prove the gate rejects them, plus
that a genuinely-minted ref is accepted.

Teeth split honestly:
* the math_spine cases run end-to-end against a REAL
  ``PersistentMathematicalSpineChainRegistry`` + ``RealRefResolver``;
* the generalized dispatch / fail-closed matrix runs against an in-memory
  ``RefResolver`` double that exercises the composition logic (ref-type ->
  getter, unknown type, missing method, raising store) independent of any one
  backend's shape. The six per-store getters themselves are adversarially
  covered end-to-end in ``test_platform_coverage.py``.
"""

from __future__ import annotations

from app.research_os import (
    ConsistencyStatus,
    MathematicalSpineChainRecord,
    PersistentMathematicalSpineChainRegistry,
    RuntimeStatus,
)
from app.research_os.ref_resolution import (
    PLACEHOLDER_TOKENS,
    REF_TYPE_RESOLVER_METHODS,
    build_real_ref_resolver,
    is_placeholder_ref,
    resolve_typed_ref,
)


class _DictResolver:
    """A ``RefResolver`` whose six getters answer from in-memory sets of "minted"
    ids. Drives the generalized dispatch + fail-closed matrix; it is a
    composition-logic double, not a stand-in for real-store resolution (covered
    against real stores below and in ``test_platform_coverage.py``)."""

    def __init__(self, **backed: set[str]) -> None:
        self._backed = {ref_type: set(ids) for ref_type, ids in backed.items()}

    def _has(self, ref_type: str, ref: str) -> bool:
        return ref in self._backed.get(ref_type, set())

    def has_qro(self, ref: str) -> bool:
        return self._has("qro", ref)

    def has_research_graph_command(self, ref: str) -> bool:
        return self._has("research_graph", ref)

    def has_lifecycle_record(self, ref: str) -> bool:
        return self._has("lifecycle", ref)

    def has_governance_record(self, ref: str) -> bool:
        return self._has("governance", ref)

    def has_rag_asset(self, ref: str) -> bool:
        return self._has("rag", ref)

    def has_math_spine_chain(self, ref: str) -> bool:
        return self._has("math_spine", ref)


class _RaisingResolver:
    """Every getter raises -- proves ``resolve_typed_ref`` fails closed on error
    instead of letting the exception (or a default-accept) leak through."""

    def has_qro(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_research_graph_command(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_lifecycle_record(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_governance_record(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_rag_asset(self, ref: str) -> bool:
        raise RuntimeError("store down")

    def has_math_spine_chain(self, ref: str) -> bool:
        raise RuntimeError("store down")


def _mk_chain(**overrides) -> MathematicalSpineChainRecord:
    data = {
        "chain_ref": "math_spine_chain:ref_resolution_real:v1",
        "data_semantics_ref": "dataset_semantics:btc_1d",
        "factor_ref": "factor:momentum_20d",
        "model_ref": "model:momentum_classifier:v1",
        "forecast_ref": "forecast:btc_momentum:v1",
        "signal_contract_ref": "signal_contract:btc_momentum:v1",
        "strategy_book_ref": "strategy_book:btc_momentum:v1",
        "portfolio_policy_ref": "portfolio_policy:btc_momentum:v1",
        "risk_policy_ref": "risk_policy:btc_momentum:v1",
        "execution_policy_ref": "execution_policy:paper_btc:v1",
        "backtest_run_ref": "backtest_run:bt1",
        "attribution_ref": "attribution:bt1",
        "monitor_ref": "monitor:weekly_btc_momentum",
        "theory_binding_refs": ("tbind:momentum", "tbind:portfolio-risk"),
        "consistency_check_refs": ("ccheck:momentum", "ccheck:risk"),
        "methodology_choice_ref": "mchoice:standard",
        "responsibility_boundary_ref": "resp:standard",
        "evidence_refs": ("evidence:bt1", "evidence:monitor"),
        "validation_refs": ("pytest:test_ref_resolution",),
        "consistency_verdict": ConsistencyStatus.ACCEPTED,
        "target_runtime": RuntimeStatus.PAPER,
        "recorded_by": "u1",
    }
    data.update(overrides)
    return MathematicalSpineChainRecord(**data)


def _real_spine_backing(tmp_path):
    """Real spine store + a real resolver over it (other stores unused here)."""

    spine = PersistentMathematicalSpineChainRegistry(tmp_path / "mathematical_spine_chains.jsonl")
    resolver = build_real_ref_resolver(
        research_graph_store=None,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=spine,
    )
    return spine, resolver


# ---------------------------------------------------------------------------
# Real-store teeth (RealRefResolver end-to-end on the math_spine type)
# ---------------------------------------------------------------------------


def test_real_minted_chain_resolves_as_backed(tmp_path):
    # Positive control: a genuinely-minted chain id resolves to a real object.
    spine, resolver = _real_spine_backing(tmp_path)
    chain = spine.record_chain(_mk_chain())
    assert resolver.has_math_spine_chain(chain.chain_ref) is True
    assert resolve_typed_ref(resolver, "math_spine", chain.chain_ref) is True


def test_unresolvable_ref_is_not_backed_mutation_guard(tmp_path):
    # MUTATION TARGET (accept-without-resolving): a real-shaped id that was never
    # minted must resolve to nothing. Weaken resolve_typed_ref to return True
    # without actually calling the store getter and this assertion turns RED;
    # restore it and the assertion is GREEN. Run against the real resolver.
    spine, resolver = _real_spine_backing(tmp_path)
    spine.record_chain(_mk_chain())  # store is non-empty, but not this id
    assert resolver.has_math_spine_chain("math_spine_chain:never_minted:v1") is False
    assert resolve_typed_ref(resolver, "math_spine", "math_spine_chain:never_minted:v1") is False


def test_goal_closure_ref_banned_even_when_it_resolves_in_store(tmp_path):
    # Recursive-fake-green defense: a goal_closure:* chain really exists in the
    # store (the removed materializer seeded such records), so the raw getter
    # returns True -- but the token ban makes resolve_typed_ref reject it.
    spine, resolver = _real_spine_backing(tmp_path)
    seeded = spine.record_chain(_mk_chain(chain_ref="math_spine_chain:goal_closure:section_0_17:v1"))
    assert resolver.has_math_spine_chain(seeded.chain_ref) is True  # raw store says backed
    assert resolve_typed_ref(resolver, "math_spine", seeded.chain_ref) is False  # gate says not


# ---------------------------------------------------------------------------
# Generalized dispatch + fail-closed matrix (composition double)
# ---------------------------------------------------------------------------


def test_backed_id_is_backed_unbacked_is_not():
    resolver = _DictResolver(qro={"qro_real_1"}, math_spine={"math_spine_chain:real:v1"})
    assert resolve_typed_ref(resolver, "qro", "qro_real_1") is True
    assert resolve_typed_ref(resolver, "math_spine", "math_spine_chain:real:v1") is True
    assert resolve_typed_ref(resolver, "qro", "qro_never_minted") is False
    assert resolve_typed_ref(resolver, "math_spine", "math_spine_chain:never:v1") is False


def test_every_ref_type_dispatches_to_its_own_getter():
    # Each ref-type must resolve only its own store's minted id; a different
    # type's id must not leak across. Guards the REF_TYPE_RESOLVER_METHODS map.
    for ref_type in REF_TYPE_RESOLVER_METHODS:
        resolver = _DictResolver(**{ref_type: {"id_real"}})
        assert resolve_typed_ref(resolver, ref_type, "id_real") is True
        assert resolve_typed_ref(resolver, ref_type, "id_other") is False


def test_fail_closed_without_resolver():
    assert resolve_typed_ref(None, "qro", "qro_real_1") is False


def test_fail_closed_unknown_ref_type():
    resolver = _DictResolver(qro={"qro_real_1"})
    assert resolve_typed_ref(resolver, "not_a_ref_type", "qro_real_1") is False


def test_fail_closed_empty_ref():
    resolver = _DictResolver(qro={"qro_real_1", ""})
    assert resolve_typed_ref(resolver, "qro", "") is False
    assert resolve_typed_ref(resolver, "qro", None) is False


def test_fail_closed_when_resolution_raises():
    assert resolve_typed_ref(_RaisingResolver(), "qro", "qro_real_1") is False
    assert resolve_typed_ref(_RaisingResolver(), "math_spine", "math_spine_chain:real:v1") is False


def test_placeholder_token_ref_never_backed_even_if_minted():
    # Every banned token, with a resolver that "minted" the placeholder id: the
    # token ban must win over resolution for all of them.
    for token in PLACEHOLDER_TOKENS:
        ref = f"math_spine_chain:{token}:v1"
        resolver = _DictResolver(math_spine={ref})
        assert is_placeholder_ref(ref) is True
        assert resolve_typed_ref(resolver, "math_spine", ref) is False


def test_is_placeholder_ref_matrix():
    assert is_placeholder_ref(None) is False
    assert is_placeholder_ref("") is False
    assert is_placeholder_ref("qro_platform_m3_real") is False
    assert is_placeholder_ref("rgcmd_unbacked0000000000") is False
    assert is_placeholder_ref("GOAL_CLOSURE:section_0_17") is True  # case-insensitive
    assert is_placeholder_ref("math_spine_chain:goalclosure:v1") is True
    assert is_placeholder_ref("x_synthetic_y") is True
    assert is_placeholder_ref("some_PLACEHOLDER_id") is True
