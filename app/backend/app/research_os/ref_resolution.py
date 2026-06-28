"""Generalized real-reference resolution (GOAL §0 / §1 / §8 / §14 · card SA-1).

Shared ancestor extracted from
``platform_coverage.validate_platform_capability_real_backing``. It owns the one
algorithm that decides whether a *typed* coverage ref is backed by a real object
in a real backend store, so coverage gates stop rubber-stamping lexically-shaped
strings. Consumers (``platform_coverage`` today; ``goal_coverage`` / ``rdp``
next) inject a resolver and ask :func:`resolve_typed_ref` per ref-type; there is
no second resolution algorithm.

Contract (fail-closed, in this order):

* empty ref                     -> not backed
* placeholder / goal-closure /
  synthetic token in the ref     -> not backed (even if it really resolves)
* no resolver wired             -> not backed
* unknown ref-type              -> not backed
* resolver has no method / the
  store lookup raises            -> not backed
* the ref resolves to a real
  persisted object               -> backed

The resolver only READS existing stores via their existing getters. It never
mints, materializes, or self-certifies anything.
"""

from __future__ import annotations

from typing import Any, Protocol

# Tokens that mark a ref as a synthetic / placeholder / self-certifying-closure
# string rather than a real persisted store id. Banned even when the ref happens
# to resolve, because the closure materializer that was removed seeded some
# dependency stores (e.g. mathematical_spine_chains.jsonl) with goal_closure:*
# placeholder records -- a pure resolution check alone could be fooled by them.
PLACEHOLDER_TOKENS: tuple[str, ...] = (
    "synthetic",
    "fixture",
    "test_only",
    "test-only",
    "goal_closure",
    "goal-closure",
    "goalclosure",
    "placeholder",
)


def is_placeholder_ref(ref: str | None) -> bool:
    """True if ``ref`` carries any banned placeholder / goal-closure token.

    Case-insensitive substring scan. A placeholder ref is never "backed" even
    when it resolves in a store, so callers must reject it before (or regardless
    of) real-store resolution.
    """

    lowered = str(ref or "").lower()
    return any(token in lowered for token in PLACEHOLDER_TOKENS)


class RefResolver(Protocol):
    """Resolves a coverage ref to a real object in a real backend store.

    Implementations MUST return True only when the ref is the id of an object
    that is actually persisted in the corresponding store. Nonexistent or
    placeholder ids MUST return False (fail-closed).
    """

    def has_qro(self, ref: str) -> bool: ...

    def has_research_graph_command(self, ref: str) -> bool: ...

    def has_lifecycle_record(self, ref: str) -> bool: ...

    def has_governance_record(self, ref: str) -> bool: ...

    def has_rag_asset(self, ref: str) -> bool: ...

    def has_math_spine_chain(self, ref: str) -> bool: ...


# Maps a logical ref-type to the resolver method that owns its backend store.
# Keys are the ref-type (the record field name without its ``_ref`` suffix), so
# callers can derive the type mechanically from a typed field. Adding a new
# real-store ref-type is one entry here plus one method on :class:`RefResolver`.
REF_TYPE_RESOLVER_METHODS: dict[str, str] = {
    "qro": "has_qro",
    "research_graph": "has_research_graph_command",
    "lifecycle": "has_lifecycle_record",
    "governance": "has_governance_record",
    "rag": "has_rag_asset",
    "math_spine": "has_math_spine_chain",
}


