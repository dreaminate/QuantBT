"""数据平台 v2 · P4 Agent 字段对齐工具测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.agent.tool_handlers import referenced_columns, register_field_tools
from app.connectors.base import make_wide_fetch_result
from app.data_quality import DatasetRegistry
from app.field_catalog import FieldCatalog, FieldMappingStore


class _Runtime:
    def __init__(self) -> None:
        self.tools: dict = {}

    def register_tool(self, name, fn) -> None:
        self.tools[name] = fn


def _setup(tmp_path: Path):
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    f = pl.DataFrame(
        [{"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "X", "market": "stocks_cn",
          "interval": "1d", "close": 10.0, "volume": 100.0, "pe_ttm": 15.0, "alpha_x": 0.3}]
    )
    p = tmp_path / "d.parquet"
    f.write_parquet(p)
    reg.register("d", make_wide_fetch_result(f, "user_x"), file_paths=[str(p)],
                 metadata={"market": "stocks_cn", "interval": "1d", "data_kind": "daily"})
    store = FieldMappingStore(":memory:")
    cat = FieldCatalog(reg, mapping=store)
    rt = _Runtime()
    register_field_tools(rt, field_catalog=cat, mapping_store=store)
    return rt, cat, store


def test_referenced_columns_excludes_operators() -> None:
    assert referenced_columns("ts_mean(close, 5)") == {"close"}
    assert referenced_columns("rank(ts_corr(close, volume, 20))") == {"close", "volume"}


def test_describe_fields_tool(tmp_path: Path) -> None:
    rt, _cat, _store = _setup(tmp_path)
    out = rt.tools["data.describe_fields"]("data.describe_fields", {"market": "stocks_cn", "interval": "1d"})
    canon = {e["field_id"] for e in out["canonical"]}
    free = {e["field_id"] for e in out["freeform"]}
    assert {"close", "volume", "pe_ttm"}.issubset(canon)
    assert "user_x__alpha_x" in free
    assert out["datasets"] and out["datasets"][0]["source"] == "user_x"


def test_infer_mapping_tool(tmp_path: Path) -> None:
    rt, _cat, _store = _setup(tmp_path)
    out = rt.tools["data.infer_mapping"]("data.infer_mapping", {"columns": ["close", "pe_ttm", "px_weird"], "market": "stocks_cn"})
    by_col = {s["raw_column"]: s for s in out["suggestions"]}
    assert by_col["close"]["suggested_field_id"] == "close" and not by_col["close"]["is_freeform"]
    assert by_col["pe_ttm"]["suggested_field_id"] == "pe_ttm"
    assert by_col["px_weird"]["is_freeform"]  # 词典无对应
    assert "close" in out["canonical_options"]


def test_validate_columns_tool(tmp_path: Path) -> None:
    rt, _cat, _store = _setup(tmp_path)
    ok = rt.tools["factor.validate_columns"]("factor.validate_columns", {"formula": "ts_mean(close, 5)", "market": "stocks_cn"})
    assert ok["ok"] and not ok["missing"]
    bad = rt.tools["factor.validate_columns"]("factor.validate_columns", {"formula": "ts_mean(nonexist_col, 5)", "market": "stocks_cn"})
    assert not bad["ok"] and "nonexist_col" in bad["missing"]
    assert bad["suggestions"]  # 给出映射建议


def test_apply_mapping_tool_then_resolves(tmp_path: Path) -> None:
    rt, cat, store = _setup(tmp_path)
    # 用户源 user_myapi 的 px 列映射到 canonical close
    res = rt.tools["data.apply_mapping"]("data.apply_mapping", {
        "source": "user_myapi", "data_kind": "ohlcv",
        "mappings": [{"raw_column": "px", "field_id": "close"}],
    })
    assert res["count"] == 1
    assert store.get("user_myapi", "ohlcv")["px"] == ("close", False)
