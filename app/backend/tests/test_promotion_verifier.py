from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

import app.ide.promotion_verifier as verifier_module
from app.delivery.rdp import RDPManifest
from app.ide.promotion_evidence import CanonicalPromotionEvidence
from app.ide.promotion_receipt import (
    EXPECTED_GATE_BINDINGS,
    GENERATED_ARTIFACT_INVENTORY_KEY,
    PersistentPromotionReceiptRegistry,
    PromotionCandidateProof,
    canonical_payload_sha256,
)
from app.ide.promotion_verifier import (
    CanonicalPromotionVerificationLoader,
    PromotionVerificationError,
)
from app.release_gate.promote_assembler import AssembledSections


OWNER = "user:alice"
SOURCE = "source-run-42"
PROMOTED = "ide_alice_strategy_verified"
LABEL = "production_ready"
SOURCE_RESULT_CONTENT_HASH = "source-result-content-hash"
GENERATED_ARTIFACT_PAYLOADS = {
    "portfolio.csv": b"timestamp,equity\n2026-01-01,1.0\n",
    "trades.csv": b"timestamp,symbol\n2026-01-01,BTCUSDT\n",
    "attribution.csv": b"period,component\n2026-01-01,alpha\n",
    "strategy.py": b"def strategy():\n    return 'verified'\n",
}


@dataclass(frozen=True)
class CanonicalRecord:
    record_ref: str


@dataclass(frozen=True)
class FakeLLMRecord:
    call_id: str
    owner_user_id: str


class FakeRDPStore:
    def __init__(self, rdp: RDPManifest) -> None:
        self.rdp = rdp
        self.calls: list[tuple[str, str]] = []

    def manifest(self, package_id: str, *, owner_user_id: str) -> RDPManifest:
        self.calls.append((package_id, owner_user_id))
        if package_id != self.rdp.package_id or owner_user_id != OWNER:
            raise KeyError((owner_user_id, package_id))
        return self.rdp


class FakeResolver:
    def __init__(self, evidence: CanonicalPromotionEvidence) -> None:
        self.evidence = evidence
        self.calls: list[dict[str, Any]] = []

    def resolve(self, **kwargs: Any) -> CanonicalPromotionEvidence:
        self.calls.append(kwargs)
        return self.evidence


class FakeReleaseValidation:
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "outcomes": [],
            "rejections": [],
            "honest_gaps": [],
            "reason_text": "all release checks passed",
        }


class FakeChainResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.rejected = bool(payload["rejected"])

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class FakeChain:
    def __init__(self) -> None:
        self.statuses: list[dict[str, bool]] = []

    def evaluate(self, manifest: dict[str, Any], *, producer_status: Any) -> FakeChainResult:
        del manifest
        status = producer_status.as_mapping()
        self.statuses.append(status)
        return FakeChainResult(_chain_base(status))


class FakeLLMStore:
    seal_secret = b"s" * 32

    def __init__(self, record: FakeLLMRecord) -> None:
        self.record = record
        self.calls: list[tuple[str, str]] = []

    def llm_records_for(self, ref: str, *, owner_user_id: str):
        self.calls.append((ref, owner_user_id))
        return (self.record,)


def _all_producer_keys() -> tuple[str, ...]:
    return tuple(binding[2] for binding in EXPECTED_GATE_BINDINGS)


def _evidence(*, producer_keys: tuple[str, ...] | None = None) -> CanonicalPromotionEvidence:
    record = lambda name: (CanonicalRecord(name),)
    return CanonicalPromotionEvidence(
        mathchain_claims=record("mathchain:1"),
        expert_reviews=record("expert-review:1"),
        release_gates=record("trust-gate:1"),
        release_checks=record("trust-check:1"),
        pressure_runs=record("pressure-run:1"),
        release_approvals=record("release-approval:1"),
        mock_records=record("mock:1"),
        data_updates=record("data-update:1"),
        llm_calls=record("llm-standard:1"),
        theory_claims=record("theory-standard:1"),
        fatal_records=record("runtime-standard:1"),
        performance_records=record("performance:1"),
        factor_library_entries=record("factor:1"),
        factor_generators=record("factor-generator:1"),
        signal_protocols=record("signal:1"),
        strategy_books=record("strategy-book:1"),
        validation_methodologies=record("methodology:1"),
        validation_depths=record("depth:1"),
        tier_claims=record("tier:1"),
        verified_producer_keys=(
            _all_producer_keys() if producer_keys is None else producer_keys
        ),
    )


