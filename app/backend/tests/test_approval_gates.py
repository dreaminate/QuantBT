"""审批门 + promote 状态机的【对抗式】测试（T-019 / spine 07 §5）。

种已知坏门必抓。T1 噪声→拒 / T2 泄露(三角不同向)→拒 / T3 缺要件三连+缺口清单 / T4 approver==creator→拒 /
T5 honest-N 改小→拒 / T6 真信号→放行 / T12 幂等门后副作用 / T14 超时默认分流 / T15 措辞 / 探索不挡(P2)。
"""

from __future__ import annotations

import numpy as np
import pytest

from app.approval import (
    ApprovalGateService,
    ApprovalGateStore,
    ApproverEqualsCreator,
    EvidenceSnapshot,
    GateStateError,
)
from app.eval.bootstrap import bootstrap_sharpe_ci
from app.eval.dsr import deflated_sharpe_ratio
from app.experiments.store import ModelRegistry
from app.lineage.ledger import Ledger, LedgerEntry
from app.research_os import (
    DependencyKind,
    ModelArtifactFormat,
    ModelArtifactManifestEntry,
    ModelArtifactSource,
    ModelGovernancePassport,
    ModelRiskTier,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
    SafeLoadingPolicy,
)


_OWNER_USER_ID = "test-owner"


def _svc(tmp_path, **kw):
    # honest-N 核验对 confirmatory 是强制项 → 默认接一本账（空账 honest_n=0，合法证据 n_trials_raw≥0 通过）。
    kw.setdefault("ledger", Ledger(tmp_path / "ledger"))
    return ApprovalGateService(ApprovalGateStore(tmp_path), **kw)


def _good_evidence(**over):
    base = dict(config_hash="cfg_v1_aaaa", dataset_version="ds1", n_eff=5, n_trials_raw=5,
                dsr=0.92, pbo=0.10, bootstrap_ci=(0.4, 1.8), bootstrap_estimate=1.0,
                champion_challenger={"verdict": "challenger_wins", "delta_sharpe": 0.3},
                returns_sha256="r1")
    base.update(over)
    return EvidenceSnapshot(**base).to_dict()


_DEFAULT = object()   # 哨兵：区分「显式传 None（无证据）」与「用默认好证据」


def _open_conf(svc, *, created_by="alice", evidence=_DEFAULT, vrid="v-1", to_stage="production", goal="theme"):
    return svc.open_gate(model_id="m1", version=2, from_stage="dev", to_stage=to_stage,
                         action_kind=("promote_production" if to_stage == "production" else "promote_staging"),
                         created_by=created_by, verification_record_id=vrid,
                         evidence=(_good_evidence() if evidence is _DEFAULT else evidence),
                         strategy_goal_ref=goal)


