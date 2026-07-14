from __future__ import annotations

import base64
import hashlib
import json
from functools import partial
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    ExternalReviewerIdentityRecord,
    PersistentRDPCIReleaseAttestationStore,
    PersistentRDPExternalPublicationProofStore,
    PersistentRDPPackagePublishStore,
    PersistentRDPSourceRunIntegrityStore,
    PersistentRDPStore,
    PersistentExternalExpertSignatureRegistry,
    PersistentTrustDisclosureRegistry,
    PersistentTrustPressureRunRegistry,
    PersistentTrustReleaseApprovalRegistry,
    PersistentTrustReleaseCheckRegistry,
    PersistentTrustReleaseGateRegistry,
    RDPLocalPackagePublisher,
    RDPOpenPackageMaterializer,
    RDPPackageArchiveExporter,
    RDPManifest,
    RDPSourceFileBundler,
    RuntimeStatus,
    TrustReleaseApprovalRecord,
    TrustReleaseGateRecord,
    external_expert_review_signature_payload,
    record_external_expert_review,
    record_trust_pressure_run,
    record_trust_release_approval,
    rdp_run_artifact_hash,
)

RDPOpenPackageMaterializer = partial(RDPOpenPackageMaterializer, owner_user_id="u1")
RDPSourceFileBundler = partial(RDPSourceFileBundler, owner_user_id="u1")
RDPPackageArchiveExporter = partial(RDPPackageArchiveExporter, owner_user_id="u1")
RDPLocalPackagePublisher = partial(RDPLocalPackagePublisher, owner_user_id="u1")
PersistentRDPPackagePublishStore = partial(
    PersistentRDPPackagePublishStore, owner_user_id="u1"
)
PersistentRDPExternalPublicationProofStore = partial(
    PersistentRDPExternalPublicationProofStore, owner_user_id="u1"
)
PersistentRDPCIReleaseAttestationStore = partial(
    PersistentRDPCIReleaseAttestationStore, owner_user_id="u1"
)
PersistentRDPSourceRunIntegrityStore = partial(
    PersistentRDPSourceRunIntegrityStore, owner_user_id="u1"
)


def _owned_root(root):
    return root / "_owners" / hashlib.sha256(b"u1").hexdigest()


def _manifest(**overrides) -> RDPManifest:
    data = {
        "research_question": "Can daily BTC momentum survive costs?",
        "graph_refs": ("rg:qro_graph",),
        "data_refs": ("dataset:BTCUSDT_1d",),
        "dataset_version_refs": ("dsver:btc-2023",),
        "market_data_use_validation_refs": ("market_data_use:BTCUSDT_1d:backtest",),
        "ingestion_skill_refs": ("skill:binance-vision-daily",),
        "mathematical_refs": ("math:momentum",),
        "theory_binding_refs": ("tbind:momentum",),
        "consistency_check_refs": ("ccheck:momentum",),
        "methodology_choice_refs": ("mchoice:standard",),
        "responsibility_refs": ("resp:standard",),
        "asset_refs": ("qro:strategy-book",),
        "code_refs": ("app/strategy/momentum.py",),
        "environment_lock_ref": "env:poetry-lock",
        "reproducibility_command": "python -m quantbt.run --run r1",
        "artifact_hash": "sha256:abc",
        "test_refs": ("tests/test_momentum.py",),
        "run_refs": ("run:bt1",),
        "honest_n_refs": ("ledger:goal1",),
        "cost_and_execution_assumptions": ("fee=10bps",),
        "attribution_refs": ("attrib:bt1",),
        "known_limits": ("sample fixture only",),
        "unverified_residuals": ("live slippage not observed",),
        "verifier_verdict_ref": "verdict:bt1",
        "compiler_artifact_refs": ("compiler_artifact:strategy:001",),
        "mathematical_spine_chain_refs": ("math_spine_chain:btc_momentum:v1",),
        "goal_entrypoint_coverage_refs": ("goal_entrypoint_coverage:strategy:001",),
        "approval_ref": "approval:paper",
        "target_runtime": RuntimeStatus.PAPER,
        "llm_call_refs": ("llmcall:slot-fill",),
        "source_file_refs": ("source-file:strategy.py", "source-file:README.md"),
    }
    data.update(overrides)
    return RDPManifest(**data)


def _write_sources(source_root):
    (source_root / "strategy.py").write_text("def alpha(row):\n    return row['close']\n", encoding="utf-8")
    (source_root / "README.md").write_text("# Research package\n", encoding="utf-8")


def _write_run(run_root, run_id: str = "bt1"):
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": run_id, "owner_user_id": "u1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "strategy.py").write_text("def alpha(row):\n    return row['close']\n", encoding="utf-8")
    (run_dir / "portfolio.csv").write_text("ts,equity\n2024-01-01,1.0\n", encoding="utf-8")
    return run_dir


def _artifact_hash(run_dir) -> str:
    return rdp_run_artifact_hash(
        run_manifest_sha256="sha256:" + hashlib.sha256((run_dir / "run.json").read_bytes()).hexdigest(),
        run_strategy_sha256="sha256:" + hashlib.sha256((run_dir / "strategy.py").read_bytes()).hexdigest(),
        run_portfolio_sha256="sha256:" + hashlib.sha256((run_dir / "portfolio.csv").read_bytes()).hexdigest(),
    )


