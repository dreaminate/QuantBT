---
uuid: 87ad21fc7aef4c39b956199516ba8626
title: R18 stacking 控制项 N/A 标注 + 实现时 OOF 约束（T-033 核验 gap）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P3
area: signals
source: research
source_ref: 2026-06-20 T-033 核验（gap: stacking_oof）
depends_on: []
---

# R18 stacking 控制项 N/A 标注 + 实现时 OOF 约束

## Scope [必填]
诚实标注：代码无 stacking/集成 meta-model 对象，R18（stacking 泄露）控制项当前 **N/A（无被测主体）**；待实现 stacking 时，meta-learner 必须消费 purged OOF（OOF+purge+embargo）防泄露。本卡仅记 gap + 约束，不强行造 stacking。

## 上下文 / 动机 [按需]
T-033：grep StackingClassifier/meta_model/out_of_fold 全 0 命中；signals/core.py 单层变换、models/training.py:93 单选模型。purge/embargo 基建已在基模型层（purged_cv.py），但无第二层 meta 套 OOF。非「purge 没做」而是「无 stacking 对象」。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/signals/core.py | 36 fuse_signals | 若加集成层：消费多基模型 OOF 预测 |
| app/backend/app/models/training.py | 93 _make_model | 若加 Stacking 估计器 |
| app/backend/app/models/purged_cv.py | — | 复用 OOF+purge+embargo |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. （实现后）构造「meta 用 in-sample 基预测训练」泄露版 → R18 守卫令 meta OOF 指标 vs 实盘段落差被检出/拦截。
2. 当前：在 dev/issues 或本卡记 R18=N/A（无对象），防误标已验证。

## 验收一句话 [必填]
R18 控制项状态诚实（N/A until stacking；实现则强制 OOF 喂 meta）；不破基线。
