# Agent OS 设计

> 本文是研究总综合给出的 Agent OS 架构建议，已把完备性复核的关键修正（确定性 / 成本 / 安全）就地织入。证据见 [99-research-appendix.md](99-research-appendix.md) 的 A 组（流 1–4）。

## 架构选择

**确定性工作流图（DAG）骨架 + 节点内有界 LLM 自主 + 仅在弱耦合超窗环节用 orchestrator-worker 的混合架构。**

- **对用户**：呈现为单一连贯助手。
- **对系统**：底层是"治理导轨上的多器官"，而非让多 agent 自由编排彼此。

### 为什么是确定性骨架，不是多 agent 自由编排

已逐文件核实：`agent_runtime.py` 是单线程 reAct（`max_steps=6`），无 checkpoint / interrupt / turn 外记忆，且与 `dag/engine.py` 完全互不引用；`dag/engine.py` 是串行拓扑执行、无 approve/interrupt/checkpoint。把二者拧成一条确定性 DAG（节点 = 假设/数据/因子/标签/模型/信号/组合/独立验证/审批/上线/监控），让 LLM 自主性收敛在"节点内执行"，是把"散的 agent"变成"有治理导轨的 Agent OS"的**根动作**——其余所有闸门都挂在此骨架上。

选确定性骨架的理由：

1. **MAST（UC Berkeley）/ Cognition 都警示**：自由编排放大"规范缺陷 + 决策分散"（多 agent 失败的高发区）。
2. 本愿景的信任**完全建立在"流程可被非程序员审计"之上**，确定性图天然可时间旅行、可回放、可逐节点解释。
3. **组合与执行环节明确保持单线程**（尊重 Cognition 立场，勿让 agent 互相传话）。
4. **只在 假设生成 / 因子海 / 文献海** 这类弱耦合、信息超上下文窗的环节，才引入 lead + 并行 subagent（subagent 写文件系统避免传话游戏），并用 Elo / 对抗式评议给候选打分排序成非程序员可读的"谁更可信"（Anthropic 多 agent research 范式：可并行任务上 +90.2%，但 ~15x token）。

> ⚠️ **完备性复核的反驳（必须先解决）**："确定性 DAG 天然可时间旅行/可回放"被当事实陈述，但 **LLM 节点（clarifier/researcher/verifier）固有非确定性**。GOAL §1.2 的可复现保证（同代码+dataset+seed → ±1e-6）在 LLM 进入图节点的那一刻被静默破坏。**在声称"可回放"之前，必须先工程化**：prompt/模型版本/seed/temperature 固定、响应缓存、以及"混入确定性阈值去 LLM 自偏好"如何与随机 LLM 共存。详见 [03-open-questions-and-risks.md](03-open-questions-and-risks.md) 盲点 (2)。

---

## 7 个器官

> 对用户是一个助手；内部是治理导轨上各司其职的器官。

| 器官 | 职责 |
|---|---|
| **需求澄清官 Clarifier** | 把模糊念头经 `SOCRATIC_DECISION` + 信息增益式提问排序（GATE/EIG 轻量实现，只问 top 问题），逼出带 `economic_mechanism` / `falsification_condition` / `stop_rule` 的良构可证伪**假设卡**；内置 reality-check 规则，在澄清阶段就温和证伪过拟合预期/趋势追逐/择时跑赢大盘，并改写为可检验小假设 |
| **数据工程官 Data Engineer** | 声明式接入 `DataConnector`（择机 MCP 式工具注册），落地 **bitemporal 双时间轴**（`knowledge_date`/`transaction_time`）按 knowledge_date 截断，维护 `InstrumentSpec`/交易日历/复权-PIT；"特征定义即代码、研究实盘同源 PIT as-of join"（中低频**不上线在线 feature store**——核查指出 training-serving skew 根因在执行边界） |
| **研究官 Researcher** | 节点内做因子/标签/模型/信号工程；产出全部进谱系；候选因子**先对 `FactorRegistry` 现有因子族正交化取残差 alpha 的增量 t**，并跨 A股/加密双 connector 复制验证 IC/方向一致性（兑现资产无关硬约束） |
| **验证官 Verifier/Challenger**（与研究官**硬分离**、异模型） | 对照预注册计划做**有效挑战**——异种子/异数据切片/CPCV 独立重跑，调用证伪协议引擎（N、PBO、DSR、PSR、MinBTL、purge/embargo、种子、`dataset_version` hash 一次性固化为**不可篡改报告**），判定混入确定性阈值去 LLM 自偏好，**有权 block** 并产出"质疑清单 + 通过/未通过 + 理由"写入审批门 |
| **风控官 Risk Officer** | 管 live 端闭环——minTRL / PSR-live / CUSUM / Page-Hinkley 变点检测 + PSI + 滚动夏普衰减，按 regime 条件化避免误判，触发降资本/暂停/移交 M11 `WARNING→RETIRED`；执行成本/容量/funding/borrow 真实计提与超容量 go/no-go 闸门 |
| **资本配置官 Allocator** | 把多个策略净值当资产做 meta-allocation（逆波动 + HRP 两个稳健基线，与等权严格 walk-forward 对照），DSR 接成**软门槛**（>0.95 评分而非硬否），pod 级 kill/scale 阈值**用户预注册可配**（不硬编码） |
| **解释官 Explainer/Translator**（贯穿全器官） | 复用 M19 渐进披露，把每个闸门翻成 **L1 一句话经济叙事 + 红黄绿过拟合体检 + 反事实 + go/no-go 卡片**，L2 给 IC 衰减/regime 失效条件，L3/L4 才露 DSR/PBO/SHAP/超参；对解释做反事实一致性/跨 regime 稳定性自检 |
| **编排官 Orchestrator** | 维护 DAG 状态机、durable checkpoint、长程 harness（session 起步读进度 + 谱系恢复上下文、按 compaction 重启上下文窗、每节点留 clean checkpoint），并在弱耦合环节调度 subagent |

