"""M3b · dataset_version (不可变) + freshness 探测 + GE-lite 规则。

参见 QuantBT-GOAL.md §M3 数据治理与 §6.2 数据质量。

设计：
- **dataset_version 不可变**：同一 `dataset_id` 可有多个 version，但每个 version
  一旦写入 registry 就不能再改。registry 落 `data/datasets/registry.jsonl`
  (append-only)；版本号用 ULID-like = `{utc-iso}__{sha256[:8]}`。
- **freshness**：给定 dataset_id 返回 (last_coverage_end, expected_end,
  staleness_seconds, status: green/yellow/red)。期望更新时间按 market：
  A股按交易日历的下一日，加密按当前 UTC（24/7 市场）。
- **GE-lite 规则**：5 类轻量规则（不引入 great_expectations 依赖）：
  not_null / unique / monotonic / value_range / foreign_key。
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

import polars as pl

from .connectors.base import FetchResult


GE_RuleType = Literal["not_null", "unique", "monotonic", "value_range", "foreign_key"]
FreshnessStatus = Literal["green", "yellow", "red", "unknown"]


@dataclass
class GERule:
    column: str
    rule_type: GE_RuleType
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GERule":
        return cls(column=data["column"], rule_type=data["rule_type"], params=data.get("params") or {})


@dataclass
class GECheckResult:
    column: str
    rule_type: GE_RuleType
    passed: bool
    failed_count: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_ge_checks(
    frame: pl.DataFrame,
    rules: list[GERule],
    foreign_provider: dict[str, set[Any]] | None = None,
) -> list[GECheckResult]:
    """运行规则集；foreign_provider 提供 {target_dataset_id: set_of_values}。"""

    results: list[GECheckResult] = []
    if frame is None or frame.is_empty():
        for rule in rules:
            results.append(
                GECheckResult(
                    column=rule.column,
                    rule_type=rule.rule_type,
                    passed=False,
                    failed_count=0,
                    message="dataset 为空，规则无法判定",
                )
            )
        return results
    for rule in rules:
        if rule.column not in frame.columns:
            results.append(
                GECheckResult(
                    column=rule.column,
                    rule_type=rule.rule_type,
                    passed=False,
                    failed_count=frame.height,
                    message=f"列不存在: {rule.column}",
                )
            )
            continue
        column = frame.get_column(rule.column)
        if rule.rule_type == "not_null":
            failed = column.is_null().sum()
            results.append(_ge_result(rule, failed == 0, failed, f"null 数 {failed}"))
        elif rule.rule_type == "unique":
            failed = column.len() - column.n_unique()
            results.append(_ge_result(rule, failed == 0, failed, f"重复 {failed}"))
        elif rule.rule_type == "monotonic":
            order = rule.params.get("order", "asc")
            sorted_col = column.sort(descending=(order != "asc"))
            ok = column.equals(sorted_col)
            results.append(
                _ge_result(rule, ok, 0 if ok else frame.height, f"单调 {order} 失败" if not ok else "ok")
            )
        elif rule.rule_type == "value_range":
            lo = rule.params.get("min")
            hi = rule.params.get("max")
            expr = pl.lit(True)
            if lo is not None:
                expr = expr & (pl.col(rule.column) >= lo)
            if hi is not None:
                expr = expr & (pl.col(rule.column) <= hi)
            failed = frame.filter(~expr).height
            results.append(_ge_result(rule, failed == 0, failed, f"超出范围 {failed}"))
        elif rule.rule_type == "foreign_key":
            target = rule.params.get("target_dataset_id")
            if not foreign_provider or target not in foreign_provider:
                results.append(_ge_result(rule, False, frame.height, f"未提供 {target} 的对照值"))
                continue
            valid = foreign_provider[target]
            failed = sum(1 for v in column.to_list() if v not in valid)
            results.append(_ge_result(rule, failed == 0, failed, f"外键不命中 {failed}"))
        else:
            results.append(_ge_result(rule, False, 0, f"未知规则: {rule.rule_type}"))
    return results


def _ge_result(rule: GERule, passed: bool, failed_count: int, message: str) -> GECheckResult:
    return GECheckResult(
        column=rule.column,
        rule_type=rule.rule_type,
        passed=passed,
        failed_count=int(failed_count or 0),
        message=message,
    )


@dataclass
class DatasetVersion:
    dataset_id: str
    version_id: str
    source_name: str
    fetched_at_utc: str
    row_count: int
    coverage_start_utc: str | None
    coverage_end_utc: str | None
    sha256: str
    file_paths: list[str] = field(default_factory=list)
    ge_results: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatasetVersion":
        return cls(**data)


def make_version_id(fetched_at_utc: str, sha256: str) -> str:
    safe_ts = fetched_at_utc.replace(":", "").replace("-", "").replace("+", "_").replace(".", "_")
    return f"{safe_ts}__{sha256[:8]}"


class DatasetRegistry:
    """append-only JSONL registry。线程安全；多进程下要把 lock 替换成 fcntl。"""

    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()

    @property
    def store_path(self) -> Path:
        return self._path

    def register(
        self,
        dataset_id: str,
        fetch_result: FetchResult,
        file_paths: list[str] | None = None,
        rules: list[GERule] | None = None,
        metadata: dict[str, Any] | None = None,
        foreign_provider: dict[str, set[Any]] | None = None,
    ) -> DatasetVersion:
        ge_results = []
        if rules:
            ge_results = [r.to_dict() for r in run_ge_checks(fetch_result.frame, rules, foreign_provider)]
        # 数据平台 v2：把数据集真实列清单落进 metadata["columns"]（FieldCatalog 的真相源之一）。
        # 用 metadata 既有扩展点，不改 DatasetVersion 字段，旧 jsonl 行不受影响。
        meta = dict(metadata or {})
        if "columns" not in meta:
            try:
                meta["columns"] = list(fetch_result.frame.columns)
            except Exception:  # noqa: BLE001
                pass
        version = DatasetVersion(
            dataset_id=dataset_id,
            version_id=make_version_id(fetch_result.fetched_at_utc, fetch_result.sha256),
            source_name=fetch_result.source_name,
            fetched_at_utc=fetch_result.fetched_at_utc,
            row_count=fetch_result.row_count,
            coverage_start_utc=fetch_result.coverage_start_utc,
            coverage_end_utc=fetch_result.coverage_end_utc,
            sha256=fetch_result.sha256,
            file_paths=list(file_paths or []),
            ge_results=ge_results,
            metadata=meta,
        )
        self._append(version)
        return version

    def list_versions(self, dataset_id: str | None = None) -> list[DatasetVersion]:
        items: list[DatasetVersion] = []
        with self._lock:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if dataset_id is None or data["dataset_id"] == dataset_id:
                    items.append(DatasetVersion.from_dict(data))
        return items

    def latest(self, dataset_id: str) -> DatasetVersion | None:
        versions = sorted(
            self.list_versions(dataset_id),
            key=lambda v: v.fetched_at_utc,
        )
        return versions[-1] if versions else None

    def list_dataset_ids(self) -> list[str]:
        return sorted({v.dataset_id for v in self.list_versions()})

    def _append(self, version: DatasetVersion) -> None:
        line = json.dumps(version.to_dict(), ensure_ascii=False)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


@dataclass
class FreshnessReport:
    dataset_id: str
    status: FreshnessStatus
    expected_end_utc: str
    actual_end_utc: str | None
    staleness_seconds: float | None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_end_utc(market_kind: str, *, now: datetime | None = None) -> datetime:
    """近似的"应有最新数据时间"。

    - A股 (`stocks_cn` / `indices_cn` / `funds_cn`)：取最近一个工作日 15:30 收盘 +
      30 分钟（结算窗口）。周六周日按周五处理，节假日表暂不嵌入（外接 pandas-mc）。
    - 加密 (`binance*`)：当前 UTC（24/7）。
    - 其它：当前 UTC（保守）。
    """

    now = (now or datetime.now(UTC)).astimezone(UTC)
    if market_kind.startswith("stocks_cn") or market_kind.startswith("indices_cn") or market_kind.startswith("funds_cn"):
        sh_now = now + timedelta(hours=8)
        target = sh_now
        if sh_now.time() < time(16, 0):
            target = target - timedelta(days=1)
        while target.weekday() >= 5:  # Sat=5 Sun=6
            target = target - timedelta(days=1)
        target = datetime.combine(target.date(), time(16, 0))
        return (target - timedelta(hours=8)).replace(tzinfo=UTC)
    return now


def compute_freshness(
    dataset_id: str,
    market_kind: str,
    registry: DatasetRegistry,
    *,
    yellow_threshold_seconds: float = 24 * 3600,
    red_threshold_seconds: float = 7 * 24 * 3600,
    now: datetime | None = None,
) -> FreshnessReport:
    version = registry.latest(dataset_id)
    expected = expected_end_utc(market_kind, now=now)
    if version is None or not version.coverage_end_utc:
        return FreshnessReport(
            dataset_id=dataset_id,
            status="unknown",
            expected_end_utc=expected.isoformat(),
            actual_end_utc=None,
            staleness_seconds=None,
            note="无版本",
        )
    actual = datetime.fromisoformat(version.coverage_end_utc.replace("Z", "+00:00"))
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=UTC)
    staleness = (expected - actual).total_seconds()
    if staleness < 0:
        status: FreshnessStatus = "green"
    elif staleness <= yellow_threshold_seconds:
        status = "green"
    elif staleness <= red_threshold_seconds:
        status = "yellow"
    else:
        status = "red"
    return FreshnessReport(
        dataset_id=dataset_id,
        status=status,
        expected_end_utc=expected.isoformat(),
        actual_end_utc=actual.isoformat(),
        staleness_seconds=staleness,
        note=f"version {version.version_id}",
    )


__all__ = [
    "DatasetRegistry",
    "DatasetVersion",
    "FreshnessReport",
    "FreshnessStatus",
    "GECheckResult",
    "GE_RuleType",
    "GERule",
    "compute_freshness",
    "expected_end_utc",
    "make_version_id",
    "run_ge_checks",
]
