from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.ide.service import IDEError, StrategyFile
from app.research_os.asset_lifecycle import (
    AssetCategory,
    GovernedAssetRecord,
    LifecycleState,
)
from app.research_os.compiler import PersistentCompilerIRStore
from app.research_os.entrypoint_evidence import (
    CompositeEntrypointEvidenceRegistry,
    PersistentEntrypointEvidenceRegistry,
)
from app.research_os.goal_coverage import PersistentGoalEntrypointCoverageRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.platform_business_history_m16_m21 import (
    M16BusinessHistorySubject,
    M19BusinessHistorySubject,
    M21BusinessHistorySubject,
    PlatformBusinessHistoryM16M21Context,
    PlatformBusinessHistoryM16M21Error,
    PlatformBusinessHistoryM16M21Recorder,
    m21_governed_template_snapshot_hash,
    m21_ide_strategy_snapshot_hash,
)
from app.research_os.platform_source_lineage_policies_m16_m21 import (
    PlatformSourceLineagePoliciesM16M21Context,
    PlatformSourceLineagePolicyM16M21Error,
    build_platform_source_lineage_policy_resolver_m16_m21,
)
from app.research_os.platform_source_lineage_policies_m9_m15 import (
    PlatformSourceLineagePoliciesM9M15Context,
    build_platform_source_lineage_policies_m9_m15,
)
from app.research_os.qro_spine_binding import (
    QROSpineBindingCommitError,
    prepare_current_qro_spine_binding,
)
from app.research_os.spine_chain_selection import SpineChainSelectionError
from app.research_os.spine import (
    ActorSource,
    EntrySource,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    ResearchGraphCommand,
)
from app.research_os.teaching_assets import (
    TeachingAssetBundle,
    TeachingEvidenceRecord,
    TutorialAssetRecord,
    WeaknessDisclosureRecord,
)
from app.sharing.service import (
    SharedStrategy,
    shared_strategy_asset_ref,
    shared_strategy_permission,
    shared_strategy_source,
    shared_strategy_status,
)


OWNER = "owner:platform-spine-binding-api"


@pytest.fixture(autouse=True)
def _clear_auth_override():
    yield
    main.app.dependency_overrides.pop(require_user_dependency, None)


def _client() -> TestClient:
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=OWNER,
        username="platform-spine-binding-owner",
    )
    return TestClient(main.app)


def _success():
    result = SimpleNamespace(
        qro_ref="qro:platform-binding",
        chain_ref="math_spine_chain:platform-binding",
        graph_command_ref="rgcmd:platform-binding",
        graph_command_created=True,
        compiler_ir_ref="compiler_ir:platform-binding",
        compiler_pass_ref="compiler_pass:platform-binding",
        entrypoint_coverage_ref="goal_entrypoint_coverage:platform-binding",
    )
    resolution = SimpleNamespace(
        lifecycle_ref="governed_asset:platform-binding",
        specific_refs=(
            SimpleNamespace(key="factor_ref", ref="factor:platform-binding:v1"),
            SimpleNamespace(key="label_ref", ref="label:platform-binding:v1"),
        ),
    )
    return result, resolution


def test_platform_spine_binding_route_accepts_only_anchor_and_reports_exact_state(
    monkeypatch,
) -> None:
    calls: list[dict[str, str]] = []

    def record(**kwargs):
        calls.append(dict(kwargs))
        return _success()

    monkeypatch.setattr(main, "_record_platform_spine_binding", record)
    response = _client().post(
        "/api/research-os/platform/spine_bindings/M4-M5/current",
        json={"anchor_ref": "factor:platform-binding:v1"},
    )

    assert response.status_code == 200, response.text
    assert calls == [
        {
            "owner_user_id": OWNER,
            "m_row": "M4-M5",
            "anchor_ref": "factor:platform-binding:v1",
        }
    ]
    body = response.json()
    assert body["entrypoint_ref"] == (
        "api:research_os.platform.spine_bindings.m4_m5"
    )
    assert body["graph_command_created"] is True
    assert body["graph_binding_current"] is True
    assert body["compiler_bundle_verified"] is True
    assert body["coverage_persisted"] is True
    assert body["policy_replay_current"] is True
    assert body["specific_refs"] == [
        {"key": "factor_ref", "ref": "factor:platform-binding:v1"},
        {"key": "label_ref", "ref": "label:platform-binding:v1"},
    ]


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_platform_spine_binding_route_exposes_exact_post_business_entrypoint(
    row: str,
    monkeypatch,
) -> None:
    calls: list[dict[str, str]] = []

    def record(**kwargs):
        calls.append(dict(kwargs))
        return _success()

    monkeypatch.setattr(main, "_record_platform_spine_binding", record)
    response = _client().post(
        f"/api/research-os/platform/spine_bindings/{row}/current",
        json={"anchor_ref": f"business_anchor:{row.lower()}"},
    )

    assert response.status_code == 200, response.text
    assert calls == [
        {
            "owner_user_id": OWNER,
            "m_row": row,
            "anchor_ref": f"business_anchor:{row.lower()}",
        }
    ]
    assert response.json()["entrypoint_ref"] == (
        f"api:research_os.platform.business_attestations.{row.lower()}"
    )


def test_platform_spine_binding_route_rejects_caller_proof_refs_before_writes(
    monkeypatch,
) -> None:
    called = False

    def record(**_kwargs):
        nonlocal called
        called = True
        return _success()

    monkeypatch.setattr(main, "_record_platform_spine_binding", record)
    response = _client().post(
        "/api/research-os/platform/spine_bindings/M4-M5/current",
        json={
            "anchor_ref": "factor:platform-binding:v1",
            "qro_ref": "qro:caller-forged",
            "math_spine_ref": "math_spine_chain:caller-forged",
        },
    )

    assert response.status_code == 422, response.text
    assert "payload must contain exactly: anchor_ref" in response.text
    assert called is False


@pytest.mark.parametrize("row", ("M15", "M17", "M22", "m9"))
def test_platform_spine_binding_route_rejects_rows_without_this_cycle(
    monkeypatch,
    row: str,
) -> None:
    called = False

    def record(**_kwargs):
        nonlocal called
        called = True
        return _success()

    monkeypatch.setattr(main, "_record_platform_spine_binding", record)
    response = _client().post(
        f"/api/research-os/platform/spine_bindings/{row}/current",
        json={"anchor_ref": "business:anchor"},
    )

    assert response.status_code == 422, response.text
    assert called is False


@pytest.mark.parametrize(
    ("phase", "expected_state"),
    (
        ("compiler_coverage", "unverified_after_failure"),
        ("policy_replay", "persisted_refs_returned_but_policy_replay_failed"),
    ),
)
def test_platform_spine_binding_route_reports_partial_append_only_state(
    monkeypatch,
    phase: str,
    expected_state: str,
) -> None:
    def record(**_kwargs):
        raise QROSpineBindingCommitError(
            "binding stopped",
            phase=phase,
            graph_binding_current=True,
            graph_command_ref="rgcmd:current-binding",
            graph_command_created=True,
        )

    monkeypatch.setattr(main, "_record_platform_spine_binding", record)
    response = _client().post(
        "/api/research-os/platform/spine_bindings/M9/current",
        json={"anchor_ref": "execution_closure_receipt:m9"},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["phase"] == phase
    assert detail["graph_binding_current"] is True
    assert detail["graph_command_ref"] == "rgcmd:current-binding"
    assert detail["graph_command_created"] is True
    assert detail["compiler_state"] == expected_state
    assert detail["policy_replay_current"] is False


def test_platform_spine_binding_policy_failure_never_claims_compiler_rollback(
    monkeypatch,
) -> None:
    def record(**_kwargs):
        raise QROSpineBindingCommitError(
            "binding policy replay stopped after compiler persistence",
            phase="policy_replay",
            graph_binding_current=False,
            graph_command_ref="rgcmd:not-current-binding",
            graph_command_created=True,
        )

    monkeypatch.setattr(main, "_record_platform_spine_binding", record)
    response = _client().post(
        "/api/research-os/platform/spine_bindings/M9/current",
        json={"anchor_ref": "execution_closure_receipt:m9"},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["graph_binding_current"] is False
    assert detail["compiler_state"] == (
        "persisted_refs_returned_but_policy_replay_failed"
    )
    assert "rolled_back" not in detail["compiler_state"]


class _TypedRegistrySpy:
    def __init__(self, **rows) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple, dict]] = []

    def _row(self, method: str, args: tuple, kwargs: dict):
        self.calls.append((method, args, kwargs))
        return self.rows[method]

    def hypothesis_envelope(self, *args, **kwargs):
        return self._row("hypothesis_envelope", args, kwargs)

    def factor_envelope(self, *args, **kwargs):
        return self._row("factor_envelope", args, kwargs)

    def portfolio_policy(self, *args, **kwargs):
        return self._row("portfolio_policy", args, kwargs)

    def dataset(self, *args, **kwargs):
        return self._row("dataset", args, kwargs)

    def passport(self, *args, **kwargs):
        return self._row("passport", args, kwargs)

    def get_job(self, *args, **kwargs):
        return self._row("get_job", args, kwargs)

    def receipt(self, *args, **kwargs):
        return self._row("receipt", args, kwargs)

    def current_receipt(self, *args, **kwargs):
        return self._row("current_receipt", args, kwargs)

    def intent(self, *args, **kwargs):
        return self._row("intent", args, kwargs)

    def monitor(self, *args, **kwargs):
        return self._row("monitor", args, kwargs)

    def attribution(self, *args, **kwargs):
        return self._row("attribution", args, kwargs)

    def transition(self, *args, **kwargs):
        return self._row("transition", args, kwargs)

    def receipts(self, *args, **kwargs):
        return self._row("receipts", args, kwargs)

    def validate_current(self, *args, **kwargs):
        return self._row("validate_current", args, kwargs)

    def promotion_gate(self, *args, **kwargs):
        return self._row("promotion_gate", args, kwargs)

    def resolve_terminal_record(self, *args, **kwargs):
        return self._row("resolve_terminal_record", args, kwargs)

    def binding_for_terminal(self, *args, **kwargs):
        return self._row("binding_for_terminal", args, kwargs)

    def shared_asset(self, *args, **kwargs):
        return self._row("shared_asset", args, kwargs)

    def permission(self, *args, **kwargs):
        return self._row("permission", args, kwargs)

    def source(self, *args, **kwargs):
        return self._row("source", args, kwargs)

    def status(self, *args, **kwargs):
        return self._row("status", args, kwargs)

    def governed_asset(self, *args, **kwargs):
        return self._row("governed_asset", args, kwargs)

    def governed_asset_by_mock_label_ref(self, *args, **kwargs):
        return self._row("governed_asset_by_mock_label_ref", args, kwargs)

    def governed_asset_by_category_ref(self, *args, **kwargs):
        return self._row("governed_asset_by_category_ref", args, kwargs)

    def tutorial_asset(self, *args, **kwargs):
        return self._row("tutorial_asset", args, kwargs)

    def bundles(self, *args, **kwargs):
        return self._row("bundles", args, kwargs)


class _CurrentQROGraph:
    def __init__(self, qro: QRORecord, *, decoy: QRORecord | None = None) -> None:
        self.qro_row = qro
        self.qro_rows = {
            item.qro_id: item
            for item in ((decoy,) if decoy is not None else ()) + (qro,)
        }
        self.expected_qro_refs = tuple(self.qro_rows)
        self.calls: list[tuple[str, tuple, dict]] = []

    def projection_index(self, *args, **kwargs):
        self.calls.append(("projection_index", args, kwargs))
        return [SimpleNamespace(qro_id=qro_ref) for qro_ref in self.qro_rows]

    def qro(self, *args, **kwargs):
        self.calls.append(("qro", args, kwargs))
        if len(args) != 1 or args[0] not in self.qro_rows:
            raise KeyError(args[0])
        return self.qro_rows[args[0]]


def _binding_test_qro(
    *,
    qro_ref: str,
    qro_type: QROType = QROType.QUANT_INTENT,
    input_contract: dict | None = None,
    output_contract: dict | None = None,
    mathematical_refs: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
) -> QRORecord:
    return QRORecord(
        qro_type=qro_type,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract=input_contract or {"anchor_ref": f"anchor:{qro_ref}"},
        output_contract=output_contract or {"result_ref": f"result:{qro_ref}"},
        market="paper",
        universe="platform-binding",
        horizon="event",
        frequency="event",
        lineage=(f"lineage:{qro_ref}",),
        implementation_hash=f"implementation:{qro_ref}:v1",
        assumptions=("The typed business record is already persisted.",),
        known_limits=("This test does not persist the binding.",),
        failure_modes=("A stale typed record fails closed.",),
        validation_plan=("Resolve the exact owner-scoped typed record.",),
        mathematical_refs=mathematical_refs,
        evidence_refs=evidence_refs,
        qro_id=qro_ref,
    )


