# 数据平台 v2 · 实施计划（多源可插拔 + 宽字段 + 字段目录 + 源开关 + Agent 字段对齐）

> 状态：草案 v1，待用户 review 后开工。
> 目标对应 GOAL 的 M3（数据接入）、M4（特征）、M14（Agent），并新增"源开关 / 字段目录"两块当前 GOAL 未覆盖的能力。
> 维护原则同 GOAL：只增不删，决策变了在原段下追加。
>
> **⚠️ 状态更新（2026-05-29，已实现并提交于分支 `feat/data-platform-v2`）**：**源开关/隔离方案已废弃**——下文 §2.5/§3 P3 里的 `SourceConfigService` / `/api/sources` / 源开关树等**已删除**。最终采用：**单库 + 官方字段加 `official_` 前缀**（不隔离、不屏蔽；运行时读全部数据；动态字段宇宙只用于告知 Agent）。另新增：字段宇宙持久化表 `field_catalog`（`field_catalog/store.py`）、官方数据更新通道 `/api/data-packages/*`（与软件更新分线）。下文"源开关"段落仅作历史轨迹，**勿据此找已删的 SourceConfigService 等服务**。

---

## 0. 一句话目标

把数据层从「**单一官方源 + 固定 10 列 OHLCV 窄漏斗**」升级为「**多源可插拔 + 宽字段全保留 + 字段目录驱动 + 市场级/源级可屏蔽 + Agent 辅助字段对齐**」，且**不破坏**已冻结的 RunDetail 收益概述页与全绿的 release_check。

### 已拍板的设计决定（用户 2026-05-29）

1. **官方数据开关 = 市场级 ＋ 源级两层**（最大 DIY）。源级 enable/disable 是原子，市场级是卷积。
2. **字段模型 = 规范核心 ＋ 自由扩展**。维护 canonical 字段词典，各源对齐到它（因子/策略可跨源移植）；词典外的列登记为带命名空间的 free-form 字段，由 Agent 辅助映射。
3. **官方"拉全字段" = 一次性全量铺开**。Tushare 2000 积分所有可用接口 + Binance 所有数据类型。
4. **「官方加密数据库」≠ Binance**。它是一个**可增长的官方源集合**：Binance Vision / REST 是首批锚点，团队爬虫爬来的数据（链上 / 衍生品聚合 / 情绪 / 新闻…）会作为**新的官方源/数据集**进同一个官方加密库，与用户自有加密源共用同一套 catalog / 开关 / 对齐机制。

### 硬约束（不变量）

- **RunDetail 收益概述页冻结**（[RunDetailPage.tsx](app/frontend-run-detail/src/pages/RunDetailPage.tsx)）。本计划不触碰它。
- **release_check 必须保持全绿**：`pytest app/backend/tests` + `validate_glossary` + `tsc --noEmit` + `vite build`（[scripts/release_check.py:45-70](scripts/release_check.py)）。
- **向后兼容靠"OHLCV 兼容视图"实现**：`enforce_unified_schema` 原样保留（[base.py:186-208](app/backend/app/connectors/base.py)），现有 run / 现有测试走它兜底，永远拿得到固定 10 列。

---

## 1. 现状基线（已核实，file:line）

