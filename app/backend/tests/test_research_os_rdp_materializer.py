from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import PersistentRDPStore, RDPOpenPackageMaterializer, RDPManifest, RuntimeStatus


def _client_with_rdp_package_store(tmp_path, monkeypatch):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    monkeypatch.setattr(main, "RDP_STORE", store)
    monkeypatch.setattr(main, "RDP_PACKAGE_MATERIALIZER", materializer)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store, materializer


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


def test_rdp_materializer_writes_manifest_and_refs_index_without_source_payload(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    manifest = _manifest()

    package = materializer.materialize(manifest)

    manifest_path = tmp_path / "rdp_packages" / manifest.package_id / "manifest.json"
    refs_path = tmp_path / "rdp_packages" / manifest.package_id / "refs.json"
    assert package.manifest_path == str(manifest_path)
    assert package.refs_index_path == str(refs_path)
    assert manifest_path.exists()
    assert refs_path.exists()

    rendered_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    refs = json.loads(refs_path.read_text(encoding="utf-8"))
    assert rendered_manifest["package_id"] == manifest.package_id
    assert refs["source_file_refs"] == ["source-file:strategy.py", "source-file:README.md"]
    assert refs["compiler_artifact_refs"] == ["compiler_artifact:strategy:001"]
    assert refs["mathematical_spine_chain_refs"] == ["math_spine_chain:btc_momentum:v1"]
    assert refs["goal_entrypoint_coverage_refs"] == ["goal_entrypoint_coverage:strategy:001"]
    assert not (tmp_path / "rdp_packages" / manifest.package_id / "source_files").exists()
    assert "source_file_payload" not in refs


def test_rdp_materializer_is_idempotent_for_same_manifest(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    manifest = _manifest()

    first = materializer.materialize(manifest)
    second = materializer.materialize(manifest)

    assert second.manifest_hash == first.manifest_hash
    assert second.manifest_path == first.manifest_path
    assert second.refs_index_path == first.refs_index_path


def test_rdp_materializer_rejects_unsafe_package_id(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    manifest = _manifest(package_id="../escape")

    with pytest.raises(ValueError, match="package_id is unsafe"):
        materializer.materialize(manifest)

    assert not (tmp_path / "escape").exists()


def test_rdp_materialize_api_writes_package_for_recorded_manifest(tmp_path, monkeypatch):
    client, store, materializer = _client_with_rdp_package_store(tmp_path, monkeypatch)
    manifest = store.record_manifest(_manifest())
    try:
        response = client.post(f"/api/research-os/rdp/manifests/{manifest.package_id}/materialize", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["materialized_by"] == "u1"
        assert body["source_file_refs"] == ["source-file:strategy.py", "source-file:README.md"]
        assert (materializer.package_root / manifest.package_id / "manifest.json").exists()
        assert (materializer.package_root / manifest.package_id / "refs.json").exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_materialize_api_404s_for_unknown_manifest(tmp_path, monkeypatch):
    client, _store, _materializer = _client_with_rdp_package_store(tmp_path, monkeypatch)
    try:
        response = client.post("/api/research-os/rdp/manifests/rdp_missing/materialize", json={})
        assert response.status_code == 404
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
