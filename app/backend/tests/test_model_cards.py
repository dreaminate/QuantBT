"""模型卡体系 + 扩充模型(新 ML + 通用 DL 架构)测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.models.catalog import (
    MODEL_CATALOG,
    get_model_card,
    list_model_cards,
    runnable_models,
    validate_cards_dir,
)
from app.models.training import ModelSpec, train_model
from app.training import TrainingRequest, TrainingService, spec_to_code


def _panel(n: int = 360, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    f1, f2 = rng.normal(size=n), rng.normal(size=n)
    y = 0.6 * f1 - 0.4 * f2 + rng.normal(size=n, scale=0.3)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "ts": [base + timedelta(days=i) for i in range(n)],
            "symbol": ["S"] * n,
            "f1": f1,
            "f2": f2,
            "label": y,
        }
    )


# ───────────── 卡片体系 ─────────────


def test_all_cards_load_and_validate() -> None:
    v = validate_cards_dir()
    assert v["ok"], v["errors"]
    assert v["count"] >= 19


def test_card_has_l1_l4_body() -> None:
    card = get_model_card("xgboost")
    assert "## L1" in card.body and "## L3" in card.body  # 调参段在 L3
    assert card.pros and card.cons and card.tuning_tip


def test_runnable_vs_documented() -> None:
    # 全部 DL 架构（含 tft/nbeats/nhits/deepar）均已实现纯 torch 模板 → runnable
    assert get_model_card("lstm").runnable is True
    assert get_model_card("tft").runnable is True
    rm = set(runnable_models())
    assert {
        "lgbm", "xgboost", "catboost", "lstm", "gru", "tcn", "transformer",
        "tft", "nbeats", "nhits", "deepar",
    } <= rm


def test_ml_dl_families_complete() -> None:
    ml = {c.key for c in list_model_cards(family="ml")}
    dl = {c.key for c in list_model_cards(family="dl")}
    assert {"lgbm", "xgboost", "catboost", "sklearn_rf", "extra_trees", "ridge", "lasso", "elastic_net", "sklearn_logreg"} <= ml
    assert {"lstm", "gru", "alstm", "mlp", "tcn", "transformer", "tft", "nbeats", "nhits", "deepar"} <= dl


# ───────────── 新 ML 模型训练 ─────────────


def test_train_catboost_regression(tmp_path: Path) -> None:
    pytest.importorskip("catboost")
    spec = ModelSpec(task="regression", model="catboost", feature_cols=["f1", "f2"], label_col="label", n_splits=4, hyperparams={"iterations": 60, "depth": 4})
    r = train_model(spec, _panel(), artifact_dir=tmp_path)
    assert r.oos_metrics["r2"] > 0


def test_train_ridge_and_extra_trees(tmp_path: Path) -> None:
    for model in ("ridge", "lasso", "elastic_net", "extra_trees"):
        spec = ModelSpec(task="regression", model=model, feature_cols=["f1", "f2"], label_col="label", n_splits=4)
        r = train_model(spec, _panel(), artifact_dir=tmp_path / model)
        assert "r2" in r.oos_metrics


# ───────────── 通用 DL 架构（子进程，真 torch）─────────────


def test_service_dl_gru_via_generic_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("torch")
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    job = svc.train_now(
        TrainingRequest(
            name="gru", model="gru", task="regression", feature_cols=["f1", "f2"], label_col="label",
            hyperparams={"max_epochs": 2, "lookback": 8, "hidden_size": 8, "batch_size": 32},
        ),
        _panel(400),
        owner_user_id="test-owner",
    )
    assert job.status == "succeeded", job.error
    import json
    res = json.loads((Path(job.artifact_dir) / "result.json").read_text())
    assert len(res["curves"]["train_loss"]) == 2
    assert res["device"] == "cpu"


# ───────────── Agent 约束 + 新增卡流程 ─────────────


def test_write_and_load_new_card_tmp(tmp_path: Path) -> None:
    from app.models.card_loader import load_model_cards_dir, write_model_card

    write_model_card(
        {"key": "tmp_xnet", "family": "dl", "display_name": "X-Net", "tasks": ["regression"], "description": "搜来的新模型"},
        directory=tmp_path,
    )
    cards = load_model_cards_dir(tmp_path)
    assert "tmp_xnet" in cards
    c = cards["tmp_xnet"]
    assert c.runnable is False  # agent 新增默认仅收录
    assert c.is_available() is False
    assert "## L1" in c.body


def test_add_model_card_validates() -> None:
    from app.models.card_loader import ModelCardError
    from app.models.catalog import add_model_card

    with pytest.raises(ModelCardError):  # family 非法 → 不写文件
        add_model_card({"key": "bad_fam", "family": "xx", "display_name": "B", "tasks": ["regression"], "description": "d"})
    with pytest.raises(ModelCardError):  # 缺字段
        add_model_card({"key": "incomplete"})


def test_agent_context_constrains_to_cards() -> None:
    from app.training.agent_context import model_choices_block, training_system_prompt

    prompt = training_system_prompt()
    assert "只能" in prompt
    assert "lgbm" in prompt and "lstm" in prompt
    assert "add_model_card" in prompt  # 指示新模型走加卡流程
    block = model_choices_block()
    assert "ML" in block and "DL" in block
    assert "可训练" in block  # 模型清单标注可训练状态


def test_codegen_all_dl_archs_runnable() -> None:
    # 全部 DL 架构（含 tft/nbeats/nhits/deepar）都能生成 train_dl 代码
    for arch in ("tcn", "tft", "nbeats", "nhits", "deepar"):
        code = spec_to_code({"model": arch, "task": "regression", "feature_cols": ["f1"], "label_col": "label", "hyperparams": {}})
        assert "train_dl" in code and f"arch='{arch}'" in code


@pytest.mark.parametrize("arch", ["tft", "nbeats", "nhits", "deepar"])
def test_service_advanced_dl_trains(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arch: str) -> None:
    pytest.importorskip("torch")
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    job = svc.train_now(
        TrainingRequest(
            name=arch, model=arch, task="regression", feature_cols=["f1", "f2"], label_col="label",
            hyperparams={"max_epochs": 2, "lookback": 8, "hidden_size": 8, "batch_size": 32},
        ),
        _panel(400),
        owner_user_id="test-owner",
    )
    assert job.status == "succeeded", job.error
    import json
    res = json.loads((Path(job.artifact_dir) / "result.json").read_text())
    assert len(res["curves"]["train_loss"]) == 2  # 学习曲线
    assert (Path(job.artifact_dir) / "model.pt").exists()  # checkpoint


# ───────── code-review 回归：一致性 & stale-ref ─────────

def test_runnable_threeway_consistency() -> None:
    """三处 runnable 来源必须一致：卡片 runnable:true(dl) == _RUNNABLE_DL == _ARCH.keys()。"""
    import importlib.util

    from app.training.codegen import _RUNNABLE_DL

    dl_runnable_cards = {c.key for c in list_model_cards(family="dl") if c.runnable}
    assert dl_runnable_cards == _RUNNABLE_DL, (
        f"卡片 runnable DL 与 codegen._RUNNABLE_DL 不一致: "
        f"卡片只有={dl_runnable_cards - _RUNNABLE_DL} codegen只有={_RUNNABLE_DL - dl_runnable_cards}"
    )
    if importlib.util.find_spec("torch") is not None:
        from app.models.dl.architectures import available_architectures
        assert set(available_architectures()) == _RUNNABLE_DL


def test_reload_catalog_in_place_no_stale_ref() -> None:
    """reload_catalog 原地更新：再导出名 app.models.MODEL_CATALOG 不会变成 stale。"""
    from app.models import MODEL_CATALOG as REEXPORTED
    from app.models.catalog import MODEL_CATALOG as CANONICAL, reload_catalog

    # 两个名应指向同一 dict 对象
    assert REEXPORTED is CANONICAL
    reload_catalog()
    # reload 后仍是同一对象（原地 clear+update，而非 rebind）
    from app.models import MODEL_CATALOG as REEXPORTED2
    assert REEXPORTED2 is CANONICAL
    assert len(REEXPORTED2) >= 19
