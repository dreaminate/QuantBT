from __future__ import annotations

import json
import hashlib
from functools import partial
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.ide.service import IDEService
from app.lineage.ids import canonical_json
from app.research_os import (
    PersistentRDPSourceRunIntegrityStore,
    PersistentRDPStore,
    RDPOpenPackageMaterializer,
    RDPManifest,
    RDPSourceFileBundler,
    RuntimeStatus,
    rdp_run_artifact_hash,
)

RDPOpenPackageMaterializer = partial(RDPOpenPackageMaterializer, owner_user_id="u1")
RDPSourceFileBundler = partial(RDPSourceFileBundler, owner_user_id="u1")
PersistentRDPSourceRunIntegrityStore = partial(
    PersistentRDPSourceRunIntegrityStore, owner_user_id="u1"
)


STRATEGY_SOURCE = "def alpha(row):\n    return row['close']\n"


def _write_run(run_root, run_id: str = "bt1", *, strategy_source: str = STRATEGY_SOURCE, manifest_run_id=None):
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_manifest = {
        "run_id": manifest_run_id if manifest_run_id is not None else run_id,
        "owner_user_id": "u1",
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


def _prepared_ide_source_package(tmp_path):
    strategy_source = (
        "quantbt.emit_result({"
        "'equity_curve': ["
        "{'t': '2026-01-01', 'equity': 1.0, 'net_return': 0.0},"
        "{'t': '2026-01-02', 'equity': 1.02, 'net_return': 0.02}],"
        "'metadata': {'market': 'crypto_perp', 'frequency': '1d'}"
        "})"
    )
    run_root = tmp_path / "ide_runs"
    ide_service = IDEService(tmp_path / "ide.db", run_root=run_root)
    ide_service.save_strategy("alice", "immutable_rdp_source", strategy_source)
    ide_run = ide_service.run_strategy(
        "alice",
        "immutable_rdp_source",
        owner_user_id="u1",
    )
    assert ide_run.status == "ok"
    run_dir = run_root / ide_run.run_id
    ide_ref = f"ide_run:{ide_run.run_id}"
    manifest = _manifest(
        asset_refs=(ide_ref,),
        run_refs=(ide_ref,),
        artifact_hash=_artifact_hash(run_dir),
    )
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    materializer.materialize(manifest)
    bundler = RDPSourceFileBundler(
        materializer.package_root,
        tmp_path / "unused_source_root",
    )
    bundler.bundle_trusted_text_sources(
        manifest,
        source_texts={"source-file:strategy.py": (run_dir / "strategy.py").read_text(encoding="utf-8")},
    )
    return manifest, materializer, bundler, ide_service, ide_run, run_root, run_dir


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


def test_rdp_ide_run_integrity_binds_immutable_snapshot_and_replays(tmp_path):
    manifest, materializer, _bundler, ide_service, ide_run, run_root, run_dir = (
        _prepared_ide_source_package(tmp_path)
    )
    # Current draft drift is irrelevant: the package and integrity proof bind the frozen run snapshot.
    ide_service.save_strategy(
        "alice",
        "immutable_rdp_source",
        "quantbt.emit_result({'equity_curve': [{'t': 'changed', 'equity': 9}]})",
    )
    store = PersistentRDPSourceRunIntegrityStore(
        tmp_path / "rdp_source_run_integrity.jsonl"
    )

    record = store.record_integrity(
        manifest,
        package_root=materializer.package_root,
        run_root=run_root,
        run_id=ide_run.run_id,
        attested_by="u1",
        attested_at="2026-07-13T00:00:00+00:00",
    )

    assert record.run_ref == f"ide_run:{ide_run.run_id}"
    assert record.bundled_source_sha256 == record.run_strategy_sha256
    assert record.artifact_hash == _artifact_hash(run_dir)
    assert {path.name for path in run_dir.iterdir() if path.is_file()} >= {
        "run.json",
        "strategy.py",
        "portfolio.csv",
        "result.json",
    }
    replayed = PersistentRDPSourceRunIntegrityStore(store.path).records(manifest.package_id)
    assert replayed == [record]


@pytest.mark.parametrize(
    "artifact_name",
    ["strategy.py", "result.json", "portfolio.csv"],
)
def test_rdp_ide_run_integrity_rejects_mutated_snapshot_without_event(tmp_path, artifact_name):
    manifest, materializer, _bundler, _ide_service, ide_run, run_root, run_dir = (
        _prepared_ide_source_package(tmp_path)
    )
    (run_dir / artifact_name).write_text("mutated\n", encoding="utf-8")
    store = PersistentRDPSourceRunIntegrityStore(
        tmp_path / "rdp_source_run_integrity.jsonl"
    )

    with pytest.raises(ValueError, match="does not match|invalid"):
        store.record_integrity(
            manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id=ide_run.run_id,
            attested_by="u1",
        )
    assert store.records(manifest.package_id) == []
    assert not store.path.exists()


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("owner_user_id", "u2", "source owner"),
        ("ide_run_id", "ide_other", "source binding"),
    ],
)
def test_rdp_ide_run_integrity_rejects_owner_or_source_id_drift_without_event(
    tmp_path,
    field,
    value,
    error,
):
    manifest, materializer, _bundler, _ide_service, ide_run, run_root, run_dir = (
        _prepared_ide_source_package(tmp_path)
    )
    run_manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    run_manifest["source"][field] = value
    (run_dir / "run.json").write_text(
        canonical_json(run_manifest) + "\n",
        encoding="utf-8",
    )
    store = PersistentRDPSourceRunIntegrityStore(
        tmp_path / "rdp_source_run_integrity.jsonl"
    )

    with pytest.raises(ValueError, match=error):
        store.record_integrity(
            manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id=ide_run.run_id,
            attested_by="u1",
        )
    assert store.records(manifest.package_id) == []
    assert not store.path.exists()


