"""promote 执行诚实【对抗式】测试（wave11/promote-execution-honesty · §16 致命「未注入资产却声称已采用」闭合）。

第十波建了 promote_assembler：run.json `execution_blocks` → ReleaseCandidate → evaluate_release 的
Mock 诚实门（R1 silent mock / R4 template false success / R5 生产走非 live）。但 promote producer 当时
【不写】execution_blocks → 组装器恒空、§16 致命门平凡过。本波让 producer 按【真实执行诚实】写出
execution_blocks，使「模板基线冒充所选组装」被 R4/R5 硬拒。

对抗 5 条（种已知坏门必抓）：
  ① 模板基线必被 R4 抓     —— _synth_and_promote 组装未注入 → run.json 留 template+production 块 → R4/R5 拒
  ② 真 live 注入不误伤     —— live+live_source_ref 块经 promote 透传 → Mock 诚实门放行（不误拒）
  ③ mock 必挂标识         —— mock 块未挂 mock_marked → R1 拒；挂上即放行（门有牙）
  ④ 向后兼容             —— 不传 execution_blocks / 无组装 → run.json 无该键、Mock 诚实门平凡过、既有不变
  ⑤ 不静默改裁决         —— 写块只是【补数据】：promote 本身仍成功落盘，§16 裁决只在显式跑组装器时发生（未接端点）

判定单一源仍在 evaluate_release；本测试只证 producer【诚实落数据】+ 该数据【可被组装器抓】。
"""

from __future__ import annotations

import json
import shutil

import pytest

import app.run_detail_core as rdc
from app.agent.business_tools import _synth_and_promote, _synth_execution_blocks
from app.agent.sample_data import SAMPLE_REL, sample_path
from app.ide.promote import promote_ide_run
from app.lineage import Ledger
from app.release_gate.mock_honesty import (
    GRADE_EXPLORATORY,
    GRADE_PRODUCTION,
    LIVE_NO_SOURCE,
    MOCK_UNMARKED,
    MODE_LIVE,
    MODE_MOCK,
    MODE_TEMPLATE,
    PRODUCTION_VIA_NON_LIVE,
    TEMPLATE_FALSE_SUCCESS,
)
from app.release_gate.promote_assembler import evaluate_run_releasable
from app.release_gate.release_gate import GATE_MOCK_HONESTY
from app.research_os import MarketDataUseValidationRecord


MARKET_DATA_USE_REFS = ["market_data_use:promote_honesty:accepted"]
MARKET_DATASET_REF = "dataset:btc_daily"


class _DatasetSemantics:
    dataset_ref = MARKET_DATASET_REF
    known_at_ref = "known_at:btc_daily"
    effective_at_ref = "effective_at:btc_daily"
    pit_bitemporal_rules_ref = "pit:btc_daily"


class _MarketDataUseRegistry:
    def __init__(self) -> None:
        self._record = MarketDataUseValidationRecord(
            validation_ref=MARKET_DATA_USE_REFS[0],
            request_ref="market_data_use:promote_honesty:request",
            use_context="backtest",
            dataset_refs=(MARKET_DATASET_REF,),
            instrument_refs=("BTC-USDT",),
            capability_matrix_ref="capability:crypto_perp_daily",
            capital_record_ref=None,
            transformation_refs=(),
            accepted=True,
            violation_codes=(),
            evidence_refs=("evidence:promote_honesty_market_data_use",),
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


# ── 建料 ─────────────────────────────────────────────────────────────────────
def _curve(n: int, start: float = 1.0, daily: float = 0.001) -> list[dict]:
    """最小可 promote 的 equity_curve（镜像 test_ide_promote._curve）。"""
    eq = start
    out = []
    for i in range(n):
        if i > 0:
            eq *= 1 + daily
        out.append({"t": f"2026-01-{i + 1:02d}", "equity": round(eq, 6),
                    "net_return": daily if i > 0 else 0.0, "benchmark_return": daily * 0.5})
    return out


def _mock_gate_missing(v) -> str:
    """汇总 Mock 诚实门拒了哪些违规码（空串 = 该门未拒）。"""
    rej = [o for o in v.rejections if o.gate_id == GATE_MOCK_HONESTY]
    return ",".join(",".join(o.missing) for o in rej)


def _promote_with_blocks(tmp_path, blocks, *, owner: str = "alice"):
    """promote 一个最小 run + 注入 execution_blocks，返回落盘后的 run.json dict。"""
    promoted = promote_ide_run(
        ide_run_id="ide_x", owner_username=owner, strategy_name="s",
        strategy_code="quantbt.emit_result({})", result={"equity_curve": _curve(30)},
        run_root=tmp_path, execution_blocks=blocks,
    )
    return promoted, json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))


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
    """隔离 data_root：拷贝随仓 BTC 样本进 tmp + RUN_ROOT 指 tmp（镜像 test_ds1_run_id_spine.iso）。"""
    src = sample_path("crypto_perp")
    dst = tmp_path / SAMPLE_REL["crypto_perp"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    run_root = tmp_path / "artifacts" / "experiments"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rdc, "RUN_ROOT", run_root)
    return {"root": tmp_path, "ledger": Ledger(tmp_path / "lineage")}


