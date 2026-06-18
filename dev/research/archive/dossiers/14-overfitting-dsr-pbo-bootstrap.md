# 14 · 过拟合体检（DSR/FST/PBO/CSCV/Bootstrap/MinBTL）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 C

## 1. 一句话定位

把一组过拟合指标从"灰标/参考数字"升级为**全生命周期不可绕过、不可事后调参的契约式体检**——核心骨架来自 Bailey & López de Prado 系：False Strategy Theorem（FST）→ Deflated Sharpe Ratio（DSR）、Probabilistic Sharpe Ratio（PSR）/Minimum Track Record Length（MinTRL）、Combinatorially Symmetric Cross-Validation（CSCV）→ Probability of Backtest Overfitting（PBO）、Minimum Backtest Length（MinBTL），辅以 Ledoit-Wolf 稳健 bootstrap Sharpe 推断与 Harvey-Liu 多重检验 haircut。但关键编辑判断是：**绝不能据此把任何单一指标设为单点否决式硬闸**——DSR/PBO 的正确性都押在两个公认难估、误差符号双向的量上（有效独立试验数 N、试验夏普的横截面方差 V），所以正确落地形态是"多证据三角 + 通缩区间 + 人类经济判断"，而非一个红灯阈值。在 agent 自动搜索场景下，本环节真正的独有杠杆是把 López de Prado 第三定律（每个回测连同全部试验上报）做成**系统不变量**——而这恰恰也是最难落地、本研究只给愿景未给可行性论证的工程难题。

---

## 2. 前沿 SOTA 与代表系统

| 系统 | 它强在哪 | 对 QuantBT 的可迁移点 |
|---|---|---|
| **Marcos López de Prado / ADIA Lab 工作流（AFML 第11/14/15章 + CPCV + 合成数据回测）** | 事实上的机构级过拟合体检 SOTA。把 DSR/PSR、PBO（CSCV）、Combinatorial Purged CV（CPCV，带 purge+embargo 防泄露）、合成数据回测、以及"每个回测必须报告全部试验 N"写成方法论。三定律：回测不是研究工具；别按回测调模型；每个回测须连同所有试验上报。 | "全程累计 N + 多证据"的方法论母本。**但 CPCV 优于 walk-forward 的系统证据仅来自 Heston 合成受控环境，未在真实低频市场外推验证（见 §7），CPCV 在本产品应作候选而非默认强制。** URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2606462 |
| **Hudson & Thames MlFinLab — backtest_statistics / backtest_overfitting** | AFML 第14/15章的成熟开源实现：annualized SR、PSR、DSR、MinTRL、PBO（CSCV）、CPCV。机构常用作参考实现。 | 公式核对与口径参照基准。**注意：MlFinLab 已闭源/商业化，作硬闸前须核实当前 license（已核实属实，见 §7）。** URL: https://hudsonthames.org/mlfinlab/ |
| **Harvey-Liu "Backtesting" 多重检验 haircut 框架** | 用 Bonferroni/Holm/BHY 三套多重检验校正，把单测试 p 值/夏普做**非线性** haircut；明确反对一刀切 50% 折扣（高夏普轻罚、边际夏普重罚）。Duke 提供官方代码。 | 一组策略逐一折扣的工具，与 DSR（单一最佳策略阈值）互补。**但与 DSR 并用存在对同一组 N 个检验双重计数（double-counting）的风险（见 §7 漏点）。** URL: https://people.duke.edu/~charvey/backtesting/ |
| **Ledoit-Wolf 稳健夏普推断（studentized stationary / circular block bootstrap）** | 对自相关、非正态、单/双策略夏普差的稳健置信区间与假设检验；是 bootstrap Sharpe CI 的标准方法，被 arch（Kevin Sheppard）等库实现。 | 作为"多证据三角"第三支，对自相关/肥尾稳健，与 DSR 的四阶矩解析修正交叉校验；二者矛盾时取更保守者。 URL: https://www.econ.uzh.ch/apps/workingpapers/wp/iewwp320.pdf |

> 编辑判断说明：把 López de Prado 工作流称作"事实上的 SOTA"是可辩护的编辑判断而非可证伪事实——其方法论的若干环节（尤其 CPCV 相对 walk-forward 的优越性）在真实低频数据上尚无系统外推证据（已在 §7 按"中"严重度降权）。

---

## 3. 关键论文（每条带 URL）

