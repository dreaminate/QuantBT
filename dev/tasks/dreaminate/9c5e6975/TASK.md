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
| app/backend/tests/test_dual_model_review_script.py | 新增 | 桩注入三测(端到端/单厂商诚实 False/缺凭据指路) |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 单厂商冒充:只配 openai → independent 必为 False(同厂商换 prompt≠第二意见),绝不 True
2. secret 卫生:密封记录与 evidence JSON 中任何 key 字面量出现 → 拒落盘(测试断言零泄漏)
3. 凭据缺失:secrets 无 key → SystemExit 指路 store/配置(不静默降级 mock——gateway dev_local 永不进路由)
4. (机制层已有,复用不重造)builder 输出篡改→binding digest 必炸;无共享 session→独立性判定拒:种 <已知的坏> → 门必 <抓的表现>(含变异要杀的点)

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
桩注入端到端产合法 binding+独立性判定+密封记录(3 tests passed);真实跨厂商调用在凭据有效时
同一路径即通(preflight 指路);单厂商绝不产 independent=True;全量基线不破。
**真实调用现状:本机中继 key 双 401(脱敏诊断留档),登记待用户换有效 anthropic+openai 凭据后跑通并落真实证据。**
