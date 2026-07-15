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

import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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
    bars_path/adj_factors_path/sample_id/manifest_path/source_file_paths）是内部接线，
    不进 provenance（as_provenance() 显式列 8 键，加字段不泄漏）。**恒无** 任何 perf
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
    # —— F3 读侧完整性门内部接线（real 分支）：绝不进 as_provenance()（保 8 键契约稳定）——
    manifest_path: str | None = None            # 注册时落的 on-disk manifest 路径（读侧 re-verify）
    source_file_paths: tuple[str, ...] = ()     # 注册 file_paths 全集（读侧按写侧同法重算 manifest root）

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
    """present-detection（三态 · FIX 2 堵「删文件→静默降级合成」）。返回 DatasetVersion / None / raise：

    - registry 文件缺 OR latest=None（该 asset 从未登记）→ **genuinely ABSENT** → None（→ 合成兜底）。
      CI / 无 lake 环境的 graceful-degrade 完全靠这条，**保留不动**。
    - 登记了但 quality_verdict != pass（未过质检）→ None（→ 合成）。registry 受信，未过质检的资产不是
      可用真实源，回落合成 —— 这不是「把已验证真实静默降级」，是「本就没有可用的已验证真实源」。
    - 登记了 **且 quality_verdict == pass**（= 声称「已验证 hfq 真实」）却 file_paths 为空 / 某在册文件
      运行时缺失 → **不降级合成**，raise PanelSourceError（fail-closed）。已通过质检的真实资产其落盘文件
      被删/损坏 = 数据损坏；静默改标成 synthetic 会把一次真实回测洗成合成、污染研究口径（decision C
      「绝不降级合成」/ RULES.project「未复权价误喂」邻域向量）。修法 = 修 lake 或登记新 version。

    只在 registry 文件**已存在**时才构造 DatasetRegistry（构造有 mkdir + 建空文件副作用）。

    诚实边界：本函数分辨的是「registry 受信前提下的 absent vs damaged」；registry 本身被篡改
    （改 file_paths / 洗 verdict）不在此门射程，属上层（受信/签名 registry）职责。
    """

    if not registry_path.is_file():
        return None  # genuinely ABSENT（无 registry）→ 合成兜底（CI graceful-degrade 保留）
    from ..data_quality import DatasetRegistry  # 惰性 import：零改 import-time 行为、避免循环依赖

    registry = DatasetRegistry(registry_path)
    version = registry.latest(asset_id)
    if version is None:
        return None  # genuinely ABSENT（该 asset 从未登记）→ 合成兜底
    if version.quality_verdict != "pass":
        return None  # 登记但未过质检 → 非可用真实源 → 合成（≠ 静默降级已验证真实；registry 受信）
    # 到此：已登记 + verdict=pass = 声称「已验证 hfq 真实」。其在册文件必须在，缺即 fail-closed（不降级合成）。
    file_paths = [str(fp) for fp in (version.file_paths or [])]
    missing = [fp for fp in file_paths if not Path(fp).is_file()]
    if not file_paths or missing:
        raise PanelSourceError(
            f"真实资产 {asset_id!r}（version={version.version_id!r}）已登记且 quality_verdict=pass"
            f"（声称已验证 hfq），但在册数据文件缺失/为空："
            f"file_paths={file_paths!r} missing={missing or '（file_paths 为空）'}"
            f"——fail-closed 拒绝：绝不把已验证真实资产静默降级成合成（污染研究口径）。"
            f"请修复 lake 文件或登记新 version。"
        )
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
        # F3 接线：读侧按【与写侧同一 file_paths 全集】重算 manifest root → re-verify per-file sha256。
        manifest_path=version.manifest_path,
        source_file_paths=tuple(str(fp) for fp in (version.file_paths or [])),
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


def _unsafe_manifest_rel(rel: str) -> bool:
    """manifest entry 的 relative_path 是否非法（防路径穿越/绝对路径逃出 root · FIX 1）。

    写侧恒用 ``Path.relative_to(root).as_posix()`` 落 entry → 合法 entry 必是「root 子树内 posix 相对
    路径」。攻击面：改 manifest JSON 把某 entry 指向绝对路径 / ``..`` 逃逸 → ``verify_manifest`` 会去
    root 外哈希一个攻击者可控/无关文件（其 hash 自洽即放行），而真正要读的 in-root 文件不被覆盖。
    故 fail-closed 拒：空 / 绝对 / 含 ``..`` / 反斜杠 / 盘符或流冒号。
    """

    if not rel or rel.strip() != rel:
        return True
    if os.path.isabs(rel):  # posix "/x"；windows "C:\x" 或 "\x"
        return True
    pp = PurePosixPath(rel)
    if pp.is_absolute() or ".." in pp.parts:
        return True
    if "\\" in rel or ":" in rel:  # windows 分隔符 / 盘符 / NTFS ADS
        return True
    return False


