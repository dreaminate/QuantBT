"""§16 advisory-first 接线（D-RELEASE-ADVISORY·中心第十二波）：

第十/十一波建了 release_gate.promote_assembler（run.json→ReleaseCandidate→evaluate_release）+
promote 执行诚实落账。本波中心把 `evaluate_run_releasable` 接进 `promote_ide_run`——每个 promoted
run 的 run.json 现携带可追溯的 `release_verdict`（§16 八门聚合裁决·ok + 缺口）。

**advisory-first 不变量**（本测试守门）：
- 接线后 release gate **真在 promote 路径上跑**（run.json 必含 release_verdict）；
- **只记录、绝不在 promote 时 reject 晋级**——即便 §16 裁 ok=False（如模板基线冒充），promote 仍成功
  落盘（晋级是否硬卡 = 后续显式 enforce 决策·本波不预先削弱、不破基线）；
- 防御式：release 自检异常绝不破 promote（落 available:False 诚实标·不静默吞）。
"""

import json

import pytest

from app.ide.promote import promote_ide_run


def _curve(n: int) -> list[dict]:
    """最小可 promote 的 equity_curve（镜像 test_promote_execution_honesty._curve）。"""
    return [{"timestamp": f"2024-01-{i + 1:02d}T00:00:00Z", "equity": 1000.0 + i} for i in range(n)]


def _promote(tmp_path, *, execution_blocks=None):
    promoted = promote_ide_run(
        ide_run_id="ide_adv_1", owner_username="alice", strategy_name="adv 策略",
        strategy_code="quantbt.emit_result({})", result={"equity_curve": _curve(30)},
        run_root=tmp_path, execution_blocks=execution_blocks,
    )
    manifest = json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))
    return promoted, manifest


def test_promote_attaches_release_verdict(tmp_path):
    """接线后每个 promoted run 的 run.json 必含 release_verdict（§16 门真在 promote 跑）。"""
    _, manifest = _promote(tmp_path)
    assert "release_verdict" in manifest, "promote 后 run.json 必含 release_verdict（gate 接进 promote 路径）"
    verdict = manifest["release_verdict"]
    assert "ok" in verdict, "release_verdict 必含 ok 字段"
    assert "honest_gaps" in verdict and "rejections" in verdict, "release_verdict 必含缺口/拒因（可追溯）"


def test_clean_weak_run_release_verdict_ok(tmp_path):
    """无特殊证据的弱标签 run → §16 硬门全过（ok=True）、缺口走软披露（不误伤正路径）。"""
    _, manifest = _promote(tmp_path)
    assert manifest["release_verdict"]["ok"] is True, "弱标签裸 run 不应被 §16 硬门误拒"


def test_template_baseline_recorded_not_ok_but_promote_succeeds(tmp_path):
    """★ advisory 核心：模板基线冒充（template+production 块）→ §16 裁 ok=False 且记录，
    但 promote **仍成功落盘**（只记录不 reject·晋级不在此硬卡）。"""
    blocks = [{"mode": "template", "result_grade": "production", "block_id": "tpl_1"}]
    promoted, manifest = _promote(tmp_path, execution_blocks=blocks)
    # ① 裁决记录：ok=False（R4 template 标 production / R5 生产走非 live）。
    verdict = manifest["release_verdict"]
    assert verdict["ok"] is False, "模板基线冒充应被 §16 裁 ok=False（R4/R5）"
    gate_ids = {o.get("gate_id") for o in verdict["rejections"]}
    assert "gate_mock_honesty" in gate_ids, f"模板冒充应由 mock 诚实门拒，实际拒门={gate_ids}"
    # ② advisory 不阻断：promote 仍成功（run_id + portfolio.csv 在·run.json 已落盘）。
    assert promoted.run_id, "advisory 裁 ok=False 绝不阻断 promote（run 仍成功落盘）"
    assert (promoted.run_dir / "portfolio.csv").exists(), "promote 主流程产物仍在（advisory 不破 promote）"


def test_backward_compat_existing_manifest_keys_intact(tmp_path):
    """接线 additive：run.json 既有键（run_id/status/metrics/source）不丢。"""
    _, manifest = _promote(tmp_path)
    for key in ("run_id", "status", "metrics", "source", "strategy_name"):
        assert key in manifest, f"既有 manifest 键 {key!r} 不应因 advisory 接线丢失"


def test_advisory_verdict_is_json_safe(tmp_path):
    """release_verdict 必 JSON-safe（已落盘 run.json·能再读回·无 NaN/对象残留）。"""
    blocks = [{"mode": "live", "result_grade": "production", "block_id": "l1", "live_source_ref": "ds://x"}]
    _, manifest = _promote(tmp_path, execution_blocks=blocks)
    # 已经 json.loads 成功即证 JSON-safe；再 dumps 一遍确认无非序列化残留。
    json.dumps(manifest["release_verdict"])
