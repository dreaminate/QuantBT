"""数据平台 v2 · P3 数据源/字段 REST 端点接线测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_fields_endpoint_structure() -> None:
    r = client.get("/api/fields", params={"market": "binanceusdm"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"canonical", "freeform"}


def test_sources_endpoint_returns_tree() -> None:
    r = client.get("/api/sources")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_source_toggle_endpoints() -> None:
    r = client.put("/api/sources/market/stocks_cn/enabled", params={"enabled": False, "kind": "official"})
    assert r.status_code == 200
    assert r.json()["market"] == "stocks_cn"
    assert r.json()["enabled"] is False

    r2 = client.put("/api/sources/tushare/enabled", params={"market": "stocks_cn", "enabled": True})
    assert r2.status_code == 200
    assert r2.json()["enabled"] is True


def test_infer_and_apply_mapping_endpoints() -> None:
    r = client.post("/api/fields/infer-mapping", json={"columns": ["close", "px_unknown"], "market": "stocks_cn"})
    assert r.status_code == 200
    body = r.json()
    assert "suggestions" in body and "canonical_options" in body
    by = {s["raw_column"]: s for s in body["suggestions"]}
    assert by["close"]["suggested_field_id"] == "close"
    assert by["px_unknown"]["is_freeform"]

    r2 = client.post(
        "/api/fields/mapping",
        json={"source": "user_t", "data_kind": "ohlcv", "mappings": [{"raw_column": "px", "field_id": "close"}]},
    )
    assert r2.status_code == 200
    assert r2.json()["applied"] == 1
