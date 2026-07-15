# F3 §11 读侧 manifest re-verify — 跨厂商两轮判 NOT SOUND，parked 待 single-snapshot 重构 2026-07-15

> deep-opus 建 F3（§11 PIT 真实读侧：读价前拿磁盘字节 re-verify 注册 manifest 的 per-file sha256，
> 不符/缺 → fail-closed）→ 我同厂商 pre-review 判 sound → **codex 跨厂商 round1 判 NOT SOUND（3P0/P1 + 1 overclaim）**
> → deep-opus 修（闭 3/4）→ **codex 跨厂商 round2 re-verify 仍判 NOT SOUND（2 must-fix）**。**未 land、代码 parked
> 本地分支 `slice/f3-readside-parked`（commit d2ec4238），main 干净。** 本 session 第 4 次跨厂商 skeptic 守住边界
> （同厂商 pre-review 两次都漏）。redo 按下方 single-snapshot spec + 再跨厂商复验。

## 缺口（F3 要闭的真问题）
`factor_factory/panel_source.py::_load_real_panel` 过去按 file_paths 读 bars/adj 落盘应用 hfq，**从不复核磁盘字节
vs 注册的不可变 manifest** → 被换/被篡/损坏的 lake 文件被静默当「已验证 hfq 真实数据」端上去。F3 = 读价前
re-verify（sha256 不符 / 缺 manifest / manifest 不覆盖将读文件 → fail-closed raise，绝不降级合成）。

## round1（codex 判 NOT SOUND，4 洞）→ 修复结果
1. **partial/empty-manifest fail-open（P1，最利）**：`verify_manifest` 空 manifest 返 `(True,[])`；且从不校 manifest
   是否覆盖将读文件 → 删 manifest 里 bars 条目 + schema-valid 篡改 bars → 仅剩条目 hash 匹配 → 放行。
   **修 = `_assert_manifest_covers_reads`（非空 + 逐条 relative_path 安全[拒 abs/`..`/反斜杠/冒号/重复] + 覆盖
   将读文件，root 用写侧同一 `dataset_manifest_root`）。round2 判：静态攻击 CLOSED。**
2. **deletion → 静默降级合成（P1）**：`_present_real_version` 任一文件缺 → None → 合成，绕过 F3。
   **修 = 三态：absent/latest-None → 合成（CI degrade 保留）；verdict≠pass → 合成（registry 受信）；
   verdict=pass 但文件缺/空 → raise（不降级）。round2 判：CLOSED；blast-radius 干净（repo grep 证
   `resolve_panel_source` 唯一生产 caller = `load_market_panel`，无 provenance-only/endpoint 依赖不 raise）。**
3. **诚实越界（P2）**：docstring 称「不可变/篡改/替换」暗示对抗抗性，但研究面 manifest 是可覆写 JSON、
   `build_research_asset` **不写签名 receipt**（签名 receipt 只在 benchmark `build_chain` 给 forbidden cohort）。
   **修 = 改 F3 docstring 为「defense-in-depth 挡 drift/corruption/非对抗 swap，非 authenticity proof」+ 列残余。
   round2 判：F3 自身 docstring CLOSED，但见下方 must-fix#2。**
4. **verify-then-read TOCTOU（P1）**：hash 后 pl.read_parquet 重开，原子 swap 窗口。
   **修 = best-effort `_file_stat_snapshot`(size,mtime_ns) 读后复检 + 诚实标窗口收窄非闭合。round2 判：CLOSED as scoped。**

测试（codex round2 亲跑）：`test_panel_source_pit.py` **23 passed**、`test_data_quality + hs300_pipeline` **46 passed**。
变异牙口（deep-opus 报告）：移 FIX-1 门 → f3_07/08/09 红；移整门 → 7 红含 f3_05 polars ComputeError（证 verify 先于 parse）。