1. **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality（Bailey & López de Prado, J. Portfolio Management 2014）**
   提出 DSR = PSR 在多重检验抬升后的阈值 SR0 处取值。原文式(1)：E[max{ŜR_n}] ≈ E[{ŜR}] + √V[{ŜR}]·((1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(Ne)))，γ≈0.5772（Euler-Mascheroni）。**确证：DSR 校正的是"选择偏差 + 非正态 + 短样本"三项，SR0 随横截面方差 V 与试验数 N 上升——DSR 是阈值标度修正（threshold scaling / studentization），不是夏普偏置补偿。**
   URL: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf （亦见 SSRN 2460551）

2. **The Probability of Backtest Overfitting（Bailey, Borwein, López de Prado, Zhu, J. Computational Finance 2015）**
   定义 PBO 与 CSCV：N×T 收益矩阵切 S 块，取所有 C(S, S/2) 个对半组合，一半 IS 一半 OOS；对每组合记 IS 最优策略在 OOS 的相对秩 ω̄_c，取 logit λ_c=ln(ω̄_c/(1−ω̄_c))，PBO=Prob(λ<0)（IS 冠军在 OOS 跌到中位数以下的频率）。附产 performance degradation（IS→OOS 退化斜率）、probability of loss、stochastic dominance。明确 holdout/标准 CV 在回测语境失效（单次试验视角、忽略 N 增长导致的假阳率）。
   URL: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf （亦见 SSRN 2326253）

3. **Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance（Bailey, Borwein, López de Prado, Zhu, Notices of the AMS 2014, 61(5):458–471）**
   提出 Minimum Backtest Length（MinBTL）：噪声下 N 个独立试验的最佳 IS 夏普随极值理论的 √(2 ln N) 量级抬升，故为使噪声策略不被误选所需的最短回测年数随 ln(N) 增长；不报告 N 的回测在统计上不可解读。**注：summary 中给出的"约 ∝ (E[max]/年化)⁻²"量级表述转写不严谨——√(2 ln N) 来自极值理论，而非直接出自 deflated-sharpe 论文式(1)；核心论断（5 年数据下试 >45 个独立配置几乎必然产出 IS Sharpe=1/OOS=0 的假策略）成立，仅公式转写需校正（见 §7）。**
   URL: https://www.ams.org/notices/201405/rnoti-p458.pdf

4. **The Sharpe Ratio Efficient Frontier（Bailey & López de Prado, J. Risk 2012, 15(2)）**
   提出 PSR 与 MinTRL：PSR(c)=Φ[(ŜR−c)·√(T−1) / √(1−γ̂₃ŜR+((γ̂₄−1)/4)ŜR²)]；MinTRL(c)=(1−γ̂₃ŜR+((γ̂₄−1)/4)ŜR²)·(z_{1−α}/(ŜR−c))²。**偏度 γ̂₃ / 峰度 γ̂₄ 不改变夏普点估计，但显著改变其置信带（负偏 + 高峰度 → 标准误更大）——这是 DSR 分母的来源，确证"标准化（studentize）而非偏置修复"的本质。**
   URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643

5. **Robust Performance Hypothesis Testing with the Sharpe Ratio（Ledoit & Wolf, J. Empirical Finance 2008, 15(5):850–859）**
   用 studentized 时间序列 block bootstrap 构造夏普（及两夏普之差）的稳健 CI/检验，处理自相关与非正态；比 delta-method 解析标准误在有限样本更可靠。是 bootstrap Sharpe CI 的权威方法。
   URL: https://www.econ.uzh.ch/apps/workingpapers/wp/iewwp320.pdf

6. **Backtesting（Harvey & Liu, J. Portfolio Management 2015/2020）**
   多重检验 haircut 是**非线性**的：最高夏普仅轻度折扣、边际夏普重罚；反对 50% 经验折扣。提供 Bonferroni/Holm/BHY 三法与可重复代码。与 DSR 互补：DSR 是单一最佳策略阈值，HL 给一组策略的逐一折扣。
   URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2345489 （Duke 官方代码：people.duke.edu/~charvey/backtesting）

7. **A Bayesian Approach to Measurement of Backtest Overfitting（Risks 2021, 9(1):18, MDPI）**
   对 CSCV/PBO 的贝叶斯替代，指出 PBO 估计依赖 S 选择/收益对齐/可交换性假设；提供另一条不依赖组合切分的过拟合度量路径。属对 PBO 方法学的补充/质疑。
   URL: https://www.mdpi.com/2227-9091/9/1/18

8. **Is There a Replication Crisis in Finance?（Jensen, Kelly, Pedersen, Journal of Finance 2023, 78(5)）+ 反向：Harvey-Liu-Zhu 2016（RFS）/ Hou-Xue-Zhang 2020（RFS）**
   反证：在统一（贝叶斯/层级）方法下因子复现率很高，削弱"金融发现几乎全假"的论断；而 HLZ（…and the Cross-Section of Expected Returns）与 HXZ（Replicating Anomalies，~35% 通过 t>1.96）给出高假阳率。**注：把二者描述为干净的"噪声派 vs 真实派"对峙是过度简化——JKP 明确把 HXZ 低复现率主要归因于其"剔除微盘股 + 市值加权"的方法选择，而非纯粹噪声判断（见 §7）。**
   URL: https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249

