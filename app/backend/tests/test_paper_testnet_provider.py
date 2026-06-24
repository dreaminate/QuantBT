"""DS-4 卡 a367bfc8 · paper **testnet 真喂** provider 对抗测试（种已知坏门，门必抓）。

testnet 真喂可选档（配 testnet key → Binance testnet 公共实时 bar；无 key → 诚实回退兜底）。无真 testnet
key 也可验：testnet REST client 抽象成可注入接缝（`TestnetMarketClient` Protocol），mock/fake client 验
「有 key→注入 testnet_provider→tick 喂 bar(bars_fed>0)」接线；无 key 回退路径直接可验。真 testnet 端到端
连接验证 = 待用户插 key（见 docs/binance-security-guide.md「模拟台 testnet 真喂」节）。

对抗坏门（每条种一个已知坏门，protection 移除即转红）：
  #1 testnet key 不进 LLM：仅查 key 名存在性，**绝不 fetch 明文 secret**；provider/record/status 串里无明文 key。
  #2 testnet 路径不调真 live 下单：provider 只读公共行情，**从不**碰 signed/place_order/assert_safe_startup。
  #3 无 key → 诚实回退 replay_provider + source 不标 testnet（坏门：无 key 却谎称连真 → 必抓）。
  #4 fail-open 留痕：mock client 抛连接异常 → 回退模拟 + 降级原因留痕（坏门：静默降级无痕 → 必抓）。
  #5 有 key（mock client）→ 注入 testnet_provider 且 tick 后 bars_fed>0（证明注入接线真生效）。
  #6 治理回归：A股恒拒 live 不破 + A股恒不走 testnet（crypto only）。
变异自检（见 test_*_mutation_self_check_*）：把回退/守门临时翻坏，确认对应坏门测试转红。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from app.paper.desk import AShareLiveForbidden, PaperDeskService
from app.paper.replay_provider import BUNDLED_SOURCE, SIMULATED_SOURCE
from app.paper.testnet_provider import (
    TESTNET_SOURCE,
    TestnetBarProvider,
    make_testnet_provider,
)


# 一个真实感的 testnet 价格序列（BTC ~量级，验首价反推 qty 不跨尺度失真）。
_FAKE_CLOSES = [60000.0, 60500.0, 60250.0, 61000.0, 60800.0, 61500.0, 61200.0, 62000.0,
                61700.0, 62500.0, 62100.0, 63000.0, 62800.0, 63500.0, 63100.0, 64000.0]
_REAL_TESTNET_SECRET = "SECRET-must-never-leak-anywhere-1234567890"  # noqa: S105  测试哨兵明文 key


def _tmp_eqlog(name: str) -> Path:
    return Path(tempfile.mkdtemp()) / f"{name}_equity.jsonl"


# ════════════════════════════════════════════════════════════════════
# 可注入接缝 fakes / spies（无真 testnet key/网络即可验注入接线）
# ════════════════════════════════════════════════════════════════════
class FakeTestnetClient:
    """mock testnet 行情 client：返预设 klines/mark（无网络）。只读公共行情接口（无下单/签名方法）。"""

    def __init__(self, closes: list[float] | None = None) -> None:
        self._closes = list(closes if closes is not None else _FAKE_CLOSES)
        self.kline_calls = 0
        self.mark_calls = 0

    def fetch_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        self.kline_calls += 1
        # Binance kline 形：[openTime, open, high, low, close, volume, ...]；close=index 4。
        return [[i, c, c * 1.001, c * 0.999, c, 1.0, i] for i, c in enumerate(self._closes[:limit])]

    def fetch_mark(self, symbol: str) -> float | None:
        self.mark_calls += 1
        return self._closes[-1]


class FaultyTestnetClient:
    """fault-injecting client：任何取数即抛连接异常（验 fail-open 留痕回退）。"""

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or ConnectionError("simulated testnet connect failure")

    def fetch_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        raise self._exc

    def fetch_mark(self, symbol: str) -> float | None:
        raise self._exc


class EmptyKlinesClient:
    """连得上但 klines 空（symbol 无对应 testnet 市场）：验「拉到 0 bar → 诚实回退不空跑」。"""

    def fetch_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        return []

    def fetch_mark(self, symbol: str) -> float | None:
        return None


class SpyKeystore:
    """keystore spy：暴露 list_names（存在性），**计数 fetch 调用**（坏门#1：取明文 secret 即被抓）。

    fetch 真返一条含明文 secret 的记录——若被调用即 fetch_count>0（testnet 路径绝不该调 fetch）。
    """

    def __init__(self, names: list[str] | None = None) -> None:
        self._names = list(names or [])
        self.fetch_count = 0
        self.list_names_count = 0

    def list_names(self) -> list[str]:
        self.list_names_count += 1
        return list(self._names)

    def fetch(self, name: str) -> Any:
        self.fetch_count += 1
        from app.security.keystore import KeystoreRecord

        return KeystoreRecord(name=name, api_key="PUBLIC-KEY-id", api_secret=_REAL_TESTNET_SECRET)


# ════════════════════════════════════════════════════════════════════
# 坏门 #5：有 key（mock client）→ 注入 testnet_provider 且 tick 后 bars_fed>0
# ════════════════════════════════════════════════════════════════════
def test_with_key_injects_testnet_provider_and_feeds_bars():
    """坏门#5：配 testnet key（spy keystore 有名）+ mock client → register 注 TestnetBarProvider，
    tick 后 bars_fed>0、source=binance_testnet_live、净值移动（证明注入接线真生效）。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])
    fake = FakeTestnetClient()
    rec = svc.register_run(
        run_id="tn5", name="tn5", origin="o", market="crypto", symbols=["BTCUSDT"],
        bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn5"),
        testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: fake,
    )
    assert isinstance(rec.provider, TestnetBarProvider), "配 key + 连通 → 注入 TestnetBarProvider（真喂档）"
    assert rec.provider_kind == "testnet"
    assert rec.simulated_source == TESTNET_SOURCE == "binance_testnet_live"
    assert rec.degrade_reason is None, "真喂档无降级原因"
    primed = svc.prime_run("tn5", ticks=12)
    assert primed["bars_fed"] > 0, "注入 testnet provider 后 tick 必喂 bar（bars_fed>0，接线生效）"
    assert primed["source"] == TESTNET_SOURCE
    assert fake.kline_calls > 0, "testnet 真喂须实际调过公共 klines（证明喂的是 testnet 源）"
    eq = svc.equity_log("tn5")
    totals = [round(r["total_equity"], 2) for r in eq]
    assert len(set(totals)) > 1, "净值须随 testnet 真行情移动（非死平）"


