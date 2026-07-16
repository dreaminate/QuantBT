---
name: math-kernel-seam-matrix-20260716
description: 金融数学 kernel P0 接缝勘定（seam analysis）——三方并集（主 Claude + deep-opus ‖ codex/GPT-5.6-sol）本仓复核 [[math-spine-gap-analysis-gpt-20260716]] 断言 vs spine 实码。承 [[math-kernel-p0-p3-decomposition-draft-20260716]]（草案要求「没勘缝前不写 math/ 代码」的门票）。
status: 勘缝已完 · 待用户拍主干取舍/优先级/依赖（decision-ready）· 未实装
type: seam-analysis
---

> **三方并集**：主 Claude（骨架+关键断言独立核实）‖ deep-opus（16 主干全扫）‖ codex/GPT-5.6-sol（跨厂商·192 测实跑核现有能力+官方 license 核）。approver≠creator。**静态源码核实为主·未执行 math 代码**（"缺"类=grep+import 缺失+无 `app/math/` 三角推断·中高置信；"已建"类=直接读源·高置信）。

## 0. 地基纠偏（GPT + 本仓草案都错的一条·影响全局定性）

GPT gap 分析（:29）与本仓 P0-P3 草案（:13）都说现有 spine 已有 `EstimatorSpec/RiskMeasure/OptimizationProblem/MeasureContext/FiltrationSpec/StochasticProcessSpec` typed 对象——**夸大**。实测（deep-opus + codex 独立核实一致）：

- **真实存在的 typed 类只有 7 个**：`TheorySpec`(lineage/spine.py:158)·`ImplementationSpec`(:199)·`MathematicalArtifact`(research_os/spine.py:353·**`artifact_type: str` 通用容器**)·`TheoryImplementationBinding`(:450)·`ConsistencyCheck`(:400)·`MethodologyChoiceRecord`(:262)·`ResponsibilityDisclosureRecord`(:323)。
- `estimator`/`risk_measure`/`measure_context` 等**只是 `artifact_type: str` 的枚举字符串取值**（lineage/spine.py:70/122），不是类。`MathematicalRequirement` 是 enum 成员不是类。
- 模块自承「容器 + 内容寻址身份·不证明数学成立」（lineage/spine.py:13）。

**这不削弱、反而坐实 GPT 核心论点**：数学产物全塞进一个字符串打标容器，类型层比 GPT 自己列的还薄。→ **P0 首切必须建真 typed 计算对象（measure/process/numerical），且 typed 对象 + 数值实现 + oracle 同时落，否则变成第二层治理文本。**

## 1. Seam Matrix（16 主干 × 三方并集分级 × file:line）

分级：✅已覆盖(现码够·别重造) / 🟡部分(有可接基线·别推倒·但 GPT 点名项确缺) / ❌缺(真无)。**deep-opus 与 codex 分级差主要在衍生品/利率/FX/基金**：codex 记「typed 合约在(market_data_contract.py 的 Option/Bond/Future/Fx/Commodity Spec)=部分接缝」，deep-opus 记「定价数学全缺=缺」——**并集=合约 typed 层在、定价/Greeks/曲线数学缺**。