9. **Open Source Cross-Sectional Asset Pricing / 发表偏误下 t-hurdle 不可识别（Chen & Zimmermann, Management Science 2023）**
   在发表偏误下 t-hurdle 调整本身不可识别——"数据对 t 门槛该升该降几乎无话可说"。这削弱的是 HLZ"需提高 t 门槛"一侧，而非简单支持任一派。**此点反而被原研究低估，应更突出地用于反驳"提高 t 门槛"一侧（见 §7）。**
   URL: https://pubsonline.informs.org/doi/10.1287/mnsc.2023.03083

---

## 4. 机构最佳实践 / 标准

1. **把过拟合体检定位为"独立验证关卡"**：SR 11-7（美联储/OCC 2011 模型风险管理）把 outcomes analysis / backtesting 列为模型验证三支柱之一，核心是 "effective challenge"——由独立、有能力、有组织影响力的人做批判性复核而非橡皮图章；OOS 验证须用未参与开发的样本期。
   来源：Federal Reserve SR 11-7 / OCC 2011-12。URL: https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

2. **按策略 materiality 分级验证强度**：SR 26-2（Fed/OCC/FDIC 联合，2026-04-17）更新 SR 11-7，从清单式转向风险相称的判断式治理（Inherent Risk / Exposure / Purpose / Materiality 四要素定验证强度），"有效挑战"从结构独立转向"复核质量"；明确把生成式/agentic AI 排除在指南范围外。
   **注：研究原引用的是 Medium 二手源；一手为 federalreserve.gov；且 SR 26-2 主要面向 >300 亿美元资产银行，作为单用户量化平台"硬闸分级"的"直接监管类比"强度被夸大（见 §7）。**
   来源（一手）：https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm

3. **TEVV 贯穿生命周期**：NIST AI RMF 1.0 把 Test/Evaluation/Verification/Validation 贯穿生命周期，"Valid & Reliable" 是可信 AI 的基石；Measure 函数在部署前与全程持续做定量+定性度量。可作为"过拟合体检即 Measure 关卡"的非金融通用框架。
   来源：NIST AI 100-1（AI RMF 1.0）。URL: https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf

4. **回测前置 checklist 与同行评审**：López de Prado"量化投资七宗罪"/"十大 ML 基金失败原因"：幸存者偏差、前视、storytelling、数据挖掘/多测、shorting 成本、交易成本、异常值、未做 walk-forward/purge-embargo。机构把这套清单当回测前置 checklist 与同行评审依据。
   来源：Luo et al.（Deutsche Bank）"Seven Sins of Quantitative Investing"；López de Prado "The 10 Reasons Most ML Funds Fail"。URL: https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给概念级方向，不点 file:line、不排实施计划。

1. **平台层自动累计 agent 产生的全部试验 N，用户不可手动改小**：每次参数扫/特征增删/重跑都计入，把 López de Prado 第三定律变成系统不变量——这是 agent-OS 相对人工研究的独有杠杆。**重大可行性警告（见 §8 与 §7 漏点）**：这在 agent 自动搜索下不仅是低估风险，更是根本性不可观测问题——LLM-agent 单次推理内部隐式尝试的多个假设无法被埋点捕获；按聚类估"有效独立 N"又需要一个相关阵，而该相关阵本身需这些策略同期回测才能估，存在先有鸡还是先有蛋的循环。建议先界定"可观测试验 N 的最小可审计口径"（显式提交的回测/扫描/重跑），明确标注其为下界而非真值，而非声称已捕获全部 N。

2. **硬闸输出"通缩区间 + 体检证据包"，绝不输出单点裁决**：对有效独立 N 用聚类（ONC/层次/相关阵特征值）给区间、对横截面方差 V 给区间，联动算出 DSR 的乐观/保守两端，并明确告诉用户"误差符号取决于 N 与 V 的真实值——我们偏保守"。非技术用户看到的是"红/黄/绿 + 为什么"，而非一个易被误读为"修复后的好夏普"的数字。**DSR 定位务必降级（见 §7）：它是带敏感性区间的多证据三角中的一支，不可单点裁决。**

