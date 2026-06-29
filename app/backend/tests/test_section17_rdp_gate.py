"""C-S17-RDP-PROMOTE-ENFORCE · §17 RDP 发版 check 插 SA-3 门链 · 对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

可证伪验收（construction-map C-S17-RDP-PROMOTE-ENFORCE·4 拒绝门全经 delivery.rdp_gate 单一源判定）：
  · 缺 artifact hash → check ok=False（missing=('artifact_hash',)）
  · 缺 reproducibility command → ok=False（'reproducibility_command'）
  · 缺 DatasetVersion / IngestionSkill ref → ok=False（'dataset_versions' / 'ingestion_skill_refs'）
  · 缺未验证残余 → ok=False（'unverified_residual'）
  · 晋级断言无 RDP 可追溯（self-promote without RDP）→ ok=False（'rdp'）
  · 晋级 rdp_ref/asset 张冠李戴 → ok=False（'rdp_ref' / 'asset_ref'）
  · 完整且可追溯 RDP → ok=True
门链合成（复用 SA-3/SA-2·非本卡重测）：
  · 注册 + producer 绿 → 整链 ENFORCE 拒不完整 RDP（blocks）
  · 注册 + producer 红/缺 → advisory：只记录不阻断（flip_refused·绝不误拒）
  · check 无 mode 字段 → 无法自封 enforce：mode 仅由 producer 绿灯翻（gaming-proof）
gameability：输入翻转 ok 跟着翻（非常量门）；复用 = missing 逐项来自 delivery.rdp_gate canonical validator。
fail-closed：section 非 dict / rdp|promotion 子对象非 dict / 空 rdp / asset_kind 非法 / dataset 非血统形态 /
  hollow（空白 artifact / 空白 ingestion / 空壳 DatasetVersion）→ 全 ok=False（违例绝不溜成 ok=True）。

★ producer 仍 RED（无假绿灯）：本卡**不建** producer 接线 `s17_rdp_runjson_producers`（把真血统/真 artifact
  hash 写进 manifest 那层 = 独立卡 C-S17-RUNJSON-PRODUCERS）。下方门链合成测试用**测试态本地**
  ProducerStatusLedger.mark_green(...) 证明 enforce 行为为真——绝非生产假绿灯（生产 producer_status 默认
  None=红·见 test_absent_producer_status_advisory_only）。

★ mutation 三态（已手验·见任务报告）：把 section17_rdp_gate.section17_rdp_check 里
  `if validation.ok:` 弱化成 `if True:`（无视 delivery.validate_rdp 裁定·让 incomplete RDP 溜成 ok=True）→
  `test_missing_artifact_hash_flagged` / `test_missing_dataset_version_flagged` /
  `test_missing_unverified_residual_flagged`（+ wrong-ref / green-enforce）转 RED → 还原 → GREEN。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_promote_gate_chain.py / test_section13_trust_gate.py 同款顺序（app.governance 包 __init__ 经
# spine_invariants 触达 orchestrator）。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

from app.delivery.rdp import RDPManifest  # noqa: E402
from app.delivery.rdp_gate import validate_rdp  # noqa: E402
from app.governance.enforcement_policy import (  # noqa: E402
    MODE_ADVISORY,
    MODE_ENFORCE,
    ProducerStatusLedger,
)
from app.release_gate.promote_gate_chain import (  # noqa: E402
    ChainResult,
    GateCheckResult,
    PromoteGateChain,
)
from app.release_gate.section17_rdp_gate import (  # noqa: E402
    SECTION17_RDP_GATE_NAME,
    SECTION17_RDP_MANIFEST_KEY,
    SECTION17_RDP_PRODUCER_KEY,
    register_section17_rdp_gate,
    section17_rdp_check,
)

# ════════════════════════════════════════════════════════════════════════════
# manifest 构造器（faithful §17 producer 契约·中心后续据此填）
# ════════════════════════════════════════════════════════════════════════════
# 一份**完整且诚实**的 RDP（过全部 4 门）：身份齐 + artifact hash + repro command + 可解析 DatasetVersion
# + IngestionSkill ref + 已列未验证残余。各对抗用例从此基线**删/篡一项**隔离出对应门。
_BASE_RDP = {
    "asset_ref": "factor::alpha_x",
    "asset_kind": "factor",
    "artifact_hash": "sha256:abc123",
    "reproducibility_command": "python -m quantbt.repro --run alpha_x",
    "dataset_versions": [{"dataset_id": "ds_csi300", "version": "v1", "manifest_sha256": "h::1"}],
    "ingestion_skill_refs": ["skill::tushare_daily"],
    "unverified_residual": ["执行成本未在 live 验证"],
}


def _manifest(section) -> dict:
    m = {"run_id": "ide_promote_test", "status": "completed"}
    if section is not None:
        m[SECTION17_RDP_MANIFEST_KEY] = section
    return m


def _drop(field: str) -> dict:
    """完整 RDP 删一项必填门字段（隔离出对应缺项门）。"""

    d = dict(_BASE_RDP)
    d.pop(field, None)
    return d


def _complete_section() -> dict:
    return {"rdp": dict(_BASE_RDP)}


def _rdp_id() -> str:
    """canonical 内容寻址 rdp_id（复用 RDPManifest.from_dict·与 check 重建同源·确定性）。"""

    return RDPManifest.from_dict(dict(_BASE_RDP)).rdp_id


def _green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION17_RDP_PRODUCER_KEY)  # 仅此卡测试态·绝非生产假绿灯
    return led


def _s17_verdict(result: ChainResult):
    matches = [v for v in result.verdicts if v.gate_name == SECTION17_RDP_GATE_NAME]
    assert len(matches) == 1, "门链中应恰有一道 §17 RDP 门裁定"
    return matches[0]


# ════════════════════════════════════════════════════════════════════════════
# ① check 层：缺项门必抓 + 完整必过（可证伪·mutation 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_missing_artifact_hash_flagged():
    """★ 可证伪①（mutation 目标）：缺 artifact hash → ok=False·精确缺项 'artifact_hash'。"""

    cr = section17_rdp_check(_manifest({"rdp": _drop("artifact_hash")}))
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is False
    assert "artifact_hash" in cr.missing


def test_missing_reproducibility_command_flagged():
    """可证伪②：缺 reproducibility command → ok=False·精确缺项 'reproducibility_command'。"""

    cr = section17_rdp_check(_manifest({"rdp": _drop("reproducibility_command")}))
    assert cr.ok is False
    assert "reproducibility_command" in cr.missing


def test_missing_dataset_version_flagged():
    """★ 可证伪③（mutation 目标）：缺 DatasetVersion → ok=False·精确缺项 'dataset_versions'。"""

    cr = section17_rdp_check(_manifest({"rdp": _drop("dataset_versions")}))
    assert cr.ok is False
    assert "dataset_versions" in cr.missing


def test_missing_ingestion_skill_flagged():
    """可证伪④：缺 IngestionSkill ref → ok=False·精确缺项 'ingestion_skill_refs'。"""

    cr = section17_rdp_check(_manifest({"rdp": _drop("ingestion_skill_refs")}))
    assert cr.ok is False
    assert "ingestion_skill_refs" in cr.missing


def test_missing_unverified_residual_flagged():
    """★ 可证伪⑤（mutation 目标）：缺未验证残余 → ok=False·精确缺项 'unverified_residual'（诚实闸）。"""

    cr = section17_rdp_check(_manifest({"rdp": _drop("unverified_residual")}))
    assert cr.ok is False
    assert "unverified_residual" in cr.missing


def test_complete_rdp_passes():
    """完整诚实 RDP（过 4 门）→ ok=True·无 missing。"""

    cr = section17_rdp_check(_manifest(_complete_section()))
    assert cr.ok is True
    assert cr.missing == ()


# ════════════════════════════════════════════════════════════════════════════
# ② 晋级可追溯（gate4·self-promote 防线）
# ════════════════════════════════════════════════════════════════════════════
def test_promotion_without_rdp_rejected_selfpromote():
    """★ self-promote without RDP：晋级断言在场却无 rdp → gate4「无 RDP 可追溯」→ ok=False（'rdp'）。"""

    cr = section17_rdp_check(_manifest({
        "promotion": {"asset_ref": "factor::a", "asset_kind": "factor", "rdp_ref": "rdp_x"}
    }))
    assert cr.ok is False
    assert "rdp" in cr.missing


def test_traceable_promotion_passes():
    """完整 RDP + 晋级 rdp_ref 解析到本 RDP + 资产对得上 → ok=True（可追溯）。"""

    section = {
        "rdp": dict(_BASE_RDP),
        "promotion": {"asset_ref": "factor::alpha_x", "asset_kind": "factor", "rdp_ref": _rdp_id()},
    }
    cr = section17_rdp_check(_manifest(section))
    assert cr.ok is True


def test_promotion_wrong_rdp_ref_rejected():
    """★ 可证伪（mutation 目标）：晋级 rdp_ref 解析不到本 RDP → ok=False·'rdp_ref'（追溯断裂）。"""

    section = {
        "rdp": dict(_BASE_RDP),
        "promotion": {"asset_ref": "factor::alpha_x", "asset_kind": "factor", "rdp_ref": "rdp_WRONG"},
    }
    cr = section17_rdp_check(_manifest(section))
    assert cr.ok is False
    assert "rdp_ref" in cr.missing


def test_promotion_asset_mismatch_rejected():
    """晋级资产 ≠ RDP 描述的资产（张冠李戴）→ ok=False·'asset_ref'。"""

    section = {
        "rdp": dict(_BASE_RDP),
        "promotion": {"asset_ref": "factor::OTHER", "asset_kind": "factor", "rdp_ref": _rdp_id()},
    }
    cr = section17_rdp_check(_manifest(section))
    assert cr.ok is False
    assert "asset_ref" in cr.missing


# ════════════════════════════════════════════════════════════════════════════
# ③ 诚实边界（RULES §3）+ 反作弊（gameability）+ 复用证明
# ════════════════════════════════════════════════════════════════════════════
def test_absent_section_is_ok_documented_limit():
    """诚实限界：manifest 未声明 §17 结构 → ok=True（无可证伪违例·非『整本已查清』）。

    『查清』由 producer 绿灯门负责——producer 未绿时本门只 advisory（见门链合成测试）。
    """

    cr = section17_rdp_check(_manifest(None))
    assert cr.ok is True
    assert cr.missing == ()
    assert "无可证伪" in cr.reason


def test_empty_section_nothing_declared_ok():
    """诚实限界：section17_rdp={}（rdp/promotion 均缺）→ ok=True（未声明·非违例）。"""

    cr = section17_rdp_check(_manifest({}))
    assert cr.ok is True
    assert cr.missing == ()


def test_input_flip_flips_ok_not_constant_gate():
    """反作弊：同一 RDP 补回 artifact_hash，ok 由 False 翻 True（门真读 validate_rdp 输出·非常量门）。"""

    bad = section17_rdp_check(_manifest({"rdp": _drop("artifact_hash")}))
    good = section17_rdp_check(_manifest(_complete_section()))
    assert bad.ok is False and good.ok is True, "输入翻转 ok 必须跟着翻"


def test_missing_delegated_to_canonical_validate_rdp():
    """复用证明：本 check 的 missing 逐项 == canonical `delivery.validate_rdp` 的 missing（不重造判定）。"""

    d = _drop("artifact_hash")
    canonical = validate_rdp(RDPManifest.from_dict(dict(d)))
    cr = section17_rdp_check(_manifest({"rdp": d}))
    assert cr.ok is False and canonical.ok is False
    assert set(cr.missing) == set(canonical.missing), "missing 必逐项来自 canonical validate_rdp（复用不重造）"


# ════════════════════════════════════════════════════════════════════════════
# ④ fail-closed 加固（codex C-S9 同款洞·堵 fail-open：违例绝不溜成 ok=True）
# ════════════════════════════════════════════════════════════════════════════
def test_section_not_mapping_failcloses():
    """fail-closed：§17 节存在但非 dict（被填成 list）→ ok=False（格式非法不静默放行）。"""

    cr = section17_rdp_check(_manifest(["not", "a", "dict"]))
    assert cr.ok is False
    assert "section17_rdp_malformed" in cr.missing


def test_rdp_subobject_not_mapping_failcloses():
    """fail-closed：rdp 子对象非 dict → ok=False（'section17_rdp_rdp_malformed'）。"""

    cr = section17_rdp_check(_manifest({"rdp": "not-a-dict"}))
    assert cr.ok is False
    assert "section17_rdp_rdp_malformed" in cr.missing


def test_promotion_subobject_not_mapping_failcloses():
    """fail-closed：promotion 子对象非 dict → ok=False（'section17_rdp_promotion_malformed'）。"""

    cr = section17_rdp_check(_manifest({"rdp": dict(_BASE_RDP), "promotion": "not-a-dict"}))
    assert cr.ok is False
    assert "section17_rdp_promotion_malformed" in cr.missing


def test_empty_rdp_dict_failcloses():
    """fail-closed：rdp={}（缺必填身份·半成品冒充正式交付）→ ok=False（'section17_rdp_unparseable'）。"""

    cr = section17_rdp_check(_manifest({"rdp": {}}))
    assert cr.ok is False
    assert "section17_rdp_unparseable" in cr.missing


def test_bad_asset_kind_failcloses():
    """fail-closed：asset_kind 非法 → RDPManifest 构造 raise → ok=False（'section17_rdp_unparseable'）。"""

    cr = section17_rdp_check(_manifest({"rdp": {**_BASE_RDP, "asset_kind": "garbage"}}))
    assert cr.ok is False
    assert "section17_rdp_unparseable" in cr.missing


def test_dataset_versions_non_lineage_shape_failcloses():
    """fail-closed：dataset_versions 被填成字符串 list（非血统形态）→ 构造炸 → ok=False（不静默放行）。"""

    cr = section17_rdp_check(_manifest({"rdp": {**_BASE_RDP, "dataset_versions": [""]}}))
    assert cr.ok is False
    assert "section17_rdp_unparseable" in cr.missing


def test_hollow_values_do_not_failopen():
    """坏门变形：空白 artifact / 空白 ingestion / 空壳 DatasetVersion —— 全 ok=False（delivery 门去空白·不 fail-open）。"""

    assert section17_rdp_check(_manifest({"rdp": {**_BASE_RDP, "artifact_hash": "   "}})).ok is False
    assert section17_rdp_check(_manifest({"rdp": {**_BASE_RDP, "ingestion_skill_refs": ["  "]}})).ok is False
    assert section17_rdp_check(
        _manifest({"rdp": {**_BASE_RDP, "dataset_versions": [{"dataset_id": "", "version": ""}]}})
    ).ok is False


def test_nonmapping_manifest_failcloses_not_open():
    """fail-closed：manifest 不是 Mapping（如 list）→ check **抛**（不静默 ok=True）；门链据此 errored 阻断。"""

    with pytest.raises(Exception):
        section17_rdp_check(["not", "a", "mapping"])  # type: ignore[arg-type]

    # 经门链（producer 绿）：check 抛 → fail-closed errored → 阻断（坏 manifest 绝不静默晋级）。
    chain = PromoteGateChain()
    register_section17_rdp_gate(chain)
    result = chain.evaluate(["not", "a", "mapping"], producer_status=_green_ledger())  # type: ignore[arg-type]
    v = _s17_verdict(result)
    assert v.ok is False and v.errored is True and v.blocks is True


# ════════════════════════════════════════════════════════════════════════════
# ⑤ 门链合成：注册 + producer 绿/红 → enforce/advisory（复用 SA-3/SA-2）
# ════════════════════════════════════════════════════════════════════════════
def test_registered_green_producer_enforces_and_rejects():
    """★ 注册 + producer 绿 → 整链 ENFORCE 拒不完整 RDP（blocks·ok=False·缺项精确）。"""

    chain = PromoteGateChain()
    register_section17_rdp_gate(chain)
    result = chain.evaluate(_manifest({"rdp": _drop("artifact_hash")}), producer_status=_green_ledger())

    assert isinstance(result, ChainResult)
    assert result.rejected is True, "producer 绿 + 不完整 RDP → 整链必须拒晋级"
    v = _s17_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert v.producer_key == SECTION17_RDP_PRODUCER_KEY
    assert "artifact_hash" in v.missing


def test_registered_red_producer_advisory_only_not_blocking():
    """★ 注册 + producer 红/缺 → advisory：不完整 RDP 被记录但**不**阻断（flip_refused·绝不误拒）。"""

    chain = PromoteGateChain()
    register_section17_rdp_gate(chain)
    result = chain.evaluate(_manifest({"rdp": _drop("artifact_hash")}), producer_status=ProducerStatusLedger())

    assert result.rejected is False, "producer 未绿 → §17 门只 advisory·绝不阻断"
    v = _s17_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.ok is False and v.blocks is False, "门诚实记下未过·但 advisory 不阻断"
    assert v in result.advisories


def test_absent_producer_status_advisory_only():
    """★ 无假绿灯：producer_status=None（生产默认）→ §17 门 advisory·producer_green=False·不阻断。"""

    chain = PromoteGateChain()
    register_section17_rdp_gate(chain)
    result = chain.evaluate(_manifest({"rdp": _drop("artifact_hash")}), producer_status=None)

    assert result.rejected is False
    v = _s17_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.producer_green is False, "确认 producer 仍 RED（出厂红·无假绿灯）"
    assert v.blocks is False


def test_check_cannot_self_declare_enforce():
    """gaming-proof：check 输出无 mode 字段 → 无法自封 enforce；mode 仅随 producer 绿灯翻。"""

    cr = section17_rdp_check(_manifest({"rdp": _drop("artifact_hash")}))
    assert not hasattr(cr, "advisory_or_enforce") and not hasattr(cr, "mode"), \
        "GateCheckResult 结构上不携 mode → check 无从自封 enforce"

    chain = PromoteGateChain()
    register_section17_rdp_gate(chain)
    red = _s17_verdict(chain.evaluate(_manifest({"rdp": _drop("artifact_hash")}), producer_status=ProducerStatusLedger()))
    green = _s17_verdict(chain.evaluate(_manifest({"rdp": _drop("artifact_hash")}), producer_status=_green_ledger()))
    assert red.advisory_or_enforce == MODE_ADVISORY
    assert green.advisory_or_enforce == MODE_ENFORCE, "仅 producer 绿灯能把同一门翻 enforce"


def test_green_producer_complete_rdp_passes_chain():
    """绿 producer + 完整 RDP → 不拒（enforce 门通过·证明 enforce 不误伤诚实 run）。"""

    chain = PromoteGateChain()
    register_section17_rdp_gate(chain)
    result = chain.evaluate(_manifest(_complete_section()), producer_status=_green_ledger())
    assert result.rejected is False
    v = _s17_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True


def test_registration_uses_documented_producer_key_and_intent():
    """注册契约：gate_name / required_producer 为文档化常量·enforce_intent 真（绿即翻 enforce·不张冠李戴）。"""

    chain = PromoteGateChain()
    register_section17_rdp_gate(chain)
    assert SECTION17_RDP_GATE_NAME in chain.gate_names
    v = _s17_verdict(chain.evaluate(_manifest(_complete_section()), producer_status=_green_ledger()))
    assert v.producer_key == SECTION17_RDP_PRODUCER_KEY
    assert v.advisory_or_enforce == MODE_ENFORCE
    # 别的 producer key 绿 → §17 门**不**翻（防张冠李戴）。
    other = ProducerStatusLedger()
    other.mark_green("some_other_producer")
    v2 = _s17_verdict(chain.evaluate(_manifest(_complete_section()), producer_status=other))
    assert v2.advisory_or_enforce == MODE_ADVISORY and v2.flip_refused is True


# ════════════════════════════════════════════════════════════════════════════
# ⑥ 冷导入安全（SA-3 纪律·镜像 section9/section10/section13 模块）
# ════════════════════════════════════════════════════════════════════════════
def test_module_cold_importable():
    """冷导入：全新解释器 import 本模块**不**撞 app.governance 既有冷导入循环。

    顶层只依赖 promote_gate_chain（cold-safe）+ delivery.rdp / delivery.rdp_gate（cold-safe·只触 lineage.ids）。
    """

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.release_gate.section17_rdp_gate as m; "
        "assert m.section17_rdp_check and m.register_section17_rdp_gate"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"§17 RDP 门模块应冷导入成功:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
