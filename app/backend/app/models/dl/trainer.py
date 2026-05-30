"""通用 DL 训练循环（架构无关）。

train_dl(panel, arch="lstm"|"gru"|...) 共用一套：滑窗序列 → **每标的时间尾切分** train/val
→ build_network(arch) → epoch 训练（train/val 学习曲线）→ OOS 指标 → 存 model.pt。
返回与 models.training.TrainResult.to_dict 同形的 dict。

只在隔离全功率子进程里跑（torch 在此 import）。设备自动 cuda→mps→cpu。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _build_sequences(
    panel: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    lookback: int,
    symbol_col: str | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """滑窗序列。返回 (X[n,lookback,F], y[n], group_id[n])。

    group_id 标记每个窗口属于哪个标的（按 symbol 分组、组内按 ts 升序），供调用方做
    **每标的时间尾切分**，避免跨标的串味与未来泄露。
    """
    xs: list[np.ndarray] = []
    ys: list[Any] = []
    groups: list[int] = []

    def _emit(g: pd.DataFrame, gid: int) -> None:
        feats = g[feature_cols].to_numpy(dtype=np.float32)
        labels = g[label_col].to_numpy()
        for i in range(lookback, len(g)):
            xs.append(feats[i - lookback : i])
            ys.append(labels[i])
            groups.append(gid)

    if symbol_col and symbol_col in panel.columns:
        for gid, (_, g) in enumerate(panel.groupby(symbol_col, sort=False)):
            _emit(g.sort_values("ts") if "ts" in g else g, gid)
    else:
        _emit(panel.sort_values("ts") if "ts" in panel else panel, 0)

    if not xs:
        raise ValueError(f"数据太短，凑不出一个 lookback={lookback} 的窗口")
    return np.stack(xs), np.asarray(ys), np.asarray(groups, dtype=np.int64)


def _temporal_val_mask(groups: np.ndarray, val_frac: float) -> np.ndarray:
    """每标的取末尾 val_frac 的窗口作为验证集（窗口已按组内时间升序）。

    返回 bool mask（True=val）。保证每个标的的 val 都是其**最近时间**的样本，
    且训练/验证不跨标的，不会用未来训练。全局兜底至少 1 train + 1 val。
    """
    mask = np.zeros(len(groups), dtype=bool)
    for gid in np.unique(groups):
        idx = np.flatnonzero(groups == gid)  # 已是时间升序
        n_val = int(len(idx) * val_frac)
        if n_val > 0:
            mask[idx[-n_val:]] = True
    # 兜底：避免空 train 或空 val
    if not mask.any():
        mask[-1] = True
    if mask.all():
        mask[0] = False
    return mask


def train_dl(
    panel: pd.DataFrame,
    *,
    arch: str,
    feature_cols: list[str],
    label_col: str = "label",
    job_dir: str | Path,
    task: str = "regression",
    hyperparams: dict[str, Any] | None = None,
    symbol_col: str | None = "symbol",
    seed: int = 7,
    device: str | None = None,
) -> dict[str, Any]:
    import torch
    from torch import nn

    from app.training.lib import pick_device

    from .architectures import build_network

    hp = dict(hyperparams or {})
    lookback = int(hp.get("lookback", 20))
    max_epochs = int(hp.get("max_epochs", 20))
    lr = float(hp.get("learning_rate", 1e-3))
    batch_size = int(hp.get("batch_size", 64))
    val_frac = float(hp.get("val_frac", 0.2))

    t0 = time.perf_counter()
    torch.manual_seed(seed)
    np.random.seed(seed)
    dev = device or pick_device()
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)

    X, y, groups = _build_sequences(panel, feature_cols, label_col, lookback, symbol_col)
    val_mask = _temporal_val_mask(groups, val_frac)
    train_mask = ~val_mask
    n_train = int(train_mask.sum())
    if n_train < 1:
        raise ValueError("训练样本不足")

    is_cls = task == "classification"
    Xt = torch.tensor(X, dtype=torch.float32)
    classes: list[float] | None = None
    if is_cls:
        # 用拟合的类别映射，支持非连续/带符号标签（如 {-1, 1}）；拒绝连续值。
        uniq = np.unique(y)
        if len(uniq) > max(20, 0.5 * len(y)):
            raise ValueError(
                f"classification 任务的 label 看起来是连续值（{len(uniq)} 个不同取值）；"
                f"请改用 regression 或提供离散类别列。"
            )
        classes = [float(c) for c in uniq]
        class_to_idx = {c: i for i, c in enumerate(uniq)}
        y_idx = np.array([class_to_idx[v] for v in y], dtype=np.int64)
        n_out = len(uniq)
        yt = torch.tensor(y_idx, dtype=torch.long)
    else:
        n_out = 1
        yt = torch.tensor(y.astype(np.float32)).reshape(-1, 1)

    tmask = torch.tensor(train_mask)
    vmask = torch.tensor(val_mask)
    Xtr, Xva = Xt[tmask].to(dev), Xt[vmask].to(dev)
    ytr, yva = yt[tmask].to(dev), yt[vmask].to(dev)
    n_train = Xtr.shape[0]

    # 把训练相关超参传给架构（lookback 供 mlp/transformer 用）
    net_hp = {k: v for k, v in hp.items() if k not in ("max_epochs", "learning_rate", "batch_size", "val_frac")}
    net_hp.setdefault("lookback", lookback)
    model = build_network(arch, len(feature_cols), n_out, **net_hp).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss() if is_cls else nn.MSELoss()

    # TensorBoard：写 event 文件到 <job_dir>/tb（无 tensorboard 时优雅跳过）
    writer = None
    tb_logdir = job_dir / "tb"
    try:
        from torch.utils.tensorboard import SummaryWriter

        writer = SummaryWriter(log_dir=str(tb_logdir))
    except Exception:  # noqa: BLE001 — tensorboard 缺失不阻塞训练
        writer = None

    train_curve: list[float] = []
    val_curve: list[float] = []
    for epoch in range(max_epochs):
        model.train()
        perm = torch.randperm(n_train)
        tot = 0.0
        for s in range(0, n_train, batch_size):
            idx = perm[s : s + batch_size]
            opt.zero_grad()
            loss = loss_fn(model(Xtr[idx]), ytr[idx])
            loss.backward()
            opt.step()
            tot += float(loss.item()) * len(idx)
        train_curve.append(tot / n_train)
        model.eval()
        with torch.no_grad():
            val_curve.append(float(_batched_loss(model, Xva, yva, loss_fn, batch_size)))
        if writer is not None:
            writer.add_scalar("loss/train", train_curve[-1], epoch)
            writer.add_scalar("loss/val", val_curve[-1], epoch)
    if writer is not None:
        writer.close()

    model.eval()
    with torch.no_grad():
        out = _batched_forward(model, Xva, batch_size)
    y_true_idx = yva.cpu().numpy().reshape(-1)
    oos_metrics: dict[str, float] = {}
    if is_cls:
        pred_idx = out.argmax(axis=1)
        oos_metrics["accuracy"] = float((pred_idx == y_true_idx).mean())
        # 映射回原始类别标签，便于评价图/下游使用
        cls_arr = np.asarray(classes, dtype=float)
        y_true = cls_arr[y_true_idx]
        y_pred = cls_arr[pred_idx]
    else:
        y_pred = out.reshape(-1)
        y_true = y_true_idx.astype(float)
        resid = y_true - y_pred
        ss_res = float(np.sum(resid**2))
        ss_tot = float(np.sum((y_true - y_true.mean()) ** 2)) or 1.0
        oos_metrics["mse"] = ss_res / len(y_true)
        oos_metrics["r2"] = 1.0 - ss_res / ss_tot

    artifact = job_dir / "model.pt"
    torch.save(
        {
            "arch": arch,
            "state_dict": model.state_dict(),
            "config": {
                "feature_cols": feature_cols,
                "label_col": label_col,
                "task": task,
                "n_outputs": n_out,
                "lookback": lookback,
                "net_hp": net_hp,
                "classes": classes,
                "symbol_col": symbol_col,
            },
        },
        artifact,
    )

    return {
        "spec": {"model": arch, "task": task, "feature_cols": feature_cols, "label_col": label_col, "hyperparams": hp},
        "oos_metrics": oos_metrics,
        "fold_metrics": [],
        "feature_importance": None,
        "artifact_path": str(artifact),
        "elapsed_seconds": round(time.perf_counter() - t0, 4),
        "curves": {"train_loss": train_curve, "val_loss": val_curve},
        "oos_predictions": {"y_true": y_true.tolist(), "y_pred": y_pred.tolist()},
        "device": dev,
        "tensorboard_logdir": str(tb_logdir) if writer is not None or tb_logdir.exists() else None,
    }


def _batched_forward(model, X, batch_size: int):
    """分批前向，避免一次性把整个验证集喂进去导致 GPU/MPS OOM。"""
    import numpy as _np
    import torch

    outs = []
    with torch.no_grad():
        for s in range(0, X.shape[0], batch_size):
            outs.append(model(X[s : s + batch_size]).cpu().numpy())
    return _np.concatenate(outs, axis=0) if outs else _np.empty((0,))


def _batched_loss(model, X, y, loss_fn, batch_size: int) -> float:
    """分批求验证损失（按样本数加权平均），与训练同样避免 OOM。"""
    import torch

    total = 0.0
    n = X.shape[0]
    if n == 0:
        return 0.0
    with torch.no_grad():
        for s in range(0, n, batch_size):
            xb, yb = X[s : s + batch_size], y[s : s + batch_size]
            total += float(loss_fn(model(xb), yb).item()) * xb.shape[0]
    return total / n


__all__ = ["train_dl"]
