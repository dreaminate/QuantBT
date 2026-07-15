---
uuid: 9c5e69752fec4a19939e8504ce5bd53e  # 全 32 位 hex 无连字符;生成:python -c "import uuid;print(uuid.uuid4().hex)"(或直接 os.py mint 全自动)
title: dual-model gate 应用内跨厂商接线——真实 anthropic builder × openai verifier 端到端(gateway 路由+HMAC 密封 LLMCallRecord+ReviewSubjectBinding+IndependenceVerdict 落盘)
status: done  # todo | in_progress | done
owner: dreaminate  # wait(在 pool) | <developer_id>;须 == 所在文件夹(validate 校验一致;os.py assign 两处同改)
assigned_by: dreaminate  # 分配者 developer_id(leader/admin);pool 中留空
review_status: 1 # 被分配者 self-review:0 未过目 | 1 已过目/确认
priority: P0  # P0 最高 … P3 最低
area: research-os  # 功能域 slug,须已在 ../_areas.md 注册(语法 ^[a-z0-9_-]+(/[a-z0-9_-]+)?$;validate 校验)
source: goal  # research | goal | interaction(三晋升源出身)
source_ref:   # 溯源句柄:finding 路径 / GOAL §x / 对话
goal_section: §7  # 服务 GOAL 哪个子系统节(如 §3);build_trace.py 据此聚合覆盖,可空
done_at: 2026-07-15  # 落档日期 YYYY-MM-DD(os.py done 自动填;归档按它分季)
depends_on: []   # 上游卡 uuid 列表(全 32 位)= DAG 的边;os.py mint --depends-on 可用 uuid8 前缀自动解析
---

# dual-model gate 应用内跨厂商接线——真实 anthropic builder × openai verifier 端到端(gateway 路由+HMAC 密封 LLMCallRecord+ReviewSubjectBinding+IndependenceVerdict 落盘)

## Scope [必填]
应用内 dual-model 跨厂商审查的脚本化真实端到端(scripts/dual_model_review.py):secrets 窄读→
内存 keystore(llm_<provider>+note extras,与 /api/llm/configure 同约定)→build_agent_llm_gateway
(单一源)→builder(anthropic)→ReviewSubjectBinding→verifier(openai,independence_required)→
bind/validate→IndependenceVerdict,HMAC 密封 LLMCallRecord 落盘;含 preflight 脱敏连通诊断。
不做:起 FastAPI 服务器(本机被 secrets.yaml Binance-material 设计性阻断)、orchestrator DAG 路径、OAuth。

## 上下文 / 动机 [按需]
<为什么现在做,链到 finding / gap>

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| scripts/dual_model_review.py | 新增 | CLI:preflight(脱敏诊断)+run_review(注入口仅测试用) |
| app/backend/app/llm/gateway.py | build_agent_llm_gateway:1490 | 零改动,复用(keystore 装配/路由/密封) |
| app/backend/app/llm/call_record.py | make/bind/validate binding+evaluate_independence | 零改动,复用 |
| app/backend/app/llm/call_record_store.py | LLMCallRecordStore.append:130 | 零改动,record_sink 逐调用注入 |
| app/backend/tests/test_dual_model_review_script.py | 新增 | 桩注入十一测(端到端/密封复验/逐坏门对抗) |

## 对抗测试设计（种已知 bug，门必抓）[必填]
经 codex(gpt-5.6-sol ultra) 增量审两轮 REJECT 迭代后定型(17 测):
1. 单厂商/缺凭据 → fail-closed 拒绝运行,零 evidence(同厂商换 prompt≠第二意见)
2. 双槽同 api_key 字面量 → 拒绝(注意:只拦字面量相同;不同 key 仍可指向同一实际
   后端——那是机制级缺口,卡 8be0e547)
