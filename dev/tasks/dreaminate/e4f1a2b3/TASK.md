---
uuid: e4f1a2b3c5d64e7f8a9b0c1d2e3f4a5b
title: §13 信任层硬约束 advisory 接进 agent orchestrator 输出/审查路径（反谄媚·诚实·弱点不隐藏在 agent 路径生效）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: trust-layer
source: goal-gap
source_ref: GOAL §13 信任层（行 1816 起）+ §7 Agent Shell；第八波信任层硬约束门(0d7c9511)建好但「接交付编排/agent 路径」留 follow-on——门已建·orchestrator 已建(四波)·wiring 是 §13 在 agent 路径的 enforce 缺口
depends_on: []
---

# §13 信任层硬约束 advisory 接进 agent orchestrator 输出/审查路径

## Scope [必填·先读 GOAL §13+§7]
第八波建的 `trust/`（trust_constraints + ResponsibilityDisclosureRecord·反谄媚/诚实硬约束/弱点不隐藏/waiver 不绕 safety）目前**未接 agent orchestrator**——agent 产出（研究结论/推荐/review）没经 §13 信任层检查。本卡把 trust_constraints 作 **advisory** 接进 orchestrator 的输出/审查路径：agent 产出经 §13 检查 → trust 裁决 attach 进事件流/输出（**advisory-first：只标记不阻断 agent**·守不预先削弱·不破既有 orchestrator 行为）。

**先勘察定攻入点**（deep-opus 自己读 + 判，无清晰点则诚实报告不硬塞）：`agent/orchestrator/`（orchestrator.py 主流程 / roles.py 12 角色含 Review / events.py 24 可见事件）哪里是 agent 产出/review 的钩子。最干净落点：Review 形态或输出汇总处加 §13 advisory 检查，trust 裁决经 on_event 发一条可见事件 / attach 进 review 结果。

## 领地（只动·扩展不替换·additive）
- `app/backend/app/agent/orchestrator/`（在输出/审查钩子加 advisory §13 检查·扩展不替换·不改既有 DAG/工具派发治理 GovernedToolDispatcher）。
- 新测试。
- **复用只读不改**：`trust/`（trust_constraints 门 + ResponsibilityDisclosureRecord·判定全委派·不重造）、`governance/spine_invariants`（如顺带需要·只读）。
- **绝不碰**：`main.py`（接 main.py=中心后续）、`trust/` 内部、`release_gate/`、其它在飞线。**若 orchestrator 无清晰 advisory 攻入点 → 停下诚实报告**（不硬塞破坏既有流）。

## 可证伪验收（种坏门必抓·§13）
1. **谄媚/弱点隐藏产出被 advisory 标记**：agent 产出含谄媚措辞 / 隐藏弱点 / 对 user_pressure 松口 → §13 trust 裁决标 flag（种坏：advisory 不跑 / 总过 → 漏标 → 测试 RED）。
2. **诚实产出不误伤**：诚实标弱点/不确定性的产出 → trust 裁决过·不误标。
3. **advisory 不阻断 agent**：即便 §13 标 flag，orchestrator 主流程仍跑完（只标记不 block·守不预先削弱·既有 orchestrator 测试不破）。
4. **waiver 不绕 safety**：若产出路径带 waiver，§13 命门仍不让 waiver 绕 secret/OrderGuard/kill switch/no-silent-mock（复用 trust 命门·不在此削弱）。

## 红线 [按需]
advisory 只标记不阻断（不预先削弱·不破基线）·复用 trust_constraints 判定零重写·扩展不替换·不改 GovernedToolDispatcher·反谄媚对 user_pressure 对称不松口·waiver 不绕 safety 命门·先读 GOAL §13+§7。无新公式→不造 MathematicalArtifact。

## 非目标 [按需]
不接 main.py（中心后续）；不改 trust/ 门判定内部；不动工具派发治理；不做 §13 硬 enforce（本波 advisory·硬卡 agent=后续显式决策）。§8 governance 接 orchestrator=另卡。

## 完成口径（隔离 worktree 自跑·中心整合）
- 先读 `~/.claude/CLAUDE.md` + 项目 `CLAUDE.md` + `dev/RULES.md` + `dev/RULES.project.md` + **GOAL §13（行 1816 起）+ §7**；读 `trust/`（门接口）+ `agent/orchestrator/`（攻入点）。
- 数学先行：无新公式→不造 MathematicalArtifact。
- 对抗测试种坏门必抓（上 4 条）+ **MUT**（in-place Edit 削弱核心 §13 advisory 门→RED→手工复原→GREEN·**绝不 git checkout**）。
- 跑 scoped + 触及 orchestrator 测试定向回归（**绝不叠跑全量**·中心统一跑）。凭真汇总行判绿。
- 自建分支 `wave13/trust-orchestrator-advisory`（基于 origin/main）·commit（省略 Claude co-author 行）+ push·**不 land**。
- 回报：分支+commit、文件清单、攻入点选择理由、真测试汇总行+collect+定向回归、对抗 4 条逐条、MUT 三态、红线合规、**触禁区冲突/诚实残余/follow-on**（含：若无清晰攻入点的诚实说明）。review_status 留 0。
