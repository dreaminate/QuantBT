# 20 · 实盘漂移监控（CUSUM/Page-Hinkley/BOCPD/PSR-live/PSI）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 D

## 1. 一句话定位

本环节回答一个上线后必须持续盯防、却极易被「指标拼盘」糊弄过去的问题：**一个曾经在回测里有效的策略，在实盘中是否正在失效，要在亏多少之前、以什么置信度判定它「红灯」并按规则停？** 核心立场是把监控**拆成两根轴并锚定在绩效上**：(a) **绩效轴**（rolling-PSR、Sharpe 衰减、CUSUM、对 PnL 的 BOCPD）是**主告警**——它直接测「策略还赚不赚钱」；(b) **特征漂移轴**（PSI、Wasserstein、PCA）只是**下游根因工具（root-cause），不是主告警**——它回答「为什么变了」，不能单独触发停机。三条必须钉死的纪律：**① 在上线时刻冻结并版本化「评分尺子」**（scoring ruler），杜绝事后挑指标自圆其说；**② 用 PSR/MinTRL 做上线门（go-live gate），上线后跑 rolling-PSR 或 SPRT，绝不把 Deflated Sharpe Ratio（DSR）的阈值搬到实盘单策略上**——那是范畴错误（见 §7）；**③ 收益非 IID，必须做 HAC 类校正，绝不用 √周期数 年化 Sharpe**。每个探测器都要有**误报预算（false-alarm budget）**与保守观测模型（如 student-t BOCPD），最终汇成一个与簇 D「实盘护栏（env 21）/ D3 决策」对齐的**确定性 绿/黄/红 阶梯**——agent 只警告、由规则停机，并产出一份大白话的健康报告。

> **本环节相对本系列其他环节的一个反常事实**：env 20 的核心事实性断言**罕见地经受住了对抗核查**——Lo 2002 的「序列相关可使年化 Sharpe 虚高 >65%」、DSR 仅回测用、BOCPD 无理论误报界、PSI 0.1/0.25 仅经验法则——**均被核实、无捏造、无撤稿、无争议来源**。本环节的降权**不是关于捏造事实，而是关于「过度简化的处方」与「引用工具与用例之间的内部不一致」**（见 §7）。

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 角色 | 要点 | URL |
|---|---|---|---|
| **NannyML** | label-free 绩效估计（CBPE / DLE） | 在标签缺失/滞后时估计模型绩效；其文档把**漂移定位为根因工具而非主告警**。**【medium 降权·范畴部分错配】NannyML 自家文档明确称 CBPE 与 DLE「无法应对 concept drift」**——而交易策略衰减的本质恰恰就是 signal→return 关系变了（即 concept drift），正是 label-free 估计器估不出的那一种；且交易里 realized PnL 是**即时到达的标签**，根本不需要 label-free 估计（见 §7）。 | https://www.nannyml.com/ |
| **Evidently** | 漂移与数据质量监控 | 在大样本下**优先用带阈值的距离度量（Wasserstein/PSI），而非 p 值检验**（KS/χ² 的 p 值在大 N 下坍缩到 ~0）。**【low 降权】此说方向对，但把「阈值距离」当 settled 最佳实践是夸大——它只是把任意性从 p 值挪到一个手设阈值，与 PSI 0.1/0.25 同样缺 type-I/type-II 依据，是横向移动而非升级（见 §7）。** | https://github.com/evidentlyai/evidently |
| **River** | 在线/流式变点与漂移（ADWIN/DDM/Page-Hinkley） | 流式场景的增量探测器库，含 Page-Hinkley、ADWIN、DDM 等。适合「逐 bar 到达的 PnL/特征流」上的在线监控。**注**：其设计同样源自「标签滞后」的 ML 世界（见 §7 对该 doctrine 的降权）。 | https://github.com/online-ml/river |
| **Alibi Detect** | 漂移/异常/对抗检测 | 提供 MMD、KS、χ²、Wasserstein 等多种漂移检测；同属「大样本下偏好阈值距离」阵营。作为特征漂移轴的根因工具库可选。 | https://github.com/SeldonIO/alibi-detect |
| **rolling-PSR / SPRT（上线绩效轴正典工具）** | 主告警的统计骨架 | 上线门用 **PSR/MinTRL**，上线后跑 **rolling-PSR**（滚动窗口的概率性 Sharpe）或 **SPRT**（Wald 序贯检验，在边界处判定、样本量不固定）。**绝不**把 DSR 阈值搬来当实盘单策略告警。 | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 |

