# FINDING · 因子收益归因（returns-based factor attribution · 北极星「归因」阶段）

## 核心主张（可证伪）[必填]
组合实现收益可**精确分解**为「各因子贡献 + 特异收益」，且分解满足**加总恒等式**（命门）：
各因子贡献之和 + 特异收益 ≡ 组合总收益（逐位，非近似）。北极星 pipeline 的「归因」阶段此前无独立模块。

### 数学（公式 + 理论）
**模型**：组合超额收益 r_t 对 K 个因子收益 F_{k,t} 的时序回归（含截距）：
$$r_t = \alpha + \sum_{k=1}^{K} \beta_k F_{k,t} + \varepsilon_t,\quad t=1..T$$
OLS 估 `β̂=(X'X)^{-1}X'r`，X=[1, F]（T×(K+1)）。

**分解**：定义因子 k 的累计贡献与特异贡献：
$$\mathrm{contrib}_k = \hat\beta_k \sum_t F_{k,t},\qquad \mathrm{specific} = T\hat\alpha + \sum_t \hat\varepsilon_t$$
**加总恒等式（命门·证）**：由 `r_t = α̂ + Σ_k β̂_k F_{k,t} + ε̂_t` 逐期求和 ⇒
$$\sum_t r_t = T\hat\alpha + \sum_k \hat\beta_k\sum_t F_{k,t} + \sum_t\hat\varepsilon_t = \sum_k \mathrm{contrib}_k + \mathrm{specific}$$
对**任意** β̂（不限 OLS）恒成立（纯代数，只要 ε̂=r−Xβ̂）∎。故归因恒「闭合」、无未解释残漏被悄悄丢弃。
注：OLS+截距下 `Σε̂_t=0`，故 specific≈Tα̂（intercept 主导），但实现用 `specific=Tα̂+Σε̂` 保恒等式逐位精确。

**R²**：`1 − SS_res/SS_tot`，报因子解释占比（低 R² = 收益多由特异/未纳入因子驱动，诚实披露、绝不渲染成「已归因」）。

### 诚实处置（不假绿灯）
- **样本不足**：`T < K+2`（无回归自由度）→ status='insufficient'、不出 β（先验断言未经检验）。
- **共线**：rank(X) < K+1（因子线性相关/常数列）→ status='collinear'、不报不可识别的 β（绝不把噪声 β 当真）；
  接近共线（condition number 高但满秩）→ status='ok' + warning（β 不稳）。
- **非有限**：r/F 任一非有限的行整行剔除（保对齐），剔后不足 → insufficient。

## 接线点（本项目 file:line）[必填]
- 新建 `app/backend/app/eval/attribution.py`：`factor_return_attribution` + `AttributionResult`。
- **消费侧物料 + 对齐器 ✅ done（2026-06-25·done 卡 8f9d79fd·审计 #2）**：
  - **per-period 因子收益 provider** `factor_factory.layered.factor_return_series(market, formula)` → 单因子多空收益时序
    F_t = 顶分位组内等权 fwd-return − 底分位组内等权（Grinold-Kahn 分位价差·leak-free 复用抽出的 `_binned_factor_panel`
    同 layered 单一滞后源+point-in-time 分桶·诊断口径非可下注·h>1 重叠窗 β 精度 caveat）。根治「factor_returns 必手搓=输入假绿灯」。
  - **ts 对齐器** `attribution_from_series(portfolio_by_ts, factor_series_by_name)` 按 ts 键 inner-join 对齐 → factor_return_attribution
    （两侧用同一 ts 列表查值·消除手工位置 misalign；MUT「各自独立顺序」被 teeth 抓）。
  - **剩 follow-on（用户方法学·池卡 e4496023 ③）**：组合台/归因报告**端点** + 前端贡献瀑布/R²/abstain UI + 因子集选择/收益口径(excess/raw)/回归窗。
- 与 factor_factory IC 度量正交（IC=预测力、本件=已实现收益归因）。

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. **命门加总恒等式**：Σ contrib_k + specific == total_return 逐位（1e-9，跨随机因子/多 seed）。种坏：漏截距/漏某因子 ΣF → 已知 β 恢复测试抓（恒等式因构造仍成立，故恒等式 + 已知β双测）。
2. **已知 β 恢复**：r=2·F1+3·F2+小噪 → β̂≈[2,3]、contrib≈[2ΣF1,3ΣF2]、R²≈1（真判别器）。
3. **insufficient**（T<K+2）/**collinear**（重复因子列）→ 各自 status、不出假 β。
4. 非有限行剔除并披露；全常数因子 → collinear。

## 复用 [按需]
- 纯 numpy lstsq + matrix_rank；无新依赖。
