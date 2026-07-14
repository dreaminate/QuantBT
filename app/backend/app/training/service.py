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
import hashlib
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ..experiments.store import ExperimentStore, ModelRegistry, RunStore
from ..models.catalog import get_model_card
from ..models.training import ModelSpec, train_model
from ..research_os import (
    ModelArtifactInspectionRecord,
    ModelArtifactManifestEntry,
    ModelArtifactSource,
    ModelGovernancePassport,
    ModelRiskTier,
    RecertificationTrigger,
    SafeLoadingPolicy,
)
from ..research_os.model_governance_closure import model_training_code_hash
from . import artifact_trust
from .artifact_inspection import inspect_artifact_in_subprocess
from .codegen import load_pit_panel, spec_to_code
from .lib import predict_with
from .runner import run_code
from .schema_drift import (
    DataSchemaRecertificationRequired,
    compute_dataset_schema,
    describe_name_diff,
    schema_change_event_ref,
)
from .store import TrainingJob, TrainingJobStore, _gen_id

# C-MODELGOV-1·③ 生产激活:组合已训练模型(input_models)消费侧的【信任门 enforce 默认开关】。
# 默认 ON = artifact 信任门生产激活(producer 已全接 register·①):组合时只放行【系统自产·已登记】
# 模型,外来/未登记 artifact 在 load 处被拒(§15)。**单点可逆**:中心整合点跑全量后若发现未登记
# producer 路径破基线 → 构造 TrainingService(trust_enforce=False) 回退 opt-in(无需改门/改 producer)。
# 🟡 enforce-默认-翻开【待中心全量验证】:本卡只跑 scoped、只验组合消费路径,绝不声称全量绿。
_TRUST_ENFORCE_DEFAULT = True
_TRAINING_SERVICE_ACTOR = "training_service"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stable_json_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"训练产物不存在，不能登记 ModelPassport: {path}")
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _next_model_version(
    registry: ModelRegistry,
    model_id: str,
    *,
    owner_user_id: str,
) -> int:
    versions = [
        version.version
        for version in registry.list_versions(
            model_id,
            owner_user_id=owner_user_id,
        )
    ]
    return (max(versions) + 1) if versions else 1


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
    dataset_id: str | None = None
    market_data_use_validation_refs: list[str] = field(default_factory=list)
    experiment_name: str | None = None
    # R28 双时态 PIT 点查（堵 look-ahead）：训练只见「截至 as_of_known 已知」的行（重述 as-of），
    # 晚于该知识时点的未来重述/未来行被挡在训练之外。ISO 日期/时间字符串。
    # None=全知视图（默认·additive·向后兼容·逐字现状不变）。透传链：to_dict() → spec →
    # codegen `load_pit_panel`（DL/脚本路·子进程）；ML 进程内路经 `_pit_view` 走同一单一源折叠。
    as_of_known: str | None = None
    # GOAL §11: confirmatory_validation is a fail-closed PIT consumer.  Other
    # contexts remain explicitly exploratory/backtest compatible.
    use_context: str = "research"
    # 模型组合：用已训练模型的输出当输入特征。
    # 每项 {"artifact_path": "...", "feature_cols": [...], "as_col": "model_x_pred"}
    input_models: list[dict[str, Any]] = field(default_factory=list)
    # 动机/设计富文档（作业台 dashboard 动机卡）：why/data/window/label/design/arch/hparams
    # + sections(逐项设计细节) + io_spec(输入输出规格)。纯文档、不参与执行；持久化进 job 快照透传前端。
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# A DATA_SCHEMA_CHANGE recertification clears the obligation only when a human review
# accepted it or explicitly waived it (the user-waived methodology path). "rejected"
# (or any other value) leaves the obligation open → training stays blocked.
_ACCEPTED_RECERT_DECISIONS = frozenset({"accepted", "waived"})


