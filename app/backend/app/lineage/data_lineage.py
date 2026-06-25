"""脊柱 · data 级谱系（dataset 来源指纹 + dataset→factor 可追溯）。

为什么单开这一层（卡 B-VERSION-1 余 · GOAL §11「lineage」字段）：
- 既有 ``spine.py`` 是 **strategy 级**谱系（理论/实现/一致性 —— MathematicalArtifact /
  TheoryImplementationBinding / ConsistencyCheck），回答「这段实现是否按理论」。
- 但 GOAL §11「每次数据更新记录」要求的 ``lineage`` 是 **data 级**：一个 ``dataset_version``
  从哪个源、哪个 IngestionSkill 版本、哪些上游 dataset 派生而来，以及它向下游连到哪些
  factor。这一层此前缺位（0430cd78 完成记录诚实残余 ③）。本模块补上，与 spine.py **正交并存**。

身份单一源（决策 S1/S4 + RULES.project「身份源 ids.py 不另造」）：
``lineage_id`` / ``edge_id`` 全走 ``ids.content_hash``（16 位内容寻址族），**绝不**另造哈希。
同一 (dataset_id, version, checksum, source, skill, upstream) → 同一 lineage_id（内容寻址、
可事后对账「我引用的那条 data 谱系是不是同一个」）。

诚实边界：本模块只建【内容寻址的谱系节点/边】容器——
- **不**证明数据正确、**不**做 schema-drift / freshness 检测（那是 data_quality 的 GE/freshness
  与上游 IngestionSkill 的活）；
- dataset→factor 边只表达「这个 factor 绑定在这个 dataset_version 上」（复用 FactorBinding
  的 (factor_id, dataset_id, dataset_version) 三元组），**不**声称该 factor 数值正确。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .ids import content_hash

# 内容寻址 id 前缀（与 spine.py 的 math_/tib_/cc_ 同风格，便于跨账区分谱系世代）。
DATA_LINEAGE_PREFIX = "dlin_"
DATA_FACTOR_EDGE_PREFIX = "dfe_"


@dataclass(frozen=True)
class DatasetLineageNode:
    """一个 ``dataset_version`` 的 data 级谱系节点（来源指纹 + 上游引用）。

    身份字段（dataset_id / dataset_version / checksum）缺一即不可建谱系（数据无身份谈不上
    来源可追溯）→ 直接 raise。``lineage_id`` 内容寻址，由 ``ids.content_hash`` 派生、恒在场。
    """

    dataset_id: str
    dataset_version: str
    checksum: str
    source_ref: str | None = None
    ingestion_skill_version: str | None = None
    upstream: tuple[str, ...] = ()  # 上游 dataset 的 lineage_id / version_id 引用（派生数据集用）
    lineage_id: str = ""

    def __post_init__(self) -> None:
        if not (self.dataset_id and self.dataset_version and self.checksum):
            raise ValueError(
                "DatasetLineageNode 需要 dataset_id / dataset_version / checksum"
                "（数据缺身份不可建 data 级谱系）"
            )
        if not self.lineage_id:
            object.__setattr__(
                self,
                "lineage_id",
                DATA_LINEAGE_PREFIX
                + content_hash(
                    {
                        "dataset_id": self.dataset_id,
                        "dataset_version": self.dataset_version,
                        "checksum": self.checksum,
                        "source_ref": self.source_ref,
                        "ingestion_skill_version": self.ingestion_skill_version,
                        "upstream": sorted(self.upstream),  # 顺序无关 → 同一上游集合同一 id
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "checksum": self.checksum,
            "source_ref": self.source_ref,
            "ingestion_skill_version": self.ingestion_skill_version,
            "upstream": list(self.upstream),
        }


@dataclass(frozen=True)
class DataToFactorEdge:
    """data→factor 谱系边：把一个 ``dataset_version`` 连到下游 ``factor_id``。

    复用 FactorBinding 的 (factor_id, dataset_id, dataset_version) 维度——同一 factor 表达式在
    不同 dataset_version 上是不同的因子，故边必须带满三元组才能无歧义追溯。
    """

    lineage_id: str        # 上游 dataset 谱系节点 id
    dataset_id: str
    dataset_version: str
    factor_id: str
    edge_id: str = ""

    def __post_init__(self) -> None:
        if not (self.lineage_id and self.dataset_id and self.dataset_version and self.factor_id):
            raise ValueError("DataToFactorEdge 需要 lineage_id / dataset_id / dataset_version / factor_id")
        if not self.edge_id:
            object.__setattr__(
                self,
                "edge_id",
                DATA_FACTOR_EDGE_PREFIX
                + content_hash(
                    {
                        "lineage_id": self.lineage_id,
                        "dataset_id": self.dataset_id,
                        "dataset_version": self.dataset_version,
                        "factor_id": self.factor_id,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "lineage_id": self.lineage_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "factor_id": self.factor_id,
        }


def derive_dataset_lineage(
    *,
    dataset_id: str,
    dataset_version: str,
    checksum: str,
    source_ref: str | None = None,
    ingestion_skill_version: str | None = None,
    upstream: Iterable[str] = (),
) -> DatasetLineageNode:
    """从一个 dataset_version 的身份 + 来源派生 data 级谱系节点（内容寻址·恒可派生）。

    register 每次落账都调它 → 每个 DatasetVersion 恒带 lineage_id（满足 §16「缺 lineage 即停」：
    lineage 是身份的派生属性、不可能缺，无须额外拒绝路径）。
    """

    return DatasetLineageNode(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        checksum=checksum,
        source_ref=source_ref,
        ingestion_skill_version=ingestion_skill_version,
        upstream=tuple(upstream or ()),
    )


def trace_dataset_to_factors(
    node: DatasetLineageNode,
    factor_bindings: Iterable[Any],
) -> list[DataToFactorEdge]:
    """给定 data 级谱系节点 + 一组 FactorBinding，产出 dataset→factor 谱系边（可追溯）。

    ``factor_bindings`` 任意暴露 ``factor_id / dataset_id / dataset_version`` 的对象皆可
    （FactorBinding 满足；鸭子类型避免硬耦合 data_hash 包）。只连 dataset_id ∧ dataset_version
    **都匹配**本节点的 binding——换数据集版本即是另一个因子，绝不误连。
    """

    edges: list[DataToFactorEdge] = []
    for b in factor_bindings:
        if (
            getattr(b, "dataset_id", None) == node.dataset_id
            and getattr(b, "dataset_version", None) == node.dataset_version
        ):
            edges.append(
                DataToFactorEdge(
                    lineage_id=node.lineage_id,
                    dataset_id=node.dataset_id,
                    dataset_version=node.dataset_version,
                    factor_id=getattr(b, "factor_id"),
                )
            )
    return edges


__all__ = [
    "DATA_FACTOR_EDGE_PREFIX",
    "DATA_LINEAGE_PREFIX",
    "DataToFactorEdge",
    "DatasetLineageNode",
    "derive_dataset_lineage",
    "trace_dataset_to_factors",
]
