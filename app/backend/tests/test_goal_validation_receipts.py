from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest

import app.research_os.goal_validation_receipts as receipt_module
from app.research_os import (
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)


OWNER = "owner:alice"
QROS = ("qro_a1", "qro_b2")
COMMANDS = ("rgcmd_a1", "rgcmd_b2")


def _receipt(**overrides: object) -> GoalValidationReceipt:
    data: dict[str, object] = {
        "validation_ref": "",
        "owner_user_id": OWNER,
        "subject_qro_refs": QROS,
        "graph_command_refs": COMMANDS,
        "validator_identifiers": ("validator:goal-entrypoint-v1",),
        "test_identifiers": (
            "pytest:app/backend/tests/test_goal_validation_receipts.py::strict-entrypoint",
        ),
        "outcome": GoalValidationOutcome.PASSED,
        "evidence_refs": ("test-report:goal-entrypoint:run-42",),
        "evidence_digests": ("sha256:" + "a" * 64,),
        "residuals": (),
    }
    data.update(overrides)
    provisional = GoalValidationReceipt(**data)  # type: ignore[arg-type]
    if "validation_ref" in overrides:
        return provisional
    return replace(
        provisional,
        validation_ref=provisional.canonical_validation_ref,
    )


def _codes(decision: object) -> set[str]:
    return {item.code for item in decision.violations}  # type: ignore[attr-defined]


def test_passed_receipt_resolves_exact_owner_qro_and_graph_sets(tmp_path) -> None:
    path = tmp_path / "goal_validation_receipts.jsonl"
    registry = PersistentGoalValidationReceiptRegistry(path)
    record = registry.record_receipt(_receipt())

    decision = registry.validate_validation_ref(
        record.validation_ref,
        owner_user_id=OWNER,
        subject_qro_refs=tuple(reversed(QROS)),
        graph_command_refs=tuple(reversed(COMMANDS)),
    )

    assert decision.accepted is True
    assert registry.receipt(record.validation_ref, owner_user_id=OWNER) == record
    assert registry.receipts(owner_user_id=OWNER) == [record]
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["schema_version"] == 2
    assert row["owner_user_id"] == OWNER


@pytest.mark.parametrize(
    ("owner", "qros", "commands", "expected_code"),
    (
        ("owner:bob", QROS, COMMANDS, "goal_validation_receipt_unknown"),
        (OWNER, ("qro_a1",), COMMANDS, "goal_validation_receipt_qro_set_mismatch"),
        (OWNER, QROS, ("rgcmd_a1",), "goal_validation_receipt_graph_set_mismatch"),
        (OWNER, QROS + ("qro_extra",), COMMANDS, "goal_validation_receipt_qro_set_mismatch"),
        (OWNER, QROS, COMMANDS + ("rgcmd_extra",), "goal_validation_receipt_graph_set_mismatch"),
    ),
)
def test_receipt_rejects_foreign_owner_or_mutated_subject_sets(
    tmp_path,
    owner,
    qros,
    commands,
    expected_code,
) -> None:
    registry = PersistentGoalValidationReceiptRegistry(tmp_path / "receipts.jsonl")
    record = registry.record_receipt(_receipt())

    decision = registry.validate_validation_ref(
        record.validation_ref,
        owner_user_id=owner,
        subject_qro_refs=qros,
        graph_command_refs=commands,
    )

    assert decision.accepted is False
    assert expected_code in _codes(decision)


@pytest.mark.parametrize(
    "outcome",
    (
        GoalValidationOutcome.FAILED,
        GoalValidationOutcome.ERROR,
        GoalValidationOutcome.SKIPPED,
    ),
)
def test_non_passed_receipts_remain_auditable_but_never_satisfy(
    tmp_path,
    outcome,
) -> None:
    registry = PersistentGoalValidationReceiptRegistry(tmp_path / "receipts.jsonl")
    record = registry.record_receipt(_receipt(outcome=outcome))

    decision = registry.validate_validation_ref(
        record.validation_ref,
        owner_user_id=OWNER,
        subject_qro_refs=QROS,
        graph_command_refs=COMMANDS,
    )

    assert decision.accepted is False
    assert "goal_validation_receipt_not_passed" in _codes(decision)
    assert registry.receipt(record.validation_ref, owner_user_id=OWNER) == record


def test_residual_bearing_receipt_never_satisfies(tmp_path) -> None:
    registry = PersistentGoalValidationReceiptRegistry(tmp_path / "receipts.jsonl")
    record = registry.record_receipt(
        _receipt(residuals=("coverage result still has one unresolved mutation",))
    )

    decision = registry.validate_validation_ref(
        record.validation_ref,
        owner_user_id=OWNER,
        subject_qro_refs=QROS,
        graph_command_refs=COMMANDS,
    )

    assert decision.accepted is False
    assert "goal_validation_receipt_has_residuals" in _codes(decision)