| 维度 | 现状 | 关键位置 |
|---|---|---|
| 统一 schema | 固定 10 列 `ts/symbol/market/interval/OHLC/volume/amount`，`enforce_unified_schema` 把任意 DF 压成这 10 列、多余列丢弃 | [base.py:43-68](app/backend/app/connectors/base.py)、[:186-208](app/backend/app/connectors/base.py) |
| Tushare | 声称支持 5 种 data_kind，`fetch()` 实际只放行 `ohlcv`（只调 `daily()`） | [tushare_connector.py:50](app/backend/app/connectors/tushare_connector.py)、[:99-123](app/backend/app/connectors/tushare_connector.py) |
| Binance | `data_pull.py` 已知 ~29 种 data_kind，但 fundingRate/OI 被伪造成 OHLC 行 | [data_pull.py:43-81](app/backend/app/data_pull.py)、[:801-810](app/backend/app/data_pull.py) |
| 用户源/上传 | generic_rest + user_upload 支持字段映射，但结果仍被压成 10 列；无自动列名推断 | [generic_rest.py:349-373](app/backend/app/connectors/generic_rest.py)、[user_upload.py:34-186](app/backend/app/connectors/user_upload.py) |
| 落盘 | CSV `data/market/{market}/{data_kind}/latest/{symbol}.csv`；Parquet `.../symbol={symbol}/{version}.parquet` | [data_pull.py:229-253](app/backend/app/data_pull.py) |
| dataset 注册表 | `DatasetRegistry` 写 `data/datasets/registry.jsonl`，`DatasetVersion` 有 `metadata` 扩展点，**当前不存 columns** | [data_quality.py:140-151](app/backend/app/data_quality.py)、[:166-233](app/backend/app/data_quality.py) |
| inventory | `data/catalog/inventory.json` **每个文件已记录 `columns: list[str]`** ✅ | [data_catalog.py:229-243](app/backend/app/tushare_quant1/data_catalog.py)、[:248-351](app/backend/app/tushare_quant1/data_catalog.py) |
| 源开关 | **完全没有**。connector 只在启动时注册 5 个；拉数是硬分支（crypto→Binance，否则→Tushare） | [connectors/__init__.py:35-46](app/backend/app/connectors/__init__.py) |
| 回测耦合 | `BacktestVenue` 硬要求 `{ts,symbol,open,high,low,close}` | [backtest_venue.py:68-69](app/backend/app/execution/backtest_venue.py) |
| 因子引擎 | `evaluate_on_panel(panel, formula, available_columns=None)`，None 时自动取 `panel.columns` —— **已支持动态列** ✅ | [expression.py:109-145](app/backend/app/factor_factory/expression.py) |
| Agent 工具 | `tool_schema.py` 13 个工具，**仅 3 个接了 handler**；`data.list_sources` 定义了但未接线 | [tool_schema.py:12-140](app/backend/app/agent/tool_schema.py)、[main.py:179-185](app/backend/app/main.py) |
| Agent 派发 | `handler = self._tools.get(tool_name)`，靠 `register_tool` 注册 | [agent_runtime.py:82-99](app/backend/app/agent/agent_runtime.py) |
| Agent 上下文 | `build_ai_context` 注入 connector/factor/operator，**不含真实字段**；M14 Agent 甚至没调它 | [ide/ai_context.py:130-159](app/backend/app/ide/ai_context.py) |
| 配置存储 | 凭证→`~/.quantbt/secrets.yaml`；业务→`data/community.db`（auth/community/billing/ide/copytrade/chat 共用） | [secrets_loader.py:29-163](app/backend/app/security/secrets_loader.py)、[main.py:96-110](app/backend/app/main.py) |

---

## 2. 目标架构（新增 / 改动模块）

```
新增：
  app/backend/app/field_catalog/          ← 字段目录（一等公民）
    canonical.py        CanonicalField 模型 + 词典 registry（从 canonical_fields.yaml 加载）
    canonical_fields.yaml  受控词表（团队维护，入 git）
    catalog.py          FieldCatalog：枚举 dataset+列、解析 canonical 映射、按 enabled 源过滤 → "可用字段宇宙"
    mapping.py          FieldMappingStore（sqlite community.db: field_mappings 表）raw_col→canonical|freeform
    infer.py            启发式映射器（列名相似度+dtype+样本值），供 Agent infer_mapping

  app/backend/app/sources/                 ← 源开关治理
    source_config.py    SourceConfigService（sqlite community.db: data_sources 表）
                        {name, market, kind=official|user, enabled, priority, config_json}
                        市场级 + 源级 enable/disable；list_enabled(market) 给 catalog 过滤用

  app/backend/app/agent/tool_handlers.py   ← Agent 工具实现（从 main.py 抽出，保持精简）

改动：
  connectors/base.py            +to_ohlcv_view() 别名；describe() 增 expected_fields；落盘不再强制 enforce
  connectors/tushare_connector.py   实装全部接口（多 data_kind，保留全列）
  connectors/binance_*            funding_rate/OI/aggTrades 等各自成独立 dataset，保留原生列
  connectors/generic_rest.py / user_upload.py   schema_target 支持 "wide"，保留额外列 + 走 mapping
  data_pull.py                  落盘改"宽 parquet + OHLCV 兼容 csv"双写；funding 不再伪造成 OHLC
  data_quality.py               DatasetRegistry.register 写 metadata["columns"]
  execution/backtest_venue.py   契约改为"声明所需字段→缺则报缺"，默认仍走 OHLCV 视图（兼容）
  factor_factory/expression.py  available_columns 接 FieldCatalog 动态字段集（已具备能力，接线即可）
  agent/tool_schema.py          +data.describe_fields / data.infer_mapping / data.apply_mapping
                                +data.register_field / factor.validate_columns；并补接 data.list_sources
  agent/agent_runtime.py / ide/ai_context.py   system prompt 注入"当前 enabled 源的可用字段宇宙"
  main.py                       注册新 handler；新增源开关 / 字段目录 / 映射 REST 路由

前端：
  frontend-data-center/         + 源开关树（市场级+源级）、字段查看器、字段映射向导（Agent 推荐+人工确认）
```

