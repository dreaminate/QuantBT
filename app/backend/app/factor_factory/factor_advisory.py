"""④ 因子健康**只读呈现**面板（卡 aa13c3b0 · §3 度量接生产路径）。

聚合 advisory 度量（衰减诊断 / 容量示意 / 拥挤定性咨询）供 **UI / 监控呈现**。这是「拥挤→仅呈现层咨询」
的**呈现端**：拥挤等度量进**呈现**、绝不进 sizing 减仓路径。

**结构红线（机器钉死）**：本面板**无任何减仓/动作字段**（reduce_position/haircut/multiplier/target_weight/
position/weight/size/order）——与 `lifecycle_metrics.CrowdingAdvisory` 同纪律（GOAL §3 / R19 禁自动减仓）。
与 sizing 的**类型层隔离**：`portfolio.capacity_sizing` 签名无 crowding 入参且运行期拒 `CrowdingAdvisory`；
本面板**接** crowding 作只读呈现——「**呈现接、sizing 拒**」即类型层隔离守住。

与 `factor_audit.FactorAuditReport`（晋级期过拟合三角：DSR/PBO/N_eff/IC/bootstrap）**用途不同、字段不重叠**：
那是 gatekeeper 过拟合裁决，本面板是**生命周期诊断**（衰减/容量/拥挤）的呈现聚合。

**缺数据显式呈现、绝不空白冒充健康**：decay=None→'no_history'、capacity invalid→显式标、crowding 数据不足→
insufficient（由度量自身保证）。镜像「missing≠none / missing≠健康」。
"""

from __future__ import annotations

from dataclasses import dataclass

from .lifecycle_metrics import CapacityEstimate, CrowdingAdvisory, DecayEstimate


@dataclass(frozen=True)
class FactorAdvisoryReport:
    """单因子健康呈现聚合（**只读咨询**·绝无动作字段）。三件 advisory 度量任一可缺（显式 None/insufficient）。"""

    factor_id: str
    decay: DecayEstimate | None = None        # IC 持久性 AR(1) 诊断（advisory·不硬退役）；None=无观测历史
    capacity: CapacityEstimate | None = None  # 容量**示意**（绝不在此缩仓；硬上限由 capacity_sizing 单独管）
    crowding: CrowdingAdvisory | None = None  # 拥挤定性咨询（绝不自动减仓）

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id,
            "decay": self.decay.to_dict() if self.decay is not None else {"status": "no_history"},
            "capacity": self.capacity.to_dict() if self.capacity is not None else {"status": "absent"},
            "crowding": self.crowding.to_dict() if self.crowding is not None else {
                "level": "none", "data_status": "absent",
            },
        }


def factor_advisory_report(
    factor_id: str,
    *,
    decay: DecayEstimate | None = None,
    capacity: CapacityEstimate | None = None,
    crowding: CrowdingAdvisory | None = None,
) -> FactorAdvisoryReport:
    """组装因子健康呈现面板（纯聚合·只读·无副作用·无动作）。"""

    return FactorAdvisoryReport(factor_id=factor_id, decay=decay, capacity=capacity, crowding=crowding)


__all__ = ["FactorAdvisoryReport", "factor_advisory_report"]
