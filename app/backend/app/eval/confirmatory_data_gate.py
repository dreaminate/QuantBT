"""confirmatory 数据身份门（B-PIT-CONFIRMATORY · GOAL §16 line1759 / §6 line1112 / §16 line2028）。

实证背景（RAG 调查 wf_748975d3）：PIT(known_at) / 注册(dataset_version) 机制【已建】——
`data_quality.DatasetRegistry` 写时强约束（缺 dataset_version/checksum/lineage→拒，卡 0430cd78）
+ `field_catalog.load_panel(as_of_known)` 双时态点查（卡 e01bf12f/6a8752ab）。但 **confirmatory
计算路径绕过它**：`eval.gate_runner.evaluate_overfit_gate(record=True)` 与假设卡 `freeze()` 只收一个
裸 `dataset_version` 字符串（默认 ``"unknown"``），**不校验它是否真注册、是否带 PIT known_at**。
于是无 PIT 语义的数据能进 confirmatory validation —— 正是 GOAL §16/§6 明令拒绝的前视红线。

本门补这一段：标 confirmatory 的 run，其 `dataset_version` 必须解析到 `DatasetRegistry` 里一条
【已注册且带 known_at/effective_at(PIT)】的 `DatasetVersion`，否则拒。

边界（扩展不替换·exploratory 不卡·诚实不假装）：
- **单一源复用** `data_quality.DatasetRegistry`（注册身份 + known_at + lineage_id），绝不另造第二本。
- `registry=None` → 无单一源可校验 → **不强制**（返 advisory verdict、不 raise）：既有无 registry 的
  调用（探索 / 单测 / 合成 sample demo）逐字不变，向后兼容、不破基线、不假装过滤。
- 只在 confirmatory（`record=True` / 假设卡冻结）触发；exploratory（`record=False`）与合成 sample
  demo 路完全不受影响（GOAL §16「合成 sample 仅 demo/exploratory 不强制」）。
- 诚实限界：本门校验【声明的 dataset_version 身份】是否注册 + 带 PIT，不对 returns 与该数据做
  逐字节内容绑定（那是更深的 content-addressing，超出本门）；它把 confirmatory 数据从「`unknown`
  / 未注册 / 无 known_at 一律放行」抬到「必须可追溯到注册 PIT 数据集」。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data_quality import DatasetRegistry

# confirmatory 边界门是否默认强制（registry 在场时）。单点可逆：中心整合跑全量后若某未注册
# 生产 confirmatory 路径破基线 → 翻 False 全局回退 advisory（无需改门 / 改调用点）。
# 🟡 默认 True【待中心全量验证 + main.py 端点接 DATASET_REGISTRY 激活】：本卡只在库层 funnel
# （evaluate_overfit_gate / 假设卡 freeze）接 opt-in registry 并以对抗测试钉死，绝不声称全量绿。
ENFORCE_CONFIRMATORY_PIT_DEFAULT = True

# 占位 / 缺省 dataset_version 黑名单：这些都不是真注册身份（§16 line2028 缺 dataset_version=致命）。
# 给出比「未注册」更精确的诊断；真 version_id（make_version_id = 时间戳__sha）绝不长这样。
_PLACEHOLDER_VERSIONS = frozenset({"", "unknown", "none", "null", "na", "n/a"})


class ConfirmatoryDataRejected(Exception):
    """confirmatory run 的数据缺 PIT(known_at) / 缺注册身份(dataset_version) → 拒（look-ahead 红线）。"""


@dataclass
class ConfirmatoryDataVerdict:
    """confirmatory 数据身份裁决（诚实措辞：只说证据充分/不足 + 缺什么，不渲染「可信/安全」）。"""

    allow: bool
    enforced: bool           # True=registry 在场且启用、真做了校验；False=无源/未启用→advisory
    dataset_version: str
    reason: str
    known_at: str | None = None
    effective_at: str | None = None
    lineage_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def check_confirmatory_data(
    dataset_version: str | None,
    *,
    registry: "DatasetRegistry | None",
    enforce: bool = ENFORCE_CONFIRMATORY_PIT_DEFAULT,
) -> ConfirmatoryDataVerdict:
    """纯校验（**不 raise**）：confirmatory 数据是否带注册身份 + PIT(known_at)。

    放行(allow=True) 条件（enforce 且 registry 在场）：``dataset_version`` 非占位 + 解析到 registry
    一条 ``DatasetVersion`` + 该 version 带 ``known_at_utc`` 或 ``effective_at_utc``（PIT 语义在场）。

    ``registry=None`` 或 ``enforce=False`` → ``enforced=False``、``allow=True``、reason 标 advisory
    （无单一源不假装过滤；向后兼容）。
    """

    dv = (dataset_version or "").strip()

    # 无单一源 / 未启用 → 不强制（诚实 advisory，绝不假装做了过滤）。
    if registry is None or not enforce:
        why = (
            "未接 DatasetRegistry 单一源，无法校验 confirmatory 数据 PIT/注册身份（advisory·不强制）"
            if registry is None
            else "confirmatory PIT 门未启用（enforce=False·advisory）"
        )
        return ConfirmatoryDataVerdict(
            allow=True, enforced=False, dataset_version=dv, reason=why
        )

    # ① 缺 / 占位 dataset_version = 无注册身份（§16 line2028 缺 dataset_version / lineage = 致命）。
    if dv.lower() in _PLACEHOLDER_VERSIONS:
        return ConfirmatoryDataVerdict(
            allow=False, enforced=True, dataset_version=dv,
            reason=f"confirmatory 数据缺注册身份 dataset_version（得到占位值 {dv!r}）；"
                   "无 dataset_version/lineage 不得进 confirmatory（GOAL §16 line2028）",
        )

    # ② dataset_version 必须解析到 registry 一条【已注册】version（注册身份 + checksum + lineage 可追溯）。
    version = registry.find_version(dv)
    if version is None:
        return ConfirmatoryDataVerdict(
            allow=False, enforced=True, dataset_version=dv,
            reason=f"dataset_version={dv!r} 未在 DatasetRegistry 注册：confirmatory 晋级资产须可追溯"
                   "（注册身份 + checksum + lineage，GOAL §16 line2028）",
        )

    # ③ 注册的 version 必须带 PIT(known_at / effective_at) 语义（§16 line1759 / §6 line1112）。
    known_at = version.known_at_utc
    effective_at = version.effective_at_utc
    if not known_at and not effective_at:
        return ConfirmatoryDataVerdict(
            allow=False, enforced=True, dataset_version=dv,
            reason=f"dataset_version={dv!r} 已注册但无 PIT 语义（known_at/effective_at 均空）："
                   "无 PIT 语义数据进 confirmatory validation = 前视（GOAL §16 line1759 / §6 line1112）",
            lineage_id=version.lineage_id,
        )

    return ConfirmatoryDataVerdict(
        allow=True, enforced=True, dataset_version=dv,
        reason="confirmatory 数据带注册身份 + PIT(known_at) 语义（放行·不误伤正路径）",
        known_at=known_at, effective_at=effective_at, lineage_id=version.lineage_id,
    )


def require_confirmatory_data(
    dataset_version: str | None,
    *,
    registry: "DatasetRegistry | None",
    enforce: bool = ENFORCE_CONFIRMATORY_PIT_DEFAULT,
    context: str = "confirmatory run",
) -> ConfirmatoryDataVerdict:
    """校验并在不放行时 **raise** ``ConfirmatoryDataRejected``（confirmatory 边界硬门入口）。

    放行（含 advisory）返 verdict；拒则 raise（措辞带 context + 诚实原因）。调用方应在【任何记账 /
    冻结副作用之前】调本函数——拒则不落账、不冻结（append-only 一本账不可撤、冻结只读不可改）。
    """

    verdict = check_confirmatory_data(dataset_version, registry=registry, enforce=enforce)
    if not verdict.allow:
        raise ConfirmatoryDataRejected(f"[{context}] {verdict.reason}")
    return verdict


__all__ = [
    "ENFORCE_CONFIRMATORY_PIT_DEFAULT",
    "ConfirmatoryDataRejected",
    "ConfirmatoryDataVerdict",
    "check_confirmatory_data",
    "require_confirmatory_data",
]
