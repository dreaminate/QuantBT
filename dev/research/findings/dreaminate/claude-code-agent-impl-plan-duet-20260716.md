# Claude-Code 式内嵌量化 agent — 第一薄纵切 工程实现图（duet 并集·recalibrated 放权）2026-07-16

> 状态：**设计定稿·零代码落地**。duet 并集（deep-opus 全案 ‖ codex 跨厂商校正 ‖ 我骨架+裁决），据用户
> 2026-07-16「放权给 user·只提供平台·别太严厉」recalibrate 上一版 [[claude-code-agent-foundation-design-20260715]]。
> **红线 floor（3→2 层结构性）属安全相关改动 → 落码前必须跨厂商 codex 复审**（沿用命门纪律）。全部 file:line
> 采自当前 worktree 真码；claude CLI 确切 flag 落地时复核（见 §6 未验证项）。

## 0. duet 收敛 + 跨厂商校正（据实）
**两半独立收敛**：stdio MCP 独立进程 · **import 隔离 = 真 L0 无钥**（MCP 只从 `spine.py`+`paths.py` import·绝不 `app.main`/`app.agent.__init__`——后者拖入 keystore/OrderGuard/execution）· 非注册 floor · 复用现有 GraphCanvas。

**codex 跨厂商校正（独立实测·推翻上一版假设·已并入）**：
1. `--permission-mode default` **对 claude 2.1.210 非法**——合法值 `dontAsk/acceptEdits/auto/manual/plan/bypassPermissions`。落地取正确值（默认 tier 无 CLI 工具时 permission-mode 影响小·但必须合法值·build 时核实）。
2. 现有 canvas projection 路由**非 owner-scoped**——新 agent 路径必须**加** owner 过滤（别假设已有）。
3. MCP 生产入口不能 `import app.main`、不能走普通 `app.agent` 包入口（`app.agent.__init__` 连带加载凭据/venue 模块）——需**独立最小模块**入口（这正是 L0 无钥结构成立的机制·codex+deep-opus 双证）。

## 1. 模块结构（新文件·职责·复用锚点 file:line·扩展不替换 RULES §4）
| 新文件 | 职责 | 复用锚点 |
|---|---|---|
| `app/agent/backends/base.py` | `AgentBackend` Protocol·`PermissionTier`(用户可配)·`BackendEvent` union·`BackendReadiness` | 语义参照 `subscription_cli_llm.py`(token 不出进程 :20/:191-198)·**不扩** `ClaudeSubscriptionLLM.chat`(:287 一次性拒 tools :295)——新兄弟抽象 |
| `app/agent/backends/claude_backend.py` | claude v2.1.210 headless：拼 argv·spawn·`stream-json`→`BackendEvent` | `preflight()`=`provider_auth_report`(`subscription_cli_llm.py:131`)·`cli_installed`(:60)·spawn env 洁净参照 `_spawn_detached_login`(:183-198) |
| `app/agent/backends/{codex,opencode}_backend.py` | 仅 `preflight()`·`run()` `NotImplementedError`(诚实无静默 fallback RULES §3) | `provider_auth_report:131` |
| `app/agent_mcp/server.py` **(build 校正:兄弟包·非 `app/agent` 子包——见 §3 ★M1 落地校正)** | stdio MCP 进程入口(官方 `mcp` SDK)·注册**恰好** `{canvas_read,canvas_create_node}`·**绝不** import `main`/execution/security.gate | 直连 `PersistentResearchGraphStore`(`spine.py:1913`)+`DATA_ROOT`(`paths.py:9`)→ 附着 `DATA_ROOT/audit/research_graph_commands.jsonl`(= `main.py:775` 同一 JSONL) |
| `app/agent/mcp/tools.py` | 两工具 handler+schema。read=`_graph_canvas_projection` 投影·write=构造 `QRORecord`→CANVAS `upsert_qro` | read `_graph_canvas_projection`(`main.py:15477`)·write `QRORecord`(`spine.py:840`)+`ResearchGraphCommand(source=EntrySource.CANVAS,command_type="upsert_qro")`(`spine.py:951/1367/1683-1694`)+`store.apply`(`spine.py:2050`) |
| `app/agent/session_orchestrator.py` | 驱动外部 CLI agent 跑自身循环：preflight→建 ws+写 `.mcp.json`→`backend.run()`→`BackendEvent`→现有 SSE 词汇·写后 `RESEARCH_GRAPH_STORE.refresh()` 令跨进程写可见 | **非改** `orchestrator/orchestrator.py`(那驱动内部 role agent)·SSE `workbench_stream.py`(`start_background_workflow:45`·`sse_format:163`)·`refresh()`(`spine.py:1959`) |
| `main.py` 新路由 `GET /api/agent/session/stream` | 镜 `agent_workbench_stream`(`main.py:36060`)：`require_user_dependency`+owner scoping+SSE·**不碰** `_dispatch_production_agent_turn`(:5618) | `require_user_dependency`(:36071)·`_formal_owner_user_id`(:36084) |
| 前端 `agentSession.ts`(或 `agentLive.ts` 参数化 URL) | 新路由 SSE reader | `agentLive.streamAgentWorkbench`(`agentLive.ts:261`·URL 硬编码 :270 需参数化)·`dispatch`(:329)·`onToolEnd`(:82) |
| 前端 `StrategyConsolePage.tsx` +onToolEnd→刷投影 | canvas 工具 tool_end→重取 projection→现有渲染出新节点 | `fetchResearchGraphCanvasProjection`(:74·mutation 后重取 :604/640…)·`setGraphProjection`(:271)·`<GraphCanvas>`(`GraphCanvas.tsx:64`) |

