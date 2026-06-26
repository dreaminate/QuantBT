---
uuid: f2a9c4e1b8d7460a9c3e1f5b6a2d8e04
title: 发版门禁接 promote 证据组装器（run→ReleaseCandidate·诚实有/缺·LINE-E·§16/§0）
status: in_progress
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