3. **用"多证据三角"而非单一指标当闸**：DSR/PSR（解析、含偏度峰度）、PBO/CSCV（组合交叉验证、给退化斜率与 probability of loss）、studentized block-bootstrap Sharpe CI（对自相关/肥尾稳健）三者并列，只有同向通过才放行；三者矛盾时取最保守者并显式呈现分歧。**对中低频长持仓，CV 的 purge+embargo（CPCV）作为候选而非默认强制——其相对 walk-forward 的优势仅在 Heston 合成受控环境证实，未在真实低频数据外推（见 §7）。**

4. **闸门强度按策略 materiality 分级**（借鉴 SR 26-2 的判断式治理）：A股到 paper 与加密到 Binance 实盘走不同严格度——实盘前置最严（且按已锁定决策 D3，实盘 agent 仅警告 + 规则停）；为每次放行生成可审计、可复算、口径版本化的"有效挑战"记录。**但应把闸门阈值与"当前生命周期阶段的实际损失函数"挂钩（见 §8 漏点）**：paper/模拟盘阶段放行假策略代价极低，而错杀真实但微弱的中低频 alpha 代价高；一刀切保守主义会系统性扼杀低频弱信号。

5. **在产品话术与教育层显式区分两类陈述**：DSR 是"在多次试验与给定离散度下夏普是否仍显著正"的**选择偏差阈值校正**，不是"修复夏普被低估"、更不替代真实 OOS/前进式验证；同时**不把"多数金融发现为假"当真理灌输（已被 JKP 2023 部分反驳，且 HXZ 低复现率主因是微盘加权口径而非纯噪声，见 §7）**，让经济学者用户在"统计闸门"与"经济判断"之间各司其职。

6. **为防"体检本身被过拟合"**：把体检引擎（回测口径、S、N 累计规则、阈值）固定为单一版本化契约，任何修改进审计日志并触发对历史已放行策略的回溯重检；同时固定唯一回测引擎口径以消除 implementation-risk 式指标漂移。**降权（见 §7）：implementation-risk 漂移仅在高换手 + 高成本子集显著，对中低频低换手产品影响被高估——零成本下五引擎完全一致、12/15 基准分歧 <0.75pp、不翻转 Sharpe 符号；此项可作"高换手分支才固定引擎口径"的弱主张，不必上升为全局必需。**

7. **短样本失效边界须显式声明（来自 §8 漏点）**：A股到 paper、加密历史短，T 本身就小——DSR 分母的偏度/峰度四阶矩修正在 T 小时本就不可靠（γ̂₃/γ̂₄ 估计方差爆炸），PBO 的 C(S, S/2) 组合在短序列下子块数 S 受限、统计功效极低。建议把"样本长度下限/置信坍缩边界"做成一等前置门：T 不足时体检直接判"证据不足、不可结论"，而非给出虚假的红/绿。

8. **体检应与成本/容量审计串联，而非孤立统计闸门（来自 §8 漏点）**：DSR/PBO/bootstrap 都假设收益序列是"真实可实现收益"。一个 DSR 通过的策略可能仅因换手成本/市场冲击在回测中被低估而虚高（平方根冲击律本身在 AQR 等处存在争议）。"统计上真实"不等于"成本现实下盈利"——体检前置应叠加成本/容量审计。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意，不接线到现有代码。

### 6.1 试验账本（N 累计为系统不变量，但标注为"可观测下界"）

```text
TrialLedger (append-only, 不可由用户事后改小)
  trial_id
  strategy_family_id     # 用于按相关性聚类估"有效独立 N"
  trigger                # param_sweep | feature_add | feature_drop | rerun | manual
  config_hash            # 唯一标识一次试验
  returns_ref            # 指向该试验的收益序列（版本化）
  created_by             # human | agent
  created_at
# 注：N_observed = count(*) 是真值 N 的【下界】，非真值
#   - agent 单次推理内隐式假设无法埋点捕获
#   - 跨会话/跨用户同因子族高度相关 → 有效独立 N << N_observed
#   - 有效 N 需相关阵聚类，而相关阵需这些策略同期回测 → 先有鸡先有蛋
```

### 6.2 体检输出：通缩区间 + 证据包（非单点裁决）

