from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROBE_PREFIX = "QUANTBT_PRODUCTION_COMPOSITION_PROBE="


PROBE_SOURCE = r"""
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app import main


runtime_root = Path(os.environ["BACKTEST_DATA_ROOT"]).resolve()
with TestClient(main.app) as client:
    registration = client.post(
        "/api/auth/register",
        json={
            "username": "production-composition-owner",
            "password": "composition-passw0rd",
            "display_name": "Production Composition Owner",
        },
    )
    token = registration.json()["token"]
    owner_user_id = registration.json()["user"]["user_id"]
    headers = {"Authorization": f"Bearer {token}"}

    summary_paths = {
        "entrypoints": "/api/research-os/goal/entrypoint_coverage/summary",
        "semantic": "/api/research-os/goal/section_semantic_proofs/summary",
        "sections": "/api/research-os/goal/section_coverage/summary",
        "full_product": "/api/research-os/goal/full_product_entrypoints",
        "platform": "/api/research-os/platform/coverage_summary",
    }
    summary_responses = {
        name: client.get(path, headers=headers)
        for name, path in summary_paths.items()
    }
    full_product_write = client.post(
        "/api/research-os/goal/full_product_entrypoints/current",
        headers=headers,
        json={},
    )
    platform_write = client.post(
        "/api/research-os/platform/coverage_manifest",
        headers=headers,
        json={},
    )

full_product_producer = main.GOAL_FULL_PRODUCT_ENTRYPOINT_PRODUCER
platform_finalizer = main.PLATFORM_SOURCE_LINEAGE_FINALIZER
platform_source_registry = main.PLATFORM_ROW_SOURCE_REGISTRY

payload = {
    "runtime_root": str(runtime_root),
    "main_data_root": str(Path(main.DATA_ROOT).resolve()),
    "registration_status": registration.status_code,
    "composition_types": {
        name: f"{type(value).__module__}.{type(value).__name__}"
        for name, value in {
            "full_product_producer": full_product_producer,
            "full_product_attestations": main.GOAL_FULL_PRODUCT_ATTESTATION_REGISTRY,
            "entrypoint_coverage": main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY,
            "semantic_proofs": main.GOAL_SECTION_SEMANTIC_PROOF_REGISTRY,
            "section_coverage": main.GOAL_SECTION_COVERAGE_REGISTRY,
            "platform_finalizer": platform_finalizer,
            "platform_typed_resolver": main.PLATFORM_TYPED_SOURCE_RESOLVER,
            "platform_source_registry": platform_source_registry,
            "platform_producer_registry": main.PLATFORM_ROW_PRODUCER_REGISTRY,
            "platform_coverage_registry": main.PLATFORM_COVERAGE_REGISTRY,
            "platform_closure_registry": main.PLATFORM_CLOSURE_REGISTRY,
        }.items()
    },
    "composition_bindings": {
        "full_product_attestations": (
            full_product_producer._attestation_registry
            is main.GOAL_FULL_PRODUCT_ATTESTATION_REGISTRY
        ),
        "full_product_entrypoints": (
            full_product_producer._entrypoint_registry
            is main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY
        ),
        "full_product_compiler": (
            full_product_producer._compiler_store is main.COMPILER_IR_STORE
        ),
        "full_product_validation": (
            full_product_producer._validation_receipt_registry
            is main.GOAL_VALIDATION_RECEIPT_REGISTRY
        ),
        "full_product_terminal_aggregate": (
            full_product_producer._terminal_aggregate_registry
            is main.GOAL_ENTRYPOINT_AGGREGATE_REGISTRY
        ),
        "full_product_closure_resolver": (
            full_product_producer._attestation_registry._closure_resolver
            is main._resolve_goal_full_product_closure
        ),
        "platform_source_entrypoints": (
            platform_source_registry._entrypoints
            is main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY
        ),
        "platform_source_rag": (
            platform_source_registry._rag is main.RESEARCH_ASSET_RAG_INDEX
        ),
        "platform_source_typed_resolver": (
            platform_source_registry._resolver
            is main.PLATFORM_TYPED_SOURCE_RESOLVER
        ),
        "platform_finalizer_sources": (
            platform_finalizer._rows is platform_source_registry
        ),
        "platform_finalizer_typed_resolver": (
            platform_finalizer._resolver is main.PLATFORM_TYPED_SOURCE_RESOLVER
        ),
        "platform_manifest_producer_resolver": (
            main.PLATFORM_COVERAGE_REGISTRY._resolver
            is main.PLATFORM_PRODUCER_BOUND_REF_RESOLVER
        ),
        "platform_manifest_current_producers": (
            main.PLATFORM_PRODUCER_BOUND_REF_RESOLVER._producers
            is main.PLATFORM_ROW_PRODUCER_REGISTRY
        ),
        "platform_closure_locked_manifest_source": (
            getattr(
                main.PLATFORM_CLOSURE_REGISTRY._resolve_current_manifest_unlocked,
                "__self__",
                None,
            )
            is platform_source_registry
            and getattr(
                main.PLATFORM_CLOSURE_REGISTRY._resolve_current_manifest_unlocked,
                "__func__",
                None,
            )
            is type(platform_source_registry).resolve_current_rows_from_journal_unlocked
        ),
    },
    "required_entry_sources": list(main.REQUIRED_ENTRY_SOURCES),
    "required_goal_sections": list(main.REQUIRED_GOAL_SECTIONS),
    "registered_semantic_sections": list(
        main.GOAL_SECTION_SEMANTIC_PROOF_REGISTRY.registered_sections
    ),
    "semantic_adapter_types": {
        section: f"{type(adapter).__module__}.{type(adapter).__name__}"
        for section, adapter in (
            main.GOAL_SECTION_SEMANTIC_PROOF_REGISTRY._adapters.items()
        )
    },
    "required_platform_rows": list(main.REQUIRED_PLATFORM_ROWS),
    "registered_platform_rows": list(
        main.PLATFORM_ROW_PRODUCER_REGISTRY.registered_rows
    ),
    "platform_producer_bindings": {
        row: (
            producer.__defaults__ == (row,)
            and any(
                cell.cell_contents is platform_source_registry
                for cell in tuple(producer.__closure__ or ())
            )
        )
        for row, producer in main.PLATFORM_ROW_PRODUCER_REGISTRY._producers.items()
    },
    "summaries": {
        name: {
            "status": response.status_code,
            "body": response.json(),
        }
        for name, response in summary_responses.items()
    },
    "failed_writes": {
        "full_product": {
            "status": full_product_write.status_code,
            "body": full_product_write.json(),
        },
        "platform": {
            "status": platform_write.status_code,
            "body": platform_write.json(),
        },
    },
    "terminal_record_counts": {
        "full_product_attestations": len(
            main.GOAL_FULL_PRODUCT_ATTESTATION_REGISTRY.records(
                owner_user_id=owner_user_id
            )
        ),
        "platform_manifest_rows": len(
            main.PLATFORM_COVERAGE_REGISTRY.records(
                owner_user_id=owner_user_id
            )
        ),
    },
    "terminal_ledger_exists": {
        "full_product_attestations": (
            runtime_root
            / "audit"
            / "goal_full_product_entrypoint_attestations.jsonl"
        ).exists(),
        "platform_manifest": (
            runtime_root / "audit" / "platform_coverage_manifest.jsonl"
        ).exists(),
    },
}
print("QUANTBT_PRODUCTION_COMPOSITION_PROBE=" + json.dumps(payload, sort_keys=True))
"""


