---
uuid: 640b66a0cfb44c3295b2fa8cf57a3568
title: LLM Gateway——唯一调用入口 + ModelRoutingPolicy(混合自适应) + CredentialPool + LLMCallRecord（A-AGENT-GW）
status: todo
owner: wait
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
