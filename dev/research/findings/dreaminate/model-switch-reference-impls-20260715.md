---
title: 参考实现调研——Claudian / Hermes / OpenClaw 的订阅 auth + 切模型（面向 S6 内嵌登录中继）
developer_id: dreaminate
date: 2026-07-15
status: 调研完成（用户指定参考源码；供 S4/S6 融合 + 一条 ToS 待拍板）
goal_section: §4（Settings/LLM Gateway）
source: interaction（用户:「去看 Claudian/Hermes/OpenClaw 源码参考修改」）
---

# license 总表（全部核实过 LICENSE 原文）
| 仓 | URL | License | 可用性 |
|---|---|---|---|
| Claudian | github.com/YishenTu/claudian @852b9708 | MIT | ✅ 可融合 |
| Hermes | github.com/NousResearch/hermes-agent | MIT | ✅ 可融合 |
| hermes-claude-auth | github.com/kristianvast/hermes-claude-auth | MIT | ⚠️ 代码 MIT，但机制=ToS 红线（见下） |
| OpenClaw | github.com/openclaw/openclaw @13c7cf45 | MIT（+THIRD_PARTY_NOTICES） | ✅ 可融合 |
| claw-orchestrator | github.com/Enderfga/claw-orchestrator | MIT | ✅ |
| 13rac1/openclaw-plugin-claude-code | — | Apache-2.0 | ✅（留 NOTICE） |
| simple10/openclaw-stack | — | **BSL 1.1**（2030 前禁生产） | ⛔ 只读 docs，代码不入库 |

**结论:要借鉴的代码全 MIT/Apache,无 GPL/AGPL。唯一「只能学不能抄」是 ToS 问题不是许可问题。**

# 核心发现:HTTP 400 根因被证否一半
QuantBT 此前记「sk-ant-oat 直连 Messages API 被拒(400)→必须走 CLI 子进程」。**后半句被 OpenClaw+Hermes 两套独立源码证否**:它们直连 `api.anthropic.com/v1/messages`,靠模仿 Claude Code 指纹让 OAuth token 被接受。400 真因=裸 token 缺这几层（三仓交叉印证）:
1. Bearer(`authToken`)而非 x-api-key（OpenClaw `packages/ai/src/providers/anthropic.ts:1092-1114`;Hermes `agent/anthropic_adapter.py:813-823`）
2. `anthropic-beta: claude-code-20250219,oauth-2025-04-20`
3. UA `claude-cli/<ver>` + `x-app: cli`（OpenClaw `:116`）
4. 强制 system[0] 身份块 `"You are Claude Code, Anthropic's official CLI for Claude."`（OpenClaw `:1530-1552`）
5. **（2026-04-04 后）签名计费头** `x-anthropic-billing-header: cc_version=<v>.<sig>;...`,`sig=SHA256(salt+msg_chars[4,7,20]+ver)[:3]`,**salt `59cf53e54c78` 从 CLI 二进制抠**（hermes-claude-auth `anthropic_billing_bypass.py:192-197,353-381`）

# 🔴 ToS 红线（学原理·绝不落地 QuantBT）
- **第 5 层签名计费头绕过=计费规避**:伪造官方 CLI 指纹走订阅额度而非按量,是 Anthropic 2026-04-04 新增「拒第三方工具」校验的绕过,salt/格式被反复 rotate（该仓 issue 里 bypass 反复失效）。**踩 ToS 红线 + 脆弱不可维护,与「机构级严谨」冲突。**
- **第 1-4 层基础指纹**灰度稍浅但本质仍是「冒充官方客户端直连」,随时可判第三方。
- **裁定（Inference,登记待用户拍板）**:QuantBT **默认走厂商 CLI 子进程**（Claudian 零托管模式,ToS 最稳,=当前 subscription_cli_llm.py 已做的）。**直连指纹方案（含签名绕过）只作「用户自担风险」高阶开关,摆明代价、非默认、绝不抄 salt。** 见 [[model-switch-crossvendor-design]] S5/S6。

