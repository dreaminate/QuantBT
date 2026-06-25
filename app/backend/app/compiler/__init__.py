"""Governed Compiler（GOAL §1 统一对象链 capstone · §7 role agent 受治理 · §8 治理脊柱）。

A-QRO-1 / A-GRAPH-1 / A-CMD 已落 QRO 信封 → Research Graph IR → CanonicalCommand 全栈通道。本包
（A-COMPILER）建链里 `→ Governed Compiler → Deterministic Run → Evidence Verdict → Promotion/Approval`
那一段——**完成 QRO→Graph→Command→Compiler→Run→Verdict 整脊柱**。四段编译管线各**收编只读**一个既有件：
① 消费 canonical command + Research Graph IR；② → deterministic run（收编 `dag.kernel.DurableExecutor`
确定性内核·run 携确定性内核身份）；③ → evidence verdict（收编 `verification.verifier.Verifier` +
`eval.overfit_gate.run_overfit_gate` 三角脊柱门）；④ governs promotion（收编 `approval.gate.ApprovalGateService`
审批门·approver≠creator）。详见 `governed_compiler.py` 模块 docstring。**绝不**另造内核身份/裁决/审批门，
**绝不**接 main.py / 建前端 / 动被收编模块内部（领地外·中心接线）。
"""

from __future__ import annotations

from .governed_compiler import (
    AttestedRun,
    CompiledRun,
    CompileLedger,
    CompileLedgerEntry,
    CompilerError,
    CompilerInputError,
    EvidenceInputs,
    EvidenceVerdictUnfavorable,
    GovernedCompiler,
    KernelIdentityViolation,
    PromotedRun,
    PromotionGovernanceViolation,
    PromotionRequest,
    RunNotCompiledError,
    UncommandedRunError,
    VerdictBook,
    VerdictBypassViolation,
    build_default_compiler,
)

__all__ = [
    "EvidenceInputs",
    "PromotionRequest",
    "CompiledRun",
    "AttestedRun",
    "PromotedRun",
    "CompileLedger",
    "CompileLedgerEntry",
    "VerdictBook",
    "GovernedCompiler",
    "build_default_compiler",
    "CompilerError",
    "CompilerInputError",
    "UncommandedRunError",
    "RunNotCompiledError",
    "KernelIdentityViolation",
    "VerdictBypassViolation",
    "EvidenceVerdictUnfavorable",
    "PromotionGovernanceViolation",
]
