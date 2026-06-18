# 25 · DL 因子库（Autoencoder/FactorVAE/AlphaNet）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 E

## 1. 一句话定位

DL 隐因子模型是"让网络自己找因子"的学术前沿，但对一个**非技术用户、资产无关、中低频**的 Agent OS 而言，它应当是**可选的、被隔离的模块——而不是脊柱**：DL 因子只能作为**候选信号**进入，必须通过与任何手工因子**完全相同**的 PIT / 样本外 / 成本 / CSCV-PBO 闸门，永远不享有黑箱特权；以"带无套利约束"的 IPCA/CAE 作保守默认，VAE/Transformer 重型机器作显式 opt-in 高级轨。

## 2. 前沿 SOTA 与代表系统

两条谱系并立。**资产定价谱系**追求无套利纪律（线性 IPCA → 条件自编码器 CAE → GAN/SDF），**ML 预测谱系**在 A 股实务最强（AlphaNet、FactorVAE 族）。

| 系统 / 代表作 | 它是什么 | 对本项目的意义 |
|---|---|---|
| **条件自编码器 CAE — Gu, Kelly, Xiu (2021)** | 双塔自编码器：β 网络把个股 characteristics 非线性映射成因子载荷，factor 网络把组合收益映射成少量隐因子（1–6 个，甜点约 3–5），收益重建为 β×factor 并**内嵌无套利限制**。报告 OOS R² 高于 Fama-French/IPCA，3 因子 SR『约 2.16 等权 / 约 0.92 市值加权』。 | "AE 资产定价"卡应对标的参考模型——但 SR 数字属**未独立核实**（见第 7 节），且 Nechvátalová 复制显示去微盘+计成本后利润"大幅下降"。 |
| **IPCA — 工具化主成分分析 (Kelly, Pruitt, Su 2019)** | CAE 的线性祖先/基线：用 characteristics 工具化的时变载荷，ALS 变体估计；快、能处理非平衡面板、有官方开源包。 | **保守默认**——CAE 必须净成本 OOS 击败 IPCA 才配得上其复杂度。注意 IPCA 自身亦有公开批评（见第 8 节）。 |
| **Deep Learning in Asset Pricing — Chen, Pelger, Zhu** | 用神经网把无套利矩条件**直接当损失**估计 SDF；对抗式 conditional 网络构造最难定价的测试资产（GAN 结构）+ LSTM 概括宏观状态。报告 OOS 最优组合 SR 约 2.1（注意与样本内 SR 约 2.6 区分）。 | "无套利约束当损失能纪律化模型"——值得移植进 OS 目标函数。venue 应锁定 **Management Science 70(2), 2024**（见第 7 节引用风险）。 |
| **FactorVAE — Duan et al. (AAAI 2022)** | 概率动态因子模型 = 动态因子模型 + VAE；同时给期望收益**与方差（风险）**。prior-posterior 训练：encoder **仅在训练时**看未来收益，推理只跑 predictor+decoder。在 A 股上以 rank IC / ICIR 评估，已并入 microsoft qlib。 | 那条**承重的防泄露边界**——自动化管线最易在此悄悄造出 look-ahead Sharpe。作者署名须更正（见第 7 节）。 |
| **HireVAE / RVRAE / GraphVAE（VAE 因子后续）** | FactorVAE 的继任：HireVAE (IJCAI 2023) 加分层市场/个股隐空间+regime-switch 解码器做在线适配；RVRAE 用变分循环自编码器；GraphVAE (CIKM 2024) 注入动态个股关系。 | 表明 VAE 因子是活跃前沿，但全部针对股票横截面，**对 crypto 可外推性未经证明**（见第 8 节）。 |
| **AlphaNet / AlphaNetV4 — 华泰证券（中国卖方）** | A 股 DL alpha 行业标准。自定义"算子"层（correlation/covariance/decaylinear 等）作用于个股量价特征矩阵端到端抽特征；V4 加 Bi-LSTM + Transformer + Spearman 相关 dropout。 | 实务影响大，但**复现/泄露文档稀疏**；其"7–10%"数字是**对前代的相对改进、非绝对超额**（见第 7 节重大降权）。 |

## 3. 关键论文（每条带 URL）

