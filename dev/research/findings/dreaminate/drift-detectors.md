# FINDING · §5 生产期漂移检测器（rolling-PSR / CUSUM / Page-Hinkley / PSI）

- **蒸馏自**:GOAL §5「漂移监控（rolling-PSR/CUSUM/Page-Hinkley/PSI，绩效轴主告警 / 特征漂移仅根因，绝不把 DSR 搬实盘单策略）」+ state.md 点名「新生残余建议 mint 卡：§5 漂移检测器 PSR/CUSUM/PSI」+ 并行双脑复核（deep-opus ‖ codex，三脑收敛）。
- **证据强度**:强 —— 4 个检测器公式均出自标准文献（Bailey & López de Prado 2012 PSR / Page 1954 CUSUM / Hinkley 1971 PH / PSI 业界标准），并经 deep-opus + codex 独立推导逐一确认；PSR↔DSR 恒等已实证到 1e-12；PH 全局 running-mean 陷阱经 deep-opus 实证（平稳噪声 494/500 假告警）。
- **适用域**:中低频、IID/近平稳收益序列。**不成立的边界**：A股 T+1/涨跌停破坏 PSR 平稳假设（R14）→ 短样本必判「证据不足」非红绿；自相关序列 PSR 高估有效 n（须披露）；PH 全局 running-mean 变体在长程平稳流上 FPR→1（已弃用、改 frozen-baseline）。

## 核心主张（可证伪）[必填]

**如果**一条已上线策略/因子的实盘绩效真的衰减（均值下移、Sharpe 显著性流失），**则** rolling-PSR 跌破下限（主告警）且 CUSUM S⁻ / frozen-baseline Page-Hinkley 越阈（绩效轴），驱动 lifecycle 权威评估退役；**而** PSI（特征分布漂移）只产出根因诊断、**绝不**单独触发退役。三者检测器对「无漂移」恒不告警、对「不可判定（短样本/退化）」恒返回 `insufficient_evidence` 而非 `ok`（不假绿灯）。

### 数学（论文公式 + 理论为何成立）

记单期（per-period，**非年化**）Sharpe $\widehat{SR}=\bar r/s$（$s=\text{std}(ddof{=}1)$）。

**① rolling-PSR**（Bailey & López de Prado 2012，绩效轴**主告警**）
$$\widehat{PSR}(SR^*)=\Phi\!\left(\frac{(\widehat{SR}-SR^*)\sqrt{n-1}}{\sqrt{1-\gamma_3\widehat{SR}+\frac{\gamma_4-1}{4}\widehat{SR}^2}}\right)$$
- $\gamma_3$=偏度、$\gamma_4$=**完整**峰度（正态=3）；代码复用 `dsr.py._kurt_excess`（存超额峰度 $g_2=\gamma_4-3$）⇒ 分母项 $\frac{\gamma_4-1}{4}=\frac{g_2+2}{4}$（= dsr.py line 84）。
- **理论为何成立**：$\widehat{SR}$ 的渐近分布（Lo 2002 / Mertens 2002）近正态、方差 $\frac{1-\gamma_3 SR+\frac{\gamma_4-1}{4}SR^2}{n-1}$。PSR 即 $\Pr(SR>SR^*\mid\widehat{SR})=\Phi(z)$，恒 $\in[0,1]$。退役监控取 $SR^*=0$：「实盘 edge 是否仍显著为正」。
- **与 DSR 的范畴区分（命门 D1）**：DSR = PSR 把 $SR^*$ 设成 $E[\max SR\text{ over }N\text{ trials}]$（多重检验通缩，晋级期过拟合闸）。**rolling-PSR 检测器签名根本不暴露 `n_trials`/`var_sr_hat`，只接固定 `sr_benchmark`** ⇒ 结构上杜绝把 DSR 通缩伪装成 live 退役触发器（违 M-AUTHORITY=A1）。

