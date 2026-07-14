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

from typing import Any, Callable, Protocol

from ..lineage.ids import content_hash
from .market_data_contract import (
    MarketDataUseRequest,
    PersistentMarketDataRegistry,
    validate_market_data_use,
)

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


def is_exact_current_research_graph_command(
    research_graph_store: Any,
    command: Any,
    *,
    owner_user_id: str,
    qro_ref: str | None = None,
) -> bool:
    """Prove one persisted command is the exact current QRO projection head."""

    def enum_text(value: Any) -> str:
        return str(getattr(value, "value", value) or "")

    try:
        owner_raw = str(owner_user_id or "")
        owner = owner_raw.strip()
        if not owner or owner != owner_raw:
            return False
        refresh = getattr(research_graph_store, "refresh", None)
        if callable(refresh):
            refresh()
        command_id = str(getattr(command, "command_id", "") or "")
        if not command_id or command_id != command_id.strip():
            return False
        payload = getattr(command, "payload", None)
        command_qro = payload.get("qro") if isinstance(payload, dict) else None
        qro_id = str(getattr(command_qro, "qro_id", "") or "")
        expected_qro_id = str(qro_ref or qro_id)
        if (
            str(getattr(command, "command_type", "") or "") != "upsert_qro"
            or not qro_id
            or qro_id != expected_qro_id
            or str(getattr(command_qro, "owner", "") or "") != owner
        ):
            return False
        command_matches = tuple(
            item
            for item in research_graph_store.commands()
            if str(getattr(item, "command_id", "") or "") == command_id
        )
        if len(command_matches) != 1 or command_matches[0] != command:
            return False
        if research_graph_store.qro(qro_id) != command_qro:
            return False
        projections = tuple(
            projection
            for projection in research_graph_store.projection_index(owner=owner)
            if str(getattr(projection, "qro_id", "") or "") == qro_id
        )
        if len(projections) != 1:
            return False
        projection = projections[0]
        return all(
            (
                str(getattr(projection, "command_id", "") or "")
                == command_id,
                str(getattr(projection, "owner", "") or "") == owner,
                str(getattr(projection, "source", "") or "")
                == enum_text(getattr(command, "source", "")),
                str(getattr(projection, "actor_source", "") or "")
                == enum_text(getattr(command, "actor_source", "")),
                str(getattr(projection, "actor", "") or "")
                == str(getattr(command, "actor", "") or ""),
                str(getattr(projection, "command_timestamp", "") or "")
                == str(getattr(command, "timestamp", "") or ""),
                int(getattr(projection, "qro_version", 0) or 0)
                == int(getattr(command_qro, "version", 0) or 0),
            )
        )
    except Exception:  # noqa: BLE001 - exact-current proof fails closed.
        return False


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

    def has_math_spine_member(self, chain_ref: str, member_type: str, ref: str) -> bool: ...

    def has_compiler_ir(self, ref: str) -> bool: ...

    def has_compiler_pass(self, ref: str) -> bool: ...

    def has_evidence(self, ref: str) -> bool: ...

    def has_platform_evidence(self, record: Any, ref: str) -> bool: ...

    def has_platform_specific_ref(self, key: str, ref: str, record: Any) -> bool: ...

    def has_platform_common_ref(self, field: str, ref: str, record: Any) -> bool | None: ...

    def platform_linkage_violations(self, record: Any) -> tuple[tuple[str, str, str], ...]: ...

    def has_rdp(self, ref: str) -> bool: ...

    def entrypoint_linkage_violations(self, record: Any) -> tuple[tuple[str, str, str], ...]: ...


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
    "compiler_ir": "has_compiler_ir",
    "compiler_pass": "has_compiler_pass",
    "evidence": "has_evidence",
    "rdp": "has_rdp",
}


class _CompilerArtifactCandidateStore:
    """Read-only compiler overlay used only for precommit validation."""

    def __init__(self, delegate: Any, artifact: Any) -> None:
        self._delegate = delegate
        self._artifact = artifact

    def ir(self, ref: str, *, owner: str | None = None) -> Any:
        return self._delegate.ir(ref, owner=owner)

    def compiler_pass(self, ref: str, *, owner: str | None = None) -> Any:
        return self._delegate.compiler_pass(ref, owner=owner)

    def canonical_ir(self, ref: str, *, owner: str) -> Any:
        return self._delegate.canonical_ir(ref, owner=owner)

    def canonical_compiler_pass(self, ref: str, *, owner: str) -> Any:
        return self._delegate.canonical_compiler_pass(ref, owner=owner)

    def artifact(self, ref: str, *, owner: str | None = None) -> Any:
        candidate_owner = str(getattr(self._artifact, "owner", "") or "")
        if ref == str(getattr(self._artifact, "artifact_ref", "") or "") and (
            owner is None or str(owner or "") == candidate_owner
        ):
            return self._artifact
        return self._delegate.artifact(ref, owner=owner)

    def canonical_artifact(self, ref: str, *, owner: str) -> Any:
        candidate_owner = str(getattr(self._artifact, "owner", "") or "")
        if (
            ref == str(getattr(self._artifact, "artifact_ref", "") or "")
            and owner == candidate_owner
        ):
            return self._artifact
        return self._delegate.canonical_artifact(ref, owner=owner)

    def canonical_records(self, *, owner: str) -> Any:
        return self._delegate.canonical_records(owner=owner)

    def irs(self, *, owner: str | None = None) -> Any:
        return self._delegate.irs(owner=owner)

    def passes(self, *, owner: str | None = None) -> Any:
        return self._delegate.passes(owner=owner)


