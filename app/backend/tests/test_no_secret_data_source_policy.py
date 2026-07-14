from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from app.research_os import (
    DataSourceAssetRecord,
    IngestionLifecycleState,
    IngestionSkillRecord,
    NoSecretDataSourcePolicyRecord,
    NoSecretDataSourcePolicyStatus,
    PersistentOnboardingRegistry,
    SecretRefRecord,
    SecretRefStatus,
)


def _source(source_ref: str = "datasource:public:prices") -> DataSourceAssetRecord:
    return DataSourceAssetRecord(
        source_ref=source_ref,
        license="public_data_terms",
        redistribution_rights="internal_research",
        rate_limit="60/min",
        tos_constraints="public_read_only",
        commercial_use_status="reviewed",
        retention_policy="retain:research-cache",
        source_owner="public-provider",
        source_url_or_path="https://data.example.test/prices.csv",
    )


def _policy(**overrides: object) -> NoSecretDataSourcePolicyRecord:
    values: dict[str, object] = {
        "policy_ref": "no_secret_policy:public:prices",
        "source_ref": "datasource:public:prices",
        "source_type": "public_api",
        "connector_type": "public_api_no_auth",
        "external_credential_required": False,
        "permission_scope": "market_data:read",
        "status": NoSecretDataSourcePolicyStatus.ACTIVE,
        "actor_ref": "user:u1",
        "approved_at": "2026-07-12T20:00:00Z",
        "approval_ref": "approval:no-secret:public-prices",
        "evidence_refs": (
            "evidence:connector-docs:no-auth",
            "evidence:connection-check:public-prices",
        ),
        "reason": "Public read-only endpoint documents and verifies anonymous access.",
    }
    values.update(overrides)
    return NoSecretDataSourcePolicyRecord(**values)


def _secret() -> SecretRefRecord:
    return SecretRefRecord(
        secret_ref="secretref:public-prices:read",
        scope="market_data:read",
        status=SecretRefStatus.ACTIVE,
        created_at="2026-07-12T20:00:00Z",
    )


def _skill(*, with_secret: bool) -> IngestionSkillRecord:
    secret_refs = ("secretref:public-prices:read",) if with_secret else ()
    connector_config = (
        {"auth_ref": secret_refs[0], "connector_name": "public_prices"}
        if with_secret
        else {"auth_mode": "none", "connector_name": "public_prices"}
    )
    return IngestionSkillRecord(
        skill_id="ingest:public:prices",
        source_type="public_api",
        source_ref="datasource:public:prices",
        connector_config=connector_config,
        schema_mapping_ref="schema_map:public:prices",
        secret_refs=secret_refs,
        refresh_mode="manual",
        data_quality_tests=("not_null:timestamp",),
        pit_bitemporal_rules_ref="pit:public:prices",
        output_dataset_id="dataset:public:prices",
        owner="user:u1",
        version="1",
        lifecycle_state=IngestionLifecycleState.ACTIVE,
        freshness_status="fresh",
        permission_scope="market_data:read",
        dependency_lock_ref="deps:public-prices:v1",
        schedule_owner="scheduler:manual",
        rollback_plan_ref="rollback:public-prices:v1",
    )


def test_no_secret_policy_records_owner_scoped_current_state_and_restarts(tmp_path):
    path = tmp_path / "onboarding.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_data_source_asset(_source(), owner_user_id="u1")

    policy = registry.record_no_secret_data_source_policy(_policy(), owner_user_id="u1")

    assert policy.external_credential_required is False
    assert registry.no_secret_data_source_policy(
        policy.policy_ref, owner_user_id="u1"
    ) == policy
    assert registry.no_secret_data_source_policies(
        owner_user_id="u1",
        source_ref=policy.source_ref,
        status=NoSecretDataSourcePolicyStatus.ACTIVE,
    ) == [policy]
    revision, record_hash = registry.record_state(
        "no_secret_data_source_policy_recorded",
        policy.policy_ref,
        owner_user_id="u1",
    )
    assert revision == 1
    assert record_hash.startswith("sha256:")

    reloaded = PersistentOnboardingRegistry(path)
    assert reloaded.no_secret_data_source_policy(
        policy.policy_ref, owner_user_id="u1"
    ) == policy
    with pytest.raises(KeyError):
        reloaded.no_secret_data_source_policy(policy.policy_ref, owner_user_id="u2")


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        (
            {"source_type": "third_party_api", "connector_type": "third_party_api_no_auth"},
            "source_type_not_eligible",
        ),
        (
            {"connector_type": "public_api_auth_required"},
            "connector_type_not_eligible",
        ),
        ({"external_credential_required": True}, "external_credential_required"),
        ({"permission_scope": "market_data:write"}, "permission_scope_not_read_only"),
        ({"policy_ref": "legacy:no-secret:public-prices"}, "policy_ref_invalid"),
    ],
)
def test_no_secret_policy_rejects_ineligible_or_credential_required_claims_without_write(
    tmp_path, overrides, error
):
    path = tmp_path / "onboarding.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_data_source_asset(_source(), owner_user_id="u1")
    before = path.read_bytes()

    with pytest.raises(ValueError, match=error):
        registry.record_no_secret_data_source_policy(
            _policy(**overrides), owner_user_id="u1"
        )

    assert path.read_bytes() == before
    assert registry.no_secret_data_source_policies(owner_user_id="u1") == []