**核心不变量**：`enforce_unified_schema` 一字不改（[base.py:186-208](app/backend/app/connectors/base.py)，`test_connectors.py:28-33` 仍过）。它从「**落盘强制门**」改用途为「**消费侧 OHLCV 视图**」——只在兼容路径调用。

---

## 2.5 量化流程扩展性契约（用户 2026-05-29 追加：量化流程之后会有大扩展，必须保留扩展性）

**原则**：量化流程的所有模块（特征 / 标签 / 模型 / 信号 / 组合 / 执行 / 评估，以及**未来新增模块**）**不直接读盘、不写死列名、不绑定数据源**，一律通过一层稳定契约访问数据。新模块只"声明它要什么字段"，由 FieldCatalog 解析。

**三个稳定抽象（一经定稿，后续只扩不破）：**

1. **`WidePanel`** — 量化流程的通用数据货币：`ts × symbol` 宽表，列 = 任意 canonical + freeform 字段。所有模块输入/输出都是 WidePanel（或其派生），不再是固定 10 列。

2. **`FieldRequirement` / `load_panel`** — 数据访问契约：
   ```python
   @dataclass
   class FieldRequirement:
       canonical_ids: list[str]        # 必需字段（canonical 或 freeform id）
       market: str
       interval: str
       optional_ids: list[str] = []    # 可选字段，缺失不报错
       derive: bool = True             # 允许派生（如 amount 缺 → close*volume）
   def load_panel(req: FieldRequirement, *, sources=None) -> PanelResult
   #   PanelResult = { panel: WidePanel, manifest: {field_id: source_name}, missing: [...] }
   ```
   未来任何新模块（新因子族 / 另类数据消费者 / 新模型输入）只构造 `FieldRequirement`，**永不 import connector、永不硬编码 "close"**。

3. **能力注册表（Capability Registry）** — 量化流程的可插拔点统一用注册表，新增能力 = 注册一条、不改核心：
   - 已有：算子注册表、因子注册表 `FACTOR_REGISTRY`、模型 spec。
   - 本计划统一补齐：`FeatureRegistry` / `LabelRegistry` / `OptimizerRegistry` / `VenueRegistry`。每个能力声明自己的 `FieldRequirement`，框架据此预取 panel。
   - 每条能力带 `id / version / required_fields / produces / markets / lifecycle`，天然接入因子五态机与 lineage。

**对实施的约束**：`load_panel` / `FieldRequirement` / `WidePanel` 是整个流程脊梁，**P1 先定稿 + 配契约测试 `tests/test_data_contract.py`**；P3 把回测/因子改成"声明 → 解析"是这套契约的第一批消费者；任何后续"大扩展"都走"注册能力 + 声明字段需求"，零侵入核心。

---

## 3. 分阶段实施

> 每一阶都是「可独立交付、可单独验收、release_check 全绿」的切片，守"不交半成品"北极星。

### P1 · 数据地基：宽字段落盘 + 字段目录 + 兼容视图

**目标**：能把任意宽列数据集完整存下来并在字段目录里查到真实列，同时现有 run/测试零回归。