def _governed_registry(tmp_path, gate_service):
    governance = PersistentModelGovernanceRegistry(
        tmp_path / "audit" / "model_governance.jsonl"
    )
    registry = ModelRegistry(
        tmp_path / "experiments",
        gate_service=gate_service,
        model_governance_registry=governance,
    )
    evidence = registry.model_recertification_evidence_registry
    vendor = evidence.record_dependency_content(
        owner_user_id=_OWNER_USER_ID,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:test-model-runtime",
        content=b"test-model-runtime==1\n",
        resolver_ref="test-lock:vendor:v1",
        recorded_by="test-fixture",
    )
    foundation = evidence.record_dependency_content(
        owner_user_id=_OWNER_USER_ID,
        dependency_kind=DependencyKind.FOUNDATION_MODEL,
        dependency_ref="foundation:test-model",
        content=b"test-foundation-model-v1\n",
        resolver_ref="test-lock:foundation:v1",
        recorded_by="test-fixture",
    )
    passport = governance.record_passport(
        ModelGovernancePassport(
            model_version_ref="model_version:m:v2",
            model_type_card_ref="model_type_card:m",
            training_plan_ref="training_plan:test-m-v2",
            training_run_ref="training_run:test-m-v2",
            model_risk_tier=ModelRiskTier.MEDIUM,
            materiality="approval gate regression fixture",
            intended_use=("approval gate regression",),
            prohibited_use=("unapproved live trading",),
            dataset_refs=("dataset:test",),
            feature_refs=("feature:test",),
            label_refs=("label:test",),
            training_code_hash="sha256:test-training-code",
            artifact_manifest=(
                ModelArtifactManifestEntry(
                    artifact_ref="artifact:m:v2",
                    uri="registry://models/m/v2/model.safetensors",
                    artifact_format=ModelArtifactFormat.SAFE_TENSORS,
                    source=ModelArtifactSource.PROJECT_PRODUCED,
                    content_hash="sha256:test-artifact",
                    producer_run_ref="training_run:test-m-v2",
                    sandbox_inspection_ref="artifact_inspection:m:v2",
                ),
            ),
            safe_loading_policy=SafeLoadingPolicy(
                sandboxed_load_inspect=True,
                torch_weights_only=True,
            ),
            vendor_dependency_refs=(vendor.fingerprint_ref,),
            foundation_model_dependency_refs=(foundation.fingerprint_ref,),
            monitoring_requirements=("test drift monitor",),
            recertification_triggers=tuple(RecertificationTrigger),
            validation_dossier_ref="validation_dossier:m:v2",
        ),
        owner_user_id=_OWNER_USER_ID,
        recorded_by="test-fixture",
    )
    return registry, passport


# ── T1 · 噪声 → PBO≈1/DSR≈0 → 三角不同向 → 门必拒 ─────────────────────────────────
def test_noise_rejected():
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.01, 500)
    dsr = deflated_sharpe_ratio(r, n_trials=50)
    ci = bootstrap_sharpe_ci(r, n_boot=300, seed=1)
    ev = _good_evidence(dsr=dsr, pbo=0.95, bootstrap_ci=(ci.lower, ci.upper), n_eff=50, n_trials_raw=50)
    svc = _svc(_tmp())
    g = _open_conf(svc, evidence=ev)
    assert g.decision == "rejected" and any("三角不同向" in x for x in g.gap_list)


# ── T2 · 泄露：dsr 填高但 pbo 高/CI 跨零 → 仍拒（无单一承重点）──────────────────────
def test_leak_triangle_not_aligned_rejected():
    svc = _svc(_tmp())
    # 调用方把 dsr 填到 0.99，但 pbo=0.8（高）、CI 下界 -0.1（跨零）
    ev = _good_evidence(dsr=0.99, pbo=0.8, bootstrap_ci=(-0.1, 1.0))
    g = _open_conf(svc, evidence=ev)
    assert g.decision == "rejected" and any("三角不同向" in x for x in g.gap_list)


# ── T3 · 缺要件三连 + 缺口清单各不相同 ──────────────────────────────────────────
def test_missing_requirements_distinct_gaps():
    svc = _svc(_tmp())
    g_a = _open_conf(svc, vrid=None)                                  # 缺独立验证记录
    g_b = _open_conf(svc, evidence=None)                             # 缺证据快照
    g_c = _open_conf(svc, evidence=_good_evidence(champion_challenger={}))   # 缺 champion 结论
    assert all(g.decision == "rejected" for g in (g_a, g_b, g_c))
    assert any("verification_record_id" in x for x in g_a.gap_list)
    assert any("证据快照" in x for x in g_b.gap_list)
    assert any("champion" in x for x in g_c.gap_list)
    assert g_a.gap_list != g_b.gap_list != g_c.gap_list


# ── T4 · approver==creator → 防自审拒 ───────────────────────────────────────────
def test_approver_equals_creator_blocked():
    svc = _svc(_tmp())
    g = _open_conf(svc, created_by="alice")
    assert g.decision == "pending"
    with pytest.raises(ApproverEqualsCreator):
        svc.approve(g.gate_id, approver="alice", reason="我自己看过了觉得没问题可以上")
    assert svc._store.get(g.gate_id).decision == "pending"           # stage 未翻


