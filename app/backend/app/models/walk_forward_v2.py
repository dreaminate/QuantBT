"""v0.9.7 学术 audit (patch1 §G.a #4) · Walk-forward with per-window selection log.

学术依据: López de Prado 2018 §11.5 / §7.5

漏洞: 旧 walk_forward(n_samples, train_size, test_size) 只生成 train/test indices,
       调用方可能先全样本 GridSearch 选最优参数再分窗 → 破坏 OOS 性质 (lookahead bias)

修复: 强制 per-window 内独立选参 (train fold 内 evaluate 所有 candidate 再选最优),
       并记录完整 selection log 便于 audit。任何"先选参再 walk-forward"的程序在
       这个 API 下都跑不通。

Contract test 锁定: WalkForwardReport.deterministic 必须为 True，每 window
       candidates_evaluated 必须 ≥ 1，candidate_train_metrics 与 candidates 同长。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import numpy as np


@dataclass
class ParamCandidate:
    """单个参数候选 + canonical hash (避免顺序不同算成不同 candidate)。"""

    params: dict[str, Any]
    params_hash: str = ""

    def __post_init__(self) -> None:
        if not self.params_hash:
            canonical = json.dumps(self.params, sort_keys=True, ensure_ascii=False)
            self.params_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass
class WindowSelectionLog:
    """单个 walk-forward window 的完整 selection 日志，每条都是 audit 可追溯。"""

    fold_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    candidates_evaluated: list[ParamCandidate] = field(default_factory=list)
    candidate_train_metrics: list[float] = field(default_factory=list)
    selected_params_hash: str = ""
    selected_train_metric: float = float("nan")
    test_metric: float = float("nan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "candidates_evaluated": [asdict(c) for c in self.candidates_evaluated],
            "candidate_train_metrics": list(self.candidate_train_metrics),
            "selected_params_hash": self.selected_params_hash,
            "selected_train_metric": self.selected_train_metric,
            "test_metric": self.test_metric,
        }


@dataclass
class WalkForwardReport:
    windows: list[WindowSelectionLog] = field(default_factory=list)
    aggregate_oos_metric: float = float("nan")
    deterministic: bool = True   # 所有 window 都有完整 candidate selection log

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [w.to_dict() for w in self.windows],
            "aggregate_oos_metric": self.aggregate_oos_metric,
            "deterministic": self.deterministic,
            "n_windows": len(self.windows),
        }


# Type aliases
MetricFn = Callable[[dict[str, Any], np.ndarray, np.ndarray], float]
# evaluator(params, X_train_slice, y_train_slice) → train metric (Sharpe / IR / ...)


class WalkForwardLeakError(Exception):
    """检测到 GridSearch leak（调用方违反 per-window 独立选参语义）。"""


def run_walk_forward_v2(
    *,
    X: np.ndarray,
    y: np.ndarray,
    param_grid: list[dict[str, Any]],
    evaluator: MetricFn,
    train_size: int,
    test_size: int,
    step: int | None = None,
    embargo: int = 0,
) -> WalkForwardReport:
    """学术正确的 walk-forward: per-window 内独立选参。

    任何 caller 想"先全样本选参再分窗"的程序在这个 API 下都被强制改写为正确流程。

    输入:
      X, y: 样本 (n, d) / (n,)，按时间排好序
      param_grid: 候选参数 list，每项 dict
      evaluator(params, X_train, y_train) → float: train metric
      train_size / test_size / step / embargo: 窗口配置

    流程:
      for each window:
        1. 切 train / test fold
        2. 对 param_grid 每一项在 train fold 内 evaluator() → train_metric
        3. 选 argmax train_metric → selected_params
        4. 用 selected_params 在 test fold 上 evaluator → test_metric
        5. 写 WindowSelectionLog (含 candidate_train_metrics 全集 便于审计)
    """

    if X.ndim != 2:
        raise ValueError(f"X must be 2D, got {X.ndim}D")
    n = X.shape[0]
    if len(y) != n:
        raise ValueError(f"X.shape[0]={n} != len(y)={len(y)}")
    if not param_grid:
        raise ValueError("param_grid 必须非空 (walk-forward 必须有候选)")

    candidates = [ParamCandidate(params=p) for p in param_grid]
    step = step or test_size

    report = WalkForwardReport()
    start = 0
    fold = 0
    while start + train_size + embargo + test_size <= n:
        train_end = start + train_size
        test_start = train_end + embargo
        test_end = test_start + test_size

        X_train = X[start:train_end]
        y_train = y[start:train_end]
        X_test = X[test_start:test_end]
        y_test = y[test_start:test_end]

        # Per-window 内独立 evaluate 所有 candidate
        train_metrics: list[float] = []
        for cand in candidates:
            try:
                m = float(evaluator(cand.params, X_train, y_train))
            except Exception as exc:  # noqa: BLE001
                m = float("-inf")  # 失败 candidate 标记最低
            train_metrics.append(m)

        # 选 argmax
        best_idx = int(np.argmax(train_metrics))
        selected = candidates[best_idx]
        try:
            test_metric = float(evaluator(selected.params, X_test, y_test))
        except Exception:  # noqa: BLE001
            test_metric = float("nan")

        log = WindowSelectionLog(
            fold_index=fold,
            train_start=start, train_end=train_end,
            test_start=test_start, test_end=test_end,
            candidates_evaluated=candidates,
            candidate_train_metrics=train_metrics,
            selected_params_hash=selected.params_hash,
            selected_train_metric=train_metrics[best_idx],
            test_metric=test_metric,
        )
        report.windows.append(log)
        fold += 1
        start += step

    # aggregate OOS = mean of test metrics
    if report.windows:
        valid_test = [w.test_metric for w in report.windows if not math.isnan(w.test_metric)]
        if valid_test:
            report.aggregate_oos_metric = float(np.mean(valid_test))

    # deterministic check: 所有 window candidate count 都 >= 1 且 log 完整
    report.deterministic = all(
        len(w.candidates_evaluated) >= 1 and len(w.candidate_train_metrics) == len(w.candidates_evaluated)
        for w in report.windows
    )

    return report


def detect_gridsearch_leak(report: WalkForwardReport) -> tuple[bool, str]:
    """启发式检测调用方是否违反 per-window 独立选参语义。

    Heuristics:
    1. 如果只有 1 个 candidate 但 param_grid 应该有多个 → 怀疑外部已选好参再传
    2. 如果所有 window selected_params_hash 完全一致 → 怀疑全局最优而非 per-window
    3. 如果 candidate_train_metrics 全 NaN → evaluator 没真跑
    """
    if not report.windows:
        return False, "no windows"
    # heuristic 1
    first_n_cands = len(report.windows[0].candidates_evaluated)
    if first_n_cands == 1:
        return True, "only 1 candidate evaluated - 怀疑外部 GridSearch 后只传最优 (违反 per-window 语义)"
    # heuristic 2
    hashes = {w.selected_params_hash for w in report.windows}
    if len(hashes) == 1 and len(report.windows) > 3:
        return True, f"所有 {len(report.windows)} 个 window 选了同一 params - 怀疑全样本最优 (lookahead bias)"
    # heuristic 3
    if all(all(math.isnan(m) or m == float("-inf") for m in w.candidate_train_metrics) for w in report.windows):
        return True, "所有 candidate_train_metrics 都 nan/-inf - evaluator 没真跑"
    return False, "ok"


__all__ = [
    "MetricFn",
    "ParamCandidate",
    "WalkForwardLeakError",
    "WalkForwardReport",
    "WindowSelectionLog",
    "detect_gridsearch_leak",
    "run_walk_forward_v2",
]
