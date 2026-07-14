from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.compiler import PersistentCompilerIRStore
from app.research_os.goal_coverage import PersistentGoalEntrypointCoverageRegistry
from app.research_os.platform_business_attestations import (
    ENTRYPOINT_REFS,
    PlatformBusinessAttestationContext,
    PlatformBusinessAttestationService,
)
from app.research_os.platform_source_lineage_policies_m16_m21 import (
    PlatformSourceLineagePolicyM16M21Error,
    build_platform_source_lineage_policy_resolver_m16_m21,
)
from app.research_os.spine import EntrySource, PersistentResearchGraphStore
from tests.test_platform_business_attestations import (
    OWNER,
    _CompilerHarness,
    _m17_system,
    _m18_system,
    _m20_system,
    _policy_context,
)


_ROW_CASES = (
    ("M17", _m17_system, "submission_ref"),
    ("M18", _m18_system, "consistency_check_ref"),
    ("M20", _m20_system, "kill_switch_ref"),
)


@pytest.fixture(autouse=True)
def _clear_auth_override():
    main.app.dependency_overrides.pop(require_user_dependency, None)
    yield
    main.app.dependency_overrides.pop(require_user_dependency, None)


class _PersistentCoverageResolver:
    """Resolve strict coverage against the temp-backed integration stores."""

    def __init__(
        self,
        *,
        owner: str,
        row: str,
        graph: PersistentResearchGraphStore,
        compiler: PersistentCompilerIRStore,
        source_context: PlatformBusinessAttestationContext,
    ) -> None:
        self.owner = owner
        self.row = row
        self.graph = graph
        self.compiler = compiler
        self.source_context = source_context

    def for_owner(self, owner: str):
        if owner != self.owner:
            raise KeyError(owner)
        return self

    def has_qro(self, ref: str) -> bool:
        try:
            return self.graph.qro(ref).owner == self.owner
        except (KeyError, LookupError):
            return False

    def has_research_graph_command(self, ref: str) -> bool:
        return (
            sum(
                command.command_id == ref and command.actor == self.owner
                for command in self.graph.commands()
            )
            == 1
        )

    def has_compiler_ir(self, ref: str) -> bool:
        try:
            return self.compiler.ir(ref, owner=self.owner).owner == self.owner
        except (KeyError, LookupError):
            return False

    def has_compiler_pass(self, ref: str) -> bool:
        try:
            return (
                self.compiler.compiler_pass(ref, owner=self.owner).actor
                == self.owner
            )
        except (KeyError, LookupError):
            return False

    def has_evidence(self, ref: str) -> bool:
        records = (
            *self.compiler.irs(owner=self.owner),
            *self.compiler.passes(owner=self.owner),
        )
        return any(ref in tuple(record.evidence_refs) for record in records)

    def has_lifecycle_record(self, ref: str) -> bool:
        context = self.source_context
        try:
            if self.row == "M17":
                return (
                    context.runtime_promotion_registry.promotion(ref)
                    is not None
                )
            if self.row == "M18":
                return sum(
                    manifest.package_id == ref
                    for manifest in context.rdp_store.manifests(
                        owner_user_id=self.owner
                    )
                ) == 1
            if self.row == "M20":
                halt = context.account_halt_barrier.halt_evidence(
                    ref,
                    owner_user_id=self.owner,
                )
                return halt.halt_ref == ref
        except (KeyError, LookupError):
            return False
        return False

    def has_rdp(self, ref: str) -> bool:
        if self.row != "M18":
            return False
        try:
            return sum(
                manifest.package_id == ref
                for manifest in self.source_context.rdp_store.manifests(
                    owner_user_id=self.owner
                )
            ) == 1
        except (KeyError, LookupError):
            return False

    def entrypoint_linkage_violations(self, record: Any):
        refs = (
            tuple(record.qro_refs),
            tuple(record.research_graph_command_refs),
            tuple(record.compiler_ir_refs),
            tuple(record.compiler_pass_refs),
        )
        if any(len(group) != 1 for group in refs):
            return (
                (
                    "entrypoint_ref",
                    record.entrypoint_ref,
                    "coverage must select one QRO, Graph command, IR, and pass",
                ),
            )
        qro_ref, graph_ref, ir_ref, pass_ref = (
            group[0] for group in refs
        )
        try:
            qro = self.graph.qro(qro_ref)
            command = next(
                item
                for item in self.graph.commands()
                if item.command_id == graph_ref
            )
            compiler_ir = self.compiler.ir(ir_ref, owner=self.owner)
            compiler_pass = self.compiler.compiler_pass(
                pass_ref,
                owner=self.owner,
            )
        except (KeyError, LookupError, StopIteration):
            return (
                (
                    "entrypoint_ref",
                    record.entrypoint_ref,
                    "coverage lineage does not resolve through persistent stores",
                ),
            )
        embedded = command.payload.get("qro") if isinstance(command.payload, dict) else None
        canonical_refs = tuple(compiler_ir.canonical_command_refs)
        if (
            embedded != qro
            or qro.owner != self.owner
            or command.actor != self.owner
            or command.source != EntrySource.API
            or tuple(compiler_ir.source_qro_refs) != (qro_ref,)
            or tuple(compiler_ir.graph_command_refs) != (graph_ref,)
            or tuple(compiler_pass.input_qro_refs) != (qro_ref,)
            or tuple(compiler_pass.graph_command_refs) != (graph_ref,)
            or compiler_pass.output_ir_ref != ir_ref
            or tuple(compiler_pass.canonical_command_refs) != canonical_refs
            or tuple(record.canonical_command_refs) != canonical_refs
            or f"research_graph_command:{graph_ref}" not in canonical_refs
            or f"entrypoint:{record.entrypoint_ref}" not in canonical_refs
        ):
            return (
                (
                    "entrypoint_ref",
                    record.entrypoint_ref,
                    "coverage recombines QRO, Graph, compiler, or provenance state",
                ),
            )
        return ()


