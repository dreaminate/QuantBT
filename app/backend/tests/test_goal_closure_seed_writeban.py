"""SA-4 对抗测试：goal_closure 占位种子 write门（spine 链 / spine research-graph 命令 / graph 命令）。

种已知的坏（goal_closure 占位种子）→ 三条写路径必须 fail-closed 抓住；干净记录必须放行。
覆盖 token 三变体（goal_closure / goal-closure / goalclosure）+ 大小写不敏感 + token 藏在 id 或
任一内容字段（含内嵌 QRO payload）。另钉一条设计边界：write门只拦**写**、不拦**load**（既存残留
种子由 scripts/purge_goal_closure_seeds.py 清，不卡启动）。

变异三态（人工，见 dev 报告）：把 _carries_goal_closure_seed / _command_carries_goal_closure_seed
改成恒 False → 对应 reject 测试转红 → 还原 → 转绿。
"""

from __future__ import annotations

import json

import pytest

from app.graph.research_graph import (
    CMD_CREATE_NODE,
    DESK_STRATEGY,
    CanonicalCommand,
    CanonicalCommandViolation,
    ResearchGraph,
)
from app.qro.envelope import (
    ACTOR_USER_MANUAL,
    OBJ_STRATEGY_BOOK,
    QualifiedResearchObject,
)
from app.research_os import (
    ActorSource,
    ConsistencyStatus,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    MathematicalSpineChainRecord,
    PersistentMathematicalSpineChainRegistry,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphError,
    RuntimeStatus,
)


# ── builders ──────────────────────────────────────────────────────────────────
def _chain(**overrides) -> MathematicalSpineChainRecord:
    data = dict(
        chain_ref="math_spine_chain:writeban_clean:v1",
        data_semantics_ref="dataset_semantics:btc_1d",
        factor_ref="factor:momentum_20d",
        model_ref="model:momentum_classifier:v1",
        forecast_ref="forecast:btc_momentum:v1",
        signal_contract_ref="signal_contract:btc_momentum:v1",
        strategy_book_ref="strategy_book:btc_momentum:v1",
        portfolio_policy_ref="portfolio_policy:btc_momentum:v1",
        risk_policy_ref="risk_policy:btc_momentum:v1",
        execution_policy_ref="execution_policy:paper_btc:v1",
        backtest_run_ref="backtest_run:bt1",
        attribution_ref="attribution:bt1",
        monitor_ref="monitor:weekly_btc_momentum",
        theory_binding_refs=("tbind:momentum",),
        consistency_check_refs=("ccheck:momentum",),
        methodology_choice_ref="mchoice:standard",
        responsibility_boundary_ref="resp:standard",
        evidence_refs=("evidence:bt1",),
        validation_refs=("pytest:writeban_seed_suite",),
        consistency_verdict=ConsistencyStatus.ACCEPTED,
        target_runtime=RuntimeStatus.PAPER,
        recorded_by="u1",
    )
    data.update(overrides)
    return MathematicalSpineChainRecord(**data)


