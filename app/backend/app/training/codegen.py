"""结构化 spec → 训练脚本代码。

"训练台本质是跑代码"：结构化的一键训练，其实也是先把 spec 渲染成脚本再跑——
和 agent 直接生成代码同一条执行路径（runner 全功率进程）。这样 ML/DL 不再硬分，
都是"生成代码 → 跑"。

`spec_to_code(spec)` 接收 request.to_dict()，避免与 service 循环 import。
脚本从 `QUANTBT_PANEL_PATH`(parquet) 读数据、`QUANTBT_JOB_DIR` 落产物，
最后 `emit(...)` 回吐与 TrainResult.to_dict 同形的结果。
"""

from __future__ import annotations

from typing import Any

from ..models.catalog import get_model_card

_HEADER = '''import os
from pathlib import Path

import pandas as pd

from app.training.lib import emit, predict_with  # noqa: F401

panel = pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])
job_dir = Path(os.environ["QUANTBT_JOB_DIR"])
'''

# 已实现 torch 训练模板的 DL 架构（与 app.models.dl.architectures 对齐）；
# 卡片可收录更多 DL（tft/nbeats…），但未在此集合内 → codegen 明确提示模板排队。
_RUNNABLE_DL = {"lstm", "gru", "alstm", "mlp", "tcn", "transformer", "tft", "nbeats", "nhits", "deepar"}


def spec_to_code(spec: dict[str, Any]) -> str:
    card = get_model_card(spec["model"])
    if card.family == "dl":
        return _dl_code(spec)
    return _ml_code(spec)


def _ml_code(spec: dict[str, Any]) -> str:
    body = f'''
from app.models.training import ModelSpec, train_model

model_spec = ModelSpec(
    task={spec["task"]!r},
    model={spec["model"]!r},
    feature_cols={list(spec["feature_cols"])!r},
    label_col={spec.get("label_col", "label")!r},
    cv_scheme={spec.get("cv_scheme", "purged_kfold")!r},
    n_splits={int(spec.get("n_splits", 5))},
    embargo_pct={float(spec.get("embargo_pct", 0.01))},
    walk_forward_train={int(spec.get("walk_forward_train", 252))},
    walk_forward_test={int(spec.get("walk_forward_test", 63))},
    walk_forward_embargo={int(spec.get("walk_forward_embargo", 5))},
    hyperparams={dict(spec.get("hyperparams") or {})!r},
    group_col={spec.get("group_col")!r},
)
res = train_model(model_spec, panel, artifact_dir=job_dir)
emit(res.to_dict())
'''
    return _HEADER + body


def _dl_code(spec: dict[str, Any]) -> str:
    model = spec["model"]
    if model not in _RUNNABLE_DL:
        raise NotImplementedError(
            f"DL 模型 {model} 的训练模板排队中（已实现: {sorted(_RUNNABLE_DL)}）；卡片已收录，"
            f"实现该架构只需在 app/models/dl/architectures.py 加一个 nn.Module。"
        )
    hp = dict(spec.get("hyperparams") or {})
    body = f'''
from app.models.dl import train_dl

res = train_dl(
    panel,
    arch={model!r},
    feature_cols={list(spec["feature_cols"])!r},
    label_col={spec.get("label_col", "label")!r},
    job_dir=job_dir,
    task={spec["task"]!r},
    symbol_col={spec.get("symbol_col", "symbol")!r},
    hyperparams={hp!r},
)
emit(res)
'''
    return _HEADER + body


__all__ = ["spec_to_code"]
