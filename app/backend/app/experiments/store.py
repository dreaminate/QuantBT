"""M12 · 实验/Run/Model 注册表 (JSONL append-only)。

为什么不用 MLflow：MLflow 体积大、自带 web UI 与本项目设计冲突。我们要的功能
其实只是：
- 给每次 backtest run 注册条目
- 记录 lineage (parent_run_id / forked_from)
- 模型版本 + stage promotion (dev → staging → production → archived)

写入 `data/experiments/{store,runs,models}.jsonl` 三个文件。
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


ModelStage = Literal["dev", "staging", "production", "archived"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class Experiment:
    experiment_id: str
    name: str
    asset_class: str
    created_at_utc: str = field(default_factory=_now)
    tags: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Run:
    run_id: str
    experiment_id: str
    started_at_utc: str
    finished_at_utc: str | None
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    inputs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    artifact_paths: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    parent_run_id: str | None = None
    forked_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelVersion:
    model_id: str
    version: int
    stage: ModelStage
    created_at_utc: str
    metrics: dict[str, float] = field(default_factory=dict)
    artifact_path: str | None = None
    source_run_id: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _JsonlStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()

    def append(self, payload: dict[str, Any]) -> None:
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(line) for line in self._path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ExperimentStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._exp_store = _JsonlStore(self._root / "experiments.jsonl")

    def create_experiment(self, name: str, asset_class: str, description: str = "", tags: dict[str, str] | None = None) -> Experiment:
        exp = Experiment(experiment_id=_gen_id("exp"), name=name, asset_class=asset_class, description=description, tags=tags or {})
        self._exp_store.append(exp.to_dict())
        return exp

    def list_experiments(self) -> list[Experiment]:
        # 最后一次出现的即为最新（允许后续追加状态变更）
        latest: dict[str, dict[str, Any]] = {}
        for row in self._exp_store.read_all():
            latest[row["experiment_id"]] = row
        return [Experiment(**v) for v in latest.values()]


class RunStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._store = _JsonlStore(self._root / "runs.jsonl")

    def create_run(
        self,
        experiment_id: str,
        inputs: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
        parent_run_id: str | None = None,
        forked_from: str | None = None,
    ) -> Run:
        run = Run(
            run_id=_gen_id("run"),
            experiment_id=experiment_id,
            started_at_utc=_now(),
            finished_at_utc=None,
            status="running",
            inputs=inputs or {},
            tags=tags or {},
            parent_run_id=parent_run_id,
            forked_from=forked_from,
        )
        self._store.append(run.to_dict())
        return run

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        metrics: dict[str, float] | None = None,
        artifact_paths: list[str] | None = None,
        finished: bool = False,
    ) -> Run:
        current = self.get_run(run_id)
        if status is not None:
            current.status = status  # type: ignore[assignment]
        if metrics:
            current.metrics.update(metrics)
        if artifact_paths:
            current.artifact_paths = list({*current.artifact_paths, *artifact_paths})
        if finished:
            current.finished_at_utc = _now()
        self._store.append(current.to_dict())
        return current

    def get_run(self, run_id: str) -> Run:
        for row in reversed(self._store.read_all()):
            if row["run_id"] == run_id:
                return Run(**row)
        raise KeyError(f"run 不存在: {run_id}")

    def list_runs(self, experiment_id: str | None = None) -> list[Run]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._store.read_all():
            latest[row["run_id"]] = row
        items = [Run(**v) for v in latest.values()]
        if experiment_id:
            items = [r for r in items if r.experiment_id == experiment_id]
        return items

    def lineage(self, run_id: str) -> list[Run]:
        """返回 run + 所有祖先（parent_run_id 链 + forked_from）。"""

        chain: list[Run] = []
        seen: set[str] = set()
        cur_id: str | None = run_id
        while cur_id and cur_id not in seen:
            try:
                run = self.get_run(cur_id)
            except KeyError:
                break
            chain.append(run)
            seen.add(cur_id)
            cur_id = run.parent_run_id or run.forked_from
        return chain


class ModelRegistry:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._store = _JsonlStore(self._root / "models.jsonl")

    def register_version(
        self,
        model_id: str,
        artifact_path: str | None = None,
        source_run_id: str | None = None,
        metrics: dict[str, float] | None = None,
        note: str = "",
    ) -> ModelVersion:
        versions = [v.version for v in self.list_versions(model_id)]
        next_v = (max(versions) + 1) if versions else 1
        mv = ModelVersion(
            model_id=model_id,
            version=next_v,
            stage="dev",
            created_at_utc=_now(),
            metrics=metrics or {},
            artifact_path=artifact_path,
            source_run_id=source_run_id,
            note=note,
        )
        self._store.append(mv.to_dict())
        return mv

    def promote(self, model_id: str, version: int, stage: ModelStage) -> ModelVersion:
        for v in self.list_versions(model_id):
            if v.version == version:
                v.stage = stage
                self._store.append(v.to_dict())
                return v
        raise KeyError(f"model={model_id} version={version} 未注册")

    def list_versions(self, model_id: str) -> list[ModelVersion]:
        latest: dict[tuple[str, int], dict[str, Any]] = {}
        for row in self._store.read_all():
            if row["model_id"] == model_id:
                latest[(row["model_id"], row["version"])] = row
        return [ModelVersion(**v) for v in latest.values()]

    def list_models(self) -> list[str]:
        return sorted({row["model_id"] for row in self._store.read_all()})


__all__ = [
    "Experiment",
    "ExperimentStore",
    "ModelRegistry",
    "ModelStage",
    "ModelVersion",
    "Run",
    "RunStore",
]
