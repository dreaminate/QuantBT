---
uuid: 8be0e54779794accba36cad3dd92ffc0  # 全 32 位 hex 无连字符;生成:python -c "import uuid;print(uuid.uuid4().hex)"(或直接 os.py mint 全自动)
title: dual-model 独立性机制层加固——binding 绑 adapter 实发 payload(本机提交为界,中继后实收不可证)+provider 身份证明升级(声明式槽名→可验证身份,评估远端 attestation 可行性)
status: todo  # todo | in_progress | done
owner: wait  # wait(在 pool) | <developer_id>;须 == 所在文件夹(validate 校验一致;os.py assign 两处同改)
assigned_by:     # 分配者 developer_id(leader/admin);pool 中留空
review_status: 0 # 被分配者 self-review:0 未过目 | 1 已过目/确认
priority: P1  # P0 最高 … P3 最低
area: research-os  # 功能域 slug,须已在 ../_areas.md 注册(语法 ^[a-z0-9_-]+(/[a-z0-9_-]+)?$;validate 校验)
source: goal  # research | goal | interaction(三晋升源出身)
source_ref: dev/tasks/dreaminate/9c5e6975 codex 二轮审残余  # 溯源句柄:finding 路径 / GOAL §x / 对话
goal_section: §7  # 服务 GOAL 哪个子系统节(如 §3);build_trace.py 据此聚合覆盖,可空
done_at:         # 落档日期 YYYY-MM-DD(os.py done 自动填;归档按它分季)
depends_on: [9c5e69752fec4a19939e8504ce5bd53e]  # 上游卡 uuid 列表(全 32 位)= DAG 的边;os.py mint --depends-on 可用 uuid8 前缀自动解析
---

# dual-model 独立性机制层加固——binding 绑 adapter 实发 payload(本机提交为界,中继后实收不可证)+provider 身份证明升级(声明式槽名→可验证身份,评估远端 attestation 可行性)

## Scope [必填]
把 dual-model 独立性的两个机制级信任缺口收进机制层(非脚本补丁):① ReviewSubjectBinding
绑到 adapter 实发(本机提交)的 request payload——adapter 层把实际发出的 payload digest
回带进 LLMCallRecord(现 prompt_digest 在 adapter 调用前按 LLMRequest 计算,client 层
改写无感知)。注意边界:这只能证到「本机网络栈发出了什么」,中继/provider 侧实收内容
单侧仍不可证,除非引入 provider 可验证回执/attestation(本卡内评估可行性,不可行则把
该边界写死进 verdict 语义);② provider 身份从「配置槽名+模型名判族」升级为可验证身份(响应
指纹/厂商侧可验证凭据,评估 attestation 可行性,不可行则把边界写死进 verdict 语义)。
不做:改 canonical 校验族、动 GoalProofLedger、重写 gateway 路由。

## 上下文 / 动机 [按需]
<为什么现在做,链到 finding / gap>

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/llm/gateway.py | _prompt_digest:673 / adapter 调用点 | 扩展:adapter 实发 payload digest 回带 record |
| app/backend/app/llm/call_record.py | validate_review_subject_binding:651 | 扩展:verifier_input_ref 绑 adapter 实发 payload digest |
| app/backend/app/llm/model_identity.py | provider 判族:33/85 | 评估可验证身份升级,边界写进文档与 verdict 语义 |
| scripts/dual_model_review.py | digest 互证段 | 机制层落地后收敛脚本级补位(不留双源) |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. adapter 改写:桩 adapter 实发 payload 与 LLMRequest 不同 → 实发 digest 校验必拒
2. 身份伪装:槽名 anthropic 配 openai 后端 → 身份校验必抓(或 verdict 语义显式降级为声明式标注)
3. 中继/provider 侧改写 → 单侧不可证:不种此坏,验收明确排除;可行性评估结论(回执/attestation 有无)写进卡

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
binding 校验覆盖 adapter 实发(本机提交)payload(种坏必抓;中继后实收明确列为不可证
边界或由 attestation 评估收口);provider 身份要么可验证、要么 verdict 语义显式声明式
标注,二者必居其一;9c5e6975 脚本级补位收敛,全量基线不破。
