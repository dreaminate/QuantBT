"""SA-3 promote 门链**接进真 promote 路径**（gate_registry + ide/promote）· 对抗测试。

中心串行第三波：`promote_gate_chain` seam + 各节门 check 已落地（test_promote_gate_chain /
test_section9_boundary_gate / test_section10_methodology_gate 守 seam/check 本身）。本卡把它们经
**单一注册收口** `release_gate.gate_registry` 接进 `ide.promote.promote_ide_run`——每个 promoted run
的 run.json 现携带 `promote_gate_chain` 裁决。

advisory-first 不变量（本测试守门·守 LOCKED 决策 1 + RULES.project「未验证≠已验证」）：
  ① 经 promote_ide_run 跑出一个 §9 / §10 违例 + **producer 全红** → 裁决落 run.json 作 **advisory**
     （记录·flip_refused·**绝不阻断**）·promote 仍成功落盘；
  ② **同一违例** + 对应 producer 在 ledger 标绿 → 同门翻 ENFORCE → **阻断**（promote 抛 PromoteError·
     被拒晋级不留 run.json·绝不冒充成功 run）；
  ③ 向后兼容：clean manifest（无 §9/§10/§13 结构）→ 全门 advisory ok=True·promote 与既有完全一致；
  ④ 无任何 producer 假绿灯：默认 producer_status=None → 全门 advisory + producer_green=False。

★ mutation 三态（已手验·见任务报告）：把 ide/promote.py 的 SA-3 门链块（evaluate+attach+reject）整段
  注释掉（弱化接线·裁决不再 evaluate/attach）→ `test_s9_violation_recorded_advisory_while_producer_red`
  与 `test_s9_violation_blocks_when_producer_green` 转 RED → 还原 → GREEN。

诚实说明：本卡**不建 producer**（把真实 §9/§10 资产写进 manifest 那层 = 独立卡·LOCKED 决策 1）。测试
用一个薄 wrapper 在 evaluate 边界把 §9/§10 结构注入 manifest，**模拟未来 producer 填值**——被评估的门、
门链、SA-2 策略全是真组件（advisory/enforce 行为 100% 真）。生产路径无 producer → manifest 无 §9/§10
结构 → 三门 nothing-declared 全过（advisory）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_promote_gate_chain.py 同款顺序（app.governance 包 __init__ 经 spine_invariants 触达 orchestrator）。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

from app.governance.enforcement_policy import ProducerStatusLedger  # noqa: E402
from app.ide.promote import PromoteError, promote_ide_run  # noqa: E402
from app.release_gate.gate_registry import (  # noqa: E402
    ensure_default_chain,
    register_all_gates,
)
from app.release_gate.promote_gate_chain import (  # noqa: E402
    PromoteGateChain,
    reset_default_chain,
)
from app.release_gate.section9_boundary_gate import (  # noqa: E402
    SECTION9_BOUNDARY_GATE_NAME,
    SECTION9_BOUNDARY_MANIFEST_KEY,
    SECTION9_BOUNDARY_PRODUCER_KEY,
)
from app.release_gate.section10_methodology_gate import (  # noqa: E402
    SECTION10_CONTROLPLANE_GATE_NAME,
    SECTION10_CONTROLPLANE_MANIFEST_KEY,
    SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION10_COST_GATE_NAME,
)
from app.release_gate.section13_trust_gate import (  # noqa: E402
    SECTION13_TRUST_GATE_NAME,
)

# —— 经 canonical 测试证明的违例 fixture（与 test_section9/10 同源·此处只搬运不重造）——
_S9_VIOLATION = {
    "factor_library_entries": [
        {"factor_ref": "f::sneaky_model", "kind": "model_body", "ref": "models/alpha.pt"}
    ]
}
_S9_CODE = "model_body_in_factor_library"

_S10CP_VIOLATION = {"tier_claims": [{"tier": "loose", "claimed_label": "evidence_sufficient"}]}
_S10CP_CODE = "s10_relaxed_tier_strong_verdict_capped"

_ALL_GATE_NAMES = {
    SECTION9_BOUNDARY_GATE_NAME,
    SECTION10_COST_GATE_NAME,
    SECTION10_CONTROLPLANE_GATE_NAME,
    SECTION13_TRUST_GATE_NAME,  # §13 信任发版门经 gate_registry 落地接进 promote 路径（C-S13-RELEASE-ENFORCE）
}


@pytest.fixture(autouse=True)
def _reset_chain():
    """每个用例前后清空进程级默认门链（隔离·让 ensure_default_chain 每次从空重填·防跨用例污染）。"""

    reset_default_chain()
    yield
    reset_default_chain()


def _curve(n: int) -> list[dict]:
    """最小可 promote 的 equity_curve（镜像 test_promote_release_advisory._curve）。"""

    return [{"timestamp": f"2024-01-{i + 1:02d}T00:00:00Z", "equity": 1000.0 + i} for i in range(n)]


def _promote(tmp_path, *, producer_status=None):
    return promote_ide_run(
        ide_run_id="ide_wire_1", owner_username="alice", strategy_name="wire 策略",
        strategy_code="quantbt.emit_result({})", result={"equity_curve": _curve(30)},
        run_root=tmp_path, producer_status=producer_status,
    )


def _inject_section(monkeypatch, section_key: str, section_value: dict) -> None:
    """让 promote 评估的 manifest 携带一个 §9/§10 违例（模拟未来 producer 在 evaluate 前填 section）。

    薄 wrapper 包住真 default_chain：在 `evaluate` 入口就地把 section 写进 manifest（promote 传进来的正是
    它将落盘的 manifest 对象·故 run.json 也会带上该 section），再委托真链跑真门/真策略。promote 对此
    无感——它仍只调 `ensure_default_chain().evaluate(...)`。"""

    import app.release_gate.gate_registry as gr

    real_ensure = gr.ensure_default_chain

    class _Wrapper:
        def __init__(self, chain: PromoteGateChain) -> None:
            self._chain = chain

        def evaluate(self, manifest, *, producer_status=None):
            manifest[section_key] = section_value  # 模拟 producer 填值（就地·让 run.json 也可见）
            return self._chain.evaluate(manifest, producer_status=producer_status)

    monkeypatch.setattr(gr, "ensure_default_chain", lambda: _Wrapper(real_ensure()))


def _verdict(chain_dict: dict, gate_name: str) -> dict:
    matches = [v for v in chain_dict["verdicts"] if v["gate_name"] == gate_name]
    assert len(matches) == 1, f"promote_gate_chain 中应恰有一道 {gate_name} 裁定"
    return matches[0]


def _read_manifest(promoted) -> dict:
    return json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))


# ════════════════════════════════════════════════════════════════════════════
# ① §9 违例经 promote：producer 红 → advisory 记录不阻断（mutation 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_s9_violation_recorded_advisory_while_producer_red(tmp_path, monkeypatch):
    """★ 可证伪①（mutation 目标）：§9 违例经 promote_ide_run + producer 全红 → 裁决落 run.json 作
    advisory（记录·不阻断），promote **仍成功落盘**。"""

    _inject_section(monkeypatch, SECTION9_BOUNDARY_MANIFEST_KEY, _S9_VIOLATION)
    promoted = _promote(tmp_path)  # producer_status=None → 全红

    # promote 成功落盘（advisory 绝不阻断）
    assert promoted.run_id, "advisory 违例绝不阻断 promote（run 仍成功落盘）"
    assert (promoted.run_dir / "run.json").exists()

    manifest = _read_manifest(promoted)
    assert "promote_gate_chain" in manifest, "run.json 必含 promote_gate_chain（门链接进 promote 路径）"
    chain = manifest["promote_gate_chain"]
    assert chain["rejected"] is False, "producer 红 → §9 违例只 advisory·整链绝不 rejected"

    s9 = _verdict(chain, SECTION9_BOUNDARY_GATE_NAME)
    assert s9["advisory_or_enforce"] == "advisory", "producer 未绿 → §9 门停 advisory"
    assert s9["ok"] is False and s9["blocks"] is False, "门诚实记下未过·但 advisory 不阻断"
    assert s9["flip_refused"] is True and s9["producer_green"] is False, "拒翻被诚实记录·无假绿灯"
    assert _S9_CODE in s9["missing"], "违例码精确来自 canonical validator（复用不重造）"


# ════════════════════════════════════════════════════════════════════════════
# ② 同一 §9 违例 + producer 绿 → 阻断（mutation 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_s9_violation_blocks_when_producer_green(tmp_path, monkeypatch):
    """★ 可证伪②（mutation 目标）：**同一** §9 违例 + 对应 producer 标绿 → 同门翻 ENFORCE → promote
    抛 PromoteError（阻断）·被拒晋级**不留 run.json**（绝不冒充成功 run）。"""

    _inject_section(monkeypatch, SECTION9_BOUNDARY_MANIFEST_KEY, _S9_VIOLATION)
    ledger = ProducerStatusLedger()
    ledger.mark_green(SECTION9_BOUNDARY_PRODUCER_KEY)  # 仅此卡测试态·绝非生产假绿灯

    with pytest.raises(PromoteError) as ei:
        _promote(tmp_path, producer_status=ledger)
    assert SECTION9_BOUNDARY_GATE_NAME in str(ei.value), "拒因须点名 §9 门（reason_text 可追溯）"

    # 被门链拒的晋级绝不落 run.json
    assert list(tmp_path.glob("ide_*/run.json")) == [], "被门链拒的晋级绝不写 run.json"


# ════════════════════════════════════════════════════════════════════════════
# ③ §10 控制面违例同样经 promote 起效（证明 registry 收口的是多门·非单门特例）
# ════════════════════════════════════════════════════════════════════════════
def test_s10_controlplane_violation_advisory_then_blocks(tmp_path, monkeypatch):
    """§10 控制面（放宽档显强标签）违例经 promote：producer 红 → advisory 记录；producer 绿 → 阻断。"""

    # 红：advisory 记录不阻断
    _inject_section(monkeypatch, SECTION10_CONTROLPLANE_MANIFEST_KEY, _S10CP_VIOLATION)
    promoted = _promote(tmp_path)
    chain = _read_manifest(promoted)["promote_gate_chain"]
    assert chain["rejected"] is False
    cp = _verdict(chain, SECTION10_CONTROLPLANE_GATE_NAME)
    assert cp["advisory_or_enforce"] == "advisory" and cp["ok"] is False and cp["blocks"] is False
    assert _S10CP_CODE in cp["missing"]

    # 绿：同违例阻断
    ledger = ProducerStatusLedger()
    ledger.mark_green(SECTION10_CONTROLPLANE_PRODUCER_KEY)
    with pytest.raises(PromoteError) as ei:
        _promote(tmp_path, producer_status=ledger)
    assert SECTION10_CONTROLPLANE_GATE_NAME in str(ei.value)


# ════════════════════════════════════════════════════════════════════════════
# ④ 向后兼容：clean manifest promote 与既有完全一致（additive·不阻断）
# ════════════════════════════════════════════════════════════════════════════
def test_clean_promote_backward_compat(tmp_path):
    """clean manifest（无 §9/§10/§13 结构·不注入）→ 全门过 advisory·promote 成功·既有键不丢（additive）。"""

    promoted = _promote(tmp_path)  # 不注入·producer_status=None
    assert promoted.run_id and (promoted.run_dir / "run.json").exists()

    manifest = _read_manifest(promoted)
    # 既有键一个不丢（含 §16 release_verdict·两条 advisory 正交并存）
    for key in ("run_id", "status", "metrics", "source", "strategy_name", "release_verdict"):
        assert key in manifest, f"既有 manifest 键 {key!r} 不应因门链接线丢失"

    chain = manifest["promote_gate_chain"]
    assert chain["rejected"] is False, "clean run 绝不被门链拒"
    names = {v["gate_name"] for v in chain["verdicts"]}
    assert names == _ALL_GATE_NAMES, "registry 应把全部已落地节门注册进 promote 路径"
    for v in chain["verdicts"]:
        assert v["ok"] is True, "nothing-declared → 全门过（不误伤诚实 run）"
        assert v["advisory_or_enforce"] == "advisory" and v["blocks"] is False


def test_promote_gate_chain_is_json_safe(tmp_path, monkeypatch):
    """promote_gate_chain 必 JSON-safe（已落盘 run.json·能再 dumps 一遍·无对象残留）。"""

    _inject_section(monkeypatch, SECTION9_BOUNDARY_MANIFEST_KEY, _S9_VIOLATION)
    manifest = _read_manifest(_promote(tmp_path))
    json.dumps(manifest["promote_gate_chain"])  # 不抛即 JSON-safe


# ════════════════════════════════════════════════════════════════════════════
# ⑤ 无假绿灯：默认 producer_status=None → 全门 advisory + producer_green=False
# ════════════════════════════════════════════════════════════════════════════
def test_all_gates_advisory_no_producer_green_by_default(tmp_path):
    """★ 守 advisory-first：默认 producer_status=None → 三门全 advisory·**无任一 producer 假绿灯**。"""

    chain = _read_manifest(_promote(tmp_path))["promote_gate_chain"]
    assert chain["rejected"] is False
    for v in chain["verdicts"]:
        assert v["advisory_or_enforce"] == "advisory", "无 producer 标绿 → 全 advisory（advisory-first）"
        assert v["producer_green"] is False, "确认无任何 producer 假绿灯（出厂全红）"
        assert v["flip_refused"] is True, "enforce_intent 门 producer 红 → 拒翻被诚实记录（非静默）"


# ════════════════════════════════════════════════════════════════════════════
# ⑥ 单一注册收口：registry 注册恰已落地全部节门 + ensure_default_chain 幂等（reset 安全）
# ════════════════════════════════════════════════════════════════════════════
def test_registry_registers_exactly_the_landed_gates():
    """registry 把全部已落地节门（§9 边界/§10 成本/§10 控制面/§13 信任）注册进任意空链·无遗漏无多余。"""

    chain = PromoteGateChain()
    register_all_gates(chain)
    assert set(chain.gate_names) == _ALL_GATE_NAMES


def test_ensure_default_chain_idempotent_and_reset_safe():
    """ensure_default_chain 幂等：连调两次不撞 register 防重抛·返回同一进程级单例·reset 后重填。"""

    reset_default_chain()
    c1 = ensure_default_chain()
    assert set(c1.gate_names) == _ALL_GATE_NAMES
    c2 = ensure_default_chain()  # 第二次：链非空 → 跳过注册（不抛重复）
    assert c1 is c2 and set(c2.gate_names) == _ALL_GATE_NAMES
    reset_default_chain()
    c3 = ensure_default_chain()  # reset 后 → 重新填满
    assert set(c3.gate_names) == _ALL_GATE_NAMES


# ════════════════════════════════════════════════════════════════════════════
# ⑦ 冷导入安全（SA-3 纪律·镜像 section9/section10/chain 模块）
# ════════════════════════════════════════════════════════════════════════════
def test_gate_registry_cold_importable():
    """冷导入：全新解释器 import gate_registry **不**撞 app.governance 既有冷导入循环（顶层不触 governance·
    register 内 governance 惰性载入只在调用期触发·模块无 import 期 auto-register 副作用）。"""

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.release_gate.gate_registry as m; "
        "assert m.ensure_default_chain and m.register_all_gates"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"gate_registry 应冷导入成功（不依赖导入顺序）:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
