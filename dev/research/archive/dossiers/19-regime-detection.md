# 19 · Regime 检测（HMM/变点/regime-switching）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 C

## 1. 一句话定位

本环节回答一个对「资产无关中低频 + 风险护栏」系统至关重要、却极易被过度承诺的问题：**市场当前处于哪种「状态」（牛/熊、平静/危机、低波/高波），以及这一判断能否在样本外（OOS）真正可信地驱动决策？** 范式有三条主线——(a) **概率隐状态**：Hamilton/Markov regime-switching 与高斯 HMM（statsmodels / hmmlearn），可解释但高斯发射对厚尾/跳跃拟合差；(b) **持续性优先聚类**：Statistical Jump Model（JM，按转移加 jump-penalty λ 正则化，强制状态持续性），目前是实践派被讨论最多的方法；(c) **变点检测**：PELT / BinSeg / BOCPD，回答「结构何时断裂」，可作独立确认与重训触发器。本项目的诚实立场是：**regime 是风险情景（risk context），不是收益预测（forecast）**——「识别当前状态」远易于「预测下一状态及其时点」，样本内易、样本外难，检测**天然滞后**，主要价值是**回撤控制**而非提升收益。因此默认姿态是**非对称去险**（检测到 risk-off 快速降杠杆/减仓，确认门控后才缓慢回到 risk-on），并把任何 regime 标签明确表述为「风险情景」而非「方向性预测」。

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 角色 | 要点 | URL |
|---|---|---|---|
| **Statistical Jump Models（JM）** | 实践派持续性优先方法（被讨论最多） | 对时间特征（多个半衰期的 EWMA 下行偏差 + EWMA 收益）做聚类，每次转移加一个固定 **jump penalty λ** 正则化以强制状态持续性，从而大幅压低翻转次数（论文：S&P 500 上 JM 翻转率 ~0.8/年 vs HMM ~2.0/年，见 §7 对原数字的更正）。sparse 变体做特征选择；λ 按下游 Sharpe 调；在线推断 + 半年滚动重训 = 防 look-ahead。**注**：λ「按下游 Sharpe 调」是在绩效指标上做超参搜索，本身有 PBO 风险（见 §7、§8）。 | https://arxiv.org/html/2402.05272v2 |
| **Two Sigma GMM（Factor Lens）** | 描述性宏观状态刻画（明确「非预测」） | 在 17 个宏观/风格因子上做无监督 GMM，4 个 regime（Crisis / Steady / Inflation / Walking-on-Ice），用对数似然/AIC 做 CV。用于压力测试与战术倾斜，**机构方明确声明「不是预测模型（not predictive）」**。 | https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/ |
| **Wasserstein / sliced-Wasserstein k-means** | 模型无关的分布聚类（厚尾视角） | 在最优传输距离下对收益分布做无模型聚类，能捕捉偏度/峰度/尾部。**注（降权）**：「优于矩 k-means 与高斯 HMM」**主要在合成数据（Merton 跳扩散等受控生成器）上成立，非真实市场 OOS 预测优越性**，应表述为「在合成跳扩散仿真中更好地还原已知聚类」（见 §7）。对加密厚尾有相关性，可作可选交叉检验。 | https://arxiv.org/abs/2310.01285 |
| **Markov / HMM regime-switching（Hamilton）** | 可解释基线 + filtered 概率监控 | statsmodels（MarkovRegression / MarkovAutoregression，暴露 filtered 与 smoothed 概率）、hmmlearn。高斯发射对厚尾失配；非齐次 HMM（Polya-Gamma / Bayesian-MCMC）被一篇**非同行评审预印本**称为「加密前沿」（**降权：单篇未评审，不可外推**，见 §7）。建议作基线 + filtered 概率监控器，不作唯一信号。 | https://www.statsmodels.org/stable/examples/notebooks/generated/markov_regression.html |
| **变点检测（PELT, BinSeg, BOCPD）** | 「结构何时断裂」视角 + 重训触发器 | PELT（Killick, Fearnhead & Eckley 2012）离线精确、近线性、BIC 惩罚；BOCPD（贝叶斯在线变点）做实时告警。可作 regime 引擎之外的**独立断裂确认与重训触发**。**注**：PELT 的正确出处是 JASA 2012（DOI 10.1080/01621459.2012.737745），原研究 JSON 给的 ACM DOI 是错链（见 §7）。 | https://doi.org/10.1080/01621459.2012.737745 |