## 3. 关键论文（每条带 URL）

- **The Statistics of Sharpe Ratios（Andrew W. Lo, 2002, *Financial Analysts Journal* / NBER w9571）**——**核实通过、无争议**：月度 Sharpe 年化需要一个 **η_q 因子而非简单 √12**；**序列相关可使年化 Sharpe 虚高最多 >65%**。这是「收益非 IID 必须做 HAC 类校正、绝不用 √周期数年化」立场的承重来源。
  https://www.nber.org/papers/w9571

- **The Probabilistic Sharpe Ratio / Minimum Track Record Length（PSR/MinTRL）与 Deflated Sharpe Ratio（DSR）（Bailey & López de Prado）**——**核实通过、甚至「被低估」**：PSR/MinTRL 是上线门工具；**DSR 是回测用的「多重检验缩水（deflation）」量**，需要 effective-N 与横截面 Sharpe 方差作输入；López de Prado 框架**明确指定 PSR（不是 DSR）才是单试验（single-trial）的上线工具**。因此「把 DSR 阈值搬到实盘单策略 = 范畴错误」的断言是**正确的、甚至比文献还保守**（见 §7 的语气降权说明）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **Bayesian Online Changepoint Detection（Adams & MacKay, 2007）**——**核实通过、无争议**：BOCPD 是在线的「run-length 后验」，**没有理论上的误报界（no theoretical false-alarm bound）**；后续论文专门提出「确认式（confirmatory）修正」正是因为这个缺陷。用 BOCPD 时必须自加误报预算与保守观测模型（student-t）。
  https://arxiv.org/abs/0710.3742

- **Sequential Analysis / SPRT（Abraham Wald, 1945 / 1947）**——序贯概率比检验：在边界处判定、**样本量不固定**，可用更少观测达到同等 type-I/type-II。**注（见 §7）**：SPRT 仅在 **IID 平稳**观测下最优；非平稳需 NSPRT 类扩展。
  https://www.jstor.org/stable/2235829

- **PSI（Population Stability Index）的 0.1 / 0.25 阈值（Lewis, 1994 起的信用评分经验法则）**——**核实通过**：0.1（轻微漂移）/0.25（显著漂移）是**经验法则（rule of thumb），无 type-I 或 type-II 依据**。最近综述（arXiv 2303.01227）确认其为经验阈值。文案不得把它写成有统计保证的门限。
  https://arxiv.org/abs/2303.01227

- **Newey-West / HAC 标准误的有限样本偏差（Newey & West 1987 及后续小样本文献）**——**降权依据论文**：HAC（Newey-West）估计量在**短的、高度重叠的滚动窗口**（正是实盘漂移监控真实使用的窗口）里**本身向下偏、过度拒绝（inflated t、size 扭曲）**；文献建议短窗口下**HAC 与 moving-block bootstrap 并用**。把 HAC 当成干净充分的修正，正落在它有限样本失效的那个区间（见 §7）。
  https://www.jstor.org/stable/1913610

- **Lo–Getmansky–Makarov：对冲基金收益的序列相关与平滑（2004, *Journal of Financial Economics*）**——**缺口角度的承重来源**：对平滑/低流动性收益，那个抬高 Sharpe 的自相关其实是**陈旧定价（stale pricing）= 流动性定时炸弹**；用 HAC「校掉」它会**丢掉这条风险预警**。序列相关不只是统计 nuisance（见 §8）。
  https://www.sciencedirect.com/science/article/abs/pii/S0304405X04000674

## 4. 机构最佳实践 / 标准

- **绩效轴为主、特征漂移轴为辅（MLOps 监控分层）**：性能（label-based or label-free）是主告警，特征/数据漂移是下游根因。**【medium 降权·过度泛化 + 支撑错配】此 MLOps doctrine 成立是因为「标签通常滞后」，且即便在 ML 内部也有争议**（标签滞后/缺失时，特征漂移是公认的领先指标）。**对交易 PnL 而言标签即时到达，这反而强化了「绩效为主」对本用例的正确性——但研究把它当成普适原则陈述，同时却倚赖一批「为标签滞后世界而生」的工具（NannyML/Evidently/River），那个世界里结论恰恰相反。原则过度泛化、其支撑基座与用例错配（见 §7）。**
  https://www.nannyml.com/

