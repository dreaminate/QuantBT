# 31 · 组合优化 / 配置官（HRP/NCO/ERC/Ledoit-Wolf）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 F

## 1. 一句话定位

「配置官」的核心张力是：**Markowitz 均值-方差（MVO）理论上最优，实务上却中了"Markowitz 诅咒"**——协方差矩阵病态（condition number = λmax/λmin 极高、最小特征值近零）叠加期望收益估计误差，被矩阵求逆放大成对输入微扰高度敏感、极不稳定的权重。**这个簇里的所有方法本质都是"在不同维度上对抗估计误差与病态求逆"的工程手段，而非互相替代的"乐器"**：(1) **Ledoit-Wolf 收缩 / RMT 去噪**修协方差矩阵本身（把噪声特征值压平、降 condition number），是几乎所有下游优化器都该先做的一步；(2) **真 ERC（风险平价）**放弃期望收益、用凸优化让每个资产风险贡献相等——**注意 ∝1/σ 的 inverse-vol 只是相关性=1 时的退化特例，二者不可混为一谈**；(3) **HRP** 用层次聚类把相关结构做成树、递归二分配权，完全绕开矩阵求逆，对奇异/病态矩阵鲁棒；(4) **NCO** 在去噪后的相关矩阵上聚类、簇内簇间分别做小规模优化，把一个大病态问题拆成若干良态子问题。**最致命的诚实点**：HRP 的"超额表现"很大程度只相对 CLA/MVO 而言；独立研究（2025 FGCS、加密 BTC-hold 反例）显示它在样本外/含成本/无真实层次结构时**并不稳定优于 1/N 或 inverse-vol**——这与 DeMiguel-Garlappi-Uppal 的"1/N 难以击败"一脉相承。结论：**对一个面向不懂代码经济学者的 Agent OS，不应让用户"挑优化器"，而应默认一条防御性管线（去噪/收缩 → 真 ERC 或 HRP 作鲁棒基线 → 永远并排展示 1/N 与 inverse-vol → condition number/特征值/换手率/集中度体检卡），把"为何这样配"翻译成经济语言，并把模型风险治理做进流程本身。可信度不取决于选了哪个花哨优化器，而取决于估计-去噪-约束-成本-再平衡全链路的可复现性与诊断透明。**

---

## 2. 前沿 SOTA 与代表系统

| 系统 / 库 | 它是什么 · 对本环节意味着什么 | URL |
|---|---|---|
| **Riskfolio-Lib** | 功能最广的开源组合优化库（cvxpy + pandas 后端）。同时覆盖经典 MVO、Black-Litterman、真风险平价/ERC、层次聚类组合（HRP/HERC）、NCO，以及 13+ 风险度量（CVaR/EVaR/CDaR 等）与多种 Ledoit-Wolf/去噪协方差估计器。**算法覆盖最全**，是"配置官"算法后端的首选候选。 | https://riskfolio-lib.readthedocs.io/en/latest/hcportfolio.html |
| **skfolio** | scikit-learn 风格的组合优化库，API 一致、内建交叉验证/嵌套 CV 与压力测试。**NCO 实现严格用 k 折 CV 训练 outer-estimator 防止簇间权重的数据泄露**——对一个强调"无泄露、可验证"的 Agent OS 是重要参考范式；也内建 HRP/HERC、真 ERC（风险预算）、Ledoit-Wolf/去噪估计器。 | https://skfolio.org/ |
| **PyPortfolioOpt** | 最易上手的库，实现经典有效前沿、Black-Litterman、收缩（含 Ledoit-Wolf）与 HRP。文档清晰，适合作为"解释给小白"的概念脚手架，但风险度量与鲁棒优化覆盖窄于 Riskfolio/skfolio。 | https://github.com/robertmartin8/PyPortfolioOpt |
| **riskparityportfolio**（Vinicius & Palomar 组） | 专注真风险平价/风险预算的高性能求解器（Spinu/Newton 类凸方法），用于**精确求解 ERC 而非 inverse-vol 近似**；是做"真 ERC vs ∝1/σ"权威对照的实现。 | https://pypi.org/project/riskparityportfolio/ |
| **Machine-Learning-for-Asset-Managers**（López de Prado 配套代码社区复现） | 作者本人书中的 RMT 去噪（拟合 Marcenko-Pastur 分离噪声/信号特征值）、detoning（剔除市场主成分）与 NCO 参考实现，是该簇方法的"原始乐谱"。 | https://github.com/emoen/Machine-Learning-for-Asset-Managers |

