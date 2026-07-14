"""F4 · 三纯库 / 信号契约 / 暴力遍历挖掘 真实后端 + 治理对抗测试。

对抗（种已知坏门必抓）：
- 对抗① POST `.pt`「本体」入因子库必拒（R17 范畴门：把模型当因子塞库是范畴错误）。
- 对抗② 生成器接口见守门指标（IC/IR/DSR 作排序键）必抓（R16 生成/守门解耦）。
- 对抗③ 等价公式（冗余括号/空白）绕诚实-N 必抓（N_eff 不被等价改写抬高）。
- 对抗④ 信号契约跳血统门 / 泄露声明门必抓（缺本体回指 / 缺 OOF+purge+embargo → 拒）。
不破基线：admit 准入路径、信号契约登记成功路径、挖掘正常路径返 200 + 合理结构；
         candidates 与 gate 物理分离（守门指标不与生成结构同列表排序）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.auth import require_user_dependency
from app.factor_factory import (
    SignalContractError,
    SignalContractRegistry,
    admit_artifact_to_factor_lib,
    looks_like_model_body,
)
from app.factor_factory.mining import (
    GATE_METRIC_KEYWORDS,
    GENERATOR_SORT_KEYS,
    MiningGateLeakError,
    assert_generator_sort_key_clean,
    candidate_config_hash,
    evaluate_gate,
    generate_candidates,
    honest_n,
    is_gate_metric_key,
    run_mining,
)
from app.main import app
from app.research_os import (
    PersistentCompilerIRStore,
    PersistentEntrypointEvidenceRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentSignalValidationRegistry,
    QROType,
    ResearchGraphStore,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver


def _patch_goal_proof_stores(tmp_path, monkeypatch):  # noqa: ANN001
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
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(app_main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(app_main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(app_main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(app_main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "SIGNAL_CONTRACTS", SignalContractRegistry(tmp_path / "signal_contracts.jsonl"))
    monkeypatch.setattr(app_main, "SIGNAL_VALIDATIONS", PersistentSignalValidationRegistry(tmp_path / "signal_validations.jsonl"))
    _patch_goal_proof_stores(tmp_path, monkeypatch)
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="tester")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def _assert_compiler_coverage(body: dict, *, entrypoint_ref: str, qro_type: QROType) -> None:
    assert body["qro_id"].startswith("qro_")
    assert body["research_graph_command_id"].startswith("rgcmd_")
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    qro = app_main.RESEARCH_GRAPH_STORE.qro(body["qro_id"])
    ir = app_main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = app_main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = app_main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert qro.qro_type == qro_type
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.input_qro_refs == (body["qro_id"],)
    assert compiler_pass.entry_source == "api"
    assert coverage.entry_source == "api"
    assert coverage.entrypoint_ref == entrypoint_ref
    assert coverage.qro_refs == (body["qro_id"],)
    assert coverage.research_graph_command_refs == (body["research_graph_command_id"],)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert compiler_pass.direct_graph_mutation is False
    assert compiler_pass.bypassed_permission is False
    assert compiler_pass.raw_llm_output_embedded_as_ir is False
    assert coverage.silent_mock_fallback_used is False
    assert coverage.raw_payload_persisted is False
    compiled_text = f"{qro.__dict__} {ir.__dict__} {compiler_pass.__dict__} {coverage.__dict__}"
    assert "raw_predictions" not in compiled_text
    assert "raw_returns" not in compiled_text
    assert "asset_returns" not in compiled_text
    assert "sk-" not in compiled_text


# ════════════════ 基线：正常路径 ════════════════
def test_admit_expression_and_signal_pass(client):
    r = client.post("/api/factors/admit", json={"kind": "expression", "ref": "ts_corr(close,volume,20)"})
    assert r.status_code == 200 and r.json()["admitted"] is True
    r2 = client.post("/api/factors/admit", json={"kind": "signal_contract", "ref": "sig::dl_tcn_seq_pred"})
    assert r2.status_code == 200 and r2.json()["admitted"] is True


def test_mine_normal_path_shape(client):
    body = {
        "exprs": [
            {"expr": "rank(close/ts_mean(close,20))", "fam": "动量"},
            {"expr": "neg(ts_zscore(close,20))", "fam": "反转"},
            {"expr": "ts_corr(close,volume,20)", "fam": "量价"},
        ],
        "sort_key": "complexity",
    }
    r = client.post("/api/factors/mine", json=body)
    assert r.status_code == 200
    j = r.json()
    assert len(j["candidates"]) == 3 and len(j["gate"]) == 3
    assert "honest_n" in j and "pass_count" in j
    # candidates 与 gate 物理分离：候选对象里绝无守门指标键。
    for c in j["candidates"]:
        assert "ic" not in c and "ir" not in c and "dsr" not in c
    # 守门指标只在 gate 列表。
    for g in j["gate"]:
        assert {"ic", "ir", "dsr", "passed"}.issubset(g.keys())


def test_signal_contract_register_and_list_success(client):
    body = {
        "name": "TCN 预测信号",
        "source_lib": "dl",
        "model_ref": "tcn_seq_alpha_v2.pt",
        "output_kind": "seq_pred",
        "horizon": 5,
        "leakage": {"oof": True, "purge": True, "embargo": True, "embargo_days": 5},
    }
    r = client.post("/api/factors/signal_contracts", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["registered"] is True
    assert j["signal_ref"].startswith("sig::")
    assert j["author"] == "tester"
    _assert_compiler_coverage(j, entrypoint_ref="api:factors.signal_contracts", qro_type=QROType.SIGNAL)
    qro = app_main.RESEARCH_GRAPH_STORE.qro(j["qro_id"])
    assert qro.output_contract["signal_ref"] == j["signal_ref"]
    assert "tcn_seq_alpha_v2.pt" not in f"{qro.__dict__}"
    lst = client.get("/api/factors/signal_contracts")
    assert lst.status_code == 200
    assert any(c["signal_id"] == j["signal_id"] for c in lst.json())


def test_signal_contract_registry_persists_and_replays(tmp_path):
    path = tmp_path / "signal_contracts.jsonl"
    registry = SignalContractRegistry(path)
    contract = registry.register(
        name="Persistent signal",
        source_lib="ml",
        model_ref="registry://models/persistent.pkl",
        output_kind="xs_score",
        horizon=5,
        leakage={"oof": True, "purge": True, "embargo": True},
        author="tester",
    )

    reloaded = SignalContractRegistry(path)

    assert reloaded.get(contract.signal_ref).signal_ref == contract.signal_ref
    assert reloaded.list()[0].model_ref == "registry://models/persistent.pkl"


def test_signal_validation_api_records_and_summarizes(tmp_path, monkeypatch, client):
    contract_registry = SignalContractRegistry(tmp_path / "signal_contracts.jsonl")
    contract = contract_registry.register(
        name="Validated signal",
        source_lib="ml",
        model_ref="registry://models/validated.pkl",
        output_kind="xs_score",
        horizon=5,
        leakage={"oof": True, "purge": True, "embargo": True},
        author="tester",
    )
    validation_path = tmp_path / "signal_validations.jsonl"
    validation_registry = PersistentSignalValidationRegistry(validation_path)
    monkeypatch.setattr(app_main, "SIGNAL_CONTRACTS", contract_registry)
    monkeypatch.setattr(app_main, "SIGNAL_VALIDATIONS", validation_registry)

    body = {
        "signal_ref": contract.signal_ref,
        "validation_dataset_ref": "dataset_version:btc_daily:oos",
        "evaluation_window_ref": "window:2025q4",
        "methodology_ref": "methodology:cpcv_walkforward",
        "metric_refs": ["metric:rank_ic", "metric:dsr"],
        "performance_summary_ref": "signal_perf:validated:oos",
        "leakage_check_ref": "leakage:oof_purge_embargo",
        "evidence_refs": ["evidence:signal_validation_report"],
        "verdict": "accepted",
        "known_limits_refs": ["limit:not_alpha_proof"],
    }
    response = client.post("/api/research-os/signal_validations", json=body)
    assert response.status_code == 200, response.text
    response_body = response.json()
    validation_id = response_body["validation_id"]
    assert response_body["signal_ref"] == contract.signal_ref
    _assert_compiler_coverage(
        response_body,
        entrypoint_ref="api:research_os.signal_validations",
        qro_type=QROType.SIGNAL,
    )

    summary = client.get("/api/research-os/signal_validations/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["signal_validation_total"] == 1
    assert payload["accepted_signal_refs"] == [contract.signal_ref]
    assert payload["validations"][0]["validation_id"] == validation_id
    assert "raw_predictions" not in payload["validations"][0]
    assert "raw_returns" not in payload["validations"][0]

    reloaded = PersistentSignalValidationRegistry(validation_path)
    assert (
        reloaded.validation(validation_id, owner_user_id="tester").performance_summary_ref
        == "signal_perf:validated:oos"
    )


def test_signal_validation_api_rejects_unknown_signal_without_write(tmp_path, monkeypatch, client):
    monkeypatch.setattr(app_main, "SIGNAL_CONTRACTS", SignalContractRegistry(tmp_path / "signal_contracts.jsonl"))
    validation_path = tmp_path / "signal_validations.jsonl"
    monkeypatch.setattr(app_main, "SIGNAL_VALIDATIONS", PersistentSignalValidationRegistry(validation_path))

    response = client.post(
        "/api/research-os/signal_validations",
        json={
            "signal_ref": "sig::missing",
            "validation_dataset_ref": "dataset_version:btc_daily:oos",
            "evaluation_window_ref": "window:2025q4",
            "methodology_ref": "methodology:cpcv_walkforward",
            "metric_refs": ["metric:rank_ic"],
            "performance_summary_ref": "signal_perf:missing:oos",
            "leakage_check_ref": "leakage:oof_purge_embargo",
            "evidence_refs": ["evidence:signal_validation_report"],
            "verdict": "accepted",
        },
    )
    assert response.status_code == 422
    assert "unknown SignalContract" in response.json()["detail"]
    assert not validation_path.exists()


# ════════════════ 对抗① POST .pt 本体入因子库必拒（R17 范畴门）════════════════
def test_adv1_post_pt_body_to_factor_lib_rejected(client):
    # 显式 model_body 范畴
    r = client.post("/api/factors/admit", json={"kind": "model_body", "ref": "tcn_seq_alpha_v2.pt"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["admitted"] is False
    assert "范畴错误" in detail["reason"]

    # 即便范畴误标成 expression，但 ref 是 .pt 本体文件 → 双保险拒。
    r2 = client.post("/api/factors/admit", json={"kind": "expression", "ref": "model.pt"})
    assert r2.status_code == 422
    assert r2.json()["detail"]["admitted"] is False


def test_adv1_admit_logic_unit():
    assert admit_artifact_to_factor_lib("model_body", "x.pt")[0] is False
    assert admit_artifact_to_factor_lib("model_body", "x.pkl")[0] is False
    # 各本体后缀都识别
    for ext in (".pt", ".pth", ".onnx", ".pkl", ".joblib", ".h5", ".ckpt"):
        assert looks_like_model_body(f"foo{ext}") is True
    assert looks_like_model_body("sig::dl_pred") is False
    assert admit_artifact_to_factor_lib("expression", "ts_mean(close,5)")[0] is True
    assert admit_artifact_to_factor_lib("signal_contract", "sig::x")[0] is True


# ════════════════ 对抗② 生成器见守门指标必抓（R16 解耦）════════════════
def test_adv2_gate_metric_as_sort_key_rejected_endpoint(client):
    for bad in ["ic", "ir", "dsr", "sharpe", "pbo", "t_stat", "pnl", "alpha_ret", "IC"]:
        r = client.post(
            "/api/factors/mine",
            json={"exprs": [{"expr": "ts_mean(close,5)", "fam": "动量"}], "sort_key": bad},
        )
        assert r.status_code == 422, f"{bad} 应被解耦门拒"
        assert r.json()["detail"]["gate_leak"] is True


def test_adv2_gate_metric_leak_unit():
    for k in ["ic", "IC", "ir_score", "dsr", "sharpe", "pbo", "t_stat", "pnl", "alpha_ret", "sortino"]:
        assert is_gate_metric_key(k) is True
        with pytest.raises(MiningGateLeakError):
            assert_generator_sort_key_clean(k)
    # 白名单全是结构维度，零守门指标
    for k in GENERATOR_SORT_KEYS:
        assert is_gate_metric_key(k) is False
        assert_generator_sort_key_clean(k)  # 不抛
    for m in ("ic", "ir", "dsr"):
        assert m in GATE_METRIC_KEYWORDS


def test_adv2_generator_output_carries_no_gate_metric():
    """生成器产出对象（MiningCandidate）结构上无任何守门指标字段。"""

    cands = generate_candidates([{"expr": "ts_corr(close,volume,20)", "fam": "量价"}], sort_key="complexity")
    d = cands[0].to_dict()
    for forbidden in ("ic", "ir", "dsr", "sharpe", "pbo", "passed"):
        assert forbidden not in d
    # 守门器独立算出才有这些
    gate = evaluate_gate(cands)
    assert {"ic", "ir", "dsr", "passed"}.issubset(gate[0].to_dict().keys())


# ════════════════ 对抗③ 等价公式绕诚实-N 必抓 ════════════════
def test_adv3_equivalent_formula_does_not_inflate_n_eff(client):
    body = {
        "exprs": [
            {"expr": "rank(close/ts_mean(close,20))", "fam": "动量"},
            {"expr": "(rank(close/ts_mean(close,20)))", "fam": "动量"},  # 等价：仅多冗余括号
            {"expr": "rank( close / ts_mean(close, 20) )", "fam": "动量"},  # 等价：仅空白
            {"expr": "neg(ts_zscore(close,20))", "fam": "反转"},
        ],
        "sort_key": "complexity",
    }
    r = client.post("/api/factors/mine", json=body)
    assert r.status_code == 200
    hn = r.json()["honest_n"]
    assert hn["total"] == 4
    assert hn["n_eff"] == 2  # 三个等价的只算 1 + 一个不同的
    assert hn["duplicates"] == 2
    assert hn["n_eff"] <= hn["total"]


def test_adv3_honest_n_uses_lineage_config_hash():
    """诚实-N 去重键 = lineage.config_hash（语法级归一，单一身份源），等价改写同 hash。"""

    h1 = candidate_config_hash("rank(close/ts_mean(close,20))")
    h2 = candidate_config_hash("(rank(close/ts_mean(close,20)))")
    h3 = candidate_config_hash("rank( close / ts_mean(close, 20) )")
    assert h1 == h2 == h3
    # 真不同公式 → 不同 hash
    assert candidate_config_hash("rank(close)") != candidate_config_hash("rank(volume)")
    rep = honest_n([
        "rank(close/ts_mean(close,20))",
        "(rank(close/ts_mean(close,20)))",
        "neg(ts_zscore(close,20))",
    ])
    assert rep.total == 3 and rep.n_eff == 2 and rep.duplicates == 1
    assert rep.n_eff <= rep.total


# ════════════════ 对抗④ 信号契约跳血统门 / 泄露门必抓 ════════════════
def test_adv4_signal_contract_orphan_body_rejected(client):
    """血统门：model_ref 缺失 / 不像本体文件（悬空信号）→ 拒。"""

    # 缺 model_ref
    r = client.post(
        "/api/factors/signal_contracts",
        json={"name": "x", "source_lib": "ml", "model_ref": "", "output_kind": "xs_score",
              "horizon": 1, "leakage": {"oof": True, "purge": True, "embargo": True}},
    )
    assert r.status_code == 422
    assert "血统门" in r.json()["detail"]["reason"]

    # model_ref 不是本体文件（指向 sig:: / 裸串）→ 悬空，拒
    r2 = client.post(
        "/api/factors/signal_contracts",
        json={"name": "x", "source_lib": "dl", "model_ref": "sig::not_a_body", "output_kind": "seq_pred",
              "horizon": 5, "leakage": {"oof": True, "purge": True, "embargo": True}},
    )
    assert r2.status_code == 422
    assert "血统门" in r2.json()["detail"]["reason"]


def test_adv4_signal_contract_leakage_declaration_gate(client):
    """泄露声明门：缺 OOF/purge/embargo 任一 → 拒（R18）。"""

    for leak in [
        {"oof": False, "purge": True, "embargo": True},
        {"oof": True, "purge": False, "embargo": True},
        {"oof": True, "purge": True, "embargo": False},
        {},  # 全缺
        None,  # 未提供
    ]:
        r = client.post(
            "/api/factors/signal_contracts",
            json={"name": "x", "source_lib": "ml", "model_ref": "gbdt_v3.pkl",
                  "output_kind": "xs_score", "horizon": 1, "leakage": leak},
        )
        assert r.status_code == 422, f"leak={leak} 应被泄露声明门拒"
        assert "泄露声明门" in r.json()["detail"]["reason"]


def test_adv4_signal_contract_wrong_source_lib_rejected(client):
    """范畴门：算术不走信号契约（source_lib 须 ml/dl）。"""

    r = client.post(
        "/api/factors/signal_contracts",
        json={"name": "x", "source_lib": "arith", "model_ref": "gbdt_v3.pkl",
              "output_kind": "xs_score", "horizon": 1,
              "leakage": {"oof": True, "purge": True, "embargo": True}},
    )
    assert r.status_code == 422
    assert "source_lib" in r.json()["detail"]["reason"]


def test_adv4_signal_contract_unit_gate():
    reg = SignalContractRegistry()
    # 孤儿：model_ref 不像本体
    with pytest.raises(SignalContractError):
        reg.register(name="x", source_lib="dl", model_ref="sig::orphan", output_kind="seq_pred",
                     horizon=5, leakage={"oof": True, "purge": True, "embargo": True})
    # 泄露未声明齐
    with pytest.raises(SignalContractError):
        reg.register(name="x", source_lib="ml", model_ref="gbdt.pkl", output_kind="xs_score",
                     horizon=1, leakage={"oof": True, "purge": False, "embargo": True})
    # 成功路径
    c = reg.register(name="ok", source_lib="ml", model_ref="gbdt.pkl", output_kind="xs_score",
                     horizon=1, leakage={"oof": True, "purge": True, "embargo": True})
    assert c.signal_ref.startswith("sig::")
    assert reg.get(c.signal_ref).signal_id == c.signal_id


# ════════════════ 基线回归：原 3 个因子端点不破 ════════════════
def test_baseline_existing_factor_endpoints(client):
    assert client.get("/api/factors/operators").status_code == 200
    factors = client.get("/api/factors")
    assert factors.status_code == 200 and isinstance(factors.json(), list)
    # signal_contracts 静态 GET 不被 {factor_id} 吞掉
    assert client.get("/api/factors/signal_contracts").status_code == 200
