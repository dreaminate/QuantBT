from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.backtest_evidence import (
    BacktestArtifactState,
    BacktestMonitorRecord,
    PersistentBacktestEvidenceRegistry,
)
from app.research_os.asset_rag import PersistentResearchAssetRAGIndex
from app.research_os.platform_coverage import PlatformCapabilityRecord
from app.research_os.platform_business_history_m16_m21 import (
    PlatformBusinessHistoryM16M21Result,
)
from app.research_os.platform_row_producers import PlatformRowSourceState
from app.research_os.platform_source_lineage_core import (
    PlatformSourceLineageCoreCommitError,
)
from app.research_os.teaching_assets import PersistentTeachingAssetRegistry


OWNER = "owner:platform-evidence-api"
OTHER_OWNER = "owner:platform-evidence-api-other"
ROW = "M1-M2"


@pytest.fixture(autouse=True)
def _clear_auth_override():
    yield
    main.app.dependency_overrides.pop(require_user_dependency, None)


def _authenticate(user_id: str = OWNER, username: str = "platform-owner") -> None:
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=user_id,
        username=username,
    )


class _PlatformSourceRegistry:
    def __init__(self) -> None:
        self._heads: dict[tuple[str, str], SimpleNamespace] = {}
        self.record_calls: list[dict[str, str]] = []
        self.resolve_calls: list[tuple[str, str]] = []
        self.drifted = False

    @staticmethod
    def _certification(owner_user_id: str, m_row: str) -> SimpleNamespace:
        record = PlatformCapabilityRecord(
            m_row=m_row,
            qro_ref="qro_platform_api",
            research_graph_ref="research_graph_command:platform-api",
            lifecycle_ref="lifecycle_event:platform-api",
            governance_ref="goal_validation_receipt:platform-api",
            rag_ref="rag_asset:platform-api",
            math_spine_ref="math_spine_chain:platform-api",
            evidence_refs=("evidence:platform-api",),
        )
        resolved = SimpleNamespace(
            production_ref="platform_row_production:platform-api",
            owner_user_id=owner_user_id,
            m_row=m_row,
            producer_ref=f"platform_row_source_registry:{m_row}:v1",
            record=record,
            source_states=(
                PlatformRowSourceState(
                    source_kind="qro_ref",
                    source_ref="qro_platform_api",
                    state_hash="sha256:" + "a" * 64,
                ),
            ),
        )
        return SimpleNamespace(
            certification_ref="platform_row_source_certification:" + "b" * 64,
            owner_user_id=owner_user_id,
            m_row=m_row,
            row_revision=1,
            previous_certification_ref="",
            source_coverage_ref="goal_entrypoint_coverage:platform-api",
            rag_ref="rag_asset:platform-api",
            resolved_row=resolved,
        )

    def record_current(self, **kwargs):
        self.record_calls.append(dict(kwargs))
        if kwargs["m_row"] != ROW:
            raise ValueError("m_row is not a canonical platform row")
        if kwargs["source_coverage_ref"] != "goal_entrypoint_coverage:platform-api":
            raise ValueError("unknown current source coverage")
        if kwargs["rag_ref"] != "rag_asset:platform-api":
            raise ValueError("unknown current RAG document")
        key = (kwargs["owner_user_id"], kwargs["m_row"])
        self._heads.setdefault(key, self._certification(*key))
        return self._heads[key]

    def current_certifications(self, *, owner_user_id: str):
        return tuple(
            certification
            for (owner, _), certification in sorted(self._heads.items())
            if owner == owner_user_id
        )

    def resolve_current_row(self, m_row: str, *, owner_user_id: str):
        self.resolve_calls.append((owner_user_id, m_row))
        try:
            certification = self._heads[(owner_user_id, m_row)]
        except KeyError:
            raise KeyError("platform row source is unavailable for owner") from None
        if self.drifted:
            raise ValueError("platform row typed sources drifted")
        return certification.resolved_row


