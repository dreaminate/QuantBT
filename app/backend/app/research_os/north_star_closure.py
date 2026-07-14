"""Non-circular GOAL §0 closure over the current §1-§17 proof heads.

§0 is the product north star.  It cannot honestly certify itself from the
§0-§17 coverage manifest because that would make the manifest its own proof.
This adapter instead derives one read-only snapshot from:

* the persisted current six-entrypoint aggregate; and
* the latest persisted, complete, currently-valid semantic proof for every
  section from §1 through §17.

The §0 proof is then the only newly-written record.  Source lookup is read-only
and deliberately excludes every §0 proof, including historical §0 refs that a
later section proof might try to feed back into the closure.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from ..lineage.ids import content_hash
from .goal_coverage import REQUIRED_GOAL_SECTIONS
from .goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
    goal_section_semantic_proof_identity,
)


NORTH_STAR_SOURCE_SECTIONS: tuple[str, ...] = tuple(
    section for section in REQUIRED_GOAL_SECTIONS if section != "§0"
)
NORTH_STAR_CLOSURE_ENTRYPOINT_REF = "api:goal.north_star_closure.current"


@dataclass(frozen=True)
class NorthStarClosureSnapshot:
    """Server-derived inputs and exact semantic fields for one §0 proof."""

    aggregate_ref: str
    section_proof_refs: tuple[tuple[str, str], ...]
    entrypoint_coverage_refs: tuple[str, ...]
    producer_refs: tuple[str, ...]
    store_refs: tuple[str, ...]
    consumer_refs: tuple[str, ...]
    gate_verdict_refs: tuple[str, ...]
    test_refs: tuple[str, ...]

    @property
    def snapshot_ref(self) -> str:
        return "north_star_snapshot:" + content_hash(
            {
                "aggregate_ref": self.aggregate_ref,
                "section_proof_refs": self.section_proof_refs,
                "entrypoint_coverage_refs": self.entrypoint_coverage_refs,
                "producer_refs": self.producer_refs,
                "store_refs": self.store_refs,
                "consumer_refs": self.consumer_refs,
                "gate_verdict_refs": self.gate_verdict_refs,
                "test_refs": self.test_refs,
            }
        )


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value or "").strip()
                for value in values
                if str(value or "").strip()
            }
        )
    )


def _current_complete_section_proofs(
    semantic_registry: Any,
    *,
    owner: str,
) -> tuple[GoalSectionSemanticProofRecord, ...]:
    heads: list[GoalSectionSemanticProofRecord] = []
    for section in NORTH_STAR_SOURCE_SECTIONS:
        records = semantic_registry.records(owner=owner, section=section)
        if not records:
            raise ValueError(f"north_star_section_proof_missing:{section}")
        head = records[-1]
        decision = semantic_registry.validate_real_backing(head, owner=owner)
        if not decision.accepted:
            codes = ",".join(item.code for item in decision.violations)
            raise ValueError(f"north_star_section_proof_not_current:{section}:{codes}")
        if not head.claims_section_complete or head.unverified_residuals:
            raise ValueError(f"north_star_section_proof_incomplete:{section}")
        heads.append(head)
    return tuple(heads)


def resolve_current_north_star_snapshot(
    semantic_registry: Any,
    entrypoint_aggregate_registry: Any,
    *,
    owner: str,
) -> NorthStarClosureSnapshot:
    """Resolve the exact non-§0 sources without writing or minting evidence."""

    normalized_owner = str(owner or "").strip()
    if not normalized_owner:
        raise ValueError("north_star_owner_required")

    current_aggregate = entrypoint_aggregate_registry.build_current(
        owner_user_id=normalized_owner
    )
    try:
        aggregate = entrypoint_aggregate_registry.aggregate(
            current_aggregate.aggregate_ref,
            owner_user_id=normalized_owner,
        )
    except KeyError as exc:
        raise ValueError("north_star_entrypoint_aggregate_not_persisted") from exc
    aggregate_violations = entrypoint_aggregate_registry.validate_current(
        aggregate,
        owner_user_id=normalized_owner,
    )
    if aggregate_violations:
        raise ValueError(
            "north_star_entrypoint_aggregate_not_current:"
            + ",".join(aggregate_violations)
        )

    heads = _current_complete_section_proofs(
        semantic_registry,
        owner=normalized_owner,
    )
    historical_zero_refs = {
        ref
        for proof in semantic_registry.records(owner=normalized_owner, section="§0")
        for ref in (proof.proof_ref, proof.subject_ref)
        if ref
    }
    source_values = {
        ref
        for proof in heads
        for ref in (
            proof.subject_ref,
            *proof.producer_refs,
            *proof.store_refs,
            *proof.consumer_refs,
            *proof.gate_verdict_refs,
            *proof.test_refs,
            *proof.entrypoint_coverage_refs,
        )
    }
    circular_refs = sorted(historical_zero_refs.intersection(source_values))
    if circular_refs:
        raise ValueError(
            "north_star_historical_zero_ref_cycle:" + ",".join(circular_refs)
        )

    section_proof_refs = tuple(
        (section, proof.proof_ref)
        for section, proof in zip(NORTH_STAR_SOURCE_SECTIONS, heads, strict=True)
    )
    return NorthStarClosureSnapshot(
        aggregate_ref=aggregate.aggregate_ref,
        section_proof_refs=section_proof_refs,
        entrypoint_coverage_refs=tuple(aggregate.coverage_refs),
        producer_refs=_unique_sorted(
            ref for proof in heads for ref in proof.producer_refs
        ),
        store_refs=_unique_sorted(
            (
                aggregate.aggregate_ref,
                *(proof.proof_ref for proof in heads),
                *(ref for proof in heads for ref in proof.store_refs),
            )
        ),
        consumer_refs=_unique_sorted(
            (
                NORTH_STAR_CLOSURE_ENTRYPOINT_REF,
                *(ref for proof in heads for ref in proof.consumer_refs),
            )
        ),
        gate_verdict_refs=_unique_sorted(
            (
                aggregate.aggregate_ref,
                *(ref for proof in heads for ref in proof.gate_verdict_refs),
            )
        ),
        test_refs=_unique_sorted(
            ref for proof in heads for ref in proof.test_refs
        ),
    )


def build_current_north_star_proof(
    semantic_registry: Any,
    entrypoint_aggregate_registry: Any,
    *,
    owner: str,
) -> GoalSectionSemanticProofRecord:
    """Build, but do not persist, the exact current §0 semantic proof."""

    normalized_owner = str(owner or "").strip()
    snapshot = resolve_current_north_star_snapshot(
        semantic_registry,
        entrypoint_aggregate_registry,
        owner=normalized_owner,
    )
    provisional = GoalSectionSemanticProofRecord(
        proof_ref="",
        section="§0",
        subject_ref=snapshot.snapshot_ref,
        producer_refs=snapshot.producer_refs,
        store_refs=snapshot.store_refs,
        consumer_refs=snapshot.consumer_refs,
        gate_verdict_refs=snapshot.gate_verdict_refs,
        test_refs=snapshot.test_refs,
        entrypoint_coverage_refs=snapshot.entrypoint_coverage_refs,
        recorded_by=normalized_owner,
        claims_section_complete=True,
        unverified_residuals=(),
    )
    return replace(
        provisional,
        proof_ref=goal_section_semantic_proof_identity(
            section=provisional.section,
            subject_ref=provisional.subject_ref,
            producer_refs=provisional.producer_refs,
            store_refs=provisional.store_refs,
            consumer_refs=provisional.consumer_refs,
            gate_verdict_refs=provisional.gate_verdict_refs,
            test_refs=provisional.test_refs,
            entrypoint_coverage_refs=provisional.entrypoint_coverage_refs,
            recorded_by=provisional.recorded_by,
            claims_section_complete=provisional.claims_section_complete,
            unverified_residuals=provisional.unverified_residuals,
        ),
    )


class NorthStarClosureSectionAdapter:
    """Validate §0 only against current §1-§17 heads and six-entry aggregate."""

    def __init__(self, semantic_registry: Any, entrypoint_aggregate_registry: Any) -> None:
        self._semantic_registry = semantic_registry
        self._entrypoint_aggregate_registry = entrypoint_aggregate_registry

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, reason: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_north_star_invalid",
                    reason,
                    field=field,
                    ref=ref,
                )
            )

        if record.section != "§0":
            reject("section", record.section, "north-star adapter only supports §0")
            return GoalSemanticDecision(False, tuple(violations))
        if record.proof_ref in {
            record.subject_ref,
            *record.producer_refs,
            *record.store_refs,
            *record.consumer_refs,
            *record.gate_verdict_refs,
            *record.test_refs,
            *record.entrypoint_coverage_refs,
        }:
            reject(
                "proof_ref",
                record.proof_ref,
                "§0 proof cannot cite itself as subject, source, store, consumer, gate, test, or entrypoint",
            )
        try:
            expected = build_current_north_star_proof(
                self._semantic_registry,
                self._entrypoint_aggregate_registry,
                owner=owner,
            )
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            reject(
                "subject_ref",
                record.subject_ref,
                f"current non-circular §1-§17 source snapshot is unavailable: {exc}",
            )
            return GoalSemanticDecision(False, tuple(violations))

        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "§0 completion requires every §1-§17 head complete with no residuals",
            )
        for field_name in (
            "subject_ref",
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
            "entrypoint_coverage_refs",
        ):
            actual = getattr(record, field_name)
            wanted = getattr(expected, field_name)
            if actual != wanted:
                reject(
                    field_name,
                    str(actual),
                    f"{field_name} must equal the server-derived current §1-§17 closure snapshot",
                )
        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "NORTH_STAR_CLOSURE_ENTRYPOINT_REF",
    "NORTH_STAR_SOURCE_SECTIONS",
    "NorthStarClosureSectionAdapter",
    "NorthStarClosureSnapshot",
    "build_current_north_star_proof",
    "resolve_current_north_star_snapshot",
]
