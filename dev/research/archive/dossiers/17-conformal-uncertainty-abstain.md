# 17 · 不确定性量化 + abstain（conformal/CQR/ACI）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 C

## 1. 一句话定位

在信号层用**分布无关**方法给每个预测配上"区间 / 置信"，并据此决定**是否下单（abstain）或缩仓**——把"区间 + abstain"做成贯穿全程 Agent OS 的一个标准 gate（一等公民），所有 ML/DL 信号模型统一经过一个 conformal 校准层，对外只暴露 `{点预测, 预测区间, abstain 标志, 触发原因}`，让"今天为什么不交易 / 为什么减仓"成为对小白用户可解释的自然语言理由。

---

## 2. 前沿 SOTA 与代表系统

| 系统 / 方法 | 它是什么 · 对本环节意味着什么 | URL |
|---|---|---|
| **Adaptive Conformal Inference (ACI)** — Gibbs & Candès, NeurIPS 2021 | 在线自适应：只追踪单参数自适应调整 miscoverage 水平 α_t（上一区间漏掉真值就放宽、覆盖到就收紧），保证**长程平均覆盖**收敛到 1−α，与任何点 / 分位预测器即插即用。非平稳时序 UQ 的事实基线。局限：是长程 / 渐近覆盖，短期或单个 regime 内可大幅偏离；γ 步长需调。 | https://arxiv.org/abs/2106.00170 |
| **DtACI（Dynamically-tuned ACI）** — Gibbs & Candès, 2024 | ACI 升级：一组不同步长的"专家" + 指数重加权在线聚合，**免手调 γ**，对漂移速率自适应。适合 regime 切换速度未知的中低频场景。 | https://jmlr.org/papers/volume25/22-1218/22-1218.pdf |
| **Conformalized Quantile Regression (CQR)** — Romano, Patterson, Candès, NeurIPS 2019 | 分位回归 + split CP：区间宽度随输入 / 波动**异方差自适应**，比固定宽度 CP 更短且仍保边际覆盖。金融最相关——区间宽度天然编码波动率 / 风险，可直接驱动缩仓与 abstain。 | https://arxiv.org/abs/1905.03222 |
| **EnbPI** — Xu & Xie, ICML 2021 | Ensemble 的 leave-one-out 残差做校准，**免数据切分**、可顺序产出无限多区间；假设误差过程平稳强混合而非可交换。注意：2026 独立基准显示其在 ARIMA 类设置会**欠覆盖**。 | https://proceedings.mlr.press/v139/xu21h.html |
| **SPCI（Sequential Predictive Conformal Inference）** — Xu & Xie, ICML 2023 | 自适应重估非一致性分数的条件分位（利用残差时间依赖），区间显著更窄、渐近条件覆盖。代码开源。但同一基准报其**欠覆盖最严重**——窄区间换覆盖的典型风险。 | https://proceedings.mlr.press/v202/xu23r.html |
| **Conformal PID Control** — Angelopoulos, Candès, Tibshirani, 2024 | 把"产出区间"当控制问题，用 P/I/D 反馈纠正覆盖误差，绕开可交换性假设。是当前在线 conformal 的强基线之一。（核查降权：见 §7，"对抗任意分布漂移"措辞偏营销） | https://arxiv.org/pdf/2307.16895 |
| **Nonexchangeable CP（俗称 NexCP）** — Barber, Candès, Ramdas, Tibshirani, Annals of Statistics 2023 | 对历史校准样本**加权**（近的权重大）以应对漂移；理论上覆盖缺口被"权重所诱导分布与真实分布的距离"上界控制——给出"漂移越大、保证越松"的诚实刻画。 | https://projecteuclid.org/journals/annals-of-statistics/volume-51/issue-2/Conformal-prediction-beyond-exchangeability/10.1214/23-AOS2276.pdf |
| **Conformal Risk Control** — Angelopoulos, Bates, Fisch, Lei, Schuster, ICLR 2024 | 把 split CP 的覆盖保证推广到"**任意单调损失期望**"的控制（如假阴率、F1、自定义交易亏损）。对 abstain 极重要：可把弃权阈值直接绑定到"坏单率 / 尾部损失"的有限样本保证上。开源 PyTorch 实现。 | https://arxiv.org/abs/2208.02814 |

**开源工具线**

