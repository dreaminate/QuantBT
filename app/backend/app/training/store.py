"""训练台 · TrainingJob 状态机 + JSONL 持久化。

沿用 M12 experiments 的 append-only + latest-wins 模式：同一 job_id 多次写入，
读取时取最后一条为最新状态。落 `data/training_runs/jobs.jsonl`，每个 job 的产物
落 `data/training_runs/<job_id>/`。
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

JobStatus = Literal["queued", "running", "succeeded", "failed"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen_id() -> str:
    return f"trn-{uuid.uuid4().hex[:12]}"


@dataclass
class TrainingJob:
    job_id: str
    name: str
    model: str  # catalog key，或 "(code)" 表示自由代码任务
    family: str  # ml / dl / code / mixed —— 仅作标签，执行不再硬分
    task: str
    status: JobStatus = "queued"
    created_at_utc: str = field(default_factory=_now)
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    request: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    artifact_dir: str | None = None
    experiment_id: str | None = None
    run_id: str | None = None
    model_version: int | None = None
    model_passport_ref: str | None = None
    validation_dossier_ref: str | None = None
    qro_id: str | None = None
    research_graph_command_id: str | None = None
    compiler_ir_ref: str | None = None
    compiler_pass_ref: str | None = None
    entrypoint_coverage_ref: str | None = None
    tensorboard: bool = False  # 该模型是否产 TensorBoard
    error: str | None = None
    elapsed_seconds: float | None = None
    # 动机/设计富文档（why/data/window/label/design/arch/hparams + sections + io_spec）。
    # 提交时从 request 持久化进 job 快照，`to_dict` 透传给前端作业台 dashboard。
    # 空 dict = 旧 job 无富文档（向后兼容，前端按 mock/缺省渲染、不假绿）。
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrainingJobStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "jobs.jsonl"
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()

    def _append(self, payload: dict[str, Any]) -> None:
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _read_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                json.loads(line)
                for line in self._path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    def create(self, job: TrainingJob) -> TrainingJob:
        self._append(job.to_dict())
        return job

    def save(self, job: TrainingJob) -> TrainingJob:
        """持久化当前 job 快照（新一行 append，latest-wins）。"""
        self._append(job.to_dict())
        return job

    def get(self, job_id: str) -> TrainingJob:
        for row in reversed(self._read_all()):
            if row["job_id"] == job_id:
                return TrainingJob(**row)
        raise KeyError(f"训练任务不存在: {job_id}")

    def list(self) -> list[TrainingJob]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._read_all():
            latest[row["job_id"]] = row
        items = [TrainingJob(**v) for v in latest.values()]
        items.sort(key=lambda j: j.created_at_utc, reverse=True)
        return items

    def job_dir(self, job_id: str) -> Path:
        d = self._root / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d


__all__ = ["JobStatus", "TrainingJob", "TrainingJobStore", "_gen_id"]
