---
name: math-kernel-p0-p3-decomposition-draft-20260716
description: 金融数学 kernel epic 的 P0-P3 分解草案（本仓视角·排在内嵌 agent epic 之后·仅规划不实装）。承 [[math-spine-gap-analysis-gpt-20260716]] + [[D-EPIC-PRIORITY]] + [[D-GOVERNANCE-LIGHT]]。
status: 草案（未拍板·未实装·排 agent epic 之后）
type: epic-decomposition
---

> **草案 · 未实装 · 排在内嵌 agent epic（M5b→M4b→M6）之后**（[[D-EPIC-PRIORITY]]）。这是本仓对外部 GPT gap 分析（[[math-spine-gap-analysis-gpt-20260716]]）的**本仓视角再结构化**——把「6+ 条主干缺口」落成可排期的切片，不是照搬原文。**尚未评估、尚未拍板哪些真做**；correctness（数学↔实现一致）与安全红线不放宽，治理层按 [[D-GOVERNANCE-LIGHT]] **L6 default-advisory**（缺失/失败**告警不硬阻断**，operator 可放行）。起做前须过一轮跨厂商评估（哪些主干真缺、哪些现有已够）。

## 0. 定位与边界

- **不是** 现在开工的信号。当前活跃切片 = 内嵌 agent epic M5b（canvas_create_node）。此草案只回答「若/当轮到金融数学 kernel，怎么切」。
- **不另起炉灶**：接现有 `app/backend/app/research_os/spine.py` 的 Mathematical Spine（TheorySpec/MathematicalArtifact/EstimatorSpec/RiskMeasure/TheoryImplementationBinding/ConsistencyCheck 已在），**扩展不替换**。GPT 原文批评「artifact 是文本容器非可执行类型系统」——本仓把它当**演进方向**，不是推倒重来。
- **prior-art-first 强制**（全局软规）：金融数学几乎全是「有名字的算法/数学统计数值」，判定式命中。每个 P 层先做三层查找（L1 已装 scipy/numpy/statsmodels/pandas 读源码 → L2 生态成熟库 QuantLib/arch/linearmodels/cvxpy → L3 论文参考实现），**自研必配 oracle**（参考库当 dev-only 测试依赖做黄金对照）。新依赖是拍板项，摆候选不擅自装。

## 1. 与现有主干的接缝（起做前必先勘定）

先跑一轮盘点（跨厂商）确认「现有 spine 已覆盖 vs 真缺」，避免 GPT 原文的「明显不足」评级把已建的重估为缺失：
- **已相对成熟**（原文亦承认，本仓 state/GOAL 有据）：PIT/数据时间意识、因子表达式、IC/RankIC、防泄露 CV、PBO/DSR/PSR/Bootstrap、Honest-N/Effective-N、Conformal、基础组合、平方根冲击、理论-实现绑定门。→ 这些**不重造**，P1+ 复用。
- **勘缝产物**：一张 `math_kernel_seam_matrix`（现有 spine 对象 × GPT 主干 → 覆盖/部分/缺），作为 P0 的门票。**没勘缝前不写任何 math/ 代码**。

## 2. P0-P3 分解（本仓切法）

### P0 — 数学内核底座（所有资产包共用·先做）
GPT 原文的 P0 = 随机分析 + 数值 + 统计三块。本仓切成**可独立过门的薄纵切**，每切一个 typed 对象族 + 一个数值实现 + 一个 oracle 黄金测试：

- **P0.1 概率/测度/信息结构 typed 层**：`MeasureContext`(physical/risk_neutral/terminal_forward/empirical/subjective)、`FiltrationSpec`、`StochasticProcessSpec`（drift/diffusion/domain/generator）。**最高杠杆**——把「这条公式在 P 还是 Q 下」从 `assumptions: str[]` 升成机器可判类型（原文列为最应优先补）。接缝：`FiltrationSpec` 是现有 PIT/known_at 的数学上层（X_t 可交易 ⇒ X_t∈F_t），**把防泄露从工程约定升成数学可验证属性**。
- **P0.2 数值求解底座**：SDE 离散（Euler-Maruyama/Milstein，记 strong/weak 误差阶）、Monte-Carlo（antithetic/control-variate/QMC）、误差账本 `ErrorBudgetSpec`。oracle = 解析可解 case（GBM 闭式 / OU 平稳分布）对照。prior-art：numpy RNG + scipy.stats + 参考 QuantLib 数值。
- **P0.3 统计/状态空间**：Kalman 家族（linear/EKF/UKF）、GARCH 族、GMM/MLE 估计器接现有 EstimatorSpec、多重检验补 BH-FDR/SPA/MCS 接现有 Honest-N/PBO。prior-art：statsmodels（Kalman/GARCH/VAR）、arch（GARCH）、linearmodels（面板/FMB），当 oracle。
- **P0 治理**：每个数学对象带 `MathCapabilityMatrix` L0-L7 标签，但 **L6 门 default-advisory**（[[D-GOVERNANCE-LIGHT]]）——L2 数值收敛测试 + L3 校准绑真 DatasetVersion 是 correctness（硬），L6「缺失即阻断晋级」降级为 advisory 告警，operator 裁决。

