---
uuid: 66195b713b8e48b1bf9f7e836708efdb
title: Document Intelligence 摄入安全栈——quarantine/parser sandbox/no network/mime check/URL allowlist（§6·安全红线）
status: done
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

## 完成记录（2026-06-26·deep-opus 任务线·隔离 worktree·中心整合+跑全量+land）
- 分支：`wave7/document-intake`（基于 origin/main·前六波已 land）。中心负责整合 + 跑全量 + land（本线只跑 scoped）。
- 新建 greenfield `app/backend/app/documents/`（绝不碰 main.py / 外来 pickle 路 / 其他在飞线·扩展不替换）：
  - `safety.py` —— 纯·无副作用安全门：`sniff_format`/`assert_mime_matches_extension`（魔数 vs 扩展名·抓伪装可执行/异类容器）、`assert_url_allowed`（scheme + 私网字面 IP·is_global + allowlist 白名单制·防 SSRF）、`no_network()`（socket 层 fail-closed 上下文·封 getaddrinfo/create_connection/socket.connect(_ex)·解析器禁联网）、`IntakeLimits`+`check_size`/`check_pages`/`inspect_archive_safety`（只读 zip 中央目录·不解压·抓 zip bomb）。`DocumentIntakeError` = 平行 `ArtifactTrustError` 的硬拒点。
  - `sandbox.py` —— `SafeDocumentParser`（把离线解析器包进 `no_network()` + 页数限额门）+ `OfflineDocumentParser` 协议 + `StubOfflineParser`（占位·真 PDF 库=用户拍·follow-on）。沙箱入口签名只收 bytes+format → 结构上凭据无处可入（兑现「实盘 key 不进解析器」）。
  - `intake.py` —— 对象 `SourceDocument`/`DocumentVersion`/`LicenseRecord`（license 非空硬校·绝不静默伪造许可）+ 内容寻址金库 `DocumentVault`（`raw/` 不可变原件审计 → `quarantine/` 隔离区·解析只读副本 → `documents.jsonl` append-only + prev_hash 链·tamper-evident）+ fail-closed 编排 `intake_document`（严格按 §6 顺序：URL门→size门→raw vault→quarantine→mime门→archive门→license门→sandbox解析→入账）。
  - `__init__.py` —— 公共 API re-export（22 项）。
  - **身份哈希纪律**：完整 256-bit sha256 = source hash / 内容地址 / 安全绑定键；16 位 id 复用 `lineage.ids.content_hash`（单一身份源·不另造）—— 与 `training/artifact_trust.py` 同纪律。
- **真测试**：`app/backend/tests/test_document_intake_security.py` —— **58 passed in 0.10s**（`python3 -m pytest app/backend/tests/test_document_intake_security.py -q`）。
- **对抗测试（种坏门必抓·MUT 全程离线·no-network 在 socket 层拦下绝不真发网络）**：
  1. 伪装扩展名：`.pdf/.docx/.txt/.csv` 实为 ELF/PE/Mach-O/shebang/异类容器 → 8 参数化 + 容器伪装 + 头部太短 fail-closed + 端到端 intake → **全拒**；正路径真 %PDF-/PK 不误伤。✅
  2. SSRF/allowlist：169.254.169.254 云元数据 / 127.0.0.1 / 10.x / 192.168.x / ::1 / 0.0.0.0 / 100.64 CGNAT / file:// / gopher:// / data: / ftp:// / localhost / *.internal / 不在 allowlist / 前缀混淆 / 后缀混淆攻击（arxiv.org.evil.com）→ 16 参数化 **全拒**；arxiv.org + 子域 export.arxiv.org 放行。端到端 intake 未授权 origin → 拒。✅
  3. no-network parser：解析器试 `create_connection`/`urllib.urlopen`/裸 socket connect → 3 MUT **全拒**；端到端 intake 接恶意联网解析器 → 拒；上下文退出还原全局 socket 不泄漏；离线 stub 不误伤。✅
  4. zip bomb/DoS：高压缩比 / 解压总量 / 条目数 / 损坏 zip / 页炸弹 / 超 size（内存 + path stat 预检）→ **全拒**；非 zip 不走 archive 门、小 docx 不误伤。✅
  5. 隔离真生效：raw vault 内容寻址落原件、quarantine 副本 ≠ 原件路径、解析器实见字节 = 隔离副本（证明喂自 quarantine 非信任原件）；**被拒恶意文档绝不入账（registry 空）、原件未被改动**。✅
  6. source hash + license：结果/入账记录均携 64-hex 完整 sha256 + license record；空 license → 拒；未知须显式 'unknown'。append-only prev_hash 链篡改可检出；content_id 复用 ids.content_hash 单一身份源。✅
- **基线**：collect-only 2285（main）→ **2343**（+58·无 collection error）；扩展不替换、零碰现有文件。Sibling 安全套件无干扰：`test_artifact_trust_gate.py`+`test_mainnet_guards.py` 20 passed、`test_security_gate_adversarial.py` 23 passed（no_network 全局 patch try/finally 还原·不泄漏）。
- **拍板项命中**：① PDF/OOXML 真解析库选型 = 用户拍 → 本卡只立沙箱边界 + `OfflineDocumentParser` 抽象 + `StubOfflineParser` 占位（注明 follow-on）。② 未撞「解析器须联网」红线岔路（魔数嗅探/zip 检查全 stdlib·零联网·zero new dep）。
- **诚实残余（🟡 = follow-on·非本卡 scope）**：① EvidenceSpan/DocumentBlock/TableArtifact/FormulaArtifact/ExtractedStrategySpec 结构化抽取未做（TASK 非目标）。② 真 PDF/OOXML 解析库接线（用户选型后替换 stub）。③ `no_network()` 是【同进程 best-effort】socket 门——挡 urllib/requests/httpx/裸 socket 现实路径；ctypes 直发 syscall / fork 子进程自建 socket 的绕过面需 OS 级沙箱（seccomp/network namespace/无网容器）根除（明确标注·领地外）。④ allowlist 内域名被 DNS-rebinding 重绑私网这层须由抓取层 resolve-and-pin 兜底（本卡不做 DNS·守 no-network 红线·抓取层=领地外 follow-on）。⑤ 真 HTTP 抓取路径（本卡只立 URL 门·不联网抓取）。⑥ 中心整合后跑全量 + land 未由本线执行（本线只 scoped·🟡≠✅）。
