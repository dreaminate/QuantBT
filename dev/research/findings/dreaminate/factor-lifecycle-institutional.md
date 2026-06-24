# FINDING · §3 因子机构级生命周期度量（衰减半衰期 / 容量 / 因子族 / 拥挤）

- **蒸馏自**:GOAL §3「机构级因子生命周期（衰减/拥挤/容量/因子族/退役，跨策略复用的独立资产）」+「加密拥挤数据不足→只定性警示、禁自动减仓」+ 决策 R21（退役+去重一等流程、去重用收益序列相关聚类）/R18（平方根冲击 δ=0.5）/R19（拥挤数据不足只定性）+ 并行双脑（codex xhigh 独立推导，确认四公式 + 加固 ρ 不 clip / τ³ / corr-vs-距离阈 / 拥挤结构隔离）。
- **证据强度**:强 —— 半衰期=AR(1) 持久性标准式、容量=sqrt-impact（Almgren/Kyle，R18 δ=0.5）闭式、因子族=复用已变异验证的 n_eff 聚类口径（R8/R19）、拥挤=定性咨询（GOAL §3 数据不足红线）。
- **适用域**:中低频。**不成立的边界**：AR(1) 小样本 OLS 偏 ρ 向 0（local-to-unity 严重）→ 短样本判 insufficient/unstable；容量 sqrt-impact 仅在合理参与率区间可信；**加密拥挤数据碎片化/不足 → 只定性、禁自动减仓**（R19）。

## 核心主张（可证伪）[必填]

**如果**因子 IC 时序服从 AR(1)（持久性 ρ∈(0,1)），**则**衰减半衰期 h=ln(0.5)/ln(ρ)（ρ↑→h↑、ρ≥1→不衰减/undefined、绝不 clip ρ）；
**如果** sqrt 市场冲击 δ=0.5，**则**策略容量 **C=ADV·α²/(τ³·Y²·σ²)**（α≤0→容量 0、回代 cost(C)≈α 自检）；
**如果**因子收益高度相关，**则**因子族聚类把它们坍缩成 1 族（复用 n_eff 锁定口径，**家族数==n_eff cluster count** 交叉校验）；
**而**拥挤是**定性咨询**（none/watch/elevated + data_status），**结构上无任何减仓/haircut/动作字段**，数据不足判 insufficient ≠ 拥挤 0（GOAL §3 禁自动减仓）。

### 数学（公式 + 推导）

**① 衰减半衰期（AR(1) 持久性，默认）**
$$IC_t-\mu=\rho(IC_{t-1}-\mu)+\varepsilon_t\ \Rightarrow\ \text{冲击 }k\text{ 期后残留}=\rho^k\ \Rightarrow\ \rho^h=0.5\ \Rightarrow\ h=\frac{\ln 0.5}{\ln\rho}$$
- 边界（**绝不 clip ρ**）：0<ρ<1→有限正半衰期；ρ→1⁻→h→∞（no_decay）；ρ≥1→undefined（爆炸/非平稳）；ρ=0→h→0（no_persistence）；−1<ρ<0→反向震荡（正向持久半衰期 undefined，可另报幅度半衰期 ln0.5/ln|ρ|）；ρ≤−1→undefined。
- insufficient/unstable：配对样本 <min_periods（诊断≥30、sizing/退役≥60）/ lagged IC 方差≈0 / ρ 置信区间跨 0 或 1（unstable，不作硬退役依据）。
- 指数法 log|IC_t|=a−λt OLS、h=ln2/λ 作辅证（IC=0 炸、ε-floor 引偏，要求时间原点有意义）。小样本 OLS 偏 ρ 向下（codex）。

**② 容量（sqrt 市场冲击 δ=0.5）**
每期冲击成本占 AUM 比 = τ·Y·σ·(τ·AUM/ADV)^δ（τ=换手、Y=冲击系数、σ=波动、ADV=金额日均成交、δ=0.5）。净 alpha=α_gross−cost。容量 C = 净 alpha=0 时 AUM：
$$\alpha=\tau Y\sigma\Big(\frac{\tau C}{ADV}\Big)^{\delta}\ \Rightarrow\ C=\frac{ADV}{\tau}\Big(\frac{\alpha}{\tau Y\sigma}\Big)^{1/\delta}\ \xrightarrow{\delta=0.5}\ \boxed{C=\frac{ADV\cdot\alpha^2}{\tau^3\,Y^2\,\sigma^2}}$$
- 量纲：α,τ,σ 同周期无量纲比例；Y 无量纲；C 单位=ADV（金额）。**α 与 τ/σ/ADV 必须同周期**（年化 α 配日频 cost=错）。
- 边界：α≤0→容量 0（no_edge，数学上无正盈利容量）；τ≤0/ADV≤0/Y≤0/σ≤0→invalid（**绝不在此返普通容量数值**）。自检：cost(C) 回代应≈α。

