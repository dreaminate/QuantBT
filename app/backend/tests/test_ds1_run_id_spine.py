"""DS-1 · run_id 脊梁对抗测试（决策 D-DELIVERY-SLICE / Fork3=A）。

脊梁断言（种已知坏门必抓）：
  1. agent 对话回测（无 run_id）→ 产真 `RUN_ROOT/<id>/run.json + portfolio.csv`（真净值），
     run_id 可被 `run_verdict.project_verdict / project_overfit` 真消费（非 mock）。
  2. 同 goal 重跑 → config_hash 一致、honest-N 不重刷（复用 lineage 单一源 memoize）。
  3. §3 不假绿灯：样本未捆 → 显式失败（needs_sample），绝不伪造 run。
  4. 断真引擎接线（沙箱不产 equity_curve）→ 显式失败，绝不伪造 run。
  5. 合成器确定性（同 goal+market+lookback → 同码）+ 无前视守卫在生成码里。
"""

from __future__ import annotations

import shutil

import pytest

import app.run_detail_core as rdc
from app.agent.business_tools import _synth_and_promote
from app.agent.sample_data import SAMPLE_REL, sample_path
from app.agent.strategy_synth import synthesize_strategy_code
from app.lineage import Ledger
from app.run_verdict import project_overfit, project_verdict
from app.verification import Verifier, VerdictStore


def _has_btc_sample() -> bool:
    try:
        return sample_path("crypto_perp").exists()
    except Exception:  # noqa: BLE001
        return False


needs_btc = pytest.mark.skipif(
    not _has_btc_sample(),
    reason="BTC 起步样本未捆绑（先跑 app.agent.sample_data.bundle_btc_daily 落 data/samples/）",
)


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """隔离 data_root：拷贝随仓 BTC 样本进 tmp + 把 run 消费端 RUN_ROOT 指到 tmp（load_run 读这里）。"""
    src = sample_path("crypto_perp")
    dst = tmp_path / SAMPLE_REL["crypto_perp"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    run_root = tmp_path / "artifacts" / "experiments"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rdc, "RUN_ROOT", run_root)  # project_verdict→load_run→run_dir 读这里
    return {
        "root": tmp_path,
        "ledger": Ledger(tmp_path / "lineage"),
        "vstore": VerdictStore(tmp_path / "verification"),
        "verifier": Verifier(),
    }


@needs_btc
def test_agent_backtest_produces_real_run_consumable_by_verdict(iso):
    """脊梁主断言：无 run_id → 真 RUN_ROOT run + run_id 被 run_verdict 真消费。"""
    out = _synth_and_promote(
        args={"market": "crypto_perp", "strategy_goal_ref": "goal-momentum-1", "lookback": 20},
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=iso["vstore"], verifier=iso["verifier"], llm_client=None,
    )
    assert out.get("error") is None, out
    run_id = out["run_id"]
    # 真落盘（非 status=running 空占位）
    run_dir = iso["root"] / "artifacts" / "experiments" / run_id
    assert (run_dir / "run.json").exists(), "run.json 必须落盘（RUN_ROOT 契约）"
    assert (run_dir / "portfolio.csv").exists(), "portfolio.csv（真净值序列）必须落盘"
    assert (run_dir / "strategy.py").exists(), "合成策略源码留痕"
    # run_id 可被 run_verdict 真消费（单一源、非 mock）
    overfit = project_overfit(run_id)
    assert overfit["run_id"] == run_id
    verdict = project_verdict(run_id, verdict_store=iso["vstore"], verifier=iso["verifier"])
    assert "verdict" in verdict
    # 真引擎产真 metrics（sharpe 是真算浮点，非写死）
    assert isinstance(out["metrics"].get("sharpe"), float)
    assert out["source"] == "synthesized_backtest_run"
    assert out["synthesis_method"] == "template"


