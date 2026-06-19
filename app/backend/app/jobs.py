from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .data_pull import execute_binance_full_pull, execute_data_pull
from .schemas import BinanceFullPullRequest, DataPullRequest, JobProgress, JobRecord

if TYPE_CHECKING:
    from .dag.engine import DAGTask


def utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class InMemoryJobStore:
    def __init__(self, *, kernel_root: Path | str | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}
        self._cond = threading.Condition(self._lock)
        # 每个 job 的 progress 版本号，watcher 用来判定"有没有新事件"
        self._revisions: dict[str, int] = {}
        # 脊柱内核 01 接线（T-023，扩展不替换）：传 kernel_root 才启用 kernel_dag job；
        # 既有数据拉取 job 不受影响（kernel_root=None 时这些字段全空，行为零改动）。
        # ArtifactStore + EffectLedger 全 store 共享一份 → retry 时 pure 工件复用、
        # effectful 经 is_consumed 去重，即「从最近 checkpoint 恢复 + 绝不重发单」（M17 雷）。
        self._kernel_root = Path(kernel_root) if kernel_root is not None else None
        self._artifact_store: Any | None = None
        self._effect_ledger: Any | None = None
        # kernel job 的 tasks/context 留存（in-memory，供 retry 用同一图重跑→内容寻址命中已落工件）。
        self._kernel_specs: dict[str, dict[str, Any]] = {}
        if self._kernel_root is not None:
            from .dag.artifact_store import ArtifactStore
            from .dag.effect_ledger import EffectLedger

            self._artifact_store = ArtifactStore(self._kernel_root)
            self._effect_ledger = EffectLedger(self._kernel_root)

    def _bump(self, job_id: str) -> None:
        """在持有 self._lock 的前提下调用：进度/状态变更通知所有 watcher。"""
        self._revisions[job_id] = self._revisions.get(job_id, 0) + 1
        self._cond.notify_all()

    def stream_job(self, job_id: str, *, last_revision: int = 0, timeout_s: float = 60.0):
        """generator：每次 progress/状态变更 yield 一份 job snapshot dict；适合 SSE。

        终态 (succeeded / failed / interrupted) 会 yield 一次后退出。
        若 `timeout_s` 内无任何变化则 yield 一次 heartbeat。
        """

        import time as _time

        # 终态集合加 halted（脊柱内核：effectful 边界被截断的 kernel_dag job 收于 halted，待对账）。
        _terminal = {"succeeded", "failed", "interrupted", "halted"}

        # 先吐一份当前快照
        with self._cond:
            if job_id not in self._jobs:
                yield {"event": "error", "data": {"detail": f"job {job_id} not found"}}
                return
            current_rev = self._revisions.get(job_id, 0)
            snapshot = self._jobs[job_id].to_dict()
            yield {"event": "snapshot", "data": snapshot, "revision": current_rev}
            done = snapshot["status"] in _terminal
        last_checkpoint = snapshot.get("checkpoint")
        if done:
            yield {"event": "done", "data": {"final_status": snapshot["status"]}}
            return

        deadline_total = _time.time() + 3600  # 单连接最多 1 小时
        while _time.time() < deadline_total:
            with self._cond:
                # 等到 revision 改变或超时
                end = _time.time() + timeout_s
                while self._revisions.get(job_id, 0) <= last_revision:
                    remaining = end - _time.time()
                    if remaining <= 0:
                        break
                    self._cond.wait(timeout=remaining)
                if job_id not in self._jobs:
                    yield {"event": "error", "data": {"detail": "job removed"}}
                    return
                new_rev = self._revisions.get(job_id, 0)
                snapshot = self._jobs[job_id].to_dict()
            if new_rev > last_revision:
                last_revision = new_rev
                # checkpoint 推进时先发一条 checkpoint 事件（新增；不改 snapshot/progress/done/heartbeat 语义）。
                new_checkpoint = snapshot.get("checkpoint")
                if new_checkpoint is not None and new_checkpoint != last_checkpoint:
                    last_checkpoint = new_checkpoint
                    yield {"event": "checkpoint", "data": {"checkpoint": new_checkpoint}, "revision": new_rev}
                yield {"event": "progress", "data": snapshot, "revision": new_rev}
                if snapshot["status"] in _terminal:
                    yield {"event": "done", "data": {"final_status": snapshot["status"]}}
                    return
            else:
                # 心跳，给前端知道连接还活着
                yield {"event": "heartbeat", "data": {"status": snapshot["status"]}}

    def _get(self, job_id: str) -> JobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def create_data_pull_job(self, payload: DataPullRequest) -> JobRecord:
        job_id = uuid.uuid4().hex
        job = JobRecord(
            job_id=job_id,
            job_type="data_sync_pull",
            status="queued",
            payload=payload.model_dump(mode="json"),
            submitted_at=utc_now(),
            progress=JobProgress(percent=0, stage="queued", stage_label="等待执行", message="等待执行"),
            payload_summary=_build_payload_summary(payload),
        )
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(target=self._run_data_pull_job, args=(job_id, payload), daemon=True)
        thread.start()
        return job

    def create_binance_full_pull_job(self, request: BinanceFullPullRequest | None = None) -> JobRecord:
        req = request or BinanceFullPullRequest()
        payload_dict = req.model_dump(mode="json")
        job_id = uuid.uuid4().hex
        job = JobRecord(
            job_id=job_id,
            job_type="binance_full_pull",
            status="queued",
            payload=payload_dict,
            submitted_at=utc_now(),
            progress=JobProgress(percent=0, stage="queued", stage_label="等待执行", message="等待执行"),
            payload_summary=_build_binance_full_summary(payload_dict),
        )
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(target=self._run_binance_full_pull_job, args=(job_id, req), daemon=True)
        thread.start()
        return job

    # ── 脊柱内核 01 接线（T-023）：kernel_dag job ───────────────────────────
    def create_kernel_job(
        self,
        tasks: list["DAGTask"],
        *,
        context: dict[str, Any] | None = None,
        mode: str = "run",
        job_type: str = "kernel_dag",
        _resume_of: str | None = None,
    ) -> JobRecord:
        """跑一张确定性内核 DAG 作为 job。

        mode="run"（默认）：正向执行；retry 时用同一图重跑（见 retry_job）→ 内容寻址命中已落
        durable 工件、effectful 经 EffectLedger.is_consumed 去重，即「从最近 checkpoint 恢复、绝不重发单」。
        mode="replay"：重放——已消费且有工件的 effectful 复用，否则在 effectful 边界 HALT（job 收于
        halted、发 RECONCILE_REQUIRED 交对账，绝不在重放路径触达券商）。
        """

        if self._artifact_store is None or self._effect_ledger is None:
            raise RuntimeError("kernel job 需要 InMemoryJobStore(kernel_root=...)；当前未启用内核 store")
        if mode not in ("run", "replay"):
            raise ValueError(f"非法 mode={mode!r}，须 ∈ ('run','replay')")
        job_id = uuid.uuid4().hex
        job = JobRecord(
            job_id=job_id,
            job_type=job_type,
            status="queued",
            payload={"resume_of": _resume_of, "mode": mode} if _resume_of else {"mode": mode},
            submitted_at=utc_now(),
            progress=JobProgress(percent=0, stage="queued", stage_label="等待执行", message="等待执行"),
            payload_summary={"kind": job_type, "task_count": len(tasks), "mode": mode, "resume_of": _resume_of},
        )
        with self._lock:
            self._jobs[job_id] = job
            self._kernel_specs[job_id] = {"tasks": list(tasks), "context": dict(context or {}), "mode": mode}
        thread = threading.Thread(target=self._run_kernel_job, args=(job_id,), daemon=True)
        thread.start()
        return job

    def _make_checkpoint_sink(self, job_id: str):
        """内核 on_event → 节点完成/复用即推进 job.checkpoint（SSE 据它发 checkpoint 事件）。"""

        def sink(rec: dict[str, Any]) -> None:
            if rec.get("event") in {"COMPLETE", "REUSED"}:
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job is not None:
                        job.checkpoint = rec.get("node_id")
                        self._bump(job_id)
        return sink

    def _run_kernel_job(self, job_id: str) -> None:
        from .dag.kernel import DurableExecutor

        spec = self._kernel_specs[job_id]
        tasks, context, mode = spec["tasks"], spec["context"], spec.get("mode", "run")
        started = utc_now()
        self._update_job(job_id, status="running", started_at=started)
        # 每个 job 一个 executor，但共享同一 ArtifactStore + EffectLedger（resume 命门）。
        executor = DurableExecutor(
            store=self._artifact_store,
            ledger=self._effect_ledger,
            on_event=self._make_checkpoint_sink(job_id),
        )
        try:
            run_fn = executor.replay if mode == "replay" else executor.run
            result = run_fn(tasks, dict(context or {}))
            finished = utc_now()
            halted = any(n.halted for n in result.nodes)
            with self._lock:
                job = self._get(job_id)
                # effectful 边界被截断 → halted（待对账，绝不当成功）；否则按内核 succeeded。
                job.status = "halted" if halted else ("succeeded" if result.succeeded else "failed")
                job.finished_at = finished
                job.duration_seconds = _duration_seconds(started, finished)
                job.result = {
                    "node_id_by_task": result.node_id_by_task,
                    "nodes": [
                        {"task_id": n.task_id, "node_id": n.node_id, "status": n.status,
                         "reused": n.reused, "halted": n.halted, "requires_reconcile": n.requires_reconcile}
                        for n in result.nodes
                    ],
                    "events": result.events,
                }
                if job.progress:
                    job.progress.percent = 100
                    job.progress.stage = "halted" if halted else "complete"
                    job.progress.stage_label = "已截断待对账" if halted else "完成"
                    job.progress.message = "effectful 边界截断，待对账" if halted else "内核 DAG 完成"
                self._bump(job_id)
        except Exception as exc:  # noqa: BLE001
            finished = utc_now()
            with self._lock:
                job = self._get(job_id)
                job.status = "failed"
                job.finished_at = finished
                job.duration_seconds = _duration_seconds(started, finished)
                job.error = str(exc)
                if job.progress:
                    job.progress.stage = "error"
                    job.progress.stage_label = "失败"
                    job.progress.message = str(exc)
                self._bump(job_id)

    def list_jobs(self, *, status: str | None = None, job_type: str | None = None, limit: int = 50) -> list[JobRecord]:
        with self._lock:
            jobs = list(self._jobs.values())
        if status:
            jobs = [job for job in jobs if job.status == status]
        if job_type:
            jobs = [job for job in jobs if job.job_type == job_type]
        jobs.sort(key=lambda job: job.submitted_at, reverse=True)
        return jobs[:limit]

    def get_job(self, job_id: str) -> JobRecord:
        with self._lock:
            return self._get(job_id)

    def retry_job(self, job_id: str) -> JobRecord:
        original = self.get_job(job_id)
        if original.job_type == "kernel_dag":
            # 脊柱内核 01 接线（T-023）：从整段重跑 → 从最近 checkpoint 恢复。
            # 用同一张图重跑：pure 节点命中已落 durable 工件直接复用、effectful 节点经
            # EffectLedger.is_consumed 命中即跳过（status=reused，绝不重发单/桥/提币，M17 雷）。
            spec = self._kernel_specs.get(job_id)
            if spec is None:
                raise ValueError(f"kernel job {job_id} 无留存的 tasks，无法恢复重试")
            # 必须透传原 mode：replay job 的 retry 仍是 replay（只读、effectful 边界 HALT），
            # 绝不静默降级为 run——否则「重放不触达券商」翻成真下单（5-lens 复核 MEDIUM）。
            return self.create_kernel_job(spec["tasks"], context=spec["context"],
                                          mode=spec.get("mode", "run"), _resume_of=job_id)
        if original.job_type == "binance_full_pull":
            return self.create_binance_full_pull_job(BinanceFullPullRequest.model_validate(original.payload))
        if original.job_type != "data_sync_pull":
            raise ValueError(f"暂不支持重试任务类型: {original.job_type}")
        return self.create_data_pull_job(DataPullRequest.model_validate(original.payload))

    def cancel_job(self, job_id: str) -> JobRecord:
        with self._lock:
            job = self._get(job_id)
            if job.status in {"succeeded", "failed", "interrupted"}:
                return job
            job.cancel_requested = True
            job.progress = job.progress or JobProgress()
            job.progress.message = "正在请求取消..."
            job.progress.stage = "cancel"
            job.progress.stage_label = "取消中"
            return job

    def _update_job(self, job_id: str, **changes: Any) -> JobRecord:
        with self._lock:
            job = self._get(job_id)
            for key, value in changes.items():
                setattr(job, key, value)
            self._bump(job_id)
            return job

    def _progress_callback(self, job_id: str):
        def callback(percent: int, stage: str, message: str, stats: dict[str, Any] | None = None) -> None:
            with self._lock:
                job = self._get(job_id)
                progress = job.progress or JobProgress()
                progress.percent = max(0, min(100, int(percent)))
                progress.stage = stage
                progress.stage_label = _stage_label(stage)
                progress.message = message
                progress.stats = stats or {}
                job.progress = progress
                self._bump(job_id)
        return callback

    def _is_cancelled(self, job_id: str):
        def callback() -> bool:
            with self._lock:
                return self._get(job_id).cancel_requested
        return callback

    def _run_data_pull_job(self, job_id: str, payload: DataPullRequest) -> None:
        started = utc_now()
        self._update_job(job_id, status="running", started_at=started)
        try:
            result = execute_data_pull(payload, progress=self._progress_callback(job_id), is_cancelled=self._is_cancelled(job_id))
            finished = utc_now()
            duration = _duration_seconds(started, finished)
            with self._lock:
                job = self._get(job_id)
                job.status = "succeeded"
                job.finished_at = finished
                job.duration_seconds = duration
                job.result = result
                if job.progress:
                    job.progress.percent = 100
                    job.progress.stage = "complete"
                    job.progress.stage_label = "完成"
                    job.progress.message = "任务完成"
                self._bump(job_id)
        except Exception as exc:  # noqa: BLE001
            finished = utc_now()
            duration = _duration_seconds(started, finished)
            with self._lock:
                job = self._get(job_id)
                job.finished_at = finished
                job.duration_seconds = duration
                job.error = str(exc)
                if job.cancel_requested:
                    job.status = "interrupted"
                    if job.progress:
                        job.progress.stage = "cancelled"
                        job.progress.stage_label = "已取消"
                        job.progress.message = str(exc)
                else:
                    job.status = "failed"
                    if job.progress:
                        job.progress.stage = "error"
                        job.progress.stage_label = "失败"
                        job.progress.message = str(exc)
                self._bump(job_id)

    def _run_binance_full_pull_job(self, job_id: str, request: BinanceFullPullRequest) -> None:
        started = utc_now()
        self._update_job(job_id, status="running", started_at=started)
        try:
            result = execute_binance_full_pull(
                request,
                progress=self._progress_callback(job_id),
                is_cancelled=self._is_cancelled(job_id),
            )
            finished = utc_now()
            duration = _duration_seconds(started, finished)
            with self._lock:
                job = self._get(job_id)
                job.status = "succeeded"
                job.finished_at = finished
                job.duration_seconds = duration
                job.result = result
                if job.progress:
                    job.progress.percent = 100
                    job.progress.stage = "complete"
                    job.progress.stage_label = "完成"
                    job.progress.message = "一键全量完成"
        except Exception as exc:  # noqa: BLE001
            finished = utc_now()
            duration = _duration_seconds(started, finished)
            with self._lock:
                job = self._get(job_id)
                job.finished_at = finished
                job.duration_seconds = duration
                job.error = str(exc)
                if job.cancel_requested:
                    job.status = "interrupted"
                    if job.progress:
                        job.progress.stage = "cancelled"
                        job.progress.stage_label = "已取消"
                        job.progress.message = str(exc)
                else:
                    job.status = "failed"
                    if job.progress:
                        job.progress.stage = "error"
                        job.progress.stage_label = "失败"
                        job.progress.message = str(exc)
                self._bump(job_id)