- **上线时刻冻结并版本化「评分尺子」**：把告警所用的指标集、窗口、阈值、归一化方式在 go-live 当天写死并打版本号，杜绝事后挑指标（after-the-fact metric picking）自圆其说。这是抗博弈（anti-gaming）的核心治理动作。

- **PSR/MinTRL 做上线门、上线后跑 rolling-PSR 或 SPRT**：上线门一次性回答「track record 是否够长够稳到值得上线」；上线后用滚动 PSR 或序贯检验持续判定。PSI 0.1/0.25 只作经验粗筛、不作判定门限。

- **非 IID 收益做 HAC 类校正、永不 √周期数年化**：年化 Sharpe 必须按 Lo 2002 的 η_q 因子（或等价的 HAC 修正）做，且在**短重叠窗口**里**与 block bootstrap 并用**以纠正 HAC 的有限样本过拒（见 §4 第一条降权与 §7）。

- **每个探测器一份误报预算 + 保守观测模型**：CUSUM/Page-Hinkley/BOCPD/PSR-live/PSI 各自标定误报率，BOCPD 用 student-t（厚尾）观测模型而非高斯，避免跳日把告警打满。

- **确定性 绿/黄/红 阶梯，对齐 D3（agent 只警告、规则停机）**：阶梯需 **regime 条件化归一化**（不同 regime 下基线不同），并产出**大白话健康报告**给非技术用户。这条与 env 21（实盘护栏/killswitch/执行安全）直接咬合。

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **两轴分离、告警锚在绩效轴**：把「绩效轴（rolling-PSR / Sharpe 衰减 / CUSUM / PnL-BOCPD）」设为唯一能触发黄/红灯的主告警；把「特征漂移轴（PSI / Wasserstein / PCA）」**结构性降级为根因解释器**，它只能给红灯**附注「为什么」**，不能独立点灯。**关键修正**：本项目交易 PnL 是**即时标签**，因此**不需要也不应**把架构建在 label-free 估计（NannyML CBPE/DLE）之上——那类工具的核心假设（无 concept drift）恰被「策略衰减」违反（见 §7）；NannyML/Evidently/River 只作特征轴的根因工具库参考，不作绩效轴主告警。

2. **go-live 冻结评分尺子为治理不变量**：在策略上线那一刻，把指标集/窗口/阈值/归一化/regime 分桶定义**写死并打版本号**，存进策略卡。任何上线后想改尺子的动作都必须走「重新 go-live + 重新计 MinTRL」流程，而不是热改阈值——这是把抗博弈做成结构而非口号。**注**：冻结尺子与「regime 条件化适配」存在张力（见第 6 条与 §8），需在卡里显式声明二者如何共存。

3. **上线门用 PSR/MinTRL、上线后跑 rolling-PSR 或 SPRT，永不把 DSR 阈值搬到实盘**：DSR 是回测期的多重检验缩水量，搬到实盘单策略会**重复计入一个已不再适用的试验数惩罚（double-count trial-count penalty）**（见 §7）。实盘判定只用 rolling-PSR / SPRT。把 SPRT 的 IID 前提显式标注：非平稳 PnL 流要么用 NSPRT 类扩展，要么把判定限定在「已 regime 归一化后的残差」上。

4. **非 IID 校正用 HAC + block bootstrap 并用，绝不 √周期数年化**：默认按 Lo 2002 的 η_q 因子做年化，并在短重叠窗口下**强制与 moving-block bootstrap 并用**以纠正 Newey-West 的有限样本过拒——**否则「校正后」的告警可能比朴素版还更差校准**（见 §7）。把 A股（T+1、涨跌停、停牌）与 Binance perp（连续、资金费、杠杆）的序列相关结构、年化周期数、尾部行为**分别参数化**，不可用单一 HAC / 单一 BOCPD 观测模型一刀切（见 §8）。

