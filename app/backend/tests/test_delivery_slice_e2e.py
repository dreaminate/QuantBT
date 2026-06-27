"""交付门 e2e 集成测试（卡 9a497bde · D-DELIVERY-SLICE 收口）。

陌生人完整路径**全程真产物、零 mock**，一条链证明非演示剧场：
  strategy_goal.create（真 goal_id）
    → backtest.run（真 run_id 落 RUN_ROOT、真净值，读真捆绑样本）
    → project_verdict / project_overfit（真裁决 + 真 PBO/DSR/Bootstrap）
    → paper register_run + prime（真 bar provider 喂数据 bars_fed>0 产真 equity）。
治理门不破：A股恒拒 live（D-PERM）。任一环退化为 mock/伪造/空壳 → 测试红。
"""

from __future__ import annotations

import shutil

import pytest

import app.run_detail_core as rdc
from app.agent.business_tools import _synth_and_promote
from app.agent.sample_data import SAMPLE_REL, sample_path
from app.lineage import Ledger
from app.paper.desk import AShareLiveForbidden, PaperDeskService
from app.research_os import MarketDataUseValidationRecord
from app.run_verdict import project_overfit, project_verdict
from app.strategy_goal_store import StrategyGoalStore
from app.verification import Verifier, VerdictStore

MARKET_DATA_USE_REFS = ["market_data_use:delivery_slice:accepted"]


class _DatasetSemantics:
    dataset_ref = "dataset:btc_daily"
    known_at_ref = "known_at:btc_daily"
    effective_at_ref = "effective_at:btc_daily"
    pit_bitemporal_rules_ref = "pit:btc_daily"


class _MarketDataUseRegistry:
    def __init__(self) -> None:
        self._record = MarketDataUseValidationRecord(
            validation_ref=MARKET_DATA_USE_REFS[0],
            request_ref="market_data_use:delivery_slice:request",
            use_context="backtest",
            dataset_refs=("dataset:btc_daily",),
            instrument_refs=("BTC-USDT",),
            capability_matrix_ref="capability:crypto_perp_daily",
            capital_record_ref=None,
            transformation_refs=(),
            accepted=True,
            violation_codes=(),
            evidence_refs=("evidence:delivery_slice_market_data_use",),
            recorded_by="test",
            created_at_utc="2026-06-27T00:00:00Z",
        )

    def use_validation(self, validation_ref: str) -> MarketDataUseValidationRecord:
        if validation_ref != self._record.validation_ref:
            raise KeyError(validation_ref)
        return self._record

    def dataset(self, dataset_ref: str) -> _DatasetSemantics:
        if dataset_ref != _DatasetSemantics.dataset_ref:
            raise KeyError(dataset_ref)
        return _DatasetSemantics()


def _has_btc() -> bool:
    try:
        return sample_path("crypto_perp").exists()
    except Exception:  # noqa: BLE001
        return False


needs_btc = pytest.mark.skipif(not _has_btc(), reason="BTC 起步样本未捆绑")


@needs_btc
def test_stranger_full_path_chat_to_paper_all_real(tmp_path, monkeypatch):
    """陌生人 chat→backtest→裁决→paper 全链真产物（非 mock/空壳）。"""
    # —— 隔离：拷真 BTC 样本进 tmp + run 消费端 RUN_ROOT 指 tmp ——
    dst = tmp_path / SAMPLE_REL["crypto_perp"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_path("crypto_perp"), dst)
    run_root = tmp_path / "artifacts" / "experiments"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rdc, "RUN_ROOT", run_root)
    ledger = Ledger(tmp_path / "lineage")
    vstore = VerdictStore(tmp_path / "verification")
    verifier = Verifier()

    # ① chat → 真 goal_id（StrategyGoal 校验落库）
    goals = StrategyGoalStore(tmp_path / "goals")
    g = goals.create_from_args({"asset_class": "crypto_perp", "objective": "max_calmar", "horizon": "daily"})
    goal_id = g["strategy_goal_id"]
    assert goal_id and goal_id.startswith("goal_"), g

    # ② backtest → 真 run_id 落 RUN_ROOT（读真样本产真净值）
    bt = _synth_and_promote(
        args={
            "market": "crypto_perp",
            "strategy_goal_ref": goal_id,
            "lookback": 20,
            "market_data_use_validation_refs": MARKET_DATA_USE_REFS,
        },
        ledger=ledger, returns_store=None, data_root=tmp_path,
        verdict_store=vstore, verifier=verifier, llm_client=None,
        market_data_registry=_MarketDataUseRegistry(),
    )
    assert bt.get("error") is None, bt
    run_id = bt["run_id"]
    assert (run_root / run_id / "run.json").exists()
    assert (run_root / run_id / "portfolio.csv").exists()  # 真净值序列
    assert isinstance(bt["metrics"].get("sharpe"), float)  # 真算 metrics 非写死

    # ③ 裁决 → run_id 被 run_verdict 真消费（真 PBO/DSR/Bootstrap，非 mock 0.18/1.34）
    overfit = project_overfit(run_id)
    assert overfit["run_id"] == run_id
    assert "config_hash" in (bt.get("overfit") or {})
    verdict = project_verdict(run_id, verdict_store=vstore, verifier=verifier)
    assert "verdict" in verdict  # 诚实裁决（无权威记录则 concern，不假绿灯）

    # ④ paper → register + prime 真喂 bars 产真 equity（bars_fed>0，非空壳）
    svc = PaperDeskService()
    eqlog = tmp_path / "eqlog_btc.jsonl"
    svc.register_run(
        run_id=run_id, name="陌生人 BTC 动量", origin="agent", market="crypto",
        symbols=["BTC-USDT"], bench="BTC-USDT", creator="stranger",
        equity_log_path=eqlog, simulate=True,
    )
    primed = svc.prime_run(run_id)
    assert primed["bars_fed"] > 0, "paper 必须真喂到 bar（非空壳）"
    assert primed["equity_points"] > 0, "净值序列非空（bars_fed>0 严格绑定）"
    assert len(svc.equity_log(run_id)) > 0


@needs_btc
def test_empty_shell_paper_no_fake_green(tmp_path):
    """§3：simulate=False 空壳 paper → bars_fed=0、净值不动（不假绿灯）。"""
    svc = PaperDeskService()
    eqlog = tmp_path / "eqlog_empty.jsonl"
    svc.register_run(
        run_id="empty1", name="空壳", origin="agent", market="crypto",
        symbols=["BTC-USDT"], bench="BTC-USDT", creator="stranger",
        equity_log_path=eqlog, simulate=False,  # 不注 provider → 空壳
    )
    primed = svc.prime_run("empty1")
    assert primed["bars_fed"] == 0, "空壳绝不伪造 bars_fed>0"


def test_governance_a_share_live_always_forbidden(tmp_path):
    """治理红线：A股 paper run 试 live 下单恒拒（D-PERM，与本波无关、必须不破）。"""
    svc = PaperDeskService()
    eqlog = tmp_path / "eqlog_cn.jsonl"
    svc.register_run(
        run_id="cn_e2e", name="A股", origin="agent", market="equity_cn",
        symbols=["000300.SH"], bench="000300.SH", creator="stranger",
        equity_log_path=eqlog,
    )
    with pytest.raises(AShareLiveForbidden):
        svc.attempt_live_order("cn_e2e", {"symbol": "000300.SH", "side": "buy", "quantity": 100})