@needs_btc
def test_same_goal_rerun_config_hash_stable_and_honest_n_not_double_spent(iso):
    """同 goal 重跑：config_hash 稳定 + honest-N 不重刷（memoize 单一源）。"""
    ref = "goal-momentum-stable"
    args = {"market": "crypto_perp", "strategy_goal_ref": ref, "lookback": 20}
    out1 = _synth_and_promote(args=args, ledger=iso["ledger"], returns_store=None,
                              data_root=iso["root"], verdict_store=None, verifier=None, llm_client=None)
    n1 = iso["ledger"].honest_n(ref)
    out2 = _synth_and_promote(args=args, ledger=iso["ledger"], returns_store=None,
                              data_root=iso["root"], verdict_store=None, verifier=None, llm_client=None)
    n2 = iso["ledger"].honest_n(ref)
    assert out1.get("error") is None and out2.get("error") is None, (out1, out2)
    ch1 = out1["overfit"]["config_hash"]
    ch2 = out2["overfit"]["config_hash"]
    assert ch1 and ch1 == ch2, f"同 goal 应同 config_hash：{ch1} vs {ch2}"
    assert n1 >= 1, "honest-N 应至少记一次（真记账）"
    assert n2 == n1, f"honest-N 重刷：{n1} → {n2}（同 config_hash 必须 memoize、不二次计数）"


@needs_btc
def test_break_engine_wiring_fails_honestly_not_fake_green(iso, monkeypatch):
    """断真引擎接线（沙箱不产 equity_curve）→ 显式失败，绝不伪造 run（§3）。"""
    import app.ide.sandbox as sandbox

    def _broken(code, **kw):  # noqa: ANN001, ARG001
        return sandbox.SandboxResult(
            exit_code=1, stdout="", stderr="injected: engine broken", duration_s=0.0,
            user_result=None,
        )

    monkeypatch.setattr(sandbox, "run_user_strategy", _broken)
    out = _synth_and_promote(
        args={"market": "crypto_perp", "strategy_goal_ref": "g-broken", "lookback": 20},
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=None, verifier=None, llm_client=None,
    )
    assert out.get("run_id") is None, "引擎断了绝不返回 run_id（防假绿灯）"
    assert "equity_curve" in (out.get("error") or ""), out


@needs_btc
def test_missing_sample_fails_honestly_no_fake_run(iso):
    """§3：stocks_cn 样本未捆（仅 BTC 拷进 tmp）→ 显式 needs_sample 失败，绝不伪造 A股回测。"""
    out = _synth_and_promote(
        args={"market": "stocks_cn", "strategy_goal_ref": "g-cn", "lookback": 20},
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=None, verifier=None, llm_client=None,
    )
    assert out.get("needs_sample") is True
    assert out.get("run_id") is None, "样本缺绝不伪造 run"
    assert out["market"] == "stocks_cn"


def test_synth_is_deterministic_and_no_lookahead():
    """合成器确定性（同入参同码）+ 无前视守卫在生成码里。"""
    a = synthesize_strategy_code(market="crypto_perp", strategy_goal_ref="x", lookback=20)
    b = synthesize_strategy_code(market="crypto_perp", strategy_goal_ref="x", lookback=20)
    assert a.code == b.code, "同入参合成码必须确定（保证 config_hash 稳定）"
    assert a.method == "template"
    # 无前视：仓位用 close[i - 1] 与 i-1-LOOKBACK 比，绝不读 close[i]（当日）。
    assert "close[i - 1] > close[i - 1 - LOOKBACK]" in a.code
    # 读真样本 + emit_result（§3 真回测契约）
    assert "os.environ" in a.code and "emit_result" in a.code
    assert 'pl.read_csv' not in a.code, "沙箱锁 socket/asyncio，禁用 polars 读路径（用 stdlib csv）"


def test_llm_seam_falls_back_when_output_invalid():
    """LLM seam：输出不含 emit_result/DATA_DIR → 判废兜底模板（防把废输出当回测）。"""
    class _BadLLM:
        def complete(self, prompt):  # noqa: ANN001, ARG002
            return "print('hello')  # 没有 emit_result"

    r = synthesize_strategy_code(market="crypto_perp", strategy_goal_ref="x",
                                 lookback=20, llm_client=_BadLLM())
    assert r.method == "template", "废 LLM 输出必须兜底模板，绝不当真回测码"


def test_llm_seam_accepts_valid_output():
    """LLM seam：合格输出（含 emit_result + DATA_DIR）→ 采纳为 llm 方法。"""
    class _GoodLLM:
        def complete(self, prompt):  # noqa: ANN001, ARG002
            return (
                "```python\nimport os\n"
                "DATA_DIR = os.environ['DATA_DIR']\n"
                "quantbt.emit_result({'equity_curve': [{'t':'1','equity':1.0}]})\n```"
            )

    r = synthesize_strategy_code(market="crypto_perp", strategy_goal_ref="x",
                                 lookback=20, llm_client=_GoodLLM())
    assert r.method == "llm"
    assert "emit_result" in r.code and "```" not in r.code, "应剥离 code fence"
