"""加密货币 Kronos 选币策略（与回测频率一致，常见为 1h）。

对合约优先用 Kronos 打分，取前 ``long_n`` 只等权做多。

基准约定：``set_benchmark`` 应与回测页「基准」一致；报告基准曲线以页面代码为准。常用：``BTCUSDT`` / ``BTC``。
"""

from quant1.authoring.catalog import strategy_entry

# 说明：`set_benchmark` / `model_predict` / `order_target_percent` 都由
# quant1 的 JQ 运行时注入，这里故意不做普通 import。
DEFAULT_BENCHMARK = "BTCUSDT"


@strategy_entry(
    strategy_id="kronos_crypto",
    display_name="Kronos 策略（加密）",
    kind="combo",
    description="Kronos-driven crypto ranking strategy.",
)
def build_kronos_crypto(_context):
    return None


def initialize(context):
    context.long_n = 10
    # 当前基准以策略源码里的 `set_benchmark(...)` 为权威入口。
    set_benchmark(DEFAULT_BENCHMARK)


def _market_filter(symbol: str) -> bool:
    return (
        "USDT" in symbol
        or "USD" in symbol
        or symbol.endswith(".XBINANCE")
        or symbol.endswith(".XCRYPTO")
    )


def _score_from_model(symbol, context):
    try:
        return float(model_predict("kronos", symbol=symbol, context=context))
    except Exception:
        return None


def _fallback_score(bar):
    if bar is None or bar.open in (None, 0):
        return None
    return float(bar.close / bar.open - 1.0)


def _rebalance(context, data, market_filter, long_n: int) -> None:
    if not data:
        return
    symbols = sorted(s for s in data.keys() if market_filter(s))
    if not symbols:
        symbols = sorted(data.keys())

    scored = []
    for symbol in symbols:
        bar = data.get(symbol)
        score = _score_from_model(symbol, context)
        if score is None:
            score = _fallback_score(bar)
        if score is None:
            continue
        scored.append((symbol, score))

    if not scored:
        return

    scored.sort(key=lambda x: x[1], reverse=True)
    n = max(int(long_n), 1)
    long_symbols = {symbol for symbol, _ in scored[:n]}
    target_weight = 1.0 / len(long_symbols) if long_symbols else 0.0

    for symbol in symbols:
        # 用 target percent 比手工算市值更贴近当前统一 API 心智。
        order_target_percent(symbol, target_weight if symbol in long_symbols else 0.0, side="long")
        order_target_percent(symbol, 0.0, side="short")


def handle_data(context, data):
    # 每根 bar 都按当下可见币池做一次横截面打分并再平衡。
    _rebalance(context, data, _market_filter, context.long_n)
