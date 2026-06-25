"""confirmatory 数据身份门【对抗式】测试（B-PIT-CONFIRMATORY · GOAL §16 line1759/line2028 · §6 line1112）。

种已知坏门必抓：无 PIT(known_at) / 无注册身份(dataset_version) 的数据进 confirmatory → 必拒；
放过即红。验收四条（可证伪）：
1. 无 known_at(PIT) 数据喂 confirmatory 回测/验证 → 拒（funnel raise + 绝不入账 honest-N）。
2. 无 dataset_version 注册身份进 confirmatory 冻结/promote → 拒（假设卡 freeze + funnel）。
3. exploratory（record=False）/ 无 registry / 合成 sample 探索 → 不受影响（不误伤·向后兼容）。
4. confirmatory 用【注册 + PIT】数据 → 正常放行（不误伤正路径）。

MUT kill-switch：funnel 用例同时断言「raise」+「honest_n 仍 0」——若把门退回 advisory（忽略
registry / 丢 enforce），坏数据会流进 record_or_hit、honest_n 变 1 → 断言红（门坏即抓）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from app.connectors.base import make_wide_fetch_result
from app.data_quality import DatasetRegistry
from app.eval.confirmatory_data_gate import (
    ConfirmatoryDataRejected,
    check_confirmatory_data,
    require_confirmatory_data,
)
from app.eval.gate_runner import evaluate_overfit_gate
from app.hypothesis import HypothesisCardStore
from app.hypothesis.store import FreezeRejected
from app.lineage.ledger import Ledger

GOOD_FALSIFIABLE = {
    "economic_mechanism": {
        "risk_premium_or_bias": "动量赌反应不足加处置效应",
        "causal_chain": "盈余漂移驱动价格延迟反应我们收割动量溢价",
        "confounder_concerns": ["规模", "流动性"],
    },
    "falsification_condition": "若A股融券年化利率持续高于15%则动量效应应在3个月内消失或反号",
    "stop_rule": "回撤超过20%或样本外IC连续3月为负则停",
}


def _frame(n: int = 8) -> pl.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        [
            {
                "ts": base + timedelta(days=i),
                "symbol": "000001.SZ",
                "market": "stocks_cn",
                "interval": "1d",
                "open": 10.0 + i,
                "high": 11.0 + i,
                "low": 9.5 + i,
                "close": 10.5 + i,
                "volume": 1000.0 + i,
            }
            for i in range(n)
        ]
    )


def _register(registry: DatasetRegistry, dataset_id: str, *, known_at: str | None, n: int = 8) -> str:
    """注册一条数据集 version，返回 version_id。known_at=None → 注册但无 PIT 语义。"""

    fr = make_wide_fetch_result(_frame(n), source_name="tushare")
    kw = {"known_at_utc": known_at} if known_at else {}
    v = registry.register(dataset_id, fr, **kw)
    return v.version_id


_RETURNS = [0.01, -0.004, 0.006, 0.002, -0.001, 0.008, 0.003, -0.002, 0.005, 0.001]


# ===================================================================== #
# A · 纯门函数 check_confirmatory_data / require_confirmatory_data
# ===================================================================== #


def test_gate_advisory_when_no_registry():
    """registry=None → 不强制（advisory）：无单一源不假装过滤，向后兼容。"""
    v = check_confirmatory_data("whatever", registry=None)
    assert v.allow is True and v.enforced is False
    # require_ 也不 raise（advisory 放行）
    require_confirmatory_data("whatever", registry=None)


@pytest.mark.parametrize("bad", ["", "unknown", "UNKNOWN", "none", "n/a"])
def test_gate_rejects_placeholder_dataset_version(tmp_path, bad):
    """占位/缺省 dataset_version = 无注册身份 → 拒（§16 line2028）。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    v = check_confirmatory_data(bad, registry=reg)
    assert v.allow is False and v.enforced is True
    with pytest.raises(ConfirmatoryDataRejected):
        require_confirmatory_data(bad, registry=reg)


def test_gate_rejects_unregistered_dataset_version(tmp_path):
    """未在 registry 注册的 dataset_version → 拒（不可追溯·§16 line2028）。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    _register(reg, "ds_pit", known_at="2024-01-05T00:00:00+00:00")  # 注册别的，确保 registry 非空
    v = check_confirmatory_data("20990101T000000__deadbeef", registry=reg)
    assert v.allow is False and v.enforced is True
    assert "未在 DatasetRegistry 注册" in v.reason


def test_gate_rejects_registered_without_known_at(tmp_path):
    """已注册但无 known_at/effective_at(PIT 语义缺) → 拒（§16 line1759 / §6 line1112）。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    vid = _register(reg, "ds_nopit", known_at=None)
    v = check_confirmatory_data(vid, registry=reg)
    assert v.allow is False and v.enforced is True
    assert "无 PIT 语义" in v.reason


