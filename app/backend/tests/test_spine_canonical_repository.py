from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.eval.spine_bindings import DSR_ARTIFACT
from app.lineage import content_hash
from app.lineage.spine import (
    CHECK_PASS,
    PROOF_BACKED,
    ConsistencyCheck,
    ImplementationSpec,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    ResponsibilityDisclosureRecord,
    TheoryImplementationBinding,
    TheorySpec,
)
from app.lineage.spine_ledger import (
    CanonicalSpinePackage,
    SpineLedger,
    SpineMirrorPendingError,
)
from app.lineage.spine_numerical_verifier import (
    DSR_NUMERICAL_PROFILE,
    DSR_NUMERICAL_VERIFIER_REF,
)
from app.research_os.spine import (
    MathematicalSpineChainRecord,
    PersistentMathematicalSpineChainRegistry,
)


def _canonical_package():
    artifact = MathematicalArtifact(
        artifact_type="execution_cost",
        notation="C(q)=fee+slippage+impact+funding+borrow",
        assumptions=("finite notional",),
        definition="all-in execution cost per fill and holding interval",
        statement="C(q) decomposes observed execution economics",
        derivation="sum mutually disclosed cost components in quote currency",
        proof_sketch="dimensional decomposition",
        counterexamples=("missing funding attribution",),
        units="quote_currency",
        dimensions="currency",
        applicability="crypto perpetual fills",
        failure_conditions=("unattributed borrow or funding",),
        proof_status=PROOF_BACKED,
        test_ref="tests:test_cost_model",
        simulation_ref="simulation:cost_model:v1",
        validation_ref="validation:cost_model:v1",
        used_by=("execution_policy:btc:v1", "monitor:cost_drift:v1"),
    )
    theory = TheorySpec(
        mathematical_requirement_ref="math_requirement:all_in_cost:v1",
        artifact_ref=artifact.artifact_id,
        title="All-in execution cost",
        assumptions=artifact.assumptions,
        definitions=(artifact.definition,),
        derivation=artifact.derivation,
        proof_sketch=artifact.proof_sketch,
        counterexamples=artifact.counterexamples,
        applicability=artifact.applicability,
        failure_conditions=artifact.failure_conditions,
        proof_status=artifact.proof_status,
        evidence_refs=("evidence:cost_definition:v1",),
        validation_refs=(artifact.validation_ref,),
        used_by=artifact.used_by,
    )
    code_hash = content_hash("def all_in_cost(fill, holding): ...")
    config_hash = content_hash({"fee_schedule": "binance_um_v1"})
    data_hash = content_hash({"known_at": "event_time", "effective_at": "event_time"})
    implementation = ImplementationSpec(
        theory_ref=theory.theory_spec_id,
        code_ref="app/execution/cost.py:all_in_cost",
        config_ref="config:fee_schedule:binance_um_v1",
        data_contract_ref="contract:execution_fill_pit:v1",
        code_content_hash=code_hash,
        config_content_hash=config_hash,
        data_contract_content_hash=data_hash,
        entrypoint_ref="execution:fill_economics",
        symbol_mapping={"q": "fill.quantity"},
        unit_mapping={"C": "quote_currency"},
        expected_properties=("all components use one quote currency",),
        test_refs=("tests:test_cost_model",),
        simulation_refs=("simulation:cost_model:v1",),
        numerical_check_refs=("numerical:cost_fixture:v1",),
        run_config_refs=("run_config:paper_btc:v1",),
        monitor_refs=("monitor:cost_drift:v1",),
    )
    binding = TheoryImplementationBinding(
        theory_ref=theory.theory_spec_id,
        implementation_ref=implementation.implementation_spec_id,
        implementation_spec=implementation.implementation_spec_id,
        code_ref=implementation.code_ref,
        code_content_hash=code_hash,
        config_ref=implementation.config_ref,
        config_content_hash=config_hash,
        data_contract_ref=implementation.data_contract_ref,
        data_contract_content_hash=data_hash,
        test_refs=implementation.test_refs,
        simulation_refs=implementation.simulation_refs,
        numerical_check_refs=implementation.numerical_check_refs,
        symbol_mapping=implementation.symbol_mapping,
        unit_mapping=implementation.unit_mapping,
        dimension_check="currency == currency",
        tolerance=1e-9,
        consistency_verdict=CHECK_PASS,
        verifier_ref="verifier:cost:v1",
        used_by=artifact.used_by,
    )
    check = ConsistencyCheck(
        binding_id=binding.binding_id,
        check_type="numerical",
        result=CHECK_PASS,
        input_refs=("fixture:fill_cost:v1",),
        expected_property="fee+slippage+funding=2.5",
        observed_property="2.5",
        tolerance=1e-9,
        affected_assets=artifact.used_by,
        verifier_ref="verifier:cost:v1",
        timestamp="2026-07-12T12:00:00+00:00",
    )
    choice = MethodologyChoiceRecord(
        chosen_path="strict",
        asset_ref=artifact.artifact_id,
        run_ref="run:paper_btc:v1",
        available_options=("strict", "standard", "exploratory"),
        recommendation="strict",
        tradeoffs_shown=("higher validation cost",),
        risks_shown=("cost attribution can remain incomplete",),
        responsibility_boundary="system verifies refs; user owns methodology choice",
        actor="alice",
        timestamp="2026-07-12T12:00:00+00:00",
        allowed_environment="paper",
        display_label="strict methodology",
    )
    responsibility = ResponsibilityDisclosureRecord(
        asset_ref=artifact.artifact_id,
        run_ref="run:paper_btc:v1",
        responsibility_boundary=choice.responsibility_boundary,
        risks_disclosed=choice.risks_shown,
        risk_owner="alice",
        recommendation=choice.recommendation,
        alternatives=choice.available_options,
        costs_disclosed=choice.tradeoffs_shown,
        actor="alice",
        timestamp=choice.timestamp,
        allowed_environment=choice.allowed_environment,
        methodology_choice_ref=choice.choice_id,
    )
    return artifact, theory, implementation, binding, check, choice, responsibility


