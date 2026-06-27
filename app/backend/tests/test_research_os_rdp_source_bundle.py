from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
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
        "approval_ref": "approval:paper",
        "target_runtime": RuntimeStatus.PAPER,
        "llm_call_refs": ("llmcall:slot-fill",),
        "source_file_refs": ("source-file:strategy.py", "source-file:README.md"),
    }
    data.update(overrides)
    return RDPManifest(**data)


def _client_with_rdp_bundle(tmp_path, monkeypatch):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    monkeypatch.setattr(main, "RDP_STORE", store)
    monkeypatch.setattr(main, "RDP_PACKAGE_MATERIALIZER", materializer)
    monkeypatch.setattr(main, "RDP_SOURCE_FILE_BUNDLER", bundler)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store, materializer, bundler, source_root


def _write_sources(source_root):
    (source_root / "strategy.py").write_text("def alpha(row):\n    return row['close']\n", encoding="utf-8")
    (source_root / "README.md").write_text("# Research package\n", encoding="utf-8")


def test_rdp_source_file_bundler_copies_declared_files_without_payload_in_manifest_refs(tmp_path):
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    _write_sources(source_root)
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    manifest = _manifest()
    materializer.materialize(manifest)

    bundle = bundler.bundle(
        manifest,
        source_map={
            "source-file:strategy.py": "strategy.py",
            "source-file:README.md": "README.md",
        },
    )

    index = json.loads((tmp_path / "rdp_packages" / manifest.package_id / "source_files_index.json").read_text())
    refs = json.loads((tmp_path / "rdp_packages" / manifest.package_id / "refs.json").read_text())
    manifest_payload = json.loads((tmp_path / "rdp_packages" / manifest.package_id / "manifest.json").read_text())

    assert len(bundle.source_files) == 2
    assert index["package_id"] == manifest.package_id
    assert index["files_dir"] == "source_files"
    assert index["index_path"] == "source_files_index.json"
    assert "package_dir" not in index
    assert [entry["source_path"] for entry in index["source_files"]] == ["strategy.py", "README.md"]
    assert all(not entry["bundled_path"].startswith("/") for entry in index["source_files"])
    assert "source_file_payload" not in index
    assert "source_file_payload" not in refs
    assert "source_file_payload" not in manifest_payload
    strategy_entry = next(entry for entry in index["source_files"] if entry["source_file_ref"] == "source-file:strategy.py")
    assert (tmp_path / "rdp_packages" / manifest.package_id / strategy_entry["bundled_path"]).read_text(
        encoding="utf-8"
    ).startswith("def alpha")


def test_rdp_source_file_bundler_rejects_undeclared_ref(tmp_path):
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    _write_sources(source_root)
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    manifest = _manifest(source_file_refs=("source-file:strategy.py",))
    materializer.materialize(manifest)

    with pytest.raises(ValueError, match="source file ref not declared"):
        bundler.bundle(
            manifest,
            source_map={
                "source-file:strategy.py": "strategy.py",
                "source-file:README.md": "README.md",
            },
        )


def test_rdp_source_file_bundler_rejects_missing_declared_mapping(tmp_path):
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    _write_sources(source_root)
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    manifest = _manifest()
    materializer.materialize(manifest)

    with pytest.raises(ValueError, match="missing source file mapping"):
        bundler.bundle(manifest, source_map={"source-file:strategy.py": "strategy.py"})


def test_rdp_source_file_bundler_rejects_path_escape_and_absolute_path(tmp_path):
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    (tmp_path / "secret.env").write_text("safe-looking-but-outside=true\n", encoding="utf-8")
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    manifest = _manifest(source_file_refs=("source-file:strategy.py",))
    materializer.materialize(manifest)

    with pytest.raises(ValueError, match="escapes source root"):
        bundler.bundle(manifest, source_map={"source-file:strategy.py": "../secret.env"})

    with pytest.raises(ValueError, match="must be relative"):
        bundler.bundle(manifest, source_map={"source-file:strategy.py": str(tmp_path / "secret.env")})


def test_rdp_source_file_bundler_rejects_plaintext_secret(tmp_path):
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    (source_root / "strategy.py").write_text("api_key = 'sk-plaintext-1234567890'\n", encoding="utf-8")
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    manifest = _manifest(source_file_refs=("source-file:strategy.py",))
    materializer.materialize(manifest)

    with pytest.raises(ValueError, match="plaintext secret"):
        bundler.bundle(manifest, source_map={"source-file:strategy.py": "strategy.py"})


def test_rdp_source_file_bundler_rejects_oversized_and_non_utf8_files(tmp_path):
    source_root = tmp_path / "source_root"
    source_root.mkdir()
    materializer = RDPOpenPackageMaterializer(tmp_path / "rdp_packages")
    manifest = _manifest(source_file_refs=("source-file:strategy.py",))
    materializer.materialize(manifest)

    (source_root / "strategy.py").write_text("0123456789", encoding="utf-8")
    small_bundler = RDPSourceFileBundler(materializer.package_root, source_root, max_bytes=4)
    with pytest.raises(ValueError, match="max_bytes"):
        small_bundler.bundle(manifest, source_map={"source-file:strategy.py": "strategy.py"})

    (source_root / "strategy.py").write_bytes(b"\xff\xfe\xfd")
    bundler = RDPSourceFileBundler(materializer.package_root, source_root)
    with pytest.raises(ValueError, match="UTF-8"):
        bundler.bundle(manifest, source_map={"source-file:strategy.py": "strategy.py"})


def test_rdp_bundle_sources_api_materializes_and_copies_declared_files(tmp_path, monkeypatch):
    client, store, materializer, _bundler, source_root = _client_with_rdp_bundle(tmp_path, monkeypatch)
    _write_sources(source_root)
    manifest = store.record_manifest(_manifest())
    try:
        response = client.post(
            f"/api/research-os/rdp/manifests/{manifest.package_id}/bundle_sources",
            json={
                "source_map": {
                    "source-file:strategy.py": "strategy.py",
                    "source-file:README.md": "README.md",
                }
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["package_id"] == manifest.package_id
        assert body["bundled_by"] == "u1"
        assert len(body["source_files"]) == 2
        assert (materializer.package_root / manifest.package_id / "manifest.json").exists()
        assert (materializer.package_root / manifest.package_id / "source_files_index.json").exists()
        assert all("source_file_payload" not in item for item in body["source_files"])
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_bundle_sources_api_404s_for_unknown_manifest(tmp_path, monkeypatch):
    client, _store, _materializer, _bundler, _source_root = _client_with_rdp_bundle(tmp_path, monkeypatch)
    try:
        response = client.post("/api/research-os/rdp/manifests/rdp_missing/bundle_sources", json={"source_map": {}})
        assert response.status_code == 404
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
