---
title: Claudian 式「每对话跨厂商切模型」——duet 裁决后实现蓝图
developer_id: dreaminate
date: 2026-07-15
status: adjudicated（待实现 · duet 三方并集）
goal_section: §4（Settings/LLM Gateway）
---

# 裁决来源
- 我的骨架 ‖ deep-opus（Agent）‖ codex（gpt-5.6-sol, xhigh, read-only）三方独立设计并集。
- 用户拍板决策（不重议）：① 每对话独立选模型（Claudian 式、无全局默认）② 动态拉厂商模型
  （api-key 真拉 `/v1/models`；订阅 CLI 无干净列模型命令→精选兜底）③ 前端内嵌订阅登录按钮。
- 简报原文：`$CLAUDE_JOB_DIR/tmp/model-switch-design-brief.md`（本机，不入仓）。

# 硬不变量（违一条即失败）
1. **dual-model 独立门不许被手选洗白**：手选 pin 只在 `RoleCapabilityRequest.independence_required==False`
   时生效；verifier/critic 永远自动异源指派、无 pin。隔离在 **role-node 级**（不只 endpoint），
   因 `orchestrator/task_router.py:190-203,242-268` 会从用户文字生成 verifier role。
   `independence_required=True + hard pin` = 非法状态，直接拒。
2. **deny-by-default 不弱化**：pin 不新增任何 provider 准入；订阅仅当 `subscription_auth_status()==True`
   才算 configured；全空仍 `NoLLMConfigured`；`dev_local` 三处拒不动。
3. **no-mixing**：anthropic 模型→anthropic 凭据、openai 模型→openai 凭据。pool_id==provider 保住；
   物化后、client_factory 前断言 `profile.provider == credential.provider`（`gateway.py:1100-1169`）。
4. **凭据零触碰**：登录中继只搬 URL 出 / device code 或 auth code 入；token 由厂商 CLI 自存，后端永不经手。

# codex 对抗复审逮到的关键修正（deep-opus + 我都漏，全部采纳）
- **K1 主链不走 GatewayBackedLLMClient**：真实路径 `main.py:35541 → _dispatch_production_agent_turn
  (main.py:5613-5685) → AgentOrchestrator → GatewayLLMAdapter(orchestrator/llm_adapter.py:78-107)`，
  adapter 也丢 model。→ pin 在 **gateway 构造期注入**（`build_agent_llm_gateway(default_pin=...)` ←
  `_current_agent_gateway(run_id, model_pin=...)`），在 `gateway.complete`（`gateway.py:427` 附近）
  盖章，覆盖 GatewayLLMAdapter + GatewayBackedLLMClient 两条路，不依赖 adapter 传 model。
- **K2 订阅-only 在 Settings preflight 就挂**：`_current_agent_gateway` 先调
  `make_settings_managed_llm_client`（`main.py:4997-5035`）→ 要求 api-key keystore
  （`llm_providers.py:728-824`）。只改 build_agent_llm_gateway 不够。**必须扩 Settings preflight
  验 subscription_cli 路由**（`llm_providers.py:502-630` 的 auth_methods/auth_refs/model_profiles 支持
  `subscription_cli`；auth ref 形如 `cliauthref://{provider}/current-machine`，不指 token 文件）。
- **K3 订阅 adapter 拒 tools，生产 role 传 tool schema**（`orchestrator.py:430-546`）：订阅模型只能
  **无工具通用对话**；带工具 turn pin 到订阅→capability error（绝不静默去 QuantBT tools 或改投 API）。
  目录里订阅 profile 标 `supports_tools=false`；workbench 里订阅项对带工具场景不可选。
  **Inference（待用户复核·可翻案）**：这是当前订阅 adapter 事实限制、非 UI 问题；要订阅也跑带工具
  agent，须先建「受治理的 subscription tool bridge」（另立卡，不在本特性 MVP）。
- **K4 `claude setup-token` 是错命令**：本机 claude 2.1.210 + 官方文档证实它生成长效
  `CLAUDE_CODE_OAUTH_TOKEN`，父 PTY 会读到→违反 K4 不变量。→ 改用 `claude auth login --claudeai`
  （若该版本要短期 authorization code 才前端回贴，token 仍 CLI 自存）；codex 用 `codex login --device-auth`
  （device flow，后端连 auth code 都不接、CLI 自轮询自存）。版本证明不了不输出 token → 停中继退手动。

