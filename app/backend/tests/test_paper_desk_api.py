"""P2 模拟台真实后端 · /api/paper/* 端点 + 治理对抗测试。

对抗（种已知坏门必抓）：
- 对抗#1 A股 live 下单端点必拒（致命错误防线：A股永不 live）。
- 对抗#2 晋级裸翻必拒（INV-5：无背书 / 自审 / 不可跳级 都拒）。
- 对抗#3 风险门会话内改必拒，且被拒事件入哈希链（会话外不可改 · 防篡改证据）。
不破基线：端点正常读路径（status/positions/fills/equity_log/promotion）返 200 + 合理结构。
"""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import require_user_dependency
from app.execution.base import Order
from app.execution.paper_venue import PaperVenue
from app.main import PAPER_DESK, VERDICT_STORE, VERIFIER, app
from app.paper.desk import (
    AShareLiveForbidden,
    PaperDeskService,
    RiskEvidenceCorrupted,
    RiskGateMutationForbidden,
    aggregate_promotion_checks,
)
from app.paper.replay_provider import (
    BUNDLED_SAMPLE_SOURCE,
    MIXED_REPLAY_SOURCE,
    SIMULATED_SOURCE,
    ReplayBarProvider,
    seed_positions,
)


@pytest.fixture
def client():
    identity = {"user_id": "tester"}
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=identity["user_id"]
    )
    try:
        test_client = TestClient(app)
        test_client.paper_test_identity = identity
        yield test_client
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def _as_user(client: TestClient, user_id: str) -> None:
    client.paper_test_identity["user_id"] = user_id


def _record_paper_endorsement(target_ref: str, *, suffix: str):
    record = VERIFIER.reconcile(
        target_ref=target_ref,
        claims={"promotion_snapshot": 1.0},
        recomputed={"promotion_snapshot": 1.0},
        generator_model="paper-builder-model",
        checker_model="paper-reviewer-model",
        generator_seed=1,
        checker_seed=2,
        generator_slice="builder-slice",
        checker_slice="reviewer-slice",
        replay_ref=f"paper_fixture:{suffix}",
        notes="test-only exact paper promotion endorsement",
        created_at_utc=datetime.now(UTC).isoformat(),
    )
    VERDICT_STORE.record(record)
    return record


# ════════════════ 基线：正常读路径 ════════════════
def test_runs_list_and_status(client):
    runs = client.get("/api/paper/runs").json()["runs"]
    assert len(runs) >= 1
    ids = {r["id"] for r in runs}
    assert "weekly_cn_multifactor" in ids
    st = client.get("/api/paper/runs/weekly_cn_multifactor/status")
    assert st.status_code == 200
    body = st.json()
    assert body["run_id"] == "weekly_cn_multifactor"
    assert "config" in body and "balance" in body and "positions" in body


def test_status_404_unknown_run(client):
    assert client.get("/api/paper/runs/__nope__/status").status_code == 404


def test_book_endpoints_shape(client):
    rid = "weekly_cn_multifactor"
    assert client.get(f"/api/paper/runs/{rid}/positions").status_code == 200
    bal = client.get(f"/api/paper/runs/{rid}/balance").json()
    assert "total_equity" in bal and "cash" in bal
    fills = client.get(f"/api/paper/runs/{rid}/fills").json()["fills"]
    assert isinstance(fills, list)
    eq = client.get(f"/api/paper/runs/{rid}/equity_log").json()["equity_log"]
    assert isinstance(eq, list)


def test_fills_derived_from_audit_log():
    """成交回报从 ExecutionAuditLog(paper_fill) 派生，不另存第二份。"""

    svc = PaperDeskService()
    rec = svc.register_run(
        run_id="t1", name="t1", origin="o", market="crypto", symbols=["BTCUSDT"],
        bench="BTC", creator="c", equity_log_path=_tmp_eqlog("t1"), simulate=False,
    )
    rec.venue.place_order(Order(venue="paper", symbol="BTCUSDT", side="buy", quantity=1.0))
    rec.venue.feed_bar({"symbol": "BTCUSDT", "open": 100, "high": 101, "low": 99, "close": 100})
    fills = svc.fills("t1")
    assert len(fills) == 1 and fills[0]["symbol"] == "BTCUSDT" and fills[0]["status"] == "filled"


# ════════════════ 对抗#1 · A股 live 下单恒拒 ════════════════
def test_ashare_live_order_always_rejected(client):
    r = client.post("/api/paper/runs/weekly_cn_multifactor/live_order",
                    json={"symbol": "600519", "side": "buy", "quantity": 100})
    assert r.status_code == 403
    assert r.json()["detail"]["a_share_live_forbidden"] is True


def test_ashare_live_order_records_violation_in_chain(client):
    """A股 live 下单被拒 → 事件入风险违规哈希链（审计留痕）。"""

    before = client.get("/api/paper/runs/weekly_cn_multifactor/risk_gate").json()["violation_count"]
    client.post("/api/paper/runs/weekly_cn_multifactor/live_order", json={"symbol": "600519"})
    after = client.get("/api/paper/runs/weekly_cn_multifactor/risk_gate").json()["violation_count"]
    assert after == before + 1


