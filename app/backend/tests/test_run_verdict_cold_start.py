"""R27 冷启动证据充分性接进 run /overfit 投影 对抗测试（价值闭环：MinTRL→裁决输出）。

门必抓：
- 短业绩期 ok+n<⌈MinTRL⌉ → sufficient=False「证据不足」（**绝不**渲染成达标）。
- N 太小估不出 Sharpe → insufficient + DSR **不适用**（R27：N=1 DSR 退化 PSR=范畴误用）。
- SR 不超基准 → never_significant。措辞守门：note 无 可信/安全/通过/排除过拟合。
- /overfit 投影含 cold_start 字段（additive），且不改 gate.color/三态裁决（呈现层不动治理）。
- JSON-safe：inf/nan → null。
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pytest

from app.run_verdict import _cold_start_evidence, project_overfit

# R7 裁决措辞红线全集（与 verification DISCLOSURE / test_run_verdict_card._BANNED_WORDS 同口径）+ 冷启动特有「通过」。
# 评审纠偏：原集漏 保证/可复现/组织独立（红线子集=纸糊门）→ 补全，与 run_verdict._BANNED_VERDICT_WORDS 对齐。
_BANNED = ("可信", "安全", "保证", "可复现", "组织独立", "排除过拟合", "通过")


def _series_with_sr(n: int, sr_pp: float, seed: int = 0) -> list[float]:
    """长度 n、精确每期 Sharpe=sr_pp 的近正态序列（去 seed 依赖）。"""
    z = np.random.default_rng(seed).standard_normal(n)
    z = (z - z.mean()) / z.std(ddof=1)
    return (z * 0.01 + sr_pp * 0.01).tolist()


def test_cold_start_short_ok_is_insufficient_not_green():
    """ok + 短业绩期（n<⌈MinTRL⌉）→ sufficient=False「证据不足」，绝不渲染达标。"""
    c = _cold_start_evidence(_series_with_sr(40, 0.05))   # sr_pp=0.05 → MinTRL≈1083 ≫ 40
    assert c["min_trl_status"] == "ok" and c["sufficient"] is False
    assert c["min_trl_obs"] > c["n_observed"] and "证据不足" in c["note"]
    assert c["dsr_applicable"] is True                    # 能估 Sharpe（仅 N 太小才 N/A）


def test_cold_start_long_sufficient():
    c = _cold_start_evidence(_series_with_sr(400, 0.3))    # sr_pp=0.3 → MinTRL≈31 ≪ 400
    assert c["min_trl_status"] == "ok" and c["sufficient"] is True
    assert c["n_observed"] >= c["min_trl_obs"]


def test_cold_start_tiny_n_dsr_not_applicable_r27():
    """N=1/2 → insufficient + dsr_applicable=False（R27：N=1 DSR 退化 PSR=范畴误用）。"""
    for rets in ([0.01], [0.01, 0.02]):
        c = _cold_start_evidence(rets)
        assert c["min_trl_status"] == "insufficient" and c["dsr_applicable"] is False
        assert c["sufficient"] is False and c["min_trl_obs"] is None


def test_cold_start_never_significant_when_no_edge():
    c = _cold_start_evidence((np.random.default_rng(1).standard_normal(200) * 0.01 - 0.002).tolist())
    assert c["min_trl_status"] == "never_significant" and not c["sufficient"]
    assert c["min_trl_obs"] is None and c["dsr_applicable"] is False


def test_cold_start_note_never_contains_banned_words():
    """措辞守门：冷启动 note 绝不含 可信/安全/通过/排除过拟合（同验证官措辞红线）。

    **门有牙·显式覆盖全 4 状态分支**（评审/mutation 教训：必行权产 note 的每条分支，尤其 ok+sufficient——
    那是唯一可能被写成「可信/已排除过拟合」的分支；种该禁词 mutation 必被本测抓）。
    """
    cases = {
        "insufficient": [0.01],                                  # N<3
        "ok_short": _series_with_sr(40, 0.05),                   # ok + 短 → 证据不足
        "ok_sufficient": _series_with_sr(400, 0.3),              # ok + 长 → 达标（禁词高危分支）
        "never_significant": (np.random.default_rng(2).standard_normal(100) * 0.01 - 0.003).tolist(),
    }
    seen_status: set[str] = set()
    for label, rets in cases.items():
        c = _cold_start_evidence(rets)
        seen_status.add("ok_sufficient" if (c["min_trl_status"] == "ok" and c["sufficient"])
                        else "ok_short" if c["min_trl_status"] == "ok"
                        else c["min_trl_status"])
        for b in _BANNED:
            assert b not in c["note"], f"[{label}] cold_start note 含禁词 {b}：{c['note']}"
    # 覆盖断言：4 条确实命中 4 个不同状态（含 ok+sufficient 高危分支）——否则禁词扫描可能漏行权该分支。
    assert {"insufficient", "ok_short", "ok_sufficient", "never_significant"} <= seen_status, \
        f"未覆盖全部状态分支，禁词守门可能漏判别路径：{seen_status}"
    # Sentinel（门有牙）：禁词检查本身是真判别器——带禁词的串必被检出。
    assert any(b in "业绩期 N=400：可信，已排除过拟合" for b in _BANNED), "禁词集失效=守门无牙"


def test_cold_start_banned_set_covers_r7_redline_no_drift():
    """评审纠偏：生产 runtime 守门集 ⊇ R7 红线全集；测试集 == 生产集（单一口径、不漂，绝非红线子集=纸糊门）。"""
    from app.run_verdict import _BANNED_VERDICT_WORDS

    r7_redline = {"可信", "安全", "保证", "可复现", "组织独立", "排除过拟合"}
    assert r7_redline <= set(_BANNED_VERDICT_WORDS), "生产守门集漏 R7 红线词（纸糊门）"
    assert set(_BANNED) == set(_BANNED_VERDICT_WORDS), "测试禁词集 ≠ 生产集（双份漂移风险）"


def test_cold_start_is_json_safe():
    """inf/nan → null：never_significant/insufficient 的 min_trl_obs 必 None、可 JSON 序列化。"""
    c = _cold_start_evidence([0.01])
    assert c["min_trl_obs"] is None
    json.dumps(c)   # 不抛 = JSON-safe


# ===========================================================================
# 集成：/overfit 投影含 cold_start（additive，不动 gate verdict）
# ===========================================================================


def _write_run(root, run_id, net_returns):
    rd = root / run_id
    rd.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "strategy_name": "冷启动测试", "strategy_id": "s_cs",
                "status": "completed", "market": "crypto_perp", "frequency": "1d",
                "benchmark": "BTC-USDT", "metrics": {"sharpe": 0.5}, "config_hash": "cfg_cs"}
    (rd / "run.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    lines = ["timestamp,equity,net_return,benchmark_return,drawdown"]
    eq, d0 = 1.0, dt.date(2020, 1, 1)
    for i, nr in enumerate(net_returns):
        eq *= 1.0 + nr
        lines.append(f"{(d0 + dt.timedelta(days=i)).isoformat()},{eq:.6f},{nr:.6f},0.0004,0.0")
    (rd / "portfolio.csv").write_text("\n".join(lines), encoding="utf-8")
    return rd


def test_overfit_projection_includes_cold_start(tmp_path, monkeypatch):
    """/overfit 投影 additive 含 cold_start，且保留原 gate 字段（呈现层不动治理）。"""
    from app import run_detail_core

    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setattr(run_detail_core, "RUN_ROOT", root)
    _write_run(root, "run_cs", _series_with_sr(40, 0.05))   # 短 ok → 证据不足
    d = project_overfit("run_cs")
    assert "cold_start" in d
    cs = d["cold_start"]
    assert set(cs) >= {"n_observed", "psr", "min_trl_obs", "min_trl_status", "sufficient",
                       "dsr_applicable", "axis", "confidence", "note"}
    assert cs["axis"] == "track_record_length"   # 与过拟合门样本充分性轴区分（防两「证据不足」混读）
    assert cs["n_observed"] == 40 and cs["sufficient"] is False    # 短 → 证据不足
    # 不动治理：原 gate 字段仍在（gate_label/is_promotion_candidate 来自过拟合门管线）
    assert "gate_label" in d and "is_promotion_candidate" in d
    json.dumps(d)   # 整个投影 JSON-safe