---
uuid: 9c5e69752fec4a19939e8504ce5bd53e  # 全 32 位 hex 无连字符;生成:python -c "import uuid;print(uuid.uuid4().hex)"(或直接 os.py mint 全自动)
title: dual-model gate 应用内跨厂商接线——真实 anthropic builder × openai verifier 端到端(gateway 路由+HMAC 密封 LLMCallRecord+ReviewSubjectBinding+IndependenceVerdict 落盘)
status: in_progress  # todo | in_progress | done
owner: dreaminate  # wait(在 pool) | <developer_id>;须 == 所在文件夹(validate 校验一致;os.py assign 两处同改)
assigned_by: dreaminate  # 分配者 developer_id(leader/admin);pool 中留空
review_status: 1 # 被分配者 self-review:0 未过目 | 1 已过目/确认
priority: P0  # P0 最高 … P3 最低
area: research-os  # 功能域 slug,须已在 ../_areas.md 注册(语法 ^[a-z0-9_-]+(/[a-z0-9_-]+)?$;validate 校验)
source: goal  # research | goal | interaction(三晋升源出身)
source_ref:   # 溯源句柄:finding 路径 / GOAL §x / 对话
goal_section: §7  # 服务 GOAL 哪个子系统节(如 §3);build_trace.py 据此聚合覆盖,可空
done_at:         # 落档日期 YYYY-MM-DD(os.py done 自动填;归档按它分季)
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
经 codex(gpt-5.6-sol ultra) 增量审 REJECT 一轮后重设计(五条否决全修):
1. 单厂商/缺凭据 → fail-closed 拒绝运行,零 evidence(同厂商换 prompt≠第二意见)
2. 双槽同 api_key 冒充跨厂商 → 可证同源,拒绝(种坏必抓)
3. verifier 实发 prompt 被偷换(种坏缝 _verifier_prompt_override)→ digest 互证门必抓;
   复用 gateway 同一哈希族(ids.content_hash),不自立第二套
4. key 回显三路径全堵:loader yaml 异常(原文含 key→消息整体抑制)/preflight 响应体
   (对全部已加载 key 脱敏,非仅当前 provider)/verifier 输出直达 evidence(扫描拒落盘);
   builder 输出回显则更早被 gateway._guard_prompt SecretLeakError 拒发(分层佐证测试)
5. evidence 事后篡改(手翻 independent)→ HMAC 密封(与 LLMCallRecord 同 key)复验必红
6. 同 base_url 中继 → 不拒但 evidence 如实披露「上游独立性不可证」(用户自判)

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
桩注入端到端产合法 binding+独立性判定+密封记录且 11 对抗测试全绿;脚本可证边界=
「双槽凭据不同源(同 key 即拒)+实发 prompt 与 binding 互证+证据密封防篡改」;真实跨厂商
调用在凭据有效时同一路径即通(preflight 常开指路);全量基线不破。
**机制级残余(登记,不冒充已证):provider 身份来自配置槽声明(model_identity 按模型名判族),
双槽指向同一实际后端的伪装无单侧证伪手段;validate_review_subject_binding 本身不绑实发
prompt(本脚本以 digest 互证补位,机制层扩展另立卡)。**
**真实调用现状:本机中继 key 双 401(脱敏诊断留档),登记待用户换有效 anthropic+openai 凭据后跑通并落真实证据。**