```yaml
# --- 不输出一个数字，输出一个证据包 ---
overfit_check:
  sample_guard:
    T: 380
    min_T_required: 504            # 短样本下限；不足则 verdict=insufficient_evidence
    moment_estimates_reliable: false   # T 小 → γ̂3/γ̂4 方差爆炸，DSR 分母不可信
  effective_N:
    observed_lower_bound: 142      # TrialLedger 计数，明确为下界
    effective_independent: { low: 9, high: 28 }   # ONC/层次聚类区间，非单点
  cross_sectional_var_V: { low: 0.31, high: 0.58 }
  dsr:
    optimistic: 0.71               # 用 V_low, N_low → SR0 偏低 → 通缩不足风险
    conservative: 0.42             # 用 V_high, N_high → SR0 偏高 → 过度通缩风险
    note: "误差符号取决于 N 与 V 的真实值；我们偏保守"
  pbo_cscv:
    pbo: 0.34
    performance_degradation_slope: -0.6
    probability_of_loss: 0.41
    caveat: "CSCV 假设时间子块近似可交换；对低频长持仓/regime 漂移敏感"
  bootstrap_sharpe_ci:               # studentized block bootstrap，对自相关/肥尾稳健
    ci_95: [0.1, 1.3]
  triangulation:
    all_agree_positive: false        # 三支未同向 → 不放行
    most_conservative_wins: true
  verdict: { color: yellow, reason: "三支分歧 + 短样本；DSR 乐观但 bootstrap CI 跨零" }
```

### 6.3 多证据三角放行逻辑（示意，非生产代码）

```text
function gate(strategy):
    if T < min_T_required:                  return INSUFFICIENT_EVIDENCE   # §5.7 短样本边界
    if not cost_capacity_audit_passed:      return BLOCKED_ON_COST         # §5.8 成本串联
    dsr_range   = deflated_sharpe_interval(strategy, effective_N_range, V_range)
    pbo         = pbo_via_cscv(strategy)     # CPCV 候选；低频时报告稳定性而非单值
    boot_ci     = studentized_block_bootstrap_sharpe_ci(strategy)
    # 三支同向才放行；矛盾取最保守；DSR 永不单点否决
    if all_positive(dsr_range.conservative, pbo, boot_ci):  return GREEN
    if any_strongly_negative(...):                          return RED
    return YELLOW(evidence_pack, human_economic_judgment_required)
# 警告：DSR 与 Harvey-Liu haircut 不可对同一组 N 双重计数（§7 漏点）——二者只取其一作多重检验校正
```

### 6.4 不可变体检契约（防体检被二次过拟合）