class RealRefResolver:
    """Resolve coverage refs against the real QRO / research graph / lifecycle /
    governance / RAG / Mathematical Spine stores.

    This reuses the existing store getters (no new store APIs). A ref counts as
    backed only when the matching getter returns a real persisted object; a
    missing id raises ``KeyError``/``LookupError`` inside the store and is
    reported here as not backed (fail-closed). The resolver does NOT mint,
    materialize, or self-certify anything -- it only reads existing stores.
    """

    def __init__(
        self,
        *,
        research_graph_store: Any,
        lifecycle_registry: Any,
        governance_registry: Any,
        rag_index: Any,
        spine_chain_registry: Any,
    ) -> None:
        self._research_graph_store = research_graph_store
        self._lifecycle_registry = lifecycle_registry
        self._governance_registry = governance_registry
        self._rag_index = rag_index
        self._spine_chain_registry = spine_chain_registry

    def has_qro(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        try:
            self._research_graph_store.qro(ref)
            return True
        except (KeyError, LookupError):
            return False

    def has_research_graph_command(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        return any(
            getattr(command, "command_id", None) == ref
            for command in self._research_graph_store.commands()
        )

    def has_lifecycle_record(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        try:
            self._lifecycle_registry.ingestion_skill_update(ref)
            return True
        except (KeyError, LookupError):
            return False

    def has_governance_record(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        for getter_name in (
            "passport",
            "monitoring_profile",
            "recertification_record",
            "artifact_inspection",
            "serving_invocation",
        ):
            getter = getattr(self._governance_registry, getter_name, None)
            if getter is None:
                continue
            try:
                getter(ref)
                return True
            except (KeyError, LookupError):
                continue
        return False

    def has_rag_asset(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        return any(
            getattr(vector, "document_id", None) == ref
            for vector in self._rag_index.dense_vectors()
        )

    def has_math_spine_chain(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        try:
            self._spine_chain_registry.chain(ref)
            return True
        except (KeyError, LookupError):
            return False


def build_real_ref_resolver(
    *,
    research_graph_store: Any,
    lifecycle_registry: Any,
    governance_registry: Any,
    rag_index: Any,
    spine_chain_registry: Any,
) -> RealRefResolver:
    """Build the production resolver from the real backend store singletons.

    Intended to be wired once at startup, e.g. in ``app.main``::

        set_default_platform_coverage_resolver(
            build_real_ref_resolver(
                research_graph_store=RESEARCH_GRAPH_STORE,
                lifecycle_registry=ASSET_LIFECYCLE_REGISTRY,
                governance_registry=MODEL_GOVERNANCE_REGISTRY,
                rag_index=RESEARCH_ASSET_RAG_INDEX,
                spine_chain_registry=MATHEMATICAL_SPINE_CHAIN_REGISTRY,
            )
        )
    """

    return RealRefResolver(
        research_graph_store=research_graph_store,
        lifecycle_registry=lifecycle_registry,
        governance_registry=governance_registry,
        rag_index=rag_index,
        spine_chain_registry=spine_chain_registry,
    )


def resolve_typed_ref(
    resolver: RefResolver | None,
    ref_type: str,
    ref: str,
) -> bool:
    """Return True only if ``resolver`` proves ``ref`` resolves to a real object.

    Fail-closed: an empty ref, a placeholder / goal-closure / synthetic token, a
    missing resolver, an unknown ``ref_type``, a resolver missing the method, or
    any error during resolution all count as not backed.

    The placeholder-token ban runs before real-store resolution so a dependency
    store seeded with a ``goal_closure:*`` placeholder record cannot launder a
    ref into "backed".
    """

    ref = str(ref or "")
    if not ref:
        return False
    if is_placeholder_ref(ref):
        return False
    if resolver is None:
        return False
    method_name = REF_TYPE_RESOLVER_METHODS.get(ref_type)
    if method_name is None:
        return False
    method = getattr(resolver, method_name, None)
    if method is None:
        return False
    try:
        return bool(method(ref))
    except Exception:  # noqa: BLE001 - a gate must fail closed if resolution errors.
        return False


__all__ = [
    "PLACEHOLDER_TOKENS",
    "REF_TYPE_RESOLVER_METHODS",
    "RealRefResolver",
    "RefResolver",
    "build_real_ref_resolver",
    "is_placeholder_ref",
    "resolve_typed_ref",
]
