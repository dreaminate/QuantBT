"""Governed Compiler（A-COMPILER·§1 链 capstone）的【对抗式】测试（GOAL §1/§7/§8 · RULES §2）。

验收标准不是「函数跑通」，是「**种一个已知坏门，编译器必抓，否则门是纸做的**」。五命门各种坏 + MUT
（关掉门 → 坏门必放过 → 证明门 load-bearing·绝不 git checkout·monkeypatch 模拟坏门）：

  #1 命令未经 compiler 落 run → 拒：命令未落图（不在 command_log）→ UncommandedRunError；
     绕 compile 直造 run（不在编译账）→ RunNotCompiledError。★ 卡点：绕 compiler 直造 run MUT 必抓。
  #2 run 无 deterministic 内核身份（未经 DurableExecutor）→ 拒：假执行器返伪 node_id（≠ compute_node_id
     独立重算）/ 非 KernelRunResult / kernel_run_id 被篡改 → KernelIdentityViolation。★ MUT 必抓。
  #3 verdict 绕过 verifier/三角门 → 拒：verdict_id 非验证官单一源 compute_verdict_id 重算（伪造裁决）/
     未绑本 run（张冠李戴）→ VerdictBypassViolation。★ MUT 必抓。
  #4 promotion 未经 approval 门（approver≠creator）→ 拒：approver==creator → 审批门 ApproverEqualsCreator；
     绕审批门直造 PromotedRun / approved 却 approver==creator → PromotionGovernanceViolation。★ MUT 必抓。
  #5 正路径：合法 command+IR → deterministic run → verifier consistent + 三角 green → approval(approver≠creator)
     → 正确编译·不误伤。

收编只读核验：内核身份 re-derive 走 dag.kernel.compute_node_id（单一源·不另造）；verdict_id 重算走
verification.schema.compute_verdict_id（单一源）；approver≠creator 由 approval.gate.ApprovalGateService 强制。
frozen 产物不可原地改；治理账三段单一通道。
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from app.approval.gate import ApprovalGateService
from app.approval.schema import ApprovalGate, ApproverEqualsCreator
from app.approval.store import ApprovalGateStore
from app.dag.engine import DAGTask, register_op
from app.dag.kernel import DurableExecutor, KernelRunResult, compute_node_id
from app.eval.n_eff import n_eff_from_matrix
from app.graph.research_graph import (
    CMD_CREATE_NODE,
    DESK_STRATEGY,
    CanonicalCommand,
    ResearchGraph,
)
from app.lineage.ids import content_hash
from app.qro.envelope import (
    ACTOR_USER_MANUAL,
    OBJ_STRATEGY_BOOK,
    QualifiedResearchObject,
)
from app.verification.verifier import Verifier
from app.compiler import (
    AttestedRun,
    CompiledRun,
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


# ─────────────────────────────────────────────────────────────────────────────
# op 注册（一次·内核 + 编译器 re-derive 共用全局 _OPS·单一源）
# ─────────────────────────────────────────────────────────────────────────────
@register_op("gc_test_op")
def _gc_test_op(context, x):
    return {"r": x * 3}


class _FakeHonestNLedger:
    """审批门 honest-N 依赖的【测试替身】（compiler 不碰 honest-N·这是 ApprovalGateService 的依赖）。

    诚实：这不是「改小 honest-N」——它是审批门确证三要件所需的最小账双。测试里 n_trials_raw 真实 ≥ 它。
    """

    def __init__(self, n: int = 1) -> None:
        self._n = n

    def honest_n(self, strategy_goal_ref: str) -> int:
        return self._n


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def graph_and_command():
    """ResearchGraph IR + 一条经 canonical command 落图的 strategy_book 资产（编译目标）。"""

    graph = ResearchGraph()
    qro = QualifiedResearchObject(
        object_type=OBJ_STRATEGY_BOOK, natural_key="sb_gc", actor=ACTOR_USER_MANUAL
    )
    command = CanonicalCommand(
        command_type=CMD_CREATE_NODE,
        actor=ACTOR_USER_MANUAL,
        target_desk=DESK_STRATEGY,
        payload={"qro": qro},
    )
    graph.apply(command)  # 落进 command_log（命门 #1 上游所需）
    return graph, command, qro


@pytest.fixture
def compiler(tmp_path):
    """接好一台 GovernedCompiler（收编 executor + verifier + 审批门·verdict_lookup 接 VerdictBook）。"""

    executor = DurableExecutor(root=tmp_path / "kernel")
    approval_store = ApprovalGateStore(tmp_path / "approval")
    return build_default_compiler(
        executor=executor,
        approval_store=approval_store,
        honest_n_ledger=_FakeHonestNLedger(n=1),
    )


@pytest.fixture
def tasks():
    return [DAGTask(id="t1", op="gc_test_op", params={"x": 7})]


@pytest.fixture
def green_evidence():
    """确定性强证据（seed 7）：验证官 consistent（claims==recomputed）+ 三角门 green（DSR/PBO/CI 同向正）。"""

    rng = np.random.default_rng(7)
    t = 504
    champ = 0.004 + 0.006 * rng.standard_normal(t)
    others = [0.012 * rng.standard_normal(t) for _ in range(11)]
    mat = np.column_stack([champ] + others)
    neff = n_eff_from_matrix(mat)
    return EvidenceInputs(
        claims={"sharpe": 1.23, "max_dd": -0.08},
        recomputed={"sharpe": 1.23, "max_dd": -0.08},
        generator_model="gen-model-A",
        checker_model="checker-model-B",
        returns=champ,
        n_eff=neff,
        honest_n=12,
        returns_matrix=mat,
        asset_class="crypto",
        periods_per_year=252,
    )


def _good_promotion(**over) -> PromotionRequest:
    base = dict(
        model_id="m1",
        version=1,
        from_stage="paper",
        to_stage="staging",
        action_kind="promote_staging",
        created_by="alice",
        approver="bob",
        reason="cross-model consistent and DSR/PBO/Bootstrap triangle aligned green",
        dataset_version="ds_v1",
        strategy_goal_ref="goal_gc",
        n_trials_raw=12,
    )
    base.update(over)
    return PromotionRequest(**base)


# ═════════════════════════════════════════════════════════════════════════════
# #5 正路径（不误伤）——合法 command+IR → run → verdict → approval → approved
# ═════════════════════════════════════════════════════════════════════════════
def test_full_spine_positive_path_promotes(compiler, graph_and_command, tasks, green_evidence):
    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    assert compiled.kernel_run_id.startswith("krn_")
    assert compiled.command_ref == command.command_id
    assert compiled.kernel_mode == "run"

    attested = compiler.attest(compiled, green_evidence)
    assert attested.verdict == "consistent"     # 异模型一致（claims==recomputed）
    assert attested.gate_color == "green"        # 三角同向正
    assert attested.verdict_id.startswith("vd_")
    # verdict 绑定本 run（target_ref == kernel_run_id·非张冠李戴）
    assert attested.verdict_record.target_ref == compiled.kernel_run_id

    promoted = compiler.promote(attested, _good_promotion())
    assert promoted.governance == "approved"     # 经审批门·approver≠creator
    assert promoted.approver == "bob"
    assert promoted.gap_list == ()
    compiler.assert_promotion_governed(promoted)  # 探针放行正路径·不误伤

    # 三段全落治理账（单一通道）
    assert compiled.run_id in compiler.ledger.compiled_ids()
    assert attested.attest_id in compiler.ledger.attested_ids()
    assert promoted.promo_id in compiler.ledger.promoted_ids()


def test_govern_one_shot_equivalent(compiler, graph_and_command, tasks, green_evidence):
    """govern() 一把过整脊柱 == compile→attest→promote·终态 approved·链可回溯。"""

    graph, command, _ = graph_and_command
    promoted = compiler.govern(
        command, tasks, graph=graph, evidence=green_evidence, promotion=_good_promotion()
    )
    assert promoted.governance == "approved"
    # 链可回溯：promoted → attested → compiled → command_ref
    assert promoted.attested_run.verdict == "consistent"
    assert promoted.attested_run.compiled_run.command_ref == command.command_id


# ═════════════════════════════════════════════════════════════════════════════
# 命门 #1：命令未经 compiler 落 run → 拒（绕 compiler 直造 run 必抓·MUT）
# ═════════════════════════════════════════════════════════════════════════════
def test_gate1_command_not_in_graph_rejected(compiler, graph_and_command, tasks):
    """命令未经 canonical command 通道落图（不在 command_log）→ 拒为其编译 run。"""

    graph, _, qro = graph_and_command
    # 另铸一条未 apply 进图的命令（绕 canonical command 通道）
    rogue = CanonicalCommand(
        command_type=CMD_CREATE_NODE,
        actor=ACTOR_USER_MANUAL,
        target_desk=DESK_STRATEGY,
        payload={"qro": QualifiedResearchObject(
            object_type=OBJ_STRATEGY_BOOK, natural_key="sb_rogue", actor=ACTOR_USER_MANUAL)},
    )
    with pytest.raises(UncommandedRunError):
        compiler.compile(rogue, tasks, graph=graph)


def test_gate1_run_bypassing_compile_rejected(compiler, green_evidence):
    """绕 compile() 直造 CompiledRun（不在编译账）→ attest 经 assert_run_compiled 拒。"""

    node_ids = {"t1": "a" * 16}
    forged = CompiledRun(
        command_ref="cmd_forged",
        target_node_id="qro_forged",
        kernel_run_id="krn_" + content_hash(sorted(node_ids.values())),  # 自洽·但未经 compile
        node_id_by_task=node_ids,
        kernel_mode="run",
        kernel_succeeded=True,
    )
    assert forged.run_id not in compiler.ledger.compiled_ids()
    with pytest.raises(RunNotCompiledError):
        compiler.attest(forged, green_evidence)


def test_gate1_MUT_disable_run_compiled_probe_lets_bypass_slip(
    compiler, green_evidence, monkeypatch
):
    """MUT：关掉 assert_run_compiled → 绕 compile 直造的 run 滑过 attest（证明门 load-bearing·否则红）。"""

    node_ids = {"t1": "b" * 16}
    forged = CompiledRun(
        command_ref="cmd_forged2",
        target_node_id="qro_forged2",
        kernel_run_id="krn_" + content_hash(sorted(node_ids.values())),
        node_id_by_task=node_ids,
        kernel_mode="run",
        kernel_succeeded=True,
    )
    # 真门必抓
    with pytest.raises(RunNotCompiledError):
        compiler.attest(forged, green_evidence)
    # 种坏门（关掉单一通道探针）→ 同一绕过 run 不再被 RunNotCompiledError 拦（滑过 → 门是真在干活）
    monkeypatch.setattr(compiler, "assert_run_compiled", lambda *a, **k: None)
    attested = compiler.attest(forged, green_evidence)
    assert isinstance(attested, AttestedRun)  # 坏门放过：证明 assert_run_compiled 此前 load-bearing


# ═════════════════════════════════════════════════════════════════════════════
# 命门 #2：run 无 deterministic 内核身份（未经 DurableExecutor）→ 拒（MUT）
# ═════════════════════════════════════════════════════════════════════════════
def test_gate2_forged_kernel_ids_rejected(compiler, tasks):
    """假执行器返伪 node_id（≠ compute_node_id 独立重算）→ assert_kernel_identity 拒。"""

    forged_result = KernelRunResult(
        mode="run", succeeded=True, nodes=[],
        node_id_by_task={"t1": "deadbeefdeadbeef"},  # 伪造身份·非内容寻址派生
    )
    with pytest.raises(KernelIdentityViolation):
        compiler.assert_kernel_identity(tasks, forged_result)


def test_gate2_non_kernel_result_rejected(compiler, tasks):
    """非 KernelRunResult（duck 假执行结果）→ 无内核身份 → 拒。"""

    with pytest.raises(KernelIdentityViolation):
        compiler.assert_kernel_identity(tasks, {"node_id_by_task": {"t1": "x"}})


def test_gate2_empty_identity_rejected(compiler, tasks):
    """node_id_by_task 空 → 无确定性内核身份 → 拒。"""

    empty = KernelRunResult(mode="run", succeeded=True, nodes=[], node_id_by_task={})
    with pytest.raises(KernelIdentityViolation):
        compiler.assert_kernel_identity(tasks, empty)


def test_gate2_real_kernel_identity_accepted(compiler, tasks):
    """真 DurableExecutor 的 node_id == compute_node_id 独立重算 → 放行（不误伤）。"""

    real = compiler._executor.run(list(tasks), {})
    compiler.assert_kernel_identity(tasks, real)  # 不抛
    # 独立重算逐一吻合（收编 dag.kernel.compute_node_id·单一身份源）
    from app.dag.kernel import op_fingerprint
    from app.dag.engine import _OPS
    want = compute_node_id(tasks[0], (), op_version=op_fingerprint(_OPS.get("gc_test_op"), "gc_test_op"))
    assert real.node_id_by_task["t1"] == want


def test_gate2_multi_task_identity_matches_kernel(compiler, tmp_path):
    """多 task DAG（含依赖·上游内容寻址）：re-derive 逐一吻合真内核（gate #2 对依赖图也正确）。"""

    real = compiler._executor.run(
        [DAGTask(id="t1", op="gc_test_op", params={"x": 1}),
         DAGTask(id="t2", op="gc_test_op", params={"x": 2}, deps=["t1"])],
        {},
    )
    tasks2 = [DAGTask(id="t1", op="gc_test_op", params={"x": 1}),
              DAGTask(id="t2", op="gc_test_op", params={"x": 2}, deps=["t1"])]
    compiler.assert_kernel_identity(tasks2, real)  # 不抛
    derived = compiler._derive_node_ids(tasks2)
    assert derived["t1"] == real.node_id_by_task["t1"]
    assert derived["t2"] == real.node_id_by_task["t2"]
    assert real.node_id_by_task["t1"] != real.node_id_by_task["t2"]  # 上游入身份·内容寻址