5. **把基线非平稳当成对所有四个主探测器的一阶威胁**：CUSUM 依赖已知/估准的 pre-change 参数（参考值 k、阈值 h），在 regime 漂移的非平稳 PnL 流里，**pre-change 基线自己在漂移**——而那恰恰是要检测的东西，假设部分自我违反（见 §7）。因此 regime 条件化归一化**不能是一句带过的修饰语**，而要作为绿/黄/红阶梯的结构前置：先把 PnL 投影到「当前 regime 的期望分布」上、再喂探测器。

6. **给整族探测器 + 跨时间一个家族级误报控制（缺口补全）**：连续跑 CUSUM/Page-Hinkley/BOCPD/PSR-live/PSI 五个探测器，本身就是一个**多重检验问题**——讽刺的是整个 DSR 讨论谈的就是多重检验膨胀，本环节却没控制这五器 × 持续时间的 family-wise 误报率（见 §8）。建议用「确认式投票（需 ≥k 个探测器同向 + 持续 ≥d bar 才升红）」+ family-wise 误报预算，把 BOCPD「无理论误报界」的缺口用确认机制兜住。

7. **用经济损失函数标定阈值，显式定价「误停」的非对称成本（缺口补全）**：在 D3 下「在回撤谷底误杀一个仍然有效的策略」（锁定亏损、错过均值回复）与「漏检」的代价不同；要把这条非对称成本写成损失函数去标定 CUSUM 的 ARL（平均运行长度）与红灯阈值，而不是拍脑袋设门限（见 §8）。

8. **序列相关既校正也保留为风险信号（缺口补全）**：对平滑/低流动性收益，HAC「校掉」的那个自相关其实是 stale-pricing 流动性预警（Lo-Getmansky-Makarov）。建议**双轨**：年化用校正后的；同时把「原始自相关水平」单列为一条**流动性健康指标**，异常升高单独点黄灯，而不是被校正掉就当不存在。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**两轴分离 + 绩效轴锚定（特征轴只作根因附注）：**

```
# 主告警 = 绩效轴（PnL 即时标签，无需 label-free 估计）
perf_signal = {
    "rolling_psr": rolling_psr(pnl[:t], window=W, hac="newey_west+block_bootstrap"),
    "sharpe_decay": sharpe_decay(pnl[:t]),       # 永不 √周期数年化，用 Lo-2002 η_q
    "cusum":  cusum(pnl_normalized_by_regime[:t], k, h),
    "bocpd":  bocpd(pnl[:t], obs_model="student_t"),   # 厚尾观测，自带误报预算
}
# 特征轴 = 仅根因（不能独立点灯）
rootcause = {"psi": psi(...), "wasserstein": wass(...), "pca": pca_shift(...)}
light = ladder(perf_signal)                 # 灯只由绩效轴决定
report = explain(light, rootcause)          # 漂移特征只解释"为什么"
# 注：NannyML CBPE/DLE 这类 label-free 估计器不进主告警——其核心假设(无 concept drift)
#     恰被"策略衰减=concept drift"违反；交易 PnL 是即时标签，本就不需要它
```

**regime 条件化归一化 = 所有探测器的结构前置（基线非平稳是一阶威胁）：**

```
# 先把 PnL 投影到"当前 regime 的期望分布"，再喂探测器
# 否则 CUSUM 的 pre-change 基线自己在漂移 => 假设自我违反
pnl_resid = (pnl_t - mu[regime_t]) / sigma[regime_t]
# SPRT 仅 IID 平稳时最优 => 只在已归一化残差上跑，或换 NSPRT
decision  = sprt(pnl_resid[:t], alpha=fa_budget, beta=miss_budget)
```

**确定性 绿/黄/红阶梯 + 家族级误报控制 + 经济损失标定（schema 草图）：**

