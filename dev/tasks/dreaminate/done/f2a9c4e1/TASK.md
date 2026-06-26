---
uuid: f2a9c4e1b8d7460a9c3e1f5b6a2d8e04
title: 发版门禁接 promote 证据组装器（run→ReleaseCandidate·诚实有/缺·LINE-E·§16/§0）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: release-gate
source: goal-gap
source_ref: GOAL §16 工程标准 release gate（行 1969 起）+ §0 可上线七条；第九波收敛判断「各门接 promote 真晋级需输入管线·硬接=空壳」的输入管线第一块
depends_on: []
---

# 发版门禁接 promote 证据组装器（run→ReleaseCandidate）

## Scope [必填·先读 GOAL §16+§0]
建 **promote 证据组装器**——已建 `release_gate.evaluate_release(ReleaseCandidate)`（§16 八门聚合）目前**无生产调用方**：缺一个把"已 promote 的 run"映射成 `ReleaseCandidate` 的输入管线。本卡建这块**孤立 lib**：`assemble_release_candidate(run_manifest, *, ledger=None, ...) → ReleaseCandidate`，从 run.json manifest（run_id/strategy_id/metrics/gate_verdict/**assembly_inputs**/source）+ 可选 ledger 证据，**诚实映射**：有的证据填进对应字段、**缺的留空标缺（绝不编造 binding/dataset_version/checksum/MCR）**。再给一个 `evaluate_run_releasable(run_manifest, ...) → ReleaseValidation` 薄 helper（组装→evaluate_release）。**这是输入管线第一块**，让中心下波能把 `evaluate_run_releasable` 接进 promote 端点（advisory-first）。

## 领地（greenfield·只动·扩展不替换）
新建 `app/backend/app/release_gate/promote_assembler.py`（组装器 + 薄 evaluate helper）+ 新测试 `tests/test_promote_assembler.py`。**复用只读**：`release_gate.release_gate`（ReleaseCandidate/evaluate_release·不改）、`release_gate.mock_honesty`（ExecutionBlock·不改）、run.json manifest 形状（ide/promote.py 产·只读参照）。**绝不碰**：`main.py`、`ide/promote.py`、`release_gate/release_gate.py` 内部、`approval/`、其它在飞线。接进真 promote 端点 = 中心下波 follow-on（本卡只交可调用的组装器+helper）。

## 可证伪验收（种坏门必抓·§16/§0 诚实）
1. **缺证据不编造**：run 无 TheoryImplementationBinding → 组装器 binding 留 None（不伪造）→ proof-backed 声明时 evaluate_release honest_gaps/missing 含 binding（种"组装器随手造个空 binding 蒙混"→必被诚实门抓）。
2. **dataset_version/checksum 缺 → 诚实标缺**：assembly_inputs 无 dataset 身份 → dataset_versions=() → §16③ 缺口 surface（种"用占位 checksum 填充"→拒）。
3. **mock/fallback 执行块诚实**：run.json 的执行诚实标识（若有）映射成 ExecutionBlock → silent mock / template 标生产成功 → 经 release_gate R1/R4 必拒（不在组装器二次洗白）。
4. **assembly_inputs 真透传**：factor_set/model_id 等组装意图原样映射、不静默丢；缺则不编造。
5. **正路径不误伤**：证据齐全的 run（proof-backed + TIB + ConsistencyCheck + dataset_version + MCR）→ 组装出的 candidate 经 evaluate_release ok=True。

## 红线 [按需]
no silent mock fallback·no template false success·**绝不编造缺失证据**（缺即诚实标缺·这正是 §0「不给假绿灯」对准自己）·复用 release_gate 不重造判定·扩展不替换·先读 GOAL §16+§0。无新公式→不强造 MathematicalArtifact。单一身份源：asset_ref/code_hash 复用 ids.content_hash 口径、不另造。

## 非目标 [按需]
不接 main.py / 真 promote 端点（中心下波 advisory-first 接线）；不改 release_gate 判定内部（只组装输入）；不碰 approval 门。

