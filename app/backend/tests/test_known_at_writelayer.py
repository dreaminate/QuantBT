"""R28 双时态 · 写层 first-seen known_at 守卫（D 卡 3a8b2360 / DECISIONS D-WAVE1A · D-AXIS=A）。

写层 owns first-seen（D-AXIS=A）：tushare 财报落盘加 known_at（= ann_date；脏/空 ann_date → 写入日
下界，永不泄漏未来），`_upsert_partition` keep-first-on-known_at —— 同身份多 known_at 取最早、
re-backfill 不推进。真正系统性丢 first-seen 的读层折叠由读层 as_of_known 路径处理（见 test_data_contract）。

门必抓（种已知坏，门必抓）：
- 断言1：不同 ann_date 的重述各自成行、known_at 各自；**同 ann_date 脏重述守住首披值**
  （把 `_upsert_partition` 改回 keep="last" → 读到后写的修正值 10.5 → 红）。
- 断言2：re-backfill 同 restatement 不增行、known_at 不推进；existing known_at 不被新派生覆盖。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl

from app.tushare_quant1 import tushare_provider as tp
from app.tushare_quant1.tushare_provider import (
    KNOWN_AT_COLUMN,
    _derive_known_at,
    _upsert_partition,
)

# 财报表身份键（含 ann_date；known_at 是属性、不在键里）。
FIN_KEYS = ("ts_code", "ann_date", "end_date")


def _fin_row(ts_code: str, ann_date: int | None, end_date: int, roe: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_code": [ts_code],
            "ann_date": pl.Series([ann_date], dtype=pl.Int64),
            "end_date": pl.Series([end_date], dtype=pl.Int64),
            "roe": [roe],
        }
    )


def test_derive_known_at_from_ann_date_and_dirty_fallback(monkeypatch):
    monkeypatch.setattr(tp, "_utc_now", lambda: datetime(2024, 6, 1, tzinfo=UTC))
    # ann_date → first-seen known_at
    out = _derive_known_at(_fin_row("X", 20240130, 20240331, 10.0))
    assert out[KNOWN_AT_COLUMN].to_list() == [date(2024, 1, 30)]
    # 脏/空 ann_date（f_ann_date null/不可解析）→ 写入日下界（GOAL §8 / R28）
    dirty = _fin_row("X", None, 20240331, 10.0)
    assert _derive_known_at(dirty)[KNOWN_AT_COLUMN].to_list() == [date(2024, 6, 1)]


def test_derive_does_not_overwrite_existing_known_at(monkeypatch):
    """幂等核心：existing 行（读回带 known_at）不被新派生值覆盖。"""
    monkeypatch.setattr(tp, "_utc_now", lambda: datetime(2024, 6, 1, tzinfo=UTC))
    existing = _fin_row("Z", 20240601, 20240331, 10.0).with_columns(
        pl.Series(KNOWN_AT_COLUMN, [date(2024, 2, 1)], dtype=pl.Date)
    )
    out = _derive_known_at(existing)
    assert out[KNOWN_AT_COLUMN].to_list() == [date(2024, 2, 1)]  # 保 2-01，不变 6-01


def test_upsert_keepfirst_restatements_and_dirty(tmp_path):
    # 断言1a：不同 ann_date 重述 → 两行保留、known_at 各自（双时态不折叠）
    path = tmp_path / "income" / "X.csv"
    _upsert_partition(path, _derive_known_at(_fin_row("X", 20240130, 20240331, 10.0)), FIN_KEYS)
    _upsert_partition(path, _derive_known_at(_fin_row("X", 20240415, 20240331, 10.5)), FIN_KEYS)
    back = pl.read_csv(path, try_parse_dates=True).sort(KNOWN_AT_COLUMN)
    assert back.height == 2
    assert back[KNOWN_AT_COLUMN].to_list() == [date(2024, 1, 30), date(2024, 4, 15)]
    assert sorted(back["roe"].to_list()) == [10.0, 10.5]

    # 断言1b：同 ann_date 脏重述（reuse ann_date 改值）→ 守住首披 10.0（keep="last" 会读 10.5）
    path2 = tmp_path / "income" / "Y.csv"
    _upsert_partition(path2, _derive_known_at(_fin_row("Y", 20240130, 20240331, 10.0)), FIN_KEYS)
    _upsert_partition(path2, _derive_known_at(_fin_row("Y", 20240130, 20240331, 10.5)), FIN_KEYS)
    back2 = pl.read_csv(path2, try_parse_dates=True)
    assert back2.height == 1
    assert back2["roe"].to_list() == [10.0]
    assert back2[KNOWN_AT_COLUMN].to_list() == [date(2024, 1, 30)]


def test_rebackfill_idempotent(tmp_path):
    """断言2：re-backfill 同一 restatement → 不增行、known_at 不推进。"""
    path = tmp_path / "income" / "Z.csv"
    _upsert_partition(path, _derive_known_at(_fin_row("Z", 20240130, 20240331, 10.0)), FIN_KEYS)
    _upsert_partition(path, _derive_known_at(_fin_row("Z", 20240130, 20240331, 10.0)), FIN_KEYS)
    back = pl.read_csv(path, try_parse_dates=True)
    assert back.height == 1
    assert back[KNOWN_AT_COLUMN].to_list() == [date(2024, 1, 30)]


def test_non_financial_spec_unaffected(tmp_path):
    """行情类（无 known_at 列）走原 keep="last" 不变（不破基线）。"""
    path = tmp_path / "daily" / "X.csv"
    f1 = pl.DataFrame({"ts_code": ["X"], "trade_date": pl.Series([20240130], dtype=pl.Int64), "close": [10.0]})
    f2 = pl.DataFrame({"ts_code": ["X"], "trade_date": pl.Series([20240130], dtype=pl.Int64), "close": [11.0]})
    _upsert_partition(path, f1, ("ts_code", "trade_date"))
    _upsert_partition(path, f2, ("ts_code", "trade_date"))
    back = pl.read_csv(path, try_parse_dates=True)
    assert back.height == 1
    assert back["close"].to_list() == [11.0]  # keep="last" 原行为：行情取最新
    assert KNOWN_AT_COLUMN not in back.columns
