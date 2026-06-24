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


# ============================================================
# ba59fb7b · 组合 promote 生产端点 record=True 真记 honest-N（对抗测试，扩展不替换）
# 门必抓：① 组合 promote → honest-N 真 +1（portfolio:<id> 命名空间）；重排成分同 config_hash
#   不重复 +1（ADV2）。② 过拟合组合(strong_neg) promote → verdict 不达 green + 账如实记。
#   边界：记账接线断开（record=False / 不传 ledger）被测出差异——证明 record=True 真生效。
# ============================================================

import random
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.dag.artifact_store import ArtifactStore
from app.lineage.ledger import Ledger


def _green_series(n: int = 300, seed: int = 7) -> list[float]:
    """确定性正漂移低噪声 → 组合净收益高 Sharpe → DSR 保守端高 + CI 双正 → A2 green（PBO=N/A）。"""
    rng = random.Random(seed)
    return [0.004 + rng.gauss(0.0, 0.003) for _ in range(n)]


def _strong_neg_series(n: int = 300, seed: int = 11) -> list[float]:
    """确定性负漂移 → strong_neg（CI 上界≤0 / DSR<0.2）→ 即便 A2 仍 red（误绿兜底）。"""
    rng = random.Random(seed)
    return [-0.003 + rng.gauss(0.0, 0.004) for _ in range(n)]


@pytest.fixture()
def promote_env(tmp_path, monkeypatch):
    """隔离一本账：把 main.LEDGER/RETURNS_STORE 换成 tmp 实例（honest-N 从 0 起、不污染生产账本）。

    端点函数体内以模块全局名引用 LEDGER/RETURNS_STORE（非 default-arg 捕获），故 monkeypatch 生效。
    """
    led = Ledger(tmp_path / "lineage")
    rs = ArtifactStore(tmp_path / "returns")
    monkeypatch.setattr(main, "LEDGER", led)
    monkeypatch.setattr(main, "RETURNS_STORE", rs)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester", username="tester"
    )
    try:
        yield TestClient(main.app), led, rs
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
        led.close()


def test_portfolio_promote_records_honest_n_and_adv2_dedup(promote_env) -> None:
    """① 组合 promote → honest-N 真 0→1（portfolio:<id>）；同成分重 promote 不重复 +1；
    重排成分（同权重）同 config_hash → 仍不 +1（ADV2）；不同成分 → +1（证明能真增）。"""
    client, led, _ = promote_env
    pid = "ut_pf_hn"
    goal = f"portfolio:{pid}"
    A, B = _green_series(), [0.0] * 300

    assert led.honest_n(goal) == 0  # 隔离账本确定性起点

    body = {"weights": {"A": 0.5, "B": 0.5}, "asset_returns": {"A": A, "B": B},
            "markets": ["crypto"], "freq": "1d"}
    r1 = client.post(f"/api/portfolio/{pid}/promote", json=body)
    assert r1.status_code == 200, r1.text
    # —— 这条断言是 kill-switch：若端点被改成 record=False（本卡要防的 bug），honest-N 留 0、此处红 ——
    assert led.honest_n(goal) == 1
    j1 = r1.json()
    assert j1["honest_n"] == 1
    assert j1["recorded"] is True
    assert j1["config_hash"]
    assert j1["strategy_goal_ref"] == goal

    # 同成分再 promote → record_or_hit 幂等（复合键去重）→ 不重复 +1
    r2 = client.post(f"/api/portfolio/{pid}/promote", json=body)
    assert r2.status_code == 200
    assert led.honest_n(goal) == 1

    # ADV2：重排成分（同权重）→ portfolio_composition 规范化 → 同 config_hash → 仍不 +1
    body_reordered = {**body, "weights": {"B": 0.5, "A": 0.5}}
    r3 = client.post(f"/api/portfolio/{pid}/promote", json=body_reordered)
    assert r3.status_code == 200
    assert r3.json()["config_hash"] == j1["config_hash"]  # 重排同身份
    assert led.honest_n(goal) == 1                          # 防作弊：不重复刷 N

    # 不同成分（真不同组合）→ honest-N 真能 +1（防「record 恒空转」的伪通过）
    body_diff = {**body, "weights": {"A": 0.7, "B": 0.3}}
    r4 = client.post(f"/api/portfolio/{pid}/promote", json=body_diff)
    assert r4.status_code == 200
    assert led.honest_n(goal) == 2


