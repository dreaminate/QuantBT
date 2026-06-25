---
uuid: 67b4202584534a23b147973d7d48b8ca
title: RDP 接线——接现导出器 6 字段 + 接真 promote 路径 require_valid_rdp（D-RDP-1 wire）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: delivery
source: goal
source_ref: GOAL §17 + 9d593481 完成记录诚实残余（schema+4 门 ✅·接线 🟡）
depends_on: [9d593481fd674978930926f541f2b7b3]
---

# RDP 接线（D-RDP-1 wire）

## Scope [必填]
9d593481 已建 RDP schema + §17 四拒绝门（greenfield delivery/·22 对抗测试·🟡 未接线）。本卡接线：① 现导出器 `run_detail_research_export.py:227` 已有 6 字段透传进 RDPManifest（扩展不替换·不动 RunDetailPage 冻结）② 接真 promote 路径（`approval.gate.ApprovalGateService` / `paper.desk.PromotionGate` promote 前调 `require_valid_rdp(rdp, promotion=claim)`，晋级缺 RDP 追溯→拒）。RDP 聚合器（D-RDP-2·依赖 LINE-A LLMCallRecord + B DatasetVersion）另卡。

## 接线点（实现复核）[必填]
- `app/backend/run_detail_research_export.py:227`（接已有 6 字段·扩展）
- `app/backend/app/approval/gate.py` / `app/backend/app/paper/desk.py`（promote 前 require_valid_rdp）

## 对抗验收（种坏门必抓）[必填]
1. promote 不带合法 RDP（缺 manifest/hash/repro/DatasetVersion/未验证残余）→ 拒晋级（端到端·MUT 放过→红）。
2. 现导出器 6 字段进 RDPManifest 不破 RunDetailPage 冻结（仅加字段）。
3. 缺字段 RDP→verdict blocked/missing 不美化完整交付。

## 红线 [按需]
RunDetailPage 收益概述页冻结·no template false success·缺字段诚实标 missing·OrderGuard/promote 门不绕·扩展不替换。