class _FailOncePersistentGraph(PersistentResearchGraphStore):
    fail_next_api_append = False

    def apply(self, command):
        if self.fail_next_api_append and command.source == EntrySource.API:
            self.fail_next_api_append = False
            raise OSError("injected Research Graph append failure")
        return super().apply(command)


class _FailOncePersistentCoverage(PersistentGoalEntrypointCoverageRegistry):
    fail_next_record = False

    def record_coverage(self, record):
        if self.fail_next_record:
            self.fail_next_record = False
            raise OSError("injected GOAL coverage append failure")
        return super().record_coverage(record)


class _PersistentCompilerAdapter:
    def __init__(
        self,
        *,
        compiler: PersistentCompilerIRStore,
        coverage: PersistentGoalEntrypointCoverageRegistry,
        fail_after_ir_once: bool = False,
    ) -> None:
        self.compiler = compiler
        self.coverage = coverage
        self.fail_after_ir_once = fail_after_ir_once
        self.calls = 0

    def compile(self, qro, command, plan):
        self.calls += 1
        built = _CompilerHarness()
        result = built.compile(qro, command, plan)
        ir = built.store.irs(owner=plan.owner_user_id)[0]
        compiler_pass = built.store.passes(owner=plan.owner_user_id)[0]
        coverage = built.coverage.records(owner=plan.owner_user_id)[0]
        self.compiler.record_ir(ir)
        if self.fail_after_ir_once:
            self.fail_after_ir_once = False
            raise OSError("injected Governed Compiler append failure after IR")
        self.compiler.record_pass(compiler_pass)
        self.coverage.record_coverage(coverage)
        return result


class _CoverageOverlay:
    def __init__(self, base, mutated) -> None:
        self.base = base
        self.mutated = mutated

    def records(self, *, owner: str | None = None):
        if owner is not None and owner != self.mutated.recorded_by:
            return []
        return [self.mutated]

    def coverage(self, ref: str, *, owner: str | None = None):
        if (
            ref != self.mutated.coverage_ref
            or (owner is not None and owner != self.mutated.recorded_by)
        ):
            raise KeyError(ref)
        return self.mutated

    def validate_real_backing(self, record):
        return self.base.validate_real_backing(record)


