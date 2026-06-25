"""训练台执行层 TrainingService。

"训练台本质是跑代码"：一次训练 = 把代码跑成一个可追踪的 TrainingJob。
- **结构化一键训练（spec）**：
  - ML 模型 → 进程内直接 `train_model`（轻、快；不碰 torch）。
  - DL 模型 → `spec_to_code` 渲染成脚本 → runner 全功率进程跑（torch 在子进程）。
- **自由代码训练（code）**：agent/用户生成的脚本 → runner 全功率进程跑。
- **模型组合**：`input_models` 把已训练模型的输出注入为新训练的特征列
  （`predict_with`），任意 ML/DL、任意数量。
- 每个 job 落 `data/training_runs/<job_id>/` 并登记 M12（Run + ModelVersion）。

**主进程绝不 import torch**：DL/代码一律经 subprocess 触达。
"""

from __future__ import annotations

import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..experiments.store import ExperimentStore, ModelRegistry, RunStore
from ..models.catalog import get_model_card
from ..models.training import ModelSpec, train_model
from .codegen import load_pit_panel, spec_to_code
from .lib import predict_with
from .runner import run_code
from .store import TrainingJob, TrainingJobStore, _gen_id


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slice_front_dates(panel: pd.DataFrame, ts_col: str, train_fraction: float) -> pd.DataFrame:
    """只保留前 train_fraction 比例的**交易日**（按 ts 唯一日期切，不是按行）。

    与回测 oos_fraction=1-train_fraction 用同一日期分位 → 训练(前段)与 OOS 回测(后段)
    严格互补、零重叠、无未来泄露。train_fraction 不在 (0,1] → 报错；=1 或 ts_col 缺失 → 原样返回。
    """
    if not (0.0 < train_fraction <= 1.0):
        raise ValueError("train_fraction 必须在 (0, 1] 区间")
    if train_fraction >= 1.0 or ts_col not in panel.columns:
        return panel
    import numpy as _np

    dates = _np.sort(panel[ts_col].unique())
    if len(dates) < 2:
        return panel
    cut_idx = min(max(int(len(dates) * train_fraction), 1), len(dates))
    keep = set(dates[:cut_idx].tolist())
    return panel[panel[ts_col].isin(keep)].copy()


