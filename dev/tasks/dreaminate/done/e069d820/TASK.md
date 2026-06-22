---
uuid: e069d82083da4629a59c17cf889f56c1
title: 裁决卡后端接线 — verdict/overfit/cost-sensitivity/promote/热力 端点 + 措辞合规
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: backend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [d93dc5a0804b4b5e8776c943487d888e]
---

# 裁决卡后端接线 — verdict/overfit/cost-sensitivity/promote/热力 端点 + 措辞合规

## Scope [必填]
新增 5 个 run 级裁决端点（GET verdict / GET overfit / GET cost-sensitivity / POST promote / GET monthly-heatmap），把已存在的 verification/eval/promote 后端逻辑投影成 RunVerdictCard 数据契约，verdictNote 强制由后端 `verifier._verdict_note` + `DISCLOSURE` 供给；**不做** RunVerdictCard 前端 React 组件、不改冻结页 RunDetailPage、不新增成本回测引擎本身（cost-sensitivity 只在现有成本模型上做 3 预设扫描）。

## 上下文 / 动机 [按需]
设计稿 RunVerdictCard（`/tmp/qbt-runDetailDeck.md` §①B/③/⑤/⑦）是 GOAL §6 信任层全新组件，承载 L1–L4 渐进披露 + 弱点一等呈现（R25）。后端逻辑齐全但**无一个 run 级裁决端点**：现有 `api.ts` 仅 `/api/runs/{id}` `/series` `/logs` `/attribution` `/source` `/tables` `/export` `/artifacts`。本卡补端点；前端落地为 R1 依赖卡 d93dc5a0 之后的兄弟卡。

**两条管线必须分清（设计稿 §⑤ 已警示，落地最大陷阱）**：
- `eval/overfit_gate.py::GateVerdict.color` ∈ {green/yellow/red/insufficient_evidence}（PBO/DSR 过拟合门，「晋级候选」措辞来自此）。
- `verification/schema.py::Verdict` ∈ {consistent/concern/blocked}（验证官三态，verdictNote 来自此）。
UI 的 verdict pill 三态 = 验证官 verdict；KPI/PBO/DSR 健康度 = GateVerdict。两者**不可混用枚举**。

## 接线点（file:line，实现时复核）[必填]

| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/main.py` | 紧邻 L2202 `@app.get("/api/runs/{run_id}")` 之后、L2217 `/series` 之前新增路由块 | 新增 `GET /api/runs/{run_id}/verdict`：调 `VERDICT_STORE`（L142 已实例化）按 run 的 target_ref（config_hash/card ref）查 `VerdictRecord`，返回 `rec.to_review()`（schema.py L92，含 verdict 三态 + disclosure + notes）；无记录返回诚实空态而非伪绿 |
| `app/backend/app/main.py` | 同区块续接 | 新增 `GET /api/runs/{run_id}/overfit`：读 run.json `gate_verdict`（promote.py L42/L122 已落盘）或在缺失时调 `eval/overfit_gate.py::run_overfit_gate`(L130)，返回 `GateVerdict.to_dict()`（L66，含 pbo/dsr_optimistic/dsr_conservative/n_observed/n_eff/model_risk_disclosure），字段名 `color` 不得改写成 verifier verdict 三态 |
| `app/backend/app/main.py` | 同区块续接 | 新增 `GET /api/runs/{run_id}/cost-sensitivity`：复用 `execution/backtest_venue.py:193`(commission+slippage+stamp+transfer) 成本模型，对 optimistic/neutral/pessimistic 3 预设重算 Sharpe/年化超额；pessimistic 须为最保守，不染绿 |
| `app/backend/app/main.py` | 同区块续接 | 新增 `GET /api/runs/{run_id}/monthly-heatmap`：从 portfolio.csv 月度聚合超额收益（6×12），替代设计稿前端 seed 造数；MOCK/不足期诚实角标 |
| `app/backend/app/main.py` | 仿 L2520 `@app.post("/api/ide/runs/{run_id}/promote")` 模式新增 `POST /api/runs/{run_id}/promote` | promote 写动作必须经审批门：调 `approval/gate.py::ApprovalGateService.open_gate`(L135)+`.approve`(L165)，触发 `ApproverEqualsCreator`(L172/176 归一比较) 与 verifier verdict!=blocked 前置；**禁**直接翻 stage |
| `app/backend/app/verification/verifier.py` | `_verdict_note` L204 | 复用为 verdictNote 唯一来源（只读，不改逻辑）；返回「证据一致/存疑/不一致 + independence.note」，端点不得自造文案 |
| `app/backend/app/verification/schema.py` | `DISCLOSURE` L23 + banlist 注释 L5/L22 | verdict 端点必须原样透传 DISCLOSURE；新增端点输出经同一 banlist 校验（禁「可信/安全/保证/可复现/组织独立/排除过拟合」） |
| `app/frontend/src/api.ts` | 末尾扩展 | 加 5 个端点的 fetch 封装 + TS 类型（verdict 三态 ≠ GateVerdict color），供 d93dc5a0 前端卡消费 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种 verdict 端点把 verdictNote 写成「PBO 0.18/DSR 1.34，排除过拟合，结果可信」（照搬设计稿 §⑤ 越界原文）→ 门必抓：banlist 断言命中「可信/排除过拟合」即 fail（R7，复用 `test_verification_verdict.py::test_disclosure_wording_banlist` L87 同款断言）。变异要杀点：把 banlist 校验改成只查 disclosure 字段、漏查 notes/verdictNote 字段 → 必须仍被抓。
2. 种 overfit 端点把 `GateVerdict.color="green"` 直接当 verifier verdict 返回成 `"consistent"`（两管线混淆）→ 门必抓：verdict 端点的 `verdict` 字段只能取自 `VerdictRecord.verdict`（consistent/concern/blocked），断言 GateVerdict.color 的取值不出现在 verdict 字段、且 overfit 端点不返回 verifier 三态枚举。变异要杀点：把 overfit 响应键 `color` 重命名/映射成三态 → 必须被抓。
3. 种 `POST promote` 绕审批门直接落 stage（不调 open_gate/approve）→ 门必抓：approver==creator 时必返 422/`ApproverEqualsCreator`（gate.py L176），无 approve 时 stage 不变；blocked verdict 下 promote 必拒。变异要杀点：把 approver≠creator 比较去掉归一（casefold/strip）想用大小写绕过 → 必须仍被抓（复用 L172 归一口径）。
4. 种 cost-sensitivity 让 pessimistic 预设算出比 neutral 更优的 Sharpe（成本方向写反）→ 门必抓：断言 sharpe(pessimistic) ≤ sharpe(neutral) ≤ sharpe(optimistic) 单调，越界即 fail。
5. 种 monthly-heatmap 在样本不足/无 portfolio.csv 时静默返回 seed 假数据 → 门必抓：缺数据必返显式空态 + MOCK 角标，禁伪造（R25 弱点一等、诚实角标）。

## 复用 [按需]
- `VerdictStore`/`VerdictRecord.to_review()`（store.py L17、schema.py L92）、`DISCLOSURE`（schema.py L23）、`_verdict_note`（verifier.py L204）。
- `run_overfit_gate`/`GateVerdict.to_dict()`（overfit_gate.py L130/L66）、`cscv_pbo`（pbo.py L58）、`deflated_sharpe_ratio`（dsr.py L58）。
- 审批门 `ApprovalGateService.open_gate/approve`（gate.py L135/L165）、`promote_ide_run`（promote.py L53）作为 promote 写动作模板（含 ledger 记账）。
- 成本模型 `backtest_venue.py:193`。前端 fetch 模式仿 `app/frontend/src/api.ts` 现有端点。

## 红线 [按需]
- verdictNote 措辞禁「可信/安全/排除过拟合/保证/可复现」（R7），文案唯一来源 = 后端 `_verdict_note` + `DISCLOSURE`。
- 权限轴 ⟂ 治理轴：promote 写动作绝不绕 ApprovalGate（approver≠creator + 验证背书，INV-5）；blocked verdict 必拒晋级。
- 弱点一等呈现（R25）：PBO/DSR/red 不染绿、缺数据诚实空态 + MOCK 角标。
- 默认止于模拟盘：promote 仅入对比分析/纸面跟踪，不导向直接实盘。
- 不改冻结页 RunDetailPage、不深色化重构（本卡纯后端 + api.ts 扩展）。

## 非目标 [按需]
- RunVerdictCard React 组件 / modal / 可编辑成本 UI（= R1 依赖卡 d93dc5a0 前端实装）。
- App.tsx topbar/血缘入口（另卡）。
- 新成本回测引擎（cost-sensitivity 只在现有成本模型上扫 3 预设，不重做撮合）。

## Open Questions（已决 D/总）[按需]
- [已决] promote 写动作必须经 ApprovalGate（approver≠creator + 非 blocked），不得旁路 —— 依 INV-5 + RULES.project，照 promote.py/gate.py 现状。
- [已决] verdict pill 三态取自 verifier verdict，GateVerdict.color 仅供过拟合健康度，两枚举不混用 —— 依 deck §⑤ + schema 锁定。
- [已决] verdictNote 文案唯一来源 = 后端，前端不杜撰 —— R7。
- [已决] cost-sensitivity 3 预设 P0 先写死常量占位(带 MOCK 角标)，P1 改读 run 配置派生 commission/slippage/stamp；分期不阻塞 P0。— leader 2026-06-21

D/总：1/4（占位，主控 build_card_counters 重算）

## 验收一句话 [必填]
种「verdictNote 输出绝对化措辞 / GateVerdict 当 verifier 三态返回 / promote 绕审批门」三类坏 → banlist 门 + 双管线枚举门 + approver≠creator 审批门必抓，且不破 `test_verification_verdict.py`/`test_overfit_gate.py`/`test_approval_gates.py` 现有基线。

---

关键文件绝对路径：
- 路由落点：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/main.py`（L2202 后新增 run 级端点；L2520 promote 模式参照；L142 `VERDICT_STORE` 已实例化）
- 裁决/措辞源：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/verification/{schema.py(DISCLOSURE L23, to_review L92, Verdict 三态),verifier.py(_verdict_note L204),store.py(VerdictStore L17)}`
- 过拟合源：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/eval/{overfit_gate.py(run_overfit_gate L130, GateVerdict L51/to_dict L66),pbo.py(L58),dsr.py(L58)}`
- 审批门：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/approval/gate.py`（open_gate L135 / approve L165 / ApproverEqualsCreator L172-176）
- promote 模板：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/ide/promote.py`（L53）
- 成本模型：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/execution/backtest_venue.py:193`
- 前端 api：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/api.ts`
- 对抗基线复用：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/tests/{test_verification_verdict.py(test_disclosure_wording_banlist L87),test_overfit_gate.py,test_approval_gates.py}`