def test_ashare_live_never_reaches_venue():
    """服务层：A股 attempt_live_order 永不下到 venue（key 路径不可达）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="cn1", name="cn1", origin="o", market="equity_cn",
                     symbols=["600519"], bench="500", creator="c",
                     equity_log_path=_tmp_eqlog("cn1"))
    with pytest.raises(AShareLiveForbidden):
        svc.attempt_live_order("cn1", {"symbol": "600519", "side": "buy", "quantity": 100})
    # venue 无任何 paper_place（更别说 live）——证明未进下单路径
    assert svc.fills("cn1") == []


# ════════════════ 对抗#2 · 晋级裸翻必拒（INV-5）════════════════
def test_promotion_naked_flip_without_endorsement_rejected(client):
    """无验证背书（endorsement_ref）直接审批 → 422 裸翻必拒。"""

    _as_user(client, "strat_wk_cn_01")
    gate = client.post("/api/paper/runs/weekly_cn_multifactor/promotion/open",
                       json={}).json()
    r = client.post(f"/api/paper/promotion/{gate['gate_id']}/approve",
                    json={"reason": "looks good"})  # 缺 endorsement_ref
    assert r.status_code == 422
    assert r.json()["detail"]["endorsement_or_reason_missing"] is True
    # 未晋级
    assert client.get("/api/paper/runs/weekly_cn_multifactor/promotion").json()["promoted"] is False


def test_promotion_self_approve_rejected(client):
    """approver == creator（自审）→ 422（生成≠验证不可自我满足）。"""

    _as_user(client, "strat_wk_cn_01")
    gate = client.post("/api/paper/runs/weekly_cn_multifactor/promotion/open",
                       json={}).json()
    r = client.post(f"/api/paper/promotion/{gate['gate_id']}/approve",
                    json={"endorsement_ref": "verdict_x", "reason": "ok"})
    assert r.status_code == 422
    assert r.json()["detail"]["approver_equals_creator"] is True


def test_promotion_cannot_skip_gates(client):
    """5 门未全过的 run（天数/超额/来源均不合格）→ 即便有背书也拒（不可跳级）。"""

    _as_user(client, "strat_div_03")
    gate = client.post("/api/paper/runs/dividend_lowvol_cn/promotion/open",
                       json={}).json()
    assert gate["eligible"] is False
    _as_user(client, "bob")
    r = client.post(f"/api/paper/promotion/{gate['gate_id']}/approve",
                    json={"endorsement_ref": "verdict_x", "reason": "ok"})
    assert r.status_code == 422
    assert r.json()["detail"]["gate_not_eligible"] is True


def test_promotion_replay_source_fails_closed_even_with_human_approval(client):
    """捆绑样本回放即使运行指标全过且人工背书齐，也不能晋级。"""

    _as_user(client, "strat_crypto_02")
    gate = client.post("/api/paper/runs/crypto_perp_mom/promotion/open",
                       json={}).json()
    assert gate["eligible"] is False
    source_check = next(c for c in gate["checks"] if c["key"] == "data_source")
    assert source_check["passed"] is False
    assert "bundled_sample_replay" in source_check["value"]
    _as_user(client, "bob")
    r = client.post(f"/api/paper/promotion/{gate['gate_id']}/approve",
                    json={"endorsement_ref": "verdict_crypto_1",
                          "reason": "异模型对账一致，超额稳定"})
    assert r.status_code == 422
    assert r.json()["detail"]["gate_not_eligible"] is True


def test_promotion_identity_aliases_are_rejected_without_partial_state(client):
    """请求体 creator/approver 别名不能伪造两个认证主体。"""

    _as_user(client, "strat_wk_cn_01")
    before = client.get("/api/paper/runs/weekly_cn_multifactor/promotion").json()
    bad_open = client.post(
        "/api/paper/runs/weekly_cn_multifactor/promotion/open",
        json={"creator": "alice"},
    )
    assert bad_open.status_code == 422
    assert bad_open.json()["detail"]["identity_from_auth_only"] is True
    after_bad_open = client.get("/api/paper/runs/weekly_cn_multifactor/promotion").json()
    assert after_bad_open == before

    gate = client.post(
        "/api/paper/runs/weekly_cn_multifactor/promotion/open", json={}
    ).json()
    assert gate["creator"] == "strat_wk_cn_01"
    bad_approve = client.post(
        f"/api/paper/promotion/{gate['gate_id']}/approve",
        json={"approver": "bob", "endorsement_ref": "verdict_x", "reason": "alias attack"},
    )
    assert bad_approve.status_code == 422
    assert bad_approve.json()["detail"]["identity_from_auth_only"] is True
    gate_after = client.get(f"/api/paper/promotion/{gate['gate_id']}").json()
    assert gate_after["decision"] == "pending"
    assert gate_after["approver"] is None
    assert gate_after["endorsement_ref"] is None


def test_only_authenticated_run_owner_can_open_promotion_gate(client):
    before = client.get("/api/paper/runs/weekly_cn_multifactor/promotion").json()
    _as_user(client, "unrelated-user")
    denied = client.post(
        "/api/paper/runs/weekly_cn_multifactor/promotion/open", json={}
    )
    assert denied.status_code == 403
    assert "paper run owner" in denied.json()["detail"]
    after = client.get("/api/paper/runs/weekly_cn_multifactor/promotion").json()
    assert after == before


def test_promotion_gate_nonce_prevents_restart_endorsement_replay():
    def build_gate():
        svc = PaperDeskService()
        svc.register_run(
            run_id="nonce-run",
            name="nonce-run",
            origin="test",
            market="crypto",
            symbols=["BTCUSDT"],
            bench="BTC",
            creator="alice",
            equity_log_path=_tmp_eqlog(uuid4().hex),
            simulate=False,
        )
        return svc.open_promotion_gate("nonce-run", creator="alice")

    first = build_gate()
    after_restart = build_gate()
    assert first.gate_id != after_restart.gate_id
    assert first.verification_target_ref != after_restart.verification_target_ref


def test_new_promotion_gate_supersedes_old_pending_gate_without_partial_promotion():
    from app.approval.schema import GateStateError

    svc = PaperDeskService()
    rec = svc.register_run(
        run_id="supersede-run",
        name="supersede-run",
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog("supersede-run"),
        simulate=False,
    )
    first = svc.open_promotion_gate("supersede-run", creator="alice")
    current = svc.open_promotion_gate("supersede-run", creator="alice")
    assert first.decision == "superseded"
    assert rec.promotion_gate_id == current.gate_id
    with pytest.raises(GateStateError, match="superseded|非 pending"):
        svc.approve_promotion(
            first.gate_id,
            approver="bob",
            endorsement_ref="vd_old",
            reason="old gate must never approve",
        )
    assert rec.promoted is False
    assert current.decision == "pending"


def test_promoted_run_cannot_open_a_new_pending_gate():
    from app.approval.schema import GateStateError

    svc = PaperDeskService()
    rec = svc.register_run(
        run_id="already-promoted",
        name="already-promoted",
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog("already-promoted"),
        simulate=False,
    )
    rec.promoted = True
    before_gate_id = rec.promotion_gate_id
    with pytest.raises(GateStateError, match="already promoted"):
        svc.open_promotion_gate("already-promoted", creator="alice")
    assert rec.promoted is True
    assert rec.promotion_gate_id == before_gate_id


def test_promoted_run_open_endpoint_returns_conflict_without_state_change(client):
    run_id = "already_promoted_http_" + uuid4().hex
    rec = PAPER_DESK.register_run(
        run_id=run_id,
        name=run_id,
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog(run_id),
        simulate=False,
    )
    rec.promoted = True
    before_gate_id = rec.promotion_gate_id

    _as_user(client, "alice")
    denied = client.post(f"/api/paper/runs/{run_id}/promotion/open", json={})

    assert denied.status_code == 409
    assert "already promoted" in denied.json()["detail"]
    assert rec.promoted is True
    assert rec.promotion_gate_id == before_gate_id


def test_promotion_requires_authenticated_reviewer_grant_and_exact_typed_endorsement(
    client, monkeypatch
):
    """两个认证主体 + exact grant + 本门 typed verdict 才能翻态。"""

    run_id = "auth_promo_" + uuid4().hex
    rec = PAPER_DESK.register_run(
        run_id=run_id,
        name=run_id,
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog(run_id),
        simulate=False,
        days_running=30,
        paper_excess_return=0.02,
        backtest_annual=0.20,
        paper_annual=0.18,
    )
    rec.simulated_source = "binance_testnet_live"
    rec.provider_kind = "testnet"
    rec.degrade_reason = None
    monkeypatch.delenv("QUANTBT_PAPER_VERIFIER_USER_IDS", raising=False)

    _as_user(client, "alice")
    gate = client.post(f"/api/paper/runs/{run_id}/promotion/open", json={}).json()
    endorsement = _record_paper_endorsement(
        gate["verification_target_ref"], suffix=gate["gate_id"]
    )
    grant = client.post(
        f"/api/paper/promotion/{gate['gate_id']}/reviewer-grants",
        json={
            "reviewer_user_id": "bob",
            "permissions": ["approve"],
            "expires_at_utc": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )
    assert grant.status_code == 200

    _as_user(client, "bob")
    no_machine_authority = client.post(
        f"/api/paper/promotion/{gate['gate_id']}/approve",
        json={
            "endorsement_ref": endorsement.verdict_id,
            "reason": "ordinary second account is not a verifier trust root",
        },
    )
    assert no_machine_authority.status_code == 403
    assert "allowlist" in no_machine_authority.json()["detail"]["reason"]
    pending = client.get(f"/api/paper/promotion/{gate['gate_id']}").json()
    assert pending["decision"] == "pending"
    assert pending["reviewer_authority_ref"] is None

    monkeypatch.setenv("QUANTBT_PAPER_VERIFIER_USER_IDS", "bob")
    _as_user(client, "mallory")
    unauthorized = client.post(
        f"/api/paper/promotion/{gate['gate_id']}/approve",
        json={
            "endorsement_ref": endorsement.verdict_id,
            "reason": "not the granted reviewer",
        },
    )
    assert unauthorized.status_code == 403
    pending = client.get(f"/api/paper/promotion/{gate['gate_id']}").json()
    assert pending["decision"] == "pending"
    assert pending["approver"] is None and pending["endorsement_ref"] is None

    _as_user(client, "bob")
    wrong_endorsement = client.post(
        f"/api/paper/promotion/{gate['gate_id']}/approve",
        json={
            "endorsement_ref": "vd_" + "0" * 16,
            "reason": "wrong endorsement must not mutate",
        },
    )
    assert wrong_endorsement.status_code == 422
    assert wrong_endorsement.json()["detail"]["endorsement_invalid"] is True
    pending = client.get(f"/api/paper/promotion/{gate['gate_id']}").json()
    assert pending["decision"] == "pending"
    assert pending["reviewer_grant_id"] is None
    assert pending["endorsement_evidence_sha256"] is None

    approved = client.post(
        f"/api/paper/promotion/{gate['gate_id']}/approve",
        json={
            "endorsement_ref": endorsement.verdict_id,
            "reason": "exact snapshot independently recomputed",
        },
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["decision"] == "approved"
    assert body["run_id"] == run_id and body["gate_id"] == gate["gate_id"]
    assert body["approver"] == "bob"
    assert body["reviewer_grant_id"] == grant.json()["grant_id"]
    assert body["reviewer_authority_ref"].startswith(
        "paper_verifier_authority:sha256:"
    )
    assert body["endorsement_evidence_sha256"].startswith(
        "paper_promotion_endorsement:sha256:"
    )
    assert PAPER_DESK.get(run_id).promoted is True


def test_promotion_aggregation_5_gates_includes_data_source():
    """判定聚合恰 5 门；默认 replay 失败，未降级 testnet 才可过数据源门。"""

    svc = PaperDeskService()
    rec = svc.register_run(run_id="agg", name="agg", origin="o", market="crypto",
                           symbols=["BTCUSDT"], bench="BTC", creator="c",
                           equity_log_path=_tmp_eqlog("agg"),
                           days_running=30, paper_excess_return=0.02,
                           backtest_annual=0.2, paper_annual=0.18)
    checks, eligible = aggregate_promotion_checks(rec, svc.risk)
    assert [c["key"] for c in checks] == ["days", "excess", "zero_violation", "decay", "data_source"]
    assert eligible is False
    assert checks[-1]["passed"] is False
    rec.simulated_source = "binance_testnet_live"
    rec.provider_kind = "testnet"
    rec.degrade_reason = None
    checks, eligible = aggregate_promotion_checks(rec, svc.risk)
    assert eligible is True
    assert checks[-1]["passed"] is True
    # 种坏门：注入一条违规 → 0违规门翻红 → 不合格
    svc.risk.record_violation("agg", title="x", detail="触线")
    _checks, elig2 = aggregate_promotion_checks(rec, svc.risk)
    assert elig2 is False


def test_promotion_ashare_cannot_spoof_testnet_source_metadata():
    """A股即使元数据被错误标成 testnet，也不能通过数据源门。"""

    svc = PaperDeskService()
    rec = svc.register_run(run_id="cn_source_spoof", name="x", origin="o", market="equity_cn",
                           symbols=["600519"], bench="500", creator="c",
                           equity_log_path=_tmp_eqlog("cn_source_spoof"),
                           days_running=30, paper_excess_return=0.02,
                           backtest_annual=0.2, paper_annual=0.18)
    rec.simulated_source = "binance_testnet_live"
    rec.provider_kind = "testnet"
    rec.degrade_reason = None
    checks, eligible = aggregate_promotion_checks(rec, svc.risk)
    assert eligible is False
    assert next(c for c in checks if c["key"] == "data_source")["passed"] is False


# ════════════════ 对抗#3 · 风险门会话内改必拒 + 入哈希链 ════════════════
def test_risk_gate_mutation_forbidden(client):
    """会话内改门请求 → 409（会话外不可改），绝不真改门。"""

    r = client.post("/api/paper/runs/weekly_cn_multifactor/risk_gate/mutate",
                    json={"leverage": 5.0})
    assert r.status_code == 409
    assert r.json()["detail"]["risk_gate_frozen"] is True


def test_risk_gate_mutation_logged_to_chain():
    """被拒的改门请求入 append-only 哈希链（防篡改证据），链完整。"""

    svc = PaperDeskService()
    svc.register_run(run_id="rg", name="rg", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("rg"))
    n0 = len(svc.risk.chain("rg"))
    with pytest.raises(RiskGateMutationForbidden):
        svc.risk.attempt_mutation("rg", {"leverage": 99}, actor="agent")
    chain = svc.risk.chain("rg")
    assert len(chain) == n0 + 1
    assert chain[-1]["kind"] == "gate_mutation_denied"
    assert svc.risk.verify_chain("rg") is True


def test_risk_gate_frozen_hash_stable():
    """门限发布即冻结哈希；同输入复发布哈希一致（内容寻址单一源）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="fz", name="fz", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("fz"))
    h1 = svc.risk.frozen_hash("fz")
    assert h1 and len(h1) == 16  # 全库 16 位哈希不变量
    h2 = svc.risk.publish("fz", svc.risk._limits["fz"])  # noqa: SLF001
    assert h2 == h1


