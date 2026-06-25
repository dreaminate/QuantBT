# -*- coding: utf-8 -*-
"""RDP 接线【对抗式】测试（卡 D-RDP-1 wire · 北极星总闸 §17）。

接线 = 把已建的 §17 RDP schema + 4 拒绝门接进【真 promote 路径】+【现导出器】。
本文件【扩展不替换】test_rdp_gate.py（那测 4 门本体；这测接线后的端到端行为）。

可证伪验收（RULES §2「种已知坏门必抓」· MUT 定点反向）：
  ① promote 带残缺 RDP（缺 manifest/hash/repro/DatasetVersion/未验证残余）→ 拒晋级（端到端）。
     MUT：把 require_promotion_rdp 改弱（吞 RDPRejected / 不调）→ 残缺也晋级 → 本文件转红。
     反向锚（同一现实里证门承重）：rdp=None 的同款晋级【成功】——差量即门的承重证据。
  ② 现导出器 6 字段进 RDPManifest 不破 RunDetailPage「收益概述」冻结（仅加字段 / 加文件）。
  ③ 残缺 RDP → verdict blocked/missing，绝不美化成完整交付（§3 不假绿灯）。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.approval import ApprovalGateService, ApprovalGateStore, EvidenceSnapshot
from app.delivery import (
    ASSET_MODEL,
    ASSET_STRATEGYBOOK,
    DatasetVersionRef,
    PromotionClaim,
    RDPRejected,
    require_promotion_rdp,
    validate_rdp,
)
from app.lineage.ledger import Ledger
from app.paper.desk import PaperDeskService
from run_detail_research_export import (
    OverviewRow,
    build_overview_rows,
    build_rdp_from_run_bundle,
    export_run_bundle_for_detail,
)

# RunDetailPage「收益概述」冻结口径：OverviewRow 的 7 列（date + 6 指标），接 RDP 绝不改这套。
_FROZEN_OVERVIEW_KEYS = {
    "date",
    "strategy_return",
    "benchmark_return",
    "excess_daily",
    "turnover",
    "daily_buy",
    "daily_sell",
}


# ── builders ──────────────────────────────────────────────────────────────────
def _df() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2]})


def _complete_rdp(run_id="run_x", asset_ref="run:run_x", asset_kind=ASSET_STRATEGYBOOK, **over):
    """经导出器投影 + 显式补齐 §17 门强制字段 → 一份过门1-3 的有效 RDP。"""

    fields = dict(
        strategy_py="def strat(): ...",
        report_md="# 研究报告",
        attribution=_df(),
        artifact_hash="a1b2c3d4e5f60718",
        reproducibility_command="python -m app.backend.reproduce --rdp rdp_xxx --seed 7",
        dataset_versions=(DatasetVersionRef("csi300_daily", "2025-12-31", "deadbeefcafef00d"),),
        ingestion_skill_refs=("tushare_daily_ohlcv@v2",),
        unverified_residual=("样本外仅 1 个 regime；成本用静态假设未压测冲击成本",),
    )
    fields.update(over)
    return build_rdp_from_run_bundle(run_id, {"run_id": run_id}, asset_ref=asset_ref,
                                     asset_kind=asset_kind, **fields)


def _incomplete_rdp(run_id="run_x", asset_ref="run:run_x", asset_kind=ASSET_STRATEGYBOOK):
    """纯 run-bundle 投影（6 字段无 hash/repro/dataset/血统/残余）→ 残缺 RDP（门必拒）。"""

    return build_rdp_from_run_bundle(
        run_id, {"run_id": run_id}, asset_ref=asset_ref, asset_kind=asset_kind,
        strategy_py="def strat(): ...", report_md="# r",
        trades=_df(), positions=_df(), attribution=_df(), log_text="backtest log line",
    )


def _claim(rdp, *, asset_ref=None, asset_kind=ASSET_STRATEGYBOOK):
    return PromotionClaim(
        asset_ref=asset_ref if asset_ref is not None else rdp.asset_ref,
        asset_kind=asset_kind, rdp_ref=rdp.rdp_id,
    )


def _tmp_eqlog(name: str) -> Path:
    return Path(tempfile.mkdtemp()) / f"{name}_equity.jsonl"


def _eligible_run(svc: PaperDeskService, run_id: str, creator="alice"):
    """注册一条【4 门全过】的 paper run（除 RDP 外无阻塞），便于隔离 RDP 闸效果。"""

    svc.register_run(
        run_id=run_id, name=run_id, origin="o", market="crypto", symbols=["BTCUSDT"],
        bench="BTC", creator=creator, equity_log_path=_tmp_eqlog(run_id), simulate=False,
        days_running=30, paper_excess_return=0.02, backtest_annual=0.2, paper_annual=0.18,
    )


# ════════════════ ① paper desk promote：残缺 RDP → 拒晋级（端到端 + MUT 差量）════════════════
def test_paperdesk_promote_with_incomplete_rdp_rejected():
    """种坏门：合规人工审批 + 4 门全过，但带【残缺 RDP】→ require_promotion_rdp 在翻态前拒，未晋级。"""

    svc = PaperDeskService()
    _eligible_run(svc, "pd_incomplete")
    gate = svc.open_promotion_gate("pd_incomplete", creator="alice")
    rdp = _incomplete_rdp(asset_ref="run:pd_incomplete")
    with pytest.raises(RDPRejected):
        svc.approve_promotion(
            gate.gate_id, approver="bob", endorsement_ref="verdict_1",
            reason="异模型对账一致，超额稳定，适用域已核",
            rdp=rdp, promotion_claim=_claim(rdp),
        )
    assert svc.get("pd_incomplete").promoted is False, "残缺 RDP 却翻了 promoted（RDP 闸被绕，门坏）"
    gate_after = svc.get_promotion_gate(gate.gate_id)
    assert gate_after.decision == "pending", "残缺 RDP 拒后门须仍 pending（未 fail-open 进 approved）"


def test_paperdesk_promote_rdp_enforcement_is_load_bearing_mut():
    """MUT 承重锚（无 git-checkout）：同款合规晋级——

    · rdp=None（默认 · 向后兼容）→ 晋级【成功】（基线不破）。
    · rdp=残缺 → 晋级【被拒】。
    差量证明 require_promotion_rdp 是承重闸；若把它改弱成放行，残缺分支也会成功 → 上面 raises 转红。
    """

    svc = PaperDeskService()
    # A：不带 RDP → 既有行为不变，晋级成功（基线锚）。
    _eligible_run(svc, "pd_none")
    g_a = svc.open_promotion_gate("pd_none", creator="alice")
    out = svc.approve_promotion(g_a.gate_id, approver="bob", endorsement_ref="v1",
                                reason="异模型对账一致超额稳定适用域已核")
    assert out.decision == "approved" and svc.get("pd_none").promoted is True

    # B：带残缺 RDP → 同样合规人审却被 RDP 闸拒（与 A 唯一差量 = RDP）。
    _eligible_run(svc, "pd_bad")
    g_b = svc.open_promotion_gate("pd_bad", creator="alice")
    bad = _incomplete_rdp(asset_ref="run:pd_bad")
    with pytest.raises(RDPRejected):
        svc.approve_promotion(g_b.gate_id, approver="bob", endorsement_ref="v1",
                              reason="异模型对账一致超额稳定适用域已核",
                              rdp=bad, promotion_claim=_claim(bad))
    assert svc.get("pd_bad").promoted is False


def test_paperdesk_promote_require_rdp_but_none_rejected():
    """require_rdp=True 但晋级未带任何 RDP → 拒（§17：晋级资产无法追溯 RDP → 拒）。"""

    svc = PaperDeskService()
    _eligible_run(svc, "pd_require")
    gate = svc.open_promotion_gate("pd_require", creator="alice")
    with pytest.raises(RDPRejected):
        svc.approve_promotion(gate.gate_id, approver="bob", endorsement_ref="v1",
                              reason="异模型对账一致超额稳定适用域已核", require_rdp=True)
    assert svc.get("pd_require").promoted is False


def test_paperdesk_promote_with_complete_rdp_and_claim_succeeds():
    """承重闸不是一刀切砖墙：完整 RDP + 匹配追溯断言 → 晋级放行（门4 真追溯到本资产的有效 RDP）。"""

    svc = PaperDeskService()
    _eligible_run(svc, "pd_ok")
    gate = svc.open_promotion_gate("pd_ok", creator="alice")
    rdp = _complete_rdp(run_id="pd_ok", asset_ref="run:pd_ok")
    assert validate_rdp(rdp).ok, "前置：构造的 RDP 应过门1-3"
    out = svc.approve_promotion(
        gate.gate_id, approver="bob", endorsement_ref="verdict_1",
        reason="异模型对账一致，超额稳定，适用域已核",
        rdp=rdp, promotion_claim=_claim(rdp),
    )
    assert out.decision == "approved" and svc.get("pd_ok").promoted is True


def test_paperdesk_promote_rdp_asset_mismatch_rejected():
    """张冠李戴：RDP 完整但追溯断言指向【别的资产】→ 门4 拒（不拿别资产的 RDP 背书本资产）。"""

    svc = PaperDeskService()
    _eligible_run(svc, "pd_mismatch")
    gate = svc.open_promotion_gate("pd_mismatch", creator="alice")
    rdp = _complete_rdp(run_id="pd_mismatch", asset_ref="run:pd_mismatch")
    wrong_claim = _claim(rdp, asset_ref="run:some_other_asset")  # asset_ref 与 RDP 不符
    with pytest.raises(RDPRejected):
        svc.approve_promotion(gate.gate_id, approver="bob", endorsement_ref="v1",
                              reason="异模型对账一致超额稳定适用域已核",
                              rdp=rdp, promotion_claim=wrong_claim)
    assert svc.get("pd_mismatch").promoted is False


# ════════════════ ① ApprovalGateService promote：残缺 RDP → 拒、不翻 stage ════════════════
def _appsvc(tmp_path):
    return ApprovalGateService(ApprovalGateStore(tmp_path), ledger=Ledger(tmp_path / "ledger"))


def _good_evidence():
    return EvidenceSnapshot(
        config_hash="cfg_v1_aaaa", dataset_version="ds1", n_eff=5, n_trials_raw=5,
        dsr=0.92, pbo=0.10, bootstrap_ci=(0.4, 1.8), bootstrap_estimate=1.0,
        champion_challenger={"verdict": "challenger_wins", "delta_sharpe": 0.3},
        returns_sha256="r1",
    ).to_dict()


def _pending_model_gate(svc, created_by="alice"):
    return svc.open_gate(
        model_id="m1", version=2, from_stage="dev", to_stage="production",
        action_kind="promote_production", created_by=created_by,
        verification_record_id="v-1", evidence=_good_evidence(), strategy_goal_ref="theme",
    )


_REASON = "独立验证官异模型复核一致，三角同向，适用域已核"


def test_approvalgate_approve_with_incomplete_rdp_rejected_stage_not_flipped(tmp_path):
    """种坏门：confirmatory 晋级 approve 带残缺 RDP → RDPRejected，gate 不进 approved（stage 不翻）。"""

    svc = _appsvc(tmp_path)
    gate = _pending_model_gate(svc, created_by="alice")
    assert gate.decision == "pending"
    rdp = _incomplete_rdp(asset_ref="model:m1@v2", asset_kind=ASSET_MODEL)
    applied = {"n": 0}

    def _exec(_g):
        applied["n"] += 1
        return "ref-1"

    with pytest.raises(RDPRejected):
        svc.approve(gate.gate_id, approver="bob", reason=_REASON, execute_fn=_exec,
                    rdp=rdp, promotion_claim=_claim(rdp, asset_ref="model:m1@v2", asset_kind=ASSET_MODEL))
    assert applied["n"] == 0, "残缺 RDP 却跑了门后副作用（fail-open，门坏）"
    assert svc._store.get(gate.gate_id).decision == "pending", "残缺 RDP 拒后须仍 pending（stage 未翻）"


def test_approvalgate_approve_require_rdp_but_none_rejected(tmp_path):
    """require_rdp=True + 未带 RDP → 拒（§17 追溯缺失）；stage 不翻。"""

    svc = _appsvc(tmp_path)
    gate = _pending_model_gate(svc, created_by="alice")
    with pytest.raises(RDPRejected):
        svc.approve(gate.gate_id, approver="bob", reason=_REASON, require_rdp=True)
    assert svc._store.get(gate.gate_id).decision == "pending"


def test_approvalgate_approve_with_complete_rdp_flips_stage(tmp_path):
    """完整 RDP + 匹配追溯 → approve 放行并跑门后副作用（execute_fn 真翻 stage）。"""

    svc = _appsvc(tmp_path)
    gate = _pending_model_gate(svc, created_by="alice")
    rdp = _complete_rdp(run_id="m1v2", asset_ref="model:m1@v2", asset_kind=ASSET_MODEL)
    applied = {"n": 0}

    def _exec(_g):
        applied["n"] += 1
        return "ref-ok"

    out = svc.approve(
        gate.gate_id, approver="bob", reason=_REASON, execute_fn=_exec,
        rdp=rdp, promotion_claim=_claim(rdp, asset_ref="model:m1@v2", asset_kind=ASSET_MODEL),
    )
    assert out.decision == "approved" and out.side_effect_ref == "ref-ok" and applied["n"] == 1


def test_approvalgate_baseline_no_rdp_still_approves(tmp_path):
    """基线不破：不带 RDP 参数（默认 no-op）→ 既有 confirmatory approve 流程零行为变化。"""

    svc = _appsvc(tmp_path)
    gate = _pending_model_gate(svc, created_by="alice")
    out = svc.approve(gate.gate_id, approver="bob", reason=_REASON, execute_fn=lambda g: "x")
    assert out.decision == "approved"


# ════════════════ ② 现导出器 6 字段进 RDP 不破「收益概述」冻结 ════════════════
def test_overview_row_frozen_schema_unchanged():
    """OverviewRow 冻结口径 = 7 列（date + 6 指标），接 RDP 后绝不增删改这套键。"""

    assert set(OverviewRow.__annotations__) == _FROZEN_OVERVIEW_KEYS


def test_build_rdp_does_not_touch_overview_rows():
    """对抗：构造 RDP 前后 build_overview_rows 输出逐字节一致（RDP 接线零侵入冻结页计算）。"""

    equity = [
        {"timestamp": "2026-01-01T00:00:00Z", "value": 100},
        {"timestamp": "2026-01-02T00:00:00Z", "value": 101},
    ]
    bench = [{"timestamp": "2026-01-01T00:00:00Z", "value": 0}]
    rows_before = build_overview_rows(equity, bench, [], [], [])
    # 在两次计算之间构造一份 RDP（若接线污染了全局/冻结逻辑，rows_after 会偏）。
    _ = _complete_rdp()
    rows_after = build_overview_rows(equity, bench, [], [], [])
    assert rows_before == rows_after
    for row in rows_after:
        assert set(row.keys()) == _FROZEN_OVERVIEW_KEYS, "收益概述行混入了非冻结字段（冻结被破，红线）"


def test_export_emits_rdp_json_additively(tmp_path, monkeypatch):
    """export_run_bundle_for_detail 带 rdp → 额外写 rdp.json（开放格式可解析、往返同 id）；

    且 run.json / portfolio.csv 与【不带 rdp】时逐字节一致——只加文件，不改既有产物（扩展不替换）。
    """

    import run_detail_research_export as rde

    monkeypatch.setattr(rde, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(rde, "ensure_runtime_dirs", lambda: None)
    portfolio = pd.DataFrame({"date": ["2026-01-01"], "equity": [1.0]})
    manifest = {"run_id": "exp_base", "status": "completed"}

    # 不带 rdp（既有行为）：无 rdp.json。
    root0 = rde.export_run_bundle_for_detail("exp_base", manifest, portfolio, overwrite=True)
    assert (root0 / "run.json").is_file() and (root0 / "portfolio.csv").is_file()
    assert not (root0 / "rdp.json").exists(), "未传 rdp 却写了 rdp.json（非向后兼容）"
    run_json_baseline = (root0 / "run.json").read_text(encoding="utf-8")

    # 带 rdp：额外 rdp.json，run.json 不变（additive）。
    rdp = _complete_rdp(run_id="exp_rdp", asset_ref="run:exp_rdp")
    root1 = rde.export_run_bundle_for_detail(
        "exp_rdp", {"run_id": "exp_rdp", "status": "completed"}, portfolio, overwrite=True, rdp=rdp,
    )
    assert (root1 / "rdp.json").is_file(), "传了 rdp 却没写 rdp.json"
    parsed = json.loads((root1 / "rdp.json").read_text(encoding="utf-8"))  # 纯 JSON 第三方可解析
    assert parsed["rdp_id"] == rdp.rdp_id and parsed["asset_ref"] == "run:exp_rdp"
    # run.json 仍是同款结构（仅 run_id 不同），未被 rdp 写入污染。
    assert run_json_baseline.replace("exp_base", "exp_rdp") == (root1 / "run.json").read_text(encoding="utf-8")


def test_export_six_fields_flow_into_rdp():
    """6 字段（strategy_py/report_md/log_text/attribution/trades/positions）真投影进 RDP 对应槽。"""

    rdp = build_rdp_from_run_bundle(
        "flow", {"run_id": "flow"}, asset_ref="run:flow",
        strategy_py="def s(): ...", report_md="# r", log_text="log",
        attribution=_df(), trades=_df(), positions=_df(),
    )
    assert "strategy.py" in rdp.source_file_refs and "strategy.py" in rdp.code_refs
    assert "report.md" in rdp.source_file_refs and "backtest.log" in rdp.source_file_refs
    assert rdp.backtest_run_refs == ("flow",)
    assert "attribution.csv" in rdp.attribution


# ════════════════ ③ 残缺 RDP → verdict missing，不美化完整 ════════════════
def test_incomplete_rdp_verdict_lists_missing_not_beautified():
    """纯导出器投影（无门强制字段）→ validate_rdp 不 ok，诚实列 missing，不冒充完整交付。"""

    rdp = _incomplete_rdp()
    v = validate_rdp(rdp)
    assert not v.ok, "残缺 RDP 不得判 ok（§3 不假绿灯）"
    missing = set(v.missing)
    # §17 门强制项缺哪些就报哪些——artifact hash / repro / DatasetVersion / IngestionSkill / 未验证残余。
    for need in ("artifact_hash", "reproducibility_command", "dataset_versions",
                 "ingestion_skill_refs", "unverified_residual"):
        assert need in missing, f"残缺项 {need} 未被诚实标 missing（验收③ 美化了残缺）"
    assert "拒" in v.reason_text and "通过" not in v.reason_text


def test_require_promotion_rdp_default_noop_backward_compatible():
    """接线闸默认形态：rdp=None + require_rdp=False → 返 None 放行（不破既有未带 RDP 的晋级）。"""

    assert require_promotion_rdp(None) is None
    assert require_promotion_rdp(None, require_rdp=False) is None
