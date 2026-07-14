"""Registered server-side Mathematical Spine consistency verifiers.

The verifier in this module has a deliberately narrow claim: it checks the
canonical theory -> implementation binding, current content hashes, mappings,
and persisted validation references.  It does not claim to prove the theory or
replace an independent numerical oracle.
"""

from __future__ import annotations

import datetime as dt
from typing import Callable

from .spine import (
    CHECK_FAIL,
    CHECK_PASS,
    ConsistencyCheck,
    ImplementationSpec,
    MathematicalArtifact,
    TheoryImplementationBinding,
    TheorySpec,
)

VERIFIER_REF = (
    "app/backend/app/lineage/spine_verifier.py::canonical_binding_property_v1"
)
BINDING_VERIFICATION_STATE = "server_property_check"


def canonical_binding_property_v1(
    *,
    binding: TheoryImplementationBinding,
    implementation: ImplementationSpec,
    theory: TheorySpec,
    artifact: MathematicalArtifact,
    owner: str,
    external_ref_resolver: Callable[[str, str, str], bool],
    current_hash_resolver: Callable[[str, str, str], str | None],
) -> ConsistencyCheck:
    """Generate a server-owned property check for one canonical binding."""

    failures: list[str] = []
    if theory.artifact_ref != artifact.artifact_id:
        failures.append("TheorySpec artifact_ref mismatch")
    if implementation.theory_ref != theory.theory_spec_id:
        failures.append("ImplementationSpec theory_ref mismatch")
    for field_name in (
        "theory_ref",
        "code_ref",
        "config_ref",
        "data_contract_ref",
        "code_content_hash",
        "config_content_hash",
        "data_contract_content_hash",
    ):
        if str(getattr(binding, field_name) or "") != str(
            getattr(implementation, field_name) or ""
        ):
            failures.append(f"binding {field_name} mismatch")
    if binding.implementation_ref != implementation.implementation_spec_id:
        failures.append("binding implementation_ref mismatch")
    if binding.consistency_verdict != BINDING_VERIFICATION_STATE:
        failures.append("binding verification state is not server-owned")
    if binding.verifier_ref != VERIFIER_REF:
        failures.append("binding verifier_ref is not the registered verifier")
    for kind, ref_field, hash_field in (
        ("code", "code_ref", "code_content_hash"),
        ("config", "config_ref", "config_content_hash"),
        ("data_contract", "data_contract_ref", "data_contract_content_hash"),
    ):
        current_hash = current_hash_resolver(
            kind,
            str(getattr(binding, ref_field) or ""),
            owner,
        )
        if not current_hash or current_hash != str(getattr(binding, hash_field) or ""):
            failures.append(f"binding {hash_field} is stale or unresolved")
    for field_name in (
        "notation",
        "definition",
        "statement",
        "derivation",
        "units",
        "dimensions",
        "applicability",
    ):
        if not str(getattr(artifact, field_name) or "").strip():
            failures.append(f"artifact {field_name} missing")
    if not artifact.assumptions or not artifact.failure_conditions:
        failures.append("artifact assumptions/failure_conditions missing")
    theory_pairs = (
        ("assumptions", tuple(theory.assumptions), tuple(artifact.assumptions)),
        ("derivation", theory.derivation, artifact.derivation),
        ("proof_sketch", theory.proof_sketch, artifact.proof_sketch),
        ("counterexamples", tuple(theory.counterexamples), tuple(artifact.counterexamples)),
        ("applicability", theory.applicability, artifact.applicability),
        (
            "failure_conditions",
            tuple(theory.failure_conditions),
            tuple(artifact.failure_conditions),
        ),
        ("proof_status", theory.proof_status, artifact.proof_status),
        ("used_by", tuple(theory.used_by), tuple(artifact.used_by)),
    )
    for field_name, observed, expected in theory_pairs:
        if observed != expected:
            failures.append(f"theory/artifact {field_name} mismatch")
    if artifact.definition not in tuple(theory.definitions):
        failures.append("theory definitions do not contain artifact definition")
    if not implementation.expected_properties:
        failures.append("ImplementationSpec expected_properties missing")
    if not implementation.symbol_mapping or not implementation.unit_mapping:
        failures.append("ImplementationSpec symbol/unit mapping missing")
    if dict(binding.symbol_mapping) != dict(implementation.symbol_mapping):
        failures.append("binding symbol_mapping mismatch")
    if dict(binding.unit_mapping) != dict(implementation.unit_mapping):
        failures.append("binding unit_mapping mismatch")
    for field_name in ("test_refs", "simulation_refs", "numerical_check_refs"):
        if tuple(getattr(binding, field_name)) != tuple(
            getattr(implementation, field_name)
        ):
            failures.append(f"binding {field_name} mismatch")

    validation_refs = tuple(
        dict.fromkeys(
            (
                *binding.test_refs,
                *binding.simulation_refs,
                *binding.numerical_check_refs,
            )
        )
    )
    if not binding.test_refs or not binding.simulation_refs or not binding.numerical_check_refs:
        failures.append("binding test/simulation/numerical refs missing")
    for role in ("test_refs", "simulation_refs", "numerical_check_refs"):
        for ref in tuple(getattr(binding, role)):
            if not external_ref_resolver(role, str(ref), owner):
                failures.append(f"{role} unresolved: {ref}")
    if not external_ref_resolver("verifier_ref", VERIFIER_REF, owner):
        failures.append("registered verifier ref is not resolvable")

    passed = not failures
    return ConsistencyCheck(
        binding_id=binding.binding_id,
        check_type="property",
        result=CHECK_PASS if passed else CHECK_FAIL,
        input_refs=validation_refs,
        expected_property=(
            "canonical theory, artifact, implementation, hashes, mappings, and "
            "validation refs are mutually consistent"
        ),
        observed_property=(
            "all registered binding properties passed"
            if passed
            else "; ".join(failures)
        ),
        failure_reason="" if passed else "; ".join(failures),
        affected_assets=binding.used_by,
        repair_plan=(
            ""
            if passed
            else "repair canonical refs/mappings/evidence, then rerun the registered verifier"
        ),
        verifier_ref=VERIFIER_REF,
        timestamp=dt.datetime.now(dt.UTC).isoformat(),
    )


__all__ = [
    "BINDING_VERIFICATION_STATE",
    "VERIFIER_REF",
    "canonical_binding_property_v1",
]
