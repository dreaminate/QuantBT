---
uuid: 9d593481fd674978930926f541f2b7b3
title: RDP 开放格式 schema + manifest 规范（fail-closed 导出器·D-RDP-1）
status: todo
owner: wait
assigned_by: dreaminate
review_status: 0
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
