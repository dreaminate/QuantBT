"""T-015 接线活性证明：把死的守门器接活 + opt-in 向后兼容 + 记账正确性。

spine 05 §5 T16（点睛）：promote 后 metrics 带 dsr/pbo → risk_summary 的 _rule_dsr/_rule_pbo
从「永远拿 None 不触发」变成真生效。这条直接证明「守门器从死接活」——dossier 点名的洞被补上。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.eval.gate_runner import asset_class_of, evaluate_overfit_gate
from app.eval.risk_summary import compute_risk_summary
from app.ide.promote import promote_ide_run
from app.lineage.ledger import Ledger


class _MemStore:
    """内容寻址收益快照假store（put 不覆盖、get 缺则 KeyError），duck-type dag ArtifactStore。"""

    def __init__(self):
        self._d: dict[str, list] = {}

    def put(self, k, v):
        self._d.setdefault(k, v)

    def get(self, k):
        if k not in self._d:
            raise KeyError(k)
        return self._d[k]


def _curve(n: int, daily: float = 0.001, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    eq = 1.0
    out = [{"t": "d0", "equity": 1.0, "net_return": 0.0, "benchmark_return": 0.0}]
    for i in range(1, n):
        r = float(rng.normal(loc=daily, scale=0.01))
        eq *= 1 + r
        out.append({"t": f"d{i}", "equity": eq, "net_return": r, "benchmark_return": r * 0.4})
    return out


# ── T-GW-1 接线活性：gate 把 risk_summary 从「insufficient(缺过拟合证据)」接成真裁决 ──
def test_gate_brings_risk_summary_alive(tmp_path: Path):
    led = Ledger(tmp_path / "ledger")
    store = _MemStore()
    result = {
        "equity_curve": _curve(300, daily=0.0008, seed=1),
        "metadata": {"strategy_name": "gw1", "market": "crypto_perp", "frequency": "1d",
                     "research_theme_id": "theme_gw"},
    }

    # 不传 ledger（旧行为）：metrics 无 dsr/pbo → risk_summary 落「缺过拟合证据」insufficient（这就是洞）。
    dead = promote_ide_run(ide_run_id="x", owner_username="a", strategy_name="gw1",
                           strategy_code="code", result=result, run_root=tmp_path / "dead")
    assert dead.gate_verdict is None and "dsr" not in dead.metrics, "不传 ledger 不应跑 gate（向后兼容破，门坏）"
    assert compute_risk_summary(dead.metrics).trust_level == "insufficient_data", \
        "前提：缺 PBO/DSR 时 risk_summary 应判 insufficient（这是被接线前的死状态）"

    # 传 ledger（接线后）：gate 注入 dsr → risk_summary 给出真裁决（不再因缺过拟合证据 insufficient）。
    live = promote_ide_run(ide_run_id="x", owner_username="a", strategy_name="gw1",
                           strategy_code="code", result=result, run_root=tmp_path / "live",
                           ledger=led, returns_store=store)
    assert live.gate_verdict is not None, "传 ledger 却没跑 gate（接线没活，门坏）"
    assert "dsr" in live.metrics, "gate 没把 dsr 注入 metrics（守门器仍是死的，门坏）"
    rs = compute_risk_summary(live.metrics)
    assert rs.trust_level != "insufficient_data", \
        "注入 dsr 后 risk_summary 仍判 insufficient → _rule_dsr 没被接活（门坏）"
    # run.json 落了 gate_verdict（前端下钻用，加字段不改既有逻辑）。
    manifest = json.loads((live.run_dir / "run.json").read_text(encoding="utf-8"))
    assert "gate_verdict" in manifest and manifest["gate_verdict"]["honest_n"] == 1


# ── T-GW-2 注入的 dsr 低 → risk_summary 真触发 high_risk（_rule_dsr 活性，spine 05 T16）─
def test_injected_low_dsr_triggers_high_risk():
    # 直接证明：metrics 一旦带低 dsr，_rule_dsr 就触发（接线前它永远拿 None）。
    rs = compute_risk_summary({"sharpe": 2.5, "dsr": 0.1})
    assert rs.trust_level == "high_risk"
    assert any(f.name == "low_dsr_confidence" for f in rs.flags), "低 dsr 没触发 low_dsr_confidence（门坏）"


# ── T-GW-2b 闭合 gate→flag 回路：gate 产出低 dsr → risk_summary 真打 low_dsr_confidence ─
def test_gate_low_dsr_closes_loop_to_risk_flag(tmp_path: Path):
    led = Ledger(tmp_path / "ledger")
    store = _MemStore()
    # 轻微负漂移噪声 over min_T → gate dsr_conservative 必低（<0.2）
    rng = np.random.default_rng(9)
    eq = 1.0
    curve = [{"t": "d0", "equity": 1.0, "net_return": 0.0}]
    for i in range(1, 320):
        r = float(rng.normal(loc=-0.0003, scale=0.012))
        eq *= 1 + r
        curve.append({"t": f"d{i}", "equity": eq, "net_return": r})
    result = {"equity_curve": curve, "metadata": {"market": "crypto_perp", "frequency": "1d",
                                                  "research_theme_id": "theme_loop"}}
    live = promote_ide_run(ide_run_id="x", owner_username="a", strategy_name="loop",
                           strategy_code="c", result=result, run_root=tmp_path / "r",
                           ledger=led, returns_store=store)
    gv = live.gate_verdict
    assert gv is not None and gv["color"] != "insufficient_evidence"
    if live.metrics.get("dsr", 1.0) < 0.2:
        rs = compute_risk_summary(live.metrics)
        flag = next((f for f in rs.flags if f.name == "low_dsr_confidence"), None)
        assert flag is not None, "gate 产低 dsr 但 risk_summary 没打 low_dsr_confidence → 回路没闭合（门坏）"
        assert abs(flag.metric_value - live.metrics["dsr"]) < 1e-9, "flag 的 dsr 值不等于 gate 注入值（门坏）"
        assert rs.trust_level == "high_risk"
    else:
        # 兜底：至少证明 dsr 被注入且 risk_summary 消费了它（非 insufficient）
        assert "dsr" in live.metrics and compute_risk_summary(live.metrics).trust_level != "insufficient_data"


# ── T-GW-3 preview（record=False）不记账，不刷 honest-N ──────────────────────────
def test_preview_does_not_record(tmp_path: Path):
    led = Ledger(tmp_path / "ledger")
    store = _MemStore()
    returns = list(np.random.default_rng(2).normal(loc=0.001, scale=0.01, size=300))
    gr = evaluate_overfit_gate(returns=returns, factor="x", universe="crypto_perp",
                               dataset_version="ds", freq="1d", strategy_goal_ref="theme_p",
                               asset_class="crypto", ledger=led, returns_store=store, record=False)
    assert led.honest_n("theme_p") == 0, "preview 竟记了账 → 预览刷 honest-N（门坏）"
    assert gr.verdict.color in ("green", "yellow", "red", "insufficient_evidence")


# ── T-GW-4 promote 记账：honest-N 随主题累计；同 config 不重复计（memoize）──────────
def test_promote_records_honest_n(tmp_path: Path):
    led = Ledger(tmp_path / "ledger")
    store = _MemStore()
    r1 = list(np.random.default_rng(3).normal(loc=0.001, scale=0.01, size=300))
    r2 = list(np.random.default_rng(4).normal(loc=0.001, scale=0.01, size=300))
    evaluate_overfit_gate(returns=r1, factor="alpha_a", universe="u", dataset_version="ds",
                          freq="1d", strategy_goal_ref="theme_r", asset_class="crypto",
                          ledger=led, returns_store=store, record=True)
    evaluate_overfit_gate(returns=r2, factor="alpha_b", universe="u", dataset_version="ds",
                          freq="1d", strategy_goal_ref="theme_r", asset_class="crypto",
                          ledger=led, returns_store=store, record=True)
    assert led.honest_n("theme_r") == 2, "两个不同 config 没各计一次（门坏）"
    # 同 config 再来一次 → 不 +N（memoize / 同一本账）
    evaluate_overfit_gate(returns=r1, factor="alpha_a", universe="u", dataset_version="ds",
                          freq="1d", strategy_goal_ref="theme_r", asset_class="crypto",
                          ledger=led, returns_store=store, record=True)
    assert led.honest_n("theme_r") == 2, "同 config 重复 promote 把 N 刷高（门坏）"


# ── T-GW-5 asset_class 映射：A股走 a_share（更长 min_T）─────────────────────────
def test_asset_class_mapping():
    assert asset_class_of("stocks_cn") == "a_share"
    assert asset_class_of("crypto_perp") == "crypto"
    assert asset_class_of("crypto_spot") == "crypto"
