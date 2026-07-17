"""Mathematical Spine 绑定 · 真 Ledoit-Wolf 协方差收缩接 canonical 命门（金融数学 kernel P0-A #8 续）。

把 ``_lw_shrinkage.ledoit_wolf`` 的真实实现绑进脊柱（``app/lineage/spine*``），复用与 ERC/VaR-ES 同一套
artifact → binding → 独立 oracle 数值对账 → 一致性门。**impl 是第三方库（sklearn.covariance.LedoitWolf）**，
故独立 oracle 走【手写 LW-2004 outer-product 路径】（不 import/call sklearn·另一条独立代码路径），核同一
数学定义 δ*=min(1,π̂/(Tγ̂))；两者一致 → 抓「sklearn 行为漂离 LW-2004 定义」的漂移（codex/deep-opus 各实证
手写 δ*==sklearn 到 1e-16）。ARTIFACT_ESTIMATOR ∈ ``spine_gate.PIT_REQUIRING_TYPES``，故命门强制 PIT
（收益窗口须实现前 PIT、无 look-ahead）。**指纹只哈希源码 + 绑定身份·不含依赖版本**（codex 裁 C+·三职责分离：
code fingerprint / runtime provenance〔config_ref 披露〕/ behavioral conformance〔每环境现场跑 oracle〕）。

⚠️ 命名裁决（codex 授权数学决策者 D-MATH-DECIDER）：公开 `ledoit_wolf` 用 classic/sklearn 口径
δ*=min(1,π̂/(Tγ̂))——**不**塞 ρ̂-corrected 式（后者 δ 差 ~0.047·非舍入·是另一 artifact）。oracle 用**同一**
classic 式（否则 oracle≠impl 假 fail）。诚实边界见 ``spine_gate``：门校验声明↔证据自洽·不自证数学命题。
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
from . import _lw_shrinkage as _lw

# ════════════════════════════ LW 绑定（数值对账）════════════════════════════

LW_ARTIFACT = MathematicalArtifact(
    artifact_type=ARTIFACT_ESTIMATOR,
    statement=(
        "Ledoit-Wolf 2004 scaled-identity 收缩：Σ*=(1−δ*)S+δ*μI，S=XᵀX/T（MLE·去均值），μ=tr(S)/N，"
        "δ*=max(0,min(1,π̂/(T·γ̂)))；π̂=(1/T)Σ_t‖x_tx_tᵀ−S‖²_F；γ̂=‖S−μI‖²_F（classic 口径·不减 ρ̂）"
    ),
    notation="X=T×N 去均值收益; S=MLE 协方差; μ=平均方差=tr(S)/N; F=μI 目标; π̂=样本协方差元素渐近方差和; γ̂=目标失配; δ*=收缩强度∈[0,1]",
    assumptions=(
        "收益窗口 PIT 正确（窗口全 observations 在决策时点前已知·无 look-ahead·无 future fill/成分股/revision）",
        "共同时间窗/频率/货币；有限四阶矩；i.i.d. 或论文适用弱依赖",
        "MLE(1/T) 正规化、按列去均值（assume_centered=False）；classic scaled-identity 口径（非 ρ̂-corrected·非 constant-correlation 目标）",
        "T≥2、N≥1；T<N 时 S 秩亏（奇异）·LW 以 δ*>0 正则化之（δ* 幅度数据依赖·非必近 1）；δ*=0 时 S 秩亏 → fail-closed raise",
    ),
    definition="Ledoit-Wolf 2004 良态协方差收缩估计——解析最优收缩强度 δ* 朝 μI 目标（Ledoit & Wolf 2004, JMVA 88(2):365-411）",
    derivation=(
        "最优线性收缩 δ*=β²/δ²（population Frobenius risk 最小）；bona-fide 一致估计 b²/d²，b²=min(b̄²,d²)，"
        "b̄²=(1/T²)Σ_t‖x_tx_tᵀ−S‖²=π̂/T，d²=‖S−μI‖²=γ̂ ⇒ δ*=min(1,π̂/(T·γ̂))。μI 目标下 classic 式不显式减 ρ̂"
        "（ρ̂ 属 constant-correlation 目标 LW-2003·此处标量 μ 的估计误差已并入 β²）"
    ),
    proof_sketch=(
        "Σ*=S 与 μI 的凸组合 ⇒ λ_i(Σ*)=δ*μ+(1−δ*)λ_i(S) ⇒ δ*>0 时 λ_min≥δ*μ>0（严格 SPD·条件数拉向 1·含 T<N 秩亏 S）；"
        "δ* 一致估计最优线性收缩（Ledoit-Wolf 2004 Thm 3.2）·渐近最优（非有限样本 MSE 保证）"
    ),
    counterexamples=(
        "固定 α 收缩（constant_shrinkage·α 不随数据自适应）≠ LW——即被修的错标实现",
        "ρ̂-corrected random-target estimator（δ 差 ~0.047·非舍入）·constant-correlation 目标（LW-2003）·OAS 均非本 artifact",
        "ddof=1 协方差喂 LW 与 sklearn MLE 口径漂移",
    ),
    units="δ* 无量纲∈[0,1]；Σ*/S/μ 为 return²",
    dimensions="X:T×N; S,Σ*:N×N; δ*,μ:标量",
    applicability="T≥2、N≥1、收益有限；N=1 → δ*=0 返回 MLE variance；T<N → S 奇异·δ*>0 正则（δ* 幅度数据依赖·非必近 1）",
    failure_conditions=(
        "returns 非 2D/复数/非有限、T<2、N<1、中心化后全零（μ=0）→ fail-closed raise（绝不静默兜底/用坏协方差续算）",
        "sklearn 返回 shape 错/非有限 Σ*/δ*、δ* 超 [0,1] 超浮点误差、Σ* 非 SPD（δ*>0 应 SPD·浮点失效）→ raise",
        "δ*∈[0,1] 由 min/max + π̂,γ̂≥0 数学保证（诚实限界·非可绕过）",
    ),
    proof_status=PROOF_BACKED,
    implementation_ref="app/backend/app/portfolio/_lw_shrinkage.py:ledoit_wolf",
    test_ref="app/backend/tests/test_portfolio_lw_spine.py",
    validation_ref="app/backend/tests/test_academic_audit_v2.py",
)
# LW 输入收益须 PIT 正确——估计器输入的时间语义（满足门 pit-bound 子句）。诚实边界（同 ERC）：raw
# returns array 无时间元数据；production caller 仍须提供带时戳的 MarketDataUse ref·非空字典 ≠ 运行时 PIT 证明。
LW_DATA_CONTRACT = {
    "known_at": "returns_window_known_at",
    "effective_at": "shrinkage_estimate_effective_at",
    "desc": (
        "全部 returns、复权、FX、universe、缺失值处理在 returns_window_known_at 前可得；Σ* 只在该时点或"
        "之后生效；禁 future returns / future 成分股 / revision look-ahead"
    ),
}
# 实现指纹 = 【整个 _lw_shrinkage 模块文本】（codex floor2 #3）：``inspect.getsource(fn)`` 只取函数体·
# 漏模块级 import 重绑（`_lw.LedoitWolf = OAS` → δ 变而指纹不变）。镜 ERC whole-module 模式取整模块源
# （含 import 行）+ 运行时 solver 身份双查。【不含】手写 oracle（在本 binding 模块·独立路径·不得耦合）。
# **不含**依赖版本（codex 裁 C+）：版本=provenance 披露（config_ref）·非代码身份；行为漂移由每环境现场
# 跑的独立 oracle 对账直接测（诚实边界：oracle 非 version tripwire 的逻辑超集·见 lw_code_fingerprint 文档）。
# 重 pin·codex 裁 C+（`lw-code-v2`）：指纹去依赖版本 → **环境无关**（commit/source 耦合）。修 CI 实证 defect：
# 旧 pin `a0e2c805`（本机 sklearn1.8.0/numpy2.4.6）在 CI（实装 1.9.0/2.5.1）算得 `9f08cc6b` → 必红。
LW_PINNED_FINGERPRINT = "e908fc43ec0a63a5"


# ── 独立 oracle：手写 LW-2004 μI classic δ*（outer-product 路径·不 import/call sklearn）──


def _covariance_mle(returns: np.ndarray) -> tuple[np.ndarray, np.ndarray, int, int, float]:
    """去均值 + MLE(1/T) 协方差（oracle 侧独立重算·与 sklearn 无关）。"""

    x = np.asarray(returns, dtype=float)
    xc = x - x.mean(axis=0)
    t_obs, n = xc.shape
    s = xc.T @ xc / t_obs
    mu = float(np.trace(s) / n)
    return s, xc, t_obs, n, mu


def _lw_delta_oracle(returns: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, float]:
    """手写 LW-2004 μI classic δ*=min(1,π̂/(Tγ̂))——per-sample outer products（**不** sklearn block-dot）。"""

    s, xc, t_obs, n, mu = _covariance_mle(returns)
    gamma = float(np.sum((s - mu * np.eye(n)) ** 2))
    pi = 0.0
    for xt in xc:  # 逐样本 outer product·与 sklearn 内部 block dot 不同路径
        d = np.outer(xt, xt) - s
        pi += float(np.sum(d * d))
    pi /= t_obs
    delta = 0.0 if gamma == 0.0 else float(np.clip(pi / (t_obs * gamma), 0.0, 1.0))
    sigma = (1.0 - delta) * s + delta * mu * np.eye(n)
    return delta, sigma, s, mu


def _recover_delta_from_matrix(sigma: np.ndarray, s: np.ndarray, mu: float) -> float:
    """从任意 μI-shrunk Σ* 反解 δ：δ=1−<Σ*−μI, S−μI>/‖S−μI‖²（μI 收缩恒等式）。"""

    n = s.shape[0]
    diff_s = s - mu * np.eye(n)
    den = float(np.sum(diff_s * diff_s))
    if den == 0.0:
        return 0.0
    return 1.0 - float(np.sum((sigma - mu * np.eye(n)) * diff_s)) / den


# ── impl 诊断（可注入真 LW 或 mutation）+ oracle：尺度不变 O(1) 输出 ──────────────


def _lw_diagnostic(shrink_from_returns):
    """impl 诊断：返回 [δ_reported, δ_recovered] + (Σ*/μ).flatten()——尺度不变（除 μ·避日收益 ~1e-4 被绝对容差藏住）。

    shrink_from_returns(returns, S, mu) → (Σ*, δ_reported)。注入真 ledoit_wolf 或固定-α mutation。
    δ_recovered 从 Σ* 反解（μI 恒等式）——抓「Σ* 与声明 δ 不自洽」。键集/维度错/非有限 → NaN（偏差 inf → fail）。
    """

    def _impl(*, returns):
        s, xc, t_obs, n, mu = _covariance_mle(returns)
        if not (mu > 0 and np.isfinite(mu)):
            return [float("nan")] * (2 + n * n)
        sigma, reported = shrink_from_returns(returns, s, mu)
        sigma = np.asarray(sigma, dtype=float)
        if sigma.shape != (n, n) or not np.all(np.isfinite(sigma)):
            return [float("nan")] * (2 + n * n)
        rec = _recover_delta_from_matrix(sigma, s, mu)
        return [float(reported), float(rec)] + list((sigma / mu).flatten())

    return _impl


def _lw_oracle(*, returns) -> list[float]:
    """LW oracle：手写 δ* + Σ*（另一条路径）→ [δ*, δ*] + (Σ*/μ).flatten()。"""

    delta, sigma, s, mu = _lw_delta_oracle(returns)
    return [delta, delta] + list((sigma / mu).flatten())


def _real_lw_shrink(returns, s, mu):
    """真 impl：sklearn LedoitWolf（经 _lw.ledoit_wolf）→ (Σ*, δ*)。"""

    res = _lw.ledoit_wolf(returns)
    return res.covariance, res.shrinkage


# ── 确定性 fixtures（无 RNG·factor+idiosyncratic 三角构造·δ*∈(0,1)/高/低）────────


def _lw_fixtures() -> list[dict]:
    """判别 fixtures：correlated interior（δ*∈(0,1)·杀固定-α）+ 高收缩 T<N + 低收缩大 T。RNG-free。"""

    def _factor_returns(t_obs, n, amp, seed_shift):
        idx = np.arange(t_obs).reshape(-1, 1)  # (T,1)
        cols = np.arange(n).reshape(1, -1)  # (1,N)
        # rank-1 共同因子（时间序列 ⊗ 载荷向量·确定性三角·非 RNG）+ 特异噪声
        common = np.sin((idx + seed_shift) * 0.37) * np.cos(cols * 1.3 + seed_shift)  # (T,N)
        idio = np.cos((idx + seed_shift) * 1.1 + cols * 2.1)  # (T,N)
        return (amp * common + 0.5 * idio) * 0.01

    return [
        {"returns": _factor_returns(30, 4, 1.5, 1)},    # correlated interior（δ*∈(0,1)）
        {"returns": _factor_returns(20, 40, 0.3, 5)},   # T<N 秩亏 S·δ*>0 正则化（δ* 幅度数据依赖·此处 0.089）
        {"returns": _factor_returns(2000, 4, 3.0, 9)},  # 低收缩·大 T
    ]


# ── 代码身份指纹（源码 + 绑定身份·**环境无关**·不含依赖版本·codex 裁 C+）──────────


def _public_api_source() -> str:
    """``app.portfolio.hrp_audit`` re-export 源文本折进指纹（re-bind 公共名触发 staleness·path-independent）。"""

    import importlib
    import inspect

    return inspect.getsource(importlib.import_module("app.portfolio.hrp_audit"))


def _solver_module_source() -> str:
    """整个 ``_lw_shrinkage`` 模块源（codex floor2 #3）：``inspect.getsource(fn)`` 只取函数体·漏模块级
    import/重绑（`from sklearn.covariance import OAS as LedoitWolf` 或 `_lw.LedoitWolf = OAS`）。镜 ERC
    whole-module 模式取整模块文本（含 import 行）·path-independent。oracle 在本 binding 模块·仍排除。"""

    import importlib
    import inspect

    return inspect.getsource(importlib.import_module("app.portfolio._lw_shrinkage"))


def lw_code_fingerprint() -> str:
    """**代码身份**指纹（codex 裁 C+·schema `lw-code-v2`）：只哈希【源码 + 运行时绑定身份】·**不含依赖版本**。

    codex 裁决三职责分离（版本号进 pinned 常量在浮动依赖政策下必然自相矛盾）：
    ① **code fingerprint**（本函数）= 代码/源 + 绑定身份 → commit/source 耦合（正确耦合）；
    ② **runtime provenance** = **静态的 oracle 复审基线版本** → 进 binding `config_ref` **披露**（非哈希
       输入·**非**运行时实测版本——它是「复审时点的基线」·故异环境下不得读作「当前环境」）；
    ③ **behavioral conformance** = 每个受支持环境**现场跑独立 oracle** 一致性对账（行为证据）。
    版本号只是粗粒度「重新审查触发器」·非代码身份·非行为证据。**CI 实证**（本 defect 真因）：本机
    sklearn 1.8.0/numpy 2.4.6 → `a0e2c805`；CI 实装 sklearn 1.9.0/numpy 2.5.1 → `9f08cc6b` → pinned 常量
    测试在任何非本机环境必红（requirements 无上界 `numpy>=1.26`/`scikit-learn>=1.5` = 移动目标）。
    **诚实边界**（codex）：去掉版本串**不**重开「改码未 repin」洞（whole-module 源+bridge+solver 身份仍抓），
    但**确实**移除「任何依赖 release 都强制人工复审」的粗粒度触发器；live oracle 更直接却**非其逻辑超集**
    （只核 3 fixture·impl 与 oracle 共用 numpy 语义可共模漂移·不核 location/fail-closed 语义）。
    """

    import sklearn.covariance

    bridge_intact = (
        __import__("app.portfolio.hrp_audit", fromlist=["ledoit_wolf"]).ledoit_wolf is _lw.ledoit_wolf
        and __import__("app.portfolio.hrp_audit", fromlist=["constant_shrinkage"]).constant_shrinkage
        is _lw.constant_shrinkage
    )
    # solver_binding_intact（codex floor2 #3）：模块级 `_lw.LedoitWolf` 必仍是 sklearn 真身——重绑到
    # OAS/别 estimator（源码不变的 monkeypatch）→ 身份变 → 指纹变 → staleness（whole-module 源 + 身份双查）。
    solver_binding_intact = _lw.LedoitWolf is sklearn.covariance.LedoitWolf
    return content_hash(
        {
            "fingerprint_schema": "lw-code-v2",  # 标记语义迁移（v1 含依赖版本=环境耦合·已裁掉）
            "solver_module": _solver_module_source(),  # 整模块源（含 import 行·抓源码级重绑）
            "public_api": _public_api_source(),
            "bridge_intact": bridge_intact,
            "solver_binding_intact": solver_binding_intact,  # 运行时身份（抓 monkeypatch 级重绑）
        }
    )


# ── binding + 一致性对账 + 全链裁定 ──────────────────────────────────────────────


def build_lw_binding(code_content_hash: str | None = None) -> TheoryImplementationBinding:
    return TheoryImplementationBinding(
        theory_ref=LW_ARTIFACT.artifact_id,
        code_ref="app/backend/app/portfolio/_lw_shrinkage.py:ledoit_wolf",
        code_content_hash=code_content_hash or lw_code_fingerprint(),
        # runtime provenance 披露（codex 裁 C+·**非**依赖钉死·**非**指纹输入）：oracle 复审基线版本。
        # 必称 "review baseline" 而非"当前运行环境"——否则 CI 在 1.9.0/2.5.1 下仍显示 1.8.0/2.4.6=新假陈述。
        config_ref=(
            "portfolio:impl=sklearn.LedoitWolf,target=muI,assume_centered=false,cov=mle,"
            "shrinkage=analytic_delta_star;oracle_review_baseline=sklearn==1.8.0|numpy==2.4.6;"
            "dependency_versions_in_code_fingerprint=false;supported_runtime_requires_live_oracle_pass=true"
        ),
        data_contract_ref="contract/returns_window_pit",
        implementation_spec="ledoit_wolf(returns) → LedoitWolfResult(covariance,shrinkage,location)",
        test_refs=("app/backend/tests/test_portfolio_lw_spine.py",),
        dimension_check="δ* 无量纲∈[0,1]；Σ* 为 return²",
        tolerance=1e-9,
    )


def lw_consistency_check(impl=_real_lw_shrink, *, binding=None):
    """真 LW impl vs 手写 LW-2004 oracle 数值对账（impl 参数仅测试注入 mutation 用）。"""

    binding = binding if binding is not None else build_lw_binding()
    return numerical_consistency_check(
        binding.binding_id,
        _lw_diagnostic(impl),
        _lw_oracle,
        _lw_fixtures(),
        tolerance=1e-9,
        affected_assets=("ledoit_wolf", "hrp_shrunk_cov", "portfolio_covariance"),
    )


def verify_lw_consistency(
    *,
    requested_label: str = PROOF_BACKED,
    impl=_real_lw_shrink,
    pinned_code_hash: str | None = None,
    current_code_hash: str | None = None,
) -> SpineDecision:
    binding = build_lw_binding(code_content_hash=pinned_code_hash or LW_PINNED_FINGERPRINT)
    check = lw_consistency_check(impl, binding=binding)
    code_hash = current_code_hash if current_code_hash is not None else lw_code_fingerprint()
    return evaluate_promotion(
        LW_ARTIFACT, binding, [check],
        requested_label=requested_label, current_code_hash=code_hash, data_contract=LW_DATA_CONTRACT,
    )
