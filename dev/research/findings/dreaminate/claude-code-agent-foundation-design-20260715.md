# Claude-Code 式内嵌量化 agent — 基础 + 第一薄纵切 设计（deep-opus，待跨厂商复审 + 用户拍板）2026-07-15

> 状态：**设计定稿、零代码落地**。含 blocking [需拍板]（尤其 fork2 安全命门）——[[openclaw-agent-epic-alignment-20260715]]
> line 47「不在用户拍 fork2 前落任何 agent-workspace 执行代码」。本篇是那个 fork2 答案的**提案**，须**跨厂商 codex 复审**
> （safety 命门 + 单厂商设计=本 session dual-model binding 教训）+ 用户拍板后才落码。全部 file:line 采自真实代码。

## 0. AgentBackend 抽象（新兄弟模块，非扩 subscription_cli_llm）
`subscription_cli_llm.ClaudeSubscriptionLLM.chat`(:287) 是**一次性文本补全且显式拒 tools**(:295)——epic 要 **agentic 模式**
（CLI 跑自己的 tool 循环+MCP），语义不同→新抽象（RULES §4 扩展不替换），但**复用**其 auth 机器（`provider_auth_report`:131、
`cli_installed`:60、token 不出进程边界 :191-198/303）。位置建议 `app/backend/app/agent/backends/`。
- `PermissionTier`（restricted 默认只读 MCP/无 Bash·standard·trusted 更广但仍 strict-mcp+floor+无 --dangerously-*）；
  `BackendEvent`（归一化 union：session_started/text/tool_call/tool_result/error/done + raw 审计用无密钥）；
  `AgentBackend` Protocol（`preflight()→BackendReadiness`；`run(task,workspace,tier,mcp_config,allowed_tools,timeout)→Iterator[BackendEvent]`）。
- **三后端 CLI 映射（flag 均已 --help 核实）**：
  - **claude v2.1.210（薄片选它·最易）**：`claude -p "<task>" --output-format stream-json --verbose --mcp-config <s>.mcp.json
    --strict-mcp-config --permission-mode default --allowedTools mcp__quantbt__canvas_read --add-dir <throwaway_ws>`。
    MCP 工具名确定式 `mcp__<server>__<tool>`；parser 须容忍/跳过 `type:"system"`/hook 行（dry-run 实测 stream-json 无 --verbose 也接受、
    但防御性带上）；`assistant`→text+tool_use、`user`→tool_result、`result`→done。
  - **codex 0.144.1（可行·后延）**：`exec` headless + `mcp`/`mcp-server` + `-s sandbox` + `-c mcp_servers.<n>.command=` 注入
    （无 ad-hoc --mcp-config；走 per-invocation -c 覆盖不改全局 config.toml）。exec JSON event schema **未核，落地时验**。
  - **opencode 1.17.12（可行·后延）**：`run`/`serve`/`acp`（ACP 标准事件协议，日后可替 stdout 解析）/`mcp`（`opencode.json` 配）。
  - codex/opencode 先只出 `preflight()`（就绪汇报），`run()` raise NotImplementedError（诚实·无静默 fallback）。

## 1. QuantBT MCP server + 唯一薄片工具 + 红线 floor（命门）
位置建议 `app/backend/app/agent/mcp/`（server/tools/red_line）。
- **薄片唯一工具 `canvas_read`（只读·side_effect=none）**：读**规范单一源**不另造——`RESEARCH_GRAPH_STORE`
  (`main.py:775`) + 已有 `_graph_canvas_projection`(`main.py:15470`) / `GET /api/research-os/graph/canvas_projection`
  (`main.py:15556`)，owner-scoped，返回前端已消费的同 shape。
- **红线 floor 结构性不可绕（三层+spawn 契约，镜 `security/gate/enforcer.py` OrderGuard 命门 :1-7/103-106/120-121）**：
  - **L0 架构级无钥（最强）**：MCP server 进程 import 图**排除** `place_order`/`OrderGuard`/`KeyBroker`/`execution/*`/
    `trading_credentials`——**拿不到 venue key 因为那些码不在进程里**（= enforcer「key 只在 S4 过门后取」）。测试 import server
    模块断言这些符号不可达（镜 `test_realmoney_audit_killswitch`，RULES.project.md:13）。
  - **L1 正向注册·危险工具根本不存在**：硬编码 allowlist（薄片={canvas_read}）；动钱/venue/A股-live/testnet/mainnet 工具**不注册**
    （= 内部 agent「动钱/晋级工具根本未注册」`main.py:35961`）。没广告的工具调不了。
  - **L2 参数无条件拒 guard**：每次 dispatch 先跑 `red_line.check(tool,args,tier)`，args 触 real money/real venue/A股 live/
    testnet/mainnet → `raise RedLineRefused`（→MCP isError），**无视 tier**（比 D-PERM `agent_runtime.py:138` 更严=无条件拒非确认）。
    tier 只能收窄不能放宽。
  - **spawn 契约（封 agent 自带工具那条道）**：`--strict-mcp-config`（忽略用户 ~/.claude MCP）、`--allowedTools` 排除 Bash/Write/
    Edit/WebFetch、**绝不** --dangerously-skip-permissions、`--add-dir`→throwaway workspace（非仓库）、spawn env 洗掉 venue creds。
  - **诚实限界（RULES §3）**：L0-2 让「经我方工具」动钱/venue **无条件·结构性**不可达；agent 自带 bash/write 那条道 (b) 是**配置不变量**
    （spawn 契约·测试守·防御纵深），**不是** L0 级不可能——**这正是 fork2 要用户拍的**。

