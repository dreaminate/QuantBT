---
uuid: db95c0c6251f44d0b9efaea4d2fddabd  # 全 32 位 hex 无连字符;生成:python -c "import uuid;print(uuid.uuid4().hex)"(或直接 os.py mint 全自动)
title: Claudian 式每对话跨厂商切模型——模型目录+hard-pin 路由+订阅接 gateway+内嵌登录+前端切换器(S1~S7)
status: in_progress  # todo | in_progress | done
owner: dreaminate  # wait(在 pool) | <developer_id>;须 == 所在文件夹(validate 校验一致;os.py assign 两处同改)
assigned_by: dreaminate  # 分配者 developer_id(leader/admin);pool 中留空
review_status: 1 # 被分配者 self-review:0 未过目 | 1 已过目/确认
priority: P1  # P0 最高 … P3 最低
area: platform  # 功能域 slug,须已在 ../_areas.md 注册(语法 ^[a-z0-9_-]+(/[a-z0-9_-]+)?$;validate 校验)
source: interaction  # research | goal | interaction(三晋升源出身)
source_ref: 用户 PIVOT:每对话选模型/动态拉/内嵌订阅登录;设计 duet 裁决 findings/dreaminate/model-switch-crossvendor-design-20260715.md  # 溯源句柄:finding 路径 / GOAL §x / 对话
goal_section: §4  # 服务 GOAL 哪个子系统节(如 §3);build_trace.py 据此聚合覆盖,可空
done_at:         # 落档日期 YYYY-MM-DD(os.py done 自动填;归档按它分季)
depends_on: []   # 上游卡 uuid 列表(全 32 位)= DAG 的边;os.py mint --depends-on 可用 uuid8 前缀自动解析
---

# Claudian 式每对话跨厂商切模型——模型目录+hard-pin 路由+订阅接 gateway+内嵌登录+前端切换器(S1~S7)

## Scope [必填]
做:用户在每个对话里独立挑一个已 auth 厂商的模型(anthropic/openai),该对话通用 agent 就用它;
动态拉厂商可用模型(api-key 真拉、订阅精选兜底);订阅账号经厂商 CLI 接进 gateway 可用;前端内嵌订阅登录。
不做:全局默认模型;订阅模型跑带工具 agentic turn(当前 adapter 拒 tools=K3,须另立「受治理 tool bridge」卡);
不碰 dual-model 独立审查门(手选永不作用于 verifier)。

## 上下文 / 动机 [按需]
用户 PIVOT 要 Claudian 式跨厂商切模型。**完整实现蓝图(三方 duet 裁决 + codex 对抗复审 4 关键修正)在
`dev/research/findings/dreaminate/model-switch-crossvendor-design-20260715.md`——本卡只做追踪,实现一切以该 finding 为准。**

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/llm/model_catalog.py | 新建 | 唯一模型目录源(S1) |
| app/backend/app/main.py | :14070 附近 / :35529 / :40706 | GET /api/llm/models、chat 传 conversation_id/selection、PATCH llm-selection(S1/S3) |
| app/backend/app/llm/routing.py | :56-70 / :73-84 / :173-267 | auto_eligible + required_* hard pin + resolve 优先处理 pin(S2) |
| app/backend/app/llm/gateway.py | :171-193 / :427 / :1214-1311 | client factory 加 subscription_cli 分支、complete 盖 default_pin、refallback 对 pinned 不跨厂商(K1/S2/S5) |
| app/backend/app/agent/orchestrator/llm_adapter.py | :78-107 | 真实主链 adapter(pin 靠 gateway 构造注入覆盖，不改此处丢 model)(K1) |
| app/backend/app/agent/llm_providers.py | :502-630 / :728-824 | Settings preflight 扩 subscription_cli 路由(K2 最关键) |
| app/backend/app/llm/credential_pool.py | :40-57 / :104-110 / :234-257 | SecretRef.auth_kind=subscription_cli、has_usable_key 认 keyless-authed、materialize 不访 keystore(S5) |
| app/backend/app/agent/subscription_cli_llm.py | :36-51 / :183-213 | subprocess 加固(stdin/最小 env/ephemeral)+ supports_tools=false(K3/K7) |
| app/backend/app/llm/subscription_login.py | 新建 | 登录 state machine(K4:claude auth login --claudeai / codex login --device-auth)(S6) |
| app/backend/app/agent/conversations.py | :25-38 / :178-223 | metadata.llm_selection owner-scoped 原子更新(K10) |
| app/frontend/src/pages/workshop/agent-workbench/* + LLMSettingsPage.tsx | selector/Settings 卡 | 前端切换器 + 登录 + 解耦全局 selector(K5/S7) |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. **pin 洗白 dual 门**:`independence_required=True` 时置 hard pin → 门必令 pin 被忽略、verifier 仍自动异源(误接则红)。
2. **跨厂商静默 fallback**:pin 厂商调用失败 → 门必终止为 PinnedModelUnavailable、**绝不换厂商**(恢复跨 provider fallback 必红)。
3. **no-mix 破坏**:交换 pool_id / profile.provider≠cred.provider → 物化前断言必拒。
4. **deny-by-default 弱化**:未登录订阅厂商 → 不得 register profile;四家全空 → 仍 NoLLMConfigured;dev_local 仍拒。
5. **凭据泄漏**:登录中继响应体/日志出现 token 形状串 → 测试必红;prompt 出现在 argv、业务 secret 进子进程 env → 必红。
6. **订阅跑带工具**:带 tool schema 的 turn pin 到订阅模型 → 必返 capability error(静默去 tools 或改投 API 必红)。
7. **Auto 回归**:接目录前后 Auto(无 pin)选择完全一致。

## 复用 [按需]
subscription_cli_llm.py(adapter+auth 探测,已落 origin/main)、model_identity.py 跨厂商 family 判定、
routing.py 现有 prefer_*/independence_required、credential_pool pool_id 隔离、auth_status_all。

## 红线 [按需]
dual-model builder≠verifier 不同厂商不许洗白;凭据零触碰;deny-by-default 不弱化;no-mixing;不破后端 6380 基线。

## 非目标 [按需]
订阅模型跑带工具 agentic turn(K3,另立卡);全局默认模型;同厂商 api-key+订阅双 pool 并选(MVP 用 api-key 优先单路由)。

## 验收一句话 [必填]
S1~S7 各自:种上述对应对抗测试的已知坏 → 门必抓;每片改动后后端全量绿(≥6380 基线)+validate_dev PASS+
GOAL 零 diff;dual-model 独立门与凭据零触碰不变量在变异测试下不可绕过。
