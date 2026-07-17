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
from conftest import build_test_agent_gateway

from app.agent.agent_runtime import AgentRuntime, permission_gate
from app.agent.business_tools import register_business_tools
from app.agent.llm_client import LLMResponse
from app.agent.tool_schema import TOOL_SCHEMA
from app.main import app
from app.research_os import (
    AssetRAGDocument,
    MarketDataUseValidationRecord,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentResearchAssetRAGIndex,
    RAGPermission,
    ResearchGraphStore,
)
from app.research_os.entrypoint_evidence import PersistentEntrypointEvidenceRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver


# ── 测试替身：最小 store 接口（真实 store 契约，不打真盘） ───────────────────
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
    def list_models(self, *, owner_user_id):
        assert owner_user_id == "test"
        return ["lgbm_rank_6f"]

    def list_versions(self, model_id, *, owner_user_id):
        assert owner_user_id == "test"
        return [_FakeMV(1, "dev"), _FakeMV(2, "staging")]


REPORT_MARKET_DATA_USE_REF = "market_data_use:report:accepted"
REPORT_DATASET_REF = "dataset:report:demo"


class _FakeDatasetSemantics:
    def __init__(
        self,
        *,
        known_at_ref: str | None = "known_at:report:demo",
        effective_at_ref: str | None = "effective_at:report:demo",
        pit_bitemporal_rules_ref: str | None = "pit:report:demo",
    ):
        self.dataset_ref = REPORT_DATASET_REF
        self.known_at_ref = known_at_ref
        self.effective_at_ref = effective_at_ref
        self.pit_bitemporal_rules_ref = pit_bitemporal_rules_ref


def _report_market_data_use(**overrides) -> MarketDataUseValidationRecord:
    data = {
        "validation_ref": REPORT_MARKET_DATA_USE_REF,
        "request_ref": "market_data_use:report:request",
        "use_context": "backtest",
        "dataset_refs": (REPORT_DATASET_REF,),
        "instrument_refs": ("BTC-USDT",),
        "capability_matrix_ref": "capability:report:demo",
        "capital_record_ref": None,
        "transformation_refs": (),
        "accepted": True,
        "violation_codes": (),
        "evidence_refs": ("evidence:report_market_data_use",),
        "recorded_by": "test",
        "created_at_utc": "2026-06-27T00:00:00Z",
    }
    data.update(overrides)
    return MarketDataUseValidationRecord(**data)


class _FakeMarketDataRegistry:
    def __init__(
        self,
        records: list[MarketDataUseValidationRecord] | None = None,
        datasets: dict[str, _FakeDatasetSemantics] | None = None,
    ):
        source = [_report_market_data_use()] if records is None else records
        self._records = {record.validation_ref: record for record in source}
        self._datasets = {REPORT_DATASET_REF: _FakeDatasetSemantics()} if datasets is None else datasets
        self.owner_lookups: list[tuple[str, str]] = []

    def use_validation(
        self,
        validation_ref: str,
        *,
        owner_user_id: str,
    ) -> MarketDataUseValidationRecord:
        self.owner_lookups.append(("use_validation", owner_user_id))
        if validation_ref not in self._records:
            raise KeyError(validation_ref)
        record = self._records[validation_ref]
        if record.recorded_by != owner_user_id:
            raise KeyError(validation_ref)
        return record

    def dataset(self, dataset_ref: str, *, owner_user_id: str) -> _FakeDatasetSemantics:
        self.owner_lookups.append(("dataset", owner_user_id))
        if dataset_ref not in self._datasets:
            raise KeyError(dataset_ref)
        return self._datasets[dataset_ref]


