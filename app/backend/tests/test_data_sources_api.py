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


def test_fields_catalog_endpoint() -> None:
    r = client.get("/api/fields/catalog")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_data_package_manifest_endpoint() -> None:
    r = client.get("/api/data-packages/manifest")
    assert r.status_code == 200
    body = r.json()
    assert body["channel"] == "official-data"
    assert "data_version" in body and "files" in body
    assert "official_fields" in body  # 供客户端合并的官方字段定义


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