## 2. 编排 seam（file:line）
新兄弟 `app/backend/app/agent/session_orchestrator.py`（非改现有 `orchestrator/orchestrator.py`——那驱动内部 role agent 经
gateway，本 epic 驱动外部 CLI agent 跑自己循环）。流程：preflight 后端(`provider_auth_report`:131,未 auth 诚实错·无 fallback)→
建 throwaway workspace + 写 `<s>.mcp.json`(env 带 QB_OWNER/QB_TIER/短 TTL cap token·**绝无订阅 token**)→ `backend.run(...)`→
**BackendEvent 映射到现有 SSE 词汇**(`workbench_stream.py:sse_format`:163 / project_turn_events:108 的 tool_start/tool_end/say/
gate/done/error)→ 前端 `agentLive.ts` 不改照渲染 → 跑在 `start_background_workflow`(:45) 里。新路由 `GET /api/agent/session/stream`
（镜 `agent_workbench_stream` `main.py:35943`·同 require_user_dependency+owner scoping·**不碰** `_dispatch_production_agent_turn`:5618）。
**画布渲染 seam**：`canvas_read` 的 tool_end payload = ResearchGraphCanvasProjection → `StrategyConsolePage.tsx`(nodes/edges
useState:208-209·fetchProjection:74·toNodeView:131-177·`<GraphCanvas>`:64) onToolEnd 推同 mapper→setNodes/setEdges。

## 3. 薄纵切 scope + 验收 + 对抗测试
- **scope**：app 里用户「读当前研究图画布并总结」→ `GET /api/agent/session/stream?backend=claude&tier=restricted` → 起**真·headless
  订阅 claude**（strict spawn 契约 + --mcp-config 我方 stdio MCP·只 canvas_read）→ claude 发 `mcp__quantbt__canvas_read` tool_use →
  server 返 owner-scoped 规范 projection → 编排流 tool_start/tool_end/say/done → 结果渲染到现有 GraphCanvas。
- **验收（可证伪·GOAL §0 line54）**：真（非 mock）订阅 claude 发该 tool_use；SSE 有 tool_start/end；UI 见节点+文本；静默 mock fallback→拒。
  backend=claude 起 claude；未 auth/未知后端→诚实就绪错·**不** fallback 内部 agent。订阅 token 不现于 mcp-config/SSE/日志/ledger。
- **对抗测试（种坏门必抓·变异必红）**：①**红线 floor bypass（核心）**：注册假 `place_live_order` 或 args 选 venue=binance_um/mode=live/
  A股+live/testnet/mainnet → MCP isError（RedLineRefused）先于任何效果；变异 red_line.check 放行→测试必红。②**tier 不能放宽 floor**：
  tier=trusted（甚至试 --dangerously-skip-permissions）→ floor 仍拒（权限轴⊥安全 floor）。③**L0 无钥**：import server 断言 OrderGuard/
  KeyBroker/place_order/venue-client 不可达。④**spawn 契约**：单测 argv/env builder，变异加 Bash 进 allowedTools / 掉 --strict-mcp-config /
  注 venue env → 断言必红。⑤**假后端·无静默 fallback**：backend=codex 未 auth → 诚实错·绝不 claude/内部 agent。

## 4. 融合计划（OpenClaw/Hermes·MIT 已核 [[model-switch-reference-impls-20260715]] :10-21）
OpenClaw `@13c7cf45` MIT ✅ / Hermes MIT ✅ / `openclaw-plugin-claude-code` Apache-2.0 ✅(留 NOTICE) / `openclaw-stack` **BSL-1.1 ⛔**(仅 docs)。
按本仓架构重实现+注释记来源(RULES §1/§4)：OpenClaw「CLI 当完整 agent·我方编排+绑 workspace↔canvas」→ AgentBackend+session_orchestrator；
`openclaw-plugin-claude-code` stream-json→tool_use/result 映射 → claude 解析器(Apache,留 NOTICE)；Hermes loop/event-projection shape →
BackendEvent 归一化参考（SSE 词汇仍我方）；OpenClaw remote-env VPS-aware spawn → 后延。⛔排除 openclaw-stack(BSL) + 指纹直连/签名计费绕过(ToS 红线)。

## 5. [需拍板]（present·不 land）
1. **fork2 安全命门批准（blocking）**：L0-2 floor+spawn 契约=提案，用户须批准才落 spawn/执行码。
2. **新 MCP 依赖+传输**：官方 `mcp` SDK（推·MIT）vs FastMCP（MIT）vs 自建 stdio JSON-RPC（无依赖）；传输 stdio-独立进程（推·强化 L0 无钥）
   vs HTTP-in-FastAPI（简单但 MCP dispatch 与能碰 place_order 的进程同域→L0 塌成 L2 独扛）。新依赖=项目拍板。
3. **ToS（fork5）**：坚持 CLI-subprocess（推），不碰指纹/计费绕过。
4. **薄片面**：只读 canvas_read（推）vs 含 canvas_create_node（图写·更大面·behind floor+fork2·建议后延）。
5. **新路由** `/api/agent/session/stream`（推·扩展不替换）vs 现有 workbench 路由加 mode flag。

## 6. 验证边界（RULES §3）
**已核（只读）**：三 CLI 装+确切 flag（claude 2.1.210/codex 0.144.1/opencode 1.17.12）；一次 claude arg dry-run（stream-json 无 --verbose 也接受·
出 system/hook 行）；全 wiring file:line 采自真码；requirements.txt 无 mcp(grep)。**待落地确认**：codex exec JSON schema + -c mcp_servers 注入；
opencode MCP/ACP event shape；真（非空）claude turn 下 per-tool 事件是否需 --verbose（防御性带）。**未碰**：无凭据/无 vendor 登录/无改文件。
