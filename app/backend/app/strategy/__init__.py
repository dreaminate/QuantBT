"""A4 · 策略台后端模块（候选池 handoff，止于模拟盘）。"""

from .candidate_pool import CandidatePoolStore, HandoffRejected

__all__ = ["CandidatePoolStore", "HandoffRejected"]
