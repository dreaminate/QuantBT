---
uuid: 89e7be1e67e14fa4a8f6c4a859769115
title: CPCV 路径稳健性 q05 接进 overfit gate（report-only 默认 / cpcv_conservative opt-in·守不替方法学拍板）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: eval-methodology
source: pool-card
source_ref: 池卡 861182e6 ②「q05 接 promote/overfit gate（阈值/gate_policy=用户拍）」；done 卡 876a0c11（CPCV→UI 闭环·report-only）的 gate 侧续接
depends_on: [876a0c11671f4c539461340b738eb58b, 861182e6f90a4219bd6a94553514172e]
---

# CPCV 路径稳健性 q05 接进 overfit gate（report-only 默认 / cpcv_conservative opt-in）

## Scope [必填]
CPCV per-path OOS 指标分布（done 卡 2da39479/c43c6301·`cpcv_oos_metric_distribution`）此前只到 UI 呈现（done 876a0c11·report-only），
**未接 gate**。本卡接 gate 侧（池卡 861182e6 ②）：把路径分布的**保守分位 q05**（< 无技能基线 = 部分路径无优于随机 = 过拟合脆弱）
作为信号接进 `run_overfit_gate` + `gate_runner.evaluate_overfit_gate`（promote 生产路径），**默认 report-only 只附报告绝不改裁决**，
调用方显式选 `cpcv_conservative` 才允许脆弱分布把 **green 降级 yellow**（advisory）。

## 数学先行（q05 作脆弱度信号 / 为何只降不升不红）[必填]
- **q05 语义**：CPCV 产 φ=C(N-1,k-1) 条 OOS 路径，每路径一个指标（regression r2 / 二分类 roc_auc）。q05 = 路径分布 5% 分位
  = **保守端**（最差 5% 路径的表现）。**无技能基线** b：r2→0、roc_auc→0.5。
- **脆弱判定**：`fragile := isfinite(q05) ∧ isfinite(b) ∧ q05 < b`。含义：哪怕策略均值漂亮，若 5% 的 CPCV 路径 OOS 跌破无技能线
  → 路径稳健性差 = 对训练/验证切分敏感 = 过拟合脆弱信号。**取保守分位非均值**：守池卡测试 #2「均值好但 q05 崩仍暴露」，
  不被漂亮单点蒙混。
- **为何只 green→yellow、绝不硬 red、绝不升级**（守 R2 单支不承重·守不替方法学拍板）：
  gate 裁决靠 PBO/DSR_cons/Bootstrap-CI **多证据三角**，q05 是**第四类弱证据**（路径一致性 ≠ 跨策略过拟合 PBO，
  绝不能等价喂 cscv_pbo——池卡红线）。单支弱证据**不足以独立创造 red**（那是把 advisory 当硬闸），故最多 advisory 降一档；
  更**绝不升级**（CPCV 稳 ⇏ 策略真好，路径稳≠样本外赚——绝不拿 q05 把 yellow/red 洗成 green=假绿灯）。

## 治理（护栏·correctness）[必填]
- **方法学松紧=用户拍板**：默认 `report_only` 不改任何裁决（只附 `verdict.cpcv` 报告）——不替用户决定「要不要让 CPCV 把关」。
  `cpcv_conservative` 是**用户显式 opt-in**，自负其责（声明在 docstring）。
- **不假绿灯**：CPCV 缺 / `status≠ok`（insufficient/unsupported_task）→ `verdict.cpcv=None`，绝不编造分布、绝不降级（未算≠已算）。
- **不削弱既有闸门**：red 永远 red（CPCV 不创造、不洗白 red）；yellow（缺 PBO）不被 robust CPCV 升 green；
  默认 None → 行为与接线前**逐位一致**（additive 扩展不替换）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/eval/overfit_gate.py | GateVerdict +`cpcv` 字段；run_overfit_gate +`cpcv_distribution`/`cpcv_policy` 参数 + 降级逻辑 + verdict_phrasing/reason cpcv 注 | additive |
