# T-023 · 确定性内核（T-014）接进 jobs / agent 执行路径

- **状态**：todo（卡已过目，待 2 岔路点头后开工）
- **review_status**：0
- **来源**：spine-designs 01（§4 接线 / §5 对抗）+ 00-contracts C1/C5/C7/C8 + R10/R11/M17
- **优先级**：P0（**STATE 头号 gap#4**：内核已建并验证 T-014，但 deferred 未接进真实执行路径——不接=验证白做）
- **依赖**：T-014（内核）、T-013（一本账）、T-016（LLM record/replay，agent 节点化复用其 fixture）
- **波次**：簇A 脊柱收尾（收口第一波）

## Scope（单一能力单元）

把已建的确定性内核（`dag/kernel.py` 的 `DurableExecutor` + `ArtifactStore` + `EffectLedger`）接进现有两条执行路径，**扩展不替换**：
1. **job 运行器**（`jobs.py`）：`retry_job` 从「整段重跑」改为「从最近 checkpoint 恢复」；恢复路径经 `EffectLedger.is_consumed` 去重防重发单（**M17 现状雷**）。
2. **agent 运行时**（`agent_runtime.py`）：每个 reAct turn 包成一个节点，LLM 输出经 `ArtifactStore` 落 fixture；replay 读 fixture 不重跑 LLM（R11）。
- effectful 边界在 replay / fork / rollback 一律 **HALT**，发 `RECONCILE_REQUIRED` 事件交对账，**绝不重发单 / 绝不撤单**。

## 侦察接线点（实现时复核行号）

| 文件 | 位置 | 接什么线（扩展不替换） |
|---|---|---|
| `dag/engine.py` | `DAGTaskStatus`(~L25) | 增 `reused` / `halted` 两态，对标内核状态机 |
| `dag/engine.py` | `DAGTask.__post_init__`(~L43–89) | **强制约束**：`kind=effectful` 必须带 `effect_idempotency_key`，否则构造即 raise；旧 `idempotency_key` 转 deprecated 别名 |
| `dag/engine.py` | `run_dag`(~L94–121) | 增可选参 `executor: DurableExecutor \| None`；None 时保持现有全量串行（向后兼容既有 7 测试） |
| `jobs.py` | `stream_job`(~L29–74) | 终态集合加 `halted`；新增 `event:"checkpoint"`（不改 snapshot/progress/done/heartbeat 语义） |
| `jobs.py` | `retry_job`(~L132–138) | **从整段重跑改为 checkpoint 恢复 + `EffectLedger.is_consumed` 去重**（堵 M17 重发单雷） |
| `agent_runtime.py` | `AgentRuntime.run`(~L62–117) | 整 turn 包进节点适配器，LLM 输出落 `ArtifactStore`；不改内部 reAct loop |
| `dag/kernel.py` `artifact_store.py` `effect_ledger.py` | 已实现 | **无改**，仅验证接线（确保 `task.kind`+`effect_idempotency_key` 进 `node_id` 哈希） |

## 对抗测试设计（种已知 bug，门必抓）

1. **durable≠reproducible**：LLM 节点内自增计数器 → replay 时 op 调用 0 次、结果逐字段相同。
2. **节点身份内容寻址**：仅装饰字段不同 → 同 `node_id`；改 structure/inputs/upstream 任一 → id 必变。
3. **effectful 幂等绝不重发单**：同 `effect_idempotency_key` 重跑 → 第二次 `reused=True`、`place_order` 总调用==1。
4. **fork 在 effectful 边界截断**：fork 上游 pure → 下游 effectful `halted`、0 次新下单、发 `RECONCILE_REQUIRED`。
5. **rollback 不撤单走对账**：rollback 到已 consumed effectful 节点前 → 无 cancel/反向单、`requires_reconcile=True`。
6. **崩溃从 checkpoint 恢复**：A(pure)→B(effectful 已下单)→C，C 中崩 → 恢复不重跑 A/B、B 经 ledger 命中 0 新下单、C 重算一次。
7. **缺幂等键被强制拒**：`DAGTask(kind=effectful, key=None)` 构造即 raise。
8. **LLM 当控制器被阻挡**：LLM 输出试图改 deps → 执行顺序==静态拓扑序，与 LLM 输出无关。
9. **memoize 复用不把 honest-N 改小**：同配置连跑 3 次，工件命中 2 次但账本 `on_attempt` 被调 3 次。
10. **裁决措辞诚实**：replay/fork 报告不含 `reproducible/可信/安全/组织独立`，含 `durable/复用工件/未验证`。
- 配套变异：删 lease-required、`is_consumed` 改 noop、忽略 checkpoint → 须全杀。不破坏全量 1001 基线。

## 复用模块

`lineage/ids.py:node_id|canonical_json|DECORATIVE_KEYS`（**唯一身份源,不另算**）· `copy_trade/beta.py:113-152`（幂等账范式）· `test_copy_trade.py`（幂等回归基线）。

## 红线（RULES §5 / DECISIONS）

- **实盘 key 进 LLM**：seed/secret 等凭证绝不走 `task.params` 进 `node_id` 哈希或 context 喂 LLM。
- **M17 重发单**：`jobs.py:132-138` 现状「整段重跑」就是雷，effectful 重试/恢复必先检 `is_consumed`。
- **R11**：durable 复用工件不可变、replay 绝不重跑 LLM（spy/mock 断言 op 调用 0 次）。
- **R1/R8**：memoize 省 compute 但绝不低估 N（命中仍通知账本）。
- **C5/C7/C8**：`node_id` 单一源，不在 kernel/engine/jobs 各自算。

## Open Questions（需关闭，部分需用户拍板）

- **[需拍板]** `effect_idempotency_key` 由谁生成？**建议确定性派生**（`node_id`+业务维度，如 `client_order_id`），**禁 LLM 直接产**（否则重跑漂移换 key 绕过幂等）。`kernel.py:386` `derive_effect_key` 是正向示范。
- `reconcile`（对账）下游消费方是谁、失败如何阻断？本卡只发 `RECONCILE_REQUIRED` 事件 + 留 hook，对账闭环归后续（与执行侧/审批门对接）。
- agent turn 节点化后每 turn LLM 成本/stall 预算：本轮先留 hook 不接 Progress Ledger。
- `run_id ↔ node_id` 一对多存储：建议复用 `JobRecord.run_id` 作句柄，索引细节实现时定。
- fork 后下游 pure 节点 PIT 安全（dataset_version 重解析）：归 D 簇双时态，本卡不动。

## 验收一句话

种重发单 / 重跑 LLM / fork 撤单 → 内核 effectful 边界必截断、走对账不重发；replay 读工件 op 调用 0 次；不破坏 1001 基线。
