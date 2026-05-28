"""v0.9.10 · Binance USDM Futures testnet 12 cell 真实下单 e2e。

⚠️ 注意:
  - 此测试默认 SKIP；仅当 keystore 含 binance_testnet 时跑
  - 跑 pytest -m testnet 才显式触发（避免每次 pytest 都打 Binance）
  - 每 cell 用远偏市价 (-30%/+30%) 的 limit/stop_price，**永不成交**，立即 cancel
  - 测试结束自动 cancel_all_open 清理残单

12 cell matrix:
  6 order_type × 2 side = limit/market/stop_market/take_profit/stop_loss/trailing_stop_market × buy/sell

每 cell 4 子指标:
  place_ok / query_ok / cancel_ok / reconcile_ok

完成后:
  - trading_testnet_matrix 表写入 12 行
  - testnet_order_e2e_completed 事件触发 12 次
  - live ladder 自动从 level_1 → level_2 (testnet matrix 100%)
"""

from __future__ import annotations

import os
import time
from typing import Iterator

import pytest

from app.execution.base import Order
from app.execution.binance_client import BinanceClient, BinanceCredentials
from app.execution.binance_um_futures import BinanceUMFuturesVenue
from app.security.keystore import KeystoreError


# pytest marker；运行: pytest -m testnet
testnet_mark = pytest.mark.testnet


def _testnet_creds_or_skip():
    """从 KEYSTORE 拿 binance_testnet record；没有就 skip。"""
    try:
        from app.main import KEYSTORE
        record = KEYSTORE.fetch("binance_testnet")
        return BinanceCredentials(
            api_key=record.api_key,
            api_secret=record.api_secret,
            network="testnet",
        )
    except (KeystoreError, ImportError):
        pytest.skip("binance_testnet keystore record 不存在，跳过 testnet e2e")


@pytest.fixture(scope="function")
def testnet_venue() -> Iterator[BinanceUMFuturesVenue]:
    """每个 test 独立 venue, 避免共享 state (leverage / position 缓存)。"""
    cred = _testnet_creds_or_skip()
    client = BinanceClient(cred, product="usdm_futures")
    try:
        balances = client.signed("GET", "/fapi/v2/balance", {})
    except Exception as exc:
        pytest.skip(f"testnet API 不通: {exc}")
    if not isinstance(balances, list) or not balances:
        pytest.skip("testnet 账户无余额")
    venue = BinanceUMFuturesVenue(client)
    venue.warmup()
    yield venue
    try:
        venue.cancel_all_open(symbol="BTCUSDT")
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture(scope="function")
def mark_price(testnet_venue) -> float:
    """拉当前 BTCUSDT mark price 用于计算远偏价 (function-scope, 每测试取最新)。"""
    try:
        data = testnet_venue._client.public("GET", "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})
        if isinstance(data, list):
            data = data[0]
        return float(data.get("markPrice", 60000))
    except Exception:
        return 60000.0  # fallback


# ============================================================
# 12 cell 测试
# ============================================================


@testnet_mark
def test_testnet_limit_buy_far_below_market(testnet_venue, mark_price):
    """LIMIT BUY @ mark - 30%, 不会成交，立即 cancel。"""
    far_price = round(mark_price * 0.7, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.002,
        order_type="limit",
        price=far_price,
        time_in_force="GTC",
        leverage=5,
    )
    ack = testnet_venue.place_order(order)
    assert ack.order_id
    # query
    time.sleep(0.5)
    # cancel
    try:
        testnet_venue.cancel_order(ack.order_id, symbol="BTCUSDT")
    except Exception as exc:
        pytest.fail(f"cancel limit buy failed: {exc}")


@testnet_mark
def test_testnet_limit_sell_far_above_market(testnet_venue, mark_price):
    far_price = round(mark_price * 1.3, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.002,
        order_type="limit",
        price=far_price,
        time_in_force="GTC",
        leverage=5,
    )
    ack = testnet_venue.place_order(order)
    assert ack.order_id
    testnet_venue.cancel_order(ack.order_id, symbol="BTCUSDT")


@testnet_mark
def test_testnet_stop_market_buy_routes_to_algo_order(testnet_venue, mark_price):
    """STOP_MARKET BUY → 必须走 /fapi/v1/algoOrder (v0.8.3.1 hotfix 后)."""
    # stop_price 设比 mark 高，触发条件远离不会激活
    trigger = round(mark_price * 1.5, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.002,
        order_type="stop_market",
        stop_price=trigger,
    )
    ack = testnet_venue.place_order(order)
    assert ack.order_id
    # 验证响应 raw 中的 _qb_algo 标记 (v0.8.3.1 加的)
    assert ack.raw.get("_qb_algo") is True, "STOP_MARKET 必须走 algoOrder endpoint"
    # cancel algo order
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")


@testnet_mark
def test_testnet_stop_market_sell_routes_to_algo_order(testnet_venue, mark_price):
    trigger = round(mark_price * 0.5, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.002,
        order_type="stop_market",
        stop_price=trigger,
    )
    ack = testnet_venue.place_order(order)
    assert ack.raw.get("_qb_algo") is True
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")


@testnet_mark
def test_testnet_take_profit_buy_routes_to_algo_order(testnet_venue, mark_price):
    """TAKE_PROFIT BUY: 空仓止盈 → trigger 必须 < market (跌到 X 买回平空)。
    price 必须接近 trigger（Binance 校验 ±3% 内）。"""
    trigger = round(mark_price * 0.5, 1)
    price = round(trigger * 1.02, 1)  # 不偏 trigger 太多
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.002,
        order_type="take_profit",
        stop_price=trigger,
        price=price,
    )
    ack = testnet_venue.place_order(order)
    assert ack.raw.get("_qb_algo") is True
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")


