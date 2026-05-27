from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest

from app.connectors import (
    BinanceRESTConnector,
    BinanceVisionConnector,
    ConnectorRegistry,
    FetchRequest,
    GenericRESTConfig,
    GenericRESTConnector,
    TushareConnector,
    UploadDatasetRegistration,
    UploadFieldMapping,
    UserUploadConnector,
    enforce_unified_schema,
    registry,
)
from app.connectors.base import UNIFIED_OHLCV_COLUMNS
from app.connectors.generic_rest import _coerce_ts, _resolve_jsonpath, _resolve_template


def test_unified_schema_fills_missing_columns() -> None:
    df = pl.DataFrame({"ts": [datetime(2024, 1, 1, tzinfo=UTC)], "close": [10.0], "symbol": ["X"]})
    aligned = enforce_unified_schema(df)
    assert list(aligned.columns) == list(UNIFIED_OHLCV_COLUMNS)
    assert aligned.height == 1
    assert aligned["close"].to_list() == [10.0]


def test_registry_bootstraps_default_connectors() -> None:
    names = registry.names()
    assert "tushare" in names
    assert "binance_vision_usdm" in names
    assert "binance_rest_usdm" in names


def test_registry_register_and_get() -> None:
    custom = ConnectorRegistry()
    cap_seen: list[str] = []

    class Dummy(TushareConnector):
        def describe(self):  # type: ignore[override]
            cap = super().describe()
            cap_seen.append(cap.name)
            return cap

    custom.register_instance("dummy", Dummy(token="DUMMY"))
    assert custom.names() == ["dummy"]
    custom.get("dummy").describe()
    assert cap_seen == ["tushare"]


def test_generic_rest_resolve_template_and_jsonpath() -> None:
    assert _resolve_template("/v1/{symbol}/{interval}", {"symbol": "X", "interval": "1d"}) == "/v1/X/1d"
    payload = {"data": [{"t": 1, "o": 1.0}, {"t": 2, "o": 2.0}]}
    assert _resolve_jsonpath(payload, "$.data[*]") == payload["data"]
    assert _resolve_jsonpath(payload, "$.data[0].o") == 1.0


def test_generic_rest_ts_coercion() -> None:
    assert _coerce_ts(1_700_000_000_000, "ms").year == 2023
    assert _coerce_ts("2024-05-01", "date").year == 2024
    assert _coerce_ts("2024-05-01T10:00:00Z", "iso").hour == 10
    assert _coerce_ts(None, "ms") is None


def test_generic_rest_fetch_with_mocked_http() -> None:
    yaml_text = """
connector_name: stub
label: Stub Source
asset_class: custom
base_url: https://example.invalid
supported_markets: [custom]
supported_intervals: [1d]
endpoints:
  ohlcv:
    method: GET
    path: /quote/{symbol}/daily
    rate_limit_per_minute: 600
    response_mapping:
      records: "$.data[*]"
      fields:
        ts: t
        open: o
        high: h
        low: l
        close: c
        volume: v
      ts_unit: ms
      tz: UTC
schema_target: ohlcv
"""
    cfg = GenericRESTConfig.from_yaml(yaml_text)
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {
        "data": [
            {"t": 1_700_000_000_000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100},
            {"t": 1_700_086_400_000, "o": 1.5, "h": 2.2, "l": 1.1, "c": 2.0, "v": 200},
        ]
    }
    resp.raise_for_status.return_value = None
    session.request.return_value = resp

    conn = GenericRESTConnector(cfg, http=session)
    cap = conn.describe()
    assert cap.name == "stub"
    assert cap.supported_data_kinds == ("ohlcv",)

    req = FetchRequest(symbol="ABC", interval="1d", data_kind="ohlcv", market="custom")
    result = conn.fetch(req)
    assert result.row_count == 2
    assert result.frame["close"].to_list() == [1.5, 2.0]
    assert result.coverage_start_utc and result.coverage_end_utc
    assert result.sha256


def test_user_upload_connector_csv_roundtrip(tmp_path: Path) -> None:
    upload_id = "demo-upload"
    upload_dir = tmp_path / upload_id
    upload_dir.mkdir()
    csv = upload_dir / "klines.csv"
    csv.write_text(
        "ts,open,high,low,close,volume\n"
        "2024-01-01,1,2,0.5,1.5,100\n"
        "2024-01-02,1.5,2.5,1,2.0,200\n",
        encoding="utf-8",
    )
    reg = UploadDatasetRegistration(
        upload_id=upload_id,
        files=["klines.csv"],
        mapping=UploadFieldMapping(
            ts="ts",
            close="close",
            open="open",
            high="high",
            low="low",
            volume="volume",
            symbol_constant="DEMO",
            market="custom",
            interval="1d",
            ts_unit="date",
        ),
    )
    conn = UserUploadConnector(reg, upload_root=tmp_path)
    cap = conn.describe()
    assert cap.asset_class == "custom"
    assert conn.list_symbols() == ["DEMO"]
    result = conn.fetch(FetchRequest(symbol="DEMO", interval="1d", market="custom"))
    assert result.row_count == 2
    assert result.frame["symbol"].to_list() == ["DEMO", "DEMO"]
    assert result.frame["close"].to_list() == [1.5, 2.0]


def test_tushare_connector_health_without_token() -> None:
    conn = TushareConnector(token="")
    hc = conn.health_check()
    assert hc.ok is False
    assert "TUSHARE_TOKEN" in hc.detail


def test_binance_rest_describe_and_fetch_mocked() -> None:
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = [
        [
            1_700_000_000_000,
            "1.0",
            "2.0",
            "0.5",
            "1.5",
            "100",
            1_700_000_059_999,
            "150",
            10,
            "50",
            "75",
            "0",
        ]
    ]
    session.get.return_value = resp
    conn = BinanceRESTConnector("binanceusdm", session=session)
    cap = conn.describe()
    assert cap.realtime
    assert "ohlcv" in cap.supported_data_kinds
    res = conn.fetch(FetchRequest(symbol="BTCUSDT", interval="1m", data_kind="ohlcv"))
    assert res.row_count == 1
    assert res.frame["close"].to_list() == [1.5]


def test_binance_vision_connector_describe() -> None:
    cap = BinanceVisionConnector("binanceusdm").describe()
    assert cap.asset_class == "crypto_perp"
    assert "ohlcv" in cap.supported_data_kinds


def test_registry_describe_all_returns_metadata() -> None:
    items = registry.describe_all()
    assert any(item.get("name") == "tushare" for item in items)


@pytest.mark.parametrize("fixture_path", ["non-existent"])
def test_user_upload_missing_file_returns_empty(tmp_path: Path, fixture_path: str) -> None:
    reg = UploadDatasetRegistration(
        upload_id=fixture_path,
        files=["missing.csv"],
        mapping=UploadFieldMapping(ts="ts", close="close", symbol_constant="X"),
    )
    conn = UserUploadConnector(reg, upload_root=tmp_path)
    result = conn.fetch(FetchRequest(symbol="X", interval="1d"))
    assert result.row_count == 0