def _http_client() -> TestClient:
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=OWNER,
        username="platform-business-attestation-http-e2e",
    )
    return TestClient(main.app)


def _build_runtime(
    tmp_path: Path,
    *,
    row: str,
    factory,
    failure: str | None = None,
):
    base = factory()
    # The production ExecutionOrderIntentRecord always carries its authenticated
    # owner.  The small shared unit fixture predates that field, so make the HTTP
    # integration source match the real typed record before composing stores.
    if row == "M17" and not hasattr(base.intent, "recorded_by"):
        base.intent.recorded_by = OWNER
    graph = _FailOncePersistentGraph(tmp_path / "research_graph.jsonl")
    for command in base.graph.commands():
        graph.apply(command)
    graph.fail_next_api_append = failure == "graph"

    compiler = PersistentCompilerIRStore(tmp_path / "compiler.jsonl")
    resolver = _PersistentCoverageResolver(
        owner=OWNER,
        row=row,
        graph=graph,
        compiler=compiler,
        source_context=base.context,
    )
    coverage = _FailOncePersistentCoverage(
        tmp_path / "coverage.jsonl",
        resolver=resolver,
    )
    coverage.fail_next_record = failure == "coverage"
    adapter = _PersistentCompilerAdapter(
        compiler=compiler,
        coverage=coverage,
        fail_after_ir_once=failure == "compiler",
    )
    context = replace(
        base.context,
        research_graph_store=graph,
        compiler_store=compiler,
        entrypoint_registry=coverage,
        compile_attestation=adapter.compile,
    )
    service = PlatformBusinessAttestationService(context)
    return SimpleNamespace(
        base=base,
        row=row,
        graph=graph,
        compiler=compiler,
        coverage=coverage,
        resolver=resolver,
        adapter=adapter,
        context=context,
        service=service,
        harness=SimpleNamespace(store=compiler, coverage=coverage),
        paths={
            "graph": graph.path,
            "compiler": compiler.path,
            "coverage": coverage.path,
        },
    )


def _post(client: TestClient, *, row: str, anchor_ref: str):
    return client.post(
        f"/api/research-os/platform/business_attestations/{row}/current",
        json={"anchor_ref": anchor_ref},
    )


def _resolve_policy(runtime, *, anchor_ref: str):
    return build_platform_source_lineage_policy_resolver_m16_m21(
        _policy_context(runtime, row=runtime.row)
    ).resolve(
        owner_user_id=OWNER,
        m_row=runtime.row,
        anchor_ref=anchor_ref,
    )


def _assert_no_business_side_effects(runtime) -> None:
    if runtime.row == "M17":
        assert runtime.base.copy_trade.relay_calls == 0
        assert runtime.base.risks.reserve_calls == 0
        assert runtime.base.submissions.record_calls == 0
    elif runtime.row == "M18":
        assert runtime.base.rdp.mutation_calls == 0
    elif runtime.row == "M20":
        assert runtime.base.halts.mutation_calls == 0