## round2 剩 2 must-fix（未闭 → 不 land）
1. **[P1] split-snapshot manifest 验证**（NEW / FIX-1 未真闭）：`_verify_real_manifest` 覆盖校读 manifest **A**
   (`panel_source.py:413/430`)，随后 `verify_manifest(path,root)` **重开重解析 manifest B**(`dataset_hash.py:167`)。
   两读间换 manifest：A 完整过覆盖门 → 换成省略 bars 条目的 B（bars 已 schema-valid 篡改）→ B 只 hash 剩余文件 →
   过；stat 基线在验证**之后**才起(`panel_source.py:466`) → 稳定的被篡 bars 被读回。**修 = 单快照：读/解析 manifest
   一次，覆盖 + sha256 都跑在**同一** `DatasetManifest` 对象上（给 `verify_manifest` 加接收已解析 manifest 的变体，
   或在 panel_source 内联 `_sha256_file` 比对已解析条目）；补 manifest-swap 回归测试。**
2. **[P1] research_quality_report 越界**：F3 自身 docstring 已诚实，但 `hs300_pipeline.py:645` `research_quality_report`
   仍称对抗完整性由**签名** registry/manifest 链保障——对研究面**为假**（无签名 receipt）。且残余列漏了 split-manifest race。
   **修 = 改该处措辞 + 补残余。**（注：这是移除假声明=诚实收窄，非新增机制。）

## redo spec（下次实现照此 + 再跨厂商复验）
- **单快照 manifest 验证**：`_verify_real_manifest` 读 manifest bytes 一次 → 解析成 `DatasetManifest` → 覆盖校 + 逐文件
  `_sha256_file` 比对**都对这一个对象**，绝不二次读 manifest 文件。这把 FIX-1 从「静态闭、race 可绕」升成 race-robust。
- **producer 诚实**：`research_quality_report` 删「签名链挡对抗」对研究面的假声明；残余列加 split-manifest race。
- 保留 round1 已闭的 FIX-2/3/4 + 全部测试（parked 分支 d2ec4238 是 3/4-closed 基座，redo 只需重构 FIX-1 的 manifest 读 + 改 producer 措辞）。
- **威胁模型诚实边界**（landable 版必须写清）：F3 挡**静态** drift/corruption/文件换（present 且 hash 不符）+ 静态 partial/empty manifest +
  静默 deletion 降级；**不挡**：manifest+lake co-tamper（manifest 无签名可覆写）、data 或 manifest 的并发原子 swap（含 split-snapshot）、
  registry 被篡（改 verdict/file_paths）。是 defense-in-depth，非 authenticity proof。

## 状态 — ✅ 已 land（918daf7f，round3 SOUND）
**更新 2026-07-15**：按上方 single-snapshot spec 修完。FIX-A 单快照：`data_hash` 加 `verify_manifest_obj(manifest,root)`（additive，
`verify_manifest` 委派、字节级不变，既有 caller 不动）；`_verify_real_manifest` 解析 manifest **一次**，覆盖门 + `verify_manifest_obj`
sha256 跑在**同一** `DatasetManifest` 对象上，无二次读盘。FIX-B：`research_quality_report` 删「签名链挡对抗」假声明、诚实收窄。
新测 `f3_12` 单快照 swap：spy 令 read#1 全量、read#2 缺 bars 条目 + 篡改 bars → 单快照必 raise，且断言 `reads==1`；two-read 变异翻红。
**codex round3 跨厂商 re-verify 判 SOUND to land**（FIX-A/B CLOSED·无新洞·空 manifest 仍先 raise·verify 仍先于 parse）。
land gate 全绿：后端全量 **6487 passed/13 skipped**、perf harness 72、前端 40 files/430 + build ✓、compileall、validate_dev PASS、
audit 基线 `1c1788b0` 不变。产品码 commit **918daf7f** 进 main；parked 分支 d2ec4238 被取代。
**教训**：同厂商 pre-review 两轮全漏（判 sound 却各有洞），3 轮跨厂商 codex skeptic 逐轮收敛（4→2→0）才 SOUND——**再证触碰
completeness/honesty 的改动必须跨厂商复验，且可能需多轮**。残余（如实登记、非 fail-open，需研究面签名 receipt 后续卡）：
未签名 manifest 的 manifest+lake co-tamper、size+mtime 保持的原子 data-file swap。
