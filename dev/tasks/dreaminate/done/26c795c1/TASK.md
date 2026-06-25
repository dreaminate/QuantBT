---
uuid: 26c795c1544547dab3378ae45dd834fd
title: Governed Compiler——canonical command+IR→deterministic run→evidence verdict（A-COMPILER·§1 链 capstone）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: compiler
source: goal
source_ref: GOAL §1(链 行60-75:Canvas/Command→QRO→Research Graph→Governed Compiler→Deterministic Run→Evidence Verdict→Promotion)·§7(行1315 role agent 受 deterministic DAG/governed compiler 管理)·§8 治理脊柱
depends_on: [8abde88e406544e990d7cdf352740f23, 76a611d3d26c42f495a7d7a29d5e5319]
branch: wave5/a-compiler
---

# Governed Compiler（A-COMPILER·LINE-A capstone·完成 QRO→Graph→Command→Compiler→Run→Verdict 整脊柱）

## Scope [已落]
建 **Governed Compiler**——GOAL §1 链「→ Governed Compiler → Deterministic Run → Evidence Verdict →
Promotion/Approval」那一段。四段编译管线，每段**收编只读**一个既有件（不重造·扩展不替换）：
① 消费 **canonical command（A-CMD）+ Research Graph IR（A-GRAPH-1）**；② → **deterministic run**
（收编 `dag/kernel.py` `DurableExecutor` 确定性内核·run 携确定性内核身份）；③ → **evidence verdict**
（收编 `verification/verifier.py` `Verifier` + `eval/overfit_gate.py` `run_overfit_gate` 三角脊柱门）；
④ governs **promotion**（收编 `approval/gate.py` `ApprovalGateService`·approver≠creator）。

## 领地（greenfield·只动·零碰他处）
- 新建 `app/backend/app/compiler/governed_compiler.py`（核心·~700 行）+ `app/backend/app/compiler/__init__.py`。
- 新建测试 `app/backend/tests/test_governed_compiler.py`（28 对抗/MUT/正路径测）。
- **git status 实测仅两项 `??` 新增**：`app/backend/app/compiler/` + `test_governed_compiler.py`。
  **零修改** main.py / 被收编模块内部 / 其他在飞线 / state·log·board·DEVMAP·GOAL·pool·其他卡。

## 实装结构（governed_compiler.py）
- `GovernedCompiler`（构造期注入收编四件：`DurableExecutor` / `Verifier` / `ApprovalGateService` /
  懒调 `run_overfit_gate`）。三段公共写口 `compile()` / `attest()` / `promote()` + `govern()` 一把过整脊柱。
- 产物 frozen 内容寻址（复用单一身份源 `lineage.ids.content_hash`·前缀 `crun_`/`att_`/`promo_`/`krn_`·
  绝不另造哈希族）：`CompiledRun`（含 `kernel_run_id` 确定性内核身份指纹 + `node_id_by_task`）/
  `AttestedRun`（含验证官 `VerdictRecord` + 三角门 `GateVerdict`）/ `PromotedRun`（含审批门裁定）。
- `CompileLedger` 三段同进一本 append-only 治理账（单一通道）；`VerdictBook` 接审批门 `verdict_lookup`
  （破构造环·共享只读裁决源）。`build_default_compiler()` 工厂一次接好四件 + 账 + 簿。
- 五命门探针：`assert_run_compiled` / `assert_kernel_identity`（+ 自洽核）/ `assert_verdict_attested` /
  `assert_promotion_governed`，是「绕 compiler 直造 / 伪造内核身份 / 伪造 verdict / 绕审批门」的可证伪抓手。

## 可证伪验收（种坏门必抓 · §1/§7/§8 · 28 测全绿）
1. **命令未经 compiler 落 run → 拒**：命令未经 canonical command 通道落图（不在 `command_log`）→
   `UncommandedRunError`；绕 `compile()` 直造 run（不在编译账）→ `RunNotCompiledError`。
   ★ MUT：关 `assert_run_compiled` → 绕过 run 滑过 attest（证门 load-bearing）。
2. **run 无 deterministic 内核身份 → 拒**：假执行器返伪 `node_id`（≠ `compute_node_id` 独立重算·单一源）/
   非 `KernelRunResult` / 空身份 / `kernel_run_id` 被篡改 → `KernelIdentityViolation`。
   ★ MUT：关 `assert_kernel_identity` → 假执行器伪身份滑过 compile。含多 task DAG（上游内容寻址）逐一吻合真内核。
3. **verdict 绕过 verifier/三角门 → 拒**：手刻 `verdict_id`（≠ `compute_verdict_id` 单一源重算·伪造裁决）/
   verdict.target_ref 未绑本 run（张冠李戴）→ `VerdictBypassViolation`。
   ★ MUT：关 `assert_verdict_attested` → 伪造 verdict 滑进 promote 被晋级。