def _qro(**overrides) -> QRORecord:
    data = dict(
        qro_type=QROType.STRATEGY_BOOK,
        owner="dreaminate",
        actor=ActorSource.USER_MANUAL,
        input_contract={"strategy_id": "strategy_demo", "code_hash": "hash_code"},
        output_contract={"strategy_book_ref": "strategy:demo"},
        market="crypto",
        universe="BTCUSDT",
        horizon="30d",
        frequency="1d",
        lineage=("ide", "strategy", "save"),
        implementation_hash="strategy:hash_code",
        assumptions=("strategy source saved before graph write",),
        known_limits=("write-ban test fixture only",),
        failure_modes=("command log corruption hides audit history",),
        validation_plan=("reload graph command store",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        runtime_status=RuntimeStatus.OFFLINE,
        permission="ide.strategy:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    data.update(overrides)
    return QRORecord(**data)


def _spine_command(qro: QRORecord) -> ResearchGraphCommand:
    return ResearchGraphCommand(
        source=EntrySource.IDE,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor="dreaminate",
        payload={"qro": qro},
        evidence_refs=("unit:writeban",),
    )


def _graph_command(**overrides) -> CanonicalCommand:
    qro = QualifiedResearchObject(
        object_type=OBJ_STRATEGY_BOOK,
        natural_key=overrides.pop("natural_key", "sb_writeban_clean"),
        actor=ACTOR_USER_MANUAL,
    )
    data = dict(
        command_type=CMD_CREATE_NODE,
        actor=ACTOR_USER_MANUAL,
        target_desk=DESK_STRATEGY,
        payload={"qro": qro},
    )
    data.update(overrides)
    return CanonicalCommand(**data)


# ── (1) MathematicalSpineChain write门 ─────────────────────────────────────────
def test_record_chain_accepts_clean_chain(tmp_path):
    reg = PersistentMathematicalSpineChainRegistry(tmp_path / "mathematical_spine_chains.jsonl")
    out = reg.record_chain(_chain())
    assert out.chain_ref == "math_spine_chain:writeban_clean:v1"
    # 真持久化 + 可重放（没被门误伤）。
    reloaded = PersistentMathematicalSpineChainRegistry(reg.path)
    assert reloaded.chain(out.chain_ref).chain_ref == out.chain_ref


@pytest.mark.parametrize(
    "field, value",
    [
        ("chain_ref", "math_spine_chain:goal_closure:section_0_17:v1"),  # token 在 id
        ("data_semantics_ref", "dataset_semantics:goal_closure:btc"),     # token 在内容字段
        ("attribution_ref", "attribution:GoalClosure:local_proof:v1"),    # CamelCase→goalclosure（大小写不敏感）
        ("monitor_ref", "monitor:goal-closure:weekly"),                   # 连字符变体
    ],
)
def test_record_chain_rejects_goal_closure_seed(tmp_path, field, value):
    reg = PersistentMathematicalSpineChainRegistry(tmp_path / "mathematical_spine_chains.jsonl")
    with pytest.raises(ValueError, match="goal_closure"):
        reg.record_chain(_chain(**{field: value}))
    # 原子 fail-closed：内存 0 条、账本一行不留。
    assert reg.chains() == []
    assert (not reg.path.exists()) or reg.path.read_text(encoding="utf-8").strip() == ""


# ── (2) spine research-graph 命令 write门（research_graph_commands.jsonl 的真写口）──
def test_persistent_research_graph_apply_accepts_clean_command(tmp_path):
    store = PersistentResearchGraphStore(tmp_path / "research_graph_commands.jsonl")
    cmd_id = store.apply(_spine_command(_qro()))
    assert cmd_id
    reloaded = PersistentResearchGraphStore(store.path)
    assert any(c.command_id == cmd_id for c in reloaded.commands())


def test_persistent_research_graph_apply_rejects_goal_closure_seed(tmp_path):
    store = PersistentResearchGraphStore(tmp_path / "research_graph_commands.jsonl")
    # token 藏在 upsert_qro 的 QRO payload 内层（真实种子形态：goal_closure 在 output_contract 里）。
    tainted = _spine_command(_qro(output_contract={"strategy_book_ref": "strategy:goal_closure:section_0_17"}))
    with pytest.raises(ResearchGraphError, match="goal_closure"):
        store.apply(tainted)
    # 原子 fail-closed：内存 0 命令、账本一行不留（拒在 super().apply 与落盘之前）。
    assert store.commands() == []
    assert (not store.path.exists()) or store.path.read_text(encoding="utf-8").strip() == ""


# ── (3) graph canonical command write门（graph/research_graph.py 的唯一写口）──────
def test_research_graph_apply_accepts_clean_command():
    graph = ResearchGraph()
    graph.apply(_graph_command())
    assert len(graph.command_log()) == 1


def test_research_graph_apply_rejects_goal_closure_in_nested_qro():
    graph = ResearchGraph()
    # token 藏在内嵌 QRO 的 natural_key（QRO.identity 是 content_hash 会洗成哈希·必须扫展开后的内容）。
    cmd = _graph_command(natural_key="goal_closure:section_0_17")
    with pytest.raises(CanonicalCommandViolation, match="goal_closure"):
        graph.apply(cmd)
    assert graph.command_log() == ()  # 原子：未落账


def test_research_graph_apply_rejects_goal_closure_in_origin():
    graph = ResearchGraph()
    cmd = _graph_command(origin="goal-closure:section_0_17")  # 连字符变体·标量字段
    with pytest.raises(CanonicalCommandViolation, match="goal_closure"):
        graph.apply(cmd)
    assert graph.command_log() == ()


# ── (4) 设计边界：write门只拦写、不拦 load（残留种子留给数据 purge）──────────────────
def test_residual_goal_closure_line_still_loads_write_only(tmp_path):
    # SA-4 是*写时* fail-closed：既存残留种子行仍能 load，不卡启动；清理由
    # scripts/purge_goal_closure_seeds.py 做（中心在 main 数据目录跑）。本测试钉死这条边界——
    # 若误把门加到 load 路径，这里会红。
    from app.research_os.spine import _chain_event_row  # 复用持久化行格式

    path = tmp_path / "mathematical_spine_chains.jsonl"
    reg = PersistentMathematicalSpineChainRegistry(path)
    reg.record_chain(_chain(chain_ref="math_spine_chain:writeban_clean:v1"))  # 一条干净行

    # 手工追加一条 goal_closure 残留行（绕过 write门·模拟门之前播下的种子）。
    residual = _chain(chain_ref="math_spine_chain:goal_closure:section_0_17:v1")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(_chain_event_row(residual), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )

    # 重构 registry：load 不被 goal_closure 卡（写时门不拦 load）·残留可见→等 purge 清。
    reloaded = PersistentMathematicalSpineChainRegistry(path)
    assert reloaded.chain("math_spine_chain:writeban_clean:v1").chain_ref == "math_spine_chain:writeban_clean:v1"
    assert reloaded.chain("math_spine_chain:goal_closure:section_0_17:v1").chain_ref.endswith("section_0_17:v1")
