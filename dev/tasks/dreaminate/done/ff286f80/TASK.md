---
uuid: ff286f80af1546bfaaea9ce0a6feb9b2
title: 因子收益归因（returns-based attribution）—— 北极星「归因」阶段建库
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: eval-methodology
source: goal-gap
source_ref: 北极星 pipeline「数据→…→归因→监控」的「归因」阶段此前无独立模块（CEO 数学贯穿全流程）
depends_on: []
---

# 因子收益归因（returns-based factor attribution）

## Scope [必填]
北极星 pipeline 的**「归因」阶段无独立模块**（grep 实证：无 attribution 模块）。本卡建机构级因子收益归因
math 件：组合实现收益时序回归到因子收益，分解为「各因子贡献 + 特异收益」，满足**加总恒等式（命门）**。

## 数学先行（finding「因子收益归因」）
r_t = α + Σ_k β_k F_{k,t} + ε_t（OLS 含截距）；contrib_k = β̂_k·Σ_t F_{k,t}；specific = T·α̂ + Σ_t ε̂_t。
**加总恒等式**：Σ_k contrib_k + specific ≡ Σ_t r_t（逐期求和纯代数；contrib 与 specific 独立公式 → 恒等式有真牙非 tautology）。

## 治理（命门·不假绿灯）[必填]
- **加总恒等式命门**：分解逐位闭合、无未解释残漏被悄悄丢（MUT-attr「mean 代 sum」验证有牙）。
- **不假绿灯**：样本不足 T<K+2 → insufficient 不出 β；共线 rank<K+1 → collinear 不报不可识别 β；近共线 cond 高 → ok+warning（β 不稳）；非有限行剔除并披露；低 R² 如实报（收益多由特异驱动≠「已归因」）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/eval/attribution.py | 新建 `factor_return_attribution` + `AttributionResult` | 新增 math 件 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. **命门加总恒等式**：Σ contrib + specific == total 逐位（test_attribution 40 seed + methodology 60 seed·MUT-attr 验证有牙）。
2. **已知 β 恢复**：r=2F1+3F2+小噪 → β̂≈[2,3]、contrib==β̂·ΣF 精确、R²≈1。
3. insufficient/collinear/非有限剔除/等长 raise/K=0 全特异/JSON-safe。

## 验收一句话 [必填]
因子收益归因 math 件建成（OLS 分解·加总恒等式命门·已知 β 恢复·insufficient/collinear 诚实 abstain），
MUT-attr 验证恒等式非 tautology 有牙；test_attribution 8 + methodology 1 + 全量后端 1594 passed/0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-ATTRIBUTION）
- **填 pipeline 缺口**：北极星「归因」阶段建 `eval/attribution.py`（grep 实证此前无 attribution 模块）。OLS 时序回归分解组合收益→因子贡献+特异；加总恒等式逐位闭合。
- **命门有真牙**：contrib（β̂·ΣF）与 specific（Tα̂+Σε̂）独立公式 → 恒等式非构造性；MUT-attr（contrib 用 mean 代 sum）→ 两恒等式 + 已知 β 三测全红。
- **验证**：`test_attribution.py` 8 + `test_methodology_invariants::test_attribution_sum_identity_invariant` 1 passed；**全量后端 1594 passed / 13 skipped / 0 failed / 151s**（基线 1585，净 +9）。
- **消费侧 follow-on**：组合台/归因报告接真组合权重+因子收益 → 已 mint 卡 e4496023（标用户方法学决策：因子集/excess 口径）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
