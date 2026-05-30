"""emit_train 协议 —— 子进程/Agent 训练脚本 → 训练台的结构化回吐。

仿 IDE 的 `__QUANTBT_RESULT__`。DL 训练在隔离子进程里跑（避 torch 的 OpenMP 冲突），
训练完在 stdout 最后打印一行 `__QUANTBT_TRAIN__ <json>`，主进程解析后落盘 + 登记 M12。

payload 约定（与 TrainResult.to_dict 对齐）：
  {"oos_metrics":{...}, "fold_metrics":[...], "feature_importance":{...}|null,
   "curves":{"train_loss":[...],"val_loss":[...]}, "oos_predictions":{...}|null,
   "artifact_path":"model.pt"|null, "tensorboard_logdir":"tb"|null, "elapsed_seconds":N}
"""

from __future__ import annotations

import json
from typing import Any

EMIT_MARKER = "__QUANTBT_TRAIN__"


def format_emit(payload: dict[str, Any]) -> str:
    """子进程调用：生成要打印到 stdout 的标记行。"""
    return f"{EMIT_MARKER} {json.dumps(payload, ensure_ascii=False)}"


def parse_emit(stdout: str) -> dict[str, Any] | None:
    """主进程调用：从子进程 stdout 里取最后一条 emit 记录。"""
    found: dict[str, Any] | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(EMIT_MARKER):
            raw = line[len(EMIT_MARKER):].strip()
            try:
                found = json.loads(raw)
            except json.JSONDecodeError:
                continue
    return found


__all__ = ["EMIT_MARKER", "format_emit", "parse_emit"]