## 3. 关键论文（每条带 URL）

- **Extending the Statistical Jump Model（Aydinhan, Kolm, Mulvey, Shu）**——特征工程蓝图：20/60/120 日半衰期的 EWMA 下行偏差 + EWMA 收益；jump penalty 强制持续性，sparse 选择。是 JM 家族的特征构造范本。（Annals of OR / SSRN 4556048）
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4556048

- **Downside Risk Reduction Using Regime-Switching Signals（Statistical Jump Model）**（*Journal of Asset Management* 2024 / arXiv 2402.05272v2）——S&P 500 区间研究。**【高严重度更正】原研究 JSON 引用的绩效数字（JM 0.78 Sharpe / -24.5% maxDD vs HMM 0.51 / -19.05% vs buy-hold 0.46 / -55.22%；「14 vs 115 次翻转」）系捏造/严重错配**：核实论文 Table 4 实为 **JM 0.68 / -26.6%、HMM 0.54 / -28.9%、buy-hold 0.48 / -55.2%**；原数字甚至把 HMM 的回撤说得比 JM 更好（-19.05% 优于 -24.5%），**反转了论文论点**（论文主张 JM 回撤控制更好：-26.6% 优于 HMM -28.9%）。「14 vs 115」累计翻转数论文中没有，Table 3 报的是「每年翻转率」（JM ~0.8/年 @λ=50 vs HMM ~2.0/年 @k=20）。**且论文 Figure 5 明确说模型「捕捉到了 2022 年由通胀与地缘政治驱动的下跌」并标为熊市 regime，原 JSON 称其「漏掉 2022」与原文直接矛盾**；「漏掉 1987 黑色星期一」也无依据（OOS 回测从 1990 年起，1987 根本不在测试窗内，属范畴错误而非已记录的失败）。**任何文案不得引用上述被捏造的数字与失败例。**
  https://arxiv.org/html/2402.05272v2

- **Clustering Market Regimes using the Wasserstein Distance（Horvath, Issa, Muguruza）**（arXiv 2110.11848）——WK-means 捕捉高阶矩/尾部，**在跳扩散合成数据上**优于矩 k-means 与高斯 HMM。模型无关，对加密厚尾相关。**降权：合成数据结论，非真实市场保证**（见 §7）。
  https://arxiv.org/pdf/2110.11848

- **Testing the Number of Regimes in Markov Regime-Switching Models**（arXiv 1801.06862；相关 1701.00029）——在「无切换」原假设下，第二 regime 参数不可识别、score 消失，经典渐近理论失效，针对 k 的 LR 检验无效。应改用识别稳健/矩检验或把 k 当治理决策。
  https://arxiv.org/pdf/1801.06862

- **Degeneracy in MLE of Gaussian mixtures with EM**（*Computational Statistics and Data Analysis*）——无约束协方差下似然无上界，EM 可把某分量塌缩到少数点。默认应加 inverse-Wishart / 对角加载 / 收缩 / 特征值约束 / 多起点。
  https://www.sciencedirect.com/science/article/abs/pii/S0167947310004147

- **Learning HMMs by Penalizing Jumps / Feature Selection in Jump Models（Nystrup et al.）**（Pattern Recognition / ESWA 2020-21）——按转移加惩罚得到比 Baum-Welch 更持续、更准确的状态；sparse 扩展做特征选择。是 JM 家族的根。
  https://github.com/Yizhan-Oliver-Shu/jump-models