| 工具 | 说明 | URL |
|---|---|---|
| **MAPIE**（scikit-learn-contrib） | 最主流的 Python CP 库，sklearn 风格 API，支持回归区间 / 分类集合 / 时序（含 EnbPI、ACI 风格）与 risk control。中低频 sklearn 管线的首选基座。 | https://github.com/scikit-learn-contrib/MAPIE |
| **TorchCP** | 面向 PyTorch / 深度学习的 CP 库，校准与推理最快；适合模型中心里的 DL/.pt 模型接 CP 校准层。 | https://www.jmlr.org/papers/volume26/24-2141/24-2141.pdf |
| **conformal-risk**（Angelopoulos 官方） | Conformal Risk Control 官方 PyTorch 代码：控制任意单调损失期望，可把 abstain 阈值绑定到坏单率 / 尾损保证。 | https://github.com/aangelopoulos/conformal-risk |
| **SPCI-code**（Xu & Xie 官方） | SPCI 参考实现，研究"更窄区间"方向时的对照基线（注意其欠覆盖风险）。 | https://github.com/hamrel-cxu/SPCI-code |
| **crepes / PUNCC / Fortuna** | 其他 CP 库：crepes（conformal regressors / predictive systems）、PUNCC（回归 / 分类 / 异常检测，但弱于现代 DL）、Fortuna（贝叶斯 + CP）。作为对照与功能补充。 | https://arxiv.org/pdf/2405.02082 |

---

## 3. 关键论文（每条带 URL）

1. **Adaptive Conformal Inference Under Distribution Shift**（Gibbs & Candès, NeurIPS 2021）
   单参数在线更新 α_t，证明在分布随时间任意演化时仍获**长程目标覆盖**，且与任意 ML 预测器即插即用。是非平稳金融 UQ 的奠基与默认基线。
   ⚠️ 核查限定：保证是**长程 / 渐近**性质，短期、单个 regime 内可大幅偏离（见 §7）。
   ref: arXiv:2106.00170 — https://arxiv.org/abs/2106.00170

2. **Conformalized Quantile Regression**（Romano, Patterson, Candès, NeurIPS 2019）
   CP + 分位回归得到异方差自适应、有限样本**边际**覆盖、区间更短。波动率高时区间自动变宽 → 天然的缩仓 / abstain 信号。
   ref: arXiv:1905.03222 — https://arxiv.org/abs/1905.03222

3. **Conformal Prediction Beyond Exchangeability**（Barber, Candès, Ramdas, Tibshirani, Annals of Statistics 2023）
   放弃可交换性、用加权样本，覆盖缺口被分布漂移距离上界。提供"漂移加剧时保证退化多少"的可量化诚实边界，是时序 CP 的理论支柱。
   ⚠️ 核查限定：原论文称 *nonexchangeable conformal prediction*，**并未自称 NexCP**；"总变差距离"是其常被引用的**直觉化表述**而非论文逐字定理（gap 上界严格说是按权重对每个交换性破坏项加权求和）。属命名 / 表述精度的轻微滑动，不影响实质结论（见 §7）。
   ref: Annals of Statistics 51(2) — https://projecteuclid.org/journals/annals-of-statistics/volume-51/issue-2/Conformal-prediction-beyond-exchangeability/10.1214/23-AOS2276.pdf

4. **Machine Learning with a Reject Option: A Survey**（Hendrickx et al., Machine Learning 2024）
   系统区分"**模糊拒绝**"（有数据但模型学不准该区域）与"**新颖性拒绝**"（输入落在训练几乎无数据的区域 = OOD / regime 偏离）。这正是本环节两类 abstain 触发器的理论命名来源。
   ref: arXiv:2107.11277 / ML J. 2024 — https://arxiv.org/abs/2107.11277v2

5. **Conformal Risk Control**（Angelopoulos, Bates, Fisch, Lei, Schuster, ICLR 2024）
   把覆盖保证推广为任意单调损失期望的控制，紧致到 O(1/n)。可把 abstain 阈值 / 区间大小直接绑定到对交易坏单率或尾部损失的有限样本保证。
   ref: arXiv:2208.02814 — https://arxiv.org/abs/2208.02814

6. **Conformal Prediction Algorithms for Time Series Forecasting: Methods and Benchmarking**（2026 独立基准）
   独立基准：5/8 方法达 90% 目标覆盖（Global-CP / AcMCP / MSCP / ACI / Parametric-PI），而 **EnbPI、SPCI、Nixtla-CP 欠覆盖（SPCI 最重）**；有效方法中简单 **MSCP 区间效率最优**、ACI 最适应非平稳但效率最低。结论：覆盖-宽度-适应性三角权衡，**无银弹，窄区间方法易暗中欠覆盖**。
   ⚠️ 核查限定（重要外推限制）：该基准**只用 AutoARIMA 作唯一基预测器、刻意排除神经网络**。EnbPI/SPCI 的设计初衷恰是搭配 ML/DL 模型，在纯 ARIMA 线性设置下评其欠覆盖，对"模型中心产出 ML/.pkl、DL/.pt 后接 CP 校准层"这一目标场景**可外推性存疑**（见 §7）。
   ref: arXiv:2601.18509 — https://arxiv.org/html/2601.18509

7. **When Alpha Breaks: Two-Level Uncertainty for Safe Deployment of Cross-Sectional Stock Rankers**（2026）
   金融直证：对日频跨截面选股区分 aleatoric / epistemic 两级不确定性，用 CP 构造带覆盖保证的预测集，在高不确定期 abstain，换取部署可靠性、缓解 alpha 衰减。
   ⚠️ 核查降权（HIGH）：**2026-02-24 arXiv 预印本，无评审、无复现、无引用记录**（见 §7）。
   ref: arXiv:2603.13252 — https://arxiv.org/pdf/2603.13252

