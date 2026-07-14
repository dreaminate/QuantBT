from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.platform_business_attestations import (
    PlatformBusinessAttestationCommitError,
    PlatformBusinessAttestationCompilePlan,
    PlatformBusinessAttestationError,
    PlatformBusinessAttestationResult,
)
from app.research_os.spine import (
    ActorSource,
    EntrySource,
    QRORecord,
    QROType,
    ResearchGraphCommand,
)


OWNER = "owner:platform-business-attestation-api"
ENTRYPOINTS = {
    "M17": "api:research_os.platform.business_attestations.m17",
    "M18": "api:research_os.platform.business_attestations.m18",
    "M20": "api:research_os.platform.business_attestations.m20",
}


@pytest.fixture(autouse=True)
def _clear_auth_override():
    main.app.dependency_overrides.pop(require_user_dependency, None)
    yield
    main.app.dependency_overrides.pop(require_user_dependency, None)


def _client() -> TestClient:
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=OWNER,
        username="platform-business-attestation-owner",
    )
    return TestClient(main.app)


def _success(*, row: str, anchor_ref: str) -> PlatformBusinessAttestationResult:
    token = row.lower()
    return PlatformBusinessAttestationResult(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=anchor_ref,
        entrypoint_ref=ENTRYPOINTS[row],
        qro_ref=f"qro:business-attestation:{token}",
        graph_command_ref=f"rgcmd:business-attestation:{token}",
        graph_command_created=True,
        mathematical_spine_chain_ref=f"math_spine_chain:business-attestation:{token}",
        compiler_ir_ref=f"compiler_ir:business-attestation:{token}",
        compiler_pass_ref=f"compiler_pass:business-attestation:{token}",
        entrypoint_coverage_ref=f"goal_entrypoint_coverage:business-attestation:{token}",
    )


@pytest.mark.parametrize("row", tuple(ENTRYPOINTS))
def test_platform_business_attestation_route_dispatches_exact_owner_anchor_and_state(
    monkeypatch,
    row: str,
) -> None:
    anchor_ref = f"business_anchor:{row.lower()}"
    calls: list[dict[str, str]] = []

    def record(**kwargs):
        calls.append(dict(kwargs))
        return _success(row=row, anchor_ref=anchor_ref)

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_ATTESTATION_SERVICE",
        SimpleNamespace(record=record),
    )
    response = _client().post(
        f"/api/research-os/platform/business_attestations/{row}/current",
        json={"anchor_ref": anchor_ref},
    )

    assert response.status_code == 200, response.text
    assert calls == [
        {
            "owner_user_id": OWNER,
            "row": row,
            "anchor_ref": anchor_ref,
        }
    ]
    token = row.lower()
    assert response.json() == {
        "m_row": row,
        "anchor_ref": anchor_ref,
        "entry_source": "api",
        "entrypoint_ref": ENTRYPOINTS[row],
        "qro_ref": f"qro:business-attestation:{token}",
        "math_spine_ref": f"math_spine_chain:business-attestation:{token}",
        "graph_command_ref": f"rgcmd:business-attestation:{token}",
        "graph_command_created": True,
        "compiler_ir_ref": f"compiler_ir:business-attestation:{token}",
        "compiler_pass_ref": f"compiler_pass:business-attestation:{token}",
        "entrypoint_coverage_ref": (
            f"goal_entrypoint_coverage:business-attestation:{token}"
        ),
        "graph_attestation_current": True,
        "compiler_bundle_verified": True,
        "coverage_persisted": True,
        "policy_replay_current": True,
        "business_side_effects_performed": False,
    }


def test_platform_business_attestation_route_rejects_caller_proof_refs_before_service(
    monkeypatch,
) -> None:
    called = False

    def record(**_kwargs):
        nonlocal called
        called = True
        return _success(row="M17", anchor_ref="execution_policy:m17")

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_ATTESTATION_SERVICE",
        SimpleNamespace(record=record),
    )
    response = _client().post(
        "/api/research-os/platform/business_attestations/M17/current",
        json={
            "anchor_ref": "execution_policy:m17",
            "qro_ref": "qro:caller-forged",
            "graph_command_ref": "rgcmd:caller-forged",
            "compiler_ir_ref": "compiler_ir:caller-forged",
            "math_spine_ref": "math_spine_chain:caller-forged",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "platform business attestation payload must contain exactly: anchor_ref"
    }
    assert called is False


@pytest.mark.parametrize("row", ("M16", "M19", "M21", "M17-M18", "m17"))
def test_platform_business_attestation_route_rejects_unsupported_or_lowercase_rows(
    monkeypatch,
    row: str,
) -> None:
    called = False

    def record(**_kwargs):
        nonlocal called
        called = True
        return _success(row="M17", anchor_ref="business_anchor:m17")

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_ATTESTATION_SERVICE",
        SimpleNamespace(record=record),
    )
    response = _client().post(
        f"/api/research-os/platform/business_attestations/{row}/current",
        json={"anchor_ref": "business_anchor:unsupported"},
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "m_row does not use a platform business attestation"
    }
    assert called is False


def test_platform_business_attestation_route_reports_exact_partial_commit_state(
    monkeypatch,
) -> None:
    def record(**_kwargs):
        raise PlatformBusinessAttestationCommitError(
            "business attestation compiler write stopped",
            phase="compiler_coverage",
            graph_attestation_current=True,
            graph_command_ref="rgcmd:business-attestation:m18",
            graph_command_created=True,
        )

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_ATTESTATION_SERVICE",
        SimpleNamespace(record=record),
    )
    response = _client().post(
        "/api/research-os/platform/business_attestations/M18/current",
        json={"anchor_ref": "validation_dossier:m18"},
    )

    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": {
            "message": "business attestation compiler write stopped",
            "phase": "compiler_coverage",
            "graph_attestation_current": True,
            "graph_command_ref": "rgcmd:business-attestation:m18",
            "graph_command_created": True,
            "compiler_state": "unverified_after_failure",
            "policy_replay_current": False,
            "business_side_effects_performed": False,
        }
    }


