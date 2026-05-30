"""M6 · 模型训练 + Purged CV。"""

from __future__ import annotations

from .catalog import (
    MODEL_CATALOG,
    ModelCard,
    get_model_card,
    is_dl_model,
    list_model_cards,
    model_catalog_summary,
)
from .purged_cv import FoldSplit, purged_kfold, walk_forward
from .training import FoldMetrics, ModelSpec, TrainResult, train_model

__all__ = [
    "FoldMetrics",
    "FoldSplit",
    "MODEL_CATALOG",
    "ModelCard",
    "ModelSpec",
    "TrainResult",
    "get_model_card",
    "is_dl_model",
    "list_model_cards",
    "model_catalog_summary",
    "purged_kfold",
    "train_model",
    "walk_forward",
]