# ── T5 · honest-N 改小 → 门按账本实计拒（防作弊，硬）───────────────────────────────
def test_honest_n_cannot_be_understated(tmp_path):
    led = Ledger(tmp_path / "ledger")
    for i in range(8):   # 账本实计 8 个 distinct config
        led.record_or_hit(LedgerEntry.create(factor=f"f{i}", params={}, universe="u", dataset_version="ds1",
                                              freq="1d", label="y", strategy_goal_ref="theme",
                                              kind="backtest", stage="confirmatory"))
    svc = _svc(tmp_path, ledger=led)
    ev = _good_evidence(n_trials_raw=3)   # 自报名义 3 想抬 DSR，实则账本 8
    g = _open_conf(svc, evidence=ev, goal="theme")
    assert g.decision == "rejected" and any("honest-N 被改小" in x for x in g.gap_list)
    # 反向（杀「拿 n_eff 比」变异，#3）：名义 n_trials_raw=8≥账本，但聚类后 n_eff=2<8 属【合法】，不得误杀。
    ok = _open_conf(svc, evidence=_good_evidence(n_trials_raw=8, n_eff=2), goal="theme")
    assert ok.decision == "pending", "聚类后 n_eff<账本 的合法晋级被误杀（honest-N 比错字段，门坏）"


# ── T6 · 真信号齐要件 → open→pending→approve→approved ────────────────────────────
def test_real_signal_full_flow():
    svc = _svc(_tmp())
    g = _open_conf(svc, created_by="alice")
    assert g.decision == "pending"
    applied = {"n": 0}

    def _exec(gate):
        applied["n"] += 1
        return "ref-1"

    out = svc.approve(g.gate_id, approver="bob", reason="独立验证官异模型复核一致，三角同向，适用域已核",
                      risk_restated="最大回撤可能达 20%", execute_fn=_exec)
    assert out.decision == "approved" and out.side_effect_executed is True and out.side_effect_ref == "ref-1"
    assert applied["n"] == 1


# ── 探索通道 P2：dev/staging 之外的探索动作不挡（直批，仅记录）────────────────────
def test_exploratory_not_blocked():
    svc = _svc(_tmp())
    g = svc.open_gate(model_id="m1", version=1, from_stage="dev", to_stage="dev",
                      action_kind="risk_reduction", created_by="alice")
    assert g.decision == "approved" and g.channel == "exploratory"


# ── T12 · 幂等门后副作用：重复 resume → 只执行一次 ───────────────────────────────
def test_idempotent_side_effect():
    svc = _svc(_tmp())
    g = _open_conf(svc, created_by="alice")
    calls = {"n": 0}

    def _exec(gate):
        calls["n"] += 1
        return f"ref-{calls['n']}"

    svc.approve(g.gate_id, approver="bob", reason="独立复核一致三角同向适用域已核", execute_fn=_exec)
    svc.resume(g.gate_id, execute_fn=_exec)        # 重复
    svc.resume(g.gate_id, execute_fn=_exec)        # 再重复
    assert calls["n"] == 1, "门后副作用执行了多次（幂等护栏失效，门坏）"


def _force_expire(svc, gate):
    """把门的 SLA 截止改到过去（落盘），供测超时分流——否则未到期 on_sla_expire 不动作（#10）。"""
    g = svc._store.get(gate.gate_id)
    g.sla_deadline_utc = "2000-01-01T00:00:00+00:00"
    svc._store.append(g)


def _open_money(svc, action_kind, **kw):
    return svc.open_gate(model_id="m1", version=1, from_stage="dev", to_stage="production",
                         action_kind=action_kind, created_by="alice", verification_record_id="v",
                         evidence=_good_evidence(), strategy_goal_ref="theme", **kw)


