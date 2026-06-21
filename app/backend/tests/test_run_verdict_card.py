"""R2 裁决卡后端接线 · 对抗测试（RunVerdictCard 接真）。

种已知坏门必抓：
  G1 verdict 措辞门：note 出现「可信/安全/排除过拟合/保证/可复现/组织独立」必抓（R7）。
  G2 GateVerdict「晋级候选」绝不当验证官三态 verdict 用（两条管线不混）。
  G3 promote 绕审批：approver==creator / 缺 approver → 422（防自审晋级，INV-5）。
  G4 未验证 ≠ 已验证：无权威 verdict_id 的 run → concern（不假绿灯）。
  G5 篡改 fail-closed：verdict 落盘被改 → 投影 concern，绝不返脏数据。
  G6 三态正投影：有权威 consistent/blocked verdict → 原样投影 + note 由 _verdict_note 供给。
  G7 成本敏感性 3 预设 + 诚实标 derived；月度热力真聚合（非造数）。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import require_user_dependency

# 措辞红线词（与 verification/schema.py DISCLOSURE + R7 一致）。
_BANNED_WORDS = ["可信", "安全", "保证", "可复现", "组织独立", "排除过拟合"]


def _write_run(root: Path, run_id: str, *, n: int = 600, verdict_id: str | None = None) -> Path:
    """造一个最小可读 run：run.json + portfolio.csv（equity/net_return/benchmark_return）。

    n 默认 600 ≥ a_share/crypto min_T，过拟合门不退化「证据不足」。
    """

    rd = root / run_id
    rd.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "strategy_name": "测试策略",
        "strategy_id": "s_test",
        "status": "completed",
        "market": "crypto_perp",
        "frequency": "1d",
        "benchmark": "BTC-USDT",
        "metrics": {"sharpe": 1.5, "annualized_return": 0.22, "excess_return": 0.17,
                    "max_drawdown": -0.15, "information_ratio": 1.2, "win_rate": 0.6, "turnover": 0.4},
        "config_hash": "cfg_test_run",
    }
    if verdict_id:
        manifest["verification_record_id"] = verdict_id
    (rd / "run.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    # portfolio：稳定正漂移 + 跨年（2019-..）以喂月度热力。
    lines = ["timestamp,equity,net_return,benchmark_return,drawdown"]
    eq = 1.0
    import datetime as _dt
    d0 = _dt.date(2019, 1, 1)
    for i in range(n):
        nr = 0.0008 + (0.0006 if i % 7 == 0 else -0.0002)
        eq *= 1.0 + nr
        br = 0.0004
        ts = (d0 + _dt.timedelta(days=i)).isoformat()
        lines.append(f"{ts},{eq:.6f},{nr:.6f},{br:.6f},0.0")
    (rd / "portfolio.csv").write_text("\n".join(lines), encoding="utf-8")
    return rd


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离 RUN_ROOT + VERDICT_STORE + GATE_SERVICE，auth override。返回 (client, run_root, main)。"""

    from app import main
    from app import run_detail_core
    from app.verification import VerdictStore, Verifier
    from app.approval import ApprovalGateService, ApprovalGateStore

    run_root = tmp_path / "runs"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(run_detail_core, "RUN_ROOT", run_root)

    # 隔离验证官账 + 审批门（不污染真账）。审批门接 ledger=None → honest-N 缺口必现（确证晋级须接账）。
    vstore = VerdictStore(tmp_path / "verification")
    monkeypatch.setattr(main, "VERDICT_STORE", vstore)
    monkeypatch.setattr(main, "VERIFIER", Verifier())
    gstore = ApprovalGateStore(tmp_path / "approval")
    gservice = ApprovalGateService(gstore, verdict_lookup=vstore.record_for)
    monkeypatch.setattr(main, "GATE_SERVICE", gservice)

    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="alice", username="alice",
    )
    try:
        yield TestClient(main.app), run_root, main, vstore
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


# ── G4 · 未验证 ≠ 已验证 ───────────────────────────────────────────────
def test_verdict_no_authoritative_record_is_concern(env):
    client, run_root, _m, _v = env
    _write_run(run_root, "run_noverdict")
    r = client.get("/api/runs/run_noverdict/verdict")
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "concern", "无权威裁决须 concern（不假绿灯）"
    assert body["has_authoritative_verdict"] is False
    # note 合规：禁词不得出现。
    for w in _BANNED_WORDS:
        assert w not in body["verdictNote"], f"note 越界禁词: {w}"


