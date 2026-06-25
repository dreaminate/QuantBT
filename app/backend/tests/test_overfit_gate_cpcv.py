"""CPCV 路径稳健性 q05 接进 overfit gate（report-only 默认 / cpcv_conservative opt-in）对抗测试。

门必抓（守 R2 单支不承重·护栏不替拍板）：
- **report_only（默认）绝不改裁决**：带 fragile CPCV 的 color 与不带逐位一致；只附 verdict.cpcv 报告。
- **cpcv_conservative 仅 green→yellow**（advisory 降级）；**绝不硬 red、绝不升级**。
- CPCV 缺/status≠ok → verdict.cpcv=None（不编造）。
"""

from __future__ import annotations

import numpy as np

from app.eval.n_eff import n_eff_from_matrix
from app.eval.overfit_gate import run_overfit_gate

FRAGILE = {"status": "ok", "metric": "r2", "baseline": 0.0, "q05": -0.12, "n_paths": 5}
ROBUST = {"status": "ok", "metric": "r2", "baseline": 0.0, "q05": 0.35, "n_paths": 5}


def _green(seed: int = 0):
    rng = np.random.default_rng(seed)
    t = 300
    strong = 0.006 + rng.standard_normal(t) * 0.003
    others = rng.standard_normal((t, 11)) * 0.01
    rm = np.column_stack([strong, others])
    return strong, rm, n_eff_from_matrix(rm)


def _red(seed: int = 0):
    rng = np.random.default_rng(seed)
    t = 300
    bad = -0.004 + rng.standard_normal(t) * 0.003          # 负漂移 → strong_neg → red
    rm = np.column_stack([bad, rng.standard_normal((t, 11)) * 0.01])
    return bad, rm, n_eff_from_matrix(rm)


def test_report_only_default_never_changes_verdict():
    """**默认 report_only**：带 fragile CPCV 的 color 与不带逐位一致（绝不改裁决·守不替拍板）；只附报告。"""
    arr, rm, neff = _green()
    base = run_overfit_gate(arr, n_eff=neff, returns_matrix=rm, honest_n=12)
    with_cpcv = run_overfit_gate(arr, n_eff=neff, returns_matrix=rm, honest_n=12, cpcv_distribution=FRAGILE)
    assert base.color == "green" and with_cpcv.color == "green"      # report_only 不动 green
    assert with_cpcv.cpcv is not None and with_cpcv.cpcv["fragile"] is True   # 报告已附
    assert "downgraded_green_to_yellow" not in with_cpcv.cpcv         # 但未降级
    assert base.cpcv is None                                          # 不传 CPCV → None（不编造）


def test_cpcv_conservative_fragile_downgrades_green_to_yellow():
    """**cpcv_conservative + 脆弱**：green→yellow（advisory 降级），cpcv.downgraded 标记。"""
    arr, rm, neff = _green()
    v = run_overfit_gate(arr, n_eff=neff, returns_matrix=rm, honest_n=12,
                         cpcv_distribution=FRAGILE, cpcv_policy="cpcv_conservative")
    assert v.color == "yellow" and v.cpcv["downgraded_green_to_yellow"] is True


def test_cpcv_conservative_robust_keeps_green():
    """cpcv_conservative + 稳健（q05≥基线）→ 不降级、green 保持。"""
    arr, rm, neff = _green()
    v = run_overfit_gate(arr, n_eff=neff, returns_matrix=rm, honest_n=12,
                         cpcv_distribution=ROBUST, cpcv_policy="cpcv_conservative")
    assert v.color == "green" and v.cpcv["fragile"] is False


def test_cpcv_conservative_never_reds_or_upgrades():
    """**绝不硬 red、绝不升级**（守 R2 单支不承重）：red 带 fragile CPCV 仍 red（CPCV 不创造 red）；
    yellow（缺 PBO）带 robust CPCV 仍 yellow（CPCV 不升级 green）。"""
    # red 场景：负漂移 → strong_neg red；fragile CPCV 不应把它「降」成别的、更不创造 red 之外的硬动作
    arr, rm, neff = _red()
    vr = run_overfit_gate(arr, n_eff=neff, returns_matrix=rm, honest_n=12,
                          cpcv_distribution=FRAGILE, cpcv_policy="cpcv_conservative")
    assert vr.color == "red"                              # CPCV 只在 green 降级；red 不动
    # yellow 场景：缺 returns_matrix → PBO None → yellow；robust CPCV 绝不升级成 green
    g_arr, _, _ = _green()
    neff_solo = n_eff_from_matrix(np.column_stack([g_arr, g_arr * 0 + 1e-9]))  # 占位 neff
    vy = run_overfit_gate(g_arr, n_eff=neff_solo, returns_matrix=None, honest_n=1,
                          cpcv_distribution=ROBUST, cpcv_policy="cpcv_conservative")
    assert vy.color == "yellow"                           # 缺 PBO → yellow；CPCV 不升级


def test_cpcv_absent_or_bad_status_none():
    """CPCV 缺 / status≠ok → verdict.cpcv=None（不编造）。"""
    arr, rm, neff = _green()
    assert run_overfit_gate(arr, n_eff=neff, returns_matrix=rm, honest_n=12).cpcv is None
    bad = run_overfit_gate(arr, n_eff=neff, returns_matrix=rm, honest_n=12,
                           cpcv_distribution={"status": "unsupported_task"}, cpcv_policy="cpcv_conservative")
    assert bad.cpcv is None and bad.color == "green"     # status≠ok 不接入、不降级


def test_gate_verdict_cpcv_json_safe():
    import json
    arr, rm, neff = _green()
    v = run_overfit_gate(arr, n_eff=neff, returns_matrix=rm, honest_n=12, cpcv_distribution=FRAGILE)
    json.dumps(v.to_dict())