```yaml
overfit_contract:
  version: v1                        # 单一版本化契约
  immutable_fields: [S, N_accrual_rule, thresholds, backtest_engine_pin]
  user_can_retune: false             # 用户不可反复改 N/阈值直到通过
  on_change:
    - append_audit_log
    - trigger_retro_recheck_of_all_passed_strategies   # 修改即回溯重检历史放行
# 未解治理悖论（§8）：agent 自主迭代必然观察体检反馈（哪怕只是红/黄/绿），
#   任何反馈回路都构成对体检的隐式优化 → agent 对闸门过拟合。
#   真正的不可变契约要求 agent 对结果"盲"，又与"agent 出工程"的自主迭代冲突。
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下**原样保留**对抗核查的限定词（夸大/争议/二手/不可外推/撤稿等）。

### 7.1 须降级的核心定位（中严重度）

- **把 DSR 当"硬闸"——【中；硬闸定位被夸大，与自承的 N/V 稳健性缺失自相矛盾】**：已证实 DSR 本质是"显著性阈值的标度/标准化修正"（Wikipedia/原论文均确认：减去 SR0 再除以标准误），机理描述正确。但研究自承"原论文与维基均未给出对 V、N 误设的稳健性分析"——经核实属实，维基对 N/V 误估敏感性仅"极少讨论（minimal discussion）"。把一个其正确性完全押在两个公认难估、误差符号双向的量（有效独立 N、横截面方差 V）上的指标设为"硬闸"，缺乏稳健性背书。summary/design_directions 顶部"升级为硬闸"的表述与 pitfalls 自己点破的隐患存在**内部张力**——硬闸定位被夸大，应明确降级为"带敏感性区间的多证据三角中的一支，不可单点裁决"。

- **CPCV 必须用于中低频长持仓——【中；不可外推：优势仅在 Heston 合成受控环境证实】**：CPCV 相对 walk-forward 更优的唯一系统性证据来自 Arian-Norouzi-Seco 的"合成受控环境"（Heston 随机波动率模型生成数据）——这是受控仿真而非真实市场外推。同一文献语境也承认"walk-forward 仍是真实交易仿真的行业标准"。把"在合成数据里 PBO/DSR 更优"直接外推为"中低频实盘必须用 CPCV"属**外推过度**。CPCV 还假设时间子块近似可交换，对强记忆/regime 漂移/低频长持仓敏感（研究自己在 pitfalls 承认），而合成 Heston 数据恰恰不含真实 regime 漂移。应降级为"CPCV 是候选方法，但其相对 walk-forward 的优势尚未在真实低频数据上验证"。URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4686376

- **不同回测引擎口径会让 DSR/PBO 结论漂移——【中；选择性放大，原文明确不翻转 Sharpe 符号】**：arXiv 2603.20319（Implementation Risk in Portfolio Backtesting）确实存在，且高换手轮动策略在最重成本档下确达 3.71% 总收益分歧——**但同一论文明确结论**：(a) 零成本下五个引擎完全一致；(b) 15 个基准中 12 个分歧 <0.75 个百分点；(c) 引擎选择在样本内"不会翻转 Sharpe 符号"。研究把它当成"过拟合体检输入会因引擎漂移而使结论不稳"的强论据，属**夸大**：实证证据显示引擎差异主要在高换手 + 高成本的边角，且不改变 Sharpe 显著性方向。中低频长持仓产品恰恰是低换手区，受影响更小。应降级为"仅在高换手/高成本子集需固定引擎口径"的弱主张。URL: https://arxiv.org/abs/2603.20319

### 7.2 低严重度降权（措辞/归属/叙事层面）

- **"过拟合普遍是真问题但几乎全是噪声被夸大"二元叙事——【低；二手化/夸大，实为口径差异 + 识别不可能性】**：两侧数字均已核实（HXZ：65% 过不了 t>1.96 即约 35% 复现；JKP：贝叶斯层级法下大多数因子可复现）。但把二者描述为干净的"噪声派 vs 真实派"对峙是**过度简化**：(a) JKP 明确将 HXZ 的低复现率主要归因于其"剔除微盘股 + 市值加权"的方法选择，而非纯粹噪声判断；(b) Chen-Zimmermann 进一步指出发表偏误下 t-hurdle 调整本身不可识别——"数据对 t 门槛该升该降几乎无话可说"，这削弱的是 HLZ"需提高 t 门槛"一侧而非简单支持任一派。研究把一个主要是"微盘加权口径差异 + 识别不可能性"的技术分歧，包装成关于"金融发现真假"的二元叙事，属**二手化/夸大**。URL: https://pubsonline.informs.org/doi/10.1287/mnsc.2023.03083

- **SR 26-2 作为单用户平台"硬闸分级"的"直接监管类比"——【低；引用卫生差 + 类比强度被夸大】**：SR 26-2 本身已核实为真：2026-04-17 由 Fed/OCC/FDIC 联合发布、替代 SR 11-7、转向风险相称的判断式治理、明确把生成式/agentic AI 排除在范围外——研究的事实陈述全部正确。但研究引用的是**二手 Medium 博客**（the-investors-handbook）而非一手联邦储备来源（federalreserve.gov/.../SR2602.htm 存在）。此外 SR 26-2 主要面向 >300 亿美元资产银行的监管框架，把它当作单用户量化平台"硬闸分级"的"直接监管类比"属**类比放大**——监管语境的 effective challenge（独立人员复核）与产品内自动闸门不是一回事。事实无误，但引用卫生差 + 类比强度被夸大。一手 URL: https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm

- **MinBTL 量级公式 "约 ∝ (E[max]/年化)⁻²"——【低；转写不严谨，核心论断成立】**：方向正确且原 AMS 2014 论文（Notices 61(5):458–471）无撤稿/争议——5 年数据下试 >45 个独立配置几乎必然产出 IS Sharpe=1/OOS=0 的假策略，这是确证的。但研究给出的量级公式表述含混、与原文 Figure 2 的"保持 E[max Sharpe] 固定为 1 所需年数随试验数增长"口径对不齐，属对原始关系的**转写不严谨**（近似 √(2 ln N) 来自极值理论，而非如 summary 所暗示直接出自 deflated-sharpe 论文式(1)）。核心论断成立，仅公式转写需校正。

### 7.3 漏点（asserted-away 被一笔带过，非错误而是遗漏）

- **有效独立 N 的可审计累计在 agent 自动搜索下是根本性不可观测问题**：研究主张"平台层自动累计 agent 产生的全部试验 N"，但未触及 (a) LLM-agent 在单次推理内部隐式尝试的多个假设无法被埋点捕获；(b) 跨会话、跨用户的策略族高度相关（同一因子库的变体），按聚类估有效 N 仍需一个相关阵，而该相关阵本身需要这些策略同期回测才能估——存在**先有鸡还是先有蛋的循环**。这是把第三定律落地为系统不变量的最大未解工程难题，研究只给了愿景没给可行性论证。

- **短样本（A股到 paper / 加密历史短）下整套体检可能集体失效**：研究把 DSR/PSR/PBO/bootstrap 全部建立在"有足够长、足够干净的收益序列"上，但完全没讨论本产品的核心约束——T 本身就小。T 小时 DSR 分母的偏度/峰度四阶矩修正本身就不可靠（研究 pitfalls 提了肥尾，但**没提 T 小导致 γ̂₃/γ̂₄ 估计方差爆炸**），PBO 的 C(S, S/2) 组合在短序列下子块数 S 受限、统计功效极低。短样本下整套体检可能集体失效，这个**对本产品最致命的角度被一笔带过**。

- **缺少"闸门通过后仍过拟合"（假阳放行）的成本-收益量化 + 术语错置**：研究反复强调"偏保守、宁可错杀"，但对中低频弱信号策略，错杀的经济代价可能远高于偶尔放行一个假策略——尤其在 paper/模拟盘阶段放行的代价极低。研究没有把闸门阈值与"当前生命周期阶段的实际损失函数"挂钩，一刀切的保守主义可能系统性扼杀真实但微弱的 alpha。**（另：研究术语里把"错杀真策略"误写成 Type II；错杀应为 Type I。）**

- **DSR 与 Harvey-Liu haircut 并用的双重计数（double-counting）风险**：二者被并列为互补工具，但研究未指出在多重检验校正上可能**双重计数**：若先用 DSR 按 N 通缩、再用 HL haircut 按同一组 N 个检验折扣，等于对同一选择偏差惩罚两次，导致**过度通缩（Type I 错杀）**。两套多重检验框架如何组合、是否可叠加，是落地时绕不开但研究未触及的口径问题。

- **所有指标假设"真实可实现收益"，未把交易成本/冲击/容量纳入体检前置**：一个 IS Sharpe 高、DSR 也通过的策略，可能仅仅因为换手成本/冲击在回测中被低估而虚高——而平方根冲击律本身在 AQR 等处存在争议（冲击模型选择会显著改变净收益）。过拟合体检放行的"统计上真实"策略，可能在成本现实下依然亏损。体检应与成本/容量审计**串联**，而非孤立的统计闸门。

- **"不可变体检契约"与"agent 自主迭代必然观察反馈"的治理悖论未被识别**：研究把体检参数设为不可由用户事后调的不可变契约作为防二次过拟合的设计，但没讨论这与 agent 自主迭代的根本张力：如果 agent 被授权自动改进策略，它必然需要观察体检反馈——而任何反馈回路（哪怕只是红/黄/绿）都构成对体检的隐式优化，等于让 agent 对闸门本身过拟合。真正的不可变契约要求 agent 对体检结果"盲"，但这又与"agent 出工程"的自主迭代定位冲突。这个治理悖论未被识别。

### 7.4 撤稿/争议状态核查（无伪造引用）

- **arXiv 2512.11913（拥挤缩量）已撤稿**：未被研究引用——研究未使用该雷区来源，无需处理。URL: https://arxiv.org/abs/2512.11913
- **Bailey/Borwein/López de Prado/Zhu 四篇核心论文（FST、DSR、PBO、Pseudo-Mathematics AMS 2014）**：无撤稿、无重大学术反驳；经多源核实均为正式发表，公式与归属准确。
- **MlFinLab（Hudson & Thames）许可状态**：核实属实——已闭源/商业化，研究的"需核对当前许可"警示恰当，无夸大。URL: https://github.com/hudson-and-thames/mlfinlab/blob/master/LICENSE.txt

> 综合裁决（保留对抗核查原话）：研究主体扎实、机理描述准确、引用大多可核验，公式与论文归属均经一手或权威二手来源证实，无撤稿、无伪造引用；难得地在 pitfalls 里自己点破了若干最大隐患（DSR 是阈值校正非夏普修复、N/V 误差符号双向、CSCV 可交换性假设对低频敏感、JKP 反证"几乎全噪声"被夸大）。作为方法论蓝图可信度高（约 80% 论断稳健），**但绝不能据此把任何单一指标设为单点否决式硬闸**——应严格落实其自身建议的"多证据三角 + 通缩区间 + 人类经济判断"，并补做短样本失效边界与成本/容量串联的前置审计。

---

## 8. 开放问题

1. **有效独立 N 的鸡生蛋循环如何破**：按相关性聚类估"有效独立试验数"需要一个跨策略相关阵，而该相关阵又需这些策略同期回测才能估。是否接受"N_observed 作为下界 + 显式标注"，还是引入近似（如基于 config_hash 距离的代理相关性）？这是把第三定律落地为系统不变量的最大未解工程难题。

2. **agent 单次推理内的隐式试验如何计入 N**：LLM-agent 在一次推理内部尝试的多个假设无法埋点捕获，N_observed 系统性偏低 → DSR/MinBTL 可能形同虚设。是否需要约束 agent 的搜索协议本身（每次假设必须显式提交回测）以使试验可观测？

3. **短样本失效边界的量化阈值**：A股到 paper、加密历史短，T 多小时四阶矩修正与 C(S, S/2) 组合 CV 集体失效？需要一个明确的"样本长度下限/置信坍缩边界"，T 不足时判"证据不足"而非给虚假红/绿。当前无定量阈值。

4. **DSR 与 Harvey-Liu haircut 的组合口径**：两套多重检验框架是否可叠加？如何避免对同一组 N 个检验双重计数导致过度通缩（Type I 错杀）？落地时绕不开但研究未触及。

5. **闸门阈值与生命周期阶段损失函数的挂钩**：paper/模拟盘阶段放行假策略代价极低，实盘阶段错杀真实弱信号 alpha 代价高。如何把闸门阈值显式挂到"当前阶段的实际损失函数"，而非一刀切保守主义？

6. **不可变契约 vs agent 自主迭代的治理悖论**：真正的不可变契约要求 agent 对体检结果"盲"，但 agent 自主改进策略必然观察反馈（哪怕只是红/黄/绿），任何反馈回路都构成对闸门的隐式过拟合。如何在"agent 出工程"与"体检不可被过拟合"之间设计？

7. **体检与成本/容量审计的串联次序**：统计体检与成本/冲击/容量审计谁先谁后、如何联动？平方根冲击律选择本身有争议，成本模型的不确定性如何并入体检证据包？

---

## 9. 参考文献（URL）

**核心论文（Bailey & López de Prado 系）**
- The Deflated Sharpe Ratio（J. Portfolio Management 2014）：https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- The Probability of Backtest Overfitting（J. Computational Finance 2015）：https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- Pseudo-Mathematics and Financial Charlatanism（Notices of the AMS 2014, 61(5):458–471）：https://www.ams.org/notices/201405/rnoti-p458.pdf
- The Sharpe Ratio Efficient Frontier（J. Risk 2012, 15(2)）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643
- AFML 工作流 / Backtesting via Synthetic Data（CPCV）综述入口：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2606462

**稳健推断与多重检验**
- Robust Performance Hypothesis Testing with the Sharpe Ratio（Ledoit & Wolf 2008）：https://www.econ.uzh.ch/apps/workingpapers/wp/iewwp320.pdf
- Backtesting（Harvey & Liu 2015/2020）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2345489 ；官方代码 https://people.duke.edu/~charvey/backtesting/
- A Bayesian Approach to Measurement of Backtest Overfitting（Risks 2021, 9(1):18）：https://www.mdpi.com/2227-9091/9/1/18

**复现率之争（并陈两侧）**
- Is There a Replication Crisis in Finance?（Jensen-Kelly-Pedersen, JF 2023）：https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249
- 发表偏误下 t-hurdle 不可识别（Chen & Zimmermann, Management Science 2023）：https://pubsonline.informs.org/doi/10.1287/mnsc.2023.03083

**机构标准与实践**
- Federal Reserve SR 11-7（Model Risk Management）：https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- SR 26-2（Fed/OCC/FDIC, 2026-04-17，一手）：https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm
- NIST AI RMF 1.0（AI 100-1）：https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf
- Seven Sins of Quantitative Investing / 10 Reasons ML Funds Fail：https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf

**开源/工具实现（核对口径用）**
- MlFinLab backtest_statistics（已商业化，须核对 license）：https://hudsonthames.org/mlfinlab/ ；license https://github.com/hudson-and-thames/mlfinlab/blob/master/LICENSE.txt
- pypbo（AGPL-3.0，参考实现非生产依赖）：https://github.com/esvhd/pypbo
- rubenbriones/Probabilistic-Sharpe-Ratio（PSR/DSR 轻量实现）：https://github.com/rubenbriones/Probabilistic-Sharpe-Ratio
- arch（Kevin Sheppard，stationary/circular block bootstrap）：https://arch.readthedocs.io/en/stable/bootstrap/confidence-intervals.html
- R quantstrat: SharpeRatio.deflated / SharpeRatio.haircut：https://rdrr.io/github/braverock/quantstrat/man/SharpeRatio.deflated.html
- CRAN pbo 包 vignette（PBO/CSCV）：https://cran.r-project.org/web/packages/pbo/vignettes/pbo.html

**对抗核查相关（降权/争议来源）**
- Implementation Risk in Portfolio Backtesting（arXiv 2603.20319，结论被选择性放大）：https://arxiv.org/abs/2603.20319
- CPCV vs walk-forward（Arian-Norouzi-Seco，优势仅 Heston 合成环境）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4686376
- arXiv 2512.11913（已撤稿，未被引用，仅备查）：https://arxiv.org/abs/2512.11913
