"""训练台（Training Console）· 跑代码为本：ML 进程内 / DL + 自由代码全功率子进程。

主进程绝不 import torch；DL 与生成代码经 runner 子进程触达。M12 登记血缘。
"""

from __future__ import annotations

from .backtest_bridge import backtest_job, backtest_trained_model, scores_to_weights
from .codegen import GraphCodegenError, graph_to_code, spec_to_code
from .emit import EMIT_MARKER, format_emit, parse_emit
from .lib import emit, load_model, pick_device, predict_with
from .runner import RunnerResult, run_code
from .schema_drift import (
    DataSchemaRecertificationRequired,
    DatasetSchema,
    SchemaDiff,
    compute_dataset_schema,
    diff_schemas,
    schema_change_event_ref,
    schema_fingerprint,
)
from .service import TrainingRequest, TrainingService
from .store import TrainingJob, TrainingJobStore

__all__ = [
    "EMIT_MARKER",
    "DataSchemaRecertificationRequired",
    "DatasetSchema",
    "GraphCodegenError",
    "RunnerResult",
    "SchemaDiff",
    "TrainingJob",
    "TrainingJobStore",
    "TrainingRequest",
    "TrainingService",
    "backtest_job",
    "backtest_trained_model",
    "compute_dataset_schema",
    "diff_schemas",
    "emit",
    "format_emit",
    "graph_to_code",
    "load_model",
    "parse_emit",
    "pick_device",
    "predict_with",
    "run_code",
    "schema_change_event_ref",
    "schema_fingerprint",
    "scores_to_weights",
    "spec_to_code",
]