1. **Autoencoder Asset Pricing Models（Gu, Kelly, Xiu, J. Econometrics 222(1), 2021）** — 奠基条件自编码器：非线性 characteristic 条件 β + 隐因子 + 无套利；OOS 定价误差远小于 Fama-French/IPCA。"AE 资产定价"卡应镜像此模型。（注：3 因子 SR『约 2.16 等权 / 约 0.92 市值加权』本环节**未能对一手论文独立核实**，见第 7 节——反而强化了"headline Sharpe 多为毛成本/微盘重"的本研究自身告诫。）
   - SSRN 3335536 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3335536
2. **Autoencoder asset pricing models and economic restrictions — international evidence（Nechvátalová, 2025）** — **批评/复制（承重反例）**。在美国+国际市场复制 CAE，发现剔除微盘/低流动性个股并计入交易成本后，多空利润"大幅下降"。直接证据：headline CAE Sharpe **撑不过**机构 OS 必须执行的"可交易、计成本"真实口径——正是本项目 A股到paper / crypto到Binance 的目标 regime。
   - IES WP 2024-26 — https://ies.fsv.cuni.cz/sites/default/files/uploads/files/wp_2024_26_nechvatalova.pdf
3. **Instrumented Principal Component Analysis（Kelly, Pruitt, Su, JFE 134(3), 2019）** — characteristic 工具化时变载荷的线性隐因子模型；有纪律、快、可解释的基线。若 DL 因子模型净成本 OOS 不能击败 IPCA，其额外复杂度就不成立。
   - SSRN 2983919 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2983919
4. **Deep Learning in Asset Pricing（Chen, Pelger, Zhu, Management Science 70(2), 2024）** — 把无套利条件**直接当训练判据**能纪律化模型：仅在无套利矩上估计，比最大化解释方差得到更好的 OOS 解释力。经济约束才是 DL 因子稳健的原因，值得移植进 OS 目标。
   - arXiv:1904.00745 — https://arxiv.org/abs/1904.00745 ；DOI — https://pubsonline.informs.org/doi/10.1287/mnsc.2023.4695
5. **FactorVAE（Duan et al., Proc. AAAI 36(4):4468–4476, 2022）** — VAE 概率因子模型，给收益与方差；prior-posterior 设计意味着 encoder **仅训练时**消费未来收益、推理用 predictor+decoder——这是自动化管线必须强制、否则悄悄产出 look-ahead Sharpe 的承重防泄露边界。（注：作者列见第 7 节更正。）
   - AAAI — https://ojs.aaai.org/index.php/AAAI/article/view/20369
6. **The Virtue of Complexity in Return Prediction（Kelly, Malamud, Zhou, J. Finance 79(1), 2024）** — 理论+证据：过参数化（"复杂"）模型即便极少正则化也提高 OOS R² 与组合 Sharpe，挑战"从简"先验。**但远比本研究所述更受争议**（见第 7 节降权与撤稿/争议表）：Nagel 2025 证其约化为波动率择时的动量、Buncic 2025 指其为零截距限制+异常聚合方案的人为产物。
   - NBER w30217 — https://www.nber.org/papers/w30217
7. **Does Academic Research Destroy Stock Return Predictability?（McLean & Pontiff, J. Finance 71(1), 2016）** — alpha 衰减实证锚：**精确数字是样本外低 26% / 发表后低 58%**（发表增量约 32%），**非**本研究笼统的"约 35–50%"（见第 7 节）。任何 DL 挖出的因子的实盘 alpha 须假定显著低于回测。
   - 论文 PDF — https://www.fmg.ac.uk/sites/default/files/2020-08/Jeffrey-Pontiff.pdf
8. **Open Source Cross-Sectional Asset Pricing（Chen & Zimmermann, Critical Finance Review, 2022）** — 复现基准：200+ characteristic 排序预测因子带代码，约 98% 原显著信号可复制 (t>1.96)。可作 (a) PIT 干净候选信号宇宙、(b) 已知因子重叠核查。（注：Chen-Zimmermann 本身论点**与强衰减叙事相左**，见第 7 节内部张力。）
   - openassetpricing.com — https://www.openassetpricing.com/

## 4. 机构最佳实践 / 标准

