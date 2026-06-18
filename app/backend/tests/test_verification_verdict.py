"""验证官（部件12）的【对抗式】测试（T-020 / spine 04 §3.3 + 06 §7-4 + 00 §1.2-G C9）。

种已知坏门必抓：
  T1 异模型不一致即 BLOCK(不取均值) / T2 容差内一致 / T3 符号翻转→blocked /
  T4 同模型→独立性未确立→concern(非 consistent) / T5 声明未复算→concern(未验证≠pass) /
  T6 措辞守门(禁组织独立/independent/可信/安全/保证/可复现) / T7 verdict_id content-addressed /
  T8 NaN/Inf 不静默通过 / T9 决策级一致性 / T10 store 幂等+verdict_for /
  T11 集成 T-017(blocked→freeze BLOCK、concern→放行带 needs_review) /
  T12 集成 T-019(blocked/concern/未知 verdict→晋升缺口、consistent→无此缺口) /
  T13 concern≠pass(闸门权威) / T14 独立性轴计数 / T15 非法输入 raise / T16 to_review 形状。
"""

from __future__ import annotations

import pytest

from app.verification import (
    DISCLOSURE,
    Independence,
    Verifier,
    VerdictRecord,
    VerdictStore,
    VerifierError,
)


def _v():
    return Verifier()


# ── T1 · 异模型不一致即 BLOCK（不取均值） ──────────────────────────────────────────
def test_mismatch_blocks_not_averaged():
    rec = _v().reconcile(
        target_ref="cfg_v1_x", generator_model="gpt-gen", checker_model="claude-chk",
        claims={"sharpe": 2.0}, recomputed={"sharpe": 1.0},
    )
    assert rec.verdict == "blocked", "超容差不一致必须 BLOCK"
    # 不取均值：记录里保留两个原值，绝不出现 1.5
    cc = {c.key: c for c in rec.consistency_check}
    assert cc["sharpe"].claimed == 2.0 and cc["sharpe"].recomputed == 1.0
    assert all(c.recomputed != 1.5 for c in rec.consistency_check)


# ── T2 · 异模型容差内一致 → consistent ─────────────────────────────────────────────
def test_within_tol_consistent():
    rec = _v().reconcile(
        target_ref="cfg", generator_model="gpt", checker_model="claude",
        claims={"dsr": 0.9000000}, recomputed={"dsr": 0.9000001},
    )
    assert rec.verdict == "consistent"
    assert rec.independence.established and rec.independence.model_differs


# ── T3 · 符号翻转 → blocked（方向相反比小差更危险） ────────────────────────────────
def test_sign_flip_blocks():
    rec = _v().reconcile(
        target_ref="cfg", generator_model="gpt", checker_model="claude",
        claims={"alpha": 0.05}, recomputed={"alpha": -0.05},
    )
    assert rec.verdict == "blocked"
    assert {c.status for c in rec.consistency_check} == {"sign_flip"}


# ── T4 · 同模型(独立性未确立) 即便数值全合 → concern，不给 consistent（06 §7-4） ──────
def test_same_model_downgraded_to_concern():
    rec = _v().reconcile(
        target_ref="cfg", generator_model="gpt-4", checker_model="gpt-4",  # 同模型
        claims={"dsr": 0.9}, recomputed={"dsr": 0.9},
    )
    assert rec.verdict == "concern", "同模型共享盲点 → 不得判 consistent"
    assert not rec.independence.established
    assert "独立性未确立" in rec.independence.note


# ── T5 · 声明未能复算 → unverified → concern（未验证 ≠ pass） ───────────────────────
def test_unverified_claim_is_concern():
    rec = _v().reconcile(
        target_ref="cfg", generator_model="gpt", checker_model="claude",
        claims={"dsr": 0.9, "pbo": 0.1}, recomputed={"dsr": 0.9},  # pbo 未复算
    )
    assert rec.verdict == "concern"
    cc = {c.key: c for c in rec.consistency_check}
    assert cc["pbo"].status == "unverified"


