from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.research_os.qro_spine_binding import (
    QROSpineBindingCommitError,
    QROSpineBindingError,
    current_qro_spine_binding_is_observed,
    prepare_current_qro_spine_binding,
    record_current_qro_spine_binding,
)
from app.research_os.spine import (
    ActorSource,
    EntrySource,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphError,
    ResearchGraphStore,
)


OWNER = "owner:qro-spine-binding"
CHAIN_REF = "math_spine_chain:qro-binding:v1"


def _qro(*, mathematical_refs: tuple[str, ...] = ()) -> QRORecord:
    return QRORecord(
        qro_type=QROType.FACTOR,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract={"factor_ref": "factor:momentum:v1"},
        output_contract={"status": "recorded"},
        market="equity",
        universe="cn_equity",
        horizon="daily",
        frequency="1d",
        lineage=("factor:momentum:v1",),
        implementation_hash="factor:momentum:implementation:v1",
        assumptions=("The factor input is point-in-time safe.",),
        known_limits=("The factor is not an execution instruction.",),
        failure_modes=("Stale data invalidates the factor.",),
        validation_plan=("Run leakage and replay checks.",),
        mathematical_refs=mathematical_refs,
    )


def _graph(qro: QRORecord, *, actor: str = OWNER) -> ResearchGraphStore:
    graph = ResearchGraphStore()
    graph.apply(
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=actor,
            payload={"qro": qro},
        )
    )
    return graph


def _chain(*, owner: str = OWNER, ref: str = CHAIN_REF):
    return SimpleNamespace(chain_ref=ref, recorded_by=owner)


def test_prepares_only_mathematical_binding_and_preserves_business_identity() -> None:
    original = _qro()
    graph = _graph(original)

    plan = prepare_current_qro_spine_binding(
        research_graph_store=graph,
        qro_ref=original.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
    )

    assert plan.current_qro == original
    assert plan.bound_qro.qro_id == original.qro_id
    assert plan.bound_qro.input_contract == original.input_contract
    assert plan.bound_qro.output_contract == original.output_contract
    assert plan.bound_qro.implementation_hash == original.implementation_hash
    assert plan.bound_qro.mathematical_refs == (CHAIN_REF,)
    assert plan.already_bound is False


def test_same_chain_is_idempotent_and_delegated_prior_actor_is_preserved() -> None:
    bound = _qro(mathematical_refs=(CHAIN_REF,))
    graph = _graph(bound, actor="reviewer:delegated")

    plan = prepare_current_qro_spine_binding(
        research_graph_store=graph,
        qro_ref=bound.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
    )

    assert plan.bound_qro is bound
    assert plan.already_bound is True
    assert plan.prior_command.actor == "reviewer:delegated"


def test_existing_different_or_duplicate_math_binding_fails_closed() -> None:
    different = _qro(mathematical_refs=("math_spine_chain:other:v1",))
    with pytest.raises(QROSpineBindingError, match="different"):
        prepare_current_qro_spine_binding(
            research_graph_store=_graph(different),
            qro_ref=different.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
        )

    duplicate = _qro(mathematical_refs=(CHAIN_REF, CHAIN_REF))
    with pytest.raises(QROSpineBindingError, match="duplicates"):
        prepare_current_qro_spine_binding(
            research_graph_store=_graph(duplicate),
            qro_ref=duplicate.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
        )


def test_owner_mismatch_placeholder_and_missing_qro_fail_before_writes() -> None:
    original = _qro()
    graph = _graph(original)
    command_count = len(graph.commands())

    with pytest.raises(QROSpineBindingError, match="owner mismatch"):
        prepare_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(owner="owner:foreign"),
        )
    with pytest.raises(QROSpineBindingError, match="exact stable ref"):
        prepare_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref="qro_placeholder",
            owner_user_id=OWNER,
            verified_chain=_chain(),
        )
    with pytest.raises(QROSpineBindingError, match="unavailable:KeyError"):
        prepare_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref="qro_missing",
            owner_user_id=OWNER,
            verified_chain=_chain(),
        )
    assert len(graph.commands()) == command_count


def test_stale_projection_command_qro_is_rejected() -> None:
    original = _qro()
    graph = _graph(original)
    current_command = graph.commands()[0]
    graph._commands[0] = replace(  # test-only corruption of the in-memory projection source.
        current_command,
        payload={"qro": replace(original, output_contract={"status": "stale"})},
    )

    with pytest.raises(QROSpineBindingError, match="stale or recombined"):
        prepare_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
        )


