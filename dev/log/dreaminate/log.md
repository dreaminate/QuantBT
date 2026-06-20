# LOG · 执行台滚动日志

> 每个 session/Goal Loop 一条，最新在上。只记**做了什么 + 结果 + 下一步**，详情进 `tasks/done/<id>/`。

<!-- 格式·防跑偏 | 追加型：最新追加到本注释下方第一位。每条照此：
## <日期> · <标题>
- 建/改了什么 + 命门  - 验收：<对抗测试 + 变异 + 全量数字>  - 下一步：<…> -->

## 2026-06-20 · 二轮 UX/agent 能力收口规划 · 立 10 卡 + 4 决策（回测全流程审计驱动）

- **审计**：ultracode workflow（6 agent）审回测全流程合理性 / 机构级严谨 vs 过严摩擦 / Agent OS 角色 —— 结论：动钱侧治理脊柱真扎实（种坏门必抓），但 agent「干活能力」重门已建、轻活未接（主对话入口 RAG-only、`backtest.run` 未注册）；GOAL §7 M10「待接进 run 闸门」是陈旧文档（T-015 已接进）。
- **立卡（leader 分配自己）**：T-026 前端派发 R11 审计 · T-027 对话入口+无副作用工具+权限三态 · T-028 防绿灯错觉（按模式分层呈现）· T-029 入口×门覆盖矩阵 · T-030 单人 self-approve（真钱硬双人）· T-031 SLA/杠杆可配 · T-032 GOAL 对齐+文案 · T-033 诚实残余核验 · T-034 实盘因子血统门 · T-035 agent 窗口 epic。
- **4 决策（用户逐项拍板）**：D-PERM（权限三态 ⟂ 治理轴 + R25 呈现分层 + 默认止于模拟盘）· D-SELFAPPROVE（单人非真钱自批 / 真钱硬双人）· D-PROVENANCE（实盘因子血统门=警告+知情确认）· D-LEVERAGE（杠杆不设硬上限 + 真钱审批超时永远 default_reject）。
- **验收**：`validate_dev.py` PASS（DAG 25 卡无环无悬空、生成视图新鲜）；9 卡 review=1 + 待拍=0 ready，T-035 epic review=0 待细化（3 个 [需拍板]）。
- **下一步**：可先开 T-026（T-027 前置）/ T-029 / T-033（零依赖 ready）；agent 窗口设计图(权限三态映射 widget)已出。未提交（用户明说才 commit）。

## 2026-06-19 · 收口第一波 · 簇A 脊柱收尾全完成（T-023/024/025）

- **闸门**：三卡 review_status 0→1（用户过目通过；AskUserQuestion 工具丢答+「继续」→ 采纳推荐项「三卡全过开跑」，同 D-T021 先例，已在响应中声明该解读）。待拍早已清零（D-T024/T025 系列）。
- **T-023 内核接执行路径**：`run_dag(executor=...)` 切内核（executor=None 向后兼容，既有 7 测试零改）；`jobs.py` kernel_dag job（`InMemoryJobStore(kernel_root)` 共享 ArtifactStore+EffectLedger，retry=同图重跑=checkpoint 恢复+is_consumed 去重**绝不重发单**，SSE 加 halted/checkpoint，replay 模式边界 HALT）；agent **复用 T-016 RecordingLLMClient**（单一源不另造 store）；main.py JOB_STORE 携 kernel_root 生产可达。14 接线对抗测试。
- **T-024 假设卡接 Run**：`Run.layer/hypothesis_card_id` 可空字段（旧行兼容）+ `HYPOTHESIS_STORE` + 6 端点 + promote_model 闸门（confirmatory 过 gate / 非 confirmatory 走真钱拒绝绝不自动晋级 / 无 card_id 不挡 / exploratory P2 放行）+ **D-T024-FALS**（freeze 低可证伪 = 硬透明 + 软决定 human_reviewed override 留痕进卡，启发式绝不自动硬挡；结构空机制/验证官 blocked 仍硬拒）。16 对抗测试，措辞黑名单 0 hit。
- **T-025 真钱审计+急停+GenericVenue**：审计不变量测试（place_order 调用点 ⊆ 门后路径 + 探针自检）；kill_switch 补 IP+密码鉴权；emergency_close_all 空壳→真调 KILL_SWITCH；GenericVenue 接活（deny_by_default 白名单 + `guarded_generic_venue` OrderGuard 工厂）；relay 向后兼容真钱陷阱闭合（enforce_gate=False+CRYPTO_LIVE→fail-closed）。15 对抗测试。
- **5-lens 对抗复核（ultracode workflow，8 agent）3 真发现全修**：**1H** 急停含 venue 平仓失败仍硬编码 ok:True+审计 result="ok"（真钱面假绿灯）→ `_killswitch_status` 据 results 派生诚实状态（ok/partial/failed）+ 失败透传审计；**1M** retry_job 丢 spec["mode"]→replay job 降级 run 触发真下单 → 透传 mode；**1L** 同 1H 源。各补对抗测试。
- **验收**：全量 **1046 passed / 13 skipped**（基线 1001 未破，+45 新测试）。`validate_dev.py` PASS（41✅/0❌）。三卡落档 done/T-023..025、BOARD 删行、STATE 刷新。
- **诚实残余**（非阻断，入下一波/后续）：T-023 reconcile 对账闭环 + kernel_dag 生产 producer；T-024 端到端集成（内核/验证官/regime 真落地后）。
- **下一步**：**下一波 = 1A 价值密度混合** → C「M7–M8 组合上多证据三角」+ D「数据双时态地基」（把*每 run 可信*做实）。未提交（用户明说才 commit）。