- **模型风险治理（监管口径——须更新）**：把每个 DL 因子模型当 SR 11-7 意义下的"模型"——独立验证、概念健全性复核、持续性能监控、限制文档化；ML/DL 模型特别被点名加重可解释性、偏差、验证频率负担。**重大降权**：SR 11-7 已于 **2026-04-17 被跨机构指引 SR 26-2 取代**，最大变化恰是**取消默认年度重验、改为按模型重要性的风险化监督**，并将"确定性规则化流程/软件"排除出模型定义——本研究承重的"至少每年验证一次"恰是新指引退役的旧惯例。治理脚手架应**改锚 SR 26-2 + NIST AI RMF**，且 SR 26-2 的风险化（非日历化）哲学**更贴合**自治 Agent OS。
  - SR 11-7（旧，仍可作概念参考） — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
  - SR 26-2（现行，2026-04-17 生效） — https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm
- **NIST AI RMF 1.0 生命周期映射**：把 DL 因子生命周期（数据/训练/部署/监控/退役）映射到 GOVERN/MAP/MEASURE/MANAGE——尤其 MEASURE（漂移、鲁棒性、可解释性）与 MANAGE（因子衰减时的停用触发）。给不透明模型的自治 Agent 一个监管可识别的脚手架。
  - https://www.nist.gov/itl/ai-risk-management-framework
- **事后可解释性是接受不透明因子模型的事实标准**：SHAP / permutation importance / attention 归因覆盖 characteristics，加经济常识核查（模型是否在动量/价值/盈利/流动性方向上如理论预期载荷）。经验上可恢复 5–6 个可解释组（价值、动量、盈利、投资、摩擦、无形）。**但事后可解释 ≠ 因果理解**（见第 7 节陷阱）。
  - https://www.sciencedirect.com/science/article/pii/S1544612325017738
- **复现 + 防泄露纪律**：严格 PIT、带显式 train_fraction 的 walk-forward/扩展窗 OOS，并文档化"任何未来信息（VAE prior-posterior）仅限训练、推理结构性不可达"。把"1998–2016 严格 PIT 无泄露延伸到 2016–2024"这类复制研究作为 OS 应自动化的金标准。
  - https://arxiv.org/abs/2403.06779

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

1. **保持因子库"纯净"——DL 因子是候选信号、永不享黑箱特权**：CAE/IPCA/FactorVAE/AlphaNet 只输出每股暴露或期望收益，必须过与手工因子**完全相同**的闸门——PIT 数据、walk-forward OOS、交易成本 + 流动性/微盘过滤、CSCV/PBO 过拟合核查。Nechvátalová 复制是警钟：任何只在毛成本+微盘上发光的东西，必须在用户看到 Sharpe **之前**自动拒绝。
2. **默认落在"低复杂度纪律端"，复杂度是 Agent 须论证的显式 opt-in**：概念阶梯 IPCA（线性、可解释）→ CAE（非线性 β、无套利）→ VAE/GAN/Transformer（概率、风险感知、最重）。Agent 从 IPCA/CAE 起步，只有能证明复杂模型在 OOS **净成本**上击败简单模型时才升级——把"复杂度之德 vs 简单胜复杂"作为**真实争议选项**呈现，而非默认拍板（且须明确告知该争议**更偏向被质疑**，见第 7 节）。
3. **把无套利/经济约束做成一等目标**：CPZ（无套利矩当损失能纪律化）与 GKX 内嵌无套利，是 DL 因子之所以泛化的概念原因。OS 应偏好目标经济受约束的因子模型，并让非技术经济学家用户用经济先验（哪些 characteristic 族、哪些约束）操舵，Agent 处理工程。
4. **把训练时未来信息当管线强制执行的结构性防泄露边界、而非信任的约定**：FactorVAE prior-posterior 很强但正是自动化管线悄悄造 look-ahead alpha 之处。OS 应让推理期使用未来数据**架构上不可能**，并为每个训练因子产出防泄露审计产物。
5. **用 SR 26-2 / NIST-AI-RMF 形状的治理外壳包裹 DL 因子，自动为非技术用户生成**：自动模型卡（架构、因子数、训练窗、重训成本/节奏）、可解释性面板（SHAP/permutation + 与已知因子的经济方向核查）、带显式停用触发的漂移/衰减监控（锚定 McLean-Pontiff 式衰减预期），以及对 Chen-Zimmermann 已知因子动物园的重叠测试——让用户被告知"这是重新发现的动量"，而非被当成新颖卖。**注意治理锚点用现行 SR 26-2（风险化、非年度化），而非已退役的 SR 11-7 年度惯例。**
6. **把重训成本、不稳定性、regime 漂移当显式产品面**：DL 因子需周期重训、对 seed/初始化敏感、随拥挤衰减。OS 应暴露重训节奏、按 seed 集成求稳、容量/拥挤感知；中低频定位（A股到paper、crypto到Binance）应回避任何依赖 HFT 级特征新鲜度的架构。
7. **治理产物本身的成本须计量（漏点补强）**：每个训练因子自动生成 SHAP/permutation 面板、泄露审计、漂移监控、重叠测试——对单用户、大宇宙、每次重训，这份计算+维护负担可能**吞掉因子边际价值**。把"治理外壳是否在本产品规模下负担得起"作为显式权衡，深网大宇宙的 SHAP 尤其昂贵。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

