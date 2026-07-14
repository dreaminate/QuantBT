from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

import app.research_os.onboarding_readiness as readiness_module
from app.research_os.onboarding_readiness import (
    ONBOARDING_READINESS_ENTRYPOINT_REF,
    OnboardingReadinessError,
    OnboardingReadinessSectionAdapter,
    OnboardingReadinessSnapshot,
    PersistentOnboardingReadinessRegistry,
    READINESS_COMPONENT_FIELDS,
    ReadinessComponentState,
    onboarding_readiness_semantic_material,
)
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    goal_section_semantic_proof_identity,
)


OWNER = "user-1"
SOURCE = "data_source:prices"
POLICY = "routing_policy:research"
CALL = "llm_call:terminal-1"
SERVICE = "service_principal:llm-gateway"


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _component(
    component_ref: str,
    principal_id: str,
    status: str,
    links: dict[str, str] | None = None,
    *,
    revision: str = "1",
) -> ReadinessComponentState:
    return ReadinessComponentState(
        component_ref=component_ref,
        principal_id=principal_id,
        revision=revision,
        state_hash=_hash(f"{component_ref}:{revision}:{status}:{links}"),
        status=status,
        links=links or {},
    )


def _snapshot(*, owner: str = OWNER) -> OnboardingReadinessSnapshot:
    secret = "secretref:source-prices"
    connection = "connection_check:prices"
    schema = "schema_probe:prices"
    mapping = "field_mapping:prices"
    pit = "pit_rule:prices"
    skill = "ingestion_skill:prices"
    update = "ingestion_update:prices-1"
    dataset_id = "dataset:prices"
    version = "dataset_version:prices:v1"
    semantics = "dataset_semantics:prices-v1"
    provider = "llm_provider:openai"
    auth = "secretref:llm-service"
    pool = "credential_pool:research"
    binding = "user_service_binding:user-1-research"
    common = {
        "provider_ref": provider,
        "auth_ref": auth,
        "credential_pool_ref": pool,
        "service_principal_ref": SERVICE,
    }
    return OnboardingReadinessSnapshot(
        owner_user_id=owner,
        credential_mode="secret_ref",
        data_source=_component(SOURCE, owner, "active"),
        secret_or_no_secret_policy=_component(
            secret,
            owner,
            "active",
            {"source_ref": SOURCE},
        ),
        connection_check=_component(
            connection,
            owner,
            "ok",
            {
                "source_ref": SOURCE,
                "auth_policy_ref": secret,
                "ingestion_skill_ref": skill,
            },
        ),
        schema_probe=_component(
            schema,
            owner,
            "unchanged",
            {
                "source_ref": SOURCE,
                "connection_check_ref": connection,
                "ingestion_skill_ref": skill,
            },
        ),
        field_mapping=_component(
            mapping,
            owner,
            "validated",
            {
                "source_ref": SOURCE,
                "schema_probe_ref": schema,
                "ingestion_skill_ref": skill,
            },
        ),
        pit_rule=_component(
            pit,
            owner,
            "validated",
            {
                "source_ref": SOURCE,
                "schema_probe_ref": schema,
                "field_mapping_ref": mapping,
                "ingestion_skill_ref": skill,
            },
        ),
        ingestion_skill=_component(
            skill,
            owner,
            "active",
            {
                "source_ref": SOURCE,
                "auth_policy_ref": secret,
                "field_mapping_ref": mapping,
                "pit_rule_ref": pit,
                "output_dataset_id": dataset_id,
            },
        ),
        ingestion_update=_component(
            update,
            owner,
            "succeeded",
            {
                "source_ref": SOURCE,
                "ingestion_skill_ref": skill,
                "dataset_version_ref": version,
            },
        ),
        dataset_version=_component(
            version,
            owner,
            "registered",
            {
                "dataset_id": dataset_id,
                "source_ref": SOURCE,
                "ingestion_skill_ref": skill,
            },
        ),
        dataset_semantics=_component(
            semantics,
            owner,
            "validated",
            {
                "source_ref": SOURCE,
                "ingestion_skill_ref": skill,
                "ingestion_update_ref": update,
                "dataset_version_ref": version,
            },
        ),
        dataset_use_validation=_component(
            "market_data_use_validation:prices-v1",
            owner,
            "passed",
            {
                "source_ref": SOURCE,
                "dataset_semantics_ref": semantics,
                "dataset_version_ref": version,
            },
        ),
        llm_provider=_component(
            provider,
            SERVICE,
            "active",
            {"service_principal_ref": SERVICE},
        ),
        service_principal_auth=_component(
            auth,
            SERVICE,
            "active",
            {"provider_ref": provider, "service_principal_ref": SERVICE},
        ),
        provider_health=_component(
            "llm_health:openai-1",
            SERVICE,
            "healthy",
            {
                "provider_ref": provider,
                "auth_ref": auth,
                "service_principal_ref": SERVICE,
                "freshness_status": "current",
            },
        ),
        credential_pool=_component(
            pool,
            SERVICE,
            "active",
            {
                "provider_ref": provider,
                "auth_ref": auth,
                "service_principal_ref": SERVICE,
            },
        ),
        routing_policy=_component(
            POLICY,
            SERVICE,
            "active",
            common,
        ),
        user_service_binding=_component(
            binding,
            owner,
            "active",
            {**common, "owner_user_id": owner, "routing_policy_ref": POLICY},
        ),
        terminal_llm_call=_component(
            CALL,
            owner,
            "ok",
            {
                **common,
                "owner_user_id": owner,
                "routing_policy_ref": POLICY,
                "user_service_binding_ref": binding,
                "record_kind": "terminal",
            },
        ),
    )


