from __future__ import annotations

import json
import multiprocessing
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import PersistentRDPStore, RDPManifest, RuntimeStatus
from app.research_os import rdp as rdp_module
from app.research_os.rdp import RDPStoreCommitUncertain


def _record_rdp_manifest_in_child(
    path: str,
    raw_manifest: dict,
    owner_user_id: str,
) -> None:
    store = PersistentRDPStore(path)
    store.record_manifest(
        RDPManifest(**raw_manifest),
        owner_user_id=owner_user_id,
        recorded_by=owner_user_id,
    )


def _record_rdp_manifest_after_gate(
    path: str,
    raw_manifest: dict,
    owner_user_id: str,
    ready,
    start,
) -> None:
    store = PersistentRDPStore(path)
    ready.set()
    if not start.wait(10.0):
        raise RuntimeError("RDP concurrent writer start gate timed out")
    store.record_manifest(
        RDPManifest(**raw_manifest),
        owner_user_id=owner_user_id,
        recorded_by=owner_user_id,
    )


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


def _legacy_v1_manifest_payload(manifest: RDPManifest) -> dict:
    legacy_fields = {
        "research_question",
        "graph_refs",
        "data_refs",
        "dataset_version_refs",
        "market_data_use_validation_refs",
        "ingestion_skill_refs",
        "mathematical_refs",
        "theory_binding_refs",
        "consistency_check_refs",
        "methodology_choice_refs",
        "responsibility_refs",
        "asset_refs",
        "code_refs",
        "environment_lock_ref",
        "reproducibility_command",
        "artifact_hash",
        "test_refs",
        "run_refs",
        "honest_n_refs",
        "cost_and_execution_assumptions",
        "attribution_refs",
        "known_limits",
        "unverified_residuals",
        "verifier_verdict_ref",
        "compiler_artifact_refs",
        "mathematical_spine_chain_refs",
        "goal_entrypoint_coverage_refs",
        "approval_ref",
        "deployment_refs",
        "monitor_refs",
        "rollback_plan_ref",
        "retire_plan_ref",
        "target_runtime",
        "llm_call_refs",
        "source_file_refs",
        "package_id",
        "manifest_version",
    }
    payload = {
        key: value
        for key, value in manifest.to_open_dict().items()
        if key in legacy_fields
    }
    payload["manifest_version"] = "rdp.v2"
    payload["package_id"] = "rdp_" + rdp_module.content_hash(
        {
            "manifest_version": payload["manifest_version"],
            "research_question": payload["research_question"],
            "graph_refs": payload["graph_refs"],
            "asset_refs": payload["asset_refs"],
            "artifact_hash": payload["artifact_hash"],
            "market_data_use_validation_refs": payload[
                "market_data_use_validation_refs"
            ],
            "compiler_artifact_refs": payload["compiler_artifact_refs"],
            "mathematical_spine_chain_refs": payload[
                "mathematical_spine_chain_refs"
            ],
            "goal_entrypoint_coverage_refs": payload[
                "goal_entrypoint_coverage_refs"
            ],
            "run_refs": payload["run_refs"],
        }
    )
    return payload


def _payload(**overrides) -> dict:
    manifest = _manifest(**overrides)
    return {"manifest": manifest.to_open_dict()}


def _record(store: PersistentRDPStore, manifest: RDPManifest) -> RDPManifest:
    return store.record_manifest(
        manifest,
        owner_user_id="u1",
        recorded_by="u1",
    )