DL 因子作为"候选信号"接入因子库的概念边界（示意，不接线到现有代码）：

```text
DLFactorModule  （隔离 · opt-in · 非脊柱）
├── 复杂度阶梯（默认低端，升级须 Agent 论证净成本 OOS 胜出）
│     IPCA(线性) ─► CAE(无套利 β) ─► VAE/GAN/Transformer(概率,最重)
├── 训练边界（结构性，非约定）
│     train: encoder 可见 future_returns（FactorVAE prior-posterior）
│     infer: 仅 predictor + decoder —— future 信息架构上不可达
└── 输出 = 候选信号（per-stock exposure / expected return）
      └──► 进入与手工因子【完全相同】的闸门，无黑箱特权
```

通用闸门（DL 因子与手工因子共用同一条管线，示意伪代码）：

```python
def admit_factor(signal, *, asset_class):
    # 任何因子（含 DL）必须过同一闸门，先于用户看到任何 Sharpe
    assert signal.is_point_in_time()                 # PIT
    oos = walk_forward(signal, train_fraction=...)   # 扩展窗/purged
    net = apply_costs(oos, asset_class)              # 成本 + 流动性/微盘过滤
    if net.universe_excludes_microcap is False:
        reject("仅在微盘/毛成本发光 —— Nechvátalová 反例，自动拒绝")
    pbo = cscv_pbo(net)                              # 过拟合概率
    overlap = known_factor_overlap(signal, zoo="Chen-Zimmermann")
    leak = leakage_audit(signal)                     # 推理期 future 不可达?
    return Verdict(net, pbo, overlap, leak)          # 全部通过才录用
```

DL 因子模型卡 schema 草图（SR 26-2 风险化治理，示意；注意非年度化）：

