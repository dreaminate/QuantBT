"""信号层规范组合器 compose_signal_pipeline 对抗测试（不可绕过的安全路径·不假信号）。

门必抓：
- **全安全门施加**：regime 关停 + 低置信打平 + conformal 区间跨阈弃权，任一触发 → direction=flat/magnitude=0。
- **与手工逐步等价**：compose == fuse→regime→confidence→abstain 逐步施加（组合器不偷改语义）。
- **向后兼容**：conformal_band=0 → 全 abstained=False（不弃权）；regimes=None → 跳过 regime gating（不臆造）。
- **导出面**：compose_signal_pipeline + conformal_abstain_gate 可从 app.signals 导入（修 core.py __all__ 漏导出）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

import app.signals as signals_pkg
from app.signals import (
    apply_regime_gating,
    compose_signal_pipeline,
    confidence_threshold_filter,
    conformal_abstain_gate,
    fuse_signals,
)

_T1 = datetime(2024, 1, 1, tzinfo=UTC)
_T2 = _T1 + timedelta(days=1)


def _preds() -> pl.DataFrame:
    return pl.DataFrame([
        {"ts": _T1, "symbol": "X", "score": 0.70},    # 强 long
        {"ts": _T1, "symbol": "Y", "score": -0.60},   # short
        {"ts": _T2, "symbol": "X", "score": 0.08},    # 弱 long（小 |score|，落 conformal 带内）
    ])


def test_compose_applies_all_safety_gates():
    """regime 关停 + conformal 弃权同时生效：bear 下 long→flat、short 保留；带内弱信号→弃权 flat。"""
    regimes = pl.DataFrame({"ts": [_T1, _T2], "regime": ["bear", "range"]})
    out = compose_signal_pipeline(
        _preds(), regimes=regimes, min_confidence=0.0,   # 关掉置信门以隔离 regime+abstain
        conformal_band=0.15,
    ).sort(["ts", "symbol"]).to_dicts()
    by = {(r["ts"], r["symbol"]): r for r in out}
    assert by[(_T1, "X")]["direction"] == "flat"                 # long 撞 bear → flat
    assert by[(_T1, "Y")]["direction"] == "short"               # short 在 bear 允许、|−0.6|>0.15 不弃权
    assert by[(_T2, "X")]["direction"] == "flat"                 # |0.08|≤0.15 → 区间跨阈弃权
    assert by[(_T2, "X")]["abstained"] is True
    assert by[(_T2, "X")]["magnitude"] == 0.0


def test_compose_equals_manual_sequential():
    """组合器 == 手工 fuse→regime→confidence→abstain 逐步施加（不偷改语义）。"""
    preds = _preds()
    regimes = pl.DataFrame({"ts": [_T1, _T2], "regime": ["bull", "range"]})
    composed = compose_signal_pipeline(
        preds, regimes=regimes, min_confidence=0.55, conformal_band=0.15,
    ).sort(["ts", "symbol"])
    manual = fuse_signals(preds)
    manual = apply_regime_gating(manual, regimes)
    manual = confidence_threshold_filter(manual, min_confidence=0.55)
    manual = conformal_abstain_gate(manual, conformal_band=0.15)
    manual = manual.sort(["ts", "symbol"])
    assert composed.select(["ts", "symbol", "direction", "magnitude", "abstained"]).to_dicts() == \
        manual.select(["ts", "symbol", "direction", "magnitude", "abstained"]).to_dicts()


def test_compose_conformal_band_zero_no_abstain():
    """conformal_band=0（默认）→ 全 abstained=False（不弃权·向后兼容）。"""
    out = compose_signal_pipeline(_preds(), min_confidence=0.0).to_dicts()
    assert all(r["abstained"] is False for r in out)


def test_compose_regimes_none_skips_regime_gating():
    """regimes=None → 跳过 regime gating（无 regime 数据不臆造）：强 long 不被任何 regime 打平。"""
    out = compose_signal_pipeline(_preds(), regimes=None, min_confidence=0.0).sort(["ts", "symbol"]).to_dicts()
    by = {(r["ts"], r["symbol"]): r for r in out}
    assert by[(_T1, "X")]["direction"] == "long"     # 无 regime → 强 long 保留
    assert by[(_T1, "Y")]["direction"] == "short"


def test_compose_export_surface():
    """compose_signal_pipeline + conformal_abstain_gate 可从 app.signals 导入 + 在 __all__（修 core.py 漏导出）。"""
    assert "compose_signal_pipeline" in signals_pkg.__all__
    assert "conformal_abstain_gate" in signals_pkg.__all__
    from app.signals.core import __all__ as core_all
    assert "compose_signal_pipeline" in core_all and "conformal_abstain_gate" in core_all