> ⚠️ **核查降权（LOW）**：研究稿原把 PyPortfolioOpt 的 URL 填为 `github.com/PyPortfolio/PyPortfolioOpt`（旧/派生 org 路径，非规范）。上表已更正为权威仓库 `github.com/robertmartin8/PyPortfolioOpt`（作者 Robert Andrew Martin，当前 v1.5.x）。库本身真实有效，仅引用路径需修正。

---

## 3. 关键论文（每条带 URL）

1. **Building Diversified Portfolios that Outperform Out-of-Sample（HRP 原始论文）**
   López de Prado (2016), Journal of Portfolio Management 42(4):59-69。提出 HRP 三步（层次聚类 → 准对角化 → 递归二分），完全绕开协方差求逆；Monte Carlo 显示 HRP 样本外方差低于 CLA（尽管 CLA 才是显式最小方差）。
   ⚠️ **核查降权**：此处 "outperform" **主要相对 CLA/MVO，而非相对朴素基线**（1/N、inverse-vol）——这正是后续争议的源头，引用时不可省略基准。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678

2. **A Robust Estimator of the Efficient Frontier（NCO）**
   López de Prado (2019), SSRN 3469961。形式化"Markowitz 诅咒"：不稳定来自 (i) 输入噪声、(ii) 放大估计误差的信号结构。方案=先 RMT 去噪降"噪声不稳定"，再在去噪相关矩阵上聚类、分簇内/簇间两层小规模优化（NCO）以降"信号不稳定"，等价于把大病态问题拆成多个良态子问题。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3469961

3. **The Properties of Equally-Weighted Risk Contribution Portfolios（真 ERC）**
   Maillard, Roncalli & Teiletche (2010), JPM 36(4):60-70。给出 ERC 的严格定义与凸优化求解（各资产对总风险贡献相等）。关键：ERC 一般介于最小方差与等权之间；**只有当所有相关性相等时 ERC 才退化为 inverse-vol（∝1/σ）**。证明了为何不能把 inverse-vol 当作"风险平价"。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1271972

4. **Optimal versus Naive Diversification: How Inefficient is the 1/N Portfolio Strategy?**
   DeMiguel, Garlappi & Uppal (2009), Review of Financial Studies 22(5):1915-1953。14 个"最优"模型在 7 个数据集上，**无一在 Sharpe/确定性等价/换手率上稳定击败 1/N**；校准美股需约 3000（25 资产）/6000（50 资产）个月样本才能让样本 MVO 击败 1/N。是所有"配置官必须把 1/N 当强基线"的实证基石。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1376199

5. **Analytical Nonlinear Shrinkage of Large-Dimensional Covariance Matrices / The Power of (Non-)Linear Shrinking**
   Ledoit & Wolf (2020), Annals of Statistics；及综述 SSRN 3384500。给出非线性收缩的解析公式（经 Hilbert 变换把相邻特征值"就地"拉拢），相对线性收缩可再提升最小方差组合表现；综述系统对比线性 vs 非线性。是协方差估计 SOTA 的权威落点。
   ⚠️ **核查降权**：见下方 §7 与论文 8 的 Bongiorno-Challet 反驳——**不要默认"非线性收缩=最佳协方差估计"**，证据冲突。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3384500

6. **Hierarchical Risk Parity: Accounting for Tail Dependencies in Multi-asset Multi-factor Allocations**
   Lohre, Rother & Schäfer (2020), in Machine Learning and Asset Management, Wiley。把 HRP 的距离度量从 Pearson 相关扩展到下尾相关系数（lower tail dependence），对偏态风格因子的下行风险管理更好——**但代价是换手率显著升高**（对中低频+交易成本敏感的本产品是关键权衡）。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3513399

7. **Hierarchical Risk Parity: Efficient Implementation and Real-World Analysis**
   Future Generation Computer Systems 167 (2025) 107744。独立实证：**在其所有实验设定下，朴素 1/N 在样本外风险调整收益上优于 HRP**。是对 HRP "样本外占优"叙事最直接的近期反例之一。
   https://www.sciencedirect.com/science/article/abs/pii/S0167739X25000391

8. **Non-linear Shrinkage of the Price Return Covariance Matrix is Far from Optimal for Portfolio Optimization**
   Bongiorno & Challet。直接质疑 Ledoit-Wolf 非线性收缩在组合优化中的最优性，主张相对组合优化目标它"远非最优"（因 **Frobenius 范数最优 ≠ 组合方差最优**，且依赖资产相关结构的非平稳性）。与"非线性优于线性"叙事冲突，证据混杂。
   ⚠️ **核查降权（LOW）**：研究稿标作 "Finance Research Letters (2022)" 略不精确——**实为 arXiv 预印本 2021-12（2112.07521），正式发表于 Finance Research Letters vol 52, 2023**。实质论断（NLS 对组合优化非最优）成立，仅年份标注需更正。
   https://arxiv.org/abs/2112.07521

