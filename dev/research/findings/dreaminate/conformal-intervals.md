# FINDING · R23 不确定性预测区间（split conformal / CQR / ACI）+ abstain

- **蒸馏自**:GOAL §4「conformal/CQR/ACI 区间 + abstain（R23）」+ 决策 R23=A（合理区间防呆、**不锁 α**）+ 并行双脑复核（codex xhigh 独立推导，确认公式 + 修正 ACI 长程界 + CQR Q̂ 可负边界）。
- **证据强度**:强 —— 三法均出自标准文献（Vovk / Lei et al. 2018 split conformal · Romano-Patterson-Candès 2019 CQR · Gibbs-Candès 2021 ACI），覆盖定理是**分布无关有限样本**结论，可直接 Monte-Carlo 证伪（覆盖率 ≥ 1−α 是机器可校验的理论性质）。
- **适用域**:**exchangeability**（可交换性）成立时 split/CQR 的边际覆盖 ≥1−α 严格成立；**时序违反 exchangeability**（这正是 ACI 的存在理由——ACI 不需可交换、保长程频率覆盖）。**不成立的边界**：条件覆盖（per-x）无保证、只保边际；校准集污染（参与训练/调参）破坏保证；OOD/regime drift 下 split/CQR 不能续称分布无关。

## 核心主张（可证伪）[必填]

**如果**校准集与测试点可交换、且校准数 n ≥ ⌈1/α⌉−1，**则** split-conformal 区间 C(X)=[μ̂(X)−q̂, μ̂(X)+q̂]（q̂=分数第 ⌈(n+1)(1−α)⌉ 阶）的边际覆盖 P(Y∈C)∈[1−α, 1−α+1/(n+1)]，**分布无关**（重尾/偏态/异方差同保）；CQR 同保证但区间宽度**自适应**；**而**当 n<⌈1/α⌉−1 / 输入非有限 / 区间无信息 → **abstain**（诚实「证据不足、不给区间」，绝不退化成全实区间或假区间）；时序漂移下 **ACI** 在线调 αₜ 保长程覆盖频率→1−α。

### 数学（论文公式 + 理论为何成立）

**① Split Conformal**（Vovk; Lei et al. 2018）
校准分数 sᵢ=|Yᵢ−μ̂(Xᵢ)|，排序 s₍₁₎≤…≤s₍ₙ₎。秩 **k=⌈(n+1)(1−α)⌉**：
$$\hat q = \begin{cases} s_{(k)} & 1\le k\le n \\ +\infty\ (\Rightarrow \textbf{abstain}) & k>n \end{cases},\qquad C(x)=[\hat\mu(x)-\hat q,\ \hat\mu(x)+\hat q]$$
- **覆盖定理**：可交换 ⇒ P(Y∈C)≥1−α；分数连续无 ties ⇒ ≤1−α+1/(n+1)。**分布无关、有限样本**。
- **理论为何成立**：测试分数 s_{n+1} 在 {s₁..sₙ,s_{n+1}} 中的秩在可交换下均匀分布 ⇒ P(s_{n+1}≤s₍ₖ₎)≥k/(n+1)≥1−α。
- **abstain 阈**：k>n ⟺ **n<⌈1/α⌉−1**（α=0.1 需 n≥9；α=0.05 需 n≥19）。此时无法在该 α 给有限区间 → abstain（**绝不退化成最大残差或 (−∞,∞)**：全实区间覆盖=1 却零信息，比 abstain 更不诚实）。

**② CQR — Conformalized Quantile Regression**（Romano et al. 2019）
给定下/上分位预测 q̂_lo(·)（≈α/2）、q̂_hi(·)（≈1−α/2），校准分数（**带符号**）：
$$E_i=\max\big(\hat q_{lo}(X_i)-Y_i,\ Y_i-\hat q_{hi}(X_i)\big)$$
（点在 [q_lo,q_hi] 内 ⇒ Eᵢ≤0，边界=0，外部=越界距离>0）。Q̂ 取 {Eᵢ} 第 k=⌈(n+1)(1−α)⌉ 阶（k>n→abstain）：
$$C(x)=[\hat q_{lo}(x)-\hat Q,\ \hat q_{hi}(x)+\hat Q]$$
- **覆盖同 split**（≥1−α，无 ties ≤1−α+1/(n+1)），但宽度**自适应**（异方差区更宽）。
- **关键边界**：**Q̂ 可为负**（合法收窄原分位区间）；若最终 lower>upper（空集）→ **abstain/empty，绝不静默交换端点**。坏 q_lo/q_hi 仍保覆盖、只是效率差（validity 不依赖分位准）。

