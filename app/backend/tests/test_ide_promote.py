"""v0.8.3 · IDE 沙箱 result.json → 正式 Run promote 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ide.ai_context import build_ai_context
from app.ide.promote import PromoteError, promote_ide_run


# ============================================================
# promote_ide_run
# ============================================================


def _curve(n: int, start: float = 1.0, daily: float = 0.001) -> list[dict]:
    eq = start
    out = []
    for i in range(n):
        if i > 0:
            eq *= 1 + daily
        out.append({"t": f"2026-01-{i + 1:02d}", "equity": round(eq, 6), "net_return": daily if i > 0 else 0.0, "benchmark_return": daily * 0.5})
    return out


def test_promote_basic(tmp_path: Path):
    result = {
        "equity_curve": _curve(60),
        "metadata": {"strategy_name": "test_v1", "market": "crypto_perp", "frequency": "1d", "benchmark": "BTC-USDT"},
    }
    promoted = promote_ide_run(
        ide_run_id="ide_xx",
        owner_username="alice",
        strategy_name="test_v1",
        strategy_code="quantbt.emit_result({})",
        result=result,
        run_root=tmp_path,
    )
    assert promoted.run_id.startswith("ide_alice_")
    assert (promoted.run_dir / "run.json").exists()
    assert (promoted.run_dir / "portfolio.csv").exists()
    assert (promoted.run_dir / "strategy.py").exists()
    manifest = json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["strategy_name"] == "test_v1"
    assert manifest["market"] == "crypto_perp"
    assert manifest["source"]["kind"] == "ide_sandbox"
    assert manifest["metrics"]["total_return"] > 0
    assert manifest["metrics"]["sharpe"] != 0


def test_promote_rejects_missing_curve(tmp_path: Path):
    with pytest.raises(PromoteError):
        promote_ide_run(
            ide_run_id="x", owner_username="a", strategy_name="s", strategy_code="",
            result={"trades": []}, run_root=tmp_path,
        )


def test_promote_rejects_too_short(tmp_path: Path):
    with pytest.raises(PromoteError):
        promote_ide_run(
            ide_run_id="x", owner_username="a", strategy_name="s", strategy_code="",
            result={"equity_curve": [{"t": "1", "equity": 1.0}]}, run_root=tmp_path,
        )


def test_promote_writes_trades_csv(tmp_path: Path):
    result = {
        "equity_curve": _curve(10),
        "trades": [
            {"timestamp": "2026-01-02T09:00", "symbol": "BTC", "side": "BUY", "quantity": 0.1, "price": 67000},
            {"timestamp": "2026-01-05T09:00", "symbol": "BTC", "side": "SELL", "quantity": 0.1, "price": 68000},
        ],
    }
    promoted = promote_ide_run(
        ide_run_id="x", owner_username="bob", strategy_name="s", strategy_code="",
        result=result, run_root=tmp_path,
    )
    trades_csv = (promoted.run_dir / "trades.csv").read_text(encoding="utf-8-sig")
    assert "BTC" in trades_csv
    assert "BUY" in trades_csv and "SELL" in trades_csv


def test_promote_normalizes_alt_keys(tmp_path: Path):
    # 用 date/value 别名
    result = {
        "equity_curve": [
            {"date": "2026-01-01", "value": 1.0},
            {"date": "2026-01-02", "value": 1.01},
            {"date": "2026-01-03", "value": 1.02},
        ],
    }
    promoted = promote_ide_run(
        ide_run_id="x", owner_username="a", strategy_name="s", strategy_code="",
        result=result, run_root=tmp_path,
    )
    assert promoted.metrics["total_return"] == pytest.approx(0.02, abs=1e-4)


def test_promote_computes_alpha_beta_with_benchmark(tmp_path: Path):
    # 构造一个 strat_return = 0.8 * bench + 0.001 的关系
    import random
    random.seed(7)
    rows = []
    eq = 1.0
    for i in range(60):
        br = random.gauss(0, 0.01)
        nr = 0.8 * br + 0.001
        eq *= 1 + nr
        rows.append({"t": f"d{i}", "equity": eq, "net_return": nr, "benchmark_return": br})
    promoted = promote_ide_run(
        ide_run_id="x", owner_username="a", strategy_name="s", strategy_code="",
        result={"equity_curve": rows}, run_root=tmp_path,
    )
    # beta 约 0.8
    assert abs(promoted.metrics["beta"] - 0.8) < 0.15
    # alpha 大于 0（年化）
    assert promoted.metrics["alpha"] > 0


def test_promote_max_drawdown_negative(tmp_path: Path):
    # 先涨 30%，再跌 50%
    rows = []
    eq = 1.0
    for d in [0.01] * 30 + [-0.02] * 30:
        eq *= 1 + d
        rows.append({"t": "x", "equity": eq, "net_return": d})
    promoted = promote_ide_run(
        ide_run_id="x", owner_username="a", strategy_name="s", strategy_code="",
        result={"equity_curve": rows}, run_root=tmp_path,
    )
    assert promoted.metrics["max_drawdown"] < -0.1


# ============================================================
# build_ai_context
# ============================================================


def test_ai_context_filters_retired_factors():
    ctx = build_ai_context(
        connectors=[{"name": "binance_rest", "asset_class": "crypto_perp"}],
        factors=[
            {"factor_id": "alpha_001", "lifecycle_state": "QUALIFIED", "description": "动量"},
            {"factor_id": "alpha_002", "lifecycle_state": "RETIRED", "description": "deprecated"},
        ],
        operators=[{"name": "ts_mean"}, {"name": "cs_rank"}],
    )
    assert len(ctx.factors) == 1
    assert ctx.factors[0]["factor_id"] == "alpha_001"


def test_ai_context_system_prompt_block_contains_all_sections():
    ctx = build_ai_context(
        connectors=[{"name": "binance", "asset_class": "crypto_perp", "kind": "rest"}],
        factors=[{"factor_id": "alpha_001", "lifecycle_state": "QUALIFIED", "description": "动量"}],
        operators=[{"name": "ts_mean"}, {"name": "cs_rank"}],
    )
    s = ctx.to_system_prompt_block()
    assert "可用数据 connector" in s
    assert "binance" in s
    assert "可用因子" in s
    assert "alpha_001" in s
    assert "白名单算子" in s
    assert "ts_mean" in s
    assert "沙箱规则" in s
    assert "禁止" in s
    assert "emit_result schema" in s
    assert "equity_curve" in s


def test_ai_context_empty_inputs_ok():
    ctx = build_ai_context()
    assert ctx.connectors == []
    assert ctx.factors == []
    assert ctx.operators == []
    # 但 rules + schema + skeleton 仍存在
    assert len(ctx.rules) >= 3
    assert "equity_curve" in ctx.emit_result_schema
    assert "quantbt.emit_result" in ctx.code_skeleton
