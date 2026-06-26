---
uuid: 2bac27d322c840888963b1151df939ac
title: Document EvidenceSpan 抽取——DocumentBlock/TableArtifact/FormulaArtifact/EvidenceSpan/ExtractedStrategySpec（§6 续）
status: done
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
扩 `app/backend/app/documents/`（extraction.py：DocumentBlock/TableArtifact/FormulaArtifact + EvidenceSpan + ExtractionRun + ExtractedStrategySpec/ModelClaim）。**复用** documents/sandbox(OfflineDocumentParser·不改安全门)、lineage/ids、lineage/ledger 落账纪律。**绝不碰** main.py、documents/safety·intake 安全门(只复用)、其他在飞线。

## 可证伪验收（种坏门必抓·§6）
1. EvidenceSpan 缺 source doc/version/位置追溯 → 拒（对抗：孤儿 EvidenceSpan→必拒；MUT 放过→红）。
2. ExtractedStrategySpec/ModelClaim 未标「抽取自文档·未验证残余」→ 拒（诚实·抽取≠已验证·不假绿灯）。
3. 抽取经 sandbox OfflineDocumentParser（不绕安全门直解析）→ 验证经安全栈。
4. ExtractionRun 落账可 replay·正路径不误伤。

## 红线 [按需]
抽取经 sandbox 安全门不绕·EvidenceSpan 可追溯·ExtractedSpec 标未验证(抽取≠已验证·不假绿灯)·复用 ids/ledger 不另造·扩展不替换·先读 GOAL §6 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不接真 PDF/OOXML 解析库(用户选型·建在 stub 抽象)；不接 main.py；不做 hypothesis/preregistration 接线(下游)。本卡只抽取层 typed + EvidenceSpan + ExtractionRun。

---

## 实现落账（done · 2026-06-26 · deep-opus 任务线 · 分支 wave8/document-evidence）

**改动文件（2 个·纯新增·扩展不替换·零 tracked 文件被改）：**
- `app/backend/app/documents/extraction.py`（新模块·全部 §6 抽取层 typed + 守门 + 沙箱抽取 + 落账）。
- `app/backend/tests/test_document_extraction.py`（新对抗测试·42 例）。
- `git diff --name-only HEAD` 空 —— main.py / documents/safety·intake·sandbox 安全门 / lineage(ids·ledger) / documents/__init__.py **一字未改**（全程只 import 复用）。

**建了什么（GOAL §6 契约逐条落地）：**
- 解析产物 typed：`DocumentBlock`（block_id 内容寻址·绑 doc_version+parser_run+位置+text_hash）/ `TableArtifact` / `FormulaArtifact` / `ReferenceArtifact`，各自 linked by block_id、携 page/bbox/section/char_span。
- `BlockPosition`：page/bbox/section/char_span，**至少一个定位器在场否则即拒**。明确两级寻址口径——block 的 char_span 是 doc-relative、EvidenceSpan 的 char_span 是 block-relative（整块=`(0,len)`），span-support 复算只需该 block（本地·tamper-evident）。
- **`EvidenceSpan`**：GOAL §6 必含字段全在场（source_id / doc_version_id / parser_run_id / block_id / page·bbox·section·char_span / quoted_excerpt_hash / parser_confidence / span_support_verification）。`__post_init__` 硬拦孤儿（任一追溯键空 / 无定位器 / 置信度越界 / 引文与哈希自相矛盾 → 拒）。`span_id` 内容寻址且**刻意排除 support**（验证态可变·身份不变）。`from_block` 免手算构造（杜绝把 doc-relative 偏移误当 block-relative 的脚枪）。
- **span-support 验证**（抗伪造核心）：`verify_span_support` 把 reader（untrusted）所称引文**对回源 block 的 char_span 复算哈希**——位置/内容对不上、悬挂 block、跨文档 block → `challenged`，不进 confirmatory（GOAL §6「未过 span-support → challenged」）。`confirmatory_ready` 仅当所引 span 全 `supported` 才放行（保守·不假绿灯）。
- `ExtractedStrategySpec` / `ExtractedModelClaim`：硬标 `verification_status == extracted_unverified`（抽取层永不发其它绿灯态）+ 不可去除 disclosure（含「未验证」marker）+ evidence_refs 非空；`create` 默认即诚实标注。编排层再拦悬挂 evidence_ref（引本次未产出的 span → 拒）。
- 沙箱抽取：`SandboxedBlockExtractor`（mirror `sandbox.SafeDocumentParser`）把抽取器 parse+切块**全程包进 `safety.no_network()`** + 过 `check_pages` 限额门——抽取**经安全门不绕**。`StubBlockExtractor`（继承 `StubOfflineParser`）文本族给**精确 char_span**（span-support 货真价实）、二进制族**诚实留白不伪造块**（真解析库=用户选型）。
- `ExtractionRun` + `ExtractionLedger`：run_id 内容寻址（只由抽取**输入**定·排除产物 id 与时间戳）→ **同输入 replay 命中存量不重复落账**；append-only prev_hash 哈希链（mirror `intake.DocumentRegistry`·复用 `ids.content_hash` 算行指纹），`verify_chain` 可对账揪事后篡改。