## 2026-06-18 · T-022 安全门 INV-3：venue 只认 lease 签名（relay key 只在门后物化）

- **建** `app/execution/leased_binance.py` `LeasedBinanceVenue`（构造不持 key；place_order(order,lease) 从 lease 现造 creds 签名；无 lease→fail-closed；get_mark_price keyless 公共端点保 T-021 fix B）+ `KeyBroker.has_key`（list_names 不 fetch）+ main.py ORDER_BROKER + 工厂改 lease-only（不 eager fetch）+ relayer 注入 broker。既有 binance venue/client 零改动（additive）。
- **真 key 只在 OrderGuard S4（门放行后）经 broker.issue 物化恰一次；门拒则永不物化**（INV-3 命门）。
- **验收**：10 对抗测试（INV-3 计时为头条）+ 4 变异全杀 + ultracode 5-lens 复核 **15 raw→1 真发现（LOW，stale 注释）修**，0 HIGH/0 MEDIUM。全量 **1000 passed / 13 skipped**。
- **诚实残余**：TCB 天花板（broker+venue 同属主机内存，lease 只收窄暴露窗口非干净修复；唯一硬墙在交易所侧）；非 relay live 路径未逐一接线（复核未确认真实漏洞）。
- **安全门生产接线全链闭合**（T-018 gate→T-019 审批门→T-020 验证官→T-021 relay 闸门→T-022 INV-3）。**BOARD 无 todo**。

## 2026-06-18 · T-021 安全门生产接线（relay 必经 OrderGuard，INV-2/M17 生产强制）

- **建** `app/copy_trade/gate_binding.py`（默认门模板 Follower→PolicyGate）+ executor `_place`（enforce_gate 时所有 follower 下单必经 OrderGuard）+ main.py 生产 relayer enforce_gate=True + RELAY_NONCE_LEDGER。此前 relay 完全绕过策略门 → 现 INV-2/M17/INV-4 生产强制。
- **产品决策** D-T021-1/2/3（whitelist={signal.symbol} / notional=既有 per_order_max_usdt / 真钱 fail-closed）记入 DECISIONS（AskUserQuestion 工具错误丢答 + 用户「继续」→ 采纳推荐保守档，可改）。
- **验收**：16 对抗测试（M17 命门 relay 截断+直连注入双夹为头条）+ 8 变异全杀 + ultracode 5-lens 复核 **16 raw→4 真发现全修**（皆「挡死正常交易」侧：现货 leverage_unspecified 全拒 → 现货显式 1x；市价 notional_unverifiable 全拒 → venue 侧可信 mark 核名义额、不读自报价、不污染 order.price）。全量 **990 passed / 13 skipped**。
- **诚实残余 → T-022**：INV-3 lease-唯一-key 通道（venue 重构成只认 JIT lease、移除 self-fetch、生产注入 broker；不接 broker 避免 no-op lease 仪式）。
- **下一步：T-022**（INV-3 venue 重构）。

## 2026-06-18 · T-020 验证官（部件12，异模型一致性，产 verdict_id）——脊柱最后一块

- **建** `app/verification/`（schema/verifier/store）：生成≠验证(R7) 真分离器。异模型/异种子/异切片对生成方自报值挑战式重算 → 产 content-addressed `verdict_id`，喂 T-017 假设卡 + T-019 审批门。
- 异模型不一致即 BLOCK(不取均值)；未验证≠pass；独立性【度量】非假定(同模型→concern，06 §7-4)；措辞禁组织独立/independent/可信/安全/保证/可复现。
- **生产接线**：main.py 注入 VERIFIER/VERDICT_STORE + 端点 POST/GET /api/verification/verdicts；审批门 verdict_lookup=record_for → 闭合 T-019 [集成必补] 缝。
- **验收**：31 对抗测试 + 10 变异全杀 + ultracode 5-lens 复核 **18 raw→5 真发现全修**（HIGH：verdict_id 未绑被审工件可张冠李戴/同模型靠大小写伪装成异模型/store 读路径无完整性校验放行篡改 blocked；MEDIUM：NaN 非对称漏判 + NFC/NFD）。全量 **974 passed / 13 skipped**。
- **脊柱收口**：8 块全建并验证（T-018 生产接线→T-021）。**下一步：T-021**（OrderGuard 接进 venue/relay，生产强制 INV-2/3/M17）。

