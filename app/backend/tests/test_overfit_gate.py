"""多证据三角 gate + N_eff + DSR(V) + block bootstrap 的【对抗式】测试（T-015）。

验收标准（RULES §2）：种一个已知坏，门必抓。对应 spine 05 §5 T1..T15 中属算法层的探针：
噪声→不绿 / 泄露→N_eff<<N / 真信号→绿 / 短样本→证据不足 / 三支不同向→不绿 / 换等价写法 N_eff 聚 1 /
打乱时间 block 比 iid 敏感 / DSR 独立重算对账 / 裁决措辞禁可信安全。
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import kurtosis, skew

from app.eval.bootstrap import bootstrap_sharpe_ci
from app.eval.dsr import deflated_sharpe_ratio, sharpe_ratio
from app.eval.n_eff import n_eff_from_matrix
from app.eval.overfit_gate import _decide, run_overfit_gate


def _noise_matrix(t=600, n=50, seed=0):
    return np.random.default_rng(seed).normal(size=(t, n)) * 0.01


def _alpha_returns(t=600, loc=0.0015, scale=0.01, seed=1):
    return np.random.default_rng(seed).normal(loc=loc, scale=scale, size=t)


# ── T-OG-1 噪声 → gate 不返 green（spine 05 T1）─────────────────────────────────
def test_noise_not_green():
    rng = np.random.default_rng(3)
    mat = rng.normal(size=(600, 50)) * 0.01
    target = mat[:, 0]
    neff = n_eff_from_matrix(mat)
    v = run_overfit_gate(target, n_eff=neff, returns_matrix=mat, asset_class="crypto")
    assert v.color != "green", f"纯噪声却放行 green（门坏）：{v.reason}"
    assert v.all_agree_positive is False


# ── T-OG-2 真信号（充足样本、少独立试验）→ 可 green（抓误杀，spine 05 T3）────────
def test_true_signal_can_pass_green():
    # 一列强 alpha + 9 列噪声（凑够 PBO 的 min_n_strategies=10），alpha 列做评估目标。
    rng = np.random.default_rng(7)
    cols = [rng.normal(loc=0.004, scale=0.01, size=600)]
    for k in range(9):
        cols.append(rng.normal(loc=0.0, scale=0.01, size=600))
    mat = np.column_stack(cols)
    target = mat[:, 0]
    neff = n_eff_from_matrix(mat)
    v = run_overfit_gate(target, n_eff=neff, returns_matrix=mat, asset_class="crypto")
    assert v.color == "green", f"真实强信号被误杀（门坏）：{v.reason}"
    assert v.all_agree_positive is True


# ── T-OG-3 短样本 → insufficient_evidence，不给红绿、不报误导单点（spine 05 T4）──
def test_short_sample_insufficient():
    r = _alpha_returns(t=300)          # a_share min_T=504
    neff = n_eff_from_matrix(r.reshape(-1, 1))
    v = run_overfit_gate(r, n_eff=neff, asset_class="a_share")
    assert v.color == "insufficient_evidence"
    assert "证据不足" in v.reason
    assert v.dsr_conservative != v.dsr_conservative  # NaN：不输出会被误读为"好夏普"的单点


# ── T-OG-4 泄露：30 高相关变体 → N_eff << N_observed（spine 05 T2/T11 核心）──────
def test_leak_neff_much_less_than_observed():
    base = _alpha_returns(t=600, seed=11)
    rng = np.random.default_rng(12)
    # 30 个 base 的近似复制（加极小噪声）→ 收益高度相关
    cols = [base + rng.normal(scale=1e-5, size=base.size) for _ in range(30)]
    mat = np.column_stack(cols)
    neff = n_eff_from_matrix(mat)
    assert neff.n_observed == 30
    assert neff.point <= 3, f"30 个高相关变体没聚拢，N_eff={neff.point}（换等价写法可稀释通缩，门坏）"


# ── T-OG-5 换等价写法 a*2 vs a+a（收益完全相同）→ N_eff 聚 1（spine 05 T11）──────
def test_equivalent_rewrites_collapse_to_one_cluster():
    a = _alpha_returns(t=600, seed=21)
    mat = np.column_stack([a * 2.0, a + a])   # 数值上完全相同的两列
    neff = n_eff_from_matrix(mat)
    assert neff.n_observed == 2 and neff.point == 1, \
        f"a*2 与 a+a 收益相同却没聚成 1 簇（N_eff={neff.point}，换写法撑大有效 N，门坏）"


# ── T-OG-6 独立试验 → N_eff ≈ N（抓"把独立的也聚没了"误判）────────────────────
def test_independent_trials_stay_separate():
    mat = _noise_matrix(t=600, n=20, seed=31)
    neff = n_eff_from_matrix(mat)
    assert neff.point >= 15, f"20 条独立噪声被过度聚类成 {neff.point} 簇（N_eff 被低报放水，门坏）"


# ── T-OG-7 三支不同向 → 必不 green（无单点承重，spine 05 T8）─────────────────────
def test_divergent_evidence_not_green():
    # 构造：DSR 保守端尚可但 Bootstrap CI 跨零（弱正漂移 + 高噪声）。
    rng = np.random.default_rng(41)
    target = rng.normal(loc=0.0006, scale=0.02, size=600)
    mat = np.column_stack([target] + [rng.normal(scale=0.02, size=600) for _ in range(11)])
    neff = n_eff_from_matrix(mat)
    v = run_overfit_gate(target, n_eff=neff, returns_matrix=mat, asset_class="crypto")
    assert v.color != "green", f"三支未同向却放行（门坏）：{v.reason}"
    if v.bootstrap_ci[0] <= 0:
        assert v.all_agree_positive is False


# ── T-OG-7b 无单点承重（直测裁决逻辑）：任一支异议都必须把 green 降级（spine 05 T8）────
def test_decide_no_single_point_of_failure():
    # 三支同向正 → green + all_agree
    assert _decide(0.6, 0.4, 0.1, 0.5) == ("green", True)
    # 仅 PBO 异议（0.6>0.5，其余正）→ 必降 yellow（pbo 能否决；catch all_agree=dsr_ok 类单点 bug）
    assert _decide(0.6, 0.6, 0.1, 0.5) == ("yellow", False)
    # 仅 CI 异议（lower≤0）→ 必降 yellow
    assert _decide(0.6, 0.4, 0.0, 0.5) == ("yellow", False)
    # 仅 DSR 异议（0.3<0.5 但≥0.2）→ 必降 yellow
    assert _decide(0.3, 0.4, 0.1, 0.5) == ("yellow", False)
    # 任一强负 → red
    assert _decide(0.1, 0.4, 0.1, 0.5)[0] == "red"      # DSR<0.2
    assert _decide(0.6, 0.4, -0.1, -0.05)[0] == "red"   # CI 上界≤0
    assert _decide(0.6, 0.8, 0.1, 0.5)[0] == "red"      # PBO>0.7
    # 缺 PBO → 至多 yellow，永不 green（即使 dsr+ci 都正）
    assert _decide(0.9, None, 0.5, 1.0) == ("yellow", False)


# ── T-OG-7c 噪声填充解锁 PBO 不能让【弱】策略变绿（honest_n DSR 兜底仍把关，复核 #3）──────
def test_noise_padding_cannot_green_weak_strategy():
    # 弱目标（loc 很小）+ 9 列噪声凑够 PBO 的 10 列 → PBO 可算了，但 DSR 在 honest_n=10 通缩下必不过。
    rng = np.random.default_rng(123)
    weak = rng.normal(loc=0.0003, scale=0.012, size=600)
    mat = np.column_stack([weak] + [rng.normal(scale=0.012, size=600) for _ in range(9)])
    neff = n_eff_from_matrix(mat)
    v = run_overfit_gate(weak, n_eff=neff, honest_n=mat.shape[1], returns_matrix=mat, asset_class="crypto")
    assert v.color != "green", f"噪声填充解锁 PBO 把弱策略放行 green（DSR 兜底没把关，门坏）：{v.reason}"


# ── T-OG-8 PBO 缺失（策略数不足）→ 至多 yellow，不 green（spine 05 §7-2）─────────
def test_pbo_insufficient_caps_at_yellow():
    target = _alpha_returns(t=600, loc=0.004, seed=51)
    neff = n_eff_from_matrix(target.reshape(-1, 1))
    # 无 returns_matrix → PBO 不可算
    v = run_overfit_gate(target, n_eff=neff, returns_matrix=None, asset_class="crypto")
    assert v.pbo is None
    assert v.color != "green", "缺 PBO（少一支证据）却放行 green（门坏）"


# ── T-OG-9 打乱时间 → block bootstrap 比 iid 对序列结构更敏感（spine 05 T5）──────
def test_block_bootstrap_more_sensitive_to_shuffle_than_iid():
    rng = np.random.default_rng(61)
    # 强自相关序列（AR(1)）
    eps = rng.normal(scale=0.01, size=800)
    ar = np.zeros(800)
    for i in range(1, 800):
        ar[i] = 0.6 * ar[i - 1] + eps[i]
    ar += 0.001
    shuffled = ar.copy()
    rng.shuffle(shuffled)
    blk = abs(bootstrap_sharpe_ci(ar, block_size=28, seed=1).lower
              - bootstrap_sharpe_ci(shuffled, block_size=28, seed=1).lower)
    iid = abs(bootstrap_sharpe_ci(ar, block_size=None, seed=1).lower
              - bootstrap_sharpe_ci(shuffled, block_size=None, seed=1).lower)
    assert blk > iid, "block bootstrap 对打乱时间不比 iid 敏感 → 没在用序列信息（门坏）"
    assert bootstrap_sharpe_ci(ar, block_size=28).method == "block"


# ── T-OG-10 DSR 独立重算对账（scipy 算 skew/kurt）→ 差异 < 1e-6（spine 05 T9）────
def test_dsr_independent_recompute_agrees():
    import math

    from scipy.stats import norm

    r = _alpha_returns(t=500, loc=0.001, seed=71)
    ours = deflated_sharpe_ratio(r, n_trials=20)
    # 独立参考实现（用 scipy.stats 的 skew/kurt + 旧极值近似口径）
    arr = np.asarray(r, float)
    sr_pp = arr.mean() / arr.std(ddof=1)
    g3 = float(skew(arr, bias=True))
    g4e = float(kurtosis(arr, fisher=True, bias=True))
    a = math.sqrt(2 * math.log(20))
    expected = a - 0.5772156649 / a
    denom = math.sqrt(max(1e-12, 1 - g3 * sr_pp + (g4e + 2) / 4.0 * sr_pp ** 2))
    # 新 studentized 口径（复核 #2，去掉 /√ppy 量纲 hack）：SR 的 t 统计量 − 标准正态极大值期望。
    z = sr_pp * math.sqrt(arr.size - 1) / denom - expected
    ref = float(norm.cdf(z))
    assert abs(ours - ref) < 1e-6, f"DSR 与独立重算不一致（指向 bug）：{ours} vs {ref}"


# ── T-OG-11 var_sr_hat 改变 DSR、向后兼容（None=旧行为）──────────────────────────
def test_var_sr_hat_changes_dsr_and_backward_compatible():
    r = _alpha_returns(t=500, loc=0.002, seed=81)
    base = deflated_sharpe_ratio(r, n_trials=20)                 # 旧路径
    base2 = deflated_sharpe_ratio(r, n_trials=20, var_sr_hat=None)
    assert base == base2, "var_sr_hat=None 不等于旧行为（向后兼容破，门坏）"
    withv = deflated_sharpe_ratio(r, n_trials=20, var_sr_hat=0.05)
    assert withv != base, "传入 V 后 DSR 没变（False Strategy Theorem 项没生效，门坏）"


# ── T-OG-12 裁决措辞：说「证据充分/不足」，禁「可信/安全/保证」（R7/R12，spine 05 T15）─
def test_verdict_wording_no_absolutes():
    target = _alpha_returns(t=600, loc=0.004, seed=91)
    mat = np.column_stack([target] + [np.random.default_rng(92).normal(scale=0.01, size=600) for _ in range(10)])
    neff = n_eff_from_matrix(mat)
    v = run_overfit_gate(target, n_eff=neff, returns_matrix=mat, asset_class="crypto")
    text = v.verdict_phrasing + v.reason + " ".join(v.model_risk_disclosure)
    assert "证据" in v.verdict_phrasing
    for banned in ("可信", "安全", "保证"):
        assert banned not in text, f"裁决出现绝对化措辞「{banned}」（门坏）"
    assert any("只与你诚实提交的 N 一样诚实" in d for d in v.model_risk_disclosure), \
        "缺 DSR 自身模型风险披露（R5，门坏）"


# ── T-OG-13 通缩区间【严格】非退化 + 保守端用更大 N（杀 low/high 互换，复核 #7/#8）──────
def test_deflation_interval_strict_and_conservative_uses_higher_n():
    # 构造跨 0.6–0.8 相关带的簇：8 列 = base + 0.6·noise（两两 corr≈0.74）→ low(0.6)合并、high(0.8)不合并
    rng = np.random.default_rng(101)
    base = rng.normal(loc=0.003, scale=0.01, size=600)
    cols = [base] + [base + 0.6 * rng.normal(scale=0.01, size=600) for _ in range(8)]
    mat = np.column_stack(cols)
    neff = n_eff_from_matrix(mat)
    assert neff.low < neff.high, f"相关带没造出非退化 N_eff 区间（low={neff.low},high={neff.high}）"
    v = run_overfit_gate(target := base, n_eff=neff, honest_n=neff.n_observed, returns_matrix=mat, asset_class="crypto")
    # 保守端用更大 N（更多通缩）→ 必【严格】低于乐观端；若实现把 low/high 互换则此处翻转、断言失败。
    assert v.dsr_conservative < v.dsr_optimistic, \
        "保守端 DSR 没严格低于乐观端 → 保守端没用更大 N（low/high 互换类 bug，门坏）"


# ── T-OG-14 honest_n 兜底通缩：矩阵拼不出时不退化成零通缩（复核 #1/#4，命门·硬）──────
def test_honest_n_floors_deflation_when_matrix_unavailable():
    strong = _alpha_returns(t=600, loc=0.003, seed=131)
    neff1 = n_eff_from_matrix(strong.reshape(-1, 1))   # 单列 → N_eff=(1,1,1)
    assert (neff1.low, neff1.high) == (1, 1)
    v_n1 = run_overfit_gate(strong, n_eff=neff1, honest_n=1, returns_matrix=None, asset_class="crypto")
    v_n30 = run_overfit_gate(strong, n_eff=neff1, honest_n=30, returns_matrix=None, asset_class="crypto")
    assert v_n30.dsr_conservative < v_n1.dsr_conservative, \
        "honest_n=30 没比 =1 通缩更狠 → honest_n 没兜底通缩，矩阵拼不出时通缩归零（泄露过闸，门坏）"


# ── T-OG-15 V 不可估披露（R5）：no-matrix → var_sr_estimated False + 明示「退化旧近似」───
def test_var_not_estimated_disclosure():
    r = _alpha_returns(t=600, loc=0.002, seed=141)
    v_none = run_overfit_gate(r, n_eff=n_eff_from_matrix(r.reshape(-1, 1)), honest_n=1,
                              returns_matrix=None, asset_class="crypto")
    assert v_none.var_sr_estimated is False
    assert "退化旧近似" in v_none.verdict_phrasing or "V 未独立估计" in v_none.verdict_phrasing, \
        "V 不可估时没披露「通缩可能不足」（R5，门坏）"
    mat = np.column_stack([r] + [np.random.default_rng(i).normal(scale=0.01, size=600) for i in range(11)])
    v_mat = run_overfit_gate(r, n_eff=n_eff_from_matrix(mat), honest_n=12, returns_matrix=mat, asset_class="crypto")
    assert v_mat.var_sr_estimated is True
    assert "退化旧近似" not in v_mat.verdict_phrasing