def test_no_secret_policy_requires_exact_owner_source_without_write(tmp_path):
    path = tmp_path / "onboarding.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_data_source_asset(_source(), owner_user_id="u1")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="not recorded for owner"):
        registry.record_no_secret_data_source_policy(_policy(), owner_user_id="u2")

    assert path.read_bytes() == before
    assert registry.no_secret_data_source_policies(owner_user_id="u1") == []
    assert registry.no_secret_data_source_policies(owner_user_id="u2") == []


def test_active_no_secret_policy_and_skill_secret_path_are_mutually_exclusive(tmp_path):
    first_path = tmp_path / "skill-first.jsonl"
    skill_first = PersistentOnboardingRegistry(first_path)
    skill_first.record_data_source_asset(_source(), owner_user_id="u1")
    skill_first.record_secret_ref(_secret(), owner_user_id="u1")
    skill_first.record_ingestion_skill(_skill(with_secret=True), owner_user_id="u1")
    before = first_path.read_bytes()

    with pytest.raises(ValueError, match="conflicts_with_skill_secret_path"):
        skill_first.record_no_secret_data_source_policy(_policy(), owner_user_id="u1")
    assert first_path.read_bytes() == before
    assert skill_first.no_secret_data_source_policies(owner_user_id="u1") == []

    policy_path = tmp_path / "policy-first.jsonl"
    policy_first = PersistentOnboardingRegistry(policy_path)
    policy_first.record_data_source_asset(_source(), owner_user_id="u1")
    policy_first.record_no_secret_data_source_policy(_policy(), owner_user_id="u1")
    policy_first.record_secret_ref(_secret(), owner_user_id="u1")
    before = policy_path.read_bytes()

    with pytest.raises(ValueError, match="conflicts_with_skill_secret_path"):
        policy_first.record_ingestion_skill(_skill(with_secret=True), owner_user_id="u1")
    assert policy_path.read_bytes() == before
    assert policy_first.ingestion_skills(owner_user_id="u1") == []


def test_active_no_secret_policy_accepts_only_matching_no_auth_skill(tmp_path):
    path = tmp_path / "onboarding.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_data_source_asset(_source(), owner_user_id="u1")
    registry.record_no_secret_data_source_policy(_policy(), owner_user_id="u1")

    skill = registry.record_ingestion_skill(_skill(with_secret=False), owner_user_id="u1")

    assert skill.secret_refs == ()


def test_active_no_secret_policy_blocks_source_drift_and_ambiguous_policy(tmp_path):
    path = tmp_path / "onboarding.jsonl"
    registry = PersistentOnboardingRegistry(path)
    source = registry.record_data_source_asset(_source(), owner_user_id="u1")
    registry.record_no_secret_data_source_policy(_policy(), owner_user_id="u1")
    before = path.read_bytes()
    source_revision, source_hash = registry.record_state(
        "data_source_asset_recorded", source.source_ref, owner_user_id="u1"
    )

    with pytest.raises(ValueError, match="revoke the policy before changing the source"):
        registry.record_data_source_asset(
            replace(source, source_url_or_path="https://changed.example.test/prices.csv"),
            owner_user_id="u1",
            expected_previous_revision=source_revision,
            expected_previous_hash=source_hash,
        )
    with pytest.raises(ValueError, match="already has an active"):
        registry.record_no_secret_data_source_policy(
            _policy(policy_ref="no_secret_policy:public:prices:duplicate"),
            owner_user_id="u1",
        )

    assert path.read_bytes() == before


