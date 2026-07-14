from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from conftest import (
    build_verified_spine_chain,
    install_training_market_data_use_validation,
)
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.lineage.ids import content_hash
from app.lineage.spine_ledger import SpineLedger
from app.ide.service import IDEService
from app.research_os import (
    ConsistencyStatus,
    MathematicalSpineChainRecord,
    PersistentMathematicalSpineChainRegistry,
    PersistentRDPStore,
    RuntimeStatus,
)
from app.research_os.asset_rag import PersistentResearchAssetRAGIndex
from app.research_os.compiler import PersistentCompilerIRStore
from app.research_os.entrypoint_evidence import (
    PersistentEntrypointEvidenceRegistry,
)
from app.research_os.goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.platform_business_attestations import (
    PlatformBusinessAttestationContext,
    PlatformBusinessAttestationService,
)
from app.research_os.platform_row_sources import (
    PersistentPlatformRowSourceRegistry,
)
from app.research_os.platform_source_adapters_m16_m21 import (
    PlatformSourceAdaptersM16M21Context,
    build_platform_source_adapters_m16_m21,
)
from app.research_os.platform_source_lineage_core import (
    PlatformSourceLineageFinalizer,
)
from app.research_os.platform_source_lineage_policies_m16_m21 import (
    PlatformSourceLineagePoliciesM16M21Context,
    build_platform_source_lineage_policy_resolver_m16_m21,
)
from app.research_os.platform_typed_sources import RealPlatformTypedSourceResolver
from app.research_os.ref_resolution import build_real_ref_resolver
from app.research_os.spine import PersistentResearchGraphStore
from tests.test_research_os_rdp_source_bundle import _manifest as rdp_manifest


OWNER = "pytest"


@dataclass(frozen=True)
class _OwnedLifecycle:
    owner_user_id: str
    value: object


class _UnusedM18Dependency:
    def __getattr__(self, name: str):
        def unavailable(*_args, **_kwargs):
            raise AssertionError(f"unused M18 dependency called: {name}")

        return unavailable


def _m18_chain_candidate(canonical_command_ref: str) -> MathematicalSpineChainRecord:
    return MathematicalSpineChainRecord(
        chain_ref="math_spine_chain:m18_http_candidate",
        data_semantics_ref="dataset_semantics:m18_http",
        factor_ref="factor:m18_http",
        model_ref="model:m18_http",
        forecast_ref="forecast:m18_http",
        signal_contract_ref="signal_contract:m18_http",
        strategy_book_ref="strategy_book:m18_http",
        portfolio_policy_ref="portfolio_policy:m18_http",
        risk_policy_ref="risk_policy:m18_http",
        execution_policy_ref="execution_policy:m18_http",
        backtest_run_ref=canonical_command_ref,
        attribution_ref="attribution:m18_http",
        monitor_ref="monitor:m18_http",
        theory_binding_refs=("replaced-by-canonical-spine-helper",),
        consistency_check_refs=("replaced-by-canonical-spine-helper",),
        methodology_choice_ref="replaced-by-canonical-spine-helper",
        responsibility_boundary_ref="replaced-by-canonical-spine-helper",
        evidence_refs=("evidence:m18_http_chain",),
        validation_refs=("pytest:m18_http_chain",),
        consistency_verdict=ConsistencyStatus.ACCEPTED,
        target_runtime=RuntimeStatus.OFFLINE,
        recorded_by=OWNER,
    )


def _proof_resolver(
    *,
    graph,
    compiler,
    receipts,
    evidence,
    rdp_store,
    rag,
    spine_chain_registry,
):
    def load_lifecycle(ref: str, owner: str):
        matches = []
        if compiler is not None:
            try:
                matches.append(compiler.artifact(ref, owner=owner))
            except (KeyError, LookupError):
                pass
        if spine_chain_registry is not None:
            try:
                matches.append(
                    spine_chain_registry.verified_chain(ref, owner=owner)
                )
            except (KeyError, LookupError):
                pass
        if rdp_store is not None:
            try:
                manifest = rdp_store.manifest(ref, owner_user_id=owner)
            except (KeyError, LookupError):
                pass
            else:
                matches.append(_OwnedLifecycle(owner_user_id=owner, value=manifest))
        if len(matches) != 1:
            raise LookupError("lifecycle ref is missing or ambiguous")
        return matches[0]

    return build_real_ref_resolver(
        research_graph_store=graph,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=rag,
        spine_chain_registry=spine_chain_registry,
        compiler_store=compiler,
        rdp_store=rdp_store,
        goal_validation_receipt_registry=receipts,
        platform_source_evidence_registry=evidence,
        lifecycle_loaders=(load_lifecycle,),
    )


