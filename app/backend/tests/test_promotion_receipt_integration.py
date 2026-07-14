from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

import app.ide.promote as promote_module
import app.release_gate.gate_registry as gate_registry_module
import app.release_gate.promote_assembler as assembler_module
from app.delivery.rdp import RDPManifest
from app.governance.enforcement_policy import ProducerStatusLedger
from app.ide.promote import (
    PromoteCommitError,
    PromoteError,
    PromotedRun,
    promote_ide_run,
    quarantine_promoted_run,
)
from app.ide.promotion_evidence import CanonicalPromotionEvidence
from app.ide.promotion_receipt import (
    EXPECTED_GATE_BINDINGS,
    GENERATED_ARTIFACT_INVENTORY_KEY,
)
from app.release_gate.promote_assembler import AssembledSections
from app.research_os.rdp_reproduction import (
    PersistentRDPReproductionReceiptStore,
    RDPReproductionSourceEvidence,
    RDPReproductionVerificationSnapshot,
    ResolvedRDPReproductionSource,
    rdp_manifest_hash,
)


OWNER = "user:alice"
SOURCE_RUN = "ide-source-receipt"
DATASET_VERSION = "dataset_version:prices:v1"
REPRODUCTION_RUNNER = "backend_runner:rdp_reproduction:v1"
_DEFAULT_PRECOMMIT = object()


def _precommit_refs() -> dict[str, str]:
    return {
        "qro_id": "qro_precommitted",
        "research_graph_command_id": "rgcmd_precommitted",
        "compiler_ir_ref": "compiler_ir:precommitted",
        "compiler_pass_ref": "compiler_pass:precommitted",
        "entrypoint_coverage_ref": "goal_entrypoint_coverage:precommitted",
    }


class _RDPStore:
    def __init__(self, manifest: RDPManifest) -> None:
        self._manifest = manifest

    def manifest(self, package_id: str, *, owner_user_id: str) -> RDPManifest:
        if package_id != self._manifest.package_id or owner_user_id != OWNER:
            raise KeyError(package_id)
        return self._manifest


class _EvidenceResolver:
    def resolve(self, **_kwargs) -> CanonicalPromotionEvidence:
        return CanonicalPromotionEvidence(
            verified_producer_keys=tuple(
                binding[2] for binding in EXPECTED_GATE_BINDINGS
            )
        )


def _source_resolver(owner_user_id, manifest, source_result_content_hash):
    assert owner_user_id == OWNER
    strategy_code = "pass"
    return ResolvedRDPReproductionSource(
        evidence=RDPReproductionSourceEvidence(
            package_id=manifest.package_id,
            source_run_ref=manifest.run_refs[0],
            source_run_id=SOURCE_RUN,
            source_file_ref=manifest.source_file_refs[0],
            manifest_hash=rdp_manifest_hash(manifest),
            source_artifact_hash=manifest.artifact_hash,
            source_integrity_hash="sha16:" + "1" * 16,
            source_bundle_index_sha256="sha256:" + "2" * 64,
            source_run_manifest_sha256="sha256:" + "3" * 64,
            source_strategy_sha256="sha256:"
            + hashlib.sha256(strategy_code.encode()).hexdigest(),
            source_result_sha256="sha256:" + "4" * 64,
            expected_replay_result_sha256="sha256:" + "5" * 64,
            source_portfolio_sha256="sha256:" + "6" * 64,
            source_result_content_hash=source_result_content_hash,
            expected_replay_artifact_hash="sha256:" + "7" * 64,
        ),
        strategy_code=strategy_code,
    )


def _reproduction_loader(owner_user_id, manifest, spec, resolved_source):
    assert owner_user_id == OWNER
    assert resolved_source.evidence.source_evidence_hash == spec.source_evidence_hash
    now = dt.datetime.now(dt.UTC)
    return RDPReproductionVerificationSnapshot(
        package_id=spec.package_id,
        manifest_hash=spec.manifest_hash,
        spec_hash=spec.spec_hash,
        expected_artifact_hash=spec.artifact_hash,
        observed_artifact_hash=spec.artifact_hash,
        expected_source_result_content_hash=spec.source_result_content_hash,
        observed_source_result_content_hash=spec.source_result_content_hash,
        expected_source_integrity_hash=spec.source_integrity_hash,
        observed_source_integrity_hash=spec.source_integrity_hash,
        expected_source_strategy_sha256=spec.source_strategy_sha256,
        observed_source_strategy_sha256=spec.source_strategy_sha256,
        expected_replay_result_sha256=spec.expected_replay_result_sha256,
        observed_replay_result_sha256=spec.expected_replay_result_sha256,
        expected_replay_artifact_hash=spec.expected_replay_artifact_hash,
        observed_replay_artifact_hash=spec.expected_replay_artifact_hash,
        environment_lock_ref=spec.environment_lock_ref,
        outcome="passed",
        passed=True,
        runner_ref=REPRODUCTION_RUNNER,
        evidence_refs=("evidence:reproduction-log:sha256:abc",),
        verified_at_utc=now.isoformat(),
        valid_until_utc=(now + dt.timedelta(minutes=10)).isoformat(),
    )