def test_forged_identity_and_placeholder_test_refs_are_not_written(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentGoalValidationReceiptRegistry(path)

    with pytest.raises(ValueError, match="identity_mismatch"):
        registry.record_receipt(_receipt(validation_ref="goal_validation_receipt:forged"))
    with pytest.raises(ValueError, match="placeholder_ref"):
        registry.record_receipt(_receipt(test_identifiers=("fixture:test-result",)))

    assert registry.receipts(owner_user_id=OWNER) == []
    assert not path.exists()


def test_digest_shape_and_evidence_cardinality_fail_closed(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentGoalValidationReceiptRegistry(path)

    with pytest.raises(ValueError, match="digest_invalid"):
        registry.record_receipt(_receipt(evidence_digests=("sha256:not-a-digest",)))
    with pytest.raises(ValueError, match="evidence_cardinality_mismatch"):
        registry.record_receipt(
            _receipt(evidence_refs=("report:a", "report:b"))
        )

    assert registry.receipts(owner_user_id=OWNER) == []
    assert not path.exists()


def test_legacy_quarantine_disk_replay_idempotency_and_read_only_lookup(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "goal_validation_receipt_recorded",
                "validation_receipt": {"validation_ref": "legacy:ownerless"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    registry = PersistentGoalValidationReceiptRegistry(path)
    assert registry.legacy_quarantined_count == 1

    record = registry.record_receipt(_receipt())
    after_record = path.read_bytes()
    assert registry.record_receipt(record) == record
    assert registry.receipt(record.validation_ref, owner_user_id=OWNER) == record
    assert path.read_bytes() == after_record

    replayed = PersistentGoalValidationReceiptRegistry(path)
    assert replayed.legacy_quarantined_count == 1
    assert replayed.receipt(record.validation_ref, owner_user_id=OWNER) == record
    before_read = path.read_bytes()
    replayed.receipt(record.validation_ref, owner_user_id=OWNER)
    replayed.receipts(owner_user_id=OWNER)
    assert path.read_bytes() == before_read


def test_stale_registry_instances_rescan_disk_and_keep_idempotent_single_row(
    tmp_path,
) -> None:
    path = tmp_path / "receipts.jsonl"
    first = PersistentGoalValidationReceiptRegistry(path)
    stale = PersistentGoalValidationReceiptRegistry(path)
    record = _receipt()

    assert first.record_receipt(record) == record
    assert stale.record_receipt(record) == record

    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 1
    assert stale.receipt(record.validation_ref, owner_user_id=OWNER) == record


def test_public_reads_reload_receipt_written_by_another_instance(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    reader = PersistentGoalValidationReceiptRegistry(path)
    writer = PersistentGoalValidationReceiptRegistry(path)
    record = writer.record_receipt(_receipt())

    assert reader.receipt(record.validation_ref, owner_user_id=OWNER) == record
    assert reader.receipts(owner_user_id=OWNER) == [record]


def test_disk_collision_does_not_append_or_install_partial_record(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentGoalValidationReceiptRegistry(path)
    incoming = _receipt()
    collision = {
        "schema_version": 2,
        "event_type": "goal_validation_receipt_recorded",
        "owner_user_id": OWNER,
        "validation_receipt": {
            **asdict(incoming),
            "evidence_digests": ["sha256:" + "b" * 64],
        },
    }
    path.write_text(json.dumps(collision) + "\n", encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="identity collision"):
        registry.record_receipt(incoming)

    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="invalid persisted GOAL validation receipt"):
        registry.receipts(owner_user_id=OWNER)


def test_append_failure_does_not_install_in_memory_or_leave_partial_file(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentGoalValidationReceiptRegistry(path)
    record = _receipt()

    def _fail(_source, _destination) -> None:
        raise OSError("simulated durable append failure")

    monkeypatch.setattr(receipt_module.os, "replace", _fail)
    with pytest.raises(OSError, match="simulated durable append failure"):
        registry.record_receipt(record)

    assert registry.receipts(owner_user_id=OWNER) == []
    assert not path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_current_content_identity_is_rechecked_from_disk_at_consumption(tmp_path) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentGoalValidationReceiptRegistry(path)
    record = registry.record_receipt(_receipt())
    row = json.loads(path.read_text(encoding="utf-8"))
    row["validation_receipt"]["test_identifiers"] = [
        "pytest:mutated-after-persist"
    ]
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid persisted GOAL validation receipt"):
        registry.validate_validation_ref(
            record.validation_ref,
            owner_user_id=OWNER,
            subject_qro_refs=QROS,
            graph_command_refs=COMMANDS,
        )
