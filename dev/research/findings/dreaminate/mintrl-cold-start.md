# FINDING · R27 冷启动 MinTRL（最小业绩期长度）+ 诚实"证据不足"

- **蒸馏自**:GOAL §6「冷启动 N=1 诚实'证据不足'（剔除 DSR 用 PSR/MinTRL + 隐性 champion）」+ 决策 R27=确认 + 并行双脑（codex xhigh 确认 MinTRL 是当前 PSR 口径的正确代数逆 + 边界/交叉校验）。
- **证据强度**:强 —— MinTRL 出自 Bailey & López de Prado 2012，是 PSR 的解析反解；扩展已交付且变异/不变量验证过的 PSR（`eval/dsr.py`）。
- **适用域**:有 ≥3 期收益可估矩。**不成立的边界**：N=1/2 估不出矩 → insufficient（绝不假装算出）；SR_pp≤SR* → MinTRL=+∞（不超基准，加样本无用）；自相关序列 √(n−1) 高估有效样本（同 PSR，docstring 披露）。

## 核心主张（可证伪）[必填]

**如果**观测到（短）业绩期的每期 Sharpe SR_pp > 基准 SR*，**则**达到置信 p 所需**最小业绩期长度**
**MinTRL = 1 + denom²·(Φ⁻¹(p)/(SR_pp−SR*))²**（denom² 与 PSR 同项）；**而** n_observed < ⌈MinTRL⌉ → 诚实
**"证据不足"**（业绩期太短、未达 p 置信）；SR_pp≤SR* → MinTRL=+∞（任何样本都不显著）。**命门交叉校验**：
n=MinTRL 时 PSR(SR*)≡p（MinTRL 是 PSR 的反解，两路必吻合）。**R27**：N=1 时 DSR 退化为 PSR=范畴误用
（无 trial universe 可通缩选择偏差）→ 冷启动 **DSR=N/A、PSR=显著性、MinTRL=最小 obs**，绝不"DSR=PSR 所以过/否"。

### 数学（公式 + 推导）

PSR(SR*)=Φ((SR_pp−SR*)·√(n−1)/√denom²)（denom²=1−γ3·SR_pp+(γ4−1)/4·SR_pp²，per-period）。解 PSR≥p：
$$(SR_{pp}-SR^*)\frac{\sqrt{n-1}}{\sqrt{denom^2}}\ge \Phi^{-1}(p)\ \Rightarrow\ n-1\ge denom^2\Big(\frac{\Phi^{-1}(p)}{SR_{pp}-SR^*}\Big)^2$$
$$\boxed{MinTRL = 1 + denom^2\cdot\Big(\frac{\Phi^{-1}(p)}{SR_{pp}-SR^*}\Big)^2},\quad MinTRL_{obs}=\lceil MinTRL\rceil$$
- **denom² 与 PSR 完全同项 + 同 max(1e-12,·) 钳**（否则不再是 PSR 的代数逆）；SR* per-period（同 PSR 签名）；Φ⁻¹(p)=**单侧**（PSR 是单侧）。
- **命门交叉校验（PSR↔MinTRL）**：代入 n=MinTRL_real → z=(SR_pp−SR*)·√(denom²(Z_p/Δ)²)/√denom²=Z_p → PSR=Φ(Z_p)=p。**恒等**。⌈MinTRL⌉ 处 PSR≥p。
- **边界**：SR_pp≤SR*（Δ≤0）→ MinTRL=+∞（never_significant，非 insufficient）；n<3 → insufficient（估不出矩，同 PSR n<3 退化）；confidence∈(0.5,1)（Z_p>0，否则"最小"语义退化）→ 校验；Δ→0 → MinTRL 爆炸（防 overflow→∞，合理"证据不足"信号）。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么(扩展不替换) |
|---|---|---|
| `app/eval/dsr.py` | +`MinTRLResult` + `minimum_track_record_length` | 复用 _skew/_kurt_excess/denom 口径；与 PSR 互为反解交叉校验 |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. **PSR↔MinTRL 交叉校验（命门）**：n=⌈MinTRL⌉ 的同矩序列 PSR≥confidence（且 real 处≈confidence）；公式转写错（denom 不一致/√(n−1)↔n）则崩。
2. SR_pp≤SR* → MinTRL=+∞（never_significant，绝不返有限数假装可达）。
3. n<3 → insufficient（绝不假装算出 MinTRL）；R27 N=1 → insufficient + DSR=N/A 语义。
4. 单调：confidence↑ → MinTRL↑；Δ（SR_pp−SR*）↑ → MinTRL↓；denom²↑（高阶矩病态）→ MinTRL↑。
5. confidence∉(0.5,1) → raise；Z_p 单侧（非双侧）。
6. n_observed<⌈MinTRL⌉ → sufficient=False（证据不足）；≥ → True。

## 复用 [按需]
- `app/eval/dsr.py`：`_skew`/`_kurt_excess`/sharpe/denom 同口径（MinTRL 是 PSR 反解）；`probabilistic_sharpe_ratio` 做交叉校验。

## 未验证残余（诚实）[必填]
- **自相关**：√(n−1) 假设 IID，自相关下 MinTRL 低估（同 PSR，docstring 披露）。
- **矩估计**：MinTRL 用观测短样本估的 SR_pp/γ3/γ4——短样本矩本身噪声大（鸡生蛋）；MinTRL 是"按当前估计"的最小长度、非保证。docstring 标。
- **隐性 champion / 呈现**：R27 的"隐性 champion + 标先验断言未经数据检验"属呈现层（前端），本切片只给 MinTRL 数学 + sufficient 判定；冷启动 UI 接线属后续。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | MinTRL 数学对齐 R27/PSR 反解、命门交叉校验、SR≤SR*→∞、n<3→insufficient、单调、confidence 校验 | P1 | — |
| (建议后续) | 冷启动 UI 接 MinTRL：DSR=N/A + PSR + "需 N 期证据不足" 渐进披露（R25/R27 呈现层） | P2 | 本切片 |
