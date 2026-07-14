from __future__ import annotations

import inspect
import json
import multiprocessing
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

import app.ide.promotion_receipt as receipt_module
from app.ide.promotion_receipt import (
    EXPECTED_GATE_BINDINGS,
    PersistentPromotionReceiptRegistry,
    PromotionCandidateProof,
    PromotionGateVerification,
    PromotionVerificationSnapshot,
    canonical_payload_sha256,
)


OWNER = "user:alice"
SOURCE_RUN = "ide-source-42"
PROMOTED_RUN = "ide_alice_strategy_receipt"
RDP_ID = "rdp_4a6c"
LABEL = "production_ready"


def _gate(
    binding: tuple[str, str, str, str],
    **overrides: object,
) -> PromotionGateVerification:
    section, manifest_key, producer_key, gate_name = binding
    data: dict[str, object] = {
        "section": section,
        "manifest_key": manifest_key,
        "producer_key": producer_key,
        "gate_name": gate_name,
        "canonical_source_refs": (f"qro:{gate_name}:one", f"record:{gate_name}:two"),
        "assembled_payload_sha256": canonical_payload_sha256(
            {"manifest_key": manifest_key, "server_payload": gate_name}
        ),
        "gate_verdict_sha256": canonical_payload_sha256(
            {"gate_name": gate_name, "mode": "enforce", "ok": True}
        ),
        "mode": "enforce",
        "ok": True,
        "producer_green": True,
        "errored": False,
        "missing": (),
        "residuals": (),
    }
    data.update(overrides)
    return PromotionGateVerification(**data)  # type: ignore[arg-type]


def _snapshot(**overrides: object) -> PromotionVerificationSnapshot:
    data: dict[str, object] = {
        "section_verifications": tuple(_gate(binding) for binding in EXPECTED_GATE_BINDINGS),
        "release_verdict_sha256": canonical_payload_sha256(
            {"ok": True, "release_ready": True}
        ),
        "gate_chain_sha256": canonical_payload_sha256(
            {"rejected": False, "release_ready": True}
        ),
        "run_manifest_sha256": canonical_payload_sha256(
            {"run_id": PROMOTED_RUN, "status": "completed"}
        ),
        "outcome": "passed",
        "release_ok": True,
        "release_ready": True,
        "chain_rejected": False,
        "chain_release_ready": True,
        "errors": (),
        "residuals": (),
    }
    data.update(overrides)
    return PromotionVerificationSnapshot(**data)  # type: ignore[arg-type]


class MutableLoader:
    def __init__(self, snapshot: PromotionVerificationSnapshot | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.calls: list[tuple[str, str, str, str, str]] = []
        self.candidate_calls = []

    def __call__(
        self,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
    ) -> PromotionVerificationSnapshot:
        self.calls.append(
            (
                owner_user_id,
                source_ide_run_id,
                promoted_run_id,
                rdp_package_id,
                requested_label,
            )
        )
        return self.snapshot

    def verify_candidate(
        self,
        owner_user_id: str,
        source_ide_run_id: str,
        promoted_run_id: str,
        rdp_package_id: str,
        requested_label: str,
        *,
        candidate: PromotionCandidateProof,
    ) -> PromotionVerificationSnapshot:
        self.candidate_calls.append(
            (
                owner_user_id,
                source_ide_run_id,
                promoted_run_id,
                rdp_package_id,
                requested_label,
                candidate,
            )
        )
        return self.snapshot


def _record(registry: PersistentPromotionReceiptRegistry):
    return registry.record_current(
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id=PROMOTED_RUN,
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )


def _record_for(
    registry: PersistentPromotionReceiptRegistry,
    promoted_run_id: str,
):
    return registry.record_current(
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id=promoted_run_id,
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )


def _process_record(
    path: str,
    promoted_run_id: str,
    start: object,
    results: object,
) -> None:
    try:
        if not start.wait(timeout=10.0):  # type: ignore[attr-defined]
            raise TimeoutError("promotion receipt process start barrier timed out")
        registry = PersistentPromotionReceiptRegistry(path, MutableLoader())
        receipt = _record_for(registry, promoted_run_id)
        results.put(("ok", receipt.receipt_ref))  # type: ignore[attr-defined]
    except BaseException as exc:  # noqa: BLE001 - subprocess reports exact failure.
        results.put(  # type: ignore[attr-defined]
            ("error", type(exc).__name__, str(exc))
        )


def _codes(decision: object) -> set[str]:
    return {item.code for item in decision.violations}  # type: ignore[attr-defined]


def test_record_current_accepts_identities_only_and_persists_schema_v2(tmp_path) -> None:
    loader = MutableLoader()
    path = tmp_path / "promotion_receipts.jsonl"
    registry = PersistentPromotionReceiptRegistry(path, loader)

    receipt = _record(registry)

    assert set(inspect.signature(registry.record_current).parameters) == {
        "owner_user_id",
        "source_ide_run_id",
        "promoted_run_id",
        "rdp_package_id",
        "requested_label",
    }
    assert receipt.receipt_ref == receipt.canonical_receipt_ref
    assert receipt.receipt_ref.startswith("ide_promotion_receipt:")
    assert len(receipt.run_manifest_sha256) == 64
    assert loader.calls == [(OWNER, SOURCE_RUN, PROMOTED_RUN, RDP_ID, LABEL)]
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["schema_version"] == 2
    assert row["owner_user_id"] == OWNER
    assert row["promotion_receipt"]["promoted_run_id"] == PROMOTED_RUN

    decision = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id=PROMOTED_RUN,
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )
    assert decision.accepted is True
    assert decision.violations == ()


