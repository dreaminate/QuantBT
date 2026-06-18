from __future__ import annotations

from pathlib import Path

import pytest

from app.experiments import ExperimentStore, ModelRegistry, RunStore


def test_experiment_create_and_list(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    e = store.create_experiment(name="hs300_lgbm_v1", asset_class="equity_cn", description="demo")
    assert e.experiment_id.startswith("exp-")
    listed = store.list_experiments()
    assert any(x.name == "hs300_lgbm_v1" for x in listed)


def test_run_lifecycle(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    runs = RunStore(tmp_path)
    exp = store.create_experiment(name="x", asset_class="crypto_perp")
    run = runs.create_run(experiment_id=exp.experiment_id, inputs={"factor_set": "v1"})
    assert run.status == "running"
    runs.update_run(run.run_id, metrics={"sharpe": 1.5, "pbo": 0.1}, artifact_paths=["a.csv"])
    runs.update_run(run.run_id, status="succeeded", finished=True)
    final = runs.get_run(run.run_id)
    assert final.status == "succeeded"
    assert final.metrics["sharpe"] == 1.5
    assert final.finished_at_utc is not None


def test_run_lineage_parent_chain(tmp_path: Path) -> None:
    runs = RunStore(tmp_path)
    a = runs.create_run("exp-1")
    b = runs.create_run("exp-1", parent_run_id=a.run_id)
    c = runs.create_run("exp-1", parent_run_id=b.run_id)
    chain = runs.lineage(c.run_id)
    assert [r.run_id for r in chain] == [c.run_id, b.run_id, a.run_id]


def test_run_lineage_forked_from(tmp_path: Path) -> None:
    runs = RunStore(tmp_path)
    a = runs.create_run("exp-1")
    forked = runs.create_run("exp-1", forked_from=a.run_id)
    chain = runs.lineage(forked.run_id)
    assert [r.run_id for r in chain] == [forked.run_id, a.run_id]


def test_model_registry_versioning_and_promotion(tmp_path: Path) -> None:
    reg = ModelRegistry(tmp_path)
    v1 = reg.register_version("lgbm_xs", artifact_path="a.pkl", metrics={"sharpe": 1.1})
    v2 = reg.register_version("lgbm_xs", artifact_path="b.pkl", metrics={"sharpe": 1.4})
    assert v1.version == 1
    assert v2.version == 2
    assert v1.stage == "dev"
    # T-019：staging/production 需经审批门；dev/archived 仍直翻（向后兼容）。这里测直翻路径。
    promoted = reg.promote("lgbm_xs", 2, "archived")
    assert promoted.stage == "archived"
    # 重新拉取
    versions = reg.list_versions("lgbm_xs")
    assert any(v.version == 2 and v.stage == "archived" for v in versions)
    assert "lgbm_xs" in reg.list_models()
    # 无 gate_service 时晋升 production 必 raise（禁裸翻）。
    import pytest as _pytest
    from app.approval.schema import GateStateError
    with _pytest.raises(GateStateError):
        reg.promote("lgbm_xs", 2, "production")
