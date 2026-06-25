"""CanonicalCommand 全栈（A-CMD）的【对抗式】测试（GOAL §1/§2 · RULES §2）。

验收标准不是「函数跑通」，是「**种一个已知坏门，通道必抓，否则门是纸做的**」。六个命门各种坏：
  #1 通道唯一：绕 bus 直接 graph.apply（user 手动改动未落 canonical command 通道）→ 拒
              （MUT：assert_single_channel 关对账 → 红）★ 卡点：绕过 canonical command MUT 必抓
  #2 actor 四类：命令 actor 非四类动作来源 → 拒（MUT：关 actor 成员校验 → 红）★ 卡点：actor 四类 MUT 必抓
  #3 目标台：命令意图缺/错目标台、未知语义动作 → 拒（MUT：关枚举校验 → 红）
  #4 内容寻址：command_id 缺/伪造（≠ 单一源 content_hash 重算）→ 拒（MUT：关重算 → 红）
  #5 payload schema：create/update 缺真 QRO、link 缺 src/dst/合法 edge_type、handoff 缺必填 → 拒
  #6 provenance 同链 + 相容：user 手动与 agent 同进一本账；actor 与来源面不相容（洗白）→ 拒
外加卡四条可证伪验收：① 手动改动未落 canonical command → 拒（#1）② actor 非四类/缺目标台/缺内容寻址 →
拒（#2/#3/#4）③ agent 与 user 手动落同一 audit/lineage（#6 同链）④ 正路径合法命令落图正确·不误伤。
身份/翻译/相容三张单一源表全覆盖自检（防漂）；frozen 不可原地改。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.lineage.ids import content_hash
from app.qro.envelope import (
    ACTOR_AGENT,
    ACTOR_SCHEDULED_AGENT,
    ACTOR_USER_CONFIRMED_AGENT,
    ACTOR_USER_MANUAL,
    ACTOR_CLASSES,
    EVIDENCE_SUFFICIENT,
    OBJ_FACTOR,
    OBJ_SIGNAL,
    OBJ_STRATEGY_BOOK,
    QualifiedResearchObject,
)
from app.graph import (
    CMD_CREATE_NODE,
    DESK_FACTOR,
    DESK_RESEARCH,
    DESK_SIGNAL,
    DESK_STRATEGY,
    DESKS,
    EDGE_DEPENDENCY,
    EDGE_DESK_HANDOFF,
    EDGE_LINEAGE,
    HANDOFF_RESOLVED,
    CanonicalCommand,
    DeskHandoff,
    WriteAuthorityViolation,
)
from app.command import (
    ACTION_CREATE_ASSET,
    ACTION_FULFILL_HANDOFF,
    ACTION_LINK_ASSETS,
    ACTION_REQUEST_HANDOFF,
    ACTION_TO_COMMAND,
    ACTION_UPDATE_ASSET,
    ACTIONS,
    ACTOR_SURFACE_ALLOWED,
    ORIGIN_AGENT_RUNTIME,
    ORIGIN_API,
    ORIGIN_CANVAS,
    ORIGIN_FORM,
    ORIGIN_IDE,
    ORIGIN_SCHEDULER,
    ORIGIN_SURFACES,
    ChannelBypassViolation,
    CommandBus,
    CommandIntent,
    CommandValidationError,
    ContentAddressViolation,
    LedgerEntry,
    PayloadSchemaError,
    Provenance,
    ProvenanceError,
    agent_provenance,
    assert_actor_surface_coherent,
    assert_content_addressed,
    manual_provenance,
    translate_intent,
    validate_intent,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _factor_qro(nk: str = "mom@v1", **over) -> QualifiedResearchObject:
    return QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key=nk, actor=ACTOR_USER_MANUAL, **over)


def _strategy_qro(nk: str = "strat1", **over) -> QualifiedResearchObject:
    return QualifiedResearchObject(object_type=OBJ_STRATEGY_BOOK, natural_key=nk, actor=ACTOR_AGENT, **over)


def _signal_qro(nk: str = "sig1", **over) -> QualifiedResearchObject:
    over.setdefault("typed_contract", {"output_kind": "xs_score", "horizon": 5})
    return QualifiedResearchObject(object_type=OBJ_SIGNAL, natural_key=nk, actor=ACTOR_AGENT, **over)


def _create_intent(qro, desk, prov=None, action=ACTION_CREATE_ASSET) -> CommandIntent:
    return CommandIntent(
        action=action, target_desk=desk, provenance=prov or manual_provenance(ORIGIN_CANVAS), args={"qro": qro}
    )


def _bus_with_factor(nk: str = "mom@v1", **over):
    bus = CommandBus()
    receipt = bus.submit(_create_intent(_factor_qro(nk, **over), DESK_FACTOR))
    return bus, receipt


# ─────────────────────────────────────────────────────────────────────────────
# 单一源 / 翻译表 / 相容表全覆盖（防漂·扩展不替换·三张表是单一源）
# ─────────────────────────────────────────────────────────────────────────────
def test_action_to_command_covers_actions_exactly():
    # 语义翻译表必须恰好覆盖 ACTIONS（不漏不多）——否则某语义动作翻不出 / 翻到野命令。
    assert set(ACTION_TO_COMMAND.keys()) == set(ACTIONS)


def test_actor_surface_allowed_covers_actor_classes_exactly():
    # 相容表 key 必恰好 == 四类 actor（单一源 ACTOR_CLASSES·防漂）。
    assert set(ACTOR_SURFACE_ALLOWED.keys()) == set(ACTOR_CLASSES)


def test_all_allowed_surfaces_are_real_surfaces():
    for surfs in ACTOR_SURFACE_ALLOWED.values():
        assert set(surfs) <= set(ORIGIN_SURFACES)


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #1：通道唯一（ChannelBypassViolation）★ 绕过 canonical command MUT 必抓
# ─────────────────────────────────────────────────────────────────────────────
def test_clean_bus_passes_single_channel():
    # 正路径：全程经 submit → 图命令账 ⊆ 通道账 → 对账过（不误伤）。
    bus, _ = _bus_with_factor()
    bus.assert_single_channel()  # 不抛即过


def test_direct_graph_apply_bypass_caught():
    # 种坏门（卡验收 ①）：绕 bus 直接 graph.apply 一条命令（= user 手动改动未落 canonical command 通道）。
    # 真门：该命令 id ∉ 通道账 → ChannelBypassViolation。
    # MUT：assert_single_channel 关掉「图命令 ∈ 通道账」对账 → 本断言转红（绕过被放过）。
    bus, _ = _bus_with_factor()
    bus.assert_single_channel()  # 绕过前：干净
    rogue = CanonicalCommand(
        command_type=CMD_CREATE_NODE, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY,
        payload={"qro": _strategy_qro("rogue")},
    )
    bus._graph.apply(rogue)  # 绕通道直写图（账无此命令）
    with pytest.raises(ChannelBypassViolation):
        bus.assert_single_channel()


def test_single_channel_discriminates_clean_vs_bypass():
    # 同一测内「干净必过 + 绕过必抓」——一举 kill always-pass 与 always-raise 两个平凡 mutant：
    #   always-pass mutant → 绕过那步不抛 → 后半断言红；always-raise mutant → 干净那步抛 → 前半断言红。
    bus, _ = _bus_with_factor()
    bus.assert_single_channel()  # 干净：必不抛
    bus._graph.apply(
        CanonicalCommand(command_type=CMD_CREATE_NODE, actor=ACTOR_AGENT, target_desk=DESK_SIGNAL,
                         payload={"qro": _signal_qro("rogue2")})
    )
    with pytest.raises(ChannelBypassViolation):  # 绕过：必抓
        bus.assert_single_channel()


def test_bypass_reconciliation_is_load_bearing():
    # 显式证伪力：手算「图命令账 − 通道账」差集——绕过后差集非空（坏门的命令在此）。
    # 一个忽略该差集的 mutant 门必放过；真门以差集非空为据抛 → 证明对账逻辑 load-bearing。
    bus, _ = _bus_with_factor()
    minted = bus.ledger().command_ids()
    graph_ids = {c.command_id for c in bus._graph.command_log()}
    assert graph_ids <= minted  # 干净：图命令全在通道账
    rogue = CanonicalCommand(command_type=CMD_CREATE_NODE, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY,
                             payload={"qro": _strategy_qro("rogue3")})
    bus._graph.apply(rogue)
    graph_ids2 = {c.command_id for c in bus._graph.command_log()}
    assert rogue.command_id in (graph_ids2 - bus.ledger().command_ids())  # 差集抓住绕过命令


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #2：actor 四类（ProvenanceError / CommandValidationError）★ actor 四类 MUT 必抓
# ─────────────────────────────────────────────────────────────────────────────
def test_provenance_rejects_non_four_class_actor():
    # 种坏门：构造 actor 非四类的 provenance。
    # MUT：assert_actor_surface_coherent 关掉 `actor ∈ ACTOR_CLASSES` 成员校验 → 本断言转红。
    with pytest.raises(ProvenanceError):
        Provenance(actor="rogue_bot", surface=ORIGIN_CANVAS)


def test_validate_intent_reasserts_forged_actor():
    # 种坏门（卡验收 ②）：先建合法 provenance，再 object.__setattr__ 篡改 actor 绕构造期门。
    # 真门：validate_intent 在通道入口独立 re-assert → 抓。MUT：关 re-assert → 红。
    prov = manual_provenance(ORIGIN_CANVAS)
    object.__setattr__(prov, "actor", "rogue_bot")  # 篡改（frozen 绕过）
    intent = CommandIntent(action=ACTION_CREATE_ASSET, target_desk=DESK_FACTOR, provenance=prov, args={"qro": _factor_qro()})
    with pytest.raises((CommandValidationError, ProvenanceError)):
        validate_intent(intent)


def test_submit_rejects_forged_actor_end_to_end():
    # 端到端：篡改 actor 的意图过 submit → 通道在落图前即拒（不污染图/账）。
    bus = CommandBus()
    prov = manual_provenance(ORIGIN_FORM)
    object.__setattr__(prov, "actor", "")  # 空 actor（非四类）
    intent = CommandIntent(action=ACTION_CREATE_ASSET, target_desk=DESK_FACTOR, provenance=prov, args={"qro": _factor_qro()})
    with pytest.raises((CommandValidationError, ProvenanceError)):
        bus.submit(intent)
    assert bus.node_count() == 0 and len(bus.ledger()) == 0  # 拒后图与账皆未被污染


@pytest.mark.parametrize("actor", sorted(ACTOR_CLASSES))
def test_four_class_actors_all_accepted_on_api_surface(actor):
    # 不误伤：四类 actor 各自经其相容来源面（api 共享边界对全类放行）建 provenance → 过。
    prov = Provenance(actor=actor, surface=ORIGIN_API)
    assert prov.actor == actor and prov.surface == ORIGIN_API


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #3：目标台 / 语义动作（CommandValidationError）
# ─────────────────────────────────────────────────────────────────────────────
def test_validate_intent_rejects_unknown_desk():
    intent = CommandIntent(action=ACTION_CREATE_ASSET, target_desk="ghost_desk", provenance=manual_provenance(ORIGIN_CANVAS), args={"qro": _factor_qro()})
    with pytest.raises(CommandValidationError):
        validate_intent(intent)


def test_validate_intent_rejects_unknown_action():
    intent = CommandIntent(action="frobnicate", target_desk=DESK_FACTOR, provenance=manual_provenance(ORIGIN_CANVAS), args={"qro": _factor_qro()})
    with pytest.raises(CommandValidationError):
        validate_intent(intent)


@pytest.mark.parametrize("desk", sorted(DESKS))
def test_real_desks_accepted(desk):
    # 不误伤：所有真实台都过目标台门（schema 是否过取决于该动作的 args，这里只验台门不误伤）。
    intent = CommandIntent(action=ACTION_REQUEST_HANDOFF, target_desk=desk, provenance=agent_provenance(),
                           args={"from_desk": desk, "to_desk": DESK_FACTOR, "requested_asset": "x"})
    validate_intent(intent)  # 不抛即过


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #4：内容寻址（ContentAddressViolation）
# ─────────────────────────────────────────────────────────────────────────────
def test_genuine_command_is_content_addressed():
    cmd = translate_intent(_create_intent(_factor_qro(), DESK_FACTOR))
    assert_content_addressed(cmd)  # 不抛即过
    assert cmd.command_id.startswith("cmd_")
    assert len(cmd.command_id) == len("cmd_") + 16  # 单一源 16 位族（lineage.ids.HASH_LEN）


def test_forged_command_id_caught():
    # 种坏门：伪造 command_id（前缀/长度对、哈希错）。
    # 真门：用图命令自身单一源派生重算 ≠ 声称值 → 拒。MUT：关重算比对 → 红。
    cmd = translate_intent(_create_intent(_factor_qro("forge1"), DESK_FACTOR))
    object.__setattr__(cmd, "command_id", "cmd_0000000000000000")  # 16 位、前缀对，但非真哈希
    with pytest.raises(ContentAddressViolation):
        assert_content_addressed(cmd)


def test_missing_or_malformed_command_id_caught():
    cmd = translate_intent(_create_intent(_factor_qro("forge2"), DESK_FACTOR))
    for bad in ["", "nothash", "xyz_abcdef0123456789", "cmd_short"]:
        object.__setattr__(cmd, "command_id", bad)
        with pytest.raises(ContentAddressViolation):
            assert_content_addressed(cmd)


def test_command_id_reuses_single_source_content_hash():
    # command_id 走单一源 content_hash（与图账一致·不另造哈希族）——translate 出的命令落图后图账同 id。
    bus = CommandBus()
    receipt = bus.submit(_create_intent(_factor_qro("idcheck"), DESK_FACTOR))
    logged = bus._graph.command_log()[-1]
    assert logged.command_id == receipt.command_id  # 通道铸的 id == 图账 id（同源）


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #5：payload schema（PayloadSchemaError）—— A-GRAPH-1 信封未做的那层
# ─────────────────────────────────────────────────────────────────────────────
def test_create_without_real_qro_rejected():
    # 种坏门：create 的 args['qro'] 是裸 dict / 缺失（非真信封）。
    for bad_args in [{}, {"qro": {"object_type": "factor"}}, {"qro": None}]:
        intent = CommandIntent(action=ACTION_CREATE_ASSET, target_desk=DESK_FACTOR, provenance=manual_provenance(ORIGIN_CANVAS), args=bad_args)
        with pytest.raises(PayloadSchemaError):
            validate_intent(intent)


def test_link_missing_src_dst_rejected():
    for bad_args in [{"dst": "qro_x", "edge_type": EDGE_DEPENDENCY}, {"src": "qro_y", "edge_type": EDGE_DEPENDENCY}, {"src": "", "dst": "qro_x", "edge_type": EDGE_DEPENDENCY}]:
        intent = CommandIntent(action=ACTION_LINK_ASSETS, target_desk=DESK_STRATEGY, provenance=agent_provenance(), args=bad_args)
        with pytest.raises(PayloadSchemaError):
            validate_intent(intent)


def test_link_desk_handoff_edge_type_rejected():
    # desk_handoff 边不能走 link（须走 request/fulfill_handoff 动作）。
    intent = CommandIntent(action=ACTION_LINK_ASSETS, target_desk=DESK_STRATEGY, provenance=agent_provenance(),
                           args={"src": "qro_a", "dst": "qro_b", "edge_type": EDGE_DESK_HANDOFF})
    with pytest.raises(PayloadSchemaError):
        validate_intent(intent)


def test_request_handoff_missing_fields_rejected():
    intent = CommandIntent(action=ACTION_REQUEST_HANDOFF, target_desk=DESK_STRATEGY, provenance=agent_provenance(),
                           args={"from_desk": DESK_STRATEGY})  # 缺 to_desk / requested_asset
    with pytest.raises(PayloadSchemaError):
        validate_intent(intent)


def test_fulfill_handoff_missing_produced_ref_rejected():
    # §2「DeskHandoff 完成后缺 produced_ref → 拒」的命令层防御纵深（早拦·不必等图）。
    intent = CommandIntent(action=ACTION_FULFILL_HANDOFF, target_desk=DESK_FACTOR, provenance=agent_provenance(),
                           args={"handoff_id": "handoff_x", "produced_ref": ""})
    with pytest.raises(PayloadSchemaError):
        validate_intent(intent)


def test_fulfill_handoff_bad_resolved_by_rejected():
    intent = CommandIntent(action=ACTION_FULFILL_HANDOFF, target_desk=DESK_FACTOR, provenance=agent_provenance(),
                           args={"handoff_id": "handoff_x", "produced_ref": "qro_p", "resolved_by": "rogue"})
    with pytest.raises(PayloadSchemaError):
        validate_intent(intent)


# ─────────────────────────────────────────────────────────────────────────────
# 命门 #6：provenance 来源面相容（ProvenanceError）+ 同链（一本账）
# ─────────────────────────────────────────────────────────────────────────────
def test_user_manual_from_agent_runtime_rejected():
    # 种坏门：user_manual 动作伪称来自 agent_runtime（手动面 vs agent 面洗白）。
    # MUT：assert_actor_surface_coherent 关相容表查 → 红。
    with pytest.raises(ProvenanceError):
        Provenance(actor=ACTOR_USER_MANUAL, surface=ORIGIN_AGENT_RUNTIME)


def test_user_manual_from_scheduler_rejected():
    with pytest.raises(ProvenanceError):
        Provenance(actor=ACTOR_USER_MANUAL, surface=ORIGIN_SCHEDULER)


def test_agent_from_human_canvas_rejected():
    # 种坏门：自治 agent 冒充人手画布/表单/IDE（§2 那是「手动」面）。
    for surface in (ORIGIN_CANVAS, ORIGIN_FORM, ORIGIN_IDE):
        with pytest.raises(ProvenanceError):
            Provenance(actor=ACTOR_AGENT, surface=surface)


def test_scheduled_agent_from_canvas_rejected():
    with pytest.raises(ProvenanceError):
        Provenance(actor=ACTOR_SCHEDULED_AGENT, surface=ORIGIN_CANVAS)


def test_unknown_surface_rejected():
    with pytest.raises(ProvenanceError):
        Provenance(actor=ACTOR_AGENT, surface="telepathy")


@pytest.mark.parametrize("surface", [ORIGIN_CANVAS, ORIGIN_FORM, ORIGIN_IDE, ORIGIN_API])
def test_user_manual_human_surfaces_ok(surface):
    # 不误伤（§2 verbatim）：user 手动经 画布/表单/IDE/API 任一人手面 → 放行。
    prov = Provenance(actor=ACTOR_USER_MANUAL, surface=surface)
    assert prov.actor == ACTOR_USER_MANUAL


def test_user_confirmed_agent_can_use_human_and_runtime_surfaces():
    # 不误伤：人确认 + agent 执行 → 人手面或 agent 运行时皆相容。
    for surface in (ORIGIN_CANVAS, ORIGIN_API, ORIGIN_AGENT_RUNTIME):
        assert_actor_surface_coherent(ACTOR_USER_CONFIRMED_AGENT, surface)  # 不抛即过


def test_user_manual_and_agent_share_one_ledger():
    # 卡验收 ③：user 手动命令 与 agent 命令落**同一本账**（provenance 区分但同链·不分账）。
    bus = CommandBus()
    bus.submit(_create_intent(_factor_qro("manual_f"), DESK_FACTOR, manual_provenance(ORIGIN_CANVAS)))
    bus.submit(_create_intent(_strategy_qro("agent_s"), DESK_STRATEGY, agent_provenance()))
    entries = bus.ledger().entries()
    assert len(entries) == 2  # 同一本账两条
    actors = {e.actor for e in entries}
    assert actors == {ACTOR_USER_MANUAL, ACTOR_AGENT}  # 两源同链
    assert len(bus.ledger().entries_by_actor(ACTOR_USER_MANUAL)) == 1  # provenance 可区分
    assert len(bus.ledger().entries_by_actor(ACTOR_AGENT)) == 1
    # 同链证据：两条 seq 连续、在同一 ledger 对象里。
    assert [e.seq for e in entries] == [0, 1]


def test_provenance_token_stamped_into_command_origin():
    # provenance 落进 command.origin → 图命令账也带来源（通道账 ↔ 图账同源·可对账）。
    prov = manual_provenance(ORIGIN_IDE, actor_id="dev42")
    cmd = translate_intent(_create_intent(_factor_qro("origintest"), DESK_FACTOR, prov))
    assert cmd.origin == prov.token()
    assert cmd.origin.startswith("prov_")
    assert cmd.actor == ACTOR_USER_MANUAL  # actor 由 provenance 注入命令


def test_ledger_query_by_surface():
    bus = CommandBus()
    bus.submit(_create_intent(_factor_qro("f_canvas"), DESK_FACTOR, manual_provenance(ORIGIN_CANVAS)))
    bus.submit(_create_intent(_signal_qro("s_runtime"), DESK_SIGNAL, agent_provenance()))
    assert len(bus.ledger().entries_by_surface(ORIGIN_CANVAS)) == 1
    assert len(bus.ledger().entries_by_surface(ORIGIN_AGENT_RUNTIME)) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 验收 ④ / 正路径不误伤：语义翻译 → 落图正确（5 动作端到端）
# ─────────────────────────────────────────────────────────────────────────────
def test_translate_maps_each_action_to_its_command_type():
    # 每个语义动作翻成正确的图 command_type（翻译表兑现）。
    fq = _factor_qro("tt")
    cmd = translate_intent(_create_intent(fq, DESK_FACTOR))
    assert cmd.command_type == ACTION_TO_COMMAND[ACTION_CREATE_ASSET]
    cmd_u = translate_intent(_create_intent(_factor_qro("tt", evidence=EVIDENCE_SUFFICIENT), DESK_FACTOR, action=ACTION_UPDATE_ASSET))
    assert cmd_u.command_type == ACTION_TO_COMMAND[ACTION_UPDATE_ASSET]


def test_full_flow_create_link_handoff_fulfill():
    # 端到端正路径（不误伤）：建因子 + 建策略 + 策略→因子依赖边 + 跨台交接 + 交付——全经 submit 落图正确。
    bus = CommandBus()
    fr = bus.submit(_create_intent(_factor_qro("mom@v1"), DESK_FACTOR, manual_provenance(ORIGIN_CANVAS)))
    sr = bus.submit(_create_intent(_strategy_qro("s1"), DESK_STRATEGY, agent_provenance()))
    # link：策略台从 strategy 拉 dependency → factor（引用·非写 factor）。
    lr = bus.submit(CommandIntent(action=ACTION_LINK_ASSETS, target_desk=DESK_STRATEGY, provenance=agent_provenance(),
                                  args={"src": sr.affected_id, "dst": fr.affected_id, "edge_type": EDGE_DEPENDENCY}))
    assert lr.result.edge_type == EDGE_DEPENDENCY
    # request_handoff：策略台向因子台请求一个资产。
    hr = bus.submit(CommandIntent(action=ACTION_REQUEST_HANDOFF, target_desk=DESK_STRATEGY, provenance=agent_provenance(),
                                  args={"from_desk": DESK_STRATEGY, "to_desk": DESK_FACTOR, "requested_asset": "newfac"}))
    handoff_id = hr.affected_id
    # fulfill_handoff：因子台交付（带 produced_ref）。
    fhr = bus.submit(CommandIntent(action=ACTION_FULFILL_HANDOFF, target_desk=DESK_FACTOR, provenance=agent_provenance(),
                                   args={"handoff_id": handoff_id, "produced_ref": fr.affected_id, "evidence_refs": ("ev1",)}))
    assert fhr.result.status == HANDOFF_RESOLVED and fhr.result.produced_ref == fr.affected_id
    # 全程同一本账、通道唯一对账过。
    assert len(bus.ledger()) == 5
    bus.assert_single_channel()


def test_submit_returns_lineage_receipt():
    bus, receipt = _bus_with_factor("rcpt")
    assert receipt.command_id.startswith("cmd_")
    assert receipt.affected_id.startswith("qro_")  # 落图节点 id
    assert receipt.provenance.actor == ACTOR_USER_MANUAL
    assert receipt.target_desk == DESK_FACTOR


def test_idempotent_create_via_bus():
    # 内容寻址幂等（透传图语义·不误伤）：同身份同态再 create → 图大小不变。
    bus, r1 = _bus_with_factor("idem")
    r2 = bus.submit(_create_intent(_factor_qro("idem"), DESK_FACTOR))
    assert r1.affected_id == r2.affected_id
    assert bus.node_count() == 1


def test_update_requires_existing_node():
    # 透传图门（不误伤·分层防御）：update 不存在的节点 → 图拒（CanonicalCommandViolation 自图）。
    from app.graph import CanonicalCommandViolation
    bus = CommandBus()
    with pytest.raises(CanonicalCommandViolation):
        bus.submit(_create_intent(_factor_qro("ghost"), DESK_FACTOR, action=ACTION_UPDATE_ASSET))


# ─────────────────────────────────────────────────────────────────────────────
# 写权限按台隔离仍是图的门（A-CMD 不重算·分层防御）——策略台经通道写 Factor 仍被图拒。
# ─────────────────────────────────────────────────────────────────────────────
def test_write_authority_still_enforced_by_graph_through_bus():
    # A-CMD 校验 actor/台/schema/provenance，但**不**重算 home 台写权限；图在 apply 独立 re-assert。
    # 策略台经合法通道 create 一个 Factor（schema 全过）→ 图的写权限门拒（单一源·未被通道旁路削弱）。
    bus = CommandBus()
    with pytest.raises(WriteAuthorityViolation):
        bus.submit(_create_intent(_factor_qro("xdesk"), DESK_STRATEGY, agent_provenance()))
    assert bus.node_count() == 0 and len(bus.ledger()) == 0  # 图拒后账未记（落图失败不记账）


# ─────────────────────────────────────────────────────────────────────────────
# frozen（内容寻址纪律·不可原地改）
# ─────────────────────────────────────────────────────────────────────────────
def test_provenance_and_intent_frozen():
    prov = manual_provenance(ORIGIN_CANVAS)
    with pytest.raises(FrozenInstanceError):
        prov.actor = ACTOR_AGENT  # type: ignore[misc]
    intent = _create_intent(_factor_qro(), DESK_FACTOR)
    with pytest.raises(FrozenInstanceError):
        intent.action = ACTION_UPDATE_ASSET  # type: ignore[misc]


def test_receipt_and_ledger_entry_frozen():
    bus, receipt = _bus_with_factor("frz")
    with pytest.raises(FrozenInstanceError):
        receipt.command_id = "x"  # type: ignore[misc]
    entry = bus.ledger().entries()[0]
    assert isinstance(entry, LedgerEntry)
    with pytest.raises(FrozenInstanceError):
        entry.seq = 9  # type: ignore[misc]


def test_provenance_token_is_content_addressed_single_source():
    # provenance token 走单一源 content_hash（前缀 prov_·与 ids 同族·不另造哈希）。
    prov = Provenance(actor=ACTOR_AGENT, surface=ORIGIN_AGENT_RUNTIME, actor_id="a1")
    expected = "prov_" + content_hash({"actor": ACTOR_AGENT, "surface": ORIGIN_AGENT_RUNTIME, "actor_id": "a1", "session_ref": "", "request_ref": ""})
    assert prov.token() == expected