def _record_package(ledger: SpineLedger, *, owner: str = "alice"):
    artifact, theory, implementation, binding, check, choice, responsibility = (
        _canonical_package()
    )
    ledger.record_package(
        CanonicalSpinePackage(
            artifacts=(artifact,),
            theory_specs=(theory,),
            implementation_specs=(implementation,),
            bindings=(binding,),
            checks=(check,),
            choices=(choice,),
            responsibilities=(responsibility,),
        ),
        owner=owner,
    )
    return artifact, theory, implementation, binding, check, choice, responsibility


def _draft_api_payload(tmp_path):
    artifact, theory, _implementation, _binding, check, choice, responsibility = (
        _canonical_package()
    )
    code_path = tmp_path / "implementation.py"
    config_path = tmp_path / "config.json"
    data_path = tmp_path / "data_contract.json"
    code_path.write_text("def implementation(x):\n    return x\n", encoding="utf-8")
    config_path.write_text('{"mode":"paper"}\n', encoding="utf-8")
    data_path.write_text('{"known_at":"event_time"}\n', encoding="utf-8")
    implementation = ImplementationSpec(
        theory_ref=theory.theory_spec_id,
        code_ref=code_path.name,
        config_ref=config_path.name,
        data_contract_ref=data_path.name,
        code_content_hash=content_hash(code_path.read_text(encoding="utf-8")),
        config_content_hash=content_hash(config_path.read_text(encoding="utf-8")),
        data_contract_content_hash=content_hash(data_path.read_text(encoding="utf-8")),
        test_refs=(code_path.name,),
        simulation_refs=(config_path.name,),
        numerical_check_refs=(data_path.name,),
    )
    binding = TheoryImplementationBinding(
        theory_ref=theory.theory_spec_id,
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
        consistency_verdict="pending",
    )
    pending_check = replace(
        check,
        binding_id=binding.binding_id,
        result="pending",
        observed_property="not yet verified",
        verifier_ref="",
        check_id="",
    )
    return {
        "artifacts": [asdict(artifact)],
        "theory_specs": [asdict(theory)],
        "implementation_specs": [asdict(implementation)],
        "bindings": [asdict(binding)],
        "checks": [asdict(pending_check)],
        "choices": [asdict(choice)],
        "responsibilities": [asdict(responsibility)],
    }


