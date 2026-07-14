from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
from dataclasses import replace

import pytest

from app.delivery.rdp import PromotionClaim
from app.delivery.rdp_gate import (
    GATE_REPRODUCTION_RECEIPT,
    gate_reproduction_receipt,
)
from app.ide.promote import PromoteError, promote_ide_run
from app.ide.service import IDEService
from app.lineage.ids import content_hash
from app.release_gate.section17_rdp_gate import (
    RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY,
    SECTION17_RDP_MANIFEST_KEY,
    section17_rdp_check,
)
from app.research_os.rdp import (
    PersistentRDPSourceRunIntegrityStore,
    RDPOpenPackageMaterializer,
    RDPManifest,
    RDPSourceFileBundler,
    rdp_run_artifact_hash,
)
from app.research_os.rdp_replay import REPOSITORY_REPRODUCTION_RUNNER_REF
from app.research_os.rdp_reproduction import (
    IDEReproductionSourceResolver,
    PersistentRDPReproductionReceiptStore,
    RDPReproductionSourceEvidence,
    RDPReproductionReceiptRejected,
    RDPReproductionVerificationSnapshot,
    ResolvedRDPReproductionSource,
    rdp_manifest_hash,
    repository_reproduction_verification_loader,
)


OWNER = "user:alice"
RUNNER = "backend_runner:rdp_reproduction:v1"
NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def _manifest(**overrides) -> RDPManifest:
    fields = {
        "research_question": "Can the exact IDE result be reproduced?",
        "graph_refs": ("research_graph:ide-1",),
        "data_refs": ("dataset:prices",),
        "dataset_version_refs": ("dataset_version:prices:v1",),
        "market_data_use_validation_refs": ("market_data_use:prices:backtest",),
        "ingestion_skill_refs": ("ingestion_skill:prices:v1",),
        "mathematical_refs": ("math:strategy:v1",),
        "theory_binding_refs": ("theory_binding:strategy:v1",),
        "consistency_check_refs": ("consistency_check:strategy:v1",),
        "asset_refs": ("ide_run:ide-1",),
        "asset_kind": "strategybook",
        "code_refs": ("source:strategy.py",),
        "environment_lock_ref": "environment_lock:uv.lock:sha256:abc",
        # Deliberately not executable. It is documentation, never authority.
        "reproducibility_command": "this command does not exist --documentation-only",
        "artifact_hash": "sha256:artifact-exact",
        "test_refs": ("test:strategy:v1",),
        "run_refs": ("run:ide-1",),
        "honest_n_refs": ("honest_n:strategy:v1",),
        "cost_and_execution_assumptions": ("fee=10bps",),
        "attribution_refs": ("attribution:ide-1",),
        "known_limits": ("single fixture",),
        "unverified_residuals": ("live slippage unverified",),
        "verifier_verdict_ref": "verifier:ide-1",
        "compiler_artifact_refs": ("compiler_artifact:ide-1",),
        "mathematical_spine_chain_refs": ("math_spine_chain:ide-1",),
        "goal_entrypoint_coverage_refs": ("goal_coverage:ide-1",),
        "source_file_refs": ("source_file:strategy.py",),
    }
    fields.update(overrides)
    return RDPManifest(**fields)