def _section_payloads() -> dict[str, Any]:
    return {
        binding[1]: {"canonical_payload": binding[3]}
        for binding in EXPECTED_GATE_BINDINGS
    }


def _fake_assembler(capture: dict[str, Any]):
    def assemble(_manifest: dict[str, Any], **kwargs: Any) -> AssembledSections:
        capture.clear()
        capture.update(kwargs)
        sections = _section_payloads()
        return AssembledSections(
            sections=sections,
            emitted=tuple(sections),
            absent=(),
            honest_gaps=(),
            verified_producer_keys=tuple(kwargs["verified_producer_keys"]),
        )

    return assemble


def _release_payload() -> dict[str, Any]:
    return {
        **FakeReleaseValidation().to_dict(),
        "gate_evaluation_ok": True,
        "ok": True,
        "release_ready": True,
        "readiness": "ready",
        "unresolved_required_inputs": [],
        "reason": "canonical promote evidence retains unresolved required inputs",
    }


def _chain_base(status: dict[str, bool]) -> dict[str, Any]:
    verdicts: list[dict[str, Any]] = []
    for _section, _manifest_key, producer_key, gate_name in EXPECTED_GATE_BINDINGS:
        green = status.get(producer_key, False) is True
        verdicts.append(
            {
                "gate_name": gate_name,
                "ok": True,
                "advisory_or_enforce": "enforce" if green else "advisory",
                "reason": "fresh canonical verdict",
                "missing": [],
                "producer_key": producer_key,
                "producer_green": green,
                "flip_refused": not green,
                "errored": False,
                "blocks": False,
            }
        )
    return {
        "rejected": False,
        "verdicts": verdicts,
        "rejections": [],
        "advisories": [row for row in verdicts if row["advisory_or_enforce"] == "advisory"],
        "reason_text": "fresh gate chain completed",
    }


def _chain_payload(status: dict[str, bool]) -> dict[str, Any]:
    payload = _chain_base(status)
    all_green = bool(payload["verdicts"]) and all(
        row["producer_green"] is True for row in payload["verdicts"]
    )
    payload["all_registered_producers_green"] = all_green
    payload["release_ready"] = all_green
    return payload


