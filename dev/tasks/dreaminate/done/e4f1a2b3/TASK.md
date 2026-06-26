---
uuid: e4f1a2b3c5d64e7f8a9b0c1d2e3f4a5b
title: §13 信任层硬约束 advisory 接进 agent orchestrator 输出/审查路径（反谄媚·诚实·弱点不隐藏在 agent 路径生效）
status: done
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

## 完成纪要（done · 第十三波 · deep-opus 线 + 中心整合 land）
**分支**：`wave13/trust-orchestrator-advisory`（基于 origin/main）·commit `970e255`·中心 merge 进 center-integ。

**攻入点（opus 勘察选定·有清晰落点）**：orchestrator 的 **Review 形态**新增 `advise_trust(ctx: TrustContext) → TrustAdvisory` 方法（与 plan/dispatch/admit_verifier_challenge 并列），把第八波 `trust/` 门接进 agent 审查路径。
**交付（+586/-2·additive 扩展不替换）**：
- 新建 `agent/orchestrator/trust_advisory.py`（188 行·TrustContext 姿态→trust 门裁定→TrustAdvisory 结果 + 可见事件投影·**判定零重写全委派 app.trust.evaluate_trust**）。
- `agent/orchestrator/orchestrator.py`（+35/-2·加 advise_trust 方法 + import·不改既有 DAG/dispatch 行为）+ `__init__.py` 导出。
- 新测试 `tests/test_trust_orchestrator_advisory.py`（352 行）。

**advisory-first 纪律 + ★ 命门不降级（关键正确处理）**：
- **软门**（诚实/反谄媚/弱点披露/责任/用户自主）：只 `flagged=not ok` + 投影 `VerifierChallengeRaised`·**绝不阻断 orchestrator 主流程**（不 raise·不改既有行为）。硬卡 agent=后续显式决策（本波非目标）。
- **§13 命门**（secret/OrderGuard/kill switch/no-silent-mock 被 waiver 绕过）= fail-closed 硬墙：`evaluate_trust` 内 `raise SafetyWaiverError`·本层**不吞**（吞=把硬墙降级成 advisory=削弱命门）·投一枚 `FailureDetected`（**只投不变量名·不投原始 target 文本**·免回显 user 自由文本/潜在 secret）后**原样 re-raise**。安全不变量不在 advisory 域。

**对抗 4 条 + MUT 三态**：谄媚/弱点隐藏产出被标记 / 诚实产出不误伤 / advisory 不阻断 agent 主流程 / waiver 不绕 safety 命门（命门 re-raise 不吞）。MUT 削弱核心 §13 advisory 门→RED→手工复原→GREEN（绝不 git checkout）。
**测试**：opus scoped+定向回归 `157 passed`（含 4 对抗）；**中心全量批次 2692 passed / 13 skipped / 0 failed / 118s**（基线 2675 + 17·collect 2705·flake 未触发）+ validate PASS。
**数学↔实现**：无新公式→未造 MathematicalArtifact。复用 trust.evaluate_trust 零重写·未碰 GovernedToolDispatcher（工具派发治理与 §13 无关）。

**红线合规**：advisory 软门只标记不阻断（不预先削弱·不破基线）·命门 fail-closed re-raise 不降级·复用 trust 判定零重写·扩展不替换·未碰 main.py/trust 内部/release_gate/governance 内部。诚实（no 假绿灯·命门投影不回显 secret）。

**诚实残余 / follow-on（→ 中心/下游）**：
- **free-text→TrustContext 映射**：本层吃调用方显式构造的结构化 TrustContext，**不**从 role agent 自由文本产出自动抽 §13 姿态（避免脆弱启发式 + 越权重判风险）。free-text→TrustContext 的上游映射=另卡/中心。
- **接 main.py**：advise_trust 接进真 agent 运行端点 = 中心后续。
- **§8 governance spine_invariants 接 orchestrator** = 平行另卡（本卡只 §13 trust）。
