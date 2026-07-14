from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.ide.promotion_receipt import EXPECTED_GATE_BINDINGS
from app.research_os.goal_coverage import GoalCoverageDecision
from app.research_os.goal_semantic_adapters import PromotionReceiptSectionAdapter
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    goal_section_semantic_proof_identity,
)


OWNER = "user:semantic-owner"
RECEIPT_REF = "ide_promotion_receipt:semantic-current"
COVERAGE_REF = "goal_entrypoint_coverage:semantic-promote"


class _Entrypoints:
    def __init__(self, section: str) -> None:
        self.record = SimpleNamespace(
            coverage_ref=COVERAGE_REF,
            entry_source="ide",
            entrypoint_ref="ide:run.promote",
            goal_sections=(section,),
            validation_refs=(RECEIPT_REF, "goal_validation_receipt:compiler"),
        )

    def coverage(self, ref: str, *, owner: str):
        if ref != COVERAGE_REF or owner != OWNER:
            raise KeyError(ref)
        return self.record

    def validate_real_backing(self, record):
        assert record is self.record
        return GoalCoverageDecision(True, ())


class _Receipts:
    def __init__(self) -> None:
        self.current = True
        self.record = SimpleNamespace(
            receipt_ref=RECEIPT_REF,
            source_ide_run_id="source-42",
            promoted_run_id="promoted-42",
            rdp_package_id="rdp-42",
            requested_label="production_ready",
            section_verifications=tuple(
                SimpleNamespace(
                    section=section,
                    gate_name=gate_name,
                    gate_verdict_sha256=f"verdict-{section}",
                    assembled_payload_sha256=f"payload-{section}",
                    canonical_source_refs=(f"source:{section}:a", f"source:{section}:b"),
                )
                for section, _manifest_key, _producer_key, gate_name in EXPECTED_GATE_BINDINGS
            ),
        )

    def receipt(self, ref: str, *, owner_user_id: str):
        if ref != RECEIPT_REF or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.record

    def validate_current(self, *_args, **_kwargs):
        violation = SimpleNamespace(code="promotion_receipt_current_verification_drift")
        return SimpleNamespace(
            accepted=self.current,
            violations=() if self.current else (violation,),
        )


def _proof(section: str, receipts: _Receipts) -> GoalSectionSemanticProofRecord:
    section_names = {
        "§6": {"6"},
        "§9": {"9"},
        "§10": {"10_cost", "10_control_plane"},
        "§13": {"13"},
        "§16": {"16"},
        "§17": {"17"},
    }[section]
    rows = tuple(
        item
        for item in receipts.record.section_verifications
        if item.section in section_names
    )
    data = {
        "section": section,
        "subject_ref": f"goal_section:{section}:promotion_receipt:{RECEIPT_REF}",
        "producer_refs": tuple(
            ref for item in rows for ref in item.canonical_source_refs
        ),
        "store_refs": (RECEIPT_REF, "rdp-42", "ide_run:source-42"),
        "consumer_refs": ("run:promoted-42",),
        "gate_verdict_refs": tuple(
            f"promotion_gate_verdict:{RECEIPT_REF}:{item.gate_name}:{item.gate_verdict_sha256}"
            for item in rows
        ),
        "test_refs": (
            RECEIPT_REF,
            *(
                f"runtime_gate_check:{RECEIPT_REF}:{item.gate_name}:"
                f"{item.assembled_payload_sha256}:{item.gate_verdict_sha256}"
                for item in rows
            ),
        ),
        "entrypoint_coverage_refs": (COVERAGE_REF,),
        "recorded_by": OWNER,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    data["proof_ref"] = goal_section_semantic_proof_identity(**data)
    return GoalSectionSemanticProofRecord(**data)


@pytest.mark.parametrize("section", ("§6", "§9", "§10", "§13", "§16", "§17"))
def test_current_promotion_receipt_exactly_proves_registered_section(section: str) -> None:
    receipts = _Receipts()
    adapter = PromotionReceiptSectionAdapter(
        _Entrypoints(section),
        receipts,
        section=section,
    )

    decision = adapter.validate(_proof(section, receipts), owner=OWNER)

    assert decision.accepted, decision.violations


def test_receipt_drift_or_field_recombination_rejects_section() -> None:
    receipts = _Receipts()
    adapter = PromotionReceiptSectionAdapter(
        _Entrypoints("§10"),
        receipts,
        section="§10",
    )
    proof = _proof("§10", receipts)
    receipts.current = False

    drift = adapter.validate(proof, owner=OWNER)
    recombined = adapter.validate(
        replace(proof, producer_refs=(*proof.producer_refs, "source:unrelated")),
        owner=OWNER,
    )

    assert not drift.accepted
    assert any("no longer current" in item.message for item in drift.violations)
    assert not recombined.accepted
    assert any(item.field == "producer_refs" for item in recombined.violations)


def test_foreign_owner_cannot_reuse_promotion_receipt() -> None:
    receipts = _Receipts()
    adapter = PromotionReceiptSectionAdapter(
        _Entrypoints("§6"),
        receipts,
        section="§6",
    )

    decision = adapter.validate(_proof("§6", receipts), owner="user:other")

    assert not decision.accepted
    assert any("not persisted for owner" in item.message for item in decision.violations)