# ── 复核 #10 · 未到 SLA 截止 → on_sla_expire 不提前放行（仍 pending）──────────────
def test_sla_not_expired_stays_pending():
    svc = _svc(_tmp())
    g = _open_money(svc, "stop_loss")
    assert g.decision == "pending"
    out = svc.on_sla_expire(g.gate_id, execute_fn=lambda gg: "ok")   # 截止远在未来
    assert out.decision == "pending", "未到期却被提前默认放行（durable-interrupt 形同虚设，门坏）"


# ── T14 · 超时默认按 action_kind 分流（到期后）────────────────────────────────────
def test_sla_timeout_routing():
    svc = _svc(_tmp())
    g1 = _open_money(svc, "stop_loss")
    assert g1.decision == "pending"
    _force_expire(svc, g1)
    out1 = svc.on_sla_expire(g1.gate_id, execute_fn=lambda g: "ok")
    assert out1.decision == "approved", "止损到期未默认放行（延迟即风险，门坏）"
    g2 = _open_money(svc, "transfer")
    _force_expire(svc, g2)
    out2 = svc.on_sla_expire(g2.gate_id, execute_fn=lambda g: "ok")
    assert out2.decision == "timed_out" and out2.side_effect_executed is False, "动钱到期未默认拒（门坏）"


# ── 复核 #7 · approver 大小写/空白差异不绕过 ────────────────────────────────────
def test_approver_case_whitespace_not_bypass():
    svc = _svc(_tmp())
    g = _open_conf(svc, created_by="Alice")
    with pytest.raises(ApproverEqualsCreator):
        svc.approve(g.gate_id, approver="  alice ", reason="改个大小写空格想自审绕过门")


# ── 复核 #11/#12 · 真钱订单缺 safety / 超 cap → fail-closed ───────────────────────
def test_money_order_hard_limit_failclosed():
    from app.approval import HardLimitExceeded
    # 无 safety_service → 动钱订单 fail-closed raise
    svc_no_safety = _svc(_tmp())
    g = svc_no_safety.open_gate(model_id="m1", version=1, from_stage="dev", to_stage="production",
                                action_kind="live_order", created_by="alice", verification_record_id="v",
                                evidence=_good_evidence(), strategy_goal_ref="theme")
    assert g.decision == "pending"
    with pytest.raises(GateStateError):
        svc_no_safety.approve(g.gate_id, approver="bob", reason="独立复核一致三角同向适用域已核")

    # 有 safety、超 cap → HardLimitExceeded
    class _Safety:
        def current_single_order_cap(self):
            return 100.0
    svc2 = _svc(_tmp(), safety_service=_Safety())
    ev = _good_evidence(config_hash="cfg_v1_bbbb")
    ev["notional_usdt"] = 50000.0
    g2 = svc2.open_gate(model_id="m1", version=1, from_stage="dev", to_stage="production",
                        action_kind="live_order", created_by="alice", verification_record_id="v",
                        evidence=ev, strategy_goal_ref="theme")
    with pytest.raises(HardLimitExceeded):
        svc2.approve(g2.gate_id, approver="bob", reason="独立复核一致三角同向适用域已核但超额")


# ── 复核 #6 · 崩溃后 resume 不重复执行门后副作用（意图先落盘）─────────────────────
def test_resume_after_crash_no_double_execute():
    svc = _svc(_tmp())
    g = _open_conf(svc, created_by="alice")
    calls = {"n": 0}

    def _crashing(gate):
        calls["n"] += 1
        raise RuntimeError("crash mid-execute")    # 副作用中途崩

    with pytest.raises(RuntimeError):
        svc.approve(g.gate_id, approver="bob", reason="独立复核一致三角同向适用域已核", execute_fn=_crashing)
    # 意图先落盘 → side_effect_executed=True；resume 见已执行不重发
    svc.resume(g.gate_id, execute_fn=_crashing)
    assert calls["n"] == 1, "崩溃后 resume 重复执行了门后副作用（应漏执行交对账、不重复动钱，门坏）"