8. **The Confidence Gate Theorem: When Should Ranked Decision Systems Abstain?**（2026）
   为排序型决策系统给出最优弃权阈值的理论刻画（置信门），直接对应跨截面排序信号的 abstain 决策。
   ⚠️ 核查降权（HIGH）：**单作者（Ronald Doku）预印本，2026-03-11**；"与 CP 分布无关保证精神一致"是**松散类比而非证明**（见 §7）。
   ref: arXiv:2603.09947 — https://arxiv.org/pdf/2603.09947

9. **Conformal Risk Control for Nonstationary Portfolio VaR**（Schmitt, 2026）
   把 conformal risk control 用于非平稳组合 VaR：在 regime 切换 / 结构突变期维持目标风险覆盖。把 UQ 从信号层延伸到组合风险层的桥梁。
   ⚠️ 核查降权（HIGH）：**2026-02-03 预印本**；虽在 CRSP 真实数据上有实验，但作者**本人**结论是"time-weighted 是 drift 下的强默认、regime-weighting 仅在部分设置改善"，**远弱于研究发现暗示的"优于参数化 VaR"的普适性**（见 §7）。
   ref: arXiv:2602.03903 — https://arxiv.org/pdf/2602.03903

10. **Pitfalls of Conformal Predictions（医学影像, 2025）+ 条件覆盖不可能性**
    边际覆盖 ≠ 条件覆盖：整体覆盖 90% 下子群可低至 62%；且**分布无关的精确条件覆盖在有限校准集下被证明不可能**。对"按 regime abstain"是关键警告——必须用 Mondrian / group-conditional 近似分 regime 校准。
    ⚠️ 核查降权（MEDIUM）："白人 92% / 黑人 62%"是**说明性 / 二手数字**（源头可追溯到 *Fair Conformal Predictors for Applications in Medical Imaging*, AAAI 2022 的 95%/5% 分布示例），**被误表述为一手实证**（见 §7）。结论本身（边际 ≠ 条件、有限样本精确条件覆盖不可能）由 Vovk 2012 / Lei-Wasserman 2014 / Barber 2021 确证。
    ref: arXiv:2506.18162 — https://arxiv.org/pdf/2506.18162

---

## 4. 机构最佳实践 / 标准

- **SR 11-7（Fed/OCC 2011）模型风险管理**：模型须有明确的局限性文档、独立验证、和"持续监控"——UQ **区间宽度、滚动覆盖回测、abstain 率**天然就是 SR 11-7 要求的监控指标与有效性挑战证据。新型 AI 模型可保留 SR 11-7 为合规锚、叠加 NIST 等组件。
  来源：Federal Reserve SR 11-7 / OCC 2011-12；ModelOp 解读 — https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7

- **NIST AI RMF 五大职能 Map / Measure / Manage / Monitor / Document**：把不确定性度量、漂移监控、弃权策略纳入 Measure + Monitor；但 RMF **不规定**具体聚合 / UQ 方法，需自行选 CP 等技术填空——给本产品留出"用 CP 作为 Measure 标准件"的空间。
  来源：NIST AI Risk Management Framework（AI 100-1）— https://arxiv.org/pdf/2401.15229

- **金融 ML 反过拟合纪律（López de Prado 体系）**：meta-labeling 分离方向与仓位、用模型置信度做 bet sizing、低置信不下注；与 CP-abstain **哲学同源**，可互为佐证。配合 DSR/PBO/CSCV 防止"弃权策略"本身被回测过拟合。
  来源：Advances in Financial Machine Learning；Meta-Labeling — https://en.wikipedia.org/wiki/Meta-Labeling
  ⚠️ 核查降权（LOW）："哲学同源 / 互为佐证"仅是**哲学 / 直觉类比，不是技术等价或互证**——meta-labeling 无分布无关有限样本保证，CP 给的是集合 / 区间有效性，两者保证类型**不可互换**（见 §7）。

> 治理标准的关键提醒：SR 11-7 / NIST AI RMF **不直接规定** CP，只要求"持续监控 + 漂移检测 + 模型局限文档化"。不能把"我们用了 conformal"当合规终点；真正的证据是持续的覆盖回测与 abstain 监控仪表盘。

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅概念级方向，不点 file:line、不排实施计划。

1. **把"区间 + abstain"设计为贯穿 Agent OS 的标准 gate（一等公民），而非单模型附属。**
   任何信号模型（ML/.pkl 或 DL/.pt）从模型中心产出后，统一经过一个 conformal 校准层，对外只暴露 `{点预测, 预测区间, abstain 标志, 触发原因}`。让上层组合 / 执行 agent 永远拿到带不确定性的信号，"流程即信任"落到信号层。