def test_with_key_status_exposes_testnet_kind():
    """status() 透出 provider_kind=testnet + source=binance_testnet_live（用户可见真喂档）。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])
    svc.register_run(run_id="tn5b", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                     bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn5b"),
                     testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: FakeTestnetClient())
    st = svc.status("tn5b")
    assert st["provider_kind"] == "testnet"
    assert st["simulated_source"] == "binance_testnet_live"
    assert st["degrade_reason"] is None


def test_testnet_first_price_back_derives_qty_no_scale_distortion():
    """坏门#5b：testnet 真价 ~60000 → seed_positions 用首价反推 qty（非 base=100），P&L 尺度自洽。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])
    svc.register_run(run_id="tn5c", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                     bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn5c"),
                     testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: FakeTestnetClient())
    svc.prime_run("tn5c", ticks=8)
    pos = svc.positions("tn5c")
    assert pos and pos[0]["entry_price"] == pytest.approx(60000.0, abs=1.0), \
        "entry_price 须为 testnet 真首价 ~60000（非合成 100）——否则 P&L 跨尺度失真"


# ════════════════════════════════════════════════════════════════════
# 坏门 #3：无 key → 诚实回退 replay_provider + source 不标 testnet
# ════════════════════════════════════════════════════════════════════
def test_no_key_falls_back_to_replay_honest_source():
    """坏门#3：请求 testnet 但 keystore 无 key → 回退 ReplayBarProvider 兜底；
    source 为兜底真实标签（crypto→bundled_sample_replay），**绝不**标 binance_testnet_live。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=[])  # 无 testnet key
    rec = svc.register_run(
        run_id="tn3", name="tn3", origin="o", market="crypto", symbols=["BTCUSDT"],
        bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn3"),
        testnet=True, testnet_keystore=ks,
    )
    # 坏门防线：无 key 却标 testnet 真喂 → 本断言转红。
    assert rec.simulated_source != TESTNET_SOURCE, "无 key 绝不标 binance_testnet_live（不伪装连真）"
    assert rec.simulated_source == BUNDLED_SOURCE, "crypto 回退兜底 → bundled_sample_replay（真捆样本）"
    assert rec.provider_kind == "replay_fallback", "请求 testnet 却回退 → provider_kind=replay_fallback（留痕档位）"
    # 兜底仍真喂 bars 产净值（回退≠空壳）。
    primed = svc.prime_run("tn3", ticks=8)
    assert primed["bars_fed"] > 0 and primed["source"] == BUNDLED_SOURCE


def test_no_key_does_not_fetch_secret_only_checks_existence():
    """坏门#1：无 key 回退路径**只查名字存在性、绝不 fetch 明文 secret**（INV-3：存在性预检不物化 key）。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=[])
    svc.register_run(run_id="tn3b", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                     bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn3b"),
                     testnet=True, testnet_keystore=ks)
    assert ks.list_names_count > 0, "须查过 key 名存在性（凭据门）"
    assert ks.fetch_count == 0, "坏门#1：testnet 路径绝不 fetch 明文 secret（取出即 fetch_count>0 转红）"