def _write_run(
    run_root: Path,
    rdp: RDPManifest,
    *,
    producer_status: dict[str, bool] | None = None,
) -> tuple[Path, dict[str, Any]]:
    sections = _section_payloads()
    status = (
        {key: True for key in _all_producer_keys()}
        if producer_status is None
        else producer_status
    )
    manifest: dict[str, Any] = {
        "run_id": PROMOTED,
        "strategy_id": "ide_alice",
        "strategy_name": "Canonical strategy",
        "status": "completed",
        "requested_label": LABEL,
        "source": {
            "kind": "ide_verified",
            "ide_run_id": SOURCE,
            "owner_username": "alice",
            "owner_user_id": OWNER,
            "result_content_hash": SOURCE_RESULT_CONTENT_HASH,
        },
        "rdp_package_id": rdp.package_id,
        "research_promote_bridge": {"honest_gaps": []},
        **sections,
        "section_assembly": {
            "emitted": list(sections),
            "absent": [],
            "honest_gaps": [],
        },
        "release_verdict": _release_payload(),
        "promote_gate_chain": _chain_payload(status),
        # This field is attacker-controlled noise.  The loader must remove it
        # and derive status only from AssembledSections.producer_status().
        "producer_status": {key: True for key in _all_producer_keys()},
        GENERATED_ARTIFACT_INVENTORY_KEY: {
            artifact_name: {
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for artifact_name, payload in GENERATED_ARTIFACT_PAYLOADS.items()
        },
    }
    run_dir = run_root / PROMOTED
    run_dir.mkdir(parents=True)
    for artifact_name, payload in GENERATED_ARTIFACT_PAYLOADS.items():
        (run_dir / artifact_name).write_bytes(payload)
    path = run_dir / "run.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, manifest


@pytest.fixture
def verifier_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "runs"
    run_root.mkdir()
    rdp = RDPManifest(asset_ref=f"ide_run:{SOURCE}", asset_kind="model")
    evidence = _evidence()
    rdp_store = FakeRDPStore(rdp)
    resolver = FakeResolver(evidence)
    capture: dict[str, Any] = {}
    chain = FakeChain()
    monkeypatch.setattr(
        verifier_module,
        "assemble_promote_sections",
        _fake_assembler(capture),
    )
    monkeypatch.setattr(
        verifier_module,
        "evaluate_run_releasable",
        lambda *_args, **_kwargs: FakeReleaseValidation(),
    )
    monkeypatch.setattr(verifier_module, "ensure_default_chain", lambda: chain)
    path, manifest = _write_run(run_root, rdp)
    loader = CanonicalPromotionVerificationLoader(
        run_root=run_root,
        rdp_store=rdp_store,
        promotion_evidence_resolver=resolver,
    )
    return {
        "run_root": run_root,
        "path": path,
        "manifest": manifest,
        "rdp": rdp,
        "rdp_store": rdp_store,
        "resolver": resolver,
        "capture": capture,
        "chain": chain,
        "loader": loader,
    }


def _load(loader: CanonicalPromotionVerificationLoader, rdp: RDPManifest):
    return loader(OWNER, SOURCE, PROMOTED, rdp.package_id, LABEL)


def _mutate_same_size(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    assert payload
    payload[0] ^= 1
    path.write_bytes(payload)


def test_exact_canonical_run_returns_full_passing_snapshot(verifier_setup) -> None:
    snapshot = _load(verifier_setup["loader"], verifier_setup["rdp"])

    assert snapshot.outcome == "passed"
    assert snapshot.release_ok is True
    assert snapshot.release_ready is True
    assert snapshot.chain_rejected is False
    assert snapshot.chain_release_ready is True
    assert snapshot.errors == ()
    assert snapshot.residuals == ()
    assert len(snapshot.section_verifications) == len(EXPECTED_GATE_BINDINGS)
    assert all(item.mode == "enforce" for item in snapshot.section_verifications)
    assert all(item.canonical_source_refs for item in snapshot.section_verifications)
    assert all(
        ref.startswith(("typed:", "typed_content_sha256:"))
        for item in snapshot.section_verifications
        for ref in item.canonical_source_refs
    )
    raw_bytes = verifier_setup["path"].read_bytes()
    assert snapshot.run_manifest_sha256 == hashlib.sha256(raw_bytes).hexdigest()
    assert snapshot.release_verdict_sha256 == canonical_payload_sha256(_release_payload())
    assert snapshot.gate_chain_sha256 == canonical_payload_sha256(
        _chain_payload({key: True for key in _all_producer_keys()})
    )
    assert verifier_setup["rdp_store"].calls == [
        (verifier_setup["rdp"].package_id, OWNER)
    ]
    assert verifier_setup["resolver"].calls == [
        {
            "owner_user_id": OWNER,
            "source_ide_run_id": SOURCE,
            "requested_label": LABEL,
            "rdp": verifier_setup["rdp"],
            "source_result_content_hash": SOURCE_RESULT_CONTENT_HASH,
        }
    ]
    assert verifier_setup["capture"]["verified_producer_keys"] == _all_producer_keys()
    assert verifier_setup["chain"].statuses == [
        {key: True for key in _all_producer_keys()}
    ]


@pytest.mark.parametrize(
    "tamper",
    (
        lambda manifest: manifest.__setitem__("run_id", "different-run"),
        lambda manifest: manifest[EXPECTED_GATE_BINDINGS[0][1]].__setitem__(
            "canonical_payload", "forged"
        ),
        lambda manifest: manifest["release_verdict"].__setitem__("ok", False),
        lambda manifest: manifest["promote_gate_chain"].__setitem__(
            "release_ready", False
        ),
        lambda manifest: manifest.__setitem__("requested_label", "proof_backed"),
    ),
    ids=("run_identity", "section", "release_verdict", "gate_chain", "requested_label"),
)
def test_tampered_final_run_is_rejected(verifier_setup, tamper) -> None:
    manifest = verifier_setup["manifest"]
    tamper(manifest)
    verifier_setup["path"].write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PromotionVerificationError):
        _load(verifier_setup["loader"], verifier_setup["rdp"])


def test_exact_run_json_byte_drift_invalidates_a_recorded_receipt(
    verifier_setup, tmp_path: Path
) -> None:
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "promotion_receipts.jsonl",
        verifier_setup["loader"],
    )
    receipt = registry.record_current(
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE,
        promoted_run_id=PROMOTED,
        rdp_package_id=verifier_setup["rdp"].package_id,
        requested_label=LABEL,
    )
    verifier_setup["path"].write_bytes(verifier_setup["path"].read_bytes() + b"\n")

    decision = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE,
        promoted_run_id=PROMOTED,
        rdp_package_id=verifier_setup["rdp"].package_id,
        requested_label=LABEL,
    )

    assert decision.accepted is False
    assert {item.code for item in decision.violations} == {
        "promotion_receipt_current_verification_drift"
    }