class _ArtifactResolver:
    def __init__(self) -> None:
        self.state = BacktestArtifactState(
            artifact_sha256="sha256:" + "c" * 64,
            row_count=3,
            component_refs=("attribution_component:return", "attribution_component:cost"),
        )
        self.calls: list[tuple[str, str, str, str]] = []

    def __call__(
        self,
        owner_user_id: str,
        backtest_run_ref: str,
        source_run_ref: str,
        artifact_path: str,
    ) -> BacktestArtifactState:
        self.calls.append(
            (owner_user_id, backtest_run_ref, source_run_ref, artifact_path)
        )
        return self.state


class _ValidationMethodologyRegistry:
    def __init__(self) -> None:
        self.record = SimpleNamespace(
            validation_ref="validation_methodology:platform-api",
            cost_model_refs=("cost_model:fees",),
        )
        self.binding = SimpleNamespace(
            owner_user_id=OWNER,
            recorded_by="platform-owner",
            source_run_ref="ide_run:platform-api",
            backtest_run_ref="backtest_run:platform-api",
        )

    def methodology(self, ref: str, *, owner_user_id: str):
        if owner_user_id != OWNER or ref != self.record.validation_ref:
            raise KeyError("validation methodology is unavailable for owner")
        return self.record

    def methodology_binding(self, ref: str, *, owner_user_id: str):
        self.methodology(ref, owner_user_id=owner_user_id)
        return self.binding


class _ValidationDepthRegistry:
    def __init__(self) -> None:
        self.record = SimpleNamespace(
            depth_ref="validation_depth:platform-api",
            cost_model_refs=("cost_model:slippage",),
        )
        self.binding = SimpleNamespace(
            owner_user_id=OWNER,
            recorded_by="platform-owner",
            source_run_ref="ide_run:platform-api",
            backtest_run_ref="backtest_run:platform-api",
        )

    def depth(self, ref: str, *, owner_user_id: str):
        if owner_user_id != OWNER or ref != self.record.depth_ref:
            raise KeyError("validation depth is unavailable for owner")
        return self.record

    def depth_binding(self, ref: str, *, owner_user_id: str):
        self.depth(ref, owner_user_id=owner_user_id)
        return self.binding


class _ModelGovernanceRegistry:
    def monitoring_profile(self, ref: str, *, owner_user_id: str):
        if owner_user_id != OWNER or ref != "monitoring_profile:platform-api":
            raise KeyError("monitoring profile is unavailable for owner")
        return SimpleNamespace(monitoring_profile_id=ref)


class _SpineRegistry:
    def __init__(self, monitor: BacktestMonitorRecord) -> None:
        self.drifted = False
        self.chain = SimpleNamespace(
            chain_ref="math_spine_chain:platform-api",
            recorded_by=OWNER,
            backtest_run_ref=monitor.backtest_run_ref,
            attribution_ref=monitor.attribution_ref,
            monitor_ref=monitor.monitor_ref,
            theory_binding_refs=(),
            consistency_check_refs=monitor.mathematical_trigger_refs,
            evidence_refs=(
                monitor.performance_primary_alert_ref,
                monitor.cost_drift_ref,
                monitor.drift_root_cause_ref,
            ),
            validation_refs=(),
        )

    def chains(self, *, owner: str):
        return [self.chain] if owner == OWNER else []

    def verified_chain(self, ref: str, *, owner: str):
        if self.drifted or owner != OWNER or ref != self.chain.chain_ref:
            raise ValueError("Mathematical Spine source drifted")
        return self.chain


class _TeachingLifecycle:
    def __init__(self) -> None:
        self.assets = {
            (OWNER, "governed_asset:teaching-api"): SimpleNamespace(
                category="tutorial",
                display_label="Current tutorial",
            )
        }

    def governed_asset(self, ref: str, *, owner_user_id: str):
        try:
            return self.assets[(owner_user_id, ref)]
        except KeyError:
            raise KeyError("governed asset is unavailable for owner") from None