# 三种架构立场（S6 选型核心）
| | token 处置 | 内嵌登录 | S6 适配 |
|---|---|---|---|
| Claudian | **完全不碰**:spawn CLI 子进程、继承 env、CLI 自持 | **无**（甩用户终端） | 给零托管骨架,不给登录中继 |
| OpenClaw | 后端持 token 直连（模仿指纹） | 有:VPS-aware 贴 redirect-URL 中继 | 给 paste 中继 + 400 修法 |
| Hermes | 后端持 token 直连 + 可选补丁 | **有:session-relay REST（verifier/token 全留服务端）** | **最贴 S6** |

**真·工程取舍**:「后端零托管」(Claudian:但无 app 内登录) vs「app 内登录顺滑」(Hermes/OpenClaw:但 gateway 持 token——直连结构上必须)。二者不可兼得。

# S6 内嵌登录中继:3 个可融合做法（保留 MIT notice）
1. **Hermes session-relay REST（首选骨架,客户端 UI 永不碰 token）**:后端 `start`（生成+暂存 code_verifier,返回 `{session_id, flow, auth_url}`）→ 客户端只开 URL + 轮询 `poll/{session_id}`（device）或贴 `code` 走 `submit`（pkce）→ 后端做 token 交换/落盘。verifier+token 全留服务端,session 内存 15min TTL、结构无 token 字段。源 `hermes_cli/web_server.py:8681-8840,9542-9627`。
2. **OpenClaw VPS-aware「本机浏览器→贴 redirect URL」中继（兜远程部署,backend≠浏览器同机）**:检测远程环境（SSH/容器/无 DISPLAY）→ 用户在自己浏览器登录 → 后端只解析贴回的 redirect URL/`code#state`/裸 code + 严格校验 state;本地则回环 `127.0.0.1:53692/callback`。源 `src/plugins/provider-oauth-flow.ts:11-60` + `remote-env.ts:6-24`。
3. **裸 token 挡在后端外**:拆「设备/会话 token」与「provider 凭据」;优先引用宿主 CLI 存储（`~/.claude/.credentials.json` / macOS Keychain `"Claude Code-credentials"`）而非自存;非自有 secret 落盘脱敏 `sha256:<fp>`（Hermes `credential_persistence.py:151-174`）。

# 可复用常量（三源交叉印证·高置信;版本号是移动靶别写死）
- Claude Code OAuth:`client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e`,authorize `https://claude.ai/oauth/authorize`,token `https://platform.claude.com/v1/oauth/token`（回落 console.anthropic.com）,回环端口 `53692`,scope 含 `user:inference`/`user:sessions:claude_code`,PKCE S256。
- Codex OAuth:`client_id=app_EMoamEEZ73f0CkXaXp7hrann`,token `https://auth.openai.com/oauth/token`,device 页 `https://auth.openai.com/codex/device`。
- 凭据双读点:macOS Keychain `"Claude Code-credentials"` + `~/.claude/.credentials.json`（`claudeAiOauth.{accessToken,refreshToken,expiresAt}`）。

# 对 QuantBT 现状的校正
- 当前 `subscription_cli_llm.py`（`claude -p` / `codex exec` 子进程）= Claudian 零托管模式,**是 ToS 最稳的推理路径,保持**。
- S6 内嵌登录:采 Hermes session-relay 骨架 + OpenClaw VPS-aware 贴码兜远程,**不采指纹直连**（除非用户拍板开高阶开关）。这样「app 内能登录」又不落 ToS 灰区。
- 模型目录/路由:三仓都是「一方厂商硬编 + 聚合动态拉 + 前缀命名路由 + 逐对话 override」——与我们 S1（model_catalog 动态拉+curated）、S2（pin）、S3（per-conversation）方向一致,印证设计。

# 验证边界（RULES §3）
license 原文、hermes-claude-auth 全文、opencode-claude-auth credentials.ts、openclaw LICENSE+NOTICES 均 `gh api` 拉原始字节亲验;逐行引用来自 3 个子探子（均 gh api 非 WebSearch 摘要）。落地任一条前对该 pinned commit 具体行再复核（指纹类变动快）。纯调研,未改任何文件。
