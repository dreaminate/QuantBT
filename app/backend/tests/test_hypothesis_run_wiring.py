"""T-024 · 可证伪假设卡接进 Run 生命周期——接线层对抗测试（P2 不挡探索）。

假设卡【组件内部】行为（空机制 BLOCK、探索越权、honest-N 实读、措辞、谱系…）已由
`test_hypothesis_card.py`（35 测试）钉死。本文件只测【接线】：
- Run.layer / hypothesis_card_id 可空字段（store 不强制，向后兼容旧 run 行）。
- D-T024-FALS：低可证伪性 = 硬透明（不静默冻结）+ 软决定（human_reviewed override 仍可冻结、留痕进卡），
  启发式绝不自动硬挡；结构空机制 / 验证官 blocked 仍硬拒（不被 override 放过）。
- 5 个假设卡端点 + promote_model 假设卡闸门（confirmatory 过 gate；非 confirmatory 走真钱 → 拒；
  无 card_id → 不挡=向后兼容）。
- 措辞黑名单（R5/R7）：GateDecision 文案禁绝对化词。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import require_user_dependency
from app.experiments.store import Run, RunStore
from app.hypothesis import FreezeRejected, HypothesisCardStore
from app.hypothesis.card import CardFrozenError
from app.lineage.ledger import Ledger
from app.main import app

GOOD = {
    "economic_mechanism": {"risk_premium_or_bias": "动量源于投资者对盈余信息反应不足（行为偏差）",
                           "causal_chain": "盈余公告后漂移 → 价格延迟反应 → 截面动量截获"},
    "falsification_condition": "若动量因子的多空利差在样本外连续两季低于 0 则该效应已失效",
    "stop_rule": "回撤超过 20% 或样本外 IR 连续两季 < 0 即停",
}
# 套套逻辑（判据=策略自身收益）+ 无阈值 → confidence=low。
TAUTOLOGY = {**GOOD, "falsification_condition": "如果这个策略长期不赚钱就说明假设是错误的不成立"}
EMPTY = {"economic_mechanism": {"risk_premium_or_bias": "  ", "causal_chain": " "},
         "falsification_condition": "   ", "stop_rule": ""}

_BANNED = ("可信", "安全", "保证", "已验证", "trustworthy", "proven", "guarantee", "组织独立")


# ── A. Run 字段（向后兼容、store 不强制）─────────────────────────────────────
def test_run_has_nullable_layer_and_card_fields():
    r = Run(run_id="r1", experiment_id="e1", started_at_utc="t", finished_at_utc=None, status="running")
    assert r.layer is None and r.hypothesis_card_id is None  # 默认空，不破坏既有 Run
    d = r.to_dict()
    assert "layer" in d and "hypothesis_card_id" in d


def test_run_store_roundtrips_layer_and_old_rows_still_load(tmp_path):
    store = RunStore(tmp_path)
    # 直接写一条带 layer/card 的 run + 一条「旧格式」缺字段的行 → get_run 都能重建（默认兜底）。
    new_run = Run(run_id="r-new", experiment_id="e", started_at_utc="t", finished_at_utc=None,
                  status="succeeded", layer="confirmatory", hypothesis_card_id="card-x")
    store._store.append(new_run.to_dict())
    store._store.append({"run_id": "r-old", "experiment_id": "e", "started_at_utc": "t",
                         "finished_at_utc": None, "status": "succeeded"})  # 旧行无新字段
    assert store.get_run("r-new").layer == "confirmatory"
    assert store.get_run("r-new").hypothesis_card_id == "card-x"
    old = store.get_run("r-old")
    assert old.layer is None and old.hypothesis_card_id is None  # 向后兼容


# ── B. D-T024-FALS：低可证伪性 = 硬透明 + 软决定（store 级）──────────────────
def test_freeze_low_falsifiability_blocks_without_ack_then_overrides_with_log(tmp_path):
    store = HypothesisCardStore(tmp_path / "hyp")
    ledger = Ledger(tmp_path / "led")
    card = store.create(strategy_goal_ref="g", layer="confirmatory", falsifiable=TAUTOLOGY)

    # 硬透明：不 acknowledge → 拒（不静默冻结）。
    with pytest.raises(FreezeRejected, match="可证伪性"):
        store.freeze(card.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=ledger)

    # 软决定：显式 human_reviewed override → 仍可冻结，但 override 留痕进卡 + needs_human_review 永不静音。
    frozen = store.freeze(card.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=ledger,
                          human_reviewed=True, override_note="我承担：机制偏弱但先验证")
    assert frozen.status == "frozen"
    assert frozen.needs_human_review is True
    ov = frozen.multiplicity["falsifiability_override"]
    assert ov["acknowledged"] is True
    assert ov["overridden_confidence"] == "low"
    assert ov["note"] == "我承担：机制偏弱但先验证"
    # 绝不渲染成绿：可证伪性裁决仍记 low（硬记账）。
    assert frozen.multiplicity["falsifiability"]["confidence"] == "low"


def test_structural_empty_mechanism_hard_rejected_even_with_override(tmp_path):
    """T2 硬边界：结构空机制（三必填空白）即便 human_reviewed=True 也硬拒，不在 D-T024-FALS 软放之列。"""
    store = HypothesisCardStore(tmp_path / "hyp")
    ledger = Ledger(tmp_path / "led")
    card = store.create(strategy_goal_ref="g", layer="confirmatory", falsifiable=EMPTY)
    with pytest.raises(FreezeRejected):
        store.freeze(card.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=ledger, human_reviewed=True)


def test_verifier_blocked_hard_rejected_even_with_override(tmp_path):
    """验证官 blocked 是保留的硬边界，human_reviewed 放不过（与措辞启发式两回事）。"""
    store = HypothesisCardStore(tmp_path / "hyp")
    ledger = Ledger(tmp_path / "led")
    card = store.create(strategy_goal_ref="g", layer="confirmatory", falsifiable=GOOD)
    with pytest.raises(FreezeRejected, match="blocked"):
        store.freeze(card.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=ledger,
                     human_reviewed=True,
                     review={"verdict": "blocked", "target_ref": card.card_id, "notes": "异模型不一致"})


def test_override_record_is_frozen_immutable(tmp_path):
    """override 留痕进 content_hash → 冻结后改 multiplicity（含 override）即只读拒（防事后抹除）。"""
    store = HypothesisCardStore(tmp_path / "hyp")
    ledger = Ledger(tmp_path / "led")
    card = store.create(strategy_goal_ref="g", layer="confirmatory", falsifiable=TAUTOLOGY)
    frozen = store.freeze(card.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=ledger, human_reviewed=True)
    with pytest.raises(CardFrozenError):
        frozen.multiplicity = {}


# ── C. 端点 + promote_model 闸门（隔离：override 鉴权 + monkeypatch 全局 store/ledger）──
@pytest.fixture
def wired(tmp_path, monkeypatch):
    store = HypothesisCardStore(tmp_path / "hyp")
    ledger = Ledger(tmp_path / "led")
    monkeypatch.setattr("app.main.HYPOTHESIS_STORE", store)
    monkeypatch.setattr("app.main.LEDGER", ledger)
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="tester")
    try:
        yield TestClient(app), store, ledger
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_create_card_endpoint_exploratory_allows_empty_falsifiable(wired):
    """P2：探索卡 falsifiable 可空 → create 放行、停 draft。"""
    client, _store, _ = wired
    r = client.post("/api/hypothesis_cards", json={"strategy_goal_ref": "g", "layer": "exploratory"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft" and body["layer"] == "exploratory" and body["falsifiable"] is None


def test_freeze_endpoint_low_409_then_ack_200_with_override(wired):
    client, store, _ = wired
    card = store.create(strategy_goal_ref="g", layer="confirmatory", falsifiable=TAUTOLOGY)
    # 硬透明：不 ack → 409。
    r1 = client.post(f"/api/hypothesis_cards/{card.card_id}/freeze",
                     json={"frozen_oos": {"dataset_version": "ds1"}})
    assert r1.status_code == 409 and "可证伪性" in r1.json()["detail"]
    # 软决定：ack → 200 + 留痕。
    r2 = client.post(f"/api/hypothesis_cards/{card.card_id}/freeze",
                     json={"frozen_oos": {"dataset_version": "ds1"}, "human_reviewed": True,
                           "override_note": "ack"})
    assert r2.status_code == 200
    assert r2.json()["multiplicity"]["falsifiability_override"]["acknowledged"] is True


def test_gate_endpoint_exploratory_blocked(wired):
    """T4：探索层越权摸 OOS → gate BLOCK（P2 硬边界）。"""
    client, store, _ = wired
    card = store.create(strategy_goal_ref="g", layer="exploratory", falsifiable=GOOD)
    r = client.get(f"/api/hypothesis_cards/{card.card_id}/gate")
    assert r.status_code == 200
    body = r.json()
    assert body["allow"] is False and "探索层" in body["block_reason"]


def test_promote_card_endpoint_pollution_409(wired):
    """晋级绑已被源卡触碰过的切片 → 409。"""
    client, store, _ = wired
    src = store.create(strategy_goal_ref="g", layer="exploratory", falsifiable=GOOD,
                       touched_versions=["ds_explored"])
    r = client.post(f"/api/hypothesis_cards/{src.card_id}/promote",
                    json={"fresh_dataset_version": "ds_explored"})
    assert r.status_code == 409 and "探索污染" in r.json()["detail"]
    r2 = client.post(f"/api/hypothesis_cards/{src.card_id}/promote",
                     json={"fresh_dataset_version": "ds_clean"})
    assert r2.status_code == 200 and r2.json()["layer"] == "confirmatory"


def test_deviation_endpoint(wired):
    client, store, _ = wired
    card = store.create(strategy_goal_ref="g", layer="exploratory", falsifiable=GOOD)
    r = client.post(f"/api/hypothesis_cards/{card.card_id}/deviation",
                    json={"deviation": {"severity": "low", "note": "样本外漂移"}})
    assert r.status_code == 200 and r.json()["status"] == "deviated"


def test_promote_model_confirmatory_unfrozen_card_blocked_409(wired):
    """promote_model 接假设卡闸门：confirmatory 卡未冻结 → can_touch_final_oos BLOCK → 409。"""
    client, store, _ = wired
    card = store.create(strategy_goal_ref="g", layer="confirmatory", falsifiable=GOOD)  # draft, 未冻结
    r = client.post("/api/models/m1/promote",
                    json={"version": 1, "stage": "production", "hypothesis_card_id": card.card_id})
    assert r.status_code == 409
    assert r.json()["detail"]["hypothesis_gate_blocked"] is True
    assert "未冻结" in r.json()["detail"]["block_reason"]


def test_promote_model_exploratory_card_realmoney_409(wired):
    """D-T024 辅助校验：声明 exploratory 却要走真钱（production）→ 409，绝不自动晋级。"""
    client, store, _ = wired
    card = store.create(strategy_goal_ref="g", layer="exploratory", falsifiable=GOOD)
    r = client.post("/api/models/m1/promote",
                    json={"version": 1, "stage": "production", "hypothesis_card_id": card.card_id})
    assert r.status_code == 409
    assert "非 confirmatory" in r.json()["detail"]["block_reason"]


def test_promote_model_without_card_id_unchanged(wired):
    """向后兼容：不传 hypothesis_card_id → 假设卡闸门不触发（落到既有 promote → model 不存在 404，非 409）。"""
    client, _store, _ = wired
    r = client.post("/api/models/does-not-exist/promote", json={"version": 1, "stage": "production"})
    assert r.status_code != 409  # 绝非假设卡闸门拦的


def test_promote_model_exploratory_card_staging_not_gate_blocked(wired):
    """P2：探索卡 + 非真钱（staging，无 execution_mode）→ 假设卡闸门不挡（落到既有 promote）。"""
    client, store, _ = wired
    card = store.create(strategy_goal_ref="g", layer="exploratory", falsifiable=GOOD)
    r = client.post("/api/models/does-not-exist/promote",
                    json={"version": 1, "stage": "staging", "hypothesis_card_id": card.card_id})
    assert r.status_code != 409  # 探索不被挡（P2）


# ── D. 措辞黑名单（R5/R7）──────────────────────────────────────────────────
def test_gate_decision_wording_no_absolutes(wired):
    client, store, _ = wired
    card = store.create(strategy_goal_ref="g", layer="exploratory", falsifiable=GOOD)
    body = client.get(f"/api/hypothesis_cards/{card.card_id}/gate").json()
    blob = (body.get("block_reason") or "") + (body.get("disclaimer") or "") + " ".join(body.get("warnings") or [])
    for word in _BANNED:
        assert word not in blob, f"裁决文案含绝对化禁词 {word!r}：{blob}"