class MutableResolver:
    def __init__(self, snapshot: OnboardingReadinessSnapshot) -> None:
        self.snapshot = snapshot

    def __call__(
        self,
        owner_user_id: str,
        data_source_ref: str,
        llm_routing_policy_ref: str,
        terminal_llm_call_ref: str,
    ) -> OnboardingReadinessSnapshot:
        return self.snapshot


def _registry(tmp_path, snapshot: OnboardingReadinessSnapshot | None = None):
    resolver = MutableResolver(snapshot or _snapshot())
    return (
        PersistentOnboardingReadinessRegistry(
            tmp_path / "onboarding-readiness.jsonl",
            resolve_snapshot=resolver,
        ),
        resolver,
    )


def _record(registry: PersistentOnboardingReadinessRegistry):
    return registry.record_current(OWNER, SOURCE, POLICY, CALL)


class _Entrypoints:
    def __init__(
        self,
        receipt_ref: str,
        *,
        recorded_by: str = OWNER,
        entrypoint_ref: str = ONBOARDING_READINESS_ENTRYPOINT_REF,
        source: str = "api",
        accepted: bool = True,
    ) -> None:
        self.coverage_ref = "goal_entrypoint_coverage:onboarding-readiness"
        self.coverage_record = SimpleNamespace(
            coverage_ref=self.coverage_ref,
            entry_source=source,
            entrypoint_ref=entrypoint_ref,
            goal_sections=("§4",),
            validation_refs=(receipt_ref,),
            recorded_by=recorded_by,
        )
        self.accepted = accepted

    def coverage(self, coverage_ref: str, *, owner: str):
        if coverage_ref != self.coverage_ref:
            raise KeyError(coverage_ref)
        return self.coverage_record

    def validate_real_backing(self, coverage):
        assert coverage is self.coverage_record
        return SimpleNamespace(accepted=self.accepted)