测试文件(每 milestone 一组)：`test_agent_mcp_redline_floor.py`·`test_agent_backend_spawn_contract.py`·`test_agent_mcp_canvas_tools.py`·`test_agent_session_stream.py`。

## 2. PermissionTier(用户可配·放权核心) + backend + 工具契约
**PermissionTier**：`name`·`cli_allowed_tools`(CLI 自带 Bash/Write/Edit… 用户放宽)·`add_dirs`(--add-dir·用户可加真实目录)·`permission_mode`(合法值·见 §0.1)·`strict_mcp_config`(默认 True 只认我方 MCP·用户可关)·`allow_dangerous_skip`(默认 False)。
- **平台默认 tier `quant-research-default`**(slice-1 ships)：CLI 工具全不给(只我方 MCP 两工具)·`add_dirs=(throwaway_ws,)`·`strict_mcp_config=True`。**是默认非天花板**——用户自建 tier 放宽随意。
- **tier 唯一管不到=红线 floor(§3)**：tier 放到「全给 + dangerous-skip」·agent 仍**动不了钱/venue/A股-live**(那些工具在 MCP server 不存在·那些码不在 MCP 进程)。权限轴 ⟂ 红线轴。

**claude v2.1.210 调用**(tier 派生)：`claude -p "<task>" --output-format stream-json --verbose --mcp-config <ws>/quantbt.mcp.json [--strict-mcp-config] --permission-mode <合法值> --allowedTools mcp__quantbt__canvas_read mcp__quantbt__canvas_create_node <tier.cli_allowed_tools> --add-dir <ws> <tier.add_dirs>`。`.mcp.json` env=`QB_OWNER/QB_CAP_TOKEN(短 TTL)/BACKTEST_DATA_ROOT`·**绝无订阅 token**(那在 claude CLI keychain)。

**canvas_read**(只读·side_effect=none)：入参 `{limit?=24,asset_types?,visible_refs?}`→`store.refresh()`→owner-scoped `projection_index`→`_graph_canvas_projection` 逻辑→前端同 shape `ResearchGraphCanvasProjection`。**owner 过滤新加**(codex 校正：现路由非 owner-scoped)。

