from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.factor_factory.registry import Factor
from app.research_os.market_data_contract import DatasetSemanticsRecord
from app.research_os.research_design_assets import (
    ResearchDesignLinkage,
    make_factor_envelope,
)
from app.research_os.spine import QRORecord
from app.research_os.spine_external_refs import (
    OwnerScopedRefSource,
    StrictSpineExternalRefResolver,
)


@dataclass(frozen=True)
class _Record:
    ref: str
    owner_user_id: str
    revision: int = 1


class _CurrentStore:
    def __init__(self, records: dict[tuple[str, str], _Record]) -> None:
        self.records = dict(records)
        self.reads = 0
        self.writes = 0

    def current(self, ref: str, owner: str) -> _Record:
        self.reads += 1
        return self.records[(owner, ref)]

    def record(self, _value: object) -> None:  # pragma: no cover - must never run.
        self.writes += 1
        raise AssertionError("external-ref resolution cannot materialize records")


def _source(
    store: _CurrentStore,
    *,
    ref_type: str = "test_asset",
    current: bool = True,
) -> OwnerScopedRefSource:
    return OwnerScopedRefSource(
        ref_type=ref_type,
        roles=frozenset({"evidence_refs"}),
        accepts_ref=lambda ref: ref.startswith("asset:"),
        load_current=store.current,
        canonical_refs=lambda value: (value.ref,),
        owner_user_id=lambda value: value.owner_user_id,
        is_current=lambda _value, _ref, _owner: current,
    )


def _resolver(tmp_path: Path, *sources: OwnerScopedRefSource) -> StrictSpineExternalRefResolver:
    return StrictSpineExternalRefResolver(
        project_root=tmp_path,
        verifier_refs=("canonical_verifier:v1",),
        extra_sources=sources,
    )


def test_exact_active_support_map_and_read_only_double_read(tmp_path: Path) -> None:
    record = _Record("asset:alpha", "alice")
    store = _CurrentStore({("alice", record.ref): record})
    resolver = _resolver(tmp_path, _source(store))

    assert resolver.supported_ref_types_by_role["evidence_refs"] == (
        "test_asset",
        "repository_path",
    )
    assert resolver.supported_ref_types_by_role["factor_ref"] == ()
    assert resolver.supported_ref_types_by_role["verifier_ref"] == (
        "registered_verifier",
    )
    assert resolver("evidence_refs", record.ref, "alice") is True
    assert store.reads == 2
    assert store.writes == 0


def test_zero_match_and_missing_record_fail_closed(tmp_path: Path) -> None:
    store = _CurrentStore({})
    resolver = _resolver(tmp_path, _source(store))

    assert resolver("evidence_refs", "unknown:alpha", "alice") is False
    assert resolver("evidence_refs", "asset:missing", "alice") is False
    assert store.reads == 1


def test_ambiguous_sources_fail_before_read(tmp_path: Path) -> None:
    record = _Record("asset:alpha", "alice")
    first = _CurrentStore({("alice", record.ref): record})
    second = _CurrentStore({("alice", record.ref): record})
    resolver = _resolver(
        tmp_path,
        _source(first, ref_type="first_asset"),
        _source(second, ref_type="second_asset"),
    )

    assert resolver("evidence_refs", record.ref, "alice") is False
    assert first.reads == second.reads == 0


def test_foreign_owner_and_non_current_record_fail_closed(tmp_path: Path) -> None:
    ref = "asset:alpha"
    foreign_store = _CurrentStore({("alice", ref): _Record(ref, "bob")})
    stale_store = _CurrentStore({("alice", ref): _Record(ref, "alice")})

    assert _resolver(tmp_path, _source(foreign_store))(
        "evidence_refs", ref, "alice"
    ) is False
    assert _resolver(tmp_path, _source(stale_store, current=False))(
        "evidence_refs", ref, "alice"
    ) is False


def test_head_change_between_the_two_reads_fails_closed(tmp_path: Path) -> None:
    ref = "asset:alpha"
    values = iter((_Record(ref, "alice", 1), _Record(ref, "alice", 2)))
    source = OwnerScopedRefSource(
        ref_type="racing_asset",
        roles=frozenset({"evidence_refs"}),
        accepts_ref=lambda value: value == ref,
        load_current=lambda _ref, _owner: next(values),
        canonical_refs=lambda value: (value.ref,),
        owner_user_id=lambda value: value.owner_user_id,
        is_current=lambda _value, _ref, _owner: True,
    )

    assert _resolver(tmp_path, source)("evidence_refs", ref, "alice") is False