def _loader(
    *,
    passed: bool = True,
    runner_ref: str = RUNNER,
    artifact_override: str | None = None,
    result_override: str | None = None,
    verified_at: dt.datetime = NOW,
    valid_until: dt.datetime = NOW + dt.timedelta(minutes=10),
    calls: list[tuple[str, str, str]] | None = None,
):
    def load(
        owner_user_id: str,
        manifest: RDPManifest,
        spec,
        resolved_source,
    ) -> RDPReproductionVerificationSnapshot:
        assert resolved_source.evidence == spec_source(
            owner_user_id,
            manifest,
            spec.source_result_content_hash,
        ).evidence
        if calls is not None:
            calls.append(
                (owner_user_id, manifest.package_id, spec.source_result_content_hash)
            )
        return RDPReproductionVerificationSnapshot(
            package_id=spec.package_id,
            manifest_hash=spec.manifest_hash,
            spec_hash=spec.spec_hash,
            expected_artifact_hash=spec.artifact_hash,
            observed_artifact_hash=artifact_override or spec.artifact_hash,
            expected_source_result_content_hash=spec.source_result_content_hash,
            observed_source_result_content_hash=(
                result_override or spec.source_result_content_hash
            ),
            expected_source_integrity_hash=spec.source_integrity_hash,
            observed_source_integrity_hash=spec.source_integrity_hash,
            expected_source_strategy_sha256=spec.source_strategy_sha256,
            observed_source_strategy_sha256=spec.source_strategy_sha256,
            expected_replay_result_sha256=spec.expected_replay_result_sha256,
            observed_replay_result_sha256=spec.expected_replay_result_sha256,
            expected_replay_artifact_hash=spec.expected_replay_artifact_hash,
            observed_replay_artifact_hash=spec.expected_replay_artifact_hash,
            environment_lock_ref=spec.environment_lock_ref,
            outcome="passed" if passed else "failed",
            passed=passed,
            runner_ref=runner_ref,
            evidence_refs=("evidence:reproduction-log:sha256:abc",),
            verified_at_utc=verified_at.isoformat(),
            valid_until_utc=valid_until.isoformat(),
            errors=() if passed else ("runner_failed",),
        )

    return load


def spec_source(
    _owner_user_id: str,
    manifest: RDPManifest,
    source_result_content_hash: str,
) -> ResolvedRDPReproductionSource:
    strategy_code = "pass\n"
    strategy_sha = "sha256:" + hashlib.sha256(strategy_code.encode()).hexdigest()
    evidence = RDPReproductionSourceEvidence(
        package_id=manifest.package_id,
        source_run_ref=manifest.run_refs[0],
        source_run_id=manifest.run_refs[0].split(":", 1)[-1],
        source_file_ref=manifest.source_file_refs[0],
        manifest_hash=rdp_manifest_hash(manifest),
        source_artifact_hash=manifest.artifact_hash,
        source_integrity_hash="sha16:" + "1" * 16,
        source_bundle_index_sha256="sha256:" + "2" * 64,
        source_run_manifest_sha256="sha256:" + "3" * 64,
        source_strategy_sha256=strategy_sha,
        source_result_sha256="sha256:" + "4" * 64,
        expected_replay_result_sha256="sha256:" + "5" * 64,
        source_portfolio_sha256="sha256:" + "6" * 64,
        source_result_content_hash=source_result_content_hash,
        expected_replay_artifact_hash="sha256:" + "7" * 64,
    )
    return ResolvedRDPReproductionSource(
        evidence=evidence,
        strategy_code=strategy_code,
    )


def _store(tmp_path, loader=None) -> PersistentRDPReproductionReceiptStore:
    return PersistentRDPReproductionReceiptStore(
        tmp_path / "rdp_reproduction_receipts.jsonl",
        loader or _loader(),
        source_resolver=spec_source,
        allowed_runner_refs=(RUNNER,),
    )


def test_store_issues_only_through_injected_verifier_and_never_runs_documentation_command(
    tmp_path,
    monkeypatch,
) -> None:
    manifest = _manifest()
    source_hash = content_hash({"result": "exact"})
    calls: list[tuple[str, str, str]] = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("free-form command execution is forbidden")

    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("os.system", forbidden)
    store = _store(tmp_path, _loader(calls=calls))

    receipt = store.record_current(
        owner_user_id=OWNER,
        manifest=manifest,
        source_result_content_hash=source_hash,
        now_utc=NOW,
    )

    assert receipt.passed is True
    assert receipt.artifact_hash == manifest.artifact_hash
    assert receipt.source_result_content_hash == source_hash
    assert calls == [(OWNER, manifest.package_id, source_hash)]
    assert "passed" not in inspect.signature(store.record_current).parameters