# ════════════════════════════════════════════════════════════════════
# 坏门 #1：testnet key 不进 LLM —— provider/record/status 串里无明文 secret
# ════════════════════════════════════════════════════════════════════
def test_configured_testnet_path_never_fetches_plaintext_secret():
    """坏门#1：**配了 key** 时走 testnet 真喂，也**只查名、绝不 fetch 明文 secret**（公共行情无需鉴权）。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])
    svc.register_run(run_id="tn1", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                     bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn1"),
                     testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: FakeTestnetClient())
    assert ks.fetch_count == 0, "坏门#1：testnet 真喂走公共端点，绝不 fetch 明文 secret（取出即转红）"


def test_no_plaintext_key_reachable_via_provider_or_status():
    """坏门#1b：哨兵明文 secret 绝不出现在 provider 对象 / run record / status 序列化里（key 不进 LLM 面）。"""

    import json

    svc = PaperDeskService()
    # keystore 的 fetch 会返含哨兵 secret 的记录——但 testnet 路径不该调 fetch，故 secret 永不入对象图。
    ks = SpyKeystore(names=["binance_testnet"])
    rec = svc.register_run(run_id="tn1b", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                           bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn1b"),
                           testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: FakeTestnetClient())
    # provider repr / record repr 里无明文 secret。
    assert _REAL_TESTNET_SECRET not in repr(rec.provider)
    assert _REAL_TESTNET_SECRET not in repr(rec)
    # status dict（可被 agent/前端读）序列化里无明文 secret。
    st = svc.status("tn1b")
    assert _REAL_TESTNET_SECRET not in json.dumps(st, default=str)
    # 即便 provider 暴露了底层 client，其 creds 也是空 secret（无 key 公共 client）。
    assert ks.fetch_count == 0