# ════════════════════════════════════════════════════════════════════════════
# 单元：_synth_execution_blocks 的 §16 诚实映射（最快·无 I/O·MUT 直接靶）
# ════════════════════════════════════════════════════════════════════════════
def test_helper_not_injected_maps_to_template_production():
    """has_assembly & 未注入 → template+production（让 R4/R5 抓模板冒充）。核心致命门。"""
    blocks = _synth_execution_blocks(market="stocks_cn", has_assembly=True, assembly_injected=False)
    assert blocks and len(blocks) == 1
    assert blocks[0]["mode"] == MODE_TEMPLATE, blocks
    assert blocks[0]["result_grade"] == GRADE_PRODUCTION, blocks


def test_helper_injected_maps_to_live_with_source():
    """has_assembly & 真注入 → live + live_source_ref（注入落地后路径·绝不留空源）。"""
    blocks = _synth_execution_blocks(
        market="crypto_perp", has_assembly=True, assembly_injected=True,
        live_source_ref="binance://btcusdt/1d",
    )
    assert blocks and blocks[0]["mode"] == MODE_LIVE
    assert blocks[0]["live_source_ref"] == "binance://btcusdt/1d"


def test_helper_no_assembly_returns_none():
    """无组装 → None（向后兼容·不污染既有 run.json）。"""
    assert _synth_execution_blocks(
        market="crypto_perp", has_assembly=False, assembly_injected=False
    ) is None


# ════════════════════════════════════════════════════════════════════════════
# 对抗①：模板基线必被 R4 抓（端到端·_synth_and_promote 真产 run.json → 组装器 → evaluate_release）
# ════════════════════════════════════════════════════════════════════════════
@needs_btc
def test_synth_with_assembly_writes_template_block_caught_by_R4(iso):
    """§16 致命闭合：用户组装却未注入 → run.json 必留 template+production 执行块，组装器→R4(template
    false success)+R5(生产走非 live) 硬拒。

    种坏门：producer 不写块 / 写成 live 冒充 → 致命门平凡过（漏「声称已采用却未注入」）→ 本断言 RED。
    """
    out = _synth_and_promote(
        args={"market": "crypto_perp", "strategy_goal_ref": "g-assembly", "lookback": 20,
              "factor_set": "fs_abc123", "model_id": "lgbm_rank_6f",
              "market_data_use_validation_refs": MARKET_DATA_USE_REFS},
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=None, verifier=None, llm_client=None, market_data_registry=_MarketDataUseRegistry(),
    )
    assert out.get("error") is None, out
    run_id = out["run_id"]
    run_json = json.loads(
        (iso["root"] / "artifacts" / "experiments" / run_id / "run.json").read_text(encoding="utf-8")
    )
    # ① producer 真写了 template+production 块（绝不写 live 冒充）。
    blocks = run_json.get("execution_blocks")
    assert blocks and len(blocks) == 1, run_json
    assert blocks[0]["mode"] == MODE_TEMPLATE, blocks       # 未注入 → template，非 live
    assert blocks[0]["result_grade"] == GRADE_PRODUCTION, blocks
    # ② 组装器读 run.json → evaluate_release：Mock 诚实门 R4 + R5 硬拒（弱标签下唯一失败门即此）。
    v = evaluate_run_releasable(run_json)
    assert v.ok is False, v.reason_text
    codes = _mock_gate_missing(v)
    assert TEMPLATE_FALSE_SUCCESS in codes, codes            # §16 ②：template 不生成 production success
    assert PRODUCTION_VIA_NON_LIVE in codes, codes           # §16 致命：生产结果走非 live
    # ③ assembly_inputs 仍诚实落账（扩展不替换·不动既有 M1 诚实披露）。
    assert run_json.get("assembly_inputs", {}).get("factor_set") == "fs_abc123", run_json
    assert out.get("assembly_injected") is False


# ════════════════════════════════════════════════════════════════════════════
# 对抗④（part A）：无组装 → 不写块、Mock 诚实门平凡过（向后兼容·不误伤诚实基线）
# ════════════════════════════════════════════════════════════════════════════
@needs_btc
def test_synth_without_assembly_writes_no_block_backward_compat(iso):
    out = _synth_and_promote(
        args={"market": "crypto_perp", "strategy_goal_ref": "g-plain", "lookback": 20,
              "market_data_use_validation_refs": MARKET_DATA_USE_REFS},
        ledger=iso["ledger"], returns_store=None, data_root=iso["root"],
        verdict_store=None, verifier=None, llm_client=None, market_data_registry=_MarketDataUseRegistry(),
    )
    assert out.get("error") is None, out
    run_json = json.loads(
        (iso["root"] / "artifacts" / "experiments" / out["run_id"] / "run.json").read_text(encoding="utf-8")
    )
    assert "execution_blocks" not in run_json, "无组装不应写 execution_blocks（不污染既有 run.json）"
    v = evaluate_run_releasable(run_json)
    assert not _mock_gate_missing(v), "无执行块 → Mock 诚实门应平凡过（不误伤诚实动量基线）"