def _duration_seconds(started_at: str, finished_at: str) -> float:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    return round((end - start).total_seconds(), 3)


def _stage_label(stage: str) -> str:
    labels = {
        "queued": "等待执行",
        "prepare": "准备中",
        "prepare_request": "准备请求",
        "validate_tokens": "校验 Token",
        "resolve_permissions": "解析权限",
        "resolve_targets": "解析目标",
        "pull_batches": "拉取批次",
        "write_parquet": "写入数据",
        "write_csv": "写入数据",
        "materialize_runtime": "生成运行时视图",
        "rebuild_catalog": "重建目录",
        "finalize": "收尾",
        "pull_tushare": "拉取 Tushare",
        "pull_binance": "拉取 Binance",
        "cancel": "取消中",
        "complete": "完成",
        "error": "失败",
    }
    return labels.get(stage, stage)


def _build_payload_summary(payload: DataPullRequest) -> dict[str, Any]:
    symbols = payload.symbols or []
    return {
        "kind": "data_sync_pull",
        "market": payload.market,
        "data_kind": payload.data_kind,
        "symbol_mode": payload.symbol_mode,
        "pool_id": payload.stock_pool_id,
        "symbol_count": len(symbols),
        "start": payload.start,
        "end": payload.end,
        "full_history": payload.full_history,
        "interval": payload.interval,
    }


def _build_binance_full_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "binance_full_pull",
        "market": "binanceusdm",
        "vision_start": payload.get("vision_start"),
        "vision_end": payload.get("vision_end"),
        "default_interval": payload.get("default_interval"),
    }