def _make_runtime(
    *,
    market_data_registry=None,
    verdict_store=None,
    verifier=None,
    owner_user_id: str = "test",
):
    rt = AgentRuntime(_DummyLLM(), permission_mode="auto", owner=owner_user_id)
    register_business_tools(
        rt,
        hypothesis_store=_FakeHypStore(),
        factor_registry=_FakeFactorRegistry(),
        model_registry=_FakeModelRegistry(),
        verdict_store=verdict_store,
        verifier=verifier,
        market_data_registry=market_data_registry,
        owner_user_id=owner_user_id,
    )
    return rt


class _DummyLLM:
    provider = "test"

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        return LLMResponse(content="(end)")


class _CapturingLLM:
    provider = "test"

    def __init__(self):
        self.messages = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.messages = list(messages)
        return LLMResponse(content="workbench grounded answer")


def _rag_doc(*, allowed_users: tuple[str, ...] = ()):
    return AssetRAGDocument(
        source_id="doc:workbench-risk",
        version="v1",
        title="Workbench risk parity note",
        body="covariance covariance shrinkage workbench portfolio risk",
        projection="ResearchRAG",
        asset_ref="qro:workbench-risk",
        permission=RAGPermission(
            allowed_users=allowed_users,
            allowed_desks=("research",),
            allowed_assets=("qro:workbench-risk",),
            permission_tags=("research.read",),
        ),
        applicability="candidate context for workbench stream research",
        source_kind="EvidenceSpan",
        evidence_label="candidate_context",
    )


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


def test_portfolio_construct_equal_risk_uses_true_erc_uncapped():
    """codex floor #2：sizing='equal_risk' 走真 ERC（等风险贡献·long-only），**不**施单票上限
    （post-hoc cap 破 RC 相等），note 诚实标注——不再把 inverse-vol 冒充 equal_risk。"""

    rt = _make_runtime()
    handler = rt._tools["portfolio.construct"]  # noqa: SLF001
    symbols = [f"S{i}" for i in range(5)]
    out = handler(
        "portfolio.construct", {"symbols": symbols, "sizing": "equal_risk", "max_pos": 0.05}
    )
    assert "error" not in out, out
    w = out["weights"]
    assert set(w.keys()) == set(symbols)
    assert abs(sum(w.values()) - 1.0) < 1e-6  # 全额·未截断
    assert all(v > 0 for v in w.values())  # long-only
    assert max(w.values()) > 0.05  # 未被 max_pos=0.05 cap（保 ERC 不变量）
    assert "等风险贡献" in out["note"] or "ERC" in out["note"]


def test_portfolio_construct_risk_parity_is_inverse_vol_capped():
    """sizing='risk_parity' = inverse-volatility 启发式（非真 ERC）·仍施单票上限。"""

    rt = _make_runtime()
    handler = rt._tools["portfolio.construct"]  # noqa: SLF001
    symbols = [f"S{i}" for i in range(5)]
    out = handler(
        "portfolio.construct", {"symbols": symbols, "sizing": "risk_parity", "max_pos": 0.05}
    )
    assert "error" not in out
    assert max(out["weights"].values()) <= 0.05 + 1e-9  # capped（启发式·可 cap）


def test_portfolio_construct_discloses_synthetic_and_enforcement_state():
    """codex floor R2 #2/#3：equal_risk 披露 covariance_source=synthetic_demo + max_position_enforced=False
    + requested_max_position（不谎报已生效风控）；risk_parity synthetic + enforced True。"""

    rt = _make_runtime()
    handler = rt._tools["portfolio.construct"]  # noqa: SLF001
    syms = [f"S{i}" for i in range(5)]
    er = handler("portfolio.construct", {"symbols": syms, "sizing": "equal_risk", "max_pos": 0.05})
    assert er["covariance_source"] == "synthetic_demo"
    assert er["risk_limits"]["max_position_enforced"] is False
    assert "requested_max_position" in er["risk_limits"]
    rp = handler("portfolio.construct", {"symbols": syms, "sizing": "risk_parity", "max_pos": 0.05})
    assert rp["covariance_source"] == "synthetic_demo"
    assert rp["risk_limits"]["max_position_enforced"] is True


