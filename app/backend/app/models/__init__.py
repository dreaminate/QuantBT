"""M6 · 模型训练 + Purged CV。"""

from __future__ import annotations

from .purged_cv import FoldSplit, purged_kfold, walk_forward
from .training import FoldMetrics, ModelSpec, TrainResult, train_model

__all__ = [
    "FoldMetrics",
    "FoldSplit",
    "ModelSpec",
    "TrainResult",
    "purged_kfold",
    "train_model",
    "walk_forward",
]