```yaml
dl_factor_model_card:
  model_id: conditional_autoencoder        # 或 ipca / factor_vae / alphanet
  complexity_tier: CAE                      # ladder: IPCA < CAE < VAE/GAN/Transformer
  factor_count: 3                           # 甜点约 3–5
  training_window: "2010-01..2018-12 (PIT)"
  retrain: { cadence: "risk_based", cost_note: "深网 SHAP 每重训昂贵" }
  no_arbitrage_objective: true              # CPZ/GKX 经济约束当损失
  leakage_boundary:
    train_uses_future_returns: true         # FactorVAE 合法
    inference_uses_future: false            # 架构上不可达 —— 强制审计
  interpretability: [shap, permutation_importance, economic_direction_check]
  decay_monitor:
    anchor: "McLean-Pontiff 26% OOS / 58% post-publication"
    retire_trigger: "净 alpha 跌破阈值 或 与已知因子重叠过高"
  known_factor_overlap: "vs Chen-Zimmermann zoo —— 防把重命名 beta 当新 alpha"
  governance_anchor: "SR 26-2 (2026-04-17, 风险化非年度) + NIST AI RMF"
  headline_stat_policy: "毛成本/微盘 Sharpe 不得直呈用户；只呈净成本可交易口径"
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下原样保留对抗核查的限定词（夸大 / 争议 / 二手未核实 / 不可外推 / 误读 / 过时 / 内部张力等）。
> 总评：核心论点（DL 因子作候选信号过同一成本/PIT/CSCV 闸门、永不黑箱特权）正确，且被所验证据**强化而非削弱**。但若干具体数字与框架被夸大、二手或过时，**产品不得按原样把这些未核实/过时数字呈现给非技术用户**。

- **【high · 误读相对改进为绝对超额】** AlphaNet/AlphaNetV4『约 7–10% 年化超额收益』是**误读一手来源**。arXiv 2411.04409 说的是 V4 相对**前代 AlphaNet** "annualized excess return of more than 7%–10%"——即对前一版本的 **7–10% 改进**，**非**对市场/基准的 7–10% 绝对超额。本研究把相对改进数字重述为绝对 alpha，**抬高了一个其自身就标注'复现/泄露文档稀疏'的卖方数字**。应改述为"V4 报告对前代的改进；绝对净成本 alpha 未核实"。
- **【high · 过时 / 已被取代】** 把 DL 因子裹进『SR 11-7 治理外壳』、并把『高重要性模型至少每年验证一次』当**现行**机构实践，**截至 2026-06-15 已过时**。SR 11-7 已于 **2026-04-17 被跨机构指引 SR 26-2 取代**（Fed/OCC/FDIC），最大运营变化正是**移除默认年度重验、改为按模型重要性的风险化监督**，并把"确定性规则化流程/软件"排除出模型定义。本研究承重的『至少每年』恰是新指引退役的惯例。治理脚手架应改锚 SR 26-2 (+NIST AI RMF)。另注：『年度』节奏始终是行业惯例/实践，**从来不是**原则导向的 SR 11-7 的字面文本。
- **【medium · 争议被低估，框架显得过于平衡】** "复杂度之德 vs 简单胜复杂"被描述为『真实、有争议的选择，而非默认』，反方仅被说成『某些 Finance Research Letters 工作发现简单网络匹敌 Transformer』——**低估了反驳的力度与具体性**。严肃具名批评：**Nagel (2025,『Seemingly Virtuous Complexity』)** 证明该"上千预测因子"策略在 random-Fourier-feature 数学下**约化为波动率择时的动量策略**；**Buncic (2025,『Simplified』)** 证明 VoC 实证结果是**两个实现选择（零截距限制 + 非常规绩效聚合方案）的人为产物**，机械地拖累简单模型。报道称『至少六篇』论文（含 Oxford、Stanford、Stockholm、一项 Fed FEDS 汇率研究）质疑该发现。Kelly-Malamud 已回击（effective vs nominal complexity），故两向皆未定论——但本研究含糊的单句框架**不充分**，须把波动率择时人为产物与设计选择两类具名批评浮现出来。
- **【medium · 不精确 / 分解混淆】** McLean-Pontiff alpha 衰减『约 35–50% 发表后』（及『约 50% 合并 OOS+发表衰减』）**分解混淆**。论文实际 headline 是**样本外低 26%**（post-sample、pre-publication）与**发表后低 58%**，发表特定增量约 32%（58%−26%）。本研究的『约 35–50%』带与『约 50% 合并』表述**与任一数字都不干净对应**；正确锚点是 **26% OOS 与 58% 发表后**。
- **【medium · 未独立核实】** 归于 Gu-Kelly-Xiu 的 headline CAE Sharpe『约 2.16 等权 / 约 0.92 市值加权』，本次复核**未能对一手 GKX (J. Econometrics 2021) 核实**。GKX 摘要/综述确认 CAE 在 R² 与 Sharpe 上胜 Fama-French，但**无法确认确切的 2.16/0.92 这对数字**；独立检索到的相关 ML 策略 Sharpe 不同（如某相关设定中神经网 decile spread 的 1.35 VW / 1.45 EW）。2.16/0.92 可能来自某特定表格或二手转写。**视作貌似可信但未确认；未重核确切表格前，不可作为一手统计硬数字呈现给用户**（这反而强化本研究自身告诫：headline Sharpe 多为毛成本/微盘重）。
- **【low · venue 引用风险】** Chen-Pelger-Zhu『Deep Learning in Asset Pricing…Management Science 2024…OOS 最优组合 SR 约 2.1』——SR 约 2.1 OOS 数字与 Management Science 70(2) 2024 venue **已佐证**。但有一处本研究未标注的真实引用风险：文献中也**误引**本文为『Review of Financial Studies 2021, vol 34, 5133-5185』（另一篇论文的坐标），且**更高的样本内 Sharpe（约 2.6–2.68 训练）流传并易与 OOS 数混淆**。应钉死 OOS-vs-样本内区分与唯一正确 venue，避免传播常见误引。
- **【low · 作者署名误引】** FactorVAE 归于『Duan, Wang, Lai, Huang, Zhu (2022)』，**作者列疑误**。AAAI 2022 元数据给出作者为 **Duan, Y.; Wang, L.; Zhang, Q.; Li, J.**。本研究的『Lai, Huang, Zhu』共同作者与权威引用不符。虽小，但为非技术用户自动生成的模型卡**不应携带错误作者归属**。
- **【low · 内部张力】** Chen-Zimmermann (2022) 被与 McLean-Pontiff 并列、用作『假定实盘 alpha 远低于回测』的支撑权威，**存在本研究未承认的内部张力**。Chen-Zimmermann 更广的工作（含『Publication Bias in Asset Pricing Research』『Do t-Statistic Hurdles Need to Be Raised?』）主张**相反**的乐观：约 98% 信号可复制、可预测性 OOS 持续、FDR<10%、收缩仅 10–15%、发表偏差并不主导。引为"已知因子复现标尺"没问题，但**一边重用 McLean-Pontiff 强衰减、一边援引 Chen-Zimmermann 当盟友，回避了这些作者主动反驳强衰减叙事**。产品应把衰减呈现为**有争议**，而非已定论的"base case"。
- **【陷阱 · 不可外推】** headline Sharpe（CAE 约 2.16、CPZ 约 2.1）**是毛成本、常微盘重**；Nechvátalová (2025) 显示剔除非流动名+计成本后利润崩塌——**永远不要不带净成本/可交易宇宙版本就向用户引用这些数字**。
- **【陷阱 · 最可能的静默失败】** VAE prior-posterior 模型**合法地**在训练时用未来收益；若推理路径或过度热心的自动化管线**曾经泄露**该未来信息，回测 Sharpe 即被伪造。这是单一最可能的静默失败模式。
- **【陷阱 · 衰减是 base case 非例外】** 约 26%/58%（McLean-Pontiff）的已发现优势预期在 OOS/拥挤后消失；DL 挖出的因子不豁免，机械型（动量/反转类）可能衰减更快。
- **【陷阱 · 卖方复现弱】** AlphaNet/AlphaNetV4 报告大超额但少有泄露控制、验证方法或代码的公开——**工业宣称视作未核实**。
- **【陷阱 · 低信噪+非平稳】** 使 DL 因子脆弱、易过拟合；同一模型可训练指标强而 OOS 差，seed/初始化方差可淹没真实优势，除非集成。
- **【陷阱 · 可解释性仅事后】** SHAP/attention 满足治理观感但**不使模型被因果理解**；对非技术用户过度宣称"模型找到了价值因子"是真实风险。
- **【陷阱 · 已知因子重叠】** DL 隐因子常只是重新发现动量/价值/盈利/流动性；无对既有动物园（Chen-Zimmermann）的重叠测试，OS 可能把重命名 beta 当新 alpha 卖。

## 8. 开放问题

1. **治理时效性（研究最大漏点）**：整个机构实践节建在 SR 11-7 上，**已非现行指引**（2026-04-17 被 SR 26-2 取代）。研究漏掉了最新、最直接相关的监管发展；而讽刺的是 SR 26-2 的风险化（非日历化）重验哲学**比研究采用的年度框架更贴合自治 Agent OS**。
2. **IPCA 基线本身有争议（研究当作不可撼默认）**：IPCA 被呈现为不容置疑的"保守默认"，但它有公开批评——**Fieberg et al.『Characteristics are Covariances? A Comment on IPCA』**质疑 IPCA 的"characteristics 即 covariances"诠释是否成立。若 IPCA 是 DL 模型须击败的基线，OS 应知道**基线本身被质疑**。
3. **A 股特有结构性摩擦被低估**（A 股腿走"到 paper"）：Nechvátalová 的微盘/流动性批评是美+国际的；A 股另加研究从未点名的混淆——**T+1 结算、10%/20% 涨跌停**（截断可实现收益、破坏成交假设）、强散户流 regime 切换、频繁 IPO/停牌缺口。AlphaNet/FactorVAE 在 A 股回测可能正因这些摩擦未建模而显得强——**比交易成本单独更大的可交易性缺口**。
4. **无容量 / AUM 衰减分析**：研究定性提拥挤但从未量化——挖同一 characteristic 动物园的 DL 隐因子，会与它们重新发现的已发表异象**共享容量**；"对 Chen-Zimmermann 重叠测试"抓标签新颖性、**抓不住容量争用**。两个"不同"的 DL 因子载于同一拥挤的流动性/反转交易，共享同一衰减时钟。
5. **DL 搜索本身的多重检验 / 选择偏差**：研究正确要求对**输出**因子做 CSCV/PBO，但对**产生**它们的架构/超参/seed 搜索引入的数据挖掘膨胀（试了多少架构、在 validation Sharpe 上早停、seed 挑拣）只字未提。这是与因子级 PBO 不同的过拟合通道，也是 DL 管线最静默膨胀之处。
6. **crypto 腿几乎完全未触及**：所引模型（IPCA、CAE、CPZ、FactorVAE、AlphaNet）全是在大型股票面板上验证的股票横截面模型；研究从未问 characteristic 工具化隐因子模型**能否迁移**到无基本面、24/7、历史短得多的约数百个流动 token 的 crypto 横截面。"资产无关"对 crypto-to-Binance 目标是**断言、未证明**。
7. **治理产物本身的成本/延迟无处理**：设计方向承诺每个训练因子自动生成 SHAP/permutation 面板、泄露审计、漂移监控、重叠测试——对非技术单用户，这份计算+维护负担（尤其大宇宙深网每次重训的 SHAP）**可能吞掉因子边际价值**；研究从未权衡治理外壳在本产品规模下是否负担得起。

## 9. 参考文献（URL）

- Gu, Kelly & Xiu (2021), *Autoencoder Asset Pricing Models*, J. Econometrics 222(1), SSRN 3335536 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3335536
- Nechvátalová (2025), *Autoencoder asset pricing models and economic restrictions — international evidence*, IES WP 2024-26 — https://ies.fsv.cuni.cz/sites/default/files/uploads/files/wp_2024_26_nechvatalova.pdf
- Kelly, Pruitt & Su (2019), *Instrumented Principal Component Analysis*, JFE 134(3), SSRN 2983919 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2983919
- Chen, Pelger & Zhu (2024), *Deep Learning in Asset Pricing*, Management Science 70(2), arXiv:1904.00745 — https://arxiv.org/abs/1904.00745 ；DOI — https://pubsonline.informs.org/doi/10.1287/mnsc.2023.4695
- Duan, Wang, Zhang & Li (2022), *FactorVAE*, Proc. AAAI 36(4):4468–4476 — https://ojs.aaai.org/index.php/AAAI/article/view/20369
- Kelly, Malamud & Zhou (2024), *The Virtue of Complexity in Return Prediction*, J. Finance 79(1), NBER w30217 — https://www.nber.org/papers/w30217
- Nagel (2025), *Seemingly Virtuous Complexity in Return Prediction*（VoC 批评） — https://bpb-us-w2.wpmucdn.com/voices.uchicago.edu/dist/f/575/files/2025/07/Complexity_2.pdf
- Buncic (2025), *Simplified*（VoC 批评，SSRN 5239006） — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5239006
- McLean & Pontiff (2016), *Does Academic Research Destroy Stock Return Predictability?*, J. Finance 71(1) — https://www.fmg.ac.uk/sites/default/files/2020-08/Jeffrey-Pontiff.pdf
- Chen & Zimmermann (2022), *Open Source Cross-Sectional Asset Pricing*, Critical Finance Review — https://www.openassetpricing.com/ ；arXiv:2209.13623 — https://arxiv.org/abs/2209.13623
- HireVAE (IJCAI 2023) — https://www.ijcai.org/proceedings/2023/545
- AlphaNetV4 (华泰, arXiv:2411.04409) — https://arxiv.org/abs/2411.04409
- 资产定价可解释性（SHAP/permutation on DL β） — https://www.sciencedirect.com/science/article/pii/S1544612325017738
- DL 资产定价复现/无泄露实践 — https://arxiv.org/abs/2403.06779
- Federal Reserve SR 11-7（旧，已被取代） — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- Federal Reserve SR 26-2（现行，2026-04-17 生效） — https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm
- NIST AI Risk Management Framework (AI RMF 1.0) — https://www.nist.gov/itl/ai-risk-management-framework
- microsoft/qlib（含 FactorVAE 等参考实现） — https://github.com/microsoft/qlib
- bkelly-lab/ipca（官方 IPCA 包） — https://github.com/bkelly-lab/ipca
- OpenSourceAP/CrossSection（Chen-Zimmermann） — https://github.com/OpenSourceAP/CrossSection
- 社区 CAE 复现（rongwang0824） — https://github.com/rongwang0824/Autoencoder-Asset-Pricing-Models
