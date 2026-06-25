# FINDING · 绩效轴漂移检测器经脊柱绑定（frozen-baseline √t 命门 property）

> ⚠️ **状态：设计草案·未实现**（loop 于 2026-06-25 在实现前被用户暂停）。本文件**只是理论/设计**——
> `app/backend/app/eval/spine_bindings.py` **尚无** drift artifact / pinned 指纹 / `verify_drift_consistency`，
> 也**无**对抗测试。下方「本切片实现/落 done」是**待办计划**、不是已完成。重启 loop 后才落地实现 + 测试 + tripwire。

- **蒸馏自**:Page-Hinkley / CUSUM（SPC 经典） · rolling-PSR（Bailey-LdP） · 现有 `app/monitor/drift.py`（§5 drift） · finding `01-04` · 决策 D-MATH-SPINE
- **证据强度**:强——frozen-baseline 有可机器证伪的命门不变量：**平稳噪声不假告警**（弃用的 global running-mean 变体 √t 假告警 FPR→1，deep-opus 实证陷阱，`_page_hinkley_global_mean_variant` 即 sentinel）。漂移回退到 global-mean 变体 → 平稳噪声 breach → property 必抓。
- **适用域**:成立 = 基准 μ0/σ0 冻结（E2）。**不成立边界**:自相关序列偏离 i.i.d. 假设；阈值 λ/h/floor 是用户风险旋钮（摆代价不替拍板）。

## 核心主张（可证伪）[必填]

```text
frozen-baseline Page-Hinkley: m_t=Σ[(μ0−x_i)/σ0 − δ]; PH_t=m_t−min(m); breach=max PH>λ
  —— μ0/σ0【冻结】基准（非全局 running-mean）→ 平稳噪声 FPR 受控
CUSUM(σ单位): z_t=(x_t−μ0)/σ0; S⁻=max(0,S⁻−z−k); breach=max S⁻>h（下降侧）
rolling-PSR: PSR(SR*)<floor → 绩效漂移 breach

必要性质（命门）：
  DR1 frozen 无假告警: 平稳噪声(baseline=自身 μ/σ) → PH/CUSUM 不 breach   ← √t 命门
  DR2 真漂移检测:      均值下降序列 → PH/CUSUM breach
  DR3 rolling-PSR:    PSR<floor → breach；PSR≥floor（足够强正 edge）→ ok
                       （注：floor=0.90 默认下，弱正 edge 即 PSR<floor 也【合法 breach】——floor 是用户
                        风险旋钮、drift.py 自陈年化 Sharpe∈(0,1.28) 合法正 edge 会 breach；故 property
                        绝不能写「任意正 edge→ok」，只能「PSR≥floor→ok / PSR<floor→breach」）
  DR4 三态诚实:        短样本/非有限/σ≈0 → insufficient_evidence（绝不红绿）
```

**如果** 检测器偏离定义（如 PH 回退 global running-mean 变体），**则** DR1 平稳噪声假告警 → 脊柱 property 一致性 fail → 门拒（守 deep-opus 实证的 √t 陷阱不回潮）。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/backend/app/monitor/drift.py` | `page_hinkley_drift`/`cusum_drift`/`rolling_psr_drift`/`PerfDriftSignal`/`_insufficient`/`_all_finite` | 被绑定实现；整链进指纹 |
| `app/backend/app/eval/spine_bindings.py` | 扩展 | drift artifact + frozen-baseline 性质 + pinned + verify_drift_consistency |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. DR1 命门：平稳噪声 frozen PH 不 breach；种漂移=回退 global-mean 变体 → 平稳噪声假告警 → DR1 fail → 门拒。
2. DR2/DR3：均值下降 → PH/CUSUM breach。
3. DR4 三态：短样本 → insufficient。
4. sentinel 对照：弃用 `_page_hinkley_global_mean_variant` 在同噪声上确实 breach（证 frozen 是对的）。
5. tripwire：pinned==源指纹；staleness pinned≠live→拒。

## 复用 [按需]
`lineage/spine_binder.property_consistency_check` · `spine_gate.evaluate_promotion` · DSR/PBO/bootstrap/MinTRL/conformal 切片范式 · `eval/dsr.probabilistic_sharpe_ratio`（rolling-PSR 同源）。

## 未验证残余（诚实）[必填]
- **生产 wiring 是单独残余（非本切片）**：drift 检测器目前在生产 monitor pass（`run_weekly_monitor_pass`）**尚未接线**（state.md 载审计 #3「4 检测器接 perf_drift」未做）。故本切片是**绑定 + dev 期 tripwire 回归保护**（防 frozen-baseline 被改坏回 √t 变体），**非**生产 fail-closed 门——待检测器接进 monitor pass 后可加 verify_drift_consistency 到那条路径。诚实标弱于已接生产消费点的 DSR/MinTRL/conformal。
- property（FPR/检测力）necessary-not-sufficient；阈值精度不在判定内（用户旋钮）。
- 只绑绩效轴三检测器；PSI（特征轴·仅根因无 breach）后续。

## → 拆成的任务（**待实现**·loop 重启后落地，当前未做）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) | 状态 |
|---|---|---|---|---|
| (待 mint) | PH 回退 global-mean→平稳噪声假告警→DR1 fail→门拒；tripwire 守 frozen-baseline | P1 | 79673e0d(conformal) | **未实现（设计草案）** |
