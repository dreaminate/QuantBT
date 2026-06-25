# STATE · 现状 vs GOAL（诚实 gap 陈述器输出）

> 每个 Goal Loop 重生。**纪律：🟡「声称但未验证」绝不写成 ✅「已建并验证」——不假绿灯（= 产品「不给小白假绿灯」原则掉转枪口对准我们自己）。**
> 上次刷新：2026-06-25（**Mathematical Spine 一致性门核心落地**——头号 gap #3 命门接活：4 个数据模型（MathematicalArtifact/TheoryImplementationBinding/ConsistencyCheck/MethodologyChoiceRecord，§6 字段全含）+ `evaluate_promotion` 升级健全谓词门（8 子句逐条对 §6/§8 一条「→ 拒」）+ append-only `SpineLedger`（复用 `ids.content_hash` 测 staleness、`ledger._ChainStore` 哈希链，无改小/伪造 API）。理论先行 finding `spine-consistency-gate/00`。**28 对抗测试种坏门全抓**（公式无 binding/实现不一致/binding 过期/跳证明标 proof-backed/estimator 不绑 PIT 真拒 + 全绿路径放行 + 拒绝口径不越权 + 账本篡改可检），全量后端 **1324 passed / 13 deselected**（未破基线）。**全链贯穿（data→factor→…→monitor 每个数学点接 binding）仍是后续切片**；PIT 子句未与 R28 resolver 真连点查。worktree `auto/math-spine`，commit/push 自管、land 待用户。上一轮（2026-06-19）：**簇A 脊柱收尾全完成**——收口第一波。T-023 确定性内核接进 jobs/agent/engine 执行路径（run_dag executor 参 / kernel_dag job：checkpoint 恢复 + EffectLedger 去重绝不重发单 / replay 边界 HALT / agent 复用 T-016 RecordingLLMClient 不另造 store；14 接线对抗测试）；T-024 可证伪假设卡接进 Run 生命周期（Run.layer/card_id 可空字段 + 6 端点 + promote_model 闸门 + D-T024-FALS 低可证伪硬透明+软决定 override 留痕；16 对抗测试，措辞 0 hit）；T-025 真钱审计不变量 + 急停 IP+密码鉴权 + emergency 真平仓 + GenericVenue 接活 deny-by-default+OrderGuard + relay 向后兼容真钱陷阱闭合（15 对抗测试）。**5-lens 对抗复核 3 真发现全修**（1H：急停含失败硬编码 ok:True=假绿灯→据 results 派生诚实状态；1M：retry 丢 replay mode→重放降级真下单；1L 同源）。全量 **1046 测试绿**（基线 1001 未破）。**下一步/todo 以 `board/dreaminate/board.md` + `DEVMAP` 为准，勿据此头部摘要判断**。上次：T-022 INV-3 lease-唯一-key 通道闭合；全量 1000 测试绿。上上次：T-021 安全门生产接线 relay 必经 deny-by-default 策略门；全量 990 测试绿。**脊柱 8 块全建并验证**）
<!-- 格式·防跑偏 | 结构型（每 loop 整篇重生,不是追加）：固定三块——
① 子系统现状表(列：子系统 | 状态 ⬜未建/🟡部分未验证/✅已建并验证 | 证据 | gap) ② 头号 gap 编号列表 ③ 待决策岔路(点名,别让人翻卡)。
铁律：🟡 绝不写成 ✅（不假绿灯）；测试数等易变值别写死,以实跑为准。 -->
> 审计修复：v2/v3 项目设计文档归位 `docs/plans/`（曾误卷进 dev archive）。

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
| 01 确定性内核(node身份/durable/effectful边界) | ✅ 已建并验证 + **接线生产路径(T-023)** | `tests/test_dag_kernel.py` 25 + `test_kernel_wiring.py` 14 passed | ✅ jobs/agent/engine 已接(T-023)；reconcile 对账闭环 + kernel_dag 生产 producer 待后续 |
| 05 试验账本算法层 + 多证据三角 gate | ✅ 已建并验证 | `tests/test_overfit_gate.py`+`test_gate_wiring.py` 24 passed + 变异全杀 + 5-lens 复核 | — |
| 02 LLM record/replay + 受控翻译层 | ✅ 已建并验证 | `tests/test_llm_record_replay.py` 30 passed + 变异全杀 + 5-lens 复核 | 🟡 受控解码(seed/fingerprint) deferred |
| 04 假设卡(P2 不挡探索) | ✅ 已建并验证 + **接进 Run 生命周期(T-024)** | `test_hypothesis_card.py` 35 + `test_hypothesis_run_wiring.py` 16 passed | ✅ 验证官已接(T-020)；**Run 接入 + 6 端点 + promote 闸门 + D-T024-FALS override 留痕(T-024)**；端到端集成 [必补] |
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
| M9 执行/风控 | ✅ A股 paper + 加密 live + ladder | ✅ 安全门 relay 全链生产强制（T-021/T-022）+ **真钱审计不变量 + 急停 IP+密码鉴权 + emergency 真平仓 + GenericVenue 接活经门 + 向后兼容真钱陷阱闭合（T-025）** + **急停/紧急平仓 IP 改服务端从连接派生 + 二次鉴权升级为服务端真校验密码(PBKDF2)/2FA TOTP、废自证 bool（D-KILLSWITCH-IP，2026-06-22）** | TCB 天花板：唯一硬墙在交易所侧（诚实） |
| M10 回测/归因/监控 | ✅ PBO/DSR/bootstrap 存在 | ✅ **已接进 run 闸门**（T-015 多证据三角 gate：promote 注入 dsr/pbo→risk_summary 真触发、honest_n 兜底通缩） | — |
| M11 因子生命周期 | 🟡 toy 五态机 | ⬜ 机构级（衰减/拥挤/容量/因子族）未做 | 因子轨 §3 |
| M12 实验/模型注册表 | ✅ append-only + lineage | ✅ honest-N 一本账（T-013）+ **promote 审批门状态机（T-019：三要件/approver≠creator/缺口清单，端点已接）** | — |
| M13 编排调度 | 🟡 mini DAG | ✅ 确定性内核 `DurableExecutor` 已建（T-014）+ **接进 run_dag/jobs/agent 执行路径（T-023：checkpoint 恢复去重绝不重发单 / replay 边界 HALT）** | — |
| M14 Agent | ✅ tool schema + 工作台 + **对话回测接真引擎（DS-1：backtest.run 无 run_id → 合成策略→沙箱跑真样本→promote 落 RUN_ROOT 产真 run_id，消灭 runs.jsonl 占位、统一注册表 Fork3=A）** | ✅ LLM 受控（T-016：record/replay + 受控翻译门挡越权；opt-in `LLM_REPLAY_MODE`）| 🟡 真 LLM 合成注入=DS-2；沪深300 真样本需 TUSHARE_TOKEN（码路已建测） |
| M15 前端 | ✅ RunDetailPage 冻结 | 🟡 治理新页面 epic 完成（cfb0fea9：**24 卡 done** 整套台 DC→React · 后端 pytest 1231 + 前端 vitest 241 passed + tsc + build 绿 · 残余诚实：部分未接端点仍 mock / T-042 桌面 tauri build 待工具链 / 3 pre-existing bug 已 spawn）· **导航收口（D-NAV-UNIFY，2026-06-22）：Research/Workshop/Models 三 tab→单 Workshop + 新增总览台、6 台切换器、旧分散页搬台/退役** · **前端交互 bug 修复批 + OOS 泄露补传 train_fraction + 文案去 AI feature 包装（D-FE-REVIEW，2026-06-22，已 push fullstack；tsc0/前端241）** | 信任层 §6 |
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
| 04 假设卡(P2 不挡探索) | ✅ 已建并验证 + 接进 Run(T-024) | `test_hypothesis_card.py` 35 + `test_hypothesis_run_wiring.py` 16 passed | ✅ Run 接入(T-024)；端到端集成 [必补] |
| 06 安全门 gate + 生产接线 + INV-3 | ✅ relay 全链（T-021+T-022） | `test_copy_trade_gate` 18 + `test_leased_binance` 8 + 变异 | ✅ relay 闭合 |
| 07 审批门 + promote 状态机 | ✅ 已建并验证 | `tests/test_approval_gates.py` 22 passed + 5 变异 | — |
| 12 验证官 | ✅ 已建并验证 | `tests/test_verification_verdict.py` 31 passed + 10 变异 | — |
| Mathematical Spine 一致性门核心 | 🟡 门 + 数据模型已建并验证、全链贯穿待续 | `tests/test_mathematical_spine_consistency_gate.py` **28 passed**（种坏门全抓 + 全绿放行 + 拒绝口径不越权 + 篡改可检）；复用 `ids.content_hash`/`ledger._ChainStore` | ✅ §6/§8 命门接活（公式无 binding/实现不一致/binding 过期/跳证明标 proof-backed/estimator 不绑 PIT 真拒）；**待续**：data→factor→…→monitor 全链每个数学点接 binding；PIT 子句未连 R28 resolver 真点查 |

