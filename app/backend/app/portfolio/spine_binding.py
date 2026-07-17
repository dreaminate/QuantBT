"""Mathematical Spine 绑定 · 真 ERC（等风险贡献）接 canonical 命门（金融数学 kernel P0-A #8）。

把 ``optimizers.equal_risk_contribution`` 的真实实现绑进脊柱（``app/lineage/spine*``），复用与
``app/math/risk_measures/spine_binding.py`` 同一套 artifact → binding → 独立 oracle 数值对账 →
一致性门：

    ERC_ARTIFACT（proof_backed 数学定义：RC_i=1/N ∀i）
      → build_erc_binding（真源码链指纹 code_content_hash·**仅 solver 路径**）
      → {dense_rc, closedform}_check（impl vs 独立 oracle 数值对账）
      → evaluate_promotion（命门裁定：实现漂离定义 → 拒升级）

独立 oracle 走【另一条计算路径】核同一定义（codex/GPT-5.6-sol 授权数学裁决 D-MATH-DECIDER）：
- **dense-RC 残差 oracle（主）**：impl 诊断返回 (sum(w), N·r̂_1,…,N·r̂_N)，r̂_i=w_i(Σw)_i/(wᵀΣw)
  在本模块**独立重算**（不调 solver 内部 helper）；oracle 返回全 1。numerical_consistency_check
  的绝对容差于是度量「相对风险预算误差」。这条在 **N≥3 相关** 结构上杀死「永远返回 inverse-vol」的
  伪 ERC（对角/2-asset 单独不够——那里 inverse-vol 恰等于 ERC）。
- **对角/2-asset 闭式 oracle（次）**：diagonal 及 2-asset 相关 Σ 上 ERC 精确退化为 inverse-vol，
  故 impl 权重 == ``inverse_volatility`` 权重（闭式·另一条路径）。

⚠️ **oracle 与 solver 两条独立代码路径**：``inverse_volatility`` 是对角 oracle，**绝不**并进
``_ERC_IMPL_CHAIN``——否则改它会同时动 solver 指纹与 oracle、耦合两路、废掉独立性（codex 推翻
「折叠 inverse_volatility 进链」的方案）。ARTIFACT_ESTIMATOR ∈ ``spine_gate.PIT_REQUIRING_TYPES``，
故命门强制 PIT 数据契约（协方差估计窗口须实现前 PIT、无 look-ahead）。诚实边界见 ``spine_gate``：
门校验「声明 vs 证据自洽 + 标签强度匹配」，不自证数学命题——那靠这里独立 oracle 内容 + Verifier。
"""

from __future__ import annotations

import numpy as np

from ..lineage.ids import content_hash
from ..lineage.spine import (
    ARTIFACT_ESTIMATOR,
    PROOF_BACKED,
    MathematicalArtifact,
    TheoryImplementationBinding,
)
from ..lineage.spine_binder import numerical_consistency_check
from ..lineage.spine_gate import SpineDecision, evaluate_promotion
from . import _erc_solver as _erc
from . import optimizers as _opt

# ════════════════════════════ ERC 绑定（数值对账）════════════════════════════

