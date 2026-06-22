"""C · 组合层多证据三角守门 对抗测试（D-WAVE1A · 卡 46f1cb3c）。

门必抓：
- ADV1（A2 放行 + 误绿兜底）：缺 PBO 时默认至多 yellow（R2）；A2 下 DSR+CI 双正才 green；
  过拟合（DSR<0.2 / CI 上界≤0）即便 A2 仍 strong_neg→red（绝不误绿）。
- ADV2（反作弊）：成分重排 → 同 config_hash（honest-N 不重复刷）。
- Q3：多市场混合取最严 min_T。
- 验收重写（非「必红」假命题）：组合层无 alpha → 不达 green。
"""

from __future__ import annotations

from app.eval.overfit_gate import _decide
from app.lineage import config_hash
from app.portfolio.gate import (
    gate_portfolio,
    portfolio_composition,
    portfolio_net_returns,
    portfolio_strategy_goal_ref,
    strictest_asset_class,
)


def test_portfolio_net_returns() -> None:
    w = {"A": 0.5, "B": 0.5}
    r = {"A": [0.02, 0.0, -0.01], "B": [0.0, 0.04, 0.01]}
    assert portfolio_net_returns(w, r) == [0.01, 0.02, 0.0]
    assert portfolio_net_returns({"A": 1.0}, {}) == []  # 无对齐标的 → 空


def test_adv1_a2_relax_and_no_false_green() -> None:
    """A2 放行只在 DSR+CI 双正；strong_neg 永远 red（误绿兜底）；单策略(allow=False)不受影响。"""
    # 缺 PBO + DSR/CI 双正：默认 yellow（完整三角 R2）；A2 → green
    assert _decide(0.6, None, 0.1, 0.5)[0] == "yellow"
    assert _decide(0.6, None, 0.1, 0.5, allow_pbo_absent_green=True)[0] == "green"
    # A2-green 时 all_agree=False（诚实标非完整三角）
    assert _decide(0.6, None, 0.1, 0.5, allow_pbo_absent_green=True)[1] is False
    # 误绿兜底：过拟合 DSR<0.2 → strong_neg → red（A2 不 override red）
    assert _decide(0.1, None, 0.1, 0.5, allow_pbo_absent_green=True)[0] == "red"
    # CI 上界≤0（强负）→ red
    assert _decide(0.6, None, -0.2, -0.05, allow_pbo_absent_green=True)[0] == "red"
    # CI 下界≤0 但上界>0（非强负、非双正）→ A2 仍 yellow（需 DSR+CI 双正）
    assert _decide(0.6, None, -0.05, 0.3, allow_pbo_absent_green=True)[0] == "yellow"
    # 单策略路径（allow=False）：缺 PBO 永远至多 yellow，绝不被组合层放松影响
    assert _decide(0.9, None, 0.5, 0.9)[0] == "yellow"


def test_adv2_composition_reorder_same_config_hash() -> None:
    w1 = {"A": 0.3, "B": 0.3, "C": 0.4}
    w2 = {"C": 0.4, "B": 0.3, "A": 0.3}
    assert portfolio_composition(w1) == portfolio_composition(w2)  # 规范化抹平顺序
    common = dict(universe="portfolio", dataset_version="v1", freq="1d", label="portfolio_net_return")
    h1 = config_hash(factor="portfolio", params={"composition": portfolio_composition(w1)}, **common)
    h2 = config_hash(factor="portfolio", params={"composition": portfolio_composition(w2)}, **common)
    assert h1 == h2  # 重排标的 → 同 config_hash → honest-N 不重复 +1（防作弊）


def test_q3_strictest_asset_class() -> None:
    assert strictest_asset_class(["crypto", "crypto"]) == "crypto"
    assert strictest_asset_class(["crypto", "stocks_cn"]) == "a_share"  # 含 A股 → 最严 504


def test_gate_portfolio_no_alpha_not_green() -> None:
    """验收重写：组合层无 alpha（负漂移）→ 三角不达 green；冷启动 PBO=N/A。"""
    n = 300
    ar = {"A": [(-0.02 if i % 2 == 0 else 0.01) for i in range(n)], "B": [0.0] * n}
    res = gate_portfolio(
        portfolio_id="p1", weights={"A": 0.5, "B": 0.5}, asset_returns=ar, markets=["crypto"], record=False
    )
    assert res.verdict.color != "green"      # 无 alpha 绝不放行
    assert res.verdict.pbo is None           # 单序列冷启动 → PBO N/A（构不成完整三角）
    assert res.config_hash                    # 复用 ids 单一身份源


def test_gate_portfolio_uses_portfolio_namespace() -> None:
    assert portfolio_strategy_goal_ref("abc") == "portfolio:abc"
