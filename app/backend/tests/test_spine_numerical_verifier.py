from __future__ import annotations

from dataclasses import replace

from app.eval.spine_bindings import DSR_ARTIFACT
from app.lineage.spine import (
    CHECK_FAIL,
    CHECK_PASS,
    ImplementationSpec,
    TheoryImplementationBinding,
    TheorySpec,
)
from app.lineage.spine_numerical_verifier import (
    DSR_NUMERICAL_VERIFIER_REF,
    NUMERICAL_BINDING_VERIFICATION_STATE,
    canonical_dsr_numerical_v1,
)


def _registered_chain():
    theory = TheorySpec(
        mathematical_requirement_ref="requirement:dsr:v1",
        artifact_ref=DSR_ARTIFACT.artifact_id,
        title="Deflated Sharpe Ratio",
        assumptions=DSR_ARTIFACT.assumptions,
        definitions=(DSR_ARTIFACT.definition,),
        derivation=DSR_ARTIFACT.derivation,
        proof_sketch=DSR_ARTIFACT.proof_sketch,
        counterexamples=DSR_ARTIFACT.counterexamples,
        applicability=DSR_ARTIFACT.applicability,
        failure_conditions=DSR_ARTIFACT.failure_conditions,
        proof_status=DSR_ARTIFACT.proof_status,
        used_by=("run:dsr-verifier",),
    )
    implementation = ImplementationSpec(
        theory_ref=theory.theory_spec_id,
        code_ref="app/backend/app/eval/dsr.py:deflated_sharpe_ratio",
        config_ref="qro:dsr-config",
        data_contract_ref="qro:pit-return-contract",
        code_content_hash="current-code-hash",
        config_content_hash="current-config-hash",
        data_contract_content_hash="current-contract-hash",
        symbol_mapping={"SR_pp": "period_sharpe"},
        unit_mapping={"DSR": "probability"},
        expected_properties=("implementation matches an independent numerical oracle",),
        test_refs=("app/backend/tests/test_spine_dsr_binding.py",),
        simulation_refs=("app/backend/tests/test_overfit_gate.py",),
        numerical_check_refs=(
            "app/backend/app/lineage/spine_numerical_verifier.py::canonical_dsr_numerical_v1",
        ),
    )
    binding = TheoryImplementationBinding(
        theory_ref=implementation.theory_ref,
        implementation_ref=implementation.implementation_spec_id,
        implementation_spec=implementation.implementation_spec_id,
        code_ref=implementation.code_ref,
        code_content_hash=implementation.code_content_hash,
        config_ref=implementation.config_ref,
        config_content_hash=implementation.config_content_hash,
        data_contract_ref=implementation.data_contract_ref,
        data_contract_content_hash=implementation.data_contract_content_hash,
        test_refs=implementation.test_refs,
        simulation_refs=implementation.simulation_refs,
        numerical_check_refs=implementation.numerical_check_refs,
        symbol_mapping=implementation.symbol_mapping,
        unit_mapping=implementation.unit_mapping,
        dimension_check="dimensionless probability",
        tolerance=1e-6,
        consistency_verdict=NUMERICAL_BINDING_VERIFICATION_STATE,
        verifier_ref=DSR_NUMERICAL_VERIFIER_REF,
        used_by=("run:dsr-verifier",),
    )
    return theory, implementation, binding


def test_registered_dsr_profile_executes_server_owned_numerical_oracle() -> None:
    theory, implementation, binding = _registered_chain()
    check = canonical_dsr_numerical_v1(
        binding=binding,
        implementation=implementation,
        theory=theory,
        artifact=DSR_ARTIFACT,
        owner="alice",
        current_hash_resolver=lambda kind, ref, owner: (
            implementation.code_content_hash
            if (kind, ref, owner) == ("code", implementation.code_ref, "alice")
            else None
        ),
    )

    assert check.result == CHECK_PASS
    assert check.check_type == "numerical"
    assert check.verifier_ref == DSR_NUMERICAL_VERIFIER_REF
    assert "oracle" in check.expected_property
    assert check.failure_reason == ""


def test_registered_dsr_profile_rejects_stale_code_before_oracle(monkeypatch) -> None:
    theory, implementation, binding = _registered_chain()

    def _must_not_run(**_kwargs):
        raise AssertionError("stale content must fail before numerical execution")

    monkeypatch.setattr("app.eval.spine_bindings.dsr_consistency_check", _must_not_run)
    check = canonical_dsr_numerical_v1(
        binding=binding,
        implementation=implementation,
        theory=theory,
        artifact=DSR_ARTIFACT,
        owner="alice",
        current_hash_resolver=lambda *_args: "different-code-hash",
    )

    assert check.result == CHECK_FAIL
    assert "stale or unresolved" in check.failure_reason


def test_registered_dsr_profile_rejects_relabelled_theory_for_same_code() -> None:
    theory, implementation, binding = _registered_chain()
    relabelled = replace(DSR_ARTIFACT, statement="This is not the registered DSR definition", artifact_id="")
    check = canonical_dsr_numerical_v1(
        binding=binding,
        implementation=implementation,
        theory=theory,
        artifact=relabelled,
        owner="alice",
        current_hash_resolver=lambda *_args: implementation.code_content_hash,
    )

    assert check.result == CHECK_FAIL
    assert "not the registered DSR mathematical definition" in check.failure_reason