def test_chain_tamper_detected():
    """种坏门：篡改链中一条 → verify_chain 必抓（断链）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="tp", name="tp", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("tp"))
    svc.risk.record_violation("tp", title="a", detail="d1")
    svc.risk.record_violation("tp", title="b", detail="d2")
    assert svc.risk.verify_chain("tp") is True
    # 直接改内部链的历史条目 detail（模拟篡改）
    svc.risk._chain["tp"][0]["detail"] = "篡改后的内容"  # noqa: SLF001
    assert svc.risk.verify_chain("tp") is False


def test_corrupted_zero_violation_chain_cannot_open_an_eligible_promotion_gate():
    """违规数即使仍为 0，风险证据链损坏也必须让晋级 fail closed。"""

    svc = PaperDeskService()
    rec = svc.register_run(
        run_id="risk_chain_promotion",
        name="risk_chain_promotion",
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog("risk_chain_promotion"),
        simulate=False,
        days_running=30,
        paper_excess_return=0.02,
        backtest_annual=0.20,
        paper_annual=0.18,
    )
    rec.simulated_source = "binance_testnet_live"
    rec.provider_kind = "testnet"
    rec.degrade_reason = None
    assert svc.risk.violation_count(rec.run_id) == 0
    svc.risk._chain[rec.run_id][0]["detail"] = "tampered"  # noqa: SLF001

    gate = svc.open_promotion_gate(rec.run_id, creator="alice")

    risk_check = next(check for check in gate.checks if check["key"] == "zero_violation")
    assert risk_check == {
        "key": "zero_violation",
        "label": "风险门 0 违规且证据链完整",
        "value": "证据链损坏",
        "passed": False,
    }
    assert gate.eligible is False
    assert rec.promoted is False


def test_truncated_violation_chain_cannot_heal_on_next_append():
    """截掉违规历史后，后续事件不得把残链重新锚定成完整或晋级全绿。"""

    svc = PaperDeskService()
    rec = svc.register_run(
        run_id="risk_chain_truncate",
        name="risk_chain_truncate",
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog("risk_chain_truncate"),
        simulate=False,
        days_running=30,
        paper_excess_return=0.02,
        backtest_annual=0.20,
        paper_annual=0.18,
    )
    rec.simulated_source = "binance_testnet_live"
    rec.provider_kind = "testnet"
    rec.degrade_reason = None
    svc.risk.record_violation(rec.run_id, title="breach", detail="must remain anchored")
    svc.risk._chain[rec.run_id].clear()  # noqa: SLF001 - simulate truncation.
    assert svc.risk.verify_chain(rec.run_id) is False

    with pytest.raises(RiskEvidenceCorrupted, match="refusing to append"):
        svc.risk.attempt_mutation(rec.run_id, {"leverage": 99}, actor="attacker")

    assert svc.risk.verify_chain(rec.run_id) is False
    checks, eligible = aggregate_promotion_checks(rec, svc.risk)
    assert next(c for c in checks if c["key"] == "zero_violation")["passed"] is False
    assert eligible is False


def test_corrupted_chain_republish_fails_without_partial_state_change():
    svc = PaperDeskService()
    svc.register_run(
        run_id="risk_chain_republish",
        name="risk_chain_republish",
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog("risk_chain_republish"),
        simulate=False,
    )
    svc.risk._chain["risk_chain_republish"][0]["detail"] = "tampered"  # noqa: SLF001
    before = {
        "frozen": svc.risk._frozen["risk_chain_republish"],  # noqa: SLF001
        "limits": deepcopy(svc.risk._limits["risk_chain_republish"]),  # noqa: SLF001
        "anchor": svc.risk._chain_anchors["risk_chain_republish"],  # noqa: SLF001
        "chain": deepcopy(svc.risk._chain["risk_chain_republish"]),  # noqa: SLF001
    }

    with pytest.raises(RiskEvidenceCorrupted, match="refusing to publish"):
        svc.risk.publish("risk_chain_republish", {"leverage": 99})

    after = {
        "frozen": svc.risk._frozen["risk_chain_republish"],  # noqa: SLF001
        "limits": svc.risk._limits["risk_chain_republish"],  # noqa: SLF001
        "anchor": svc.risk._chain_anchors["risk_chain_republish"],  # noqa: SLF001
        "chain": svc.risk._chain["risk_chain_republish"],  # noqa: SLF001
    }
    assert after == before


def test_violation_during_endorsement_lookup_is_rechecked_before_promotion():
    """外部验证期间新增的违规必须被最终快照抓住，审批保持 pending。"""

    from app.approval.schema import GateStateError

    svc = PaperDeskService()
    rec = svc.register_run(
        run_id="risk_race_before_final_snapshot",
        name="risk_race_before_final_snapshot",
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog("risk_race_before_final_snapshot"),
        simulate=False,
        days_running=30,
        paper_excess_return=0.02,
        backtest_annual=0.20,
        paper_annual=0.18,
    )
    rec.simulated_source = "binance_testnet_live"
    rec.provider_kind = "testnet"
    rec.degrade_reason = None
    gate = svc.open_promotion_gate(rec.run_id, creator="alice")
    endorsement = _record_paper_endorsement(
        gate.verification_target_ref, suffix=gate.gate_id
    )
    lookup_started = threading.Event()
    release_lookup = threading.Event()

    def blocking_lookup(ref):
        lookup_started.set()
        assert release_lookup.wait(timeout=2)
        return endorsement if ref == endorsement.verdict_id else None

    svc.configure_promotion_endorsement_lookup(blocking_lookup)
    svc.configure_promotion_reviewer_authority(
        lambda actor: "paper_verifier_authority:sha256:test" if actor == "bob" else None
    )
    svc.grant_promotion_reviewer(
        gate.gate_id,
        owner_user_id="alice",
        reviewer_user_id="bob",
        permissions=("approve",),
        expires_at_utc=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    result: dict[str, object] = {}

    def approve() -> None:
        try:
            result["gate"] = svc.approve_promotion(
                gate.gate_id,
                approver="bob",
                endorsement_ref=endorsement.verdict_id,
                reason="concurrent risk evidence must be rechecked",
            )
        except Exception as exc:  # noqa: BLE001 - asserted below.
            result["error"] = exc

    approval_thread = threading.Thread(target=approve)
    approval_thread.start()
    assert lookup_started.wait(timeout=2)
    svc.risk.record_violation(
        rec.run_id, title="concurrent breach", detail="arrived before final snapshot"
    )
    release_lookup.set()
    approval_thread.join(timeout=2)

    assert not approval_thread.is_alive()
    assert isinstance(result.get("error"), GateStateError)
    assert "风险门" in str(result["error"])
    assert "gate" not in result
    assert gate.decision == "pending"
    assert gate.approver is None and gate.endorsement_ref is None
    assert rec.promoted is False


def test_final_risk_snapshot_and_promotion_commit_are_one_critical_section(monkeypatch):
    """违规写入不能落在最终风险快照与晋级 commit 的中间。"""

    svc = PaperDeskService()
    rec = svc.register_run(
        run_id="risk_race_during_commit",
        name="risk_race_during_commit",
        origin="test",
        market="crypto",
        symbols=["BTCUSDT"],
        bench="BTC",
        creator="alice",
        equity_log_path=_tmp_eqlog("risk_race_during_commit"),
        simulate=False,
        days_running=30,
        paper_excess_return=0.02,
        backtest_annual=0.20,
        paper_annual=0.18,
    )
    rec.simulated_source = "binance_testnet_live"
    rec.provider_kind = "testnet"
    rec.degrade_reason = None
    gate = svc.open_promotion_gate(rec.run_id, creator="alice")
    endorsement = _record_paper_endorsement(
        gate.verification_target_ref, suffix=gate.gate_id
    )
    svc.configure_promotion_endorsement_lookup(
        lambda ref: endorsement if ref == endorsement.verdict_id else None
    )
    svc.configure_promotion_reviewer_authority(
        lambda actor: "paper_verifier_authority:sha256:test" if actor == "bob" else None
    )
    svc.grant_promotion_reviewer(
        gate.gate_id,
        owner_user_id="alice",
        reviewer_user_id="bob",
        permissions=("approve",),
        expires_at_utc=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )

    original_snapshot = svc.risk.promotion_snapshot
    snapshot_calls = 0
    final_snapshot_reached = threading.Event()
    violation_started = threading.Event()
    violation_finished = threading.Event()
    finished_inside_snapshot: list[bool] = []

    def observed_snapshot(run_id: str):
        nonlocal snapshot_calls
        value = original_snapshot(run_id)
        snapshot_calls += 1
        if snapshot_calls == 2:  # approval preliminary snapshot is #1; final guarded snapshot is #2.
            final_snapshot_reached.set()
            assert violation_started.wait(timeout=2)
            finished_inside_snapshot.append(violation_finished.wait(timeout=0.2))
        return value

    monkeypatch.setattr(svc.risk, "promotion_snapshot", observed_snapshot)

    def add_violation() -> None:
        assert final_snapshot_reached.wait(timeout=2)
        violation_started.set()
        svc.risk.record_violation(
            rec.run_id, title="serialized breach", detail="must not land inside commit"
        )
        violation_finished.set()

    violation_thread = threading.Thread(target=add_violation)
    violation_thread.start()
    approved = svc.approve_promotion(
        gate.gate_id,
        approver="bob",
        endorsement_ref=endorsement.verdict_id,
        reason="final snapshot and commit are atomic against risk writes",
    )
    violation_thread.join(timeout=2)

    assert not violation_thread.is_alive()
    assert finished_inside_snapshot == [False]
    assert approved.decision == "approved" and rec.promoted is True
    assert violation_finished.is_set()


# ════════════════ DS-4 · provider 产净值（非空壳）+ 治理门不破 ════════════════
def test_replay_provider_uses_bundled_btc_sample_and_sample_entry_price():
    """crypto BTC 有捆绑样本 → bar 来自真样本；建仓 entry_price/qty 按首价，不再硬编码 100。"""

    provider = ReplayBarProvider(symbols=["BTCUSDT"], length=4)
    first_bar = provider.next_bar("BTCUSDT")
    assert first_bar is not None
    assert first_bar["source"] == BUNDLED_SAMPLE_SOURCE
    assert first_bar["close"] == pytest.approx(47704.35)
    assert provider.source == BUNDLED_SAMPLE_SOURCE
    assert provider.first_price("BTCUSDT") == pytest.approx(47704.35)

    venue = PaperVenue(cash=1_000_000)
    count = seed_positions(venue, ["BTCUSDT"], provider=provider)
    pos = venue.get_position("BTCUSDT")
    assert count == 1
    assert pos.entry_price == pytest.approx(47704.35)
    assert pos.quantity == pytest.approx(50_000 / 47704.35)
    assert venue.get_balance()["CASH"].free == pytest.approx(950_000, abs=0.1)


def test_replay_provider_accepts_dash_symbol_but_preserves_bar_symbol():
    """BTC-USDT 可复用 BTCUSDT 样本文件；bar symbol 仍保留调用方符号以匹配 paper book。"""

    provider = ReplayBarProvider(symbols=["BTC-USDT"], length=2)
    bar = provider.next_bar("BTC-USDT")
    assert bar is not None
    assert bar["source"] == BUNDLED_SAMPLE_SOURCE
    assert bar["symbol"] == "BTC-USDT"
    assert bar["close"] == pytest.approx(47704.35)


def test_replay_provider_missing_sample_falls_back_with_honest_source():
    """无捆绑样本的 symbol 仍可模拟，但 source 必须标 synthetic fallback。"""

    provider = ReplayBarProvider(symbols=["NO_SAMPLE"], length=2)
    bar = provider.next_bar("NO_SAMPLE")
    assert bar is not None
    assert bar["source"] == SIMULATED_SOURCE
    assert provider.source == SIMULATED_SOURCE
    assert provider.first_price("NO_SAMPLE") != pytest.approx(47704.35)


def test_register_with_provider_feeds_real_bars_and_produces_equity():
    """种已知坏门反向：注入回放 provider → tick 真喂 bars → 净值非空、bars_fed>0、有持仓。

    BTCUSDT 配捆样本(真回放) + ETHUSDT 无样本(合成兜底) → run 级 source 为诚实混合标
    （绝不把含合成的 run 谎称纯 bundled，§3）；位置来自 seed_position（sim 路径不下单，fills 恒 0）。
    """

    svc = PaperDeskService()
    svc.register_run(run_id="ds4a", name="ds4a", origin="o", market="crypto",
                     symbols=["BTCUSDT", "ETHUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("ds4a"))  # simulate=True 默认
    primed = svc.prime_run("ds4a", ticks=12)
    assert primed["bars_fed"] > 0, "真喂 bars 后 bars_fed 必 > 0（非空壳）"
    assert primed["simulated"] is True and primed["source"] == MIXED_REPLAY_SOURCE
    eq = svc.equity_log("ds4a")
    assert len(eq) > 0, "MTM 必写出净值序列（非空壳）"
    # 净值是移动的（回放价格变动），不是一条死平线
    totals = [row["total_equity"] for row in eq]
    assert len(set(round(t, 2) for t in totals)) > 1, "净值须随回放移动，非死平"
    # seed_position 建仓 → 有真持仓（sim 路径不经 place_order，fills 恒 0；持仓来自种子）
    assert len(svc.positions("ds4a")) > 0


def test_prime_run_is_idempotent():
    """种已知坏门：重复 prime_run 不串行拼接净值——复位再跑产同一 N 点确定性序列（幂等）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="ds4idem", name="x", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("ds4idem"))
    p1 = svc.prime_run("ds4idem", ticks=16)
    eq1 = [round(r["total_equity"], 4) for r in svc.equity_log("ds4idem")]
    p2 = svc.prime_run("ds4idem", ticks=16)
    eq2 = [round(r["total_equity"], 4) for r in svc.equity_log("ds4idem")]
    assert p1["bars_fed"] == p2["bars_fed"] == 16, "重复 prime 计数不累加"
    assert p1["equity_points"] == p2["equity_points"] == 16, "净值点数不翻倍（无拼接）"
    assert eq1 == eq2, "确定性序列：重复 prime 产完全相同净值（不漂）"


