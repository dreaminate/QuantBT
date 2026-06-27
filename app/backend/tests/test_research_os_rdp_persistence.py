from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import PersistentRDPStore, RDPManifest, RuntimeStatus


def _client_with_rdp_store(tmp_path, monkeypatch):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    monkeypatch.setattr(main, "RDP_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store


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
        "source_file_refs": ("source-file:strategy.py",),
    }
    data.update(overrides)
    return RDPManifest(**data)


def _payload(**overrides) -> dict:
    manifest = _manifest(**overrides)
    return {"manifest": manifest.to_open_dict()}


def test_persistent_rdp_store_replays_valid_manifest(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    manifest = store.record_manifest(_manifest())

    reloaded = PersistentRDPStore(path)
    replayed = reloaded.manifest(manifest.package_id)
    assert replayed.package_id == manifest.package_id
    assert replayed.reproducibility_command == "python -m quantbt.run --run r1"
    assert replayed.source_file_refs == ("source-file:strategy.py",)
    assert replayed.compiler_artifact_refs == ("compiler_artifact:strategy:001",)
    assert replayed.mathematical_spine_chain_refs == ("math_spine_chain:btc_momentum:v1",)
    assert replayed.goal_entrypoint_coverage_refs == ("goal_entrypoint_coverage:strategy:001",)


def test_persistent_rdp_store_rejects_invalid_manifest_without_persisting(tmp_path):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")

    with pytest.raises(ValueError, match="missing_dataset_version_refs"):
        store.record_manifest(_manifest(dataset_version_refs=(), reproducibility_command=""))

    assert not store.path.exists()


def test_persistent_rdp_store_rejects_live_manifest_without_runtime_refs(tmp_path):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    manifest = _manifest(
        target_runtime=RuntimeStatus.LIVE,
        deployment_refs=(),
        monitor_refs=(),
        rollback_plan_ref=None,
        retire_plan_ref=None,
    )

    with pytest.raises(ValueError, match="missing_deployment_refs"):
        store.record_manifest(manifest)


def test_rdp_api_records_lists_and_reads_manifest_without_source_payload(tmp_path, monkeypatch):
    client, _store = _client_with_rdp_store(tmp_path, monkeypatch)
    try:
        created = client.post("/api/research-os/rdp/manifests", json=_payload())
        assert created.status_code == 200
        package_id = created.json()["package_id"]
        assert package_id.startswith("rdp_")

        listed = client.get("/api/research-os/rdp/manifests")
        assert listed.status_code == 200
        summary = listed.json()["manifests"][0]
        assert summary["package_id"] == package_id
        assert summary["target_runtime"] == RuntimeStatus.PAPER.value
        assert summary["market_data_use_validation_refs"] == ["market_data_use:BTCUSDT_1d:backtest"]
        assert "source_file_payload" not in summary

        detail = client.get(f"/api/research-os/rdp/manifests/{package_id}")
        assert detail.status_code == 200
        manifest = detail.json()["manifest"]
        assert manifest["package_id"] == package_id
        assert manifest["source_file_refs"] == ["source-file:strategy.py"]
        assert manifest["market_data_use_validation_refs"] == ["market_data_use:BTCUSDT_1d:backtest"]
        assert manifest["compiler_artifact_refs"] == ["compiler_artifact:strategy:001"]
        assert manifest["mathematical_spine_chain_refs"] == ["math_spine_chain:btc_momentum:v1"]
        assert manifest["goal_entrypoint_coverage_refs"] == ["goal_entrypoint_coverage:strategy:001"]
        assert "source_file_payload" not in manifest
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_api_rejects_invalid_manifest_without_persisting(tmp_path, monkeypatch):
    client, store = _client_with_rdp_store(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/rdp/manifests",
            json=_payload(dataset_version_refs=(), reproducibility_command=""),
        )
        assert rejected.status_code == 422
        assert not store.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_api_rejects_unrecorded_upstream_refs_without_persisting(tmp_path, monkeypatch):
    client, store = _client_with_rdp_store(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/rdp/manifests",
            json=_payload(compiler_artifact_refs=("compiler_artifact:missing",)),
        )
        assert rejected.status_code == 422
        assert "compiler_artifact_ref" in rejected.json()["detail"]
        assert not store.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_api_rejects_unknown_market_data_use_refs_without_persisting(tmp_path, monkeypatch):
    client, store = _client_with_rdp_store(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/rdp/manifests",
            json=_payload(market_data_use_validation_refs=("market_data_use:missing",)),
        )
        assert rejected.status_code == 422
        assert "market_data_use_validation_ref" in rejected.json()["detail"]
        assert not store.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_api_rejects_market_data_use_refs_that_do_not_cover_data_refs(tmp_path, monkeypatch):
    client, store = _client_with_rdp_store(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/rdp/manifests",
            json=_payload(data_refs=("dataset:ETHUSDT_1d",)),
        )
        assert rejected.status_code == 422
        assert "do not cover data_ref" in rejected.json()["detail"]
        assert not store.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_persistent_rdp_store_rejects_malformed_history(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    path.write_text(
        '{"schema_version":1,"event_type":"rdp_manifest_recorded","manifest":{"research_question":"x"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid persisted RDP row"):
        PersistentRDPStore(path)
