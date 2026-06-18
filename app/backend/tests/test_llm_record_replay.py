"""LLM record/replay + 受控翻译层的【对抗式】测试（T-016 / spine 02 §5）。

验收标准（RULES §2）：种一个已知坏，门必抓。覆盖 spine 02 §5 的 A1–A6/B1–B3/C1/D1–D4/E1：
replay 偷跑真 API / fixture 篡改 / cache key 碰撞 / 确定地错 / fingerprint 漂移 / 别名冒充版本 /
逐字节重放 / 三级度量 / 独立重算 fixture_key / put 幂等 / tombstone 不减 N / 崩溃恢复 / 一次性消费。
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import Mock

import pytest

from app.agent.llm_client import LLMClient, LLMMessage, LLMResponse
from app.agent.replay.fixture import (
    FixtureKey,
    LLMFixture,
    ModelPin,
    compute_hmac,
    is_alias_model_id,
    prompt_digest,
    verify_hmac,
)
from app.agent.replay.recording_client import RecordingLLMClient
from app.agent.replay.repro import ReproLevel, pass_caret_k
from app.agent.replay.store import FixtureConflict, FixtureStore, IntegrityError, ReplayMiss
from app.agent.replay.translation import ControlledTranslator
from app.lineage.ids import canonical_json


class _FakeLLM(LLMClient):
    provider = "fake"
    default_model = "claude-sonnet-4-5-20991231"   # 带日期 = 非别名

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="ok", tool_calls=[])


def _msgs(text="hi"):
    return [LLMMessage(role="user", content=text)]


# ── A1 · replay 偷跑真 API 探针（R11 命门）──────────────────────────────────────
def test_replay_miss_never_calls_real_api(tmp_path):
    store = FixtureStore(tmp_path)
    inner = _FakeLLM([LLMResponse(content="should-not-run")])
    client = RecordingLLMClient(inner, store, mode="replay", run_id="r1")
    with pytest.raises(ReplayMiss):
        client.chat(_msgs("never recorded"))
    assert inner.calls == 0, "replay 未命中却回退打真 API → R11 命门破（门坏）"


# ── A2 · fixture 篡改探针（HMAC 完整性门）──────────────────────────────────────
def test_tampered_fixture_raises_integrity_error(tmp_path):
    store = FixtureStore(tmp_path)
    inner = _FakeLLM([LLMResponse(content="x", tool_calls=[{"name": "t", "arguments": '{"leverage": 3}'}])])
    rec = RecordingLLMClient(inner, store, mode="record", run_id="r1")
    resp = rec.chat(_msgs("trade"))
    key = resp.fixture_key

    # 种坏：直改落盘 JSONL 里该 fixture 的 response（leverage 3→30），不更新 integrity。
    fpath = tmp_path / "fixtures.jsonl"
    lines = fpath.read_text().splitlines()
    row = json.loads(lines[-1])
    row["response"]["tool_calls"] = [{"name": "t", "arguments": '{"leverage": 30}'}]
    lines[-1] = json.dumps(row, ensure_ascii=False)
    fpath.write_text("\n".join(lines) + "\n")

    store2 = FixtureStore(tmp_path)
    with pytest.raises(IntegrityError):
        store2.get(key)


# ── A3 · cache key 碰撞探针（内容寻址 key 门，dossier §7.3）──────────────────────
def test_cache_key_no_collision_across_run_index_and_upstream():
    base = dict(node_pos="r1:0", prompt_digest="pd", model_pin_digest="md")
    k_a = FixtureKey(**base, upstream_digest="u1", run_index=0).compute()
    k_b = FixtureKey(**base, upstream_digest="u1", run_index=1).compute()   # best-of-N 第二分支
    k_c = FixtureKey(**base, upstream_digest="u2", run_index=0).compute()   # 上游不同分支
    assert k_a != k_b != k_c and k_a != k_c, "同坐标同 prompt 不同 run_index/upstream 撞 key（门坏）"
    assert all(k.startswith("llmfx-") for k in (k_a, k_b, k_c))


# ── A4 · 翻译「确定地错」探针（语义不变量门，dossier §8.4）──────────────────────
def test_translation_human_confirm_for_over_leverage():
    tr = ControlledTranslator(leverage_cap=3.0)
    # schema 合规但语义越界：杠杆 30 > 上限 3
    calls = [{"name": "order.place", "arguments": json.dumps({"constraints": {"leverage_max": 30}})}]
    res = tr.translate(calls)
    assert res.status == "human_confirm_required", "schema 合规即放行越界杠杆 → 确定地错被放大（门坏）"
    # 合规杠杆放行
    ok = tr.translate([{"name": "order.place", "arguments": json.dumps({"leverage": 2})}])
    assert ok.status == "ok"


# ── A4b · AgentRuntime 翻译门：human_confirm 的 tool_call 不派发 ──────────────────
def test_agent_runtime_does_not_dispatch_human_confirm(tmp_path):
    from app.agent.agent_runtime import AgentRuntime

    placed = {"n": 0}

    def _order(_name, _args):
        placed["n"] += 1
        return {"ok": True}

    llm = _FakeLLM([LLMResponse(content="下单", tool_calls=[
        {"id": "c1", "name": "order.place", "arguments": json.dumps({"leverage_max": 30})}])])
    rt = AgentRuntime(llm, tools={"order.place": _order},
                      translator=ControlledTranslator(leverage_cap=3.0))
    turn = rt.run("用 30 倍杠杆梭哈")
    assert placed["n"] == 0, "越界杠杆 tool_call 被派发 → LLM 直接动手下了 30x（门坏）"
    assert turn.succeeded is False


# ── A5 · fingerprint 静默漂移探针（dossier §5.4/§8.3）──────────────────────────
def test_fingerprint_drift_emits_event(tmp_path):
    events = []
    store = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))

    def _mk(fp, key):
        return LLMFixture(
            fixture_key=key, run_id="r1", repro_level="decision",
            model_pin=ModelPin("anthropic", "claude-x-20240101", fp).to_dict(),
            request={}, response={"content": "a"}, tool_calls=[], translation_status="ok",
        )

    store.put(_mk("fp_v1", "llmfx-aaaa000000000001"))
    store.put(_mk("fp_v2", "llmfx-bbbb000000000002"))   # 同 (provider, model_id) 指纹变了
    drift = [e for e in events if e[0] == "fingerprint_drift"]
    assert drift and drift[0][1]["from"] == "fp_v1" and drift[0][1]["to"] == "fp_v2", \
        "供应商静默换指纹未发 fingerprint_drift 事件 → 「我改了还是供应商换了」不可区分（门坏）"


# ── A6 · 别名冒充版本探针（dossier §5.4）──────────────────────────────────────
def test_alias_model_id_detected_and_event(tmp_path):
    assert is_alias_model_id("claude-sonnet-4-5") is True       # 无日期 = 别名
    assert is_alias_model_id("gpt-4o-latest") is True           # latest = 别名
    assert is_alias_model_id("claude-3-5-sonnet-20241022") is False   # 带日期 = 不可变
    events = []
    store = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))
    store.put(LLMFixture(
        fixture_key="llmfx-cccc000000000003", run_id="r1", repro_level="decision",
        model_pin=ModelPin("anthropic", "claude-sonnet-4-5", None).to_dict(),
        request={}, response={"content": "a"}, tool_calls=[], translation_status="ok",
    ))
    assert any(e[0] == "model_id_is_alias" for e in events), "别名当不可变 id 未告警（门坏）"


# ── B1 · replay 逐字节确定（00 §T9：重放逐字节相同防偷跑）────────────────────────
def test_replay_byte_identical(tmp_path):
    store = FixtureStore(tmp_path)
    inner = _FakeLLM([LLMResponse(content="hello", tool_calls=[{"name": "t", "arguments": "{}"}])])
    rec = RecordingLLMClient(inner, store, mode="record", run_id="r1")
    r_rec = rec.chat(_msgs("q"))

    replay = RecordingLLMClient(_FakeLLM([LLMResponse(content="DIFFERENT")]), store, mode="replay", run_id="r1")
    r1 = replay.chat(_msgs("q"))
    replay2 = RecordingLLMClient(_FakeLLM(), store, mode="replay", run_id="r1")
    r2 = replay2.chat(_msgs("q"))
    proj = lambda r: canonical_json({"content": r.content, "tool_calls": r.tool_calls})
    assert proj(r1) == proj(r2) == proj(r_rec), "replay 两遍不逐字节相同 → 偷跑/漂移（门坏）"


# ── B3 · 三级度量解耦：pass^k(decision) 与 (semantic) 各自独立 ───────────────────
def test_pass_caret_k_levels_decouple():
    # 同 tool 名、不同 arguments → semantic 全同(1.0)，decision 分歧(<1.0)
    resps = [
        {"content": "a", "tool_calls": [{"name": "order", "arguments": {"qty": 1}}]},
        {"content": "b", "tool_calls": [{"name": "order", "arguments": {"qty": 2}}]},
    ]
    assert pass_caret_k(resps, ReproLevel.SEMANTIC) == 1.0
    assert pass_caret_k(resps, ReproLevel.DECISION) < 1.0, "decision 级该分歧却报全同（三级未解耦，门坏）"
    # 完全相同 → 各级全 1.0
    same = [resps[0], dict(resps[0])]
    assert pass_caret_k(same, ReproLevel.DECISION) == 1.0


# ── C1 · 两套独立实现对账 fixture_key（防 key 算法 bug 让命中漂移）────────────────
def test_fixture_key_independent_recompute():
    fk = FixtureKey(node_pos="r1:2", prompt_digest="pd", model_pin_digest="md",
                    upstream_digest="ud", run_index=1)
    ours = fk.compute()
    # 独立朴素参考实现：canonical_json + sha256[:16] + llmfx- 前缀
    payload = {"node_pos": "r1:2", "prompt_digest": "pd", "model_pin_digest": "md",
               "upstream_digest": "ud", "run_index": 1}
    ref = "llmfx-" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]
    assert ours == ref, f"fixture_key 两实现不一致（命中会漂移，门坏）：{ours} vs {ref}"


# ── D1 · put 幂等 / 同 key 异内容拒覆盖（append-only）────────────────────────────
def test_put_idempotent_and_conflict(tmp_path):
    store = FixtureStore(tmp_path)
    f1 = LLMFixture(fixture_key="llmfx-dddd000000000004", run_id="r1", repro_level="decision",
                    model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                    request={}, response={"content": "a"}, tool_calls=[], translation_status="ok")
    store.put(f1)
    # 同 key 同内容 → 幂等不报错、不新增行
    n1 = len((tmp_path / "fixtures.jsonl").read_text().splitlines())
    store.put(LLMFixture(**{**f1.to_dict(), "integrity": ""}))
    assert len((tmp_path / "fixtures.jsonl").read_text().splitlines()) == n1, "幂等 put 却新增行（门坏）"
    # 同 key 异内容 → 拒
    with pytest.raises(FixtureConflict):
        store.put(LLMFixture(**{**f1.to_dict(), "response": {"content": "TAMPERED"}, "integrity": ""}))


# ── D2 · tombstone 不减 distinct 计数（honest-N 不可改小，R8）──────────────────────
def test_tombstone_does_not_reduce_distinct_count(tmp_path):
    store = FixtureStore(tmp_path)
    for i in range(3):
        store.put(LLMFixture(fixture_key=f"llmfx-eeee00000000000{i}", run_id="r1", repro_level="decision",
                             model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                             request={}, response={"content": str(i)}, tool_calls=[], translation_status="ok"))
    assert store.distinct_count() == 3
    store.tombstone("llmfx-eeee000000000000")
    assert store.distinct_count() == 3, "tombstone 减少了 distinct 计数 → 可删 fixture 刷低 N（门坏）"


# ── D2b · tombstone 后 get 仍过完整性门（HMAC 随 tombstoned 重算，不自打篡改告警）──────
def test_tombstone_preserves_integrity(tmp_path):
    store = FixtureStore(tmp_path)
    key = "llmfx-eeee100000000000"
    store.put(LLMFixture(fixture_key=key, run_id="r1", repro_level="decision",
                         model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                         request={}, response={"content": "a"}, tool_calls=[], translation_status="ok"))
    store.tombstone(key)
    # 新进程从 JSONL 重建：最新行带 tombstoned=True 且 HMAC 自洽 → get 不报 IntegrityError。
    fx = FixtureStore(tmp_path).get(key)
    assert fx.tombstoned is True, "tombstone 后最新行未带 tombstoned（状态丢了，门坏）"
    assert verify_hmac(fx, store._key) is True, "tombstone 未重算 HMAC → 合法软删自触发完整性门（门坏）"


# ── D3 · 崩溃中段恢复：前序 step 从 fixture 读、inner 调 0 次 ──────────────────────
def test_crash_recovery_replays_recorded_steps(tmp_path):
    store = FixtureStore(tmp_path)
    # record 跑 2 步
    rec = RecordingLLMClient(_FakeLLM([LLMResponse(content="s0", tool_calls=[{"name": "t", "arguments": "{}"}]),
                                       LLMResponse(content="s1", tool_calls=[])]), store, mode="record", run_id="r1")
    rec.chat(_msgs("step0"))
    rec.chat(_msgs("step1"))
    # 新进程 replay：相同坐标 → 命中，inner 一次都不调
    inner2 = _FakeLLM([LLMResponse(content="LIVE")])
    replay = RecordingLLMClient(inner2, FixtureStore(tmp_path), mode="replay", run_id="r1")
    a = replay.chat(_msgs("step0"))
    b = replay.chat(_msgs("step1"))
    assert a.content == "s0" and b.content == "s1"
    assert inner2.calls == 0, "崩溃恢复 replay 偷跑了真 API（门坏）"


# ── D4 · 一次性消费留痕：第二次消费产 consumed_again 事件（R12）────────────────────
def test_consume_twice_emits_consumed_again(tmp_path):
    events = []
    store = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))
    store.put(LLMFixture(fixture_key="llmfx-ffff000000000005", run_id="r1", repro_level="decision",
                         model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                         request={}, response={"content": "a"}, tool_calls=[], translation_status="ok"))
    store.consume("llmfx-ffff000000000005")
    store.consume("llmfx-ffff000000000005")
    assert any(e[0] == "consumed_again" for e in events), "二次消费未留痕 consumed_again（门坏）"


# ── D4b · consume 后 get 仍过完整性门（HMAC 随 consumed 重算）──────────────────────
def test_consume_preserves_integrity(tmp_path):
    store = FixtureStore(tmp_path)
    key = "llmfx-ffff100000000005"
    store.put(LLMFixture(fixture_key=key, run_id="r1", repro_level="decision",
                         model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                         request={}, response={"content": "a"}, tool_calls=[], translation_status="ok"))
    store.consume(key)
    # 新进程从 JSONL 重建：最新行带 consumed=True 且 HMAC 自洽 → get 不报 IntegrityError。
    fx = FixtureStore(tmp_path).get(key)
    assert fx.consumed is True, "consume 后最新行未带 consumed（一次性留痕丢了，门坏）"
    assert verify_hmac(fx, store._key) is True, "consume 未重算 HMAC → 合法消费自触发完整性门（门坏）"


# ── E1 · 措辞：fixture/翻译裁决不得出现「可信/安全/已合规」──────────────────────
def test_wording_no_absolutes():
    from app.agent.replay.repro import PASS_CARET_K_CAVEAT

    tr = ControlledTranslator(leverage_cap=3.0)
    res = tr.translate([{"name": "order", "arguments": json.dumps({"leverage": 30})}])
    text = res.reason + " " + PASS_CARET_K_CAVEAT
    for banned in ("可信", "安全", "已合规", "保证"):
        assert banned not in text, f"出现绝对化措辞「{banned}」（门坏）"
    assert "高确定性 ≠ 高正确性" in PASS_CARET_K_CAVEAT


# ── 复核 #8/#9/#10 · 翻译门绕过：字符串/列表/变体名杠杆都必抓 ────────────────────
@pytest.mark.parametrize("args", [
    {"leverage": "30"},                       # #8 字符串数值
    {"leverage": [10, 30]},                   # #9 列表
    {"leverageMax": 30},                      # #10 camelCase
    {"max_leverage_limit": 30},               # #10 加词变体
    {"constraints": {"nested": {"lev": 30}}}, # 深层嵌套
], ids=["string", "list", "camelCase", "wordy", "deep"])
def test_translation_leverage_bypass_variants_caught(args):
    tr = ControlledTranslator(leverage_cap=3.0)
    res = tr.translate([{"name": "order.place", "arguments": json.dumps(args)}])
    assert res.status == "human_confirm_required", f"越界杠杆变体 {args} 绕过了翻译门（门坏）"


def test_translation_does_not_false_trigger_on_relevance_or_bool():
    tr = ControlledTranslator(leverage_cap=3.0)
    # 'relevance' 含 'lev' 子串但不是杠杆字段 → 不误伤
    assert tr.translate([{"name": "t", "arguments": json.dumps({"relevance": 99})}]).status == "ok"
    # bool True 不被当 1.0 杠杆
    assert tr.translate([{"name": "t", "arguments": json.dumps({"leverage": True})}]).status == "ok"
    # 合规杠杆（==cap）放行
    assert tr.translate([{"name": "t", "arguments": json.dumps({"leverage": 3})}]).status == "ok"


# ── 复核 #11 · schema_invalid 也不派发（非法 tool_call 不执行）────────────────────
def test_agent_runtime_blocks_schema_invalid(tmp_path):
    from app.agent.agent_runtime import AgentRuntime

    placed = {"n": 0}
    llm = _FakeLLM([LLMResponse(content="x", tool_calls=[
        {"id": "c1", "name": "unknown_tool", "arguments": "{}"}])])
    rt = AgentRuntime(llm, tools={"order.place": lambda *_: placed.__setitem__("n", placed["n"] + 1)},
                      translator=ControlledTranslator(leverage_cap=3.0, known_tools={"order.place"}))
    turn = rt.run("call unknown")
    assert placed["n"] == 0 and turn.succeeded is False, "schema_invalid tool_call 仍被派发（门坏）"


# ── 复核 #4 · tombstone/consume 后 get 仍可读（不因改可变字段误报篡改）──────────────
def test_get_works_after_tombstone_and_consume(tmp_path):
    store = FixtureStore(tmp_path)
    f = LLMFixture(fixture_key="llmfx-2222000000000007", run_id="r1", repro_level="decision",
                   model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                   request={}, response={"content": "real"}, tool_calls=[], translation_status="ok")
    store.put(f)
    store.tombstone("llmfx-2222000000000007")
    store.consume("llmfx-2222000000000007")
    got = store.get("llmfx-2222000000000007")   # 不得抛 IntegrityError
    assert got.response["content"] == "real" and got.tombstoned is True


# ── 复核 #5 · 追加伪造行不能锁死好 fixture（回退到上一有效行 + 事件）────────────────
def test_forged_appended_line_falls_back_to_valid(tmp_path):
    events = []
    store = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))
    f = LLMFixture(fixture_key="llmfx-3333000000000008", run_id="r1", repro_level="decision",
                   model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                   request={}, response={"content": "good"}, tool_calls=[], translation_status="ok")
    store.put(f)
    # 种坏：直接追加一条同 key 的伪造行（错 integrity）。
    forged = {**f.to_dict(), "response": {"content": "EVIL"}, "integrity": "deadbeef"}
    with (tmp_path / "fixtures.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged, ensure_ascii=False) + "\n")
    store2 = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))
    got = store2.get("llmfx-3333000000000008")
    assert got.response["content"] == "good", "伪造追加行锁死/顶替了好 fixture（门坏）"
    assert any(e[0] == "integrity_violation" for e in events), "回退未发 integrity_violation 事件（静默，门坏）"


# ── 复核 #12 · 坏 JSONL 行不静默缩水 distinct（发事件）──────────────────────────────
def test_corrupt_line_emits_event_not_silent(tmp_path):
    store = FixtureStore(tmp_path)
    for i in range(2):
        store.put(LLMFixture(fixture_key=f"llmfx-4444000000000{i:03d}", run_id="r1", repro_level="decision",
                             model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                             request={}, response={"content": str(i)}, tool_calls=[], translation_status="ok"))
    # 种坏：中间插一条坏 JSON 行。
    with (tmp_path / "fixtures.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    events = []
    store2 = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))
    assert any(e[0] == "fixture_line_corrupt" for e in events), "坏行被静默吞（distinct 可悄然缩水，门坏）"


# ── 复核 #13 · tombstone 后【重建】distinct 仍不减（honest-N 不可改小，rebuild 路径）────
def test_tombstone_distinct_preserved_after_rebuild(tmp_path):
    store = FixtureStore(tmp_path)
    keys = []
    for i in range(3):
        k = f"llmfx-5555000000000{i:03d}"
        keys.append(k)
        store.put(LLMFixture(fixture_key=k, run_id="r1", repro_level="decision",
                             model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                             request={}, response={"content": str(i)}, tool_calls=[], translation_status="ok"))
    store.tombstone(keys[0])
    store2 = FixtureStore(tmp_path)   # 从盘重建
    assert store2.distinct_count() == 3, "重建后 tombstone 减少了 distinct → 可删 fixture 刷低 N（门坏）"


# ── 复核 #2 · 不同 run_id 同 prompt 不撞 key（record 模式不静默复用陈旧答案）──────────
def test_different_run_id_no_stale_reuse(tmp_path):
    store = FixtureStore(tmp_path)
    a = RecordingLLMClient(_FakeLLM([LLMResponse(content="PNL +5%")]), store, mode="record", run_id="agent-aaa")
    r_a = a.chat(_msgs("pnl?"))
    inner_b = _FakeLLM([LLMResponse(content="PNL -90% LIQUIDATED")])
    b = RecordingLLMClient(inner_b, store, mode="record", run_id="agent-bbb")   # 不同逻辑 run
    r_b = b.chat(_msgs("pnl?"))
    assert inner_b.calls == 1, "不同 run_id 同 prompt 撞 key → 真 LLM 被跳过、复用陈旧答案（门坏）"
    assert r_b.content == "PNL -90% LIQUIDATED" and r_a.content == "PNL +5%"


# ── D1b · HMAC 自洽：compute → verify 通过；改一字段 → verify 失败 ────────────────
def test_hmac_self_consistency(tmp_path):
    key = b"x" * 32
    fx = LLMFixture(fixture_key="llmfx-1111000000000006", run_id="r1", repro_level="decision",
                    model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                    request={}, response={"content": "a"}, tool_calls=[], translation_status="ok")
    fx.integrity = compute_hmac(fx, key)
    assert verify_hmac(fx, key) is True
    fx.response = {"content": "TAMPERED"}
    assert verify_hmac(fx, key) is False, "改了 response 但 HMAC 仍验过（门坏）"
