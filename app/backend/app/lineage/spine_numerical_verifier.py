"""Allowlisted server-side numerical verifiers for the canonical Mathematical Spine.

The caller selects a registered profile, but cannot supply executable code,
fixtures, an oracle, or a result.  Each profile binds one repository
implementation to one separately implemented numerical oracle.  This keeps a
server-produced ``pass`` narrower than a proof claim while making it stronger
than a structural/property-only check.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
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


DSR_NUMERICAL_PROFILE = "canonical_dsr_numerical_v1"
DSR_NUMERICAL_VERIFIER_REF = (
    "app/backend/app/lineage/spine_numerical_verifier.py::"
    + DSR_NUMERICAL_PROFILE
)
NUMERICAL_BINDING_VERIFICATION_STATE = "server_numerical_check"
_DSR_CODE_REF = "app/backend/app/eval/dsr.py:deflated_sharpe_ratio"
_DSR_FIXTURE_REF = DSR_NUMERICAL_VERIFIER_REF + "#deterministic-fixtures-v1"


def canonical_dsr_numerical_v1(
    *,
    binding: TheoryImplementationBinding,
    implementation: ImplementationSpec,
    theory: TheorySpec,
    artifact: MathematicalArtifact,
    owner: str,
    current_hash_resolver: Callable[[str, str, str], str | None],
) -> ConsistencyCheck:
    """Execute the registered DSR implementation against its independent oracle.

    The DSR implementation uses QuantBT's production estimator.  The oracle and
    deterministic fixtures live in ``app.eval.spine_bindings`` and recompute the
    definition through SciPy moments.  No part of either callable or its inputs
    comes from the request.
    """

    # Local import avoids turning the core lineage model into an eval import
    # cycle while retaining one fixed, inspectable verifier implementation.
    from ..eval.spine_bindings import (
        DSR_ARTIFACT,
        DSR_PINNED_FINGERPRINT,
        dsr_code_fingerprint,
        dsr_consistency_check,
    )

    failures: list[str] = []
    if artifact.artifact_id != DSR_ARTIFACT.artifact_id:
        failures.append("artifact is not the registered DSR mathematical definition")
    if theory.artifact_ref != artifact.artifact_id:
        failures.append("TheorySpec artifact_ref mismatch")
    if implementation.theory_ref != theory.theory_spec_id:
        failures.append("ImplementationSpec theory_ref mismatch")
    if implementation.code_ref != _DSR_CODE_REF:
        failures.append("ImplementationSpec code_ref is not the registered DSR implementation")
    if binding.implementation_ref != implementation.implementation_spec_id:
        failures.append("binding implementation_ref mismatch")
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
    if binding.consistency_verdict != NUMERICAL_BINDING_VERIFICATION_STATE:
        failures.append("binding verification state is not server numerical")
    if binding.verifier_ref != DSR_NUMERICAL_VERIFIER_REF:
        failures.append("binding verifier_ref is not the registered DSR numerical verifier")
    current_code_hash = current_hash_resolver("code", implementation.code_ref, owner)
    if not current_code_hash or current_code_hash != implementation.code_content_hash:
        failures.append("registered DSR code content hash is stale or unresolved")
    try:
        live_fingerprint = dsr_code_fingerprint()
    except (OSError, TypeError, ValueError) as exc:
        failures.append(f"registered DSR source fingerprint unavailable: {type(exc).__name__}")
    else:
        if live_fingerprint != DSR_PINNED_FINGERPRINT:
            failures.append("registered DSR implementation changed without verifier recertification")

    numerical: ConsistencyCheck | None = None
    if not failures:
        try:
            numerical = dsr_consistency_check(binding=binding)
        except Exception as exc:  # noqa: BLE001 - a verifier crash is a fail, never a pass.
            failures.append(f"registered DSR numerical verifier failed: {type(exc).__name__}")
        else:
            if numerical.result != CHECK_PASS:
                failures.append(numerical.failure_reason or "DSR numerical oracle mismatch")

    passed = not failures and numerical is not None
    return ConsistencyCheck(
        binding_id=binding.binding_id,
        check_type="numerical",
        result=CHECK_PASS if passed else CHECK_FAIL,
        input_refs=(
            implementation.code_ref,
            implementation.config_ref,
            implementation.data_contract_ref,
            _DSR_FIXTURE_REF,
        ),
        expected_property=(
            numerical.expected_property
            if numerical is not None
            else "registered DSR implementation matches the independent SciPy oracle"
        ),
        observed_property=(
            numerical.observed_property
            if passed and numerical is not None
            else "; ".join(failures)
        ),
        tolerance=(numerical.tolerance if numerical is not None else binding.tolerance),
        failure_reason="" if passed else "; ".join(failures),
        affected_assets=binding.used_by,
        repair_plan=(
            ""
            if passed
            else "repair or recertify the registered DSR implementation, then rerun this server profile"
        ),
        verifier_ref=DSR_NUMERICAL_VERIFIER_REF,
        timestamp=dt.datetime.now(dt.UTC).isoformat(),
    )


__all__ = [
    "DSR_NUMERICAL_PROFILE",
    "DSR_NUMERICAL_VERIFIER_REF",
    "NUMERICAL_BINDING_VERIFICATION_STATE",
    "canonical_dsr_numerical_v1",
]
