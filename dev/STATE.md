# STATE · 现状 vs GOAL（诚实 gap 陈述器输出）

> 每个 Goal Loop 重生。**纪律：🟡「声称但未验证」绝不写成 ✅「已建并验证」——不假绿灯（= 产品「不给小白假绿灯」原则掉转枪口对准我们自己）。**
> 上次刷新：2026-06-18（T-022 INV-3 lease-唯一-key 通道闭合：LeasedBinanceVenue 构造不持 key、真 key 只在门放行后 S4 物化、has_key 不 fetch；既有 venue 零改动 additive；10 对抗测试 + 4 变异全杀 + 5-lens 复核 15→1[LOW]修；全量 1000 测试绿。**安全门生产接线全链闭合，BOARD 无 todo**。上上次：T-021 安全门生产接线：relay 必经 deny-by-default 策略门（INV-2/M17 生产强制）+ 默认门模板 + 防重放 + 真钱 fail-closed；16 对抗测试 + 8 变异全杀 + 5-lens 复核 4 真发现全修（现货/市价全拒）；全量 990 测试绿。🟡 INV-3 lease-唯一-key 通道→T-022。上上次：T-020 验证官=脊柱最后一块：异模型一致性，产 content-addressed verdict_id，喂 T-017/T-019；异模型不一致即 BLOCK(不取均值)/独立性度量非假定/concern≠pass/措辞禁组织独立；含生产接线 + verdict↔工件绑定 + 防篡改读路径；31 对抗测试 + 10 变异全杀 + 5-lens 复核 18→5 真发现全修；全量 974 测试绿。**脊柱 8 块全建并验证**，T-018 生产接线→T-021）
> **harness 自检**：`python dev/scripts/validate_dev.py` → PASS（对抗验证过：藏掉 done 记录即 FAIL）。

<!-- 格式·防跑偏 | 结构型（每 loop 整篇重生,不是追加）：固定三块——
① 子系统现状表(列：子系统 | 状态 ⬜未建/🟡部分未验证/✅已建并验证 | 证据 | gap) ② 头号 gap 编号列表 ③ 待决策岔路(点名,别让人翻卡)。
铁律：🟡 绝不写成 ✅（不假绿灯）；测试数等易变值别写死,以实跑为准。 -->
> 审计修复：v2/v3 项目设计文档归位 `docs/plans/`（曾误卷进 dev archive）· 旧 codex 任务残留归 `tasks/_archive/` · 补 `done/T-012/` 落档 · 建 `exec/LOG.md` + `scripts/validate_dev.py`。

## 终态结构（GOAL §1 两层相乘）

- **层1 功能平台 M1–M21**：原始 §13 清单大部分 ✅ 已建（763 测试基线绿）——平台「能跑」。
- **层2 机构级 Agent OS 治理**：本阶段在建——把零件接成不可绕过的闸门。**绝大多数 gap 在层2。**
- 头号风险不是「缺零件」，是层1 零件**未被层2 贯穿治理**（M10 守门未接进 run、M12 promote 是裸 flip、M13 是 mini DAG）。

## 脊柱（A 簇 · 第 0–3 层）