**canvas_create_node**(写·写 owner 自己 DRAFT 研究节点·**不触红线**)：
- **关键(据 `QRORecord.__post_init__` `spine.py:905-913`)**：QRORecord **强制**非空 `owner/market/frequency/lineage/implementation_hash/assumptions/known_limits/failure_modes/validation_plan`——工具**不能**只收 `{label,text}`。入参=`{qro_type,market,universe,horizon,frequency,assumptions[],known_limits[],failure_modes[],validation_plan[],input/output_contract?}`(agent 提假说+假设/边界/失败模式/验证计划=GOAL「画布表意+agent 辅助」)。
- 工具强制安全默认(非门墙·是构造良构 QRO)：`owner=actor=QB_OWNER`·`version=1`·`definition_status=DRAFT`·`runtime_status=OFFLINE`·`evidence_status=UNTESTED`·`qro_id` content_hash 派生。写路径 `ResearchGraphCommand(source=CANVAS,upsert_qro)`→`store.apply`(CANVAS owner 强制 `spine.py:1683-1689`·`qro.owner!=actor`→拒)。返 `{qro_id,version,projection_node_id}`。
- **为何非红线**：owner 自己 DRAFT/OFFLINE 节点·动不了钱·选不了 venue·不能置 LIVE(编辑 LIVE QRO 被 `spine.py:1705/1718/1735` 独立拒)·不缩 honest-N。

## 3. 红线 floor（recalibrated 2 层结构性·非门墙）
**3 硬禁**(RULES.project.md:11-12+GOAL)：不动真钱·无真实 venue·A股永不实盘。**只两条结构性事实·删逐参数拒门**(用户「minimal not a wall」)：
- **L-A 不注册**：MCP 工具表**恰好** `{canvas_read,canvas_create_node}`·动钱/venue/A股-live/testnet/mainnet 工具根本不注册。镜现有范式 `main.py:5303`/`main.py:36078`(动钱/晋级永不注册给 agent)。
- **L-B 不 import(架构无钥)·⚠️ 机制已据 codex 跨厂商复审+实测校正**：MCP 进程拿不到 venue key 因为 `place_order`/`OrderGuard`(`enforcer.py:20/50`)/`KeyBroker`(`broker.py:104`)/`keystore`/`trading_credentials` 的码**不加载进进程**。
  - **★ 校正(codex floor 复审 + 我实测)**：**不能**说「只 import spine 面 :13-38 = 零 execution」——`from app.research_os.spine import` **会先触发父包 `app/research_os/__init__.py`**(eager import `execution_boundary`:277·`execution_closure`:340 等治理账本)。即 spine.py 自身 import 干净·但**包级 __init__ 级联**加载了治理层。**上一版 prose 只 grep spine.py 顶部=不足证 L-B**(codex 逮出)。
  - **但安全 OUTCOME 仍成立(实测证)**：`env QUANTBT_RUNTIME_MODE=test PYTHONPATH=. python -c "import app.research_os.spine; ..."` → 1868 模块加载·**venue-key/下单码 0 个**(keystore/KeyBroker/trading_credentials/place_order/order_guard/enforcer/broker/secrets_loader 均**不在 sys.modules**)。治理账本(execution_boundary·非动钱·S4 审计证)被载·但**真正碰 key 的码没载**。
  - **真正的 L0 保证 = 经验断言(M1 test)·非 import-list 推断**：M1 对抗测试 `import server 后断言上述 danger 符号/模块不在 sys.modules`(镜 `test_realmoney_audit_killswitch` RULES.project.md:13)才是红线证据·prose 不能替代。**build 时**：若要更硬·MCP 入口用**最小模块**避开 `app.research_os.__init__` 级联(读规范 JSONL 或抽 store 到 leaf 模块)——待 codex floor 终verdict 定是否必要。既有 OrderGuard/执行边界不动(place_order 仍全程过 OrderGuard·只是 MCP 进程不可达)。