# ── T6 · 裁决措辞守门（R7 / 00 §1.2-G / T-DET-10） ─────────────────────────────────
def test_disclosure_wording_banlist():
    text = DISCLOSURE
    low = text.lower()
    # 禁英文 independent validation / reproducible（子串）
    assert "independent validation" not in low
    assert "reproducible" not in low
    # 禁中文定性词
    for banned in ("可信", "安全", "保证", "可复现"):
        assert banned not in text, f"措辞禁词出现：{banned}"
    # 「组织独立」只能作为「非组织独立」出现（负向必需、正向禁止）
    assert "非组织独立" in text, "必须诚实声明非组织独立"
    assert "组织独立" not in text.replace("非组织独立", ""), "出现了正向『组织独立』断言"
    # 必含一致性检查语义 + 度量
    assert "consistency_check" in text and "一致性检查" in text and "度量" in text
    # 裁决记录本身也带该 disclosure
    rec = _v().reconcile(target_ref="c", generator_model="a", checker_model="b",
                         claims={"x": 1.0}, recomputed={"x": 1.0})
    assert rec.disclosure == DISCLOSURE


# ── T7 · verdict_id content-addressed（同输入同 id、异输入异 id、可复算） ───────────
def test_verdict_id_content_addressed():
    kw = dict(target_ref="cfg", generator_model="g", checker_model="c",
              claims={"s": 1.23}, recomputed={"s": 1.23})
    a = _v().reconcile(**kw)
    b = _v().reconcile(**kw)
    assert a.verdict_id == b.verdict_id and a.verdict_id.startswith("vd_")
    c = _v().reconcile(**{**kw, "recomputed": {"s": 9.99}})
    assert c.verdict_id != a.verdict_id, "不同对账结果必须不同 id"


# ── T8 · NaN/Inf 不静默通过 ────────────────────────────────────────────────────────
def test_nan_inf_not_silent_pass():
    rec = _v().reconcile(
        target_ref="cfg", generator_model="g", checker_model="c",
        claims={"x": float("nan")}, recomputed={"x": float("nan")},
    )
    assert rec.verdict == "blocked", "NaN 不可比 → 当作不一致，绝不静默 pass"


# ── T9 · 决策级一致性（离散，非数值） ──────────────────────────────────────────────
def test_decision_consistency():
    v = _v()
    same = v.reconcile_decision(target_ref="d", generator_decision="go_live",
                                checker_decision="go_live", generator_model="g", checker_model="c")
    assert same.verdict == "consistent"
    diff = v.reconcile_decision(target_ref="d", generator_decision="go_live",
                                checker_decision="hold", generator_model="g", checker_model="c")
    assert diff.verdict == "blocked"


# ── T10 · VerdictStore 幂等 + verdict_for ──────────────────────────────────────────
def test_store_idempotent_and_lookup(tmp_path):
    store = VerdictStore(tmp_path)
    rec = _v().reconcile(target_ref="cfg", generator_model="g", checker_model="c",
                         claims={"x": 1.0}, recomputed={"x": 1.0})
    store.record(rec)
    store.record(rec)  # 幂等：content-addressed 同 id 不重复写
    assert len([r for r in store.list_all() if r.verdict_id == rec.verdict_id]) == 1
    assert store.get(rec.verdict_id).verdict == "consistent"
    assert store.verdict_for(rec.verdict_id) == "consistent"
    assert store.verdict_for("vd_nonexistent") is None
    assert store.verdict_for(None) is None
    with pytest.raises(KeyError):
        store.get("vd_nope")


# ── T11 · 集成 T-017：blocked → freeze BLOCK；concern → 放行带 needs_review ─────────
def _hyp_store(tmp_path):
    from app.hypothesis import HypothesisCardStore
    return HypothesisCardStore(tmp_path)


_GOOD_TRIPLET = {
    "economic_mechanism": {
        "risk_premium_or_bias": "动量赌反应不足加处置效应",
        "causal_chain": "盈余漂移驱动价格延迟反应我们收割动量溢价",
        "confounder_concerns": ["规模", "流动性"],
    },
    "falsification_condition": "若A股融券年化利率持续高于15%则动量效应应在3个月内消失或反号",
    "stop_rule": "回撤超过20%或样本外IC连续3月为负则停",
}


