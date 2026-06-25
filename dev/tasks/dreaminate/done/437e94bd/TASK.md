---
uuid: 437e94bd4e1e4a56bf2c52c6b96ed333
title: Agent Orchestrator——role agent 调度 + 24 事件投影 + Plan/ReAct/Review/Replay/Repair（A-AGENT-ORCH）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: agent-orchestrator
source: goal
source_ref: GOAL §7(Agent Shell→Orchestrator→LLM Gateway→role dispatch·12 role agent·24 可见事件·Plan/ReAct/Review/Replay/Repair·所有 role agent 受 deterministic DAG/governed compiler 管理·只经工具权限/canonical command/compiler 写 Research Graph)
depends_on: [640b66a0cfb44c3295b2fa8cf57a3568]
---

# Agent Orchestrator（A-AGENT-ORCH·LINE-A-AGENT 续·LLM Gateway 已解锁）

## Scope [必填·先读 GOAL §7]
LLM Gateway（640b66a0·已 land）建了唯一调用入口。本卡建 **Agent Orchestrator**——§7「Agent Shell→Agent Orchestrator→LLM Gateway→role agent dispatch」：① 12 role agent 调度（Coordinator/Planner、Literature/Mathematical Researcher、Data/Factor/Model/Signal/StrategyBook/Backtest Engineer、Risk Analyst、Verifier/Critic、Reporter·串/并行）② 可见事件投影到 user 工作流 ③ Plan/ReAct/Review/Replay/Repair 五形态 ④ 所有 role agent 受 deterministic DAG 管理·只经工具权限/canonical command 写 Research Graph。**wrap 现有 agent_runtime.py 不重建**·LLM 全经 Gateway（绕过→拒）。

## 完成记录（2026-06-26·deep-opus 任务线·隔离 worktree·基于 origin/main 前四波已 land·分支 `wave4/agent-orchestrator`·待中心整合+全量+land）

> 自含交付摘要。**🟡≠✅**：本卡核心门已建并经变异验证（下表 6 个 MUT 各自抓红·真门=生产代码、纸门=拆门后放过·非 git checkout）；全量 2057 套件 + land 由中心做（本线只跑 scoped + collect-only 基线）。

### 新建文件（greenfield·只动新建 `app/agent/orchestrator/` 包·没碰 main.py / agent_runtime 内部 / llm / graph / qro / 其他在飞线）
- `app/backend/app/agent/orchestrator/__init__.py` —— 包导出（42 符号）。
- `app/backend/app/agent/orchestrator/events.py` —— **24 可见事件**全集常量（GOAL §7 逐行·import 期硬校验 ==24·去重不漏）+ `WorkflowEvent` + `EventProjector`（统一流·adopt LLM Gateway 5 枚同名事件=单一源）+ **可见性边界门** `assert_event_clean`（secret 明文 / provider 隐藏思维链键 → 拒）。LLM 5 枚直接 import gateway 的 `EV_ROUTE_SELECTED…` 常量（不另立字符串·防漂）。
- `app/backend/app/agent/orchestrator/roles.py` —— **12 role agent** 登记（`RoleAgent`·import 期硬校验 ==12）+ 每 role 工具权限白名单（GOAL §7「工具权限按台过滤」落点·home_desk 复用 research_graph 的 DESK_* 单一源）+ `capability()`（交 Gateway 的 `RoleCapabilityRequest`·Verifier 默认 independence_required=True）。
- `app/backend/app/agent/orchestrator/governance.py` —— **`GovernedToolDispatcher`**（工具派发唯一闸）+ `NodeExecutionContext`（进冻结 DAG 节点才铸出·HMAC 令牌·dispatcher 私有 nonce）+ `DAGBypassError`/`ToolPermissionError` + `ToolCallRecord`/`ToolViolation`。三道闸：无节点上下文（自由派发）→拒 / 令牌无效（伪造上下文）→拒 / 工具越白名单（越权·越 DAG 计划）→拒+记 violation。
- `app/backend/app/agent/orchestrator/llm_adapter.py` —— **`GatewayLLMAdapter`**（实现既有 `LLMClient` 接口·可直接注入被 wrap 的 AgentRuntime；内部把每次 `chat` 翻成 `LLMRequest` 经 `gateway.complete` 出门·封印+落账+5 事件；`provider="gateway"`·role agent 拿不到 provider/key）+ `assert_llm_admissible`（复用 gateway `assert_admissible_to_graph`·绕过 Gateway 自造 → 不可准入）。
- `app/backend/app/agent/orchestrator/plan.py` —— Plan 形态产物 `AgentPlan`（todo/deps/risk/gates/handoff/rollback·缺 todo/deps/gates 或悬空依赖→维持 draft·不晋升）+ `AgentTodo`/`AcceptanceGate` + `AgentCodeChange`（缺 diff/test/rollback→拒·声称按理论实现缺 TIB→拒）+ `AgentCompletion`（声称完成但工具记录缺失→拒）+ `MethodologyChoiceRecord` + `assert_methodology_user_decided`（agent/scheduled_agent 自拍方法学松紧→拒·决定权属 user）。
- `app/backend/app/agent/orchestrator/orchestrator.py` —— **`AgentOrchestrator` 核**：五形态（`plan` / `dispatch`=ReAct / `admit_verifier_challenge`=Review / `replay` / `repair`）+ `role_node_op`（role agent 在冻结 DAG 节点内受治理执行·**wrap AgentRuntime**·注入 gateway-backed llm + 注册受治理工具）+ `make_executor`（注册 op 的 `DurableExecutor`）+ 工具→语义事件投影 hook + `propose_graph_write`（唯一图写口=`graph.apply(CanonicalCommand)`·agent 写图绝不冒充 user_manual）+ `open_handoff`。role 节点全 `kind="pure"`（不触 effectful·绝不动钱）。
- `app/backend/tests/test_agent_orchestrator.py` —— **47 测试**（5 门 + 6 MUT + 正例 + 集成 + 12 role/24 事件/五形态/可见性/图写/Replay 覆盖）。

