---
uuid: 640b66a0cfb44c3295b2fa8cf57a3568
title: LLM Gateway——唯一调用入口 + ModelRoutingPolicy(混合自适应) + CredentialPool + LLMCallRecord（A-AGENT-GW）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: llm-gateway
source: goal
source_ref: GOAL §7 Agent Shell(Orchestrator→LLM Gateway/ModelRoutingPolicy→role dispatch·role agent 绝不直接调 provider/读 key)·§1(LLMProvider/Auth/CredentialPool/ModelProfile/ModelRoutingPolicy/LLMCallRecord/ProviderHealth/QuotaStatus 对象)·决策 D-LLM-ROUTING(混合自适应)
depends_on: []
---

# LLM Gateway（A-AGENT-GW·LINE-A-AGENT 开局·另一最强瓶颈）

## Scope [必填·先读 GOAL §7+§1]
全仓 LLM 调用散落（agent/llm_client.py 直调），无治理层。本卡建 **LLM Gateway**——§7「Agent Orchestrator→LLM Gateway→role dispatch」唯一调用入口：① **Gateway**（所有 LLM 调用单一入口·role agent 绝不直接调 provider SDK/读 key·只拿结果+LLMCallRecord）② **ModelRoutingPolicy**（按 D-LLM-ROUTING **混合自适应**·按 role 能力需求/任务难度/风险/replay 要求选 provider/model/credential_pool·可配·绝不静默降质难任务）③ **LLMCredentialPool**（明文 key/OAuth/token 只在 Settings/Secrets 安全后端·Gateway 只持 SecretRef 引用）④ **LLMCallRecord**（provider/model/auth_ref/replay_state·可审计·进 RDP）⑤ ProviderHealth/QuotaStatus + fallback。**wrap 现有 `agent/llm_client.py`（不重建·它成 Gateway 后端一个 provider adapter）**。Orchestrator + 12 role + 23 事件投影 = 另卡（本卡只 Gateway 核 + 路由 + 凭据池 + 调用账）。

## 领地（greenfield·只动这些·扩展不替换）
新 `app/backend/app/llm/`（gateway.py 单一入口 / routing.py 混合自适应 / credential_pool.py SecretRef / call_record.py LLMCallRecord）。**wrap 只读** agent/llm_client.py（作 adapter·不改它）、security/keystore（SecretRef 物化在门后）、lineage/ids。**绝不碰** main.py、其他在飞线领地。

## 可证伪验收（种坏门必抓·GOAL §7/§1）
1. LLM 调用绕过 Gateway（直调 provider SDK / 读 token）→ 拒（对抗：构造直调→Gateway 单一入口门必抓；MUT 放过→红）。
2. LLMCallRecord 缺 provider/model/auth_ref/replay_state → 拒（§1）。
3. 明文 secret（API key/OAuth/token）进 LLM prompt/RAG/日志/导出 → 拒（§1·只 SecretRef 引用·明文只在 Settings/Secrets）。
4. Verifier/Critic 独立挑战缺 provider/model/context 记录 → 标独立性不足（§7·写进 LLMCallRecord）。
5. 混合自适应路由：难任务（架构/数学/难调试）走强模型·机械活走轻模型·绝不静默降质（对抗：难任务误路由轻模型→correctness 风险·必标）。

## 红线 [按需]
**实盘 key/secret 不进 LLM/RAG/日志/导出**（致命·明文只在 Settings/Secrets·Gateway 只持 SecretRef）·role agent 不直接读 provider credential·复用 ids.content_hash 不另造·扩展不替换（wrap llm_client 不改）·撞 decisions 未覆盖岔路停报中心。**先读 GOAL §7/§1 + D-LLM-ROUTING 再动手。**

## 非目标 [按需]
不建 Agent Orchestrator 全栈 + 12 role + 23 事件投影（另卡）；不自实现 OAuth（D-DELIVERY-SLICE：用户跑 Hermes 本地代理·Gateway 指向即可）。本卡只 Gateway 核 + 路由 + 凭据池 + 调用账。

## 完成记录（2026-06-26·deep-opus 任务线·隔离 worktree·分支 `wave3/llm-gateway`·待中心整合+全量+land）