def test_prepared_receipt_ref_exactly_matches_durable_commit(
    verifier_setup, tmp_path: Path
) -> None:
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "promotion_receipts.jsonl",
        verifier_setup["loader"],
    )
    identities = {
        "owner_user_id": OWNER,
        "source_ide_run_id": SOURCE,
        "promoted_run_id": PROMOTED,
        "rdp_package_id": verifier_setup["rdp"].package_id,
        "requested_label": LABEL,
    }

    prepared = registry.prepare_current(**identities)
    recorded = registry.record_current(**identities)

    assert prepared == recorded
    assert registry.receipt(
        prepared.receipt_ref,
        owner_user_id=OWNER,
    ) == recorded


def test_hidden_candidate_receipt_is_red_until_exact_final_publish(
    verifier_setup,
    tmp_path: Path,
) -> None:
    run_root = verifier_setup["run_root"]
    staging_root = run_root / ".staging"
    staging_root.mkdir()
    candidate_dir = staging_root / "candidate-exact"
    verifier_setup["path"].parent.rename(candidate_dir)
    candidate_stat = candidate_dir.lstat()
    manifest_sha256 = hashlib.sha256(
        (candidate_dir / "run.json").read_bytes()
    ).hexdigest()
    candidate = PromotionCandidateProof(
        staging_name=candidate_dir.name,
        st_dev=candidate_stat.st_dev,
        st_ino=candidate_stat.st_ino,
        run_manifest_sha256=manifest_sha256,
    )
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "candidate-receipts.jsonl",
        verifier_setup["loader"],
    )
    identities = {
        "owner_user_id": OWNER,
        "source_ide_run_id": SOURCE,
        "promoted_run_id": PROMOTED,
        "rdp_package_id": verifier_setup["rdp"].package_id,
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
    before_publish = registry.validate_current(
        recorded.receipt_ref,
        **identities,
    )
    assert before_publish.accepted is False
    assert {item.code for item in before_publish.violations} == {
        "promotion_receipt_current_verification_unavailable"
    }
    candidate_dir.rename(run_root / PROMOTED)
    after_publish = registry.validate_current(
        recorded.receipt_ref,
        **identities,
    )
    assert after_publish.accepted is True


def test_candidate_identity_and_manifest_hash_are_exactly_bound(
    verifier_setup,
) -> None:
    run_root = verifier_setup["run_root"]
    staging_root = run_root / ".staging"
    staging_root.mkdir()
    candidate_dir = staging_root / "candidate-bound"
    verifier_setup["path"].parent.rename(candidate_dir)
    original = candidate_dir.lstat()
    raw = (candidate_dir / "run.json").read_bytes()
    candidate = PromotionCandidateProof(
        staging_name=candidate_dir.name,
        st_dev=original.st_dev,
        st_ino=original.st_ino,
        run_manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )
    displaced = staging_root / "candidate-displaced"
    candidate_dir.rename(displaced)
    candidate_dir.mkdir()
    (candidate_dir / "run.json").write_bytes(raw)

    with pytest.raises(PromotionVerificationError, match="identity mismatch"):
        verifier_setup["loader"].verify_candidate(
            OWNER,
            SOURCE,
            PROMOTED,
            verifier_setup["rdp"].package_id,
            LABEL,
            candidate=candidate,
        )


def test_candidate_manifest_hash_drift_is_rejected(verifier_setup) -> None:
    run_root = verifier_setup["run_root"]
    staging_root = run_root / ".staging"
    staging_root.mkdir()
    candidate_dir = staging_root / "candidate-drift"
    verifier_setup["path"].parent.rename(candidate_dir)
    candidate_stat = candidate_dir.lstat()
    candidate = PromotionCandidateProof(
        staging_name=candidate_dir.name,
        st_dev=candidate_stat.st_dev,
        st_ino=candidate_stat.st_ino,
        run_manifest_sha256="0" * 64,
    )

    with pytest.raises(PromotionVerificationError, match="manifest hash mismatch"):
        verifier_setup["loader"].verify_candidate(
            OWNER,
            SOURCE,
            PROMOTED,
            verifier_setup["rdp"].package_id,
            LABEL,
            candidate=candidate,
        )


@pytest.mark.parametrize("artifact_name", tuple(GENERATED_ARTIFACT_PAYLOADS))
def test_candidate_artifact_mutation_before_receipt_is_rejected(
    verifier_setup,
    tmp_path: Path,
    artifact_name: str,
) -> None:
    run_root = verifier_setup["run_root"]
    staging_root = run_root / ".staging"
    staging_root.mkdir()
    candidate_dir = staging_root / f"candidate-before-{artifact_name}"
    verifier_setup["path"].parent.rename(candidate_dir)
    candidate_stat = candidate_dir.lstat()
    run_bytes = (candidate_dir / "run.json").read_bytes()
    candidate = PromotionCandidateProof(
        staging_name=candidate_dir.name,
        st_dev=candidate_stat.st_dev,
        st_ino=candidate_stat.st_ino,
        run_manifest_sha256=hashlib.sha256(run_bytes).hexdigest(),
    )
    _mutate_same_size(candidate_dir / artifact_name)
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / f"candidate-before-{artifact_name}.jsonl",
        verifier_setup["loader"],
    )

    with pytest.raises(PromotionVerificationError, match="artifact hash mismatch"):
        registry.record_candidate_current(
            owner_user_id=OWNER,
            source_ide_run_id=SOURCE,
            promoted_run_id=PROMOTED,
            rdp_package_id=verifier_setup["rdp"].package_id,
            requested_label=LABEL,
            candidate=candidate,
        )


