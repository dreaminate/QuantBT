---
uuid: 0781bb130bb740c18f271f91bb8d9d5f
title: RDP 聚合器——从真血统装配 RDP（DatasetVersion/LLMCallRecord/honest-N/verdict 真填）（D-RDP-2）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: delivery
source: goal
source_ref: GOAL §17(RDP ~25 字段·DatasetVersion/IngestionSkill/LLMCallRecord/replay/honest-N/verdict/approval 引用)；D-RDP-1(9d593481)建 schema+4 拒绝门·本卡聚合真血统填字段
depends_on: [9d593481fd674978930926f541f2b7b3, 640b66a0cfb44c3295b2fa8cf57a3568]
---

# RDP 聚合器（D-RDP-2·北极星 §17 总闸·LLM Gateway 已解锁）

## Scope [必填·先读 GOAL §17]
D-RDP-1（9d593481）建了 RDP schema + §17 四拒绝门（schema 字段多为 string ref/optional 槽）。本卡建 **RDP 聚合器**——从**真血统**装配 RDP：① DatasetVersion（data_quality 注册身份·W3 已建）② LLMCallRecord（llm/call_record·LLM Gateway 已建·进 RDP「LLM Provider/ModelRoutingPolicy/replay state」）③ artifact hash（lineage/ids）④ honest-N（lineage/ledger）⑤ Verifier verdict/Approval/promotion record ⑥ 已知限制/未验证残余（诚实闸）。聚合器产**真 RDP**喂 D-RDP-1 的拒绝门校验。**3 命名对象（LLMCallRecord 现已建·可 typed 引用收紧；TheorySpec/ResponsibilityDisclosureRecord 待建则保 string ref·不强造）**。

## 领地（只动·扩展不替换）
扩 `app/backend/app/delivery/`（新 aggregator.py：从真血统装配 RDPManifest·不改 rdp.py schema/rdp_gate.py 4 门语义）。**读只读**：llm/call_record（LLMCallRecord）、data_quality（DatasetVersion）、lineage/ids/ledger（hash/honest-N）、verification（verdict）、approval。**绝不碰** main.py、llm/data_quality/lineage 内部（只读）、其他在飞线、RunDetailPage（冻结）。

## 可证伪验收（种坏门必抓·§17）
1. 聚合的 RDP 缺 DatasetVersion/IngestionSkill 真引用 → D-RDP-1 门拒（对抗：聚合漏真 DatasetVersion→门必抓；MUT 放过→红）。
2. 聚合的 RDP 缺 LLMCallRecord（用了 LLM 但无调用账）→ 标 missing 不美化（§17·诚实）。
3. 缺「未验证残余」字段 → 拒（诚实闸·D-RDP-1 门）。
4. 真血统装配：DatasetVersion/LLMCallRecord/honest-N/verdict 从真源填·非编造（对抗：篡改源→聚合反映·不静默填默认）。

## 红线 [按需]
复用 lineage.ids/data_quality/llm 单一源不另造·开放格式 JSON·缺字段诚实标 missing 不美化（no template false success）·实盘 key 不进 RDP（只 LLMCallRecord 的 auth_ref/SecretRef·不含明文）·RunDetailPage 冻结·扩展不替换·先读 GOAL §17 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不改 D-RDP-1 schema/4 门语义（只聚合填）；TheorySpec/ResponsibilityDisclosureRecord 类未建则保 string ref 不强造；接进真 promote 端到端强制档=用户拍（D-SCOPE-CONSERVATIVE·等聚合器即本卡·常开仍待用户）。本卡只聚合器+真血统填+喂 D-RDP-1 门。