ERC_ARTIFACT = MathematicalArtifact(
    artifact_type=ARTIFACT_ESTIMATOR,
    statement=(
        "ERC：w_i·(Σw)_i = w_j·(Σw)_j ∀i,j，s.t. 1ᵀw=1, w>0 ⇒ 相对风险贡献 r_i=w_i(Σw)_i/(wᵀΣw)=1/N。"
        "解唯一凸问题 min_{y>0} ½yᵀRy − (1/N)Σln y_i（R=D⁻¹ΣD⁻¹ 相关矩阵，D=diag(σ)），映回 x=D⁻¹y、w=x/1ᵀx"
    ),
    notation="Σ=SPD 协方差; D=diag(σ_i); R=D⁻¹ΣD⁻¹ 相关矩阵; C_i=w_i(Σw)_i 绝对贡献; r_i=C_i/(wᵀΣw) 相对贡献; N=资产数",
    assumptions=(
        "Σ 有限、对称、数值 SPD；各方差严格正",
        "long-only 全额投资（1ᵀw=1, w>0）；long-short ERC 非唯一，本实现不覆盖",
        "共同收益周期/基准货币；协方差与 universe 满足 PIT（估计窗口 end ≤ rebalance 决策时点、无 look-ahead）",
        "无额外绑定约束（sector/pair cap、single_pos_max、leverage<1 均破 ERC，须另立 artifact）",
    ),
    definition="Equal Risk Contribution：各标的对组合方差贡献相等的 long-only 全额组合（Maillard-Roncalli-Teïletche 2010）",
    derivation=(
        "对角 Σ ⇒ C_i=σ_i²w_i² ⇒ σ_iw_i 相等 ⇒ w∝1/σ（=inverse-vol）；N=2 时协方差交叉项在 C_1−C_2 抵消 ⇒ 仍=inverse-vol"
        "（判别真 ERC 须 N≥3 相关）。一般 Σ 由 log-barrier FOC y_i(Ry)_i=1/N（=x_i(Σx)_i）得等绝对贡献，归一化保持相对贡献相等"
        "（w_i(Σw)_i=(1/N)/s²、wᵀΣw=1/s² ⇒ r_i=1/N）。不把 1ᵀw=1 加进障碍问题（否则 KKT 多预算乘子破坏 ERC 方程）"
    ),
    proof_sketch=(
        "严格凸（∇²f=R+diag((1/N)/y²)≻0）+ SPD R 使二次项无穷远占优、log 障碍在 y_i↓0 趋 +∞ ⇒ 唯一内点极小=唯一 ERC"
        "（存在唯一性 Maillard 2010）；damped Newton（Cholesky 解方向 + Armijo 保正线搜）在紧内点水平集全局收敛、解附近二次收敛（Spinu 2013 / Griveau-Billion-Richard-Roncalli 2013）"
    ),
    counterexamples=(
        "N≥3 非均匀相关下 inverse-vol 通常≠ERC（codex 实证 3 资产 SPD 例 inverse-vol 相对贡献=(3/7,3/14,5/14)≠(1/3,1/3,1/3)）——即被修的错标实现",
        "min-variance / equal-weight ≠ ERC（除非 Σ 退化）",
        "post-hoc 权重截断（apply_constraints）破坏 RC 相等——约束 ERC 是另一 artifact",
        "零方差资产使 inverse-vol 闭式未定义；奇异/近秩亏 Σ 被本实现契约拒绝",
    ),
    units="w / r_i 无量纲（Σr_i=1）；Σ 与 wᵀΣw 为 return²；volatility contribution 为 return",
    dimensions="Σ:N×N; w:N; sum(w)=1",
    applicability="N≥2、Σ 数值 SPD、long-only 全额；N=1 → w=[1]；N=0 → {}",
    failure_conditions=(
        "非法协方差（非有限/非对称/方差非正/indefinite/近秩亏）/ rc_tolerance 非正/非有限/bool → fail-closed raise（拒 clip/jitter/shrink）",
        "rc_tolerance 是 best-effort 收敛目标（仅能收紧到硬地板以下·loose 值被夹到硬地板）；硬保证=返回权重 E_RC≤1e-6；max_iterations 内未达硬地板 → raise（绝不返回未收敛迭代或等权兜底）",
        "权重下溢为零 / sum(w)≠1 / V(w)≤0 / 返回权重 Σ 空间 RC 后置校验超硬地板 → raise",
    ),
    proof_status=PROOF_BACKED,
    implementation_ref="app/backend/app/portfolio/_erc_solver.py:equal_risk_contribution",
    test_ref="app/backend/tests/test_portfolio_erc_spine.py",
    validation_ref="app/backend/tests/test_portfolio.py",
)
# ERC 输入 Σ 须 PIT 正确——估计器输入的时间语义（满足门 pit-bound 子句）。
# 诚实边界：raw DataFrame 本身无时间元数据；production caller 仍须提供带时戳的 covariance/
# MarketDataUse ref，非空字典 ≠ 运行时 PIT 证明（codex 明示）。
ERC_DATA_CONTRACT = {
    "known_at": "covariance_estimate_known_at",
    "effective_at": "portfolio_rebalance_effective_at",
    "desc": (
        "Σ、asset universe 及其所有 return observations 在 covariance_estimate_known_at 前已知；"
        "weights 只在该时点或之后生效；禁 future returns / future constituents / revision look-ahead"
    ),
}
# 实现指纹 = 【整个 _erc_solver 模块文本】（codex floor #6）：``inspect.getsource(fn)`` 只取函数体、
# 不含模块级 import（``from scipy.linalg import cho_solve`` 等）——改 import 来源能悄改 solver 行为却
# 不触发 staleness。故 solver 隔离成 ``_erc_solver`` 模块、指纹整模块文本（imports+globals+全部函数）→
# 改任一处都触发 staleness。【不含】inverse_volatility（optimizers.py 的对角 oracle）与本模块 oracle——
# 独立 oracle 路径。改 _erc_solver.py 后必须：重跑 test_portfolio_erc_spine + 更新此常量。
ERC_PINNED_FINGERPRINT = "0840b622b19910a7"


