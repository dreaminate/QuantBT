from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from app.research_os.goal_validation_receipts import (
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)


def _receipt(ref: str, *, owner: str = "owner:alice") -> GoalValidationReceipt:
    provisional = GoalValidationReceipt(
        validation_ref="",
        owner_user_id=owner,
        subject_qro_refs=(f"qro:{ref}",),
        graph_command_refs=(f"rgcmd:{ref}",),
        validator_identifiers=("runtime_validator:rollback_v1",),
        test_identifiers=("runtime_check:rollback_v1",),
        outcome=GoalValidationOutcome.PASSED,
        evidence_refs=(f"evidence:{ref}",),
        evidence_digests=("sha256:" + "a" * 64,),
    )
    return replace(
        provisional,
        validation_ref=provisional.canonical_validation_ref,
    )


def test_rollback_reopens_without_target_and_preserves_racing_unrelated_append(
    tmp_path,
) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentGoalValidationReceiptRegistry(path)
    target = _receipt("target")
    unrelated = _receipt("unrelated")
    registry.record_receipt(target)
    other_writer = PersistentGoalValidationReceiptRegistry(path)
    barrier = Barrier(2)

    def append_unrelated() -> GoalValidationReceipt:
        barrier.wait()
        return other_writer.record_receipt(unrelated)

    def rollback_target() -> bool:
        barrier.wait()
        return registry.rollback_exact_receipt(target, dependent_refs=())

    with ThreadPoolExecutor(max_workers=2) as pool:
        append_future = pool.submit(append_unrelated)
        rollback_future = pool.submit(rollback_target)
        assert append_future.result() == unrelated
        assert rollback_future.result() is True

    reopened = PersistentGoalValidationReceiptRegistry(path)
    assert reopened.receipts(owner_user_id="owner:alice") == [unrelated]
    with pytest.raises(KeyError):
        reopened.receipt(
            target.validation_ref,
            owner_user_id="owner:alice",
        )
    assert reopened.rollback_exact_receipt(target, dependent_refs=()) is False


def test_rollback_refuses_same_ref_different_payload_and_live_dependencies(
    tmp_path,
) -> None:
    path = tmp_path / "receipts.jsonl"
    registry = PersistentGoalValidationReceiptRegistry(path)
    target = registry.record_receipt(_receipt("target"))
    before = path.read_bytes()

    with pytest.raises(ValueError, match="identity mismatch"):
        registry.rollback_exact_receipt(
            replace(target, evidence_digests=("sha256:" + "b" * 64,)),
            dependent_refs=(),
        )
    with pytest.raises(ValueError, match="live records reference"):
        registry.rollback_exact_receipt(
            target,
            dependent_refs=("compiler_ir:dependent", "coverage:dependent"),
        )

    assert path.read_bytes() == before
    reopened = PersistentGoalValidationReceiptRegistry(path)
    assert reopened.receipt(
        target.validation_ref,
        owner_user_id=target.owner_user_id,
    ) == target


def test_rollback_refuses_blank_dependency_claim(tmp_path) -> None:
    registry = PersistentGoalValidationReceiptRegistry(tmp_path / "receipts.jsonl")
    target = registry.record_receipt(_receipt("target"))

    with pytest.raises(ValueError, match="must be non-empty refs"):
        registry.rollback_exact_receipt(target, dependent_refs=("",))

    assert registry.receipt(
        target.validation_ref,
        owner_user_id=target.owner_user_id,
    ) == target
