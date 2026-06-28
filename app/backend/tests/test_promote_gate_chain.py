"""SA-3 promote 门链 seam + SA-2 enforce 策略件 · 对抗测试（种坏门必抓·守 RULES §2/§3）。

覆盖三条 SA-3/SA-2 可证伪验收：
  ① ENFORCING check 拒坏 run → 整链 rejected（且 advisory_or_enforce=="enforce"）；
  ② ADVISORY check 拒坏 run → 只记录、**不**阻断（advisory 永不 block）；
  ③ enforce_intent 门 producer 未绿 → 策略**拒翻**（fail-closed·降级 advisory + flip_refused）；
     直接构造 enforce-on-red 的解析 → 结构不变量抛（不可表示·gaming-proof）。
加固：auto-flip（producer 转绿即 enforce）、收齐全部裁定不短路、check 抛异常 fail-closed、
复用已建 §16 release gate（不重造判定）。

mutation 三态（见底部 docstring）：削弱 `GateVerdict.blocks` 丢掉 enforce 拒绝 →
`test_enforcing_check_rejects_bad_run` 转 RED → 还原 → GREEN。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：`app.governance` 包 __init__ 经 spine_invariants 触达
# `app.agent.orchestrator`，cold-import `app.governance` 子模块会撞既有循环（governance_advisory
# 反向 import governance）。与全仓 governance 测试同款顺序（见 test_governance_spine.py）——先全载
# orchestrator 解环，再导 governance 子模块。本卡新模块 enforcement_policy 自身只依赖 stdlib。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

from app.governance.enforcement_policy import (
    MODE_ADVISORY,
    MODE_ENFORCE,
    EnforcementDecl,
    EnforcementPolicyError,
    EnforcementResolution,
    ProducerStatusLedger,
    resolve_enforcement,
)
from app.release_gate.promote_gate_chain import (
    ChainResult,
    GateCheckResult,
    GateVerdict,
    PromoteGateChain,
    default_chain,
    reset_default_chain,
)

# —— 最小 run manifest（门链对它无 schema 假设·check 自己读所需字段）——
_MANIFEST = {"run_id": "ide_test_run", "status": "completed"}


def _pass_check(_manifest):
    return GateCheckResult(ok=True, reason="通过")


def _reject_check(_manifest):
    return GateCheckResult(ok=False, reason="坏 run：模板基线冒充生产", missing=("template_false_success",))


def _green_ledger(producer_key: str) -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(producer_key)
    return led


# ════════════════════════════════════════════════════════════════════════════
# ① ENFORCING check 拒坏 run → 整链 rejected（mutation 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_enforcing_check_rejects_bad_run():
    """★ 可证伪①：producer 已绿的 enforce 门判坏 run 未过 → 整链 rejected、该门 blocks。"""

    chain = PromoteGateChain()
    chain.register(
        gate_name="s17_rdp",
        check=_reject_check,
        required_producer="rdp_runjson_producers",
        enforce_intent=True,
    )
    result = chain.evaluate(_MANIFEST, producer_status=_green_ledger("rdp_runjson_producers"))

    assert isinstance(result, ChainResult)
    assert result.rejected is True, "enforce 门判坏 run 未过 → 整链必须 rejected"
    assert len(result.rejections) == 1
    v = result.rejections[0]
    assert v.gate_name == "s17_rdp"
    assert v.advisory_or_enforce == MODE_ENFORCE, "producer 绿 → 该门应解析为 enforce"
    assert v.blocks is True
    assert v.ok is False


# ════════════════════════════════════════════════════════════════════════════
# ② ADVISORY check → 记录、不阻断
# ════════════════════════════════════════════════════════════════════════════
def test_advisory_check_recorded_not_blocking():
    """可证伪②：纯 advisory 门（enforce_intent=False）即便判 ok=False → 只记录、不阻断。"""

    chain = PromoteGateChain()
    chain.register(gate_name="s10_cost", check=_reject_check, enforce_intent=False)
    result = chain.evaluate(_MANIFEST)

    assert result.rejected is False, "advisory 门未过绝不阻断 promote"
    assert len(result.rejections) == 0
    assert len(result.verdicts) == 1, "advisory 门仍被记录进 verdicts（可追溯）"
    v = result.verdicts[0]
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.ok is False, "门确实判未过（被诚实记录）"
    assert v.blocks is False
    assert v in result.advisories


def test_enforce_intent_without_green_producer_stays_advisory():
    """可证伪②加固：有 enforce 意图但 producer 未绿 → 降级 advisory + flip_refused，判坏也不阻断。"""

    chain = PromoteGateChain()
    chain.register(
        gate_name="s9_boundary",
        check=_reject_check,
        required_producer="boundary_producer",
        enforce_intent=True,
    )
    # producer_status 为空 → producer 未绿
    result = chain.evaluate(_MANIFEST, producer_status=ProducerStatusLedger())

    assert result.rejected is False, "未绿 producer 的 enforce 门不得阻断（绝不误拒诚实 run）"
    v = result.verdicts[0]
    assert v.advisory_or_enforce == MODE_ADVISORY, "producer 未绿 → 必须停在 advisory"
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.producer_green is False


# ════════════════════════════════════════════════════════════════════════════
# ③ enforce-on-red：策略拒翻（fail-closed）+ 结构不变量不可表示
# ════════════════════════════════════════════════════════════════════════════
def test_resolve_enforcement_refuses_flip_on_red_producer():
    """可证伪③（运行期）：enforce_intent 门 producer 未绿 → resolve 降级 advisory + 记录拒翻，绝不 enforce。"""

    decl = EnforcementDecl(gate_name="s13_trust", required_producer="trust_producer", enforce_intent=True)

    res = resolve_enforcement(decl, ProducerStatusLedger())  # producer 未绿
    assert res.mode == MODE_ADVISORY, "未绿 producer 绝不能解析为 enforce"
    assert res.enforcing is False
    assert res.flip_refused is True, "拒翻必须显式记录"
    assert res.producer_green is False

    # 缺 producer_status（None）同样 fail-closed
    res_none = resolve_enforcement(decl, None)
    assert res_none.mode == MODE_ADVISORY and res_none.flip_refused is True


def test_resolution_structural_failclosed_unrepresentable():
    """★ 可证伪③（结构）：直接构造「无绿 producer 却 enforce」→ 抛 EnforcementPolicyError（gaming-proof）。

    enforce-on-red 在类型层不可表示——任何绕过 resolve 的尝试（含未来 gaming）都 fail-closed。
    """

    with pytest.raises(EnforcementPolicyError):
        EnforcementResolution(
            gate_name="evil_gate",
            mode=MODE_ENFORCE,
            producer_key="missing_producer",
            producer_green=False,  # ← 无绿证据却想 enforce
            enforce_intent=True,
            flip_refused=False,
        )

    # 合法的 enforce 解析（producer 绿）可正常构造
    ok = EnforcementResolution(
        gate_name="good_gate",
        mode=MODE_ENFORCE,
        producer_key="green_producer",
        producer_green=True,
        enforce_intent=True,
        flip_refused=False,
    )
    assert ok.enforcing is True


# ════════════════════════════════════════════════════════════════════════════
# 加固：auto-flip / 收齐全部裁定 / check 抛异常 fail-closed / 复用 §16
# ════════════════════════════════════════════════════════════════════════════
def test_auto_enforce_once_producer_green():
    """LOCKED 决策 1：producer 转绿那刻自动从 advisory 翻 enforce（过则不拒·未过则拒）。"""

    decl = EnforcementDecl(gate_name="s16_engstd", required_producer="engstd_producer", enforce_intent=True)

    advisory = resolve_enforcement(decl, ProducerStatusLedger())  # 未绿
    assert advisory.mode == MODE_ADVISORY

    enforce = resolve_enforcement(decl, _green_ledger("engstd_producer"))  # 转绿
    assert enforce.mode == MODE_ENFORCE and enforce.flip_refused is False

    # 绿 + 过 → 不拒
    chain = PromoteGateChain()
    chain.register(gate_name="s16_engstd", check=_pass_check,
                   required_producer="engstd_producer", enforce_intent=True)
    good = chain.evaluate(_MANIFEST, producer_status=_green_ledger("engstd_producer"))
    assert good.rejected is False and good.verdicts[0].advisory_or_enforce == MODE_ENFORCE


def test_chain_collects_all_verdicts_no_shortcircuit():
    """门链跑全部 check 一遍·收齐裁定不短路（enforce 拒后仍收 advisory 记录）。"""

    chain = PromoteGateChain()
    chain.register(gate_name="enforce_reject", check=_reject_check,
                   required_producer="p_enf", enforce_intent=True)
    chain.register(gate_name="advisory_reject", check=_reject_check, enforce_intent=False)
    chain.register(gate_name="enforce_pass", check=_pass_check,
                   required_producer="p_pass", enforce_intent=True)

    led = ProducerStatusLedger()
    led.mark_green("p_enf")
    led.mark_green("p_pass")
    result = chain.evaluate(_MANIFEST, producer_status=led)

    assert len(result.verdicts) == 3, "三道门全部被评估、收齐裁定（不短路）"
    assert result.rejected is True
    assert {v.gate_name for v in result.rejections} == {"enforce_reject"}
    assert {v.gate_name for v in result.advisories} == {"advisory_reject"}
    # to_dict 可投影进 run.json
    d = result.to_dict()
    assert d["rejected"] is True and len(d["verdicts"]) == 3


def test_enforcing_check_that_errors_failcloses():
    """fail-closed：enforce 门的 check 抛异常 → 视为未过 → 阻断（坏门绝不静默放行）。"""

    def _boom(_manifest):
        raise RuntimeError("check 内部炸了")

    chain = PromoteGateChain()
    chain.register(gate_name="s17_rdp", check=_boom,
                   required_producer="p", enforce_intent=True)
    result = chain.evaluate(_MANIFEST, producer_status=_green_ledger("p"))

    assert result.rejected is True, "enforce 门 check 抛异常必须 fail-closed 阻断"
    v = result.rejections[0]
    assert v.ok is False and v.errored is True


def test_advisory_check_that_errors_recorded_not_blocking():
    """fail-closed 对称面：advisory 门的 check 抛异常 → 记录 errored、不阻断。"""

    def _boom(_manifest):
        raise RuntimeError("advisory check 炸了")

    chain = PromoteGateChain()
    chain.register(gate_name="s10_controlplane", check=_boom, enforce_intent=False)
    result = chain.evaluate(_MANIFEST)

    assert result.rejected is False
    v = result.verdicts[0]
    assert v.errored is True and v.advisory_or_enforce == MODE_ADVISORY and v.blocks is False


def test_reuse_existing_release_validation_not_duplicated():
    """复用不重造（RULES §1）：已建 §16 `ReleaseValidation` 经 duck-typed 适配插进门链作一道 check。"""

    from app.release_gate import ReleaseGateOutcome, ReleaseValidation

    bad = ReleaseValidation(
        ok=False,
        outcomes=(ReleaseGateOutcome("gate_mock_honesty", False, ("template_false_success",), "模板冒充生产"),),
    )
    cr = GateCheckResult.from_release_validation(bad)
    assert cr.ok is False and "template_false_success" in cr.missing

    # 把它包成 enforce check 插链：§16 裁未过 + producer 绿 → 阻断
    chain = PromoteGateChain()
    chain.register(gate_name="s16_release", check=lambda _m: cr,
                   required_producer="release_producer", enforce_intent=True)
    result = chain.evaluate(_MANIFEST, producer_status=_green_ledger("release_producer"))
    assert result.rejected is True


def test_register_rejects_duplicate_and_empty():
    """注册防呆：重复 gate_name / 空 gate_name / 非可调用 check → 抛（防一道门被静默覆盖）。"""

    chain = PromoteGateChain()
    chain.register(gate_name="g", check=_pass_check)
    with pytest.raises(ValueError):
        chain.register(gate_name="g", check=_pass_check)  # 重复
    with pytest.raises(ValueError):
        chain.register(gate_name="  ", check=_pass_check)  # 空
    with pytest.raises(TypeError):
        chain.register(gate_name="h", check="not-callable")  # type: ignore[arg-type]


def test_default_chain_singleton_and_reset():
    """默认门链是进程级共享落点·reset 清空（测试隔离·绝不污染生产路径）。"""

    reset_default_chain()
    c1 = default_chain()
    c1.register(gate_name="x", check=_pass_check)
    assert "x" in default_chain().gate_names, "同进程拿到同一默认门链"
    reset_default_chain()
    assert default_chain().gate_names == (), "reset 后默认门链清空"
    reset_default_chain()


# ════════════════════════════════════════════════════════════════════════════
# 反作弊加固（codex 对抗复审后补·种坏门必抓）
# ════════════════════════════════════════════════════════════════════════════
def test_truthy_nonbool_status_is_not_green():
    """反假绿灯：状态源给 truthy 非布尔（"red"/"false"/1/"true"）→ 未绿 → enforce_intent 门停 advisory。

    若用 bool(...) 而非严格 `is True`，`bool("red")==True` 会假绿灯放开 enforce（违「未验证≠已验证」）。
    """

    decl = EnforcementDecl(gate_name="g", required_producer="p", enforce_intent=True)
    for bad in ("red", "false", 1, "true", [1]):
        res = resolve_enforcement(decl, {"p": bad})
        assert res.mode == MODE_ADVISORY, f"truthy 非布尔 {bad!r} 不得算绿 → 必须停 advisory"
        assert res.flip_refused is True
    # 唯有布尔 True 算绿
    assert resolve_enforcement(decl, {"p": True}).mode == MODE_ENFORCE
    # ledger 构造同样严格
    assert ProducerStatusLedger({"p": "red"}).is_green("p") is False
    assert ProducerStatusLedger({"p": True}).is_green("p") is True


def test_check_ok_must_be_bool():
    """反作弊：GateCheckResult.ok 非布尔 → 构造即抛（拒 `ok="false"` 这类 truthy 字符串冒充过门）。"""

    with pytest.raises(TypeError):
        GateCheckResult(ok="false")  # bool("false") == True 的陷阱
    with pytest.raises(TypeError):
        GateCheckResult(ok=1)


def test_enforce_gate_with_nonbool_ok_failcloses():
    """端到端：enforce 门 check 返回非布尔 ok（构造抛）→ 门链 fail-closed 阻断（绝不静默吞拒绝）。"""

    chain = PromoteGateChain()
    chain.register(
        gate_name="g",
        check=lambda _m: GateCheckResult(ok="false"),  # type: ignore[arg-type]
        required_producer="p",
        enforce_intent=True,
    )
    result = chain.evaluate(_MANIFEST, producer_status=_green_ledger("p"))
    assert result.rejected is True, "非布尔 ok 不得静默放行 enforce 门"
    assert result.rejections[0].errored is True


def test_manifest_mutation_isolated_across_checks():
    """反作弊：一道 check 改 manifest 不污染别的 check / 原 manifest（每 check 收独立深拷贝）。

    没有隔离时，advisory 前置门可给后置 enforce 门「种」伪造字段让其放行——这里证明串改无效。
    """

    def _forger(manifest):
        manifest["forged_pass"] = True  # 试图给后置门种字段
        return GateCheckResult(ok=True, reason="advisory forger")

    def _enforce_reads_forged(manifest):
        # 只有看到 forged_pass 才放行；隔离生效 → 看不到 → 判未过
        return GateCheckResult(ok=manifest.get("forged_pass") is True, reason="enforce reads forged")

    chain = PromoteGateChain()
    chain.register(gate_name="aaa_forger", check=_forger, enforce_intent=False)
    chain.register(gate_name="zzz_enforce", check=_enforce_reads_forged,
                   required_producer="p", enforce_intent=True)
    original = {"run_id": "x"}
    result = chain.evaluate(original, producer_status=_green_ledger("p"))

    assert result.rejected is True, "深拷贝隔离 → 后门看不到伪造字段 → enforce 判未过 → 拒"
    assert "forged_pass" not in original, "原 manifest 绝不被 check 污染"


def test_gateverdict_rejects_unknown_mode():
    """反作弊：advisory_or_enforce 错拼（'enforce ' / 'ENFORCE'）→ 构造即抛（杜绝阻断被悄悄丢）。"""

    with pytest.raises(ValueError):
        GateVerdict(gate_name="g", ok=False, advisory_or_enforce="enforce ")
    with pytest.raises(ValueError):
        GateVerdict(gate_name="g", ok=False, advisory_or_enforce="ENFORCE")


def test_chain_mode_constants_match_policy():
    """本地 MODE 字面量（冷导入安全用）必须与 policy 单一源同值（防漂·wire 词汇一致）。"""

    from app.release_gate import promote_gate_chain as cm

    assert cm.MODE_ADVISORY == MODE_ADVISORY
    assert cm.MODE_ENFORCE == MODE_ENFORCE


def test_chain_module_cold_importable():
    """冷导入安全：全新解释器里 import 本门链模块**不**撞 app.governance 既有冷导入循环。

    （门链顶层不 import governance·policy 符号惰性载入；解 codex 复审指出的「import 即炸」blocker。）
    """

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = "import app.release_gate.promote_gate_chain as m; assert m.PromoteGateChain and m.default_chain"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"门链模块冷导入应成功（不依赖导入顺序）:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