def test_platform_row_source_api_is_strict_owner_scoped_and_revalidates_get(
    monkeypatch,
) -> None:
    registry = _PlatformSourceRegistry()
    monkeypatch.setattr(main, "PLATFORM_ROW_SOURCE_REGISTRY", registry)
    _authenticate()
    client = TestClient(main.app)
    payload = {
        "source_coverage_ref": "goal_entrypoint_coverage:platform-api",
        "rag_ref": "rag_asset:platform-api",
    }

    first = client.post(
        f"/api/research-os/platform/row_sources/{ROW}/current",
        json=payload,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["current"] is True
    assert first_body["m_row"] == ROW
    assert first_body["source_coverage_ref"] == payload["source_coverage_ref"]
    assert registry.record_calls[-1]["owner_user_id"] == OWNER

    second = client.post(
        f"/api/research-os/platform/row_sources/{ROW}/current",
        json=payload,
    )
    assert second.status_code == 200, second.text
    assert second.json()["certification_ref"] == first_body["certification_ref"]

    call_count = len(registry.record_calls)
    forged = client.post(
        f"/api/research-os/platform/row_sources/{ROW}/current",
        json={**payload, "certification_ref": "client:forged"},
    )
    assert forged.status_code == 422, forged.text
    assert len(registry.record_calls) == call_count

    current = client.get(
        f"/api/research-os/platform/row_sources/{ROW}/current"
    )
    assert current.status_code == 200, current.text
    assert current.json()["current"] is True
    assert registry.resolve_calls[-1] == (OWNER, ROW)

    _authenticate(OTHER_OWNER, "other")
    hidden = client.get(
        f"/api/research-os/platform/row_sources/{ROW}/current"
    )
    assert hidden.status_code == 404, hidden.text
    empty = client.get("/api/research-os/platform/row_sources/current")
    assert empty.status_code == 200, empty.text
    assert empty.json()["row_source_total"] == 0

    _authenticate()
    registry.drifted = True
    stale = client.get(
        f"/api/research-os/platform/row_sources/{ROW}/current"
    )
    assert stale.status_code == 422, stale.text
    summary = client.get("/api/research-os/platform/row_sources/current")
    assert summary.status_code == 200, summary.text
    assert summary.json()["rows"][0]["current"] is False
    assert "drifted" in summary.json()["rows"][0]["current_error"]


def test_public_rag_api_cannot_mint_reserved_platform_source_provenance(
    tmp_path,
    monkeypatch,
) -> None:
    rag = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", rag)
    _authenticate()
    client = TestClient(main.app)
    base = {
        "source_id": "user:research-note",
        "version": "v1",
        "title": "Research note",
        "body": "User-authored candidate context.",
        "projection": "research",
        "asset_ref": "qro:user-note",
        "permission": {"allowed_users": [OWNER]},
        "applicability": "candidate context only",
        "source_kind": "user_supplied_document",
        "metadata": {},
        "evidence_label": "candidate_context",
    }

    for mutation in (
        {"metadata": {"platform_capability": {"m_row": "M15"}}},
        {"source_id": "platform_source_lineage:M15"},
        {"source_kind": "server_derived_platform_source_lineage"},
    ):
        response = client.post(
            "/api/research-os/rag/documents",
            json={**base, **mutation},
        )
        assert response.status_code == 422, response.text
        assert "server-derived platform producer" in response.text

    assert not rag.path.exists()


def test_platform_source_lineage_api_reports_partial_commit_state_and_rejects_proof_fields(
    monkeypatch,
) -> None:
    class FailingFinalizer:
        def __init__(self) -> None:
            self.calls = 0

        def record_current(self, **_kwargs):
            self.calls += 1
            raise PlatformSourceLineageCoreCommitError(
                "simulated RAG ledger failure",
                coverage_persisted=True,
                rag_persisted=False,
                row_source_persisted=False,
            )

    finalizer = FailingFinalizer()
    monkeypatch.setattr(main, "PLATFORM_SOURCE_LINEAGE_FINALIZER", finalizer)
    _authenticate()
    client = TestClient(main.app)

    extra = client.post(
        "/api/research-os/platform/source_lineage/M15/current",
        json={
            "anchor_ref": "desk_topology_receipt:m15",
            "rag_ref": "caller:forged",
        },
    )
    assert extra.status_code == 422, extra.text
    assert finalizer.calls == 0

    partial = client.post(
        "/api/research-os/platform/source_lineage/M15/current",
        json={"anchor_ref": "desk_topology_receipt:m15"},
    )
    assert partial.status_code == 409, partial.text
    assert partial.json()["detail"] == {
        "message": "platform source-lineage finalization is incomplete",
        "coverage_persisted": True,
        "rag_persisted": False,
        "row_source_persisted": False,
        "row_source_certified": False,
    }


def test_backtest_evidence_api_derives_records_is_idempotent_and_rechecks_current(
    tmp_path,
    monkeypatch,
) -> None:
    resolver = _ArtifactResolver()
    registry = PersistentBacktestEvidenceRegistry(
        tmp_path / "backtest_evidence.jsonl",
        artifact_resolver=resolver,
    )
    monkeypatch.setattr(main, "BACKTEST_ATTRIBUTION_ARTIFACT_RESOLVER", resolver)
    monkeypatch.setattr(main, "BACKTEST_EVIDENCE_REGISTRY", registry)
    monkeypatch.setattr(
        main,
        "VALIDATION_METHODOLOGY_REGISTRY",
        _ValidationMethodologyRegistry(),
    )
    monkeypatch.setattr(
        main,
        "VALIDATION_DEPTH_REGISTRY",
        _ValidationDepthRegistry(),
    )
    _authenticate()
    client = TestClient(main.app)
    attribution_payload = {
        "backtest_run_ref": "backtest_run:platform-api",
        "source_run_ref": "ide_run:platform-api",
        "validation_methodology_ref": "validation_methodology:platform-api",
        "validation_depth_ref": "validation_depth:platform-api",
        "cost_model_refs": ["cost_model:fees", "cost_model:slippage"],
    }

    first = client.post(
        "/api/research-os/backtests/attributions/current",
        json=attribution_payload,
    )
    assert first.status_code == 200, first.text
    attribution = first.json()
    assert attribution["owner_user_id"] == OWNER
    assert attribution["recorded_by"] == OWNER
    assert attribution["artifact_path"] == "attribution.csv"
    assert attribution["artifact_sha256"] == resolver.state.artifact_sha256
    assert attribution["row_count"] == resolver.state.row_count
    assert attribution["component_refs"] == list(resolver.state.component_refs)
    assert all(call[0] == OWNER for call in resolver.calls)

    attribution_bytes = registry.path.read_bytes()
    replay = client.post(
        "/api/research-os/backtests/attributions/current",
        json=attribution_payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["attribution_ref"] == attribution["attribution_ref"]
    assert registry.path.read_bytes() == attribution_bytes

    for forged_field, forged_value in (
        ("artifact_sha256", "sha256:" + "f" * 64),
        ("row_count", 999),
        ("component_refs", ["attribution_component:client-forged"]),
        ("attribution_ref", "attribution:client-forged"),
        ("owner_user_id", OTHER_OWNER),
        ("recorded_by", OTHER_OWNER),
    ):
        forged = client.post(
            "/api/research-os/backtests/attributions/current",
            json={**attribution_payload, forged_field: forged_value},
        )
        assert forged.status_code == 422, forged.text
        assert registry.path.read_bytes() == attribution_bytes

    wrong_cost_binding = client.post(
        "/api/research-os/backtests/attributions/current",
        json={**attribution_payload, "cost_model_refs": ["cost_model:client"]},
    )
    assert wrong_cost_binding.status_code == 422, wrong_cost_binding.text
    assert registry.path.read_bytes() == attribution_bytes

    monitor_payload = {
        "attribution_ref": attribution["attribution_ref"],
        "monitoring_profile_ref": "monitoring_profile:platform-api",
        "performance_primary_alert_ref": "performance_alert:platform-api",
        "cost_drift_ref": "cost_drift:platform-api",
        "drift_root_cause_ref": "drift_root_cause:platform-api",
        "mathematical_trigger_refs": ["math_trigger:drawdown"],
        "evidence_refs": [
            attribution["attribution_ref"],
            "monitoring_profile:platform-api",
            "performance_alert:platform-api",
            "cost_drift:platform-api",
            "drift_root_cause:platform-api",
            "math_trigger:drawdown",
        ],
        "used_dsr_as_primary_live_alert": False,
    }
    monitor_candidate = BacktestMonitorRecord(
        owner_user_id=OWNER,
        recorded_by=OWNER,
        backtest_run_ref=attribution_payload["backtest_run_ref"],
        attribution_ref=attribution["attribution_ref"],
        monitoring_profile_ref=monitor_payload["monitoring_profile_ref"],
        performance_primary_alert_ref=monitor_payload[
            "performance_primary_alert_ref"
        ],
        cost_drift_ref=monitor_payload["cost_drift_ref"],
        drift_root_cause_ref=monitor_payload["drift_root_cause_ref"],
        mathematical_trigger_refs=tuple(
            monitor_payload["mathematical_trigger_refs"]
        ),
        evidence_refs=tuple(monitor_payload["evidence_refs"]),
        used_dsr_as_primary_live_alert=False,
    )
    spine = _SpineRegistry(monitor_candidate)
    monkeypatch.setattr(main, "MODEL_GOVERNANCE_REGISTRY", _ModelGovernanceRegistry())
    monkeypatch.setattr(main, "MATHEMATICAL_SPINE_CHAIN_REGISTRY", spine)
    before_monitor = registry.path.read_bytes()
    spine.drifted = True
    unbacked_monitor = client.post(
        "/api/research-os/backtests/monitors/current",
        json=monitor_payload,
    )
    assert unbacked_monitor.status_code == 422, unbacked_monitor.text
    assert registry.path.read_bytes() == before_monitor
    spine.drifted = False
    monitor_response = client.post(
        "/api/research-os/backtests/monitors/current",
        json=monitor_payload,
    )
    assert monitor_response.status_code == 200, monitor_response.text
    monitor = monitor_response.json()
    assert monitor["owner_user_id"] == OWNER
    assert monitor["backtest_run_ref"] == attribution_payload["backtest_run_ref"]
    assert monitor["attribution_ref"] == attribution["attribution_ref"]

    monitor_bytes = registry.path.read_bytes()
    for forged_field in ("monitor_ref", "backtest_run_ref", "owner_user_id"):
        forged_monitor = client.post(
            "/api/research-os/backtests/monitors/current",
            json={**monitor_payload, forged_field: "client:forged"},
        )
        assert forged_monitor.status_code == 422, forged_monitor.text
        assert registry.path.read_bytes() == monitor_bytes

    monitor_replay = client.post(
        "/api/research-os/backtests/monitors/current",
        json=monitor_payload,
    )
    assert monitor_replay.status_code == 200, monitor_replay.text
    assert monitor_replay.json()["monitor_ref"] == monitor["monitor_ref"]
    assert registry.path.read_bytes() == monitor_bytes

    current = client.get(
        "/api/research-os/backtests/evidence/current",
        params={"backtest_run_ref": attribution_payload["backtest_run_ref"]},
    )
    assert current.status_code == 200, current.text
    assert current.json()["complete"] is True
    assert current.json()["attribution"]["current"] is True
    assert current.json()["monitor"]["current"] is True

    spine.drifted = True
    stale_monitor = client.get(
        "/api/research-os/backtests/evidence/current",
        params={"backtest_run_ref": attribution_payload["backtest_run_ref"]},
    )
    assert stale_monitor.status_code == 422, stale_monitor.text
    assert "typed sources could not be validated" in stale_monitor.text
    spine.drifted = False

    _authenticate(OTHER_OWNER, "other")
    hidden = client.get(
        "/api/research-os/backtests/evidence/current",
        params={"backtest_run_ref": attribution_payload["backtest_run_ref"]},
    )
    assert hidden.status_code == 404, hidden.text

    _authenticate()
    resolver.state = BacktestArtifactState(
        artifact_sha256="sha256:" + "d" * 64,
        row_count=3,
        component_refs=resolver.state.component_refs,
    )
    stale = client.get(
        "/api/research-os/backtests/evidence/current",
        params={"backtest_run_ref": attribution_payload["backtest_run_ref"]},
    )
    assert stale.status_code == 422, stale.text
    assert "could not be validated" in stale.text


def test_teaching_asset_api_derives_identity_isolates_owner_and_reports_drift(
    tmp_path,
    monkeypatch,
) -> None:
    lifecycle = _TeachingLifecycle()
    registry = PersistentTeachingAssetRegistry(
        tmp_path / "teaching_assets.jsonl",
        lifecycle_registry=lifecycle,
    )
    monkeypatch.setattr(main, "ASSET_LIFECYCLE_REGISTRY", lifecycle)
    monkeypatch.setattr(main, "TEACHING_ASSET_REGISTRY", registry)
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_HISTORY_M16_M21_RECORDER",
        SimpleNamespace(
            record=lambda **kwargs: PlatformBusinessHistoryM16M21Result(
                owner_user_id=kwargs["owner_user_id"],
                row=kwargs["row"],
                anchor_ref=kwargs["anchor_ref"],
                entrypoint_ref="api:research_os.teaching.assets",
                qro_ref="qro:test:teaching-asset",
                graph_command_ref="rgcmd_test_teaching_asset",
                graph_command_created=True,
                compiler_ir_ref="compiler_ir:test:teaching-asset",
                compiler_pass_ref="compiler_pass:test:teaching-asset",
                entrypoint_coverage_ref="goal_entrypoint_coverage:test:teaching-asset",
            )
        ),
    )
    _authenticate()
    client = TestClient(main.app)
    payload = {
        "governed_asset_ref": "governed_asset:teaching-api",
        "title": "API tutorial",
        "weakness_refs": ["weakness:limited-history"],
        "evidence_refs": ["evidence:tutorial-test", "evidence:tutorial-doc"],
    }

    first = client.post("/api/research-os/teaching/assets", json=payload)
    assert first.status_code == 200, first.text
    asset = first.json()
    assert asset["current"] is True
    assert asset["tutorial"]["owner_user_id"] == OWNER
    assert asset["tutorial"]["category"] == "tutorial"
    assert asset["tutorial"]["tutorial_asset_ref"].startswith("tutorial_asset:")
    assert asset["weakness"]["visible_by_default"] is True
    assert asset["evidence"]["teaching_evidence_ref"].startswith(
        "teaching_evidence:"
    )

    first_bytes = registry.path.read_bytes()
    replay = client.post("/api/research-os/teaching/assets", json=payload)
    assert replay.status_code == 200, replay.text
    assert (
        replay.json()["tutorial"]["tutorial_asset_ref"]
        == asset["tutorial"]["tutorial_asset_ref"]
    )
    assert registry.path.read_bytes() == first_bytes

    forged = client.post(
        "/api/research-os/teaching/assets",
        json={**payload, "tutorial_asset_ref": "tutorial_asset:client-forged"},
    )
    assert forged.status_code == 422, forged.text
    assert registry.path.read_bytes() == first_bytes

    listing = client.get("/api/research-os/teaching/assets")
    assert listing.status_code == 200, listing.text
    assert listing.json()["asset_total"] == 1
    assert listing.json()["current_asset_total"] == 1

    _authenticate(OTHER_OWNER, "other")
    hidden = client.get("/api/research-os/teaching/assets")
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["asset_total"] == 0

    _authenticate()
    lifecycle.assets.clear()
    stale = client.get("/api/research-os/teaching/assets")
    assert stale.status_code == 200, stale.text
    assert stale.json()["current_asset_total"] == 0
    assert stale.json()["assets"][0]["current"] is False
    assert "unavailable for owner" in stale.json()["assets"][0]["current_error"]


def test_platform_evidence_routes_are_registered() -> None:
    routes = {
        (route.path, method)
        for route in main.app.routes
        for method in getattr(route, "methods", ())
    }
    assert ("/api/research-os/platform/row_sources/{m_row}/current", "POST") in routes
    assert ("/api/research-os/platform/row_sources/{m_row}/current", "GET") in routes
    assert ("/api/research-os/platform/row_sources/current", "GET") in routes
    assert ("/api/research-os/backtests/attributions/current", "POST") in routes
    assert ("/api/research-os/backtests/monitors/current", "POST") in routes
    assert ("/api/research-os/backtests/evidence/current", "GET") in routes
    assert ("/api/research-os/teaching/assets", "POST") in routes
    assert ("/api/research-os/teaching/assets", "GET") in routes
