"""模拟台 **testnet 真喂** bar/mark provider —— 加密交易所 testnet 实时行情源（DS-4「都做」可选档）。

定位（与 replay_provider 并列档，扩展不替换）：
  · `replay_provider.ReplayBarProvider` = 零依赖兜底（真捆样本回放 / 确定性合成游走），无 key 也能跑。
  · 本模块 `TestnetBarProvider`   = **配 testnet key 时**才上的可选档——喂**交易所 testnet 真实时 bar**
    （Binance USDM Futures testnet 公共 klines / premiumIndex mark），让模拟台跑出真行情驱动的净值。

⚠️【治理铁律 · 与 R10 / D-T021-3 / INV-3 单一源一致】：
  1. **key 不进 LLM、不进 agent 提示词**：testnet 行情走【公共】端点（klines / premiumIndex），**无需签名、
     无需 api_secret**。本模块**仅查 keystore 名字存在性**（`list_names`，镜像 `KeyBroker.has_key`「仅查名字、
     不 fetch 本体」INV-3），**绝不 `fetch()` 取出明文 secret**。REST client 用**空 creds**(`api_key=""`,
     `api_secret=""`，复用 `LeasedBinanceVenue._public_client` 既有无 key 接缝)拼 base_url，**结构上无 secret
     可泄**——provider 对象 / run record / status dict / 异常串里都不存在明文 key。
  2. **永走模拟撮合、绝不触 live 下单**：本模块**只读公共行情**(klines/marks)，**从不**调 `place_order` /
     `signed` / `assert_safe_startup`（后者要签名=要 secret，故意不用——市场数据无需鉴权）。注入后仍由
     `PaperScheduler.tick_once → venue.feed_bar`（模拟撮合）/ `mtm_once → venue.mark_to_market` 消费，**不经
     OrderGuard、不下真单**。testnet 假钱也永不调真 live 路径。
  3. **fail-open 留痕（D-T021-3：CRYPTO_TESTNET 假钱不过度工程化）**：testnet 连接/网络失败 →
     `make_testnet_provider` 返 `(None, 降级原因)`，**绝不静默假装连上**；调用方（desk.register_run）据此
     **回退 replay_provider 兜底**并诚实标 `degrade_reason` + source（**回退态绝不标成 testnet 真喂**，§3）。
     这是【市场数据连接】的 fail 策略（与 D-T021-3 下单防重放台 fail 模式同精神：testnet 不过度工程化、
     不破坏既有 testnet 基线），**非** D-T021-3 本体（那是下单路径），故障绝不硬停 paper run。
  4. **crypto only**：testnet 仅 crypto；A股恒走兜底（永不 testnet、永拒 live），市场守门**先于**任何
     keystore/网络触碰。

无真 testnet key 时本模块不被启用（`make_testnet_provider` 返 None）——真 testnet 端到端验证待用户插 key
（见 docs/binance-security-guide.md「模拟台 testnet 真喂」节）。对抗测试用 mock/fake client 验注入接线。

与 ReplayBarProvider **同形 duck-typed 接口**（next_bar / current_marks / reset / source / first_price /
source_for），故 `make_bar_provider` / `make_mark_provider` / `seed_positions(provider=)` / `prime_run` /
`status` 全部**复用不改**（desk.register_run 注入即生效）。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .scheduler import MarketKind


logger = logging.getLogger(__name__)


# ── source 标签（诚实区分 bar 来源；与 simulated_source 同义域）──
TESTNET_SOURCE = "binance_testnet_live"  # 交易所 testnet 真实时行情（公共端点，非实盘真钱、非合成）
TESTNET_REALTIME_SOURCE = TESTNET_SOURCE
TESTNET_UNAVAILABLE_SOURCE = "testnet_unavailable_replay_fallback"

DEFAULT_TESTNET_KEYSTORE_NAME = "binance_testnet"
_DEFAULT_INTERVAL = "1d"
_DEFAULT_LENGTH = 64  # 与 ReplayBarProvider.length 同形：prime ticks(≤16)≪length，截断足够


@runtime_checkable
class TestnetMarketClient(Protocol):
    """testnet 行情 REST 接缝（可注入）——对抗测试注 mock/fake，无需真 testnet key/网络。

    **只读公共行情**：实现**绝不**暴露下单 / 签名方法到本接口（下单永走 OrderGuard live 路径，与此无关）。
    """

    def fetch_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        """公共 klines（Binance: [[openTime, open, high, low, close, volume, ...], ...]）。无数据返 []。"""
        ...

    def fetch_mark(self, symbol: str) -> float | None:
        """公共 mark（Binance premiumIndex markPrice）。取不到返 None。"""
        ...


class BinanceTestnetMarketClient:
    """真 testnet 行情 client：包 `BinanceClient` 的【公共】端点（klines / premiumIndex）。

    **无 key**：用空 creds 拼 base_url（复用 `LeasedBinanceVenue._public_client` 接缝），只调 `client.public`
    （无签名、无 X-MBX-APIKEY）。**故意不**持 api_secret——结构上无明文 key 可泄（R10/INV-3）。
    network 钉死 testnet（base_url=https://testnet.binancefuture.com），绝不静默落到 mainnet 真行情。
    """

    def __init__(self, *, product: str = "usdm_futures", timeout_s: float = 2.0) -> None:
        from ..execution.binance_client import BinanceClient, BinanceCredentials

        # 空 creds：公共端点无需 key（structurally no secret to leak）。network 显式 testnet。
        cred = BinanceCredentials(api_key="", api_secret="", network="testnet")
        self._client = BinanceClient(cred, product=product)  # type: ignore[arg-type]
        self._product = product
        # 紧超时：fail-open 要快跳（不拖垮 register / 首屏 <2s）。
        try:
            self._client._http.request = _with_timeout(self._client._http.request, timeout_s)  # type: ignore[attr-defined]  # noqa: SLF001
        except Exception:  # noqa: BLE001  超时包装失败不阻断（底层 public 自带 timeout=10 兜底）
            pass

    @property
    def base_url(self) -> str:
        return self._client.base_url

    def fetch_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        path = "/fapi/v1/klines" if self._product == "usdm_futures" else "/api/v3/klines"
        data = self._client.public("GET", path, {"symbol": symbol.upper(), "interval": interval, "limit": limit})
        return data if isinstance(data, list) else []

    def fetch_mark(self, symbol: str) -> float | None:
        try:
            if self._product == "usdm_futures":
                data = self._client.public("GET", "/fapi/v1/premiumIndex", {"symbol": symbol.upper()})
                if isinstance(data, list):
                    data = data[0] if data else {}
                mark = float((data or {}).get("markPrice", 0) or 0)
            else:
                data = self._client.public("GET", "/api/v3/ticker/price", {"symbol": symbol.upper()})
                mark = float((data or {}).get("price", 0) or 0)
            return mark if mark > 0 else None
        except Exception:  # noqa: BLE001  公共取价失败 → None（mark 回退末根 close）
            return None


def _with_timeout(request_fn: Callable[..., Any], timeout_s: float) -> Callable[..., Any]:
    """给 requests.Session.request 套紧超时（除非调用方显式传更短的）。"""

    def _wrapped(method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", timeout_s)
        return request_fn(method, url, **kwargs)

    return _wrapped


def _parse_close(kline: list[Any]) -> float | None:
    """Binance kline → close（index 4）。解析失败返 None（诚实跳过，不造数）。"""

    try:
        return float(kline[4])
    except (IndexError, TypeError, ValueError):
        return None


@dataclass
class TestnetBarProvider:
    """testnet 真喂 provider：每 symbol 一条 **testnet 公共 klines 真 close 序列**（注册时一次性快照）。

    与 ReplayBarProvider 同形 duck-typed 接口；source 恒 `binance_testnet_live`（诚实标真 testnet 行情）。
    **快照语义**（幂等关键）：构造时一次性拉 klines 存内存数值序列；`next_bar` 推游标、`reset` 仅游标归零
    （**绝不**重拉网络）——故 `prime_run` 复位再跑产同一序列（与 ReplayBarProvider 幂等同形）。
    `current_marks` 用游标处 close（快照回放语义，MTM 随回放进度移动）。线程安全。
    """

    __test__ = False  # 名以 Test* 起：显式告知 pytest **不**当测试类收集（它是产品 provider，非测试）。

    symbols: list[str]
    _client: TestnetMarketClient
    interval: str = _DEFAULT_INTERVAL
    length: int = _DEFAULT_LENGTH
    fetch_errors: int = 0  # snapshot_klines 期间拉异常（连接失败）计数——factory 据此诚实区分降级原因
    _series: dict[str, list[float]] = field(default_factory=dict)
    _cursor: dict[str, int] = field(default_factory=dict)
    _first_price: dict[str, float] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def snapshot_klines(self) -> int:
        """一次性拉各 symbol 的 testnet 公共 klines 存内存（构造后由 factory 调，**网络在锁外**）。

        返回成功建序列的 symbol 数。任一 symbol **拉异常**（连接失败）→ 跳过该 symbol 并计 `fetch_errors`
        （factory 据此区分「连接失败」vs「行情空」诚实留痕）；**空数据**（无异常）→ 跳过（不崩、不造数）。
        """

        total = 0
        self.fetch_errors = 0
        for sym in self.symbols:
            try:
                klines = self._client.fetch_klines(sym, self.interval, self.length)
            except Exception as exc:  # noqa: BLE001  单 symbol 拉异常=连接失败 → 跳过 + 计数（聚合层判 bars>0）
                logger.warning("testnet klines 拉取失败 symbol=%s: %s", sym, exc)
                self.fetch_errors += 1
                continue
            closes = [c for c in (_parse_close(k) for k in (klines or [])) if c is not None and c > 0]
            if not closes:
                continue
            series = [round(float(c), 4) for c in closes[: self.length]]
            with self._lock:
                self._series[sym] = series
                self._first_price[sym] = series[0]
                self._cursor[sym] = 0
            total += 1
        return total

    @property
    def has_data(self) -> bool:
        with self._lock:
            return any(self._series.values())

    @property
    def source(self) -> str:
        """run 级数据来源标签：恒 `binance_testnet_live`（真 testnet 行情；不混源——无样本 symbol 直接不建序列）。"""

        return TESTNET_SOURCE

    def source_for(self, symbol: str) -> str:
        return TESTNET_SOURCE

    def first_price(self, symbol: str) -> float:
        """该 symbol 序列首价（testnet 真 close ~60000）。seed_positions 反推 qty 用（防 P&L 尺度失真）。"""

        with self._lock:
            return self._first_price.get(symbol, 100.0)

    def reset(self) -> None:
        """游标归零（**不重拉网络**）——让 prime_run 可重复跑出同一快照窗口（幂等）。"""

        with self._lock:
            for sym in self._series:
                self._cursor[sym] = 0

    def next_bar(self, symbol: str) -> dict[str, Any] | None:
        """下一根 bar（OHLC + ts + source）。耗尽则恒返末根 close（停更，绝不造新数据）。"""

        with self._lock:
            series = self._series.get(symbol)
            if not series:
                return None
            i = self._cursor[symbol]
            if i >= len(series):
                i = len(series) - 1
            close = series[i]
            prev = series[i - 1] if i > 0 else close
            self._cursor[symbol] = min(i + 1, len(series))
            high = max(prev, close) * 1.001
            low = min(prev, close) * 0.999
            return {
                "symbol": symbol,
                "open": round(prev, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "ts": f"testnet-{i:04d}",
                "source": TESTNET_SOURCE,
            }

    def current_marks(self, symbols: list[str]) -> dict[str, float]:
        """当前 mark = 各 symbol **游标处 close**（与 ReplayBarProvider 同语义）——MTM 随回放进度移动。

        为何用游标 close 而非实时 premiumIndex：本 provider 是**快照回放**模型（snapshot klines + tick 推游标，
        prime 驱动 N tick 跑过捕获窗口）；MTM 应跟随**刚喂入那根 bar** 的 close，反映被回放的 testnet 真行情
        进度。单一实时 spot mark 会把净值钉死在一个常数、抹掉回放进度（与 prime 语义不符）。实时 premiumIndex
        仅在未来「真正前向常驻跑」时有意义（`fetch_mark` 留作该用途的接缝，本快照回放流程不调用）。
        """

        with self._lock:
            out: dict[str, float] = {}
            for sym in symbols:
                series = self._series.get(sym)
                if not series:
                    continue
                i = min(max(self._cursor[sym] - 1, 0), len(series) - 1)
                out[sym] = series[i]
            return out


def make_testnet_provider(
    market: MarketKind,
    symbols: list[str],
    *,
    keystore: Any,
    keystore_name: str = DEFAULT_TESTNET_KEYSTORE_NAME,
    client_factory: Callable[[], TestnetMarketClient] | None = None,
    interval: str = _DEFAULT_INTERVAL,
    length: int = _DEFAULT_LENGTH,
) -> tuple[TestnetBarProvider | None, str | None]:
    """配 testnet key 时建 testnet 真喂 provider；否则/失败 → (None, 诚实降级原因)（fail-open）。

    分流（**市场守门先于一切**）：
      1. `market != "crypto"`        → (None, "testnet 仅支持 crypto …")（A股永不 testnet）。
      2. 无 symbols                  → (None, "无标的 …")。
      3. **key 不存在**(`keystore.list_names` 仅查名、**绝不 fetch 本体** INV-3) → (None, "未配 testnet key …")。
      4. 建 client + 拉 klines（网络；**调用方在锁外调**）→ 任一异常/拉到 0 bar → (None, "testnet 连接失败 …")。
      5. 成功（bars>0）              → (provider, None)。

    **绝不**在此 `keystore.fetch()` 取明文 key（公共行情无需鉴权）；**绝不** assert_safe_startup（要签名=要
    secret，市场数据不需）。失败恒 fail-open 返 None 让 desk 回退兜底，绝不抛错硬停 paper run。
    """

    # ① 市场守门（先于 keystore/网络）：testnet 仅 crypto。
    if market != "crypto":
        return None, f"testnet 仅支持 crypto（market={market!r} 走兜底，A股永不 testnet）"
    syms = [str(s) for s in (symbols or []) if str(s).strip()]
    if not syms:
        return None, "无标的，testnet provider 不建（走兜底）"

    # ② 凭据门：仅查名字存在性（镜像 KeyBroker.has_key「不 fetch 本体」INV-3）——绝不取明文 secret。
    if not _keystore_has_name(keystore, keystore_name):
        return None, f"未配 testnet key（keystore 无 {keystore_name!r}）——诚实回退兜底，不伪装连真"

    # ③ 建 client（无 key 公共 client）+ 一次性快照 klines（网络）。任一失败 → fail-open 返 None。
    try:
        client = client_factory() if client_factory is not None else BinanceTestnetMarketClient()
        provider = TestnetBarProvider(symbols=syms, _client=client, interval=interval, length=length)
        n = provider.snapshot_klines()
    except Exception as exc:  # noqa: BLE001  构造/factory 异常 → fail-open（留痕、回退兜底）
        return None, f"testnet 连接失败（{type(exc).__name__}: {exc}）——fail-open 回退兜底（留痕）"
    if n <= 0 or not provider.has_data:
        # 区分诚实降级原因：有拉异常 → 连接失败；纯空数据 → 行情空（symbol 无对应市场）。
        if getattr(provider, "fetch_errors", 0) > 0:
            return None, "testnet 连接失败（klines 拉取异常）——fail-open 回退兜底（留痕）"
        return None, "testnet 拉到 0 bar（行情空/symbol 无对应市场）——诚实回退兜底，不空跑伪装"
    return provider, None


def _keystore_has_name(keystore: Any, keystore_name: str) -> bool:
    """key 是否已配置——**仅查名字、不 fetch 本体**（INV-3：存在性预检绝不物化 key 到内存）。

    镜像 `KeyBroker.has_key` 语义：后端错/无 list_names → 视为未配置（fail-safe，不抛、不取 secret）。
    """

    if not keystore_name:
        return False
    try:
        return keystore_name in keystore.list_names()
    except Exception:  # noqa: BLE001  后端错 → 视为未配置（fail-safe）
        return False


class _PublicClientAdapter:
    """Adapt the older BinanceClient-like public() seam to TestnetMarketClient."""

    def __init__(self, client: Any, *, product: str) -> None:
        self._client = client
        self._product = product

    def fetch_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        path = "/fapi/v1/klines" if self._product == "usdm_futures" else "/api/v3/klines"
        data = self._client.public("GET", path, {"symbol": symbol.upper(), "interval": interval, "limit": limit})
        return data if isinstance(data, list) else []

    def fetch_mark(self, symbol: str) -> float | None:
        try:
            if self._product == "usdm_futures":
                data = self._client.public("GET", "/fapi/v1/premiumIndex", {"symbol": symbol.upper()})
                if isinstance(data, list):
                    data = data[0] if data else {}
                mark = float((data or {}).get("markPrice", 0) or 0)
            else:
                data = self._client.public("GET", "/api/v3/ticker/price", {"symbol": symbol.upper()})
                mark = float((data or {}).get("price", 0) or 0)
            return mark if mark > 0 else None
        except Exception:  # noqa: BLE001
            return None


@dataclass
class BinanceTestnetBarProvider(TestnetBarProvider):
    def current_marks(self, symbols: list[str]) -> dict[str, float]:
        marks: dict[str, float] = {}
        for symbol in symbols:
            try:
                mark = self._client.fetch_mark(symbol)
            except Exception:  # noqa: BLE001
                mark = None
            if mark is not None:
                marks[symbol] = mark
        if marks:
            return marks
        return super().current_marks(symbols)


def make_binance_testnet_provider(
    *,
    symbols: list[str],
    keystore: Any,
    key_name: str | None,
    product: str = "usdm_futures",
    interval: str = "1m",
    client_factory: Callable[[Any, str], Any] | None = None,
) -> tuple[TestnetBarProvider | None, dict[str, Any]]:
    """Compatibility status API for callers that need explicit provider diagnostics.

    The production desk path still uses `make_testnet_provider`, which checks key
    presence without fetching secret material. This path exists for API/status
    reporting and test injection where the caller supplies a client seam.
    """

    if not key_name:
        return None, {
            "requested_provider": TESTNET_REALTIME_SOURCE,
            "active_provider": TESTNET_UNAVAILABLE_SOURCE,
            "connected": False,
            "credential_configured": False,
            "fallback_reason": "missing_testnet_key_name",
        }
    try:
        configured_names = set(keystore.list_names())
    except Exception:  # noqa: BLE001
        configured_names = set()
    if key_name not in configured_names:
        return None, {
            "requested_provider": TESTNET_REALTIME_SOURCE,
            "active_provider": TESTNET_UNAVAILABLE_SOURCE,
            "connected": False,
            "credential_configured": False,
            "fallback_reason": "testnet_key_not_found",
        }
    try:
        if client_factory is not None:
            # Public market data needs no secret.  The compatibility seam gets
            # no credential record so test/status code cannot accidentally
            # retain key material.
            client = client_factory(None, product)
        else:
            from ..execution.binance_client import BinanceClient, BinanceCredentials

            client = BinanceClient(
                BinanceCredentials(api_key="", api_secret="", network="testnet"),
                product=product,  # type: ignore[arg-type]
            )
        provider = BinanceTestnetBarProvider(
            symbols=[str(symbol) for symbol in symbols],
            _client=_PublicClientAdapter(client, product=product),
            interval=interval,
        )
        n = provider.snapshot_klines()
    except Exception as exc:  # noqa: BLE001
        return None, {
            "requested_provider": TESTNET_REALTIME_SOURCE,
            "active_provider": TESTNET_UNAVAILABLE_SOURCE,
            "connected": False,
            "credential_configured": True,
            "fallback_reason": f"testnet_provider_unavailable:{type(exc).__name__}",
        }
    if n <= 0 or not provider.has_data:
        return None, {
            "requested_provider": TESTNET_REALTIME_SOURCE,
            "active_provider": TESTNET_UNAVAILABLE_SOURCE,
            "connected": False,
            "credential_configured": True,
            "fallback_reason": "testnet_provider_unavailable:no_bars",
        }
    return provider, {
        "requested_provider": TESTNET_REALTIME_SOURCE,
        "active_provider": TESTNET_REALTIME_SOURCE,
        "connected": True,
        "credential_configured": True,
        "permission_checked": False,
        "network": "testnet",
        "product": product,
        "warnings": ["public market-data feed does not inspect API-key permissions"],
    }


__all__ = [
    "BinanceTestnetBarProvider",
    "TESTNET_SOURCE",
    "TESTNET_REALTIME_SOURCE",
    "TESTNET_UNAVAILABLE_SOURCE",
    "DEFAULT_TESTNET_KEYSTORE_NAME",
    "BinanceTestnetMarketClient",
    "TestnetBarProvider",
    "TestnetMarketClient",
    "make_binance_testnet_provider",
    "make_testnet_provider",
]