**新增**
- `app/backend/app/field_catalog/__init__.py`
- `field_catalog/canonical.py`：`CanonicalField(id, dtype, unit, markets, aliases, description)` + `CanonicalRegistry`（从 yaml 加载）。
- `field_catalog/canonical_fields.yaml`：首版受控词表（见 §4）。
- `field_catalog/catalog.py`：
  - `FieldCatalog.list_datasets(market=None, enabled_only=False)`
  - `FieldCatalog.dataset_columns(dataset_id) -> list[ColumnInfo]`（读 inventory 的 `columns` + registry 的 `metadata["columns"]`）
  - `FieldCatalog.available_fields(market, enabled_sources) -> FieldUniverse`（canonical + freeform，按 enabled 过滤、按 priority 选源）
  - `FieldCatalog.resolve(field_id) -> (source, dataset, raw_column)`

**改动**
- [connectors/base.py](app/backend/app/connectors/base.py)：
  - 保留 `enforce_unified_schema` 不动；新增 `to_ohlcv_view = enforce_unified_schema`（语义别名，供消费侧调用）。
  - `ConnectorCapability` 增可选 `expected_fields: tuple[FieldSpec, ...]`，`describe()` 带出来（供未拉取前预告字段）。
- [data_quality.py:180](app/backend/app/data_quality.py) `DatasetRegistry.register`：把 `fetch_result.frame.columns` 写进 `metadata["columns"]`（向后兼容，老记录无此键时按 inventory 兜底）。
- [data_pull.py:229-253](app/backend/app/data_pull.py) 落盘：**双写**——① 宽 parquet（全列，新）② OHLCV csv（10 列，兼容，沿用现有写法）。新增 `load_wide_panel(symbols, interval, fields, market, sources)`：读宽 parquet → 按 `fields` select → 缺字段记录到 `missing`。现有 `load_csv` 路径不动。

**测试**
- 新 `tests/test_field_catalog.py`：存一个 12 列数据集 → catalog 能列出全部列 + canonical 映射命中 + freeform 归类。
- 回归：`test_connectors.py` / `test_execution.py` / `test_factor_factory.py` / `test_labels.py` / `test_data_quality.py` 全过（不改这些测试）。

**验收**
- 拉一份带 `pe_ttm/funding_rate` 等额外列的数据集，落盘后 `GET /api/data/preview` 看得到全部列；`enforce_unified_schema` 仍只给 10 列视图。
- `pytest app/backend/tests -q` 全绿。

**向后兼容守卫**：OHLCV csv 双写 + `to_ohlcv_view` 兜底；任何现有消费者读到的仍是 10 列。

**粗估**：中（新包 + 双写 + 注册表小改）。

---

### P2 · 官方全量拉取：Tushare 全接口 + Binance 全类型 + 爬虫源接入口

**目标**：把官方源能拉的字段全拉成多 dataset（各自成表、保留原生列），并注册进字段目录（含 canonical 映射）。

**改动 / 新增**
- [tushare_connector.py:99-123](app/backend/app/connectors/tushare_connector.py)：实装全部 data_kind，每个接口 = 一个 dataset，保留接口全部列。首批：
  `daily`、`daily_basic`(估值)、`adj_factor`(复权)、`index_daily`、`fund_basic`/`fund_nav`、`fina_indicator`(财务)、`income`/`balancesheet`/`cashflow`、`moneyflow`、`top_inst`/`top10_holders`、`stock_basic`(标的属性)、`trade_cal`(日历)。复用现有令牌桶限流。
- Binance：[data_pull.py:755-836](app/backend/app/data_pull.py) 的 `_normalize_binance_rows` 改为「按 data_kind 输出原生宽列」，**取消 funding/OI→OHLC 的伪造**（[:801-810](app/backend/app/data_pull.py)）。`funding_rate`、`open_interest_hist`、`taker_buy_sell_volume`、`agg_trades`、`mark_price_klines` 各自成 dataset。
- **爬虫官方源接入口**（呼应「官方加密 ≠ Binance」）：`sources/source_config.py` + `field_catalog` 提供 `register_official_dataset(source_name, market, frame_or_path, mapping)`——爬虫 job 产出 parquet 后走这一条路径登记 dataset + catalog + canonical 映射，与 connector 同构。本阶段只交付**接入口 + 一个样例爬虫源 stub**，真实爬虫是团队后续工作。
- canonical_fields.yaml 扩充到覆盖上述接口的高频字段 + 给每个内置 dataset 落 seed mapping（写入 `field_mappings`）。

