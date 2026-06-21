"""A4 · agent 业务工具补全 + handoff 候选池 对抗测试（种已知坏门必抓）。

覆盖 4 类对抗（task 硬约束）：
  ① 动钱/晋级工具被注册给 agent 必抓——register 出的全部工具 side_effect 恒 none，
     且工具名集合不含任何 order/promote/place/动钱 类（纵深防御）。
  ② handoff 直推实盘必抓——submit_candidate 的 destination 只止于 paper_desk；
     live/mainnet/realmoney 一律 422（D-PERM 不跳级）。
  ③ permission_gate realmoney 任何模式（含 bypass）恒 confirm——权限轴 ⟂ 治理轴。
  ④ 伪造 side_effect 必抓——tool_status 暴露的 side_effect 是 runtime 真值，
     业务工具全 none；治理逻辑不信调用方伪造。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.agent_runtime import AgentRuntime, permission_gate
from app.agent.business_tools import register_business_tools
from app.agent.tool_schema import TOOL_SCHEMA
from app.main import app


# ── 测试替身：最小 store 接口（接真 store 契约，不打真盘） ───────────────────
class _FakeCard:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeHypStore:
    def create(self, *, strategy_goal_ref, layer, falsifiable=None):
        return _FakeCard(card_id="card_x", strategy_goal_ref=strategy_goal_ref,
                         layer=layer, status="draft")


class _FakeFactor:
    def __init__(self, fid, state):
        self.factor_id = fid
        self.lifecycle_state = state
        self.ic_summary = {"ic": 0.05}


class _FakeFactorRegistry:
    def list(self):
        return [_FakeFactor("good1", "QUALIFIED"), _FakeFactor("good2", "QUALIFIED"),
                _FakeFactor("raw1", "NEW")]


class _FakeMV:
    def __init__(self, version, stage):
        self.version = version
        self.stage = stage
        self.metrics = {"ndcg": 0.23}


class _FakeModelRegistry:
    def list_models(self):
        return ["lgbm_rank_6f"]

    def list_versions(self, model_id):
        return [_FakeMV(1, "dev"), _FakeMV(2, "staging")]


def _make_runtime():
    rt = AgentRuntime(_DummyLLM(), permission_mode="auto")
    register_business_tools(
        rt,
        hypothesis_store=_FakeHypStore(),
        factor_registry=_FakeFactorRegistry(),
        model_registry=_FakeModelRegistry(),
    )
    return rt


class _DummyLLM:
    provider = "test"

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        from app.agent.llm_client import LLMResponse
        return LLMResponse(content="(end)")


# ── ① 动钱/晋级工具永不注册（全部 side_effect=none） ────────────────────────
def test_business_tools_all_side_effect_none():
    rt = _make_runtime()
    for name in rt._tools:  # noqa: SLF001
        assert rt._side_effects.get(name) == "none", \
            f"业务工具 {name} side_effect 非 none——动钱/晋级类绝不注册给 agent（致命）"


def test_no_money_or_promote_tool_registered():
    """种坏门：若 register 进了 order/place/promote/动钱 类工具名 → 必抓。"""
    rt = _make_runtime()
    banned_substr = ("order", "place", "promote", "submit_order", "withdraw",
                     "transfer", "apply_stage", "approve", "lease")
    for name in rt._tools:  # noqa: SLF001
        low = name.lower()
        for bad in banned_substr:
            assert bad not in low, f"危险工具名 {name} 不得注册给 agent（含 {bad!r}）"


def test_model_registry_select_is_readonly():
    """model_registry.select 只读：handler 返回 readonly=True，绝不暴露 promote/翻 stage。"""
    rt = _make_runtime()
    handler = rt._tools["model_registry.select"]  # noqa: SLF001
    out = handler("model_registry.select", {"model_id": "lgbm_rank_6f", "stage": "staging"})
    assert out.get("readonly") is True
    assert out.get("selected_stage") == "staging"
    # dev 版不该被选进策略组装（血统门）。
    out_dev = handler("model_registry.select", {"model_id": "lgbm_rank_6f"})
    assert out_dev.get("selected_stage") in ("staging", "production"), \
        "select 缺省应优先已发布版本，不选 dev"


def test_factor_set_compose_lineage_gate():
    """血统门：factor_set.compose 只选 QUALIFIED+，NEW 因子被拒且弱点一等呈现（R25）。"""
    rt = _make_runtime()
    handler = rt._tools["factor_set.compose"]  # noqa: SLF001
    out = handler("factor_set.compose", {"factor_ids": ["good1", "raw1"]})
    member_ids = {m["factor_id"] for m in out["members"]}
    assert "good1" in member_ids and "raw1" not in member_ids, "NEW 血统因子必须被拒"
    assert any(r["factor_id"] == "raw1" for r in out["rejected"]), "被拒因子必须显式列出（弱点呈现）"


def test_eval_pbo_real_compute():
    """eval.pbo 接真：返回真 PBO 结构（非 queued 占位）。"""
    rt = _make_runtime()
    out = rt._tools["eval.pbo"]("eval.pbo", {"s_blocks": 8})  # noqa: SLF001
    assert "pbo" in out and "n_strategies" in out, "eval.pbo 应返回 CSCV 真结果，非占位"
    assert out.get("queued") is None, "eval.pbo 不应是 queued 占位"


# ── ③ permission_gate realmoney 任何模式恒 confirm ──────────────────────────
@pytest.mark.parametrize("mode", ["ask", "auto", "bypass"])
def test_permission_gate_realmoney_confirm_every_mode(mode):
    assert permission_gate(mode, "realmoney") == "confirm", \
        f"realmoney 在 {mode} 必须 confirm（权限轴绝不跳治理门，致命）"


def test_permission_gate_external_only_bypass_auto_runs():
    assert permission_gate("bypass", "external") == "execute"
    assert permission_gate("auto", "external") == "confirm"
    assert permission_gate("ask", "external") == "confirm"


# ── ④ 伪造 side_effect 必抓：tool_status 真值全 none，治理逻辑不信前端 ────────
def test_tool_status_business_tools_side_effect_truth():
    client = TestClient(app)
    body = client.get("/api/agent/tools").json()
    m = {t["name"]: t for t in body["tool_status"]}
    for name in ("backtest.run", "eval.pbo", "report.generate",
                 "hypothesis.create", "factor_set.compose", "model_registry.select",
                 "signal.define", "portfolio.construct"):
        assert m[name]["side_effect"] == "none", f"{name} side_effect 真值必须 none"
        assert m[name]["status"] == "live", f"{name} 应 live（接真），实得 {m[name]['status']}"


def test_forged_side_effect_does_not_bypass_gate():
    """种坏门：即便 LLM/前端把 realmoney 工具伪装成 none 想绕，治理逻辑只认真值——
    realmoney 真值在 bypass 仍 confirm。"""
    # 真值是 realmoney → 恒 confirm（伪造成 none 无济于事，因为门只看真 side_effect）。
    assert permission_gate("bypass", "realmoney") == "confirm"
    # 反证：真值是 none 才在 bypass 放行（正确放行不算绕门）。
    assert permission_gate("bypass", "none") == "execute"


# ── ② handoff 直推实盘必抓：submit_candidate 只止于模拟盘 ────────────────────
def _login_client():
    client = TestClient(app)
    import uuid as _uuid
    uname = f"a4user_{_uuid.uuid4().hex[:8]}"
    client.post("/api/auth/register", json={"username": uname, "password": "pw123456", "display_name": "a4"})
    r = client.post("/api/auth/login", json={"username": uname, "password": "pw123456"})
    token = r.json().get("token")
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_handoff_stops_at_paper_desk():
    client = _login_client()
    r = client.post("/api/strategy/submit_candidate",
                    json={"run_id": "run_wk_cn_8f2a", "name": "weekly_cn", "destination": "paper_desk"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["destination"] == "paper_desk"
    assert body["stops_at"] == "paper_desk"
    assert body["status"] == "candidate", "handoff 只登记候选，不进场/不动钱"


@pytest.mark.parametrize("dest", ["live", "mainnet", "realmoney", "production_trade"])
def test_handoff_rejects_live_destinations(dest):
    """种坏门：handoff 直推实盘（live/mainnet/realmoney/…）必抓——422 拒绝（D-PERM 不跳级）。"""
    client = _login_client()
    r = client.post("/api/strategy/submit_candidate",
                    json={"run_id": "run_x", "name": "x", "destination": dest})
    assert r.status_code == 422, f"目的地 {dest} 应被拒（直推实盘=跳级），实得 {r.status_code}"
    assert r.json()["detail"]["rejected"] is True


def test_handoff_requires_run_id():
    client = _login_client()
    r = client.post("/api/strategy/submit_candidate", json={"name": "no_run", "destination": "paper_desk"})
    assert r.status_code == 422, "缺 run_id 应被拒（不对幽灵 run 开候选）"


# ── workbench 结构化事件投影（scripted runtime，确定性证 tool_start/tool_end/gate/milestone） ──
def test_workbench_projects_tool_and_milestone_events():
    """auto 模式 + none 工具 → tool_start + tool_end + milestone 事件序列（非裸 chunk）。"""
    from app.agent.agent_runtime import AgentRuntime
    from app.agent.llm_client import LLMResponse
    from app.agent.workbench_stream import project_turn_events

    class _Scripted:
        provider = "test"

        def __init__(self):
            self._q = [
                LLMResponse(content="先建假设卡",
                            tool_calls=[{"id": "c1", "name": "hypothesis.create",
                                         "arguments": json.dumps({})}]),
                LLMResponse(content="完成"),
            ]

        def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
            return self._q.pop(0) if self._q else LLMResponse(content="(end)")

    rt = AgentRuntime(_Scripted(), permission_mode="auto")
    rt.register_tool("hypothesis.create", lambda _n, _a: {"card_id": "card_x"}, side_effect="none")
    turn = rt.run("立题")
    events = list(project_turn_events(turn, side_effects=rt._side_effects, permission_mode="auto"))  # noqa: SLF001
    kinds = [e["event"] for e in events]
    assert "tool_start" in kinds, "auto + none 工具应发 tool_start"
    assert "tool_end" in kinds, "工具结果应发 tool_end"
    assert any(e["event"] == "milestone" and e["data"]["key"] == "立题" for e in events), \
        "hypothesis.create 应点亮『立题』里程碑"


def test_workbench_gate_event_on_realmoney_even_bypass():
    """种坏门：realmoney 工具即便 bypass，投影也发 gate 事件（不发 tool_start 自动执行）。"""
    from app.agent.agent_runtime import AgentRuntime
    from app.agent.llm_client import LLMResponse
    from app.agent.workbench_stream import project_turn_events

    class _Scripted:
        provider = "test"

        def __init__(self):
            self._q = [LLMResponse(content="x",
                                   tool_calls=[{"id": "c1", "name": "order.submit",
                                                "arguments": "{}"}]),
                       LLMResponse(content="(end)")]

        def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
            return self._q.pop(0) if self._q else LLMResponse(content="(end)")

    rt = AgentRuntime(_Scripted(), permission_mode="bypass")
    # 模拟「若有人错误地把 realmoney 工具注册了」——投影仍按真值发 gate（纵深防御第二层）。
    rt.register_tool("order.submit", lambda _n, _a: {"ok": True}, side_effect="realmoney")
    turn = rt.run("下单")
    events = list(project_turn_events(turn, side_effects=rt._side_effects, permission_mode="bypass"))  # noqa: SLF001
    kinds = [e["event"] for e in events]
    assert "gate" in kinds, "realmoney + bypass 投影必须发 gate（治理门不随权限放宽）"
    assert "tool_start" not in kinds, "realmoney 绝不发 tool_start（不自动执行）"


# ── workbench SSE 结构化事件接通（真 turn，非 mock 剧本） ─────────────────────
def test_workbench_stream_emits_structured_events():
    client = _login_client()
    with client.stream("GET", "/api/agent/workbench/stream",
                       params={"q": "组装一个 A股周频多因子策略", "permission_mode": "ask"}) as r:
        assert r.status_code == 200
        raw = "".join(chunk for chunk in r.iter_text())
    # 结构化 SSE（非裸 chunk）：必发 user，且以结构化终态事件收尾（done 成功 / error LLM 不可用）。
    # CI 无真 LLM → 终态可能是 error，但仍是结构化事件（证明投影管线接通，非裸 token 流）。
    assert "event: user" in raw
    assert ("event: done" in raw) or ("event: error" in raw), \
        "workbench 流必须发结构化终态事件（done/error），非裸 chunk"
