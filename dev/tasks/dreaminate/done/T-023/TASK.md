# T-023 · 确定性内核（T-014）接进 jobs / agent / engine 执行路径

- **状态**：done · **review_status**：1（用户 2026-06-19 过目通过；AskUserQuestion 工具丢答 +「继续」→ 采纳推荐项「三卡全过开跑」，同 D-T021 先例）
- **来源**：spine-designs 01（§4 接线 / §5 对抗）+ 00-contracts C1/C5/C7/C8 + R10/R11/M17 · **依赖**：T-014/T-013/T-016 · **优先级**：P0（STATE 头号 gap#4）

## 做了什么（扩展不替换，全程 additive）

把已建并验证的确定性内核（`DurableExecutor`+`ArtifactStore`+`EffectLedger`，T-014）接进三条真实执行路径：

- **engine `run_dag(executor=...)`**（`dag/engine.py`）：新增可选参，传 `DurableExecutor` 即把编排路径切到内核
  （durable 复用 pure 工件 / effectful 经统一幂等账去重 / replay·fork·rollback 在 effectful 边界 HALT）；
  `executor=None`（默认）保持现有全量串行语义——既有 7 个 DAG 测试零改动。身份单一源：node_id 由内核
  （`lineage/ids.py`）算，engine 绝不另算（C5/C7/C8）。循环 import 用 `TYPE_CHECKING` 字符串注解避开。
- **jobs `kernel_dag` job**（`jobs.py`）：`InMemoryJobStore(kernel_root=...)` 携共享 ArtifactStore+EffectLedger；
  `create_kernel_job(tasks, mode=run|replay)`；`retry_job` 从「整段重跑」改为「同图重跑 = 从最近 checkpoint 恢复」
  ——pure 命中已落 durable 工件、effectful 经 `is_consumed` 命中即跳过（**绝不重发单，M17 雷**）。`stream_job`
  终态集合加 `halted` + 新增 `checkpoint` 事件（不改 snapshot/progress/done/heartbeat 语义）。`schemas.py`
  `JobStatus` 加 `halted`、`JobRecord` 加可空 `checkpoint`。
- **agent 节点化（复用 T-016，不另造）**：每 reAct turn 的「LLM 输出落 fixture / replay 读 fixture 不重跑 LLM」
  由注入的 `RecordingLLMClient`（T-016）透明承担——它本身是 `LLMClient`，从 main.py 注入即生效，`agent_runtime.py`
  零逻辑改动（仅加 docstring 说明）。**绝不在 agent 侧另造第二套 store/身份**（单一源红线；fixture_key=node_id 别名出自 ids.py）。
- **生产接线**：`main.py` `JOB_STORE = InMemoryJobStore(kernel_root=DATA_ROOT/"kernel")`——kernel_dag 机制生产可达、非死代码。

## 验收（对抗测试 + 5-lens 复核）

`tests/test_kernel_wiring.py` 14 passed（内核内部行为已由 `test_dag_kernel.py` 25 钉死，本卡只测接线）：
run_dag(executor) durable 复用 / effectful 不重发 / 静态拓扑序 / 复用仍计 attempt（honest-N 不改小）/ executor=None
向后兼容；jobs kernel 崩溃恢复不重发（A→B effectful 已下单→C 崩，retry：A/B reused、placed 一次、C 重算）/
retry 不重发 / **replay job 在 effectful 边界 HALT 收于 halted、绝不触达券商** / SSE checkpoint+halted 终态；
agent replay 整 turn 0 LLM 真调用 + 逐字段一致 / replay 未命中抛 ReplayMiss 不回退真 API（R11）；变异：拆掉
`is_consumed` 幂等闸 → 必重发单（证明闸是承重墙）。全量 **1046 passed / 13 skipped**（基线 1001 未破）。

**5-lens 对抗复核**：1 MEDIUM 真发现已修——`retry_job` 丢 `spec["mode"]`，replay job 的 retry 静默降级为 run →
「重放只读不触达券商」翻成真下单；已透传 `mode=spec.get("mode","run")` + 补对抗测试
`test_kernel_job_retry_preserves_replay_mode`（retry 仍 halted/placed 不变）。

## 诚实残余（非阻断，记入后续）

- `reconcile`（对账）下游消费方未闭环：本卡只发 `RECONCILE_REQUIRED` 事件 + 留 hook，对账闭环归后续。
- agent turn 节点化的 Progress Ledger（每 turn 成本/stall 预算）本轮留 hook 未接。
- 生产暂无 `create_kernel_job` 业务调用方：机制 live-ready（retry 经 EffectLedger 去重、SSE 支持 halted/checkpoint），
  待首个 kernel_dag 生产 producer 接入。
