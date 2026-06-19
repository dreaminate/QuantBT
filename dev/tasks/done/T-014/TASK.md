# T-014 · 确定性内核（node 身份 / durable / effectful 不可幂等边界）

- **状态**：done
- **review_status**：1（用户 2026-06-19 确认）
- **来源**：spine-designs 01（§4 接线 + §5 T-DET-1..10）+ 复核 00 §1.2-C/E（checkpoint_id==node_id）+ R10/R11/M17
- **优先级**：P0 · **依赖**：T-012（`ids.node_id`）、T-013（一本账，N 通知对账）

## Scope（单一能力单元）

把 DAG 建成**确定性内核**：内容寻址 node_id（复用 ids，绝不另造）+ durable 复用 +
replay/fork/rollback + **pure/effectful 分类**，核心命门：**effectful（动钱）节点在
replay/fork/rollback 一律 HALT、绝不重发副作用，发 reconcile 交对账**。

**诚实 deferred（绝不假绿灯）**：`jobs.py` SSE 事件接线（halted/checkpoint）与
`agent_runtime.py` 节点化【未做】——后者与 T-016（LLM record/replay）重叠，留给后续。

## 做了什么

- **复用 `ids.node_id`** 做单一身份源（无第二套哈希算法）；`compute_node_id` 的 structure
  = {op 名, **kind**（复核 #5）, **op 代码指纹**（复核 #3）}，inputs = 归一 params（剔
  `ids.DECORATIVE_KEYS`），upstream = 上游 node_id。
- `dag/effect_ledger.py`：`EffectLedger` 泛化 copy_trade `is_consumed→record+UNIQUE 兜底`
  到单键 `effect_idempotency_key`（R10/M17，所有 effectful 节点同一道幂等闸）。`busy_timeout`。
- `dag/artifact_store.py`：内容寻址 durable store（`exists`→复用不重跑；内容寻址不可覆盖）。
- `dag/kernel.py`：`DurableExecutor.run/replay/fork/rollback`。effectful 在非正向路径 HALT +
  reconcile；记账失败 CRITICAL + 标 requires_reconcile（绝不静默）；`on_attempt` 通知试验账本
  （复用绝不把 honest-N 改小）；`render_report` 措辞禁「reproducible/可信/安全/组织独立」。
- `engine.py`：`DAGTask` 加 `kind/effect_idempotency_key` + **__post_init__ 强制约束**
  （effectful 缺键构造即 raise）；`+reused/halted` 状态；`register_op(version=)`。向后兼容
  （旧 `run_dag` + 7 测试不动、旧 `idempotency_key` 对 effectful 迁移）。

## 验收（25 对抗测试 + 15 变异全杀 + 两轮复核）

`tests/test_dag_kernel.py` T-DET-1..22（durable≠reproducible / node 内容寻址 / effectful 幂等 /
fork·rollback·replay HALT / 崩溃恢复不重发 / 缺键 raise / 静态拓扑 / 复用不减 N / 措辞 /
跨主题·op版本·round-trip·未知 id·传递下游·遗留迁移·context 契约·菱形拓扑·不可覆盖·并发兜底·
记账失败标 reconcile）。
`cd app/backend && python -m pytest tests/test_dag_kernel.py -v` → **25 passed**。
全量回归 **821 passed / 13 skipped**（796 基线未破）。
变异测试 **15/15 mutation killed**（核心 7 + 修复 8）。

## 对抗复核（ultracode workflow + 二轮 money-safety）

1. 5-lens 对抗复核（effectful_boundary 因 529 未跑）→ 确认 **8 真发现**（context 非寻址 / round-trip
   不对称 / op 版本缺失 / 未知 id 静默 no-op / kind 撞 node_id / 空 rollback 守卫 / 传递下游未测 /
   遗留迁移未测）+ 5 低 note。
2. 8 项全修 + 各配回归 + 变异验证；并发测试自揪 `busy_timeout` 缺失（跨连接锁错）→ 补。
3. **专项 money-safety 复审**（effectful 边界 8 探针）：**无 HIGH，边界全部成立**；probe-4
   揪出「记账失败静默」→ 修（CRITICAL + requires_reconcile，T-DET-22）；probe-7（key 确定性，
   `derive_effect_key` + 文档禁 LLM 产 key）与 probe-8（硬杀进程的 place→record 窗口）= 已诚实
   记录的**不可消除残余**（需交易所侧幂等 token / 启动对账），非缺陷。

## 踩坑

- node_id 初版 structure 只含 op 名 → pure/effectful 撞同一 id + op 改码取陈旧工件（复核 #5/#3）→ 补 kind + 代码指纹。
- `context` 是隐藏的非寻址输入通道（数据塞 context → 假命中）→ 立硬契约「context 只携基础设施句柄」+ 回归钉死。
- 跨连接并发写无 `busy_timeout` → `database is locked`（幂等账尤危：已发单未记账）→ 补 5s。

## 下一步

T-015 试验账本算法层（N_eff 聚类 + 多证据三角 gate，读 T-013 一本账，接 M10 守门进 run 闸门=头号 gap）。
内核 deferred 项（jobs.py SSE / agent_runtime 节点化）择期接。
