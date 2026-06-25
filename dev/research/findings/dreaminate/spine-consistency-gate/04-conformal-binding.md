# FINDING · Conformal 预测区间经脊柱绑定（覆盖定理 property）+ 接 model_eval band

- **蒸馏自**:Vovk; Lei et al. 2018（split conformal） · 现有 `eval/conformal.py`（R23） · 消费点 `eval/model_eval.conformal_prediction_band` · finding `01/02/03` · 决策 D-MATH-SPINE / R23
- **证据强度**:中强——split conformal 有**可机器证伪的覆盖定理**：P(Y∈C)≥1−α（分布无关·有限样本·边际）。property = MC 留出覆盖率≈1−α；覆盖掉 1−α 下即实现跑偏（漂移 grossly 必抓，±1 秩校正在大 n 下细微差异 property 抓不到 → 诚实标弱于精确恒等式）。
- **适用域**:成立 = exchangeability（可交换）。**不成立边界**:时序非平稳/regime drift 违反可交换 → 实测偏离 1−α（用 ACI/abstain）；只保边际不保条件覆盖。

## 核心主张（可证伪）[必填]

```text
split conformal: q̂ = |残差| 的第 k=⌈(n+1)(1−α)⌉ 阶（含 +1 校正·防小 n 欠覆盖）；区间 [μ̂−q̂, μ̂+q̂]
覆盖定理: P(Y ∈ [μ̂−q̂, μ̂+q̂]) ≥ 1−α（可交换下·有限样本）

必要性质（命门）：
  C1 覆盖: 固定 seed 留出集 MC 经验覆盖 ≥ 1−α（多 α 验）  ← 覆盖定理
  C2 abstain 诚实: n_cal < ⌈1/α⌉−1 → abstained=True（NaN 边界·绝不假区间）
  C3 区间合法: 非 abstain → lower≤upper、边界非 NaN；abstain → 边界 NaN（矛盾态构造期拒）
```

**如果** `split_conformal_interval` 偏离定义（如丢 +1 秩校正 / 区间过窄 / 错分位），**则** C1 经验覆盖掉 1−α 下 → 脊柱 property 一致性 fail → `conformal_prediction_band` fail-soft 标 abstained + 数学一致性失败 note（呈现层不假绿灯：坏 conformal 无法认证覆盖→不给 band）。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/backend/app/eval/conformal.py` | `split_conformal_interval`/`SplitConformalCalibrator`/`_conformal_rank_quantile`/`_min_calib_for` | 被绑定实现；整链进指纹 |
| `app/backend/app/eval/spine_bindings.py` | 扩展 | conformal artifact + 覆盖性质 + pinned + verify_conformal_consistency |
| `app/backend/app/eval/model_eval.py` | `conformal_prediction_band` | 注入 spine_consistency；漂移→abstained+note（呈现层 fail-soft） |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. C1 覆盖：固定 seed N(0,1) 留出 MC 覆盖 ≥1−α（α=0.1→≈0.9 / 0.05→≈0.95）；种漂移（区间砍半/错分位）→ 覆盖掉 1−α 下 → property fail → 门拒。
2. C2 abstain：n<⌈1/α⌉−1 → abstained（漂移成给假区间 → 抓）。
3. tripwire：pinned==源指纹（改 conformal.py 链即硬失败）。
4. staleness：pinned≠live → fresh 拒。
5. 生产 wire：band 含 spine_consistency；一致→band 不变；漂移→abstained=True+数学一致性失败 note（守 R7 禁词）。

## 复用 [按需]
`lineage/spine_binder.property_consistency_check` · `spine_gate.evaluate_promotion` · DSR/PBO/bootstrap/MinTRL 切片范式（pinned+tripwire+fail-soft）· `ConformalInterval.covers`（覆盖判定单一源）。

## 未验证残余（诚实）[必填]
- property（MC 覆盖）necessary-not-sufficient：抓 gross 漂移（过窄/错分位），±1 秩校正大 n 细微差异抓不到（小 n abstain 边界 C2 兜底部分）→ check_type=property 标弱于 DSR/MinTRL 精确恒等。
- cqr/aci 本切片只绑 split（最常用·model_eval 消费的就是 split）；cqr/aci 后续。
- 覆盖保证依赖 exchangeability，时序非平稳偏离（实现正确但前提不满足）——不在 property 判定内（那是适用域披露）。

## → 拆成的任务（本切片实现，落 done）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | conformal 区间过窄/错分位→MC 覆盖掉 1−α 下→band fail-soft abstained；接 model_eval | P0 | c86be35e(MinTRL) |