**测试**
- `tests/test_tushare_fields.py`（mock pro 接口）：每个 data_kind 拉到的列数 > OHLCV，且 canonical 映射命中预期字段。
- `tests/test_binance_funding_dataset.py`：funding_rate 独立成表、列含 `funding_rate/funding_time`，不再是伪 OHLC。

**验收**
- 一键拉 A股：`daily_basic` 的 `pe_ttm/pb/total_mv/turnover_rate`、`fina_indicator` 的 `roe/eps`、`moneyflow` 的净额都能落库并在 catalog 查到。
- 一键拉加密：`funding_rate`、`open_interest` 独立成表，限流安全（命中退避）。

**粗估**：大（接口多、字段多、限流与缓存要稳）。

---

### P3 · 源开关 + 动态字段宇宙

**目标**：市场级+源级开关落地；量化流程的可用字段 = ⋃(enabled 源的 catalog 字段)，关掉官方源后流程里看不到官方字段。

**新增**
- `sources/source_config.py`：`SourceConfigService`（sqlite `data_sources` 表）。
  - `register_source(name, market, kind, priority, config)`、`set_enabled(name, enabled)`、`set_market_enabled(market, kind, enabled)`（市场级卷积）、`list_enabled(market) -> list[Source]`。
  - 启动时把现有 5 个内置 connector + 官方爬虫源 seed 进表（默认 enabled）。

**改动**
- [field_catalog/catalog.py] `available_fields(market)` 调 `SourceConfigService.list_enabled(market)` 过滤；同一 canonical 多源提供时按 `priority` 选源（用户自有 vs 官方的取舍点）。
- [factor_factory/expression.py:109-145](app/backend/app/factor_factory/expression.py)：因子/策略求值时，`available_columns` 由 `FieldCatalog.available_fields()` 提供；缺字段抛明确错误（带"哪个源能补"提示）。
- [backtest_venue.py:68-69](app/backend/app/execution/backtest_venue.py)：契约从"硬要 6 列"改为"声明所需 canonical 字段 → 向 catalog 解析 → 缺则报缺"；默认策略仍只依赖 OHLCV，走兼容视图。
- [main.py](app/backend/app/main.py)：新增路由
  - `GET /api/sources`（树：market→sources，含 enabled/kind/priority）
  - `PUT /api/sources/{name}/enabled`、`PUT /api/sources/market/{market}/enabled`
  - `GET /api/fields?market=&enabled_only=true`（当前可用字段宇宙）

**测试**
- `tests/test_source_gating.py`：关掉官方 A股源 → `available_fields("stocks_cn")` 不含官方字段，只剩用户源字段；重新开启恢复。
- `tests/test_field_universe.py`：多源同 canonical 按 priority 选源。

**验收**：UI/REST 关掉"官方 Tushare"后，因子表达式引用 `pe_ttm` 报"该字段当前不可用（需启用 官方A股/Tushare 或提供等价用户源字段）"。

**粗估**：中。

---

### P4 · Agent 字段对齐能力（给 M14 那个 Agent 加工具）

**目标**：在"入库时（用户列名→canonical）"和"消费时（策略要的字段→catalog 找/派生/提示缺失）"两个接缝，让现有 Agent 辅助。

**新增**
- `agent/tool_handlers.py`：实现并集中注册工具 handler。

**改动**
- [tool_schema.py:12-140](app/backend/app/agent/tool_schema.py) 新增工具：
  - `data.list_sources`（**补接现有未接线的**）→ `{sources:[{name,market,kind,enabled,freshness}]}`
  - `data.describe_fields(source|dataset)` → 真实列 + dtype + 样本值 + 已映射 canonical id
  - `data.infer_mapping(dataset|sample)` → 用 `field_catalog/infer.py`（列名相似度 + dtype + 样本）产出 raw→canonical **建议**，或建议登记新 freeform 字段
  - `data.apply_mapping` / `data.register_field` → 落 `field_mappings` / 新 canonical 或 freeform 字段
  - `factor.validate_columns(formula)` → 解析公式列名，对照当前可用字段宇宙校验，缺列给"哪个源能补"
