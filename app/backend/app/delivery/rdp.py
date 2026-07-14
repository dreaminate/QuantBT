"""Compatibility vocabulary for the canonical Research Delivery Package.

``RDPManifest`` is defined only in :mod:`app.research_os.rdp`.  Delivery and
release-gate code import that exact class through this module while the two
small reference/claim records remain delivery-specific adapters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..research_os.rdp import DatasetVersionRef, RDPManifest

RDP_SCHEMA_VERSION = "rdp.v3"

ASSET_FACTOR = "factor"
ASSET_MODEL = "model"
ASSET_SIGNAL = "signal"
ASSET_STRATEGYBOOK = "strategybook"
ASSET_KINDS = frozenset({ASSET_FACTOR, ASSET_MODEL, ASSET_SIGNAL, ASSET_STRATEGYBOOK})


@dataclass(frozen=True)
class PromotionClaim:
    asset_ref: str
    asset_kind: str
    rdp_ref: str
    requested_stage: str = ""
    actor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "RDP_SCHEMA_VERSION",
    "ASSET_KINDS",
    "ASSET_FACTOR",
    "ASSET_MODEL",
    "ASSET_SIGNAL",
    "ASSET_STRATEGYBOOK",
    "DatasetVersionRef",
    "PromotionClaim",
    "RDPManifest",
]