# 其余采纳的 codex 加固
- **K5** 全局 `/api/llm/active`（`LLM_PROVIDER` 进程级）**前端已接**（`Shell.tsx:204-239`，简报说未接=错）。
  agent chat preflight 加 `honor_process_default=false`，把进程全局与「每对话 Auto/pin」解耦；不删端点（旧消费者）。
- **K6** 登录须 `_require_machine_llm_admin()`（`main.py:14055`）——机器级 CLI 凭据，普通用户不得覆盖全机账号。
- **K7** 订阅 subprocess 加固：prompt 走 stdin（非 argv）；子进程环境只留 PATH/HOME/CODEX_HOME/locale/TMPDIR，
  不继承 QuantBT/交易/API-key env；ephemeral（`--no-session-persistence` / `--ephemeral --ignore-user-config`）；
  temp dir 0700 / 输出 0600 / finally 删；stderr 只出类型化错误码、不原样进日志/API。
- **K8** selection digest 必须进 request claim / prompt digest（`gateway.py:673-686` 现缺 pin），否则同
  request_id 切模型后复用旧结果。
- **K9** Auto profile 与 pinnable 分离：`LLMModelProfile` 加 `auto_eligible`（`routing.py:56-70`）——
  配置默认模型 auto_eligible=true；会话 pin 的目录模型=临时 profile auto_eligible=false。Auto 只看 auto profiles。
- **K10** 手选持久化在 `chat_conversations.metadata`（`agent/conversations.py:25-38,85-96`；加 owner-scoped
  原子 metadata 更新，现只有 state/context 更新 `:178-223`）；服务端每次读 thread selection，**不信每条消息随手传的 model**。
  canonical：`llm_selection={mode:auto|pinned, provider?, model?, auth_kind?, catalog_revision?, updated_at?}`。
- **K11** 模型目录唯一源 `app/backend/app/llm/model_catalog.py`（新建）；订阅默认列表从
  `subscription_cli_llm.py:278-299` 挪来只此一份；`dual_model_review.py:219` 的 `_SUBSCRIPTION_MODELS` 也归并引用。
  live `/models` 返回非聊天模型→未知 capability 可展示但 `selectable=false`。TTL 300s / negative 15s /
  按 `(provider,auth_kind,redacted_base,config_rev)` 分桶 + single-flight；configure/revoke/登录成功即失效；
  禁 redirect、限 body、短 timeout、不缓存 header/key。

# 切片划分（各带对抗测试、独立过四门；单一写者=我；每片改动后全跑最低验证）
- **S1 纯 model catalog**：`model_catalog.py` + `GET /api/llm/models`（鉴权后，`main.py:14070` 附近）。
  fake HTTP transport；测：分页/非聊天模型 selectable=false/redirect+body-limit 拒/cache 失效/未认证零 live 请求/
  订阅 curated+source 标。**可与 S2 并行**。
- **S2 纯 hard-pin routing**：`RoleCapabilityRequest.required_provider/required_model/required_auth_kind`
  （与软 prefer_* 分开，`routing.py:73-84`）+ `resolve()` 在 tier/prefer/independence 之前处理 pin
  （`routing.py:173-267`：三字段全/精确命中同 route/profile.provider==pool cred provider/需 tools 而
  supports_tools=false 立拒/无命中→typed pin error）+ `auto_eligible`（K9）+ pin 的 fallback 集为空
  （`_refallback` `gateway.py:1214-1311` 对 pinned 终止为 `PinnedModelUnavailable`、不跨模型/厂商）。
  **变异门必红**：删精确 filter / 恢复跨 provider fallback / 交换 pool / `independence_required=True` 时 pin 生效。
  证明 Auto 接目录前后选择完全一致。
- **S3 conversation 持久化 + 主链传播**：metadata 原子更新 + selection API
  （`POST /api/agent/chat/start` 带初始 selection `main.py:40706`；`PATCH /api/agent/chat/{tid}/llm-selection`；
  bare `POST /api/agent/chat` 加 conversation_id `main.py:35529`；workbench SSE 加 conversation_id `main.py:35809`）+
  gateway 构造期注入 pin（K1）覆盖 GatewayLLMAdapter + GatewayBackedLLMClient + selection digest 进 claim（K8）。
  测：A/B 对话隔离、owner 隔离、Auto reset、stream/non-stream 一致、request-id 绑 pin digest。
