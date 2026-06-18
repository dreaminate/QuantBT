# ISSUES · 跨任务问题 / 风险登记册

> 卡 done 时未决的 Open Question、跨部件风险、诚实残余——**不随卡消失、不掉地**。
> 这是「发现问题」的持久容器：决策岔路→`DECISIONS.md`，要做的活→`BOARD.md`，**没现成归宿的风险/问题→这里**。
> 状态：`open` 待处理 · `watching` 观察中 · `accepted` 已接受残余(不修·文档化) · `resolving` 处理中 · `resolved` 已闭 · `→T-xxx` 已升任务。
> 闭环纪律：升任务即标 `→T-xxx`；接受为残余即标 `accepted` 并写理由；解决即标 `resolved` 并留闭合条件。

<!-- 格式·防跑偏 | 追加型：登记一行表格 + 下方一块明细。新问题照此：
表格行：| I-XXX | <标题> | 高/中/低 | <来源> | <状态> |
明细块：### I-XXX · <标题> [状态]  <描述 + **闭合条件**：满足什么算解决> -->

| id | 标题 | 严重 | 来源 | 状态 |
|----|------|------|------|------|
| I-001 | TCB 天花板：本地门=防篡改证据非防篡改，唯一硬墙在交易所侧 | 高(结构) | T-018..T-022 | accepted |
| I-002 | 对齐闸 review_status 从未行使（12 张 done 卡全 0） | 中(流程) | dev OS 审视 | resolved |
| I-003 | reconcile 对账下游消费方未定（HALT 发 RECONCILE_REQUIRED 后谁对账 / 失败如何阻断下游） | 高 | T-014/T-023 | open |
| I-004 | node_id 单一源跨部件一致性（后续谱系部件若与 lineage/ids 分叉 → 一本账分裂） | 中 | T-023 Open Q | watching |
| I-005 | 晋级用一次性 OOS vs 运营滚动验证集 是否同切片 | 中 | T-024 Open Q | open |
| I-006 | Sentry flush 致 pytest 退出假死 | 低 | 本 session | resolved |
| I-007 | 非-relay live：emergency_close_all 空壳 + kill_switch 端点无鉴权 | 中 | T-025 审计 | →T-025 |

## 明细

### I-001 · TCB 天花板 [accepted]
broker 与 venue 同属主机进程内存；lease 只把 key 暴露窗口收窄到单次 `place_order`，**抬高代价非干净修复**。被攻破属主机时短时 lease 仍可被截。唯一真硬墙在交易所侧（子账户限额 / 交易专用 + IP 白名单 key）。→ 不可由本地代码消除，已诚实文档化（STATE 诚实残余 + 各安全卡）。**不修,接受为结构残余。**

### I-002 · 对齐闸空转 [resolved]
`review_status` 0→1 是人类对齐机制，但 12 张 done 卡全 0——结构在、从未行使。**已闭合**：用户 2026-06-19 审完 T-001/T-012..T-022 全部 12 张 done 卡，review_status 全部 0→1（确认）。对齐闸首次真运转。

### I-003 · reconcile 下游未定 [open]
内核 effectful 边界 HALT 后发 `RECONCILE_REQUIRED`，但**谁消费、对账失败如何阻断下游**未定。T-023 只发事件 + 留 hook，对账闭环归后续（执行侧 / 审批门对接）。**闭合条件**：定义 reconcile 消费方 + 失败阻断路径 + 对账测试。

### I-004 · node_id 跨部件一致性 [watching]
若后续谱系部件对 `node_id` 的定义与 `lineage/ids.node_id()` 分叉 → 一本账分裂、honest-N 失真。守：单一身份源铁律（RULES §1）。**观察点**：接谱系部件时做 checksum 对账。

### I-005 · 一次性 OOS vs 滚动验证集 [open]
「晋级确认用的一次性 OOS」（碰一次出裁决）与「运营 walk-forward 反复消费近段」是否同切片？建议**分两套**、文档钉死各自消费口径，避免把元科学范式生搬运营。归 T-024 设计澄清。

### I-006 · Sentry pytest 假死 [resolved]
全量 pytest 通过后进程在 Sentry flush 处长挂（不可达 DSN，曾观测约 1 小时）。在 `app/backend/app/observability/errors.py` 加 `_under_pytest()` → `shutdown_timeout=0`（chip `task_e665e0b7` 产出）。**已闭合**：2026-06-19 平跑全量（无 timeout 插件）**1001 passed / 13 skipped，全程 69.46s 干净退出**，假死消失；改动随本轮提交并入。

### I-007 · 非-relay live 急停控件 [→T-025]
emergency_close_all 仅 log 不真平仓；`/api/risk/kill_switch` 端点无鉴权。真 live 下单面已 100% 经门（本 session 核实），残余在急停控件完整性。已立 **T-025**。