def test_gate2_tampered_kernel_run_id_rejected(compiler, graph_and_command, tasks, green_evidence):
    """kernel_run_id 与 node_id_by_task 不自洽（身份字段被篡改）→ attest 经自洽门拒。"""

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    tampered = replace(compiled, kernel_run_id="krn_" + "0" * 16, run_id="")
    compiler.ledger.record_compiled(tampered)  # 录账·让 assert_run_compiled 过·孤立测内核自洽门
    with pytest.raises(KernelIdentityViolation):
        compiler.attest(tampered, green_evidence)


def test_gate2_MUT_disable_kernel_identity_lets_fake_executor_slip(
    graph_and_command, tasks, tmp_path, monkeypatch
):
    """MUT：关掉 assert_kernel_identity → 假执行器的伪 node_id 滑过 compile（证明门 load-bearing）。"""

    graph, command, _ = graph_and_command

    class _FakeExecutor(DurableExecutor):
        """DurableExecutor 子类·run() 返伪 node_id（模拟非确定性内核 / 被掉包的执行器）。"""

        def run(self, task_list, context=None):
            return KernelRunResult(
                mode="run", succeeded=True, nodes=[],
                node_id_by_task={t.id: "fake" + t.id for t in task_list},
            )

    fake_ex = _FakeExecutor(root=tmp_path / "fake_kernel")
    comp = GovernedCompiler(
        executor=fake_ex,
        verifier=Verifier(),
        approval=ApprovalGateService(ApprovalGateStore(tmp_path / "appr")),
    )
    # 真门必抓伪身份
    with pytest.raises(KernelIdentityViolation):
        comp.compile(command, tasks, graph=graph)
    # 种坏门（关掉内核身份探针）→ 假执行器的伪 node_id 滑过 → 产出带伪身份的 CompiledRun（门曾 load-bearing）
    monkeypatch.setattr(comp, "assert_kernel_identity", lambda *a, **k: None)
    compiled = comp.compile(command, tasks, graph=graph)
    assert compiled.node_id_by_task["t1"] == "faket1"  # 坏门放过伪身份