def _derive_case(row: str, monkeypatch):
    anchor = f"anchor:{row.lower().replace('-', '_')}"
    qro_ref = f"qro:{row.lower().replace('-', '_')}"
    graph = None
    graph_reloads = 0
    expected_calls: list[tuple[_TypedRegistrySpy, list[tuple]]] = []

    if row == "M1-M2":
        anchor = "hypothesis_card:m1_m2"
        envelope = SimpleNamespace(
            owner_user_id=OWNER,
            hypothesis_card_ref=anchor,
            linkage=SimpleNamespace(qro_ref=qro_ref),
            strategy_goal_ref="strategy_goal:m1_m2",
            universe_definition_ref="universe_definition:m1_m2",
            regime_scenario_ref="regime_scenario:m1_m2",
        )
        registry = _TypedRegistrySpy(hypothesis_envelope=envelope)
        monkeypatch.setattr(main, "RESEARCH_DESIGN_ASSET_REGISTRY", registry)
        expected_calls.append(
            (
                registry,
                [("hypothesis_envelope", (anchor,), {"owner_user_id": OWNER})],
            )
        )
        constraints = {
            "union_contains_refs": (
                (
                    ("validation_refs", "evidence_refs"),
                    (
                        envelope.strategy_goal_ref,
                        anchor,
                        envelope.universe_definition_ref,
                        envelope.regime_scenario_ref,
                    ),
                ),
            )
        }
    elif row == "M3":
        anchor = "dataset:m3"
        dataset = SimpleNamespace(dataset_ref=anchor)
        dataset.to_dict = lambda: {"dataset_ref": anchor, "field": "close"}
        registry = _TypedRegistrySpy(dataset=dataset)
        monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", registry)
        expected_calls.append(
            (registry, [("dataset", (anchor,), {"owner_user_id": OWNER})])
        )
        graph = _CurrentQROGraph(
            _binding_test_qro(
                qro_ref=qro_ref,
                qro_type=QROType.DATASET,
                input_contract={"record_hash": main.content_hash(dataset.to_dict())},
                output_contract={"dataset_ref": anchor},
            ),
            decoy=_binding_test_qro(
                qro_ref="qro:m3:decoy",
                qro_type=QROType.DATASET,
                input_contract={"record_hash": "record_hash:wrong"},
                output_contract={"dataset_ref": anchor},
            ),
        )
        monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
        constraints = {"scalar_refs": {"data_semantics_ref": anchor}}
    elif row == "M4-M5":
        anchor = "factor:m4_m5"
        envelope = SimpleNamespace(
            owner_user_id=OWNER,
            factor_ref=anchor,
            label_ref="label:m4_m5",
            linkage=SimpleNamespace(qro_ref=qro_ref),
        )
        registry = _TypedRegistrySpy(factor_envelope=envelope)
        monkeypatch.setattr(main, "RESEARCH_DESIGN_ASSET_REGISTRY", registry)
        expected_calls.append(
            (registry, [("factor_envelope", (anchor,), {"owner_user_id": OWNER})])
        )
        constraints = {
            "scalar_refs": {"factor_ref": anchor},
            "union_contains_refs": (
                (
                    ("validation_refs", "evidence_refs"),
                    (envelope.label_ref,),
                ),
            ),
        }
    elif row == "M6":
        anchor = "model_passport:m6"
        passport = SimpleNamespace(
            owner_user_id=OWNER,
            passport_id=anchor,
            validation_dossier_ref="validation_dossier:training-m6",
            model_version_ref="model_version:m6",
        )
        governance = _TypedRegistrySpy(passport=passport)
        job = SimpleNamespace(owner_user_id=OWNER, qro_id=qro_ref)
        training = _TypedRegistrySpy(get_job=job)
        monkeypatch.setattr(main, "MODEL_GOVERNANCE_REGISTRY", governance)
        monkeypatch.setattr(main, "TRAINING_SERVICE", training)
        expected_calls.extend(
            (
                (governance, [("passport", (anchor,), {"owner_user_id": OWNER})]),
                (training, [("get_job", ("training-m6",), {})]),
            )
        )
        constraints = {
            "scalar_one_of_refs": {
                "model_ref": (passport.model_version_ref, anchor),
            }
        }
    elif row == "M7-M8":
        anchor = "portfolio_policy:m7_m8"
        policy = SimpleNamespace(
            owner_user_id=OWNER,
            portfolio_policy_ref=anchor,
            signal_contract_ref="signal_contract:m7_m8",
            strategy_book_ref="strategy_book:m7_m8",
            linkage=SimpleNamespace(qro_ref=qro_ref),
        )
        registry = _TypedRegistrySpy(portfolio_policy=policy)
        monkeypatch.setattr(main, "RESEARCH_DESIGN_ASSET_REGISTRY", registry)
        expected_calls.append(
            (
                registry,
                [("portfolio_policy", (anchor,), {"owner_user_id": OWNER})],
            )
        )
        constraints = {
            "scalar_refs": {
                "signal_contract_ref": policy.signal_contract_ref,
                "strategy_book_ref": policy.strategy_book_ref,
                "portfolio_policy_ref": anchor,
            }
        }
    elif row == "M9":
        anchor = "execution_closure_receipt:m9"
        intent_ref = "order_intent:m9"
        receipt = SimpleNamespace(
            owner_user_id=OWNER,
            receipt_ref=anchor,
            order_intent_ref=intent_ref,
        )
        intent = SimpleNamespace(
            recorded_by=OWNER,
            order_intent_ref=intent_ref,
            risk_policy_ref="risk_policy:m9",
            execution_policy_ref="execution_policy:m9",
        )
        closures = _TypedRegistrySpy(receipt=receipt)
        intents = _TypedRegistrySpy(intent=intent)
        monkeypatch.setattr(main, "EXECUTION_CLOSURE_REGISTRY", closures)
        monkeypatch.setattr(main, "EXECUTION_ORDER_INTENTS", intents)
        expected_calls.extend(
            (
                (closures, [("receipt", (anchor,), {"owner_user_id": OWNER})]),
                (intents, [("intent", (intent_ref,), {})]),
            )
        )
        graph = _CurrentQROGraph(
            _binding_test_qro(
                qro_ref=qro_ref,
                qro_type=QROType.EXECUTION_POLICY,
                input_contract={"order_intent_ref": intent_ref},
            ),
            decoy=_binding_test_qro(
                qro_ref="qro:m9:decoy",
                qro_type=QROType.EXECUTION_POLICY,
                input_contract={"order_intent_ref": "order_intent:wrong"},
            ),
        )
        monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
        constraints = {
            "scalar_refs": {
                "risk_policy_ref": intent.risk_policy_ref,
                "execution_policy_ref": intent.execution_policy_ref,
            }
        }
    elif row == "M10":
        anchor = "backtest_monitor:m10"
        attribution = SimpleNamespace(
            recorded_by=OWNER,
            attribution_ref="backtest_attribution:m10",
        )
        monitor = SimpleNamespace(
            recorded_by=OWNER,
            monitor_ref=anchor,
            attribution_ref=attribution.attribution_ref,
            backtest_run_ref=qro_ref,
        )
        registry = _TypedRegistrySpy(monitor=monitor, attribution=attribution)
        monkeypatch.setattr(main, "BACKTEST_EVIDENCE_REGISTRY", registry)
        expected_calls.append(
            (
                registry,
                [
                    ("monitor", (anchor,), {"owner_user_id": OWNER}),
                    (
                        "attribution",
                        (attribution.attribution_ref,),
                        {"owner_user_id": OWNER},
                    ),
                ],
            )
        )
        constraints = {
            "scalar_refs": {
                "backtest_run_ref": qro_ref,
                "attribution_ref": attribution.attribution_ref,
                "monitor_ref": anchor,
            }
        }
    elif row == "M11":
        anchor = "lifecycle_transition:m11"
        receipt = SimpleNamespace(
            owner_user_id=OWNER,
            receipt_ref="lifecycle_closure_receipt:m11",
            transition_refs=(anchor, "lifecycle_transition:m11:other"),
            current_asset_refs=("governed_asset:m11", "governed_asset:m11:other"),
        )
        transition = SimpleNamespace(owner_user_id=OWNER, transition_ref=anchor)
        registry = _TypedRegistrySpy(
            transition=transition,
            receipts=(receipt,),
            validate_current=SimpleNamespace(accepted=True),
        )
        monkeypatch.setattr(main, "LIFECYCLE_TRANSITION_REGISTRY", registry)
        expected_calls.append(
            (
                registry,
                [
                    ("transition", (anchor,), {"owner_user_id": OWNER}),
                    ("receipts", (), {"owner_user_id": OWNER}),
                    (
                        "validate_current",
                        (receipt.receipt_ref,),
                        {"owner_user_id": OWNER},
                    ),
                ],
            )
        )
        graph = _CurrentQROGraph(
            _binding_test_qro(
                qro_ref=qro_ref,
                qro_type=QROType.VALIDATION_DOSSIER,
                input_contract={
                    "lifecycle_transition_refs": receipt.transition_refs,
                },
                output_contract={
                    "lifecycle_closure_receipt_ref": receipt.receipt_ref,
                },
            ),
            decoy=_binding_test_qro(
                qro_ref="qro:m11:decoy",
                qro_type=QROType.VALIDATION_DOSSIER,
                input_contract={"lifecycle_transition_refs": (anchor,)},
                output_contract={
                    "lifecycle_closure_receipt_ref": receipt.receipt_ref,
                },
            ),
        )
        monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
        constraints = {
            "union_contains_refs": (
                (
                    ("validation_refs", "evidence_refs"),
                    (anchor, receipt.receipt_ref, receipt.current_asset_refs[0]),
                ),
            )
        }
    elif row == "M16":
        strategy = SharedStrategy(
            share_id="share-m16-binding",
            run_id="run-m16-binding",
            author_id=OWNER,
            title="M16 governed shared strategy",
            asset_class="equity_cn",
            public=True,
            created_at_utc="2026-07-13T00:00:00+00:00",
        )
        anchor = main.shared_strategy_asset_ref(strategy)
        permission = main.shared_strategy_permission(strategy)
        source = main.shared_strategy_source(strategy)
        status = main.shared_strategy_status(strategy)
        evidence_refs = (
            anchor,
            permission.permission_ref,
            source.source_ref,
            status.status_ref,
        )
        lifecycle = SimpleNamespace(
            owner_user_id=OWNER,
            asset_ref=anchor,
            asset_type="SharedStrategy",
            category="user_asset",
            evidence_refs=evidence_refs[1:],
        )
        sharing = _TypedRegistrySpy(
            shared_asset=strategy,
            permission=permission,
            source=source,
            status=status,
        )
        lifecycles = _TypedRegistrySpy(governed_asset=lifecycle)
        monkeypatch.setattr(main, "SHARING_SERVICE", sharing)
        monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycles)
        expected_calls.extend(
            (
                (
                    sharing,
                    [
                        ("shared_asset", (anchor,), {"owner_user_id": OWNER}),
                        (
                            "permission",
                            (permission.permission_ref,),
                            {"owner_user_id": OWNER},
                        ),
                        (
                            "source",
                            (source.source_ref,),
                            {"owner_user_id": OWNER},
                        ),
                        (
                            "status",
                            (status.status_ref,),
                            {"owner_user_id": OWNER},
                        ),
                    ],
                ),
                (
                    lifecycles,
                    [("governed_asset", (anchor,), {"owner_user_id": OWNER})],
                ),
            )
        )
        graph = _CurrentQROGraph(
            _binding_test_qro(
                qro_ref=qro_ref,
                qro_type=QROType.STRATEGY_BOOK,
                input_contract={
                    "shared_asset_ref": anchor,
                    "permission_ref": permission.permission_ref,
                    "source_ref": source.source_ref,
                },
                output_contract={"status_ref": status.status_ref},
                evidence_refs=evidence_refs,
            ),
            decoy=_binding_test_qro(
                qro_ref="qro:m16:decoy",
                qro_type=QROType.STRATEGY_BOOK,
                input_contract={
                    "shared_asset_ref": anchor,
                    "permission_ref": "permission:wrong",
                    "source_ref": source.source_ref,
                },
                output_contract={"status_ref": status.status_ref},
            ),
        )
        monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
        graph_reloads = 1
        constraints = {
            "union_contains_refs": (
                (("validation_refs", "evidence_refs"), evidence_refs),
            )
        }
    elif row == "M19":
        anchor = "tutorial_asset:m19-binding"
        governed_ref = "governed_asset:m19-binding"
        tutorial = SimpleNamespace(
            owner_user_id=OWNER,
            tutorial_asset_ref=anchor,
            governed_asset_ref=governed_ref,
            category="tutorial",
        )
        weakness = SimpleNamespace(
            owner_user_id=OWNER,
            tutorial_asset_ref=anchor,
            weakness_disclosure_ref="weakness_disclosure:m19-binding",
            visible_by_default=True,
        )
        evidence = SimpleNamespace(
            owner_user_id=OWNER,
            tutorial_asset_ref=anchor,
            weakness_disclosure_ref=weakness.weakness_disclosure_ref,
            teaching_evidence_ref="teaching_evidence:m19-binding",
        )
        bundle = SimpleNamespace(
            tutorial=tutorial,
            weakness=weakness,
            evidence=evidence,
        )
        lifecycle = SimpleNamespace(
            owner_user_id=OWNER,
            asset_ref=governed_ref,
            asset_type="TeachingAsset",
            category="tutorial",
        )
        evidence_refs = (
            anchor,
            weakness.weakness_disclosure_ref,
            evidence.teaching_evidence_ref,
            governed_ref,
        )
        teaching = _TypedRegistrySpy(
            tutorial_asset=tutorial,
            bundles=(bundle,),
        )
        lifecycles = _TypedRegistrySpy(governed_asset=lifecycle)
        monkeypatch.setattr(main, "TEACHING_ASSET_REGISTRY", teaching)
        monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycles)
        expected_calls.extend(
            (
                (
                    teaching,
                    [
                        ("tutorial_asset", (anchor,), {"owner_user_id": OWNER}),
                        ("bundles", (), {"owner_user_id": OWNER}),
                    ],
                ),
                (
                    lifecycles,
                    [
                        (
                            "governed_asset",
                            (governed_ref,),
                            {"owner_user_id": OWNER},
                        )
                    ],
                ),
            )
        )
        graph = _CurrentQROGraph(
            _binding_test_qro(
                qro_ref=qro_ref,
                qro_type=QROType.DOCUMENT_ARTIFACT,
                input_contract={
                    "tutorial_asset_ref": anchor,
                    "weakness_disclosure_ref": weakness.weakness_disclosure_ref,
                    "teaching_evidence_ref": evidence.teaching_evidence_ref,
                    "governed_asset_ref": governed_ref,
                },
                evidence_refs=evidence_refs,
            ),
            decoy=_binding_test_qro(
                qro_ref="qro:m19:decoy",
                qro_type=QROType.DOCUMENT_ARTIFACT,
                input_contract={
                    "tutorial_asset_ref": anchor,
                    "weakness_disclosure_ref": weakness.weakness_disclosure_ref,
                    "teaching_evidence_ref": "teaching_evidence:wrong",
                    "governed_asset_ref": governed_ref,
                },
            ),
        )
        monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
        graph_reloads = 1
        constraints = {
            "union_contains_refs": (
                (("validation_refs", "evidence_refs"), evidence_refs),
            )
        }
    elif row == "M21":
        anchor = "ide_strategy:strategy-m21-binding"
        governed_asset_ref = "governed_asset:m21-binding"
        mock_label_ref = "mock_label:m21-binding"
        asset_category_ref = "asset_category:equity_cn:m21-binding"
        lifecycle = GovernedAssetRecord(
            asset_ref=governed_asset_ref,
            asset_type="StrategyTemplate",
            category=AssetCategory.TEMPLATE,
            lifecycle_state=LifecycleState.LINKED,
            evidence_refs=("evidence:m21:binding",),
            validation_plan_ref="validation_plan:m21:binding",
            promotion_history=(),
            display_label="TEMPLATE - candidate context only",
            mock_label_ref=mock_label_ref,
            asset_category_ref=asset_category_ref,
        )
        strategy = StrategyFile(
            strategy_id=anchor.removeprefix("ide_strategy:"),
            owner_username="platform-spine-binding-owner",
            name="m21_binding",
            code="def generate_signal(ctx):\n    return 0\n",
            asset_class="equity_cn",
            description="forked from governed template",
            updated_at_utc="2026-07-13T00:00:00Z",
            market_data_use_validation_refs=[],
        )
        monkeypatch.setattr(
            main,
            "AUTH_SERVICE",
            SimpleNamespace(
                get_user_by_id=lambda owner: (
                    SimpleNamespace(
                        user_id=OWNER,
                        username=strategy.owner_username,
                    )
                    if owner == OWNER
                    else None
                )
            ),
        )
        monkeypatch.setattr(
            main,
            "IDE_SERVICE",
            SimpleNamespace(
                get_strategy_by_id=lambda strategy_id: (
                    strategy
                    if strategy_id == strategy.strategy_id
                    else (_ for _ in ()).throw(KeyError(strategy_id))
                )
            ),
        )
        evidence_refs = (
            anchor,
            governed_asset_ref,
            mock_label_ref,
            asset_category_ref,
        )
        lifecycles = _TypedRegistrySpy(
            governed_asset=lifecycle,
            governed_asset_by_mock_label_ref=lifecycle,
            governed_asset_by_category_ref=lifecycle,
        )
        monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycles)
        expected_calls.append(
            (
                lifecycles,
                [
                    (
                        "governed_asset",
                        (governed_asset_ref,),
                        {"owner_user_id": OWNER},
                    ),
                    (
                        "governed_asset",
                        (governed_asset_ref,),
                        {"owner_user_id": OWNER},
                    ),
                    (
                        "governed_asset_by_mock_label_ref",
                        (mock_label_ref,),
                        {"owner_user_id": OWNER},
                    ),
                    (
                        "governed_asset_by_category_ref",
                        (asset_category_ref,),
                        {"owner_user_id": OWNER},
                    ),
                ],
            )
        )
        graph = _CurrentQROGraph(
            _binding_test_qro(
                qro_ref=qro_ref,
                qro_type=QROType.STRATEGY_BOOK,
                input_contract={
                    "entry_source": "api",
                    "governed_asset_ref": governed_asset_ref,
                },
                output_contract={
                    "ide_strategy_ref": anchor,
                    "ide_strategy_snapshot_hash": (
                        m21_ide_strategy_snapshot_hash(strategy)
                    ),
                    "governed_template_snapshot_hash": (
                        m21_governed_template_snapshot_hash(lifecycle)
                    ),
                    "mock_label_ref": mock_label_ref,
                    "asset_category_ref": asset_category_ref,
                    "status": "template_fork_recorded",
                },
                evidence_refs=evidence_refs,
            ),
            decoy=_binding_test_qro(
                qro_ref="qro:m21:decoy",
                qro_type=QROType.STRATEGY_BOOK,
                input_contract={
                    "entry_source": "api",
                    "governed_asset_ref": governed_asset_ref,
                },
                output_contract={
                    "ide_strategy_ref": "ide_strategy:strategy-m21-decoy",
                    "ide_strategy_snapshot_hash": (
                        "sha256:m21-decoy-strategy"
                    ),
                    "governed_template_snapshot_hash": (
                        m21_governed_template_snapshot_hash(lifecycle)
                    ),
                    "mock_label_ref": "mock_label:wrong",
                    "asset_category_ref": asset_category_ref,
                    "status": "template_fork_recorded",
                },
            ),
        )
        monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
        graph_reloads = 1
        constraints = {
            "union_contains_refs": (
                (("validation_refs", "evidence_refs"), evidence_refs),
            )
        }
    elif row == "M13":
        anchor = "agent_workflow_closure_receipt:m13"
        workflow = "agent_workflow:m13"
        snapshot = SimpleNamespace(
            owner_user_id=OWNER,
            workflow_id=workflow,
            qro=SimpleNamespace(component_ref=qro_ref),
        )
        receipt = SimpleNamespace(
            owner_user_id=OWNER,
            receipt_ref=anchor,
            workflow_id=workflow,
            snapshot=snapshot,
        )
        registry = _TypedRegistrySpy(receipt=receipt, current_receipt=receipt)
        monkeypatch.setattr(main, "AGENT_WORKFLOW_CLOSURE_REGISTRY", registry)
        expected_calls.append(
            (
                registry,
                [
                    ("receipt", (anchor,), {"owner_user_id": OWNER}),
                    (
                        "current_receipt",
                        (),
                        {"owner_user_id": OWNER, "workflow_id": workflow},
                    ),
                ],
            )
        )
        constraints = {
            "union_contains_refs": (
                (("validation_refs", "evidence_refs"), (anchor,)),
            )
        }
    elif row == "M14":
        call_ref = "llm_call:m14"
        anchor = f"llm_gateway:{call_ref}"
        workflow = "agent_workflow:m14"
        binding_ref = "llm_use_binding:m14"
        receipt_ref = "agent_workflow_closure_receipt:m14"
        terminal = SimpleNamespace(
            owner_user_id=OWNER,
            call_id=call_ref,
            record_kind="terminal",
            status="ok",
        )
        binding = SimpleNamespace(
            owner_user_id=OWNER,
            binding_ref=binding_ref,
            workflow_id=workflow,
            terminal_call_id=call_ref,
            terminal_status="ok",
        )
        snapshot = SimpleNamespace(
            owner_user_id=OWNER,
            workflow_id=workflow,
            qro=SimpleNamespace(component_ref=qro_ref),
            terminal_calls=(SimpleNamespace(component_ref=call_ref),),
            llm_use_bindings=(SimpleNamespace(component_ref=binding_ref),),
        )
        receipt = SimpleNamespace(
            owner_user_id=OWNER,
            receipt_ref=receipt_ref,
            workflow_id=workflow,
            snapshot=snapshot,
        )
        calls = _TypedRegistrySpy(resolve_terminal_record=terminal)
        bindings = _TypedRegistrySpy(
            binding_for_terminal=binding,
            validate_current=SimpleNamespace(accepted=True),
        )
        workflows = _TypedRegistrySpy(current_receipt=receipt)
        monkeypatch.setattr(main, "LLM_CALL_RECORD_STORE", calls)
        monkeypatch.setattr(main, "LLM_USE_BINDING_STORE", bindings)
        monkeypatch.setattr(main, "AGENT_WORKFLOW_CLOSURE_REGISTRY", workflows)
        expected_calls.extend(
            (
                (calls, [("resolve_terminal_record", (call_ref, OWNER), {})]),
                (
                    bindings,
                    [
                        (
                            "binding_for_terminal",
                            (call_ref,),
                            {"owner_user_id": OWNER},
                        ),
                        (
                            "validate_current",
                            (binding_ref,),
                            {"owner_user_id": OWNER},
                        ),
                    ],
                ),
                (
                    workflows,
                    [
                        (
                            "current_receipt",
                            (),
                            {"owner_user_id": OWNER, "workflow_id": workflow},
                        )
                    ],
                ),
            )
        )
        constraints = {
            "union_contains_refs": (
                (
                    ("validation_refs", "evidence_refs"),
                    (receipt_ref, anchor, binding_ref),
                ),
            )
        }
    else:
        assert row == "M12"
        anchor = "promotion_gate:m12"
        passport_ref = "model_passport:m12"
        passport = SimpleNamespace(
            owner_user_id=OWNER,
            passport_id=passport_ref,
            model_version_ref="model_version:m12",
        )
        gate = SimpleNamespace(
            evidence={
                "owner_user_id": OWNER,
                "logical_model_id": "logical_model:m12",
                "model_passport_ref": passport_ref,
                "model_recertification_record_refs": (
                    "model_recertification:m12",
                ),
            }
        )
        models = _TypedRegistrySpy(promotion_gate=gate)
        governance = _TypedRegistrySpy(passport=passport)
        monkeypatch.setattr(main, "MODEL_REGISTRY", models)
        monkeypatch.setattr(main, "MODEL_GOVERNANCE_REGISTRY", governance)
        expected_calls.extend(
            (
                (
                    models,
                    [("promotion_gate", (anchor,), {"owner_user_id": OWNER})],
                ),
                (
                    governance,
                    [("passport", (passport_ref,), {"owner_user_id": OWNER})],
                ),
            )
        )
        graph = _CurrentQROGraph(
            _binding_test_qro(
                qro_ref=qro_ref,
                qro_type=QROType.MODEL,
                input_contract={
                    "gate_id": anchor,
                    "model": gate.evidence["logical_model_id"],
                    "model_version_ref": passport.model_version_ref,
                },
            ),
            decoy=_binding_test_qro(
                qro_ref="qro:m12:decoy",
                qro_type=QROType.MODEL,
                input_contract={
                    "gate_id": "promotion_gate:wrong",
                    "model": gate.evidence["logical_model_id"],
                    "model_version_ref": passport.model_version_ref,
                },
            ),
        )
        monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
        constraints = {
            "scalar_one_of_refs": {
                "model_ref": (passport.model_version_ref, passport_ref),
            },
            "union_contains_refs": (
                (
                    ("validation_refs", "evidence_refs"),
                    (
                        anchor,
                        passport_ref,
                        gate.evidence["model_recertification_record_refs"][0],
                    ),
                ),
            ),
        }

    return SimpleNamespace(
        anchor=anchor,
        qro_ref=qro_ref,
        graph=graph,
        expected_calls=expected_calls,
        constraints=constraints,
        graph_reloads=graph_reloads,
    )