**③ ACI — Adaptive Conformal Inference**（Gibbs & Candès 2021，时序/分布漂移）
$$err_t=\mathbb 1[Y_t\notin C_t(\alpha_t)],\qquad \alpha_{t+1}=\alpha_t+\gamma(\alpha-err_t)$$
- **方向**：err_t=1（漏覆盖）⇒ α_t↓ ⇒ 1−α_t↑ ⇒ 分位更大 ⇒ **区间变宽**；err_t=0 ⇒ 收窄。
- **长程覆盖界（codex 修正）**：$\big|\tfrac1T\sum err_t-\alpha\big|\le\frac{\max\{\alpha_1,1-\alpha_1\}+\gamma}{T\gamma}\to0$（α₁=0.1 时分子 0.9+γ，**非** α₁+γ）。**不需可交换**即保长程频率覆盖。
- **工程变体诚实标注**：原版假设分位在 [0,1] 外延拓（证 α_t∈[−γ,1+γ]）；本实现保 **raw α_t**（递推正确）+ 分位查询用 **clipped level=clip(1−α_t,0,1)**（level≥1→q=∞ 全实保守；level=0→最紧半径）。这是工程变体——**不空引论文界，实测长程覆盖收敛**（R5 守门器自身风险明示）。

### abstain（诚实不确定性 · 北极星「能信」）
**已实现**触发：① 样本不足 n<⌈1/α⌉−1 / n=0 / k>n ② 输入非有限或**非 1D**（NaN/inf/无预测/畸形形状）③ CQR 端点交叉空集 ④ split/CQR 绝对宽 width>max_width（**风险治理旋钮非 conformal 定理**，默认 None）。abstain ≠ 假区间 = 与 §5 漂移检测器三态「不假绿灯」同源。
**未实现（P2·消费侧用户旋钮）**：相对宽 width/|center|>阈、OOD/exchangeability 破坏检测——这些是消费侧风险治理，本切片不锁（R23 不锁 α 精神延伸）；docstring 披露面已收窄到「已实现」四类，绝不承诺超出实现（RULES §3）。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/eval/conformal.py` | 新建 | SplitConformalCalibrator(存排序分数,任意 α 查) + cqr_interval + AdaptiveConformalInference(在线) + ConformalInterval(含 abstain/covers/width) |
| `app/eval/__init__.py`（若有导出） | 导出 | — |
| 消费侧（model_eval / 信号层，按需 additive） | 预测附校准区间 + abstain 标 | 模型无关：只接残差/分位预测，不接模型本体（同信号契约解耦哲学） |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. 分位 +1 校正写成 ⌈n(1−α)⌉ → 小 n 欠覆盖（MC 覆盖率<1−α 被抓）。
2. k>n 不 abstain、clamp p=1 返回最大分数 → 欠覆盖 + 假区间（断言 abstain）。
3. 用 np.quantile 默认线性插值替代 ceil-rank → 与理论秩不一致（断言 q̂==sorted[k−1]）。
4. **边际覆盖（核心命门）**：多分布（正态/重尾 t/偏态/异方差）多 seed MC → 覆盖率 ≥1−α；sentinel：朴素正态区间 μ̂±z·σ̂ 在重尾下**欠覆盖**（证 conformal 分布无关有牙）。
5. 单调嵌套：α1<α2 → C_{α1}⊇C_{α2}（分位单调反了被抓）。
6. CQR 符号反/取绝对值 → 丢「区间内为负」→ 覆盖/宽度自适应崩；Q̂ 强行 max(·,0) → 非精确 CQR（保守）标注。
7. ACI 方向反 → 欠覆盖时继续收窄（断言 err=1 后 α_t↓、区间↑）；漂移下长程覆盖→1−α（vs 固定 split 漂移下 mis-cover）。
8. 排列不变 / 校准集顺序无关。
9. abstain 三态：非有限输入 → abstain，绝不返回数值区间当 ok。

## 复用 [按需]
- `app/eval/`：与 dsr/pbo/n_eff 同放（统计方法学层）；ConformalInterval 与 §5 `drift.py` 三态哲学（ok/abstain/insufficient）一脉。
- 不重造分位：手写 sort+rank（conformal 秩语义），不混用 np.quantile 默认插值。

## 未验证残余（诚实）[必填]
- **exchangeability**：split/CQR 覆盖保证依赖可交换；时序/regime drift 违反 → 须用 ACI 或显式 abstain（docstring 披露，R5）。
- **条件覆盖**：只保边际、不保 per-x 条件覆盖（不写条件覆盖断言）。
- **CQR 分位预测来源**：本切片接**已算好**的 q_lo/q_hi（模型无关解耦），分位回归模型本体不在此切片（上游模型台产出）。
- **ACI clipped-level 工程变体**：实测长程覆盖收敛、不空引论文界；raw 分位延拓的严格版未做（够用即止）。
- **max_width / OOD abstain 阈**：属用户风险治理旋钮（不锁，R23「不锁 α」精神延伸），给默认 + 摆代价。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | split/CQR/ACI + abstain 数学对齐理论、覆盖率 MC ≥1−α 跨分布、朴素区间欠覆盖 sentinel、ACI 漂移长程覆盖、不锁 α | P1 | — |
| (建议后续) | 消费侧接线：模型台/信号层预测附校准区间 + abstain UI 呈现（信任层 §6 渐进披露） | P2 | 本切片 |
