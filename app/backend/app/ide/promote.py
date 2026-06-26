"""把 IDE 沙箱 emit_result 提升为正式 Run，复用现有 RunDetail pipeline。

输入：IDE run 的 result.json（用户代码末尾 quantbt.emit_result({...}) 产出）
输出：runs/<new_run_id>/ 目录，含 run.json + portfolio.csv (+ trades.csv +
     strategy.py)，前端 /runs/<id> 三联图能直接读。

emit_result 协议（最小可识别字段）：
    {
      "equity_curve": [{"t": "2026-01-01", "equity": 1.0, "net_return": 0.0, "benchmark_return": 0.0?}, ...],
      "trades": [{"timestamp": ..., "symbol": ..., "side": ..., "quantity": ..., "price": ...}]?,
      "positions": [...]?,
      "metadata": {"strategy_name": ..., "market": "stocks_cn|crypto_perp|crypto_spot",
                   "frequency": "1d|1h|...", "benchmark": "000300.SH|BTC-USDT" }?,
    }

只有 equity_curve 是必需的；其它字段缺省由 metadata 默认值填或留空。
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

from ..paths import RUN_ROOT


class PromoteError(Exception):
    """IDE run 不满足 promote 条件（缺 equity_curve / 长度 < 2 / 数据非法）。"""


@dataclass(frozen=True)
class PromotedRun:
    run_id: str
    run_dir: Path
    metrics: dict[str, float]
    gate_verdict: dict | None = None   # T-015 多证据三角裁决（仅当传入 ledger 时有值）


_DEFAULT_METADATA = {
    "strategy_name": "IDE 策略",
    "market": "crypto_perp",
    "frequency": "1d",
    "benchmark": "BTC-USDT",
}


def promote_ide_run(
    *,
    ide_run_id: str,
    owner_username: str,
    strategy_name: str,
    strategy_code: str,
    result: dict[str, Any],
    record_name: str | None = None,
    run_root: Path = RUN_ROOT,
    ledger: Any = None,
    returns_store: Any = None,
    extra_metadata: dict[str, Any] | None = None,
    execution_blocks: list[dict[str, Any]] | None = None,
    registry: Any = None,
) -> PromotedRun:
    """把 IDE 沙箱结果落到 runs/<id>/，跑 metrics，返回新 run_id。

    raises PromoteError 当 result 不含可识别的 equity_curve。

    T-015 接线（**opt-in，向后兼容**）：传入 `ledger`（T-013 一本账）时跑多证据三角 gate，
    把 dsr/pbo/bootstrap 注入 metrics（让 risk_summary 守门规则从死接活）并把 gate_verdict 写进
    run.json。不传 → 行为与既有完全一致（不记账、不跑 gate）。

    M1 诚实接线（**opt-in，向后兼容**）：传入 `extra_metadata`（如 agent 组装的
    factor_set/model_id/signal_id/portfolio_id/cost_preset）时原样写进 run.json 的
    `assembly_inputs`——让组装意图可追溯、不被静默丢弃。不传 → 不写该键，行为与既有一致。

    §16 执行诚实接线（**opt-in，向后兼容**）：传入 `execution_blocks`（调用方按【真实执行诚实】
    构造的块字典：`mode`∈live/mock/fallback/template + `result_grade` + 诚实标识 mock_marked/
    live_source_ref/fallback_reason/note）时原样写进 run.json 的 `execution_blocks`，供
    `release_gate.promote_assembler` 组装→`evaluate_release` 的 Mock 诚实门核查（§16 致命
    「未注入资产却声称已采用 / template false success」在此被 R4/R5 抓）。不传 → 不写该键、
    行为与既有一致。本函数仅诚实【落数据】，绝不重造分类/判定（单一源 = mock_honesty + evaluate_release）。
    """

    equity_curve = result.get("equity_curve")
    if not isinstance(equity_curve, list) or len(equity_curve) < 2:
        raise PromoteError("emit_result 必须包含 equity_curve 数组（至少 2 个点）")

    rows = _normalize_equity_curve(equity_curve)
    if len(rows) < 2:
        raise PromoteError("equity_curve 解析后有效点不足 2 个")

    metadata = _merge_metadata(result.get("metadata"))
    run_id = _make_run_id(owner_username, strategy_name)
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_portfolio_csv(run_dir / "portfolio.csv", rows)
    trades = result.get("trades")
    if isinstance(trades, list) and trades:
        _write_trades_csv(run_dir / "trades.csv", trades)
    if strategy_code:
        (run_dir / "strategy.py").write_text(strategy_code, encoding="utf-8")

    metrics = _compute_metrics(rows)

    # —— T-015 多证据三角 gate（opt-in：仅当传入 ledger）——
    gate_verdict: dict | None = None
    if ledger is not None:
        gate_verdict = _run_overfit_gate(
            rows=rows, result=result, metadata=metadata, strategy_name=strategy_name,
            strategy_code=strategy_code, metrics=metrics, ledger=ledger, returns_store=returns_store,
            registry=registry,
        )

    manifest = {
        "run_id": run_id,
        "strategy_id": f"ide_{owner_username}",
        "strategy_name": strategy_name,
        "started_at": rows[0]["timestamp"],
        "status": "completed",
        "record_name": record_name or f"{strategy_name} · IDE 沙箱",
        "market": metadata["market"],
        "frequency": metadata["frequency"],
        "benchmark": metadata["benchmark"],
        "metrics": metrics,
        "source": {
            "kind": "ide_sandbox",
            "ide_run_id": ide_run_id,
            "owner_username": owner_username,
        },
    }
    if gate_verdict is not None:
        manifest["gate_verdict"] = gate_verdict
    # M1：落 agent 组装意图（factor_set/model_id/...）于 run.json，使其可追溯、不静默丢弃。
    if extra_metadata:
        manifest["assembly_inputs"] = dict(extra_metadata)
    # §16：落【真实执行诚实】块（live/mock/fallback/template + result_grade）于 run.json，让
    # release_gate.promote_assembler 组装→evaluate_release 能抓「未注入资产却声称已采用 / 模板基线
    # 冒充生产」。纯透传（与 assembly_inputs 同范式·不分类不判定）；不传 → 不写该键、行为不变。
    if execution_blocks:
        manifest["execution_blocks"] = [dict(b) for b in execution_blocks]

    # §16 advisory-first（中心接线·D-RELEASE-ADVISORY）：让已建 release gate（§16 八门聚合）
    # **真正在 promote 路径上跑**，把裁决落进 run.json 的 `release_verdict`——使每个 promoted run
    # 携带可追溯的发版门状态（ok + 缺口）。**只记录、绝不在此 reject 晋级**（是否硬卡晋级 = 后续
    # 显式 enforce 决策·守不预先削弱方法学也不破基线）。防御式：release 自检任何异常都不得破坏
    # promote 主流程（落账诚实标 available:False，不静默吞、不假绿灯）。
    try:
        from ..release_gate.promote_assembler import evaluate_run_releasable

        manifest["release_verdict"] = evaluate_run_releasable(manifest).to_dict()
    except Exception as exc:  # noqa: BLE001 — advisory 不得破坏 promote 主流程
        manifest["release_verdict"] = {
            "available": False,
            "error": f"release 自检未运行: {type(exc).__name__}",
        }

    (run_dir / "run.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return PromotedRun(run_id=run_id, run_dir=run_dir, metrics=metrics, gate_verdict=gate_verdict)


def _run_overfit_gate(
    *, rows, result, metadata, strategy_name, strategy_code, metrics, ledger, returns_store,
    registry=None,
) -> dict:
    """记账 + 跑三角 gate + 把 dsr/pbo/bootstrap 注入 metrics（就地改 metrics dict）。

    `registry`（B-PIT-CONFIRMATORY）：透传给 evaluate_overfit_gate 的 confirmatory 数据身份门
    （record=True 入账前校验 dataset_version 注册身份 + PIT）；None=不强制（向后兼容）。"""

    from ..eval.gate_runner import asset_class_of, evaluate_overfit_gate, freq_to_ppy

    meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    returns = [r["net_return"] or 0.0 for r in rows]
    theme = (meta.get("research_theme_id") or strategy_name)
    # CPCV 路径稳健性 q05 接进 promote 真实路径（done 卡 89e7be1e 的最后一公里）：
    # emit 携带 cpcv_distribution（模型 train 的 per-path 分布）则透传给 gate；缺则 None（不编造·行为不变）。
    # cpcv_policy 从 emit metadata 读（默认 report_only 只附报告绝不改裁决——守不替方法学拍板；用户显式
    # cpcv_conservative 才允许脆弱分布 green→yellow advisory）。非法值回落 report_only。
    cpcv_distribution = result.get("cpcv_distribution")
    if not isinstance(cpcv_distribution, dict):
        m_cpcv = meta.get("cpcv_distribution")
        cpcv_distribution = m_cpcv if isinstance(m_cpcv, dict) else None
    cpcv_policy = meta.get("cpcv_policy") or "report_only"
    if cpcv_policy not in ("report_only", "cpcv_conservative"):
        cpcv_policy = "report_only"
    gr = evaluate_overfit_gate(
        returns=returns,
        factor=meta.get("factor_formula") or (strategy_code[:2000] if strategy_code else strategy_name),
        params=meta.get("params") or {},
        universe=metadata["market"],
        dataset_version=str(meta.get("dataset_version") or "unknown"),
        freq=metadata["frequency"],
        label=str(meta.get("label") or "net_return"),
        strategy_goal_ref=str(theme),
        asset_class=asset_class_of(metadata["market"]),
        periods_per_year=freq_to_ppy(metadata["frequency"]),
        ledger=ledger,
        returns_store=returns_store,
        cpcv_distribution=cpcv_distribution,
        cpcv_policy=cpcv_policy,
        record=True,
        registry=registry,
    )
    v = gr.verdict
    # 注入 → risk_summary._rule_dsr/_rule_pbo 真生效（活性证明）。insufficient 时不注入误导单点。
    if v.color != "insufficient_evidence":
        metrics["dsr"] = v.dsr_conservative
        if v.pbo is not None:
            metrics["pbo"] = v.pbo
        metrics["bootstrap_sharpe_lower"] = v.bootstrap_ci[0]
    gv = v.to_dict()
    gv["honest_n"] = gr.honest_n
    gv["config_hash"] = gr.config_hash
    return gv


# -------- helpers --------


def _make_run_id(owner: str, name: str) -> str:
    safe_owner = "".join(ch for ch in owner if ch.isalnum())[:16] or "u"
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in "-_")[:24] or "s"
    return f"ide_{safe_owner}_{safe_name}_{token_urlsafe(4)}"


def _merge_metadata(meta: Any) -> dict[str, str]:
    out = dict(_DEFAULT_METADATA)
    if isinstance(meta, dict):
        for k in _DEFAULT_METADATA:
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
    return out


def _normalize_equity_curve(raw: list[Any]) -> list[dict[str, Any]]:
    """统一成 {timestamp, equity, net_return, benchmark_return, drawdown}。

    支持的输入点格式：
      {"t": ..., "equity": ...}
      {"timestamp": ..., "equity": ...}
      {"date": ..., "equity": ...}
      {"t": ..., "value": ...}
    """

    rows: list[dict[str, Any]] = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            continue
        ts = p.get("timestamp") or p.get("t") or p.get("date") or str(i)
        eq = p.get("equity")
        if eq is None:
            eq = p.get("value")
        try:
            eq_f = float(eq)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(eq_f):
            continue
        rows.append({
            "timestamp": str(ts),
            "equity": eq_f,
            "net_return": _safe_float(p.get("net_return")),
            "benchmark_return": _safe_float(p.get("benchmark_return")),
            "drawdown": _safe_float(p.get("drawdown")),
        })

    if not rows:
        return rows

    # 计算缺省 net_return
    for i in range(1, len(rows)):
        if rows[i]["net_return"] is None:
            prev = rows[i - 1]["equity"]
            if prev:
                rows[i]["net_return"] = rows[i]["equity"] / prev - 1.0
    if rows[0]["net_return"] is None:
        rows[0]["net_return"] = 0.0

    # drawdown
    peak = rows[0]["equity"]
    for r in rows:
        peak = max(peak, r["equity"])
        if r["drawdown"] is None and peak:
            r["drawdown"] = r["equity"] / peak - 1.0

    return rows


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _write_portfolio_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    cols = ["timestamp", "equity", "net_return", "benchmark_return", "drawdown"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})


def _write_trades_csv(path: Path, trades: list[Any]) -> None:
    cleaned = [t for t in trades if isinstance(t, dict)]
    if not cleaned:
        return
    cols: list[str] = []
    for t in cleaned:
        for k in t.keys():
            if k not in cols:
                cols.append(k)
    if "timestamp" not in cols and "t" in cols:
        cols.insert(0, "timestamp")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for t in cleaned:
            if "timestamp" not in t and "t" in t:
                t = {**t, "timestamp": t["t"]}
            w.writerow({k: ("" if t.get(k) is None else t.get(k)) for k in cols})


def _compute_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    """从 portfolio 序列计算 sharpe / sortino / max_dd / total_return / vol / alpha / beta。"""

    eq = [r["equity"] for r in rows]
    nr = [r["net_return"] or 0.0 for r in rows]
    br = [r["benchmark_return"] for r in rows]

    out: dict[str, float] = {}
    out["total_return"] = (eq[-1] / eq[0] - 1.0) if eq[0] else 0.0
    n = len(rows)
    if n > 1 and eq[0] > 0 and eq[-1] > 0:
        out["annualized_return"] = (eq[-1] / eq[0]) ** (252.0 / n) - 1.0
    out["trade_count"] = 0
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak:
            mdd = min(mdd, v / peak - 1.0)
    out["max_drawdown"] = mdd

    if len(nr) >= 2:
        sd = statistics.pstdev(nr)
        mu = statistics.mean(nr)
        out["volatility"] = sd * math.sqrt(252)
        out["sharpe"] = (mu / sd * math.sqrt(252)) if sd > 0 else 0.0
        downside = [x for x in nr if x < 0]
        if downside:
            dd = statistics.pstdev(downside)
            out["sortino"] = (mu / dd * math.sqrt(252)) if dd > 0 else 0.0
        else:
            out["sortino"] = 0.0

    valid_pairs = [(nr[i], br[i]) for i in range(n) if br[i] is not None]
    if len(valid_pairs) >= 5:
        sx = [p[1] for p in valid_pairs]
        sy = [p[0] for p in valid_pairs]
        mux, muy = statistics.mean(sx), statistics.mean(sy)
        cov = sum((sx[i] - mux) * (sy[i] - muy) for i in range(len(sx))) / len(sx)
        varx = sum((x - mux) ** 2 for x in sx) / len(sx)
        if varx > 0:
            beta = cov / varx
            alpha = (muy - beta * mux) * 252
            out["beta"] = beta
            out["alpha"] = alpha
        # information_ratio = mean(excess) / std(excess) * sqrt(252)
        ex = [sy[i] - sx[i] for i in range(len(sx))]
        if len(ex) >= 2:
            ed = statistics.pstdev(ex)
            em = statistics.mean(ex)
            out["information_ratio"] = (em / ed * math.sqrt(252)) if ed > 0 else 0.0
            bvol = statistics.pstdev(sx) * math.sqrt(252) if len(sx) >= 2 else 0.0
            out["benchmark_volatility"] = bvol
        # 基准累计收益
        w = 1.0
        for x in sx:
            w *= 1.0 + x
        out["benchmark_return"] = w - 1.0

    return out


__all__ = ["PromoteError", "PromotedRun", "promote_ide_run"]
