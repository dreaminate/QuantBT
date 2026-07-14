from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.datasets.templates import StrategyTemplate
from app.ide.service import IDEService, StrategyFile
from app.research_os.asset_lifecycle import (
    AssetCategory,
    GovernedAssetRecord,
    LifecycleState,
    PersistentAssetLifecycleRegistry,
)
from app.research_os.compiler import PersistentCompilerIRStore
from app.research_os.goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
)
from app.research_os.platform_business_history_m16_m21 import (
    ENTRYPOINT_REFS,
    M16BusinessHistorySubject,
    M19BusinessHistorySubject,
    M21BusinessHistorySubject,
    PlatformBusinessHistoryM16M21Context,
    PlatformBusinessHistoryM16M21CommitError,
    PlatformBusinessHistoryM16M21Error,
    PlatformBusinessHistoryM16M21Recorder,
    PlatformBusinessHistoryM16M21Result,
    m21_governed_template_snapshot_hash,
    m21_ide_strategy_snapshot_hash,
    prepare_platform_business_history_m16_m21,
)
from app.research_os.spine import PersistentResearchGraphStore
from app.research_os.teaching_assets import (
    TeachingAssetBundle,
    TeachingEvidenceRecord,
    TutorialAssetRecord,
    WeaknessDisclosureRecord,
)
from app.sharing.service import (
    SharedStrategy,
    SharingService,
    shared_strategy_asset_ref,
    shared_strategy_permission,
    shared_strategy_source,
    shared_strategy_status,
)
from tests.test_platform_business_history_m16_m21 import (
    _FailOncePersistentHistoryCoverage,
    _PersistentHistoryCompilerAdapter,
    _PersistentHistoryCoverageResolver,
)


OWNER = "owner:platform-business-history-api"
USERNAME = "platform_business_history_owner"


@pytest.fixture(autouse=True)
def _clear_auth_override():
    main.app.dependency_overrides.pop(require_user_dependency, None)
    yield
    main.app.dependency_overrides.pop(require_user_dependency, None)


def _client() -> TestClient:
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=OWNER,
        username=USERNAME,
    )
    return TestClient(main.app)


def _success(*, row: str, anchor_ref: str) -> PlatformBusinessHistoryM16M21Result:
    token = row.lower()
    return PlatformBusinessHistoryM16M21Result(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=anchor_ref,
        entrypoint_ref=ENTRYPOINT_REFS[row],
        qro_ref=f"qro:platform-business-history:{token}",
        graph_command_ref=f"rgcmd:platform-business-history:{token}",
        graph_command_created=True,
        compiler_ir_ref=f"compiler_ir:platform-business-history:{token}",
        compiler_pass_ref=f"compiler_pass:platform-business-history:{token}",
        entrypoint_coverage_ref=(
            f"goal_entrypoint_coverage:platform-business-history:{token}"
        ),
    )


def _history_body(*, row: str, anchor_ref: str) -> dict[str, Any]:
    result = _success(row=row, anchor_ref=anchor_ref)
    return {
        "owner_user_id": result.owner_user_id,
        "row": result.row,
        "anchor_ref": result.anchor_ref,
        "entrypoint_ref": result.entrypoint_ref,
        "qro_ref": result.qro_ref,
        "graph_command_ref": result.graph_command_ref,
        "graph_command_created": result.graph_command_created,
        "compiler_ir_ref": result.compiler_ir_ref,
        "compiler_pass_ref": result.compiler_pass_ref,
        "entrypoint_coverage_ref": result.entrypoint_coverage_ref,
    }


class _FailOncePlannedHistoryRecorder:
    """Inject one history failure without replacing deterministic preparation."""

    def __init__(self) -> None:
        self.plans: list[Any] = []
        self.subjects: list[object] = []

    def record(
        self,
        *,
        owner_user_id: str,
        row: str,
        anchor_ref: str,
        subject: object,
    ) -> PlatformBusinessHistoryM16M21Result:
        plan = prepare_platform_business_history_m16_m21(
            owner_user_id=owner_user_id,
            row=row,
            anchor_ref=anchor_ref,
            subject=subject,
        )
        self.plans.append(plan)
        self.subjects.append(subject)
        proof_token = main.content_hash(
            {
                "owner_user_id": owner_user_id,
                "row": row,
                "qro_ref": plan.qro.qro_id,
                "graph_command_ref": plan.command.command_id,
            }
        )
        compiler_ir_ref = f"compiler_ir:retry-regression:{proof_token}"
        compiler_pass_ref = f"compiler_pass:retry-regression:{proof_token}"
        coverage_ref = f"goal_entrypoint_coverage:retry-regression:{proof_token}"
        if len(self.plans) == 1:
            raise PlatformBusinessHistoryM16M21CommitError(
                "injected business history failure before proof persistence",
                phase="research_graph",
                graph_history_current=False,
                graph_command_ref=plan.command.command_id,
                graph_command_created=False,
                compiler_history_current=False,
                compiler_ir_ref=compiler_ir_ref,
                compiler_pass_ref=compiler_pass_ref,
                entrypoint_coverage_ref=coverage_ref,
            )
        return PlatformBusinessHistoryM16M21Result(
            owner_user_id=owner_user_id,
            row=row,
            anchor_ref=anchor_ref,
            entrypoint_ref=plan.entrypoint_ref,
            qro_ref=plan.qro.qro_id,
            graph_command_ref=plan.command.command_id,
            graph_command_created=True,
            compiler_ir_ref=compiler_ir_ref,
            compiler_pass_ref=compiler_pass_ref,
            entrypoint_coverage_ref=coverage_ref,
        )