## 完成口径（隔离 worktree 自跑·中心整合）
- 先读 `~/.claude/CLAUDE.md` + 项目 `CLAUDE.md` + `dev/RULES.md` + `dev/RULES.project.md` + **GOAL §16（行 1969 起）+ §0**。
- 数学先行：本卡无新公式（组装映射非数学口径）→ 不造 MathematicalArtifact。
- 对抗测试种坏门必抓（按上 5 条）+ **MUT**（in-place Edit 削弱核心门→测试转 RED→手工复原→GREEN·**绝不 git checkout**）。
- 只跑 scoped：`cd app/backend && pytest tests/test_promote_assembler.py -x -q --timeout=300`·凭真汇总行判绿·**绝不叠跑全量**（中心整合统一跑）。
- 自建分支 `wave10/promote-assembler`（基于 origin/main）·commit（省略 Claude co-author 行）+ push·**不 land**。
- 回报：分支+commit、文件清单、真测试汇总行+collect、对抗 5 条逐条、MUT 三态、红线合规、触禁区冲突/诚实残余/follow-on。review_status 留 0。

## 完成纪要（done · 第十波 · deep-opus 线 + 中心整合 land）
**分支**：`wave10/promote-assembler`（基于 origin/main 3b5d24f）·commit `682da76`·中心 merge 进 center-integ。

**交付（输入管线第一块·release_gate 接 promote 的前置）**：
- 新建 `app/release_gate/promote_assembler.py`（515 行）：run.json manifest → `ReleaseCandidate` **诚实映射器**·三入口 `assemble()/assemble_release_candidate()/evaluate_run_releasable()`·**只组装输入·判定全委派 evaluate_release**（零重写门逻辑）。缺证据留 None/()（不编造 binding/checksum/MCR/执行块）·执行块缺 mode/非法 mode → fail-closed raise（不静默吞）。
- 新建 `tests/test_promote_assembler.py`：28 对抗测（5 条种坏门 + ledger 探针 + helper 委派完整性）。

**测试**：opus scoped `28 passed in 0.17s`；**中心全量批次 2660 passed / 13 skipped / 0 failed / 118s**（collect 2673 = 基线 2645 + 28·精确吻合·flake 未触发）+ validate PASS。

**对抗 5 条 + MUT 两门三态**：缺 TIB 不编造(proof-backed→binding-exists 硬拒) / dataset 缺 checksum 不造占位(dataset 门硬拒) / mock·template·fallback 执行块经 R1·R4·R5 必拒 / assembly_inputs 真透传不静默丢 / 全证据正路径 ok=True 不误伤。MUT-A(占位 checksum)·MUT-B(空壳 binding)各削弱→RED→手工复原→GREEN·源码零残留。
**数学↔实现**：无新公式（纯映射管线）→ 不造 MathematicalArtifact；asset_ref=run_id 复用、ledger 重建的 binding_id/check_id 由 spine dataclass 自身复用 ids.content_hash 重算一致·未另造哈希。
**工程取舍（中心已 ratify）**：assembly_inputs 在 ReleaseCandidate(禁改)无字段可放 → opus 新增 `AssembledRelease` 包装(candidate + mapped/absent/honest_gaps + assembly_inputs)·`assemble()` 返它·薄包取 `.candidate`。判为"不静默丢"最干净落点·不碰 ReleaseCandidate·接受。

**★ 关键诚实缺口（opus 暴露·KNOWN_RUN_GAPS·= 第十一波中心活的精确指引）**：现 `ide/promote.py` 写的 run.json **不携带**这些证据，故此类 run 对应字段恒空、被诚实标缺：
- 执行诚实标识(live/mock/fallback/template) run.json 无 → execution_blocks 恒空 → mock 诚实门平凡过（非"已核 live"）。
- dataset_version+checksum run.json 无 → dataset 门平凡过。
- LLMCallRecord run.json 不记 → LLM 用了会漏审计。
- **⚠️ 最关键（§16 致命「未注入资产却声称已采用」真实未闭合处）**：`business_tools._synth_and_promote` 的 `assembly_injected=False` + 模板基线 note **只进返回 dict、不进 run.json**；run.json 只落 assembly_inputs(意图)。**组装器无从核"声称注入但实为模板基线"** → 中心须把 injection 状态写进 run.json，组装器才能映射成 MODE_TEMPLATE 执行块经 R4 硬拒。

**诚实残余 / 中心 follow-on（第十一波）**：
- 把 evaluate_run_releasable 接进 promote 端点（advisory-first·attach release_verdict 到 run.json·不破基线·enforce 仅 proof/theory-backed 声明时）。
- **先补 run.json 证据落账**（injection 状态/执行诚实标识/dataset 身份/LLMCallRecord）——否则组装器恒空标缺、门平凡过、§16 致命门不闭合。injection 状态是最高优先（§16 致命）。
- ledger 探针 duck-type SpineLedger；promote_ide_run 实际传的 T-013 Ledger 不持 spine 证据 → 主路径走显式注入参数喂真证据。