def test_empty_shell_without_provider_stays_red():
    """断 provider（simulate=False）→ tick_once 返 0、净值恒空（空壳必红，绝不假绿灯）。"""

    svc = PaperDeskService()
    rec = svc.register_run(run_id="ds4b", name="ds4b", origin="o", market="crypto",
                           symbols=["BTCUSDT"], bench="BTC", creator="c",
                           equity_log_path=_tmp_eqlog("ds4b"), simulate=False)
    assert rec.provider is None and rec.simulated_source is None
    primed = svc.prime_run("ds4b", ticks=12)
    assert primed["bars_fed"] == 0, "无 provider：tick_once 必返 0（空壳）"
    assert primed["simulated"] is False
    assert svc.equity_log("ds4b") == [], "空壳净值恒空——绝不盖绿"


def test_ashare_run_with_provider_still_rejects_live():
    """A股 run 即便注了 provider 真跑，live 下单仍恒拒（治理门不破：provider≠放开 live）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="ds4cn", name="ds4cn", origin="o", market="equity_cn",
                     symbols=["600519"], bench="500", creator="c",
                     equity_log_path=_tmp_eqlog("ds4cn"))
    svc.prime_run("ds4cn", ticks=8)
    assert svc.status("ds4cn")["bars_fed"] > 0  # 真跑出净值
    with pytest.raises(AShareLiveForbidden):  # 但 A股永不 live
        svc.attempt_live_order("ds4cn", {"symbol": "600519", "side": "buy", "quantity": 100})


def test_register_does_not_bypass_inv5_approval():
    """register_run 不绕审批：注真 provider 跑出净值，晋级仍须 approver≠creator + 背书（INV-5）。"""

    from app.paper.desk import aggregate_promotion_checks

    svc = PaperDeskService()
    rec = svc.register_run(run_id="ds4inv5", name="x", origin="o", market="crypto",
                           symbols=["BTCUSDT"], bench="BTC", creator="alice",
                           equity_log_path=_tmp_eqlog("ds4inv5"),
                           days_running=30, paper_excess_return=0.02,
                           backtest_annual=0.2, paper_annual=0.18)
    svc.prime_run("ds4inv5")
    _checks, eligible = aggregate_promotion_checks(rec, svc.risk)
    assert eligible is False
    assert next(c for c in _checks if c["key"] == "data_source")["passed"] is False
    gate = svc.open_promotion_gate("ds4inv5", creator="alice")
    from app.approval.schema import ApproverEqualsCreator
    with pytest.raises(ApproverEqualsCreator):  # 自审恒拒——register 未削弱 INV-5
        svc.approve_promotion(gate.gate_id, approver="alice",
                              endorsement_ref="v1", reason="ok")


def test_approve_rechecks_source_after_gate_open():
    """开门时 testnet 合格，审批前降级回 replay → 旧门立即转红且不晋级。"""

    from app.approval.schema import GateStateError

    svc = PaperDeskService()
    rec = svc.register_run(run_id="source_drift", name="x", origin="o", market="crypto",
                           symbols=["BTCUSDT"], bench="BTC", creator="alice",
                           equity_log_path=_tmp_eqlog("source_drift"),
                           days_running=30, paper_excess_return=0.02,
                           backtest_annual=0.2, paper_annual=0.18)
    rec.simulated_source = "binance_testnet_live"
    rec.provider_kind = "testnet"
    rec.degrade_reason = None
    gate = svc.open_promotion_gate("source_drift", creator="alice")
    assert gate.eligible is True

    rec.simulated_source = BUNDLED_SAMPLE_SOURCE
    rec.provider_kind = "replay_fallback"
    rec.degrade_reason = "testnet 连接失败"
    with pytest.raises(GateStateError, match="数据源"):
        svc.approve_promotion(gate.gate_id, approver="bob",
                              endorsement_ref="v1", reason="ok")
    assert rec.promoted is False
    assert gate.eligible is True
    assert gate.decision == "pending"
    assert gate.approver is None and gate.endorsement_ref is None


def test_post_paper_runs_registers_runnable_run(client):
    """POST /api/paper/runs：注册一条 run，列表含之，且喂模拟 bars 产净值（bars_fed>0）。"""

    r = client.post("/api/paper/runs", json={
        "run_id": "ds4_post", "name": "ds4_post", "market": "crypto",
        "symbols": ["BTCUSDT"], "bench": "BTC",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["register"]["registered"] is True
    assert body["register"]["bars_fed"] > 0
    assert body["run"]["simulated_source"] == BUNDLED_SAMPLE_SOURCE
    ids = {x["id"] for x in client.get("/api/paper/runs").json()["runs"]}
    assert "ds4_post" in ids
    eq = client.get("/api/paper/runs/ds4_post/equity_log").json()["equity_log"]
    assert len(eq) > 0  # 真净值序列（非空壳）


def test_post_paper_runs_requires_run_id(client):
    """POST /api/paper/runs 缺 run_id → 422（不对幽灵 run 开模拟台）。"""

    r = client.post("/api/paper/runs", json={"name": "no_id"})
    assert r.status_code == 422


# ════════════════ 64717fe6 · paper 真捆样本回放（source 诚实 + P&L 不失真）════════════════
def _sample_first_close() -> tuple[float, float]:
    """读 data/samples/crypto/BTCUSDT_1d.csv 首行 (close, open)（断言基准从真数据读，样本换不脱钩）。"""

    import polars as pl

    from app.agent.sample_data import has_sample, sample_path

    assert has_sample("crypto_perp"), "BTC 捆样本缺失——真回放测试前置不满足"
    df = pl.read_csv(sample_path("crypto_perp"), columns=["open", "close"])
    return float(df["close"][0]), float(df["open"][0])


def test_crypto_replays_real_btc_sample_not_synthetic():
    """坏门#1：crypto paper run 必读真 BTC 样本 close 序列（非合成 100 起）；source=bundled_sample_replay。

    断言序列前值贴近 data/samples/crypto/BTCUSDT_1d.csv 真值（首 close ~47704、首 open ~46210），
    且明确 ≠ 合成 base=100。坏门若回到合成 100 起或谎称 bundled，本测试转红。
    """

    from app.paper.replay_provider import BUNDLED_SOURCE, ReplayBarProvider

    first_close, first_open = _sample_first_close()
    assert first_close > 1000, "真 BTC 样本首价应 ~47704（远大于合成 base 100）——前置数据校验"

    p = ReplayBarProvider(symbols=["BTCUSDT"], market="crypto")
    assert p.source == BUNDLED_SOURCE, "crypto 配捆样本 → source 必为 bundled_sample_replay"
    assert p.source_for("BTCUSDT") == BUNDLED_SOURCE
    # 序列首值 = 样本真 close（非合成 100）
    assert abs(p.first_price("BTCUSDT") - first_close) < 1e-6
    assert p._series["BTCUSDT"][0] == pytest.approx(first_close, abs=1e-2)
    assert p._series["BTCUSDT"][0] > 1000, "真样本价 ~47704，绝非合成 100 起（坏门防线）"
    # next_bar 也是真样本（open 贴样本首 open ~46210 区间、source 标对）
    bar = p.next_bar("BTCUSDT")
    assert bar["source"] == BUNDLED_SOURCE
    assert bar["close"] == pytest.approx(first_close, abs=1e-2)


def test_crypto_hyphen_symbol_resolves_real_sample():
    """坏门#1b：e2e 用的 'BTC-USDT'（带连字符）也须解析到真捆样本（非因 symbol 写法漏成合成）。"""

    from app.paper.replay_provider import BUNDLED_SOURCE, ReplayBarProvider

    first_close, _ = _sample_first_close()
    p = ReplayBarProvider(symbols=["BTC-USDT"], market="crypto")
    assert p.source == BUNDLED_SOURCE, "BTC-USDT 连字符形也须真回放（symbol 归一匹配样本 base）"
    assert abs(p.first_price("BTC-USDT") - first_close) < 1e-6


