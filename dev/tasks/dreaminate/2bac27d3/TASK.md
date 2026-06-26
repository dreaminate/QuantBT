---
uuid: 2bac27d322c840888963b1151df939ac
title: Document EvidenceSpan 抽取——DocumentBlock/TableArtifact/FormulaArtifact/EvidenceSpan/ExtractedStrategySpec（§6 续）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: documents
source: goal
source_ref: GOAL §6 Document Intelligence Plane(行 812+·DocumentBlock/TableArtifact/FormulaArtifact/ReferenceArtifact/EvidenceSpan/ExtractionRun/ExtractedStrategySpec/ExtractedModelClaim·抽取→EvidenceSpan→hypothesis/preregistration)；Document 摄入安全栈(66195b71)已立 sandbox+OfflineDocumentParser 抽象·本卡接抽取层
depends_on: [66195b713b8e48b1bf9f7e836708efdb]
---

# Document EvidenceSpan 抽取（§6 续·建在 stub parser 抽象上）

## Scope [必填·先读 GOAL §6]
摄入安全栈(66195b71)已立 raw vault→quarantine→sandbox(OfflineDocumentParser 抽象+stub)。本卡接 §6 **抽取层**：① DocumentBlock/TableArtifact/FormulaArtifact/ReferenceArtifact（解析产物 typed·从 OfflineDocumentParser 输出结构化）② **EvidenceSpan**（抽取片段→source doc/version/位置的可追溯证据跨度·晋级资产引 evidence_ref）③ ExtractionRun（抽取一次落账）④ ExtractedStrategySpec/ExtractedModelClaim（抽取出的策略/模型声明·标「抽取自文档·未验证」诚实）。**建在 stub parser 抽象上**（真 PDF/OOXML 库=用户选型待定·本卡抽取逻辑+EvidenceSpan 结构独立于真解析器）。

## 领地（扩 documents/·扩展不替换）
扩 `app/backend/app/documents/`（extraction.py：DocumentBlock/TableArtifact/FormulaArtifact + EvidenceSpan + ExtractionRun + ExtractedStrategySpec/ModelClaim）。**复用** documents/sandbox(OfflineDocumentParser·不改安全门)、lineage/ids、lineage/ledger(ExtractionRun 落账)。**绝不碰** main.py、documents/safety·intake 安全门(只复用)、其他在飞线。

## 可证伪验收（种坏门必抓·§6）
1. EvidenceSpan 缺 source doc/version/位置追溯 → 拒（对抗：孤儿 EvidenceSpan→必拒；MUT 放过→红）。
2. ExtractedStrategySpec/ModelClaim 未标「抽取自文档·未验证残余」→ 拒（诚实·抽取≠已验证·不假绿灯）。
3. 抽取经 sandbox OfflineDocumentParser（不绕安全门直解析）→ 验证经安全栈。
4. ExtractionRun 落账可 replay·正路径不误伤。

## 红线 [按需]
抽取经 sandbox 安全门不绕·EvidenceSpan 可追溯·ExtractedSpec 标未验证(抽取≠已验证·不假绿灯)·复用 ids/ledger 不另造·扩展不替换·先读 GOAL §6 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不接真 PDF/OOXML 解析库(用户选型·建在 stub 抽象)；不接 main.py；不做 hypothesis/preregistration 接线(下游)。本卡只抽取层 typed + EvidenceSpan + ExtractionRun。