@pytest.mark.parametrize("artifact_name", tuple(GENERATED_ARTIFACT_PAYLOADS))
def test_artifact_mutation_after_candidate_receipt_stays_red_after_publish(
    verifier_setup,
    tmp_path: Path,
    artifact_name: str,
) -> None:
    run_root = verifier_setup["run_root"]
    staging_root = run_root / ".staging"
    staging_root.mkdir()
    candidate_dir = staging_root / f"candidate-after-{artifact_name}"
    verifier_setup["path"].parent.rename(candidate_dir)
    candidate_stat = candidate_dir.lstat()
    run_bytes = (candidate_dir / "run.json").read_bytes()
    candidate = PromotionCandidateProof(
        staging_name=candidate_dir.name,
        st_dev=candidate_stat.st_dev,
        st_ino=candidate_stat.st_ino,
        run_manifest_sha256=hashlib.sha256(run_bytes).hexdigest(),
    )
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / f"candidate-after-{artifact_name}.jsonl",
        verifier_setup["loader"],
    )
    identities = {
        "owner_user_id": OWNER,
        "source_ide_run_id": SOURCE,
        "promoted_run_id": PROMOTED,
        "rdp_package_id": verifier_setup["rdp"].package_id,
        "requested_label": LABEL,
    }
    receipt = registry.record_candidate_current(
        **identities,
        candidate=candidate,
    )
    _mutate_same_size(candidate_dir / artifact_name)
    candidate_dir.rename(run_root / PROMOTED)

    decision = registry.validate_current(receipt.receipt_ref, **identities)

    assert decision.accepted is False
    assert {item.code for item in decision.violations} == {
        "promotion_receipt_current_verification_unavailable"
    }