@pytest.mark.parametrize(("row", "factory", "anchor_key"), _ROW_CASES)
def test_actual_http_route_persists_server_owned_proof_and_real_policy_consumes_it(
    tmp_path: Path,
    monkeypatch,
    row: str,
    factory,
    anchor_key: str,
) -> None:
    runtime = _build_runtime(tmp_path, row=row, factory=factory)
    anchor_ref = runtime.base.refs[anchor_key]
    monkeypatch.setattr(main, "PLATFORM_BUSINESS_ATTESTATION_SERVICE", runtime.service)

    with _http_client() as client:
        response = _post(client, row=row, anchor_ref=anchor_ref)

    assert response.status_code == 200, response.text
    payload = response.json()
    qro = runtime.graph.qro(payload["qro_ref"])
    command = next(
        item
        for item in runtime.graph.commands()
        if item.command_id == payload["graph_command_ref"]
    )
    coverage = runtime.coverage.coverage(
        payload["entrypoint_coverage_ref"],
        owner=OWNER,
    )
    compiler_ir = runtime.compiler.ir(payload["compiler_ir_ref"], owner=OWNER)
    compiler_pass = runtime.compiler.compiler_pass(
        payload["compiler_pass_ref"],
        owner=OWNER,
    )

    assert payload["entrypoint_ref"] == ENTRYPOINT_REFS[row]
    assert payload["business_side_effects_performed"] is False
    assert payload["graph_attestation_current"] is True
    assert payload["compiler_bundle_verified"] is True
    assert payload["coverage_persisted"] is True
    assert qro.input_contract == runtime.base.refs
    assert qro.mathematical_refs == (payload["math_spine_ref"],)
    assert command.tool_record_refs == (ENTRYPOINT_REFS[row],)
    assert coverage.entry_source == EntrySource.API
    assert coverage.entrypoint_ref == ENTRYPOINT_REFS[row]
    assert "§14" not in coverage.goal_sections
    assert tuple(compiler_ir.source_qro_refs) == (qro.qro_id,)
    assert tuple(compiler_pass.input_qro_refs) == (qro.qro_id,)
    assert all(path.exists() and path.stat().st_size > 0 for path in runtime.paths.values())

    resolution = _resolve_policy(runtime, anchor_ref=anchor_ref)
    assert resolution.qro_ref == payload["qro_ref"]
    assert resolution.business_entrypoint_ref == ENTRYPOINT_REFS[row]
    assert resolution.math_spine_ref == payload["math_spine_ref"]
    _assert_no_business_side_effects(runtime)


def test_actual_http_route_replays_from_fresh_persistent_stores_without_recompile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = _build_runtime(tmp_path, row="M17", factory=_m17_system)
    anchor_ref = runtime.base.refs["submission_ref"]
    monkeypatch.setattr(main, "PLATFORM_BUSINESS_ATTESTATION_SERVICE", runtime.service)
    with _http_client() as client:
        first = _post(client, row="M17", anchor_ref=anchor_ref)
    assert first.status_code == 200, first.text
    assert runtime.adapter.calls == 1

    replay_graph = _FailOncePersistentGraph(runtime.paths["graph"])
    replay_compiler = PersistentCompilerIRStore(runtime.paths["compiler"])
    replay_resolver = _PersistentCoverageResolver(
        owner=OWNER,
        row="M17",
        graph=replay_graph,
        compiler=replay_compiler,
        source_context=runtime.base.context,
    )
    replay_coverage = _FailOncePersistentCoverage(
        runtime.paths["coverage"],
        resolver=replay_resolver,
    )
    replay_adapter = _PersistentCompilerAdapter(
        compiler=replay_compiler,
        coverage=replay_coverage,
    )
    replay_context = replace(
        runtime.base.context,
        research_graph_store=replay_graph,
        compiler_store=replay_compiler,
        entrypoint_registry=replay_coverage,
        compile_attestation=replay_adapter.compile,
    )
    replay_runtime = SimpleNamespace(
        **{
            **vars(runtime),
            "graph": replay_graph,
            "compiler": replay_compiler,
            "coverage": replay_coverage,
            "context": replay_context,
            "service": PlatformBusinessAttestationService(replay_context),
            "adapter": replay_adapter,
            "harness": SimpleNamespace(
                store=replay_compiler,
                coverage=replay_coverage,
            ),
        }
    )
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_ATTESTATION_SERVICE",
        replay_runtime.service,
    )
    with _http_client() as client:
        second = _post(client, row="M17", anchor_ref=anchor_ref)

    assert second.status_code == 200, second.text
    assert second.json() == {
        **first.json(),
        "graph_command_created": False,
    }
    assert replay_adapter.calls == 0
    assert len(replay_graph.commands()) == 1
    assert _resolve_policy(replay_runtime, anchor_ref=anchor_ref).qro_ref == first.json()[
        "qro_ref"
    ]
    _assert_no_business_side_effects(replay_runtime)


