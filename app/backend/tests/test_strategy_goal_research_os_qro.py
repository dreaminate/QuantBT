"""DS-2 · strategy_goal.create 真实后端对抗测试（D-DELIVERY-SLICE · blocker #2）。

种已知坏门必抓：
  1. 结构化 args（asset_class）→ 校验落库产真 goal_id；A股强制 leverage=1.0（治理不变量不破）。
  2. 自然语言 description（无 asset_class）→ slot-filler 补全产 goal_id（无 LLM 也走通）。
  3. §3：缺 asset_class 且无自然语言 → needs_slots，绝不产假 goal_id。
  4. 内容寻址幂等：同目标 → 同 goal_id。
  5. goal_id 真可被 DS-1 backtest 消费（chat→backtest 链路闭合）。
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

import app.run_detail_core as rdc
from app.agent.business_tools import _synth_and_promote
from app.agent.sample_data import SAMPLE_REL, sample_path
from app.lineage import Ledger
from app.research_os import (
    MarketDataUseValidationRecord,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    ResearchGraphStore,
)
from app.research_os.entrypoint_evidence import PersistentEntrypointEvidenceRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver
from app.strategy_goal_store import StrategyGoalStore

MARKET_DATA_USE_REFS = ["market_data_use:ds2_chain:accepted"]
MARKET_DATASET_REF = "dataset:btc_daily"
TEST_OWNER_USER_ID = "test:strategy-goal-qro"


class _DatasetSemantics:
    dataset_ref = MARKET_DATASET_REF
    known_at_ref = "known_at:btc_daily"
    effective_at_ref = "effective_at:btc_daily"
    pit_bitemporal_rules_ref = "pit:btc_daily"


class _MarketDataUseRegistry:
    def __init__(self) -> None:
        self._record = MarketDataUseValidationRecord(
            validation_ref=MARKET_DATA_USE_REFS[0],
            request_ref="market_data_use:ds2_chain:request",
            use_context="backtest",
            dataset_refs=(MARKET_DATASET_REF,),
            instrument_refs=("BTC-USDT",),
            capability_matrix_ref="capability:crypto_perp_daily",
            capital_record_ref=None,
            transformation_refs=(),
            accepted=True,
            violation_codes=(),
            evidence_refs=("evidence:ds2_chain_market_data_use",),
            recorded_by=TEST_OWNER_USER_ID,
            created_at_utc="2026-06-27T00:00:00Z",
        )

    def use_validation(
        self, validation_ref: str, *, owner_user_id: str,
    ) -> MarketDataUseValidationRecord:
        if owner_user_id != TEST_OWNER_USER_ID:
            raise PermissionError(owner_user_id)
        if validation_ref != self._record.validation_ref:
            raise KeyError(validation_ref)
        return self._record

    def dataset(self, dataset_ref: str, *, owner_user_id: str) -> _DatasetSemantics:
        if owner_user_id != TEST_OWNER_USER_ID:
            raise PermissionError(owner_user_id)
        if dataset_ref != _DatasetSemantics.dataset_ref:
            raise KeyError(dataset_ref)
        return _DatasetSemantics()


def test_structured_args_persist_real_goal_id_and_a_share_leverage(tmp_path):
    store = StrategyGoalStore(tmp_path / "goals")
    out = store.create_from_args({"asset_class": "equity_cn", "objective": "info_ratio", "horizon": "weekly"})
    assert out.get("error") is None, out
    gid = out["strategy_goal_id"]
    assert gid.startswith("goal_"), out
    # 真落库 + 可读回
    loaded = store.get(gid)
    assert loaded.asset_class == "equity_cn"
    # 治理不变量：A股 leverage 强制 1.0（StrategyGoal 校验器把守）
    assert loaded.constraints.leverage_max == 1.0


def test_natural_language_slot_filled_to_goal_id(tmp_path):
    store = StrategyGoalStore(tmp_path / "goals")
    out = store.create_from_args({"description": "加密 永续 资金费率 日频 卡玛"})
    assert out.get("error") is None, out
    assert out["asset_class"] == "crypto_perp"  # "永续" → crypto_perp
    assert out["strategy_goal_id"].startswith("goal_")


def test_missing_slots_no_fake_goal_id():
    """§3：缺 asset_class 且无自然语言 → needs_slots，绝不产假 goal_id。"""
    import tempfile
    from pathlib import Path

    store = StrategyGoalStore(Path(tempfile.mkdtemp()))
    out = store.create_from_args({"objective": "max_sharpe"})  # 啥市场都没说
    assert out.get("strategy_goal_id") is None, out
    assert out.get("needs_slots"), "缺槽位必须显式提示补全，不伪造目标"


def test_goal_id_is_content_addressed_idempotent():
    import tempfile
    from pathlib import Path

    store = StrategyGoalStore(Path(tempfile.mkdtemp()))
    a = store.create_from_args({"asset_class": "crypto_perp", "objective": "max_calmar", "horizon": "daily"})
    b = store.create_from_args({"asset_class": "crypto_perp", "objective": "max_calmar", "horizon": "daily"})
    assert a["strategy_goal_id"] == b["strategy_goal_id"], "同目标必须同 goal_id（内容寻址幂等）"


def test_strategy_goal_success_records_quant_intent_qro_without_prompt_plaintext(tmp_path):
    store = StrategyGoalStore(tmp_path / "goals")
    graph = ResearchGraphStore()
    secret = "SHOULD_NOT_ENTER_STRATEGY_GOAL_QRO"

    out = store.create_from_args(
        {"description": f"加密 永续 资金费率 日频 卡玛 {secret}"},
        research_graph=graph,
        entry_source="agent_shell",
        actor_source="agent",
        actor="agent_runtime",
        owner="strategy_goal_store",
    )

    assert out.get("error") is None, out
    assert out["qro_id"]
    assert out["research_graph_command_id"]
    qro = graph.qro(out["qro_id"])
    assert qro.qro_type == "QuantIntent" or getattr(qro.qro_type, "value", None) == "QuantIntent"
    assert qro.output_contract["strategy_goal_id"] == out["strategy_goal_id"]
    assert qro.output_contract["asset_class"] == "crypto_perp"
    qro_contract_text = str(qro.input_contract) + str(qro.output_contract)
    assert secret not in qro_contract_text
    assert "加密" not in qro_contract_text


def test_strategy_goal_api_create_records_quant_intent_qro_without_prompt_plaintext(tmp_path, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "STRATEGY_GOAL_STORE", StrategyGoalStore(tmp_path / "goals"))
    graph = ResearchGraphStore()
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage_store = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage_store.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage_store)
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    secret = "SHOULD_NOT_ENTER_STRATEGY_GOAL_API_AUDIT"
    client = TestClient(main.app)

    response = client.post("/api/strategy_goals", json={"description": f"加密 永续 日频 卡玛 {secret}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy_goal_id"].startswith("goal_")
    assert body["qro_id"]
    assert body["research_graph_command_id"]
    assert body["compiler_ir_ref"]
    assert body["compiler_pass_ref"]
    assert body["entrypoint_coverage_ref"]
    assert main.STRATEGY_GOAL_STORE.get(body["strategy_goal_id"]).asset_class == "crypto_perp"
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before + 1

    audit = client.get("/api/research-os/graph/commands", params={"limit": 5})
    assert audit.status_code == 200, audit.text
    audit_body = audit.json()
    qros = [
        command["payload"]["qro"]
        for command in audit_body["commands"]
        if command["payload"].get("qro", {}).get("qro_id") == body["qro_id"]
    ]
    assert qros
    qro = qros[0]
    assert qro["qro_type"] == "QuantIntent"
    assert qro["input_contract"]["entry_source"] == "api"
    assert qro["output_contract"]["strategy_goal_id"] == body["strategy_goal_id"]
    assert qro["output_contract"]["asset_class"] == "crypto_perp"
    assert secret not in str(audit_body)
    assert "加密" not in str(qro["input_contract"]) + str(qro["output_contract"])

    ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.input_qro_refs == (body["qro_id"],)
    assert compiler_pass.entry_source == "api"
    assert coverage.entry_source == "api"
    assert coverage.entrypoint_ref == "api:strategy_goals"
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert secret not in str(ir) + str(compiler_pass) + str(coverage)


def test_strategy_goal_api_missing_slots_rejects_without_business_qro(tmp_path, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "STRATEGY_GOAL_STORE", StrategyGoalStore(tmp_path / "goals"))
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    response = TestClient(main.app).post("/api/strategy_goals", json={"objective": "max_sharpe"})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["needs_slots"]
    assert "strategy_goal_id" not in detail
    assert main.STRATEGY_GOAL_STORE.list_ids() == []
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before


def _has_btc() -> bool:
    try:
        return sample_path("crypto_perp").exists()
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _has_btc(), reason="BTC 样本未捆绑")
def test_goal_id_flows_into_backtest_chat_to_backtest_chain(tmp_path, monkeypatch):
    """链路闭合：strategy_goal.create 产 goal_id → DS-1 backtest 真消费产真 run。"""
    # 建真 goal
    store = StrategyGoalStore(tmp_path / "goals")
    g = store.create_from_args({"asset_class": "crypto_perp", "objective": "max_calmar", "horizon": "daily"})
    gid = g["strategy_goal_id"]
    # 隔离样本 + run root（复刻 DS-1 iso）
    dst = tmp_path / SAMPLE_REL["crypto_perp"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_path("crypto_perp"), dst)
    rr = tmp_path / "artifacts" / "experiments"
    rr.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rdc, "RUN_ROOT", rr)
    # 把 goal_id 当 strategy_goal_ref 喂 backtest
    out = _synth_and_promote(
        args={
            "market": "crypto_perp",
            "strategy_goal_ref": gid,
            "lookback": 20,
            "market_data_use_validation_refs": MARKET_DATA_USE_REFS,
        },
        ledger=Ledger(tmp_path / "lineage"), returns_store=None, data_root=tmp_path,
        verdict_store=None, verifier=None, llm_client=None,
        market_data_registry=_MarketDataUseRegistry(),
        owner_user_id=TEST_OWNER_USER_ID,
    )
    assert out.get("error") is None, out
    assert out["run_id"], "chat 产的 goal_id 必须能驱动 DS-1 backtest 产真 run"
