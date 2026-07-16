"""§17 RDP advisory-first slice · 对抗测试（RULES §2 种坏门必抓 + §3 诚实 + advisory 不破基线）。

本切片：promote 路径无 persisted canonical RDP 时，用现有 `delivery.aggregate_rdp` 单一源从**本链真在
scope 的工件**（run 身份 + result artifact + 已解析的 LLMCallRecord）组装一份**透明 advisory RDP**，喂进
`promote_assembler` 既有 honest-empty §17 seam；**require_rdp 保持 False、s17_rdp producer 不转绿**——
门经 SA-2 降级 advisory，只记录不阻断。诚实两栏（RULES §3 crux）：
  · gate1 `reproducibility_command` = 显式文档（"not executable authority"·权威=ReproductionReceipt·本 RDP 不claim）
  · gate3 `unverified_residual` = 诚实枚举"未验证什么"（跨厂商 LLM 复审待凭据 / 无重现收据 / typed 血统未解析）

可证伪验收（每条种坏门·去掉守卫即红）：
  ① 组装 RDP 缺 unverified_residual → section17_rdp_check ok=False·'unverified_residual' ∈ missing（gate3 咬穿新接线）
  ② promotion.rdp_ref ≠ 组装 rdp_id → gate4 追溯拒（'rdp_ref' ∈ missing）
  ③ 明文 secret 进自由文本字段 → SecretLeakError（attach 之前·实盘 key 不进 RDP）
  ④ 基线：不带 advisory flag 的 promote 仍成功且 section17 诚实 undeclared（不回归）
  ⑤ advisory producer 绝不转绿（HARD 约束：s17_rdp_runjson_producers 保持 non-green）

★ mutation 三态（已手验·见任务报告）：把 `section17_rdp_gate.section17_rdp_check` 里 `if validation.ok:`
  弱化成 `if True:`（无视 delivery.validate_rdp 裁定）→ ①②（及 producer 仍-advisory 里的 ok=False 断言）
  转 RED → 还原 → GREEN。另：删 `aggregator.py` 门3 传参（unverified_residual 恒补 [] 洗白）→ ① 红。
"""

from __future__ import annotations

import json

import pytest

# 冷导入预热（既有循环解环·与 test_section17_rdp_gate 同款）：promotion_evidence/section17 门
# 触达 app.governance.enforcement_policy·先全载 orchestrator 解环。
import app.agent.orchestrator  # noqa: F401

from app.delivery.aggregator import aggregate_rdp  # noqa: E402
from app.delivery.rdp import PromotionClaim  # noqa: E402
from app.ide.promote import promote_ide_run  # noqa: E402
from app.ide.promotion_evidence import assemble_advisory_rdp  # noqa: E402
from app.llm.call_record import SecretLeakError  # noqa: E402
from app.release_gate.section17_rdp_gate import (  # noqa: E402
    SECTION17_RDP_MANIFEST_KEY,
    section17_rdp_check,
)

_SECRET = "sk-ant-LIVE-0123456789abcdefDEADBEEFcafef00d"  # 测试用假实盘 key（绝不入 RDP）


def _curve(n: int) -> list[dict]:
    return [{"timestamp": f"2024-01-{i + 1:02d}T00:00:00Z", "equity": 1000.0 + i} for i in range(n)]


def _promote(tmp_path, *, attach_advisory_rdp: bool = False):
    promoted = promote_ide_run(
        ide_run_id="ide_adv_1",
        owner_username="alice",
        strategy_name="adv 策略",
        strategy_code="quantbt.emit_result({})",
        result={"equity_curve": _curve(30)},
        run_root=tmp_path,
        attach_advisory_rdp=attach_advisory_rdp,
    )
    manifest = json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))
    return promoted, manifest


def _section_of(rdp, promotion: PromotionClaim | None = None) -> dict:
    section: dict = {"rdp": rdp.to_dict()}
    if promotion is not None:
        section["promotion"] = promotion.to_dict()
    return {"run_id": "ide_promote_test", "status": "completed", SECTION17_RDP_MANIFEST_KEY: section}


# ════════════ 组装诚实性：两栏手写·gate1/gate3 真过·gate2 诚实缺 ════════════
def test_advisory_producer_assembles_honest_rdp():
    a = assemble_advisory_rdp(
        asset_ref="ide_run_ABC",
        source_ref="ide_run:ide_ABC",
        artifact={"equity_curve": [1, 2, 3]},
        created_by="alice",
    )
    assert a is not None
    gates = {o.gate_id: o.passed for o in a.validation.outcomes}
    # gate1（repro+artifact_hash 诚实）与 gate3（残余诚实声明）真过·非空口。
    assert gates["gate1_manifest_completeness"] is True
    assert gates["gate3_unverified_residual"] is True
    # gate2 无 typed 血统 → 诚实缺（不伪造 dataset 放行）。
    assert gates["gate2_dataset_lineage"] is False
    assert a.ok is False  # advisory RDP 诚实不完整（非假绿灯）
    # repro 显式文档·非可执行权威。
    assert a.rdp.reproducibility_command.startswith("documentation only; not executable authority")
    # 残余诚实枚举未验证项（跨厂商 LLM 复审待凭据 + 无重现收据 + 无调用账）。
    residual = "\n".join(a.rdp.unverified_residual)
    assert "待用户凭据" in residual
    assert "ReproductionReceipt" in residual
    assert "未解析到任何 LLMCallRecord" in residual
    # artifact_hash 由真 artifact 经单一身份源派生（非编造）。
    from app.lineage.ids import content_hash

    assert a.rdp.artifact_hash == content_hash({"equity_curve": [1, 2, 3]})