# ════════════════════════════════════════════════════════════════════════════
# 对抗②：真 live 注入不误伤（promote 透传 live+source → Mock 诚实门放行）
# ════════════════════════════════════════════════════════════════════════════
def test_live_injection_block_not_false_flagged(tmp_path):
    blocks = [{"block_id": "synth_crypto_perp", "mode": MODE_LIVE,
               "result_grade": GRADE_PRODUCTION, "live_source_ref": "binance://btcusdt/1d"}]
    _, run_json = _promote_with_blocks(tmp_path, blocks)
    assert run_json["execution_blocks"][0]["mode"] == MODE_LIVE
    v = evaluate_run_releasable(run_json)
    assert not _mock_gate_missing(v), f"live+source 块不应被 Mock 诚实门拒：{v.reason_text}"
    assert v.ok is True, v.reason_text  # 弱标签 + live+source + 无其它缺 → 整体可发版


def test_live_injection_without_source_still_caught_R3(tmp_path):
    """诚实边界：声明 live 却无 source（伪 live）→ R3 拒——证「写 live 不等于免检」。"""
    blocks = [{"block_id": "b", "mode": MODE_LIVE, "result_grade": GRADE_PRODUCTION,
               "live_source_ref": ""}]
    _, run_json = _promote_with_blocks(tmp_path, blocks)
    v = evaluate_run_releasable(run_json)
    assert LIVE_NO_SOURCE in _mock_gate_missing(v), v.reason_text


# ════════════════════════════════════════════════════════════════════════════
# 对抗③：mock 必挂标识（未挂 → R1 拒；挂上 → 放行·门有牙）
# ════════════════════════════════════════════════════════════════════════════
def test_silent_mock_block_rejected_R1(tmp_path):
    unmarked = [{"block_id": "probe", "mode": MODE_MOCK, "result_grade": GRADE_EXPLORATORY,
                 "mock_marked": False}]
    _, run_json = _promote_with_blocks(tmp_path, unmarked, owner="m1")
    v = evaluate_run_releasable(run_json)
    assert MOCK_UNMARKED in _mock_gate_missing(v), v.reason_text
    # MUT：挂上标识即必绿（补回标识就过——门不是纸做的）。
    marked = [{**unmarked[0], "mock_marked": True}]
    _, run_json2 = _promote_with_blocks(tmp_path, marked, owner="m2")
    v2 = evaluate_run_releasable(run_json2)
    assert not _mock_gate_missing(v2), v2.reason_text


# ════════════════════════════════════════════════════════════════════════════
# 对抗④（part B）：promote 不传 execution_blocks → 无该键、行为不变
# ════════════════════════════════════════════════════════════════════════════
def test_promote_without_execution_blocks_backward_compat(tmp_path):
    promoted = promote_ide_run(
        ide_run_id="x", owner_username="a", strategy_name="s", strategy_code="",
        result={"equity_curve": _curve(30)}, run_root=tmp_path,
    )
    run_json = json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))
    assert "execution_blocks" not in run_json
    # 既有键一字不少（扩展不替换）。
    for k in ("run_id", "strategy_name", "market", "metrics", "source"):
        assert k in run_json
    v = evaluate_run_releasable(run_json)
    assert not _mock_gate_missing(v), "无块 → Mock 诚实门平凡过"


# ════════════════════════════════════════════════════════════════════════════
# 对抗⑤：不静默改裁决——写块只是【补数据】，promote 本身仍成功；§16 裁决只在显式跑组装器时发生
# ════════════════════════════════════════════════════════════════════════════
def test_promote_only_adds_data_does_not_gate_at_promote_time(tmp_path):
    bad = [{"block_id": "synth", "mode": MODE_TEMPLATE, "result_grade": GRADE_PRODUCTION}]
    promoted, run_json = _promote_with_blocks(tmp_path, bad, owner="g5")
    # promote 不拒（只补数据·未接端点）：run_id + portfolio.csv 照常产出。
    assert promoted.run_id
    assert (promoted.run_dir / "portfolio.csv").exists()
    for k in ("run_id", "strategy_name", "market", "metrics", "source"):
        assert k in run_json, "扩展不替换：既有 run.json 键不得丢"
    # 只有【显式】跑组装器→evaluate_release 才裁（裁决不在 promote 路径里·不静默改）。
    assert evaluate_run_releasable(run_json).ok is False