**② CUSUM**（Page 1954 双侧 tabular，frozen 基准 μ0，绩效轴确证）
标准化 $z_t=(x_t-\mu_0)/\sigma_0$（μ0/σ0 = 晋级期 OOS 冻结基准，**绝不用监控窗自身均值**，否则缓慢漂移免疫——温水煮青蛙 E2）：
$$S^+_t=\max(0,\;S^+_{t-1}+z_t-k),\quad S^-_t=\max(0,\;S^-_{t-1}-z_t-k),\quad \text{告警 } S^\pm_t>h$$
- $k$=slack（≈待检测位移的一半，σ 单位），$h$=决策区间（σ 单位，典型 4~5）。绩效下降看 $S^-$、成本上升看 $S^+$。
- **理论为何成立**：CUSUM 是重复 SPRT，对已知幅度均值位移在给定误报率下检测延迟最优（Moustakides 1986）。$\max(0,\cdot)$ 反射壁保证 $S^\pm\ge0$ 且无漂移时回落到 0。

**③ Page-Hinkley**（frozen-baseline 变体，检测均值**下降**，绩效轴确证）
$$m_t=\sum_{i=1}^t\big[(\mu_0-x_i)-\delta\big],\quad M_t=\min_{0\le s\le t}m_s,\quad PH_t=m_t-M_t\ge0,\quad \text{告警 }\max_t PH_t>\lambda$$
- $\delta$≥0 容差（保护性 slack）、$\lambda$ 阈。无漂移：$m_t\approx-t\delta$ 下行、$M_t$ 跟随running-min ⇒ $PH_t$ 被 δ 压住；持续下降 $x_i=\mu_0-\Delta\;(\Delta>\delta)$：$m_t=t(\Delta-\delta)$ 线性增 ⇒ 必越 λ。
- **为何弃用教科书全局 running-mean 变体（deep-opus 实证陷阱 E1）**：$m_t=\sum(x_i-\bar x_t-\delta)$ 在平稳流上是带漂移随机游走，包络随 $\sqrt t$ 无界增长 ⇒ 固定 λ 必被穿越，FPR→1（实证 N(0,1) 500 窗 494/500 假告警，δ 增大反而 500/500）。**改 frozen-baseline 后 δ 变保护 slack（CUSUM-like），FPR 受控**。配 sentinel 测试钉死此判别力（R5 守门器自身风险自证）。

