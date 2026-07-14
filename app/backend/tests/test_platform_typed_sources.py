from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.research_os.platform_coverage import (
    PlatformCapabilityRecord,
    PlatformSpecificRef,
)
from app.research_os.platform_typed_sources import (
    PlatformTypedSourceAdapter,
    RealPlatformTypedSourceResolver,
    compose_platform_source_adapter_groups,
    platform_compiler_snapshot,
    scope_platform_source_adapters,
)


def _record(row: str, *specific: tuple[str, str]) -> PlatformCapabilityRecord:
    return PlatformCapabilityRecord(
        m_row=row,
        qro_ref=f"qro:{row}",
        research_graph_ref=f"rgcmd:{row}",
        lifecycle_ref=f"lifecycle:{row}",
        governance_ref=f"goal_validation_receipt:{row}",
        rag_ref=f"rag:{row}",
        math_spine_ref=f"math:{row}",
        evidence_refs=(f"evidence:{row}",),
        specific_refs=tuple(
            PlatformSpecificRef(key=key, ref=ref) for key, ref in specific
        ),
    )


def _adapter(kind: str) -> PlatformTypedSourceAdapter:
    return PlatformTypedSourceAdapter(
        source_kind=kind,
        load=lambda ref, owner, record: {
            "kind": kind,
            "ref": ref,
            "owner": owner,
            "row": str(getattr(record.m_row, "value", record.m_row)),
        },
        validate_linkage=lambda _value, _owner, _record: (),
    )


def _resolver(specific_adapters):
    return RealPlatformTypedSourceResolver(
        research_graph_store=object(),
        lifecycle_loaders=(),
        goal_validation_receipt_registry=object(),
        rag_index=object(),
        spine_chain_registry=object(),
        compiler_store=object(),
        specific_adapters=specific_adapters,
        row_validators={},
    )


def test_same_specific_field_can_have_distinct_row_scoped_typed_getters() -> None:
    resolver = _resolver(
        {
            ("M6", "model_passport_ref"): _adapter("training_passport"),
            ("M12", "model_passport_ref"): _adapter("registry_passport"),
        }
    )
    m6 = _record("M6", ("model_passport_ref", "model_passport:m6"))
    m12 = _record("M12", ("model_passport_ref", "model_passport:m12"))

    m6_state = resolver.resolve_state(
        "model_passport_ref",
        "model_passport:m6",
        owner_user_id="owner-a",
        record=m6,
    )
    m12_state = resolver.resolve_state(
        "model_passport_ref",
        "model_passport:m12",
        owner_user_id="owner-a",
        record=m12,
    )

    assert m6_state.source_kind == "training_passport"
    assert m12_state.source_kind == "registry_passport"
    assert resolver.registered_specific_keys == (
        "M12:model_passport_ref",
        "M6:model_passport_ref",
    )


def test_row_scoped_getter_wins_over_legacy_global_fallback() -> None:
    resolver = _resolver(
        {
            "llm_gateway_ref": _adapter("global_gateway"),
            ("M20", "llm_gateway_ref"): _adapter("security_gateway"),
        }
    )
    m14 = _record("M14", ("llm_gateway_ref", "llm_gateway:m14"))
    m20 = _record("M20", ("llm_gateway_ref", "llm_gateway:m20"))

    assert resolver.resolve_state(
        "llm_gateway_ref",
        "llm_gateway:m14",
        owner_user_id="owner-a",
        record=m14,
    ).source_kind == "global_gateway"
    assert resolver.resolve_state(
        "llm_gateway_ref",
        "llm_gateway:m20",
        owner_user_id="owner-a",
        record=m20,
    ).source_kind == "security_gateway"


def test_invalid_row_specific_adapter_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown row"):
        _resolver({("M99", "model_passport_ref"): _adapter("bad")})

    with pytest.raises(ValueError, match="not required"):
        _resolver({("M6", "llm_gateway_ref"): _adapter("bad")})


def test_adapter_group_composition_scopes_repeated_fields_by_row() -> None:
    m14_gateway = _adapter("agent_gateway")
    m20_gateway = _adapter("security_gateway")
    scoped, validators = compose_platform_source_adapter_groups(
        (
            {
                "llm_gateway_ref": m14_gateway,
                "model_routing_policy_ref": _adapter("routing"),
                "credential_pool_ref": _adapter("pool"),
                "theory_implementation_binding_ref": _adapter("binding"),
            },
            {"M14": lambda *_args: ()},
        ),
        (
            {
                "secret_ref": _adapter("secret"),
                "llm_gateway_ref": m20_gateway,
                "kill_switch_ref": _adapter("halt"),
            },
            {"M20": lambda *_args: ()},
        ),
    )

    assert scoped[("M14", "llm_gateway_ref")] is m14_gateway
    assert scoped[("M20", "llm_gateway_ref")] is m20_gateway
    assert set(validators) == {"M14", "M20"}