def test_projection_cardinality_and_foreign_projection_owner_fail_closed() -> None:
    original = _qro()

    class _NoProjectionGraph:
        def qro(self, ref: str):
            assert ref == original.qro_id
            return original

        def projection_index(self, *, owner: str):
            return ()

        def commands(self):
            return ()

    with pytest.raises(QROSpineBindingError, match="exactly one"):
        prepare_current_qro_spine_binding(
            research_graph_store=_NoProjectionGraph(),
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
        )

    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": original},
    )
    projection = SimpleNamespace(
        qro_id=original.qro_id,
        command_id=command.command_id,
        owner="owner:foreign",
    )

    class _ForeignProjectionGraph(_NoProjectionGraph):
        def projection_index(self, *, owner: str):
            return (projection,)

        def commands(self):
            return (command,)

    with pytest.raises(QROSpineBindingError, match="projection owner mismatch"):
        prepare_current_qro_spine_binding(
            research_graph_store=_ForeignProjectionGraph(),
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
        )


def _compile_result():
    return {
        "compiler_ir_ref": "compiler_ir:qro-binding",
        "compiler_pass_ref": "compiler_pass:qro-binding",
        "entrypoint_coverage_ref": "goal_entrypoint_coverage:qro-binding",
    }


def test_record_binding_appends_one_owner_api_head_and_retry_reuses_it() -> None:
    original = _qro()
    graph = _graph(original, actor="reviewer:historical")
    seen: list[tuple[QRORecord, ResearchGraphCommand]] = []

    def compile_binding(qro, command):
        seen.append((qro, command))
        return _compile_result()

    first = record_current_qro_spine_binding(
        research_graph_store=graph,
        qro_ref=original.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
        entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
        compile_binding=compile_binding,
    )

    assert first.graph_command_created is True
    assert len(graph.commands()) == 2
    binding_command = graph.commands()[-1]
    assert binding_command.command_id == first.graph_command_ref
    assert binding_command.actor == OWNER
    assert binding_command.source == EntrySource.API
    assert binding_command.actor_source == ActorSource.USER_MANUAL
    assert binding_command.tool_record_refs == (
        "api:research_os.platform.spine_bindings.m4_m5",
    )
    assert binding_command.evidence_refs == (
        CHAIN_REF,
        graph.commands()[0].command_id,
    )
    assert graph.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)
    assert seen[-1] == (graph.qro(original.qro_id), binding_command)

    second = record_current_qro_spine_binding(
        research_graph_store=graph,
        qro_ref=original.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
        entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
        compile_binding=compile_binding,
    )

    assert second.graph_command_created is False
    assert second.graph_command_ref == first.graph_command_ref
    assert len(graph.commands()) == 2
    assert len(seen) == 2


@pytest.mark.parametrize(
    "entrypoint",
    (
        "api:research_os.platform.spine_bindings.m4_m5",
        "api:research_os.platform.business_attestations.m17",
    ),
)
def test_platform_bound_qro_rejects_overwrite_and_observer_detects_projection_drift(
    entrypoint: str,
) -> None:
    original = _qro()
    graph = _graph(original)
    result = record_current_qro_spine_binding(
        research_graph_store=graph,
        qro_ref=original.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
        entrypoint_ref=entrypoint,
        compile_binding=lambda _qro, _command: _compile_result(),
    )
    assert current_qro_spine_binding_is_observed(
        research_graph_store=graph,
        owner_user_id=OWNER,
        qro_ref=original.qro_id,
        chain_ref=CHAIN_REF,
        entrypoint_ref=entrypoint,
        graph_command_ref=result.graph_command_ref,
    )

    with pytest.raises(ResearchGraphError, match="platform-bound QRO is immutable"):
        graph.apply(
            ResearchGraphCommand(
                source=EntrySource.API,
                command_type="upsert_qro",
                actor_source=ActorSource.USER_MANUAL,
                actor=OWNER,
                payload={"qro": graph.qro(original.qro_id)},
                evidence_refs=("evidence:later-business-head",),
                tool_record_refs=("api:research_os.later_business_write",),
            )
        )

    projection = graph.projection_index(owner=OWNER)[0]
    graph._projection_index[original.qro_id] = replace(  # noqa: SLF001
        projection,
        command_id=graph.commands()[0].command_id,
    )

    assert not current_qro_spine_binding_is_observed(
        research_graph_store=graph,
        owner_user_id=OWNER,
        qro_ref=original.qro_id,
        chain_ref=CHAIN_REF,
        entrypoint_ref=entrypoint,
        graph_command_ref=result.graph_command_ref,
    )


