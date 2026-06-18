"""VerdictRecord · 部件12 验证官产物（C9 / spine 04 §3.3 ConsistencyReview）。

字段名权威收敛为 `verdict_id`（00 §1.2-G 裁定；06/07 的 `verification_record_id` 是同物别名）。
裁决措辞铁律（R7 / 00 §1.2-G / T-DET-10）：只说证据【一致/存疑/不一致】+ 适用域 + 未验证项；
**禁**「组织独立 / independent validation / 可信 / 安全 / 保证 / 可复现 / reproducible」。
诚实声明：单主体下的『第二双眼睛』是【非组织独立】验证；独立性按 `independence` 字段被【度量】而非假定
（06 §7-4：验证官与生成方可能共享低困惑度盲点，self-preference 是熟悉度非身份）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ..lineage.ids import content_hash

# 三态裁决（与 04 §3.3 ConsistencyReview.verdict 一致）：
#   consistent = 异模型重算一致（且独立性已度量成立）；concern = 存疑（差异在容差边缘/独立性未确立/部分未复算）；
#   blocked    = 异模型不一致（符号翻转或超容差）——**有权 BLOCK**，下游 freeze/promote 不得当 pass。
Verdict = Literal["consistent", "concern", "blocked"]

# 裁决文案诚实声明（措辞守门）。刻意不含「可信/安全/保证/可复现/reproducible/组织独立(无非前缀)」。
DISCLOSURE = (
    "本记录是【异模型一致性检查 consistency_check】：用不同模型/种子/数据切片对生成方自报值做挑战式重算。"
    "结论只陈述证据【一致 / 存疑 / 不一致】+ 适用域 + 未验证项，不对结论本身下任何定性判断。"
    "诚实声明：这是单主体下的『第二双眼睛』，属【非组织独立】验证；验证官与生成方可能共享低困惑度盲点"
    "（self-preference 是熟悉度而非身份），故独立性以 independence 字段被【度量】而非假定。"
)


class VerifierError(Exception):
    """验证官输入非法（无可对账的声明/缺生成方标识等）。"""


class VerdictTamperError(Exception):
    """落盘裁决被篡改：重算 verdict_id 与存量不符（读路径==被核验路径，绝不返脏数据）。"""


@dataclass(frozen=True)
class ClaimCheck:
    """单个数值声明的对账行。"""

    key: str
    claimed: float | None          # 生成方自报值（None = 生成方未报但验证官算了）
    recomputed: float | None       # 验证官异模型重算值（None = 未能复算）
    abs_diff: float | None
    within_tol: bool
    status: Literal["match", "mismatch", "sign_flip", "unverified"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Independence:
    """独立性【度量】（06 §7-4 / open-Q#4：度量而非假定）。

    model_differs 为假 → 独立性未确立：验证官与生成方共用同一模型，可能共享盲点 → consistent 降为 concern。
    """

    model_differs: bool
    seed_differs: bool
    slice_differs: bool
    axes: int                      # 上述为真的轴数（0=完全同源，3=模型/种子/切片皆异）
    established: bool              # 独立性是否成立（至少 model_differs）
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerdictRecord:
    """验证官裁决记录（content-addressed，verdict_id 为主键）。"""

    verdict_id: str
    target_ref: str                # 被复核对象引用（config_hash / card_id / claim ref）
    generator_model: str
    checker_model: str
    verdict: Verdict
    consistency_check: list[ClaimCheck]
    independence: Independence
    disclosure: str = DISCLOSURE
    replay_ref: str | None = None  # 部件11/01 fixture node_id（R11，重放读它不重跑 LLM）
    notes: str = ""
    created_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def to_review(self) -> dict[str, Any]:
        """投影成 04 §3.3 ConsistencyReview / T-017 卡 review 字段消费的形状。

        T-017 freeze 读 review['verdict']（blocked→拒、concern→needs_review）与 review['notes']。
        """

        return {
            "verdict_id": self.verdict_id,
            "target_ref": self.target_ref,   # 复核 #1：下游须校验 target_ref 绑定（防张冠李戴）
            "checker_model": self.checker_model,
            "verdict": self.verdict,
            "replay_ref": self.replay_ref,
            "consistency_check": [c.to_dict() for c in self.consistency_check],
            "independence": self.independence.to_dict(),
            "notes": self.notes,
            "disclosure": self.disclosure,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "VerdictRecord":
        cc = [ClaimCheck(**c) for c in row.get("consistency_check", [])]
        ind = row.get("independence") or {}
        return cls(
            verdict_id=row["verdict_id"],
            target_ref=row["target_ref"],
            generator_model=row["generator_model"],
            checker_model=row["checker_model"],
            verdict=row["verdict"],
            consistency_check=cc,
            independence=Independence(**ind) if ind else Independence(False, False, False, 0, False, ""),
            disclosure=row.get("disclosure", DISCLOSURE),
            replay_ref=row.get("replay_ref"),
            notes=row.get("notes", ""),
            created_at_utc=row.get("created_at_utc", ""),
        )


def _claim_dicts(checks: Any) -> list[dict[str, Any]]:
    return [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in checks]


def _ind_dict(ind: Any) -> dict[str, Any]:
    return ind.to_dict() if hasattr(ind, "to_dict") else dict(ind)


def compute_verdict_id(
    *,
    target_ref: str,
    generator_model: str,
    checker_model: str,
    verdict: str,
    consistency_check: Any,
    independence: Any,
    replay_ref: str | None,
) -> str:
    """裁决主键 = content-addressed（覆盖 target_ref/双模型/裁决/逐项对账/独立性/replay_ref）。

    **唯一**的 id 计算口径：mint（verifier.reconcile）与 read-path 完整性校验（store）都走这里，
    杜绝两处口径漂移导致「自证」式校验。target_ref 入哈希 → 裁决与被审工件绑定（复核 #1）。
    """

    payload = {
        "target_ref": target_ref,
        "generator_model": generator_model,
        "checker_model": checker_model,
        "verdict": verdict,
        "consistency_check": _claim_dicts(consistency_check),
        "independence": _ind_dict(independence),
        "replay_ref": replay_ref,
    }
    return "vd_" + content_hash(payload)


def verdict_id_of(rec: "VerdictRecord") -> str:
    """从一条 VerdictRecord 重算其 verdict_id（store 完整性校验用）。"""

    return compute_verdict_id(
        target_ref=rec.target_ref, generator_model=rec.generator_model,
        checker_model=rec.checker_model, verdict=rec.verdict,
        consistency_check=rec.consistency_check, independence=rec.independence,
        replay_ref=rec.replay_ref,
    )


__all__ = [
    "Verdict",
    "DISCLOSURE",
    "VerifierError",
    "VerdictTamperError",
    "ClaimCheck",
    "Independence",
    "VerdictRecord",
    "compute_verdict_id",
    "verdict_id_of",
]
