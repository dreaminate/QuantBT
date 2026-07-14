"""DL trainer 正确性回归测试 —— 专门用 demo 数据掩盖不了的 panel:
非 'symbol' 命名的标的列 + 带符号/非连续分类标签 + 多标的。
对应 code-review 发现 #1(跨标的 val 切分)/#2(n_out 标签映射)/#3(symbol_col)/#4(transformer 头守卫)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from app.models.dl.trainer import _build_sequences, _temporal_val_mask, train_dl


_OWNER_USER_ID = "test-owner"


def _multi_symbol_panel(n_syms: int = 4, n_days: int = 60, seed: int = 0, sym_col: str = "ts_code") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for s in range(n_syms):
        f1 = rng.normal(size=n_days)
        f2 = rng.normal(size=n_days)
        y = 0.6 * f1 - 0.4 * f2 + rng.normal(size=n_days, scale=0.3)
        for d in range(n_days):
            rows.append({
                "ts": base + timedelta(days=d),
                sym_col: f"SYM{s:03d}",
                "f1": float(f1[d]),
                "f2": float(f2[d]),
                "label": float(y[d]),
                "label_sign": int(1 if y[d] > 0 else -1),  # 带符号标签 {-1, 1}
            })
    return pd.DataFrame(rows)


# ---- #1 每标的时间尾切分（不跨标的、不泄露未来）----

def test_temporal_val_mask_per_symbol_tail() -> None:
    # 3 个标的各 10 窗口，val_frac=0.2 → 每标的末 2 个为 val
    groups = np.array([0] * 10 + [1] * 10 + [2] * 10)
    mask = _temporal_val_mask(groups, 0.2)
    for gid in (0, 1, 2):
        idx = np.flatnonzero(groups == gid)
        # val 必须是该组的"末尾"窗口（时间最新），不是开头
        assert mask[idx[-1]] and mask[idx[-2]]
        assert not mask[idx[0]]
    # 每个标的都既有 train 又有 val（不会整标的进 val）
    assert mask.sum() == 6


def test_build_sequences_tracks_group_id() -> None:
    panel = _multi_symbol_panel(n_syms=3, n_days=30, sym_col="ts_code")
    X, y, groups = _build_sequences(panel, ["f1", "f2"], "label", lookback=10, symbol_col="ts_code")
    assert X.shape[1:] == (10, 2)
    assert len(np.unique(groups)) == 3  # 三个标的都建了窗
    # 每个 group 的窗口数应一致（每标的 30-10=20）
    assert all((groups == g).sum() == 20 for g in range(3))


def test_dl_val_not_single_symbol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归 #1：旧实现会把最后一个标的整体塞进 val。新实现每标的都参与 train。"""
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    panel = _multi_symbol_panel(n_syms=4, n_days=50, sym_col="ts_code")
    res = train_dl(
        panel, arch="lstm", feature_cols=["f1", "f2"], label_col="label",
        job_dir=tmp_path, task="regression", symbol_col="ts_code",
        hyperparams={"max_epochs": 2, "lookback": 8, "hidden_size": 8, "batch_size": 16},
    )
    assert "r2" in res["oos_metrics"]
    assert len(res["curves"]["val_loss"]) == 2


# ---- #2 分类 n_out 用类别映射，支持 {-1, 1} ----

def test_dl_classification_signed_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归 #2：标签 {-1,1} 旧实现 CrossEntropy 收到 -1 直接崩。新实现映射到 {0,1}。"""
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    panel = _multi_symbol_panel(n_syms=4, n_days=60, sym_col="ts_code")
    res = train_dl(
        panel, arch="gru", feature_cols=["f1", "f2"], label_col="label_sign",
        job_dir=tmp_path, task="classification", symbol_col="ts_code",
        hyperparams={"max_epochs": 2, "lookback": 8, "hidden_size": 8, "batch_size": 16},
    )
    assert "accuracy" in res["oos_metrics"]
    # 预测应映射回原始类别 {-1, 1}，而非内部索引 {0, 1}
    assert set(res["oos_predictions"]["y_pred"]) <= {-1.0, 1.0}
    assert set(res["oos_predictions"]["y_true"]) <= {-1.0, 1.0}


def test_dl_classification_rejects_continuous_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归 #2：连续 label + task=classification 应明确报错，而非静默训练垃圾。"""
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    panel = _multi_symbol_panel(n_syms=4, n_days=60, sym_col="ts_code")
    with pytest.raises(ValueError, match="连续值"):
        train_dl(
            panel, arch="lstm", feature_cols=["f1", "f2"], label_col="label",  # 连续
            job_dir=tmp_path, task="classification", symbol_col="ts_code",
            hyperparams={"max_epochs": 1, "lookback": 8},
        )


