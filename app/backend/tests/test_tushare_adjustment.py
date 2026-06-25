"""Tushare runtime 复权对抗测试（拆『未复权价喂回测/成交层』RULES 停工红线地雷·审计 pass2 #1）。

门必抓：
- **原始未复权源乘 adj 复权**：除权跳变样本经复权后收益连续（纯价格 alpha），真实收益保留；sentinel（不复权）跳变还在。
- **缺 adj raise**：原始未复权源 + adj 缺失 → raise（绝不写未复权价·不假绿）。
- **防双重复权**：已复权源（apply_adjustment=False）绝不再乘 adj（us_daily_adj 等）。
- **源感知集**：_RAW_PRICE_SOURCES 含 daily/pro_bar/hk_daily/us_daily，不含已复权 us_daily_adj。
"""

from __future__ import annotations

import polars as pl
import pytest

from app.tushare_quant1.tushare_provider import (
    _RAW_PRICE_SOURCES,
    _merge_runtime_adjustment_factor,
)


def _price(close, *, volume=None, n=None):
    n = n or len(close)
    return pl.DataFrame({
        "symbol": ["AAA"] * n,
        "timestamp": list(range(1, n + 1)),
        "open": list(close), "high": list(close), "low": list(close), "close": list(close),
        "volume": list(volume) if volume is not None else [100.0] * n,
    })


def _adj(factors):
    return pl.DataFrame({
        "symbol": ["AAA"] * len(factors),
        "timestamp": list(range(1, len(factors) + 1)),
        "adj_factor": list(factors),
    })


def test_raw_source_adjustment_removes_exdiv_jump():
    """原始未复权源乘 adj：day3 拆股(11→5.5 = 原始 -50%)经复权后收益≈0(纯股本跳变消除)、day2 +10% 真实收益保留。

    raw close=[10,11,5.5,5.5]、adj=[1,1,2,2]、qfq=adj/adj_last=[.5,.5,1,1] → P_adj=[5,5.5,5.5,5.5]。
    MUT（still join 不乘 / 取错 last）→ 复权后仍含跳变，本测红。
    """
    out = _merge_runtime_adjustment_factor(
        _price([10.0, 11.0, 5.5, 5.5]), _adj([1.0, 1.0, 2.0, 2.0]), apply_adjustment=True,
    ).sort("timestamp")
    adj_close = out.get_column("close").to_list()
    assert adj_close == pytest.approx([5.0, 5.5, 5.5, 5.5])
    rets = [adj_close[i] / adj_close[i - 1] - 1 for i in range(1, 4)]
    assert rets[0] == pytest.approx(0.10)           # day2 真实 +10% 保留
    assert abs(rets[1]) < 1e-9                       # day3 拆股跳变被复权消除（纯价格 alpha）
    assert abs(rets[2]) < 1e-9
    # sentinel：原始未复权 day3 收益 = -50%（跳变还在）——证复权确实改变了序列
    raw = [10.0, 11.0, 5.5, 5.5]
    assert raw[2] / raw[1] - 1 == pytest.approx(-0.5)
    assert "adj_factor" not in out.columns          # 悬空列已乘入并丢弃，不写脏列


def test_volume_inverse_adjusted_preserves_value():
    """volume 反向除 qfq（守 P·V 值不变）：qfq=[.5,.5,1,1] → V_adj=V/qfq=[200,200,100,100]。"""
    out = _merge_runtime_adjustment_factor(
        _price([10.0, 10.0, 5.0, 5.0], volume=[100.0, 100.0, 100.0, 100.0]),
        _adj([1.0, 1.0, 2.0, 2.0]), apply_adjustment=True,
    ).sort("timestamp")
    assert out.get_column("volume").to_list() == pytest.approx([200.0, 200.0, 100.0, 100.0])


def test_raw_source_missing_adj_raises():
    """**红线门**：原始未复权源 + adj 缺失 → raise（绝不写未复权价喂成交层）。"""
    with pytest.raises(ValueError, match="未复权|停工红线"):
        _merge_runtime_adjustment_factor(_price([10.0, 5.0]), pl.DataFrame(), apply_adjustment=True)


def test_pre_adjusted_source_not_double_adjusted():
    """**防双重复权**：已复权源 apply_adjustment=False → 原样返回，绝不再乘 adj（即便 adj_frame 在场）。"""
    raw = [10.0, 11.0, 5.5, 5.5]
    out = _merge_runtime_adjustment_factor(
        _price(raw), _adj([1.0, 1.0, 2.0, 2.0]), apply_adjustment=False,
    ).sort("timestamp")
    assert out.get_column("close").to_list() == pytest.approx(raw)   # 未被复权（已复权源不重复乘）
    assert "adj_factor" not in out.columns                            # 也不贴悬空列


def test_adj_coverage_gap_forward_filled_no_null():
    """adj 覆盖不全（某日缺）→ symbol 内前向填充、无 null 价（累积因子事件间稳定）。"""
    price = _price([10.0, 10.0, 5.0, 5.0])
    adj = pl.DataFrame({"symbol": ["AAA"] * 3, "timestamp": [1, 2, 4], "adj_factor": [1.0, 1.0, 2.0]})  # 缺 day3
    out = _merge_runtime_adjustment_factor(price, adj, apply_adjustment=True).sort("timestamp")
    assert out.get_column("close").null_count() == 0
    assert out.height == 4


def test_raw_price_sources_set_excludes_pre_adjusted():
    """源感知集：原始未复权源在集内、已复权 us_daily_adj 不在（防双重复权的判据）。"""
    assert {"daily", "pro_bar", "hk_daily", "us_daily"} <= _RAW_PRICE_SOURCES
    assert "us_daily_adj" not in _RAW_PRICE_SOURCES