### 真测试汇总行（scoped·带 timeout·凭真汇总行判绿·不叠跑）
- `pytest tests/test_agent_orchestrator.py -q` → **47 passed in 0.16s**。
- `pytest test_agent + test_agent_permission_tristate + test_llm_gateway + test_llm_record_replay + test_dag_kernel + test_kernel_wiring + test_research_graph -q` → **185 passed in 1.97s**（被 wrap/依赖的 agent·gateway·内核·图 现有套件零回归）。
- `pytest --collect-only -q` → **2057 collected**（基线 2010 + 本卡 47 净增·无 collection error·基线未破）。
- `python -m py_compile app/agent/orchestrator/*.py tests/test_agent_orchestrator.py` → 全过；本环境无 ruff/pyflakes（未安装·非本卡引入）·已用 AST 自检无未用 import。

### 对抗测试·变异验证（种坏门必抓·门是不是纸做的·RULES §2·真门=生产代码、纸门=拆门后放过）
| MUT | 拆哪道门 | 抓红测试（真门=生产 API） | 卡面要求 |
|---|---|---|---|
| MUT-1 | DAG 上下文闸（无节点上下文即拒）拆成 no-op | `test_gate1_MUT_paper_door_free_dispatch`（真门=`dispatcher.dispatch(node_ctx=None)`→`DAGBypassError`；纸门放过） | **绕过 DAG MUT** ✅ |
| MUT-2 | 准入门封印校验摘除 | `test_gate2_MUT_paper_door_no_seal_check`（真门=`assert_llm_admissible(伪造账)`→`LLMRecordError`；纸门放过） | **绕过 Gateway MUT** ✅ |
| MUT-3 | 独立性裁决拆成一律放行 | `test_gate3_MUT_paper_door_independence`（真门=`orch.admit_verifier_challenge(假独立)`→`VerifierIndependenceError`；纸门放过） | **Verifier 独立性 MUT** ✅ |
| MUT-4 | 完成门改成只看 claims | `test_gate4_MUT_paper_door_completion`（真门=`AgentCompletion(claims=True,无工具记录)`→`AgentCompletionError`；纸门放过） | 完成门 MUT |
| MUT-5 | 方法学决定权门拆除 | `test_gate5_MUT_paper_door_methodology`（真门=`assert_methodology_user_decided(agent 自拍 accepted)`→`MethodologyAutonomyError`；纸门放过） | **Agent 替拍方法学 MUT** ✅ |
| MUT-6 | 可见性边界扫描拆除 | `test_visibility_MUT_paper_door_secret_leak`（真门=`assert_event_clean(secret)`→`EventProjectionError`；纸门泄露） | 可见性边界 MUT（加固） |