def test_entry_price_back_derived_from_sample_first_price_pnl_sane():
    """坏门#2：entry_price 用样本首价反推 qty → P&L 合理（非几百倍失真）。

    真路径：entry=样本首 close(47704)、qty=notional/首价 → 扣现金恰=notional、MTM@t0 positions_value≈
    notional（~1x）。变异自检（坏门）：故意 entry=100 配 47704 价序列 → positions_value 失真几百倍，
    断言两侧（真路径 ~1x / 坏门 >100x）证明门能判别。
    """

    from app.execution.paper_venue import PaperVenue
    from app.paper.replay_provider import ReplayBarProvider, seed_positions

    first_close, _ = _sample_first_close()
    notional = 50_000.0
    init_cash = 1_000_000.0

    # ---- 真路径：entry_price 用样本首价反推 ----
    p = ReplayBarProvider(symbols=["BTCUSDT"], market="crypto")
    v = PaperVenue(cash=init_cash, equity_log_path=_tmp_eqlog("fe_good"))
    seed_positions(v, ["BTCUSDT"], provider=p, notional_per_symbol=notional)
    pos = v.get_position("BTCUSDT")
    assert pos.entry_price == pytest.approx(first_close, abs=1e-6), "entry_price 必=样本首 close"
    assert pos.quantity == pytest.approx(notional / first_close, rel=1e-6), "qty=notional/首价"
    # 扣现金恰=notional（entry==除数 → 不变量）
    assert v.get_balance()["CASH"].free == pytest.approx(init_cash - notional, abs=1e-2)
    # MTM@t0：mark=首 close → positions_value≈notional（P&L 不失真，~1x）
    marks = p.current_marks(["BTCUSDT"])
    snap = v.mark_to_market(marks)
    assert snap.positions_value == pytest.approx(notional, rel=1e-3), "真路径 positions_value≈notional（~1x）"
    good_ratio = snap.positions_value / notional
    assert 0.5 < good_ratio < 2.0, "真路径 P&L 在合理带（~1x）"

    # ---- 变异自检（种坏门）：entry=100（合成 base）配真 47704 价序列 → 失真几百倍 ----
    vbad = PaperVenue(cash=init_cash, equity_log_path=_tmp_eqlog("fe_bad"))
    vbad.seed_position("BTCUSDT", quantity=round(notional / 100.0, 8), entry_price=100.0)  # 坏门
    snap_bad = vbad.mark_to_market({"BTCUSDT": first_close})
    bad_ratio = snap_bad.positions_value / notional
    assert bad_ratio > 100.0, "坏门：base=100 entry 配 47704 价 → positions_value 失真 >100x（门必抓）"
    # 真路径与坏门差几百倍——证明反推 entry 确实防失真
    assert bad_ratio / good_ratio > 100.0, "真路径相对坏门差 >100x（反推 entry 防 P&L 失真生效）"