def test_unexpected_consumer_artifact_is_rejected(verifier_setup) -> None:
    run_dir = verifier_setup["path"].parent
    (run_dir / "unexpected-consumer.csv").write_text(
        "must not be ignored",
        encoding="utf-8",
    )

    with pytest.raises(PromotionVerificationError, match="exact inventory"):
        _load(verifier_setup["loader"], verifier_setup["rdp"])


def test_linked_generated_artifact_is_rejected(
    verifier_setup,
    tmp_path: Path,
) -> None:
    artifact = verifier_setup["path"].parent / "portfolio.csv"
    foreign = tmp_path / "foreign-portfolio.csv"
    foreign.write_bytes(artifact.read_bytes())
    artifact.unlink()
    artifact.symlink_to(foreign)

    with pytest.raises(PromotionVerificationError, match="linked, or unreadable"):
        _load(verifier_setup["loader"], verifier_setup["rdp"])


def test_missing_final_run_invalidates_a_recorded_receipt(
    verifier_setup, tmp_path: Path
) -> None:
    registry = PersistentPromotionReceiptRegistry(
        tmp_path / "promotion_receipts.jsonl",
        verifier_setup["loader"],
    )
    receipt = registry.record_current(
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE,
        promoted_run_id=PROMOTED,
        rdp_package_id=verifier_setup["rdp"].package_id,
        requested_label=LABEL,
    )
    verifier_setup["path"].unlink()
    for artifact_name in GENERATED_ARTIFACT_PAYLOADS:
        (verifier_setup["path"].parent / artifact_name).unlink()
    verifier_setup["path"].parent.rmdir()

    decision = registry.validate_current(
        receipt.receipt_ref,
        owner_user_id=OWNER,
        source_ide_run_id=SOURCE,
        promoted_run_id=PROMOTED,
        rdp_package_id=verifier_setup["rdp"].package_id,
        requested_label=LABEL,
    )

    assert decision.accepted is False
    assert {item.code for item in decision.violations} == {
        "promotion_receipt_current_verification_unavailable"
    }


def test_unknown_receipt_context_label_is_rejected_before_resolution(
    verifier_setup,
) -> None:
    with pytest.raises(PromotionVerificationError, match="label is unknown"):
        verifier_setup["loader"](
            OWNER,
            SOURCE,
            PROMOTED,
            verifier_setup["rdp"].package_id,
            "production-readi",
        )

    assert verifier_setup["resolver"].calls == []


def test_path_traversal_and_linked_run_directory_are_rejected(verifier_setup) -> None:
    loader = verifier_setup["loader"]
    rdp = verifier_setup["rdp"]
    with pytest.raises(PromotionVerificationError, match="direct run_root child"):
        loader(OWNER, SOURCE, "../" + PROMOTED, rdp.package_id, LABEL)

    linked_id = "linked-run"
    (verifier_setup["run_root"] / linked_id).symlink_to(
        verifier_setup["path"].parent,
        target_is_directory=True,
    )
    with pytest.raises(PromotionVerificationError, match="linked"):
        loader(OWNER, SOURCE, linked_id, rdp.package_id, LABEL)