| # | 主干 | 分级(并集) | 关键 file:line | 杠杆薄纵切(Inference) |
|---|---|---|---|---|
| 1 | 随机过程/随机分析 | ❌缺 | 无 `app/math/`;合成"GBM"实为正态收益×(1+r)(datasets/samples.py:57);spine 文本容器 | **P0-A** `MeasureContext+FiltrationSpec+StochasticProcessSpec`+GBM typed process |
| 2 | 数值金融/校准 | ❌缺 | 唯一数值 oracle=DSR profile(spine_numerical_verifier.py:27);优化只 MV(optimizers.py:43) | **P0-A** `NumericalSchemeSpec+ErrorBudgetSpec`+Euler-Maruyama(GBM exact oracle·记 strong/weak err) |
| 3 | 金融计量/状态空间 | 🟡部分 | IC 有 Newey-West(factor_factory/ic.py:60);regime 明说规则法非 HMM/GARCH(regime/detector.py:11) | **P1** `EstimatorSpec+StateSpaceSpec`·先 local-level Kalman/MLE 再 GARCH |
| 4 | 资产定价 SDF-GMM | ❌缺 | 无 SDF/GMM;"Fama-MacBeth"只 docstring(factor_factory/layered.py:3·实为分位分组) | **P1** `MomentConditionSpec+SDFSpec+GMMEstimatorSpec`·线性因子 GMM+Hansen J |
| 5 | 面板/横截面 | 🟡部分 | IC/RankIC/NW(ic.py:19/113)+分层诊断在;正式 FMB+双向 cluster SE 缺 | **P1** `PanelEstimatorSpec`·Fama-MacBeth+entity/time cluster |
| 6 | 尾部风险 Copula-EVT | ❌缺 | `var_max` 只 schema 字段(strategy_goal.py:34);无 GPD/copula 计算 | **P0-A**(并 #7) `TailModelSpec+CopulaSpec`·POT/GPD→VaR/ES→Kupiec/Christoffersen |
| 7 | 机构市场风险 | 🟡部分 | `RiskLimits`=单笔/日亏/集中度/强平(risk/checks.py:29)=**交易护栏非度量**;risk_summary 只 flag(eval/risk_summary.py:201) | **P0-A** `RiskMeasureSpec+ScenarioSpec+RiskRunRecord`·历史/参数 VaR+ES+component/marginal+回验+压力 |
| 8 | 稳健多期组合 | 🟡部分 | **risk_parity 明写 1/σ(optimizers.py:70)·约束求解后截断(:153)·固定α收缩(hrp_audit.py:61)** | **P0-A** 先改名 inverse-vol·`CovarianceEstimatorSpec+RiskBudgetSpec+OptimizationProblemSpec`·自动 Ledoit-Wolf+真 ERC+成本进目标 |
| 9 | 期权/波动率面 | 🟡部分(合约在·定价缺) | `OptionSpec` 明说 Greeks/IV 不计算(market_data_contract.py:1329) | P2 `PricingContext+OptionModelSpec+VolSurfaceSpec`·先静态无套利+BS |
| 10 | 利率/固收 | 🟡部分(合约在·定价缺) | `BondSpec` 明说 duration/convexity 是声明值非推导(:1295) | P2 `CurveSpec+CashflowSpec+BondPricerSpec` |
| 11 | 信用/XVA | ❌缺 | required family 只 option/future/bond/fx/commodity(market_coverage.py:55)·连 credit typed family 都无 | P3 `CreditCurveSpec+CounterpartySpec+NettingSetSpec` |
| 12 | FX/期货/商品 | 🟡部分(合约在·定价缺) | Future/Fx/CommoditySpec 在(:1314/1350/1382);forward/basis/quanto/carry 计算缺 | P2 `ForwardBasisSpec+CarryCurveSpec+RollAdjustmentSpec` |
| 13 | 最优执行/微观结构 | 🟡部分 | 平方根冲击单式(execution/impact.py:21);TCA 只 gross-总成本(methodology_validation.py:568) | **P1.5** `ExecutionModelSpec+ScheduleSpec`·Almgren-Chriss 闭式+IS 分解 |
| 14 | 因果推断 | ❌缺 | `EconomicMechanism` 明说不跑因果算法(strategy_goal.py:92)=治理文本 | P2 `CausalEstimandSpec+TreatmentSpec`·先 DiD/IV+placebo |
| 15 | 贝叶斯/序贯 | 🟡部分 | ACI(conformal.py:182)+CUSUM/PH(monitor/drift.py:170/215)=真序贯;无 Bayesian posterior/MCMC | P2 `PriorSpec+PosteriorSpec`·先共轭 |
| 16 | 基金/ETF 混合 | 🟡部分(识别在·穿透缺) | `EquitySpec.is_etf/underlying_index_ref`(:1282);Tushare 仅登记 NAV(tushare_provider.py:903) | P2 `FundVehicleSpec+LookThroughHoldingsSpec` |

**✅ 已覆盖（GPT 承认成熟·P1+ 复用别重造·均核到真实现）**：PBO/CSCV(pbo.py:58)·DSR/PSR/MinTRL(dsr.py:59/97/157)·bootstrap CI(bootstrap.py:39)·Honest-N/Effective-N(n_eff.py:77)·conformal/CQR/ACI(conformal.py)·防泄露 CV(models/cpcv.py·purged_cv.py·walk_forward_v2.py)·理论-实现绑定门(eval/spine_bindings.py·但窄=只绑防过拟合五统计)。

## 2. GPT 六条具体仓库缺陷断言复核（主 Claude 独立核实 #3/#7 铁证）

| GPT 断言 | 核实 | file:line |
|---|---|---|
| risk_parity 实为逆波动率 | ✅属实(主 Claude 亲核) | optimizers.py:70 docstring「权重∝1/σ」+ `inv=1/sigma;w=inv/inv.sum()` |
| 无 VaR/ES 市场风险引擎 | ✅属实(主 Claude grep 仅假阳:env:VAR/np.var) | 无任何 VaR/ES/Kupiec/genpareto 实现 |
| 约束=优化后截断 | ✅属实 | constraints.py:21 + optimizers.py:153(约束在 minimize 后调用) |
| 协方差收缩=固定 α=0.2 fallback | ✅属实 | hrp_audit.py:61 docstring 自承「生产应用 sklearn 自动估 α」 |
| DeepAR 只 μ 头·MSE 训练非概率似然 | ✅属实 | dl/architectures.py:252 + dl/trainer.py:147 |

**结论**：GPT gap 主体属实（16 主干 6 全缺+10 部分+防自欺统计成熟），六条具体缺陷全有铁证；唯一纠偏=typed 对象清单夸大（§0）。GPT 无一条把已建评成缺失。

## 3. Prior-art / oracle + license（codex 官方源核·全 permissive 无 GPL/AGPL）

**关键 dep-hygiene（codex 逮）**：`requirements.txt` 只声明 pandas/scipy/sklearn(:6)；**statsmodels 在本机但未进 requirements·本机 pandas 3.0.3 ≠ 声明 2.3.2**。→ "L1 已装" 须拆「本机可 import」vs「项目可复现依赖」；建 statsmodels 前先补声明+版本矩阵。

| 目标 | L1(requirements 已声明) | L2 候选(oracle/引擎) | license(codex 官方核) |
|---|---|---|---|
| VaR/ES/EVT(6+7) | scipy.stats.genpareto/norm/t·numpy | arch(回验+bootstrap oracle) | scipy BSD-3·arch 3-clause |
| 真 ERC+自动收缩(8) | scipy.optimize·sklearn.covariance.LedoitWolf/GraphicalLasso/OAS | riskfolio/PyPortfolioOpt(oracle)·cvxpy(约束优化引擎) | sklearn BSD-3·riskfolio BSD-3·PyPortfolioOpt MIT·cvxpy Apache-2.0 |
| measure/process/SDE typed+数值(1+2) | 纯 Python dataclass·numpy RNG·scipy | QuantLib(数值 oracle) | QuantLib modified-BSD |
| FMB+cluster SE+GRS(4+5) | numpy OLS 自实现 | linearmodels.FamaMacBeth/PanelOLS/LinearFactorModelGMM(oracle) | linearmodels 3-clause |
| GARCH/状态空间(3) | (statsmodels 本机·须补声明) | arch(GARCH)·statsmodels(Kalman/SARIMAX/VAR/VECM) | statsmodels BSD-3·arch 3-clause |
| Almgren-Chriss(13) | numpy 闭式 | 论文 L3(Almgren-Chriss 2000) | — |

**机构市场风险方法锚**=Basel FRTB/ES 框架(不把运行时限额冒充度量)·SDF-GMM=Hansen 1982·GARCH-EVT/ES=McNeil-Frey 2000。

## 4. 待拍板归类（decision-ready）

**方法学门槛（用户拍·放权：已摆代价+给推荐·标 Inference 即可放行不停摆）**：
- 6 条真缺主干哪些真做/优先级/起做时机（草案排 agent epic 之后·agent M6b 现已 land）。
- **P/Q 测度与衍生品定价(9-12)是否在范围内**——鉴于「A股永不实盘」+ 当前 equity/crypto 聚焦，可能 scope 外（scope 判断=用户）。
- 各主干口径：VaR 置信度/持有期/lookback/P&L mapping/stress set·POT 阈值/copula family·panel cluster 轴/test assets·组合 risk budget/CVaR α·执行 benchmark/λ·因果识别假设·Bayesian prior/stopping。
- （无需重决）MathCapabilityMatrix L6 硬度已由 [[D-GOVERNANCE-LIGHT]] 定 advisory；L2 数值收敛/L3 校准绑真 DatasetVersion 是 correctness 硬门。

**新依赖（用户拍·[[prior-art-first]] 红线：不擅自装）**：优先序建议 `linearmodels(dev-only) → statsmodels(先补声明) → arch → cvxpy → QuantLib`；PyMC/EconML/DoWhy 暂不进首批。**P0-A #7/#8 用现声明 scipy+sklearn 即可建·oracle 库(arch/riskfolio)可只进 dev 测试依赖·主运行时零新增。**

**correctness 可自决（agent·无方法学/无新依赖·须数学 epic greenlit 后）**：改名 risk_parity→inverse_volatility(保 alias 不破基线)·固定 α→sklearn.covariance.LedoitWolf 自动·scipy 版 VaR/ES/GPD 数值·类型/单位/维度/PIT-filtration 一致性/解析恒等式/数值收敛阶/solver fail-closed/静态无套利/oracle tolerance/失败不染绿。

## 5. Decision-ready brief（给用户）

**真缺 top-6（按杠杆·三方一致）**：① VaR/ES+EVT-POT 市场风险引擎 ② 组合 correctness(真 ERC/自动收缩/约束进优化+诚实改名) ③ P/Q measure+process typed 层+数值底座 ④ Fama-MacBeth+GRS 横截面检验 ⑤ GARCH/Kalman 计量 ⑥ Almgren-Chriss 执行。

**推荐先做（我方裁决·四面权衡）**：**并集把 P0-A 定为「①VaR/ES+②组合 correctness+③measure typed 层」三者·均零新运行时依赖**。若只挑一个先起：
- **VaR/ES+EVT-POT 引擎（deep-opus 首选）**——机构风险地基缺件·价值最高·scipy 现声明即产 Historical/Parametric/MC VaR+ES+Kupiec/Christoffersen+GPD 尾部·与 risk/checks.py 实盘风控正交不撞(那是操作限额·这是度量)·arch 只 dev oracle。**代价**=一薄纵切(typed RiskMeasureSpec+scipy 数值+arch 对照测试)·零主运行时新依赖·须拍 VaR 口径(可 Inference 默认 95%/99%·1-day)。
- **组合 correctness（codex 强调·次选）**——一次修 3 处点名缺陷+一处诚实改名·L1 零依赖·correctness-heavy 方法学最轻。
- **measure typed 层（架构地基·数值回报低但防泄露升级为数学可验证）**——须与数值实现+oracle 同落。

**依赖拍板**：P0-A 三条**不需新主依赖**；真正要拍的是 P1 起的 linearmodels/statsmodels/arch/cvxpy/QuantLib(全 permissive)。**起做时机=用户/中心 orchestrator 的闸**——本勘缝只交付「接缝地图+先做哪条」，agent M6b 已 land 故 gate 已开，具体主干选择/口径待用户拍或授权中心 orchestrator 自决。

**Unverified（codex 标·实装前须核）**：QuantLib 在 macOS/Python 3.13 wheel/build 兼容性·cvxpy solver 组合·真实校准数据可得性——均未实装验证。