**工程取舍裁定（已按卡精神 + 落地先例定·未阻塞·供中心复核）：**
- ExtractionRun「落账」走 **documents 侧独立哈希链账**（`ExtractionLedger`），**不**塞进 honest-N `lineage.ledger.Ledger`。理由：honest-N 账是试验计数单元（`ALLOWED_KINDS={backtest,train,card_freeze,factor_eval}`、键=(config_hash,strategy_goal_ref)），抽取运行非试验——塞进去要么触 `__post_init__` 拒、要么虚高 honest-N（作弊面）；且改 `ledger.py` 越领地。`intake.py` 已立先例（`DocumentRegistry` 文档侧独立链账·注释明写「绝不与 honest-N Ledger 混账」），本卡延续同纪律。「复用 lineage/ledger」= 复用其 append-only 哈希链**范式** + `ids.content_hash` 行指纹，非物理同账；「不另造」红线针对的是第二套 config_hash / 第二本 honest-N，不含证据/抽取溯源链（与文档溯源链同列）。

**门必抓（42 测试·真实 MUT 验证·绝不 git checkout）：**
- 验收 #1 孤儿 EvidenceSpan：缺 source/version/parser_run/block 任一键、无定位器、置信度越界、引文哈希自相矛盾 → 全拒。
- 验收 #2 未标未验证：spec/claim 空 evidence_refs、标 validated/proof_backed/production_ready/supported、抽 disclosure marker → 全拒；悬挂 evidence_ref → 编排拒。
- 验收 #3 经沙箱：抽取器 parse 内联网 / extract_blocks 裸 socket / 页炸弹 / 产非 RawBlock → 全拒（no-network + 限额门）；二进制不伪造块。
- 验收 #4 落账 replay：同输入同 run_id + 二次命中存量 + 重开 ledger 仍命中 + 篡改 verify_chain 揪出 + run_id 排除产物/时间戳；独立账非 honest-N（无 config_hash/strategy_goal_ref）。
- span-support：真引文 supported / 伪造引文·悬挂·跨文档 challenged / confirmatory 需全 span supported。
- 正路径：真文本→真 block(真 char_span)→真 span(supported)→合法未验证 spec→run 落账；FormulaArtifact 非 MathematicalArtifact（无适用域/推导/反例·诚实 note）；与摄入安全栈集成（复用 intake 给的 source_id/doc_version_id/content_sha256·读隔离副本）。
- **真实变异证伪**（手改源·非 git checkout·手改回）：临时禁掉 EvidenceSpan.block_id 守门 + ExtractedSpec.verification_status 守门 → 对应对抗例 **8 例 DID NOT RAISE 转红**（证守门承重）；手改回 → 42 全绿、源无残留 marker。

**真测试汇总行（scoped·未跑全量）：**
- `tests/test_document_extraction.py` → **42 passed in 0.06s**（新增）。
- 回归零破：`tests/test_document_intake_security.py + test_intake.py + test_doc_alignment.py` → **61 passed**；`-k "ledger or lineage or ids"` → **91 passed, 2411 deselected**。
- collect-only：基线 **2460 → 2502**（+42·恰为新增·无 collection 破坏）。

**诚实残余 / 限界：**
1. **真 PDF/OOXML 解析库 = 用户选型待定**：本卡建在 stub 抽象上。`StubBlockExtractor` 文本族 char_span 精确（span-support 真复算）、二进制族诚实留白不伪造块。接真解析库后只换 `DocumentBlockExtractor` 实现，EvidenceSpan/守门/落账结构不动。
2. **Reader = untrusted·真实现下游**：本卡只给协议（`DocumentReader`）+ 验证机（span-support·悬挂引用拦截）+ schema 守门；真 Reader（LLM/规则引擎）= 用户/下游。GOAL §6「Reader 抽证据·privileged tool-holder 只消费 schema 约束产物」边界本卡守住（产物全经验证才可信）。
3. **下游未接**：hypothesis/preregistration/experiment plan 链路（GOAL §6 抽取→晋级后段）= 下游卡，非本卡。`ExtractedSpec` 标 extracted_unverified、confirmatory 门已就绪供下游消费。
4. **no-network 诚实边界沿用安全门**：in-process socket 层 best-effort（ctypes 直发 syscall / fork 子进程绕过须 OS 级沙箱根除）—— 复用 `safety.no_network` 既有限界，本卡不放大也不削弱。
5. **span-support 诚实措辞**：验证的是「引文是否复算命中所称位置」，不对文档内容真伪/论断对错下结论（challenged≠内容假·supported≠内容真）。