**③ 因子族（R21 去重 · 收益相关聚类，复用 n_eff 锁定口径）**
corr_ij=corr(R_i,R_j)，dist=1−|corr|，average linkage，**合并 |corr|≥0.7**（= n_eff 距离 cutoff 1−0.7=0.3，**corr 阈非距离阈**，codex 钉清）。家族=簇；家族数=有效独立因子数（dedup，防换等价公式撑大）。
- **交叉校验命门**：`n_families == n_eff_from_matrix(rm).point`（同一锁定口径 → 两路必吻合，绑定 honest-N）。
- 边界：完全相同/完全相反（|corr|=1）→1 族；正交→N 族；block-diagonal→block 数族；列序/符号翻转→membership 不变；NaN corr **绝不填 0**（零方差列→自成一簇）。

**④ 拥挤（定性咨询 · GOAL §3 禁自动减仓）**
`CrowdingAdvisory{level∈{none,watch,elevated}, data_status∈{ok,partial,insufficient}, evidence:list}`——**结构上无** reduce_position/haircut/multiplier/trade_action。
- 代理（数据不足只能定性）：与拥挤篮 rolling corr（篮未验证/史短→定性）、估值价差（crypto 口径不稳→定性）、short interest/funding/OI（跨所碎片→定性）。
- **红线**：`missing ≠ crowding 0`（数据不足→data_status=insufficient/watch，绝不编码成 none 的证据）；elevated 只产 warning、**绝不产订单/目标仓位**；未来要减仓须新建人工批准 policy adapter，**绝不**在 lifecycle_metrics 暗加。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么(扩展不替换) |
|---|---|---|
| `app/factor_factory/lifecycle_metrics.py` | 新建 | ic_decay_half_life + strategy_capacity + factor_families + crowding_advisory + 结果 dataclass(value/status/method/n_obs/warnings) |
| `app/eval/n_eff.py` | 复用 `_cluster_count`/`_CORR_THRESHOLD`/`_LINKAGE` 口径 | 不改（因子族绑同一锁定口径） |
| `app/factor_factory/lifecycle.py` | toy 五态机 | 不改（本切片是度量层，喂状态机/sizing 的输入） |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. 半衰期：ρ=0.5→h=1、ρ=√0.5→h=2（解析点）；ρ↑→h↑单调；**ρ 被 clip 到 (0,1)** → ρ≥1 该 undefined 却返有限数 → 抓；短样本/方差≈0→insufficient（非假数）。
2. 容量：C∝ADV·α²/(τ³Y²σ²)——**τ 翻倍→C/8（τ³，最易写成 τ²）**、α 翻倍→C×4、ADV 翻倍→C×2；α≤0→容量 0；τ=0/σ=0→invalid（非普通数值）；回代 cost(C)≈α。
3. 因子族：相同/相反收益→1 族；正交→N 族；block→block 数；**家族数==n_eff.point**（口径漂移→交叉校验崩）；NaN corr 填 0 → 抓。
4. 拥挤命门：schema 扫字段名**禁** reduce/haircut/multiplier/action/target_weight（结构隔离，绝不自动减仓）；数据不足→data_status=insufficient 非 level=none；elevated 不产任何动作。

## 复用 [按需]
- `app/eval/n_eff.py`：`_cluster_count`/`_CORR_THRESHOLD`/`_THRESHOLD_BAND`/`_LINKAGE`（因子族同一锁定聚类口径，绑 honest-N）。
- `app/factor_factory/lifecycle.py`：FactorObservation（IC 序列来源）；本切片度量喂其状态机/sizing。

## 未验证残余（诚实）[必填]
- **AR(1) 小样本偏差**：ρ OLS 向 0 偏、local-to-unity 严重 → 长半衰期弱识别；本切片报 status(unstable/insufficient) + warnings，不做去偏（Kendall/jackknife）校正。
- **容量**：sqrt-impact 系数 Y/ADV/σ 须用户/数据提供（本切片给公式 + 边界，不估 Y）；仅合理参与率区间可信、未加 participation cap。
- **拥挤**：本切片是定性咨询 schema + 代理占位；真实拥挤篮/估值/short-interest 数据接入属上游（crypto 数据不足 → 永远定性，R19）。
- **因子族阈值**：复用 n_eff 锁定 0.7（R21「阈值二轮定」→ 暂用 honest-N 同口径，升口径=升 NEFF_CONFIG_VERSION）。
- **接线**：度量喂 lifecycle 状态机/sizing 的生产接线属后续（建议 mint）。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | 衰减半衰期/容量/因子族/拥挤 数学对齐理论、ρ 不 clip、容量 τ³、家族数==n_eff、拥挤无减仓字段、命门不变量守门 | P1 | — |
| (建议后续) | 度量接 lifecycle 状态机/sizing 生产路径（衰减→退役触发、容量→sizing 上限、因子族→组合独立 bet） | P2 | 本切片 |