2. **abstain 触发分两条正交通道，分别对应综述里的两类拒绝。**
   (a) **模糊性拒绝** = 区间过宽 / 分位置信不足（用 CQR 区间宽度阈值或 conformal risk control 把"坏单率"控住）；
   (b) **新颖性拒绝** = 输入 / 特征 / regime 偏离训练分布（OOD / drift 检测），与项目已有的 **regime 模块**和 **universe PIT 数据通道**对齐——regime 偏离训练分布时优先走新颖性 abstain。两通道独立可解释，便于给小白用自然语言说清"今天为什么不交易"。

3. **默认方法选型遵循"诚实保守优先于花哨"。**
   基座用 **split CP + CQR**（异方差自适应、稳）；非平稳适配优先 **ACI / DtACI 或 Conformal PID** 这类长程覆盖有保证的在线控制器；对 SPCI / EnbPI 这类"更窄区间"方法保持怀疑——任何更窄区间的方法都必须先过**滚动覆盖回测**证明没有暗中欠覆盖（2026 基准已警示其欠覆盖）。
   ⚠️ 注意：该基准只用 ARIMA 基模型、排除神经网络，对"CP 接 ML/DL"场景外推性存疑（§7）——故"对 SPCI/EnbPI 保持怀疑"应表述为**待自家滚动覆盖回测裁决**，而非"已被判欠覆盖"。

4. **正视"边际覆盖 ≠ 条件覆盖"这一硬限制。**
   产品最想要的是 **regime-条件覆盖**，而分布无关精确条件覆盖在有限样本下不可能。方向是用 **Mondrian / group-conditional CP**——按 regime / 资产簇分层校准，在每个 regime 内分别保覆盖；并把"各 regime 的覆盖回测"作为模型卡与 Run 详情里的显式诊断，暴露欠覆盖子群而非用整体覆盖掩盖。
   ⚠️ 张力（见 §8 开放问题）：分组越细越想要条件覆盖，但分组越细每组校准样本越少越保不住——尤其崩盘 / 稀有 regime 这个最想保覆盖的分组。

5. **把 UQ 与 abstain 接进 SR 11-7 / NIST AI RMF 式的治理闭环。**
   滚动覆盖率、平均区间宽度、abstain 率、漂移指标作为持续监控的一等指标；当滚动覆盖跌破阈值或漂移超限，自动升级为"仅产出区间 + 全局 abstain / 降级"状态（与已锁定的 D3 = "实盘 agent 仅警告 + 规则停"一致），并把这些指标沉淀为模型局限性文档，服务于"人只出意图"的可审计性。

6. **严守无泄露纪律以保住区间"有效性"。**
   CP 的保证完全依赖校准集与生产分布的一致性和无 look-ahead。把 conformal 校准接到项目已有的 **walk-forward / PIT 管线**上（校准残差只用 shift-1 之后、PIT 正确的数据），并在弃权策略本身上套 **DSR/PBO/CSCV**，防止"abstain 规则"被回测过拟合成又一个虚假策略。

7. **把不确定性显式分成 aleatoric 与 epistemic 并据此驱动不同动作。**
   aleatoric（市场固有噪声，不可减，信噪比低就该多 abstain）→ 直接缩仓或弃权；epistemic（模型 / 数据不足，可随数据补充管线缓解）→ 提示用户补数据 / 再训练。这与"按用户风格个性化"结合：让用户 / 经济学者用自然语言设定其可接受的覆盖水平 1−α 与弃权偏好（保守者高覆盖宽区间多弃权），agent 据此参数化整条 conformal 管线。
   ⚠️ 防呆要求（见 §8）：1−α 直接决定区间宽度与 abstain 率，小白用户极易设出在低信噪比金融数据上**根本不可达 / 几乎永不或永远交易**的 α；且事后看回测调 α 本身是一种数据窥探——交互面须加**合理区间约束与防呆**。

8. **把信号层 UQ 向组合 / 风险层延伸但分清边界。**
   用 conformal risk control 思路对组合层 VaR / 尾损做覆盖保证（参考非平稳组合 VaR 工作），与 López de Prado 的置信度 → bet sizing 哲学打通——信号置信低不仅可二元 abstain，也可**连续缩仓**，给中低频策略一个平滑的"区间 → 仓位"映射，而非只有开 / 关两态。
   ⚠️ 注意（§7）：组合 VaR 那篇是**未复现预印本**，其结论也只支持"time-weighted 是强默认"，不支持"普适优于参数化 VaR"——此方向应标注为"前沿探索"，而非已验证落地。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意草图，不接线到现有代码。

**6.1 conformal 校准层输出 schema（信号层统一契约）**

```yaml
signal_with_uncertainty:
  model_id: str                      # ML/.pkl 或 DL/.pt，来自模型中心
  asset: str
  asof: date                         # PIT 对齐，shift-1 之后
  point: float                       # 点预测
  interval: [lo, hi]                 # CQR 异方差自适应区间
  target_coverage: 0.90              # 1-α，用户/风格可配（须防呆约束）
  abstain: bool
  abstain_channel: ambiguity | novelty | none   # 两条正交通道
  abstain_reason: "区间宽度 0.21 > 阈值 0.15（aleatoric 高）"
  regime: str                        # 与 regime 模块对齐
  uncertainty_split:                 # aleatoric/epistemic 两级
    aleatoric: 0.18                  # 高→缩仓/弃权
    epistemic: 0.04                  # 高→提示补数据/再训练
  size_multiplier: 0.0..1.0          # 区间→仓位的平滑映射（非开/关两态）
```

