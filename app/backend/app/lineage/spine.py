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

from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from enum import Enum
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

PROMOTION_LABELS = frozenset(
    {
        LABEL_DRAFT,
        LABEL_EXPLORATORY,
        LABEL_CHALLENGED,
        LABEL_USER_WAIVED_THEORY,
        LABEL_USER_WAIVED_VALIDATION,
        LABEL_CUSTOM_METHODOLOGY,
        LABEL_EVIDENCE_SUFFICIENT,
        LABEL_PROOF_BACKED,
        LABEL_PRODUCTION_READY,
    }
)

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
ARTIFACT_LABEL_DEFINITION = "label_definition"
ARTIFACT_SIGNAL_TRANSFORM = "signal_transform"
ARTIFACT_PORTFOLIO_OBJECTIVE = "portfolio_objective"
ARTIFACT_PAYOFF_DEFINITION = "payoff_definition"
ARTIFACT_ATTRIBUTION_DECOMPOSITION = "attribution_decomposition"

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


def _record_identity(record: Any, *, prefix: str, id_field: str) -> str:
    """Derive an identity from every semantic field, never from a caller id."""

    return _frozen_id(
        prefix,
        {
            item.name: getattr(record, item.name)
            for item in fields(record)
            if item.name != id_field
        },
    )


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
    dimensions: str = ""
    applicability: str = ""
    failure_conditions: tuple[str, ...] = ()
    proof_status: str = PROOF_UNPROVEN
    implementation_ref: str = ""
    test_ref: str = ""
    simulation_ref: str = ""
    validation_ref: str = ""
    used_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "counterexamples", tuple(self.counterexamples))
        object.__setattr__(self, "failure_conditions", tuple(self.failure_conditions))
        object.__setattr__(self, "used_by", tuple(self.used_by))
        if self.proof_status not in PROOF_STATES:
            raise ValueError(f"proof_status 非法：{self.proof_status!r} ∉ {sorted(PROOF_STATES)}")
        if not self.artifact_id:
            object.__setattr__(
                self,
                "artifact_id",
                _record_identity(self, prefix="math", id_field="artifact_id"),
            )


@dataclass(frozen=True)
class TheorySpec:
    """Canonical theory object linking a mathematical requirement to an artifact."""

    mathematical_requirement_ref: str
    artifact_ref: str
    title: str = ""
    assumptions: tuple[str, ...] = ()
    definitions: tuple[str, ...] = ()
    derivation: str = ""
    proof_sketch: str = ""
    counterexamples: tuple[str, ...] = ()
    applicability: str = ""
    failure_conditions: tuple[str, ...] = ()
    proof_status: str = PROOF_UNPROVEN
    evidence_refs: tuple[str, ...] = ()
    validation_refs: tuple[str, ...] = ()
    used_by: tuple[str, ...] = ()
    theory_spec_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "assumptions",
            "definitions",
            "counterexamples",
            "failure_conditions",
            "evidence_refs",
            "validation_refs",
            "used_by",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if self.proof_status not in PROOF_STATES:
            raise ValueError(f"proof_status 非法：{self.proof_status!r} ∉ {sorted(PROOF_STATES)}")
        if not self.theory_spec_id:
            object.__setattr__(
                self,
                "theory_spec_id",
                _record_identity(self, prefix="theory", id_field="theory_spec_id"),
            )


