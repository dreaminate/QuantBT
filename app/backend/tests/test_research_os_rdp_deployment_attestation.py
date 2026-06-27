from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    PersistentRDPDeploymentAttestationStore,
    PersistentRDPDeploymentHealthCheckStore,
    PersistentRDPStore,
    RDPOpenPackageMaterializer,
    RDPManifest,
    RDPSourceFileBundler,
    RuntimeStatus,
)


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
        "approval_ref": "approval:live-1",
        "target_runtime": RuntimeStatus.LIVE,
        "deployment_refs": ("deploy:live-1",),
        "monitor_refs": ("monitor:weekly",),
        "rollback_plan_ref": "rollback:live-1",
        "retire_plan_ref": "retire:live-1",
        "llm_call_refs": ("llmcall:slot-fill",),
        "source_file_refs": ("source-file:strategy.py",),
    }
    data.update(overrides)
    return RDPManifest(**data)


def _client_with_rdp_attestation(tmp_path, monkeypatch):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    attestation_store = PersistentRDPDeploymentAttestationStore(tmp_path / "rdp_deployment_attestations.jsonl")
    monkeypatch.setattr(main, "RDP_STORE", store)
    monkeypatch.setattr(main, "RDP_PACKAGE_MATERIALIZER", materializer)
    monkeypatch.setattr(main, "RDP_SOURCE_FILE_BUNDLER", bundler)
    monkeypatch.setattr(main, "RDP_DEPLOYMENT_ATTESTATION_STORE", attestation_store)
    monkeypatch.setattr(main, "RDP_DEPLOYMENT_RUNNER", None)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store, materializer, bundler, attestation_store, source_root


def _client_with_rdp_health(tmp_path, monkeypatch):
    client, store, materializer, bundler, attestation_store, source_root = _client_with_rdp_attestation(
        tmp_path,
        monkeypatch,
    )
    health_store = PersistentRDPDeploymentHealthCheckStore(tmp_path / "rdp_deployment_health_checks.jsonl")
    monkeypatch.setattr(main, "RDP_DEPLOYMENT_HEALTH_CHECK_STORE", health_store)
    return client, store, materializer, bundler, attestation_store, health_store, source_root


def _write_source(source_root):
    (source_root / "strategy.py").write_text("def alpha(row):\n    return row['close']\n", encoding="utf-8")


def _materialize_and_bundle(materializer, bundler, manifest, source_root):
    _write_source(source_root)
    materializer.materialize(manifest)
    bundler.bundle(manifest, source_map={"source-file:strategy.py": "strategy.py"})


def _deployment_runner_result(**overrides):
    result = {
        "deployment_ref": "deploy:live-1",
        "deployment_status": "deployed",
        "deployment_event_ref": "deployment_event:rdp-live-1",
        "deployment_artifact_digest": "sha256:deployment-artifact",
        "monitor_refs": ["monitor:weekly"],
        "rollback_plan_ref": "rollback:live-1",
        "retire_plan_ref": "retire:live-1",
        "evidence_refs": ["deploy:evidence:summary", "deploy:health:refs-only"],
    }
    result.update(overrides)
    return result


def _deployment_health_payload(attestation_hash, **overrides):
    payload = {
        "deployment_attestation_hash": attestation_hash,
        "deployment_ref": "deploy:live-1",
        "health_status": "healthy",
        "health_check_refs": ["health:rdp-live-1"],
        "monitor_refs": ["monitor:weekly"],
        "rollback_plan_ref": "rollback:live-1",
        "rollback_readiness_ref": "rollback:ready:live-1",
        "rollback_drill_ref": "rollback:drill:live-1",
        "retire_plan_ref": "retire:live-1",
        "evidence_refs": ["health:evidence:summary"],
    }
    payload.update(overrides)
    return payload