def test_gate_allows_registered_pit(tmp_path):
    """已注册 + 带 known_at(PIT) → 放行（不误伤正路径），带回 lineage_id。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    vid = _register(reg, "ds_pit", known_at="2024-01-05T00:00:00+00:00")
    v = check_confirmatory_data(vid, registry=reg)
    assert v.allow is True and v.enforced is True
    assert v.known_at == "2024-01-05T00:00:00+00:00"
    assert v.lineage_id  # data 级谱系恒在场（复用 derive_dataset_lineage）
    require_confirmatory_data(vid, registry=reg)  # 不 raise


def test_gate_effective_at_only_also_passes(tmp_path):
    """只有 effective_at（无 known_at）也算带 PIT 语义 → 放行（§11 信封 known_at/effective_at）。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    v = reg.register("ds_eff", fr, effective_at_utc="2024-01-03T00:00:00+00:00")
    assert check_confirmatory_data(v.version_id, registry=reg).allow is True


# ===================================================================== #
# B · funnel evaluate_overfit_gate —— confirmatory 记账入口（真路径）
# ===================================================================== #


def test_funnel_rejects_nonpit_confirmatory_and_does_not_record(tmp_path):
    """验收① + MUT kill-switch：record=True(confirmatory) + 无 PIT 数据 → raise 且【不入账】。

    若门被退回 advisory（忽略 registry / 丢 enforce），坏数据会流进 record_or_hit、honest_n→1，
    `assert led.honest_n == 0` 即红——这条断言钉死「门真生效、坏数据没进账本」。
    """
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    led = Ledger(tmp_path / "ledger")
    vid_nopit = _register(reg, "ds_nopit", known_at=None)
    theme = "theme_confirmatory_nopit"

    with pytest.raises(ConfirmatoryDataRejected):
        evaluate_overfit_gate(
            returns=_RETURNS, factor="alpha_x", universe="stocks_cn",
            dataset_version=vid_nopit, freq="1d", strategy_goal_ref=theme,
            asset_class="a_share", ledger=led, returns_store=None,
            record=True, registry=reg,
        )
    # 入账前拒绝：一本账纹丝不动（honest-N 不可被无 PIT confirmatory 污染）。
    assert led.honest_n(theme) == 0


def test_funnel_rejects_unknown_dataset_version_confirmatory(tmp_path):
    """验收②：record=True 但 dataset_version=占位「unknown」→ 拒（无注册身份不得进 confirmatory）。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    led = Ledger(tmp_path / "ledger")
    theme = "theme_unknown_dv"
    with pytest.raises(ConfirmatoryDataRejected):
        evaluate_overfit_gate(
            returns=_RETURNS, factor="a", universe="u", dataset_version="unknown",
            freq="1d", strategy_goal_ref=theme, asset_class="crypto",
            ledger=led, returns_store=None, record=True, registry=reg,
        )
    assert led.honest_n(theme) == 0


def test_funnel_allows_registered_pit_confirmatory_and_records(tmp_path):
    """验收④：record=True + 注册 + PIT 数据 → 放行且正常入账（honest_n 0→1，不误伤）。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    led = Ledger(tmp_path / "ledger")
    vid = _register(reg, "ds_pit", known_at="2024-01-05T00:00:00+00:00")
    theme = "theme_confirmatory_pit"
    gr = evaluate_overfit_gate(
        returns=_RETURNS, factor="alpha_x", universe="stocks_cn",
        dataset_version=vid, freq="1d", strategy_goal_ref=theme,
        asset_class="a_share", ledger=led, returns_store=None,
        record=True, registry=reg,
    )
    assert gr.honest_n == 1
    assert led.honest_n(theme) == 1