def test_sampleless_market_falls_back_to_synthetic_honest_label():
    """坏门#3：无捆样本的市场 → 合成兜底 + source=deterministic_sim_walk（诚实区分，不伪造真样本）。"""

    from app.paper.replay_provider import SIMULATED_SOURCE, ReplayBarProvider

    # A股 token-gated 无免费样本 → 合成兜底
    p_cn = ReplayBarProvider(symbols=["600519"], market="equity_cn")
    assert p_cn.source == SIMULATED_SOURCE, "A股无样本 → deterministic_sim_walk"
    assert p_cn.first_price("600519") == 100.0, "合成首价=100（base）"
    assert p_cn._series["600519"][0] < 1000, "合成游走 base=100，绝非真样本 47704"
    # crypto 里无对应样本的 symbol（ETHUSDT，无 ETH 样本）也合成兜底（不拿 BTC 序列冒充 ETH）
    p_eth = ReplayBarProvider(symbols=["ETHUSDT"], market="crypto")
    assert p_eth.source == SIMULATED_SOURCE, "ETH 无样本 → 合成兜底（不冒充 BTC）"
    assert p_eth.first_price("ETHUSDT") == 100.0


def test_mixed_run_source_is_honest_and_scales_isolated():
    """坏门#1c（混源诚实）：BTC(真)+ETH(合成) → run source 为诚实混合标（绝不谎称纯 bundled）；

    且两 symbol 各自尺度自洽——BTC 持仓 ~47704 尺度、ETH ~100 尺度，互不串扰（防一处尺度污染另一处）。
    """

    from app.execution.paper_venue import PaperVenue
    from app.paper.replay_provider import (
        BUNDLED_SOURCE,
        SIMULATED_SOURCE,
        ReplayBarProvider,
        seed_positions,
    )

    p = ReplayBarProvider(symbols=["BTCUSDT", "ETHUSDT"], market="crypto")
    # run 级标签：含 bundled 与合成 → 显式混合，绝非纯 bundled（§3 不谎称）
    assert p.source == f"mixed:{BUNDLED_SOURCE}+{SIMULATED_SOURCE}"
    assert p.source_for("BTCUSDT") == BUNDLED_SOURCE
    assert p.source_for("ETHUSDT") == SIMULATED_SOURCE
    # 各 symbol 首价尺度隔离：BTC ~47704、ETH ~100
    assert p.first_price("BTCUSDT") > 1000
    assert p.first_price("ETHUSDT") == 100.0
    v = PaperVenue(cash=1_000_000.0, equity_log_path=_tmp_eqlog("mixed"))
    seed_positions(v, ["BTCUSDT", "ETHUSDT"], provider=p, notional_per_symbol=50_000.0)
    btc, eth = v.get_position("BTCUSDT"), v.get_position("ETHUSDT")
    assert btc.entry_price > 1000 and eth.entry_price == 100.0, "尺度隔离：各用自身首价"
    assert btc.quantity == pytest.approx(50_000 / p.first_price("BTCUSDT"), rel=1e-6)
    assert eth.quantity == pytest.approx(50_000 / 100.0, rel=1e-6)


def test_reprime_keeps_real_entry_price_not_reset_to_100():
    """坏门#2b：重复 prime_run 仍用样本首价反推 entry（不因复位重建仓退回 100 引入失真）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="fe_reprime", name="x", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("fe_reprime"))
    first_close, _ = _sample_first_close()
    svc.prime_run("fe_reprime", ticks=8)
    p1 = svc.positions("fe_reprime")
    svc.prime_run("fe_reprime", ticks=8)  # 再 prime（触发复位重建仓）
    p2 = svc.positions("fe_reprime")
    # 两次 prime 后 entry_price 都=样本首价（复位重建仓未退回 base=100）
    for snap in (p1, p2):
        btc = next(x for x in snap if x["symbol"] == "BTCUSDT")
        assert btc["entry_price"] == pytest.approx(first_close, abs=1e-6), \
            "re-prime 后 entry 仍=样本首价（未退回 100 → 不重引入失真）"


def test_crypto_real_replay_still_rejects_ashare_live_governance():
    """坏门#4（治理回归）：crypto 真回放不放开 A股 live——A股 run 走 live 路径仍恒拒（治理门不破）。"""

    svc = PaperDeskService()
    # A股 run（合成兜底真跑）
    svc.register_run(run_id="fe_cn", name="fe_cn", origin="o", market="equity_cn",
                     symbols=["600519"], bench="500", creator="c",
                     equity_log_path=_tmp_eqlog("fe_cn"))
    svc.prime_run("fe_cn", ticks=4)
    with pytest.raises(AShareLiveForbidden):  # A股永不 live（与捆样本回放无关，恒拒）
        svc.attempt_live_order("fe_cn", {"symbol": "600519", "side": "buy", "quantity": 100})
    assert svc.fills("fe_cn") == [], "A股未进任何下单路径（key 路径不可达）"