@dataclass(frozen=True)
class ImplementationSpec:
    """Canonical code/config/data contract referenced by a theory binding."""

    theory_ref: str
    code_ref: str
    config_ref: str
    data_contract_ref: str
    code_content_hash: str = ""
    config_content_hash: str = ""
    data_contract_content_hash: str = ""
    entrypoint_ref: str = ""
    symbol_mapping: dict[str, str] = field(default_factory=dict)
    unit_mapping: dict[str, str] = field(default_factory=dict)
    expected_properties: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    simulation_refs: tuple[str, ...] = ()
    numerical_check_refs: tuple[str, ...] = ()
    run_config_refs: tuple[str, ...] = ()
    monitor_refs: tuple[str, ...] = ()
    implementation_spec_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "expected_properties",
            "test_refs",
            "simulation_refs",
            "numerical_check_refs",
            "run_config_refs",
            "monitor_refs",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "symbol_mapping", dict(self.symbol_mapping))
        object.__setattr__(self, "unit_mapping", dict(self.unit_mapping))
        if not self.implementation_spec_id:
            object.__setattr__(
                self,
                "implementation_spec_id",
                _record_identity(
                    self,
                    prefix="implspec",
                    id_field="implementation_spec_id",
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
    implementation_ref: str = ""
    code_ref: str = ""
    code_content_hash: str = ""
    config_ref: str = ""
    config_content_hash: str = ""
    data_contract_ref: str = ""
    data_contract_content_hash: str = ""
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
        for name in (
            "test_refs",
            "simulation_refs",
            "numerical_check_refs",
            "known_differences",
            "used_by",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "symbol_mapping", dict(self.symbol_mapping))
        object.__setattr__(self, "unit_mapping", dict(self.unit_mapping))
        if not self.binding_id:
            object.__setattr__(
                self,
                "binding_id",
                _record_identity(self, prefix="tib", id_field="binding_id"),
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
        object.__setattr__(self, "input_refs", tuple(self.input_refs))
        object.__setattr__(self, "affected_assets", tuple(self.affected_assets))
        if self.check_type not in CHECK_TYPES:
            raise ValueError(f"check_type 非法：{self.check_type!r} ∉ {sorted(CHECK_TYPES)}")
        if self.result not in CHECK_RESULTS:
            raise ValueError(f"result 非法：{self.result!r} ∉ {sorted(CHECK_RESULTS)}")
        if not self.check_id:
            object.__setattr__(
                self,
                "check_id",
                _record_identity(self, prefix="cc", id_field="check_id"),
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
        for name in (
            "available_options",
            "tradeoffs_shown",
            "risks_shown",
            "skipped_steps",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.choice_id:
            object.__setattr__(
                self,
                "choice_id",
                _record_identity(self, prefix="mcr", id_field="choice_id"),
            )

    @property
    def is_waiver(self) -> bool:
        """是否一条「跳过严格路径」的放权（升级门 proof-honest 子句据此判 waiver 在场）。"""

        return self.chosen_path in WAIVER_LABELS or bool(self.skipped_steps)


@dataclass(frozen=True)
class ResponsibilityDisclosureRecord:
    """Persisted responsibility boundary paired with methodology decisions."""

    asset_ref: str
    run_ref: str = ""
    responsibility_boundary: str = ""
    risks_disclosed: tuple[str, ...] = ()
    accepted_risks: tuple[str, ...] = ()
    user_accepted_risk: bool = False
    risk_owner: str = ""
    recommendation: str = ""
    alternatives: tuple[str, ...] = ()
    costs_disclosed: tuple[str, ...] = ()
    actor: str = ""
    timestamp: str = ""
    allowed_environment: str = ""
    methodology_choice_ref: str = ""
    disclosure_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "risks_disclosed", tuple(self.risks_disclosed))
        object.__setattr__(self, "accepted_risks", tuple(self.accepted_risks))
        object.__setattr__(self, "alternatives", tuple(self.alternatives))
        object.__setattr__(self, "costs_disclosed", tuple(self.costs_disclosed))
        if not self.disclosure_id:
            object.__setattr__(
                self,
                "disclosure_id",
                _record_identity(self, prefix="resp", id_field="disclosure_id"),
            )


def _chain_now() -> str:
    return datetime.now(UTC).isoformat()


def _chain_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


@dataclass(frozen=True)
class MathematicalSpineChainRecord:
    """Canonical owner-scoped full-chain projection stored by ``SpineLedger``."""

    chain_ref: str
    data_semantics_ref: str
    factor_ref: str
    model_ref: str
    forecast_ref: str
    signal_contract_ref: str
    strategy_book_ref: str
    portfolio_policy_ref: str
    risk_policy_ref: str
    execution_policy_ref: str
    backtest_run_ref: str
    attribution_ref: str
    monitor_ref: str
    theory_binding_refs: tuple[str, ...]
    consistency_check_refs: tuple[str, ...]
    methodology_choice_ref: str
    responsibility_boundary_ref: str
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...]
    consistency_verdict: str
    target_runtime: str = "offline"
    recorded_by: str = ""
    silent_mock_fallback_used: bool = False
    chain_version: str = "math_spine_chain.v1"
    created_at: str = field(default_factory=_chain_now)

    def __post_init__(self) -> None:
        for field_name in (
            "theory_binding_refs",
            "consistency_check_refs",
            "evidence_refs",
            "validation_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(str(value) for value in _chain_tuple(getattr(self, field_name))),
            )
        for field_name in ("consistency_verdict", "target_runtime"):
            value = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                str(value.value if isinstance(value, Enum) else value),
            )


def mathematical_spine_chain_from_dict(
    data: dict[str, Any],
) -> MathematicalSpineChainRecord:
    return MathematicalSpineChainRecord(
        chain_ref=str(data.get("chain_ref") or ""),
        data_semantics_ref=str(data.get("data_semantics_ref") or ""),
        factor_ref=str(data.get("factor_ref") or ""),
        model_ref=str(data.get("model_ref") or ""),
        forecast_ref=str(data.get("forecast_ref") or ""),
        signal_contract_ref=str(data.get("signal_contract_ref") or ""),
        strategy_book_ref=str(data.get("strategy_book_ref") or ""),
        portfolio_policy_ref=str(data.get("portfolio_policy_ref") or ""),
        risk_policy_ref=str(data.get("risk_policy_ref") or ""),
        execution_policy_ref=str(data.get("execution_policy_ref") or ""),
        backtest_run_ref=str(data.get("backtest_run_ref") or ""),
        attribution_ref=str(data.get("attribution_ref") or ""),
        monitor_ref=str(data.get("monitor_ref") or ""),
        theory_binding_refs=_chain_tuple(data.get("theory_binding_refs")),
        consistency_check_refs=_chain_tuple(data.get("consistency_check_refs")),
        methodology_choice_ref=str(data.get("methodology_choice_ref") or ""),
        responsibility_boundary_ref=str(
            data.get("responsibility_boundary_ref") or ""
        ),
        evidence_refs=_chain_tuple(data.get("evidence_refs")),
        validation_refs=_chain_tuple(data.get("validation_refs")),
        consistency_verdict=str(data.get("consistency_verdict") or "unbound"),
        target_runtime=str(data.get("target_runtime") or "offline"),
        recorded_by=str(data.get("recorded_by") or ""),
        silent_mock_fallback_used=bool(
            data.get("silent_mock_fallback_used", False)
        ),
        chain_version=str(data.get("chain_version") or "math_spine_chain.v1"),
        created_at=str(data.get("created_at") or _chain_now()),
    )


def canonical_mathematical_spine_chain_ref(
    record: MathematicalSpineChainRecord,
) -> str:
    payload = asdict(record)
    payload.pop("chain_ref", None)
    payload.pop("consistency_verdict", None)
    payload.pop("created_at", None)
    return "math_spine_chain_" + content_hash(payload)


def canonical_spine_record_identity(record: Any) -> str:
    """Recompute the complete-content identity for a canonical Spine record."""

    if isinstance(record, MathematicalSpineChainRecord):
        return canonical_mathematical_spine_chain_ref(record)
    specs = (
        (MathematicalArtifact, "math", "artifact_id"),
        (TheorySpec, "theory", "theory_spec_id"),
        (ImplementationSpec, "implspec", "implementation_spec_id"),
        (TheoryImplementationBinding, "tib", "binding_id"),
        (ConsistencyCheck, "cc", "check_id"),
        (MethodologyChoiceRecord, "mcr", "choice_id"),
        (ResponsibilityDisclosureRecord, "resp", "disclosure_id"),
    )
    for record_type, prefix, id_field in specs:
        if isinstance(record, record_type):
            return _record_identity(record, prefix=prefix, id_field=id_field)
    raise TypeError(
        f"unsupported canonical Mathematical Spine record: {type(record).__name__}"
    )