def test_integration_t017_blocked_freeze(tmp_path):
    from app.hypothesis.store import FreezeRejected
    from app.lineage.ledger import Ledger
    st = _hyp_store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="theme", layer="confirmatory", falsifiable=_GOOD_TRIPLET)
    blocked = _v().reconcile(target_ref=c.card_id, generator_model="g", checker_model="c",
                             claims={"ic": 0.1}, recomputed={"ic": -0.4})  # 不一致 → blocked
    assert blocked.verdict == "blocked"
    with pytest.raises(FreezeRejected, match="blocked"):
        st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led,
                  review=blocked.to_review())


def test_integration_t017_concern_allows_with_review(tmp_path):
    from app.lineage.ledger import Ledger
    st = _hyp_store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="theme", layer="confirmatory", falsifiable=_GOOD_TRIPLET)
    concern = _v().reconcile(target_ref=c.card_id, generator_model="gpt", checker_model="gpt",  # 同模型→concern
                             claims={"ic": 0.1}, recomputed={"ic": 0.1})
    assert concern.verdict == "concern"
    frozen = st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led,
                       review=concern.to_review())
    assert frozen.status == "frozen" and frozen.needs_human_review, "concern 应放行但带 needs_human_review"


def test_integration_t017_wrong_target_ref_rejected(tmp_path):
    """复核 #1（T-017 侧）：拿【针对别的卡】产的 consistent 裁决冒名顶替 → freeze BLOCK。"""
    from app.hypothesis.store import FreezeRejected
    from app.lineage.ledger import Ledger
    st = _hyp_store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="theme", layer="confirmatory", falsifiable=_GOOD_TRIPLET)
    other = _v().reconcile(target_ref="some_other_card", generator_model="g", checker_model="c",
                           claims={"ic": 0.1}, recomputed={"ic": 0.1})  # consistent，但 target 是别的卡
    assert other.verdict == "consistent"
    with pytest.raises(FreezeRejected, match="张冠李戴"):
        st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led,
                  review=other.to_review())


# ── T12/T13 · 集成 T-019：verdict_lookup 接进晋升闸门 ───────────────────────────────
def _approval_svc(tmp_path, verdict_store):
    from app.approval import ApprovalGateService, ApprovalGateStore
    from app.lineage.ledger import Ledger
    return ApprovalGateService(
        ApprovalGateStore(tmp_path / "gates"),
        ledger=Ledger(tmp_path / "ledger"),
        verdict_lookup=verdict_store.record_for,   # 复核 #1：闸门取完整记录做 target_ref 绑定
    )


def _good_evidence(**over):
    from app.approval import EvidenceSnapshot
    base = dict(config_hash="cfg_v1_aaaa", dataset_version="ds1", n_eff=5, n_trials_raw=5,
                dsr=0.92, pbo=0.10, bootstrap_ci=(0.4, 1.8), bootstrap_estimate=1.0,
                champion_challenger={"verdict": "challenger_wins", "delta_sharpe": 0.3},
                returns_sha256="r1")
    base.update(over)
    return EvidenceSnapshot(**base).to_dict()


def _mk_verdict(verifier, store, *, kind):
    if kind == "consistent":
        rec = verifier.reconcile(target_ref="cfg_v1_aaaa", generator_model="g", checker_model="c",
                                 claims={"dsr": 0.92}, recomputed={"dsr": 0.92})
    elif kind == "blocked":
        rec = verifier.reconcile(target_ref="cfg_v1_aaaa", generator_model="g", checker_model="c",
                                 claims={"dsr": 0.92}, recomputed={"dsr": -0.1})
    else:  # concern (same model)
        rec = verifier.reconcile(target_ref="cfg_v1_aaaa", generator_model="g", checker_model="g",
                                 claims={"dsr": 0.92}, recomputed={"dsr": 0.92})
    assert rec.verdict == kind
    store.record(rec)
    return rec.verdict_id


def _open(svc, vrid):
    return svc.open_gate(model_id="m1", version=2, from_stage="dev", to_stage="production",
                         action_kind="promote_production", created_by="alice",
                         verification_record_id=vrid, evidence=_good_evidence(),
                         strategy_goal_ref="theme")