def _record_source_run_integrity(manifest: RDPManifest, materializer, run_root) -> None:
    main.RDP_SOURCE_RUN_INTEGRITY_STORE.record_integrity(
        manifest,
        package_root=materializer.package_root,
        run_root=run_root,
        run_id="bt1",
        source_file_ref="source-file:strategy.py",
        attested_by="u1",
        attested_at="2026-06-26T00:00:00+00:00",
    )


def _release_gate(**overrides) -> TrustReleaseGateRecord:
    data = {
        "release_ref": "release:v1",
        "anti_flattery_pressure_test_ref": "trust_test:anti_flattery",
        "multi_turn_pressure_test_ref": "trust_test:multi_turn",
        "expert_veto_ref": "expert_veto:001",
        "weakness_collapse_check_ref": "weakness_check:001",
        "mock_honesty_check_ref": "mock_check:001",
        "cold_start_honesty_check_ref": "cold_start_check:001",
    }
    data.update(overrides)
    return TrustReleaseGateRecord(**data)


def _release_approval(**overrides) -> TrustReleaseApprovalRecord:
    data = {
        "approval_ref": "trust_release_approval:release:v1",
        "release_ref": "release:v1",
        "release_gate_ref": "release:v1",
        "pressure_run_ref": "trust_pressure_run:release:v1",
        "expert_review_ref": "expert_review:release:v1",
        "artifact_ref": "rdp_package:release:v1",
        "approval_protocol_ref": "protocol:trust-release-approval",
        "verdict": "approved",
        "source_hash": "sha256:trust-release-approval",
        "evidence_refs": ("evidence:trust-release-approval",),
        "signed_approval_ref": "attestation:trust-release-approval",
    }
    data.update(overrides)
    return TrustReleaseApprovalRecord(**data)


def _trust_pressure_scenarios() -> list[dict]:
    rows = []
    for check_kind, prefix in (
        ("anti_flattery_pressure_test", "anti-flattery"),
        ("multi_turn_pressure_test", "multi-turn"),
        ("expert_veto", "expert-veto"),
        ("weakness_collapse_check", "weakness"),
        ("mock_honesty_check", "mock-honesty"),
        ("cold_start_honesty_check", "cold-start"),
    ):
        rows.append(
            {
                "check_kind": check_kind,
                "scenario_ref": f"scenario:{prefix}",
                "expected_behavior_ref": f"behavior:{prefix}:honest",
                "observed_behavior_ref": f"behavior:{prefix}:honest",
                "evidence_refs": [f"evidence:{prefix}"],
                "validation_result_refs": [f"pytest:{prefix}"],
            }
        )
    return rows


def _record_trust_release_authority(
    manifest: RDPManifest,
    *,
    owner_user_id: str = "u1",
    release_ref: str = "release:v1",
    artifact_ref_override: str | None = None,
    signed_approval_ref_override: str | None = None,
) -> TrustReleaseApprovalRecord:
    run, gate, checks = record_trust_pressure_run(
        release_ref=release_ref,
        runner_mode="local_deterministic",
        scenarios=_trust_pressure_scenarios(),
        evidence_refs=("evidence:pressure-run",),
        validation_result_refs=("pytest:pressure-run",),
        runner_ref=f"trust_pressure_run:{release_ref}",
    )
    for check in checks:
        main.TRUST_RELEASE_CHECK_REGISTRY.record_check(
            check, owner_user_id=owner_user_id
        )
    main.TRUST_RELEASE_GATE_REGISTRY.record_gate(gate, owner_user_id=owner_user_id)
    main.TRUST_PRESSURE_RUN_REGISTRY.record_run(run, owner_user_id=owner_user_id)

    artifact_ref = artifact_ref_override or f"rdp:{manifest.package_id}"
    review = record_external_expert_review(
        release_ref=release_ref,
        reviewer_ref="expert:independent_quant_reviewer",
        reviewer_independence_ref="independence:expert:001",
        artifact_ref=artifact_ref,
        review_protocol_ref="protocol:trust-release-review:v1",
        verdict="approved",
        evidence_refs=("evidence:expert-review",),
        signed_attestation_ref=f"attestation:expert:{manifest.package_id}",
        review_ref=f"expert_review:{release_ref}",
    )
    main.TRUST_DISCLOSURE_REGISTRY.record_external_expert_review(
        review, owner_user_id=owner_user_id
    )
    key = Ed25519PrivateKey.generate()
    public_key_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    identity = ExternalReviewerIdentityRecord(
        identity_ref="expert_identity:independent_quant_reviewer",
        reviewer_ref=review.reviewer_ref,
        identity_provider_ref="identity_provider:test-public-key",
        public_key_ref="public_key:independent_quant_reviewer:v1",
        public_key_pem=public_key_pem,
        reviewer_independence_ref=review.reviewer_independence_ref,
        evidence_refs=("identity:evidence:001",),
    )
    main.TRUST_EXPERT_SIGNATURE_REGISTRY.record_identity(
        identity, owner_user_id=owner_user_id
    )
    signature = main.TRUST_EXPERT_SIGNATURE_REGISTRY.record_signature(
        review=review,
        identity_ref=identity.identity_ref,
        signature_b64=base64.b64encode(
            key.sign(external_expert_review_signature_payload(review))
        ).decode("ascii"),
        attestation_ref=review.signed_attestation_ref,
        owner_user_id=owner_user_id,
    )
    approval = record_trust_release_approval(
        release_ref=release_ref,
        release_gate=gate,
        pressure_run=run,
        expert_review=review,
        artifact_ref=artifact_ref,
        approval_protocol_ref="protocol:trust-release-approval:v1",
        verdict="approved",
        evidence_refs=("evidence:trust-release-approval",),
        signed_approval_ref=signed_approval_ref_override or signature.verified_signature_ref,
        approval_ref=f"trust_release_approval:{release_ref}",
    )
    return main.TRUST_RELEASE_APPROVAL_REGISTRY.record_approval(
        approval, owner_user_id=owner_user_id
    )


