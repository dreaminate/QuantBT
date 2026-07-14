"""Canonical section adapters for GOAL semantic proofs.

Adapters are read-only.  They derive the expected proof fields from persisted
owner-scoped stores and reject any caller-supplied recombination.
"""

from __future__ import annotations

from typing import Any

from .goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    strict_current_entrypoint_coverage,
    strict_current_entrypoint_lookup,
)
from .goal_entrypoint_lineage_aggregate import (
    PersistentGoalEntrypointLineageAggregateRegistry,
)
from .goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
)


def _entry_source(record) -> str:
    value = getattr(record, "entry_source", "")
    return str(getattr(value, "value", value) or "")


class EntrypointLineageSectionAdapter:
    """Prove §1/§8 from all six strict QRO -> Graph -> Compiler lineages."""

    def __init__(
        self,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        aggregate_registry: PersistentGoalEntrypointLineageAggregateRegistry,
        *,
        section: str,
    ) -> None:
        if section not in {"§1", "§8"}:
            raise ValueError("entrypoint lineage adapter only supports §1 or §8")
        self._entrypoint_registry = entrypoint_registry
        self._aggregate_registry = aggregate_registry
        self._section = section

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
                    "goal_semantic_entrypoint_aggregate_invalid",
                    reason,
                    field=field,
                    ref=ref,
                )
            )

        if record.section != self._section:
            reject("section", record.section, "adapter section mismatch")
            return GoalSemanticDecision(False, tuple(violations))
        if len(record.gate_verdict_refs) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(record.gate_verdict_refs),
                "section aggregate requires one durable current-head receipt",
            )
            return GoalSemanticDecision(False, tuple(violations))
        aggregate_ref = record.gate_verdict_refs[0]
        expected_subject = (
            f"goal_section:{self._section}:entrypoint_aggregate:{aggregate_ref}"
        )
        if record.subject_ref != expected_subject:
            reject(
                "subject_ref",
                record.subject_ref,
                "section subject must bind the durable current-head aggregate",
            )
        try:
            aggregate = self._aggregate_registry.aggregate(
                aggregate_ref,
                owner_user_id=owner,
            )
        except KeyError:
            reject(
                "gate_verdict_refs",
                aggregate_ref,
                "entrypoint aggregate receipt is not persisted for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        current_violations = self._aggregate_registry.validate_current(
            aggregate,
            owner_user_id=owner,
        )
        if current_violations:
            reject(
                "gate_verdict_refs",
                aggregate_ref,
                "entrypoint aggregate receipt is no longer current: "
                + ",".join(current_violations),
            )
        if tuple(record.entrypoint_coverage_refs) != tuple(aggregate.coverage_refs):
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "semantic proof coverage refs must equal the durable aggregate",
            )

        coverages = []
        coverage_for_ref = strict_current_entrypoint_lookup(
            self._entrypoint_registry,
            owner=owner,
        )
        for coverage_ref in record.entrypoint_coverage_refs:
            try:
                coverage = coverage_for_ref(coverage_ref)
            except KeyError:
                reject("entrypoint_coverage_refs", coverage_ref, "coverage is not persisted for owner")
                continue
            decision = self._entrypoint_registry.validate_real_backing(coverage)
            if not decision.accepted:
                reject("entrypoint_coverage_refs", coverage_ref, "coverage failed strict real backing")
            if self._section not in set(coverage.goal_sections):
                reject("entrypoint_coverage_refs", coverage_ref, "coverage does not cite adapter section")
            coverages.append(coverage)

        sources = {_entry_source(item) for item in coverages}
        if (
            sources != set(REQUIRED_ENTRY_SOURCES)
            or len(coverages) != len(REQUIRED_ENTRY_SOURCES)
            or len({item.coverage_ref for item in coverages}) != len(coverages)
        ):
            reject(
                "entrypoint_coverage_refs",
                ",".join(sorted(sources)),
                "section aggregate requires exactly all six canonical entry sources",
            )

        expected_producers = {
            ref
            for coverage in coverages
            for ref in coverage.research_graph_command_refs
        }
        expected_stores = {
            aggregate.aggregate_ref,
            *(coverage.coverage_ref for coverage in coverages),
            *(ref for coverage in coverages for ref in coverage.qro_refs),
            *(ref for coverage in coverages for ref in coverage.compiler_ir_refs),
            *(ref for coverage in coverages for ref in coverage.compiler_pass_refs),
        }
        expected_consumers = {coverage.entrypoint_ref for coverage in coverages}
        expected_gates = {aggregate.aggregate_ref}
        expected_tests = {
            ref
            for coverage in coverages
            for ref in coverage.validation_refs
        }
        for field_name, expected in (
            ("producer_refs", expected_producers),
            ("store_refs", expected_stores),
            ("consumer_refs", expected_consumers),
            ("gate_verdict_refs", expected_gates),
            ("test_refs", expected_tests),
        ):
            actual = set(getattr(record, field_name))
            if actual != expected:
                reject(
                    field_name,
                    ",".join(sorted(actual)),
                    f"{field_name} must equal the persisted six-entry lineage",
                )

        return GoalSemanticDecision(not violations, tuple(violations))