- **🔴 L-C spawn env 白名单(codex floor 复审 P0·动钱红线·必修)**：**绝不** `env=os.environ.copy()`(现 `subscription_cli_llm.py:197/303` 就是·会把 `QUANTBT_MASTER_KEY` 带进 agent env·而它解密 trading keystore `keystore.py:419`)。spawn env = **显式最小白名单** `{QB_OWNER, QB_CANVAS_TOKEN, BACKTEST_DATA_ROOT}`·**禁**一切 venue/keystore secret(QUANTBT_MASTER_KEY、venue key、broker token)。`QB_CANVAS_TOKEN` 必须是**canvas-only token·结构上不可被 KeyBroker 兑付**(`broker.py:25` CapabilityToken 无 api_key 字段·且此 token 不进 KeyBroker 兑付路径)。**否则**：开 Bash 的 agent 读 env 里的 master key→解 keystore→够得着真 venue(这是我方 orchestration 给的权限·非宿主机 ambient 风险)。
- **🔴 L-D CANVAS runtime 不变量(codex floor 复审 P1·venue/LIVE 红线·必修)**：`QRORecord` 只**默认** OFFLINE(`spine.py:856`)·非强制——CANVAS upsert 查 owner(1683-1689)后**原样写**(1690)·1705/1718/1735 的 LIVE 门护的是**别的操作**。codex 实测：`runtime_status=live` 的 CANVAS QRO **成功落**。修：**store 级 CANVAS 不变量**——CANVAS-source upsert 强制 `runtime_status ∈ {OFFLINE}`·拒 TESTNET/LIVE(在 `spine.py` CANVAS 分支 1683-1690 加断言·镜 owner 强制)。canvas_create_node 工具层设 OFFLINE 只是第一道·store 级才是红线证据。
- **诚实限界(RULES §3·L-C 修后收窄)**：L-C 后·agent env **无**我方 venue/key secret→即便开 Bash 也**读不到我方给的 key**。**剩余诚实边界**：若用户**自己**在宿主机 env/文件里有 venue 凭据·且放宽 Bash·则「无危险工具/无危险 import」不证任意 shell 够不着**用户自己的**凭据——那是用户自己的 ambient 风险·非我方 orchestration 提供。写清楚·这才是「放权」的正确显式代价(我方不递 key·用户自己的环境自己担)。

### ★ M1 落地校正（2026-07-16·真 build+实测·解本文件内部矛盾）
本文件曾内部打架：§0 line 14 说「不走 `app.agent` 包入口(`__init__` 连带加载凭据/venue)·需独立最小模块」·但 §1 模块表却把 server 放 `app/agent/mcp/server.py`（= `app.agent` 子包内）。**build 时实测判定 line 14 对**：
- **实测**：`import app.agent` → **2030 模块·`app.security.keystore`+`app.security.trading_credentials` 双双载入**（`app/agent/__init__.py:17` `from .llm_providers import ... llm_secret_ref` 级联进 keystore）。Python 导入任一子模块必先跑父包 `__init__`·**无法 opt-out**——故 server **不能**在 `app/agent/` 下。
- **修**：no-key server 落**兄弟包 `app/agent_mcp/`**（bare `__init__`）。实测 `import app.agent_mcp` → **75 模块·0 danger**；`import app.agent_mcp.server` → **0 danger**（keystore/trading_credentials/KeyBroker/place_order/ccxt/binance/vnpy/… 均不在 sys.modules）。
- **L-B 证据 = M1 对抗测试**（`tests/test_agent_mcp_redline_floor.py`）：**新解释器**子进程 import server 后断言 danger 模块集==∅ + 注册表=={canvas_read}。变异证有牙：加 `place_order` 进注册表→L-A 红；注 `import app.security.keystore`→L-B 红；均已跑验+字节级还原。
- **mcp SDK**：用**低层** `mcp.server.Server`+`stdio_server`+`@list_tools/@call_tool`（非高层 FastMCP——低层给 L-A 显式控制）·`requirements.txt` 钉 `mcp==1.28.1`。
- **M1 只发 canvas_read（只读地基）**：用户选「含 canvas 写(create_node)」是 epic 终态；**write 延到 M5**·**先证无钥地基再上任何写工具**（安全排序·非缩范围）。M1 land 前经**跨厂商 codex floor 复审**（builder=Claude·verifier=GPT·approver≠creator）。
- **未变**：L-C(spawn env 白名单·M3 修)、L-D(CANVAS store 级 OFFLINE 不变量·M5 修)照旧——M1 不 spawn、不 write·两者不 gate M1。

