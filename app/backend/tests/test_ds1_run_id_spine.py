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
from app.research_os import MarketDataUseValidationRecord
from app.run_verdict import project_overfit, project_verdict
from app.verification import Verifier, VerdictStore

MARKET_DATA_USE_REFS = ["market_data_use:agent_builder:accepted"]
MARKET_DATASET_REF = "dataset:btc_daily"


class _DatasetSemantics:
    def __init__(
        self,
        *,
        known_at_ref: str | None = "known_at:btc_daily",
        effective_at_ref: str | None = "effective_at:btc_daily",
        pit_bitemporal_rules_ref: str | None = "pit:btc_daily",
    ) -> None:
        self.dataset_ref = MARKET_DATASET_REF
        self.known_at_ref = known_at_ref
        self.effective_at_ref = effective_at_ref
        self.pit_bitemporal_rules_ref = pit_bitemporal_rules_ref


class _MarketDataUseRegistry:
    def __init__(
        self,
        records: list[MarketDataUseValidationRecord] | None = None,
        datasets: dict[str, _DatasetSemantics] | None = None,
    ) -> None:
        source = [_market_data_use_validation()] if records is None else records
        self._records = {record.validation_ref: record for record in source}
        self._datasets = {MARKET_DATASET_REF: _DatasetSemantics()} if datasets is None else datasets

    def use_validation(self, validation_ref: str) -> MarketDataUseValidationRecord:
        return self._records[validation_ref]

    def dataset(self, dataset_ref: str) -> _DatasetSemantics:
        return self._datasets[dataset_ref]


def _market_data_use_validation(**overrides) -> MarketDataUseValidationRecord:
    data = {
        "validation_ref": MARKET_DATA_USE_REFS[0],
        "request_ref": "market_data_use:agent_builder:request",
        "use_context": "strategy_builder_backtest",
        "dataset_refs": (MARKET_DATASET_REF,),
        "instrument_refs": ("BTC-USDT",),
        "capability_matrix_ref": "capability:crypto_perp_daily",
        "capital_record_ref": None,
        "transformation_refs": (),
        "accepted": True,
        "violation_codes": (),
        "evidence_refs": ("evidence:agent_builder_market_data_use",),
        "recorded_by": "test",
        "created_at_utc": "2026-06-27T00:00:00Z",
    }
    data.update(overrides)
    return MarketDataUseValidationRecord(**data)


def _with_market_data_use(args: dict) -> dict:
    return {**args, "market_data_use_validation_refs": list(MARKET_DATA_USE_REFS)}


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
        "market_data_registry": _MarketDataUseRegistry(),
    }


def test_strategy_builder_requires_market_data_use_refs_before_synthesis(tmp_path):
    class _CountingLLM:
        called = False

        def complete(self, prompt):  # noqa: ANN001, ARG002
            self.called = True
            return "print('should not be called')"

    llm = _CountingLLM()
    out = _synth_and_promote(
        args={"market": "crypto_perp", "strategy_goal_ref": "g-no-refs", "lookback": 20},
        ledger=Ledger(tmp_path / "lineage"),
        returns_store=None,
        data_root=tmp_path,
        verdict_store=None,
        verifier=None,
        llm_client=llm,
        market_data_registry=_MarketDataUseRegistry(),
    )
    assert "market_data_use_validation_refs" in (out.get("error") or "")
    assert out.get("no_write") is True
    assert llm.called is False, "MarketDataUse gate must run before LLM/code synthesis"
    assert not (tmp_path / "artifacts" / "experiments").exists(), "bad refs must not create run artifacts"


@pytest.mark.parametrize(
    ("registry", "refs", "message"),
    [
        (_MarketDataUseRegistry([]), ["market_data_use:agent_builder:missing"], "unknown"),
        (
            _MarketDataUseRegistry([
                _market_data_use_validation(
                    validation_ref="market_data_use:agent_builder:rejected",
                    accepted=False,
                )
            ]),
            ["market_data_use:agent_builder:rejected"],
            "not accepted",
        ),
        (
            _MarketDataUseRegistry([
                _market_data_use_validation(
                    validation_ref="market_data_use:agent_builder:violation",
                    violation_codes=("live_permission_missing",),
                )
            ]),
            ["market_data_use:agent_builder:violation"],
            "violations",
        ),
        (
            _MarketDataUseRegistry(
                [_market_data_use_validation(validation_ref="market_data_use:agent_builder:no_timing")],
                datasets={MARKET_DATASET_REF: _DatasetSemantics(pit_bitemporal_rules_ref=None)},
            ),
            ["market_data_use:agent_builder:no_timing"],
            "PIT/bitemporal timing",
        ),
    ],
)
def test_strategy_builder_rejects_bad_market_data_use_refs_before_run(tmp_path, registry, refs, message):
    out = _synth_and_promote(
        args={
            "market": "crypto_perp",
            "strategy_goal_ref": "g-bad-market-data-use",
            "lookback": 20,
            "market_data_use_validation_refs": refs,
        },
        ledger=Ledger(tmp_path / "lineage"),
        returns_store=None,
        data_root=tmp_path,
        verdict_store=None,
        verifier=None,
        llm_client=None,
        market_data_registry=registry,
    )
    assert message in (out.get("error") or "")
    assert out.get("no_write") is True
    assert out.get("run_id") is None
    assert not (tmp_path / "artifacts" / "experiments").exists(), "bad refs must not create run artifacts"