@pytest.mark.parametrize(
    ("loader", "expected"),
    [
        (_loader(passed=False), "reproduction_snapshot_not_passed"),
        (
            _loader(runner_ref="caller_supplied:runner"),
            "reproduction_snapshot_runner_not_allowlisted",
        ),
        (
            _loader(artifact_override="sha256:different"),
            "reproduction_snapshot_artifact_drift",
        ),
        (
            _loader(result_override="0" * 16),
            "reproduction_snapshot_result_drift",
        ),
        (
            _loader(valid_until=NOW + dt.timedelta(minutes=16)),
            "reproduction_snapshot_validity_exceeds_policy",
        ),
    ],
)
def test_store_rejects_untrusted_failed_or_drifted_snapshot(
    tmp_path,
    loader,
    expected,
) -> None:
    with pytest.raises(RDPReproductionReceiptRejected, match=expected):
        _store(tmp_path, loader).record_current(
            owner_user_id=OWNER,
            manifest=_manifest(),
            source_result_content_hash=content_hash({"result": "exact"}),
            now_utc=NOW,
        )


def test_receipt_reload_is_owner_scoped_content_bound_and_expires(tmp_path) -> None:
    manifest = _manifest()
    source_hash = content_hash({"result": "exact"})
    store = _store(tmp_path)
    expected = store.record_current(
        owner_user_id=OWNER,
        manifest=manifest,
        source_result_content_hash=source_hash,
        now_utc=NOW,
    )
    reloaded = _store(tmp_path)

    assert (
        reloaded.current_passed(
            owner_user_id=OWNER,
            manifest=manifest,
            source_result_content_hash=source_hash,
            now_utc=NOW + dt.timedelta(minutes=1),
        )
        == expected
    )
    with pytest.raises(
        RDPReproductionReceiptRejected,
        match="current_reproduction_receipt_not_found",
    ):
        reloaded.current_passed(
            owner_user_id="user:bob",
            manifest=manifest,
            source_result_content_hash=source_hash,
            now_utc=NOW + dt.timedelta(minutes=1),
        )
    with pytest.raises(RDPReproductionReceiptRejected):
        reloaded.current_passed(
            owner_user_id=OWNER,
            manifest=manifest,
            source_result_content_hash=content_hash({"result": "drifted"}),
            now_utc=NOW + dt.timedelta(minutes=1),
        )
    with pytest.raises(RDPReproductionReceiptRejected):
        reloaded.current_passed(
            owner_user_id=OWNER,
            manifest=manifest,
            source_result_content_hash=source_hash,
            now_utc=NOW + dt.timedelta(minutes=11),
        )


def test_current_passed_reresolves_and_rejects_drifted_source_evidence(tmp_path) -> None:
    manifest = _manifest()
    source_hash = content_hash({"result": "exact"})
    drifted = False

    def mutable_resolver(owner_user_id, candidate, candidate_source_hash):
        resolved = spec_source(owner_user_id, candidate, candidate_source_hash)
        if not drifted:
            return resolved
        return ResolvedRDPReproductionSource(
            evidence=replace(
                resolved.evidence,
                source_integrity_hash="sha16:" + "9" * 16,
                source_evidence_hash="",
            ),
            strategy_code=resolved.strategy_code,
        )

    store = PersistentRDPReproductionReceiptStore(
        tmp_path / "rdp_reproduction_receipts.jsonl",
        _loader(),
        source_resolver=mutable_resolver,
        allowed_runner_refs=(RUNNER,),
    )
    store.record_current(
        owner_user_id=OWNER,
        manifest=manifest,
        source_result_content_hash=source_hash,
        now_utc=NOW,
    )
    drifted = True

    with pytest.raises(
        RDPReproductionReceiptRejected,
        match="current_reproduction_receipt_not_found",
    ):
        store.current_passed(
            owner_user_id=OWNER,
            manifest=manifest,
            source_result_content_hash=source_hash,
            now_utc=NOW + dt.timedelta(minutes=1),
        )