@pytest.mark.parametrize(
    "row",
    (
        "M1-M2",
        "M3",
        "M4-M5",
        "M6",
        "M7-M8",
        "M9",
        "M10",
        "M11",
        "M12",
        "M13",
        "M14",
        "M16",
        "M19",
        "M21",
    ),
)
def test_derive_platform_spine_binding_subject_uses_exact_typed_branch(
    monkeypatch,
    row: str,
) -> None:
    assert set(main._PLATFORM_SPINE_BINDING_ENTRYPOINTS) == {
        "M1-M2",
        "M3",
        "M4-M5",
        "M6",
        "M7-M8",
        "M9",
        "M10",
        "M11",
        "M12",
        "M13",
        "M14",
        "M16",
        "M19",
        "M21",
    }
    case = _derive_case(row, monkeypatch)
    chain_registry = object()
    chain = SimpleNamespace(
        chain_ref=f"math_spine_chain:{row.lower().replace('-', '_')}",
        recorded_by=OWNER,
    )
    resolver_calls: list[tuple[object, dict]] = []

    def resolve(registry, **kwargs):
        resolver_calls.append((registry, kwargs))
        return chain

    monkeypatch.setattr(main, "MATHEMATICAL_SPINE_CHAIN_REGISTRY", chain_registry)
    monkeypatch.setattr(main, "resolve_unique_verified_spine_chain", resolve)

    qro_ref, derived_chain = main._derive_platform_spine_binding_subject(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=case.anchor,
    )

    assert qro_ref == case.qro_ref
    assert derived_chain is chain
    assert resolver_calls == [
        (
            chain_registry,
            {"owner_user_id": OWNER, **case.constraints},
        )
    ]
    for registry, expected in case.expected_calls:
        assert registry.calls == expected
    if case.graph is not None:
        assert case.graph.calls == [
            ("projection_index", (), {"owner": OWNER}),
            *(
                ("qro", (qro_ref,), {})
                for qro_ref in case.graph.expected_qro_refs
            ),
            *(("qro", (case.qro_ref,), {}) for _ in range(case.graph_reloads)),
        ]


class _EmptyBindingGraph:
    def commands(self):
        return []

    def projection_index(self, **_filters):
        return []

    def qro(self, qro_ref: str):
        raise KeyError(qro_ref)


class _EmptyBindingCompiler:
    def canonical_records(self, *, owner: str):
        return SimpleNamespace(owner=owner, irs=(), passes=(), artifacts=())

    def canonical_ir(self, ref: str, *, owner: str):
        raise KeyError((ref, owner))

    def canonical_compiler_pass(self, ref: str, *, owner: str):
        raise KeyError((ref, owner))

    def irs(self, *, owner: str):
        return []

    def passes(self, *, owner: str):
        return []

    def ir(self, ref: str, *, owner: str):
        raise KeyError((ref, owner))

    def compiler_pass(self, ref: str, *, owner: str):
        raise KeyError((ref, owner))


