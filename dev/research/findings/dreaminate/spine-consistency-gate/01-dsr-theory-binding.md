# FINDING · DSR（Deflated Sharpe Ratio）理论 + Spine 绑定（全链贯穿第一段）

- **蒸馏自**:Bailey & López de Prado 2014「The Deflated Sharpe Ratio」· 现有实现 `app/backend/app/eval/dsr.py` · 决策 D-MATH-SPINE · finding `00-consistency-gate-theory`
- **证据强度**:强——DSR 是同行评审发表结果（proof_backed）；绑定的「实现↔定义一致」由独立 oracle（scipy 矩）数值对账 + 真源码 `inspect.getsource` 指纹证伪。
- **适用域**:成立 = 返回序列 PIT 正确（无 look-ahead）+ 诚实提交 N（试验数）。**不成立边界**:DSR 只做显著性【标度修正】，不保证「真有效」；`var_sr_hat` 不可估时退化旧极值近似、通缩可能不足（须裁决披露）。

## 核心主张（可证伪）[必填]
DSR 把「多次试验后偶然高 SR」的偏差通缩进显著性。z 统计量（V 不可估分支，studentized）：

```text
SR_pp   = mean(r) / std(r, ddof=1)                    # 每期 Sharpe
γ3      = m3/m2^1.5            (有偏偏度, = scipy.skew(bias=True))
γ4−3    = m4/m2^2 − 3          (有偏超额峰度, = scipy.kurtosis(fisher,bias=True))
denom   = sqrt(1 − γ3·SR_pp + (γ4−3+2)/4 · SR_pp²)
E[max]  = sqrt(2 ln N) − γ_euler/sqrt(2 ln N)         # N 试验下 SR 极大值期望
z       = SR_pp·sqrt(T−1)/denom − E[max]
DSR     = Φ(z) ∈ [0,1]
```

**如果**实现 `deflated_sharpe_ratio` 在任意 fixture 上偏离这套定义超过容差 ε，**则** Spine 数值 ConsistencyCheck 必判 fail、一致性门必拒升级（命门：理论对、实现跑偏=系统错误）。

## 接线点（本项目 file:line）[必填]

| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/backend/app/eval/dsr.py` | `deflated_sharpe_ratio` + `_skew/_kurt_excess/_expected_max_sr/sharpe_ratio` | 被绑定的真实现；整条计算链进指纹 |
| `app/backend/app/lineage/spine_binder.py` | 新增 | 可复用：`code_fingerprint`（真 `inspect.getsource` 指纹）+ `numerical_consistency_check`（impl vs 独立 oracle）+ `bind_callable` |
| `app/backend/app/eval/spine_bindings.py` | 新增 | DSR worked example：artifact + 独立 oracle（scipy 矩）+ `verify_dsr_consistency()` 跑通 artifact→binding→check→gate 全链 |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. 正确 impl vs 独立 oracle（scipy 矩）→ 数值一致性 pass、门 promotable=proof_backed。
2. **种漂移 impl**（如丢掉 E[max] 通缩 = 退回裸 Sharpe 显著性，或 ddof 错）→ oracle 对账 fail → 门拒、granted=challenged（命门）。
3. **真源码指纹**：`code_fingerprint(deflated_sharpe_ratio, _skew, ...)` == `content_hash(inspect.getsource 拼接)`；改 dsr.py 任一函数 → 指纹变 → 若 binding 未刷新，门 fresh 子句拒。
4. 整条计算链入指纹：只改 `_skew` 不改主函数 → 指纹仍变（防「改 helper 绕过」）。
5. PIT：DSR 的 data_contract 携带返回序列 known_at/effective_at（统计检验的输入须 PIT 正确）→ 缺则 pit-bound 拒。

## 复用 [按需]
`lineage/ids.content_hash`（指纹单一源）· `lineage/spine_gate.evaluate_promotion`（门）· `lineage/spine.MathematicalArtifact/TheoryImplementationBinding/ConsistencyCheck` · `lineage/spine_ledger.SpineLedger` · `scipy.stats`（独立 oracle 矩）。

## 未验证残余（诚实）[必填]
- 本切片建「DSR 绑定 + 独立 oracle 对账 + 门」并证明漂移被抓；**尚未**把 `verify_dsr_consistency()` 接进生产 promote 路径（`run_verdict`/`overfit_gate`/`ide.promote`）——那是下一切片（接进后 promote 时实时核 DSR 一致性）。
- oracle 与 impl 共享「每期 SR + z 公式」骨架，独立性在【矩计算】层（scipy vs 手算 m_k）；能抓矩/符号/cdf/通缩漂移，不能抓「定义本身错」（定义对错靠 Verifier/Critic + 文献，不是本门）。
- 全链贯穿仍只覆盖 DSR 一个点；factor/model/signal/portfolio/execution/attribution/monitor 其余数学点逐个绑是后续切片。

## → 拆成的任务（本切片实现，落 done）[必填]

| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | DSR 漂移→oracle 对账 fail→门拒；真源码指纹 staleness 抓改动 | P0 | a00b3956(spine 门核心) |
