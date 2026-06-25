---
uuid: 79673e0d24ac4c7cb93f509116d94223
title: Conformal 预测区间经脊柱绑定（覆盖定理 property）+ 接 model_eval band
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: math-spine
source: goal
source_ref: GOAL §4（R23 conformal）+ 决策 D-MATH-SPINE + finding spine-consistency-gate/04 + 依赖 c86be35e
depends_on: [c86be35ee275495298f8da08a43e01a8]
---

# Conformal 预测区间经脊柱绑定 + 接 model_eval band

## Scope [必填]
把 conformal 预测区间（`eval/conformal.py:split_conformal_interval`，R23）经脊柱绑定，接进生产消费点 `eval/model_eval.conformal_prediction_band`（产 conformal band 喂 UI + 信号层 abstain gate）。**做**：conformal artifact + 覆盖定理 property（C1 MC 留出覆盖≥1−α / C2 abstain 诚实 / C3 区间合法）+ pinned + tripwire + 接 band（漂移→abstained+note·呈现层 fail-soft）。**不做**：cqr/aci（后续）；不动覆盖计算逻辑。

## 上下文 / 动机 [按需]
脊柱已治理 overfit gate + run verdict cold_start 两个生产消费点；conformal band（model_eval）是第三个、建在 split_conformal_interval 上。覆盖定理 P(Y∈C)≥1−α 可机器证伪（MC 覆盖掉 1−α 下=漂移）→ 绑它 correctness-critical。理论先行 finding 04。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/eval/conformal.py` | `split_conformal_interval`/`SplitConformalCalibrator`/`_conformal_rank_quantile`/`_min_calib_for` | 被绑定实现（只 import）|
| `app/backend/app/eval/spine_bindings.py` | 扩展 | conformal artifact + 覆盖性质 + pinned `be82f9471f557ab8` + verify |
| `app/backend/app/eval/model_eval.py` | `_conformal_spine_status`(新) + `conformal_prediction_band` | 注入 spine_consistency + 漂移 fail-soft abstained |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. C1 覆盖定理：固定 seed N(0,1) 留出 MC 覆盖 ≥1−α（α=0.1→0.898 / 0.05→0.956）；种区间砍半漂移 → 覆盖掉 1−α 下 → property fail → 门拒。
2. C2 abstain：n<⌈1/α⌉−1 → abstained。
3. tripwire：pinned==源指纹。
4. staleness：pinned≠live→fresh 拒。
5. 生产 wire：band 含 spine_consistency；一致→band 不变；漂移→abstained=True+数学一致性失败 note（无 R7 禁词「可信」）。

## 复用 [按需]
`lineage/spine_binder.property_consistency_check` · `spine_gate.evaluate_promotion` · DSR/PBO/bootstrap/MinTRL 切片范式 · `ConformalInterval.covers`（覆盖判定单一源）。

## 红线 [按需]
- 诚实：property（MC 覆盖）necessary-not-sufficient，抓 gross 漂移、±1 秩校正大 n 细微差异抓不到（C2 小 n abstain 部分兜底）→ check_type=property。
- R7 禁词：band fail-soft note 避「可信」（codex P2 教训）。
- 不破基线：conformal 一致时 band 逐位不变。

## 非目标 [按需]
- 不绑 cqr/aci（后续）；不改覆盖计算。
- band fail-soft 呈现层（不动治理闸门）。

## 收尾结果（done）
- `eval/spine_bindings.py` +conformal proof_backed artifact + 覆盖性质（C1/C2/C3）+ pinned + verify；`model_eval.py` +`_conformal_spine_status` + band 注入 spine_consistency + fail-soft abstained；新增 `tests/test_spine_conformal_binding.py`。
- **codex 1×P2 处置（真问题，已修）**：C3 原只查 `lower` 有限，漂移成 `[finite, +inf]` 会让 C1 蒙混 100% 覆盖 + C2 通过 → 门给 proof_backed + band 吐 inf 半宽。修：C3 加 `math.isfinite(upper)`（split 本该 finite-or-abstain）+ 回归测试 `_inf_upper_conformal` 必抓。
- 验证：conformal 绑定 **10 passed**（含 P2 回归 1）；spine 组 **58 passed**、model_eval/conformal **62 passed**（未破基线）；全量后端套件后台验证（真汇总行见 log）。
- 推进 GOAL §4 + gap #3/#7：脊柱覆盖扩到验证纵深 conformal + **第三个生产消费点**（model_eval band）。接 cqr/aci/drift/attribution 为后续。