def test_record_current_rejects_source_drift_during_verification(tmp_path) -> None:
    manifest = _manifest()
    source_hash = content_hash({"result": "exact"})
    drifted = False

    def mutable_resolver(owner_user_id, candidate, candidate_source_hash):
        resolved = spec_source(owner_user_id, candidate, candidate_source_hash)
        if not drifted:
            return resolved
        return ResolvedRDPReproductionSource(
            evidence=replace(
                resolved.evidence,
                source_integrity_hash="sha16:" + "8" * 16,
                source_evidence_hash="",
            ),
            strategy_code=resolved.strategy_code,
        )

    base_loader = _loader()

    def drifting_loader(owner_user_id, candidate, spec, resolved_source):
        nonlocal drifted
        snapshot = base_loader(owner_user_id, candidate, spec, resolved_source)
        drifted = True
        return snapshot

    path = tmp_path / "rdp_reproduction_receipts.jsonl"
    store = PersistentRDPReproductionReceiptStore(
        path,
        drifting_loader,
        source_resolver=mutable_resolver,
        allowed_runner_refs=(RUNNER,),
    )
    with pytest.raises(
        RDPReproductionReceiptRejected,
        match="reproduction_source_drifted_during_verification",
    ):
        store.record_current(
            owner_user_id=OWNER,
            manifest=manifest,
            source_result_content_hash=source_hash,
            now_utc=NOW,
        )
    assert not path.exists()


def test_persisted_receipt_tamper_fails_store_reload(tmp_path) -> None:
    manifest = _manifest()
    path = tmp_path / "rdp_reproduction_receipts.jsonl"
    store = _store(tmp_path)
    store.record_current(
        owner_user_id=OWNER,
        manifest=manifest,
        source_result_content_hash=content_hash({"result": "exact"}),
        now_utc=NOW,
    )
    row = json.loads(path.read_text(encoding="utf-8"))
    row["receipt"]["artifact_hash"] = "sha256:tampered"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid persisted RDP reproduction receipt"):
        _store(tmp_path)


