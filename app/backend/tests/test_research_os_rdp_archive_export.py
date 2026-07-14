from __future__ import annotations

import io
import hashlib
import zipfile
from functools import partial
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    PersistentRDPStore,
    RDPOpenPackageMaterializer,
    RDPPackageArchiveExporter,
    RDPManifest,
    RDPSourceFileBundler,
    RuntimeStatus,
)

RDPOpenPackageMaterializer = partial(RDPOpenPackageMaterializer, owner_user_id="u1")
RDPSourceFileBundler = partial(RDPSourceFileBundler, owner_user_id="u1")
RDPPackageArchiveExporter = partial(RDPPackageArchiveExporter, owner_user_id="u1")


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


def _materialize_and_bundle(materializer, bundler, manifest, source_root):
    _write_sources(source_root)
    materializer.materialize(manifest)
    bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )


def _client_with_rdp_archive(tmp_path, monkeypatch):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    exporter = RDPPackageArchiveExporter(materializer.package_root)
    monkeypatch.setattr(main, "RDP_STORE", store)
    monkeypatch.setattr(main, "RDP_PACKAGE_MATERIALIZER", materializer)
    monkeypatch.setattr(main, "RDP_SOURCE_FILE_BUNDLER", bundler)
    monkeypatch.setattr(main, "RDP_PACKAGE_ARCHIVE_EXPORTER", exporter)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store, materializer, bundler, exporter, source_root


def test_rdp_package_archive_exporter_writes_deterministic_zip_with_package_files(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    exporter = RDPPackageArchiveExporter(materializer.package_root)
    manifest = _manifest()
    _materialize_and_bundle(materializer, bundler, manifest, source_root)

    first = exporter.export(manifest)
    first_bytes = (_owned_root(tmp_path / "rdp_packages") / "_archives" / f"{manifest.package_id}.zip").read_bytes()
    second = exporter.export(manifest)
    second_bytes = (_owned_root(tmp_path / "rdp_packages") / "_archives" / f"{manifest.package_id}.zip").read_bytes()

    assert first.archive_sha256 == second.archive_sha256
    assert first_bytes == second_bytes
    assert first.file_count == 5
    assert first.included_paths == second.included_paths
    assert not any("_archives" in path for path in first.included_paths)
    with zipfile.ZipFile(io.BytesIO(first_bytes)) as archive:
        names = archive.namelist()
        assert f"{manifest.package_id}/manifest.json" in names
        assert f"{manifest.package_id}/refs.json" in names
        assert f"{manifest.package_id}/source_files_index.json" in names
        assert sum(name.startswith(f"{manifest.package_id}/source_files/") for name in names) == 2
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_rdp_package_archive_exporter_requires_materialized_package(tmp_path):
    exporter = RDPPackageArchiveExporter(tmp_path / "rdp_packages")

    with pytest.raises(ValueError, match="materialized before archive export"):
        exporter.export(_manifest())


def test_rdp_package_archive_exporter_rejects_reserved_package_id(tmp_path):
    with pytest.raises(ValueError, match="canonical content identity"):
        _manifest(package_id="_archives", source_file_refs=())


def test_rdp_package_archive_exporter_requires_source_bundle_for_declared_sources(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    exporter = RDPPackageArchiveExporter(materializer.package_root)
    manifest = _manifest()
    materializer.materialize(manifest)

    with pytest.raises(ValueError, match="source bundle index is required"):
        exporter.export(manifest)


def test_rdp_package_archive_exporter_rejects_tampered_manifest_file(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    exporter = RDPPackageArchiveExporter(materializer.package_root)
    manifest = _manifest(source_file_refs=())
    materializer.materialize(manifest)
    (_owned_root(materializer.package_root) / manifest.package_id / "manifest.json").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="manifest file does not match"):
        exporter.export(manifest)


def test_rdp_package_archive_exporter_rejects_symlink_escape(tmp_path):
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    exporter = RDPPackageArchiveExporter(materializer.package_root)
    manifest = _manifest(source_file_refs=())
    materializer.materialize(manifest)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not include\n", encoding="utf-8")

    try:
        (_owned_root(materializer.package_root) / manifest.package_id / "leak.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(ValueError, match="refuses symlink"):
        exporter.export(manifest)


def test_rdp_package_archive_api_returns_downloadable_zip(tmp_path, monkeypatch):
    client, store, materializer, bundler, _exporter, source_root = _client_with_rdp_archive(tmp_path, monkeypatch)
    manifest = store.record_manifest(
        _manifest(), owner_user_id="u1", recorded_by="u1"
    )
    _materialize_and_bundle(materializer, bundler, manifest, source_root)
    try:
        response = client.get(f"/api/research-os/rdp/manifests/{manifest.package_id}/archive")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["x-rdp-archive-sha256"].startswith("sha256:")
        assert response.headers["x-rdp-archive-file-count"] == "5"
        assert f'{manifest.package_id}.zip' in response.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert f"{manifest.package_id}/manifest.json" in archive.namelist()
            assert f"{manifest.package_id}/source_files_index.json" in archive.namelist()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_package_archive_api_404s_for_unknown_manifest(tmp_path, monkeypatch):
    client, _store, _materializer, _bundler, _exporter, _source_root = _client_with_rdp_archive(tmp_path, monkeypatch)
    try:
        response = client.get("/api/research-os/rdp/manifests/rdp_missing/archive")
        assert response.status_code == 404
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
