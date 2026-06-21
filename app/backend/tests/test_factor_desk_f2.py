"""F2 · 因子台后端接真 + 方法学治理对抗测试（决策 D-F2-AUDIT 全采纳+数值可调）。

真代码（非 mock）端点：
  POST /api/factors                          注册（必经三检查门 + 初始 NEW）
  POST /api/factors/validate                 构建台即时 IC 预览（编译/前视门）
  GET  /api/factors/correlation              拥挤度 Spearman 矩阵 + 去冗余
  GET  /api/factors/{id}/ic | /ic_decay      IC / Rank-IC / IC-IR（纳 Newey-West）/ 衰减
  GET  /api/factors/{id}/lifecycle/events    五态机事件日志
  POST /api/factors/{id}/audit               多证据三角审查（cscv_pbo/DSR/N_eff/bootstrap/IC-NW）
  POST /api/factors/{id}/layered_backtest    五分位分层回测

对抗（种已知坏门必抓，绝不假绿灯）：
  ① 注册绕生命周期门（前视/未编译/重名）必抓 → 422 携 gate 名。
  ② audit 单条红线下给正向结论必抓（缺 DSR/PBO/N_eff 任一即降级，绝不 consistent）。
  ③ IC 端点喂前视/未复权口径必抓（前视公式注册即被前视门拦，进不了 IC 端点）。
  ④ verdict / disclosure 含 R7 禁词（可信/安全/保证/可复现/排除过拟合/裸『组织独立』）必抓。
不破基线：correlation/validate/ic/audit/layered 正常路径返 200 + 合理结构。
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.auth import require_user_dependency
from app.factor_factory.factor_audit import (
    DEFAULT_THRESHOLDS,
    _build_checks,
    _verdict_from_checks,
    resolve_thresholds,
    run_factor_audit,
)
from app.factor_factory.ic import newey_west_tstat
from app.factor_factory.register_guard import (
    RegisterGateError,
    check_no_lookahead,
    precheck_register,
)
from app.factor_factory.registry import FactorRegistry
from app.main import FACTOR_REGISTRY, app

_BANNED = ("可信", "安全", "保证", "可复现", "排除过拟合")


@pytest.fixture
def client():
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="tester")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def _cleanup(*factor_ids: str) -> None:
    """测试落库的因子从注册表内存 + 落盘清掉（不污染真实 store）。"""
    for fid in factor_ids:
        keys = [k for k in list(FACTOR_REGISTRY._items) if k[0] == fid]  # noqa: SLF001
        for k in keys:
            FACTOR_REGISTRY._items.pop(k, None)  # noqa: SLF001
    FACTOR_REGISTRY._persist()  # noqa: SLF001


# ════════════════ 基线：正常路径 ════════════════
def test_register_valid_factor_initial_new(client):
    fid = "f2t_reg_ok"
    try:
        r = client.post("/api/factors", json={"factor_id": fid, "formula": "ts_zscore(close, 20)"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["registered"] is True
        assert body["lifecycle_state"] == "NEW"          # 红线：初始恒 NEW
        assert body["gates"]["compiled"] and body["gates"]["no_lookahead"]
        # 真落库：列表能查到
        r2 = client.get(f"/api/factors/{fid}")
        assert r2.status_code == 200 and r2.json()["formula"] == "ts_zscore(close, 20)"
    finally:
        _cleanup(fid)


def test_validate_ok_returns_ic(client):
    r = client.post("/api/factors/validate", json={"formula": "ts_mean(close, 5)", "market": "equity_cn"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True and body["stage"] == "ok"
    assert body["ic"] is not None and "ic_tstat_nw" in body["ic"]


def test_correlation_matrix_shape(client):
    r = client.get("/api/factors/correlation", params={"market": "equity_cn", "threshold": 0.5})
    assert r.status_code == 200, r.text
    body = r.json()
    n = len(body["factor_ids"])
    assert n >= 2
    assert len(body["matrix"]) == n and all(len(row) == n for row in body["matrix"])
    # 对角线为 1
    assert all(abs(body["matrix"][i][i] - 1.0) < 1e-9 for i in range(n))
    assert body["threshold"] == 0.5


def test_ic_and_decay_endpoints(client):
    fid = "f2t_ic"
    try:
        client.post("/api/factors", json={"factor_id": fid, "formula": "ts_zscore(close, 20)"})
        r = client.get(f"/api/factors/{fid}/ic", params={"market": "equity_cn", "horizon": 5})
        assert r.status_code == 200, r.text
        body = r.json()
        # Newey-West HAC t 必须在返回里（D-F2-AUDIT b）
        assert "ic_tstat_nw" in body and body["nw_lag"] == 4
        r2 = client.get(f"/api/factors/{fid}/ic_decay", params={"market": "equity_cn"})
        assert r2.status_code == 200
        decay = r2.json()["decay"]
        assert [d["horizon"] for d in decay] == [1, 3, 5, 10, 20]
    finally:
        _cleanup(fid)


def test_layered_backtest_buckets(client):
    fid = "f2t_layer"
    try:
        client.post("/api/factors", json={"factor_id": fid, "formula": "ts_zscore(close, 20)"})
        r = client.post(f"/api/factors/{fid}/layered_backtest", json={"n_quantiles": 5})
        assert r.status_code == 200, r.text
        body = r.json()
        # equity_cn 仅 4 symbol → 5 分位下调到 4，所有桶非空（无空桶伪精确）
        assert body["effective_quantiles"] == 4
        assert len(body["buckets"]) == 4
        assert all(b["n_obs"] > 0 for b in body["buckets"])
        assert "long_short_spread" in body
    finally:
        _cleanup(fid)


def test_lifecycle_events_endpoint(client):
    fid = "f2t_life"
    try:
        client.post("/api/factors", json={"factor_id": fid, "formula": "ts_mean(close, 10)"})
        r = client.get(f"/api/factors/{fid}/lifecycle/events")
        assert r.status_code == 200
        assert r.json()["events"] == []  # 新注册无迁移事件
    finally:
        _cleanup(fid)


def test_audit_normal_path_structure(client):
    fid = "f2t_audit"
    try:
        client.post("/api/factors", json={"factor_id": fid, "formula": "ts_zscore(close, 20)"})
        r = client.post(f"/api/factors/{fid}/audit", json={"tier": "standard"})
        assert r.status_code == 200, r.text
        body = r.json()
        # 多证据三角原语全在（cscv_pbo/DSR/N_eff/bootstrap/IC）
        assert "pbo" in body and "dsr" in body and "n_eff" in body
        assert "bootstrap_ci" in body and "ic" in body
        assert body["verdict"] in ("consistent", "concern", "blocked")
        assert isinstance(body["checks"], list) and len(body["checks"]) == 4
    finally:
        _cleanup(fid)


# ════════════════ 对抗①：注册绕生命周期门必抓 ════════════════
def test_adversarial_register_lookahead_blocked(client):
    """前视公式（负 shift = 未来函数）注册必被前视门拦（绝不裸写 registry）。"""
    fid = "f2t_la"
    r = client.post("/api/factors", json={"factor_id": fid, "formula": "ts_lag(close, -2)"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["gate"] == "lookahead"
    # 红线自证：真的没落库
    g = client.get(f"/api/factors/{fid}")
    assert g.status_code == 404
    _cleanup(fid)


def test_adversarial_register_uncompilable_blocked(client):
    """未编译表达式（未知算子）注册必被编译门拦。"""
    r = client.post("/api/factors", json={"factor_id": "f2t_bad", "formula": "totally_unknown_op(close)"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["gate"] == "compile"
    assert client.get("/api/factors/f2t_bad").status_code == 404
    _cleanup("f2t_bad")


def test_adversarial_register_duplicate_blocked(client):
    """重名注册（无 overwrite）必被无重名门拦。"""
    fid = "f2t_dup"
    try:
        r1 = client.post("/api/factors", json={"factor_id": fid, "formula": "ts_mean(close, 5)"})
        assert r1.status_code == 200
        r2 = client.post("/api/factors", json={"factor_id": fid, "formula": "ts_mean(close, 10)"})
        assert r2.status_code == 422 and r2.json()["detail"]["gate"] == "name"
    finally:
        _cleanup(fid)


def test_precheck_gate_unit_seeds_known_bad():
    """单测：三检查门对种下的已知坏门逐一命中（gate 名正确）。"""
    reg = FactorRegistry()
    # 前视
    with pytest.raises(RegisterGateError) as e1:
        precheck_register(reg, "x", "ts_delta(close, -3)")
    assert e1.value.gate == "lookahead"
    # 编译
    with pytest.raises(RegisterGateError) as e2:
        precheck_register(reg, "y", "no_such_op(close)")
    assert e2.value.gate == "compile"
    # 因果公式放行
    assert precheck_register(reg, "z", "ts_zscore(close, 20)").ok


# ════════════════ 对抗②：audit 单点红线下给正向结论必抓 ════════════════
@pytest.mark.parametrize("missing", ["dsr", "pbo", "ic_t"])
def test_adversarial_single_severe_redline_never_consistent(missing):
    """缺 DSR / PBO / IC-t 任一（严重证据）→ 绝不 consistent（多证据三角 D-F2-AUDIT c）。"""
    thr, _ = resolve_thresholds("standard")
    kwargs = dict(dsr=0.99, pbo=0.05, ic_t=5.0, n_eff_point=10, thr=thr)
    if missing == "dsr":
        kwargs["dsr"] = None
    elif missing == "pbo":
        kwargs["pbo"] = float("nan")
    else:
        kwargs["ic_t"] = None
    checks = _build_checks(**kwargs)
    verdict = _verdict_from_checks(checks)
    assert verdict != "consistent", f"单条红线({missing})缺失却给了 consistent —— 假绿灯"
    assert verdict in ("concern", "blocked")


def test_adversarial_two_severe_redlines_blocked():
    """两条严重证据同时缺失 → blocked（绝非 concern 蒙混）。"""
    thr, _ = resolve_thresholds("standard")
    checks = _build_checks(dsr=None, pbo=float("nan"), ic_t=5.0, n_eff_point=10, thr=thr)
    assert _verdict_from_checks(checks) == "blocked"


def test_adversarial_all_pass_consistent():
    """全达标才 consistent（正向基线，证明门不是恒降级摆设）。"""
    thr, _ = resolve_thresholds("standard")
    checks = _build_checks(dsr=0.99, pbo=0.05, ic_t=5.0, n_eff_point=10, thr=thr)
    assert _verdict_from_checks(checks) == "consistent"


def test_threshold_override_clamped_and_disclosed():
    """数值可调（D-F2-AUDIT §0.1）：越界覆盖被防呆夹回 + 计入披露（不静默放水）。"""
    eff, applied = resolve_thresholds("standard", {"min_dsr": 99.0, "max_pbo": -5.0})
    assert eff["min_dsr"] == 1.0 and eff["max_pbo"] == 0.0  # 夹回 [0,1]
    assert applied == {"min_dsr": 1.0, "max_pbo": 0.0}      # 披露被调字段


def test_audit_override_path_endpoint(client):
    """端点接受 tier + 阈值覆盖；覆盖计入 thresholds_overridden 披露。"""
    fid = "f2t_ovr"
    try:
        client.post("/api/factors", json={"factor_id": fid, "formula": "ts_zscore(close, 20)"})
        r = client.post(f"/api/factors/{fid}/audit", json={"tier": "lenient", "min_dsr": 0.5})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tier"] == "lenient"
        assert body["thresholds_overridden"].get("min_dsr") == 0.5
        # 调松不改通缩真相：DSR 原值仍在 body
        assert "dsr" in body
    finally:
        _cleanup(fid)


# ════════════════ 对抗③：IC 端点喂前视/未复权必抓 ════════════════
def test_adversarial_lookahead_formula_never_reaches_ic(client):
    """前视公式注册即被拦 → 永远进不了 IC 端点（端点不可能算到前视因子的 IC）。"""
    fid = "f2t_la_ic"
    r = client.post("/api/factors", json={"factor_id": fid, "formula": "ts_lag(close, -1)"})
    assert r.status_code == 422 and r.json()["detail"]["gate"] == "lookahead"
    assert client.get(f"/api/factors/{fid}/ic").status_code == 404  # 没这因子
    _cleanup(fid)


def test_validate_lookahead_rejected(client):
    """构建台即时预览：前视公式 valid=False stage=lookahead（绝不假绿灯放预览）。"""
    r = client.post("/api/factors/validate", json={"formula": "ts_delta(close, -5)"})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False and body["stage"] == "lookahead" and body["ic"] is None


def test_check_no_lookahead_catches_negative_shift():
    """单测：前视门对负 shift（未来函数）必命中，对因果 rolling 放行。"""
    ok, _ = check_no_lookahead("ts_zscore(close, 20)")
    assert ok is True
    bad, detail = check_no_lookahead("ts_lag(close, -3)")
    assert bad is False and "前视" in detail


def test_newey_west_more_conservative_than_naive():
    """NW t（重叠窗口自相关调整）对强正自相关序列应比朴素 t 更保守（|t| 更小）。"""
    # 构造强正自相关序列（AR(1) φ=0.8）→ 朴素 t 高估显著性。
    rng = np.random.default_rng(0)
    n = 200
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.8 * x[i - 1] + rng.standard_normal() * 0.1
    x = x + 0.05  # 给个正均值
    series = x.tolist()
    naive_t = (np.mean(x) / (np.std(x, ddof=1) / math.sqrt(n)))
    nw_t = newey_west_tstat(series, lag=10)
    assert nw_t is not None
    assert abs(nw_t) < abs(naive_t), "NW t 未比朴素 t 更保守 —— 自相关调整失效"


# ════════════════ 对抗④：verdict / disclosure 含禁词必抓 ════════════════
@pytest.mark.parametrize("tier", ["strict", "standard", "lenient"])
def test_adversarial_verdict_note_no_banned_words(tier):
    """裁决文案（verdict_note + disclosure）禁 R7 词；裸『组织独立』断言禁。"""
    report = run_factor_audit("x", "equity_cn", "ts_zscore(close, 20)", tier=tier)  # type: ignore[arg-type]
    for field in (report.verdict_note, report.disclosure):
        for w in _BANNED:
            assert w not in field, f"{tier}: 措辞禁词出现：{w} in {field!r}"
        # 允许『非组织独立』负向声明，禁裸『组织独立』正向断言
        assert "组织独立" not in field.replace("非组织独立", "")


def test_adversarial_verdict_note_endpoint_no_banned(client):
    """端点返回的 verdict_note/disclosure 同样禁词（守门贯穿到 HTTP 边界）。"""
    fid = "f2t_words"
    try:
        client.post("/api/factors", json={"factor_id": fid, "formula": "ts_zscore(close, 20)"})
        r = client.post(f"/api/factors/{fid}/audit", json={"tier": "standard"})
        assert r.status_code == 200
        body = r.json()
        for text in (body["verdict_note"], body["disclosure"]):
            for w in _BANNED:
                assert w not in text
            assert "组织独立" not in text.replace("非组织独立", "")
    finally:
        _cleanup(fid)


def test_banned_scanner_self_check():
    """守门有效性自证：若文案真含禁词，扫描必命中（防扫描器恒返空的摆设）。"""
    bad = "PBO 0.18 排除过拟合，结论可信安全有保证"
    hits = [w for w in _BANNED if w in bad]
    assert "排除过拟合" in hits and "可信" in hits and "安全" in hits and "保证" in hits


def test_default_thresholds_three_tiers_present():
    """三档阈值（谨慎/标准/宽松）齐全且单调（strict 比 lenient 严）。"""
    assert set(DEFAULT_THRESHOLDS) == {"strict", "standard", "lenient"}
    assert DEFAULT_THRESHOLDS["strict"]["min_dsr"] >= DEFAULT_THRESHOLDS["lenient"]["min_dsr"]
    assert DEFAULT_THRESHOLDS["strict"]["max_pbo"] <= DEFAULT_THRESHOLDS["lenient"]["max_pbo"]
    assert DEFAULT_THRESHOLDS["strict"]["min_ic_t"] >= DEFAULT_THRESHOLDS["lenient"]["min_ic_t"]
