"""QRO 统一信封的【对抗式】测试（GOAL §1 · 卡 A-QRO-1 · RULES §2）。

验收标准不是「函数跑通」，是「**种一个已知的坏门，信封必须抓住，否则门是纸做的**」。
四个命门各种坏：
  #1 actor 非四类 → 拒（MUT 放过 → 红）
  #2 Signal QRO 无 typed contract → 拒（MUT 放过 → 红）
  #3 状态四轴混成单绿灯（任一轴弱却整体绿）→ 拒（MUT 漏任一轴 → 红）
  #4 模型本体塞 Factor library → 拒（复用单一源范畴门；MUT 绕门 → 红）
外加：身份走单一源 content_hash（不另造哈希族）、收编复用既有 id 且 carried 不重释、
信封 frozen 不可原地改。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.lineage.ids import content_hash
from app.lineage.spine import MathematicalArtifact
from app.qro import (
    ACTOR_AGENT,
    ACTOR_CLASSES,
    ACTOR_SCHEDULED_AGENT,
    ACTOR_USER_CONFIRMED_AGENT,
    ACTOR_USER_MANUAL,
    CORE_AXES,
    DEFINITION_DRAFT,
    DEFINITION_IMPLEMENTED,
    DEFINITION_SPECIFIED,
    EVIDENCE_INSUFFICIENT,
    EVIDENCE_SUFFICIENT,
    EVIDENCE_UNTESTED,
    GOVERNANCE_APPROVED,
    GOVERNANCE_UNREVIEWED,
    LIB_FACTOR,
    LIB_MODEL,
    OBJ_FACTOR,
    OBJ_FORECAST,
    OBJ_MATHEMATICAL_ARTIFACT,
    OBJ_MODEL,
    OBJ_SIGNAL,
    OBJ_STRATEGY_BOOK,
    RUNTIME_LIVE,
    RUNTIME_OFFLINE,
    RUNTIME_PAPER,
    THEORY_ACCEPTED,
    QROBoundaryError,
    QROValidationError,
    QualifiedResearchObject,
    admit_factor_qro,
    assert_library_membership,
    axis_clearance,
    from_factor,
    from_mathematical_artifact,
    from_model_card,
    from_signal_contract,
    from_strategy_candidate,
)

# 四核心轴全强（整体绿的唯一合法前提）。
_STRONG = {
    "definition": DEFINITION_IMPLEMENTED,
    "evidence": EVIDENCE_SUFFICIENT,
    "governance": GOVERNANCE_APPROVED,
    "runtime": RUNTIME_LIVE,
}


def _qro(object_type: str = OBJ_FACTOR, natural_key: str = "f@v1", **overrides):
    base = dict(object_type=object_type, natural_key=natural_key)
    base.update(_STRONG)
    base.update(overrides)
    return QualifiedResearchObject(**base)


# ── 命门 #1：actor 必须 ∈ 四类动作来源（GOAL §0）──────────────────────────────
def test_actor_must_be_one_of_four_classes():
    assert ACTOR_CLASSES == {
        ACTOR_USER_MANUAL,
        ACTOR_AGENT,
        ACTOR_USER_CONFIRMED_AGENT,
        ACTOR_SCHEDULED_AGENT,
    }


@pytest.mark.parametrize(
    "actor", [ACTOR_USER_MANUAL, ACTOR_AGENT, ACTOR_USER_CONFIRMED_AGENT, ACTOR_SCHEDULED_AGENT]
)
def test_four_legal_actors_construct(actor):
    qro = QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="f@v1", actor=actor)
    assert qro.actor == actor


@pytest.mark.parametrize("bad_actor", ["rogue_bot", "system", "USER_MANUAL", "", "root", "daemon"])
def test_illegal_actor_rejected(bad_actor):
    # 种坏门：非四类 actor 构造 QRO。MUT：__post_init__ 删 actor 校验 → 本断言转红。
    with pytest.raises(QROValidationError):
        QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="f@v1", actor=bad_actor)


# ── 命门 #2：Signal/Forecast QRO 必须带 typed input/output contract ───────────
@pytest.mark.parametrize("sig_type", [OBJ_SIGNAL, OBJ_FORECAST])
def test_signal_without_typed_contract_rejected(sig_type):
    # 种坏门：信号/预测 QRO 不绑 typed contract。MUT：删 CONTRACT_REQUIRING_TYPES 校验 → 转红。
    with pytest.raises(QROValidationError):
        QualifiedResearchObject(object_type=sig_type, natural_key="s1")


@pytest.mark.parametrize("sig_type", [OBJ_SIGNAL, OBJ_FORECAST])
def test_signal_with_typed_contract_ok(sig_type):
    qro = QualifiedResearchObject(
        object_type=sig_type,
        natural_key="s1",
        typed_contract={"output_kind": "xs_score", "horizon": 5},
    )
    assert qro.typed_contract["output_kind"] == "xs_score"


def test_non_signal_without_contract_is_fine():
    # 因子不在强制集——无 typed_contract 也能构造（命门只对信号/预测输出强制）。
    assert QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="f@v1").typed_contract == {}


# ── 命门 #3：状态四轴分离·不混单绿灯 ──────────────────────────────────────────
def test_six_axes_are_separate_fields():
    qro = _qro()
    axes = qro.state_axes()
    assert set(axes) == {"definition", "theory", "consistency", "evidence", "governance", "runtime"}


def test_all_four_core_axes_strong_clears_overall_green():
    assert axis_clearance(_qro()).cleared is True


@pytest.mark.parametrize(
    "axis,weak_value",
    [
        ("definition", DEFINITION_DRAFT),
        ("evidence", EVIDENCE_INSUFFICIENT),
        ("governance", GOVERNANCE_UNREVIEWED),
        ("runtime", RUNTIME_OFFLINE),
    ],
)
def test_any_single_weak_core_axis_blocks_overall_green(axis, weak_value):
    # 种坏门：单轴打弱、其余三轴强 → 整体绿**必须**被拒，且该轴进 blocking_axes。
    # 这把「不混单绿灯」做实：没有任何单轴能独自点亮整体绿。
    # MUT：axis_clearance 把某轴漏出合取（如只看 governance）→ 该轴这条转红。
    qro = _qro(**{axis: weak_value})
    clearance = axis_clearance(qro)
    assert clearance.cleared is False
    assert axis in clearance.blocking_axes


def test_evidence_missing_but_governance_green_is_not_overall_green():
    # 命门原文：「种『evidence 缺但 governance 绿就整体绿』→ 必拒」。
    qro = _qro(evidence=EVIDENCE_INSUFFICIENT, governance=GOVERNANCE_APPROVED)
    clearance = axis_clearance(qro)
    assert clearance.cleared is False
    assert clearance.governance_ok is True  # governance 确实绿
    assert clearance.evidence_ok is False  # 但 evidence 不绿
    assert "evidence" in clearance.blocking_axes  # → 整体绿被 evidence 卡住


@pytest.mark.parametrize(
    "axis,bad_value",
    [
        ("definition", "ready"),
        ("theory", "proven"),
        ("consistency", "consistent"),
        ("evidence", "green"),
        ("governance", "ok"),
        ("runtime", "production"),
    ],
)
def test_axis_value_out_of_enum_rejected(axis, bad_value):
    # 种坏门：任一轴塞枚举外的值（证明每轴是 typed 枚举、非自由单字段）。
    # MUT：删 __post_init__ 的逐轴枚举校验 → 转红。
    with pytest.raises(QROValidationError):
        QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="f@v1", **{axis: bad_value})


def test_default_axes_are_honest_deny_by_default():
    # 新铸 QRO 默认 = 最保守诚实态（draft/未测/未审/离线），绝不假绿灯。
    qro = QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="f@v1")
    assert qro.definition == DEFINITION_DRAFT
    assert qro.evidence == EVIDENCE_UNTESTED
    assert qro.governance == GOVERNANCE_UNREVIEWED
    assert qro.runtime == RUNTIME_OFFLINE
    assert axis_clearance(qro).cleared is False


# ── 命门 #4：模型本体进 Model Registry，不进 Factor Library（语义边界·R17）─────
def test_model_body_kind_rejected_from_factor_library():
    # 种坏门：把模型本体（kind=model_body）当因子塞因子库。
    # MUT：admit_factor_qro 绕过 admit_artifact_to_factor_lib → 转红。
    with pytest.raises(QROBoundaryError):
        admit_factor_qro(kind="model_body", ref="gbdt_xs_rank.pkl", factor_id="bad")


@pytest.mark.parametrize("body_ref", ["model.pt", "net.onnx", "tree.pkl", "w.safetensors.pt"])
def test_model_body_file_ref_rejected_from_factor_library(body_ref):
    # 种坏门：kind 自称 expression，但 ref 指向模型本体文件（双保险，复用既有范畴门）。
    with pytest.raises(QROBoundaryError):
        admit_factor_qro(kind="expression", ref=body_ref, factor_id="bad")


def test_expression_admitted_to_factor_library():
    qro = admit_factor_qro(
        kind="expression", ref="close/open - 1", factor_id="ret1", formula="close/open - 1"
    )
    assert qro.object_type == OBJ_FACTOR
    assert qro.natural_key == "ret1@v1"


def test_assert_library_membership_blocks_model_into_factor_lib():
    # 对象级语义边界：OBJ_MODEL 属 Model Registry，不能进 Factor Library。
    with pytest.raises(QROBoundaryError):
        assert_library_membership(OBJ_MODEL, LIB_FACTOR)


def test_assert_library_membership_allows_correct_homes():
    assert assert_library_membership(OBJ_FACTOR, LIB_FACTOR) is None
    assert assert_library_membership(OBJ_MODEL, LIB_MODEL) is None


# ── 身份：单一源 content_hash，不另造哈希族（红线）──────────────────────────────
def test_identity_is_content_addressed_via_single_source():
    qro = QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="mom@v3")
    expected = "qro_" + content_hash({"object_type": OBJ_FACTOR, "natural_key": "mom@v3"})
    assert qro.identity == expected


def test_identity_is_deterministic_and_discriminating():
    a = QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="mom@v3")
    a2 = QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="mom@v3")
    b = QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="mom@v4")
    c = QualifiedResearchObject(object_type=OBJ_SIGNAL, natural_key="mom@v3", typed_contract={"k": 1})
    assert a.identity == a2.identity  # 同对象 → 同身份（确定性）
    assert a.identity != b.identity  # 不同 natural_key → 不同身份
    assert a.identity != c.identity  # 不同 object_type → 不同身份（命名空间隔离）


def test_unknown_object_type_rejected():
    with pytest.raises(QROValidationError):
        QualifiedResearchObject(object_type="alpha_blob", natural_key="x")


def test_empty_natural_key_rejected():
    with pytest.raises(QROValidationError):
        QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="")


# ── 信封 frozen：状态迁移产新版本，不原地改 ───────────────────────────────────
def test_envelope_is_frozen():
    qro = _qro()
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        qro.governance = GOVERNANCE_UNREVIEWED  # type: ignore[misc]


# ── 收编适配器：复用既有 id、carried 不重释、扩展不替换 ───────────────────────
def test_from_factor_carries_lifecycle_not_reinterpret():
    # M-AUTHORITY：factor lifecycle 仍归 registry 权威；QRO 只 carried 快照，不重释。
    factor = SimpleNamespace(
        factor_id="momentum_20d",
        formula="ts_rank(close, 20)",
        version=3,
        author="alice",
        lifecycle_state="QUALIFIED",
        params={"window": 20},
    )
    qro = from_factor(factor)
    assert qro.object_type == OBJ_FACTOR
    assert qro.natural_key == "momentum_20d@v3"  # 复用既有 id，不另造
    assert qro.lifecycle == "QUALIFIED"  # 原样 carried
    assert qro.owner == "alice"
    assert qro.typed_contract["formula"] == "ts_rank(close, 20)"


def test_from_signal_contract_reuses_signal_id_and_satisfies_contract():
    # 用真 SignalContract 走通：身份直接复用 signal_id（已 content_hash），且天然满足命门 #2。
    from app.factor_factory.signal_contract import (
        LeakageDeclaration,
        SignalContractRegistry,
    )

    reg = SignalContractRegistry()
    sc = reg.register(
        name="gbdt xs score",
        source_lib="ml",
        model_ref="gbdt_xs_rank_v3.pkl",
        output_kind="xs_score",
        horizon=5,
        leakage=LeakageDeclaration(oof=True, purge=True, embargo=True, embargo_days=3),
    )
    qro = from_signal_contract(sc)
    assert qro.object_type == OBJ_SIGNAL
    assert qro.natural_key == sc.signal_id  # 直接复用既有 content_hash 身份
    assert qro.typed_contract["output_kind"] == "xs_score"  # typed contract 已满足
    assert qro.typed_contract["model_ref"] == "gbdt_xs_rank_v3.pkl"
    assert any("model_ref:" in ref for ref in qro.lineage)  # 回指模型本体（血统）


def test_from_model_card_lands_in_model_registry_semantics():
    card = SimpleNamespace(key="lightgbm_ranker", family="ml", tasks=["lambdarank"])
    qro = from_model_card(card)
    assert qro.object_type == OBJ_MODEL
    assert qro.natural_key == "lightgbm_ranker"
    # 语义边界：模型 QRO 归 Model Registry，不能进 Factor Library。
    with pytest.raises(QROBoundaryError):
        assert_library_membership(qro.object_type, LIB_FACTOR)


def test_from_strategy_candidate_pins_paper_runtime():
    # 候选池钉死 paper_desk（D-PERM 不跳级）→ runtime 轴映 paper，绝不 live。
    candidate = {
        "candidate_id": "cand_abc123",
        "run_id": "run_999",
        "created_by": "agent",
        "status": "candidate",
        "stops_at": "paper_desk",
    }
    qro = from_strategy_candidate(candidate)
    assert qro.object_type == OBJ_STRATEGY_BOOK
    assert qro.natural_key == "cand_abc123"
    assert qro.runtime == RUNTIME_PAPER
    assert qro.runtime != RUNTIME_LIVE


def test_from_mathematical_artifact_maps_proof_status_to_theory_axis():
    art = MathematicalArtifact(
        artifact_type="estimator",
        statement="DSR deflated Sharpe",
        definition="x",
        proof_status="proof_backed",
    )
    qro = from_mathematical_artifact(art)
    assert qro.object_type == OBJ_MATHEMATICAL_ARTIFACT
    assert qro.natural_key == art.artifact_id  # 复用 content_hash 身份
    assert qro.theory == THEORY_ACCEPTED  # proof_backed → theory=accepted（粗投影·快照）
    assert art.artifact_id in qro.mathematical_refs


def test_incorporated_specified_definition_consistent():
    # 收编的已注册因子标 definition=implemented；但仍需 evidence/governance/runtime 才整体绿。
    factor = SimpleNamespace(
        factor_id="f1", formula="close", version=1, author="x", lifecycle_state="NEW", params={}
    )
    qro = from_factor(factor)
    assert qro.definition == DEFINITION_IMPLEMENTED
    # 单 definition 强不足以整体绿（再证不混单绿灯）。
    assert axis_clearance(qro).cleared is False
