---
uuid: b85e34cca681472b9d45cfc052653875
title: 信任层三角补齐——PBO + Bootstrap 经脊柱 property-based 绑定 + 接生产 gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: math-spine
source: goal
source_ref: GOAL §6/§9 + 决策 D-MATH-SPINE + finding spine-consistency-gate/02 + 依赖 4458ff54(DSR 接生产 gate)
depends_on: [4458ff54dabe40fe98b45e60491790bb]
---

# 信任层三角补齐——PBO + Bootstrap 经脊柱绑定

## Scope [必填]
把信任层多证据三角的另两支估计器（CSCV-PBO `eval/pbo.py` / Bootstrap CI `eval/bootstrap.py`）经脊柱绑定，把生产一致性核从 DSR 一支扩到**三支全覆盖**。PBO/bootstrap 难做闭式独立 oracle → 用 **property-based 一致性检查**（从数学定义推出的必要性质）。**做**：各支 MathematicalArtifact + 必要性质集 + pinned 指纹 + `verify_*_consistency` + 接进 `run_overfit_gate`（三支任一漂移/staleness/抛错 → fail-closed）。**不做**：conformal/attribution/MinTRL/drift（main 新增）等其余数学点（后续）。

## 上下文 / 动机 [按需]
DSR 已接生产 gate（4458ff54），但 gate 红绿建在 DSR/PBO/bootstrap **三支**上——只核一支不够，PBO/bootstrap 漂移同样让裁决不可信。本切片补齐三角。理论先行 finding `spine-consistency-gate/02`。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/lineage/spine_binder.py` | +`property_consistency_check` | 可复用 property-based 一致性（§6 check_type=property）|
| `app/backend/app/eval/spine_bindings.py` | 扩展 | PBO/bootstrap artifact + 性质集 + binding + verify + pinned 指纹 |
| `app/backend/app/eval/overfit_gate.py` | +`pbo_spine_decision`/`bootstrap_spine_decision` + spine 块泛化三支循环 | 任一不一致 fail-closed |
| `app/backend/app/lineage/__init__.py` | 导出 | +property_consistency_check |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. PBO 性质（范围/噪声≈0.5/符号一致/真信号低 pbo）对真实现全过；种 sign 反转漂移 → P4/P5 fail → 门拒。
2. bootstrap 性质（lower≤upper/estimate==sharpe/可复现/真信号 lower>0/噪声跨0）全过；种 lower/upper 交换 → B1 fail → 门拒。
3. tripwire：PBO/bootstrap pinned==源指纹（实现一改即硬失败逼重核）。
4. staleness：pinned≠live → fresh 子句拒（生产可达）。
5. 生产 gate：三支全一致→正常裁决不变（spine_consistency 含 dsr/pbo/bootstrap 三键、color 不变）；PBO/bootstrap 任一漂移→fail-closed insufficient_evidence、reason 点名哪支。

## 复用 [按需]
`lineage/spine_binder`（指纹 + numerical/property 一致性）· `spine_gate.evaluate_promotion` · DSR 切片范式（pinned + tripwire + fail-closed）· `eval/dsr.sharpe_ratio`（bootstrap B2 同源交叉校验）。

## 红线 [按需]
- 诚实：property 必要非充分，check_type=property 标明弱于 numerical；no silent。
- 不破基线：三支一致时 color/numbers 不变。
- 单一身份源：指纹只走 ids.content_hash。

## 非目标 [按需]
- 不绑 conformal/attribution/MinTRL/drift（后续）。
- 不改 pbo/bootstrap/gate 既有裁决逻辑。
- property 不替代数值精度验证。

## 收尾结果（done）
- `lineage/spine_binder.py` +`property_consistency_check`；`eval/spine_bindings.py` +PBO/bootstrap artifact+性质集+binding+verify+pinned（PBO `8a7179e0db1006b3`/bootstrap `fc9f5c540e5834b8`）；`overfit_gate.py` +2 decision 函数 + spine 块泛化三支；新增 `tests/test_spine_pbo_bootstrap_binding.py`。
- 验证：PBO/bootstrap 绑定 **17 passed**；spine+gate 组 **93 passed**（未破基线）；全量后端套件后台验证（真汇总行见 log）。
- 推进 GOAL §6/§9 + gap #3：信任层三角三支全上脊柱、生产 gate 三支任一漂移 fail-closed。接 conformal/attribution 等其余数学点为后续。