def test_candidate_prepare_and_record_use_only_typed_exact_candidate(tmp_path) -> None:
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "candidate-receipts.jsonl",
        loader,
    )
    candidate = PromotionCandidateProof(
        staging_name="candidate-one",
        st_dev=1,
        st_ino=2,
        run_manifest_sha256=_snapshot().run_manifest_sha256,
    )
    identities = {
        "owner_user_id": OWNER,
        "source_ide_run_id": SOURCE_RUN,
        "promoted_run_id": PROMOTED_RUN,
        "rdp_package_id": RDP_ID,
        "requested_label": LABEL,
    }

    prepared = registry.prepare_candidate_current(
        **identities,
        candidate=candidate,
    )
    recorded = registry.record_candidate_current(
        **identities,
        candidate=candidate,
    )

    assert prepared == recorded
    assert loader.calls == []
    assert [call[-1] for call in loader.candidate_calls] == [candidate, candidate]
    assert registry.receipt(
        recorded.receipt_ref,
        owner_user_id=OWNER,
    ) == recorded


@pytest.mark.parametrize(
    "kwargs",
    (
        {"staging_name": "../escape"},
        {"staging_name": "candidate", "st_ino": 0},
        {"staging_name": "candidate", "run_manifest_sha256": "f" * 63},
    ),
)
def test_candidate_proof_rejects_ambiguous_path_or_identity(kwargs) -> None:
    values = {
        "staging_name": "candidate",
        "st_dev": 1,
        "st_ino": 2,
        "run_manifest_sha256": "f" * 64,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        PromotionCandidateProof(**values)


def test_receipt_and_nested_gate_records_are_immutable(tmp_path) -> None:
    receipt = _record(
        PersistentPromotionReceiptRegistry(tmp_path / "receipts.jsonl", MutableLoader())
    )
    with pytest.raises(FrozenInstanceError):
        receipt.requested_label = "draft"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        receipt.section_verifications[0].producer_green = False  # type: ignore[misc]


def test_owner_isolation_and_exact_identity_context(tmp_path) -> None:
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "receipts.jsonl", MutableLoader()
    )
    receipt = _record(registry)

    with pytest.raises(KeyError):
        registry.receipt(receipt.receipt_ref, owner_user_id="user:bob")
    assert registry.receipts(owner_user_id="user:bob") == []
    foreign = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id="user:bob",
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id=PROMOTED_RUN,
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )
    assert foreign.accepted is False
    assert _codes(foreign) == {"promotion_receipt_unknown"}

    wrong_run = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id="different-promoted-run",
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )
    assert wrong_run.accepted is False
    assert _codes(wrong_run) == {"promotion_receipt_identity_context_mismatch"}


