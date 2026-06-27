"""v0.8.4 Day 4 · run 证据状态风险摘要（纯函数）。

输入: run metrics dict (含 sharpe / pbo / dsr / max_drawdown / ic_ir / turnover / 等)
输出:
    {
      "trust_level": "ok" | "caution" | "high_risk" | "insufficient_data",
      "flags": [{"name": ..., "severity": ..., "message": ..., "metric_value": ...}],
      "summary": "一句话总结，给 RunDetail 顶部 chip 用",
      "checked_metrics": [...]
    }

规则集（patch1 §D.c 给的 5 条 + 用户要求补 turnover/exposure 并集 = 7 条）：

  HIGH (任一触发 → trust_level=high_risk)
    1. pbo > 0.6                       · CSCV 过拟合概率高
    2. dsr < 0.2                       · 折减夏普证据不足
    3. max_drawdown < -0.25            · 单次回测损失 > 25%

  MEDIUM (累积或单触发 caution)
    4. sharpe < 1.0 (但 > 0)           · 收益风险比偏低
    5. ic_ir < 0.3                     · 因子预测稳定性不足
    6. turnover > 3.0                  · 年化换手率 > 300% (成本敏感)
    7. concentration > 0.25            · 单标的占比 > 25%

  INSUFFICIENT (必需字段缺失 → trust_level=insufficient_data)
    - 既无 pbo 也无 dsr 时：无法判断过拟合证据状态（即便 sharpe 漂亮）

完全 pure function：不依赖 db / file / http；可在 promote_ide_run / RunDetail API
/ 主动建议 hook 任何路径下调用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal


TrustLevel = Literal["ok", "caution", "high_risk", "insufficient_data"]
Severity = Literal["high", "medium", "low"]


@dataclass
class RiskFlag:
    name: str
    severity: Severity
    message: str
    metric_name: str
    metric_value: float | None
    threshold: float


@dataclass
class RiskSummary:
    trust_level: TrustLevel
    flags: list[RiskFlag] = field(default_factory=list)
    summary: str = ""
    checked_metrics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trust_level": self.trust_level,
            "flags": [f.__dict__ for f in self.flags],
            "summary": self.summary,
            "checked_metrics": list(self.checked_metrics),
        }


def _read(metrics: dict[str, Any], *names: str) -> float | None:
    """metrics 里取第一个非 None / finite 的数。"""
    for n in names:
        v = metrics.get(n)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            return f
    return None


# ---------- 规则定义 ----------


def _rule_pbo(metrics: dict[str, Any]) -> RiskFlag | None:
    v = _read(metrics, "pbo", "probability_of_backtest_overfitting")
    if v is None:
        return None
    if v > 0.6:
        return RiskFlag(
            name="high_overfit_risk",
            severity="high",
            message=f"PBO={v:.2f} > 0.6，CSCV 过拟合概率高；建议 walk-forward 重测",
            metric_name="pbo",
            metric_value=v,
            threshold=0.6,
        )
    return None


def _rule_dsr(metrics: dict[str, Any]) -> RiskFlag | None:
    v = _read(metrics, "dsr", "deflated_sharpe", "deflated_sharpe_ratio", "dsr_confidence")
    if v is None:
        return None
    if v < 0.2:
        return RiskFlag(
            name="low_dsr_confidence",
            severity="high",
            message=f"DSR={v:.2f} < 0.2，多次试验偏差大；当前 Sharpe 不足以支撑晋级",
            metric_name="dsr",
            metric_value=v,
            threshold=0.2,
        )
    return None


def _rule_max_drawdown(metrics: dict[str, Any]) -> RiskFlag | None:
    v = _read(metrics, "max_drawdown", "drawdown")
    if v is None:
        return None
    # max_drawdown 通常是负数（如 -0.25），但有些实现给正数 0.25
    abs_dd = abs(v)
    if abs_dd > 0.25:
        return RiskFlag(
            name="high_max_drawdown",
            severity="high",
            message=f"最大回撤 {abs_dd:.1%} > 25%，资金曲线深度受伤；杠杆/止损需复核",
            metric_name="max_drawdown",
            metric_value=v,
            threshold=-0.25,
        )
    return None


def _rule_sharpe(metrics: dict[str, Any]) -> RiskFlag | None:
    v = _read(metrics, "sharpe", "sharpe_ratio")
    if v is None:
        return None
    if 0 < v < 1.0:
        return RiskFlag(
            name="low_sharpe",
            severity="medium",
            message=f"Sharpe={v:.2f} < 1.0，收益风险比偏低；尝试调整标签 / universe",
            metric_name="sharpe",
            metric_value=v,
            threshold=1.0,
        )
    return None


def _rule_ic_ir(metrics: dict[str, Any]) -> RiskFlag | None:
    v = _read(metrics, "ic_ir", "ic_information_ratio")
    if v is None:
        return None
    if 0 < v < 0.3:
        return RiskFlag(
            name="low_factor_predictive",
            severity="medium",
            message=f"IC-IR={v:.2f} < 0.3，因子预测稳定性不足；考虑因子组合或时间窗调整",
            metric_name="ic_ir",
            metric_value=v,
            threshold=0.3,
        )
    return None


def _rule_turnover(metrics: dict[str, Any]) -> RiskFlag | None:
    v = _read(metrics, "turnover", "annual_turnover")
    if v is None:
        return None
    if v > 3.0:
        return RiskFlag(
            name="excessive_turnover",
            severity="medium",
            message=f"年化换手率 {v:.1%} > 300%，交易成本对净收益侵蚀显著",
            metric_name="turnover",
            metric_value=v,
            threshold=3.0,
        )
    return None


def _rule_concentration(metrics: dict[str, Any]) -> RiskFlag | None:
    v = _read(metrics, "max_position_weight", "concentration", "max_single_weight")
    if v is None:
        return None
    if v > 0.25:
        return RiskFlag(
            name="high_concentration",
            severity="medium",
            message=f"单标的占比 {v:.1%} > 25%，集中度过高",
            metric_name="max_position_weight",
            metric_value=v,
            threshold=0.25,
        )
    return None


# 顺序按 severity 排（high 先）便于阅读
_RULES = [
    _rule_pbo,
    _rule_dsr,
    _rule_max_drawdown,
    _rule_sharpe,
    _rule_ic_ir,
    _rule_turnover,
    _rule_concentration,
]


def compute_risk_summary(metrics: dict[str, Any] | None) -> RiskSummary:
    """从 metrics dict 推断风险等级。"""

    if not metrics:
        return RiskSummary(
            trust_level="insufficient_data",
            summary="无 metrics 数据，无法给出证据状态",
        )

    flags: list[RiskFlag] = []
    checked: list[str] = []
    for rule in _RULES:
        flag = rule(metrics)
        if flag is not None:
            flags.append(flag)
            checked.append(flag.metric_name)
        else:
            # 即便没触发也记录"检查过这个 metric"（只有该 metric 有值才算 checked）
            # 通过 rule 内部 _read 探测：这里再 _read 一次以确认 metric 存在
            pass

    # 完整 checked_metrics：遍历每个规则中尝试 read 的 alias，记录命中
    rule_metric_aliases = {
        "pbo": ["pbo", "probability_of_backtest_overfitting"],
        "dsr": ["dsr", "deflated_sharpe", "deflated_sharpe_ratio", "dsr_confidence"],
        "max_drawdown": ["max_drawdown", "drawdown"],
        "sharpe": ["sharpe", "sharpe_ratio"],
        "ic_ir": ["ic_ir", "ic_information_ratio"],
        "turnover": ["turnover", "annual_turnover"],
        "max_position_weight": ["max_position_weight", "concentration", "max_single_weight"],
    }
    checked = [name for name, aliases in rule_metric_aliases.items() if _read(metrics, *aliases) is not None]

    # 判断等级：核心两个反过拟合证据缺失 → insufficient
    has_pbo = _read(metrics, "pbo") is not None
    has_dsr = _read(metrics, "dsr", "deflated_sharpe", "deflated_sharpe_ratio") is not None
    has_sharpe = _read(metrics, "sharpe", "sharpe_ratio") is not None

    if has_sharpe and not has_pbo and not has_dsr:
        # 经典反过拟合证据双缺：即便其他规则没触发也是 insufficient
        return RiskSummary(
            trust_level="insufficient_data",
            flags=flags,
            summary="Sharpe 已有但缺 PBO/DSR 反过拟合证据，无法给出 Sharpe 证据状态",
            checked_metrics=checked,
        )

    if not checked:
        return RiskSummary(
            trust_level="insufficient_data",
            flags=flags,
            summary="metrics 中无可识别字段",
            checked_metrics=checked,
        )

    high_flags = [f for f in flags if f.severity == "high"]
    medium_flags = [f for f in flags if f.severity == "medium"]

    if high_flags:
        level: TrustLevel = "high_risk"
        summary = f"{len(high_flags)} 条高风险信号 · {high_flags[0].message}"
    elif medium_flags:
        level = "caution"
        summary = f"{len(medium_flags)} 条中等风险信号 · {medium_flags[0].message}"
    else:
        level = "ok"
        summary = f"已检 {len(checked)} 个指标全部在合理区间"

    return RiskSummary(
        trust_level=level,
        flags=flags,
        summary=summary,
        checked_metrics=checked,
    )


__all__ = ["RiskFlag", "RiskSummary", "TrustLevel", "compute_risk_summary"]
