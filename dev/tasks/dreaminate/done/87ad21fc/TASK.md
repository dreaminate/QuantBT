---
uuid: 87ad21fc7aef4c39b956199516ba8626
title: R18 stacking 控制项 N/A 标注 + 实现时 OOF 约束（T-033 核验 gap）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
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

## 实现落账（done · 2026-06-22 · D-WAVE1A 首卡）
**评审修正**：原 Scope「R18 整体 N/A」不够诚实——`signal_contract.py:52 LeakageDeclaration` 是**已建已对抗测试的活声明门**（`register` line 207-210 强制 OOF+purge+embargo 自报齐全否则拒入库；`test_adv4_signal_contract_leakage_declaration_gate`/`_unit_gate` 五变体）。故切**两面**：
- **(a) 声明门 = ✅ 已建并验证**（拒未声明，非证明无泄露）。
- **(b) stacking meta-learner 实证 OOF 强制 = N/A until 实现**（确无 stacking/meta-model 对象，graphify+grep 0 命中）。

**落地**（纯 additive 守卫，不造 stacking、不动产品代码）：`app/backend/tests/test_r18_stacking_control.py` 3 测试钉死两面 + 单一 CV 源：
- `test_face_a_declaration_gate_is_live`：声明门拒缺项、准齐全。
- `test_face_b_no_stacking_meta_model_object_yet`：扫 app/ 无 stacking 对象 → N/A 诚实；**种 stacking 对象即红**，强制实现者补 R18 实证 OOF。
- `test_single_cv_source_is_purged_cv`：`def purged_kfold`/`def walk_forward` 仅在 `models/purged_cv.py`（§1 单一源）；**种第二个 CV 实现即红**（关 S↔C 软耦合：将来 stacking/组合都复用同一 CV 源）。

**证据**：3 passed（1.96s）；**变异验证**种 `class Stacking`+`meta_model`+第二个 `purged_kfold`/`walk_forward` → 两道扫描门精确变红、删探针回绿（门必抓非纸门，RULES §2）。不破基线（实跑确认见 log）。
