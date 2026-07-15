"""§11 PIT/复权 读侧接线——对抗测试（种已知坏门必抓 · §16「未复权价误喂成交层」向量）。

设计源：dev/research/findings/dreaminate/pit-adjustment-readside-design-20260715.md。
覆盖 design 8 测 + present-detection 负例 + volume=raw 硬化。承重护栏（对抗 1/2/3/7）用**硬编码
期望值 oracle**（不复用被测公式），种变异（× → /、漏乘、fail→drop、只调 close）必打红。

fixture：3 symbol × 5 日，两处不同日的除权（AAA d2 派息 20%、CCC d3 拆股 2:1），
raw 价格精确被 adj_factor 补偿 → 后复权 hfq 连续价恒定。factor 取 1.0 / 1.25 / 2.0（float 精确）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from app.connectors.base import make_wide_fetch_result
from app.data_quality import DatasetRegistry, GERule
from app.factor_factory.panel_source import (
    FORBIDDEN_SOURCE_ASSET_IDS,
    HS300_RESEARCH_ASSET_ID,
    PanelResolution,
    PanelSourceError,
    _ensure_asset_allowed,
    _load_real_panel,
    load_market_panel,
    resolve_panel_source,
)

# —— 采自变更【前】的合成输出（capture：BACKTEST_DATA_ROOT 隔离下跑 load_market_panel）——
# 逐字节 tripwire：合成分支任何走样（改 sort / 丢列 / 变 dtype / 换 sample）→ 哈希变 → 打红。
_PRECHANGE_EQUITY_CN_CSV_SHA256 = "57ed8c535807cb4e8d5aad2b39482bc14ae96876ce431d85f0d1490834e2a44c"
_PRECHANGE_CRYPTO_CSV_SHA256 = "7e8de8a1418a1f4a8942c28ee21d0d3a917b9c3a5aa5727e72f04280ec84116c"

_COHORT_FORBIDDEN_ID = "hs300_daily_10y_readbench_cohort"

# 5 个交易日（tz-aware UTC，与 tushare 落盘 Datetime 口径一致）。
_DAYS = [
    datetime(2024, 1, 2, tzinfo=UTC),
    datetime(2024, 1, 3, tzinfo=UTC),
    datetime(2024, 1, 4, tzinfo=UTC),
    datetime(2024, 1, 5, tzinfo=UTC),
    datetime(2024, 1, 8, tzinfo=UTC),
]
_AAA_EXDIV_TS = _DAYS[2]  # AAA 除权日（d2）：raw close 10→8，factor 1.0→1.25
_CCC_SPLIT_TS = _DAYS[3]  # CCC 拆股日（d3）：raw close 50→25，factor 1.0→2.0

# raw bars 与 adj_factor（同 (symbol,ts) 一一对应；raw 精确被 factor 补偿 → hfq 连续）。
# 列结构 = CANONICAL_COLUMNS：ts, symbol, open, high, low, close, volume。
_ROWS: list[dict[str, object]] = []


def _add(symbol: str, ts, o, h, l, c, v, f) -> None:
    _ROWS.append(
        {"symbol": symbol, "ts": ts, "open": float(o), "high": float(h),
         "low": float(l), "close": float(c), "volume": float(v), "adj_factor": float(f)}
    )


# AAA：d2 派息 20%（raw 10→8，factor 1.0→1.25）→ hfq O/H/L/C 恒 [10,10.5,9.5,10]。
_add("AAA", _DAYS[0], 10.0, 10.5, 9.5, 10.0, 1000, 1.0)
_add("AAA", _DAYS[1], 10.0, 10.5, 9.5, 10.0, 1100, 1.0)
_add("AAA", _DAYS[2], 8.0, 8.4, 7.6, 8.0, 1200, 1.25)
_add("AAA", _DAYS[3], 8.0, 8.4, 7.6, 8.0, 1300, 1.25)
_add("AAA", _DAYS[4], 8.0, 8.4, 7.6, 8.0, 1400, 1.25)
# BBB：无公司行动，factor 恒 1.0 → hfq == raw（价格漂移）。
_add("BBB", _DAYS[0], 20.0, 20.5, 19.5, 20.0, 500, 1.0)
_add("BBB", _DAYS[1], 21.0, 21.5, 20.5, 21.0, 510, 1.0)
_add("BBB", _DAYS[2], 22.0, 22.5, 21.5, 22.0, 520, 1.0)
_add("BBB", _DAYS[3], 21.0, 21.5, 20.5, 21.0, 530, 1.0)
_add("BBB", _DAYS[4], 23.0, 23.5, 22.5, 23.0, 540, 1.0)
# CCC：d3 拆股 2:1（raw 50→25，factor 1.0→2.0）→ hfq O/H/L/C 恒 [50,51,49,50]。
_add("CCC", _DAYS[0], 50.0, 51.0, 49.0, 50.0, 200, 1.0)
_add("CCC", _DAYS[1], 50.0, 51.0, 49.0, 50.0, 210, 1.0)
_add("CCC", _DAYS[2], 50.0, 51.0, 49.0, 50.0, 220, 1.0)
_add("CCC", _DAYS[3], 25.0, 25.5, 24.5, 25.0, 230, 2.0)
_add("CCC", _DAYS[4], 25.0, 25.5, 24.5, 25.0, 240, 2.0)

# 硬编码期望的后复权 hfq（raw × factor，人手算，独立于被测公式——真 oracle）。
# AAA 恒 [o10,h10.5,l9.5,c10]；CCC 恒 [o50,h51,l49,c50]；BBB == raw。
_EXPECTED_HFQ: dict[tuple[str, int], tuple[float, float, float, float]] = {
    ("AAA", i): (10.0, 10.5, 9.5, 10.0) for i in range(5)
} | {
    ("CCC", i): (50.0, 51.0, 49.0, 50.0) for i in range(5)
}


def _bars() -> pl.DataFrame:
    return pl.DataFrame(_ROWS).select(
        ["ts", "symbol", "open", "high", "low", "close", "volume"]
    )


def _adj() -> pl.DataFrame:
    return pl.DataFrame(_ROWS).select(["symbol", "ts", "adj_factor"])


def _default_rules() -> list[GERule]:
    return [GERule(column=c, rule_type="not_null") for c in ("open", "high", "low", "close", "volume")]


def _register_real_asset(
    root: Path,
    *,
    bars: pl.DataFrame | None = None,
    adj: pl.DataFrame | None = None,
    dataset_id: str = HS300_RESEARCH_ASSET_ID,
    rules: list[GERule] | None = None,
    with_suspensions: bool = True,
    metadata: dict[str, object] | None = None,
    drop_files: tuple[str, ...] = (),
):
    """把 mini 真实资产（bars + adj[+ suspensions]）落盘并经 DatasetRegistry.register 注册。

    镜像 hs300_pipeline.build_research_asset 的写路径（3 文件 manifest + require_provenance）。
    drop_files：注册后删除指定 basename（模拟 file_paths 中某文件运行时缺失 → present-detection miss）。
    """

    bars = _bars() if bars is None else bars
    adj = _adj() if adj is None else adj
    out = root / "raw"
    out.mkdir(parents=True, exist_ok=True)
    bars_path = out / "bars.parquet"
    adj_path = out / "adj_factors.parquet"
    bars.write_parquet(bars_path)
    adj.write_parquet(adj_path)
    file_paths = [str(bars_path), str(adj_path)]
    if with_suspensions:
        susp_path = out / "suspensions.parquet"
        pl.DataFrame(
            {"symbol": ["AAA"], "ts": [_DAYS[0]], "suspend_timing": [None], "suspend_type": ["S"]}
        ).write_parquet(susp_path)
        file_paths.append(str(susp_path))

    registry = DatasetRegistry(root / "datasets" / "registry.jsonl")
    fr = make_wide_fetch_result(bars, "tushare")
    meta: dict[str, object] = {
        "survivorship": "union_includes_delisted",
        "adjustment_policy": "raw_plus_adj_factor_no_prejoin",
    }
    if metadata:
        meta.update(metadata)
    version = registry.register(
        dataset_id,
        fr,
        file_paths=file_paths,
        rules=_default_rules() if rules is None else rules,
        metadata=meta,
        source_ref="tushare://daily",
        ingestion_skill_version="tushare@test",
        secret_ref="keyring://quantbt/tushare",
        known_at_utc=datetime.now(UTC).isoformat(),
        effective_at_utc=bars.get_column("ts").max().isoformat(),
        require_provenance=True,
    )
    for name in drop_files:
        Path(out / name).unlink()
    return version


def _hfq_panel(root: Path) -> pl.DataFrame:
    return load_market_panel("ashare_hs300")  # 需 monkeypatch QUANTBT_DATA_ROOT=root


def _sym(panel: pl.DataFrame, symbol: str) -> pl.DataFrame:
    return panel.filter(pl.col("symbol") == symbol).sort("ts")


# ————————————————————————————————————————————————————————————————————————
# 1. hfq 方向（× 不是 ÷）：跨除权日 hfq 连续；× → / 变异断连续。
# ————————————————————————————————————————————————————————————————————————
def test_01_hfq_direction_multiply_not_divide(tmp_path, monkeypatch):
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    panel = load_market_panel("ashare_hs300")

    aaa = _sym(panel, "AAA")
    close = aaa.get_column("close").to_list()
    # 正确 hfq（raw×factor）：AAA close 恒 10.0（20% 派息被 factor 精确补偿）→ 跨除权日零跳变。
    assert close == pytest.approx([10.0, 10.0, 10.0, 10.0, 10.0], abs=1e-9)
    # 跨除权日（d1→d2）hfq 收益连续 = 0；× → / 变异会得 8/1.25=6.4 → 收益 -36% → 本断言红。
    ret_exdiv = close[2] / close[1] - 1.0
    assert ret_exdiv == pytest.approx(0.0, abs=1e-9)
    # CCC 拆股（d2→d3）同理 hfq 连续（50→50）。
    ccc_close = _sym(panel, "CCC").get_column("close").to_list()
    assert ccc_close == pytest.approx([50.0] * 5, abs=1e-9)


# ————————————————————————————————————————————————————————————————————————
# 2. 漏 join / 漏乘（raw 冒充复权）：hfq_close == raw×factor 且 != raw；漏乘 → close==raw → 抓。
# ————————————————————————————————————————————————————————————————————————
def test_02_missing_join_raw_masquerade(tmp_path, monkeypatch):
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    panel = load_market_panel("ashare_hs300")

    aaa = _sym(panel, "AAA")
    exdiv = aaa.filter(pl.col("ts") == _AAA_EXDIV_TS)
    hfq_close = exdiv.get_column("close").item()
    raw_close, factor = 8.0, 1.25
    # 复权后 == raw×factor（=10），且明确 != raw（=8）——漏乘会让 close 停在 raw=8 → 两条断言都红。
    assert hfq_close == pytest.approx(raw_close * factor, abs=1e-9)
    assert abs(hfq_close - raw_close) > 1e-6
    # BBB（factor≡1）hfq 必须 == raw：证明「!= raw」不是无条件成立、只有真有 factor 才变。
    bbb = _sym(panel, "BBB").get_column("close").to_list()
    assert bbb == pytest.approx([20.0, 21.0, 22.0, 21.0, 23.0], abs=1e-9)


# ————————————————————————————————————————————————————————————————————————
# 3. 缺因子行 → fail-closed raise（不 drop、不 null、不 ffill）。
# ————————————————————————————————————————————————————————————————————————
def test_03_missing_factor_row_fail_closed_raise(tmp_path, monkeypatch):
    # adj 故意删掉 AAA 除权日一行 → left-join 该行 factor=null。
    adj_missing = _adj().filter(
        ~((pl.col("symbol") == "AAA") & (pl.col("ts") == _AAA_EXDIV_TS))
    )
    _register_real_asset(tmp_path, adj=adj_missing)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))

    # fail-closed：缺因子 → raise（若变异成 drop_nulls / 静默 null，则不 raise → 本 pytest.raises 红）。
    with pytest.raises(PanelSourceError, match="缺同日 adj_factor"):
        load_market_panel("ashare_hs300")


def test_03b_nonfinite_factor_fail_closed_raise(tmp_path, monkeypatch):
    # F1 回归：polars 里 NaN **非** null 且 `NaN<=0`/`+inf<=0` 均为 False → null_count + (<=0) 都漏。
    # 必须 is_finite 显式拦，否则出 NaN/inf 价却标 hfq（假复权）。把 <=0 guard 退回原样 → 本测试红。
    adj_nan = _adj().with_columns(
        pl.when((pl.col("symbol") == "AAA") & (pl.col("ts") == _AAA_EXDIV_TS))
        .then(pl.lit(float("nan")))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    _register_real_asset(tmp_path, adj=adj_nan)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    with pytest.raises(PanelSourceError, match="非法"):
        load_market_panel("ashare_hs300")

    # +inf factor 同样 fail-closed（另起 data_root，避免复用已注册的 NaN 资产）。
    root_inf = tmp_path / "inf"
    adj_inf = _adj().with_columns(
        pl.when((pl.col("symbol") == "CCC") & (pl.col("ts") == _CCC_SPLIT_TS))
        .then(pl.lit(float("inf")))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    _register_real_asset(root_inf, adj=adj_inf)
    with pytest.raises(PanelSourceError, match="非法"):
        resolve_and_load(root_inf)


# ————————————————————————————————————————————————————————————————————————
# 4. PIT：仅「更晚」的 factor vintage 改动，不得回改「更早」行的 hfq（无前视）。
# ————————————————————————————————————————————————————————————————————————
def test_04_pit_earlier_hfq_invariant_to_later_factor_vintage(tmp_path):
    # v1：原始 adj。v2：仅把 AAA 最后一日(d4) 的 factor 改掉（模拟更晚日期的 vintage 修订）。
    root_v1 = tmp_path / "v1"
    root_v2 = tmp_path / "v2"
    adj_v2 = _adj().with_columns(
        pl.when((pl.col("symbol") == "AAA") & (pl.col("ts") == _DAYS[4]))
        .then(pl.lit(1.30))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    _register_real_asset(root_v1)
    _register_real_asset(root_v2, adj=adj_v2)

    p1 = _sym(resolve_and_load(root_v1), "AAA").sort("ts")
    p2 = _sym(resolve_and_load(root_v2), "AAA").sort("ts")
    c1 = p1.get_column("close").to_list()
    c2 = p2.get_column("close").to_list()
    # d0..d3（ts < d4）hfq 逐行不变——每行 factor 独立、不引用 latest → 晚到 vintage 不回改历史。
    assert c1[:4] == pytest.approx(c2[:4], abs=1e-9)
    # d4 因 factor 改动而变（8×1.25=10 → 8×1.30=10.4）：证明改动确实落在「更晚」那行、非无操作。
    assert c1[4] == pytest.approx(10.0, abs=1e-9)
    assert c2[4] == pytest.approx(10.4, abs=1e-9)


def resolve_and_load(root: Path) -> pl.DataFrame:
    """直接 data_root 路径读真实 panel（不经 env）——用 resolve_panel_source + 公有 load。"""
    import os

    prev = os.environ.get("QUANTBT_DATA_ROOT")
    os.environ["QUANTBT_DATA_ROOT"] = str(root)
    try:
        return load_market_panel("ashare_hs300")
    finally:
        if prev is None:
            os.environ.pop("QUANTBT_DATA_ROOT", None)
        else:
            os.environ["QUANTBT_DATA_ROOT"] = prev


# ————————————————————————————————————————————————————————————————————————
# 5. 诚实 label：resolution.kind / adjustment 真实（real→real/hfq，synthetic→synthetic/continuous）。
# ————————————————————————————————————————————————————————————————————————
def test_05_honest_labels_real_vs_synthetic(tmp_path):
    _register_real_asset(tmp_path)
    real = resolve_panel_source("ashare_hs300", data_root=tmp_path)
    assert real.kind == "real"
    assert real.adjustment == "hfq"
    assert real.volume_adjustment == "none"
    assert real.survivorship == "union_includes_delisted"
    assert real.universe == HS300_RESEARCH_ASSET_ID
    assert real.pit_limit == "no_per_row_factor_vintage"
    assert real.dataset_version_ref is not None
    assert real.perf_baseline_claim is False
    prov = real.as_provenance()
    assert prov["kind"] == "real" and prov["adjustment"] == "hfq"
    assert set(prov) == {
        "kind", "dataset_version_ref", "adjustment", "volume_adjustment",
        "survivorship", "universe", "pit_limit", "perf_baseline_claim",
    }

    # 合成（无 registry 的空目录）→ 诚实标 synthetic / synthetic_continuous，绝不谎称 hfq/real。
    syn = resolve_panel_source("ashare_hs300", data_root=tmp_path / "empty")
    assert syn.kind == "synthetic"
    assert syn.adjustment == "synthetic_continuous"
    assert syn.adjustment != "hfq"
    assert syn.dataset_version_ref is None
    assert syn.volume_adjustment == "none"
    assert syn.perf_baseline_claim is False
    # equity_cn / crypto 恒合成。
    assert resolve_panel_source("equity_cn").kind == "synthetic"
    assert resolve_panel_source("crypto").kind == "synthetic"


# ————————————————————————————————————————————————————————————————————————
# 6. 两路径：absent → 逐字节等于今天的 load_market_panel(equity_cn)；present → 真实 hfq、provenance=real。
# ————————————————————————————————————————————————————————————————————————
def test_06_absent_byte_identical_present_real(tmp_path, monkeypatch):
    # —— absent 分支：空 data_root（无 registry）——
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path / "empty"))
    equity = load_market_panel("equity_cn")
    crypto = load_market_panel("crypto")
    ashare_absent = load_market_panel("ashare_hs300")

    # (a) equity_cn / crypto 逐字节 == 变更前捕获的哈希（合成分支零走样）。
    assert hashlib.sha256(equity.write_csv().encode()).hexdigest() == _PRECHANGE_EQUITY_CN_CSV_SHA256
    assert hashlib.sha256(crypto.write_csv().encode()).hexdigest() == _PRECHANGE_CRYPTO_CSV_SHA256
    # (b) ashare_hs300 absent → 与 equity_cn 逐字节相等（同一合成 sample 兜底）。
    assert_frame_equal(ashare_absent, equity)
    assert resolve_panel_source("ashare_hs300", data_root=tmp_path / "empty").kind == "synthetic"

    # —— present 分支：注册真实资产 ——
    version = _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    real_panel = load_market_panel("ashare_hs300")
    res = resolve_panel_source("ashare_hs300", data_root=tmp_path)
    assert res.kind == "real"
    assert res.dataset_version_ref == version.version_id
    # present ≠ absent：真实 hfq 面板与合成兜底不同帧（列/值都不同）。
    assert real_panel.height == 15  # 3 symbol × 5 日：present 分支确读了 mini 真实资产，非合成兜底
    assert set(real_panel["symbol"].unique().to_list()) == {"AAA", "BBB", "CCC"}
    # 真实 hfq 全表逐行对齐硬编码 oracle（AAA/CCC 恒定；BBB==raw）。
    for (symbol, i), (eo, eh, el, ec) in _EXPECTED_HFQ.items():
        row = _sym(real_panel, symbol).slice(i, 1)
        assert row.get_column("open").item() == pytest.approx(eo, abs=1e-9)
        assert row.get_column("high").item() == pytest.approx(eh, abs=1e-9)
        assert row.get_column("low").item() == pytest.approx(el, abs=1e-9)
        assert row.get_column("close").item() == pytest.approx(ec, abs=1e-9)


# ————————————————————————————————————————————————————————————————————————
# 7. O/H/L/C 一致性：四列同乘同一 factor → 日内比值不变 + OHLC 序不破；只调 close 变异打红。
# ————————————————————————————————————————————————————————————————————————
def test_07_ohlc_all_four_same_factor(tmp_path, monkeypatch):
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    panel = load_market_panel("ashare_hs300")

    aaa = _sym(panel, "AAA")
    exdiv = aaa.filter(pl.col("ts") == _AAA_EXDIV_TS)
    o = exdiv.get_column("open").item()
    h = exdiv.get_column("high").item()
    low = exdiv.get_column("low").item()
    c = exdiv.get_column("close").item()
    # 四列各自 == raw×factor（只调 close 变异 → open/high/low 停在 raw → 这三条红）。
    assert o == pytest.approx(8.0 * 1.25, abs=1e-9)   # 10.0
    assert h == pytest.approx(8.4 * 1.25, abs=1e-9)   # 10.5
    assert low == pytest.approx(7.6 * 1.25, abs=1e-9)  # 9.5
    assert c == pytest.approx(8.0 * 1.25, abs=1e-9)   # 10.0
    # 日内比值 factor 相消不变：hfq high/close == raw high/close（只调 close → high 未缩、比值变 → 红）。
    assert h / c == pytest.approx(8.4 / 8.0, abs=1e-9)
    assert low / c == pytest.approx(7.6 / 8.0, abs=1e-9)
    # OHLC 序不变式（复权后 high 仍是最大、low 仍是最小）——只调 close 会让 close>high → 红。
    for row in panel.iter_rows(named=True):
        hi, lo = row["high"], row["low"]
        assert hi >= max(row["open"], row["close"], lo) - 1e-9
        assert lo <= min(row["open"], row["close"], hi) + 1e-9


# ————————————————————————————————————————————————————————————————————————
# 8. §16 守卫：拒 cohort asset id；perf_baseline_claim=False；无 perf measured。
# ————————————————————————————————————————————————————————————————————————
def test_08_section16_reject_cohort_no_perf_claim(tmp_path):
    # (a) 显式拒绝 forbidden_confirmatory 幸存者偏差 cohort。
    assert _COHORT_FORBIDDEN_ID in FORBIDDEN_SOURCE_ASSET_IDS
    assert HS300_RESEARCH_ASSET_ID != _COHORT_FORBIDDEN_ID
    with pytest.raises(PanelSourceError, match="forbidden_confirmatory"):
        _ensure_asset_allowed(_COHORT_FORBIDDEN_ID)
    # 合法源不被误拒。
    _ensure_asset_allowed(HS300_RESEARCH_ASSET_ID)
    _ensure_asset_allowed("equity_cn")

    # (b) 行为：即使 registry 里只有 cohort（无 research_universe），读侧也绝不取它 → 合成兜底。
    _register_real_asset(tmp_path, dataset_id=_COHORT_FORBIDDEN_ID)
    res_cohort_only = resolve_panel_source("ashare_hs300", data_root=tmp_path)
    assert res_cohort_only.kind == "synthetic"
    assert res_cohort_only.asset_id is None

    # (c) real resolution perf_baseline_claim=False 且无任何 perf measured 字段。
    _register_real_asset(tmp_path)  # 追加合法源
    real = resolve_panel_source("ashare_hs300", data_root=tmp_path)
    assert real.kind == "real"
    assert real.perf_baseline_claim is False
    assert not hasattr(real, "measured")
    assert "measured" not in real.as_provenance()
    assert all("measured" not in k for k in real.as_provenance())


# ————————————————————————————————————————————————————————————————————————
# 9.（硬化）present-detection：genuinely-absent（无 registry / latest=None）与 verdict≠pass → 合成兜底；
#    但【已登记+verdict=pass 却在册文件缺失】按 FIX-2 收紧为 fail-closed raise（绝不静默降级合成）。
# ————————————————————————————————————————————————————————————————————————
def test_09_present_detection_negatives_fall_back_synthetic(tmp_path):
    # 无 registry 文件。
    assert resolve_panel_source("ashare_hs300", data_root=tmp_path / "nope").kind == "synthetic"

    # registry 存在但无该 asset（latest=None）。
    root_empty_reg = tmp_path / "emptyreg"
    DatasetRegistry(root_empty_reg / "datasets" / "registry.jsonl")  # 建空 registry
    assert resolve_panel_source("ashare_hs300", data_root=root_empty_reg).kind == "synthetic"

    # quality_verdict != pass（种一条会 fail 的 GE 规则）→ 合成兜底。
    root_fail = tmp_path / "verdictfail"
    _register_real_asset(
        root_fail,
        rules=[GERule(column="close", rule_type="value_range", params={"min": 0, "max": 1})],
    )
    res_fail = resolve_panel_source("ashare_hs300", data_root=root_fail)
    assert res_fail.kind == "synthetic", "verdict=fail 必须回落合成，不得当真实读"

    # file_paths 某文件运行时缺失（注册后删 bars.parquet）：**行为已按 FIX-2 收紧**。
    # 旧行为(纸门)：present-detection miss → 静默降级合成 → 一次真实回测被洗成合成、污染研究口径。
    # 新行为(fail-closed)：已登记 + verdict=pass = 声称已验证 hfq，其在册文件缺 → raise，绝不降级合成。
    # （genuinely-absent[无 registry / 该 asset 从未登记] 仍回落合成——见上方 case 与 test_f3_10。）
    root_missing = tmp_path / "filemiss"
    _register_real_asset(root_missing, drop_files=("bars.parquet",))
    with pytest.raises(PanelSourceError, match="缺失"):
        resolve_panel_source("ashare_hs300", data_root=root_missing)


# ————————————————————————————————————————————————————————————————————————
# 10.（硬化）D-11-VOLUME-ADJ=raw：volume 不复权，逐行 == raw；provenance 声明 none。
# ————————————————————————————————————————————————————————————————————————
def test_10_volume_stays_raw(tmp_path, monkeypatch):
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    panel = load_market_panel("ashare_hs300")

    aaa_vol = _sym(panel, "AAA").get_column("volume").to_list()
    # AAA volume raw = [1000..1400]，即便 factor=1.25 也 **不** 被乘（若误乘则 1250.. → 红）。
    assert aaa_vol == pytest.approx([1000.0, 1100.0, 1200.0, 1300.0, 1400.0], abs=1e-9)
    ccc_vol = _sym(panel, "CCC").get_column("volume").to_list()
    assert ccc_vol == pytest.approx([200.0, 210.0, 220.0, 230.0, 240.0], abs=1e-9)
    assert resolve_panel_source("ashare_hs300", data_root=tmp_path).volume_adjustment == "none"


def test_11_resolution_is_frozen_dataclass_contract():
    """PanelResolution 是冻结 dataclass，8 键 provenance 契约稳定（防字段漂移）。"""
    res = resolve_panel_source("equity_cn")
    assert isinstance(res, PanelResolution)
    with pytest.raises(Exception):
        res.kind = "real"  # frozen：不可变


# ════════════════════════════════════════════════════════════════════════════
# F3 · 读侧完整性门（读价【之前】拿磁盘字节 re-verify 注册 manifest 的 per-file sha256）。
#
# 缺口：`_load_real_panel` 过去只按 file_paths 读 bars/adj 落盘文件应用 hfq，从不复核磁盘字节 vs
# 注册 manifest → 漂移/损坏/误替换的 lake 文件被静默当「已验证 hfq 真实数据」端上去。
# F3 = 读价前 re-verify（非空 + 覆盖 + 路径门 + per-file sha256；不符/缺/空/未覆盖 → fail-closed raise）。
#
# 诚实威胁模型（防夸大 · §3）：F3 是【纵深防御】，抓「受信 registry+manifest 下，在册文件的
# DRIFT/损坏/非对抗性误替换 + partial/empty manifest 洗白」；它【不】抓 manifest+lake co-tamper
# （本研究资产 manifest 未签名、可覆写；签名收据只属被读侧 forbidden 的 benchmark cohort）与
# 同 size+mtime 的并发原子替换（TOCTOU，仅 best-effort re-stat 收窄，不闭合）——详见
# `_verify_real_manifest` docstring 的残余风险 (a)/(b)/(c)。
#
# 每测带【变异】牙口（§2）：注释 `_load_real_panel` 里的 `_verify_real_manifest(resolution)`（整门失效）
# 或 `_verify_real_manifest` 内的 `_assert_manifest_covers_reads`（仅 FIX-1 非空/覆盖/路径门失效）→ 对应
# pytest.raises 变「DID NOT RAISE」/ 变 polars 解析错 → 打红。变异是交付时按 HANDOFF Verify 段实跑的
# 一次性核对（非仓库内常驻证据）；哪些用例翻红见交付报告变异段。
# ════════════════════════════════════════════════════════════════════════════


def _raw_bars_path(root: Path) -> Path:
    return root / "raw" / "bars.parquet"


def _raw_adj_path(root: Path) -> Path:
    return root / "raw" / "adj_factors.parquet"


def _load_manifest_json(version) -> dict:
    """读注册时落盘的 on-disk manifest JSON（供 F3 对抗用例改写 entry 集）。"""
    return json.loads(Path(version.manifest_path).read_text(encoding="utf-8"))


def _write_manifest_json(version, data: dict) -> None:
    """把改写后的 manifest 落回原路径（模拟 manifest 未签名·可覆写这一诚实残余）。"""
    Path(version.manifest_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_f3_01_pristine_real_load_ok_hfq_preserved(tmp_path, monkeypatch):
    """F3 不破坏基线：pristine 注册 → load 正常返回 hfq 面板（15 行、oracle 恒定）。"""
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    panel = load_market_panel("ashare_hs300")  # F3 verify 通过（字节未动）→ 照常读
    assert panel.height == 15
    assert set(panel["symbol"].unique().to_list()) == {"AAA", "BBB", "CCC"}
    # hfq 行为仍被保留（AAA close 恒 10.0，跨除权日零跳变）。
    assert _sym(panel, "AAA").get_column("close").to_list() == pytest.approx([10.0] * 5, abs=1e-9)


def test_f3_02_tampered_bars_raises_integrity(tmp_path, monkeypatch):
    """篡改 bars.parquet（改写成 schema 相同、值不同的【合法】parquet）→ sha256 不符 → fail-closed raise。

    变异牙口：移除 `_verify_real_manifest` 门 → 被篡 bars 被静默读入并当 hfq 真实数据返回 →
    本 pytest.raises 变「DID NOT RAISE」→ 打红（证明门有牙、非纸门）。
    """
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    # 模拟被换库/被改的 lake 文件：合法 parquet、present-detection 照过、GE verdict 仍 pass（注册期已定），
    # 唯有磁盘字节 sha256 变 → 只能靠 F3 抓。
    tampered = _bars().with_columns((pl.col("close") * 2.0 + 1.0).alias("close"))
    tampered.write_parquet(_raw_bars_path(tmp_path))
    with pytest.raises(PanelSourceError, match="完整性"):
        load_market_panel("ashare_hs300")


def test_f3_03_tampered_adj_raises_integrity(tmp_path, monkeypatch):
    """篡改 adj_factors.parquet → sha256 不符 → raise。

    变异牙口：移 F3 门 → 静默用被篡 factor 算出错误 hfq 并返回 → pytest.raises 变 DID-NOT-RAISE → 红。
    """
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    tampered = _adj().with_columns((pl.col("adj_factor") + 0.5).alias("adj_factor"))
    tampered.write_parquet(_raw_adj_path(tmp_path))
    with pytest.raises(PanelSourceError, match="完整性"):
        load_market_panel("ashare_hs300")


def test_f3_04_missing_manifest_fail_closed_not_synthetic(tmp_path, monkeypatch):
    """缺 manifest 的真实 resolution → fail-closed raise，【绝不】降级合成（decision C）。"""
    # (a) on-disk manifest 文件被删：走 full public path。present-detection 不查 manifest → 仍判 real；
    #     F3 检出 manifest 文件缺 → raise（而非静默回落 synthetic）。
    version = _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    assert version.manifest_path and Path(version.manifest_path).is_file()
    Path(version.manifest_path).unlink()
    assert resolve_panel_source("ashare_hs300", data_root=tmp_path).kind == "real"  # 仍 real（非兜底）
    with pytest.raises(PanelSourceError, match="manifest"):
        load_market_panel("ashare_hs300")

    # (b) manifest_path=None 的真实 resolution（模拟 manifest 特性前的旧 registry 行）→ raise，不降级合成。
    root_b = tmp_path / "b"
    _register_real_asset(root_b)
    res = resolve_panel_source("ashare_hs300", data_root=root_b)
    assert res.kind == "real"
    res_none = dataclasses.replace(res, manifest_path=None)
    with pytest.raises(PanelSourceError, match="manifest"):
        _load_real_panel(res_none)  # 不可验证真实必须 refuse，绝不返回合成/污染面板


def test_f3_05_verify_before_parse_no_tampered_rows_leak(tmp_path, monkeypatch):
    """完整性门在 `pl.read_parquet` 【之前】：写入非法 parquet 字节 → 抛的是完整性错、不是 parquet 解析错。

    证明篡改字节从未被解析成面板行（零污染泄漏）。变异牙口：移 F3 门 → read_parquet 抛 polars 解析异常
    （非 PanelSourceError）→ 本 pytest.raises(PanelSourceError, match="完整性") 打红。
    """
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    # 非 parquet 垃圾字节：若门失效被 read_parquet 先碰到 → polars ComputeError（≠ 完整性错）。
    _raw_bars_path(tmp_path).write_bytes(b"NOT_A_PARQUET_tampered_" + b"\x00\x01\x02" * 64)
    with pytest.raises(PanelSourceError, match="完整性") as exc_info:
        load_market_panel("ashare_hs300")
    # 抛的确是「读价前」的完整性门（措辞钉死），不是下游 parquet 解析或 hfq 计算错。
    assert "manifest sha256 不符" in str(exc_info.value)


def test_f3_06_absent_registry_no_f3_regression(tmp_path, monkeypatch):
    """无 registry（absent）→ 合成分支，F3 门根本不触发；与 equity_cn 逐字节相等（零回归）。"""
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path / "empty"))
    ashare = load_market_panel("ashare_hs300")
    equity = load_market_panel("equity_cn")
    assert resolve_panel_source("ashare_hs300", data_root=tmp_path / "empty").kind == "synthetic"
    assert_frame_equal(ashare, equity)  # absent 逐字节兜底到合成 sample
    assert hashlib.sha256(equity.write_csv().encode()).hexdigest() == _PRECHANGE_EQUITY_CN_CSV_SHA256


# ————————————————————————————————————————————————————————————————————————
# FIX 1 · partial/empty-manifest fail-open 收口（verify_manifest 空过 + 不覆盖将读文件的洞）。
# ————————————————————————————————————————————————————————————————————————
def test_f3_07_empty_manifest_vacuous_pass_now_raises(tmp_path, monkeypatch):
    """空 manifest（0 entry）在真实 resolution 上 → raise。

    修复【前】：`verify_manifest` 对空 manifest 返回 `(True, [])` → 未被任何 entry 覆盖的磁盘字节
    全程不校验 → 「已验证 hfq 真实」名不副实（vacuous pass）。修复【后】：非空门 fail-closed。
    变异牙口：注释 `_assert_manifest_covers_reads` → 空 manifest 放行（数据文件本身 pristine → load 成功）
    → 本 pytest.raises 变「DID NOT RAISE」→ 红。
    """
    version = _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    data = _load_manifest_json(version)
    data["files"] = []  # 清空 entry（数据文件不动 —— 纯 vacuous-pass 攻击面）
    _write_manifest_json(version, data)
    with pytest.raises(PanelSourceError, match="完整性") as exc:
        load_market_panel("ashare_hs300")
    assert "manifest 为空" in str(exc.value)  # 钉死是「非空门」而非下游 sha256 门


def test_f3_08_partial_manifest_plus_schema_valid_tamper_raises(tmp_path, monkeypatch):
    """从合法 manifest 删掉 bars entry + 用 schema 合法的篡改 parquet 覆盖 bars.parquet → raise。

    这正是 `verify_manifest` 单独抓不到的洞（codex FIX-1 攻击）：剩余 (adj/susp) entry 全对 → verify
    空过，而删了 entry 的篡改 bars 却被读入当真实数据。FIX-1 覆盖门：bars 是将读文件却无 entry → fail-closed。
    变异牙口：注释 `_assert_manifest_covers_reads` → 篡改 bars 被静默读入 → 本 pytest.raises 变 DID-NOT-RAISE → 红。
    """
    version = _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    data = _load_manifest_json(version)
    data["files"] = [
        f for f in data["files"] if not str(f["relative_path"]).endswith("bars.parquet")
    ]
    _write_manifest_json(version, data)
    # schema 合法但值不同的篡改 bars（present-detection 照过、注册期 GE verdict 仍 pass，只有字节 sha256 变）。
    tampered = _bars().with_columns((pl.col("close") * 2.0 + 1.0).alias("close"))
    tampered.write_parquet(_raw_bars_path(tmp_path))
    with pytest.raises(PanelSourceError, match="未覆盖") as exc:
        load_market_panel("ashare_hs300")
    assert "bars.parquet" in str(exc.value)


def test_f3_09_manifest_unsafe_entry_paths_raise(tmp_path):
    """manifest entry 的 relative_path 绝对 / `..` 逃逸 / 重复 → fail-closed raise（防路径穿越/洗白 · FIX 1）。

    每 sub-case 造「hash 自洽 + 目标存在」的恶意 entry，且不动 bars/adj/susp（覆盖门过）→ 只有路径门能抓：
    `verify_manifest` 单独会去 root 外哈希那个自洽 decoy 并放行。
    变异牙口：注释 `_assert_manifest_covers_reads` → verify 放行 → 本 pytest.raises 变 DID-NOT-RAISE → 红。
    """
    # (a) `..` 逃逸：root=<dotdot>/raw；加一条 ../decoy.parquet（指向 <dotdot>/decoy.parquet、hash 自洽）。
    root_dd = tmp_path / "dotdot"
    v = _register_real_asset(root_dd)
    decoy = root_dd / "decoy.parquet"
    decoy.write_bytes(b"decoy-dotdot-bytes")
    data = _load_manifest_json(v)
    data["files"].append(
        {
            "relative_path": "../decoy.parquet",
            "sha256": hashlib.sha256(decoy.read_bytes()).hexdigest(),
            "size_bytes": decoy.stat().st_size,
            "row_count": None,
        }
    )
    _write_manifest_json(v, data)
    with pytest.raises(PanelSourceError, match="路径"):
        resolve_and_load(root_dd)

    # (b) 绝对路径 entry（指向存在的 decoy2、hash 自洽）→ raise。
    root_abs = tmp_path / "abs"
    v2 = _register_real_asset(root_abs)
    decoy2 = root_abs / "decoy2.parquet"
    decoy2.write_bytes(b"decoy-abs-bytes")
    data2 = _load_manifest_json(v2)
    data2["files"].append(
        {
            "relative_path": str(decoy2),
            "sha256": hashlib.sha256(decoy2.read_bytes()).hexdigest(),
            "size_bytes": decoy2.stat().st_size,
            "row_count": None,
        }
    )
    _write_manifest_json(v2, data2)
    with pytest.raises(PanelSourceError, match="路径"):
        resolve_and_load(root_abs)

    # (c) 重复 relative_path（复制第一条 entry）→ raise。
    root_dup = tmp_path / "dup"
    v3 = _register_real_asset(root_dup)
    data3 = _load_manifest_json(v3)
    data3["files"].append(dict(data3["files"][0]))
    _write_manifest_json(v3, data3)
    with pytest.raises(PanelSourceError, match="重复"):
        resolve_and_load(root_dup)


# ————————————————————————————————————————————————————————————————————————
# FIX 2 · 删文件→静默降级合成 收口 + 保留 genuinely-absent→synthetic（CI graceful-degrade）。
# ————————————————————————————————————————————————————————————————————————
def test_f3_10_registered_pass_missing_file_raises_absent_still_synthetic(tmp_path):
    """已登记+verdict=pass 的真实资产、在册文件被删 → resolve 即 fail-closed raise（绝不降级合成）；
    genuinely-absent（无 registry）仍回落 synthetic（CI degrade 保留、未被 FIX-2 误伤）。"""
    # (a) 已登记+pass+删 bars → resolve_panel_source 直接 raise（不再静默 synthetic）。
    root_del = tmp_path / "deleted"
    _register_real_asset(root_del, drop_files=("bars.parquet",))
    with pytest.raises(PanelSourceError, match="缺失"):
        resolve_panel_source("ashare_hs300", data_root=root_del)
    # (b) genuinely-absent（无 registry 文件）→ synthetic（CI graceful-degrade 保留）。
    assert (
        resolve_panel_source("ashare_hs300", data_root=tmp_path / "absent").kind
        == "synthetic"
    )
    # (c) 登记但 verdict!=pass → 仍 synthetic（registry 受信，未过质检非可用真实源，≠ 静默降级已验证真实）。
    root_fail = tmp_path / "verdictfail"
    _register_real_asset(
        root_fail,
        rules=[GERule(column="close", rule_type="value_range", params={"min": 0, "max": 1})],
    )
    assert (
        resolve_panel_source("ashare_hs300", data_root=root_fail).kind == "synthetic"
    )


# ————————————————————————————————————————————————————————————————————————
# FIX 4 · TOCTOU（best-effort 收窄，不闭合）：verify→read 之间并发替换、size/mtime 变即抓。
# ————————————————————————————————————————————————————————————————————————
def test_f3_11_toctou_concurrent_swap_during_read_best_effort(tmp_path, monkeypatch):
    """verify 通过后、pl.read_parquet 期间文件被并发替换(size/mtime 变) → 读后 re-stat raise。

    诚实边界：仅**收窄** TOCTOU 窗口；同 size+mtime 的原子替换仍不可分辨（不宣称闭合，见残余风险 b）。
    构造：monkeypatch panel_source 用的 pl.read_parquet，在读 bars 时先把 bars 换成不同 size 的合法 parquet
    再委托真读 → 读后快照 ≠ 读前快照 → raise。
    """
    _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    import app.factor_factory.panel_source as ps

    real_read = ps.pl.read_parquet

    def _swapping_read(path, *args, **kwargs):
        if str(path).endswith("bars.parquet"):
            _bars().head(3).write_parquet(path)  # 读中途原子替换成不同 size 的合法 parquet
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(ps.pl, "read_parquet", _swapping_read)
    with pytest.raises(PanelSourceError, match="并发替换"):
        load_market_panel("ashare_hs300")


# ————————————————————————————————————————————————————————————————————————
# FIX A · 单快照 manifest 校验（收口 split-snapshot race）：覆盖门与 sha256 门共用【一次】读盘解析。
# ————————————————————————————————————————————————————————————————————————
def test_f3_12_manifest_single_snapshot_no_split_read_swap(tmp_path, monkeypatch):
    """single-snapshot 铁证：F3 对 manifest 文件只读【一次】，覆盖门与 per-file sha256 门跑在【同一】
    parsed 对象上 —— verify→hash 之间的 manifest swap 无从下手（收口 split-snapshot race）。

    攻击（仅【两读】实现才成立）：磁盘 bars 被篡改（sha256 与【完整】manifest 记录不符）。令 manifest
    文件第 1 次读（覆盖门）返回【完整】版（bars entry 在 → 覆盖过），第 2 次读（旧 verify_manifest 会
    重开读）返回【删了 bars entry】版（bars 不被哈希）→ 篡改 bars 既过覆盖门又逃 sha256 → 静默读入。
    单快照下二者共用同一次读盘：覆盖门看到完整版 → sha256 门在同一对象上撞 bars sha 不符 → raise。

    双牙口：
    - 行为牙：single-snapshot → PanelSourceError（完整性）；回退两读则 swap 生效 → DID NOT RAISE。
    - 计数牙：F3 只读 manifest 文件【一次】(reads==1)；回退两读则第 2 次重开 → reads==2 → assert 红。
    变异（FIX-A 回退）：把 `_verify_real_manifest` 末尾 `verify_manifest_obj(parsed, root)` 改回
    `verify_manifest(mp, root)`（第二次读盘）→ 这两条 assert 同时翻红（DID NOT RAISE + reads==2）。
    """
    version = _register_real_asset(tmp_path)
    monkeypatch.setenv("QUANTBT_DATA_ROOT", str(tmp_path))
    manifest_path = Path(version.manifest_path)

    full = _load_manifest_json(version)  # 完整：bars/adj/susp 三 entry
    partial = dict(full)
    partial["files"] = [
        f for f in full["files"] if not str(f["relative_path"]).endswith("bars.parquet")
    ]
    full_json = json.dumps(full, ensure_ascii=False)
    partial_json = json.dumps(partial, ensure_ascii=False)

    # 磁盘 bars 被篡改（schema 合法、值不同 → sha256 与【完整】manifest 记录不符；present-detection 照过）。
    tampered = _bars().with_columns((pl.col("close") * 2.0 + 1.0).alias("close"))
    tampered.write_parquet(_raw_bars_path(tmp_path))

    # spy：对【manifest 文件】第 1 次读返回完整版（覆盖门想看到的），第 2 次起返回 partial 版（两读实现的
    #      sha 门会重开读到它、漏掉被篡 bars）。非 manifest 路径一律走真实 read_text（registry 等不受影响）。
    real_read_text = Path.read_text
    reads = {"n": 0}

    def _spy_read_text(self, *args, **kwargs):
        if str(self) == str(manifest_path):
            reads["n"] += 1
            return full_json if reads["n"] == 1 else partial_json
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _spy_read_text)

    with pytest.raises(PanelSourceError, match="完整性"):
        load_market_panel("ashare_hs300")
    # 单快照铁证：整条 F3 路径对 manifest 文件只读了一次（两读实现下这里会是 2）。
    assert reads["n"] == 1, f"manifest 被读 {reads['n']} 次（期望 1）——split-snapshot 回归"