def test_real_main_composition_is_registered_and_fails_closed_until_sources_exist(
    tmp_path: Path,
) -> None:
    """Exercise a fresh production graph without fake producers or resolvers.

    This is intentionally a red-state acceptance contract.  A clean deployment
    has no owner evidence, so claiming strict completion would be dishonest.
    The test proves that the real composition is complete at registration time,
    that its public summaries remain red, and that both terminal writers stop
    before persistence at the first missing real source.  When a real bootstrap
    workflow can author the complete evidence chain, this test should be
    replaced by that positive production-composition journey.
    """

    runtime_root = (tmp_path / "runtime").resolve()
    environment = os.environ.copy()
    environment.update(
        {
            "BACKTEST_DATA_ROOT": str(runtime_root),
            "QUANTBT_KEYSTORE_BACKEND": "memory",
            "QUANTBT_RUNTIME_MODE": "test",
            "QUANTBT_SECRETS_PATH": str(runtime_root / "absent-secrets.yaml"),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", PROBE_SOURCE],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, (
        f"production composition probe exited {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    probe_lines = [
        line.removeprefix(PROBE_PREFIX)
        for line in completed.stdout.splitlines()
        if line.startswith(PROBE_PREFIX)
    ]
    assert len(probe_lines) == 1, completed.stdout
    probe = json.loads(probe_lines[0])

    assert probe["runtime_root"] == str(runtime_root)
    assert probe["main_data_root"] == str(runtime_root)
    assert probe["registration_status"] == 200
    assert probe["composition_types"] == {
        "entrypoint_coverage": (
            "app.research_os.goal_coverage.RiskConsentEntrypointCoverageRegistry"
        ),
        "full_product_attestations": (
            "app.research_os.goal_full_product_entrypoint."
            "PersistentGoalFullProductEntrypointAttestationRegistry"
        ),
        "full_product_producer": (
            "app.research_os.goal_full_product_entrypoint."
            "GoalFullProductEntrypointProducer"
        ),
        "platform_coverage_registry": (
            "app.research_os.platform_coverage.PersistentPlatformCoverageRegistry"
        ),
        "platform_closure_registry": (
            "app.research_os.platform_closure.PersistentPlatformClosureRegistry"
        ),
        "platform_finalizer": (
            "app.research_os.platform_source_lineage_core."
            "PlatformSourceLineageFinalizer"
        ),
        "platform_producer_registry": (
            "app.research_os.platform_row_producers.PlatformRowProducerRegistry"
        ),
        "platform_source_registry": (
            "app.research_os.platform_row_sources."
            "PersistentPlatformRowSourceRegistry"
        ),
        "platform_typed_resolver": (
            "app.research_os.platform_typed_sources.RealPlatformTypedSourceResolver"
        ),
        "section_coverage": (
            "app.research_os.goal_coverage.PersistentGoalSectionCoverageRegistry"
        ),
        "semantic_proofs": (
            "app.research_os.goal_semantics."
            "PersistentGoalSectionSemanticProofRegistry"
        ),
    }
    assert all(probe["composition_bindings"].values())

    assert probe["registered_semantic_sections"] == probe["required_goal_sections"]
    assert probe["semantic_adapter_types"] == {
        "§0": "app.research_os.north_star_closure.NorthStarClosureSectionAdapter",
        "§1": (
            "app.research_os.goal_semantic_adapters.EntrypointLineageSectionAdapter"
        ),
        "§2": "app.research_os.desk_topology.DeskTopologySectionAdapter",
        "§3": "app.research_os.goal_semantic_adapters.LifecycleClosureSectionAdapter",
        "§4": (
            "app.research_os.onboarding_readiness.OnboardingReadinessSectionAdapter"
        ),
        "§5": "app.research_os.goal_semantic_adapters.RAGConformanceSectionAdapter",
        "§6": "app.research_os.goal_semantic_adapters.PromotionReceiptSectionAdapter",
        "§7": (
            "app.research_os.agent_workflow_closure.AgentWorkflowClosureSectionAdapter"
        ),
        "§8": (
            "app.research_os.goal_semantic_adapters.EntrypointLineageSectionAdapter"
        ),
        "§9": "app.research_os.goal_semantic_adapters.PromotionReceiptSectionAdapter",
        "§10": "app.research_os.goal_semantic_adapters.PromotionReceiptSectionAdapter",
        "§11": "app.research_os.market_coverage.MarketCoverageSectionAdapter",
        "§12": "app.research_os.execution_closure.ExecutionClosureSectionAdapter",
        "§13": "app.research_os.goal_semantic_adapters.PromotionReceiptSectionAdapter",
        "§14": "app.research_os.platform_closure.PlatformClosureSectionAdapter",
        "§15": (
            "app.research_os.model_governance_closure."
            "ModelGovernanceClosureSectionAdapter"
        ),
        "§16": "app.research_os.goal_semantic_adapters.PromotionReceiptSectionAdapter",
        "§17": "app.research_os.goal_semantic_adapters.PromotionReceiptSectionAdapter",
    }
    assert probe["registered_platform_rows"] == probe["required_platform_rows"]
    assert set(probe["platform_producer_bindings"]) == set(
        probe["required_platform_rows"]
    )
    assert all(probe["platform_producer_bindings"].values())
    assert probe["required_entry_sources"] == [
        "chat",
        "canvas",
        "api",
        "ide",
        "scheduler",
        "agent_shell",
    ]

    summaries = probe["summaries"]
    assert all(item["status"] == 200 for item in summaries.values())
    assert summaries["entrypoints"]["body"]["all_entrypoints_wired"] is False
    assert set(summaries["entrypoints"]["body"]["missing_entry_sources"]) == set(
        probe["required_entry_sources"]
    )
    assert summaries["semantic"]["body"]["strictly_backed_proof_total"] == 0
    assert summaries["sections"]["body"]["full_product_implementation"] is False
    assert set(summaries["sections"]["body"]["missing_sections"]) == set(
        probe["required_goal_sections"]
    )
    assert summaries["full_product"]["body"]["current_attestation_total"] == 0
    assert summaries["platform"]["body"]["full_platform_coverage"] is False
    assert set(summaries["platform"]["body"]["missing_platform_rows"]) == set(
        probe["required_platform_rows"]
    )

    full_product_failure = probe["failed_writes"]["full_product"]
    assert full_product_failure["status"] == 422
    assert full_product_failure["body"]["detail"]["stage"] == "preflight"
    assert full_product_failure["body"]["detail"]["completed_stages"] == []
    assert full_product_failure["body"]["detail"]["state_unchanged"] is True
    assert (
        "missing strict non-full core sources: "
        "chat,canvas,api,ide,scheduler,agent_shell"
        in full_product_failure["body"]["detail"]["message"]
    )

    platform_failure = probe["failed_writes"]["platform"]
    assert platform_failure == {
        "status": 422,
        "body": {
            "detail": "platform row source certification is unavailable for M1-M2"
        },
    }
    assert probe["terminal_record_counts"] == {
        "full_product_attestations": 0,
        "platform_manifest_rows": 0,
    }
    assert probe["terminal_ledger_exists"] == {
        "full_product_attestations": False,
        "platform_manifest": False,
    }


def _closure_proofs(
    *,
    promotion_coverage_ref: str = "coverage:promotion",
    lifecycle_asset_ref: str = "run:promoted-shared",
) -> tuple[SimpleNamespace, ...]:
    from app import main

    promotion_receipt_ref = "ide_promotion_receipt:shared"
    rdp_ref = "rdp:shared"
    source_run = "ide-source-shared"
    promotion = tuple(
        SimpleNamespace(
            section=section,
            entrypoint_coverage_refs=(promotion_coverage_ref,),
            subject_ref=(
                f"goal_section:{section}:promotion_receipt:"
                f"{promotion_receipt_ref}"
            ),
            store_refs=(
                promotion_receipt_ref,
                rdp_ref,
                f"ide_run:{source_run}",
            ),
            gate_verdict_refs=(f"gate:{section}",),
        )
        for section in main._FULL_PRODUCT_PROMOTION_SECTIONS
    )
    lifecycle_ref = "lifecycle_closure_receipt:shared"
    lifecycle = SimpleNamespace(
        section="§3",
        entrypoint_coverage_refs=("coverage:lifecycle",),
        subject_ref=f"goal_section:§3:lifecycle_receipt:{lifecycle_ref}",
        store_refs=(lifecycle_ref, lifecycle_asset_ref),
        gate_verdict_refs=(lifecycle_ref,),
    )
    return (lifecycle, *promotion)


def _install_closure_authorities(
    monkeypatch: pytest.MonkeyPatch,
    *,
    linked_promotion_ref: str = "ide_promotion_receipt:shared",
    run_asset_ref: str = "run:promoted-shared",
    run_asset_type: str = "Run",
    source_asset_type: str = "Run",
    run_state: str = "approved_runtime",
    transition_from_state: str = "paper_candidate",
    transition_to_state: str | None = None,
    promotion_history: tuple[str, ...] = ("ide_promotion_receipt:shared",),
) -> None:
    from app import main

    owner = "owner:full-product-main-binding"
    default_receipt = SimpleNamespace(
        source_ide_run_id="ide-source-shared",
        promoted_run_id="promoted-shared",
        rdp_package_id="rdp:shared",
        requested_label="exploratory",
    )
    other_receipt = SimpleNamespace(
        source_ide_run_id="ide-source-other",
        promoted_run_id="promoted-other",
        rdp_package_id="rdp:other",
        requested_label="exploratory",
    )
    coverages = {
        "coverage:promotion": SimpleNamespace(
            entry_source="ide",
            entrypoint_ref="ide:run.promote",
            validation_refs=("ide_promotion_receipt:shared",),
        ),
        "coverage:promotion-other": SimpleNamespace(
            entry_source="ide",
            entrypoint_ref="ide:run.promote",
            validation_refs=("ide_promotion_receipt:other",),
        ),
    }

    class CoverageRegistry:
        def coverage(self, ref, *, owner):
            assert owner == "owner:full-product-main-binding"
            return coverages[ref]

        def canonical_coverage(self, ref, *, owner):
            return self.coverage(ref, owner=owner)

    class PromotionRegistry:
        def receipt(self, ref, *, owner_user_id):
            assert owner_user_id == owner
            if ref == "ide_promotion_receipt:shared":
                return default_receipt
            if ref == "ide_promotion_receipt:other":
                return other_receipt
            raise KeyError(ref)

        def validate_current(self, ref, **kwargs):
            assert kwargs["owner_user_id"] == owner
            return SimpleNamespace(accepted=True)

    lifecycle_receipt = SimpleNamespace(
        receipt_ref="lifecycle_closure_receipt:shared",
        transition_refs=("lifecycle_transition:shared",),
        current_asset_refs=(run_asset_ref,),
    )
    lifecycle_transition = SimpleNamespace(
        transition_ref="lifecycle_transition:shared",
        before_asset_ref="run:source-shared",
        after_asset_ref=run_asset_ref,
        from_state=transition_from_state,
        to_state=transition_to_state or run_state,
        promotion_record_ref=linked_promotion_ref,
    )
    promoted_run_asset = SimpleNamespace(
        asset_ref=run_asset_ref,
        asset_type=run_asset_type,
        lifecycle_state=run_state,
        promotion_history=promotion_history,
    )
    source_run_asset = SimpleNamespace(
        asset_ref="run:source-shared",
        asset_type=source_asset_type,
        lifecycle_state=transition_from_state,
    )

    class LifecycleRegistry:
        def current_closure_snapshot(self, ref, *, owner_user_id):
            assert ref == "lifecycle_closure_receipt:shared"
            assert owner_user_id == owner
            return SimpleNamespace(
                receipt=lifecycle_receipt,
                transitions=(lifecycle_transition,),
                before_assets=(source_run_asset,),
                after_assets=(promoted_run_asset,),
            )

    class RDPStore:
        def manifest(self, ref, *, owner_user_id):
            assert owner_user_id == owner
            return SimpleNamespace(package_id=ref)

    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", CoverageRegistry())
    monkeypatch.setattr(main, "PROMOTION_RECEIPT_REGISTRY", PromotionRegistry())
    monkeypatch.setattr(main, "LIFECYCLE_TRANSITION_REGISTRY", LifecycleRegistry())
    monkeypatch.setattr(main, "RDP_STORE", RDPStore())
    monkeypatch.setattr(
        main,
        "_validate_rdp_manifest_for_runtime",
        lambda manifest, *, has_user_waiver, owner: (
            None
            if not has_user_waiver
            and owner == "owner:full-product-main-binding"
            else pytest.fail("unexpected RDP validation envelope")
        ),
    )


@pytest.mark.parametrize(
    ("run_state", "transition_from_state"),
    (
        ("approved_runtime", "paper_candidate"),
        ("monitored_runtime", "approved_runtime"),
    ),
)
def test_main_full_product_closure_derives_coherent_server_owned_chain(
    monkeypatch: pytest.MonkeyPatch,
    run_state: str,
    transition_from_state: str,
) -> None:
    from app import main

    _install_closure_authorities(
        monkeypatch,
        run_state=run_state,
        transition_from_state=transition_from_state,
    )

    closure = main._resolve_goal_full_product_closure(
        "owner:full-product-main-binding",
        _closure_proofs(),
    )

    assert closure.lifecycle_refs == ("lifecycle_closure_receipt:shared",)
    assert closure.rdp_refs == ("rdp:shared",)
    assert closure.promotion_receipt_ref == "ide_promotion_receipt:shared"


def test_main_full_product_closure_rejects_cross_receipt_recombination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    _install_closure_authorities(monkeypatch)
    proofs = list(_closure_proofs())
    section17 = next(index for index, proof in enumerate(proofs) if proof.section == "§17")
    proofs[section17] = SimpleNamespace(
        **{
            **vars(proofs[section17]),
            "entrypoint_coverage_refs": ("coverage:promotion-other",),
            "subject_ref": (
                "goal_section:§17:promotion_receipt:"
                "ide_promotion_receipt:other"
            ),
            "store_refs": (
                "ide_promotion_receipt:other",
                "rdp:other",
                "ide_run:ide-source-other",
            ),
        }
    )

    with pytest.raises(ValueError, match="do not share one receipt and RDP"):
        main._resolve_goal_full_product_closure(
            "owner:full-product-main-binding",
            tuple(proofs),
        )


def test_main_full_product_closure_requires_lifecycle_promotion_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    _install_closure_authorities(
        monkeypatch,
        linked_promotion_ref="ide_promotion_receipt:different",
    )

    with pytest.raises(ValueError, match="exactly one transition bound"):
        main._resolve_goal_full_product_closure(
            "owner:full-product-main-binding",
            _closure_proofs(),
        )


@pytest.mark.parametrize(
    "authority_overrides",
    (
        {
            "run_state": "specified",
            "transition_from_state": "draft",
            "transition_to_state": "specified",
        },
        {"run_asset_ref": "run:unrelated"},
        {"run_asset_type": "Experiment"},
        {"source_asset_type": "StrategyBook"},
        {"promotion_history": ()},
        {"transition_to_state": "monitored_runtime"},
        {
            "run_state": "approved_runtime",
            "transition_from_state": "draft",
        },
        {
            "run_state": "monitored_runtime",
            "transition_from_state": "paper_candidate",
        },
        {
            "run_state": "approved_runtime",
            "transition_from_state": "approved_runtime",
        },
    ),
)
def test_main_full_product_closure_rejects_recombinable_run_edges(
    monkeypatch: pytest.MonkeyPatch,
    authority_overrides,
) -> None:
    from app import main

    _install_closure_authorities(monkeypatch, **authority_overrides)

    with pytest.raises(ValueError, match="exact approved/monitored Run"):
        main._resolve_goal_full_product_closure(
            "owner:full-product-main-binding",
            _closure_proofs(
                lifecycle_asset_ref=authority_overrides.get(
                    "run_asset_ref",
                    "run:promoted-shared",
                )
            ),
        )


def test_rdp_runtime_rejects_prior_terminal_coverage_without_recursing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    owner = "owner:rdp-no-terminal-cycle"
    base = SimpleNamespace(
        coverage_ref="coverage:base",
        recorded_by=owner,
        claims_full_product_entrypoint=False,
        lifecycle_refs=(),
    )
    terminal = SimpleNamespace(
        coverage_ref="coverage:terminal",
        recorded_by=owner,
        claims_full_product_entrypoint=True,
        lifecycle_refs=("lifecycle_closure_receipt:old",),
    )

    class CoverageRegistry:
        def __init__(self) -> None:
            self.refresh_total = 0
            self.validated_refs: list[str] = []

        def refresh(self) -> None:
            self.refresh_total += 1

        def coverage(self, ref, *, owner):
            assert owner == "owner:rdp-no-terminal-cycle"
            return {
                base.coverage_ref: base,
                terminal.coverage_ref: terminal,
            }[ref]

        def canonical_coverage(self, ref, *, owner):
            return self.coverage(ref, owner=owner)

        def validate_real_backing(self, record):
            self.validated_refs.append(record.coverage_ref)
            return SimpleNamespace(accepted=True, violations=())

    coverage_registry = CoverageRegistry()
    empty_spine_closure = SimpleNamespace(
        mathematical_refs=(),
        theory_binding_refs=(),
        consistency_check_refs=(),
        methodology_choice_refs=(),
        responsibility_refs=(),
    )
    manifest = SimpleNamespace(
        trust_release_ref="",
        market_data_use_validation_refs=(),
        data_refs=(),
        compiler_artifact_refs=(),
        mathematical_spine_chain_refs=("math_spine_chain:test",),
        mathematical_refs=(),
        theory_binding_refs=(),
        consistency_check_refs=(),
        methodology_choice_refs=(),
        responsibility_refs=(),
        goal_entrypoint_coverage_refs=(base.coverage_ref, terminal.coverage_ref),
    )
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        coverage_registry,
    )
    monkeypatch.setattr(
        main,
        "_verified_spine_closures",
        lambda refs, *, owner: {refs[0]: empty_spine_closure},
    )

    with pytest.raises(ValueError, match="terminal full-product"):
        main._validate_rdp_manifest_registered_refs(manifest, owner=owner)

    assert coverage_registry.refresh_total == 0
    assert coverage_registry.validated_refs == [base.coverage_ref]