# ═════════════════════════════════════════════════════════════════════════════
# 命门 #3：verdict 绕过 verifier/三角门 → 拒（伪造裁决·张冠李戴·MUT）
# ═════════════════════════════════════════════════════════════════════════════
def test_gate3_forged_verdict_id_rejected(compiler, graph_and_command, tasks, green_evidence):
    """手刻 verdict_id（≠ 验证官单一源 compute_verdict_id 重算）→ assert_verdict_attested 拒。"""

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    attested = compiler.attest(compiled, green_evidence)
    # 伪造：把 verdict_id 改成手刻值（内容未变·重算必不符）
    forged_rec = replace(attested.verdict_record, verdict_id="vd_FORGED0000000")
    forged_att = replace(
        attested, verdict_record=forged_rec, verdict_id="vd_FORGED0000000", attest_id=""
    )
    with pytest.raises(VerdictBypassViolation):
        compiler.assert_verdict_attested(forged_att)


def test_gate3_borrowed_verdict_not_bound_to_run_rejected(
    compiler, graph_and_command, tasks, green_evidence
):
    """借别 run 的裁决（verdict.target_ref ≠ 本 run kernel_run_id）→ 张冠李戴 → 拒。"""

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    # 给「另一个 run」铸一条自洽 verdict（target_ref 指向别的 kernel_run_id）
    other_rec = Verifier().reconcile(
        target_ref="krn_" + "f" * 16,  # 别的 run
        claims={"x": 1.0}, recomputed={"x": 1.0},
        generator_model="g", checker_model="c",
    )
    from app.eval.overfit_gate import run_overfit_gate  # 真三角门裁决（绑定不靠它·只为字段齐）
    gv = run_overfit_gate(
        green_evidence.returns, n_eff=green_evidence.n_eff, honest_n=green_evidence.honest_n,
        returns_matrix=green_evidence.returns_matrix,
    )
    borrowed = AttestedRun(
        run_id=compiled.run_id, compiled_run=compiled,
        verdict_record=other_rec, verdict_id=other_rec.verdict_id, verdict=other_rec.verdict,
        gate_verdict=gv, gate_color=gv.color,
    )
    with pytest.raises(VerdictBypassViolation):
        compiler.assert_verdict_attested(borrowed)