def test_post_ashare_run_then_live_order_rejected(client):
    """POST 注册 A股 run（真跑）后，其 live_order 端点仍恒拒（A股恒 paper，治理门不破）。"""

    client.post("/api/paper/runs", json={
        "run_id": "ds4_cn_post", "name": "ds4_cn_post", "market": "equity_cn",
        "symbols": ["600519"], "bench": "中证500",
    })
    r = client.post("/api/paper/runs/ds4_cn_post/live_order", json={"symbol": "600519"})
    assert r.status_code == 403
    assert r.json()["detail"]["a_share_live_forbidden"] is True


def test_submit_candidate_registers_paper_run(client):
    """过裁决候选（submit_candidate）→ 自动注册成模拟台可跑 run + 喂模拟 bars 产净值。"""

    r = client.post("/api/strategy/submit_candidate", json={
        "run_id": "cand_ds4", "name": "cand_ds4", "destination": "paper_desk",
        "market": "crypto", "symbols": ["BTCUSDT"], "bench": "BTC",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["paper_run"] is not None
    assert body["paper_run"]["bars_fed"] > 0
    # 候选 run 出现在模拟台列表
    ids = {x["id"] for x in client.get("/api/paper/runs").json()["runs"]}
    assert "cand_ds4" in ids


def test_submit_candidate_rejected_destination_no_paper_run(client):
    """候选目的地非 paper_desk（跳级）→ 422 且不注册模拟台 run（治理：直推实盘硬拒）。"""

    r = client.post("/api/strategy/submit_candidate", json={
        "run_id": "cand_live", "name": "cand_live", "destination": "live",
    })
    assert r.status_code == 422
    ids = {x["id"] for x in client.get("/api/paper/runs").json()["runs"]}
    assert "cand_live" not in ids


# ════════════════ U1 注册诚实化对抗（种坏门必抓）════════════════
def test_submit_candidate_crypto_via_asset_class_not_registered_as_ashare(client):
    """种坏门（H3）：crypto 候选只带 asset_class（无 market 字段）→ 绝不被注册成 A股 + 伪造 600519。

    旧 bug：payload 无 market 即默认 equity_cn、symbols 凭空 ["600519"]、bench 中证500。
    """

    r = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_crypto_cand", "name": "u1_crypto", "destination": "paper_desk",
        "asset_class": "crypto_perp", "symbols": ["BTCUSDT", "ETHUSDT"],
    })
    assert r.status_code == 200, r.text
    paper = r.json()["paper_run"]
    assert paper["registered"] is True
    assert paper["market"] == "crypto", "crypto 候选必须注册成 crypto，绝非 A股"
    assert "600519" not in paper["symbols"], "绝不伪造 A股标的 600519"
    assert paper["symbols"] == ["BTCUSDT", "ETHUSDT"]
    # 模拟台真 run 的市场也必须是 crypto（不是被默认成 equity_cn）。
    st = client.get("/api/paper/runs/u1_crypto_cand/status").json()
    assert st["market"] == "crypto"


def test_submit_candidate_unknown_market_no_fabrication_shows_error(client):
    """种坏门（H3/H4）：候选缺 market/asset_class → 不默认 A股伪造标的，paper_run 带显式 error。

    候选登记本身仍成功（200），但模拟台派生注册不静默假成功——不凭空造 600519 的 A股幽灵 run。
    """

    r = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_unknown_cand", "name": "u1_unknown", "destination": "paper_desk",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "candidate"  # 候选登记成功（handoff 不阻塞）
    paper = body["paper_run"]
    assert paper["registered"] is False, "市场判不出绝不静默注册"
    assert "error" in paper and paper["error"]
    assert "paper_run_error" in body, "H4：端点透传失败原因供前端显示"
    # 绝不建出伪造的 A股幽灵 run。
    ids = {x["id"] for x in client.get("/api/paper/runs").json()["runs"]}
    assert "u1_unknown_cand" not in ids


def test_post_paper_runs_unknown_market_rejected_no_ghost_run(client):
    """种坏门（H3）：POST /api/paper/runs 缺 market → 422 拒绝、不建伪造 A股 run（不再默认 600519）。"""

    r = client.post("/api/paper/runs", json={"run_id": "u1_ghost", "name": "u1_ghost"})
    assert r.status_code == 422, r.text
    assert "market" in r.json()["detail"]["reason"] or "市场" in r.json()["detail"]["reason"]
    ids = {x["id"] for x in client.get("/api/paper/runs").json()["runs"]}
    assert "u1_ghost" not in ids


def test_resubmit_different_market_not_silently_ignored(client):
    """种坏门（M3）：同 run_id 先注册 crypto 后换 equity_cn 二次提交 → 显式拒绝，不静默沿用旧值还报 success。"""

    r1 = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_reconcile", "name": "u1_reconcile", "destination": "paper_desk",
        "market": "crypto", "symbols": ["BTCUSDT"],
    })
    assert r1.status_code == 200 and r1.json()["paper_run"]["registered"] is True
    # 二次提交换成 A股 —— 必须显式标冲突，不能静默返 registered:True。
    r2 = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_reconcile", "name": "u1_reconcile", "destination": "paper_desk",
        "market": "equity_cn", "symbols": ["600519"],
    })
    assert r2.status_code == 200, r2.text  # 候选登记仍成功
    paper = r2.json()["paper_run"]
    assert paper["registered"] is False, "换 market 二次提交不可静默成功"
    assert "M3" in paper["error"] or "冲突" in paper["error"]
    # 既有 run 市场不被静默改写——仍是 crypto（治理：不静默改市场）。
    st = client.get("/api/paper/runs/u1_reconcile/status").json()
    assert st["market"] == "crypto"


def test_resubmit_different_symbols_not_silently_ignored(client):
    """种坏门（M3）：同 run_id 同 market 但换标的二次提交 → 显式拒绝，不静默沿用旧标的还报 success。"""

    r1 = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_sym_reconcile", "name": "x", "destination": "paper_desk",
        "market": "crypto", "symbols": ["BTCUSDT"],
    })
    assert r1.status_code == 200 and r1.json()["paper_run"]["registered"] is True
    r2 = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_sym_reconcile", "name": "x", "destination": "paper_desk",
        "market": "crypto", "symbols": ["ETHUSDT"],
    })
    assert r2.status_code == 200
    paper = r2.json()["paper_run"]
    assert paper["registered"] is False and ("M3" in paper["error"] or "冲突" in paper["error"])


def test_ashare_candidate_still_live_forbidden_after_register(client):
    """§5 治理不削弱：A股候选正确注册成 equity_cn 后，其 live_order 端点仍恒拒（A股恒 paper）。"""

    r = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_cn_cand", "name": "u1_cn", "destination": "paper_desk",
        "market": "equity_cn", "symbols": ["600519"],
    })
    assert r.status_code == 200 and r.json()["paper_run"]["market"] == "equity_cn"
    lo = client.post("/api/paper/runs/u1_cn_cand/live_order", json={"symbol": "600519"})
    assert lo.status_code == 403
    assert lo.json()["detail"]["a_share_live_forbidden"] is True


def test_ashare_spot_asset_class_not_misclassified_as_crypto(client):
    """种坏门（H3/§5）：A股 spot 候选（asset_class 含 'spot'）绝不被误判成 crypto。

    误判成 crypto 会让该 run 绕过 equity_cn 的 A股 live-forbidden 映射——治理红线，必抓。
    """

    from app.main import _derive_candidate_market

    for ac in ("a_share_spot", "cn_spot", "stock_spot", "equity_cn_spot"):
        assert _derive_candidate_market({"asset_class": ac}) == "equity_cn", \
            f"asset_class={ac!r} 必须判成 equity_cn（A股 spot 不是 crypto）"
    for ac in ("crypto_spot", "crypto_perp", "usdt_pair", "btc_basket", "perp"):
        assert _derive_candidate_market({"asset_class": ac}) == "crypto"
    # 端到端：A股 spot 候选注册后其 live_order 仍恒拒（市场正确派生为 equity_cn）。
    r = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_cn_spot", "name": "x", "destination": "paper_desk",
        "asset_class": "a_share_spot", "symbols": ["600519"],
    })
    assert r.status_code == 200 and r.json()["paper_run"]["market"] == "equity_cn"
    lo = client.post("/api/paper/runs/u1_cn_spot/live_order", json={"symbol": "600519"})
    assert lo.status_code == 403 and lo.json()["detail"]["a_share_live_forbidden"] is True