@needs_btc
def test_agent_backtest_produces_real_run_consumable_by_verdict(iso):
    """脊梁主断言：无 run_id → 真 RUN_ROOT run + run_id 被 run_verdict 真消费。"""
    out = _synth_and_promote(
        args=_with_market_data_use({"market": "crypto_perp", "strategy_goal_ref": "goal-momentum-1", "lookback": 20}),
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=iso["vstore"], verifier=iso["verifier"], llm_client=None,
        market_data_registry=iso["market_data_registry"],
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
    assert out["market_data_use_validation_refs"] == MARKET_DATA_USE_REFS


@needs_btc
def test_assembly_inputs_recorded_in_metadata_and_disclosed_honestly(iso):
    """M8/M1 种坏门：用户组装 factor_set/model_id → 不静默丢；落 run.json assembly_inputs + note 诚实披露。

    旧坏门：_synth_and_promote 忽略组装参数、只跑 momentum 模板 → 用户被误导以为回测了自己的组装。
    新契约：组装落 metadata（可追溯）+ 返回 note 明说「这是模板基线、组装已记录但未注入」。
    """
    import json

    out = _synth_and_promote(
        args=_with_market_data_use({
            "market": "crypto_perp", "strategy_goal_ref": "g-assembly", "lookback": 20,
            "factor_set": "fs_abc123", "model_id": "lgbm_rank_6f",
            "signal_id": "sig_xyz", "portfolio_id": "pf_789", "cost_preset": "binance_taker",
        }),
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=iso["vstore"], verifier=iso["verifier"], llm_client=None,
        market_data_registry=iso["market_data_registry"],
    )
    assert out.get("error") is None, out
    run_id = out["run_id"]
    # ① 组装落 run.json metadata（assembly_inputs）—— 可追溯、不静默丢。
    run_json = json.loads(
        (iso["root"] / "artifacts" / "experiments" / run_id / "run.json").read_text(encoding="utf-8")
    )
    ai = run_json.get("assembly_inputs") or {}
    assert ai.get("factor_set") == "fs_abc123", run_json
    assert ai.get("model_id") == "lgbm_rank_6f"
    assert ai.get("signal_id") == "sig_xyz"
    assert ai.get("portfolio_id") == "pf_789"
    assert ai.get("cost_preset") == "binance_taker"
    # ② 返回 dict 也透出组装 + 诚实 note（不假装回测了组装）。
    assert out.get("assembly_injected") is False, "DS-1 尚未注入组装，必须诚实标 False"
    assert out["assembly_inputs"]["factor_set"] == "fs_abc123"
    note = out.get("note") or ""
    assert "模板基线" in note and "尚未注入" in note and "已记录" in note, note


@needs_btc
def test_no_assembly_no_assembly_inputs_key(iso):
    """无组装入参 → 不写 assembly_inputs（向后兼容、不污染既有 run.json）。"""
    import json

    out = _synth_and_promote(
        args=_with_market_data_use({"market": "crypto_perp", "strategy_goal_ref": "g-plain", "lookback": 20}),
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=None, verifier=None, llm_client=None,
        market_data_registry=iso["market_data_registry"],
    )
    assert out.get("error") is None, out
    run_json = json.loads(
        (iso["root"] / "artifacts" / "experiments" / out["run_id"] / "run.json").read_text(encoding="utf-8")
    )
    assert "assembly_inputs" not in run_json, "无组装不应写 assembly_inputs 键"
    assert "assembly_injected" not in out


@needs_btc
def test_same_goal_rerun_config_hash_stable_and_honest_n_not_double_spent(iso):
    """同 goal 重跑：config_hash 稳定 + honest-N 不重刷（memoize 单一源）。"""
    ref = "goal-momentum-stable"
    args = _with_market_data_use({"market": "crypto_perp", "strategy_goal_ref": ref, "lookback": 20})
    out1 = _synth_and_promote(args=args, ledger=iso["ledger"], returns_store=None,
                              data_root=iso["root"], verdict_store=None, verifier=None, llm_client=None,
                              market_data_registry=iso["market_data_registry"])
    n1 = iso["ledger"].honest_n(ref)
    out2 = _synth_and_promote(args=args, ledger=iso["ledger"], returns_store=None,
                              data_root=iso["root"], verdict_store=None, verifier=None, llm_client=None,
                              market_data_registry=iso["market_data_registry"])
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
        args=_with_market_data_use({"market": "crypto_perp", "strategy_goal_ref": "g-broken", "lookback": 20}),
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=None, verifier=None, llm_client=None,
        market_data_registry=iso["market_data_registry"],
    )
    assert out.get("run_id") is None, "引擎断了绝不返回 run_id（防假绿灯）"
    assert "equity_curve" in (out.get("error") or ""), out