> 自含交付摘要。**🟡≠✅**：本卡核心门已建并经变异验证（下表 6 个 MUT 各自抓红再还原·非 git checkout）；全量套件 + land 由中心做（本线只跑 scoped）。

### 新建文件（greenfield·只动 llm/·没碰 main.py / llm_client 内部 / 其他在飞线）
- `app/backend/app/llm/__init__.py` —— 包导出（40 个符号）。
- `app/backend/app/llm/call_record.py` —— `LLMCallRecord`（provider/model/auth_ref/replay_state 必填四要素）+ `ReplayState`/`CallStatus`/`IndependenceRecord` + 三门（`assert_record_admissible` 必填 / `assert_no_plaintext_secret` secret / `seal_record`+`verify_record_seal` 封印）+ `evaluate_independence`（§7 裁决）+ `make_call_id`（复用 `lineage/ids.content_hash`·不另造）。
- `app/backend/app/llm/credential_pool.py` —— `SecretRef`（永不含明文·repr 不泄露）+ `LLMCredentialPool`（capability 物化·明文只在门后）+ `MaterializedCredential`（短命·repr 打码）+ `GatewayCapability` + `CredentialDescriptor`（role-agent 安全视图）。物化复用 `security.SecureKeystore`。
- `app/backend/app/llm/routing.py` —— `ModelRoutingPolicy`（混合自适应/质量优先/成本优先可配）+ `TaskDifficulty`/`RiskLevel`/`ModelTier` + `LLMModelProfile` + `RoleCapabilityRequest` + `RoutingDecision` + `infer_capability_tier`（默认启发式·可被显式 profile 覆盖）。不可逆/难任务永远不降档；降档必标 `degraded`。
- `app/backend/app/llm/gateway.py` —— `LLMGateway.complete()` 唯一入口（prompt secret guard → 路由 → strict-degrade → 健康/配额 fallback → 组账 → secret 门 → 必填门 → 封印）+ `ProviderHealth`/`QuotaStatus` + `LLMGatewayEvent`（§7 的 5 枚 LLM 事件·数据 only·投影=另卡）+ `assert_admissible_to_graph`（下游准入唯一门=绕过门）。默认 client 工厂 wrap 现有 `make_llm_client`（不重建 provider）。
- `app/backend/tests/test_llm_gateway.py` —— 31 测试。

### 真测试汇总行（scoped·带 timeout·凭汇总行判绿）
- `pytest app/backend/tests/test_llm_gateway.py -q` → **31 passed in 0.17s**。
- `pytest test_llm_gateway + test_llm_providers + test_llm_record_replay + test_llm_custom_and_api + test_llm_e2e_agent -q` → **83 passed in 13.06s**（现有 LLM 测试零回归）。
- `pytest --collect-only -q` → **1930 collected**（基线 1900 + 本卡 30 净增·无 collection error·基线未破）。
- py_compile 全过；本环境无 ruff（未安装·非本卡引入）。

### 对抗测试·变异验证（种坏门必抓·门是不是纸做的·RULES §2）
| MUT | 拆哪道门 | 抓红测试 | 还原 |
|---|---|---|---|
| MUT-1 | `assert_admissible_to_graph` 封印校验摘除 | `test_gate_bypass_forged_record_rejected` + `test_gate_bypass_tampered_seal_detected`（2 红） | Edit 还原·非 git checkout |
| MUT-2 | `assert_no_plaintext_secret` 扫描置 no-op | `test_gate_plaintext_secret_in_record_rejected`（红） | 同上 |
| MUT-3 | `_guard_prompt` prompt secret 门摘除 | `test_gate_plaintext_secret_in_prompt_blocked`（红） | 同上 |
| MUT-4 | `required_tier` 拆「难任务/不可逆→强模型」下限 | hard→strong / irreversible→strong / degraded-flag / strict-refuse（4 红） | 同上 |
| MUT-5 | `assert_record_admissible` 只查 provider | `test_gate_missing_required_field_rejected[model,auth_ref]`（2 红） | 同上 |
| MUT-6 | `materialize` capability 校验摘除 | `test_credential_pool_blocks_role_agent_materialize`（红） | 同上 |