# ---- #3 symbol_col 非 'symbol' 名也能正确分组 ----

def test_dl_respects_custom_symbol_col(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归 #3：列名为 ts_code 时，必须按它分组建窗，而非退化成单序列跨标的串味。"""
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    panel = _multi_symbol_panel(n_syms=3, n_days=40, sym_col="ts_code")
    # 用 symbol_col='ts_code' → 每标的 40-10=30 窗 × 3 = 90 窗
    X_ok, _, g_ok = _build_sequences(panel, ["f1", "f2"], "label", 10, "ts_code")
    # 若误用默认 'symbol'（不存在）→ 退化单序列，跨标的边界建窗（窗口更多且串味）
    X_bad, _, g_bad = _build_sequences(panel, ["f1", "f2"], "label", 10, "symbol")
    assert len(np.unique(g_ok)) == 3
    assert len(np.unique(g_bad)) == 1  # 退化
    assert X_ok.shape[0] == 90
    assert X_bad.shape[0] == 120 - 10  # 单序列 120 行 - lookback


# ---- #5 predict_with 支持 .pt（DL 模型输出作为新训练输入）----

def test_predict_with_pt_aligns_to_panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归 #5：训 DL → .pt → predict_with 输出对齐 panel 行（warmup 行 NaN），可作输入特征。"""
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    from app.training.lib import predict_with

    panel = _multi_symbol_panel(n_syms=3, n_days=40, sym_col="ts_code")
    res = train_dl(
        panel, arch="lstm", feature_cols=["f1", "f2"], label_col="label",
        job_dir=tmp_path, task="regression", symbol_col="ts_code",
        hyperparams={"max_epochs": 1, "lookback": 8, "hidden_size": 8, "batch_size": 16},
    )
    artifact = res["artifact_path"]
    assert artifact.endswith(".pt")

    preds = predict_with(artifact, panel, ["f1", "f2"])
    assert len(preds) == len(panel)  # 严格对齐 panel 行
    # 每标的前 lookback=8 行无窗口 → NaN；之后有预测
    n_nan = int(np.isnan(preds).sum())
    assert n_nan == 3 * 8  # 3 标的 × 8 warmup
    assert np.isfinite(preds[~np.isnan(preds)]).all()


def test_service_compose_dl_then_ml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归 #5：DL 输出作为 ML 新训练的输入特征（input_models 跨族组合）。"""
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    from app.training import TrainingRequest, TrainingService

    panel = _multi_symbol_panel(n_syms=4, n_days=60, sym_col="symbol")  # 用默认 symbol 名
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    dl = svc.train_now(
        TrainingRequest(
            name="A-lstm", model="lstm", task="regression", feature_cols=["f1", "f2"], label_col="label",
            symbol_col="symbol",
            hyperparams={"max_epochs": 1, "lookback": 8, "hidden_size": 8, "batch_size": 16},
        ),
        panel,
        owner_user_id=_OWNER_USER_ID,
    )
    assert dl.status == "succeeded", dl.error
    pt = str(Path(dl.artifact_dir) / "model.pt")

    b = svc.train_now(
        TrainingRequest(
            name="B-lgbm", model="lgbm", task="regression", feature_cols=["f1", "f2"], label_col="label",
            n_splits=4,
            input_models=[{"artifact_path": pt, "feature_cols": ["f1", "f2"], "as_col": "lstm_pred"}],
        ),
        panel,
        owner_user_id=_OWNER_USER_ID,
    )
    assert b.status == "succeeded", b.error  # 不再因 .pt 报 ValueError


# ---- #4 transformer n_heads 不整除 hidden_size 不崩 ----

def test_transformer_non_divisible_heads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归 #4：hidden_size=48, n_heads=5 不整除，旧实现构造即崩，新实现自动收缩头数。"""
    monkeypatch.setenv("QUANTBT_FORCE_DEVICE", "cpu")
    panel = _multi_symbol_panel(n_syms=3, n_days=50, sym_col="ts_code")
    res = train_dl(
        panel, arch="transformer", feature_cols=["f1", "f2"], label_col="label",
        job_dir=tmp_path, task="regression", symbol_col="ts_code",
        hyperparams={"max_epochs": 1, "lookback": 8, "hidden_size": 48, "n_heads": 5, "batch_size": 16},
    )
    assert "r2" in res["oos_metrics"]
