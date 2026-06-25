---
uuid: 1b886c2eea7a41a18a3677268e2b702a
title: risk_summary DSR 别名单一源——消除 flags⊥trust_level 自相矛盾（dsr_confidence 漂移）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: eval-methodology
source: audit-finding
source_ref: 第二轮 correctness 审计（workflow wnbmpeqiv）#8（DSR 别名集不一致·lev 5）
depends_on: []
---

# risk_summary DSR 别名单一源——消除 flags⊥trust_level 矛盾

## Scope [必填]
`risk_summary` 的 DSR 别名集**三处手抄不一致**：`_rule_dsr`（含 dsr_confidence）+ `rule_metric_aliases`（含）但
`has_dsr` 守门（**漏 dsr_confidence**）→ `{sharpe, dsr_confidence=0.1}`：`_rule_dsr` 触 `low_dsr_confidence` HIGH flag，
但 has_dsr=False → 早返 `insufficient_data`（携该 flag）→ **flags[high]⊥trust_level[insufficient] 自相矛盾**
（trust 说「缺 DSR 证据」、flags 说「DSR 太低高风险」=误导·不能信）。本卡提单一源常量根治。

## 数学/不变量先行 [必填]
- **内部一致性不变量**：同一 metric 的「是否在场（has_*）」「是否触发规则（_rule_*）」「是否计入 checked」**必须共用同一别名集**
  ——否则 has_*=False 早返 insufficient 与 _rule_* 已触发的 flag 自相矛盾。
- 单一源 `_DSR_ALIASES = (dsr, deflated_sharpe, deflated_sharpe_ratio, dsr_confidence)`，三处共用 → 漂移不可能。

## 治理（护栏·correctness）[必填]
- 纯 correctness（内部一致性·不能信修复），不动任何阈值/口径=不涉用户方法学。behavior 变化仅限 dsr_confidence 别名
  的 run（修前矛盾·修后一致），无测试依赖旧矛盾行为（1655 passed）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| eval/risk_summary.py | +module 级 `_DSR_ALIASES`；_rule_dsr / rule_metric_aliases / has_dsr 三处共用 | 单一源重构 |
| app/backend/tests/test_risk_summary.py | +2 测试 | additive |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **矛盾门**：{sharpe, dsr_confidence=0.1} → 触 low_dsr_confidence flag 且 trust_level=high_risk（非 insufficient·与 flag 一致）→ MUT（has_dsr 别名去掉 dsr_confidence）→ 红 ✓
2. **健康路径**：{sharpe, dsr_confidence=0.8} → has_dsr 识得 → 可达 ok（不误判 insufficient）。

## 验收一句话 [必填]
DSR 别名提单一源 `_DSR_ALIASES` 三处共用，消除 dsr_confidence 触 flag 却判 insufficient 的 flags⊥trust_level 矛盾；
MUT 抓；全量后端 1655 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-DSR-ALIAS）
- **审计驱动（第二轮 #8·lev 5）**：DSR 别名三处不一致（_rule_dsr/checked 含 dsr_confidence、has_dsr 守门漏）→ flags⊥trust_level 矛盾。读 risk_summary.py:104/237/248 原文复核坐实。
- **实现（单一源重构）**：提 module 级 `_DSR_ALIASES`，_rule_dsr/rule_metric_aliases/has_dsr 三处共用。
- **对抗 + 变异**：+2 测试（矛盾门 + 健康路径）。MUT（has_dsr 去 dsr_confidence）→ 矛盾复现 + 健康误判 insufficient 2 测红；定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：risk_summary 28 passed（+2）；**全量后端 1655 passed / 13 skipped / 0 failed / 178s**（基线 1653，净 +2）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
