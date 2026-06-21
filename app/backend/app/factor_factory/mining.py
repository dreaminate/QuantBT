"""F4 · R16/R19 暴力遍历挖掘引擎（生成器 / 守门器**严格解耦**；诚实-N 走一本账）。

定位（dev/decisions §R19 + GOAL §3）：暴力遍历是**廉价候选生成器**，不是「挖矿机」。
铁律（违一条即验证集泄露 / honest-N 洗白）：

1. **生成器 / 守门器严格解耦**：
   - 生成器（`generate_candidates`）只看**结构维度**（复杂度 / 算子覆盖 / 族多样性 /
     结构新颖度）排序候选。
   - 守门器（`evaluate_gate`）是**独立后置**环节，才看 IC/IR/DSR 等守门指标。
2. **守门指标绝不进生成 fitness**（R19②）：任何含 IC/IR/DSR/Sharpe/PBO/t/return… 关键词的
   排序键塞进生成器 → `MiningGateLeakError`。这是「先看结果再生成」选择偏误的硬门。
3. **诚实-N 复用 lineage 一本账**（R8/R19④）：候选去重/计数走 `lineage.ids.config_hash`
   语法级归一（`a*2`≡`a*2`≡`(a*2)`），等价改写**不抬高 N_eff**。绝不自造第二套去重。
4. **守门裁决不假绿灯**（RULES §3 / R25）：不达标 → passed=False + 诚实 note；
   裁决措辞绝不出现「可信 / 安全 / 排除过拟合」。

诚实边界：本模块的 IC/IR/DSR 是**确定性合成占位**（与前端 mock 同式），用于把「解耦 +
诚实-N + 不假绿灯」三条治理不变量做成**真后端逻辑**可对抗测试；真实守门指标接 eval 子系统
在后续卡接入。守门指标合成绝不回流进生成器（解耦在结构上强制，不靠纪律）。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from ..lineage.ids import config_hash, normalize_factor_ast

# ── R16/R19②：守门指标关键词黑名单（绝不可作生成器排序/fitness 维度）。 ──
# 与前端 factorLabData.GATE_METRIC_KEYWORDS 同口径（两端镜像，测试钉死）。
GATE_METRIC_KEYWORDS: tuple[str, ...] = (
    "ic", "ir", "dsr", "sharpe", "pbo", "cscv",
    "tstat", "pnl", "return", "alpha", "ret", "sortino", "calmar",
)

# 生成器允许的排序键（白名单，全是结构维度，零守门指标）。
GENERATOR_SORT_KEYS: tuple[str, ...] = ("complexity", "op_coverage", "family_diversity", "novelty")


class MiningError(ValueError):
    """挖掘引擎一般错误。"""


class MiningGateLeakError(MiningError):
    """R16 解耦门：守门指标被塞进生成器排序/fitness（验证集泄露的入口），拒。"""


def is_gate_metric_key(key: str) -> bool:
    """某排序键是否「污染」了守门指标（命中黑名单关键词）。与前端 isGateMetricKey 同算法。"""

    k = "".join(ch for ch in key.lower() if ch.isalnum())
    return any(m.replace("_", "").replace("-", "") in k for m in GATE_METRIC_KEYWORDS)


def assert_generator_sort_key_clean(key: str) -> None:
    """断言生成器排序键里无任何守门指标。命中即抛 —— 解耦门的强制点。"""

    if is_gate_metric_key(key):
        raise MiningGateLeakError(
            f"R16 解耦门：守门指标『{key}』不可进生成器候选排序/fitness——"
            "生成器只看结构多样性，守门在独立后置环节（否则验证集泄露）"
        )


# ── 候选 / 守门结果数据结构 ─────────────────────────────────────────────────
@dataclass
class MiningCandidate:
    """生成器产出的单个候选。**只带结构属性，无任何守门指标**（IC/IR/DSR 不在此）。"""

    candidate_id: str
    expr: str
    fam: str
    complexity: int            # 嵌套深度*10 + 算子数（结构）
    op_count: int              # 用到的算子数（结构）
    novelty: float             # 结构新颖度 0..1（结构）
    config_hash: str           # lineage 语法级归一身份（诚实-N 去重键）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    """守门器独立后置算出的裁决。IC/IR/DSR **只在这里出现**（生成器永不见）。"""

    candidate_id: str
    ic: float
    ir: float
    dsr: float
    passed: bool
    note: str = ""             # 未过原因（passed=False 时非空；诚实，不染绿）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HonestNReport:
    """诚实-N 计数（走 lineage config_hash 归一去重）。恒有 n_eff ≤ total。"""

    total: int
    n_eff: int
    duplicates: int
    disclosure: str = field(
        default=(
            "n_eff 为语法级归一（lineage.config_hash）后的 distinct 计数，是真值【下界】："
            "等价改写已去重，但语义同义（a*2≡a+a）与 agent 隐式试验未计入；"
            "本计数只回答「显式提交了几个不同结构」，不对结论下任何定性判断。"
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── 结构度量（生成器视野；全是结构，零守门指标）────────────────────────────
def _max_paren_depth(expr: str) -> int:
    depth = 0
    best = 0
    for ch in expr:
        if ch == "(":
            depth += 1
            best = max(best, depth)
        elif ch == ")":
            depth = max(0, depth - 1)
    return best


def _op_count(expr: str) -> int:
    """函数调用样式 `name(` 的个数 = 用到的算子数（结构维度）。"""

    count = 0
    i = 0
    n = len(expr)
    while i < n:
        if expr[i] == "(":
            j = i - 1
            while j >= 0 and (expr[j].isalnum() or expr[j] == "_"):
                j -= 1
            if j < i - 1 and (expr[j + 1].isalpha() or expr[j + 1] == "_"):
                count += 1
        i += 1
    return count


def _novelty(expr: str, seen_norms: set[str]) -> float:
    """结构新颖度 0..1：与已见结构的「归一形差异度」。确定性、只看结构。"""

    norm = normalize_factor_ast(expr)
    if norm in seen_norms:
        return 0.0
    # 与已见集合的最小 token 重合度 → 越独特越高（确定性，无随机）。
    if not seen_norms:
        return 1.0
    toks = set(norm)
    best_overlap = 0.0
    for s in seen_norms:
        st = set(s)
        inter = len(toks & st)
        union = len(toks | st) or 1
        best_overlap = max(best_overlap, inter / union)
    return round(1.0 - best_overlap, 4)


def candidate_config_hash(expr: str) -> str:
    """候选的诚实-N 去重键 = lineage.config_hash（语法级归一，单一身份源）。"""

    return config_hash(factor=expr)


# ── 生成器（结构排序；守门指标在此**结构上**不可达）──────────────────────────
def generate_candidates(
    exprs: list[dict[str, Any]] | list[tuple[str, str]],
    *,
    sort_key: str = "complexity",
) -> list[MiningCandidate]:
    """暴力遍历生成器：输入 (expr, fam) 列表 → 结构度量 + 按结构排序候选。

    解耦在结构上强制：本函数签名里**没有**任何守门指标入口；`sort_key` 先过
    `assert_generator_sort_key_clean`，守门指标关键词当场拒。
    """

    assert_generator_sort_key_clean(sort_key)
    if sort_key not in GENERATOR_SORT_KEYS:
        raise MiningError(
            f"未知生成器排序键 {sort_key!r}；允许 {list(GENERATOR_SORT_KEYS)}（全是结构维度）"
        )

    norm_pairs: list[tuple[str, str]] = []
    for item in exprs:
        if isinstance(item, dict):
            norm_pairs.append((item["expr"], item.get("fam", "未知")))
        else:
            norm_pairs.append((item[0], item[1] if len(item) > 1 else "未知"))

    seen_norms: set[str] = set()
    cands: list[MiningCandidate] = []
    for i, (expr, fam) in enumerate(norm_pairs):
        nov = _novelty(expr, seen_norms)
        seen_norms.add(normalize_factor_ast(expr))
        opc = _op_count(expr)
        depth = _max_paren_depth(expr)
        cands.append(
            MiningCandidate(
                candidate_id=f"cand_{i}",
                expr=expr,
                fam=fam,
                complexity=depth * 10 + opc,
                op_count=opc,
                novelty=nov,
                config_hash=candidate_config_hash(expr),
            )
        )

    def keyfn(c: MiningCandidate):
        if sort_key == "complexity":
            return (-c.complexity, c.candidate_id)
        if sort_key == "op_coverage":
            return (-c.op_count, c.candidate_id)
        if sort_key == "novelty":
            return (-c.novelty, c.candidate_id)
        return (c.fam, c.candidate_id)  # family_diversity

    return sorted(cands, key=keyfn)


# ── 守门器（独立后置；IC/IR/DSR 只在这里产生）───────────────────────────────
def _lz(i: int) -> float:
    """确定性伪随机（与前端 factorLabData.lz 同式，保证跨端/测试稳定）。"""

    x = math.sin(i * 12.9898 + 3.71) * 43758.5453
    return x - math.floor(x)


def evaluate_gate(
    candidates: list[MiningCandidate],
    *,
    ic_min: float = 0.02,
    ir_min: float = 0.5,
) -> list[GateResult]:
    """守门器：给候选算 IC/IR/DSR + 诚实门槛裁决（独立后置环节）。

    门槛：|IC|≥ic_min 且 IR≥ir_min 且 DSR≥0 才 passed（不达标不染绿，R25）。
    DSR<0 视为去膨胀后失真（加密短样本 caveat，R16=B）。
    """

    out: list[GateResult] = []
    for i, c in enumerate(candidates):
        ic = (_lz(i * 7 + 1) - 0.42) * 0.09
        ir = (_lz(i * 7 + 3) - 0.35) * 1.6
        dsr = (_lz(i * 7 + 5) - 0.45) * 0.8
        passed = abs(ic) >= ic_min and ir >= ir_min and dsr >= 0
        note = ""
        if not passed:
            fails: list[str] = []
            if abs(ic) < ic_min:
                fails.append(f"|IC|<{ic_min}")
            if ir < ir_min:
                fails.append(f"IR<{ir_min}")
            if dsr < 0:
                fails.append("DSR<0（去膨胀后失真）")
            note = " · ".join(fails)
        out.append(GateResult(candidate_id=c.candidate_id, ic=ic, ir=ir, dsr=dsr, passed=passed, note=note))
    return out


# ── 诚实-N（复用 lineage config_hash 归一；绝不自造第二套去重）────────────────
def honest_n(exprs: list[str]) -> HonestNReport:
    """在候选公式集合里数「不同结构」个数（n_eff）。等价改写只计一次。

    去重键 = `lineage.config_hash`（语法级归一，单一身份源）—— 与一本账、与内核 node_id
    共用同一份归一，杜绝双产方。恒有 n_eff ≤ total。
    """

    seen = {candidate_config_hash(e) for e in exprs}
    total = len(exprs)
    n_eff = len(seen)
    return HonestNReport(total=total, n_eff=n_eff, duplicates=total - n_eff)


def run_mining(
    exprs: list[dict[str, Any]],
    *,
    sort_key: str = "complexity",
    ic_min: float = 0.02,
    ir_min: float = 0.5,
) -> dict[str, Any]:
    """一次完整挖掘：生成（结构排序）→ 守门（独立后置）→ 诚实-N。

    返回 {candidates, gate, honest_n, pass_count}；candidates 与 gate 物理分离（不同列表）
    —— 守门指标从不与生成结构在同一对象里被排序。
    """

    cands = generate_candidates(exprs, sort_key=sort_key)
    gate = evaluate_gate(cands, ic_min=ic_min, ir_min=ir_min)
    hn = honest_n([c.expr for c in cands])
    return {
        "candidates": [c.to_dict() for c in cands],
        "gate": [g.to_dict() for g in gate],
        "honest_n": hn.to_dict(),
        "pass_count": sum(1 for g in gate if g.passed),
        "sort_key": sort_key,
    }


__all__ = [
    "GATE_METRIC_KEYWORDS",
    "GENERATOR_SORT_KEYS",
    "GateResult",
    "HonestNReport",
    "MiningCandidate",
    "MiningError",
    "MiningGateLeakError",
    "assert_generator_sort_key_clean",
    "candidate_config_hash",
    "evaluate_gate",
    "generate_candidates",
    "honest_n",
    "is_gate_metric_key",
    "run_mining",
]
