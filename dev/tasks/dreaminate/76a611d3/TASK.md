---
uuid: 76a611d3d26c42f495a7d7a29d5e5319
title: ResearchGraph IR——QRO 节点 typed 图 + 各台 typed projection + 单一真相源（A-GRAPH-1）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: research-graph
source: goal
source_ref: GOAL §1 统一对象链(Quant Intent→Canvas→QRO→Research Graph→Compiler)·§2 多台工作系统(每台 Canvas=同一 Research Graph 的 typed projection·单一真相源)；施工图 LINE-A 续(QRO 已出契约)
depends_on: [f19c5c192f4a44cc95fd159ea04d94e5]
---

# ResearchGraph IR（A-GRAPH-1·LINE-A 续·阻塞 Compiler/Command/各台）

## Scope [必填·先读 GOAL §1+§2]
A-QRO-1（f19c5c19）已出 QRO 统一信封。本卡建 **Research Graph IR**——§1 链里 QRO→Compiler 之间的 IR：**typed 图**持有 QRO 节点（复用 qro/envelope·只读收编）+ 边（lineage/dependency/DeskHandoff）+ **各台 typed projection**（§2「每台 Canvas=同一 Research Graph 的 typed projection」）+ **单一真相源不变量**（§2「任一台维护独立真相状态→拒」）+ canonical command 落点（§2「user 手动改动未落 canonical command→拒」）。**不建 Compiler（A-COMPILER 另卡）、不建 CanonicalCommand 全栈（A-CMD 另卡）**，本卡只定 IR 图结构 + projection + 单一源门。

## 领地（greenfield·只动这些·扩展不替换）
新 `app/backend/app/graph/`（research_graph.py：node[QRO]/edge/graph + typed projection API + 单一源不变量 + canonical command apply 落点）。**收编只读**：qro/envelope（节点）、lineage/ids（身份）、lineage/spine（theory 节点）。**绝不碰** main.py、qro/（A-QRO 领地·只读）、其他在飞线。

## 可证伪验收（种坏门必抓·GOAL §2）
1. 任一台维护独立真相状态（绕过 Research Graph 自存）→ 拒（对抗：构造两台不同状态→单一源门必抓矛盾；MUT 放过→红）。
2. QRO 节点无 typed input/output contract 进图 → 拒（§1）。
3. DeskHandoff 完成缺 produced_ref → 拒（§2）；user/agent 改动未落 canonical command 进图 → 拒。
4. 各台 typed projection 正确投影（当前台决定节点/边/状态/可编辑类型·§2）；正路径不误伤。

## 红线 [按需]
单一身份源 ids.py 不另造·扩展不替换（收编 qro 不改）·单一真相源（任一台独立状态→拒）·撞 decisions 未覆盖岔路停报中心。**先读 GOAL §1/§2 再动手。**

## 非目标 [按需]
不建 Governed Compiler（A-COMPILER 另卡）；不建 CanonicalCommand 全栈翻译（A-CMD 另卡）；不建前端 Canvas（projection 后端 IR 即可）。本卡只 IR 图 + projection + 单一源门。