def test_persistent_rdp_store_replays_valid_manifest(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    manifest = _record(store, _manifest())

    reloaded = PersistentRDPStore(path)
    replayed = reloaded.manifest(manifest.package_id, owner_user_id="u1")
    assert replayed.package_id == manifest.package_id
    assert replayed.reproducibility_command == "python -m quantbt.run --run r1"
    assert replayed.source_file_refs == ("source-file:strategy.py",)
    assert replayed.compiler_artifact_refs == ("compiler_artifact:strategy:001",)
    assert replayed.mathematical_spine_chain_refs == ("math_spine_chain:btc_momentum:v1",)
    assert replayed.goal_entrypoint_coverage_refs == ("goal_entrypoint_coverage:strategy:001",)


def test_persistent_rdp_store_accepts_attested_explicit_zero_residuals(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    manifest = _record(
        store,
        _manifest(
            unverified_residuals=(),
            residual_attestation="review:all-known-residuals-resolved:v1",
        ),
    )

    replayed = PersistentRDPStore(path).manifest(
        manifest.package_id,
        owner_user_id="u1",
    )
    assert replayed.unverified_residuals == ()
    assert replayed.residual_attestation == "review:all-known-residuals-resolved:v1"


def test_persistent_rdp_store_rejects_unattested_zero_residuals(tmp_path):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")

    with pytest.raises(ValueError, match="missing_residual_attestation"):
        _record(store, _manifest(unverified_residuals=(), residual_attestation=""))

    assert not store.path.exists()


def test_persistent_rdp_store_preserves_json_legal_unicode_line_separators(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    question = "line separator:\u2028 paragraph separator:\u2029 still one JSONL record"
    manifest = _record(store, _manifest(research_question=question))

    raw = path.read_bytes()
    assert b"\xe2\x80\xa8" in raw
    assert b"\xe2\x80\xa9" in raw
    assert len(raw.split(b"\n")) == 2

    replayed = PersistentRDPStore(path)
    assert replayed.manifest(manifest.package_id, owner_user_id="u1").research_question == question


def test_persistent_rdp_store_isolates_same_content_by_owner_across_replay(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    manifest = _manifest()
    store.record_manifest(
        manifest,
        owner_user_id="owner-a",
        recorded_by="same-display-name",
    )
    store.record_manifest(
        manifest,
        owner_user_id="owner-b",
        recorded_by="same-display-name",
    )

    assert store.manifests(owner_user_id="owner-a") == [manifest]
    assert store.manifests(owner_user_id="owner-b") == [manifest]
    with pytest.raises(KeyError):
        store.manifest(manifest.package_id, owner_user_id="owner-c")

    replayed = PersistentRDPStore(path)
    assert replayed.manifest(manifest.package_id, owner_user_id="owner-a") == manifest
    assert replayed.manifest(manifest.package_id, owner_user_id="owner-b") == manifest


def test_persistent_rdp_store_refreshes_long_lived_instances_in_both_directions(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    first_store = PersistentRDPStore(path)
    second_store = PersistentRDPStore(path)
    first = _manifest(research_question="first cross-instance RDP")
    second = _manifest(research_question="second cross-instance RDP")

    first_store.record_manifest(first, owner_user_id="u1", recorded_by="u1")
    assert second_store.manifest(first.package_id, owner_user_id="u1") == first

    second_store.record_manifest(second, owner_user_id="u1", recorded_by="u1")
    assert first_store.manifests(owner_user_id="u1") == [first, second]


def test_persistent_rdp_store_refreshes_after_external_process_commit(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    long_lived = PersistentRDPStore(path)
    manifest = _manifest(research_question="child process RDP")
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_record_rdp_manifest_in_child,
        args=(str(path), manifest.to_open_dict(), "u1"),
    )

    process.start()
    process.join(15.0)

    assert process.exitcode == 0
    assert long_lived.manifest(manifest.package_id, owner_user_id="u1") == manifest


def test_persistent_rdp_store_simultaneous_distinct_writers_preserve_both_events(
    tmp_path,
):
    path = tmp_path / "rdp_manifests.jsonl"
    first = _manifest(research_question="simultaneous distinct writer one")
    second = _manifest(research_question="simultaneous distinct writer two")
    context = multiprocessing.get_context("spawn")
    ready = (context.Event(), context.Event())
    start = context.Event()
    processes = (
        context.Process(
            target=_record_rdp_manifest_after_gate,
            args=(str(path), first.to_open_dict(), "u1", ready[0], start),
        ),
        context.Process(
            target=_record_rdp_manifest_after_gate,
            args=(str(path), second.to_open_dict(), "u1", ready[1], start),
        ),
    )

    for process in processes:
        process.start()
    try:
        assert all(event.wait(10.0) for event in ready)
        start.set()
        for process in processes:
            process.join(15.0)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5.0)

    assert [process.exitcode for process in processes] == [0, 0]
    replayed = PersistentRDPStore(path)
    assert set(replayed.manifests(owner_user_id="u1")) == {first, second}
    assert len(path.read_text(encoding="utf-8").split("\n")) == 3


def test_persistent_rdp_store_simultaneous_identical_writers_emit_one_event(
    tmp_path,
):
    path = tmp_path / "rdp_manifests.jsonl"
    manifest = _manifest(research_question="simultaneous identical writer")
    context = multiprocessing.get_context("spawn")
    ready = (context.Event(), context.Event())
    start = context.Event()
    processes = tuple(
        context.Process(
            target=_record_rdp_manifest_after_gate,
            args=(str(path), manifest.to_open_dict(), "u1", ready[index], start),
        )
        for index in range(2)
    )

    for process in processes:
        process.start()
    try:
        assert all(event.wait(10.0) for event in ready)
        start.set()
        for process in processes:
            process.join(15.0)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5.0)

    assert [process.exitcode for process in processes] == [0, 0]
    replayed = PersistentRDPStore(path)
    assert replayed.manifests(owner_user_id="u1") == [manifest]
    assert len([line for line in path.read_text(encoding="utf-8").split("\n") if line]) == 1


def test_persistent_rdp_store_stale_identical_retry_is_singleton(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    first_store = PersistentRDPStore(path)
    stale_store = PersistentRDPStore(path)
    manifest = _manifest(research_question="idempotent stale retry")

    first_store.record_manifest(manifest, owner_user_id="u1", recorded_by="u1")
    committed = path.read_bytes()
    assert stale_store.record_manifest(
        manifest,
        owner_user_id="u1",
        recorded_by="retrying-worker",
    ) == manifest

    assert path.read_bytes() == committed
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_persistent_rdp_store_rejects_different_content_collision_without_write(tmp_path):
    class _ForgedCollisionManifest(RDPManifest):
        @property
        def canonical_package_id(self) -> str:
            return self.package_id

    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    first = _manifest(research_question="canonical package")
    store.record_manifest(first, owner_user_id="u1", recorded_by="u1")
    before = path.read_bytes()
    forged = _ForgedCollisionManifest(
        **_manifest(research_question="different forged package").to_open_dict()
    )
    object.__setattr__(forged, "package_id", first.package_id)
    object.__setattr__(forged, "rdp_id", first.package_id)

    with pytest.raises(ValueError, match="package_id collision"):
        store.record_manifest(forged, owner_user_id="u1", recorded_by="u1")

    assert path.read_bytes() == before


def test_persistent_rdp_store_poisoned_refresh_never_serves_stale_cache(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    manifest = _record(store, _manifest(research_question="cached before poison"))
    assert store.manifest(manifest.package_id, owner_user_id="u1") == manifest
    with path.open("ab") as handle:
        handle.write(b'{"schema_version":2')
        handle.flush()
        os.fsync(handle.fileno())

    with pytest.raises(ValueError, match="invalid persisted RDP row"):
        store.manifest(manifest.package_id, owner_user_id="u1")
    assert store._manifests == {}
    with pytest.raises(ValueError, match="invalid persisted RDP row"):
        store.manifests(owner_user_id="u1")


def test_persistent_rdp_store_short_writes_complete_and_zero_write_rolls_back(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    first = _record(store, _manifest(research_question="short write baseline"))
    second = _manifest(research_question="short write completes")
    real_write = rdp_module.os.write

    def short_write(fd, payload):
        chunk = max(1, len(payload) // 3)
        return real_write(fd, payload[:chunk])

    monkeypatch.setattr(rdp_module.os, "write", short_write)
    assert _record(store, second) == second
    assert PersistentRDPStore(path).manifests(owner_user_id="u1") == [first, second]

    before = path.read_bytes()
    third = _manifest(research_question="zero write rejected")
    monkeypatch.setattr(rdp_module.os, "write", lambda _fd, _payload: 0)
    with pytest.raises(OSError, match="made no progress"):
        _record(store, third)
    assert path.read_bytes() == before

    monkeypatch.setattr(rdp_module.os, "write", real_write)
    assert _record(store, third) == third
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_persistent_rdp_store_temp_fsync_failure_restores_exact_bytes_and_retries(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    _record(store, _manifest(research_question="temp fsync baseline"))
    before = path.read_bytes()
    candidate = _manifest(research_question="temp fsync candidate")
    real_fsync = rdp_module.os.fsync
    calls = 0

    def fail_first_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected RDP temp fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(rdp_module.os, "fsync", fail_first_fsync)
    with pytest.raises(OSError, match="injected RDP temp fsync failure"):
        _record(store, candidate)
    assert path.read_bytes() == before

    monkeypatch.setattr(rdp_module.os, "fsync", real_fsync)
    assert _record(store, candidate) == candidate
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_persistent_rdp_store_replace_failure_restores_exact_bytes_and_retries(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    _record(store, _manifest(research_question="replace baseline"))
    before = path.read_bytes()
    candidate = _manifest(research_question="replace candidate")
    real_replace = rdp_module.os.replace

    def fail_replace(_source, _target):
        raise OSError("injected RDP replace failure")

    monkeypatch.setattr(rdp_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected RDP replace failure"):
        _record(store, candidate)
    assert path.read_bytes() == before

    monkeypatch.setattr(rdp_module.os, "replace", real_replace)
    assert _record(store, candidate) == candidate
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_persistent_rdp_store_replace_ack_loss_restores_exact_bytes_and_retries(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    _record(store, _manifest(research_question="ack loss baseline"))
    before = path.read_bytes()
    candidate = _manifest(research_question="ack loss candidate")
    real_replace = rdp_module.os.replace
    calls = 0

    def replace_then_raise(source, target):
        nonlocal calls
        calls += 1
        real_replace(source, target)
        if calls == 1:
            raise OSError("injected RDP replace acknowledgement loss")

    monkeypatch.setattr(rdp_module.os, "replace", replace_then_raise)
    with pytest.raises(OSError, match="injected RDP replace acknowledgement loss"):
        _record(store, candidate)
    assert path.read_bytes() == before

    monkeypatch.setattr(rdp_module.os, "replace", real_replace)
    assert _record(store, candidate) == candidate
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_persistent_rdp_store_first_write_ack_loss_removes_file_and_retries(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    candidate = _manifest(research_question="first write acknowledgement loss")
    real_replace = rdp_module.os.replace
    calls = 0

    def replace_then_raise(source, target):
        nonlocal calls
        calls += 1
        real_replace(source, target)
        if calls == 1:
            raise OSError("injected first RDP replace acknowledgement loss")

    monkeypatch.setattr(rdp_module.os, "replace", replace_then_raise)
    with pytest.raises(OSError, match="injected first RDP replace acknowledgement loss"):
        _record(store, candidate)
    assert not path.exists()
    assert store._manifests == {}

    monkeypatch.setattr(rdp_module.os, "replace", real_replace)
    assert _record(store, candidate) == candidate
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_persistent_rdp_store_parent_fsync_failure_restores_exact_bytes_and_retries(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    _record(store, _manifest(research_question="parent fsync baseline"))
    before = path.read_bytes()
    candidate = _manifest(research_question="parent fsync candidate")
    real_parent_fsync = store._fsync_parent
    calls = 0

    def fail_first_parent_fsync():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected RDP parent fsync failure")
        return real_parent_fsync()

    monkeypatch.setattr(store, "_fsync_parent", fail_first_parent_fsync)
    with pytest.raises(OSError, match="injected RDP parent fsync failure"):
        _record(store, candidate)
    assert path.read_bytes() == before

    monkeypatch.setattr(store, "_fsync_parent", real_parent_fsync)
    assert _record(store, candidate) == candidate
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_persistent_rdp_store_reports_commit_uncertain_when_rollback_cannot_be_proved(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    _record(store, _manifest(research_question="uncertain baseline"))
    candidate = _manifest(research_question="uncertain candidate")
    real_replace = rdp_module.os.replace
    calls = 0

    def lose_commit_ack_then_fail_rollback(source, target):
        nonlocal calls
        calls += 1
        if calls == 1:
            real_replace(source, target)
            raise OSError("injected RDP commit acknowledgement loss")
        raise OSError("injected RDP rollback replace failure")

    monkeypatch.setattr(
        rdp_module.os,
        "replace",
        lose_commit_ack_then_fail_rollback,
    )
    with pytest.raises(RDPStoreCommitUncertain, match="rollback is uncertain"):
        _record(store, candidate)
    assert store._manifests == {}

    monkeypatch.setattr(rdp_module.os, "replace", real_replace)
    replayed = PersistentRDPStore(path)
    assert replayed.manifest(candidate.package_id, owner_user_id="u1") == candidate
    assert _record(replayed, candidate) == candidate
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_persistent_rdp_store_quarantines_ownerless_v1_history(tmp_path):
    path = tmp_path / "rdp_manifests.jsonl"
    legacy_manifest = _manifest(research_question="valid ownerless legacy manifest")
    legacy_row = {
        "schema_version": 1,
        "event_type": "rdp_manifest_recorded",
        "has_user_waiver": False,
        "manifest": _legacy_v1_manifest_payload(legacy_manifest),
    }
    legacy_bytes = (
        "  "
        + json.dumps(legacy_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "  \n"
    ).encode("utf-8")
    path.write_bytes(legacy_bytes)

    store = PersistentRDPStore(path)
    assert store.legacy_quarantined_count == 1
    assert store.legacy_quarantine_status.status == "read_only_unattributed"
    assert store.legacy_quarantine_status.quarantined_count == 1
    assert store.manifests(owner_user_id="u1") == []
    with pytest.raises(KeyError):
        store.manifest(legacy_row["manifest"]["package_id"], owner_user_id="u1")

    current = _manifest(research_question="owner-scoped current manifest")
    store.record_manifest(current, owner_user_id="u1", recorded_by="u1")
    assert path.read_bytes().startswith(legacy_bytes)
    assert store.manifests(owner_user_id="u1") == [current]

    reloaded = PersistentRDPStore(path)
    assert reloaded.legacy_quarantined_count == 1
    assert reloaded.legacy_quarantine_status.status == "read_only_unattributed"
    assert reloaded.manifests(owner_user_id="u1") == [current]


def test_persistent_rdp_store_quarantine_status_refreshes_after_external_legacy_append(
    tmp_path,
):
    path = tmp_path / "rdp_manifests.jsonl"
    store = PersistentRDPStore(path)
    assert store.legacy_quarantined_count == 0
    assert store.legacy_quarantine_status.status == "clear"
    legacy_row = {
        "schema_version": 1,
        "event_type": "rdp_manifest_recorded",
        "has_user_waiver": False,
        "manifest": _legacy_v1_manifest_payload(
            _manifest(research_question="externally appended legacy")
        ),
    }
    path.write_text(json.dumps(legacy_row, ensure_ascii=False) + "\n", encoding="utf-8")

    assert store.legacy_quarantined_count == 1
    assert store.legacy_quarantine_status.status == "read_only_unattributed"


def test_persistent_rdp_store_rejects_invalid_manifest_without_persisting(tmp_path):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")

    with pytest.raises(ValueError, match="missing_dataset_version_refs"):
        _record(store, _manifest(dataset_version_refs=(), reproducibility_command=""))

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
        _record(store, manifest)


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


@pytest.mark.parametrize(
    ("residual_input", "expected_detail"),
    [
        ("absent", "missing_unverified_residuals"),
        ("null", "missing_unverified_residuals"),
        ("empty", "missing_residual_attestation"),
    ],
)
def test_rdp_api_rejects_missing_or_unattested_zero_residuals(
    tmp_path,
    monkeypatch,
    residual_input,
    expected_detail,
):
    client, store = _client_with_rdp_store(tmp_path, monkeypatch)
    if residual_input in {"absent", "null"}:
        payload = _payload(unverified_residuals=None)
    else:
        payload = _payload(unverified_residuals=(), residual_attestation="")
    if residual_input == "absent":
        payload["manifest"].pop("unverified_residuals")
    try:
        rejected = client.post("/api/research-os/rdp/manifests", json=payload)
        assert rejected.status_code == 422
        assert expected_detail in rejected.json()["detail"]
        assert not store.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_api_records_attested_explicit_zero_residuals(tmp_path, monkeypatch):
    client, store = _client_with_rdp_store(tmp_path, monkeypatch)
    try:
        created = client.post(
            "/api/research-os/rdp/manifests",
            json=_payload(
                unverified_residuals=(),
                residual_attestation="review:all-known-residuals-resolved:v1",
            ),
        )
        assert created.status_code == 200
        package_id = created.json()["package_id"]
        replayed = PersistentRDPStore(store.path).manifest(
            package_id,
            owner_user_id="u1",
        )
        assert replayed.unverified_residuals == ()
        assert replayed.residual_attestation == (
            "review:all-known-residuals-resolved:v1"
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_api_defaults_omitted_manifest_version_to_v3(tmp_path, monkeypatch):
    client, _store = _client_with_rdp_store(tmp_path, monkeypatch)
    payload = _payload()
    payload["manifest"].pop("manifest_version")
    try:
        created = client.post("/api/research-os/rdp/manifests", json=payload)
        assert created.status_code == 200
        assert created.json()["manifest_version"] == "rdp.v3"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rdp_api_foreign_owner_matches_missing_and_lists_nothing(tmp_path, monkeypatch):
    client, _store = _client_with_rdp_store(tmp_path, monkeypatch)
    try:
        created = client.post("/api/research-os/rdp/manifests", json=_payload())
        assert created.status_code == 200
        package_id = created.json()["package_id"]

        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
            username="same-display-name",
            user_id="u2",
        )
        listed = client.get("/api/research-os/rdp/manifests")
        assert listed.status_code == 200
        assert listed.json()["manifests"] == []

        foreign = client.get(f"/api/research-os/rdp/manifests/{package_id}")
        missing = client.get("/api/research-os/rdp/manifests/rdp_missing")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json() == {"detail": "RDP package not found"}
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: {**row, "event_type": "unknown"},
        lambda row: {**row, "has_user_waiver": 0},
        lambda row: {**row, "unexpected": True},
        lambda row: {
            **row,
            "manifest": {
                **row["manifest"],
                "package_id": "rdp_" + "0" * 16,
            },
        },
    ],
)
def test_persistent_rdp_store_rejects_unknown_or_tampered_v1_history(
    tmp_path,
    mutate,
):
    path = tmp_path / "rdp_manifests.jsonl"
    row = {
        "schema_version": 1,
        "event_type": "rdp_manifest_recorded",
        "has_user_waiver": False,
        "manifest": _legacy_v1_manifest_payload(
            _manifest(research_question="strict legacy history")
        ),
    }
    path.write_text(json.dumps(mutate(row), ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid persisted RDP row"):
        PersistentRDPStore(path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: {**row, "unexpected": True},
        lambda row: {**row, "owner_user_id": " u1"},
        lambda row: {**row, "recorded_by": "u1\n"},
        lambda row: {**row, "has_user_waiver": 0},
        lambda row: {**row, "event_type": "unknown"},
        lambda row: {**row, "manifest": {"package_id": "rdp_forged"}},
        lambda row: {
            **row,
            "manifest": {
                **row["manifest"],
                "package_id": "rdp_" + "0" * 16,
            },
        },
        lambda row: {
            **row,
            "manifest": {
                key: value
                for key, value in row["manifest"].items()
                if key != "rdp_id"
            },
        },
    ],
)
def test_persistent_rdp_store_rejects_inexact_or_invalid_v2_history(tmp_path, mutate):
    path = tmp_path / "rdp_manifests.jsonl"
    manifest = _manifest(research_question="strict persisted event")
    row = {
        "schema_version": 2,
        "event_type": "rdp_manifest_recorded",
        "owner_user_id": "u1",
        "recorded_by": "u1",
        "has_user_waiver": False,
        "manifest": manifest.to_open_dict(),
    }
    path.write_text(json.dumps(mutate(row), ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid persisted RDP row"):
        PersistentRDPStore(path)