def test_advisory_rdp_returns_none_without_identity():
    """无可解析资产身份 → None（无可诚实组装的·不伪造身份）。"""
    assert assemble_advisory_rdp(asset_ref="   ", artifact={"k": 1}) is None


# ════════════ 验收①：组装 RDP 缺 unverified_residual → gate3 咬穿新接线 ════════════
def test_advisory_rdp_missing_residual_gate3_bites():
    """MUT：section17_rdp_check 的 `if validation.ok` 弱化成 `if True` → ok 溜成 True → 本测转红。"""
    bad = aggregate_rdp(
        asset_ref="ide_run_ABC",
        asset_kind="",
        artifact={"k": 1},
        reproducibility_command="documentation only; not executable authority: x",
        unverified_residual=None,  # 种坏门：忘了声明未验证残余
    )
    cr = section17_rdp_check(_section_of(bad.rdp))
    assert cr.ok is False
    assert "unverified_residual" in cr.missing, cr.missing


# ════════════ 验收②：promotion.rdp_ref ≠ 组装 rdp_id → gate4 追溯拒 ════════════
def test_advisory_rdp_promotion_ref_mismatch_gate4_bites():
    a = assemble_advisory_rdp(asset_ref="ide_run_ABC", artifact={"k": 1})
    assert a is not None
    # 张冠李戴：晋级断言指向一个解析不到本 RDP 的 rdp_ref。
    promo = PromotionClaim(asset_ref=a.rdp.asset_ref, asset_kind="factor", rdp_ref="rdp_WRONG0000")
    cr = section17_rdp_check(_section_of(a.rdp, promo))
    assert cr.ok is False
    assert "rdp_ref" in cr.missing, cr.missing
    # 正例反证（gaming-proof）：rdp_ref 指向真 rdp_id → gate4 该项不再 miss。
    ok_promo = PromotionClaim(asset_ref=a.rdp.asset_ref, asset_kind="factor", rdp_ref=a.rdp.rdp_id)
    assert "rdp_ref" not in section17_rdp_check(_section_of(a.rdp, ok_promo)).missing


# ════════════ 验收③：明文 secret 进自由文本 → SecretLeakError（attach 之前）════════════
def test_advisory_rdp_plaintext_secret_raises_before_attach():
    """MUT：aggregator 不扫 RDP 开放面 → 不 raise → 红。secret 绝不回显。"""
    with pytest.raises(SecretLeakError) as exc:
        assemble_advisory_rdp(
            asset_ref="ide_run_ABC",
            artifact={"k": 1},
            known_limitations=[f"config leaked {_SECRET}"],
            known_secrets=[_SECRET],
        )
    assert _SECRET not in str(exc.value)  # 只报字段族泄露·不回显明文


# ════════════ 验收④：基线不带 flag → promote 成功 + section17 诚实 undeclared（不回归）════════════
def test_baseline_promote_without_flag_no_section17(tmp_path):
    promoted, manifest = _promote(tmp_path, attach_advisory_rdp=False)
    assert promoted.run_id  # promote 仍成功
    assert SECTION17_RDP_MANIFEST_KEY not in manifest  # 无 advisory RDP 挂载
    assert "section17_rdp_advisory" not in manifest
    # §17 节诚实 undeclared（未声明≠违例）。
    assert any("section17_rdp:undeclared" in g for g in manifest["section_assembly"]["honest_gaps"])
    # 既有 manifest 键不因接线丢失（additive）。
    for key in ("run_id", "status", "metrics", "source", "strategy_name"):
        assert key in manifest


# ════════════ 验收⑤：带 flag → attached + advisory-not-green + promote 成功 ════════════
def test_advisory_promote_attaches_and_stays_advisory(tmp_path):
    promoted, manifest = _promote(tmp_path, attach_advisory_rdp=True)
    assert promoted.run_id  # advisory 不阻断·promote 仍成功落盘
    assert (promoted.run_dir / "portfolio.csv").exists()
    # §17 节真被组装挂载（undeclared → 真 advisory RDP）。
    assert "rdp" in manifest[SECTION17_RDP_MANIFEST_KEY]
    assert "section17_rdp_advisory" in manifest
    assert manifest["section17_rdp_advisory"]["ok"] is False  # 诚实不完整（gate2）
    # HARD 约束：producer 绝不转绿·门经 SA-2 降级 advisory·all_producers_green=False。
    verdicts = manifest["promote_gate_chain"]["verdicts"]
    s17 = next(v for v in verdicts if v["gate_name"] == "s17_rdp")
    assert s17["advisory_or_enforce"] == "advisory"
    assert s17["producer_green"] is False
    assert manifest["promote_gate_chain"]["all_registered_producers_green"] is False


def test_advisory_promote_does_not_flip_release_ready(tmp_path):
    """advisory RDP 挂载不得把弱 run 洗成 release-ready（vacuous ok 冒充）。"""
    _, manifest = _promote(tmp_path, attach_advisory_rdp=True)
    assert manifest["release_verdict"]["release_ready"] is False
    assert manifest["promote_gate_chain"]["release_ready"] is False