@pytest.mark.parametrize(
    ("gate_overrides", "expected_code"),
    (
        ({"mode": "advisory"}, "promotion_receipt_gate_not_enforcing"),
        ({"ok": False}, "promotion_receipt_gate_not_passed"),
        ({"producer_green": False}, "promotion_receipt_producer_not_green"),
        ({"errored": True}, "promotion_receipt_gate_errored"),
        ({"missing": ("canonical claim",)}, "promotion_receipt_gate_missing_evidence"),
        ({"residuals": ("one unresolved gate gap",)}, "promotion_receipt_gate_has_residuals"),
    ),
)
def test_non_enforce_red_failed_errored_or_residual_gate_is_not_written(
    tmp_path,
    gate_overrides,
    expected_code,
) -> None:
    sections = list(_snapshot().section_verifications)
    sections[0] = replace(sections[0], **gate_overrides)
    loader = MutableLoader(_snapshot(section_verifications=tuple(sections)))
    path = tmp_path / "receipts.jsonl"
    registry = PersistentPromotionReceiptRegistry(path, loader)

    with pytest.raises(ValueError, match=expected_code):
        _record(registry)

    assert registry.receipts(owner_user_id=OWNER) == []
    assert not path.exists()


@pytest.mark.parametrize(
    ("snapshot_overrides", "expected_code"),
    (
        ({"outcome": "failed"}, "promotion_receipt_not_passed"),
        ({"release_ok": False}, "promotion_receipt_release_not_ready"),
        ({"release_ready": False}, "promotion_receipt_release_not_ready"),
        ({"chain_rejected": True}, "promotion_receipt_chain_not_ready"),
        ({"chain_release_ready": False}, "promotion_receipt_chain_not_ready"),
        ({"errors": ("release evaluator crashed",)}, "promotion_receipt_has_errors"),
        ({"residuals": ("section 9 unresolved",)}, "promotion_receipt_has_residuals"),
        ({"run_manifest_sha256": "a" * 63}, "promotion_receipt_digest_invalid"),
    ),
)
def test_non_passed_release_chain_or_invalid_digest_is_not_written(
    tmp_path,
    snapshot_overrides,
    expected_code,
) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentPromotionReceiptRegistry(
        path, MutableLoader(_snapshot(**snapshot_overrides))
    )

    with pytest.raises(ValueError, match=expected_code):
        _record(registry)

    assert not path.exists()


def test_exact_gate_set_and_canonical_sources_are_required(tmp_path) -> None:
    snapshot = _snapshot()
    path = tmp_path / "receipts.jsonl"
    missing_gate = replace(
        snapshot,
        section_verifications=snapshot.section_verifications[:-1],
    )
    with pytest.raises(ValueError, match="promotion_receipt_gate_set_mismatch"):
        _record(PersistentPromotionReceiptRegistry(path, MutableLoader(missing_gate)))
    assert not path.exists()

    hollow = list(snapshot.section_verifications)
    hollow[0] = replace(hollow[0], canonical_source_refs=())
    with pytest.raises(ValueError, match="promotion_receipt_sources_invalid"):
        _record(
            PersistentPromotionReceiptRegistry(
                path, MutableLoader(replace(snapshot, section_verifications=tuple(hollow)))
            )
        )
    assert not path.exists()


def test_validate_current_detects_canonical_manifest_drift_and_loader_failure(
    tmp_path,
) -> None:
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(tmp_path / "receipts.jsonl", loader)
    receipt = _record(registry)

    loader.snapshot = replace(
        loader.snapshot,
        run_manifest_sha256=canonical_payload_sha256({"run": "changed-after-receipt"}),
    )
    drift = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id=PROMOTED_RUN,
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )
    assert drift.accepted is False
    assert _codes(drift) == {"promotion_receipt_current_verification_drift"}

    def unavailable(*_args: str) -> PromotionVerificationSnapshot:
        raise FileNotFoundError("run.json disappeared")

    registry._verification_loader = unavailable
    failed = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id=PROMOTED_RUN,
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )
    assert failed.accepted is False
    assert _codes(failed) == {"promotion_receipt_current_verification_unavailable"}


