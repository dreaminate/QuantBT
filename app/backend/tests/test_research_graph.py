"""Research Graph IR 的【对抗式】测试（GOAL §1/§2 · 卡 A-GRAPH-1 · RULES §2）。

验收标准不是「函数跑通」，是「**种一个已知坏门，IR 必抓，否则门是纸做的**」。七个命门各种坏：
  #1 单一真相源：任一台维护独立真相状态（与图矛盾）→ 拒（MUT 关比对 → 红）
  #2 typed contract：signal/forecast 节点缺 typed contract / 非 QRO 对象进图 → 拒（MUT 关校验 → 红）
  #3 canonical command 落点：改动未落命令（缺 command_ref / 绕 apply 裸写）→ 拒（MUT 关 assert → 红）
  #4 DeskHandoff resolved 缺 produced_ref → 拒（MUT 删 __post_init__ 检查 → 红）
  #5 写权限按台隔离：策略台直接写 Factor → 拒（MUT 关 authority → 红）
  #6 机构级投影缺 math/consistency 轴 → 拒（MUT 关 assert → 红）
  #7 正路径不误伤：home 台写本台对象 / 跨台引用 / 带 produced_ref 解决交接 → 放行
外加：身份走单一源 content_hash（node_id=qro.identity·edge/cmd/handoff 同族·不另造）、frozen 不可原地改、
内容寻址幂等不静默覆盖、HOME_DESK_OF 全覆盖 OBJECT_TYPES（单一源·防漂）。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.lineage.ids import content_hash
from app.qro.envelope import (
    ACTOR_AGENT,
    ACTOR_USER_MANUAL,
    EVIDENCE_SUFFICIENT,
    EVIDENCE_UNTESTED,
    OBJ_BACKTEST_RUN,
    OBJ_EXECUTION_POLICY,
    OBJ_FACTOR,
    OBJ_MODEL,
    OBJ_SIGNAL,
    OBJ_STRATEGY_BOOK,
    OBJECT_TYPES,
    QualifiedResearchObject,
)
from app.graph import (
    CMD_ADD_EDGE,
    CMD_CREATE_NODE,
    CMD_OPEN_HANDOFF,
    CMD_RESOLVE_HANDOFF,
    CMD_UPDATE_NODE,
    DESK_BACKTEST,
    DESK_EXECUTION,
    DESK_FACTOR,
    DESK_MODEL,
    DESK_RESEARCH,
    DESK_SIGNAL,
    DESK_STRATEGY,
    DESKS,
    EDGE_DEPENDENCY,
    EDGE_LINEAGE,
    HANDOFF_OPEN,
    HANDOFF_REJECTED,
    HANDOFF_RESOLVED,
    HOME_DESK_OF,
    CanonicalCommand,
    CanonicalCommandViolation,
    DeskHandoff,
    GraphIntegrityError,
    GraphNode,
    HandoffIncompleteError,
    NodeAdmissionError,
    NodeView,
    DeskProjection,
    ProjectionError,
    ResearchGraph,
    ResearchGraphError,
    SingleSourceViolation,
    WriteAuthorityViolation,
    assert_institutional_projection,
    home_desk_of,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _factor_qro(nk: str = "mom@v1", **over) -> QualifiedResearchObject:
    return QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key=nk, actor=ACTOR_USER_MANUAL, **over)


def _signal_qro(nk: str = "sig1", **over) -> QualifiedResearchObject:
    over.setdefault("typed_contract", {"output_kind": "xs_score", "horizon": 5})
    return QualifiedResearchObject(object_type=OBJ_SIGNAL, natural_key=nk, actor=ACTOR_AGENT, **over)


def _strategy_qro(nk: str = "strat1", **over) -> QualifiedResearchObject:
    return QualifiedResearchObject(object_type=OBJ_STRATEGY_BOOK, natural_key=nk, actor=ACTOR_AGENT, **over)


def _create(desk: str, qro: QualifiedResearchObject, actor: str = ACTOR_USER_MANUAL) -> CanonicalCommand:
    return CanonicalCommand(
        command_type=CMD_CREATE_NODE, actor=actor, target_desk=desk, payload={"qro": qro}, origin="canvas"
    )


def _graph_with_factor(nk: str = "mom@v1", **over):
    g = ResearchGraph()
    fq = _factor_qro(nk, **over)
    node = g.apply(_create(DESK_FACTOR, fq))
    return g, node, fq


# ─────────────────────────────────────────────────────────────────────────────
# HOME_DESK_OF 单一源 + 全覆盖（防漂·写权限投影的唯一源）
# ─────────────────────────────────────────────────────────────────────────────
def test_home_desk_map_covers_all_object_types_exactly():
    # HOME_DESK_OF 必须恰好覆盖 OBJECT_TYPES（不漏不多）——否则写权限/投影 editable 出现盲区。
    assert set(HOME_DESK_OF.keys()) == set(OBJECT_TYPES)


def test_every_home_desk_is_a_real_desk():
    assert set(HOME_DESK_OF.values()) <= set(DESKS)


def test_home_desk_of_unmapped_type_rejected():
    with pytest.raises(WriteAuthorityViolation):
        home_desk_of("not_a_real_object_type")


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #1：单一真相源（SingleSourceViolation）—— 任一台维护独立真相状态 → 拒
# ─────────────────────────────────────────────────────────────────────────────
def test_desk_consistent_state_passes_single_source():
    # 正路径：台呈与图一致的（派生）真相态 → 不误伤。
    g, node, fq = _graph_with_factor()
    g.assert_single_source(DESK_FACTOR, {node.node_id: fq.state_axes()})  # 不抛即过


def test_desk_divergent_state_rejected():
    # 种坏门：某台维护一份与图矛盾的私有真相态（evidence 谎称 sufficient，图实为 untested）。
    # MUT：assert_single_source 关掉轴比对 → 本断言转红（漂移被放过）。
    g, node, fq = _graph_with_factor()
    assert fq.evidence == EVIDENCE_UNTESTED
    divergent = {**fq.state_axes(), "evidence": EVIDENCE_SUFFICIENT}
    with pytest.raises(SingleSourceViolation):
        g.assert_single_source(DESK_STRATEGY, {node.node_id: divergent})


def test_two_desks_conflicting_state_caught():
    # 卡对抗规格 verbatim：构造两台不同状态 → 单一源门必抓矛盾。
    # 台A 呈 canonical（=图），台B 呈漂移态 → 跨台门对照唯一真相源（图）抓出台B。
    g, node, fq = _graph_with_factor()
    canonical = fq.state_axes()
    deskA_claim = dict(canonical)  # 与图一致
    deskB_claim = {**canonical, "governance": "approved"}  # 与图矛盾（图实为 unreviewed）
    with pytest.raises(SingleSourceViolation):
        g.assert_single_source_across_desks(
            {DESK_FACTOR: {node.node_id: deskA_claim}, DESK_STRATEGY: {node.node_id: deskB_claim}}
        )


def test_desk_claiming_unknown_node_rejected():
    # 台对「图里不存在的节点」声称真相态 = 维护图外独立状态 → 拒（绕过 Research Graph 自存）。
    g, node, fq = _graph_with_factor()
    with pytest.raises(SingleSourceViolation):
        g.assert_single_source(DESK_STRATEGY, {"qro_ghost_node": {"evidence": EVIDENCE_SUFFICIENT}})


def test_projection_is_derived_not_independent_store():
    # 投影是派生只读视图、不存独立真相：update_node 后重新投影必反映新态（无缓存漂移）。
    g, node, fq = _graph_with_factor()
    v0 = {nv.node_id: nv for nv in g.project(DESK_FACTOR).node_views}[node.node_id]
    assert v0.evidence == EVIDENCE_UNTESTED
    # 经命令迁移状态（同身份新态）
    fq2 = _factor_qro("mom@v1", evidence=EVIDENCE_SUFFICIENT)
    g.apply(CanonicalCommand(command_type=CMD_UPDATE_NODE, actor=ACTOR_AGENT, target_desk=DESK_FACTOR, payload={"qro": fq2}))
    v1 = {nv.node_id: nv for nv in g.project(DESK_FACTOR).node_views}[node.node_id]
    assert v1.evidence == EVIDENCE_SUFFICIENT  # 投影跟随唯一真相源、不滞留旧态


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #2：typed contract / 真 QRO 进图（NodeAdmissionError）
# ─────────────────────────────────────────────────────────────────────────────
def test_non_qro_object_rejected_from_graph():
    # 种坏门：裸 dict / duck 对象冒充节点进图（绕信封 = 绕单一真相源）。
    from types import SimpleNamespace

    g = ResearchGraph()
    for fake in [{"object_type": "factor"}, SimpleNamespace(object_type="factor", identity="x")]:
        with pytest.raises(NodeAdmissionError):
            g.apply(CanonicalCommand(command_type=CMD_CREATE_NODE, actor=ACTOR_AGENT, target_desk=DESK_FACTOR, payload={"qro": fake}))


def test_signal_node_without_typed_contract_rejected():
    # 种坏门：signal QRO 被篡改成空 typed_contract 再进图。图作为 §1 chokepoint 独立 re-assert → 拒。
    # MUT：_admit_qro 删 CONTRACT_REQUIRING_TYPES 校验 → 转红。
    sig = _signal_qro()
    object.__setattr__(sig, "typed_contract", {})  # 篡改：模拟绕过信封构造期校验
    g = ResearchGraph()
    with pytest.raises(NodeAdmissionError):
        g.apply(_create(DESK_SIGNAL, sig, actor=ACTOR_AGENT))


def test_signal_node_with_contract_admitted():
    # 正路径：带 typed contract 的 signal 正常进图（不误伤）。
    g = ResearchGraph()
    node = g.apply(_create(DESK_SIGNAL, _signal_qro(), actor=ACTOR_AGENT))
    assert node.qro.object_type == OBJ_SIGNAL
    assert node.qro.typed_contract["output_kind"] == "xs_score"


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #3：canonical command 落点（CanonicalCommandViolation）
# ─────────────────────────────────────────────────────────────────────────────
def test_apply_rejects_non_command():
    g = ResearchGraph()
    for bad in [{"command_type": "create_node"}, "create_node", None]:
        with pytest.raises(CanonicalCommandViolation):
            g.apply(bad)


def test_graphnode_without_command_ref_rejected():
    # 节点构造期就拦缺 command_ref（改动必经 canonical command 落图）。
    with pytest.raises(CanonicalCommandViolation):
        GraphNode(qro=_factor_qro(), command_ref="")


def test_smuggled_node_caught_by_assert_commanded():
    # 种坏门：绕 apply 直插 _nodes（维护图外状态 / 手动改动未落命令），command_ref 不在命令账。
    # MUT：assert_commanded 删 command_ref ∈ 命令账校验 → 转红（偷渡节点被放过）。
    g, node, fq = _graph_with_factor()
    g.assert_commanded()  # 干净图先过
    smuggled = GraphNode(qro=_strategy_qro("smuggled"), command_ref="cmd_not_in_log_xxxx")
    g._nodes[smuggled.node_id] = smuggled  # 裸写绕过 apply
    with pytest.raises(CanonicalCommandViolation):
        g.assert_commanded()


def test_all_changes_via_apply_are_commanded():
    # 正路径：全程经 apply → 每个节点/边/交接都有命令账凭证。
    g, fnode, fq = _graph_with_factor()
    snode = g.apply(_create(DESK_STRATEGY, _strategy_qro(), actor=ACTOR_AGENT))
    g.apply(CanonicalCommand(command_type=CMD_ADD_EDGE, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY, payload={"src": snode.node_id, "dst": fnode.node_id, "edge_type": EDGE_DEPENDENCY}))
    g.assert_commanded()  # 不抛即过


def test_command_is_content_addressed_single_source():
    cmd = _create(DESK_FACTOR, _factor_qro())
    assert cmd.command_id.startswith("cmd_")
    # id 走单一源 content_hash（前缀 + 16 位指纹族·不另造哈希算法）。
    assert len(cmd.command_id) == len("cmd_") + 16


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #4：DeskHandoff resolved 缺 produced_ref（HandoffIncompleteError）
# ─────────────────────────────────────────────────────────────────────────────
def test_resolved_handoff_without_produced_ref_rejected():
    # 种坏门：构造一条 resolved 但无 produced_ref 的交接。
    # MUT：DeskHandoff.__post_init__ 删 produced_ref 检查 → 转红。
    with pytest.raises(HandoffIncompleteError):
        DeskHandoff(from_desk=DESK_STRATEGY, to_desk=DESK_FACTOR, requested_asset="mom@v1", status=HANDOFF_RESOLVED, produced_ref="")


def test_resolve_handoff_command_without_produced_ref_rejected():
    # 经命令解决交接时缺 produced_ref → 同样在 resolved 构造期被拦。
    g = ResearchGraph()
    h = DeskHandoff(from_desk=DESK_STRATEGY, to_desk=DESK_FACTOR, requested_asset="mom@v1", status=HANDOFF_OPEN, created_by=ACTOR_AGENT)
    g.apply(CanonicalCommand(command_type=CMD_OPEN_HANDOFF, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY, payload={"handoff": h}))
    with pytest.raises(HandoffIncompleteError):
        g.apply(CanonicalCommand(command_type=CMD_RESOLVE_HANDOFF, actor=ACTOR_AGENT, target_desk=DESK_FACTOR, payload={"handoff_id": h.handoff_id, "produced_ref": "", "resolved_by": ACTOR_AGENT}))


def test_resolve_handoff_with_produced_ref_ok():
    # 正路径：带 produced_ref 解决交接 → resolved（不误伤）。
    g, fnode, fq = _graph_with_factor()
    h = DeskHandoff(from_desk=DESK_STRATEGY, to_desk=DESK_FACTOR, requested_asset="mom@v1", status=HANDOFF_OPEN, created_by=ACTOR_AGENT)
    g.apply(CanonicalCommand(command_type=CMD_OPEN_HANDOFF, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY, payload={"handoff": h}))
    resolved = g.apply(CanonicalCommand(command_type=CMD_RESOLVE_HANDOFF, actor=ACTOR_AGENT, target_desk=DESK_FACTOR, payload={"handoff_id": h.handoff_id, "produced_ref": fnode.node_id, "resolved_by": ACTOR_AGENT, "evidence_refs": ("ev1",)}))
    assert resolved.status == HANDOFF_RESOLVED
    assert resolved.produced_ref == fnode.node_id
    assert resolved.handoff_id == h.handoff_id  # 解决不改身份


def test_rejected_handoff_needs_no_produced_ref():
    # 不误伤：rejected（拒绝产出）态无需 produced_ref。
    h = DeskHandoff(from_desk=DESK_STRATEGY, to_desk=DESK_FACTOR, requested_asset="x", status=HANDOFF_REJECTED)
    assert h.status == HANDOFF_REJECTED and h.produced_ref == ""


def test_handoff_created_by_must_be_four_class_actor():
    with pytest.raises(ResearchGraphError):
        DeskHandoff(from_desk=DESK_STRATEGY, to_desk=DESK_FACTOR, requested_asset="x", created_by="rogue_bot")


def test_resolve_unknown_handoff_rejected():
    g = ResearchGraph()
    with pytest.raises(GraphIntegrityError):
        g.apply(CanonicalCommand(command_type=CMD_RESOLVE_HANDOFF, actor=ACTOR_AGENT, target_desk=DESK_FACTOR, payload={"handoff_id": "handoff_ghost", "produced_ref": "x"}))


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #5：写权限按台隔离（WriteAuthorityViolation）—— 策略台直接写 Factor → 拒
# ─────────────────────────────────────────────────────────────────────────────
def test_strategy_desk_cannot_write_factor():
    # 种坏门（§2 verbatim）：策略台直接 create 一个 Factor 节点。
    # MUT：_assert_write_authority 关掉 home 比对 → 转红。
    g = ResearchGraph()
    with pytest.raises(WriteAuthorityViolation):
        g.apply(_create(DESK_STRATEGY, _factor_qro(), actor=ACTOR_AGENT))


@pytest.mark.parametrize(
    "desk,obj_type",
    [
        (DESK_STRATEGY, OBJ_FACTOR),  # 策略台写因子
        (DESK_FACTOR, OBJ_MODEL),  # 因子台写模型
        (DESK_SIGNAL, OBJ_STRATEGY_BOOK),  # 信号台写策略
        (DESK_MODEL, OBJ_SIGNAL),  # 模型台写信号
        (DESK_BACKTEST, OBJ_EXECUTION_POLICY),  # 回测台写执行策略
    ],
)
def test_non_home_desk_write_rejected(desk, obj_type):
    g = ResearchGraph()
    qro = QualifiedResearchObject(
        object_type=obj_type,
        natural_key="x1",
        actor=ACTOR_AGENT,
        typed_contract={"output_kind": "k"} if obj_type == OBJ_SIGNAL else {},
    )
    with pytest.raises(WriteAuthorityViolation):
        g.apply(_create(desk, qro, actor=ACTOR_AGENT))


def test_factor_desk_can_write_factor():
    g, node, fq = _graph_with_factor()  # 正路径：home 台写本台对象（不误伤）
    assert node.home_desk == DESK_FACTOR


def test_strategy_desk_can_reference_factor_via_dependency_edge():
    # 不误伤（§2「策略台引用 factor id」）：策略台加 strategy→factor 依赖边 = 引用、非写 factor。
    g, fnode, fq = _graph_with_factor()
    snode = g.apply(_create(DESK_STRATEGY, _strategy_qro(), actor=ACTOR_AGENT))
    edge = g.apply(CanonicalCommand(command_type=CMD_ADD_EDGE, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY, payload={"src": snode.node_id, "dst": fnode.node_id, "edge_type": EDGE_DEPENDENCY}))
    assert edge.edge_type == EDGE_DEPENDENCY
    assert edge.src == snode.node_id and edge.dst == fnode.node_id


def test_strategy_desk_cannot_add_outgoing_edge_from_factor():
    # 种坏门：策略台想从 factor 节点拉出边（= 改 factor 的血统/依赖 = 写 factor）→ 拒。
    g, fnode, fq = _graph_with_factor()
    snode = g.apply(_create(DESK_STRATEGY, _strategy_qro(), actor=ACTOR_AGENT))
    with pytest.raises(WriteAuthorityViolation):
        g.apply(CanonicalCommand(command_type=CMD_ADD_EDGE, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY, payload={"src": fnode.node_id, "dst": snode.node_id, "edge_type": EDGE_LINEAGE}))


def test_update_node_also_authority_gated():
    # update_node 同受写权限门：策略台改 factor 状态 → 拒。
    g, fnode, fq = _graph_with_factor()
    with pytest.raises(WriteAuthorityViolation):
        g.apply(CanonicalCommand(command_type=CMD_UPDATE_NODE, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY, payload={"qro": _factor_qro("mom@v1", evidence=EVIDENCE_SUFFICIENT)}))


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #6：机构级投影含 math/consistency 轴（ProjectionError）
# ─────────────────────────────────────────────────────────────────────────────
def test_institutional_projection_includes_math_consistency():
    # 正路径：声称机构级的投影，每个 NodeView 带 theory/consistency（从 QRO 单一源读）→ 过。
    g, node, fq = _graph_with_factor()
    proj = g.project(DESK_FACTOR, claims_institutional=True)
    v = proj.node_views[0]
    assert v.theory == fq.theory and v.consistency == fq.consistency
    assert_institutional_projection(proj)  # 不抛即过


def test_institutional_projection_missing_math_axis_rejected():
    # 种坏门：声称机构级，但某 NodeView 的 theory/consistency 被裁成空（非枚举值）。
    # MUT：assert_institutional_projection 删轴校验 → 转红。
    stripped = NodeView(
        node_id="qro_x", object_type=OBJ_FACTOR, natural_key="x", editable=True,
        definition="implemented", theory="", consistency="", evidence="untested",
        governance="unreviewed", runtime="offline",
    )
    proj = DeskProjection(
        desk=DESK_FACTOR, node_views=(stripped,), edge_views=(), handoffs=(),
        editable_types=frozenset({OBJ_FACTOR}), claims_institutional=True,
    )
    with pytest.raises(ProjectionError):
        assert_institutional_projection(proj)


def test_non_institutional_projection_can_be_lean():
    # 不误伤：未声称机构级的投影即便缺轴也放行（§2 当前台决定可见内容·非机构级可精简）。
    stripped = NodeView(
        node_id="qro_x", object_type=OBJ_FACTOR, natural_key="x", editable=True,
        definition="implemented", theory="", consistency="", evidence="untested",
        governance="unreviewed", runtime="offline",
    )
    proj = DeskProjection(
        desk=DESK_FACTOR, node_views=(stripped,), edge_views=(), handoffs=(),
        editable_types=frozenset({OBJ_FACTOR}), claims_institutional=False,
    )
    assert_institutional_projection(proj)  # 不抛即过


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #7 / projection 正确性（gate ④ 不误伤）
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("desk", sorted(DESKS))
def test_projection_editable_only_home_types(desk):
    # 每台投影的可编辑类型 = 恰好它的 home 类型（§2 写权限按台隔离·当前台决定可编辑类型）。
    g = ResearchGraph()
    proj = g.project(desk)
    expected = {t for t, home in HOME_DESK_OF.items() if home == desk}
    assert set(proj.editable_types) == expected


def test_projection_node_views_carry_six_axes():
    # 投影把六轴如实带给当前台（分离·不混单绿灯）。
    g, node, fq = _graph_with_factor()
    v = g.project(DESK_FACTOR).node_views[0]
    assert (v.definition, v.theory, v.consistency, v.evidence, v.governance, v.runtime) == (
        fq.definition, fq.theory, fq.consistency, fq.evidence, fq.governance, fq.runtime,
    )


def test_projection_editable_flag_per_desk():
    # 同一节点：在 home 台 editable=True、在他台 editable=False（写权限隔离的投影面）。
    g, node, fq = _graph_with_factor()
    assert g.project(DESK_FACTOR).node_views[0].editable is True
    assert g.project(DESK_STRATEGY).node_views[0].editable is False


def test_handoff_projected_to_involved_desks_only():
    g = ResearchGraph()
    h = DeskHandoff(from_desk=DESK_STRATEGY, to_desk=DESK_FACTOR, requested_asset="x", status=HANDOFF_OPEN, created_by=ACTOR_AGENT)
    g.apply(CanonicalCommand(command_type=CMD_OPEN_HANDOFF, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY, payload={"handoff": h}))
    assert len(g.project(DESK_STRATEGY).handoffs) == 1  # from_desk 命中
    assert len(g.project(DESK_FACTOR).handoffs) == 1  # to_desk 命中
    assert len(g.project(DESK_MODEL).handoffs) == 0  # 无关台不投影


def test_unknown_desk_rejected():
    g = ResearchGraph()
    with pytest.raises(ResearchGraphError):
        g.project("nonexistent_desk")


# ─────────────────────────────────────────────────────────────────────────────
# 身份单一源（红线：node_id=qro.identity·不另造哈希族）
# ─────────────────────────────────────────────────────────────────────────────
def test_node_id_is_qro_identity():
    g, node, fq = _graph_with_factor()
    assert node.node_id == fq.identity  # 复用信封身份，绝不另造
    assert fq.identity.startswith("qro_")


def test_edge_id_content_addressed_single_source():
    g, fnode, fq = _graph_with_factor()
    snode = g.apply(_create(DESK_STRATEGY, _strategy_qro(), actor=ACTOR_AGENT))
    edge = g.apply(CanonicalCommand(command_type=CMD_ADD_EDGE, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY, payload={"src": snode.node_id, "dst": fnode.node_id, "edge_type": EDGE_DEPENDENCY}))
    expected = "edge_" + content_hash({"src": snode.node_id, "dst": fnode.node_id, "edge_type": EDGE_DEPENDENCY})
    assert edge.edge_id == expected


def test_handoff_id_content_addressed():
    h = DeskHandoff(from_desk=DESK_STRATEGY, to_desk=DESK_FACTOR, requested_asset="mom@v1", created_by=ACTOR_AGENT)
    expected = "handoff_" + content_hash({"from_desk": DESK_STRATEGY, "to_desk": DESK_FACTOR, "requested_asset": "mom@v1", "created_by": ACTOR_AGENT})
    assert h.handoff_id == expected


def test_command_actor_must_be_four_class():
    with pytest.raises(CanonicalCommandViolation):
        CanonicalCommand(command_type=CMD_CREATE_NODE, actor="rogue_bot", target_desk=DESK_FACTOR, payload={"qro": _factor_qro()})


def test_command_target_desk_must_be_real():
    with pytest.raises(CanonicalCommandViolation):
        CanonicalCommand(command_type=CMD_CREATE_NODE, actor=ACTOR_AGENT, target_desk="ghost_desk", payload={"qro": _factor_qro()})


# ─────────────────────────────────────────────────────────────────────────────
# frozen / 幂等 / 无悬空（扩展不替换·内容寻址纪律）
# ─────────────────────────────────────────────────────────────────────────────
def test_graph_node_frozen():
    g, node, fq = _graph_with_factor()
    with pytest.raises(FrozenInstanceError):
        node.command_ref = "x"  # type: ignore[misc]


def test_command_and_handoff_frozen():
    cmd = _create(DESK_FACTOR, _factor_qro())
    with pytest.raises(FrozenInstanceError):
        cmd.actor = ACTOR_AGENT  # type: ignore[misc]
    h = DeskHandoff(from_desk=DESK_STRATEGY, to_desk=DESK_FACTOR, requested_asset="x")
    with pytest.raises(FrozenInstanceError):
        h.status = HANDOFF_RESOLVED  # type: ignore[misc]


def test_create_node_idempotent_same_state():
    # 内容寻址幂等：同身份 + 同态再 create → no-op，图大小不变。
    g, node, fq = _graph_with_factor()
    again = g.apply(_create(DESK_FACTOR, _factor_qro("mom@v1")))
    assert again.node_id == node.node_id
    assert len(g) == 1


def test_create_node_same_id_different_state_rejected():
    # 不静默覆盖：同身份不同态走 create → 拒（必须 update_node 显式迁移）。
    g, node, fq = _graph_with_factor()
    with pytest.raises(CanonicalCommandViolation):
        g.apply(_create(DESK_FACTOR, _factor_qro("mom@v1", evidence=EVIDENCE_SUFFICIENT)))


def test_update_node_missing_target_rejected():
    g = ResearchGraph()
    with pytest.raises(CanonicalCommandViolation):
        g.apply(CanonicalCommand(command_type=CMD_UPDATE_NODE, actor=ACTOR_AGENT, target_desk=DESK_FACTOR, payload={"qro": _factor_qro("ghost")}))


def test_add_edge_dangling_rejected():
    # 无悬空（§8 DAG 精神）：加边引用不存在的节点 → 拒。
    g, fnode, fq = _graph_with_factor()
    with pytest.raises(GraphIntegrityError):
        g.apply(CanonicalCommand(command_type=CMD_ADD_EDGE, actor=ACTOR_AGENT, target_desk=DESK_FACTOR, payload={"src": fnode.node_id, "dst": "qro_ghost", "edge_type": EDGE_LINEAGE}))


def test_graph_does_not_mutate_incorporated_qro():
    # 扩展不替换：收编只读——图存的就是原 QRO 对象、frozen 未被改写。
    fq = _factor_qro()
    g = ResearchGraph()
    node = g.apply(_create(DESK_FACTOR, fq))
    assert node.qro is fq  # 同一对象（未复制改写）
    assert node.qro.state_axes() == fq.state_axes()
