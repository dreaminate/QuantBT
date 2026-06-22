"""DS-2 · strategy_goal.create 接真对抗测试（D-DELIVERY-SLICE · blocker #2）。

种已知坏门必抓：
  1. 结构化 args（asset_class）→ 校验落库产真 goal_id；A股强制 leverage=1.0（治理不变量不破）。
  2. 自然语言 description（无 asset_class）→ slot-filler 补全产 goal_id（无 LLM 也走通）。
  3. §3：缺 asset_class 且无自然语言 → needs_slots，绝不产假 goal_id。
  4. 内容寻址幂等：同目标 → 同 goal_id。
  5. goal_id 真可被 DS-1 backtest 消费（chat→backtest 链路闭合）。
"""

from __future__ import annotations

import shutil

import pytest

import app.run_detail_core as rdc
from app.agent.business_tools import _synth_and_promote
from app.agent.sample_data import SAMPLE_REL, sample_path
from app.lineage import Ledger
from app.strategy_goal_store import StrategyGoalStore


def test_structured_args_persist_real_goal_id_and_a_share_leverage(tmp_path):
    store = StrategyGoalStore(tmp_path / "goals")
    out = store.create_from_args({"asset_class": "equity_cn", "objective": "info_ratio", "horizon": "weekly"})
    assert out.get("error") is None, out
    gid = out["strategy_goal_id"]
    assert gid.startswith("goal_"), out
    # 真落库 + 可读回
    loaded = store.get(gid)
    assert loaded.asset_class == "equity_cn"
    # 治理不变量：A股 leverage 强制 1.0（StrategyGoal 校验器把守）
    assert loaded.constraints.leverage_max == 1.0


def test_natural_language_slot_filled_to_goal_id(tmp_path):
    store = StrategyGoalStore(tmp_path / "goals")
    out = store.create_from_args({"description": "加密 永续 资金费率 日频 卡玛"})
    assert out.get("error") is None, out
    assert out["asset_class"] == "crypto_perp"  # "永续" → crypto_perp
    assert out["strategy_goal_id"].startswith("goal_")


def test_missing_slots_no_fake_goal_id():
    """§3：缺 asset_class 且无自然语言 → needs_slots，绝不产假 goal_id。"""
    import tempfile
    from pathlib import Path

    store = StrategyGoalStore(Path(tempfile.mkdtemp()))
    out = store.create_from_args({"objective": "max_sharpe"})  # 啥市场都没说
    assert out.get("strategy_goal_id") is None, out
    assert out.get("needs_slots"), "缺槽位必须显式提示补全，不伪造目标"


def test_goal_id_is_content_addressed_idempotent():
    import tempfile
    from pathlib import Path

    store = StrategyGoalStore(Path(tempfile.mkdtemp()))
    a = store.create_from_args({"asset_class": "crypto_perp", "objective": "max_calmar", "horizon": "daily"})
    b = store.create_from_args({"asset_class": "crypto_perp", "objective": "max_calmar", "horizon": "daily"})
    assert a["strategy_goal_id"] == b["strategy_goal_id"], "同目标必须同 goal_id（内容寻址幂等）"


def _has_btc() -> bool:
    try:
        return sample_path("crypto_perp").exists()
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _has_btc(), reason="BTC 样本未捆绑")
def test_goal_id_flows_into_backtest_chat_to_backtest_chain(tmp_path, monkeypatch):
    """链路闭合：strategy_goal.create 产 goal_id → DS-1 backtest 真消费产真 run。"""
    # 建真 goal
    store = StrategyGoalStore(tmp_path / "goals")
    g = store.create_from_args({"asset_class": "crypto_perp", "objective": "max_calmar", "horizon": "daily"})
    gid = g["strategy_goal_id"]
    # 隔离样本 + run root（复刻 DS-1 iso）
    dst = tmp_path / SAMPLE_REL["crypto_perp"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_path("crypto_perp"), dst)
    rr = tmp_path / "artifacts" / "experiments"
    rr.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rdc, "RUN_ROOT", rr)
    # 把 goal_id 当 strategy_goal_ref 喂 backtest
    out = _synth_and_promote(
        args={"market": "crypto_perp", "strategy_goal_ref": gid, "lookback": 20},
        ledger=Ledger(tmp_path / "lineage"), returns_store=None, data_root=tmp_path,
        verdict_store=None, verifier=None, llm_client=None,
    )
    assert out.get("error") is None, out
    assert out["run_id"], "chat 产的 goal_id 必须能驱动 DS-1 backtest 产真 run"
