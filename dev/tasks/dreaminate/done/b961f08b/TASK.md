---
uuid: b961f08b270a4e2bb99765672213b249
title: Agent 后端工具补全 — 4 schema+handler + stream 结构化事件 + handoff
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [edc1e32623674b1f870b264119db2421]
---

# Agent 后端工具补全 — 4 schema+handler + stream 结构化事件 + handoff

## Scope [必填]
后端补全 strategy 台 agent 所需工具与事件管线：在 `TOOL_SCHEMA` 新增 5 个缺失业务工具 schema（hypothesis.create / factor_set.compose / model_registry.select / signal.define / portfolio.construct）+ 给 3 个有 schema 无 handler 的工具（backtest.run / eval.pbo / report.generate）接真引擎、`register_tool(side_effect="none")` 注册；agent stream 端点发结构化 SSE 事件（tool 开始/结束、gate 挂起、todos、thinking、里程碑）；新增 handoff 端点把候选策略提交模拟台候选池。**不做**：前端窗口/产物卡/里程碑 UI（属 T-040/T-044/T-045）、不注册任何动钱/晋级工具、不新建第二套 run/PBO/report 引擎（复用现有）、不碰 model/hypothesis/ide 的 promote 晋级链。

## 上下文 / 动机 [按需]
扩 T-043 残余（依赖 AgentRuntime edc1e32623674b1f870b264119db2421 / 残卡 3bb62d7d）。设计稿 `QuantBT Agent.dc.html` 剧本用了 7 个业务工具名，后端现状：`TOOL_SCHEMA` 只有 backtest.run / eval.pbo / report.generate（有 schema、handler 未接，三者均 unwired），其余 5 个 schema 都不存在；`_agent_runtime()` register 块只注册 strategy_goal.create / factor.run_ic(stub) / code.replicate + field tools。设计稿 7 种 chat block（thinking/say/todos/tool/gate/handoff/user）需要后端发结构化 SSE 事件，但现 stream 端点只发 `rag`/`chunk`/`done`、且**未取 permission_mode**（非流式 `/chat`、`/message` 都取了，stream 漏）。handoff 卡终点「候选策略→交接模拟台」无后端端点。这些是设计稿剧本能真跑的后端地基。

## 接线点（file:line，实现时复核）[必填]

| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/agent/tool_schema.py` | `TOOL_SCHEMA` list 末尾 L198 前 + report.generate L182~186 区 | 追加 5 个新 schema dict（hypothesis.create / factor_set.compose / model_registry.select / signal.define / portfolio.construct），与既有 backtest.run/eval.pbo/report.generate 风格一致；只扩 list、不动既有 17 条 |
| `app/backend/app/main.py` | `_agent_runtime()` register 块 L296~305 | 扩 register：3 个真 handler（backtest.run→BacktestVenue 链、eval.pbo→`cscv_pbo()`、report.generate→`render_card_md()`/`render_detail_bundle()`）+ 5 个新 schema 的 handler，全 `side_effect="none"`；register 块只准 none——动钱/晋级永不进此块（对抗 #1 的钉点） |
| `app/backend/app/agent/agent_runtime.py` | `permission_gate()` L37~48 / `register_tool()` L91~93 | 复用不改逻辑；新 handler 经 register_tool 时强制 side_effect 走默认 none；realmoney 恒 confirm 不动 |
| `app/backend/app/main.py` | `chat_stream()` event_stream L3140~3184 | 扩 SSE 事件类型：把裸 `client.stream_chat` 换成 `runtime.run` 的步进，发 `event: tool`(开始/结束)、`event: gate`(挂起)、`event: todos`、`event: thinking`、`event: milestone`；side_effect 字段必从 `runtime._side_effects`/`tool_status` 取真值（不接收前端传入，对抗 #3 钉点） |
| `app/backend/app/main.py` | `chat_stream()` 签名 L3127~3128 | 补取 `permission_mode`（Query 或 body），传入 `_agent_runtime(permission_mode=...)`——对齐 `/message` L3105 已有的取法 |
| `app/backend/app/main.py` | 新增端点（紧邻 M14 Agent 段 L1503 之后或 paper 段） | 新建 `POST /api/strategy/submit_candidate`：候选策略写入模拟台候选池（止于 PaperVenue/`paper/scheduler.py` 流，**不调** `/api/models/.../promote` L481、`/api/ide/runs/.../promote` L2520 等晋级链）；缺过拟合/血统要件→拒 |
| `app/backend/app/eval/pbo.py` | `cscv_pbo()` L58 | eval.pbo handler 复用此函数，不重写 CSCV |
| `app/backend/app/run_detail_core.py` / `app/backend/app/notebook_primitives.py` | `render_card_md()` / `render_detail_bundle()` L120 / `get_run_response()` L24 | report.generate handler 复用现有渲染，按 run_id 取 run 输出 |
| `app/backend/app/execution/backtest_venue.py` | `BacktestVenue` L55 + `experiments/store.py` `create_run()` L134 | backtest.run handler 走真 venue + 落标准 run 目录，不造影子引擎 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「把 realmoney 工具（如 order.place / model.promote）写进 `_agent_runtime()` register 块或用 `register_tool(..., side_effect="realmoney"/"external")` 注册给 agent」→ 门必抓：断言 `runtime._side_effects` 所有值恒为 `"none"`、register 块不出现任何 realmoney/external 工具名；变异要杀点——把某新 handler 的 side_effect 默认从 none 偷改为 external 必须红。钉红线：register 块只注册 side_effect=none，动钱/晋级永不注册。
2. 种「`/api/strategy/submit_candidate` 直接调 promote 晋级链（`/api/models/promote` / `ide_promote_run` / paper→live）或跳过 ladder 把候选推向实盘」→ 门必抓：断言 handoff 落点只触达 PaperVenue/候选池、永不触达 OrderGuard live/mainnet 路径、永不调 `MODEL_REGISTRY.promote`；变异要杀点——把 submit 目标从 paper 改成 live venue 必须红。钉红线：handoff 止于模拟盘、不导向实盘、不跳 ladder（R8 / D-PERM）。
3. 种「stream SSE 的 `side_effect`/gate 判定值从前端请求体取（可被客户端伪造成 none 绕过 confirm）」→ 门必抓：构造 permission_mode=bypass + 伪造 side_effect=none 的请求，断言 gate 判定仍走后端 `runtime._side_effects` 真值、realmoney 任何模式恒发 `event: gate`(confirm)、external 非 bypass 恒 confirm；变异要杀点——让 stream 读取 payload 里的 side_effect 必须红。钉红线：side_effect 真值只出后端、permission_gate realmoney 任何模式恒 confirm。

## 复用 [按需]
- 回测：`BacktestVenue`（backtest_venue.py L55）+ `RunStore.create_run()`（experiments/store.py L134），不另造。
- PBO：`cscv_pbo()`（eval/pbo.py L58）；DSR 既有 `deflated_sharpe_ratio()`（eval/dsr.py L58）已 schema 在册。
- 报告：`render_card_md()` / `render_detail_bundle()`（notebook_primitives L120）+ `get_run_response()`（run_detail_services L24）。
- 权限：`permission_gate()`（agent_runtime L37）逻辑零改，仅被新 handler 间接复用。
- handoff 落点：`PaperVenue`（paper_venue L44）/ `PaperScheduler`（paper/scheduler L75）现成模拟台流。

## 红线 [按需]
- register 块只注册 side_effect=none 工具；动钱/晋级（order.place / *.promote）永不注册给 agent（D-PERM 权限轴⟂治理轴，纵深防御钉端点层）。
- `permission_gate` realmoney 任何模式（含 bypass）恒 confirm；external 仅 bypass 自动。
- handoff 止于模拟盘，不导向直接实盘、不跳 ladder（R8）；A股 live 下单永远拒；下单唯一入口经 OrderGuard。
- SSE 的 side_effect/gate 判定真值只出后端 `runtime._side_effects`，绝不接收前端伪造值。
- 主进程不碰 torch（M6）；实盘 key 不进 LLM；新增 5 工具 handler 全本地可重置、无外部副作用。

## 非目标 [按需]
- 不实装前端 agent 窗口、产物卡、里程碑、台 switcher（T-040/T-044/T-045）。
- 不接 eval.dsr / attribution.brinson / experiment.compare 等已在册其它工具的 handler（不在本卡 7 工具范围）。
- 不改 model/hypothesis/ide 三条 promote 晋级链的 approver≠creator + 验证背书逻辑（INV-5）。
- 不做 LLM 真 token streaming 升级（沿用现有 stream_chat），只补结构化事件类型。

## Open Questions（已决 D/总）[按需]
- [已决] register 块只注册 side_effect=none，动钱/晋级永不注册（D-PERM，已决·不重议）。
- [已决] handoff 止于模拟盘候选池、不导向实盘（D-PERM / R8，已决）。
- [已决] side_effect 真值只出后端 `tool_status`/`_side_effects`，前端不可伪造（T-028/T-040 对抗已立）。
- [已决] handoff 端点 POST /api/strategy/submit_candidate 写候选池、止于模拟盘(不导向实盘)；与现有 paper 调度的衔接实现时定(非阻塞)。— leader 2026-06-21
- [已决] 5 新 schema 工具 handler 真接对应 store(HYPOTHESIS_STORE / FactorRegistry / MODEL_REGISTRY 只读 select / signal / portfolio 构造)保证剧本可跑；动钱/晋级工具永不注册(仅 side_effect=none)。— leader 2026-06-21
- D/总：占位（主控 build_card_counters 重算）。

## 验收一句话 [必填]
种「动钱/晋级工具被注册进 agent / handoff 直推实盘跳 ladder / stream 用前端可伪造的 side_effect」三类坏 → 三道门（register 恒 none、handoff 止于 paper、gate 判定走后端真值）必抓，且不破现有 agent_runtime / permission_gate / tools 端点 / chat_stream 测试基线。