def test_validate_current_loader_reentry_fails_red_without_self_lock_timeout(
    tmp_path,
) -> None:
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "receipts.jsonl",
        MutableLoader(),
    )
    receipt = _record(registry)

    def reenter(*_identities: str) -> PromotionVerificationSnapshot:
        registry.receipts(owner_user_id=OWNER)
        return _snapshot()

    registry._verification_loader = reenter
    decision = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id=PROMOTED_RUN,
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )

    assert decision.accepted is False
    assert _codes(decision) == {"promotion_receipt_current_verification_unavailable"}


def test_gate_verdict_lookup_is_owner_scoped_and_exact(tmp_path) -> None:
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "receipts.jsonl", MutableLoader()
    )
    receipt = _record(registry)
    expected = receipt.section_verifications[2]

    assert (
        registry.gate_verdict(
            receipt.receipt_ref,
            expected.gate_name,
            owner_user_id=OWNER,
        )
        == expected
    )
    with pytest.raises(KeyError):
        registry.gate_verdict(
            receipt.receipt_ref,
            "s10",
            owner_user_id=OWNER,
        )
    with pytest.raises(KeyError):
        registry.gate_verdict(
            receipt.receipt_ref,
            expected.gate_name,
            owner_user_id="user:bob",
        )


def test_legacy_quarantine_replay_and_reload_are_idempotent(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "ide_promotion_verification_recorded",
                "promotion_receipt": {"receipt_ref": "legacy:ownerless"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(path, loader)
    assert registry.legacy_quarantined_count == 1

    receipt = _record(registry)
    after_first = path.read_bytes()
    assert _record(registry) == receipt
    assert path.read_bytes() == after_first

    reloaded = PersistentPromotionReceiptRegistry(path, loader)
    assert reloaded.legacy_quarantined_count == 1
    assert reloaded.receipt(receipt.receipt_ref, owner_user_id=OWNER) == receipt
    before_reads = path.read_bytes()
    reloaded.receipt(receipt.receipt_ref, owner_user_id=OWNER)
    reloaded.receipts(owner_user_id=OWNER)
    assert path.read_bytes() == before_reads


def test_forged_persisted_identity_is_rejected_on_reload(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentPromotionReceiptRegistry(path, MutableLoader())
    _record(registry)
    row = json.loads(path.read_text(encoding="utf-8"))
    row["promotion_receipt"]["receipt_ref"] = "ide_promotion_receipt:" + "f" * 64
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="history changed before marker"):
        PersistentPromotionReceiptRegistry(path, MutableLoader())


def test_stale_registry_disk_collision_preserves_existing_row(tmp_path, monkeypatch) -> None:
    constant_ref = "ide_promotion_receipt:" + "c" * 64
    monkeypatch.setattr(
        receipt_module,
        "promotion_receipt_identity",
        lambda **_kwargs: constant_ref,
    )
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    first = PersistentPromotionReceiptRegistry(path, loader)
    stale = PersistentPromotionReceiptRegistry(path, loader)
    initial = _record(first)
    existing_bytes = path.read_bytes()

    loader.snapshot = replace(
        loader.snapshot,
        run_manifest_sha256=canonical_payload_sha256({"different": "manifest"}),
    )
    with pytest.raises(ValueError, match="identity collision"):
        _record(stale)

    assert initial.receipt_ref == constant_ref
    assert path.read_bytes() == existing_bytes
    assert stale.receipts(owner_user_id=OWNER) == [initial]


def test_append_failure_never_installs_an_in_memory_or_disk_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentPromotionReceiptRegistry(path, MutableLoader())

    def fail_append(_row: dict[str, object]) -> None:
        raise OSError("simulated durable append failure")

    monkeypatch.setattr(registry, "_append_event", fail_append)
    with pytest.raises(OSError, match="simulated durable append failure"):
        _record(registry)

    assert registry.receipts(owner_user_id=OWNER) == []
    assert not path.exists()


def test_mapping_loader_is_strictly_adapted_and_content_bound(tmp_path) -> None:
    snapshot = _snapshot()
    raw = asdict(snapshot)
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "receipts.jsonl",
        lambda *_identities: raw,
    )

    receipt = _record(registry)

    assert receipt.section_verifications == snapshot.section_verifications
    assert receipt.canonical_receipt_ref == receipt.receipt_ref


def test_reader_created_before_writer_replays_durable_receipt_on_validate(
    tmp_path,
) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    reader = PersistentPromotionReceiptRegistry(path, loader)
    writer = PersistentPromotionReceiptRegistry(path, loader)

    receipt = _record(writer)
    decision = reader.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE_RUN,
        promoted_run_id=PROMOTED_RUN,
        rdp_package_id=RDP_ID,
        requested_label=LABEL,
    )

    assert decision.accepted is True
    assert reader.receipt(receipt.receipt_ref, owner_user_id=OWNER) == receipt


