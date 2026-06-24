"""方法学核心 · 理论不变量守门层（监管 agent 实现 ↔ 学术理论一致）。

**为什么要这一层（GOAL §4 方法学纵深 + 主旨「该有数学就要有数学、用公式证明理论能行、
监管 agent 实现与理论一致」）**：
`test_academic_audit.py` 是 *example/契约* 测试——固定 seed、特定数值、少数单调性点。它证明
「在这几个点上对」，但不证明「在整个输入空间上理论不变量恒成立」。本文件补上后者：把每个统计门
（DSR / PBO / N_eff）背后**论文公式直接蕴含的不变量**写成跨多 seed 的确定性 property 守门。
任何未来改动（人或 agent）若让实现偏离理论——破坏尺度不变性、单调性、等价坍缩、组合数——
本层立即变红。这是「监管实现与理论一致」的可机器校验持久化形态。

**口径**：
- 不依赖 hypothesis（近上线项目不新增依赖 + 强复现要求）→ 用**确定性随机 sweep**
  （固定 seed 范围循环），可复现、CI 稳定。
- 每个不变量 docstring 写明它编码的**定理/公式**与「为什么能抓 agent 漂移」。
- 按 RULES §2「门必须有牙」：关键不变量配 **sentinel** 测试——证明一个*故意错误*的变体
  会违反该不变量（即该 property 是真判别器，非恒真废测）。
- 所有断言前已用经验探针实测成立（§6 先验证再断言），非凭空假设。

文献锚：Bailey & López de Prado 2014《The Deflated Sharpe Ratio》、
López de Prado 2018《Advances in Financial Machine Learning》§11–12（PBO/CSCV）、R8/R19（honest-N/N_eff）。
"""

from __future__ import annotations

import inspect
import math
import statistics
from math import comb

import numpy as np
import pytest

from app.eval.dsr import _expected_max_sr, deflated_sharpe_ratio, probabilistic_sharpe_ratio
from app.eval.n_eff import NEFF_CONFIG_VERSION, n_eff_from_matrix
from app.eval.pbo import cscv_pbo
from app.eval.conformal import (
    AdaptiveConformalInference,
    SplitConformalCalibrator,
    cqr_interval,
    split_conformal_interval,
)
from app.models.cpcv import (
    assemble_cpcv_paths,
    build_path_matrix,
    cpcv_splits,
    n_cpcv_combinations,
    n_cpcv_paths,
)
from app.monitor.drift import (
    _page_hinkley_global_mean_variant,
    cusum_drift,
    page_hinkley_drift,
    psi_from_proportions,
    rolling_psr_drift,
)

# ===========================================================================
# DSR — Deflated Sharpe Ratio (Bailey & López de Prado 2014)
#   DSR = Φ(z),  z = (ŜR − E[max SR]) · √(T−1) / √(1 − γ3·SR + (γ4−1)/4·SR²)
# ===========================================================================


def test_dsr_is_a_probability_in_unit_interval():
    """DSR=Φ(z) 是标准正态 CDF ⇒ ∀输入恒 ∈[0,1]、永不 NaN。

    定理：DSR 定义为一个概率（在诚实 N 下 SR 超过期望极值的显著性）。任何让它越界
    [0,1] 或产生 NaN 的实现都背离定义。跨 300 个 (序列长度/波动/漂移/试验数) 组合扫。
    """
    for s in range(300):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(int(rng.integers(20, 400))) * rng.uniform(0.005, 0.02) + rng.uniform(-0.001, 0.002)
        d = deflated_sharpe_ratio(r, n_trials=int(rng.integers(1, 5000)))
        assert 0.0 <= d <= 1.0 and not math.isnan(d), f"seed={s} DSR={d} 越界/NaN"


def test_dsr_scale_invariant():
    """DSR(c·returns) == DSR(returns) ∀c>0。

    定理：Sharpe = μ/σ 与标准化矩 γ3=m3/m2^1.5、γ4=m4/m2² 都**尺度无关**（同乘 c
    分子分母同阶约掉）⇒ DSR 只依赖 returns 的*形状*、不依赖*单位*。这条能抓任何把
    **有量纲的绝对量**（如 returns.mean() 本身）混进 z 的漂移——那是一类隐蔽 bug。
    """
    worst = 0.0
    for s in range(200):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(252) * 0.01 + 0.0005
        base = deflated_sharpe_ratio(r, n_trials=100)
        for c in (0.5, 2.0, 10.0, 100.0):
            worst = max(worst, abs(deflated_sharpe_ratio(r * c, n_trials=100) - base))
    assert worst < 1e-9, f"DSR 非尺度不变 max|Δ|={worst:.2e}（疑有量纲量混入 z）"


def _scale_contaminated_dsr(returns: np.ndarray, n_trials: int) -> float:
    """故意错误变体：把有量纲的绝对均值混进结果——真实现绝不该这样。仅供 sentinel。"""
    return deflated_sharpe_ratio(returns, n_trials) + float(np.asarray(returns).mean()) * 1e4


def test_dsr_scale_invariance_has_teeth():
    """Sentinel（RULES §2 门有牙）：一个把绝对尺度量污染进去的错误 DSR **会**违反尺度不变性。

    证明 `test_dsr_scale_invariant` 是真判别器：若有人这样改坏实现，尺度不变性守门必抓。
    """
    rng = np.random.default_rng(0)
    r = rng.standard_normal(252) * 0.01 + 0.0005
    base = _scale_contaminated_dsr(r, 100)
    diffs = [abs(_scale_contaminated_dsr(r * c, 100) - base) for c in (2.0, 10.0)]
    assert max(diffs) > 1e-6, "污染变体竟仍尺度不变？则该 property 无判别力——守门有牙性失效"