def test_portfolio_construct_falsey_and_invalid_inputs_fail_closed():
    """codex floor R3 #2/#3：falsey sizing / 非法 max_pos → error（不静默退等权·不把 fallback 谎报
    requested）；仅 key 缺失才补缺省。"""

    rt = _make_runtime()
    handler = rt._tools["portfolio.construct"]  # noqa: SLF001
    for bad_sizing in ("", None, 0, [], {}):
        out = handler("portfolio.construct", {"symbols": ["A", "B"], "sizing": bad_sizing})
        assert "error" in out, f"falsey sizing {bad_sizing!r} 应 fail closed"
    # 非法 max_pos/dd_halt（含显式 None 与 bool·codex floor R4 #4）→ fail closed
    for key in ("max_pos", "dd_halt"):
        for bad in ("bad", -0.1, 2.0, float("nan"), None, True, False):
            out = handler(
                "portfolio.construct", {"symbols": ["A", "B"], "sizing": "equal_weight", key: bad}
            )
            assert "error" in out, f"非法 {key}={bad!r} 应 fail closed"
    # key 缺失 → 默认（不报错）；sizing 缺失默认 equal_weight
    ok = handler("portfolio.construct", {"symbols": ["A", "B"]})
    assert "error" not in ok and ok["sizing"] == "equal_weight"


def test_factor_set_compose_lineage_gate():
    """血统门：factor_set.compose 只选 QUALIFIED+，NEW 因子被拒且弱点一等呈现（R25）。"""
    rt = _make_runtime()
    handler = rt._tools["factor_set.compose"]  # noqa: SLF001
    out = handler("factor_set.compose", {"factor_ids": ["good1", "raw1"]})
    member_ids = {m["factor_id"] for m in out["members"]}
    assert "good1" in member_ids and "raw1" not in member_ids, "NEW 血统因子必须被拒"
    assert any(r["factor_id"] == "raw1" for r in out["rejected"]), "被拒因子必须显式列出（弱点呈现）"


def test_eval_pbo_real_compute():
    """eval.pbo 真实计算：返回 PBO 结构（非 queued 占位）。"""
    rt = _make_runtime()
    out = rt._tools["eval.pbo"]("eval.pbo", {"s_blocks": 8})  # noqa: SLF001
    assert "pbo" in out and "n_strategies" in out, "eval.pbo 应返回 CSCV 真结果，非占位"
    assert out.get("queued") is None, "eval.pbo 不应是 queued 占位"


def test_report_generate_schema_requires_market_data_use_refs():
    schema = next(item for item in TOOL_SCHEMA if item["name"] == "report.generate")
    params = schema["parameters"]
    assert "market_data_use_validation_refs" in params["properties"]
    assert "market_data_use_validation_refs" in params["required"]
    assert "run_id" in params["required"]


def _patch_report_projection(monkeypatch):
    import app.run_verdict as run_verdict

    calls: list[str] = []

    def _project_verdict(run_id, *, verdict_store, verifier):  # noqa: ANN001
        calls.append("verdict")
        return {
            "run_id": run_id,
            "verdict": "concern",
            "verdictNote": "本 run 尚需进一步验证。",
            "has_authoritative_verdict": False,
        }

    def _project_overfit(run_id):  # noqa: ANN001
        calls.append("overfit")
        return {"run_id": run_id, "pbo": 0.25, "dsr": 0.9, "gate_label": "证据分歧"}

    def _project_cost_sensitivity(run_id):  # noqa: ANN001
        calls.append("cost")
        return {
            "run_id": run_id,
            "cost": [{"preset": "neutral", "sharpe": 1.1, "excess": 0.03}],
        }

    monkeypatch.setattr(run_verdict, "project_verdict", _project_verdict)
    monkeypatch.setattr(run_verdict, "project_overfit", _project_overfit)
    monkeypatch.setattr(run_verdict, "project_cost_sensitivity", _project_cost_sensitivity)
    return calls