**6.2 双通道 abstain 决策（概念伪代码）**

```python
def conformal_gate(x, model, calib_by_regime, cfg):
    regime = detect_regime(x)                      # 与 regime 模块对齐
    # 通道 b：新颖性拒绝（输入/regime 偏离训练分布）
    if is_ood(x, model.train_support) or regime not in calib_by_regime:
        return abstain(channel="novelty",
                       reason="regime/特征偏离训练分布")
    # Mondrian：按 regime 分层取校准残差（条件覆盖近似）
    calib = calib_by_regime[regime]                # ⚠ 分层后样本可能很少
    lo, hi = cqr_interval(x, model, calib, alpha=1 - cfg.target_coverage)
    # 通道 a：模糊性拒绝（区间过宽/坏单率不可控）
    if (hi - lo) > cfg.width_ceiling or bad_trade_risk(lo, hi) > cfg.tau:
        return abstain(channel="ambiguity",
                       reason=f"区间宽度 {hi-lo:.2f} 超阈/坏单率超控")
    return signal(point=model.predict(x), interval=[lo, hi],
                  size=interval_to_size(lo, hi))   # 平滑缩仓，非二元
```

**6.3 治理监控指标（持续覆盖回测 → 自动降级）**

```
滚动指标（每 regime × 滚动窗口）:
  rolling_coverage     目标 ≈ 1-α；跌破阈值 → 触发
  mean_interval_width  区间宽度（效率）
  abstain_rate         弃权率（机会成本侧另需净值回测，见 §8）
  drift_score          输入分布漂移（NexCP 加权/PIT 偏移）

触发逻辑（对齐 D3 实盘"仅警告+规则停"）:
  if rolling_coverage < floor  or  drift_score > ceil:
      degrade -> "仅产出区间 + 全局 abstain/降级"
      log -> 模型局限性文档（SR 11-7 / NIST 持续监控证据）

⚠ 监控触发器本身是被反复观察的统计量 → 多 regime/多窗口反复检验
  覆盖率会带来多重比较问题，须做 FWER/FDR 校正（见 §8），否则
  大量假阳性停用 / 假阴性放行。
```

**6.4 方法分层（诚实保守优先）**