def _materialize_bundle_archive(tmp_path, manifest: RDPManifest):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    _write_sources(source_root)
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    exporter = RDPPackageArchiveExporter(materializer.package_root)
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )
    archive = exporter.export(manifest)
    return materializer, bundler, exporter, archive, source_root


def _client_with_publish(tmp_path, monkeypatch):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    exporter = RDPPackageArchiveExporter(materializer.package_root)
    publisher = RDPLocalPackagePublisher(materializer.package_root)
    publish_store = PersistentRDPPackagePublishStore(tmp_path / "rdp_package_publishes.jsonl")
    external_publish_store = PersistentRDPExternalPublicationProofStore(
        tmp_path / "rdp_external_publication_proofs.jsonl"
    )
    ci_release_store = PersistentRDPCIReleaseAttestationStore(tmp_path / "rdp_ci_release_attestations.jsonl")
    trust_store = PersistentTrustReleaseGateRegistry(tmp_path / "trust_release_gates.jsonl")
    trust_check_store = PersistentTrustReleaseCheckRegistry(tmp_path / "trust_release_checks.jsonl")
    trust_pressure_store = PersistentTrustPressureRunRegistry(tmp_path / "trust_pressure_runs.jsonl")
    approval_store = PersistentTrustReleaseApprovalRegistry(tmp_path / "trust_release_approvals.jsonl")
    trust_disclosure_store = PersistentTrustDisclosureRegistry(tmp_path / "trust_disclosures.jsonl")
    trust_signature_store = PersistentExternalExpertSignatureRegistry(
        tmp_path / "trust_expert_signatures.jsonl"
    )
    integrity_store = PersistentRDPSourceRunIntegrityStore(tmp_path / "rdp_source_run_integrity.jsonl")
    monkeypatch.setattr(main, "RDP_STORE", store)
    monkeypatch.setattr(main, "RDP_PACKAGE_MATERIALIZER", materializer)
    monkeypatch.setattr(main, "RDP_SOURCE_FILE_BUNDLER", bundler)
    monkeypatch.setattr(main, "RDP_PACKAGE_ARCHIVE_EXPORTER", exporter)
    monkeypatch.setattr(main, "RDP_PACKAGE_PUBLISHER", publisher)
    monkeypatch.setattr(main, "RDP_PACKAGE_PUBLISH_STORE", publish_store)
    monkeypatch.setattr(main, "RDP_EXTERNAL_PUBLICATION_PROOF_STORE", external_publish_store)
    monkeypatch.setattr(main, "RDP_CI_RELEASE_ATTESTATION_STORE", ci_release_store)
    monkeypatch.setattr(main, "RDP_EXTERNAL_PUBLICATION_UPLOADER", None)
    monkeypatch.setattr(main, "RDP_CI_RELEASE_RUNNER", None)
    monkeypatch.setattr(main, "TRUST_RELEASE_GATE_REGISTRY", trust_store)
    monkeypatch.setattr(main, "TRUST_RELEASE_CHECK_REGISTRY", trust_check_store)
    monkeypatch.setattr(main, "TRUST_PRESSURE_RUN_REGISTRY", trust_pressure_store)
    monkeypatch.setattr(main, "TRUST_RELEASE_APPROVAL_REGISTRY", approval_store)
    monkeypatch.setattr(main, "TRUST_DISCLOSURE_REGISTRY", trust_disclosure_store)
    monkeypatch.setattr(main, "TRUST_EXPERT_SIGNATURE_REGISTRY", trust_signature_store)
    monkeypatch.setattr(main, "RDP_SOURCE_RUN_INTEGRITY_STORE", integrity_store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store, materializer, bundler, exporter, publisher, publish_store, source_root


def _record_manifest_and_local_publish(client, store, materializer, bundler, source_root, tmp_path):
    _write_sources(source_root)
    run_root = tmp_path / "runs"
    run_dir = _write_run(run_root)
    manifest = store.record_manifest(
        _manifest(artifact_hash=_artifact_hash(run_dir)),
        owner_user_id="u1",
        recorded_by="u1",
    )
    _record_trust_release_authority(manifest)
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )
    _record_source_run_integrity(manifest, materializer, run_root)
    response = client.post(
        f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
        json={
            "channel": "local_registry",
            "trust_release_ref": "release:v1",
            "trust_release_approval_ref": "trust_release_approval:release:v1",
        },
    )
    assert response.status_code == 200
    return manifest, response.json()


def _record_manifest_local_and_external_publish(client, store, materializer, bundler, source_root, tmp_path):
    manifest, publication = _record_manifest_and_local_publish(client, store, materializer, bundler, source_root, tmp_path)
    response = client.post(
        f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications",
        json={
            "external_channel": "object_store",
            "external_uri": "s3://quantbt-rdp/releases/rdp_pkg_1.zip",
            "immutable_pointer_ref": "object-version:rdp_pkg_1:v1",
            "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
            "local_publish_hash": publication["publish_hash"],
            "archive_sha256": publication["archive_sha256"],
            "trust_release_ref": "release:v1",
            "trust_release_approval_ref": "trust_release_approval:release:v1",
            "evidence_refs": ["ci:upload:001", "object-head:sha256"],
        },
    )
    assert response.status_code == 200, response.text
    return manifest, publication, response.json()


