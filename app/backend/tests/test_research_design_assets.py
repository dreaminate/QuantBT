from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.research_os.research_design_assets import (
    PersistentResearchDesignAssetRegistry,
    ResearchDesignLinkage,
    make_label_definition_record,
    make_portfolio_policy_record,
    make_regime_scenario_record,
    make_strategy_book_record,
    make_universe_definition_record,
    portfolio_policy_ref,
)


OWNER = "researcher-a"


def _linkage(suffix: str) -> ResearchDesignLinkage:
    return ResearchDesignLinkage(
        qro_ref=f"qro:{suffix}",
        research_graph_ref=f"rgcmd:{suffix}",
        lifecycle_ref=f"lifecycle:{suffix}",
    )


def _strategy_book() -> dict:
    return {
        "strategy_book_ref": "strategy_book:relative-value-v1",
        "factor_refs": ["factor:spread:v1"],
        "signal_refs": ["sig::spread"],
        "legs": [
            {
                "intent_ref": "intent:long-btc",
                "side": "long",
                "instrument_ref": "instrument:BTCUSDT",
            },
            {
                "intent_ref": "intent:short-eth",
                "side": "short",
                "instrument_ref": "instrument:ETHUSDT",
            },
        ],
        "default_factor_refs": [],
        "mathematical_refs": ["math:spread"],
        "theory_binding_refs": ["theory:relative-value"],
        "run_config_binding_refs": ["runconfig:relative-value-v1"],
        "signal_validation_refs": ["signal_validation:spread:oos"],
        "market_data_use_validation_refs": ["market_data_use:spread"],
        "portfolio_of_strategies_refs": [],
        "correlation_budget_ref": "budget:correlation:v1",
        "capacity_budget_ref": "budget:capacity:v1",
        "drawdown_budget_ref": "budget:drawdown:v1",
        "capital_allocation_ref": "allocation:relative-value:v1",
    }


def test_registry_round_trip_owner_scope_and_canonical_policy(tmp_path):
    path = tmp_path / "research_design.jsonl"
    registry = PersistentResearchDesignAssetRegistry(path)
    universe = make_universe_definition_record(
        {
            "id": "crypto-pairs",
            "name": "Crypto pairs",
            "market": "binanceusdm",
            "rules": {
                "market": "binanceusdm",
                "static_symbols": ["BTCUSDT", "ETHUSDT"],
            },
        },
        owner_user_id=OWNER,
        linkage=_linkage("universe"),
    )
    regime = make_regime_scenario_record(
        owner_user_id=OWNER,
        universe_definition_ref=universe.universe_definition_ref,
        scenario={
            "name": "high-volatility",
            "detector": "realized_volatility",
            "config": {"window": 20, "threshold": 0.8},
        },
        linkage=_linkage("regime"),
    )
    strategy = make_strategy_book_record(
        _strategy_book(),
        owner_user_id=OWNER,
        linkage=_linkage("strategy"),
    )
    policy_payload = {
        "portfolio_id": "relative-value",
        "strategy_book_ref": strategy.strategy_book_ref,
        "signal_contract_ref": "signal_contract:sig::spread",
        "signal_validation_ref": "signal_validation:spread:oos",
        "strategy_book_source_hash": strategy.source_content_hash,
        "signal_contract_source_hash": "signal-source-hash",
        "policy": {"gross_limit": 1.0, "net_limit": 0.1},
    }
    policy = make_portfolio_policy_record(
        owner_user_id=OWNER,
        linkage=_linkage("policy"),
        **policy_payload,
    )

    for record in (universe, regime, strategy, policy):
        registry.record(record)
    registry.record(
        make_strategy_book_record(
            _strategy_book(),
            owner_user_id="researcher-b",
            linkage=_linkage("strategy-owner-b"),
        )
    )

    reopened = PersistentResearchDesignAssetRegistry(path)
    assert reopened.universe_definition(
        universe.universe_definition_ref, owner_user_id=OWNER
    ) == universe
    assert reopened.regime_scenario(regime.regime_scenario_ref, owner_user_id=OWNER) == regime
    assert reopened.strategy_book(strategy.strategy_book_ref, owner_user_id=OWNER) == strategy
    assert reopened.portfolio_policy(policy.portfolio_policy_ref, owner_user_id=OWNER) == policy
    assert policy.portfolio_policy_ref == portfolio_policy_ref(**policy_payload)
    assert reopened.strategy_book(
        strategy.strategy_book_ref, owner_user_id="researcher-b"
    ).owner_user_id == "researcher-b"
    with pytest.raises(KeyError):
        reopened.strategy_book(strategy.strategy_book_ref, owner_user_id="researcher-c")


def test_registry_rejects_identity_collision_tamper_and_uncommitted_suffix(tmp_path):
    collision_path = tmp_path / "collision.jsonl"
    registry = PersistentResearchDesignAssetRegistry(collision_path)
    label = make_label_definition_record(
        owner_user_id=OWNER,
        label_kind="time_series",
        output_column="forward_return_5d",
        horizon=5,
        parameters={"price_column": "close"},
        known_at_rule="label known after horizon closes",
        effective_at_rule="effective at forecast origin",
        linkage=_linkage("label"),
    )
    registry.record(label)
    with pytest.raises(ValueError, match="canonical identity collision"):
        registry.record(replace(label, linkage=_linkage("different-linkage")))

    tampered_path = tmp_path / "tampered.jsonl"
    tampered = PersistentResearchDesignAssetRegistry(tampered_path)
    tampered.record(label)
    row = json.loads(tampered_path.read_text(encoding="utf-8"))
    row["record"]["output_column"] = "silently_changed"
    tampered_path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid research-design row"):
        PersistentResearchDesignAssetRegistry(tampered_path)

    suffix_path = tmp_path / "suffix.jsonl"
    suffix = PersistentResearchDesignAssetRegistry(suffix_path)
    suffix.record(label)
    first = json.loads(suffix_path.read_text(encoding="utf-8"))
    second = dict(first)
    second["sequence"] = 2
    second["previous_sha256"] = first["row_sha256"]
    second["row_sha256"] = suffix._row_hash(second)
    with suffix_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(second, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="uncommitted suffix"):
        PersistentResearchDesignAssetRegistry(suffix_path)


def test_registry_serializes_concurrent_writers_and_rejects_empty_strategy_book(tmp_path):
    path = tmp_path / "concurrent.jsonl"

    def write_label(index: int) -> str:
        registry = PersistentResearchDesignAssetRegistry(path)
        record = make_label_definition_record(
            owner_user_id=OWNER,
            label_kind="cross_sectional",
            output_column=f"forward_rank_{index}",
            horizon=index + 1,
            parameters={"rank_group": index + 2},
            known_at_rule="known after the horizon",
            effective_at_rule="effective at forecast origin",
            linkage=_linkage(f"label-{index}"),
        )
        return registry.record(record).label_ref

    with ThreadPoolExecutor(max_workers=4) as pool:
        refs = tuple(pool.map(write_label, range(8)))

    reopened = PersistentResearchDesignAssetRegistry(path)
    assert len(set(refs)) == 8
    for ref in refs:
        assert reopened.label_definition(ref, owner_user_id=OWNER).label_ref == ref

    incomplete = _strategy_book()
    incomplete["legs"] = []
    with pytest.raises(ValueError, match="at least one typed leg"):
        make_strategy_book_record(
            incomplete,
            owner_user_id=OWNER,
            linkage=_linkage("incomplete-strategy"),
        )
