from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from .data_pull import execute_binance_full_pull, execute_data_pull
from .schemas import BinanceFullPullRequest, DataPullRequest, JobProgress, JobRecord


def utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class InMemoryJobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}

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