## 2026-06-18 · T-019 审批门 + promote 状态机（脊柱第 3 层，含生产接线）

- **建** `app/approval/`（schema/channels/store/gate/hard_limits）：promote 3 行裸翻转 → 带审批门状态机。三要件（独立验证 + approver≠creator + 多证据三角重算）缺即拒+缺口清单；探索零门(P2)；honest-N 实读 T-013 一本账不可改小；门后硬限额 fail-closed（审批≠授权）；幂等意图先落盘防崩溃双发；SLA 截止+分流。
- **生产接线**（与 T-018 不同，本次已接）：main.py 注入 GATE_SERVICE、promote_model 端点改（422+缺口清单）、新增 approve/reject/get gate 端点；apply_stage 公开方法禁直翻 production（防侧门）+ approve_promotion 真翻 stage。
- **验收**：22 对抗测试 + 5 变异全杀 + ultracode 5-lens 复核 **17 真发现全修**（HIGH：门从未接进 live promote/apply_stage 侧门/崩溃双发/approver 大小写绕过/SLA 提前放行/硬限额绑错维度）。全量 **943 passed / 13 skipped**。
- **下一步**：T-020 验证官（产 verdict_id 喂 T-017/T-019）——脊柱最后一块。

## 2026-06-18 · T-018 安全门 gate 组件（脊柱第 3 层，生产接线 deferred）

- **建** `app/security/gate/`（policy deny-by-default / nonce 防重放 / broker JIT-key / enforcer OrderGuard S0-S7 / ingest Rule-of-Two）。注入/越权单走不到 S4 → key 永不取出。
- **验收**：23 对抗测试 + 7 变异全杀 + ultracode 5-lens 复核 **19 真发现**：12 在 gate 内硬化（cap-0=deny、名义额只信撮合价非自报、实盘强制 nonce+leverage、capability 绑门、attestation 不从 order.extra 取、提币 allow-list），**7 生产接线 deferred→T-021**（OrderGuard 未接进任何 venue/relay、KeyBroker 未实例化、lease 非唯一 key 通道）。全量 **926 passed**。
- **诚实**：gate 已建+硬化+单测验证，但 **INV-2/3/M17 在生产未强制**——不标绿（RULES §3）。需产品先定默认门模板/白名单来源/fail-closed 档（设计 §7）。
- **下一步**：T-019 审批门 + promote 状态机。

## 2026-06-18 · T-017 可证伪假设卡（脊柱第 2 层，P2 不挡探索）

- **建** `app/hypothesis/`（card/falsifiability/store/gate/lineage_hook）+ strategy_goal 三必填可空字段。可证伪性**真语义检测非字数门**；冻结=只读+content_hash+honest-N **实读 T-013 一本账**(card_freeze 计入)；探索层永不挡(P2)、过不了 gate。
- **验收**：29 对抗测试 + 变异全杀 + ultracode 5-lens 复核 **15 真发现全修**（HIGH：可证伪检测退化成中文-P&L 字词门，自指标/英文/领域词包装的循环判据全静默冻结；deviation 翻状态重开 hashed 字段；篡改读路径不检；secondary 可过闸；freeze 重绑污染 OOS）。全量 **903 passed / 13 skipped**。
- **下一步**：T-018 安全门 deny-by-default + 交易所侧硬墙。

## 2026-06-18 · T-016 LLM record/replay + 受控翻译层（脊柱第 2 层）

- **建** `app/agent/replay/` 包（fixture+HMAC / store / recording_client / translation / repro）。LLM 是触手、确定性脊柱是骨架；本部件是防伪/可回放硬接口。
- **命门**：replay 未命中 raise ReplayMiss、**绝不打真 API**（R11）；fixture HMAC 完整性（只签内容）；cache key 内容寻址（llmfx-，编码图中位置+上游+run_index）；受控翻译门挡越权杠杆（schema 合规但语义越界→human_confirm 不派发）。
- 接线：`AgentRuntime` 可选翻译门（非 ok 不派发）；`main.py` opt-in（`LLM_REPLAY_MODE`，默认 passthrough 行为不变）+ 每 turn 唯一 run_id + 武装翻译门。
- **验收**：30 对抗测试 + 变异全杀 + ultracode 5-lens 复核 **14 真发现全修**（HIGH：常量 run_id 撞键致 record 复用陈旧答案现场复现；翻译门字符串/列表/变体杠杆绕过；tombstone 改签名字段不重签锁死 fixture）。全量 **874 passed / 13 skipped**。
- **下一步**：T-017 假设卡（P2 不挡探索）。