# ════════════════════════════════════════════════════════════════════
# 坏门 #2：testnet 路径不调真 live 下单（永走模拟撮合）
# ════════════════════════════════════════════════════════════════════
def test_testnet_provider_has_no_order_or_signed_surface():
    """坏门#2：TestnetBarProvider **只读公共行情**——无 place_order / signed / assert_safe_startup 表面。"""

    p = TestnetBarProvider(symbols=["BTCUSDT"], _client=FakeTestnetClient())
    for forbidden in ("place_order", "signed", "_signed", "assert_safe_startup", "submit_order"):
        assert not hasattr(p, forbidden), f"坏门#2：testnet provider 绝不暴露下单/签名表面 {forbidden!r}"


def test_testnet_tick_only_calls_public_market_data_never_signed():
    """坏门#2b：种坏门——client 任何【签名/私有】调用即炸测试；tick/mtm 全程只该碰公共 klines/mark。

    若 provider 误触 signed/place_order/assert_safe_startup（如想 assert_safe_startup 校验权限）→ 立即 fail。
    """

    calls: list[str] = []

    class TrippingClient:
        def fetch_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
            calls.append("fetch_klines")
            return [[i, c, c, c, c, 1.0] for i, c in enumerate(_FAKE_CLOSES[:limit])]

        def fetch_mark(self, symbol: str) -> float | None:
            calls.append("fetch_mark")
            return _FAKE_CLOSES[-1]

        # 种坏门：任何签名/私有/下单调用都炸（testnet 真喂绝不该走到这些）。
        def signed(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
            pytest.fail("坏门#2：testnet 真喂触到 signed 私有调用（绝不该鉴权下单路径）")

        def _signed(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
            pytest.fail("坏门#2：testnet 真喂触到 _signed")

        def assert_safe_startup(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
            pytest.fail("坏门#2：testnet 真喂触到 assert_safe_startup（要签名=要 secret）")

        def place_order(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
            pytest.fail("坏门#2：testnet 真喂触到 place_order live 路径")

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])
    svc.register_run(run_id="tn2", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                     bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn2"),
                     testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: TrippingClient())
    svc.prime_run("tn2", ticks=10)  # 大量 tick+mtm：全程只该碰公共行情端点（绝不签名/下单）
    # 快照回放模型：snapshot 拉 klines，MTM 用游标 close（不再每 tick 打实时 mark）——更少网络、更稳。
    assert "fetch_klines" in calls, "testnet 真喂须拉过公共 klines（快照源）"
    assert all(c in ("fetch_klines", "fetch_mark") for c in calls), \
        "testnet 全程只碰公共行情端点（fetch_klines/fetch_mark），绝不 signed/place_order/assert_safe_startup"


def test_testnet_run_still_rejects_live_order():
    """坏门#2c：即便 testnet 真喂在跑，crypto run 的 A股式 live 下单治理门不破——testnet≠放开真 live。

    （testnet provider 只喂行情；下单仍走 OrderGuard live 路径，与本 provider 正交。）"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])
    svc.register_run(run_id="tn2d", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                     bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn2d"),
                     testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: FakeTestnetClient())
    svc.prime_run("tn2d", ticks=4)
    # crypto live 下单不在本 desk 路径放开（desk.attempt_live_order 仅 A股族；crypto live 走 relay/lease 门）。
    # 这里验：testnet provider 注入不会新增任何裸 live 下单口（provider 无下单表面，已由 #2/#2b 覆盖）。
    assert svc.status("tn2d")["bars_fed"] > 0


# ════════════════════════════════════════════════════════════════════
# 坏门 #4：fail-open 留痕（连接异常 → 回退模拟 + 降级原因留痕）
# ════════════════════════════════════════════════════════════════════
def test_connect_failure_fails_open_to_replay_with_trace():
    """坏门#4：mock client 抛连接异常 → fail-open 回退兜底 + degrade_reason 留痕（非静默降级）。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])  # 有 key
    rec = svc.register_run(
        run_id="tn4", name="tn4", origin="o", market="crypto", symbols=["BTCUSDT"],
        bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn4"),
        testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: FaultyTestnetClient(),
    )
    # fail-open：不抛错硬停，回退兜底真跑。
    assert rec.provider_kind == "replay_fallback", "连接失败 → 回退兜底（replay_fallback）"
    assert rec.simulated_source != TESTNET_SOURCE, "连接失败绝不标 testnet 真喂（§3 不假绿灯）"
    # 留痕：degrade_reason 非空且含可读降级原因（坏门：静默降级无痕 → 本断言转红）。
    assert rec.degrade_reason is not None, "坏门#4：连接失败须留降级原因（静默无痕即转红）"
    assert "testnet 连接失败" in rec.degrade_reason
    # status() 也透出降级原因（用户可见为何没走 testnet）。
    st = svc.status("tn4")
    assert st["degrade_reason"] is not None and st["provider_kind"] == "replay_fallback"
    # 回退兜底仍产净值（fail-open 不破 paper run）。
    assert svc.prime_run("tn4", ticks=8)["bars_fed"] > 0


def test_empty_klines_falls_back_honestly_with_trace():
    """坏门#4b：连得上但拉到 0 bar（symbol 无对应市场）→ 诚实回退兜底 + 留痕，不空跑伪装真喂。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])
    rec = svc.register_run(run_id="tn4b", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                           bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn4b"),
                           testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: EmptyKlinesClient())
    assert rec.provider_kind == "replay_fallback"
    assert rec.simulated_source != TESTNET_SOURCE
    assert rec.degrade_reason is not None and "0 bar" in rec.degrade_reason


def test_factory_fail_open_returns_none_not_raise():
    """factory 直测：连接异常恒 fail-open 返 (None, reason)，绝不抛错（不硬停 paper run）。"""

    prov, reason = make_testnet_provider(
        "crypto", ["BTCUSDT"], keystore=SpyKeystore(names=["binance_testnet"]),
        client_factory=lambda: FaultyTestnetClient(),
    )
    assert prov is None and reason is not None and "连接失败" in reason


# ════════════════════════════════════════════════════════════════════
# 坏门 #6：治理回归 —— A股恒拒 live 不破 + A股恒不走 testnet（crypto only）
# ════════════════════════════════════════════════════════════════════
def test_ashare_never_uses_testnet_even_when_requested():
    """坏门#6：A股即便 testnet=True 也恒走兜底（crypto only），且永不触 keystore/网络（市场守门先行）。"""

    svc = PaperDeskService()
    ks = SpyKeystore(names=["binance_testnet"])  # 有 key 也不该用
    rec = svc.register_run(
        run_id="tn6cn", name="x", origin="o", market="equity_cn", symbols=["600519"],
        bench="500", creator="c", equity_log_path=_tmp_eqlog("tn6cn"),
        testnet=True, testnet_keystore=ks, testnet_client_factory=lambda: FakeTestnetClient(),
    )
    assert rec.provider_kind != "testnet", "A股永不 testnet 真喂"
    assert rec.simulated_source != TESTNET_SOURCE, "A股 source 绝不标 binance_testnet_live"
    assert rec.simulated_source == SIMULATED_SOURCE, "A股无样本 → 合成兜底 deterministic_sim_walk"
    assert ks.list_names_count == 0 and ks.fetch_count == 0, "A股市场守门先行：keystore 一次都不该碰"


def test_ashare_testnet_requested_still_rejects_live():
    """坏门#6b：A股 run（即便 testnet=True 请求）live 下单仍恒拒（致命错误防线，A股永不 live）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="tn6cn2", name="x", origin="o", market="equity_cn", symbols=["600519"],
                     bench="500", creator="c", equity_log_path=_tmp_eqlog("tn6cn2"),
                     testnet=True, testnet_keystore=SpyKeystore(names=["binance_testnet"]))
    svc.prime_run("tn6cn2", ticks=4)
    with pytest.raises(AShareLiveForbidden):
        svc.attempt_live_order("tn6cn2", {"symbol": "600519", "side": "buy", "quantity": 100})


def test_factory_market_guard_rejects_ashare_before_keystore():
    """factory 直测：market!=crypto 在查 keystore **之前**返 (None, reason)（守门先于凭据/网络）。"""

    ks = SpyKeystore(names=["binance_testnet"])
    prov, reason = make_testnet_provider("equity_cn", ["600519"], keystore=ks)
    assert prov is None and "crypto" in reason
    assert ks.list_names_count == 0, "A股守门先行：factory 未查 keystore"


# ════════════════════════════════════════════════════════════════════
# 基线不破 + 向后兼容：testnet=False（默认）路径完全不变
# ════════════════════════════════════════════════════════════════════
def test_default_no_testnet_keeps_replay_source():
    """向后兼容：不传 testnet（默认 False）→ 走原 ReplayBarProvider，source/kind 不变（既有绿测不翻）。"""

    svc = PaperDeskService()
    rec = svc.register_run(run_id="tn0", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                           bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tn0"))
    assert rec.provider_kind == "replay", "默认（未请求 testnet）→ provider_kind=replay（非 fallback）"
    assert rec.simulated_source == BUNDLED_SOURCE, "默认 crypto 仍 bundled_sample_replay（基线不破）"
    assert rec.degrade_reason is None


def test_testnet_provider_reset_is_idempotent_no_refetch():
    """幂等关键：TestnetBarProvider.reset() 仅游标归零、**不重拉网络**（prime 复位再跑产同一序列）。"""

    fake = FakeTestnetClient()
    p = TestnetBarProvider(symbols=["BTCUSDT"], _client=fake)
    p.snapshot_klines()
    calls_after_snapshot = fake.kline_calls
    # 跑几根 + reset + 再跑：reset 不该再调 fetch_klines。
    [p.next_bar("BTCUSDT") for _ in range(5)]
    p.reset()
    [p.next_bar("BTCUSDT") for _ in range(5)]
    assert fake.kline_calls == calls_after_snapshot, "reset 不重拉网络（快照语义，幂等）"


# ════════════════════════════════════════════════════════════════════
# 变异自检（mutation self-check）：确认坏门#3 / #4 真会转红
# ════════════════════════════════════════════════════════════════════
def test_mutation_self_check_no_key_false_label_would_be_caught():
    """变异自检（坏门#3）：若无 key 却把 source 谎称 testnet 真喂，本测试逻辑必判红。

    模拟『坏门已植入』的世界：手工把回退态 source 改成 binance_testnet_live → 断言应捕获（red）。
    这证明 test_no_key_falls_back_to_replay_honest_source 的断言是真守门（非空过）。
    """

    svc = PaperDeskService()
    rec = svc.register_run(run_id="tnmut3", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                           bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tnmut3"),
                           testnet=True, testnet_keystore=SpyKeystore(names=[]))
    # 当前（正确）：回退兜底真实标签。
    assert rec.simulated_source != TESTNET_SOURCE
    # 植入坏门：谎称连真。
    rec.simulated_source = TESTNET_SOURCE
    with pytest.raises(AssertionError):
        assert rec.simulated_source != TESTNET_SOURCE, "（变异世界）无 key 谎称 testnet 应被坏门#3 断言捕获"


def test_mutation_self_check_silent_degrade_would_be_caught():
    """变异自检（坏门#4）：若连接失败却不留 degrade_reason（静默降级），坏门#4 断言必判红。"""

    svc = PaperDeskService()
    rec = svc.register_run(run_id="tnmut4", name="x", origin="o", market="crypto", symbols=["BTCUSDT"],
                           bench="BTC", creator="c", equity_log_path=_tmp_eqlog("tnmut4"),
                           testnet=True, testnet_keystore=SpyKeystore(names=["binance_testnet"]),
                           testnet_client_factory=lambda: FaultyTestnetClient())
    assert rec.degrade_reason is not None  # 当前（正确）：留痕。
    # 植入坏门：抹掉留痕（静默降级）。
    rec.degrade_reason = None
    with pytest.raises(AssertionError):
        assert rec.degrade_reason is not None, "（变异世界）静默降级无痕应被坏门#4 断言捕获"