_PROMOTION_SECTIONS = {
    "§6": ("6",),
    "§9": ("9",),
    "§10": ("10_cost", "10_control_plane"),
    "§13": ("13",),
    "§16": ("16",),
    "§17": ("17",),
}


class PromotionReceiptSectionAdapter:
    """Prove promotion-gated sections from one current durable receipt."""

    def __init__(
        self,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        promotion_receipt_registry: Any,
        *,
        section: str,
    ) -> None:
        if section not in _PROMOTION_SECTIONS:
            raise ValueError("promotion receipt adapter supports §6/§9/§10/§13/§16/§17")
        self._entrypoint_registry = entrypoint_registry
        self._promotion_receipt_registry = promotion_receipt_registry
        self._section = section

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
                    "goal_semantic_promotion_receipt_invalid",
                    reason,
                    field=field,
                    ref=ref,
                )
            )

        if record.section != self._section:
            reject("section", record.section, "promotion adapter section mismatch")
            return GoalSemanticDecision(False, tuple(violations))
        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "promotion semantic proof must claim completion with no residuals",
            )
        if len(record.entrypoint_coverage_refs) != 1:
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "promotion semantic proof requires exactly one formal IDE promote lineage",
            )
            return GoalSemanticDecision(False, tuple(violations))

        coverage_ref = record.entrypoint_coverage_refs[0]
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoint_registry,
                coverage_ref,
                owner=owner,
            )
        except KeyError:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "formal IDE promote coverage is not persisted for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        coverage_decision = self._entrypoint_registry.validate_real_backing(coverage)
        if not coverage_decision.accepted:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "formal IDE promote coverage failed strict current backing",
            )
        if _entry_source(coverage) != "ide" or coverage.entrypoint_ref != "ide:run.promote":
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "semantic proof must use the canonical IDE formal promote entrypoint",
            )
        if self._section not in set(coverage.goal_sections):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "formal IDE promote lineage does not cite this section",
            )

        receipt_refs = tuple(
            ref
            for ref in coverage.validation_refs
            if str(ref).startswith("ide_promotion_receipt:")
        )
        if len(receipt_refs) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(receipt_refs),
                "formal IDE promote lineage must bind exactly one promotion receipt",
            )
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._promotion_receipt_registry.receipt(
                receipt_ref,
                owner_user_id=owner,
            )
        except KeyError:
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "promotion receipt is not persisted for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        current = self._promotion_receipt_registry.validate_current(
            receipt_ref,
            owner_user_id=owner,
            source_ide_run_id=receipt.source_ide_run_id,
            promoted_run_id=receipt.promoted_run_id,
            rdp_package_id=receipt.rdp_package_id,
            requested_label=receipt.requested_label,
        )
        if not bool(getattr(current, "accepted", False)):
            codes = ",".join(
                sorted(
                    {
                        str(getattr(item, "code", "promotion_receipt_invalid"))
                        for item in tuple(getattr(current, "violations", ()) or ())
                    }
                )
            )
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "promotion receipt is no longer current" + (f": {codes}" if codes else ""),
            )

        required_rows = set(_PROMOTION_SECTIONS[self._section])
        section_rows = tuple(
            item
            for item in receipt.section_verifications
            if str(item.section) in required_rows
        )
        if {str(item.section) for item in section_rows} != required_rows:
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "promotion receipt does not contain the exact section gate set",
            )
        expected_subject = (
            f"goal_section:{self._section}:promotion_receipt:{receipt_ref}"
        )
        expected_producers = {
            ref for item in section_rows for ref in item.canonical_source_refs
        }
        expected_stores = {
            receipt_ref,
            receipt.rdp_package_id,
            f"ide_run:{receipt.source_ide_run_id}",
        }
        expected_consumers = {f"run:{receipt.promoted_run_id}"}
        expected_gates = {
            "promotion_gate_verdict:"
            f"{receipt_ref}:{item.gate_name}:{item.gate_verdict_sha256}"
            for item in section_rows
        }
        expected_tests = {
            receipt_ref,
            *(
                "runtime_gate_check:"
                f"{receipt_ref}:{item.gate_name}:{item.assembled_payload_sha256}:"
                f"{item.gate_verdict_sha256}"
                for item in section_rows
            ),
        }
        if record.subject_ref != expected_subject:
            reject(
                "subject_ref",
                record.subject_ref,
                "semantic proof subject must content-bind the promotion receipt",
            )
        for field_name, expected in (
            ("producer_refs", expected_producers),
            ("store_refs", expected_stores),
            ("consumer_refs", expected_consumers),
            ("gate_verdict_refs", expected_gates),
            ("test_refs", expected_tests),
        ):
            actual_values = tuple(getattr(record, field_name))
            if len(actual_values) != len(set(actual_values)) or set(actual_values) != expected:
                reject(
                    field_name,
                    ",".join(sorted(actual_values)),
                    f"{field_name} must exactly match the current promotion receipt",
                )

        return GoalSemanticDecision(not violations, tuple(violations))