## 头号 gap（按优先级）

1. ~~M10 守门未接进 run 闸门~~ ✅ **闭合（T-015）**：多证据三角 gate 接进 promote，PBO/DSR 从死接活、honest_n 兜底通缩、噪声不绿。**层2 第一个活性证明已立。**
2. ~~一本账 / 确定性内核~~ ✅ 已建（T-013/T-014）——脊柱第 0 层地基 3 块齐（`ids.py` + `ledger.py` + `dag/kernel.py`）。
3. **M12 promote 是 3 行裸 flip**（无 approver≠creator）——层1 已建件待层2 改造（T-019）。
4. ~~内核 deferred：jobs SSE + agent 节点化~~ ✅ **闭合（T-023）**：run_dag(executor) + kernel_dag job（checkpoint 恢复 + EffectLedger 去重绝不重发单 + halted/checkpoint SSE）+ agent 复用 T-016 record/replay。**诚实残余**：reconcile 对账闭环 + kernel_dag 生产 producer 待后续（非阻断）。
5. **gate 后续增强**（已记录，非阻断）：gate_verdict.color→risk_summary trust_level 映射；IDE config 粒度（params 入 metadata 才进 config_hash）。
6. **安全门生产接线全链闭合**：T-021 relay 必经 deny-by-default 策略门（INV-2/M17/INV-4）+ T-022 INV-3（LeasedBinanceVenue 构造不持 key、真 key 只在门放行后 S4 物化、has_key 不 fetch、既有 venue 零改动 additive）。**诚实限界**：TCB 天花板（本地门=防篡改证据非防篡改，唯一硬墙在交易所侧——工程设计极限,不会再改）。**诚实残余**：非 relay live 路径未逐一接线（→ 收口 T-025）。
7. 现有**测试基线绿**（数目以实跑 `pytest` 为准,别据此判断）；新增代码须不破坏它 + 自带对抗测试（种已知 bug 门必抓）。