@dataclass(frozen=True)
class _SchemaRecertPlan:
    """Outcome of the pre-run §15 DATA_SCHEMA_CHANGE gate, threaded into passport
    recording. ``change_events`` is non-empty only when this run's dataset schema
    changed *and* a recertification cleared it; ``recertification_record_refs`` then
    binds the clearing record(s) onto the passport so ``record_passport`` accepts the
    change event (defense-in-depth with the pre-run gate)."""

    schema_fingerprint: str
    change_events: tuple[RecertificationTrigger, ...]
    recertification_record_refs: tuple[str, ...]


class TrainingService:
    def __init__(
        self,
        root: Path,
        *,
        experiment_store: ExperimentStore | None = None,
        run_store: RunStore | None = None,
        model_registry: ModelRegistry | None = None,
        model_governance_registry: Any | None = None,
        model_recertification_event_registry: Any | None = None,
        result_recorder: Callable[[TrainingJob], dict[str, Any]] | None = None,
        max_concurrency: int = 1,
        timeout: float | None = None,
        trust_enforce: bool = _TRUST_ENFORCE_DEFAULT,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._jobs = TrainingJobStore(self._root)
        # C-MODELGOV-1·③:组合消费侧 artifact 信任门 enforce 开关(默认 ON·见 _TRUST_ENFORCE_DEFAULT)。
        # 信任账落点 store_under(self._root) 与 producer 的 store_under(artifact_dir.parent) 同源。
        self._trust_enforce = trust_enforce
        m12_root = self._root.parent / "experiments"
        self._exp = experiment_store or ExperimentStore(m12_root)
        self._runs = run_store or RunStore(m12_root)
        self._models = model_registry or ModelRegistry(
            m12_root,
            model_governance_registry=model_governance_registry,
        )
        attached_model_governance = getattr(
            self._models,
            "_model_governance_registry",
            None,
        )
        if (
            model_governance_registry is not None
            and attached_model_governance is not model_governance_registry
        ):
            raise ValueError(
                "TrainingService model_registry and model_governance_registry must share identity"
            )
        self._model_governance = model_governance_registry or getattr(
            self._models,
            "_model_governance_registry",
            None,
        )
        self._model_recertification_events = None
        if self._model_governance is not None:
            from ..research_os.model_recertification_events import (
                PersistentModelRecertificationEventRegistry,
            )

            attached_events = getattr(
                self._models,
                "model_recertification_event_registry",
                None,
            )
            event_registry = (
                model_recertification_event_registry
                or attached_events
                or PersistentModelRecertificationEventRegistry(
                    self._root.parent
                    / "audit"
                    / "model_recertification_events.jsonl"
                )
            )
            bind_events = getattr(
                self._models,
                "bind_model_recertification_events",
                None,
            )
            if not callable(bind_events):
                raise ValueError(
                    "TrainingService model registry lacks recertification event binding"
                )
            bind_events(event_registry, self._jobs)
            self._model_recertification_events = event_registry
        self._result_recorder = result_recorder
        # 有界线程池：真正限流并发（不再为每个提交预先 spawn 一个阻塞线程→内存/线程泄漏）。
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, max_concurrency), thread_name_prefix="train"
        )
        self._futures: list[Future] = []
        self._timeout = timeout

    # ---------------- 公开 API：结构化 spec ----------------

    def submit(
        self,
        request: TrainingRequest,
        panel: pd.DataFrame,
        *,
        owner_user_id: str | None = None,
    ) -> TrainingJob:
        owner = self._execution_owner(owner_user_id)
        job = self._build_spec_job(request)
        job.owner_user_id = owner
        self._jobs.create(job)
        self._spawn(job.job_id, panel, request=request, owner_user_id=owner)
        return job

    def train_now(
        self,
        request: TrainingRequest,
        panel: pd.DataFrame,
        *,
        owner_user_id: str | None = None,
    ) -> TrainingJob:
        owner = self._execution_owner(owner_user_id)
        job = self._build_spec_job(request)
        job.owner_user_id = owner
        self._jobs.create(job)
        self._execute(job.job_id, panel, request=request, owner_user_id=owner)
        return self._jobs.get(job.job_id)

    # ---------------- 公开 API：自由代码 ----------------

    def submit_code(
        self,
        name: str,
        code: str,
        panel: pd.DataFrame,
        *,
        asset_class: str = "a_share",
        owner_user_id: str | None = None,
    ) -> TrainingJob:
        owner = self._execution_owner(owner_user_id)
        job = self._build_code_job(name, asset_class)
        job.owner_user_id = owner
        self._jobs.create(job)
        self._spawn(
            job.job_id,
            panel,
            code=code,
            asset_class=asset_class,
            owner_user_id=owner,
        )
        return job

    def train_now_code(
        self,
        name: str,
        code: str,
        panel: pd.DataFrame,
        *,
        asset_class: str = "a_share",
        owner_user_id: str | None = None,
    ) -> TrainingJob:
        owner = self._execution_owner(owner_user_id)
        job = self._build_code_job(name, asset_class)
        job.owner_user_id = owner
        self._jobs.create(job)
        self._execute(
            job.job_id,
            panel,
            code=code,
            asset_class=asset_class,
            owner_user_id=owner,
        )
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

    def _execution_owner(self, owner_user_id: str | None) -> str:
        """Normalize the authenticated owner at the public service boundary.

        Every successful structured training run writes a ModelVersion even when a
        model-governance registry is not configured. The caller must therefore
        provide the stable authenticated owner explicitly for every public training
        seam; deriving an owner from existing rows would turn ambient single-owner
        state into an authorization decision and fail open when another owner exists.
        """

        owner = str(owner_user_id or "").strip()
        if not owner:
            raise ValueError("owner_user_id is required for training model identity")
        return owner

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
        owner_user_id: str,
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

                # C-S15 producer · DATA_SCHEMA_CHANGE pre-run 重认证门（fail-closed，_train_ml/_run_code 前）：
                # 训练台是 §15「data schema change」触发器的 producer。本 run 训练数据集（模型实际消费的
                # feature/label 列 + dtype）的 schema 指纹，与「同模型」上一份已登记 passport 的指纹不一致时，
                # 必须先有一条 accepted/waived 的 DATA_SCHEMA_CHANGE 重认证记录清账，否则在任何训练开跑前
                # 抛 DataSchemaRecertificationRequired 阻断——绝不放「未重认证的 schema 变更」进训练。
                # panel 已过 input_models 注入 + train_fraction 切片，指纹反映真实送训 schema。
                # 返回的 plan 在训练后登记 passport 时透传（绑定指纹 + change_events + 清账记录引用）。
                recert_plan = (
                    self._evaluate_data_schema_recertification(
                        request,
                        panel,
                        owner_user_id=owner_user_id,
                    )
                    if request is not None
                    else None
                )

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
                    version_record = self._register_model_version(
                        request=request,
                        job=job,
                        job_dir=job_dir,
                        result=result,
                        metrics=metrics,
                        run_id=run_id,
                        spec_dump=spec_dump,
                        recert_plan=recert_plan,
                        owner_user_id=owner_user_id,
                    )
                    job.model_version = version_record.version
                    job.model_passport_ref = version_record.model_passport_ref
                    job.validation_dossier_ref = version_record.validation_dossier_ref
                job.status = "succeeded"
                job.metrics = metrics
                job.experiment_id = exp.experiment_id
                job.run_id = run_id
                job.artifact_dir = str(job_dir)
                if self._result_recorder is not None and job.model_version is not None:
                    graph_refs = self._result_recorder(job)
                    job.qro_id = str(graph_refs.get("qro_id") or "") or None
                    job.research_graph_command_id = (
                        str(graph_refs.get("research_graph_command_id") or "") or None
                    )
                    job.compiler_ir_ref = str(graph_refs.get("compiler_ir_ref") or "") or None
                    job.compiler_pass_ref = str(graph_refs.get("compiler_pass_ref") or "") or None
                    job.entrypoint_coverage_ref = str(graph_refs.get("entrypoint_coverage_ref") or "") or None
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

        - 非 confirmatory 且 ``as_of_known=None`` → **逐字原 panel**：向后兼容·additive。
        - ``use_context=confirmatory_validation`` → 缺 ``as_of_known`` 或 ``known_at`` 轴均 fail-closed。
        - ``as_of_known`` 给定 → 经 ``load_pit_panel`` 按 ``known_at<=as_of_known`` 折叠点查：
          晚于该知识时点的未来重述 / 未来行必被挡在训练之外（重述 as-of）。
        - 无 ``known_at`` 列 → ``load_pit_panel`` 内部 mirror ``_materialize_sub`` 原样返回
          （无知识轴可过滤·不假装过滤·不报错）。

        诚实边界：``load_pit_panel`` 是 path-based 单一源（消费 parquet）；进程内路 panel 是内存
        DataFrame → 落一份**临时** parquet 当传输、走同一源折叠后即清理（不在 job_dir 留未过滤快照、
        与 ML 进程内路本就不持久化训练面板一致），绝不在 service 层另造折叠逻辑。
        """
        confirmatory = request.use_context == "confirmatory_validation"
        if request.as_of_known is None and not confirmatory:
            return panel  # 逐字现状·向后兼容（既有 ML 训练一字不变，无 round-trip 开销）
        import tempfile

        with tempfile.TemporaryDirectory(prefix="quantbt_pit_") as td:
            pit_path = Path(td) / "panel.parquet"
            panel.to_parquet(pit_path)
            return load_pit_panel(  # load_pit_panel 全量读进内存后返回，临时目录可随即清理
                str(pit_path),
                as_of_known=request.as_of_known,
                confirmatory=confirmatory,
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

    def _register_model_version(
        self,
        *,
        request: TrainingRequest,
        job: TrainingJob,
        job_dir: Path,
        result: dict[str, Any],
        metrics: dict[str, float],
        run_id: str,
        spec_dump: dict[str, Any],
        recert_plan: _SchemaRecertPlan | None = None,
        owner_user_id: str,
    ):
        artifact_path = Path(str(result["artifact_path"]))
        artifact_hash = _sha256_file(artifact_path)
        inspection = inspect_artifact_in_subprocess(artifact_path, expected_hash=artifact_hash)
        (job_dir / "artifact_inspection.json").write_text(
            json.dumps(inspection, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        next_version = _next_model_version(
            self._models,
            request.model,
            owner_user_id=owner_user_id,
        )
        model_version_ref = f"model_version:{request.model}:v{next_version}"
        validation_dossier_ref = f"validation_dossier:{job.job_id}"
        training_run_ref = f"training_run:{run_id}"
        dataset_ref = request.dataset_id or f"training_panel:{job.job_id}"
        market_data_use_validation_refs = tuple(
            str(ref).strip()
            for ref in request.market_data_use_validation_refs
            if str(ref).strip()
        )
        dossier = {
            "validation_dossier_ref": validation_dossier_ref,
            "model_version_ref": model_version_ref,
            "training_run_ref": training_run_ref,
            "dataset_refs": [dataset_ref],
            "market_data_use_validation_refs": list(market_data_use_validation_refs),
            "feature_refs": list(request.feature_cols),
            "label_refs": [request.label_col],
            "cv_scheme": request.cv_scheme,
            "n_splits": request.n_splits,
            "metrics": metrics,
            "artifact_path": str(artifact_path),
            "artifact_hash": artifact_hash,
            "artifact_inspection_ref": inspection["inspection_ref"],
            "artifact_inspection_mode": inspection["inspection_mode"],
            "result_oos_metrics": result.get("oos_metrics") or {},
            "fold_count": len(result.get("fold_metrics") or []),
        }
        (job_dir / "validation_dossier.json").write_text(
            json.dumps(dossier, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        passport_ref: str | None = None
        if self._model_governance is not None:
            # C-S15 producer: bind this run's dataset-schema fingerprint into the
            # passport, and — when the pre-run gate detected a cleared schema change —
            # emit the DATA_SCHEMA_CHANGE change event + the clearing recert record(s)
            # so record_passport's §15 recertification gate accepts it (and rejects it
            # if somehow unresolved: defense-in-depth behind the pre-run gate).
            schema_fingerprint = recert_plan.schema_fingerprint if recert_plan is not None else ""
            change_events = recert_plan.change_events if recert_plan is not None else ()
            recertification_records = (
                recert_plan.recertification_record_refs if recert_plan is not None else ()
            )
            passport = ModelGovernancePassport(
                model_version_ref=model_version_ref,
                model_type_card_ref=f"model_type_card:{request.model}",
                training_plan_ref=f"training_plan:{job.job_id}",
                training_run_ref=training_run_ref,
                model_risk_tier=ModelRiskTier.MEDIUM,
                materiality=f"{request.asset_class} {request.task} training artifact",
                intended_use=(f"{request.task} research model review",),
                prohibited_use=("direct live order placement",),
                dataset_refs=(dataset_ref,),
                feature_refs=tuple(request.feature_cols),
                label_refs=(request.label_col,),
                training_code_hash=model_training_code_hash(spec_dump),
                artifact_manifest=(
                    ModelArtifactManifestEntry(
                        artifact_ref=f"model_artifact:{job.job_id}",
                        uri=str(artifact_path),
                        source=ModelArtifactSource.PROJECT_PRODUCED,
                        content_hash=artifact_hash,
                        producer_run_ref=training_run_ref,
                        sandbox_inspection_ref=inspection["inspection_ref"],
                    ),
                ),
                safe_loading_policy=SafeLoadingPolicy(
                    sandboxed_load_inspect=True,
                    prefer_safe_tensors=True,
                    torch_weights_only=True,
                    direct_load_allowed=False,
                    policy_ref="training_produced_local_artifact_hash_inspection_v1",
                ),
                vendor_dependency_refs=("none",),
                foundation_model_dependency_refs=("none",),
                monitoring_requirements=("performance degradation monitor",),
                recertification_triggers=tuple(RecertificationTrigger),
                recertification_records=recertification_records,
                dataset_schema_fingerprint=schema_fingerprint,
                validation_dossier_ref=validation_dossier_ref,
                challenger_result="not required for medium risk training artifact",
                owner_user_id=owner_user_id,
                recorded_by=_TRAINING_SERVICE_ACTOR,
            )
            recorded_passport = self._model_governance.record_passport(
                passport,
                change_events=change_events,
                owner_user_id=owner_user_id,
                recorded_by=_TRAINING_SERVICE_ACTOR,
            )
            passport_ref = recorded_passport.passport_id
            self._model_governance.record_artifact_inspection(
                ModelArtifactInspectionRecord(
                    model_version_ref=model_version_ref,
                    model_passport_ref=recorded_passport.passport_id,
                    artifact_ref=f"model_artifact:{job.job_id}",
                    inspection_ref=inspection["inspection_ref"],
                    artifact_hash=artifact_hash,
                    inspection_status="accepted",
                    inspection_mode=str(inspection.get("inspection_mode") or ""),
                    inspector_ref=str(inspection.get("inspector_ref") or ""),
                    checks=tuple(str(value) for value in inspection.get("checks") or ()),
                    limitations=tuple(str(value) for value in inspection.get("limitations") or ()),
                    recorded_by=_TRAINING_SERVICE_ACTOR,
                    owner_user_id=owner_user_id,
                ),
                owner_user_id=owner_user_id,
                recorded_by=_TRAINING_SERVICE_ACTOR,
            )
        return self._models.register_version(
            model_id=request.model,
            artifact_path=str(artifact_path),
            source_run_id=run_id,
            metrics=metrics,
            model_passport_ref=passport_ref,
            validation_dossier_ref=validation_dossier_ref,
            note=job.name,
            owner_user_id=owner_user_id,
        )

    # ---------------- C-S15 producer：DATA_SCHEMA_CHANGE 重认证门 ----------------

    def _evaluate_data_schema_recertification(
        self,
        request: TrainingRequest,
        panel: pd.DataFrame,
        *,
        owner_user_id: str,
    ) -> _SchemaRecertPlan:
        """Pre-run §15 DATA_SCHEMA_CHANGE gate (producer side).

        Fingerprints this run's training-dataset schema (model-consumed feature +
        label columns + dtypes) and compares it against the most recent recorded
        passport for the *same* model (keyed by ``model_type_card_ref``). When the
        schema changed and no accepted/waived DATA_SCHEMA_CHANGE recertification
        clears the exact transition, raises ``DataSchemaRecertificationRequired``
        (fail-closed) *before any training runs*. Otherwise returns the fingerprint
        plus the change event + clearing record refs to bind into the passport
        recorded after training.

        Reuse, not re-judge: whether a change event is satisfied (declared trigger +
        recertification record) stays owned by ``model_governance``; this only
        *detects* the change and *requires* the governed record.
        """
        governance = self._model_governance
        if governance is None:
            # No governance registry → no passport recorded, no obligation to track.
            return _SchemaRecertPlan("", (), ())

        now_schema = compute_dataset_schema(panel, request.feature_cols, request.label_col)
        now_fp = now_schema.fingerprint

        model_card_ref = f"model_type_card:{request.model}"
        # Baseline = the latest passport for this model that actually CARRIES a schema
        # fingerprint. Skipping fingerprint-less passports closes a fail-open: a
        # passport recorded without a fingerprint (e.g. via the manual REST passport
        # API) must not be able to erase the producer-recorded baseline and let a
        # changed schema train unchecked. A model with no fingerprinted passport yet
        # has no prior schema to police → its baseline is set by this run (no
        # obligation on a baseline that does not exist).
        prior = self._schema_baseline_passport(
            model_card_ref,
            owner_user_id=owner_user_id,
        )
        prev_fp = str(getattr(prior, "dataset_schema_fingerprint", "") or "") if prior is not None else ""
        if not prev_fp or prev_fp == now_fp:
            # No fingerprinted baseline for this model, or schema unchanged →放行（无义务）。
            return _SchemaRecertPlan(now_fp, (), ())

        change_event_ref = schema_change_event_ref(model_card_ref, prev_fp, now_fp)
        resolving = self._resolving_schema_recertifications(
            model_card_ref,
            change_event_ref,
            owner_user_id=owner_user_id,
        )
        if not resolving:
            diff = describe_name_diff(
                prior.feature_refs,
                prior.label_refs,
                request.feature_cols,
                (request.label_col,),
            )
            raise DataSchemaRecertificationRequired(
                model_ref=model_card_ref,
                change_event_ref=change_event_ref,
                prev_fingerprint=prev_fp,
                new_fingerprint=now_fp,
                diff=diff,
            )
        return _SchemaRecertPlan(
            now_fp,
            (RecertificationTrigger.DATA_SCHEMA_CHANGE,),
            tuple(record.recertification_record_id for record in resolving),
        )

    def _schema_baseline_passport(
        self,
        model_card_ref: str,
        *,
        owner_user_id: str,
    ) -> Any | None:
        """Latest passport for a model that carries a non-empty schema fingerprint
        (``passports()`` keeps insertion order, so the last match is the most recent),
        or None when no fingerprinted passport exists yet. A fingerprint-less passport
        is skipped so it cannot reset the producer baseline (fail-closed)."""
        baseline = None
        for passport in self._model_governance.passports(
            owner_user_id=owner_user_id
        ):
            if getattr(passport, "model_type_card_ref", None) != model_card_ref:
                continue
            if not str(getattr(passport, "dataset_schema_fingerprint", "") or ""):
                continue
            baseline = passport
        return baseline

    def _resolving_schema_recertifications(
        self,
        model_card_ref: str,
        change_event_ref: str,
        *,
        owner_user_id: str,
    ) -> list[Any]:
        """Accepted/waived DATA_SCHEMA_CHANGE recert records that clear exactly this
        transition. Three independent bindings must all hold so an unrelated or
        cross-model record cannot satisfy the gate:
          (1) trigger is DATA_SCHEMA_CHANGE,
          (2) change_event_ref matches (model identity + both fingerprints are hashed
              into it), and the model-card binding below re-checks model identity,
          (3) decision is accepted or waived,
          (4) the record is filed against a passport of THIS model card.
        """
        governance = self._model_governance
        resolving: list[Any] = []
        for record in governance.recertification_records(
            owner_user_id=owner_user_id
        ):
            trigger = str(getattr(record.trigger, "value", record.trigger))
            if trigger != RecertificationTrigger.DATA_SCHEMA_CHANGE.value:
                continue
            if getattr(record, "change_event_ref", "") != change_event_ref:
                continue
            if getattr(record, "decision", "") not in _ACCEPTED_RECERT_DECISIONS:
                continue
            try:
                bound = governance.passport(
                    record.model_passport_ref,
                    owner_user_id=owner_user_id,
                )
            except KeyError:
                continue
            if getattr(bound, "model_type_card_ref", None) != model_card_ref:
                continue
            resolving.append(record)
        return resolving

    def _run_code(self, code: str, panel: pd.DataFrame, job_dir: Path) -> dict[str, Any]:
        panel_path = job_dir / "panel.parquet"
        panel.to_parquet(panel_path)
        # C-MODELGOV-1·残余① 兑现：把信任根 + enforce 继承透传给子进程（runner trust-bootstrap 钩子），
        # 使【自由代码 / DL】子进程内用户代码自调 predict_with / load_model（trust 默认）也过信任门——
        # 子进程 store_under(QUANTBT_TRUST_ROOT) 与主进程消费侧 store_under(self._root) 解析到【同一】
        # on-disk JSONL（跨进程共享·producer 登记的系统自产 artifact 子进程可见、外来未登记被拒·§15）。
        # enforce 继承自 self._trust_enforce（W1 单点可逆开关）：默认 ON；trust_enforce=False → 子进程同步回退。
        res = run_code(
            code,
            job_dir,
            env_extra={
                "QUANTBT_PANEL_PATH": str(panel_path),
                "QUANTBT_TRUST_ROOT": str(self._root),
                "QUANTBT_TRUST_ENFORCE": "1" if self._trust_enforce else "0",
            },
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
        # 信任门 enforce(C-MODELGOV-1·③):组合已训练模型时,消费侧用本 service 的信任账核验来源——
        # 系统自产(producer 已登记·①)→ 放行；外来/未登记 artifact → 在 predict_with 的 load 处 raise(§15)。
        # store_under(self._root) 与 producer 的 store_under(artifact_dir.parent) 解析到同一 on-disk 账。
        # enforce 默认 ON(可经构造参数 trust_enforce=False 回退 opt-in·🟡 默认翻开待中心全量验证)。
        trust = artifact_trust.TrustPolicy(
            store=artifact_trust.store_under(self._root),
            enforce=self._trust_enforce,
        )
        for im in request.input_models:
            col = im["as_col"]
            panel[col] = predict_with(
                im["artifact_path"], panel, list(im["feature_cols"]), trust=trust
            )
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
