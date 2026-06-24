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
from .cpcv import (
    CPCVSplit,
    assemble_cpcv_paths,
    build_path_matrix,
    cpcv_metric_distribution,
    cpcv_splits,
    n_cpcv_combinations,
    n_cpcv_paths,
)
from .purged_cv import FoldSplit, purged_kfold, walk_forward
from .training import FoldMetrics, ModelSpec, TrainResult, train_model

__all__ = [
    "CPCVSplit",
    "FoldMetrics",
    "FoldSplit",
    "MODEL_CATALOG",
    "ModelCard",
    "ModelSpec",
    "TrainResult",
    "assemble_cpcv_paths",
    "build_path_matrix",
    "cpcv_metric_distribution",
    "cpcv_splits",
    "get_model_card",
    "is_dl_model",
    "list_model_cards",
    "model_catalog_summary",
    "n_cpcv_combinations",
    "n_cpcv_paths",
    "purged_kfold",
    "train_model",
    "walk_forward",
]
