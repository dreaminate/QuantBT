"""不可信摄入隔离（INV-1 Rule of Two）+ 验证官 attestation 消费（T-018 / spine 06）。

能下单的会话默认禁止摄入不可信内容；摄入放进无工具子 agent，只回传【类型受约束 + 合理性区间/异常
检测】的结构化结果。dossier §8.3：决策值语义投毒（signal_score=99）对量化下单比控制流注入更致命。
验证官（部件12=T-020）裁决权威；本处只消费 attestation 并诚实标注【非组织独立】（R7）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 验证官措辞铁律（R7）：禁「组织独立 / independent validation」。
VERIFIER_DISCLOSURE = "异模型一致性检查（consistency_check），非组织独立验证；独立性需被度量、不可假定。"


@dataclass
class IngestResult:
    value: dict[str, Any]
    trust: str = "untrusted"                 # 摄入内容默认不可信
    anomaly_flags: list[str] = field(default_factory=list)

    @property
    def can_drive_go_live(self) -> bool:
        # 不可信 + 有异常旗标 → 单独不能驱动 go_live（需验证官交叉）。
        return self.trust == "trusted" and not self.anomaly_flags


def sanity_check(value: dict[str, Any], ranges: dict[str, tuple[float, float]] | None = None) -> list[str]:
    """合理性区间 + 离群检测。范围外/被诱导的离群决策值 → poison_suspect 旗标。"""

    flags: list[str] = []
    ranges = ranges or {"signal_score": (-3.0, 3.0), "sentiment": (-1.0, 1.0), "weight": (-1.0, 1.0)}
    for k, (lo, hi) in ranges.items():
        if k in value:
            try:
                v = float(value[k])
            except (TypeError, ValueError):
                flags.append(f"non_numeric:{k}")
                continue
            if v < lo or v > hi:
                flags.append("poison_suspect")
    return flags


def isolated_ingest(value: dict[str, Any], ranges: dict[str, tuple[float, float]] | None = None) -> IngestResult:
    """把（已由无工具子 agent 抽取的）结构化结果过合理性检测，标 trust=untrusted。"""

    return IngestResult(value=value, trust="untrusted", anomaly_flags=sanity_check(value, ranges))


@dataclass
class Attestation:
    """来自试验账本/验证官的 go_live 前置证明（本部件只读、不自算 DSR/PBO）。"""

    passed: bool
    verdict_id: str = ""
    checker_model: str = ""
    note: str = ""

    def consume(self) -> tuple[bool, str]:
        """返回 (是否放行前置, 诚实措辞)。措辞必含「非组织独立」（R7）。"""

        return self.passed, f"{VERIFIER_DISCLOSURE} verdict_id={self.verdict_id} checker={self.checker_model}"


__all__ = ["Attestation", "IngestResult", "VERIFIER_DISCLOSURE", "isolated_ingest", "sanity_check"]