- [main.py:179-185](app/backend/app/main.py)：用 `tool_handlers.register_all(runtime, ...)` 注册以上 handler（接 `connector_registry` / `FieldCatalog` / `SourceConfigService` / `FACTOR_REGISTRY` 现有单例）。
- [ide/ai_context.py:130-159](app/backend/app/ide/ai_context.py) `build_ai_context` 增 `field_universe` 入参；`to_system_prompt_block` 注入"当前 enabled 源可用字段（canonical + freeform）"。M14 Agent 的 system prompt 也接上同一份字段宇宙。

**测试**
- `tests/test_agent_field_tools.py`：喂一个列名乱的用户源样本 → `data.infer_mapping` 给出合理建议 → `apply_mapping` 落地 → `factor.validate_columns` 通过。
- `tests/test_agent_context_fields.py`：context 里出现当前可用字段，且随源开关变化。

**验收**：接一个 `{px, qty, t}` 这种列名的用户源，Agent 能推荐 `px→close / qty→volume / t→ts`，确认后因子能跑。

**粗估**：中（工具是轻 wrapper，难点在 infer 启发式与 context 注入）。

---

### P5 · 前端（数据中心）

**目标**：用户能在 UI 开关源、看字段、走映射向导。

**改动**：[frontend-data-center](app/frontend-data-center)（[DataPage.tsx](app/frontend-data-center/src/pages/DataPage.tsx) 加 tab）
- **源开关树**：market→sources，市场级总开关 + 源级开关；官方/用户分组；调 `/api/sources`。
- **字段查看器**：选中源/dataset 看真实列 + canonical 映射 + 样本；调 `/api/fields`、`/api/data/preview`。
- **字段映射向导**：用户上传/自定义 API 后，调 `data.infer_mapping` 拿 Agent 建议 → 拖拽确认 → `apply_mapping`。
- **不碰** RunDetail（[frontend-run-detail](app/frontend-run-detail)）。

**测试**：`tsc --noEmit` + `vite build` 通过（release_check 项）。

**验收**：关掉官方加密源后，数据中心字段查看器只显示用户加密源字段；上传一份乱列名 csv 能走向导对齐入库。

**粗估**：中。

---

## 4. canonical 字段词典（首版 seed，canonical_fields.yaml）

受控词表，团队维护、入 git。每条：`id / dtype / unit / markets / aliases / description`。首版覆盖：

- **价量核心**：`open high low close volume amount`（aliases: vol→volume, turnover→amount）
- **复权**：`adj_factor`
- **A股估值**(daily_basic)：`pe_ttm pb ps_ttm total_mv circ_mv turnover_rate volume_ratio dv_ttm`
- **A股财务**(fina_indicator)：`roe roa net_profit_margin gross_margin debt_to_assets eps bps`
- **A股资金流**(moneyflow)：`net_mf_amount buy_lg_amount sell_lg_amount`
- **加密永续**：`funding_rate open_interest mark_price index_price long_short_ratio taker_buy_volume taker_sell_volume`

词典外的源列 → 登记为 freeform，命名空间化：`tushare.<col>` / `binance.<col>` / `user_<conn>.<col>` / `crawler_<name>.<col>`。

---

## 5. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 改 schema 砸现有测试/run | `enforce_unified_schema` 不动 + OHLCV 双写兼容；P1 先跑定位过的 5 个 schema 测试 |
| Tushare 全量拉触发限流 | 复用现有令牌桶 + 退避 + 本地 parquet 缓存；批量接口优先 |
| 宽 parquet 磁盘膨胀 | 分区 + 压缩 + 增量；逐笔类数据默认不拉、按需开 |
| 多源同字段冲突 | priority 显式选源 + catalog 标注来源，UI 可见 |
| 爬虫源数据质量参差 | 走同一套 GE-lite 规则 + freshness，官方源也要过校验 |
| Agent infer 误映射 | 只产**建议**，必须人工确认才落地；mapping 可回滚（版本化） |

**回滚**：每阶独立分支；P1 双写可一键回到"只读 csv"路径；source_config / field_mappings 是新表，删表即回退。

---

## 6. 测试与 release_check 策略