9. **Implementation Risk in Portfolio Backtesting: A Previously Unquantified Source of Error**
   Yin, Miki, Lesnichenko & Gural (2026), arXiv:2603.20319。同一策略跨 5 个回测引擎，零成本时完全一致，但含成本（尤其高换手）时出现可测量分歧，根因=交易成本模型实现差异。建议把 SR 11-7 模型验证扩展到回测引擎本身（Engine Spread / Conclusion Sensitivity 指标）。
   ⚠️ **核查降权（MEDIUM，详见 §7）**：研究稿原写的"分歧达 2.1-3.7%（约每 10 亿美元 AUM 年化 3700 万美元歧义）/ 对'流程即信任'最致命"被**显著夸大**。论文实际结论是"**多数策略分歧 < 0.75 个百分点，仅高换手轮动策略达 3.71%**"——"2.1%" 下界查无实据，"2-4%" 是被构造的区间，把尾部极值伪装成典型值；"$37M/十亿AUM" 数字论文中不存在；且论文自陈 **conclusion stability index = 1（所有引擎在每个指标符号上一致，"implementation risk 不改变投资决策"）**，与"最致命/流程即信任会破功"直接矛盾。该文系**未经同行评审的预印本**（投稿 Financial Innovation 未录用），仅在 180 只标普 500 股票上测试，**外推到加密/实盘属过度外推**。
   https://arxiv.org/abs/2603.20319

10. **Beyond Risk Parity — ML-based HRP on Cryptocurrencies**
    Burggraf (2021), Finance Research Letters（vol 38, art 101523）。在加密大盘上 HRP 在尾部风险调整收益上优于传统风险最小化方法。
    ⚠️ **核查降权（LOW）**：论文本身核实无误，但其对照组是"**传统风险最小化方法（MVO 类）**"，**并非 1/N 或 BTC-hold**——所以它既不能证明也不能证伪"HRP 优于朴素基线"。引用时必须明确其基准，否则会被误以为与下文 BTC-hold 反例处于同一对照框架。
    https://www.sciencedirect.com/science/article/abs/pii/S154461232030177X

---

## 4. 机构最佳实践 / 标准

- **模型风险治理三支柱**：概念健全性（conceptual soundness）+ 独立验证（开发-验证职责分离）+ 持续监控 + 至少年度复审与已知局限登记。组合优化模型属"用于实质性决策的量化模型"，应纳入模型清单并留存验证报告。对 Agent OS：可把"配置官"每次产出当作一次受治理的模型运行，自动生成验证卡。
  来源：Federal Reserve / OCC SR 11-7 Model Risk Management — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **把 SR 11-7 的模型验证显式扩展到"回测/模拟引擎本身"**：用 Engine Spread 与 Conclusion Sensitivity Indicator 作为验收指标，要求至少两个架构不同（事件驱动 + 向量化）的独立验证器交叉核对，并对每个引擎的交易成本模型做对照审计。
  来源：Implementation Risk in Portfolio Backtesting (2026) — https://arxiv.org/abs/2603.20319
  ⚠️ **核查降权**：该来源系**未评审预印本、仅测股票**，其量级数字被夸大（见 §3 论文 9 / §7）。"双引擎交叉核对"这一**方法论建议**仍站得住——但应剥掉被构造的 2-4%/$37M 数字，作为"可复现性诊断"而非"已量化的致命风险"呈现。

- **协方差估计的事实标准流水线**：先做 Ledoit-Wolf 收缩或 RMT（Marcenko-Pastur）去噪/detoning 压平噪声特征值、降低 condition number，再喂给任何需要求逆的优化器；并把 condition number / 最小特征值作为"矩阵是否可信"的体检指标（condition-number-regularized estimation 是成熟做法）。
  来源：Ledoit-Wolf 2004/2020；MOSEK Portfolio Optimization Cookbook（估计误差章）— https://docs.mosek.com/portfolio-cookbook/estimationerror.html