def _server_property_api_payload(tmp_path, *, owner: str = "alice-id"):
    payload = _draft_api_payload(tmp_path)
    payload.pop("checks")

    implementation_raw = dict(payload["implementation_specs"][0])
    implementation_raw.update(
        {
            "implementation_spec_id": "",
            "symbol_mapping": {"x": "input.x"},
            "unit_mapping": {"x": "unitless"},
            "expected_properties": ["implementation preserves x"],
        }
    )
    implementation = ImplementationSpec(**implementation_raw)
    payload["implementation_specs"] = [asdict(implementation)]

    binding_raw = dict(payload["bindings"][0])
    binding_raw.update(
        {
            "binding_id": "",
            "implementation_ref": implementation.implementation_spec_id,
            "implementation_spec": implementation.implementation_spec_id,
            "theory_ref": implementation.theory_ref,
            "code_ref": implementation.code_ref,
            "code_content_hash": implementation.code_content_hash,
            "config_ref": implementation.config_ref,
            "config_content_hash": implementation.config_content_hash,
            "data_contract_ref": implementation.data_contract_ref,
            "data_contract_content_hash": implementation.data_contract_content_hash,
            "symbol_mapping": implementation.symbol_mapping,
            "unit_mapping": implementation.unit_mapping,
            "test_refs": list(implementation.test_refs),
            "simulation_refs": list(implementation.simulation_refs),
            "numerical_check_refs": list(implementation.numerical_check_refs),
            "consistency_verdict": "",
            "verifier_ref": "",
        }
    )
    payload["bindings"] = [asdict(TheoryImplementationBinding(**binding_raw))]

    choice_raw = dict(payload["choices"][0])
    choice_raw.update({"actor": owner, "choice_id": ""})
    choice = MethodologyChoiceRecord(**choice_raw)
    payload["choices"] = [asdict(choice)]
    responsibility_raw = dict(payload["responsibilities"][0])
    responsibility_raw.update(
        {
            "actor": owner,
            "risk_owner": owner,
            "methodology_choice_ref": choice.choice_id,
            "disclosure_id": "",
        }
    )
    payload["responsibilities"] = [
        asdict(ResponsibilityDisclosureRecord(**responsibility_raw))
    ]
    return payload


def _server_numerical_api_payload(*, owner: str = "alice-id"):
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
        evidence_refs=("app/backend/tests/test_spine_dsr_binding.py",),
        validation_refs=("app/backend/tests/test_overfit_gate.py",),
        used_by=DSR_ARTIFACT.used_by,
    )
    code_ref = "app/backend/app/eval/dsr.py:deflated_sharpe_ratio"
    config_ref = "app/backend/app/eval/spine_bindings.py"
    data_contract_ref = "app/backend/app/eval/spine_bindings.py"
    implementation = ImplementationSpec(
        theory_ref=theory.theory_spec_id,
        code_ref=code_ref,
        config_ref=config_ref,
        data_contract_ref=data_contract_ref,
        code_content_hash=main._canonical_spine_current_hash_resolver(
            "code", code_ref, owner
        )
        or "",
        config_content_hash=main._canonical_spine_current_hash_resolver(
            "config", config_ref, owner
        )
        or "",
        data_contract_content_hash=main._canonical_spine_current_hash_resolver(
            "data_contract", data_contract_ref, owner
        )
        or "",
        entrypoint_ref=code_ref,
        symbol_mapping={"SR_pp": "period_sharpe"},
        unit_mapping={"DSR": "probability"},
        expected_properties=(
            "implementation matches an independent numerical oracle",
        ),
        test_refs=("app/backend/tests/test_spine_dsr_binding.py",),
        simulation_refs=("app/backend/tests/test_overfit_gate.py",),
        numerical_check_refs=(
            "app/backend/app/lineage/spine_numerical_verifier.py",
        ),
    )
    binding = TheoryImplementationBinding(
        theory_ref=theory.theory_spec_id,
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
        used_by=DSR_ARTIFACT.used_by,
    )
    choice = MethodologyChoiceRecord(
        chosen_path="strict",
        asset_ref=DSR_ARTIFACT.artifact_id,
        run_ref="run:dsr-verifier:v1",
        available_options=("strict", "exploratory"),
        recommendation="strict",
        tradeoffs_shown=("fixed profile only",),
        risks_shown=("numerical agreement is not a proof",),
        responsibility_boundary="server owns verifier; user owns methodology choice",
        actor=owner,
        timestamp="2026-07-13T12:00:00+00:00",
        allowed_environment="paper",
        display_label="strict methodology",
    )
    responsibility = ResponsibilityDisclosureRecord(
        asset_ref=DSR_ARTIFACT.artifact_id,
        run_ref=choice.run_ref,
        responsibility_boundary=choice.responsibility_boundary,
        risks_disclosed=choice.risks_shown,
        risk_owner=owner,
        recommendation=choice.recommendation,
        alternatives=choice.available_options,
        costs_disclosed=choice.tradeoffs_shown,
        actor=owner,
        timestamp=choice.timestamp,
        allowed_environment=choice.allowed_environment,
        methodology_choice_ref=choice.choice_id,
    )
    return {
        "verifier_profile": DSR_NUMERICAL_PROFILE,
        "package": {
            "artifacts": [asdict(DSR_ARTIFACT)],
            "theory_specs": [asdict(theory)],
            "implementation_specs": [asdict(implementation)],
            "bindings": [asdict(binding)],
            "choices": [asdict(choice)],
            "responsibilities": [asdict(responsibility)],
        },
    }