def _ci_release_runner_result(**overrides):
    result = {
        "ci_system_ref": "ci:github-actions",
        "ci_workflow_ref": "workflow:rdp-release",
        "ci_run_ref": "ci_run:runner-12345",
        "source_commit_ref": "git:commit:abc123",
        "ci_status": "passed",
        "artifact_digest": "sha256:artifact",
        "test_report_ref": "test-report:rdp-release",
        "test_report_hash": "sha256:test-report",
        "build_log_digest": "sha256:build-log",
        "required_check_refs": ["check:unit", "check:frontend", "check:backend"],
        "failed_check_refs": [],
        "skipped_check_refs": [],
        "missing_check_refs": [],
        "evidence_refs": ["ci:evidence:summary", "release:attestation"],
    }
    result.update(overrides)
    return result


def _external_publication_uploader_result(**overrides):
    result = {
        "external_channel": "object_store",
        "external_uri_digest": "sha16:1234567890abcdef",
        "immutable_pointer_ref": "object-version:rdp_pkg_1:runner",
        "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
        "publication_status": "published",
        "evidence_refs": ["uploader:evidence:summary", "object-head:sha16"],
    }
    result.update(overrides)
    return result


def test_rdp_local_package_publisher_copies_archive_and_replays_publish_record(tmp_path):
    manifest = _manifest()
    materializer, _bundler, _exporter, archive, _source_root = _materialize_bundle_archive(tmp_path, manifest)
    publisher = RDPLocalPackagePublisher(materializer.package_root)
    store = PersistentRDPPackagePublishStore(tmp_path / "rdp_package_publishes.jsonl")

    record = publisher.publish(
        manifest,
        archive,
        channel="local_registry",
        published_by="u1",
        published_at="2026-06-26T00:00:00+00:00",
        trust_release_ref="release:v1",
        trust_release_approval_ref="trust_release_approval:release:v1",
    )
    persisted = store.record_publication(record)

    published_path = _owned_root(tmp_path / "rdp_packages") / "_published" / manifest.package_id / f"{manifest.package_id}.zip"
    publication_json = _owned_root(tmp_path / "rdp_packages") / "_published" / manifest.package_id / "publication.json"
    assert published_path.exists()
    assert publication_json.exists()
    assert persisted.publish_hash.startswith("sha16:")
    assert persisted.archive_sha256 == archive.archive_sha256
    assert persisted.trust_release_ref == "release:v1"
    assert persisted.trust_release_approval_ref == "trust_release_approval:release:v1"
    assert json.loads(publication_json.read_text(encoding="utf-8"))["publish_hash"] == persisted.publish_hash

    reloaded = PersistentRDPPackagePublishStore(store.path)
    replayed = reloaded.publications(manifest.package_id)[0]
    assert replayed.publish_hash == persisted.publish_hash


def test_rdp_local_package_publisher_rejects_tampered_archive_without_publish(tmp_path):
    manifest = _manifest()
    materializer, _bundler, _exporter, archive, _source_root = _materialize_bundle_archive(tmp_path, manifest)
    publisher = RDPLocalPackagePublisher(materializer.package_root)
    archive_path = _owned_root(tmp_path / "rdp_packages") / "_archives" / f"{manifest.package_id}.zip"
    archive_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="archive sha256 mismatch"):
        publisher.publish(
            manifest,
            archive,
            channel="local_registry",
            published_by="u1",
            trust_release_ref="release:v1",
            trust_release_approval_ref="trust_release_approval:release:v1",
        )

    assert not (_owned_root(tmp_path / "rdp_packages") / "_published" / manifest.package_id / f"{manifest.package_id}.zip").exists()


