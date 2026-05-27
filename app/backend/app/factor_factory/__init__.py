"""M4 · 因子工厂：算子空间 + 表达式引擎 + 注册表 + IC 工具。"""

from __future__ import annotations

from .alpha_lite import alpha_lite_specs, register_alpha_lite
from .expression import ExpressionError, compile_expression, evaluate_on_panel, parse_expression
from .ic import ICReport, attach_forward_returns, compute_ic_decay, compute_ic_report
from .lifecycle import (
    FactorObservation,
    LifecycleEvent,
    LifecycleManager,
    LifecycleThresholds,
    evaluate_transition,
)
from .operators import OPERATOR_REGISTRY, list_operators
from .registry import Factor, FactorRegistry, LifecycleState

__all__ = [
    "ExpressionError",
    "Factor",
    "FactorObservation",
    "FactorRegistry",
    "ICReport",
    "LifecycleEvent",
    "LifecycleManager",
    "LifecycleState",
    "LifecycleThresholds",
    "OPERATOR_REGISTRY",
    "alpha_lite_specs",
    "attach_forward_returns",
    "compile_expression",
    "compute_ic_decay",
    "compute_ic_report",
    "evaluate_on_panel",
    "evaluate_transition",
    "list_operators",
    "parse_expression",
    "register_alpha_lite",
]