def test_canonical_spine_repository_wal_reopen_and_full_payload(tmp_path):
    ledger = SpineLedger(tmp_path)
    package = _record_package(ledger)
    assert ledger.journal_mode() == "wal"
    assert ledger.verify_chain() == (True, [])
    ledger.close()

    reopened = SpineLedger(tmp_path)
    artifact, theory, implementation, binding, check, choice, responsibility = package
    assert reopened.artifact(artifact.artifact_id, owner="alice") == artifact
    assert reopened.theory_spec(theory.theory_spec_id, owner="alice") == theory
    assert reopened.implementation_spec(
        implementation.implementation_spec_id, owner="alice"
    ) == implementation
    assert reopened.binding(binding.binding_id, owner="alice") == binding
    assert reopened.check(check.check_id, owner="alice") == check
    assert reopened.choice(choice.choice_id, owner="alice") == choice
    assert reopened.responsibility(responsibility.disclosure_id, owner="alice") == responsibility
    assert reopened.verify_chain() == (True, [])


def test_canonical_spine_package_is_atomic_on_late_parent_failure(tmp_path):
    ledger = SpineLedger(tmp_path)
    artifact, theory, implementation, binding, check, choice, responsibility = (
        _canonical_package()
    )
    bad_binding = replace(
        binding,
        implementation_ref="implspec_missing",
        implementation_spec="implspec_missing",
        binding_id="",
    )
    bad_check = replace(
        check,
        binding_id=bad_binding.binding_id,
        check_id="",
    )
    package = CanonicalSpinePackage(
        artifacts=(artifact,),
        theory_specs=(theory,),
        implementation_specs=(implementation,),
        bindings=(bad_binding,),
        checks=(bad_check,),
        choices=(choice,),
        responsibilities=(responsibility,),
    )

    with pytest.raises(ValueError, match="bindings must exactly cover"):
        ledger.record_package(package, owner="alice")

    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM spine_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM spine_audit_events").fetchone()[0] == 0
    assert not ledger.mirror_path.exists()


def test_canonical_spine_audit_uses_full_sha256_hashes(tmp_path):
    ledger = SpineLedger(tmp_path)
    _record_package(ledger)

    with sqlite3.connect(ledger.db_path) as conn:
        rows = conn.execute(
            "SELECT payload_hash, event_id FROM spine_audit_events"
        ).fetchall()
    assert rows
    assert all(len(payload_hash) == 64 and len(event_id) == 64 for payload_hash, event_id in rows)
    mirror_rows = [
        __import__("json").loads(line)
        for line in ledger.mirror_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(
        len(row["payload_hash"]) == 64 and len(row["row_hash"]) == 64
        for row in mirror_rows
    )


def test_canonical_spine_api_records_unverified_draft_atomically(tmp_path, monkeypatch):
    ledger = SpineLedger(tmp_path / "ledger")
    monkeypatch.setattr(main, "CANONICAL_SPINE_LEDGER", ledger)
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice-display",
        user_id="alice-id",
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/spine/packages",
            json=_draft_api_payload(tmp_path),
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200, response.text
    assert response.json()["verification_state"] == "unverified_draft"
    assert response.json()["strict_chain_eligible"] is False
    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM spine_records").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM spine_audit_events").fetchone()[0] == 7
    assert ledger.verify_chain() == (True, [])


def test_canonical_spine_api_rejects_caller_pass_without_partial_rows(tmp_path, monkeypatch):
    ledger = SpineLedger(tmp_path / "ledger")
    monkeypatch.setattr(main, "CANONICAL_SPINE_LEDGER", ledger)
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    payload = _draft_api_payload(tmp_path)
    payload["checks"][0]["result"] = "pass"
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice-display",
        user_id="alice-id",
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/spine/packages",
            json=payload,
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 422
    assert "caller-submitted ConsistencyCheck pass is forbidden" in response.json()["detail"]
    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM spine_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM spine_audit_events").fetchone()[0] == 0


