"""C-S9-BOUNDARY-ENFORCE · §9 边界 check 插 SA-3 门链 · 对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

可证伪验收（construction-map C-S9-BOUNDARY-ENFORCE）：
  · 模型体入因子库 → check ok=False（model_body_in_factor_library）
  · 守门指标入 generator fitness → check ok=False（gate_metric_in_generator_fitness）
  · 退役因子被新策略默认采用 → check ok=False（retired_factor_default_adoption）
  · clean manifest → ok=True
门链合成（复用 SA-3/SA-2·非本卡重测）：
  · 注册 + producer 绿 → 整链 ENFORCE 拒坏 manifest（blocks）
  · 注册 + producer 红/缺 → advisory：只记录不阻断（flip_refused·绝不误拒）
  · check 无 mode 字段 → 无法自封 enforce：mode 仅由 producer 绿灯翻（gaming-proof）
gameability：输入翻转 ok 跟着翻（非常量门）；复用 = 违例码精确来自 canonical validator。

★ mutation 三态（已手验·见报告）：把 section9_boundary_gate._accumulate 对
  `factor_library_entries` 的那一行注释掉（弱化 check 使模型体不被旗标）→
  `test_model_body_as_factor_flagged` 转 RED → 还原 → GREEN。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_promote_gate_chain.py 同款顺序（app.governance 包 __init__ 经 spine_invariants 触达 orchestrator）。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

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
from app.release_gate.section9_boundary_gate import (  # noqa: E402
    SECTION9_BOUNDARY_GATE_NAME,
    SECTION9_BOUNDARY_MANIFEST_KEY,
    SECTION9_BOUNDARY_PRODUCER_KEY,
    register_section9_boundary_gate,
    section9_boundary_check,
)


# ════════════════════════════════════════════════════════════════════════════
# manifest 构造器（faithful §9 producer 契约·中心后续据此填）
# ════════════════════════════════════════════════════════════════════════════
def _manifest(section: dict | None) -> dict:
    m = {"run_id": "ide_promote_test", "status": "completed"}
    if section is not None:
        m[SECTION9_BOUNDARY_MANIFEST_KEY] = section
    return m


def _model_body_manifest() -> dict:
    """坏门：把一个 .pt 模型体当作因子库条目（kind=model_body）。"""

    return _manifest({
        "factor_library_entries": [
            {"factor_ref": "f::sneaky_model", "kind": "model_body", "ref": "models/alpha.pt"}
        ]
    })


def _retired_adoption_manifest() -> dict:
    """坏门：新策略本默认采用一个 RETIRED 生命周期的因子。"""

    return _manifest({
        "strategy_books": [
            {
                "strategy_book_ref": "book::new_strat",
                "factor_refs": ["f::retired"],
                "default_factor_refs": ["f::retired"],
                "factor_library": {
                    "f::retired": {
                        "factor_ref": "f::retired",
                        "kind": "expression",
                        "ref": "ts_mean(close,5)",
                        "lifecycle_state": "RETIRED",
                    }
                },
            }
        ]
    })


def _gate_metric_manifest() -> dict:
    """坏门：守门指标（ic）混进因子生成器的 fitness_inputs（给 gatekeeper 以隔离此一违例）。"""

    return _manifest({
        "factor_generators": [
            {
                "generator_ref": "gen::g1",
                "structure_inputs": ["close", "volume"],
                "fitness_inputs": ["ic", "complexity"],
                "gatekeeper_ref": "gk::holdout_sharpe",
            }
        ]
    })


def _clean_manifest() -> dict:
    """clean：三族全部合法 → 无违例。"""

    return _manifest({
        "factor_library_entries": [
            {"factor_ref": "f::ok", "kind": "expression", "ref": "ts_zscore(close,20)"}
        ],
        "factor_generators": [
            {
                "generator_ref": "gen::ok",
                "structure_inputs": ["close"],
                "fitness_inputs": ["complexity"],
                "gatekeeper_ref": "gk::holdout_sharpe",
            }
        ],
        "strategy_books": [
            {
                "strategy_book_ref": "book::ok",
                "factor_refs": ["f::ok"],
                "default_factor_refs": ["f::ok"],
                "factor_library": {
                    "f::ok": {
                        "factor_ref": "f::ok",
                        "kind": "expression",
                        "ref": "ts_zscore(close,20)",
                        "lifecycle_state": "QUALIFIED",
                    }
                },
            }
        ],
    })


def _green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION9_BOUNDARY_PRODUCER_KEY)
    return led


def _s9_verdict(result: ChainResult):
    matches = [v for v in result.verdicts if v.gate_name == SECTION9_BOUNDARY_GATE_NAME]
    assert len(matches) == 1, "门链中应恰有一道 §9 边界门裁定"
    return matches[0]


# ════════════════════════════════════════════════════════════════════════════
# ① check 层：坏门必抓 + clean 必过（可证伪三连·mutation 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_model_body_as_factor_flagged():
    """★ 可证伪①：模型体（.pt）入因子库 → ok=False·精确码 model_body_in_factor_library。"""

    cr = section9_boundary_check(_model_body_manifest())
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is False
    assert "model_body_in_factor_library" in cr.missing


def test_retired_factor_default_adoption_flagged():
    """★ 可证伪②：退役因子被新策略默认采用 → ok=False·精确码 retired_factor_default_adoption。"""

    cr = section9_boundary_check(_retired_adoption_manifest())
    assert cr.ok is False
    assert "retired_factor_default_adoption" in cr.missing


def test_gate_metric_in_generator_fitness_flagged():
    """可证伪③：守门指标入 generator fitness → ok=False·精确码 gate_metric_in_generator_fitness。"""

    cr = section9_boundary_check(_gate_metric_manifest())
    assert cr.ok is False
    assert "gate_metric_in_generator_fitness" in cr.missing
    assert "missing_gatekeeper_ref" not in cr.missing, "给了 gatekeeper → 不应有缺 gatekeeper 噪声"


def test_clean_manifest_passes():
    """clean：三族全部合法 → ok=True·无 missing。"""

    cr = section9_boundary_check(_clean_manifest())
    assert cr.ok is True
    assert cr.missing == ()


# ════════════════════════════════════════════════════════════════════════════
# ② 诚实边界（RULES §3）+ 反作弊（gameability）
# ════════════════════════════════════════════════════════════════════════════
def test_absent_section_is_ok_documented_limit():
    """诚实限界：manifest 未声明 §9 结构 → ok=True（无可证伪违例·非『整本已查清』）。

    『查清』由 producer 绿灯门负责——producer 未绿时本门只 advisory（见门链合成测试）。
    """

    cr = section9_boundary_check(_manifest(None))
    assert cr.ok is True
    assert cr.missing == ()
    assert "无可证伪" in cr.reason


def test_malformed_section_failcloses():
    """fail-closed：§9 节存在但非 dict（被填成 list）→ ok=False（格式非法不静默放行）。"""

    m = {"run_id": "r", SECTION9_BOUNDARY_MANIFEST_KEY: ["not", "a", "dict"]}
    cr = section9_boundary_check(m)
    assert cr.ok is False
    assert "section9_boundary_malformed" in cr.missing


def test_input_flip_flips_ok_not_constant_gate():
    """反作弊：同一条目 model_body→expression+合法 ref，ok 由 False 翻 True（证明非常量 no-op 门）。"""

    bad = section9_boundary_check(_manifest({
        "factor_library_entries": [
            {"factor_ref": "f::x", "kind": "model_body", "ref": "models/x.pt"}
        ]
    }))
    good = section9_boundary_check(_manifest({
        "factor_library_entries": [
            {"factor_ref": "f::x", "kind": "expression", "ref": "ts_zscore(close,20)"}
        ]
    }))
    assert bad.ok is False and good.ok is True, "输入翻转 ok 必须跟着翻（门真读 validator 输出）"


def test_missing_codes_come_from_canonical_validator():
    """复用证明：missing 里的码是 factor_strategy_boundary canonical validator 原码（非本模块自造）。"""

    from app.research_os import factor_strategy_boundary as fsb

    cr = section9_boundary_check(_retired_adoption_manifest())
    # 这条码在 canonical validator 里硬编码（同一源）——本 check 只搬运不重造。
    assert "retired_factor_default_adoption" in cr.missing
    assert "retired_factor_default_adoption" in Path(fsb.__file__).read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════════
# ⑤ fail-closed 加固（codex 对抗复审后补·堵 fail-open：违例绝不溜成 ok=True）
# ════════════════════════════════════════════════════════════════════════════
def test_family_as_mapping_does_not_failopen():
    """坏门变形：把 factor_library_entries 填成 {id: entry} 映射（非 list）藏一个 model_body。

    旧实现会静默 skip 非 list → ok=True（违例溜走）。现 fail-closed：记 malformed·ok=False。
    """

    m = _manifest({
        "factor_library_entries": {
            "f::hidden": {"factor_ref": "f::hidden", "kind": "model_body", "ref": "models/x.pt"}
        }
    })
    cr = section9_boundary_check(m)
    assert cr.ok is False, "非 list 的族不得静默放行藏在里面的违例"
    assert "section9_factor_library_entry_malformed" in cr.missing


def test_family_list_with_nondict_item_failcloses():
    """坏门变形：族是 list 但含非 dict 项 → fail-closed malformed（不静默 skip）。"""

    m = _manifest({"factor_generators": ["not-a-dict"]})
    cr = section9_boundary_check(m)
    assert cr.ok is False
    assert "section9_factor_generator_malformed" in cr.missing


def test_retired_default_adoption_without_factor_refs_still_flagged():
    """★ fail-open 堵口：default_factor_refs 命名退役因子但漏填 factor_refs → 仍 ok=False。

    canonical retired 检查只迭代 factor_refs；adapter 把 default_factor_refs 并进 factor_refs，
    使「退役因子被默认采用」无论是否同时出现在 factor_refs 都被评到。
    """

    m = _manifest({
        "strategy_books": [
            {
                "strategy_book_ref": "book::sneaky",
                # 故意不给 factor_refs，只给 default_factor_refs
                "default_factor_refs": ["f::retired"],
                "factor_library": {
                    "f::retired": {
                        "factor_ref": "f::retired",
                        "kind": "expression",
                        "ref": "ts_mean(close,5)",
                        "lifecycle_state": "RETIRED",
                    }
                },
            }
        ]
    })
    cr = section9_boundary_check(m)
    assert cr.ok is False
    assert "retired_factor_default_adoption" in cr.missing


def test_nonmapping_manifest_failcloses_not_open():
    """fail-closed：manifest 不是 Mapping（如 list）→ check **抛**（不静默 ok=True）；门链据此 errored 阻断。"""

    with pytest.raises(Exception):
        section9_boundary_check(["not", "a", "mapping"])  # type: ignore[arg-type]

    # 经门链（producer 绿）：check 抛 → fail-closed errored → 阻断（坏 manifest 绝不静默晋级）。
    chain = PromoteGateChain()
    register_section9_boundary_gate(chain)
    result = chain.evaluate(["not", "a", "mapping"], producer_status=_green_ledger())  # type: ignore[arg-type]
    v = _s9_verdict(result)
    assert v.ok is False and v.errored is True and v.blocks is True


# ════════════════════════════════════════════════════════════════════════════
# ③ 门链合成：注册 + producer 绿/红 → enforce/advisory（复用 SA-3/SA-2）
# ════════════════════════════════════════════════════════════════════════════
def test_registered_green_producer_enforces_and_rejects():
    """★ 注册 + producer 绿 → 整链 ENFORCE 拒坏 manifest（blocks·ok=False）。"""

    chain = PromoteGateChain()
    register_section9_boundary_gate(chain)
    result = chain.evaluate(_model_body_manifest(), producer_status=_green_ledger())

    assert isinstance(result, ChainResult)
    assert result.rejected is True, "producer 绿 + §9 违例 → 整链必须拒晋级"
    v = _s9_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert v.producer_key == SECTION9_BOUNDARY_PRODUCER_KEY
    assert "model_body_in_factor_library" in v.missing


def test_registered_red_producer_advisory_only_not_blocking():
    """★ 注册 + producer 红/缺 → advisory：坏 manifest 被记录但**不**阻断（flip_refused·绝不误拒）。"""

    chain = PromoteGateChain()
    register_section9_boundary_gate(chain)
    result = chain.evaluate(_model_body_manifest(), producer_status=ProducerStatusLedger())

    assert result.rejected is False, "producer 未绿 → §9 门只 advisory·绝不阻断诚实 run"
    v = _s9_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.ok is False and v.blocks is False, "门诚实记下未过·但 advisory 不阻断"
    assert v in result.advisories


def test_check_cannot_self_declare_enforce_mode_from_policy_only():
    """gaming-proof：check 输出无 mode 字段 → 无法自封 enforce；mode 仅随 producer 绿灯翻。

    同一 check、同一坏 manifest：producer 红→advisory、producer 绿→enforce。check 自己改变不了这个。
    """

    cr = section9_boundary_check(_model_body_manifest())
    assert not hasattr(cr, "advisory_or_enforce") and not hasattr(cr, "mode"), \
        "GateCheckResult 结构上不携 mode → check 无从自封 enforce"

    chain = PromoteGateChain()
    register_section9_boundary_gate(chain)
    red = _s9_verdict(chain.evaluate(_model_body_manifest(), producer_status=ProducerStatusLedger()))
    green = _s9_verdict(chain.evaluate(_model_body_manifest(), producer_status=_green_ledger()))
    assert red.advisory_or_enforce == MODE_ADVISORY
    assert green.advisory_or_enforce == MODE_ENFORCE, "仅 producer 绿灯能把同一门翻 enforce"


def test_green_producer_clean_manifest_passes_chain():
    """绿 producer + clean manifest → 不拒（enforce 门通过·证明 enforce 不误伤诚实 run）。"""

    chain = PromoteGateChain()
    register_section9_boundary_gate(chain)
    result = chain.evaluate(_clean_manifest(), producer_status=_green_ledger())
    assert result.rejected is False
    v = _s9_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True


def test_registration_uses_documented_producer_key_and_intent():
    """注册契约：gate_name / required_producer 为文档化常量·enforce_intent 真（绿即翻 enforce）。"""

    chain = PromoteGateChain()
    register_section9_boundary_gate(chain)
    assert SECTION9_BOUNDARY_GATE_NAME in chain.gate_names
    # producer 绿 → enforce（证明 enforce_intent=True 且绑定的 producer key 即文档常量）。
    v = _s9_verdict(chain.evaluate(_clean_manifest(), producer_status=_green_ledger()))
    assert v.producer_key == SECTION9_BOUNDARY_PRODUCER_KEY
    assert v.advisory_or_enforce == MODE_ENFORCE
    # 别的 producer key 绿 → §9 门**不**翻（防张冠李戴）。
    other = ProducerStatusLedger()
    other.mark_green("some_other_producer")
    v2 = _s9_verdict(chain.evaluate(_clean_manifest(), producer_status=other))
    assert v2.advisory_or_enforce == MODE_ADVISORY and v2.flip_refused is True


# ════════════════════════════════════════════════════════════════════════════
# ④ 冷导入安全（SA-3 纪律·镜像 test_chain_module_cold_importable）
# ════════════════════════════════════════════════════════════════════════════
def test_module_cold_importable():
    """冷导入：全新解释器 import 本模块**不**撞 app.governance 既有冷导入循环。

    顶层只依赖 promote_gate_chain（cold-safe）+ research_os.factor_strategy_boundary（cold-safe）。
    """

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.release_gate.section9_boundary_gate as m; "
        "assert m.section9_boundary_check and m.register_section9_boundary_gate"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"§9 边界门模块应冷导入成功:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