class _ReceiptRegistry:
    def __init__(self, *, fail: bool = False, fail_validate: bool = False) -> None:
        self.fail = fail
        self.fail_validate = fail_validate
        self.calls: list[dict[str, str]] = []
        self.preview_calls: list[dict[str, str]] = []
        self.candidates = []
        self.events: list[str] = []

    def prepare_candidate_current(self, *, candidate, **identities):
        self.preview_calls.append(dict(identities))
        self.candidates.append(candidate)
        self.events.append("prepare")
        return SimpleNamespace(receipt_ref="ide_promotion_receipt:verified")

    def record_candidate_current(self, *, candidate, **identities):
        self.calls.append(dict(identities))
        self.candidates.append(candidate)
        self.events.append("record")
        if self.fail:
            raise OSError("simulated receipt append failure")
        return SimpleNamespace(receipt_ref="ide_promotion_receipt:verified")

    def validate_current(self, _receipt_ref, **_identities):
        self.events.append("validate")
        if self.fail_validate:
            return SimpleNamespace(
                accepted=False,
                violations=(SimpleNamespace(code="injected_current_failure"),),
            )
        return SimpleNamespace(accepted=True, violations=())


class _ArtifactDetectingReceiptRegistry(_ReceiptRegistry):
    def __init__(self, run_root, artifact_name: str) -> None:
        super().__init__()
        self.run_root = run_root
        self.artifact_name = artifact_name

    def validate_current(self, _receipt_ref, **identities):
        self.events.append("validate")
        run_dir = self.run_root / identities["promoted_run_id"]
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        descriptor = manifest[GENERATED_ARTIFACT_INVENTORY_KEY][
            self.artifact_name
        ]
        payload = (run_dir / self.artifact_name).read_bytes()
        assert descriptor != {
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        return SimpleNamespace(
            accepted=False,
            violations=(SimpleNamespace(code="artifact_inventory_mismatch"),),
        )


class _ReleaseResult:
    def to_dict(self):
        return {
            "ok": True,
            "outcomes": [],
            "rejections": [],
            "honest_gaps": [],
            "reason_text": "passed",
        }


class _ChainResult:
    rejected = False
    reason_text = "passed"

    def __init__(self, producer_status: ProducerStatusLedger) -> None:
        status = producer_status.as_mapping()
        self._payload = {
            "rejected": False,
            "verdicts": [
                {
                    "gate_name": gate_name,
                    "producer_key": producer_key,
                    "producer_green": status.get(producer_key) is True,
                }
                for _section, _manifest_key, producer_key, gate_name in EXPECTED_GATE_BINDINGS
            ],
            "rejections": [],
            "advisories": [],
            "reason_text": "passed",
        }

    def to_dict(self):
        return dict(self._payload)


class _Chain:
    def __init__(self) -> None:
        self.statuses: list[dict[str, bool]] = []

    def evaluate(self, _manifest, *, producer_status):
        self.statuses.append(producer_status.as_mapping())
        return _ChainResult(producer_status)


def _install_complete_gate_path(monkeypatch):
    verified_keys = tuple(binding[2] for binding in EXPECTED_GATE_BINDINGS)
    sections = {
        manifest_key: {"canonical": gate_name}
        for _section, manifest_key, _producer_key, gate_name in EXPECTED_GATE_BINDINGS
    }

    def assemble(_manifest, **_kwargs):
        return AssembledSections(
            sections=sections,
            emitted=tuple(sections),
            absent=(),
            honest_gaps=(),
            verified_producer_keys=verified_keys,
        )

    chain = _Chain()
    monkeypatch.setattr(assembler_module, "assemble_promote_sections", assemble)
    monkeypatch.setattr(
        assembler_module,
        "evaluate_run_releasable",
        lambda *_args, **_kwargs: _ReleaseResult(),
    )
    monkeypatch.setattr(
        gate_registry_module,
        "ensure_default_chain",
        lambda **_kwargs: chain,
    )
    monkeypatch.setattr(
        promote_module,
        "_run_overfit_gate",
        lambda **_kwargs: {
            "color": "green",
            "config_hash": "config:verified",
            "honest_n": 10,
        },
    )
    return chain


def _mutate_same_size(path) -> None:
    payload = bytearray(path.read_bytes())
    assert payload
    payload[0] ^= 1
    path.write_bytes(payload)


def _promote(
    tmp_path,
    monkeypatch,
    registry,
    *,
    producer_status=None,
    promotion_precommit_hook=_DEFAULT_PRECOMMIT,
    promotion_precommit_compensator=_DEFAULT_PRECOMMIT,
    run_root=None,
):
    chain = _install_complete_gate_path(monkeypatch)
    rdp = RDPManifest(
        research_question="Can the exact IDE result be reproduced?",
        graph_refs=("research_graph:ide-source-receipt",),
        data_refs=("dataset:prices",),
        asset_ref=f"ide_run:{SOURCE_RUN}",
        asset_kind="strategybook",
        dataset_version_refs=(DATASET_VERSION,),
        market_data_use_validation_refs=("market_data_use:prices:backtest",),
        ingestion_skill_refs=("ingestion_skill:prices:v1",),
        mathematical_refs=("math:strategy:v1",),
        theory_binding_refs=("theory_binding:strategy:v1",),
        consistency_check_refs=("consistency_check:strategy:v1",),
        code_refs=("source:strategy.py",),
        environment_lock_ref="environment_lock:uv.lock:sha256:abc",
        reproducibility_command="documentation only; not executable authority",
        artifact_hash="sha256:artifact-exact",
        test_refs=("test:strategy:v1",),
        run_refs=("run:ide-source-receipt",),
        honest_n_refs=("honest_n:strategy:v1",),
        cost_and_execution_assumptions=("fee=10bps",),
        known_limits=("single fixture",),
        unverified_residuals=("live slippage unverified",),
        verifier_verdict_ref="verifier:ide-source-receipt",
        compiler_artifact_refs=("compiler_artifact:ide-source-receipt",),
        mathematical_spine_chain_refs=("math_spine_chain:ide-source-receipt",),
        goal_entrypoint_coverage_refs=("goal_coverage:ide-source-receipt",),
        source_file_refs=("source_file:strategy.py",),
    )
    reproduction_receipt_store = PersistentRDPReproductionReceiptStore(
        tmp_path / "audit" / "rdp_reproduction_receipts.jsonl",
        _reproduction_loader,
        source_resolver=_source_resolver,
        allowed_runner_refs=(REPRODUCTION_RUNNER,),
    )
    if promotion_precommit_hook is _DEFAULT_PRECOMMIT:
        promotion_precommit_hook = lambda _pending: _precommit_refs()
    if promotion_precommit_compensator is _DEFAULT_PRECOMMIT:
        promotion_precommit_compensator = lambda _pending, _refs: None
    promoted = promote_ide_run(
        ide_run_id=SOURCE_RUN,
        owner_username="alice",
        owner_user_id=OWNER,
        strategy_name="receipt_strategy",
        strategy_code="pass",
        result={
            "equity_curve": [
                {"t": "2026-01-01", "equity": 1.0},
                {"t": "2026-01-02", "equity": 1.1},
            ],
            "trades": [
                {
                    "timestamp": "2026-01-02",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "quantity": 1,
                    "price": 100,
                }
            ],
            "attribution": [
                {
                    "period": "2026-01",
                    "component": "market",
                    "portfolio_weight": "0.6",
                    "benchmark_weight": "0.5",
                    "portfolio_return": "0.10",
                    "benchmark_return": "0.08",
                    "benchmark_total_return": "0.07",
                    "allocation_effect": "0.001",
                    "selection_effect": "0.010",
                    "interaction_effect": "0.002",
                    "cost_effect": "0.001",
                    "net_contribution": "0.012",
                }
            ],
            "metadata": {"dataset_version": DATASET_VERSION},
        },
        run_root=run_root or (tmp_path / "runs"),
        ledger=object(),
        returns_store=object(),
        producer_status=producer_status,
        rdp_package_id=rdp.package_id,
        rdp_store=_RDPStore(rdp),
        reproduction_receipt_store=reproduction_receipt_store,
        requested_label="exploratory",
        promotion_evidence_resolver=_EvidenceResolver(),
        promotion_receipt_registry=registry,
        canonical_overfit_registry=object(),
        promotion_precommit_hook=promotion_precommit_hook,
        promotion_precommit_compensator=promotion_precommit_compensator,
    )
    return promoted, chain


def test_receipt_is_recorded_after_publish_and_attached_to_result(tmp_path, monkeypatch) -> None:
    registry = _ReceiptRegistry()

    promoted, chain = _promote(tmp_path, monkeypatch, registry)

    assert promoted.run_dir.is_dir()
    assert promoted.promotion_receipt_ref == "ide_promotion_receipt:verified"
    manifest = json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["requested_label"] == "exploratory"
    assert manifest["rdp_reproduction_receipt"]["passed"] is True
    assert manifest["rdp_reproduction_receipt"]["package_id"] == manifest["rdp_package_id"]
    inventory = manifest[GENERATED_ARTIFACT_INVENTORY_KEY]
    assert set(inventory) == {
        "portfolio.csv",
        "trades.csv",
        "attribution.csv",
        "strategy.py",
    }
    for artifact_name, descriptor in inventory.items():
        payload = (promoted.run_dir / artifact_name).read_bytes()
        assert descriptor == {
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    assert registry.calls == [
        {
            "owner_user_id": OWNER,
            "source_ide_run_id": SOURCE_RUN,
            "promoted_run_id": promoted.run_id,
            "rdp_package_id": registry.calls[0]["rdp_package_id"],
            "requested_label": "exploratory",
        }
    ]
    assert all(chain.statuses[0].values())


def test_receipt_path_ignores_injected_producer_status(tmp_path, monkeypatch) -> None:
    attacker = ProducerStatusLedger()
    registry = _ReceiptRegistry()

    _promote(tmp_path, monkeypatch, registry, producer_status=attacker)

    # The attacker ledger is entirely red, while the chain received the
    # canonical assembly ledger and therefore saw every verified producer.
    assert not any(attacker.as_mapping().values())


@pytest.mark.parametrize(
    ("hook", "compensator"),
    (
        (None, lambda _pending, _refs: None),
        (lambda _pending: _precommit_refs(), None),
    ),
    ids=("missing-hook", "missing-compensator"),
)
def test_receipt_requires_complete_precommit_contract_before_publish(
    tmp_path,
    monkeypatch,
    hook,
    compensator,
) -> None:
    registry = _ReceiptRegistry()

    with pytest.raises(
        PromoteError,
        match="requires QRO precommit hook and compensator",
    ):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_hook=hook,
            promotion_precommit_compensator=compensator,
        )

    assert registry.events == []
    assert not (tmp_path / "runs").exists()


def test_formal_promotion_refuses_symlink_run_root(
    tmp_path,
    monkeypatch,
) -> None:
    real_root = tmp_path / "real-runs"
    real_root.mkdir()
    linked_root = tmp_path / "linked-runs"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(PromoteError, match="must be a real no-follow directory"):
        _promote(
            tmp_path,
            monkeypatch,
            _ReceiptRegistry(),
            run_root=linked_root,
        )

    assert list(real_root.iterdir()) == []


def test_receipt_append_failure_quarantines_new_run_from_visible_root(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry(fail=True)

    with pytest.raises(PromoteError, match="durable promotion verification failed"):
        _promote(tmp_path, monkeypatch, registry)

    run_root = tmp_path / "runs"
    assert not any(path.is_dir() and (path / "run.json").exists() for path in run_root.iterdir())
    quarantined = list((run_root / ".staging").glob("*.receipt_failed.*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "run.json").is_file()


def _published_run(run_root, run_id="formal_run") -> PromotedRun:
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text("{}", encoding="utf-8")
    return PromotedRun(run_id=run_id, run_dir=run_dir, metrics={})


def test_quarantine_rename_preserves_captured_run_identity(tmp_path) -> None:
    run_root = tmp_path / "runs"
    promoted = _published_run(run_root)
    before = promoted.run_dir.lstat()

    quarantined = quarantine_promoted_run(
        promoted,
        phase="receipt_failed",
        expected_run_root=run_root,
    )

    assert quarantined is not None
    after = quarantined.lstat()
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert not promoted.run_dir.exists()


def test_publish_destination_race_preserves_foreign_empty_directory(
    tmp_path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "runs"
    staging = run_root / ".staging"
    staging.mkdir(parents=True)
    candidate_name = "candidate-race"
    candidate_dir = staging / candidate_name
    candidate_dir.mkdir()
    candidate_stat = candidate_dir.lstat()
    captured_foreign_identity = []
    rename_noreplace = promote_module._rename_noreplace_at

    def collide_after_destination_check(
        src_dir_fd,
        src_name,
        dst_dir_fd,
        dst_name,
    ):
        os.mkdir(dst_name, dir_fd=dst_dir_fd)
        foreign = os.stat(dst_name, dir_fd=dst_dir_fd, follow_symlinks=False)
        captured_foreign_identity.append((foreign.st_dev, foreign.st_ino))
        return rename_noreplace(
            src_dir_fd,
            src_name,
            dst_dir_fd,
            dst_name,
        )

    monkeypatch.setattr(
        promote_module,
        "_rename_noreplace_at",
        collide_after_destination_check,
    )
    run_root_fd = os.open(run_root, os.O_RDONLY | os.O_DIRECTORY)
    staging_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(
            PromoteError,
            match="atomic publish rename failed; hidden candidate retained",
        ):
            promote_module._publish_hidden_candidate(
                run_root_fd=run_root_fd,
                staging_fd=staging_fd,
                candidate_name=candidate_name,
                run_id="foreign-final",
                candidate_identity=(candidate_stat.st_dev, candidate_stat.st_ino),
            )
    finally:
        os.close(staging_fd)
        os.close(run_root_fd)

    assert candidate_dir.is_dir()
    assert (run_root / "foreign-final").is_dir()
    foreign_after = (run_root / "foreign-final").lstat()
    assert captured_foreign_identity == [
        (foreign_after.st_dev, foreign_after.st_ino)
    ]
    assert list((run_root / "foreign-final").iterdir()) == []


def test_hidden_audit_collision_preserves_foreign_empty_directory(
    tmp_path,
    monkeypatch,
) -> None:
    staging = tmp_path / "runs" / ".staging"
    staging.mkdir(parents=True)
    candidate_name = "candidate-audit-collision"
    candidate_dir = staging / candidate_name
    candidate_dir.mkdir()
    candidate_stat = candidate_dir.lstat()
    monkeypatch.setattr(promote_module, "token_urlsafe", lambda _size: "collision")
    foreign = staging / f"{candidate_name}.receipt_failed.collision"
    foreign.mkdir()
    foreign_before = foreign.lstat()
    staging_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(
            PromoteError,
            match="audit rename failed; candidate retained",
        ):
            promote_module._rename_hidden_candidate_for_audit(
                staging_fd,
                candidate_name=candidate_name,
                candidate_identity=(candidate_stat.st_dev, candidate_stat.st_ino),
                phase="receipt_failed",
            )
    finally:
        os.close(staging_fd)

    assert candidate_dir.is_dir()
    foreign_after = foreign.lstat()
    assert (foreign_after.st_dev, foreign_after.st_ino) == (
        foreign_before.st_dev,
        foreign_before.st_ino,
    )
    assert list(foreign.iterdir()) == []


def test_quarantine_collision_preserves_foreign_empty_directory(
    tmp_path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "runs"
    promoted = _published_run(run_root)
    staging = run_root / ".staging"
    staging.mkdir()
    monkeypatch.setattr(promote_module, "token_urlsafe", lambda _size: "collision")
    foreign = staging / f"{promoted.run_id}.receipt_failed.collision"
    foreign.mkdir()
    foreign_before = foreign.lstat()

    with pytest.raises(
        PromoteError,
        match="atomic quarantine rename failed; exact run left visible",
    ):
        quarantine_promoted_run(
            promoted,
            phase="receipt_failed",
            expected_run_root=run_root,
        )

    assert promoted.run_dir.is_dir()
    assert (promoted.run_dir / "run.json").is_file()
    foreign_after = foreign.lstat()
    assert (foreign_after.st_dev, foreign_after.st_ino) == (
        foreign_before.st_dev,
        foreign_before.st_ino,
    )
    assert list(foreign.iterdir()) == []


def test_quarantine_refuses_same_basename_below_foreign_root(tmp_path) -> None:
    trusted_root = tmp_path / "trusted-runs"
    trusted_root.mkdir()
    foreign_root = tmp_path / "foreign-runs"
    promoted = _published_run(foreign_root)

    with pytest.raises(PromoteError, match="identity mismatch"):
        quarantine_promoted_run(
            promoted,
            phase="receipt_failed",
            expected_run_root=trusted_root,
        )

    assert promoted.run_dir.is_dir()
    assert (promoted.run_dir / "run.json").is_file()
    assert not (trusted_root / ".staging").exists()


def test_quarantine_refuses_symlink_run_root(tmp_path) -> None:
    real_root = tmp_path / "real-runs"
    promoted = _published_run(real_root)
    linked_root = tmp_path / "linked-runs"
    linked_root.symlink_to(real_root, target_is_directory=True)
    linked_promoted = PromotedRun(
        run_id=promoted.run_id,
        run_dir=linked_root / promoted.run_id,
        metrics={},
    )

    with pytest.raises(PromoteError, match="must be a real no-follow directory"):
        quarantine_promoted_run(
            linked_promoted,
            phase="receipt_failed",
            expected_run_root=linked_root,
        )

    assert promoted.run_dir.is_dir()
    assert (promoted.run_dir / "run.json").is_file()


def test_quarantine_refuses_symlink_run(tmp_path) -> None:
    run_root = tmp_path / "runs"
    run_root.mkdir()
    foreign_run = tmp_path / "foreign-run"
    foreign_run.mkdir()
    (foreign_run / "run.json").write_text("{}", encoding="utf-8")
    run_dir = run_root / "formal_run"
    run_dir.symlink_to(foreign_run, target_is_directory=True)
    promoted = PromotedRun(
        run_id="formal_run",
        run_dir=run_dir,
        metrics={},
    )

    with pytest.raises(PromoteError, match="refuses a symlink run"):
        quarantine_promoted_run(
            promoted,
            phase="receipt_failed",
            expected_run_root=run_root,
        )

    assert run_dir.is_symlink()
    assert (foreign_run / "run.json").is_file()


def test_quarantine_refuses_symlink_staging_root(tmp_path) -> None:
    run_root = tmp_path / "runs"
    promoted = _published_run(run_root)
    foreign_staging = tmp_path / "foreign-staging"
    foreign_staging.mkdir()
    (run_root / ".staging").symlink_to(
        foreign_staging,
        target_is_directory=True,
    )

    with pytest.raises(PromoteError, match="must be a real no-follow directory"):
        quarantine_promoted_run(
            promoted,
            phase="receipt_failed",
            expected_run_root=run_root,
        )

    assert promoted.run_dir.is_dir()
    assert (run_root / ".staging").is_symlink()
    assert list(foreign_staging.iterdir()) == []


def test_quarantine_refuses_replaced_identity_after_failed_rename(
    tmp_path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "runs"
    promoted = _published_run(run_root)
    displaced = run_root / "displaced-original"

    def replace_identity_then_fail(
        src_dir_fd,
        src,
        dst_dir_fd,
        dst,
    ):
        assert src == promoted.run_id
        assert dst.startswith(f"{promoted.run_id}.receipt_failed.")
        assert src_dir_fd is not None
        assert dst_dir_fd is not None
        promoted.run_dir.replace(displaced)
        promoted.run_dir.mkdir()
        (promoted.run_dir / "replacement.txt").write_text(
            "must survive",
            encoding="utf-8",
        )
        raise OSError("injected rename failure after identity replacement")

    monkeypatch.setattr(
        promote_module,
        "_rename_noreplace_at",
        replace_identity_then_fail,
    )

    with pytest.raises(
        PromoteError,
        match="identity changed during quarantine rename",
    ):
        quarantine_promoted_run(
            promoted,
            phase="receipt_failed",
            expected_run_root=run_root,
        )

    assert (promoted.run_dir / "replacement.txt").read_text(
        encoding="utf-8"
    ) == "must survive"
    assert (displaced / "run.json").is_file()
    assert list((run_root / ".staging").iterdir()) == []


def test_quarantine_rename_failure_never_deletes_unchanged_identity(
    tmp_path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "runs"
    promoted = _published_run(run_root)

    def fail_rename(*_args, **_kwargs):
        raise OSError("injected rename failure")

    monkeypatch.setattr(promote_module, "_rename_noreplace_at", fail_rename)

    with pytest.raises(
        PromoteError,
        match="atomic quarantine rename failed; exact run left visible",
    ):
        quarantine_promoted_run(
            promoted,
            phase="receipt_failed",
            expected_run_root=run_root,
        )

    assert promoted.run_dir.is_dir()
    assert (promoted.run_dir / "run.json").is_file()


def test_precommit_lineage_runs_before_receipt_authority_commit(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry()
    observed = []

    def precommit(pending):
        pending_root = pending.run_dir.parent.parent
        observed.append(
            (
                pending.promotion_receipt_ref,
                pending.run_dir.is_dir(),
                pending.run_dir.parent.name,
                tuple(
                    path.name
                    for path in pending_root.iterdir()
                    if path.name != ".staging" and (path / "run.json").is_file()
                ),
                tuple(registry.events),
            )
        )
        registry.events.append("lineage")
        return _precommit_refs()

    promoted, _chain = _promote(
        tmp_path,
        monkeypatch,
        registry,
        promotion_precommit_hook=precommit,
    )

    assert promoted.promotion_receipt_ref == "ide_promotion_receipt:verified"
    assert observed == [
        (
            "ide_promotion_receipt:verified",
            True,
            ".staging",
            (),
            ("prepare",),
        )
    ]
    assert registry.events == ["prepare", "lineage", "record", "validate"]


def test_precommit_failure_quarantines_run_before_receipt_is_recorded(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry()

    def fail_precommit(_pending):
        raise RuntimeError("injected lineage failure")

    with pytest.raises(PromoteCommitError, match="RuntimeError"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_hook=fail_precommit,
        )

    assert registry.preview_calls
    assert registry.calls == []
    run_root = tmp_path / "runs"
    assert not any(
        path.is_dir() and (path / "run.json").exists()
        for path in run_root.iterdir()
        if path.name != ".staging"
    )
    quarantined = list((run_root / ".staging").glob("*.receipt_failed.*"))
    assert len(quarantined) == 1


@pytest.mark.parametrize(
    "bad_result",
    (
        None,
        {},
        {"qro_id": "qro_only"},
        {**_precommit_refs(), "extra_ref": "extra:value"},
        {**_precommit_refs(), "qro_id": "qro:wrong-prefix"},
    ),
)
def test_malformed_precommit_result_cannot_commit_receipt(
    tmp_path,
    monkeypatch,
    bad_result,
) -> None:
    registry = _ReceiptRegistry()

    with pytest.raises(PromoteCommitError, match="PromoteError"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_hook=lambda _pending: bad_result,
        )

    assert registry.calls == []
    assert not any(
        path.is_dir() and (path / "run.json").exists()
        for path in (tmp_path / "runs").iterdir()
        if path.name != ".staging"
    )


def test_hook_tail_failure_invokes_compensator_without_returned_refs(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry()
    compensated = []

    def persist_then_fail(pending):
        (pending.run_dir / "persisted-prefix.marker").write_text(
            "durable prefix",
            encoding="utf-8",
        )
        raise RuntimeError("tail failure after durable prefix")

    def compensate(pending, refs):
        compensated.append((pending.run_id, refs))

    with pytest.raises(PromoteCommitError, match="RuntimeError"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_hook=persist_then_fail,
            promotion_precommit_compensator=compensate,
        )

    assert len(compensated) == 1
    assert compensated[0][1] is None
    run_root = tmp_path / "runs"
    assert not any(
        path.name != ".staging" and (path / "run.json").is_file()
        for path in run_root.iterdir()
    )
    audited = list((run_root / ".staging").glob("*.receipt_failed.*"))
    assert len(audited) == 1
    assert (audited[0] / "persisted-prefix.marker").is_file()


def test_baseexception_before_receipt_commit_never_exposes_final_run(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry()

    class InjectedCrash(BaseException):
        pass

    def crash(_pending):
        raise InjectedCrash("simulated process boundary")

    with pytest.raises(InjectedCrash, match="simulated process boundary"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_hook=crash,
        )

    run_root = tmp_path / "runs"
    assert registry.calls == []
    assert not any(
        path.name != ".staging" and (path / "run.json").is_file()
        for path in run_root.iterdir()
    )
    audited = list((run_root / ".staging").glob("*.receipt_failed.*"))
    assert len(audited) == 1
    assert (audited[0] / "run.json").is_file()


def test_baseexception_after_exact_publish_keeps_current_public_run(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry()
    compensated = []
    publish = promote_module._publish_hidden_candidate

    class InjectedPublishCrash(BaseException):
        pass

    def publish_then_crash(**kwargs):
        publish(**kwargs)
        raise InjectedPublishCrash("process boundary after exact publish")

    monkeypatch.setattr(
        promote_module,
        "_publish_hidden_candidate",
        publish_then_crash,
    )

    with pytest.raises(InjectedPublishCrash, match="after exact publish"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_compensator=(
                lambda pending, refs: compensated.append((pending.run_id, refs))
            ),
        )

    run_root = tmp_path / "runs"
    visible = [
        path
        for path in run_root.iterdir()
        if path.name != ".staging" and (path / "run.json").is_file()
    ]
    assert len(visible) == 1
    assert registry.calls
    assert registry.events[-1] == "validate"
    assert compensated == []


def test_baseexception_after_red_publish_requarantines_and_compensates(
    tmp_path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "runs"
    registry = _ArtifactDetectingReceiptRegistry(run_root, "portfolio.csv")
    compensated = []
    publish = promote_module._publish_hidden_candidate

    class InjectedRedPublishCrash(BaseException):
        pass

    def publish_mutate_then_crash(**kwargs):
        publish(**kwargs)
        _mutate_same_size(run_root / kwargs["run_id"] / "portfolio.csv")
        raise InjectedRedPublishCrash("process boundary after red publish")

    monkeypatch.setattr(
        promote_module,
        "_publish_hidden_candidate",
        publish_mutate_then_crash,
    )

    with pytest.raises(InjectedRedPublishCrash, match="after red publish"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            run_root=run_root,
            promotion_precommit_compensator=(
                lambda pending, refs: compensated.append((pending.run_id, refs))
            ),
        )

    assert not any(
        path.name != ".staging" and (path / "run.json").is_file()
        for path in run_root.iterdir()
    )
    quarantined = list(
        (run_root / ".staging").glob("*.postcommit_validation_failed.*")
    )
    assert len(quarantined) == 1
    assert len(compensated) == 1


def test_baseexception_from_final_validator_requarantines_and_compensates(
    tmp_path,
    monkeypatch,
) -> None:
    compensated = []

    class InjectedValidationCrash(BaseException):
        pass

    class CrashingValidationRegistry(_ReceiptRegistry):
        def validate_current(self, _receipt_ref, **_identities):
            self.events.append("validate")
            raise InjectedValidationCrash("current validator boundary")

    registry = CrashingValidationRegistry()

    with pytest.raises(InjectedValidationCrash, match="validator boundary"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_compensator=(
                lambda pending, refs: compensated.append((pending.run_id, refs))
            ),
        )

    run_root = tmp_path / "runs"
    assert not any(
        path.name != ".staging" and (path / "run.json").is_file()
        for path in run_root.iterdir()
    )
    quarantined = list(
        (run_root / ".staging").glob("*.postcommit_validation_failed.*")
    )
    assert len(quarantined) == 1
    assert len(compensated) == 1
    assert registry.events.count("validate") == 2


def test_receipt_commit_then_publish_failure_keeps_candidate_hidden_and_red(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry()
    compensated = []

    def fail_publish(**_kwargs):
        raise OSError("injected final publish failure")

    monkeypatch.setattr(
        promote_module,
        "_publish_hidden_candidate",
        fail_publish,
    )

    with pytest.raises(PromoteCommitError, match="OSError"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_compensator=(
                lambda pending, refs: compensated.append((pending.run_id, refs))
            ),
        )

    assert registry.calls
    assert len(compensated) == 1
    run_root = tmp_path / "runs"
    assert not any(
        path.name != ".staging" and (path / "run.json").is_file()
        for path in run_root.iterdir()
    )
    audited = list((run_root / ".staging").glob("*.receipt_failed.*"))
    assert len(audited) == 1
    assert (audited[0] / "run.json").is_file()


def test_publish_helper_failure_after_rename_requarantines_exact_candidate(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry()
    compensated = []
    publish = promote_module._publish_hidden_candidate

    def publish_then_fail(**kwargs):
        publish(**kwargs)
        raise OSError("injected failure after final rename")

    monkeypatch.setattr(
        promote_module,
        "_publish_hidden_candidate",
        publish_then_fail,
    )

    with pytest.raises(PromoteCommitError, match="OSError"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_compensator=(
                lambda pending, refs: compensated.append((pending.run_id, refs))
            ),
        )

    assert registry.calls
    assert len(compensated) == 1
    run_root = tmp_path / "runs"
    assert not any(
        path.name != ".staging" and (path / "run.json").is_file()
        for path in run_root.iterdir()
    )
    quarantined = list(
        (run_root / ".staging").glob("*.postcommit_validation_failed.*")
    )
    assert len(quarantined) == 1
    assert (quarantined[0] / "run.json").is_file()


def test_failed_final_current_validation_requarantines_and_compensates(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry(fail_validate=True)
    compensated = []

    with pytest.raises(PromoteCommitError, match="ValueError"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_compensator=(
                lambda pending, refs: compensated.append((pending.run_id, refs))
            ),
        )

    assert registry.calls
    assert len(compensated) == 1
    run_root = tmp_path / "runs"
    assert not any(
        path.name != ".staging" and (path / "run.json").is_file()
        for path in run_root.iterdir()
    )
    quarantined = list(
        (run_root / ".staging").glob("*.postcommit_validation_failed.*")
    )
    assert len(quarantined) == 1
    assert (quarantined[0] / "run.json").is_file()


@pytest.mark.parametrize(
    "artifact_name",
    ("portfolio.csv", "trades.csv", "attribution.csv", "strategy.py"),
)
def test_postreceipt_artifact_mutation_requarantines_exact_run(
    tmp_path,
    monkeypatch,
    artifact_name,
) -> None:
    run_root = tmp_path / "runs"
    registry = _ArtifactDetectingReceiptRegistry(run_root, artifact_name)
    compensated = []
    publish = promote_module._publish_hidden_candidate

    def publish_then_mutate(**kwargs):
        publish(**kwargs)
        _mutate_same_size(run_root / kwargs["run_id"] / artifact_name)

    monkeypatch.setattr(
        promote_module,
        "_publish_hidden_candidate",
        publish_then_mutate,
    )

    with pytest.raises(PromoteCommitError, match="ValueError"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            run_root=run_root,
            promotion_precommit_compensator=(
                lambda pending, refs: compensated.append((pending.run_id, refs))
            ),
        )

    assert registry.calls
    assert len(compensated) == 1
    assert not any(
        path.name != ".staging" and (path / "run.json").is_file()
        for path in run_root.iterdir()
    )
    quarantined = list(
        (run_root / ".staging").glob("*.postcommit_validation_failed.*")
    )
    assert len(quarantined) == 1
    assert (quarantined[0] / artifact_name).is_file()


def test_receipt_failure_after_precommit_compensates_lineage_and_quarantines(
    tmp_path,
    monkeypatch,
) -> None:
    registry = _ReceiptRegistry(fail=True)
    compensated = []

    def precommit(_pending):
        return _precommit_refs()

    def compensate(pending, refs):
        compensated.append((pending.run_id, refs))

    with pytest.raises(PromoteCommitError, match="OSError"):
        _promote(
            tmp_path,
            monkeypatch,
            registry,
            promotion_precommit_hook=precommit,
            promotion_precommit_compensator=compensate,
        )

    assert len(compensated) == 1
    assert compensated[0][1] == _precommit_refs()
    run_root = tmp_path / "runs"
    assert not any(
        path.is_dir() and (path / "run.json").exists()
        for path in run_root.iterdir()
        if path.name != ".staging"
    )
