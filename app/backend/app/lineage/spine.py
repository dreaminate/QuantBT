"""脊柱 · Mathematical Spine 数据模型（GOAL §6 字段契约）。

数学贯穿全流程（决策 D-MATH-SPINE）：数据时间语义、因子、标签、模型、信号、组合、
执行成本、保证金、回测估计、归因、监控触发器，凡声称「按理论实现」都要产出
`MathematicalArtifact / TheoryImplementationBinding / ConsistencyCheck`，并由
`spine_gate.evaluate_promotion` 这道一致性硬门裁定能否升级到强标签。

为什么字段照 §6 全含、id 走 `ids.content_hash`：
- §6 列了每个产物的「必须包含」字段集——少一个就接不住对应的「→ 拒」门。
- 身份只有一个源（`ids.py`，决策 S1/S4）。artifact_id / binding_id / check_id 全是
  内容寻址指纹，**绝不**另造哈希族。改实现源 → code_content_hash 变 → staleness 门必抓。

诚实边界：本模块只是「容器 + 内容寻址身份」。它**不**判定 code 是否真的实现了
definition——那是 ConsistencyCheck 的内容 + Verifier/Critic 的活；本模块绝不声称证明了
任何下游数学命题。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ids import content_hash

# ── 证明强度（数学产物自身的理论成熟度）─────────────────────────────────────
PROOF_UNPROVEN = "unproven"
PROOF_SKETCH = "proof_sketch"
PROOF_BACKED = "proof_backed"
PROOF_STATES = frozenset({PROOF_UNPROVEN, PROOF_SKETCH, PROOF_BACKED})

# ── 升级标签阶梯（产物对外展示口径）─────────────────────────────────────────
# 弱/诚实标签：永远可授（它们不越权，如实陈述「还没证 / 用户跳过」）。
LABEL_DRAFT = "draft"
LABEL_EXPLORATORY = "exploratory"
LABEL_CHALLENGED = "challenged"
LABEL_USER_WAIVED_THEORY = "user_waived_theory"
LABEL_USER_WAIVED_VALIDATION = "user_waived_validation"
LABEL_CUSTOM_METHODOLOGY = "custom_methodology"
# 强标签：越权空间所在，必须过一致性门全部必需子句。
LABEL_EVIDENCE_SUFFICIENT = "evidence_sufficient"
LABEL_PROOF_BACKED = "proof_backed"
LABEL_PRODUCTION_READY = "production_ready"

STRONG_LABELS = frozenset(
    {LABEL_EVIDENCE_SUFFICIENT, LABEL_PROOF_BACKED, LABEL_PRODUCTION_READY}
)
# 需要「理论真的被证明」的标签子集（waiver / proof_status 诚实门作用于这些）。
PROOF_REQUIRING_LABELS = frozenset({LABEL_PROOF_BACKED, LABEL_PRODUCTION_READY})
WAIVER_LABELS = frozenset(
    {LABEL_USER_WAIVED_THEORY, LABEL_USER_WAIVED_VALIDATION, LABEL_CUSTOM_METHODOLOGY,
     LABEL_EXPLORATORY}
)

# ── 数学产物类型（§6；带 PIT 时间义务的子集见 spine_gate.PIT_REQUIRING_TYPES）──
ARTIFACT_ESTIMATOR = "estimator"
ARTIFACT_STATISTICAL_TEST = "statistical_test"
ARTIFACT_DATA_TIMING = "data_timing"
ARTIFACT_FACTOR_FORMULA = "factor_formula"
ARTIFACT_LOSS = "loss_function"
ARTIFACT_RISK_MEASURE = "risk_measure"
ARTIFACT_MONITOR_TRIGGER = "monitor_trigger"
ARTIFACT_EXECUTION_COST = "execution_cost"

# ── ConsistencyCheck 类型（§6）──────────────────────────────────────────────
CHECK_TYPES = frozenset(
    {"symbolic", "dimensional", "property", "numerical", "simulation", "replay", "review"}
)
CHECK_PASS = "pass"
CHECK_FAIL = "fail"
CHECK_PENDING = "pending"
CHECK_RESULTS = frozenset({CHECK_PASS, CHECK_FAIL, CHECK_PENDING})


def _frozen_id(prefix: str, payload: dict[str, Any]) -> str:
    """内容寻址 id = 前缀 + content_hash(payload)（复用单一身份源 ids.content_hash）。"""

    return f"{prefix}_{content_hash(payload)}"


@dataclass(frozen=True)
class MathematicalArtifact:
    """§6 MathematicalArtifact——数学定义/估计器/公式/触发器的形式化容器。

    字段照 §6「这些必须包含」全列；`proof_status` 是理论成熟度（升级门的 proof-honest 子句
    读它）。`statement` / `derivation` 是 §8 `TheoryClaim ⇒ Artifact exists` 的实质内容载体。
    """

    artifact_type: str
    statement: str = ""
    artifact_id: str = ""
    notation: str = ""
    assumptions: tuple[str, ...] = ()
    definition: str = ""
    derivation: str = ""
    proof_sketch: str = ""
    counterexamples: tuple[str, ...] = ()
    units: str = ""
    applicability: str = ""
    failure_conditions: tuple[str, ...] = ()
    proof_status: str = PROOF_UNPROVEN
    implementation_ref: str = ""
    test_ref: str = ""
    simulation_ref: str = ""
    validation_ref: str = ""
    used_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.proof_status not in PROOF_STATES:
            raise ValueError(f"proof_status 非法：{self.proof_status!r} ∉ {sorted(PROOF_STATES)}")
        if not self.artifact_id:
            object.__setattr__(
                self,
                "artifact_id",
                _frozen_id(
                    "math",
                    {
                        "artifact_type": self.artifact_type,
                        "statement": self.statement,
                        "definition": self.definition,
                        "assumptions": list(self.assumptions),
                    },
                ),
            )


@dataclass(frozen=True)
class TheoryImplementationBinding:
    """§6 TheoryImplementationBinding——把理论产物绑到具体实现 + 冻结实现内容指纹。

    `code_content_hash` 是 staleness 门的命门：bind 时用 `ids.content_hash` 冻结 code_ref 的
    源内容；运行时若 `content_hash(code_now) != code_content_hash` 即「实现改动后未刷新 binding」
    → §6 → 拒。§8 硬不变量 `TIB ⇒ code_ref + config_ref + data_contract_ref + ConsistencyCheck`
    在 spine_gate 的 binding-complete / consistency-present 子句兑现。
    """

    theory_ref: str
    code_ref: str = ""
    code_content_hash: str = ""
    config_ref: str = ""
    data_contract_ref: str = ""
    implementation_spec: str = ""
    binding_id: str = ""
    test_refs: tuple[str, ...] = ()
    simulation_refs: tuple[str, ...] = ()
    numerical_check_refs: tuple[str, ...] = ()
    symbol_mapping: dict[str, str] = field(default_factory=dict)
    unit_mapping: dict[str, str] = field(default_factory=dict)
    dimension_check: str = ""
    tolerance: float | None = None
    known_differences: tuple[str, ...] = ()
    consistency_verdict: str = ""
    verifier_ref: str = ""
    waiver_ref: str = ""
    used_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.binding_id:
            object.__setattr__(
                self,
                "binding_id",
                _frozen_id(
                    "tib",
                    {
                        "theory_ref": self.theory_ref,
                        "code_ref": self.code_ref,
                        "config_ref": self.config_ref,
                        "data_contract_ref": self.data_contract_ref,
                        "code_content_hash": self.code_content_hash,
                    },
                ),
            )

    @classmethod
    def bind_source(
        cls,
        *,
        theory_ref: str,
        code_ref: str,
        code_source: Any,
        config_ref: str = "",
        data_contract_ref: str = "",
        test_refs: tuple[str, ...] = (),
        **kw: Any,
    ) -> "TheoryImplementationBinding":
        """便捷构造：从实现源对象冻结 `code_content_hash`（复用 ids.content_hash）。

        `code_source` 可以是源码字符串、AST dump、或任何可 canonical_json 的结构——
        改它必变 hash，staleness 门据此抓「实现改了但 binding 没刷」。
        """

        return cls(
            theory_ref=theory_ref,
            code_ref=code_ref,
            code_content_hash=content_hash(code_source),
            config_ref=config_ref,
            data_contract_ref=data_contract_ref,
            test_refs=tuple(test_refs),
            **kw,
        )


@dataclass(frozen=True)
class ConsistencyCheck:
    """§6 ConsistencyCheck——理论 vs 实现的一条比对结果（symbolic/dimensional/numerical/...）。

    `result=fail` 即「代码实现与数学定义不一致」，升级门 consistency-pass 子句据此拒。
    `result=pending` 不算决定性证据（consistency-present 子句要求至少一条非 pending）。
    """

    binding_id: str
    check_type: str
    result: str
    check_id: str = ""
    input_refs: tuple[str, ...] = ()
    expected_property: str = ""
    observed_property: str = ""
    tolerance: float | None = None
    failure_reason: str = ""
    affected_assets: tuple[str, ...] = ()
    repair_plan: str = ""
    verifier_ref: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if self.check_type not in CHECK_TYPES:
            raise ValueError(f"check_type 非法：{self.check_type!r} ∉ {sorted(CHECK_TYPES)}")
        if self.result not in CHECK_RESULTS:
            raise ValueError(f"result 非法：{self.result!r} ∉ {sorted(CHECK_RESULTS)}")
        if not self.check_id:
            object.__setattr__(
                self,
                "check_id",
                _frozen_id(
                    "cc",
                    {
                        "binding_id": self.binding_id,
                        "check_type": self.check_type,
                        "expected_property": self.expected_property,
                        "observed_property": self.observed_property,
                        "result": self.result,
                    },
                ),
            )


@dataclass(frozen=True)
class MethodologyChoiceRecord:
    """§6 MethodologyChoiceRecord——用户对方法学松紧的选择 + 责任边界（决策 D-MATH-SPINE 放权）。

    门**不**拒绝放权产物的存在；它只拒「越权标注」（把放权产物叫 proof_backed）。
    `chosen_path` ∈ 放权标签时，门把可达标签降到 `allowed_environment` 内、记 responsibility_boundary。
    """

    chosen_path: str
    asset_ref: str = ""
    run_ref: str = ""
    choice_id: str = ""
    available_options: tuple[str, ...] = ()
    recommendation: str = ""
    tradeoffs_shown: tuple[str, ...] = ()
    risks_shown: tuple[str, ...] = ()
    skipped_steps: tuple[str, ...] = ()
    responsibility_boundary: str = ""
    actor: str = ""
    timestamp: str = ""
    allowed_environment: str = ""
    display_label: str = ""

    def __post_init__(self) -> None:
        if not self.choice_id:
            object.__setattr__(
                self,
                "choice_id",
                _frozen_id(
                    "mcr",
                    {
                        "chosen_path": self.chosen_path,
                        "asset_ref": self.asset_ref,
                        "run_ref": self.run_ref,
                        "actor": self.actor,
                    },
                ),
            )

    @property
    def is_waiver(self) -> bool:
        """是否一条「跳过严格路径」的放权（升级门 proof-honest 子句据此判 waiver 在场）。"""

        return self.chosen_path in WAIVER_LABELS or bool(self.skipped_steps)