@pytest.mark.parametrize(
    "ref",
    (
        "asset:placeholder:v1",
        "asset:synthetic:v1",
        "asset:fixture:v1",
        "asset:test-only:v1",
        "asset:goal_closure:v1",
        "asset:fake:v1",
        "asset:dummy:v1",
    ),
)
def test_placeholder_components_are_rejected_before_store_access(
    tmp_path: Path,
    ref: str,
) -> None:
    store = _CurrentStore({("alice", ref): _Record(ref, "alice")})
    resolver = _resolver(tmp_path, _source(store))

    assert resolver("evidence_refs", ref, "alice") is False
    assert store.reads == 0


def test_role_ref_and_owner_text_must_be_exact(tmp_path: Path) -> None:
    record = _Record("asset:alpha", "alice")
    store = _CurrentStore({("alice", record.ref): record})
    resolver = _resolver(tmp_path, _source(store))

    assert resolver("unknown_role", record.ref, "alice") is False
    assert resolver("evidence_refs ", record.ref, "alice") is False
    assert resolver("evidence_refs", f" {record.ref}", "alice") is False
    assert resolver("evidence_refs", record.ref, " alice") is False
    assert store.reads == 0


def test_registered_verifier_is_exact_and_not_prefix_based(tmp_path: Path) -> None:
    resolver = _resolver(tmp_path)

    assert resolver("verifier_ref", "canonical_verifier:v1", "alice") is True
    assert resolver("verifier_ref", "canonical_verifier:v1:forged", "alice") is False
    assert resolver("evidence_refs", "canonical_verifier:v1", "alice") is False


def test_repository_paths_require_canonical_repo_contained_real_files(
    tmp_path: Path,
) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_alpha.py"
    test_file.write_text("def test_alpha():\n    assert True\n", encoding="utf-8")
    code_dir = tmp_path / "app"
    code_dir.mkdir()
    code_file = code_dir / "alpha.py"
    code_file.write_text("VALUE = 1\n", encoding="utf-8")
    resolver = _resolver(tmp_path)

    assert resolver("test_refs", "tests/test_alpha.py", "alice") is True
    assert resolver("test_refs", "tests/test_alpha.py::test_alpha", "alice") is True
    assert resolver("consistency_input_refs", "app/alpha.py:VALUE", "alice") is True
    assert resolver("consistency_input_refs", "app/alpha.py:1", "alice") is True

    assert resolver("test_refs", str(test_file), "alice") is False
    assert resolver("test_refs", "./tests/test_alpha.py", "alice") is False
    assert resolver("test_refs", "tests/../tests/test_alpha.py", "alice") is False
    assert resolver("test_refs", "tests/missing.py", "alice") is False
    assert resolver("test_refs", "tests/test_alpha.py::not valid", "alice") is False
    assert resolver("test_refs", "tests/test_alpha.py:any:suffix", "alice") is False


