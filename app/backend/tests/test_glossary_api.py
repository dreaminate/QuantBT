"""v0.8.4 Day 2 · Glossary API endpoint 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_glossary_list_returns_array(client: TestClient):
    r = client.get("/api/glossary")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # 至少包含 3 条样例（sharpe_ratio / pbo / deflated_sharpe）
    slugs = {x["slug"] for x in data}
    assert {"sharpe_ratio", "pbo", "deflated_sharpe"} <= slugs


def test_glossary_list_shape(client: TestClient):
    r = client.get("/api/glossary")
    data = r.json()
    for item in data:
        assert "slug" in item
        assert "display" in item
        assert "level" in item
        assert "category" in item
        assert "aliases" in item
        assert "levels_available" in item


def test_glossary_list_filter_by_category(client: TestClient):
    r = client.get("/api/glossary?category=metric")
    data = r.json()
    assert all(x["category"] == "metric" for x in data)


def test_glossary_list_filter_by_level(client: TestClient):
    r = client.get("/api/glossary?level=advanced")
    data = r.json()
    assert all(x["level"] == "advanced" for x in data)


def test_glossary_get_by_slug(client: TestClient):
    r = client.get("/api/glossary/sharpe_ratio")
    assert r.status_code == 200
    data = r.json()
    assert data["slug"] == "sharpe_ratio"
    assert "l1" in data and "l2" in data and "l3" in data and "l4" in data
    assert "frontmatter" in data
    assert data["frontmatter"]["term"] == "sharpe_ratio"


def test_glossary_get_by_alias(client: TestClient):
    """alias 命中：'夏普' 应该返回 sharpe_ratio。"""

    r = client.get("/api/glossary/夏普")
    assert r.status_code == 200
    assert r.json()["slug"] == "sharpe_ratio"


def test_glossary_get_case_insensitive_alias(client: TestClient):
    r = client.get("/api/glossary/SHARPE")
    assert r.status_code == 200
    assert r.json()["slug"] == "sharpe_ratio"


def test_glossary_get_404_with_suggestions(client: TestClient):
    r = client.get("/api/glossary/sharp_typo")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["error"] == "term_not_found"
    assert detail["term"] == "sharp_typo"
    # 'sharp' 是 'sharpe_ratio' 的前缀 → 建议含 sharpe_ratio
    assert "sharpe_ratio" in detail["suggestions"]


def test_glossary_get_progressive_disclosure_l1(client: TestClient):
    """level=l1 只返 L1，不含 L2/L3/L4。"""

    r = client.get("/api/glossary/sharpe_ratio?level=l1")
    data = r.json()
    assert "l1" in data
    assert "l2" not in data
    assert "l3" not in data
    assert "l4" not in data


def test_glossary_get_progressive_disclosure_l2(client: TestClient):
    r = client.get("/api/glossary/sharpe_ratio?level=l2")
    data = r.json()
    assert "l1" in data and "l2" in data
    assert "l3" not in data and "l4" not in data


def test_glossary_get_invalid_level_returns_full(client: TestClient):
    """level 参数非法时 fallback 返全部。"""

    r = client.get("/api/glossary/sharpe_ratio?level=bogus")
    data = r.json()
    assert "l1" in data and "l4" in data  # 全 returned


def test_glossary_meta(client: TestClient):
    r = client.get("/api/glossary_meta")
    assert r.status_code == 200
    data = r.json()
    assert "count" in data
    assert data["count"] >= 3
    assert "by_category" in data
    assert "by_level" in data
    assert "related_closure_ok" in data
    # baseline 30 条没全到位前 closure 必然 False，但不影响 endpoint 成功
    assert isinstance(data["related_closure_ok"], bool)


def test_glossary_meta_aggregates_categories(client: TestClient):
    r = client.get("/api/glossary_meta")
    data = r.json()
    # 至少 metric category 应有内容（sharpe_ratio / deflated_sharpe 都是 metric）
    assert data["by_category"].get("metric", 0) >= 2


def test_glossary_l1_is_short_for_tooltip(client: TestClient):
    """L1 必须够短做 hover tooltip。"""

    r = client.get("/api/glossary/sharpe_ratio?level=l1")
    l1 = r.json()["l1"]
    assert len(l1) <= 60


def test_glossary_pbo_loaded(client: TestClient):
    r = client.get("/api/glossary/pbo")
    assert r.status_code == 200
    data = r.json()
    assert data["frontmatter"]["level"] == "intermediate"
    # PBO L3 必须包含阈值表（>0.6 / >0.5 等关键阈值）
    assert "0.6" in data["l3"] or "0.5" in data["l3"]


def test_glossary_dsr_loaded(client: TestClient):
    r = client.get("/api/glossary/dsr")  # 用 alias 命中
    assert r.status_code == 200
    assert r.json()["slug"] == "deflated_sharpe"
