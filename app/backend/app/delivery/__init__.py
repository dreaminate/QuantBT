"""交付层 · Research Delivery Package（RDP）schema + 4 拒绝门（GOAL §17 北极星总闸）。

正式研究交付 = 开放格式 RDP。任何正式因子/模型/信号/StrategyBook 晋级都必须能追溯到一套 RDP，
且 RDP 必须过 §17 的 4 条拒绝门（缺 manifest/artifact hash/reproducibility command、缺
DatasetVersion/IngestionSkill、缺未验证残余、晋级追不到 RDP —— 任一即拒）。

单一身份源（RULES.project）：rdp_id 复用 `lineage.ids.content_hash`，不另造哈希族。
"""

from __future__ import annotations

from .rdp import (
    ASSET_FACTOR,
    ASSET_KINDS,
    ASSET_MODEL,
    ASSET_SIGNAL,
    ASSET_STRATEGYBOOK,
    RDP_SCHEMA_VERSION,
    DatasetVersionRef,
    PromotionClaim,
    RDPManifest,
)
from .rdp_gate import (
    GATE_DATASET_LINEAGE,
    GATE_MANIFEST,
    GATE_PROMOTION_TRACEABILITY,
    GATE_UNVERIFIED_RESIDUAL,
    RDPGateOutcome,
    RDPRejected,
    RDPValidation,
    assemble_rdp,
    gate_dataset_lineage,
    gate_manifest_completeness,
    gate_promotion_traceability,
    gate_unverified_residual,
    require_promotion_rdp,
    require_valid_rdp,
    validate_rdp,
)

__all__ = [
    # schema
    "RDP_SCHEMA_VERSION",
    "ASSET_KINDS",
    "ASSET_FACTOR",
    "ASSET_MODEL",
    "ASSET_SIGNAL",
    "ASSET_STRATEGYBOOK",
    "DatasetVersionRef",
    "PromotionClaim",
    "RDPManifest",
    # gates
    "GATE_MANIFEST",
    "GATE_DATASET_LINEAGE",
    "GATE_UNVERIFIED_RESIDUAL",
    "GATE_PROMOTION_TRACEABILITY",
    "RDPGateOutcome",
    "RDPValidation",
    "RDPRejected",
    "gate_manifest_completeness",
    "gate_dataset_lineage",
    "gate_unverified_residual",
    "gate_promotion_traceability",
    "validate_rdp",
    "require_valid_rdp",
    "assemble_rdp",
    "require_promotion_rdp",
]