@pytest.mark.parametrize(
    ("row", "entrypoint_ref"),
    tuple(main._PLATFORM_SPINE_BINDING_ENTRYPOINTS.items()),
)
def test_preflight_platform_spine_binding_builds_exact_provenance_overlay(
    monkeypatch,
    row: str,
    entrypoint_ref: str,
) -> None:
    row_token = row.lower().replace("-", "_")
    qro_ref = f"qro:preflight:{row_token}"
    chain_ref = f"math_spine_chain:preflight:{row_token}"
    anchor_ref = f"business_anchor:{row_token}"
    if row == "M21":
        anchor_ref = f"ide_strategy:preflight:{row_token}"
    governed_asset_ref = f"governed_asset:preflight:{row_token}"
    historical_qro = _binding_test_qro(
        qro_ref=qro_ref,
        input_contract={
            **(
                {
                    "entry_source": "api",
                    "governed_asset_ref": governed_asset_ref,
                }
                if row == "M21"
                else {"anchor_ref": anchor_ref}
            ),
            **(
                {"governed_asset_ref": governed_asset_ref}
                if row == "M19"
                else {}
            ),
        },
        output_contract=(
            {
                "ide_strategy_ref": anchor_ref,
                "ide_strategy_snapshot_hash": (
                    f"snapshot:ide:{row_token}"
                ),
                "governed_template_snapshot_hash": (
                    f"snapshot:template:{row_token}"
                ),
                "mock_label_ref": f"mock_label:preflight:{row_token}",
                "asset_category_ref": f"asset_category:preflight:{row_token}",
                "status": "template_fork_recorded",
            }
            if row == "M21"
            else None
        ),
    )
    bound_qro = replace(historical_qro, mathematical_refs=(chain_ref,))
    historical_command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": historical_qro},
        evidence_refs=(f"business_evidence:{row_token}",),
        tool_record_refs=(f"api:business:{row_token}",),
    )
    plan = SimpleNamespace(
        owner_user_id=OWNER,
        qro_ref=qro_ref,
        chain_ref=chain_ref,
        current_qro=historical_qro,
        bound_qro=bound_qro,
        prior_projection=SimpleNamespace(
            qro_id=qro_ref,
            command_id=historical_command.command_id,
            owner=OWNER,
        ),
        prior_command=historical_command,
        already_bound=False,
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", _EmptyBindingGraph())
    monkeypatch.setattr(main, "COMPILER_IR_STORE", _EmptyBindingCompiler())
    monkeypatch.setattr(
        main,
        "_fresh_platform_compiler_view",
        lambda: _EmptyBindingCompiler(),
    )
    chain = SimpleNamespace(
        chain_ref=chain_ref,
        recorded_by=OWNER,
        validation_refs=(f"validation:preflight:{row_token}",),
        evidence_refs=(f"evidence:preflight:{row_token}",),
        theory_binding_refs=(f"tbind:preflight:{row_token}",),
        consistency_check_refs=(f"ccheck:preflight:{row_token}",),
    )
    monkeypatch.setattr(
        main,
        "MATHEMATICAL_SPINE_CHAIN_REGISTRY",
        _M16M21Spines(chain),
    )

    class EmptyEntrypoints:
        canonical_projection_available = True

        def records(self, *, owner=None):
            return []

        def canonical_records(self, *, owner):
            return ()

        def canonical_coverage(self, ref, *, owner):
            raise KeyError((ref, owner))

        def validate_real_backing(self, _record):
            raise AssertionError("only the synthetic coverage may be validated")

    monkeypatch.setattr(
        main,
        "_fresh_platform_entrypoint_coverage_view",
        EmptyEntrypoints,
    )
    builder_calls: list[tuple[str, object, object, object]] = []

    class Resolver:
        def __init__(self, graph, compiler, entrypoints) -> None:
            self.graph = graph
            self.compiler = compiler
            self.entrypoints = entrypoints

        def resolve(self, **kwargs):
            assert kwargs == {
                "owner_user_id": OWNER,
                "m_row": row,
                "anchor_ref": anchor_ref,
            }
            assert self.graph.qro(qro_ref) == bound_qro
            commands = self.graph.commands()
            assert len(commands) == 1
            command = commands[0]
            assert command.source == EntrySource.API
            assert command.command_type == "upsert_qro"
            assert command.actor_source == ActorSource.USER_MANUAL
            assert command.actor == OWNER
            assert command.payload == {"qro": bound_qro}
            assert command.payload["qro"].mathematical_refs == (chain_ref,)
            assert command.evidence_refs == (
                chain_ref,
                historical_command.command_id,
            )
            assert command.tool_record_refs == (entrypoint_ref,)
            projections = self.graph.projection_index(
                owner=OWNER,
                qro_type=QROType.QUANT_INTENT.value,
            )
            assert len(projections) == 1
            assert projections[0].qro_id == qro_ref
            assert projections[0].command_id == command.command_id
            assert projections[0].mathematical_refs == (chain_ref,)
            irs = self.compiler.irs(owner=OWNER)
            passes = self.compiler.passes(owner=OWNER)
            assert len(irs) == 1
            assert len(passes) == 1
            ir = irs[0]
            compiler_pass = passes[0]
            assert ir.source_qro_refs == (qro_ref,)
            assert ir.graph_command_refs == (command.command_id,)
            assert ir.mathematical_spine_chain_refs == (chain_ref,)
            if row in {"M16", "M19", "M21"}:
                assert ir.canonical_command_refs == (
                    f"research_graph_command:{command.command_id}",
                    anchor_ref,
                    chain_ref,
                    f"entrypoint:{entrypoint_ref}",
                )
            else:
                assert ir.canonical_command_refs == (
                    f"research_graph_command:{command.command_id}",
                    f"entrypoint:{entrypoint_ref}",
                )
            assert compiler_pass.output_ir_ref == ir.ir_ref
            assert compiler_pass.input_qro_refs == (qro_ref,)
            assert compiler_pass.graph_command_refs == (command.command_id,)
            assert compiler_pass.canonical_command_refs == ir.canonical_command_refs
            assert compiler_pass.entry_source == EntrySource.API.value
            assert compiler_pass.status == "compiled"
            if row in {"M16", "M19", "M21"}:
                assert compiler_pass.input_ir_refs == ()
                assert compiler_pass.actor_source == ActorSource.USER_MANUAL
                assert compiler_pass.tool_record_refs == (
                    entrypoint_ref,
                    anchor_ref,
                    chain_ref,
                    "api:compile_qro",
                )
                assert compiler_pass.permission_ref == (
                    f"platform.spine_binding:{row_token}:user_manual"
                )
                rows = self.entrypoints.records(owner=OWNER)
                assert len(rows) == 1
                coverage = rows[0]
                assert coverage.entrypoint_ref == entrypoint_ref
                assert coverage.qro_refs == (qro_ref,)
                assert coverage.research_graph_command_refs == (
                    command.command_id,
                )
                assert coverage.compiler_ir_refs == (ir.ir_ref,)
                assert coverage.compiler_pass_refs == (compiler_pass.pass_ref,)
                assert coverage.goal_sections == (
                    main._PLATFORM_SPINE_BINDING_GOAL_SECTIONS[row]
                )
                assert coverage.lifecycle_refs == (
                    (governed_asset_ref,)
                    if row in {"M19", "M21"}
                    else (anchor_ref,)
                )
                assert (
                    self.entrypoints.validate_real_backing(coverage).accepted
                    is True
                )
            return SimpleNamespace(
                qro_ref=qro_ref,
                math_spine_ref=chain_ref,
                business_entry_source=EntrySource.API.value,
                business_entrypoint_ref=entrypoint_ref,
                lifecycle_ref=(
                    governed_asset_ref
                    if row in {"M19", "M21"}
                    else anchor_ref
                ),
                specific_refs=(),
            )

    def build_resolver(*, m_row, graph, compiler, entrypoints=None):
        builder_calls.append((m_row, graph, compiler, entrypoints))
        return Resolver(graph, compiler, entrypoints)

    monkeypatch.setattr(
        main,
        "_build_platform_binding_preflight_resolver",
        build_resolver,
    )

    resolution = main._preflight_platform_spine_binding(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=anchor_ref,
        qro_ref=qro_ref,
        chain=chain,
        plan=plan,
    )

    assert resolution.qro_ref == qro_ref
    assert resolution.math_spine_ref == chain_ref
    assert resolution.business_entrypoint_ref == entrypoint_ref
    assert len(builder_calls) == 1
    assert builder_calls[0][0] == row
    assert (builder_calls[0][3] is not None) is (
        row in {"M16", "M19", "M21"}
    )


def test_record_platform_spine_binding_reports_observed_stale_graph_after_replay_failure(
    monkeypatch,
) -> None:
    row = "M9"
    entrypoint_ref = main._PLATFORM_SPINE_BINDING_ENTRYPOINTS[row]
    qro_ref = "qro:policy-replay-stale"
    chain_ref = "math_spine_chain:policy-replay-stale"
    graph_command_ref = "rgcmd:policy-replay-stale"
    chain = SimpleNamespace(
        chain_ref=chain_ref,
        recorded_by=OWNER,
        validation_refs=(),
        evidence_refs=(),
    )
    result = SimpleNamespace(
        qro_ref=qro_ref,
        chain_ref=chain_ref,
        graph_command_ref=graph_command_ref,
        graph_command_created=True,
        compiler_ir_ref="compiler_ir:policy-replay-stale",
        compiler_pass_ref="compiler_pass:policy-replay-stale",
        entrypoint_coverage_ref="goal_entrypoint_coverage:policy-replay-stale",
    )
    preflight = SimpleNamespace(
        qro_ref=qro_ref,
        math_spine_ref=chain_ref,
        business_entry_source=EntrySource.API.value,
        business_entrypoint_ref=entrypoint_ref,
        lifecycle_ref="governed_asset:policy-replay-stale",
        specific_refs=(),
    )
    monkeypatch.setattr(
        main,
        "_derive_platform_spine_binding_subject",
        lambda **_kwargs: (qro_ref, chain),
    )
    monkeypatch.setattr(
        main,
        "MATHEMATICAL_SPINE_CHAIN_REGISTRY",
        SimpleNamespace(
            verified_chain_record_refs=lambda ref, *, owner: SimpleNamespace(
                theory_binding_refs=(),
                consistency_check_refs=(),
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "_preflight_platform_spine_binding",
        lambda **_kwargs: preflight,
    )

    def record_binding(**kwargs):
        kwargs["validate_plan"](SimpleNamespace())
        return result

    monkeypatch.setattr(main, "record_current_qro_spine_binding", record_binding)

    def fail_replay(**_kwargs):
        raise LookupError("persisted policy head is stale")

    monkeypatch.setattr(
        main,
        "PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER",
        SimpleNamespace(resolve=fail_replay),
    )
    observer_calls: list[dict] = []

    def observe(**kwargs):
        observer_calls.append(kwargs)
        return False

    monkeypatch.setattr(main, "current_qro_spine_binding_is_observed", observe)

    with pytest.raises(QROSpineBindingCommitError) as exc_info:
        main._record_platform_spine_binding(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref="execution_closure_receipt:policy-replay-stale",
        )

    error = exc_info.value
    assert error.phase == "policy_replay"
    assert error.graph_binding_current is False
    assert error.graph_command_ref == graph_command_ref
    assert error.graph_command_created is True
    assert "LookupError:persisted policy head is stale" in str(error)
    assert observer_calls == [
        {
            "research_graph_store": main.RESEARCH_GRAPH_STORE,
            "owner_user_id": OWNER,
            "qro_ref": qro_ref,
            "chain_ref": chain_ref,
            "entrypoint_ref": entrypoint_ref,
            "graph_command_ref": graph_command_ref,
        }
    ]


class _M9Spines:
    def __init__(self, owner: str, chain) -> None:
        self.owner = owner
        self.rows = [chain]

    def chains(self, *, owner: str):
        return [item for item in self.rows if item.recorded_by == owner]

    def verified_chain(self, ref: str, *, owner: str):
        matches = [
            item
            for item in self.rows
            if item.chain_ref == ref and item.recorded_by == owner
        ]
        if len(matches) != 1:
            raise KeyError(ref)
        return matches[0]

    def verified_chain_record_refs(self, ref: str, *, owner: str):
        chain = self.verified_chain(ref, owner=owner)
        return SimpleNamespace(
            theory_binding_refs=tuple(chain.theory_binding_refs),
            consistency_check_refs=tuple(chain.consistency_check_refs),
        )


class _M9Closures:
    def __init__(self, receipt) -> None:
        self.receipt_row = receipt

    def receipt(self, ref: str, *, owner_user_id: str):
        if (
            ref != self.receipt_row.receipt_ref
            or owner_user_id != self.receipt_row.owner_user_id
        ):
            raise KeyError(ref)
        return self.receipt_row

    def validate_current(self, ref: str, *, owner_user_id: str):
        return SimpleNamespace(
            accepted=(
                ref == self.receipt_row.receipt_ref
                and owner_user_id == self.receipt_row.owner_user_id
            )
        )


class _M9Intents:
    def __init__(self, intent) -> None:
        self.intent_row = intent

    def intent(self, ref: str):
        if ref != self.intent_row.order_intent_ref:
            raise KeyError(ref)
        return self.intent_row


class _M9Market:
    def __init__(self, use, matrix) -> None:
        self.use = use
        self.matrix = matrix

    def use_validation(self, ref: str, *, owner_user_id: str):
        if ref != self.use.validation_ref or owner_user_id != self.use.recorded_by:
            raise KeyError(ref)
        return self.use

    def capability_matrix(self, ref: str, *, owner_user_id: str):
        if ref != self.matrix.matrix_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.matrix


def _install_real_m9_binding_world(tmp_path, monkeypatch):
    graph_path = tmp_path / "research_graph.jsonl"
    compiler_path = tmp_path / "compiler.jsonl"
    coverage_path = tmp_path / "goal_entrypoint_coverage.jsonl"
    proof_ledger_path = tmp_path / "goal_proof_ledger"
    proof_ledger = GoalProofLedger(proof_ledger_path)
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(
        compiler_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    intent = SimpleNamespace(
        order_intent_ref="order_intent:platform-binding-m9",
        recorded_by=OWNER,
        market_data_use_validation_ref="market_data_use:platform-binding-m9",
        execution_policy_ref="execution_policy:platform-binding-m9",
        risk_policy_ref="risk_policy:platform-binding-m9",
    )
    use = SimpleNamespace(
        validation_ref=intent.market_data_use_validation_ref,
        recorded_by=OWNER,
        capability_matrix_ref="market_capability:platform-binding-m9",
        accepted=True,
        violation_codes=(),
    )
    matrix = SimpleNamespace(matrix_ref=use.capability_matrix_ref)
    receipt = SimpleNamespace(
        receipt_ref="execution_closure_receipt:platform-binding-m9",
        owner_user_id=OWNER,
        order_intent_ref=intent.order_intent_ref,
    )
    chain = SimpleNamespace(
        chain_ref="math_spine_chain:platform-binding-m9",
        recorded_by=OWNER,
        risk_policy_ref=intent.risk_policy_ref,
        execution_policy_ref=intent.execution_policy_ref,
        validation_refs=(
            use.validation_ref,
            matrix.matrix_ref,
            "validation:platform-binding-m9",
        ),
        evidence_refs=(
            receipt.receipt_ref,
            intent.order_intent_ref,
            "evidence:platform-binding-m9",
        ),
        theory_binding_refs=("tbind:platform-binding-m9",),
        consistency_check_refs=("ccheck:platform-binding-m9",),
    )
    spines = _M9Spines(OWNER, chain)
    closures = _M9Closures(receipt)
    intents = _M9Intents(intent)
    market = _M9Market(use, matrix)
    unavailable = _UnavailableM16M21Dependency()
    evidence = PersistentEntrypointEvidenceRegistry(
        compiler_path.with_name("entrypoint_evidence.jsonl"),
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )

    def lifecycle_loader(ref: str, owner: str):
        closures.receipt(ref, owner_user_id=owner)
        return SimpleNamespace(owner_user_id=owner, lifecycle_ref=ref)

    coverage.set_ref_resolver(
        main.build_real_platform_coverage_resolver(
            research_graph_store=graph,
            lifecycle_registry=unavailable,
            governance_registry=unavailable,
            rag_index=unavailable,
            spine_chain_registry=spines,
            compiler_store=compiler,
            document_store=unavailable,
            rdp_store=unavailable,
            market_data_registry=market,
            dataset_registry=unavailable,
            onboarding_registry=unavailable,
            llm_service_owner_user_id="service:llm",
            llm_call_record_store=unavailable,
            account_halt_barrier=unavailable,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=(
                CompositeEntrypointEvidenceRegistry((evidence,))
            ),
            lifecycle_loaders=(lifecycle_loader,),
        )
    )

    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)
    monkeypatch.setattr(main, "MATHEMATICAL_SPINE_CHAIN_REGISTRY", spines)
    monkeypatch.setattr(main, "EXECUTION_CLOSURE_REGISTRY", closures)
    monkeypatch.setattr(main, "EXECUTION_ORDER_INTENTS", intents)
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", market)

    qro = QRORecord(
        qro_type=QROType.EXECUTION_POLICY,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "order_intent_ref": intent.order_intent_ref,
            "market_data_use_validation_ref": use.validation_ref,
        },
        output_contract={
            "execution_policy_ref": intent.execution_policy_ref,
            "risk_policy_ref": intent.risk_policy_ref,
        },
        market="paper",
        universe="copy_trade",
        horizon="order_intent",
        frequency="event",
        lineage=(intent.order_intent_ref, use.validation_ref),
        implementation_hash="execution_policy:platform-binding-m9:v1",
        assumptions=("The order intent has already passed its typed boundary.",),
        known_limits=("This QRO does not submit an order.",),
        failure_modes=("Stale risk state invalidates the intent.",),
        validation_plan=("Revalidate execution closure and market capability.",),
        evidence_refs=(receipt.receipt_ref, intent.order_intent_ref),
        permission="execution.order_intent:user_manual",
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=("api:research_os.execution.order_intents",),
    )
    graph.apply(command)
    main._compile_entrypoint_qro(
        qro_id=qro.qro_id,
        graph_command_id=command.command_id,
        actor=OWNER,
        actor_source=ActorSource.USER_MANUAL.value,
        entry_source=EntrySource.API.value,
        entrypoint_ref="api:research_os.execution.order_intents",
        pass_name="api_execution_order_intent_qro_to_ir",
        validation_refs=(use.validation_ref,),
        evidence_refs=qro.evidence_refs,
        environment_lock_ref="env:execution_order_intent:test:v1",
        permission_ref="execution.order_intent:user_manual",
        deterministic_run_plan_ref="runplan:execution_order_intent:test",
        rollback_ref="rollback:execution_order_intent:test",
        tool_record_refs=("api:research_os.execution.order_intents",),
        node_refs=(f"qro:{qro.qro_id}", intent.order_intent_ref),
        canonical_command_refs=(
            f"research_graph_command:{command.command_id}",
            intent.order_intent_ref,
        ),
        goal_sections=("§12", "§14"),
    )
    policy = build_platform_source_lineage_policies_m9_m15(
        PlatformSourceLineagePoliciesM9M15Context(
            research_graph_store=graph,
            compiler_store=compiler,
            spine_chain_registry=spines,
            execution_closure_registry=closures,
            execution_order_intent_registry=intents,
            market_data_registry=market,
        )
    )
    monkeypatch.setattr(main, "PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER", policy)
    return SimpleNamespace(
        graph=graph,
        compiler=compiler,
        coverage=coverage,
        evidence=evidence,
        spines=spines,
        closures=closures,
        intents=intents,
        market=market,
        receipt=receipt,
        qro=qro,
        graph_path=graph_path,
        compiler_path=compiler_path,
        coverage_path=coverage_path,
        proof_ledger=proof_ledger,
        proof_ledger_path=proof_ledger_path,
    )


def test_real_persistent_m9_binding_is_current_idempotent_and_replayable(
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m9_binding_world(tmp_path, monkeypatch)

    first, resolution = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row="M9",
        anchor_ref=world.receipt.receipt_ref,
    )

    assert first.graph_command_created is True
    assert resolution.business_entrypoint_ref == (
        "api:research_os.platform.spine_bindings.m9"
    )
    assert world.graph.qro(world.qro.qro_id).mathematical_refs == (
        "math_spine_chain:platform-binding-m9",
    )
    binding_coverage = world.coverage.coverage(
        first.entrypoint_coverage_ref,
        owner=OWNER,
    )
    assert "§14" not in set(binding_coverage.goal_sections)
    command_count = len(world.graph.commands())
    ir_count = len(world.compiler.irs(owner=OWNER))
    pass_count = len(world.compiler.passes(owner=OWNER))
    coverage_count = len(world.coverage.records(owner=OWNER))

    second, replay = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row="M9",
        anchor_ref=world.receipt.receipt_ref,
    )

    assert second.graph_command_created is False
    assert second.graph_command_ref == first.graph_command_ref
    assert replay == resolution
    assert len(world.graph.commands()) == command_count
    assert len(world.compiler.irs(owner=OWNER)) == ir_count
    assert len(world.compiler.passes(owner=OWNER)) == pass_count
    assert len(world.coverage.records(owner=OWNER)) == coverage_count

    restarted_graph = PersistentResearchGraphStore(world.graph_path)
    restarted_ledger = GoalProofLedger(world.proof_ledger_path)
    restarted_compiler = PersistentCompilerIRStore(
        world.compiler_path,
        proof_ledger=restarted_ledger,
        legacy_read_only=True,
    )
    restarted_policy = build_platform_source_lineage_policies_m9_m15(
        PlatformSourceLineagePoliciesM9M15Context(
            research_graph_store=restarted_graph,
            compiler_store=restarted_compiler,
            spine_chain_registry=world.spines,
            execution_closure_registry=world.closures,
            execution_order_intent_registry=world.intents,
            market_data_registry=world.market,
        )
    )
    restarted = restarted_policy.resolve(
        owner_user_id=OWNER,
        m_row="M9",
        anchor_ref=world.receipt.receipt_ref,
    )
    assert restarted.qro_ref == world.qro.qro_id
    assert restarted.math_spine_ref == "math_spine_chain:platform-binding-m9"
    assert dict(restarted.row_policy_metadata)["graph_command_ref"] == (
        first.graph_command_ref
    )


class _UnavailableM16M21Dependency:
    def __getattr__(self, name: str):
        def unavailable(*_args, **_kwargs):
            raise KeyError(name)

        return unavailable


class _M16SharingRegistry:
    def __init__(self, strategy: SharedStrategy) -> None:
        self.strategy = strategy
        self.permission_row = shared_strategy_permission(strategy)
        self.source_row = shared_strategy_source(strategy)
        self.status_row = shared_strategy_status(strategy)

    def shared_asset(self, ref: str, *, owner_user_id: str):
        if (
            ref != shared_strategy_asset_ref(self.strategy)
            or owner_user_id != self.strategy.author_id
        ):
            raise KeyError(ref)
        return self.strategy

    def permission(self, ref: str, *, owner_user_id: str):
        if ref != self.permission_row.permission_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.permission_row

    def source(self, ref: str, *, owner_user_id: str):
        if ref != self.source_row.source_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.source_row

    def status(self, ref: str, *, owner_user_id: str):
        if ref != self.status_row.status_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.status_row


class _M16M21LifecycleRegistry:
    def __init__(self, asset: GovernedAssetRecord) -> None:
        self.asset = asset

    def governed_asset(self, ref: str, *, owner_user_id: str):
        if ref != self.asset.asset_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.asset

    def governed_asset_by_mock_label_ref(
        self,
        ref: str,
        *,
        owner_user_id: str,
    ):
        if ref != self.asset.mock_label_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.asset

    def governed_asset_by_category_ref(
        self,
        ref: str,
        *,
        owner_user_id: str,
    ):
        if ref != self.asset.asset_category_ref or owner_user_id != OWNER:
            raise KeyError(ref)
        return self.asset


class _M19TeachingRegistry:
    def __init__(self, bundle: TeachingAssetBundle) -> None:
        self.bundle = bundle

    def tutorial_asset(self, ref: str, *, owner_user_id: str):
        if (
            ref != self.bundle.tutorial.tutorial_asset_ref
            or owner_user_id != OWNER
        ):
            raise KeyError(ref)
        return self.bundle.tutorial

    def bundles(self, *, owner_user_id: str):
        if owner_user_id != OWNER:
            return ()
        return (self.bundle,)


class _M16M21Spines:
    def __init__(self, chain) -> None:
        self.chain = chain

    def chains(self, *, owner: str):
        return [self.chain] if owner == self.chain.recorded_by else []

    def verified_chain(self, ref: str, *, owner: str):
        if ref != self.chain.chain_ref or owner != self.chain.recorded_by:
            raise KeyError(ref)
        return self.chain

    def verified_chain_record_refs(self, ref: str, *, owner: str):
        chain = self.verified_chain(ref, owner=owner)
        return SimpleNamespace(
            theory_binding_refs=tuple(chain.theory_binding_refs),
            consistency_check_refs=tuple(chain.consistency_check_refs),
        )


def _fresh_m16_m21_coverage_view(
    *,
    coverage_path,
    graph_path,
    compiler_path,
    validation_path,
    proof_ledger_path,
    lifecycle,
    spines,
):
    unavailable = _UnavailableM16M21Dependency()

    def lifecycle_loader(ref: str, owner: str):
        lifecycle.governed_asset(ref, owner_user_id=owner)
        return SimpleNamespace(owner_user_id=owner, lifecycle_ref=ref)

    proof_ledger = GoalProofLedger(proof_ledger_path)
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(
        compiler_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        validation_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        compiler_path.with_name("entrypoint_evidence.jsonl"),
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    resolver = main.build_real_platform_coverage_resolver(
        research_graph_store=graph,
        lifecycle_registry=unavailable,
        governance_registry=unavailable,
        rag_index=unavailable,
        spine_chain_registry=spines,
        compiler_store=compiler,
        document_store=unavailable,
        rdp_store=unavailable,
        market_data_registry=unavailable,
        dataset_registry=unavailable,
        onboarding_registry=unavailable,
        llm_service_owner_user_id="service:llm",
        llm_call_record_store=unavailable,
        account_halt_barrier=unavailable,
        goal_validation_receipt_registry=validations,
        platform_source_evidence_registry=(
            CompositeEntrypointEvidenceRegistry((evidence,))
        ),
        lifecycle_loaders=(lifecycle_loader,),
    )
    return PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=resolver,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )


def _fresh_m16_m21_compiler_view(*, compiler_path, proof_ledger_path):
    proof_ledger = GoalProofLedger(proof_ledger_path)
    return PersistentCompilerIRStore(
        compiler_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )


def _fresh_m16_m21_evidence_view(
    *,
    graph_path,
    compiler_path,
    validation_path,
    proof_ledger_path,
):
    proof_ledger = GoalProofLedger(proof_ledger_path)
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(
        compiler_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        validation_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    return PersistentEntrypointEvidenceRegistry(
        compiler_path.with_name("entrypoint_evidence.jsonl"),
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )


def _governed_binding_asset(
    *,
    asset_ref: str,
    asset_type: str,
    category: AssetCategory,
    evidence_refs: tuple[str, ...],
    mock_label_ref: str | None = None,
    asset_category_ref: str | None = None,
) -> GovernedAssetRecord:
    return GovernedAssetRecord(
        asset_ref=asset_ref,
        asset_type=asset_type,
        category=category,
        lifecycle_state=LifecycleState.LINKED,
        evidence_refs=evidence_refs,
        validation_plan_ref="validation_plan:m16_m21_binding",
        promotion_history=(),
        display_label="TEMPLATE - candidate context only" if mock_label_ref else "",
        mock_label_ref=mock_label_ref,
        asset_category_ref=asset_category_ref,
    )


def _m16_m21_binding_subject(row: str):
    if row == "M16":
        strategy = SharedStrategy(
            share_id="share-m16-persistent-binding",
            run_id="run-m16-persistent-binding",
            author_id=OWNER,
            title="M16 persistent binding",
            asset_class="equity_cn",
            public=True,
            created_at_utc="2026-07-13T00:00:00+00:00",
        )
        sharing = _M16SharingRegistry(strategy)
        anchor = shared_strategy_asset_ref(strategy)
        asset = _governed_binding_asset(
            asset_ref=anchor,
            asset_type="SharedStrategy",
            category=AssetCategory.USER_ASSET,
            evidence_refs=(
                sharing.permission_row.permission_ref,
                sharing.source_row.source_ref,
                sharing.status_row.status_ref,
            ),
        )
        return SimpleNamespace(
            anchor=anchor,
            subject=M16BusinessHistorySubject(
                strategy=strategy,
                permission=sharing.permission_row,
                source=sharing.source_row,
                status=sharing.status_row,
                governed_asset=asset,
            ),
            sharing=sharing,
            lifecycle=_M16M21LifecycleRegistry(asset),
            teaching=_UnavailableM16M21Dependency(),
        )
    if row == "M19":
        governed_ref = "governed_asset:m19-persistent-binding"
        tutorial = TutorialAssetRecord(
            tutorial_asset_ref="",
            owner_user_id=OWNER,
            governed_asset_ref=governed_ref,
            category="tutorial",
            title="M19 persistent binding",
        )
        tutorial = replace(tutorial, tutorial_asset_ref=tutorial.canonical_ref)
        weakness = WeaknessDisclosureRecord(
            weakness_disclosure_ref="",
            owner_user_id=OWNER,
            tutorial_asset_ref=tutorial.tutorial_asset_ref,
            weakness_refs=("weakness:m19:persistent-binding",),
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
            evidence_refs=("evidence:m19:persistent-binding",),
        )
        evidence = replace(evidence, teaching_evidence_ref=evidence.canonical_ref)
        bundle = TeachingAssetBundle(
            tutorial=tutorial,
            weakness=weakness,
            evidence=evidence,
        )
        asset = _governed_binding_asset(
            asset_ref=governed_ref,
            asset_type="TeachingAsset",
            category=AssetCategory.TUTORIAL,
            evidence_refs=("evidence:m19:lifecycle:persistent-binding",),
        )
        return SimpleNamespace(
            anchor=tutorial.tutorial_asset_ref,
            subject=M19BusinessHistorySubject(
                bundle=bundle,
                governed_asset=asset,
            ),
            sharing=_UnavailableM16M21Dependency(),
            lifecycle=_M16M21LifecycleRegistry(asset),
            teaching=_M19TeachingRegistry(bundle),
        )
    assert row == "M21"
    governed_asset_ref = "governed_asset:m21-persistent-binding"
    asset = _governed_binding_asset(
        asset_ref=governed_asset_ref,
        asset_type="StrategyTemplate",
        category=AssetCategory.TEMPLATE,
        evidence_refs=("evidence:m21:persistent-binding",),
        mock_label_ref="mock_label:m21:persistent-binding",
        asset_category_ref="asset_category:equity_cn:m21:persistent-binding",
    )
    strategy = StrategyFile(
        strategy_id="strategy-m21-persistent-binding",
        owner_username="platform-spine-binding-owner",
        name="m21_persistent_binding",
        code="def generate_signal(ctx):\n    return 0\n",
        asset_class="equity_cn",
        description="forked from governed template",
        updated_at_utc="2026-07-13T00:00:00Z",
        market_data_use_validation_refs=[],
    )
    anchor = f"ide_strategy:{strategy.strategy_id}"
    return SimpleNamespace(
        anchor=anchor,
        subject=M21BusinessHistorySubject(
            governed_asset=asset,
            ide_strategy=strategy,
        ),
        sharing=_UnavailableM16M21Dependency(),
        lifecycle=_M16M21LifecycleRegistry(asset),
        teaching=_UnavailableM16M21Dependency(),
    )


def _build_real_m16_m21_policy(
    world,
    *,
    graph=None,
    compiler=None,
    coverage=None,
):
    unavailable = _UnavailableM16M21Dependency()
    compiler = compiler or world.compiler
    coverage = coverage or world.coverage
    return build_platform_source_lineage_policy_resolver_m16_m21(
        PlatformSourceLineagePoliciesM16M21Context(
            research_graph_store=graph or world.graph,
            compiler_store=compiler,
            entrypoint_registry=coverage,
            entrypoint_view_factory=(
                lambda: _fresh_m16_m21_coverage_view(
                    coverage_path=world.coverage_path,
                    graph_path=world.graph_path,
                    compiler_path=world.compiler_path,
                    validation_path=world.validation_path,
                    proof_ledger_path=world.proof_ledger_path,
                    lifecycle=world.typed.lifecycle,
                    spines=world.spines,
                )
            )
            if coverage is world.coverage
            else None,
            compiler_view_factory=(
                lambda: _fresh_m16_m21_compiler_view(
                    compiler_path=world.compiler_path,
                    proof_ledger_path=world.proof_ledger_path,
                )
            )
            if compiler is world.compiler
            else None,
            spine_chain_registry=world.spines,
            asset_lifecycle_registry=world.typed.lifecycle,
            sharing_service=world.typed.sharing,
            copy_trade_service=unavailable,
            runtime_promotion_registry=unavailable,
            follower_risk_state_store=unavailable,
            execution_order_submission_registry=unavailable,
            execution_order_intent_registry=unavailable,
            canonical_spine_ledger=unavailable,
            rdp_store=unavailable,
            teaching_asset_registry=world.typed.teaching,
            onboarding_registry=unavailable,
            llm_call_record_store=unavailable,
            account_halt_barrier=unavailable,
            ide_strategy_loader=main._load_current_owned_m21_ide_strategy,
            llm_service_owner_user_id="service:llm",
        )
    )


def _install_real_m16_m21_binding_world(row: str, tmp_path, monkeypatch):
    typed = _m16_m21_binding_subject(row)
    if row == "M21":
        strategy = typed.subject.ide_strategy

        def strategy_by_id(strategy_id: str):
            if strategy_id != strategy.strategy_id:
                raise KeyError(strategy_id)
            return strategy

        monkeypatch.setattr(
            main,
            "AUTH_SERVICE",
            SimpleNamespace(
                get_user_by_id=lambda owner: (
                    SimpleNamespace(
                        user_id=OWNER,
                        username=strategy.owner_username,
                    )
                    if owner == OWNER
                    else None
                )
            ),
        )
        monkeypatch.setattr(
            main,
            "IDE_SERVICE",
            SimpleNamespace(get_strategy_by_id=strategy_by_id),
        )
    graph_path = tmp_path / f"research_graph_{row.lower()}.jsonl"
    compiler_path = tmp_path / f"compiler_{row.lower()}.jsonl"
    coverage_path = tmp_path / f"coverage_{row.lower()}.jsonl"
    validation_path = tmp_path / f"validation_{row.lower()}.jsonl"
    proof_ledger_path = tmp_path / f"goal_proof_ledger_{row.lower()}"
    proof_ledger = GoalProofLedger(proof_ledger_path)
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(
        compiler_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        validation_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        compiler_path.with_name("entrypoint_evidence.jsonl"),
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    unavailable = _UnavailableM16M21Dependency()

    def install_active_coverage_resolver(spine_registry) -> None:
        def lifecycle_loader(ref: str, owner: str):
            typed.lifecycle.governed_asset(ref, owner_user_id=owner)
            return SimpleNamespace(owner_user_id=owner, lifecycle_ref=ref)

        coverage.set_ref_resolver(
            main.build_real_platform_coverage_resolver(
                research_graph_store=graph,
                lifecycle_registry=unavailable,
                governance_registry=unavailable,
                rag_index=unavailable,
                spine_chain_registry=spine_registry,
                compiler_store=compiler,
                document_store=unavailable,
                rdp_store=unavailable,
                market_data_registry=unavailable,
                dataset_registry=unavailable,
                onboarding_registry=unavailable,
                llm_service_owner_user_id="service:llm",
                llm_call_record_store=unavailable,
                account_halt_barrier=unavailable,
                goal_validation_receipt_registry=validations,
                platform_source_evidence_registry=(
                    CompositeEntrypointEvidenceRegistry((evidence,))
                ),
                lifecycle_loaders=(lifecycle_loader,),
            )
        )

    install_active_coverage_resolver(unavailable)

    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)
    monkeypatch.setattr(
        main,
        "_PERSISTENT_GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        coverage,
    )
    monkeypatch.setattr(
        main,
        "_fresh_platform_entrypoint_coverage_view",
        lambda: _fresh_m16_m21_coverage_view(
            coverage_path=coverage_path,
            graph_path=graph_path,
            compiler_path=compiler_path,
            validation_path=validation_path,
            proof_ledger_path=proof_ledger_path,
            lifecycle=typed.lifecycle,
            spines=_UnavailableM16M21Dependency(),
        ),
    )
    monkeypatch.setattr(
        main,
        "_fresh_platform_compiler_view",
        lambda: _fresh_m16_m21_compiler_view(
            compiler_path=compiler_path,
            proof_ledger_path=proof_ledger_path,
        ),
    )
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", typed.lifecycle)
    monkeypatch.setattr(main, "SHARING_SERVICE", typed.sharing)
    monkeypatch.setattr(main, "TEACHING_ASSET_REGISTRY", typed.teaching)

    recorder = PlatformBusinessHistoryM16M21Recorder(
        PlatformBusinessHistoryM16M21Context(
            research_graph_store=graph,
            compiler_store=compiler,
            entrypoint_registry=coverage,
            apply_graph=graph.apply,
            compile_history=main._compile_platform_business_history_m16_m21,
            entrypoint_view_factory=(
                lambda: _fresh_m16_m21_coverage_view(
                    coverage_path=coverage_path,
                    graph_path=graph_path,
                    compiler_path=compiler_path,
                    validation_path=validation_path,
                    proof_ledger_path=proof_ledger_path,
                    lifecycle=typed.lifecycle,
                    spines=_UnavailableM16M21Dependency(),
                )
            ),
            compiler_view_factory=lambda: _fresh_m16_m21_compiler_view(
                compiler_path=compiler_path,
                proof_ledger_path=proof_ledger_path,
            ),
            entrypoint_evidence_view_factory=lambda: (
                _fresh_m16_m21_evidence_view(
                    graph_path=graph_path,
                    compiler_path=compiler_path,
                    validation_path=validation_path,
                    proof_ledger_path=proof_ledger_path,
                )
            ),
            validation_receipt_registry=validations,
        )
    )
    historical = recorder.record(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=typed.anchor,
        subject=typed.subject,
    )
    historical_qro = graph.qro(historical.qro_ref)
    chain = SimpleNamespace(
        chain_ref=f"math_spine_chain:{row.lower()}:persistent-binding",
        recorded_by=OWNER,
        validation_refs=(
            f"validation:{row.lower()}:persistent-binding",
        ),
        evidence_refs=tuple(
            dict.fromkeys(
                (
                    *historical_qro.evidence_refs,
                    f"evidence:{row.lower()}:persistent-binding",
                )
            )
        ),
        theory_binding_refs=(f"tbind:{row.lower()}:persistent-binding",),
        consistency_check_refs=(f"ccheck:{row.lower()}:persistent-binding",),
    )
    spines = _M16M21Spines(chain)
    install_active_coverage_resolver(spines)
    monkeypatch.setattr(main, "MATHEMATICAL_SPINE_CHAIN_REGISTRY", spines)
    world = SimpleNamespace(
        row=row,
        typed=typed,
        graph=graph,
        compiler=compiler,
        coverage=coverage,
        validations=validations,
        evidence=evidence,
        historical=historical,
        historical_qro=historical_qro,
        chain=chain,
        spines=spines,
        graph_path=graph_path,
        compiler_path=compiler_path,
        coverage_path=coverage_path,
        validation_path=validation_path,
        proof_ledger=proof_ledger,
        proof_ledger_path=proof_ledger_path,
        recorder=recorder,
    )
    policy = _build_real_m16_m21_policy(world)
    world.policy = policy
    monkeypatch.setattr(
        main,
        "PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER",
        SimpleNamespace(resolve=policy.resolve),
    )
    return world


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_real_persistent_m16_m21_history_binding_and_policy_replay(
    row: str,
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world(row, tmp_path, monkeypatch)
    historical_command = next(
        command
        for command in world.graph.commands()
        if command.command_id == world.historical.graph_command_ref
    )
    historical_coverage = world.coverage.coverage(
        world.historical.entrypoint_coverage_ref,
        owner=OWNER,
    )

    result, resolution = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=world.typed.anchor,
    )

    entrypoint_ref = main._PLATFORM_SPINE_BINDING_ENTRYPOINTS[row]
    assert entrypoint_ref == (
        f"api:research_os.platform.business_attestations.{row.lower()}"
    )
    assert historical_command.payload["qro"].mathematical_refs == ()
    assert historical_command.source == EntrySource.API
    assert historical_command.actor_source == ActorSource.USER_MANUAL
    assert historical_command.actor == OWNER
    assert historical_command.tool_record_refs == (
        {
            "M16": "api:sharing.publish",
            "M19": "api:research_os.teaching.assets",
            "M21": "api:strategies.templates.fork_to_ide",
        }[row],
    )
    assert historical_coverage.goal_sections == {
        "M16": ("§0", "§1", "§8", "§16"),
        "M19": ("§0", "§1", "§8", "§17"),
        "M21": ("§0", "§1", "§8"),
    }[row]
    assert "§14" not in historical_coverage.goal_sections
    assert historical_coverage.lifecycle_refs == (
        world.typed.subject.governed_asset.asset_ref,
    )
    if row == "M21":
        assert world.typed.anchor == (
            f"ide_strategy:{world.typed.subject.ide_strategy.strategy_id}"
        )
        assert world.historical_qro.input_contract == {
            "entry_source": "api",
            "governed_asset_ref": (
                world.typed.subject.governed_asset.asset_ref
            ),
        }
        assert world.historical_qro.output_contract["ide_strategy_ref"] == (
            world.typed.anchor
        )

    commands = world.graph.commands()
    assert len(commands) == 2
    binding_command = next(
        command
        for command in commands
        if command.command_id == result.graph_command_ref
    )
    assert binding_command.payload["qro"].qro_id == world.historical.qro_ref
    assert binding_command.payload["qro"].mathematical_refs == (
        world.chain.chain_ref,
    )
    assert binding_command.source == EntrySource.API
    assert binding_command.actor_source == ActorSource.USER_MANUAL
    assert binding_command.actor == OWNER
    assert binding_command.tool_record_refs == (entrypoint_ref,)
    assert world.graph.qro(world.historical.qro_ref) == binding_command.payload["qro"]

    binding_ir = world.compiler.ir(result.compiler_ir_ref, owner=OWNER)
    binding_pass = world.compiler.compiler_pass(
        result.compiler_pass_ref,
        owner=OWNER,
    )
    binding_coverage = world.coverage.coverage(
        result.entrypoint_coverage_ref,
        owner=OWNER,
    )
    expected_canonical = (
        f"research_graph_command:{result.graph_command_ref}",
        world.typed.anchor,
        world.chain.chain_ref,
        f"entrypoint:{entrypoint_ref}",
    )
    assert binding_ir.canonical_command_refs == expected_canonical
    assert binding_pass.canonical_command_refs == expected_canonical
    assert binding_pass.input_ir_refs == ()
    assert binding_pass.output_ir_ref == binding_ir.ir_ref
    assert binding_pass.actor_source == ActorSource.USER_MANUAL
    assert binding_pass.entry_source == EntrySource.API
    assert binding_pass.tool_record_refs == (
        entrypoint_ref,
        world.typed.anchor,
        world.chain.chain_ref,
        "api:compile_qro",
    )
    assert binding_coverage.entrypoint_ref == entrypoint_ref
    assert binding_coverage.goal_sections == {
        "M16": ("§0", "§1", "§6", "§8", "§16"),
        "M19": ("§0", "§1", "§6", "§8", "§17"),
        "M21": ("§0", "§1", "§6", "§8"),
    }[row]
    assert "§14" not in binding_coverage.goal_sections
    assert binding_coverage.lifecycle_refs == (
        world.typed.subject.governed_asset.asset_ref,
    )
    assert resolution.qro_ref == world.historical.qro_ref
    assert resolution.math_spine_ref == world.chain.chain_ref
    assert resolution.lifecycle_ref == (
        world.typed.subject.governed_asset.asset_ref
    )
    assert resolution.primary_rag_asset_ref == (
        world.typed.subject.governed_asset.asset_ref
    )
    assert dict(resolution.row_policy_metadata)[
        "historical_business_coverage_ref"
    ] == world.historical.entrypoint_coverage_ref

    restarted_graph = PersistentResearchGraphStore(world.graph_path)
    restarted_compiler = _fresh_m16_m21_compiler_view(
        compiler_path=world.compiler_path,
        proof_ledger_path=world.proof_ledger_path,
    )
    restarted_coverage = _fresh_m16_m21_coverage_view(
        coverage_path=world.coverage_path,
        graph_path=world.graph_path,
        compiler_path=world.compiler_path,
        validation_path=world.validation_path,
        proof_ledger_path=world.proof_ledger_path,
        lifecycle=world.typed.lifecycle,
        spines=world.spines,
    )
    restarted_policy = _build_real_m16_m21_policy(
        world,
        graph=restarted_graph,
        compiler=restarted_compiler,
        coverage=restarted_coverage,
    )
    replay = restarted_policy.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=world.typed.anchor,
    )
    assert replay.qro_ref == world.historical.qro_ref
    assert replay.math_spine_ref == world.chain.chain_ref
    assert replay.business_entrypoint_ref == entrypoint_ref
    assert dict(replay.row_policy_metadata)["graph_command_ref"] == (
        result.graph_command_ref
    )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "mutation",
    ("owner", "entrypoint", "qro_context"),
)
def test_business_history_reopen_rejects_swapped_entrypoint_evidence_context(
    row: str,
    mutation: str,
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world(row, tmp_path, monkeypatch)
    evidence_view = _fresh_m16_m21_evidence_view(
        graph_path=world.graph_path,
        compiler_path=world.compiler_path,
        validation_path=world.validation_path,
        proof_ledger_path=world.proof_ledger_path,
    )
    rows = evidence_view.evidences(owner_user_id=OWNER)
    assert len(rows) == 1
    record = rows[0]
    changes = {
        "owner": {"owner_user_id": "owner:foreign-entrypoint-evidence"},
        "entrypoint": {"entrypoint_ref": "api:foreign.entrypoint"},
        "qro_context": {"qro_ref": "qro:foreign-entrypoint-context"},
    }[mutation]
    provisional = replace(record, evidence_ref="", **changes)
    mutated = replace(
        provisional,
        evidence_ref=provisional.canonical_evidence_ref,
    )

    class MutatedEvidenceView:
        def evidence(self, ref: str, *, owner_user_id: str):
            if ref != record.evidence_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return mutated

        def evidences(self, *, owner_user_id: str):
            return (mutated,) if owner_user_id == OWNER else ()

        def validate_current(self, candidate, *, owner_user_id: str):
            return evidence_view.validate_current(
                candidate,
                owner_user_id=owner_user_id,
            )

        def validate_platform_ref(
            self,
            evidence_ref: str,
            *,
            owner_user_id: str,
            record,
        ):
            return evidence_view.validate_platform_ref(
                evidence_ref,
                owner_user_id=owner_user_id,
                record=record,
            )

    recorder = PlatformBusinessHistoryM16M21Recorder(
        replace(
            world.recorder._context,
            entrypoint_evidence_view_factory=MutatedEvidenceView,
        )
    )
    protected_paths = (
        world.graph_path,
        world.compiler_path,
        world.coverage_path,
        world.validation_path,
        world.proof_ledger.db_path,
        world.proof_ledger.mirror_path,
    )

    def path_state(path):
        return (path.exists(), path.read_bytes() if path.exists() else b"")

    before = {path: path_state(path) for path in protected_paths}

    with pytest.raises(PlatformBusinessHistoryM16M21Error):
        recorder.record(
            owner_user_id=OWNER,
            row=row,
            anchor_ref=world.typed.anchor,
            subject=world.typed.subject,
        )

    assert {path: path_state(path) for path in protected_paths} == before


class _M16M21GraphMutation:
    def __init__(self, graph, *, command_ref: str, mutation: str) -> None:
        self.graph = graph
        self.command_ref = command_ref
        self.mutation = mutation

    def qro(self, ref: str):
        return self.graph.qro(ref)

    def projection_index(self, **filters):
        return self.graph.projection_index(**filters)

    def commands(self):
        rows = self.graph.commands()
        if self.mutation == "missing_history":
            return [row for row in rows if row.command_id != self.command_ref]
        mutated = []
        for row in rows:
            if row.command_id != self.command_ref:
                mutated.append(row)
                continue
            if self.mutation == "recombined_history":
                qro = row.payload["qro"]
                qro = replace(
                    qro,
                    input_contract={
                        **qro.input_contract,
                        "same_owner_recombined_ref": "business_ref:unrelated",
                    },
                )
                mutated.append(
                    replace(
                        row,
                        payload={"qro": qro},
                        command_id=row.command_id,
                    )
                )
            else:
                assert self.mutation == "wrong_history_provenance"
                mutated.append(
                    replace(
                        row,
                        source=EntrySource.IDE,
                        command_id=row.command_id,
                    )
                )
        return mutated


class _M16M21CompilerMutation:
    def __init__(self, compiler, *, ir_ref: str, pass_ref: str) -> None:
        self.compiler = compiler
        self.ir_ref = ir_ref
        self.pass_ref = pass_ref

    @staticmethod
    def _canonical(refs: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            "entrypoint:api:research_os.platform.business_attestations.wrong"
            if ref.startswith("entrypoint:")
            else ref
            for ref in refs
        )

    def _ir(self, row):
        if row.ir_ref != self.ir_ref:
            return row
        return replace(
            row,
            canonical_command_refs=self._canonical(row.canonical_command_refs),
        )

    def _pass(self, row):
        if row.pass_ref != self.pass_ref:
            return row
        return replace(
            row,
            canonical_command_refs=self._canonical(row.canonical_command_refs),
        )

    def irs(self, *, owner: str):
        return [self._ir(row) for row in self.compiler.irs(owner=owner)]

    def passes(self, *, owner: str):
        return [self._pass(row) for row in self.compiler.passes(owner=owner)]

    def ir(self, ref: str, *, owner: str):
        return self._ir(self.compiler.ir(ref, owner=owner))

    def compiler_pass(self, ref: str, *, owner: str):
        return self._pass(self.compiler.compiler_pass(ref, owner=owner))

    def canonical_records(self, *, owner: str):
        records = self.compiler.canonical_records(owner=owner)
        return SimpleNamespace(
            owner=owner,
            irs=tuple(self._ir(row) for row in records.irs),
            passes=tuple(self._pass(row) for row in records.passes),
            artifacts=records.artifacts,
        )

    def canonical_ir(self, ref: str, *, owner: str):
        return self._ir(self.compiler.canonical_ir(ref, owner=owner))

    def canonical_compiler_pass(self, ref: str, *, owner: str):
        return self._pass(
            self.compiler.canonical_compiler_pass(ref, owner=owner)
        )


class _M16M21CoverageMutation:
    canonical_projection_available = True

    def __init__(self, coverage, *, target_ref: str, mutation: str) -> None:
        self.coverage_registry = coverage
        self.target_ref = target_ref
        self.mutation = mutation

    def _row(self, row):
        if row.coverage_ref != self.target_ref:
            return row
        if self.mutation == "current_section_14":
            return replace(row, goal_sections=("§0", "§14"))
        assert self.mutation == "historical_entrypoint"
        return replace(
            row,
            entrypoint_ref="api:research_os.platform.business_attestations.wrong",
        )

    def records(self, *, owner: str | None = None):
        return [
            self._row(row)
            for row in self.coverage_registry.records(owner=owner)
        ]

    def canonical_records(self, *, owner: str):
        return tuple(
            self._row(row)
            for row in self.coverage_registry.canonical_records(owner=owner)
        )

    def canonical_coverage(self, ref: str, *, owner: str):
        return self._row(
            self.coverage_registry.canonical_coverage(ref, owner=owner)
        )

    def validate_real_backing(self, record):
        return self.coverage_registry.validate_real_backing(record)


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "mutation",
    (
        "missing_history",
        "recombined_history",
        "wrong_history_provenance",
        "wrong_history_entrypoint",
        "wrong_chain",
    ),
)
def test_m16_m21_binding_preflight_rejects_recombined_history_before_write(
    row: str,
    mutation: str,
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world(row, tmp_path, monkeypatch)
    assert len(world.graph.commands()) == 1
    assert world.graph.qro(world.historical.qro_ref).mathematical_refs == ()

    if mutation == "wrong_chain":
        wrong_chain = SimpleNamespace(
            **{
                **vars(world.chain),
                "chain_ref": f"math_spine_chain:{row.lower()}:unrelated",
                "evidence_refs": (f"evidence:{row.lower()}:unrelated",),
            }
        )
        monkeypatch.setattr(
            main,
            "MATHEMATICAL_SPINE_CHAIN_REGISTRY",
            _M16M21Spines(wrong_chain),
        )
        with pytest.raises(SpineChainSelectionError):
            main._derive_platform_spine_binding_subject(
                owner_user_id=OWNER,
                m_row=row,
                anchor_ref=world.typed.anchor,
            )
    else:
        plan = prepare_current_qro_spine_binding(
            research_graph_store=world.graph,
            qro_ref=world.historical.qro_ref,
            owner_user_id=OWNER,
            verified_chain=world.chain,
        )
        if mutation == "wrong_history_entrypoint":
            compiler = _M16M21CompilerMutation(
                world.compiler,
                ir_ref=world.historical.compiler_ir_ref,
                pass_ref=world.historical.compiler_pass_ref,
            )
            monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
            monkeypatch.setattr(
                main,
                "_fresh_platform_compiler_view",
                lambda: compiler,
            )
        else:
            graph = _M16M21GraphMutation(
                world.graph,
                command_ref=world.historical.graph_command_ref,
                mutation=mutation,
            )
            monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
        with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
            main._preflight_platform_spine_binding(
                owner_user_id=OWNER,
                m_row=row,
                anchor_ref=world.typed.anchor,
                qro_ref=world.historical.qro_ref,
                chain=world.chain,
                plan=plan,
            )

    assert len(world.graph.commands()) == 1
    assert world.graph.qro(world.historical.qro_ref).mathematical_refs == ()
    assert len(world.compiler.irs(owner=OWNER)) == 1
    assert len(world.compiler.passes(owner=OWNER)) == 1
    assert len(world.coverage.records(owner=OWNER)) == 1


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "mutation",
    ("current_section_14", "historical_entrypoint"),
)
def test_m16_m21_persisted_policy_replay_rejects_mutated_coverage(
    row: str,
    mutation: str,
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world(row, tmp_path, monkeypatch)
    result, _resolution = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=world.typed.anchor,
    )
    target_ref = (
        result.entrypoint_coverage_ref
        if mutation == "current_section_14"
        else world.historical.entrypoint_coverage_ref
    )
    coverage = _M16M21CoverageMutation(
        _fresh_m16_m21_coverage_view(
            coverage_path=world.coverage_path,
            graph_path=world.graph_path,
            compiler_path=world.compiler_path,
            validation_path=world.validation_path,
            proof_ledger_path=world.proof_ledger_path,
            lifecycle=world.typed.lifecycle,
            spines=world.spines,
        ),
        target_ref=target_ref,
        mutation=mutation,
    )
    policy = _build_real_m16_m21_policy(
        world,
        graph=PersistentResearchGraphStore(world.graph_path),
        compiler=_fresh_m16_m21_compiler_view(
            compiler_path=world.compiler_path,
            proof_ledger_path=world.proof_ledger_path,
        ),
        coverage=coverage,
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        policy.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.typed.anchor,
        )


