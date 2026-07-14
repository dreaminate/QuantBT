"""S2 策略台后端接线 · 对抗测试。

覆盖（含「种已知坏门必抓」）：
- validate：种坏图（exec 绕 Final Risk Gate / compat=bad / 必填未连）必报；好图必过。
- fork / 版本身份：必须锚 lineage/ids.py（content_hash）单一源——种「不锚」必抓。
- live_snapshot：A股 live 永拒；任何下单参数/路径不得出现（无绕 OrderGuard 新路径）。
- HTTP 层（TestClient + auth override）：4 端点 owner 隔离 + 坏图 422/200 行为。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import require_user_dependency
from app.ide.service import IDEService
from app.ide.strategy_graph import (
    APPROVED_PORTFOLIO_DT,
    compat,
    strategy_content_hash,
    validate_graph,
)
from app.lineage import content_hash
from app.lineage.ids import canonical_json
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


# ──────────────────────────────────────────────────────────────────────
# fixtures：图字面量（对齐前端 graphLogic.ts 端口口径）
# ──────────────────────────────────────────────────────────────────────


def _gate_graph():
    """合法链路：PortfolioRisk → FinalRiskGate(approvedPortfolio) → Execution(exec)。"""
    nodes = [
        {"id": "prisk", "title": "PortfolioRisk", "ins": [],
         "outs": [{"id": "rp", "name": "risked", "dt": "riskedPortfolio"}]},
        {"id": "gate", "title": "Final Risk Gate", "locked": True,
         "ins": [{"id": "i", "name": "risked", "dt": "riskedPortfolio", "req": True}],
         "outs": [{"id": "ap", "name": "approved", "dt": APPROVED_PORTFOLIO_DT}]},
        {"id": "exec", "title": "Execution",
         "ins": [{"id": "ei", "name": "approved", "dt": APPROVED_PORTFOLIO_DT, "role": "exec", "req": True}],
         "outs": []},
    ]
    edges = [
        {"id": "er", "from": {"node": "prisk", "port": "rp"}, "to": {"node": "gate", "port": "i"}},
        {"id": "eg", "from": {"node": "gate", "port": "ap"}, "to": {"node": "exec", "port": "ei"}},
    ]
    return nodes, edges


# ──────────────────────────────────────────────────────────────────────
# validate · 种坏图必抓
# ──────────────────────────────────────────────────────────────────────


def test_validate_good_graph_passes():
    nodes, edges = _gate_graph()
    r = validate_graph(nodes, edges)
    assert r["ok"] is True
    assert r["errors"] == []


def test_validate_seeds_exec_bypassing_gate_caught():
    """种已知坏门：exec 入边直连 PortfolioRisk（绕 Final Risk Gate）→ 必报 B6 error。"""
    nodes, edges = _gate_graph()
    bad = [{"id": "eb", "from": {"node": "prisk", "port": "rp"}, "to": {"node": "exec", "port": "ei"}}]
    r = validate_graph(nodes, bad)
    assert r["ok"] is False
    assert any("B6" in e["text"] for e in r["errors"]), r["errors"]


def test_validate_seeds_incompatible_edge_caught():
    """种坏门：类型不兼容连线 compat=bad → error。"""
    nodes = [
        {"id": "a", "title": "A", "ins": [], "outs": [{"id": "o", "name": "o", "dt": "panel"}]},
        {"id": "b", "title": "B", "ins": [{"id": "i", "name": "i", "dt": "modelScore", "req": True}], "outs": []},
    ]
    edges = [{"id": "e", "from": {"node": "a", "port": "o"}, "to": {"node": "b", "port": "i"}}]
    r = validate_graph(nodes, edges)
    assert r["ok"] is False
    assert any("不兼容" in e["text"] for e in r["errors"])


def test_validate_required_unconnected_is_warning_not_error():
    nodes = [
        {"id": "b", "title": "B",
         "ins": [{"id": "i", "name": "必填入", "dt": "panel", "req": True}], "outs": []},
    ]
    r = validate_graph(nodes, [])
    assert r["ok"] is True  # warn 不阻断
    assert len(r["warnings"]) == 1
    assert "未连接" in r["warnings"][0]["text"]


def test_validate_accepts_dict_nodes_shape():
    nodes, edges = _gate_graph()
    as_dict = {n["id"]: n for n in nodes}
    assert validate_graph(as_dict, edges)["ok"] is True


def test_compat_exec_role_rejects_non_approved_source():
    out_other = {"id": "rp", "dt": "riskedPortfolio"}
    in_exec = {"id": "ei", "dt": APPROVED_PORTFOLIO_DT, "role": "exec"}
    assert compat(out_other, in_exec)["s"] == "bad"
    out_gate = {"id": "ap", "dt": APPROVED_PORTFOLIO_DT}
    assert compat(out_gate, in_exec)["s"] == "ok"


# ──────────────────────────────────────────────────────────────────────
# 身份单一源 · fork / 版本必锚 lineage/ids.py
# ──────────────────────────────────────────────────────────────────────


def test_strategy_content_hash_anchored_to_lineage_ids():
    """种已知坏门：身份不锚 lineage.content_hash（自造 hash）→ 此断言必抓。"""
    h = strategy_content_hash(name="x", code="print(1)", asset_class="crypto_perp")
    assert h == content_hash({"name": "x", "code": "print(1)", "asset_class": "crypto_perp"})
    assert len(h) == 16  # 全库 16 位不变量


def test_strategy_content_hash_changes_with_code():
    a = strategy_content_hash(name="x", code="print(1)", asset_class="crypto_perp")
    b = strategy_content_hash(name="x", code="print(2)", asset_class="crypto_perp")
    assert a != b


@pytest.fixture
def svc(tmp_path: Path) -> IDEService:
    return IDEService(tmp_path / "ide.db", run_root=tmp_path / "runs")


def test_save_records_version_history(svc):
    svc.save_strategy("alice", "s1", "print(1)")
    svc.save_strategy("alice", "s1", "print(2)")
    versions = svc.list_versions("alice", "s1")
    assert len(versions) == 2
    assert all(v.origin == "save" for v in versions)
    # 内容指纹随 code 变（身份锚 content_hash）。
    assert versions[0].content_hash != versions[1].content_hash


def test_fork_anchors_parent_via_lineage(svc):
    parent = svc.save_strategy("alice", "base", "print('p')", asset_class="crypto_perp")
    forked = svc.fork_strategy("alice", "base")
    assert forked.strategy_id != parent.strategy_id
    assert forked.code == parent.code
    fv = svc.list_versions("alice", forked.name)
    assert fv[0].origin == "fork"
    # 父锚 = 父策略当前内容指纹（经 lineage.content_hash，非自造）。
    expected_parent = strategy_content_hash(
        name=parent.name, code=parent.code, asset_class=parent.asset_class,
    )
    assert fv[0].parent_content_hash == expected_parent
    assert fv[0].parent_strategy_id == parent.strategy_id


def test_fork_owner_namespace_isolated(svc):
    svc.save_strategy("alice", "base", "print(1)")
    from app.ide.service import IDEError
    with pytest.raises(IDEError):
        svc.fork_strategy("bob", "base")  # bob 看不到 alice 的 base


def test_versions_owner_isolated(svc):
    svc.save_strategy("alice", "base", "print(1)")
    from app.ide.service import IDEError
    with pytest.raises(IDEError):
        svc.list_versions("bob", "base")


# ──────────────────────────────────────────────────────────────────────
# live_snapshot · A股永拒 + 无下单路径（不绕 OrderGuard）
# ──────────────────────────────────────────────────────────────────────


def test_live_snapshot_source_has_no_order_call():
    """live_snapshot 端点源码不得有任何下单【调用面】（物理上无法从此端点下单）。

    检的是真实调用/构造（`.place_order(` / `OrderGuard(` 等），而非文档里提到这些词——
    诚实记录禁令的注释/docstring 不该把测试逼绿/逼红。种坏门：若有人日后在此端点
    引入 venue.place_order(...) 等真实下单调用，下面必抓。
    """
    from app import main

    src = inspect.getsource(main.ide_strategy_live_snapshot)
    # 去掉以 # 开头的整行注释（docstring 里的散文不构成调用面，下面只查调用模式）。
    code_lines = [ln for ln in src.splitlines() if not ln.strip().startswith("#")]
    code = "\n".join(code_lines)
    for forbidden in (
        ".place_order(", "place_order(", "OrderGuard(", "OrderGuard.wrap",
        "KillSwitch(", ".submit_order(", ".place(", "paper_venue", "inner_venue",
    ):
        assert forbidden not in code, f"live_snapshot 引入了下单调用面: {forbidden}"


# ──────────────────────────────────────────────────────────────────────
# HTTP 层 · 4 端点（TestClient + auth override）
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def http(tmp_path, monkeypatch):
    from app import main

    isolated = IDEService(tmp_path / "ide_http.db", run_root=tmp_path / "runs_http")
    monkeypatch.setattr(main, "IDE_SERVICE", isolated)
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
    coverage = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=main.ASSET_LIFECYCLE_REGISTRY,
            governance_registry=main.MODEL_GOVERNANCE_REGISTRY,
            rag_index=main.RESEARCH_ASSET_RAG_INDEX,
            spine_chain_registry=main.MATHEMATICAL_SPINE_CHAIN_REGISTRY,
            compiler_store=compiler,
            document_store=main.DOCUMENT_INTELLIGENCE_STORE,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([_market_data_use_validation()]))
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester", username="tester",
    )
    try:
        yield TestClient(main.app), isolated
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


class _MarketDataUseRegistry:
    def __init__(self, records: list[MarketDataUseValidationRecord] | None = None) -> None:
        self._records = {record.validation_ref: record for record in records or []}

    def use_validation(
        self,
        validation_ref: str,
        *,
        owner_user_id: str,
    ) -> MarketDataUseValidationRecord:
        if validation_ref not in self._records:
            raise KeyError(validation_ref)
        record = self._records[validation_ref]
        if record.recorded_by != owner_user_id:
            raise KeyError(validation_ref)
        return record


def _market_data_use_validation(**overrides) -> MarketDataUseValidationRecord:
    data = {
        "validation_ref": "market_data_use:ide_save:accepted",
        "request_ref": "market_data_request:ide_save",
        "use_context": "backtest",
        "dataset_refs": ("dataset:ide_strategy_panel:v1",),
        "instrument_refs": ("instrument:BTCUSDT",),
        "capability_matrix_ref": "capability:crypto_perp:backtest",
        "capital_record_ref": None,
        "transformation_refs": ("transform:ide_features:v1",),
        "accepted": True,
        "violation_codes": (),
        "evidence_refs": ("evidence:ide_market_data_use_gate",),
        "recorded_by": "tester",
        "created_at_utc": "2026-06-27T00:00:00+00:00",
    }
    data.update(overrides)
    return MarketDataUseValidationRecord(**data)


def _promotable_ide_code(strategy_name: str = "promo_gate") -> str:
    rows = [
        {"t": f"2026-01-{i + 1:02d}", "equity": round(1.0 + i * 0.002, 6), "net_return": 0.002 if i else 0.0}
        for i in range(30)
    ]
    return (
        "quantbt.emit_result({"
        f"'equity_curve': {rows!r}, "
        f"'metadata': {{'strategy_name': '{strategy_name}', 'market': 'crypto_perp', 'frequency': '1d'}}"
        "})"
    )


def test_http_save_strategy_records_strategybook_qro_without_source_leakage(http):
    from app import main

    client, _ = http
    secret = "SHOULD_NOT_ENTER_IDE_STRATEGY_QRO"
    res = client.post(
        "/api/ide/strategies",
        json={
            "name": "qro_save",
            "asset_class": "crypto_perp",
            "description": f"draft description {secret}",
            "code": f"quantbt.emit_result({{'secret': '{secret}'}})",
            "market_data_use_validation_refs": ["market_data_use:ide_save:accepted"],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["qro_id"].startswith("qro_")
    assert body["research_graph_command_id"].startswith("rgcmd_")
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    assert body["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    audit = client.get("/api/research-os/graph/commands", params={"limit": 10})
    assert audit.status_code == 200, audit.text
    audit_body = audit.json()
    qros = [
        command["payload"]["qro"]
        for command in audit_body["commands"]
        if command["payload"].get("qro", {}).get("qro_id") == body["qro_id"]
    ]
    assert qros
    qro = qros[0]
    assert qro["qro_type"] == "StrategyBook"
    assert qro["input_contract"]["entry_source"] == "ide"
    assert qro["input_contract"]["strategy_id"] == body["strategy_id"]
    assert qro["input_contract"]["strategy_name"] == "qro_save"
    assert qro["input_contract"]["asset_class"] == "crypto_perp"
    assert qro["input_contract"]["code_hash"]
    assert qro["input_contract"]["description_hash"]
    assert qro["input_contract"]["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert qro["output_contract"]["content_hash"]
    assert qro["output_contract"]["updated_at_utc"] == body["updated_at_utc"]
    assert qro["output_contract"]["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert "code" not in qro["input_contract_keys"]
    assert "description" not in qro["input_contract_keys"]
    assert secret not in str(audit_body)
    assert "quantbt.emit_result" not in str(audit_body)
    assert "draft description" not in str(audit_body)
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == 1
    ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.input_qro_refs == (body["qro_id"],)
    assert compiler_pass.entry_source == "ide"
    assert coverage.entry_source == "ide"
    assert coverage.entrypoint_ref == "ide:strategy.save"
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert secret not in str(ir) + str(compiler_pass) + str(coverage)
    assert "quantbt.emit_result" not in str(ir) + str(compiler_pass) + str(coverage)


def test_http_save_strategy_validation_failure_does_not_fabricate_qro(http):
    from app import main

    client, svc = http
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    res = client.post(
        "/api/ide/strategies",
        json={
            "name": "bad_asset",
            "asset_class": "forex",
            "code": "print(1)",
            "market_data_use_validation_refs": ["market_data_use:ide_save:accepted"],
        },
    )

    assert res.status_code == 400
    assert "qro_id" not in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_strategies("tester") == []


def test_http_save_strategy_requires_market_data_use_validation_before_persisting(http):
    from app import main

    client, svc = http
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    res = client.post(
        "/api/ide/strategies",
        json={"name": "missing_market_data_use", "asset_class": "crypto_perp", "code": "print(1)"},
    )

    assert res.status_code == 422
    assert "market_data_use_validation_refs" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_strategies("tester") == []


def test_http_save_strategy_rejects_unknown_market_data_use_validation_before_persisting(http):
    from app import main

    client, svc = http
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    res = client.post(
        "/api/ide/strategies",
        json={
            "name": "unknown_market_data_use",
            "asset_class": "crypto_perp",
            "code": "print(1)",
            "market_data_use_validation_refs": ["market_data_use:ide_save:missing"],
        },
    )

    assert res.status_code == 422
    assert "unknown market data use validation" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_strategies("tester") == []


def test_http_save_strategy_rejects_unaccepted_market_data_use_validation_before_persisting(http, monkeypatch):
    from app import main

    client, svc = http
    rejected = _market_data_use_validation(
        validation_ref="market_data_use:ide_save:rejected",
        accepted=False,
        violation_codes=("market_data_use_backtest_matrix_unavailable",),
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([rejected]))
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    res = client.post(
        "/api/ide/strategies",
        json={
            "name": "rejected_market_data_use",
            "asset_class": "crypto_perp",
            "code": "print(1)",
            "market_data_use_validation_refs": [rejected.validation_ref],
        },
    )

    assert res.status_code == 422
    assert "not accepted" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_strategies("tester") == []


def test_http_save_strategy_rejects_violation_market_data_use_validation_before_persisting(http, monkeypatch):
    from app import main

    client, svc = http
    violation = _market_data_use_validation(
        validation_ref="market_data_use:ide_save:violation",
        accepted=True,
        violation_codes=("market_data_use_dataset_missing_pit",),
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([violation]))
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    res = client.post(
        "/api/ide/strategies",
        json={
            "name": "violation_market_data_use",
            "asset_class": "crypto_perp",
            "code": "print(1)",
            "market_data_use_validation_refs": [violation.validation_ref],
        },
    )

    assert res.status_code == 422
    assert "unresolved violations" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_strategies("tester") == []


def test_http_run_strategy_records_backtestrun_qro_without_log_or_result_leakage(http):
    from app import main

    client, svc = http
    secret = "SHOULD_NOT_ENTER_IDE_RUN_QRO"
    svc.save_strategy(
        "tester",
        "run_qro",
        f"print('{secret}'); quantbt.emit_result({{'alpha_secret_key': 1}})",
        asset_class="crypto_perp",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )

    res = client.post("/api/ide/strategies/run_qro/run", json={})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["result_keys"] == ["alpha_secret_key"]
    assert body["qro_id"].startswith("qro_")
    assert body["research_graph_command_id"].startswith("rgcmd_")
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    assert body["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    frozen_manifest = json.loads(
        (svc.run_root / body["run_id"] / "run.json").read_text(encoding="utf-8")
    )
    assert frozen_manifest["source"]["owner_user_id"] == "tester"

    audit = client.get("/api/research-os/graph/commands", params={"limit": 10})
    assert audit.status_code == 200, audit.text
    audit_body = audit.json()
    qros = [
        command["payload"]["qro"]
        for command in audit_body["commands"]
        if command["payload"].get("qro", {}).get("qro_id") == body["qro_id"]
    ]
    assert qros
    qro = qros[0]
    assert qro["qro_type"] == "BacktestRun"
    assert qro["input_contract"]["entry_source"] == "ide"
    assert qro["input_contract"]["strategy_name"] == "run_qro"
    assert qro["input_contract"]["asset_class"] == "crypto_perp"
    assert qro["input_contract"]["code_hash"]
    assert qro["input_contract"]["strategy_content_hash"]
    assert qro["input_contract"]["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert qro["output_contract"]["run_id"] == body["run_id"]
    assert qro["output_contract"]["status"] == "ok"
    assert qro["output_contract"]["result_key_count"] == 1
    assert qro["output_contract"]["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert qro["status_axes"]["evidence"] == "exploratory"
    assert "code" not in qro["input_contract_keys"]
    assert "stdout" not in qro["output_contract_keys"]
    assert "stderr" not in qro["output_contract_keys"]
    assert "result_keys" not in qro["output_contract_keys"]
    assert secret not in str(audit_body)
    assert "alpha_secret_key" not in str(audit_body)
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == 1
    ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.entry_source == "ide"
    assert coverage.entrypoint_ref == "ide:strategy.run"
    assert secret not in str(ir) + str(compiler_pass) + str(coverage)
    assert "alpha_secret_key" not in str(ir) + str(compiler_pass) + str(coverage)


def test_http_run_strategy_failed_code_records_failed_qro_without_stderr_leakage(http):
    from app import main

    client, svc = http
    secret = "SHOULD_NOT_ENTER_IDE_RUN_FAILURE_QRO"
    svc.save_strategy(
        "tester",
        "run_fail_qro",
        f"raise RuntimeError('{secret}')",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )

    res = client.post("/api/ide/strategies/run_fail_qro/run", json={})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "failed"
    assert secret in body["stderr_excerpt"]
    assert body["qro_id"]
    assert body["compiler_ir_ref"]
    assert body["compiler_pass_ref"]
    assert body["entrypoint_coverage_ref"]
    qro = main.RESEARCH_GRAPH_STORE.qro(body["qro_id"])
    assert qro.qro_type == "BacktestRun" or getattr(qro.qro_type, "value", None) == "BacktestRun"
    assert qro.input_contract["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert qro.output_contract["status"] == "failed"
    assert qro.output_contract["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert qro.status_axes()["evidence"] == "insufficient"

    audit = client.get("/api/research-os/graph/commands", params={"limit": 10})
    assert audit.status_code == 200, audit.text
    assert secret not in str(audit.json())
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert coverage.entrypoint_ref == "ide:strategy.run"


def test_http_run_unknown_strategy_does_not_fabricate_qro(http):
    from app import main

    client, _ = http
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    res = client.post("/api/ide/strategies/nope/run", json={})

    assert res.status_code == 404
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before


def test_http_run_strategy_requires_market_data_use_validation_before_sandbox(http):
    from app import main

    client, svc = http
    svc.save_strategy("tester", "run_missing_market_data_use", "quantbt.emit_result({'x': 1})")
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post("/api/ide/strategies/run_missing_market_data_use/run", json={})

    assert res.status_code == 422
    assert "market_data_use_validation_refs" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_runs("tester") == []


def test_http_run_strategy_rejects_unknown_market_data_use_validation_before_sandbox(http):
    from app import main

    client, svc = http
    svc.save_strategy(
        "tester",
        "run_unknown_market_data_use",
        "quantbt.emit_result({'x': 1})",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(
        "/api/ide/strategies/run_unknown_market_data_use/run",
        json={"market_data_use_validation_refs": ["market_data_use:ide_save:missing"]},
    )

    assert res.status_code == 422
    assert "unknown market data use validation" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_runs("tester") == []


def test_http_run_strategy_rejects_unaccepted_market_data_use_validation_before_sandbox(http, monkeypatch):
    from app import main

    client, svc = http
    rejected = _market_data_use_validation(
        validation_ref="market_data_use:ide_run:rejected",
        accepted=False,
        violation_codes=("market_data_use_backtest_matrix_unavailable",),
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([rejected]))
    svc.save_strategy("tester", "run_rejected_market_data_use", "quantbt.emit_result({'x': 1})")
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(
        "/api/ide/strategies/run_rejected_market_data_use/run",
        json={"market_data_use_validation_refs": [rejected.validation_ref]},
    )

    assert res.status_code == 422
    assert "not accepted" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_runs("tester") == []


def test_http_run_strategy_rejects_violation_market_data_use_validation_before_sandbox(http, monkeypatch):
    from app import main

    client, svc = http
    violation = _market_data_use_validation(
        validation_ref="market_data_use:ide_run:violation",
        accepted=True,
        violation_codes=("market_data_use_dataset_missing_pit",),
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([violation]))
    svc.save_strategy("tester", "run_violation_market_data_use", "quantbt.emit_result({'x': 1})")
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(
        "/api/ide/strategies/run_violation_market_data_use/run",
        json={"market_data_use_validation_refs": [violation.validation_ref]},
    )

    assert res.status_code == 422
    assert "unresolved violations" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert svc.list_runs("tester") == []


def test_http_formal_promote_requires_rdp_before_artifact_or_qro_mutation(
    http,
    tmp_path,
    monkeypatch,
):
    from app import main

    real_promote = main.promote_ide_run
    captured_kwargs = {}

    def _promote_tmp(**kwargs):
        captured_kwargs.update(kwargs)
        kwargs["run_root"] = tmp_path / "promoted_runs"
        return real_promote(**kwargs)

    monkeypatch.setattr(main, "promote_ide_run", _promote_tmp)
    client, svc = http
    secret = "SHOULD_NOT_ENTER_IDE_PROMOTE_QRO"
    rows = [
        {"t": f"2026-01-{i + 1:02d}", "equity": round(1.0 + i * 0.002, 6), "net_return": 0.002 if i else 0.0}
        for i in range(30)
    ]
    code = (
        f"print('{secret}')\n"
        "quantbt.emit_result({"
        f"'equity_curve': {rows!r}, "
        f"'trades': [{{'timestamp': '2026-01-02', 'symbol': '{secret}', 'side': 'BUY', 'quantity': 1, 'price': 1}}], "
        "'metadata': {'strategy_name': 'promo_qro', 'market': 'crypto_perp', 'frequency': '1d', 'benchmark': 'BTC-USDT'}"
        "})"
    )
    svc.save_strategy(
        "tester",
        "promo_qro",
        code,
        asset_class="crypto_perp",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    ide_run = svc.run_strategy("tester", "promo_qro")
    svc.save_strategy(
        "tester",
        "promo_qro",
        "quantbt.emit_result({'equity_curve': [{'t': 'draft-drift', 'equity': 9}]})",
        asset_class="crypto_perp",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(f"/api/ide/runs/{ide_run.run_id}/promote", json={"record_name": f"record {secret}"})

    assert res.status_code == 400, res.text
    assert "formal IDE promotion requires rdp_package_id" in res.text
    assert captured_kwargs["require_reproduction_receipt"] is True
    assert captured_kwargs["strategy_code"] == code
    assert captured_kwargs["strategy_name"] == "promo_qro"
    assert captured_kwargs["execution_blocks"] == [
        {
            "block_id": f"ide_sandbox:{ide_run.run_id}",
            "mode": "mock",
            "result_grade": "exploratory",
            "mock_marked": True,
            "note": (
                "Server-derived IDE sandbox execution; non-live and not "
                "paper, testnet, mainnet, or production execution."
            ),
        }
    ]
    assert (
        captured_kwargs["reproduction_receipt_store"]
        is main.RDP_REPRODUCTION_RECEIPT_STORE
    )
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert not (tmp_path / "promoted_runs").exists()
    assert secret not in str(main.RESEARCH_GRAPH_STORE.commands())


def test_http_promote_qro_binds_frozen_source_after_mutable_draft_drift(
    http, monkeypatch
):
    from app import main

    client, svc = http
    frozen_code = _promotable_ide_code("frozen_qro")
    svc.save_strategy(
        "tester",
        "frozen_qro",
        frozen_code,
        asset_class="crypto_perp",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    ide_run = svc.run_strategy("tester", "frozen_qro")
    frozen_manifest = json.loads(
        (svc.run_root / ide_run.run_id / "run.json").read_text(encoding="utf-8")
    )
    svc.save_strategy(
        "tester",
        "frozen_qro",
        _promotable_ide_code("mutable_draft"),
        asset_class="equity_cn",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    captured_kwargs = {}

    def _promote_stub(**kwargs):
        captured_kwargs.update(kwargs)
        pending = SimpleNamespace(
            run_id="promoted_frozen_qro",
            run_dir=Path("/unused/promoted_frozen_qro"),
            metrics={},
            gate_verdict=None,
            promotion_receipt_ref="ide_promotion_receipt:frozen",
            requested_label="exploratory",
        )
        kwargs["promotion_precommit_hook"](pending)
        return pending

    monkeypatch.setattr(main, "promote_ide_run", _promote_stub)
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(f"/api/ide/runs/{ide_run.run_id}/promote", json={})

    assert res.status_code == 200, res.text
    assert captured_kwargs["strategy_code"] == frozen_code
    command = main.RESEARCH_GRAPH_STORE.commands()[before]
    qro = command.payload["qro"]
    source = frozen_manifest["source"]
    assert qro.input_contract["asset_class"] == source["strategy_asset_class"]
    assert qro.input_contract["code_hash"] == content_hash(frozen_code)
    assert (
        qro.input_contract["strategy_content_hash"]
        == source["strategy_content_hash"]
    )
    assert qro.input_contract["asset_class"] != "equity_cn"
    assert qro.input_contract["requested_label"] == "exploratory"
    assert qro.output_contract["requested_label"] == "exploratory"
    assert qro.output_contract["status"] == "hidden_candidate_pending_receipt"
    assert (
        qro.output_contract["promotion_receipt_commit_state"]
        == "precommit_reference"
    )
    assert qro.evidence_status.value == "exploratory"
    assert qro.governance_status.value == "unreviewed"
    assert qro.mock_profile == "ide_sandbox"
    audit_qro = main._qro_audit_summary(qro)
    assert audit_qro["input_contract"]["requested_label"] == "exploratory"
    assert audit_qro["output_contract"]["requested_label"] == "exploratory"
    assert (
        audit_qro["output_contract"]["promotion_receipt_commit_state"]
        == "precommit_reference"
    )


@pytest.mark.parametrize(
    "tamper",
    (
        lambda manifest: manifest.__setitem__("strategy_id", "strategy_foreign"),
        lambda manifest: manifest["source"].__setitem__(
            "owner_username", "foreign-user"
        ),
    ),
    ids=("strategy_id", "nested_owner_username"),
)
def test_http_promote_rejects_canonical_but_identity_tampered_source_snapshot(
    http, monkeypatch, tamper
):
    from app import main

    client, svc = http
    svc.save_strategy(
        "tester",
        "tampered_source_identity",
        _promotable_ide_code("tampered_source_identity"),
        asset_class="crypto_perp",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    ide_run = svc.run_strategy("tester", "tampered_source_identity")
    manifest_path = svc.run_root / ide_run.run_id / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tamper(manifest)
    manifest_path.write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))

    monkeypatch.setattr(
        main,
        "promote_ide_run",
        lambda **_kwargs: pytest.fail("tampered source reached promotion"),
    )
    res = client.post(f"/api/ide/runs/{ide_run.run_id}/promote", json={})

    assert res.status_code == 400
    assert "IDE source run manifest binding is invalid" in res.text


def test_http_promote_qro_failure_quarantines_published_run(
    http, tmp_path, monkeypatch
):
    from app import main

    client, svc = http
    svc.save_strategy(
        "tester",
        "qro_failure_quarantine",
        _promotable_ide_code("qro_failure_quarantine"),
        asset_class="crypto_perp",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    ide_run = svc.run_strategy("tester", "qro_failure_quarantine")
    promoted_root = tmp_path / "promoted_qro_failure"
    final_dir = promoted_root / "formal_run"

    def _published_stub(**kwargs):
        final_dir.mkdir(parents=True)
        (final_dir / "run.json").write_text("{}", encoding="utf-8")
        pending = SimpleNamespace(
            run_id="formal_run",
            run_dir=final_dir,
            metrics={},
            gate_verdict=None,
            promotion_receipt_ref="ide_promotion_receipt:orphan",
            requested_label="exploratory",
        )
        try:
            kwargs["promotion_precommit_hook"](pending)
        except RuntimeError as exc:
            from app.ide.promote import quarantine_promoted_run

            quarantine_promoted_run(
                pending,
                phase="receipt_failed",
                expected_run_root=promoted_root,
            )
            kwargs["promotion_precommit_compensator"](pending, {})
            raise main.PromoteCommitError(
                "durable promotion verification failed: RuntimeError"
            ) from exc
        return pending

    monkeypatch.setattr(main, "promote_ide_run", _published_stub)
    monkeypatch.setattr(
        main,
        "_compile_entrypoint_qro",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("injected QRO failure")),
    )

    res = client.post(f"/api/ide/runs/{ide_run.run_id}/promote", json={})

    assert res.status_code == 500
    assert "durable promotion verification failed: RuntimeError" in res.text
    assert not final_dir.exists()
    quarantined = list((promoted_root / ".staging").glob("formal_run.receipt_failed.*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "run.json").is_file()
    commands = main.RESEARCH_GRAPH_STORE.commands()
    assert [command.command_type for command in commands] == [
        "upsert_qro",
        "tombstone_qro",
    ]
    failed_qro = commands[0].payload["qro"]
    [tombstone] = main.RESEARCH_GRAPH_STORE.qro_tombstones()
    assert tombstone.qro_id == failed_qro.qro_id
    with pytest.raises(KeyError):
        main.RESEARCH_GRAPH_STORE.qro(failed_qro.qro_id)
    assert (
        main.RESEARCH_GRAPH_STORE.qro(
            failed_qro.qro_id,
            include_tombstoned=True,
        )
        == failed_qro
    )


def test_lifecycle_promotion_ref_requires_current_receipt(monkeypatch):
    from app import main

    receipt = SimpleNamespace(
        source_ide_run_id="source-run",
        promoted_run_id="promoted-run",
        rdp_package_id="rdp-package",
        requested_label="exploratory",
    )
    calls = []

    class Registry:
        def receipt(self, ref, *, owner_user_id):
            assert ref == "ide_promotion_receipt:stale"
            assert owner_user_id == "owner-a"
            return receipt

        def validate_current(self, ref, **kwargs):
            calls.append((ref, kwargs))
            return SimpleNamespace(accepted=False)

    monkeypatch.setattr(main, "PROMOTION_RECEIPT_REGISTRY", Registry())

    assert (
        main._lifecycle_transition_ref_validator(
            "owner-a", "promotion", "ide_promotion_receipt:stale"
        )
        is False
    )
    assert calls == [
        (
            "ide_promotion_receipt:stale",
            {
                "owner_user_id": "owner-a",
                "source_ide_run_id": "source-run",
                "promoted_run_id": "promoted-run",
                "rdp_package_id": "rdp-package",
                "requested_label": "exploratory",
            },
        )
    ]


def test_http_promote_requires_market_data_use_validation_before_promoting(http, tmp_path, monkeypatch):
    from app import main

    real_promote = main.promote_ide_run

    def _promote_tmp(**kwargs):
        kwargs["run_root"] = tmp_path / "promoted_runs"
        return real_promote(**kwargs)

    monkeypatch.setattr(main, "promote_ide_run", _promote_tmp)
    client, svc = http
    svc.save_strategy("tester", "promote_missing_market_data_use", _promotable_ide_code("promote_missing"))
    ide_run = svc.run_strategy("tester", "promote_missing_market_data_use")
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(f"/api/ide/runs/{ide_run.run_id}/promote", json={})

    assert res.status_code == 422
    assert "market_data_use_validation_refs" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert not (tmp_path / "promoted_runs").exists()


def test_http_promote_rejects_unknown_market_data_use_validation_before_promoting(http, tmp_path, monkeypatch):
    from app import main

    real_promote = main.promote_ide_run

    def _promote_tmp(**kwargs):
        kwargs["run_root"] = tmp_path / "promoted_runs"
        return real_promote(**kwargs)

    monkeypatch.setattr(main, "promote_ide_run", _promote_tmp)
    client, svc = http
    svc.save_strategy(
        "tester",
        "promote_unknown_market_data_use",
        _promotable_ide_code("promote_unknown"),
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    ide_run = svc.run_strategy("tester", "promote_unknown_market_data_use")
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(
        f"/api/ide/runs/{ide_run.run_id}/promote",
        json={"market_data_use_validation_refs": ["market_data_use:ide_save:missing"]},
    )

    assert res.status_code == 422
    assert "unknown market data use validation" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert not (tmp_path / "promoted_runs").exists()


def test_http_promote_rejects_unaccepted_market_data_use_validation_before_promoting(http, tmp_path, monkeypatch):
    from app import main

    real_promote = main.promote_ide_run

    def _promote_tmp(**kwargs):
        kwargs["run_root"] = tmp_path / "promoted_runs"
        return real_promote(**kwargs)

    monkeypatch.setattr(main, "promote_ide_run", _promote_tmp)
    client, svc = http
    rejected = _market_data_use_validation(
        validation_ref="market_data_use:ide_promote:rejected",
        accepted=False,
        violation_codes=("market_data_use_backtest_matrix_unavailable",),
    )
    svc.save_strategy(
        "tester",
        "promote_rejected_market_data_use",
        _promotable_ide_code("promote_rejected"),
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    ide_run = svc.run_strategy("tester", "promote_rejected_market_data_use")
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([rejected]))
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(
        f"/api/ide/runs/{ide_run.run_id}/promote",
        json={"market_data_use_validation_refs": [rejected.validation_ref]},
    )

    assert res.status_code == 422
    assert "not accepted" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert not (tmp_path / "promoted_runs").exists()


def test_http_promote_rejects_violation_market_data_use_validation_before_promoting(http, tmp_path, monkeypatch):
    from app import main

    real_promote = main.promote_ide_run

    def _promote_tmp(**kwargs):
        kwargs["run_root"] = tmp_path / "promoted_runs"
        return real_promote(**kwargs)

    monkeypatch.setattr(main, "promote_ide_run", _promote_tmp)
    client, svc = http
    violation = _market_data_use_validation(
        validation_ref="market_data_use:ide_promote:violation",
        accepted=True,
        violation_codes=("market_data_use_dataset_missing_pit",),
    )
    svc.save_strategy(
        "tester",
        "promote_violation_market_data_use",
        _promotable_ide_code("promote_violation"),
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    ide_run = svc.run_strategy("tester", "promote_violation_market_data_use")
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([violation]))
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(
        f"/api/ide/runs/{ide_run.run_id}/promote",
        json={"market_data_use_validation_refs": [violation.validation_ref]},
    )

    assert res.status_code == 422
    assert "unresolved violations" in res.text
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert not (tmp_path / "promoted_runs").exists()


def test_http_promote_invalid_result_does_not_fabricate_qro(http, tmp_path, monkeypatch):
    from app import main

    real_promote = main.promote_ide_run

    def _promote_tmp(**kwargs):
        kwargs["run_root"] = tmp_path / "promoted_runs"
        return real_promote(**kwargs)

    monkeypatch.setattr(main, "promote_ide_run", _promote_tmp)
    client, svc = http
    svc.save_strategy(
        "tester",
        "bad_promote",
        "quantbt.emit_result({'not_equity_curve': 1})",
        market_data_use_validation_refs=["market_data_use:ide_save:accepted"],
    )
    ide_run = svc.run_strategy("tester", "bad_promote")
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(f"/api/ide/runs/{ide_run.run_id}/promote", json={})

    assert res.status_code == 400
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before
    assert not (tmp_path / "promoted_runs").exists()


def test_http_ide_ai_complete_records_llm_call_qro_without_prompt_context_or_output_leakage(http, monkeypatch):
    from app import main

    class _FakeLLM:
        provider = "fake-ide-llm"

        def chat(self, _messages):  # noqa: ANN001
            return SimpleNamespace(content="print('SHOULD_NOT_ENTER_IDE_AI_QRO')")

    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None, **_kwargs: _FakeLLM())
    client, _ = http
    prompt_secret = "PROMPT_SHOULD_NOT_ENTER_IDE_AI_QRO"
    context_secret = "CONTEXT_SHOULD_NOT_ENTER_IDE_AI_QRO"

    res = client.post(
        "/api/ide/ai_complete",
        json={
            "mode": "write",
            "market": "crypto_perp",
            "prompt": f"write code {prompt_secret}",
            "context_code": f"# old code {context_secret}",
            "market_data_use_validation_refs": ["market_data_use:ide_save:accepted"],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] == "print('SHOULD_NOT_ENTER_IDE_AI_QRO')"
    assert body["provider"] == "fake-ide-llm"
    assert body["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert body["qro_id"].startswith("qro_")
    assert body["research_graph_command_id"].startswith("rgcmd_")
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")

    audit = client.get("/api/research-os/graph/commands", params={"limit": 10})
    assert audit.status_code == 200, audit.text
    audit_body = audit.json()
    qros = [
        command["payload"]["qro"]
        for command in audit_body["commands"]
        if command["payload"].get("qro", {}).get("qro_id") == body["qro_id"]
    ]
    assert qros
    qro = qros[0]
    assert qro["qro_type"] == "LLMCallRecord"
    assert qro["input_contract"]["entry_source"] == "ide"
    assert qro["input_contract"]["mode"] == "write"
    assert qro["input_contract"]["provider"] == "fake-ide-llm"
    assert qro["input_contract"]["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert qro["input_contract"]["prompt_hash"]
    assert qro["input_contract"]["context_hash"]
    assert qro["output_contract"]["output_hash"]
    assert qro["output_contract"]["output_char_count"] == len(body["code"])
    assert qro["output_contract"]["market_data_use_validation_refs"] == ["market_data_use:ide_save:accepted"]
    assert qro["status_axes"]["evidence"] == "untested"
    assert "prompt" not in qro["input_contract_keys"]
    assert "context_code" not in qro["input_contract_keys"]
    assert "output_text" not in qro["output_contract_keys"]
    assert prompt_secret not in str(audit_body)
    assert context_secret not in str(audit_body)
    assert "SHOULD_NOT_ENTER_IDE_AI_QRO" not in str(audit_body)
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == 1
    ir = main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.entry_source == "ide"
    assert coverage.entrypoint_ref == "ide:ai_complete"
    assert prompt_secret not in str(ir) + str(compiler_pass) + str(coverage)
    assert context_secret not in str(ir) + str(compiler_pass) + str(coverage)
    assert "SHOULD_NOT_ENTER_IDE_AI_QRO" not in str(ir) + str(compiler_pass) + str(coverage)


def test_http_ide_ai_complete_requires_market_data_use_validation_before_llm(http, monkeypatch):
    from app import main

    called = {"llm": False}

    class _FakeLLM:
        provider = "fake-ide-llm"

        def chat(self, _messages):  # noqa: ANN001
            called["llm"] = True
            return SimpleNamespace(content="print('should not run')")

    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None, **_kwargs: _FakeLLM())
    client, _ = http
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(
        "/api/ide/ai_complete",
        json={"mode": "write", "market": "crypto_perp", "prompt": "write code"},
    )

    assert res.status_code == 422
    assert "market_data_use_validation_refs" in res.text
    assert called["llm"] is False
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before


def test_http_ide_ai_complete_rejects_violation_market_data_use_validation_before_llm(
    http,
    monkeypatch,
):
    from app import main

    called = {"llm": False}
    violation = _market_data_use_validation(
        validation_ref="market_data_use:ide_ai:violation",
        violation_codes=("live_permission_missing",),
    )
    monkeypatch.setattr(main, "MARKET_DATA_REGISTRY", _MarketDataUseRegistry([violation]))

    class _FakeLLM:
        provider = "fake-ide-llm"

        def chat(self, _messages):  # noqa: ANN001
            called["llm"] = True
            return SimpleNamespace(content="print('should not run')")

    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None, **_kwargs: _FakeLLM())
    client, _ = http
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    res = client.post(
        "/api/ide/ai_complete",
        json={
            "mode": "write",
            "market": "crypto_perp",
            "prompt": "write code",
            "market_data_use_validation_refs": [violation.validation_ref],
        },
    )

    assert res.status_code == 422
    assert "violation" in res.text
    assert called["llm"] is False
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before


def test_http_ide_ai_complete_empty_prompt_does_not_fabricate_qro(http):
    from app import main

    client, _ = http
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    res = client.post("/api/ide/ai_complete", json={"prompt": ""})

    assert res.status_code == 400
    assert len(main.RESEARCH_GRAPH_STORE.commands()) == before


def test_http_validate_seeds_bad_graph_reports_error(http):
    client, svc = http
    svc.save_strategy("tester", "s1", "print(1)")
    nodes = [
        {"id": "prisk", "title": "PortfolioRisk", "ins": [],
         "outs": [{"id": "rp", "name": "risked", "dt": "riskedPortfolio"}]},
        {"id": "exec", "title": "Execution",
         "ins": [{"id": "ei", "name": "approved", "dt": APPROVED_PORTFOLIO_DT, "role": "exec", "req": True}],
         "outs": []},
    ]
    edges = [{"id": "eb", "from": {"node": "prisk", "port": "rp"}, "to": {"node": "exec", "port": "ei"}}]
    res = client.post("/api/ide/strategies/s1/validate", json={"nodes": nodes, "edges": edges})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert any("B6" in e["text"] for e in body["errors"])


def test_http_validate_unknown_strategy_404(http):
    client, _ = http
    res = client.post("/api/ide/strategies/nope/validate", json={"nodes": [], "edges": []})
    assert res.status_code == 404


def test_http_versions_and_fork_roundtrip(http):
    client, svc = http
    svc.save_strategy("tester", "base", "print('p')", asset_class="crypto_perp")
    v = client.get("/api/ide/strategies/base/versions")
    assert v.status_code == 200
    assert len(v.json()) == 1

    fk = client.post("/api/ide/strategies/base/fork", json={})
    assert fk.status_code == 200
    forked_name = fk.json()["name"]
    assert forked_name != "base"

    fv = client.get(f"/api/ide/strategies/{forked_name}/versions")
    assert fv.json()[0]["origin"] == "fork"
    assert fv.json()[0]["parent_strategy_id"] is not None


def test_http_fork_unknown_404(http):
    client, _ = http
    res = client.post("/api/ide/strategies/nope/fork", json={})
    assert res.status_code == 404


def test_http_live_snapshot_crypto_readonly(http):
    client, svc = http
    svc.save_strategy("tester", "cs", "print(1)", asset_class="crypto_perp")
    res = client.get("/api/ide/strategies/cs/live_snapshot")
    assert res.status_code == 200
    body = res.json()
    assert body["live_allowed"] is True
    assert body["readonly"] is True
    # 无任何下单参数键。
    assert "order" not in body and "qty" not in body and "price" not in body


def test_http_live_snapshot_equity_cn_forbidden(http):
    """A股 live 永拒：equity_cn 策略 live_snapshot → live_allowed=False，无运行态。"""
    client, svc = http
    svc.save_strategy("tester", "acn", "print(1)", asset_class="equity_cn")
    res = client.get("/api/ide/strategies/acn/live_snapshot")
    assert res.status_code == 200
    body = res.json()
    assert body["live_allowed"] is False
    assert "禁止" in body["reason"]
    assert body["recent_runs"] == []