@dataclass
class TrainingRequest:
    name: str
    model: str  # catalog key
    task: str
    feature_cols: list[str]
    label_col: str = "label"
    asset_class: str = "a_share"
    cv_scheme: str = "purged_kfold"
    n_splits: int = 5
    embargo_pct: float = 0.01
    walk_forward_train: int = 252
    walk_forward_test: int = 63
    walk_forward_embargo: int = 5
    hyperparams: dict[str, Any] = field(default_factory=dict)
    group_col: str | None = None
    symbol_col: str = "symbol"  # DL 序列按此分组建窗；真实面板可能叫 ts_code
    ts_col: str = "ts"
    # 严格无泄露 OOS：只用**前** train_fraction 比例的交易日训练（与回测 oos_fraction=1-train_fraction
    # 同一切点互补）。None=用全程数据训练（默认，与历史行为一致）。
    train_fraction: float | None = None
    experiment_name: str | None = None
    # R28 双时态 PIT 点查（堵 look-ahead）：训练只见「截至 as_of_known 已知」的行（重述 as-of），
    # 晚于该知识时点的未来重述/未来行被挡在训练之外。ISO 日期/时间字符串。
    # None=全知视图（默认·additive·向后兼容·逐字现状不变）。透传链：to_dict() → spec →
    # codegen `load_pit_panel`（DL/脚本路·子进程）；ML 进程内路经 `_pit_view` 走同一单一源折叠。
    as_of_known: str | None = None
    # 模型组合：用已训练模型的输出当输入特征。
    # 每项 {"artifact_path": "...", "feature_cols": [...], "as_col": "model_x_pred"}
    input_models: list[dict[str, Any]] = field(default_factory=list)
    # 动机/设计富文档（作业台 dashboard 动机卡）：why/data/window/label/design/arch/hparams
    # + sections(逐项设计细节) + io_spec(输入输出规格)。纯文档、不参与执行；持久化进 job 快照透传前端。
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrainingService:
    def __init__(
        self,
        root: Path,
        *,
        experiment_store: ExperimentStore | None = None,
        run_store: RunStore | None = None,
        model_registry: ModelRegistry | None = None,
        max_concurrency: int = 1,
        timeout: float | None = None,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._jobs = TrainingJobStore(self._root)
        m12_root = self._root.parent / "experiments"
        self._exp = experiment_store or ExperimentStore(m12_root)
        self._runs = run_store or RunStore(m12_root)
        self._models = model_registry or ModelRegistry(m12_root)
        # 有界线程池：真正限流并发（不再为每个提交预先 spawn 一个阻塞线程→内存/线程泄漏）。
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, max_concurrency), thread_name_prefix="train"
        )
        self._futures: list[Future] = []
        self._timeout = timeout

    # ---------------- 公开 API：结构化 spec ----------------

    def submit(self, request: TrainingRequest, panel: pd.DataFrame) -> TrainingJob:
        job = self._build_spec_job(request)
        self._jobs.create(job)
        self._spawn(job.job_id, panel, request=request)
        return job

    def train_now(self, request: TrainingRequest, panel: pd.DataFrame) -> TrainingJob:
        job = self._build_spec_job(request)
        self._jobs.create(job)
        self._execute(job.job_id, panel, request=request)
        return self._jobs.get(job.job_id)

    # ---------------- 公开 API：自由代码 ----------------

    def submit_code(
        self, name: str, code: str, panel: pd.DataFrame, *, asset_class: str = "a_share"
    ) -> TrainingJob:
        job = self._build_code_job(name, asset_class)
        self._jobs.create(job)
        self._spawn(job.job_id, panel, code=code, asset_class=asset_class)
        return job

    def train_now_code(
        self, name: str, code: str, panel: pd.DataFrame, *, asset_class: str = "a_share"
    ) -> TrainingJob:
        job = self._build_code_job(name, asset_class)
        self._jobs.create(job)
        self._execute(job.job_id, panel, code=code, asset_class=asset_class)
        return self._jobs.get(job.job_id)

    # ---------------- 查询 ----------------

    def get_job(self, job_id: str) -> TrainingJob:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[TrainingJob]:
        return self._jobs.list()

    def wait_all(self, timeout: float | None = None) -> None:
        for f in list(self._futures):
            try:
                f.result(timeout)
            except Exception:  # noqa: BLE001 — _execute 自己落 job.error，这里只等完成
                pass

    # ---------------- 内部：建 job ----------------

    def _build_spec_job(self, request: TrainingRequest) -> TrainingJob:
        card = get_model_card(request.model)  # 未知模型 → KeyError
        if request.task not in card.tasks:
            raise ValueError(
                f"模型 {request.model} 不支持任务 {request.task}（支持: {list(card.tasks)}）"
            )
        if not request.feature_cols:
            raise ValueError("feature_cols 不能为空")
        return TrainingJob(
            job_id=_gen_id(),
            name=request.name,
            model=request.model,
            family=card.family,
            task=request.task,
            request=request.to_dict(),
            tensorboard=card.tensorboard,
            detail=dict(request.detail or {}),
        )

    def _build_code_job(self, name: str, asset_class: str) -> TrainingJob:
        return TrainingJob(
            job_id=_gen_id(),
            name=name,
            model="(code)",
            family="code",
            task="(code)",
            request={"asset_class": asset_class},
        )

    def _spawn(self, job_id: str, panel: pd.DataFrame, **kw: Any) -> None:
        # 提交到有界线程池：超过 max_workers 的任务在池内排队（保持 status=queued），
        # 不会为每个提交各起一条阻塞线程。保留 future 句柄供 wait_all/cleanup。
        fut = self._pool.submit(self._execute, job_id, panel, **kw)
        self._futures = [f for f in self._futures if not f.done()]  # 顺手清理已完成
        self._futures.append(fut)

    # ---------------- 内部：执行 ----------------

    def _execute(
        self,
        job_id: str,
        panel: pd.DataFrame,
        *,
        request: TrainingRequest | None = None,
        code: str | None = None,
        asset_class: str = "a_share",
    ) -> None:
        # 并发由线程池 max_workers 限流；此处不再各自 acquire 信号量。
        if True:
            job = self._jobs.get(job_id)
            job.status = "running"
            job.started_at_utc = _now()
            self._jobs.save(job)
            t0 = time.perf_counter()
            run_id: str | None = None
            try:
                job_dir = self._jobs.job_dir(job_id)
                spec_dump = request.to_dict() if request else {"code": code}
                (job_dir / "spec.json").write_text(
                    json.dumps(spec_dump, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                exp = self._ensure_experiment(
                    (request.experiment_name if request else None) or "训练台",
                    request.asset_class if request else asset_class,
                )
                run = self._runs.create_run(
                    exp.experiment_id,
                    inputs=spec_dump,
                    tags={"kind": "training", "family": job.family},
                )
                run_id = run.run_id

                # 模型组合：注入已训练模型的输出列
                if request is not None and request.input_models:
                    panel, request = self._apply_input_models(request, panel)

                # 严格无泄露 OOS：只用前 train_fraction 比例的交易日训练
                # （与回测 oos_fraction=1-train_fraction 同一日期分位互补、零重叠）。
                if request is not None and request.train_fraction is not None:
                    panel = _slice_front_dates(panel, request.ts_col, request.train_fraction)

                result = self._resolve_result(request, code, panel, job_dir)

                (job_dir / "result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                metrics = {
                    k: float(v)
                    for k, v in (result.get("oos_metrics") or {}).items()
                    if isinstance(v, (int, float))
                }
                # 先把 run 标 succeeded，再登记 model version：避免出现"已注册版本
                # 指向一个非 succeeded run"的不一致；且仅在有 artifact 时登记，
                # 不为自由代码/无产物任务注册幽灵 (code) 版本。
                self._runs.update_run(
                    run_id,
                    status="succeeded",
                    metrics=metrics,
                    artifact_paths=[p for p in [result.get("artifact_path")] if p],
                    finished=True,
                )
                if result.get("artifact_path") and request is not None:
                    self._models.register_version(
                        model_id=request.model,
                        artifact_path=result.get("artifact_path"),
                        source_run_id=run_id,
                        metrics=metrics,
                        note=job.name,
                    )
                job.status = "succeeded"
                job.metrics = metrics
                job.experiment_id = exp.experiment_id
                job.run_id = run_id
                job.artifact_dir = str(job_dir)
            except Exception as exc:  # noqa: BLE001 — 失败要落 job.error，不冒泡崩线程
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                if run_id:
                    try:
                        self._runs.update_run(run_id, status="failed", finished=True)
                    except Exception:
                        pass
            finally:
                job.finished_at_utc = _now()
                job.elapsed_seconds = round(time.perf_counter() - t0, 4)
                self._jobs.save(job)

    def _resolve_result(
        self,
        request: TrainingRequest | None,
        code: str | None,
        panel: pd.DataFrame,
        job_dir: Path,
    ) -> dict[str, Any]:
        """统一返回 TrainResult.to_dict 同形的 dict。"""
        if code is not None:
            return self._run_code(code, panel, job_dir)
        assert request is not None
        card = get_model_card(request.model)
        if card.family == "dl":
            return self._run_code(spec_to_code(request.to_dict()), panel, job_dir)
        # ML：进程内直接训练（不需 torch，省一次 subprocess 开销）
        return self._train_ml(request, panel, job_dir)

    def _pit_view(self, request: TrainingRequest, panel: pd.DataFrame) -> pd.DataFrame:
        """ML 进程内路的 R28 双时态 PIT 点查（堵 look-ahead）。

        DL/脚本路在子进程里经生成脚本的 ``load_pit_panel`` 折叠（``to_dict`` 透传 ``as_of_known``
        → ``spec_to_code``）；ML 进程内路不渲染脚本、直接 ``train_model``，故此处把同一份 panel 经
        **同一单一源** ``codegen.load_pit_panel`` 折叠后再训练——两路 as-of 语义对齐、不另造平行
        PIT 逻辑（复用 ``resolver.as_of_bound`` + 镜像 ``catalog._materialize_sub`` 折叠，单一源）。

        - ``as_of_known=None`` → **逐字原 panel**：向后兼容·additive·绝不改既有 ML 训练（无 round-trip）。
        - ``as_of_known`` 给定 → 经 ``load_pit_panel`` 按 ``known_at<=as_of_known`` 折叠点查：
          晚于该知识时点的未来重述 / 未来行必被挡在训练之外（重述 as-of）。
        - 无 ``known_at`` 列 → ``load_pit_panel`` 内部 mirror ``_materialize_sub`` 原样返回
          （无知识轴可过滤·不假装过滤·不报错）。

        诚实边界：``load_pit_panel`` 是 path-based 单一源（消费 parquet）；进程内路 panel 是内存
        DataFrame → 落一份**临时** parquet 当传输、走同一源折叠后即清理（不在 job_dir 留未过滤快照、
        与 ML 进程内路本就不持久化训练面板一致），绝不在 service 层另造折叠逻辑。
        """
        if request.as_of_known is None:
            return panel  # 逐字现状·向后兼容（既有 ML 训练一字不变，无 round-trip 开销）
        import tempfile

        with tempfile.TemporaryDirectory(prefix="quantbt_pit_") as td:
            pit_path = Path(td) / "panel.parquet"
            panel.to_parquet(pit_path)
            return load_pit_panel(  # load_pit_panel 全量读进内存后返回，临时目录可随即清理
                str(pit_path),
                as_of_known=request.as_of_known,
                ts_col=request.ts_col,
                symbol_col=request.symbol_col,
            )

    def _train_ml(
        self, request: TrainingRequest, panel: pd.DataFrame, job_dir: Path
    ) -> dict[str, Any]:
        # R28 双时态 PIT：进程内路同样无前视（panel 经单一源 load_pit_panel 折叠点查）。
        panel = self._pit_view(request, panel)
        spec = ModelSpec(
            task=request.task,  # type: ignore[arg-type]
            model=request.model,  # type: ignore[arg-type]
            feature_cols=request.feature_cols,
            label_col=request.label_col,
            cv_scheme=request.cv_scheme,  # type: ignore[arg-type]
            n_splits=request.n_splits,
            embargo_pct=request.embargo_pct,
            walk_forward_train=request.walk_forward_train,
            walk_forward_test=request.walk_forward_test,
            walk_forward_embargo=request.walk_forward_embargo,
            hyperparams=request.hyperparams,
            group_col=request.group_col,
        )
        return train_model(spec, panel, artifact_dir=job_dir).to_dict()

    def _run_code(self, code: str, panel: pd.DataFrame, job_dir: Path) -> dict[str, Any]:
        panel_path = job_dir / "panel.parquet"
        panel.to_parquet(panel_path)
        res = run_code(
            code,
            job_dir,
            env_extra={"QUANTBT_PANEL_PATH": str(panel_path)},
            timeout=self._timeout,
        )
        if not res.ok:
            tail = (res.stderr or "").strip()[-1200:]
            raise RuntimeError(
                f"训练脚本失败(rc={res.returncode})：{tail or '无 emit 输出'}"
            )
        return res.emit  # type: ignore[return-value]

    def _apply_input_models(
        self, request: TrainingRequest, panel: pd.DataFrame
    ) -> tuple[pd.DataFrame, TrainingRequest]:
        panel = panel.copy()
        feats = list(request.feature_cols)
        for im in request.input_models:
            col = im["as_col"]
            panel[col] = predict_with(im["artifact_path"], panel, list(im["feature_cols"]))
            if col not in feats:
                feats.append(col)
        return panel, replace(request, feature_cols=feats)

    def _ensure_experiment(self, name: str, asset_class: str):
        for e in self._exp.list_experiments():
            if e.name == name and e.asset_class == asset_class:
                return e
        return self._exp.create_experiment(
            name=name, asset_class=asset_class, description="训练台自动创建"
        )


__all__ = ["TrainingRequest", "TrainingService"]
