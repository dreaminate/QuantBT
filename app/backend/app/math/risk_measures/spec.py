"""``RiskMeasureSpec`` — typed declaration of a risk measure + measure dispatch.

Turns "which risk measure, at what confidence/method/horizon" from a free-text
``assumptions: str[]`` (the old ``MathematicalArtifact`` container) into a machine-checkable
typed object with a CANONICAL content-addressed identity.

命门 (一致性校验门) is deliberately NOT reimplemented here: the kernel is bound to the canonical
spine in ``spine_binding.py`` (app/lineage/spine.py + spine_binder.py + spine_gate.py), reusing
code-fingerprint / staleness / binding-ownership / canonical promotion — the ``verify_*`` default
records the AUDITED pinned fingerprint so source drift is caught by the gate fresh clause. NOT a
parallel self-certifying gate. Cross-vendor floor ruling (codex): connect at the first slice.

Registered follow-ons (need shared-gate changes → user 拍板, not exploited by this kernel's public
API): (1) spine_gate does not enforce ``binding.theory_ref == artifact.artifact_id`` (a foreign-
theory binding can satisfy the gate); (2) ``ARTIFACT_RISK_MEASURE`` is not in ``PIT_REQUIRING_TYPES``
(this kernel uses ARTIFACT_ESTIMATOR / ARTIFACT_STATISTICAL_TEST so PIT IS enforced here). Both are
PRE-EXISTING in spine_gate (affect all bindings), and the ``verify_*`` wrappers always pair the
matching artifact + PIT-bound binding, so neither hole is reachable through this kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.lineage.ids import content_hash

RiskMeasure = Literal["VaR", "ES"]
RiskMethod = Literal["historical", "parametric_gaussian"]


@dataclass(frozen=True)
class RiskMeasureSpec:
    """Typed declaration of a downside risk measure.

    口径 (methodology decided by the authorized math decider — codex): the kernel FORCES an
    explicit ``confidence`` (no hidden default). ``holding_period_days`` scales a
    parametric measure (i.i.d.); a HISTORICAL measure cannot be horizon-scaled (it would
    distort the empirical distribution), so ``historical`` + ``holding_period_days > 1`` is
    rejected at CONSTRUCTION (fail-fast), not at compute time.
    """

    measure: RiskMeasure
    method: RiskMethod
    confidence: float
    holding_period_days: int = 1

    def __post_init__(self) -> None:
        # Valid-value literals live INLINE here (part of the class source that the spine fingerprint
        # hashes) — a module-level tuple would let a behavior change slip past staleness (codex R8).
        if self.measure not in ("VaR", "ES"):
            raise ValueError(f"measure must be one of ('VaR', 'ES'), got {self.measure!r}")
        if self.method not in ("historical", "parametric_gaussian"):
            raise ValueError(
                f"method must be one of ('historical', 'parametric_gaussian'), got {self.method!r}"
            )
        if not (0.0 < float(self.confidence) < 1.0):
            raise ValueError(f"confidence must be in (0, 1), got {self.confidence}")
        # Accept python int OR numpy integer (matches var_es._check_horizon — the spec and
        # the direct functions must not disagree on np.int64; codex R2 API-consistency catch).
        if isinstance(self.holding_period_days, bool) or not isinstance(
            self.holding_period_days, (int, np.integer)
        ):
            raise ValueError(f"holding_period_days must be an int, got {self.holding_period_days!r}")
        if self.holding_period_days < 1:
            raise ValueError(f"holding_period_days must be >= 1, got {self.holding_period_days}")
        if self.method == "historical" and self.holding_period_days > 1:
            raise ValueError(
                "a historical measure cannot be horizon-scaled (distorts the empirical "
                "distribution) — supply multi-day returns instead of holding_period_days > 1"
            )

    @property
    def spec_id(self) -> str:
        """Canonical content-addressed identity — recomputed from content, never stored or
        externally overridable (single-identity-source red line; codex)."""

        return "riskmeasure_" + content_hash(
            {
                "measure": self.measure,
                "method": self.method,
                "confidence": float(self.confidence),
                "holding_period_days": int(self.holding_period_days),
            }
        )


def compute_measure(spec: RiskMeasureSpec, returns) -> float:
    """Compute the per-``spec`` risk measure (loss units), horizon-aware for parametric."""

    from .var_es import (
        historical_es,
        historical_var,
        parametric_gaussian_es,
        parametric_gaussian_var,
    )

    if spec.method == "historical":
        # holding_period_days == 1 guaranteed by RiskMeasureSpec (fail-fast on > 1).
        fn = historical_var if spec.measure == "VaR" else historical_es
        return fn(returns, spec.confidence)
    fn = parametric_gaussian_var if spec.measure == "VaR" else parametric_gaussian_es
    return fn(returns, spec.confidence, horizon=spec.holding_period_days)