4. **promotion 未经 approval 门（approver≠creator）→ 拒**：approver==creator → 收编审批门抛
   `ApproverEqualsCreator`；绕审批门直造 PromotedRun / approved 却 approver==creator →
   `PromotionGovernanceViolation`。★ MUT：审批门掉包成「自动批不查 approver≠creator」→ 自批滑过（证门 load-bearing）。
5. **正路径不误伤**：合法 command+IR → deterministic run（确定性内核身份）→ verifier consistent + 三角 green
   → approval（approver≠creator）→ governance=approved·三段全落账。`govern()` 一把过等价·链可回溯。
   外加：异模型不一致(concern/blocked) / 三角非 green → **诚实拒晋级**（`EvidenceVerdictUnfavorable`·证据不足·非误伤）。

## 红线合规 [逐条]
- **单一身份源 ids.py 不另造**：所有 id 走 `content_hash`；内核身份走 `compute_node_id`（=内核那一个·
  测 `test_collected_modules_unmodified_smoke` 断言 `is` 同一函数）；verdict 走 `compute_verdict_id`。✓
- **扩展不替换·收编不改**：仅新增 compiler/ + 测试；被收编模块零修改（git status 实测）。✓
- **deterministic 内核身份不绕**：compile 恒经 `DurableExecutor.run` + `assert_kernel_identity` 独立 re-derive。✓
- **verdict 经 verifier**：attest 恒经 `Verifier.reconcile`；promote 恒经 `assert_verdict_attested`。✓
- **promotion 经 approval（approver≠creator）**：promote 恒路由 `ApprovalGateService.open_gate+approve`·
  绝无「不经审批直翻 governance=approved」旁路。✓
- **无新公式→不造 MathematicalArtifact**：编译管线是治理结构·非数学产物。✓
- **先读 GOAL §1/§7/§8 再动手**：动手前 grep+读 §1 链(行60-75)+§7(行1315)+§8 治理脊柱·按契约建。✓

## 测试汇总（scoped·不跑全量）
- `test_governed_compiler.py`：**28 passed in 1.00s**（5 命门 + 5 MUT + 正路径/govern/不利证据/结构不变量）。
- 收编模块基线不破：`test_research_graph.py`+`test_canonical_command.py` **117 passed**；
  kernel/dag/verifier/approval/overfit/n_eff 批 **172 passed**（1 例 `test_effect_ledger_concurrent_same_key`
  在叠跑下 SQLite 锁超时·**隔离重跑 1.12s 通过**·属环境 flaky 非回归·我未碰 effect_ledger）。
- collect 基线：main **2138** → 加本卡 **2165**（+28·纯增量·零破坏·collection 成功）。

## 拍板项命中（GOAL 没覆盖的岔路）
无需停报。两处**已知边界·诚实记录·非治理漏洞·非阻塞**（GOAL §1/§7/§8 契约内·未触未覆盖决策岔路）：
- 内核身份 re-derive 默认用内核默认 op 注册表 `dag.engine._OPS`（与 `DurableExecutor` 默认一致）。若注入
  的 executor 用**自定义** ops 表，须把同表传 `ops=`，否则 re-derive 误判（false reject）——治理路径默认共享
  `_OPS`·此为已知边界（模块 docstring 已钉）。
- 审批门 honest-N 依赖由调用方按 `ApprovalGateService` 契约注入（本模块不碰 honest-N·测试用最小账双·
  `n_trials_raw` 真实 ≥ 它·非「改小 N」）。

## 诚实残余
- 接 main.py / 建前端 / 各台 Canvas 投影编译触发 = 领地外接线卡（中心做）。本卡只 Compiler 段后端管线。
- `attest` 的 evidence（claims/recomputed/returns/n_eff）由调用方从 deterministic run 产物抽取后呈上——
  本模块**不**计算/伪造证据，只交收编的验证官 + 三角门裁、把 verdict 绑定到 run。run 产物→evidence 的抽取
  适配（按各资产类型）是下游卡。
- `assert_run_compiled` 等单一通道探针同 A-CMD/A-GRAPH 范式：Python 不能真隐藏内部账，绕过仍可能，但探针
  使「是否都走了前门」可证伪（非防恶意·是防自欺 + 落账可审）。

## 验收一句话
canonical command + Research Graph IR 经 Governed Compiler → 确定性内核 run（身份不绕）→ 验证官+三角门
evidence verdict（不伪造、绑本 run）→ 审批门晋级（approver≠creator）整脊柱贯通；四类逃逸种坏门必抓 + MUT
证门 load-bearing；收编不改、基线不破（2138→2165）。