def _assert_manifest_covers_reads(manifest, root: Path, resolution: PanelResolution) -> None:
    """FIX 1 · partial/empty-manifest fail-open 收口：manifest 必须【非空】且【覆盖所有将读文件】。

    根因：``verify_manifest`` 只逐条核对 manifest 里**已列**的 entry —— 空 manifest → vacuous
    ``(True, [])``；缺某文件 entry → 那个文件根本不被哈希。攻击：把 bars entry 从 manifest 删掉 +
    换成 schema 合法的篡改 bars → 剩余 entry 全对 → verify 空过 → 篡改 bars 被读。故读价【前】显式断言：
    - manifest 非空（0 entry 直接拒，堵 vacuous pass）；
    - 每条 entry 的 relative_path 合法（非绝对/非 ``..``/非重复 —— 防路径穿越 + 防重复洗白）；
    - 所有【将读文件】(bars_path + adj_factors_path) 与【全体在册存在文件】(source_file_paths) 都能在
      manifest entry 集合里找到对应 relative_path（缺一即 fail-closed），否则被删 entry 的文件虽被读却从不校验。
    """

    files = list(manifest.files or [])
    if not files:
        raise PanelSourceError(
            f"数据完整性校验失败 dataset={resolution.asset_id!r} "
            f"version={resolution.dataset_version_ref!r}：注册 manifest 为空（0 entry）——"
            f"空 manifest 会让 sha256 校验 vacuous 空过，fail-closed 拒绝。"
        )
    rel_paths = [str(e.relative_path) for e in files]
    bad = [r for r in rel_paths if _unsafe_manifest_rel(r)]
    if bad:
        raise PanelSourceError(
            f"数据完整性校验失败 dataset={resolution.asset_id!r}：manifest entry 含非法 relative_path "
            f"{bad!r}（绝对路径 / ``..`` 逃逸 / 反斜杠 —— 防路径穿越，fail-closed 拒绝）。"
        )
    if len(set(rel_paths)) != len(rel_paths):
        raise PanelSourceError(
            f"数据完整性校验失败 dataset={resolution.asset_id!r}：manifest 含重复 relative_path "
            f"{rel_paths!r}（重复 entry 洗白，fail-closed 拒绝）。"
        )
    manifest_rel = set(rel_paths)
    # 将读文件 + 全体在册存在文件，都必须被 manifest 覆盖（表达为相对同一 root 的 posix path）。
    read_files = [p for p in (resolution.bars_path, resolution.adj_factors_path) if p]
    source_existing = [str(fp) for fp in resolution.source_file_paths if Path(fp).is_file()]
    must_cover = list(dict.fromkeys([*read_files, *source_existing]))  # 去重保序
    uncovered: list[str] = []
    for fp in must_cover:
        try:
            rel = Path(fp).relative_to(root).as_posix()
        except ValueError:
            uncovered.append(fp)  # 落在 root 子树外 —— manifest 与读路径结构不一致，fail-closed
            continue
        if rel not in manifest_rel:
            uncovered.append(fp)
    if uncovered:
        raise PanelSourceError(
            f"数据完整性校验失败 dataset={resolution.asset_id!r} "
            f"version={resolution.dataset_version_ref!r}：manifest 未覆盖将读文件 {uncovered!r}"
            f"（partial/空 manifest 洗白 —— 被删 entry 的文件会被读却从不校验，fail-closed 拒绝）。"
        )


def _file_stat_snapshot(paths: list[str]) -> dict[str, tuple[int, int]]:
    """(size, mtime_ns) 快照 —— 供 best-effort TOCTOU 窗口收窄（读前/读后比对 · FIX 4）。

    诚实边界：这【不】闭合 TOCTOU。它只抓「size 或 mtime 变了的并发替换」；同 size+mtime 的原子替换
    仍不可分辨（见 ``_verify_real_manifest`` 残余风险 b）。文件在读期间消失 → 记哨兵 → 下游判定为「变了」。
    """

    snap: dict[str, tuple[int, int]] = {}
    for p in paths:
        try:
            st = Path(p).stat()
            snap[str(p)] = (st.st_size, st.st_mtime_ns)
        except OSError:
            snap[str(p)] = (-1, -1)
    return snap


