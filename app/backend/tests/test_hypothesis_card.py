"""可证伪假设卡的【对抗式】测试（T-017 / spine 04 §5）。

种已知坏门必抓。T1 可证伪启发式(含字数达标的套套逻辑) / T2 空机制 BLOCK + 探索留空放行 /
T3 OOS 探索污染 / T4 探索层越权 / T5 honest-N 实读不可改小(接真 T-013 一本账) / T5b 噪声 /
T6 content_hash 篡改 + T6b 键序/NFC / T7 冻结只读+fork / T8 晋级谱系 / T10 冻结幂等 +
T10b 并发 / T11 崩溃恢复 / T12 措辞守门。
"""

from __future__ import annotations

import threading

import pytest

from app.hypothesis import (
    CardFrozenError,
    HypothesisCardStore,
    LineageHook,
    assess_falsifiability,
    can_touch_final_oos,
    compute_content_hash,
)
from app.hypothesis.card import HypothesisCard
from app.hypothesis.store import FreezeRejected, PromoteRejected
from app.lineage.ledger import Ledger
from app.strategy_goal import FalsifiableTriplet

GOOD = {
    "economic_mechanism": {
        "risk_premium_or_bias": "动量赌反应不足加处置效应",
        "causal_chain": "盈余漂移驱动价格延迟反应我们收割动量溢价",
        "confounder_concerns": ["规模", "流动性"],
    },
    "falsification_condition": "若A股融券年化利率持续高于15%则动量效应应在3个月内消失或反号",
    "stop_rule": "回撤超过20%或样本外IC连续3月为负则停",
}


def _store(tmp_path, events=None):
    hook = LineageHook(on_event=(lambda e, p: events.append((e, p))) if events is not None else None)
    return HypothesisCardStore(tmp_path, lineage_hook=hook)


# ── T1 · 不可证伪条件（四规则，含字数达标的套套逻辑）→ 不静默冻结 ──────────────────
@pytest.mark.parametrize("fc, expect_codes", [
    ("如果这个策略长期不赚钱就说明假设是错的", {"tautology"}),                       # (a) 套套逻辑(≥12)
    ("该动量效应在任何市场环境下都将长期持续有效永不衰减", {"no_antecedent"}),       # (b) 无前置(≥12)
    ("若整体市场宏观环境发生显著变化则该效应表现也会随之改变", {"no_threshold"}),     # (c) 无阈值(≥12)
    ("如果这个策略在未来长期持续不能盈利那就证明假设是错误的无疑", {"tautology"}),    # (d) 字数达标的套套逻辑
], ids=["tautology", "no_antecedent", "no_threshold", "wordy_tautology"])
def test_falsifiability_catches_unfalsifiable(fc, expect_codes):
    triplet = FalsifiableTriplet(**{**GOOD, "falsification_condition": fc})
    v = assess_falsifiability(triplet)
    assert v.confidence in {"low", "medium"}, f"不可证伪条件被判 high（字数门，门坏）：{fc}"
    assert expect_codes & {c for c, _ in v.flags}, f"未命中预期规则 {expect_codes}：{v.flags}"


def test_good_mechanism_is_high_confidence():
    v = assess_falsifiability(FalsifiableTriplet(**GOOD))
    assert v.confidence == "high", f"良构可证伪卡被误杀：{v.flags}"


def test_freeze_not_silent_for_unfalsifiable(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="g1", layer="confirmatory",
                  falsifiable={**GOOD, "falsification_condition": "如果策略不赚钱就说明假设错了该效应不成立"})
    # 套套逻辑(tautology)+无阈值(no_threshold) → low → 不静默冻结（须人工复核）。
    with pytest.raises(FreezeRejected, match="可证伪性"):
        st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)