def _fresh_m16_m21_binding_snapshot(world):
    proof_ledger = GoalProofLedger(world.proof_ledger_path)
    graph = PersistentResearchGraphStore(world.graph_path)
    compiler = PersistentCompilerIRStore(
        world.compiler_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        world.coverage_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        world.validation_path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        world.compiler_path.with_name("entrypoint_evidence.jsonl"),
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    return SimpleNamespace(
        commands=tuple(graph.commands()),
        qro=graph.qro(world.historical.qro_ref),
        irs=tuple(
            sorted(compiler.irs(owner=OWNER), key=lambda record: record.ir_ref)
        ),
        passes=tuple(
            sorted(
                compiler.passes(owner=OWNER),
                key=lambda record: record.pass_ref,
            )
        ),
        coverages=tuple(
            sorted(
                coverage.records(owner=OWNER),
                key=lambda record: record.coverage_ref,
            )
        ),
        receipts=tuple(
            sorted(
                validations.receipts(owner_user_id=OWNER),
                key=lambda record: record.validation_ref,
            )
        ),
        evidences=tuple(
            sorted(
                evidence.evidences(owner_user_id=OWNER),
                key=lambda record: record.evidence_ref,
            )
        ),
    )


def _assert_m16_m21_binding_retry_is_singleton(world, baseline) -> None:
    retry, retry_resolution = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row=world.row,
        anchor_ref=world.typed.anchor,
    )
    assert retry.graph_command_created is True
    assert retry_resolution.qro_ref == world.historical.qro_ref
    assert retry_resolution.math_spine_ref == world.chain.chain_ref

    after_retry = _fresh_m16_m21_binding_snapshot(world)
    assert len(after_retry.commands) == len(baseline.commands) + 1
    assert len(after_retry.irs) == len(baseline.irs) + 1
    assert len(after_retry.passes) == len(baseline.passes) + 1
    assert len(after_retry.coverages) == len(baseline.coverages) + 1
    assert len(after_retry.receipts) == len(baseline.receipts) + 1
    assert len(after_retry.evidences) == len(baseline.evidences) + 1
    assert after_retry.qro.mathematical_refs == (world.chain.chain_ref,)

    replay, replay_resolution = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row=world.row,
        anchor_ref=world.typed.anchor,
    )
    assert replay.graph_command_created is False
    assert replay.graph_command_ref == retry.graph_command_ref
    assert replay.compiler_ir_ref == retry.compiler_ir_ref
    assert replay.compiler_pass_ref == retry.compiler_pass_ref
    assert replay.entrypoint_coverage_ref == retry.entrypoint_coverage_ref
    assert replay_resolution == retry_resolution
    assert _fresh_m16_m21_binding_snapshot(world) == after_retry