class _CapturingPlannedHistoryRecorder:
    """Return deterministic proof identities while preserving every route subject."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.plans: list[Any] = []

    def record(
        self,
        *,
        owner_user_id: str,
        row: str,
        anchor_ref: str,
        subject: object,
    ) -> PlatformBusinessHistoryM16M21Result:
        plan = prepare_platform_business_history_m16_m21(
            owner_user_id=owner_user_id,
            row=row,
            anchor_ref=anchor_ref,
            subject=subject,
        )
        self.calls.append(
            {
                "owner_user_id": owner_user_id,
                "row": row,
                "anchor_ref": anchor_ref,
                "subject": subject,
            }
        )
        self.plans.append(plan)
        proof_token = main.content_hash(
            {
                "owner_user_id": owner_user_id,
                "row": row,
                "qro_ref": plan.qro.qro_id,
                "graph_command_ref": plan.command.command_id,
            }
        )
        return PlatformBusinessHistoryM16M21Result(
            owner_user_id=owner_user_id,
            row=row,
            anchor_ref=anchor_ref,
            entrypoint_ref=plan.entrypoint_ref,
            qro_ref=plan.qro.qro_id,
            graph_command_ref=plan.command.command_id,
            graph_command_created=True,
            compiler_ir_ref=f"compiler_ir:capture:{proof_token}",
            compiler_pass_ref=f"compiler_pass:capture:{proof_token}",
            entrypoint_coverage_ref=f"goal_entrypoint_coverage:capture:{proof_token}",
        )


def _persistent_m21_route_history_runtime(
    *,
    graph_path,
    compiler_path,
    coverage_path,
    governed_asset_ref: str,
    failure: str,
):
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(compiler_path)
    backing = _PersistentHistoryCoverageResolver(
        graph,
        compiler,
        owner=OWNER,
        lifecycle_refs=(governed_asset_ref,),
    )
    coverage = _FailOncePersistentHistoryCoverage(
        coverage_path,
        resolver=backing,
    )
    adapter = _PersistentHistoryCompilerAdapter(
        compiler=compiler,
        coverage=coverage,
        failure="" if failure == "graph_ack" else failure,
    )
    graph_ack_pending = failure == "graph_ack"

    def apply_graph(command):
        nonlocal graph_ack_pending
        ref = graph.apply(command)
        if graph_ack_pending:
            graph_ack_pending = False
            raise OSError("injected Graph durability acknowledgement loss")
        return ref

    def fresh_compiler():
        return PersistentCompilerIRStore(compiler_path)

    def fresh_coverage():
        fresh_graph = PersistentResearchGraphStore(graph_path)
        fresh_compiler_store = PersistentCompilerIRStore(compiler_path)
        return PersistentGoalEntrypointCoverageRegistry(
            coverage_path,
            resolver=_PersistentHistoryCoverageResolver(
                fresh_graph,
                fresh_compiler_store,
                owner=OWNER,
                lifecycle_refs=(governed_asset_ref,),
            ),
        )

    recorder = PlatformBusinessHistoryM16M21Recorder(
        PlatformBusinessHistoryM16M21Context(
            research_graph_store=graph,
            compiler_store=compiler,
            entrypoint_registry=coverage,
            apply_graph=apply_graph,
            compile_history=adapter.compile,
            compiler_view_factory=fresh_compiler,
            entrypoint_view_factory=fresh_coverage,
        )
    )
    return SimpleNamespace(
        recorder=recorder,
        graph=graph,
        compiler=compiler,
        coverage=coverage,
        paths=(graph_path, compiler_path, coverage_path),
        fresh_coverage=fresh_coverage,
    )


def _fresh_m21_route_history_state(runtime):
    graph = PersistentResearchGraphStore(runtime.paths[0])
    compiler = PersistentCompilerIRStore(runtime.paths[1])
    coverage = runtime.fresh_coverage()
    return SimpleNamespace(
        graph=graph,
        compiler=compiler,
        coverage=coverage,
    )


@dataclass
class _RouteScenario:
    row: str
    path: str
    payload: dict[str, Any]
    anchor_ref: str
    subject: Callable[[], object]
    expected_body: Callable[[dict[str, Any]], dict[str, Any]]
    assert_business_committed: Callable[[], None]
    business_call_count: Callable[[], int]


def _m16_scenario(monkeypatch) -> _RouteScenario:
    strategy = SharedStrategy(
        share_id="share-route-history-m16",
        run_id="run-route-history-m16",
        author_id=OWNER,
        title="M16 route history",
        description="the just-published strategy",
        tags=["history", "m16"],
        asset_class="equity_cn",
        public=True,
        created_at_utc="2026-07-13T01:00:00+00:00",
    )
    anchor = shared_strategy_asset_ref(strategy)
    permission = shared_strategy_permission(strategy)
    source = shared_strategy_source(strategy)
    status = shared_strategy_status(strategy)
    sharing_calls: list[dict[str, Any]] = []
    lifecycle_calls: list[tuple[GovernedAssetRecord, str]] = []

    def publish_strategy(**kwargs):
        sharing_calls.append(dict(kwargs))
        return strategy

    def shared_asset(ref: str, *, owner_user_id: str):
        assert (ref, owner_user_id) == (anchor, OWNER)
        return strategy

    def stored_permission(ref: str, *, owner_user_id: str):
        assert (ref, owner_user_id) == (permission.permission_ref, OWNER)
        return permission

    def stored_source(ref: str, *, owner_user_id: str):
        assert (ref, owner_user_id) == (source.source_ref, OWNER)
        return source

    def stored_status(ref: str, *, owner_user_id: str):
        assert (ref, owner_user_id) == (status.status_ref, OWNER)
        return status

    def record_governed_asset(
        record: GovernedAssetRecord,
        *,
        owner_user_id: str,
    ) -> GovernedAssetRecord:
        lifecycle_calls.append((record, owner_user_id))
        return record

    def governed_asset(ref: str, *, owner_user_id: str) -> GovernedAssetRecord:
        assert (ref, owner_user_id) == (anchor, OWNER)
        return lifecycle_calls[-1][0]

    monkeypatch.setattr(
        main,
        "SHARING_SERVICE",
        SimpleNamespace(
            publish_strategy=publish_strategy,
            shared_asset=shared_asset,
            permission=stored_permission,
            source=stored_source,
            status=stored_status,
        ),
    )
    monkeypatch.setattr(
        main,
        "ASSET_LIFECYCLE_REGISTRY",
        SimpleNamespace(
            record_governed_asset=record_governed_asset,
            governed_asset=governed_asset,
        ),
    )

    def subject() -> M16BusinessHistorySubject:
        assert len(lifecycle_calls) == 1
        lifecycle, owner = lifecycle_calls[0]
        assert owner == OWNER
        assert lifecycle.asset_ref == anchor
        assert lifecycle.asset_type == "SharedStrategy"
        assert str(getattr(lifecycle.category, "value", lifecycle.category)) == "user_asset"
        assert str(
            getattr(lifecycle.lifecycle_state, "value", lifecycle.lifecycle_state)
        ) == "linked"
        assert set(lifecycle.evidence_refs) == {
            permission.permission_ref,
            source.source_ref,
            status.status_ref,
        }
        return M16BusinessHistorySubject(
            strategy=strategy,
            permission=permission,
            source=source,
            status=status,
            governed_asset=lifecycle,
        )

    def expected_body(history: dict[str, Any]) -> dict[str, Any]:
        return {**strategy.to_dict(), "business_history": history}

    def assert_business_committed() -> None:
        assert sharing_calls == [
            {
                "run_id": strategy.run_id,
                "author_id": OWNER,
                "title": strategy.title,
                "description": strategy.description,
                "tags": strategy.tags,
                "asset_class": strategy.asset_class,
                "public": True,
                "idempotency_key": "m16-sharing-publish:"
                + main.content_hash(
                    {
                        "owner_user_id": OWNER,
                        "run_id": strategy.run_id,
                        "title": strategy.title,
                        "description": strategy.description,
                        "tags": strategy.tags,
                        "asset_class": strategy.asset_class,
                        "public": True,
                    }
                ),
            }
        ]
        subject()

    return _RouteScenario(
        row="M16",
        path="/api/sharing/publish",
        payload={
            "run_id": strategy.run_id,
            "title": strategy.title,
            "description": strategy.description,
            "tags": strategy.tags,
            "asset_class": strategy.asset_class,
            "public": True,
        },
        anchor_ref=anchor,
        subject=subject,
        expected_body=expected_body,
        assert_business_committed=assert_business_committed,
        business_call_count=lambda: len(sharing_calls) + len(lifecycle_calls),
    )


def _m19_bundle(governed_asset_ref: str) -> TeachingAssetBundle:
    tutorial = TutorialAssetRecord(
        tutorial_asset_ref="",
        owner_user_id=OWNER,
        governed_asset_ref=governed_asset_ref,
        category="tutorial",
        title="M19 route history",
    )
    tutorial = replace(tutorial, tutorial_asset_ref=tutorial.canonical_ref)
    weakness = WeaknessDisclosureRecord(
        weakness_disclosure_ref="",
        owner_user_id=OWNER,
        tutorial_asset_ref=tutorial.tutorial_asset_ref,
        weakness_refs=("weakness:m19:limited-sample",),
        visible_by_default=True,
    )
    weakness = replace(
        weakness,
        weakness_disclosure_ref=weakness.canonical_ref,
    )
    evidence = TeachingEvidenceRecord(
        teaching_evidence_ref="",
        owner_user_id=OWNER,
        tutorial_asset_ref=tutorial.tutorial_asset_ref,
        weakness_disclosure_ref=weakness.weakness_disclosure_ref,
        evidence_refs=("evidence:m19:route-history",),
    )
    evidence = replace(evidence, teaching_evidence_ref=evidence.canonical_ref)
    return TeachingAssetBundle(
        tutorial=tutorial,
        weakness=weakness,
        evidence=evidence,
    )


def _m19_scenario(monkeypatch) -> _RouteScenario:
    governed = GovernedAssetRecord(
        asset_ref="governed_asset:teaching:route-history-m19",
        asset_type="TeachingAsset",
        category=AssetCategory.TUTORIAL,
        lifecycle_state=LifecycleState.LINKED,
        evidence_refs=("evidence:m19:lifecycle",),
        validation_plan_ref="validation_plan:m19:route-history",
        promotion_history=(),
    )
    bundle = _m19_bundle(governed.asset_ref)
    teaching_calls: list[dict[str, Any]] = []
    lifecycle_lookups: list[tuple[str, str]] = []

    def record_bundle(**kwargs):
        teaching_calls.append(dict(kwargs))
        return bundle

    def governed_asset(ref: str, *, owner_user_id: str) -> GovernedAssetRecord:
        lifecycle_lookups.append((ref, owner_user_id))
        assert (ref, owner_user_id) == (governed.asset_ref, OWNER)
        return governed

    monkeypatch.setattr(
        main,
        "TEACHING_ASSET_REGISTRY",
        SimpleNamespace(record_bundle=record_bundle),
    )
    monkeypatch.setattr(
        main,
        "ASSET_LIFECYCLE_REGISTRY",
        SimpleNamespace(governed_asset=governed_asset),
    )

    payload = {
        "governed_asset_ref": governed.asset_ref,
        "title": bundle.tutorial.title,
        "weakness_refs": list(bundle.weakness.weakness_refs),
        "evidence_refs": list(bundle.evidence.evidence_refs),
    }

    def subject() -> M19BusinessHistorySubject:
        assert lifecycle_lookups
        return M19BusinessHistorySubject(
            bundle=bundle,
            governed_asset=governed,
        )

    def expected_body(history: dict[str, Any]) -> dict[str, Any]:
        return {
            "tutorial": asdict(bundle.tutorial),
            "weakness": asdict(bundle.weakness),
            "evidence": asdict(bundle.evidence),
            "current": True,
            "current_error": None,
            "business_history": history,
        }

    def assert_business_committed() -> None:
        assert teaching_calls == [
            {
                "owner_user_id": OWNER,
                "governed_asset_ref": governed.asset_ref,
                "title": bundle.tutorial.title,
                "weakness_refs": bundle.weakness.weakness_refs,
                "evidence_refs": bundle.evidence.evidence_refs,
            }
        ]
        subject()

    return _RouteScenario(
        row="M19",
        path="/api/research-os/teaching/assets",
        payload=payload,
        anchor_ref=bundle.tutorial.tutorial_asset_ref,
        subject=subject,
        expected_body=expected_body,
        assert_business_committed=assert_business_committed,
        business_call_count=lambda: len(teaching_calls),
    )


def _m21_scenario(monkeypatch) -> _RouteScenario:
    template = StrategyTemplate(
        template_id="route_history_m21",
        name="M21 route history template",
        asset_class="equity_cn",
        description="governed template fork",
        expected_metrics={"sharpe_min": 0.5},
        code="quantbt.emit_result({'signal': 0})\n",
    )
    strategy = StrategyFile(
        strategy_id="stg_route_history_m21",
        owner_username=USERNAME,
        name="route_history_fork",
        code=template.code,
        asset_class=template.asset_class,
        description="forked for route history",
        updated_at_utc="2026-07-13T01:30:00Z",
        market_data_use_validation_refs=[],
    )
    lifecycle_calls: list[tuple[GovernedAssetRecord, str]] = []
    ide_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def record_governed_asset(
        record: GovernedAssetRecord,
        *,
        owner_user_id: str,
    ) -> GovernedAssetRecord:
        lifecycle_calls.append((record, owner_user_id))
        return record

    def governed_asset(ref: str, *, owner_user_id: str) -> GovernedAssetRecord:
        if not lifecycle_calls:
            raise KeyError(ref)
        assert (ref, owner_user_id) == (lifecycle_calls[-1][0].asset_ref, OWNER)
        return lifecycle_calls[-1][0]

    def save_strategy(*args, **kwargs) -> StrategyFile:
        ide_calls.append((args, dict(kwargs)))
        return strategy

    monkeypatch.setattr(
        main,
        "get_strategy_template",
        lambda template_id: template if template_id == template.template_id else None,
    )
    monkeypatch.setattr(
        main,
        "ASSET_LIFECYCLE_REGISTRY",
        SimpleNamespace(
            record_governed_asset=record_governed_asset,
            governed_asset=governed_asset,
        ),
    )
    monkeypatch.setattr(main, "IDE_SERVICE", SimpleNamespace(save_strategy=save_strategy))

    payload = {
        "name": strategy.name,
        "description": strategy.description,
    }

    def subject() -> M21BusinessHistorySubject:
        assert len(lifecycle_calls) == 1
        lifecycle, owner = lifecycle_calls[0]
        assert owner == OWNER
        assert lifecycle == template.to_governed_asset_record()
        assert ide_calls == [
            (
                (USERNAME, strategy.name, template.code),
                {
                    "asset_class": template.asset_class,
                    "description": strategy.description,
                },
            )
        ]
        assert strategy.owner_username == USERNAME
        assert strategy.owner_username != OWNER
        return M21BusinessHistorySubject(
            governed_asset=lifecycle,
            ide_strategy=strategy,
        )

    def expected_body(history: dict[str, Any]) -> dict[str, Any]:
        lifecycle = lifecycle_calls[0][0]
        strategy_anchor = f"ide_strategy:{strategy.strategy_id}"
        return {
            "strategy_id": strategy.strategy_id,
            "ide_strategy_ref": strategy_anchor,
            "governed_asset_ref": lifecycle.asset_ref,
            "name": strategy.name,
            "ide_url": f"/ide?open={strategy.name}",
            "expected_metrics": template.expected_metrics,
            "category": "template",
            "mock_label_ref": lifecycle.mock_label_ref,
            "asset_category_ref": lifecycle.asset_category_ref,
            "display_label": lifecycle.display_label,
            "production_eligible": False,
            "business_history": history,
        }

    def assert_business_committed() -> None:
        subject()

    return _RouteScenario(
        row="M21",
        path=(
            f"/api/strategies/templates/{template.template_id}/fork_to_ide"
        ),
        payload=payload,
        anchor_ref=f"ide_strategy:{strategy.strategy_id}",
        subject=subject,
        expected_body=expected_body,
        assert_business_committed=assert_business_committed,
        business_call_count=lambda: len(lifecycle_calls) + len(ide_calls),
    )


def _scenario(monkeypatch, row: str) -> _RouteScenario:
    return {
        "M16": _m16_scenario,
        "M19": _m19_scenario,
        "M21": _m21_scenario,
    }[row](monkeypatch)


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_original_business_route_records_exact_just_written_subject_and_history(
    monkeypatch,
    row: str,
) -> None:
    scenario = _scenario(monkeypatch, row)
    recorder_calls: list[dict[str, Any]] = []

    def record(**kwargs):
        recorder_calls.append(dict(kwargs))
        return _success(row=row, anchor_ref=scenario.anchor_ref)

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        SimpleNamespace(record=record),
    )
    response = _client().post(scenario.path, json=scenario.payload)

    assert response.status_code == 200, response.text
    scenario.assert_business_committed()
    assert recorder_calls == [
        {
            "owner_user_id": OWNER,
            "row": row,
            "anchor_ref": scenario.anchor_ref,
            "subject": scenario.subject(),
        }
    ]
    history = _history_body(row=row, anchor_ref=scenario.anchor_ref)
    assert response.json() == jsonable_encoder(scenario.expected_body(history))


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_original_business_route_reports_exact_history_partial_commit_state(
    monkeypatch,
    row: str,
) -> None:
    scenario = _scenario(monkeypatch, row)
    token = row.lower()

    def record(**_kwargs):
        raise PlatformBusinessHistoryM16M21CommitError(
            "business history compiler write stopped",
            phase="compiler_coverage",
            graph_history_current=True,
            graph_command_ref=f"rgcmd:partial:{token}",
            graph_command_created=True,
            compiler_history_current=True,
            compiler_ir_ref=f"compiler_ir:partial:{token}",
            compiler_pass_ref=f"compiler_pass:partial:{token}",
            entrypoint_coverage_ref=f"goal_entrypoint_coverage:partial:{token}",
        )

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        SimpleNamespace(record=record),
    )
    response = _client().post(scenario.path, json=scenario.payload)

    assert response.status_code == 409, response.text
    scenario.assert_business_committed()
    assert response.json() == {
        "detail": {
            "message": "business history compiler write stopped",
            "business_write_committed": True,
            "row": row,
            "anchor_ref": scenario.anchor_ref,
            "phase": "compiler_coverage",
            "graph_history_current": True,
            "graph_command_ref": f"rgcmd:partial:{token}",
            "graph_command_created": True,
            "compiler_history_current": True,
            "compiler_ir_ref": f"compiler_ir:partial:{token}",
            "compiler_pass_ref": f"compiler_pass:partial:{token}",
            "entrypoint_coverage_ref": (
                f"goal_entrypoint_coverage:partial:{token}"
            ),
        }
    }


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_original_business_route_maps_history_semantic_error_after_business_commit(
    monkeypatch,
    row: str,
) -> None:
    scenario = _scenario(monkeypatch, row)

    def record(**_kwargs):
        raise PlatformBusinessHistoryM16M21Error(
            "just-written business state cannot form exact prospective history"
        )

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        SimpleNamespace(record=record),
    )
    response = _client().post(scenario.path, json=scenario.payload)

    assert response.status_code == 409, response.text
    scenario.assert_business_committed()
    assert response.json() == {
        "detail": {
            "message": (
                "just-written business state cannot form exact prospective history"
            ),
            "business_write_committed": True,
            "row": row,
            "anchor_ref": scenario.anchor_ref,
            "phase": "history_preflight",
        }
    }


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_original_business_route_rejects_caller_proof_refs_before_business_write(
    monkeypatch,
    row: str,
) -> None:
    scenario = _scenario(monkeypatch, row)
    recorder_called = False

    def record(**_kwargs):
        nonlocal recorder_called
        recorder_called = True
        return _success(row=row, anchor_ref=scenario.anchor_ref)

    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        SimpleNamespace(record=record),
    )
    forged = {
        **scenario.payload,
        "qro_ref": "qro:caller-forged",
        "graph_command_ref": "rgcmd:caller-forged",
        "compiler_ir_ref": "compiler_ir:caller-forged",
        "compiler_pass_ref": "compiler_pass:caller-forged",
        "entrypoint_coverage_ref": "goal_entrypoint_coverage:caller-forged",
        "mathematical_spine_chain_ref": "math_spine_chain:caller-forged",
        "validation_refs": ["goal_validation_receipt:caller-forged"],
    }

    response = _client().post(scenario.path, json=forged)

    assert response.status_code == 422, response.text
    assert scenario.business_call_count() == 0
    assert recorder_called is False


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_message", "expected_error_type"),
    (
        ("name", "bad name!", "策略名只能用字母数字 - _", "IDEError"),
        ("name", 0, "name 必须是字符串", "TypeError"),
        ("name", False, "name 必须是字符串", "TypeError"),
        ("name", [], "name 必须是字符串", "TypeError"),
        ("name", {}, "name 必须是字符串", "TypeError"),
        ("description", 0, "description 必须是字符串", "TypeError"),
        ("description", False, "description 必须是字符串", "TypeError"),
        ("description", [], "description 必须是字符串", "TypeError"),
        ("description", {}, "description 必须是字符串", "TypeError"),
    ),
)
def test_m21_invalid_raw_ide_input_is_rejected_before_any_persistent_write(
    monkeypatch,
    tmp_path,
    field: str,
    invalid_value: object,
    expected_message: str,
    expected_error_type: str | None,
) -> None:
    template = StrategyTemplate(
        template_id="route_history_m21_invalid_preflight",
        name="M21 invalid preflight template",
        asset_class="equity_cn",
        description="invalid IDE input must not touch lifecycle",
        expected_metrics={"sharpe_min": 0.5},
        code="quantbt.emit_result({'signal': 0})\n",
    )
    ide_db = tmp_path / "m21-invalid-preflight-ide.db"
    run_root = tmp_path / "m21-invalid-preflight-runs"
    lifecycle_path = tmp_path / "m21-invalid-preflight-lifecycle.jsonl"
    ide = IDEService(ide_db, run_root=run_root)
    lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    history_calls: list[dict[str, Any]] = []

    def record(**kwargs):
        history_calls.append(dict(kwargs))
        raise AssertionError("invalid IDE input reached business history")

    monkeypatch.setattr(
        main,
        "get_strategy_template",
        lambda template_id: template if template_id == template.template_id else None,
    )
    monkeypatch.setattr(main, "IDE_SERVICE", ide)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        SimpleNamespace(record=record),
    )
    initial_ide_bytes = ide_db.read_bytes()
    path = f"/api/strategies/templates/{template.template_id}/fork_to_ide"
    payload = {
        "name": "valid_m21_preflight_name",
        "description": "must fail deterministic IDE preflight",
    }
    payload[field] = invalid_value
    client = _client()

    first = client.post(path, json=payload)

    expected_detail = {
        "message": expected_message,
        "business_write_committed": False,
        "business_fork_committed": False,
        "row": "M21",
        "anchor_ref": None,
        "governed_asset_ref": template.to_governed_asset_record().asset_ref,
        "phase": "ide_preflight",
        "lifecycle_write_current": False,
        "lifecycle_preexisting_before_attempt": None,
        "lifecycle_created_by_attempt": False,
        "ide_strategy_write_current": False,
        "ide_strategy_projection_current": False,
        "ide_strategy_version_current": False,
    }
    if expected_error_type is not None:
        expected_detail["error_type"] = expected_error_type
    assert first.status_code == 400, first.text
    assert first.json() == {"detail": expected_detail}
    assert ide.list_strategies(USERNAME) == []
    assert lifecycle.governed_assets(owner_user_id=OWNER) == []
    assert history_calls == []
    assert ide_db.read_bytes() == initial_ide_bytes
    assert not lifecycle_path.exists() or lifecycle_path.read_bytes() == b""

    restarted_ide = IDEService(ide_db, run_root=run_root)
    restarted_lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    monkeypatch.setattr(main, "IDE_SERVICE", restarted_ide)
    monkeypatch.setattr(
        main,
        "ASSET_LIFECYCLE_REGISTRY",
        restarted_lifecycle,
    )
    second = client.post(path, json=payload)

    assert second.status_code == 400, second.text
    assert second.json() == first.json()
    assert restarted_ide.list_strategies(USERNAME) == []
    assert restarted_lifecycle.governed_assets(owner_user_id=OWNER) == []
    assert history_calls == []
    assert ide_db.read_bytes() == initial_ide_bytes
    assert not lifecycle_path.exists() or lifecycle_path.read_bytes() == b""


def test_m16_identical_http_retry_reuses_one_real_shared_strategy_and_history_identity(
    monkeypatch,
    tmp_path,
) -> None:
    run_id = "run-route-history-m16-idempotent-retry"
    run_root = tmp_path / "sharing-runs"
    (run_root / run_id).mkdir(parents=True)
    sharing_db = tmp_path / "sharing.db"
    lifecycle_path = tmp_path / "m16-lifecycle.jsonl"
    sharing = SharingService(sharing_db, run_root)
    lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    recorder = _FailOncePlannedHistoryRecorder()
    monkeypatch.setattr(main, "SHARING_SERVICE", sharing)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        recorder,
    )
    payload = {
        "run_id": run_id,
        "title": "M16 identical HTTP retry",
        "description": "history fails once after the business write",
        "tags": ["m16", "retry"],
        "asset_class": "equity_cn",
        "public": True,
    }
    client = _client()

    first = client.post("/api/sharing/publish", json=payload)

    assert first.status_code == 409, first.text
    assert first.json()["detail"]["business_write_committed"] is True
    first_rows = sharing.list_strategies(
        author_id=OWNER,
        public_only=False,
        limit=100,
    )
    assert len(first_rows) == 1
    first_strategy = first_rows[0]
    first_anchor = shared_strategy_asset_ref(first_strategy)
    assert first.json()["detail"]["anchor_ref"] == first_anchor
    assert len(lifecycle.governed_assets(owner_user_id=OWNER)) == 1

    restarted_sharing = SharingService(sharing_db, run_root)
    restarted_lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    monkeypatch.setattr(main, "SHARING_SERVICE", restarted_sharing)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", restarted_lifecycle)
    second = client.post("/api/sharing/publish", json=payload)

    assert second.status_code == 200, second.text
    second_rows = restarted_sharing.list_strategies(
        author_id=OWNER,
        public_only=False,
        limit=100,
    )
    assert second_rows == [first_strategy]
    assert len(restarted_lifecycle.governed_assets(owner_user_id=OWNER)) == 1
    assert recorder.subjects[0] == recorder.subjects[1]
    assert recorder.plans[0] == recorder.plans[1]
    history = second.json()["business_history"]
    assert second.json()["share_id"] == first_strategy.share_id
    assert history["anchor_ref"] == first_anchor
    assert history["qro_ref"] == recorder.plans[0].qro.qro_id
    assert history["graph_command_ref"] == recorder.plans[0].command.command_id
    assert (
        first.json()["detail"]["graph_command_ref"]
        == history["graph_command_ref"]
    )


def test_m21_identical_http_retry_reuses_one_real_ide_version_and_history_identity(
    monkeypatch,
    tmp_path,
) -> None:
    template = StrategyTemplate(
        template_id="route_history_m21_idempotent_retry",
        name="M21 idempotent retry template",
        asset_class="equity_cn",
        description="real IDE persistence regression",
        expected_metrics={"sharpe_min": 0.5},
        code="quantbt.emit_result({'signal': 0})\n",
    )
    ide_db = tmp_path / "ide.db"
    ide_run_root = tmp_path / "ide-runs"
    lifecycle_path = tmp_path / "m21-lifecycle.jsonl"
    ide = IDEService(ide_db, run_root=ide_run_root)
    lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    recorder = _FailOncePlannedHistoryRecorder()
    monkeypatch.setattr(
        main,
        "get_strategy_template",
        lambda template_id: template if template_id == template.template_id else None,
    )
    monkeypatch.setattr(main, "IDE_SERVICE", ide)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        recorder,
    )
    strategy_name = "route_history_m21_retry"
    payload = {
        "name": strategy_name,
        "description": "identical template fork retry",
    }
    path = f"/api/strategies/templates/{template.template_id}/fork_to_ide"
    client = _client()

    first = client.post(path, json=payload)

    assert first.status_code == 409, first.text
    assert first.json()["detail"]["business_write_committed"] is True
    first_strategy = ide.get_strategy(USERNAME, strategy_name)
    first_versions = ide.list_versions(USERNAME, strategy_name)
    assert len(ide.list_strategies(USERNAME)) == 1
    assert len(first_versions) == 1
    first_anchor = f"ide_strategy:{first_strategy.strategy_id}"
    assert first.json()["detail"]["anchor_ref"] == first_anchor
    assert len(lifecycle.governed_assets(owner_user_id=OWNER)) == 1

    restarted_ide = IDEService(ide_db, run_root=ide_run_root)
    restarted_lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    monkeypatch.setattr(main, "IDE_SERVICE", restarted_ide)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", restarted_lifecycle)
    second = client.post(path, json=payload)

    assert second.status_code == 200, second.text
    second_strategy = restarted_ide.get_strategy(USERNAME, strategy_name)
    second_versions = restarted_ide.list_versions(USERNAME, strategy_name)
    assert second_strategy == first_strategy
    assert second_strategy.updated_at_utc == first_strategy.updated_at_utc
    assert second_versions == first_versions
    assert len(second_versions) == 1
    assert len(restarted_ide.list_strategies(USERNAME)) == 1
    assert len(restarted_lifecycle.governed_assets(owner_user_id=OWNER)) == 1
    assert recorder.subjects[0] == recorder.subjects[1]
    assert recorder.plans[0] == recorder.plans[1]
    history = second.json()["business_history"]
    assert second.json()["strategy_id"] == first_strategy.strategy_id
    assert second.json()["ide_strategy_ref"] == first_anchor
    assert second.json()["governed_asset_ref"] == (
        template.to_governed_asset_record().asset_ref
    )
    assert history["anchor_ref"] == first_anchor
    assert history["qro_ref"] == recorder.plans[0].qro.qro_id
    assert history["graph_command_ref"] == recorder.plans[0].command.command_id
    assert (
        first.json()["detail"]["graph_command_ref"]
        == history["graph_command_ref"]
    )


def test_m21_ide_ack_loss_reports_current_partial_state_and_retry_reuses_it(
    monkeypatch,
    tmp_path,
) -> None:
    template = StrategyTemplate(
        template_id="route_history_m21_ide_ack_loss",
        name="M21 IDE acknowledgement-loss template",
        asset_class="equity_cn",
        description="IDE writes before acknowledgement fails",
        expected_metrics={"sharpe_min": 0.5},
        code="quantbt.emit_result({'signal': 0})\n",
    )
    ide_db = tmp_path / "m21-ide-ack-loss.db"
    run_root = tmp_path / "m21-ide-ack-loss-runs"
    lifecycle_path = tmp_path / "m21-ide-ack-loss-lifecycle.jsonl"
    ide = IDEService(ide_db, run_root=run_root)
    lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    recorder = _CapturingPlannedHistoryRecorder()

    class _PersistThenRaiseIDE:
        def save_strategy(self, *args, **kwargs):
            ide.save_strategy(*args, **kwargs)
            raise ValueError("injected IDE durability acknowledgement loss")

        def get_strategy(self, *args, **kwargs):
            return ide.get_strategy(*args, **kwargs)

        def list_versions(self, *args, **kwargs):
            return ide.list_versions(*args, **kwargs)

    monkeypatch.setattr(
        main,
        "get_strategy_template",
        lambda template_id: template if template_id == template.template_id else None,
    )
    monkeypatch.setattr(main, "IDE_SERVICE", _PersistThenRaiseIDE())
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        recorder,
    )
    name = "route_history_m21_ide_ack_loss"
    payload = {"name": name, "description": "exact retryable IDE state"}
    path = f"/api/strategies/templates/{template.template_id}/fork_to_ide"
    client = _client()

    first = client.post(path, json=payload)

    persisted = ide.get_strategy(USERNAME, name)
    anchor = f"ide_strategy:{persisted.strategy_id}"
    assert first.status_code == 409, first.text
    assert first.json() == {
        "detail": {
            "message": "injected IDE durability acknowledgement loss",
            "error_type": "ValueError",
            "business_write_committed": True,
            "business_fork_committed": True,
            "row": "M21",
            "anchor_ref": anchor,
            "governed_asset_ref": template.to_governed_asset_record().asset_ref,
            "phase": "ide_strategy",
            "lifecycle_write_current": True,
            "lifecycle_preexisting_before_attempt": False,
            "lifecycle_created_by_attempt": None,
            "ide_strategy_write_current": True,
            "ide_strategy_projection_current": True,
            "ide_strategy_version_current": True,
        }
    }
    assert len(ide.list_strategies(USERNAME)) == 1
    assert len(ide.list_versions(USERNAME, name)) == 1
    assert len(lifecycle.governed_assets(owner_user_id=OWNER)) == 1
    assert recorder.calls == []

    restarted_ide = IDEService(ide_db, run_root=run_root)
    restarted_lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    monkeypatch.setattr(main, "IDE_SERVICE", restarted_ide)
    monkeypatch.setattr(
        main,
        "ASSET_LIFECYCLE_REGISTRY",
        restarted_lifecycle,
    )
    second = client.post(path, json=payload)

    assert second.status_code == 200, second.text
    assert restarted_ide.get_strategy(USERNAME, name) == persisted
    assert len(restarted_ide.list_strategies(USERNAME)) == 1
    assert len(restarted_ide.list_versions(USERNAME, name)) == 1
    assert len(restarted_lifecycle.governed_assets(owner_user_id=OWNER)) == 1
    assert [call["anchor_ref"] for call in recorder.calls] == [anchor]
    assert second.json()["business_history"]["anchor_ref"] == anchor


@pytest.mark.parametrize(
    ("failure", "expected_phase"),
    (
        ("graph_ack", "research_graph"),
        ("after_ir", "compiler_coverage"),
        ("after_pass", "compiler_coverage"),
        ("coverage_failure", "compiler_coverage"),
        ("coverage_ack", "compiler_coverage"),
    ),
)
def test_m21_route_real_history_failure_keeps_fork_and_retries_one_proof_bundle(
    monkeypatch,
    tmp_path,
    failure: str,
    expected_phase: str,
) -> None:
    template = StrategyTemplate(
        template_id=f"route_history_m21_real_failure_{failure}",
        name="M21 real history failure template",
        asset_class="equity_cn",
        description="the business fork and proof prefix survive a late failure",
        expected_metrics={"sharpe_min": 0.5},
        code="quantbt.emit_result({'signal': 0})\n",
    )
    governed_asset_ref = template.to_governed_asset_record().asset_ref
    ide_db = tmp_path / f"m21-real-history-{failure}-ide.db"
    run_root = tmp_path / f"m21-real-history-{failure}-runs"
    lifecycle_path = tmp_path / f"m21-real-history-{failure}-lifecycle.jsonl"
    graph_path = tmp_path / f"m21-real-history-{failure}-graph.jsonl"
    compiler_path = tmp_path / f"m21-real-history-{failure}-compiler.jsonl"
    coverage_path = tmp_path / f"m21-real-history-{failure}-coverage.jsonl"
    ide = IDEService(ide_db, run_root=run_root)
    lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    runtime = _persistent_m21_route_history_runtime(
        graph_path=graph_path,
        compiler_path=compiler_path,
        coverage_path=coverage_path,
        governed_asset_ref=governed_asset_ref,
        failure=failure,
    )
    monkeypatch.setattr(
        main,
        "get_strategy_template",
        lambda template_id: template if template_id == template.template_id else None,
    )
    monkeypatch.setattr(main, "IDE_SERVICE", ide)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        runtime.recorder,
    )
    name = f"m21_real_history_{failure}"
    payload = {"name": name, "description": "retry the exact proof saga"}
    path = f"/api/strategies/templates/{template.template_id}/fork_to_ide"
    client = _client()

    first = client.post(path, json=payload)

    strategy = ide.get_strategy(USERNAME, name)
    anchor = f"ide_strategy:{strategy.strategy_id}"
    assert first.status_code == 409, first.text
    assert first.json()["detail"]["business_write_committed"] is True
    assert first.json()["detail"]["anchor_ref"] == anchor
    assert first.json()["detail"]["phase"] == expected_phase
    assert len(ide.list_strategies(USERNAME)) == 1
    assert len(ide.list_versions(USERNAME, name)) == 1
    assert len(lifecycle.governed_assets(owner_user_id=OWNER)) == 1
    failed_state = _fresh_m21_route_history_state(runtime)
    expected_counts = {
        "graph_ack": (0, 0, 0),
        "after_ir": (1, 0, 0),
        "after_pass": (1, 1, 0),
        "coverage_failure": (1, 1, 0),
        "coverage_ack": (1, 1, 1),
    }[failure]
    assert len(failed_state.graph.commands()) == 1
    assert len(failed_state.compiler.irs(owner=OWNER)) == expected_counts[0]
    assert len(failed_state.compiler.passes(owner=OWNER)) == expected_counts[1]
    assert len(failed_state.coverage.records(owner=OWNER)) == expected_counts[2]
    preserved_command = failed_state.graph.commands()[0]
    preserved_ir_refs = tuple(
        row.ir_ref for row in failed_state.compiler.irs(owner=OWNER)
    )
    preserved_pass_refs = tuple(
        row.pass_ref for row in failed_state.compiler.passes(owner=OWNER)
    )
    preserved_coverage_refs = tuple(
        row.coverage_ref for row in failed_state.coverage.records(owner=OWNER)
    )
    failed_proof_bytes = {
        path: (path.read_bytes() if path.exists() else b"")
        for path in runtime.paths
    }

    restarted_ide = IDEService(ide_db, run_root=run_root)
    restarted_lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    repaired_runtime = _persistent_m21_route_history_runtime(
        graph_path=graph_path,
        compiler_path=compiler_path,
        coverage_path=coverage_path,
        governed_asset_ref=governed_asset_ref,
        failure="",
    )
    monkeypatch.setattr(main, "IDE_SERVICE", restarted_ide)
    monkeypatch.setattr(
        main,
        "ASSET_LIFECYCLE_REGISTRY",
        restarted_lifecycle,
    )
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        repaired_runtime.recorder,
    )
    second = client.post(path, json=payload)

    assert second.status_code == 200, second.text
    assert restarted_ide.get_strategy(USERNAME, name) == strategy
    assert len(restarted_ide.list_strategies(USERNAME)) == 1
    assert len(restarted_ide.list_versions(USERNAME, name)) == 1
    assert len(restarted_lifecycle.governed_assets(owner_user_id=OWNER)) == 1
    history = second.json()["business_history"]
    assert history["anchor_ref"] == anchor
    repaired_state = _fresh_m21_route_history_state(repaired_runtime)
    assert repaired_state.graph.commands() == [preserved_command]
    assert preserved_command.command_id == history["graph_command_ref"]
    assert graph_path.read_bytes() == failed_proof_bytes[graph_path]
    assert compiler_path.read_bytes().startswith(
        failed_proof_bytes[compiler_path]
    )
    assert coverage_path.read_bytes().startswith(
        failed_proof_bytes[coverage_path]
    )
    assert [row.ir_ref for row in repaired_state.compiler.irs(owner=OWNER)] == [
        history["compiler_ir_ref"]
    ]
    assert [
        row.pass_ref for row in repaired_state.compiler.passes(owner=OWNER)
    ] == [history["compiler_pass_ref"]]
    assert [
        row.coverage_ref for row in repaired_state.coverage.records(owner=OWNER)
    ] == [history["entrypoint_coverage_ref"]]
    assert set(preserved_ir_refs).issubset(
        {row.ir_ref for row in repaired_state.compiler.irs(owner=OWNER)}
    )
    assert set(preserved_pass_refs).issubset(
        {row.pass_ref for row in repaired_state.compiler.passes(owner=OWNER)}
    )
    assert set(preserved_coverage_refs).issubset(
        {row.coverage_ref for row in repaired_state.coverage.records(owner=OWNER)}
    )
    assert repaired_state.graph.qro(history["qro_ref"]).mathematical_refs == ()
    persisted_proof_bytes = {
        path: path.read_bytes() for path in repaired_runtime.paths
    }

    third = client.post(path, json=payload)

    assert third.status_code == 200, third.text
    assert third.json()["business_history"] == {
        **history,
        "graph_command_created": False,
    }
    assert {
        path: path.read_bytes() for path in repaired_runtime.paths
    } == persisted_proof_bytes
    assert len(restarted_ide.list_versions(USERNAME, name)) == 1
    assert len(restarted_lifecycle.governed_assets(owner_user_id=OWNER)) == 1


def test_m21_same_template_two_names_create_two_fork_anchors_and_retry_exactly(
    monkeypatch,
    tmp_path,
) -> None:
    template = StrategyTemplate(
        template_id="route_history_m21_two_forks",
        name="M21 two-fork template",
        asset_class="equity_cn",
        description="one governed template may produce multiple IDE strategies",
        expected_metrics={"sharpe_min": 0.5},
        code="quantbt.emit_result({'signal': 0})\n",
    )
    ide_db = tmp_path / "m21-two-forks-ide.db"
    run_root = tmp_path / "m21-two-forks-runs"
    lifecycle_path = tmp_path / "m21-two-forks-lifecycle.jsonl"
    ide = IDEService(ide_db, run_root=run_root)
    lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    recorder = _CapturingPlannedHistoryRecorder()
    monkeypatch.setattr(
        main,
        "get_strategy_template",
        lambda template_id: template if template_id == template.template_id else None,
    )
    monkeypatch.setattr(main, "IDE_SERVICE", ide)
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        recorder,
    )
    path = f"/api/strategies/templates/{template.template_id}/fork_to_ide"
    first_payload = {
        "name": "route_history_m21_first_fork",
        "description": "first fork",
    }
    second_payload = {
        "name": "route_history_m21_second_fork",
        "description": "second fork",
    }
    client = _client()

    first = client.post(path, json=first_payload)
    second = client.post(path, json=second_payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_strategy = ide.get_strategy(USERNAME, first_payload["name"])
    second_strategy = ide.get_strategy(USERNAME, second_payload["name"])
    first_versions = ide.list_versions(USERNAME, first_payload["name"])
    second_versions = ide.list_versions(USERNAME, second_payload["name"])
    first_anchor = f"ide_strategy:{first_strategy.strategy_id}"
    second_anchor = f"ide_strategy:{second_strategy.strategy_id}"
    governed_asset_ref = template.to_governed_asset_record().asset_ref
    assert first_anchor != second_anchor
    assert len(ide.list_strategies(USERNAME)) == 2
    assert len(first_versions) == 1
    assert len(second_versions) == 1
    assert len(lifecycle.governed_assets(owner_user_id=OWNER)) == 1
    assert first.json()["ide_strategy_ref"] == first_anchor
    assert second.json()["ide_strategy_ref"] == second_anchor
    assert first.json()["governed_asset_ref"] == governed_asset_ref
    assert second.json()["governed_asset_ref"] == governed_asset_ref
    assert first.json()["business_history"]["anchor_ref"] == first_anchor
    assert second.json()["business_history"]["anchor_ref"] == second_anchor

    restarted_ide = IDEService(ide_db, run_root=run_root)
    restarted_lifecycle = PersistentAssetLifecycleRegistry(lifecycle_path)
    monkeypatch.setattr(main, "IDE_SERVICE", restarted_ide)
    monkeypatch.setattr(
        main,
        "ASSET_LIFECYCLE_REGISTRY",
        restarted_lifecycle,
    )
    retry = client.post(path, json=first_payload)

    assert retry.status_code == 200, retry.text
    assert restarted_ide.get_strategy(USERNAME, first_payload["name"]) == (
        first_strategy
    )
    assert restarted_ide.list_versions(USERNAME, first_payload["name"]) == (
        first_versions
    )
    assert restarted_ide.get_strategy(USERNAME, second_payload["name"]) == (
        second_strategy
    )
    assert restarted_ide.list_versions(USERNAME, second_payload["name"]) == (
        second_versions
    )
    assert len(restarted_ide.list_strategies(USERNAME)) == 2
    assert len(restarted_lifecycle.governed_assets(owner_user_id=OWNER)) == 1
    assert retry.json()["ide_strategy_ref"] == first_anchor
    assert retry.json()["governed_asset_ref"] == governed_asset_ref
    assert retry.json()["business_history"]["anchor_ref"] == first_anchor
    assert [call["anchor_ref"] for call in recorder.calls] == [
        first_anchor,
        second_anchor,
        first_anchor,
    ]
    assert recorder.calls[0]["subject"] == recorder.calls[2]["subject"]
    assert recorder.calls[0]["subject"].governed_asset == (
        recorder.calls[1]["subject"].governed_asset
    )
    assert recorder.calls[0]["subject"].ide_strategy != (
        recorder.calls[1]["subject"].ide_strategy
    )
    assert recorder.plans[0] == recorder.plans[2]
    assert recorder.plans[0].qro.qro_id != recorder.plans[1].qro.qro_id
    assert recorder.plans[0].qro.input_contract == {
        "entry_source": "api",
        "governed_asset_ref": governed_asset_ref,
    }
    assert recorder.plans[1].qro.input_contract == (
        recorder.plans[0].qro.input_contract
    )
    for plan, call in zip(recorder.plans[:2], recorder.calls[:2], strict=True):
        subject = call["subject"]
        assert set(plan.qro.output_contract) == {
            "ide_strategy_ref",
            "ide_strategy_snapshot_hash",
            "governed_template_snapshot_hash",
            "mock_label_ref",
            "asset_category_ref",
            "status",
        }
        assert plan.qro.output_contract["ide_strategy_snapshot_hash"] == (
            m21_ide_strategy_snapshot_hash(subject.ide_strategy)
        )
        assert plan.qro.output_contract[
            "governed_template_snapshot_hash"
        ] == m21_governed_template_snapshot_hash(subject.governed_asset)


def test_no_retroactive_platform_business_history_mutation_route_is_exposed() -> None:
    mutation_methods = {"POST", "PUT", "PATCH"}
    exposed = sorted(
        (method, route.path)
        for route in main.app.routes
        if "business_history" in str(getattr(route, "path", ""))
        for method in set(getattr(route, "methods", set()) or set()) & mutation_methods
    )

    assert exposed == []