def test_integration_t019_consistent_passes_gate(tmp_path):
    store = VerdictStore(tmp_path / "verdicts")
    svc = _approval_svc(tmp_path, store)
    vid = _mk_verdict(_v(), store, kind="consistent")
    g = _open(svc, vid)
    assert g.decision == "pending", f"consistent 应过验证官闸门，缺口：{g.gap_list}"
    assert not any("验证官" in x for x in (g.gap_list or []))


def test_integration_t019_blocked_rejected(tmp_path):
    store = VerdictStore(tmp_path / "verdicts")
    svc = _approval_svc(tmp_path, store)
    vid = _mk_verdict(_v(), store, kind="blocked")
    g = _open(svc, vid)
    assert g.decision == "rejected"
    assert any("verdict=blocked" in x for x in g.gap_list)


def test_integration_t019_concern_rejected(tmp_path):
    store = VerdictStore(tmp_path / "verdicts")
    svc = _approval_svc(tmp_path, store)
    vid = _mk_verdict(_v(), store, kind="concern")
    g = _open(svc, vid)
    assert g.decision == "rejected", "concern ≠ pass：闸门必拒"
    assert any("verdict=concern" in x for x in g.gap_list)


def test_integration_t019_unknown_verdict_rejected(tmp_path):
    store = VerdictStore(tmp_path / "verdicts")
    svc = _approval_svc(tmp_path, store)
    g = _open(svc, "vd_never_produced")  # 给个查不到的 id
    assert g.decision == "rejected"
    assert any("查无权威裁决" in x for x in g.gap_list)


# ── T14 · 独立性轴计数（model/seed/slice） ─────────────────────────────────────────
def test_independence_axes_counted():
    rec = _v().reconcile(
        target_ref="cfg", generator_model="gpt", checker_model="claude",
        generator_seed=1, checker_seed=2, generator_slice="2020-2022", checker_slice="2023-2025",
        claims={"x": 1.0}, recomputed={"x": 1.0},
    )
    ind = rec.independence
    assert ind.model_differs and ind.seed_differs and ind.slice_differs and ind.axes == 3


# ── T15 · 非法输入 → VerifierError ─────────────────────────────────────────────────
def test_illegal_inputs_raise():
    v = _v()
    with pytest.raises(VerifierError):
        v.reconcile(target_ref="", generator_model="g", checker_model="c",
                    claims={"x": 1.0}, recomputed={"x": 1.0})
    with pytest.raises(VerifierError):
        v.reconcile(target_ref="c", generator_model="", checker_model="c",
                    claims={"x": 1.0}, recomputed={"x": 1.0})
    with pytest.raises(VerifierError):
        v.reconcile(target_ref="c", generator_model="g", checker_model="c",
                    claims={}, recomputed={})


# ── T16 · to_review 形状（T-017 消费的键齐全，含 target_ref 绑定） ─────────────────
def test_to_review_shape():
    rec = _v().reconcile(target_ref="c", generator_model="g", checker_model="c",
                         claims={"x": 1.0}, recomputed={"x": 1.0})
    rv = rec.to_review()
    for key in ("verdict_id", "target_ref", "checker_model", "verdict", "replay_ref", "notes",
                "consistency_check", "independence", "disclosure"):
        assert key in rv
    assert rv["target_ref"] == "c"
    # round-trip from_dict
    again = VerdictRecord.from_dict(rec.to_dict())
    assert again.verdict_id == rec.verdict_id and again.verdict == rec.verdict


# ── 复核回归 ───────────────────────────────────────────────────────────────────────

# 复核 #2 · 同模型靠大小写/空白伪装成异模型 → 仍判 concern（独立性度量非假定）
@pytest.mark.parametrize("gen,chk", [
    ("gpt-4", "GPT-4 "), ("gpt-4", " gpt-4"), ("gpt-4", "GPT-4"),
])
def test_model_disguise_still_concern(gen, chk):
    rec = _v().reconcile(target_ref="c", generator_model=gen, checker_model=chk,
                         claims={"dsr": 0.9}, recomputed={"dsr": 0.9})
    assert rec.verdict == "concern", f"{gen!r} vs {chk!r} 是同模型，不得判 consistent"
    assert not rec.independence.established


