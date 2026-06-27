"""M2 Model台后端接线 · 对抗测试（种已知坏门必抓）。

覆盖本卡 5 项后端落点 + 3 条本卡对抗门：
  ① JobDetail 富文档（why/data/window/label/design/arch/hparams）持久化 + to_dict 暴露
  ② ModelCard io_spec(card_loader 解析 + to_dict 暴露)
  ③ walk-forward 逐窗端点（诚实合约：非 walk_forward CV 不假绿）
  ④ promote gate 字段（approver≠creator / reason / risk_restated 强制）→ 缺/自批 422
  ⑤ 构建台图 codegen（D-DESK-F1B(a) 线性链）—— 纯字符串拼装、主进程绝不 import torch

对抗门：
  - promote 缺 approver≠creator → 422（self-approve 走正路才放行，裸自批硬拒）
  - 图 codegen 在主进程编译/实例化 torch 必抓（断 torch 仍能产代码字符串）
  - JobDetail / IoSpec to_dict 字段齐（缺字段=假绿/断链）
  - 非线性图 / 缺 input·output / 未支持原子 → GraphCodegenError（不放行残图）
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import require_user_dependency
from app.main import MODEL_GOVERNANCE_REGISTRY, MODEL_REGISTRY, VERDICT_STORE, VERIFIER, app
from app.research_os import (
    ModelArtifactFormat,
    ModelArtifactManifestEntry,
    ModelArtifactSource,
    ModelGovernancePassport,
    ModelRiskTier,
    RecertificationTrigger,
    SafeLoadingPolicy,
)
from app.training.codegen import GraphCodegenError, graph_to_code

client = TestClient(app)


def _good_evidence() -> dict:
    from app.approval import EvidenceSnapshot

    return EvidenceSnapshot(
        config_hash="cfg_v1_aaaa", dataset_version="ds1", n_eff=5, n_trials_raw=5,
        dsr=0.92, pbo=0.10, bootstrap_ci=(0.4, 1.8), bootstrap_estimate=1.0,
        champion_challenger={"verdict": "challenger_wins", "delta_sharpe": 0.3},
        returns_sha256="r1",
    ).to_dict()


# ===========================================================================
# ① JobDetail 富文档持久化 + to_dict 暴露
# ===========================================================================
def test_training_job_detail_field_round_trips() -> None:
    """提交 detail 富文档 → 持久化进 job → to_dict 原样暴露（动机卡数据源不断链）。"""
    from app.training.store import TrainingJob

    detail = {
        "why": "为排序基线做对照", "data": "equity_cn 5412 标的", "window": "2019~2023 训 · 2024 OOS",
        "label": "fwd_ret_5 截面排序", "design": "GBDT 非线性交互", "arch": "LightGBM 800 trees",
        "hparams": "lr 0.03 · purged_kfold(6)", "sections": [["正则化", "dropout+weight_decay"]],
        "io_spec": {"in_groups": [{"group": "动量", "type": "f32", "fields": "mom_20d"}]},
    }
    job = TrainingJob(job_id="j1", name="t", model="lgbm", family="ml", task="regression", detail=detail)
    d = job.to_dict()
    assert "detail" in d, "TrainingJob.to_dict 缺 detail（作业台动机卡数据源断链=假绿）"
    for k in ("why", "data", "window", "label", "design", "arch", "hparams", "sections"):
        assert k in d["detail"], f"detail 缺富文档字段 {k}"
    assert d["detail"]["io_spec"]["in_groups"][0]["group"] == "动量"


def test_training_submit_persists_detail(training_market_data_use_validation_ref) -> None:
    """端到端：POST /api/training/jobs 带 detail → GET jobs/{id} 透传（库读回不丢）。"""
    detail = {"why": "对抗测试动机", "data": "demo", "window": "w", "label": "l",
              "design": "d", "arch": "a", "hparams": "h", "sections": []}
    r = client.post("/api/training/jobs", json={
        "name": "m2-detail", "model": "xgboost", "task": "regression",
        "feature_cols": ["f_mom5"], "label_col": "label",
        "dataset_id": "demo_ashare_xsec", "detail": detail,
        "market_data_use_validation_refs": [training_market_data_use_validation_ref],
    })
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    got = client.get(f"/api/training/jobs/{job_id}").json()
    assert got["detail"]["why"] == "对抗测试动机", "detail 未持久化进 job 快照"


def test_training_job_without_detail_is_empty_not_fabricated(training_market_data_use_validation_ref) -> None:
    """旧 job 无 detail → 空 dict（向后兼容），绝不编造（不假绿）。"""
    r = client.post("/api/training/jobs", json={
        "name": "m2-nodetail", "model": "xgboost", "task": "regression",
        "feature_cols": ["f_mom5"], "dataset_id": "demo_ashare_xsec",
        "market_data_use_validation_refs": [training_market_data_use_validation_ref],
    })
    assert r.status_code == 200
    assert r.json()["detail"] == {}


# ===========================================================================
# ② ModelCard io_spec 解析 + to_dict 暴露
# ===========================================================================
def test_model_card_io_spec_default_empty() -> None:
    """未声明 io_spec 的卡 → {} 且 to_dict 暴露该键（前端据空不渲染、不假绿）。"""
    from app.models.catalog import get_model_card

    card = get_model_card("lgbm")
    d = card.to_dict()
    assert "io_spec" in d, "ModelCard.to_dict 缺 io_spec 键（IO 规格单一来源断链）"
    assert isinstance(d["io_spec"], dict)


def test_model_card_io_spec_parsed_from_frontmatter(tmp_path) -> None:
    """frontmatter 带 io_spec → card_loader 解析进 dataclass，to_dict 原样暴露。"""
    from app.models.card_loader import parse_model_card, render_card_md

    fm = {
        "key": "iocard", "family": "ml", "display_name": "io 卡",
        "tasks": ["regression"], "description": "测 io_spec",
        "io_spec": {
            "in_groups": [{"group": "动量·5", "type": "f32", "fields": "mom_20d"}],
            "out_groups": [{"group": "主输出·1", "type": "f32 [N,1]", "fields": "score"}],
            "in_src": "equity_cn", "in_pre": "zscore", "out_note": "截面排序分",
        },
    }
    p = tmp_path / "iocard.md"
    p.write_text(render_card_md(fm, ""), encoding="utf-8")
    card = parse_model_card(p)
    assert card.io_spec["in_src"] == "equity_cn"
    d = card.to_dict()
    assert d["io_spec"]["in_groups"][0]["group"] == "动量·5"
    assert d["io_spec"]["out_groups"][0]["fields"] == "score"


# ===========================================================================
# ③ walk-forward 逐窗端点（诚实合约）
# ===========================================================================
def test_walk_forward_extract_honest_for_kfold() -> None:
    """purged_kfold 结果 → ran=False（绝不把 k-fold 冒充成 walk-forward 通过）。"""
    from app.eval.model_eval import walk_forward_windows

    result = {
        "spec": {"cv_scheme": "purged_kfold"},
        "fold_metrics": [
            {"fold_index": 0, "n_train": 400, "n_test": 100, "metrics": {"ndcg": 0.23}},
            {"fold_index": 1, "n_train": 400, "n_test": 100, "metrics": {"ndcg": -0.05}},
        ],
    }
    out = walk_forward_windows(result)
    assert out["ran"] is False, "purged_kfold 被标成 walk-forward 已跑（假绿）"
    assert out["n_windows"] == 2
    # 负窗原样返回（前端据正负诚实上色，不洗成绿）
    assert out["windows"][1]["metric"] == pytest.approx(-0.05)
    assert out["n_positive"] == 1


def test_walk_forward_extract_ran_for_walk_forward_scheme() -> None:
    """cv_scheme=walk_forward → ran=True；逐窗带真实 n_train/n_test。"""
    from app.eval.model_eval import walk_forward_windows

    result = {
        "spec": {"cv_scheme": "walk_forward"},
        "fold_metrics": [{"fold_index": 0, "n_train": 252, "n_test": 63, "metrics": {"ir": 0.4}}],
    }
    out = walk_forward_windows(result)
    assert out["ran"] is True
    assert out["windows"][0]["n_train"] == 252 and out["windows"][0]["n_test"] == 63
    assert out["windows"][0]["metric_key"] == "ir"


def test_walk_forward_endpoint_unrun_job_not_fabricated(training_market_data_use_validation_ref) -> None:
    """未训完 / 无 artifact 的 job walk-forward → windows=[]，ran=False（不编造逐窗）。"""
    r = client.post("/api/training/jobs", json={
        "name": "m2-wf", "model": "xgboost", "task": "regression",
        "feature_cols": ["f_mom5"], "dataset_id": "demo_ashare_xsec",
        "market_data_use_validation_refs": [training_market_data_use_validation_ref],
    })
    job_id = r.json()["job_id"]
    wf = client.get(f"/api/training/jobs/{job_id}/walkforward").json()
    assert wf["ran"] is False and wf["windows"] == []


def test_walk_forward_endpoint_404_unknown_job() -> None:
    r = client.get("/api/training/jobs/does-not-exist/walkforward")
    assert r.status_code == 404


# ===========================================================================
# ④ promote gate 字段强制（approver≠creator / reason / risk_restated）→ 422
# ===========================================================================
@pytest.fixture
def _auth_override():
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="tester")
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def _consistent_verdict(config_hash: str) -> str:
    """经验证官产一份 consistent 权威裁决（target_ref==config_hash，异模型一致），返回 verdict_id。

    consistent 要件：claims==recomputed（容差内）+ generator_model≠checker_model（独立性已确立）。
    直接走 VERIFIER/VERDICT_STORE（与端点同模块）；落进 GATE_SERVICE 的 verdict_lookup 源，
    使 promote 门凑齐要件→pending，从而能测自批/空理由的 422。
    """
    rec = VERIFIER.reconcile(
        target_ref=config_hash,
        claims={"sharpe": 1.0}, recomputed={"sharpe": 1.0},
        generator_model="gen-A", checker_model="chk-B",
        notes="M2 对抗 fixture",
    )
    assert rec.verdict == "consistent", f"fixture 裁决非 consistent，门不会 pending: {rec.verdict}"
    VERDICT_STORE.record(rec)
    return rec.verdict_id


def _record_model_passport(model_id: str, version: int) -> str:
    passport = ModelGovernancePassport(
        model_version_ref=f"model_version:{model_id}:v{version}",
        model_type_card_ref="model_type_card:lgbm",
        training_plan_ref=f"training_plan:{model_id}:v{version}",
        training_run_ref=f"training_run:{model_id}:v{version}",
        model_risk_tier=ModelRiskTier.MEDIUM,
        materiality="model desk staging candidate",
        intended_use=("staging review",),
        prohibited_use=("direct live order placement",),
        dataset_refs=("dataset_version:fixture",),
        feature_refs=("feature:fixture",),
        label_refs=("label:fixture",),
        training_code_hash=f"codehash:{model_id}:v{version}",
        artifact_manifest=(
            ModelArtifactManifestEntry(
                artifact_ref=f"artifact:{model_id}:v{version}",
                uri=f"registry://models/{model_id}/v{version}/model.safetensors",
                artifact_format=ModelArtifactFormat.SAFE_TENSORS,
                source=ModelArtifactSource.PROJECT_PRODUCED,
                content_hash=f"sha256:{model_id}{version}",
                producer_run_ref=f"training_run:{model_id}:v{version}",
                sandbox_inspection_ref=f"inspect:{model_id}:v{version}",
            ),
        ),
        safe_loading_policy=SafeLoadingPolicy(
            sandboxed_load_inspect=True,
            prefer_safe_tensors=True,
            torch_weights_only=True,
        ),
        vendor_dependency_refs=("none",),
        foundation_model_dependency_refs=("none",),
        monitoring_requirements=("performance degradation monitor",),
        recertification_triggers=tuple(RecertificationTrigger),
        validation_dossier_ref=f"validation_dossier:{model_id}:v{version}",
        challenger_result="fixture challenger review complete",
    )
    return MODEL_GOVERNANCE_REGISTRY.record_passport(passport).passport_id


def _open_staging_gate(creator: str):
    """经 MODEL_REGISTRY 正路开一个 pending staging 门，返回 (model_id, gate_id)。"""
    import uuid

    mid = f"m2adv-{uuid.uuid4().hex[:8]}"
    MODEL_REGISTRY.register_version(mid, artifact_path="a.pkl")
    passport_ref = _record_model_passport(mid, 2)
    MODEL_REGISTRY.register_version(mid, artifact_path="b.pkl", model_passport_ref=passport_ref)
    evidence = _good_evidence()
    vid = _consistent_verdict(evidence["config_hash"])
    gate = MODEL_REGISTRY.promote(
        mid, 2, "staging", created_by=creator, verification_record_id=vid,
        evidence=evidence, strategy_goal_ref="theme", model_passport_ref=passport_ref,
    )
    assert gate.decision == "pending", f"门未 pending（前置坏，无法测自批）: {gate}"
    return mid, gate.gate_id


def test_promote_approve_self_approve_rejected_422(_auth_override) -> None:
    """对抗：approver == creator（裸自批）→ 422（self-approve 必走正路，否则绝不放行）。"""
    mid, gate_id = _open_staging_gate(creator="alice")
    r = client.post(f"/api/models/{mid}/gates/{gate_id}/approve",
                    json={"approver": "alice", "reason": "想自批，理由够长够具体",
                          "risk_restated": True})
    assert r.status_code == 422, f"approver==creator 竟放行（双控门坏）: {r.text}"


def test_promote_approve_empty_reason_rejected_422(_auth_override) -> None:
    """对抗：reason 空 → 422（审批理由不可空/套话）。"""
    mid, gate_id = _open_staging_gate(creator="alice")
    r = client.post(f"/api/models/{mid}/gates/{gate_id}/approve",
                    json={"approver": "bob", "reason": "", "risk_restated": True})
    assert r.status_code == 422, f"空 reason 竟放行（门坏）: {r.text}"


def test_promote_approve_distinct_approver_with_reason_passes(_auth_override) -> None:
    """正路：approver≠creator + 实质 reason → 真翻 stage 到 staging。"""
    mid, gate_id = _open_staging_gate(creator="alice")
    r = client.post(f"/api/models/{mid}/gates/{gate_id}/approve",
                    json={"approver": "bob", "reason": "独立复核证据三角同向适用域明确，可上 staging",
                          "risk_restated": True})
    assert r.status_code == 200, r.text
    versions = client.get(f"/api/models/{mid}/versions").json()
    assert any(v["version"] == 2 and v["stage"] == "staging" for v in versions), \
        "approve 后 stage 未真翻 staging（gate→registry 执行断链）"


def test_promote_bare_flip_to_staging_blocked() -> None:
    """侧门关闭：apply_stage 不可裸翻 staging（必经审批门）。"""
    from app.approval.schema import GateStateError

    import uuid
    mid = f"m2bare-{uuid.uuid4().hex[:8]}"
    MODEL_REGISTRY.register_version(mid, artifact_path="a.pkl")
    with pytest.raises(GateStateError):
        MODEL_REGISTRY.apply_stage(mid, 1, "staging")


# ===========================================================================
# ⑤ 图 codegen（线性链）+ M6 主进程不碰 torch（对抗：断 torch 仍产代码）
# ===========================================================================
def _linear_graph() -> dict:
    return {
        "nodes": [
            {"id": "n1", "type": "input", "features": 28},
            {"id": "n2", "type": "linear", "params": {"out": 256}},
            {"id": "n3", "type": "gelu"},
            {"id": "n4", "type": "head", "params": {"out": 1}},
            {"id": "n5", "type": "output"},
        ],
        "edges": [
            {"from": {"node": "n1"}, "to": {"node": "n2"}},
            {"from": {"node": "n2"}, "to": {"node": "n3"}},
            {"from": {"node": "n3"}, "to": {"node": "n4"}},
            {"from": {"node": "n4"}, "to": {"node": "n5"}},
        ],
    }


def test_graph_codegen_pure_string_no_torch_in_main_process(monkeypatch) -> None:
    """对抗：把 torch 从主进程彻底打掉，graph_to_code 仍能产代码（证明它绝不 import/实例化 torch）。

    种坏门：若 graph_to_code 偷偷 `import torch` 或实例化 nn.Module 跑形状校验，
    这里 torch=None 时它必 ImportError/AttributeError —— 本测试就抓住它（违反 M6）。
    """
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "torch.nn", None)
    code = graph_to_code(_linear_graph())  # torch 被打掉仍须成功
    assert isinstance(code, str) and "class GraphModel(nn.Module)" in code
    assert "nn.Linear(28, 256)" in code  # 纯整数形状推断，无需 torch
    assert "nn.Linear(256, 1)" in code   # head
    # M6 标注：编译/训练走子进程，主进程不碰 torch
    assert "主进程" in code and ("子进程" in code or "M6" in code)


def test_graph_codegen_endpoint_compiled_false(monkeypatch) -> None:
    """端点 graph 路径：返回 code + compiled=False（明示主进程只产字符串、未编译）。"""
    monkeypatch.setitem(sys.modules, "torch", None)
    r = client.post("/api/training/codegen", json={"graph": _linear_graph()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "graph" and body["compiled"] is False
    assert "nn.Module" in body["code"]


def test_graph_codegen_rejects_branching() -> None:
    """对抗：分支图（多出度）非线性链 → GraphCodegenError（子集 (a) 不接，残图不放行）。"""
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "features": 8},
            {"id": "n2", "type": "linear", "params": {"out": 4}},
            {"id": "n3", "type": "linear", "params": {"out": 4}},
            {"id": "n4", "type": "output"},
        ],
        "edges": [  # n1 出度=2（分叉）→ 非线性链
            {"from": {"node": "n1"}, "to": {"node": "n2"}},
            {"from": {"node": "n1"}, "to": {"node": "n3"}},
            {"from": {"node": "n2"}, "to": {"node": "n4"}},
        ],
    }
    with pytest.raises(GraphCodegenError):
        graph_to_code(graph)


def test_graph_codegen_rejects_missing_input_output() -> None:
    """缺 input/output 端 → GraphCodegenError（不放行残图）。"""
    graph = {
        "nodes": [
            {"id": "n1", "type": "linear", "params": {"out": 4}},
            {"id": "n2", "type": "linear", "params": {"out": 1}},
        ],
        "edges": [{"from": {"node": "n1"}, "to": {"node": "n2"}}],
    }
    with pytest.raises(GraphCodegenError):
        graph_to_code(graph)


def test_graph_codegen_rejects_unsupported_atom() -> None:
    """未支持原子（如自定义机制）→ GraphCodegenError（不静默吞、不假装能编）。"""
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "features": 8},
            {"id": "n2", "type": "factor_vae"},  # 子集 (a) 不支持
            {"id": "n3", "type": "output"},
        ],
        "edges": [
            {"from": {"node": "n1"}, "to": {"node": "n2"}},
            {"from": {"node": "n2"}, "to": {"node": "n3"}},
        ],
    }
    with pytest.raises(GraphCodegenError):
        graph_to_code(graph)


def test_graph_codegen_endpoint_bad_graph_400() -> None:
    """端点：非法图 → 400（GraphCodegenError 映射），不 500、不放行。"""
    bad = {"nodes": [{"id": "n1", "type": "linear", "params": {"out": 4}}], "edges": []}
    r = client.post("/api/training/codegen", json={"graph": bad})
    assert r.status_code == 400


def test_graph_codegen_conv_lstm_shape_inference(monkeypatch) -> None:
    """conv1d / lstm 形状推断为纯整数算术（断 torch 仍产正确层声明）。"""
    monkeypatch.setitem(sys.modules, "torch", None)
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "features": 16},
            {"id": "n2", "type": "conv1d", "params": {"out_channels": 32, "kernel_size": 3}},
            {"id": "n3", "type": "lstm", "params": {"hidden": 64}},
            {"id": "n4", "type": "head", "params": {"out": 1}},
            {"id": "n5", "type": "output"},
        ],
        "edges": [
            {"from": {"node": "n1"}, "to": {"node": "n2"}},
            {"from": {"node": "n2"}, "to": {"node": "n3"}},
            {"from": {"node": "n3"}, "to": {"node": "n4"}},
            {"from": {"node": "n4"}, "to": {"node": "n5"}},
        ],
    }
    code = graph_to_code(graph)
    assert "nn.Conv1d(16, 32, kernel_size=3" in code
    assert "nn.LSTM(32, 64, batch_first=True)" in code
    assert "nn.Linear(64, 1)" in code  # head 接 lstm 末步 hidden
