---
uuid: 66195b713b8e48b1bf9f7e836708efdb
title: Document Intelligence 摄入安全栈——quarantine/parser sandbox/no network/mime check/URL allowlist（§6·安全红线）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: documents
source: goal
source_ref: GOAL §6 Research/Document Intelligence(行 812+·Document Intelligence Plane·Source intake:raw vault/quarantine/parser sandbox/mime·magic check/URL allowlist/size·page·compression limits/no network parser/source hash/license record)
depends_on: []
---

# Document Intelligence 摄入安全栈（§6·外来文档=RCE-adjacent 攻击面·安全优先）

## Scope [必填·先读 GOAL §6]
建 §6 Document Intelligence **摄入安全栈第一切片**（先安全后抽取）：① SourceDocument/DocumentVersion 对象 + source hash + license/rights record ② **Source intake 安全门**：raw vault → quarantine → parser sandbox·mime/magic check（防伪装扩展名）·URL allowlist（防 SSRF/外联）·size/page/compression limits（防 zip bomb/DoS）·**no network parser**（解析器禁联网·防外联泄露/SSRF）。**外来文档解析 = 与外来 pickle 同级攻击面**（恶意 PDF/文档可 RCE/SSRF/DoS）——本卡先把摄入安全边界立死，EvidenceSpan/抽取/ExtractedStrategySpec 作 follow-on。

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/documents/`（intake.py：SourceDocument/DocumentVersion + quarantine/sandbox/mime/allowlist/limits/no-network 安全门 + source hash）。**复用** lineage/ids（content hash·source hash）、security/keystore 模式。**绝不碰** main.py、其他在飞线、外来 pickle 加载路（已有 artifact_trust 范式参考）。

## 可证伪验收（种坏门必抓·§6·安全红线）
1. mime/magic 与扩展名不符（伪装文档）→ 拒（对抗：.pdf 实为可执行→必拒；MUT 放过→红）。
2. URL 不在 allowlist（外联/SSRF）→ 拒；解析器尝试联网 → 拒（no network parser）。
3. 超 size/page/compression limit（zip bomb/DoS）→ 拒。
4. 文档先进 quarantine 再 sandbox 解析（绝不直接信任外来文档）→ 验证隔离真生效。
5. source hash + license record 在场（可追溯·合规）。

## 红线 [按需]
**外来文档=攻击面·绝不直接信任**(quarantine+sandbox+no network)·防 SSRF/zip bomb/伪装扩展名·复用 lineage/ids content hash·扩展不替换·实盘 key 不进解析器·先读 GOAL §6 再动手。**撞「解析器须联网才能解析」之类岔路停报中心**(no network parser 是红线)。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不做 EvidenceSpan 抽取/ExtractedStrategySpec/数学抽取（follow-on）；不接真 PDF 解析库（库选型=用户拍·本卡建安全门框架·解析器 stub/抽象）；不接 main.py。本卡只摄入安全栈（quarantine/sandbox/mime/allowlist/limits/no-network）。
