"""W3 · B-VERSION-1 · 数据写时强约束门（缺 dataset_version/checksum → 拒）。

把已建的不可变寻址原语接进**实际登记写路径**（DatasetRegistry.register —— intake.py
等所有写路径的唯一单点）：缺 dataset_version 必备身份、缺 checksum、或 checksum 与
frame 内容不匹配（篡改）的写入，直接 raise，绝不静默落账。

可证伪验收（种坏门必抓）：
1. 缺 dataset_version：dataset_id 空 / fetched_at_utc 空 → 登记被拒、且不落账。
2. 缺 / 篡改 checksum：sha256 空 / 非 64-hex / 与 frame 重算不符 → 拒、且不落账。
3. 合法 version+checksum → 正常落账（正路径不误伤·空 frame 不误伤·向后兼容）。

门 = 单源 FetchResult.validate_for_write（connectors/base.py），register 强制调用；
复用既有 _sha256_of_frame，绝不另造哈希。
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from app.connectors.base import (
    DatasetWriteIntegrityError,
    enforce_unified_schema,
    make_fetch_result,
    make_wide_fetch_result,
)
from app.data_quality import DatasetRegistry


def _frame(n: int = 4) -> pl.DataFrame:
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
                "pe_ttm": 15.0 + i,
            }
            for i in range(n)
        ]
    )


def _reg(tmp_path) -> DatasetRegistry:
    return DatasetRegistry(tmp_path / "registry.jsonl")


# --------------------------------------------------------------------------- #
# 验收 3：正路径不误伤（合法 version+checksum → 正常写入·向后兼容）
# --------------------------------------------------------------------------- #
def test_legit_write_succeeds(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    v = reg.register("ds_ok", fr, metadata={"market": "stocks_cn"})
    assert v.sha256 == fr.sha256
    assert v.version_id and "__" in v.version_id  # version_id 成形
    assert reg.latest("ds_ok") is not None


def test_legit_empty_frame_write_not_rejected(tmp_path) -> None:
    """空 frame 是合法的'无数据'结果（空哈希仍是有效 64-hex）→ 门绝不误伤。"""
    reg = _reg(tmp_path)
    fr = make_fetch_result(enforce_unified_schema(pl.DataFrame()), source_name="tushare")
    v = reg.register("ds_empty", fr)
    assert v.row_count == 0
    assert len(v.sha256) == 64


def test_validate_for_write_passes_on_legit_result() -> None:
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    fr.validate_for_write(dataset_id="ds")  # 不抛即为通过


def test_registered_record_matches_fetch_result(tmp_path) -> None:
    """向后兼容证据：合法写入落账内容 = FetchResult 派生值，门不改写已写字节。"""
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    v = reg.register("ds_bc", fr, metadata={"market": "stocks_cn"})
    line = (tmp_path / "registry.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["dataset_id"] == "ds_bc"
    assert rec["sha256"] == fr.sha256
    assert rec["version_id"] == v.version_id


# --------------------------------------------------------------------------- #
# 验收 1：缺 dataset_version 必备身份 → 拒（且不落账）
# --------------------------------------------------------------------------- #
def test_blank_dataset_id_rejected(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    with pytest.raises(DatasetWriteIntegrityError):
        reg.register("   ", fr)  # 空白 dataset_id
    assert reg.list_versions() == []  # 拒后不得落账


def test_empty_dataset_id_rejected(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    with pytest.raises(DatasetWriteIntegrityError):
        reg.register("", fr)
    assert reg.list_versions() == []


def test_missing_fetched_at_rejected(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    bad = dataclasses.replace(fr, fetched_at_utc="")  # version_id 无法成形
    with pytest.raises(DatasetWriteIntegrityError):
        reg.register("ds", bad)
    assert reg.list_versions() == []


# --------------------------------------------------------------------------- #
# 验收 2：缺 / 篡改 checksum → 拒（且不落账）
# --------------------------------------------------------------------------- #
def test_missing_checksum_rejected(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    bad = dataclasses.replace(fr, sha256="")
    with pytest.raises(DatasetWriteIntegrityError):
        reg.register("ds", bad)
    assert reg.list_versions() == []


def test_malformed_checksum_rejected(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    bad = dataclasses.replace(fr, sha256="not-a-real-64-hex-sha256")
    with pytest.raises(DatasetWriteIntegrityError):
        reg.register("ds", bad)
    assert reg.list_versions() == []


def test_tampered_checksum_rejected(tmp_path) -> None:
    """对抗：合法 64-hex 但与 frame 内容不符（篡改 declared sha）→ verify 失败 → 拒。"""
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    tampered = "0" * 64
    assert tampered != fr.sha256
    bad = dataclasses.replace(fr, sha256=tampered)
    with pytest.raises(DatasetWriteIntegrityError):
        reg.register("ds", bad)
    assert reg.list_versions() == []


def test_frame_swapped_under_declared_checksum_rejected(tmp_path) -> None:
    """对抗：保留旧 sha256、把 frame 换成别的内容（内容漂移）→ 重算不匹配 → 拒。"""
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(4), source_name="tushare")
    other = make_wide_fetch_result(_frame(8), source_name="tushare")
    assert fr.sha256 != other.sha256
    bad = dataclasses.replace(fr, frame=other.frame)  # sha256 仍是 4 行的、frame 已是 8 行
    with pytest.raises(DatasetWriteIntegrityError):
        reg.register("ds", bad)
    assert reg.list_versions() == []