def test_canonical_spine_server_property_check_is_generated_and_narrow(
    tmp_path,
    monkeypatch,
):
    ledger = SpineLedger(tmp_path / "ledger")
    monkeypatch.setattr(main, "CANONICAL_SPINE_LEDGER", ledger)
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice-display",
        user_id="alice-id",
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/spine/packages/server-property-check",
            json=_server_property_api_payload(tmp_path),
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification_state"] == "server_property_check_passed"
    assert body["strict_chain_eligible"] is False
    assert "not a mathematical proof" in body["verification_scope"]
    assert len(body["check_refs"]) == 1
    check = ledger.check(body["check_refs"][0], owner="alice-id")
    assert check.result == "pass"
    assert check.check_type == "property"
    assert check.verifier_ref.endswith("::canonical_binding_property_v1")


@pytest.mark.parametrize(
    ("mutator", "expected"),
    (
        (lambda payload: payload.__setitem__("checks", []), "caller-supplied checks"),
        (
            lambda payload: payload["bindings"][0].__setitem__(
                "consistency_verdict", "caller_claim"
            ),
            "consistency_verdict/verifier_ref",
        ),
        (
            lambda payload: payload["bindings"][0].__setitem__(
                "verifier_ref", "app/backend/app/lineage/spine_verifier.py::not_registered"
            ),
            "consistency_verdict/verifier_ref",
        ),
    ),
)
def test_canonical_spine_server_property_check_rejects_caller_provenance(
    tmp_path,
    monkeypatch,
    mutator,
    expected,
):
    ledger = SpineLedger(tmp_path / "ledger")
    monkeypatch.setattr(main, "CANONICAL_SPINE_LEDGER", ledger)
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    payload = _server_property_api_payload(tmp_path)
    mutator(payload)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice-display",
        user_id="alice-id",
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/spine/packages/server-property-check",
            json=payload,
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 422
    assert expected in response.json()["detail"]
    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM spine_records").fetchone()[0] == 0


def test_canonical_spine_server_property_failure_persists_as_fail(
    tmp_path,
    monkeypatch,
):
    ledger = SpineLedger(tmp_path / "ledger")
    monkeypatch.setattr(main, "CANONICAL_SPINE_LEDGER", ledger)
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    payload = _server_property_api_payload(tmp_path)
    implementation_raw = dict(payload["implementation_specs"][0])
    implementation_raw.update({"implementation_spec_id": "", "expected_properties": []})
    implementation = ImplementationSpec(**implementation_raw)
    payload["implementation_specs"] = [asdict(implementation)]
    binding_raw = dict(payload["bindings"][0])
    binding_raw.update(
        {
            "binding_id": "",
            "implementation_ref": implementation.implementation_spec_id,
            "implementation_spec": implementation.implementation_spec_id,
        }
    )
    payload["bindings"] = [asdict(TheoryImplementationBinding(**binding_raw))]
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice-display",
        user_id="alice-id",
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/spine/packages/server-property-check",
            json=payload,
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification_state"] == "server_property_check_failed"
    assert body["strict_chain_eligible"] is False
    check = ledger.check(body["check_refs"][0], owner="alice-id")
    assert check.result == "fail"
    assert "expected_properties missing" in check.failure_reason


def test_canonical_spine_server_numerical_check_runs_fixed_dsr_profile(
    tmp_path,
    monkeypatch,
):
    ledger = SpineLedger(tmp_path / "ledger")
    monkeypatch.setattr(main, "CANONICAL_SPINE_LEDGER", ledger)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice-display",
        user_id="alice-id",
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/spine/packages/server-numerical-check",
            json=_server_numerical_api_payload(),
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification_profile"] == DSR_NUMERICAL_PROFILE
    assert body["verification_state"] == "server_numerical_check_passed"
    assert body["strict_chain_eligible"] is False
    assert "not a proof" in body["verification_scope"]
    check = ledger.check(body["check_refs"][0], owner="alice-id")
    assert check.result == "pass"
    assert check.check_type == "numerical"
    assert check.verifier_ref == DSR_NUMERICAL_VERIFIER_REF


@pytest.mark.parametrize(
    ("mutator", "expected"),
    (
        (
            lambda payload: payload.__setitem__(
                "verifier_profile", "caller_supplied_profile"
            ),
            "unknown server numerical verifier profile",
        ),
        (
            lambda payload: payload["package"].__setitem__("checks", []),
            "caller-supplied checks",
        ),
        (
            lambda payload: payload["package"]["bindings"][0].__setitem__(
                "verifier_ref", DSR_NUMERICAL_VERIFIER_REF
            ),
            "consistency_verdict/verifier_ref",
        ),
    ),
)
def test_canonical_spine_server_numerical_rejects_caller_authority_without_rows(
    tmp_path,
    monkeypatch,
    mutator,
    expected,
):
    ledger = SpineLedger(tmp_path / "ledger")
    monkeypatch.setattr(main, "CANONICAL_SPINE_LEDGER", ledger)
    payload = _server_numerical_api_payload()
    mutator(payload)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice-display",
        user_id="alice-id",
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/spine/packages/server-numerical-check",
            json=payload,
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 422
    assert expected in response.json()["detail"]
    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM spine_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM spine_audit_events").fetchone()[0] == 0