def test_rdp_deployment_attestation_records_live_package_and_replays(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    store = PersistentRDPDeploymentAttestationStore(tmp_path / "rdp_deployment_attestations.jsonl")
    manifest = _manifest()
    _materialize_and_bundle(materializer, bundler, manifest, source_root)

    record = store.record_attestation(
        manifest,
        package_root=materializer.package_root,
        deployment_ref="deploy:live-1",
        attested_by="u1",
        attested_at="2026-06-26T00:00:00+00:00",
    )

    assert record.package_id == manifest.package_id
    assert record.target_runtime == RuntimeStatus.LIVE.value
    assert record.approval_ref == "approval:live-1"
    assert record.source_bundle_index_sha256.startswith("sha256:")
    assert record.attestation_hash.startswith("sha16:")

    reloaded = PersistentRDPDeploymentAttestationStore(store.path)
    replayed = reloaded.attestations(manifest.package_id)[0]
    assert replayed.attestation_hash == record.attestation_hash


def test_rdp_deployment_attestation_requires_source_bundle_by_default(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    store = PersistentRDPDeploymentAttestationStore(tmp_path / "rdp_deployment_attestations.jsonl")
    manifest = _manifest()
    materializer.materialize(manifest)

    with pytest.raises(ValueError, match="source bundle index is required"):
        store.record_attestation(
            manifest,
            package_root=materializer.package_root,
            deployment_ref="deploy:live-1",
            attested_by="u1",
        )

    assert not store.path.exists()


def test_rdp_deployment_attestation_rejects_undeclared_deployment_ref(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    store = PersistentRDPDeploymentAttestationStore(tmp_path / "rdp_deployment_attestations.jsonl")
    manifest = _manifest()
    _materialize_and_bundle(materializer, bundler, manifest, source_root)

    with pytest.raises(ValueError, match="deployment_ref is not declared"):
        store.record_attestation(
            manifest,
            package_root=materializer.package_root,
            deployment_ref="deploy:other",
            attested_by="u1",
        )


def test_rdp_deployment_attestation_rejects_mismatched_source_bundle_index(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    store = PersistentRDPDeploymentAttestationStore(tmp_path / "rdp_deployment_attestations.jsonl")
    manifest = _manifest()
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    index_path = tmp_path / "rdp_packages" / manifest.package_id / "source_files_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["package_id"] = "rdp_other"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(ValueError, match="package_id does not match"):
        store.record_attestation(
            manifest,
            package_root=materializer.package_root,
            deployment_ref="deploy:live-1",
            attested_by="u1",
        )


def test_rdp_deployment_attestation_rejects_tampered_manifest_file(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    store = PersistentRDPDeploymentAttestationStore(tmp_path / "rdp_deployment_attestations.jsonl")
    manifest = _manifest(source_file_refs=())
    package = materializer.materialize(manifest)
    (tmp_path / "rdp_packages" / manifest.package_id / "manifest.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest file does not match"):
        store.record_attestation(
            manifest,
            package_root=materializer.package_root,
            deployment_ref="deploy:live-1",
            attested_by="u1",
        )

    assert package.manifest_path.endswith("manifest.json")
    assert not store.path.exists()


def test_rdp_deployment_attestation_api_records_live_package(tmp_path, monkeypatch):
    client, store, materializer, bundler, attestation_store, source_root = _client_with_rdp_attestation(
        tmp_path,
        monkeypatch,
    )
    manifest = store.record_manifest(_manifest())
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/deployment_attestations",
            json={"deployment_ref": "deploy:live-1"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["deployment_ref"] == "deploy:live-1"
        assert body["attestation_hash"].startswith("sha16:")
        assert attestation_store.attestations(manifest.package_id)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_deployment_runner_default_disabled_without_partial_record(tmp_path, monkeypatch):
    client, store, materializer, bundler, attestation_store, source_root = _client_with_rdp_attestation(
        tmp_path,
        monkeypatch,
    )
    manifest = store.record_manifest(_manifest())
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/deployment_attestations/run",
            json={"deployment_ref": "deploy:live-1"},
        )
        assert response.status_code == 422
        assert "RDP deployment runner is not configured" in response.json()["detail"]
        assert attestation_store.attestations(manifest.package_id) == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_deployment_runner_records_attestation_from_fake_runner(tmp_path, monkeypatch):
    client, store, materializer, bundler, attestation_store, source_root = _client_with_rdp_attestation(
        tmp_path,
        monkeypatch,
    )
    captured_request = {}

    def fake_runner(request):
        captured_request.update(request)
        return _deployment_runner_result()

    monkeypatch.setattr(main, "RDP_DEPLOYMENT_RUNNER", fake_runner)
    manifest = store.record_manifest(_manifest())
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/deployment_attestations/run",
            json={"deployment_ref": "deploy:live-1"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["deployment_ref"] == "deploy:live-1"
        assert body["deployment_event_ref"] == "deployment_event:rdp-live-1"
        assert body["deployment_artifact_digest"] == "sha256:deployment-artifact"
        assert body["evidence_refs"] == ["deploy:evidence:summary", "deploy:health:refs-only"]
        assert body["attestation_hash"].startswith("sha16:")
        assert captured_request["package_id"] == manifest.package_id
        assert captured_request["deployment_ref"] == "deploy:live-1"
        assert captured_request["monitor_refs"] == ["monitor:weekly"]
        assert "package_path" not in captured_request
        assert "raw_package" not in captured_request
        assert "kubeconfig" not in captured_request
        record = attestation_store.attestations(manifest.package_id)[0]
        assert record.attestation_version == "rdp.deployment_attestation.v2"
        assert record.deployment_event_ref == "deployment_event:rdp-live-1"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


@pytest.mark.parametrize(
    ("runner_result", "expected_detail"),
    [
        (_deployment_runner_result(raw_deploy_payload={"image": "latest"}), "raw or secret-bearing field"),
        (_deployment_runner_result(stdout="deploy log"), "raw or secret-bearing field"),
        (_deployment_runner_result(deployment_status="failed"), "deployment_status=deployed"),
        (_deployment_runner_result(deployment_ref="deploy:other"), "deployment_ref does not match request"),
        (_deployment_runner_result(deployment_artifact_digest="sha256:artifact?token=secret"), "plaintext secret"),
    ],
)
def test_rdp_deployment_runner_rejects_bad_result_without_partial_record(
    tmp_path, monkeypatch, runner_result, expected_detail
):
    client, store, materializer, bundler, attestation_store, source_root = _client_with_rdp_attestation(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(main, "RDP_DEPLOYMENT_RUNNER", lambda _request: runner_result)
    manifest = store.record_manifest(_manifest())
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/deployment_attestations/run",
            json={"deployment_ref": "deploy:live-1"},
        )
        assert response.status_code == 422
        assert expected_detail in response.json()["detail"]
        assert attestation_store.attestations(manifest.package_id) == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_deployment_health_records_post_deploy_refs(tmp_path, monkeypatch):
    client, store, materializer, bundler, attestation_store, health_store, source_root = _client_with_rdp_health(
        tmp_path,
        monkeypatch,
    )
    manifest = store.record_manifest(_manifest())
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    attestation = attestation_store.record_attestation(
        manifest,
        package_root=materializer.package_root,
        deployment_ref="deploy:live-1",
        deployment_event_ref="deployment_event:rdp-live-1",
        deployment_artifact_digest="sha256:deployment-artifact",
        evidence_refs=("deploy:evidence:summary",),
        attested_by="u1",
    )
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/deployment_health_checks",
            json=_deployment_health_payload(attestation.attestation_hash),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["deployment_ref"] == "deploy:live-1"
        assert body["deployment_attestation_hash"] == attestation.attestation_hash
        assert body["health_status"] == "healthy"
        assert body["health_check_refs"] == ["health:rdp-live-1"]
        assert body["monitor_refs"] == ["monitor:weekly"]
        assert body["rollback_plan_ref"] == "rollback:live-1"
        assert body["rollback_readiness_ref"] == "rollback:ready:live-1"
        assert body["rollback_drill_ref"] == "rollback:drill:live-1"
        assert body["retire_plan_ref"] == "retire:live-1"
        assert body["proof_hash"].startswith("sha16:")
        assert len(health_store.health_checks(manifest.package_id)) == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_deployment_health_rejects_unknown_attestation_without_partial_record(tmp_path, monkeypatch):
    client, store, materializer, bundler, _attestation_store, health_store, source_root = _client_with_rdp_health(
        tmp_path,
        monkeypatch,
    )
    manifest = store.record_manifest(_manifest())
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/deployment_health_checks",
            json=_deployment_health_payload("sha16:deadbeefdeadbeef"),
        )
        assert response.status_code == 422
        assert "recorded deployment attestation" in response.json()["detail"]
        assert health_store.health_checks(manifest.package_id) == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


@pytest.mark.parametrize(
    ("payload_overrides", "expected_detail"),
    [
        ({"health_status": "degraded"}, "health_status=healthy"),
        ({"monitor_refs": []}, "monitor_refs are required"),
        ({"rollback_readiness_ref": ""}, "rollback_readiness_ref is required"),
        ({"raw_health_response": {"status": "ok"}}, "raw or secret-bearing field"),
        ({"evidence_refs": ["health:evidence?token=secret"]}, "plaintext secret"),
        ({"deployment_ref": "deploy:other"}, "deployment_ref does not match deployment attestation"),
    ],
)
def test_rdp_deployment_health_rejects_bad_payload_without_partial_record(
    tmp_path,
    monkeypatch,
    payload_overrides,
    expected_detail,
):
    client, store, materializer, bundler, attestation_store, health_store, source_root = _client_with_rdp_health(
        tmp_path,
        monkeypatch,
    )
    manifest = store.record_manifest(_manifest())
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    attestation = attestation_store.record_attestation(
        manifest,
        package_root=materializer.package_root,
        deployment_ref="deploy:live-1",
        deployment_event_ref="deployment_event:rdp-live-1",
        deployment_artifact_digest="sha256:deployment-artifact",
        evidence_refs=("deploy:evidence:summary",),
        attested_by="u1",
    )
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/deployment_health_checks",
            json=_deployment_health_payload(attestation.attestation_hash, **payload_overrides),
        )
        assert response.status_code == 422
        assert expected_detail in response.json()["detail"]
        assert health_store.health_checks(manifest.package_id) == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_deployment_attestation_api_404s_for_unknown_manifest(tmp_path, monkeypatch):
    client, _store, _materializer, _bundler, _attestation_store, _source_root = _client_with_rdp_attestation(
        tmp_path,
        monkeypatch,
    )
    try:
        response = client.post(
            "/api/research-os/rdp/manifests/rdp_missing/deployment_attestations",
            json={"deployment_ref": "deploy:live-1"},
        )
        assert response.status_code == 404
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