def test_rdp_publish_api_publishes_recorded_manifest_and_lists_publications(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    _write_sources(source_root)
    run_root = tmp_path / "runs"
    run_dir = _write_run(run_root)
    manifest = store.record_manifest(
        _manifest(artifact_hash=_artifact_hash(run_dir)),
        owner_user_id="u1",
        recorded_by="u1",
    )
    _record_trust_release_authority(manifest)
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )
    _record_source_run_integrity(manifest, materializer, run_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={
                "channel": "local_registry",
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["channel"] == "local_registry"
        assert body["archive_sha256"].startswith("sha256:")
        assert body["publish_hash"].startswith("sha16:")
        assert body["trust_release_ref"] == "release:v1"
        assert body["trust_release_approval_ref"] == "trust_release_approval:release:v1"
        assert (_owned_root(tmp_path / "rdp_packages") / "_published" / manifest.package_id / f"{manifest.package_id}.zip").exists()

        listed = client.get("/api/research-os/rdp/publications")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["publications"][0]["publish_hash"] == body["publish_hash"]
        assert listed.json()["publications"][0]["trust_release_ref"] == "release:v1"
        assert listed.json()["publications"][0]["trust_release_approval_ref"] == "trust_release_approval:release:v1"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_external_publication_proof_records_after_local_publish_and_replays(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    try:
        manifest, publication = _record_manifest_and_local_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )

        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications",
            json={
                "external_channel": "object_store",
                "external_uri": "s3://quantbt-rdp/releases/rdp_pkg_1.zip",
                "immutable_pointer_ref": "object-version:rdp_pkg_1:v1",
                "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
                "local_publish_hash": publication["publish_hash"],
                "archive_sha256": publication["archive_sha256"],
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "evidence_refs": ["ci:upload:001", "object-head:sha256"],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["external_channel"] == "object_store"
        assert body["external_uri_digest"].startswith("sha16:")
        assert "external_uri" not in body
        assert body["local_publish_hash"] == publication["publish_hash"]
        assert body["archive_sha256"] == publication["archive_sha256"]
        assert body["trust_release_approval_ref"] == "trust_release_approval:release:v1"
        assert body["proof_hash"].startswith("sha16:")

        listed = client.get("/api/research-os/rdp/publications")
        assert listed.status_code == 200
        assert listed.json()["external_total"] == 1
        assert listed.json()["external_publications"][0]["proof_hash"] == body["proof_hash"]
        assert "external_uri" not in listed.json()["external_publications"][0]

        reloaded = PersistentRDPExternalPublicationProofStore(main.RDP_EXTERNAL_PUBLICATION_PROOF_STORE.path)
        replayed = reloaded.proofs(manifest.package_id)[0]
        assert replayed.proof_hash == body["proof_hash"]
        assert replayed.external_uri_digest == body["external_uri_digest"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_external_publication_proof_requires_local_publication_without_partial_record(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    _write_sources(source_root)
    manifest = store.record_manifest(
        _manifest(), owner_user_id="u1", recorded_by="u1"
    )
    _record_trust_release_authority(manifest)
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )
    try:
        missing = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications",
            json={
                "external_channel": "object_store",
                "external_uri": "s3://quantbt-rdp/releases/rdp_pkg_1.zip",
                "immutable_pointer_ref": "object-version:rdp_pkg_1:v1",
                "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "evidence_refs": ["ci:upload:001"],
            },
        )
        assert missing.status_code == 422
        assert "local_publish_hash is required" in missing.json()["detail"]

        unknown = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications",
            json={
                "external_channel": "object_store",
                "external_uri": "s3://quantbt-rdp/releases/rdp_pkg_1.zip",
                "immutable_pointer_ref": "object-version:rdp_pkg_1:v1",
                "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
                "local_publish_hash": "sha16:missing",
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "evidence_refs": ["ci:upload:001"],
            },
        )
        assert unknown.status_code == 422
        assert "unknown local_publish_hash" in unknown.json()["detail"]
        assert main.RDP_EXTERNAL_PUBLICATION_PROOF_STORE.proofs() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_external_publication_proof_rejects_mismatch_and_secret_uri_without_partial_record(
    tmp_path, monkeypatch
):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    try:
        manifest, publication = _record_manifest_and_local_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )
        base_payload = {
            "external_channel": "object_store",
            "external_uri": "s3://quantbt-rdp/releases/rdp_pkg_1.zip",
            "immutable_pointer_ref": "object-version:rdp_pkg_1:v1",
            "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
            "local_publish_hash": publication["publish_hash"],
            "archive_sha256": publication["archive_sha256"],
            "trust_release_ref": "release:v1",
            "trust_release_approval_ref": "trust_release_approval:release:v1",
            "evidence_refs": ["ci:upload:001"],
        }

        bad_archive = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications",
            json={**base_payload, "archive_sha256": "sha256:mismatch"},
        )
        assert bad_archive.status_code == 422
        assert "archive_sha256 does not match" in bad_archive.json()["detail"]

        bad_approval = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications",
            json={**base_payload, "trust_release_approval_ref": "trust_release_approval:missing"},
        )
        assert bad_approval.status_code == 422
        assert "unknown trust_release_approval_ref" in bad_approval.json()["detail"]

        secret_uri = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications",
            json={**base_payload, "external_uri": "https://object-store.example/rdp.zip?token=sk-abc123456"},
        )
        assert secret_uri.status_code == 422
        assert "plaintext secret" in secret_uri.json()["detail"]
        assert main.RDP_EXTERNAL_PUBLICATION_PROOF_STORE.proofs() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_external_publication_uploader_default_disabled_without_partial_record(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    try:
        manifest, publication = _record_manifest_and_local_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )

        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications/run",
            json={
                "external_channel": "object_store",
                "immutable_pointer_ref": "object-version:rdp_pkg_1:v1",
                "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
                "local_publish_hash": publication["publish_hash"],
                "archive_sha256": publication["archive_sha256"],
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "evidence_refs": ["uploader:evidence:summary"],
            },
        )

        assert response.status_code == 422
        assert "RDP external publication uploader is not configured" in response.json()["detail"]
        assert main.RDP_EXTERNAL_PUBLICATION_PROOF_STORE.proofs() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_external_publication_uploader_records_proof_from_fake_uploader(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    captured_request = {}

    def fake_uploader(request):
        captured_request.update(request)
        return _external_publication_uploader_result()

    monkeypatch.setattr(main, "RDP_EXTERNAL_PUBLICATION_UPLOADER", fake_uploader)
    try:
        manifest, publication = _record_manifest_and_local_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )

        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications/run",
            json={
                "external_channel": "object_store",
                "immutable_pointer_ref": "object-version:rdp_pkg_1:request",
                "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
                "local_publish_hash": publication["publish_hash"],
                "archive_sha256": publication["archive_sha256"],
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "evidence_refs": ["uploader:evidence:request"],
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["local_publish_hash"] == publication["publish_hash"]
        assert body["archive_sha256"] == publication["archive_sha256"]
        assert body["external_uri_digest"] == "sha16:1234567890abcdef"
        assert body["immutable_pointer_ref"] == "object-version:rdp_pkg_1:runner"
        assert body["proof_hash"].startswith("sha16:")
        assert "external_uri" not in body
        assert captured_request["package_id"] == manifest.package_id
        assert captured_request["local_publish_hash"] == publication["publish_hash"]
        assert captured_request["archive_sha256"] == publication["archive_sha256"]
        assert "external_uri" not in captured_request
        assert "published_archive_path" not in captured_request
        assert "raw_artifact" not in captured_request
        assert len(main.RDP_EXTERNAL_PUBLICATION_PROOF_STORE.proofs()) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


@pytest.mark.parametrize(
    ("uploader_result", "expected_detail"),
    [
        (_external_publication_uploader_result(raw_external_uri="s3://bucket/release.zip"), "raw or secret-bearing field"),
        (_external_publication_uploader_result(stdout="uploaded"), "raw or secret-bearing field"),
        (_external_publication_uploader_result(publication_status="failed"), "publication_status=published"),
        (
            _external_publication_uploader_result(immutable_pointer_ref="object-version:rdp?api_key=secret"),
            "plaintext secret",
        ),
    ],
)
def test_rdp_external_publication_uploader_rejects_bad_result_without_partial_record(
    tmp_path, monkeypatch, uploader_result, expected_detail
):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(main, "RDP_EXTERNAL_PUBLICATION_UPLOADER", lambda _request: uploader_result)
    try:
        manifest, publication = _record_manifest_and_local_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )

        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/external_publications/run",
            json={
                "external_channel": "object_store",
                "immutable_pointer_ref": "object-version:rdp_pkg_1:request",
                "destination_allowlist_ref": "destination_allowlist:rdp-release-prod",
                "local_publish_hash": publication["publish_hash"],
                "archive_sha256": publication["archive_sha256"],
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "evidence_refs": ["uploader:evidence:request"],
            },
        )

        assert response.status_code == 422
        assert expected_detail in response.json()["detail"]
        assert main.RDP_EXTERNAL_PUBLICATION_PROOF_STORE.proofs() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_ci_release_attestation_records_after_external_proof_and_replays(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    try:
        manifest, publication, external_proof = _record_manifest_local_and_external_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )

        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json={
                "local_publish_hash": publication["publish_hash"],
                "external_proof_hash": external_proof["proof_hash"],
                "archive_sha256": publication["archive_sha256"],
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "ci_system_ref": "ci:github-actions",
                "ci_workflow_ref": "workflow:rdp-release",
                "ci_run_ref": "ci_run:12345",
                "source_commit_ref": "git:commit:abc123",
                "ci_status": "passed",
                "artifact_digest": "sha256:artifact",
                "test_report_ref": "test-report:rdp-release",
                "test_report_hash": "sha256:test-report",
                "build_log_digest": "sha256:build-log",
                "required_check_refs": ["check:unit", "check:frontend", "check:backend"],
                "evidence_refs": ["ci:evidence:summary", "release:attestation"],
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["local_publish_hash"] == publication["publish_hash"]
        assert body["external_proof_hash"] == external_proof["proof_hash"]
        assert body["ci_status"] == "passed"
        assert body["attestation_hash"].startswith("sha16:")
        assert "raw_log" not in body

        listed = client.get("/api/research-os/rdp/publications")
        assert listed.status_code == 200
        assert listed.json()["ci_release_total"] == 1
        assert listed.json()["ci_release_attestations"][0]["attestation_hash"] == body["attestation_hash"]
        assert "raw_artifact" not in listed.json()["ci_release_attestations"][0]

        reloaded = PersistentRDPCIReleaseAttestationStore(main.RDP_CI_RELEASE_ATTESTATION_STORE.path)
        replayed = reloaded.attestations(manifest.package_id)[0]
        assert replayed.attestation_hash == body["attestation_hash"]
        assert replayed.external_proof_hash == external_proof["proof_hash"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_ci_release_attestation_requires_publication_and_external_proof_without_partial_record(
    tmp_path, monkeypatch
):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    try:
        manifest, publication = _record_manifest_and_local_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )
        base_payload = {
            "local_publish_hash": publication["publish_hash"],
            "archive_sha256": publication["archive_sha256"],
            "trust_release_ref": "release:v1",
            "trust_release_approval_ref": "trust_release_approval:release:v1",
            "ci_system_ref": "ci:github-actions",
            "ci_workflow_ref": "workflow:rdp-release",
            "ci_run_ref": "ci_run:12345",
            "source_commit_ref": "git:commit:abc123",
            "ci_status": "passed",
            "artifact_digest": "sha256:artifact",
            "test_report_ref": "test-report:rdp-release",
            "test_report_hash": "sha256:test-report",
            "build_log_digest": "sha256:build-log",
            "required_check_refs": ["check:unit"],
            "evidence_refs": ["ci:evidence:summary"],
        }

        missing_publish = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json={**base_payload, "local_publish_hash": ""},
        )
        assert missing_publish.status_code == 422
        assert "local_publish_hash is required" in missing_publish.json()["detail"]

        missing_external = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json=base_payload,
        )
        assert missing_external.status_code == 422
        assert "external_proof_hash is required" in missing_external.json()["detail"]

        unknown_external = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json={**base_payload, "external_proof_hash": "sha16:missing"},
        )
        assert unknown_external.status_code == 422
        assert "unknown external_proof_hash" in unknown_external.json()["detail"]
        assert main.RDP_CI_RELEASE_ATTESTATION_STORE.attestations() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_ci_release_attestation_rejects_bad_status_mismatch_and_secret_refs_without_partial_record(
    tmp_path, monkeypatch
):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    try:
        manifest, publication, external_proof = _record_manifest_local_and_external_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )
        base_payload = {
            "local_publish_hash": publication["publish_hash"],
            "external_proof_hash": external_proof["proof_hash"],
            "archive_sha256": publication["archive_sha256"],
            "trust_release_ref": "release:v1",
            "trust_release_approval_ref": "trust_release_approval:release:v1",
            "ci_system_ref": "ci:github-actions",
            "ci_workflow_ref": "workflow:rdp-release",
            "ci_run_ref": "ci_run:12345",
            "source_commit_ref": "git:commit:abc123",
            "ci_status": "passed",
            "artifact_digest": "sha256:artifact",
            "test_report_ref": "test-report:rdp-release",
            "test_report_hash": "sha256:test-report",
            "build_log_digest": "sha256:build-log",
            "required_check_refs": ["check:unit", "check:frontend"],
            "evidence_refs": ["ci:evidence:summary"],
        }

        bad_archive = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json={**base_payload, "archive_sha256": "sha256:mismatch"},
        )
        assert bad_archive.status_code == 422
        assert "archive_sha256 does not match" in bad_archive.json()["detail"]

        bad_status = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json={**base_payload, "ci_status": "failed"},
        )
        assert bad_status.status_code == 422
        assert "ci_status=passed" in bad_status.json()["detail"]

        skipped = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json={**base_payload, "skipped_check_refs": ["check:backend"]},
        )
        assert skipped.status_code == 422
        assert "failed, skipped, or missing" in skipped.json()["detail"]

        bad_approval = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json={**base_payload, "trust_release_approval_ref": "trust_release_approval:missing"},
        )
        assert bad_approval.status_code == 422
        assert "unknown trust_release_approval_ref" in bad_approval.json()["detail"]

        secret_ref = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations",
            json={**base_payload, "build_log_digest": "sha256:build-log?token=secret"},
        )
        assert secret_ref.status_code == 422
        assert "plaintext secret" in secret_ref.json()["detail"]
        assert main.RDP_CI_RELEASE_ATTESTATION_STORE.attestations() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_ci_release_runner_default_disabled_without_partial_record(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    try:
        manifest, publication, external_proof = _record_manifest_local_and_external_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )

        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations/run",
            json={
                "local_publish_hash": publication["publish_hash"],
                "external_proof_hash": external_proof["proof_hash"],
                "archive_sha256": publication["archive_sha256"],
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "ci_system_ref": "ci:github-actions",
                "ci_workflow_ref": "workflow:rdp-release",
                "source_commit_ref": "git:commit:abc123",
                "required_check_refs": ["check:unit"],
                "evidence_refs": ["ci:evidence:summary"],
            },
        )

        assert response.status_code == 422
        assert "RDP CI release runner is not configured" in response.json()["detail"]
        assert main.RDP_CI_RELEASE_ATTESTATION_STORE.attestations() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_ci_release_runner_records_attestation_from_fake_runner(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    captured_request = {}

    def fake_runner(request):
        captured_request.update(request)
        return _ci_release_runner_result()

    monkeypatch.setattr(main, "RDP_CI_RELEASE_RUNNER", fake_runner)
    try:
        manifest, publication, external_proof = _record_manifest_local_and_external_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )

        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations/run",
            json={
                "local_publish_hash": publication["publish_hash"],
                "external_proof_hash": external_proof["proof_hash"],
                "archive_sha256": publication["archive_sha256"],
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "ci_system_ref": "ci:github-actions",
                "ci_workflow_ref": "workflow:rdp-release",
                "source_commit_ref": "git:commit:abc123",
                "required_check_refs": ["check:unit", "check:frontend", "check:backend"],
                "evidence_refs": ["ci:evidence:summary"],
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["local_publish_hash"] == publication["publish_hash"]
        assert body["external_proof_hash"] == external_proof["proof_hash"]
        assert body["ci_run_ref"] == "ci_run:runner-12345"
        assert body["attestation_hash"].startswith("sha16:")
        assert captured_request["package_id"] == manifest.package_id
        assert captured_request["local_publish_hash"] == publication["publish_hash"]
        assert captured_request["external_proof_hash"] == external_proof["proof_hash"]
        assert "external_uri" not in captured_request
        assert "published_archive_path" not in captured_request
        assert "raw_artifact" not in captured_request
        assert len(main.RDP_CI_RELEASE_ATTESTATION_STORE.attestations()) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


@pytest.mark.parametrize(
    ("runner_result", "expected_detail"),
    [
        (_ci_release_runner_result(raw_ci_log="raw log text"), "raw or secret-bearing field"),
        (_ci_release_runner_result(build_log_digest="sha256:build-log?token=secret"), "plaintext secret"),
        (_ci_release_runner_result(skipped_check_refs=["check:backend"]), "failed, skipped, or missing"),
        (_ci_release_runner_result(ci_status="failed"), "ci_status=passed"),
    ],
)
def test_rdp_ci_release_runner_rejects_bad_result_without_partial_record(
    tmp_path, monkeypatch, runner_result, expected_detail
):
    client, store, materializer, bundler, _exporter, _publisher, _publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(main, "RDP_CI_RELEASE_RUNNER", lambda _request: runner_result)
    try:
        manifest, publication, external_proof = _record_manifest_local_and_external_publish(
            client, store, materializer, bundler, source_root, tmp_path
        )

        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/ci_release_attestations/run",
            json={
                "local_publish_hash": publication["publish_hash"],
                "external_proof_hash": external_proof["proof_hash"],
                "archive_sha256": publication["archive_sha256"],
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
                "ci_system_ref": "ci:github-actions",
                "ci_workflow_ref": "workflow:rdp-release",
                "source_commit_ref": "git:commit:abc123",
                "required_check_refs": ["check:unit"],
                "evidence_refs": ["ci:evidence:summary"],
            },
        )

        assert response.status_code == 422
        assert expected_detail in response.json()["detail"]
        assert main.RDP_CI_RELEASE_ATTESTATION_STORE.attestations() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_publish_api_requires_source_run_integrity_without_publish_record(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    _write_sources(source_root)
    run_root = tmp_path / "runs"
    run_dir = _write_run(run_root)
    manifest = store.record_manifest(
        _manifest(artifact_hash=_artifact_hash(run_dir)),
        owner_user_id="u1",
        recorded_by="u1",
    )
    _record_trust_release_authority(manifest)
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
            },
        )
        assert response.status_code == 422
        assert "source-run integrity attestation is required" in response.json()["detail"]
        assert publish_store.publications() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_publish_api_requires_recorded_trust_release_gate_without_publish_record(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    _write_sources(source_root)
    manifest = store.record_manifest(
        _manifest(), owner_user_id="u1", recorded_by="u1"
    )
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )
    try:
        missing = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={"channel": "local_registry"},
        )
        assert missing.status_code == 422
        assert "trust_release_ref is required" in missing.json()["detail"]

        missing_approval = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={"channel": "local_registry", "trust_release_ref": "release:v1"},
        )
        assert missing_approval.status_code == 422
        assert "trust_release_approval_ref is required" in missing_approval.json()["detail"]

        unknown = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={
                "channel": "local_registry",
                "trust_release_ref": "release:missing",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
            },
        )
        assert unknown.status_code == 422
        assert "unknown trust_release_ref" in unknown.json()["detail"]

        _record_trust_release_authority(manifest)
        unknown_approval = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={
                "channel": "local_registry",
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:missing",
            },
        )
        assert unknown_approval.status_code == 422
        assert "unknown trust_release_approval_ref" in unknown_approval.json()["detail"]

        main.TRUST_RELEASE_APPROVAL_REGISTRY.record_approval(
            _release_approval(approval_ref="trust_release_approval:release:v2", release_ref="release:v2"),
            owner_user_id="u1",
        )
        mismatched_approval = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={
                "channel": "local_registry",
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v2",
            },
        )
        assert mismatched_approval.status_code == 422
        assert "does not match trust_release_ref" in mismatched_approval.json()["detail"]
        assert publish_store.publications() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_publish_api_rejects_missing_source_bundle_without_publish_record(tmp_path, monkeypatch):
    client, store, materializer, _bundler, _exporter, _publisher, publish_store, _source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    manifest = store.record_manifest(
        _manifest(), owner_user_id="u1", recorded_by="u1"
    )
    _record_trust_release_authority(manifest)
    materializer.materialize(manifest)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
            },
        )
        assert response.status_code == 422
        assert "source bundle index is required" in response.json()["detail"]
        assert publish_store.publications() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_publish_api_rejects_external_channel_without_publish_record(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, _publisher, publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    _write_sources(source_root)
    run_root = tmp_path / "runs"
    run_dir = _write_run(run_root)
    manifest = store.record_manifest(
        _manifest(artifact_hash=_artifact_hash(run_dir)),
        owner_user_id="u1",
        recorded_by="u1",
    )
    _record_trust_release_authority(manifest)
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )
    _record_source_run_integrity(manifest, materializer, run_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={
                "channel": "https://object-store.example/upload",
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
            },
        )
        assert response.status_code == 422
        assert "local_registry" in response.json()["detail"]
        assert publish_store.publications() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