class LifecycleClosureSectionAdapter:
    """Prove §3 from one current multi-family lifecycle closure receipt."""

    def __init__(self, entrypoint_registry, lifecycle_transition_registry) -> None:
        self._entrypoint_registry = entrypoint_registry
        self._lifecycle_transition_registry = lifecycle_transition_registry

    def validate(self, record, *, owner: str) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, reason: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_lifecycle_closure_invalid",
                    reason,
                    field=field,
                    ref=ref,
                )
            )

        if record.section != "§3":
            reject("section", record.section, "lifecycle adapter only supports §3")
            return GoalSemanticDecision(False, tuple(violations))
        if len(record.entrypoint_coverage_refs) != 1:
            reject("entrypoint_coverage_refs", "", "§3 requires one closure API lineage")
            return GoalSemanticDecision(False, tuple(violations))
        coverage_ref = record.entrypoint_coverage_refs[0]
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoint_registry,
                coverage_ref,
                owner=owner,
            )
        except KeyError:
            reject("entrypoint_coverage_refs", coverage_ref, "§3 closure API lineage is absent")
            return GoalSemanticDecision(False, tuple(violations))
        if not self._entrypoint_registry.validate_real_backing(coverage).accepted:
            reject("entrypoint_coverage_refs", coverage_ref, "§3 closure API lineage is not current")
        if _entry_source(coverage) != "api" or coverage.entrypoint_ref != "api:goal.lifecycle.closure":
            reject("entrypoint_coverage_refs", coverage_ref, "§3 requires canonical lifecycle closure API")
        receipt_refs = tuple(
            ref
            for ref in coverage.validation_refs
            if str(ref).startswith("lifecycle_closure_receipt:")
        )
        if len(receipt_refs) != 1:
            reject("gate_verdict_refs", "", "§3 API lineage must bind exactly one lifecycle receipt")
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._lifecycle_transition_registry.receipt(
                receipt_ref,
                owner_user_id=owner,
            )
        except KeyError:
            reject("gate_verdict_refs", receipt_ref, "§3 lifecycle receipt is absent for owner")
            return GoalSemanticDecision(False, tuple(violations))
        current = self._lifecycle_transition_registry.validate_current(
            receipt_ref,
            owner_user_id=owner,
        )
        if not current.accepted:
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§3 lifecycle receipt is stale: " + ",".join(current.violations),
            )
        expected = {
            "subject_ref": f"goal_section:§3:lifecycle_receipt:{receipt_ref}",
            "producer_refs": set(receipt.transition_refs),
            "store_refs": {receipt_ref, *receipt.current_asset_refs},
            "consumer_refs": {
                f"lifecycle_current:{ref}" for ref in receipt.current_asset_refs
            },
            "gate_verdict_refs": {receipt_ref},
            "test_refs": {
                receipt_ref,
                *(f"lifecycle_transition_check:{ref}" for ref in receipt.transition_refs),
            },
        }
        if record.subject_ref != expected["subject_ref"]:
            reject("subject_ref", record.subject_ref, "§3 subject must bind lifecycle receipt")
        for field_name in (
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            actual = tuple(getattr(record, field_name))
            if len(actual) != len(set(actual)) or set(actual) != expected[field_name]:
                reject(field_name, ",".join(sorted(actual)), f"{field_name} does not match current lifecycle receipt")
        if not record.claims_section_complete or record.unverified_residuals:
            reject("claims_section_complete", record.proof_ref, "§3 completion cannot retain residuals")
        return GoalSemanticDecision(not violations, tuple(violations))


class RAGConformanceSectionAdapter:
    """Prove §5 from one current strict Agent RAG use and its real lineage."""

    def __init__(self, entrypoint_registry, rag_index) -> None:
        self._entrypoint_registry = entrypoint_registry
        self._rag_index = rag_index

    def validate(self, record, *, owner: str) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, reason: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_rag_conformance_invalid",
                    reason,
                    field=field,
                    ref=ref,
                )
            )

        if record.section != "§5":
            reject("section", record.section, "RAG conformance adapter only supports §5")
            return GoalSemanticDecision(False, tuple(violations))
        if len(record.entrypoint_coverage_refs) != 1:
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "§5 requires exactly one Agent Shell entrypoint lineage",
            )
            return GoalSemanticDecision(False, tuple(violations))
        coverage_ref = record.entrypoint_coverage_refs[0]
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoint_registry,
                coverage_ref,
                owner=owner,
            )
        except KeyError:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§5 Agent Shell entrypoint lineage is absent for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if not self._entrypoint_registry.validate_real_backing(coverage).accepted:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§5 Agent Shell entrypoint lineage is not current",
            )
        if _entry_source(coverage) != "agent_shell" or not str(
            coverage.entrypoint_ref
        ).startswith("agent_shell:"):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§5 requires the canonical Agent Shell execution lineage",
            )
        if "§5" not in set(coverage.goal_sections):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "Agent Shell lineage does not cite §5",
            )

        usage_refs = tuple(
            str(ref).removeprefix("rag_usage:")
            for ref in coverage.evidence_refs
            if str(ref).startswith("rag_usage:")
        )
        if len(usage_refs) != 1 or len(set(usage_refs)) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(usage_refs),
                "§5 lineage must bind exactly one strict Agent RAG usage",
            )
            return GoalSemanticDecision(False, tuple(violations))
        usage_id = usage_refs[0]
        try:
            usage = self._rag_index.strict_usage_for_owner(
                usage_id,
                owner_user_id=owner,
            )
            receipt = self._rag_index.validate_current_usage(
                usage_id,
                owner_user_id=owner,
            )
        except (KeyError, LookupError, TypeError, ValueError):
            reject(
                "gate_verdict_refs",
                usage_id,
                "strict Agent RAG usage is absent for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if not receipt.accepted:
            reject(
                "gate_verdict_refs",
                usage_id,
                "strict Agent RAG usage is stale: " + ",".join(receipt.violations),
            )
        if not usage.workflow_ref.startswith("agentwf_"):
            reject(
                "consumer_refs",
                usage.workflow_ref,
                "§5 proof requires a production Agent workflow, not a direct RAG API call",
            )
        if usage.tool_call_ref != f"{usage.workflow_ref}:rag_context":
            reject(
                "consumer_refs",
                usage.tool_call_ref,
                "§5 usage tool-call ref must bind the exact Agent workflow RAG invocation",
            )

        document_ids = tuple(item.document_id for item in usage.returned_documents)
        producer_refs = {
            f"rag_document:{item.document_id}:{item.source_id}@{item.version}"
            for item in usage.returned_documents
        }
        conformance_ref = (
            f"rag_conformance:{usage_id}:{receipt.query_digest}:{receipt.context_digest}"
        )
        expected = {
            "subject_ref": f"goal_section:§5:rag_usage:{usage_id}",
            "producer_refs": producer_refs,
            "store_refs": {usage_id, *document_ids},
            "consumer_refs": {usage.workflow_ref, usage.tool_call_ref},
            "gate_verdict_refs": {conformance_ref},
            "test_refs": {
                conformance_ref,
                *(f"rag_current_document:{document_id}" for document_id in document_ids),
            },
        }
        if record.subject_ref != expected["subject_ref"]:
            reject("subject_ref", record.subject_ref, "§5 subject must bind the strict usage")
        for field_name in (
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            actual = tuple(getattr(record, field_name))
            if len(actual) != len(set(actual)) or set(actual) != expected[field_name]:
                reject(
                    field_name,
                    ",".join(sorted(actual)),
                    f"{field_name} does not match the current strict RAG usage",
                )
        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "§5 completion cannot retain unverified residuals",
            )
        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "EntrypointLineageSectionAdapter",
    "LifecycleClosureSectionAdapter",
    "PromotionReceiptSectionAdapter",
    "RAGConformanceSectionAdapter",
]