# ── T2 · 空机制 → confirmatory freeze BLOCK；探索留空 → 放行（P2 反向）──────────────
def test_empty_mechanism_blocks_confirmatory_but_allows_exploratory(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    # confirmatory 空白三必填 → freeze BLOCK，返回可读原因
    bad = st.create(strategy_goal_ref="g1", layer="confirmatory",
                    falsifiable={"economic_mechanism": {"risk_premium_or_bias": "  ", "causal_chain": " "},
                                 "falsification_condition": "   ", "stop_rule": ""})
    with pytest.raises(FreezeRejected):
        st.freeze(bad.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    # 反向：探索卡留空 falsifiable → create 放行（P2 不挡探索），停在 draft
    exp = st.create(strategy_goal_ref="g1", layer="exploratory", falsifiable=None)
    assert exp.status == "draft" and exp.falsifiable is None


# ── T3 · OOS 探索污染：晋级绑已碰过的数据 → BLOCK；consumed → gate BLOCK ────────────
def test_oos_pollution_and_consumed_blocked(tmp_path):
    st = _store(tmp_path)
    src = st.create(strategy_goal_ref="g1", layer="exploratory", falsifiable=GOOD,
                    touched_versions=["ds_explored"])
    with pytest.raises(PromoteRejected, match="探索污染"):
        st.promote_to_confirmatory(src.card_id, fresh_dataset_version="ds_explored")
    # 干净 OOS 可晋级
    promoted = st.promote_to_confirmatory(src.card_id, fresh_dataset_version="ds_fresh")
    assert promoted.layer == "confirmatory" and promoted.parent_card_id == src.card_id
    # consumed 的 OOS → gate BLOCK
    led = Ledger(tmp_path / "ledger")
    frozen = st.freeze(promoted.card_id, frozen_oos={"dataset_version": "ds_fresh", "consumed": True}, ledger=led)
    g = can_touch_final_oos(frozen)
    assert g.allow is False and "已被消费" in g.block_reason


# ── T4 · 探索层越权摸 OOS → gate BLOCK（P2 硬边界）──────────────────────────────
def test_exploratory_cannot_touch_oos(tmp_path):
    st = _store(tmp_path)
    c = st.create(strategy_goal_ref="g1", layer="exploratory", falsifiable=GOOD)
    g = can_touch_final_oos(c)
    assert g.allow is False and "探索层" in g.block_reason


# ── T5 · honest-N 实读自真 T-013 一本账、不可改小、不接受调用方传 N ──────────────────
def test_honest_n_read_from_real_ledger_and_immutable(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c1 = st.create(strategy_goal_ref="theme", layer="confirmatory", falsifiable=GOOD)
    f1 = st.freeze(c1.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    assert f1.multiplicity["honest_n_at_freeze"] == 1
    c2 = st.create(strategy_goal_ref="theme", layer="confirmatory", falsifiable=GOOD)
    f2 = st.freeze(c2.card_id, frozen_oos={"dataset_version": "ds2"}, ledger=led)
    assert f2.multiplicity["honest_n_at_freeze"] == 2, "第二张 confirmatory 卡未计入 honest-N（card_freeze 没进账，门坏）"
    # freeze() 无 N 入参——调用方无法谎报；且冻结后 multiplicity 只读，改不小。
    import inspect
    assert "honest_n" not in inspect.signature(st.freeze).parameters, "freeze 暴露了 N 入参（可谎报，门坏）"
    with pytest.raises(CardFrozenError):
        f2.multiplicity = {"honest_n_at_freeze": 1}   # 冻结后改小 N → 只读拒绝


# ── T5b · 噪声机制（字数格式达标的随机文本）→ low，不判 high ────────────────────────
def test_noise_mechanism_low_confidence():
    noisy = {
        "economic_mechanism": {"risk_premium_or_bias": "asdfghjkl qwerty zxcvbnm 占位文本",
                               "causal_chain": "lkjhgfdsa mnbvcxz poiuytrewq 随机串"},
        "falsification_condition": "qwertyuiop asdfghjkl 随机乱码文本占位无意义内容",
        "stop_rule": "zxcvbnm 停机占位",
    }
    v = assess_falsifiability(FalsifiableTriplet(**noisy))
    assert v.confidence == "low", f"噪声蒙混过关被判 {v.confidence}（门坏）：{v.flags}"
    assert "noise" in {c for c, _ in v.flags}


# ── T6 · content_hash 篡改被检出（读路径对账，复核 #7）+ exclude 集不变量 ────────────
def test_content_hash_tamper_detected_on_read(tmp_path):
    import json as _json
    from app.hypothesis import CardTamperError

    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="g1", layer="confirmatory", falsifiable=GOOD)
    frozen = st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    stored = frozen.content_hash
    assert compute_content_hash(frozen) == stored
    # 种坏：直改落盘 JSONL 的受哈希字段（falsification_condition），不更新 content_hash。
    path = tmp_path / "hypothesis_cards.jsonl"
    lines = path.read_text().splitlines()
    row = _json.loads(lines[-1])
    row["falsifiable"]["falsification_condition"] = "篡改后若融券利率高于99%则动量效应消失或反号"
    lines[-1] = _json.dumps(row, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(CardTamperError):
        _store(tmp_path).get(c.card_id)


def test_content_hash_exclude_set_invariant(tmp_path):
    # exclude 集正确性：用 draft 卡（可变）直接验 compute_content_hash 的 include/exclude 边界。
    st = _store(tmp_path)
    base = st.create(strategy_goal_ref="g1", layer="confirmatory", falsifiable=GOOD)
    h0 = compute_content_hash(base)
    # 改 exclude 字段（deviations/review）→ hash 不变
    base.deviations = [{"x": 1}]
    base.review = {"verdict": "consistent"}
    assert compute_content_hash(base) == h0, "改 exclude 字段 hash 却变了（exclude 集错，门坏）"
    # 改受哈希字段（falsifiable）→ hash 必变
    base.falsifiable = {**GOOD, "stop_rule": "回撤超过30%即停不同了"}
    assert compute_content_hash(base) != h0, "改受哈希字段 hash 没变（漏哈希，门坏）"


# ── 复核 #1/#2/#14 · 自指标(净值/累计收益/夏普) + 英文循环判据不得判 high ──────────
@pytest.mark.parametrize("fc", [
    "当策略的累计收益回撤超过历史最大值时假设即被证伪",          # #1 自指标(累计收益/回撤)
    "一旦本策略的样本外夏普低于0.5则推翻该价值假设",            # #1 自指标(夏普)
    "if the strategy cumulative return falls below 0 the thesis is wrong",  # #2 英文循环
    "当超额收益消失或因子失效时该假设不再成立",                 # #14 领域词包装的循环
], ids=["equity_dd", "sharpe", "english", "domain_dressed"])
def test_self_result_circular_not_high(fc):
    v = assess_falsifiability(FalsifiableTriplet(**{**GOOD, "falsification_condition": fc}))
    assert v.confidence != "high", f"自指/循环判据被判 high（字词门退化，门坏）：{fc} → {v.flags}"
    assert "tautology" in {c for c, _ in v.flags}


# ── 复核 #3 · 英文真可证伪机制不被误杀 ─────────────────────────────────────────
def test_english_falsifiable_not_false_killed():
    eng = {
        "economic_mechanism": {"risk_premium_or_bias": "momentum premium from underreaction",
                               "causal_chain": "earnings drift drives delayed price reaction we harvest momentum premium",
                               "confounder_concerns": ["size", "liquidity"]},
        "falsification_condition": "if the funding rate stays above 15% annualized the momentum effect should disappear within 3 months",
        "stop_rule": "stop when drawdown exceeds 20 percent",
    }
    v = assess_falsifiability(FalsifiableTriplet(**eng))
    assert v.confidence == "high", f"英文良构可证伪卡被误杀（阈值/前置英文盲，门坏）：{v.flags}"


# ── 复核 #6 · 冻结后 deviation 翻状态不能重开 hashed 字段 ──────────────────────────
def test_deviation_does_not_reopen_frozen_fields(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="g1", layer="confirmatory", falsifiable=GOOD)
    st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    st.deviation(c.card_id, {"severity": "high", "why": "regime shift"})
    # 关键：从盘【重新加载】deviated 卡（status 已是 deviated）——核心字段仍须锁死。
    # 这条专杀「sticky 只认 status=='frozen'」的实现：重载 deviated 行时 _frozen_core 必须仍为真。
    reloaded = st.get(c.card_id)
    assert reloaded.status == "deviated"
    with pytest.raises(CardFrozenError):
        reloaded.falsifiable = {"x": 1}        # 翻成 deviated 后重载仍锁核心字段
    with pytest.raises(CardFrozenError):
        reloaded.content_hash = "forged"


# ── 复核 #10 · secondary 层卡不可冻结、过不了 gate ─────────────────────────────────
def test_secondary_layer_cannot_freeze_or_touch_oos(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="g1", layer="secondary", falsifiable=GOOD)
    with pytest.raises(FreezeRejected, match="confirmatory"):
        st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)


# ── 复核 #11/#15 · 冻结必须绑 frozen_oos.dataset_version + 必须接 ledger ──────────────
def test_freeze_requires_frozen_oos_and_ledger(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="g1", layer="confirmatory", falsifiable=GOOD)
    with pytest.raises(FreezeRejected, match="frozen_oos"):
        st.freeze(c.card_id, frozen_oos=None, ledger=led)
    c2 = st.create(strategy_goal_ref="g1", layer="confirmatory", falsifiable=GOOD)
    with pytest.raises(FreezeRejected, match="一本账"):
        st.freeze(c2.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=None)


# ── 复核 #9 · promote 后 freeze 重绑探索碰过的 OOS → BLOCK ──────────────────────────
def test_freeze_cannot_rebind_polluted_oos(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    src = st.create(strategy_goal_ref="g1", layer="exploratory", falsifiable=GOOD,
                    touched_versions=["ds_explored"])
    promoted = st.promote_to_confirmatory(src.card_id, fresh_dataset_version="ds_fresh")
    # 用干净版 ds_fresh 晋级，却在 freeze 时重绑被探索碰过的 ds_explored → 必 BLOCK
    with pytest.raises(FreezeRejected, match="探索污染"):
        st.freeze(promoted.card_id, frozen_oos={"dataset_version": "ds_explored"}, ledger=led)


# ── 复核 #13 · freeze/deviation 发 PROV 事件（不静默丢） ───────────────────────────
def test_freeze_and_deviation_emit_lineage(tmp_path):
    events = []
    st = _store(tmp_path, events=events)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="g1", layer="confirmatory", falsifiable=GOOD)
    st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    assert sum(1 for e in events if e[0] == "card.freeze") == 1, "freeze 未发/多发 PROV 事件（门坏）"
    st.deviation(c.card_id, {"severity": "low"})
    assert any(e[0] == "card.deviate" for e in events), "deviation 未发 PROV 事件（门坏）"


# ── T7 · 冻结只读 → CardFrozenError；改须 fork ──────────────────────────────────
def test_frozen_readonly_and_fork(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="g1", layer="confirmatory", falsifiable=GOOD)
    frozen = st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    with pytest.raises(CardFrozenError):
        frozen.falsifiable = {"x": 1}
    fork = st.fork_card(frozen.card_id)
    assert fork.card_id != frozen.card_id and fork.parent_card_id == frozen.card_id and fork.status == "draft"
    # 原卡仍在（append-only，不被覆写）
    assert st.get(frozen.card_id).status == "frozen"


# ── T8 · 晋级谱系：parent 指回 + 两卡共存 + 发 PROV 事件 ──────────────────────────
def test_promote_lineage_event(tmp_path):
    events = []
    st = _store(tmp_path, events=events)
    src = st.create(strategy_goal_ref="g1", layer="exploratory", falsifiable=GOOD)
    promoted = st.promote_to_confirmatory(src.card_id, fresh_dataset_version="ds_fresh")
    assert promoted.parent_card_id == src.card_id
    assert {c.card_id for c in st.list_cards("g1")} >= {src.card_id, promoted.card_id}, "探索卡被删（应降级不删，门坏）"
    assert any(e[0] == "card.promote" for e in events), "晋级未发 PROV 事件（审计缺一段，门坏）"


# ── T10 · 冻结幂等：重复 freeze → 返存量、不重复计 N ──────────────────────────────
def test_freeze_idempotent(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="theme", layer="confirmatory", falsifiable=GOOD)
    f1 = st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    f2 = st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    assert f1.content_hash == f2.content_hash and f1.frozen_at_utc == f2.frozen_at_utc
    assert led.honest_n("theme") == 1, "重复 freeze 重复计入 honest-N（门坏）"


# ── T10b · 并发双写：同卡两线程 freeze → 只一条冻结、N 只 +1 ───────────────────────
def test_concurrent_freeze_single_record(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="theme", layer="confirmatory", falsifiable=GOOD)
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        try:
            st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
        except Exception:  # noqa: BLE001
            pass

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert led.honest_n("theme") == 1, "并发 freeze 把 honest-N 计了多次（门坏）"
    assert st.get(c.card_id).status == "frozen"


# ── T11 · 崩溃恢复：jsonl 半行不炸库 ───────────────────────────────────────────
def test_crash_recovery_bad_line(tmp_path):
    st = _store(tmp_path)
    c = st.create(strategy_goal_ref="g1", layer="exploratory", falsifiable=GOOD)
    with (tmp_path / "hypothesis_cards.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"card_id": "card-broken", "half')   # 半行
    st2 = _store(tmp_path)
    assert st2.get(c.card_id).card_id == c.card_id, "一个坏行让卡库不可读（门坏）"


# ── T12 · 裁决措辞守门：禁绝对化词、必带 needs_human_review + 免责 ──────────────────
def test_gate_wording_no_absolutes(tmp_path):
    st = _store(tmp_path)
    led = Ledger(tmp_path / "ledger")
    c = st.create(strategy_goal_ref="g1", layer="confirmatory",
                  falsifiable={**GOOD, "economic_mechanism": {**GOOD["economic_mechanism"], "confounder_concerns": []}})
    frozen = st.freeze(c.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    g = can_touch_final_oos(frozen, honest_n_now=5)
    text = g.disclaimer + " ".join(g.warnings) + (g.block_reason or "")
    # 注：不禁「确定」——免责语「非统计确定性」是诚实否定式，子串黑名单须避开它。
    for banned in ("可信", "安全", "保证正确", "已确认", "通过验证", "有效", "保证", "可靠",
                   "trustworthy", "proven", "guaranteed", "validated", "significant"):
        assert banned not in text, f"裁决出现绝对化措辞「{banned}」（门坏）"
    assert g.needs_human_review is True, "闸门未要求人工复核（自动放行下注，门坏）"
    assert "证据" in g.disclaimer