- **How to predict financial stress? A Markov-switching assessment（ECB WP 2057）**——央行口径，关于宏观/风险 regime 模型在真实世界预测能力的局限与验证框架，对「描述性非预测性」立场提供机构级佐证。
  https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2057.en.pdf

## 4. 机构最佳实践 / 标准

- **模型风险管理（Fed SR 11-7 → SR 26-2）**：独立验证、文档化、持续监控、治理；用第三方/库不转移问责。SR 26-2（2026-04-17）取代 SR 11-7、风险比例化、保留同样支柱。**【medium 降权·治理框架误用】经核实 SR 26-2 真实存在并取代 SR 11-7 与 SR 21-8，但它明确把生成式 AI 与 agentic AI 排除在适用范围外（称其「新颖且快速演化」）**。本项目恰是带 LLM 因子生成的 Agent OS，把 SR 26-2 当 agentic/ML 部分的治理框架，正落在监管刻意划出的范围之外；且 SR 26-2 转向风险比例化判断、远离规定式清单，所以「强制式年检型 model card / 评估 harness」并非其要求。原 JSON 引二手 sia-partners 博客而非美联储原始通函，进一步放大问题。**结论：可借鉴「独立验证/监控/文档」的精神支柱，但不得宣称 SR 26-2「治理」本项目的 agentic 部分。**
  原始通函：https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm

- **NIST AI RMF（Govern / Map / Measure / Manage）+ Model Cards**：清单化（inventory）、每模型一张卡、评估 harness、运行时监控。对 regime 模型可对应到「k 选择理由 / 特征 / 假设 / 已知失败模式」的卡片字段。
  https://www.nist.gov/itl/ai-risk-management-framework

- **regime 作为描述性风险情景而非预测**：Two Sigma 明确把其 GMM regime 标注为「**不是预测模型**」，仅用于压力测试与战术倾斜。这是本环节最重要、也最被验证的姿态来源。
  https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/

- **Walk-forward 重训 + 前移状态（forward-shifted states）**：在当日收盘按当日状态行动、同时计入次日 P&L 以杜绝 look-ahead；并显式记录 OOS 衰减。
  https://developers.lseg.com/en/article-catalog/article/market-regime-detection

- **Whipsaw / turnover 控制**：非对称确认阈值、最小驻留时间（minimum dwell time）、低换手带、翻转后降仓位；成本/滑点建模为强制项——否则 regime 的毛 alpha 会被换手成本吞掉（见 §7）。
  https://arxiv.org/html/2402.05272v2

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **持续性优先引擎为主、HMM 为受治理基线**：默认把 Statistical Jump Model 这类持续性正则化方法作主 regime 仪器，把高斯/HMM 严格留作**可解释、受治理的基线（benchmark）而非上线信号**。把 jump-penalty λ 暴露为用户可懂的「你要 regime 多稳定」旋钮，按下游**风险调整效用**（而非原始似然）调——但务必把「按下游 Sharpe 调 λ」同时纳入多重检验/PBO 计数（见第 5 条、§8），不得在产品里宣传 JM「总是更优」或引用任何被捏造的 Sharpe/回撤数字（见 §7）。

2. **filtered/在线推断设为架构不变量**：时刻 t 的 regime 标签只能用截至 t 的信息，策略读取时再**前移一格（shift +1 bar）**。把 smoothed 概率**物理隔离**为「仅研究面」，上线引擎在结构上无法触碰，从而从构造上消除最常见的泄漏。**注**：smoothed 概率对「历史标注/研究」是合法可用的；「上线引擎不可触碰」是设计偏好而非定理（见 §7），文案不宜把它写成铁律。

3. **regime 输出在对话层定位为「风险情景」而非收益预测**：用于驱动仓位、杠杆上限、压力测试条件化、以及在不稳定转移期暂停/去险；拒绝把标签表述为方向性预测。契合资产无关中低频（尤其 Binance 实盘）目标，保护非技术用户。