## 待决策岔路（等用户拍板）
> 卡在用户经济/产品判断上的开口——**点名**,别让人去翻任务卡 Open Questions。
- **前端整套台 epic（cfb0fea9）已实装完成**：24 子卡全 done（地基4+台前端6+Agent4+后端接真7+教学/桌面2），最终全量验证绿（后端 1231 / 前端 241 / tsc / build）；commit·合并 main 待用户授权（不擅自 commit）。残余：部分 mock 未接真(P1)/T-042 桌面待工具链/pre-existing bug spawn task。
- 簇A（T-023/024/025）已 2026-06-19 用户过目通过 + 落档完成；下一波 1A 价值密度混合（C 组合三角 + D 双时态地基 → B 因子轨 → E 信任层 / F 可上线 交织）若遇 `decisions/` 未覆盖新岔路再点名。
- **导航收口 + killswitch 加固（2026-06-22「a+b / 都做 / 升级」已做完）**：前端三 tab 合一为 Workshop + 总览台 + 旧页搬台/退役（D-NAV-UNIFY）；后端急停/紧急平仓 IP 改服务端派生防伪造 + 二次鉴权升级为服务端真校验密码(PBKDF2)/TOTP、废自证 bool（D-KILLSWITCH-IP）。验证全绿：tsc 0 / 前端 241 / 后端全量 1240 passed（含 IP 防伪造 + 错密码 + 自证 bool 失效 3 条回归）/ 6 台浏览器实证 + 零 console 报错。**commit·合并 main 待用户授权（未擅自 commit）**。
- **前端交互审查 + 文案去 AI 包装（2026-06-22 已 push origin/fullstack）**：11+ 交互 bug 修复（死循环/真钱页假绿灯/OOS 泄露补 train_fraction/因子门/revert/IME/2FA/顶栏/登录next/崩溃守卫）+ 全前端去 AI hype 文案（D-FE-REVIEW）；gitignore graphify-out/data 产物（D-GITIGNORE-ARTIFACTS）。对抗验证 10 claim 后**剩 2 条待拍**：agent-live-mock（LIVE 批准门重放 mock，违 LIVE 不假绿灯）、jobsdeck selJob 卡 mock id；其余误报/死代码/mock-later 不动。tsc0/前端241/凭据扫描0。
- **交付门垂直切片整波收官（2026-06-23，决策 D-DELIVERY-SLICE）**：DS-2~6 + e2e 全 done。6 worker 并行各出 PR（DS-2 前端 #4 / DS-3 裁决 #2 / DS-4 paper #5 / DS-5 §3 #3 / DS-6 装机 #1 / binance bug W6），leader 整合进 delivery-slice（解 AgentWorkbenchPage/PaperDeskPage 冲突 + §3 复审 relabel paper source）。**陌生人 chat→backtest→裁决→paper 全链真**（e2e 终验 3 测：真 goal_id→真 run_id→真 PBO/DSR/Bootstrap→paper bars_fed>0 真 equity；空壳/A股 live 红线守住）。全量后端 **1292 passed**、前端 **267 测 + tsc/build 绿**、validate PASS。子系统：M15 前端「部分 mock」→ ✅ 陌生人真路径接真（默认 liveMode/真裁决卡/真 paper 净值/§3 无假绿）；M9 paper「空壳」→ ✅ 真 provider 产净值（治理门不破）。**残余（非假绿、明确边界）**：真样本回放 paper provider（64717fe6·现确定性合成模拟诚实标 deterministic_sim_walk）/ testnet 可选喂（a367bfc8·「都做」backlog）/ A股 token-gated（用户自配 TUSHARE_TOKEN）/ 真 LLM 用 Hermes（文档已给）。**land main 进行中（用户授权）**。
- **交付门垂直切片 DS-1+DS-2核 done（2026-06-22，决策 D-DELIVERY-SLICE / Fork3=A，worktree `delivery-slice`，已 commit+push origin `6726c4f`；land main 待授权）**：DS-2 后端核（`strategy_goal.create` 校验落库产真 goal_id，闭合 chat→backtest 后端）随 DS-1 同 commit；DS-2 前端（liveMode/Hermes 预设）待续。DS-1——agent 对话回测（`business_tools._backtest_run` 无 run_id 分支）从 RunStore 占位改 `_synth_and_promote`——合成最小动量策略（新 `strategy_synth.py`，per-market 模板 + LLM seam）→ `ide.sandbox.run_user_strategy` 读真捆样本（新 `sample_data.py` 复用 vision 原语并发拉 BTC 516 真点落 `data/samples/`）→ `ide.promote.promote_ide_run` 落 RUN_ROOT + 三角 gate → **真 run_id**，被 `run_verdict.project_verdict/project_overfit` 真消费。**全量 1270 passed / 13 skipped**（基线 1263 + 7 新，0 破坏）+ 1 变异（伪造 equity_curve→break_engine 转红）。真回测真数：sharpe 1.18/收益 81%/DSR 0.956/verdict=concern（不假绿灯）。**消灭两套并行 run 注册表**（Fork3=A 统一 RUN_ROOT）。**诚实残余**：① 沪深300 真样本需 TUSHARE_TOKEN（绝不伪造，`bundle_hs300_daily` 一命令补，码路已测）② BTC 516/730 点（Vision 免费日 K 空洞）③ 真 LLM 注入=DS-2 ④ 发现 binance_vision_pull reload-merge pre-existing bug（绕开未碰，宜 mint 卡修）。**接缝**：DS-3/DS-4 可直接消费 run_id。已 commit+push origin `6726c4f`；land main 待授权。
- **下一波 1A「把每 run 可信做实」5 卡全 done（2026-06-22，决策 D-WAVE1A，worktree `wave-1a`、未 commit）**：S R18 stacking 控制项两面化 / D R28 全双时态 Stage①②（写层 owns first-seen + 读层 as_of_known 重述点查 + resolver 双轴）/ C 组合三角 full-fat（A2 override R2 放行语义 + 验收语义重写 + ADV2 反作弊 config_hash）/ 组合消费者（agent portfolio.gate）/ M 监控尾部闭环（lifecycle 权威 A1 自动退役 + 单一 PROV + croniter 硬化）。**全量 1240→1263 passed（+23 全绿）+ 12 变异验证 + validate PASS**。**子系统进展**：M7-M8 组合层「⬜ 未上多证据三角」→ ✅ gate 接活；M3/M8 数据层「全库双时态未做」→ ✅ Stage①② 机制全库；M11 监控尾部「漂移不驱动动作」→ ✅ 闭环。**残余处置（诚实闭：不强建投机桩）**：生产编排两残余依赖 wave 外上游管道（grep 实证 `FACTOR_LIFECYCLE.record_observation` 生产零调用→直接接 Scheduler 会空转），**已 mint 后续卡**：`ba59fb7b`（组合 promote production 端点 record=True 真记 honest-N）+ `de764e1c`（监控生产调度 + 因子观测记录管道）。**非卡的诚实边界**（用户档/下游采纳，不是待办）：v2 connectors known_at（取舍2=A 用户选机制全库）/ A2 反假绿灯护栏（用户可选档）/ 量化各模块传 as_of_known（下游按需采纳）。**commit·合并 main 待用户授权**。CEO flag：下一波宜转**交付门垂直切片**（陌生人 chat→backtest→裁决→paper），非直入 B 因子轨（连续两波向内、零移动 §9 交付总闸）。
- **Mathematical Spine 一致性门核心 done（2026-06-25，决策 D-MATH-SPINE，worktree `auto/math-spine`，分支自 `fix-u2-synth` HEAD）**：头号 gap #3 命门接活——`lineage/spine.py`（4 数据模型 §6 字段全含）+ `lineage/spine_gate.py`（`evaluate_promotion` 升级健全谓词门，8 子句逐条对 §6/§8 一条「→ 拒」）+ `lineage/spine_ledger.py`（`SpineLedger` append-only、复用 `ledger._ChainStore`、无改小/伪造 API）+ 理论先行 finding `spine-consistency-gate/00`。**新对抗测试 28 passed + 全量后端 1324 passed / 13 deselected（未破基线）**。子系统：Mathematical Spine ⬜→🟡（门核心已建并验证，全链贯穿待续）。**残余（诚实边界）**：data→factor→…→monitor 全链每数学点接 binding 是后续切片；PIT 子句(7)只校验 data_contract 携 known_at/effective_at 键、未与 R28 双时态 resolver 真点查；门不证明 code 真实现了 definition（靠 ConsistencyCheck 内容 + Verifier/Critic）。**commit/push 自管（已授权），land main 待用户**。⚠️ **双 state.md 对齐 flag**：本分支基于 committed HEAD 的旧版 state.md；主 checkout 有一份 GOAL-2026-06-25-rebaseline 的**未提交** state.md（74 未提交文件之一，含 9 条头号 gap 表），land 时需把本 Mathematical Spine 进展并入那份新版、避免双源漂移。