def test_stale_writer_replays_before_append_and_preserves_both_receipts(
    tmp_path,
) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    first = PersistentPromotionReceiptRegistry(path, loader)
    stale = PersistentPromotionReceiptRegistry(path, loader)

    first_receipt = _record_for(first, f"{PROMOTED_RUN}-first")
    stale_receipt = _record_for(stale, f"{PROMOTED_RUN}-stale")

    reloaded = PersistentPromotionReceiptRegistry(path, loader)
    assert reloaded.receipts(owner_user_id=OWNER) == [
        first_receipt,
        stale_receipt,
    ]
    assert len(path.read_bytes().splitlines()) == 2


def test_concurrent_registry_appends_do_not_lose_either_receipt(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    first = PersistentPromotionReceiptRegistry(path, loader)
    second = PersistentPromotionReceiptRegistry(path, loader)
    barrier = threading.Barrier(2)

    def append(
        registry: PersistentPromotionReceiptRegistry,
        promoted_run_id: str,
    ):
        barrier.wait(timeout=5.0)
        return _record_for(registry, promoted_run_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(append, first, f"{PROMOTED_RUN}-concurrent-a"),
            pool.submit(append, second, f"{PROMOTED_RUN}-concurrent-b"),
        )
        recorded = {future.result(timeout=10.0).receipt_ref for future in futures}

    reloaded = PersistentPromotionReceiptRegistry(path, loader)
    assert {item.receipt_ref for item in reloaded.receipts(owner_user_id=OWNER)} == recorded
    assert len(path.read_bytes().splitlines()) == 2


def test_concurrent_process_appends_do_not_lose_either_receipt(tmp_path) -> None:
    path = tmp_path / "process-receipts.jsonl"
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = (
        context.Process(
            target=_process_record,
            args=(str(path), f"{PROMOTED_RUN}-process-a", start, results),
        ),
        context.Process(
            target=_process_record,
            args=(str(path), f"{PROMOTED_RUN}-process-b", start, results),
        ),
    )
    for process in processes:
        process.start()
    start.set()
    reported = [results.get(timeout=20.0) for _process in processes]
    for process in processes:
        process.join(timeout=20.0)

    assert [process.exitcode for process in processes] == [0, 0]
    assert {item[0] for item in reported} == {"ok"}, reported
    recorded_refs = {item[1] for item in reported}
    reloaded = PersistentPromotionReceiptRegistry(path, MutableLoader())
    assert {
        item.receipt_ref for item in reloaded.receipts(owner_user_id=OWNER)
    } == recorded_refs
    assert len(path.read_bytes().splitlines()) == 2
    results.close()
    results.join_thread()


@pytest.mark.parametrize("restart", (False, True), ids=("live", "restart"))
def test_receipt_history_truncation_fails_closed(tmp_path, restart: bool) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(path, loader)
    receipt = _record(registry)
    path.write_bytes(b"")

    with pytest.raises(ValueError, match="history was truncated"):
        if restart:
            PersistentPromotionReceiptRegistry(path, loader)
        else:
            registry.validate_current(
                receipt.receipt_ref,
                owner_user_id=OWNER,
                source_ide_run_id=SOURCE_RUN,
                promoted_run_id=PROMOTED_RUN,
                rdp_package_id=RDP_ID,
                requested_label=LABEL,
            )


@pytest.mark.parametrize("mutation", ("truncate", "replace"))
def test_validate_current_rechecks_durable_identity_after_loader(
    tmp_path,
    mutation: str,
) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(path, loader)
    receipt = _record(registry)
    original = path.read_bytes()

    def mutate_during_verification(*_identities: str) -> PromotionVerificationSnapshot:
        if mutation == "truncate":
            path.write_bytes(b"")
        else:
            replacement = tmp_path / "validate-replacement.jsonl"
            replacement.write_bytes(original)
            os.replace(replacement, path)
        return loader.snapshot

    registry._verification_loader = mutate_during_verification
    with pytest.raises(ValueError, match="ledger path identity changed"):
        registry.validate_current(
            receipt.receipt_ref,
            owner_user_id=OWNER,
            source_ide_run_id=SOURCE_RUN,
            promoted_run_id=PROMOTED_RUN,
            rdp_package_id=RDP_ID,
            requested_label=LABEL,
        )


@pytest.mark.parametrize("restart", (False, True), ids=("live", "restart"))
@pytest.mark.parametrize("mutation", ("replace", "reorder"))
def test_receipt_history_prefix_replace_or_reorder_fails_closed(
    tmp_path,
    restart: bool,
    mutation: str,
) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(path, loader)
    _record_for(registry, f"{PROMOTED_RUN}-history-a")
    _record_for(registry, f"{PROMOTED_RUN}-history-b")
    rows = path.read_bytes().splitlines(keepends=True)
    if mutation == "replace":
        rows[0] = rows[1]
    else:
        rows.reverse()
    path.write_bytes(b"".join(rows))

    with pytest.raises(ValueError, match="history changed before marker"):
        if restart:
            PersistentPromotionReceiptRegistry(path, loader)
        else:
            registry.receipts(owner_user_id=OWNER)


@pytest.mark.parametrize("restart", (False, True), ids=("live", "restart"))
def test_schema_v2_history_marker_deletion_fails_closed(tmp_path, restart: bool) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(path, loader)
    _record(registry)
    marker_path = path.with_suffix(path.suffix + ".history")
    marker_path.unlink()

    with pytest.raises(ValueError, match="history marker is missing"):
        if restart:
            PersistentPromotionReceiptRegistry(path, loader)
        else:
            registry.receipts(owner_user_id=OWNER)


def test_ledger_ahead_of_fsynced_marker_recovers_crash_window(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(path, loader)
    marker_path = path.with_suffix(path.suffix + ".history")
    empty_marker = marker_path.read_bytes()
    receipt = _record(registry)

    marker_path.write_bytes(empty_marker)
    reloaded = PersistentPromotionReceiptRegistry(path, loader)

    assert reloaded.receipt(receipt.receipt_ref, owner_user_id=OWNER) == receipt
    assert json.loads(marker_path.read_text(encoding="utf-8"))["row_count"] == 1


def test_ledger_fd_identity_swap_does_not_overwrite_replacement(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "receipts.jsonl"
    loader = MutableLoader()
    registry = PersistentPromotionReceiptRegistry(path, loader)
    first = _record_for(registry, f"{PROMOTED_RUN}-fd-first")
    original_bytes = path.read_bytes()
    original_identity = (path.stat().st_dev, path.stat().st_ino)
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_bytes(original_bytes)
    real_write = os.write
    swapped = False

    def swap_before_ledger_write(fd: int, payload: object) -> int:
        nonlocal swapped
        opened = os.fstat(fd)
        if not swapped and (opened.st_dev, opened.st_ino) == original_identity:
            os.replace(replacement, path)
            swapped = True
        return real_write(fd, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(receipt_module.os, "write", swap_before_ledger_write)
    with pytest.raises(ValueError, match="path identity changed"):
        _record_for(registry, f"{PROMOTED_RUN}-fd-second")

    assert swapped is True
    assert path.read_bytes() == original_bytes
    assert (path.stat().st_dev, path.stat().st_ino) != original_identity
    assert registry.receipts(owner_user_id=OWNER) == [first]


@pytest.mark.parametrize("protected", ("ledger", "marker", "lock"))
def test_receipt_durable_paths_reject_symlinks(tmp_path, protected: str) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentPromotionReceiptRegistry(path, MutableLoader())
    _record(registry)
    protected_paths = {
        "ledger": path,
        "marker": path.with_suffix(path.suffix + ".history"),
        "lock": path.with_name(f".{path.name}.lock"),
    }
    protected_path = protected_paths[protected]
    target = tmp_path / f"{protected}.target"
    target.write_bytes(protected_path.read_bytes())
    protected_path.unlink()
    protected_path.symlink_to(target)

    with pytest.raises(ValueError, match="non-symlink|history marker|opened safely"):
        registry.receipts(owner_user_id=OWNER)
