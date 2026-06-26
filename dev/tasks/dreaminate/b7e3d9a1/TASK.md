---
uuid: b7e3d9a1c4f8460b8d2a6e9f1c5b3a07
title: promote 时把执行诚实(injection 状态)落进 run.json·闭 §16 致命「声称已采用却未注入/模板基线」(LINE-E·§16)
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: release-gate
source: goal-gap
source_ref: GOAL §16 工程标准(行 1969 起·致命「未注入资产却声称已采用」/no template false success) + §0；第十波组装器(f2a9c4e1)暴露的 KNOWN_RUN_GAPS——run.json 不带 injection 状态/执行诚实标识→组装器无从核模板基线
depends_on: [f2a9c4e1b8d7460a9c3e1f5b6a2d8e04]
---

# promote 时把执行诚实(injection 状态)落进 run.json·闭 §16 致命

## Scope [必填·先读 GOAL §16+§0]
第十波建的 `release_gate/promote_assembler.py` 能把 run.json 的 `execution_blocks` 映射成 ReleaseCandidate 经 §16 mock 诚实门（R1/R4/R5）裁定。**但现 promote producer 不写 `execution_blocks`** → 组装器恒空、门平凡过、**§16 致命「未注入资产却声称已采用 / 模板基线冒充生产成功」当前不闭合**。本卡把 producer 端补上：promote 时按**真实执行诚实**写出 `execution_blocks` 进 run.json，让组装器+R4 能抓住模板基线冒充。

**最关键（§16 致命）**：`app/backend/app/agent/business_tools.py` 的 `_synth_and_promote` 现有 `assembly_injected` 标志 + 模板基线 note **只进返回 dict、不进 run.json**。本卡：injection=False（模板基线/未真注入资产却走 promote）→ 写 `execution_blocks=[{mode:"template", result_grade:"production"/"none", ...}]`（让组装器映射→evaluate_release R4「template 标 production 成功」硬拒）；真注入（live source）→ 写 `mode:"live"+live_source_ref`（R1 要求 live 必有 source）。

## 领地（只动·扩展不替换·additive opt-in）
- `app/backend/app/agent/business_tools.py`（`_synth_and_promote`：把 injection 状态/执行诚实映射成 execution_blocks，经 promote_ide_run 写进 run.json）。
- `app/backend/app/ide/promote.py`（`promote_ide_run`：加可选 `execution_blocks` 参数透传进 manifest，**与既有 extra_metadata 同范式·opt-in 向后兼容**·不传则行为不变）。
- 新测试 `tests/test_promote_execution_honesty.py`。
- **复用只读不改**：`release_gate/promote_assembler.py`、`release_gate/mock_honesty.py`（ExecutionBlock mode/result_grade 语义·R1/R4/R5 单一源）。键名对齐组装器 `_execution_block_from_dict` 读的字段（mode/block_id/result_grade/mock_marked/live_source_ref/fallback_reason/note）。
- **绝不碰**：`main.py`（接 promote 端点=中心下波）、`release_gate/` 内部、`promote_assembler.py` 内部、`approval/`、其它在飞线。

## 可证伪验收（种坏门必抓·§16 致命）
1. **模板基线必被抓**：`_synth_and_promote` injection=False/模板基线 → run.json 写 template execution_block → `evaluate_run_releasable(run.json)` 经 R4 **硬拒**（种坏：不写 block / 写成 live 冒充 → 致命门平凡过 = 漏「声称已采用却未注入」→ 测试必 RED）。
2. **真注入不误伤**：真 live source 注入 → 写 live block + live_source_ref → 不被 R1 误拒（live 有 source）。
3. **mock 必挂标识**：mock 执行 → mock_marked=True，否则 R1 silent mock 硬拒。
4. **向后兼容**：promote_ide_run 不传 execution_blocks → manifest 无该键、既有行为/既有 run.json 消费方不破（既有测试全绿）。
5. **不静默改裁决**：本卡只让 run.json 诚实携带执行事实 + 组装器能读到；是否在 promote 端点 enforce（拒晋级）=中心下波 advisory-first 决定·本卡不接端点不改晋级行为（仅补数据 + 可被组装器核）。

## 红线 [按需]
no template false success（§16 致命）·no silent mock fallback·缺/未注入绝不写成 live 冒充·扩展不替换·复用 mock_honesty/组装器键不另造·先读 GOAL §16+§0。无新公式→不造 MathematicalArtifact。单一身份源 ids.content_hash 不另造。

## 非目标 [按需]
不接 main.py promote 端点（中心下波 advisory-first 接 evaluate_run_releasable + 决定是否 enforce）；不改组装器/release_gate 判定；本卡只补 producer 端 run.json 执行诚实落账。dataset_version/LLMCallRecord 落账=后续卡（本卡聚焦 injection/执行诚实这条 §16 致命链）。

## 完成口径（隔离 worktree 自跑·中心整合）
- 先读 `~/.claude/CLAUDE.md` + 项目 `CLAUDE.md` + `dev/RULES.md` + `dev/RULES.project.md` + **GOAL §16（行 1969 起）+ §0**；读 `promote_assembler.py`（学它读哪些 execution_block 字段）+ `mock_honesty.py`（ExecutionBlock mode/grade 语义 + R1/R4/R5）+ `ide/promote.py`（manifest/extra_metadata 范式）+ `business_tools.py _synth_and_promote`（现 assembly_injected 流向）。
- 数学先行：无新公式 → 不造 MathematicalArtifact。
- 对抗测试种坏门必抓（上 5 条）+ **MUT**（in-place Edit 削弱核心致命门→RED→手工复原→GREEN·**绝不 git checkout**）。
- 只跑 scoped：`cd app/backend && pytest tests/test_promote_execution_honesty.py -x -q --timeout=300` + 触及模块定向回归（business_tools/promote 相关·**不叠跑全量**·中心统一跑）。凭真汇总行判绿。
- 自建分支 `wave11/promote-execution-honesty`（基于 origin/main）·commit（省略 Claude co-author 行）+ push·**不 land**。
- 回报：分支+commit、文件清单、真测试汇总行+collect、对抗 5 条逐条、MUT 三态、红线合规、**触禁区冲突/诚实残余/follow-on**（尤其：还有哪些 run 类型的执行诚实未落账·中心接端点时要知道）。review_status 留 0。