def test_no_secret_policy_revocation_requires_cas_and_is_terminal(tmp_path):
    path = tmp_path / "onboarding.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_data_source_asset(_source(), owner_user_id="u1")
    active = registry.record_no_secret_data_source_policy(_policy(), owner_user_id="u1")
    revision, record_hash = registry.record_state(
        "no_secret_data_source_policy_recorded",
        active.policy_ref,
        owner_user_id="u1",
    )
    revoked = replace(
        active,
        status=NoSecretDataSourcePolicyStatus.REVOKED,
        revoked_at="2026-07-12T21:00:00Z",
        revocation_reason="Provider now requires an API credential.",
        revocation_evidence_refs=("evidence:provider-auth-change",),
    )
    before = path.read_bytes()

    with pytest.raises(ValueError, match="matching previous revision and hash"):
        registry.record_no_secret_data_source_policy(revoked, owner_user_id="u1")
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="approval identity is immutable"):
        registry.record_no_secret_data_source_policy(
            replace(active, reason="Mutated approval claim."),
            owner_user_id="u1",
            expected_previous_revision=revision,
            expected_previous_hash=record_hash,
        )
    assert path.read_bytes() == before

    registry.record_no_secret_data_source_policy(
        revoked,
        owner_user_id="u1",
        expected_previous_revision=revision,
        expected_previous_hash=record_hash,
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    policy_rows = [
        row for row in rows if row["event_type"] == "no_secret_data_source_policy_recorded"
    ]
    assert policy_rows[-1]["record_revision"] == 2
    assert policy_rows[-1]["previous_record_hash"] == policy_rows[0]["record_hash"]
    assert registry.no_secret_data_source_policies(
        owner_user_id="u1", status=NoSecretDataSourcePolicyStatus.ACTIVE
    ) == []
    assert registry.no_secret_data_source_policy(
        active.policy_ref, owner_user_id="u1"
    ).status == NoSecretDataSourcePolicyStatus.REVOKED

    reloaded = PersistentOnboardingRegistry(path)
    latest_revision, latest_hash = reloaded.record_state(
        "no_secret_data_source_policy_recorded",
        active.policy_ref,
        owner_user_id="u1",
    )
    before = path.read_bytes()
    with pytest.raises(ValueError, match="terminal"):
        reloaded.record_no_secret_data_source_policy(
            active,
            owner_user_id="u1",
            expected_previous_revision=latest_revision,
            expected_previous_hash=latest_hash,
        )
    assert path.read_bytes() == before

    reloaded.record_secret_ref(_secret(), owner_user_id="u1")
    reloaded.record_ingestion_skill(_skill(with_secret=True), owner_user_id="u1")


def test_no_secret_policy_hash_chain_corruption_fails_closed(tmp_path):
    path = tmp_path / "onboarding.jsonl"
    registry = PersistentOnboardingRegistry(path)
    registry.record_data_source_asset(_source(), owner_user_id="u1")
    policy = registry.record_no_secret_data_source_policy(_policy(), owner_user_id="u1")
    revision, record_hash = registry.record_state(
        "no_secret_data_source_policy_recorded",
        policy.policy_ref,
        owner_user_id="u1",
    )
    registry.record_no_secret_data_source_policy(
        replace(
            policy,
            status=NoSecretDataSourcePolicyStatus.REVOKED,
            revoked_at="2026-07-12T21:00:00Z",
            revocation_reason="Anonymous access removed.",
            revocation_evidence_refs=("evidence:auth-required",),
        ),
        owner_user_id="u1",
        expected_previous_revision=revision,
        expected_previous_hash=record_hash,
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[-1]["previous_record_hash"] = "sha256:" + "0" * 64
    body = {key: value for key, value in rows[-1].items() if key != "record_hash"}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    rows[-1]["record_hash"] = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid persisted onboarding settings row"):
        PersistentOnboardingRegistry(path)


def test_legacy_no_secret_policy_namespace_is_quarantined_not_adopted(tmp_path):
    path = tmp_path / "onboarding.jsonl"
    legacy = {
        "schema_version": 1,
        "event_type": "no_secret_data_source_policy_recorded",
        "payload": {
            "policy_ref": "no_secret_policy:legacy:spoof",
            "source_ref": "datasource:legacy:spoof",
            "status": "active",
        },
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    registry = PersistentOnboardingRegistry(path)

    assert registry.legacy_quarantined_count == 1
    assert registry.no_secret_data_source_policies(owner_user_id="u1") == []