## 4. 编排 + SSE + GraphCanvas 写回（含跨进程一致性·关键修正）
编排流：preflight(未 auth→诚实 error·不 fallback 内部 agent)→建 ws+写 mcp.json→`backend.run()`迭代 `BackendEvent`→映现有 SSE 词汇(SessionStarted→say·Text→say·ToolCall→tool_start·ToolResult→tool_end·Done→done)→跑 `start_background_workflow`(`workbench_stream.py:45`)。新路由镜 `agent_workbench_stream`(`main.py:36060`)。
**canvas_create_node 写回(跨进程)**：MCP 是独立进程 append JSONL·API 的 `RESEARCH_GRAPH_STORE`(`main.py:775`)读内存 dict 不自动重读磁盘 → 不处理则 agent 写的节点不现于 `GET canvas_projection`。**解**：①并发安全内建——`store.apply`/`refresh` 都取 `flock(LOCK_EX)`(`cross_process_lock.py:70/100`)·跨进程串行·JSONL 不撕。②可见性 `refresh()`(`spine.py:1959`「fresh replay of the log」一等操作)：编排器观察到 `ToolResult(canvas_create_node)` 时 API 进程内调 `RESEARCH_GRAPH_STORE.refresh()`(一次·恰在写时)→前端 `onToolEnd`→`fetchResearchGraphCanvasProjection`→`setGraphProjection`→`<GraphCanvas>` 重渲染。零新渲染路径(= 手动 canvas 编辑刷新那条)。给编排器加 refresh-on-write(非每 GET refresh·避免每读全量重放·perf)。

## 5. 里程碑 M1–M6（顺序·各自独立测·每关对抗测试）
- **M1 MCP 骨架+L-B 无钥(红线地基先立)**：起 stdio·附着规范 JSONL·注册 canvas_read。测：import server 断言 `OrderGuard/KeyBroker/place_order` 不可达+**不在 sys.modules**(镜 `test_realmoney_audit_killswitch` RULES.project.md:13)·注册表=={canvas_read}·变异让 server import main→红。
- **M2 canvas_read 端到端**（✅ **已建·commit 7e1dd20f**）：owner-scoped 真投影 + lineage edges。测：owner A/B 隔离·另进程 append 后 read 能见(refresh 生效)。**★ M2 落地校正**：原写「shape==前端契约」——**改为语义投影**（Inference·可翻案）。理由：前端 `_graph_canvas_projection`(main.py:15477) 产**像素布局节点**（x/y/w·ports·badge）供人看，且耦合 main.py 全局（L-B 不可 import）；嵌入 agent 的 LLM 要**语义内容**（type/owner/status/lineage/evidence）不要坐标。故 canvas_read 返 `{nodes[语义记录], edges[from/to/relation], count, edge_count}`·edges 限双端点在投影集内（owner 透传隔离）。跨厂商 codex SOUND（A-B/A-A/B-B 边隔离 probe）。
- **M3 claude 后端+spawn 契约**（✅ **已建·app/agent/backends/{base,claude_backend}.py**·纯 builder 不 spawn）：argv/env builder。`build_agent_argv`(stream-json+strict-mcp+add-dir+canvas MCP 工具+permission-mode)、`build_spawn_env`(L-C allowlist)、`build_mcp_config`、`preflight`。PermissionTier 用户可配。
  - **★ M3 落地校正——跨厂商 codex floor 3 轮逮真红线破口（强制复审的价值）**：①**prompt argv 注入**（R1·真红线破口）——prompt 作 argv 位置参数时 claude 2.1.210 把 `--mcp-config=/evil.json` 当**真 flag** 解析→绕 strict-mcp 注入恶意 venue-tool MCP server。修：**prompt 移出 argv 走 stdin**（`agent_prompt_via_stdin`）+ model dash-guard。②**preflight 假绿**（R1）——generic ready 认 API key 也 ready·但本后端走 CLI keychain 不递 API key。修：ready=cli_installed AND subscription_authed。③**外来 mcp__ + comma/space smuggling**（R1-R2）——allowed_tools 逐元素 filter 后 comma-join·但 claude 按 comma/space 重切→`"Bash,mcp__evil__x"`/`"Bash mcp__evil__x"` 走私外来 mcp。修：comma-split 后 **drop 含 `mcp__` 任意位置 token**（挡全分隔符·paren spec `Bash(git *)` 存活）。④去 NODE_OPTIONS/NODE_PATH（node code-injection 面）。**R3 判 FLOOR-HOLD**（comma/space/tab/newline smuggling 全挡·legit 工具存活·15 测 7 变异有牙）。**tier 放宽不破红线**结构性成立：strict-mcp 钉死+MCP server 只注册 canvas_read（M1 L-A）·widen tier 只加 CLI 工具不加 MCP 面。