class _CompilerArtifactCandidateEvidenceRegistry:
    """Delegate evidence reads while binding one uncommitted artifact."""

    def __init__(self, delegate: Any, artifact: Any) -> None:
        self._delegate = delegate
        self._artifact = artifact

    def evidence(self, ref: str, *, owner_user_id: str) -> Any:
        return self._delegate.evidence(ref, owner_user_id=owner_user_id)

    def validate_current(self, record: Any, *, owner_user_id: str) -> Any:
        return self._delegate.validate_current(
            record,
            owner_user_id=owner_user_id,
        )

    def validate_platform_ref(
        self,
        ref: str,
        *,
        owner_user_id: str,
        record: Any,
    ) -> Any:
        return self._delegate.validate_platform_ref(
            ref,
            owner_user_id=owner_user_id,
            record=record,
        )

    def validate_entrypoint_ref(
        self,
        ref: str,
        *,
        owner_user_id: str,
        record: Any,
    ) -> Any:
        return self._delegate.validate_entrypoint_ref(
            ref,
            owner_user_id=owner_user_id,
            record=record,
            artifact_candidate=self._artifact,
        )


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
        compiler_store: Any = None,
        document_store: Any = None,
        rdp_store: Any = None,
        market_data_registry: PersistentMarketDataRegistry | None = None,
        dataset_registry: Any = None,
        onboarding_registry: Any = None,
        llm_service_owner_user_id: str | None = None,
        llm_call_record_store: Any = None,
        account_halt_barrier: Any = None,
        goal_validation_receipt_registry: Any = None,
        goal_full_product_attestation_registry: Any = None,
        platform_source_evidence_registry: Any = None,
        lifecycle_loaders: tuple[Callable[[str, str], Any], ...] = (),
        owner: str | None = None,
    ) -> None:
        self._research_graph_store = research_graph_store
        self._lifecycle_registry = lifecycle_registry
        self._governance_registry = governance_registry
        self._rag_index = rag_index
        self._spine_chain_registry = spine_chain_registry
        self._compiler_store = compiler_store
        self._document_store = document_store
        self._rdp_store = rdp_store
        self._market_data_registry = market_data_registry
        self._dataset_registry = dataset_registry
        self._onboarding_registry = onboarding_registry
        self._llm_service_owner_user_id = str(llm_service_owner_user_id or "").strip() or None
        self._llm_call_record_store = llm_call_record_store
        self._account_halt_barrier = account_halt_barrier
        self._goal_validation_receipt_registry = goal_validation_receipt_registry
        self._goal_full_product_attestation_registry = (
            goal_full_product_attestation_registry
        )
        self._platform_source_evidence_registry = (
            platform_source_evidence_registry
        )
        self._lifecycle_loaders = tuple(lifecycle_loaders)
        self._owner = str(owner or "").strip() or None

    def set_platform_source_evidence_registry(self, registry: Any) -> None:
        """Attach the independent platform-source evidence ledger at startup."""

        for method_name in ("evidence", "validate_current", "validate_platform_ref"):
            if not callable(getattr(registry, method_name, None)):
                raise TypeError(
                    "platform source evidence registry lacks " + method_name
                )
        self._platform_source_evidence_registry = registry

    def for_owner(self, owner: str) -> "RealRefResolver":
        """Return the same read-only resolver bound to one stable owner id."""

        return RealRefResolver(
            research_graph_store=self._research_graph_store,
            lifecycle_registry=self._lifecycle_registry,
            governance_registry=self._governance_registry,
            rag_index=self._rag_index,
            spine_chain_registry=self._spine_chain_registry,
            compiler_store=self._compiler_store,
            document_store=self._document_store,
            rdp_store=self._rdp_store,
            market_data_registry=self._market_data_registry,
            dataset_registry=self._dataset_registry,
            onboarding_registry=self._onboarding_registry,
            llm_service_owner_user_id=self._llm_service_owner_user_id,
            llm_call_record_store=self._llm_call_record_store,
            account_halt_barrier=self._account_halt_barrier,
            goal_validation_receipt_registry=self._goal_validation_receipt_registry,
            goal_full_product_attestation_registry=(
                self._goal_full_product_attestation_registry
            ),
            platform_source_evidence_registry=(
                self._platform_source_evidence_registry
            ),
            lifecycle_loaders=self._lifecycle_loaders,
            owner=owner,
        )

    def with_compiler_artifact_candidate(self, artifact: Any) -> "RealRefResolver":
        """Return a read-only resolver overlay for zero-write artifact checks."""

        if self._compiler_store is None:
            raise TypeError("compiler artifact candidate requires a compiler store")
        artifact_ref = str(getattr(artifact, "artifact_ref", "") or "").strip()
        artifact_owner = str(getattr(artifact, "owner", "") or "").strip()
        if not artifact_ref or not artifact_owner:
            raise ValueError("compiler artifact candidate requires exact ref and owner")

        def candidate_lifecycle_loader(ref: str, owner: str) -> Any:
            if ref == artifact_ref and owner == artifact_owner:
                return artifact
            raise LookupError("compiler artifact candidate lifecycle ref mismatch")

        return RealRefResolver(
            research_graph_store=self._research_graph_store,
            lifecycle_registry=self._lifecycle_registry,
            governance_registry=self._governance_registry,
            rag_index=self._rag_index,
            spine_chain_registry=self._spine_chain_registry,
            compiler_store=_CompilerArtifactCandidateStore(
                self._compiler_store,
                artifact,
            ),
            document_store=self._document_store,
            rdp_store=self._rdp_store,
            market_data_registry=self._market_data_registry,
            dataset_registry=self._dataset_registry,
            onboarding_registry=self._onboarding_registry,
            llm_service_owner_user_id=self._llm_service_owner_user_id,
            llm_call_record_store=self._llm_call_record_store,
            account_halt_barrier=self._account_halt_barrier,
            goal_validation_receipt_registry=(
                self._goal_validation_receipt_registry
            ),
            goal_full_product_attestation_registry=(
                self._goal_full_product_attestation_registry
            ),
            platform_source_evidence_registry=(
                _CompilerArtifactCandidateEvidenceRegistry(
                    self._platform_source_evidence_registry,
                    artifact,
                )
                if self._platform_source_evidence_registry is not None
                else None
            ),
            lifecycle_loaders=(
                candidate_lifecycle_loader,
                *self._lifecycle_loaders,
            ),
            owner=self._owner,
        )

    def has_qro(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        try:
            qro = self._research_graph_store.qro(ref)
            return self._owner is not None and str(getattr(qro, "owner", "")) == self._owner
        except (KeyError, LookupError):
            return False

    def has_research_graph_command(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref or self._owner is None:
            return False
        matches = tuple(
            command
            for command in self._research_graph_store.commands()
            if getattr(command, "command_id", None) == ref
        )
        if len(matches) != 1:
            return False
        command = matches[0]
        return self._research_graph_command_matches_owner(
            command
        ) and is_exact_current_research_graph_command(
            self._research_graph_store,
            command,
            owner_user_id=self._owner,
        )

    def _research_graph_command_matches_owner(self, command: Any) -> bool:
        if self._owner is None:
            return False
        if str(getattr(command, "actor", "") or "") == self._owner:
            return True
        payload = getattr(command, "payload", None)
        qro = payload.get("qro") if isinstance(payload, dict) else None
        inputs = getattr(qro, "input_contract", None)
        if (
            qro is None
            or str(getattr(qro, "owner", "") or "") != self._owner
            or not isinstance(inputs, dict)
            or str(inputs.get("delegated_actor") or "")
            != str(getattr(command, "actor", "") or "")
            or not str(inputs.get("delegated_actor_authority_ref") or "")
            or not str(inputs.get("delegated_actor_authority_hash") or "")
            or self._goal_validation_receipt_registry is None
        ):
            return False
        command_id = str(getattr(command, "command_id", "") or "")
        qro_id = str(getattr(qro, "qro_id", "") or "")
        try:
            receipts = self._goal_validation_receipt_registry.receipts(
                owner_user_id=self._owner,
            )
        except (KeyError, LookupError, TypeError, ValueError):
            return False
        for receipt in receipts:
            if (
                tuple(getattr(receipt, "subject_qro_refs", ()) or ()) != (qro_id,)
                or tuple(getattr(receipt, "graph_command_refs", ()) or ())
                != (command_id,)
                or "runtime_validator:current_qro_graph_delegated_authority_v1"
                not in set(getattr(receipt, "validator_identifiers", ()) or ())
            ):
                continue
            decision = self._goal_validation_receipt_registry.validate_validation_ref(
                receipt.validation_ref,
                owner_user_id=self._owner,
                subject_qro_refs=(qro_id,),
                graph_command_refs=(command_id,),
            )
            if decision.accepted:
                return True
        return False

    def has_lifecycle_record(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref or self._owner is None:
            return False
        matches: list[Any] = []
        for getter_name in ("ingestion_skill_update", "governed_asset"):
            getter = getattr(self._lifecycle_registry, getter_name, None)
            if not callable(getter):
                continue
            try:
                matches.append(getter(ref, owner_user_id=self._owner))
            except (KeyError, LookupError):
                continue
            except (OSError, TypeError, ValueError):
                return False
        for loader in self._lifecycle_loaders:
            try:
                value = loader(ref, self._owner)
            except (KeyError, LookupError):
                continue
            except (OSError, TypeError, ValueError):
                return False
            if value is not None:
                matches.append(value)
        if len(matches) != 1:
            return False
        record = matches[0]
        owner_values = tuple(
            str(getattr(record, field, "") or "")
            for field in ("owner_user_id", "owner", "recorded_by")
            if str(getattr(record, field, "") or "")
        )
        return bool(owner_values) and set(owner_values) == {self._owner}

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
                if self._owner is None:
                    return False
                record = getter(ref, owner_user_id=self._owner)
                record_owner = str(
                    getattr(
                        record,
                        "owner_user_id",
                        getattr(record, "owner", ""),
                    )
                    or ""
                )
                return record_owner == self._owner
            except (KeyError, LookupError, TypeError):
                continue
        return False

    def has_rag_asset(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        if self._owner is None:
            return False
        try:
            document = self._rag_index.document_for_owner(
                ref,
                owner_user_id=self._owner,
                require_current=True,
            )
        except (KeyError, LookupError, TypeError, ValueError):
            return False
        permission = getattr(document, "permission", None)
        return self._owner in tuple(getattr(permission, "allowed_users", ()) or ())

    def has_math_spine_chain(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        if self._owner is None:
            return False
        try:
            self._spine_chain_registry.verified_chain(ref, owner=self._owner)
            return True
        except (KeyError, LookupError, ValueError):
            return False

    def has_math_spine_member(self, chain_ref: str, member_type: str, ref: str) -> bool:
        chain_ref = str(chain_ref or "")
        ref = str(ref or "")
        if not chain_ref or not ref or self._owner is None:
            return False
        try:
            chain = self._spine_chain_registry.verified_chain(
                chain_ref,
                owner=self._owner,
            )
            owner = self._owner
            closure = self._spine_chain_registry.verified_chain_record_refs(
                chain_ref,
                owner=owner,
            )
        except (KeyError, LookupError, ValueError):
            return False
        field_by_type = {
            "theory_implementation_binding_ref": "theory_binding_refs",
            "consistency_check_ref": "consistency_check_refs",
        }
        field_name = field_by_type.get(str(member_type or ""))
        if field_name is None:
            return False
        return ref in tuple(getattr(closure, field_name, ()) or ())

    def has_compiler_ir(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref or self._compiler_store is None:
            return False
        try:
            if self._owner is None:
                return False
            self._compiler_store.canonical_ir(ref, owner=self._owner)
            return True
        except (KeyError, LookupError, ValueError):
            return False

    def has_compiler_pass(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref or self._compiler_store is None:
            return False
        try:
            if self._owner is None:
                return False
            self._compiler_store.canonical_compiler_pass(
                ref,
                owner=self._owner,
            )
            return True
        except (KeyError, LookupError, ValueError):
            return False

    def has_evidence(self, ref: str) -> bool:
        """Resolve evidence through an independent owner-scoped evidence store.

        A compiler IR/pass merely *carries* evidence refs and is therefore not
        an evidence authority.  Accepting compiler containment here would let
        the record under validation certify its own arbitrary labels.
        """

        ref = str(ref or "")
        if not ref or self._owner is None or is_placeholder_ref(ref):
            return False
        if self._document_store is not None:
            try:
                span = self._document_store.span(ref)
                if (
                    str(getattr(span, "owner", "") or "") == self._owner
                    and bool(getattr(span, "verified", False))
                    and bool(
                        str(
                            getattr(
                                span,
                                "span_support_verification_ref",
                                "",
                            )
                            or ""
                        ).strip()
                    )
                ):
                    return True
            except Exception:  # noqa: BLE001 - evidence lookup fails closed.
                pass

        platform_registry = self._platform_source_evidence_registry
        if platform_registry is not None:
            try:
                evidence = platform_registry.evidence(
                    ref,
                    owner_user_id=self._owner,
                )
                decision = platform_registry.validate_current(
                    evidence,
                    owner_user_id=self._owner,
                )
            except Exception:  # noqa: BLE001 - evidence resolution fails closed.
                pass
            else:
                if (
                    str(getattr(evidence, "owner_user_id", "") or "")
                    == self._owner
                    and str(getattr(evidence, "evidence_ref", "") or "") == ref
                    and str(
                        getattr(evidence, "canonical_evidence_ref", "") or ""
                    )
                    == ref
                    and bool(getattr(decision, "accepted", False))
                ):
                    return True

        attestation_registry = self._goal_full_product_attestation_registry
        if attestation_registry is None:
            return False
        try:
            attestation = attestation_registry.attestation(
                ref,
                owner_user_id=self._owner,
            )
            decision = attestation_registry.validate_current(
                attestation,
                owner_user_id=self._owner,
            )
        except Exception:  # noqa: BLE001 - evidence resolution fails closed.
            return False
        return (
            str(getattr(attestation, "owner_user_id", "") or "")
            == self._owner
            and str(getattr(attestation, "attestation_ref", "") or "") == ref
            and str(getattr(attestation, "canonical_attestation_ref", "") or "")
            == ref
            and bool(getattr(decision, "accepted", False))
        )

    def has_platform_evidence(self, record: Any, ref: str) -> bool:
        """Require independent evidence plus linkage to the row's compiler lineage."""

        ref = str(ref or "")
        qro_ref = str(getattr(record, "qro_ref", "") or "")
        if (
            not ref
            or not qro_ref
            or self._owner is None
            or not self.has_evidence(ref)
        ):
            return False

        registry = self._platform_source_evidence_registry
        if registry is not None:
            try:
                registry.evidence(
                    ref,
                    owner_user_id=self._owner,
                )
                decision = registry.validate_platform_ref(
                    ref,
                    owner_user_id=self._owner,
                    record=record,
                )
            except Exception:  # noqa: BLE001 - platform proof fails closed.
                return False
            else:
                if not bool(getattr(decision, "accepted", False)):
                    return False

        if self._compiler_store is None:
            return False
        try:
            records = self._compiler_store.canonical_records(owner=self._owner)
            for ir in records.irs:
                if (
                    qro_ref in tuple(getattr(ir, "source_qro_refs", ()) or ())
                    and ref in tuple(getattr(ir, "evidence_refs", ()) or ())
                ):
                    return True
            for compiler_pass in records.passes:
                if (
                    qro_ref in tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
                    and ref in tuple(getattr(compiler_pass, "evidence_refs", ()) or ())
                ):
                    return True
        except Exception:  # noqa: BLE001 - platform proof fails closed.
            return False
        return False

    def _owner_qro_output_ref(
        self,
        field_name: str,
        ref: str,
        *,
        expected_qro_type: str,
        record: Any,
    ) -> bool:
        if self._research_graph_store is None or self._owner is None:
            return False
        try:
            commands = self._research_graph_store.commands()
        except Exception:  # noqa: BLE001 - resolver callers fail closed.
            return False
        for command in commands:
            if str(getattr(command, "command_id", "") or "") != str(
                getattr(record, "research_graph_ref", "") or ""
            ):
                continue
            payload = getattr(command, "payload", None)
            qro = payload.get("qro") if isinstance(payload, dict) else None
            if qro is None:
                continue
            owner = str(getattr(qro, "owner", "") or "")
            actor = str(getattr(command, "actor", "") or "")
            if owner != self._owner or actor != self._owner:
                continue
            if str(getattr(qro, "qro_id", "") or "") != str(
                getattr(record, "qro_ref", "") or ""
            ):
                continue
            qro_type = str(getattr(getattr(qro, "qro_type", ""), "value", getattr(qro, "qro_type", "")) or "")
            if qro_type != expected_qro_type:
                continue
            output = getattr(qro, "output_contract", None)
            if isinstance(output, dict) and str(output.get(field_name) or "") == ref:
                return True
        return False

    @staticmethod
    def _platform_row(record: Any) -> str:
        value = getattr(record, "m_row", "")
        return str(getattr(value, "value", value) or "")

    def has_platform_common_ref(
        self,
        field: str,
        ref: str,
        record: Any,
    ) -> bool | None:
        """Resolve row-specific meanings for otherwise generic common refs.

        ``None`` delegates to the generic resolver. A boolean is an explicit
        row-aware decision and must never be widened by generic fallback.
        """

        row = self._platform_row(record)
        known_rows = {
            "M1-M2",
            "M3",
            "M4-M5",
            "M6",
            "M7-M8",
            "M9",
            "M10",
            "M11",
            "M12",
            "M13",
            "M14",
            "M15",
            "M16",
            "M17",
            "M18",
            "M19",
            "M20",
            "M21",
        }
        if row != "M3":
            # Real platform rows must opt into a row-specific common-ref
            # contract. Generic existence is not semantic backing.
            return False if row in known_rows else None
        field = str(field or "")
        ref = str(ref or "")
        if not ref or self._owner is None:
            return False
        if field == "qro_ref":
            try:
                qro = self._research_graph_store.qro(ref)
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            qro_type = str(
                getattr(
                    getattr(qro, "qro_type", ""),
                    "value",
                    getattr(qro, "qro_type", ""),
                )
                or ""
            )
            return str(getattr(qro, "owner", "") or "") == self._owner and qro_type == "Dataset"
        if field == "research_graph_ref":
            return self.has_research_graph_command(ref)
        if field == "lifecycle_ref":
            return self.has_lifecycle_record(ref)
        if field == "governance_ref":
            if self._market_data_registry is None:
                return False
            try:
                validation = self._market_data_registry.use_validation(
                    ref,
                    owner_user_id=self._owner,
                )
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            return str(getattr(validation, "recorded_by", "") or "") == self._owner
        if field == "rag_ref":
            return self.has_rag_asset(ref)
        if field == "math_spine_ref":
            return self.has_math_spine_chain(ref)
        return False

    def _m3_linkage_violations(
        self,
        record: Any,
        *,
        command: Any,
        command_qro: Any,
    ) -> tuple[tuple[str, str, str], ...]:
        violations: list[tuple[str, str, str]] = []

        def add(field: str, ref: Any, reason: str) -> None:
            violations.append((field, str(ref or ""), reason))

        owner = self._owner
        if owner is None:
            add("qro_ref", getattr(record, "qro_ref", ""), "owner-bound resolver is required")
            return tuple(violations)
        if any(
            store is None
            for store in (
                self._research_graph_store,
                self._lifecycle_registry,
                self._market_data_registry,
                self._onboarding_registry,
                self._dataset_registry,
                self._rag_index,
                self._spine_chain_registry,
            )
        ):
            add("m_row", "M3", "M3 resolver dependency is unavailable")
            return tuple(violations)

        specific = {
            str(getattr(item, "key", "") or ""): str(getattr(item, "ref", "") or "")
            for item in tuple(getattr(record, "specific_refs", ()) or ())
        }
        skill_ref = specific.get("ingestion_skill_ref", "")
        instrument_ref = specific.get("instrument_spec_ref", "")
        try:
            stored_qro = self._research_graph_store.qro(str(record.qro_ref or ""))
            skill = self._onboarding_registry.ingestion_skill(
                skill_ref,
                owner_user_id=owner,
            )
            source = self._onboarding_registry.data_source(
                skill.source_ref,
                owner_user_id=owner,
            )
            update = self._lifecycle_registry.ingestion_skill_update(
                str(record.lifecycle_ref or ""),
                owner_user_id=owner,
            )
            instrument = self._market_data_registry.instrument(
                instrument_ref,
                owner_user_id=owner,
            )
            validation = self._market_data_registry.use_validation(
                str(record.governance_ref or ""),
                owner_user_id=owner,
            )
        except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError) as exc:
            add("m_row", "M3", f"M3 coherent bundle lookup failed: {exc}")
            return tuple(violations)

        input_contract = getattr(stored_qro, "input_contract", None)
        output_contract = getattr(stored_qro, "output_contract", None)
        if not isinstance(input_contract, dict) or not isinstance(output_contract, dict):
            add("qro_ref", record.qro_ref, "M3 Dataset QRO contracts are malformed")
            return tuple(violations)
        dataset_ref = str(output_contract.get("dataset_ref") or "")
        try:
            dataset = self._market_data_registry.dataset(
                dataset_ref,
                owner_user_id=owner,
            )
            pit_rule = self._onboarding_registry.data_connector_pit_bitemporal_rule(
                str(dataset.pit_bitemporal_rules_ref or ""),
                owner_user_id=owner,
            )
            capability = self._market_data_registry.capability_matrix(
                str(validation.capability_matrix_ref or ""),
                owner_user_id=owner,
            )
            resolve_version = getattr(self._dataset_registry, "resolve_version_ref", None)
            if not callable(resolve_version):
                raise LookupError("DatasetRegistry exact-ref resolver is unavailable")
            version = resolve_version(str(update.dataset_version_ref or ""))
            chain = self._spine_chain_registry.verified_chain(
                str(record.math_spine_ref or ""),
                owner=owner,
            )
        except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError) as exc:
            add("m_row", "M3", f"M3 derived bundle lookup failed: {exc}")
            return tuple(violations)

        qro_type = str(
            getattr(
                getattr(stored_qro, "qro_type", ""),
                "value",
                getattr(stored_qro, "qro_type", ""),
            )
            or ""
        )
        if qro_type != "Dataset":
            add("qro_ref", record.qro_ref, "M3 primary QRO must be Dataset")
        if str(getattr(command, "command_type", "") or "") != "upsert_qro":
            add("research_graph_ref", record.research_graph_ref, "M3 graph command must be upsert_qro")
        if command_qro != stored_qro:
            add("research_graph_ref", record.research_graph_ref, "M3 graph command payload is stale or differs from the persisted QRO")

        expected_input = {
            "dataset_ref": dataset.dataset_ref,
            "source_ref": dataset.source_ref,
            "version": dataset.version,
            "record_hash": content_hash(dataset.to_dict()),
        }
        for key, expected in expected_input.items():
            if str(input_contract.get(key) or "") != str(expected or ""):
                add("qro_ref", record.qro_ref, f"M3 Dataset QRO input {key} mismatch")
        expected_output = {
            "status": "dataset_semantics_recorded",
            "dataset_ref": dataset.dataset_ref,
            "known_at_ref": dataset.known_at_ref,
            "effective_at_ref": dataset.effective_at_ref,
            "pit_bitemporal_rules_ref": dataset.pit_bitemporal_rules_ref,
            "quality_status": dataset.quality_status,
            "freshness_status": dataset.freshness_status,
        }
        for key, expected in expected_output.items():
            if str(output_contract.get(key) or "") != str(expected or ""):
                add("qro_ref", record.qro_ref, f"M3 Dataset QRO output {key} mismatch")
        if str(getattr(stored_qro, "implementation_hash", "") or "") != (
            "market_data_dataset:" + content_hash(dataset.to_dict())
        ):
            add("qro_ref", record.qro_ref, "M3 Dataset QRO implementation hash mismatch")

        for field, actual, expected in (
            ("specific_refs.ingestion_skill_ref", skill.skill_id, skill_ref),
            ("lifecycle_ref", update.update_ref, str(record.lifecycle_ref or "")),
            ("lifecycle_ref", update.skill_ref, skill.skill_id),
            ("lifecycle_ref", update.skill_version, skill.version),
            ("lifecycle_ref", update.source_ref, skill.source_ref),
            ("dataset_ref", dataset.source_ref, skill.source_ref),
            ("dataset_ref", dataset.version, version.version_id),
            ("dataset_ref", dataset.checksum, version.sha256),
            ("dataset_ref", dataset.known_at_ref, update.known_at_ref),
            ("dataset_ref", dataset.effective_at_ref, update.effective_at_ref),
            ("dataset_ref", dataset.pit_bitemporal_rules_ref, skill.pit_bitemporal_rules_ref),
            ("pit_bitemporal_rules_ref", pit_rule.skill_id, skill.skill_id),
            ("pit_bitemporal_rules_ref", pit_rule.source_ref, skill.source_ref),
            ("specific_refs.instrument_spec_ref", instrument.instrument_ref, instrument_ref),
            ("specific_refs.instrument_spec_ref", instrument.symbol_mapping_ref, skill.schema_mapping_ref),
            ("governance_ref", validation.validation_ref, str(record.governance_ref or "")),
            ("governance_ref", capability.matrix_ref, validation.capability_matrix_ref),
            ("governance_ref", validation.recorded_by, owner),
            ("governance_ref", capability.asset_class, instrument.asset_class),
            ("governance_ref", capability.instrument_type, instrument.instrument_type),
            ("governance_ref", capability.data_availability, dataset.dataset_ref),
            ("math_spine_ref", chain.data_semantics_ref, dataset.dataset_ref),
        ):
            if str(actual or "") != str(expected or ""):
                add(field, actual, f"M3 coherent bundle mismatch; expected {expected!r}")
        if str(getattr(skill, "owner", "") or "") != owner:
            add("specific_refs.ingestion_skill_ref", skill.skill_id, "M3 ingestion skill owner mismatch")
        if str(getattr(update, "recorded_by", "") or "") != owner:
            add("lifecycle_ref", update.update_ref, "M3 lifecycle update owner mismatch")
        if str(getattr(pit_rule, "recorded_by", "") or "") != owner:
            add("pit_bitemporal_rules_ref", pit_rule.rule_ref, "M3 PIT rule owner mismatch")
        if str(getattr(source, "source_ref", "") or "") != str(skill.source_ref or ""):
            add("specific_refs.ingestion_skill_ref", skill.skill_id, "M3 DataSource binding mismatch")

        metadata = dict(getattr(version, "metadata", {}) or {})
        for key, actual, expected in (
            ("dataset_id", version.dataset_id, skill.output_dataset_id),
            ("ingestion_skill_id", metadata.get("ingestion_skill_id"), skill.skill_id),
            ("ingestion_skill_version", metadata.get("ingestion_skill_version"), skill.version),
            ("source_ref", metadata.get("source_ref"), skill.source_ref),
            ("pit_bitemporal_rules_ref", metadata.get("pit_bitemporal_rules_ref"), skill.pit_bitemporal_rules_ref),
            ("update_checksum", update.checksum, version.sha256),
            ("update_row_count", update.row_count, version.row_count),
        ):
            if actual != expected:
                add("lifecycle_ref", update.update_ref, f"M3 DatasetVersion {key} mismatch")

        lineage_refs = {str(ref) for ref in tuple(dataset.lineage_refs or ())}
        required_lineage = {
            str(ref)
            for ref in (
                update.update_ref,
                update.lineage_ref,
                pit_rule.rule_ref,
                pit_rule.field_mapping_ref,
                pit_rule.schema_probe_ref,
            )
            if str(ref or "")
        }
        if not required_lineage.issubset(lineage_refs):
            add("dataset_ref", dataset.dataset_ref, "M3 DatasetSemantics lineage is incomplete")

        if tuple(validation.dataset_refs) != (dataset.dataset_ref,):
            add("governance_ref", validation.validation_ref, "M3 use validation must bind exactly one DatasetSemantics ref")
        if tuple(validation.instrument_refs) != (instrument.instrument_ref,):
            add("governance_ref", validation.validation_ref, "M3 use validation must bind exactly one InstrumentSpec ref")
        if not bool(validation.accepted) or tuple(validation.violation_codes):
            add("governance_ref", validation.validation_ref, "M3 use validation is not accepted and clean")
        if validation.capital_record_ref or tuple(validation.transformation_refs):
            add("governance_ref", validation.validation_ref, "M3 capital/transformation refs lack durable exact getters")
        recomputed = validate_market_data_use(
            MarketDataUseRequest(
                request_ref=validation.request_ref,
                use_context=validation.use_context,
                datasets=(dataset,),
                instruments=(instrument,),
                capability_matrix=capability,
            )
        )
        if not recomputed.accepted:
            add("governance_ref", validation.validation_ref, "M3 use validation fails canonical recomputation")

        try:
            rag_document = self._rag_index.document_for_owner(
                str(record.rag_ref or ""),
                owner_user_id=owner,
                require_current=True,
            )
        except (KeyError, LookupError, TypeError, ValueError):
            rag_document = None
        if rag_document is None:
            add("rag_ref", record.rag_ref, "M3 RAG document is not persisted")
        else:
            permission = getattr(rag_document, "permission", None)
            if owner not in tuple(getattr(permission, "allowed_users", ()) or ()):
                add("rag_ref", record.rag_ref, "M3 RAG document owner permission mismatch")
            if str(getattr(rag_document, "asset_ref", "") or "") != dataset.dataset_ref:
                add("rag_ref", record.rag_ref, "M3 RAG asset_ref must equal DatasetSemantics ref")
            if dataset.dataset_ref not in tuple(getattr(permission, "allowed_assets", ()) or ()):
                add("rag_ref", record.rag_ref, "M3 RAG permission must bind the DatasetSemantics asset")
            rag_metadata = dict(getattr(rag_document, "metadata", {}) or {})
            expected_rag = {
                "m_row": "M3",
                "qro_ref": str(record.qro_ref or ""),
                "research_graph_ref": str(record.research_graph_ref or ""),
                "ingestion_skill_ref": skill.skill_id,
                "lifecycle_ref": update.update_ref,
                "dataset_ref": dataset.dataset_ref,
                "pit_bitemporal_rules_ref": pit_rule.rule_ref,
                "instrument_spec_ref": instrument.instrument_ref,
                "governance_ref": validation.validation_ref,
                "math_spine_ref": str(record.math_spine_ref or ""),
            }
            for key, expected in expected_rag.items():
                if str(rag_metadata.get(key) or "") != str(expected or ""):
                    add("rag_ref", record.rag_ref, f"M3 RAG metadata {key} mismatch")

        return tuple(violations)

    def has_platform_specific_ref(self, key: str, ref: str, record: Any) -> bool:
        """Resolve the currently supported platform-specific typed refs."""

        key = str(key or "")
        ref = str(ref or "")
        if not key or not ref or self._owner is None:
            return False
        if key == "canonical_code_command_ref":
            if ref != str(getattr(record, "research_graph_ref", "") or ""):
                return False
            try:
                command = next(
                    item
                    for item in self._research_graph_store.commands()
                    if str(getattr(item, "command_id", "") or "") == ref
                    and str(getattr(item, "actor", "") or "") == self._owner
                )
            except (StopIteration, KeyError, LookupError, OSError, ValueError):
                return False
            payload = getattr(command, "payload", None)
            qro = payload.get("qro") if isinstance(payload, dict) else None
            input_contract = getattr(qro, "input_contract", None)
            return (
                str(getattr(command, "command_type", "") or "") == "upsert_qro"
                and str(getattr(qro, "qro_id", "") or "")
                == str(getattr(record, "qro_ref", "") or "")
                and str(getattr(qro, "owner", "") or "") == self._owner
                and bool(str(getattr(qro, "implementation_hash", "") or "").strip())
                and isinstance(input_contract, dict)
                and bool(str(input_contract.get("code_hash") or "").strip())
            )
        if key == "typed_canvas_projection_ref":
            try:
                return any(
                    str(getattr(projection, "projection_ref", "") or "") == ref
                    and str(getattr(projection, "qro_id", "") or "")
                    == str(getattr(record, "qro_ref", "") or "")
                    and str(getattr(projection, "command_id", "") or "")
                    == str(getattr(record, "research_graph_ref", "") or "")
                    and str(getattr(projection, "owner", "") or "") == self._owner
                    for projection in self._research_graph_store.projection_index(owner=self._owner)
                )
            except Exception:  # noqa: BLE001
                return False
        if key == "instrument_spec_ref":
            if self._market_data_registry is None or not ref.startswith(
                ("instrument:", "instrument_spec:")
            ):
                return False
            try:
                instrument = self._market_data_registry.instrument(
                    ref,
                    owner_user_id=self._owner,
                )
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            return str(getattr(instrument, "instrument_ref", "") or "") == ref
        if key == "market_capability_matrix_ref":
            if self._market_data_registry is None or not ref.startswith(
                ("market_capability_matrix:", "capability:")
            ):
                return False
            try:
                matrix = self._market_data_registry.capability_matrix(
                    ref,
                    owner_user_id=self._owner,
                )
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            return str(getattr(matrix, "matrix_ref", "") or "") == ref
        if key == "ingestion_skill_ref":
            if self._onboarding_registry is None:
                return False
            try:
                skill = self._onboarding_registry.ingestion_skill(
                    ref,
                    owner_user_id=self._owner,
                )
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            return (
                str(getattr(skill, "skill_id", "") or "") == ref
                and str(getattr(skill, "owner", "") or "") == self._owner
            )
        if key in {"mock_label_ref", "asset_category_ref"}:
            if self._lifecycle_registry is None:
                return False
            getter_name, identity_field = {
                "mock_label_ref": (
                    "governed_asset_by_mock_label_ref",
                    "mock_label_ref",
                ),
                "asset_category_ref": (
                    "governed_asset_by_category_ref",
                    "asset_category_ref",
                ),
            }[key]
            try:
                asset = getattr(self._lifecycle_registry, getter_name)(
                    ref,
                    owner_user_id=self._owner,
                )
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            category = str(getattr(getattr(asset, "category", ""), "value", getattr(asset, "category", "")) or "")
            if not (
                str(getattr(asset, identity_field, "") or "") == ref
                and category in {"demo", "template", "example", "tutorial"}
            ):
                return False
            if self._platform_row(record) == "M21":
                specific = {
                    str(getattr(item, "key", "") or ""): str(
                        getattr(item, "ref", "") or ""
                    )
                    for item in tuple(getattr(record, "specific_refs", ()) or ())
                }
                other_key = (
                    "asset_category_ref"
                    if key == "mock_label_ref"
                    else "mock_label_ref"
                )
                other_ref = specific.get(other_key, "")
                other_getter, _other_identity = {
                    "mock_label_ref": (
                        "governed_asset_by_mock_label_ref",
                        "mock_label_ref",
                    ),
                    "asset_category_ref": (
                        "governed_asset_by_category_ref",
                        "asset_category_ref",
                    ),
                }[other_key]
                try:
                    other_asset = getattr(self._lifecycle_registry, other_getter)(
                        other_ref,
                        owner_user_id=self._owner,
                    )
                except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                    return False
                if str(getattr(other_asset, "asset_ref", "") or "") != str(
                    getattr(asset, "asset_ref", "") or ""
                ):
                    return False
            return True
        if key in {"model_routing_policy_ref", "credential_pool_ref", "secret_ref"}:
            if self._onboarding_registry is None or self._llm_service_owner_user_id is None:
                return False
            getter_name, identity_field = {
                "model_routing_policy_ref": ("routing_policy", "routing_policy_id"),
                "credential_pool_ref": ("credential_pool", "pool_id"),
                "secret_ref": ("secret_ref", "secret_ref"),
            }[key]
            try:
                stored = getattr(self._onboarding_registry, getter_name)(
                    ref,
                    owner_user_id=self._llm_service_owner_user_id,
                )
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            if str(getattr(stored, identity_field, "") or "") != ref:
                return False
            if key == "credential_pool_ref":
                return (
                    str(getattr(stored, "owner", "") or "")
                    == self._llm_service_owner_user_id
                )
            return True
        if key == "llm_gateway_ref":
            if self._llm_call_record_store is None or not ref.startswith("llm_gateway:"):
                return False
            call_id = ref.removeprefix("llm_gateway:")
            if not call_id:
                return False
            try:
                records = self._llm_call_record_store.read_all(owner_user_id=self._owner)
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            return any(
                str(getattr(record, "call_id", "") or "") == call_id
                and str(getattr(record, "record_kind", "") or "") == "terminal"
                for record in records
            )
        if key == "kill_switch_ref":
            if self._account_halt_barrier is None or not ref.startswith(
                ("kill_switch:", "account_halt_")
            ):
                return False
            try:
                evidence = self._account_halt_barrier.halt_evidence(
                    ref,
                    owner_user_id=self._owner,
                )
            except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                return False
            return (
                str(getattr(evidence, "halt_ref", "") or "") == ref
                and str(getattr(evidence, "owner_user_id", "") or "") == self._owner
                and str(getattr(evidence, "owner_state", "") or "") == "halted"
                and bool(tuple(getattr(evidence, "account_binding_refs", ()) or ()))
                and len(tuple(getattr(evidence, "flat_proof_refs", ()) or ()))
                == len(tuple(getattr(evidence, "account_binding_refs", ()) or ()))
                and all(
                    str(proof_ref or "").strip()
                    for proof_ref in tuple(getattr(evidence, "flat_proof_refs", ()) or ())
                )
            )
        if key in {
            "execution_boundary_ref",
            "model_passport_ref",
            "validation_dossier_ref",
            "signal_contract_ref",
            "strategy_book_ref",
        }:
            expected_type = {
                "execution_boundary_ref": "ExecutionPolicy",
                "model_passport_ref": "Model",
                "validation_dossier_ref": "ValidationDossier",
                "signal_contract_ref": "Signal",
                "strategy_book_ref": "StrategyBook",
            }[key]
            row = self._platform_row(record)
            if row == "M6" and key in {"model_passport_ref", "validation_dossier_ref"}:
                expected_type = "Model"
            elif row == "M7-M8" and key in {"signal_contract_ref", "strategy_book_ref"}:
                expected_type = "StrategyBook"
            elif row == "M9" and key in {
                "execution_boundary_ref",
                "market_capability_matrix_ref",
            }:
                expected_type = "ExecutionPolicy"
            if key == "model_passport_ref":
                if self._governance_registry is None:
                    return False
                try:
                    passport = self._governance_registry.passport(
                        ref,
                        owner_user_id=self._owner,
                    )
                except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                    return False
                if str(getattr(passport, "passport_id", "") or "") != ref:
                    return False
            return self._owner_qro_output_ref(
                key,
                ref,
                expected_qro_type=expected_type,
                record=record,
            )
        # Remaining platform-specific producers do not yet expose stable,
        # owner-scoped getters through this resolver and therefore stay unavailable.
        return False

    def platform_linkage_violations(self, record: Any) -> tuple[tuple[str, str, str], ...]:
        """Prove the row's graph command actually produced its owner-scoped QRO."""

        qro_ref = str(getattr(record, "qro_ref", "") or "")
        command_ref = str(getattr(record, "research_graph_ref", "") or "")
        if self._owner is None:
            return (("qro_ref", qro_ref, "owner-bound resolver is required"),)
        command = next(
            (
                item
                for item in self._research_graph_store.commands()
                if str(getattr(item, "command_id", "") or "") == command_ref
                and str(getattr(item, "actor", "") or "") == self._owner
            ),
            None,
        )
        if command is None:
            return (("research_graph_ref", command_ref, "owner-scoped graph command is not persisted"),)
        payload = getattr(command, "payload", None)
        qro = payload.get("qro") if isinstance(payload, dict) else None
        produced_qro_ref = str(getattr(qro, "qro_id", "") or "")
        if produced_qro_ref != qro_ref:
            return (("qro_ref", qro_ref, "graph command does not produce the declared QRO"),)
        if str(getattr(qro, "owner", "") or "") != self._owner:
            return (("qro_ref", qro_ref, "graph command QRO owner mismatch"),)
        if self._platform_row(record) == "M3":
            return self._m3_linkage_violations(
                record,
                command=command,
                command_qro=qro,
            )
        return ()

    def has_rdp(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref or self._rdp_store is None or self._owner is None:
            return False
        try:
            self._rdp_store.manifest(ref, owner_user_id=self._owner)
            return True
        except (KeyError, LookupError):
            return False

    def entrypoint_linkage_violations(self, record: Any) -> tuple[tuple[str, str, str], ...]:
        """Validate that coverage refs form one coherent persisted compiler lineage.

        Independent existence checks are insufficient: the same real objects
        could otherwise be recombined or relabelled as a different entry source.
        This method is read-only and returns structured failures to the caller.
        """

        violations: list[tuple[str, str, str]] = []

        def add(field: str, ref: object, reason: str) -> None:
            violations.append((field, str(ref or ""), reason))

        def enum_text(value: object) -> str:
            return str(getattr(value, "value", value) or "")

        if self._compiler_store is None:
            add("compiler_ir_refs", "", "compiler store is unavailable")
            return tuple(violations)

        irs: list[Any] = []
        if self._owner is None:
            add("recorded_by", "", "owner-bound resolver is required")
            return tuple(violations)
        if str(getattr(record, "recorded_by", "") or "") != self._owner:
            add("recorded_by", getattr(record, "recorded_by", ""), "coverage owner mismatch")
            return tuple(violations)
        for ref in tuple(getattr(record, "compiler_ir_refs", ()) or ()):
            try:
                irs.append(
                    self._compiler_store.canonical_ir(
                        ref,
                        owner=self._owner,
                    )
                )
            except (KeyError, LookupError, ValueError):
                add(
                    "compiler_ir_refs",
                    ref,
                    "compiler IR is not a canonical current proof head",
                )
        passes: list[Any] = []
        for ref in tuple(getattr(record, "compiler_pass_refs", ()) or ()):
            try:
                passes.append(
                    self._compiler_store.canonical_compiler_pass(
                        ref,
                        owner=self._owner,
                    )
                )
            except (KeyError, LookupError, ValueError):
                add(
                    "compiler_pass_refs",
                    ref,
                    "compiler pass is not a canonical current proof head",
                )
        if not irs or not passes:
            return tuple(violations)

        actual_irs = set(str(ref) for ref in tuple(getattr(record, "compiler_ir_refs", ()) or ()))
        pass_outputs = {str(getattr(item, "output_ir_ref", "") or "") for item in passes}
        if actual_irs != pass_outputs:
            add("compiler_pass_refs", ",".join(sorted(pass_outputs)), "coverage IR refs must equal compiler pass outputs")

        expected_qros = {
            str(ref)
            for item in (*irs, *passes)
            for ref in (
                tuple(getattr(item, "source_qro_refs", ()) or ())
                if hasattr(item, "source_qro_refs")
                else tuple(getattr(item, "input_qro_refs", ()) or ())
            )
        }
        actual_qros = {str(ref) for ref in tuple(getattr(record, "qro_refs", ()) or ())}
        if actual_qros != expected_qros:
            add("qro_refs", ",".join(sorted(actual_qros)), "coverage QRO refs must equal the IR/pass QRO lineage")

        expected_graph = {
            str(ref)
            for item in (*irs, *passes)
            for ref in tuple(getattr(item, "graph_command_refs", ()) or ())
        }
        actual_graph = {
            str(ref) for ref in tuple(getattr(record, "research_graph_command_refs", ()) or ())
        }
        if actual_graph != expected_graph:
            add(
                "research_graph_command_refs",
                ",".join(sorted(actual_graph)),
                "coverage graph refs must equal the IR/pass graph lineage",
            )

        validation_refs = tuple(
            str(ref)
            for ref in tuple(getattr(record, "validation_refs", ()) or ())
        )
        receipt_refs = tuple(
            ref
            for ref in validation_refs
            if ref.startswith("goal_validation_receipt:")
        )
        domain_validation_refs = tuple(
            ref
            for ref in validation_refs
            if not ref.startswith("goal_validation_receipt:")
        )
        if self._goal_validation_receipt_registry is None:
            add(
                "validation_refs",
                "",
                "durable GOAL validation receipt registry is unavailable",
            )
        else:
            if not receipt_refs:
                add(
                    "validation_refs",
                    "",
                    "coverage validation refs require at least one durable receipt",
                )
            trusted_domain_refs: set[str] = set()
            for validation_ref in receipt_refs:
                try:
                    decision = self._goal_validation_receipt_registry.validate_validation_ref(
                        validation_ref,
                        owner_user_id=self._owner,
                        subject_qro_refs=tuple(sorted(actual_qros)),
                        graph_command_refs=tuple(sorted(actual_graph)),
                    )
                except Exception:  # noqa: BLE001 - coverage validation fails closed.
                    add(
                        "validation_refs",
                        validation_ref,
                        "durable validation receipt lookup raised",
                    )
                    continue
                if not bool(getattr(decision, "accepted", False)):
                    codes = ",".join(
                        sorted(
                            {
                                str(getattr(item, "code", "validation_receipt_invalid"))
                                for item in tuple(getattr(decision, "violations", ()) or ())
                            }
                        )
                    )
                    add(
                        "validation_refs",
                        validation_ref,
                        "validation ref is not an exact passed durable receipt"
                        + (f": {codes}" if codes else ""),
                    )
                    continue
                try:
                    receipt = self._goal_validation_receipt_registry.receipt(
                        validation_ref,
                        owner_user_id=self._owner,
                    )
                except Exception:  # noqa: BLE001 - coverage validation fails closed.
                    add(
                        "validation_refs",
                        validation_ref,
                        "validated durable receipt could not be reloaded",
                    )
                    continue
                trusted_domain_refs.update(
                    identifier.removeprefix("domain_validation_ref:")
                    for identifier in tuple(
                        getattr(receipt, "validator_identifiers", ()) or ()
                    )
                    if str(identifier).startswith("domain_validation_ref:")
                )
            if (
                len(domain_validation_refs) != len(set(domain_validation_refs))
                or set(domain_validation_refs) != trusted_domain_refs
            ):
                add(
                    "validation_refs",
                    ",".join(sorted(domain_validation_refs)),
                    "domain validation refs must exactly equal the refs content-bound by durable receipts",
                )

        if bool(getattr(record, "claims_full_product_entrypoint", False)):
            trusted_full_product_receipt = False
            if self._goal_validation_receipt_registry is not None:
                for validation_ref in receipt_refs:
                    try:
                        receipt = self._goal_validation_receipt_registry.receipt(
                            validation_ref,
                            owner_user_id=self._owner,
                        )
                    except Exception:  # noqa: BLE001 - full-product claims fail closed.
                        continue
                    if (
                        "runtime_validator:goal_full_product_entrypoint_v1"
                        in tuple(getattr(receipt, "validator_identifiers", ()) or ())
                    ):
                        trusted_full_product_receipt = True
                        break
            if not trusted_full_product_receipt:
                add(
                    "claims_full_product_entrypoint",
                    getattr(record, "coverage_ref", ""),
                    "full-product entrypoint claims require a dedicated durable full-product validator receipt",
                )
            if (
                self._owner is None
                or self._goal_full_product_attestation_registry is None
            ):
                add(
                    "claims_full_product_entrypoint",
                    getattr(record, "coverage_ref", ""),
                    "full-product entrypoint claims require the dedicated current attestation registry",
                )
            else:
                try:
                    full_product_decision = (
                        self._goal_full_product_attestation_registry
                        .validate_full_product_coverage(
                            record,
                            owner_user_id=self._owner,
                        )
                    )
                except Exception:  # noqa: BLE001 - terminal claims fail closed.
                    add(
                        "claims_full_product_entrypoint",
                        getattr(record, "coverage_ref", ""),
                        "dedicated full-product attestation validation raised",
                    )
                else:
                    if not bool(getattr(full_product_decision, "accepted", False)):
                        codes = ",".join(
                            sorted(
                                {
                                    str(
                                        getattr(
                                            item,
                                            "code",
                                            "goal_full_product_attestation_invalid",
                                        )
                                    )
                                    for item in tuple(
                                        getattr(
                                            full_product_decision,
                                            "violations",
                                            (),
                                        )
                                        or ()
                                    )
                                }
                            )
                        )
                        add(
                            "claims_full_product_entrypoint",
                            getattr(record, "coverage_ref", ""),
                            "full-product coverage failed the dedicated current attestation validator"
                            + (f": {codes}" if codes else ""),
                        )

        for field_name, ir_field, pass_field in (
            ("evidence_refs", "evidence_refs", "evidence_refs"),
            ("validation_refs", "validation_refs", "validation_refs"),
            ("canonical_command_refs", "canonical_command_refs", "canonical_command_refs"),
        ):
            sources = [(item, ir_field) for item in irs] + [
                (item, pass_field) for item in passes
            ]
            expected = {
                str(ref)
                for item, source_field in sources
                for ref in tuple(getattr(item, source_field, ()) or ())
            }
            actual = {str(ref) for ref in tuple(getattr(record, field_name, ()) or ())}
            if actual != expected:
                add(field_name, ",".join(sorted(actual)), f"coverage {field_name} must equal the IR/pass lineage")

        entrypoint_evidence_refs = tuple(
            str(ref)
            for ref in tuple(getattr(record, "evidence_refs", ()) or ())
            if str(ref).startswith(
                ("entrypoint_evidence:", "platform_source_evidence:")
            )
        )
        if entrypoint_evidence_refs:
            entrypoint_evidence_validator = getattr(
                self._platform_source_evidence_registry,
                "validate_entrypoint_ref",
                None,
            )
            if not callable(entrypoint_evidence_validator):
                for evidence_ref in entrypoint_evidence_refs:
                    if not evidence_ref.startswith("platform_source_evidence:"):
                        add(
                            "evidence_refs",
                            evidence_ref,
                            "entrypoint evidence registry/context validator is unavailable",
                        )
                        continue
                    try:
                        source_evidence = (
                            self._platform_source_evidence_registry.evidence(
                                evidence_ref,
                                owner_user_id=self._owner,
                            )
                        )
                        source_decision = (
                            self._platform_source_evidence_registry.validate_current(
                                source_evidence,
                                owner_user_id=self._owner,
                            )
                        )
                    except Exception:  # noqa: BLE001 - evidence linkage fails closed.
                        add(
                            "evidence_refs",
                            evidence_ref,
                            "platform source evidence context validation raised",
                        )
                        continue
                    if not bool(getattr(source_decision, "accepted", False)):
                        add(
                            "evidence_refs",
                            evidence_ref,
                            "platform source evidence is not current",
                        )
                        continue
                    source_expected = (
                        (
                            str(getattr(source_evidence, "owner_user_id", "") or ""),
                            str(getattr(record, "recorded_by", "") or ""),
                        ),
                        (
                            enum_text(getattr(source_evidence, "entry_source", "")),
                            enum_text(getattr(record, "entry_source", "")),
                        ),
                        (
                            str(getattr(source_evidence, "entrypoint_ref", "") or ""),
                            str(getattr(record, "entrypoint_ref", "") or ""),
                        ),
                        (
                            (str(getattr(source_evidence, "qro_ref", "") or ""),),
                            tuple(str(ref) for ref in getattr(record, "qro_refs", ()) or ()),
                        ),
                        (
                            (
                                str(
                                    getattr(
                                        source_evidence,
                                        "research_graph_ref",
                                        "",
                                    )
                                    or ""
                                ),
                            ),
                            tuple(
                                str(ref)
                                for ref in getattr(
                                    record,
                                    "research_graph_command_refs",
                                    (),
                                )
                                or ()
                            ),
                        ),
                        (
                            (evidence_ref,),
                            tuple(
                                str(ref)
                                for ref in getattr(record, "evidence_refs", ()) or ()
                            ),
                        ),
                    )
                    governance_ref = str(
                        getattr(source_evidence, "governance_ref", "") or ""
                    )
                    source_linked = all(
                        evidence_value == record_value
                        for evidence_value, record_value in source_expected
                    ) and governance_ref in tuple(
                        str(ref)
                        for ref in getattr(record, "validation_refs", ()) or ()
                    )
                    if not source_linked:
                        add(
                            "evidence_refs",
                            evidence_ref,
                            "platform source evidence is not bound to this exact owner/entrypoint/QRO/Graph/validation context",
                        )
            else:
                for evidence_ref in entrypoint_evidence_refs:
                    try:
                        decision = entrypoint_evidence_validator(
                            evidence_ref,
                            owner_user_id=self._owner,
                            record=record,
                        )
                    except Exception:  # noqa: BLE001 - evidence linkage fails closed.
                        add(
                            "evidence_refs",
                            evidence_ref,
                            "entrypoint evidence context validation raised",
                        )
                        continue
                    if not bool(getattr(decision, "accepted", False)):
                        codes = ",".join(
                            sorted(
                                {
                                    str(
                                        getattr(
                                            item,
                                            "code",
                                            "entrypoint_evidence_invalid",
                                        )
                                    )
                                    for item in tuple(
                                        getattr(decision, "violations", ()) or ()
                                    )
                                }
                            )
                        )
                        add(
                            "evidence_refs",
                            evidence_ref,
                            "entrypoint evidence is not bound to this exact coverage/compiler context"
                            + (f": {codes}" if codes else ""),
                        )

        expected_permissions = {
            str(getattr(item, "permission_ref", "") or "")
            for item in (*irs, *passes)
            if str(getattr(item, "permission_ref", "") or "")
        }
        actual_permissions = {str(ref) for ref in tuple(getattr(record, "permission_refs", ()) or ())}
        if actual_permissions != expected_permissions:
            add("permission_refs", ",".join(sorted(actual_permissions)), "coverage permissions must equal IR/pass permissions")

        entry_source = enum_text(getattr(record, "entry_source", ""))
        for compiler_pass in passes:
            if enum_text(getattr(compiler_pass, "entry_source", "")) != entry_source:
                add("entry_source", getattr(compiler_pass, "pass_ref", ""), "compiler pass entry source does not match coverage")

        commands_by_ref = {
            str(getattr(command, "command_id", "") or ""): command
            for command in self._research_graph_store.commands()
        }
        for ref in actual_graph:
            command = commands_by_ref.get(ref)
            if command is None:
                add("research_graph_command_refs", ref, "research graph command is not persisted")
                continue
            payload = getattr(command, "payload", None)
            qro = payload.get("qro") if isinstance(payload, dict) else None
            qro_id = str(getattr(qro, "qro_id", "") or "")
            if not self._research_graph_command_matches_owner(command):
                add("research_graph_command_refs", ref, "research graph command owner mismatch")
            if not is_exact_current_research_graph_command(
                self._research_graph_store,
                command,
                owner_user_id=self._owner,
                qro_ref=qro_id,
            ):
                add(
                    "research_graph_command_refs",
                    ref,
                    "research graph command is not the exact current QRO projection head",
                )
            if enum_text(getattr(command, "source", "")) != entry_source:
                add("entry_source", ref, "research graph command source does not match coverage")
            if not qro_id:
                add("qro_refs", ref, "graph command does not carry a QRO payload")
            elif qro_id not in actual_qros:
                add("qro_refs", qro_id, "graph command QRO is outside the coverage compiler lineage")
            else:
                try:
                    current_qro = self._research_graph_store.qro(qro_id)
                except (KeyError, LookupError, OSError, PermissionError, TypeError, ValueError):
                    add("qro_refs", qro_id, "graph command QRO is not currently persisted")
                else:
                    if current_qro != qro:
                        add("qro_refs", qro_id, "graph command QRO payload is stale or differs from current store state")
                    if str(getattr(current_qro, "owner", "") or "") != self._owner:
                        add("qro_refs", qro_id, "current QRO owner mismatch")
            input_contract = getattr(qro, "input_contract", None)
            declared_source = str(input_contract.get("entry_source") or "") if isinstance(input_contract, dict) else ""
            if declared_source and declared_source != entry_source:
                add("entry_source", qro_id, "QRO input contract entry source does not match coverage")

        entrypoint_ref = str(getattr(record, "entrypoint_ref", "") or "")
        binding_refs = {
            str(ref)
            for item in (*irs, *passes)
            for ref in (
                *tuple(getattr(item, "tool_record_refs", ()) or ()),
                *tuple(getattr(item, "canonical_command_refs", ()) or ()),
                *tuple(getattr(item, "node_refs", ()) or ()),
            )
        }
        artifact_derivative_bound = False
        if entrypoint_ref.startswith("compiler_artifact:"):
            artifact_refs = tuple(
                str(ref)
                for ref in tuple(getattr(record, "lifecycle_refs", ()) or ())
                if str(ref).startswith("compiler_artifact:")
            )
            if len(artifact_refs) == 1:
                try:
                    artifact = self._compiler_store.canonical_artifact(
                        artifact_refs[0],
                        owner=self._owner,
                    )
                except (KeyError, LookupError, ValueError):
                    artifact = None
                artifact_derivative_bound = artifact is not None and (
                    entrypoint_ref
                    == "compiler_artifact:"
                    + str(getattr(artifact, "artifact_kind", "") or "")
                    and tuple(getattr(artifact, "source_ir_refs", ()) or ())
                    == tuple(getattr(record, "compiler_ir_refs", ()) or ())
                    and tuple(getattr(artifact, "compiler_pass_refs", ()) or ())
                    == tuple(getattr(record, "compiler_pass_refs", ()) or ())
                )
        if (
            entrypoint_ref not in binding_refs
            and f"entrypoint:{entrypoint_ref}" not in binding_refs
            and not artifact_derivative_bound
        ):
            add("entrypoint_ref", entrypoint_ref, "entrypoint ref is not bound by the persisted IR/pass records")

        expected_replay_refs = {
            *(f"replay:research_graph:{ref}" for ref in actual_graph),
            *(f"replay:compiler_ir:{ref}" for ref in actual_irs),
            *(f"replay:compiler_pass:{ref}" for ref in tuple(getattr(record, "compiler_pass_refs", ()) or ())),
        }
        actual_replay_refs = {str(ref) for ref in tuple(getattr(record, "replay_refs", ()) or ())}
        if expected_replay_refs != actual_replay_refs:
            add("replay_refs", ",".join(sorted(actual_replay_refs)), "coverage replay refs must exactly equal deterministic graph/compiler replay refs")

        return tuple(violations)


def build_real_ref_resolver(
    *,
    research_graph_store: Any,
    lifecycle_registry: Any,
    governance_registry: Any,
    rag_index: Any,
    spine_chain_registry: Any,
    compiler_store: Any = None,
    document_store: Any = None,
    rdp_store: Any = None,
    market_data_registry: PersistentMarketDataRegistry | None = None,
    dataset_registry: Any = None,
    onboarding_registry: Any = None,
    llm_service_owner_user_id: str | None = None,
    llm_call_record_store: Any = None,
    account_halt_barrier: Any = None,
    goal_validation_receipt_registry: Any = None,
    goal_full_product_attestation_registry: Any = None,
    platform_source_evidence_registry: Any = None,
    lifecycle_loaders: tuple[Callable[[str, str], Any], ...] = (),
    owner: str | None = None,
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
                compiler_store=COMPILER_IR_STORE,
                document_store=DOCUMENT_INTELLIGENCE_STORE,
                market_data_registry=MARKET_DATA_REGISTRY,
            )
        )
    """

    return RealRefResolver(
        research_graph_store=research_graph_store,
        lifecycle_registry=lifecycle_registry,
        governance_registry=governance_registry,
        rag_index=rag_index,
        spine_chain_registry=spine_chain_registry,
        compiler_store=compiler_store,
        document_store=document_store,
        rdp_store=rdp_store,
        market_data_registry=market_data_registry,
        dataset_registry=dataset_registry,
        onboarding_registry=onboarding_registry,
        llm_service_owner_user_id=llm_service_owner_user_id,
        llm_call_record_store=llm_call_record_store,
        account_halt_barrier=account_halt_barrier,
        goal_validation_receipt_registry=goal_validation_receipt_registry,
        goal_full_product_attestation_registry=(
            goal_full_product_attestation_registry
        ),
        platform_source_evidence_registry=platform_source_evidence_registry,
        lifecycle_loaders=lifecycle_loaders,
        owner=owner,
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
    "is_exact_current_research_graph_command",
    "is_placeholder_ref",
    "resolve_typed_ref",
]