def _m18_policy_context(runtime) -> PlatformSourceLineagePoliciesM16M21Context:
    unused = _UnusedM18Dependency()
    return PlatformSourceLineagePoliciesM16M21Context(
        research_graph_store=runtime.graph,
        compiler_store=runtime.compiler,
        entrypoint_registry=runtime.coverage,
        spine_chain_registry=runtime.spine,
        asset_lifecycle_registry=unused,
        sharing_service=unused,
        copy_trade_service=unused,
        runtime_promotion_registry=unused,
        follower_risk_state_store=unused,
        execution_order_submission_registry=unused,
        execution_order_intent_registry=unused,
        canonical_spine_ledger=runtime.ledger,
        rdp_store=runtime.rdp_store,
        teaching_asset_registry=unused,
        onboarding_registry=unused,
        llm_call_record_store=unused,
        account_halt_barrier=unused,
        llm_service_owner_user_id=OWNER,
    )


def _build_production_m18_runtime(
    *,
    graph,
    compiler,
    receipts,
    evidence,
    coverage,
    rdp_store,
    rag,
    spine,
    ledger,
):
    runtime = SimpleNamespace(
        graph=graph,
        compiler=compiler,
        coverage=coverage,
        receipts=receipts,
        evidence=evidence,
        rdp_store=rdp_store,
        rag=rag,
        spine=spine,
        ledger=ledger,
    )

    def validate_current(result):
        return build_platform_source_lineage_policy_resolver_m16_m21(
            _m18_policy_context(runtime)
        ).resolve(
            owner_user_id=result.owner_user_id,
            m_row=result.row,
            anchor_ref=result.anchor_ref,
        )

    context = PlatformBusinessAttestationContext(
        research_graph_store=graph,
        compiler_store=compiler,
        entrypoint_registry=coverage,
        spine_chain_registry=spine,
        compile_attestation=main._compile_platform_business_attestation,
        validate_current_attestation=validate_current,
        entrypoint_view_factory=None,
        compiler_view_factory=None,
        validation_receipt_registry=receipts,
        canonical_spine_ledger=ledger,
        rdp_store=rdp_store,
    )
    runtime.context = context
    runtime.service = PlatformBusinessAttestationService(context)
    return runtime