def test_gate3_MUT_disable_verdict_probe_lets_forged_verdict_promote(
    compiler, graph_and_command, tasks, green_evidence, monkeypatch
):
    """MUT：关掉 assert_verdict_attested → 伪造 verdict 滑进 promote → 被晋级（证明门 load-bearing）。

    伪造 = 把真 consistent 裁决的 verdict_id 篡改后塞进 VerdictBook（审批门按篡改 id 能查到·target_ref 仍绑本 run）。
    真门：promote 经 assert_verdict_attested 抓 verdict_id 不自洽 → VerdictBypassViolation。
    坏门（关探针）：伪造裁决滑过编译器 verdict 门 → 审批门据（被信任的）篡改裁决放行 → governance=approved。
    """

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    attested = compiler.attest(compiled, green_evidence)
    tampered_id = "vd_TAMPERED00000"
    tampered_rec = replace(attested.verdict_record, verdict_id=tampered_id)
    forged_att = replace(
        attested, verdict_record=tampered_rec, verdict_id=tampered_id, attest_id=""
    )
    # 真门必抓
    with pytest.raises(VerdictBypassViolation):
        compiler.promote(forged_att, _good_promotion())
    # 种坏门：关编译器 verdict 探针 + 把篡改裁决塞进 VerdictBook（审批门据 verification_record_id 能查到）
    compiler.verdict_book.put(tampered_rec)
    monkeypatch.setattr(compiler, "assert_verdict_attested", lambda *a, **k: None)
    promoted = compiler.promote(forged_att, _good_promotion())
    assert promoted.governance == "approved"  # 坏门放过伪造 verdict → 证明 assert_verdict_attested load-bearing