def test_portfolio_promote_overfit_not_green_but_recorded(promote_env) -> None:
    """② 过拟合组合（strong_neg 负漂移）promote → verdict 不达 green（A2 不 override red）+ 账如实记。"""
    client, led, _ = promote_env
    pid = "ut_pf_overfit"
    goal = f"portfolio:{pid}"
    An, B = _strong_neg_series(), [0.0] * 300

    r = client.post(f"/api/portfolio/{pid}/promote", json={
        "weights": {"A": 0.5, "B": 0.5}, "asset_returns": {"A": An, "B": B}, "markets": ["crypto"]
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["color"] != "green"       # 过拟合绝不放行（strong_neg 兜底守北极星）
    assert j["promoted"] is False      # 记账 ≠ 过闸
    # 失败的试验也如实记账（绝不靠不记账洗白 honest-N）
    assert j["recorded"] is True
    assert led.honest_n(goal) == 1


def test_portfolio_promote_record_true_truly_takes_effect(promote_env, tmp_path) -> None:
    """边界（接线断开探针）：同一输入，端点 record=True 真记 1；直调 gate_portfolio(record=False)
    或不传 ledger 则账不动——差异证明端点的 record=True 真生效（非空转、非假绿灯）。"""
    client, led, _ = promote_env
    pid = "ut_pf_seam"
    goal = f"portfolio:{pid}"
    A, B = _green_series(), [0.0] * 300
    weights, ar = {"A": 0.5, "B": 0.5}, {"A": A, "B": B}

    # 接线断开 A：完全不传 ledger（gate 不记账）——honest-N 必须不动。
    res_noledger = gate_portfolio(
        portfolio_id=pid, weights=weights, asset_returns=ar, markets=["crypto"], record=True
    )
    assert led.honest_n(goal) == 0  # 没传 ledger → 账不动（探针 A）

    # 接线断开 B：传隔离 ledger 但 record=False（预览口径）——honest-N 仍不动。
    led_preview = Ledger(tmp_path / "preview_lin")
    rs_preview = ArtifactStore(tmp_path / "preview_ret")
    try:
        gate_portfolio(portfolio_id=pid, weights=weights, asset_returns=ar, markets=["crypto"],
                       ledger=led_preview, returns_store=rs_preview, record=False)
        assert led_preview.honest_n(goal) == 0  # record=False → 账不动（探针 B）
    finally:
        led_preview.close()

    # 真生产端点（record=True 硬编码）：同一输入 → honest-N 0→1。三者差异坐实 record=True 真生效。
    r = client.post(f"/api/portfolio/{pid}/promote", json={
        "weights": weights, "asset_returns": ar, "markets": ["crypto"]
    })
    assert r.status_code == 200, r.text
    assert led.honest_n(goal) == 1
    assert res_noledger.config_hash == r.json()["config_hash"]  # 同身份、唯记账面不同


def test_portfolio_promote_a2_green_is_honest_not_full_triangle(promote_env) -> None:
    """A2 放行诚实标：冷启动 green 时 pbo=None + all_agree_positive=False（非完整三角），
    且响应措辞不出现「可信/安全」（§3 不假绿灯 + 措辞守门）。"""
    client, _, _ = promote_env
    A, B = _green_series(), [0.0] * 300
    r = client.post("/api/portfolio/ut_pf_a2/promote", json={
        "weights": {"A": 0.5, "B": 0.5}, "asset_returns": {"A": A, "B": B}, "markets": ["crypto"]
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["color"] == "green"
    assert j["pbo"] is None                      # PBO N/A（冷启动构不成完整三角）
    assert j["all_agree_positive"] is False      # 非三支同向，A2 override 诚实标
    blob = (j.get("verdict_phrasing", "") + j.get("note", "") + j.get("honest_n_disclaimer", ""))
    assert "可信" not in blob and "安全" not in blob  # 措辞黑名单（不粉饰）


def test_portfolio_promote_rejects_unscoreable_without_recording(promote_env) -> None:
    """不可评分前拒绝（入账前）：weights 与 asset_returns 无交集 → 净收益<2 → 422，且账不动
    （honest-N 不可改小，绝不用不可评分 garbage 永久污染账本）。"""
    client, led, _ = promote_env
    pid = "ut_pf_garbage"
    goal = f"portfolio:{pid}"
    r = client.post(f"/api/portfolio/{pid}/promote", json={
        "weights": {"A": 1.0}, "asset_returns": {"Z": [0.01] * 300}, "markets": ["crypto"]
    })
    assert r.status_code == 422
    assert led.honest_n(goal) == 0  # 拒绝在入账前 → 账本零污染


def test_portfolio_promote_malformed_inputs_422(promote_env) -> None:
    """结构非法 → 422（绝不 500、绝不入账）：空 weights / 空 asset_returns / 空 markets / 非有限值。"""
    client, _, _ = promote_env
    A = _green_series()
    base = {"weights": {"A": 1.0}, "asset_returns": {"A": A}, "markets": ["crypto"]}

    assert client.post("/api/portfolio/p/promote", json={**base, "weights": {}}).status_code == 422
    assert client.post("/api/portfolio/p/promote", json={**base, "asset_returns": {}}).status_code == 422
    assert client.post("/api/portfolio/p/promote", json={**base, "markets": []}).status_code == 422
    # 空 markets 不得静默退化成 crypto/252（A股 504 min_T 静默放松洞）
    assert client.post("/api/portfolio/p/promote", json={k: v for k, v in base.items() if k != "markets"}).status_code == 422
    # 非有限值（NaN）→ 422 而非 500。NaN 经裸 JSON 串送达端点（标准 json 编码器客户端侧拒 NaN，
    # 故用 content= 绕过客户端编码，让 NaN 真到端点的有限性校验）。
    nan_body = '{"weights": {"A": 1.0}, "asset_returns": {"A": [NaN, NaN, 0.01]}, "markets": ["crypto"]}'
    rn = client.post("/api/portfolio/p/promote", content=nan_body,
                     headers={"Content-Type": "application/json"})
    assert rn.status_code == 422, rn.text


def test_portfolio_promote_short_valid_sample_is_insufficient_not_error(promote_env) -> None:
    """有效但样本太短（T≥2 但 < min_T）→ gate 诚实 insufficient_evidence（200，非 HTTP 错误）+
    照常入账（gate 能评分=一次真实多重检验）。"""
    client, led, _ = promote_env
    pid = "ut_pf_short"
    goal = f"portfolio:{pid}"
    short = [0.01, -0.005, 0.008, 0.0, 0.002]  # 5 点 < 252
    r = client.post(f"/api/portfolio/{pid}/promote", json={
        "weights": {"A": 1.0}, "asset_returns": {"A": short}, "markets": ["crypto"]
    })
    assert r.status_code == 200, r.text
    assert r.json()["color"] == "insufficient_evidence"
    assert led.honest_n(goal) == 1  # 有效可评分 → 照常入账（与不可评分 garbage 区分）


def test_portfolio_promote_namespace_isolated_from_single_strategy(promote_env) -> None:
    """命名空间物理隔离：组合 promote 只动 portfolio:<id>，不串单策略主题（同名 id 也不撞）。"""
    client, led, _ = promote_env
    A, B = _green_series(), [0.0] * 300
    client.post("/api/portfolio/shared_id/promote", json={
        "weights": {"A": 0.5, "B": 0.5}, "asset_returns": {"A": A, "B": B}, "markets": ["crypto"]
    })
    assert led.honest_n("portfolio:shared_id") == 1
    assert led.honest_n("shared_id") == 0  # 单策略裸主题 ref 不受影响（串号物理隔离）