def test_canonical_spine_rejects_forged_identity_without_rows(tmp_path):
    ledger = SpineLedger(tmp_path)
    artifact = _canonical_package()[0]
    forged = replace(artifact, artifact_id="math_forged")

    with pytest.raises(ValueError, match="identity mismatch"):
        ledger.record_artifact(forged, owner="alice")

    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM spine_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM spine_audit_events").fetchone()[0] == 0
    assert ledger.verify_chain() == (True, [])


def test_canonical_spine_parentage_and_owner_are_fail_closed(tmp_path):
    ledger = SpineLedger(tmp_path)
    artifact, _theory, _implementation, binding, check, *_rest = _canonical_package()
    ledger.record_artifact(artifact, owner="alice")

    with pytest.raises(ValueError, match="theory_ref is not recorded for owner"):
        ledger.record_binding(binding, owner="bob")
    with pytest.raises(ValueError, match="binding_id is not recorded for owner"):
        ledger.record_check(check, owner="alice")
    with pytest.raises(KeyError):
        ledger.artifact(artifact.artifact_id, owner="bob")


def test_canonical_spine_mirror_failure_is_explicit_and_retry_repairs(tmp_path):
    ledger = SpineLedger(tmp_path)
    artifact = _canonical_package()[0]
    real_mirror = ledger.mirror_path
    blocked = tmp_path / "blocked_mirror"
    blocked.mkdir()
    ledger._mirror_path = blocked

    with pytest.raises(SpineMirrorPendingError, match="committed"):
        ledger.record_artifact(artifact, owner="alice")
    assert ledger.artifact(artifact.artifact_id, owner="alice") == artifact

    ledger._mirror_path = real_mirror
    assert ledger.sync_audit_mirror() == 1
    assert ledger.sync_audit_mirror() == 0
    assert ledger.verify_chain() == (True, [])


def test_canonical_spine_concurrent_exact_retry_creates_one_event(tmp_path):
    ledger = SpineLedger(tmp_path)
    artifact = _canonical_package()[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = list(
            pool.map(
                lambda _index: ledger.record_artifact(artifact, owner="alice"),
                range(16),
            )
        )

    assert refs == [artifact.artifact_id] * 16
    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM spine_records").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM spine_audit_events").fetchone()[0] == 1
    assert ledger.verify_chain() == (True, [])


def test_required_field_mutation_changes_complete_content_identity():
    artifact, theory, implementation, binding, check, choice, responsibility = (
        _canonical_package()
    )
    mutations = (
        (artifact.artifact_id, replace(artifact, dimensions="dimensionless", artifact_id="").artifact_id),
        (theory.theory_spec_id, replace(theory, derivation="changed", theory_spec_id="").theory_spec_id),
        (
            implementation.implementation_spec_id,
            replace(implementation, config_content_hash="changed", implementation_spec_id="").implementation_spec_id,
        ),
        (binding.binding_id, replace(binding, tolerance=1e-6, binding_id="").binding_id),
        (check.check_id, replace(check, input_refs=("fixture:changed",), check_id="").check_id),
        (choice.choice_id, replace(choice, risks_shown=("changed",), choice_id="").choice_id),
        (
            responsibility.disclosure_id,
            replace(responsibility, costs_disclosed=("changed",), disclosure_id="").disclosure_id,
        ),
    )
    assert all(original != mutated for original, mutated in mutations)