- **风险平价/ERC 行业实践明确区分三档**：朴素 inverse-vol（naive，隐含相关性=1）、真 ERC（凸优化，Spinu/Newton 求解，纳入相关性）、最大分散化；并强调真 ERC 需控制换手与对协方差估计的敏感性。机构白皮书普遍把 ERC 视为"稳健但需稳健协方差"的方法。
  来源：S&P DJI "Indexing Risk Parity Strategies"；ReSolve "Risk Parity: Methods and Measures of Success" — https://www.spglobal.com/spdji/en/documents/research/research-indexing-risk-parity-strategies.pdf

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅概念级方向，不点 file:line、不排实施计划。

1. **把"配置官"定位成一条防御性管线，而非"优化器选择题"。**
   默认顺序：协方差估计 → 去噪/收缩（Ledoit-Wolf 或 RMT，先压平噪声特征值）→ 在去噪相关矩阵上做鲁棒配置（**HRP 或真 ERC 作默认基线，而非 MVO**）→ 约束与成本 → 再平衡。用户出经济意图，agent 出全链路；**不要让不懂代码的经济学者去挑 HRP/NCO/ERC**——这是工程决策，应由 agent 依据数据规模/相关结构/换手预算自动选择并解释。

2. **永远把 1/N 和 inverse-vol 作为"诚实基线"与任何高级配置并排展示。**
   鉴于 DeMiguel 2009、2025 FGCS HRP 实证、加密上 BTC-hold 反例，产品的可信度来自"我们没有夸大"——**若高级方法在该用户的样本外/含成本检验中不优于 1/N，流程必须如实告诉用户并默认回退**，而不是为复杂而复杂。

3. **明确区分"真 ERC"与"∝1/σ"，并在 UI/解释层强制澄清。**
   inverse-vol 只是相关性=1 的特例。给经济学者的语言应是"**真风险平价考虑了资产间相关性（债券作为分散器会拿到更高权重），inverse-vol 忽略相关性**"——避免把伪风险平价当成风险平价交付。

4. **把协方差矩阵体检卡做成一等公民诊断。**
   condition number（λmax/λmin）、最小特征值、去噪前后特征值谱、有效自由度/估计窗口是否足够（N 与样本长度比）、矩阵是否接近奇异。**当 condition number 过高或样本不足，agent 应主动降级到 HRP/ERC/1/N 并解释"此处 MVO 不可信"**，把数学病态翻译成经济语言。
   ⚠️ 见 §8 开放问题：研究稿**没给出何时触发降级的可操作阈值**——没有阈值的体检卡对不懂代码的经济学者等于没有；落地前必须为加密与 A股分别定 N/样本比的降级判据。

5. **把"实现风险/可复现性"写进信任契约。**
   "配置官"的输出必须绑定：确切的协方差估计器 + 去噪参数 + 求解器 + 约束 + 交易成本模型 + 再平衡规则 + 随机种子，并支持双引擎（事件驱动 + 向量化）交叉核对。**中低频场景下换手率与成本是头等约束**——HRP 尾部扩展、NCO、真 ERC 都可能高换手，需在配置目标里显式惩罚。
   ⚠️ 见 §7：跨引擎分歧的量级被夸大且不改变决策符号——这一方向的价值是**可复现性/归因透明**，不是"防止 2-4% 致命误差"。

6. **用 SR 11-7 式治理包裹每次配置作为产品骨架，而非附加文档。**
   概念健全性说明（为何选此法、假设与已知局限）、样本外验证（walk-forward、无泄露，**复用项目 v3 的 OOS 框架**）、持续监控（权重漂移、condition number 漂移、相对基线表现衰减触发复审）。这正是"流程即信任"的可落地形态。
   ⚠️ 见 §8：SR 11-7 本是面向受监管银行的；把这套治理移植到**单用户、非受监管个人产品**有过度合规之险，应评估其边际价值与维护成本，对 paper 实验保持轻量。

7. **对协方差估计保持方法多元化，而非押注单一"最优"。**
   证据冲突（非线性收缩有论文称 far from optimal；有数据集线性优于非线性），因此应**内建多估计器（样本/线性收缩/非线性收缩/RMT 去噪/单因子目标）并按用户数据用嵌套 CV 自动择优 + 展示稳健性区间**，而不是硬编码一个估计器当真理。
   ⚠️ 见 §8：金融时间序列上**朴素 k 折 CV 本身有前视/泄露争议**，自动择优应配合 purging+embargo 的 CPCV/walk-forward，而非朴素 k 折。