def test_section17_formal_promotion_requires_exact_current_receipt(tmp_path) -> None:
    manifest = _manifest()
    source_hash = content_hash({"result": "exact"})
    store = _store(tmp_path)
    # 用测试内取鲜的 now:receipt 有效期=now+5min,而 staleness 对真实时钟评估。
    # 模块级 NOW 在收集期冻结,慢环境(CI 全量 17min)跑到本测试时窗口已过期
    # ——CI run5 实证的时间脆弱性,与门语义无关。
    fresh_now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    receipt = store.record_current(
        owner_user_id=OWNER,
        manifest=manifest,
        source_result_content_hash=source_hash,
        now_utc=fresh_now,
    )
    promotion = PromotionClaim(
        asset_ref=manifest.asset_ref,
        asset_kind=manifest.asset_kind,
        rdp_ref=manifest.package_id,
        requested_stage="formal_run",
        actor="alice",
    )
    run_manifest = {
        "run_id": "formal-1",
        "status": "completed",
        "source": {
            "owner_user_id": OWNER,
            "result_content_hash": source_hash,
        },
        SECTION17_RDP_MANIFEST_KEY: {
            "rdp": manifest.to_open_dict(),
            "promotion": promotion.to_dict(),
        },
    }

    missing = section17_rdp_check(run_manifest)
    assert missing.ok is False
    assert "rdp_reproduction_receipt" in missing.missing

    run_manifest[RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY] = receipt.to_open_dict()
    untrusted = section17_rdp_check(run_manifest)
    assert untrusted.ok is False
    assert "rdp_reproduction_receipt_authority" in untrusted.missing

    accepted = section17_rdp_check(
        run_manifest,
        reproduction_receipt_store=store,
    )
    assert accepted.ok is True, accepted.reason

    for mutation in (
        {**receipt.to_open_dict(), "production_verified": True},
        {
            key: value
            for key, value in receipt.to_open_dict().items()
            if key != "receipt_ref"
        },
        {
            key: value
            for key, value in receipt.to_open_dict().items()
            if key != "receipt_version"
        },
        {**receipt.to_open_dict(), "evidence_refs": receipt.evidence_refs[0]},
        {**receipt.to_open_dict(), "evidence_refs": [*receipt.evidence_refs, " "]},
        {**receipt.to_open_dict(), "runner_ref": f" {receipt.runner_ref} "},
    ):
        run_manifest[RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY] = mutation
        rejected_shape = section17_rdp_check(
            run_manifest,
            reproduction_receipt_store=store,
        )
        assert rejected_shape.ok is False
        assert "rdp_reproduction_receipt_unparseable" in rejected_shape.missing

    forged = replace(
        receipt,
        receipt_ref="",
        runner_ref="attacker:made-up-runner",
        verification_snapshot_hash="sha16:" + "9" * 16,
    )
    run_manifest[RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY] = forged.to_open_dict()
    rejected_forgery = section17_rdp_check(
        run_manifest,
        reproduction_receipt_store=store,
    )
    assert rejected_forgery.ok is False
    assert "rdp_reproduction_receipt_authority_mismatch" in rejected_forgery.missing

    direct = gate_reproduction_receipt(
        manifest,
        receipt,
        owner_user_id=OWNER,
        source_result_content_hash=source_hash,
        reproduction_receipt_store=store,
    )
    assert direct.gate_id == GATE_REPRODUCTION_RECEIPT
    assert direct.passed is True


def test_formal_ide_promotion_without_rdp_fails_before_filesystem_mutation(
    tmp_path,
) -> None:
    run_root = tmp_path / "runs"

    with pytest.raises(PromoteError, match="formal IDE promotion requires rdp_package_id"):
        promote_ide_run(
            ide_run_id="ide-1",
            owner_username="alice",
            owner_user_id=OWNER,
            strategy_name="strategy",
            strategy_code="pass",
            result={
                "equity_curve": [
                    {"t": "2026-01-01", "equity": 1.0},
                    {"t": "2026-01-02", "equity": 1.1},
                ]
            },
            run_root=run_root,
            require_reproduction_receipt=True,
        )

    assert not run_root.exists()


def test_formal_ide_promotion_with_rdp_but_without_trusted_store_fails_closed(
    tmp_path,
) -> None:
    manifest = _manifest()
    run_root = tmp_path / "runs"

    class RDPStore:
        def manifest(self, package_id, *, owner_user_id):
            assert package_id == manifest.package_id
            assert owner_user_id == OWNER
            return manifest

    with pytest.raises(
        PromoteError,
        match="formal IDE promotion requires the trusted RDP reproduction receipt store",
    ):
        promote_ide_run(
            ide_run_id="ide-1",
            owner_username="alice",
            owner_user_id=OWNER,
            strategy_name="strategy",
            strategy_code="pass",
            result={
                "equity_curve": [
                    {"t": "2026-01-01", "equity": 1.0},
                    {"t": "2026-01-02", "equity": 1.1},
                ]
            },
            run_root=run_root,
            rdp_package_id=manifest.package_id,
            rdp_store=RDPStore(),
        )

    assert not run_root.exists()