def test_rdp_ide_run_integrity_rejects_mutated_bundled_source_without_event(tmp_path):
    manifest, materializer, _bundler, _ide_service, ide_run, run_root, _run_dir = (
        _prepared_ide_source_package(tmp_path)
    )
    package_dir = materializer.package_root / "_owners" / hashlib.sha256(b"u1").hexdigest() / manifest.package_id
    index = json.loads((package_dir / "source_files_index.json").read_text(encoding="utf-8"))
    bundled_path = package_dir / index["source_files"][0]["bundled_path"]
    bundled_path.write_text("mutated package source\n", encoding="utf-8")
    store = PersistentRDPSourceRunIntegrityStore(
        tmp_path / "rdp_source_run_integrity.jsonl"
    )

    with pytest.raises(ValueError, match="bundled source hash"):
        store.record_integrity(
            manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id=ide_run.run_id,
            attested_by="u1",
        )
    assert store.records(manifest.package_id) == []
    assert not store.path.exists()


@pytest.mark.parametrize("run_owner", [None, "u2"])
def test_rdp_source_run_integrity_rejects_ownerless_or_foreign_run_without_event(
    tmp_path,
    run_owner,
):
    run_root = tmp_path / "runs"
    run_dir = _write_run(run_root)
    run_manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run_owner is None:
        run_manifest.pop("owner_user_id", None)
    else:
        run_manifest["owner_user_id"] = run_owner
    (run_dir / "run.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = _manifest(artifact_hash=_artifact_hash(run_dir))
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    store = PersistentRDPSourceRunIntegrityStore(
        tmp_path / "rdp_source_run_integrity.jsonl"
    )

    with pytest.raises(ValueError, match="run.json is not owned by the package owner"):
        store.record_integrity(
            manifest,
            package_root=materializer.package_root,
            run_root=run_root,
            run_id="bt1",
            attested_by="u1",
        )
    assert store.records(manifest.package_id) == []
    assert not store.path.exists()


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
    manifest = store.record_manifest(
        _manifest(artifact_hash=_artifact_hash(run_dir)),
        owner_user_id="u1",
        recorded_by="u1",
    )
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


def test_rdp_ide_integrity_api_uses_ide_run_root_and_exact_server_run_id(
    tmp_path,
    monkeypatch,
):
    client, store, materializer, bundler, integrity_store, _source_root, run_root = (
        _client_with_source_run_integrity(tmp_path, monkeypatch)
    )
    ide_service = IDEService(
        tmp_path / "ide.db",
        run_root=tmp_path / "ide_runs",
    )
    monkeypatch.setattr(main, "IDE_SERVICE", ide_service)
    strategy_source = (
        "quantbt.emit_result({'equity_curve': ["
        "{'t': '2026-01-01', 'equity': 1.0},"
        "{'t': '2026-01-02', 'equity': 1.1}]})"
    )
    ide_service.save_strategy("u1", "integrity_api", strategy_source)
    ide_run = ide_service.run_strategy(
        "u1",
        "integrity_api",
        owner_user_id="u1",
    )
    ide_run_dir = ide_service.run_root / ide_run.run_id
    ide_ref = f"ide_run:{ide_run.run_id}"
    manifest = store.record_manifest(
        _manifest(
            asset_refs=(ide_ref,),
            run_refs=(ide_ref,),
            source_file_refs=("source_file:strategy.py",),
            artifact_hash=_artifact_hash(ide_run_dir),
        ),
        owner_user_id="u1",
        recorded_by="u1",
    )
    materializer.materialize(manifest)
    bundler.bundle_trusted_text_sources(
        manifest,
        source_texts={"source_file:strategy.py": strategy_source},
    )
    assert run_root != ide_service.run_root

    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/source_run_integrity_attestations",
            json={},
        )
        assert response.status_code == 200, response.text
        assert response.json()["run_id"] == ide_run.run_id
        assert response.json()["run_ref"] == ide_ref
        assert integrity_store.records(manifest.package_id)

        conflict = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/source_run_integrity_attestations",
            json={"run_id": "different"},
        )
        assert conflict.status_code == 422
        assert "conflicts" in conflict.json()["detail"]
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