def test_atomic_compare_append_rejects_interleaved_business_head_without_write() -> None:
    original = _qro()
    graph = _graph(original)
    revised = replace(
        original,
        output_contract={"status": "recorded", "revision": "v2"},
        mathematical_refs=(),
    )
    revised_command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": revised},
        evidence_refs=("evidence:business-v2",),
        tool_record_refs=("api:research_os.business_revision",),
    )

    def interleave(_plan) -> None:
        graph.apply(revised_command)

    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            validate_plan=interleave,
            compile_binding=lambda _qro, _command: _compile_result(),
        )

    assert captured.value.phase == "research_graph"
    assert captured.value.graph_binding_current is False
    assert captured.value.graph_command_created is False
    assert graph.qro(original.qro_id) == revised
    assert graph.qro(original.qro_id).mathematical_refs == ()
    assert graph.projection_index(owner=OWNER)[0].command_id == revised_command.command_id
    assert len(graph.commands()) == 2


def test_exact_business_command_retry_is_idempotent_before_compare_append() -> None:
    original = _qro()
    graph = _graph(original)
    historical = graph.commands()[0]

    result = record_current_qro_spine_binding(
        research_graph_store=graph,
        qro_ref=original.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
        entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
        validate_plan=lambda _plan: graph.apply(historical),
        compile_binding=lambda _qro, _command: _compile_result(),
    )

    assert result.graph_command_created is True
    assert len(graph.commands()) == 2
    assert len({item.command_id for item in graph.commands()}) == 2
    assert graph.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)


def test_persistent_compare_append_rejects_other_store_business_head(tmp_path) -> None:
    original = _qro()
    path = tmp_path / "research-graph-head-race.jsonl"
    seed = PersistentResearchGraphStore(path)
    seed.apply(
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": original},
        )
    )
    binder = PersistentResearchGraphStore(path)
    business_writer = PersistentResearchGraphStore(path)
    revised = replace(
        original,
        output_contract={"status": "recorded", "revision": "v2"},
        mathematical_refs=(),
    )
    revised_command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": revised},
        evidence_refs=("evidence:persistent-business-v2",),
        tool_record_refs=("api:research_os.business_revision",),
    )

    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=binder,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            validate_plan=lambda _plan: business_writer.apply(revised_command),
            compile_binding=lambda _qro, _command: _compile_result(),
        )

    assert captured.value.phase == "research_graph"
    replay = PersistentResearchGraphStore(path)
    assert replay.qro(original.qro_id) == revised
    assert replay.qro(original.qro_id).mathematical_refs == ()
    assert replay.projection_index(owner=OWNER)[0].command_id == revised_command.command_id
    assert len(replay.commands()) == 2


def test_persistent_exact_retry_is_deduplicated_before_binding(tmp_path) -> None:
    original = _qro()
    path = tmp_path / "research-graph-exact-retry.jsonl"
    seed = PersistentResearchGraphStore(path)
    historical = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": original},
    )
    seed.apply(historical)
    binder = PersistentResearchGraphStore(path)
    retrier = PersistentResearchGraphStore(path)

    result = record_current_qro_spine_binding(
        research_graph_store=binder,
        qro_ref=original.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
        entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
        validate_plan=lambda _plan: retrier.apply(historical),
        compile_binding=lambda _qro, _command: _compile_result(),
    )

    replay = PersistentResearchGraphStore(path)
    assert result.graph_command_created is True
    assert len(replay.commands()) == 2
    assert len({item.command_id for item in replay.commands()}) == 2
    assert replay.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)


def test_persistent_append_failure_never_publishes_an_in_memory_binding(tmp_path) -> None:
    original = _qro()
    path = tmp_path / "research-graph-append-failure.jsonl"
    seed = PersistentResearchGraphStore(path)
    seed.apply(
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": original},
        )
    )

    class _AppendFailureStore(PersistentResearchGraphStore):
        def _append_command_row_unlocked(self, _row) -> None:
            raise OSError("durable append unavailable")

    graph = _AppendFailureStore(path)
    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: _compile_result(),
        )

    assert captured.value.phase == "research_graph"
    assert captured.value.graph_binding_current is False
    assert captured.value.graph_command_created is False
    assert graph.qro(original.qro_id).mathematical_refs == ()
    assert len(graph.commands()) == 1
    replay = PersistentResearchGraphStore(path)
    assert replay.qro(original.qro_id).mathematical_refs == ()
    assert len(replay.commands()) == 1


