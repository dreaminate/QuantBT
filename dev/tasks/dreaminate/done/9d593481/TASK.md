---
uuid: 9d593481fd674978930926f541f2b7b3
title: RDP 开放格式 schema + manifest 规范（fail-closed 导出器·D-RDP-1）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: delivery
source: goal
source_ref: GOAL §17 交付标准（RDP 缺 manifest/hash/repro command→拒）+ §0 北极星交付项 + 施工图 LINE-E W4
depends_on: []
---

# RDP 开放格式 schema + manifest 规范（D-RDP-1）

## Scope [必填]
现 `run_detail_research_export.py:export_run_bundle_for_detail` 只是图表 bundle（run.json+csv+md+py·覆盖 ~6/27 字段）。本卡建 §17 **开放格式 RDP schema**（27 字段 JSON Schema + 版本化 manifest），字段留 **optional 槽位**（Research Graph/数学/TheoryImplementationBinding/未验证残余 等待 LINE-A/spine/C 供给）。先把 schema 骨架 + 已有 6 字段接通 + **fail-closed**（缺字段→`blocked/missing` verdict，不美化成完整交付）。

## 文件领地（owner·并发隔离）
新 `app/backend/app/delivery/rdp_schema.py` `delivery/manifest.py`。**全新目录·零交叠·LINE-E 早定先行（5 并发都向它供字段）**。

## 接线点（file:line·实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| 新 `app/backend/app/delivery/rdp_schema.py` | — | 27 字段 JSON Schema + optional 槽 |
| 新 `app/backend/app/delivery/manifest.py` | — | 版本化 manifest + artifact hash + repro command 槽 |
| `app/backend/run_detail_research_export.py:227` | 现导出器 | 接已有 6 字段（不替换·扩展） |

## 对抗测试设计（种坏门必抓）[必填]
1. **命门**：RDP 缺 reproducibility command / artifact hash / manifest → 必拒（§17）。
2. RDP 缺 DatasetVersion / IngestionSkill 引用 → 拒。
3. RDP 缺未验证残余 → 拒。
4. 缺字段 → verdict=`blocked/missing`，绝不标「完整交付」（不假绿灯）。

## 复用 [按需]
`lineage/ids.py` content_hash（artifact hash）· `run_detail_research_export.py`（已有字段·扩展不替换）· `RunDetailPage 冻结`（仅加字段·不改结构）。

## 红线 [按需]
RunDetailPage 收益概述页冻结 · no template false success · 缺字段诚实标 missing 不美化 · 扩展不替换。

## 非目标 [按需]
不做 RDP 聚合器（D-RDP-2 另卡·依赖 A LLMCallRecord + B DatasetVersion）；schema 字段先留 optional 槽、不阻塞等上游。

## 完成记录（2026-06-26·第一波整合 land·中心 orchestrator）
- 实现 commit `f96b34b`（分支 `wave1/w4-rdp-schema`）→ 中心 merge `ac85710`。
- greenfield `delivery/`：`rdp.py`（§17 ~25 字段 RDPManifest + DatasetVersionRef + PromotionClaim + 开放 JSON 往返·rdp_id 复用 lineage.ids.content_hash·from_dict 重算 id 防伪造追溯）+ `rdp_gate.py`（§17 四拒绝门 + RDPRejected + assemble/validate/require_valid_rdp）。
- 对抗：`test_rdp_gate.py` 22 passed·4 门各 MUT（缺 manifest/hash/repro→拒·缺 DatasetVersion/IngestionSkill→拒·缺未验证残余→拒·晋级追溯错配→拒）。开放 JSON 第三方可解析。
- **诚实状态：schema + 4 拒绝门 ✅；本卡 scope 余项 🟡 = follow-on P2**——① 接现导出器 `run_detail_research_export.py:227`（已有 6 字段透传）未做（本卡建独立 delivery/ 模块·未接旧导出器）② 接真 promote 路径（approval.gate/paper.desk 调 require_valid_rdp）③ 3 命名对象（LLMCallRecord/ResponsibilityDisclosureRecord/TheorySpec）按 string ref·待类建好收紧 typed。RDP 聚合器 = D-RDP-2 另卡（依赖 LINE-A）。
