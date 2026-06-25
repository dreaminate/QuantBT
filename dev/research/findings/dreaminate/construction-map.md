# 施工图 · GOAL §0-§17 → task DAG（一中心 + 5 并发 deep-opus）

> 三方独立研究并集（中心 Claude + deep-opus 代码核验 + codex gpt-5.5·xhigh），2026-06-26 建。
> **单一现状源 = 各 pool/dev 卡的 depends_on DAG + dev/state**；本文件是【导航总览】，实时依据永远是卡原文 + 代码。
> 派 opus 前必读：dev/GOAL.md（完整 §0-§17·2076 行·已 canonical on main）+ dev/RULES*。

## 0. 基线真相（代码实证 · 派 fleet 的前置）

- **GOAL canonical**：完整 §0-§17 已 commit 进 main（此前只在本地未提交·已修双源漂移）。
- **集成基线 = main + auto/math-spine**：Mathematical Spine 全套 + 验证纵深件（conformal/cpcv/drift/attribution/impact/lifecycle_metrics）在 `auto/math-spine`（9 ahead·**land 进 main = 一切 spine-dependent 验收的对照基线**）。`fix-u2-synth`(47d79a9) 已是 main 祖先、无需 land。
- **三态成熟度**（贯穿全表，别重复做已 done）：
  - ✅ **已建不变量**：`lineage/ids.py` 单一身份源 + ledger 哈希链/honest-N、`dag/kernel.py` 确定性内核、approval(approver≠creator)、verifier(Independence 度量)、OrderGuard 全 venue + CI 矩阵、SQLite WAL、append-only JSONL、content-addressed、LLM 决策级 replay、provenance 血统门、kill switch(IP+PBKDF2/TOTP)、前端整套台 + 画布引擎 + agent 窗口 epic。
  - 🟡 **auto/math-spine（land 即生效）**：Mathematical Spine + CPCV/conformal/attribution/MinTRL/drift/impact/lifecycle_metrics。
  - 🟥 **greenfield 硬地基**（全仓 0 hit 实证）：QRO/ResearchGraph/GovernedCompiler/CanonicalCommand、LLM Gateway/Registry/Routing/CredentialPool/LLMCallRecord、Document Intelligence 全栈、RDP 开放格式导出、StrategyBook/Forecast 对象、方法学控制面 6 档、发版门禁套件、§11 多资产语义/InstrumentSpec/MarketCapabilityMatrix。

## 1. 七条 LINE（territory + 依赖 + 文件争用）

> 一条 LINE = 内部串行依赖链 + 一块尽量不交叠的文件 territory，分配给一个 deep-opus。中心控并发=文件争用：绝不让两张碰同一文件的卡同时在飞。

| LINE | territory（owner） | 内部串行链 | 阻塞下游 |
|---|---|---|---|
| **LINE-0 集成基线**（中心/leader） | 三流合一 diff · `main.py` 集成窗口 | land auto/math-spine → 全量验证 | 全部（spine 验收对照） |
| **LINE-A 对象脊柱**（gap#1#2·最硬地基） | 新 `qro/` `graph/` `command/` `compiler/` `governance/invariants` + 前端画布投影 | QRO 信封 → ResearchGraph IR → CanonicalCommand → Compiler →（扇出）Canvas/Desk/治理收口 | 几乎全部·收编 ids/kernel/ledger/approval/spine_gate **不重造** |
| **LINE-A-AGENT**（§7§4§8·最强上游瓶颈） | 新 `llm/`(Gateway/Registry/Routing/Pool/CallRecord) + `agent/orchestrator.py` `roles/` | LLM Gateway → Orchestrator → 12 role → 23 事件投影 | D-ENG-3/RDP-2/TRUST-1/DOC-4/ENG-1·收编 replay/keystore |
| **LINE-B 数据PIT脊柱**（gap#6+RAG） | 新 `ingestion/` + `field_catalog/` `universe/` `data_pull.py` `agent/rag.py` | PIT 接线 ‖ DatasetVersion 写门 ‖ IngestionSkill ‖ SecretRef ‖ RAG 升级 | C-METH-2(feature-leak)/RDP-2/B-INST |
| **LINE-C 模型/因子/信号**（gap#5§15§9§10剩余） | `models/` `training/` `signals/` `factor_factory/` `strategy/`(新) `methodology/`(新) `portfolio/` `eval/` | 模型治理 ‖ Forecast→Signal→portfolio typed contract ‖ 因子生命周期接转移 ‖ StrategyBook ‖ 方法学控制面 ‖ spine_gate 接 promote | C-CONTRACT-3/STRAT-3 跨 LINE-G |
| **LINE-E 交付信任**（§17§13§16·北极星总闸） | 新 `delivery/`(RDP) `release_gate/` `runtime/`(profile) `governance/` | RDP schema → 聚合器 → 残余字段 ‖ 发版门禁 ‖ no-silent-mock 中心守卫 ‖ Binding/ConsistencyCheck 门 | 终态交付·汇聚 A/spine/B/C 字段 |
| **LINE-G 执行/文档**（§12§6·安全红线） | `execution/` `risk/` `monitor/production.py` `documents/`(新全栈) `instruments/` | 生产监控调度 → live ladder → graded kill ‖ Document intake 安全栈 → EvidenceSpan → 信任边界 | 跨 B-INST/A Gateway |

