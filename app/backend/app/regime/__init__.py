"""M2 · 市场状态划分（regime）包。"""

from __future__ import annotations

from .detector import RegimeConfig, detect_regime, regime_summary

__all__ = ["RegimeConfig", "detect_regime", "regime_summary"]
