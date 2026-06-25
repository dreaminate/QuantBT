---
uuid: b762da53ba5b4a1f85626ae9a154a358
title: ic_decay 诚实 status 精修——ρ̂≈0 弱负判 no_persistence 而非过claim reversal
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: factor-lifecycle
source: review-finding
source_ref: 分支评审（done 卡 3d4a872e）low 残余：ic_decay ρ̂≈0 白噪误标 reversal
depends_on: []
---

# ic_decay 诚实 status 精修（no_persistence）

## Scope [必填]
分支 land-readiness 评审挖出的 low 残余：`ic_decay_half_life` 把 ρ̂≤0 一律判 `reversal`，但 ρ̂≈0（白噪 IC、
无自相关）是**无持久性**、非「反转」（reversal=anti-persistent 须 ρ 显著<0 方可下）。本卡按**显著性**诚实分。

## 数学先行（finding「衰减边界」节）
−1<ρ≤0：仅当 ρ̂ **显著<0**（95% CI 上界 ci_hi<0）→ `reversal`（实质反持久结论）；ρ̂≤0 但 **CI 含 0**（ρ̂ 与 0
不可辨）→ `no_persistence`（IC 无显著自相关=无持久性，**非反转非持久**），半衰期不适用。ρ̂>0 弱（CI 跨 0）仍
归既有 unstable（warning 已 hedged「CI 跨 0」、非硬过claim，本切片不动避 ripple）。

## 治理（命门·不假绿灯/诚实 status）[必填]
- **不 over-claim**：reversal 是实质结论、须显著负；噪声级弱负 ρ̂ → no_persistence（如实「无持久性」）。
- **advisory 传播不变**：decay_diagnostic 对 no_persistence 落 status!=ok 分支（不作硬退役依据），行为一致。
- **低 ripple**：显著负（ρ=-0.6 n=2000）仍 reversal；random walk（ρ≈1）不碰本分支；near-constant 仍 insufficient。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/factor_factory/lifecycle_metrics.py | DecayEstimate.status Literal +no_persistence；ρ≤0 分支按 ci_hi 分 | additive 枚举 + 分支细化 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 弱负不显著（ρ=-0.2 n=45·CI 含 0）→ no_persistence、半衰期 NaN；显著负（ρ=-0.6 n=2000）→ reversal；白噪→no_persistence/unstable（绝不 reversal/ok）。
2. **MUT「还原 ρ≤0 全 reversal 过claim」→ 弱负判 reversal → 测试红**（验证 no_persistence 有牙）。

## 验收一句话 [必填]
ic_decay ρ̂≈0 弱负按显著性诚实判 no_persistence（非过claim reversal·MUT 还原过claim 验证有牙），低 ripple；
全量后端 1605 passed/0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-DECAY-NOPERSIST）
- **诚实 status 精修**：ρ̂≤0 按 95% CI 上界分——含 0→no_persistence（无持久性、非反转）、显著负→reversal。绝不把白噪弱负 ρ̂ over-claim 成「反转」（评审 low 纠偏，对齐不假绿灯/honest-status 纪律）。
- **MUT 验证有牙**：还原「ρ≤0 全 reversal」→ 弱负测试红。低 ripple（显著负仍 reversal、random walk 不碰、near-constant insufficient）。
- **验证**：`test_factor_lifecycle_metrics` 31 + `test_lifecycle_decay_advisory` 全 passed；**全量后端 1605 passed / 13 skipped / 0 failed / 124s**（基线 1604，净 +1）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户·分支续 land-ready）。