def test_funnel_exploratory_preview_not_gated(tmp_path):
    """验收③：record=False（exploratory/preview）+ 无 PIT 数据 + registry → 不门控（探索自由）。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    led = Ledger(tmp_path / "ledger")
    vid_nopit = _register(reg, "ds_nopit", known_at=None)
    theme = "theme_preview"
    # 不 raise（exploratory 不卡）；record=False → 本就不入账。
    evaluate_overfit_gate(
        returns=_RETURNS, factor="a", universe="stocks_cn", dataset_version=vid_nopit,
        freq="1d", strategy_goal_ref=theme, asset_class="a_share",
        ledger=led, returns_store=None, record=False, registry=reg,
    )
    assert led.honest_n(theme) == 0


def test_funnel_no_registry_is_backward_compatible(tmp_path):
    """验收③（向后兼容基线）：registry=None → 门不触发，record=True + 占位 dataset_version 照常入账。

    这正是既有 test_gate_wiring / 端点 record=True 的口径（不传 registry）——不破基线。
    """
    led = Ledger(tmp_path / "ledger")
    theme = "theme_no_registry"
    gr = evaluate_overfit_gate(
        returns=_RETURNS, factor="a", universe="u", dataset_version="unknown",
        freq="1d", strategy_goal_ref=theme, asset_class="crypto",
        ledger=led, returns_store=None, record=True,  # registry 缺省 None
    )
    assert gr.honest_n == 1 and led.honest_n(theme) == 1


def test_funnel_enforce_false_disables_gate(tmp_path):
    """单点可逆证明：enforce_confirmatory_pit=False → 门关，坏数据放行入账（门确是当事机制）。

    与 test_funnel_rejects_nonpit_... 同输入、唯一差异是 enforce 翻 False → 从 raise 变放行，
    坐实「拒绝来自这道门」而非别处副作用。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    led = Ledger(tmp_path / "ledger")
    vid_nopit = _register(reg, "ds_nopit", known_at=None)
    theme = "theme_enforce_off"
    gr = evaluate_overfit_gate(
        returns=_RETURNS, factor="a", universe="stocks_cn", dataset_version=vid_nopit,
        freq="1d", strategy_goal_ref=theme, asset_class="a_share",
        ledger=led, returns_store=None, record=True, registry=reg,
        enforce_confirmatory_pit=False,
    )
    assert gr.honest_n == 1 and led.honest_n(theme) == 1


# ===================================================================== #
# C · 假设卡 freeze —— confirmatory 冻结（promote 层）
# ===================================================================== #


def _confirmatory_card(store: HypothesisCardStore, theme: str = "g_pit"):
    return store.create(strategy_goal_ref=theme, layer="confirmatory", falsifiable=GOOD_FALSIFIABLE)


def test_freeze_rejects_nonpit_oos_with_registry(tmp_path):
    """验收②：接 registry 时，frozen_oos.dataset_version 无 PIT/未注册 → FreezeRejected。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    led = Ledger(tmp_path / "ledger")
    store = HypothesisCardStore(tmp_path / "cards")
    vid_nopit = _register(reg, "ds_nopit", known_at=None)
    card = _confirmatory_card(store)
    with pytest.raises(FreezeRejected, match="数据身份门"):
        store.freeze(card.card_id, frozen_oos={"dataset_version": vid_nopit}, ledger=led, registry=reg)
    # 未注册的随机 version 同样拒
    card2 = _confirmatory_card(store, theme="g_pit2")
    with pytest.raises(FreezeRejected, match="数据身份门"):
        store.freeze(card2.card_id, frozen_oos={"dataset_version": "ds_fake"}, ledger=led, registry=reg)


def test_freeze_allows_registered_pit_oos_with_registry(tmp_path):
    """验收④：接 registry 时，frozen_oos.dataset_version 注册 + PIT → 正常冻结（不误伤）。"""
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    led = Ledger(tmp_path / "ledger")
    store = HypothesisCardStore(tmp_path / "cards")
    vid = _register(reg, "ds_pit", known_at="2024-01-05T00:00:00+00:00")
    card = _confirmatory_card(store)
    frozen = store.freeze(card.card_id, frozen_oos={"dataset_version": vid}, ledger=led, registry=reg)
    assert frozen.status == "frozen"


def test_freeze_without_registry_unchanged_baseline(tmp_path):
    """验收③（向后兼容基线）：registry=None（既有口径）→ 冻结行为逐字不变，'ds1' 仍可冻。"""
    led = Ledger(tmp_path / "ledger")
    store = HypothesisCardStore(tmp_path / "cards")
    card = _confirmatory_card(store)
    frozen = store.freeze(card.card_id, frozen_oos={"dataset_version": "ds1"}, ledger=led)
    assert frozen.status == "frozen"