def test_dsr_monotone_non_increasing_in_n_trials():
    """n_trials ↑ ⇒ DSR ↓（或持平）。

    定理：试验数越多，E[max SR]（偶然出现的最高 SR 期望）越大 ⇒ 同一 SR 的显著性越低。
    选择偏差通缩必须随 N 单调。跨 200 seed × 9 档 n_trials 网格逐对校验。
    """
    grid = [1, 2, 5, 10, 50, 100, 500, 1000, 5000]
    for s in range(200):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(252) * 0.01 + rng.uniform(0.0, 0.0015)
        ds = [deflated_sharpe_ratio(r, n_trials=nt) for nt in grid]
        for i in range(len(ds) - 1):
            assert ds[i] >= ds[i + 1] - 1e-12, f"seed={s} n={grid[i]}→{grid[i+1]} DSR 反升 {ds[i]}→{ds[i+1]}"


def test_dsr_monotone_non_decreasing_in_sharpe():
    """SR ↑ ⇒ DSR ↑（或持平），用「加常数漂移」抬升 SR 而不动高阶矩。

    定理：returns 加常数 δ → 均值 +δ、std/偏度/峰度不变（中心矩平移不变）⇒ SR=μ/σ 单调升
    ⇒ 同 N 下 DSR 不降。这条钉死「更高夏普在诚实 N 下不该更不显著」。跨 200 seed × 6 档漂移。
    """
    for s in range(200):
        rng = np.random.default_rng(s)
        noise = rng.standard_normal(252) * 0.01
        ds = [deflated_sharpe_ratio(noise + drift, n_trials=100)
              for drift in (0.0, 0.0002, 0.0005, 0.001, 0.002, 0.004)]
        for i in range(len(ds) - 1):
            assert ds[i] <= ds[i + 1] + 1e-12, f"seed={s} 漂移升 SR 但 DSR 反降 {ds[i]}→{ds[i+1]}"


def test_dsr_false_strategy_theorem_path_in_unit_interval():
    """给定横截面方差 V（var_sr_hat，False Strategy Theorem 路径）DSR 仍恒 ∈[0,1]。

    定理：FST 路径下 E[max SR]=√V·[(1−γ)Φ⁻¹(1−1/N)+γΦ⁻¹(1−1/(Ne))] 是「每期 SR 单位」，
    与 (SR−E[max]) 再 studentize 后量纲一致 ⇒ Φ(z) 仍是合法概率。守住量纲一致性修复不被回退。
    """
    for s in range(150):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(252) * 0.01 + 0.0005
        d = deflated_sharpe_ratio(r, n_trials=int(rng.integers(2, 2000)), var_sr_hat=float(rng.uniform(0.0, 2.0)))
        assert 0.0 <= d <= 1.0, f"seed={s} FST 路径 DSR={d} 越界"


def test_dsr_degenerate_inputs_return_zero():
    """退化输入安全归零、不 crash：常量序列（σ=0）/ 样本 <3。"""
    assert deflated_sharpe_ratio(np.ones(252) * 0.001, n_trials=10) == 0.0
    assert deflated_sharpe_ratio(np.array([0.01, -0.005]), n_trials=10) == 0.0


# ===========================================================================
# PBO — Probability of Backtest Overfitting via CSCV (López de Prado 2018 §11)
# ===========================================================================


def test_pbo_in_unit_interval_or_nan():
    """PBO ∈[0,1]（合法概率）∪{NaN}（退化拒算）。跨 120 个随机 (T,N) 矩阵扫。"""
    for s in range(120):
        rng = np.random.default_rng(s)
        rm = rng.standard_normal((int(rng.integers(40, 200)), int(rng.integers(2, 25)))) * 0.01
        pbo = cscv_pbo(rm, s_blocks=8).pbo
        assert math.isnan(pbo) or 0.0 <= pbo <= 1.0, f"seed={s} PBO={pbo} 越界"


def test_pbo_invariant_to_strategy_column_permutation():
    """重排策略列 ⇒ PBO 不变。

    定理：PBO 衡量的是「IS-argmax 选择*程序*」的可靠性，与策略的*标号顺序*无关
    （argmax/排名都是顺序无关的集合运算）。这条钉死「换个顺序喂同一批策略，过拟合概率
    不该变」——一类索引/对齐 bug 的探针。enumerate_all=True 保证确定性可比。
    """
    worst = 0.0
    for s in range(120):
        rng = np.random.default_rng(s)
        rm = rng.standard_normal((96, 12)) * 0.01
        base = cscv_pbo(rm, s_blocks=8, enumerate_all=True).pbo
        if math.isnan(base):
            continue
        perm = rng.permutation(rm.shape[1])
        worst = max(worst, abs(base - cscv_pbo(rm[:, perm], s_blocks=8, enumerate_all=True).pbo))
    assert worst < 1e-9, f"PBO 受列顺序影响 max|Δ|={worst:.2e}"