```yaml
drift_monitor_card:
  scoring_ruler:                       # go-live 当天冻结、打版本号（抗博弈）
    frozen_at: <go_live_ts>
    version: <ruler_vN>                # 改尺子 = 重新 go-live + 重算 MinTRL
    metrics: [rolling_psr, sharpe_decay, cusum, bocpd]
    regime_buckets: <frozen_def>       # 注：与 regime 适配存在张力，须显式声明共存
  axes:
    performance:                       # 主告警：唯一能点灯的轴
      primary_alarms: [rolling_psr, sharpe_decay, cusum, bocpd]
      non_iid_correction: newey_west + moving_block_bootstrap   # 短窗口下并用
      never: sqrt_periods_annualization
    feature_drift:                     # 仅根因，不能独立点灯
      tools: [psi, wasserstein, pca]
      psi_thresholds: {warn: 0.1, alarm: 0.25}   # 仅经验法则，无 type-I/II 依据
      role: root_cause_only
  go_live_gate:
    instrument: psr_mintrl             # 上线门
  live_decision:
    instrument: rolling_psr | sprt     # 上线后判定
    never_use: deflated_sharpe_threshold   # DSR 是回测多重检验缩水量，搬来=范畴错误
    sprt_assumption: iid_stationary_only    # 非平稳 => 用归一化残差或 NSPRT
  false_alarm_control:
    per_detector_budget: required
    family_wise: required              # 缺口补全：五器 × 时间的 FWER 必须控制
    confirmation_rule: ">=k detectors same-direction & persist >=d bars"   # 兜住 BOCPD 无理论误报界
    bocpd_obs_model: student_t
  detection_delay:                     # 缺口：必须量化
    target_arl_to_detect: <bars>       # "亏几天才点红"是决策关键数字
    worst_case_delay: <bars>
  economic_loss_function:              # 缺口补全：误停的非对称成本定价
    cost_false_halt: <drawdown_trough_lock_in + missed_mean_reversion>
    cost_missed_detection: <continued_bleed>
    thresholds_set_by: economic_loss   # 阈值由损失函数标定，非拍脑袋
  serial_correlation:                  # 缺口：既校正也当风险信号
    annualization: hac_corrected
    raw_autocorr_as_liquidity_flag: true   # stale-pricing 预警，单独点黄
  ladder:                              # 对齐 D3 / env 21
    levels: [green, yellow, red]
    regime_conditioned: true           # 非平稳基线 => 归一化是结构前置而非修饰
    action: warn_only                  # agent 只警告，规则停机
    health_report: plain_language
  market_specific:                     # 缺口：禁市场无关一刀切
    a_share: {calendar: gapped, limit_moves: true, t_plus_1: true}
    binance_perp: {continuous: true, funding: true, leverage: true,
                   jump_days_destabilize: [psr_skew, psr_kurtosis]}  # 资金费/清算跳/费拖
# 注：本环节核心事实经受住核查（Lo 65%、DSR 回测限、BOCPD 无界、PSI 经验法则均核实）；
#     降权集中在"过度简化处方"与"引用工具与用例错配"，非捏造事实
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（夸大/争议/撤稿/二手/不可外推/过度泛化/范畴错配/部分自我违反/横向移动/语气非实质 等）**原样保留**；凡涉「已验证/总是更优/干净充分的修正/settled 最佳实践」的强确定性措辞均已按对抗核查降级。任何对用户的承诺或文案，必须采用降级后的表述。

**对抗核查总评（verdict）**：**大体稳健，仅有边界性越界。** 与本系列大多数环节不同，**env 20 的核心事实性断言经受住了审查**——Lo 2002 确实报告了序列相关可使年化 Sharpe 虚高 >65%、且 √12 对非 IID 收益是错的（NBER w9571, FAJ 2002）；DSR 确是「回测 + 多重检验缩水」量，需要 effective-N 与横截面 Sharpe 方差作输入，López de Prado 框架**明确指定 PSR（非 DSR）为单试验上线工具**，故「实盘 DSR 阈值=范畴错误」的断言**正确、甚至被低估**；BOCPD（Adams-MacKay 2007）**确实没有理论误报界**，后续论文专门提确认式修正正因如此；PSI 0.1/0.25 **确为 Lewis-1994 经验法则、无 type-I/II 依据**。**无任何被点名论文被撤稿或有争议**，且研究**避开了已知的 DSR 雷区**（把 DSR 当 deflation、而非把它当成「修正系统性低估」的工具）。因此降权是关于**过度简化的处方**与**引用工具的内部不一致使用**，不是捏造事实。**最伤的矛盾**：研究把 **NannyML 举为「绩效优先监控」的范例，但 NannyML 自家文档称 CBPE 与 DLE 无法应对 concept drift——而那正是衰减交易策略的失效模式，研究全程没有标注这点**；它还把「绩效为主、特征漂移为辅」这条 MLOps doctrine 照搬进来，**没指出该 doctrine 之所以存在是因为 ML 标签滞后，而交易 PnL 标签即时**，使得 NannyML/Evidently 框架的一部分与交易用例是范畴错配。

- **【medium · 过度简化】「HAC 校正修复非 IID 收益、永不 √周期数年化」被当成干净充分的修正陈述**——HAC（Newey-West）估计量**本身向下偏、过度拒绝（inflated t-stats、size 扭曲）**，恰恰发生在实盘漂移监控真实使用的**短的、高度重叠的滚动窗口**里。文献建议短窗口下**moving-block bootstrap 与 HAC 并用**。把 HAC 当作「那个修正」而无视它在「正是实盘短窗口」这个区间的有限样本失效，是一种过度简化，**可能让校正后的告警比朴素版还更差校准**。
  https://www.jstor.org/stable/1913610

- **【medium · 过度泛化 + 支撑错配】「绩效轴为主告警、特征漂移（PSI/Wasserstein/PCA）仅下游根因」被当成普适设计原则**——这条 MLOps doctrine 成立是因为**标签通常滞后，且即便在那里也有争议**（标签滞后/缺失时特征漂移是公认领先指标）。对交易 PnL 标签即时，**这强化了本用例的正确性**；但研究把它当**普适原则**陈述，同时倚赖一批「存在理由就是标签滞后世界」的工具（NannyML/Evidently/River），那个世界里结论恰恰相反。**过度泛化、其支撑基座错配。**

- **【medium · 范畴部分错配】「NannyML 作为 label-free 绩效估计的 SOTA 范例、漂移是根因而非主告警」**——**部分范畴错配**。NannyML 的 CBPE 与 DLE 是为**延迟标签的 ML 管线**设计的，且其文档**明确称不应对 concept drift**。而活的交易策略衰减恰恰因为 signal→return 关系在变（即 concept drift），那正是 label-free 估计器估不出的那一种 regime。**对交易你根本不需要 label-free 估计，因为 realized PnL 就是实时到达的标签。** 把 NannyML 当模板，等于引入一个其核心假设被交易失效模式违反的工具，且未加标注。

- **【medium · 假设部分自我违反】「CUSUM 与 BOCPD on PnL 作为主绩效告警、用 student-t BOCPD 等保守观测模型」**——CUSUM 假设 pre-change 参数已知或估准（参考值 k、阈值 h），**对其高度敏感**；在 regime 漂移的非平稳 PnL 流里，**pre-change 基线自己在漂移**——那正是要检测的东西，假设**部分自我违反**。SPRT 仅在 **IID 平稳**观测下最优（否则需 NSPRT）。研究把 regime 条件化归一化**降格为一句带过的修饰**，而没有把「基线非平稳」当成对全部四个主探测器的一阶威胁。

- **【low · 横向移动当升级】「大样本下优先阈值距离度量、而非 p 值检验」（Evidently/River/Alibi 框架）**——**方向上正确**（KS/χ² 的 p 值在大 N 下坍缩到近 0），但被当成 settled 最佳实践陈述；替代方案「阈值化的 Wasserstein 或 PSI」只是把任意性**挪到一个手设阈值**、同样缺 type-I/type-II 依据——正是研究自己对 PSI 0.1/0.25 提的那条批评。它**用一个已知差的旋钮换一个同样无依据的旋钮，却当成升级而非横向移动**。

- **【low · 语气非实质】「DSR 是回测专用、其实盘单策略阈值是范畴错误」**——**此断言正确且来源扎实**，此处标注仅为记录它**经受住了对抗核查**、且至多是修辞性的语气过强。称其为「范畴错误（category error）」比文献更锋利——文献只是说 PSR 是单试验工具、DSR 加的是多重检验缩水；实盘用 DSR 阈值是**重复计入一个已不再适用的试验数惩罚（double-count trial-count penalty）**。**语气，非实质。**

**被核实但未被推翻（verified but not disputed）**：Lo 65%（NBER w9571）；DSR 回测专用、PSR 单试验（SSRN 2460551）；BOCPD 无误报界（确认于后续论文，arXiv 2407.16376）；PSI 经验法则（arXiv 2303.01227）。
**因遗漏（非撤稿）而被部分削弱**：NannyML CBPE 与 DLE 按其自家文档在 concept drift 下失效。

## 8. 开放问题

- **检测延迟 vs 误报未被量化**：没有给出 **Average Run Length（ARL）to detection** 或最坏情况延迟——而「红灯触发前要流血几天」是实盘停机的**决策关键数字**，CUSUM 的 ARL 调参正是这个权衡的发生地。缺这个量化，整套阶梯无法真正驱动停机决策。
- **五个探测器 + 跨时间的多重检验未被控制**：每个探测器有自己的误报预算，但**连续跑 CUSUM/Page-Hinkley/BOCPD/PSR-live/PSI 的 family-wise 误报率从未被控制**——**讽刺的是整个 DSR 讨论谈的就是多重检验膨胀**。需要确认式投票 + family-wise 误报预算。
- **D3 下「误停」的非对称成本从未被定价**：在回撤谷底误杀一个仍然有效的策略（锁定亏损、错过均值回复）vs 漏检的代价不对称；**没有经济损失函数来标定阈值**。阈值仍是拍脑袋而非由损失函数导出。
- **冻结尺子 vs regime 适配的张力未被调和**：一个在良性样本内 regime 上冻结的尺子，在 regime 翻转时会**误标定**（产生长期假红或长期失明），**直接与 regime 条件化归一化目标冲突**；研究没有调和「抗博弈冻结」与「适配性」二者。
- **市场特定结构被一刀切**：A股（间隙日历、涨跌停、T+1）vs Binance perp（连续、资金费、杠杆）有不同的序列相关、年化周期数与尾部行为，但研究**市场无关地**只给单一 HAC 与单一 BOCPD 观测模型；**资金费 carry、清算跳空、费拖**还会在**跳日**附近扰动 PSR-live 的 skew/kurtosis 输入——那不是漂移，却仍会触发 student-t BOCPD（误报源）。
- **序列相关被仅当 nuisance 处理、丢掉了风险信号**：对平滑/低流动性收益（Lo-Getmansky-Makarov），那个抬高 Sharpe 的自相关是 **stale pricing = 流动性定时炸弹**；HAC「校掉」它会**丢掉这条预警**。研究把序列相关纯当统计 nuisance 去除，未把它单列为流动性健康指标。

## 9. 参考文献（URL）

- The Statistics of Sharpe Ratios（Andrew W. Lo, 2002, FAJ / NBER w9571）【核实通过：序列相关使年化 Sharpe 虚高 >65%、√12 对非 IID 错】：https://www.nber.org/papers/w9571
- The Sharpe Ratio Efficient Frontier / PSR / MinTRL 与 Deflated Sharpe Ratio（Bailey & López de Prado，SSRN 2460551）【核实通过：DSR 回测专用、PSR 单试验上线】：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Bayesian Online Changepoint Detection（Adams & MacKay, 2007, arXiv 0710.3742）【核实通过：无理论误报界】：https://arxiv.org/abs/0710.3742
- BOCPD 无误报界的后续确认（arXiv 2407.16376）：https://arxiv.org/abs/2407.16376
- Sequential Analysis / SPRT（Wald, 1945, JSTOR）【仅 IID 平稳最优】：https://www.jstor.org/stable/2235829
- A Hypothesis Test for the Robustness of PSI / PSI 经验阈值综述（arXiv 2303.01227）【核实通过：0.1/0.25 仅经验法则、无 type-I/II 依据】：https://arxiv.org/abs/2303.01227
- A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix（Newey & West, 1987, JSTOR）【HAC 短重叠窗口有限样本过拒】：https://www.jstor.org/stable/1913610
- An Econometric Model of Serial Correlation and Illiquidity in Hedge Fund Returns（Lo, Getmansky & Makarov, 2004, JFE）【自相关=stale pricing 流动性预警】：https://www.sciencedirect.com/science/article/abs/pii/S0304405X04000674
- NannyML（CBPE / DLE，label-free 绩效估计；**文档自承不应对 concept drift**）：https://www.nannyml.com/
- Evidently（漂移/数据质量监控，大样本偏好阈值距离）：https://github.com/evidentlyai/evidently
- River（在线流式探测器：Page-Hinkley / ADWIN / DDM）：https://github.com/online-ml/river
- Alibi Detect（MMD/KS/χ²/Wasserstein 漂移检测）：https://github.com/SeldonIO/alibi-detect
