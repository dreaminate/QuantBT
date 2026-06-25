# FINDING · PBO + Bootstrap CI 经脊柱绑定（property-based 一致性·三角补齐）

- **蒸馏自**:López de Prado 2014「CSCV→PBO」· bootstrap percentile CI（标准） · 现有 `eval/pbo.py`/`eval/bootstrap.py` · finding `01-dsr-theory-binding` · 决策 D-MATH-SPINE
- **证据强度**:中——PBO/bootstrap 难做独立闭式 oracle（CSCV 组合算法 / 随机重抽），改用**property-based 一致性检查**：断言实现满足从数学定义推出的**必要性质**；性质违反 → 实现偏离定义。性质是必要非充分，故诚实标 check_type="property"（弱于 DSR 的 numerical oracle 对账）。
- **适用域**:成立 = 性质集覆盖足够多失效模式（噪声校准 + 范围 + 符号 + 区间合法）。**不成立边界**:property 检查抓不到「所有性质都满足但仍偏离定义」的细微 bug（那靠更强 oracle / Verifier）；不替代数值精度验证。

## 核心主张（可证伪）[必填]

**PBO（CSCV）必要性质**（违一即实现偏离定义 → 门拒）：
```text
P1 范围:    纯噪声/任意有效输入 → pbo ∈ [0,1]
P2 噪声校准: 纯 i.i.d. 噪声矩阵(无真信号) → pbo ≈ 0.5（IS-best 在 OOS 纯随机 → ~50% 落 median 下）  ← 命门
P3 过拟合:  构造 IS-best 恒 OOS-worst → pbo 高(→1)
P4 真信号:  一列强 alpha + 噪声 → pbo 低(→0，强者 OOS 仍最优)
P5 符号一致: pbo = frac(lambda_logit<0) → pbo 高 ↔ lambda_logit_mean 负
```

**Bootstrap CI 必要性质**（seed 固定 → 确定可复现）：
```text
B1 区间合法: lower ≤ upper
B2 点估一致: estimate == sharpe_ratio(returns)（与 DSR 模块同源 sharpe，交叉校验）
B3 可复现:  同 seed 两次调用 → 逐位相同 CI
B4 真信号:  强正 Sharpe 序列 → lower > 0（技能可辨）
B5 噪声:    零均值噪声 → lower < 0 < upper（CI 跨零，不造假技能）
```

**如果** `cscv_pbo`/`bootstrap_sharpe_ci` 违反任一性质，**则** 脊柱 property 一致性检查判 fail、`run_overfit_gate` fail-closed 降级 insufficient_evidence（三角任一支估计器漂离定义即不可信）。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/backend/app/eval/pbo.py` | `cscv_pbo`+`_sharpe_per_period` | 被绑定实现；整链进指纹 |
| `app/backend/app/eval/bootstrap.py` | `bootstrap_sharpe_ci`+`_moving_block_sample`+`sharpe_ratio` | 被绑定实现；整链进指纹 |
| `app/backend/app/lineage/spine_binder.py` | 新增 `property_consistency_check` | 可复用 property-based 一致性 |
| `app/backend/app/eval/spine_bindings.py` | 扩展 | PBO/bootstrap artifact + 性质集 + verify_*_consistency + pinned |
| `app/backend/app/eval/overfit_gate.py` | spine 块 | +pbo_spine_decision/bootstrap_spine_decision，三支任一不一致 fail-closed |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. PBO 正确 → 性质全过、verify promotable；种漂移（rank 反转/范围越界）→ P2/P3 fail → 门拒。
2. bootstrap 正确 → 性质全过；种漂移（lower/upper 交换 / estimate 用 mean 代 sharpe）→ B1/B2 fail → 门拒。
3. 真源码指纹：pinned vs live，改 pbo.py/bootstrap.py 任一环 → 指纹变 → staleness 拒（tripwire）。
4. 生产 gate：三支全一致 → 正常裁决不变；任一支漂移/抛错 → fail-closed insufficient_evidence。
5. 整链入指纹（含 helper），防改 helper 绕过。

## 复用 [按需]
`lineage/spine_binder`（指纹 + numerical/property 一致性）· `spine_gate.evaluate_promotion` · DSR 切片范式（pinned + tripwire + fail-closed）· `eval/dsr.sharpe_ratio`（bootstrap B2 交叉校验同源）。

## 未验证残余（诚实）[必填]
- property 检查是**必要非充分**：抓噪声校准/范围/符号/区间合法类漂移，**抓不到**「所有性质满足但数值细微偏离」——那需更强 oracle/Verifier；故 check_type="property" 诚实标弱于 DSR numerical。
- PBO P2「噪声≈0.5」用固定 seed 噪声矩阵 + 容差（如 0.5±0.15）；极端容差选择是工程判断、非定理精确值。
- 仍只覆盖信任层三角三支；conformal/attribution/MinTRL/drift（main 新增）等其余数学点逐个绑后续。

## → 拆成的任务（本切片实现，落 done）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | PBO/bootstrap 漂移→property 一致性 fail→生产 gate fail-closed；三角三支全上脊柱 | P0 | 4458ff54(DSR 接生产 gate) |