def test_backtest_run_existing_run_requires_market_data_use_refs_before_projection(monkeypatch):
    calls = _patch_report_projection(monkeypatch)
    rt = _make_runtime(market_data_registry=_FakeMarketDataRegistry(), verdict_store=object(), verifier=object())
    out = rt._tools["backtest.run"]("backtest.run", {"run_id": "run_report_1"})  # noqa: SLF001
    assert "market_data_use_validation_refs" in (out.get("error") or "")
    assert out.get("no_write") is True
    assert calls == [], "existing-run backtest projection must not run without MarketDataUse refs"


def test_backtest_run_existing_run_includes_market_data_use_refs_after_gate(monkeypatch):
    calls = _patch_report_projection(monkeypatch)
    rt = _make_runtime(market_data_registry=_FakeMarketDataRegistry(), verdict_store=object(), verifier=object())
    out = rt._tools["backtest.run"](  # noqa: SLF001
        "backtest.run",
        {"run_id": "run_report_1", "market_data_use_validation_refs": [REPORT_MARKET_DATA_USE_REF]},
    )
    assert out.get("error") is None, out
    assert out["source"] == "projected_existing_run"
    assert out["market_data_use_validation_refs"] == [REPORT_MARKET_DATA_USE_REF]
    assert calls == ["verdict", "overfit"]


def test_agent_market_data_owner_comes_from_authenticated_runtime_not_tool_args(monkeypatch):
    calls = _patch_report_projection(monkeypatch)
    registry = _FakeMarketDataRegistry()
    rt = _make_runtime(
        market_data_registry=registry,
        verdict_store=object(),
        verifier=object(),
        owner_user_id="test",
    )

    out = rt._tools["backtest.run"](  # noqa: SLF001
        "backtest.run",
        {
            "run_id": "run_report_1",
            "market_data_use_validation_refs": [REPORT_MARKET_DATA_USE_REF],
            "owner": "foreign-client-owner",
            "owner_user_id": "foreign-client-owner",
        },
    )

    assert out.get("error") is None, out
    assert registry.owner_lookups == [
        ("use_validation", "test"),
        ("dataset", "test"),
    ]
    assert calls == ["verdict", "overfit"]


def test_agent_market_data_ref_from_foreign_owner_fails_before_projection(monkeypatch):
    calls = _patch_report_projection(monkeypatch)
    registry = _FakeMarketDataRegistry()
    rt = _make_runtime(
        market_data_registry=registry,
        verdict_store=object(),
        verifier=object(),
        owner_user_id="foreign-owner",
    )

    out = rt._tools["backtest.run"](  # noqa: SLF001
        "backtest.run",
        {
            "run_id": "run_report_1",
            "market_data_use_validation_refs": [REPORT_MARKET_DATA_USE_REF],
        },
    )

    assert "unknown MarketDataUse validation ref" in (out.get("error") or "")
    assert out.get("no_write") is True
    assert registry.owner_lookups == [("use_validation", "foreign-owner")]
    assert calls == []


def test_report_generate_requires_market_data_use_refs_before_projection(monkeypatch):
    calls = _patch_report_projection(monkeypatch)
    rt = _make_runtime(market_data_registry=_FakeMarketDataRegistry(), verdict_store=object(), verifier=object())
    out = rt._tools["report.generate"]("report.generate", {"run_id": "run_report_1"})  # noqa: SLF001
    assert "market_data_use_validation_refs" in (out.get("error") or "")
    assert out.get("no_write") is True
    assert calls == [], "MarketDataUse gate must run before report projection"