8. **为 A股 vs 加密分别设默认。资产无关的是"管线与治理"，不是"同一组参数"。**
   加密（到 Binance 实盘）相关结构常被单一市场因子主导（detoning 价值高）、尾部厚、BTC 主导，HRP/ERC 优势不稳健，应强化尾部度量（CVaR/下尾相关）与对"集中于 BTC"的诚实对照；A股（到 paper）更适合先验证去噪 + 约束的稳健配置。
   ⚠️ 见 §8：**加密上机械 detoning 会剔除 BTC 这个事实上的市场 beta，而 BTC beta 恰是该资产类近年最大收益来源**——"去噪 vs 去掉真信号"的权衡须点明；A股侧的 T+1/涨跌停/停牌对协方差估计的硬约束研究稿回避了。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意草图，不接线到现有代码。

**6.1 防御性配置管线（概念顺序，非优化器选择题）**

```
意图(用户)  →  协方差估计(多估计器候选)
            →  去噪/收缩  (Ledoit-Wolf | 非线性收缩 | RMT/Marcenko-Pastur | 单因子目标)
            →  体检卡     (condition_number, λ_min, 谱图, N/样本比)  ──┐
            →  鲁棒配置   (默认: 真ERC 或 HRP; MVO 仅在体检通过时启用)   │ 体检不过
            →  约束+成本  (换手惩罚, 仓位上限, A股: T+1/涨跌停/停牌掩码)  │   ↓
            →  再平衡规则 (频率 = 受治理超参, 纳入无泄露 walk-forward)   └→ 降级 1/N|inverse-vol
            →  永远并排展示: {该方法, 1/N, inverse-vol, 真ERC}  + 诚实对照
```

**6.2 协方差体检卡 schema（一等诊断对象）**

```yaml
covariance_healthcard:
  estimator: sample | lw_linear | lw_nonlinear | rmt_denoise | single_factor
  condition_number: float        # λmax / λmin
  min_eigenvalue: float          # 近零 → 接近奇异
  n_assets: int
  sample_length: int             # 与 ½N(N+1) 比较: 不足则不可求逆
  n_over_T_ratio: float          # N/样本长度; 过高触发降级
  spectrum_before / after: [..]  # 去噪前后特征值谱
  detoning_applied: bool         # ⚠️ 加密: detoning 会削掉 BTC beta (真信号)
  verdict: mvo_trustworthy | degrade_to_hrp_erc | degrade_to_1overN
  # ⚠️ 见§8: 降级阈值须按 A股(样本短/停牌) vs 加密(长样本但非平稳) 分别校准
```

**6.3 真 ERC vs inverse-vol 强制澄清（概念，给经济学者的对照）**

```python
def allocator_explain(weights_true_erc, weights_inverse_vol, corr):
    # inverse-vol 只是 corr ≡ 1 的退化特例; 二者不可混为"风险平价"
    if corr_is_near_identity(corr):
        note = "本宇宙资产近不相关 → 真ERC ≈ inverse-vol (退化特例)"
    else:
        note = ("真风险平价考虑了相关性: 分散器(如债券)拿到更高权重; "
                "inverse-vol 忽略相关性, 在相关资产上会系统性误配")
    return Explanation(true_erc=weights_true_erc,
                       inverse_vol=weights_inverse_vol,  # 标注"近似, 非ERC"
                       economic_note=note)
```

**6.4 配置产出的可复现绑定 + 诚实对照（概念伪代码）**