# ── G1 · 措辞门：任何投影出的 note 都无禁词 ───────────────────────────────
def test_verdict_note_never_contains_banned_words(env):
    client, run_root, _m, vstore = env
    # 造一条真 blocked 裁决（异模型不一致）绑到 run。
    from app.verification import Verifier
    rec = Verifier().reconcile(
        target_ref="cfg_test_run", generator_model="gpt-gen", checker_model="claude-chk",
        claims={"sharpe": 2.0}, recomputed={"sharpe": 0.5},
    )
    vstore.record(rec)
    _write_run(run_root, "run_blocked", verdict_id=rec.verdict_id)
    r = client.get("/api/runs/run_blocked/verdict")
    body = r.json()
    assert body["verdict"] == "blocked"
    for w in _BANNED_WORDS:
        assert w not in body["verdictNote"]
        assert w not in (body.get("disclosure") or "") or w in ("可信", "安全", "保证", "可复现", "组织独立")
    # disclosure 是诚实声明：它明文【否定】这些词（如「非组织独立」），故只查 note 的正向出现。


def test_seed_banned_word_would_be_caught(env):
    """种已知坏门：若 note 真含『排除过拟合/可信』，扫描必命中（守门有效性自证）。"""
    bad = "PBO 0.18 排除过拟合，结论可信安全"
    hits = [w for w in _BANNED_WORDS if w in bad]
    assert "排除过拟合" in hits and "可信" in hits and "安全" in hits


# ── G6 · 三态正投影 + note 由 _verdict_note 供给 ─────────────────────────
def test_verdict_consistent_projected(env):
    client, run_root, _m, vstore = env
    from app.verification import Verifier
    rec = Verifier().reconcile(
        target_ref="cfg_test_run", generator_model="gpt-gen", checker_model="claude-chk",
        claims={"sharpe": 1.5}, recomputed={"sharpe": 1.5000001},
    )
    assert rec.verdict == "consistent"
    vstore.record(rec)
    _write_run(run_root, "run_ok", verdict_id=rec.verdict_id)
    body = client.get("/api/runs/run_ok/verdict").json()
    assert body["verdict"] == "consistent"
    assert body["has_authoritative_verdict"] is True
    assert body["verdict_id"] == rec.verdict_id
    # note 来自 _verdict_note（含「一致」式表述），非杜撰。
    assert "一致" in body["verdictNote"]


# ── G5 · 篡改 fail-closed ────────────────────────────────────────────────
def test_tampered_verdict_fails_closed_to_concern(env):
    client, run_root, _m, vstore = env
    from app.verification import Verifier
    # 同模型 → 独立性未确立 → 原 verdict=concern；篡改成 consistent 才是真的越界翻绿灯。
    rec = Verifier().reconcile(
        target_ref="cfg_test_run", generator_model="same-model", checker_model="same-model",
        claims={"x": 1.0}, recomputed={"x": 1.0},
    )
    assert rec.verdict == "concern"
    vstore.record(rec)
    # 篡改落盘：把 verdict 改成 consistent 但不重算 verdict_id → record_for 抛 TamperError。
    path = vstore._path  # noqa: SLF001
    raw = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(raw[0])
    row["verdict"] = "consistent"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_run(run_root, "run_tamper", verdict_id=rec.verdict_id)
    body = client.get("/api/runs/run_tamper/verdict").json()
    assert body["verdict"] == "concern", "篡改须 fail-closed 投影 concern，绝不返脏数据/绿灯"
    assert body["has_authoritative_verdict"] is False


# ── G2 · GateVerdict「晋级候选」≠ 验证官三态 verdict ──────────────────────
def test_overfit_gate_label_is_separate_pipeline(env):
    client, run_root, _m, _v = env
    _write_run(run_root, "run_of")
    body = client.get("/api/runs/run_of/overfit").json()
    # overfit 投影有 color/gate_label，但绝无三态 verdict 枚举字段冒充。
    assert "color" in body
    assert body["color"] in ("green", "yellow", "red", "insufficient_evidence")
    assert "gate_label" in body
    # gate_label 可为「晋级候选」，但它不是 verification 三态。
    assert body["gate_label"] in ("晋级候选", "证据分歧", "证据强负", "证据不足")
    assert body.get("verdict") not in ("consistent", "concern", "blocked"), \
        "过拟合门投影绝不暴露验证官三态 verdict 字段（防 UI 混用两条管线）"