> 卡面强制 4 MUT（绕过 DAG / 绕过 Gateway / Verifier 独立性 / Agent 替拍方法学）全覆盖（MUT-1/2/3/5）；另加 2 道加固 MUT（完成门 / 可见性边界）。

### 可证伪验收逐条（对卡上 5 条）
1. **多 Agent 绕过 DAG 自由派发工具 → 拒** ✅：工具只经 `GovernedToolDispatcher.dispatch`，必带「进冻结 DAG 节点才铸出」的 `NodeExecutionContext`（HMAC·dispatcher 私有 nonce）——无上下文（LLM 当控制器自由派发）/伪造令牌 → `DAGBypassError`；越白名单 → `ToolPermissionError`+记 violation（`test_gate1_*` 4 正反 + MUT-1）。集成：节点内 LLM 派发越权工具 → 闸拒+记 violation → 节点 op 查 violation 非空即 raise → 内核判节点 failed + 投影 `FailureDetected`（`test_gate1_INTEGRATION_node_fails_on_planned_tool_bypass`）。
2. **AgentLLMCall 绕过 LLM Gateway → 拒** ✅：role agent 的 LLM 唯一路径=`GatewayLLMAdapter`（每次 `chat` 经 `gateway.complete`·封印+落账·`provider="gateway"`·拿不到 key）；每条结果过 `assert_llm_admissible`（绕过 Gateway 自造的未封印账验不过·`test_gate2_*` + MUT-2）；role agent 账只留 SecretRef、无明文 key（`test_gate2_role_agent_gets_no_provider_or_key`）。
3. **Verifier 与 Builder 共用上下文未标独立性 → 拒** ✅：`admit_verifier_challenge` 复用 gateway `evaluate_independence`（单一源）——共用上下文（同 provider+model）却声称独立（satisfied=True）→ 拒；共用但**诚实标 satisfied=False** → 不抛（honest 挑战·非干净独立）；换 provider → 独立成立（`test_gate3_*` + MUT-3）。集成：同 session builder+verifier 节点，gateway 给 verifier 路由到相对 builder 不同 provider（`test_gate3_INTEGRATION_verifier_routed_distinct_provider`）。
4. **声称完成但工具记录缺失 → 拒 · AgentPlan 缺 todo/deps/gates → draft · AgentCodeChange 缺 diff/test/rollback → 拒** ✅：`AgentCompletion` 构造门（claims_complete+无工具记录→拒·MUT-4）；节点 op 内置完成门（`test_gate4_INTEGRATION_node_fails_when_claims_complete_no_tool`）；`AgentPlan.validate` 缺 todo/deps/gates 或悬空依赖→status=draft·`build_dag` 拒 draft（`test_gate4_plan_*`）；`AgentCodeChange.__post_init__` 缺 diff/test/rollback→拒（声称按理论实现缺 TIB→拒）。
5. **Agent 替 user 拍板方法学松紧 → 拒** ✅：`assert_methodology_user_decided`——decided_by∈{agent,scheduled_agent} 且 decision=accepted → `MethodologyAutonomyError`；只有 user_manual / user_confirmed_agent 可 accept；agent 只能记 pending 的 `MethodologyChoiceRecord`（cost/recommended_path/responsibility_boundary）请 user 拍板（`test_gate5_*` + MUT-5）。