3. verifier 送入 gateway 的 prompt 被偷换(种坏缝 _verifier_prompt_override)→
   记账 digest 互证必抓(复用 ids.content_hash 同哈希族);边界:互证覆盖到 gateway
   记账为止,adapter/中继之后的实收 payload 不可证(卡 8be0e547)
4. key 回显全路径:loader yaml 异常抑制+非字符串 key 拒收不回显/preflight 响应体与
   异常分支对全部已加载 key 脱敏/verifier 输出直达 evidence 双扫(序列化文本+对象
   递归,含 JSON 转义 key)拒落盘;builder 侧回显被 gateway SecretLeakError 更早拒发
5. evidence 篡改三态(翻 independent/改非 independent 字段/改 seal_algo 声明)→
   HMAC 复验必红;伪验证器变异(只看 independent)被非 independent 篡改态杀死
6. 同 base_url 中继(归一化比较)→ 不拒但 evidence 落机器可读 caveat + 披露文本
7. 变异杀手:机制 verdict 强制 False 时脚本必须如实转录(杀 independent 硬编码
   True)/binding 校验强制炸必须外传(杀删调用)/preflight 失败 main 必须停在
   run_review 之前(哨兵)

## 复用 [按需]
<现有可复用的 file:符号,别重造>

## 红线 [按需]
<相关 RULES.project 红线 / 致命错误>

## 非目标 [按需]
<明确不做什么,防 scope 蔓延>

## Open Questions [按需]
<进实现前必须全部决完。需拍板的逐条标**规范标签** [需拍板](待) / [已决](已拍)——**只认这两个名、别用变体**,
且标签必须在行首列表项(`- [需拍板 ...]`),散文里提到标签字面量不算。**计数不落盘**:board/DEVMAP 展示时
从标签现算;validate 守「标签规范 + in_progress 时 [需拍板]=0」。非拍板的开口(留 hook / 归后续)不标。>

## 验收一句话 [必填]
桩注入端到端产合法 binding+独立性判定+密封记录且 17 对抗测试全绿;脚本可证边界(措辞
精确,不夸大)=「两个 key 字面量不同 + gateway 记账 prompt digest 与 binding 派生
instruction 互证 + 可信 seal key 下检出内层 evidence/seal_algo 的未重签修改」;
preflight 在 CLI 与 keys=None 编程路径常开(keys 显式注入是测试缝,生产不走);
evidence 带机器可读 independence_claim_scope=cross_vendor_as_configured + caveats;
全量基线不破。
**机制级残余 → 已立卡 tasks/pool/8be0e547:①binding 未绑 provider 实收 prompt(adapter
之后不可证)②provider 身份是声明式(槽名+模型名判族),不同 key 同后端伪装无单侧证伪。**
**真实跨厂商调用已跑通(2026-07-15,订阅路径)**:改走厂商官方 CLI 订阅账号
(app/backend/app/agent/subscription_cli_llm.py:ClaudeSubscriptionLLM/CodexSubscriptionLLM)——
builder=anthropic claude-sonnet-4-5(claude CLI 订阅) / verifier=openai gpt-5.6-sol
(codex CLI 订阅),`python scripts/dual_model_review.py --subscription` 实测 independent=True
(provider+foundation-model family 均异)、verifier 独立重算 IC=0.996834 并逮到 builder 夸大、
evidence HMAC 密封。auth_mode=subscription_cli、claim_scope=cross_vendor_via_official_cli,
caveats=[](两独立 CLI 无中继)。彻底绕过 api-key/中继 401 blocker;CLI 自理 OAuth/刷新/签名,
比 token 重放稳、受支持、ToS 灰度低。陌生用户 onboarding:scripts/llm_auth.py + docs/llm-auth-quickstart.md。
**历史(api-key 路径)**:本机中继 key 双 401,anthropic 槽须原生 /messages;api-key 路径保留可用。
**机制级残余(卡 8be0e547)不变**:binding 未绑 adapter 实收 prompt / provider 身份声明式。