# ── 复核 #17 · ModelRegistry 经门正路：approve_promotion 真翻 stage ──────────────
def test_registry_approve_flips_stage(tmp_path):
    svc = _svc(tmp_path)
    reg, passport = _governed_registry(tmp_path, svc)
    reg.register_version("m", artifact_path="a.pkl", owner_user_id=_OWNER_USER_ID)
    reg.register_version("m", artifact_path="b.pkl", owner_user_id=_OWNER_USER_ID)
    gate = reg.promote("m", 2, "production", created_by="alice", verification_record_id="v",
                       evidence=_good_evidence(), strategy_goal_ref="theme",
                       model_passport_ref=passport.passport_id,
                       owner_user_id=_OWNER_USER_ID)
    assert gate.decision == "pending"
    reg.approve_promotion(
        gate.gate_id,
        model_id="m",
        owner_user_id=_OWNER_USER_ID,
        approver="bob",
        reason="独立复核一致三角同向适用域已核可上",
    )
    assert any(
        v.version == 2 and v.stage == "production"
        for v in reg.list_versions("m", owner_user_id=_OWNER_USER_ID)
    ), \
        "approve_promotion 后 stage 未真翻到 production（gate→registry 执行断链，门坏）"
    # 侧门关闭：apply_stage 不可直翻 production
    with pytest.raises(GateStateError):
        reg.apply_stage("m", 1, "production", owner_user_id=_OWNER_USER_ID)


# ── T15 · 裁决措辞：证据充分/不足 + 适用域 + 未验证；禁可信/安全/保证 ────────────────
def test_verdict_wording():
    svc = _svc(_tmp())
    rej = _open_conf(svc, evidence=_good_evidence(pbo=0.9))
    ok = _open_conf(svc, created_by="alice")
    for g in (rej, ok):
        assert "证据" in g.verdict_text and "适用域" in g.verdict_text and "未验证" in g.verdict_text
        for w in ("可信", "安全", "保证"):
            assert w not in g.verdict_text, f"裁决出现绝对化措辞「{w}」（门坏）"


# ── confirmatory 审批理由反套话 ─────────────────────────────────────────────────
def test_boilerplate_reason_rejected():
    svc = _svc(_tmp())
    g = _open_conf(svc, created_by="alice")
    from app.approval.schema import EmptyReason
    with pytest.raises(EmptyReason):
        svc.approve(g.gate_id, approver="bob", reason="同意")        # 纯套话


# ── ModelRegistry.promote 接审批门：production 经门、rejected 不翻 stage ──────────
def test_registry_promote_through_gate(tmp_path):
    svc = _svc(tmp_path)
    reg, passport = _governed_registry(tmp_path, svc)
    reg.register_version("m", artifact_path="a.pkl", owner_user_id=_OWNER_USER_ID)
    reg.register_version("m", artifact_path="b.pkl", owner_user_id=_OWNER_USER_ID)
    # 缺要件 → GateRejection，stage 不翻
    res = reg.promote(
        "m",
        2,
        "production",
        created_by="alice",
        evidence=_good_evidence(pbo=0.9),
        model_passport_ref=passport.passport_id,
        owner_user_id=_OWNER_USER_ID,
    )
    from app.approval.schema import GateRejection
    assert isinstance(res, GateRejection) and res.gap_list
    assert all(
        v.stage != "production"
        for v in reg.list_versions("m", owner_user_id=_OWNER_USER_ID)
    ), "被拒却翻了 stage（门坏）"


# —— helper：每条用例独立 tmp 目录 ——
_counter = {"n": 0}


def _tmp():
    import pathlib
    import tempfile
    _counter["n"] += 1
    d = pathlib.Path(tempfile.mkdtemp(prefix=f"appgate{_counter['n']}_"))
    return d
