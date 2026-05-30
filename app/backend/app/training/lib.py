"""训练台标准库 —— agent/用户生成的训练代码 import 它来跑。

设计：训练台"本质是跑代码"。生成的脚本顶上写
    from app.training.lib import emit, pick_device, predict_with
就能：选设备、把已训练模型的输出当特征（模型组合）、最后 emit 结果回吐给 runner。

**模块级零 torch 导入**：本文件被主进程也会 import（service 用 predict_with）；
torch 只在 `pick_device` 等函数内惰性 import，确保主进程永不加载 torch（避 OMP）。
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .emit import format_emit


def emit(payload: dict[str, Any]) -> None:
    """训练脚本最后一行调用：把结构化结果打到 stdout，runner 解析。"""
    print(format_emit(payload), flush=True)


def pick_device(prefer: str | None = None) -> str:
    """自动选最好的设备：cuda(NVIDIA) → mps(Apple 芯片) → cpu。

    - 环境变量 `QUANTBT_FORCE_DEVICE` 优先（测试/调试用，如强制 cpu）。
    - `prefer` 次之。
    - 仅在此惰性 import torch（本函数只该被 DL 代码在子进程里调用）。
    """
    forced = os.environ.get("QUANTBT_FORCE_DEVICE")
    if forced:
        return forced
    if prefer:
        return prefer
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def load_model(artifact_path: str | Path) -> Any:
    """加载训练好的 ML artifact（`.pkl`/`.joblib` → pickle，树/线性模型）。

    DL 的 `.pt` 不在此加载（需重建网络）；走 `predict_with` 的 DL 分支。
    """
    p = Path(artifact_path)
    if p.suffix in (".pkl", ".joblib"):
        with p.open("rb") as fh:
            return pickle.load(fh)
    raise ValueError(f"load_model 仅支持 .pkl/.joblib（DL .pt 请用 predict_with）: {p.suffix}（{p}）")


def predict_with(
    artifact_path: str | Path,
    panel: pd.DataFrame,
    feature_cols: list[str],
) -> np.ndarray:
    """**模型组合原语**：拿一个已训练模型对 panel 推理，输出可作为新模型的输入特征。

    支持任意 ML（.pkl）与 DL（.pt）模型，兑现"已训练 ml/dl 模型输出可作新训练输入"：
        panel["model_a_pred"] = predict_with(a_artifact, panel, a_features)

    返回长度恒等于 len(panel)、与 panel 行对齐的一维数组：
    - ML：逐行 predict。
    - DL：按 .pt 内保存的 lookback/symbol_col 逐标的滑窗预测，每个标的的前 lookback 行
      （无完整窗口）填 NaN，其余按窗口末步对齐到该行。
    """
    p = Path(artifact_path)
    if p.suffix == ".pt":
        return _predict_dl(p, panel, feature_cols)
    model = load_model(p)
    X = panel[feature_cols]
    return np.asarray(model.predict(X))


def _predict_dl(artifact_path: Path, panel: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    """DL .pt 推理，输出对齐到 panel 行（warmup 行 NaN）。

    惰性 import torch（只在真遇到 .pt 时）；先设 KMP_DUPLICATE_LIB_OK 防御 OMP 冲突。
    """
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    import torch

    from ..models.dl.architectures import build_network

    ckpt = torch.load(artifact_path, map_location="cpu", weights_only=False)
    cfg = ckpt["config"]
    arch = ckpt["arch"]
    lookback = int(cfg["lookback"])
    n_out = int(cfg["n_outputs"])
    symbol_col = cfg.get("symbol_col", "symbol")
    classes = cfg.get("classes")
    feats = feature_cols or cfg["feature_cols"]

    net = build_network(arch, len(feats), n_out, **(cfg.get("net_hp") or {}))
    net.load_state_dict(ckpt["state_dict"])
    net.eval()

    out = np.full(len(panel), np.nan, dtype=float)
    # 与 trainer._build_sequences 同样的分组规则，但要保留每个窗口对应的 panel 行号
    pos = np.arange(len(panel))

    def _infer_group(idx_rows: np.ndarray) -> None:
        g = panel.iloc[idx_rows]
        if "ts" in g.columns:
            order = np.argsort(g["ts"].to_numpy(), kind="stable")
            idx_rows = idx_rows[order]
            g = panel.iloc[idx_rows]
        arr = g[feats].to_numpy(dtype=np.float32)
        if len(arr) <= lookback:
            return
        windows = np.stack([arr[i - lookback : i] for i in range(lookback, len(arr))])
        with torch.no_grad():
            logits = net(torch.tensor(windows, dtype=torch.float32)).cpu().numpy()
        if classes is not None:  # 分类 → 映射回原始类别标签
            preds = np.asarray(classes, dtype=float)[logits.argmax(axis=1)]
        else:
            preds = logits.reshape(-1)
        out[idx_rows[lookback:]] = preds

    if symbol_col and symbol_col in panel.columns:
        for _, sub in pd.DataFrame({"_g": panel[symbol_col].to_numpy(), "_pos": pos}).groupby("_g", sort=False):
            _infer_group(sub["_pos"].to_numpy())
    else:
        _infer_group(pos)
    return out


__all__ = ["emit", "load_model", "pick_device", "predict_with"]
