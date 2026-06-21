"""R2 裁决卡后端投影层（RunVerdictCard 接真）。

把 run 级别的 **验证官三态裁决** / **过拟合三角门** / **成本敏感性** / **月度热力** 投影成
RunVerdictCard.tsx 数据契约的形状。不重造任何评估逻辑——全部复用现有单一源：
  - 三态 verdict：verification/store.py VerdictStore + schema.VerdictRecord.to_review()
  - verdict note：verification/verifier.py Verifier._verdict_note（措辞守门：禁可信/安全/排除过拟合）
  - 过拟合门：eval/overfit_gate.py run_overfit_gate（PBO/DSR/honest-N/GateVerdict）
  - n_eff：eval/n_eff.py n_eff_from_matrix
  - 资产类/年化频率：eval/gate_runner.py asset_class_of / freq_to_ppy

红线（落地硬约束，由对抗测试把守）：
  ① verdict 锁死三态 consistent/concern/blocked（verification/schema.py）——
     **绝不**把 overfit_gate.GateVerdict 的「晋级候选」当 verdict 三态枚举（两条管线）。
  ② verdictNote 一律由 Verifier._verdict_note 供给（一致/存疑/不一致 + 适用域 + 未验证项），
     **禁** 可信/安全/保证/排除过拟合/可复现/组织独立（R7）。无裁决时 note 也走守门措辞，不杜撰。
  ③ 未验证 ≠ 已验证：run 没有权威 verdict_id → 投影成 concern（不假绿灯，未验证不当 pass）。
  ④ promote 是写动作 → 永远经审批门（approver≠creator，INV-5），本模块只投影、不绕门。
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

from .eval.gate_runner import asset_class_of, freq_to_ppy
from .eval.n_eff import n_eff_from_matrix
from .eval.overfit_gate import run_overfit_gate
from .run_detail_core import load_run
from .verification.schema import DISCLOSURE
from .verification.verifier import Verifier

# GateVerdict.color → 设计稿「晋级候选/…」展示文案。这是【过拟合门】另一条管线的标签，
# 绝不与验证官三态混用（UI 上 verdictLabel ≠ verdict pill）。
_GATE_LABEL = {
    "green": "晋级候选",
    "yellow": "证据分歧",
    "red": "证据强负",
    "insufficient_evidence": "证据不足",
}

# 成本敏感性 3 预设（P0 派生）：单边成本档（bp），从 neutral 基准对 Sharpe/超额做确定性折让。
# 这是【展示性区间】而非新回测——pessimistic 高亮抗「乐观参数选择」（GOAL §6 L3）。
COST_PRESETS: dict[str, float] = {
    "optimistic": 8.0,
    "neutral": 18.0,
    "pessimistic": 35.0,
}
_COST_BASE_PRESET = "neutral"


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _portfolio_series(run) -> tuple[list[float], list[float], list[str]]:
    """从 portfolio.csv 取 equity / benchmark 累计净值 / 时间戳。

    benchmark 列存的是逐期收益 → 累乘成净值（与策略 equity 同基 1.0 对齐）。
    """

    pf = run.portfolio
    if pf is None or pf.height == 0:
        return [], [], []
    cols = pf.columns
    rows = pf.to_dicts()
    equity: list[float] = []
    bench: list[float] = []
    ts: list[str] = []
    bench_cum = 1.0
    has_bench = "benchmark_return" in cols
    for r in rows:
        eq = r.get("equity")
        if eq is None:
            continue
        equity.append(_safe_float(eq, 1.0))
        if has_bench:
            bench_cum *= 1.0 + _safe_float(r.get("benchmark_return"), 0.0)
        bench.append(bench_cum)
        ts.append(str(r.get("timestamp") or r.get("date") or ""))
    return equity, bench, ts


def _net_returns(run) -> list[float]:
    pf = run.portfolio
    if pf is None or pf.height == 0:
        return []
    if "net_return" in pf.columns:
        return [_safe_float(v, 0.0) for v in pf["net_return"].to_list()]
    # 无 net_return 列 → 从 equity 派生逐期收益。
    eq = [_safe_float(v, 1.0) for v in pf["equity"].to_list()] if "equity" in pf.columns else []
    out: list[float] = []
    for i in range(1, len(eq)):
        prev = eq[i - 1]
        out.append(eq[i] / prev - 1.0 if prev else 0.0)
    return out


def _metrics(run) -> dict[str, Any]:
    m: dict[str, Any] = {}
    m.update(run.manifest.get("metrics") or {})
    return m


def _verdict_note_for(verifier: Verifier, verdict: str) -> str:
    """无逐项对账可用时，仍由 Verifier._verdict_note 产合规 note（措辞守门单一源）。

    传空 checks + 未确立独立性的 Independence → note 走「存疑/不一致」式表述，
    绝不前端杜撰「排除过拟合/可信」。
    """

    from .verification.schema import Independence

    ind = Independence(False, False, False, 0, False,
                       "独立性未确立：本投影无异模型对账记录（未验证不当 pass）。")
    return verifier._verdict_note(verdict, [], ind)  # noqa: SLF001  单一措辞源，刻意复用


def project_verdict(run_id: str, *, verdict_store: Any, verifier: Verifier) -> dict[str, Any]:
    """GET /api/runs/{id}/verdict 的投影。

    优先读 run.json 里绑定的权威 verdict_id（verification_record_id / verdict_id）→ to_review()。
    未绑定 → concern（未验证 ≠ 已验证，不假绿灯），note 仍走守门措辞。
    篡改（VerdictTamperError）→ fail-closed 投影成 concern + 诚实标注（绝不返脏数据）。
    """

    run = load_run(run_id)
    manifest = run.manifest
    vid = manifest.get("verification_record_id") or manifest.get("verdict_id")

    review: dict[str, Any] | None = None
    tamper = False
    if vid:
        try:
            rec = verdict_store.record_for(vid)
        except Exception:  # noqa: BLE001  篡改/读失败一律 fail-closed（绝不返脏数据，绝不 500）
            rec = None
            tamper = True
        if rec is not None:
            review = rec.to_review()

    if review is not None:
        verdict = review["verdict"]
        note = review.get("notes") or _verdict_note_for(verifier, verdict)
        disclosure = review.get("disclosure") or DISCLOSURE
        verdict_id_out = review.get("verdict_id")
        target_ref = review.get("target_ref")
        consistency_check = review.get("consistency_check") or []
        independence = review.get("independence") or {}
    else:
        # 未验证 / 篡改 → concern（不当 pass）。note + disclosure 仍合规。
        verdict = "concern"
        if tamper:
            note = ("验证记录不可信（读失败/被篡改）：fail-closed 投影为存疑，不予当 pass；"
                    + _verdict_note_for(verifier, "concern"))
        else:
            note = ("本 run 尚无权威异模型裁决记录（未验证 ≠ 已验证）；"
                    + _verdict_note_for(verifier, "concern"))
        disclosure = DISCLOSURE
        verdict_id_out = None
        target_ref = manifest.get("config_hash")
        consistency_check = []
        independence = {}

    return {
        "run_id": run_id,
        "verdict": verdict,                 # 三态：consistent/concern/blocked（前端 pill 取此）
        "verdict_id": verdict_id_out,
        "target_ref": target_ref,
        "has_authoritative_verdict": review is not None,
        "verdictNote": note,                # 措辞守门：由 Verifier._verdict_note 供给
        "disclosure": disclosure,
        "consistency_check": consistency_check,
        "independence": independence,
    }


def _build_overfit(run) -> Any:
    """跑 run 级过拟合门（PBO/DSR/honest-N/三角）。无同主题历史矩阵时退化单列 n_eff。"""

    import numpy as np

    returns = _net_returns(run)
    manifest = run.manifest
    market = manifest.get("market")
    freq = manifest.get("frequency") or "1d"
    arr = np.asarray(returns, dtype=float).reshape(-1, 1) if returns else np.zeros((0, 1))
    neff = n_eff_from_matrix(arr)
    gate = run_overfit_gate(
        returns,
        n_eff=neff,
        honest_n=None,
        returns_matrix=None,                # run 级单点投影：无同主题矩阵 → PBO=None → 至多 yellow
        asset_class=asset_class_of(market),
        periods_per_year=freq_to_ppy(freq),
    )
    return gate


def project_overfit(run_id: str) -> dict[str, Any]:
    """GET /api/runs/{id}/overfit 的投影：GateVerdict.to_dict() + 派生展示标签。

    verdictLabel 来自 GateVerdict.color（晋级候选/证据分歧/…）——【过拟合门】管线标签，
    **与验证官三态 verdict 是两个枚举**，前端不可混用。
    """

    run = load_run(run_id)
    gate = _build_overfit(run)
    d = gate.to_dict()
    d["run_id"] = run_id
    # 派生展示标签：明确归属过拟合门（非验证官 verdict）。
    d["gate_label"] = _GATE_LABEL.get(gate.color, gate.color)
    d["is_promotion_candidate"] = gate.color == "green"
    return d


def project_cost_sensitivity(run_id: str, preset: str | None = None) -> dict[str, Any]:
    """GET /api/runs/{id}/cost-sensitivity?preset=（P0 派生）。

    3 预设各给 (sharpe, excess)：从 neutral 基准按单边成本档做确定性折让。
    这是展示性区间（非新回测）——诚实标 derived=True，pessimistic 高亮（抗乐观参数选择）。
    preset 给定 → 只返该预设；缺省 → 返三预设。
    """

    run = load_run(run_id)
    m = _metrics(run)
    base_sharpe = _safe_float(m.get("sharpe"), 0.0)
    # 基准超额：年化超额优先；缺则用 information_ratio*vol 近似不靠谱 → 退化 annualized_return。
    base_excess = _safe_float(
        m.get("excess_return")
        if m.get("excess_return") is not None
        else m.get("annualized_return"),
        0.0,
    )
    base_cost = COST_PRESETS[_COST_BASE_PRESET]

    def _cell(name: str) -> dict[str, Any]:
        cost_bp = COST_PRESETS[name]
        # 成本越高 → Sharpe/超额越低。确定性线性折让（每多 1bp 单边成本年化约扣 turnover*成本）。
        # P0 派生用保守斜率：以基准为锚，按成本相对差缩放（neutral=1.0）。
        if base_cost > 0:
            haircut = (cost_bp - base_cost) / base_cost
        else:
            haircut = 0.0
        sharpe = base_sharpe * (1.0 - 0.18 * haircut)
        excess = base_excess - 0.02 * haircut  # 每档差约 2pct 年化超额折让
        return {"preset": name, "sharpe": round(sharpe, 4), "excess": round(excess, 4)}

    names = [preset] if (preset and preset in COST_PRESETS) else list(COST_PRESETS)
    cells = [_cell(n) for n in names]
    return {
        "run_id": run_id,
        "derived": True,                    # 诚实：P0 派生，非独立重跑回测
        "base_preset": _COST_BASE_PRESET,
        "cost_presets_bp": COST_PRESETS,
        "cost": cells,
        "note": ("成本敏感性为 neutral 基准的确定性派生区间（非独立重跑回测）；"
                 "pessimistic 档用于抗乐观参数选择，决策应以保守端为准。"),
    }


def project_monthly_heatmap(run_id: str) -> dict[str, Any]:
    """月度（超额）收益热力聚合：把逐期 net_return 按 年-月 累乘成月度收益。

    真聚合（非前端 seed 造数）：有 benchmark 则聚月度超额，否则聚月度净收益（诚实标 metric）。
    """

    run = load_run(run_id)
    pf = run.portfolio
    if pf is None or pf.height == 0:
        return {"run_id": run_id, "metric": "none", "available": False, "rows": []}

    has_bench = "benchmark_return" in pf.columns
    metric = "excess" if has_bench else "net"
    # 逐期收益按 年-月 真聚合（_heatmap_rows 分策略/基准两轨累乘，有基准则取月度超额）。
    rows = _heatmap_rows(pf, has_bench)
    return {
        "run_id": run_id,
        "metric": metric,                   # excess（有基准）/ net（无基准）
        "available": bool(rows),
        "rows": rows,
        "note": ("月度热力为逐期收益按年-月真聚合（非造数）；"
                 + ("有基准 → 月度超额。" if has_bench else "无基准 → 月度净收益。")),
    }


def _heatmap_rows(pf, has_bench: bool) -> list[dict[str, Any]]:
    strat: "OrderedDict[tuple[int, int], float]" = OrderedDict()
    bench: "OrderedDict[tuple[int, int], float]" = OrderedDict()
    for r in pf.to_dicts():
        ym = _parse_year_month(str(r.get("timestamp") or r.get("date") or ""))
        if ym is None:
            continue
        strat[ym] = strat.get(ym, 1.0) * (1.0 + _safe_float(r.get("net_return"), 0.0))
        if has_bench:
            bench[ym] = bench.get(ym, 1.0) * (1.0 + _safe_float(r.get("benchmark_return"), 0.0))
    if not strat:
        return []
    years = sorted({y for (y, _m) in strat})
    rows: list[dict[str, Any]] = []
    for y in years:
        cells: list[dict[str, Any]] = []
        for mo in range(1, 13):
            key = (y, mo)
            if key not in strat:
                cells.append({"month": mo, "value": None})
                continue
            s = strat[key] - 1.0
            if has_bench:
                b = bench.get(key, 1.0) - 1.0
                v = (1.0 + s) / (1.0 + b) - 1.0
            else:
                v = s
            cells.append({"month": mo, "value": round(v, 6)})
        rows.append({"year": y, "cells": cells})
    return rows


def _parse_year_month(ts: str) -> tuple[int, int] | None:
    s = (ts or "").strip()
    if len(s) < 7:
        return None
    try:
        y = int(s[0:4])
        mo = int(s[5:7])
    except ValueError:
        return None
    if not (1 <= mo <= 12):
        return None
    return (y, mo)


__all__ = [
    "COST_PRESETS",
    "project_verdict",
    "project_overfit",
    "project_cost_sensitivity",
    "project_monthly_heatmap",
]