@pytest.mark.parametrize("failure_point", ("post_append_ack", "memory_publish"))
def test_persistent_post_append_failure_reobserves_the_durable_binding(
    tmp_path,
    failure_point,
) -> None:
    original = _qro()
    path = tmp_path / f"research-graph-{failure_point}.jsonl"
    seed = PersistentResearchGraphStore(path)
    seed.apply(
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": original},
        )
    )

    class _PostAppendFailureStore(PersistentResearchGraphStore):
        def _append_command_row_unlocked(self, row) -> None:
            super()._append_command_row_unlocked(row)
            if failure_point == "post_append_ack":
                raise OSError("append acknowledgement lost")

        def _publish_projection_unlocked(self, fresh) -> None:
            if failure_point == "memory_publish":
                raise OSError("memory publish unavailable")
            super()._publish_projection_unlocked(fresh)

    graph = _PostAppendFailureStore(path)
    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: _compile_result(),
        )

    assert captured.value.phase == "research_graph"
    assert captured.value.graph_binding_current is True
    assert captured.value.graph_command_created is True
    assert graph.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)
    assert len(graph.commands()) == 2
    replay = PersistentResearchGraphStore(path)
    assert replay.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)
    assert len(replay.commands()) == 2


def test_binding_lock_refresh_failure_reports_current_state_as_unobserved(tmp_path) -> None:
    original = _qro()

    class _RefreshFailureGraph(ResearchGraphStore):
        path = tmp_path / "refresh-failure.jsonl"

        def refresh(self) -> None:
            raise OSError("refresh unavailable")

    graph = _RefreshFailureGraph()
    graph.apply(
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": original},
        )
    )

    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: _compile_result(),
        )

    assert captured.value.phase == "binding_lock"
    assert captured.value.graph_binding_current is None
    assert captured.value.graph_command_created is None
    assert "OSError:refresh unavailable" in str(captured.value)


def test_persistent_semantic_failure_is_not_mislabeled_as_a_lock_failure(
    tmp_path,
) -> None:
    graph = PersistentResearchGraphStore(tmp_path / "missing-qro.jsonl")

    with pytest.raises(QROSpineBindingError, match="current QRO is unavailable"):
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref="qro:missing",
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: _compile_result(),
        )


def test_compiler_failure_preserves_binding_head_and_retry_reuses_it() -> None:
    original = _qro()
    graph = _graph(original)

    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: (_ for _ in ()).throw(
                OSError("compiler unavailable")
            ),
        )

    error = captured.value
    assert error.phase == "compiler_coverage"
    assert error.graph_binding_current is True
    assert error.graph_command_created is True
    command_count = len(graph.commands())
    failed_command_ref = error.graph_command_ref
    assert command_count == 2
    assert graph.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)
    assert graph.projection_index(owner=OWNER)[0].command_id == failed_command_ref

    result = record_current_qro_spine_binding(
        research_graph_store=graph,
        qro_ref=original.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
        entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
        compile_binding=lambda _qro, _command: _compile_result(),
    )
    assert result.graph_command_created is False
    assert result.graph_command_ref == failed_command_ref
    assert len(graph.commands()) == command_count


def test_persistent_compiler_failure_preserves_current_head_and_retry_reuses_it(
    tmp_path,
) -> None:
    original = _qro()
    path = tmp_path / "binding-forward-only.jsonl"
    graph = PersistentResearchGraphStore(path)
    prior = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": original},
        evidence_refs=("evidence:original",),
        tool_record_refs=("api:test.original",),
    )
    graph.apply(prior)

    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: (_ for _ in ()).throw(
                OSError("compiler unavailable")
            ),
        )

    error = captured.value
    assert error.phase == "compiler_coverage"
    assert error.graph_binding_current is True
    assert error.graph_command_created is True
    failed_command_ref = error.graph_command_ref
    failed_replay = PersistentResearchGraphStore(path)
    failed_commands = failed_replay.commands()
    assert len(failed_commands) == 2
    assert failed_commands[0] == prior
    assert failed_commands[-1].command_id == failed_command_ref
    assert failed_replay.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)
    assert (
        failed_replay.projection_index(owner=OWNER)[0].command_id
        == failed_command_ref
    )

    repaired = record_current_qro_spine_binding(
        research_graph_store=failed_replay,
        qro_ref=original.qro_id,
        owner_user_id=OWNER,
        verified_chain=_chain(),
        entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
        compile_binding=lambda _qro, _command: _compile_result(),
    )
    assert repaired.graph_command_created is False
    assert repaired.graph_command_ref == failed_command_ref
    success_replay = PersistentResearchGraphStore(path)
    assert len(success_replay.commands()) == 2
    assert success_replay.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)