4. **数值稳健护栏设为不可协商默认**：协方差收缩/对角加载、特征值/驻留约束、固定种子多起点、确定性 relabeling（解决 label switching）；把「regime 数 k」当**受治理决策 + 强制敏感性分析**，而非自动选的超参——因为此处经典选择检验（LR/AIC/BIC for k）在统计上无效（见 §7）。

5. **接入模型风险生命周期（去掉 SR 26-2 误用）**：自动生成一张「NIST-AI-RMF 风格 + SR 11-7『独立验证/监控/文档』精神」的 model card（假设、特征、k 选择理由、已知失败模式），跑强制 walk-forward OOS（含交易成本/whipsaw 核算），并上线监控（filtered 状态稳定性、PELT/BOCPD 告警、转移率与特征漂移检查）触发重训/告警。**关键修正**：不要把 SR 26-2 当作治理框架对外宣称——它把 agentic/生成式 AI 排除在范围外，本项目的 agentic 部分不在其规制内（见 §4、§7）；只借「独立验证/持续监控/文档化」的通用精神。同时把 λ、k、特征选择等所有调参纳入多重检验计数，喂给 deflated Sharpe / PBO。

6. **可选模型无关分布镜（Wasserstein/sliced-Wasserstein）作交叉检验**：尤其对厚尾加密。持续性引擎与分布镜**结论背离本身就是模型不确定性信号**，可据此加宽风险缓冲或升级到人工判断。**注**：分布镜的「优越性」是合成数据结论，对外只作交叉检验而非「更准」的卖点（见 §7）。

7. **保守诚实默认（非对称去险）**：regime 检测有滞后、主要帮回撤控制、在新型危机中可能失效，故默认姿态非对称——**检测到 risk-off 快速去险，回到 risk-on 则缓慢且确认门控**；对外口径是「本系统降低尾部损害」，而非承诺更高收益。

8. **强制接入便宜基线对照（缺口补全）**：把 regime 模型默认与「波动率目标（vol-target）」「200 日均线/趋势过滤」等便宜基线并排回测——JM/HMM 的多数「alpha」其实是回撤削减，而 vol-target / MA 过滤以更低复杂度、零 look-ahead 风险也能达到类似效果。不做此对照，整套 regime 装置的边际价值无法成立（见 §8）。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**filtered/在线推断 + 前移一格（架构不变量，杜绝 smoothed 泄漏）：**

```
# 上线面：只允许 filtered/online，禁止 smoothed/Viterbi
state_t = engine.filtered_state(data[: t])     # 仅用截至 t 的信息
action  = strategy.read(state_shifted = state_{t-1})  # shift +1 bar
# smoothed 概率物理隔离到「研究面」，上线引擎不可引用：
#   research_only.smoothed_proba = engine.smoothed(full_sample)   # 仅历史标注/科研
# 注：smoothed 对研究合法；"上线不可触碰" 是设计偏好而非定理
```

**持续性优先引擎（JM）+ 数值稳健护栏（默认不可关）：**

```
# 特征：多半衰期 EWMA 下行偏差 + EWMA 收益（资产日历驱动）
features = ewma_downside_dev(returns, halflives=[20,60,120]) + ewma_return(returns)
# jump penalty λ = "你要 regime 多稳定" 旋钮；按下游风险调整效用调
labels = jump_model.fit(features, jump_penalty=lambda_dial)
# HMM 基线（受治理 benchmark，非上线信号）须带稳健护栏：
hmm = GaussianHMM(cov="shrinkage|diagonal_loading", n_init=multi_start_seeds_fixed)
hmm = deterministic_relabel(hmm)              # 解决 label switching
# k(regime 数) = 受治理决策 + 强制敏感性分析（经典 LR/AIC/BIC for k 无效）
```

**regime = 风险情景 → 驱动护栏（非收益预测）+ 模型卡 schema 草图：**

