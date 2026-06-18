# 机构级 Agent OS · 脊柱 build-ready 设计（二轮·第一簇）

> 7 部件并行设计 + 异角色契约/测试真实性复核（全 Opus 4.8）· 2026-06-16
> 接 [R1–R29 决策](../decisions-r1-r29.md) · 每份含 §4 file:line 接线 + §5 对抗式测试规约

## 索引

| # | 部件 | 接线点 | 对抗测试 | 状态 |
|---|---|---|---|---|
| [01](01-deterministic-kernel.md) | 确定性 DAG 内核 + checkpoint/replay/fork/rollback + 交易副作用不可幂等边界 | 8 | 10 | build-ready |
| [02](02-llm-record-replay.md) | LLM 节点 record/replay + 受控翻译层 | 9 | 17 | build-ready |
| [03](03-lineage-bus.md) | PROV 谱系总线 + run 快照强制属性 + config_hash/ledger/event 权威产方 | 9 | 15 | build-ready |
| [04](04-hypothesis-card.md) | 可证伪假设卡 + 预注册 + confirmatory/exploratory(P2 不挡探索) | 18 | 16 | build-ready |
| [05](05-trial-ledger.md) | R1/R8 内容寻址试验账本(honest-N+memoize) + N_eff 收益聚类 + 多证据三角 gate | 8 | 16 | build-ready |
| [06](06-security-rbac-gate.md) | Agent 安全 + 确定性策略门 deny-by-default + 交易所侧硬墙 | 15 | 18 | build-ready |
| [07](07-approval-gates.md) | HITL 审批门双通道 + promote 状态机 + 幂等恢复 | 11 | 16 | build-ready |
| [00](00-contracts-and-coherence.md) | **跨部件契约一致性 + 测试真实性复核**（异角色，必读） | — | — | 复核完成 |

## 复核（00）的核心结论

**接线点核实**：抽查 14 处 file:line 全部命中（含 `engine.py:52` idempotency_key、`store.py:232` promote 三行裸翻转、`eval/dsr.py:33/:41`、`data_packages.py:70` 的 16 位哈希不变量等）。无写错文件/越界行号。

**测试真实性**：7 份 §5 **绝大多数是"真对抗"**（种已知bug门必抓），03/04 的 §5 还主动把 mock 测标 `[集成必补]`，是 7 份里最诚实的。

**最高价值发现（验证官抓出的"假绿灯"具体形态）**：honest-N 不可改小被 03/04/05/07 **四处独立测、四处全绿**——但当前 config_hash 双算法 + 账本双实现未解决，**四处测的其实是三本不同的账**，合起来仍是"四本账各自的剧场"。**这正是"绿灯可能是 bug 造的假信号"的真实样本，被异角色复核当场抓住。**

## 落地前必须由人拍板的 3 个结构性合并（见 00 §1.2-A/I + §附）

1. **config_hash 单一算法**：03 与 05 各产一套（03 `[:16]`无前缀 / 05 `cfg_+[:24]`，且 05 的 24 位违反全库 16 位不变量）。
2. **试验账本一本账**：03 `lineage/ledger.jsonl` 与 05 `experiments/trial_ledger.jsonl` 两本并存，R8"同一本账"裂开。
3. **部件12 验证官提前**：04/06/07 的独立验证(`verdict_id`)全卡未建的部件12，不提前则脊柱右半边真集成测试全停 mock。

## 建设依赖顺序（00 §标注②）

- **第 0 层（并列最先，共用一份 `node_id.py`）**：03 谱系总线+账本本体+config_hash权威 ‖ 01 确定性内核 — 必须同期，对齐 node_id↔content_hash↔checkpoint_id 三角。
- **第 1 层**：05 只建算法层（N_eff 聚类+多证据三角 gate），账本存储归 03、删自己的存储层。
- **第 2 层**：02 LLM record/replay ‖ 04 假设卡。
- **第 3 层**：06 安全门 ‖ 07 审批门。
- **第 4 层（应提前并行）**：部件12 验证官（产 verdict_id）。
