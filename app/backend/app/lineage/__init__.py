"""Agent OS 脊柱 · 谱系/身份地基（第 0 层）。

单一身份源（复用原则 S4）：全脊柱的 node_id / content_hash / config_hash /
canonical_json 只在 `ids.py` 定义一次，01 内核与 03 谱系总线、05 试验账本
一律 import 此处，绝不各自重写（杜绝复核 §1.2-A 抓出的 config_hash 双产方）。
"""

from __future__ import annotations

from .ids import (
    CONFIG_HASH_PREFIX,
    FIXTURE_PREFIX,
    HASH_LEN,
    canonical_json,
    config_hash,
    content_hash,
    fixture_key,
    node_id,
    normalize_factor_ast,
    strip_fixture_prefix,
)
from .ledger import (
    HONEST_N_DISCLOSURE,
    IntegrityReport,
    Ledger,
    LedgerEntry,
)
from .spine import (
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from .spine_binder import (
    code_fingerprint,
    numerical_consistency_check,
    property_consistency_check,
)
from .spine_gate import SpineDecision, evaluate_promotion
from .spine_ledger import SpineLedger

__all__ = [
    "CONFIG_HASH_PREFIX",
    "FIXTURE_PREFIX",
    "HASH_LEN",
    "HONEST_N_DISCLOSURE",
    "IntegrityReport",
    "Ledger",
    "LedgerEntry",
    "canonical_json",
    "config_hash",
    "content_hash",
    "fixture_key",
    "node_id",
    "normalize_factor_ast",
    "strip_fixture_prefix",
    # Mathematical Spine（数学贯穿 + 理论实现一致性硬门 · 决策 D-MATH-SPINE）
    "MathematicalArtifact",
    "TheoryImplementationBinding",
    "ConsistencyCheck",
    "MethodologyChoiceRecord",
    "SpineDecision",
    "evaluate_promotion",
    "SpineLedger",
    "code_fingerprint",
    "numerical_consistency_check",
    "property_consistency_check",
]