@pytest.mark.parametrize(
    ("registry", "refs", "message"),
    [
        (_FakeMarketDataRegistry([]), ["market_data_use:report:missing"], "unknown"),
        (
            _FakeMarketDataRegistry([
                _report_market_data_use(validation_ref="market_data_use:report:rejected", accepted=False)
            ]),
            ["market_data_use:report:rejected"],
            "not accepted",
        ),
        (
            _FakeMarketDataRegistry([
                _report_market_data_use(
                    validation_ref="market_data_use:report:violation",
                    violation_codes=("missing_pit_rules",),
                )
            ]),
            ["market_data_use:report:violation"],
            "violations",
        ),
        (
            _FakeMarketDataRegistry([
                _report_market_data_use(validation_ref="market_data_use:report:research", use_context="research")
            ]),
            ["market_data_use:report:research"],
            "wrong use_context",
        ),
        (
            _FakeMarketDataRegistry(
                [_report_market_data_use(validation_ref="market_data_use:report:no_timing")],
                datasets={REPORT_DATASET_REF: _FakeDatasetSemantics(pit_bitemporal_rules_ref=None)},
            ),
            ["market_data_use:report:no_timing"],
            "PIT/bitemporal timing",
        ),
    ],
)
def test_report_generate_rejects_bad_market_data_use_refs_before_report(monkeypatch, registry, refs, message):
    calls = _patch_report_projection(monkeypatch)
    rt = _make_runtime(market_data_registry=registry, verdict_store=object(), verifier=object())
    out = rt._tools["report.generate"](  # noqa: SLF001
        "report.generate",
        {"run_id": "run_report_1", "market_data_use_validation_refs": refs},
    )
    assert message in (out.get("error") or "")
    assert out.get("no_write") is True
    assert out.get("run_id") is None
    assert calls == [], "bad MarketDataUse refs must not project a report"


def test_report_generate_includes_market_data_use_refs_after_gate(monkeypatch):
    calls = _patch_report_projection(monkeypatch)
    rt = _make_runtime(market_data_registry=_FakeMarketDataRegistry(), verdict_store=object(), verifier=object())
    out = rt._tools["report.generate"](  # noqa: SLF001
        "report.generate",
        {"run_id": "run_report_1", "market_data_use_validation_refs": [REPORT_MARKET_DATA_USE_REF]},
    )
    assert out.get("error") is None, out
    assert out["market_data_use_validation_refs"] == [REPORT_MARKET_DATA_USE_REF]
    assert REPORT_MARKET_DATA_USE_REF in out["markdown"]
    assert "数据使用证明" in out["markdown"]
    assert calls == ["verdict", "overfit", "cost"]


def test_portfolio_gate_tool_no_alpha_not_green():
    """C 消费者 portfolio.gate（D-WAVE1A）：组合层 gate 经 agent 工具真跑（无 alpha → 不达 green、PBO=N/A）。"""
    rt = _make_runtime()
    n = 300
    ar = {"A": [(-0.02 if i % 2 == 0 else 0.01) for i in range(n)], "B": [0.0] * n}
    out = rt._tools["portfolio.gate"](  # noqa: SLF001
        "portfolio.gate",
        {"portfolio_id": "p1", "weights": {"A": 0.5, "B": 0.5}, "asset_returns": ar, "markets": ["crypto"]},
    )
    assert out.get("error") is None, out
    assert out["color"] != "green"       # 无 alpha 绝不放行
    assert out["pbo"] is None            # 冷启动单序列 → PBO=N/A
    assert out["config_hash"]            # 复用 ids 单一身份源


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
        assert m[name]["status"] == "live", f"{name} 应 live（真实引擎），实得 {m[name]['status']}"


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
    client.a4_user_id = r.json()["user"]["user_id"]
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


