"""v0.8.3 · IDE 沙箱 result.json → 正式 Run promote 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ide.ai_context import build_ai_context
from app.ide.promote import PromoteError, promote_ide_run
from app.llm.call_record import (
    CallRecordKind,
    LLMCallRecord,
    ReplayState,
    make_call_id,
    seal_record,
)
from app.llm.call_record_store import LLMCallRecordStore


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


def _attribution_rows() -> list[dict]:
    return [
        {
            "period": "2026-01",
            "component": "market",
            "portfolio_weight": "0.6",
            "benchmark_weight": "0.5",
            "portfolio_return": "0.10",
            "benchmark_return": "0.08",
            "benchmark_total_return": "0.07",
            "allocation_effect": "0.001",
            "selection_effect": "0.010",
            "interaction_effect": "0.002",
            "cost_effect": "0.001",
            "net_contribution": "0.012",
        }
    ]


def _append_store_invocation(
    store: LLMCallRecordStore,
    *,
    owner_user_id: str,
    workflow_id: str,
    invocation_id: str,
) -> tuple[LLMCallRecord, LLMCallRecord]:
    common = dict(
        provider="anthropic",
        model="claude-x",
        auth_ref="secretref://anthropic/llm_anthropic",
        replay_state=ReplayState.LIVE.value,
        owner_user_id=owner_user_id,
        workflow_id=workflow_id,
        invocation_id=invocation_id,
        attempt_no=1,
        routing_policy_ref="routing:ide-promote:test",
        routing_policy_state="configured_ref",
        prompt_digest="0123456789abcdef",
        prompt_hash="0123456789abcdef",
        tool_schema_hash="1111111111111111",
        response_digest="fedcba9876543210",
        response_ref="llm_response:fedcba9876543210",
        started_at="2026-07-12T00:00:00+00:00",
        finished_at="2026-07-12T00:00:01+00:00",
        latency_ms=1000.0,
        cost={
            "status": "unavailable", "currency": "USD", "amount": None,
            "source": "none", "reason": "provider_cost_not_reported",
        },
    )
    rows: list[LLMCallRecord] = []
    for kind in (CallRecordKind.ATTEMPT.value, CallRecordKind.TERMINAL.value):
        row = LLMCallRecord(
            **common,
            record_kind=kind,
            call_id=make_call_id(
                prompt_digest="",
                provider="",
                model="",
                role="",
                session_id="",
                seq=1,
                owner_user_id=owner_user_id,
                workflow_id=workflow_id,
                invocation_id=invocation_id,
                record_kind=kind,
                attempt_no=1,
            ),
        )
        row.seal = seal_record(row, store.seal_secret)
        store.append(row)
        rows.append(row)
    return rows[0], rows[1]


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
    assert not (promoted.run_dir / "attribution.csv").exists()


def test_promote_persists_only_reconciled_canonical_attribution(tmp_path: Path):
    promoted = promote_ide_run(
        ide_run_id="ide-attribution",
        owner_username="alice",
        strategy_name="attributed",
        strategy_code="quantbt.emit_result({})",
        result={
            "equity_curve": _curve(10),
            "attribution": _attribution_rows(),
        },
        run_root=tmp_path / "runs",
    )

    artifact = promoted.run_dir / "attribution.csv"
    assert artifact.exists()
    assert artifact.read_text(encoding="utf-8").splitlines()[1].startswith(
        "2026-01,market,"
    )


def test_promote_rejects_false_attribution_without_partial_run(tmp_path: Path):
    rows = _attribution_rows()
    rows[0]["selection_effect"] = "0.999"
    run_root = tmp_path / "runs"

    with pytest.raises(PromoteError, match="selection_effect does not reconcile"):
        promote_ide_run(
            ide_run_id="ide-bad-attribution",
            owner_username="alice",
            strategy_name="bad-attribution",
            strategy_code="",
            result={"equity_curve": _curve(10), "attribution": rows},
            run_root=run_root,
        )

    assert not run_root.exists()


def test_promote_resolves_owner_scoped_llm_records(tmp_path: Path):
    store = LLMCallRecordStore(tmp_path / "audit" / "llm_call_records.jsonl")
    expected = _append_store_invocation(
        store,
        owner_user_id="owner-alice",
        workflow_id="ide_run:ide-audit",
        invocation_id="invocation-alice",
    )

    promoted = promote_ide_run(
        ide_run_id="ide-audit",
        owner_username="alice",
        owner_user_id="owner-alice",
        strategy_name="llm-audited",
        strategy_code="quantbt.emit_result({})",
        result={"equity_curve": _curve(10)},
        run_root=tmp_path / "runs",
        llm_call_record_store=store,
    )

    manifest = json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["source"]["owner_user_id"] == "owner-alice"
    assert manifest["llm_call_record_refs"] == [row.call_id for row in expected]
    assert manifest["release_verdict"]["gate_evaluation_ok"] is True


def test_promote_llm_records_are_owner_isolated(tmp_path: Path):
    store = LLMCallRecordStore(tmp_path / "audit" / "llm_call_records.jsonl")
    _append_store_invocation(
        store,
        owner_user_id="owner-alice",
        workflow_id="ide_run:ide-audit",
        invocation_id="invocation-alice",
    )

    promoted = promote_ide_run(
        ide_run_id="ide-audit",
        owner_username="bob",
        owner_user_id="owner-bob",
        strategy_name="isolated",
        strategy_code="",
        result={"equity_curve": _curve(10)},
        run_root=tmp_path / "runs",
        llm_call_record_store=store,
    )

    manifest = json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))
    assert "llm_call_record_refs" not in manifest


def test_promote_llm_store_requires_owner_and_does_not_swallow_read_errors(tmp_path: Path):
    store = LLMCallRecordStore(tmp_path / "audit" / "llm_call_records.jsonl")
    with pytest.raises(PromoteError, match="stable owner_user_id"):
        promote_ide_run(
            ide_run_id="ide-audit",
            owner_username="alice",
            strategy_name="missing-owner",
            strategy_code="",
            result={"equity_curve": _curve(10)},
            run_root=tmp_path / "runs",
            llm_call_record_store=store,
        )

    class BrokenOwnerScopedStore:
        def llm_records_for(self, asset_ref, *, owner_user_id):
            raise RuntimeError("owner-scoped read failed")

    with pytest.raises(RuntimeError, match="owner-scoped read failed"):
        promote_ide_run(
            ide_run_id="ide-audit",
            owner_username="alice",
            owner_user_id="owner-alice",
            strategy_name="broken-store",
            strategy_code="",
            result={"equity_curve": _curve(10)},
            run_root=tmp_path / "runs",
            llm_call_record_store=BrokenOwnerScopedStore(),
        )


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