# ── 确定性 fixtures（无 RNG）─────────────────────────────────────────────────


def _mkcov(sigmas: list[float], corr: list[list[float]]) -> "object":
    """从波动率 + 相关矩阵造协方差 DataFrame（标的名 A0..A{n-1}，稳定 symbol order）。"""

    import pandas as pd

    d = np.diag(sigmas)
    cov = d @ np.asarray(corr, dtype=float) @ d
    labels = [f"A{i}" for i in range(len(sigmas))]
    return pd.DataFrame(cov, index=labels, columns=labels)


def _erc_dense_fixtures() -> list[dict]:
    """dense-RC 对账用：N≥3 相关（真 ERC 的 RC=1/N 非平凡）+ 极端 vol，杀「永远 inverse-vol」伪 ERC。"""

    return [
        # codex 跨厂商实证例：inverse-vol RC=(3/7,3/14,5/14)≠ERC
        {"cov": _mkcov([0.1, 0.2, 0.3], [[1, 0.1, 0.7], [0.1, 1, -0.2], [0.7, -0.2, 1.0]])},
        # 4 资产块相关
        {"cov": _mkcov([0.15, 0.15, 0.25, 0.4],
                       [[1, 0.6, 0.1, 0.0], [0.6, 1, 0.1, 0.0], [0.1, 0.1, 1, 0.3], [0.0, 0.0, 0.3, 1]])},
        # 极端 vol 尺度（scale-safe 相关变换判别）
        {"cov": _mkcov([0.001, 0.5, 2.0], [[1, 0.3, -0.4], [0.3, 1, 0.2], [-0.4, 0.2, 1.0]])},
        # 对角（RC=1/N 处处成立·真 ERC 也须过）
        {"cov": _mkcov([0.1, 0.25, 0.4, 0.15], [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])},
    ]


def _erc_closedform_fixtures() -> list[dict]:
    """闭式退化用：仅 diagonal 与 2-asset（这里 ERC 精确=inverse-vol；N≥3 相关会让真 ERC≠inv-vol、不可放此）。"""

    return [
        {"cov": _mkcov([0.1, 0.25, 0.4, 0.15], [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])},
        {"cov": _mkcov([0.12, 0.31], [[1, 0.83], [0.83, 1]])},  # 2-asset 任意相关 → =inverse-vol
        {"cov": _mkcov([0.2, 0.2], [[1, -0.5], [-0.5, 1]])},
    ]


# ── 独立 oracle：从数学定义【另一条计算路径】重算 ─────────────────────────────