def _verify_real_manifest(resolution: PanelResolution) -> None:
    """F3 读侧完整性门：读磁盘价【之前】拿磁盘字节 re-verify 注册时落盘 manifest 的 per-file sha256。

    诚实威胁模型（防夸大 · RULES §3 诚实纪律；不说「保证 / 防篡改 / 不可变」）：
    本门是【纵深防御 / defense-in-depth】，射程 = 「在【受信】registry+manifest 前提下，在册文件的
    DRIFT / 损坏 / 位翻转 / schema 合法但字节漂移 / 非对抗性误替换」→ 读价前 sha256 不符即 raise。
    本研究资产（``hs300_pipeline.build_research_asset``）只落 registry + on-disk manifest、**不签收据**
    （签名 provenance 收据只由 ``build_chain`` 为 benchmark cohort ``hs300_daily_10y_readbench_cohort``
    产出，且该 cohort 被读侧 ``FORBIDDEN_SOURCE_ASSET_IDS`` 显式拒），故此处 manifest 是**可覆写、未签名**
    的 JSON。它【不是】对抗性真实性证明。

    如实声明的残余风险（本门【不】覆盖）：
    (a) manifest + lake 同时被改（co-tamper）：manifest 无签名可覆写，攻击者改文件再重写对应 sha256 即
        自洽通过 —— 真解药 = 对研究资产也签收据 + factor vintage(known_at) 落盘（后续卡）。
    (b) verify 与 ``pl.read_parquet`` 之间的并发原子替换（TOCTOU）：先哈希后重开文件，中途 swap 可逃逸。
        下游 ``_load_real_panel`` 有一道 best-effort 读后 re-stat（size/mtime 变即 raise）**收窄**该窗口，
        但同 size+mtime 的替换仍不可分辨 —— **不宣称**闭合 TOCTOU。
    (c) 本门不覆盖 present-detection 的 absent→synthetic 来源裁决（那是来源层，非完整性层）。

    fail-closed 判定：
    - manifest_path 缺失(None) 或 on-disk manifest 文件不存在 → raise（不可验证的真实 = 拒绝，绝不降级合成）。
    - manifest 为空 / 未覆盖将读文件 / entry 路径非法（绝对 / ``..`` / 重复）→ raise
      （``_assert_manifest_covers_reads``，堵 partial/empty vacuous pass）。
    - 磁盘字节 sha256 与 manifest 记录不符（在册文件被改写/损坏/漂移）→ raise（``verify_manifest_obj`` 单源哈希）。

    root 用【与写侧同一】``data_quality.dataset_manifest_root`` 算（防 relative_path 漂移致假阳性）；
    manifest 只解析【一次】，覆盖门与 sha256 门共用同一 parsed 对象（单快照，收口 verify→hash 之间的
    split-manifest swap）；哈希复用 ``data_hash.verify_manifest_obj`` → 内部 ``_sha256_file`` 单一源，绝不另造哈希。
    """

    # 惰性 import：零改 panel_source import-time 行为、避免循环依赖（沿用本模块既有惯例）。
    from ..data_hash.dataset_hash import DatasetManifest, verify_manifest_obj
    from ..data_quality import dataset_manifest_root

    manifest_path = resolution.manifest_path
    if not manifest_path or not Path(manifest_path).is_file():
        raise PanelSourceError(
            f"真实资产 {resolution.asset_id!r} (version={resolution.dataset_version_ref!r}) "
            f"无可验证的 on-disk manifest（manifest_path={manifest_path!r}）——真实分支声称已验证 hfq，"
            f"不可验证即 fail-closed 拒绝：绝不降级合成、绝不把未验证数据冒充已验证真实。"
        )
    mp = Path(manifest_path)
    # 解析【一次】：覆盖/路径门与 per-file sha256 门共用这【同一个】parsed 对象（单快照 → 收口
    # split-snapshot race）；哈希由 verify_manifest_obj 内部 _sha256_file 单源做，绝不另造哈希、绝不二次读盘。
    try:
        parsed = DatasetManifest.from_dict(json.loads(mp.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        raise PanelSourceError(
            f"真实资产 {resolution.asset_id!r} manifest 解析失败（{exc}）——fail-closed 拒绝。"
        ) from exc
    # root：与写侧同一函数算（防 relative_path 漂移致假阳性）；source_file_paths 空时退回将读文件。
    root_inputs = resolution.source_file_paths or tuple(
        p for p in (resolution.bars_path, resolution.adj_factors_path) if p
    )
    root = dataset_manifest_root(root_inputs)
    if root is None:
        raise PanelSourceError(
            f"真实资产 {resolution.asset_id!r} 无法定位 manifest root"
            f"（source_file_paths={resolution.source_file_paths!r} 无磁盘存在文件），fail-closed 拒绝。"
        )
    # FIX 1：非空 + 路径安全 + 覆盖（堵 partial/empty vacuous pass）。注释此行 = FIX-1 覆盖门失效（变异牙口）。
    _assert_manifest_covers_reads(parsed, root, resolution)
    # per-file sha256（复用 verify_manifest_obj → 内部 _sha256_file 单源）：跑在【同一】parsed 对象上，与
    # 覆盖门共用【单次读盘】快照 → verify→hash 之间无第二次读 manifest 的窗口（收口 split-snapshot：中途
    # swap manifest 让被删 entry 的篡改文件既过覆盖又逃哈希）。在册文件被改写/损坏/字节漂移 → raise。
    ok, mismatches = verify_manifest_obj(parsed, root)
    if not ok:
        raise PanelSourceError(
            f"数据完整性校验失败 dataset={resolution.asset_id!r} "
            f"version={resolution.dataset_version_ref!r}：磁盘字节与注册 manifest sha256 不符"
            f"（在册文件被改写/损坏/漂移 —— fail-closed 拒绝，绝不喂入 hfq 研究读侧）mismatches={mismatches}"
        )


def _load_real_panel(resolution: PanelResolution) -> pl.DataFrame:
    """真实分支：raw bars ⋈ adj_factor → 后复权 hfq 连续价 panel（fail-closed）。

    承重 landmine（§16「未复权价误喂成交层」直接向量）：
    - O/H/L/C 同乘同一 adj_factor（日内比值 factor 相消不变）；volume 保持 raw。
    - left-join 保留所有 bar 行；缺因子 → null_count>0 → **raise**（绝不 drop/ffill）。
    - adj_factor<=0 → raise。adj_factors 重复 (symbol,ts) → raise（防 join fan-out 污染 panel）。

    F3（纵深防御，**非**对抗性证明 —— 威胁模型/残余风险详见 ``_verify_real_manifest`` docstring）：
    读磁盘【之前】先过 ``_verify_real_manifest``（re-verify 注册 manifest 的 per-file sha256 + 非空/覆盖/
    路径门），在册文件 DRIFT/损坏/字节漂移 / 空·partial·缺 manifest → raise，污染字节绝不被 pl.read_parquet
    解析；读【后】另有一道 best-effort re-stat（size/mtime 变即 raise）**收窄** TOCTOU 窗口（不闭合）。
    """

    _ensure_asset_allowed(resolution.asset_id)  # 纵深：真实读取前再拒一次 forbidden cohort
    _verify_real_manifest(resolution)  # F3 完整性门在读价【之前】，fail-closed。注释此行 = 整门失效（变异牙口）
    bars_path = resolution.bars_path
    adj_path = resolution.adj_factors_path
    if not bars_path or not adj_path:
        raise PanelSourceError(
            f"真实资产 {resolution.asset_id!r} 缺 bars.parquet / adj_factors.parquet"
            f"（file_paths 结构异常，fail-closed 拒绝；present-detection 已过但资产口径不符）"
        )
    # FIX 4 best-effort：读【前】快照将读文件 (size,mtime)，读【后】比对 —— 收窄 verify→read 的并发替换
    # (TOCTOU) 窗口。诚实边界：同 size+mtime 的原子替换仍不可分辨，**不宣称**闭合（残余风险 b）。
    _pre_stat = _file_stat_snapshot([bars_path, adj_path])
    bars = pl.read_parquet(bars_path)
    adj = pl.read_parquet(adj_path)
    if _file_stat_snapshot([bars_path, adj_path]) != _pre_stat:
        raise PanelSourceError(
            f"数据完整性校验失败 dataset={resolution.asset_id!r}：读取期间将读文件被并发替换"
            f"（size/mtime 在 verify→read 之间变化 —— best-effort TOCTOU 收窄门，fail-closed 拒绝）。"
        )
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