```python
def allocate(intent, universe, asset_class):
    cov   = estimate_cov_multi(universe)          # 多估计器候选
    cov   = denoise_or_shrink(cov, pick="nested_cv")  # ⚠️ 须 purge+embargo, 非朴素k折
    card  = healthcheck(cov)                      # §6.2 体检卡
    method = auto_select(card, asset_class)       # 体检/相关结构/换手预算驱动, 非用户挑
    w     = robust_allocate(cov, method)          # 默认 真ERC|HRP; MVO 仅体检通过
    base  = {"1/N": equal_weight(universe),
             "inverse_vol": inv_vol(universe)}    # 永远并排
    return Allocation(
        weights=w, baselines=base, healthcard=card,
        repro_lock={                              # 可复现契约
            "estimator": cov.estimator, "denoise_params": ...,
            "solver": ..., "constraints": ...,
            "cost_model": ..., "rebalance_rule": ..., "seed": ...,
        },
        # ⚠️ 若 w 在 OOS/含成本下不优于 base → 流程默认回退并如实告知 (诚实第一)
        dual_engine_check="event_driven + vectorized",  # 归因透明, 非"防致命误差"
    )
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 对抗核查总判：**总体可信、且罕见地诚实**——核心智识价值（MVO 诅咒、HRP "超额"只相对 CLA/MVO 而非朴素基线、真 ERC ≠ inverse-vol、1/N 是硬基线、非线性收缩有争议、Wikipedia HRP 页带 COI 声明）经独立核实**全部成立**，且研究稿在正文中已主动预先认领了大部分潜在夸大。关键算法机制、condition number 数学、DeMiguel 2009、Maillard-Roncalli-Teiletche 2010、Ledoit-Wolf 2020、SR 11-7、HRP 原始论文、2025 FGCS（1/N 全设定胜 HRP）、Bongiorno-Challet "far from optimal" 均**核实无误，无撤稿/造假**。需要扣分的主要是若干**被包装的数字**与**来源等级**。设计方向（防御性管线、永远并排 1/N、强制区分真 ERC/inverse-vol、协方差体检卡、锁定成本模型 + 双引擎、SR 11-7 治理）本身稳健且与已验证证据一致。

**MEDIUM 严重度**

- ⚠️【数字夸大 + 关键反向证据被省略 + 不可外推】**implementation risk "2.1-3.7% / 2-4% 分歧、$37M/十亿AUM、对'流程即信任'最致命"**。三处问题：(1) **区间被夸大**——论文实际结论是"对多数策略分歧 **< 0.75 个百分点**，仅高换手轮动策略达 **3.71%**"；"2.1%" 下界在 arXiv abstract 与两次独立检索中均查不到，"2-4%" 是**被构造的区间，把一个尾部极端值伪装成典型值**。(2) **"$37M/十亿AUM" 在论文中不存在**（WebFetch 确认），是二次加工的衍生数字。(3) **最关键的反向证据被省略**：论文自陈 **conclusion stability index = 1**，即所有引擎在每个指标符号上一致，"**implementation risk 不改变投资决策**"，只在业绩归因上引入可测量的模糊——这与"最致命/流程即信任会破功"的渲染**直接矛盾**。且该文是**未经同行评审的预印本**（投稿 Financial Innovation，未录用），仅在 180 只标普 500 股票、向量化/事件驱动开源引擎上测试，**外推到加密/实盘成本属过度外推**。（已在 §3 论文 9 与 §4 就地降权。）

- ⚠️【二手数字 + 来源降级 + 方向自相矛盾 + 窗口依赖】**"近期（2022-2025）40 币种实测显示单押 BTC 常击败各 HRP 变体，即便不含交易成本；加密场景 HRP 优势高度不稳健"**。该论断的可定位来源是一篇**个人博客**（alexeygolev.blog，2022-06~2025-06 窗口）的回测，**而非"实测"级研究**；"40 币种"的精确措辞无法在任何同行评审文献中证实。更严重的是**方向性矛盾**：博客原文说 BTC Hold 是 "**once transaction costs are considered**"（计入交易成本后）才胜出，而研究稿写成"**即便不含交易成本**"——把"含成本才输"反写成"不含成本也输"，放大了对 HRP 的不利结论。directionally BTC 在该窗口确实跑赢，但把单一博主的择时窗口回测**包装成"实测/高度不稳健的普遍结论"属外推过度且窗口依赖**（2022-2025 正是 BTC 单边主导期）。（已在 §3 论文 10 标注基准框架。）

**LOW 严重度**

- ⚠️【先扬后抑的叙事张力，基准不对齐】**Burggraf 2021 与未证实的 "BTC-hold 击败 HRP" 并置**。Burggraf 论文核实无误（FRL vol 38, art 101523），但研究稿把它与未证实的 BTC-hold 反例并置叙事时，制造了"先扬后抑"的张力来支撑"HRP 不稳健"的预设结论。诚实地说，Burggraf 的对照组是"**传统风险最小化方法（MVO 类）**"，**并非 1/N 或 BTC-hold**——所以它既不能证明也不能证伪"HRP 优于朴素基线"；引用时应明确其基准，否则读者会误以为它与 BTC-hold 反例处于同一对照框架。

- ⚠️【URL 非规范】**PyPortfolioOpt 仓库 URL** 研究稿填 `github.com/PyPortfolio/PyPortfolioOpt`（旧/派生 org 路径）。权威仓库为 `github.com/robertmartin8/PyPortfolioOpt`（作者 Robert Andrew Martin，当前 v1.5.x）。**不影响库本身的真实性与适用性判断**，仅作为可追溯引用的瑕疵——已在 §2 更正。

- ⚠️【年份标注不精确】**Ledoit-Wolf 非线性收缩 "far from optimal" 论文（Bongiorno & Challet）** 实质论断正确（NLS 对组合优化非最优，因 Frobenius 最优 ≠ 组合方差最优，且依赖资产相关结构的非平稳性），但研究稿标作纯 "2022" 略有出入——**arXiv 预印本 2021-12（2112.07521），正式发表于 Finance Research Letters vol 52，2023 年**。**证据冲突的定性站得住**，仅年份需更正。（已在 §3 论文 8 更正。）

- ⚠️【已证实，研究稿准确】**Wikipedia Hierarchical Risk Parity 页带作者利益相关（COI）声明** 页面 2025-12 起挂有 COI 横幅（"A major contributor to this article appears to have a close connection with its subject ... neutral point of view"）。研究稿此项**准确**——引用 HRP 时不应以 Wikipedia 该页为中立来源。
   https://en.wikipedia.org/wiki/Hierarchical_Risk_Parity

**通用陷阱清单（设计须规避）**

- **把 inverse-vol（∝1/σ）当成"风险平价/ERC"交付** → 这是相关性=1 的退化特例，在相关资产上会系统性误配；真 ERC 必须解凸优化并纳入相关性。
- **盲信 HRP "样本外占优"叙事** → 该说法**主要相对 CLA/MVO**；独立研究（2025 FGCS）与加密实测（BTC-hold 击败 HRP）显示其优势**高度数据集依赖、常被 1/N 击败**。Wikipedia HRP 页本身带 COI 声明。
- **直接对原始样本协方差做 MVO/求逆** → condition number 极高（最小特征值近零），权重对输入微扰剧烈震荡（Markowitz 诅咒），且需要 ≥½N(N+1) 观测才可逆，实务样本几乎不够。
- **默认"非线性收缩=最佳协方差估计"** → 有论文（Bongiorno-Challet）称其对组合优化"far from optimal"，且 Frobenius 范数最优不等于组合方差最优；**证据冲突，需按目标与数据验证**。
- **忽视换手率/交易成本** → HRP 尾部依赖扩展、真 ERC、频繁再平衡都可能高换手；在中低频 + 实盘成本下，纸面 Sharpe 优势会被成本吞掉。（注意：3.71% 这个 implementation-risk 极值正源于高换手轮动，**不应泛化成所有方法的普遍风险**。）
- **把回测数字当真理而忽略实现风险** → 同策略跨引擎含成本时有可测量分歧，根因是成本模型实现差异——不锁定成本模型/求解器/再平衡规则就没有可复现性。（但注意：该分歧**不改变决策符号**，是归因模糊而非致命错误，见上方 MEDIUM 降权。）
- **NCO 等两层优化不做无泄露交叉验证** → 簇间权重若不用簇内的样本外估计会引入数据泄露，样本外表现被高估；且金融序列上**朴素 k 折本身有泄露争议，须配 purging+embargo 的 CPCV/walk-forward**。
- **只看最终权重不看诊断** → 不暴露 condition number、特征值谱、估计窗口充足性、相对 1/N 的诚实对照，小白用户无法判断该配置是否可信，等于把病态优化的脆弱性藏起来。

---

## 8. 开放问题

> 以下为对抗核查指出的**漏点（missing angles）**，研究稿完全缺席或仅一句带过，是落地前必须回答的。

1. **换手率/交易成本的量级从未被定量化，却是本产品（中低频 + 到 Binance 实盘）的头等约束。** 研究稿反复说"HRP 尾部扩展/真 ERC/再平衡可能高换手"，但既没给任何换手率或成本拖累的数量级，也没说明在何种再平衡频率下高级方法的纸面优势会被成本完全吞掉——这恰是 implementation-risk 论文里 3.71% 极值的来源（高换手轮动），却被泛化成所有方法的普遍风险。

2. **完全没有讨论 A股特有的结构性约束。** T+1、涨跌停板（±10%/±20%/ST 5%）、停牌导致的协方差估计样本缺口与 PIT 问题、做空限制（几乎无法做真正的多空风险平价）。这些会直接破坏"去噪 → 求逆/聚类 → 配权"管线的可行性（**停牌资产的相关性如何估？涨跌停下的协方差是否可信？**），但研究稿把"资产无关的是管线与治理"当作了挡箭牌，回避了 A股侧最硬的工程约束。

3. **缺少对"估计窗口 vs 资产数 N"的可操作阈值。** 研究稿引用了 DeMiguel 的 3000/6000 月，也说要把"N 与样本长度比"做成体检卡，但**没给出在加密（高频可得长样本但结构非平稳）与 A股（样本短、停牌多）下，何时应触发"降级到 1/N"的具体判据**。没有阈值的体检卡对不懂代码的经济学者等于没有。

4. **再平衡频率与协方差估计频率的耦合被忽略。** HRP/ERC 的结果对"用多长窗口、多频繁重估协方差"**极度敏感**（2025 FGCS 与各 HRP 实证的窗口依赖很大程度来自此），但设计方向里只字未提如何把这个超参纳入治理/无泄露 walk-forward——这是**比"选哪个优化器"更影响结果稳定性的隐藏自由度**。

5. **对"NCO 防泄露的 k 折 CV"只赞扬未质疑。** skfolio 的嵌套 CV 范式被当作"无泄露可验证"的样板，但**金融时间序列上 k 折 CV 本身就有前视/泄露争议**（应配合 purging+embargo 的 CPCV/walk-forward，而非朴素 k 折）。研究稿在别处强调无泄露，却没指出朴素 k 折在簇间权重估计上同样可能引入时间泄露——存在内部不一致。

6. **缺少对"治理/体检卡"本身成本与可证伪性的讨论。** 把每次配置当作 SR 11-7 受治理模型运行、生成验证卡、双引擎交叉核对，对**单用户产品是巨大工程与维护负担**；研究稿未评估这套治理在"单用户、非受监管个人"语境下的边际价值（SR 11-7 本是面向受监管银行的），存在**把机构合规框架过度移植到个人产品**的风险。

7. **对 "detoning（剔除市场主成分）" 在加密上的副作用未提示。** 研究稿说加密"detoning 价值高"（因单一市场因子主导），但 **detoning 会剔除掉 BTC 这个事实上的市场 beta——而 BTC beta 恰恰是该资产类近年最大的收益来源**；在加密上机械 detoning 可能系统性削掉真实收益来源，这一权衡（**去噪 vs 去掉真信号**）未被点明。

---

## 9. 参考文献（URL）

**核心论文**
- HRP 原始论文（López de Prado 2016, JPM）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678
- A Robust Estimator of the Efficient Frontier / NCO（López de Prado 2019）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3469961
- 真 ERC（Maillard, Roncalli & Teiletche 2010, JPM）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1271972
- Optimal versus Naive Diversification / 1/N（DeMiguel, Garlappi & Uppal 2009, RFS）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1376199
- Ledoit-Wolf 非线性收缩综述（The Power of (Non-)Linear Shrinking）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3384500
- HRP 下尾相关扩展（Lohre, Rother & Schäfer 2020, Wiley）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3513399
- HRP Efficient Implementation and Real-World Analysis（FGCS 167, 2025）— https://www.sciencedirect.com/science/article/abs/pii/S0167739X25000391
- Non-linear Shrinkage Far from Optimal（Bongiorno & Challet, arXiv 2112.07521 / FRL vol 52, 2023）— https://arxiv.org/abs/2112.07521
- Implementation Risk in Portfolio Backtesting（Yin et al. 2026, arXiv 2603.20319，未评审预印本）— https://arxiv.org/abs/2603.20319
- Beyond Risk Parity — HRP on Cryptocurrencies（Burggraf 2021, FRL vol 38）— https://www.sciencedirect.com/science/article/abs/pii/S154461232030177X

**机构标准 / 实践**
- Federal Reserve / OCC SR 11-7 Model Risk Management — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- MOSEK Portfolio Optimization Cookbook（估计误差章）— https://docs.mosek.com/portfolio-cookbook/estimationerror.html
- S&P DJI "Indexing Risk Parity Strategies" — https://www.spglobal.com/spdji/en/documents/research/research-indexing-risk-parity-strategies.pdf

**开源工具 / 库**
- Riskfolio-Lib — https://github.com/dcajasn/Riskfolio-Lib ｜ HRP/HERC 文档 — https://riskfolio-lib.readthedocs.io/en/latest/hcportfolio.html
- skfolio — https://github.com/skfolio/skfolio ｜ https://skfolio.org/
- PyPortfolioOpt（权威仓库）— https://github.com/robertmartin8/PyPortfolioOpt
- riskparityportfolio（Palomar 组）— https://pypi.org/project/riskparityportfolio/
- Machine-Learning-for-Asset-Managers（López de Prado 代码社区复现）— https://github.com/emoen/Machine-Learning-for-Asset-Managers

**争议来源（已降权，仅作可追溯标注）**
- Wikipedia Hierarchical Risk Parity 页（带 COI 声明）— https://en.wikipedia.org/wiki/Hierarchical_Risk_Parity
- 加密 BTC-hold vs HRP 个人博客回测（来源降级，非同行评审）— https://alexeygolev.blog/hierarchical-risk-parity-hrp-for-crypto-portfolio-optimisation/