# ═════════════════════════════════════════════════════════════════════════════
# 命门 #4：promotion 未经 approval 门（approver≠creator）→ 拒（MUT）
# ═════════════════════════════════════════════════════════════════════════════
def test_gate4_approver_equals_creator_rejected(compiler, graph_and_command, tasks, green_evidence):
    """approver==creator → 收编审批门 ApprovalGateService 抛 ApproverEqualsCreator（compiler 路由进门·不旁路）。"""

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    attested = compiler.attest(compiled, green_evidence)
    with pytest.raises(ApproverEqualsCreator):
        compiler.promote(attested, _good_promotion(created_by="sam", approver="sam"))


def test_gate4_bypass_approval_direct_promoted_run_rejected(compiler):
    """绕审批门直造 PromotedRun（不在治理账）→ assert_promotion_governed 拒。"""

    bypass = PromotedRun(
        run_id="crun_x", attested_run=None, gate_id="gate-fake",
        governance="approved", approver="alice", created_by="alice",
    )
    assert bypass.promo_id not in compiler.ledger.promoted_ids()
    with pytest.raises(PromotionGovernanceViolation):
        compiler.assert_promotion_governed(bypass)


def test_gate4_approved_with_approver_equals_creator_rejected(compiler):
    """approved 却 approver==creator（即便录了账）→ approver≠creator 防御纵深复核拒（§8）。"""

    forged = PromotedRun(
        run_id="crun_y", attested_run=None, gate_id="gate-y",
        governance="approved", approver="dave", created_by="Dave ",  # 归一后相等
    )
    compiler.ledger.record_promoted(forged)  # 录账·孤立测 approver≠creator 复核（绕过审批门强制）
    with pytest.raises(PromotionGovernanceViolation):
        compiler.assert_promotion_governed(forged)