- 每阶新增专项测试（见各阶），且 `pytest app/backend/tests -q` 必须全绿。
- 改 OHLCV 相邻代码后，先跑：`test_connectors.py::test_unified_schema_fills_missing_columns`、`test_execution.py`、`test_factor_factory.py`、`test_labels.py`、`test_data_quality.py`。
- 前端阶段过 `tsc --noEmit` + `vite build`。
- 全部完成后补 `docs/data-connector-guide.md`（宽字段 + canonical + 源开关）与 GOAL 的 M3/M4/M14 更新段。

---

## 7. 【人类视角】怎么改 · 旧状况 · 改成什么样 · 为什么

| # | 在哪改 | 旧状况 | 改成什么样 | 为什么这么改 |
|---|---|---|---|---|
| 1 | 落盘 schema（`enforce_unified_schema` 用途 + 双写） | 所有源被压成固定 10 列 OHLCV，多余字段直接丢；`enforce_unified_schema` 是落盘强制门 | 落盘保留**全部原生列**（宽 parquet）；`enforce_unified_schema` 原样保留，但改当"**OHLCV 兼容视图**"，只在老路径调用；同时双写 10 列 csv 兜底 | "拉全字段"现在根本存不下来。窄漏斗是根症结。保留它当视图，既能存全字段，又不动现有 run/测试 |
| 2 | 字段目录 `field_catalog/` | 没有统一字段目录；只有 inventory.json 零散记了 columns | 新增 FieldCatalog：枚举每个 dataset 的真实列 + canonical 映射 + 按 enabled 源过滤，成为"可用字段宇宙"的**唯一真相源** | 量化流程要"按数据源动态决定可用字段"，必须有一个集中、可查询、可过滤的目录，而不是散在各 connector 里 |
| 3 | canonical 词典 + 映射 | 无规范字段概念；用户列名各写各的，因子不可移植 | 团队维护 canonical 受控词表（close/pe_ttm/funding_rate…），各源对齐到它；词典外的列登记为带命名空间的 freeform | 你选了"规范核心+自由扩展"。有规范核心，因子/策略才能跨数据源复用；freeform 兜住长尾，不丢字段 |
| 4 | Tushare/Binance 全量拉取 | Tushare 只调 `daily()`；Binance 把 funding/OI 伪造成 OHLC | Tushare 实装全部接口各自成表；Binance funding/OI/逐笔各自成独立 dataset 保留原生列 | 你要"能拉的字段都拉，一次性全量"。伪造成 OHLC 是严重数据损失，必须各自成表 |
| 5 | 官方源 = 可增长集合 + 爬虫接入口 | 加密 = 写死 Binance；无第三方/爬虫数据进官方库的通道 | "官方加密"是一组源；新增 `register_official_dataset` 接入口，爬虫产出走同一套登记/校验/映射 | 你补充的关键点：官方加密数据未来含团队爬虫数据。架构不能把"官方加密"等同于 Binance |
| 6 | 源开关 `sources/` + REST | 完全没有开关；拉数硬分支 crypto→Binance | 新增 `data_sources` 表 + 市场级/源级两层开关；catalog 按 enabled 过滤 | 你要"用户 DIY 是否用官方数据，不用就在量化流程屏蔽我们的库"。这就是屏蔽机制的落点 |
| 7 | 量化流程解耦 OHLCV | 回测硬要 6 列；因子默认 OHLCV | 回测/因子改"声明所需 canonical 字段→向 catalog 解析→缺则报缺"；默认策略仍走兼容视图 | "可用字段取决于启用的数据源"必须让流程从目录拿字段，而不是写死 |
| 8 | Agent 加字段对齐工具 | 13 个工具只接了 3 个；无任何字段感知/对齐工具；context 不含真实字段 | 补接 `data.list_sources`，新增 `describe_fields/infer_mapping/apply_mapping/register_field/validate_columns`；context 注入"当前可用字段宇宙" | 你要"拉数与量化流程对齐字段的地方用 Agent 辅助，给原来那个 agent 加功能"。这是直接落点 |
| 9 | 前端数据中心 | 只有拉取/浏览/任务；无源开关、字段查看、映射向导 | 加源开关树、字段查看器、字段映射向导（Agent 推荐+人工确认） | 让上面的能力对非工程用户可点、可用、可视 |

> **冻结红线**：以上 9 项**不触碰** RunDetail 收益概述页；schema 升级靠"OHLCV 兼容视图"保证现有 run 与 release_check 全绿。
