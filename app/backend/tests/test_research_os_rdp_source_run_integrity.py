from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    PersistentRDPSourceRunIntegrityStore,
    PersistentRDPStore,
    RDPOpenPackageMaterializer,
    RDPManifest,
    RDPSourceFileBundler,
    RuntimeStatus,
    rdp_run_artifact_hash,
)


STRATEGY_SOURCE = "def alpha(row):\n    return row['close']\n"


def _write_run(run_root, run_id: str = "bt1", *, strategy_source: str = STRATEGY_SOURCE, manifest_run_id=None):
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_manifest = {
        "run_id": manifest_run_id if manifest_run_id is not None else run_id,
        "strategy_name": "momentum",
        "status": "completed",
        "market": "crypto_perp",
        "frequency": "1d",
        "metrics": {"sharpe": 1.23},
    }
    (run_dir / "run.json").write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "strategy.py").write_text(strategy_source, encoding="utf-8")
    (run_dir / "portfolio.csv").write_text("timestamp,equity,net_return\n2026-01-01,1,0\n2026-01-02,1.01,0.01\n", encoding="utf-8")
    return run_dir


def _artifact_hash(run_dir) -> str:
    return rdp_run_artifact_hash(
        run_manifest_sha256="sha256:" + hashlib.sha256((run_dir / "run.json").read_bytes()).hexdigest(),
        run_strategy_sha256="sha256:" + hashlib.sha256((run_dir / "strategy.py").read_bytes()).hexdigest(),
        run_portfolio_sha256="sha256:" + hashlib.sha256((run_dir / "portfolio.csv").read_bytes()).hexdigest(),
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
        "reproducibility_command": "python -m quantbt.run --run bt1",
        "artifact_hash": "sha256:placeholder",
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


def _write_source(source_root, *, strategy_source: str = STRATEGY_SOURCE):
    (source_root / "strategy.py").write_text(strategy_source, encoding="utf-8")


def _materialize_and_bundle(materializer, bundler, manifest, source_root):
    _write_source(source_root)
    materializer.materialize(manifest)
    bundler.bundle(manifest, source_map={"source-file:strategy.py": "strategy.py"})


def _prepared_package(tmp_path):
    run_root = tmp_path / "runs"
    run_dir = _write_run(run_root)
    manifest = _manifest(artifact_hash=_artifact_hash(run_dir))
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    return manifest, materializer, bundler, source_root, run_root, run_dir


def _client_with_source_run_integrity(tmp_path, monkeypatch):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    integrity_store = PersistentRDPSourceRunIntegrityStore(tmp_path / "rdp_source_run_integrity.jsonl")
    run_root = tmp_path / "runs"
    monkeypatch.setattr(main, "RDP_STORE", store)
    monkeypatch.setattr(main, "RDP_PACKAGE_MATERIALIZER", materializer)
    monkeypatch.setattr(main, "RDP_SOURCE_FILE_BUNDLER", bundler)
    monkeypatch.setattr(main, "RDP_SOURCE_RUN_INTEGRITY_STORE", integrity_store)
    monkeypatch.setattr(main, "RUN_ROOT", run_root)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store, materializer, bundler, integrity_store, source_root, run_root


def test_rdp_source_run_integrity_records_package_source_to_run_and_replays(tmp_path):
    manifest, materializer, _bundler, _source_root, run_root, _run_dir = _prepared_package(tmp_path)
    store = PersistentRDPSourceRunIntegrityStore(tmp_path / "rdp_source_run_integrity.jsonl")

    record = store.record_integrity(
        manifest,
        package_root=materializer.package_root,
        run_root=run_root,
        run_id="bt1",
        attested_by="u1",
        attested_at="2026-06-26T00:00:00+00:00",
    )

    assert record.package_id == manifest.package_id
    assert record.run_ref == "run:bt1"
    assert record.source_file_ref == "source-file:strategy.py"
    assert record.artifact_hash == manifest.artifact_hash
    assert record.bundled_source_sha256 == record.run_strategy_sha256
    assert record.integrity_hash.startswith("sha16:")

    reloaded = PersistentRDPSourceRunIntegrityStore(store.path)
    replayed = reloaded.records(manifest.package_id)[0]
    assert replayed.integrity_hash == record.integrity_hash


def test_rdp_source_run_integrity_requires_source_bundle(tmp_path):
    run_root = tmp_path / "runs"
    run_dir = _write_run(run_root)
    manifest = _manifest(artifact_hash=_artifact_hash(run_dir))
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    materializer.materialize(manifest)
    store = PersistentRDPSourceRunIntegrityStore(tmp_path / "rdp_source_run_integrity.jsonl")

    with pytest.raises(ValueError, match="source bundle index is required"):
        store.record_integrity(
            manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id="bt1",
            attested_by="u1",
        )


def test_rdp_source_run_integrity_rejects_undeclared_run_id(tmp_path):
    manifest, materializer, _bundler, _source_root, run_root, _run_dir = _prepared_package(tmp_path)
    wrong_manifest = _manifest(artifact_hash=manifest.artifact_hash, run_refs=("run:other",))
    wrong_source_root = tmp_path / "source_root_wrong_run"
    wrong_source_root.mkdir()
    wrong_bundler = RDPSourceFileBundler(materializer.package_root, wrong_source_root)
    _materialize_and_bundle(materializer, wrong_bundler, wrong_manifest, wrong_source_root)
    store = PersistentRDPSourceRunIntegrityStore(tmp_path / "rdp_source_run_integrity.jsonl")

    with pytest.raises(ValueError, match="not declared"):
        store.record_integrity(
            wrong_manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id="bt1",
            attested_by="u1",
        )


def test_rdp_source_run_integrity_rejects_artifact_hash_mismatch(tmp_path):
    _manifest_ok, materializer, _bundler, _source_root, run_root, _run_dir = _prepared_package(tmp_path)
    manifest = _manifest(artifact_hash="sha256:wrong")
    wrong_source_root = tmp_path / "source_root_wrong_artifact"
    wrong_source_root.mkdir()
    wrong_bundler = RDPSourceFileBundler(materializer.package_root, wrong_source_root)
    _materialize_and_bundle(materializer, wrong_bundler, manifest, wrong_source_root)
    store = PersistentRDPSourceRunIntegrityStore(tmp_path / "rdp_source_run_integrity.jsonl")

    with pytest.raises(ValueError, match="artifact_hash does not match"):
        store.record_integrity(
            manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id="bt1",
            attested_by="u1",
        )


def test_rdp_source_run_integrity_rejects_source_mismatch_and_run_manifest_mismatch(tmp_path):
    manifest, materializer, _bundler, _source_root, run_root, run_dir = _prepared_package(tmp_path)
    (run_dir / "strategy.py").write_text("def alpha(row):\n    return -1\n", encoding="utf-8")
    store = PersistentRDPSourceRunIntegrityStore(tmp_path / "rdp_source_run_integrity.jsonl")

    with pytest.raises(ValueError, match="bundled source does not match"):
        store.record_integrity(
            manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id="bt1",
            attested_by="u1",
        )

    clean_run_root = tmp_path / "runs2"
    bad_run_dir = _write_run(clean_run_root, manifest_run_id="other")
    bad_manifest = _manifest(artifact_hash=_artifact_hash(bad_run_dir))
    clean_materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages2")
    clean_source_root = tmp_path / "source_root2"
    clean_source_root.mkdir()
    clean_bundler = RDPSourceFileBundler(clean_materializer.package_root, clean_source_root)
    _materialize_and_bundle(clean_materializer, clean_bundler, bad_manifest, clean_source_root)

    with pytest.raises(ValueError, match="run_id does not match"):
        store.record_integrity(
            bad_manifest,
            package_root=clean_materializer.package_root,
            run_root=clean_run_root,
            run_id="bt1",
            attested_by="u1",
        )


def test_rdp_source_run_integrity_rejects_run_id_path_escape(tmp_path):
    manifest, materializer, _bundler, _source_root, run_root, _run_dir = _prepared_package(tmp_path)
    store = PersistentRDPSourceRunIntegrityStore(tmp_path / "rdp_source_run_integrity.jsonl")

    with pytest.raises(ValueError, match="run_id is unsafe"):
        store.record_integrity(
            manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id="../bt1",
            attested_by="u1",
        )


def test_rdp_source_run_integrity_api_records_attestation(tmp_path, monkeypatch):
    client, store, materializer, bundler, integrity_store, source_root, run_root = _client_with_source_run_integrity(
        tmp_path,
        monkeypatch,
    )
    run_dir = _write_run(run_root)
    manifest = store.record_manifest(_manifest(artifact_hash=_artifact_hash(run_dir)))
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/source_run_integrity_attestations",
            json={"run_id": "bt1"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["run_ref"] == "run:bt1"
        assert body["artifact_hash"] == manifest.artifact_hash
        assert body["integrity_hash"].startswith("sha16:")
        assert integrity_store.records(manifest.package_id)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_source_run_integrity_api_404s_for_unknown_manifest(tmp_path, monkeypatch):
    client, _store, _materializer, _bundler, _integrity_store, _source_root, _run_root = (
        _client_with_source_run_integrity(tmp_path, monkeypatch)
    )
    try:
        response = client.post(
            "/api/research-os/rdp/manifests/rdp_missing/source_run_integrity_attestations",
            json={"run_id": "bt1"},
        )
        assert response.status_code == 404
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
