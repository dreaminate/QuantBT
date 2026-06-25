"""QRO 语义边界**完整切分**的对抗式测试（GOAL §1 行154-157 + §9 · 卡 A-QRO-2 · RULES §2）。

在 A-QRO-1（信封 / 状态六轴 / 四命门，见 test_qro_envelope.py）之上，钉死 §1 语义边界的
**库归属**与**守门器解耦**——验收标准不是「函数跑通」，是「**种一个已知的坏门，门必须抓住，
否则门是纸做的**」。五条可证伪验收各种坏：

  ① 模型本体（ML/DL）作为因子入 Factor Library → 拒（A-QRO-1 已有·本卡完整化）。
  ② 模型输出（Forecast）未绑 Signal Contract 进信号层 → 拒。
  ③ 因子（算术/expression）误放进 Model Registry → 拒；策略误放进 Factor/Model → 拒。
  ④ 守门指标（DSR/PBO/IC…）进入 generator fitness → 拒（generator/gatekeeper 解耦）。
  ⑤ 正路径：各类资产正确归属库 · 跨库 typed 引用（策略引 factor id/model id）放行**不误伤**。

单一源（RULES §1）：守门指标黑名单只此一份（mining.GATE_METRIC_KEYWORDS），本测试**导入它**
钉死 QRO 层守门与 mining 层同口径，绝不在 QRO 层另立第二黑名单。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.qro import (
    ACTOR_USER_MANUAL,
    LIB_FACTOR,
    LIB_MODEL,
    LIB_SIGNAL,
    LIB_STRATEGY,
    LIBRARY_OF,
    OBJ_EXECUTION_POLICY,
    OBJ_FACTOR,
    OBJ_FORECAST,
    OBJ_MODEL,
    OBJ_PORTFOLIO_POLICY,
    OBJ_RISK_POLICY,
    OBJ_SIGNAL,
    OBJ_STRATEGY_BOOK,
    QROBoundaryError,
    QualifiedResearchObject,
    admit_factor_qro,
    admit_model_qro,
    assert_generator_fitness_clean,
    assert_library_membership,
    assert_signal_contract_bound,
    from_model_card,
    from_signal_contract,
    from_strategy_candidate,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 验收① 模型本体（ML/DL）作为因子入 Factor Library → 拒（A-QRO-1 已有·本卡完整化）
# ═══════════════════════════════════════════════════════════════════════════════
# 完整化：覆盖**全部** MODEL_BODY_EXTS 后缀（A-QRO-1 测试只点了 4 个；这里钉死单一源全集）。
def _model_body_exts() -> tuple[str, ...]:
    from app.factor_factory.signal_contract import MODEL_BODY_EXTS

    return MODEL_BODY_EXTS


@pytest.mark.parametrize("ext", _model_body_exts())
def test_every_model_body_ext_rejected_from_factor_lib(ext):
    # 种坏门：把任一种模型本体文件后缀当 expression 因子塞因子库。
    # MUT：admit_factor_qro 绕过 admit_artifact_to_factor_lib（单一源范畴门）→ 转红。
    with pytest.raises(QROBoundaryError):
        admit_factor_qro(kind="expression", ref=f"trained_model{ext}", factor_id="bad")


def test_model_body_kind_rejected_from_factor_lib_complete():
    # 种坏门：kind 直接自报 model_body 仍塞因子库（最直白的范畴错误）。
    with pytest.raises(QROBoundaryError):
        admit_factor_qro(kind="model_body", ref="gbdt_xs_rank.pkl", factor_id="bad")


def test_object_level_model_cannot_home_in_factor_lib():
    # 对象级语义边界：OBJ_MODEL 的家是 Model Registry，绝不能进 Factor Library。
    # MUT：LIBRARY_OF[OBJ_MODEL] 被错配成 factor_library → 转红。
    with pytest.raises(QROBoundaryError):
        assert_library_membership(OBJ_MODEL, LIB_FACTOR)


def test_incorporated_model_card_qro_blocked_from_factor_lib():
    # 收编的真模型卡（from_model_card）→ 其 QRO 归 Model Registry，钉死不能进 Factor Library。
    card = SimpleNamespace(key="lightgbm_ranker", family="ml", tasks=["lambdarank"])
    qro = from_model_card(card)
    assert qro.object_type == OBJ_MODEL
    with pytest.raises(QROBoundaryError):
        assert_library_membership(qro.object_type, LIB_FACTOR)


# ═══════════════════════════════════════════════════════════════════════════════
# 验收② 模型输出（Forecast）未绑 Signal Contract 进信号层 → 拒
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sig_type", [OBJ_SIGNAL, OBJ_FORECAST])
def test_unbound_forecast_rejected_from_signal_layer(sig_type):
    # 种坏门：信号/预测带了 typed_contract（过构造门）但**无任何契约绑定**（无 model_ref / 契约 id）。
    # MUT：assert_signal_contract_bound 删绑定校验（直接 return）→ 转红。
    qro = QualifiedResearchObject(
        object_type=sig_type,
        natural_key="orphan_pred",
        typed_contract={"output_kind": "xs_score", "horizon": 5},  # 只有口径、无回指本体
    )
    with pytest.raises(QROBoundaryError):
        assert_signal_contract_bound(qro)


@pytest.mark.parametrize("sig_type", [OBJ_SIGNAL, OBJ_FORECAST])
def test_forecast_with_nonbody_model_ref_still_rejected(sig_type):
    # 种坏门：model_ref 填了，但指向的不是真本体文件（如裸 key），= 悬空信号（与血统门同口径拒）。
    qro = QualifiedResearchObject(
        object_type=sig_type,
        natural_key="dangling",
        typed_contract={"output_kind": "xs_score", "model_ref": "lightgbm_ranker"},
    )
    with pytest.raises(QROBoundaryError):
        assert_signal_contract_bound(qro)


def test_signal_from_real_contract_passes_binding():
    # 正路径：经 SignalContractRegistry 登记的真契约 → from_signal_contract → 绑定门放行（不抛）。
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
    assert assert_signal_contract_bound(qro) is None  # 回指真实本体 → 已绑，放行


def test_signal_bound_via_explicit_contract_id_passes():
    # 正路径（集成/stacking）：信号绑契约 id（signal_id）而非裸本体 → 亦算已绑（GOAL §9 信号层组合）。
    qro = QualifiedResearchObject(
        object_type=OBJ_SIGNAL,
        natural_key="ensemble_1",
        typed_contract={"output_kind": "blend", "signal_id": "sig_abc123"},
    )
    assert assert_signal_contract_bound(qro) is None


def test_signal_bound_via_lineage_backref_passes():
    # 正路径：lineage 携 model_ref: 回指 → 已绑。
    qro = QualifiedResearchObject(
        object_type=OBJ_FORECAST,
        natural_key="lin",
        typed_contract={"output_kind": "seq_pred"},
        lineage=("model_ref:lstm_v2.pt",),
    )
    assert assert_signal_contract_bound(qro) is None


def test_binding_gate_noop_on_non_signal_objects():
    # 不误伤：因子/模型不在信号绑定门作用面 → no-op（返回 None，不抛）。
    factor_qro = QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key="f@v1")
    assert assert_signal_contract_bound(factor_qro) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 验收③ 因子（算术/expression）误放进 Model Registry → 拒；策略误放进 Factor/Model → 拒
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("expr", ["close/open - 1", "ts_rank(close, 20)", "(high+low)/2"])
def test_arithmetic_expression_rejected_from_model_registry(expr):
    # 种坏门：把算术因子表达式当模型本体塞 Model Registry。
    # MUT：admit_model_qro 删 looks_like_model_body（单一源）本体校验 → 转红。
    with pytest.raises(QROBoundaryError):
        admit_model_qro(model_key="bad", family="ml", body_ref=expr)


@pytest.mark.parametrize("bad_family", ["arithmetic", "expression", "strategy", "rule", ""])
def test_non_ml_dl_family_rejected_from_model_registry(bad_family):
    # 种坏门：family 非 ml/dl（因子/策略/规则伪装成模型）入 Model Registry。
    with pytest.raises(QROBoundaryError):
        admit_model_qro(model_key="x", family=bad_family, body_ref="m.pkl")


def test_object_level_factor_cannot_home_in_model_registry():
    # 对象级：OBJ_FACTOR 的家是 Factor Library，不能进 Model Registry。
    with pytest.raises(QROBoundaryError):
        assert_library_membership(OBJ_FACTOR, LIB_MODEL)


@pytest.mark.parametrize("wrong_lib", [LIB_FACTOR, LIB_MODEL])
def test_strategy_body_rejected_from_factor_and_model_lib(wrong_lib):
    # 种坏门：策略本体误放进 Factor Library / Model Registry。
    # MUT：LIBRARY_OF[OBJ_STRATEGY_BOOK] 被错配 → 转红。
    with pytest.raises(QROBoundaryError):
        assert_library_membership(OBJ_STRATEGY_BOOK, wrong_lib)


def test_real_model_body_admitted_to_registry():
    # 正路径：真模型本体文件 → 准入 Model Registry，QRO 类型 = model。
    qro = admit_model_qro(model_key="gbdt_xs_rank_v3", family="ml", body_ref="gbdt_xs_rank_v3.pkl")
    assert qro.object_type == OBJ_MODEL
    assert qro.natural_key == "gbdt_xs_rank_v3"
    assert assert_library_membership(qro.object_type, LIB_MODEL) is None


def test_catalog_key_model_admitted_without_body_ref():
    # 正路径：登记目录模型（卡片，尚无 body 文件）→ model_key + body_ref 留空即可准入。
    qro = admit_model_qro(model_key="lightgbm_ranker", family="dl", actor=ACTOR_USER_MANUAL)
    assert qro.object_type == OBJ_MODEL
    assert qro.typed_contract["family"] == "dl"


# ═══════════════════════════════════════════════════════════════════════════════
# 验收④ 守门指标进入 generator fitness → 拒（generator/gatekeeper 严格解耦）
# ═══════════════════════════════════════════════════════════════════════════════
def _gate_metric_keywords() -> tuple[str, ...]:
    # 单一源：直接取 mining 黑名单，钉死 QRO 层守门与 mining 同口径（绝不另立第二黑名单）。
    from app.factor_factory.mining import GATE_METRIC_KEYWORDS

    return GATE_METRIC_KEYWORDS


@pytest.mark.parametrize("metric", _gate_metric_keywords())
def test_every_gate_metric_rejected_from_generator_fitness(metric):
    # 种坏门：把**每一个**守门指标关键词当生成器 fitness 维度。
    # MUT：assert_generator_fitness_clean 绕过 mining.is_gate_metric_key（单一源）→ 转红。
    with pytest.raises(QROBoundaryError):
        assert_generator_fitness_clean([metric])


@pytest.mark.parametrize(
    "dirty_key", ["ic_mean", "rank_ic", "sharpe_oos", "dsr_gate", "pbo_score", "ir_12m", "net_return"]
)
def test_gate_metric_compound_keys_rejected_from_generator_fitness(dirty_key):
    # 种坏门：守门指标被包装进复合排序键（先看结果再生成的隐蔽入口）。
    with pytest.raises(QROBoundaryError):
        assert_generator_fitness_clean([dirty_key])


def test_single_string_gate_metric_not_iterated_char_by_char():
    # 防呆：单个 str（非 list）传入也按一个键判，不被逐字符迭代漏判。
    # MUT：删 isinstance(str) 防呆 → "ic" 逐字符 'i','c' 均不命中 → 漏放 → 转红。
    with pytest.raises(QROBoundaryError):
        assert_generator_fitness_clean("ic")


def test_mixed_clean_and_dirty_fitness_rejected():
    # 种坏门：结构键里混一个守门指标 → 整体拒（脏的那个必被抓）。
    with pytest.raises(QROBoundaryError):
        assert_generator_fitness_clean(["complexity", "novelty", "dsr"])


@pytest.mark.parametrize("clean_key", ["complexity", "op_coverage", "family_diversity", "novelty"])
def test_structural_sort_keys_pass_generator_fitness(clean_key):
    # 正路径：纯结构维度（生成器白名单）→ 放行不误伤。
    assert assert_generator_fitness_clean([clean_key]) is None


def test_qro_generator_gate_agrees_with_mining_single_source():
    # 钉死单一源：QRO 层守门判定与 mining.is_gate_metric_key 对每个键完全一致（无第二真相）。
    from app.factor_factory.mining import is_gate_metric_key

    for key in ["ic", "dsr", "pbo", "complexity", "novelty", "op_coverage", "sharpe_oos"]:
        flagged = is_gate_metric_key(key)
        if flagged:
            with pytest.raises(QROBoundaryError):
                assert_generator_fitness_clean([key])
        else:
            assert assert_generator_fitness_clean([key]) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 验收⑤ 正路径：各类资产正确归属库 · 跨库 typed 引用放行不误伤
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "obj_type,home_lib",
    [
        (OBJ_FACTOR, LIB_FACTOR),
        (OBJ_MODEL, LIB_MODEL),
        (OBJ_SIGNAL, LIB_SIGNAL),
        (OBJ_FORECAST, LIB_SIGNAL),  # 模型输出经信号契约进信号库
        (OBJ_STRATEGY_BOOK, LIB_STRATEGY),
    ],
)
def test_each_asset_homes_in_its_own_library(obj_type, home_lib):
    # 正路径：每类资产进自己的家 → 放行（assert_library_membership 返回 None）。
    assert assert_library_membership(obj_type, home_lib) is None
    # 钉死归属表与验收一致（单一源 LIBRARY_OF）。
    assert LIBRARY_OF[obj_type] == home_lib


@pytest.mark.parametrize(
    "policy_type", [OBJ_PORTFOLIO_POLICY, OBJ_RISK_POLICY, OBJ_EXECUTION_POLICY]
)
def test_policies_home_in_their_own_policy_libs_not_factor(policy_type):
    # 正路径 + 边界：组合/风控/执行各居其 Policy 库，且绝不能进 Factor Library。
    assert assert_library_membership(policy_type, LIBRARY_OF[policy_type]) is None
    with pytest.raises(QROBoundaryError):
        assert_library_membership(policy_type, LIB_FACTOR)


def test_strategy_referencing_factor_and_model_ids_is_reference_not_misplacement():
    # 核心不误伤：策略 typed-引用 factor id / model id（跨库引用），策略仍归 StrategyBook，
    # 被引的 factor / model 各居其家——引用 ≠ 误放，绝不因「策略提到了 factor id」就拒策略。
    # MUT：若边界门把「引用别库 id」错当「把别库对象塞进本库」→ 这条转红。
    candidate = {
        "candidate_id": "cand_xref",
        "run_id": "run_1",
        "created_by": "agent",
        "status": "candidate",
        "stops_at": "paper_desk",
        "factor_set": "momentum_20d@v3",   # 跨库引用：因子 id
        "model_id": "gbdt_xs_rank_v3",     # 跨库引用：模型 id
    }
    qro = from_strategy_candidate(candidate)
    assert qro.object_type == OBJ_STRATEGY_BOOK
    # 策略本体归 StrategyBook（放行）。
    assert assert_library_membership(qro.object_type, LIB_STRATEGY) is None
    # 被引对象各居其家（引用合法、不触边界）。
    assert assert_library_membership(OBJ_FACTOR, LIB_FACTOR) is None
    assert assert_library_membership(OBJ_MODEL, LIB_MODEL) is None
    # typed 引用如实承载在契约里（被引 id 是数据、非成员资格声明）。
    assert qro.typed_contract["factor_set"] == "momentum_20d@v3"
    assert qro.typed_contract["model_id"] == "gbdt_xs_rank_v3"