def _erc_dense_rc_diagnostic(weight_fn):
    """impl 诊断（可注入任意 weight_fn）：返回 (sum(w), positivity_flag, N·r̂_1,…,N·r̂_N)。

    ⚠️ 独立性：r̂_i=w_i(Σw)_i/(wᵀΣw) 在本模块从 Σ、w 直接重算，**不调** solver 内部收敛 helper——
    与 solver 两条路径。注入 inverse_volatility 作 weight_fn 时，N≥3 相关上 N·r̂_i≠1 → 被逮。
    ⚠️ **long-only 门（codex floor #1）**：SPD 在其他符号象限也有 RC=1/N 解（如 {1.45,-0.86,0.40}·
    RC 误差 8.9e-16）——只核 RC 相等会漏放签名解。故加 positivity_flag = 1.0 iff 键集精确∧全有限∧
    全 w_i>0，否则 0.0（oracle 要求恰 1）。键集错/V≤0/非有限 → 全 NaN（偏差 inf → fail）。
    """

    def _impl(*, cov):
        syms = list(cov.columns)
        n = len(syms)
        w = weight_fn(cov)
        if not isinstance(w, dict) or set(w.keys()) != set(syms):
            return [float("nan")] * (n + 2)
        wv = np.array([float(w[s]) for s in syms], dtype=float)
        sigma = np.asarray(cov.loc[syms, syms].values, dtype=float)
        v = float(wv @ sigma @ wv)
        if not (v > 0 and np.isfinite(v)):
            return [float("nan")] * (n + 2)
        r = wv * (sigma @ wv) / v
        pos_flag = 1.0 if (bool(np.all(np.isfinite(wv))) and bool(np.all(wv > 0.0))) else 0.0
        return [float(np.sum(wv)), pos_flag] + [float(n * ri) for ri in r]

    return _impl


def _erc_dense_rc_oracle(*, cov) -> list[float]:
    """dense-RC oracle：ERC 定义 ⇒ sum(w)=1、long-only positivity=1、N·r_i=1 ∀i → 全 1（长度 N+2）。"""

    n = len(list(cov.columns))
    return [1.0] * (n + 2)


def _erc_weight_tuple(weight_fn):
    """impl 权重按稳定 symbol order 成 tuple（可注入任意 weight_fn）。"""

    def _impl(*, cov):
        w = weight_fn(cov)
        return [float(w[s]) for s in list(cov.columns)]

    return _impl


def _erc_closedform_oracle(*, cov) -> list[float]:
    """闭式 oracle：diagonal/2-asset 上 ERC 精确=inverse-vol（另一条闭式路径，不解 Newton）。"""

    w = _opt.inverse_volatility(cov)
    return [float(w[s]) for s in list(cov.columns)]


# ── 实现链指纹 ────────────────────────────────────────────────────────────────


def _public_api_source() -> str:
    """SOURCE TEXT of ``app.portfolio`` 公共 ``__init__``（导出绑定），折进指纹使 re-bind 公共名
    （``risk_parity = inverse_volatility``）触发 staleness。用 .py 文本、非模块对象（其 repr 含
    绝对 checkout 路径 → 指纹路径相关、CI 上碎；本机假 pinned-match）。lazy import 避免循环加载。
    """

    import importlib
    import inspect

    return inspect.getsource(importlib.import_module("app.portfolio"))


def _erc_solver_source() -> str:
    """整个 ERC solver 模块的 SOURCE TEXT（imports + globals + 全部函数）——捕获模块级 import 变更
    （codex floor #6：函数体指纹漏掉 import 来源）。用 .py 文本、非模块对象 repr（后者含绝对路径 →
    路径相关·CI 碎）。inverse_volatility 在 optimizers.py、不在本源文本内 → oracle 路径独立。
    """

    import importlib
    import inspect

    return inspect.getsource(importlib.import_module("app.portfolio._erc_solver"))