```yaml
regime_card:                       # NIST-AI-RMF 风格 + SR 11-7 "独立验证/监控/文档" 精神
                                   # 注：不宣称受 SR 26-2 治理（其排除 agentic/生成式 AI）
  engine:
    primary: statistical_jump_model
    benchmark: gaussian_hmm        # 受治理基线，非上线信号
    distribution_lens: sliced_wasserstein   # 可选交叉检验（合成数据优越性，仅作背离信号）
  k_regimes:
    value: <governed>              # 受治理决策，非自动选
    sensitivity_analysis: required
    note: "经典 number-of-states 检验无效"
  inference_invariant:
    mode: filtered_online_only     # 上线面禁 smoothed/Viterbi
    forward_shift_bars: 1
    smoothed_surface: research_only
  lambda_tuning:                   # JM 持续性旋钮
    objective: downstream_risk_adjusted_utility
    counted_in_multiple_testing: true   # 纳入 PBO/DSR 计数（防超参 PBO）
  risk_context_use:                # 输出当风险情景，禁当方向预测
    drives: [position_sizing, leverage_cap, stress_conditioning, pause_derisk]
    posture: asymmetric            # 快去险 / 慢回险（确认门控）
  numerical_guards:
    covariance: shrinkage|diagonal_loading|eigenvalue_constraint
    multi_start: fixed_seed
    relabeling: deterministic
    dwell_min: <bars>              # 最小驻留 + 非对称确认阈值（抗 whipsaw）
  monitoring:
    live: [filtered_state_stability, pelt_bocpd_alarm, transition_rate, feature_drift]
    triggers: [refit, alert]
  oos_validation:
    walk_forward: required
    cost_model: required           # taker fee / funding / 滑点（缺口：需按 Binance 实际参数化）
    cheap_baselines: [vol_target, ma_200_filter]   # 强制对照，证明边际价值
  known_failure_modes:
    - detection_lag                # 多周至多月级（缺口：需量化）
    - fast_crash_miss
    - non_stationarity_relabel
    - gaussian_emission_fat_tail_misfit
# 注：所有数字（Sharpe/回撤/翻转）须重拉源表，禁用原 JSON 被捏造的数值
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（捏造/夸大/争议/二手/不可外推/单源/合成数据/范围误用/技术口误 等）**原样保留**；凡涉「已验证/直接证实/总是更优/已确证失败」的强确定性措辞均已按对抗核查降级。任何对用户的承诺或文案，必须采用降级后的表述。

- **【high · 捏造/错误数字】「JM 0.78 Sharpe / -24.5% maxDD vs HMM 0.51 / -19.05% vs buy-hold 0.46 / -55.22%；14 vs 115 次翻转」**——**捏造/严重错配**。核实论文（arXiv 2402.05272v2）Table 4 实为 **JM 0.68 / -26.6%、HMM 0.54 / -28.9%、buy-hold 0.48 / -55.2%**。原数字的 Sharpe 全不对，maxDD 严重偏离；且**内部不自洽**：它声称 HMM maxDD -19.05% 优于 JM -24.5%，**反转了论文整个论点**（论文主张 JM 回撤控制更好）。「14 vs 115」累计翻转数论文里没有，Table 3 是「每年翻转率」（JM ~0.8/年 @λ=50 vs HMM ~2.0/年 @k=20）。这些数字像是被捏造或从别处误抄。**文案绝对禁止引用这组数字。**
  https://arxiv.org/html/2402.05272v2

- **【high · 与原文矛盾】「JM 漏掉 1987 黑色星期一与 2022 下跌」/「misses fast crashes」举的具体失败例**——**被原文直接反驳**。论文 Figure 5 明确称模型**捕捉到了**「2022 年由通胀与地缘政治驱动的下跌」并标为熊市 regime；论文中没有「漏掉 2022」的说法。「漏掉 1987」也无依据——OOS 回测从 1990 年起，1987 根本不在测试窗内，属**范畴错误**而非已记录的失败。原 JSON 给出的唯一具体「失败例」不成立。**「检测滞后/可能漏快速崩盘」作为一般性陷阱仍成立，但不得用这两个被反驳的具体例子佐证。**

- **【medium · 夸大·合成数据结论】「Wasserstein / sliced-Wasserstein k-means 优于矩 k-means 与高斯 HMM、能标记已知危机」**——**夸大，系合成数据结论**。Horvath et al.（2110.11848）与 Luan-Hamp sliced-Wasserstein（2310.01285）的优越性**主要在合成数据（Merton 跳扩散、受控生成器）上演示，非真实市场 OOS 预测表现**——与「CPCV 仅在合成环境显著」同一类 caveat。「优于高斯 HMM」应降级为「在合成跳扩散仿真中更好地还原已知聚类」。原 JSON 自己的 summary 承认「figures 是单研究/二手」，却在 sota_systems 里把优越性当事实陈述。
  https://arxiv.org/abs/2310.01285

- **【medium · 治理框架范围误用】「自动生成 SR 11-7 / SR 26-2 model card 接入模型风险生命周期」与「SR 26-2 覆盖本用例」**——**范围误用**。核实 SR 26-2 真实存在（美联储，2026-04-17，取代 SR 11-7 与 SR 21-8），但它**明确把生成式 AI 与 agentic AI 排除在适用范围外**（称其「新颖且快速演化」）。本项目整体是带 LLM 因子生成的 Agent OS，把 SR 26-2 当 agentic/ML 部分的治理框架，正落在监管刻意划出的范围之外。该框架也**转向风险比例化判断、远离规定式清单**，故「强制式 model card / harness」并非 SR 26-2 所要求。引二手 sia-partners 博客而非美联储原始通函进一步放大问题。
  原始通函：https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm

- **【medium · 单篇未评审·不可外推】「非齐次 HMM（Polya-Gamma / Bayesian-MCMC）是加密前沿」**——**单篇非同行评审预印本的外推**。支撑 URL（preprints.org/manuscript/202603.0831）是**预印本服务器手稿、非同行评审刊物**（返回 403；preprints.org 非 peer-reviewed venue）。「加密前沿」是从一篇未评审论文外推。应降级为「一篇预印本提出的一个方向」。
  https://www.preprints.org/manuscript/202603.0831

- **【low · 研究代码当生产就绪】「jump-models (Shu) 是『最直接的防 look-ahead 引擎路径』/ 生产推荐」**——**研究代码被当生产就绪**。该 repo 真实（Apache-2.0），但仅 ~13 commits、无 tagged release，是 2024 论文的学术配套代码。称其「最直接的防 look-ahead 引擎路径」夸大成熟度；**look-ahead 安全是「你如何接 walk-forward 重训与前移」的属性，不是库本身保证的**。应作参考实现，而非可部署引擎。
  https://github.com/Yizhan-Oliver-Shu/jump-models

- **【low · 引用/URL 错配】PELT（Killick 2012）链到 dl.acm.org/doi/pdf/10.1145/3773365.3773532**——**引用/URL 错配**。PELT 归属 Killick, Fearnhead & Eckley (2012) **正确**，但正典论文是「Optimal Detection of Changepoints With a Linear Computational Cost」，**JASA 2012，DOI 10.1080/01621459.2012.737745**——**不是**所引的 ACM DOI（10.1145/3773365.3773532，为无关/二手文档）。承重的主引用指向错误来源。
  https://doi.org/10.1080/01621459.2012.737745

- **【low · 过强确定性】「SMOOTHED-PROBABILITY LEAKAGE（#1 killer）」「only filtered/online inference is admissible」当成普适铁律**——**大体正确但被过度排名/绝对化**。泄漏点真实且众所周知。但称其「#1 killer」是单作者编辑性排名、非既定共识；实务中 whipsaw/交易成本侵蚀与 number-of-states 过拟合至少同等致命。且 smoothed 概率对**研究/历史标注**是合法可用的；「上线引擎不可触碰」的绝对化是**设计偏好而非定理**。属对确定性的轻微过度宣称。

**通用陷阱清单（工程红线）：**

- **SMOOTHED 概率泄漏**：smoothed/Viterbi 标签用了全样本（含未来），会膨胀回测；上线只可用 filtered/在线推断，并对状态前移一格。（点真实，但「#1 killer」排名是单作者编辑性观点，非共识——见上）
- **number-of-states 不是普通检验**：无切换原假设下额外 regime 参数不可识别、score 消失，针对 k 的 LR/AIC/BIC **经典上无效**；过参数化会**发明伪 regime**。把 k 当受治理量 + 敏感性分析或用持续性惩罚聚类。
- **EM 退化 / 协方差奇异**：无约束 GMM/HMM 似然无上界，分量可塌缩到少数点；用收缩/对角加载/inverse-Wishart/特征值约束 + 确定性 relabeling（解决 label switching）。
- **whipsaw + 交易成本**：原始 HMM 状态频繁翻转（论文 ~2.0/年 vs JM ~0.8/年）；无持续性惩罚/确认阈值/驻留时间/成本滑点建模，毛 regime alpha 会蒸发，紧密切换常跑输买入持有。
- **描述性非预测性**：识别当前 regime 远易于预测下一状态及其时点；样本内易、样本外难，常只匹配买入持有 Sharpe，漏快速崩盘，**检测天然滞后**。（**注**：原 JSON「漏 2022」的具体例子被论文反驳，见上；一般性滞后成立但缺幅度量化，见 §8）
- **regime 非平稳**：含义会漂移，pre-2008/pre-COVID 拟合会在后期被 relabel；需周期性重训、状态稳定性监控、边界处人工判断。
- **高斯发射误设**：默认高斯 HMM 欠拟合偏度/峰度/跳跃（加密尤甚）；用厚尾/混合发射或分布聚类，或仅把高斯 HMM 当基线。
- **无干净 ground truth**：真实 regime 不可观测，验证不能用监督式准确率；改用下游经济效用（风险调整收益、净成本回撤）、持续性/稳定性、危机召回率评估，并防回测过拟合/PBO。
- **λ 调参的 PBO（缺口，见 §8）**：JM 的 λ「按下游 Sharpe 用时序 CV 调」= 在绩效指标上做超参搜索，正是 deflated-Sharpe / PBO 陷阱；原 JSON 仅泛泛提一次 PBO，从未连到自己的头号推荐。
- **输入特征的 vintage 泄漏（缺口）**：宏观/因子输入（Two Sigma 17 因子）会被修订/滞后发布；若特征被回填或修订，「filtered、信息截至 t」的不变量在**输入层**就被违反——泄漏讨论只覆盖了 smoothed-vs-filtered 标签，未覆盖输入 vintage 泄漏。

## 8. 开放问题

- **检测滞后的幅度未量化**：反复说「天然滞后」却从不给数量级（JM 的持续性惩罚 + 半年重训意味着 regime 进入有多周至多月级滞后）。对中低频 Binance 实盘目标，**这个滞后是最有决策价值的数字，却被省略**——需实测量化。
- **A股适用性完全缺位**：所引研究全是美/德/日股或加密。本项目范围含 A股（T+1、10%/20% 涨跌停、频繁停牌/重大事项停牌、强政策驱动 regime）。**涨跌停与停牌截断收益分布，破坏高斯发射与最优传输距离假设**，所引方法均未处理，也无迁移证据。
- **λ（jump-penalty）调参的多重检验/PBO 核算缺失**：λ 按下游 Sharpe 调即在绩效指标上做超参搜索，膨胀 OOS Sharpe；需把 λ/k/特征选择全部纳入 deflated Sharpe / PBO 计数（呼应簇 C 第 15 环节）。
- **加密的 regime 数 k 无依据**：Two Sigma 用 4 个 regime 是宏观股票口径；24/7 加密的微结构 regime（资金费率/流动性/杠杆级联）与股票宏观 regime 结构不同。既然 k 选择检验无效，对实际目标资产类却完全不指定 k，是缺口。
- **未与便宜基线做经济显著性对照**：JM/HMM 多数「alpha」是回撤削减，而 vol-target / 200 日 MA 过滤以更低复杂度、零 look-ahead 也能达到类似效果；不与这些便宜基线对照，整套 regime 装置的**边际价值未确立**。
- **宏观特征的 point-in-time / data-vintage 泄漏**：宏观/因子输入被修订、滞后发布，「信息截至 t」的不变量若输入被回填即被破坏；泄漏护栏需扩展到输入层，而不仅是 smoothed-vs-filtered 标签层。
- **成本模型只断言未参数化**：「成本/滑点建模强制」只是口号，Binance 实盘相关数字（taker 费、funding、本项目规模下的滑点）及 regime 翻转换手如何与之交互均缺——而这正是 JM 论文显示毛 alpha 蒸发的地方。

## 9. 参考文献（URL）

- Statistical Jump Model · Downside Risk Reduction（arXiv 2402.05272v2，*J. Asset Management* 2024）【数字须以 Table 4 为准，原 JSON 数字被捏造】：https://arxiv.org/html/2402.05272v2
- Extending the Statistical Jump Model（Aydinhan, Kolm, Mulvey, Shu，SSRN 4556048）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4556048
- Clustering Market Regimes using the Wasserstein Distance（Horvath, Issa, Muguruza，arXiv 2110.11848）【合成数据结论，不可外推】：https://arxiv.org/pdf/2110.11848
- Sliced-Wasserstein regime clustering（Luan-Hamp，arXiv 2310.01285）【合成数据结论】：https://arxiv.org/abs/2310.01285
- Testing the Number of Regimes in Markov Regime-Switching Models（arXiv 1801.06862）：https://arxiv.org/pdf/1801.06862
- Degeneracy in MLE of Gaussian mixtures with EM（*Comp. Statistics and Data Analysis*）：https://www.sciencedirect.com/science/article/abs/pii/S0167947310004147
- Learning HMMs by Penalizing Jumps / jump-models 实现（Shu，Apache-2.0，研究代码）：https://github.com/Yizhan-Oliver-Shu/jump-models
- How to predict financial stress?（ECB WP 2057）：https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2057.en.pdf
- PELT 正典论文（Killick, Fearnhead & Eckley 2012, JASA，DOI 10.1080/01621459.2012.737745）【原 JSON 的 ACM DOI 为错链】：https://doi.org/10.1080/01621459.2012.737745
- Two Sigma · A Machine Learning Approach to Regime Modeling（明确「非预测」）：https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/
- 非齐次 HMM 加密预印本（preprints.org，**非同行评审，返回 403**，不可外推）：https://www.preprints.org/manuscript/202603.0831
- Fed SR 26-2 原始通函（取代 SR 11-7；**排除生成式/agentic AI**）：https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm
- Fed SR 11-7（模型风险管理）：https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- NIST AI RMF 1.0：https://www.nist.gov/itl/ai-risk-management-framework
- LSEG · Market Regime Detection（walk-forward + 前移状态）：https://developers.lseg.com/en/article-catalog/article/market-regime-detection
- statsmodels MarkovRegression（filtered 与 smoothed 概率）：https://www.statsmodels.org/stable/examples/notebooks/generated/markov_regression.html
- hmmlearn（高斯/多项 HMM，注意协方差正则/多起点/label switching）：https://github.com/hmmlearn/hmmlearn
- ruptures（离线变点：PELT/BinSeg/DynP/kernel/window）：https://github.com/deepcharles/ruptures
- pomegranate（PyTorch HMM/GMM，厚尾混合发射，GPU）：https://github.com/jmschrei/pomegranate
- CLUSTERING-MARKET-REGIMES（Horvath WK-means 在 SPY + 合成跳扩散的开源复现）：https://github.com/mirkovicdev/CLUSTERING-MARKET-REGIMES
