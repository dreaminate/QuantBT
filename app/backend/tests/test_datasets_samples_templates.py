"""v0.8.7 · 样例数据集 + 策略模板测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.datasets import (
    STRATEGY_TEMPLATES,
    generate_ashare_etf_sample,
    generate_btc_perp_sample,
    generate_eth_perp_sample,
    get_template,
    list_samples,
    list_templates,
    load_sample,
)
from app.main import app


# ============================================================
# samples
# ============================================================


def test_btc_sample_deterministic():
    """同 seed 应生成完全相同的数据 (复现性)。"""
    df1 = generate_btc_perp_sample(days=30)
    df2 = generate_btc_perp_sample(days=30)
    assert df1.equals(df2)


def test_btc_sample_shape():
    df = generate_btc_perp_sample(days=365)
    assert df.height == 365
    expected_cols = {"t_index", "symbol", "open", "high", "low", "close", "volume", "funding_rate"}
    assert expected_cols <= set(df.columns)


def test_btc_high_ge_low():
    """OHLC 内在约束。"""
    df = generate_btc_perp_sample(days=100)
    assert (df["high"] >= df["low"]).all()


def test_eth_different_from_btc():
    btc = generate_btc_perp_sample(days=50)
    eth = generate_eth_perp_sample(days=50)
    # 用不同 seed，价格序列不同
    assert btc["close"].to_list() != eth["close"].to_list()


def test_ashare_etf_multi_symbol():
    df = generate_ashare_etf_sample(days=252)
    symbols = set(df["symbol"].unique().to_list())
    assert {"510300", "510500", "510050", "510880"} <= symbols
    # 每个 symbol 各 252 行
    assert df.height == 252 * 4


def test_list_samples_returns_three():
    out = list_samples()
    assert len(out) == 3
    ids = {s["sample_id"] for s in out}
    assert {"btc_perp_daily_365d", "eth_perp_daily_365d", "ashare_etf_daily_252d"} == ids


def test_load_sample_returns_dataframe():
    df = load_sample("btc_perp_daily_365d")
    assert df is not None
    assert df.height == 365


def test_load_sample_unknown_returns_none():
    assert load_sample("not_a_sample") is None


# ============================================================
# templates
# ============================================================


def test_three_templates_registered():
    assert len(STRATEGY_TEMPLATES) == 3
    assert "btc_momentum_v1" in STRATEGY_TEMPLATES
    assert "eth_funding_arb_v1" in STRATEGY_TEMPLATES
    assert "ashare_etf_rotation_v1" in STRATEGY_TEMPLATES


def test_template_code_contains_emit_result():
    """每个模板必须以 quantbt.emit_result 结尾。"""
    for t in STRATEGY_TEMPLATES.values():
        assert "quantbt.emit_result" in t.code, f"{t.template_id} 缺 emit_result 调用"


def test_template_expected_metrics_present():
    for t in STRATEGY_TEMPLATES.values():
        assert "sharpe_min" in t.expected_metrics
        assert "pbo_max" in t.expected_metrics


def test_get_template():
    t = get_template("btc_momentum_v1")
    assert t is not None
    assert t.asset_class == "crypto_perp"


def test_get_unknown_template_returns_none():
    assert get_template("not_a_template") is None


# ============================================================
# API
# ============================================================


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_api_list_samples(client: TestClient):
    r = client.get("/api/datasets/samples")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3


def test_api_sample_preview(client: TestClient):
    r = client.get("/api/datasets/samples/btc_perp_daily_365d/preview?rows=10")
    assert r.status_code == 200
    data = r.json()
    assert data["total_rows"] == 365
    assert len(data["rows"]) == 10


def test_api_sample_preview_404(client: TestClient):
    r = client.get("/api/datasets/samples/bogus/preview")
    assert r.status_code == 404


def test_api_list_templates(client: TestClient):
    r = client.get("/api/strategies/templates")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    # 列表不返完整 code，只返 code_length
    for t in data:
        assert "code_length" in t
        assert "code" not in t


def test_api_template_detail(client: TestClient):
    r = client.get("/api/strategies/templates/btc_momentum_v1")
    assert r.status_code == 200
    data = r.json()
    assert data["template_id"] == "btc_momentum_v1"
    assert "quantbt.emit_result" in data["code"]


def test_api_template_detail_404(client: TestClient):
    r = client.get("/api/strategies/templates/bogus")
    assert r.status_code == 404