@needs_btc
def test_missing_sample_fails_honestly_no_fake_run(iso):
    """§3：stocks_cn 样本未捆（仅 BTC 拷进 tmp）→ 显式 needs_sample 失败，绝不伪造 A股回测。"""
    out = _synth_and_promote(
        args=_with_market_data_use({"market": "stocks_cn", "strategy_goal_ref": "g-cn", "lookback": 20}),
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=None, verifier=None, llm_client=None,
        market_data_registry=iso["market_data_registry"],
    )
    assert out.get("needs_sample") is True
    assert out.get("run_id") is None, "样本缺绝不伪造 run"
    assert out["market"] == "stocks_cn"
    # H1：error/guidance 清晰引导前端诚实展示（crypto 自带样本即用 / A股需 TUSHARE_TOKEN+bundle）。
    msg = (out.get("error") or "") + (out.get("guidance") or "")
    assert "TUSHARE_TOKEN" in msg and "bundle_hs300_daily" in msg, msg
    assert "crypto" in msg and "BTC" in msg, msg


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
    """LLM seam：合格输出（含 emit_result + DATA_DIR + 正确 market 标签 + 实读对应样本路径）→ 采纳为 llm 方法。"""
    from app.agent.sample_data import sample_rel

    rel = sample_rel("crypto_perp")

    class _GoodLLM:
        def complete(self, prompt):  # noqa: ANN001, ARG002
            return (
                "```python\nimport os\n"
                "DATA_DIR = os.environ['DATA_DIR']\n"
                f"open(f'{{DATA_DIR}}/{rel}')\n"
                "quantbt.emit_result({'equity_curve': [{'t':'1','equity':1.0}],"
                " 'metadata': {'market': 'crypto_perp'}})\n```"
            )

    r = synthesize_strategy_code(market="crypto_perp", strategy_goal_ref="x",
                                 lookback=20, llm_client=_GoodLLM())
    assert r.method == "llm"
    assert "emit_result" in r.code and "```" not in r.code, "应剥离 code fence"


def test_llm_seam_rejects_market_mislabel():
    """M8 种坏门：LLM 读 crypto 样本却把 metadata.market 标 stocks_cn → 判废兜底模板（防 silent mislabel）。"""
    from app.agent.sample_data import sample_rel

    rel = sample_rel("crypto_perp")  # 实读 crypto 样本

    class _MislabelLLM:
        def complete(self, prompt):  # noqa: ANN001, ARG002
            # 实读 crypto 样本，却把 market 标成 stocks_cn —— 标签与实读数据不符。
            return (
                "import os\n"
                "DATA_DIR = os.environ['DATA_DIR']\n"
                f"open(f'{{DATA_DIR}}/{rel}')\n"
                "quantbt.emit_result({'equity_curve': [{'t':'1','equity':1.0}],"
                " 'metadata': {'market': 'stocks_cn'}})\n"
            )

    r = synthesize_strategy_code(market="crypto_perp", strategy_goal_ref="x",
                                 lookback=20, llm_client=_MislabelLLM())
    assert r.method == "template", "market 标签与实读样本不符必须判废，绝不让 mislabel run 通过（§3）"


def test_llm_seam_rejects_wrong_sample_path():
    """M8 种坏门：声明 market 对、但实读的是别的 market 样本路径 → 判废（实读数据须与声明 market 对应）。"""
    from app.agent.sample_data import sample_rel

    wrong_rel = sample_rel("stocks_cn")  # 声明 crypto_perp 却去读 A股样本路径

    class _WrongPathLLM:
        def complete(self, prompt):  # noqa: ANN001, ARG002
            return (
                "import os\n"
                "DATA_DIR = os.environ['DATA_DIR']\n"
                f"open(f'{{DATA_DIR}}/{wrong_rel}')\n"
                "quantbt.emit_result({'equity_curve': [{'t':'1','equity':1.0}],"
                " 'metadata': {'market': 'crypto_perp'}})\n"
            )

    r = synthesize_strategy_code(market="crypto_perp", strategy_goal_ref="x",
                                 lookback=20, llm_client=_WrongPathLLM())
    assert r.method == "template", "实读样本路径与声明 market 不对应必须判废（§3）"
