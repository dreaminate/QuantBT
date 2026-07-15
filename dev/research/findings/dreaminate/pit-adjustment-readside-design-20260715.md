# §11 PIT/复权 读侧接线设计（execution-ready，含 R6 解）2026-07-15

> 承 deep-opus 设计（会话内产出，本篇持久化免丢）+ R6 registry 路径已核。**correctness-critical**（§16
> 致命错误「未复权价误喂成交层」向量）。执行前走 duet + 逐 sub-slice 对抗验证。唯一改动点主要在
> `app/backend/app/factor_factory/panel_source.py`。

## 结论 + 真实源
`load_market_panel`（panel_source.py:49）= 合成 sample 唯一落点。接真实的正确源 = slice① 的**研究面 union**
`hs300_research_universe_10y`（raw bars + adj_factor **分表**、无幸存者、`adjustment_policy=
raw_plus_adj_factor_no_prejoin`，hs300_pipeline.py:768）。**显式拒** `hs300_daily_10y_readbench_cohort`
（`research_use=forbidden_confirmatory`,幸存者偏差,喂因子研究即违纪）。

## R6 已核（registry 路径对齐——先前的真实 unknown）
- 写侧：`scripts/hs300_onboard.py --registry-path`（**CLI 参数**,help 建议 `<repo>/data/datasets/registry.jsonl`）
  → `hs300_pipeline.build_research_asset(registry_path=...)` → `DatasetRegistry(Path(registry_path))`。**无 env、无全局约定**。
- 读侧：`panel_source.py` 当前**零** registry/data_root 感知。
- **对齐解**：定义单一约定 = `QUANTBT_DATA_ROOT` env override，否则默认 `<repo>/data/datasets/registry.jsonl`
  （= 写侧 help 建议路径）。**同时把 onboarding `--registry-path` 默认值设成同一路径**，两侧由构造对齐、不漂。
  CI/无 lake → registry 文件不存在 → 天然 absent → 合成（零行为变更）。

## 复权数学（承重 landmine · 11b）
```
hfq_col[sym,t] = raw_col[sym,t] × adj_factor[sym,t]   for col ∈ {open,high,low,close}
volume         = raw_volume    (默认不动,声明 volume_adjustment=none —— 见待拍板)
```
- join：`bars.join(adj_factors, on=["symbol","ts"], how="left")`；读侧**再守一次**缺因子 → `null_count>0 raise`
  （注册期探针 #6 已保证,但读侧防御纵深,可能读到旧资产）。
- **fail-closed**：缺 (sym,ts) factor / `adj_factor<=0` → **raise,不 drop、不 ffill**（drop=survivorship 畸变+断
  forward-return;ffill=陈旧 factor 污染除权日）。
- **O/H/L 必须与 close 同乘同一 factor**：因子表达式可引用任意列（expression.py 允许 `high/low`、`(close-open)/open`）；
  只复权 close 会在除权日出混口径伪跳变 = 隐蔽 correctness bug。四列同乘 → 日内比值 factor 相消不变。

## PIT / 无前视
- hfq（累计因子、参照点=首日=1.0）：新除权只新增 t'≥ 的因子,历史 t<t' 不变 → adj_factor[t] 在 t 已知 → **无前视**。
- qfq（÷latest）：每来新行动全历史重缩放,latest=窗末 = **前视**。→ 读侧**选 hfq 拒 qfq**。
- **诚实限界**：Tushare 落盘 factor **无逐行 known_at/vintage** → 只能声明 hfq（PIT-safe 方向）+ 标 no-per-row-vintage,
  **不得声称完整 bitemporal PIT**。forward-return 仍**只**经 `ic.attach_forward_returns`（数据层不自造 forward 列）。

## 不破现有 + §16 红线
- absent → 走**逐字节不变**的现有合成分支（additive 包裹,现有 :56-74 语句一句不动）。端点/调用方签名零改。
- §16：读侧是**研究/回测 env**（≠ perf harness 的 `measure_hs300_10y_daily_read`,两个独立 consumer,物理隔离）。
  不踩 §16 前提：读侧**永不** set perf `measured=True`、不喂执行层、`perf_baseline_claim=False`、label 不自升。
  唯一真实风险 = 有人把真实 panel 接进 perf harness / production verdict 而无 authority pin → 那才踩。故必带守卫。

## 待拍板（reversible → 选推荐 + tag Inference；执行时落 log）
- **D-11-MARKET-KEY**：推荐 **B 新增 `ashare_hs300` 显式 key**（`equity_cn` 保持合成不动,消隐式 universe 漂移）。
- **D-11-VOLUME-ADJ**：推荐 **raw + 声明 `volume_adjustment=none`**（turnover 不变式留因子台 opt-in）。
- **D-11-DATA-ROOT**：推荐 **`QUANTBT_DATA_ROOT` env,默认 `<repo>/data/datasets/registry.jsonl`**（见 R6 解）。

## 切片（additive,逐片可 land）+ 对抗测试
- **11a** resolver + present-detection（走 `DatasetRegistry.latest` + quality_verdict=pass + file_paths 全 is_file）+
  合成兜底。测：absent→合成**逐字节相等**（先 snapshot 现值）；present-detection 真/假（tmp mini registry）。**零行为变更 on absence**。
- **11b（承重）** hfq apply（left-join + fail-closed + OHLC×factor + volume 策略）。测对抗 1/2/3/7：qfq 方向错、
  漏 join（raw 冒充）、缺行 fail-closed、OHLC 一致性——变异（× → /、漏乘、fail→drop、只调 close）必打红。
- **11c** 诚实 label + §16/PIT 守卫 + docstring（现写「合成 sample」）。测 4/5/6/8：PIT 属性、label 诚实、
  两路径、§16 守卫（拒 cohort、no-perf-claim、`perf_baseline_claim=False`）。

## 最脆子项
**11b 的 hfq join + 缺行 fail-closed** —— 「raw 冒充复权」与「静默 drop→前视/survivorship」两 landmine 交点,
又是 §16「未复权价误喂成交层」直接向量。对抗 2/3/7 变异测试是承重护栏,门必须有牙。
