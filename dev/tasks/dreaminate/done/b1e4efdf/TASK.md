---
uuid: b1e4efdf30ee441c959346ba4168bd9b
title: 冷启动 MinTRL 接进 run /overfit 投影（价值闭环·呈现层不动治理）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: eval-methodology
source: goal-gap
source_ref: P2 卡 31289338 的后端部分；CEO 透镜反复「数学对、未接到用户」→ 首个价值闭环合拢
depends_on: [6acbb499f5b94fe3b77c4de79bb43982]
---

# 冷启动 MinTRL 接进 run /overfit 投影

## Scope [必填]
把已建的 R27 冷启动 MinTRL（`eval/dsr.py`）**接进 run /overfit 投影**——首个**价值闭环合拢**切片（数学→裁决输出）。
`project_overfit` additive 加 `cold_start` 证据充分性字段（短业绩期诚实"证据不足/需 N 期" + DSR 适用性），
**R27 明言冷启动是呈现层、不动治理闸门 / 三态裁决**。

## 治理（命门·不假绿灯/措辞守门/两管线分离）[必填]
- **additive·不动治理**：只加 cold_start 字段，gate.color/is_promotion_candidate/三态裁决全不变。
- **不假绿灯**：短业绩期 n<⌈MinTRL⌉ → sufficient=False；N<3/σ≈0 → DSR 不适用（R27 N=1 范畴误用）；SR≤基准 → never_significant。
- **措辞守门（R7）**：note 走 `_BANNED_VERDICT_WORDS` **runtime 防御**（红线全集：可信/安全/保证/可复现/组织独立/排除过拟合 + 通过）——红线词出现即退安全兜底，**生产期绝不输出禁词**（不只靠测试）。
- **两管线分离**：`axis="track_record_length"` 标识，与过拟合门样本充分性轴区分（防两「证据不足」混读）。JSON-safe（inf/nan→null）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/run_verdict.py | +_cold_start_evidence + _BANNED_VERDICT_WORDS；project_overfit 加 cold_start 字段 | additive 不动 gate/三态 |
| app/eval/dsr.py | 复用 minimum_track_record_length / probabilistic_sharpe_ratio | 不改 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 短 ok+n<⌈MinTRL⌉ → sufficient=False（绝不渲染达标）；N=1 → insufficient + DSR 不适用；负 edge → never_significant。
2. **措辞守门**：note 全 4 状态分支显式覆盖（含 ok_sufficient 高危分支）+ 禁词集 ⊇ R7 红线全集 + 测试集==生产集（不漂）+ sentinel。
3. /overfit additive 含 cold_start 且不动 gate_label/is_promotion_candidate。JSON-safe。

## 验收一句话 [必填]
MinTRL 接进 /overfit 冷启动证据字段（短样本诚实证据不足 + DSR 适用性 + axis 区分）、措辞守门生产 runtime 防御 + 红线全集、不动治理闸门；全量后端绿、基线不破。

## 完成记录（2026-06-25 · autonomous-loop / D-COLDSTART-WIRE）
- **价值闭环**：CEO 透镜反复指「数学对、未接到用户」→ 转向闭环。评估后选最低风险（R27 呈现层、不动 governance gate）：MinTRL 接 /overfit。
- **实现（additive）**：`run_verdict._cold_start_evidence`（MinTRL 判证据充分性，4 状态）；`project_overfit` 加 cold_start。
- **两轮独立复核全闭环**：① **用户种 banned-words mutation**（sufficient 分支 note 塞「可信/已排除过拟合」）测措辞守门——已撤回；强化测试**显式覆盖全 4 状态分支 + sentinel**（你那 mutation 落 ok_sufficient 分支、必被抓）。② **多透镜评审 confirmed**：**我的禁词集是 R7 红线不完整子集**（漏 保证/可复现/组织独立、cold_start note 绕 _verdict_note 单一源→唯一守门、子集=纸糊门）+ dsr_applicable 口径/σ≈0 措辞 → 补全红线全集 + **加生产 runtime 防御守门**（不只测试）+ 单一源对齐测试 + insufficient 分 n<3/σ≈0 + axis 轴区分。
- **验证**：`test_run_verdict_cold_start.py` 9 + run_verdict_card 14 回归 passed；**全量后端 1555 passed / 13 skipped / 0 failed**，基线 1547 未破。
- **land main 待用户授权**（本轮 loop「commit 不擅自 push」→ 仅本地 commit，未 push）。
