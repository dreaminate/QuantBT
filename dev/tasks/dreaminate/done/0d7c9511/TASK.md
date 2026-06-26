---
uuid: 0d7c951178574b31ae35146c7867df0f
title: 信任层硬约束门 + ResponsibilityDisclosureRecord——反谄媚/诚实硬约束/waiver 不绕 safety（§13）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: trust
source: goal
source_ref: GOAL §13 信任层(行 1816-1877·诚实硬约束:不伪造 proof-backed/evidence sufficient/production-ready·不隐藏 user waiver·waiver 不绕 secret/OrderGuard/kill switch/no-silent-mock·ResponsibilityDisclosureRecord·反谄媚·弱点一等呈现·可证伪:Agent 顺从 wishful thinking 输出强结论→拒·弱点默认隐藏→拒)
depends_on: []
---

# 信任层硬约束门 + ResponsibilityDisclosureRecord（§13·反谄媚+诚实硬约束）

## Scope [必填·先读 GOAL §13]
建 §13 **信任层硬约束门**：① **诚实硬约束**（不得伪造 proof-backed/evidence sufficient/production-ready·不得隐藏 user waiver·不得让理论↔实现不一致冒充一致·**不得让 secret/OrderGuard/kill switch/no-silent-mock 被 waiver 绕过**=命门）② **ResponsibilityDisclosureRecord**（responsibility boundary disclosure·user 承担风险写入）③ **反谄媚**（Agent 遇稳赢/越级实盘/忽略成本/忽略 N/忽略泄露给缺口+证据要求+下一步·不顺从 wishful thinking 输出强结论）④ 弱点一等呈现（风险/缺口/弱点默认可见不隐藏）。**收编只读**已建（methodology MethodologyChoiceRecord/release_gate mock honesty/verifier）·补 ResponsibilityDisclosureRecord + waiver-safety 边界 + 反谄媚门。

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/trust/`（trust_constraints.py 诚实硬约束门 + ResponsibilityDisclosureRecord + 反谄媚检查 + waiver-safety 边界门）。**复用** methodology/MethodologyChoiceRecord、lineage/spine、lineage/ids。**绝不碰** main.py、被收编模块内部、其他在飞线。

## 可证伪验收（种坏门必抓·§13）
1. **waiver 绕过 secret/OrderGuard/kill switch/no-silent-mock** → 拒（命门·MUT 放过→红·安全不变量不可 waiver）。
2. Agent 顺从 user wishful thinking 输出强结论(稳赢/忽略 N/忽略泄露)→ 拒（反谄媚）。
3. 弱点风险默认隐藏 / user waiver 被隐藏 → 拒（弱点一等呈现+不隐藏 waiver）。
4. user 承担风险但缺 ResponsibilityDisclosureRecord → 拒；伪造 proof-backed/evidence sufficient/production-ready → 拒。

## 红线 [按需]
**安全不变量(secret/OrderGuard/kill switch/no-silent-mock)绝不可被 waiver 绕过**(§13 命门)·不伪造强标签·反谄媚不顺从 wishful thinking·复用 MethodologyChoiceRecord 不另造·扩展不替换·先读 GOAL §13 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不重造 MethodologyChoiceRecord/mock honesty/verifier(收编只读)；不接 main.py；不建前端渐进披露 UI(后端门即可)。本卡只信任层硬约束门+ResponsibilityDisclosureRecord+反谄媚门。

## 完成记录（2026-06-26 · wave8/trust-constraints · greenfield）

### 建了什么（只动 greenfield `app/backend/app/trust/`，零改既有文件）
- `app/backend/app/trust/responsibility.py` —— `ResponsibilityDisclosureRecord`（frozen·`disclosure_id` 内容寻址 `rdr_`+`lineage.ids.content_hash`，复用单一身份源不另造哈希族）。补全 `delivery/rdp.py` 早已 string-ref（`responsibility_disclosure_refs`）但全仓尚无类的缺口。`is_complete`/`missing_fields` 给「责任披露齐不齐」诚实诊断。
- `app/backend/app/trust/trust_constraints.py` —— 四块硬约束门：
  - **② waiver-safety 边界门 = 命门**：`SAFETY_INVARIANTS`={secret/order_guard/kill_switch/no_silent_mock}，`map_target_to_safety_invariant` 中英别名 substring 匹配（fail-closed），`evaluate_waiver_safety`（结构化·列拒/可放宽）+ `assert_safety_invariants_intact`（撞即 `raise SafetyWaiverError`）。`collect_waived_targets` 把 `MethodologyChoiceRecord.skipped_steps` 一并纳入扫描，堵「借方法学放宽把安全不变量塞进 skipped_steps 偷渡」。
  - **③ 反谄媚门**：`check_anti_sycophancy(AgentConclusion)` —— 稳赢/越级实盘/忽略成本/忽略 N/忽略泄露/未控多重检验/冷启动 N≤1 → 不输出强结论，降级到诚实强度 + 给【缺口+证据要求+下一步验证动作】。对 `user_pressure` 对称不松口；越级实盘缺阶梯=执行侧硬拦（非软 override）。
  - **④ 弱点一等呈现门**：`check_weakness_disclosure(DisclosureManifest)` —— 已知弱点未展示/被标隐藏/user waiver 被隐藏 → 拒（R25 绝不淡化·无「证据强时做轻」路径）。
  - **① 诚实硬约束门**：`check_honesty_constraints(TrustClaim)` —— 声称强标签必须有【已建证据门】放行该确切标签背书（`spine_gate.SpineDecision` + `methodology.MethodologyDecision` 双背书；本层只核「声明↔裁定一致」、绝不另写一致性判定）；理论↔实现不一致冒充一致 → 拒；单人模式/无真实组织流程声明组织独立 → 拒。
  - 外加 `check_user_autonomy`（Agent 替 user 拍板方法学/风险 → 拒）、`check_responsibility`（承担风险缺/不全责任记录 → 拒，但齐了就不再加非红线阻断）、聚合 `evaluate_trust`/`require_trustworthy`（命门走硬 raise·其余结构化 `TrustValidation`）。
  - 裁决口径自检 `_assert_no_banned_positive`（同 spine_gate/policy 范式·假绿灯反噬自身）：本门所有 verdict_text 绝不出现越权正向断言。
- `app/backend/app/trust/__init__.py` —— 单一 `app.trust` 导出面。

### 真测试汇总行（scoped·非全量）
- `app/backend/tests/test_trust_constraints.py`：**63 passed in 0.04s**（含 12 条参数化命门别名 + 5 条 benign 不误伤）。
- reuse-adjacent 回归带：`test_methodology_control_plane` + `test_release_gate` + `test_mathematical_spine_consistency_gate` **124 passed**（零回归·只动 greenfield）。
- 全量 collect-only：**2523 collected / 0 error**（基线 2460 + 本卡 63·新包不破收集）。

### 对抗测试（种坏门必抓·MUT 放过即红）
- **命门①（waiver 绕 safety）**：`test_waiver_bypassing_safety_invariant_refused`（4 参数化:secret/OrderGuard/kill switch/no-silent-mock）结构化拒 + `assert_safety_invariants_intact` 硬 raise 双路径；`test_methodology_skipped_steps_smuggling_safety_refused`（偷渡必抓）；`test_evaluate_trust_raises_on_safety_waiver_hard_stop`（聚合入口撞即 raise）；`test_each_safety_invariant_has_a_catching_alias`（删别名表任一族→红）。正路径 `test_methodology_relaxation_not_safety_is_permitted`（纯方法学放宽不误伤）。
- **反谄媚②**：`test_sure_win_strong_conclusion_refused`（user 施压仍拒·降级·给缺口/证据/下一步）+ 忽略成本/泄露/N 未知/冷启动 N=1/未控多重检验/越级实盘各一坏门必拒；正路径 `test_honest_strong_conclusion_with_full_evidence_permitted`（证据齐的强结论不误伤）。
- **弱点隐藏③**：`test_hidden_weakness_refused` / `test_explicitly_hidden_item_refused` / `test_hidden_user_waiver_refused`；正路径 `test_all_weaknesses_and_waivers_shown_permitted`。
- **责任缺失+伪造强标签④**：`test_risk_assumed_missing_responsibility_refused` / `test_incomplete_responsibility_refused` / `test_fake_proof_backed_without_decision_refused` / `test_fake_strong_label_when_spine_not_promotable_refused` / `test_fake_evidence_sufficient_via_relaxed_tier_cap_refused`（放宽档 cap 仍声称强标签必抓）；正路径 `test_real_evidence_sufficient_double_backed_permitted`（真过 spine+methodology 双门放行·reuse 端到端）。
- 自检有效：`test_banned_positive_self_check_fires`（planted 越权词必触发）；`test_reuses_spine_methodology_choice_record_not_recreated`（`tc.MethodologyChoiceRecord is spine.MethodologyChoiceRecord`·证未另造）。

### 红线合规（逐条）
- **安全不变量绝不可被 waiver 绕过（§13 命门）**：✅ 别名表覆盖四类·fail-closed·`evaluate_trust` 撞即 `raise SafetyWaiverError`（对齐 §13「撞即停工报告」+ release_gate `SecretLeakError` 既有先例）；本门只裁「弃权能否绕安全不变量」、不替各安全门做运行时强制（真硬墙仍在 security.gate/keystore/trading.safety/release_gate）——诚实限界已写进 disclosure。
- **不伪造强标签**：✅ 强标签真假【委派】`spine_gate`+`methodology` 已建裁定，本层只核「声明↔裁定一致」，缺背书即判伪造。
- **反谄媚不顺从 wishful thinking**：✅ 对 `user_pressure` 对称不松口；可证伪经济错觉（稳赢）从不背书，但非安全事项保留 R26「硬透明+软决定」（降级输出强度·不硬拦 user 自负其责推进）。
- **复用 MethodologyChoiceRecord 不另造**：✅ import 自 `lineage.spine`，测试钉死同一类对象；ResponsibilityDisclosureRecord 是新增独立类、身份仍走 `lineage.ids`。
- **扩展不替换 / 不破基线**：✅ 仅新增 4 文件，零改既有；全量 collect 2523/0 error，reuse 带 124 passed。
- **无新公式→不强造 MathematicalArtifact**：✅ 信任层无新数学命题，未造 MathematicalArtifact（测试里构造一个仅为驱动被复用的 spine 门·属测试脚手架非门内强造）。

### 待拍板项命中
无 decisions-未覆盖岔路。一处设计选择已按既有契约自决、非未覆盖分叉、供中心知悉：聚合入口 `evaluate_trust` 对「waiver 触安全不变量」走**硬 raise** 而非软 `ok=False`——依据 §13 命门「撞即停工报告」语义 + `release_gate.evaluate_release` 对 secret 泄露同样在 evaluate 内 `raise SecretLeakError` 的既有先例（需纯结构化的调用方改用 `evaluate_waiver_safety`）。R24/R25/R26/R27 已读并落（恰当依赖/弱点一等呈现绝不淡化/专业知识优先可 override/冷启动 N=1 标先验断言）。

### 诚实残余（未做/边界·不假绿灯）
- **未接 main.py / 无端点 / 无前端**：后端门即止（卡非目标明列）；接线进交付编排是中心/下游另卡。
- **文本检测的固有限界**：waiver-safety 靠中英别名 substring（fail-closed），刻意不收裸 `key`（防误伤）；极端隐晦改写可能绕过文本层——故 disclosure 明示本门「不替各安全门做运行时强制」，真硬墙在各自模块；`mock_honesty` 同款限界（识不破谎报 mode 的执行块）继承。
- **反谄媚的 N 阈值不烤死**：只编码结构性诚实点（N 未追踪 / 冷启动 N≤1）→ 拒；N≥2 的「样本够不够」交下游 PBO/DSR + user 可配阈值，本门不替 user 定数值（守 user methodology autonomy）。
- **未跑全量后端套件**（卡令「只跑 scoped 不跑全量」）：全量绿由中心整合时统一验。