def erc_code_fingerprint() -> str:
    # bridge_intact（codex floor R2 #4）：solver 真身在 _erc_solver；optimizers/__init__ 只是 re-export
    # 桥。重绑 optimizers.equal_risk_contribution 不改模块文本、却断桥（callers 经 optimizers 拿到别的
    # 函数）——此布尔翻 False → 指纹变 → staleness 真触发。桥拿到的必须 is solver 真身。
    bridge_intact = (
        _opt.equal_risk_contribution is _erc.equal_risk_contribution
        and _opt.ERCError is _erc.ERCError
    )
    return content_hash(
        {
            "solver_module": _erc_solver_source(),
            "public_api": _public_api_source(),
            "bridge_intact": bridge_intact,
        }
    )


# ── binding 构造 ──────────────────────────────────────────────────────────────


def build_erc_binding(code_content_hash: str | None = None) -> TheoryImplementationBinding:
    return TheoryImplementationBinding(
        theory_ref=ERC_ARTIFACT.artifact_id,
        code_ref="app/backend/app/portfolio/_erc_solver.py:equal_risk_contribution",
        code_content_hash=code_content_hash or erc_code_fingerprint(),
        config_ref="portfolio:solver=corr_space_damped_newton,rc_tolerance=1e-8,max_iterations=100,pd_gate=eig,fail_closed=true",
        data_contract_ref="contract/covariance_estimate_pit",
        implementation_spec="equal_risk_contribution(cov,*,rc_tolerance,max_iterations) → long-only 全额 ERC 权重",
        test_refs=("app/backend/tests/test_portfolio_erc_spine.py",),
        dimension_check="w 无量纲、sum(w)=1、r_i=1/N 无量纲；Σ 方差量纲",
        tolerance=1e-6,
    )


# ── 一致性对账 ────────────────────────────────────────────────────────────────


def erc_dense_rc_check(impl=_opt.equal_risk_contribution, *, binding=None):
    """ERC impl vs dense-RC 残差 oracle（主·N≥3 相关杀伪 ERC）；impl 参数仅测试注入漂移用。"""

    binding = binding if binding is not None else build_erc_binding()
    return numerical_consistency_check(
        binding.binding_id,
        _erc_dense_rc_diagnostic(impl),
        _erc_dense_rc_oracle,
        _erc_dense_fixtures(),
        tolerance=1e-6,
        affected_assets=("ERC", "risk_budget", "portfolio_weights"),
    )


def erc_closedform_check(impl=_opt.equal_risk_contribution, *, binding=None):
    """ERC impl vs 对角/2-asset 闭式 oracle（次·退化=inverse-vol）；impl 参数仅测试注入漂移用。"""

    binding = binding if binding is not None else build_erc_binding()
    return numerical_consistency_check(
        binding.binding_id,
        _erc_weight_tuple(impl),
        _erc_closedform_oracle,
        _erc_closedform_fixtures(),
        tolerance=1e-8,
        affected_assets=("ERC", "inverse_volatility_reduction"),
    )


# ── 全链裁定 ──────────────────────────────────────────────────────────────────


# staleness 默认路径：binding 记【已审定 pinned】指纹、current 读 live 源指纹。改 optimizers.py
# ERC 链未重 pin → live≠pinned → 门 fresh 子句真拒（默认即查 staleness·非自我指纹）。


def verify_erc_consistency(
    *,
    requested_label: str = PROOF_BACKED,
    impl=_opt.equal_risk_contribution,
    pinned_code_hash: str | None = None,
    current_code_hash: str | None = None,
) -> SpineDecision:
    binding = build_erc_binding(code_content_hash=pinned_code_hash or ERC_PINNED_FINGERPRINT)
    checks = [erc_dense_rc_check(impl, binding=binding), erc_closedform_check(impl, binding=binding)]
    code_hash = current_code_hash if current_code_hash is not None else erc_code_fingerprint()
    return evaluate_promotion(
        ERC_ARTIFACT, binding, checks,
        requested_label=requested_label, current_code_hash=code_hash, data_contract=ERC_DATA_CONTRACT,
    )