def test_strict_chain_is_server_derived_and_revalidated(tmp_path):
    ledger = SpineLedger(tmp_path / "ledger")
    stage_refs = {
        "data_semantics_ref": "qro:data",
        "factor_ref": "qro:factor",
        "model_ref": "qro:model",
        "forecast_ref": "qro:forecast",
        "signal_contract_ref": "qro:signal",
        "strategy_book_ref": "qro:strategy",
        "portfolio_policy_ref": "qro:portfolio",
        "risk_policy_ref": "qro:risk",
        "execution_policy_ref": "qro:execution",
        "backtest_run_ref": "qro:backtest",
        "attribution_ref": "qro:attribution",
        "monitor_ref": "qro:monitor",
    }
    all_stages = tuple(stage_refs.values())

    def add_bound_artifact(kind: str, used_by: tuple[str, ...]):
        artifact = MathematicalArtifact(
            artifact_type=kind,
            statement=f"{kind} statement",
            definition=f"{kind} definition",
            derivation=f"{kind} derivation",
            assumptions=("PIT inputs",),
            applicability="paper and testnet",
            failure_conditions=("stale implementation",),
            proof_status=PROOF_BACKED,
            used_by=used_by,
        )
        ledger.record_artifact(artifact, owner="alice")
        theory = TheorySpec(
            mathematical_requirement_ref=f"requirement:{kind}",
            artifact_ref=artifact.artifact_id,
            definitions=(artifact.definition,),
            assumptions=artifact.assumptions,
            derivation=artifact.derivation,
            applicability=artifact.applicability,
            failure_conditions=artifact.failure_conditions,
            proof_status=PROOF_BACKED,
            used_by=used_by,
        )
        ledger.record_theory_spec(theory, owner="alice")
        code_ref = f"code:{kind}"
        config_ref = f"config:{kind}"
        data_ref = f"data:{kind}"
        hashes = {
            "code": content_hash(code_ref),
            "config": content_hash(config_ref),
            "data_contract": content_hash(data_ref),
        }
        implementation = ImplementationSpec(
            theory_ref=theory.theory_spec_id,
            code_ref=code_ref,
            config_ref=config_ref,
            data_contract_ref=data_ref,
            code_content_hash=hashes["code"],
            config_content_hash=hashes["config"],
            data_contract_content_hash=hashes["data_contract"],
            test_refs=(f"test:{kind}",),
            simulation_refs=(f"simulation:{kind}",),
            numerical_check_refs=(f"numerical:{kind}",),
        )
        ledger.record_implementation_spec(implementation, owner="alice")
        binding = TheoryImplementationBinding(
            theory_ref=theory.theory_spec_id,
            implementation_ref=implementation.implementation_spec_id,
            implementation_spec=implementation.implementation_spec_id,
            code_ref=code_ref,
            code_content_hash=hashes["code"],
            config_ref=config_ref,
            config_content_hash=hashes["config"],
            data_contract_ref=data_ref,
            data_contract_content_hash=hashes["data_contract"],
            test_refs=implementation.test_refs,
            simulation_refs=implementation.simulation_refs,
            numerical_check_refs=implementation.numerical_check_refs,
            consistency_verdict=CHECK_PASS,
            verifier_ref=f"verifier:{kind}",
            used_by=used_by,
        )
        ledger.record_binding(binding, owner="alice")
        check = ConsistencyCheck(
            binding_id=binding.binding_id,
            check_type="numerical",
            result=CHECK_PASS,
            input_refs=(f"fixture:{kind}",),
            expected_property="expected",
            observed_property="expected",
            verifier_ref=f"verifier:{kind}",
        )
        ledger.record_check(check, owner="alice")
        return binding, check, hashes

    artifact_specs = (
        ("data_timing", (stage_refs["data_semantics_ref"],)),
        ("factor_formula", (stage_refs["factor_ref"],)),
        ("loss_function", (stage_refs["model_ref"],)),
        ("estimator", (stage_refs["forecast_ref"], stage_refs["backtest_run_ref"])),
        ("signal_transform", (stage_refs["signal_contract_ref"],)),
        ("payoff_definition", (stage_refs["strategy_book_ref"],)),
        ("portfolio_objective", (stage_refs["portfolio_policy_ref"],)),
        ("risk_measure", (stage_refs["risk_policy_ref"],)),
        ("execution_cost", (stage_refs["execution_policy_ref"],)),
        ("attribution_decomposition", (stage_refs["attribution_ref"],)),
        ("monitor_trigger", (stage_refs["monitor_ref"],)),
    )
    bound = {
        kind: add_bound_artifact(kind, used_by)
        for kind, used_by in artifact_specs
    }
    execution_binding, execution_check, execution_hashes = bound["execution_cost"]
    choice = MethodologyChoiceRecord(
        chosen_path="strict",
        asset_ref=stage_refs["strategy_book_ref"],
        available_options=("strict", "standard"),
        recommendation="strict",
        tradeoffs_shown=("more tests",),
        risks_shown=("residual model risk",),
        responsibility_boundary="system verifies refs; user chooses methodology",
        actor="alice",
        allowed_environment="paper",
    )
    ledger.record_choice(choice, owner="alice")
    responsibility = ResponsibilityDisclosureRecord(
        asset_ref=choice.asset_ref,
        responsibility_boundary=choice.responsibility_boundary,
        risks_disclosed=choice.risks_shown,
        risk_owner="alice",
        actor="alice",
        allowed_environment="paper",
        methodology_choice_ref=choice.choice_id,
    )
    ledger.record_responsibility(responsibility, owner="alice")
    current_hashes = {
        (kind_name, str(getattr(binding, ref_field))): hashes[kind_name]
        for binding, _check, hashes in bound.values()
        for kind_name, ref_field in (
            ("code", "code_ref"),
            ("config", "config_ref"),
            ("data_contract", "data_contract_ref"),
        )
    }
    registry = PersistentMathematicalSpineChainRegistry(
        tmp_path / "chains.jsonl",
        ledger,
        external_ref_resolver=lambda _role, _ref, owner: owner == "alice",
        current_hash_resolver=lambda kind, ref, owner: (
            current_hashes.get((kind, ref)) if owner == "alice" else None
        ),
    )
    candidate = MathematicalSpineChainRecord(
        chain_ref="caller:forged",
        **stage_refs,
        theory_binding_refs=tuple(
            binding.binding_id for binding, _check, _hashes in bound.values()
        ),
        consistency_check_refs=tuple(
            check.check_id for _binding, check, _hashes in bound.values()
        ),
        methodology_choice_ref=choice.choice_id,
        responsibility_boundary_ref=responsibility.disclosure_id,
        evidence_refs=("evidence:chain",),
        validation_refs=("validation:chain",),
        consistency_verdict="caller_accepted",
        target_runtime="paper",
        recorded_by="alice",
    )

    property_only_check = replace(
        execution_check,
        check_type="property",
        check_id="",
    )
    ledger.record_check(property_only_check, owner="alice")
    property_only_candidate = replace(
        candidate,
        chain_ref="",
        consistency_check_refs=tuple(
            property_only_check.check_id if check.check_id == execution_check.check_id else check.check_id
            for _binding, check, _hashes in bound.values()
        ),
    )
    with pytest.raises(ValueError, match="executed_check_missing"):
        registry.record_chain(property_only_candidate)

    recorded = registry.record_chain(candidate)

    assert recorded.chain_ref.startswith("math_spine_chain_")
    assert recorded.chain_ref != candidate.chain_ref
    assert recorded.consistency_verdict == "accepted"
    assert ledger.chain(recorded.chain_ref, owner="alice") == recorded
    assert not registry.path.exists() or not registry.path.read_text(encoding="utf-8").strip()
    assert registry.record_chain(candidate) == recorded
    with sqlite3.connect(ledger.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM spine_records WHERE record_type='mathematical_spine_chain'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM spine_audit_events WHERE record_type='mathematical_spine_chain'"
        ).fetchone()[0] == 1
    reopened_ledger = SpineLedger(tmp_path / "ledger")
    reopened_registry = PersistentMathematicalSpineChainRegistry(
        registry.path,
        reopened_ledger,
        external_ref_resolver=lambda _role, _ref, owner: owner == "alice",
        current_hash_resolver=lambda kind, ref, owner: (
            current_hashes.get((kind, ref)) if owner == "alice" else None
        ),
    )
    assert reopened_registry.verified_chain(recorded.chain_ref, owner="alice") == recorded
    reopened_ledger.close()
    assert registry.verified_chain(recorded.chain_ref, owner="alice") == recorded
    closure = registry.verified_chain_record_refs(recorded.chain_ref, owner="alice")
    assert set(closure.theory_binding_refs) == {
        binding.binding_id for binding, _check, _hashes in bound.values()
    }
    assert set(closure.consistency_check_refs) == {
        check.check_id for _binding, check, _hashes in bound.values()
    }
    assert closure.methodology_choice_refs == (choice.choice_id,)
    assert closure.responsibility_refs == (responsibility.disclosure_id,)
    with pytest.raises(KeyError):
        registry.verified_chain(recorded.chain_ref, owner="bob")

    registry._chains["math_spine_chain_alias"] = recorded
    with pytest.raises(KeyError):
        registry.verified_chain("math_spine_chain_alias", owner="alice")

    current_hashes[("code", execution_binding.code_ref)] = "stale"
    with pytest.raises(ValueError, match="current_hash_mismatch"):
        registry.verified_chain(recorded.chain_ref, owner="alice")