def test_pbo_full_enumeration_yields_exact_binomial_combinations():
    """enumerate_all=True ⇒ 组合数精确 = C(S, S/2)（CSCV 对称分割的完整枚举）。

    定理：CSCV 从 S 段选 S/2 训练，完整组合空间大小 = C(S,S/2)。S∈{4,6,8,10,12}→{6,20,70,252,924}。
    钉死采样模式绝不冒充全枚举（enumerated_full 诚实标记）。
    """
    for S in (4, 6, 8, 10, 12):
        rng = np.random.default_rng(S)
        rm = rng.standard_normal((S * 6, 12)) * 0.01
        r = cscv_pbo(rm, s_blocks=S, enumerate_all=True)
        assert r.n_combinations == comb(S, S // 2) == r.expected_combinations_full
        assert r.enumerated_full is True


def test_pbo_flags_pure_noise_selection_as_overfit_across_seeds():
    """纯随机 returns + argmax 选择程序 ⇒ PBO 统计上偏高（多 seed 均值 > 0.5）。

    定理（López de Prado 2018 §11）：对纯噪声，IS-argmax 选出的「最佳」策略 OOS 期望落在
    中位以下 ⇒ PBO→高。这是 PBO 有判别力的正向证据；用多 seed 均值而非单点，避免偶然。
    """
    pbos = []
    for s in range(40):
        rng = np.random.default_rng(1000 + s)
        rm = rng.standard_normal((160, 20)) * 0.01
        r = cscv_pbo(rm, s_blocks=8, enumerate_all=True)
        if not math.isnan(r.pbo):
            pbos.append(r.pbo)
    assert statistics.mean(pbos) > 0.5, f"纯噪声 argmax 程序 PBO 均值应>0.5，得 {statistics.mean(pbos):.3f}"


def test_pbo_is_not_a_vacuous_constant():
    """Sentinel（门有牙）：PBO 在不同数据上取≥2 个不同值——证明置换不变性非「恒等废测」。

    若 PBO 对一切输入恒为同一常数，则 test_pbo_invariant_to_strategy_column_permutation
    会平凡通过却毫无判别力。此测确认该指标真随数据变化。
    """
    vals = set()
    for s in range(30):
        rng = np.random.default_rng(2000 + s)
        rm = rng.standard_normal((96, 12)) * 0.01
        pbo = cscv_pbo(rm, s_blocks=8, enumerate_all=True).pbo
        if not math.isnan(pbo):
            vals.add(round(pbo, 6))
    assert len(vals) >= 2, "PBO 在多样数据上竟恒为常数——置换不变性守门将失判别力"


# ===========================================================================
# N_eff — 有效独立试验数（honest-N 抗等价写法稀释，R8/R19）
# ===========================================================================


def test_neff_interval_bounds_invariant():
    """1 ≤ low ≤ point ≤ high ≤ N_observed 恒成立。

    定理：N_eff 是把名义 N 条试验按收益相关聚类后的*簇数*，必 ≥1（至少一簇）且 ≤N（最多人人独立）；
    敏感性区间 [low,high] 必夹住点估计。这条钉死区间口径不被改坏。跨 200 个随机 (T,N)。
    """
    for s in range(200):
        rng = np.random.default_rng(s)
        N = int(rng.integers(2, 30))
        rm = rng.standard_normal((int(rng.integers(30, 300)), N)) * 0.01
        res = n_eff_from_matrix(rm)
        assert 1 <= res.low <= res.point <= res.high <= N, \
            f"seed={s} 越界 low={res.low} point={res.point} high={res.high} N={N}"


def test_neff_equivalent_formulas_collapse_to_one():
    """N 条**完全相同**的收益列（如 a*2 与 a+a 这类等价写法）⇒ N_eff 点估计 = 1。

    这是 N_eff 的**核心主张**（R8/R19）：honest-N 名义计数会被等价写法撑大，N_eff 必须把
    收益序列几乎相同的试验聚回**一簇**，给 DSR 一个不被等价写法稀释的有效 N。跨 100 seed。
    """
    for s in range(100):
        rng = np.random.default_rng(s)
        col = rng.standard_normal((150, 1)) * 0.01
        res = n_eff_from_matrix(np.repeat(col, 8, axis=1))
        assert res.point == 1, f"seed={s} 8 条等价列未坍缩成 1 簇，point={res.point}"


def test_neff_near_equivalent_collapse():
    """近似等价列（同序列 + 1e-9 噪声）⇒ N_eff ≤ 2。浮点级别的等价写法也不该撑大有效 N。"""
    for s in range(100):
        rng = np.random.default_rng(s)
        col = rng.standard_normal((200, 1)) * 0.01
        rm = np.repeat(col, 6, axis=1) + rng.standard_normal((200, 6)) * 1e-9
        assert n_eff_from_matrix(rm).point <= 2, f"seed={s} 近似等价列未坍缩"


def test_neff_independent_trials_are_not_deflated():
    """相互独立的收益列 ⇒ N_eff 点估计 ≈ N（不被错误压缩）。

    定理：N_eff 只该把*相关*试验聚簇；对真独立试验不应通缩，否则会把诚实的多重检验风险藏掉。
    与 collapse 测试对称——证明 N_eff 既不放水也不冤杀。多 seed 均值 point/N > 0.85。
    """
    ratios = []
    for s in range(80):
        rng = np.random.default_rng(s)
        rm = rng.standard_normal((400, 10)) * 0.01
        ratios.append(n_eff_from_matrix(rm).point / 10)
    assert statistics.mean(ratios) > 0.85, f"独立列被错误通缩，mean point/N={statistics.mean(ratios):.3f}"


def test_neff_collapse_has_teeth():
    """Sentinel（门有牙）：等价坍缩=1 的同时，独立列必 >1——证明「==1」非平凡恒真。

    若 n_eff 对一切输入都返 1，collapse 测试会平凡通过却无意义。本测在同一 sweep 内确认
    独立列点估计 >1，从而 collapse 的「恰好=1」携带真信息（确实是相关性把它们聚成一簇）。
    """
    rng = np.random.default_rng(7)
    dup = n_eff_from_matrix(np.repeat(rng.standard_normal((150, 1)) * 0.01, 8, axis=1)).point
    indep = n_eff_from_matrix(rng.standard_normal((400, 8)) * 0.01).point
    assert dup == 1 and indep > 1, f"判别力失效 dup={dup} indep={indep}（坍缩与独立应可区分）"


def test_neff_invariant_to_column_permutation():
    """重排试验列 ⇒ (point, low, high) 完全不变。聚类是集合运算、与列顺序无关。"""
    for s in range(120):
        rng = np.random.default_rng(s)
        N = 12
        rm = rng.standard_normal((200, N)) * 0.01
        base = n_eff_from_matrix(rm)
        pq = n_eff_from_matrix(rm[:, rng.permutation(N)])
        assert (base.point, base.low, base.high) == (pq.point, pq.low, pq.high), f"seed={s} N_eff 受列序影响"


def test_neff_caliber_is_locked_against_caller_gaming():
    """口径锁定（防放水，对应 RULES.project「honest-N 不可手动改小」的数学层）。

    定理/红线：N_eff 的相关阈值/区间宽度/linkage 不得由调用方逐次传参覆盖（否则可低报阈值
    把有效 N 撑大 = 放水）。守门：① 公开 API 只收 returns_matrix，无 threshold/corr 等可调旋钮；
    ② NEFF_CONFIG_VERSION 是固定常量（改口径=升版本、留痕，不是请求参数）。
    """
    params = set(inspect.signature(n_eff_from_matrix).parameters) - {"returns_matrix"}
    assert not params, f"n_eff_from_matrix 暴露了可被放水的调参口：{params}"
    assert isinstance(NEFF_CONFIG_VERSION, str) and NEFF_CONFIG_VERSION, "口径版本必须钉死为固定常量"


# ===========================================================================
# §5 漂移检测器 — rolling-PSR / CUSUM / Page-Hinkley / PSI（生产期监控）
#   设计/推导：dev/research/findings/dreaminate/drift-detectors.md
#   论文公式直接蕴含的理论不变量；任何让实现偏离理论的改动（人或 agent）→ 本层立即变红。
# ===========================================================================


def test_psr_is_a_probability_in_unit_interval():
    """PSR=Φ(z) ⇒ ∀输入恒 ∈[0,1]、永不 NaN。跨 300 组 (序列长度/波动/漂移/基准)。

    定理：PSR 是「真 SR 超过基准 SR* 的概率」。任何让它越界或 NaN 的实现（如 denom 不钳制
    导致 sqrt(负)）都背离定义——R14 的 A股截断分布病态高阶矩尤其会撞上。
    """
    for s in range(300):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(int(rng.integers(20, 400))) * rng.uniform(0.005, 0.02) + rng.uniform(-0.002, 0.003)
        p = probabilistic_sharpe_ratio(r, sr_benchmark=float(rng.uniform(-0.2, 0.2)))
        assert 0.0 <= p <= 1.0 and not math.isnan(p), f"seed={s} PSR={p} 越界/NaN"


def test_psr_equals_half_when_sharpe_equals_benchmark():
    """ŜR=SR* ⇒ z=0 ⇒ PSR=Φ(0)=0.5 恒成立。钉死分子 (ŜR−SR*) 的零点。"""
    for s in range(150):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(252) * 0.01 + 0.0005
        sr_pp = r.mean() / r.std(ddof=1)
        assert abs(probabilistic_sharpe_ratio(r, sr_benchmark=sr_pp) - 0.5) < 1e-9, f"seed={s} 自基准≠0.5"


def test_psr_strictly_monotone_decreasing_in_benchmark():
    """SR* ↑ ⇒ PSR ↓（或持平，饱和区）。

    定理：固定 returns ⇒ denom、ŜR 不变；z=(ŜR−SR*)√(n−1)/denom 关于 SR* 严格递减 ⇒ Φ(z) 单调降。
    这条钉死「基准越高、超越概率越低」——抓基准符号搞反一类 bug。跨 200 seed × 7 档基准。
    """
    grid = [-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15]
    for s in range(200):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(252) * 0.01 + rng.uniform(0.0, 0.0015)
        ps = [probabilistic_sharpe_ratio(r, sr_benchmark=b) for b in grid]
        for i in range(len(ps) - 1):
            assert ps[i] >= ps[i + 1] - 1e-12, f"seed={s} 基准升 PSR 反升 {ps[i]}→{ps[i+1]}"


def test_psr_benchmark_monotonicity_has_teeth():
    """Sentinel（门有牙）：一个把基准符号搞反的 PSR **会**违反「关于基准递减」。

    `_flipped(r,b)=PSR(r,−b)` 关于 b 递增——证明 test_psr_strictly_monotone_decreasing_in_benchmark
    是真判别器（若实现把 −SR* 写成 +SR*，单调方向反转、守门必抓）。
    """
    rng = np.random.default_rng(0)
    r = rng.standard_normal(252) * 0.01 + 0.001
    flipped = [probabilistic_sharpe_ratio(r, sr_benchmark=-b) for b in (0.0, 0.05, 0.10, 0.15)]
    assert flipped[-1] > flipped[0] + 1e-6, "符号翻转变体竟仍递减？则该 property 无判别力"


def test_psr_equals_dsr_on_v_path_to_1e_minus_12():
    """**强交叉校验**：deflated_sharpe_ratio(r,N,var_sr_hat=V) ≡ PSR(r, _expected_max_sr(N,V))。

    两条独立代码路径（DSR 的 V-path z 式 ↔ 纯 PSR）必须逐位吻合到 1e-12。这是「监管实现↔理论
    一致」最硬的锚：任何让 PSR 偏离（量纲误年化、denom 改坏、高阶矩口径漂）的改动都会在此变红。
    仅 V-path（V=None 是历史量纲兼容路径，不在此断言）。排除退化样本（DSR 对 sr=0 早退 0.0）。
    """
    worst = 0.0
    for s in range(200):
        rng = np.random.default_rng(s)
        n = int(rng.integers(30, 400))
        r = rng.standard_normal(n) * rng.uniform(0.005, 0.02) + rng.uniform(0.0003, 0.002)  # 非零 edge
        for V in (0.5, 1.0, 2.0):
            for N in (1, 10, 100, 2000):
                dsr = deflated_sharpe_ratio(r, N, var_sr_hat=V)
                psr = probabilistic_sharpe_ratio(r, sr_benchmark=_expected_max_sr(N, V))
                worst = max(worst, abs(dsr - psr))
    assert worst < 1e-12, f"PSR↔DSR(V-path) 不吻合 max|Δ|={worst:.2e}（实现↔理论漂移）"


def test_psr_dsr_cross_check_has_interior_discriminative_power():
    """加固（评审 L1）：用**现实小 V**（0.002–0.01）让 N>1 的 deflation 拼接落在 PSR∈(0.05,0.95) 中段，
    而非仅靠 N=1 或饱和到 0 的两端——确保交叉校验在非饱和区也逐位锚住（否则内部 bug 漏网）。
    """
    worst = 0.0
    interior = 0
    for s in range(100):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(252) * 0.01 + rng.uniform(0.0005, 0.0025)
        for V in (0.002, 0.005, 0.01):
            for N in (2, 5, 20, 100):
                d = deflated_sharpe_ratio(r, N, var_sr_hat=V)
                p = probabilistic_sharpe_ratio(r, sr_benchmark=_expected_max_sr(N, V))
                worst = max(worst, abs(d - p))
                if 0.05 < p < 0.95:
                    interior += 1
    assert worst < 1e-12, f"PSR↔DSR 内部区不吻合 max|Δ|={worst:.2e}"
    assert interior > 100, f"交叉校验落中段的样本过少 {interior}（判别力仍集中在饱和端）"


def test_dsr_degenerates_to_psr_at_n1_per_r27():
    """R27 代码级证据：N=1（无多重检验）⇒ E[max SR]=0 ⇒ DSR(V) ≡ PSR(SR*=0) ≡ 普通 PSR vs 零。

    钉死「N=1 时 DSR 退化为 PSR」——冷启动单策略不该有通缩、就是 PSR。
    """
    for s in range(120):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(252) * 0.01 + 0.0008
        assert abs(deflated_sharpe_ratio(r, 1, var_sr_hat=1.0) - probabilistic_sharpe_ratio(r, 0.0)) < 1e-12


def test_cusum_statistics_are_nonnegative():
    """S⁺,S⁻ = max(0,·) ⇒ 峰值恒 ≥0。去掉反射壁的实现会变负、被抓。跨 200 随机序列。"""
    for s in range(200):
        rng = np.random.default_rng(s)
        sig = cusum_drift(rng.standard_normal(int(rng.integers(10, 200))) * 0.01,
                          baseline_mean=0.0, baseline_std=0.01)
        if sig.status == "insufficient_evidence":
            continue
        assert sig.detail["peak_s_neg"] >= 0.0 and sig.detail["peak_s_pos"] >= 0.0, f"seed={s} CUSUM 峰值<0"


def test_cusum_translation_invariant():
    """x+c, μ0+c ⇒ z=(x−μ0)/σ0 不变 ⇒ CUSUM 统计量逐位不变。抓把绝对量混进标准化的 bug。"""
    worst = 0.0
    for s in range(120):
        rng = np.random.default_rng(s)
        x = rng.standard_normal(80) * 0.01 + 0.001
        base = cusum_drift(x, baseline_mean=0.001, baseline_std=0.01).statistic
        for c in (0.5, -0.3, 10.0):
            shifted = cusum_drift(x + c, baseline_mean=0.001 + c, baseline_std=0.01).statistic
            worst = max(worst, abs(base - shifted))
    assert worst < 1e-9, f"CUSUM 非平移不变 max|Δ|={worst:.2e}"


def test_cusum_scale_equivariant():
    """x,μ0,σ0 同乘 c>0 ⇒ z 不变 ⇒ 标准化 CUSUM 统计量不变（告警时点不变）。抓单位不一致。"""
    worst = 0.0
    for s in range(120):
        rng = np.random.default_rng(s)
        x = rng.standard_normal(80) * 0.01 + 0.001
        base = cusum_drift(x, baseline_mean=0.001, baseline_std=0.01).statistic
        for c in (2.0, 100.0):
            scaled = cusum_drift(x * c, baseline_mean=0.001 * c, baseline_std=0.01 * c).statistic
            worst = max(worst, abs(base - scaled))
    assert worst < 1e-9, f"CUSUM 非尺度等变 max|Δ|={worst:.2e}（疑单位不一致）"


def test_cusum_direction_step_down_lights_lower_arm():
    """下偏 step ⇒ S⁻ 峰 > S⁺ 峰（双侧分离 + 方向正确）。抓 S⁺/S⁻ 搞反。跨 60 seed 多数成立。"""
    wins = 0
    for s in range(60):
        rng = np.random.default_rng(s)
        step = np.concatenate([rng.standard_normal(30) * 0.01 + 0.001,
                               rng.standard_normal(40) * 0.01 + 0.001 - 0.02])
        sig = cusum_drift(step, baseline_mean=0.001, baseline_std=0.01)
        if sig.detail["peak_s_neg"] > sig.detail["peak_s_pos"]:
            wins += 1
    assert wins >= 57, f"下偏 step 点燃 S⁻ 的占比过低 {wins}/60（方向疑反）"


def test_page_hinkley_statistic_nonnegative():
    """PH_t = m_t − min(m) ≥ 0 恒成立（按 running-min 定义）。跨 200 随机序列。"""
    for s in range(200):
        rng = np.random.default_rng(s)
        sig = page_hinkley_drift(rng.standard_normal(int(rng.integers(10, 200))) * 0.01,
                                 baseline_mean=0.0, baseline_std=0.01)
        if sig.status != "insufficient_evidence":
            assert sig.statistic >= 0.0, f"seed={s} PH={sig.statistic}<0"


def test_page_hinkley_frozen_baseline_bounds_fpr_global_variant_does_not():
    """理论 + 门有牙：长程平稳输入下，**正确**的检测器 FPR 必须受控。

    弃用的教科书全局 running-mean PH：m_t 是带漂移随机游走、包络随 √t 无界 ⇒ FPR→1（实证假告警）；
    生产用的 frozen-baseline 变体：δ 作保护 slack ⇒ FPR≈0。这条同时证明①设计选择对②sentinel 有判别力。
    """
    mu0, sd0 = 0.001, 0.01
    rejected_fa = sum(
        _page_hinkley_global_mean_variant(np.random.default_rng(s).standard_normal(500), delta=0.0, threshold_lambda=8.0)
        for s in range(100)
    )
    chosen_fa = sum(
        page_hinkley_drift(np.random.default_rng(s).standard_normal(500) * sd0 + mu0,
                           baseline_mean=mu0, baseline_std=sd0).breach
        for s in range(100)
    )
    assert rejected_fa > 90, f"弃用变体 FPR 应≈1，实测 {rejected_fa}/100（sentinel 失判别力）"
    assert chosen_fa == 0, f"frozen-baseline 变体应 FPR≈0，实测 {chosen_fa}/100"


def test_psi_is_nonnegative():
    """PSI = Σ(aᵢ−eᵢ)ln(aᵢ/eᵢ) = Jeffreys 散度 ≥0（KL-type 凸性）。跨 2000 随机占比对。"""
    worst_min = 1.0
    for s in range(2000):
        rng = np.random.default_rng(s)
        e = rng.dirichlet(np.ones(int(rng.integers(2, 15))))
        a = rng.dirichlet(np.ones(len(e)))
        psi, _ = psi_from_proportions(e, a)
        worst_min = min(worst_min, psi)
    assert worst_min >= -1e-12, f"PSI 出现负值 {worst_min:.2e}（背离散度非负）"


def test_psi_is_symmetric():
    """PSI(a,e)=PSI(e,a)（Jeffreys 对称散度，区别于非对称 KL）。跨 500 占比对逐位校验。"""
    worst = 0.0
    for s in range(500):
        rng = np.random.default_rng(s)
        e = rng.dirichlet(np.ones(8))
        a = rng.dirichlet(np.ones(8))
        p1, _ = psi_from_proportions(e, a)
        p2, _ = psi_from_proportions(a, e)
        worst = max(worst, abs(p1 - p2))
    assert worst < 1e-12, f"PSI 非对称 max|Δ|={worst:.2e}（疑实现成非对称 KL）"


def test_psi_symmetry_has_teeth():
    """Sentinel（门有牙）：非对称 KL `Σ aᵢ ln(aᵢ/eᵢ)` **会**违反对称性。

    证明 test_psi_is_symmetric 是真判别器：若有人把 PSI 写成单向 KL，对称性守门必抓。
    """
    rng = np.random.default_rng(3)
    e = rng.dirichlet(np.ones(8))
    a = rng.dirichlet(np.ones(8))
    kl_ae = float(np.sum(a * np.log(a / e)))
    kl_ea = float(np.sum(e * np.log(e / a)))
    assert abs(kl_ae - kl_ea) > 1e-6, "KL 竟对称？则对称性 property 无判别力"


def test_psi_zero_iff_identical():
    """aᵢ≡eᵢ ⇒ PSI=0；不同分布 ⇒ PSI>0（唯一零点）。"""
    for s in range(100):
        rng = np.random.default_rng(s)
        e = rng.dirichlet(np.ones(10))
        assert psi_from_proportions(e, e)[0] == 0.0, f"seed={s} 恒等分布 PSI≠0"
        a = rng.dirichlet(np.ones(10) * 0.5)   # 不同
        if not np.allclose(e, a):
            assert psi_from_proportions(e, a)[0] > 0.0, f"seed={s} 不同分布 PSI 应>0"


def test_psi_permutation_invariant():
    """桶同步重排（actual+expected 同序）⇒ PSI 不变（求和与桶序无关）。跨 200 占比对。"""
    worst = 0.0
    for s in range(200):
        rng = np.random.default_rng(s)
        e = rng.dirichlet(np.ones(12))
        a = rng.dirichlet(np.ones(12))
        perm = rng.permutation(12)
        base, _ = psi_from_proportions(e, a)
        pq, _ = psi_from_proportions(e[perm], a[perm])
        worst = max(worst, abs(base - pq))
    assert worst < 1e-12, f"PSI 受桶序影响 max|Δ|={worst:.2e}"


def test_rolling_psr_detector_caliber_locked_against_dsr_deflation():
    """口径锁定（命门 · M-AUTHORITY=A1）：rolling-PSR 检测器**绝不**暴露 n_trials/var_sr_hat 旋钮。

    定理/红线：把 SR* 设成 E[max SR over N trials] 即变回 DSR（多重检验通缩、晋级期过拟合闸）。
    若检测器接受 n_trials，调用方就能在 live 退役里偷偷塞 DSR 通缩 = 范畴错误（GOAL §5「绝不把
    DSR 搬实盘单策略」）。守门：公开签名只收 returns + 固定 sr_benchmark，无任何 trial-count 口。
    """
    params = set(inspect.signature(rolling_psr_drift).parameters)
    for forbidden in ("n_trials", "var_sr_hat", "trials", "n_trial", "expected_max_sr"):
        assert forbidden not in params, f"rolling-PSR 暴露了把 DSR 通缩走私进 live 退役的口：{forbidden}"


# ===========================================================================
# R23 不确定性区间 — split conformal / CQR / ACI（分布无关覆盖保证）
#   设计/推导：dev/research/findings/dreaminate/conformal-intervals.md
#   覆盖定理是分布无关、有限样本结论 ⇒ 可直接 Monte-Carlo 证伪（覆盖率掉到 1−α 以下即实现跑偏）。
# ===========================================================================


def _split_coverage(dist: str, alpha: float, seeds: int = 60, n_cal: int = 200, n_test: int = 80) -> float:
    """对某分布跑 split-conformal 边际覆盖 Monte-Carlo（预测器=校准前段均值）。"""
    covs = []
    for s in range(seeds):
        rng = np.random.default_rng(10_000 + s)
        if dist == "normal":
            data = rng.standard_normal(n_cal + n_test + 50)
        elif dist == "heavy_t":
            data = rng.standard_t(3, n_cal + n_test + 50)
        elif dist == "skew":
            data = rng.exponential(1.0, n_cal + n_test + 50) - 1.0
        else:  # heteroscedastic-ish 混合
            data = rng.standard_normal(n_cal + n_test + 50) * rng.uniform(0.5, 2.0)
        mu = float(data[:50].mean())
        sc = SplitConformalCalibrator(data[50:50 + n_cal] - mu)
        test = data[50 + n_cal:50 + n_cal + n_test]
        covs.append(sum(sc.interval(mu, alpha).covers(y) for y in test) / n_test)
    return float(statistics.mean(covs))


def test_split_conformal_marginal_coverage_is_distribution_free():
    """边际覆盖 ≥1−α 在正态/重尾/偏态/异方差**同保**（分布无关，conformal 核心定理）。

    定理（Vovk; Lei et al. 2018）：可交换 ⇒ P(Y∈C)≥1−α，与底层分布无关。任何让覆盖掉到 1−α
    以下的实现（漏 +1 校正 / 用错分位 / abstain 当数值）都背离定理。MC tol 容多 seed 抽样噪声。
    """
    alpha = 0.1
    for dist in ("normal", "heavy_t", "skew", "hetero"):
        cov = _split_coverage(dist, alpha)
        assert cov >= 1 - alpha - 0.015, f"{dist} 覆盖 {cov:.3f} < 目标 {1 - alpha}（分布无关保证被破坏）"


def test_split_conformal_plus_one_correction_has_teeth():
    """Sentinel（门有牙）：去掉 +1 校正（用 ⌈n(1−α)⌉）在小 n **明显欠覆盖**。

    证明 +1 校正是真判别器：正确实现达标、错误实现欠覆盖、且差距清晰（非恒真废测）。
    """
    alpha, n_cal, trials = 0.1, 20, 4000

    def cov(use_plus_one: bool) -> float:
        hits = 0
        for s in range(trials):
            rng = np.random.default_rng(20_000 + s)
            d = rng.standard_normal(n_cal + 1)
            calib = np.sort(np.abs(d[:n_cal]))
            k = math.ceil((n_cal + 1) * (1 - alpha)) if use_plus_one else math.ceil(n_cal * (1 - alpha))
            q = np.inf if k > n_cal else calib[max(1, k) - 1]
            hits += abs(d[n_cal]) <= q
        return hits / trials

    correct, buggy = cov(True), cov(False)
    assert correct >= 1 - alpha - 0.015, f"正确实现覆盖 {correct:.3f} 不足"
    assert correct - buggy > 0.02, f"去 +1 校正未明显欠覆盖（correct={correct:.3f} buggy={buggy:.3f}）→ sentinel 无判别力"


def test_split_conformal_not_grossly_overcovering():
    """效率：覆盖 ≤ 1−α + 合理裕度（不靠把区间撑到无穷蒙混达标）。上界理论 ≈1−α+1/(n+1)。"""
    cov = _split_coverage("normal", 0.1, n_cal=200)
    assert cov <= 1 - 0.1 + 0.05, f"覆盖 {cov:.3f} 远超 1−α（疑区间无意义地宽/恒覆盖）"


def test_split_conformal_calibration_permutation_invariant():
    """校准集顺序无关（conformal 用的是序统计量、集合运算）。"""
    rng = np.random.default_rng(30_001)
    resid = rng.standard_normal(200)
    base = split_conformal_interval(resid, 0.5, 0.1)
    perm = split_conformal_interval(rng.permutation(resid), 0.5, 0.1)
    assert abs(base.width - perm.width) < 1e-12


def test_split_conformal_interval_nested_in_alpha():
    """α₁<α₂ ⇒ C_{α₁} ⊇ C_{α₂}（小 α 区间更宽，单调嵌套）。跨 100 seed。"""
    for s in range(100):
        rng = np.random.default_rng(40_000 + s)
        sc = SplitConformalCalibrator(rng.standard_normal(500))
        w = [sc.interval(0.0, a).width for a in (0.02, 0.05, 0.1, 0.2)]
        for i in range(len(w) - 1):
            assert w[i] >= w[i + 1] - 1e-9, f"seed={s} α 升区间反宽 {w[i]}→{w[i + 1]}"


def test_cqr_marginal_coverage_distribution_free():
    """CQR 边际覆盖 ≥1−α（异方差，给定分位预测）。同 split 保证、宽度自适应。"""
    covs = []
    for s in range(40):
        rng = np.random.default_rng(50_000 + s)
        x = rng.uniform(0, 5, 600)
        y = np.sin(x) + rng.standard_normal(600) * (0.1 + 0.3 * x)
        qlo, qhi = np.sin(x) - 1.64 * (0.1 + 0.3 * x), np.sin(x) + 1.64 * (0.1 + 0.3 * x)
        hit = [cqr_interval(qlo[:300], qhi[:300], y[:300], qlo[j], qhi[j], 0.1).covers(y[j]) for j in range(300, 600)]
        covs.append(float(np.mean(hit)))
    assert statistics.mean(covs) >= 0.9 - 0.02, f"CQR 覆盖 {statistics.mean(covs):.3f} 不足"


def test_aci_raw_recursion_identity():
    """ACI raw 递推恒等：α_{T+1} = α₁ + γ·Σ(α−errₜ)。方向/累加搞错必抓。"""
    rng = np.random.default_rng(60_001)
    aci = AdaptiveConformalInference(target_alpha=0.1, gamma=0.03)
    errs = []
    for _ in range(200):
        covered = bool(rng.random() > 0.15)
        errs.append(0 if covered else 1)
        aci.record(covered)
    expected = 0.1 + 0.03 * sum(0.1 - e for e in errs)
    assert abs(aci.alpha_t - expected) < 1e-9, f"ACI 递推不符 {aci.alpha_t} vs {expected}"


def test_aci_long_run_coverage_converges_under_drift():
    """ACI 长程覆盖在分布漂移下 →1−α（不需可交换）；这是 ACI 区别于 split 的核心定理性质。"""
    rng = np.random.default_rng(70_001)
    aci = AdaptiveConformalInference(target_alpha=0.1, gamma=0.05)
    window = list(np.abs(rng.standard_normal(100)))
    T = 2000
    cov = []
    for t in range(T):
        scale = 1.0 + 2.5 * t / T
        y = rng.standard_normal() * scale
        c = aci.interval(0.0, np.array(window[-100:])).covers(y)
        cov.append(c)
        aci.record(c)
        window.append(abs(y))
    mean_cov = float(np.mean(cov))
    assert abs(mean_cov - 0.9) < 0.03, f"ACI 漂移下长程覆盖 {mean_cov:.3f} 未收敛 0.9"


def test_conformal_alpha_not_hardcoded():
    """不锁 α（R23）：split/CQR/ACI 的 α 均为调用方传参，签名无内部硬编的固定显著性。"""
    assert "alpha" in inspect.signature(SplitConformalCalibrator.interval).parameters
    assert "alpha" in inspect.signature(cqr_interval).parameters
    assert "target_alpha" in inspect.signature(AdaptiveConformalInference.__init__).parameters


# ===========================================================================
# R4 CPCV — Combinatorial Purged Cross-Validation（组合学 + 防泄露不变量）
#   设计/推导：dev/research/findings/dreaminate/cpcv.md（φ 双计数证明 + golden path_matrix）
# ===========================================================================

import pandas as pd  # noqa: E402


def test_cpcv_path_count_identity():
    """φ = C(N−1,k−1) = k·C(N,k)/N（双计数恒等）∀ 1≤k<N；且 k·C(N,k) 必整除 N。

    定理：按组合计 (group,combo) 出现 = k·C(N,k)；按 group 计 = N·φ ⇒ φ=k·C(N,k)/N=C(N−1,k−1)。
    任何让组合/路径计数偏离的实现（静默采样、漏组合）都背离组合学。
    """
    for n in range(3, 13):
        for k in range(1, n):
            assert n_cpcv_combinations(n, k) == comb(n, k)
            assert n_cpcv_paths(n, k) == comb(n - 1, k - 1) == k * comb(n, k) // n
            assert (k * comb(n, k)) % n == 0


def test_cpcv_path_matrix_bijection():
    """path_matrix(N×φ)：每 group 恰出现 φ 次；所有 (combo,group)-test occurrence 被用恰一次（双射）。

    定理：每 group 在 test 出现 C(N−1,k−1)=φ 次 ⇒ path_matrix 每行长 φ；全体 occurrence 数 = N·φ
    = k·C(N,k) = 所有组合的 test-group 槽总数 ⇒ 一一对应、无重无漏。
    """
    for n in (4, 6, 8):
        for k in (1, 2, 3):
            if k >= n:
                continue
            mat = build_path_matrix(n, k)
            phi = n_cpcv_paths(n, k)
            assert mat.shape == (n, phi)
            # 每个 (combo_id, group) occurrence 恰用一次：统计 mat 里每组合被引用次数 == 该组合的 k
            from collections import Counter
            ref = Counter(int(c) for c in mat.flat)
            for ci in range(n_cpcv_combinations(n, k)):
                assert ref[ci] == k, f"组合 {ci} 被引用 {ref[ci]} ≠ k={k}（occurrence 双射破坏）"


def test_cpcv_each_path_covers_every_sample_exactly_once():
    """每条回测路径恰覆盖每个样本一次（无重无漏）+ 各 group 单元来源 == path_matrix[g,p]（防坍缩成 path0）。

    填**组合 id**而非全 1（评审：全 1 无法区分路径来源，φ 条坍缩成 path0 变体也能蒙混）。
    """
    n, k, nsamp = 6, 2, 120
    times = pd.Series(pd.date_range("2021-01-01", periods=nsamp, freq="D"))
    splits = cpcv_splits(times, n, k, embargo_pct=0.0)
    from itertools import combinations as _c
    per = [np.full(nsamp, np.nan) for _ in _c(range(n), k)]
    for s in splits:
        per[s.combination_index][s.test_idx] = float(s.combination_index)   # 标来源 combo
    mat = build_path_matrix(n, k)
    go = np.concatenate([np.full(len(p), g) for g, p in enumerate(np.array_split(np.arange(nsamp), n))])
    paths = assemble_cpcv_paths(per, nsamp, n, k)
    for p_idx, path in enumerate(paths):
        assert not np.any(np.isnan(path))                  # 无漏
        for g in range(n):
            assert np.all(path[go == g] == mat[g, p_idx])  # 来源精确 = path_matrix（无坍缩/错位）


def test_cpcv_purge_blocks_label_leakage_and_segmented_not_global():
    """purge 无标签泄露 + **逐 test group 段判**（非全局 min..max，否则误删非连续 test group 中间合法 train）。

    构造非连续 test groups（含首尾），短 t1 → 中间 group 的 train 样本标签不跨任何 test 区间 ⇒ 应**保留**；
    若用全局 [min(test)..max(test)] 大区间会把它误删。这条同时钉死「无泄露」与「逐段非全局」。
    """
    n, k, nsamp = 6, 2, 120
    times = pd.Series(pd.date_range("2021-01-01", periods=nsamp, freq="D"))
    t1 = pd.Series(times.values + np.timedelta64(2, "D"))   # 短标签跨度
    ta, t1a = np.asarray(times), np.asarray(t1)
    go = np.concatenate([np.full(len(p), g) for g, p in enumerate(np.array_split(np.arange(nsamp), n))])
    splits = cpcv_splits(times, n, k, embargo_pct=0.0, t1=t1)
    # 无泄露
    for s in splits:
        for g in s.test_groups:
            gs = np.where(go == g)[0]
            tt0, tt1 = ta[gs[0]], t1a[gs].max()
            assert not np.any((ta[s.train_idx] <= tt1) & (t1a[s.train_idx] >= tt0)), "purge 后仍泄露"
    # 逐段非全局：找含首尾两组(0, n-1)的组合，断言中间组的 train 样本被保留
    mid = splits[[s.test_groups for s in splits].index((0, n - 1))]
    mid_group_samples = np.where(go == n // 2)[0]
    assert np.any(np.isin(mid_group_samples, mid.train_idx)), "中间 group 合法 train 被误删（疑用全局区间 purge）"
