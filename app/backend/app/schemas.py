from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


ProgressMode = Literal["basic", "detailed"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "interrupted"]
SymbolMode = Literal["manual", "all", "stock_pool", "preset"]
NumericFilterOperator = Literal[">", ">=", "<", "<=", "=", "between"]


class DataPullRequest(BaseModel):
    market: str
    data_kind: str
    symbol_mode: SymbolMode = "manual"
    symbol_source: str | None = None
    symbols: list[str] = Field(default_factory=list)
    stock_pool_id: str | None = None
    pool_id: str | None = None
    preset_name: str | None = None
    start: str | None = None
    end: str | None = None
    full_history: bool = False
    refresh_mode: Literal["incremental", "full"] = "incremental"
    interval: str | None = None
    progress_mode: ProgressMode | None = "detailed"

    @model_validator(mode="before")
    @classmethod
    def _normalize_symbol_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if out.get("symbol_source"):
            mapping = {"pool": "stock_pool", "manual": "manual", "all": "all"}
            out["symbol_mode"] = mapping.get(str(out["symbol_source"]), out.get("symbol_mode", "manual"))
        pool = out.get("pool_id") or out.get("stock_pool_id")
        if pool:
            out["stock_pool_id"] = pool
        return out


class BinanceFullPullRequest(BaseModel):
    """一键全量拉取 Binance USDM：按种类顺序依次 Full Refresh。"""

    vision_start: str = "2019-09-01"
    vision_end: str | None = None
    default_interval: str = "1h"


class RunTableOptions(BaseModel):
    limit: int = 200
    offset: int = 0
    sort: str | None = None
    order: Literal["asc", "desc"] = "desc"
    start_ts: str | None = None
    end_ts: str | None = None
    symbol: str | None = None
    side: str | None = None


class RunNumericFilter(BaseModel):
    field: str
    operator: NumericFilterOperator
    value: float
    value_to: float | None = None


class RunQueryRequest(BaseModel):
    search: str | None = None
    favorite_only: bool = False
    strategy_mode: str | None = None
    status: str | None = None
    market: str | None = None
    frequency: str | None = None
    benchmark: str | None = None
    dataset_version: str | None = None
    universe_snapshot_id: str | None = None
    neutralization: str | None = None
    unit_handling: str | None = None
    pasteurization: str | None = None
    model_used: bool | None = None
    sort_by: str | None = "started_at"
    sort_order: Literal["asc", "desc"] = "desc"
    limit: int = 200
    offset: int = 0
    numeric_filters: list[RunNumericFilter] = Field(default_factory=list)


@dataclass
class JobProgressDetailItem:
    label: str
    status: Literal["pending", "active", "completed", "failed"] = "pending"
    message: str | None = None


@dataclass
class JobProgress:
    percent: int = 0
    stage: str = "queued"
    stage_label: str = "等待执行"
    message: str = "等待执行"
    mode: ProgressMode = "detailed"
    stats: dict[str, Any] = field(default_factory=dict)
    detail_items: list[JobProgressDetailItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["detail_items"] = [asdict(item) for item in self.detail_items]
        return payload


@dataclass
class JobRecord:
    job_id: str
    job_type: str
    status: JobStatus
    payload: dict[str, Any]
    submitted_at: str
    started_at: str | None = None
    finished_at: str | None = None
    progress: JobProgress | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    run_id: str | None = None
    duration_seconds: float | None = None
    payload_summary: dict[str, Any] | None = None
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "payload": self.payload,
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress.to_dict() if self.progress else None,
            "error": self.error,
            "result": self.result,
            "run_id": self.run_id,
            "duration_seconds": self.duration_seconds,
            "payload_summary": self.payload_summary or {},
        }


class NotebookMetricCard(BaseModel):
    key: str
    label: str
    value: float | int | str | None = None
    format: Literal["pct", "num", "text"] = "text"


class NotebookBundle(BaseModel):
    run: dict[str, Any]
    metric_cards: list[NotebookMetricCard]
    available_series: list[str]
    report_markdown: str | None = None
    log_entries: list[dict[str, Any]] = Field(default_factory=list)