def test_adapter_group_composition_rejects_missing_field_and_duplicate_row() -> None:
    with pytest.raises(ValueError, match="omitted M20.kill_switch_ref"):
        scope_platform_source_adapters(
            {
                "secret_ref": _adapter("secret"),
                "llm_gateway_ref": _adapter("gateway"),
            },
            {"M20": lambda *_args: ()},
        )
    complete = {
        "secret_ref": _adapter("secret"),
        "llm_gateway_ref": _adapter("gateway"),
        "kill_switch_ref": _adapter("halt"),
    }
    with pytest.raises(ValueError, match="duplicate platform row validators"):
        compose_platform_source_adapter_groups(
            (complete, {"M20": lambda *_args: ()}),
            (complete, {"M20": lambda *_args: ()}),
        )


def _delegated_m12_resolver(*, delegated_marker: bool = True):
    owner = "model-owner"
    reviewer = "independent-reviewer"
    record = _record("M12")
    qro = SimpleNamespace(
        qro_id=record.qro_ref,
        owner=owner,
        approval="gate:m12",
        input_contract={
            "gate_id": "gate:m12",
            "delegated_actor": reviewer,
            "delegated_actor_authority_ref": "reviewer_grant:m12",
            "delegated_actor_authority_hash": "sha256:" + "a" * 64,
        },
        output_contract={
            "gate_id": "gate:m12",
            "approved_by": reviewer,
        },
    )
    command = SimpleNamespace(
        command_id=record.research_graph_ref,
        actor=reviewer,
        payload={"qro": qro},
    )

    class Graph:
        @staticmethod
        def qro(ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

        @staticmethod
        def commands():
            return [command]

    marker = (
        "runtime_validator:current_qro_graph_delegated_authority_v1"
        if delegated_marker
        else "runtime_validator:current_qro_graph_owner_linkage_v1"
    )

    class Validations:
        @staticmethod
        def receipt(ref, *, owner_user_id):
            if ref != record.governance_ref or owner_user_id != owner:
                raise KeyError(ref)
            return SimpleNamespace(validator_identifiers=(marker,))

        @staticmethod
        def validate_validation_ref(
            ref,
            *,
            owner_user_id,
            subject_qro_refs,
            graph_command_refs,
        ):
            accepted = (
                ref == record.governance_ref
                and owner_user_id == owner
                and subject_qro_refs == (record.qro_ref,)
                and graph_command_refs == (record.research_graph_ref,)
            )
            return SimpleNamespace(accepted=accepted)

    resolver = RealPlatformTypedSourceResolver(
        research_graph_store=Graph(),
        lifecycle_loaders=(),
        goal_validation_receipt_registry=Validations(),
        rag_index=object(),
        spine_chain_registry=object(),
        compiler_store=object(),
    )
    return resolver, record, owner


def test_m12_graph_command_accepts_exact_durable_delegated_reviewer_authority() -> None:
    resolver, record, owner = _delegated_m12_resolver()

    state = resolver.resolve_state(
        "research_graph_ref",
        record.research_graph_ref,
        owner_user_id=owner,
        record=record,
    )

    assert state.source_kind == "research_graph_command"
    assert state.source_ref == record.research_graph_ref


def test_m12_graph_command_rejects_delegated_fields_without_authority_receipt() -> None:
    resolver, record, owner = _delegated_m12_resolver(delegated_marker=False)

    with pytest.raises(LookupError, match="command/QRO linkage mismatch"):
        resolver.resolve_state(
            "research_graph_ref",
            record.research_graph_ref,
            owner_user_id=owner,
            record=record,
        )


def test_ledger_backed_compiler_snapshot_ignores_legacy_shadow_rows() -> None:
    canonical_ir = SimpleNamespace(ir_ref="compiler_ir:current", owner="owner-a")
    canonical_pass = SimpleNamespace(
        pass_ref="compiler_pass:current",
        actor="owner-a",
    )
    legacy_ir = SimpleNamespace(ir_ref="compiler_ir:legacy", owner="owner-a")
    legacy_pass = SimpleNamespace(
        pass_ref="compiler_pass:legacy",
        actor="owner-a",
    )

    class LedgerBackedCompiler:
        _proof_projection = object()

        @staticmethod
        def canonical_records(*, owner):
            assert owner == "owner-a"
            return SimpleNamespace(
                owner=owner,
                irs=(canonical_ir,),
                passes=(canonical_pass,),
            )

        @staticmethod
        def irs(*, owner):
            raise AssertionError(f"legacy IR read must not run for {owner}")

        @staticmethod
        def passes(*, owner):
            raise AssertionError(f"legacy pass read must not run for {owner}")

    snapshot = platform_compiler_snapshot(
        LedgerBackedCompiler(),
        owner="owner-a",
    )

    assert snapshot.canonical is True
    assert snapshot.irs == (canonical_ir,)
    assert snapshot.passes == (canonical_pass,)
    assert legacy_ir not in snapshot.irs
    assert legacy_pass not in snapshot.passes


def test_ledger_backed_compiler_without_canonical_snapshot_fails_closed() -> None:
    class BrokenLedgerBackedCompiler:
        _proof_projection = None
        _goal_proof_ledger = object()

        @staticmethod
        def irs(*, owner):
            return ()

        @staticmethod
        def passes(*, owner):
            return ()

    with pytest.raises(
        TypeError,
        match="ledger-backed compiler store lacks canonical_records",
    ):
        platform_compiler_snapshot(
            BrokenLedgerBackedCompiler(),
            owner="owner-a",
        )