def test_symlink_run_root_is_rejected(verifier_setup, tmp_path: Path) -> None:
    linked_root = tmp_path / "linked-run-root"
    linked_root.symlink_to(
        verifier_setup["run_root"],
        target_is_directory=True,
    )
    loader = CanonicalPromotionVerificationLoader(
        run_root=linked_root,
        rdp_store=verifier_setup["rdp_store"],
        promotion_evidence_resolver=verifier_setup["resolver"],
    )

    with pytest.raises(PromotionVerificationError, match="real no-follow"):
        _load(loader, verifier_setup["rdp"])


def test_cross_owner_run_and_rdp_lookup_are_rejected(verifier_setup) -> None:
    rdp = verifier_setup["rdp"]
    with pytest.raises(PromotionVerificationError, match="source owner mismatch"):
        verifier_setup["loader"](
            "user:bob",
            SOURCE,
            PROMOTED,
            rdp.package_id,
            LABEL,
        )

    verifier_setup["manifest"]["source"]["owner_user_id"] = "user:bob"
    verifier_setup["path"].write_text(
        json.dumps(verifier_setup["manifest"]), encoding="utf-8"
    )
    with pytest.raises(PromotionVerificationError, match="owner scope"):
        verifier_setup["loader"](
            "user:bob",
            SOURCE,
            PROMOTED,
            rdp.package_id,
            LABEL,
        )


def test_stored_producer_green_cannot_replace_canonical_receipts(
    verifier_setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    red_evidence = _evidence(producer_keys=())
    resolver = FakeResolver(red_evidence)
    loader = CanonicalPromotionVerificationLoader(
        run_root=verifier_setup["run_root"],
        rdp_store=verifier_setup["rdp_store"],
        promotion_evidence_resolver=resolver,
    )
    capture: dict[str, Any] = {}
    monkeypatch.setattr(
        verifier_module,
        "assemble_promote_sections",
        _fake_assembler(capture),
    )
    red_status = {key: False for key in _all_producer_keys()}
    verifier_setup["manifest"]["promote_gate_chain"] = _chain_payload(red_status)
    verifier_setup["path"].write_text(
        json.dumps(verifier_setup["manifest"]), encoding="utf-8"
    )

    snapshot = _load(loader, verifier_setup["rdp"])

    assert snapshot.outcome == "failed"
    assert snapshot.chain_release_ready is False
    assert all(item.mode == "advisory" for item in snapshot.section_verifications)
    assert any("canonical_producer_not_green" in item for item in snapshot.residuals)
    assert verifier_setup["manifest"]["producer_status"] == {
        key: True for key in _all_producer_keys()
    }
    assert verifier_setup["chain"].statuses[-1] == {}


def test_registered_section_without_typed_sources_is_rejected(
    verifier_setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = replace(
        _evidence(),
        factor_library_entries=(),
        factor_generators=(),
        signal_protocols=(),
        strategy_books=(),
    )
    capture: dict[str, Any] = {}
    monkeypatch.setattr(
        verifier_module,
        "assemble_promote_sections",
        _fake_assembler(capture),
    )
    loader = CanonicalPromotionVerificationLoader(
        run_root=verifier_setup["run_root"],
        rdp_store=verifier_setup["rdp_store"],
        promotion_evidence_resolver=FakeResolver(evidence),
    )

    with pytest.raises(PromotionVerificationError, match="no server-derived"):
        _load(loader, verifier_setup["rdp"])


def test_llm_lookup_rejects_foreign_owner_records(verifier_setup) -> None:
    store = FakeLLMStore(FakeLLMRecord(call_id="call-1", owner_user_id="user:bob"))
    loader = CanonicalPromotionVerificationLoader(
        run_root=verifier_setup["run_root"],
        rdp_store=verifier_setup["rdp_store"],
        promotion_evidence_resolver=verifier_setup["resolver"],
        llm_call_record_store=store,
    )

    with pytest.raises(PromotionVerificationError, match="another owner"):
        _load(loader, verifier_setup["rdp"])
    assert store.calls[0][1] == OWNER