- **M4 orchestrator+新路由**（✅ **M4a 已建·core**·route 留 M4b）：scripted/replay 后端驱动 SSE。
  - **★ M4a 落地**：`app/agent/backends/events.py`（BackendEvent 联合：SessionStarted/AssistantText/ToolCall/ToolResult/Done/BackendError + `backend_events_to_sse` 映**现有 SSE 词汇** say/tool_start/tool_end/done/error·run_id 顶提·纯函数）+ `scripted_backend.py`（ScriptedBackend 回放定序 BackendEvent·ready 开关驱动 not-ready 路径·无 subprocess）+ `session_orchestrator.py`（`SessionOrchestrator.stream_events/stream_sse`：preflight not-ready→**诚实 error 不 fallback 内部 agent**·backend.run()→映 SSE·`is_cross_process_write`→`refresh_store()` 令 canvas 写跨进程可见）。复用 workbench_stream.sse_format。
  - **对抗测试 8·2 变异有牙**（去 not-ready 门→假 fallback run 红·去 refresh hook→红）：帧含 tool_start/end、not-ready→error 且 run() 不被调（无 fallback）、owner 穿 run()、cross-process 写 refresh 恰一次、errored 写不 refresh、terminal done 补齐。
  - **M4b（下切）**：main.py 新路由 `GET /api/agent/session/stream`（镜 agent_workbench_stream:36060·owner 从 auth·TestClient e2e）+ claude stream-json→BackendEvent parser（真后端 run()）。诚实边界（not-fallback）跨厂商复审。
- **M5 canvas_create_node 写+跨进程写回**：测：真写(qro 存在·owner==QB_OWNER·OFFLINE)·**跨进程可见**(MCP 写→API refresh→projection 见)·owner 伪造被拒(`spine.py:1685`)·不能建 LIVE·漏 assumptions/failure_modes/validation_plan→`__post_init__` 拒。
- **M6 全链真 claude 冒烟+红线总断言(核心)**：本地真订阅 claude 跑「读画布+加假说节点」(GOAL §0 可证伪)。测：真(非 mock)claude 发两 tool_use·UI 见节点+文本·静默 mock fallback→拒·**money/venue/A股-live/testnet/mainnet 工具缺席**(`list_tools`=={canvas_read,canvas_create_node})·**tier 放最宽仍动不了钱**·spawn 契约守·订阅 token 不现于 mcp.json/SSE/日志/ledger。**加**：cancel/timeout/backpressure/concurrent-append(codex flag)。

## 6. 待拍板 + 新依赖 + 未验证边界
**新依赖(方向已批)**：官方 `mcp` SDK(PyPI `mcp`·modelcontextprotocol/python-sdk·MIT)。requirements.txt 现无 mcp/fastmcp(grep 确认)·落地钉版本。传输=stdio 独立进程(强化 L-B)。**build 时核实确切符号**(`mcp.server.fastmcp.FastMCP` 高层 vs 低层 `Server`+`stdio_server`+`list_tools/call_tool`)——RULES §3 未验证·勿凭记忆。
**待拍板(present·不 land)**：
1. **canvas_create_node 必填字段面**：QRORecord 强制 assumptions/known_limits/failure_modes/validation_plan 非空。agent 全供(真画布表意·门槛高·GOAL 对齐·**推荐**)vs 工具合成占位(门槛低·弱研究契约)——方法学松紧属用户那摊·摆代价请拍。
2. **跨进程可见接缝**：refresh-on-write(编排器内·推荐)vs projection 端点条件 refresh(兜底)。先上前者。
3. **前端 URL**：参数化复用 `agentLive` vs 新 `agentSession.ts` 兄弟(推荐扩展不替换)。
4. **★ 跨厂商复审(命门纪律)**：本稿红线 floor 3→2 层是安全相关·**落码前 parent 走 codex 跨厂商 skeptic 复审 floor**再 M1。
**未验证边界(只读·本 session)**：wiring file:line 采自真码·跨进程锁=真 flock·spine import 面无 execution·QRORecord 强制字段·无现存 create-fresh-canvas-node 端点·requirements 无 mcp。**未碰**：无凭据·未登录 vendor CLI·未 spawn 真 claude·未改文件。claude CLI 确切 flag 沿用上一稿 §6 `--help` 结论(本 session 未复跑)+ codex permission-mode 校正(build 时定值)。
