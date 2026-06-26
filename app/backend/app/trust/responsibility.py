"""§13 信任层 · ResponsibilityDisclosureRecord —— 责任边界披露 + user 承担风险留痕（greenfield）。

GOAL §13「responsibility boundary disclosure」+「User 选择承担风险后，系统继续交付，并把选择
写入 MethodologyChoiceRecord / ResponsibilityDisclosureRecord」。本记录补 ResponsibilityDisclosureRecord
这一块 —— 全仓 `delivery/rdp.py` 只 string-ref 引它（`responsibility_disclosure_refs`）、尚无类（grep 实证）。

为什么是新记录而非塞进 spine.py（扩展不替换 + 单一身份源 S4）：
- 卡领地 = 新 `app/backend/app/trust/`，**绝不碰**被收编模块（spine.py）内部；ResponsibilityDisclosureRecord
  在 trust/ greenfield 新建。
- 身份仍走唯一源：`disclosure_id = "rdr_" + ids.content_hash(...)`，复用 `lineage.ids`，绝不另造哈希族。
- 与 `MethodologyChoiceRecord` **互补不重复**：MCR 记「方法学松紧选了哪档 + 该档责任边界」；本记录记
  「user 对一次具体交付/动作明示承担了哪些风险 + 系统给的推荐/代价/替代/责任边界」，可经
  `methodology_choice_ref` 钉到一条 MCR.choice_id（复用不复制其内容）。

诚实边界（这条记录**不**做什么）：它只是「责任归属的留痕容器」。
- 它**不**授予任何强度标签（强标签仍走 spine_gate / methodology 控制面）。
- 它**不**解除任何安全不变量（secret / OrderGuard / kill switch / no-silent-mock）—— user 可为研究松紧
  自负其责，但安全不变量不在可弃权域（§13 命门，由 `trust_constraints` 的 waiver-safety 边界门强制）。
  一条 ResponsibilityDisclosureRecord 即便写满 user 承担风险，也绝不让安全不变量被 waiver 绕过。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..lineage.ids import content_hash

__all__ = ["ResponsibilityDisclosureRecord"]


@dataclass(frozen=True)
class ResponsibilityDisclosureRecord:
    """§13 ResponsibilityDisclosureRecord —— 一次「user 知情承担风险」的责任边界留痕。

    字段语义（照 §13「Agent 给推荐、代价、替代路径和责任边界，不替 user 决定」）：
    - `boundary`：责任边界（系统做什么 / user 自担什么）。
    - `risk_owner`：风险归属（谁承担 —— 明确写死，不含糊）。
    - `user_accepted_risk` + `accepted_risks`：user 是否明示承担 + 具体承担了哪些风险项。
    - `recommendation` / `alternatives` / `costs_disclosed`：系统给的推荐 / 替代路径 / 代价（披露给 user 知情选）。
    - `methodology_choice_ref`：钉到一条 `MethodologyChoiceRecord.choice_id`（复用·不复制 MCR 内容）。
    - `actor`：发起者。承担风险的【决定】须由 user 拍（actor=user）—— 若 actor=agent/system，
      撞 §13「Agent 替 user 拍板风险选择 → 拒」（由 `trust_constraints.check_user_autonomy` 守）。

    `disclosure_id` 内容寻址（`rdr_` + content_hash）：同样的责任披露逐字节同 id；改边界/风险归属即变 id。
    """

    asset_ref: str
    boundary: str = ""
    risk_owner: str = ""
    user_accepted_risk: bool = False
    accepted_risks: tuple[str, ...] = ()
    recommendation: str = ""
    alternatives: tuple[str, ...] = ()
    costs_disclosed: tuple[str, ...] = ()
    methodology_choice_ref: str = ""
    run_ref: str = ""
    actor: str = ""
    timestamp: str = ""
    disclosure_id: str = ""

    def __post_init__(self) -> None:
        if not self.disclosure_id:
            object.__setattr__(
                self,
                "disclosure_id",
                "rdr_"
                + content_hash(
                    {
                        "asset_ref": self.asset_ref,
                        "boundary": self.boundary,
                        "risk_owner": self.risk_owner,
                        "accepted_risks": list(self.accepted_risks),
                        "run_ref": self.run_ref,
                        "actor": self.actor,
                    }
                ),
            )

    @property
    def is_complete(self) -> bool:
        """一条「可凭信」的责任披露须齐：明示承担 + 责任边界 + 风险归属 + ≥1 条具体风险。

        缺任一 = 责任归属说不清，§13「user 承担风险但缺 ResponsibilityDisclosureRecord → 拒」的诚实底线
        （空壳记录不算数）。
        """

        return (
            self.user_accepted_risk
            and bool(self.boundary.strip())
            and bool(self.risk_owner.strip())
            and len(self.accepted_risks) > 0
        )

    def missing_fields(self) -> tuple[str, ...]:
        """列出使 `is_complete` 为假的缺失字段（供门给诚实的「缺什么」诊断）。"""

        miss: list[str] = []
        if not self.user_accepted_risk:
            miss.append("user_accepted_risk")
        if not self.boundary.strip():
            miss.append("boundary")
        if not self.risk_owner.strip():
            miss.append("risk_owner")
        if not self.accepted_risks:
            miss.append("accepted_risks")
        return tuple(miss)