def test_gate4_MUT_disable_approval_routing_lets_self_approve_slip(
    compiler, graph_and_command, tasks, green_evidence, monkeypatch
):
    """MUT：把收编审批门掉包成「自动批·不查 approver≠creator」→ approver==creator 晋级滑过（证门 load-bearing）。"""

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    attested = compiler.attest(compiled, green_evidence)

    class _RubberStampGate:
        """坏审批门：开门即 approved·从不查 approver≠creator（模拟绕审批门治理的编译器）。"""

        def open_gate(self, **kw):
            g = ApprovalGate(
                gate_id="rubber-1", model_id=kw["model_id"], version=kw["version"],
                from_stage=kw["from_stage"], to_stage=kw["to_stage"], channel="confirmatory",
                action_kind=kw["action_kind"], created_by=kw["created_by"],
            )
            g.decision = "approved"
            g.approver = kw["created_by"]  # ← 自批（approver==creator）却放行
            return g

    monkeypatch.setattr(compiler, "_approval", _RubberStampGate())
    promoted = compiler.promote(attested, _good_promotion(created_by="sam", approver="sam"))
    # 坏门放过自批 → 证明真 ApprovalGateService（approver≠creator 强制）此前 load-bearing
    assert promoted.governance == "approved" and promoted.approver == "sam"


def test_gate4_MUT_disable_governed_probe_lets_bypass_slip(compiler, monkeypatch):
    """MUT：关掉 assert_promotion_governed → 绕审批门直造的 PromotedRun 不再被拦（证明探针 load-bearing）。"""

    bypass = PromotedRun(
        run_id="crun_z", attested_run=None, gate_id="gate-z",
        governance="approved", approver="eve", created_by="eve",
    )
    with pytest.raises(PromotionGovernanceViolation):
        compiler.assert_promotion_governed(bypass)
    monkeypatch.setattr(compiler, "assert_promotion_governed", lambda *a, **k: None)
    compiler.assert_promotion_governed(bypass)  # 坏门放过（无抛）→ 探针此前 load-bearing


# ═════════════════════════════════════════════════════════════════════════════
# 证据不利 = 诚实拒晋级（非误伤）+ 收编不改 + 结构不变量
# ═════════════════════════════════════════════════════════════════════════════
def test_unfavorable_verdict_concern_refuses_promotion_not_falsereject(
    compiler, graph_and_command, tasks
):
    """异模型不一致（claims≠recomputed → concern/blocked）→ 诚实拒晋级（证据不足·非误伤）。"""

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    rng = np.random.default_rng(7)
    champ = 0.004 + 0.006 * rng.standard_normal(504)
    mat = np.column_stack([champ] + [0.012 * rng.standard_normal(504) for _ in range(11)])
    bad_ev = EvidenceInputs(
        claims={"sharpe": 1.23}, recomputed={"sharpe": 0.40},  # 异模型重算翻车 → blocked/concern
        generator_model="gen-A", checker_model="chk-B",
        returns=champ, n_eff=n_eff_from_matrix(mat), honest_n=12, returns_matrix=mat,
    )
    attested = compiler.attest(compiled, bad_ev)
    assert attested.verdict in ("blocked", "concern")
    with pytest.raises(EvidenceVerdictUnfavorable):
        compiler.promote(attested, _good_promotion())


