"""部件12 · 验证官（异模型一致性检查，产 verdict_id）。

spine 04 §3.3 ConsistencyReview + 00 §1.2-G（字段名收敛 verdict_id）+ 06 §7-4（独立性度量非假定）。
生成≠验证（R7）：以不同模型/种子/切片对生成方自报值挑战式重算；异模型不一致即 BLOCK，不取均值。
裁决措辞禁「组织独立 / independent validation / 可信 / 安全 / 保证 / 可复现」。
"""

from .schema import (
    DISCLOSURE,
    ClaimCheck,
    Independence,
    Verdict,
    VerdictRecord,
    VerdictTamperError,
    VerifierError,
    compute_verdict_id,
    verdict_id_of,
)
from .store import VerdictStore
from .verifier import DEFAULT_ATOL, DEFAULT_RTOL, Verifier

__all__ = [
    "DISCLOSURE",
    "ClaimCheck",
    "Independence",
    "Verdict",
    "VerdictRecord",
    "VerdictTamperError",
    "VerifierError",
    "compute_verdict_id",
    "verdict_id_of",
    "VerdictStore",
    "Verifier",
    "DEFAULT_ATOL",
    "DEFAULT_RTOL",
]