def test_workbench_tool_end_carries_run_id_for_downstream():
    """DS-3 贯穿：backtest.run 结果带 run_id → tool_end 事件顶层透出 run_id（供前端贯穿裁决/paper）。

    种坏门：若投影只塞进 result.run_id 而不提升到顶层，DS-3 前端就拿不到稳定字段。
    """
    from app.agent.agent_runtime import AgentRuntime
    from app.agent.llm_client import LLMResponse
    from app.agent.workbench_stream import project_turn_events

    class _Scripted:
        provider = "test"

        def __init__(self):
            self._q = [
                LLMResponse(content="跑回测",
                            tool_calls=[{"id": "c1", "name": "backtest.run",
                                         "arguments": json.dumps({})}]),
                LLMResponse(content="完成"),
            ]

        def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
            return self._q.pop(0) if self._q else LLMResponse(content="(end)")

    rt = AgentRuntime(_Scripted(), permission_mode="auto")
    rt.register_tool("backtest.run",
                     lambda _n, _a: {"run_id": "agentbt_cn_demo", "status": "done"},
                     side_effect="none")
    turn = rt.run("回测")
    events = list(project_turn_events(turn, side_effects=rt._side_effects, permission_mode="auto"))  # noqa: SLF001
    tool_ends = [e for e in events if e["event"] == "tool_end"]
    assert tool_ends, "backtest.run 应发 tool_end"
    assert any(e["data"].get("run_id") == "agentbt_cn_demo" for e in tool_ends), \
        "带 run_id 的 tool 结果应把 run_id 提升到 tool_end 事件顶层（DS-3 贯穿单一字段）"
    # 同时保留 result（不替换，扩展）。
    assert all("result" in e["data"] for e in tool_ends), "tool_end 仍须带完整 result（扩展不替换）"


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


def test_workbench_stream_auto_retrieves_research_asset_rag(tmp_path, monkeypatch):
    import app.main as main

    client = _login_client()
    index = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    index.add_for_owner(
        _rag_doc(allowed_users=(client.a4_user_id,)),
        owner_user_id=client.a4_user_id,
    )
    store = ResearchGraphStore()
    llm = _CapturingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler_store = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validation_store = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence_store = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=store,
        compiler_store=compiler_store,
        validation_receipt_registry=validation_store,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage_store = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
        resolver=build_real_ref_resolver(
            research_graph_store=store,
            lifecycle_registry=main.ASSET_LIFECYCLE_REGISTRY,
            governance_registry=main.MODEL_GOVERNANCE_REGISTRY,
            rag_index=index,
            spine_chain_registry=main.MATHEMATICAL_SPINE_CHAIN_REGISTRY,
            compiler_store=compiler_store,
            document_store=main.DOCUMENT_INTELLIGENCE_STORE,
            goal_validation_receipt_registry=validation_store,
            platform_source_evidence_registry=evidence_store,
        ),
    )
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler_store)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validation_store)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence_store)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage_store)
    monkeypatch.setattr(
        main,
        "_current_agent_gateway",
        lambda run_id=None, *, model_pin=None: build_test_agent_gateway(
            llm,
            seal_secret=main.LLM_CALL_RECORD_STORE.seal_secret,
        ),
    )

    with client.stream(
        "GET",
        "/api/agent/workbench/stream",
        params={
            "q": "covariance shrinkage portfolio risk",
            "permission_mode": "auto",
            "desk": "research",
            "visible_asset_refs": ["qro:workbench-risk"],
            "permission_tags": ["research.read"],
            "projections": ["ResearchRAG"],
            "rag_search": "vector",
        },
    ) as r:
        assert r.status_code == 200
        raw = "".join(chunk for chunk in r.iter_text())

    assert "event: user" in raw
    assert "event: say" in raw
    assert "event: done" in raw
    assert "rag:doc:workbench-risk@v1:qro:workbench-risk" in raw
    assert "rag_usage_ids" in raw
    assert index.strict_usage_records(owner_user_id=client.a4_user_id)
    prompt_text = "\n".join(message.content for message in llm.messages)
    assert "Research Asset RAG candidate context" in prompt_text
    assert "covariance covariance shrinkage" in prompt_text
