"""S2 策略台后端接线 · 对抗测试。

覆盖（含「种已知坏门必抓」）：
- validate：种坏图（exec 绕 Final Risk Gate / compat=bad / 必填未连）必报；好图必过。
- fork / 版本身份：必须锚 lineage/ids.py（content_hash）单一源——种「不锚」必抓。
- live_snapshot：A股 live 永拒；任何下单参数/路径不得出现（无绕 OrderGuard 新路径）。
- HTTP 层（TestClient + auth override）：4 端点 owner 隔离 + 坏图 422/200 行为。
"""

from __future__ import annotations

import inspect
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
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester", username="tester",
    )
    try:
        yield TestClient(main.app), isolated
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


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