## 2026-06-17 · T-015 多证据三角 gate（脊柱第 1 层 · 头号 gap 闭合）

- **建** `eval/overfit_gate.py`（三角裁决）+ `eval/n_eff.py`（收益相关聚类）+ `eval/gate_runner.py`（接 T-013 一本账 + 收益快照）；`eval/dsr.py`(+var_sr_hat, studentized 修正, 标准 skew/kurt)、`eval/bootstrap.py`(+block bootstrap) 升级；接线 `ide/promote.py`(opt-in) + `main.py`(LEDGER/RETURNS_STORE + risk_preview + honest_n 下钻端点)。
- **命门闭合**：M10 的 PBO/DSR/bootstrap 此前全仓零调用、`risk_summary._rule_dsr/_rule_pbo` 永远拿 None；现在 promote 跑三角 gate 注入 dsr/pbo → **守门器从死接活**。噪声→不绿、泄露→N_eff<<N、短样本→证据不足。
- **验收**：24 对抗测试 + 变异全杀 + ultracode 5-lens 对抗复核 **10 真发现全修**（HIGH：honest_n 兜底通缩——矩阵拼不出时通缩归零让泄露过闸；HIGH：噪声填充解锁 PBO；MEDIUM：DSR 量纲 hack）。全量 **844 passed / 13 skipped**（基线未破）。复核还揪出**测试剧场**：所有矩阵 N_eff.low==high 退化→low/high 互换变异全绿→补跨相关带严格非退化测试。
- **下一步**：T-016 LLM record/replay + 受控翻译层（spine 02）。

## 2026-06-17 · T-014 确定性内核（脊柱第 0 层第 3 块）

- **建** `dag/kernel.py` `DurableExecutor`（run/replay/fork/rollback）+ `effect_ledger.py`（泛化 copy_trade 幂等到单键，所有 effectful 节点同一道闸）+ `artifact_store.py`（内容寻址 durable）+ `engine.py` 升级（DAGTask `kind`/`effect_idempotency_key` + __post_init__ 强制约束 + `reused`/`halted` 状态）。复用 `ids.node_id` 单一身份源。
- **命门**：effectful（动钱）节点在 replay/fork/rollback **一律 HALT、绝不重发副作用**，发 reconcile 交对账；崩溃恢复经 EffectLedger 幂等不重发。
- **验收**：25 对抗测试（T-DET-1..22）+ **15 变异全杀** + ultracode 5-lens 复核 8 真发现全修 + **专项 money-safety 复审（8 探针）无 HIGH，边界全成立**（probe-7 key 确定性 / probe-8 硬杀 place→record 窗口 = 已诚实记录的不可消除残余）。全量 **821 passed / 13 skipped**（基线未破）。自揪并补 `busy_timeout`（跨连接锁错）+ 记账失败 CRITICAL+reconcile（probe-4）。
- **诚实 deferred**：`jobs.py` SSE 接线 + `agent_runtime.py` 节点化（与 T-016 重叠）未做。
- **下一步**：T-015 试验账本算法层（N_eff + 多证据三角 gate，接 M10 守门进 run 闸门=头号 gap）。

## 2026-06-17 · T-013 一本账 ledger（脊柱第 0 层第 2 块）

- **建** `app/backend/app/lineage/ledger.py`：honest-N + memoize **物理同源**一本账。双存储（SQLite WAL 快查询索引 O(log n) + JSONL 哈希链防篡改持久真相 + `ledger.hwm` 防末尾截断），复用 `ids.config_hash` 单一算法，读路径==被核验路径（删 payload_json 旁路）。
- **关键设计纠正**（对抗复核揪出）：计数键从 `config_hash` 单键 → **复合键 `(config_hash, strategy_goal_ref)`**——否则第二个主题的同 config 试验撞行被静默吞掉（honest-N 洗白，HIGH）。
- **验收**：25 对抗测试绿 + **13 变异全杀**（种坏门必抓）+ ultracode 5-lens 对抗复核确认 **11 真发现全修** + 二轮 second-look 无缺陷。全量 **796 passed / 13 skipped**（763 基线未破）。
- **下一步**：**T-014 确定性内核**（node 身份/durable/effectful 不可幂等边界，依赖 ids+ledger 已就绪）；其后 T-015 接 M10 守门进 run 闸门（头号 gap）。