def test_platform_business_attestation_route_maps_semantic_error_to_422(
    monkeypatch,
) -> None:
    def record(**_kwargs):
        raise PlatformBusinessAttestationError(
            "current business evidence is stale or ambiguous"
        )

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_ATTESTATION_SERVICE",
        SimpleNamespace(record=record),
    )
    response = _client().post(
        "/api/research-os/platform/business_attestations/M20/current",
        json={"anchor_ref": "risk_policy:m20"},
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "current business evidence is stale or ambiguous"
    }


def _compile_qro(*, qro_id: str = "qro:business-attestation:m17") -> QRORecord:
    return QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract={"anchor_ref": "execution_policy:m17"},
        output_contract={"status": "guarded_submission_recorded"},
        market="paper",
        universe="copy_trade",
        horizon="event",
        frequency="event",
        lineage=("execution_policy:m17",),
        implementation_hash="implementation:business-attestation:m17:v1",
        assumptions=("The business state was persisted before attestation.",),
        known_limits=("The attestation does not submit an order.",),
        failure_modes=("Stale business state fails closed.",),
        validation_plan=("Resolve the exact owner-scoped business state.",),
        qro_id=qro_id,
    )


def _compile_plan() -> PlatformBusinessAttestationCompilePlan:
    return PlatformBusinessAttestationCompilePlan(
        row="M17",
        owner_user_id=OWNER,
        anchor_ref="execution_policy:m17",
        entrypoint_ref=ENTRYPOINTS["M17"],
        pass_name="api_platform_business_attestation_m17_qro_to_ir",
        validation_refs=("validation:business-attestation:m17",),
        evidence_refs=("evidence:business-attestation:m17",),
        environment_lock_ref="env:business-attestation:m17:v1",
        permission_ref="platform.business_attestation:m17:user_manual",
        deterministic_run_plan_ref="runplan:business-attestation:m17:v1",
        rollback_ref="rollback:business-attestation:m17:append_only_repair",
        tool_record_refs=(ENTRYPOINTS["M17"], "tool:business-attestation:m17"),
        node_refs=("qro:qro:business-attestation:m17", "execution_policy:m17"),
        canonical_command_refs=("business_command:m17",),
        lifecycle_refs=("lifecycle:business-attestation:m17",),
        rdp_refs=("rdp:business-attestation:m17",),
        theory_binding_refs=("theory_binding:business-attestation:m17",),
        consistency_check_refs=("consistency_check:business-attestation:m17",),
        mathematical_spine_chain_refs=(
            "math_spine_chain:business-attestation:m17",
        ),
        goal_sections=("§0", "§1", "§6", "§8", "§16"),
    )


def test_platform_business_attestation_compile_adapter_forwards_entire_compile_plan(
    monkeypatch,
) -> None:
    qro = _compile_qro()
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": qro},
        command_id="rgcmd:business-attestation:m17",
    )
    plan = _compile_plan()
    calls: list[dict[str, object]] = []
    expected_result = {
        "compiler_ir_ref": "compiler_ir:business-attestation:m17",
        "compiler_pass_ref": "compiler_pass:business-attestation:m17",
        "entrypoint_coverage_ref": "goal_entrypoint_coverage:business-attestation:m17",
    }

    def compile_entrypoint(**kwargs):
        calls.append(dict(kwargs))
        return expected_result

    monkeypatch.setattr(main, "_compile_entrypoint_qro", compile_entrypoint)

    assert main._compile_platform_business_attestation(qro, command, plan) == (
        expected_result
    )
    assert calls == [
        {
            "qro_id": qro.qro_id,
            "graph_command_id": command.command_id,
            "actor": plan.owner_user_id,
            "actor_source": "user_manual",
            "entry_source": "api",
            "entrypoint_ref": plan.entrypoint_ref,
            "pass_name": plan.pass_name,
            "validation_refs": plan.validation_refs,
            "evidence_refs": plan.evidence_refs,
            "environment_lock_ref": plan.environment_lock_ref,
            "permission_ref": plan.permission_ref,
            "deterministic_run_plan_ref": plan.deterministic_run_plan_ref,
            "rollback_ref": plan.rollback_ref,
            "tool_record_refs": plan.tool_record_refs,
            "node_refs": plan.node_refs,
            "canonical_command_refs": plan.canonical_command_refs,
            "lifecycle_refs": plan.lifecycle_refs,
            "rdp_refs": plan.rdp_refs,
            "theory_binding_refs": plan.theory_binding_refs,
            "consistency_check_refs": plan.consistency_check_refs,
            "mathematical_spine_chain_refs": plan.mathematical_spine_chain_refs,
            "goal_sections": plan.goal_sections,
        }
    ]


def test_platform_business_attestation_compile_adapter_rejects_qro_command_mismatch(
    monkeypatch,
) -> None:
    qro = _compile_qro()
    different_qro = _compile_qro(qro_id="qro:business-attestation:different")
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": different_qro},
        command_id="rgcmd:business-attestation:mismatch",
    )
    called = False

    def compile_entrypoint(**_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(main, "_compile_entrypoint_qro", compile_entrypoint)

    with pytest.raises(
        ValueError,
        match="platform business attestation QRO/command mismatch",
    ):
        main._compile_platform_business_attestation(qro, command, _compile_plan())
    assert called is False
