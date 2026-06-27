from __future__ import annotations

from app.research_os.document_intelligence import (
    EvidenceSpanRecord,
    ExtractedResearchClaim,
    PrivilegedToolUseRequest,
    SourceDocumentIntakeRecord,
    validate_document_intelligence,
    validate_evidence_span,
    validate_extracted_claim,
    validate_privileged_tool_use,
    validate_source_document_intake,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _source(**overrides) -> SourceDocumentIntakeRecord:
    data = {
        "source_ref": "source:paper:001",
        "quarantine_ref": "quarantine:001",
        "parser_sandbox_ref": "sandbox:parser",
        "mime_magic_check_ref": "magic:pdf",
        "source_hash": "sha256:paper",
        "license_rights_ref": "license:ok",
        "no_network_parser": True,
        "untrusted_data_boundary_ref": "boundary:document_untrusted",
    }
    data.update(overrides)
    return SourceDocumentIntakeRecord(**data)


def _span(**overrides) -> EvidenceSpanRecord:
    data = {
        "span_ref": "span:001",
        "source_id": "source:paper:001",
        "doc_version_id": "doc_version:001",
        "parser_run_id": "parser_run:001",
        "block_id": "block:42",
        "page": 7,
        "quoted_excerpt_hash": "sha256:quote",
        "parser_confidence": 0.91,
        "span_support_verification_ref": "span_support:001",
        "verified": True,
    }
    data.update(overrides)
    return EvidenceSpanRecord(**data)


def test_source_intake_requires_sandbox_hash_rights_and_no_network_parser():
    decision = validate_source_document_intake(
        _source(parser_sandbox_ref=None, source_hash=None, no_network_parser=False)
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "source_intake_missing_safety_ref",
        "source_parser_network_enabled",
    }


def test_evidence_span_requires_location_hash_and_support_verification():
    decision = validate_evidence_span(
        _span(page=None, quoted_excerpt_hash=None, span_support_verification_ref=None)
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "evidence_span_missing_location",
        "evidence_span_missing_required_ref",
        "verified_span_missing_support_record",
    }


def test_extracted_claim_requires_evidence_span():
    decision = validate_extracted_claim(
        ExtractedResearchClaim(
            claim_ref="claim:strategy",
            claim_kind="ExtractedStrategySpec",
            evidence_span_refs=(),
        ),
        spans=(_span(),),
    )
    assert not decision.accepted
    assert "extracted_claim_missing_evidence_span" in _codes(decision)


def test_unverified_span_cannot_enter_confirmatory_claim():
    span = _span(verified=False)
    decision = validate_extracted_claim(
        ExtractedResearchClaim(
            claim_ref="claim:model",
            claim_kind="ExtractedModelClaim",
            evidence_span_refs=(span.span_ref,),
            confirmatory_use=True,
        ),
        spans=(span,),
    )
    assert not decision.accepted
    assert "unverified_span_used_for_confirmatory_claim" in _codes(decision)


def test_pdf_payload_cannot_directly_trigger_privileged_tool():
    decision = validate_privileged_tool_use(
        PrivilegedToolUseRequest(
            request_ref="tool:bad",
            source_document_ref="source:paper:001",
            direct_document_payload=True,
            schema_constrained_artifact_ref=None,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "document_payload_direct_privileged_tool_use",
        "privileged_tool_missing_schema_artifact",
    }


def test_complete_document_intelligence_contract_accepts_verified_claim_flow():
    span = _span()
    decision = validate_document_intelligence(
        sources=(_source(),),
        spans=(span,),
        claims=(
            ExtractedResearchClaim(
                claim_ref="claim:strategy",
                claim_kind="ExtractedStrategySpec",
                evidence_span_refs=(span.span_ref,),
                confirmatory_use=True,
            ),
        ),
        tool_requests=(
            PrivilegedToolUseRequest(
                request_ref="tool:schema_only",
                source_document_ref="source:paper:001",
                direct_document_payload=False,
                schema_constrained_artifact_ref="extracted_strategy_spec:001",
            ),
        ),
    )
    assert decision.accepted
    assert decision.violations == ()