### P1 — 机构股票研究 + 组合风险（离用户可见价值最近）
- **P1.1 横截面因子推断**：Fama-MacBeth + 双向 cluster SE + GRS/SDF-GMM 检验，接现有 Factor Library（原文：现有强于「发现」弱于「资产定价意义上证/反驳」）。prior-art：linearmodels.FamaMacBeth 当 oracle。
- **P1.2 风险模型**：协方差收缩升级（现有 hrp_audit 的固定参数 Ledoit-Wolf → 自动线性/非线性收缩 + 因子协方差 + 稀疏逆协方差）、**真 ERC**（现有 `risk_parity` 实为逆波动率，原文点名）求解 RC_i 相等。prior-art：sklearn.covariance（LedoitWolf/GraphicalLasso）、riskfolio/PyPortfolioOpt 参照。**改名**：现逆波动率基线标注为 inverse-volatility，不冒充 ERC。
- **P1.3 尾部风险 + 情景**：VaR/ES 引擎 + Kupiec/Christoffersen 回验 + EVT(POT/GPD) + Copula + `ScenarioGeneratorSpec`。prior-art：scipy.stats(genpareto) + arch(bootstrap) oracle。
- **P1.4 成本敏感多期组合**：Mean-CVaR/DRO + turnover/impact/margin 约束直接进优化问题（原文批评现有是「优化后截断」破坏最优性）。prior-art：cvxpy（凸求解）当引擎。
- **P1.5 执行**：Almgren-Chriss 轨迹优化 + TCA（IS 分解），升级现有平方根冲击基线。

### P2 — 期权/波动率/利率/外汇（终态定价语义）
- 静态无套利（put-call parity/butterfly convexity/calendar monotonicity）先行（廉价、抓数据错）；BS/Black-76/局部波动率/Heston/SABR；IV 反演 + SVI/SSVI arb-free 面拟合；曲线 bootstrap + DV01/key-rate；Hull-White/HJM/LMM；FX forward/basis/quanto。**prior-art 主力 = QuantLib**（成熟、被机构用）——评估作 dependency（license: QuantLib = modified BSD，宽松可融合）或参照重写 + QuantLib 当 oracle。license 拍板项。

### P3 — 信用/XVA/商品/复杂品/rough vol（最远·基本缺失）
- hazard/CDS bootstrap、structural credit(Merton)、migration/default dependence、CVA-XVA、商品 convenience yield/delivery option、convertible/结构性票据、variance/vol swap、rough vol(rough Heston)、Lévy 高级跳跃。原文列为「基本缺失/主要终态语义」，离本仓当前最远，P3 兜底。

## 3. 建议模块形态（草案）
`app/backend/app/math/{core,stochastic,numerics,econometrics,asset_pricing,risk,portfolio,derivatives,rates,credit,fx,futures,commodities,crypto,execution}/`。**关键不是目录数**，而是每个资产包**复用同一套** `MeasureContext`/`StochasticProcessSpec`/`CalibrationSpec`/`NumericalSchemeSpec`/`RiskMeasureSpec`/`ConsistencyCheck`——不各自重解释数学。落地时逐目录薄纵切、逐切过门，不一次铺开。

## 4. 每切片的过门契约（草案·沿用现有 loop 四门 + 数学附加）
1. 数学先行：公式/推导先证理论成立（理论-实现绑定门，现有机制）。
2. prior-art check：三层查找结论落到具体 repo/文件/版本 + oracle 选定。
3. 实现 + 对抗测试 + oracle 黄金测试（数值对照参考库，收敛阶/误差在预算内）。
4. 一致性门（命门）：agent 实现 ↔ 被证明理论严格一致（监管对齐，不可绕过）。
5. 治理标签 L0-L7，**L6 advisory**（不硬阻断，operator 裁决）。
6. 跨厂商 dual-model 独立审查（builder≠verifier·分属厂商）后 land。

## 5. 起做前的待拍板（不在本草案解决·登记）
- **主干取舍**：6+ 主干哪些真做、哪些现有已够、优先级——须一轮跨厂商勘缝评估后报 decision-ready brief（用户方法学放权：摆代价、给推荐、用户拍）。
- **新依赖**：QuantLib / arch / linearmodels / cvxpy / riskfolio 是否引入（各是拍板项·license 表：QuantLib BSD、arch NCSA、linearmodels NCSA、cvxpy Apache-2.0 — 均宽松，可融合，但引依赖仍用户拍）。
- **范围**：这是平台最大 epic（原文语），排在 agent epic 之后；起做时机 = agent M6 收尾后由用户/中心 orchestrator 拍。

> 本草案只做「怎么切」的骨架，**不含任何 math/ 代码**，不改 agent epic。承接见 [[D-EPIC-PRIORITY]]（M5b→M4b→M6→math P0）。