---

## 记忆模型（三层）

1. **短时**：`AgentTurn` 内的 reAct 步。
2. **长程会话**：DAG 节点级 durable checkpoint + 高保真 compaction 摘要 + 结构化进度笔记；session 重启时先读进度文件与谱系恢复上下文。
   - > 核查纠正：按 Anthropic *Effective context engineering* **已确认的** compaction + memory-tools 实现，**勿照搬**"每次工具调用反馈剩余容量 / programmatic tool calling"——核查指出系与其它帖混淆。
3. **持久谱系总线**：**PROV-AGENT 式 W3C PROV schema**，把每次 agent 的 prompt/response/工具调用/产出/`dataset_version`/下游指标接成可审计 DAG；扩展 `experiments/store.py` 现有 Run lineage（当前只到 `parent_run_id`/`forked_from` 的 backtest Run 级），并记录"原始念头 → 澄清问答 → `HypothesisSpec` → 预注册时间戳"**不可变链**。
   - > 把"谱系 → 恰当信任"当**需自验假设**，配反向校准检查（PROV-AGENT 原型只在 ORNL 金属 3D 打印 HPC 工作流评估过，未证明经济学者能读懂谱系 DAG——不可直接外推）。

---

## HITL 模型：工程全自主、经济判断与风控停人

停点设为 DAG 上**可持久挂起数小时/数天**的 interrupt-and-approve 节点：

1. **假设预注册冻结**（碰最终验证集前，经济学者逐条确认机制/标的池/stop_rule）
2. **审批门 promote**（晋升 staging/production 必须附 独立验证记录 id + `approver≠creator` + 过拟合证据快照 + champion/challenger 结论，缺任一即拒绝并返回缺口清单——直接堵 `ModelRegistry.promote()` 当前裸状态切换的最致命缺口）
3. **资本配置**（按资金/超容量/kill-scale 阈值）
4. **上线**（衔接 M20 Live Ladder / M9 KillSwitch）
5. **live 漂移触发的降级/退役**（drift-triggered **必须人在环**，经预注册测试 + 人工 go/no-go 再验证，而非全自动晋级）

> agent 在每个停点用自然语言陈述 go/no-go 理由 + 可回放谱系，人只按按钮。
>
> ⚠️ **完备性复核警告**：五道长达数天的闸门会导致**决策疲劳 → 橡皮图章**，反噬"人只供经济判断"的核心。需设计低风险审批的批处理/委派，以及 confirmatory/exploratory 二分驱动的**轻量探索通道**。详见 [03](03-open-questions-and-risks.md) 盲点 (5)(7)。

---

## 防过拟合护栏（多层硬护栏）

1. **留出集硬隔离** — 在 `dataset_version` 切一块锁定 OOS/最终验证集，agent 探索期"权限层技术上无法访问"（而非约定），只在审批门一次性揭盲；配红队回归套件（自动注入诱导性提示/未来数据/"换种子再跑"）作为上线前 gate。
   - > ⚠️ 核查：单机 DuckDB/Parquet 本地优先架构（§1.1）下**不存在真实访问控制边界**（用户能读 Parquet = 能读 OOS）。"技术上不可访问"与"本地优先/开放落盘/可独立审计导出"有结构性张力——须先解决，否则降级为"约定"。
2. **证伪优先** — 默认结论是"该策略无效"；体检从"打灰标不阻塞"升级为**硬闸**（MinBTL 给定 N 与观测 SR 样本不足直接拒绝）。
3. **honest-N** — N 从 store 沿 `parent_run_id`/`forked_from` 谱系自动累加（含失败/弃用），先做相关聚类/ONC 估有效独立试验数 N_eff，自动注入 DSR/PBO；翻成赌场直觉"每多试一次门槛自动变高"。
   - > ⚠️ 核查：N_eff（相关试验估有效独立数）是**有争议的硬统计问题**，不是接线——估错任一方向都会静默击穿所有多重检验校正。应重分类为深方法学任务。
4. **把 DSR/PBO/Bootstrap 真正接进 `main.py` run 完成处**（当前无生产调用方）。
5. **反谄媚** — coach system prompt 写入"拒绝顺着用户优化、每次再调参显式提示 N 上升与门槛抬高、为什么这在经济上该有效=继续优化前必答闸口"。
6. **不确定性量化 + abstain** — 信号层 conformal/CQR 预测区间 + regime 偏离训练分布触发 abstain（不交易）接 KillSwitch。
7. **DSR 标度修正** — 增 `var_sr_hat` 入参按 False Strategy Theorem，旧式仅作退化近似并标注（用词标"标度修正"非"修复系统性低估"）。

> ⚠️ **完备性复核：安全护栏的依赖顺序是倒置的**。实盘 Binance 交易 key 与"能接线执行的 agent"自 P0 起就在场，但 MCP/HMAC/withdraw-deny 安全模型被放到 P5 可选。红队目前只覆盖过拟合，**完全没有** prompt-injection（经摄入文献/新闻）、tool-abuse（能下单的 agent）、因子海数据投毒、探索 agent 与锁定 OOS 的特权混淆。**安全模型必须前移到 P0/P1 脊柱**。详见 [03](03-open-questions-and-risks.md) 盲点 (4)。
