"""R27 冷启动 MinTRL（最小业绩期长度）对抗测试。

设计/推导见 `dev/research/findings/dreaminate/mintrl-cold-start.md`。门必抓：
- MinTRL 是 PSR 的解析反解：n=MinTRL 时 PSR(SR*)≡confidence（命门交叉校验）。
- SR_pp≤SR* → +∞（never_significant，非"样本不足"）；n<3/N=1 → insufficient（绝不假装算出，R27）。
- 单调：confidence↑→MinTRL↑、edge(SR−SR*)↑→MinTRL↓。confidence∈(0.5,1) raise。
- 冷启动：n_observed<⌈MinTRL⌉ → sufficient=False（诚实证据不足）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import norm

from app.eval.dsr import _kurt_excess, _skew, minimum_track_record_length, probabilistic_sharpe_ratio


def test_mintrl_is_psr_inverse_cross_check():
    """**命门交叉校验**：n=MinTRL_real 时 z=(SR_pp−SR*)√(MinTRL−1)/√denom² ≡ Φ⁻¹(confidence)。

    MinTRL 是 PSR 的代数反解——公式转写错（denom 不一致 / √(n−1)↔n）则此恒等崩。
    """
    worst = 0.0
    for s in range(150):
        rng = np.random.default_rng(s)
        r = rng.standard_normal(int(rng.integers(60, 500))) * rng.uniform(0.005, 0.02) + rng.uniform(0.0005, 0.003)
        for conf in (0.9, 0.95, 0.99):
            m = minimum_track_record_length(r, 0.0, conf)
            if m.status != "ok":
                continue
            sr_pp = m.sr_per_period
            denom2 = max(1e-12, 1 - _skew(r) * sr_pp + (_kurt_excess(r) + 2) / 4 * sr_pp ** 2)
            z = sr_pp * math.sqrt(m.min_trl - 1) / math.sqrt(denom2)
            worst = max(worst, abs(z - norm.ppf(conf)))
    assert worst < 1e-9, f"MinTRL 非 PSR 反解 max|z−Φ⁻¹(p)|={worst:.2e}"


def test_mintrl_psr_inverse_holds_for_nonzero_benchmark():
    """**门必抓·补牙**：sr_benchmark≠0 时 n=MinTRL 仍须 PSR(SR*)≡confidence。

    种坏：把 MinTRL 里 `delta=sr_pp−sr_benchmark` 改成 `delta=sr_pp`（dropped sr_benchmark）——
    sr_benchmark=0 时不可见，但 sr_benchmark≠0 时 MinTRL 用错 Δ → 此交叉校验立崩。原测试全用 0 基准故漏网。
    """
    worst = 0.0
    cnt = 0
    for s in range(120):
        rng = np.random.default_rng(7000 + s)
        r = rng.standard_normal(int(rng.integers(80, 400))) * 0.01 + rng.uniform(0.001, 0.004)
        for bench in (0.02, 0.04, -0.02):     # **非零基准**（含正/负），覆盖 sr_pp−SR* 真差
            for conf in (0.9, 0.95):
                m = minimum_track_record_length(r, sr_benchmark=bench, confidence=conf)
                if m.status != "ok":
                    continue
                sr_pp = m.sr_per_period
                denom2 = max(1e-12, 1 - _skew(r) * sr_pp + (_kurt_excess(r) + 2) / 4 * sr_pp ** 2)
                # 正确 Δ=sr_pp−bench；n=MinTRL 时 z 须 = Φ⁻¹(conf)
                z = (sr_pp - bench) * math.sqrt(m.min_trl - 1) / math.sqrt(denom2)
                worst = max(worst, abs(z - norm.ppf(conf)))
                cnt += 1
    assert cnt > 30, f"非零基准 ok 样本太少 {cnt}（构造问题）"
    assert worst < 1e-9, f"sr_benchmark≠0 时 MinTRL≠PSR 反解 max|Δz|={worst:.2e}（疑 dropped sr_benchmark）"


def test_mintrl_monotone_in_confidence():
    r = np.random.default_rng(0).standard_normal(400) * 0.01 + 0.0012
    ms = [minimum_track_record_length(r, 0.0, c).min_trl for c in (0.85, 0.9, 0.95, 0.99)]
    for i in range(len(ms) - 1):
        assert ms[i] < ms[i + 1], f"confidence↑ MinTRL 未升 {ms}"


def test_mintrl_decreases_with_edge():
    """edge(SR_pp−SR*)↑ → MinTRL↓（更强 edge 更快达显著）。"""
    lo = np.random.default_rng(1).standard_normal(400) * 0.01 + 0.0008
    hi = np.random.default_rng(1).standard_normal(400) * 0.01 + 0.003
    assert minimum_track_record_length(hi, 0.0, 0.95).min_trl < minimum_track_record_length(lo, 0.0, 0.95).min_trl


def test_mintrl_never_significant_when_sr_below_benchmark():
    """SR_pp≤SR* → +∞（never_significant）：不超基准，任何样本都不显著（非'样本不足'）。"""
    r = np.random.default_rng(2).standard_normal(400) * 0.01 - 0.002   # 负均值
    m = minimum_track_record_length(r, 0.0, 0.95)
    assert m.status == "never_significant" and math.isinf(m.min_trl) and not m.sufficient


def test_mintrl_insufficient_short_sample_r27():
    """n<3 / N=1 → insufficient（估不出矩，绝不假装算出；R27 N=1 冷启动诚实）。"""
    assert minimum_track_record_length(np.array([0.01, 0.02]), 0.0, 0.95).status == "insufficient"
    assert minimum_track_record_length(np.array([0.01]), 0.0, 0.95).status == "insufficient"   # N=1
    assert math.isnan(minimum_track_record_length(np.array([0.01]), 0.0, 0.95).min_trl)


def test_mintrl_confidence_range_validated():
    r = np.random.default_rng(3).standard_normal(100) * 0.01 + 0.001
    for bad in (0.5, 0.3, 0.0, 1.0, 1.2):
        with pytest.raises(ValueError, match="confidence"):
            minimum_track_record_length(r, 0.0, bad)


def test_mintrl_one_sided_quantile():
    """Z_p 用单侧 Φ⁻¹(confidence)（非双侧）：MinTRL 应随 Φ⁻¹(conf)² 缩放。"""
    r = np.random.default_rng(4).standard_normal(400) * 0.01 + 0.0015
    m = minimum_track_record_length(r, 0.0, 0.95)
    # (MinTRL−1) ∝ Z_p²；用单侧 Z_0.95≈1.645 反推 denom²·(Z/Δ)²
    sr_pp = m.sr_per_period
    denom2 = max(1e-12, 1 - _skew(r) * sr_pp + (_kurt_excess(r) + 2) / 4 * sr_pp ** 2)
    expect = 1 + denom2 * (norm.ppf(0.95) / sr_pp) ** 2
    assert abs(m.min_trl - expect) < 1e-9


def _series_with_sr(n: int, sr_pp: float, seed: int = 0):
    """构造长度 n、**精确**每期 Sharpe = sr_pp 的近正态序列（标准化后缩放，去 seed 依赖）。"""
    z = np.random.default_rng(seed).standard_normal(n)
    z = (z - z.mean()) / z.std(ddof=1)        # 精确 mean 0 / std 1
    return z * 0.01 + sr_pp * 0.01            # mean/std(ddof=1) == sr_pp


def test_mintrl_cold_start_sufficiency_verdict_has_teeth():
    """**门必抓（评审补牙）**：ok+短业绩期 → sufficient=False（诚实证据不足）；ok+够长 → True。

    原测试 seed 下落 never_significant、核心断言被 `if status==ok` 跳过 → 把 `>=` 翻 `<=` 也漏网。
    改**确定性构造** sr_pp>0（必 status=ok）+ **无条件** assert，钉死 ok+short/ok+long 两路 sufficient 语义。
    """
    # ok + 短：sr_pp=0.05（小正 edge）→ MinTRL≈1083 ≫ n=40 → 证据不足
    m_short = minimum_track_record_length(_series_with_sr(40, 0.05), 0.0, 0.95)
    assert m_short.status == "ok"                          # 确定性（sr_pp>0）
    assert m_short.min_trl_obs > m_short.n_observed        # MinTRL 远超已观测
    assert m_short.sufficient is False                     # **无条件**：短 → 证据不足（翻 >=↔<= 即抓）
    # ok + 够长：sr_pp=0.3（强 edge）→ MinTRL≈31，n=300 ≫ → 达标
    m_long = minimum_track_record_length(_series_with_sr(300, 0.3), 0.0, 0.95)
    assert m_long.status == "ok"
    assert m_long.n_observed >= m_long.min_trl_obs
    assert m_long.sufficient is True                       # **无条件**：够长 → 达标（对称钉死 True 分支）
    assert "sufficient" in m_long.to_dict()


def test_mintrl_at_ceil_psr_meets_confidence():
    """⌈MinTRL⌉ 处 PSR≥confidence（取整后达标）——**纯矩确定性**断言（评审：去单种子重采样噪声）。

    用原序列的 sr_pp/γ3/γ4 直接算 n=⌈MinTRL⌉ 处的 z=sr_pp·√(⌈MinTRL⌉−1)/√denom²，断言 Φ(z)≥conf
    （⌈⌉≥real ⇒ z≥Z_p ⇒ PSR≥conf，精确、零噪声、真钉死取整方向）。
    """
    conf = 0.95
    worst_below = 0.0
    cnt = 0
    for s in range(40):
        rng = np.random.default_rng(600 + s)
        base = rng.standard_normal(300) * 0.01 + rng.uniform(0.0015, 0.004)
        m = minimum_track_record_length(base, 0.0, conf)
        if m.status != "ok" or not math.isfinite(m.min_trl_obs):
            continue
        sr_pp = m.sr_per_period
        denom2 = max(1e-12, 1 - _skew(base) * sr_pp + (_kurt_excess(base) + 2) / 4 * sr_pp ** 2)
        z = sr_pp * math.sqrt(m.min_trl_obs - 1) / math.sqrt(denom2)   # ⌈MinTRL⌉ 处纯矩 z
        psr_at_ceil = float(norm.cdf(z))
        worst_below = min(worst_below, psr_at_ceil - conf)             # 应 ≥0
        cnt += 1
    assert cnt > 20 and worst_below >= -1e-9, f"⌈MinTRL⌉ 处 PSR<conf 缺口={worst_below:.2e}"