def test_market_field_case_insensitive(client):
    """显式 market 字段大小写不敏感（CRYPTO/Equity_CN 都识别，与 asset_class casefold 一致）。"""

    from app.main import _derive_candidate_market

    assert _derive_candidate_market({"market": "CRYPTO"}) == "crypto"
    assert _derive_candidate_market({"market": "Equity_CN"}) == "equity_cn"


def test_resubmit_without_symbols_reports_existing_not_empty(client):
    """二次注册缺 symbols → 返回报既有 run 的真实标的，不返空列表谎称无标的（§3 反向不假）。"""

    r1 = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_sym_keep", "name": "x", "destination": "paper_desk",
        "market": "crypto", "symbols": ["BTCUSDT"],
    })
    assert r1.status_code == 200 and r1.json()["paper_run"]["symbols"] == ["BTCUSDT"]
    # 二次提交不带 symbols（仅带 market）——成功，但 symbols 必须仍报 ["BTCUSDT"] 不报 []。
    r2 = client.post("/api/strategy/submit_candidate", json={
        "run_id": "u1_sym_keep", "name": "x", "destination": "paper_desk", "market": "crypto",
    })
    assert r2.status_code == 200
    paper = r2.json()["paper_run"]
    assert paper["registered"] is True
    assert paper["symbols"] == ["BTCUSDT"], "缺标的二次注册不可返空列表谎称无标的"


# ════════════════ U5 并发 + perf 对抗（种已知坏门必抓） ════════════════
def test_prime_equity_points_equals_mtm_count_and_log_lines():
    """perf 修正不撕语义：equity_points 取内存 mtm_count，须 == mtm_count == 实际净值行数。"""

    svc = PaperDeskService()
    svc.register_run(run_id="u5_pts", name="x", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("u5_pts"))
    primed = svc.prime_run("u5_pts", ticks=11)
    eq = svc.equity_log("u5_pts")
    assert primed["mtm_count"] == 11, "11 轮 MTM → mtm_count==11"
    assert primed["equity_points"] == primed["mtm_count"], "equity_points 必 == mtm_count（perf 源一致）"
    assert primed["equity_points"] == len(eq), "equity_points 必 == 实际净值行数（不撕语义）"


def test_prime_empty_shell_equity_points_zero_via_mtm_count():
    """空壳分支同样用 mtm_count 算 equity_points：无 provider → 0，与净值恒空一致（不假绿灯）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="u5_shell", name="x", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("u5_shell"), simulate=False)
    primed = svc.prime_run("u5_shell", ticks=8)
    assert primed["equity_points"] == primed["mtm_count"] == 0
    assert svc.equity_log("u5_shell") == []


def test_reprime_after_start_does_not_tear_equity_log():
    """种已知坏门（M4 并发竞态）：start 启高频后台 loop 后反复 re-prime——

    旧坏门：prime 不停后台 loop 就复位 venue/state + 清空 equity_log，而 _bar_loop 正 mid-tick
    改同 venue._positions/_cash/state.bars_fed → reset 与 loop 撞车：dict mid-iterate 改抛
    RuntimeError、bars_fed 错乱、equity_log 撕裂/残留旧行（write_text("") 与 append 互撞）。
    本测试把 bar_interval 压到极小让 _bar_loop 高频 tick，扩大复位窗口的撞车概率（旧码必炸/漂）。
    新约束：prime 先 scheduler.stop() join 后台线程再复位/喂数据 → reset 段对 loop 原子。

    验收（每次 re-prime 后停 loop 取静默快照——观察 prime 的原子结果，排除重启后自由跑的 loop 混淆）：
      · prime_run 不抛异常（旧码并发改 _positions/_cash 会 RuntimeError/撕裂）；
      · equity_log 每行均为合法 JSON（撕裂写产半行 → json.loads 抛错）；
      · mtm_count == equity_points == 实际净值行数（计数与文件严格一致，无错乱/漂）；
      · prime 段产确定性 16 点序列（与基准单跑逐点相同，loop 未串入额外/撕裂/残留行）；
      · re-prime 不静默停掉用户已 start 的 run（每轮重启回 running）。
    """

    import json

    svc = PaperDeskService()
    svc.register_run(run_id="u5_race", name="x", origin="o", market="crypto",
                     symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("u5_race"))
    # 把 bar loop 间隔压到极小：_bar_loop 几乎不停 tick → 高频改 venue，放大复位窗口撞车概率。
    svc.get("u5_race").scheduler._cfg.bar_interval_seconds = 0.0001  # noqa: SLF001
    # 基准：单跑（未 start）确定性序列。
    svc.prime_run("u5_race", ticks=16)
    base_eq = [round(r["total_equity"], 6) for r in svc.equity_log("u5_race")]
    assert len(base_eq) == 16

    # start 高频后台 loop，随即反复 re-prime → 持续撞复位窗口（旧坏门在此撕裂/抛错）。
    # try/finally 包住：任一轮断言炸也确保停掉后台 daemon 线程（不泄漏高频 loop 到后续测试）。
    try:
        for _ in range(40):
            svc.start("u5_race")
            # prime_run 本身在并发下不得抛（旧码：reset 与 loop tick 撞车 → RuntimeError/撕裂）。
            primed = svc.prime_run("u5_race", ticks=16)
            # re-prime 不应停掉已 start 的 run（prime finally 须按原态重启）。
            assert svc.get("u5_race").scheduler.state.running is True, "re-prime 后 run 须仍在跑"
            # 停 loop 取静默快照：观察 prime 的原子产物，排除重启后自由跑的 loop 混淆计数。
            svc.stop("u5_race")
            path = svc.get("u5_race").equity_log_path
            raw = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            # 每行合法 JSON：撕裂写会产半行 → json.loads 抛错（旧坏门在此炸）。
            parsed = [json.loads(ln) for ln in raw]
            mtm = svc.get("u5_race").scheduler.state.mtm_count
            # 计数与文件严格一致：mtm_count == equity_points == 实际行数（无错乱/漂/残留）。
            assert mtm == primed["mtm_count"] == primed["equity_points"] == len(parsed), (
                f"计数/文件不一致：mtm={mtm} primed_mtm={primed['mtm_count']} "
                f"pts={primed['equity_points']} 行={len(parsed)}"
            )
            # prime 段产确定性 16 点：与基准单跑逐点相同（loop 未串入额外/撕裂/残留行）。
            got = [round(r["total_equity"], 6) for r in parsed]
            assert got == base_eq, "re-prime 净值须与基准单跑逐点一致（无 loop 污染/拼接/撕裂/残留）"
    finally:
        svc.stop("u5_race")  # 断言失败也停后台线程，绝不泄漏高频 daemon loop


def test_reprime_reset_failure_does_not_restart_loop_on_partial_state():
    """异常安全：复位段中途抛错（如喂数据失败），prime 不把后台 loop 拉回半复位 venue 上跑。

    种坏门：让 reset 后的 tick 抛 → prime_run 上抛异常，且已 start 的 run 不被静默重启
    （reset_ok=False → finally 不 start），避免后台 loop 在半复位状态上继续撕裂。
    """

    svc = PaperDeskService()
    svc.register_run(run_id="u5_excsafe", name="x", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("u5_excsafe"))
    svc.prime_run("u5_excsafe", ticks=4)
    svc.start("u5_excsafe")
    sched = svc.get("u5_excsafe").scheduler
    # 注入故障：mtm_once 抛错模拟复位段写盘/喂数据失败。
    boom = RuntimeError("simulated reset-phase failure")
    orig_mtm = sched.mtm_once
    sched.mtm_once = lambda: (_ for _ in ()).throw(boom)  # type: ignore[assignment, method-assign]
    try:
        with pytest.raises(RuntimeError):
            svc.prime_run("u5_excsafe", ticks=4)
        # reset_ok=False → finally 不重启：后台 loop 不被拉回半复位 venue 上继续跑。
        assert sched.state.running is False, "复位段抛错后 run 须保持 stopped（不在半复位态重启 loop）"
    finally:
        sched.mtm_once = orig_mtm  # type: ignore[method-assign]
        svc.stop("u5_excsafe")


# ---- helper ----
def _tmp_eqlog(name: str):
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / f"{name}_equity.jsonl"
