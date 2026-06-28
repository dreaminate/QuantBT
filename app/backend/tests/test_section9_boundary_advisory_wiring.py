"""GOAL §9 边界验证器 · advisory-first 生产接线的对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

本波把三个原本**零生产 call-site** 的 §9 canonical 边界验证器接到真实 register/admit 路径：

  · validate_factor_library_entry → POST /api/factors        （模型本体塞进 Factor Library → 拒 / 因子数学缺 run_config 绑定 → 拒）
  · validate_factor_generator     → POST /api/factors/mine    （守门指标进生成 fitness / 生成器须命名独立 gatekeeper）
  · validate_strategy_book        → POST /api/strategy/submit_candidate（退役因子被新策略默认采用 → 拒；仅此 sub-criterion，余为 KNOWN_RUN_GAP）

接线是 **advisory-first**：裁决以 `boundary_verdict` 挂到产物响应，**违例不 raise、不拒请求**
（`enforced=False`）。强制是后续显式决策。

每个边界配：① 种一个已知违例 → 断言 `boundary_verdict` 抓住（ok=False + 精确 violation code）；
② clean case → ok=True；③ advisory 不变量 → 违例下请求仍成功（不被拒）。
精确 code 断言 + 输入翻转 ok 跟着翻 = 证明 verdict 真携带 validator 输出、不是常量门（不可被 no-op 蒙混）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.auth import require_user_dependency
from app.factor_factory import FactorRegistry
from app.main import app
from app.strategy.candidate_pool import CandidatePoolStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    """隔离 FACTOR_REGISTRY / CANDIDATE_POOL（fresh per test）+ 覆盖鉴权 + stub 派生 paper run。"""

    monkeypatch.setattr(app_main, "FACTOR_REGISTRY", FactorRegistry(tmp_path / "factors.json"))
    monkeypatch.setattr(app_main, "CANDIDATE_POOL", CandidatePoolStore(tmp_path))
    # submit_candidate 的派生动作（模拟台注册）与 §9 边界裁决正交：stub 掉以聚焦 boundary_verdict。
    monkeypatch.setattr(app_main, "_register_candidate_paper_run", lambda *a, **k: None)
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="tester", username="tester")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


# 一个能过 compile/lookahead/name 三门的合法表达式（基线已证）。
_VALID_FORMULA = "ts_zscore(close, 20)"


def _codes(verdict: dict) -> set[str]:
    return {v["code"] for v in verdict["violations"]}


# ══════════════ 边界 1 · validate_factor_library_entry → POST /api/factors ══════════════
def test_factor_library_entry_violation_flagged_advisory(client):
    """种坏门：因子带 mathematical_refs 却缺 theory/run_config 绑定 → boundary_verdict 必抓（但不拒注册）。"""

    r = client.post(
        "/api/factors",
        json={
            "factor_id": "s9_math_no_bind",
            "formula": _VALID_FORMULA,
            "mathematical_refs": ["math::sharpe_def"],
            # 故意不给 theory_binding_ref / run_config_binding_ref
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # advisory：违例下因子仍注册（不被拒）。
    assert body["registered"] is True
    bv = body["boundary_verdict"]
    assert bv["boundary"] == "factor_library_entry_§9"
    assert bv["advisory"] is True and bv["enforced"] is False
    # 门必须抓住，且是 validator 的精确 code（非泛化常量）。
    assert bv["ok"] is False
    assert "factor_math_without_run_binding" in _codes(bv)


def test_factor_library_entry_clean_passes(client):
    """clean：同样合法表达式、无悬空数学产物 → ok=True（输入翻转，ok 跟着翻 = 非常量门）。"""

    r = client.post(
        "/api/factors",
        json={"factor_id": "s9_clean", "formula": _VALID_FORMULA},
    )
    assert r.status_code == 200, r.text
    bv = r.json()["boundary_verdict"]
    assert bv["ok"] is True
    assert bv["violations"] == []


def test_factor_library_entry_math_with_bindings_passes(client):
    """clean：带 mathematical_refs 但**补齐** theory+run_config 绑定 → ok=True（同一坏门补绑定即转绿）。"""

    r = client.post(
        "/api/factors",
        json={
            "factor_id": "s9_math_bound",
            "formula": _VALID_FORMULA,
            "mathematical_refs": ["math::sharpe_def"],
            "theory_binding_ref": "theory::sharpe_v1",
            "run_config_binding_ref": "runcfg::sharpe_v1",
        },
    )
    assert r.status_code == 200, r.text
    bv = r.json()["boundary_verdict"]
    assert bv["ok"] is True
    assert "factor_math_without_run_binding" not in _codes(bv)


# ══════════════ 边界 2 · validate_factor_generator → POST /api/factors/mine ══════════════
_MINE_EXPRS = [
    {"expr": "rank(close/ts_mean(close,20))", "fam": "动量"},
    {"expr": "ts_corr(close,volume,20)", "fam": "量价"},
]


def test_factor_generator_missing_gatekeeper_flagged_advisory(client):
    """种坏门：生成器未命名独立 gatekeeper（clean sort_key 仍 200）→ boundary_verdict 抓 missing_gatekeeper_ref。"""

    r = client.post(
        "/api/factors/mine",
        json={"exprs": _MINE_EXPRS, "sort_key": "complexity"},  # 结构键，run_mining 不挡；无 gatekeeper_ref
    )
    assert r.status_code == 200, r.text
    body = r.json()
    bv = body["boundary_verdict"]
    assert bv["boundary"] == "factor_generator_§9"
    assert bv["advisory"] is True and bv["enforced"] is False
    assert bv["ok"] is False
    assert "missing_gatekeeper_ref" in _codes(bv)
    # 挖掘产物本身照常返回（advisory 不破坏既有 shape）。
    assert "candidates" in body and "gate" in body


def test_factor_generator_with_gatekeeper_passes(client):
    """clean：命名独立 gatekeeper_ref → ok=True（输入翻转，ok 跟着翻）。"""

    r = client.post(
        "/api/factors/mine",
        json={"exprs": _MINE_EXPRS, "sort_key": "complexity", "gatekeeper_ref": "gk::holdout_sharpe"},
    )
    assert r.status_code == 200, r.text
    bv = r.json()["boundary_verdict"]
    assert bv["ok"] is True
    assert "missing_gatekeeper_ref" not in _codes(bv)


def test_factor_generator_gate_metric_sort_key_still_hard_rejected(client):
    """回归护栏：守门指标作 sort_key 的**既有硬门**不被 advisory 接线削弱（仍 422 gate_leak）。"""

    r = client.post(
        "/api/factors/mine",
        json={"exprs": _MINE_EXPRS, "sort_key": "ic", "gatekeeper_ref": "gk::x"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["gate_leak"] is True


# ══════════════ 边界 3 · validate_strategy_book → POST /api/strategy/submit_candidate ══════════════
def _register_factor(state: str) -> str:
    """直接在 FACTOR_REGISTRY 注册一个因子并置生命周期态，返回 factor_id。"""

    factor = app_main.FACTOR_REGISTRY.register("s9_book_factor", "ts_mean(close,5)")
    app_main.FACTOR_REGISTRY.update_state(factor.factor_id, factor.version, state)
    return factor.factor_id


def _submit_candidate(client: TestClient, factor_set) -> dict:
    r = client.post(
        "/api/strategy/submit_candidate",
        json={
            "run_id": "cand_s9",
            "name": "cand_s9",
            "destination": "paper_desk",
            "factor_set": factor_set,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_strategy_book_retired_factor_default_adoption_flagged_advisory(client):
    """种坏门：候选（新策略）默认采用一个 RETIRED 注册因子 → boundary_verdict 抓 retired_factor_default_adoption。"""

    fid = _register_factor("RETIRED")
    body = _submit_candidate(client, [fid])
    # advisory：候选仍登记、仍止于 paper（不被拒）。
    assert body["status"] == "candidate" and body["stops_at"] == "paper_desk"
    bv = body["boundary_verdict"]
    assert bv["boundary"] == "strategy_book_§9"
    assert bv["advisory"] is True and bv["enforced"] is False
    assert bv["ok"] is False
    assert "retired_factor_default_adoption" in _codes(bv)
    assert fid in bv["resolved_factor_refs"]
    # 解析到了真实因子 → 这条边界确实被评估（evaluated），不是「没查」。
    assert bv["evaluated"] is True
    assert bv["unresolved_factor_refs"] == []


def test_strategy_book_qualified_factor_passes(client):
    """clean：候选采用 QUALIFIED 注册因子 → ok=True 且 evaluated=True（态从 RETIRED→QUALIFIED，ok 翻绿）。"""

    fid = _register_factor("QUALIFIED")
    body = _submit_candidate(client, [fid])
    bv = body["boundary_verdict"]
    assert bv["ok"] is True
    assert bv["evaluated"] is True
    assert "retired_factor_default_adoption" not in _codes(bv)
    assert fid in bv["resolved_factor_refs"]


def test_strategy_book_opaque_factor_set_id_is_not_evaluated_not_false_green(client):
    """诚实边界（RULES §3）：不透明 factor_set_id 解析不到成员 → evaluated=False、记 unresolved。

    ok=True 在此**只表「无可证伪退役采用」**而非「整本已查清」——消费方须看 evaluated，
    不得当干净通过（防假绿灯）。不造 missing_factor_contract 噪声。
    """

    body = _submit_candidate(client, "fs_opaque_setid_xyz")
    bv = body["boundary_verdict"]
    assert bv["evaluated"] is False  # 关键：没解析到成员 = 没查清，绝不渲染成 clean pass
    assert bv["unresolved_factor_refs"] == ["fs_opaque_setid_xyz"]
    assert bv["resolved_factor_refs"] == []
    assert _codes(bv) == set()  # 不解析就不造退役/缺契约的假违例