def _inject_binding_proof_commit_failure(
    world,
    monkeypatch,
    *,
    after_commit: bool,
):
    original = world.proof_ledger.commit
    binding_entrypoint = main._PLATFORM_SPINE_BINDING_ENTRYPOINTS[world.row]

    def fail_binding_commit(bundle):
        if bundle.metadata.get("entrypoint_ref") != binding_entrypoint:
            return original(bundle)
        if after_commit:
            original(bundle)
            raise OSError("injected atomic proof commit acknowledgement failure")
        raise OSError("injected atomic proof commit failure")

    monkeypatch.setattr(world.proof_ledger, "commit", fail_binding_commit)
    return original


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "failure_phase",
    ("proof_commit", "proof_commit_ack", "policy"),
)
def test_real_persistent_m16_m21_binding_prefix_is_preserved_and_retry_idempotent(
    row: str,
    failure_phase: str,
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world(row, tmp_path, monkeypatch)
    baseline = _fresh_m16_m21_binding_snapshot(world)
    assert baseline.qro.mathematical_refs == ()

    if failure_phase in {"proof_commit", "proof_commit_ack"}:
        original = _inject_binding_proof_commit_failure(
            world,
            monkeypatch,
            after_commit=failure_phase == "proof_commit_ack",
        )
    else:
        assert failure_phase == "policy"
        original = main.PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER

        def fail_policy_replay(**_kwargs):
            raise PlatformSourceLineagePolicyM16M21Error(
                "injected persisted policy replay failure"
            )

        monkeypatch.setattr(
            main,
            "PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER",
            SimpleNamespace(resolve=fail_policy_replay),
        )

    with pytest.raises(QROSpineBindingCommitError) as failure:
        main._record_platform_spine_binding(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.typed.anchor,
        )

    if failure_phase == "policy":
        assert failure.value.phase == "policy_replay"
        monkeypatch.setattr(
            main,
            "PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER",
            original,
        )
    else:
        assert failure.value.phase == "compiler_coverage"
        monkeypatch.setattr(world.proof_ledger, "commit", original)

    assert failure.value.graph_binding_current is True
    assert failure.value.graph_command_created is True
    if failure_phase == "proof_commit":
        assert "injected atomic proof commit failure" in str(failure.value)
    elif failure_phase == "proof_commit_ack":
        assert "injected atomic proof commit acknowledgement failure" in str(
            failure.value
        )
    else:
        assert "persisted platform Spine binding policy replay failed" in str(
            failure.value
        )
    # Every assertion below comes from a new disk-backed reader.  The Graph
    # prefix is append-only, while the five proof records are all-or-nothing.
    after_failure = _fresh_m16_m21_binding_snapshot(world)
    assert len(after_failure.commands) == len(baseline.commands) + 1
    assert after_failure.qro.mathematical_refs == (world.chain.chain_ref,)
    expected_complete_delta = (
        0 if failure_phase == "proof_commit" else 1
    )
    assert len(after_failure.irs) == (
        len(baseline.irs) + expected_complete_delta
    )
    assert len(after_failure.passes) == (
        len(baseline.passes) + expected_complete_delta
    )
    assert len(after_failure.coverages) == (
        len(baseline.coverages) + expected_complete_delta
    )
    assert len(after_failure.receipts) == (
        len(baseline.receipts) + expected_complete_delta
    )
    assert len(after_failure.evidences) == (
        len(baseline.evidences) + expected_complete_delta
    )

    recovered, recovered_resolution = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=world.typed.anchor,
    )
    assert recovered.graph_command_created is False
    assert recovered_resolution.qro_ref == world.historical.qro_ref
    after_recovery = _fresh_m16_m21_binding_snapshot(world)
    assert len(after_recovery.commands) == len(baseline.commands) + 1
    assert len(after_recovery.irs) == len(baseline.irs) + 1
    assert len(after_recovery.passes) == len(baseline.passes) + 1
    assert len(after_recovery.coverages) == len(baseline.coverages) + 1
    assert len(after_recovery.receipts) == len(baseline.receipts) + 1
    assert len(after_recovery.evidences) == len(baseline.evidences) + 1
    replay, replay_resolution = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=world.typed.anchor,
    )
    assert replay.graph_command_created is False
    assert replay.graph_command_ref == recovered.graph_command_ref
    assert replay_resolution == recovered_resolution
    assert _fresh_m16_m21_binding_snapshot(world) == after_recovery