def test_actual_http_route_and_policy_reject_current_business_source_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = _build_runtime(tmp_path, row="M17", factory=_m17_system)
    anchor_ref = runtime.base.refs["submission_ref"]
    monkeypatch.setattr(main, "PLATFORM_BUSINESS_ATTESTATION_SERVICE", runtime.service)
    with _http_client() as client:
        first = _post(client, row="M17", anchor_ref=anchor_ref)
        assert first.status_code == 200, first.text
        runtime.base.follower.status = "stopped"
        drifted = _post(client, row="M17", anchor_ref=anchor_ref)

    assert drifted.status_code == 422, drifted.text
    assert "stale or recombined" in drifted.json()["detail"]
    assert len(runtime.coverage.records(owner=OWNER)) == 1
    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        _resolve_policy(runtime, anchor_ref=anchor_ref)
    _assert_no_business_side_effects(runtime)


@pytest.mark.parametrize("mutation", ("provenance", "sections"))
def test_actual_http_replay_and_policy_reject_exact_coverage_mutation(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    runtime = _build_runtime(tmp_path, row="M17", factory=_m17_system)
    anchor_ref = runtime.base.refs["submission_ref"]
    monkeypatch.setattr(main, "PLATFORM_BUSINESS_ATTESTATION_SERVICE", runtime.service)
    with _http_client() as client:
        first = _post(client, row="M17", anchor_ref=anchor_ref)
    assert first.status_code == 200, first.text

    original = runtime.coverage.records(owner=OWNER)[0]
    mutated = (
        replace(original, entry_source=EntrySource.IDE)
        if mutation == "provenance"
        else replace(original, goal_sections=(*original.goal_sections, "§17"))
    )
    overlay = _CoverageOverlay(runtime.coverage, mutated)
    mutated_context = replace(
        runtime.context,
        entrypoint_view_factory=lambda: overlay,
    )
    monkeypatch.setattr(
        main,
        "PLATFORM_BUSINESS_ATTESTATION_SERVICE",
        PlatformBusinessAttestationService(mutated_context),
    )
    with _http_client() as client:
        replay = _post(client, row="M17", anchor_ref=anchor_ref)

    assert replay.status_code == 422, replay.text
    policy_context = replace(
        _policy_context(runtime, row="M17"),
        entrypoint_view_factory=lambda: overlay,
    )
    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(
            policy_context
        ).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=anchor_ref,
        )
    _assert_no_business_side_effects(runtime)


@pytest.mark.parametrize("failure", ("graph", "compiler", "coverage"))
def test_failed_http_commit_has_no_policy_accessible_attestation_and_retry_repairs(
    tmp_path: Path,
    monkeypatch,
    failure: str,
) -> None:
    runtime = _build_runtime(
        tmp_path,
        row="M17",
        factory=_m17_system,
        failure=failure,
    )
    anchor_ref = runtime.base.refs["submission_ref"]
    monkeypatch.setattr(main, "PLATFORM_BUSINESS_ATTESTATION_SERVICE", runtime.service)
    with _http_client() as client:
        failed = _post(client, row="M17", anchor_ref=anchor_ref)

        assert failed.status_code == 409, failed.text
        expected_phase = "research_graph" if failure == "graph" else "compiler_coverage"
        assert failed.json()["detail"]["phase"] == expected_phase
        assert runtime.coverage.records(owner=OWNER) == []
        with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
            _resolve_policy(runtime, anchor_ref=anchor_ref)
        _assert_no_business_side_effects(runtime)

        repaired = _post(client, row="M17", anchor_ref=anchor_ref)

    assert repaired.status_code == 200, repaired.text
    assert len(runtime.coverage.records(owner=OWNER)) == 1
    assert _resolve_policy(runtime, anchor_ref=anchor_ref).qro_ref == repaired.json()[
        "qro_ref"
    ]
    _assert_no_business_side_effects(runtime)