def _semantic_proof(
    receipt,
    entrypoints: _Entrypoints,
    *,
    owner: str = OWNER,
) -> GoalSectionSemanticProofRecord:
    material = onboarding_readiness_semantic_material(receipt)
    data = {
        "section": "§4",
        "subject_ref": material.subject_ref,
        "producer_refs": material.producer_refs,
        "store_refs": material.store_refs,
        "consumer_refs": material.consumer_refs,
        "gate_verdict_refs": material.gate_verdict_refs,
        "test_refs": material.test_refs,
        "entrypoint_coverage_refs": (entrypoints.coverage_ref,),
        "recorded_by": owner,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    data["proof_ref"] = goal_section_semantic_proof_identity(**data)
    return GoalSectionSemanticProofRecord(**data)


def _codes(error: pytest.ExceptionInfo[OnboardingReadinessError]) -> str:
    return str(error.value)


def test_exact_chain_records_and_revalidates_current(tmp_path) -> None:
    registry, _resolver = _registry(tmp_path)

    receipt = _record(registry)

    assert receipt.receipt_ref.startswith("onboarding_readiness_receipt:")
    assert registry.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted
    assert registry.receipt(receipt.receipt_ref, owner_user_id=OWNER) == receipt
    assert registry.current_receipt(OWNER, SOURCE, POLICY, CALL) == receipt


def test_missing_exact_link_is_rejected(tmp_path) -> None:
    snapshot = _snapshot()
    broken = replace(
        snapshot.connection_check,
        links={
            "source_ref": SOURCE,
            "auth_policy_ref": snapshot.secret_or_no_secret_policy.component_ref,
        },
    )
    registry, _resolver = _registry(tmp_path, replace(snapshot, connection_check=broken))

    with pytest.raises(OnboardingReadinessError) as error:
        _record(registry)

    assert "onboarding_readiness_link_fields_inexact" in _codes(error)


def test_cross_owner_data_chain_is_rejected_and_receipts_are_owner_isolated(tmp_path) -> None:
    snapshot = _snapshot()
    foreign_source = replace(snapshot.data_source, principal_id="user-2")
    registry, resolver = _registry(tmp_path, replace(snapshot, data_source=foreign_source))

    with pytest.raises(OnboardingReadinessError) as error:
        _record(registry)
    assert "onboarding_readiness_data_owner_mismatch" in _codes(error)

    resolver.snapshot = snapshot
    receipt = _record(registry)
    with pytest.raises(KeyError):
        registry.receipt(receipt.receipt_ref, owner_user_id="user-2")


def test_revoked_source_secret_is_rejected(tmp_path) -> None:
    snapshot = _snapshot()
    revoked = replace(snapshot.secret_or_no_secret_policy, status="revoked")
    registry, _resolver = _registry(
        tmp_path,
        replace(snapshot, secret_or_no_secret_policy=revoked),
    )

    with pytest.raises(OnboardingReadinessError) as error:
        _record(registry)

    assert "onboarding_readiness_secret_not_active" in _codes(error)


def test_stale_provider_health_is_rejected(tmp_path) -> None:
    snapshot = _snapshot()
    links = snapshot.provider_health.link_map
    links["freshness_status"] = "stale"
    stale = replace(snapshot.provider_health, links=links)
    registry, _resolver = _registry(tmp_path, replace(snapshot, provider_health=stale))

    with pytest.raises(OnboardingReadinessError) as error:
        _record(registry)

    assert "onboarding_readiness_llm_chain_mismatch" in _codes(error)


@pytest.mark.parametrize("component_name", ("service_principal_auth", "routing_policy"))
def test_wrong_service_principal_is_rejected(tmp_path, component_name) -> None:
    snapshot = _snapshot()
    wrong_component = replace(
        getattr(snapshot, component_name),
        principal_id="service_principal:other",
    )
    registry, _resolver = _registry(
        tmp_path,
        replace(snapshot, **{component_name: wrong_component}),
    )

    with pytest.raises(OnboardingReadinessError) as error:
        _record(registry)

    assert "onboarding_readiness_service_principal_mismatch" in _codes(error)


@pytest.mark.parametrize("failure", ["owner", "policy"])
def test_terminal_call_must_belong_to_user_and_consume_requested_policy(tmp_path, failure) -> None:
    snapshot = _snapshot()
    if failure == "owner":
        terminal = replace(snapshot.terminal_llm_call, principal_id="user-2")
    else:
        links = snapshot.terminal_llm_call.link_map
        links["routing_policy_ref"] = "routing_policy:other"
        terminal = replace(snapshot.terminal_llm_call, links=links)
    registry, _resolver = _registry(tmp_path, replace(snapshot, terminal_llm_call=terminal))

    with pytest.raises(OnboardingReadinessError) as error:
        _record(registry)

    assert (
        "onboarding_readiness_llm_user_owner_mismatch" in _codes(error)
        or "onboarding_readiness_llm_chain_mismatch" in _codes(error)
    )


@pytest.mark.parametrize("drift", ["secret_rotation", "secret_revocation", "mapping", "policy"])
def test_component_drift_invalidates_persisted_receipt(tmp_path, drift) -> None:
    registry, resolver = _registry(tmp_path)
    receipt = _record(registry)
    if drift == "secret_rotation":
        changed = replace(
            resolver.snapshot.secret_or_no_secret_policy,
            revision="2",
            state_hash=_hash("rotated source secret"),
        )
        resolver.snapshot = replace(resolver.snapshot, secret_or_no_secret_policy=changed)
    elif drift == "secret_revocation":
        changed = replace(
            resolver.snapshot.secret_or_no_secret_policy,
            status="revoked",
            revision="2",
            state_hash=_hash("revoked source secret"),
        )
        resolver.snapshot = replace(resolver.snapshot, secret_or_no_secret_policy=changed)
    elif drift == "mapping":
        changed = replace(
            resolver.snapshot.field_mapping,
            revision="2",
            state_hash=_hash("field mapping revision 2"),
        )
        resolver.snapshot = replace(resolver.snapshot, field_mapping=changed)
    else:
        changed = replace(
            resolver.snapshot.routing_policy,
            revision="2",
            state_hash=_hash("routing policy revision 2"),
        )
        resolver.snapshot = replace(resolver.snapshot, routing_policy=changed)

    decision = registry.validate_current(receipt.receipt_ref, owner_user_id=OWNER)

    assert not decision.accepted
    assert "onboarding_readiness_current_state_drifted" in {
        item.code for item in decision.violations
    }


def test_replay_is_idempotent_and_multi_instance_concurrency_writes_one_row(tmp_path) -> None:
    path = tmp_path / "onboarding-readiness.jsonl"
    resolver = MutableResolver(_snapshot())

    def write_once(_index: int) -> str:
        registry = PersistentOnboardingReadinessRegistry(path, resolve_snapshot=resolver)
        return registry.record_current(OWNER, SOURCE, POLICY, CALL).receipt_ref

    with ThreadPoolExecutor(max_workers=8) as executor:
        refs = list(executor.map(write_once, range(16)))

    assert len(set(refs)) == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    reloaded = PersistentOnboardingReadinessRegistry(path, resolve_snapshot=resolver)
    assert len(reloaded.receipts(owner_user_id=OWNER)) == 1
    assert reloaded.record_current(OWNER, SOURCE, POLICY, CALL).receipt_ref == refs[0]


def test_content_identity_collision_with_different_evidence_fails_closed(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(readiness_module, "_sha256", lambda _value: "a" * 64)
    registry, resolver = _registry(tmp_path)
    _record(registry)
    changed_mapping = replace(
        resolver.snapshot.field_mapping,
        revision="2",
        state_hash=_hash("changed mapping"),
    )
    resolver.snapshot = replace(resolver.snapshot, field_mapping=changed_mapping)

    with pytest.raises(OnboardingReadinessError, match="identity collision"):
        _record(registry)


def test_legacy_rows_are_quarantined_without_becoming_receipts(tmp_path) -> None:
    path = tmp_path / "onboarding-readiness.jsonl"
    path.write_text('{"schema_version":1,"owner_user_id":"user-1"}\n', encoding="utf-8")

    registry = PersistentOnboardingReadinessRegistry(
        path,
        resolve_snapshot=MutableResolver(_snapshot()),
    )

    assert registry.legacy_quarantined_count == 1
    assert registry.receipts(owner_user_id=OWNER) == ()


def test_section_adapter_accepts_exact_current_18_component_api_lineage(tmp_path) -> None:
    registry, _resolver = _registry(tmp_path)
    receipt = _record(registry)
    entrypoints = _Entrypoints(receipt.receipt_ref)
    proof = _semantic_proof(receipt, entrypoints)
    material = onboarding_readiness_semantic_material(receipt)
    adapter = OnboardingReadinessSectionAdapter(entrypoints, registry)

    decision = adapter.validate(proof, owner=OWNER)

    assert decision.accepted, decision.violations
    assert len(READINESS_COMPONENT_FIELDS) == 18
    assert len(material.producer_refs) == 18
    assert len(material.store_refs) == 19
    assert len(material.consumer_refs) == 3
    assert len(material.gate_verdict_refs) == 1
    assert len(material.test_refs) == 18
    assert set(material.producer_refs) == {
        getattr(receipt.snapshot, name).component_ref
        for name in READINESS_COMPONENT_FIELDS
    }
    assert material.consumer_refs == (
        ONBOARDING_READINESS_ENTRYPOINT_REF,
        receipt.snapshot.user_service_binding.component_ref,
        receipt.snapshot.terminal_llm_call.component_ref,
    )


@pytest.mark.parametrize(
    ("entrypoint_ref", "source", "extra_coverage"),
    (
        ("api:goal.onboarding.unrelated", "api", False),
        (ONBOARDING_READINESS_ENTRYPOINT_REF, "agent_shell", False),
        (ONBOARDING_READINESS_ENTRYPOINT_REF, "api", True),
    ),
)
def test_section_adapter_requires_exactly_one_canonical_readiness_api_lineage(
    tmp_path,
    entrypoint_ref,
    source,
    extra_coverage,
) -> None:
    registry, _resolver = _registry(tmp_path)
    receipt = _record(registry)
    entrypoints = _Entrypoints(
        receipt.receipt_ref,
        entrypoint_ref=entrypoint_ref,
        source=source,
    )
    proof = _semantic_proof(receipt, entrypoints)
    if extra_coverage:
        proof = replace(
            proof,
            entrypoint_coverage_refs=(
                *proof.entrypoint_coverage_refs,
                "goal_entrypoint_coverage:unrelated",
            ),
        )
    adapter = OnboardingReadinessSectionAdapter(entrypoints, registry)

    decision = adapter.validate(proof, owner=OWNER)

    assert not decision.accepted
    assert any(item.field == "entrypoint_coverage_refs" for item in decision.violations)


@pytest.mark.parametrize(
    "field_name",
    (
        "producer_refs",
        "store_refs",
        "consumer_refs",
        "gate_verdict_refs",
        "test_refs",
    ),
)
def test_section_adapter_rejects_every_semantic_material_recombination(
    tmp_path,
    field_name,
) -> None:
    registry, _resolver = _registry(tmp_path)
    receipt = _record(registry)
    entrypoints = _Entrypoints(receipt.receipt_ref)
    proof = _semantic_proof(receipt, entrypoints)
    poisoned = replace(
        proof,
        **{field_name: (*getattr(proof, field_name), f"unrelated:{field_name}")},
    )
    adapter = OnboardingReadinessSectionAdapter(entrypoints, registry)

    decision = adapter.validate(poisoned, owner=OWNER)

    assert not decision.accepted
    assert any(item.field == field_name for item in decision.violations)


@pytest.mark.parametrize("drift", ("service_principal", "terminal_policy", "health"))
def test_section_adapter_rejects_current_service_binding_or_health_drift(
    tmp_path,
    drift,
) -> None:
    registry, resolver = _registry(tmp_path)
    receipt = _record(registry)
    entrypoints = _Entrypoints(receipt.receipt_ref)
    proof = _semantic_proof(receipt, entrypoints)
    if drift == "service_principal":
        changed = replace(
            resolver.snapshot.service_principal_auth,
            principal_id="service_principal:other",
            revision="2",
            state_hash=_hash("foreign service principal"),
        )
        resolver.snapshot = replace(resolver.snapshot, service_principal_auth=changed)
    elif drift == "terminal_policy":
        links = resolver.snapshot.terminal_llm_call.link_map
        links["routing_policy_ref"] = "routing_policy:other"
        changed = replace(
            resolver.snapshot.terminal_llm_call,
            links=links,
            revision="2",
            state_hash=_hash("terminal policy drift"),
        )
        resolver.snapshot = replace(resolver.snapshot, terminal_llm_call=changed)
    else:
        links = resolver.snapshot.provider_health.link_map
        links["freshness_status"] = "stale"
        changed = replace(
            resolver.snapshot.provider_health,
            links=links,
            revision="2",
            state_hash=_hash("stale provider health"),
        )
        resolver.snapshot = replace(resolver.snapshot, provider_health=changed)
    adapter = OnboardingReadinessSectionAdapter(entrypoints, registry)

    decision = adapter.validate(proof, owner=OWNER)

    assert not decision.accepted
    assert any(
        item.field in {"gate_verdict_refs", "consumer_refs"}
        for item in decision.violations
    )


def test_section_adapter_rejects_cross_owner_receipt_reuse(tmp_path) -> None:
    registry, _resolver = _registry(tmp_path)
    receipt = _record(registry)
    entrypoints = _Entrypoints(receipt.receipt_ref, recorded_by="user-2")
    proof = _semantic_proof(receipt, entrypoints, owner="user-2")
    adapter = OnboardingReadinessSectionAdapter(entrypoints, registry)

    decision = adapter.validate(proof, owner="user-2")

    assert not decision.accepted
    assert any(
        item.field == "gate_verdict_refs" and "not persisted for owner" in item.message
        for item in decision.violations
    )


def test_section_adapter_rejects_receipt_and_component_recombination(tmp_path) -> None:
    registry, resolver = _registry(tmp_path)
    first = _record(registry)
    changed_mapping = replace(
        resolver.snapshot.field_mapping,
        revision="2",
        state_hash=_hash("mapping revision 2"),
    )
    resolver.snapshot = replace(resolver.snapshot, field_mapping=changed_mapping)
    second = _record(registry)
    entrypoints = _Entrypoints(second.receipt_ref)
    first_material = onboarding_readiness_semantic_material(first)
    second_proof = _semantic_proof(second, entrypoints)
    recombined = replace(
        second_proof,
        producer_refs=first_material.producer_refs,
        store_refs=first_material.store_refs,
        test_refs=first_material.test_refs,
    )
    adapter = OnboardingReadinessSectionAdapter(entrypoints, registry)

    decision = adapter.validate(recombined, owner=OWNER)

    assert not decision.accepted
    assert {item.field for item in decision.violations} >= {"store_refs", "test_refs"}
