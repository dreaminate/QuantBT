from __future__ import annotations

from app.research_os.desk_projection import (
    CanvasMutationRequest,
    DeskHandoffRecord,
    DeskName,
    DeskProjectionRecord,
    validate_canvas_mutation,
    validate_desk_handoff,
    validate_desk_projection,
    validate_multi_desk_contract,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _projection(**overrides) -> DeskProjectionRecord:
    data = {
        "projection_ref": "projection:strategy",
        "desk": DeskName.STRATEGY,
        "source_of_truth_refs": ("research_graph", "asset_libraries"),
        "typed_canvas_ref": "canvas:strategy",
        "agent_shell_ref": "agent_shell:strategy",
        "rag_projection_ref": "rag:strategy",
        "math_projection_ref": "math:strategy",
        "asset_inspector_ref": "inspector:strategy",
        "tool_permission_ref": "permission:strategy",
        "editable_asset_types": ("StrategyBook", "PortfolioPolicy"),
        "canonical_command_types": ("UpdateStrategyBook",),
        "consistency_projection_ref": "consistency:strategy",
    }
    data.update(overrides)
    return DeskProjectionRecord(**data)


def test_desk_projection_requires_shared_research_graph():
    decision = validate_desk_projection(
        _projection(source_of_truth_refs=("local_store",), independent_truth_ref="local:true")
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "desk_projection_missing_research_graph",
        "desk_projection_independent_truth_state",
    }


def test_desk_projection_enforces_write_scope():
    decision = validate_desk_projection(_projection(editable_asset_types=("Factor",)))
    assert not decision.accepted
    assert "desk_projection_write_scope_violation" in _codes(decision)


def test_institutional_method_claim_requires_math_and_consistency_projection():
    decision = validate_desk_projection(
        _projection(
            claims_institutional_method=True,
            math_projection_ref=None,
            consistency_projection_ref=None,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "institutional_method_missing_math_projection",
        "institutional_method_missing_consistency_projection",
    }


def test_completed_handoff_requires_produced_ref_and_evidence():
    decision = validate_desk_handoff(
        DeskHandoffRecord(
            handoff_id="handoff:factor",
            from_desk=DeskName.STRATEGY,
            to_desk=DeskName.FACTOR,
            requested_asset="Factor:quality",
            reason="strategy needs new factor",
            blocking_dependency="factor_formula",
            status="completed",
            produced_ref=None,
            evidence_refs=(),
            created_by="agent",
            resolved_by="factor_agent",
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "desk_handoff_completed_without_produced_ref",
        "desk_handoff_completed_without_evidence",
    }


def test_strategy_desk_cannot_write_factor_formula_and_must_use_canonical_command():
    decision = validate_canvas_mutation(
        CanvasMutationRequest(
            command_ref="cmd:bad_factor_write",
            source_desk=DeskName.STRATEGY,
            actor_source="user_manual",
            target_asset_type="Factor",
            field_path="formula.expression",
            canonical_command_ref=None,
            audit_ref=None,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "strategy_desk_cannot_write_factor_formula",
        "canvas_mutation_missing_canonical_command",
        "canvas_mutation_missing_audit_ref",
    }


def test_complete_multi_desk_contract_accepts_projection_handoff_and_mutation():
    decision = validate_multi_desk_contract(
        (_projection(),),
        handoffs=(
            DeskHandoffRecord(
                handoff_id="handoff:signal",
                from_desk=DeskName.STRATEGY,
                to_desk=DeskName.SIGNAL,
                requested_asset="Signal:trend",
                reason="strategy book needs signal contract",
                blocking_dependency=None,
                status="completed",
                produced_ref="signal:trend:v1",
                evidence_refs=("validation:signal:v1",),
                created_by="user_manual",
                resolved_by="signal_agent",
            ),
        ),
        mutations=(
            CanvasMutationRequest(
                command_ref="cmd:update_strategy",
                source_desk=DeskName.STRATEGY,
                actor_source="agent",
                target_asset_type="StrategyBook",
                field_path="legs.0.signal_ref",
                canonical_command_ref="command:UpdateStrategyBook:001",
                audit_ref="audit:001",
            ),
        ),
    )
    assert decision.accepted
    assert decision.violations == ()