@pytest.mark.parametrize(
    ("authority_kwargs", "expected_detail"),
    [
        ({"owner_user_id": "u2"}, "unknown trust_release_ref"),
        (
            {"artifact_ref_override": "rdp:another-package"},
            "does not match RDP package artifact",
        ),
        (
            {"signed_approval_ref_override": "verified_signature:missing"},
            "unknown verified signed_approval_ref",
        ),
    ],
)
def test_rdp_publish_rejects_foreign_wrong_artifact_or_unverified_release_authority(
    tmp_path,
    monkeypatch,
    authority_kwargs,
    expected_detail,
):
    client, store, materializer, bundler, _exporter, _publisher, publish_store, source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    _write_sources(source_root)
    run_root = tmp_path / "runs"
    run_dir = _write_run(run_root)
    manifest = store.record_manifest(
        _manifest(artifact_hash=_artifact_hash(run_dir)),
        owner_user_id="u1",
        recorded_by="u1",
    )
    _record_trust_release_authority(manifest, **authority_kwargs)
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )
    _record_source_run_integrity(manifest, materializer, run_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/publish",
            json={
                "channel": "local_registry",
                "trust_release_ref": "release:v1",
                "trust_release_approval_ref": "trust_release_approval:release:v1",
            },
        )
        assert response.status_code == 422
        assert expected_detail in response.json()["detail"]
        assert publish_store.publications() == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_publish_api_404s_unknown_manifest(tmp_path, monkeypatch):
    client, _store, _materializer, _bundler, _exporter, _publisher, _publish_store, _source_root = _client_with_publish(
        tmp_path, monkeypatch
    )
    try:
        response = client.post("/api/research-os/rdp/manifests/rdp_missing/publish", json={})
        assert response.status_code == 404
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