**关键文件争用（必排序·写进卡 depends_on）**：`main.py`=中心独占 · `lineage/spine.py`=C0 先定 schema·下游只消费 · `training/codegen.py`=B-PIT(装载入口) 先于 C-CONTRACT(出口) · `eval/overfit_gate.py`=扩展不替换(LINE-0 已落 DSR helper) · `portfolio/gate.py`=冻结不动 · `governance/responsibility.py`/`methodology_choice.py`=LINE-C/E/G 共建单一 schema · `instruments/`=LINE-B owns·LINE-G 消费。

## 2. 波次计划（中心动态补派·活的任务池）

> **前沿实证刷新（2026-06-26 中心 loop）**：① **LINE-0 已完成**——`auto/math-spine` 已 land 进 main（origin/main 严格领先 origin/auto/math-spine 7 提交、spine 分支 0 unique commit），Mathematical Spine 全套 + 验证纵深（cpcv/conformal/drift/attribution/mintrl/impact/lifecycle）已是 main 基线、spine-dependent 验收对照已就位。② **W5 D-EXEC-3（`de764e1c`）已 done**（在 `tasks/dreaminate/done/`）。③ 基线 = origin/main，全量 **1734 tests collected**。

**第一波就绪前沿——已 mint+派发（2026-06-26·4 条 deep-opus 在飞，文件领地不交叠）**：
- **W1 C-MODELGOV-1-full**（uuid `2b65a76e`·分支 `wave1/w1-artifact-trust`）——止血已 done（`training/lib.py` RestrictedUnpickler+weights_only）；完整 producer-run+hash 信任门 + allowlist + safetensors。领地 `training/lib.py`(+新 `training/artifact_trust.py`)。
- **W2 B-PIT-1**（uuid `fe46991c`·分支 `wave1/w2-pit-wiring`）——`training/codegen.py:25` raw parquet → 消费 `load_panel(as_of_known)`（catalog.py:197 已就绪）堵 look-ahead。领地 `training/codegen.py`。
- **W3 B-VERSION-1**（uuid `5745c2c3`·分支 `wave1/w3-dataset-write-gate`）——不可变门已建（`data_hash/dataset_hash.py`），真 gap=接进实际 ingest 写路径强制缺 version/checksum→拒。领地 `data_hash/`+`connectors/base.py`+`data_quality.py`。
- **W4 D-RDP-1**（uuid `0e7bbc13`·分支 `wave1/w4-rdp-schema`）——greenfield `delivery/` RDP schema+manifest+§17 四拒绝门。领地 新 `delivery/`。

**第二波起**（LINE-A 出契约后扇出·当前最强上游瓶颈）：QRO/Graph/Compiler/Command、LLM Gateway/Registry/Routing、Document Intelligence、StrategyBook/Forecast/方法学控制面、RDP 聚合器接 promote、发版门禁。**LINE-A（对象脊柱）是几乎全部下游的依赖**——wave-1 land 后中心宜开 LINE-A 线（greenfield `qro/graph/command/compiler`·收编 ids/kernel/ledger 不重造）。中心每完成一卡从更新后就绪前沿补派，保持 ≤5 满载。

## 3. 拍板项清单（opus 绝不擅自做·点名）

1. §11 多资产范围（期权/期货/债券/FX/商品是否本期做）= 产品范围决策。
2. 方法学控制面 6 档阈值口径 + 新档位语义。
3. 因子退役/去重硬阈值（R21 流程已拍·数值待拍）。
4. 模型风险分层/materiality 口径。
5. 专家否决权 override 边界（R26 可 override「可证伪经济错觉」≠「方法学松紧」）。
6. 用户方法学自主权流程（系统只记录 MethodologyChoiceRecord 不替决）。
7. 生产 profile 松紧（mock/profile 边界是用户那摊·只守 no-silent-mock 红线）。
8. PDF 解析库选型 + 文档解析能力边界。
9. **A股 live 边界**（GOAL §12 说未来治理可开·但 RULES.project「A股永不实盘」更严·**按更严·绝不擅动**）。
10. mainnet 100U 一周实盘（用户亲自按键·agent 绝不动钱）。
11. LLM 默认路由策略（成本优先 vs 质量优先·只摆选项）。

## 4. 红线守卫（全程·任一违反即停工）

A股不实盘（禁 vnpy/easytrader/ths_trader）· 实盘 key 不进 LLM/RAG/日志/导出 · OrderGuard 唯一下单入口（新 venue/端点禁裸调 place_order）· 杠杆护栏接所有路径含中继桥 · **外来 pickle/torch.load 不安全加载**（已止血·完整门 C-MODELGOV-1）· 单一身份源 `lineage/ids.py` 不另造 · RunDetailPage 冻结 · 生产禁 silent mock fallback · 扩展不替换 · land 仅 leader/admin · 对抗测试种坏门必抓不破基线。

---
> 完整逐节 DAG 表（§0-§17 每节×现状×gap×depends_on×文件领地×可证伪验收）见三方研究记录；pool 卡是其落地单元。中心在 loop 中按就绪前沿动态 mint 后续卡、开新线。