### 可证伪验收逐条（对卡上 5 条）
1. **绕过 Gateway → 拒** ✅：封印（HMAC over 账规范 JSON·gateway 实例 nonce）+ `assert_admissible_to_graph` 准入门——伪造/篡改账验不过（MUT-1 双抓）。
2. **LLMCallRecord 缺四要素 → 拒** ✅：`assert_record_admissible`（MUT-5 抓 model/auth_ref）+ 非法 replay_state 枚举拒。
3. **明文 secret 进 prompt/账/导出 → 拒** ✅：发前 `_guard_prompt` 扫 prompt（MUT-3）+ 落账前 `assert_no_plaintext_secret` 扫账面（MUT-2）·报错绝不回显 secret·真路由账逐字断言不含物化 key（`test_real_call_record_carries_no_plaintext_key`）。
4. **Verifier 独立性** ✅：双 provider→换 provider satisfied=True；单 provider→satisfied=False 标独立性不足；同源假报 satisfied=True→`evaluate_independence` 判「假独立」；缺 context→不足。
5. **混合自适应·绝不静默降质** ✅：hard/不可逆→strong；机械低风险→light；只剩 light 的 hard→`degraded=True`+reason（非 strict）/ `DegradedRoutingError`（strict 默认·provider 不被调）。fallback 换 provider 不降档；降档必标。

### 红线合规逐条
- **实盘 key/secret 不进 LLM/RAG/日志/导出** ✅：明文只在 `SecureKeystore`；Gateway 持 `SecretRef`；物化 `MaterializedCredential` 短命·repr 打码·随调用出作用域回收；prompt 门 + 账门双扫（含交易 key 如 binance·`known_secret_values` 覆盖全 keystore）；本模块 logger 绝不打 secret/原始 prompt（账只存 `prompt_digest` 内容哈希·不存原文）。
- **role agent 不直接读 credential** ✅：物化需 gateway capability（私有 nonce）；role-agent 视图 `describe()` 只给 provider/auth_ref 元数据。
- **复用 ids.content_hash 不另造** ✅：`call_id`/`prompt_digest` 走 `lineage/ids.content_hash`。
- **扩展不替换（wrap llm_client 不改）** ✅：未改 `agent/llm_client.py`/`llm_providers.py`/`keystore.py`/`lineage/ids.py` 一字；默认工厂 wrap `make_llm_client`。
- **无新公式** → 未造 MathematicalArtifact ✅。

### 拍板项命中（GOAL 没覆盖的岔路）
- **无停报项**。D-LLM-ROUTING（混合自适应）已覆盖路由默认值；D-DELIVERY-SLICE（Hermes·不自实现 OAuth）已覆盖 oauth_proxy 走 custom provider。两处设计内决定均已落进 decisions，未越界。
- 一处**诚实限界**（设计极限·不会再改·非残余）：封印/capability 是**治理 provenance 证据**，不是对「同进程内恶意构造者」的密码学防御——Python 进程无法语言层绝对禁止 `import requests` 直打 API。本卡落地的是 GOAL 真要的「**绕过治理的 LLM 结果对 Research Graph 不可准入**」，已写进 gateway.py / call_record.py docstring。

### 诚实残余（会变成后续任务·非本卡 scope）
1. **Agent Orchestrator 全栈 + 12 role agent + 23 事件投影到 user 工作流** = 另卡（本卡只把 5 枚 LLM 事件作数据挂结果上·未投影 Canvas）。
2. **record/replay store 接线**：本卡如实记录 `replay_state`（从既有 `RecordingLLMClient` 回传读 fixture_key），但未在 llm/ 内自建 fixture store（复用 agent/replay·接线点留给 Orchestrator 卡·避免本卡耦合 agent/replay）。
3. **ProviderHealth 主动探活 + QuotaStatus 从 429 自动回填**：当前 health 由调用失败被动更新、quota 留接口（`mark_quota_exhausted`）待 provider 响应解析接线。
4. **oauth_proxy（Hermes）端到端**：凭据池已建 auth_kind=oauth_proxy·走 custom provider；onboarding/Settings 引导预设（D-DELIVERY-SLICE 的轻活）未在本卡做。
5. **Gateway 接进 main.py / AgentRuntime 注入**：本卡只交治理层；把 AgentRuntime 的 `self._llm.chat` 改走 Gateway = 接线卡（动 main.py / agent_runtime·本卡领地外）。