# 复核 #4 · NFC/NFD Unicode 等价拼写也算同模型 → concern
def test_model_disguise_nfc_nfd():
    import unicodedata
    name = "modèle-é"
    gen, chk = unicodedata.normalize("NFC", name), unicodedata.normalize("NFD", name)
    assert gen != chk  # 字节不同但语义同
    rec = _v().reconcile(target_ref="c", generator_model=gen, checker_model=chk,
                         claims={"dsr": 0.9}, recomputed={"dsr": 0.9})
    assert rec.verdict == "concern" and not rec.independence.established


# 复核 #5 · 自报 NaN/Inf + 缺对侧重算 → blocked（不落 concern）
@pytest.mark.parametrize("claims,recomp", [
    ({"x": float("nan")}, {}),
    ({"x": float("inf")}, {}),
    ({}, {"x": float("inf")}),
    ({"x": float("nan")}, {"x": 0.9}),
])
def test_asymmetric_nan_inf_blocks(claims, recomp):
    rec = _v().reconcile(target_ref="c", generator_model="g", checker_model="c",
                         claims=claims, recomputed=recomp)
    assert rec.verdict == "blocked", "自报 NaN/Inf 是垃圾值，缺对侧也必须 BLOCK 不当 concern"


# 复核 #3 · 落盘裁决被篡改 → 读路径 raise；闸门 fail-closed 不放行
def test_store_tamper_detected_and_gate_fails_closed(tmp_path):
    from app.verification import VerdictTamperError
    store = VerdictStore(tmp_path / "verdicts")
    rec = _v().reconcile(target_ref="cfg_v1_aaaa", generator_model="g", checker_model="c",
                         claims={"dsr": 0.92}, recomputed={"dsr": -0.5})  # blocked
    assert rec.verdict == "blocked"
    store.record(rec)
    # 手改落盘：把 blocked 翻成 consistent（verdict_id 不动）
    path = tmp_path / "verdicts" / "verdicts.jsonl"
    text = path.read_text(encoding="utf-8").replace('"verdict": "blocked"', '"verdict": "consistent"')
    path.write_text(text, encoding="utf-8")
    with pytest.raises(VerdictTamperError):
        store.get(rec.verdict_id)
    with pytest.raises(VerdictTamperError):
        store.verdict_for(rec.verdict_id)
    # 闸门 fail-closed：篡改记录 → 拒，不得静默放行
    svc = _approval_svc(tmp_path, store)
    g = _open(svc, rec.verdict_id)
    assert g.decision == "rejected"
    assert any("被篡改" in x or "不可信" in x for x in g.gap_list)


# 复核 #1 · 闸门拿【针对别的 config】产的 consistent 裁决冒名顶替 → 拒（张冠李戴）
def test_gate_rejects_target_ref_mismatch(tmp_path):
    store = VerdictStore(tmp_path / "verdicts")
    svc = _approval_svc(tmp_path, store)
    # 裁决 target_ref 是 unrelated，但 evidence config_hash 是 cfg_v1_aaaa
    rec = _v().reconcile(target_ref="unrelated_xyz", generator_model="g", checker_model="c",
                         claims={"foo": 1.0}, recomputed={"foo": 1.0})
    assert rec.verdict == "consistent"
    store.record(rec)
    g = _open(svc, rec.verdict_id)
    assert g.decision == "rejected", "无关裁决不得授权本次晋升"
    assert any("张冠李戴" in x for x in g.gap_list)


# 复核 #1b · verdict_id 哈希覆盖 target_ref：换 target_ref 即换 id（绑定真入哈希）
def test_verdict_id_includes_target_ref():
    a = _v().reconcile(target_ref="cfg_A", generator_model="g", checker_model="c",
                       claims={"x": 1.0}, recomputed={"x": 1.0})
    b = _v().reconcile(target_ref="cfg_B", generator_model="g", checker_model="c",
                       claims={"x": 1.0}, recomputed={"x": 1.0})
    assert a.verdict_id != b.verdict_id, "target_ref 不同必须产不同 verdict_id"