def test_unfavorable_gate_not_green_refuses_promotion(compiler, graph_and_command, tasks):
    """三角门非 green（弱/噪声收益）→ 诚实拒晋级（非误伤·绝不把弱证据推进晋级）。"""

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    rng = np.random.default_rng(3)
    noise = 0.02 * rng.standard_normal(504)  # 零漂移噪声 → 非 green
    mat = np.column_stack([noise] + [0.02 * rng.standard_normal(504) for _ in range(11)])
    weak_ev = EvidenceInputs(
        claims={"sharpe": 0.0}, recomputed={"sharpe": 0.0},  # 一致但弱
        generator_model="gen-A", checker_model="chk-B",
        returns=noise, n_eff=n_eff_from_matrix(mat), honest_n=12, returns_matrix=mat,
    )
    attested = compiler.attest(compiled, weak_ev)
    assert attested.gate_color != "green"
    with pytest.raises(EvidenceVerdictUnfavorable):
        compiler.promote(attested, _good_promotion())


def test_compile_rejects_non_canonical_command(compiler, graph_and_command, tasks):
    graph, _, _ = graph_and_command
    with pytest.raises(CompilerInputError):
        compiler.compile({"not": "a command"}, tasks, graph=graph)


def test_compile_rejects_empty_run_plan(compiler, graph_and_command):
    graph, command, _ = graph_and_command
    with pytest.raises(CompilerInputError):
        compiler.compile(command, [], graph=graph)


def test_compile_rejects_target_not_in_graph(compiler, tasks):
    """命令的目标资产不在 IR 节点 → 拒（消费 IR·绑定真资产）。空图 → 目标节点不存在。"""

    empty_graph = ResearchGraph()
    qro = QualifiedResearchObject(
        object_type=OBJ_STRATEGY_BOOK, natural_key="sb_absent", actor=ACTOR_USER_MANUAL
    )
    command = CanonicalCommand(
        command_type=CMD_CREATE_NODE, actor=ACTOR_USER_MANUAL,
        target_desk=DESK_STRATEGY, payload={"qro": qro},
    )
    # 命令未 apply 进 empty_graph → 先撞 command_log 门
    with pytest.raises((UncommandedRunError, CompilerInputError)):
        compiler.compile(command, tasks, graph=empty_graph)


def test_frozen_products_not_mutable(compiler, graph_and_command, tasks, green_evidence):
    """编译产物 frozen（内容寻址身份记录·状态迁移产新版·不原地改）。"""

    graph, command, _ = graph_and_command
    compiled = compiler.compile(command, tasks, graph=graph)
    with pytest.raises(Exception):  # FrozenInstanceError
        compiled.kernel_run_id = "krn_hacked"  # type: ignore[misc]


def test_collected_modules_unmodified_smoke():
    """收编只读核验：被收编模块的关键单一源函数仍是其原件（本卡绝不改它们内部）。"""

    # 内核身份单一源仍是 dag.kernel.compute_node_id（不另造）
    from app.dag.kernel import compute_node_id as k_cni
    from app.compiler.governed_compiler import compute_node_id as c_cni
    assert k_cni is c_cni  # 编译器 import 的就是内核那一个·非第二套
    # verdict 单一源仍是 verification.schema.compute_verdict_id
    from app.verification.schema import compute_verdict_id as v_cvi
    from app.compiler.governed_compiler import compute_verdict_id as c_cvi
    assert v_cvi is c_cvi


def test_build_default_compiler_wires_verdict_lookup(tmp_path):
    """build_default_compiler 把 VerdictBook 同时接给审批门 verdict_lookup 与 compiler（破构造环·共享源）。"""

    ex = DurableExecutor(root=tmp_path / "k")
    comp = build_default_compiler(
        executor=ex, approval_store=ApprovalGateStore(tmp_path / "a"),
        honest_n_ledger=_FakeHonestNLedger(),
    )
    assert isinstance(comp, GovernedCompiler)
    assert isinstance(comp.verdict_book, VerdictBook)
    # 审批门的 verdict_lookup 读的就是 compiler 写的那本簿
    rec = Verifier().reconcile(target_ref="krn_x", claims={"a": 1.0}, recomputed={"a": 1.0},
                               generator_model="g", checker_model="c")
    comp.verdict_book.put(rec)
    assert comp._approval._verdict_lookup(rec.verdict_id) is rec