- **S4 dual-model 隔离门**：pin 只进非 independence role（role-node 级 `roles.py:85-106`）；显式 review/fork
  路径无 pin（`main.py:35686-35745` + `model_identity.py:14-98` 跨厂商跨 family 门不变）。
  测：builder 被 pin、verifier 自动换厂商且不同 foundation family；**误把 pin 传 verifier 必红**；
  复用 `tests/test_llm_gateway.py:461-655` 独立性用例。
- **S5 订阅 gateway + adapter 加固**：Settings preflight 扩 subscription_cli 路由（K2，最关键）+
  `SecretRef.auth_kind="subscription_cli"`（`credential_pool.py:40-57`；materialize 不访 keystore 只产空 api_key+
  provider/model/auth_ref `:234-257`；has_usable_key 认 keyless-authenticated `:104-110`）+ client factory 加分支
  （`gateway.py:171-193`：subscription_cli→make_subscription_cli_client，不伪装 oauth_proxy/custom）+
  subprocess 加固（K7）+ 订阅 profile supports_tools=false（K3）。
  测：logged-out 不建 profile / logged-in subscription-only 可建路由调 CLI（mock subprocess）/ 无 dev_local /
  prompt 不在 argv / secret env 不进子进程 / tools 明确拒且不 fallback / 四家全空仍 NoLLMConfigured。
- **S6 登录 state machine**（**参考实现见 [[model-switch-reference-impls-20260715]]**：采 Hermes session-relay REST
  骨架[verifier/token 全留服务端] + OpenClaw VPS-aware 贴码兜远程；**不采指纹直连**[ToS 红线，签名计费绕过=
  计费规避，只学不落地]；OAuth 常量[client_id/端点/端口 53692]已核实可复用但版本号是移动靶别写死）：
  `app/backend/app/llm/subscription_login.py` + `POST /api/llm/subscription/login/{provider}`
  （action: start/poll/submit_code/cancel；`_require_machine_llm_admin` K6；PTY/process group；每 provider 一 flow；
  TTL 5min；只回 login_url/user_code/status/error_code、绝不回 raw stdout/stderr；unknown prompt/版本不在
  allowlist/token-shaped output→杀 process group 降级；成功唯一证明=重跑 subscription_auth_status==True；
  完成失效 auth/catalog/gateway cache）。Claude=`claude auth login --claudeai`，Codex=`codex login --device-auth`（K4）。
  全 fake PTY fixture、不跑真登录。测：Claude URL/code、Codex device flow、timeout/cancel、版本漂移、
  token-shaped output kill、raw-output mutation gate。
- **S7 前端**：workbench selector（`AgentWorkbenchPage.tsx` + `agentLive.ts`；进入建/恢复 conversation_id；
  消费 `GET /api/llm/models`；当前选择读 thread `metadata.llm_selection`；切换 `PATCH .../llm-selection`；
  SSE 带 conversation_id；按 provider 分组标 live/curated+API/订阅+tools capability；auth 失效当前选择变红、
  下条消息前要求改选或切 Auto、不自动切别家；verifier 事件显实际自动 provider 但 selector 仍显「本对话通用模型」）+
  Settings 卡（`LLMSettingsPage.tsx` 扩，不替换 api-key 表单；登录按钮调 S6 state machine；仅 machine admin 可点）+
  移除/降级全局 selector 对 chat 的影响（K5）。扩 `LLMSettingsPage.test.tsx`/`Mode2ChatPage.test.tsx`+新 workbench selector 测试。

**顺序**：S1（∥S2）→ S3 → S4 → S5 → S6 → S7。S1/S2 是不变量地基先行；S6 最脆末位（有手动兜底）。

# 风险 · 单一最脆子项
- **单一最脆 = S5/S6 订阅 CLI subprocess 边界**：厂商 CLI 输出/参数随版本漂移、setup-token 与零 token 矛盾（已 K4 规避）、
  codex loopback 受网络拓扑影响、CLI 自带 tools 不受 QuantBT ledger 管、当前 adapter 不支持 QuantBT tools。
  **未满足三条前订阅模型不标 workbench 可选**：① 登录命令经版本门证明不向父进程输出 token ② inference 子进程
  无法读 checkout/继承业务 secret/执行未记账工具 ③ 带工具 turn 有明确能力拒绝或受治理 tool bridge。
- 其余：live `/models`≠chat-capable（保守标 selectable）；动态 catalog 与 Settings allowed_models 须同 revision 绑定；
  全局 LLM_PROVIDER 未剥离会暗破「无全局默认」（K5）。
