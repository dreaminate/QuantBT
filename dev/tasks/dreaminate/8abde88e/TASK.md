---
uuid: 8abde88e406544e990d7cdf352740f23
title: CanonicalCommand——typed 命令层 + 语义翻译 + 全入口落同一 audit/lineage（A-CMD）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: canonical-command
source: goal
source_ref: GOAL §1(链 Canvas/Command→QRO→Research Graph)·§2(user 手动画布/表单/IDE/API 改动都落 canonical command·与 Agent 动作进同一 audit/lineage/lifecycle·user 手动改动未落 canonical command→拒)；A-GRAPH-1 落最小命令信封·语义翻译归本卡
depends_on: [76a611d3d26c42f495a7d7a29d5e5319]
---

# CanonicalCommand（A-CMD·LINE-A 续·QRO→Graph→Command→Compiler 链）

## Scope [必填·先读 GOAL §1+§2]
A-GRAPH-1 落了最小命令落点（actor∈四类+目标台+内容寻址 id+payload）。本卡建 **CanonicalCommand 全栈**——§2「user 手动画布/表单/IDE/API 改动都落 canonical command·与 Agent 动作进同一 audit/lineage/lifecycle」：① typed 命令层（所有写入 Research Graph 的唯一通道·user 手动 + agent 动作同源）② 语义翻译/解析（intent/canvas action → typed command）③ 全栈校验（actor 四类/目标台/内容寻址/payload schema）④ provenance（命令来源面：user-manual/agent/ide/api）。**不建 Governed Compiler（A-COMPILER 另卡·消费 command→run）**·本卡只命令层 + 翻译 + 校验 + 落 graph。

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/command/`（canonical_command.py：typed 命令 + 翻译 + 校验 + provenance + 落 research_graph apply）。**读只读**：graph/research_graph（落点·A-GRAPH-1 已建）、qro/envelope、lineage/ids。**绝不碰** main.py、graph/qro 内部（只读）、其他在飞线。

## 可证伪验收（种坏门必抓·§2）
1. user 手动改动（画布/表单/IDE/API）未落 canonical command 进图 → 拒（对抗：构造直写绕过→必抓；MUT 放过→红）。
2. canonical command actor 非四类 / 缺目标台 / 缺内容寻址 id → 拒。
3. agent 动作与 user 手动动作落同一 audit/lineage（对抗：两源命令同进一本账·provenance 区分但同链）。
4. 正路径：合法 typed command 落图正确·不误伤。

## 红线 [按需]
单一身份源 ids.py 不另造·扩展不替换·所有写入经 canonical command（绕过→拒）·先读 GOAL §1/§2 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不建 Governed Compiler（A-COMPILER 另卡）；不建前端 Canvas 交互（命令后端层即可）。本卡只命令层+翻译+校验+落图。