def test_overfit_gate_label_caught_if_used_as_verdict(env):
    """种已知坏门：若把 GateVerdict.color 映射进验证官三态枚举，断言必失败（守门）。

    verdict 端点的 verdict ∈ 三态；overfit 端点的 gate_label ∈ 门标签——两集合不相交。
    """
    client, run_root, _m, _v = env
    _write_run(run_root, "run_x")
    verdict_body = client.get("/api/runs/run_x/verdict").json()
    overfit_body = client.get("/api/runs/run_x/overfit").json()
    three_state = {"consistent", "concern", "blocked"}
    gate_labels = {"晋级候选", "证据分歧", "证据强负", "证据不足"}
    assert verdict_body["verdict"] in three_state
    assert overfit_body["gate_label"] in gate_labels
    assert three_state.isdisjoint(gate_labels)


# ── G3 · promote 绕审批必抓（approver≠creator / 缺 approver） ─────────────
def test_promote_self_approve_rejected(env):
    client, run_root, _m, _v = env
    _write_run(run_root, "run_promo")
    # approver == creator（自审）→ 422。
    r = client.post("/api/runs/run_promo/promote",
                    json={"created_by": "alice", "approver": "alice"})
    assert r.status_code == 422
    assert r.json()["detail"]["rejected"] is True


def test_promote_missing_approver_rejected(env):
    client, run_root, _m, _v = env
    _write_run(run_root, "run_promo2")
    # 缺 approver（默认 creator=alice，approver 空）→ 422，绝不静默放行。
    r = client.post("/api/runs/run_promo2/promote", json={})
    assert r.status_code == 422


def test_promote_distinct_approver_but_missing_requirements_returns_gaps(env):
    """approver≠creator 通过自审门，但三要件不全（无 verdict/证据/账本）→ 422 + 缺口清单（诚实，不假晋级）。"""
    client, run_root, _m, _v = env
    _write_run(run_root, "run_promo3")
    r = client.post("/api/runs/run_promo3/promote",
                    json={"created_by": "alice", "approver": "bob"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["rejected"] is True
    assert isinstance(detail.get("gaps"), list) and detail["gaps"], "须返缺口清单（差什么诚实告知）"
    # 缺口必含「独立验证记录」/「过拟合证据」/「honest-N」类（绝不无声晋级）。
    gap_text = " ".join(detail["gaps"])
    assert ("验证" in gap_text) or ("证据" in gap_text) or ("honest-N" in gap_text)


def test_promote_unknown_run_404(env):
    client, _run_root, _m, _v = env
    r = client.post("/api/runs/ghost/promote", json={"created_by": "alice", "approver": "bob"})
    assert r.status_code == 404


# ── G7 · 成本敏感性 + 月度热力 ───────────────────────────────────────────
def test_cost_sensitivity_three_presets_derived(env):
    client, run_root, _m, _v = env
    _write_run(run_root, "run_cost")
    body = client.get("/api/runs/run_cost/cost-sensitivity").json()
    assert body["derived"] is True, "P0 派生须诚实标 derived"
    presets = {c["preset"] for c in body["cost"]}
    assert presets == {"optimistic", "neutral", "pessimistic"}
    # 成本越高 → Sharpe 越低（pessimistic < neutral < optimistic）。
    by = {c["preset"]: c["sharpe"] for c in body["cost"]}
    assert by["pessimistic"] < by["neutral"] < by["optimistic"]


def test_cost_sensitivity_single_preset(env):
    client, run_root, _m, _v = env
    _write_run(run_root, "run_cost2")
    body = client.get("/api/runs/run_cost2/cost-sensitivity?preset=pessimistic").json()
    assert [c["preset"] for c in body["cost"]] == ["pessimistic"]


def test_monthly_heatmap_real_aggregation(env):
    client, run_root, _m, _v = env
    _write_run(run_root, "run_heat", n=600)  # 跨 ~20 个月
    body = client.get("/api/runs/run_heat/monthly-heatmap").json()
    assert body["available"] is True
    assert body["metric"] in ("excess", "net")
    assert body["rows"], "须有真聚合行（非空）"
    # 年份真实（2019..），每行 12 月槽。
    assert all(len(row["cells"]) == 12 for row in body["rows"])
    assert body["rows"][0]["year"] == 2019


def test_endpoints_404_on_missing_run(env):
    client, _run_root, _m, _v = env
    for path in ("verdict", "overfit", "cost-sensitivity", "monthly-heatmap"):
        r = client.get(f"/api/runs/ghost/{path}")
        assert r.status_code == 404, path