def test_prebound_business_head_cannot_masquerade_as_platform_binding() -> None:
    bound = _qro(mathematical_refs=(CHAIN_REF,))
    graph = _graph(bound)
    with pytest.raises(QROSpineBindingError, match="not the exact current"):
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=bound.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: _compile_result(),
        )


def test_wrong_graph_ack_reports_observed_current_state_without_compiling() -> None:
    original = _qro()

    class _WrongAckGraph(ResearchGraphStore):
        def apply(self, command):
            super().apply(command)
            return "rgcmd:wrong-ack"

    graph = _WrongAckGraph()
    ResearchGraphStore.apply(
        graph,
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": original},
        ),
    )
    compile_calls = 0

    def compile_binding(_qro, _command):
        nonlocal compile_calls
        compile_calls += 1
        return _compile_result()

    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=compile_binding,
        )
    assert captured.value.phase == "research_graph_ack"
    assert captured.value.graph_binding_current is True
    assert captured.value.graph_command_created is True
    assert compile_calls == 0


def test_graph_ack_loss_reports_persisted_current_head_without_compiling() -> None:
    original = _qro()

    class _AckLossGraph(ResearchGraphStore):
        def apply(self, command):
            super().apply(command)
            raise OSError("ack lost after append")

    graph = _AckLossGraph()
    ResearchGraphStore.apply(
        graph,
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": original},
        ),
    )
    compile_calls = 0

    def compile_binding(_qro, _command):
        nonlocal compile_calls
        compile_calls += 1
        return _compile_result()

    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=compile_binding,
        )
    assert captured.value.phase == "research_graph"
    assert captured.value.graph_binding_current is True
    assert captured.value.graph_command_created is True
    assert compile_calls == 0


def test_graph_failure_before_append_reports_no_observed_binding() -> None:
    original = _qro()

    class _FailedGraph(ResearchGraphStore):
        def apply(self, command):
            raise OSError("append unavailable")

    graph = _FailedGraph()
    ResearchGraphStore.apply(
        graph,
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": original},
        ),
    )

    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: _compile_result(),
        )
    assert captured.value.phase == "research_graph"
    assert captured.value.graph_binding_current is False
    assert captured.value.graph_command_created is False


def test_concurrent_persistent_binders_share_one_current_head(tmp_path) -> None:
    original = _qro()
    path = tmp_path / "research-graph.jsonl"
    seed = PersistentResearchGraphStore(path)
    seed.apply(
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": original},
        )
    )
    stores = (PersistentResearchGraphStore(path), PersistentResearchGraphStore(path))
    ready = threading.Barrier(2)

    def bind(store):
        ready.wait(timeout=5)
        return record_current_qro_spine_binding(
            research_graph_store=store,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: _compile_result(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(bind, stores))

    assert sorted(item.graph_command_created for item in results) == [False, True]
    assert len({item.graph_command_ref for item in results}) == 1
    replay = PersistentResearchGraphStore(path)
    assert len(replay.commands()) == 2
    assert replay.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)


@pytest.mark.parametrize(
    "compiled",
    (
        None,
        {},
        {
            "compiler_ir_ref": "compiler_ir:qro-binding",
            "compiler_pass_ref": "compiler_pass:qro-binding",
            "entrypoint_coverage_ref": "placeholder",
        },
    ),
)
def test_invalid_compiler_result_preserves_binding_graph_head(compiled) -> None:
    original = _qro()
    graph = _graph(original)
    with pytest.raises(QROSpineBindingCommitError) as captured:
        record_current_qro_spine_binding(
            research_graph_store=graph,
            qro_ref=original.qro_id,
            owner_user_id=OWNER,
            verified_chain=_chain(),
            entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
            compile_binding=lambda _qro, _command: compiled,
        )
    assert captured.value.phase == "compiler_coverage"
    assert captured.value.graph_binding_current is True
    assert captured.value.graph_command_created is True
    assert graph.qro(original.qro_id).mathematical_refs == (CHAIN_REF,)
    assert len(graph.commands()) == 2
    assert (
        graph.projection_index(owner=OWNER)[0].command_id
        == captured.value.graph_command_ref
    )