**④ PSI**（Population Stability Index，特征漂移**仅根因**）
$$PSI=\sum_{i=1}^B (a_i-e_i)\ln\frac{a_i}{e_i}=D_{KL}(A\Vert E)+D_{KL}(E\Vert A)\ge0$$
- $e_i/a_i$=expected(基准期)/actual 归一化占比；**桶边界由 expected 一次性冻结**（actual 用同套边界，否则把分桶变化误当漂移）。零桶 ε-clip（1e-6 固定常量）+ 返回 `zero_bucket=True`，**平滑后 PSI 绝不作退役 breach**。
- **理论**：PSI 是 Jeffreys（对称化）散度，$\ge0$、=0 ⟺ 两分布同、**对称** $PSI(a,e)=PSI(e,a)$（区别于非对称 KL）。阈值 <0.1 无显著 / 0.1–0.25 中度 / >0.25 重大。
- **范畴红线（命门 D2）**：PSI 是**特征**分布漂移、非绩效失败证据。结构隔离见下。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/eval/dsr.py` | 新增 `probabilistic_sharpe_ratio` | PSR 构件，复用 `_skew`/`_kurt_excess`/σ 阈；与 `deflated_sharpe_ratio` V-path 互为 1e-12 交叉校验 |
| `app/monitor/drift.py` | 新建 | 4 检测器 + 三态 + 绩效轴/特征轴类型隔离 + `PerfDriftSignal.to_lifecycle_observation()` |
| `app/monitor/closure.py` | `monitor_tick` 加可选 `perf_drift` 入参（additive，向后兼容） | 绩效轴漂移 breach → 喂 lifecycle 权威（同 cost_drift 路径，M-AUTHORITY 允许）；PSI 永不进此路径 |
| `app/monitor/__init__.py` | 导出新符号 | — |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. **PSR 量纲**：把 per-period SR 误年化（×√252）→ PSR↔DSR V-path 恒等断言（<1e-12）立崩。
2. **PSR 越界**：denom 不钳制 `max(1e-12,·)` → 病态高阶矩 sqrt(负)=NaN → `psr∈[0,1] 且非 NaN` 跨 300 seed 抓。
3. **PSR 单调**：$SR^*$ 升 PSR 反升（符号搞反）→ `单调递减` 抓。
4. **CUSUM 反射壁**：去掉 `max(0,·)` → `S±≥0` 抓；用监控窗自身均值当 μ0 → 「温水煮青蛙」缓慢下降不告警（种线性缓降序列断言 S⁻ 必破 h）。
5. **CUSUM 方向**：S⁺/S⁻ 搞反 → 种 step-down 断言 S⁻ 先破 h（非 S⁺）。
6. **PH 全局 running-mean 陷阱**：sentinel 证明弃用变体在平稳噪声上假告警（FPR 随窗长↑），frozen-baseline 变体不假告警 → 钉死设计选择有判别力。
7. **PH 方向**：误用上升版（min→max 反）→ 种 step-down 断言告警。
8. **PSI 对称 + 非负**：实现成非对称 KL → `PSI(a,e)==PSI(e,a)` 抓；负值 → `PSI≥0` 抓。
9. **PSI 范畴红线（最关键）**：种「PSI=∞（剧烈特征漂移）但 PSR 仍显著为正」→ 断言 **lifecycle 不迁移、不产生退役观测**；反向「PSI≈0 但 PSR 崩」→ 断言照常退役。PSI result 类型**无 breach 字段、无 to_observation**，喂退役矩阵编译/类型层即拒。
10. **三态**：短样本/σ≈0/桶不匹配 → 返回 `insufficient_evidence`（非 `ok` 非 `breach`），断言不被当绿灯。

## 复用 [按需]
- `app/eval/dsr.py`：`sharpe_ratio` / `_skew` / `_kurt_excess` / σ<1e-12 阈 / `_expected_max_sr`（仅交叉校验用，**不进 drift 检测器签名**）。
- `app/factor_factory/lifecycle.py`：`FactorObservation`（绩效轴漂移以负 ic_mean 表达退化，喂 `LifecycleManager`，A1 权威）。
- `app/monitor/closure.py`：`_drift_degrade_observation` 模式（perf 信号造降级观测）。

## 未验证残余（诚实）[必填]
- **CUSUM/PH 的 μ0/σ0 须由晋级期 OOS 冻结基准提供**；本切片提供检测器机制 + 接口，生产「冻结基准持久化 + 跨重启」依赖上游观测管道（与 state.md「监控观测跨重启持久化」残余同源，宜后续 mint 卡）。检测器本身不自造基准。
- **PSR 自相关高估有效 n**：重叠窗/序列相关下显著性被高估（更易误「显著」）；本切片 docstring 披露，Newey-West 有效 n 调整未做。
- **A股 R14**：检测器接收 `min_samples` 守门返回 `insufficient_evidence`；涨跌停日收益截断污染高阶矩仅标 caveat，未做降权/删失校正。
- **λ/h/k 阈值标定**：给文献默认（h≈4~5σ、PSI 0.1/0.25），真实生产标定（ARL₀ 目标）属用户方法学旋钮、未锁死。
- **PH 仅作绩效轴确证**：因 running-mean 陷阱的教训，PH 在本设计中是确证信号而非唯一触发器；rolling-PSR 才是主告警。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
> 本 finding 即「§5 漂移检测器」卡的设计稿；本切片直接实现（leader 自取，非走 pool 分配）。下游残余建议 mint：

| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | 4 检测器 + PSR↔DSR 交叉校验 + PH 陷阱 sentinel + PSI 范畴隔离对抗测试全绿、基线不破 | P1 | — |
| (建议后续) | 晋级期 OOS 冻结基准 μ0/σ0 持久化 + 跨重启喂 CUSUM/PH（监控观测跨重启持久化残余） | P2 | 本切片 |