| 部件 | 状态 | 证据 | gap / 下一步 |
|---|---|---|---|
| `lineage/ids.py` 单一身份源(config_hash/node_id/content_hash) | ✅ 已建并验证 | `tests/test_lineage_node_id.py` 8 passed | — |
| 7 份脊柱 build-ready 设计 | 🟡 **设计完成、逐个实现中** | `research/findings/spine-designs/00-07` | 03(ledger 部分)✅、余下逐个 |
| 一本账 lineage ledger(SQLite WAL+JSONL, honest-N+memoize) | ✅ 已建并验证 | `tests/test_lineage_ledger.py` 25 passed + 13 变异全杀 + 二轮复核 | — |
| 01 确定性内核(node身份/durable/effectful边界) | ✅ 已建并验证 | `tests/test_dag_kernel.py` 25 passed + 15 变异全杀 + money-safety 复审无 HIGH | 🟡 jobs/agent 接线 deferred |
| 05 试验账本算法层 + 多证据三角 gate | ✅ 已建并验证 | `tests/test_overfit_gate.py`+`test_gate_wiring.py` 24 passed + 变异全杀 + 5-lens 复核 | — |
| 02 LLM record/replay + 受控翻译层 | ✅ 已建并验证 | `tests/test_llm_record_replay.py` 30 passed + 变异全杀 + 5-lens 复核 | 🟡 受控解码(seed/fingerprint) deferred |
| 04 假设卡(P2 不挡探索) | ✅ 已建并验证 | `tests/test_hypothesis_card.py` 35 passed + 变异全杀 + 5-lens 复核 | ✅ 验证官已接(T-020：blocked 拒/concern 带 needs_review/张冠李戴拒)；Run连接 [集成必补] |
| 06 安全门 gate + 生产接线 + INV-3 | ✅ relay 全链：策略门(T-021)+INV-3 key 只在门后物化(T-022) | `test_security_gate_adversarial`+`test_copy_trade_gate`+`test_leased_binance` + 变异 + 5-lens×3 | ✅ relay 闭合；TCB 天花板诚实标注 |
| 07 审批门 + promote 状态机 | ✅ 已建并验证（含生产接线） | `tests/test_approval_gates.py` 22 passed + 5 变异 + 5-lens 复核 | — |
| 12 验证官 | ✅ 已建并验证（含生产接线） | `tests/test_verification_verdict.py` 31 passed + 10 变异 + 5-lens 复核 | — |

## 层1 功能平台子系统（vs GOAL §7，诚实 gap）

| 子系统 | 层1（功能） | 层2（治理） | gap / 接线点 |
|---|---|---|---|
| M3/M8 数据层 | ✅ 多源可插拔 v2 + 宽字段 | 🟡 PIT 部分，**全库双时态未做**（R28） | bitemporal known_at 落库 |
| M4–M5 特征/标签 | ✅ 三重障碍 + 防泄露 | 🟡 N_eff 泄露门已建（T-015：等价写法收益聚类）；特征级泄露探针仍待接 | 因子轨 §3 |
| M6 模型训练 | ✅ 训练台 + 19 卡 + DL harness | 🟡 输出未走信号契约（R17） | 因子轨 §3 |
| M7–M8 信号/组合 | 🟡 部分（融合 + HRP/ERC/NCO） | ⬜ 组合未上多证据三角 | 方法学 §4 |
| M9 执行/风控 | ✅ A股 paper + 加密 live + ladder | ✅ 安全门 relay 全链生产强制（T-021 策略门 INV-2/M17/INV-4 + T-022 INV-3 key 只在门后物化） | TCB 天花板：唯一硬墙在交易所侧（诚实） |
| M10 回测/归因/监控 | ✅ PBO/DSR/bootstrap 存在 | ✅ **已接进 run 闸门**（T-015 多证据三角 gate：promote 注入 dsr/pbo→risk_summary 真触发、honest_n 兜底通缩） | — |
| M11 因子生命周期 | 🟡 toy 五态机 | ⬜ 机构级（衰减/拥挤/容量/因子族）未做 | 因子轨 §3 |
| M12 实验/模型注册表 | ✅ append-only + lineage | ✅ honest-N 一本账（T-013）+ **promote 审批门状态机（T-019：三要件/approver≠creator/缺口清单，端点已接）** | — |
| M13 编排调度 | 🟡 mini DAG | ✅ 确定性内核 `DurableExecutor`（node身份/durable/effectful HALT边界）已建（T-014）；🟡 jobs/agent 接线 deferred | — |
| M14 Agent | ✅ tool schema + 工作台 | ✅ LLM 受控（T-016：record/replay + 受控翻译门挡越权；opt-in `LLM_REPLAY_MODE`）| — |
| M15 前端 | ✅ RunDetailPage 冻结 | ⬜ 治理新页面（证据下钻 L1–L4）未加 | 信任层 §6 |
| M16–M21 社区/跟单/IDE/教学/实盘安全/示例 | ✅ 全已建 | n/a | — |

## 层2 脊柱（A 簇 · 第 0–3 层）