def test_repository_path_rejects_symlinks_even_when_target_is_inside_root(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real.py"
    real.write_text("VALUE = 1\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    link.symlink_to(real)

    assert _resolver(tmp_path)("test_refs", "linked.py", "alice") is False


class _DatasetRegistry:
    def __init__(self, record: DatasetSemanticsRecord, owner: str) -> None:
        self.record = record
        self.owner = owner
        self.calls: list[tuple[str, str]] = []

    def dataset(self, ref: str, *, owner_user_id: str) -> DatasetSemanticsRecord:
        self.calls.append((ref, owner_user_id))
        if owner_user_id != self.owner or ref != self.record.dataset_ref:
            raise KeyError(ref)
        return self.record


def test_real_dataset_type_uses_owner_aware_getter(tmp_path: Path) -> None:
    record = DatasetSemanticsRecord(
        dataset_ref="dataset:bars:v1",
        source_ref="source:bars",
        version="v1",
        known_at_ref="known_at:bars",
        effective_at_ref="effective_at:bars",
        pit_bitemporal_rules_ref="pit:bars",
        quality_status="pass",
        lineage_refs=("lineage:bars",),
        freshness_status="current",
        checksum="sha256:" + "a" * 64,
    )
    registry = _DatasetRegistry(record, "alice")
    resolver = StrictSpineExternalRefResolver(
        project_root=tmp_path,
        market_data_registry=registry,
    )

    assert resolver("data_semantics_ref", record.dataset_ref, "alice") is True
    assert resolver("data_semantics_ref", record.dataset_ref, "bob") is False
    assert registry.calls == [
        (record.dataset_ref, "alice"),
        (record.dataset_ref, "alice"),
        (record.dataset_ref, "bob"),
    ]


class _Graph:
    def __init__(self, qro: QRORecord) -> None:
        self.qro_record = qro
        self.tombstoned = False

    def qro(self, qro_id: str) -> QRORecord:
        if self.tombstoned or qro_id != self.qro_record.qro_id:
            raise KeyError(qro_id)
        return self.qro_record


def _qro(owner: str = "alice") -> QRORecord:
    return QRORecord(
        qro_type="Factor",
        owner=owner,
        actor="user_manual",
        input_contract={"input": "factor"},
        output_contract={"output": "factor"},
        market="equity",
        universe="hs300",
        horizon="1d",
        frequency="1d",
        lineage=("factor",),
        implementation_hash="implementation:factor:v1",
        assumptions=("prices are adjusted",),
        known_limits=("capacity is unverified",),
        failure_modes=("data can be stale",),
        validation_plan=("run walk-forward validation",),
    )


def test_qro_resolution_requires_canonical_identity_owner_and_current_head(
    tmp_path: Path,
) -> None:
    qro = _qro()
    graph = _Graph(qro)
    resolver = StrictSpineExternalRefResolver(
        project_root=tmp_path,
        research_graph_store=graph,
    )

    assert resolver("factor_ref", qro.qro_id, "alice") is True
    assert resolver("factor_ref", f"qro:{qro.qro_id}", "alice") is True
    assert resolver("factor_ref", qro.qro_id, "bob") is False
    graph.tombstoned = True
    assert resolver("factor_ref", qro.qro_id, "alice") is False


class _FactorDesignRegistry:
    def __init__(self, envelope: object) -> None:
        self.envelope = envelope

    def factor_envelope(self, ref: str, *, owner_user_id: str) -> object:
        if owner_user_id != "alice" or ref != self.envelope.factor_ref:
            raise KeyError(ref)
        return self.envelope

    # Construction registers these read-only source types; tests do not resolve them.
    def strategy_book(self, *_args, **_kwargs):
        raise KeyError

    def portfolio_policy(self, *_args, **_kwargs):
        raise KeyError

    def universe_definition(self, *_args, **_kwargs):
        raise KeyError

    def regime_scenario(self, *_args, **_kwargs):
        raise KeyError

    def label_definition(self, *_args, **_kwargs):
        raise KeyError


class _Factors:
    def __init__(self, factor: Factor) -> None:
        self.factor = factor

    def get(self, factor_id: str, version: int) -> Factor:
        if (factor_id, version) != (self.factor.factor_id, self.factor.version):
            raise KeyError(factor_id)
        return self.factor


def test_legacy_factor_requires_current_owner_envelope_and_source_hash(
    tmp_path: Path,
) -> None:
    factor = Factor(factor_id="alpha", formula="close / open", version=1, author="alice")
    envelope = make_factor_envelope(
        factor,
        owner_user_id="alice",
        label_ref="label:0123456789abcdef",
        linkage=ResearchDesignLinkage(
            qro_ref="qro:factor",
            research_graph_ref="graph:factor",
            lifecycle_ref="lifecycle:factor",
        ),
    )
    resolver = StrictSpineExternalRefResolver(
        project_root=tmp_path,
        research_design_registry=_FactorDesignRegistry(envelope),
        factor_registry=_Factors(factor),
    )

    assert resolver("factor_ref", envelope.factor_ref, "alice") is True
    assert resolver("factor_ref", envelope.factor_ref, "bob") is False
    factor.formula = "close / high"
    assert resolver("factor_ref", envelope.factor_ref, "alice") is False


def test_stage_support_map_is_exact_for_configured_domain_dependencies(
    tmp_path: Path,
) -> None:
    inert = object()
    resolver = StrictSpineExternalRefResolver(
        project_root=tmp_path,
        market_data_registry=inert,
        research_design_registry=inert,
        factor_registry=inert,
        model_registry=inert,
        signal_contract_registry=inert,
        hypothesis_store=inert,
    )

    actual = resolver.supported_ref_types_by_role
    assert {role: actual[role] for role in (
        "data_semantics_ref",
        "factor_ref",
        "model_ref",
        "forecast_ref",
        "signal_contract_ref",
        "strategy_book_ref",
        "portfolio_policy_ref",
        "risk_policy_ref",
        "execution_policy_ref",
        "backtest_run_ref",
        "attribution_ref",
        "monitor_ref",
    )} == {
        "data_semantics_ref": ("dataset_semantics",),
        "factor_ref": ("factor",),
        "model_ref": ("model_version",),
        "forecast_ref": (),
        "signal_contract_ref": ("signal_contract",),
        "strategy_book_ref": ("strategy_book",),
        "portfolio_policy_ref": ("portfolio_policy",),
        "risk_policy_ref": (),
        "execution_policy_ref": (),
        "backtest_run_ref": (),
        "attribution_ref": (),
        "monitor_ref": (),
    }


def test_duplicate_ref_type_names_are_rejected_at_construction(tmp_path: Path) -> None:
    store = _CurrentStore({})
    source = _source(store)
    with pytest.raises(ValueError, match="ref_type names must be unique"):
        _resolver(tmp_path, source, source)
