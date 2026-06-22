# LOG · 执行台滚动日志

> 每个 session/Goal Loop 一条，最新在上。只记**做了什么 + 结果 + 下一步**，详情进 `tasks/done/<id>/`。

<!-- 格式·防跑偏 | 追加型：最新追加到本注释下方第一位。每条照此：
## <日期> · <标题>
- 建/改了什么 + 命门  - 验收：<对抗测试 + 变异 + 全量数字>  - 下一步：<…> -->

## 2026-06-23 · 交付门垂直切片整波收官（DS-2~6 + e2e）· 6 worker 并行 + leader 整合 land main

- **审计收卡**：55 done 卡全诚实、0 假绿灯、validate PASS。微调：ba59fb7b/de764e1c pool→自领 active；defe660c Scope 澄清前后端；46f1cb3c/d0e5d208 残余加承接链路注。
- **6 并行 worker（worktree·各 PR→delivery-slice）**：DS-2 前端(PR#4·默认接真+Hermes 预设页+stream run_id) / DS-3 裁决(PR#2·liveRunId 贯穿+Bootstrap 第三腿) / DS-4 paper(PR#5·register_run 注 provider+POST 端点+真净值·**治理 §5 全不破**) / DS-5 §3假绿灯修(PR#3·乐观假成功改诚实失败) / DS-6 装机(PR#1·跨平台 launcher+mkdir+A股 token 引导) / binance bug(W6·agent API 死 leader 接手 land ac72b81)。每 worker code-review skill 抓真 bug 自修。
- **leader 整合**：5 PR merge 进 delivery-slice，解 AgentWorkbenchPage/PaperDeskPage 冲突（barsFed 去重 + W4 handoff 测试适配默认接真 + LIVE 标取 §3 严格版）。**§3 复审发现**：DS-4 source 标签 `bundled_sample_replay` 过度声称真样本回放（实为合成游走）→relabel `deterministic_sim_walk` 诚实化；mint 2 follow-up（64717fe6 真样本回放 / a367bfc8 testnet 可选，对应「都做」）。
- **e2e 终验**：新 test_delivery_slice_e2e（3 测）陌生人 chat→backtest→裁决→paper 全链真产物一条龙（真 goal_id→真 run_id 落 RUN_ROOT 真净值→真 PBO/DSR/Bootstrap concern 不假绿→paper bars_fed>0 真 equity）；空壳 bars_fed=0 不假绿；A股 live 恒拒。
- **验收**：**全量后端 1292 passed / 13 skipped**（基线 1275→1292，+17 全绿）+ 前端 **267 测 / 23 文件 + tsc/build 绿** + validate_dev PASS。陌生人真路径全程真数据、§3 无假绿灯、治理门（A股恒拒 live/INV-5/止模拟盘/绕门审计）不破。
- **下一步**：land delivery-slice→main（用户已授权）。残余：真样本回放/testnet（2 follow-up）、A股 token-gated（用户自配）、真 LLM 注入用 Hermes（文档已给）。

## 2026-06-22 · DS-2 后端核 done（造站接真 · blocker #2 · 卡未整完）

- **建/改**：`strategy_goal_store.py`（新·`StrategyGoalStore` 落库 + `create_from_args`：结构化 args 补 cost_model/evaluation_window 默认校验 / 自然语言走既有 `StrategyGoalSlotFiller`→ 真 goal_id 内容寻址幂等）+ `main.py`（`strategy_goal.create` 回显 lambda→真 handler 校验落库产 goal_id）。**陌生人对话→真 goal_id→DS-1 真回测** 后端入口闭合。
- **命门（5 测）**：结构化产真 goal_id + A股 leverage=1.0 治理不变量不破 / 自然语言 slot-fill 产 goal_id / §3 缺 asset_class 无 NL→needs_slots 不伪造 / 内容寻址幂等 / goal_id 真喂 DS-1 backtest 产真 run（链路闭合）。
- **验收**：DS-2 5 测全绿；agent/strategy_goal/a4 基线 38 passed；main import 干净。
- **DS-2 残余（卡未 done）**：前端 ① AgentWorkbenchPage 默认 liveMode=true + 演示挂 MockBadge ② LLMSettingsPage（Hermes 预设：复用已有 POST /api/llm/configure custom provider + 文档）③ DevLocalLLM slot-filling 追问润色（SlotFiller 已建、endpoint 已在）。均前端/文档活。
- **下一步**：DS-2 前端 + DS-3（裁决 liveRunId 贯穿，依赖 DS-2 真 run_id 到前端）/DS-4（paper 治理敏感）；**已 commit+push origin `6726c4f`**；land main 待授权。

## 2026-06-22 · DS-1 run_id 脊梁 done（交付门垂直切片首卡 · D-DELIVERY-SLICE / Fork3=A）

- **建/改**：`agent/sample_data.py`（新·捆真行情样本，复用 binance_vision_pull 无状态原语并发拉 BTC 绕开其 reload-merge 预存 bug；TushareConnector 捆沪深300 seam）+ `agent/strategy_synth.py`（新·per-market 确定性动量模板，stdlib csv 读样本避开沙箱 socket 锁致 polars 读路径失败；LLM seam 废输出兜底防假绿灯）+ `agent/business_tools.py`（扩展·`_backtest_run` 无 run_id 分支 RunStore 占位→`_synth_and_promote`：合成→sandbox→promote_ide_run 落 RUN_ROOT+三角 gate→真 run_id；register 加注入 ledger/returns_store/data_root/llm_client 全默认）+ `main.py`（注入 LEDGER/RETURNS_STORE/DATA_ROOT，llm_client 留 DS-2）。**消灭两套并行 run 注册表**（runs.jsonl→统一 RUN_ROOT，Fork3=A）。
- **命门（7 测 + 1 变异）**：真 run 被 project_verdict/project_overfit 真消费（非 mock）/ 同 goal config_hash 稳 honest-N 不重刷 / 断引擎(沙箱无净值)诚实失败不伪造 / 缺样本诚实失败 / 合成确定性+无前视 / LLM seam 废输出兜底+合格采纳；变异（伪造 equity_curve 分支）→ break_engine 转红（守卫 load-bearing）。
- **验收**：DS-1 7 测全绿；**全量 1270 passed / 13 skipped**（基线 1263 完整 + 7 新，0 破坏，161s）。真回测真实数字：sharpe 1.18 / 总收益 81% / 回撤 -24% / DSR 0.956 / verdict=concern（无权威裁决→不假绿灯）。BTC 样本 516 真点（2022-2023）落 `data/samples/`。
- **诚实残余**：① 沪深300 真样本未捆（码路已建测，需 TUSHARE_TOKEN，绝不伪造 §3——`bundle_hs300_daily` 一条命令补）；② BTC 516/730 点（Vision 免费日 K 空洞，起步样本）；③ LLM 合成真注入是 DS-2；④ 发现 binance_vision_pull reload-merge pre-existing bug（已绕开未碰，建议 mint 卡修）。
- **下一步**：DS-3（裁决 run_id 贯穿）/DS-4（paper register）接缝已通；**已 commit+push origin `6726c4f`**；land main 待授权。

## 2026-06-22 · D-WAVE1A 整波完成（C + M + 消费者）· 5 卡全 done

- **C 组合三角 full-fat**（`46f1cb3c`）：新 `portfolio/gate.py`（`gate_portfolio` 复用单一源 `evaluate_overfit_gate`、`portfolio_net_returns`、ADV2 `portfolio_composition` 排序入 config_hash 不改 ids、Q3 `strictest_asset_class`）+ `overfit_gate._decide`/`run_overfit_gate` 加 `allow_pbo_absent_green`（A2 override R2，默认 False 单策略不变，A2-green 标 PBO N/A）+ 验收语义重写（「必抓」假命题→「不达 green，red 仅 strong_neg」）。
- **消费者**（`1e0e65b4`）：`agent/business_tools` 新 `portfolio.gate` 工具（agent 真能调组合 gate，side_effect=none），gate 不再悬空。
- **M 监控尾部闭环**（`d0e5d208`）：新 `monitor/closure.py`（`monitor_tick` 绩效/漂移→lifecycle 权威 A1→自动 WARNING/RETIRED+单一 PROV；漂移超阈结构化告警+降级动作真调用；范畴红线只接绩效/漂移不接 gate verdict）+ `Scheduler` croniter 硬化（strict 响亮失败）。
- **命门（C 7 测试 + M 5 测试 + 4 变异）**：C—A2 放行只在 DSR+CI 双正 / 过拟合 strong_neg→red 误绿兜底（变异禁 strong_neg 双红）/ 重排同 config_hash / 无 alpha 不达 green / agent 工具真跑；M—种应退役卡→RETIRED+单一 PROV（变异断 evaluate 红）/ 漂移动作真调用 / croniter strict 响亮失败 / 签名无 gate verdict。
- **验收**：**全量 1263 passed / 13 skipped**（基线 1240→1263，+23 测试全绿，121s）；validate_dev PASS（55 卡 DAG 无环、消费者 depends_on C 合法）。
- **整波诚实残余**：① 组合 promote production 端点（record=True 真记 honest-N）未接；② M 生产 weekly cron 调度起点 + store→lifecycle 派生同步未接；③ D：v2 connectors known_at 未填(取舍2=A)、keep_known_at_axis 多集双轴限界、量化各模块未传 as_of_known；④ A2 反假绿灯护栏=用户可选档默认未加。均 tracked、非假绿、非阻断。
- **下一步**：worktree `wave-1a`、**未 commit**（待用户授权 commit+land main）。CEO flag：下一波宜转交付门垂直切片（陌生人走通 chat→backtest→裁决→paper），非直入 B 因子轨。

## 2026-06-22 · D-WAVE1A · D(R28 全双时态 Stage①②) done

- **deep-opus spec 先行**（修正评审 CTV-4：真 provider=`tushare_quant1/tushare_provider.py`；写层财报 ann_date 在 unique_keys→不同 ann_date 重述保留，只有同 ann_date 脏重述 + 读层 `catalog.py:233` 无条件折叠丢 first-seen）。
- **实装（扩展不替换）**：写层 `tushare_provider` known_at first-seen + keep-first-on-known_at（同身份取最早=own+幂等，行情类走原 keep='last' 不变）；读层 `catalog.load_panel` 加 `as_of_known`（重述 as-of 点查）+ `keep_known_at_axis`（Stage② 双轴）+ `_STRUCTURAL` 收 known_at；`PanelResult` 加双时态字段；resolver 加 `as_of_known` 第二轴 + `as_of_bound` 升 public（单一源 catalog 复用）。默认路径逐字不变（守 `test_data_contract:139`）。
- **命门（8 测试 + 2 变异）**：写层 5（重述/脏重述守首披/幂等/不覆盖/行情不变）+ 读层断言3（as_of_known 点查 10.0↔10.5）+ resolver 双轴 + 单轴回归。变异：写层 keep='first'→'last' 红、读层忽略 as_of_known 红。
- **验收**：**全量 1251 passed / 13 skipped**（基线 1243+8 未破，实跑 133s）；validate_dev PASS。
- **诚实残余**：keep_known_at_axis 多数据集双轴 ill-defined（限界，仅单集干净）；v2 connectors known_at 暂不填（取舍2=A）；utc_now 兜底非确定性；量化各模块尚未传 as_of_known（参数就绪、按需接）。
- **下一步**：消费者卡（agent 组合→promote→gate）+ C full-fat（A2 放行语义 + 验收语义重写 + ADV2 config_hash 规范化）+ M。worktree wave-1a，**未 commit**。

## 2026-06-22 · D-WAVE1A 启动 + S(R18 stacking 控制项) done

- **评审**：合规多 voice（16 agents，graphify grounding + 对抗验证 CTV-1~6）审下一波 1A 4 卡 scope/排序；7 项逐一拍板落 DECISIONS `D-WAVE1A`：SEQ-CONSUMER=A(C full-fat+新增消费者卡)/C-Q1=A2(override R2、护栏可选)/C-Q2·Q3=A/D-AXIS=A(写层 owns)/D-NECESSITY=B(全 Stage①②)/M-AUTHORITY=A1(lifecycle 权威)。
- **S 卡 done** `87ad21fc`：R18 切两面（声明门 `LeakageDeclaration` ✅已建已验证 / stacking 实证 OOF=N/A until 实现）；新 `app/backend/tests/test_r18_stacking_control.py` 3 测试钉死两面 + 单一 CV 源 `purged_cv.py`。命门=种 stacking 对象 / 第二 CV 实现即红。纯 additive 守卫，不造 stacking、不动产品代码。
- **验收**：3 passed + **变异验证**（种 `class Stacking`+`meta_model`+第二 `purged_kfold/walk_forward` → 两扫描门精确红、删探针回绿，门必抓非纸门 RULES §2）；**全量 1243 passed / 13 skipped**（基线 1240+3 未破，实跑 154s）；validate_dev PASS。
- **下一步**：按 D-WAVE1A 排序进 **D**（R28 全双时态 Stage①②：写层 owns first-seen + 幂等 + `end_date×known_at` 双轴）→ 消费者卡 → C full-fat(A2+护栏) → M。worktree `wave-1a`，**未 commit**（待用户授权）。

## 2026-06-20 · T-035 epic 拆分（leader 领）+ 批次 commit

- **批次 commit** `e3a859a`（33 files +1191/-66）：T-026~T-034 实装 + 4 决策 + 4 gap pool 卡 + 51 新测试；署名 dreaminate 无 co-author，不含 graphify-out。
- **T-035 epic 拆为 4 子卡**（分配 dreaminate）：T-040 `82120b9c` 前端窗口核心 · T-041 `3d95e0f6` 弹窗+文案 · T-042 `bc21c7c1` Tauri 挂载 · T-043 `3bb62d7d` 无副作用工具接真引擎(P1)。epic 标 done（规划+拆分完成，实装由子卡承接）。
- **下一步**：4 子卡待 self-review + 实装（T-043 为北极星最后一公里：agent 真跑回测）。T-035 拆分这批未 commit。

## 2026-06-20 · T-033 完成 · 诚实残余核验（2 verified / 4 gap 升级 pool）

- **核验**（workflow 7 agent 逐项复证，无假绿灯）：✅ venue_lease(INV-3 lease-only 生产做实) · ✅ jsonl_tamper(hash chain 防篡改 25 tests) · 🟡 monitor_loop / portfolio_triangle / stacking_oof / pit_bitemporal 确为 gap。
- **verified 探针** `test_venue_lease_invariant.py` 2 passed（lease-only 签名 + fail-closed）。
- **gap 升级 pool**：d0e5d208 monitor闭环 · 46f1cb3c 组合三角 · 87ad21fc stacking-R18(N/A) · 3a8b2360 双时态-R28（诚实 tracked 进 DAG）。
- **下一步**：批次 T-027→T-034 实装完成；T-035 epic 占位待拆。未提交。

## 2026-06-20 · T-034 完成 · 实盘因子血统门（警告+知情确认）

- **核心**：新模块 `provenance.py` `gate_live_promotion`——未走完治理流程（假设卡→验证→审批）的因子上真钱线 → 列出 + 要求知情确认；已 ack → 放行留痕（硬透明+软决定，不死挡）；查询异常 fail-safe 按未过。
- **测试** `test_provenance_gate.py` 5 passed（未过必警告/知情放行/fail-safe/不误拦）。
- **残余（接线）**：status_lookup 接 lineage 谱系 + hypothesis/verification；上真钱线端点插门 + 前端弹窗（拆子卡）。
- **下一步**：T-033（诚实残余核验）。未提交。

## 2026-06-20 · T-030 完成 · 单人 self-approve 仅非真钱通道（真钱硬双人）

- **核心**：`gate.approve(self_approve, acknowledged, cooling_seconds)`——真钱场景（MONEY_ACTIONS）self-approve → SelfApproveForbidden；非真钱须二次确认 + 可冷却 + `self_approved=True` 诚实标注（不伪装双控）；未开 self_approve 仍 approver≠creator 硬拒。schema 加 self_approved 字段 + SelfApproveForbidden。
- **测试** `test_self_approve.py` 6 passed（真钱禁/缺确认拒/冷却拒/双人不误标）+ approval 回归 23。
- **残余（端点接线）**：approve 端点经 MODEL_REGISTRY 透传 self_approve + 客户端冷却 UI（拆子卡）。
- **下一步**：T-034（实盘因子血统门）。未提交。

## 2026-06-20 · T-032 完成 · GOAL 对齐 + RULES.project 禁裸 place_order 红线

- **GOAL.md:67** M10「待接进 run 闸门」→「已接进(T-015)」（授权对齐 state）。
- **RULES.project** 加红线「下单唯一入口 / 新增端点·venue 禁裸调 place_order」（承接 T-026/T-029）。
- **测试** `test_doc_alignment.py` 2 passed（防文档再漂）。
- **残余（前端文案）**：409 flag 引导句 / market_mode / paper 文案随前端批做；后端逻辑不动。
- **下一步**：T-030（单人 self-approve）。未提交。

## 2026-06-20 · T-029 完成 · 入口×门覆盖矩阵（不可绕过结构化）

- **核心**：`test_entrypoint_gate_coverage.py` AST 审计 main.py 全部 route，高危端点（/signals //promote //approve //kill_switch //emergency //subscribe //redeem //mainnet //place_order //upgrade）断言体内必带门/鉴权标志。全部通过 + 探针抓无门端点。与 T-025 place_order 扫描互补（端点层 vs venue 层）。
- **测试** 2 passed。修过程：main.py 有 BOM → read_text 用 utf-8-sig。
- **残余（转 T-032）**：禁裸 place_order 钉 RULES.project 红线（文档）。
- **下一步**：T-030（单人 self-approve）。未提交。

## 2026-06-20 · T-031 完成 · 审批 SLA/杠杆可配 + 真钱超时铁律

- **改**：`channels.py` `sla_seconds(overrides)` / `timeout_default(overrides)`（动钱类 default_reject 不可 override 放行）；`main._agent_leverage_cap()` 从 env 读、无硬上限（D-LEVERAGE）。
- **测试** `test_approval_sla_leverage_config.py` 6 passed（真钱铁律种坏门 + SLA 可配 + 杠杆无硬上限 + 非法回退）+ approval 回归 22。
- **残余（前端）**：客户端档位设置 UI；后端 overrides/env 已就绪。
- **下一步**：T-029（入口×门覆盖矩阵 + venue OrderGuard.wrap CI 静态检查）。未提交。

## 2026-06-20 · T-028 完成 · 工具真实状态诚实暴露（防绿灯错觉）

- **核心**：`/api/agent/tools` 加 `tool_status`——TOOL_SCHEMA 18 工具逐一标 live/stub/unwired + side_effect。揭穿能力名不副实：8 接通（含 factor.run_ic=stub），10 个（backtest.run/eval.pbo/model.train/report.generate…）声明未接=unwired。
- **测试** `test_agent_tool_status.py` 5 passed（unwired/stub/live + 全标 live 假绿探针）；全量 **1075 passed / 13 skipped**（基线 1070 未破，+5）。
- **残余（前端 UI）**：red/yellow 按权限模式一等呈现分层属 RunDetailPage 渲染（冻结只能加显示），随 T-035 窗口做；后端裁决已由 ide_promote gate_verdict 暴露。
- **下一步**：T-029（入口×门覆盖矩阵 + venue OrderGuard.wrap CI 静态检查）。未提交。

## 2026-06-20 · T-027 完成 · agent 权限三态 + 权限轴⟂治理轴 + chat 接 AgentRuntime

- **机制**：`agent_runtime.py` 加 `permission_gate(mode, side_effect)` + `register_tool(side_effect)` + dispatch 前权限门。none=ask 确认/auto·bypass 自动；external=仅 bypass 自动；**realmoney=任何模式（含 bypass）都挂起**（权限轴绝不跳治理门）。
- **chat 入口接 AgentRuntime**：`chat_send_message` 从裸 client.chat → `_agent_runtime(permission_mode, system_prompt=RAG)`，支持工具派发 + permission_mode；RAG/metadata 保留、round-trip 回归绿。
- **测试** `test_agent_permission_tristate.py` 16 passed（矩阵 9 + realmoney 三模式全挂起探针 + 分模式）；全量 **1070 passed / 13 skipped**（基线 1054 未破，+16）。
- **残余（拆子卡）**：无副作用业务工具接真引擎让 agent「一句话真跑回测」（backtest.run/eval.pbo/report.generate 真 handler）—— 机制已做实，接真 handler 是独立功能。
- **下一步**：T-028（防绿灯错觉呈现，依赖 T-027 权限模式已就绪）。未提交。

## 2026-06-20 · T-026 完成 · R11 前端派发审计（裁决 no_bypass）

- **审计**（三角调查 workflow）：治理门钉在端点/执行层（OrderGuard 会话外硬墙「agent 注入成功也下不了单」），前端 agent 页 display-only（tool_call 仅渲染 chip），前端绕 agent 直调端点也越不过门 → R11 前端侧无缺口，非 §5、未停工。
- **测试** `tests/test_r11_frontend_dispatch_audit.py` 8 passed：白名单守门 / dispatch 不执行未注册高危 / 翻译门拦非 ok / 前端不直 fetch 执行端点，各配探针。过程修正：黑名单 `/api/security/` 过宽误报 reloadSecrets（手动按钮）→ 收窄执行端点。
- **验收**：全量 **1054 passed / 13 skipped**（基线 1046 未破，+8）。
- **转交**：copy_trade service 内门逐一压测 + main.py:282 注释钉 RULES.project 红线 → T-029；enforcer lease 退化 → T-033。
- **下一步**：T-026 落档 done；可接 T-027（前置已满足）。未提交（用户明说才 commit）。

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

## 2026-06-21 · 整套台前端实装 epic（cfb0fea9）开卡

- **背景**：用户提供 Claude Design handoff bundle(quantbt-claude)，要把整套 DC 原型（策略台/因子台/Model台/模拟台/回测详情+裁决卡/Agent 窗口）pixel-perfect 还原成 React。三板拍板：先开卡自分配 leader / 分期开齐全套卡 P0→完整 / 整套台全做。
- **开卡**：mint epic cfb0fea9 + 17 子卡（地基×3 G1/G2/G3 + 台×10 + Agent 补×4），全自分配 dreaminate；validate PASS（51 卡 DAG 无环、依赖无悬空、视图新鲜）。leader self-review 18 张新卡 review_status 0→1。
- **待拍**：A 类工程取舍 7 条 leader 已决（图 codegen 子集/promote 复用晋级门/成本档/里程碑切 tab/self-approve 归属/handoff 形态/handler 深度，写回各卡 [已决]）；B 类 2 条等用户拍（F1 三纯库+暴力遍历范围 / F2 audit 方法学口径），state 待决岔路点名，P0 不阻塞。
- **理解资产**：2 轮并行理解 workflow（4+6 agent，~98 万 token）吃透 7 个台/组件 + DC 运行时（support.js）+ 跨台共享地基 + 冻结红线边界，落 /tmp/qbt-*.md（本机临时，不入库）。
- **诚实状态**：本 session 未写任何前端/后端代码，纯开卡 + 落档；实装由子卡承接，每卡对抗测试已钉权限⟂治理/冻结页/止于模拟盘/弱点一等/措辞合规。
- **下一步**：P0 地基 G1（暗色台壳件+token+accent）→ G2 画布引擎 / G3 Agent 对话+Inspector+Dock → 各台 P0 像素还原；因子台进实现前清 F1/F2 待拍。

## 2026-06-21（续）· F1=B 拍板 + 前端测试缺口补卡 + 真值源入库

- **用户拍板「1走b、都做」**：F1=B 走 (b)——三纯库（算术/ML/DL 分库+信号契约 R17）+ 暴力遍历挖掘（生成/守门解耦、诚实-N R16）本期补，handoff 无稿由 leader 直接设计实装，立 **F3 `a11e2aa5`**（前端设计+实装）/ **F4 `51271d38`**（后端）承接；F2 方法学口径延后到 F2 实现时拍。
- **前端测试缺口**：勘查 `app/frontend` 零测试设施（无 vitest/playwright、0 测试文件），所有前端卡对抗测试无处落地=违「门必抓」铁律——立 **G0 `e2de3d32`**（vitest+RTL+对抗 harness）作 G1 及全部前端实装卡硬前置。
- **真值源入库**：handoff bundle → `docs/design/handoff/`；10 份理解报告 → `dev/research/findings/desk-handoff/`（防 /tmp 清）。
- **落档**：epic 子卡 17→20（+G0/F3/F4）；决策 D-DESK-F1B；build_card_counters/board/dev_map/ledger 全刷新，validate PASS（25 活跃卡、唯一待拍 F2 b106177f）。**仍未写任何实装代码**。
- **下一步**：P0 顺序 G0 测试设施 → G1 地基 → G2/G3 → 各台像素还原（S1 策略台优先）。

## 2026-06-21（续3）· P0 地基 G0-G3 + 第一波 5 台实装完成（9 卡 done）

- **地基**：G0 测试设施（vitest+RTL+jsdom+对抗 harness 禁词/冻结守卫，runner 绿能绿红能红自证）· G1 desk 壳件+theme-cc `--desk-*` token+per-desk accent+cssToObj（零硬编码色值）· G2 画布引擎（GraphCanvas/Node/Edge/MiniMap/geometry，受控）· G3 Agent对话7型气泡(gate 治理弱点强制展开 R25)+Inspector(locked→disabled)+Dock。
- **第一波**：S1 策略台（DAG 工作台 17 节点/19 连线 mock + 治理三层硬强制：删除门/校验门/连线门 B6）· F1 因子台 5 视图 · M1 Model台 4 子台（晋级门 approver≠creator 校验对齐后端 422）· P1 模拟台 5 视图+PaperBoardCard（A股止 paper、风险门只读、晋级须人工 INV-5）· R1 裁决卡（verdict 三态不混 GateVerdict「晋级候选」、R7 措辞「排除过拟合」改写为「容差内/未触发熔断」、不嵌冻结页、promote 受控）。
- **路由**：App.tsx 加 desk 全屏分支（绕 cc Shell，与冻结页同理），/strategy /factors /models /paper；/factors /models 从 cc Shell 迁入 desk。
- **验证**：全量 vitest 11 files / **124 passed** · tsc clean · `npm run build` ✓（基线不破）· 零硬编码色值全目录。
- **落档**：G0-G3 + S1/F1/M1/P1/R1 → done（9 卡）。R1 残余：frontend-run-detail 顶栏（非冻结 cosmetic）land 前补。
- **进行中**：第二波 F3（因子台三纯库+暴力遍历挖掘）+ Agent 窗口（T-040/A1/A2/A3 合并）；后续后端波 S2/F2/F4/M2/P2/R2/A4（pytest）→ land。诚实：前端 P0 用 mock+MockBadge，接真后端在后端波。

## 2026-06-22 · 真实联调（dev server + 后端真跑）+ 抓修 1 真 bug + 前后端真连通验证

- **真实环境**：起后端 `uvicorn app.main:app:8000` + 前端 `vite:5173`，浏览器逐台真渲染验证（非单测 mock）。
- **5 台真渲染全过**：per-desk accent 全对（策略橙 / 因子紫 `#a98fd4` / Model蓝 `#6f9bd1` / 模拟绿 `#9bbd5a` / Agent橙 `#d97757`）；策略台画布 **18 节点 / 21 连线** 真渲染、pan-zoom 几何 `translate(44px,70px) scale(0.72)` 与 DC 原型初始值**逐字一致**；7 个因子 sub-tab（F1+F3 并入同台）。
- **抓 + 修 1 真 bug**（单测没抓、真跑才暴露）：`AgentWorkbenchPage.advance()` 把 `setBlocks` 等副作用写在 `setCursor` updater 内 → React 18 StrictMode 双调 updater → blocks 双推 → 重复 key 刷屏。修：副作用移出 updater（`cursorRef` 读游标）+ autoplay StrictMode 双挂载守卫 + restart 重置游标。验证：DOM 19 block **0 重复 id**、agent-workbench 60 vitest、全量 **241 vitest + tsc + build** 全绿。
- **层面2 前后端真连通**：模拟台 `/api/paper/runs/.../{status,positions,fills,balance,promotion}` + Model台 `/api/training/jobs` 浏览器实测**全 200 OK**；curl 后端确认真数据（paper balance CASH 1e6 / config symbols / promotion 4 门真值；training job xgboost succeeded）。authFetch ↔ 端点 URL 全对、真数据流通——「前端切真」从「写了代码」坐实为「真跑通」。
- **e2e 完整闭环**：登录(devqa)→建策略 200→`validate` 200 `{ok:true,errors:[],warnings:[]}`→`versions` 200 真版本史(content_hash b2dc13ad)；validate before-login 401(URL/方法对)、login 后链路全通。不需 auth 台 paper/training 200 + 真数据。
- **视觉逐像素核对**(computed style 实测，比截图准)：root bg #1c1b19 / 文字 #e6e1d6 / accent #d97757 / JetBrains Mono、节点卡 bg #1d1c19 / border 1.5px / w176、五台 accent 全中 DC 精确值、pan-zoom `translate(44,70)scale(.72)` 逐字一致。
- **残余全清（2026-06-22）**：① 3 pre-existing bug 修（`_dt` NameError create_verdict 500→200 + operators `ts_corr/ts_cov` 跨 symbol 泄露 `.over(order_by="ts")` + 4 个 Cargo/Tauri 缺陷），bug-catch proof（revert 即 FAIL）+ 后端全量 **1237 passed** ② **T-042 桌面 `tauri build` 真跑通**：cargo check ✅ + tauri build --debug ✅(47.76s)，产物落盘 quantbt-desktop(Mach-O arm64 34MB)+QuantBT.app+QuantBT_1.0.0_aarch64.dmg(10MB) ③ R1 frontend-run-detail 顶栏(logo QB/nav 6tab/血缘按钮)，冻结 RunDetailPage 零改动。
- **诚实保留**：操作触发型 fetch 仅策略台 validate 做了完整 e2e（其余因子 audit/裁决卡同源封装、未逐一点）；视觉核对抽样关键元素（未逐像素扫全台每个组件）；Tauri 仅 aarch64-apple-darwin 本机原生（跨平台 nsis/deb/appimage 未产）。
- **land**：实装 + 真实联调 + e2e + 视觉核对 + 残余全清完成，commit / 合并 main 待用户授权（不擅自 commit/push）。

## 2026-06-22 · 整套台前端 epic（cfb0fea9）实装完成（24 卡 done）

- 三波前端（地基 G0-G3 / 台前端 S1·F1·M1·P1·R1·F3 / Agent 窗口 T-040·A1·A2·A3）+ 两波后端接真（S2·R2·M2·P2·F4·A4·F2）+ 教学/桌面（T-041·T-042）= **24 子卡全实装落档 done**，活跃卡 0，validate 49✅/0❌/0⚠️。
- **最终全量验证**：后端 pytest **1231 passed/13 skipped**、前端 vitest **241 passed/21 files**、tsc clean、`npm run build` ✓。
- **治理红线全守**：冻结 RunDetailPage 不嵌不深色化、权限轴⟂治理（bypass 不跳门）、默认止于模拟盘、弱点一等呈现(R25)、裁决措辞禁词走 _verdict_note(R7)、A股止 paper、晋级 approver≠creator+背书(INV-5)。零硬编码色值（全 --desk-* token）。
- **诚实残余**：①各台未接端点处 mock+MockBadge（P1 深度功能逐步接真）②T-042 桌面 `tauri build` 待 npm install tauri-cli + 修 pre-existing Cargo `[lib]` 缺 src/lib.rs ③pre-existing bug 已 spawn 修复任务：`create_verdict` _dt NameError（无测试覆盖）、`operators ts_corr/ts_cov` 跨 symbol 泄露（注册前视门已防住入库）。
- **land**：实装完成、验证绿、24 卡落档 done；**commit/合并 main 待用户授权**（CLAUDE.md 不擅自 commit/push）。当前全部改动在工作区（fullstack 分支）。

## 2026-06-22 · 前端交互 bug 修复 + 文案去 AI 包装（已 push origin/fullstack）

- **触发**：用户 goal「前端有交互逻辑 bug；不动大逻辑下把描述去掉 AI feature 包装、改成正常产品描述」。
- **方法**：并行 deep-opus 子代理地毯式发现（交互 bug + AI 文案盘点）→ leader **亲自复核每条不照单全收** → 改 → tsc + vitest 验证 → 对抗验证待办项。
- **交互 bug 修复（11+ 处，纯前端·不动大逻辑·tsc0/前端241）**：
  - 死循环/请求风暴：CopyTrade/IDE `getStoredUser()` 每 render 新对象进依赖数组 → 稳定 `user_id` 代理。
  - 真钱页假绿灯：Binance `store()/switchToTestnet()` 补 `res.ok` 守卫（HTTP 失败不再报成功+清密钥），对齐同文件 confirmKill 范式。
  - **OOS 训练泄露（数据有效性级）**：TrainingBench 选「前 N% 训练」但 submit() 漏传 `train_fraction`、UI 却承诺「无泄露」→ 后端全样本训练=真泄露。后端切片管路（`_slice_front_dates`/service.py L245/回测 strict_oos）本已就绪自洽，**前端补传一行**即兑现（详见 D-FE-REVIEW）。
  - 因子注册假绿灯门（gateChecks 跟随 live + 按钮 disabled + bdRegister 守卫）、StrategyConsole revert 撤错（只栈顶 patch 可 revert）、ChatComposer IME 合成误发、SettingsSecurity 2FA try/catch、Shell 顶栏高亮、Login `?next=` 跳转+防开放重定向、Experiment 非数组崩溃守卫、CommunityFeed toggleLike try/catch。
- **文案去 AI feature 包装（纯字符串·不动逻辑）**：StrategyWorkshop「自然语言→」失真→「关键词规则提取」；IDE「AI 助手/AI 辅助(BigQuant风)/让 AI 写」→「代码助手/生成」；Mode2「量化教练/副驾驶/Socratic」→「研究问答/复核」；Pricing/CoachBanner/Templates/Glossary(去 GPT 品牌名)/Home(去黑话)/Build·Jobs·Research Deck mock「助手」→「面板」。真 LLM 功能保留准确描述、不删功能。
- **对抗验证（10 条待办 claim · 每条独立 skeptic 默认当误报）**：真该现在修 3（OOS 已修 / agent-live-mock LIVE 批准门重放 mock 脚本 / jobsdeck selJob 卡 mock id，后两待拍）；**误报 2**（SharedStrategies 刷赞被后端 PK 去重推翻、PaperDesk 双击双审批被后端 self.lock+GateStateError+幂等三护栏推翻）；**死代码 1**（Runs WS 是 stub 永不触发）；其余 mock/低影响 later。**H3「Runs 涨跌色反转」确认误报**——A 股「红涨绿跌」正确惯例，不改（防回潮，见 D-FE-REVIEW）。
- **入库纪律（D-GITIGNORE-ARTIFACTS）**：gitignore `graphify-out/`（52MB 生成产物）+ `data/strategy/`；demo 示例数据仍入库。push 前凭据扫描 0 命中。
- **land**：**已 push origin/fullstack**（c213583 主体 + cb2a083 gitignore，138 文件；用户拍板「全部工作区一起推、去掉生成产物」）。dev/ 账本本次同步补记。