| 部件 | 状态 | 证据 | gap / 下一步 |
|---|---|---|---|
| `lineage/ids.py` 单一身份源 | ✅ 已建并验证 | `tests/test_lineage_node_id.py` 8 passed | — |
| `dev/GOAL.md` 终态蒸馏 | ✅ 完成 | `dev/GOAL.md`（两层相乘、剔过渡） | — |
| 7 份脊柱 build-ready 设计 | 🟡 设计完成、逐个实现中 | `research/findings/spine-designs/00-07` | 03(ledger)✅、余下逐个 |
| 一本账 ledger(SQLite WAL+JSONL, honest-N+memoize) | ✅ 已建并验证 | `tests/test_lineage_ledger.py` 25 passed + 13 变异全杀 | — |
| 01 确定性内核(node身份/durable/effectful边界) | ✅ 已建并验证 | `tests/test_dag_kernel.py` 25 passed + 15 变异 + money-safety 复审无 HIGH | 🟡 jobs/agent 接线 deferred |
| 05 试验账本算法层 + 多证据三角 gate | ✅ 已建并验证 | `tests/test_overfit_gate.py`+`test_gate_wiring.py` 24 passed + 变异全杀 + 5-lens 复核 | — |
| 02 LLM record/replay + 受控翻译层 | ✅ 已建并验证 | `tests/test_llm_record_replay.py` 30 passed + 变异全杀 + 5-lens 复核 | 🟡 受控解码 deferred |
| 04 假设卡(P2 不挡探索) | ✅ 已建并验证 | `tests/test_hypothesis_card.py` 29 passed + 变异全杀 | 🟡 [集成必补] |
| 06 安全门 gate + 生产接线 + INV-3 | ✅ relay 全链（T-021+T-022） | `test_copy_trade_gate` 18 + `test_leased_binance` 8 + 变异 | ✅ relay 闭合 |
| 07 审批门 + promote 状态机 | ✅ 已建并验证 | `tests/test_approval_gates.py` 22 passed + 5 变异 | — |
| 12 验证官 | ✅ 已建并验证 | `tests/test_verification_verdict.py` 31 passed + 10 变异 | — |

## 头号 gap（按优先级）

1. ~~M10 守门未接进 run 闸门~~ ✅ **闭合（T-015）**：多证据三角 gate 接进 promote，PBO/DSR 从死接活、honest_n 兜底通缩、噪声不绿。**层2 第一个活性证明已立。**
2. ~~一本账 / 确定性内核~~ ✅ 已建（T-013/T-014）——脊柱第 0 层地基 3 块齐（`ids.py` + `ledger.py` + `dag/kernel.py`）。
3. **M12 promote 是 3 行裸 flip**（无 approver≠creator）——层1 已建件待层2 改造（T-019）。
4. **内核 deferred**：`jobs.py` SSE（halted/checkpoint）+ `agent_runtime.py` 节点化（与 T-016 重叠）择期接——诚实标 🟡 未做。
5. **gate 后续增强**（已记录，非阻断）：gate_verdict.color→risk_summary trust_level 映射；IDE config 粒度（params 入 metadata 才进 config_hash）。
6. **安全门生产接线全链闭合**：T-021 relay 必经 deny-by-default 策略门（INV-2/M17/INV-4）+ T-022 INV-3（LeasedBinanceVenue 构造不持 key、真 key 只在门放行后 S4 物化、has_key 不 fetch、既有 venue 零改动 additive）。**诚实限界**：TCB 天花板（本地门=防篡改证据非防篡改，唯一硬墙在交易所侧——工程设计极限,不会再改）。**诚实残余**：非 relay live 路径未逐一接线（→ 收口 T-025）。
7. 现有**测试基线绿**（数目以实跑 `pytest` 为准,别据此判断）；新增代码须不破坏它 + 自带对抗测试（种已知 bug 门必抓）。

## 待决策岔路（等用户拍板）
> 卡在用户经济/产品判断上的开口——**点名**,别让人去翻任务卡 Open Questions。
- **T-024 · exploratory↔confirmatory 判定信号从哪来**（谁判一个 run 是探索还是可下注确认）。建议:用户在 `StrategyGoal` 显式声明/晋级。
- **T-025 · 急停 kill/emergency 的 fail 模式**（平仓本体 fail-open 不被门挡 vs 全过门）。建议:平仓 fail-open + 端点加鉴权。