def test_real_ide_source_package_local_replay_residual_blocks_receipt_and_promotion(
    tmp_path,
) -> None:
    owner = "user:alice"
    strategy_code = (
        "quantbt.emit_result({"
        "'equity_curve': ["
        "{'t': '2026-01-01', 'equity': 1.0, 'net_return': 0.0},"
        "{'t': '2026-01-02', 'equity': 1.1, 'net_return': 0.1}],"
        "'metadata': {'market': 'crypto_perp', 'frequency': '1d'}"
        "})"
    )
    ide_service = IDEService(
        tmp_path / "ide.db",
        run_root=tmp_path / "ide_runs",
    )
    ide_service.save_strategy("alice", "frozen_replay", strategy_code)
    ide_run = ide_service.run_strategy(
        "alice",
        "frozen_replay",
        owner_user_id=owner,
    )
    assert ide_run.status == "ok"
    run_dir = ide_service.run_root / ide_run.run_id

    def file_sha(name: str) -> str:
        return "sha256:" + hashlib.sha256((run_dir / name).read_bytes()).hexdigest()

    artifact_hash = rdp_run_artifact_hash(
        run_manifest_sha256=file_sha("run.json"),
        run_strategy_sha256=file_sha("strategy.py"),
        run_portfolio_sha256=file_sha("portfolio.csv"),
    )
    ide_ref = f"ide_run:{ide_run.run_id}"
    manifest = _manifest(
        asset_refs=(ide_ref,),
        run_refs=(ide_ref,),
        source_file_refs=("source_file:strategy.py",),
        artifact_hash=artifact_hash,
    )
    package_root = tmp_path / "rdp_packages"
    materializer = RDPOpenPackageMaterializer(package_root)
    materializer.materialize(manifest, owner_user_id=owner)
    bundler = RDPSourceFileBundler(package_root, tmp_path / "unused_source_root")
    bundler.bundle_trusted_text_sources(
        manifest,
        owner_user_id=owner,
        source_texts={"source_file:strategy.py": strategy_code},
    )
    integrity_store = PersistentRDPSourceRunIntegrityStore(
        tmp_path / "source_integrity.jsonl"
    )
    integrity_store.record_integrity(
        manifest,
        owner_user_id=owner,
        package_root=package_root,
        run_root=ide_service.run_root,
        run_id=ide_run.run_id,
        attested_by="alice",
    )
    source_resolver = IDEReproductionSourceResolver(
        integrity_store=integrity_store,
        package_root=package_root,
        ide_run_root=ide_service.run_root,
    )
    receipt_path = tmp_path / "reproduction_receipts.jsonl"
    receipt_store = PersistentRDPReproductionReceiptStore(
        receipt_path,
        repository_reproduction_verification_loader,
        source_resolver=source_resolver,
        allowed_runner_refs=(REPOSITORY_REPRODUCTION_RUNNER_REF,),
    )
    result = ide_service.get_run_artifact(ide_run.run_id, "result")["body"]
    result_hash = content_hash(result)

    with pytest.raises(
        RDPReproductionReceiptRejected,
        match="reproduction_snapshot_has_residuals",
    ):
        receipt_store.record_current(
            owner_user_id=owner,
            manifest=manifest,
            source_result_content_hash=result_hash,
        )
    assert not receipt_path.exists()

    class ManifestStore:
        def manifest(self, package_id, *, owner_user_id):
            assert package_id == manifest.package_id
            assert owner_user_id == owner
            return manifest

    promoted_root = tmp_path / "promoted_runs"
    with pytest.raises(
        PromoteError,
        match="reproduction_snapshot_has_residuals",
    ):
        promote_ide_run(
            ide_run_id=ide_run.run_id,
            owner_username="alice",
            owner_user_id=owner,
            strategy_name="frozen_replay",
            strategy_code=strategy_code,
            result=result,
            run_root=promoted_root,
            rdp_package_id=manifest.package_id,
            rdp_store=ManifestStore(),
            reproduction_receipt_store=receipt_store,
            require_reproduction_receipt=True,
        )
    assert not promoted_root.exists()
    assert not receipt_path.exists()
