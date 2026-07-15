# 订阅账号 in-app 认证（S6 落地）— 2026-07-15

> 归属 slice：跨厂商切模型伞卡（db95c0c6）。本篇是 [[model-switch-crossvendor-design-20260715]] 里
> **S6（in-app 订阅登录 relay）** 的实现记录 + 陌生用户 onboarding 流程。设计源、K1–K11 见该蓝图。

## 一句话
让陌生用户在**应用里**（不用只靠终端）用 Claude Pro/Max / ChatGPT Plus/Pro 订阅账号登录，接上正经模型。
承重机制 = **状态检测 + 轮询**；登录 spawn 是便利、诚实降级到终端命令。**后端全程不碰 token**。

## 落地面（extend 不 replace）
- `app/backend/app/agent/subscription_cli_llm.py`
  - `_CLI_META[...]["login_cmd"]` = 登录命令**单一源**（in-app relay 与 `scripts/llm_auth.py` 共用，不漂）。
  - `begin_subscription_login(provider, *, spawn=None)`：allowlist 校验 provider → 未装回 install 引导 →
    装了则 `_spawn_detached_login(login_cmd)`。返回体**只含流程信息**（launched/cli/guided_command），无凭据字段。
  - `_spawn_detached_login`：`Popen(stdin/stdout/stderr=DEVNULL, start_new_session=True)`——不捕获、不 wait。
    这是「后端不碰 token」边界的落点。
- `app/backend/app/main.py`
  - `GET /api/llm/providers/auth`：逐 provider 认证画像（实时探测，不吃 60s 缓存）。机器级 admin gated。
  - `POST /api/llm/subscription/login/{provider}`：登录 relay。机器级 admin gated；launched 后清目录缓存。
- `app/frontend/src/pages/LLMSettingsPage.tsx`：订阅登录面板（`data-subscription-auth-panel`）——
  逐 provider 卡（CLI 已装/订阅登录/API key 状态）+『登录订阅账号』按钮（POST→轮询状态转绿）+ 终端降级命令。

## 关键设计判定
1. **为什么 detached-spawn + 轮询，不做有状态 relay**：跨 HTTP 请求管理交互登录子进程的生命周期（codex 标的
   最脆点）整个避开。后端起完就忘；`claude auth status` / `codex login status` 是另起的新子进程读 CLI keychain，
   登录后一次轮询即反映新态，无需重启后端。
2. **K4 修正（已完成，全仓一致）**：登录一律走 `claude auth login --claudeai`（浏览器→keychain），
   **禁 `claude setup-token`**（把长效 token 打到 stdout=泄漏面）。清干净了：in-app relay、`scripts/llm_auth.py`、
   adapter docstring/错误、`docs/llm-auth-quickstart.md`。仓内剩余 setup-token 全是「别用它」的警示。
3. **诚实降级（OpenClaw VPS-aware 精神）**：本地能弹浏览器→一键；弹不出（headless/无桌面）→ guided_command
   始终给出可在终端直接跑的命令。承重的是状态检测 + 轮询，不是 spawn。
4. **诚实边界（§3 不假绿灯）**：`subscription_auth_status` 只解析 `loggedIn`/`authMethod`（claude JSON）、
   `logged in` 文本（codex），绝不读 token；未登录不会被误判为已登录。

## 仍开的约束（不属本 slice，登记）
- **K3**：订阅模型带 tool 的 agent 流跑不了（订阅 CLI 拒 tools）——订阅目前只用于免工具场景
  （dual-model 复审 / 免工具对话）。主 agent 聊天要正经模型仍走 **API key** 线。前端面板已如实标注。
  订阅接进带工具主流程需要 tool bridge（待拍板：桥 or 免工具模式），另开 slice。

## 陌生用户 onboarding 流程（把我当第一次用的）
1. 打开应用 →「模型连接配置」页（`/settings/llm`）。
2. 顶部「订阅账号登录」面板：看到 anthropic / openai 两张卡的状态（CLI 已装？订阅登录？API key？）。
3. CLI 没装 → 卡里直接给 `npm install -g ...` 命令；装完点『刷新』。
4. 点『登录订阅账号』→ 浏览器弹出厂商登录页 → 登入订阅账号 → 面板轮询到「已登录」自动转绿。
   浏览器没弹（远程环境）→ 复制卡里的 `claude auth login --claudeai` / `codex login` 到终端跑，再『刷新』。
5. 也可完全走终端：`python scripts/llm_auth.py status|login <p>|verify`。
6. 登录后可在对话切到该厂商模型（免工具场景）；要带工具的 agent 流则配 API key（同页下方表单）。

## 验证
- 后端 `test_subscription_cli_llm.py`（relay + K4 + 安全门）、`test_llm_custom_and_api.py`（端点 admin gated + argv + 缓存失效）；
  前端 `LLMSettingsPage.test.tsx`（面板渲染 + 点登录 POST 正确端点、请求无凭据）。
- 承重安全门变异测试：把 `_spawn_detached_login` 的 `stdout=DEVNULL` 改 `PIPE` → `test_spawn_detached_never_captures_output` 立即打红（已实测 -1≠-3）。