```
基座    : split CP + CQR（异方差自适应、稳、边际覆盖）
非平稳  : ACI / DtACI / Conformal PID（长程平均覆盖的在线控制器）
漂移加权: NexCP（加权样本，覆盖缺口被漂移距离上界）
风险层  : Conformal Risk Control（abstain 阈值绑定坏单率/尾损）
怀疑区  : SPCI / EnbPI（更窄区间）——必须先过自家滚动覆盖回测
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 对抗核查总判：**方法学骨架扎实、引用基本可靠，但金融"落地证据"层存在明显的成熟度夸大，且有两处经验性 / 二手数字被升格为硬实证。** 核心方法学全部核实无误（ACI / CQR / EnbPI / SPCI / Conformal PID / Beyond Exchangeability / Conformal Risk Control / DtACI / Hendrickx reject-option 综述 / 条件覆盖不可能性——作者、venue、核心论断均经得起核查，**无撤稿、无伪造引用**）。降权后核心方向（把区间 + abstain 做成贯穿 Agent OS 的标准 gate、双通道 abstain、Mondrian 分 regime 覆盖回测、接 SR 11-7/NIST 治理闭环、绑 walk-forward/PIT）**仍然站得住**，但"金融已被验证"的叙事必须降级为"**方法学成熟、金融落地仍是前沿未定区**"。

**HIGH 严重度**

- ⚠️【证据成熟度夸大 / 未复现新文献撑结论】**三篇金融"落地证据"（'When Alpha Breaks' 2603.13252、'Confidence Gate Theorem' 2603.09947、'Conformal Risk Control for Nonstationary Portfolio VaR' 2602.03903）被当作 CP/abstain 在金融已落地的证据**——这三篇**全部是 2026 年 2-3 月的 arXiv 预印本**（分别 2026-02-24、2026-03-11、2026-02-03），距今仅数周到数月，**均无同行评审、无第三方复现、无引用记录**。Confidence Gate Theorem 更是**单作者（Ronald Doku）预印本**，其"与 CP 分布无关保证精神一致"是**松散类比而非证明**。把"数周前刚挂出的单 / 双篇预印本"表述为"金融落地证据正在出现"，是用**未复现的新鲜文献支撑结论**，属典型的证据成熟度夸大——与已知雷区中"PROV-AGENT 仅单一环境评估不可外推"同类问题。VaR 那篇虽在 CRSP 真实数据上有实验，但作者**本人结论**是"time-weighted 是 drift 下的强默认、regime-weighting 仅在部分设置改善"，**远弱于研究发现暗示的"优于参数化 VaR"的普适性**。

**MEDIUM 严重度**

- ⚠️【二手数字 + 经验性强度夸大】**边际覆盖 ≠ 条件覆盖在医学影像里"已被实证"：白人 92%、黑人 62%**——这个 92%/62% 数字**并非来自所引的 2506.18162（'Pitfalls of Conformal Predictions'）的一手实验测量**，而是该领域用来解释"边际 vs 条件覆盖"概念的**说明性范例**，其源头可追溯到 *Fair Conformal Predictors for Applications in Medical Imaging*（AAAI 2022）中关于 95% 白 /5% 黑数据分布下的**示例性论述**。研究发现用"已被实证""实证子群低至 62%"这种措辞，把一个**说明性 / 示意性数字升格为硬实证结果**——属二手数字 + 经验性强度夸大。**结论（边际 ≠ 条件覆盖、有限样本精确条件覆盖不可能）本身是对的**（Vovk 2012 / Lei-Wasserman 2014 / Barber 2021 确证），但用来佐证它的那个具体百分比的"实证"地位被高估。

- ⚠️【外推过度 / 单一线性基模型设置不可外推】**2026 独立基准（2601.18509）显示 EnbPI/SPCI 在 ARIMA 类设置欠覆盖、MSCP 效率最优，据此对 SPCI/EnbPI"更窄区间"方法保持普遍怀疑**——基准结论本身**核实无误**（Global-CP/AcMCP/MSCP/ACI/Parametric-PI 达 90%；Nixtla-CP/EnbPI/SPCI 欠覆盖，SPCI 最重）。但有一个被研究发现一笔带过、实则致命的外推限制：该基准**明确只用 AutoARIMA 作为唯一基预测器、刻意排除了神经网络等复杂预测器**。EnbPI/SPCI 的设计初衷恰恰是**搭配 ML/DL 模型**，在纯 ARIMA 线性设置下评其欠覆盖，对"模型中心产出 ML/.pkl、DL/.pt 后接 CP 校准层"这一**目标场景的可外推性存疑**。把一个单一线性基模型设置下的排名当作对 SPCI/EnbPI 的普遍"欠覆盖"判决，是**外推过度**。这点应作为对该证据的**强限定**，而非仅作为方法选型的脚注。

**LOW 严重度**

- ⚠️【对单个方法能力轻度夸大 / 措辞营销化 / 自相矛盾】**Conformal PID Control 被列为"绕开可交换性、对抗任意分布漂移，是当前在线 conformal 的强基线之一"**——措辞偏营销化。该方法（Angelopoulos-Candès-Tibshirani）给的是把覆盖误差当控制信号的**长程 / 在线纠偏**，本质上与 ACI 一样提供的是**长窗口平均覆盖的渐近性质**，并不"对抗任意分布漂移"到能保短期 / 单 regime 覆盖的程度——这与研究发现自己在 pitfalls 里诚实承认的"在线方法是长程性质、崩盘期混合性失效会给过窄区间"**相矛盾**。"对抗任意分布漂移"的表述与同篇的诚实分级**自相打架**，属对单个方法能力的轻度夸大。

- ⚠️【命名 / 表述精度轻微滑动】**NexCP 作为 'Conformal Prediction Beyond Exchangeability' 的方法名，覆盖缺口被权重诱导分布与真实分布的总变差距离上界控制**——论文（Barber-Candès-Ramdas-Tibshirani, Annals of Statistics 2023）本身**核实无误**，作者 / 期刊 / 年份正确，加权样本 + 覆盖缺口被分布漂移距离上界的核心思想也正确。但"**NexCP**"这一名称是研究发现（及部分二手文献）的**简写**，原论文使用的是"nonexchangeable conformal prediction"，**并未自称 NexCP**；且原文的 gap 上界严格说是**按权重对每个交换性破坏项加权求和**的形式，"总变差距离"是其常被引用的**直觉化表述而非论文逐字定理**。属命名 / 表述精度的轻微滑动，**不影响实质结论**。

- ⚠️【类比强度轻度夸大 / 标准一致性不足】**把 López de Prado 的 meta-labeling/bet-sizing 与 CP-abstain 表述为"哲学同源、可互为佐证"**——这是**哲学 / 直觉层面的类比，不是技术等价或互证**。meta-labeling 给的是**无分布无关有限样本覆盖保证**的启发式置信度 → 仓位映射；CP 给的是集合 / 区间**有效性保证**。把二者"互为佐证"会让读者误以为 meta-labeling 能为 CP 的覆盖保证背书（或反之），实则两者**保证类型不可互换**——研究发现自己在 pitfalls 第 8 条也承认"贝叶斯 /MC-dropout 等无分布无关保证、不能替代 CP"。这条与那条标准一致性不足，属类比强度轻度夸大。

**通用陷阱清单（设计须规避）**

- **可交换性假设系统性失效**：经典 split CP/CQR 的有限样本保证建立在 exchangeability 上，而金融时序有自相关、波动聚集、regime 切换，直接套用 split CP 在实盘会丢失覆盖保证。必须用 ACI/NexCP/Conformal PID 等非可交换方法，但要清楚它们换来的是"**长程 / 加权**"保证而非逐点保证。
- **边际覆盖 ≠ 条件覆盖（最危险）**：90% 整体覆盖完全可能在某个 regime / 某段时间 / 某资产簇系统性欠覆盖，而你最想保的恰是 regime 条件覆盖。分布无关的精确条件覆盖在有限校准集下**被证明不可能**，只能用 Mondrian 近似 + 分群覆盖回测，**不能用整体数字自我安慰**。
- **"更窄区间"常以暗中欠覆盖为代价**：2026 独立基准显示 SPCI/EnbPI 在 ARIMA 类设置欠覆盖（SPCI 最重）。论文常用区间宽度当卖点，但**宽度短若不达覆盖即是无效**；选型必须以滚动覆盖回测为准绳，警惕"越花哨越好"的叙事。
- **在线方法的覆盖是长程 / 渐近性质**：ACI 等保证的是长窗口平均覆盖，短期、单个 regime 内可大幅偏离；**崩盘等极端期混合性假设失效会给出过度乐观（过窄）的区间——恰在最需要 abstain 时最不可靠**。
- **校准集泄露会让区间"看着严谨实则失真"**：若校准残差用了含 look-ahead / 重叠标签 / 未 PIT 对齐的数据，CP 保证名存实亡。这是金融 CP **最隐蔽的坑**，必须与项目 walk-forward/PIT 纪律强绑定。
- **弃权策略本身会被过拟合**：在回测里调 abstain 阈值 / regime 触发器极易制造"只在好时段交易"的幸存者偏差。需对弃权规则套 DSR/PBO/CSCV，否则 abstain 只是又一层数据窥探。
- **治理标准不提供现成方法**：SR 11-7/NIST AI RMF 说"要监控、要量化不确定性"，但不规定用哪种 UQ；不能把"我们用了 conformal"当作合规终点，真正的证据是**持续的覆盖回测与 abstain 监控仪表盘**。
- **贝叶斯 /MC-dropout / 深集成等替代 UQ 无分布无关有限样本保证、且校准常困难**——可作为 CP 的"信号源 / 底层不确定性估计"但**不能替代 CP 的覆盖保证**；反过来 CP 给的是集合 / 区间有效性，不直接给逐点概率，abstain 设计需想清要的是"覆盖保证"还是"逐点概率"。

---

## 8. 开放问题

> 以下为对抗核查指出的**漏点（missing angles）**，研究稿完全缺席或仅一句带过，是落地前必须回答的。

1. **计算 / 延迟成本与中低频可行性完全缺席。** SPCI 用 quantile regression forest 在线重估残差条件分位、DtACI 并行跑多个 ACI 专家、Conformal PID 每步反馈，这些在线方法**每个 bar 都要重算**，对"对话式、人只出意图"的产品其延迟 / 算力预算如何？中低频（日频）虽缓解，但跨数千标的的 Mondrian 分 regime 校准会让校准集在每个分组内迅速变小——这正好撞上下一条。

2. **Mondrian / group-conditional 校准的有限样本可行性自相矛盾未被点破。** 研究发现一边承认"分布无关精确条件覆盖在有限校准集下不可能"，一边把 Mondrian 分 regime 校准当解药。但按 regime × 资产簇分层后，每个 bin 的校准样本数急剧下降（尤其崩盘 / 稀有 regime——**恰恰是最想保覆盖的那个**），小样本下 CP 区间会退化为极宽或覆盖剧烈波动。"**分组越细越想要条件覆盖、但分组越细每组样本越少越保不住**"这个根本张力没有被量化或正视。

3. **abstain 的策略后果（机会成本 / 路径依赖）未评估。** 全局 abstain 在崩盘期意味着空仓躲过下跌（好），但也可能**错过 V 型反弹或在 regime 误判时系统性踏空**；abstain 率本身会与策略容量、换手、交易成本交互。研究发现把 abstain 当**纯安全阀**，未讨论"频繁弃权导致的收益拖累 / abstain 触发的自我实现式踏空"这一面，缺少对 abstain 决策本身做**净值层面的成本-收益与回测**。

4. **覆盖回测的多重检验 / 数据窥探未被纳入反过拟合纪律。** 研究发现提到对 abstain 阈值套 DSR/PBO/CSCV，但没提"**滚动覆盖回测**"本身作为模型监控指标也是被反复观察的统计量——在多 regime、多窗口上反复检验覆盖率会带来多重比较问题，"某个 regime 覆盖跌破阈值就停用"的触发器若不做多重检验校正，会产生**大量假阳性停用（或假阴性放行）**。监控指标的统计显著性如何控制 **FWER/FDR**，完全没谈。

5. **标签重叠 / 样本权重对 CP 校准的特殊破坏未细化。** 金融重叠标签（overlapping labels，如 20 日前瞻收益）会让校准残差**强相关**，这不仅违反可交换性，还会让**有效校准样本数远小于名义样本数**（López de Prado 的 uniqueness / average uniqueness 问题）。研究发现笼统说"无泄露 / PIT 对齐"，但没指出**重叠标签会使 CP 名义覆盖的有效样本量被高估**这一具体且隐蔽的失效模式。

6. **缺少与更简单基线的对照论证。** 既然 2601.18509 基准的结论是"简单的 MSCP/Parametric-PI 在有效方法里效率最优、花哨方法易暗中欠覆盖"，那么是否中低频场景下**直接用固定宽度 split CP + 简单时间加权就已足够**，而 CQR/ACI/Conformal PID 的额外复杂度是否真带来与其工程 / 治理成本相称的收益？研究发现默认选型已偏向 CQR+ACI/PID，但没做"**复杂度是否值得**"的反向论证——与该基准"无银弹、简单常胜"的精神略有张力。

7. **1−α 由用户自然语言设定的安全隐患。** design_directions 提议让小白用户 / 经济学者用自然语言设定可接受覆盖水平 1−α 与弃权偏好。但 α 的选择直接决定区间宽度与 abstain 率，**小白用户极易设出在低信噪比金融数据上根本不可达或导致几乎永不 / 永远交易的 α**；且用户事后看回测调 α 本身就是一种**数据窥探**。这个"人只出意图"的交互面缺少**防呆 / 合理区间约束**的讨论。

---

## 9. 参考文献（URL）

**核心方法学（conformal 家族）**
- Gibbs & Candès (2021), Adaptive Conformal Inference Under Distribution Shift (ACI) — https://arxiv.org/abs/2106.00170
- Gibbs & Candès (2024), Conformal Inference for Online Prediction with Arbitrary Distribution Shifts (DtACI) — https://jmlr.org/papers/volume25/22-1218/22-1218.pdf
- Romano, Patterson & Candès (2019), Conformalized Quantile Regression (CQR) — https://arxiv.org/abs/1905.03222
- Xu & Xie (2021), Conformal Prediction Interval for Dynamic Time-Series (EnbPI) — https://proceedings.mlr.press/v139/xu21h.html
- Xu & Xie (2023), Sequential Predictive Conformal Inference for Time Series (SPCI) — https://proceedings.mlr.press/v202/xu23r.html
- Angelopoulos, Candès & Tibshirani (2024), Conformal PID Control for Time Series Prediction — https://arxiv.org/pdf/2307.16895
- Barber, Candès, Ramdas & Tibshirani (2023), Conformal Prediction Beyond Exchangeability — https://projecteuclid.org/journals/annals-of-statistics/volume-51/issue-2/Conformal-prediction-beyond-exchangeability/10.1214/23-AOS2276.pdf
- Angelopoulos, Bates, Fisch, Lei & Schuster (2024, ICLR), Conformal Risk Control — https://arxiv.org/abs/2208.02814

**abstain / reject option / 基准 / 条件覆盖限制**
- Hendrickx et al. (2024), Machine Learning with a Reject Option: A Survey — https://arxiv.org/abs/2107.11277v2
- Conformal Prediction Algorithms for Time Series Forecasting: Methods and Benchmarking (2026) — https://arxiv.org/html/2601.18509
- Pitfalls of Conformal Predictions（医学影像, 2025）— https://arxiv.org/pdf/2506.18162

**金融落地（⚠ 全为 2026 未复现预印本，见 §7）**
- When Alpha Breaks: Two-Level Uncertainty for Cross-Sectional Stock Rankers (2026) — https://arxiv.org/pdf/2603.13252
- The Confidence Gate Theorem: When Should Ranked Decision Systems Abstain? (2026) — https://arxiv.org/pdf/2603.09947
- Conformal Risk Control for Nonstationary Portfolio VaR (Schmitt, 2026) — https://arxiv.org/pdf/2602.03903

**机构治理 / 标准**
- SR 11-7 模型风险管理（Fed/OCC，ModelOp 解读）— https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7
- NIST AI Risk Management Framework（AI 100-1）— https://arxiv.org/pdf/2401.15229
- Meta-Labeling（López de Prado 体系）— https://en.wikipedia.org/wiki/Meta-Labeling

**开源工具**
- MAPIE（scikit-learn-contrib）— https://github.com/scikit-learn-contrib/MAPIE
- TorchCP — https://www.jmlr.org/papers/volume26/24-2141/24-2141.pdf
- conformal-risk（Angelopoulos 官方）— https://github.com/aangelopoulos/conformal-risk
- SPCI-code（Xu & Xie 官方）— https://github.com/hamrel-cxu/SPCI-code
- crepes / PUNCC / Fortuna（CP 库综述）— https://arxiv.org/pdf/2405.02082
