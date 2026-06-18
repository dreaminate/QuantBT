# LOG · 执行台滚动日志

> 每个 session/Goal Loop 一条，最新在上。只记**做了什么 + 结果 + 下一步**，详情进 `tasks/done/<id>/`。

<!-- 格式·防跑偏 | 追加型：最新追加到本注释下方第一位。每条照此：
## <日期> · <标题>
- 建/改了什么 + 命门  - 验收：<对抗测试 + 变异 + 全量数字>  - 下一步：<…> -->

## 2026-06-19 · 装回 dev-os：保内容 + 升结构（融合）

- 从可复用 dev-os 骨架融合回 QuantBT：**保**全部内容（GOAL/DECISIONS R1–R29/ISSUES/TRACE/研究 archive+findings/12 张 done 卡/wave-A 卡），**升**结构件。
- **新增**：根 `CLAUDE.md`（新 Claude Code 自动入口）· `dev/RULES.project.md`（项目红线，从旧混合 RULES.md 抽出）· `scripts/build_ledger.py`（全含量账本）· `research/findings/_TEMPLATE.md`。
- **替换 OS 自带件**：`RULES.md`（转 OS 通用层 + 审计纪律）· `README.md`（OS 规约）· `validate_dev.py`（配置化 PROJECT_ANCHORS=lineage/ids + STALE_PREFIXES + 孤儿检查）· TASK/ideas/active 模板（含格式·防跑偏注释）。
- **升约定**：BOARD 转活跃版（删 done 行，全档走 build_ledger）· wave-A 卡 `状态` pending_review→todo（正交模型）· 内容台账加 in-file 格式注释 · 删 4 个旧 codex 模板。
- 备份：git tag `dev-pre-devos-merge`(f598cbd) + tarball。
- **下一步**：用户过目融合 → 点头 commit/push；收口 wave-A 仍等 2 岔路。

---

## 2026-06-18 · 补 dev OS 两个工位（创新/在研 + 问题登记册）

- 用户审视 dev OS 后拍板补两缺口：① 研究台加 `research/ideas/`(架构RFC/论文笔记·探索自由) + `research/active/<topic>/`(在研线程，镜像 tasks/active)，生命周期 **ideas→active→findings→任务**（各带 README + `_TEMPLATE.md`）；② 加 `dev/ISSUES.md` **跨任务问题/风险登记册**（卡 done 时未决 Open Q / 跨部件风险 / 诚实残余不掉地）。
- ISSUES 种 7 条真实项：I-001 TCB 残余[accepted] · I-002 对齐闸空转[open，用户处理中] · I-003 reconcile 下游未定 · I-004 node_id 跨部件 · I-005 OOS 切片 · I-006 Sentry 假死[resolving] · I-007 急停控件[→T-025]。
- `validate_dev.py` 升级自检新工位（REQUIRED+ISSUES.md / 目录+research/{active,ideas,findings} / LIVE_DOCS+ISSUES.md）；README + INDEX 同步生命周期。
- **下一步**：用户审 12 张 done 卡（review_status 0→1，I-002）；簇A 三张卡（T-023/24/25）+ 2 岔路待点头。

---


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

## 2026-06-17 · 审计 dev/ + 修复边界与 harness 卫生

- **审计**：迁移字节级完整（34/34 git-删除文件全等落点）；无 runtime 读取指向被移走文件（功能安全）；dev→docs 方向分得干净。
- **发现并修复**：
  1. v2/v3 plans 是被项目代码引用的**项目设计文档**，被误卷进 `dev/research/archive/plans/` → 归位 `docs/plans/`（3 处 field_catalog 注释引用零改动重新生效）；`agent-os-technical-architecture`（超期研究、不同来源）留 dev。
  2. 旧 codex 任务残留 `TASK-0001/` + `index.md` → 移 `tasks/_archive/`。
  3. 补 `done/T-012/`（BOARD 标 done 却缺落档）。
  4. 建本 `LOG.md`（README 描述过但从未创建）。
  5. 写 `dev/scripts/validate_dev.py` —— harness 从「纯手工纪律」升级为**可自检**（BOARD↔done 一致 / 四台文件齐全 / 无迁移前悬空路径）。
- **下一步**：T-013 一本账（SQLite WAL + JSONL，honest-N + memoize）。

## 2026-06-16 · 建脊柱第 0 层地基 + 蒸馏 GOAL

- T-012 `lineage/ids.py` 单一身份源 ✅（8 对抗测试绿）。
- T-001 蒸馏 `dev/GOAL.md` 完整最终形态 ✅（两层相乘：功能平台 × 治理）。
- 重构 docs/ → dev/ 四台开发 OS（只搬开发那一套；glossary/model_cards 留 docs/ 因 app 运行时读）。
- **下一步**：T-013 一本账。