@pytest.mark.parametrize(
    "failure_phase",
    ("proof_commit", "proof_commit_ack", "policy"),
)
def test_m21_binding_http_failure_preserves_history_then_retries_one_binding(
    failure_phase: str,
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world("M21", tmp_path, monkeypatch)
    baseline = _fresh_m16_m21_binding_snapshot(world)
    assert baseline.qro.mathematical_refs == ()

    if failure_phase in {"proof_commit", "proof_commit_ack"}:
        original = _inject_binding_proof_commit_failure(
            world,
            monkeypatch,
            after_commit=failure_phase == "proof_commit_ack",
        )
    else:
        assert failure_phase == "policy"
        original = main.PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER

        def fail_policy_replay(**_kwargs):
            raise PlatformSourceLineagePolicyM16M21Error(
                "injected persisted policy replay failure"
            )

        monkeypatch.setattr(
            main,
            "PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER",
            SimpleNamespace(resolve=fail_policy_replay),
        )

    path = "/api/research-os/platform/spine_bindings/M21/current"
    payload = {"anchor_ref": world.typed.anchor}
    client = _client()
    failed = client.post(path, json=payload)

    assert failed.status_code == 409, failed.text
    assert failed.json()["detail"]["phase"] == (
        "policy_replay" if failure_phase == "policy" else "compiler_coverage"
    )
    assert failed.json()["detail"]["graph_binding_current"] is True
    after_failure = _fresh_m16_m21_binding_snapshot(world)
    assert len(after_failure.commands) == len(baseline.commands) + 1
    expected_complete_delta = (
        0 if failure_phase == "proof_commit" else 1
    )
    assert len(after_failure.irs) == (
        len(baseline.irs) + expected_complete_delta
    )
    assert len(after_failure.passes) == (
        len(baseline.passes) + expected_complete_delta
    )
    assert len(after_failure.coverages) == (
        len(baseline.coverages) + expected_complete_delta
    )
    assert len(after_failure.receipts) == (
        len(baseline.receipts) + expected_complete_delta
    )
    assert len(after_failure.evidences) == (
        len(baseline.evidences) + expected_complete_delta
    )
    assert after_failure.qro.mathematical_refs == (world.chain.chain_ref,)

    if failure_phase == "policy":
        monkeypatch.setattr(
            main,
            "PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER",
            original,
        )
    else:
        monkeypatch.setattr(world.proof_ledger, "commit", original)

    repaired = client.post(path, json=payload)

    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["graph_command_created"] is False
    assert repaired.json()["policy_replay_current"] is True
    repaired_snapshot = _fresh_m16_m21_binding_snapshot(world)
    assert len(repaired_snapshot.commands) == len(baseline.commands) + 1
    assert len(repaired_snapshot.irs) == len(baseline.irs) + 1
    assert len(repaired_snapshot.passes) == len(baseline.passes) + 1
    assert len(repaired_snapshot.coverages) == len(baseline.coverages) + 1
    assert len(repaired_snapshot.receipts) == len(baseline.receipts) + 1
    assert len(repaired_snapshot.evidences) == len(baseline.evidences) + 1
    assert repaired_snapshot.qro.mathematical_refs == (world.chain.chain_ref,)

    retry = client.post(path, json=payload)

    assert retry.status_code == 200, retry.text
    assert retry.json()["graph_command_created"] is False
    assert retry.json()["graph_command_ref"] == repaired.json()[
        "graph_command_ref"
    ]
    assert _fresh_m16_m21_binding_snapshot(world) == repaired_snapshot


@pytest.mark.parametrize(
    ("mutation", "changes"),
    (
        ("deleted", None),
        ("name", {"name": "m21_mutated_current_name"}),
        ("code", {"code": "def generate_signal(ctx):\n    return 1\n"}),
        ("description", {"description": "mutated after history"}),
        (
            "market_data_use_validation_refs",
            {"market_data_use_validation_refs": ["validation:mutated"]},
        ),
    ),
)
def test_m21_binding_http_rejects_deleted_or_mutated_current_ide_without_writes(
    mutation: str,
    changes: dict[str, object] | None,
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world("M21", tmp_path, monkeypatch)
    baseline = _fresh_m16_m21_binding_snapshot(world)
    strategy = world.typed.subject.ide_strategy

    def current_strategy(strategy_id: str):
        if strategy_id != strategy.strategy_id:
            raise IDEError("策略不存在")
        if changes is None:
            raise IDEError("策略不存在")
        return replace(strategy, **changes)

    monkeypatch.setattr(
        main,
        "IDE_SERVICE",
        SimpleNamespace(get_strategy_by_id=current_strategy),
    )
    response = _client().post(
        "/api/research-os/platform/spine_bindings/M21/current",
        json={"anchor_ref": world.typed.anchor},
    )

    assert response.status_code == 422, response.text
    assert _fresh_m16_m21_binding_snapshot(world) == baseline
    assert baseline.qro.mathematical_refs == ()


def test_m16_binding_forward_prefix_never_calls_destructive_coverage_rollback(
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world("M16", tmp_path, monkeypatch)
    baseline = _fresh_m16_m21_binding_snapshot(world)

    def fail_coverage_rollback(_record):
        raise OSError("injected coverage compensation failure")

    def fail_policy_replay(**_kwargs):
        raise PlatformSourceLineagePolicyM16M21Error(
            "injected persisted policy replay failure"
        )

    monkeypatch.setattr(
        world.coverage,
        "rollback_exact_coverage",
        fail_coverage_rollback,
    )
    monkeypatch.setattr(
        main,
        "PLATFORM_SOURCE_LINEAGE_POLICY_ROUTER",
        SimpleNamespace(resolve=fail_policy_replay),
    )

    with pytest.raises(QROSpineBindingCommitError) as failure:
        main._record_platform_spine_binding(
            owner_user_id=OWNER,
            m_row="M16",
            anchor_ref=world.typed.anchor,
        )

    assert failure.value.phase == "policy_replay"
    assert "persisted platform Spine binding policy replay failed" in str(
        failure.value
    )
    assert "rollback failed" not in str(failure.value)
    after_failure = _fresh_m16_m21_binding_snapshot(world)
    assert len(after_failure.commands) == len(baseline.commands) + 1
    assert after_failure.qro.mathematical_refs == (world.chain.chain_ref,)
    assert len(after_failure.irs) == len(baseline.irs) + 1
    assert len(after_failure.passes) == len(baseline.passes) + 1
    assert len(after_failure.coverages) == len(baseline.coverages) + 1
    assert len(after_failure.receipts) == len(baseline.receipts) + 1
    assert len(after_failure.evidences) == len(baseline.evidences) + 1


def test_existing_partial_m16_binding_head_is_preserved_and_completed_on_retry(
    tmp_path,
    monkeypatch,
) -> None:
    world = _install_real_m16_m21_binding_world("M16", tmp_path, monkeypatch)
    baseline = _fresh_m16_m21_binding_snapshot(world)
    plan = prepare_current_qro_spine_binding(
        research_graph_store=world.graph,
        qro_ref=world.historical.qro_ref,
        owner_user_id=OWNER,
        verified_chain=world.chain,
    )
    entrypoint_ref = main._PLATFORM_SPINE_BINDING_ENTRYPOINTS["M16"]
    partial_command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": plan.bound_qro},
        evidence_refs=(world.chain.chain_ref, plan.prior_command.command_id),
        tool_record_refs=(entrypoint_ref,),
    )
    assert world.graph.apply_if_current(
        plan.prior_command.command_id,
        partial_command,
    ) == partial_command.command_id
    partial = _fresh_m16_m21_binding_snapshot(world)
    assert len(partial.commands) == len(baseline.commands) + 1
    assert partial.qro.mathematical_refs == (world.chain.chain_ref,)
    assert partial.irs == baseline.irs
    assert partial.passes == baseline.passes
    assert partial.coverages == baseline.coverages
    assert partial.receipts == baseline.receipts

    original_commit = _inject_binding_proof_commit_failure(
        world,
        monkeypatch,
        after_commit=False,
    )
    with pytest.raises(QROSpineBindingCommitError) as failure:
        main._record_platform_spine_binding(
            owner_user_id=OWNER,
            m_row="M16",
            anchor_ref=world.typed.anchor,
        )
    assert failure.value.phase == "compiler_coverage"
    assert failure.value.graph_command_created is True
    assert "injected atomic proof commit failure" in str(failure.value)
    monkeypatch.setattr(world.proof_ledger, "commit", original_commit)

    after_failure = _fresh_m16_m21_binding_snapshot(world)
    assert len(after_failure.commands) == len(baseline.commands) + 1
    assert after_failure.qro.mathematical_refs == (world.chain.chain_ref,)
    assert after_failure.irs == baseline.irs
    assert after_failure.passes == baseline.passes
    assert after_failure.coverages == baseline.coverages
    assert after_failure.receipts == baseline.receipts
    assert after_failure.evidences == baseline.evidences

    recovered, recovered_resolution = main._record_platform_spine_binding(
        owner_user_id=OWNER,
        m_row="M16",
        anchor_ref=world.typed.anchor,
    )
    assert recovered.graph_command_created is False
    assert recovered_resolution.qro_ref == world.historical.qro_ref
    after_recovery = _fresh_m16_m21_binding_snapshot(world)
    assert len(after_recovery.commands) == len(baseline.commands) + 1
    assert len(after_recovery.irs) == len(baseline.irs) + 1
    assert len(after_recovery.passes) == len(baseline.passes) + 1
    assert len(after_recovery.coverages) == len(baseline.coverages) + 1
    assert len(after_recovery.receipts) == len(baseline.receipts) + 1
    assert len(after_recovery.evidences) == len(baseline.evidences) + 1