### 红线合规逐条
- **role agent 不直接调 provider/读 key（经 Gateway）** ✅：唯一 LLM 路径 `GatewayLLMAdapter`·`provider="gateway"`·内部 `gateway.complete` 物化凭据在门后；role agent 拿不到 provider 名/key（`test_gate2_role_agent_gets_no_provider_or_key`）。
- **绕过 DAG/Gateway → 拒** ✅：DAG 经 `GovernedToolDispatcher` 三道闸 + 节点 violation→failed；Gateway 经 `assert_llm_admissible` 封印准入门（MUT-1/2 双证）。
- **复用 ids.content_hash 不另造** ✅：节点身份由内核 `compute_node_id`→`lineage.ids.node_id` 算（本卡未碰）；治理令牌/封印是 **provenance HMAC**（同 gateway `seal_record` 范式·非 identity hash·不与 content_hash 竞争）。未新立任何哈希族。
- **扩展不替换（wrap agent_runtime 不改）** ✅：`git diff app/agent/agent_runtime.py` 空——一字未改；orchestrator 经注入 `llm`(GatewayLLMAdapter) + `register_tool`(受治理闭包) wrap 之。
- **Agent 不替 user 拍方法学** ✅：MUT-5 守。
- **无新公式 → 不强造 MathematicalArtifact** ✅：orchestrator 不自造任何 QRO/MathematicalArtifact；`propose_graph_write` 只把**调用方给的** payload 经 canonical command 落图。
- **role 节点全 pure·绝不触 effectful** ✅：`DAGTask.kind="pure"`——orchestrator 不发单/不动钱（A股永不实盘·杠杆护栏等执行层红线本卡领地外·未触）。

### 拍板项命中（GOAL 没覆盖的岔路·停报中心）
- **24 vs 23 事件计数差**（需中心一句确认·非阻塞·已按 GOAL-FIRST 处理）：GOAL §7「可见事件类型」**逐行列了 24 个**事件名（AgentPlanCreated … RunVerdictProduced）；卡面摘要 + assign 写「23 可见事件」。按 GOAL-FIRST（用户三次强调以 GOAL 原文为契约），实现 **24 全集**（少实现一个=自造契约）·`events.py` import 期硬校验 ==24。判定：卡面「23」是摘要时的 off-by-one 计数，GOAL 原文 24 为准。**若中心认定确应 23**（某枚不算 user 可见），请指明哪枚、我再调——但当前以 GOAL 列举为唯一依据。已在 `events.py` docstring + 本卡诚实点名。
- 其余**无停报项**：12 role / 五形态 / DAG 治理 / canonical command 写图均 GOAL §7 明文覆盖；actor 四类、DESK/HOME_DESK、CanonicalCommand 信封均复用已 land 的 research_graph/qro 单一源（决策 R7-R12/R24-27 + D-QRO-CANVAS 已覆盖·未越界）。

### 诚实残余（会变成后续任务/接线·非本卡 scope·卡面非目标已列）
1. **record/replay store 深接线**（fixture 后端 RecordingLLMClient）= 另卡：本卡 Replay 形态依赖 **kernel durable 工件复用**（真·零重跑·`test_replay_reuses_durable_artifacts_zero_rerun` 证：replay 命中→节点 reused→op 不调→LLM 调用数不变）+ gateway `replay_state` 标注；但「cache-miss 时也零真 LLM」的 fixture 后端接线未在本卡做（避免耦合 agent/replay·留接线卡）。
2. **Gateway/Orchestrator 接进 main.py + 前端工作流可视化**：本卡只交后端编排核 + 24 事件**数据**投影（`EventProjector`）；把事件投到 user Canvas / 把 Orchestrator 挂进 FastAPI 路由 = 接线卡（动 main.py·本卡领地外）。
3. **Fork/Rollback 形态的 orchestrator 包装**：内核 `DurableExecutor` 已有 fork/rollback（effectful 边界 HALT）；本卡显式包了 Plan/ReAct/Review/Replay/Repair 五形态（卡面要求），fork/rollback 作为内核能力可直接调用但未在 orchestrator 加专用糖方法（按需另接）。
4. **真业务工具接线**：role 工具白名单是**能力类抽象占位**（read_asset/run_validation/…）+ 受治理派发模型；接 `business_tools.py` 的真工具（按 role 白名单注入）= 接线点（本卡只定权限模型 + 闸·真工具注入由调用方/接线卡做）。
5. **ProviderFallbackUsed / RagHitUsed 等部分事件**仅在对应路径触发时投影（fallback 真发生 / 真用 RAG 工具时）——本卡保证 24 枚都有 emit 落点，未强制每次 run 都触发每一枚。