def _fresh_m18_row_resolver(
    *,
    paths,
    spine_resolvers,
):
    graph = PersistentResearchGraphStore(paths.graph)
    proof_ledger = GoalProofLedger(paths.proof_ledger)
    compiler = PersistentCompilerIRStore(
        paths.compiler,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    receipts = PersistentGoalValidationReceiptRegistry(
        paths.receipts,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        paths.evidence,
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=receipts,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    rdp_store = PersistentRDPStore(paths.rdp)
    rag = PersistentResearchAssetRAGIndex(paths.rag)
    ledger = SpineLedger(paths.spine_root)
    spine = PersistentMathematicalSpineChainRegistry(
        paths.spine_projection,
        ledger,
        external_ref_resolver=spine_resolvers.external,
        current_hash_resolver=spine_resolvers.current_hash,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        paths.coverage,
        resolver=_proof_resolver(
            graph=graph,
            compiler=compiler,
            receipts=receipts,
            evidence=evidence,
            rdp_store=rdp_store,
            rag=rag,
            spine_chain_registry=spine,
        ),
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    adapters, row_validators = build_platform_source_adapters_m16_m21(
        PlatformSourceAdaptersM16M21Context(
            research_graph_store=graph,
            canonical_spine_ledger=ledger,
            rdp_store=rdp_store,
            rag_index=rag,
            spine_chain_registry=spine,
        )
    )
    typed = RealPlatformTypedSourceResolver(
        research_graph_store=graph,
        lifecycle_loaders=(
            lambda ref, owner, _record: rdp_store.manifest(
                ref,
                owner_user_id=owner,
            ),
        ),
        goal_validation_receipt_registry=receipts,
        rag_index=rag,
        spine_chain_registry=spine,
        compiler_store=compiler,
        specific_adapters=adapters,
        row_validators=row_validators,
    )
    return PersistentPlatformRowSourceRegistry(
        paths.rows,
        entrypoint_registry=coverage,
        rag_index=rag,
        source_resolver=typed,
    )


def test_formal_ide_http_rdp_replays_into_m18_policy_and_exposes_row_seam(
    tmp_path,
    monkeypatch,
) -> None:
    market_ref = install_training_market_data_use_validation(
        monkeypatch,
        tmp_path / "market_data",
        dataset_id="m18_http",
    )
    ide_service = IDEService(
        tmp_path / "ide.db",
        run_root=tmp_path / "ide_runs",
    )
    graph_path = tmp_path / "research_graph.jsonl"
    compiler_path = tmp_path / "compiler.jsonl"
    receipt_path = tmp_path / "goal_validation_receipts.jsonl"
    evidence_path = tmp_path / "entrypoint_evidence.jsonl"
    coverage_path = tmp_path / "goal_entrypoint_coverage.jsonl"
    rdp_path = tmp_path / "rdp_manifests.jsonl"
    rag_path = tmp_path / "research_asset_rag.jsonl"
    rows_path = tmp_path / "platform_row_sources.jsonl"
    spine_root = tmp_path / "spine"
    proof_ledger_path = tmp_path / "goal_proof_ledger"

    graph = PersistentResearchGraphStore(graph_path)
    proof_ledger = GoalProofLedger(proof_ledger_path)
    compiler = PersistentCompilerIRStore(
        compiler_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    receipts = PersistentGoalValidationReceiptRegistry(
        receipt_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        evidence_path,
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=receipts,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    rdp_store = PersistentRDPStore(rdp_path)
    rag = PersistentResearchAssetRAGIndex(rag_path)
    coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=_proof_resolver(
            graph=graph,
            compiler=compiler,
            receipts=receipts,
            evidence=evidence,
            rdp_store=rdp_store,
            rag=rag,
            spine_chain_registry=None,
        ),
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )

    for name, value in (
        ("IDE_SERVICE", ide_service),
        ("RESEARCH_GRAPH_STORE", graph),
        ("COMPILER_IR_STORE", compiler),
        ("GOAL_VALIDATION_RECEIPT_REGISTRY", receipts),
        ("ENTRYPOINT_EVIDENCE_REGISTRY", evidence),
        ("GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage),
        ("RDP_STORE", rdp_store),
            ("RESEARCH_ASSET_RAG_INDEX", rag),
            ("GOAL_PROOF_LEDGER", proof_ledger),
        ):
        monkeypatch.setattr(main, name, value)

    frozen_source = (
        "quantbt.emit_result({'equity_curve': ["
        "{'t': '2026-01-01', 'equity': 1.0},"
        "{'t': '2026-01-02', 'equity': 1.1}]})"
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username=OWNER,
        user_id=OWNER,
    )

    try:
        with TestClient(main.app) as client:
            saved = client.post(
                "/api/ide/strategies",
                json={
                    "name": "m18_real_journey",
                    "code": frozen_source,
                    "asset_class": "equity_cn",
                    "market_data_use_validation_refs": [market_ref],
                },
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["research_graph_command_id"]
            assert saved.json()["compiler_ir_ref"]
            assert saved.json()["compiler_pass_ref"]
            assert saved.json()["entrypoint_coverage_ref"]

            ran = client.post(
                "/api/ide/strategies/m18_real_journey/run",
                json={"market_data_use_validation_refs": [market_ref]},
            )
            assert ran.status_code == 200, ran.text
            run_payload = ran.json()
            assert run_payload["status"] == "ok"
            run_id = run_payload["run_id"]
            source_qro_ref = run_payload["qro_id"]
            source_command_ref = run_payload["research_graph_command_id"]

            replay_graph = PersistentResearchGraphStore(graph_path)
            source_qro = replay_graph.qro(source_qro_ref)
            source_commands = tuple(
                command
                for command in replay_graph.commands()
                if command.command_id == source_command_ref
            )
            assert len(source_commands) == 1
            source_command = source_commands[0]
            assert getattr(source_qro.qro_type, "value", source_qro.qro_type) == "BacktestRun"
            assert source_command.payload["qro"] == source_qro
            assert source_qro.input_contract["code_hash"] == content_hash(
                frozen_source
            )
            code_hash = source_qro.input_contract["code_hash"]
            assert compiler.ir(run_payload["compiler_ir_ref"], owner=OWNER)
            assert compiler.compiler_pass(
                run_payload["compiler_pass_ref"], owner=OWNER
            )
            assert coverage.coverage(
                run_payload["entrypoint_coverage_ref"], owner=OWNER
            )

            spine, chain, ledger = build_verified_spine_chain(
                spine_root,
                _m18_chain_candidate(source_command_ref),
            )
            closure = spine.verified_chain_record_refs(
                chain.chain_ref,
                owner=OWNER,
            )
            selected_checks = []
            for check_ref in closure.consistency_check_refs:
                check = ledger.check(check_ref, owner=OWNER)
                binding = ledger.binding(check.binding_id, owner=OWNER)
                if source_command_ref in binding.used_by:
                    selected_checks.append((check, binding))
            assert len(selected_checks) == 1
            selected_check, selected_binding = selected_checks[0]

            monkeypatch.setattr(main, "MATHEMATICAL_SPINE_CHAIN_REGISTRY", spine)
            monkeypatch.setattr(main, "CANONICAL_SPINE_LEDGER", ledger)
            coverage.set_ref_resolver(
                _proof_resolver(
                    graph=graph,
                    compiler=compiler,
                    receipts=receipts,
                    evidence=evidence,
                    rdp_store=rdp_store,
                    rag=rag,
                    spine_chain_registry=spine,
                )
            )

            compiled = client.post(
                "/api/research-os/compiler/compile_qro",
                json={
                    "qro_id": source_qro_ref,
                    "graph_command_refs": [source_command_ref],
                },
            )
            assert compiled.status_code == 200, compiled.text
            compiled_refs = compiled.json()
            prerequisite_ir = compiler.ir(compiled_refs["ir_ref"], owner=OWNER)
            prerequisite_pass = compiler.compiler_pass(
                compiled_refs["pass_ref"],
                owner=OWNER,
            )
            assert prerequisite_ir.mathematical_spine_chain_refs == (
                chain.chain_ref,
            )
            artifact_response = client.post(
                "/api/research-os/compiler/artifacts",
                json={
                    "source_ir_refs": [prerequisite_ir.ir_ref],
                    "compiler_pass_refs": [prerequisite_pass.pass_ref],
                },
            )
            assert artifact_response.status_code == 200, artifact_response.text
            artifact_body = artifact_response.json()
            artifact = compiler.canonical_artifact(
                artifact_body["artifact_ref"],
                owner=OWNER,
            )
            assert artifact.artifact_kind == "deterministic_run_plan_manifest"
            assert artifact.source_ir_refs == (prerequisite_ir.ir_ref,)
            assert artifact.compiler_pass_refs == (prerequisite_pass.pass_ref,)
            assert artifact.mathematical_spine_chain_refs == (chain.chain_ref,)
            prerequisite_coverage = coverage.coverage(
                artifact_body["entrypoint_coverage_ref"],
                owner=OWNER,
            )
            prerequisite_decision = coverage.validate_real_backing(
                prerequisite_coverage
            )
            assert prerequisite_decision.accepted, prerequisite_decision.violations

            market_validation = main.MARKET_DATA_REGISTRY.use_validation(
                market_ref,
                owner_user_id=OWNER,
            )
            raw = rdp_manifest().to_open_dict()
            raw.pop("package_id", None)
            raw.pop("rdp_id", None)
            raw.update(
                {
                    "graph_refs": [source_command_ref],
                    "data_refs": list(market_validation.dataset_refs),
                    "market_data_use_validation_refs": [market_ref],
                    "mathematical_refs": list(closure.mathematical_refs),
                    "theory_binding_refs": list(closure.theory_binding_refs),
                    "consistency_check_refs": list(
                        closure.consistency_check_refs
                    ),
                    "methodology_choice_refs": list(
                        closure.methodology_choice_refs
                    ),
                    "responsibility_refs": list(closure.responsibility_refs),
                    "asset_refs": [],
                    "code_refs": [code_hash],
                    "artifact_hash": "",
                    "reproducibility_command": "",
                    "test_refs": ["pytest:m18-real-http-journey"],
                    "run_refs": [],
                    "unverified_residuals": [],
                    "residual_attestation": (
                        "review:all-known-residuals-resolved:m18-real-http-journey:v1"
                    ),
                    "compiler_artifact_refs": [artifact.artifact_ref],
                    "mathematical_spine_chain_refs": [chain.chain_ref],
                    "goal_entrypoint_coverage_refs": [
                        prerequisite_coverage.coverage_ref
                    ],
                    "source_file_refs": [],
                }
            )

            created = client.post(
                "/api/research-os/rdp/manifests",
                json={"ide_run_id": run_id, "manifest": raw},
            )
            assert created.status_code == 200, created.text
            package_id = created.json()["package_id"]

            replay_store = PersistentRDPStore(rdp_path)
            replayed = replay_store.manifest(
                package_id,
                owner_user_id=OWNER,
            )
            ide_ref = f"ide_run:{run_id}"
            assert replayed.asset_refs == (ide_ref,)
            assert replayed.run_refs == (ide_ref,)
            assert replayed.source_file_refs == ("source_file:strategy.py",)
            assert replayed.graph_refs == (source_command_ref,)
            assert replayed.code_refs == (code_hash,)
            assert replayed.mathematical_spine_chain_refs == (chain.chain_ref,)
            assert replayed.unverified_residuals == ()
            assert replayed.residual_attestation == (
                "review:all-known-residuals-resolved:m18-real-http-journey:v1"
            )

            runtime = _build_production_m18_runtime(
                graph=graph,
                compiler=compiler,
                receipts=receipts,
                evidence=evidence,
                coverage=coverage,
                rdp_store=replay_store,
                rag=rag,
                spine=spine,
                ledger=ledger,
            )
            monkeypatch.setattr(
                main,
                "PLATFORM_BUSINESS_ATTESTATION_SERVICE",
                runtime.service,
            )
            rdp_bytes_before_attestation = rdp_path.read_bytes()
            attested = client.post(
                "/api/research-os/platform/business_attestations/M18/current",
                json={"anchor_ref": selected_check.check_id},
            )
            assert attested.status_code == 200, attested.text
            assert rdp_path.read_bytes() == rdp_bytes_before_attestation

            policy = build_platform_source_lineage_policy_resolver_m16_m21(
                _m18_policy_context(runtime)
            )
            resolution = policy.resolve(
                owner_user_id=OWNER,
                m_row="M18",
                anchor_ref=selected_check.check_id,
            )
            assert resolution.lifecycle_ref == package_id
            assert dict(resolution.row_policy_metadata)["rdp_package_ref"] == package_id

            business_coverage = runtime.coverage.coverage(
                attested.json()["entrypoint_coverage_ref"],
                owner=OWNER,
            )
            business_qro = runtime.graph.qro(attested.json()["qro_ref"])
            business_command = next(
                command
                for command in runtime.graph.commands()
                if command.command_id == attested.json()["graph_command_ref"]
            )
            compiler_ir = runtime.compiler.ir(
                attested.json()["compiler_ir_ref"],
                owner=OWNER,
            )
            compiler_pass = runtime.compiler.compiler_pass(
                attested.json()["compiler_pass_ref"],
                owner=OWNER,
            )
            expected_semantic_evidence = (
                source_command_ref,
                selected_check.check_id,
                package_id,
                selected_binding.binding_id,
                source_qro_ref,
                code_hash,
                chain.chain_ref,
                "pytest:m18-real-http-journey",
            )
            assert business_qro.evidence_refs == expected_semantic_evidence
            assert business_command.evidence_refs == expected_semantic_evidence
            assert len(compiler_ir.evidence_refs) == 1
            assert compiler_ir.evidence_refs[0].startswith("entrypoint_evidence:")
            assert compiler_pass.evidence_refs == compiler_ir.evidence_refs
            assert business_coverage.evidence_refs == compiler_ir.evidence_refs
            receipt_refs = tuple(
                ref
                for ref in compiler_ir.validation_refs
                if ref.startswith("goal_validation_receipt:")
            )
            assert len(receipt_refs) == 1
            assert compiler_ir.validation_refs == (receipt_refs[0],)
            assert compiler_pass.validation_refs == compiler_ir.validation_refs
            assert business_coverage.validation_refs == compiler_ir.validation_refs
            receipt = runtime.receipts.receipt(
                receipt_refs[0],
                owner_user_id=OWNER,
            )
            assert receipt.subject_qro_refs == (business_qro.qro_id,)
            assert receipt.graph_command_refs == (business_command.command_id,)
            business_evidence = runtime.evidence.evidence(
                compiler_ir.evidence_refs[0],
                owner_user_id=OWNER,
            )
            assert runtime.evidence.validate_current(
                business_evidence,
                owner_user_id=OWNER,
            ).accepted
            assert business_evidence.qro_ref == business_qro.qro_id
            assert business_evidence.research_graph_ref == business_command.command_id
            assert business_evidence.validation_ref == receipt.validation_ref

            adapters, row_validators = build_platform_source_adapters_m16_m21(
                PlatformSourceAdaptersM16M21Context(
                    research_graph_store=runtime.graph,
                    canonical_spine_ledger=runtime.ledger,
                    rdp_store=replay_store,
                    rag_index=rag,
                    spine_chain_registry=runtime.spine,
                )
            )
            typed = RealPlatformTypedSourceResolver(
                research_graph_store=runtime.graph,
                lifecycle_loaders=(
                    lambda ref, owner, _record: replay_store.manifest(
                        ref,
                        owner_user_id=owner,
                    ),
                ),
                goal_validation_receipt_registry=runtime.receipts,
                rag_index=rag,
                spine_chain_registry=runtime.spine,
                compiler_store=runtime.compiler,
                specific_adapters=adapters,
                row_validators=row_validators,
            )
            rows = PersistentPlatformRowSourceRegistry(
                rows_path,
                entrypoint_registry=runtime.coverage,
                rag_index=rag,
                source_resolver=typed,
            )
            finalizer = PlatformSourceLineageFinalizer(
                policy_resolver=policy,
                entrypoint_registry=runtime.coverage,
                rag_index=rag,
                row_source_registry=rows,
                source_resolver=typed,
                record_coverage=lambda record: (
                    main._record_canonical_goal_entrypoint_coverage(
                        record,
                        registry=runtime.coverage,
                    )
                ),
            )
            monkeypatch.setattr(
                main,
                "PLATFORM_SOURCE_LINEAGE_FINALIZER",
                finalizer,
            )
            monkeypatch.setattr(
                main,
                "PLATFORM_ROW_SOURCE_REGISTRY",
                rows,
            )
            finalized_response = client.post(
                "/api/research-os/platform/source_lineage/M18/current",
                json={"anchor_ref": selected_check.check_id},
            )
            assert finalized_response.status_code == 200, finalized_response.text
            finalized = finalized_response.json()
            assert (
                finalized["business_coverage_ref"]
                == business_coverage.coverage_ref
            )
            source_coverage = runtime.coverage.coverage(
                finalized["source_coverage_ref"],
                owner=OWNER,
            )
            assert source_coverage.goal_sections == ("§14",)
            resolved_row = rows.resolve_current_row(
                "M18",
                owner_user_id=OWNER,
            )
            assert rdp_path.read_bytes() == rdp_bytes_before_attestation

            fresh_rows = _fresh_m18_row_resolver(
                paths=SimpleNamespace(
                    graph=graph_path,
                    compiler=compiler_path,
                    receipts=receipt_path,
                    evidence=evidence_path,
                    coverage=coverage_path,
                    rdp=rdp_path,
                    rag=rag_path,
                    rows=rows_path,
                    proof_ledger=proof_ledger_path,
                    spine_root=spine_root / "canonical_spine",
                    spine_projection=spine_root
                    / "mathematical_spine_chains.jsonl",
                ),
                spine_resolvers=SimpleNamespace(
                    external=spine._external_ref_resolver,
                    current_hash=spine._current_hash_resolver,
                ),
            )
            assert fresh_rows.resolve_current_row(
                "M18",
                owner_user_id=OWNER,
            ) == resolved_row
            assert rdp_path.read_bytes() == rdp_bytes_before_attestation
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