| app/backend/app/eval/gate_runner.py | evaluate_overfit_gate +`cpcv_distribution`/`cpcv_policy` 透传给 run_overfit_gate（promote 生产路径接通） | additive |
| app/backend/tests/test_overfit_gate_cpcv.py | 新建 6 测试（单元层 gate 逻辑） | 新增 |
| app/backend/tests/test_gate_wiring.py | +2 测试（gate_runner 透传牙） | additive |

## 对抗测试设计（种已知 bug，门必抓）+ 变异验证 [必填]
1. **report_only 默认绝不改裁决**：带 fragile CPCV 的 color 与不带逐位一致、只附报告 → MUT-A（丢 policy 守卫让 report_only 也降级）→ 测试红 ✓
2. **cpcv_conservative + 脆弱 → green→yellow**（advisory 标记 downgraded_green_to_yellow）→ MUT-B（降级成 "red" 而非 "yellow"）→ 测试红 ✓
3. **绝不硬 red、绝不升级**：red 带 fragile 仍 red；yellow（缺 PBO）带 robust 仍 yellow。
4. **缺/status≠ok → cpcv=None**（不编造）；JSON-safe。
5. **gate_runner 透传牙**（T-GW-6）：report_only fragile 经 gate_runner → 裁决不变 + cpcv 附；cpcv_conservative fragile → green 降 yellow、robust 保 green
   → MUT-C（gate_runner 丢转发行 `cpcv_distribution=…, cpcv_policy=…`）→ 两测试红（cpcv 恒 None / 降级不发生）✓

## 验收一句话 [必填]
CPCV q05 保守分位接进 overfit gate + gate_runner promote 路径（report-only 默认绝不改裁决·cpcv_conservative 仅 green→yellow advisory·
绝不硬 red/不升级/缺则 None），守不替方法学拍板；MUT-A/B/C 三变异全抓；全量后端 1619 passed / 13 skipped / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-CPCV-GATE）
- **数学先行**：q05<无技能基线(r2:0/auc:0.5)=部分路径无优于随机=过拟合脆弱信号；取保守分位非均值（守「均值掩盖差路径」）；
  q05 是多证据三角外的第四类**弱证据**→ 最多 advisory 降一档（守 R2 单支不承重），**绝不硬 red、绝不升级**（路径稳≠策略好·不洗假绿灯）。
- **实现（additive·两层）**：① `overfit_gate.py` GateVerdict +`cpcv` 字段、run_overfit_gate +`cpcv_distribution`/`cpcv_policy`（report_only 默认 / cpcv_conservative）+ 降级逻辑（仅 fragile∧green→yellow）+ verdict_phrasing/reason 三分支 cpcv 注；② `gate_runner.evaluate_overfit_gate` 透传两参数到 run_overfit_gate（**promote 生产路径接通**）。默认 None/report_only → 行为逐位不变。
- **对抗 + 变异（牙坐实）**：单元 6（test_overfit_gate_cpcv）+ gate_runner 透传 2（test_gate_wiring T-GW-6）。**MUT-A**（report_only 也降级）→ report_only-不变-测试红；**MUT-B**（降级成 red）→ 降级-测试红；**MUT-C**（gate_runner 丢转发）→ 透传两测试红（cpcv 恒 None / 不降级）。三变异均定点反向 edit 验证后还原（**绝不 git checkout 带未提交改动**）。
- **green 可达性**：gate_runner 全链产 green 走组合层 A2 `allow_pbo_absent_green=True`（单策略 theme matrix 列不足 cscv_pbo→PBO None；A2 路径下高 dsr_cons+CI>0→green），CPCV 降级测试据此构造。
- **验证**：`test_overfit_gate_cpcv` 6 + `test_gate_wiring` 8（+2 透传）passed；**全量后端 1619 passed / 13 skipped / 0 failed / 183s**（基线 1611，净 +8）。
- **861182e6 残**：② done（本卡）；**③剩**：cv_scheme UI 选项（cpcv/dual_cpcv_wf 用户选）+ 双轨 report（CPCV⟂WF 并陈不自动判赢）+ Sharpe/DSR 口径 prediction→收益转换（用户方法学）—— 池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户·分支续 land-ready）。
