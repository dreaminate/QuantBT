"""Financial-math kernel (P0-A onward).

The typed computational math layer the seam analysis
(dev/research/findings/dreaminate/math-kernel-seam-matrix-20260716.md) identified as
the real gap: the existing spine provides the governance/binding layer
(``MathematicalArtifact`` text specs + ``ConsistencyCheck`` + ``TheoryImplementationBinding``),
while the actual computational math was scattered across ``app/eval|models|portfolio``.
This package holds the unified, typed, oracle-tested kernel — each thin vertical slice
lands a typed object family + a numerical implementation + an oracle golden test
together (never schema-only, or it becomes a second governance-text layer).

First slice (P0-A #1): ``risk_measures`` — VaR / ES market-risk engine.
"""
