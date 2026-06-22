---
uuid: 79ebe273a97549cda08e7de8f896a783
title: 模拟台后端接线 — /api/paper/* 整层 + 晋级审批门 + 风险门冻结哈希链
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: backend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [9d5405ce121d4f98bf3dbc9e1014947b]
---

# 模拟台后端接线 — /api/paper/* 整层 + 晋级审批门 + 风险门冻结哈希链

## Scope [必填]
挂 `/api/paper/*` 整组只读+控制端点（status/start/stop/runs/持仓/成交-从 audit 派生/equity log）、晋级判定聚合（28天/超额/0违规/衰减<30% 四门）+ 人工审批端点（approver≠creator + 验证背书 INV-5）、风险门发布冻结哈希 + append-only 违规哈希链；复用已建 `PaperScheduler`/`PaperVenue`/`LifecycleManager`/`RiskMonitor`/kill_switch 引擎，不重造撮合/MTM/状态机/审计核。**不做**前端 React 实装、不做真钱阶梯（testnet→mainnet 属上游 BinanceTradingPage 域）、不改 RunDetailPage 交互逻辑。

## 上下文 / 动机 [按需]
后端核心引擎已具备但 `/api/paper/*` HTTP 整层未挂载：`PaperScheduler.snapshot()`（`app/paper/scheduler.py:177`）数据结构就绪、`PaperVenue` 撮合/MTM/audit 就绪、`LifecycleManager` 五态机就绪、`RiskMonitor`+kill_switch 就绪——本卡是把这些引擎接到 HTTP 面，并补两处治理缺口：**晋级人工审批门**（lifecycle 引擎在但未接 HTTP 审批，须 approver≠creator）与**风险门发布冻结哈希 + 违规 append-only 哈希链**（`/api/risk/alerts`+`RISK_MONITOR` 在但缺冻结持久化与篡改证据链）。本卡是 epic cfb0fea9 整套台前端实装的后端供数前置，配合前端 PaperDeskPage 落地。

## 接线点（file:line，实现时复核）[必填]

| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/main.py` | `app = FastAPI(...)` L79；现有路由块尾（risk 端点 L1454/L1482、trading safety ladder L2953-2966 之后） | 新增 `@app.get/post("/api/paper/*")` 端点组（status/start/stop/runs/positions/fills/equity/promotion/approve）；不动既有端点，追加在文件末尾路由区 |
| `app/backend/app/paper/scheduler.py` | `PaperScheduler.snapshot()` L177、`.state()` L96、`.start()` L99/`.stop()` L110、`.tick_once()` L119、`.mtm_once()` L139 | 复用为 status/start/stop 数据源；scheduler 当前单策略实例，新增「多 run 注册表」薄层（dict[run_id]→scheduler）不改 scheduler 内核 |
| `app/backend/app/execution/paper_venue.py` | `feed_bar()` L82（`paper_fill` 落 audit L123）、`get_position()` L76、`get_balance()` L79、`mark_to_market()` L127（equity log JSONL L141-143） | fills 端点从 `ExecutionAuditLog` 的 `paper_fill`/`paper_place` 事件派生；positions/balance 端点读 venue；equity 端点读 `_equity_log` JSONL |
| `app/backend/app/factor_factory/lifecycle.py` | `evaluate_transition()` L73（PROBATION→OBSERVATION L98-100）、`LifecycleManager.evaluate()` L147 | 晋级判定聚合复用此状态机；新增 4 门聚合（28天/超额/0违规/衰减）+ 审批门，审批通过才驱动 transition，引擎不改 |
| `app/backend/app/security/gate/policy.py` | `_threat_tier` L32-36（equity/cn/a_share→`TrustTier.PAPER`，永不 live） | A股 paper start/任何 live 下单端点接此判定：market=equity_cn 时 venue 恒 paper，live 路径拒；复用不旁路 |
| `app/backend/app/security/gate/enforcer.py` | `OrderGuard` L20 | 任何经模拟台触发的下单仍走 OrderGuard（S1 防重放→S2 deny-by-default→S3 升级），权限轴绝不旁路治理轴 |
| `app/backend/app/security/mainnet_guards.py` | `log_operation()` L342、`list_audit_log()` L371（已 `import hashlib` L24） | 风险门冻结哈希 + 违规链复用 append-only 审计基建；冻结哈希落盘 + 违规 append（prev_hash 链）经此或同构 JSONL，approver/审批操作落 log_operation |
| `app/backend/app/risk/checks.py` | `RiskMonitor` L85、`check_concentration()` L124 | RISK view 门限/违规来源；发布时快照门限→冻结哈希；会话内门限被改 → 拒并入违规哈希链 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「A股（market=equity_cn）走 live 下单端点」→ 门必**拒**（`_threat_tier` policy.py:35-36 返回 PAPER，live 路径 deny；A股 live 永远拒，R13/RULES 致命错误）。变异要杀：把 `_threat_tier` 改成对 equity 返回非 PAPER、或端点跳过 tier 判定直发 live venue → 测试必红。
2. 种「晋级裸翻：调 promotion approve 端点但无审批人 / approver==creator / 无验证背书」→ 门必**拒**（INV-5：approver≠creator + 验证背书；Agent 永不自动晋级）。变异要杀：把 approver≠creator 校验删掉、或 approve 端点直接 `evaluate_transition` 跳过审批 → 测试必红。
3. 种「风险门门限在会话内被改写（发布冻结后篡改 RiskMonitor 限值）」→ 门必**拒并把篡改请求写入 append-only 违规哈希链**（门限发布时冻结哈希，Agent 会话内永不可改）。变异要杀：让冻结后改门限静默通过、或违规未入链 / 链断（prev_hash 不连续）→ 测试必红。
4. 种「fills 端点直接信任传入的成交而非从 audit 派生」→ 门必只认 `ExecutionAuditLog` 的 `paper_fill` 事件（成交回报防伪，对齐防篡改证据链）。变异要杀：fills 端点改读外部传参 → 测试必红。
5. 种「下单绕过 OrderGuard 直发 venue」→ 门必经 OrderGuard（权限轴⟂治理轴，bypass 绝不跳 OrderGuard）。变异要杀：端点直调 `venue.place_order` 不经 enforcer → 测试必红。

## 复用 [按需]
- `PaperScheduler`（scheduler.py，含 start/stop/tick_once/mtm_once/snapshot/state）—— 不重造调度循环。
- `PaperVenue`（paper_venue.py，撮合/MTM/equity log/audit）—— 不重造撮合与净值写入。
- `LifecycleManager`+`evaluate_transition`（lifecycle.py 五态机）—— 不重造晋级状态机。
- `RiskMonitor`+kill_switch（checks.py + main.py L1482）+ `/api/risk/alerts`（L1454）—— RISK view 复用，不重复实现熔断/预警。
- `MainnetGuardsService.log_operation/list_audit_log`（mainnet_guards.py:342/371，hashlib 已在）—— append-only 哈希链复用同一审计范式。
- A股 paper 硬约束 `_threat_tier`（policy.py:32-36）—— 不另写一套市场判定。

## 红线 [按需]
- A股 live 下单永远拒（market=equity_cn 恒 paper）；下单唯一入口经 OrderGuard、实盘 key 不进 LLM。
- 权限轴⟂治理轴：bypass 绝不跳 OrderGuard / 审批门 / 过拟合门 / 血统门。
- 默认止于模拟盘，不导向直接实盘；晋级 approver≠creator + 验证背书（INV-5）。
- 弱点一等呈现：违规/衰减/风险门状态不染绿、不折叠藏（R25）；裁决措辞禁「可信/安全/排除过拟合/保证」（R7，文案走 `_verdict_note`）。
- 本地门=防篡改证据非防篡改（诚实声明，不假绿灯，§3）；违规链 append-only 不可删。
- 主进程不碰 torch（M6）。

## 非目标 [按需]
- 不实装前端 React（PaperDeskPage / PaperBoardCard 属 epic 其他卡）。
- 不实装真钱阶梯 testnet→mainnet（属 BinanceTradingPage 域）；不改 RunDetailPage 交互逻辑。
- 不重写 RiskMonitor / scheduler / lifecycle 内核；不做 REVIEW decay 对账端点之外的回测侧 PBO/DSR（§4 已建）。

## Open Questions（已决 D/总）[按需]
- [已决] A股 live 一律拒、恒 paper —— 经 `_threat_tier`（policy.py:32-36），MEMORY 项目范围硬约束，不重议。
- [已决] 晋级须 approver≠creator + 验证背书 —— INV-5，决策已定。
- [已决] 复用 MainnetGuards append-only 审计范式做违规哈希链 —— 不另起审计基建。

## 验收一句话 [必填]
种 A股 live 下单 / 晋级裸翻（无审批或 approver==creator）/ 风险门会话内被改 三类已知坏，`/api/paper/*` 整层门必分别拒（A股 live 永拒、审批门拒裸翻、篡改拒并入 append-only 哈希链），且不破现有 risk/security/trading 测试基线（含 `test_realmoney_audit_killswitch.py`）。
