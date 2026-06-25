---
uuid: f19c5c192f4a44cc95fd159ea04d94e5
title: QRO 统一对象信封 + 状态四/五轴——对象脊柱地基（A-QRO-1）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: qro
source: goal
source_ref: GOAL §1 统一对象模型（QRO/Quant Research Object）+ 头号 gap #1 + 施工图 LINE-A 首卡
depends_on: []
---

# QRO 统一对象信封 + 状态四/五轴（A-QRO-1）

## Scope [必填]
头号 gap #1 主轴第一砖。theory/methodology 对象（MathematicalArtifact/TheoryImplementationBinding/ConsistencyCheck/MethodologyChoiceRecord）已在 `lineage/spine.py`，但资产（factor/model/signal/strategy）散落、无共享信封。本卡定义 **QRO 统一信封**（identity / version / actor 四类 / event_time / known_at / effective_at / lineage / verdict / permission / lifecycle）+ **状态四轴枚举**（definition / evidence / governance / runtime 分离）+ **收编现有资产**（扩展不替换·复用 `ids.py` 身份不另造）。**这条 LINE-A 阻塞最多下游**（ResearchGraph/CanonicalCommand/Compiler/Canvas/Agent OS 写路径都经它），建议中心自管或固定 1 opus 稳推。

## 文件领地（owner·并发隔离）
新 `app/backend/app/qro/`（信封 + 轴枚举 + 资产收编适配）。**收编只读**：`lineage/spine.py`/`ids.py`/`verification/schema.py`。**LINE-A·依赖 LINE-0 land·阻塞下游·绝不与第二波 A-* 卡并行同改 qro/**。

## 接线点（file:line·实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| 新 `app/backend/app/qro/envelope.py` | — | QRO 信封 dataclass（字段照 GOAL §1）+ 四轴枚举 |
| `app/backend/app/lineage/spine.py` | theory 对象 | 收编进 QRO（不改 spine·只挂信封） |
| `app/backend/app/lineage/ids.py` | content_hash | QRO identity 复用（**不另造身份源**） |

## 对抗测试设计（种坏门必抓）[必填]
1. **命门**：Signal QRO 无 typed contract → 必拒；actor 非四类枚举 → 拒。
2. 状态四轴混成单绿灯（definition/evidence/governance/runtime 不分离）→ 拒。
3. 模型本体塞进 Factor library → 拒（语义边界·A-QRO-2 接续）。

## 复用 [按需]
`lineage/ids.py`（identity·**单一身份源不另造**）· `lineage/spine.py`（theory 对象收编）· `verification/schema`（verdict 轴）。

## 红线 [按需]
单一身份源 ids.py 不另造 · 扩展不替换（收编现有资产不重写）· 四轴分离不假单绿灯 · 撞 decisions 未覆盖新岔路停下报中心。

## 非目标 [按需]
不建 ResearchGraph IR（A-GRAPH-1 接续）；不建 CanonicalCommand/Compiler（后续卡）；本卡只定信封 + 轴 + 收编。
