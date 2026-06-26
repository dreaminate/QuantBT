---
uuid: 785c79c6d2e84e84bd82f70e504c5b23
title: 发版门禁套件——工程标准 release gate（no silent mock/no template false success/required bindings→拒）（LINE-E·D-RELEASE-GATE）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: release-gate
source: goal
source_ref: GOAL §16 工程标准(行 1969-2032·no silent mock fallback/no template false success/dataset_version+checksum/TheoryImplementationBinding required/ConsistencyCheck required before promotion/MethodologyChoiceRecord required/LLM Gateway enforced/Mock 诚实)+§0 可上线七条；施工图 LINE-E 发版门禁
depends_on: []
---

# 发版门禁套件（LINE-E·D-RELEASE-GATE·§16 工程标准 release gate）

## Scope [必填·先读 GOAL §16+§0]
建 **发版门禁套件**——§16 工程标准作不可绕的 **release gate**：晋级/发版前强制核查 ① no silent mock fallback（mock block 必挂标识·fallback 显原因·template response 不生成 production success）② no template false success ③ dataset_version+checksum 在场 ④ TheoryImplementationBinding required for proof-backed ⑤ ConsistencyCheck required before theory-backed promotion ⑥ MethodologyChoiceRecord required for user-waived ⑦ LLM Gateway enforced + provider/model/auth_ref/cost/replay logged。任一缺→拒发版。**收编只读**已建门（spine_gate/verifier/approval/llm call_record/data_quality）·不重造·聚合成单一 release gate。

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/release_gate/`（release_gate.py：工程标准核查清单 + 拒绝门 + 聚合已建证据）。**收编只读**：lineage/spine、verification/verifier、approval/gate、llm/call_record、data_quality、delivery/rdp_gate。**绝不碰** main.py、被收编模块内部、其他在飞线。

## 可证伪验收（种坏门必抓·§16）
1. silent mock fallback（mock 未挂标识 / fallback 无原因 / template 标 production success）→ 拒（MUT 放过→红）。
2. proof-backed 实现缺 TheoryImplementationBinding → 拒；theory-backed promotion 缺 ConsistencyCheck → 拒。
3. user-waived 路径缺 MethodologyChoiceRecord → 拒。
4. LLM 用了但未经 Gateway / LLMCallRecord 缺字段 → 拒。
5. 全标准齐 → 放行（正路径不误伤）。

## 红线 [按需]
no silent mock fallback·no template false success·复用已建门不另造·扩展不替换·先读 GOAL §16 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不重造 spine_gate/verifier/approval（收编只读聚合）；不接 main.py（发版编排接线另卡/中心）。本卡只工程标准 release gate 核查门。

## 完成纪要（done · 隔离 worktree·中心整合+跑全量+land）

**分支**：`wave7/release-gate`（基于 origin/main·前六波已 land）。

**新建文件（greenfield·只动 release_gate/ + 新测试·零碰被收编模块/main.py）**：
- `app/backend/app/release_gate/__init__.py` — 包出口。
- `app/backend/app/release_gate/mock_honesty.py` — **新建原语**：§16 Mock 诚实（全仓原无可核查门）。`ExecutionBlock`（mode∈{live,mock,fallback,template}·result_grade·诚实标识三件套）+ 5 条规则 R1-R5：mock 必挂标识 / fallback 必显原因 / live 必用 source / template 不冒充生产成功 / 生产结果不走非 live（致命）。mode·grade 构造期校验非法即 raise（fail-closed·防 typo 绕过）。
- `app/backend/app/release_gate/release_gate.py` — **聚合门**：`ReleaseCandidate` + `evaluate_release` / `require_releasable`，8 门聚合。§16 ④⑤【委派】`spine_gate.evaluate_promotion`（不另写一致性判定·单一源）；§16 ⑦ 复用 `call_record.assert_record_admissible`（必填四要素单一源）+ `verify_record_seal`（Gateway 来路）；§16 ③ duck-type 收编 `DatasetVersion`/`DatasetVersionRef`（免拉 polars）；§16 ⑥ 新建 MCR presence 门（evaluate_promotion 只在 waiver 在场时用它·不强制其存在 → 真缺口）；附收编 Verifier/Approval/RDP（给则核·缺则软披露）。
- `app/backend/tests/test_release_gate.py` — 28 对抗测试。

**真测试汇总行**：`28 passed in 0.16s`（`pytest tests/test_release_gate.py`）。collect-only：`2313 tests collected`（= main 基线 2285 + 本卡 28·未破基线）。

**对抗测试（种坏门必抓·逐 §16 标准）**：
- ① Mock 诚实 5 例（R1 silent mock / R2 silent fallback / R3 live 无 source / R4 template 标生产成功 / R5 生产走 fallback 致命）各种坏→必拒；补回标识/原因/降级→必绿；非法 mode/grade 构造即 raise。
- ② proof-backed 缺 TIB→拒（binding-exists）；theory 晋级缺 ConsistencyCheck→拒（consistency-present）；弱标签不误伤。
- ③ user-waived 缺 MCR→拒；MCR 张冠李戴/缺责任边界→拒；有效 MCR→过。
- ④ 声明用 LLM 无 record→拒；record 缺 auth_ref→拒（复用单一源）；伪造封印（给 gateway_secret）→拒；未用 LLM 不误伤；cost 未记=软披露不硬拒。
- ⑤ 全标准齐 proof_backed 候选→放行（criterion ⑤ 不误伤）。
- 附：Verifier blocked→拒、Approval 非 approved→拒、RDP 未过 §17→拒、明文 secret 进账→raise SecretLeakError（不回显 secret）、多标准同缺全 surface。
- **MUT（绝不 git checkout·手 Edit 复原）**：削弱 R1 / LLM 封印门 / dataset checksum 门 三处各跑对应测试→均转红（门非纸做的）→手工复原→全绿、无 MUT 残留。

**红线合规逐条**：
- no silent mock fallback ✓（R1/R2/R5 硬拒，MUT 证非纸门）。
- no template false success ✓（R4 硬拒）。
- 复用已建门不另造 ✓（§16 ④⑤ 委派 evaluate_promotion、⑦ 复用 assert_record_admissible/verify_record_seal、③ duck-type 收编、§17 委派 validate_rdp；零改被收编模块内部）。
- 扩展不替换 ✓（纯新增 greenfield 包 + 新测试文件；未改任何既有文件）。
- 先读 GOAL §16+§0 ✓。无新公式→未造 MathematicalArtifact ✓。
- 未碰 main.py / state / log / board / DEVMAP / GOAL / pool / 其他卡 / 被收编模块内部 ✓。

**拍板项命中**：本卡无硬待拍板岔路（scope 由卡写死）。一处可由中心/用户后续收紧的**设计选择**（非阻断·已按 correctness/安全默认strict 决定）：
- **R5 生产结果走非 live 一律拒**：按 §16 致命「生产结果走 mock fallback」字面取 strict（生产仅 live source 可喂）。§0 措辞带「silent」限定，理论上「显式 surface 的降级喂生产」可放宽——但那属安全不变量（致命错误清单），按 RULES §0/§5 不预先削弱；若需「surfaced production fallback」放行通道，应走显式 MCR-gated 决策（decisions/），本卡不预建。
- **cost 作软披露而非硬拒**：单一源准入门 `REQUIRED_FIELDS` 刻意不含 cost（provider 常不返 usage）；硬拒会造第二套必填定义与单一源冲突且误伤已封印真账，故按 RULES §1 单一源取软披露。

**诚实残余（→ 中心/下游·非本卡 scope）**：
- 接 `main.py` / 真实 promote-端点的发版编排（在「翻态/上线之前」调 `require_releasable`）= 中心/另卡（卡非目标明示）。本卡只交可调用的核查门，未接线产品路径。
- `graphify update` 未跑（graphify-out/ 不在本卡领地·中心整合时统一刷）。
- 全量套件未跑（按完成协议只跑 scoped；中心跑全量 + land 审）。review_status 留 0（权威 review = 中心 land 时）。
