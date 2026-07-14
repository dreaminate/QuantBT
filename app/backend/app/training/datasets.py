"""训练台 · 内置训练数据集（先用确定性合成 demo，保证开箱即训通）。

返回的 panel 含 ts / symbol / 若干特征列 / label，可直接喂训练台。
后续可接 datasets/samples.py 的真 sample + 因子工厂算特征（留扩展）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

FEATURES = ["f_mom5", "f_mom20", "f_vol20", "f_value"]

_DATASETS: dict[str, dict[str, Any]] = {
    "demo_ashare_xsec": {
        "label": "合成 · A股截面 demo",
        "asset_class": "a_share",
        "n_symbols": 30,
        "n_days": 240,
        "seed": 7,
    },
    "demo_crypto_ts": {
        "label": "合成 · 加密时序 demo",
        "asset_class": "crypto_perp",
        "n_symbols": 5,
        "n_days": 365,
        "seed": 11,
    },
}


def list_training_datasets() -> list[dict[str, Any]]:
    return [
        {
            "dataset_id": k,
            "label": v["label"],
            "asset_class": v["asset_class"],
            "feature_cols": FEATURES,
            "label_col": "label",
            "symbol_col": "symbol",
            "rows": v["n_symbols"] * v["n_days"],
        }
        for k, v in _DATASETS.items()
    ]


def load_training_panel(dataset_id: str) -> pd.DataFrame:
    if dataset_id not in _DATASETS:
        raise KeyError(dataset_id)
    cfg = _DATASETS[dataset_id]
    rng = np.random.default_rng(cfg["seed"])
    n_sym, n_days = cfg["n_symbols"], cfg["n_days"]
    base = datetime(2023, 1, 1, tzinfo=UTC)

    n = n_sym * n_days
    feats = rng.normal(size=(n, len(FEATURES))).astype(float)
    # 可学习信号 + 噪声（保证 r2>0 / acc>0.55，demo 训得动）
    label = (
        0.5 * feats[:, 0] - 0.3 * feats[:, 1] + 0.2 * feats[:, 2] + rng.normal(scale=0.4, size=n)
    )
    ts = np.repeat([base + timedelta(days=d) for d in range(n_days)], n_sym)
    symbol = np.tile([f"SYM{s:03d}" for s in range(n_sym)], n_days)

    df = pd.DataFrame(feats, columns=FEATURES)
    df.insert(0, "symbol", symbol)
    df.insert(0, "ts", ts)
    # Deterministic synthetic observations are known when emitted.  Keeping an
    # explicit knowledge-time axis lets confirmatory consumers exercise the
    # same fail-closed PIT path as real datasets without inventing later revisions.
    df.insert(1, "known_at", ts)
    df["label"] = label
    df["label_cls"] = (label > 0).astype(int)
    # close 价格列：每标的随机游走，日收益随 label 轻微倾斜，让"训练→回测"有真实可学信号。
    # 数据按 day-major / symbol-minor 平铺，reshape 成 (n_days, n_sym) 做按标的累乘游走。
    label_2d = label.reshape(n_days, n_sym)
    rets = 0.02 * np.tanh(label_2d) + rng.normal(scale=0.01, size=(n_days, n_sym))
    close_2d = 100.0 * np.cumprod(1.0 + rets, axis=0)
    df["close"] = close_2d.reshape(-1)
    return df.sort_values(["ts", "symbol"]).reset_index(drop=True)


__all__ = ["FEATURES", "list_training_datasets", "load_training_panel"]
