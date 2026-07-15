"""F2 · 因子评测类端点的「按 factor + market 取 panel」共同前置数据源层。

为什么单独一层（红线：panel 强制复权 + 正确 forward-return 滞后，绝不前视穿越）：
所有 IC / IC衰减 / 分层回测 / audit 端点都吃同一份 polars panel
(symbol, ts, close, volume, ...)。把「取 panel + 校正 ts 列 + 复权口径 + forward
return 滞后」收成单一入口，杜绝各端点各自手搓 panel 时漏 shift（前视）或漏复权。

真实 vs 合成（§11 PIT 读侧接线，design: pit-adjustment-readside-design-20260715）：
- market `ashare_hs300` = 真实研究面 union（raw bars + adj_factor 分表、无幸存者偏差、
  `hs300_research_universe_10y`）。registry present（latest≠None + quality_verdict=pass +
  file_paths 全 is_file）→ 返回**后复权 hfq** 连续价 panel；absent（无 lake / CI）→ 逐字节
  回落到与 `equity_cn` 相同的合成 ETF sample（零行为变更）。
- `equity_cn` / `crypto` = 合成 sample 唯一落点，**永不**查 registry、口径完全不变。
- 复权数学（承重 landmine · §16「未复权价误喂成交层」向量）：
  `hfq_col = raw_col × adj_factor` for col ∈ {open, high, low, close}（四列同乘同一 factor，
  日内比值 factor 相消不变）；volume 保持 raw（D-11-VOLUME-ADJ=raw，声明 volume_adjustment=none）。
  left-join 缺因子 → **fail-closed raise**（绝不 drop、绝不 ffill）；adj_factor<=0 → raise。
- PIT 诚实限界：Tushare 落盘 factor 无逐行 known_at/vintage → 只声明 hfq（PIT-safe 方向）+
  标 `pit_limit=no_per_row_factor_vintage`，**不**声称完整 bitemporal PIT。
- §16 隔离：本层是研究/回测 env（≠ perf harness `measure_hs300_10y_daily_read`，物理隔离的独立
  consumer）。provenance 恒带 `perf_baseline_claim=False`；本层**永不** set perf `measured=True`、
  不喂执行层；`hs300_daily_10y_readbench_cohort`（forbidden_confirmatory 幸存者偏差）显式拒。

诚实边界：
- 合成 sample 价格本身连续无除权跳变（等价后复权连续价），不谎称是真实复权数据
  （provenance.adjustment=synthetic_continuous）。
- forward return **只**经 `ic.attach_forward_returns`（用 `close.shift(-h)`，正向滞后、
  按 symbol 分组），本层不自造 forward 列——单一滞后源，防某端点偷偷 shift(0) 前视。
- `ts` 列：合成 panel 用 `t_index`（整数序，非日历）；真实 panel 用 tushare 日历 Datetime。
  本层统一 alias 成 `ts`，让下游 `group_by("ts")` 截面 IC 正常工作。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ..datasets.samples import load_sample
from ..paths import DATA_ROOT

# market（前端 equity_cn / crypto）→ 评测用 sample_id。
# A股=合成 ETF 多标的 252d（截面 IC 需多 symbol）；加密=BTC+ETH 拼成多标的。
# ashare_hs300=真实研究面 key，registry absent 时回落到与 equity_cn **同一** 合成 sample
# （逐字节等于 load_market_panel("equity_cn")）；equity_cn 映射保持完全不动（D-11-MARKET-KEY=B）。
_MARKET_SAMPLE: dict[str, str] = {
    "equity_cn": "ashare_etf_daily_252d",
    "crypto": "btc_perp_daily_365d",
    "ashare_hs300": "ashare_etf_daily_252d",
}

# 真实研究面 union——读侧唯一合法真实源（raw bars + adj_factor 分表、无幸存者偏差）。
HS300_RESEARCH_ASSET_ID = "hs300_research_universe_10y"
# market → 真实资产 id：仅这些 market 会查 registry；其余（equity_cn/crypto）永远合成、永不触 registry。
_REAL_MARKETS: dict[str, str] = {"ashare_hs300": HS300_RESEARCH_ASSET_ID}
# §16 红线：幸存者偏差 confirmatory cohort（research_use=forbidden_confirmatory），禁喂因子研究读侧。显式拒。
FORBIDDEN_SOURCE_ASSET_IDS: frozenset[str] = frozenset({"hs300_daily_10y_readbench_cohort"})

# 后复权 hfq 需同乘同一 factor 的四价列（volume 不在内——D-11-VOLUME-ADJ=raw）。
_HFQ_PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")

REQUIRED_COLUMNS: frozenset[str] = frozenset({"symbol", "ts", "close"})


class PanelSourceError(ValueError):
    """panel 数据源口径违规（缺市场 / 缺列 / 复权未声明 / fail-closed 数据完整性拒绝）。"""


@dataclass(frozen=True)
class PanelResolution:
    """一次 panel 取数的来源裁决 + 诚实 provenance（real vs synthetic 单一判定源）。

    `as_provenance()` 返回 design 约定的 8 键 provenance channel；其余字段（market/asset_id/
    bars_path/adj_factors_path/sample_id）是内部接线，不进 provenance。**恒无** 任何 perf
    `measured` 字段，`perf_baseline_claim` 恒 False（§16：读侧永不自升为 perf baseline）。
    """

    kind: str                       # "real" | "synthetic"
    market: str
    universe: str                   # real=dataset_id；synthetic=sample_id（或 market）
    asset_id: str | None            # real dataset_id；synthetic=None
    dataset_version_ref: str | None  # real=version_id；synthetic=None
    adjustment: str                 # real="hfq"；synthetic="synthetic_continuous"
    volume_adjustment: str          # 恒 "none"（D-11-VOLUME-ADJ=raw）
    survivorship: str               # real="union_includes_delisted"；synthetic="not_applicable_synthetic"
    pit_limit: str | None           # real="no_per_row_factor_vintage"；synthetic=None
    perf_baseline_claim: bool       # 恒 False
    bars_path: str | None = None    # real 内部接线
    adj_factors_path: str | None = None
    sample_id: str | None = None    # synthetic 内部接线

    def as_provenance(self) -> dict[str, object]:
        """design 约定的 8 键 provenance channel（供端点/日志附带，不含内部路径）。"""

        return {
            "kind": self.kind,
            "dataset_version_ref": self.dataset_version_ref,
            "adjustment": self.adjustment,
            "volume_adjustment": self.volume_adjustment,
            "survivorship": self.survivorship,
            "universe": self.universe,
            "pit_limit": self.pit_limit,
            "perf_baseline_claim": self.perf_baseline_claim,
        }


def _ensure_asset_allowed(asset_id: str | None) -> None:
    """§16 守卫：拒绝 forbidden_confirmatory 幸存者偏差 cohort 进因子研究读侧。"""

    if asset_id in FORBIDDEN_SOURCE_ASSET_IDS:
        raise PanelSourceError(
            f"asset_id={asset_id!r} = forbidden_confirmatory 幸存者偏差 cohort，"
            f"禁喂因子研究读侧（§16 未复权/幸存者向量）。"
            f"研究面唯一合法真实源 = {HS300_RESEARCH_ASSET_ID!r}。"
        )


def _resolve_registry_path(data_root: str | Path | None = None) -> Path:
    """registry 路径解析（D-11-DATA-ROOT=b 单一源）：显式 data_root > env QUANTBT_DATA_ROOT > paths.DATA_ROOT。

    三者皆为「data 根目录」，registry 恒在 `<root>/datasets/registry.jsonl`。默认 base = **paths.DATA_ROOT**
    ——与 `main.py:734 DATASET_REGISTRY = DatasetRegistry(DATA_ROOT/"datasets"/"registry.jsonl")` **同一常量**，
    读侧与全 app 真实 registry 由构造对齐、绝不双源漂移（§1）；DATA_ROOT 本身已尊重 BACKTEST_DATA_ROOT
    （默认 <repo>/data）。QUANTBT_DATA_ROOT 是额外 override（测试注入 / 高阶指向），不设时恒随 DATA_ROOT。
    注意：本函数**不构造** DatasetRegistry（构造会 mkdir + 建空文件），只算路径，present-detection 先
    is_file() 再决定是否构造，避免在合成路径污染 data 目录。
    """

    if data_root is not None:
        base = Path(data_root).resolve()
    else:
        env = os.getenv("QUANTBT_DATA_ROOT")  # 测试注入 / 高阶指向；不设时恒随 DATA_ROOT
        base = Path(env).resolve() if env else DATA_ROOT  # DATA_ROOT 已 .resolve()——三支对称可比
    return base / "datasets" / "registry.jsonl"


def _present_real_version(registry_path: Path, asset_id: str):
    """present-detection：registry 文件在 AND latest≠None AND quality_verdict=pass AND
    file_paths 非空且全 is_file。任一 miss → None（→ 合成兜底）。返回 DatasetVersion 或 None。

    只在 registry 文件**已存在**时才构造 DatasetRegistry（构造有 mkdir + 建空文件副作用）。
    """

    if not registry_path.is_file():
        return None
    from ..data_quality import DatasetRegistry  # 惰性 import：零改 import-time 行为、避免循环依赖

    registry = DatasetRegistry(registry_path)
    version = registry.latest(asset_id)
    if version is None:
        return None
    if version.quality_verdict != "pass":
        return None
    file_paths = [str(fp) for fp in (version.file_paths or [])]
    if not file_paths:
        return None
    if not all(Path(fp).is_file() for fp in file_paths):
        return None
    return version


def _real_resolution(market: str, asset_id: str, version) -> PanelResolution:
    paths = {Path(fp).name: str(fp) for fp in version.file_paths}
    survivorship = (version.metadata or {}).get("survivorship", "union_includes_delisted")
    return PanelResolution(
        kind="real",
        market=market,
        universe=asset_id,
        asset_id=asset_id,
        dataset_version_ref=version.version_id,
        adjustment="hfq",
        volume_adjustment="none",
        survivorship=str(survivorship),
        pit_limit="no_per_row_factor_vintage",
        perf_baseline_claim=False,
        bars_path=paths.get("bars.parquet"),
        adj_factors_path=paths.get("adj_factors.parquet"),
        sample_id=None,
    )


def _synthetic_resolution(market: str) -> PanelResolution:
    sample_id = _MARKET_SAMPLE.get(market)
    return PanelResolution(
        kind="synthetic",
        market=market,
        universe=sample_id or market,
        asset_id=None,
        dataset_version_ref=None,
        adjustment="synthetic_continuous",
        volume_adjustment="none",
        survivorship="not_applicable_synthetic",
        pit_limit=None,
        perf_baseline_claim=False,
        bars_path=None,
        adj_factors_path=None,
        sample_id=sample_id,
    )


def resolve_panel_source(market: str, *, data_root: str | Path | None = None) -> PanelResolution:
    """裁决一个 market 取真实还是合成 panel，并给出诚实 provenance（不读价格、只解析来源）。

    仅 `_REAL_MARKETS`（ashare_hs300）会查 registry；其余 market 恒合成、永不触 registry。
    真实资产 id 先过 §16 守卫（拒 forbidden cohort），再走 present-detection；detection miss
    → 合成兜底。`data_root` 覆盖 registry 根（测试用）；None → env QUANTBT_DATA_ROOT / 默认 <repo>/data。
    """

    asset_id = _REAL_MARKETS.get(market)
    if asset_id is not None:
        _ensure_asset_allowed(asset_id)  # 防御：硬编码 id 恒合法，此守卫钉死意图 + 供对抗测试有牙
        registry_path = _resolve_registry_path(data_root)
        version = _present_real_version(registry_path, asset_id)
        if version is not None:
            return _real_resolution(market, asset_id, version)
    return _synthetic_resolution(market)


def _normalize_ts(panel: pl.DataFrame) -> pl.DataFrame:
    """统一时间列名为 `ts`（合成 sample 用 t_index 整数序，非日历；真实 panel 已是 ts）。"""

    if "ts" in panel.columns:
        return panel
    if "t_index" in panel.columns:
        return panel.rename({"t_index": "ts"})
    raise PanelSourceError("panel 缺时间列（既无 ts 也无 t_index）")


def _load_synthetic_panel(market: str) -> pl.DataFrame:
    """合成分支：现有逻辑逐字节不动（additive 包裹——absence 时零行为变更）。"""

    sample_id = _MARKET_SAMPLE.get(market)
    if sample_id is None:
        raise PanelSourceError(
            f"未知 market={market!r}（支持 {sorted(_MARKET_SAMPLE)}）"
        )
    panel = load_sample(sample_id)
    if panel is None or panel.is_empty():
        raise PanelSourceError(f"market={market} 对应 sample={sample_id} 无数据")
    # 加密：单 sample 只有 1 个 symbol，截面 IC 退化。拼 BTC+ETH 凑多标的截面。
    if market == "crypto":
        eth = load_sample("eth_perp_daily_365d")
        if eth is not None and not eth.is_empty():
            common = [c for c in panel.columns if c in eth.columns]
            panel = pl.concat([panel.select(common), eth.select(common)], how="vertical")
    panel = _normalize_ts(panel)
    missing = REQUIRED_COLUMNS - set(panel.columns)
    if missing:
        raise PanelSourceError(f"panel 缺必需列: {sorted(missing)}")
    return panel.sort(["symbol", "ts"])


def _load_real_panel(resolution: PanelResolution) -> pl.DataFrame:
    """真实分支：raw bars ⋈ adj_factor → 后复权 hfq 连续价 panel（fail-closed）。

    承重 landmine（§16「未复权价误喂成交层」直接向量）：
    - O/H/L/C 同乘同一 adj_factor（日内比值 factor 相消不变）；volume 保持 raw。
    - left-join 保留所有 bar 行；缺因子 → null_count>0 → **raise**（绝不 drop/ffill）。
    - adj_factor<=0 → raise。adj_factors 重复 (symbol,ts) → raise（防 join fan-out 污染 panel）。
    """

    _ensure_asset_allowed(resolution.asset_id)  # 纵深：真实读取前再拒一次 forbidden cohort
    bars_path = resolution.bars_path
    adj_path = resolution.adj_factors_path
    if not bars_path or not adj_path:
        raise PanelSourceError(
            f"真实资产 {resolution.asset_id!r} 缺 bars.parquet / adj_factors.parquet"
            f"（file_paths 结构异常，fail-closed 拒绝；present-detection 已过但资产口径不符）"
        )
    bars = pl.read_parquet(bars_path)
    adj = pl.read_parquet(adj_path)
    # 结构守卫：join key + adj_factor 列必须在（读到旧/错资产时纵深防御）。
    for name, frame, need in (
        ("bars", bars, ("symbol", "ts")),
        ("adj_factors", adj, ("symbol", "ts", "adj_factor")),
    ):
        col_missing = [c for c in need if c not in frame.columns]
        if col_missing:
            raise PanelSourceError(f"{name} 缺列 {col_missing}（真实资产口径异常，fail-closed）")
    price_missing = [c for c in _HFQ_PRICE_COLUMNS if c not in bars.columns]
    if price_missing:
        raise PanelSourceError(f"bars 缺价格列 {price_missing}（无法复权，fail-closed）")
    # adj_factors (symbol,ts) 必须唯一——否则 left-join 会 fan-out 行、静默污染 panel（纵深，防 join 畸变）。
    dup_adj = adj.height - adj.select(pl.struct(["symbol", "ts"]).n_unique()).item()
    if dup_adj > 0:
        raise PanelSourceError(
            f"adj_factors 含 {dup_adj} 条重复 (symbol,ts)——join 会 fan-out 污染 panel，fail-closed 拒绝"
        )
    # left-join：保留所有 bar 行；缺因子 → null → 下面 raise（fail-closed，绝不 drop/ffill）。
    joined = bars.join(
        adj.select(["symbol", "ts", "adj_factor"]), on=["symbol", "ts"], how="left"
    )
    null_factor = joined.get_column("adj_factor").null_count()
    if null_factor > 0:
        raise PanelSourceError(
            f"{null_factor} 行 bar 缺同日 adj_factor（fail-closed：不 drop 不 ffill——"
            f"drop=幸存者畸变+断 forward-return，ffill=陈旧 factor 污染除权日）"
        )
    # 非法 factor = 非有限(NaN/±inf) 或 <=0。polars 里 NaN **非** null（上面 null_count 漏它）
    # 且 `NaN<=0`/`+inf<=0` 均为 False → 必须显式 is_finite 拦，否则出 NaN/inf 价却标 hfq（假复权）。
    bad_factor = joined.select(
        ((~pl.col("adj_factor").is_finite()) | (pl.col("adj_factor") <= 0)).sum()
    ).item()
    if bad_factor > 0:
        raise PanelSourceError(
            f"{bad_factor} 行 adj_factor 非法（<=0 / NaN / ±inf——复权因子非正或非有限，fail-closed 拒绝）"
        )
    # 后复权 hfq：四价列同乘同一 factor；volume 保持 raw。drop 掉 factor 辅助列（provenance，非价格列）。
    panel = joined.with_columns(
        [(pl.col(c) * pl.col("adj_factor")).alias(c) for c in _HFQ_PRICE_COLUMNS]
    ).drop("adj_factor")
    panel = _normalize_ts(panel)
    missing = REQUIRED_COLUMNS - set(panel.columns)
    if missing:
        raise PanelSourceError(f"panel 缺必需列: {sorted(missing)}")
    return panel.sort(["symbol", "ts"])


def load_market_panel(market: str) -> pl.DataFrame:
    """按 market 取一份【已复权、多 symbol、含 ts】的评测 panel。

    复权口径：`ashare_hs300` registry present → 真实后复权 hfq 连续价（raw × adj_factor，四价列同乘、
    volume raw、缺因子 fail-closed）；absent → 逐字节回落到与 `equity_cn` 相同的合成 sample。
    `equity_cn`/`crypto` = 合成 sample（价格本身连续无除权跳变，等价后复权连续价），永不查 registry。
    返回列至少含 (symbol, ts, close[, volume, ...])。来源裁决 + 诚实 provenance 见 `resolve_panel_source`。
    """

    resolution = resolve_panel_source(market)
    if resolution.kind == "real":
        return _load_real_panel(resolution)
    return _load_synthetic_panel(market)


def factor_panel(
    market: str,
    formula: str,
    *,
    horizon: int = 5,
    factor_alias: str = "factor_value",
) -> pl.DataFrame:
    """取 market panel → 应用因子表达式 → 关联原始 OHLCV，供 IC/回测端点直用。

    返回 (ts, symbol, {factor_alias}, close[, volume...])，forward return 由下游
    `attach_forward_returns` 加（本层不前视）。
    """

    from .expression import evaluate_on_panel  # 局部 import 防循环

    base = load_market_panel(market)
    feat = evaluate_on_panel(base, formula, alias=factor_alias)
    # join 回原始价（forward return 要用 close），保持复权 close 单一源。
    merged = base.join(feat, on=["ts", "symbol"], how="inner")
    return merged.sort(["symbol", "ts"])


__all__ = [
    "FORBIDDEN_SOURCE_ASSET_IDS",
    "HS300_RESEARCH_ASSET_ID",
    "PanelResolution",
    "PanelSourceError",
    "REQUIRED_COLUMNS",
    "factor_panel",
    "load_market_panel",
    "resolve_panel_source",
]