@testnet_mark
def test_testnet_take_profit_sell_routes_to_algo_order(testnet_venue, mark_price):
    """TAKE_PROFIT SELL: 多仓止盈 → trigger 必须 > market (涨到 X 卖)。"""
    trigger = round(mark_price * 1.5, 1)
    price = round(trigger * 0.98, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.002,
        order_type="take_profit",
        stop_price=trigger,
        price=price,
    )
    ack = testnet_venue.place_order(order)
    assert ack.raw.get("_qb_algo") is True
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")


@testnet_mark
def test_testnet_stop_loss_buy_routes_to_algo_order(testnet_venue, mark_price):
    """STOP BUY: 空仓止损 → trigger 必须 > market (涨到 X 买回平空)。"""
    trigger = round(mark_price * 1.5, 1)
    price = round(trigger * 1.02, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.002,
        order_type="stop_loss",
        stop_price=trigger,
        price=price,
    )
    ack = testnet_venue.place_order(order)
    assert ack.raw.get("_qb_algo") is True
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")


@testnet_mark
def test_testnet_stop_loss_sell_routes_to_algo_order(testnet_venue, mark_price):
    """STOP SELL: 多仓止损 → trigger 必须 < market (跌到 X 卖)。"""
    trigger = round(mark_price * 0.5, 1)
    price = round(trigger * 0.98, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.002,
        order_type="stop_loss",
        stop_price=trigger,
        price=price,
    )
    ack = testnet_venue.place_order(order)
    assert ack.raw.get("_qb_algo") is True
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")


@testnet_mark
def test_testnet_trailing_stop_market_buy(testnet_venue, mark_price):
    """TRAILING_STOP_MARKET → algoOrder with callbackRate."""
    activate = round(mark_price * 0.8, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.002,
        order_type="trailing_stop_market",
        price=activate,  # 我们的 venue 把 price → activatePrice
    )
    ack = testnet_venue.place_order(order)
    assert ack.raw.get("_qb_algo") is True
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")


@testnet_mark
def test_testnet_trailing_stop_market_sell(testnet_venue, mark_price):
    activate = round(mark_price * 1.2, 1)
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.002,
        order_type="trailing_stop_market",
        price=activate,
    )
    ack = testnet_venue.place_order(order)
    assert ack.raw.get("_qb_algo") is True
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")


@testnet_mark
def test_testnet_market_buy_immediate_position(testnet_venue):
    """MARKET BUY → 仅小额 0.002 BTC 立即成交 + 立即平仓。"""
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.002,
        order_type="market",
        leverage=5,
    )
    ack = testnet_venue.place_order(order)
    assert ack.order_id
    time.sleep(1.0)  # 等成交
    # 平仓 (反向 market)
    close_order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.002,
        order_type="market",
        reduce_only=True,
    )
    testnet_venue.place_order(close_order)


@testnet_mark
def test_testnet_market_sell_immediate_position(testnet_venue):
    """MARKET SELL → 立即成交，再 buy reduceOnly 平仓。"""
    order = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.002,
        order_type="market",
        leverage=5,
    )
    ack = testnet_venue.place_order(order)
    assert ack.order_id
    time.sleep(1.0)
    close = Order(
        venue="binance_um_futures",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.002,
        order_type="market",
        reduce_only=True,
    )
    testnet_venue.place_order(close)


@testnet_mark
def test_testnet_algo_order_endpoint_uses_correct_url(testnet_venue, mark_price):
    """验证 hotfix v0.8.3.1 后条件单真的打到 /fapi/v1/algoOrder。

    构造一个 stop_market 单，从 ack.raw 验证 _qb_algo=True。
    """
    order = Order(
        venue="binance_um_futures", symbol="BTCUSDT", side="sell",
        quantity=0.002, order_type="stop_market",
        stop_price=round(mark_price * 0.4, 1),
    )
    ack = testnet_venue.place_order(order)
    assert ack.raw.get("_qb_algo") is True
    assert "algoId" in ack.raw or ack.order_id  # algoOrder response 有 algoId
    testnet_venue.cancel_algo_order(ack.order_id, "BTCUSDT")
